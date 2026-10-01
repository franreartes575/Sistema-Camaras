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
