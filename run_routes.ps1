param(
  [double]$OriginLat = 42.5389,
  [double]$OriginLon = -71.0481,
  [double]$DestLat   = 42.6557,
  [double]$DestLon   = -70.6206,
  [string]$Endpoint = "https://router.project-osrm.org/route/v1/driving",
  [string]$HeatmapPath = "data/geojson/scenic_grid_heatmap.geojson",
  [string]$RoutesPath = "data/geojson/routes.geojson",
  [string]$HtmlPath   = "outputs/routes.html"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $HeatmapPath)) {
  $fallback = "data/geojson/scenic_heatmap.geojson"
  if (Test-Path $fallback) {
    $HeatmapPath = $fallback
  } else {
    Write-Error "No heatmap found. Run .\\run_prepare_grid.ps1 first."
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
  --heatmap $HeatmapPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Routes updated: $HtmlPath"
