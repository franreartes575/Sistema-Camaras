"""Tests de integración de los endpoints HTTP."""

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def client() -> TestClient:
    """Cliente HTTP sobre la app, sin levantar un servidor real."""
    return TestClient(app)


def a_xlsx(frame: pd.DataFrame) -> bytes:
    """Serializa un DataFrame a .xlsx en memoria."""
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


@pytest.fixture
def planilla_split() -> bytes:
    """Dos zonas de tres cámaras, con lat y lon en columnas separadas."""
    filas = [
        {
            "id_camara": f"MIC-{i}",
            "direccion": f"Microcentro {i}",
            "latitud": -34.6037 + i * 0.001,
            "longitud": -58.3816 + i * 0.001,
        }
        for i in range(3)
    ] + [
        {
            "id_camara": f"PAL-{i}",
            "direccion": f"Palermo {i}",
            "latitud": -34.5780 + i * 0.001,
            "longitud": -58.4300 + i * 0.001,
        }
        for i in range(3)
    ]
    return a_xlsx(pd.DataFrame(filas))


@pytest.fixture
def planilla_single() -> bytes:
    """Las mismas cámaras con las coordenadas juntas y coma decimal."""
    filas = [
        {
            "id_camara": f"MIC-{i}",
            "direccion": f"Microcentro {i}",
            "coordenadas": (
                f"{-34.6037 + i * 0.001:.6f},{-58.3816 + i * 0.001:.6f}"
            ).replace(".", ","),
        }
        for i in range(4)
    ]
    return a_xlsx(pd.DataFrame(filas))


# --------------------------------------------------------------------------
# GET /health
# --------------------------------------------------------------------------


def test_health_informa_osrm(client: TestClient) -> None:
    """El health expone a qué instancia de OSRM apunta el backend."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "osrm_base_url" in response.json()


# --------------------------------------------------------------------------
# POST /upload-excel/
# --------------------------------------------------------------------------


def test_upload_devuelve_encabezados(client: TestClient, planilla_split: bytes) -> None:
    """Lee sólo la primera fila y sugiere el mapeo."""
    response = client.post(
        "/upload-excel/",
        files={"file": ("camaras.xlsx", planilla_split, XLSX_MIME)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["column_count"] == 4
    assert body["suggested_mapping"]["lat"] == "latitud"
    assert body["suggested_mapping"]["mode"] == "split"


def test_upload_detecta_columna_unica(
    client: TestClient, planilla_single: bytes
) -> None:
    """Con coordenadas combinadas sugiere el modo single."""
    response = client.post(
        "/upload-excel/",
        files={"file": ("camaras.xlsx", planilla_single, XLSX_MIME)},
    )

    assert response.json()["suggested_mapping"]["mode"] == "single"
    assert response.json()["suggested_mapping"]["coords"] == "coordenadas"


def test_upload_rechaza_extension_no_soportada(client: TestClient) -> None:
    """Un .txt no es una planilla."""
    response = client.post(
        "/upload-excel/", files={"file": ("notas.txt", b"hola", "text/plain")}
    )

    assert response.status_code == 400
    assert ".txt" in response.json()["detail"]


def test_upload_rechaza_archivo_vacio(client: TestClient) -> None:
    """Un archivo sin bytes se corta antes de llegar a pandas."""
    response = client.post(
        "/upload-excel/", files={"file": ("vacio.xlsx", b"", XLSX_MIME)}
    )

    assert response.status_code == 400


# --------------------------------------------------------------------------
# POST /process/
# --------------------------------------------------------------------------


def test_process_agrupa_dos_columnas(client: TestClient, planilla_split: bytes) -> None:
    """Modo split: seis cámaras en dos clusters."""
    response = client.post(
        "/process/",
        files={"file": ("camaras.xlsx", planilla_split, XLSX_MIME)},
        data={
            "col_id": "id_camara",
            "col_lat": "latitud",
            "col_lon": "longitud",
            "col_label": "direccion",
            "eps_km": 1.0,
            "min_samples": 2,
        },
    )

    assert response.status_code == 200
    stats = response.json()["stats"]
    assert stats["valid_rows"] == 6
    assert stats["cluster_count"] == 2
    assert stats["discarded_rows"] == 0


def test_process_agrupa_columna_unica(
    client: TestClient, planilla_single: bytes
) -> None:
    """Modo single con coma decimal: las cuatro filas se parsean."""
    response = client.post(
        "/process/",
        files={"file": ("camaras.xlsx", planilla_single, XLSX_MIME)},
        data={
            "col_id": "id_camara",
            "col_coords": "coordenadas",
            "coord_order": "auto",
            "eps_km": 1.0,
            "min_samples": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["valid_rows"] == 4
    assert body["cameras"][0]["lat"] == pytest.approx(-34.6037)


def test_process_exige_coordenadas(client: TestClient, planilla_split: bytes) -> None:
    """Sin lat/lon ni columna combinada devuelve 400 con un mensaje accionable."""
    response = client.post(
        "/process/",
        files={"file": ("camaras.xlsx", planilla_split, XLSX_MIME)},
        data={"col_id": "id_camara"},
    )

    assert response.status_code == 400
    assert "columna combinada" in response.json()["detail"]


def test_process_rechaza_columna_inexistente(
    client: TestClient, planilla_split: bytes
) -> None:
    """El error nombra la columna que no existe."""
    response = client.post(
        "/process/",
        files={"file": ("camaras.xlsx", planilla_split, XLSX_MIME)},
        data={"col_id": "id_camara", "col_lat": "no_existe", "col_lon": "longitud"},
    )

    assert response.status_code == 400
    assert "no_existe" in response.json()["detail"]


def test_process_rechaza_orden_invalido(
    client: TestClient, planilla_single: bytes
) -> None:
    """`coord_order` sólo acepta auto, latlon o lonlat."""
    response = client.post(
        "/process/",
        files={"file": ("camaras.xlsx", planilla_single, XLSX_MIME)},
        data={
            "col_id": "id_camara",
            "col_coords": "coordenadas",
            "coord_order": "cualquiera",
        },
    )

    assert response.status_code == 422


def test_process_sin_coordenadas_validas(client: TestClient) -> None:
    """Si el mapeo apunta a datos no geográficos, lo dice explícitamente."""
    frame = pd.DataFrame({"id_camara": ["A", "B"], "lat": ["x", "y"], "lon": ["z", "w"]})

    response = client.post(
        "/process/",
        files={"file": ("camaras.xlsx", a_xlsx(frame), XLSX_MIME)},
        data={"col_id": "id_camara", "col_lat": "lat", "col_lon": "lon"},
    )

    assert response.status_code == 422
    assert "mapeo" in response.json()["detail"].lower()
