param(
  [switch]$SkipPrep  # call as: .\run_mvp.ps1 -SkipPrep
)

$ErrorActionPreference = "Stop"

# ---- config (edit these) ----
$ORIGIN_LAT = 42.5389
$ORIGIN_LON = -71.0481
$DEST_LAT   = 42.6557
$DEST_LON   = -70.6206

$OVERPASS_RADIUS = 25000
$GRID_STEP       = 200
$CACHE_DIR       = "data/cache"
$GRID_HEATMAP_PATH    = "data/mapillary/geojson/scenic_grid_heatmap.geojson"
$HEATMAP_MAX_DISTANCE = 250

# outputs
New-Item -ItemType Directory -Force -Path data/mapillary/osm,data/mapillary/im_meta,data/mapillary/images,data/mapillary/scores,data/mapillary/geojson,data/geojson,outputs | Out-Null

if (-not $SkipPrep) {
    # 2b) Uniform grid samples for imagery coverage
    python 02_grid_samples.py `
      --center-lat $ORIGIN_LAT `
      --center-lon $ORIGIN_LON `
      --radius $OVERPASS_RADIUS `
      --step $GRID_STEP `
      --output data/mapillary/osm/grid_samples.geojson

    if (-not $env:MAPILLARY_TOKEN) {
      Write-Error "MAPILLARY_TOKEN is not set. Export it before running this script."
      exit 1
    }

    # 3) Mapillary metadata (reads $env:MAPILLARY_TOKEN if set)
    python 03_mapillary_metadata.py `
      --input data/mapillary/osm/grid_samples.geojson `
      --cache-dir $CACHE_DIR `
      --output data/mapillary/im_meta/mapillary_grid.csv

    # 4) Download Mapillary thumbnails
    python 04_mapillary_images.py `
      --input data/mapillary/im_meta/mapillary_grid.csv `
      --output-dir data/mapillary/images `
      --limit 1000
}

# 5) Image scenic features
python 05_scenic_model.py `
  --images-dir data/mapillary/images `
  --metadata data/mapillary/im_meta/mapillary_grid.csv `
  --output data/mapillary/scores/image_scores.csv

# 6) Grid scenic scores + heatmap
python 06_grid_scores.py `
  --samples data/mapillary/osm/grid_samples.geojson `
  --metadata data/mapillary/im_meta/mapillary_grid.csv `
  --image-scores data/mapillary/scores/image_scores.csv `
  --heatmap-output $GRID_HEATMAP_PATH `
  --output data/mapillary/geojson/grid_scored.geojson

# 7) Routes (OSRM)
python 07_route_candidates.py `
  --origin-lat $ORIGIN_LAT `
  --origin-lon $ORIGIN_LON `
  --dest-lat $DEST_LAT `
  --dest-lon $DEST_LON `
  --heatmap $GRID_HEATMAP_PATH `
  --max-heatmap-distance $HEATMAP_MAX_DISTANCE `
  --endpoint "https://router.project-osrm.org/route/v1/driving" `
  --output data/geojson/routes.geojson

# 8) View on OSM basemap -> /outputs/routes.html + search circle
python 08_view_routes.py `
  --input data/geojson/routes.geojson `
  --output outputs/routes.html `
  --center-lat $ORIGIN_LAT `
  --center-lon $ORIGIN_LON `
  --radius $OVERPASS_RADIUS `
  --heatmap $GRID_HEATMAP_PATH `
  --source mapillary

Write-Host "Done. Open outputs/routes.html."
