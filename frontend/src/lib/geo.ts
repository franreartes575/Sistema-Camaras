/** Utilidades geográficas mínimas, sin depender de una librería como turf. */

// Debe coincidir con EARTH_RADIUS_KM en backend/app/services/clustering.py.
const EARTH_RADIUS_KM = 6371.0088;

/**
 * Genera un polígono GeoJSON que aproxima un círculo geográfico.
 *
 * Usa la fórmula esférica de punto-destino por rumbo: un vértice cada
 * `360/steps` grados alrededor del centro. 48 pasos es suave de sobra a la
 * escala en que se usa este mapa (ciudad/provincia) y barato de recalcular
 * para unas pocas decenas de clusters.
 */
export function circlePolygon(
  centerLat: number,
  centerLon: number,
  radiusKm: number,
  steps = 48,
): GeoJSON.Polygon {
  const lat1 = (centerLat * Math.PI) / 180;
  const lon1 = (centerLon * Math.PI) / 180;
  const angularDistance = radiusKm / EARTH_RADIUS_KM;

  const ring: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const bearing = (2 * Math.PI * i) / steps;
    const lat2 = Math.asin(
      Math.sin(lat1) * Math.cos(angularDistance) +
        Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(bearing),
    );
    const lon2 =
      lon1 +
      Math.atan2(
        Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(lat1),
        Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2),
      );
    ring.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }

  return { type: "Polygon", coordinates: [ring] };
}
