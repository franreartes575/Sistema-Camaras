"""Tests de la optimización del orden de visita."""

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import MAX_UPLOAD_BYTES
from app.main import app
from app.services.optimizer import build_route, solve_order
from app.services.routing import (
    ClusterTooLargeError,
    HaversineProvider,
    OsrmProvider,
    RoutingError,
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Cuatro cámaras alineadas de norte a sur, separadas ~110 m cada una.
COLINEALES = [
    (-34.6000, -58.3816),
    (-34.6010, -58.3816),
    (-34.6020, -58.3816),
    (-34.6030, -58.3816),
]


def matriz_de(puntos: list[tuple[float, float]]) -> np.ndarray:
    """Matriz haversine de los puntos dados."""
    return HaversineProvider().distance_matrix(puntos)


# --------------------------------------------------------------------------
# solve_order
# --------------------------------------------------------------------------


@pytest.mark.parametrize("size", [0, 1, 2], ids=["vacio", "un punto", "dos puntos"])
def test_casos_triviales(size: int) -> None:
    """Con dos paradas o menos no hay nada que optimizar."""
    matrix = matriz_de(COLINEALES[:size])

    assert solve_order(matrix) == list(range(size))


def test_puntos_colineales_se_recorren_en_orden() -> None:
    """En una línea recta el óptimo es recorrerla de punta a punta."""
    order = solve_order(matriz_de(COLINEALES), depot=0, time_limit_s=2)

    assert order == [0, 1, 2, 3]


def test_orden_desordenado_se_corrige() -> None:
    """Aunque la planilla venga mezclada, el recorrido sale ordenado."""
    mezclados = [COLINEALES[2], COLINEALES[0], COLINEALES[3], COLINEALES[1]]

    order = solve_order(matriz_de(mezclados), depot=1, time_limit_s=2)

    # Partiendo del índice 1 (el punto más al norte) baja en orden geográfico.
    assert order == [1, 3, 0, 2]


def test_recorrido_cerrado_vuelve_al_deposito() -> None:
    """Con round_trip la última parada es el punto de partida."""
    order = solve_order(matriz_de(COLINEALES), depot=0, round_trip=True, time_limit_s=2)

    assert order[0] == 0
    assert order[-1] == 0
    assert len(order) == len(COLINEALES) + 1


def test_recorrido_abierto_no_vuelve() -> None:
    """Sin round_trip la cuadrilla termina en la última cámara."""
    order = solve_order(
        matriz_de(COLINEALES), depot=0, round_trip=False, time_limit_s=2
    )

    assert len(order) == len(COLINEALES)
    assert len(set(order)) == len(COLINEALES)


def test_visita_todas_las_camaras_una_sola_vez() -> None:
    """Invariante del TSP: ninguna parada se repite ni se omite."""
    rng = np.random.default_rng(7)
    puntos = [
        (-34.60 + rng.normal(0, 0.01), -58.38 + rng.normal(0, 0.01)) for _ in range(9)
    ]

    order = solve_order(matriz_de(puntos), time_limit_s=2)

    assert sorted(order) == list(range(9))


def test_tramos_inalcanzables_no_desbordan() -> None:
    """Un infinito en la matriz se sustituye por un costo alto pero finito."""
    matrix = matriz_de(COLINEALES)
    matrix[0][1] = np.inf

    order = solve_order(matrix, time_limit_s=2)

    assert sorted(order) == [0, 1, 2, 3]


# --------------------------------------------------------------------------
# build_route
# --------------------------------------------------------------------------


def test_build_route_acumula_la_distancia() -> None:
    """El total es la suma de los tramos y el primero siempre vale cero."""
    route = build_route(COLINEALES, HaversineProvider(), time_limit_s=2)

    assert route.stops[0].distance_from_previous_m == 0
    assert route.total_distance_m == pytest.approx(
        sum(stop.distance_from_previous_m for stop in route.stops), abs=0.5
    )
    # Tres tramos de ~111 m entre cámaras consecutivas.
    assert route.total_distance_m == pytest.approx(333, abs=30)


def test_build_route_geometria_sigue_el_orden() -> None:
    """Sin OSRM la geometría es la poligonal de las paradas ya ordenadas."""
    route = build_route(COLINEALES, HaversineProvider(), time_limit_s=2)

    assert len(route.geometry) == len(COLINEALES)
    assert route.geometry[0] == COLINEALES[route.order[0]]


def test_build_route_sin_puntos() -> None:
    """Un cluster vacío devuelve un recorrido vacío, no una excepción."""
    route = build_route([], HaversineProvider())

    assert route.order == ()
    assert route.total_distance_m == 0.0


# --------------------------------------------------------------------------
# POST /optimize/
# --------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    """Cliente HTTP sobre la app, sin levantar un servidor real."""
    return TestClient(app)


@pytest.fixture
def planilla() -> bytes:
    """Dos zonas de cuatro cámaras cada una."""
    filas = [
        {"id_camara": f"MIC-{i}", "latitud": -34.6000 - i * 0.001, "longitud": -58.3816}
        for i in range(4)
    ] + [
        {"id_camara": f"PAL-{i}", "latitud": -34.5780 - i * 0.001, "longitud": -58.4300}
        for i in range(4)
    ]
    buffer = io.BytesIO()
    pd.DataFrame(filas).to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


def optimizar(client: TestClient, planilla: bytes, **extra: object):
    """Llama a /optimize/ con el mapeo estándar de las fixtures."""
    data: dict[str, object] = {
        "col_id": "id_camara",
        "col_lat": "latitud",
        "col_lon": "longitud",
        "eps_km": 1.0,
        "min_samples": 2,
        "provider": "haversine",
        "time_limit_s": 2,
    }
    data.update(extra)
    return client.post(
        "/optimize/",
        files={"file": ("camaras.xlsx", planilla, XLSX_MIME)},
        data=data,
    )


def test_optimize_devuelve_una_ruta_por_cluster(
    client: TestClient, planilla: bytes
) -> None:
    """Dos zonas separadas producen dos recorridos independientes."""
    response = optimizar(client, planilla)

    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["cluster_count"] == 2
    assert len(body["routes"]) == 2
    assert {route["cluster_id"] for route in body["routes"]} == {0, 1}


def test_optimize_ordena_las_paradas(client: TestClient, planilla: bytes) -> None:
    """Cada recorrido numera sus paradas desde cero y sin repetir cámaras."""
    body = optimizar(client, planilla).json()
    ruta = body["routes"][0]

    assert [stop["order"] for stop in ruta["stops"]] == list(range(ruta["stop_count"]))
    ids = [stop["camera_id"] for stop in ruta["stops"]]
    assert len(set(ids)) == len(ids)


def test_optimize_declara_que_no_es_red_vial(
    client: TestClient, planilla: bytes
) -> None:
    """Con haversine la respuesta avisa que no son distancias de manejo."""
    body = optimizar(client, planilla).json()

    assert body["provider"] == "haversine"
    assert body["is_road_network"] is False


def test_optimize_informa_degradacion_en_modo_auto(
    client: TestClient, planilla: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin OSRM levantado, el modo auto entrega rutas pero con advertencia."""
    monkeypatch.setattr(OsrmProvider, "is_available", lambda self: False)

    body = optimizar(client, planilla, provider="auto").json()

    assert body["provider"] == "haversine"
    assert body["warning"] is not None


def test_optimize_falla_si_se_exige_osrm_y_no_esta(
    client: TestClient, planilla: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pedir OSRM explícitamente sin motor devuelve 503, no rutas falsas."""
    monkeypatch.setattr(OsrmProvider, "is_available", lambda self: False)

    response = optimizar(client, planilla, provider="osrm")

    assert response.status_code == 503
    assert "no responde" in response.json()["detail"]


def test_optimize_propaga_falla_del_motor(
    client: TestClient, planilla: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si OSRM falla a mitad del cálculo, el error llega traducido."""

    def explota(self, points):
        raise RoutingError("motor caído")

    monkeypatch.setattr(OsrmProvider, "is_available", lambda self: True)
    monkeypatch.setattr(OsrmProvider, "distance_matrix", explota)

    response = optimizar(client, planilla, provider="osrm")

    assert response.status_code == 503
    assert "motor caído" in response.json()["detail"]


def test_optimize_excluye_el_ruido(client: TestClient) -> None:
    """Las cámaras sin cluster no entran en ningún recorrido."""
    filas = [
        {"id_camara": f"MIC-{i}", "latitud": -34.6000 - i * 0.001, "longitud": -58.3816}
        for i in range(3)
    ] + [{"id_camara": "LEJOS", "latitud": -38.0055, "longitud": -57.5426}]
    buffer = io.BytesIO()
    pd.DataFrame(filas).to_excel(buffer, index=False, engine="openpyxl")

    body = optimizar(client, buffer.getvalue()).json()

    assert body["stats"]["noise_count"] == 1
    ruteadas = {
        stop["camera_id"] for route in body["routes"] for stop in route["stops"]
    }
    assert "LEJOS" not in ruteadas


def test_optimize_rechaza_proveedor_invalido(
    client: TestClient, planilla: bytes
) -> None:
    """`provider` sólo acepta auto, osrm o haversine."""
    assert optimizar(client, planilla, provider="google").status_code == 422


# --------------------------------------------------------------------------
# Regresiones de la revisión de código
# --------------------------------------------------------------------------


@pytest.mark.parametrize("size", [1, 2], ids=["una parada", "dos paradas"])
def test_round_trip_cierra_el_loop_en_clusters_chicos(size: int) -> None:
    """Regresión: el atajo de casos triviales ignoraba round_trip.

    Con min_samples=2 por defecto, los clusters de dos cámaras son el caso
    más común, y devolvían un recorrido abierto aunque se pidiera cerrado.
    """
    order = solve_order(matriz_de(COLINEALES[:size]), depot=0, round_trip=True)

    if size == 1:
        assert order == [0]
    else:
        assert order == [0, 1, 0]


def test_tramo_inalcanzable_no_cuenta_como_cero() -> None:
    """Regresión: un tramo sin conexión vial se reportaba como 0 m.

    Eso hacía que la distancia total pareciera menor de lo que es, sin ningún
    indicio de que el recorrido no era transitable.
    """

    class ProveedorConHueco:
        """Dos puntos alcanzables y un tercero aislado de la red."""

        name = "falso"
        is_road_network = True

        def distance_matrix(self, points):
            return np.array(
                [
                    [0.0, 100.0, np.inf],
                    [100.0, 0.0, np.inf],
                    [np.inf, np.inf, 0.0],
                ]
            )

        def route_geometry(self, points):
            return list(points)

    route = build_route(COLINEALES[:3], ProveedorConHueco(), time_limit_s=2)

    assert route.has_unreachable_legs is True
    assert any(stop.distance_from_previous_m is None for stop in route.stops)
    # El total suma sólo lo transitable, nunca el tramo imposible.
    assert route.total_distance_m == pytest.approx(100.0)


def test_cluster_demasiado_grande_es_error_de_input(
    client: TestClient, planilla: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regresión: se devolvía 503, que le sugiere al cliente reintentar.

    Achicar el cluster es la única salida, así que corresponde un 422.
    """

    def demasiado_grande(self, points):
        raise ClusterTooLargeError("El cluster tiene 150 cámaras. Reduzca eps_km.")

    monkeypatch.setattr(OsrmProvider, "is_available", lambda self: True)
    monkeypatch.setattr(OsrmProvider, "distance_matrix", demasiado_grande)

    response = optimizar(client, planilla, provider="osrm")

    assert response.status_code == 422
    assert "eps_km" in response.json()["detail"]


def test_rechaza_subida_sobre_el_limite(client: TestClient) -> None:
    """Un archivo enorme se corta antes de cargarse entero a memoria."""
    gigante = b"x" * (MAX_UPLOAD_BYTES + 1024)

    response = client.post(
        "/upload-excel/", files={"file": ("enorme.xlsx", gigante, XLSX_MIME)}
    )

    assert response.status_code == 413
    assert "MB" in response.json()["detail"]
