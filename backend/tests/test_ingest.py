"""Tests de lectura, mapeo y validación de planillas."""

import pandas as pd
import pytest

from app.services.ingest import (
    extract_points,
    parse_coord_cell,
    split_done,
    suggest_mapping,
)


# --------------------------------------------------------------------------
# parse_coord_cell — celdas con latitud y longitud juntas
# --------------------------------------------------------------------------

BUENOS_AIRES = (-34.6037, -58.3816)


@pytest.mark.parametrize(
    "cell",
    [
        "-34.6037,-58.3816",
        "-34.6037, -58.3816",
        "  -34.6037 , -58.3816  ",
        "(-34.6037, -58.3816)",
        "-34.6037|-58.3816",
    ],
    ids=["simple", "con espacio", "con padding", "entre parentesis", "pipe"],
)
def test_parsea_punto_decimal(cell: str) -> None:
    """El formato internacional con punto decimal se lee directo."""
    assert parse_coord_cell(cell, "auto") == pytest.approx(BUENOS_AIRES)


@pytest.mark.parametrize(
    "cell",
    [
        "-34,6037,-58,3816",  # cuatro comas: decimal en ambos valores
        "-34,6037;-58,3816",  # punto y coma separador
        "-34,6037 -58,3816",  # espacio separador
        "-34,6037,-58.3816",  # tres comas: decimal en uno solo
        "-34.6037,-58,3816",
    ],
    ids=["4 comas", "punto y coma", "espacio", "mixto A", "mixto B"],
)
def test_parsea_coma_decimal(cell: str) -> None:
    """Excel en configuración es-AR exporta con coma decimal."""
    assert parse_coord_cell(cell, "auto") == pytest.approx(BUENOS_AIRES)


def test_auto_detecta_orden_por_rango() -> None:
    """Un valor fuera de ±90 sólo puede ser longitud, venga en el orden que venga."""
    los_angeles = (34.0522, -118.2437)
    assert parse_coord_cell("-118.2437,34.0522", "auto") == pytest.approx(los_angeles)
    assert parse_coord_cell("34.0522,-118.2437", "auto") == pytest.approx(los_angeles)


def test_orden_explicito_lonlat() -> None:
    """Con lonlat se invierte el par declarado."""
    assert parse_coord_cell("-58.3816,-34.6037", "lonlat") == pytest.approx(
        BUENOS_AIRES
    )
    assert parse_coord_cell("-58,3816,-34,6037", "lonlat") == pytest.approx(
        BUENOS_AIRES
    )


def test_orden_ambiguo_asume_latlon() -> None:
    """Si ambos valores caben en ±90 el rango no desempata: se asume lat,lon."""
    assert parse_coord_cell("-34,6037,-58,3816", "auto") == pytest.approx(BUENOS_AIRES)


@pytest.mark.parametrize(
    "cell",
    ["", "sin datos", "-34.6037", "999,999", "0,0", None],
    ids=["vacio", "texto", "un solo valor", "fuera de rango", "isla nula", "None"],
)
def test_rechaza_celdas_invalidas(cell: object) -> None:
    """Todo lo que no sea un par geográfico válido se rechaza."""
    assert parse_coord_cell(cell, "auto") is None


# --------------------------------------------------------------------------
# suggest_mapping — inferencia del rol de cada columna
# --------------------------------------------------------------------------


def test_sugiere_dos_columnas() -> None:
    """Con lat y lon separadas arranca en modo split."""
    result = suggest_mapping(["id_camara", "direccion", "latitud", "longitud"])

    assert result["mode"] == "split"
    assert result["id"] == "id_camara"
    assert result["lat"] == "latitud"
    assert result["lon"] == "longitud"
    assert result["label"] == "direccion"


def test_sugiere_columna_unica() -> None:
    """Sin par lat/lon pero con columna combinada arranca en modo single."""
    result = suggest_mapping(["id_camara", "direccion", "coordenadas"])

    assert result["mode"] == "single"
    assert result["coords"] == "coordenadas"


def test_sugiere_split_cuando_no_reconoce_nada() -> None:
    """Sin coincidencias cae al modo por defecto sin romper."""
    result = suggest_mapping(["columna_a", "columna_b"])

    assert result["mode"] == "split"
    assert result["lat"] is None
    assert result["coords"] is None


