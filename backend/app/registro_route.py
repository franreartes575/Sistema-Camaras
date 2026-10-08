"""/registro/: los recorridos guardados, su avance y la carga de seguimientos.

Es la única parte del backend con estado: el planificador sigue recibiendo
todo en cada request. Vive en su propio router, igual que /export/, y cada
request abre y cierra su conexión a la base (ver `database.get_db`).
"""

import datetime as dt
import sqlite3
from typing import Annotated, Literal

import anyio
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from .auth.dependencias import requiere_admin, requiere_sesion
from .auth.servicio import SesionActiva
from .config import RATE_LIMIT_REGISTRO_MAX
from .database import get_db
from .schemas import (
    FollowUpImport,
    FollowUpResult,
    PlanSummary,
    PlanUpdate,
    RegistryPlanIn,
    RouteDetail,
    RouteSummary,
    RouteUpdate,
    Task,
    TaskUpdate,
)
from .security import rate_limiter
from .services import registro
from .services.export import build_tasks_workbook, tasks_filename
from .uploads import read_upload

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Cuántas jornadas completas (con polilínea) se piden de una vez para el mapa.
MAX_DETAIL_IDS = 100

registro_rate_limit = rate_limiter(RATE_LIMIT_REGISTRO_MAX)

router = APIRouter(
    prefix="/registro",
    tags=["registro"],
    dependencies=[Depends(registro_rate_limit)],
)

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def _author(sesion: Annotated[SesionActiva, Depends(requiere_sesion)]) -> registro.Author:
    """Quién hace el cambio, tomado de la sesión (nunca de lo que manda el cliente)."""
    return registro.Author(username=sesion.usuario, name=sesion.nombre)


Author = Annotated[registro.Author, Depends(_author)]

# Filtro de estado de las tareas: "faltan" = pendientes + no realizadas, que
# es lo que hay que volver a planificar.
# "fuera_de_plan" no es un estado: las que se trabajaron otro día que el planificado.
StatusFilter = Literal[
    "pendiente", "realizada", "no_realizada", "reprogramada", "faltan", "fuera_de_plan"
]
_STATUS_GROUPS: dict[str, list[str]] = {"faltan": ["pendiente", "no_realizada"]}


def _filters(
    desde: Annotated[dt.date | None, Query(description="Fecha mínima (AAAA-MM-DD)")] = None,
    hasta: Annotated[dt.date | None, Query(description="Fecha máxima (AAAA-MM-DD)")] = None,
    plan_id: Annotated[int | None, Query(ge=1)] = None,
    q: Annotated[str | None, Query(max_length=100, description="Texto a buscar")] = None,
) -> registro.Filters:
    if desde and hasta and desde > hasta:
        raise HTTPException(status_code=422, detail="La fecha 'desde' es posterior a 'hasta'.")
    return registro.Filters(date_from=desde, date_to=hasta, plan_id=plan_id, query=q)


Filters = Annotated[registro.Filters, Depends(_filters)]


def _statuses(estado: list[StatusFilter] | None) -> list[str] | None:
    if not estado:
        return None
    expanded: list[str] = []
    for value in estado:
        expanded.extend(_STATUS_GROUPS.get(value, [value]))
    return list(dict.fromkeys(expanded))


def _not_found(exc: registro.NotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------- Planes


@router.get("/planes/", response_model=list[PlanSummary])
def list_plans(conn: Db) -> list[PlanSummary]:
    """Planes guardados, del más nuevo al más viejo, con su avance."""
    return registro.list_plans(conn)


@router.post("/planes/", response_model=PlanSummary, status_code=201)
def create_plan(plan: RegistryPlanIn, conn: Db, author: Author) -> PlanSummary:
    """Guarda un plan del planificador: sus jornadas, paradas y polilíneas."""
    try:
        return registro.create_plan(conn, plan, author)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/planes/{plan_id}", response_model=PlanSummary)
def replace_plan(plan_id: int, plan: RegistryPlanIn, conn: Db, author: Author) -> PlanSummary:
    """Reemplaza las jornadas de un plan sin seguimiento (p. ej. cambió una fecha)."""
    try:
        return registro.replace_plan(conn, plan_id, plan, author)
    except registro.NotFoundError as exc:
        raise _not_found(exc) from exc
    except registro.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/planes/{plan_id}", response_model=PlanSummary)
def update_plan(plan_id: int, changes: PlanUpdate, conn: Db, author: Author) -> PlanSummary:
    """Renombra un plan o edita sus notas."""
    try:
        return registro.update_plan(conn, plan_id, changes, author)
    except registro.NotFoundError as exc:
        raise _not_found(exc) from exc


@router.delete("/planes/{plan_id}", status_code=204)
def delete_plan(plan_id: int, conn: Db, author: Author) -> Response:
    """Borra un plan con sus jornadas y tareas. No se puede deshacer."""
    try:
        registro.delete_plan(conn, plan_id, author)
    except registro.NotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=204)


