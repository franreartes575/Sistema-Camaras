<#
.SYNOPSIS
    Construye el grafo de ruteo de OSRM para la provincia de Salta.

.DESCRIPTION
    Se corre UNA SOLA VEZ (y despues cada vez que quieras actualizar el mapa).
    Hace tres cosas:
      1. Descarga el extracto de Argentina desde Geofabrik (~410 MB).
      2. Lo recorta al bounding box de Salta, para que el procesamiento entre
         holgado en memoria y tarde minutos en vez de horas.
      3. Corre el preprocesado de OSRM (extract -> partition -> customize).

    Todo se ejecuta dentro de contenedores: no instala nada en Windows.

.EXAMPLE
    .\preparar.ps1
    .\preparar.ps1 -Force    # rehace el grafo aunque ya exista
#>

[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$data = Join-Path $PSScriptRoot "data"
# La misma imagen que docker-compose.yml: el grafo sólo lo lee la versión que lo armó.
$osrmImage = "ghcr.io/project-osrm/osrm-backend:v26.9.0@sha256:8a1b1bc938412f15f9b5b32d794c4ec6bf4a85dfbbabfa0a014b70b187edb53b"

# Bounding box de la provincia de Salta, con un margen para que las rutas que
# salen y vuelven a entrar por rutas nacionales sigan siendo navegables.
#   oeste, sur, este, norte
$bbox = "-68.8,-26.6,-62.0,-21.7"

$argentina = "argentina-latest.osm.pbf"
$salta = "salta-latest.osm.pbf"

function Write-Paso($numero, $texto) {
    Write-Host ""
    Write-Host "==== [$numero] $texto" -ForegroundColor Cyan
}

# ---------------------------------------------------------------- chequeos ---
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker no esta instalado o no esta en el PATH. Ver README.md de esta carpeta."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker esta instalado pero el daemon no responde. Inicia Docker y reintenta."
}

New-Item -ItemType Directory -Force -Path $data | Out-Null

if ((Test-Path (Join-Path $data "salta-latest.osrm.mldgr")) -and -not $Force) {
    Write-Host "El grafo ya esta construido. Usa -Force para rehacerlo." -ForegroundColor Yellow
    Write-Host "Para levantar el motor:  docker compose up -d"
    exit 0
}

# ------------------------------------------------------------- 1. descarga ---
Write-Paso 1 "Mapa de Argentina"
$pbf = Join-Path $data $argentina
if (Test-Path $pbf) {
    $mb = [math]::Round((Get-Item $pbf).Length / 1MB, 1)
    Write-Host "Ya descargado ($mb MB), se reutiliza."
} else {
    Write-Host "Descargando desde Geofabrik (~410 MB)..."
    curl.exe -L --fail --retry 3 -o $pbf `
        "https://download.geofabrik.de/south-america/argentina-latest.osm.pbf"
    $mb = [math]::Round((Get-Item $pbf).Length / 1MB, 1)
    Write-Host "Descargado: $mb MB"
}

# -------------------------------------------------------------- 2. recorte ---
Write-Paso 2 "Recorte a Salta (bbox $bbox)"
# osmium no viene en la imagen de OSRM. Se instala en un Debian efimero en vez
# de depender de una imagen de terceros que puede desaparecer.
docker run --rm -v "${data}:/data" debian:bookworm-slim bash -c @"
set -e
apt-get update -qq
apt-get install -y -qq osmium-tool
osmium extract --bbox $bbox --overwrite -o /data/$salta /data/$argentina
"@
if ($LASTEXITCODE -ne 0) { throw "Fallo el recorte con osmium." }

$mb = [math]::Round((Get-Item (Join-Path $data $salta)).Length / 1MB, 1)
Write-Host "Salta recortada: $mb MB"

# ---------------------------------------------------------- 3. preprocesado ---
Write-Paso 3 "Preprocesado de OSRM (tarda unos minutos)"

Write-Host "-- osrm-extract"
docker run --rm -v "${data}:/data" $osrmImage `
    osrm-extract -p /opt/car.lua "/data/$salta"
if ($LASTEXITCODE -ne 0) { throw "Fallo osrm-extract." }

Write-Host "-- osrm-partition"
docker run --rm -v "${data}:/data" $osrmImage `
    osrm-partition /data/salta-latest.osrm
if ($LASTEXITCODE -ne 0) { throw "Fallo osrm-partition." }

Write-Host "-- osrm-customize"
docker run --rm -v "${data}:/data" $osrmImage `
    osrm-customize /data/salta-latest.osrm
if ($LASTEXITCODE -ne 0) { throw "Fallo osrm-customize." }

Write-Host ""
Write-Host "==== Grafo listo" -ForegroundColor Green
Write-Host "Levanta el motor con:   docker compose up -d"
Write-Host "Verifica con:           curl http://localhost:5000/nearest/v1/driving/-65.4117,-24.7859"
