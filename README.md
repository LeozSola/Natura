# Scenic Route Planner MVP

This repository contains a minimal, offline‑friendly prototype for
exploring scenic routes between two locations.  It follows the plan
outlined previously: rather than relying on Google’s closed APIs, it
leverages **OpenStreetMap** for road geometry, **Mapillary** for
street‑level imagery, and simple heuristics to estimate the scenic
value of each road segment.  The pipeline is divided into small scripts
so that you can inspect and run each step independently.

> **Disclaimer:** None of these scripts will function without an
> internet connection and valid API tokens for Overpass (OSM) and
> Mapillary.  The code is provided as a working example and a starting
> point for your own experimentation.


## Directory structure

```
scenic_mvp/
├── 01_fetch_osm_roads.py      # fetch OSM roads via Overpass
├── 02_densify_roadpoints.py   # generate sample points along roads
├── 03_mapillary_metadata.py   # find nearest Mapillary image for each sample
├── 04_mapillary_images.py     # download thumbnail images
├── 05_scenic_model.py         # compute heuristic scenicness features
├── 06_edge_scores.py          # aggregate scenic scores per road
├── 07_route_candidates.py     # request OSRM routes and score them
├── 08_view_routes.py          # plot candidate routes with scenic scores
└── README.md                  # this document
```

Intermediate and output files are written into a `data/` directory at
the project root by default.  You can override these paths via
command‑line arguments.


## Installation and dependencies

The scripts are intentionally lightweight and avoid heavy GIS libraries
like *shapely* or *geopandas*.  The following Python packages are
required:

- `requests` – for HTTP requests
- `numpy` and `Pillow` (PIL) – for image processing
- `matplotlib` – for plotting routes

If you wish to display routes on an interactive map, consider
installing `folium` or running your own tile server; however, this is
outside the scope of the MVP.

You can install the dependencies with pip:

```bash
pip install requests numpy Pillow matplotlib
```


## Step‑by‑step pipeline

The pipeline is designed to be executed sequentially.  Each step
produces files consumed by the next.  The typical workflow is as
follows:

### 1. Fetch roads from OSM

```
python scenic_mvp/01_fetch_osm_roads.py \
  --lat 42.539 --lon -71.048 \
  --radius 5000 \
  --highways motor,primary,secondary,tertiary,residential \
  --output data/osm/roads.geojson
```

This script contacts the Overpass API to retrieve all road segments
matching the specified highway types within a radius (in metres) of
the centre point.  The result is stored as `roads.geojson`.

### 2. Densify road segments

```
python scenic_mvp/02_densify_roadpoints.py \
  --input data/osm/roads.geojson \
  --step 100 \
  --output data/osm/samples.geojson
```

The densify step takes each road polyline and samples points along it
every `step` metres.  For each sample point it also records the
bearing (direction) of travel.  The output `samples.geojson` will be
used to query imagery services.

### 3. Discover Mapillary images

```
python scenic_mvp/03_mapillary_metadata.py \
  --input data/osm/samples.geojson \
  --token $MAPILLARY_TOKEN \
  --limit 500 \
  --output data/im_meta/mapillary_samples.csv
```

For each sample point, this script calls the Mapillary Graph API to
retrieve the nearest image.  The `sample_index` column in the CSV
corresponds to the index of the sample feature in `samples.geojson`.
Specify `--limit` during testing to process only the first N samples.

### 4. Download thumbnails

```
python scenic_mvp/04_mapillary_images.py \
  --input data/im_meta/mapillary_samples.csv \
  --token $MAPILLARY_TOKEN \
  --limit 500 \
  --output-dir data/images/mapillary
```

Using the image IDs recorded in the metadata, this script fetches a
1024‑px wide thumbnail for each image and stores it under the
specified directory.  Existing files are skipped to avoid duplicate
downloads.

### 5. Compute heuristic scenicness features

```
python scenic_mvp/05_scenic_model.py \
  --images-dir data/images/mapillary \
  --metadata data/im_meta/mapillary_samples.csv \
  --output data/scores/images.csv
```

