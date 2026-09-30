"use client";

import type { LngLatBoundsLike, MapRef } from "react-map-gl/maplibre";
import {
  Layer,
  Map as MapLibreMap,
  NavigationControl,
  Popup,
  ScaleControl,
  Source,
} from "react-map-gl/maplibre";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";

import type { Camera, Cluster, ClusterRoute, ClusterStart, Depot } from "@/lib/api";
import { circlePolygon } from "@/lib/geo";
import { OSM_STYLE } from "@/lib/mapStyle";
import { DAY_COLOR_EXPRESSION, DEPOT_INK, MARK_RING, NOISE_INK } from "@/lib/vizTokens";

/** Punto de partida asignado a un cluster, tal como se va a mandar al backend. */
export type StartPoint = ClusterStart & { cluster: number };

type Props = {
  cameras: Camera[];
  routes: ClusterRoute[];
  clusters: Cluster[];
  depots: Depot[];
  starts: StartPoint[];
  selectedCluster: number | null;
  /** Jornada resaltada dentro de `selectedCluster`; null = todas sus jornadas. */
  selectedDay: number | null;
  onSelectCluster: (cluster: number | null) => void;
};

type HoverInfo = {
  lat: number;
  lon: number;
  id: string;
  label: string | null;
  cluster: number;
  day: number | null;
  stop: number | null;
};

type StopRef = { day: number; order: number };
type LatLon = { lat: number; lon: number };

const POINTS_LAYER = "camaras-punto";

// Cámaras con recorrido: color de su día. Ruido o sin recorrido (no entraron
// en ninguna jornada): tinta neutra, para que no se confundan con un día.
const CAMERA_COLOR = ["case", [">=", ["get", "day"], 1], DAY_COLOR_EXPRESSION, NOISE_INK];

// Texto sobre el mapa: tinta de texto, nunca el color de la serie.
const LABEL_INK = "#0b0b0b";

// Filtro que deja pasar todo: todas las capas filtrables tienen `cluster`.
const MATCH_ALL = ["has", "cluster"];

