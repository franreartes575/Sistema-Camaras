"""Modelos de respuesta de la API."""

import datetime as dt

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
    """Recorrido resuelto para un cluster."""

    cluster_id: int
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
        ..., description="Número de jornada/vehículo dentro del cluster, base 1"
    )
    vehicle_day_count: int = Field(
        ..., description="Cuántas jornadas en total le tocaron a este cluster"
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
