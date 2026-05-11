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

This file is currently about 2.3 GB. It cannot be committed to this repository
for GitHub Pages:

- GitHub rejects regular Git files larger than 100 MB.
- Git LFS cannot be used by GitHub Pages sites.
- Published GitHub Pages sites may not be larger than 1 GB.

For a deployed Pages version, keep the app on GitHub Pages and host the PMTiles
archive on storage that supports HTTP range requests and CORS, such as
Cloudflare R2, S3, or another static object store. The viewer then needs to be
configured to read that remote PMTiles URL instead of the local `pmtiles serve`
tile endpoint.

See `NOTES.md` for the full PMTiles generation pipeline and the SHOM/DEM offset
details.
