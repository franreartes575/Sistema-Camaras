"""Sistema Logístico Free - API.

Backend FastAPI para optimización de rutas de mantenimiento de cámaras.
Stack 100% libre: FastAPI + pandas + scikit-learn (DBSCAN) + OR-Tools + OSRM local.
"""

import json
import logging
import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, NamedTuple

import anyio
import numpy as np

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import (
    ALLOWED_UPLOAD_EXTENSIONS,
    API_KEY,
    CORS_ORIGINS,
    MAX_UPLOAD_BYTES,
    RATE_LIMIT_OPTIMIZE_MAX,
    RATE_LIMIT_PROCESS_MAX,
    RATE_LIMIT_UPLOAD_MAX,
    UPLOAD_CHUNK_BYTES,
)
from .export_route import router as export_router
from .security import rate_limiter, require_api_key
from .schemas import (
    Camera,
    Cluster,
    ClusterRoute,
    DiscardedRow,
    IngestStats,
    OptimizeResponse,
    ProcessResponse,
    RouteStop,
    SuggestedMapping,
    UploadExcelResponse,
)
from .services.clustering import (
    bounding_span_km,
    haversine_km,
    reassign_noise,
    run_dbscan,
)
from .services.ingest import (
    extract_points,
    read_dataframe,
    read_headers,
    split_done,
    suggest_mapping,
)
from .services.routing import (
    BudgetInfeasibleError,
    ClusterTooLargeError,
    RoutingError,
    RoutingProvider,
    select_provider,
)
from .services.vrp import build_day_routes

# Salta mide unos 600 km de punta a punta. Si las coordenadas leidas abarcan
# bastante mas que eso, lo mas probable es que el mapeo apunte a columnas que
# contienen numeros pero no coordenadas.
MAX_SPAN_PLAUSIBLE_KM = 800.0

logger = logging.getLogger(__name__)

# Un limitador por endpoint, creado una sola vez para que el estado (hits por
# IP) persista entre requests. El de /optimize/ es el más estricto: es el
# único que corre OR-Tools.
_upload_rate_limit = rate_limiter(RATE_LIMIT_UPLOAD_MAX)
_process_rate_limit = rate_limiter(RATE_LIMIT_PROCESS_MAX)
_optimize_rate_limit = rate_limiter(RATE_LIMIT_OPTIMIZE_MAX)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Deja constancia en el log si el servicio arranca sin API_KEY.

    El chequeo queda deshabilitado por defecto para no pedir configuración
    extra en desarrollo local, pero exponerlo así a la red pasaría
    desapercibido sin este aviso.
    """
    if not API_KEY:
        logger.warning(
            "API_KEY no está configurada: los endpoints de escritura no "
            "exigen autenticación. No exponer así a la red."
        )
    yield


app = FastAPI(
    title="Sistema Logístico Free",
    description="Optimización de rutas de mantenimiento de cámaras sobre stack libre.",
    version="0.2.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # El frontend lee el nombre sugerido del Excel exportado.
    expose_headers=["Content-Disposition"],
)

app.include_router(export_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Chequeo de vida del servicio, sin autenticación (lo puede pegar un LB).

    No expone `OSRM_BASE_URL`: es infraestructura interna y este endpoint es
    público a propósito.
    """
    return {"status": "ok"}


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    """Valida la extensión y devuelve el contenido del archivo."""
    filename = file.filename or "sin-nombre"
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Extensión '{suffix or 'desconocida'}' no soportada. "
                f"Use: {', '.join(ALLOWED_UPLOAD_EXTENSIONS)}"
            ),
        )

    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"El archivo supera el límite de "
                    f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                ),
            )
        chunks.append(chunk)

    if not chunks:
        raise HTTPException(status_code=400, detail="El archivo llegó vacío.")

    return filename, b"".join(chunks)


