#!/usr/bin/env bash
set -euo pipefail

INPUT_DIR="${1:-asc}"
OUTPUT_PMTILES="${2:-bathymetrie_aquitaine_1m_512_composite.pmtiles}"

# Les fichiers Litto3D fournis ici sont en Lambert-93 / RGF93 / IGN69.
SOURCE_SRS="${SOURCE_SRS:-EPSG:2154}"
TARGET_SRS="${TARGET_SRS:-EPSG:3857}"
RESOLUTION="${RESOLUTION:-0.5}"
MNT_DIR="${MNT_DIR:-MNT1m}"
NODATA="${NODATA:--99999}"
NODATA_FILL_ELEVATION="${NODATA_FILL_ELEVATION:--20}"
WARP_RESAMPLING="${WARP_RESAMPLING:-cubicspline}"
TILE_SIZE="${TILE_SIZE:-512}"
MIN_ZOOM="${MIN_ZOOM:-11}"
MAX_ZOOM="${MAX_ZOOM:-18}"
FULL_RESOLUTION_ZOOM="${FULL_RESOLUTION_ZOOM:-19}"
COASTAL_REFERENCE="${COASTAL_REFERENCE:-NM}"
COASTAL_NODATA="${COASTAL_NODATA:--9999}"
COASTAL_SOURCE_SRS="${COASTAL_SOURCE_SRS:-EPSG:4326}"
COASTAL_RESAMPLING="${COASTAL_RESAMPLING:-bilinear}"
INCLUDE_FALLBACK_BOUNDS="${INCLUDE_FALLBACK_BOUNDS:-0}"
OUTPUT_BOUNDS_WGS84="${OUTPUT_BOUNDS_WGS84:-}"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/estran-pmtiles.XXXXXX")"
VENV_DIR="${VENV_DIR:-.venv-rgbify}"

cleanup() {
  if [[ "${KEEP_WORK:-0}" == "1" ]]; then
    echo "Fichiers temporaires conserves dans: $WORK_DIR"
  else
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

install_system_deps() {
  local missing_gdal=0
  for cmd in gdalbuildvrt gdalwarp; do
    if ! need_cmd "$cmd"; then
      missing_gdal=1
    fi
  done

  if [[ "$missing_gdal" == "1" ]]; then
    if need_cmd brew; then
      echo "Installation de GDAL via Homebrew..."
      brew install gdal
    elif need_cmd apt-get; then
      echo "Installation de GDAL via apt..."
      sudo apt-get update -yqq
      sudo apt-get install -yqq gdal-bin python3 python3-pip python3-venv curl tar
    else
      echo "GDAL est manquant. Installe-le puis relance le script." >&2
      exit 1
    fi
  fi

  if ! need_cmd pmtiles; then
    if need_cmd brew; then
      echo "Installation de pmtiles via Homebrew..."
      brew install pmtiles
    else
      echo "pmtiles est manquant. Installe l'outil Protomaps puis relance le script." >&2
      exit 1
    fi
  fi

  if ! need_cmd python3; then
    echo "python3 est manquant." >&2
    exit 1
  fi
}

echo "=== 1. Verification des dependances ==="
install_system_deps

echo "=== 2. Preparation de l'environnement Python ==="
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip --quiet
python -m pip install --quiet rasterio mercantile pmtiles pillow

echo "=== 3. Recherche des fichiers ASC ($MNT_DIR) ==="
ASC_LIST="$WORK_DIR/liste_asc.txt"
find "$INPUT_DIR" -type f -path "*/$MNT_DIR/*.asc" | sort > "$ASC_LIST"

if [[ ! -s "$ASC_LIST" ]]; then
  echo "Aucun fichier .asc trouve dans les dossiers $MNT_DIR sous: $INPUT_DIR" >&2
  echo "Astuce: pour utiliser les MNT1m, lance: MNT_DIR=MNT1m ./generer_pmtiles.sh asc" >&2
  exit 1
fi

ASC_COUNT="$(wc -l < "$ASC_LIST" | tr -d ' ')"
echo "$ASC_COUNT fichiers trouves."

echo "=== 4. Recherche du MNT cotier de remplissage ($COASTAL_REFERENCE) ==="
COASTAL_ASC_LIST="$WORK_DIR/liste_cotier.txt"
: > "$COASTAL_ASC_LIST"
case "$COASTAL_REFERENCE" in
  NM|PBMA)
    find "$INPUT_DIR" -type f -path "*/MNT_COTIER_PERTUIS_HOMONIM_${COASTAL_REFERENCE}/DONNEES/*.asc" | sort > "$COASTAL_ASC_LIST"
    ;;
  ALL)
    find "$INPUT_DIR" -type f -path "*/MNT_COTIER_PERTUIS_HOMONIM_*/DONNEES/*.asc" | sort > "$COASTAL_ASC_LIST"
    ;;
  NONE)
    ;;
  *)
    echo "COASTAL_REFERENCE doit valoir NM, PBMA, ALL ou NONE." >&2
    exit 1
    ;;
