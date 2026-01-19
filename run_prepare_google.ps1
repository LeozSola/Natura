param(
  [int]$Limit = 0,
  [switch]$TestGrid
)

$ErrorActionPreference = "Stop"

# ---- config (edit these) ----
$CENTER_LAT = 42.5389
$CENTER_LON = -71.0481
$RADIUS_M   = 25000
$GRID_STEP  = 200
$CACHE_DIR  = "data/cache"
$IMAGE_SIZE = "640x640"

# outputs
New-Item -ItemType Directory -Force -Path data/google/osm,data/google/im_meta,data/google/images,data/google/scores,data/google/geojson | Out-Null

$TEST_ARG = @()
if ($TestGrid) { $TEST_ARG = @("--test-grid") }

python 02_grid_samples.py `
  --center-lat $CENTER_LAT `
  --center-lon $CENTER_LON `
  --radius $RADIUS_M `
  --step $GRID_STEP `
  @TEST_ARG `
  --output data/google/osm/grid_samples.geojson
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $env:GOOGLE_MAPS_API_KEY) {
  Write-Error "GOOGLE_MAPS_API_KEY is not set. Export it before running this script."
  exit 1
}

$LIMIT_ARG = @()
if ($Limit -gt 0) { $LIMIT_ARG = @("--limit", $Limit) }

python 03_google_streetview.py `
  --input data/google/osm/grid_samples.geojson `
  --key $env:GOOGLE_MAPS_API_KEY `
  --cache-dir $CACHE_DIR `
  --size $IMAGE_SIZE `
  @LIMIT_ARG `
  --output data/google/im_meta/google_grid.csv `
  --images-dir data/google/images
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python 05_scenic_model.py `
  --images-dir data/google/images `
  --metadata data/google/im_meta/google_grid.csv `
  --output data/google/scores/image_scores.csv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python 06_grid_scores.py `
  --samples data/google/osm/grid_samples.geojson `
  --metadata data/google/im_meta/google_grid.csv `
  --image-scores data/google/scores/image_scores.csv `
  --heatmap-output data/google/geojson/scenic_grid_heatmap.geojson `
  --output data/google/geojson/grid_scored.geojson
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Google Street View data prepared. Scenic heatmap: data/google/geojson/scenic_grid_heatmap.geojson"
