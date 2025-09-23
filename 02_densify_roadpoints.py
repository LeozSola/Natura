"""
Script: 02_densify_roadpoints.py
=================================

This module takes a GeoJSON file of road segments (as produced by
``01_fetch_osm_roads.py``) and creates a set of sample points along each
polyline at a fixed interval.  Each sample point includes the bearing
(heading) of the road at that location.

The implementation avoids heavy dependencies such as shapely or geopandas by
working directly with coordinate sequences.  Distances are computed using
a simple haversine formula, which is sufficiently accurate for small
intervals (tens or hundreds of metres).  Bearings are calculated from
consecutive points.

Usage
-----

    python 02_densify_roadpoints.py \
        --input data/osm/roads.geojson \
        --step 100 \
        --output data/osm/samples.geojson

Parameters
----------
--input:
    Path to the GeoJSON file containing road segments.
--step:
    Sampling interval in metres.  Defaults to 100 m.
--output:
    Path where the generated sample points will be written as a GeoJSON
    FeatureCollection.  Each feature has properties: ``road_id`` and
    ``bearing`` (degrees from north).

Notes
-----
This script does not require internet access.  It operates solely on the
input GeoJSON.  If you intend to use the sample points to query an
imagery service, ensure that your sampling interval is not too fine
(otherwise you will generate a large number of points).
"""

import argparse
import json
import math
import os
from typing import List, Tuple


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute the great‑circle distance between two points.

    This function implements the haversine formula to calculate the
    distance between two latitude/longitude pairs.  The result is
    returned in metres.

    Parameters
    ----------
    lat1, lon1, lat2, lon2: float
        Coordinates in decimal degrees.

    Returns
    -------
    float
        Distance in metres.
    """
    R = 6371000.0  # mean Earth radius in metres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the compass bearing from point 1 to point 2 in degrees.

    Bearings are measured clockwise from true north (0 degrees).  The
    result is between 0 and 360.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    initial_bearing = math.atan2(x, y)
    bearing_degrees = math.degrees(initial_bearing)
    return (bearing_degrees + 360) % 360


def interpolate_point(lat1: float, lon1: float, lat2: float, lon2: float, fraction: float) -> Tuple[float, float]:
    """Linearly interpolate between two points.

    This approximation treats latitude and longitude as linear over the
    interval, which is reasonable over small distances (hundreds of
    metres).  For long segments crossing large distances, a more
    sophisticated interpolation should be used.

    Parameters
    ----------
    lat1, lon1, lat2, lon2: float
        Start and end coordinates.
    fraction: float
        Fraction between 0 and 1 indicating the position along the
        segment.

    Returns
    -------
    (lat, lon): tuple of float
        Interpolated point.
    """
    lat = lat1 + (lat2 - lat1) * fraction
    lon = lon1 + (lon2 - lon1) * fraction
    return lat, lon


def densify_line(coords: List[List[float]], step: float) -> List[Tuple[float, float, float]]:
    """Generate sample points along a line.

    Given a list of [lon, lat] pairs representing a road segment, this
    function computes evenly spaced points along the line at the given
    step length.  For each sample, it also calculates the local bearing
    using the segment on which it lies.

    Returns a list of tuples (lat, lon, bearing).
    """
    samples = []
    if len(coords) < 2:
        return samples
    # Track leftover distance from previous segment to ensure constant spacing
    leftover = 0.0
    prev_lat, prev_lon = coords[0][1], coords[0][0]
    for i in range(1, len(coords)):
        curr_lon, curr_lat = coords[i]
        segment_length = haversine_distance(prev_lat, prev_lon, curr_lat, curr_lon)
        seg_bearing = bearing(prev_lat, prev_lon, curr_lat, curr_lon)
        # Distance along the segment including leftover from previous segments
        distance_covered = leftover
        while distance_covered + step <= segment_length:
            # Determine the fraction along the current segment where this sample falls
            fraction = (distance_covered + step) / segment_length
            s_lat, s_lon = interpolate_point(prev_lat, prev_lon, curr_lat, curr_lon, fraction)
            samples.append((s_lat, s_lon, seg_bearing))
            distance_covered += step
        # Update leftover to the remainder of the segment not covered by a full step
        leftover = segment_length - distance_covered
        prev_lat, prev_lon = curr_lat, curr_lon
    return samples


def load_geojson(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Densify road segments into sample points")
    parser.add_argument("--input", type=str, required=True, help="Input roads GeoJSON file")
    parser.add_argument("--step", type=float, default=100.0, help="Sampling interval in metres (default: 100)")
    parser.add_argument(
        "--output",
        type=str,
        default="data/osm/samples.geojson",
        help="Path to write sample points GeoJSON",
    )
    args = parser.parse_args()

    data = load_geojson(args.input)
    features = data.get("features", [])
    out_features = []
    for feat in features:
        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates", [])
        road_id = feat.get("properties", {}).get("id")
        samples = densify_line(coords, args.step)
        for lat, lon, brg in samples:
            out_features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "road_id": road_id,
                        "bearing": brg,
                    },
                }
            )
    result = {"type": "FeatureCollection", "features": out_features}
    ensure_dir(args.output)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f)
    print(f"Generated {len(out_features)} sample points written to {args.output}")


if __name__ == "__main__":
    main()