@app.post(
    "/upload-excel/",
    response_model=UploadExcelResponse,
    dependencies=[Depends(_upload_rate_limit), Depends(require_api_key)],
)
async def upload_excel(file: UploadFile = File(...)) -> UploadExcelResponse:
    """Recibe una planilla y devuelve los encabezados de su primera fila.

    Incluye una sugerencia de mapeo para precargar el formulario del frontend.
    """
    filename, raw = await _read_upload(file)

    try:
        columns = read_headers(filename, raw)
    except Exception as exc:  # pandas/openpyxl levantan tipos muy variados
        # El detalle de pandas/openpyxl puede incluir rutas u otros datos
        # internos: se loguea server-side, no se reenvía tal cual al cliente.
        logger.warning("No se pudo leer la planilla '%s': %s", filename, exc)
        raise HTTPException(
            status_code=422,
            detail=(
                "No se pudo leer la planilla. Verifique que sea un archivo "
                "Excel (.xlsx/.xlsm) o CSV válido."
            ),
        ) from exc

    if not columns:
        raise HTTPException(
            status_code=422, detail="La planilla no tiene fila de encabezados."
        )

    return UploadExcelResponse(
        filename=filename,
        columns=columns,
        column_count=len(columns),
        suggested_mapping=SuggestedMapping(**suggest_mapping(columns)),
    )


class Clustered(NamedTuple):
    """Resultado de la ingesta y el agrupamiento, compartido por dos endpoints."""

    filename: str
    stats: IngestStats
    cameras: list[Camera]
    clusters: list[Cluster]
    discarded: list[DiscardedRow]
    warning: str | None


def _mapping_warning(
    span_km: float, valid: int, total: int, origen: str
) -> str | None:
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


async def _ingest_and_cluster(
    file: UploadFile,
    columns: ColumnMap,
    eps_km: float,
    min_samples: int,
    noise_reassign_factor: float,
) -> Clustered:
    """Lee la planilla, aparta lo realizado, valida coordenadas y agrupa con DBSCAN."""
    col_lat, col_lon, col_coords = columns.col_lat, columns.col_lon, columns.col_coords
    filename, raw = await _read_upload(file)

    try:
        frame = read_dataframe(filename, raw)
    except Exception as exc:
        logger.warning("No se pudo leer la planilla '%s': %s", filename, exc)
        raise HTTPException(
            status_code=422,
            detail=(
                "No se pudo leer la planilla. Verifique que sea un archivo "
                "Excel (.xlsx/.xlsm) o CSV válido."
            ),
        ) from exc

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
    warning = _mapping_warning(span_km, len(points), len(frame), origen)

    labels, clusters = run_dbscan(points, eps_km=eps_km, min_samples=min_samples)
    original_labels = labels
    max_reassign_km = eps_km * noise_reassign_factor
    labels, clusters = reassign_noise(points, labels, clusters, max_km=max_reassign_km)

    cameras = [
        Camera(
            id=str(record["id"]),
            lat=float(record["lat"]),
            lon=float(record["lon"]),
            label=record["label"],
            node=record["node"],
            observation=record["observation"],
            cluster=int(label),
            reassigned=bool(original_label == -1 and label != -1),
        )
        for record, label, original_label in zip(
            points.to_dict("records"), labels, original_labels, strict=True
        )
    ]

    sin_rutear = sum(1 for camera in cameras if camera.cluster == -1)
    if sin_rutear:
        # No hay silencio ante ruido sin cobertura: cada cámara sin recorrido
        # tiene que quedar explícita, no perderse en las estadísticas.
        aviso_ruido = (
            f"{sin_rutear} cámara(s) quedaron sin cluster cercano (a más de "
            f"{max_reassign_km:,.1f} km) y no entran en ningún recorrido."
        )
        warning = f"{warning} {aviso_ruido}" if warning else aviso_ruido

    return Clustered(
        filename=filename,
        stats=IngestStats(
            total_rows=total_rows,
            valid_rows=len(cameras),
            discarded_rows=len(discarded),
            done_rows=done_rows,
            cluster_count=len(clusters),
            noise_count=sin_rutear,
            eps_km=eps_km,
            min_samples=min_samples,
            span_km=round(span_km, 1),
        ),
        cameras=cameras,
        clusters=[Cluster(**cluster) for cluster in clusters],
        discarded=[DiscardedRow(**row) for row in discarded],
        warning=warning,
    )


