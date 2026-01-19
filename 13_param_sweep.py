"""
Script: 13_param_sweep.py
=========================

Run a parameter sweep for scenic scoring on existing imagery and report
route-ranking sensitivity. No external imagery calls are made.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from pathlib import Path
from typing import Dict, List, Optional


def read_scores(path: Path) -> List[float]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        values = []
        for row in reader:
            try:
                values.append(float(row.get("scenic_score", "")))
            except ValueError:
                continue
        return values


def score_stats(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "max": None, "mean": None, "std": None}
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return {
        "min": min(values),
        "max": max(values),
        "mean": mean,
        "std": math.sqrt(var),
    }


def read_validation(path: Path) -> Dict[str, Optional[float]]:
    if not path.exists():
        return {
            "pairs": 0,
            "scenic_differs": None,
            "scenic_diff_rate": None,
            "mean_distance_delta_m": None,
            "mean_scenic_best_effective": None,
        }
    with path.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    if not reader:
        return {
            "pairs": 0,
            "scenic_differs": None,
            "scenic_diff_rate": None,
            "mean_distance_delta_m": None,
            "mean_scenic_best_effective": None,
        }
    scenic_diff = 0
    deltas = []
    scenic_best = []
    for row in reader:
        if row.get("scenic_best_index") != row.get("shortest_index"):
            scenic_diff += 1
        try:
            deltas.append(float(row.get("distance_delta_m", "")))
        except ValueError:
            pass
        try:
            scenic_best.append(float(row.get("scenic_best_effective_score", "")))
        except ValueError:
            pass
    return {
        "pairs": len(reader),
        "scenic_differs": scenic_diff,
        "scenic_diff_rate": scenic_diff / len(reader),
        "mean_distance_delta_m": (sum(deltas) / len(deltas)) if deltas else None,
        "mean_scenic_best_effective": (sum(scenic_best) / len(scenic_best)) if scenic_best else None,
    }


def run_command(cmd: List[str]) -> None:
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise SystemExit(f"Command failed: {' '.join(cmd)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Parameter sweep for scenic scoring")
    parser.add_argument("--source", type=str, default="google", help="Data source (google|mapillary)")
    parser.add_argument("--max-image-distance", type=float, default=250.0, help="Max distance (m) for grid scoring")
    parser.add_argument("--output", type=str, default="outputs/param_sweep_summary.csv", help="Summary CSV path")
    parser.add_argument("--json-output", type=str, default="outputs/param_sweep_summary.json", help="Summary JSON path")
    args = parser.parse_args()

    base = Path("data") / args.source
    images_dir = base / "images"
    metadata_csv = base / "im_meta" / ("google_grid.csv" if args.source == "google" else "mapillary_grid.csv")
    samples_geojson = base / "osm" / "grid_samples.geojson"

    configs = [
        {
            "id": "baseline",
            "resize": 256,
            "colorfulness_norm": 100.0,
            "veg_delta": 20,
            "veg_min": 100,
            "sky_delta": 10,
            "sky_min": 80,
            "water_blue_delta": 20,
            "water_min_blue": 80,
            "weight_green": 0.4,
            "weight_sky": 0.3,
            "weight_water": 0.2,
            "weight_color": 0.1,
        },
        {
            "id": "sky_boost",
            "resize": 256,
            "colorfulness_norm": 100.0,
            "veg_delta": 20,
            "veg_min": 100,
            "sky_delta": 10,
            "sky_min": 80,
            "water_blue_delta": 20,
            "water_min_blue": 80,
            "weight_green": 0.3,
            "weight_sky": 0.4,
            "weight_water": 0.2,
            "weight_color": 0.1,
        },
        {
            "id": "water_boost",
            "resize": 256,
            "colorfulness_norm": 100.0,
            "veg_delta": 20,
            "veg_min": 100,
            "sky_delta": 10,
            "sky_min": 80,
            "water_blue_delta": 20,
            "water_min_blue": 80,
            "weight_green": 0.3,
            "weight_sky": 0.25,
            "weight_water": 0.35,
            "weight_color": 0.1,
        },
        {
            "id": "higher_thresholds",
            "resize": 256,
            "colorfulness_norm": 100.0,
            "veg_delta": 30,
            "veg_min": 120,
            "sky_delta": 20,
            "sky_min": 100,
            "water_blue_delta": 30,
            "water_min_blue": 100,
            "weight_green": 0.4,
            "weight_sky": 0.3,
            "weight_water": 0.2,
            "weight_color": 0.1,
        },
        {
            "id": "color_boost",
            "resize": 256,
            "colorfulness_norm": 80.0,
            "veg_delta": 20,
            "veg_min": 100,
            "sky_delta": 10,
            "sky_min": 80,
            "water_blue_delta": 20,
            "water_min_blue": 80,
            "weight_green": 0.3,
            "weight_sky": 0.3,
            "weight_water": 0.2,
            "weight_color": 0.2,
        },
        {
            "id": "resize_384",
            "resize": 384,
            "colorfulness_norm": 100.0,
            "veg_delta": 20,
            "veg_min": 100,
            "sky_delta": 10,
            "sky_min": 80,
            "water_blue_delta": 20,
            "water_min_blue": 80,
            "weight_green": 0.4,
            "weight_sky": 0.3,
            "weight_water": 0.2,
            "weight_color": 0.1,
        },
    ]

    summary_rows = []
    summary_json = []

    for cfg in configs:
        cfg_id = cfg["id"]
        scores_csv = base / "scores" / f"image_scores__{cfg_id}.csv"
        grid_out = base / "geojson" / f"grid_scored__{cfg_id}.geojson"
        heatmap_out = base / "geojson" / f"scenic_grid_heatmap__{cfg_id}.geojson"
        validation_out = Path("outputs") / f"route_validation__{cfg_id}.csv"

        run_command(
            [
                "python",
                "05_scenic_model.py",
                "--images-dir",
                str(images_dir),
                "--metadata",
                str(metadata_csv),
                "--output",
                str(scores_csv),
                "--resize",
                str(cfg["resize"]),
                "--colorfulness-norm",
                str(cfg["colorfulness_norm"]),
                "--veg-delta",
                str(cfg["veg_delta"]),
                "--veg-min",
                str(cfg["veg_min"]),
                "--sky-delta",
                str(cfg["sky_delta"]),
                "--sky-min",
                str(cfg["sky_min"]),
                "--water-blue-delta",
                str(cfg["water_blue_delta"]),
                "--water-min-blue",
                str(cfg["water_min_blue"]),
                "--weight-green",
                str(cfg["weight_green"]),
                "--weight-sky",
                str(cfg["weight_sky"]),
                "--weight-water",
                str(cfg["weight_water"]),
                "--weight-color",
                str(cfg["weight_color"]),
            ]
        )

        run_command(
            [
                "python",
                "06_grid_scores.py",
                "--samples",
                str(samples_geojson),
                "--metadata",
                str(metadata_csv),
                "--image-scores",
                str(scores_csv),
                "--max-image-distance",
                str(args.max_image_distance),
                "--output",
                str(grid_out),
                "--heatmap-output",
                str(heatmap_out),
            ]
        )

        run_command(
            [
                "python",
                "10_route_validation.py",
                "--source",
                args.source,
                "--heatmap",
                str(heatmap_out),
                "--output",
                str(validation_out),
            ]
        )

        stats = score_stats(read_scores(scores_csv))
        validation = read_validation(validation_out)

        row = {
            "config_id": cfg_id,
            **stats,
            **validation,
        }
        summary_rows.append(row)
        summary_json.append({"config": cfg, "summary": row})

    out_csv = Path(args.output)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(summary_rows[0].keys()) if summary_rows else []
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)

    out_json = Path(args.json_output)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary_json, indent=2), encoding="utf-8")

    print(f"Wrote sweep summary to {out_csv} and {out_json}")


if __name__ == "__main__":
    main()
