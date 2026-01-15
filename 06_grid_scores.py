"""
Script: 06_grid_scores.py
=========================

Attach scenic scores to a uniform grid of sample points.

This script joins Mapillary metadata (sample_index -> image_id) with
image-level scenic scores and writes:
1) A scored grid GeoJSON (points with scenic_score + coverage metadata).
2) A heatmap GeoJSON for routing/visualization.
"""

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from natura.heatmap import write_heatmap


def load_geojson(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_metadata(csv_path: str) -> Dict[int, Dict[str, str]]:
    rows: Dict[int, Dict[str, str]] = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = row.get("sample_index")
            if idx is None:
                continue
            try:
                rows[int(idx)] = row
            except ValueError:
                continue
    return rows


def load_image_scores(csv_path: str) -> Dict[str, float]:
    scores = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            image_id = row.get("image_id")
            score = row.get("scenic_score")
            if image_id and score is not None:
                try:
                    scores[image_id] = float(score)
                except ValueError:
                    continue
    return scores


def ensure_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def parse_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Attach scenic scores to grid samples")
    parser.add_argument("--samples", type=str, required=True, help="Grid samples GeoJSON (from 02_grid_samples.py)")
    parser.add_argument("--metadata", type=str, required=True, help="Mapillary metadata CSV (from 03_mapillary_metadata.py)")
    parser.add_argument("--image-scores", type=str, required=True, help="Image scores CSV (from 05_scenic_model.py)")
    parser.add_argument(
        "--max-image-distance",
        type=float,
        default=250.0,
        help="Max allowed distance (m) from sample to matched image (default: 250)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/geojson/grid_scored.geojson",
        help="Output GeoJSON path for scored grid points",
    )
    parser.add_argument(
        "--heatmap-output",
        type=str,
        default="data/geojson/scenic_grid_heatmap.geojson",
        help="Output heatmap GeoJSON path",
    )
    args = parser.parse_args()

    samples = load_geojson(args.samples).get("features", [])
    metadata_rows = load_metadata(args.metadata)
    image_scores = load_image_scores(args.image_scores)

    scored_points = []
    heatmap_points = []
    max_dist = args.max_image_distance if args.max_image_distance and args.max_image_distance > 0 else None

    for idx, feature in enumerate(samples):
        props = feature.setdefault("properties", {})
        meta = metadata_rows.get(idx)
        image_id = (meta or {}).get("image_id") or None
        image_distance = parse_float((meta or {}).get("image_distance_m"))
        score = image_scores.get(image_id) if image_id else None

        if max_dist is not None and image_distance is not None and image_distance > max_dist:
            score = None

        if score is not None:
            props["scenic_score"] = float(score)
            props["n_samples"] = 1
            props["image_id"] = image_id
            props["image_distance_m"] = image_distance
            coords = feature.get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                lon, lat = coords[:2]
                heatmap_points.append((lat, lon, float(score)))
            scored_points.append(feature)
        else:
            props["scenic_score"] = None
            props["n_samples"] = 0
            props["image_id"] = image_id
            props["image_distance_m"] = image_distance
            scored_points.append(feature)

    out = {"type": "FeatureCollection", "features": scored_points}
    ensure_dir(args.output)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(f"Wrote scored grid to {args.output} ({len(heatmap_points)} scored points)")

    if args.heatmap_output and heatmap_points:
        write_heatmap(heatmap_points, Path(args.heatmap_output))
        print(f"Wrote grid heatmap to {args.heatmap_output}")
    elif args.heatmap_output:
        print("No scored points available to write a grid heatmap.")


if __name__ == "__main__":
    main()