@app.post(
    "/process/",
    response_model=ProcessResponse,
    dependencies=[Depends(_process_rate_limit), Depends(require_api_key)],
)
async def process(
    file: UploadFile = File(...),
    col_id: str = Form(...),
    col_lat: str | None = Form(None),
    col_lon: str | None = Form(None),
    col_coords: str | None = Form(None),
    coord_order: str = Form("auto", pattern="^(auto|latlon|lonlat)$"),
    col_label: str | None = Form(None),
    col_node: str | None = Form(None),
    col_obs: str | None = Form(None),
    col_done: str | None = Form(None),
    eps_km: float = Form(1.0, gt=0, le=500),
    min_samples: int = Form(2, ge=1, le=1000),
    noise_reassign_factor: float = Form(3.0, ge=0, le=20),
) -> ProcessResponse:
    """Ingesta la planilla completa, valida coordenadas y agrupa con DBSCAN.

    Las coordenadas pueden venir en dos columnas (`col_lat`/`col_lon`) o en una
    sola columna combinada (`col_coords`), con el orden indicado en
    `coord_order`.

    El archivo se reenvía junto con el mapeo en lugar de guardarse entre
    llamadas: mantiene el backend sin estado y evita limpiar temporales.
    Con `col_done` (Excel de seguimiento), las filas tildadas como realizadas
    se apartan y sólo se agrupa lo pendiente.
    """
    columns = ColumnMap(
        col_id, col_lat, col_lon, col_coords, coord_order, col_label,
        col_node, col_obs, col_done,
    )
    result = await _ingest_and_cluster(
        file, columns, eps_km, min_samples, noise_reassign_factor
    )

    return ProcessResponse(
        filename=result.filename,
        warning=result.warning,
        stats=result.stats,
        cameras=result.cameras,
        clusters=result.clusters,
        discarded=result.discarded,
    )


class ClusterStart(NamedTuple):
    """Punto de partida asignado a mano a un cluster: una sede o coordenadas sueltas."""

    lat: float
    lon: float
    name: str | None


