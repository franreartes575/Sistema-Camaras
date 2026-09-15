"""Sistema Logístico Free - API.

Backend FastAPI para optimización de rutas de mantenimiento de cámaras.
Stack 100% libre: FastAPI + pandas + scikit-learn (DBSCAN) + OR-Tools + OSRM local.
"""

from pathlib import Path
from typing import NamedTuple

import anyio

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import (
    ALLOWED_UPLOAD_EXTENSIONS,
    CORS_ORIGINS,
    MAX_UPLOAD_BYTES,
    OSRM_BASE_URL,
    UPLOAD_CHUNK_BYTES,
)
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
from .services.clustering import run_dbscan
from .services.ingest import (
    extract_points,
    read_dataframe,
    read_headers,
    suggest_mapping,
)
from .services.optimizer import build_route
from .services.routing import (
    ClusterTooLargeError,
    RoutingError,
    RoutingProvider,
    select_provider,
)

app = FastAPI(
    title="Sistema Logístico Free",
    description="Optimización de rutas de mantenimiento de cámaras sobre stack libre.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Chequeo de vida del servicio y configuración de ruteo."""
    return {"status": "ok", "osrm_base_url": OSRM_BASE_URL}


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


@app.post("/upload-excel/", response_model=UploadExcelResponse)
async def upload_excel(file: UploadFile = File(...)) -> UploadExcelResponse:
    """Recibe una planilla y devuelve los encabezados de su primera fila.

    Incluye una sugerencia de mapeo para precargar el formulario del frontend.
    """
    filename, raw = await _read_upload(file)

    try:
        columns = read_headers(filename, raw)
    except Exception as exc:  # pandas/openpyxl levantan tipos muy variados
        raise HTTPException(
            status_code=422, detail=f"No se pudo leer la planilla: {exc}"
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


async def _ingest_and_cluster(
    file: UploadFile,
    col_id: str,
    col_lat: str | None,
    col_lon: str | None,
    col_coords: str | None,
    coord_order: str,
    col_label: str | None,
    eps_km: float,
    min_samples: int,
) -> Clustered:
    """Lee la planilla, valida las coordenadas y agrupa con DBSCAN."""
    filename, raw = await _read_upload(file)

    try:
        frame = read_dataframe(filename, raw)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"No se pudo leer la planilla: {exc}"
        ) from exc

    total_rows = len(frame)
    if total_rows == 0:
        raise HTTPException(status_code=422, detail="La planilla no tiene filas.")

    try:
        points, discarded = extract_points(
            frame,
            col_id,
            col_lat=col_lat or None,
            col_lon=col_lon or None,
            col_label=col_label or None,
            col_coords=col_coords or None,
            coord_order=coord_order,
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
                f"Ninguna de las {total_rows} filas dio coordenadas válidas "
                f"leyendo {usadas}. Verifique que el mapeo de columnas sea el "
                f"correcto y que esa columna contenga números."
            ),
        )

    labels, clusters = run_dbscan(points, eps_km=eps_km, min_samples=min_samples)

    cameras = [
        Camera(
            id=str(record["id"]),
            lat=float(record["lat"]),
            lon=float(record["lon"]),
            label=record["label"] if record["label"] else None,
            cluster=int(label),
        )
        for record, label in zip(points.to_dict("records"), labels, strict=True)
    ]

    return Clustered(
        filename=filename,
        stats=IngestStats(
            total_rows=total_rows,
            valid_rows=len(cameras),
            discarded_rows=len(discarded),
            cluster_count=len(clusters),
            noise_count=sum(1 for camera in cameras if camera.cluster == -1),
            eps_km=eps_km,
            min_samples=min_samples,
        ),
        cameras=cameras,
        clusters=[Cluster(**cluster) for cluster in clusters],
        discarded=[DiscardedRow(**row) for row in discarded],
    )


@app.post("/process/", response_model=ProcessResponse)
async def process(
    file: UploadFile = File(...),
    col_id: str = Form(...),
    col_lat: str | None = Form(None),
    col_lon: str | None = Form(None),
    col_coords: str | None = Form(None),
    coord_order: str = Form("auto", pattern="^(auto|latlon|lonlat)$"),
    col_label: str | None = Form(None),
    eps_km: float = Form(1.0, gt=0, le=500),
    min_samples: int = Form(2, ge=1, le=1000),
) -> ProcessResponse:
    """Ingesta la planilla completa, valida coordenadas y agrupa con DBSCAN.

    Las coordenadas pueden venir en dos columnas (`col_lat`/`col_lon`) o en una
    sola columna combinada (`col_coords`), con el orden indicado en
    `coord_order`.

    El archivo se reenvía junto con el mapeo en lugar de guardarse entre
    llamadas: mantiene el backend sin estado y evita limpiar temporales.
    """
    result = await _ingest_and_cluster(
        file,
        col_id,
        col_lat,
        col_lon,
        col_coords,
        coord_order,
        col_label,
        eps_km,
        min_samples,
    )

    return ProcessResponse(
        filename=result.filename,
        stats=result.stats,
        cameras=result.cameras,
        clusters=result.clusters,
        discarded=result.discarded,
    )


