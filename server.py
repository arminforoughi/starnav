#!/usr/bin/env python3
"""Star Nav - tiny star/planet navigation server.

Pure standard library. Stores bodies as a small graph (nodes + edges) in SQLite.
Planet/moon positions come live from NASA/JPL Horizons; stars come from the
open HYG catalog (CC BY-SA 4.0, astronexus.com) with a small built-in fallback.

Run:  python3 server.py [port] [--lan]     (--lan = reachable from phones on the same Wi-Fi)
"""
import csv
import gzip
import io
import json
import math
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "starnav.db")
STATIC = os.path.join(ROOT, "static")

HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
HYG_URL = ("https://raw.githubusercontent.com/astronexus/HYG-Database/"
           "main/hyg/CURRENT/hygdata_v40.csv.gz")
STAR_MAG_LIMIT = float(os.environ.get("STARNAV_MAG_LIMIT", "6.5"))   # 6.5 = naked-eye limit, ~9,000 stars
STAR_NEAR_PC = float(os.environ.get("STARNAV_NEAR_PC", "100"))       # plus every catalog star within 100 pc (~25,000)

AU_PER_PC = 206264.806
OBLIQUITY = math.radians(23.4392911)   # J2000 mean obliquity

# id, display name, Horizons id, kind, colour, mean radius km, parent (graph edge)
SOLAR_BODIES = [
    ("mercury", "Mercury", "199", "planet", "#b8b8b8", 2439.7, "sun"),
    ("venus",   "Venus",   "299", "planet", "#e8c98c", 6051.8, "sun"),
    ("earth",   "Earth",   "399", "planet", "#4f8ef7", 6371.0, "sun"),
    ("moon",    "Moon",    "301", "moon",   "#d0d0d0", 1737.4, "earth"),
    ("mars",    "Mars",    "499", "planet", "#e0653a", 3389.5, "sun"),
    ("jupiter", "Jupiter", "599", "planet", "#d9b48f", 69911.0, "sun"),
    ("saturn",  "Saturn",  "699", "planet", "#e8d9a8", 58232.0, "sun"),
    ("uranus",  "Uranus",  "799", "planet", "#8fd6e0", 25362.0, "sun"),
    ("neptune", "Neptune", "899", "planet", "#4b6ff0", 24622.0, "sun"),
    ("pluto",   "Pluto",   "999", "dwarf",  "#c9b8a8", 1188.3, "sun"),
]

# Fallback stars used only if the HYG download fails: (name, RA h, Dec deg, dist pc, mag, B-V)
FALLBACK_STARS = [
    ("Sirius", 6.752, -16.716, 2.64, -1.46, 0.00), ("Canopus", 6.399, -52.696, 95.0, -0.74, 0.15),
    ("Rigil Kentaurus", 14.660, -60.835, 1.34, -0.27, 0.71), ("Arcturus", 14.261, 19.182, 11.26, -0.05, 1.23),
    ("Vega", 18.616, 38.784, 7.68, 0.03, 0.00), ("Capella", 5.278, 45.998, 13.2, 0.08, 0.80),
    ("Rigel", 5.242, -8.202, 260.0, 0.13, -0.03), ("Procyon", 7.655, 5.225, 3.51, 0.34, 0.42),
    ("Achernar", 1.629, -57.237, 43.0, 0.46, -0.16), ("Betelgeuse", 5.919, 7.407, 170.0, 0.50, 1.85),
    ("Hadar", 14.064, -60.373, 120.0, 0.61, -0.23), ("Altair", 19.846, 8.868, 5.13, 0.77, 0.22),
    ("Acrux", 12.443, -63.099, 98.0, 0.76, -0.24), ("Aldebaran", 4.599, 16.509, 20.0, 0.86, 1.54),
    ("Antares", 16.490, -26.432, 170.0, 1.06, 1.83), ("Spica", 13.420, -11.161, 77.0, 0.97, -0.23),
    ("Pollux", 7.755, 28.026, 10.4, 1.14, 1.00), ("Fomalhaut", 22.961, -29.622, 7.7, 1.16, 0.09),
    ("Deneb", 20.690, 45.280, 800.0, 1.25, 0.09), ("Regulus", 10.140, 11.967, 24.0, 1.40, -0.11),
    ("Polaris", 2.530, 89.264, 133.0, 1.98, 0.60), ("Castor", 7.577, 31.888, 15.6, 1.58, 0.03),
    ("Bellatrix", 5.419, 6.350, 77.0, 1.64, -0.22), ("Proxima Centauri", 14.495, -62.679, 1.30, 11.13, 1.82),
    ("Barnard's Star", 17.963, 4.693, 1.83, 9.54, 1.74),
]

