# Star Nav

A real-scale 3D map of the measured universe, from satellites in low Earth orbit out to the edge of
the observable universe. Every point is a catalog entry with a real position. Lock the camera on any
body, tumble around it at any angle, and zoom from 400 km above Earth to 100 billion light-years.

**Live site:** https://arminforoughi.github.io/starnav/ · **Code:** https://github.com/arminforoughi/starnav

It is a static web page (one HTML file, no framework) plus a small Python toolchain that fetches open
data, builds the catalogs, and serves them locally. Nothing runs on a server for visitors.

## What you can do

- **Lock on anything**: the Sun, a planet, the Moon, a star, a black hole, a galaxy, a satellite. The
  view stays centred on it while you drag to orbit around it and scroll to zoom. Double-click any
  object to lock on it; click for its card.
- **Zoom across 15 orders of magnitude**, from 20,000 km wide to 100 billion light-years. Range rings
  and the scale bar switch units (km, AU, light-years, parsecs) as you go.
- **See planets as globes**: real surface maps, sunlit with the true phase, rotating about their real
  axes. Earth's map is aligned to the current time so the daylight side is correct. Saturn has rings
  with the planet's shadow across them.
- **Watch satellites move live**: 11,600 tracked objects propagated in real time; click one for its
  altitude, speed, period, and next orbit.
- **Read every object's card**: distance, light travel time, brightness, size, spectral type, redshift,
  planets, and a plain-language note with links to Wikipedia, SIMBAD, NED, or N2YO.
- **Play the tour**: a scripted 70-second flight from Earth to the edge of the observable universe with
  captions naming distances along the way, and the reverse trip. The Record toggle saves it to a video.
- **Toggle layers**: orbit rings, range rings, height lines, height ×10, Gaia stars, galaxy density,
  model disk, Cepheids, star clusters, exoplanet hosts, satellites, Starlink, galaxy guides, star names.
- **Pick a date** (local server only) to move the planets to any epoch JPL can compute.

## What's in it

