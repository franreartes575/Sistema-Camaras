"""Mantenimiento del catálogo desde la consola del servidor.

    python -m app.catalogo_cli preparar-municipios
    python -m app.catalogo_cli preparar-municipios --archivo municipios.geojson
    python -m app.catalogo_cli recalcular-localidades

`preparar-municipios` se corre UNA vez (y cuando el IGN actualice los límites):
baja la capa `municipio` del IGN filtrada a Salta, la simplifica y la guarda en
`config.MUNICIPIOS_PATH`, que va con el código. Con eso el backend calcula la
localidad de cada cámara sin consultar ningún servicio externo. Si el servidor
no tiene salida a internet, se baja la capa en otra máquina (GeoJSON, desde el
WFS o la página de descargas del IGN) y se pasa con `--archivo`.
"""

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from . import config, database
from .services import catalogo, localidades

IGN_WFS = "https://wms.ign.gob.ar/geoserver/ows"
# Código INDEC de la provincia de Salta: los municipios de Salta tienen un
# código (`in1`) que empieza así.
SALTA_INDEC = "66"
# Caja que contiene a Salta con margen (lon_min, lat_min, lon_max, lat_max).
SALTA_CAJA = (-69.0, -26.6, -62.0, -21.7)
# ~50 m: alcanza para decidir en qué municipio cae una cámara y deja el archivo
# en unos cientos de KB.
TOLERANCIA_GRADOS = 0.0005
_TIMEOUT_S = 120
# Nombres posibles de la propiedad con el nombre del municipio, en orden.
_CAMPOS_NOMBRE = ("nam", "NAM", "nombre", "NOMBRE", "fna", "FNA", "name")
_CAMPOS_CODIGO = ("in1", "IN1", "id", "codigo")


def _wfs_url(type_name: str, **extra: str) -> str:
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": type_name,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "maxFeatures": "5000",
        **extra,
    }
    return f"{IGN_WFS}?{urllib.parse.urlencode(params)}"


def _descargar(url: str) -> dict:
    print(f"Descargando {url[:110]}…")
    with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as respuesta:  # noqa: S310 (URL fija del IGN)
        return json.loads(respuesta.read().decode("utf-8"))


def _propiedad(propiedades: dict, campos: tuple[str, ...]) -> str | None:
    for campo in campos:
        valor = propiedades.get(campo)
        if valor not in (None, ""):
            return str(valor).strip()
    return None


def _anillos(geometria: dict) -> list[list[list[list[float]]]]:
    """Polygon o MultiPolygon como lista de polígonos (listas de anillos)."""
    if geometria.get("type") == "Polygon":
        return [geometria["coordinates"]]
    if geometria.get("type") == "MultiPolygon":
        return geometria["coordinates"]
    return []


def _orden_lon_lat(features: list[dict]) -> bool:
    """True si las coordenadas vienen como (lon, lat), lo que pide GeoJSON.

    Un WFS puede devolver EPSG:4326 como (lat, lon); en Salta se nota porque la
    latitud anda por -24 y la longitud por -65.
    """
    for feature in features:
        for poligono in _anillos(feature.get("geometry") or {}):
            x, y = poligono[0][0][:2]
            return not (-30 < x < -20 and -70 < y < -60)
    return True


def simplificar(anillo: list[tuple[float, float]], tolerancia: float) -> list[tuple[float, float]]:
    """Douglas-Peucker (iterativo): saca vértices que se apartan menos que la tolerancia.

    Conserva el anillo cerrado y con al menos cuatro puntos; si la tolerancia
    lo achataría más que eso, lo devuelve como estaba.
    """
    if len(anillo) <= 4:
        return anillo
    conservar = [False] * len(anillo)
    conservar[0] = conservar[-1] = True
    pendientes = [(0, len(anillo) - 1)]
    while pendientes:
        inicio, fin = pendientes.pop()
        (ax, ay), (bx, by) = anillo[inicio], anillo[fin]
        dx, dy = bx - ax, by - ay
        largo = (dx * dx + dy * dy) ** 0.5
        peor, indice = -1.0, -1
        for i in range(inicio + 1, fin):
            px, py = anillo[i]
            if largo == 0:
                distancia = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                distancia = abs(dy * px - dx * py + bx * ay - by * ax) / largo
            if distancia > peor:
                peor, indice = distancia, i
        if indice != -1 and peor > tolerancia:
            conservar[indice] = True
            pendientes.extend([(inicio, indice), (indice, fin)])
    resultado = [punto for punto, queda in zip(anillo, conservar) if queda]
    return resultado if len(resultado) >= 4 else anillo


def _en_salta(feature: dict, provincia: localidades.Limites | None) -> bool:
    """Si el municipio es de Salta: por código INDEC, o por estar adentro de
    la provincia (más de la mitad de sus vértices)."""
    codigo = _propiedad(feature.get("properties") or {}, _CAMPOS_CODIGO)
    if provincia is None:
        return bool(codigo and codigo.startswith(SALTA_INDEC))
    vertices = [
        punto
        for poligono in _anillos(feature["geometry"])
        for punto in poligono[0]
    ]
    adentro = sum(
        1 for x, y, *_ in vertices if any(m.contiene(x, y) for m in provincia.municipios)
    )
    return adentro > len(vertices) / 2


