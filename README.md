# Scenic Route Planner MVP

This repository contains a minimal, offline-friendly prototype for
exploring scenic routes between two locations. Rather than relying on
closed APIs, it leverages OpenStreetMap for road geometry, Mapillary for
street-level imagery, and simple heuristics to estimate the scenic value
of each area. The pipeline is divided into small scripts so you can run
and inspect each step independently.

> Disclaimer: None of these scripts will function without an internet
> connection and valid API tokens for Overpass (OSM) and Mapillary. The
> code is provided as a working example and a starting point for your
> own experimentation.

## Directory structure

```
.
|-- 01_fetch_osm_roads.py      # fetch OSM roads via Overpass (optional)
|-- 02_densify_roadpoints.py   # generate sample points along roads (legacy)
|-- 02_grid_samples.py         # generate uniform grid samples (recommended)
|-- 03_mapillary_metadata.py   # find nearest Mapillary image for each sample
|-- 04_mapillary_images.py     # download thumbnail images
|-- 05_scenic_model.py         # compute heuristic scenicness features
|-- 06_edge_scores.py          # aggregate scenic scores per road and emit heatmap (optional)
|-- 06_grid_scores.py          # aggregate scenic scores per grid and emit heatmap
|-- 07_route_candidates.py     # request OSRM routes and score them using heatmap data
|-- 08_view_routes.py          # plot candidate routes with scenic scores & heatmap overlay
|-- natura/
|   |-- __init__.py            # shared package initializer
|   |-- cache.py               # disk caching helpers
|   |-- geo.py                 # geographic utility helpers
|   `-- heatmap.py             # heatmap sampling + I/O helpers
|-- README.md                  # this document
|-- run_mvp.ps1                # helper script for the full pipeline
```

Intermediate and output files are written into a `data/` directory at
the project root by default. You can override these paths via
command-line arguments.

## Installation and dependencies

The scripts are intentionally lightweight and avoid heavy GIS libraries
like shapely or geopandas. The following Python packages are required:

- `requests` for HTTP requests
- `numpy` and `Pillow` (PIL) for image processing
- `matplotlib` for plotting routes

If you wish to display routes on an interactive map, consider installing
`folium` or running your own tile server; however, this is outside the
scope of the MVP.

You can install the dependencies with pip:

```bash
pip install requests numpy Pillow matplotlib
```

## Recommended grid-based pipeline

The grid-based approach creates a uniform lattice of sample points to
reduce coverage bias. This produces a more even scenic surface for
routing.

Quick start scripts:
- `run_prepare_grid.ps1` pulls Mapillary data once for a grid area and writes the scenic heatmap.
- `run_routes.ps1` recomputes routes + HTML from the existing heatmap without re-downloading imagery.

### 1. Build grid samples

```
python 02_grid_samples.py   --center-lat 42.539 --center-lon -71.048   --radius 5000   --step 200   --output data/osm/grid_samples.geojson
```

### 2. Discover Mapillary images

```
python 03_mapillary_metadata.py   --input data/osm/grid_samples.geojson   --token $MAPILLARY_TOKEN   --limit 500   --output data/im_meta/mapillary_grid.csv
```

For each sample point, this script calls the Mapillary Graph API to
retrieve the nearest image. The output includes `image_distance_m`, which
is used to drop overly distant matches downstream.

### 3. Download thumbnails

```
python 04_mapillary_images.py   --input data/im_meta/mapillary_grid.csv   --token $MAPILLARY_TOKEN   --limit 500   --output-dir data/images/mapillary
```

### 4. Compute heuristic scenicness features

```
python 05_scenic_model.py   --images-dir data/images/mapillary   --metadata data/im_meta/mapillary_grid.csv   --output data/scores/image_scores.csv
```

### 5. Build grid scenic heatmap

```
python 06_grid_scores.py   --samples data/osm/grid_samples.geojson   --metadata data/im_meta/mapillary_grid.csv   --image-scores data/scores/image_scores.csv   --heatmap-output data/geojson/scenic_grid_heatmap.geojson   --output data/geojson/grid_scored.geojson
```

### 6. Score route alternatives via scenic heatmap

```
python 07_route_candidates.py   --origin-lat 42.539 --origin-lon -71.048   --dest-lat 42.491 --dest-lon -71.063   --heatmap data/geojson/scenic_grid_heatmap.geojson   --endpoint https://router.project-osrm.org   --output data/geojson/routes.geojson
```

Routes are ranked using a coverage-weighted scenic score
(`scenic_effective_score = scenic_score * scenic_coverage`) so that
routes with sparse coverage are penalized.

### 7. Visualize routes and heatmap

```
python 08_view_routes.py   --input data/geojson/routes.geojson   --heatmap data/geojson/scenic_grid_heatmap.geojson   --output outputs/routes.html
```

## Optional road-based pipeline (legacy)

If you want edge-level scores for debugging or comparison, use the
road-based steps below and then pass `--edge-scores` to
`07_route_candidates.py` as a fallback.

1) Fetch roads from OSM (`01_fetch_osm_roads.py`)
2) Densify road segments (`02_densify_roadpoints.py`)
3) Query Mapillary metadata (`03_mapillary_metadata.py`)
4) Download thumbnails (`04_mapillary_images.py`)
5) Compute scenic features (`05_scenic_model.py`)
6) Aggregate edge scores + heatmap (`06_edge_scores.py`)

## Caching external API calls

Steps 1, 3, and 7 accept `--cache-dir`, `--cache-ttl`, and `--no-cache`
flags that wrap the Overpass, Mapillary, and OSRM requests with a simple
disk cache (`natura.cache.DiskCache`). This avoids re-downloading
identical payloads during iterative development and makes it easier to
work offline once you have captured the raw responses.

## Extending this prototype

This MVP deliberately uses simple heuristics and a naive nearest
neighbour search. To improve performance and quality you may consider:

- Replace the heuristic scenic model with a proper vision model.
- Use a spatial index (e.g. an R-tree) to speed up nearest neighbour
  queries when matching route samples to scenic points.
- Support user preferences by weighting different scenic attributes
  (water vs greenery vs vistas) and implementing multi-objective routing.
- Integrate additional data sources such as elevation profiles and OSM
  `scenic=yes` tags to enrich the scoring.

## Troubleshooting

- Missing API tokens: Steps 3 and 4 require a Mapillary access token.
  Obtain one from https://www.mapillary.com/developer/api-documentation/
  and supply it via `--token` or the `MAPILLARY_TOKEN` environment
  variable.
- Network access: Overpass, Mapillary and OSRM calls all require outbound
  internet connectivity. In offline environments you must run your own
  Overpass/OSRM servers and cache Mapillary images.
- Large data volumes: Sampling with very fine steps will generate many
  points and API calls. Start with a coarse step (e.g. 200-300 m) and
  adjust once you have verified the pipeline.

## Licence

This code is provided for educational purposes. Be sure to respect the
licences of any external data sources you use (OpenStreetMap
contributors, Mapillary, etc.) when deploying or sharing your own
derived datasets.
