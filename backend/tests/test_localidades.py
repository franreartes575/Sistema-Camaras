"""Localidad por coordenadas: punto en polígono, bordes y preparación de los límites."""

import json
import os
from pathlib import Path

import pytest

from app import catalogo_cli, config
from app.services import localidades

from .municipios_de_prueba import GEOJSON, escribir

# El archivo real, si ya se generó (se toma antes de que el fixture autouse
# de conftest lo cambie por uno temporal).
ARCHIVO_REAL = Path(__file__).resolve().parent.parent / "app" / "data" / "municipios_salta.geojson"


@pytest.fixture
def limites() -> localidades.Limites:
    return localidades.desde_geojson(GEOJSON)


@pytest.mark.parametrize(
    ("lat", "lon", "esperada"),
    [
        (-24.75, -65.45, "Salta"),
        (-24.80, -65.40, "Enclave"),  # dentro del hueco de Salta
        (-24.95, -65.40, "Cerrillos"),
        (-23.15, -64.35, "Islas"),  # primera parte
        (-22.50, -63.80, "Islas"),  # segunda parte
    ],
)
def test_ubica_el_punto_en_su_municipio(limites, lat, lon, esperada) -> None:
    assert limites.localidad_de(lat, lon) == esperada


def test_entre_dos_municipios_toma_el_mas_cercano(limites) -> None:
    """La simplificación deja huecos angostos en los bordes: no son "fuera"."""
    assert limites.localidad_de(-24.905, -65.40) == "Salta"  # a ~0,6 km de Salta
    assert limites.localidad_de(-24.917, -65.40) == "Cerrillos"  # a ~0,3 km de Cerrillos


def test_lejos_de_todo_queda_fuera_de_salta(limites) -> None:
    assert limites.localidad_de(-26.5, -67.0) == localidades.FUERA_DE_SALTA
    # Justo afuera de la caja de Islas pero a más de 5 km.
    assert limites.localidad_de(-23.0, -64.0) == localidades.FUERA_DE_SALTA


def test_ignora_features_sin_nombre_o_sin_geometria(limites) -> None:
    assert limites.nombres == ["Cerrillos", "Enclave", "Islas", "Salta"]


def test_sin_poligonos_es_un_error() -> None:
    with pytest.raises(ValueError):
        localidades.desde_geojson({"features": []})
    with pytest.raises(ValueError, match="Geometría no soportada"):
        localidades.desde_geojson(
            {"features": [{"properties": {"nombre": "X"}, "geometry": {"type": "Point", "coordinates": [0, 0]}}]}
        )


def test_sin_archivo_queda_sin_calcular() -> None:
    assert localidades.cargar() is None
    assert localidades.localidad_de(-24.75, -65.45) == localidades.SIN_CALCULAR


def test_con_archivo_usa_los_limites_y_los_recarga_si_cambian() -> None:
    ruta = escribir(config.MUNICIPIOS_PATH)
    assert localidades.localidad_de(-24.75, -65.45) == "Salta"

    otro = json.loads(json.dumps(GEOJSON))
    otro["features"][0]["properties"]["nombre"] = "Salta Capital"
    ruta.write_text(json.dumps(otro), encoding="utf-8")
    stat = ruta.stat()
    os.utime(ruta, (stat.st_atime, stat.st_mtime + 5))  # otra fecha, aunque el FS sea grueso

    assert localidades.localidad_de(-24.75, -65.45) == "Salta Capital"


@pytest.mark.skipif(not ARCHIVO_REAL.exists(), reason="todavía no se generaron los límites reales")
@pytest.mark.parametrize(
    ("lat", "lon", "contiene"),
    [
        (-24.7883, -65.4106, "salta"),  # plaza 9 de Julio
        (-24.9008, -65.4847, "cerrillos"),
        (-23.1371, -64.3254, "orán"),
        (-22.5161, -63.8017, "tartagal"),
    ],
)
def test_los_limites_reales_ubican_ciudades_conocidas(lat, lon, contiene) -> None:
    limites = localidades.cargar(str(ARCHIVO_REAL))
    assert limites is not None
    assert contiene in limites.localidad_de(lat, lon).lower()


# --------------------------------------------------------------------------
# preparar-municipios
# --------------------------------------------------------------------------


