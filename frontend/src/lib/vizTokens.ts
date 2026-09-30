/**
 * Tokens de color para las capas del mapa.
 *
 * El numero de clusters no esta acotado, asi que la identidad de cada uno NO se
 * codifica con matiz: una paleta categorica solo sostiene 3 colores simultaneos
 * sobre el fondo de los tiles OSM antes de que pares como naranja/amarillo caigan
 * por debajo del piso de distinguibilidad. En su lugar la identidad la lleva el
 * numero impreso sobre cada punto, y el color codifica un unico estado binario:
 * seleccionado vs. no seleccionado. Eso escala a cualquier cantidad de clusters.
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