# ---------------------------------------------------------------- Recorridos


@router.get("/recorridos/", response_model=list[RouteSummary])
def list_routes(conn: Db, filters: Filters) -> list[RouteSummary]:
    """Jornadas guardadas con su avance, sin polilínea (ver /detalle)."""
    return registro.list_routes(conn, filters)


@router.patch("/recorridos/{route_id}", response_model=RouteSummary)
def update_route(
    route_id: int,
    changes: RouteUpdate,
    conn: Db,
    sesion: Annotated[SesionActiva, Depends(requiere_admin)],
) -> RouteSummary:
    """Cambia la fecha planificada de una jornada entera (sólo administradores)."""
    try:
        return registro.update_route(conn, route_id, changes, _author(sesion))
    except registro.NotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/recorridos/detalle", response_model=list[RouteDetail])
def route_details(
    conn: Db,
    ids: Annotated[list[int], Query(min_length=1, max_length=MAX_DETAIL_IDS)],
) -> list[RouteDetail]:
    """Jornadas completas —paradas y polilínea— para dibujarlas en el mapa."""
    return registro.route_details(conn, ids)


# ---------------------------------------------------------------- Tareas


@router.get("/tareas/", response_model=list[Task])
def list_tasks(
    conn: Db,
    filters: Filters,
    estado: Annotated[list[StatusFilter] | None, Query()] = None,
) -> list[Task]:
    """Tareas (cámaras a visitar) con su estado; `estado=faltan` = lo que queda por hacer."""
    return registro.list_tasks(conn, filters, _statuses(estado))


@router.get("/tareas.xlsx", response_class=Response)
def tasks_workbook(
    conn: Db,
    filters: Filters,
    estado: Annotated[list[StatusFilter] | None, Query()] = None,
) -> Response:
    """Las tareas filtradas en el formato del Excel de seguimiento.

    Con `estado=faltan` es la planilla para armar los próximos recorridos:
    entra tal cual por el paso 1 del planificador.
    """
    tasks = registro.list_tasks(conn, filters, _statuses(estado))
    if not tasks:
        raise HTTPException(status_code=404, detail="No hay tareas con esos filtros.")
    return Response(
        content=build_tasks_workbook(tasks),
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{tasks_filename(dt.date.today())}"'
        },
    )


@router.patch("/tareas/{task_id}", response_model=Task)
def update_task(
    task_id: int,
    changes: TaskUpdate,
    conn: Db,
    sesion: Annotated[SesionActiva, Depends(requiere_admin)],
) -> Task:
    """Corrige a mano el estado, la observación o el nodo migrado de una tarea
    (sólo administradores). Queda registrado quién lo hizo."""
    author = _author(sesion)
    try:
        return registro.update_task(conn, task_id, changes, author)
    except registro.NotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------- Seguimientos


@router.post("/seguimiento/", response_model=FollowUpResult)
async def import_follow_up(conn: Db, author: Author, file: UploadFile = File(...)) -> FollowUpResult:
    """Carga un Excel de seguimiento completado y actualiza las tareas del registro."""
    filename, raw = await read_upload(file)
    try:
        # pandas y SQLite bloquean: a un hilo, como /optimize/.
        return await anyio.to_thread.run_sync(registro.import_follow_up, conn, filename, raw, author)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/cargas/", response_model=list[FollowUpImport])
def list_imports(conn: Db) -> list[FollowUpImport]:
    """Historial de seguimientos cargados, del más nuevo al más viejo."""
    return registro.list_imports(conn)


@router.get("/respaldo", response_class=Response, dependencies=[Depends(requiere_admin)])
def backup(conn: Db) -> Response:
    """Descarga la base completa (.sqlite) para guardarla como respaldo (sólo administradores)."""
    return Response(
        content=registro.backup(conn),
        media_type="application/vnd.sqlite3",
        headers={
            "Content-Disposition": (
                f'attachment; filename="registro-recorridos-{dt.date.today().isoformat()}.sqlite"'
            )
        },
    )
