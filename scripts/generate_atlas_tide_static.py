#!/usr/bin/env python3
import argparse
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import uptide
from netCDF4 import Dataset

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATLAS_DIR = ROOT / "atlas" / "V1_AQUI"
DEFAULT_OUTPUT = ROOT / "data" / "shom" / "SAINT-MARTIN_DE_RE.json"

STATION = {
    "cst": "SAINT-MARTIN_DE_RE",
    "toponyme": "Saint-Martin-de-Re (Ile de Re)",
    "lat": 46.268493,
    "lon": -1.367113,
    "ut": 10,
}

CONSTITUENT_ALIASES = {
    "La2": "LAMBDA2",
    "Mf": "MF",
    "Mm": "MM",
    "Mu2": "MU2",
    "Nu2": "NU2",
}

# The atlas predicts sea level around a model mean level. SHOM-style displayed
# tide heights are relative to chart datum, so this constant is a local vertical
# offset. The default was calibrated against the Saint-Martin-de-Re May 2026
# high/low tide heights already present in the project cache.
DEFAULT_CHART_DATUM_OFFSET = 3.72
LOCAL_TIMEZONE = ZoneInfo("Europe/Paris")


def parse_day(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def month_key(day):
    return f"{day.year}-{day.month:02d}"


def normalize_constituent(name):
    return CONSTITUENT_ALIASES.get(name, name).upper()


def atlas_constituent(path):
    match = re.match(r"(.+)-XE-[^-]+-atlas\.nc$", path.name)
    return match.group(1) if match else None


def find_grid_point(atlas_file, lon, lat):
    with Dataset(atlas_file) as dataset:
        longitudes = dataset.variables["longitude"][:]
        latitudes = dataset.variables["latitude"][:]
        distance = (longitudes - lon) ** 2 + ((latitudes - lat) * math.cos(math.radians(lat))) ** 2
        row, col = np.unravel_index(np.nanargmin(distance), distance.shape)
        return {
            "row": int(row),
            "col": int(col),
            "lon": float(longitudes[row, col]),
            "lat": float(latitudes[row, col]),
            "distanceDegrees": float(math.sqrt(distance[row, col])),
        }


def read_harmonics(atlas_dir, grid_point):
    available = set(uptide.tidal.omega.keys())
    constituents = []
    amplitudes = []
    phases = []
    skipped = []

    for path in sorted(atlas_dir.glob("*-XE-*-atlas.nc")):
        source_name = atlas_constituent(path)
        if not source_name:
            continue
        constituent = normalize_constituent(source_name)
        if constituent not in available:
            skipped.append(source_name)
            continue
        with Dataset(path) as dataset:
            amplitude = dataset.variables["XE_a"][grid_point["row"], grid_point["col"]]
            phase = dataset.variables["XE_G"][grid_point["row"], grid_point["col"]]
            if np.ma.is_masked(amplitude) or np.ma.is_masked(phase):
                skipped.append(f"{source_name}:nodata")
                continue
            amplitude = float(amplitude)
            phase = float(phase)
            if not math.isfinite(amplitude) or not math.isfinite(phase):
                skipped.append(f"{source_name}:nodata")
                continue
            constituents.append(constituent)
            amplitudes.append(amplitude)
            phases.append(math.radians(phase))

    return {
        "constituents": constituents,
        "amplitudes": amplitudes,
        "phases": phases,
        "skipped": skipped,
    }


def predict_water_levels(harmonics, start_day, end_day, step_minutes, offset):
    start_local = datetime.combine(start_day, datetime.min.time())
    end_local = datetime.combine(end_day + timedelta(days=1), datetime.min.time())
    start_utc = start_local.replace(tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc).replace(tzinfo=None)

    tide = uptide.Tides(harmonics["constituents"])
    tide.set_initial_time(start_utc)

    points = []
    current_local = start_local
    while current_local <= end_local:
        utc_time = current_local.replace(tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc).replace(tzinfo=None)
        seconds = (utc_time - start_utc).total_seconds()
        model_height = float(tide.from_amplitude_phase(
            harmonics["amplitudes"],
            harmonics["phases"],
            seconds,
        ))
        points.append({
            "time": current_local,
            "height": round(model_height + offset, 3),
            "modelHeight": model_height,
        })
        current_local += timedelta(minutes=step_minutes)
    return points


def rows_by_day(points, start_day, end_day):
    days = defaultdict(list)
    for point in points:
        day = point["time"].date()
        if start_day <= day <= end_day:
            days[day.isoformat()].append([
                point["time"].strftime("%H:%M"),
                point["height"],
            ])
    return dict(sorted(days.items()))


def detect_events(points, start_day, end_day):
    raw_events = []
    for index in range(1, len(points) - 1):
        previous = points[index - 1]["modelHeight"]
        current = points[index]["modelHeight"]
        next_height = points[index + 1]["modelHeight"]
        event_type = None
        if (current >= previous and current > next_height) or (current > previous and current >= next_height):
            event_type = "tide.high"
        elif (current <= previous and current < next_height) or (current < previous and current <= next_height):
            event_type = "tide.low"
        if event_type:
            raw_events.append({**points[index], "type": event_type})

    events = defaultdict(list)
    for event in raw_events:
        day = event["time"].date()
        if start_day <= day <= end_day:
            events[day.isoformat()].append([
                event["type"],
                event["time"].strftime("%H:%M"),
                f"{event['height']:.2f}",
                "---",
            ])
    return dict(sorted(events.items()))


def event_ranges(events):
    previous = None
    ranges_by_day = defaultdict(list)
    for day, rows in sorted(events.items()):
        for row in rows:
            event_type, time_value, height_value = row[:3]
            current = {
                "type": event_type,
                "height": float(height_value),
            }
            if previous and previous["type"] != current["type"]:
                ranges_by_day[day].append(round(abs(current["height"] - previous["height"]), 2))
            previous = current
    return dict(sorted(ranges_by_day.items()))


def filter_days(mapping, start_day, end_day):
    return {
        day: value
        for day, value in sorted(mapping.items())
        if start_day <= parse_day(day) <= end_day
    }


def approximate_coefficients(events, start_day, end_day, reference_range):
    coefficients = defaultdict(lambda: [[] for _ in range(31)])
    previous = None
    for day, rows in sorted(events.items()):
        date_value = parse_day(day)
        for row in rows:
            current = {
                "type": row[0],
                "height": float(row[2]),
            }
            if (
                start_day <= date_value <= end_day
                and current["type"] == "tide.high"
                and previous
                and previous["type"] != current["type"]
            ):
                tide_range = abs(current["height"] - previous["height"])
                coefficient = max(20, min(120, round((tide_range / reference_range) * 100)))
                coefficients[month_key(date_value)][date_value.day - 1].append(str(coefficient))
            previous = current

    compact = {}
    for key, rows in coefficients.items():
        year, month = map(int, key.split("-"))
        month_length = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
        compact[key] = rows[:month_length]
    return dict(sorted(compact.items()))


def build_payload(args):
    atlas_files = sorted(args.atlas_dir.glob("*-XE-*-atlas.nc"))
    if not atlas_files:
        raise RuntimeError(f"no XE atlas files found in {args.atlas_dir}")

    grid_point = find_grid_point(atlas_files[0], args.lon, args.lat)
    harmonics = read_harmonics(args.atlas_dir, grid_point)
    if not harmonics["constituents"]:
        raise RuntimeError("no supported harmonic constituents found")

    prediction_start = args.start - timedelta(days=1)
    prediction_end = args.end + timedelta(days=1)
    points = predict_water_levels(harmonics, prediction_start, prediction_end, args.step, args.chart_datum_offset)
    all_events = detect_events(points, prediction_start, prediction_end)
    events = filter_days(all_events, args.start, args.end)
    ranges = filter_days(event_ranges(all_events), args.start, args.end)
    try:
        atlas_label = str(args.atlas_dir.resolve().relative_to(ROOT))
    except ValueError:
        atlas_label = str(args.atlas_dir)

    return {
        "station": {
            **STATION,
            "lat": args.lat,
            "lon": args.lon,
        },
        "source": {
            "provider": "ifremer-atlas",
            "atlas": atlas_label,
            "timezone": "Europe/Paris",
            "stepMinutes": args.step,
            "chartDatumOffsetMeters": args.chart_datum_offset,
            "coefficientReferenceRangeMeters": args.coefficient_reference_range,
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "availableFrom": args.start.isoformat(),
            "availableTo": args.end.isoformat(),
            "gridPoint": grid_point,
            "constituents": harmonics["constituents"],
            "skippedConstituents": harmonics["skipped"],
            "coefficientNote": "Coefficients are local range-based approximations, not official SHOM/Brest coefficients.",
        },
        "waterLevels": rows_by_day(points, args.start, args.end),
        "events": events,
        "ranges": ranges,
        "coefficients": approximate_coefficients(all_events, args.start, args.end, args.coefficient_reference_range),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Generate MaRe static tide JSON from IFREMER harmonic atlas")
    parser.add_argument("--atlas-dir", type=Path, default=DEFAULT_ATLAS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start", type=parse_day, default=date(2026, 1, 1))
    parser.add_argument("--end", type=parse_day, default=date(2026, 12, 31))
    parser.add_argument("--step", type=int, default=5)
    parser.add_argument("--lon", type=float, default=STATION["lon"])
    parser.add_argument("--lat", type=float, default=STATION["lat"])
    parser.add_argument("--chart-datum-offset", type=float, default=DEFAULT_CHART_DATUM_OFFSET)
    parser.add_argument("--coefficient-reference-range", type=float, default=5.35)
    args = parser.parse_args()
    if args.end < args.start:
        raise SystemExit("--end must be after --start")
    return args


def main():
    args = parse_args()
    payload = build_payload(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        f"wrote {args.output} "
        f"({len(payload['waterLevels'])} water-level days, "
        f"{len(payload['events'])} event days, "
        f"{len(payload['source']['constituents'])} constituents)"
    )
    if payload["source"]["skippedConstituents"]:
        print("skipped:", ", ".join(payload["source"]["skippedConstituents"]))


if __name__ == "__main__":
    main()
