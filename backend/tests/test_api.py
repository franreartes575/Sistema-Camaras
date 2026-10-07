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


def test_health_no_expone_configuracion_interna(client: TestClient) -> None:
    """El health es público a propósito: no debe filtrar la URL de OSRM."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "osrm_base_url" not in response.json()


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


def test_upload_sanea_el_error_de_lectura(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Un .xlsx corrupto no debe reenviar el detalle crudo de openpyxl.

    El error real (BadZipFile, con detalles de la librería) sólo llega al
    log del servidor; el cliente recibe un mensaje genérico.
    """
    with caplog.at_level("WARNING"):
        response = client.post(
            "/upload-excel/",
            files={"file": ("camaras.xlsx", b"esto no es un xlsx valido", XLSX_MIME)},
        )

    assert response.status_code == 422
    assert "zip" not in response.json()["detail"].lower()
    assert "no se pudo leer la planilla" in response.json()["detail"].lower()
    assert "zip" in caplog.text.lower()


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


def test_process_sanea_el_error_de_lectura(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Igual que /upload-excel/: un archivo ilegible no filtra detalles internos."""
    with caplog.at_level("WARNING"):
        response = client.post(
            "/process/",
            files={
                "file": ("camaras.xlsx", b"esto no es un xlsx valido", XLSX_MIME)
            },
            data={"col_id": "id_camara", "col_lat": "lat", "col_lon": "lon"},
        )

    assert response.status_code == 422
    assert "zip" not in response.json()["detail"].lower()
    assert "zip" in caplog.text.lower()


# --------------------------------------------------------------------------
# Seguimiento: reimportar el Excel completado por los técnicos
# --------------------------------------------------------------------------


@pytest.fixture
def planilla_seguimiento() -> bytes:
    """Un Excel exportado y completado: una hecha, dos pendientes y una nueva."""
    filas = [
        {"ID de la cámara": "MIC-0", "Realizado": "Sí", "Observación": None,
         "Nodo preliminar": "ATOCHA", "Latitud": -34.6037, "Longitud": -58.3816},
        {"ID de la cámara": "MIC-1", "Realizado": "No", "Observación": "Sin acceso",
         "Nodo preliminar": "ATOCHA", "Latitud": -34.6047, "Longitud": -58.3826},
        {"ID de la cámara": "MIC-2", "Realizado": None, "Observación": None,
         "Nodo preliminar": None, "Latitud": -34.6057, "Longitud": -58.3836},
        # Tarea nueva agregada al pie por el planificador.
        {"ID de la cámara": "NUEVA-1", "Realizado": None, "Observación": None,
         "Nodo preliminar": "CERRO SAN BERNARDO", "Latitud": -34.6067, "Longitud": -58.3846},
    ]
    return a_xlsx(pd.DataFrame(filas))


def test_upload_sugiere_columnas_de_seguimiento(
    client: TestClient, planilla_seguimiento: bytes
) -> None:
    """Al volver a subir el Excel, el mapeo de seguimiento se completa solo."""
    response = client.post(
        "/upload-excel/",
        files={"file": ("seguimiento.xlsx", planilla_seguimiento, XLSX_MIME)},
    )

    sugerido = response.json()["suggested_mapping"]
    assert sugerido["id"] == "ID de la cámara"
    assert sugerido["done"] == "Realizado"
    assert sugerido["node"] == "Nodo preliminar"
    assert sugerido["observation"] == "Observación"


def test_process_aparta_las_realizadas_y_conserva_el_seguimiento(
    client: TestClient, planilla_seguimiento: bytes
) -> None:
    """Las hechas no se replanifican; las pendientes traen nodo y observación."""
    response = client.post(
        "/process/",
        files={"file": ("seguimiento.xlsx", planilla_seguimiento, XLSX_MIME)},
        data={
            "col_id": "ID de la cámara",
            "col_lat": "Latitud",
            "col_lon": "Longitud",
            "col_done": "Realizado",
            "col_node": "Nodo preliminar",
            "col_obs": "Observación",
            "eps_km": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["done_rows"] == 1
    assert body["stats"]["discarded_rows"] == 0
    camaras = {camera["id"]: camera for camera in body["cameras"]}
    assert set(camaras) == {"MIC-1", "MIC-2", "NUEVA-1"}
    assert camaras["MIC-1"]["observation"] == "Sin acceso"
    assert camaras["NUEVA-1"]["node"] == "CERRO SAN BERNARDO"
    assert camaras["MIC-2"]["node"] is None


def test_process_con_todo_realizado_lo_dice(
    client: TestClient, planilla_seguimiento: bytes
) -> None:
    """Si no queda nada pendiente, el error lo explica en vez de hablar de coordenadas."""
    frame = pd.read_excel(io.BytesIO(planilla_seguimiento))
    frame["Realizado"] = "Sí"

    response = client.post(
        "/process/",
        files={"file": ("seguimiento.xlsx", a_xlsx(frame), XLSX_MIME)},
        data={
            "col_id": "ID de la cámara",
            "col_lat": "Latitud",
            "col_lon": "Longitud",
            "col_done": "Realizado",
        },
    )

    assert response.status_code == 422
    assert "realizadas" in response.json()["detail"]
