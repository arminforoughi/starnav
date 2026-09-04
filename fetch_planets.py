#!/usr/bin/env python3
"""Fetch current planet positions from JPL Horizons and write docs/planets.json (used by the static site)."""
import json, os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server

epoch = datetime.now(timezone.utc).replace(second=0, microsecond=0, tzinfo=None)
nodes = [{"id": "sun", "name": "Sun", "kind": "sun", "x": 0.0, "y": 0.0, "z": 0.0, "mag": -26.74,
          "color": "#ffd27a", "radius_km": 695700.0, "spect": "G2V", "source": "origin"}]
edges = []
for bid, name, hid, kind, color, radius, parent in server.SOLAR_BODIES:
    x, y, z = server.horizons_vector(hid, epoch)
    nodes.append({"id": bid, "name": name, "kind": kind, "x": x, "y": y, "z": z, "color": color,
                  "radius_km": radius, "source": "JPL Horizons"})
    edges.append({"src": bid, "dst": parent, "rel": "orbits"})
out = {"epoch": epoch.strftime("%Y-%m-%d %H:%M"), "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
       "nodes": nodes, "edges": edges}
os.makedirs("docs", exist_ok=True)
with open("docs/planets.json", "w") as f:
    json.dump(out, f, separators=(",", ":"))
print(f"wrote docs/planets.json for epoch {out['epoch']} UTC ({len(nodes)} bodies)")