# Deep-sky landmarks: id, name, kind, RA deg, Dec deg, distance pc, colour, note
DEEP_SKY = [
    ("sgr-a", "Sagittarius A* (Galactic Center)", "blackhole", 266.4168, -29.0078, 8178, "#ff9a3c",
     "Supermassive black hole at the centre of the Milky Way, about 4.3 million solar masses. "
     "The Sun orbits it once every ~230 million years."),
    ("gaia-bh1", "Gaia BH1", "blackhole", 262.1712, -0.5811, 480, "#ff9a3c",
     "Closest known black hole (found 2022), ~9.6 solar masses, orbited by a Sun-like star."),
    ("gaia-bh3", "Gaia BH3", "blackhole", 294.8280, 14.9316, 590, "#ff9a3c",
     "Most massive stellar black hole known in the Milky Way, ~33 solar masses (2024)."),
    ("a0620", "A0620-00 (V616 Mon)", "blackhole", 95.6854, -0.3458, 1060, "#ff9a3c",
     "~6.6 solar masses; one of the nearest X-ray binaries."),
    ("gaia-bh2", "Gaia BH2", "blackhole", 207.5700, -59.2390, 1160, "#ff9a3c",
     "~8.9 solar masses with a red-giant companion (2023)."),
    ("xte-j1118", "XTE J1118+480", "blackhole", 169.5450, 48.0369, 1700, "#ff9a3c",
     "~7 solar masses, far above the galactic plane in the halo."),
    ("cyg-x1", "Cygnus X-1", "blackhole", 299.5903, 35.2016, 2220, "#ff9a3c",
     "First black hole ever identified (1971), ~21 solar masses, feeding from a blue supergiant."),
    ("v404-cyg", "V404 Cygni", "blackhole", 306.0158, 33.8672, 2390, "#ff9a3c",
     "~9 solar masses; famous for its 2015 X-ray outburst."),
    ("hyades", "Hyades", "cluster", 66.75, 15.8667, 47, "#9ec5ff", "Nearest open star cluster."),
    ("m45", "Pleiades (M45)", "cluster", 56.75, 24.1167, 136, "#9ec5ff", "Open cluster of ~1,000 young stars."),
    ("m42", "Orion Nebula (M42)", "nebula", 83.8221, -5.3911, 412, "#d98cff", "Nearest massive star-forming region."),
    ("m1", "Crab Nebula (M1)", "nebula", 83.6331, 22.0145, 2000, "#d98cff",
     "Remnant of the supernova seen in 1054 AD, with a pulsar at its heart."),
    ("omega-cen", "Omega Centauri", "cluster", 201.6970, -47.4795, 5200, "#ffd9a0",
     "Largest globular cluster in the Milky Way, ~10 million stars."),
    ("m13", "Hercules Cluster (M13)", "cluster", 250.4235, 36.4613, 7700, "#ffd9a0", "Globular cluster of ~300,000 stars."),
    ("sgr-dwarf", "Sagittarius Dwarf Galaxy", "galaxy", 283.7639, -30.4800, 20000, "#c9d6ff",
     "Satellite galaxy currently being torn apart by the Milky Way."),
    ("lmc", "Large Magellanic Cloud", "galaxy", 80.8942, -69.7561, 49970, "#c9d6ff",
     "Satellite galaxy of the Milky Way, visible from the southern hemisphere."),
    ("smc", "Small Magellanic Cloud", "galaxy", 13.1867, -72.8286, 62440, "#c9d6ff", "Satellite galaxy of the Milky Way."),
    ("m31", "Andromeda Galaxy (M31)", "galaxy", 10.6847, 41.2687, 765000, "#c9d6ff",
     "Nearest large spiral galaxy, ~1 trillion stars; will merge with the Milky Way in ~4.5 billion years."),
    ("m33", "Triangulum Galaxy (M33)", "galaxy", 23.4621, 30.6599, 840000, "#c9d6ff",
     "Third-largest galaxy in the Local Group."),
    ("virgo", "Virgo Cluster", "gcluster", 187.70, 12.39, 16.5e6, "#ffd0e8",
     "Nearest big galaxy cluster, ~1,500 galaxies around the giant elliptical M87. Its gravity shapes our Local Group's motion."),
    ("fornax", "Fornax Cluster", "gcluster", 54.62, -35.45, 19e6, "#ffd0e8", "Second-nearest rich galaxy cluster."),
    ("centaurus", "Centaurus Cluster", "gcluster", 192.20, -41.31, 52e6, "#ffd0e8", "Rich cluster in the southern sky."),
    ("hydra", "Hydra Cluster", "gcluster", 159.17, -27.53, 58e6, "#ffd0e8", "Galaxy cluster in the Hydra-Centaurus supercluster."),
    ("norma", "Norma Cluster (Great Attractor)", "gcluster", 243.60, -60.85, 68e6, "#ffd0e8",
     "Heart of the Great Attractor, a mass concentration pulling the Milky Way and thousands of galaxies toward it."),
    ("perseus", "Perseus Cluster", "gcluster", 49.95, 41.51, 74e6, "#ffd0e8", "One of the most massive nearby clusters, a strong X-ray source."),
    ("coma", "Coma Cluster", "gcluster", 194.95, 27.98, 100e6, "#ffd0e8",
     "~1,000 galaxies; where Fritz Zwicky first inferred dark matter in 1933."),
    ("shapley", "Shapley Supercluster", "gcluster", 202.5, -31.5, 200e6, "#ffd0e8",
     "Largest concentration of galaxies in the nearby universe."),
    ("sloan-wall", "Sloan Great Wall", "gcluster", 200.0, 0.0, 300e6, "#ffd0e8",
     "A filament of galaxies ~1.4 billion light-years long, one of the largest known structures."),
    ("3c273", "3C 273 (quasar)", "blackhole", 187.2779, 2.0524, 749e6, "#ff9a3c",
     "Nearest bright quasar: a supermassive black hole ~900 million solar masses swallowing gas so violently it outshines its galaxy. Distance from redshift."),
]
DEEP_SKY_EDGES = [("sun", "sgr-a", "orbits"), ("sgr-dwarf", "sgr-a", "near"), ("lmc", "sgr-a", "near"),
                  ("smc", "sgr-a", "near"), ("m31", "sun", "near"), ("m33", "sun", "near")]