def normalizar(
    datos: dict,
    *,
    tolerancia: float = TOLERANCIA_GRADOS,
    filtrar: bool = True,
    provincia: localidades.Limites | None = None,
    fuente: str = "",
) -> dict:
    """GeoJSON del IGN → el formato que lee `localidades`: un feature por
    municipio con la propiedad `nombre`, simplificado y en (lon, lat)."""
    features = [f for f in datos.get("features", []) if f.get("geometry")]
    lon_lat = _orden_lon_lat(features)
    por_nombre: dict[str, list] = {}
    for feature in features:
        nombre = _propiedad(feature.get("properties") or {}, _CAMPOS_NOMBRE)
        if not nombre:
            continue
        if filtrar and not _en_salta(feature, provincia):
            continue
        for poligono in _anillos(feature["geometry"]):
            anillos = []
            for anillo in poligono:
                puntos = [
                    (round(p[0], 5), round(p[1], 5)) if lon_lat else (round(p[1], 5), round(p[0], 5))
                    for p in anillo
                ]
                anillos.append([list(p) for p in simplificar(puntos, tolerancia)])
            por_nombre.setdefault(nombre, []).append(anillos)
    return {
        "type": "FeatureCollection",
        "metadata": {
            "fuente": fuente or "IGN, capa municipio",
            "generado": dt.date.today().isoformat(),
            "tolerancia_grados": tolerancia,
        },
        "features": [
            {
                "type": "Feature",
                "properties": {"nombre": nombre},
                "geometry": {"type": "MultiPolygon", "coordinates": poligonos},
            }
            for nombre, poligonos in sorted(por_nombre.items())
        ],
    }


def _provincia_salta() -> localidades.Limites:
    datos = _descargar(_wfs_url("ign:provincia"))
    salta = [
        f for f in datos.get("features", [])
        if (_propiedad(f.get("properties") or {}, _CAMPOS_NOMBRE) or "").lower() == "salta"
    ]
    if not salta:
        raise RuntimeError("El IGN no devolvió el límite de la provincia de Salta.")
    return localidades.desde_geojson(
        normalizar({"features": salta}, filtrar=False, fuente="IGN, capa provincia")
    )


def _preparar(args: argparse.Namespace) -> None:
    salida = Path(args.salida or config.MUNICIPIOS_PATH)
    if args.archivo:
        datos = json.loads(Path(args.archivo).read_text(encoding="utf-8"))
        resultado = normalizar(
            datos, tolerancia=args.tolerancia, filtrar=False, fuente=Path(args.archivo).name
        )
    else:
        filtro = f"in1 LIKE '{SALTA_INDEC}%'"
        datos = _descargar(_wfs_url("ign:municipio", CQL_FILTER=filtro))
        resultado = normalizar(datos, tolerancia=args.tolerancia)
        if not resultado["features"]:
            # El filtro por código no funcionó (otra versión de la capa): se
            # baja la zona y se filtra contra el límite provincial.
            print("El filtro por código INDEC no devolvió municipios; filtrando por la provincia.")
            caja = ",".join(str(v) for v in SALTA_CAJA)
            datos = _descargar(_wfs_url("ign:municipio", bbox=caja))
            resultado = normalizar(
                datos, tolerancia=args.tolerancia, provincia=_provincia_salta()
            )

    cantidad = len(resultado["features"])
    if cantidad == 0:
        raise RuntimeError("No quedó ningún municipio: revisá el archivo o la descarga.")
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(resultado, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{cantidad} municipios guardados en {salida} ({salida.stat().st_size // 1024} KB):")
    print("  " + ", ".join(feature["properties"]["nombre"] for feature in resultado["features"]))
    if not 40 <= cantidad <= 80:
        print(
            f"OJO: Salta tiene unos 60 municipios y quedaron {cantidad}. Revisá que el "
            "archivo sea el correcto antes de usarlo."
        )
    if salida.resolve() == Path(config.MUNICIPIOS_PATH).resolve():
        _recalcular(args)


def _recalcular(_: argparse.Namespace) -> None:
    limites = localidades.cargar()
    if limites is None:
        raise RuntimeError(
            f"No están los límites de los municipios ({config.MUNICIPIOS_PATH}). "
            "Corré primero: python -m app.catalogo_cli preparar-municipios"
        )
    conn = database.connect()
    try:
        with conn:
            cambiadas = catalogo.recalcular_localidades(conn, limites)
        total = conn.execute("SELECT COUNT(*) FROM camaras").fetchone()[0]
    finally:
        conn.close()
    print(f"Localidades recalculadas: {cambiadas} de {total} cámaras cambiaron.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.catalogo_cli", description=__doc__.split("\n\n")[0])
    comandos = parser.add_subparsers(dest="comando", required=True)

    preparar = comandos.add_parser(
        "preparar-municipios", help="Baja y guarda los límites de los municipios de Salta (IGN)"
    )
    preparar.add_argument("--archivo", help="GeoJSON ya descargado (sólo municipios de Salta)")
    preparar.add_argument("--salida", help=f"Dónde guardarlo (por defecto {config.MUNICIPIOS_PATH})")
    preparar.add_argument("--tolerancia", type=float, default=TOLERANCIA_GRADOS)
    preparar.set_defaults(fn=_preparar)

    comandos.add_parser(
        "recalcular-localidades", help="Vuelve a calcular la localidad de todo el catálogo"
    ).set_defaults(fn=_recalcular)

    args = parser.parse_args(argv)
    try:
        args.fn(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
