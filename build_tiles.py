#!/usr/bin/env python3
"""Build Gaia star tiles and the Milky Way density layer for the viewer.

Inputs (from the Gaia archive, see README):
  gaia_stars.csv    ra,dec,parallax,phot_g_mean_mag,bp_rp   (G < 11.5, parallax_over_error > 5)
  gaia_density.csv  rb,db,dist_bin,n   (5 deg x 5 deg sky cells x 200 pc distance bins, counts)

Outputs:
  docs/tiles/<shell>-<patch>-<tier>.bin  binary star tiles: [n x 3 float32 xyz AU][n int16 G*100][n x 4 uint8 r,g,b,tier]
  docs/tiles/index.json                  cell centres/radii and per-tier counts, for culling + level of detail
  docs/galaxy.bin                        density voxels: float32 x,y,z (AU), radius (AU), weight, kind(0 gaia/1 model)
"""
import csv, json, math, os, struct, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server

ROOT = os.path.dirname(os.path.abspath(__file__))
SCR = sys.argv[1] if len(sys.argv) > 1 else "."
OUT = os.path.join(ROOT, "docs", "tiles"); os.makedirs(OUT, exist_ok=True)
AU_PER_PC = server.AU_PER_PC
SHELLS = [0, 60, 120, 250, 500, 1000, 2000, 4000, 8000, 30000]   # pc
TIER_EDGES = [-2.0, 0.0, 2.0, 4.5]                                 # absolute magnitude tier boundaries
G_MIN = 7.0                                                        # brighter stars come from HYG already

def eq_unit(ra_deg, dec_deg):
    ra, dec = np.radians(ra_deg), np.radians(dec_deg)
    return np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)

def eq_to_ecl(x, y, z):
    c, s = math.cos(server.OBLIQUITY), math.sin(server.OBLIQUITY)
    return x, y * c + z * s, -y * s + z * c

# ------------------------------------------------------------------ stars
print("reading stars ...", flush=True)
data = np.genfromtxt(os.path.join(SCR, "gaia_stars.csv"), delimiter=",", names=True, dtype=None, encoding="utf-8")
ra, dec, plx, G, bprp = data["ra"], data["dec"], data["parallax"], data["phot_g_mean_mag"], data["bp_rp"]
keep = G >= G_MIN
ra, dec, plx, G, bprp = ra[keep], dec[keep], plx[keep], G[keep], bprp[keep]
dist = 1000.0 / plx                                                # pc
M = G + 5 * np.log10(plx) - 10                                     # absolute magnitude
tier = np.digitize(M, TIER_EDGES)                                  # 0..4
ux, uy, uz = eq_unit(ra, dec)
ex, ey, ez = eq_to_ecl(ux * dist, uy * dist, uz * dist)            # ecliptic pc
X, Y, Z = ex * AU_PER_PC, ey * AU_PER_PC, ez * AU_PER_PC
shell = np.digitize(dist, SHELLS[1:])
lat = np.arcsin(np.clip(ez / dist, -1, 1)); lon = np.arctan2(ey, ex) % (2 * np.pi)
band = np.clip(((np.sin(lat) + 1) / 2 * 8).astype(int), 0, 7)
sector = np.clip((lon / (2 * np.pi) * 16).astype(int), 0, 15)
patch = np.where(shell <= 1, 0, band * 16 + sector)               # inner shells: one all-sky patch

bv = np.where(np.isnan(bprp), 0.6, bprp / 1.3)                     # rough BP-RP -> B-V
def rgb(b):
    h = server.bv_to_hex(float(b)); return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
uniq, inv = np.unique(np.round(bv, 2), return_inverse=True)
lut = np.array([rgb(b) for b in uniq], dtype=np.uint8); col = lut[inv]

for f in os.listdir(OUT):
    if f.endswith(".bin"): os.remove(os.path.join(OUT, f))
