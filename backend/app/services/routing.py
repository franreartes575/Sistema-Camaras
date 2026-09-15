"""Proveedores de distancias y geometrías de ruta.

La optimización no depende de OSRM directamente: consume la interfaz
`RoutingProvider`. Eso permite trabajar sin motor de ruteo instalado —con
distancias en línea recta— y enchufar OSRM después sin tocar el optimizador.

Convención de coordenadas: hacia afuera todo es `(lat, lon)`, que es como
vienen las cámaras. OSRM espera `lon,lat`, y esa inversión se hace acá adentro.
"""

import math
from typing import Protocol, Sequence

import numpy as np
import requests

from ..config import OSRM_BASE_URL
from .clustering import haversine_km

Point = tuple[float, float]

# OSRM rechaza matrices por encima de su `max-table-size` (100 por defecto).
OSRM_MAX_TABLE_SIZE = 100

# Un timeout corto: el motor corre en localhost, si no responde es que no está.
OSRM_TIMEOUT_S = 10

# Punto de sondeo para verificar que el motor esté vivo: plaza 9 de Julio,
# Salta capital. Debe pertenecer al área del grafo que se haya construido.
PROBE_LAT = -24.7859
PROBE_LON = -65.4117


class RoutingError(RuntimeError):
    """Falla del motor de ruteo, ya traducida a un mensaje accionable."""


class ClusterTooLargeError(RoutingError):
    """El cluster excede lo que el motor acepta por matriz.

    Se distingue del resto porque no es una falla del servicio sino del input:
    el usuario tiene que achicar los clusters y reenviar, no reintentar.
    """


class RoutingProvider(Protocol):
    """Fuente de distancias entre puntos y de la geometría que los une."""

    name: str
    is_road_network: bool

    def distance_matrix(self, points: Sequence[Point]) -> np.ndarray:
        """Matriz cuadrada de distancias en metros."""
        ...

    def route_geometry(self, points: Sequence[Point]) -> list[Point]:
        """Vértices del recorrido que pasa por `points`, en orden."""
        ...


class HaversineProvider:
    """Distancias en línea recta. No requiere ningún servicio externo.

    Sirve para desarrollar y validar la optimización sin OSRM, pero ignora el
    trazado real de las calles: en zona urbana subestima la distancia de manejo
    de forma significativa, así que las rutas que produce no son operativas.
    """

    name = "haversine"
    is_road_network = False

    def distance_matrix(self, points: Sequence[Point]) -> np.ndarray:
        """Distancia esférica entre cada par de puntos."""
        if not points:
            return np.zeros((0, 0))

        lats = np.array([lat for lat, _ in points], dtype=float)
        lons = np.array([lon for _, lon in points], dtype=float)

        matrix = np.zeros((len(points), len(points)), dtype=float)
        for index, (lat0, lon0) in enumerate(points):
            matrix[index] = haversine_km(lats, lons, lat0, lon0) * 1000.0
        return matrix

    def route_geometry(self, points: Sequence[Point]) -> list[Point]:
        """Sin red de calles, el recorrido es la poligonal entre los puntos."""
        return list(points)


class OsrmProvider:
    """Distancias y geometrías reales contra una instancia local de OSRM."""

    name = "osrm"
    is_road_network = True

    def __init__(self, base_url: str = OSRM_BASE_URL, profile: str = "driving") -> None:
        self.base_url = base_url.rstrip("/")
        self.profile = profile

    def _coords(self, points: Sequence[Point]) -> str:
        """Serializa a `lon,lat;lon,lat`, el orden que espera OSRM.

        La ingesta ya descarta coordenadas no finitas, pero el chequeo se
        repite acá para que el proveedor no dependa en silencio de que otro
        módulo haya validado antes.
        """
        for lat, lon in points:
            if not (math.isfinite(lat) and math.isfinite(lon)):
                raise RoutingError(f"Coordenada inválida: ({lat}, {lon})")
        return ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)

    def is_available(self) -> bool:
        """Comprueba que el motor responda, sin levantar excepción.

        La sonda cae en Salta capital: tiene que estar dentro del grafo
        cargado, o el motor responde pero sin encontrar calle cercana.
        """
        try:
            response = requests.get(
                f"{self.base_url}/nearest/v1/{self.profile}/{PROBE_LON},{PROBE_LAT}",
                timeout=OSRM_TIMEOUT_S,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def distance_matrix(self, points: Sequence[Point]) -> np.ndarray:
        """Matriz de distancias por calle vía el servicio `table` de OSRM."""
        if not points:
            return np.zeros((0, 0))

        if len(points) > OSRM_MAX_TABLE_SIZE:
            raise ClusterTooLargeError(
                f"El cluster tiene {len(points)} cámaras y OSRM acepta hasta "
                f"{OSRM_MAX_TABLE_SIZE} por matriz. Reduzca el radio de "
                f"vecindad (eps_km) para obtener clusters más chicos."
            )

        payload = self._get(
            f"{self.base_url}/table/v1/{self.profile}/{self._coords(points)}",
            params={"annotations": "distance"},
        )

        distances = payload.get("distances")
        if not distances:
            raise RoutingError("OSRM no devolvió matriz de distancias.")

        # OSRM marca con null los pares que no puede conectar por la red vial.
        return np.array(
            [
                [np.inf if value is None else float(value) for value in row]
                for row in distances
            ]
        )

    def route_geometry(self, points: Sequence[Point]) -> list[Point]:
        """Polilínea del recorrido real, devuelta como `(lat, lon)`."""
        if len(points) < 2:
            return list(points)

        payload = self._get(
            f"{self.base_url}/route/v1/{self.profile}/{self._coords(points)}",
            params={"overview": "full", "geometries": "geojson"},
        )

        routes = payload.get("routes")
        if not routes:
            raise RoutingError("OSRM no devolvió una ruta para esos puntos.")

        coordinates = routes[0]["geometry"]["coordinates"]
        return [(lat, lon) for lon, lat in coordinates]

    def _get(self, url: str, params: dict[str, str]) -> dict:
        """Llama a OSRM y normaliza sus modos de falla a `RoutingError`."""
        try:
            response = requests.get(url, params=params, timeout=OSRM_TIMEOUT_S)
        except requests.RequestException as exc:
            raise RoutingError(
                f"No se pudo contactar a OSRM en {self.base_url}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise RoutingError(f"OSRM respondió {response.status_code}.")

        payload = response.json()
        if payload.get("code") != "Ok":
            detail = payload.get("message") or payload.get("code")
            raise RoutingError(f"OSRM rechazó la consulta: {detail}")
        return payload


def select_provider(preference: str = "auto") -> tuple[RoutingProvider, str | None]:
    """Elige el proveedor y explica la elección.

    Devuelve el proveedor y una advertencia cuando hubo que degradar a línea
    recta, para que la interfaz pueda avisarle al usuario que esas distancias
    no son de manejo.
    """
    if preference == "haversine":
        return HaversineProvider(), None

    osrm = OsrmProvider()

    if preference == "osrm":
        if not osrm.is_available():
            raise RoutingError(
                f"OSRM no responde en {osrm.base_url}. Levante el motor de "
                f"ruteo o use el proveedor 'haversine'."
            )
        return osrm, None

    if osrm.is_available():
        return osrm, None

    return HaversineProvider(), (
        f"OSRM no responde en {osrm.base_url}: las distancias son en línea "
        f"recta y subestiman el recorrido real por calle."
    )
