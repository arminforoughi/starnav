# Star Nav

A tiny star / planet navigation app. Pure Python standard library + one HTML file.

- **Planets, Moon, Pluto**: live positions from the open [NASA/JPL Horizons API](https://ssd-api.jpl.nasa.gov/doc/horizons.html)
  (heliocentric ecliptic J2000, in AU) for any date you pick.
- **Stars**: the whole open [HYG database](https://github.com/astronexus/HYG-Database) (CC BY-SA 4.0), ~109,000 stars
  with known distances (Hipparcos, Yale Bright Star and Gliese catalogs), downloaded once and cached.
  Tune with `STARNAV_MAG_LIMIT` and `STARNAV_NEAR_PC`.
  A small built-in list is used if the download fails.
- **Galaxies**: ~870 galaxies within 36 Mly with measured distances (Local Volume catalog,
  Karachentsev+ 2013) and ~43,000 galaxies out to ~1 Gly from the 2MASS Redshift Survey
  (Huchra+ 2012; distances from redshift with H0 = 70), both fetched from VizieR and cached.
- **Gaia star tiles**: 1.9 million Gaia DR3 stars (G < 11.5, good parallaxes) sorted into distance shells,
  sky patches and luminosity tiers. The viewer streams only the tiles in view, at the detail level the zoom
  warrants, under a fixed budget of points per frame (`build_tiles.py`, `docs/tiles/`).
- **Milky Way density**: real Gaia star counts (volume-limited to intrinsically bright stars, 5° × 200 pc voxels)
  drawn as an additive glow, plus a standard exponential-disk + four-arm spiral model calibrated to Gaia's
  local density for the parts of the galaxy Gaia cannot see (`docs/galaxy.bin`). Toggle "Model disk" to
  see only what is measured.
- **Cepheids**: 2,214 classical Cepheids across the whole disk, including the far side, from the OGLE
  Milky Way map (Skowron+ 2019, VizieR) with period-luminosity distances.
- **Landmarks**: known black holes (Sagittarius A*, Gaia BH1/BH2/BH3, Cygnus X-1, V404 Cygni, …),
  clusters, nebulae, the Magellanic Clouds and Andromeda, galaxy clusters (Virgo, Coma, Perseus, the
  Great Attractor, Shapley, the Sloan Great Wall), the quasar 3C 273, a schematic Milky Way disk and
  the edge of the observable universe.
- **Storage**: SQLite (`starnav.db`) holding a small graph — a `nodes` table (bodies with x/y/z) and an
  `edges` table (`orbits`: Moon→Earth, planets→Sun; `near`: star→Sun).
- **Viewer**: 3-D orbit camera locked on the Sun, Earth, or any body. Drag (or arrow keys) to swing
  around it at any angle, wheel or pinch to zoom (from lunar distance out to hundreds of light-years),
  click to inspect, double-click to lock on. Top / Tilted / Edge-on presets, auto-spin, and a
  "Height ×10" toggle that exaggerates how far each planet sits above or below the ecliptic.

## Live site

**https://arminforoughi.github.io/starnav/** — a static build on GitHub Pages. Stars, galaxies and
landmarks are prebuilt into `docs/data.json`; planet positions in `docs/planets.json` are refreshed
every day by a GitHub Actions job (`.github/workflows/planets.yml`) that calls JPL Horizons.
Rebuild the static site after changing the viewer or catalogs:

```bash
python3 fetch_planets.py && python3 build_static.py && git add docs && git commit -m "Rebuild site" && git push
```

## Run locally

```bash
python3 server.py
```

Then open http://127.0.0.1:8000. First start fetches planets (a few seconds) and the star catalog (~14 MB).

### On a phone

Run the server in LAN mode, then open the address it prints on a phone connected to the same Wi-Fi:

```bash
python3 server.py 8000 --lan
```

The page is touch-friendly: one finger tumbles, two fingers pinch-zoom, the ☰ button shows the controls.

## Rebuilding the Gaia layers

Two ADQL queries against the [Gaia archive](https://gea.esac.esa.int/archive/) (async TAP, no login needed):

```sql
-- gaia_stars.csv
SELECT ra, dec, parallax, phot_g_mean_mag, bp_rp FROM gaiadr3.gaia_source
 WHERE phot_g_mean_mag < 11.5 AND parallax > 0.05 AND parallax_over_error > 5
-- gaia_density.csv
SELECT FLOOR(ra/5) AS rb, FLOOR((dec+90)/5) AS db, FLOOR(1000.0/parallax/200.0) AS dist_bin, COUNT(*) AS n
  FROM gaiadr3.gaia_source
 WHERE parallax > 0.1 AND parallax_over_error > 3 AND phot_g_mean_mag + 5*LOG10(parallax) - 10 < 3.5
 GROUP BY rb, db, dist_bin
```

Then `python3 build_tiles.py <dir with the two csv files>` (needs numpy) and `python3 build_static.py`.

## API

- `GET  /api/bodies` – all nodes, edges and metadata
- `GET  /api/status` – background job status
- `POST /api/refresh?what=planets&epoch=YYYY-MM-DD HH:MM` – re-fetch planets from Horizons
- `POST /api/refresh?what=stars` – re-download the star catalog
- `POST /api/refresh?what=landmarks` – reload the built-in black hole / galaxy landmarks
- `POST /api/refresh?what=galaxies` – re-download the galaxy catalogs from VizieR
- `POST /api/refresh?what=cepheids` – re-download the Cepheid map from VizieR
