"""
Script: 09_coverage_report.py
=============================

Summarize scenic data coverage and bounds for the current dataset.
Uses the grid-scored GeoJSON when available; otherwise falls back to the
heatmap only (coverage ratio will be unavailable).
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def load_geojson(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def summarize_points(points: List[Tuple[float, float, Optional[float]]]) -> Dict[str, Optional[float]]:
    if not points:
        return {
            "count": 0,
            "min_lat": None,
            "min_lon": None,
            "max_lat": None,
            "max_lon": None,
            "min_score": None,
            "max_score": None,
            "mean_score": None,
        }
    lats = [lat for lat, _lon, _score in points]
    lons = [lon for _lat, lon, _score in points]
    scores = [score for _lat, _lon, score in points if score is not None]
    return {
        "count": len(points),
        "min_lat": min(lats),
        "min_lon": min(lons),
        "max_lat": max(lats),
        "max_lon": max(lons),
        "min_score": min(scores) if scores else None,
        "max_score": max(scores) if scores else None,
        "mean_score": sum(scores) / len(scores) if scores else None,
    }


def parse_grid(grid_path: Path) -> Tuple[List[Tuple[float, float, Optional[float]]], int, int]:
    data = load_geojson(grid_path)
    features = data.get("features", [])
    points: List[Tuple[float, float, Optional[float]]] = []
    scored = 0
    for feat in features:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = coords[:2]
        score = (feat.get("properties") or {}).get("scenic_score")
        if score is not None:
            scored += 1
            score = float(score)
        points.append((lat, lon, score))
    return points, len(points), scored


def parse_heatmap(heatmap_path: Path) -> List[Tuple[float, float, Optional[float]]]:
    data = load_geojson(heatmap_path)
    points: List[Tuple[float, float, Optional[float]]] = []
    for feat in data.get("features", []):
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = coords[:2]
        score = (feat.get("properties") or {}).get("scenic_score")
        if score is not None:
            score = float(score)
        points.append((lat, lon, score))
    return points


def main() -> None:
    parser = argparse.ArgumentParser(description="Report scenic data coverage and bounds")
    parser.add_argument(
        "--source",
        type=str,
        default="mapillary",
        help="Data source to report on (mapillary|google)",
    )
    parser.add_argument(
        "--grid-scored",
        type=str,
        default="",
        help="Grid-scored GeoJSON path (optional override)",
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
        help="Fallback heatmap path if the grid heatmap is missing",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="outputs/coverage_report.json",
        help="Output JSON path for the report",
    )
    args = parser.parse_args()

    report: Dict[str, Dict[str, Optional[float]]] = {}

    grid_path = Path(args.grid_scored) if args.grid_scored else Path(f"data/{args.source}/geojson/grid_scored.geojson")
    if grid_path.exists():
        grid_points, total, scored = parse_grid(grid_path)
        summary = summarize_points(grid_points)
        coverage = float(scored) / total if total else None
        report["grid"] = {
            "total_points": total,
            "scored_points": scored,
            "coverage_ratio": coverage,
            **summary,
        }
    else:
        report["grid"] = {
            "total_points": 0,
            "scored_points": 0,
            "coverage_ratio": None,
            "count": 0,
            "min_lat": None,
            "min_lon": None,
            "max_lat": None,
            "max_lon": None,
            "min_score": None,
            "max_score": None,
            "mean_score": None,
        }

    heatmap_path = Path(args.heatmap) if args.heatmap else Path(f"data/{args.source}/geojson/scenic_grid_heatmap.geojson")
    if not heatmap_path.exists():
        fallback = Path(args.fallback_heatmap) if args.fallback_heatmap else Path(
            f"data/{args.source}/geojson/scenic_heatmap.geojson"
        )
        if not fallback.exists():
            fallback = Path("data/geojson/scenic_heatmap.geojson")
        heatmap_path = fallback
    if heatmap_path.exists():
        heatmap_points = parse_heatmap(heatmap_path)
        report["heatmap"] = summarize_points(heatmap_points)
    else:
        report["heatmap"] = {
            "count": 0,
            "min_lat": None,
            "min_lon": None,
            "max_lat": None,
            "max_lon": None,
            "min_score": None,
            "max_score": None,
            "mean_score": None,
        }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote coverage report to {output_path}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
