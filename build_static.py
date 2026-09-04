#!/usr/bin/env python3
"""Build the static site into docs/ (for GitHub Pages / any static host).

docs/index.html   - the viewer, with static mode switched on
docs/data.json    - stars, galaxies, landmarks and graph edges from starnav.db
docs/planets.json - planet positions (written by fetch_planets.py; kept if present)
"""
import json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "docs")
os.makedirs(OUT, exist_ok=True)

server.init_db()
conn = sqlite3.connect(server.DB_PATH); conn.row_factory = sqlite3.Row
if conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='star'").fetchone()[0] == 0:
    server.refresh_stars()
if conn.execute("SELECT COUNT(*) FROM nodes WHERE note IS NOT NULL").fetchone()[0] == 0:
    server.refresh_landmarks()
if conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='galaxy' AND note IS NULL").fetchone()[0] == 0:
    server.refresh_galaxies()

sources, src_index = [], {}
def sid(s):
    if s not in src_index:
        src_index[s] = len(sources); sources.append(s)
    return src_index[s]

sig = lambda v: float(f"{v:.7g}") if v is not None else None
nodes = []
for r in conn.execute("SELECT * FROM nodes WHERE kind NOT IN ('sun','planet','moon','dwarf')"):
    n = {"id": r["id"], "name": r["name"], "kind": r["kind"], "x": sig(r["x"]), "y": sig(r["y"]), "z": sig(r["z"]),
         "s": sid(r["source"])}
    for k in ("mag", "dist_pc"):
        if r[k] is not None: n[k] = sig(r[k])
    for k in ("color", "spect", "con", "note"):
        if r[k]: n[k] = r[k]
    nodes.append(n)
edges = [dict(r) for r in conn.execute("SELECT src,dst,rel FROM edges WHERE src NOT IN "
                                       "(SELECT id FROM nodes WHERE kind IN ('planet','moon','dwarf'))")]
edges = [e for e in edges if e["rel"] != "near" or not e["src"].startswith(("hyg-", "fb-"))]   # star->sun edges are implicit
meta = {k: v for k, v in server.get_meta().items() if k != "epoch"}
with open(os.path.join(OUT, "data.json"), "w") as f:
    json.dump({"nodes": nodes, "edges": edges, "sources": sources, "meta": meta}, f, separators=(",", ":"))

html = open(os.path.join(ROOT, "static", "index.html")).read()
html = html.replace("<script>\nconst AU_KM", "<script>window.STATIC = true;</script>\n<script>\nconst AU_KM", 1)
assert "window.STATIC = true" in html, "could not inject static flag"
with open(os.path.join(OUT, "index.html"), "w") as f:
    f.write(html)
open(os.path.join(OUT, ".nojekyll"), "w").close()
print(f"built docs/: {len(nodes)} nodes, {len(edges)} edges, data.json {os.path.getsize(os.path.join(OUT,'data.json'))/1e6:.1f} MB")
