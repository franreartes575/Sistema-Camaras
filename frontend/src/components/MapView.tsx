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

import type { Camera, ClusterRoute } from "@/lib/api";
import { OSM_STYLE } from "@/lib/mapStyle";
import { MARK_RING, NOISE_INK, SERIES_BASE, SERIES_SELECTED } from "@/lib/vizTokens";

type Props = {
  cameras: Camera[];
  routes: ClusterRoute[];
  selectedCluster: number | null;
  onSelectCluster: (cluster: number | null) => void;
};

type HoverInfo = {
  lat: number;
  lon: number;
  id: string;
  label: string | null;
  cluster: number;
  stop: number | null;
};

const POINTS_LAYER = "camaras-punto";

export default function MapView({
  cameras,
  routes,
  selectedCluster,
  onSelectCluster,
}: Props) {
  const mapRef = useRef<MapRef | null>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);

  /** Posición de cada cámara dentro del recorrido de su cluster. */
  const stopByCamera = useMemo(() => {
    const map = new Map<string, number>();
    for (const route of routes) {
      for (const stop of route.stops) map.set(stop.camera_id, stop.order);
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
            stop: stop ?? -1,
            // Con ruta, el rótulo es el orden de visita; sin ruta, el cluster.
            tag:
              camera.cluster === -1
                ? "·"
                : String(stop !== undefined ? stop + 1 : camera.cluster),
          },
        };
      }),
    }),
    [cameras, stopByCamera],
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
          properties: { cluster: route.cluster_id },
        })),
    }),
    [routes],
  );

  // Encuadra el mapa sobre los datos cada vez que cambia el conjunto.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || cameras.length === 0) return;

    const lats = cameras.map((camera) => camera.lat);
    const lons = cameras.map((camera) => camera.lon);
    const bounds: LngLatBoundsLike = [
      [Math.min(...lons), Math.min(...lats)],
      [Math.max(...lons), Math.max(...lats)],
    ];
    map.fitBounds(bounds, { padding: 60, maxZoom: 15, duration: 600 });
  }, [cameras]);

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
      setHover({
        lat: event.lngLat.lat,
        lon: event.lngLat.lng,
        id: String(properties.id ?? ""),
        label: properties.label ? String(properties.label) : null,
        cluster: Number(properties.cluster),
        stop: stop >= 0 ? stop : null,
      });
    },
    [],
  );

  const fillColor = useMemo(() => {
    const noiseCase = [["==", ["get", "cluster"], -1], NOISE_INK];
    const selectedCase =
      selectedCluster === null
        ? []
        : [["==", ["get", "cluster"], selectedCluster], SERIES_SELECTED];
    return ["case", ...noiseCase, ...selectedCase, SERIES_BASE];
  }, [selectedCluster]);

  const lineColor = useMemo(() => {
    const selectedCase =
      selectedCluster === null
        ? []
        : [["==", ["get", "cluster"], selectedCluster], SERIES_SELECTED];
    return ["case", ...selectedCase, SERIES_BASE];
  }, [selectedCluster]);

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

      {routes.length > 0 && (
        <Source id="recorridos" type="geojson" data={lines}>
          <Layer
            id="recorridos-halo"
            type="line"
            layout={{ "line-cap": "round", "line-join": "round" }}
            paint={{ "line-color": MARK_RING, "line-width": 6, "line-opacity": 0.9 }}
          />
          <Layer
            id="recorridos-linea"
            type="line"
            layout={{ "line-cap": "round", "line-join": "round" }}
            paint={{
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              "line-color": lineColor as any,
              "line-width": 3,
              "line-opacity": 0.9,
            }}
          />
        </Source>
      )}

      {cameras.length > 0 && (
        <Source id="camaras" type="geojson" data={points}>
          <Layer
            id={POINTS_LAYER}
            type="circle"
            paint={{
              "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 4, 14, 9],
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              "circle-color": fillColor as any,
              "circle-stroke-width": 2,
              "circle-stroke-color": MARK_RING,
              "circle-opacity": 0.95,
            }}
          />
          <Layer
            id="camaras-rotulo"
            type="symbol"
            minzoom={12}
            layout={{
              "text-field": ["get", "tag"],
              "text-font": ["Noto Sans Bold"],
              "text-size": 11,
              "text-offset": [0, -1.3],
              "text-allow-overlap": false,
            }}
            paint={{
              "text-color": "#0b0b0b",
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
              {hover.stop !== null && ` · parada ${hover.stop + 1}`}
            </div>
          </div>
        </Popup>
      )}
    </MapLibreMap>
  );
}
