#!/usr/bin/env python3
import calendar
import json
import ssl
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SHOM_HDM = "https://services.data.shom.fr/b2q8lrcdl4s04cbabsj4nhcb/hdm"
SHOM_REFERER = "https://maree.shom.fr/"
SSL_CONTEXT = ssl._create_unverified_context()
STATIONS = [
    "SAINT-MARTIN_DE_RE",
]
ROOT = Path(__file__).resolve().parents[1] / "data" / "shom"


def request_json(path, params):
    url = f"{SHOM_HDM}{path}?{urlencode(params)}"
    request = Request(url, headers={"Referer": SHOM_REFERER, "User-Agent": "MaRe static data builder"})
    last_error = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            last_error = RuntimeError(f"{error.code} {error.read().decode('utf-8', errors='replace')}")
        except Exception as error:
            last_error = error
        time.sleep(0.7 * (attempt + 1))
    raise last_error


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def days_for_month(year, month):
    count = calendar.monthrange(year, month)[1]
    return [date(year, month, day) for day in range(1, count + 1)]


def fetch_water_level_day(station, day):
    payload = request_json("/spm/wl", {
        "harborName": station,
        "duration": "1",
        "date": day.isoformat(),
        "utc": "standard",
        "nbWaterLevels": "288",
    })
    return day.isoformat(), payload.get(day.isoformat(), [])


def build_water_levels(station, year, month):
    month_payload = {}
    for day in days_for_month(year, month):
        try:
            key, values = fetch_water_level_day(station, day)
            month_payload[key] = values
        except RuntimeError as error:
            print(f"{station} wl {day.isoformat()} skipped: {error}")
    month_key = f"{year}-{month:02d}"
    if month_payload:
        write_json(ROOT / "wl" / station / f"{month_key}.json", dict(sorted(month_payload.items())))
        print(f"{station} wl {month_key}")


def build_high_low_tides(station, year, month):
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    current = start
    payload = {}
    while current <= end:
        try:
            chunk = request_json("/spm/hlt", {
                "harborName": station,
                "duration": "7",
                "date": current.isoformat(),
                "utc": "standard",
                "correlation": "1",
            })
            month_prefix = f"{year}-{month:02d}-"
            for key, values in chunk.items():
                if key.startswith(month_prefix):
                    payload[key] = values
        except RuntimeError as error:
            print(f"{station} hlt {current.isoformat()} skipped: {error}")
        current += timedelta(days=7)
    if payload:
        write_json(ROOT / "hlt" / station / f"{year}.json", dict(sorted(payload.items())))
        print(f"{station} hlt {year}-{month:02d}")


def build_coefficients(station, year, month):
    month_key = f"{year}-{month:02d}"
    rows = request_json("/spm/coeff", {
        "harborName": station,
        "duration": str(calendar.monthrange(year, month)[1]),
        "date": f"{month_key}-01",
        "utc": "1",
        "correlation": "1",
    })
    payload = {month_key: rows[0] if rows else []}
    print(f"{station} coeff {month_key}")
    write_json(ROOT / "coeff" / station / f"{year}.json", payload)


def main():
    today = date.today()
    for station in STATIONS:
        build_water_levels(station, today.year, today.month)
        build_high_low_tides(station, today.year, today.month)
        build_coefficients(station, today.year, today.month)


if __name__ == "__main__":
    main()