esac

FALLBACK_VRT=""
if [[ -s "$COASTAL_ASC_LIST" ]]; then
  COASTAL_COUNT="$(wc -l < "$COASTAL_ASC_LIST" | tr -d ' ')"
  echo "$COASTAL_COUNT fichier(s) cotier(s) trouve(s)."
  FALLBACK_VRT="$WORK_DIR/fallback_cotier.vrt"
  gdalbuildvrt -q -a_srs "$COASTAL_SOURCE_SRS" -srcnodata "$COASTAL_NODATA" -vrtnodata "$COASTAL_NODATA" \
    -input_file_list "$COASTAL_ASC_LIST" "$FALLBACK_VRT"
else
  echo "Aucun MNT cotier de remplissage trouve."
fi

echo "=== 5. Construction du VRT haute resolution en $SOURCE_SRS ==="
VRT="$WORK_DIR/combined.vrt"
gdalbuildvrt -q -a_srs "$SOURCE_SRS" -srcnodata "$NODATA" -vrtnodata "$NODATA" \
  -input_file_list "$ASC_LIST" "$VRT"

echo "=== 6. Reprojection haute resolution vers $TARGET_SRS a ${RESOLUTION}m/pixel ==="
REPROJECTED="$WORK_DIR/reprojected.tif"
gdalwarp -q \
  -s_srs "$SOURCE_SRS" \
  -t_srs "$TARGET_SRS" \
  -tr "$RESOLUTION" "$RESOLUTION" \
  -r "$WARP_RESAMPLING" \
  -srcnodata "$NODATA" \
  -dstnodata "$NODATA" \
  -multi \
  -co TILED=YES \
  -co COMPRESS=DEFLATE \
  -co BIGTIFF=YES \
  "$VRT" "$REPROJECTED"

echo "=== 7. Generation directe des tuiles DEM Terrarium ==="
echo "Priorite: MNT $MNT_DIR valide, puis MNT cotier $COASTAL_REFERENCE, puis ${NODATA_FILL_ELEVATION}m."
python - "$REPROJECTED" "$FALLBACK_VRT" "$OUTPUT_PMTILES" "$MIN_ZOOM" "$MAX_ZOOM" "$TILE_SIZE" "$FULL_RESOLUTION_ZOOM" "$NODATA" "$COASTAL_NODATA" "$NODATA_FILL_ELEVATION" "$COASTAL_RESAMPLING" "$INCLUDE_FALLBACK_BOUNDS" "$OUTPUT_BOUNDS_WGS84" <<'PY'
import os
import sys
import tempfile
from contextlib import nullcontext

import mercantile
import numpy as np
from affine import Affine
from PIL import Image
from pmtiles.tile import Compression, TileType, tileid_to_zxy, zxy_to_tileid
from pmtiles.writer import Writer
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds

source_path = sys.argv[1]
fallback_path = sys.argv[2] or None
output_path = sys.argv[3]
min_zoom = int(sys.argv[4])
max_zoom = int(sys.argv[5])
tile_size = int(sys.argv[6])
full_resolution_zoom = int(sys.argv[7])
nodata = float(sys.argv[8])
fallback_nodata = float(sys.argv[9])
nodata_fill = float(sys.argv[10])
fallback_resampling_name = sys.argv[11]
include_fallback_bounds = sys.argv[12] == "1"
output_bounds_arg = sys.argv[13].strip()

if tile_size != 512:
    raise SystemExit("Ce generateur direct est calibre pour TILE_SIZE=512.")

