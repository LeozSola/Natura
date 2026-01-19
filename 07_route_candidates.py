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

ROAD_CLASS_WEIGHTS = {
    "motorway": 0.55,
    "trunk": 0.65,
    "primary": 0.75,
    "secondary": 0.85,
    "tertiary": 0.95,
    "unclassified": 0.9,
    "residential": 0.75,
    "living_street": 0.7,
    "service": 0.65,
    "track": 1.05,
}
DEFAULT_ROAD_WEIGHT = 1.0

def build_osrm_url(
    base_endpoint: str,
    coords: List[Tuple[float, float]],   # [(lat, lon), ...]
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

    # Append lon,lat;lon,lat...
    coord_str = ";".join([f"{lon},{lat}" for lat, lon in coords])
    path = f"{path}/{coord_str}"

    # Merge existing query with extra params
    q = dict(parse_qsl(p.query))
    q.update(extra_params)

    return urlunparse(p._replace(path=path, query=urlencode(q)))


def query_osrm(
    coords: List[Tuple[float, float]],
    endpoint: str,
    extra_params: Optional[Dict[str, str]] = None,
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
    if extra_params:
        defaults.update(extra_params)
    url = build_osrm_url(endpoint, coords, profile="driving", extra_params=defaults)
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

def densify_linestring(coords: List[List[float]], step: float) -> List[Tuple[float, float]]:
    """Generate points along a LineString at a fixed interval."""
    if not coords:
        return []
    points = []
    prev_lon, prev_lat = coords[0]
    points.append((prev_lat, prev_lon))
    for i in range(1, len(coords)):
        curr_lon, curr_lat = coords[i]
        segment_len = haversine_distance(prev_lat, prev_lon, curr_lat, curr_lon)
        if segment_len <= 0:
            prev_lon, prev_lat = curr_lon, curr_lat
            continue
        distance_covered = 0.0
        while distance_covered + step < segment_len:
            fraction = (distance_covered + step) / segment_len
            lat, lon = interpolate_point(prev_lat, prev_lon, curr_lat, curr_lon, fraction)
            points.append((lat, lon))
            distance_covered += step
        points.append((curr_lat, curr_lon))
        prev_lon, prev_lat = curr_lon, curr_lat
    return points


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


def load_roads(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("features", [])


def normalize_highway_tag(tag: Optional[str]) -> Optional[str]:
    if not tag:
        return None
    if "_" in tag:
        base = tag.split("_")[0]
        if base in ROAD_CLASS_WEIGHTS:
            return base
    return tag


def build_road_anchors(
    road_features: List[Dict],
    step_m: float,
) -> List[Tuple[float, float, float, str]]:
    anchors: List[Tuple[float, float, float, str]] = []
    for feat in road_features:
        props = feat.get("properties", {}) or {}
        tags = props.get("tags", {}) or {}
        highway_raw = tags.get("highway")
        highway = normalize_highway_tag(highway_raw)
        if not highway:
            continue
        weight = ROAD_CLASS_WEIGHTS.get(highway, DEFAULT_ROAD_WEIGHT)
        coords = feat.get("geometry", {}).get("coordinates", [])
        if not coords:
            continue
        points = densify_linestring(coords, step_m) if step_m and step_m > 0 else [(coords[0][1], coords[0][0])]
        for lat, lon in points:
            anchors.append((lat, lon, weight, highway))
    return anchors


def build_dead_end_nodes(road_features: List[Dict]) -> List[Tuple[float, float]]:
    endpoint_counts: Dict[Tuple[float, float], int] = {}
    for feat in road_features:
        coords = feat.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue
        start_lon, start_lat = coords[0]
        end_lon, end_lat = coords[-1]
        start_key = (round(start_lat, 6), round(start_lon, 6))
        end_key = (round(end_lat, 6), round(end_lon, 6))
        endpoint_counts[start_key] = endpoint_counts.get(start_key, 0) + 1
        endpoint_counts[end_key] = endpoint_counts.get(end_key, 0) + 1

    dead_ends = [(lat, lon) for (lat, lon), count in endpoint_counts.items() if count == 1]
    return dead_ends


def build_grid_index(points: List[Tuple], cell_deg: float) -> Dict[Tuple[int, int], List[Tuple]]:
    grid: Dict[Tuple[int, int], List[Tuple]] = {}
    for pt in points:
        lat = pt[0]
        lon = pt[1]
        key = (math.floor(lat / cell_deg), math.floor(lon / cell_deg))
        grid.setdefault(key, []).append(pt)
    return grid


def iter_neighbor_cells(lat: float, lon: float, cell_deg: float, radius_cells: int) -> List[Tuple[int, int]]:
    base_row = math.floor(lat / cell_deg)
    base_col = math.floor(lon / cell_deg)
    cells = []
    for dy in range(-radius_cells, radius_cells + 1):
        for dx in range(-radius_cells, radius_cells + 1):
            cells.append((base_row + dy, base_col + dx))
    return cells


def cell_radius_for_distance(cell_deg: float, max_distance_m: Optional[float]) -> int:
    if max_distance_m is None:
        return 2
    cell_m = max(cell_deg * 111000.0, 1.0)
    return max(1, int(math.ceil(max_distance_m / cell_m)))


def nearest_index_point(
    lat: float,
    lon: float,
    grid: Dict[Tuple[int, int], List[Tuple]],
    cell_deg: float,
    max_distance_m: Optional[float] = None,
) -> Optional[Tuple[Tuple, float]]:
    best = None
    best_dist = float("inf")
    radius_cells = cell_radius_for_distance(cell_deg, max_distance_m)
    for cell in iter_neighbor_cells(lat, lon, cell_deg, radius_cells):
        for pt in grid.get(cell, []):
            d = haversine_distance(lat, lon, pt[0], pt[1])
            if d < best_dist:
                best = pt
                best_dist = d
    if best is None:
        return None
    if max_distance_m is not None and best_dist > max_distance_m:
        return None
    return best, best_dist


def apply_road_weighting(
    heatmap_points: List[Tuple[float, float, float]],
    anchors: List[Tuple[float, float, float, str]],
    max_distance_m: Optional[float],
    cell_deg: float,
) -> List[Tuple[float, float, float]]:
    if not anchors:
        return heatmap_points
    grid = build_grid_index(anchors, cell_deg)
    weighted = []
    used = 0
    weights: List[float] = []
    for lat, lon, score in heatmap_points:
        nearest = nearest_index_point(lat, lon, grid, cell_deg, max_distance_m)
        if nearest is None:
            weighted.append((lat, lon, score))
            continue
        anchor, _dist = nearest
        weight = anchor[2]
        used += 1
        weights.append(weight)
        weighted.append((lat, lon, score * weight))
    if weights:
        avg_weight = sum(weights) / len(weights)
        print(f"Applied road class weighting to {used}/{len(heatmap_points)} points (avg weight {avg_weight:.2f}).")
    return weighted


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


def select_waypoints(
    candidates: List[Tuple[float, float, float]],
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    count: int,
    radius_m: float,
    min_distance_m: float,
    min_separation_m: float,
    dead_end_grid: Optional[Dict[Tuple[int, int], List[Tuple[float, float]]]] = None,
    dead_end_cell_deg: float = 0.002,
    dead_end_radius_m: float = 0.0,
) -> List[Tuple[float, float, float]]:
    if count <= 0:
        return []
    mid_lat = (origin[0] + dest[0]) / 2.0
    mid_lon = (origin[1] + dest[1]) / 2.0

    filtered = []
    for lat, lon, score in candidates:
        if haversine_distance(lat, lon, mid_lat, mid_lon) > radius_m:
            continue
        if haversine_distance(lat, lon, origin[0], origin[1]) < min_distance_m:
            continue
        if haversine_distance(lat, lon, dest[0], dest[1]) < min_distance_m:
            continue
        if dead_end_grid and dead_end_radius_m and dead_end_radius_m > 0:
            nearest_dead = nearest_index_point(
                lat,
                lon,
                dead_end_grid,
                dead_end_cell_deg,
                max_distance_m=dead_end_radius_m,
            )
            if nearest_dead is not None:
                continue
        filtered.append((lat, lon, score))

    filtered.sort(key=lambda x: x[2], reverse=True)
    chosen: List[Tuple[float, float, float]] = []
    for lat, lon, score in filtered:
        if len(chosen) >= count:
            break
        if all(haversine_distance(lat, lon, c_lat, c_lon) >= min_separation_m for c_lat, c_lon, _ in chosen):
            chosen.append((lat, lon, score))
    return chosen


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
        "--roads",
        type=str,
        default="",
        help="Optional OSM roads GeoJSON to apply road class weighting and dead-end filtering",
    )
    parser.add_argument(
        "--road-sample-step",
        type=float,
        default=300.0,
        help="Spacing (m) when sampling road anchors for class weighting (default: 300)",
    )
    parser.add_argument(
        "--road-max-distance",
        type=float,
        default=800.0,
        help="Max distance (m) to match heatmap points to road anchors (default: 800)",
    )
    parser.add_argument(
        "--dead-end-radius",
        type=float,
        default=80.0,
        help="Radius (m) around dead-end nodes to exclude waypoint candidates (default: 80)",
    )
    parser.add_argument(
        "--no-road-weighting",
        action="store_true",
        help="Disable road class weighting even if roads are provided",
    )
    parser.add_argument(
        "--no-dead-end-filter",
        action="store_true",
        help="Disable dead-end filtering for waypoint candidates",
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
        "--scenic-weight",
        type=float,
        default=0.7,
        help="Weight for scenic score vs travel time (0-1, default: 0.7)",
    )
    parser.add_argument(
        "--max-duration-ratio",
        type=float,
        default=1.7,
        help="Max allowed duration ratio vs shortest route (default: 1.7)",
    )
    parser.add_argument(
        "--waypoint-count",
        type=int,
        default=6,
        help="Number of scenic waypoint routes to try (default: 6)",
    )
    parser.add_argument(
        "--waypoint-radius",
        type=float,
        default=8000.0,
        help="Search radius (m) around midpoint for waypoint selection (default: 8000)",
    )
    parser.add_argument(
        "--waypoint-min-distance",
        type=float,
        default=2000.0,
        help="Minimum distance (m) from origin/dest for a waypoint (default: 2000)",
    )
    parser.add_argument(
        "--waypoint-min-separation",
        type=float,
        default=1500.0,
        help="Minimum separation (m) between waypoints (default: 1500)",
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

    scenic_weight = min(1.0, max(0.0, args.scenic_weight))

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

    road_weighting_applied = False
    dead_end_grid = None
    dead_end_cell_deg = 0.002
    if args.roads:
        roads_path = Path(args.roads)
        if roads_path.exists():
            road_features = load_roads(str(roads_path))
            if road_features:
                if not args.no_road_weighting and scenic_source == "heatmap":
                    anchors = build_road_anchors(road_features, args.road_sample_step)
                    if anchors:
                        scoring_candidates = apply_road_weighting(
                            scoring_candidates,
                            anchors,
                            args.road_max_distance if args.road_max_distance > 0 else None,
                            cell_deg=0.01,
                        )
                        road_weighting_applied = True
                if not args.no_dead_end_filter:
                    dead_ends = build_dead_end_nodes(road_features)
                    if dead_ends:
                        dead_end_grid = build_grid_index(dead_ends, dead_end_cell_deg)
                        print(f"Dead-end filter enabled ({len(dead_ends)} dead-end nodes).")
            else:
                print(f"Roads file {args.roads} contained no features; skipping road weighting.")
        else:
            print(f"Roads file {args.roads} not found; skipping road weighting.")

    # Query OSRM for route alternatives
    cache: Optional[DiskCache] = None
    if not args.no_cache:
        ttl = args.cache_ttl if args.cache_ttl > 0 else None
        cache = DiskCache(Path(args.cache_dir), namespace="osrm", max_age=ttl)

    try:
        def _request(coords: List[Tuple[float, float]], extra: Optional[Dict[str, str]] = None) -> dict:
            return query_osrm(coords, args.endpoint, extra_params=extra)

        base_coords = [origin, dest]
        if cache:
            request_key = DiskCache.key_from_mapping(
                {
                    "coords": [(round(lat, 6), round(lon, 6)) for lat, lon in base_coords],
                    "endpoint": args.endpoint,
                    "alternatives": "true",
                }
            )
            routes_data = cache.get_or_create(request_key, lambda: _request(base_coords))
        else:
            routes_data = _request(base_coords)
    except Exception as exc:
        raise SystemExit(f"Failed to query OSRM: {exc}")

    routes = routes_data.get("routes", [])
    if not routes:
        raise SystemExit("OSRM returned no routes.")

    durations = [r.get("duration") for r in routes if r.get("duration") is not None]
    shortest_duration = min(durations) if durations else None

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
            "scenic_weight": scenic_weight,
            "road_weighting": road_weighting_applied,
            "route_variant": "osrm_alternative",
        }
        if shortest_duration and props.get("duration") is not None:
            props["duration_ratio"] = props["duration"] / shortest_duration
        else:
            props["duration_ratio"] = None
        props["max_duration_ratio"] = args.max_duration_ratio
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,  # already GeoJSON from OSRM (geometries=geojson)
                "properties": props,
            }
        )

    if args.waypoint_count > 0 and scoring_candidates:
        waypoint_candidates = select_waypoints(
            scoring_candidates,
            origin,
            dest,
            count=args.waypoint_count,
            radius_m=args.waypoint_radius,
            min_distance_m=args.waypoint_min_distance,
            min_separation_m=args.waypoint_min_separation,
            dead_end_grid=dead_end_grid,
            dead_end_cell_deg=dead_end_cell_deg,
            dead_end_radius_m=args.dead_end_radius,
        )
        for idx, (w_lat, w_lon, w_score) in enumerate(waypoint_candidates, start=1):
            waypoint_coords = [origin, (w_lat, w_lon), dest]
            try:
                if cache:
                    request_key = DiskCache.key_from_mapping(
                        {
                            "coords": [(round(lat, 6), round(lon, 6)) for lat, lon in waypoint_coords],
                            "endpoint": args.endpoint,
                            "alternatives": "false",
                        }
                    )
                    waypoint_data = cache.get_or_create(request_key, lambda: _request(waypoint_coords, {"alternatives": "false"}))
                else:
                    waypoint_data = _request(waypoint_coords, {"alternatives": "false"})
            except Exception:
                continue

            wp_routes = waypoint_data.get("routes", []) or []
            for route in wp_routes:
                geometry = route.get("geometry", {})
                coords = geometry.get("coordinates", [])
                if not coords:
                    continue
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
                    "route_index": f"waypoint_{idx}",
                    "duration": route.get("duration"),
                    "distance": route.get("distance"),
                    "scenic_score": mean_score,
                    "scenic_effective_score": effective_score,
                    "scenic_source": scenic_source,
                    "scenic_coverage": coverage or 0.0,
                    "scenic_sampled_points": (scenic_stats or {}).get("sampled_points", 0),
                    "scenic_total_samples": len(samples),
                    "scenic_avg_lookup_distance": (scenic_stats or {}).get("avg_lookup_distance"),
                    "scenic_weight": scenic_weight,
                    "route_variant": "waypoint",
                    "waypoint_lat": w_lat,
                    "waypoint_lon": w_lon,
                    "waypoint_score": w_score,
                }
                if shortest_duration and props.get("duration") is not None:
                    props["duration_ratio"] = props["duration"] / shortest_duration
                else:
                    props["duration_ratio"] = None
                props["max_duration_ratio"] = args.max_duration_ratio

                features.append(
                    {
                        "type": "Feature",
                        "geometry": geometry,
                        "properties": props,
                    }
                )

    scored_routes = [
        feat for feat in features if feat.get("properties", {}).get("scenic_effective_score") is not None
    ]
    scenic_values = [f["properties"]["scenic_effective_score"] for f in scored_routes]
    duration_values = [f["properties"]["duration"] for f in scored_routes if f["properties"].get("duration") is not None]
    scenic_min = min(scenic_values) if scenic_values else None
    scenic_max = max(scenic_values) if scenic_values else None
    duration_min = min(duration_values) if duration_values else None
    duration_max = max(duration_values) if duration_values else None

    def _norm(value: Optional[float], min_val: Optional[float], max_val: Optional[float]) -> Optional[float]:
        if value is None or min_val is None or max_val is None:
            return None
        if max_val <= min_val:
            return 1.0
        return (value - min_val) / (max_val - min_val)

    for feat in scored_routes:
        props = feat["properties"]
        scenic_norm = _norm(props.get("scenic_effective_score"), scenic_min, scenic_max)
        duration_norm = _norm(props.get("duration"), duration_min, duration_max)
        combined = None
        if scenic_norm is not None and duration_norm is not None:
            combined = scenic_weight * scenic_norm + (1.0 - scenic_weight) * (1.0 - duration_norm)
        props["scenic_norm"] = scenic_norm
        props["duration_norm"] = duration_norm
        props["combined_score"] = combined

    scored_routes = [feat for feat in scored_routes if feat["properties"].get("combined_score") is not None]

    ranked_routes = scored_routes
    ratio_limit = args.max_duration_ratio if args.max_duration_ratio and args.max_duration_ratio > 0 else None
    if ratio_limit and shortest_duration:
        eligible = [
            feat for feat in scored_routes
            if (feat["properties"].get("duration_ratio") is not None and feat["properties"]["duration_ratio"] <= ratio_limit)
        ]
        if eligible:
            ranked_routes = eligible

    ranked_routes.sort(key=lambda f: f["properties"]["combined_score"], reverse=True)
    for rank, feat in enumerate(ranked_routes, start=1):
        feat["properties"]["scenic_rank"] = rank
    for feat in features:
        feat["properties"].setdefault("scenic_rank", None)
        feat["properties"]["is_most_scenic"] = feat["properties"]["scenic_rank"] == 1

    if ranked_routes:
        best = ranked_routes[0]["properties"]
        print(
            f"Most scenic route: index {best['route_index']} "
            f"(score {best['scenic_score']:.3f}, effective {best['scenic_effective_score']:.3f}, "
            f"combined {best['combined_score']:.3f}, coverage {best['scenic_coverage']:.0%}) "
            f"via {best.get('scenic_source')} weight={scenic_weight:.2f} max_ratio={args.max_duration_ratio:.2f}"
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
