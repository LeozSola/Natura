"""
Script: 05_scenic_model.py
==========================

This module processes downloaded Mapillary images and computes a set of
simple heuristic features that serve as proxies for "scenicness."  It
avoids heavy machine learning dependencies by using only Pillow and
NumPy.  While not as sophisticated as deep models, these heuristics
provide a starting point for evaluating the relative attractiveness of
scenes.

For each image, the following features are extracted:

* ``green_ratio`` – proportion of pixels that appear to be vegetation
  (green dominant over red and blue channels).
* ``sky_ratio`` – proportion of pixels classified as sky (blue channel
  dominant over red and green).
* ``water_ratio`` – proportion of pixels where blue and green are high
  relative to red.
* ``colorfulness`` – a measure of how vibrant the image is, based on
  the difference between colour channels (see Hasler and Süsstrunk,
  2003).

These features are combined into a ``scenic_score`` using a weighted
sum.  You can adjust the weights depending on your preferences.

Usage
-----

    python 05_scenic_model.py \
        --images-dir data/images/mapillary \
        --metadata data/im_meta/mapillary_samples.csv \
        --output data/scores/images.csv

The script expects JPEG images named ``<image_id>.jpg`` in the
specified directory and a CSV mapping image IDs to their geographic
locations and compass angles.
"""

import argparse
import csv
import os
from typing import Dict, Tuple, Optional

import numpy as np
from PIL import Image


def load_metadata(csv_path: str) -> Dict[str, Dict[str, float]]:
    """Load image metadata keyed by image_id.

    Each row in the CSV must include ``image_id``, ``image_lat``,
    ``image_lon`` and optionally ``compass_angle``.  Returns a mapping
    from image_id to a dictionary of these values.
    """
    meta: Dict[str, Dict[str, float]] = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            image_id = row.get("image_id")
            if not image_id:
                continue
            lat = row.get("image_lat")
            lon = row.get("image_lon")
            angle = row.get("compass_angle")
            meta[image_id] = {
                "lat": float(lat) if lat else None,
                "lon": float(lon) if lon else None,
                "compass_angle": float(angle) if angle else None,
            }
    return meta


def compute_colorfulness(arr: np.ndarray) -> float:
    """Compute the colourfulness metric of an image array.

    Based on the method by Hasler and Süsstrunk (2003).  See
    https://infoscience.epfl.ch/record/33994 for details.
    """
    # Separate channels
    (R, G, B) = arr[..., 0], arr[..., 1], arr[..., 2]
    # Compute rg = R - G and yb = 0.5 * (R + G) - B
    rg = R - G
    yb = 0.5 * (R + G) - B
    # Compute means and standard deviations
    std_rg = np.std(rg)
    std_yb = np.std(yb)
    mean_rg = np.mean(rg)
    mean_yb = np.mean(yb)
    # Combine
    std_root = np.sqrt(std_rg ** 2 + std_yb ** 2)
    mean_root = np.sqrt(mean_rg ** 2 + mean_yb ** 2)
    return std_root + 0.3 * mean_root


def compute_pixel_ratios(arr: np.ndarray) -> Tuple[float, float, float]:
    """Compute vegetation, sky and water pixel ratios.

    Returns three values between 0 and 1 representing the fraction of
    pixels that meet simple heuristics for green vegetation, blue sky
    and water.  These heuristics may misclassify pixels but provide a
    lightweight approximation.
    """
    r = arr[..., 0].astype(np.int32)
    g = arr[..., 1].astype(np.int32)
    b = arr[..., 2].astype(np.int32)
    total = arr.shape[0] * arr.shape[1]
    # Vegetation: green significantly higher than red and blue
    veg_mask = (g > r + 20) & (g > b + 20) & (g > 100)
    # Sky: blue dominant, moderate brightness
    sky_mask = (b > g + 10) & (b > r + 10) & (b > 80)
    # Water: blue moderately high and green somewhat high relative to red
    water_mask = (b > r + 20) & (g > r) & (b > 80)
    veg_ratio = float(np.sum(veg_mask)) / total
    sky_ratio = float(np.sum(sky_mask)) / total
    water_ratio = float(np.sum(water_mask)) / total
    return veg_ratio, sky_ratio, water_ratio


def compute_features(image_path: str) -> Optional[Dict[str, float]]:
    """Compute the feature set for a single image.

    Returns a dictionary of features.  If the image cannot be processed,
    ``None`` is returned.
    """
    try:
        with Image.open(image_path) as im:
            # Convert to RGB and resize to a fixed small size to speed up
            im = im.convert("RGB")
            im_small = im.resize((256, 256))
            arr = np.array(im_small)
    except Exception as exc:
        print(f"Failed to process {image_path}: {exc}")
        return None
    veg_ratio, sky_ratio, water_ratio = compute_pixel_ratios(arr)
    colorfulness = compute_colorfulness(arr)
    # Normalize colorfulness by a typical range (observed approx 0-100)
    colorfulness_norm = colorfulness / 100.0
    # Compute scenic score as weighted sum (tune weights as desired)
    scenic_score = 0.4 * veg_ratio + 0.3 * sky_ratio + 0.2 * water_ratio + 0.1 * colorfulness_norm
    return {
        "green_ratio": veg_ratio,
        "sky_ratio": sky_ratio,
        "water_ratio": water_ratio,
        "colorfulness": colorfulness,
        "scenic_score": scenic_score,
    }


def ensure_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute heuristic scenicness features for Mapillary images")
    parser.add_argument(
        "--images-dir",
        type=str,
        required=True,
        help="Directory containing downloaded images (e.g. data/images/mapillary)",
    )
    parser.add_argument(
        "--metadata",
        type=str,
        required=True,
        help="CSV with image_id, image_lat, image_lon and compass_angle",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/scores/images.csv",
        help="Path to write the computed features as CSV",
    )
    args = parser.parse_args()

    metadata = load_metadata(args.metadata)
    image_ids = list(metadata.keys())
    total = len(image_ids)
    print(f"Computing features for {total} images")
    ensure_dir(args.output)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "image_id",
            "lat",
            "lon",
            "compass_angle",
            "green_ratio",
            "sky_ratio",
            "water_ratio",
            "colorfulness",
            "scenic_score",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        processed = 0
        for image_id in image_ids:
            img_path = os.path.join(args.images_dir, f"{image_id}.jpg")
            if not os.path.isfile(img_path):
                continue
            features = compute_features(img_path)
            if features is None:
                continue
            meta = metadata[image_id]
            row = {
                "image_id": image_id,
                "lat": meta.get("lat"),
                "lon": meta.get("lon"),
                "compass_angle": meta.get("compass_angle"),
            }
            row.update(features)
            writer.writerow(row)
            processed += 1
            if processed % 50 == 0:
                print(f"Processed {processed}/{total} images")
    print(f"Feature CSV written to {args.output}")


if __name__ == "__main__":
    main()