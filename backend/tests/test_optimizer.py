"""Tests de la optimización del orden de visita."""

import io
import json
import threading

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import config, main
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


def puntos_de_partida_genericos() -> str:
    """Cubre de sobra los ids de cluster que pueden salir en estos tests.

    Los ids sólo importan como clave (no hace falta que el punto quede cerca
    del cluster real): con presupuesto de 8h alcanza igual, y los ids que no
    correspondan a ningún cluster real simplemente no se usan.
    """
    return json.dumps(
        {
            str(i): {"lat": -34.6000, "lon": -58.3816, "name": f"Base {i}"}
            for i in range(10)
        }
    )


def optimizar(client: TestClient, planilla: bytes, **extra: object):
    """Llama a /optimize/ con el mapeo estándar de las fixtures."""
    data: dict[str, object] = {
        "col_id": "id_camara",
        "col_lat": "latitud",
        "col_lon": "longitud",
        "eps_km": 1.0,
        "min_samples": 2,
        "provider": "haversine",
        "cluster_starts_json": puntos_de_partida_genericos(),
        "day_budget_s": 8 * 3600,
        "service_time_s": 0,
        "average_speed_kmh": 40,
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
    """Pedir OSRM explícitamente sin motor devuelve 503, no rutas falsas.

    El detalle expuesto al cliente es genérico a propósito: no debe filtrar
    la URL interna de OSRM (ver CLAUDE.md, "Antes de exponerlo a la red").
    """
    monkeypatch.setattr(OsrmProvider, "is_available", lambda self: False)

    response = optimizar(client, planilla, provider="osrm")

    assert response.status_code == 503
    assert "no está disponible" in response.json()["detail"]
    assert "localhost" not in response.json()["detail"]


def test_optimize_propaga_falla_del_motor(
    client: TestClient,
    planilla: bytes,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Si OSRM falla a mitad del cálculo, se loguea server-side y se sanea.

    El cliente recibe un mensaje genérico; el detalle original ("motor
    caído") sólo llega al log, nunca a la respuesta HTTP.
    """

    def explota(self, points):
        raise RoutingError("motor caído")

    monkeypatch.setattr(OsrmProvider, "is_available", lambda self: True)
    monkeypatch.setattr(OsrmProvider, "travel_matrix", explota)

    with caplog.at_level("WARNING"):
        response = optimizar(client, planilla, provider="osrm")

    assert response.status_code == 503
    assert "motor caído" not in response.json()["detail"]
    assert "no está disponible" in response.json()["detail"]
    assert "motor caído" in caplog.text


def test_optimize_excluye_el_ruido_mas_alla_del_limite(client: TestClient) -> None:
    """Una cámara a ~600 km queda fuera de cualquier `noise_reassign_factor` razonable."""
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
    assert body["warning"] is not None
    assert "sin cluster cercano" in body["warning"]


def test_optimize_reasigna_ruido_cercano_a_su_recorrido(client: TestClient) -> None:
    """Una cámara moderadamente lejana se reasigna y aparece en la ruta."""
    filas = [
        {"id_camara": f"MIC-{i}", "latitud": -34.6000 - i * 0.001, "longitud": -58.3816}
        for i in range(3)
    ] + [
        # A ~2.2 km del cluster MIC: fuera de eps=1km (ruido) pero dentro del
        # tope por defecto (eps_km * 3 = 3km).
        {"id_camara": "CERCANA", "latitud": -34.6000 - 0.02, "longitud": -58.3816}
    ]
    buffer = io.BytesIO()
    pd.DataFrame(filas).to_excel(buffer, index=False, engine="openpyxl")

    body = optimizar(client, buffer.getvalue()).json()

    assert body["stats"]["noise_count"] == 0
    ruteadas = {
        stop["camera_id"] for route in body["routes"] for stop in route["stops"]
    }
    assert "CERCANA" in ruteadas
    reassigned_by_id = {camera["id"]: camera["reassigned"] for camera in body["cameras"]}
    assert reassigned_by_id["CERCANA"] is True
    assert reassigned_by_id["MIC-0"] is False


def test_optimize_rechaza_proveedor_invalido(
    client: TestClient, planilla: bytes
) -> None:
    """`provider` sólo acepta auto, osrm o haversine."""
    assert optimizar(client, planilla, provider="google").status_code == 422


# --------------------------------------------------------------------------
# Puntos de partida por cluster y presupuesto de jornada
# --------------------------------------------------------------------------


def test_optimize_exige_punto_de_partida_para_cada_cluster(
    client: TestClient, planilla: bytes
) -> None:
    """Sin punto de partida para algún cluster, 400 explícito, no un default."""
    response = optimizar(client, planilla, cluster_starts_json="{}")

    assert response.status_code == 400
    assert "punto de partida" in response.json()["detail"]


def test_optimize_rechaza_json_invalido_en_cluster_starts(
    client: TestClient, planilla: bytes
) -> None:
    """Un cluster_starts_json mal formado no debe explotar el servidor."""
    response = optimizar(client, planilla, cluster_starts_json="no es json")

    assert response.status_code == 400


def test_optimize_respeta_el_punto_de_partida_asignado(client: TestClient) -> None:
    """El recorrido sale y vuelve al punto de partida indicado, no de la cámara 0."""
    filas = [
        {"id_camara": f"MIC-{i}", "latitud": -34.6000 - i * 0.001, "longitud": -58.3816}
        for i in range(3)
    ]
    buffer = io.BytesIO()
    pd.DataFrame(filas).to_excel(buffer, index=False, engine="openpyxl")

    partida = json.dumps({"0": {"lat": -34.70, "lon": -58.40, "name": "Sede Sur"}})
    body = optimizar(
        client, buffer.getvalue(), cluster_starts_json=partida
    ).json()

    ruta = body["routes"][0]
    assert ruta["start_name"] == "Sede Sur"
    assert ruta["start_lat"] == pytest.approx(-34.70)
    assert ruta["start_lon"] == pytest.approx(-58.40)
    assert ruta["geometry"][0] == [pytest.approx(-34.70), pytest.approx(-58.40)]


def test_optimize_presupuesto_chico_parte_en_varias_jornadas(client: TestClient) -> None:
    """Un cluster que no entra en una jornada sale en varios `vehicle_day`."""
    filas = [
        {"id_camara": "N", "latitud": -34.5910, "longitud": -58.3816},
        {"id_camara": "S", "latitud": -34.6090, "longitud": -58.3816},
        {"id_camara": "E", "latitud": -34.6000, "longitud": -58.3706},
        {"id_camara": "O", "latitud": -34.6000, "longitud": -58.3926},
    ]
    buffer = io.BytesIO()
    pd.DataFrame(filas).to_excel(buffer, index=False, engine="openpyxl")

    partida = json.dumps({"0": {"lat": -34.6000, "lon": -58.3816, "name": "Base"}})
    body = optimizar(
        client,
        buffer.getvalue(),
        eps_km=5.0,  # las cuatro entran en un solo cluster
        cluster_starts_json=partida,
        day_budget_s=20 * 60,
        service_time_s=600,
    ).json()

    rutas = [route for route in body["routes"] if route["cluster_id"] == 0]
    assert len(rutas) >= 2
    assert {ruta["vehicle_day"] for ruta in rutas} == set(range(1, len(rutas) + 1))
    assert all(ruta["vehicle_day_count"] == len(rutas) for ruta in rutas)
    camaras_ruteadas = {
        stop["camera_id"] for ruta in rutas for stop in ruta["stops"]
    }
    assert camaras_ruteadas == {"N", "S", "E", "O"}


def test_optimize_presupuesto_imposible_avisa_camaras_fuera(client: TestClient) -> None:
    """Ni una visita solitaria entra: no aborta, informa qué cámaras quedaron fuera."""
    filas = [
        {"id_camara": "MIC-0", "latitud": -34.6000, "longitud": -58.3816},
        {"id_camara": "MIC-1", "latitud": -34.6001, "longitud": -58.3816},
    ]
    buffer = io.BytesIO()
    pd.DataFrame(filas).to_excel(buffer, index=False, engine="openpyxl")

    partida = json.dumps({"0": {"lat": -34.7000, "lon": -58.5000}})
    response = optimizar(
        client,
        buffer.getvalue(),
        cluster_starts_json=partida,
        day_budget_s=1,
        service_time_s=0,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["routes"] == []
    assert "MIC-0" in body["warning"]
    assert "MIC-1" in body["warning"]


def _planilla_cruz() -> bytes:
    """Cuatro cámaras a ~1 km de (-34.6, -58.3816), en cruz."""
    filas = [
        {"id_camara": "N", "latitud": -34.5910, "longitud": -58.3816},
        {"id_camara": "S", "latitud": -34.6090, "longitud": -58.3816},
        {"id_camara": "E", "latitud": -34.6000, "longitud": -58.3706},
        {"id_camara": "O", "latitud": -34.6000, "longitud": -58.3926},
    ]
    buffer = io.BytesIO()
    pd.DataFrame(filas).to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


def test_optimize_minimo_mayor_que_tope_es_error(client: TestClient) -> None:
    """Pedir más cámaras mínimas que el tope no tiene solución: 422 explícito."""
    response = optimizar(
        client, _planilla_cruz(), eps_km=5, min_stops_per_day=6, max_stops_per_day=5
    )

    assert response.status_code == 422
    assert "mínimo" in response.json()["detail"]


def test_optimize_minimo_por_dia_avisa_las_que_quedan_fuera_por_regla(
    client: TestClient,
) -> None:
    """Con 20 min por jornada sólo entra una cámara: el mínimo 2 deja tres fuera.

    El aviso tiene que apuntar al mínimo, no a "quedan muy lejos": cada una
    entraría sola.
    """
    centro = json.dumps({"0": {"lat": -34.6000, "lon": -58.3816, "name": "Base"}})
    response = optimizar(
        client,
        _planilla_cruz(),
        eps_km=5,
        cluster_starts_json=centro,
        day_budget_s=20 * 60,
        service_time_s=600,
        min_stops_per_day=2,
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["routes"]) == 1
    assert "mínimo" in body["warning"]
    assert "muy lejos" not in body["warning"]


def test_optimize_punto_de_partida_absurdo_es_error_explicito(
    client: TestClient,
) -> None:
    """Lat/lon invertidas dejan la base a miles de km: se rechaza diciéndolo."""
    filas = [
        {"id_camara": "MIC-0", "latitud": -34.6000, "longitud": -58.3816},
        {"id_camara": "MIC-1", "latitud": -34.6001, "longitud": -58.3816},
    ]
    buffer = io.BytesIO()
    pd.DataFrame(filas).to_excel(buffer, index=False, engine="openpyxl")

    invertido = json.dumps({"0": {"lat": -58.3816, "lon": -34.6000, "name": "Base"}})
    response = optimizar(client, buffer.getvalue(), cluster_starts_json=invertido)

    assert response.status_code == 422
    detalle = response.json()["detail"]
    assert "cluster 0" in detalle
    assert "invertidas" in detalle


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
    monkeypatch.setattr(OsrmProvider, "travel_matrix", demasiado_grande)

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


@pytest.mark.parametrize("endpoint", ["/upload-excel/", "/process/"])
def test_rechaza_un_excel_que_descomprimido_es_demasiado_grande(
    client: TestClient, planilla: bytes, monkeypatch, endpoint: str
) -> None:
    """Un .xlsx es un zip: unos pocos MB pueden descomprimirse en gigas y
    dejar al servidor sin memoria. Se mide antes de abrirlo con openpyxl."""
    monkeypatch.setattr(config, "MAX_XLSX_UNCOMPRESSED_BYTES", 1_000)

    response = client.post(
        endpoint,
        files={"file": ("planilla.xlsx", planilla, XLSX_MIME)},
        data={"col_id": "id_camara", "col_lat": "latitud", "col_lon": "longitud"},
    )

    assert response.status_code == 413
    assert "descomprimida" in response.json()["detail"]


def test_las_zonas_se_resuelven_en_paralelo(client: TestClient, planilla: bytes, monkeypatch) -> None:
    """Cada zona consume su límite de tiempo de OR-Tools: de a una, seis sedes
    son seis límites seguidos. Si no corrieran a la vez, la barrera vencería."""
    barrera = threading.Barrier(2, timeout=10)
    original = main._route_for_cluster

    def esperando_a_la_otra(*args, **kwargs):
        barrera.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(main, "_route_for_cluster", esperando_a_la_otra)

    response = optimizar(client, planilla)

    assert response.status_code == 200, response.text
    assert sorted({ruta["cluster_id"] for ruta in response.json()["routes"]}) == [0, 1]


def test_optimize_respeta_tope_de_camaras_por_dia(
    client: TestClient, planilla: bytes
) -> None:
    """Con tope 3, cada zona de cuatro cámaras sale en dos jornadas."""
    body = optimizar(client, planilla, max_stops_per_day=3).json()

    assert all(route["stop_count"] <= 3 for route in body["routes"])
    for cluster_id in (0, 1):
        dias = [r for r in body["routes"] if r["cluster_id"] == cluster_id]
        assert len(dias) == 2
        assert {r["vehicle_day_count"] for r in dias} == {2}
        assert sum(r["stop_count"] for r in dias) == 4


def test_optimize_tope_cero_es_sin_limite(client: TestClient, planilla: bytes) -> None:
    """El valor por defecto (0) no divide las jornadas."""
    body = optimizar(client, planilla, max_stops_per_day=0).json()

    assert len(body["routes"]) == 2


def test_optimize_junta_clusters_con_la_misma_sede_en_una_jornada(
    client: TestClient, planilla: bytes
) -> None:
    """Dos zonas con la misma sede caben en un día: una sola jornada con las ocho."""
    body = optimizar(client, planilla, merge_clusters=True).json()

    assert len(body["routes"]) == 1
    ruta = body["routes"][0]
    assert ruta["cluster_ids"] == [0, 1]
    assert ruta["cluster_id"] == 0
    assert ruta["stop_count"] == 8


def test_optimize_sin_juntar_clusters_mantiene_una_ruta_por_cluster(
    client: TestClient, planilla: bytes
) -> None:
    """Sin la opción, cada cluster sigue con sus propias jornadas."""
    body = optimizar(client, planilla, merge_clusters=False).json()

    assert [route["cluster_ids"] for route in body["routes"]] == [[0], [1]]


def test_optimize_no_junta_clusters_con_sedes_distintas(
    client: TestClient, planilla: bytes
) -> None:
    """Un vehículo sale de una sola sede: sedes distintas nunca comparten día."""
    sedes = json.dumps(
        {
            "0": {"lat": -34.6000, "lon": -58.3816, "name": "Sede A"},
            "1": {"lat": -34.5780, "lon": -58.4300, "name": "Sede B"},
        }
    )
    body = optimizar(
        client, planilla, merge_clusters=True, cluster_starts_json=sedes
    ).json()

    assert len(body["routes"]) == 2
    assert all(len(route["cluster_ids"]) == 1 for route in body["routes"])


def test_optimize_junta_clusters_respetando_el_tope_por_dia(
    client: TestClient, planilla: bytes
) -> None:
    """Con tope 4 y las dos zonas juntas salen dos jornadas llenas, sin perder cámaras."""
    body = optimizar(client, planilla, merge_clusters=True, max_stops_per_day=4).json()

    assert all(route["stop_count"] <= 4 for route in body["routes"])
    assert all(route["cluster_ids"] == [0, 1] for route in body["routes"])
    camaras = {stop["camera_id"] for route in body["routes"] for stop in route["stops"]}
    assert len(camaras) == 8