# --------------------------------------------------------------------------
# extract_points — validación de filas
# --------------------------------------------------------------------------


def test_extrae_dos_columnas() -> None:
    """Modo split sobre datos limpios."""
    frame = pd.DataFrame(
        {
            "id_camara": ["A", "B"],
            "lat": [-34.60, -34.61],
            "lon": [-58.38, -58.39],
        }
    )

    points, discarded = extract_points(frame, "id_camara", "lat", "lon")

    assert len(points) == 2
    assert discarded == []


def test_extrae_columna_unica_con_coma_decimal() -> None:
    """Modo single con el formato es-AR."""
    frame = pd.DataFrame(
        {
            "id_camara": ["A", "B"],
            "coordenadas": ["-34,6037,-58,3816", "-34,6050,-58,3800"],
        }
    )

    points, discarded = extract_points(
        frame, "id_camara", col_coords="coordenadas", coord_order="auto"
    )

    assert len(points) == 2
    assert discarded == []
    assert points.iloc[0]["lat"] == pytest.approx(-34.6037)


@pytest.mark.parametrize(
    ("lat", "lon", "reason"),
    [
        (None, None, "Coordenada vacía o no numérica"),
        (999.0, -58.0, "Coordenada fuera de rango válido"),
        (0.0, 0.0, "Coordenada nula (0,0)"),
    ],
    ids=["vacia", "fuera de rango", "isla nula"],
)
def test_descarta_filas_invalidas(
    lat: float | None, lon: float | None, reason: str
) -> None:
    """Cada fila descartada informa su motivo y su número de fila."""
    frame = pd.DataFrame(
        {
            "id_camara": ["OK", "MALA"],
            "lat": [-34.60, lat],
            "lon": [-58.38, lon],
        }
    )

    points, discarded = extract_points(frame, "id_camara", "lat", "lon")

    assert len(points) == 1
    assert discarded == [{"row": 2, "reason": reason}]


def test_exige_alguna_columna_de_coordenadas() -> None:
    """Sin lat/lon ni columna combinada el mapeo es inválido."""
    frame = pd.DataFrame({"id_camara": ["A"]})

    with pytest.raises(ValueError, match="columna combinada"):
        extract_points(frame, "id_camara")


def test_rechaza_columna_inexistente() -> None:
    """El error nombra la columna que falta, para que el usuario la corrija."""
    frame = pd.DataFrame({"id_camara": ["A"], "lat": [-34.6], "lon": [-58.4]})

    with pytest.raises(ValueError, match="no_existe"):
        extract_points(frame, "id_camara", "no_existe", "lon")


# --------------------------------------------------------------------------
# Regresion: una columna que nombra ambas coordenadas
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "columna",
    [
        "Latitud y Longitud",
        "LATITUD/LONGITUD",
        "Lat-Long",
        "Coordenadas (Latitud, Longitud)",
        "LAT LONG",
        "lat_lon",
    ],
)
def test_columna_que_nombra_ambas_coordenadas_es_combinada(columna: str) -> None:
    """Regresion: se asignaba la misma columna a latitud y a longitud.

    El detector elegia modo 'split' con col_lat == col_lon, y al convertir ese
    texto a numero daba NaN en todas las filas. El usuario veia un 422 sin
    ninguna pista de que el mapeo era el problema.
    """
    result = suggest_mapping(["id_camara", "direccion", columna])

    assert result["mode"] == "single"
    assert result["coords"] == columna
    # Lo esencial: nunca la misma columna en los dos roles.
    assert not (result["lat"] is not None and result["lat"] == result["lon"])


def test_dos_columnas_separadas_siguen_en_modo_split() -> None:
    """El caso normal no debe verse afectado por la correccion."""
    result = suggest_mapping(["id_camara", "Latitud", "Longitud"])

    assert result["mode"] == "split"
    assert result["lat"] == "Latitud"
    assert result["lon"] == "Longitud"


