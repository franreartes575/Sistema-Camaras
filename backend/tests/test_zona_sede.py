"""Agrupar por zona de sede: una sede, un cluster; lo lejano, por cercanía.

El escenario es el norte de Salta con coordenadas reales: la sede de Tartagal
tiene que tomar Salvador Mazza (~55 km), Aguaray y General Ballivián; la de
Orán, Pichanal y Embarcación; Morillo queda lejos de las dos.
"""

import io
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.clustering import cluster_by_depot, run_dbscan

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

SEDES = [
    {"name": "Tartagal", "lat": -22.5334, "lon": -63.8024},
    {"name": "Orán", "lat": -23.1245, "lon": -64.3259},
]

# (pueblo, lat, lon, cámaras)
PUEBLOS = [
    ("Tartagal", -22.516, -63.801, 3),
    ("Mazza", -22.049, -63.694, 2),
    ("Aguaray", -22.240, -63.730, 2),
    ("Ballivian", -22.940, -63.860, 2),
    ("Oran", -23.137, -64.325, 3),
    ("Pichanal", -23.316, -64.218, 2),
    ("Embarcacion", -23.210, -64.100, 2),
    ("Morillo", -23.470, -62.700, 3),
    ("Rivadavia", -24.190, -62.880, 1),
]


def _puntos() -> pd.DataFrame:
    filas = []
    for pueblo, lat, lon, cantidad in PUEBLOS:
        for i in range(cantidad):
            filas.append({"id": f"{pueblo}-{i}", "lat": lat + i * 0.002, "lon": lon + i * 0.002})
    return pd.DataFrame(filas)


def _por_pueblo(points: pd.DataFrame, labels) -> dict[str, set[int]]:
    grupos: dict[str, set[int]] = {}
    for camera_id, label in zip(points["id"], labels, strict=True):
        grupos.setdefault(camera_id.split("-")[0], set()).add(int(label))
    return grupos


def _sedes_tuplas() -> list[tuple[float, float]]:
    return [(sede["lat"], sede["lon"]) for sede in SEDES]


# --------------------------------------------------------------------------
# cluster_by_depot
# --------------------------------------------------------------------------


def test_cada_camara_va_a_la_zona_de_su_sede() -> None:
    points = _puntos()
    labels, clusters, reassigned = cluster_by_depot(points, _sedes_tuplas(), 60, 20, 2, 1)
    grupos = _por_pueblo(points, labels)

    tartagal = {pueblo: grupos[pueblo] for pueblo in ("Tartagal", "Mazza", "Aguaray", "Ballivian")}
    assert all(ids == {0} for ids in tartagal.values())
    assert all(grupos[pueblo] == {1} for pueblo in ("Oran", "Pichanal", "Embarcacion"))
    assert [cluster["depot"] for cluster in clusters[:2]] == [0, 1]
    assert clusters[0]["size"] == 9 and clusters[1]["size"] == 7

    # Morillo, lejos de las dos sedes, forma su propio grupo después de las sedes.
    assert grupos["Morillo"] == {2}
    assert clusters[2]["depot"] is None and clusters[2]["size"] == 3
    # Rivadavia queda suelta: a ~80 km de Morillo, más que el radio de reasignación.
    assert grupos["Rivadavia"] == {-1}
    assert not reassigned.any()


def test_mas_alla_de_la_distancia_maxima_queda_sin_sede() -> None:
    points = _puntos()
    labels, clusters, _ = cluster_by_depot(points, _sedes_tuplas(), 40, 20, 2, 1)
    grupos = _por_pueblo(points, labels)

    # Mazza (~55 km) y Ballivián (~45 km) ya no son de la zona de Tartagal.
    assert grupos["Tartagal"] == {0}
    assert grupos["Mazza"] != {0} and grupos["Ballivian"] != {0}
    sin_sede = {cluster["id"] for cluster in clusters if cluster["depot"] is None}
    assert grupos["Mazza"] <= sin_sede | {-1}


