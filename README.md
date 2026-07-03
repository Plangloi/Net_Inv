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

## Repo

```
index.html   # entire app — markup, styles, logic, single file
```

No build step. Edit in place, commit, done.
