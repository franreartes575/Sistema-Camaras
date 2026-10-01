/**
 * Cliente del registro de recorridos (/registro/ en el backend).
 *
 * A diferencia del planificador, el registro sí guarda estado: planes,
 * jornadas, el estado de cada tarea y el historial de seguimientos cargados.
 */

import { API_BASE_URL, filenameFrom } from "@/lib/api";

export type TaskStatus = "pendiente" | "realizada" | "no_realizada" | "reprogramada";
/** Lo que se puede informar a mano: "reprogramada" se deriva sola. */
export type ReportedStatus = Exclude<TaskStatus, "reprogramada">;
/** Filtro de tareas; "faltan" = pendientes + no realizadas. */
export type StatusFilter = TaskStatus | "faltan";

export type TaskCounts = {
  total: number;
  done: number;
  pending: number;
  not_done: number;
  /** Pendientes que ya se volvieron a planificar en un plan posterior. */
  rescheduled: number;
};

export type PlanSummary = TaskCounts & {
  id: number;
  name: string;
  created_at: string;
  source_file: string | null;
  provider: string | null;
  is_road_network: boolean;
  notes: string | null;
  route_count: number;
  date_from: string | null;
  date_to: string | null;
  distance_m: number;
  duration_s: number;
};

export type RouteSummary = TaskCounts & {
  id: number;
  plan_id: number;
  plan_name: string;
  /** "AAAA-MM-DD" */
  date: string;
  cluster_id: number;
  day: number;
  start_name: string | null;
  start_lat: number;
  start_lon: number;
  distance_m: number;
  duration_s: number;
  has_unreachable_legs: boolean;
};

export type Task = {
  id: number;
  route_id: number;
  plan_id: number;
  plan_name: string;
  date: string;
  cluster_id: number;
  day: number;
  /** Posición en el recorrido, base 1. */
  order: number;
  camera_id: string;
  lat: number;
  lon: number;
  label: string | null;
  node: string | null;
  migrated_node: string | null;
  observation: string | null;
  status: TaskStatus;
  verified_at: string | null;
};

export type RouteDetail = RouteSummary & {
  /** Polilínea como pares [lat, lon]. */
  geometry: [number, number][];
  stops: Task[];
};

export type FollowUpResult = {
  import_id: number;
  filename: string;
  plan_id: number | null;
  plan_name: string | null;
  rows: number;
  matched: number;
  updated: number;
  done: number;
  not_done: number;
  no_news: number;
  unmatched: number;
  unmatched_ids: string[];
  previously_loaded_at: string | null;
};

export type FollowUpImport = {
  id: number;
  filename: string;
  loaded_at: string;
  plan_id: number | null;
  plan_name: string | null;
  rows: number;
  matched: number;
  updated: number;
  done: number;
  not_done: number;
  unmatched: number;
};

export type RegistryStopIn = {
  camera_id: string;
  lat: number;
  lon: number;
  label: string | null;
  node: string | null;
  observation: string | null;
};

export type RegistryRouteIn = {
  date: string;
  cluster_id: number;
  day: number;
  start_name: string | null;
  start_lat: number;
  start_lon: number;
  distance_m: number;
  duration_s: number;
  has_unreachable_legs: boolean;
  geometry: [number, number][];
  stops: RegistryStopIn[];
};

export type RegistryPlanIn = {
  name?: string | null;
  source_file: string | null;
  provider: string | null;
  is_road_network: boolean;
  routes: RegistryRouteIn[];
};

/** Filtros comunes de la sección Registro. "" / null = sin filtrar. */
export type RegistryFilters = {
  desde: string;
  hasta: string;
  planId: number | null;
  q: string;
};

// El backend acepta hasta 100 jornadas completas por pedido.
const DETAIL_CHUNK = 100;

/** Error del registro con el código HTTP, para distinguir 404/409 de una caída. */
export class RegistryError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function failure(response: Response, fallback: string): Promise<RegistryError> {
  const payload = await response.json().catch(() => null);
  const detail = payload?.detail;
  return new RegistryError(
    typeof detail === "string" ? detail : `${fallback} (error ${response.status})`,
    response.status,
  );
}

