#!/usr/bin/env python3
"""Merge brand/model catalogs into the built-in catalog shipped with NET·INV.

    python3 tools/sync-brands.py                       # sync brands.json -> both HTML builds
    python3 tools/sync-brands.py ~/Downloads/netinv-brands.json [more.json ...]

Additive only: brands/models from brands.json, the extra files given, and the
<script id="netinv-brands-builtin"> blocks of index.html and
server/static/index.html are unioned, then written back to all three. Nothing
is ever removed or reordered — new brands go before "Other", new models are
appended. To delete an entry, edit brands.json AND both HTML blocks by hand.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "brands.json"
HTML_FILES = [ROOT / "index.html", ROOT / "server" / "static" / "index.html"]
BLOCK_RE = re.compile(
    r'(<script type="application/json" id="netinv-brands-builtin">\n)(.*?)(\n</script>)', re.S
)


def merge(into: dict[str, list[str]], src: dict, label: str) -> tuple[int, int]:
    if not isinstance(src, dict):
        sys.exit(f"{label}: expected a JSON object of {{brand: [models]}}")
    new_b = new_m = 0
    for brand, models in src.items():
        brand = str(brand).strip()
        if not brand:
            continue
        if brand not in into:
            into[brand] = []
            new_b += 1
        for m in models if isinstance(models, list) else []:
            m = str(m).strip()
            if m and m not in into[brand]:
                into[brand].append(m)
                new_m += 1
    return new_b, new_m


def render(cat: dict[str, list[str]]) -> str:
    # "Other" is the catch-all — keep it last
    keys = [k for k in cat if k != "Other"] + (["Other"] if "Other" in cat else [])
    lines = [f"  {json.dumps(k, ensure_ascii=False)}:{json.dumps(cat[k], ensure_ascii=False, separators=(',', ':'))}" for k in keys]
    return "{\n" + ",\n".join(lines) + "\n}"


def main() -> None:
    cat: dict[str, list[str]] = {}
    sources: list[tuple[str, dict]] = []
    if CATALOG.exists():
        sources.append(("brands.json", json.loads(CATALOG.read_text())))
    html = {}
    for f in HTML_FILES:
        text = f.read_text()
        m = BLOCK_RE.search(text)
        if not m:
            sys.exit(f"{f}: netinv-brands-builtin block not found")
        html[f] = text
        sources.append((str(f.relative_to(ROOT)), json.loads(m.group(2))))
    for arg in sys.argv[1:]:
        sources.append((arg, json.loads(Path(arg).expanduser().read_text())))

    for label, src in sources:
        b, m = merge(cat, src, label)
        if (b or m) and label != sources[0][0]:
            print(f"  + {label}: {b} new brand(s), {m} new model(s)")

    body = render(cat)
    CATALOG.write_text(body + "\n")
    for f, text in html.items():
        f.write_text(BLOCK_RE.sub(lambda m: m.group(1) + body + m.group(3), text, count=1))
    print(f"Catalog: {len(cat)} brands, {sum(map(len, cat.values()))} models -> brands.json + {len(html)} HTML builds")


if __name__ == "__main__":
    main()
