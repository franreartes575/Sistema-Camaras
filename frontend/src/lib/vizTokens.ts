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

/**
 * Estado de cada tarea del registro. Es la escala de estado (fija, nunca por
 * tema), distinta de los slots categóricos para no hacerse pasar por un día.
 *
 * Verde y rojo NO se distinguen con deuteranopía (ΔE 4.1 medido con el script
 * de la skill dataviz contra el panel slate-900): por eso un estado nunca va
 * sólo con color. En el panel lleva ícono + rótulo; en el mapa, un ícono
 * dibujado (✓, ✕, punto hueco, flecha) — ver `lib/statusIcons.ts`; y en las
 * barras apiladas lo pendiente va entre lo realizado y lo no realizado, así
 * el par verde/rojo nunca queda contiguo.
 */
export const STATUS_INK = {
  realizada: "#0ca30c",
  no_realizada: "#d03b3b",
  // Neutros: "falta y nadie informó nada" y "ya está en otro plan".
  pendiente: "#94a3b8",
  reprogramada: "#64748b",
} as const;

/** Lo pendiente en el mapa va hueco: aro oscuro sobre blanco, lejos del verde y el rojo. */
export const PENDING_RING = "#334155";

/** Línea de un recorrido del registro sin color de día asignado. */
export const ROUTE_LINE = SERIES_BASE;

/**
 * Colores de los días del Registro: uno por fecha, para reconocerla de un
 * vistazo en el mapa y en la grilla de días. Son diez porque un plan suele
 * tener hasta diez jornadas; con más, se repiten.
 *
 * El orden importa: los colores se asignan por fecha, así que dos días
 * seguidos reciben colores vecinos de la lista, y por eso van alternados
 * (frío/cálido, claro/oscuro): entre vecinos la distancia de color (ΔE76) es
 * de 62 como mínimo. Los dos más parecidos (bermellón y ámbar, ΔE 24) quedan
 * a cinco lugares uno del otro. Con diez tonos sobre el fondo de OSM igual
 * hay parecidos: el mapa suma una leyenda con el color de cada día y el
 * rótulo "fecha · Día N" sobre cada línea.
 */
export const REGISTRY_DAY_PALETTE = [
  "#0072b2", // azul
  "#d55e00", // bermellón
  "#009e73", // verde
  "#b6407f", // magenta
  "#2b2b2b", // carbón
  "#7a3db8", // violeta
  "#c27c00", // ámbar
  "#2aa7d8", // celeste
  "#b91c1c", // carmesí
  "#6a8d1f", // oliva
] as const;

/**
 * Color de cada fecha: se reparte por orden cronológico entre todas las
 * fechas a la vista (no sólo las marcadas), así un día no cambia de color al
 * marcar o sacar otros.
 */
export function assignDayColors(dates: string[]): Record<string, string> {
  const unique = [...new Set(dates)].sort();
  return Object.fromEntries(
    unique.map((date, index) => [date, REGISTRY_DAY_PALETTE[index % REGISTRY_DAY_PALETTE.length]]),
  );
}

/**
 * Color de cada cluster en el mapa del Inicio. Es la excepción a la regla de
 * arriba: ahí se pide distinguir clusters a simple vista, con todo el catálogo
 * a la vista. Son los mismos cinco colores validados de DAY_PALETTE (el máximo
 * que pasa contra el tile comparando todos los pares; el par verde/rojo queda
 * en la banda 6–8 de daltonismo, legal sólo con codificación secundaria). Con
 * más clusters que colores el backend (`assign_colors`) reparte los índices
 * para que los cercanos no se repitan, y la identidad la lleva el rótulo
 * "C n" en el centro de cada uno.
 */
export const CLUSTER_PALETTE = DAY_PALETTE;

/** Expresión MapLibre: color según la propiedad `color` (índice); -1 = suelta. */
export const CLUSTER_COLOR_EXPRESSION = [
  "match",
  ["get", "color"],
  ...CLUSTER_PALETTE.flatMap((color, index) => [index, color]),
  NOISE_INK,
];

/**
 * Barras de magnitud de una sola serie sobre el panel oscuro (slate-900).
 * Validada con el script de la skill dataviz: dentro de la banda de
 * luminosidad del modo oscuro y por encima de 3:1 contra el panel.
 */
export const PANEL_BAR = "#3b8fe0";
