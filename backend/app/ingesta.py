"""Tramo compartido de la ingesta: archivo subido → puntos con coordenadas válidas.

Lo usan el planificador (`/process/` y `/optimize/`, que después agrupan con
DBSCAN) y el catálogo (`/catalogo/importar/`, que guarda los puntos). Leer la
planilla, apartar lo realizado, validar coordenadas y avisar cuando el
resultado no se parece a cámaras reales es lo mismo en los dos casos, y vive
acá para no duplicarse.
"""

import logging
from typing import NamedTuple

import anyio
import pandas as pd
from fastapi import Form, HTTPException, UploadFile

from .services.clustering import bounding_span_km
from .services.ingest import extract_points, read_dataframe, split_done
from .uploads import read_upload

logger = logging.getLogger(__name__)

# Salta mide unos 600 km de punta a punta. Si las coordenadas leidas abarcan
# bastante mas que eso, lo mas probable es que el mapeo apunte a columnas que
# contienen numeros pero no coordenadas.
MAX_SPAN_PLAUSIBLE_KM = 800.0

_UNREADABLE = (
    "No se pudo leer la planilla. Verifique que sea un archivo "
    "Excel (.xlsx/.xlsm) o CSV válido."
)


class ColumnMap(NamedTuple):
    """Qué columna de la planilla cumple cada rol (vacío = no se usa)."""

    col_id: str
    col_lat: str | None
    col_lon: str | None
    col_coords: str | None
    coord_order: str
    col_label: str | None
    col_node: str | None = None
    col_obs: str | None = None
    col_done: str | None = None


def column_map_form(
    col_id: str = Form(...),
    col_lat: str | None = Form(None),
    col_lon: str | None = Form(None),
    col_coords: str | None = Form(None),
    coord_order: str = Form("auto", pattern="^(auto|latlon|lonlat)$"),
    col_label: str | None = Form(None),
    col_node: str | None = Form(None),
    col_obs: str | None = Form(None),
) -> ColumnMap:
    """El mapeo de columnas como dependencia, para los endpoints que no
    planifican (sin columna de realizado)."""
    return ColumnMap(
        col_id, col_lat, col_lon, col_coords, coord_order, col_label, col_node, col_obs
    )


class Ingested(NamedTuple):
    """La planilla leída: puntos válidos, filas descartadas y avisos."""

    filename: str
    raw: bytes
    total_rows: int
    done_rows: int
    # Columnas: row, id, lat, lon, label, node, observation.
    points: pd.DataFrame
    discarded: list[dict]
    span_km: float
    warning: str | None


def mapping_warning(span_km: float, valid: int, total: int, origen: str) -> str | None:
    """Avisa cuando el resultado no se parece a un conjunto de camaras reales."""
    if span_km > MAX_SPAN_PLAUSIBLE_KM:
        return (
            f"Las coordenadas leídas de {origen} abarcan {span_km:,.0f} km, "
            f"mucho más que una provincia. Es casi seguro que esa columna no "
            f"contiene coordenadas. Revise el mapeo."
        )
    if total >= 5 and valid < total / 2:
        return (
            f"Sólo {valid} de {total} filas dieron coordenadas válidas. "
            f"Verifique que {origen} sea la columna correcta."
        )
    return None


async def ingest_points(file: UploadFile, columns: ColumnMap) -> Ingested:
    """Lee la planilla, aparta lo realizado y valida coordenadas."""
    filename, raw = await read_upload(file)
    # pandas y openpyxl son sincrónicos y pueden tardar segundos con una
    # planilla grande: a un hilo, para no congelar al resto de los pedidos.
    return await anyio.to_thread.run_sync(_ingest, filename, raw, columns)


def _ingest(filename: str, raw: bytes, columns: ColumnMap) -> Ingested:
    col_lat, col_lon, col_coords = columns.col_lat, columns.col_lon, columns.col_coords
    try:
        frame = read_dataframe(filename, raw)
    except Exception as exc:  # pandas/openpyxl levantan tipos muy variados
        # El detalle puede incluir rutas u otros datos internos: se loguea
        # server-side, no se reenvía tal cual al cliente. %r: el nombre lo
        # elige el cliente y podría traer saltos de línea.
        logger.warning("No se pudo leer la planilla %r: %s", filename, exc)
        raise HTTPException(status_code=422, detail=_UNREADABLE) from exc

    total_rows = len(frame)
    if total_rows == 0:
        raise HTTPException(status_code=422, detail="La planilla no tiene filas.")

    try:
        # Un Excel de seguimiento ya completado: lo tildado como realizado no
        # se vuelve a planificar.
        frame, done_rows = split_done(frame, columns.col_done or None)
        if frame.empty:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Las {done_rows} filas están marcadas como realizadas: no "
                    f"queda nada pendiente para planificar."
                ),
            )
        points, discarded = extract_points(
            frame,
            columns.col_id,
            col_lat=col_lat or None,
            col_lon=col_lon or None,
            col_label=columns.col_label or None,
            col_coords=col_coords or None,
            coord_order=columns.coord_order,
            col_node=columns.col_node or None,
            col_obs=columns.col_obs or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if points.empty:
        usadas = (
            f"columna combinada '{col_coords}'"
            if col_coords
            else f"latitud '{col_lat}' y longitud '{col_lon}'"
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"Ninguna de las {len(frame)} filas dio coordenadas válidas "
                f"leyendo {usadas}. Verifique que el mapeo de columnas sea el "
                f"correcto y que esa columna contenga números."
            ),
        )

    span_km = bounding_span_km(points)
    origen = (
        f"la columna '{col_coords}'"
        if col_coords
        else f"las columnas '{col_lat}' y '{col_lon}'"
    )
    return Ingested(
        filename=filename,
        raw=raw,
        total_rows=total_rows,
        done_rows=done_rows,
        points=points,
        discarded=discarded,
        span_km=span_km,
        warning=mapping_warning(span_km, len(points), len(frame), origen),
    )
