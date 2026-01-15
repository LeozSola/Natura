"""
Small collection of geographic helpers shared across the pipeline.
"""

from __future__ import annotations

import math
from typing import Iterable, Iterator, List, Sequence, Tuple


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance between two WGS84 coordinates in metres."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def interpolate_linear(lat1: float, lon1: float, lat2: float, lon2: float, fraction: float) -> Tuple[float, float]:
    """Simple linear interpolation between two coordinates."""
    return lat1 + (lat2 - lat1) * fraction, lon1 + (lon2 - lon1) * fraction


def densify_linestring(coords: Sequence[Sequence[float]], step_m: float) -> List[Tuple[float, float]]:
    """Return a list of evenly spaced points along a LineString."""
    if step_m <= 0:
        raise ValueError("step_m must be > 0")
    points: List[Tuple[float, float]] = []
    if not coords:
        return points

    prev_lon, prev_lat = coords[0]
    points.append((prev_lat, prev_lon))

    for lon, lat in coords[1:]:
        segment_len = haversine_m(prev_lat, prev_lon, lat, lon)
        if segment_len <= 0:
            prev_lon, prev_lat = lon, lat
            continue
        # number of interior points (no double-counting end)
        steps = max(1, int(segment_len // step_m))
        for step in range(1, steps + 1):
            fraction = min(1.0, (step * step_m) / segment_len)
            interp_lat, interp_lon = interpolate_linear(prev_lat, prev_lon, lat, lon, fraction)
            if fraction < 1.0:
                points.append((interp_lat, interp_lon))
        points.append((lat, lon))
        prev_lon, prev_lat = lon, lat

    # Deduplicate consecutive duplicates that may occur due to short segments
    deduped: List[Tuple[float, float]] = []
    for pt in points:
        if not deduped or deduped[-1] != pt:
            deduped.append(pt)
    return deduped