This step processes each downloaded image and computes four
heuristics: vegetation ratio, sky ratio, water ratio and colourfulness.
These are combined into an overall `scenic_score`.  The output
`images.csv` contains one row per image with its coordinates and
features.

### 6. Aggregate scenic scores to road segments

```
python scenic_mvp/06_edge_scores.py \
  --roads data/osm/roads.geojson \
  --samples data/osm/samples.geojson \
  --metadata data/im_meta/mapillary_samples.csv \
  --image-scores data/scores/images.csv \
  --output data/geojson/edges_scored.geojson
```

This script links sample points back to their originating road
segments and averages the `scenic_score` over all samples on that
segment.  If a segment has no samples (for example, no nearby
images), its score is `null` and its `n_samples` property is zero.

### 7. Request routes and evaluate scenicness

```
python scenic_mvp/07_route_candidates.py \
  --origin-lat 42.539 --origin-lon -71.048 \
  --dest-lat 42.491 --dest-lon -71.063 \
  --edge-scores data/geojson/edges_scored.geojson \
  --endpoint https://router.project-osrm.org \
  --step 100 \
  --output data/geojson/routes.geojson
```

The routing step queries the OSRM API for alternative routes between
the origin and destination.  It samples points along each route every
`step` metres and looks up the scenic score of the nearest road
segment using the results of step 6.  The mean of these values is
reported as the route’s `scenic_score` property.  The resulting
`routes.geojson` contains a feature for each alternative with the OSRM
duration, distance and the computed scenic score.

> **OSRM note:** The public OSRM server is provided for demonstration
> purposes only and may rate‑limit or reject your requests.  For
> reliable performance you should run your own OSRM instance using
> the same OSM extract you used to fetch roads.

### 8. Plot the candidate routes

```
python scenic_mvp/08_view_routes.py \
  --input data/geojson/routes.geojson \
  --output routes.png
```

Finally, visualise the alternative routes and their scenic scores on
a simple lat/lon plot.  Without a basemap this serves purely as a
sanity check.  For interactive maps or background tiles you can use
libraries such as Folium or MapLibre once the core pipeline is
working.


## Extending this prototype

This MVP deliberately uses simple heuristics and a naive nearest
neighbour search.  To improve performance and quality you may consider
the following:

- **Replace the heuristic scenic model** with a proper vision model
  (e.g. CLIP + aesthetics head) and semantic segmentation to measure
  sky/water/vegetation more accurately.
- **Use a spatial index** (e.g. an R‑tree) to speed up nearest
  neighbour queries when matching route samples to road segments.
- **Support user preferences** by weighting different scenic attributes
  (water vs greenery vs vistas) and implementing multi‑objective
  routing (e.g. via k‑shortest paths or scalarisation).
- **Integrate additional data sources** such as official scenic
  byways, elevation profiles and OpenStreetMap `scenic=yes` tags to
  enrich the scoring.
- **Comply with API terms** – remember that storing and deriving data
  from Google imagery is prohibited.  This pipeline uses only
  open‑licensed imagery from Mapillary, which requires attribution
  (see Mapillary’s licence for details).


## Troubleshooting

The scripts will raise exceptions when required inputs are missing or
API requests fail.  Common issues include:

- **Missing API tokens:** Steps 3 and 4 require a Mapillary access
  token.  Obtain one from <https://www.mapillary.com/developer/api-documentation/>
  and supply it via `--token` or the `MAPILLARY_TOKEN` environment
  variable.
- **Network access:** Overpass, Mapillary and OSRM calls all require
  outbound internet connectivity.  In offline environments you must
  run your own Overpass/OSRM servers and cache Mapillary images.
- **Large data volumes:** Sampling roads at very fine intervals will
  generate many points and API calls.  Start with a coarse step
  (e.g. 200–300 m) and adjust once you’ve verified the pipeline.


## Licence

This code is provided for educational purposes.  Be sure to respect
the licences of any external data sources you use (OpenStreetMap
contributors, Mapillary, etc.) when deploying or sharing your own
derived datasets.