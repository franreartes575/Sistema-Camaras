"""Límites de municipios inventados, chicos y fáciles de razonar, para los tests.

    Salta       cuadrado de 0,2° con un hueco en el medio
    Enclave     el hueco de Salta (otro municipio adentro)
    Cerrillos   franja al sur de Salta, separada por ~2,2 km sin municipio
    Islas       un municipio en dos partes, lejos de los demás
"""

import json
from pathlib import Path


def _cuadrado(lon_min: float, lat_min: float, lon_max: float, lat_max: float) -> list:
    return [
        [lon_min, lat_min],
        [lon_max, lat_min],
        [lon_max, lat_max],
        [lon_min, lat_max],
        [lon_min, lat_min],
    ]


HUECO = _cuadrado(-65.42, -24.82, -65.38, -24.78)

GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"nombre": "Salta"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_cuadrado(-65.50, -24.90, -65.30, -24.70), HUECO],
            },
        },
        {
            "type": "Feature",
            "properties": {"nombre": "Enclave"},
            "geometry": {"type": "Polygon", "coordinates": [HUECO]},
        },
        {
            "type": "Feature",
            "properties": {"nombre": "Cerrillos"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_cuadrado(-65.50, -25.00, -65.30, -24.92)],
            },
        },
        {
            "type": "Feature",
            "properties": {"nombre": "Islas"},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [_cuadrado(-64.40, -23.20, -64.30, -23.10)],
                    [_cuadrado(-63.85, -22.55, -63.75, -22.45)],
                ],
            },
        },
        # Sin nombre o sin geometría: se ignoran.
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [HUECO]}},
        {"type": "Feature", "properties": {"nombre": "Vacío"}, "geometry": None},
    ],
}


def escribir(ruta: str | Path) -> Path:
    path = Path(ruta)
    path.write_text(json.dumps(GEOJSON), encoding="utf-8")
    return path