def test_una_sede_sin_camaras_no_forma_cluster() -> None:
    points = _puntos()
    lejana = (-26.07, -65.97)  # Cafayate
    labels, clusters, _ = cluster_by_depot(points, [lejana, *_sedes_tuplas()], 60, 20, 2, 1)

    assert [cluster["depot"] for cluster in clusters if cluster["depot"] is not None] == [1, 2]
    assert [cluster["id"] for cluster in clusters] == list(range(len(clusters)))
    assert set(labels) - {-1} == {cluster["id"] for cluster in clusters}


def test_en_empate_gana_la_primera_sede() -> None:
    points = pd.DataFrame([{"id": "medio", "lat": -24.0, "lon": -65.0}])
    _, clusters, _ = cluster_by_depot(points, [(-24.1, -65.0), (-23.9, -65.0)], 60, 20, 2, 1)
    assert clusters[0]["depot"] == 0


def test_sin_sedes_es_el_dbscan_de_siempre() -> None:
    points = _puntos()
    labels, clusters, _ = cluster_by_depot(points, [], 60, 20, 2, 0)
    esperadas, esperados = run_dbscan(points, eps_km=20, min_samples=2)

    assert list(labels) == list(esperadas)
    assert [{k: v for k, v in c.items() if k != "depot"} for c in clusters] == esperados
    assert all(cluster["depot"] is None for cluster in clusters)


def test_la_reasignacion_de_ruido_sigue_valiendo_fuera_de_las_zonas() -> None:
    points = _puntos()
    labels, _, reassigned = cluster_by_depot(points, _sedes_tuplas(), 60, 20, 2, 5)
    grupos = _por_pueblo(points, labels)

    # Con 20 km × 5, Rivadavia se suma al grupo de Morillo.
    assert grupos["Rivadavia"] == grupos["Morillo"]
    assert reassigned[points["id"] == "Rivadavia-0"].all()


# --------------------------------------------------------------------------
# /process/ y /optimize/
# --------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def planilla() -> bytes:
    buffer = io.BytesIO()
    _puntos().rename(columns={"id": "Cámara", "lat": "Lat", "lon": "Lon"}).to_excel(
        buffer, index=False, engine="openpyxl"
    )
    return buffer.getvalue()


def _campos(**extra) -> dict:
    return {
        "col_id": "Cámara", "col_lat": "Lat", "col_lon": "Lon",
        "eps_km": "20", "noise_reassign_factor": "1", **extra,
    }


def test_process_agrupa_por_sede_y_devuelve_la_sede_de_cada_cluster(client, planilla) -> None:
    response = client.post(
        "/process/",
        files={"file": ("norte.xlsx", planilla, XLSX_MIME)},
        data=_campos(group_by_depot="true", depots_json=json.dumps(SEDES)),
    )
    assert response.status_code == 200, response.text
    datos = response.json()

    clusters = datos["clusters"]
    assert [c["depot"]["name"] if c["depot"] else None for c in clusters] == ["Tartagal", "Orán", None]
    camaras = {c["id"]: c["cluster"] for c in datos["cameras"]}
    assert camaras["Mazza-0"] == camaras["Ballivian-1"] == camaras["Tartagal-0"] == 0
    assert camaras["Rivadavia-0"] == -1
    assert "a más de 60 km de toda sede" in datos["warning"]


def test_process_sin_agrupar_por_sede_no_cambia(client, planilla) -> None:
    sin = client.post("/process/", files={"file": ("n.xlsx", planilla, XLSX_MIME)}, data=_campos())
    apagado = client.post(
        "/process/",
        files={"file": ("n.xlsx", planilla, XLSX_MIME)},
        data=_campos(group_by_depot="false", depots_json=json.dumps(SEDES)),
    )
    assert sin.json()["clusters"] == apagado.json()["clusters"]
    assert all(cluster["depot"] is None for cluster in sin.json()["clusters"])

    # Activado pero sin sedes: también por cercanía.
    vacio = client.post(
        "/process/",
        files={"file": ("n.xlsx", planilla, XLSX_MIME)},
        data=_campos(group_by_depot="true", depots_json="[]"),
    )
    assert vacio.json()["clusters"] == sin.json()["clusters"]