def resampling_from_name(name):
    normalized = name.lower().replace("-", "_")
    if not hasattr(Resampling, normalized):
        allowed = ", ".join(item.name for item in Resampling)
        raise SystemExit(f"COASTAL_RESAMPLING invalide: {name}. Valeurs possibles: {allowed}")
    return getattr(Resampling, normalized)

def tile_transform(bounds, size):
    return Affine(
        (bounds.right - bounds.left) / size,
        0,
        bounds.left,
        0,
        -(bounds.top - bounds.bottom) / size,
        bounds.top,
    )

def vertical_factor(z):
    return 2 ** (full_resolution_zoom - z) / 256

def encode_terrarium(data, z):
    data = np.nan_to_num(data, nan=nodata_fill, posinf=nodata_fill, neginf=nodata_fill).astype(np.float32)
    factor = vertical_factor(z)
    data = np.round(data / factor) * factor
    encoded = np.clip(data + 32768.0, 0.0, 65535.99609375)
    rgb = np.zeros((tile_size, tile_size, 3), dtype=np.uint8)
    rgb[:, :, 0] = np.floor(encoded / 256.0)
    rgb[:, :, 1] = np.floor(encoded % 256.0)
    rgb[:, :, 2] = np.floor((encoded - np.floor(encoded)) * 256.0)
    return rgb

def decode_terrarium(path):
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0

def save_png(rgb, path):
    Image.fromarray(rgb, "RGB").save(path, format="PNG", compress_level=6)

def clamped_wgs84_bounds(dataset):
    west, south, east, north = transform_bounds(dataset.crs, "EPSG:4326", *dataset.bounds, densify_pts=21)
    return (
        max(west, -180.0),
        max(south, -85.05112878),
        min(east, 180.0),
        min(north, 85.05112878),
    )

def parse_wgs84_bounds(value):
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise SystemExit("OUTPUT_BOUNDS_WGS84 doit etre: west,south,east,north")
    west, south, east, north = parts
    if west >= east or south >= north:
        raise SystemExit("OUTPUT_BOUNDS_WGS84 invalide: west/south/east/north incoherents")
    return (
        max(west, -180.0),
        max(south, -85.05112878),
        min(east, 180.0),
        min(north, 85.05112878),
    )

def union_bounds(a, b):
    return (
        min(a[0], b[0]),
        min(a[1], b[1]),
        max(a[2], b[2]),
        max(a[3], b[3]),
    )

def write_archive(tile_root, output_path, bounds_wgs84):
    tile_ids = []
    for root, _, files in os.walk(tile_root):
        for filename in files:
            if not filename.endswith(".png"):
                continue
            z, x, y = [int(value) for value in filename[:-4].split("-")]
            tile_ids.append(zxy_to_tileid(z, x, y))

    tile_ids.sort()
    min_lon, min_lat, max_lon, max_lat = bounds_wgs84
    if os.path.exists(output_path):
        os.remove(output_path)

    with open(output_path, "wb") as out:
        writer = Writer(out)
        for tile_id in tile_ids:
            z, x, y = tileid_to_zxy(tile_id)
            with open(os.path.join(tile_root, str(z), f"{z}-{x}-{y}.png"), "rb") as tile:
                writer.write_tile(tile_id, tile.read())

        writer.finalize(
            {
                "tile_type": TileType.PNG,
                "tile_compression": Compression.NONE,
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
                "min_lon_e7": int(min_lon * 1e7),
                "min_lat_e7": int(min_lat * 1e7),
                "max_lon_e7": int(max_lon * 1e7),
                "max_lat_e7": int(max_lat * 1e7),
                "center_zoom": min_zoom,
                "center_lon_e7": int((min_lon + max_lon) * 0.5 * 1e7),
                "center_lat_e7": int((min_lat + max_lat) * 0.5 * 1e7),
            },
            {
                "name": "bathymetrie_litto3d",
                "description": "Litto3D Terrarium DEM, MNT 1m with coastal MNT fallback",
                "format": "png",
                "encoding": "terrarium",
                "minzoom": str(min_zoom),
                "maxzoom": str(max_zoom),
                "type": "overlay",
            },
        )

fallback_context = rasterio.open(fallback_path) if fallback_path else nullcontext(None)
fallback_resampling = resampling_from_name(fallback_resampling_name)

