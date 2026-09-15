"""Tests de lectura, mapeo y validación de planillas."""

import pandas as pd
import pytest

from app.services.ingest import (
    extract_points,
    parse_coord_cell,
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