def _route_for_cluster(
    cluster_id: int,
    members: list[Camera],
    provider: RoutingProvider,
    round_trip: bool,
    time_limit_s: int,
) -> ClusterRoute:
    """Optimiza el orden de visita de un cluster y arma su respuesta."""
    points = [(camera.lat, camera.lon) for camera in members]
    route = build_route(
        points, provider, round_trip=round_trip, time_limit_s=time_limit_s
    )

    stops = [
        RouteStop(
            order=stop.order,
            camera_id=members[stop.index].id,
            lat=members[stop.index].lat,
            lon=members[stop.index].lon,
            label=members[stop.index].label,
            distance_from_previous_m=stop.distance_from_previous_m,
        )
        for stop in route.stops
    ]

    return ClusterRoute(
        cluster_id=cluster_id,
        stop_count=len(stops),
        total_distance_m=route.total_distance_m,
        has_unreachable_legs=route.has_unreachable_legs,
        stops=stops,
        geometry=[[lat, lon] for lat, lon in route.geometry],
    )


class Solved(NamedTuple):
    """Recorridos resueltos más la identidad del motor que los calculó."""

    routes: list[ClusterRoute]
    provider_name: str
    is_road_network: bool
    warning: str | None


def _solve_routes(
    result: Clustered, preference: str, round_trip: bool, time_limit_s: int
) -> Solved:
    """Elige el motor y resuelve cada cluster.

    Es síncrona a propósito: consultar OSRM y correr OR-Tools bloquea, así que
    el endpoint la despacha a un hilo en vez de frenar el event loop.
    """
    engine, warning = select_provider(preference)

    routes = [
        _route_for_cluster(
            cluster.id,
            [camera for camera in result.cameras if camera.cluster == cluster.id],
            engine,
            round_trip,
            time_limit_s,
        )
        for cluster in result.clusters
    ]

    unreachable = sum(1 for route in routes if route.has_unreachable_legs)
    if unreachable:
        aviso = (
            f"{unreachable} recorrido(s) incluyen tramos que la red vial no "
            f"conecta: la distancia total informada subestima la real."
        )
        warning = f"{warning} {aviso}" if warning else aviso

    return Solved(routes, engine.name, engine.is_road_network, warning)


@app.post("/optimize/", response_model=OptimizeResponse)
async def optimize(
    file: UploadFile = File(...),
    col_id: str = Form(...),
    col_lat: str | None = Form(None),
    col_lon: str | None = Form(None),
    col_coords: str | None = Form(None),
    coord_order: str = Form("auto", pattern="^(auto|latlon|lonlat)$"),
    col_label: str | None = Form(None),
    eps_km: float = Form(1.0, gt=0, le=500),
    min_samples: int = Form(2, ge=1, le=1000),
    provider: str = Form("auto", pattern="^(auto|osrm|haversine)$"),
    round_trip: bool = Form(False),
    time_limit_s: int = Form(5, ge=1, le=60),
) -> OptimizeResponse:
    """Agrupa las cámaras y resuelve el orden de visita de cada cluster.

    Con `provider=auto` usa OSRM si responde y cae a línea recta si no,
    informándolo en `warning`. Las cámaras marcadas como ruido por DBSCAN no
    entran en ningún recorrido.
    """
    result = await _ingest_and_cluster(
        file,
        col_id,
        col_lat,
        col_lon,
        col_coords,
        coord_order,
        col_label,
        eps_km,
        min_samples,
    )

    try:
        solved = await anyio.to_thread.run_sync(
            _solve_routes, result, provider, round_trip, time_limit_s
        )
    except ClusterTooLargeError as exc:
        # Es un problema del input, no del servicio: reintentar no lo arregla.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RoutingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return OptimizeResponse(
        filename=result.filename,
        provider=solved.provider_name,
        is_road_network=solved.is_road_network,
        warning=solved.warning,
        stats=result.stats,
        cameras=result.cameras,
        clusters=result.clusters,
        routes=solved.routes,
        discarded=result.discarded,
    )
