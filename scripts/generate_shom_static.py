#!/usr/bin/env python3
import calendar
import json
import ssl
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SHOM_HDM = "https://services.data.shom.fr/b2q8lrcdl4s04cbabsj4nhcb/hdm"
SHOM_REFERER = "https://maree.shom.fr/"
SSL_CONTEXT = ssl._create_unverified_context()
ROOT = Path(__file__).resolve().parents[1] / "data" / "shom"
STATION = {
    "cst": "SAINT-MARTIN_DE_RE",
    "toponyme": "Saint-Martin-de-Re (Ile de Re)",
    "lat": 46.208,
    "lon": -1.3655,
    "ut": 10,
}


def request_json(path, params):
    url = f"{SHOM_HDM}{path}?{urlencode(params)}"
    request = Request(url, headers={"Referer": SHOM_REFERER, "User-Agent": "MaRe static tide builder"})
    last_error = None
    for attempt in range(2):
        try:
            with urlopen(request, timeout=25, context=SSL_CONTEXT) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            last_error = RuntimeError(f"{error.code} {error.read().decode('utf-8', errors='replace')}")
        except Exception as error:
            last_error = error
        time.sleep(0.6 * (attempt + 1))
    raise last_error


def month_key(year, month):
    return f"{year}-{month:02d}"


def fetch_month_events(station, year, month):
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    current = start
    events = {}
    prefix = f"{year}-{month:02d}-"

    while current <= end:
        try:
            payload = request_json("/spm/hlt", {
                "harborName": station,
                "duration": "7",
                "date": current.isoformat(),
                "utc": "standard",
                "correlation": "1",
            })
            for key, rows in payload.items():
                if key.startswith(prefix):
                    events[key] = rows
        except RuntimeError as error:
            print(f"{station} hlt {current.isoformat()} skipped: {error}")
        current += timedelta(days=7)

    return dict(sorted(events.items()))


def fetch_month_coefficients(station, year, month):
    key = month_key(year, month)
    payload = request_json("/spm/coeff", {
        "harborName": station,
        "duration": str(calendar.monthrange(year, month)[1]),
        "date": f"{key}-01",
        "utc": "1",
        "correlation": "1",
    })
    return payload[0] if payload else []


def build_calendar(years):
    station = STATION["cst"]
    events = {}
    coefficients = {}

    for year in years:
        for month in range(1, 13):
            key = month_key(year, month)
            month_events = fetch_month_events(station, year, month)
            if month_events:
                events.update(month_events)
                print(f"{station} events {key}")
            try:
                month_coefficients = fetch_month_coefficients(station, year, month)
                if month_coefficients:
                    coefficients[key] = month_coefficients
                    print(f"{station} coeff {key}")
            except RuntimeError as error:
                print(f"{station} coeff {key} skipped: {error}")

    return {
        "station": STATION,
        "generatedAt": date.today().isoformat(),
        "yearsRequested": years,
        "events": dict(sorted(events.items())),
        "coefficients": dict(sorted(coefficients.items())),
    }


def main():
    years = [int(value) for value in sys.argv[1:]] if len(sys.argv) > 1 else [date.today().year]
    payload = build_calendar(years)
    ROOT.mkdir(parents=True, exist_ok=True)
    output = ROOT / f"{STATION['cst']}.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {output} ({len(payload['events'])} event days, {len(payload['coefficients'])} coefficient months)")


if __name__ == "__main__":
    main()
