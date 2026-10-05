"""Modelos de respuesta de la API."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field


class SuggestedMapping(BaseModel):
    """Mapeo de columnas inferido por heurística de nombres."""

    id: str | None = Field(None, description="Columna identificadora de la cámara")
    lat: str | None = Field(None, description="Columna de latitud")
    lon: str | None = Field(None, description="Columna de longitud")
    coords: str | None = Field(
        None, description="Columna única con latitud y longitud juntas"
    )
    label: str | None = Field(None, description="Columna descriptiva / dirección")
    node: str | None = Field(None, description="Columna del nodo preliminar")
    observation: str | None = Field(None, description="Columna de observaciones")
    done: str | None = Field(
        None, description="Columna 'Realizado' del Excel de seguimiento"
    )
    mode: str = Field(
        "split", description="'split' (dos columnas) o 'single' (columna combinada)"
    )


class UploadExcelResponse(BaseModel):
    """Respuesta de POST /upload-excel/: encabezados detectados en la planilla."""

    filename: str = Field(..., description="Nombre del archivo recibido")
    columns: list[str] = Field(..., description="Encabezados de la primera fila")
    column_count: int = Field(..., description="Cantidad de columnas detectadas")
    suggested_mapping: SuggestedMapping = Field(
        ..., description="Sugerencia automática de mapeo de columnas"
    )


class Camera(BaseModel):
    """Una cámara georreferenciada, ya asignada a un cluster."""

    id: str
    lat: float
    lon: float
    label: str | None = None
    node: str | None = Field(None, description="Nodo preliminar al que se migra")
    observation: str | None = Field(
        None, description="Observación arrastrada de un seguimiento anterior"
    )
    cluster: int = Field(
        ..., description="Id de cluster DBSCAN; -1 indica punto de ruido"
    )
    reassigned: bool = Field(
        False,
        description="True si era ruido DBSCAN y se reasignó a un cluster cercano",
    )


class Cluster(BaseModel):
    """Agrupamiento geográfico de cámaras producido por DBSCAN."""

    id: int
    size: int
    centroid_lat: float
    centroid_lon: float
    radius_km: float = Field(
        ..., description="Distancia máxima del centroide a un miembro"
    )


class DiscardedRow(BaseModel):
    """Fila descartada durante la validación, con su motivo."""

    row: int = Field(..., description="Número de fila en la planilla (base 1)")
    reason: str


class IngestStats(BaseModel):
    """Resumen de la ingesta y el clustering."""

    total_rows: int
    valid_rows: int
    discarded_rows: int
    done_rows: int = Field(
        0, description="Filas marcadas como realizadas: no se replanifican"
    )
    cluster_count: int
    noise_count: int = Field(
        ...,
        description=(
            "Cámaras sin recorrido tras intentar reasignar el ruido DBSCAN al "
            "cluster más cercano"
        ),
    )
    eps_km: float
    min_samples: int
    span_km: float = Field(
        0.0, description="Extension geografica que abarcan las cámaras válidas"
    )


class ProcessResponse(BaseModel):
    """Respuesta de POST /process/."""

    filename: str
    warning: str | None = Field(
        None, description="Aviso sobre la plausibilidad del mapeo de columnas"
    )
    stats: IngestStats
    cameras: list[Camera]
    clusters: list[Cluster]
    discarded: list[DiscardedRow]


class RouteStop(BaseModel):
    """Una parada del recorrido optimizado."""

    order: int = Field(..., description="Posición en el recorrido, base 0")
    camera_id: str
    lat: float
    lon: float
    label: str | None = None
    distance_from_previous_m: float | None = Field(
        ...,
        description=(
            "Metros desde la parada anterior; 0 en la primera y null cuando la "
            "red vial no conecta el tramo"
        ),
    )


class ClusterRoute(BaseModel):
    """Recorrido resuelto para un cluster, o para varios con la misma sede."""

    cluster_id: int = Field(..., description="El menor id de los clusters de la jornada")
    cluster_ids: list[int] = Field(
        default_factory=list,
        description="Clusters cuyas cámaras reparte esta jornada (comparten sede)",
    )
    stop_count: int
    total_distance_m: float
    total_duration_s: float = Field(
        ..., description="Manejo real más tiempo de servicio en cada parada"
    )
    has_unreachable_legs: bool = Field(
        False,
        description=(
            "True si algún tramo no es transitable: el total subestima el "
            "recorrido real"
        ),
    )
    stops: list[RouteStop]
    geometry: list[list[float]] = Field(
        ..., description="Polilínea del recorrido como pares [lat, lon]"
    )
    vehicle_day: int = Field(
        ..., description="Número de jornada/vehículo dentro de su grupo de clusters, base 1"
    )
    vehicle_day_count: int = Field(
        ..., description="Cuántas jornadas en total le tocaron a ese grupo de clusters"
    )
    start_name: str | None = Field(
        None, description="Nombre del punto de partida, si se le puso uno"
    )
    start_lat: float
    start_lon: float


class OptimizeResponse(BaseModel):
    """Respuesta de POST /optimize/."""

    filename: str
    provider: str = Field(..., description="Motor de distancias usado: osrm o haversine")
    is_road_network: bool = Field(
        ..., description="False indica distancias en línea recta, no de manejo"
    )
    warning: str | None = Field(
        None, description="Aviso cuando hubo que degradar el proveedor"
    )
    stats: IngestStats
    cameras: list[Camera]
    clusters: list[Cluster]
    routes: list[ClusterRoute]
    discarded: list[DiscardedRow]


# --------------------------------------------------------------------------
# Exportación del plan a Excel (POST /export/)
# --------------------------------------------------------------------------

# Topes de tamaño: el endpoint arma el archivo en memoria.
MAX_EXPORT_DAYS = 366
MAX_STOPS_PER_EXPORT_DAY = 500


class ExportStop(BaseModel):
    """Una cámara del plan, tal como va al Excel de seguimiento."""

    camera_id: str = Field(..., min_length=1, max_length=200)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    node: str | None = Field(None, max_length=200, description="Nodo preliminar")
    observation: str | None = Field(
        None, max_length=2000, description="Observación de un seguimiento anterior"
    )


class ExportDay(BaseModel):
    """Un recorrido (jornada) con la fecha en que se va a hacer."""

    date: dt.date
    cluster_id: int
    day: int = Field(..., ge=1, description="Número de jornada dentro del cluster")
    start_name: str | None = Field(None, max_length=200)
    distance_m: float = Field(..., ge=0)
    duration_s: float = Field(..., ge=0)
    stops: list[ExportStop] = Field(
        ..., min_length=1, max_length=MAX_STOPS_PER_EXPORT_DAY,
        description="Cámaras en orden de visita",
    )


class ExportRequest(BaseModel):
    """Plan completo a exportar: el backend no guarda estado, llega entero."""

    days: list[ExportDay] = Field(..., min_length=1, max_length=MAX_EXPORT_DAYS)
    plan_id: int | None = Field(
        None,
        ge=1,
        description=(
            "Plan del registro al que corresponde. Va en una hoja oculta del "
            "Excel para que, al cargar el seguimiento, se actualice ese plan."
        ),
    )


# --------------------------------------------------------------------------
# Registro de recorridos (/registro/...)
# --------------------------------------------------------------------------

# Una polilínea de OSRM para una jornada larga ronda los miles de puntos.
MAX_GEOMETRY_POINTS = 50_000

# Estado que informan los técnicos. "reprogramada" no se carga: se deriva
# cuando la cámara vuelve a aparecer en un plan posterior.
TaskStatus = Literal["pendiente", "realizada", "no_realizada", "reprogramada"]
ReportedStatus = Literal["pendiente", "realizada", "no_realizada"]


class RegistryStopIn(BaseModel):
    """Una cámara de una jornada, tal como sale del planificador."""

    camera_id: str = Field(..., min_length=1, max_length=200)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    label: str | None = Field(None, max_length=500)
    node: str | None = Field(None, max_length=200, description="Nodo preliminar")
    observation: str | None = Field(None, max_length=2000)


class RegistryRouteIn(BaseModel):
    """Una jornada del plan con su fecha."""

    date: dt.date
    cluster_id: int
    day: int = Field(..., ge=1)
    start_name: str | None = Field(None, max_length=200)
    start_lat: float = Field(..., ge=-90, le=90)
    start_lon: float = Field(..., ge=-180, le=180)
    distance_m: float = Field(..., ge=0)
    duration_s: float = Field(..., ge=0)
    has_unreachable_legs: bool = False
    geometry: list[tuple[float, float]] = Field(
        default_factory=list,
        max_length=MAX_GEOMETRY_POINTS,
        description="Polilínea como pares [lat, lon]",
    )
    stops: list[RegistryStopIn] = Field(
        ..., min_length=1, max_length=MAX_STOPS_PER_EXPORT_DAY,
        description="Cámaras en orden de visita",
    )


class RegistryPlanIn(BaseModel):
    """Plan completo a guardar en el registro."""

    name: str | None = Field(None, max_length=200)
    source_file: str | None = Field(None, max_length=255)
    provider: str | None = Field(None, max_length=20)
    is_road_network: bool = False
    routes: list[RegistryRouteIn] = Field(..., min_length=1, max_length=MAX_EXPORT_DAYS)


class TaskCounts(BaseModel):
    """Cuántas tareas hay en cada estado."""

    total: int
    done: int = Field(..., description="Realizadas")
    pending: int = Field(..., description="Pendientes, sin novedad de los técnicos")
    not_done: int = Field(..., description="Informadas como no realizadas")
    rescheduled: int = Field(
        ..., description="Pendientes que ya se volvieron a planificar en otro plan"
    )


class PlanSummary(TaskCounts):
    """Un plan del registro con su avance."""

    id: int
    name: str
    created_at: str
    source_file: str | None
    provider: str | None
    is_road_network: bool
    notes: str | None
    route_count: int
    date_from: dt.date | None
    date_to: dt.date | None
    distance_m: float
    duration_s: float


class PlanUpdate(BaseModel):
    """Cambios editables de un plan."""

    name: str | None = Field(None, min_length=1, max_length=200)
    notes: str | None = Field(None, max_length=2000)


class RouteSummary(TaskCounts):
    """Una jornada del registro con su avance (sin polilínea)."""

    id: int
    plan_id: int
    plan_name: str
    date: dt.date
    cluster_id: int
    day: int
    start_name: str | None
    start_lat: float
    start_lon: float
    distance_m: float
    duration_s: float
    has_unreachable_legs: bool


class Task(BaseModel):
    """Una parada del registro: la tarea de visitar una cámara."""

    id: int
    route_id: int
    plan_id: int
    plan_name: str
    date: dt.date
    cluster_id: int
    day: int
    order: int = Field(..., description="Posición en el recorrido, base 1")
    camera_id: str
    lat: float
    lon: float
    label: str | None
    node: str | None = Field(None, description="Nodo preliminar")
    migrated_node: str | None = Field(None, description="Nodo al cual se migró")
    observation: str | None
    status: TaskStatus
    verified_at: str | None


class RouteDetail(RouteSummary):
    """Una jornada completa: paradas y polilínea, para dibujarla en el mapa."""

    geometry: list[tuple[float, float]]
    stops: list[Task]


class TaskUpdate(BaseModel):
    """Corrección manual de una tarea desde el registro."""

    status: ReportedStatus | None = None
    observation: str | None = Field(None, max_length=2000)
    migrated_node: str | None = Field(None, max_length=200)


class FollowUpResult(BaseModel):
    """Qué cambió en el registro al cargar un Excel de seguimiento."""

    import_id: int
    filename: str
    plan_id: int | None
    plan_name: str | None
    rows: int = Field(..., description="Filas con ID de cámara en el archivo")
    matched: int = Field(..., description="Filas que coinciden con una tarea guardada")
    updated: int = Field(..., description="Tareas cuyo estado, nodo u observación cambió")
    done: int
    not_done: int
    no_news: int = Field(..., description="Coinciden pero sin Realizado cargado")
    unmatched: int
    unmatched_ids: list[str] = Field(
        ..., description="Algunas cámaras sin tarea guardada (hasta 20)"
    )
    previously_loaded_at: str | None = Field(
        None, description="Si el mismo archivo ya se había cargado, cuándo"
    )


class FollowUpImport(BaseModel):
    """Una carga de seguimiento del historial."""

    id: int
    filename: str
    loaded_at: str
    plan_id: int | None
    plan_name: str | None
    rows: int
    matched: int
    updated: int
    done: int
    not_done: int
    unmatched: int
