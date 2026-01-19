"""
Script: 10_route_validation.py
==============================

Validate scenic routing by comparing the most scenic alternative against
the shortest alternative for a set of origin/destination pairs.
"""

import argparse
import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from natura.cache import DiskCache
from natura.heatmap import load_heatmap

import importlib.util


def load_route_utils() -> object:
    path = Path("07_route_candidates.py")
    spec = importlib.util.spec_from_file_location("route_utils", path)
    if spec is None or spec.loader is None:
        raise SystemExit("Failed to load 07_route_candidates.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def load_pairs(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def parse_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def choose_heatmap(path: Path, fallback: Path) -> Path:
    if path.exists():
        return path
    return fallback


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate scenic route selection across multiple OD pairs")
    parser.add_argument(
        "--pairs",
        type=str,
        default="data/validation/route_pairs.csv",
        help="CSV of origin/destination pairs",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="mapillary",
        help="Data source to validate (mapillary|google)",
    )
    parser.add_argument(
        "--heatmap",
        type=str,
        default="",
        help="Scenic heatmap GeoJSON path (optional override)",
    )
    parser.add_argument(
        "--fallback-heatmap",
        type=str,
        default="",
        help="Fallback heatmap path if grid heatmap missing",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default="https://router.project-osrm.org/route/v1/driving",
        help="OSRM endpoint",
    )
    parser.add_argument(
        "--step",
        type=float,
        default=120.0,
        help="Sampling step (meters) along the route polyline",
    )
    parser.add_argument(
        "--max-heatmap-distance",
        type=float,
        default=250.0,
        help="Maximum distance (m) to accept a heatmap point when scoring routes",
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
    parser.add_argument(
        "--output",
        type=str,
        default="outputs/route_validation.csv",
        help="Output CSV path for validation results",
    )
    args = parser.parse_args()

    pairs_path = Path(args.pairs)
    default_heatmap = Path(f"data/{args.source}/geojson/scenic_grid_heatmap.geojson")
    heatmap_path = choose_heatmap(Path(args.heatmap) if args.heatmap else default_heatmap, Path(args.fallback_heatmap) if args.fallback_heatmap else default_heatmap)
    if not heatmap_path.exists():
        fallback = Path(f"data/{args.source}/geojson/scenic_heatmap.geojson")
        if fallback.exists():
            heatmap_path = fallback
        else:
            legacy = Path("data/geojson/scenic_heatmap.geojson")
            if legacy.exists():
                heatmap_path = legacy
    if not heatmap_path.exists():
        raise SystemExit("No heatmap available. Run run_prepare_grid.ps1 first.")

    pairs = load_pairs(pairs_path)
    if not pairs:
        raise SystemExit("No pairs found in CSV.")

    heatmap_points = load_heatmap(heatmap_path)
    if not heatmap_points:
        raise SystemExit("Heatmap contains no points.")

    route_utils = load_route_utils()

    cache: Optional[DiskCache] = None
    if not args.no_cache:
        ttl = args.cache_ttl if args.cache_ttl > 0 else None
        cache = DiskCache(Path(args.cache_dir), namespace="osrm_validation", max_age=ttl)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "pair_id",
        "origin_lat",
        "origin_lon",
        "dest_lat",
        "dest_lon",
        "route_count",
        "scenic_best_index",
        "scenic_best_score",
        "scenic_best_effective_score",
        "scenic_best_coverage",
        "scenic_best_distance_m",
        "shortest_index",
        "shortest_distance_m",
        "shortest_duration_s",
        "shortest_scenic_score",
        "shortest_effective_score",
        "distance_delta_m",
    ]

    scenic_matches = 0

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in pairs:
            pair_id = row.get("pair_id") or "pair"
            o_lat = parse_float(row.get("origin_lat"))
            o_lon = parse_float(row.get("origin_lon"))
            d_lat = parse_float(row.get("dest_lat"))
            d_lon = parse_float(row.get("dest_lon"))
            if None in (o_lat, o_lon, d_lat, d_lon):
                continue

            origin = (float(o_lat), float(o_lon))
            dest = (float(d_lat), float(d_lon))

            def _request() -> Dict:
                return route_utils.query_osrm(origin, dest, args.endpoint)

            if cache:
                key = DiskCache.key_from_mapping(
                    {
                        "origin": (round(origin[0], 6), round(origin[1], 6)),
                        "dest": (round(dest[0], 6), round(dest[1], 6)),
                        "endpoint": args.endpoint,
                    }
                )
                routes_data = cache.get_or_create(key, _request)
            else:
                routes_data = _request()

            routes = routes_data.get("routes", [])
            if not routes:
                continue

            scored_routes = []
            for idx, route in enumerate(routes):
                coords = (route.get("geometry") or {}).get("coordinates") or []
                if not coords:
                    continue
                samples = route_utils.densify_route(coords, args.step)
                max_dist = args.max_heatmap_distance if args.max_heatmap_distance > 0 else None
                scenic_stats = route_utils.compute_route_scenic(samples, heatmap_points, max_distance=max_dist)
                mean_score = (scenic_stats or {}).get("mean")
                coverage = (scenic_stats or {}).get("coverage")
                effective = None
                if mean_score is not None and coverage is not None:
                    effective = mean_score * coverage
                scored_routes.append(
                    {
                        "index": idx,
                        "distance": route.get("distance"),
                        "duration": route.get("duration"),
                        "scenic_score": mean_score,
                        "scenic_effective_score": effective,
                        "scenic_coverage": coverage,
                    }
                )

            if not scored_routes:
                continue

            scenic_candidates = [r for r in scored_routes if r["scenic_effective_score"] is not None]
            scenic_best = max(scenic_candidates, key=lambda r: r["scenic_effective_score"]) if scenic_candidates else None
            shortest = min(scored_routes, key=lambda r: r["distance"] or float("inf"))

            if scenic_best and scenic_best["index"] == shortest["index"]:
                scenic_matches += 1

            distance_delta = None
            if scenic_best and scenic_best["distance"] is not None and shortest["distance"] is not None:
                distance_delta = scenic_best["distance"] - shortest["distance"]

            writer.writerow(
                {
                    "pair_id": pair_id,
                    "origin_lat": origin[0],
                    "origin_lon": origin[1],
                    "dest_lat": dest[0],
                    "dest_lon": dest[1],
                    "route_count": len(scored_routes),
                    "scenic_best_index": (scenic_best or {}).get("index"),
                    "scenic_best_score": (scenic_best or {}).get("scenic_score"),
                    "scenic_best_effective_score": (scenic_best or {}).get("scenic_effective_score"),
                    "scenic_best_coverage": (scenic_best or {}).get("scenic_coverage"),
                    "scenic_best_distance_m": (scenic_best or {}).get("distance"),
                    "shortest_index": shortest.get("index"),
                    "shortest_distance_m": shortest.get("distance"),
                    "shortest_duration_s": shortest.get("duration"),
                    "shortest_scenic_score": shortest.get("scenic_score"),
                    "shortest_effective_score": shortest.get("scenic_effective_score"),
                    "distance_delta_m": distance_delta,
                }
            )

    total_pairs = len(pairs)
    print(f"Wrote route validation results to {output_path}")
    print(f"Scenic best equals shortest for {scenic_matches}/{total_pairs} pairs")


if __name__ == "__main__":
    main()