def _feature(nombre: str, codigo: str, anillo: list, **extra) -> dict:
    return {
        "type": "Feature",
        "properties": {"nam": nombre, "in1": codigo, **extra},
        "geometry": {"type": "Polygon", "coordinates": [anillo]},
    }


def _anillo_denso(lon_min, lat_min, lon_max, lat_max, pasos=50) -> list:
    """Un cuadrado con muchos vértices alineados: la simplificación los saca."""
    lados = []
    for i in range(pasos):
        lados.append([lon_min + (lon_max - lon_min) * i / pasos, lat_min])
    for i in range(pasos):
        lados.append([lon_max, lat_min + (lat_max - lat_min) * i / pasos])
    for i in range(pasos):
        lados.append([lon_max - (lon_max - lon_min) * i / pasos, lat_max])
    for i in range(pasos):
        lados.append([lon_min, lat_max - (lat_max - lat_min) * i / pasos])
    lados.append(lados[0])
    return lados


def test_simplificar_saca_los_vertices_alineados() -> None:
    anillo = [tuple(p) for p in _anillo_denso(-65.5, -24.9, -65.3, -24.7)]
    simple = catalogo_cli.simplificar(anillo, 0.0005)
    assert len(simple) == 5
    assert simple[0] == simple[-1]
    # Un triángulo no se puede achicar más: queda como está.
    triangulo = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, 0.0)]
    assert catalogo_cli.simplificar(triangulo, 10) == triangulo


def test_normalizar_filtra_por_codigo_y_junta_partes() -> None:
    datos = {
        "features": [
            _feature("Salta", "660014", _anillo_denso(-65.5, -24.9, -65.3, -24.7)),
            _feature("Islas", "660021", _anillo_denso(-64.4, -23.2, -64.3, -23.1)),
            _feature("Islas", "660021", _anillo_denso(-63.85, -22.55, -63.75, -22.45)),
            _feature("San Salvador de Jujuy", "380007", _anillo_denso(-65.4, -24.3, -65.2, -24.1)),
            _feature("", "660099", _anillo_denso(-65.0, -25.0, -64.9, -24.9)),
        ]
    }
    resultado = catalogo_cli.normalizar(datos)
    nombres = [f["properties"]["nombre"] for f in resultado["features"]]
    assert nombres == ["Islas", "Salta"]
    islas = resultado["features"][0]["geometry"]
    assert islas["type"] == "MultiPolygon" and len(islas["coordinates"]) == 2
    assert len(resultado["features"][1]["geometry"]["coordinates"][0][0]) == 5

    limites = localidades.desde_geojson(resultado)
    assert limites.localidad_de(-24.75, -65.45) == "Salta"
    assert limites.localidad_de(-22.5, -63.8) == "Islas"


def test_normalizar_da_vuelta_lat_lon_si_vienen_invertidas() -> None:
    anillo = [[lat, lon] for lon, lat in _anillo_denso(-65.5, -24.9, -65.3, -24.7)]
    resultado = catalogo_cli.normalizar({"features": [_feature("Salta", "660014", anillo)]})
    limites = localidades.desde_geojson(resultado)
    assert limites.localidad_de(-24.75, -65.45) == "Salta"


def test_normalizar_contra_la_provincia_cuando_no_hay_codigo() -> None:
    provincia = localidades.desde_geojson(
        {
            "features": [
                {
                    "properties": {"nombre": "Salta"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [_anillo_denso(-66.0, -25.5, -64.0, -23.0, pasos=2)],
                    },
                }
            ]
        }
    )
    datos = {
        "features": [
            _feature("Adentro", "", _anillo_denso(-65.5, -24.9, -65.3, -24.7)),
            _feature("Afuera", "", _anillo_denso(-63.0, -22.0, -62.8, -21.8)),
        ]
    }
    resultado = catalogo_cli.normalizar(datos, provincia=provincia)
    assert [f["properties"]["nombre"] for f in resultado["features"]] == ["Adentro"]


