"""
Script: 08_view_routes.py
=========================

Visualize candidate routes on a normal (OpenStreetMap) basemap and draw a
search circle centered on the origin (same radius as the Overpass query).

Usage
-----
python scenic_mvp/08_view_routes.py \
  --input data/geojson/routes.geojson \
  --output outputs/routes.html \
  --center-lat 42.5389 \
  --center-lon -71.0481 \
  --radius 25000

Notes
-----
- Output is an interactive HTML map (Folium + OSM tiles).
- If --output is omitted, saves to routes_map.html in the CWD.
"""

import argparse
import json
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import folium
from folium.plugins import HeatMap
from branca.element import Element

from natura.heatmap import load_heatmap


def load_routes(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("features", [])


def ensure_html_path(path: Optional[str]) -> str:
    """Ensure output filename ends with .html; default if None."""
    if not path:
        return "routes_map.html"
    root, ext = os.path.splitext(path)
    return path if ext.lower() == ".html" else f"{path}.html"


def plot_routes(
    routes: List[Dict],
    output_path: Optional[str] = None,
    center_lat: Optional[float] = None,
    center_lon: Optional[float] = None,
    radius_m: Optional[int] = None,
    heatmap_points: Optional[List[Tuple[float, float, float]]] = None,
    source: str = "mapillary",
    scenic_weight: float = 0.9,
    waypoint_count: int = 6,
    waypoint_radius: float = 8000.0,
    waypoint_min_distance: float = 2000.0,
    waypoint_min_separation: float = 1500.0,
) -> None:
    if not routes:
        raise SystemExit("No routes found")

    # Center: use provided origin or fall back to first route's first coord
    first_coords = routes[0]["geometry"]["coordinates"]
    default_lat = first_coords[0][1]
    default_lon = first_coords[0][0]
    lat0 = center_lat if center_lat is not None else default_lat
    lon0 = center_lon if center_lon is not None else default_lon

    # Build map (normal street basemap)
    m = folium.Map(location=[lat0, lon0], zoom_start=12, tiles="OpenStreetMap")

    coverage_label = "Data coverage bounds"
    if source:
        coverage_label = f"{source.capitalize()} coverage bounds"

    # Optional: draw the search circle
    if radius_m and radius_m > 0:
        folium.Circle(
            location=[lat0, lon0],
            radius=radius_m,
            color="red",
            weight=2,
            fill=True,
            fill_opacity=0.05,
            tooltip=f"Search radius: {radius_m/1000:.1f} km",
        ).add_to(m)
        # Mark the center point
        folium.CircleMarker(
            location=[lat0, lon0],
            radius=4,
            color="red",
            fill=True,
            fill_opacity=1.0,
            tooltip="Search center",
        ).add_to(m)

    bounds = None
    # Optional heatmap overlay
    if heatmap_points:
        scores = [score for _, _, score in heatmap_points if score is not None]
        if scores:
            lats = [lat for lat, _, _ in heatmap_points]
            lons = [lon for _, lon, _ in heatmap_points]
            bounds = [(min(lats), min(lons)), (max(lats), max(lons))]
            folium.Rectangle(
                bounds=bounds,
                color="#1f6feb",
                weight=2,
                fill=True,
                fill_opacity=0.06,
                tooltip=coverage_label,
            ).add_to(m)

            min_score = min(scores)
            max_score = max(scores)
            scale = max(max_score - min_score, 1e-6)
            heatmap_data = [
                [lat, lon, (score - min_score) / scale] for lat, lon, score in heatmap_points
            ]
            HeatMap(
                heatmap_data,
                name="Scenic heatmap",
                radius=18,
                blur=28,
                min_opacity=0.2,
                max_zoom=15,
            ).add_to(m)

            point_step = max(1, len(heatmap_points) // 4000)
            point_group = folium.FeatureGroup(name="Scenic sample points", show=False)
            for idx, (lat, lon, _score) in enumerate(heatmap_points):
                if idx % point_step != 0:
                    continue
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=4,
                    color="#d73a49",
                    fill=True,
                    fill_opacity=0.75,
                    opacity=0.75,
                ).add_to(point_group)
            point_group.add_to(m)
            sample_layer_name = point_group.get_name()
        else:
            sample_layer_name = None
    else:
        sample_layer_name = None

    # Draw each route as an interactive polyline
    for i, route in enumerate(routes):
        geom = route.get("geometry", {})
        coords = geom.get("coordinates", [])
        if not coords:
            continue
        latlons = [(pt[1], pt[0]) for pt in coords]  # folium expects [lat, lon]
        props = route.get("properties", {})
        scenic = props.get("scenic_score")
        effective = props.get("scenic_effective_score")
        coverage = props.get("scenic_coverage")
        rank = props.get("scenic_rank")
        combined = props.get("combined_score")
        duration_ratio = props.get("duration_ratio")
        variant = props.get("route_variant")
        waypoint_score = props.get("waypoint_score")
        road_weighting = props.get("road_weighting")
        details = []
        if variant:
            details.append(f"variant {variant}")
        if road_weighting:
            details.append("road-weighted")
        if scenic is not None:
            details.append(f"scenic {scenic:.3f}")
        if effective is not None:
            details.append(f"effective {effective:.3f}")
        if combined is not None:
            details.append(f"combined {combined:.3f}")
        if duration_ratio is not None:
            details.append(f"dur x{duration_ratio:.2f}")
        if coverage is not None:
            details.append(f"coverage {coverage:.0%}")
        if waypoint_score is not None:
            details.append(f"wp {waypoint_score:.3f}")
        if rank is not None:
            details.append(f"rank {int(rank)}")
        label = f"Route {i}" if not details else f"Route {i} ({', '.join(details)})"
        color = "#1f6feb"
        weight = 4
        if rank == 1:
            color = "#2ea043"
            weight = 5
        elif rank == 2:
            color = "#f2a900"
            weight = 5
        folium.PolyLine(latlons, color=color, weight=weight, opacity=0.85, tooltip=label).add_to(m)

    # Interactive origin/destination controls
    origin_lat = lat0
    origin_lon = lon0
    dest_lat = routes[0]["geometry"]["coordinates"][-1][1]
    dest_lon = routes[0]["geometry"]["coordinates"][-1][0]
    map_name = m.get_name()

    m.get_root().header.add_child(Element(
        "<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600&display=swap\">"
    ))

    panel_html = """
    <div id="route-panel" style="
        position: fixed;
        top: 12px;
        right: 12px;
        z-index: 9999;
        background: rgba(255,255,255,0.95);
        padding: 10px 12px;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.15);
        font-family: 'Space Grotesk', 'Segoe UI', sans-serif;
        width: 280px;
    ">
      <div style="font-weight: 600; margin-bottom: 6px;">Scenic Route Rerun</div>
      <div style="font-size: 12px; color: #333;">
        Drag markers or click the map to set origin/destination. Then rerun the local script.
      </div>
      <div style="margin-top: 8px;">
        <label style="font-size: 12px;">Origin (lat, lon)</label>
        <div style="display: flex; gap: 6px; margin-top: 4px;">
          <input id="origin-lat" style="width: 120px;" />
          <input id="origin-lon" style="width: 120px;" />
        </div>
        <button id="pick-origin" style="margin-top: 6px;">Pick origin</button>
      </div>
      <div style="margin-top: 8px;">
        <label style="font-size: 12px;">Destination (lat, lon)</label>
        <div style="display: flex; gap: 6px; margin-top: 4px;">
          <input id="dest-lat" style="width: 120px;" />
          <input id="dest-lon" style="width: 120px;" />
        </div>
        <button id="pick-dest" style="margin-top: 6px;">Pick destination</button>
      </div>
      <div style="margin-top: 8px;">
        <label style="font-size: 12px;">Scenic weight: <span id="weight-value"></span></label>
        <input id="weight-slider" type="range" min="0" max="100" step="1" style="width: 100%;" />
      </div>
      <div style="margin-top: 8px; font-size: 12px; color: #555;">Command:</div>
      <pre id="route-cmd" style="white-space: pre-wrap; font-size: 11px; background: #f4f4f4; padding: 6px;"></pre>
      <button id="copy-cmd">Copy command</button>
      <button id="toggle-samples" style="margin-top: 6px;">Toggle sample points</button>
      <button id="rerun-btn" style="margin-top: 6px;">Rerun routes</button>
      <div id="rerun-status" style="margin-top: 6px; font-size: 11px; color: #666;"></div>
      <div id="bounds-status" style="margin-top: 6px; font-size: 11px; color: #666;"></div>
    </div>
    """
    m.get_root().html.add_child(Element(panel_html))

    bounds_js = "null"
    if bounds:
        bounds_js = f"{{minLat: {bounds[0][0]}, minLon: {bounds[0][1]}, maxLat: {bounds[1][0]}, maxLon: {bounds[1][1]}}}"

    sample_layer_js = "null"
    if sample_layer_name:
        sample_layer_js = f"window['{sample_layer_name}']"

    coverage_label_js = json.dumps(coverage_label)
    waypoint_count_js = int(waypoint_count)
    waypoint_radius_js = float(waypoint_radius)
    waypoint_min_distance_js = float(waypoint_min_distance)
    waypoint_min_separation_js = float(waypoint_min_separation)

    weight_value = max(0.0, min(1.0, scenic_weight))
    panel_js = f"""
    (function() {{
      function initPanel() {{
        var map = window['{map_name}'];
        if (!map) {{
          setTimeout(initPanel, 50);
          return;
        }}
        var picking = 'origin';
        var originMarker = L.marker([{origin_lat}, {origin_lon}], {{draggable: true}}).addTo(map);
        var destMarker = L.marker([{dest_lat}, {dest_lon}], {{draggable: true}}).addTo(map);
        var bounds = {bounds_js};
        var sampleLayer = {sample_layer_js};
        var coverageLabel = {coverage_label_js};
        var weightSlider = document.getElementById('weight-slider');
        var weightValue = document.getElementById('weight-value');
        var waypointCount = {waypoint_count_js};
        var waypointRadius = {waypoint_radius_js};
        var waypointMinDistance = {waypoint_min_distance_js};
        var waypointMinSeparation = {waypoint_min_separation_js};
        weightSlider.value = Math.round({weight_value} * 100);

        function setInputs() {{
          var scenicWeight = (parseInt(weightSlider.value, 10) || 0) / 100.0;
          weightValue.textContent = scenicWeight.toFixed(2);
          document.getElementById('origin-lat').value = originMarker.getLatLng().lat.toFixed(6);
          document.getElementById('origin-lon').value = originMarker.getLatLng().lng.toFixed(6);
          document.getElementById('dest-lat').value = destMarker.getLatLng().lat.toFixed(6);
          document.getElementById('dest-lon').value = destMarker.getLatLng().lng.toFixed(6);
          var cmd = '.\\\\run_routes.ps1 -OriginLat ' + originMarker.getLatLng().lat.toFixed(6) +
                    ' -OriginLon ' + originMarker.getLatLng().lng.toFixed(6) +
                    ' -DestLat ' + destMarker.getLatLng().lat.toFixed(6) +
                    ' -DestLon ' + destMarker.getLatLng().lng.toFixed(6) +
                    ' -Source {source}' +
                    ' -ScenicWeight ' + scenicWeight.toFixed(2) +
                    ' -MaxDurationRatio 1.7' +
                    ' -WaypointCount ' + waypointCount +
                    ' -WaypointRadius ' + waypointRadius +
                    ' -WaypointMinDistance ' + waypointMinDistance +
                    ' -WaypointMinSeparation ' + waypointMinSeparation;
          document.getElementById('route-cmd').textContent = cmd;
          var status = document.getElementById('bounds-status');
          if (bounds) {{
            var o = originMarker.getLatLng();
            var d = destMarker.getLatLng();
            var oInside = o.lat >= bounds.minLat && o.lat <= bounds.maxLat && o.lng >= bounds.minLon && o.lng <= bounds.maxLon;
            var dInside = d.lat >= bounds.minLat && d.lat <= bounds.maxLat && d.lng >= bounds.minLon && d.lng <= bounds.maxLon;
            if (oInside && dInside) {{
              status.textContent = 'Both points are inside ' + coverageLabel + '.';
            }} else {{
              status.textContent = 'One or more points are outside ' + coverageLabel + '.';
            }}
          }} else {{
            status.textContent = 'Coverage bounds unavailable.';
          }}
        }}

        function updateMarkerFromInputs() {{
          var oLat = parseFloat(document.getElementById('origin-lat').value);
          var oLon = parseFloat(document.getElementById('origin-lon').value);
          var dLat = parseFloat(document.getElementById('dest-lat').value);
          var dLon = parseFloat(document.getElementById('dest-lon').value);
          if (!isNaN(oLat) && !isNaN(oLon)) {{ originMarker.setLatLng([oLat, oLon]); }}
          if (!isNaN(dLat) && !isNaN(dLon)) {{ destMarker.setLatLng([dLat, dLon]); }}
          setInputs();
        }}

        document.getElementById('pick-origin').addEventListener('click', function() {{
          picking = 'origin';
        }});
        document.getElementById('pick-dest').addEventListener('click', function() {{
          picking = 'dest';
        }});
        document.getElementById('origin-lat').addEventListener('change', updateMarkerFromInputs);
        document.getElementById('origin-lon').addEventListener('change', updateMarkerFromInputs);
        document.getElementById('dest-lat').addEventListener('change', updateMarkerFromInputs);
        document.getElementById('dest-lon').addEventListener('change', updateMarkerFromInputs);
        weightSlider.addEventListener('input', setInputs);

        originMarker.on('dragend', setInputs);
        destMarker.on('dragend', setInputs);

        map.on('click', function(e) {{
          if (picking === 'origin') {{
            originMarker.setLatLng(e.latlng);
          }} else {{
            destMarker.setLatLng(e.latlng);
          }}
          setInputs();
        }});

        document.getElementById('copy-cmd').addEventListener('click', function() {{
          var cmd = document.getElementById('route-cmd').textContent;
          if (navigator.clipboard && navigator.clipboard.writeText) {{
            navigator.clipboard.writeText(cmd);
          }}
        }});

        var toggleBtn = document.getElementById('toggle-samples');
        if (sampleLayer) {{
          toggleBtn.addEventListener('click', function() {{
            if (map.hasLayer(sampleLayer)) {{
              map.removeLayer(sampleLayer);
              toggleBtn.textContent = 'Show sample points';
            }} else {{
              map.addLayer(sampleLayer);
              toggleBtn.textContent = 'Hide sample points';
            }}
          }});
          if (map.hasLayer(sampleLayer)) {{
            toggleBtn.textContent = 'Hide sample points';
          }} else {{
            toggleBtn.textContent = 'Show sample points';
          }}
        }} else {{
          toggleBtn.textContent = 'Sample points unavailable';
          toggleBtn.disabled = true;
        }}

        document.getElementById('rerun-btn').addEventListener('click', function() {{
          var status = document.getElementById('rerun-status');
          status.textContent = 'Rerunning routes...';
          var o = originMarker.getLatLng();
          var d = destMarker.getLatLng();
          var scenicWeight = (parseInt(weightSlider.value, 10) || 0) / 100.0;
          var url = 'http://127.0.0.1:8787/rerun' +
            '?origin_lat=' + encodeURIComponent(o.lat.toFixed(6)) +
            '&origin_lon=' + encodeURIComponent(o.lng.toFixed(6)) +
            '&dest_lat=' + encodeURIComponent(d.lat.toFixed(6)) +
            '&dest_lon=' + encodeURIComponent(d.lng.toFixed(6)) +
            '&source={source}' +
            '&scenic_weight=' + encodeURIComponent(scenicWeight.toFixed(2)) +
            '&max_duration_ratio=1.7' +
            '&waypoint_count=' + encodeURIComponent(waypointCount) +
            '&waypoint_radius=' + encodeURIComponent(waypointRadius) +
            '&waypoint_min_distance=' + encodeURIComponent(waypointMinDistance) +
            '&waypoint_min_separation=' + encodeURIComponent(waypointMinSeparation);
          fetch(url).then(function(resp) {{
            if (!resp.ok) {{
              throw new Error('HTTP ' + resp.status);
            }}
            return resp.json();
          }}).then(function(data) {{
            if (data.ok) {{
              status.textContent = 'Routes updated. Refresh this page.';
            }} else {{
              status.textContent = 'Rerun failed: ' + (data.error || 'unknown error');
            }}
          }}).catch(function(err) {{
            status.textContent = 'Rerun failed: ' + err.message + ' (is the local server running?)';
          }});
        }});

        setInputs();
      }}

      setTimeout(initPanel, 0);
    }})();"""
    m.get_root().script.add_child(Element(panel_js))

    folium.LayerControl().add_to(m)

    # Save
    out_html = ensure_html_path(output_path)
    out_dir = os.path.dirname(out_html)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    m.save(out_html)
    print(f"Interactive map saved to {out_html}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot scenic routes on OSM and draw search circle")
    parser.add_argument("--input", type=str, required=True, help="Routes GeoJSON file")
    parser.add_argument("--output", type=str, default="outputs/routes.html", help="Output HTML path")
    parser.add_argument("--center-lat", type=float, required=False, help="Center latitude (origin)")
    parser.add_argument("--center-lon", type=float, required=False, help="Center longitude (origin)")
    parser.add_argument("--radius", type=int, required=False, help="Search radius in meters")
    parser.add_argument(
        "--heatmap",
        type=str,
        required=False,
        help="Optional scenic heatmap GeoJSON (from step 6) to overlay",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="mapillary",
        help="Data source name for rerun command (default: mapillary)",
    )
    parser.add_argument(
        "--scenic-weight",
        type=float,
        default=0.7,
        help="Initial scenic weight for the UI slider (0-1, default: 0.7)",
    )
    parser.add_argument(
        "--waypoint-count",
        type=int,
        default=6,
        help="Number of waypoint routes to request (default: 6)",
    )
    parser.add_argument(
        "--waypoint-radius",
        type=float,
        default=8000.0,
        help="Waypoint selection radius in meters (default: 8000)",
    )
    parser.add_argument(
        "--waypoint-min-distance",
        type=float,
        default=2000.0,
        help="Minimum distance from origin/destination for waypoints (default: 2000)",
    )
    parser.add_argument(
        "--waypoint-min-separation",
        type=float,
        default=1500.0,
        help="Minimum separation between waypoint candidates (default: 1500)",
    )
    args = parser.parse_args()

    routes = load_routes(args.input)
    if not routes:
        raise SystemExit("No routes found in the input file")

    heatmap_points = None
    if args.heatmap:
        heatmap_path = Path(args.heatmap)
        if heatmap_path.exists():
            heatmap_points = load_heatmap(heatmap_path)
        else:
            print(f"Heatmap file {args.heatmap} not found; continuing without heatmap overlay.")

    plot_routes(
        routes,
        output_path=args.output,
        center_lat=args.center_lat,
        center_lon=args.center_lon,
        radius_m=args.radius,
        heatmap_points=heatmap_points,
        source=args.source,
        scenic_weight=args.scenic_weight,
        waypoint_count=args.waypoint_count,
        waypoint_radius=args.waypoint_radius,
        waypoint_min_distance=args.waypoint_min_distance,
        waypoint_min_separation=args.waypoint_min_separation,
    )


if __name__ == "__main__":
    main()