cells = {}
key = shell * 1000 + patch
for k in np.unique(key):
    sel = np.where(key == k)[0]
    sh, pa = int(k // 1000), int(k % 1000)
    cx, cy, cz = X[sel].mean(), Y[sel].mean(), Z[sel].mean()
    rad = float(np.sqrt((X[sel] - cx) ** 2 + (Y[sel] - cy) ** 2 + (Z[sel] - cz) ** 2).max())
    counts = []
    for t in range(5):
        s = sel[tier[sel] == t]
        counts.append(int(len(s)))
        if not len(s): continue
        xyz = np.stack([X[s], Y[s], Z[s]], axis=1).astype(np.float32)
        mag = np.round(G[s] * 100).astype(np.int16)
        extra = np.column_stack([col[s], np.full(len(s), t, dtype=np.uint8)]).astype(np.uint8)
        with open(os.path.join(OUT, f"{sh}-{pa}-{t}.bin"), "wb") as f:
            f.write(xyz.tobytes()); f.write(mag.tobytes()); f.write(extra.tobytes())
    cells[f"{sh}-{pa}"] = {"c": [float(f"{cx:.6g}"), float(f"{cy:.6g}"), float(f"{cz:.6g}")], "r": float(f"{rad:.5g}"), "n": counts}
# all-sky file for the most luminous tier: wide views always need all of it (one request instead of ~860)
t0 = np.where(tier == 0)[0]
with open(os.path.join(OUT, "tier0-all.bin"), "wb") as f:
    f.write(np.stack([X[t0], Y[t0], Z[t0]], axis=1).astype(np.float32).tobytes())
    f.write(np.round(G[t0] * 100).astype(np.int16).tobytes())
    f.write(np.column_stack([col[t0], np.zeros(len(t0), dtype=np.uint8)]).astype(np.uint8).tobytes())
with open(os.path.join(OUT, "index.json"), "w") as f:
    json.dump({"shells_pc": SHELLS, "tiers_absmag": TIER_EDGES, "cells": cells, "tier0_all": int(len(t0)),
               "source": "Gaia DR3 (ESA), G < 11.5, parallax_over_error > 5"}, f, separators=(",", ":"))
print(f"stars: {len(G)} in {len(cells)} cells; per tier: {[int((tier == t).sum()) for t in range(5)]}", flush=True)

# ------------------------------------------------------------------ density: Gaia counts
print("building density layer ...", flush=True)
vox = []
with open(os.path.join(SCR, "gaia_density.csv")) as f:
    for r in csv.DictReader(f):
        n = int(r["n"]); db = int(float(r["dist_bin"]))
        if n < 3 or db > 40: continue
        rac, decc = (float(r["rb"]) + 0.5) * 5, (float(r["db"]) + 0.5) * 5 - 90
        d = (db + 0.5) * 200.0                                     # pc
        ux, uy, uz = eq_unit(rac, decc)
        x, y, z = eq_to_ecl(ux * d, uy * d, uz * d)
        cell_w = max(200.0, d * math.radians(5) * math.cos(math.radians(decc)))   # physical cell size, pc
        # mass-conserving: each voxel carries its star count (tapered where Gaia is incomplete, > 3 kpc)
        # and is spread over a radius that overlaps neighbouring voxels so distance shells don't show
        w = n * (1.0 if d < 3000 else max(0.0, 1 - (d - 3000) / 4000))
        if w <= 0: continue
        vox.append((x * AU_PER_PC, y * AU_PER_PC, z * AU_PER_PC, max(cell_w, 200.0) * 0.8 * AU_PER_PC, w, 0))
n_gaia = len(vox)
# calibrate the model against Gaia: stars per pc^3 in voxels 1-2 kpc from the Sun near the plane
gaia_rho = []
with open(os.path.join(SCR, "gaia_density.csv")) as f:
    for r in csv.DictReader(f):
        db = int(float(r["dist_bin"])); d = (db + 0.5) * 200.0
        if not (1000 <= d <= 2000): continue
        decc = (float(r["db"]) + 0.5) * 5 - 90
        cell_w = max(200.0, d * math.radians(5) * math.cos(math.radians(decc)))
        gaia_rho.append(int(r["n"]) / (cell_w * cell_w * 200.0))
RHO_SUN = float(np.percentile(gaia_rho, 60))                        # stars / pc^3 seen by Gaia near the Sun
print(f"Gaia density near the Sun: {RHO_SUN*1e6:.1f} stars per 100 pc cube (model calibrated to this)")

# coarse level (10 deg x 400 pc) for wide views
coarse = {}
with open(os.path.join(SCR, "gaia_density.csv")) as f:
    for r in csv.DictReader(f):
        n = int(r["n"]); db = int(float(r["dist_bin"]))
        if db > 40: continue
        k = (int(float(r["rb"])) // 2, int(float(r["db"])) // 2, db // 2)
        coarse[k] = coarse.get(k, 0) + n
cvox = []
for (rb, dbb, db), n in coarse.items():
    if n < 10: continue
    rac, decc = (rb + 0.5) * 10, (dbb + 0.5) * 10 - 90
    d = (db + 0.5) * 400.0
    ux, uy, uz = eq_unit(rac, decc)
    x, y, z = eq_to_ecl(ux * d, uy * d, uz * d)
    cell_w = max(400.0, d * math.radians(10) * math.cos(math.radians(decc)))
    w = n * (1.0 if d < 3000 else max(0.0, 1 - (d - 3000) / 4000))
    if w > 0: cvox.append((x * AU_PER_PC, y * AU_PER_PC, z * AU_PER_PC, max(cell_w, 400.0) * 0.8 * AU_PER_PC, w, 0))

# ------------------------------------------------------------------ density: model disk beyond Gaia
# Exponential disk (scale length 2.6 kpc, height 0.3 kpc) + bulge + 4 log-spiral arms, galactocentric.
R_SUN, Z_SUN = 8178.0, 20.0                                        # pc
GC = np.array(eq_to_ecl(*eq_unit(266.405, -28.936)))              # unit vector Sun -> galactic centre (ecliptic)
NGP = np.array(eq_to_ecl(*eq_unit(192.859, 27.128)))              # north galactic pole
GY = np.cross(NGP, GC)                                             # direction of galactic rotation (l = 90)
ARMS = [(0.0, "Norma"), (math.pi / 2, "Scutum-Centaurus"), (math.pi, "Sagittarius"), (3 * math.pi / 2, "Perseus")]
PITCH = math.radians(12.5)
def arm_boost(Rg, phi):
    best = 0.0
    for phi0, _ in ARMS:
        # log spiral: phi(R) = phi0 + ln(R/3000)/tan(pitch); enhancement falls off with angular distance
        target = phi0 + math.log(max(Rg, 500) / 3000.0) / math.tan(PITCH)
        d = (phi - target + math.pi) % (2 * math.pi) - math.pi
        best = max(best, math.exp(-(d * Rg) ** 2 / (2 * 700.0 ** 2)))   # arm width ~700 pc
    return best
STEP = 400.0
for gx in np.arange(-16000, 16001, STEP):
    for gy in np.arange(-16000, 16001, STEP):
        Rg = math.hypot(gx, gy)
        if Rg > 16000: continue
        phi = math.atan2(gy, gx)
        for gz in (-450.0, -150.0, 150.0, 450.0):
            disk = math.exp(-Rg / 2600.0) * math.exp(-abs(gz) / 300.0)
            bulge = 2.5 * math.exp(-Rg / 600.0) * math.exp(-abs(gz) / 400.0)
            dens = disk * (1 + 2.0 * arm_boost(Rg, phi)) + bulge
            # heliocentric: Sun at (R_SUN, 0, Z_SUN) in galactocentric coords; +x axis Sun -> GC
            hx, hy, hz = R_SUN - gx, gy, gz - Z_SUN                # galactic cartesian, pc (x toward GC)
            dsun = math.sqrt(hx * hx + hy * hy + hz * hz)
            taper = 0.0 if dsun < 2500 else min(1.0, (dsun - 2500) / 2000)   # let Gaia own the neighbourhood
            # model density relative to the Sun's location, converted to a star count for this 400 pc x 400 pc x 300 pc cell
            dens_sun = math.exp(-R_SUN / 2600.0) * (1 + 2.0 * arm_boost(R_SUN, 0.0)) + 2.5 * math.exp(-R_SUN / 600.0)
            w = dens / dens_sun * RHO_SUN * (STEP * STEP * 300.0) * taper
            if w < 0.002 * RHO_SUN * STEP * STEP * 300.0: continue
            v = GC * hx + GY * hy + NGP * hz                        # -> ecliptic pc
            vox.append((v[0] * AU_PER_PC, v[1] * AU_PER_PC, v[2] * AU_PER_PC, STEP * 0.8 * AU_PER_PC, w, 1))
model = [v for v in vox if v[5] == 1]
with open(os.path.join(ROOT, "docs", "galaxy.bin"), "wb") as f:
    f.write(np.array(vox, dtype=np.float32).tobytes())
with open(os.path.join(ROOT, "docs", "galaxy_lo.bin"), "wb") as f:
    f.write(np.array(cvox + model, dtype=np.float32).tobytes())
print(f"coarse level: {len(cvox)} Gaia voxels + model")
print(f"density voxels: {n_gaia} Gaia + {len(vox) - n_gaia} model -> galaxy.bin {os.path.getsize(os.path.join(ROOT,'docs','galaxy.bin'))/1e6:.1f} MB")
tot = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
print(f"tiles: {len(os.listdir(OUT))} files, {tot/1e6:.1f} MB total")
