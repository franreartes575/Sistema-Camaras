"""Tests de los proveedores de distancia y geometría."""

from unittest.mock import Mock, patch

import numpy as np
import pytest
import requests

from app.services.routing import (
    DEFAULT_AVERAGE_SPEED_KMH,
    OSRM_MAX_TABLE_SIZE,
    HaversineProvider,
    OsrmProvider,
    RoutingError,
    select_provider,
)

OBELISCO = (-34.6037, -58.3816)
PALERMO = (-34.5780, -58.4300)


def respuesta_osrm(payload: dict, status: int = 200) -> Mock:
    """Arma una respuesta HTTP simulada de OSRM."""
    mock = Mock()
    mock.status_code = status
    mock.json.return_value = payload
    return mock


# --------------------------------------------------------------------------
# HaversineProvider
# --------------------------------------------------------------------------


def test_haversine_matriz_es_simetrica_y_diagonal_cero() -> None:
    """Propiedades básicas de una matriz de distancias euclídea."""
    matrix = HaversineProvider().distance_matrix([OBELISCO, PALERMO])

    assert matrix.shape == (2, 2)
    assert np.allclose(np.diag(matrix), 0)
    assert matrix[0][1] == pytest.approx(matrix[1][0])


def test_haversine_distancia_conocida_en_metros() -> None:
    """Obelisco a Palermo son unos 5 km; la matriz va en metros."""
    matrix = HaversineProvider().distance_matrix([OBELISCO, PALERMO])

    assert matrix[0][1] == pytest.approx(5000, abs=800)


def test_haversine_sin_puntos() -> None:
    """Una lista vacía no rompe el proveedor."""
    assert HaversineProvider().distance_matrix([]).shape == (0, 0)


def test_haversine_geometria_es_la_poligonal() -> None:
    """Sin red vial el recorrido es la recta entre los puntos dados."""
    assert HaversineProvider().route_geometry([OBELISCO, PALERMO]) == [
        OBELISCO,
        PALERMO,
    ]


def test_haversine_no_es_red_vial() -> None:
    """La bandera permite que la interfaz avise que no son distancias de manejo."""
    assert HaversineProvider().is_road_network is False


def test_haversine_duracion_usa_la_velocidad_configurada() -> None:
    """Sin OSRM, la duración es distancia/velocidad, con la velocidad pedida."""
    provider = HaversineProvider(average_speed_kmh=60.0)

    matrices = provider.travel_matrix([OBELISCO, PALERMO])

    esperado_s = matrices.distances_m[0][1] / (60.0 * 1000.0 / 3600.0)
    assert matrices.durations_s[0][1] == pytest.approx(esperado_s)


def test_haversine_duracion_default_usa_velocidad_por_defecto() -> None:
    """Sin velocidad explícita, usa DEFAULT_AVERAGE_SPEED_KMH."""
    matrices = HaversineProvider().travel_matrix([OBELISCO, PALERMO])

    esperado_s = matrices.distances_m[0][1] / (
        DEFAULT_AVERAGE_SPEED_KMH * 1000.0 / 3600.0
    )
    assert matrices.durations_s[0][1] == pytest.approx(esperado_s)


def test_haversine_travel_matrix_sin_puntos() -> None:
    """Una lista vacía no rompe travel_matrix."""
    matrices = HaversineProvider().travel_matrix([])

    assert matrices.distances_m.shape == (0, 0)
    assert matrices.durations_s.shape == (0, 0)


# --------------------------------------------------------------------------
# OsrmProvider — orden de coordenadas y manejo de fallas
# --------------------------------------------------------------------------


def test_osrm_invierte_a_lon_lat() -> None:
    """OSRM espera lon,lat: es el error clásico al integrarlo."""
    provider = OsrmProvider("http://localhost:5000")

    assert provider._coords([OBELISCO]) == "-58.381600,-34.603700"


def test_osrm_pide_matriz_al_servicio_table() -> None:
    """La matriz sale del endpoint `table`, anotada por distancia."""
    payload = {"code": "Ok", "distances": [[0, 5200], [5100, 0]]}

    with patch(
        "app.services.routing.requests.get", return_value=respuesta_osrm(payload)
    ) as get:
        matrix = OsrmProvider().distance_matrix([OBELISCO, PALERMO])

    assert matrix[0][1] == 5200
    (url,) = get.call_args[0]
    assert "/table/v1/driving/" in url
    assert get.call_args[1]["params"]["annotations"] == "distance"


def test_osrm_traduce_tramos_nulos_a_infinito() -> None:
    """Un par que la red vial no conecta llega como null."""
    payload = {"code": "Ok", "distances": [[0, None], [None, 0]]}

    with patch(
        "app.services.routing.requests.get", return_value=respuesta_osrm(payload)
    ):
        matrix = OsrmProvider().distance_matrix([OBELISCO, PALERMO])

    assert np.isinf(matrix[0][1])


def test_osrm_travel_matrix_pide_distancia_y_duracion() -> None:
    """travel_matrix anota ambas, no sólo distancia."""
    payload = {
        "code": "Ok",
        "distances": [[0, 5200], [5100, 0]],
        "durations": [[0, 420], [410, 0]],
    }

    with patch(
        "app.services.routing.requests.get", return_value=respuesta_osrm(payload)
    ) as get:
        matrices = OsrmProvider().travel_matrix([OBELISCO, PALERMO])

    assert matrices.distances_m[0][1] == 5200
    assert matrices.durations_s[0][1] == 420
    assert get.call_args[1]["params"]["annotations"] == "distance,duration"