def test_rechaza_lat_y_lon_apuntando_a_la_misma_columna() -> None:
    """Si el usuario fuerza ese mapeo a mano, el error lo explica."""
    frame = pd.DataFrame(
        {"id_camara": ["A"], "Coordenadas": ["-24,7859,-65,4117"]}
    )

    with pytest.raises(ValueError, match="misma columna"):
        extract_points(frame, "id_camara", "Coordenadas", "Coordenadas")


def test_columna_combinada_con_nombre_ambiguo_se_parsea() -> None:
    """El flujo completo con el nombre que disparaba el bug."""
    frame = pd.DataFrame(
        {
            "id_camara": ["CAM-1", "CAM-2"],
            "Latitud y Longitud": ["-24,7859,-65,4117", "-24,7870,-65,4107"],
        }
    )
    sugerencia = suggest_mapping(list(frame.columns))

    points, discarded = extract_points(
        frame, "id_camara", col_coords=sugerencia["coords"], coord_order="auto"
    )

    assert len(points) == 2
    assert discarded == []
    assert points.iloc[0]["lat"] == pytest.approx(-24.7859)
    assert points.iloc[0]["lon"] == pytest.approx(-65.4117)


# --------------------------------------------------------------------------
# Regresion: exportacion de cnMaestro (planilla de camaras de Martearena)
# --------------------------------------------------------------------------

CNMAESTRO_COLUMNS = [
    "Device Name",
    "IP Address",
    "Device Type",
    "MAC",
    "Latitude",
    "Longitude",
    "Nodo a Migrar",
]


def test_sugiere_device_name_como_id_de_camara() -> None:
    """cnMaestro nombra a la camara en 'Device Name'; no hay otra columna de id."""
    result = suggest_mapping(CNMAESTRO_COLUMNS)

    assert result["id"] == "Device Name"
    assert result["lat"] == "Latitude"
    assert result["lon"] == "Longitude"


def test_ip_address_no_es_una_direccion_postal() -> None:
    """'IP Address' contiene 'address' pero no es un domicilio."""
    assert suggest_mapping(CNMAESTRO_COLUMNS)["label"] is None
    assert suggest_mapping(["id", "Address", "lat", "lon"])["label"] == "Address"


def test_coordenadas_enteras_escaladas_se_reescalan() -> None:
    """cnMaestro exporta microgrados sin punto decimal: -24845092 es -24.845092.

    Antes se descartaban todas las filas por 'fuera de rango'.
    """
    frame = pd.DataFrame(
        {
            "Device Name": ["1-0099", "1-0461", "1-9999"],
            "Latitude": [-24845092.0, -24828979.0, None],
            "Longitude": [-65448486.0, -65419006.0, None],
        }
    )

    points, discarded = extract_points(frame, "Device Name", "Latitude", "Longitude")

    assert list(points["id"]) == ["1-0099", "1-0461"]
    assert points.iloc[0]["lat"] == pytest.approx(-24.845092)
    assert points.iloc[0]["lon"] == pytest.approx(-65.448486)
    assert discarded == [{"row": 3, "reason": "Coordenada vacía o no numérica"}]


def test_escala_comun_la_fija_la_longitud() -> None:
    """Una latitud de un digito entero admitiria una escala menor; la longitud la desempata."""
    frame = pd.DataFrame(
        {"id": ["A"], "lat": [-8500000], "lon": [-65448486]}
    )

    points, _ = extract_points(frame, "id", "lat", "lon")

    assert points.iloc[0]["lat"] == pytest.approx(-8.5)
    assert points.iloc[0]["lon"] == pytest.approx(-65.448486)


def test_no_reescala_si_hay_coordenadas_en_grados() -> None:
    """Un valor fuera de rango suelto entre grados normales sigue siendo un error."""
    frame = pd.DataFrame(
        {"id": ["A", "B"], "lat": [-24.8, -24845092.0], "lon": [-65.4, -65448486.0]}
    )

    points, discarded = extract_points(frame, "id", "lat", "lon")

    assert list(points["id"]) == ["A"]
    assert discarded == [{"row": 2, "reason": "Coordenada fuera de rango válido"}]


def test_no_reescala_decimales_fuera_de_rango() -> None:
    """Sólo los enteros son una escala plausible; 999.5 es simplemente inválido."""
    frame = pd.DataFrame({"id": ["A"], "lat": [999.5], "lon": [-5800.25]})

    points, discarded = extract_points(frame, "id", "lat", "lon")

    assert points.empty
    assert discarded[0]["reason"] == "Coordenada fuera de rango válido"


