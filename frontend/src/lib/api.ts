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
  /** Nodo preliminar ("Nodo a Migrar" en cnMaestro). */
  node: string | null;
  observation: string | null;
  /** Columna "Realizado" de un Excel de seguimiento ya completado. */
  done: string | null;
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
  /** Nodo preliminar al que se migra. */
  node: string | null;
  /** Observación arrastrada de un seguimiento anterior. */
  observation: string | null;
  cluster: number;
  /** True si era ruido DBSCAN y se reasignó a un cluster cercano. */
  reassigned: boolean;
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
  /** Filas tildadas como realizadas en un seguimiento: no se replanifican. */
  done_rows: number;
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
  /** Manejo real más tiempo de servicio en cada parada. */
  total_duration_s: number;
  /** True si el total subestima el recorrido por tramos no transitables. */
  has_unreachable_legs: boolean;
  stops: RouteStop[];
  /** Polilinea del recorrido, como pares [lat, lon]. */
  geometry: [number, number][];
  /** Número de jornada/vehículo dentro del cluster, base 1. */
  vehicle_day: number;
  /** Cuántas jornadas en total le tocaron a este cluster. */
  vehicle_day_count: number;
  start_name: string | null;
  start_lat: number;
  start_lon: number;
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

export type ProcessResponse = {
  filename: string;
  warning: string | null;
  stats: IngestStats;
  cameras: Camera[];
  clusters: Cluster[];
  discarded: DiscardedRow[];
};

/** Una sede guardada por el usuario — sólo vive en el navegador. */
export type Depot = { id: string; name: string; lat: number; lon: number };

/** Punto de partida ya resuelto para un cluster (sede guardada o manual). */
export type ClusterStart = { lat: number; lon: number; name: string | null };

export type ColumnMapping = {
  col_id: string;
  /** "split": lat y lon en columnas separadas. "single": ambas en una celda. */
  mode: CoordMode;
  col_lat: string;
  col_lon: string;
  col_coords: string;
  coord_order: CoordOrder;
  col_label?: string;
  /** Columnas de seguimiento opcionales; "" = no se usa. */
  col_node?: string;
  col_obs?: string;
  col_done?: string;
};

export type ClusterParams = {
  eps_km: number;
  min_samples: number;
  /** Radio de reasignación de ruido, como múltiplo de eps_km. */
  noise_reassign_factor: number;
};

export type RouteParams = {
  provider: ProviderChoice;
  /** Presupuesto de jornada, en segundos: manejo + servicio, ida y vuelta. */
  day_budget_s: number;
  /** Tiempo fijo de servicio por parada, en segundos. */
  service_time_s: number;
  /** Velocidad asumida sin OSRM, para estimar duración en línea recta. */
  average_speed_kmh: number;
  time_limit_s: number;
  /** Tope de cámaras por jornada; 0 = sin tope (sólo corta por tiempo). */
  max_stops_per_day: number;
  /**
   * Mínimo de cámaras por jornada; 0 = sin mínimo. Lo cumplen todas las
   * jornadas salvo una (el "resto" cuando no se reparten justo).
   */
  min_stops_per_day: number;
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
  if (mapping.col_node) body.append("col_node", mapping.col_node);
  if (mapping.col_obs) body.append("col_obs", mapping.col_obs);
  if (mapping.col_done) body.append("col_done", mapping.col_done);
  body.append("eps_km", String(params.eps_km));
  body.append("min_samples", String(params.min_samples));
  body.append("noise_reassign_factor", String(params.noise_reassign_factor));
  return body;
}

/**
 * Agrupa las camaras sin resolver recorridos: vista previa de los clusters.
 *
 * Es el paso 1 de 2 — con los clusters ya formados, el usuario les asigna un
 * punto de partida antes de pedir /optimize/. No toca OSRM.
 */
export function previewClusters(
  file: File,
  mapping: ColumnMapping,
  params: ClusterParams,
): Promise<ProcessResponse> {
  return post<ProcessResponse>("/process/", mappingFields(file, mapping, params));
}

/**
 * Resuelve el orden de visita de cada cluster dentro del presupuesto de
 * jornada, a partir del punto de partida que el usuario le asignó a cada uno.
 *
 * El archivo se reenvia en cada llamada: el backend no guarda estado, asi que
 * reajustar los parametros es simplemente volver a postear.
 */
export function optimize(
  file: File,
  mapping: ColumnMapping,
  params: ClusterParams,
  routing: RouteParams,
  clusterStarts: Record<number, ClusterStart>,
): Promise<OptimizeResponse> {
  const body = mappingFields(file, mapping, params);
  body.append("provider", routing.provider);
  body.append("cluster_starts_json", JSON.stringify(clusterStarts));
  body.append("day_budget_s", String(routing.day_budget_s));
  body.append("service_time_s", String(routing.service_time_s));
  body.append("average_speed_kmh", String(routing.average_speed_kmh));
  body.append("time_limit_s", String(routing.time_limit_s));
  body.append("max_stops_per_day", String(routing.max_stops_per_day));
  body.append("min_stops_per_day", String(routing.min_stops_per_day));
  return post<OptimizeResponse>("/optimize/", body);
}

export type ExportStop = {
  camera_id: string;
  lat: number;
  lon: number;
  node: string | null;
  observation: string | null;
};

/** Un recorrido con la fecha en que se va a hacer ("AAAA-MM-DD"). */
export type ExportDay = {
  date: string;
  cluster_id: number;
  day: number;
  start_name: string | null;
  distance_m: number;
  duration_s: number;
  stops: ExportStop[];
};

/** Nombre sugerido por el backend en Content-Disposition, si vino. */
function filenameFrom(response: Response, fallback: string): string {
  const header = response.headers.get("Content-Disposition") ?? "";
  return /filename="([^"]+)"/.exec(header)?.[1] ?? fallback;
}

/**
 * Pide el Excel de seguimiento del plan. Devuelve el archivo y el nombre con
 * que conviene guardarlo; la descarga en sí la dispara quien llama.
 */
export async function exportPlan(
  days: ExportDay[],
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE_URL}/export/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ days }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string" ? detail : `No se pudo exportar (error ${response.status})`,
    );
  }

  return { blob: await response.blob(), filename: filenameFrom(response, "plan-recorridos.xlsx") };
}
