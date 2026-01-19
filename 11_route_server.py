"""
Script: 11_route_server.py
==========================

Local HTTP server to rerun scenic routing from the HTML UI.

Start:
  python 11_route_server.py

Then click "Rerun routes" in outputs/routes.html.
"""

from __future__ import annotations

import json
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


class RouteHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/ping":
            self._send_json(200, {"ok": True})
            return
        if parsed.path != "/rerun":
            self._send_json(404, {"ok": False, "error": "Not found"})
            return

        params = parse_qs(parsed.query)
        try:
            origin_lat = float(params.get("origin_lat", [""])[0])
            origin_lon = float(params.get("origin_lon", [""])[0])
            dest_lat = float(params.get("dest_lat", [""])[0])
            dest_lon = float(params.get("dest_lon", [""])[0])
        except ValueError:
            self._send_json(400, {"ok": False, "error": "Invalid coordinates"})
            return
        source = params.get("source", ["mapillary"])[0]
        scenic_weight = params.get("scenic_weight", ["0.7"])[0]
        max_duration_ratio = params.get("max_duration_ratio", ["1.7"])[0]
        waypoint_count = params.get("waypoint_count", ["6"])[0]
        waypoint_radius = params.get("waypoint_radius", ["8000"])[0]
        waypoint_min_distance = params.get("waypoint_min_distance", ["2000"])[0]
        waypoint_min_separation = params.get("waypoint_min_separation", ["1500"])[0]

        cmd = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "run_routes.ps1",
            "-OriginLat",
            f"{origin_lat:.6f}",
            "-OriginLon",
            f"{origin_lon:.6f}",
            "-DestLat",
            f"{dest_lat:.6f}",
            "-DestLon",
            f"{dest_lon:.6f}",
            "-Source",
            source,
            "-ScenicWeight",
            scenic_weight,
            "-MaxDurationRatio",
            max_duration_ratio,
            "-WaypointCount",
            waypoint_count,
            "-WaypointRadius",
            waypoint_radius,
            "-WaypointMinDistance",
            waypoint_min_distance,
            "-WaypointMinSeparation",
            waypoint_min_separation,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except OSError as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})
            return

        if result.returncode != 0:
            self._send_json(
                500,
                {
                    "ok": False,
                    "error": "Route script failed",
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
            return

        self._send_json(200, {"ok": True, "stdout": result.stdout})

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    server = HTTPServer(("127.0.0.1", 8787), RouteHandler)
    print("Route server running on http://127.0.0.1:8787")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
