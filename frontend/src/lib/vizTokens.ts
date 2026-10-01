/**
 * Tokens de color para las capas del mapa.
 *
 * El numero de clusters no esta acotado, asi que la identidad de cada uno NO se
 * codifica con matiz: una paleta categorica solo sostiene 3 colores simultaneos
 * sobre el fondo de los tiles OSM antes de que pares como naranja/amarillo caigan
 * por debajo del piso de distinguibilidad. En su lugar la identidad la lleva el
 * numero impreso sobre cada punto. Lo que sí lleva color es la jornada (día) de
 * cada recorrido — ver DAY_PALETTE y sus límites.
 */

/** Fondo aproximado de los tiles raster de OpenStreetMap. */
export const TILE_SURFACE = "#f2efe9";

/** Slot categorico 1 — cluster en reposo. Contraste 3.5:1 sobre el tile. */
export const SERIES_BASE = "#2a78d6";

/** Slot categorico 2 — cluster seleccionado. */
export const SERIES_SELECTED = "#eb6834";

/** Tinta atenuada para el ruido DBSCAN (camaras sin cluster). */
export const NOISE_INK = "#52514e";

/** Halo blanco: separa los puntos entre si y del mapa de fondo. */
export const MARK_RING = "#ffffff";

/**
 * Tinta para sedes / puntos de partida. Las sedes son un conjunto chico y
 * acotado (a diferencia de los clusters, sin límite), así que un color propio
 * no choca con la regla de arriba: no identifica un cluster, identifica una
 * categoría nueva ("acá sale un vehículo").
 */
export const DEPOT_INK = "#1fb17a";

/**
 * Color de cada jornada (día) de recorrido.
 *
 * Validada con el script de la skill dataviz contra TILE_SURFACE comparando
 * TODOS los pares (con varios días a la vista cualquier par puede quedar
 * junto): es el conjunto más grande que pasa. Sumar rosa u otro naranja rompe
 * el piso de visión normal; verde/rojo queda en la banda 6–8 para daltonismo,
 * legal sólo con codificación secundaria — que existe: cada línea lleva
 * "Día N" y cada parada "día·orden". Por la misma razón, con más de cinco
 * días el color se repite: la identidad la sigue llevando el rótulo, y al
 * seleccionar un día se dibuja solo, sin nada con qué confundirlo.
 */
export const DAY_PALETTE = ["#2a78d6", "#eda100", "#4a3aa7", "#e34948", "#008300"] as const;

/** Color de la jornada `day` (base 1). */
export function dayColor(day: number): string {
  return DAY_PALETTE[(day - 1) % DAY_PALETTE.length];
}

/**
 * Expresión MapLibre equivalente a `dayColor`, leyendo la propiedad `day`.
 * Es un `match` y no un `at` sobre un literal: MapLibre tipa ese literal como
 * array<string> y rechaza la capa por no ser array<color>.
 */
export const DAY_COLOR_EXPRESSION = [
  "match",
  ["%", ["-", ["get", "day"], 1], DAY_PALETTE.length],
  ...DAY_PALETTE.slice(0, -1).flatMap((color, index) => [index, color]),
  DAY_PALETTE[DAY_PALETTE.length - 1],
];
