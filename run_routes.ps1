param(
  [double]$OriginLat = 42.5389,
  [double]$OriginLon = -71.0481,
  [double]$DestLat   = 42.700109,
  [double]$DestLon   = -71.159784,
  [string]$Source = "mapillary",
  [double]$ScenicWeight = 0.9,
  [double]$MaxDurationRatio = 1.7,
  [int]$WaypointCount = 6,
  [double]$WaypointRadius = 8000,
  [double]$WaypointMinDistance = 2000,
  [double]$WaypointMinSeparation = 1500,
  [string]$RoadsPath = "",
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
  if (Test-Path $fallback) {
    $HeatmapPath = $fallback
  } else {
    Write-Error "No heatmap found for source '$Source'. Run .\\run_prepare_${Source}.ps1 first."
    exit 1
  }
}

if (-not $RoadsPath) {
  if ($Source -eq "google") {
    $RoadsPath = "data/google/osm/roads.geojson"
  } else {
    $RoadsPath = "data/mapillary/osm/roads.geojson"
  }
  if (-not (Test-Path $RoadsPath)) {
    $fallbackRoads = "data/mapillary/osm/roads.geojson"
    if (Test-Path $fallbackRoads) {
      $RoadsPath = $fallbackRoads
    }
  }
}

python 07_route_candidates.py `
  --origin-lat $OriginLat `
  --origin-lon $OriginLon `
  --dest-lat $DestLat `
  --dest-lon $DestLon `
  --heatmap $HeatmapPath `
  --roads $RoadsPath `
  --max-heatmap-distance 250 `
  --scenic-weight $ScenicWeight `
  --max-duration-ratio $MaxDurationRatio `
  --waypoint-count $WaypointCount `
  --waypoint-radius $WaypointRadius `
  --waypoint-min-distance $WaypointMinDistance `
  --waypoint-min-separation $WaypointMinSeparation `
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
  --source $Source `
  --scenic-weight $ScenicWeight `
  --waypoint-count $WaypointCount `
  --waypoint-radius $WaypointRadius `
  --waypoint-min-distance $WaypointMinDistance `
  --waypoint-min-separation $WaypointMinSeparation
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Routes updated: $HtmlPath"
