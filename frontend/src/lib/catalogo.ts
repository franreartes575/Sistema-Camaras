/**
 * Cliente del catálogo de cámaras y de las sedes (/catalogo/ en el backend).
 *
 * El catálogo guarda todas las cámaras con su localidad (el municipio, que el
 * backend calcula por coordenadas). Planificar desde el catálogo no es un
 * camino aparte: el backend arma una planilla con las cámaras elegidas y
 * entra por el paso 1 como cualquier otra.
 */

import { filenameFrom, type ColumnMapping, type Depot, type DiscardedRow } from "@/lib/api";
import { apiError, apiFetch, apiJson, jsonBody } from "@/lib/http";
import type { ReportedStatus, TaskCounts } from "@/lib/registro";

export type CatalogCamera = {
  id: string;
  lat: number;
  lon: number;
  /** Municipio, calculado por coordenadas (o corregido a mano). */
  locality: string;
  locality_manual: boolean;
  label: string | null;
  node: string | null;
  observation: string | null;
  created_at: string;
  updated_at: string;
  /** Tareas realizadas en esta cámara. */
  visits: number;
  /** "AAAA-MM-DD" de la última realizada. */
  last_visit: string | null;
  /** Estado de su tarea más reciente (la del plan más nuevo). */
  last_status: ReportedStatus | null;
  last_planned: string | null;
};

export type CatalogImportResult = {
  import_id: number;
  filename: string;
  rows: number;
  valid: number;
  added: number;
  updated: number;
  unchanged: number;
  duplicates: number;
  discarded: DiscardedRow[];
  camera_count: number;
  municipalities_loaded: boolean;
  warning: string | null;
  previously_loaded_at: string | null;
};

export type CatalogImport = {
  id: number;
  filename: string;
  loaded_at: string;
  rows: number;
  added: number;
  updated: number;
  unchanged: number;
  discarded: number;
};

export type CatalogCluster = {
  id: number;
  size: number;
  centroid_lat: number;
  centroid_lon: number;
  radius_km: number;
  /** Índice en la paleta: dos clusters vecinos nunca comparten. */
  color: number;
  /** La sede de cuya zona es; null = sin sede (agrupado por cercanía). */
  depot: { name: string; lat: number; lon: number } | null;
};

export type CatalogClusters = {
  eps_km: number;
  by_depot: boolean;
  depot_max_km: number;
  cameras: { id: string; cluster: number }[];
  clusters: CatalogCluster[];
  noise_count: number;
};

export type LocalitySummary = {
  name: string;
  cameras: number;
  /** Cámaras con al menos una tarea realizada. */
  visited: number;
  /** Cámaras cuya tarea más reciente todavía falta. */
  pending: number;
  last_visit: string | null;
};

export type MonthTasks = {
  /** "AAAA-MM" */
  month: string;
  done: number;
  pending: number;
  not_done: number;
  rescheduled: number;
};

export type DepotReach = {
  id: number;
  name: string;
  cameras: number;
  average_km: number | null;
  max_km: number | null;
};

export type CatalogSummary = {
  today: string;
  camera_count: number;
  locality_count: number;
  municipalities_loaded: boolean;
  localities: LocalitySummary[];
  visit_age: { never: number; within_30: number; within_90: number; older: number };
  plan_count: number;
  route_count: number;
  distance_m: number;
  tasks: TaskCounts;
  months: MonthTasks[];
  depots: DepotReach[];
  /** Hasta dónde llega la zona de una sede. */
  depot_max_km: number;
  /** Cámaras a más de esa distancia de toda sede. */
  outside_depots: number;
  planned_outside_catalog: number;
  last_import_at: string | null;
};

export type DepotIn = { name: string; lat: number; lon: number };

/** Localidades que no son un municipio (las devuelve el backend tal cual). */
export const LOCALITY_UNKNOWN = "Sin calcular";
export const LOCALITY_OUTSIDE = "Fuera de Salta";

