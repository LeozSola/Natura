"""
Script: 08_view_routes.py
=========================

This module provides a simple visualisation of candidate routes with
scenic scores.  It reads a GeoJSON produced by ``07_route_candidates.py``
and plots the routes on a latitude/longitude axis using matplotlib.
Each route is drawn as a separate line; the scenic score is reported in
the legend.  The resulting plot can be displayed on screen or saved
as a PNG.

Usage
-----

    python 08_view_routes.py \
        --input data/geojson/routes.geojson \
        --output routes.png

Options
-------
--input:
    Path to the GeoJSON file containing routes.
--output:
    Optional path to save the plot as an image.  If not provided,
    the plot will be displayed interactively.

Notes
-----
This script uses only matplotlib (no seaborn) and does not attempt to
overlay a basemap.  For a richer interactive map, consider installing
Folium and modifying this script accordingly.  However, for a minimal
visual sanity check, this plot suffices.
"""

import argparse
import json
import os
from typing import List, Dict

import matplotlib.pyplot as plt


def load_routes(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("features", [])


def plot_routes(routes: List[Dict], output_path: str = None) -> None:
    plt.figure(figsize=(8, 6))
    for i, route in enumerate(routes):
        geom = route.get("geometry", {})
        coords = geom.get("coordinates", [])
        if not coords:
            continue
        lons = [pt[0] for pt in coords]
        lats = [pt[1] for pt in coords]
        props = route.get("properties", {})
        scenic = props.get("scenic_score")
        label = f"Route {i} (scenic: {scenic:.3f})" if scenic is not None else f"Route {i}"
        plt.plot(lons, lats, label=label)
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Candidate routes with scenic scores")
    plt.legend()
    plt.tight_layout()
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        plt.savefig(output_path)
        print(f"Plot saved to {output_path}")
    else:
        plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot scenic routes")
    parser.add_argument("--input", type=str, required=True, help="Routes GeoJSON file")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to save the plot as PNG. If not provided, the plot is shown",
    )
    args = parser.parse_args()

    routes = load_routes(args.input)
    if not routes:
        raise SystemExit("No routes found in the input file")
    plot_routes(routes, args.output)


if __name__ == "__main__":
    main()