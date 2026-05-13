# Estran maintenance notes

This project renders a tide-aware coastal view with MapLibre, static tide data
generated from an IFREMER harmonic atlas, IGN orthophoto, a local land mask, and
a bathymetry DEM encoded as Terrarium PMTiles.

## Current runtime

- Main app: `viewer.html`
- Tide data: static JSON in `data/shom/SAINT-MARTIN_DE_RE.json` by default
- SHOM proxy: `shom_proxy.py`, optional with `?tideSource=proxy`
- HTML server: usually `python3 -m http.server 8000 --bind 127.0.0.1`
- PMTiles server: usually `pmtiles serve . --interface=127.0.0.1 --port=8080 --cors=*`
- Local default DEM in the viewer: `bathymetrie_aquitaine_1m_512_composite.pmtiles`
- Local default DEM tile URL base in `viewer.html`:
  `http://127.0.0.1:8080/bathymetrie_aquitaine_1m_512_composite`
- GitHub Pages default DEM: `bathymetrie_aquitaine_z15_unmasked.pmtiles`
- Alternate DEMs can be tested with `?dem=<pmtiles-basename>`, for example:
  `viewer.html?dem=bathymetrie_aquitaine_z15_unmasked&demMaxZoom=15`
- The debug panel exposes the same DEM switcher. It rewrites the URL with
  `dem`, `demMaxZoom`, and a cache-busting `v` parameter.
- GitHub Pages and local runs read a single static tide calendar from
  `data/shom/SAINT-MARTIN_DE_RE.json`; the committed cache is intentionally
  limited to `SAINT-MARTIN_DE_RE`.

Large source and generated data are local-only and ignored by Git:

- `asc/`
- `*.pmtiles`, except `bathymetrie_aquitaine_z15_unmasked.pmtiles`
- debug exports

## Bathymetry PMTiles generation

The current generator is `generer_pmtiles.sh`.

The important design is source priority per DEM pixel:

1. Use valid Litto3D/MNT 1 m data from `*/MNT1m/*.asc`.
2. If the 1 m tile has nodata, fill from the wider coastal MNT.
3. If both are missing, fill with `-20 m` so offshore nodata is deep water, not zero.

Default fallback is `COASTAL_REFERENCE=NM`, using:

- `asc/MNT_COTIER_PERTUIS_HOMONIM_NM/DONNEES/*.asc`

Do not merge the 20 m coastal MNT directly into the high-res VRT before warping.
The script keeps the 1 m raster as the primary source and samples the 20 m MNT
only during tile encoding for pixels where the 1 m raster is nodata. This avoids
degrading precise areas while still filling rectangles with no 1 m coverage.

Command used for the current PMTiles:

```bash
./generer_pmtiles.sh asc bathymetrie_aquitaine_1m_512_composite.pmtiles
```

Current generator defaults:

- `SOURCE_SRS=EPSG:2154` for Litto3D 1 m ASC files
- `COASTAL_SOURCE_SRS=EPSG:4326` for the HOMONIM coastal MNT
- `TARGET_SRS=EPSG:3857`
- `RESOLUTION=0.5`
- `TILE_SIZE=512`
- `MIN_ZOOM=11`
- `MAX_ZOOM=18`
- `FULL_RESOLUTION_ZOOM=19`
- `NODATA_FILL_ELEVATION=-20`

GitHub Pages archive:

```bash
MAX_ZOOM=15 ./generer_pmtiles.sh asc bathymetrie_aquitaine_z15_unmasked.pmtiles
```

Measured size:

- `bathymetrie_aquitaine_z15_unmasked.pmtiles`: about `54 MB`, small enough to
  commit for GitHub Pages testing.

Current PMTiles metadata after generation:

- Bounds: `[-1.681015, 46.134064, -1.407020, 46.324219]`
- Zooms: `11 -> 18`
- Encoding: `terrarium`
- Tile type: PNG

Verification commands:

```bash
pmtiles verify bathymetrie_aquitaine_1m_512_composite.pmtiles
pmtiles show bathymetrie_aquitaine_1m_512_composite.pmtiles
```

## Tide level and vertical offset

SHOM tide heights are relative to chart datum / zero hydrographique. The DEM is
in the terrestrial vertical reference used by the source elevation data, so the
viewer must convert SHOM tide height to DEM elevation before building the
`color-relief` expression.

The viewer does this in `setMaregramReadout`:

```js
const demLevel = point.height + selectedZhToDemOffset();
```

Important: this used to be a global `-3.0 m` offset. That created a fixed
artifact around DEM elevation `3.0 m`, visible as a thin contour in the tide
`color-relief`. The current value for the Ile de Re area is:

```js
const defaultZhToDemOffset = -3.504;
const zhToDemOffsetByHarbor = {
  "LA_ROCHELLE-PALLICE": -3.504,
  "SAINT-MARTIN_DE_RE": -3.504
};
```

Saint-Martin-de-Re has `ch_ref = LA_ROCHELLE-PALLICE` in the SHOM harbor
metadata, so it uses the La Rochelle-La Pallice offset. If more harbors are added
later, add their offset keyed either by station `cst` or by `ch_ref`.

Do not switch back to a hardcoded `-3` offset unless the DEM vertical reference
and the SHOM zero are intentionally changed.

## Tide color-relief layer

The water overlay is a MapLibre `color-relief` layer:

