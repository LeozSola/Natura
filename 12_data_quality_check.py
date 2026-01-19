"""
Script: 12_data_quality_check.py
================================

Quick data quality report for the scenic pipeline inputs/outputs.
Focuses on the latter pipeline stages and verifies that imagery and
scores exist with reasonable coverage.
"""

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def load_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_geojson(path: Path) -> Dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def to_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def summarize_numeric(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check data quality for scenic pipeline inputs/outputs")
    parser.add_argument("--source", type=str, default="mapillary", help="Data source (mapillary|google)")
    parser.add_argument("--output", type=str, default="outputs/data_quality_report.json", help="Output JSON report path")
    args = parser.parse_args()

    base = Path("data") / args.source
    meta_path = base / "im_meta" / ("google_grid.csv" if args.source == "google" else "mapillary_grid.csv")
    images_dir = base / "images"
    scores_path = base / "scores" / "image_scores.csv"
    grid_path = base / "osm" / "grid_samples.geojson"
    heatmap_path = base / "geojson" / "scenic_grid_heatmap.geojson"

    meta_rows = load_csv(meta_path)
    image_ids = [row.get("image_id") for row in meta_rows if row.get("image_id")]
    unique_image_ids = list(dict.fromkeys(image_ids))
    image_distance_values = [
        val for val in (to_float(row.get("image_distance_m")) for row in meta_rows) if val is not None
    ]

    missing_images = 0
    for image_id in unique_image_ids:
        image_path = images_dir / f"{image_id}.jpg"
        if not image_path.exists():
            missing_images += 1

    scores_rows = load_csv(scores_path)
    scenic_scores = [
        val for val in (to_float(row.get("scenic_score")) for row in scores_rows) if val is not None
    ]

    grid_data = load_geojson(grid_path)
    grid_points = len(grid_data.get("features", [])) if grid_data else 0
    heatmap_data = load_geojson(heatmap_path)
    heatmap_points = len(heatmap_data.get("features", [])) if heatmap_data else 0

    report = {
        "source": args.source,
        "paths": {
            "metadata_csv": str(meta_path),
            "images_dir": str(images_dir),
            "scores_csv": str(scores_path),
            "grid_geojson": str(grid_path),
            "heatmap_geojson": str(heatmap_path),
        },
        "metadata": {
            "rows": len(meta_rows),
            "matched_images": len(image_ids),
            "unique_images": len(unique_image_ids),
            "missing_image_files": missing_images,
            "match_rate": (len(image_ids) / len(meta_rows)) if meta_rows else None,
            "image_distance_m": summarize_numeric(image_distance_values),
        },
        "scores": {
            "rows": len(scores_rows),
            "scored_images": len(scenic_scores),
            "scenic_score": summarize_numeric(scenic_scores),
        },
        "grid": {
            "points": grid_points,
            "heatmap_points": heatmap_points,
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
