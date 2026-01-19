"""
Script: 02_grid_samples.py
==========================

Generate a uniform grid of sample points inside a circular search area.
These samples are used to pull Mapillary imagery on a regular spatial
lattice, producing a more uniform scenic surface than road-only sampling.

Usage
-----
python 02_grid_samples.py \
  --center-lat 42.5389 \
  --center-lon -71.0481 \
  --radius 25000 \
  --step 200 \
  --output data/osm/grid_samples.geojson
"""

import argparse
import json
import math
import os
from typing import List, Tuple

from natura.geo import haversine_m


def meters_to_lat_delta(meters: float) -> float:
    return meters / 111_320.0


def meters_to_lon_delta(meters: float, lat: float) -> float:
    return meters / (111_320.0 * max(0.0001, math.cos(math.radians(lat))))


def iter_grid_points(center_lat: float, center_lon: float, radius_m: float, step_m: float) -> List[Tuple[float, float, int, int]]:
    if step_m <= 0:
        raise ValueError("step must be > 0")

    lat_step = meters_to_lat_delta(step_m)
    lat_radius = meters_to_lat_delta(radius_m)
    min_lat = center_lat - lat_radius
    max_lat = center_lat + lat_radius

    points: List[Tuple[float, float, int, int]] = []
    row = 0
    lat = min_lat
    while lat <= max_lat + 1e-12:
        lon_step = meters_to_lon_delta(step_m, lat)
        lon_radius = meters_to_lon_delta(radius_m, lat)
        min_lon = center_lon - lon_radius
        max_lon = center_lon + lon_radius
        col = 0
        lon = min_lon
        while lon <= max_lon + 1e-12:
            if haversine_m(center_lat, center_lon, lat, lon) <= radius_m:
                points.append((lat, lon, row, col))
            lon += lon_step
            col += 1
        lat += lat_step
        row += 1
    return points


def build_test_grid_samples() -> List[Tuple[float, float, int, int]]:
    """Return a fixed 1km grid for a known test area."""
    center_lat = 42.5389
    center_lon = -71.0481
    radius_m = 25_000.0
    step_m = 1000.0
    return iter_grid_points(center_lat, center_lon, radius_m, step_m)


def build_feature_collection(points: List[Tuple[float, float, int, int]]) -> dict:
    features = []
    for idx, (lat, lon, row, col) in enumerate(points):
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "grid_id": f"r{row}_c{col}",
                    "grid_row": row,
                    "grid_col": col,
                    "grid_index": idx,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def ensure_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a uniform grid of sample points within a radius")
    parser.add_argument("--center-lat", type=float, required=True, help="Center latitude")
    parser.add_argument("--center-lon", type=float, required=True, help="Center longitude")
    parser.add_argument("--radius", type=float, default=25_000.0, help="Radius in meters (default: 25000)")
    parser.add_argument("--step", type=float, default=200.0, help="Grid spacing in meters (default: 200)")
    parser.add_argument(
        "--test-grid",
        action="store_true",
        help="Use a fixed 1km grid test case (overrides center/radius/step)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/osm/grid_samples.geojson",
        help="Path to write GeoJSON point grid",
    )
    args = parser.parse_args()

    if args.test_grid:
        points = build_test_grid_samples()
    else:
        points = iter_grid_points(args.center_lat, args.center_lon, args.radius, args.step)
    fc = build_feature_collection(points)
    ensure_dir(args.output)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(fc, f)
    print(f"Wrote {len(points)} grid samples to {args.output}")


if __name__ == "__main__":
    main()
