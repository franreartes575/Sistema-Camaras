import type { StyleSpecification } from "maplibre-gl";

/**
 * Estilo raster 100% libre servido por los tiles de OpenStreetMap.
 * Sin API keys ni proveedores propietarios.
 */
export const OSM_STYLE: StyleSpecification = {
  version: 8,
  // Servidor de glifos libre de OpenMapTiles, necesario para rotular los puntos.
  // Si no responde, los circulos se dibujan igual y solo se pierde el numero.
  glyphs: "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf",
  sources: {
    osm: {
      type: "raster",
      tiles: [
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    },
  },
  layers: [{ id: "osm-tiles", type: "raster", source: "osm", minzoom: 0, maxzoom: 22 }],
};
