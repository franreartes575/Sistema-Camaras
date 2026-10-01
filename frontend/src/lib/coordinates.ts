/** Lectura de coordenadas pegadas como texto, p. ej. desde Google Maps. */

export type LatLon = { lat: number; lon: number };

const NUMBER = /^[-+]?\d+(?:\.\d+)?$/;

function toNumber(text: string): number | null {
  const cleaned = text.trim().replace(",", ".");
  return NUMBER.test(cleaned) ? Number(cleaned) : null;
}

function splitPair(text: string): string[] | null {
  if (text.includes(";")) return text.split(";");

  const byComma = text.split(",").filter((part) => part.trim() !== "");
  if (byComma.length === 2) return byComma;
  // "-24,775119, -65,427213": coma decimal en ambos valores.
  if (byComma.length === 4) return [`${byComma[0]},${byComma[1]}`, `${byComma[2]},${byComma[3]}`];

  const byBlank = text.split(/\s+/).filter(Boolean);
  return byBlank.length === 2 ? byBlank : null;
}

/**
 * Interpreta "lat, lon" tal como lo copia Google Maps ("-24.775119, -65.427213").
 * Acepta también separador por espacio o punto y coma, coma decimal y
 * paréntesis o grados alrededor. Devuelve null si no es un par válido.
 */
export function parseCoordinatePair(text: string): LatLon | null {
  const cleaned = text.replace(/[()[\]°]/g, " ").trim();
  const parts = cleaned ? splitPair(cleaned) : null;
  if (!parts) return null;

  const lat = toNumber(parts[0]);
  const lon = toNumber(parts[1]);
  if (lat === null || lon === null) return null;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}

export function formatCoordinatePair({ lat, lon }: LatLon): string {
  return `${lat}, ${lon}`;
}
