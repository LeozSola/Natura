"""
Script: 03_5_mapillary_two_pass.py
==================================

Automates a two-pass Mapillary metadata query:
- Pass 1: tight radius (e.g. 400m) to keep results close to road samples.
- Pass 2: wider radius (e.g. 1000m) for only those sample points that failed.

Merges the results into a single CSV with all sample points preserved.

Usage
-----
    $env:MAPILLARY_TOKEN="MLY|24448759648080414|5ba810a40676897e2f400df4b32af2e7"
    python 03_5_mapillary_two_pass.py `
        --input data/osm/samples.geojson `
        --out data/im_meta/mapillary_samplesTwoPass.csv `
        --radius1 400 --radius2 1000
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from typing import Dict, List

def ensure_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

def load_csv(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save_csv(path: str, rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    ensure_dir(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

def write_geojson(path: str, rows: List[Dict[str, str]]) -> None:
    feats = []
    for row in rows:
        if not row["sample_lat"] or not row["sample_lon"]:
            continue
        lat, lon = float(row["sample_lat"]), float(row["sample_lon"])
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"index": row["sample_index"]}
        })
    geo = {"type": "FeatureCollection", "features": feats}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(geo, f)

def run_pass(input_geojson: str, output_csv: str, radius: int, verbose: bool):
    cmd = [
        sys.executable, "03_mapillary_metadata.py",
        "--input", input_geojson,
        "--radius", str(radius),
        "--output", output_csv,
    ]
    if verbose:
        cmd.append("--verbose")
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="Input samples.geojson")
    p.add_argument("--out", required=True, help="Final merged CSV")
    p.add_argument("--radius1", type=int, default=400, help="Tight radius (m)")
    p.add_argument("--radius2", type=int, default=1000, help="Wide radius (m)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    tmp1 = "data/im_meta/_pass1.csv"
    tmp2 = "data/im_meta/_pass2.csv"
    misses_geo = "data/osm/_misses.geojson"

    # Pass 1
    run_pass(args.input, tmp1, args.radius1, args.verbose)
    rows1 = load_csv(tmp1)

    # Collect misses (empty image_id)
    misses = [r for r in rows1 if not r["image_id"]]
    print(f"Pass 1 matched {len(rows1) - len(misses)} / {len(rows1)}")

    if misses:
        write_geojson(misses_geo, misses)
        run_pass(misses_geo, tmp2, args.radius2, args.verbose)
        rows2 = load_csv(tmp2)
        rows2_map = {r["sample_index"]: r for r in rows2 if r["image_id"]}
    else:
        rows2_map = {}

    # Merge results: prefer pass1 rows, fill from pass2 where empty
    merged = []
    for r in rows1:
        if not r["image_id"] and r["sample_index"] in rows2_map:
            merged.append(rows2_map[r["sample_index"]])
        else:
            merged.append(r)

    fieldnames = list(rows1[0].keys())
    save_csv(args.out, merged, fieldnames)
    print(f"Merged output written to {args.out} "
          f"({sum(1 for r in merged if r['image_id'])}/{len(merged)} matched)")

if __name__ == "__main__":
    main()
