/**
 * Fechas de planificación de cada recorrido (jornada).
 *
 * Las fechas se manejan como texto ISO "AAAA-MM-DD" en hora local, igual que
 * un <input type="date">: así nunca se corren un día por la zona horaria, que
 * es lo que pasa al pasar por `Date.toISOString()` (UTC).
 */

type RouteRef = { cluster_id: number; vehicle_day: number };

export type PlanDateOptions = {
  /** Fecha del primer recorrido. */
  start: string;
  /** Si es true, sábados y domingos no reciben recorridos. */
  skipWeekends: boolean;
};

/** Clave estable de un recorrido: cluster + número de jornada. */
export function routeKey(route: RouteRef): string {
  return `${route.cluster_id}-${route.vehicle_day}`;
}

function parseIso(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function toIso(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function isWeekend(date: Date): boolean {
  const weekday = date.getDay();
  return weekday === 0 || weekday === 6;
}

/** Hoy, en hora local. */
export function todayIso(): string {
  return toIso(new Date());
}

/** `iso` si es hábil; si no (y se saltean fines de semana), el próximo lunes. */
export function firstWorkingDay(iso: string, skipWeekends: boolean): string {
  const date = parseIso(iso);
  while (skipWeekends && isWeekend(date)) date.setDate(date.getDate() + 1);
  return toIso(date);
}

/** El día hábil siguiente a `iso`. */
function nextWorkingDay(iso: string, skipWeekends: boolean): string {
  const date = parseIso(iso);
  date.setDate(date.getDate() + 1);
  return firstWorkingDay(toIso(date), skipWeekends);
}

/**
 * Fecha de cada recorrido, en el orden en que vienen (cluster y jornada).
 *
 * Una cuadrilla, un recorrido por día: cada jornada toma el día hábil
 * siguiente al anterior. Las fechas cargadas a mano (`overrides`) mandan
 * sobre la sugerida, sin correr la secuencia de las demás — cambiar un día no
 * reprograma todo el resto.
 */
export function assignRouteDates(
  routes: RouteRef[],
  options: PlanDateOptions,
  overrides: Record<string, string>,
): Record<string, string> {
  const dates: Record<string, string> = {};
  if (!options.start) return dates;

  let cursor = firstWorkingDay(options.start, options.skipWeekends);
  for (const route of routes) {
    const key = routeKey(route);
    dates[key] = overrides[key] || cursor;
    cursor = nextWorkingDay(cursor, options.skipWeekends);
  }
  return dates;
}

/** `iso` corrido `days` días (negativo = hacia atrás). */
export function shiftIso(iso: string, days: number): string {
  const date = parseIso(iso);
  date.setDate(date.getDate() + days);
  return toIso(date);
}

/** Lunes de la semana de `iso`. */
export function weekStartIso(iso: string): string {
  const weekday = parseIso(iso).getDay(); // 0 = domingo
  return shiftIso(iso, weekday === 0 ? -6 : 1 - weekday);
}

/** Primer y último día del mes de `iso`. */
export function monthRangeIso(iso: string): { from: string; to: string } {
  const date = parseIso(iso);
  const last = new Date(date.getFullYear(), date.getMonth() + 1, 0);
  return { from: toIso(new Date(date.getFullYear(), date.getMonth(), 1)), to: toIso(last) };
}
