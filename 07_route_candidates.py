"""
Script: 07_route_candidates.py
==============================

This module requests alternative driving routes between two points using the
Open Source Routing Machine (OSRM) API and scores each route for
scenicness based on a scenic heatmap (or optional edge scores). It
provides a simple example of multi-objective routing where travel time
and scenic value can be compared.

Usage
-----

    python 07_route_candidates.py --origin-lat 42.539 --origin-lon -71.048 --dest-lat 42.491 --dest-lon -71.063 --heatmap data/geojson/scenic_grid_heatmap.geojson --output data/geojson/routes.geojson

Parameters
----------
--origin-lat, --origin-lon:
    Coordinates of the starting point.
--dest-lat, --dest-lon:
    Coordinates of the destination point.
--edge-scores:
    Optional GeoJSON of road segments with ``scenic_score`` properties
    (produced by ``06_edge_scores.py``). Used only as a fallback if the
    heatmap is missing or empty.
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
connectivity or a local OSRM instance. It also uses a naive nearest
neighbour search to match route sample points to scenic points; this
works for small test areas but does not scale to large networks. In a
real system you would use a spatial index (e.g. an R-tree) for
efficiency.
"""

import argparse
import json
import os
import requests
import math
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from natura.cache import DiskCache
from natura.heatmap import load_heatmap

def build_osrm_url(
    base_endpoint: str,
    origin: Tuple[float, float],   # (lat, lon)
    dest: Tuple[float, float],     # (lat, lon)
    profile: str = "driving",
    extra_params: Optional[Dict[str, str]] = None,
) -> str:
    """
    Merge any existing query string in base_endpoint with extra_params,
    ensure the route path is present, and append coordinates.
    """
    extra_params = extra_params or {}

    p = urlparse(base_endpoint)

    # Ensure path includes /route/v1/{profile}
    path = p.path.rstrip("/")
    needed = f"/route/v1/{profile}"
    if needed not in path:
        path = path + needed

    # Append lon,lat;lon,lat
    o_lat, o_lon = origin
    d_lat, d_lon = dest
    path = f"{path}/{o_lon},{o_lat};{d_lon},{d_lat}"

    # Merge existing query with extra params
    q = dict(parse_qsl(p.query))
    q.update(extra_params)

    return urlunparse(p._replace(path=path, query=urlencode(q)))


def query_osrm(
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    endpoint: str,
) -> dict:
    """
    Request route alternatives from OSRM, preserving any query on `endpoint`
    (e.g., ?exclude=motorway) and adding the usual params.
    """
    defaults = {
        "alternatives": "true",
        "overview": "full",
        "geometries": "geojson",
    }
    url = build_osrm_url(endpoint, origin, dest, profile="driving", extra_params=defaults)
    resp = requests.get(url, timeout=30)  # params already baked into URL
    resp.raise_for_status()
    return resp.json()

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


def nearest_score(
    lat: float,
    lon: float,
    candidates: List[Tuple[float, float, float]],
    max_distance: Optional[float] = None,
) -> Optional[Tuple[float, float]]:
    """Find the scenic score (and distance) of the closest candidate."""
    min_dist = float("inf")
    min_score = None
    for c_lat, c_lon, score in candidates:
        d = haversine_distance(lat, lon, c_lat, c_lon)
        if d < min_dist:
            min_dist = d
            min_score = score
    if min_score is None:
        return None
    if max_distance is not None and min_dist > max_distance:
        return None
    return min_score, min_dist


def compute_route_scenic(
    samples: List[Tuple[float, float]],
    candidates: List[Tuple[float, float, float]],
    max_distance: Optional[float] = None,
) -> Optional[Dict[str, float]]:
    """Compute scenic statistics along a sampled route from heatmap points."""
    if not samples:
        return None

    matched_scores: List[float] = []
    lookup_distances: List[float] = []
    for lat, lon in samples:
        result = nearest_score(lat, lon, candidates, max_distance=max_distance)
        if result is None:
            continue
        score, distance = result
        matched_scores.append(score)
        lookup_distances.append(distance)

    if not matched_scores:
        return None

    mean_score = sum(matched_scores) / len(matched_scores)
    coverage = len(matched_scores) / len(samples)
    avg_lookup = sum(lookup_distances) / len(lookup_distances) if lookup_distances else None
    return {
        "mean": mean_score,
        "coverage": coverage,
        "sampled_points": len(matched_scores),
        "total_samples": len(samples),
        "avg_lookup_distance": avg_lookup,
    }


