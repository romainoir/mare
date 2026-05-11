# MaRe

MapLibre viewer for an intertidal coastal map around Ile de Re, with SHOM tide
data, IGN orthophoto, OSM land masking, and a Terrarium bathymetry DEM served
from PMTiles.

## Run locally

Start the SHOM/OSM proxy:

```bash
python3 shom_proxy.py
```

Serve the app:

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

Serve the local PMTiles archive:

```bash
pmtiles serve . --interface=127.0.0.1 --port=8080 --cors=*
```

Then open:

```text
http://127.0.0.1:8000/viewer.html
```

## Data

Large local data and generated artifacts are intentionally not tracked in Git:

- `asc/`
- `*.pmtiles`
- debug exports

The current app expects this local PMTiles file next to `viewer.html`:

```text
bathymetrie_aquitaine_1m_512_composite.pmtiles
```

See `NOTES.md` for the full PMTiles generation pipeline and the SHOM/DEM offset
details.

