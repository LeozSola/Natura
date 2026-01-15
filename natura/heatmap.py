"""
Heatmap generation helpers.

We approximate the scenicness of the network by sampling scored edges and
producing dense point clouds. These points can drive a tile heatmap overlay and
also serve the routing module when it needs to look up a scenic score at any
arbitrary location.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence, Tuple

from .geo import densify_linestring


def iter_heatmap_points(
    edges_geojson: Dict,
    step_m: float = 75.0,
) -> Iterator[Tuple[float, float, float]]:
    """Yield (lat, lon, score) tuples along each scored edge."""
    for feature in edges_geojson.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue
        score = feature.get("properties", {}).get("scenic_score")
        if score is None:
            continue
        coords = geometry.get("coordinates") or []
        if not coords:
            continue
        for lat, lon in densify_linestring(coords, step_m):
            yield lat, lon, float(score)


def heatmap_feature_collection(points: Iterable[Tuple[float, float, float]]) -> Dict:
    """Convert sampled points to a GeoJSON FeatureCollection."""
    features = []
    for lat, lon, score in points:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"scenic_score": score},
            }
        )
    return {"type": "FeatureCollection", "features": features}


def write_heatmap(points: Iterable[Tuple[float, float, float]], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fc = heatmap_feature_collection(points)
    path.write_text(json.dumps(fc), encoding="utf-8")


def load_heatmap(path: Path) -> List[Tuple[float, float, float]]:
    """Read a GeoJSON heatmap file created by :func:`write_heatmap`."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    points: List[Tuple[float, float, float]] = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = coords[:2]
        score = feature.get("properties", {}).get("scenic_score")
        if score is None:
            continue
        points.append((lat, lon, float(score)))
    return points