def ensure_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score OSRM route alternatives using scenic edge scores")
    parser.add_argument("--origin-lat", type=float, required=True, help="Origin latitude")
    parser.add_argument("--origin-lon", type=float, required=True, help="Origin longitude")
    parser.add_argument("--dest-lat",   type=float, required=True, help="Destination latitude")
    parser.add_argument("--dest-lon",   type=float, required=True, help="Destination longitude")
    parser.add_argument(
        "--edge-scores",
        type=str,
        required=False,
        help="GeoJSON of road edges with per-edge scenic_score (from step 6)",
    )
    parser.add_argument(
        "--heatmap",
        type=str,
        default="data/geojson/scenic_heatmap.geojson",
        help="GeoJSON of scenic heatmap points (from step 6)",
    )
    parser.add_argument(
        "--max-heatmap-distance",
        type=float,
        default=250.0,
        help="Maximum distance (m) to accept a heatmap point when scoring routes",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default="https://router.project-osrm.org/route/v1/driving",
        help="OSRM base endpoint; you may include query, e.g. '?exclude=motorway'",
    )
    parser.add_argument(
        "--step",
        type=float,
        default=120.0,
        help="Sampling step (meters) along the route polyline when computing scenic mean (default: 120)",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output routes GeoJSON path",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default="data/cache",
        help="Directory for cached OSRM responses",
    )
    parser.add_argument(
        "--cache-ttl",
        type=float,
        default=7 * 24 * 3600,
        help="Cache expiry in seconds (default: 7 days). Set to 0 for no expiry.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable caching OSRM route responses",
    )
    args = parser.parse_args()

    origin = (args.origin_lat, args.origin_lon)
    dest   = (args.dest_lat,   args.dest_lon)

    # Prefer the densified heatmap for scenic lookups, fall back to road midpoints.
    scoring_candidates: List[Tuple[float, float, float]] = []
    scenic_source = None
    heatmap_points: List[Tuple[float, float, float]] = []

    if args.heatmap:
        heatmap_path = Path(args.heatmap)
        if heatmap_path.exists():
            heatmap_points = load_heatmap(heatmap_path)
            if heatmap_points:
                scoring_candidates = heatmap_points
                scenic_source = "heatmap"
            else:
                print(f"Heatmap file {args.heatmap} contained no scenic points; falling back to edge midpoints.")
        else:
            print(f"Heatmap file {args.heatmap} not found; falling back to edge midpoints.")

    if not scoring_candidates:
        if not args.edge_scores:
            raise SystemExit("No scenic data available. Provide --heatmap or --edge-scores.")
        edge_features = load_edge_scores(args.edge_scores)
        scoring_candidates = build_road_midpoints(edge_features)
        scenic_source = "edge_midpoints"
        if not scoring_candidates:
            raise SystemExit("No scenic data available. Ensure step 6 generated edge scores or a heatmap.")

    # Query OSRM for route alternatives
    cache: Optional[DiskCache] = None
    if not args.no_cache:
        ttl = args.cache_ttl if args.cache_ttl > 0 else None
        cache = DiskCache(Path(args.cache_dir), namespace="osrm", max_age=ttl)

    try:
        def _request() -> dict:
            return query_osrm(origin, dest, args.endpoint)

        if cache:
            request_key = DiskCache.key_from_mapping(
                {
                    "origin": (round(origin[0], 6), round(origin[1], 6)),
                    "dest": (round(dest[0], 6), round(dest[1], 6)),
                    "endpoint": args.endpoint,
                }
            )
            routes_data = cache.get_or_create(request_key, _request)
        else:
            routes_data = _request()
    except Exception as exc:
        raise SystemExit(f"Failed to query OSRM: {exc}")

    routes = routes_data.get("routes", [])
    if not routes:
        raise SystemExit("OSRM returned no routes.")

    features = []
    for i, route in enumerate(routes):
        geometry = route.get("geometry", {})
        coords = geometry.get("coordinates", [])
        if not coords:
            continue

        # Sample along route and compute scenic mean
        samples = densify_route(coords, args.step)
        max_dist = None
        if scenic_source == "heatmap" and args.max_heatmap_distance > 0:
            max_dist = args.max_heatmap_distance
        scenic_stats = compute_route_scenic(samples, scoring_candidates, max_distance=max_dist)
        mean_score = (scenic_stats or {}).get("mean")
        coverage = (scenic_stats or {}).get("coverage")
        effective_score = None
        if mean_score is not None and coverage is not None:
            effective_score = mean_score * coverage

        props = {
            "route_index": i,
            "duration": route.get("duration"),
            "distance": route.get("distance"),
            "scenic_score": mean_score,
            "scenic_effective_score": effective_score,
            "scenic_source": scenic_source,
            "scenic_coverage": coverage or 0.0,
            "scenic_sampled_points": (scenic_stats or {}).get("sampled_points", 0),
            "scenic_total_samples": len(samples),
            "scenic_avg_lookup_distance": (scenic_stats or {}).get("avg_lookup_distance"),
        }
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,  # already GeoJSON from OSRM (geometries=geojson)
                "properties": props,
            }
        )

    scored_routes = [
        feat for feat in features if feat.get("properties", {}).get("scenic_effective_score") is not None
    ]
    scored_routes.sort(key=lambda f: f["properties"]["scenic_effective_score"], reverse=True)
    for rank, feat in enumerate(scored_routes, start=1):
        feat["properties"]["scenic_rank"] = rank
    for feat in features:
        feat["properties"].setdefault("scenic_rank", None)
        feat["properties"]["is_most_scenic"] = feat["properties"]["scenic_rank"] == 1

    if scored_routes:
        best = scored_routes[0]["properties"]
        print(
            f"Most scenic route: index {best['route_index']} "
            f"(score {best['scenic_score']:.3f}, effective {best['scenic_effective_score']:.3f}, "
            f"coverage {best['scenic_coverage']:.0%}) "
            f"via {best.get('scenic_source')}"
        )
    else:
        print("No scenic scores could be computed for the retrieved routes.")

    # Write output
    out = {"type": "FeatureCollection", "features": features}
    ensure_dir(args.output)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(f"Wrote {len(features)} routes with scenic scores to {args.output}")

if __name__ == "__main__":
    main()