def _parse_cluster_starts(raw: str) -> dict[int, ClusterStart]:
    """Parsea y valida el JSON de puntos de partida por cluster.

    Formato esperado: `{"<cluster_id>": {"lat": ..., "lon": ..., "name": ...}}`.
    El nombre es opcional; lat/lon no.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="cluster_starts_json no es JSON válido."
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="cluster_starts_json debe ser un objeto {cluster_id: punto}.",
        )

    starts: dict[int, ClusterStart] = {}
    for key, value in payload.items():
        try:
            cluster_id = int(key)
            lat = float(value["lat"])
            lon = float(value["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Punto de partida inválido para el cluster '{key}'.",
            ) from exc
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise HTTPException(
                status_code=400,
                detail=f"Coordenadas no finitas para el cluster '{key}'.",
            )
        starts[cluster_id] = ClusterStart(lat, lon, value.get("name"))
    return starts


def _check_starts_near_clusters(
    clusters: list[Cluster], starts: dict[int, ClusterStart]
) -> None:
    """Rechaza puntos de partida a una distancia imposible de su cluster.

    Una base a más de `MAX_SPAN_PLAUSIBLE_KM` de sus cámaras no es una sede
    lejana: son coordenadas mal cargadas (típicamente lat/lon invertidas o un
    signo perdido). Sin este chequeo el optimizador corre igual, ninguna
    cámara entra en la jornada y el síntoma no apunta a la causa.
    """
    for cluster in clusters:
        start = starts[cluster.id]
        distance_km = float(
            haversine_km(
                np.array([start.lat]),
                np.array([start.lon]),
                cluster.centroid_lat,
                cluster.centroid_lon,
            )[0]
        )
        if distance_km > MAX_SPAN_PLAUSIBLE_KM:
            # Separador de miles a la argentina: 5.231 km, no 5,231 km.
            distancia = f"{distance_km:,.0f}".replace(",", ".")
            raise HTTPException(
                status_code=422,
                detail=(
                    f"El punto de partida del cluster {cluster.id} "
                    f"({start.lat:.4f}, {start.lon:.4f}) está a {distancia} km "
                    f"de sus cámaras. Revise las coordenadas de la sede: "
                    f"¿latitud y longitud invertidas o sin el signo negativo?"
                ),
            )


class DayRules(NamedTuple):
    """Reglas de cada jornada, tal como las eligió el usuario."""

    day_budget_s: float
    service_time_s: float
    time_limit_s: int
    max_stops_per_day: int | None  # None = sin tope
    min_stops_per_day: int | None  # None = sin mínimo


class ClusterPlan(NamedTuple):
    """Recorridos de un cluster y las cámaras que no entraron, por motivo."""

    routes: list[ClusterRoute]
    out_of_reach: list[Camera]  # no entran ni yendo solas
    left_out: list[Camera]  # entrarían solas; las dejó fuera el mínimo/tope


def _route_for_cluster(
    cluster_id: int,
    members: list[Camera],
    start: ClusterStart,
    provider: RoutingProvider,
    rules: DayRules,
) -> ClusterPlan:
    """Arma uno o más recorridos (vehículo-jornada) para un cluster.

    `members[0]` nunca es el punto de partida: se antepone acá y
    `build_day_routes` lo mantiene fuera de `stops` porque no es una cámara.
    Devuelve también las cámaras que no entran en ninguna jornada.
    """
    points = [(start.lat, start.lon)] + [
        (camera.lat, camera.lon) for camera in members
    ]
    plan = build_day_routes(
        points,
        provider,
        day_budget_s=rules.day_budget_s,
        service_time_s=rules.service_time_s,
        time_limit_s=rules.time_limit_s,
        max_stops_per_day=rules.max_stops_per_day,
        min_stops_per_day=rules.min_stops_per_day,
    )

    out_of_reach = [members[index - 1] for index in plan.out_of_reach]
    left_out = [
        members[index - 1] for index in plan.unserved if index not in plan.out_of_reach
    ]
    total_days = len(plan.routes)
    routes: list[ClusterRoute] = []
    for day_index, day_route in enumerate(plan.routes, start=1):
        stops = [
            RouteStop(
                order=stop.order,
                camera_id=members[stop.index - 1].id,
                lat=members[stop.index - 1].lat,
                lon=members[stop.index - 1].lon,
                label=members[stop.index - 1].label,
                distance_from_previous_m=stop.distance_from_previous_m,
            )
            for stop in day_route.stops
        ]
        ordered_points = (
            [(start.lat, start.lon)]
            + [(stop.lat, stop.lon) for stop in stops]
            + [(start.lat, start.lon)]
        )
        routes.append(
            ClusterRoute(
                cluster_id=cluster_id,
                stop_count=len(stops),
                total_distance_m=day_route.total_distance_m,
                total_duration_s=day_route.total_duration_s,
                has_unreachable_legs=day_route.has_unreachable_legs,
                stops=stops,
                geometry=[
                    [lat, lon] for lat, lon in provider.route_geometry(ordered_points)
                ],
                vehicle_day=day_index,
                vehicle_day_count=total_days,
                start_name=start.name,
                start_lat=start.lat,
                start_lon=start.lon,
            )
        )
    return ClusterPlan(routes, out_of_reach, left_out)


class Solved(NamedTuple):
    """Recorridos resueltos más la identidad del motor que los calculó."""

    routes: list[ClusterRoute]
    provider_name: str
    is_road_network: bool
    warning: str | None


def _solve_routes(
    result: Clustered,
    preference: str,
    average_speed_kmh: float,
    cluster_starts: dict[int, ClusterStart],
    rules: DayRules,
) -> Solved:
    """Elige el motor y resuelve cada cluster con presupuesto de jornada.

    Es síncrona a propósito: consultar OSRM y correr OR-Tools bloquea, así que
    el endpoint la despacha a un hilo en vez de frenar el event loop.
    """
    engine, warning = select_provider(preference, average_speed_kmh=average_speed_kmh)

    routes: list[ClusterRoute] = []
    out_of_reach: list[Camera] = []
    left_out: list[Camera] = []
    for cluster in result.clusters:
        members = [
            camera for camera in result.cameras if camera.cluster == cluster.id
        ]
        if not members:
            continue
        plan = _route_for_cluster(
            cluster.id, members, cluster_starts[cluster.id], engine, rules
        )
        routes.extend(plan.routes)
        out_of_reach.extend(plan.out_of_reach)
        left_out.extend(plan.left_out)

    avisos = [warning] if warning else []
    unreachable = sum(1 for route in routes if route.has_unreachable_legs)
    if unreachable:
        avisos.append(
            f"{unreachable} recorrido(s) incluyen tramos que la red vial no "
            f"conecta: la distancia total informada subestima la real."
        )
    if out_of_reach:
        avisos.append(_unserved_warning(out_of_reach))
    if left_out:
        avisos.append(_left_out_warning(left_out, rules))

    return Solved(
        routes,
        engine.name,
        engine.is_road_network,
        " ".join(avisos) if avisos else None,
    )


# Cuántos ids de cámaras sin cubrir se listan en el aviso antes de resumir.
MAX_UNSERVED_IDS_IN_WARNING = 10


def _camera_listing(cameras: list[Camera]) -> str:
    """Ids de las cámaras para un aviso, resumiendo si son muchas."""
    ids = [camera.id for camera in cameras[:MAX_UNSERVED_IDS_IN_WARNING]]
    resto = len(cameras) - len(ids)
    return ", ".join(ids) + (f" y {resto} más" if resto else "")


def _left_out_warning(left_out: list[Camera], rules: DayRules) -> str:
    """Aviso para las cámaras que entrarían solas pero no con las reglas del día."""
    minimo = (
        f"el mínimo de {rules.min_stops_per_day} cámaras por día"
        if rules.min_stops_per_day
        else "el tope de cámaras por día"
    )
    return (
        f"{len(left_out)} cámara(s) quedaron fuera de los recorridos por "
        f"{minimo} ({_camera_listing(left_out)}): con el presupuesto de "
        f"jornada no se pueden agrupar así. Baje el mínimo por día o suba el "
        f"presupuesto de jornada."
    )


def _unserved_warning(unserved: list[Camera]) -> str:
    """Aviso para las cámaras que no entran en ninguna jornada."""
    listado = _camera_listing(unserved)
    return (
        f"{len(unserved)} cámara(s) no entran en ninguna jornada desde su "
        f"punto de partida (quedan muy lejos o sin conexión vial) y quedaron "
        f"fuera de los recorridos "
        f"({listado}). Revise el punto de partida, el presupuesto de jornada "
        f"o el tiempo de servicio."
    )


@app.post(
    "/optimize/",
    response_model=OptimizeResponse,
    dependencies=[Depends(_optimize_rate_limit), Depends(require_api_key)],
)
async def optimize(
    file: UploadFile = File(...),
    col_id: str = Form(...),
    col_lat: str | None = Form(None),
    col_lon: str | None = Form(None),
    col_coords: str | None = Form(None),
    coord_order: str = Form("auto", pattern="^(auto|latlon|lonlat)$"),
    col_label: str | None = Form(None),
    col_node: str | None = Form(None),
    col_obs: str | None = Form(None),
    col_done: str | None = Form(None),
    eps_km: float = Form(1.0, gt=0, le=500),
    min_samples: int = Form(2, ge=1, le=1000),
    noise_reassign_factor: float = Form(3.0, ge=0, le=20),
    provider: str = Form("auto", pattern="^(auto|osrm|haversine)$"),
    cluster_starts_json: str = Form(...),
    day_budget_s: float = Form(28800, gt=0, le=86400),
    service_time_s: float = Form(600, ge=0, le=3600),
    average_speed_kmh: float = Form(35, gt=0, le=150),
    time_limit_s: int = Form(5, ge=1, le=60),
    max_stops_per_day: int = Form(0, ge=0, le=100),
    min_stops_per_day: int = Form(0, ge=0, le=100),
) -> OptimizeResponse:
    """Agrupa las cámaras y resuelve el orden de visita de cada cluster.

    Cada cluster necesita un punto de partida asignado a mano (una sede
    guardada o coordenadas sueltas, vía `cluster_starts_json`) — no hay
    asignación automática. Si un cluster no entra en una jornada con el
    presupuesto dado, se arman varios recorridos (vehículo-jornada) desde el
    mismo punto en vez de dejar cámaras sin cubrir. Con `provider=auto` usa
    OSRM si responde y cae a línea recta (a `average_speed_kmh`) si no,
    informándolo en `warning`. Las cámaras marcadas como ruido por DBSCAN se
    reasignan al cluster más cercano dentro de `eps_km * noise_reassign_factor`;
    las que quedan más allá de ese radio no entran en ningún recorrido.
    `min_stops_per_day` / `max_stops_per_day` acotan las cámaras por jornada
    (0 = sin límite); el mínimo lo cumplen todas las jornadas salvo una.
    """
    if max_stops_per_day and min_stops_per_day > max_stops_per_day:
        raise HTTPException(
            status_code=422,
            detail=(
                f"El mínimo de cámaras por día ({min_stops_per_day}) no puede "
                f"superar el máximo ({max_stops_per_day})."
            ),
        )

    columns = ColumnMap(
        col_id, col_lat, col_lon, col_coords, coord_order, col_label,
        col_node, col_obs, col_done,
    )
    result = await _ingest_and_cluster(
        file, columns, eps_km, min_samples, noise_reassign_factor
    )

    cluster_starts = _parse_cluster_starts(cluster_starts_json)
    missing = [
        cluster.id for cluster in result.clusters if cluster.id not in cluster_starts
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                "Falta el punto de partida para el/los cluster(s): "
                + ", ".join(str(cluster_id) for cluster_id in missing)
            ),
        )
    _check_starts_near_clusters(result.clusters, cluster_starts)

    rules = DayRules(
        day_budget_s=day_budget_s,
        service_time_s=service_time_s,
        time_limit_s=time_limit_s,
        max_stops_per_day=max_stops_per_day or None,  # 0 = sin tope
        min_stops_per_day=min_stops_per_day or None,  # 0 = sin mínimo
    )
    try:
        solved = await anyio.to_thread.run_sync(
            _solve_routes,
            result,
            provider,
            average_speed_kmh,
            cluster_starts,
            rules,
        )
    except ClusterTooLargeError as exc:
        # Es un problema del input, no del servicio: reintentar no lo arregla.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BudgetInfeasibleError as exc:
        # Tampoco es una falla del servicio: el presupuesto/punto de partida
        # no alcanza, hay que ajustar parámetros, no reintentar.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RoutingError as exc:
        # El mensaje original puede incluir la URL interna de OSRM: se loguea
        # server-side pero no se expone al cliente.
        logger.warning("Fallo del motor de ruteo: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "El motor de ruteo no está disponible. Intente nuevamente en "
                "unos minutos."
            ),
        ) from exc

    avisos = [a for a in (result.warning, solved.warning) if a]

    return OptimizeResponse(
        filename=result.filename,
        provider=solved.provider_name,
        is_road_network=solved.is_road_network,
        warning=" ".join(avisos) if avisos else None,
        stats=result.stats,
        cameras=result.cameras,
        clusters=result.clusters,
        routes=solved.routes,
        discarded=result.discarded,
    )
