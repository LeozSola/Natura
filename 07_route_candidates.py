"""
Script: 07_route_candidates.py
==============================

This module requests alternative driving routes between two points using the
Open Source Routing Machine (OSRM) API and scores each route for
scenicness based on previously computed road segment scores.  It
provides a simple example of multi‑objective routing where travel time
and scenic value can be compared.

Usage
-----

    python 07_route_candidates.py \
        --origin-lat 42.539 --origin-lon -71.048 \
        --dest-lat 42.491 --dest-lon -71.063 \
        --edge-scores data/geojson/edges_scored.geojson \
        --output data/geojson/routes.geojson

Parameters
----------
--origin-lat, --origin-lon:
    Coordinates of the starting point.
--dest-lat, --dest-lon:
    Coordinates of the destination point.
--edge-scores:
    GeoJSON of road segments with ``scenic_score`` properties (produced
    by ``06_edge_scores.py``).
--endpoint:
    OSRM API endpoint.  Default is the public demo server
    (``https://router.project-osrm.org``), which does not guarantee
    availability or performance.  For production use, run your own
    server.
--step:
    Sampling interval in metres for computing route scenicness.  Default
    is 100 m.
--output:
    Path to write the routes as a GeoJSON FeatureCollection.  Each
    route feature includes the OSRM properties (duration, distance)
    plus ``scenic_score`` (mean scenicness along the route).

Notes
-----
This script relies on OSRM and will not function without internet
connectivity or a local OSRM instance.  It also uses a naive nearest
neighbour search to match route sample points to road segments; this
works for small test areas but does not scale to large networks.  In a
real system you would use a spatial index (e.g. an R‑tree) for
efficiency.
"""

import argparse
import json
import os
import requests
import math
from typing import List, Tuple, Dict, Optional


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def interpolate_point(lat1: float, lon1: float, lat2: float, lon2: float, fraction: float) -> Tuple[float, float]:
    lat = lat1 + (lat2 - lat1) * fraction
    lon = lon1 + (lon2 - lon1) * fraction
    return lat, lon


def densify_route(coords: List[List[float]], step: float) -> List[Tuple[float, float]]:
    """Generate points along a polyline at a fixed interval.

    Input coords are [[lon, lat], ...] in GeoJSON order.  Step is in
    metres.
    """
    samples = []
    if len(coords) < 2:
        return samples
    leftover = 0.0
    prev_lon, prev_lat = coords[0]
    for i in range(1, len(coords)):
        curr_lon, curr_lat = coords[i]
        segment_len = haversine_distance(prev_lat, prev_lon, curr_lat, curr_lon)
        # accumulate leftover from previous segment
        distance_covered = leftover
        while distance_covered + step <= segment_len:
            fraction = (distance_covered + step) / segment_len
            lat, lon = interpolate_point(prev_lat, prev_lon, curr_lat, curr_lon, fraction)
            samples.append((lat, lon))
            distance_covered += step
        leftover = segment_len - distance_covered
        prev_lon, prev_lat = curr_lon, curr_lat
    return samples


def load_edge_scores(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    features = data.get("features", [])
    return features


def build_road_midpoints(edge_features: List[Dict]) -> List[Tuple[float, float, float]]:
    """Create a list of road midpoints with scenic scores.

    Each tuple contains (lat, lon, scenic_score).  If scenic_score is
    None, the road is ignored.
    """
    midpoints = []
    for feat in edge_features:
        props = feat.get("properties", {})
        score = props.get("scenic_score")
        if score is None:
            continue
        coords = feat.get("geometry", {}).get("coordinates", [])
        if not coords:
            continue
        # Compute midpoint of the polyline by taking the middle coordinate
        mid_idx = len(coords) // 2
        lon, lat = coords[mid_idx]
        midpoints.append((lat, lon, score))
    return midpoints


def nearest_score(lat: float, lon: float, midpoints: List[Tuple[float, float, float]]) -> Optional[float]:
    """Find the scenic score of the closest road midpoint to the given point."""
    min_dist = float("inf")
    min_score = None
    for mlat, mlon, score in midpoints:
        d = haversine_distance(lat, lon, mlat, mlon)
        if d < min_dist:
            min_dist = d
            min_score = score
    return min_score


def compute_route_scenic(samples: List[Tuple[float, float]], midpoints: List[Tuple[float, float, float]]) -> Optional[float]:
    """Compute the mean scenic score along a sampled route."""
    scores = []
    for lat, lon in samples:
        score = nearest_score(lat, lon, midpoints)
        if score is not None:
            scores.append(score)
    if not scores:
        return None
    return sum(scores) / len(scores)


def query_osrm(origin: Tuple[float, float], dest: Tuple[float, float], endpoint: str) -> dict:
    """Request route alternatives from OSRM."""
    base_url = endpoint.rstrip("/") + "/route/v1/driving/"
    coords = f"{origin[1]},{origin[0]};{dest[1]},{dest[0]}"
    params = {
        "alternatives": "true",
        "overview": "full",
        "geometries": "geojson",
    }
    url = base_url + coords
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def ensure_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Request OSRM routes and score their scenicness")
    parser.add_argument("--origin-lat", type=float, required=True)
    parser.add_argument("--origin-lon", type=float, required=True)
    parser.add_argument("--dest-lat", type=float, required=True)
    parser.add_argument("--dest-lon", type=float, required=True)
    parser.add_argument(
        "--edge-scores",
        type=str,
        required=True,
        help="GeoJSON file with scenic_score for each road segment",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default="https://router.project-osrm.org",
        help="Base URL of OSRM server",
    )
    parser.add_argument(
        "--step",
        type=float,
        default=100.0,
        help="Sampling interval in metres for scoring routes (default: 100)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/geojson/routes.geojson",
        help="Output GeoJSON file to write routes with scenic scores",
    )
    args = parser.parse_args()

    # Load edge scores and prepare road midpoints for nearest neighbour lookup
    edge_features = load_edge_scores(args.edge_scores)
    midpoints = build_road_midpoints(edge_features)
    if not midpoints:
        raise SystemExit("No road midpoints with scenic scores found. Ensure step 6 ran correctly.")
    # Query OSRM for routes
    try:
        routes_data = query_osrm((args.origin_lat, args.origin_lon), (args.dest_lat, args.dest_lon), args.endpoint)
    except Exception as exc:
        raise SystemExit(f"Failed to query OSRM: {exc}")
    routes = routes_data.get("routes", [])
    features = []
    for i, route in enumerate(routes):
        geometry = route.get("geometry", {})
        coords = geometry.get("coordinates", [])
        # Sample along route
        samples = densify_route(coords, args.step)
        scenic = compute_route_scenic(samples, midpoints)
        props = {
            "route_index": i,
            "duration": route.get("duration"),
            "distance": route.get("distance"),
            "scenic_score": scenic,
        }
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": props,
            }
        )
    # Write output
    out = {"type": "FeatureCollection", "features": features}
    ensure_dir(args.output)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(f"Wrote {len(features)} routes with scenic scores to {args.output}")


if __name__ == "__main__":
    main()