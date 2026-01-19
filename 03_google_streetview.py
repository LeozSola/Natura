"""
Script: 03_google_streetview.py
===============================

Fetch Street View metadata and thumbnails for grid sample points.
Outputs a metadata CSV compatible with the downstream scenic pipeline.

Usage
-----
python 03_google_streetview.py \
  --input data/google/osm/grid_samples.geojson \
  --key $GOOGLE_MAPS_API_KEY \
  --output data/google/im_meta/google_grid.csv \
  --images-dir data/google/images
"""

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from natura.cache import DiskCache
from natura.geo import haversine_m


METADATA_ENDPOINT = "https://maps.googleapis.com/maps/api/streetview/metadata"
IMAGE_ENDPOINT = "https://maps.googleapis.com/maps/api/streetview"


def load_samples(path: str) -> List[Dict[str, float]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    samples = []
    for idx, feature in enumerate(data.get("features", [])):
        geom = feature.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = coords[:2]
        samples.append({"index": idx, "lat": lat, "lon": lon})
    return samples


def ensure_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def meters_to_bbox(lat: float, lon: float, radius_m: float) -> Tuple[float, float, float, float]:
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(0.0001, math.cos(math.radians(lat))))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def query_metadata(
    sess: requests.Session,
    lat: float,
    lon: float,
    key: str,
    radius: Optional[int] = None,
    source: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    params = {
        "location": f"{lat},{lon}",
        "key": key,
    }
    if radius:
        params["radius"] = str(radius)
    if source:
        params["source"] = source
    resp = sess.get(METADATA_ENDPOINT, params=params, timeout=20)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if data.get("status") != "OK":
        return None
    return data


def download_image(
    sess: requests.Session,
    lat: float,
    lon: float,
    key: str,
    dest_path: str,
    size: str,
    source: Optional[str] = None,
) -> bool:
    params = {
        "location": f"{lat},{lon}",
        "key": key,
        "size": size,
    }
    if source:
        params["source"] = source
    resp = sess.get(IMAGE_ENDPOINT, params=params, timeout=30, stream=True)
    if resp.status_code != 200:
        return False
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return True


def build_image_id(meta: Dict[str, str], lat: float, lon: float) -> str:
    pano_id = meta.get("pano_id")
    if pano_id:
        return pano_id
    return f"loc_{lat:.6f}_{lon:.6f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Google Street View metadata + thumbnails for grid samples")
    parser.add_argument("--input", type=str, required=True, help="Input grid samples GeoJSON")
    parser.add_argument(
        "--key",
        type=str,
        default=os.environ.get("GOOGLE_MAPS_API_KEY"),
        help="Google Maps API key (or set GOOGLE_MAPS_API_KEY env var)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/google/im_meta/google_grid.csv",
        help="Output metadata CSV path",
    )
    parser.add_argument(
        "--images-dir",
        type=str,
        default="data/google/images",
        help="Directory to save downloaded images",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of samples to process",
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=250,
        help="Search radius (m) for metadata lookup (default: 250)",
    )
    parser.add_argument(
        "--size",
        type=str,
        default="640x640",
        help="Street View image size (default: 640x640)",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Optional Google Street View source filter (e.g. 'outdoor')",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default="data/cache",
        help="Directory for metadata cache (per sample point)",
    )
    parser.add_argument(
        "--cache-ttl",
        type=float,
        default=14 * 24 * 3600,
        help="Cache expiry in seconds (default: 14 days). Set to 0 for no expiry.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable caching metadata requests",
    )
    args = parser.parse_args()

    if not args.key:
        raise SystemExit("A Google Maps API key is required. Provide via --key or GOOGLE_MAPS_API_KEY.")

    samples = load_samples(args.input)
    if args.limit is not None:
        samples = samples[: args.limit]
    total = len(samples)
    print(f"Loaded {total} grid samples from {args.input}")

    if not os.path.exists(args.images_dir):
        os.makedirs(args.images_dir, exist_ok=True)
    ensure_dir(args.output)

    cache: Optional[DiskCache] = None
    if not args.no_cache:
        ttl = args.cache_ttl if args.cache_ttl > 0 else None
        cache = DiskCache(Path(args.cache_dir), namespace="google_streetview_metadata", max_age=ttl)

    sess = requests.Session()
    fieldnames = [
        "sample_index",
        "sample_lat",
        "sample_lon",
        "image_id",
        "image_lat",
        "image_lon",
        "compass_angle",
        "image_distance_m",
        "pano_id",
    ]

    matches = 0
    with open(args.output, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for idx, sample in enumerate(samples, start=1):
            lat = sample["lat"]
            lon = sample["lon"]
            cache_key = None
            meta = None

            if cache is not None:
                cache_key = DiskCache.key_from_mapping(
                    {
                        "lat": round(lat, 6),
                        "lon": round(lon, 6),
                        "radius": args.radius,
                        "source": args.source,
                    }
                )
                meta = cache.load(cache_key)

            if meta is None:
                meta = query_metadata(sess, lat, lon, args.key, radius=args.radius, source=args.source)
                if cache is not None and cache_key is not None:
                    cache.save(cache_key, meta)

            if meta:
                matches += 1
                image_id = build_image_id(meta, lat, lon)
                image_loc = (meta.get("location") or {})
                image_lat = float(image_loc.get("lat", lat))
                image_lon = float(image_loc.get("lng", lon))
                image_distance = haversine_m(lat, lon, image_lat, image_lon)
                dest_path = os.path.join(args.images_dir, f"{image_id}.jpg")
                if not os.path.exists(dest_path):
                    ok = download_image(
                        sess,
                        image_lat,
                        image_lon,
                        args.key,
                        dest_path,
                        size=args.size,
                        source=args.source,
                    )
                    if not ok:
                        image_id = ""
            else:
                image_id = ""
                image_lat = ""
                image_lon = ""
                image_distance = ""

            writer.writerow(
                {
                    "sample_index": sample["index"],
                    "sample_lat": lat,
                    "sample_lon": lon,
                    "image_id": image_id,
                    "image_lat": image_lat,
                    "image_lon": image_lon,
                    "compass_angle": "",
                    "image_distance_m": image_distance,
                    "pano_id": (meta or {}).get("pano_id", ""),
                }
            )

            if idx % 100 == 0 or idx == total:
                print(f"Processed {idx}/{total} samples")

    print(f"Wrote metadata to {args.output}; matched {matches} images out of {total} samples")


if __name__ == "__main__":
    main()
