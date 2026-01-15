param(
  [int]$Limit = 1000
)

$ErrorActionPreference = "Stop"

# ---- config (edit these) ----
$CENTER_LAT = 42.5389
$CENTER_LON = -71.0481
$RADIUS_M   = 25000
$GRID_STEP  = 200
$CACHE_DIR  = "data/cache"

# outputs
New-Item -ItemType Directory -Force -Path data/osm,data/im_meta,data/images,data/scores,data/geojson | Out-Null

python 02_grid_samples.py `
  --center-lat $CENTER_LAT `
  --center-lon $CENTER_LON `
  --radius $RADIUS_M `
  --step $GRID_STEP `
  --output data/osm/grid_samples.geojson
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $env:MAPILLARY_TOKEN) {
  Write-Error "MAPILLARY_TOKEN is not set. Export it before running this script."
  exit 1
}

python 03_mapillary_metadata.py `
  --input data/osm/grid_samples.geojson `
  --cache-dir $CACHE_DIR `
  --output data/im_meta/mapillary_grid.csv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python 04_mapillary_images.py `
  --input data/im_meta/mapillary_grid.csv `
  --output-dir data/images/mapillary `
  --limit $Limit
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python 05_scenic_model.py `
  --images-dir data/images/mapillary `
  --metadata data/im_meta/mapillary_grid.csv `
  --output data/scores/image_scores.csv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python 06_grid_scores.py `
  --samples data/osm/grid_samples.geojson `
  --metadata data/im_meta/mapillary_grid.csv `
  --image-scores data/scores/image_scores.csv `
  --heatmap-output data/geojson/scenic_grid_heatmap.geojson `
  --output data/geojson/grid_scored.geojson
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Grid data prepared. Scenic heatmap: data/geojson/scenic_grid_heatmap.geojson"
