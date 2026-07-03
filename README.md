# NET·INV — AV Site Coordinator

Single-file, browser-only network device inventory tool for AV/show site work. No server, no build, no dependencies — `index.html` is the whole app.

## Quickstart

```bash
open index.html          # macOS
xdg-open index.html      # Linux
```

Or just double-click it. Works from `file://` or any static host.

## Data model

Device columns: `hostname, brand, model, ip, mac, vlan, subnet, location, serial, username, password, status, notes`

## Features

**Inventory table** — add/edit devices, column filters, bulk select + bulk actions, print stylesheet for handoff sheets.

**Brand/Model manager** — built-in catalog (`#netinv-brands-builtin`) + custom brand/model entries, persisted separately.

**VLAN manager** — custom VLAN list, tied into device records and CSV/JSON payloads.

**Subnet scanner** — target parser accepts single IP, CIDR (`192.168.1.0/24`), or dash range (`192.168.1.1-50`). Probes hosts client-side via `fetch(..., {mode:"no-cors"})` against a configurable port profile with timeout — this is a reachability probe, not a real SYN scan (browser sandboxing limits it to whatever ports the JS engine will attempt HTTP-ish connects on).

**Port profiles** — predefined port sets (web, etc.) for the scanner.

**Nmap import** — parses `-oN` (plain text), `-oG` (grepable), and `-oX` (XML) nmap output; appends discovered hosts to inventory.

**IP autofill** — sequential IP fill helper tied to the site subnet field.

**Ping/reachability log** — same no-cors fetch-probe technique, logged per device.

**Export/Import** — CSV and JSON round-trip (`exportCSV`/`exportJSON`, `impCSV`/`impJSON`). JSON export includes meta (site/subnet/date/engineer) and custom VLANs.

**Self-save (bake-to-HTML)** — `saveHTML()` pulls the current document source via synchronous XHR, injects current state as JSON into `<script id="netinv-baked">`, and downloads a new fully standalone `.html` with your data embedded. This is the primary save/handoff mechanism — the resulting file needs nothing but a browser to reopen with all data intact. Filename pattern: `<site>_<date>.html`.

**localStorage persistence** — `niv_d`/`niv_n`/`niv_m` keys auto-persist devices/nextId/meta between sessions in the same browser as a fallback when you haven't baked/saved.

**Fit-to-screen mode**, **Ctrl+S** shortcut (triggers `saveHTML()`), **copy-to-clipboard** on cells/rows.

## Persistence model — know the difference

- **Baked HTML** (`saveHTML()` / Ctrl+S): data lives inside the downloaded file itself. Portable, versionable, diffable in git.
- **localStorage**: browser-local fallback only. Doesn't survive a different browser/profile/machine. Don't rely on it for anything you'd be upset to lose.

## Server mode (Docker)

There's a second flavor under `server/` — same UI, backed by a small FastAPI + SQLite service instead of localStorage/bake-to-HTML. Use this when you want one shared, persistent inventory reachable from every machine on the LAN instead of passing `.html` snapshots around.

```bash
cp .env.example .env      # optional, defaults to port 8080
docker compose up -d --build
curl localhost:8080/api/health
```

Open `http://<host>:8080/`. Data lives in `./data/netinv.db` (bind-mounted, survives `docker compose down`).

**No auth** — this sits on your LAN/VLAN by design, not the open internet. Put it behind a reverse proxy (Caddy/Traefik/nginx) with Basic Auth if you need to expose it further.

**API:**

| Route | Method | Notes |
|---|---|---|
| `/api/health` | GET | liveness, used by the container healthcheck |
| `/api/state` | GET | full state blob (`devices`, `nextId`, `meta`, `customBrands`, `customVlans`) |
| `/api/state` | PUT | replace full state — the frontend debounces this on every edit |
| `/api/export.json` | GET | same as `/api/state`, semantic alias |
| `/api/export.csv` | GET | CSV pulled straight from the `devices` SQL table |
| `/api/stream` | GET | Server-Sent Events — one `state_updated` event per write, see below |
| `/api/probe` | POST | `{"ip":"..."}` → ping + ARP lookup, returns `{ip, reachable, mac}` |
| `/api/docs` | GET | Swagger UI (FastAPI auto-docs) |

**Auto MAC on reach-test** — a browser can never read ARP/L2 data, that's a hard sandboxing wall regardless of technique. But the server can: `⬢ Test All` / per-row reach-test now also calls `POST /api/probe`, which pings the IP (populates the kernel neighbor cache) then reads it back via `ip neigh show`. If a MAC resolves and the row's MAC field is empty, it's auto-filled and logged.

This only works if the container is L2-adjacent to your AV subnet:
- **Linux docker host** — run with the host-networking overlay: `docker compose -f docker-compose.yml -f docker-compose.host-net.yml up -d --build`. Real ARP against your actual LAN.
- **macOS Docker Desktop** — no true host network namespace, so ping still generally reaches LAN devices via NAT but `ip neigh` reflects the VM's own neighbor table, not your physical subnet. MAC will typically come back empty (fails closed, never guesses) — reach-test/status still works fine, you just won't get free MAC fill on Mac.

**Live updates** — every open tab subscribes to `/api/stream` (SSE, auto-reconnecting). When any client PUTs a change, every *other* tab refetches `/api/state` and re-renders within a second — no manual refresh. Each tab tags its own writes with an `X-Client-Id` header so it ignores its own echo. If you're mid-keystroke in a table cell when a remote update lands, it's held and applied on blur instead of yanking your cursor out from under you (full `render()` rebuilds the table's DOM, so applying it mid-edit would eat the character you're typing). The sub-bar badge (`● server` / `○ offline`) reflects both the state fetch and the stream connection.

In-memory pub/sub, single process — do **not** run `uvicorn --workers >1` or scale to multiple replicas, subscribers in one worker won't see broadcasts from another. Fine for the single-container/single-site use case this is built for; swap in Redis pub/sub if you ever need to scale out.

**CLI-friendly by design** — every write rematerializes a real `devices` table alongside the JSON blob, so you can query it directly without touching the API:

```bash
sqlite3 ./data/netinv.db "SELECT hostname, ip, vlan, status FROM devices ORDER BY vlan;"
```

Frontend behavior: on load it tries `GET /api/state`; if the server's unreachable it falls back to baked HTML → localStorage → sample data, same as the standalone build, and shows `○ offline (local cache)` in the sub-bar. Once the server's back, the next edit pushes local state up automatically. The `💾 Save HTML` bake-to-file button still works in server mode too — handy as an out-of-band backup or to hand a snapshot to someone off-network.

```
server/
  Dockerfile
  .dockerignore
  pyproject.toml
  app/
    __init__.py
    main.py          # FastAPI routes: /api/state, /api/stream (SSE), /api/probe, exports
    db.py            # SQLite schema, state blob + devices table
  static/
    index.html       # frontend copy, wired to /api/state + SSE instead of localStorage
docker-compose.yml            # repo root — build + run + volume + healthcheck
docker-compose.host-net.yml   # optional overlay, Linux only — real ARP for MAC probe
.env.example
.gitignore
```

## Repo

```
index.html   # standalone build — entire app, markup/styles/logic, single file
server/      # dockerized build — FastAPI + SQLite backend, same UI, shared/live inventory
```

No build step for the standalone file — edit in place, commit, done. The server build needs `docker compose up -d --build` after editing anything under `server/`.