- Layer id: `tide-overlay`
- Source: `masked-bathymetrie`
- Expression: `tideColorExpression(level, tideLayerOpacity)`
- Default water opacity slider value: `220%`

The foam line is a separate, very thin `color-relief` layer:

- Layer id: `tide-foam`
- Expression: `tideFoamExpression(level, tideLayerOpacity)`

Both tide layers use:

```js
"resampling": "nearest"
```

This avoids creating visual contour artifacts from DEM interpolation. The foam is
only cosmetic; if a contour artifact appears at a fixed DEM elevation, check the
vertical offset first.

## Masked DEM protocol

`viewer.html` registers:

```js
maplibregl.addProtocol("masked-dem", maskedDemProtocol);
```

The protocol fetches the PMTiles-served Terrarium PNG tile, then applies:

- missing/empty ocean tile -> `-20 m`
- local land mask -> `12000 m`, unless `tideMask=0`

The MapLibre `raster-dem` source keeps the working GitHub behavior with source
`maxzoom=18`. This is not a tide layer visibility cap; it tells MapLibre the
native tile request ceiling. The layer can still render above it.

`maskedDemProtocol` handles lower-resolution archives itself. It infers the
native DEM max zoom from the `?dem=` basename (`z15`, `z16`, etc.) or from
`?demMaxZoom=...`, fetches the parent native tile, and crops/upscales it with
image smoothing disabled. If a requested/native tile is missing, the protocol
walks down to parent zooms before falling back to the offshore `-20 m` tile. This
keeps `z15` test archives usable while preserving the source behavior that
worked in the GitHub version.

When the tide land mask is enabled, GitHub Pages also uses `maskedDemProtocol`.
The protocol reads directly from the committed PMTiles archive and applies
`data/re_landmask.geojson` before handing the Terrarium tile to MapLibre.
The masked tiles are encoded back to explicit RGB PNGs, not canvas-generated
RGBA PNGs, because the DEM decoder only needs Terrarium RGB values. If the
runtime masking path fails on a browser, it now fails open and returns the
unmasked DEM tile instead of making the tide color-relief disappear.

When the tide land mask is disabled with `tideMask=0`, GitHub Pages bypasses
`maskedDemProtocol` for the committed static PMTiles archive and uses the
official PMTiles MapLibre protocol directly:

```js
maplibregl.addProtocol("pmtiles", new Protocol().tile);
```

The source then uses `url: "pmtiles://..."`, matching the pattern used by
PMTiles/MapLibre examples.

For debugging tile overzoom, add `?demDebug=1` to the viewer URL and inspect the
console logs for `DEM tile hit` / `DEM tile miss`.

The debug panel can disable the runtime tide land mask. For full tide
color-relief over the orthophoto, use `bathymetrie_aquitaine_z15_unmasked` with
`tideMask=0`.

The runtime land mask defaults to:

```text
data/re_landmask.geojson
```

It can be overridden with `?landMask=path/to/mask.geojson`. The high land value
makes masked land transparent in the tide `color-relief`, because it is far above
the last color stop.

For backward compatibility, `shom_proxy.py` still serves `/osm/land-mask`, but it
now returns the same local `data/re_landmask.geojson` content rather than querying
Nominatim.

If artifacts appear exactly on land boundaries, inspect the mask protocol and
resampling. If artifacts appear at a fixed tide/DEM elevation everywhere, inspect
the SHOM-to-DEM offset first.

## Static Tide Calendar

The Pages build stores tide data as one JSON file per station, currently:

```text
data/shom/SAINT-MARTIN_DE_RE.json
```

The preferred static source is now the IFREMER harmonic atlas in `atlas/V1_AQUI`.
The atlas contains one NetCDF per harmonic constituent. `*-XE-*` files are used
for sea-surface height; `*-U-*` and `*-V-*` are current components and are not
used for the maregram.

Generate the cache with:

```bash
python3 -m venv .venv-tide
source .venv-tide/bin/activate
pip install -r requirements-tide.txt
python3 scripts/generate_atlas_tide_static.py --start 2026-01-01 --end 2026-12-31
```

The generated file stores dense 5-minute water-level rows in `waterLevels`,
high/low tide events derived from those rows in `events`, tide ranges in
`ranges`, and approximate local coefficients derived from those ranges. The
coefficient is not the official SHOM/Brest coefficient.

The atlas prediction uses the harmonic formula implemented by `uptide`, with
IFREMER amplitudes and phases in UTC. The atlas does not include an elevation
`Z0` file, so the script adds a local chart-datum offset:

```text
chartDatumOffsetMeters = 3.72
```

This value was calibrated against Saint-Martin-de-Re May 2026 high/low tide
heights previously cached from SHOM/maree.info-style tables. Changing this value
moves all water levels up or down without changing tide timing or range.

If `waterLevels` is absent, the viewer falls back to the older cosine
interpolation between each pair of successive extrema:

```js
height = previous.height + (next.height - previous.height) * (1 - cos(pi * t)) / 2
```

The older SHOM generator is kept as a reference, but it is not the current
preferred way to build the Pages cache.

## MapLibre

The app uses MapLibre GL JS ESM:

```html
https://unpkg.com/maplibre-gl@6.0.0-8/dist/maplibre-gl.mjs
```

The worker is loaded locally:

```js
vendor/maplibre-gl-worker-6.0.0-8.mjs
```

Rotation is intentionally disabled; the app is kept in 2D.
