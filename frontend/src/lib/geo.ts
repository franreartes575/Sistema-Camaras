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

/** Distancia en línea recta entre dos puntos, en km (haversine). */
export function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = Math.PI / 180;
  const dLat = (lat2 - lat1) * toRad;
  const dLon = (lon2 - lon1) * toRad;
  const a =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

type LonLat = [number, number];

function cross(o: LonLat, a: LonLat, b: LonLat): number {
  return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
}

/** Envolvente convexa (monotone chain de Andrew), en sentido antihorario. */
function convexHull(points: LonLat[]): LonLat[] {
  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (sorted.length < 3) return sorted;
  const lower: LonLat[] = [];
  for (const point of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], point) <= 0) lower.pop();
    lower.push(point);
  }
  const upper: LonLat[] = [];
  for (const point of [...sorted].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], point) <= 0) upper.pop();
    upper.push(point);
  }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

/**
 * Contorno de cada cluster: la envolvente convexa de un pequeño octógono
 * (`padKm` de radio) alrededor de cada cámara. Sigue la forma real del grupo
 * —una ruta larga queda angosta— en vez de un círculo desde el centroide hasta
 * la cámara más lejana, que exagera los grupos alargados o con una cámara
 * apartada. Las cámaras sueltas (cluster -1) no tienen contorno.
 */
export function clusterOutlines<T extends { lat: number; lon: number }>(
  cameras: T[],
  clusterOf: (camera: T) => number,
  padKm = 1.5,
): Map<number, GeoJSON.Polygon> {
  const corners = new Map<number, LonLat[]>();
  for (const camera of cameras) {
    const cluster = clusterOf(camera);
    if (cluster === -1) continue;
    const dLat = padKm / 111.32;
    const dLon = dLat / Math.max(Math.cos((camera.lat * Math.PI) / 180), 0.1);
    const list = corners.get(cluster) ?? [];
    for (let i = 0; i < 8; i++) {
      const angle = (Math.PI / 4) * i;
      list.push([camera.lon + dLon * Math.cos(angle), camera.lat + dLat * Math.sin(angle)]);
    }
    corners.set(cluster, list);
  }
  const outlines = new Map<number, GeoJSON.Polygon>();
  for (const [cluster, points] of corners) {
    const hull = convexHull(points);
    outlines.set(cluster, { type: "Polygon", coordinates: [[...hull, hull[0]]] });
  }
  return outlines;
}