# --------------------------------------------------------------------------
# Seguimiento: nodo preliminar, observación y "Realizado"
# --------------------------------------------------------------------------

# Encabezados del Excel que exporta la app (ver services/export.py).
EXPORT_COLUMNS = [
    "ID de la cámara",
    "Fecha de planificación",
    "Orden",
    "Realizado",
    "Observación",
    "Nodo al cual se migró",
    "Nodo preliminar",
    "Latitud",
    "Longitud",
]


def test_sugiere_el_mapeo_del_excel_exportado() -> None:
    """El Excel que exporta la app se vuelve a subir sin mapear nada a mano."""
    result = suggest_mapping(EXPORT_COLUMNS)

    assert result["id"] == "ID de la cámara"
    assert result["lat"] == "Latitud"
    assert result["lon"] == "Longitud"
    assert result["node"] == "Nodo preliminar"
    assert result["observation"] == "Observación"
    assert result["done"] == "Realizado"


def test_nodo_a_migrar_de_cnmaestro_es_el_nodo_preliminar() -> None:
    """En la planilla original el nodo preliminar se llama "Nodo a Migrar"."""
    result = suggest_mapping(CNMAESTRO_COLUMNS)

    assert result["node"] == "Nodo a Migrar"
    assert result["done"] is None


def test_extrae_nodo_y_observacion_sin_arrastrar_nan() -> None:
    """Las celdas vacías de columnas opcionales quedan en None, no en 'nan'."""
    frame = pd.DataFrame(
        {
            "id": ["A", "B"],
            "lat": [-34.60, -34.61],
            "lon": [-58.38, -58.39],
            "nodo": ["ATOCHA", None],
            "obs": [None, "  Sin acceso al poste  "],
        }
    )

    points, _ = extract_points(frame, "id", "lat", "lon", col_node="nodo", col_obs="obs")

    assert points["node"].tolist() == ["ATOCHA", None]
    assert points["observation"].tolist() == [None, "Sin acceso al poste"]


@pytest.mark.parametrize(
    "marca", ["Sí", "si", "SI", "x", "X", "✓", "✔", "TRUE", True, 1, "ok", "Hecho", "realizado"]
)
def test_las_filas_realizadas_se_apartan(marca: object) -> None:
    """Todas las formas razonables de tildar "Realizado" cuentan como hecha."""
    frame = pd.DataFrame(
        {"id": ["HECHA", "PENDIENTE"], "realizado": [marca, None]}
    )

    pending, done = split_done(frame, "realizado")

    assert done == 1
    assert pending["id"].tolist() == ["PENDIENTE"]


@pytest.mark.parametrize("marca", ["No", "no", "", None, False, 0, "pendiente"])
def test_no_realizado_sigue_pendiente(marca: object) -> None:
    """Un "No", una celda vacía o texto libre no marcan la tarea como hecha."""
    frame = pd.DataFrame({"id": ["A"], "realizado": [marca]})

    pending, done = split_done(frame, "realizado")

    assert done == 0
    assert len(pending) == 1


def test_apartar_realizadas_conserva_el_numero_de_fila() -> None:
    """Las filas descartadas después informan su fila original en la planilla."""
    frame = pd.DataFrame(
        {
            "id": ["HECHA", "MALA", "OK"],
            "realizado": ["Sí", None, None],
            "lat": [-34.60, None, -34.61],
            "lon": [-58.38, None, -58.39],
        }
    )

    pending, _ = split_done(frame, "realizado")
    points, discarded = extract_points(pending, "id", "lat", "lon")

    assert points["id"].tolist() == ["OK"]
    assert discarded == [{"row": 2, "reason": "Coordenada vacía o no numérica"}]


def test_sin_columna_de_realizado_no_aparta_nada() -> None:
    """Sin columna mapeada, todas las filas siguen pendientes."""
    frame = pd.DataFrame({"id": ["A", "B"]})

    pending, done = split_done(frame, None)

    assert done == 0
    assert len(pending) == 2
