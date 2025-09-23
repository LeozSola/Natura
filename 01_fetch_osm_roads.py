"""
Script: 01_fetch_osm_roads.py
===============================

This module queries the OpenStreetMap (OSM) Overpass API for road geometries
within a specified radius around a centre point.  It produces a GeoJSON file
containing only the requested highway types (by default major driveable roads).

The script does not require heavy spatial libraries such as geopandas or
shapely; it simply passes through the geometry returned by Overpass.  The
resulting file can be consumed by the next step in the pipeline to densify
road segments and generate sampling points.

Usage
-----
Run from the command line:

    python 01_fetch_osm_roads.py \
        --lat 42.539 \
        --lon -71.048 \
        --radius 5000 \
        --highways motor,primary,secondary,tertiary,residential \
        --output data/osm/roads.geojson

Parameters
----------
--lat, --lon:
    Latitude and longitude of the centre of the search area (in decimal
    degrees).
--radius:
    Radius in metres.  Overpass interprets this radius as a circle
    centred on the provided coordinates.  The default is 5000 (5 km).
--highways:
    Comma‑separated list of OSM highway tags to include.  Defaults to
    ``motorway,primary,secondary,tertiary,residential``.  See
    https://wiki.openstreetmap.org/wiki/Key:highway for the full list.
--endpoint:
    Optional Overpass endpoint.  Defaults to the official public server
    (https://overpass-api.de/api/interpreter).  You can point this to
    your own instance if you have one.
--output:
    Path where the resulting GeoJSON should be written.  Intermediate
    directories will be created automatically.

Limitations
-----------
This script must be run with an active internet connection to reach the
Overpass API.  In environments without internet access (like this
exercise), the code will simply illustrate how to compose and send the
query; it cannot fetch real data.  See the project README for details on
configuring your own Overpass instance for offline operation.
"""

import argparse
import json
import os
from typing import List

import requests


def build_overpass_query(lat: float, lon: float, radius: int, highways: List[str]) -> str:
    """Construct an Overpass QL query for the given parameters.

    The query searches for ways (roads) with the specified highway tags within a
    given radius of the centre point and outputs their geometries.

    Parameters
    ----------
    lat, lon: float
        Centre point in decimal degrees.
    radius: int
        Radius in metres.
    highways: list of str
        List of highway tags to include.

    Returns
    -------
    str
        A complete Overpass QL query string.
    """
    # Build the highway filter part of the query.  Each tag gets its own
    # predicate combined with an OR.
    if not highways:
        raise ValueError("At least one highway type must be specified")
    highway_predicates = "".join([
        f"way(around:{radius},{lat},{lon})[highway={h}];"
        for h in highways
    ])
    # Request both the way and its nodes' geometry.  The 'out geom' clause
    # ensures we get coordinate arrays for each way.
    query = (
        "[out:json][timeout:25];"
        f"({highway_predicates});"
        "out geom;"
    )
    return query


def fetch_osm_roads(lat: float, lon: float, radius: int, highways: List[str], endpoint: str) -> dict:
    """Fetch road geometries from Overpass API as a Python dict.

    Parameters
    ----------
    lat, lon: float
        Centre point in decimal degrees.
    radius: int
        Radius in metres.
    highways: list of str
        OSM highway tags to include.
    endpoint: str
        URL of the Overpass API interpreter endpoint.

    Returns
    -------
    dict
        Parsed JSON response from Overpass containing the selected ways.
    """
    query = build_overpass_query(lat, lon, radius, highways)
    response = requests.post(endpoint, data=query)
    response.raise_for_status()
    return response.json()


def convert_to_geojson(overpass_data: dict) -> dict:
    """Convert Overpass JSON to a minimal GeoJSON structure.

    The Overpass API returns data in a custom JSON schema.  This function
    extracts road features with their geometry and properties and wraps
    them in a standard GeoJSON FeatureCollection.

    Parameters
    ----------
    overpass_data: dict
        Raw Overpass output.

    Returns
    -------
    dict
        A GeoJSON FeatureCollection.
    """
    elements = overpass_data.get("elements", [])
    features = []
    for el in elements:
        if el.get("type") != "way":
            continue
        # Each way has a list of coordinates in the 'geometry' field.  The
        # coordinates are dictionaries with 'lat' and 'lon' keys.
        coords = el.get("geometry", [])
        # Skip if no geometry; Overpass sometimes omits it if the way is
        # outside the bounding box or incomplete.
        if not coords:
            continue
        # Convert to [lon, lat] pairs as per GeoJSON specification.
        line = [[pt["lon"], pt["lat"]] for pt in coords]
        properties = {
            "id": el.get("id"),
            "tags": el.get("tags", {}),
        }
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": line,
            },
            "properties": properties,
        }
        features.append(feature)
    return {
        "type": "FeatureCollection",
        "features": features,
    }


def ensure_dir(path: str) -> None:
    """Ensure that the directory for the given file path exists."""
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch OSM roads via Overpass API")
    parser.add_argument("--lat", type=float, required=True, help="Centre latitude")
    parser.add_argument("--lon", type=float, required=True, help="Centre longitude")
    parser.add_argument(
        "--radius",
        type=int,
        default=5000,
        help="Search radius in metres (default: 5000)",
    )
    parser.add_argument(
        "--highways",
        type=str,
        default="motorway,primary,secondary,tertiary,residential",
        help="Comma‑separated list of highway tags to include",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default="https://overpass-api.de/api/interpreter",
        help="Overpass API endpoint",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/osm/roads.geojson",
        help="Path to write GeoJSON output (default: data/osm/roads.geojson)",
    )
    args = parser.parse_args()

    highways = [h.strip() for h in args.highways.split(",") if h.strip()]
    print(f"Querying Overpass for {', '.join(highways)} roads around ({args.lat}, {args.lon}) within {args.radius} m")

    try:
        overpass_data = fetch_osm_roads(args.lat, args.lon, args.radius, highways, args.endpoint)
    except Exception as exc:
        raise SystemExit(f"Failed to fetch data from Overpass: {exc}")

    geojson = convert_to_geojson(overpass_data)
    ensure_dir(args.output)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(geojson, f)
    print(f"Wrote {len(geojson['features'])} road features to {args.output}")


if __name__ == "__main__":
    main()