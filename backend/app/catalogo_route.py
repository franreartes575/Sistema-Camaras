"""/catalogo/: las cámaras guardadas, las sedes y el resumen del Inicio.

Leer es para cualquier sesión; cambiar el catálogo o las sedes, sólo para
administradores. Como el registro, cada request abre y cierra su conexión.
"""

import datetime as dt
import sqlite3
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from .auth.dependencias import requiere_admin
from .config import RATE_LIMIT_CATALOGO_MAX
from .database import get_db
from .ingesta import ColumnMap, column_map_form, ingest_points
from .schemas import (
    CatalogCamera,
    CatalogCameraUpdate,
    CatalogClusters,
    CatalogImport,
    CatalogImportResult,
    CatalogSelection,
    CatalogSummary,
    Depot,
    DepotIn,
)
from .security import rate_limiter
from .services import catalogo
from .services.clustering import DEPOT_MAX_KM
from .services.export import build_catalog_workbook, catalog_filename
from .services.registro import ConflictError, NotFoundError

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Cuántos IDs desconocidos se nombran en el error antes de resumir.
MAX_MISSING_IDS = 20

catalogo_rate_limit = rate_limiter(RATE_LIMIT_CATALOGO_MAX)

router = APIRouter(
    prefix="/catalogo",
    tags=["catalogo"],
    dependencies=[Depends(catalogo_rate_limit)],
)

Db = Annotated[sqlite3.Connection, Depends(get_db)]
Admin = [Depends(requiere_admin)]


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------- Cámaras


@router.get("/camaras/", response_model=list[CatalogCamera])
def list_cameras(conn: Db) -> list[CatalogCamera]:
    """Todo el catálogo, con la última visita y el estado de cada cámara."""
    return catalogo.list_cameras(conn)


@router.patch("/camaras/{camera_id:path}", response_model=CatalogCamera, dependencies=Admin)
def update_camera(camera_id: str, changes: CatalogCameraUpdate, conn: Db) -> CatalogCamera:
    """Corrige a mano la localidad de una cámara (None la vuelve a calcular)."""
    try:
        return catalogo.update_camera(conn, camera_id, changes)
    except NotFoundError as exc:
        raise _not_found(exc) from exc


@router.delete("/camaras/{camera_id:path}", status_code=204, dependencies=Admin)
def delete_camera(camera_id: str, conn: Db) -> Response:
    """Da de baja una cámara del catálogo. El registro no se toca."""
    try:
        catalogo.delete_camera(conn, camera_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=204)


@router.post("/importar/", response_model=CatalogImportResult, dependencies=Admin)
async def import_cameras(
    conn: Db,
    file: UploadFile = File(...),
    columns: ColumnMap = Depends(column_map_form),
) -> CatalogImportResult:
    """Combina una planilla con el catálogo, por ID: agrega y actualiza, nunca borra.

    El mapeo de columnas es el mismo del planificador; los encabezados y la
    sugerencia salen de `/upload-excel/`.
    """
    ingested = await ingest_points(file, columns)
    # Calcular localidades y escribir en SQLite bloquea: a un hilo.
    return await anyio.to_thread.run_sync(catalogo.import_points, conn, ingested)


@router.get("/importaciones/", response_model=list[CatalogImport])
def list_imports(conn: Db) -> list[CatalogImport]:
    """Historial de planillas importadas al catálogo, de la más nueva a la más vieja."""
    return catalogo.list_imports(conn)


@router.post("/planilla", response_class=Response)
def selection_workbook(selection: CatalogSelection, conn: Db) -> Response:
    """Planilla de entrada al planificador con las cámaras elegidas.

    Sube por el paso 1 como cualquier otra: el planificador sigue sin estado y
    el resto del flujo (agrupar, optimizar, exportar, registro) no cambia.
    """
    cameras, missing = catalogo.cameras_for_selection(conn, selection.ids)
    if missing:
        listed = ", ".join(missing[:MAX_MISSING_IDS])
        rest = len(missing) - MAX_MISSING_IDS
        raise HTTPException(
            status_code=422,
            detail=(
                f"{len(missing)} ID(s) no están en el catálogo: {listed}"
                + (f" y {rest} más" if rest > 0 else "")
                + "."
            ),
        )
    if not cameras:
        raise HTTPException(status_code=422, detail="No se eligió ninguna cámara.")
    filename = catalog_filename(len(cameras), dt.date.today())
    return Response(
        content=build_catalog_workbook(cameras),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/clusters", response_model=CatalogClusters)
async def clusters(
    conn: Db,
    eps_km: Annotated[float, Query(gt=0, le=500)] = 20.0,
    min_samples: Annotated[int, Query(ge=1, le=1000)] = 2,
    # En el mapa una cámara suelta se suma a un grupo sólo si está a menos de
    # 1,5 radios (30 km con el radio por defecto): con tres, un grupo chico se
    # estiraba hasta 60 km, y con uno quedaban afuera cámaras a 24-27 km de un
    # grupo grande (El Galpón y El Quebrachal, de J. V. González).
    noise_reassign_factor: Annotated[float, Query(ge=0, le=20)] = 1.5,
    colores: Annotated[int, Query(ge=1, le=20, description="Colores de la paleta")] = 8,
    por_sede: bool = True,
    max_sede_km: Annotated[float, Query(ge=1, le=500)] = DEPOT_MAX_KM,
) -> CatalogClusters:
    """El catálogo agrupado como en el planificador: por zona de sede y, lo
    que queda lejos de toda sede, por cercanía."""
    return await anyio.to_thread.run_sync(
        catalogo.cluster_catalog, conn, eps_km, min_samples, noise_reassign_factor,
        colores, por_sede, max_sede_km,
    )


# ---------------------------------------------------------------- Sedes


@router.get("/sedes/", response_model=list[Depot])
def list_depots(conn: Db) -> list[Depot]:
    """Las sedes (bases operativas) de las que salen las cuadrillas."""
    return catalogo.list_depots(conn)


@router.post("/sedes/", response_model=Depot, status_code=201, dependencies=Admin)
def create_depot(depot: DepotIn, conn: Db) -> Depot:
    try:
        return catalogo.create_depot(conn, depot)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/sedes/{depot_id}", response_model=Depot, dependencies=Admin)
def update_depot(depot_id: int, depot: DepotIn, conn: Db) -> Depot:
    try:
        return catalogo.update_depot(conn, depot_id, depot)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/sedes/{depot_id}", status_code=204, dependencies=Admin)
def delete_depot(depot_id: int, conn: Db) -> Response:
    try:
        catalogo.delete_depot(conn, depot_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=204)


# ---------------------------------------------------------------- Inicio


@router.get("/resumen", response_model=CatalogSummary)
def summary(
    conn: Db, max_sede_km: Annotated[float, Query(ge=1, le=500)] = DEPOT_MAX_KM
) -> CatalogSummary:
    """Catálogo por localidad, antigüedad de las visitas, zonas de las sedes,
    planes y tareas por mes."""
    return catalogo.summary(conn, depot_max_km=max_sede_km)