with rasterio.open(source_path) as src, fallback_context as fallback_src, tempfile.TemporaryDirectory(prefix="estran-tiles.") as tile_root:
    if output_bounds_arg:
        bounds_wgs84 = parse_wgs84_bounds(output_bounds_arg)
    else:
        bounds_wgs84 = clamped_wgs84_bounds(src)
        if fallback_src is not None and include_fallback_bounds:
            bounds_wgs84 = union_bounds(bounds_wgs84, clamped_wgs84_bounds(fallback_src))

    west, south, east, north = bounds_wgs84
    if fallback_src is not None:
        fallback_crs = fallback_src.crs or "EPSG:4326"
        print(f"MNT cotier actif: {os.path.basename(fallback_path)} ({fallback_crs}, nodata {fallback_nodata:g}).")
    else:
        fallback_crs = None
        print("MNT cotier inactif: les zones absentes seront remplies directement.")

    max_tiles = list(mercantile.tiles(west, south, east, north, [max_zoom]))
    os.makedirs(os.path.join(tile_root, str(max_zoom)), exist_ok=True)
    print(f"{len(max_tiles)} tuiles z{max_zoom} a encoder depuis le Float32.")

    for index, tile in enumerate(max_tiles, start=1):
        bounds = mercantile.xy_bounds(tile)
        precise = np.full((tile_size, tile_size), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=precise,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=nodata,
            dst_transform=tile_transform(bounds, tile_size),
            dst_crs=src.crs,
            dst_nodata=np.nan,
            resampling=Resampling.cubic_spline,
            num_threads=2,
        )
        destination = precise
        if fallback_src is not None:
            fallback = np.full((tile_size, tile_size), np.nan, dtype=np.float32)
            reproject(
                source=rasterio.band(fallback_src, 1),
                destination=fallback,
                src_transform=fallback_src.transform,
                src_crs=fallback_crs,
                src_nodata=fallback_src.nodata if fallback_src.nodata is not None else fallback_nodata,
                dst_transform=tile_transform(bounds, tile_size),
                dst_crs=src.crs,
                dst_nodata=np.nan,
                resampling=fallback_resampling,
                num_threads=2,
            )
            destination = np.where(np.isfinite(precise), precise, fallback)

        out_path = os.path.join(tile_root, str(max_zoom), f"{tile.z}-{tile.x}-{tile.y}.png")
        save_png(encode_terrarium(destination, max_zoom), out_path)
        if index % 250 == 0:
            print(f"{index}/{len(max_tiles)} tuiles z{max_zoom}")

    for z in range(max_zoom - 1, min_zoom - 1, -1):
        child_dir = os.path.join(tile_root, str(z + 1))
        parent_dir = os.path.join(tile_root, str(z))
        os.makedirs(parent_dir, exist_ok=True)
        parent_tiles = set()
        for filename in os.listdir(child_dir):
            if filename.endswith(".png"):
                child_z, child_x, child_y = [int(value) for value in filename[:-4].split("-")]
                parent_tiles.add(mercantile.parent(mercantile.Tile(child_x, child_y, child_z), zoom=z))

        print(f"{len(parent_tiles)} tuiles z{z} par moyenne Float32 2x2.")
        for parent in sorted(parent_tiles):
            full = np.full((tile_size * 2, tile_size * 2), nodata_fill, dtype=np.float32)
            for row_offset in range(2):
                for col_offset in range(2):
                    child = mercantile.Tile(parent.x * 2 + col_offset, parent.y * 2 + row_offset, z + 1)
                    child_path = os.path.join(child_dir, f"{child.z}-{child.x}-{child.y}.png")
                    if not os.path.exists(child_path):
                        continue
                    row_start = row_offset * tile_size
                    col_start = col_offset * tile_size
                    full[row_start:row_start + tile_size, col_start:col_start + tile_size] = decode_terrarium(child_path)

            parent_data = full.reshape((tile_size, 2, tile_size, 2)).mean(axis=(1, 3))
            save_png(encode_terrarium(parent_data, z), os.path.join(parent_dir, f"{parent.z}-{parent.x}-{parent.y}.png"))

    write_archive(tile_root, output_path, (west, south, east, north))
PY

deactivate

echo "Termine: $OUTPUT_PMTILES"