export default function MapView({
  cameras,
  routes,
  clusters,
  depots,
  starts,
  selectedCluster,
  selectedDay,
  onSelectCluster,
}: Props) {
  const mapRef = useRef<MapRef | null>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);

  /** Jornada y posición de cada cámara dentro de su recorrido. */
  const stopByCamera = useMemo(() => {
    const map = new Map<string, StopRef>();
    for (const route of routes) {
      for (const stop of route.stops) {
        map.set(stop.camera_id, { day: route.vehicle_day, order: stop.order });
      }
    }
    return map;
  }, [routes]);

  const points = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: cameras.map((camera) => {
        const stop = stopByCamera.get(camera.id);
        return {
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [camera.lon, camera.lat] },
          properties: {
            id: camera.id,
            label: camera.label ?? "",
            cluster: camera.cluster,
            day: stop?.day ?? -1,
            reassigned: camera.reassigned,
            stop: stop?.order ?? -1,
            // Con ruta, el rótulo es "día·orden de visita"; sin ruta, el cluster.
            tag:
              camera.cluster === -1
                ? "·"
                : stop
                  ? `${stop.day}·${stop.order + 1}`
                  : String(camera.cluster),
          },
        };
      }),
    }),
    [cameras, stopByCamera],
  );

  const boundaries = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: clusters.map((cluster) => ({
        type: "Feature" as const,
        geometry: circlePolygon(cluster.centroid_lat, cluster.centroid_lon, cluster.radius_km),
        properties: { cluster: cluster.id },
      })),
    }),
    [clusters],
  );

  const depotPoints = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: depots.map((depot) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [depot.lon, depot.lat] },
        properties: { name: depot.name || "Sede" },
      })),
    }),
    [depots],
  );

  const startPoints = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: starts.map((start) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [start.lon, start.lat] },
        properties: {
          cluster: start.cluster,
          name: `Salida C${start.cluster}${start.name ? ` · ${start.name}` : ""}`,
        },
      })),
    }),
    [starts],
  );

  const lines = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: routes
        .filter((route) => route.geometry.length > 1)
        .map((route) => ({
          type: "Feature" as const,
          geometry: {
            type: "LineString" as const,
            coordinates: route.geometry.map(([lat, lon]) => [lon, lat]),
          },
          properties: {
            cluster: route.cluster_id,
            day: route.vehicle_day,
            label: `Día ${route.vehicle_day}`,
          },
        })),
    }),
    [routes],
  );

  /** Encuadra el mapa sobre el conjunto de puntos que se le pase. */
  const fitTo = useCallback((subset: LatLon[], maxZoom: number) => {
    const map = mapRef.current;
    if (!map || subset.length === 0) return;

    const lats = subset.map((point) => point.lat);
    const lons = subset.map((point) => point.lon);
    const bounds: LngLatBoundsLike = [
      [Math.min(...lons), Math.min(...lats)],
      [Math.max(...lons), Math.max(...lats)],
    ];
    map.fitBounds(bounds, { padding: 60, maxZoom, duration: 600 });
  }, []);

  // Al cargar datos nuevos, encuadrar los recorridos — no todos los puntos.
  // Una sola parada aislada a cientos de kilometros obligaria a alejar tanto
  // el mapa que los recorridos quedarian de un pixel. Si no hay ningun
  // recorrido, se encuadra todo lo que haya.
  useEffect(() => {
    const enRuta = cameras.filter((camera) => camera.cluster !== -1);
    fitTo(enRuta.length > 0 ? enRuta : cameras, 15);
  }, [cameras, fitTo]);

  // Al elegir un cluster o una jornada, acercarse a ella (incluida la salida).
  // Sin esto, una sola parada lejana obliga a alejar tanto el mapa que los
  // recorridos quedan de un pixel y parece que no se dibujo nada.
  useEffect(() => {
    if (selectedCluster === null) return;
    const route =
      selectedDay === null
        ? undefined
        : routes.find(
            (candidate) =>
              candidate.cluster_id === selectedCluster && candidate.vehicle_day === selectedDay,
          );
    if (route) {
      fitTo([...route.stops, { lat: route.start_lat, lon: route.start_lon }], 16);
      return;
    }
    fitTo(
      cameras.filter((camera) => camera.cluster === selectedCluster),
      16,
    );
  }, [selectedCluster, selectedDay, routes, cameras, fitTo]);

  const handleClick = useCallback(
    (event: { features?: { properties?: Record<string, unknown> }[] }) => {
      const feature = event.features?.[0];
      if (!feature) {
        onSelectCluster(null);
        return;
      }
      const cluster = Number(feature.properties?.cluster);
      onSelectCluster(cluster === selectedCluster ? null : cluster);
    },
    [onSelectCluster, selectedCluster],
  );

  const handleHover = useCallback(
    (event: {
      features?: { properties?: Record<string, unknown> }[];
      lngLat: { lat: number; lng: number };
    }) => {
      const feature = event.features?.[0];
      if (!feature) {
        setHover(null);
        return;
      }
      const properties = feature.properties ?? {};
      const stop = Number(properties.stop);
      const day = Number(properties.day);
      setHover({
        lat: event.lngLat.lat,
        lon: event.lngLat.lng,
        id: String(properties.id ?? ""),
        label: properties.label ? String(properties.label) : null,
        cluster: Number(properties.cluster),
        day: day >= 1 ? day : null,
        stop: stop >= 0 ? stop : null,
      });
    },
    [],
  );

  /** Condición MapLibre "pertenece al cluster seleccionado", o null sin selección. */
  const clusterMatch = useMemo(
    () => (selectedCluster === null ? null : ["==", ["get", "cluster"], selectedCluster]),
    [selectedCluster],
  );

  /**
   * Filtro de lo que se dibuja: con una jornada elegida, sólo ella; con un
   * cluster elegido, sólo sus jornadas; sin selección, todo. "Todo" es
   * MATCH_ALL y no `undefined`: react-map-gl pasa el prop tal cual y MapLibre
   * rechaza la capa entera si `filter` no es un array.
   */
  const selectionFilter = useMemo(() => {
    if (clusterMatch === null) return MATCH_ALL;
    if (selectedDay === null) return clusterMatch;
    return ["all", clusterMatch, ["==", ["get", "day"], selectedDay]];
  }, [clusterMatch, selectedDay]);

  // El límite del cluster y su salida se filtran por cluster, nunca por
  // jornada: no tienen propiedad `day`.
  const boundaryFilter = clusterMatch ?? MATCH_ALL;

  return (
    <MapLibreMap
      ref={mapRef}
      initialViewState={{ longitude: -65.4117, latitude: -24.7859, zoom: 10 }}
      style={{ width: "100%", height: "100%" }}
      mapStyle={OSM_STYLE}
      interactiveLayerIds={[POINTS_LAYER]}
      onClick={handleClick}
      onMouseMove={handleHover}
      onMouseOut={() => setHover(null)}
      cursor={hover ? "pointer" : "grab"}
    >
      <NavigationControl position="top-right" />
      <ScaleControl position="bottom-left" />

      {clusters.length > 0 && (
        <Source id="limites-cluster" type="geojson" data={boundaries}>
          <Layer
            id="limites-cluster-relleno"
            type="fill"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            filter={boundaryFilter as any}
            paint={{ "fill-color": NOISE_INK, "fill-opacity": 0.05 }}
          />
          <Layer
            id="limites-cluster-borde"
            type="line"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            filter={boundaryFilter as any}
            paint={{ "line-color": NOISE_INK, "line-width": 1.5, "line-opacity": 0.3 }}
          />
        </Source>
      )}

      {routes.length > 0 && (
        <Source id="recorridos" type="geojson" data={lines}>
          <Layer
            id="recorridos-halo"
            type="line"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            filter={selectionFilter as any}
            layout={{ "line-cap": "round", "line-join": "round" }}
            paint={{ "line-color": MARK_RING, "line-width": 7, "line-opacity": 0.9 }}
          />
          <Layer
            id="recorridos-linea"
            type="line"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            filter={selectionFilter as any}
            layout={{ "line-cap": "round", "line-join": "round" }}
            paint={{
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              "line-color": DAY_COLOR_EXPRESSION as any,
              "line-width": 4,
              "line-opacity": 0.9,
            }}
          />
          <Layer
            id="recorridos-rotulo"
            type="symbol"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            filter={selectionFilter as any}
            minzoom={11}
            layout={{
              "symbol-placement": "line",
              "symbol-spacing": 280,
              "text-field": ["get", "label"],
              "text-font": ["Noto Sans Bold"],
              "text-size": 11,
            }}
            paint={{
              "text-color": LABEL_INK,
              "text-halo-color": MARK_RING,
              "text-halo-width": 2,
            }}
          />
        </Source>
      )}

      {cameras.length > 0 && (
        <Source id="camaras" type="geojson" data={points}>
          <Layer
            id={POINTS_LAYER}
            type="circle"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            filter={selectionFilter as any}
            paint={{
              "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 4, 14, 9],
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              "circle-color": CAMERA_COLOR as any,
              // Trazo mas grueso para cámaras reasignadas desde ruido — sin
              // sumar color nuevo, sólo distingue el outlier por contorno.
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              "circle-stroke-width": ["case", ["get", "reassigned"], 3, 2] as any,
              "circle-stroke-color": MARK_RING,
              "circle-opacity": 0.95,
            }}
          />
          <Layer
            id="camaras-rotulo"
            type="symbol"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            filter={selectionFilter as any}
            minzoom={12}
            layout={{
              "text-field": ["get", "tag"],
              "text-font": ["Noto Sans Bold"],
              "text-size": 11,
              "text-offset": [0, -1.3],
              "text-allow-overlap": false,
            }}
            paint={{
              "text-color": LABEL_INK,
              "text-halo-color": MARK_RING,
              "text-halo-width": 1.5,
            }}
          />
        </Source>
      )}

      {depots.length > 0 && (
        <Source id="sedes" type="geojson" data={depotPoints}>
          <Layer
            id="sedes-punto"
            type="circle"
            paint={{
              "circle-radius": 7,
              "circle-color": DEPOT_INK,
              "circle-stroke-width": 2,
              "circle-stroke-color": MARK_RING,
            }}
          />
          <Layer
            id="sedes-rotulo"
            type="symbol"
            layout={{
              "text-field": ["get", "name"],
              "text-font": ["Noto Sans Bold"],
              "text-size": 11,
              "text-offset": [0, 1.3],
              "text-anchor": "top",
            }}
            paint={{
              "text-color": DEPOT_INK,
              "text-halo-color": MARK_RING,
              "text-halo-width": 1.5,
            }}
          />
        </Source>
      )}

      {starts.length > 0 && (
        <Source id="salidas" type="geojson" data={startPoints}>
          <Layer
            id="salidas-punto"
            type="circle"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            filter={boundaryFilter as any}
            paint={{
              // Anillo verde con centro blanco: misma categoría que las sedes
              // ("acá sale un vehículo") pero distinguible cuando no coinciden.
              "circle-radius": 9,
              "circle-color": MARK_RING,
              "circle-stroke-width": 4,
              "circle-stroke-color": DEPOT_INK,
            }}
          />
          <Layer
            id="salidas-rotulo"
            type="symbol"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            filter={boundaryFilter as any}
            layout={{
              "text-field": ["get", "name"],
              "text-font": ["Noto Sans Bold"],
              "text-size": 11,
              "text-offset": [0, -1.4],
              "text-anchor": "bottom",
            }}
            paint={{
              "text-color": DEPOT_INK,
              "text-halo-color": MARK_RING,
              "text-halo-width": 1.5,
            }}
          />
        </Source>
      )}

      {hover && (
        <Popup
          longitude={hover.lon}
          latitude={hover.lat}
          closeButton={false}
          closeOnClick={false}
          offset={14}
          maxWidth="260px"
        >
          <div className="text-xs leading-relaxed text-slate-900">
            <div className="font-semibold">{hover.id}</div>
            {hover.label && <div className="text-slate-600">{hover.label}</div>}
            <div className="text-slate-600">
              {hover.cluster === -1 ? "Sin cluster (ruido)" : `Cluster ${hover.cluster}`}
              {hover.day !== null && ` · día ${hover.day}`}
              {hover.stop !== null && ` · parada ${hover.stop + 1}`}
            </div>
          </div>
        </Popup>
      )}
    </MapLibreMap>
  );
}