@pytest.mark.parametrize(
    "depots_json",
    [
        "no es json",
        json.dumps({"name": "x"}),
        json.dumps([{"name": "x", "lat": 95, "lon": 0}]),
        json.dumps([{"name": "x", "lat": "NaN", "lon": 0}]),
        json.dumps([{"name": "x", "lat": 0}]),
        json.dumps([{"name": "x", "lat": 0, "lon": 0}] * 101),
    ],
)
def test_sedes_invalidas_son_400(client, planilla, depots_json) -> None:
    response = client.post(
        "/process/",
        files={"file": ("n.xlsx", planilla, XLSX_MIME)},
        data=_campos(group_by_depot="true", depots_json=depots_json),
    )
    assert response.status_code == 400


def test_optimize_con_las_salidas_de_cada_sede(client, planilla) -> None:
    starts = {
        "0": SEDES[0],
        "1": SEDES[1],
        "2": {"lat": -23.47, "lon": -62.70, "name": None},
    }
    response = client.post(
        "/optimize/",
        files={"file": ("norte.xlsx", planilla, XLSX_MIME)},
        data=_campos(
            group_by_depot="true",
            depots_json=json.dumps(SEDES),
            provider="haversine",
            cluster_starts_json=json.dumps(starts),
            day_budget_s="36000",
            average_speed_kmh="60",
        ),
    )
    assert response.status_code == 200, response.text
    rutas = response.json()["routes"]
    salidas = {route["start_name"] for route in rutas}
    assert {"Tartagal", "Orán"} <= salidas
    paradas = {stop["camera_id"] for route in rutas for stop in route["stops"]}
    assert {"Mazza-0", "Aguaray-1", "Ballivian-0", "Pichanal-0", "Morillo-2"} <= paradas


# --------------------------------------------------------------------------
# Catálogo
# --------------------------------------------------------------------------


def _cargar_catalogo(client: TestClient, planilla: bytes) -> None:
    response = client.post(
        "/catalogo/importar/",
        files={"file": ("norte.xlsx", planilla, XLSX_MIME)},
        data={"col_id": "Cámara", "col_lat": "Lat", "col_lon": "Lon"},
    )
    assert response.status_code == 200, response.text
    for sede in SEDES:
        assert client.post("/catalogo/sedes/", json=sede).status_code == 201


def test_el_mapa_del_inicio_agrupa_por_sede(client, planilla) -> None:
    _cargar_catalogo(client, planilla)

    datos = client.get("/catalogo/clusters").json()
    assert datos["by_depot"] is True and datos["depot_max_km"] == 60
    camaras = {c["id"]: c["cluster"] for c in datos["cameras"]}
    tartagal = next(c for c in datos["clusters"] if c["depot"] and c["depot"]["name"] == "Tartagal")
    assert camaras["Mazza-1"] == camaras["Aguaray-0"] == camaras["Ballivian-0"] == tartagal["id"]
    morillo = camaras["Morillo-0"]
    assert next(c for c in datos["clusters"] if c["id"] == morillo)["depot"] is None
    # En el mapa el ruido se reasigna dentro de un radio: Rivadavia queda suelta.
    assert camaras["Rivadavia-0"] == -1

    por_cercania = client.get("/catalogo/clusters", params={"por_sede": "false"}).json()
    assert por_cercania["by_depot"] is False
    assert all(cluster["depot"] is None for cluster in por_cercania["clusters"])
    cercania = {c["id"]: c["cluster"] for c in por_cercania["cameras"]}
    assert cercania["Mazza-0"] != cercania["Tartagal-0"]


def test_el_resumen_cuenta_las_zonas_de_cada_sede(client, planilla) -> None:
    _cargar_catalogo(client, planilla)

    resumen = client.get("/catalogo/resumen").json()
    zonas = {sede["name"]: sede["cameras"] for sede in resumen["depots"]}
    assert zonas == {"Orán": 7, "Tartagal": 9}
    assert resumen["depot_max_km"] == 60
    assert resumen["outside_depots"] == 4  # Morillo y Rivadavia

    amplio = client.get("/catalogo/resumen", params={"max_sede_km": 500}).json()
    assert amplio["outside_depots"] == 0
