/** Cliente del backend FastAPI. */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export type CoordMode = "split" | "single";
export type CoordOrder = "auto" | "latlon" | "lonlat";
export type ProviderChoice = "auto" | "osrm" | "haversine";

export type SuggestedMapping = {
  id: string | null;
  lat: string | null;
  lon: string | null;
  coords: string | null;
  label: string | null;
  mode: CoordMode;
};

export type UploadExcelResponse = {
  filename: string;
  columns: string[];
  column_count: number;
  suggested_mapping: SuggestedMapping;
};

export type Camera = {
  id: string;
  lat: number;
  lon: number;
  label: string | null;
  cluster: number;
};

export type Cluster = {
  id: number;
  size: number;
  centroid_lat: number;
  centroid_lon: number;
  radius_km: number;
};

export type DiscardedRow = { row: number; reason: string };

export type IngestStats = {
  total_rows: number;
  valid_rows: number;
  discarded_rows: number;
  cluster_count: number;
  noise_count: number;
  eps_km: number;
  min_samples: number;
  /** Extension geografica de las camaras validas, en km. */
  span_km: number;
};

export type RouteStop = {
  order: number;
  camera_id: string;
  lat: number;
  lon: number;
  label: string | null;
  /** null cuando la red vial no conecta el tramo con la parada anterior. */
  distance_from_previous_m: number | null;
};

export type ClusterRoute = {
  cluster_id: number;
  stop_count: number;
  total_distance_m: number;
  /** True si el total subestima el recorrido por tramos no transitables. */
  has_unreachable_legs: boolean;
  stops: RouteStop[];
  /** Polilinea del recorrido, como pares [lat, lon]. */
  geometry: [number, number][];
};

export type OptimizeResponse = {
  filename: string;
  provider: string;
  is_road_network: boolean;
  warning: string | null;
  stats: IngestStats;
  cameras: Camera[];
  clusters: Cluster[];
  routes: ClusterRoute[];
  discarded: DiscardedRow[];
};

export type ColumnMapping = {
  col_id: string;
  /** "split": lat y lon en columnas separadas. "single": ambas en una celda. */
  mode: CoordMode;
  col_lat: string;
  col_lon: string;
  col_coords: string;
  coord_order: CoordOrder;
  col_label?: string;
};

export type ClusterParams = {
  eps_km: number;
  min_samples: number;
};

export type RouteParams = {
  provider: ProviderChoice;
  round_trip: boolean;
  time_limit_s: number;
};

async function post<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { method: "POST", body });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Error ${response.status}`);
  }

  return response.json();
}

/** Sube una planilla y devuelve los encabezados detectados. */
export function uploadExcel(file: File): Promise<UploadExcelResponse> {
  const body = new FormData();
  body.append("file", file);
  return post<UploadExcelResponse>("/upload-excel/", body);
}

/** Campos de mapeo comunes a /process/ y /optimize/. */
function mappingFields(file: File, mapping: ColumnMapping, params: ClusterParams) {
  const body = new FormData();
  body.append("file", file);
  body.append("col_id", mapping.col_id);
  if (mapping.mode === "single") {
    body.append("col_coords", mapping.col_coords);
    body.append("coord_order", mapping.coord_order);
  } else {
    body.append("col_lat", mapping.col_lat);
    body.append("col_lon", mapping.col_lon);
  }
  if (mapping.col_label) body.append("col_label", mapping.col_label);
  body.append("eps_km", String(params.eps_km));
  body.append("min_samples", String(params.min_samples));
  return body;
}

/**
 * Agrupa las camaras y resuelve el orden de visita de cada cluster.
 *
 * El archivo se reenvia en cada llamada: el backend no guarda estado, asi que
 * reajustar los parametros es simplemente volver a postear.
 */
export function optimize(
  file: File,
  mapping: ColumnMapping,
  params: ClusterParams,
  routing: RouteParams,
): Promise<OptimizeResponse> {
  const body = mappingFields(file, mapping, params);
  body.append("provider", routing.provider);
  body.append("round_trip", String(routing.round_trip));
  body.append("time_limit_s", String(routing.time_limit_s));
  return post<OptimizeResponse>("/optimize/", body);
}