/** fetch con un mensaje entendible cuando el backend no está levantado. */
async function call(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API_BASE_URL}${path}`, init);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new Error("No se pudo conectar con el backend. Verificá que esté corriendo.");
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await call(path, init);
  if (!response.ok) throw await failure(response, "Error del registro");
  return (response.status === 204 ? undefined : await response.json()) as T;
}

function sendJson<T>(path: string, method: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Query string con los filtros y, opcionalmente, los estados de tarea. */
function filterQuery(filters: RegistryFilters, statuses: StatusFilter[] = []): string {
  const params = new URLSearchParams();
  if (filters.desde) params.set("desde", filters.desde);
  if (filters.hasta) params.set("hasta", filters.hasta);
  if (filters.planId !== null) params.set("plan_id", String(filters.planId));
  if (filters.q.trim()) params.set("q", filters.q.trim());
  for (const status of statuses) params.append("estado", status);
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** Rutas de lectura: sirven también de clave para volver a pedir los datos. */
export const registryPaths = {
  plans: "/registro/planes/",
  imports: "/registro/cargas/",
  routes: (filters: RegistryFilters) => `/registro/recorridos/${filterQuery(filters)}`,
  tasks: (filters: RegistryFilters, statuses: StatusFilter[]) =>
    `/registro/tareas/${filterQuery(filters, statuses)}`,
};

export function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { signal });
}

/** Guarda el plan; con `planId`, reemplaza ese plan en vez de crear otro. */
export function savePlan(plan: RegistryPlanIn, planId: number | null): Promise<PlanSummary> {
  return planId === null
    ? sendJson<PlanSummary>("/registro/planes/", "POST", plan)
    : sendJson<PlanSummary>(`/registro/planes/${planId}`, "PUT", plan);
}

export function updatePlan(
  planId: number,
  changes: { name?: string; notes?: string | null },
): Promise<PlanSummary> {
  return sendJson<PlanSummary>(`/registro/planes/${planId}`, "PATCH", changes);
}

export function deletePlan(planId: number): Promise<void> {
  return request<void>(`/registro/planes/${planId}`, { method: "DELETE" });
}

export function updateTask(
  taskId: number,
  changes: { status?: ReportedStatus; observation?: string | null; migrated_node?: string | null },
): Promise<Task> {
  return sendJson<Task>(`/registro/tareas/${taskId}`, "PATCH", changes);
}

/** Carga un Excel de seguimiento completado y actualiza las tareas. */
export function importFollowUp(file: File): Promise<FollowUpResult> {
  const body = new FormData();
  body.append("file", file);
  return request<FollowUpResult>("/registro/seguimiento/", { method: "POST", body });
}

/** Jornadas completas (paradas + polilínea), de a tandas de 100. */
export async function fetchRouteDetails(ids: number[], signal?: AbortSignal): Promise<RouteDetail[]> {
  const chunks: number[][] = [];
  for (let start = 0; start < ids.length; start += DETAIL_CHUNK) {
    chunks.push(ids.slice(start, start + DETAIL_CHUNK));
  }
  const pages = await Promise.all(
    chunks.map((chunk) => {
      const params = new URLSearchParams();
      for (const id of chunk) params.append("ids", String(id));
      return getJson<RouteDetail[]>(`/registro/recorridos/detalle?${params}`, signal);
    }),
  );
  return pages.flat();
}

async function download(path: string, fallbackName: string): Promise<{ blob: Blob; filename: string }> {
  const response = await call(path);
  if (!response.ok) throw await failure(response, "No se pudo descargar");
  return { blob: await response.blob(), filename: filenameFrom(response, fallbackName) };
}

/** Excel de tareas en el formato del seguimiento (reimportable en el paso 1). */
export function downloadTasks(filters: RegistryFilters, statuses: StatusFilter[]) {
  return download(`/registro/tareas.xlsx${filterQuery(filters, statuses)}`, "tareas-registro.xlsx");
}

/** La base completa, para guardarla como respaldo. */
export function downloadBackup() {
  return download("/registro/respaldo", "registro-recorridos.sqlite");
}

/** Cuántas tareas faltan: pendientes más las que no se pudieron hacer. */
export function missing(counts: TaskCounts): number {
  return counts.pending + counts.not_done;
}

/** Estado de una jornada, para filtrar y rotular la lista. */
export type RouteState = "completo" | "faltan" | "programado" | "reprogramado";

export function routeState(route: RouteSummary, today: string): RouteState {
  if (route.total > 0 && route.done === route.total) return "completo";
  if (missing(route) === 0) return "reprogramado";
  if (route.date > today && route.done + route.not_done === 0) return "programado";
  return "faltan";
}