VIZIER = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"
LV_URL = VIZIER + "?-source=J/AJ/145/101/catalog&-out.max=unlimited&-out=Name,RAJ2000,DEJ2000,Dist,Bmag,SimbadName"
MRS_URL = VIZIER + "?-source=J/ApJS/199/26/table3&-out.max=unlimited&-out=ID,RAJ2000,DEJ2000,Ktmag,cz,SimbadName"
H0 = 70.0                      # km/s/Mpc, for redshift distances
MRS_MIN_CZ = 800.0             # below this the Local Volume catalog (real distances) is used instead

_lock = threading.Lock()
_state = {"status": "idle", "busy": False}


# ----------------------------------------------------------------- database
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
            x REAL, y REAL, z REAL,           -- AU, heliocentric ecliptic J2000
            mag REAL, color TEXT, radius_km REAL, dist_pc REAL,
            spect TEXT, con TEXT, source TEXT, updated_at TEXT, note TEXT);
        CREATE TABLE IF NOT EXISTS edges (
            src TEXT NOT NULL, dst TEXT NOT NULL, rel TEXT NOT NULL,
            PRIMARY KEY (src, dst, rel));
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE INDEX IF NOT EXISTS nodes_kind ON nodes(kind);
        """)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(nodes)")}
        if "note" not in cols:                       # migrate databases created before landmarks
            conn.execute("ALTER TABLE nodes ADD COLUMN note TEXT")


def set_meta(key, value):
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))


def get_meta():
    with db() as conn:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM meta")}


def count(kind_sql):
    with db() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM nodes WHERE {kind_sql}").fetchone()[0]


# ----------------------------------------------------------------- helpers
def set_status(msg, busy=None):
    with _lock:
        _state["status"] = msg
        if busy is not None:
            _state["busy"] = busy
    print("[starnav]", msg, flush=True)


def bv_to_hex(bv):
    """Rough B-V colour index to screen colour."""
    table = [(-0.40, (155, 176, 255)), (0.00, (202, 215, 255)), (0.40, (255, 244, 234)),
             (0.80, (255, 221, 180)), (1.50, (255, 189, 111)), (2.00, (255, 160, 80))]
    if bv is None:
        return "#ffffff"
    bv = max(table[0][0], min(table[-1][0], bv))
    for (b0, c0), (b1, c1) in zip(table, table[1:]):
        if b0 <= bv <= b1:
            t = (bv - b0) / (b1 - b0)
            r, g, b = (round(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#ffffff"


def eq_to_ecl(x, y, z):
    """Equatorial J2000 -> ecliptic J2000 (rotation about X by the obliquity)."""
    c, s = math.cos(OBLIQUITY), math.sin(OBLIQUITY)
    return x, y * c + z * s, -y * s + z * c


def radec_to_ecl_au(ra_deg, dec_deg, dist_pc):
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    xq = dist_pc * math.cos(dec) * math.cos(ra)
    yq = dist_pc * math.cos(dec) * math.sin(ra)
    zq = dist_pc * math.sin(dec)
    x, y, z = eq_to_ecl(xq, yq, zq)
    return x * AU_PER_PC, y * AU_PER_PC, z * AU_PER_PC


def vizier_rows(url):
    """Fetch a VizieR TSV table and yield dict rows (comment, unit and dash lines skipped)."""
    req = urllib.request.Request(url, headers={"User-Agent": "starnav/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        text = resp.read().decode("utf-8", "replace")
    header = None
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if header is None:
            header = [h.strip() for h in parts]
            continue
        if parts[0].startswith("---") or all(not p.strip() or p.strip() in ("deg", "Mpc", "mag", "km/s") for p in parts):
            continue
        yield {h: p.strip() for h, p in zip(header, parts)}


def sexagesimal(text, hours):
    a, b, c = (float(v) for v in text.replace("+", " +").split()[:3]) if len(text.split()) >= 3 else (0, 0, 0)
    sign = -1 if text.strip().startswith("-") else 1
    val = abs(a) + b / 60 + c / 3600
    return sign * val * (15 if hours else 1)


def pretty_galaxy_name(simbad, fallback):
    name = (simbad or "").replace("_", " ").strip()
    if not name:
        return fallback
    parts = name.split()
    if parts[0].upper() == "MESSIER" and len(parts) > 1 and parts[1].isdigit():
        return "M" + str(int(parts[1]))
    if len(parts) == 2 and parts[1].isdigit():
        return f"{parts[0]} {int(parts[1])}"
    return name


def refresh_galaxies():
    set_status("Downloading Local Volume galaxy catalog (VizieR) ...", True)
    rows = []
    for r in vizier_rows(LV_URL):
        try:
            d = float(r["Dist"])
        except (KeyError, ValueError):
            continue
        if d <= 0:
            continue
        ra, dec = sexagesimal(r["RAJ2000"], True), sexagesimal(r["DEJ2000"], False)
        x, y, z = radec_to_ecl_au(ra, dec, d * 1e6)
        rows.append((f"lv-{r['Name'].replace(' ', '')}", pretty_galaxy_name(r.get("SimbadName"), r["Name"]), "galaxy",
                     x, y, z, fnum(r.get("Bmag")), "#c9d6ff", None, d * 1e6, None, None,
                     "Local Volume catalog (Karachentsev+ 2013, VizieR)"))
    n_lv = len(rows)
    set_status(f"Local Volume: {n_lv} galaxies. Downloading 2MASS Redshift Survey (~45,000 galaxies) ...", True)
    for r in vizier_rows(MRS_URL):
        try:
            cz = float(r["cz"])
        except (KeyError, ValueError):
            continue
        if cz < MRS_MIN_CZ:
            continue
        d = cz / H0                                   # Mpc, Hubble-law distance
        x, y, z = radec_to_ecl_au(float(r["RAJ2000"]), float(r["DEJ2000"]), d * 1e6)
        k = fnum(r.get("Ktmag"))
        rows.append((f"2mrs-{r['ID']}", pretty_galaxy_name(r.get("SimbadName"), "2MASX J" + r["ID"]), "galaxy",
                     x, y, z, (k + 3.5) if k is not None else None, "#b9c8ff", None, d * 1e6, None, None,
                     "2MASS Redshift Survey (Huchra+ 2012, VizieR); distance from redshift, H0=70"))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        conn.execute("DELETE FROM nodes WHERE kind='galaxy' AND note IS NULL")
        conn.executemany("INSERT OR REPLACE INTO nodes(id,name,kind,x,y,z,mag,color,radius_km,dist_pc,"
                         "spect,con,source,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         [r + (now,) for r in rows])
    set_meta("galaxies_updated", now)
    set_status(f"Galaxies loaded: {n_lv} Local Volume + {len(rows) - n_lv} 2MRS.", False)


def refresh_landmarks():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        for bid, name, kind, ra, dec, dist, color, note in DEEP_SKY:
            x, y, z = radec_to_ecl_au(ra, dec, dist)
            conn.execute("INSERT OR REPLACE INTO nodes(id,name,kind,x,y,z,mag,color,radius_km,dist_pc,"
                         "spect,con,source,updated_at,note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (bid, name, kind, x, y, z, None, color, None, dist, None, None,
                          "built-in landmark list", now, note))
        conn.executemany("INSERT OR IGNORE INTO edges(src,dst,rel) VALUES (?,?,?)", DEEP_SKY_EDGES)
    set_status(f"Landmarks loaded: {len(DEEP_SKY)} black holes, clusters, nebulae and galaxies.", False)


def parse_epoch(text):
    text = (text or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError("epoch must be YYYY-MM-DD or YYYY-MM-DD HH:MM")


# ----------------------------------------------------------------- planets
def horizons_vector(command, epoch):
    stop = epoch + timedelta(days=1)
    params = {
        "format": "text", "COMMAND": f"'{command}'", "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'", "EPHEM_TYPE": "'VECTORS'", "CENTER": "'500@10'",
        "START_TIME": f"'{epoch:%Y-%m-%d %H:%M}'", "STOP_TIME": f"'{stop:%Y-%m-%d %H:%M}'",
        "STEP_SIZE": "'1d'", "VEC_TABLE": "'1'", "OUT_UNITS": "'AU-D'",
        "REF_PLANE": "'ECLIPTIC'", "CSV_FORMAT": "'YES'",
    }
    url = HORIZONS + "?" + urllib.parse.urlencode(params)
    text, last_err = None, None
    for attempt in range(4):                      # Horizons occasionally answers 503
        try:
            with urllib.request.urlopen(url, timeout=40) as resp:
                text = resp.read().decode("utf-8", "replace")
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    if text is None:
        raise RuntimeError(f"Horizons unavailable for {command}: {last_err}")
    if "$$SOE" not in text:
        raise RuntimeError(f"Horizons returned no ephemeris for {command}: {text[:200]}")
    block = text.split("$$SOE", 1)[1].split("$$EOE", 1)[0].strip().splitlines()
    fields = [f.strip() for f in block[0].split(",")]
    return float(fields[2]), float(fields[3]), float(fields[4])


def refresh_planets(epoch):
    set_status(f"Fetching planet positions from JPL Horizons for {epoch:%Y-%m-%d %H:%M} UTC ...", True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def fetch(body):
        bid, name, hid, kind, color, radius, parent = body
        x, y, z = horizons_vector(hid, epoch)
        return (bid, name, kind, x, y, z, color, radius, parent)

    with ThreadPoolExecutor(max_workers=3) as ex:
        rows = list(ex.map(fetch, SOLAR_BODIES))

    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO nodes(id,name,kind,x,y,z,mag,color,radius_km,dist_pc,"
                     "spect,con,source,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("sun", "Sun", "sun", 0.0, 0.0, 0.0, -26.74, "#ffd27a", 695700.0, 0.0,
                      "G2V", None, "origin", now))
        for bid, name, kind, x, y, z, color, radius, parent in rows:
            conn.execute("INSERT OR REPLACE INTO nodes(id,name,kind,x,y,z,mag,color,radius_km,dist_pc,"
                         "spect,con,source,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (bid, name, kind, x, y, z, None, color, radius, None, None, None,
                          "JPL Horizons", now))
            conn.execute("INSERT OR IGNORE INTO edges(src,dst,rel) VALUES (?,?,?)", (bid, parent, "orbits"))
    set_meta("epoch", epoch.strftime("%Y-%m-%d %H:%M"))
    set_meta("planets_updated", now)
    set_status(f"Planets updated from JPL Horizons ({len(rows)} bodies).", False)


# ----------------------------------------------------------------- stars
def star_name(r):
    if r.get("proper"):
        return r["proper"]
    if r.get("bayer") and r.get("con"):
        return f"{r['bayer']} {r['con']}"
    if r.get("flam") and r.get("con"):
        return f"{r['flam']} {r['con']}"
    if r.get("hip"):
        return f"HIP {r['hip']}"
    return f"HYG {r['id']}"


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def download_hyg():
    set_status("Downloading HYG star catalog (~14 MB) ...", True)
    req = urllib.request.Request(HYG_URL, headers={"User-Agent": "starnav/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    text = io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(data)), encoding="utf-8")
    rows = []
    for r in csv.DictReader(text):
        mag, dist = fnum(r.get("mag")), fnum(r.get("dist"))
        if mag is None or r.get("id") == "0":
            continue
        if dist is None or dist <= 0 or dist >= 100000:   # 100000 = unknown in HYG
            continue
        if mag > STAR_MAG_LIMIT and dist > STAR_NEAR_PC:   # keep naked-eye stars anywhere + all neighbours
            continue
        x, y, z = eq_to_ecl(float(r["x"]), float(r["y"]), float(r["z"]))
        rows.append((f"hyg-{r['id']}", star_name(r), "star", x * AU_PER_PC, y * AU_PER_PC,
                     z * AU_PER_PC, mag, bv_to_hex(fnum(r.get("ci"))), None, dist,
                     r.get("spect") or None, r.get("con") or None, "HYG v4.0"))
    return rows


def fallback_stars():
    rows = []
    for i, (name, ra_h, dec_d, dist, mag, bv) in enumerate(FALLBACK_STARS):
        x, y, z = radec_to_ecl_au(ra_h * 15, dec_d, dist)
        rows.append((f"fb-{i}", name, "star", x, y, z, mag, bv_to_hex(bv), None, dist, None, None, "built-in list"))
    return rows


def refresh_stars():
    try:
        rows = download_hyg()
        src = "HYG v4.0"
    except Exception as e:           # offline or upstream change: keep the app usable
        set_status(f"HYG download failed ({e}); using built-in star list.", True)
        rows = fallback_stars()
        src = "built-in list"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        conn.execute("DELETE FROM edges WHERE src IN (SELECT id FROM nodes WHERE kind='star')")
        conn.execute("DELETE FROM nodes WHERE kind='star'")
        conn.executemany("INSERT OR REPLACE INTO nodes(id,name,kind,x,y,z,mag,color,radius_km,dist_pc,"
                         "spect,con,source,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         [r + (now,) for r in rows])
        # graph edge: every star is a neighbour of the Sun, weighted by distance
        conn.executemany("INSERT OR IGNORE INTO edges(src,dst,rel) VALUES (?,?,?)",
                         [(r[0], "sun", "near") for r in rows])
    set_meta("stars_source", src)
    set_meta("stars_updated", now)
    set_status(f"Stars loaded: {len(rows)} ({src}).", False)


# ----------------------------------------------------------------- jobs
def run_job(fn, *args):
    with _lock:
        if _state["busy"]:
            return False
        _state["busy"] = True

    def worker():
        try:
            fn(*args)
        except Exception as e:
            set_status(f"Error: {e}", False)
        finally:
            with _lock:
                _state["busy"] = False
    threading.Thread(target=worker, daemon=True).start()
    return True


def seed_if_empty():
    def job():
        errors = []
        if count("kind IN ('sun','planet','moon','dwarf')") == 0:
            try:
                refresh_planets(datetime.now(timezone.utc).replace(tzinfo=None))
            except Exception as e:
                errors.append(f"planets: {e}")
        if count("kind = 'star'") == 0:
            try:
                refresh_stars()
            except Exception as e:
                errors.append(f"stars: {e}")
        if count("note IS NOT NULL") == 0:
            refresh_landmarks()
        if count("kind = 'galaxy' AND note IS NULL") == 0:
            try:
                refresh_galaxies()
            except Exception as e:
                errors.append(f"galaxies: {e}")
        set_status("Error: " + "; ".join(errors) if errors else "Ready.", False)
    run_job(job)


# ----------------------------------------------------------------- http
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/status"):
            super().log_message(fmt, *args)

    def send_json(self, obj, code=200):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if len(body) > 4096 and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, compresslevel=5)
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                                   # client went away mid-response (page reload)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/bodies":
            with db() as conn:
                nodes = [{k: v for k, v in dict(r).items() if v is not None}
                         for r in conn.execute("SELECT * FROM nodes")]
                edges = [dict(r) for r in conn.execute("SELECT * FROM edges")]
            return self.send_json({"nodes": nodes, "edges": edges, "meta": get_meta(),
                                   "status": dict(_state)})
        if url.path == "/api/status":
            return self.send_json({"meta": get_meta(), "status": dict(_state)})
        return super().do_GET()

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/api/refresh":
            what = q.get("what", ["planets"])[0]
            try:
                epoch = parse_epoch(q.get("epoch", [""])[0]) if q.get("epoch", [""])[0] \
                    else datetime.now(timezone.utc).replace(tzinfo=None)
            except ValueError as e:
                return self.send_json({"ok": False, "error": str(e)}, 400)
            if what == "stars":
                started = run_job(refresh_stars)
            elif what == "landmarks":
                started = run_job(refresh_landmarks)
            elif what == "galaxies":
                started = run_job(refresh_galaxies)
            else:
                started = run_job(refresh_planets, epoch)
            return self.send_json({"ok": started, "status": dict(_state)},
                                  200 if started else 409)
        return self.send_json({"error": "not found"}, 404)


def lan_ip():
    """Best-effort local network address (no packets are actually sent)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = int(args[0]) if args else 8000
    lan = "--lan" in sys.argv or os.environ.get("STARNAV_LAN") == "1"
    init_db()
    seed_if_empty()
    host = "0.0.0.0" if lan else "127.0.0.1"
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[starnav] serving on http://127.0.0.1:{port}  (db: {DB_PATH})", flush=True)
    if lan:
        ip = lan_ip()
        print(f"[starnav] LAN mode: open http://{ip or '<this-mac-ip>'}:{port} on your phone (same Wi-Fi)", flush=True)
    else:
        print("[starnav] local only; run with --lan to reach it from a phone on the same Wi-Fi", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
