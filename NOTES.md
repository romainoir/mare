# Estran maintenance notes

This project renders a tide-aware coastal view with MapLibre, SHOM tide data,
IGN orthophoto, an OSM land mask, and a bathymetry DEM encoded as Terrarium
PMTiles.

## Current runtime

- Main app: `viewer.html`
- SHOM/OSM proxy: `shom_proxy.py`, expected on `http://127.0.0.1:8002`
- HTML server: usually `python3 -m http.server 8000 --bind 127.0.0.1`
- PMTiles server: usually `pmtiles serve . --interface=127.0.0.1 --port=8080 --cors=*`
- Current DEM in the viewer: `bathymetrie_aquitaine_1m_512_composite.pmtiles`
- Current DEM tile URL base in `viewer.html`:
  `http://127.0.0.1:8080/bathymetrie_aquitaine_1m_512_composite`

Large source and generated data are local-only and ignored by Git:

- `asc/`
- `*.pmtiles`
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
- OSM land mask -> `12000 m`

The land mask comes from `shom_proxy.py` at `/osm/land-mask`. The high land value
makes land transparent in the tide `color-relief`, because it is far above the
last color stop.

If artifacts appear exactly on land boundaries, inspect the mask protocol and
resampling. If artifacts appear at a fixed tide/DEM elevation everywhere, inspect
the SHOM-to-DEM offset first.

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
