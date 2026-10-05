"""Localidad de cada cámara a partir de sus coordenadas.

Las planillas no traen la localidad, así que se calcula: es el municipio de
Salta dentro del cual cae la cámara, según los límites oficiales del IGN
guardados en `config.MUNICIPIOS_PATH` (un GeoJSON con la propiedad `nombre`).
No se consulta ningún servicio externo: las coordenadas de las cámaras no
salen del servidor.

El archivo lo genera una sola vez `python -m app.catalogo_cli
preparar-municipios`. Mientras no exista, la localidad queda como
`SIN_CALCULAR` — nunca se inventa una.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import numpy as np

from .. import config

SIN_CALCULAR = "Sin calcular"
FUERA_DE_SALTA = "Fuera de Salta"

# Un punto fuera de todos los municipios pero a menos de esto de alguno se le
# asigna ese: la simplificación de los límites deja pequeños huecos entre
# municipios vecinos y recorta un poco los bordes.
MAX_BORDE_KM = 5.0

_KM_POR_GRADO = 111.32



class Anillo:
    """Un anillo del polígono como arreglos de numpy, con sus aristas listas.

    Ubicar miles de cámaras con un ray casting en Python puro tarda segundos;
    vectorizado sobre las aristas, milisegundos.
    """

    __slots__ = ("x", "y", "x_prev", "y_prev")

    def __init__(self, puntos: list[tuple[float, float]]):
        coords = np.asarray(puntos, dtype=float)
        if len(coords) > 1 and np.array_equal(coords[0], coords[-1]):
            coords = coords[:-1]  # el cierre repetido no es una arista más
        self.x, self.y = coords[:, 0], coords[:, 1]
        self.x_prev, self.y_prev = np.roll(self.x, 1), np.roll(self.y, 1)

    def contiene(self, lon: float, lat: float) -> bool:
        """Ray casting: cuántas aristas cruza una semirrecta hacia el este."""
        cruza = (self.y > lat) != (self.y_prev > lat)
        if not cruza.any():
            return False
        x, y = self.x[cruza], self.y[cruza]
        x_prev, y_prev = self.x_prev[cruza], self.y_prev[cruza]
        x_cruce = x + (lat - y) * (x_prev - x) / (y_prev - y)
        return bool(np.count_nonzero(lon < x_cruce) % 2)

    def distancia_km(self, lon: float, lat: float) -> float:
        """Distancia al borde, con proyección equirectangular local.

        A la escala de unos pocos km el error es despreciable.
        """
        escala_x = _KM_POR_GRADO * math.cos(math.radians(lat))
        ax, ay = (self.x_prev - lon) * escala_x, (self.y_prev - lat) * _KM_POR_GRADO
        bx, by = (self.x - lon) * escala_x, (self.y - lat) * _KM_POR_GRADO
        dx, dy = bx - ax, by - ay
        largo2 = dx * dx + dy * dy
        with np.errstate(invalid="ignore", divide="ignore"):
            t = np.where(largo2 > 0, -(ax * dx + ay * dy) / largo2, 0.0)
        t = np.clip(t, 0.0, 1.0)
        return float(np.min(np.hypot(ax + t * dx, ay + t * dy)))


Poligono = tuple[Anillo, ...]  # exterior + huecos


@dataclass(frozen=True)
class Municipio:
    nombre: str
    poligonos: tuple[Poligono, ...]
    # (lon_min, lat_min, lon_max, lat_max): descarta rápido los que no pueden
    # contener el punto.
    caja: tuple[float, float, float, float]

    def contiene(self, lon: float, lat: float) -> bool:
        return any(
            exterior.contiene(lon, lat) and not any(hueco.contiene(lon, lat) for hueco in huecos)
            for exterior, *huecos in self.poligonos
        )

    def distancia_km(self, lon: float, lat: float) -> float:
        return min(
            anillo.distancia_km(lon, lat) for poligono in self.poligonos for anillo in poligono
        )


class Limites:
    """Los municipios cargados, listos para ubicar puntos."""

    def __init__(self, municipios: list[Municipio]):
        self.municipios = municipios

    @property
    def nombres(self) -> list[str]:
        return sorted(municipio.nombre for municipio in self.municipios)

    def localidad_de(self, lat: float, lon: float) -> str:
        for municipio in self.municipios:
            lon_min, lat_min, lon_max, lat_max = municipio.caja
            if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
                continue
            if municipio.contiene(lon, lat):
                return municipio.nombre

        # Fuera de todos: el más cercano, si está a pocos km. Sólo se mide
        # contra los que tienen la caja a tiro, que son unos pocos.
        margen_lat = MAX_BORDE_KM / _KM_POR_GRADO
        margen_lon = margen_lat / max(math.cos(math.radians(lat)), 0.1)
        cercano, distancia_minima = None, math.inf
        for municipio in self.municipios:
            lon_min, lat_min, lon_max, lat_max = municipio.caja
            if not (
                lon_min - margen_lon <= lon <= lon_max + margen_lon
                and lat_min - margen_lat <= lat <= lat_max + margen_lat
            ):
                continue
            distancia = municipio.distancia_km(lon, lat)
            if distancia < distancia_minima:
                cercano, distancia_minima = municipio, distancia
        if cercano is not None and distancia_minima <= MAX_BORDE_KM:
            return cercano.nombre
        return FUERA_DE_SALTA


def _anillo(coordenadas: list) -> Anillo:
    return Anillo([(float(punto[0]), float(punto[1])) for punto in coordenadas])


def _poligonos(geometria: dict) -> tuple[Poligono, ...]:
    tipo = geometria.get("type")
    if tipo == "Polygon":
        partes = [geometria["coordinates"]]
    elif tipo == "MultiPolygon":
        partes = geometria["coordinates"]
    else:
        raise ValueError(f"Geometría no soportada: {tipo}")
    return tuple(
        tuple(_anillo(anillo) for anillo in poligono if len(anillo) >= 3)
        for poligono in partes
        if poligono and len(poligono[0]) >= 3
    )


def desde_geojson(datos: dict) -> Limites:
    """Arma los límites desde un FeatureCollection con la propiedad `nombre`."""
    municipios: list[Municipio] = []
    for feature in datos.get("features", []):
        nombre = str((feature.get("properties") or {}).get("nombre") or "").strip()
        geometria = feature.get("geometry")
        if not nombre or not geometria:
            continue
        poligonos = _poligonos(geometria)
        if not poligonos:
            continue
        xs = np.concatenate([poligono[0].x for poligono in poligonos])
        ys = np.concatenate([poligono[0].y for poligono in poligonos])
        caja = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
        municipios.append(Municipio(nombre, poligonos, caja))
    if not municipios:
        raise ValueError("El archivo de municipios no tiene ningún polígono con nombre.")
    return Limites(municipios)


# Caché por (ruta, fecha de modificación): si se regenera el archivo, se
# recarga sin reiniciar el backend.
_cache: dict[str, tuple[float, Limites]] = {}
_cache_lock = Lock()


def cargar(ruta: str | None = None) -> Limites | None:
    """Los límites guardados, o None si el archivo todavía no existe."""
    path = Path(ruta or config.MUNICIPIOS_PATH)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    clave = str(path)
    with _cache_lock:
        guardado = _cache.get(clave)
        if guardado and guardado[0] == mtime:
            return guardado[1]
        limites = desde_geojson(json.loads(path.read_text(encoding="utf-8")))
        _cache[clave] = (mtime, limites)
        return limites


def localidad_de(lat: float, lon: float, limites: Limites | None = None) -> str:
    """La localidad (municipio) de un punto, con los límites guardados."""
    limites = limites or cargar()
    if limites is None:
        return SIN_CALCULAR
    return limites.localidad_de(lat, lon)