| Layer | Objects | Source | Notes |
|---|---|---|---|
| Sun, planets, Moon, Pluto | 11 | [NASA/JPL Horizons](https://ssd-api.jpl.nasa.gov/doc/horizons.html) | positions refetched daily; surface maps from [Solar System Scope](https://www.solarsystemscope.com/textures/) (CC BY 4.0) |
| Earth satellites | 11,609 | [CelesTrak](https://celestrak.org/) GP elements | ISS, Hubble, GPS, Galileo, weather, geostationary, all Starlink; SGP4 in a web worker |
| Stars with distances | 109,400 | [HYG v4](https://github.com/astronexus/HYG-Database) (CC BY-SA 4.0) | Hipparcos, Yale, Gliese; drawn at true size when zoomed in, radius from luminosity and spectral type |
| Gaia star tiles | 1.9 million | [Gaia DR3](https://gea.esac.esa.int/archive/) | G < 11.5, good parallaxes; streamed by cell and luminosity tier under a per-frame point budget |
| Milky Way density | 89,000 voxels | Gaia DR3 star counts | volume-limited to bright stars; a calibrated exponential-disk + spiral-arm model fills in beyond Gaia's reach, drawn in a different colour and switchable off |
| Cepheids | 2,214 | OGLE map, Skowron+ 2019 | real stars across the whole disk including the far side; period–luminosity distances |
| Open clusters | 1,867 | Cantat-Gaudin+ 2020 | Gaia members; age and member count on the card |
| Globular clusters | 145 | Harris 2010 | metal content, brightness, distance from the galactic centre |
| Exoplanet host stars | 4,747 | [NASA Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/) | each card lists the planets with size, period, discovery year |
| Galaxies, measured distances | 869 | Local Volume catalog, Karachentsev+ 2013 | within 36 million ly |
| Galaxies, redshift distances | 43,280 | 2MASS Redshift Survey, Huchra+ 2012 | out to ~1 billion ly, H0 = 70 |
| Abell galaxy clusters | 568 | Abell/ACO 1989 | those with measured redshifts, sized by richness |
| Landmarks | 29 | curated | black holes (Sgr A*, Gaia BH1–3, Cygnus X-1, V404 Cyg, …), nebulae, the Magellanic Clouds, Andromeda, Virgo, Coma, Perseus, the Great Attractor, Shapley, the Sloan Great Wall, the quasar 3C 273 |
| Reference rings | | | Milky Way bulge and disk edge, the Sun's galactic orbit, the edge of the observable universe at 46.5 billion ly |

About 176,000 catalogued objects in the database plus 1.9 million Gaia stars in tiles.

Coordinates are heliocentric ecliptic J2000 in AU throughout. Galaxy distances past 36 million ly come
from redshift and are only as good as the Hubble constant. The dark band through the galaxy cloud is
the Milky Way's own dust, not empty space. The far side of the Milky Way is a model; nobody has seen it.

## How it works

```
Open data ──► fetch/build scripts ──► SQLite (local) ──► docs/  (static site) ──► GitHub Pages
  JPL, CelesTrak      server.py            starnav.db          data.json, tiles/,     (CDN, no server)
  HYG, VizieR,        build_tiles.py                           galaxy.bin, tex/,
  Gaia, NASA EA       build_static.py                          satellites.json,
                      fetch_*.py                               planets.json, index.html
```

- `static/index.html` is the whole viewer: a canvas with a trackball camera, a pixel-buffer star
  renderer, per-pixel textured globes, a density splatter, a tile streamer, and the tour engine.
- `server.py` is a standard-library Python server for local use. It seeds the database from the open
  sources on first start, serves the viewer and the built assets, and exposes a small API.
- `build_tiles.py` sorts Gaia stars into distance shells × sky patches × luminosity tiers (2,278 binary
  tiles) and builds the density voxels. `build_static.py` exports everything to `docs/` for hosting.
- `fetch_planets.py` and `fetch_satellites.py` run daily in GitHub Actions
  (`.github/workflows/planets.yml`) so the live site's planets and satellite elements stay fresh.
- A visitor downloads about 8 MB up front (5.8 MB catalog, 0.7 MB satellites, textures on demand) and
  a few MB of star tiles as they zoom. Frame times are 10–35 ms on a laptop at every zoom level.

## Run locally

```bash
python3 server.py            # http://127.0.0.1:8000
python3 server.py 8000 --lan # also reachable from phones on the same Wi-Fi (prints the address)
./start.sh                   # same, in the background, restartable
```

First start fetches the planets, the 14 MB star catalog, the galaxy catalogs, Cepheids, clusters,
and exoplanet hosts (a few minutes total). The Gaia tiles, density layer, textures, and satellites
are read from `docs/` and are already in the repository.

On a phone the page is touch-friendly: one finger tumbles, two fingers pinch-zoom, ☰ shows the menu.

## Rebuild and publish

```bash
python3 fetch_planets.py && python3 fetch_satellites.py   # fresh JPL + CelesTrak data
python3 build_static.py                                    # export docs/
git add docs && git commit -m "Rebuild site" && git push   # GitHub Pages redeploys in ~1 minute
```

### Rebuilding the Gaia layers

Two ADQL queries against the Gaia archive (async TAP, no login needed):

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

### Recording the tour

In the app, press **● Record** then **▶ Zoom out** or **▶ Zoom in**. On the live site the video
downloads when the tour ends; on the local server it is saved to `captures/`. For a frame-perfect
render regardless of screen refresh, run `renderTourFrames('out')` in the browser console against the
local server, then assemble with ffmpeg:

```bash
ffmpeg -framerate 30 -i captures/frames-out/%05d.jpg -vf scale=1920:1080 -c:v libx264 -crf 19 -movflags +faststart starnav-zoom-out.mp4
```

## Local API

- `GET  /api/bodies` – all nodes, edges and metadata
- `GET  /api/status` – background job status
- `POST /api/refresh?what=planets&epoch=YYYY-MM-DD HH:MM` – re-fetch planets from Horizons
- `POST /api/refresh?what=stars|galaxies|cepheids|extras|landmarks` – re-download a catalog
- `POST /api/recording?name=…` / `POST /api/frame?dir=…&i=…` – used by the tour recorder

Environment knobs: `STARNAV_MAG_LIMIT` and `STARNAV_NEAR_PC` (star catalog cut), `STARNAV_LAN=1`,
`SAT_CACHE_DIR` (fallback TLE files if CelesTrak refuses a repeat download).

## Credits

Data: NASA/JPL Horizons, CelesTrak, ESA Gaia DR3, HYG Database (David Nash, CC BY-SA 4.0), VizieR/CDS
(Karachentsev+ 2013, Huchra+ 2012, Skowron+ 2019, Cantat-Gaudin+ 2020, Harris 2010, Abell/ACO 1989),
NASA Exoplanet Archive. Planet maps: Solar System Scope (CC BY 4.0). Satellite propagation: satellite.js.
