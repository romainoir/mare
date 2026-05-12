# MaRe

MapLibre viewer for an intertidal coastal map around Ile de Re, with SHOM tide
data, IGN orthophoto, a local land mask, and a Terrarium bathymetry DEM served
from PMTiles.

## Run locally

Start the SHOM proxy:

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

To test another PMTiles served by `pmtiles serve`, pass its basename with
`?dem=`:

```text
http://127.0.0.1:8000/viewer.html?dem=bathymetrie_aquitaine_z15_unmasked&demMaxZoom=15
```

The viewer infers the native archive zoom from names such as `z15` or `z16` and
overzooms higher map zooms internally. If the filename does not contain that
pattern, pass it explicitly:

```text
http://127.0.0.1:8000/viewer.html?dem=my_tiles&demMaxZoom=15
```

The same values can be changed from the debug panel in the app. The PMTiles
field accepts either a local `pmtiles serve` basename, such as
`bathymetrie_aquitaine_z15_unmasked`, a static `.pmtiles` URL, or a full tile
URL base.

The debug panel also has a tide land-mask toggle. To let the tide color relief
cover land/shore pixels, disable `Masque terre marée` and use an unmasked DEM,
for example:

```text
http://127.0.0.1:8000/viewer.html?dem=bathymetrie_aquitaine_z15_unmasked&demMaxZoom=15&tideMask=0
```

When the tide mask is enabled, the viewer uses:

```text
data/re_landmask.geojson
```

You can test another mask with `?landMask=path/to/mask.geojson`.

## Data

Large local data and generated artifacts are intentionally not tracked in Git:

- `asc/`
- `*.pmtiles`, except the small GitHub Pages archive
  `bathymetrie_aquitaine_z15_unmasked.pmtiles`
- debug exports

The current app expects this local PMTiles file next to `viewer.html`:

```text
bathymetrie_aquitaine_1m_512_composite.pmtiles
```

This file is currently about 2.3 GB. It is intentionally local-only and is too
large to commit for GitHub Pages:

- GitHub rejects regular Git files larger than 100 MB.
- Git LFS cannot be used by GitHub Pages sites.
- Published GitHub Pages sites may not be larger than 1 GB.

For GitHub Pages, the viewer defaults to this smaller unmasked archive when it
is not running on `localhost`:

```text
bathymetrie_aquitaine_z15_unmasked.pmtiles
```

Its maximum zoom is `15`, so it is visibly less precise than the full local
`z18` archive, but it is small enough to commit and can be read directly by the
browser as a static PMTiles file.

See `NOTES.md` for the full PMTiles generation pipeline and the SHOM/DEM offset
details.
