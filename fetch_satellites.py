#!/usr/bin/env python3
"""Fetch current orbital elements (TLEs) for Earth satellites from CelesTrak into docs/satellites.json.

The viewer propagates them to live positions in the browser with satellite.js (SGP4).
"""
import json, os, urllib.request
from datetime import datetime, timezone

GROUPS = ["stations", "science", "visual", "gps-ops", "galileo", "weather", "geo", "starlink"]
URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP={}&FORMAT=tle"

CACHE = os.environ.get("SAT_CACHE_DIR")      # optional dir of <group>.tle files used if CelesTrak refuses (403 = re-request too soon)

seen, sats = set(), []
for g in GROUPS:
    text = None
    try:
        req = urllib.request.Request(URL.format(g), headers={"User-Agent": "starnav/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            text = resp.read().decode("utf-8", "replace")
        if CACHE:
            with open(os.path.join(CACHE, f"{g}.tle"), "w") as f:
                f.write(text)
    except Exception as e:
        cached = CACHE and os.path.join(CACHE, f"{g}.tle")
        if cached and os.path.exists(cached):
            text = open(cached).read(); print(f"{g}: download failed ({e}); using cached file", flush=True)
        else:
            print(f"{g}: skipped ({e})", flush=True); continue
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    n = 0
    for i in range(0, len(lines) - 2, 3):
        name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
        if not (l1.startswith("1 ") and l2.startswith("2 ")):
            continue
        norad = l1[2:7].strip()
        if norad in seen:
            continue
        seen.add(norad); n += 1
        sats.append({"n": name, "id": norad, "g": g, "l1": l1, "l2": l2})
    print(f"{g}: {n} new", flush=True)

out = {"fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "CelesTrak GP elements (SGP4/TLE)",
       "groups": GROUPS, "sats": sats}
os.makedirs("docs", exist_ok=True)
with open("docs/satellites.json", "w") as f:
    json.dump(out, f, separators=(",", ":"))
print(f"wrote docs/satellites.json: {len(sats)} satellites, {os.path.getsize('docs/satellites.json')/1e6:.1f} MB")
