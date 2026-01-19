param(
  [double]$OriginLat = 42.5389,
  [double]$OriginLon = -71.0481,
  [double]$DestLat   = 42.700109,
  [double]$DestLon   = -71.159784,
  [string]$Source = "mapillary",
  [string]$Endpoint = "https://router.project-osrm.org/route/v1/driving",
  [string]$HeatmapPath = "",
  [string]$RoutesPath = "data/geojson/routes.geojson",
  [string]$HtmlPath   = "outputs/routes.html"
)

$ErrorActionPreference = "Stop"

if (-not $HeatmapPath) {
  if ($Source -eq "google") {
    $HeatmapPath = "data/google/geojson/scenic_grid_heatmap.geojson"
  } else {
    $HeatmapPath = "data/mapillary/geojson/scenic_grid_heatmap.geojson"
  }
}

if (-not (Test-Path $HeatmapPath)) {
  $fallback = if ($Source -eq "google") {
    "data/google/geojson/scenic_heatmap.geojson"
  } else {
    "data/mapillary/geojson/scenic_heatmap.geojson"
  }
  if (-not (Test-Path $fallback)) {
    $fallback = "data/geojson/scenic_heatmap.geojson"
  }
  if (Test-Path $fallback) {
    $HeatmapPath = $fallback
  } else {
    Write-Error "No heatmap found. Run .\\run_prepare_mapillary.ps1 or .\\run_prepare_google.ps1 first."
    exit 1
  }
}

python 07_route_candidates.py `
  --origin-lat $OriginLat `
  --origin-lon $OriginLon `
  --dest-lat $DestLat `
  --dest-lon $DestLon `
  --heatmap $HeatmapPath `
  --max-heatmap-distance 250 `
  --endpoint $Endpoint `
  --output $RoutesPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python 08_view_routes.py `
  --input $RoutesPath `
  --output $HtmlPath `
  --center-lat $OriginLat `
  --center-lon $OriginLon `
  --radius 25000 `
  --heatmap $HeatmapPath `
  --source $Source
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Routes updated: $HtmlPath"