def test_osrm_travel_matrix_traduce_nulos_a_infinito_en_ambas() -> None:
    """Un tramo sin conexión vial llega como null en distancia y duración."""
    payload = {
        "code": "Ok",
        "distances": [[0, None], [None, 0]],
        "durations": [[0, None], [None, 0]],
    }

    with patch(
        "app.services.routing.requests.get", return_value=respuesta_osrm(payload)
    ):
        matrices = OsrmProvider().travel_matrix([OBELISCO, PALERMO])

    assert np.isinf(matrices.distances_m[0][1])
    assert np.isinf(matrices.durations_s[0][1])


def test_osrm_travel_matrix_sin_puntos() -> None:
    """Una lista vacía no consulta OSRM."""
    with patch("app.services.routing.requests.get") as get:
        matrices = OsrmProvider().travel_matrix([])

    assert matrices.distances_m.shape == (0, 0)
    get.assert_not_called()


def test_osrm_travel_matrix_rechaza_cluster_mas_grande_que_la_matriz() -> None:
    """Mismo límite de tamaño que distance_matrix."""
    puntos = [OBELISCO] * (OSRM_MAX_TABLE_SIZE + 1)

    with pytest.raises(RoutingError, match="eps_km"):
        OsrmProvider().travel_matrix(puntos)


def test_osrm_geometria_vuelve_como_lat_lon() -> None:
    """El GeoJSON de OSRM viene en lon,lat y se invierte al salir."""
    payload = {
        "code": "Ok",
        "routes": [
            {"geometry": {"coordinates": [[-58.3816, -34.6037], [-58.43, -34.578]]}}
        ],
    }

    with patch(
        "app.services.routing.requests.get", return_value=respuesta_osrm(payload)
    ):
        geometry = OsrmProvider().route_geometry([OBELISCO, PALERMO])

    assert geometry[0] == pytest.approx(OBELISCO)
    assert geometry[1] == pytest.approx(PALERMO)


def test_osrm_rechaza_cluster_mas_grande_que_la_matriz() -> None:
    """Por encima de max-table-size el mensaje explica cómo achicar el cluster."""
    puntos = [OBELISCO] * (OSRM_MAX_TABLE_SIZE + 1)

    with pytest.raises(RoutingError, match="eps_km"):
        OsrmProvider().distance_matrix(puntos)


def test_osrm_traduce_error_de_red() -> None:
    """Una conexión caída se convierte en RoutingError, no en ConnectionError."""
    with patch(
        "app.services.routing.requests.get",
        side_effect=requests.ConnectionError("rechazada"),
    ):
        with pytest.raises(RoutingError, match="No se pudo contactar"):
            OsrmProvider().distance_matrix([OBELISCO, PALERMO])


def test_osrm_traduce_codigo_de_error_del_motor() -> None:
    """OSRM devuelve 200 con `code` distinto de Ok cuando rechaza la consulta."""
    payload = {"code": "NoSegment", "message": "punto sin calle cercana"}

    with patch(
        "app.services.routing.requests.get", return_value=respuesta_osrm(payload)
    ):
        with pytest.raises(RoutingError, match="punto sin calle cercana"):
            OsrmProvider().distance_matrix([OBELISCO, PALERMO])


def test_osrm_geometria_con_un_solo_punto_no_consulta() -> None:
    """Con menos de dos puntos no hay ruta que pedir."""
    with patch("app.services.routing.requests.get") as get:
        assert OsrmProvider().route_geometry([OBELISCO]) == [OBELISCO]

    get.assert_not_called()


# --------------------------------------------------------------------------
# select_provider
# --------------------------------------------------------------------------


def test_select_haversine_no_consulta_osrm() -> None:
    """Forzar línea recta evita cualquier llamada de red."""
    with patch("app.services.routing.requests.get") as get:
        provider, warning = select_provider("haversine")

    assert provider.name == "haversine"
    assert warning is None
    get.assert_not_called()


def test_select_auto_degrada_con_aviso_si_osrm_no_responde() -> None:
    """El modo auto sigue funcionando, pero avisa que las distancias no son reales."""
    with patch.object(OsrmProvider, "is_available", return_value=False):
        provider, warning = select_provider("auto")

    assert provider.name == "haversine"
    assert warning is not None
    assert "línea" in warning


def test_select_auto_degrada_propaga_velocidad_configurada() -> None:
    """El proveedor de línea recta usa la velocidad pedida, no la default."""
    with patch.object(OsrmProvider, "is_available", return_value=False):
        provider, _ = select_provider("auto", average_speed_kmh=80.0)

    assert isinstance(provider, HaversineProvider)
    assert provider.average_speed_kmh == 80.0


def test_select_auto_usa_osrm_si_responde() -> None:
    """Con el motor arriba no hay degradación ni aviso."""
    with patch.object(OsrmProvider, "is_available", return_value=True):
        provider, warning = select_provider("auto")

    assert provider.name == "osrm"
    assert provider.is_road_network is True
    assert warning is None


def test_select_osrm_explicito_falla_si_no_responde() -> None:
    """Pedir OSRM explícitamente no debe degradar en silencio."""
    with patch.object(OsrmProvider, "is_available", return_value=False):
        with pytest.raises(RoutingError, match="no responde"):
            select_provider("osrm")


def test_is_available_no_propaga_excepciones() -> None:
    """El chequeo de disponibilidad nunca debe romper el flujo."""
    with patch(
        "app.services.routing.requests.get",
        side_effect=requests.Timeout("timeout"),
    ):
        assert OsrmProvider().is_available() is False
