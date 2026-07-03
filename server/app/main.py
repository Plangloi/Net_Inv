"""NET-INV server mode.

Serves the static single-page frontend (server/static/index.html) and a
minimal JSON API backed by SQLite. The frontend already builds the exact
`{devices, nextId, meta, customBrands, customVlans}` shape in memory for its
localStorage / bake-to-HTML save paths — this API just gives it a server to
GET/PUT that same blob against instead, so a shared inventory survives
container restarts and is reachable from every machine on the LAN.

No auth by design — this is meant to sit behind your own network ACL /
reverse proxy / VLAN, not be exposed on the open internet. Bolt on
Basic Auth at a reverse proxy (Caddy/Traefik/nginx) if you need to expose it.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import db

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR.parent / "static"

app = FastAPI(title="NET-INV Server", docs_url="/api/docs", redoc_url=None)

# ─── LIVE UPDATES (Server-Sent Events) ─────────────────────────────────────
# One-way push: "state changed" — connected clients refetch /api/state on
# receipt. In-memory fan-out only, no broker — fine at this scale, but it
# means this MUST stay a single process. Do not run with `--workers > 1` or
# multiple replicas; subscribers in one worker never see broadcasts from
# another. If you ever outgrow that, swap this for Redis pub/sub.
_subscribers: set[asyncio.Queue] = set()


async def _broadcast(event: dict) -> None:
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.discard(q)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/state")
def read_state():
    return db.get_state()


@app.put("/api/state")
async def write_state(request: Request):
    body = await request.json()
    # Single-tenant tool, no auth boundary to enforce — trust the client
    # blob shape, just fill in defaults so a partial payload doesn't 500.
    state = {**db.EMPTY_STATE, **body}
    updated_at = db.put_state(state)
    client_id = request.headers.get("x-client-id", "")
    await _broadcast({"type": "state_updated", "updated_at": updated_at, "by": client_id})
    return {"status": "ok", "updated_at": updated_at}


@app.get("/api/stream")
async def stream(request: Request):
    """SSE endpoint — push channel for 'state changed, go refetch'."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    _subscribers.add(queue)

    async def gen():
        try:
            yield "retry: 2000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keep-alive comment — defeats proxy/LB idle timeouts
        finally:
            _subscribers.discard(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx: don't buffer this if you put it behind one
        },
    )


# ─── ARP / MAC PROBE ────────────────────────────────────────────────────────
# Ping resolves L3->L2 by populating the kernel's neighbor cache, then we
# read that cache back — the standard "arping"-adjacent trick. Requires the
# container to be L2-adjacent to the target subnet:
#   - Linux host, network_mode: host  -> real ARP for your actual LAN. Use
#     docker-compose.host-net.yml for this.
#   - Default bridge network (incl. macOS Docker Desktop) -> ping usually
#     still succeeds via NAT, but `ip neigh` reflects the bridge/VM's own
#     neighbor table, not your physical LAN's — MAC will typically come back
#     null, or in the worst case (proxy-ARP gateways) a wrong shared MAC. We
#     filter out FAILED/INCOMPLETE entries but can't fully detect that case,
#     so treat MACs from bridge-mode deployments as unverified.
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_MAC_RE = re.compile(r"([0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5})")


async def _ping_once(ip: str, timeout_s: float = 1.5) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", "1", ip,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False
    try:
        rc = await asyncio.wait_for(proc.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        return False
    return rc == 0


async def _arp_lookup(ip: str, timeout_s: float = 1.5) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ip", "neigh", "show", ip,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    line = out.decode(errors="ignore")
    if "FAILED" in line or "INCOMPLETE" in line or not line.strip():
        return None
    m = _MAC_RE.search(line)
    return m.group(1).lower() if m else None


class ProbeRequest(BaseModel):
    ip: str


@app.post("/api/probe")
async def probe(req: ProbeRequest):
    ip = req.ip.strip()
    if not _IPV4_RE.match(ip):
        return {"ip": ip, "reachable": False, "mac": None}
    reachable = await _ping_once(ip)
    mac = await _arp_lookup(ip)  # try even if ping failed — entry may predate this call
    return {"ip": ip, "reachable": reachable, "mac": mac}


@app.get("/api/export.json")
def export_json():
    return JSONResponse(db.get_state())


@app.get("/api/export.csv")
def export_csv():
    devices = db.list_devices()
    buf = io.StringIO()
    cols = ["id", *db.DEVICE_COLS]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(devices)
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=network-inventory.csv"},
    )


# Static frontend mounted last — catches everything not matched above.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
