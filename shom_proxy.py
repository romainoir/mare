#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError

HOST = "127.0.0.1"
PORT = 8002
SHOM_REFERER = "https://maree.shom.fr/"
SHOM_HDM = "https://services.data.shom.fr/b2q8lrcdl4s04cbabsj4nhcb/hdm"
SHOM_WFS = "https://services.data.shom.fr/x13f1b4faeszdyinv9zqxmx1/wfs"
SSL_CONTEXT = ssl._create_unverified_context()
LAND_MASK_PATH = Path(__file__).resolve().parent / "data" / "re_landmask.geojson"
LAND_MASK_CACHE = None


class Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/shom/wl":
            self.proxy_shom_water_levels(parsed.query)
            return
        if parsed.path == "/shom/hlt":
            self.proxy_shom_high_low_tides(parsed.query)
            return
        if parsed.path == "/shom/harbors":
            self.proxy_shom_harbors()
            return
        if parsed.path == "/shom/coeff":
            self.proxy_shom_coefficients(parsed.query)
            return
        if parsed.path == "/osm/land-mask":
            self.serve_land_mask()
            return
        self.send_error(404, "Not found")

    def proxy_shom_water_levels(self, query):
        params = parse_qs(query)
        safe = {
            "harborName": params.get("harborName", ["SAINT-MARTIN_DE_RE"])[0],
            "duration": params.get("duration", ["1"])[0],
            "date": params.get("date", ["2026-05-06"])[0],
            "utc": params.get("utc", ["standard"])[0],
            "nbWaterLevels": params.get("nbWaterLevels", ["288"])[0],
        }
        self.proxy(f"{SHOM_HDM}/spm/wl?{urlencode(safe)}")

    def proxy_shom_high_low_tides(self, query):
        params = parse_qs(query)
        safe = {
            "harborName": params.get("harborName", ["SAINT-MARTIN_DE_RE"])[0],
            "duration": params.get("duration", ["7"])[0],
            "date": params.get("date", ["2026-05-06"])[0],
            "utc": params.get("utc", ["standard"])[0],
            "correlation": params.get("correlation", ["1"])[0],
        }
        self.proxy(f"{SHOM_HDM}/spm/hlt?{urlencode(safe)}")

    def proxy_shom_coefficients(self, query):
        params = parse_qs(query)
        safe = {
            "harborName": params.get("harborName", ["SAINT-MARTIN_DE_RE"])[0],
            "duration": params.get("duration", ["365"])[0],
            "date": params.get("date", ["2026-01-01"])[0],
            "utc": params.get("utc", ["1"])[0],
            "correlation": params.get("correlation", ["1"])[0],
        }
        self.proxy(f"{SHOM_HDM}/spm/coeff?{urlencode(safe)}")

    def proxy_shom_harbors(self):
        params = {
            "service": "WFS",
            "version": "1.0.0",
            "srsName": "EPSG:3857",
            "request": "GetFeature",
            "typeName": "SPM_PORTS_WFS:liste_ports_spm_h2m",
            "outputFormat": "application/json",
        }
        self.proxy(f"{SHOM_WFS}?{urlencode(params)}")

    def serve_land_mask(self):
        global LAND_MASK_CACHE
        if LAND_MASK_CACHE is None:
            payload = json.loads(LAND_MASK_PATH.read_text(encoding="utf-8"))
            if payload.get("type") == "FeatureCollection":
                features = payload.get("features", [])
            elif payload.get("type") == "Feature":
                features = [payload]
            else:
                features = [{"type": "Feature", "properties": {}, "geometry": payload}]
            LAND_MASK_CACHE = {
                "type": "FeatureCollection",
                "features": [
                    feature for feature in features
                    if feature.get("geometry", {}).get("type") in {"Polygon", "MultiPolygon"}
                ],
            }

        body = json.dumps(LAND_MASK_CACHE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/geo+json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def proxy(self, url):
        request = Request(url, headers={"Referer": SHOM_REFERER, "User-Agent": "Estran local tide proxy"})
        try:
            with urlopen(request, timeout=20, context=SSL_CONTEXT) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type", "application/json")
                self.send_response(response.status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
        except HTTPError as error:
            body = error.read()
            self.send_response(error.code)
            self.send_header("Content-Type", error.headers.get("Content-Type", "text/plain"))
            self.end_headers()
            self.wfile.write(body)
        except Exception as error:
            body = str(error).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"SHOM proxy listening on http://{HOST}:{PORT}")
    server.serve_forever()
