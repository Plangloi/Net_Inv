"""SQLite persistence for NET-INV server mode.

Storage model: the full client-side state (devices/nextId/meta/customBrands/
customVlans) is kept as a single JSON blob in `kv_state` — that's the exact
payload shape the frontend already builds in memory for its localStorage /
bake-to-HTML save paths, so no relational refactor of the 2000+ line
frontend was needed to get a server backing it.

On every write the `devices` table is fully rematerialized from that blob,
so you get free CLI queryability against a real SQL table:

    sqlite3 /data/netinv.db "SELECT hostname, ip, vlan, status FROM devices;"
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("NETINV_DB", "/data/netinv.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    hostname TEXT, brand TEXT, model TEXT, ip TEXT, mac TEXT,
    vlan TEXT, subnet TEXT, location TEXT, serial TEXT,
    username TEXT, password TEXT, status TEXT, notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_devices_ip ON devices(ip);
CREATE INDEX IF NOT EXISTS idx_devices_vlan ON devices(vlan);
"""

EMPTY_STATE = {
    "devices": [],
    "nextId": 1,
    "meta": {"site": "", "subnet": "", "date": "", "engineer": ""},
    "customBrands": {},
    "customVlans": [],
}

DEVICE_COLS = [
    "hostname", "brand", "model", "ip", "mac", "vlan", "subnet",
    "location", "serial", "username", "password", "status", "notes",
]


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def get_state() -> dict:
    with connect() as conn:
        row = conn.execute("SELECT payload FROM kv_state WHERE id = 1").fetchone()
        if row is None:
            return dict(EMPTY_STATE)
        return json.loads(row["payload"])


def put_state(state: dict) -> str:
    """Persist the full blob and rematerialize the devices table for CLI/SQL access."""
    now = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(state)
    with connect() as conn:
        conn.execute(
            """INSERT INTO kv_state (id, payload, updated_at) VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET payload = excluded.payload,
                                              updated_at = excluded.updated_at""",
            (payload, now),
        )
        conn.execute("DELETE FROM devices")
        rows = [
            (d.get("id"), *[d.get(c, "") for c in DEVICE_COLS])
            for d in state.get("devices", [])
            if d.get("id") is not None
        ]
        if rows:
            conn.executemany(
                f"INSERT INTO devices (id, {', '.join(DEVICE_COLS)}) "
                f"VALUES (?, {', '.join(['?'] * len(DEVICE_COLS))})",
                rows,
            )
    return now


def list_devices() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            f"SELECT id, {', '.join(DEVICE_COLS)} FROM devices ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
