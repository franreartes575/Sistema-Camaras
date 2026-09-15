"""Modelos de respuesta de la API."""

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
    cluster: int = Field(
        ..., description="Id de cluster DBSCAN; -1 indica punto de ruido"
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
    cluster_count: int
    noise_count: int = Field(..., description="Cámaras sin cluster (ruido DBSCAN)")
    eps_km: float
    min_samples: int


class ProcessResponse(BaseModel):
    """Respuesta de POST /process/."""

    filename: str
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