/** Rutas de lectura: sirven también de clave para volver a pedir los datos. */
export const catalogPaths = {
  cameras: "/catalogo/camaras/",
  depots: "/catalogo/sedes/",
  summary: (depotMaxKm: number) => `/catalogo/resumen?max_sede_km=${depotMaxKm}`,
  imports: "/catalogo/importaciones/",
  clusters: (epsKm: number, colors: number, byDepot: boolean, depotMaxKm: number) =>
    `/catalogo/clusters?eps_km=${epsKm}&colores=${colors}&por_sede=${byDepot}&max_sede_km=${depotMaxKm}`,
};

function request<T>(path: string, init?: RequestInit): Promise<T> {
  return apiJson<T>(path, init, "Error del catálogo");
}

/** Combina una planilla con el catálogo (sólo administradores). */
export function importCatalog(file: File, mapping: ColumnMapping): Promise<CatalogImportResult> {
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
  return request<CatalogImportResult>("/catalogo/importar/", { method: "POST", body });
}

/**
 * Planilla de entrada al planificador con las cámaras elegidas, lista para
 * pasarla al paso 1 como si se hubiera subido.
 */
export async function selectionWorkbook(ids: string[]): Promise<File> {
  const response = await apiFetch("/catalogo/planilla", jsonBody("POST", { ids }));
  if (!response.ok) throw await apiError(response, "No se pudo armar la planilla");
  const filename = filenameFrom(response, `catalogo-${ids.length}-camaras.xlsx`);
  return new File([await response.blob()], filename, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

const cameraPath = (id: string) => `/catalogo/camaras/${encodeURIComponent(id)}`;

/** Corrige la localidad a mano; con null vuelve al cálculo por coordenadas. */
export function setCameraLocality(id: string, locality: string | null): Promise<CatalogCamera> {
  return request<CatalogCamera>(cameraPath(id), jsonBody("PATCH", { locality }));
}

export function deleteCamera(id: string): Promise<void> {
  return request<void>(cameraPath(id), { method: "DELETE" });
}

export function createDepot(depot: DepotIn): Promise<Depot> {
  return request<Depot>("/catalogo/sedes/", jsonBody("POST", depot));
}

export function updateDepot(id: number, depot: DepotIn): Promise<Depot> {
  return request<Depot>(`/catalogo/sedes/${id}`, jsonBody("PUT", depot));
}

export function deleteDepot(id: number): Promise<void> {
  return request<void>(`/catalogo/sedes/${id}`, { method: "DELETE" });
}

/**
 * IDs pegados de cualquier lado: una columna de Excel (uno por línea), una
 * lista separada por comas, punto y coma, tabs o espacios. Sin repetir y en
 * el orden en que vinieron.
 */
export function parseIds(text: string): string[] {
  const ids = text
    .split(/[\s,;]+/)
    .map((id) => id.trim().replace(/^["']+|["']+$/g, ""))
    .filter(Boolean);
  return [...new Set(ids)];
}

// --------------------------------------------------------------------------
// Sedes que quedaron en el navegador (antes se guardaban sólo ahí)
// --------------------------------------------------------------------------

const LEGACY_DEPOTS_KEY = "sistema-logistico:sedes";

/** Las sedes viejas del localStorage, si quedan. */
export function legacyDepots(): DepotIn[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(LEGACY_DEPOTS_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (item): item is DepotIn =>
          typeof item === "object" &&
          item !== null &&
          typeof item.lat === "number" &&
          typeof item.lon === "number",
      )
      .map((item) => ({ name: String(item.name ?? "").trim(), lat: item.lat, lon: item.lon }));
  } catch {
    return [];
  }
}

export function forgetLegacyDepots(): void {
  try {
    window.localStorage.removeItem(LEGACY_DEPOTS_KEY);
  } catch {
    // Sin acceso al almacenamiento no hay nada que borrar.
  }
}

/**
 * Sube al servidor las sedes del navegador y, si salió bien, las borra de
 * ahí. Las que ya existen con el mismo nombre (409) se saltean.
 */
export async function migrateLegacyDepots(depots: DepotIn[]): Promise<number> {
  let created = 0;
  for (const [index, depot] of depots.entries()) {
    try {
      await createDepot({ ...depot, name: depot.name || `Sede ${index + 1}` });
      created += 1;
    } catch (err) {
      if (!(err instanceof Error && "status" in err && err.status === 409)) throw err;
    }
  }
  forgetLegacyDepots();
  return created;
}