def test_preparar_desde_archivo_guarda_y_recalcula(tmp_path, capsys) -> None:
    from app import database
    from app.services import catalogo

    conn = database.connect()
    with conn:
        conn.execute("INSERT INTO camaras (id, lat, lon) VALUES ('C-1', -24.75, -65.45)")
    conn.close()

    archivo = tmp_path / "descargado.geojson"
    archivo.write_text(
        json.dumps({"features": [_feature("Salta", "660014", _anillo_denso(-65.5, -24.9, -65.3, -24.7))]}),
        encoding="utf-8",
    )
    catalogo_cli.main(["preparar-municipios", "--archivo", str(archivo)])

    salida = capsys.readouterr().out
    assert "1 municipios guardados" in salida
    assert "OJO" in salida  # 1 no se parece a los ~60 de Salta
    assert "1 de 1 cámaras cambiaron" in salida
    conn = database.connect()
    try:
        assert catalogo.get_camera(conn, "C-1").locality == "Salta"
    finally:
        conn.close()


def test_recalcular_sin_limites_avisa(capsys) -> None:
    with pytest.raises(SystemExit):
        catalogo_cli.main(["recalcular-localidades"])
    assert "preparar-municipios" in capsys.readouterr().err


def test_preparar_desde_el_ign_filtra_por_codigo(monkeypatch, capsys) -> None:
    """Sin --archivo baja la capa del WFS con el filtro por código INDEC."""
    pedidos: list[str] = []

    def descargar(url: str) -> dict:
        pedidos.append(url)
        return {"features": [_feature("Salta", "660014", _anillo_denso(-65.5, -24.9, -65.3, -24.7))]}

    monkeypatch.setattr(catalogo_cli, "_descargar", descargar)
    catalogo_cli.main(["preparar-municipios"])

    assert len(pedidos) == 1
    assert "typeName=ign%3Amunicipio" in pedidos[0] and "CQL_FILTER=in1+LIKE" in pedidos[0]
    assert localidades.localidad_de(-24.75, -65.45) == "Salta"
    assert "1 municipios guardados" in capsys.readouterr().out


def test_preparar_desde_el_ign_sin_codigo_filtra_por_la_provincia(monkeypatch, tmp_path) -> None:
    """Si el filtro por código no trae nada, baja la zona y la corta con el límite provincial."""
    municipios = {
        "features": [
            _feature("Adentro", "", _anillo_denso(-65.5, -24.9, -65.3, -24.7)),
            _feature("Afuera", "", _anillo_denso(-63.0, -22.0, -62.8, -21.8)),
        ]
    }
    provincias = {
        "features": [
            {"properties": {"nam": "Jujuy"}, "geometry": {"type": "Polygon", "coordinates": [_anillo_denso(-67, -24.5, -64, -21.5, 2)]}},
            {"properties": {"nam": "Salta"}, "geometry": {"type": "Polygon", "coordinates": [_anillo_denso(-66.0, -25.5, -64.0, -23.0, 2)]}},
        ]
    }

    def descargar(url: str) -> dict:
        if "CQL_FILTER" in url:
            return {"features": []}
        return provincias if "provincia" in url else municipios

    monkeypatch.setattr(catalogo_cli, "_descargar", descargar)
    salida = tmp_path / "otra" / "m.geojson"
    catalogo_cli.main(["preparar-municipios", "--salida", str(salida)])

    limites = localidades.cargar(str(salida))
    assert limites is not None and limites.nombres == ["Adentro"]
    assert not Path(config.MUNICIPIOS_PATH).exists()  # otra salida: no toca la de la app


def test_preparar_sin_provincia_o_sin_municipios_falla(monkeypatch, capsys) -> None:
    monkeypatch.setattr(catalogo_cli, "_descargar", lambda url: {"features": []})
    with pytest.raises(SystemExit):
        catalogo_cli.main(["preparar-municipios"])
    assert "Salta" in capsys.readouterr().err

    vacio = {"features": [_feature("Jujuy", "380007", _anillo_denso(-65.4, -24.3, -65.2, -24.1))]}
    monkeypatch.setattr(catalogo_cli, "_descargar", lambda url: vacio)
    archivo_vacio = Path(config.MUNICIPIOS_PATH).with_name("vacio.geojson")
    archivo_vacio.write_text(json.dumps({"features": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        catalogo_cli.main(["preparar-municipios", "--archivo", str(archivo_vacio)])
    assert "No quedó ningún municipio" in capsys.readouterr().err
