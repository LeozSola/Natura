"""
Script: 04_mapillary_images.py
==============================

This module downloads thumbnail images from Mapillary for a list of image IDs.
It reads a CSV file produced by ``03_mapillary_metadata.py`` and fetches
the ``thumb_1024_url`` for each image via the Mapillary Graph API.  The
images are stored on disk under the specified output directory.  Only
images that do not already exist will be downloaded; if a file is
present, it is skipped.

As with previous scripts, this code requires an active internet
connection and a valid Mapillary access token.  You can provide your
token via the ``--token`` argument or the ``MAPILLARY_TOKEN`` environment
variable.

Usage
-----

    python 04_mapillary_images.py \
        --input data/im_meta/mapillary_samples.csv \
        --token YOUR_MAPILLARY_ACCESS_TOKEN \
        --output-dir data/images/mapillary

Notes
-----
Mapillary imposes rate limits on API requests.  If you download a large
number of images, you may need to add delays or implement caching.  This
script is designed for small batches typical of an MVP evaluation.
"""

import argparse
import csv
import os
import sys
from typing import List, Dict

import requests

GRAPH_ENDPOINT_TEMPLATE = "https://graph.mapillary.com/{id}"


def read_image_ids(csv_path: str) -> List[str]:
    """Extract a list of unique image IDs from the metadata CSV."""
    ids = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            image_id = row.get("image_id")
            if image_id:
                ids.append(image_id)
    return list(dict.fromkeys(ids))  # preserve order and uniqueness


def get_thumbnail_url(image_id: str, token: str) -> str:
    """Retrieve the thumbnail URL for a Mapillary image via the Graph API.

    The Graph API returns a JSON object containing the field
    ``thumb_1024_url``, which points to a JPEG file hosted by Mapillary.
    """
    endpoint = GRAPH_ENDPOINT_TEMPLATE.format(id=image_id)
    params = {
        "fields": "thumb_1024_url",
        "access_token": token,
    }
    try:
        resp = requests.get(endpoint, params=params)
    except Exception as exc:
        print(f"Error requesting thumbnail for {image_id}: {exc}", file=sys.stderr)
        return ""
    if resp.status_code != 200:
        print(
            f"Failed to fetch thumbnail URL for {image_id}: {resp.status_code} {resp.text}",
            file=sys.stderr,
        )
        return ""
    data = resp.json()
    return data.get("thumb_1024_url", "")


def download_image(url: str, dest_path: str) -> bool:
    """Download an image from a URL and write it to dest_path.

    Returns ``True`` on success, ``False`` otherwise.
    """
    try:
        resp = requests.get(url, stream=True)
    except Exception as exc:
        print(f"Error downloading {url}: {exc}", file=sys.stderr)
        return False
    if resp.status_code != 200:
        print(
            f"Failed to download {url}: {resp.status_code} {resp.text}",
            file=sys.stderr,
        )
        return False
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return True


def ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Mapillary thumbnails from metadata CSV")
    parser.add_argument("--input", type=str, required=True, help="Path to metadata CSV")
    parser.add_argument(
        "--token",
        type=str,
        default=os.environ.get("MAPILLARY_TOKEN"),
        help="Mapillary access token (or set MAPILLARY_TOKEN env var)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/images/mapillary",
        help="Directory to save downloaded images",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of images to download (for testing)",
    )
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("A Mapillary access token is required (provide via --token or MAPILLARY_TOKEN env var)")

    ids = read_image_ids(args.input)
    if args.limit is not None:
        ids = ids[: args.limit]
    total = len(ids)
    print(f"Downloading thumbnails for {total} images to {args.output_dir}")
    ensure_dir(args.output_dir)

    for idx, image_id in enumerate(ids):
        dest_path = os.path.join(args.output_dir, f"{image_id}.jpg")
        if os.path.exists(dest_path):
            # Skip existing files
            continue
        url = get_thumbnail_url(image_id, args.token)
        if not url:
            continue
        success = download_image(url, dest_path)
        if not success:
            continue
        if (idx + 1) % 50 == 0:
            print(f"Downloaded {idx + 1}/{total} images")
    print("Finished downloading thumbnails")


if __name__ == "__main__":
    main()