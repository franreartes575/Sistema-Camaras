/** Formatos de presentación compartidos por el panel y el mapa. */

/** Metros como km con un decimal, o metros redondos si es corto. */
export function formatDistance(meters: number | null): string {
  // null significa que la red vial no conecta el tramo, no que mida cero.
  if (meters === null) return "sin conexión";
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
}

/** Segundos como "X h Y min" (o sólo minutos si dura menos de una hora). */
export function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours === 0 ? `${minutes} min` : `${hours} h ${minutes} min`;
}

const DAY_LABEL = new Intl.DateTimeFormat("es-AR", {
  weekday: "short",
  day: "2-digit",
  month: "2-digit",
});

const WEEKDAY = new Intl.DateTimeFormat("es-AR", { weekday: "short" });

/** "2026-10-01" → "jue". */
export function formatWeekday(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return "";
  return WEEKDAY.format(new Date(year, month - 1, day)).replace(".", "");
}

/** "2026-10-01" → "jue 01/10". La fecha se interpreta en hora local. */
export function formatDayLabel(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  return DAY_LABEL.format(new Date(year, month - 1, day)).replace(",", "");
}

const LONG_DAY = new Intl.DateTimeFormat("es-AR", {
  weekday: "long",
  day: "numeric",
  month: "long",
});

/** "2026-10-01" → "01/10" (armado a mano: no depende del idioma del navegador). */
export function formatShortDate(iso: string): string {
  const [, month, day] = iso.split("-");
  return month && day ? `${day.slice(0, 2)}/${month}` : iso;
}

/** "2026-10-01" → "Jueves, 1 de octubre" (sólo la primera letra en mayúscula). */
export function formatLongDay(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  const text = LONG_DAY.format(new Date(year, month - 1, day));
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "2026-10-01 14:05:00" → "01/10 14:05" (marca de tiempo del backend). */
export function formatTimestamp(stamp: string): string {
  const [date, time = ""] = stamp.split(/[ T]/);
  return `${formatShortDate(date)} ${time.slice(0, 5)}`.trim();
}

/** Porcentaje entero, sin dividir por cero. */
export function percent(part: number, total: number): number {
  return total > 0 ? Math.round((part / total) * 100) : 0;
}
