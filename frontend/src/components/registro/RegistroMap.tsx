"use client";

/**
 * Mapa del registro: los recorridos elegidos en la lista, con cada parada
 * marcada según su estado.
 *
 * A diferencia del planificador, acá conviven jornadas de días y planes
 * distintos, así que el color de la línea no identifica el día (los cinco
 * colores de DAY_PALETTE no alcanzan y chocarían con el verde/rojo de los
 * estados). Todas las líneas van en un mismo azul con su rótulo de fecha; la
 * jornada enfocada pasa a naranja y las demás se atenúan.
 */

import type { LngLatBoundsLike, MapRef } from "react-map-gl/maplibre";
import { Layer, Map as MapLibreMap, NavigationControl, Popup, ScaleControl, Source } from "react-map-gl/maplibre";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";

import { StatusIcon, STATUS_LABEL } from "@/components/registro/StatusBadge";
import { formatDayLabel } from "@/lib/format";
import { OSM_STYLE } from "@/lib/mapStyle";
import type { RouteDetail, TaskStatus } from "@/lib/registro";
import { addStatusIcons, statusIconId, STATUSES } from "@/lib/statusIcons";
import { DEPOT_INK, MARK_RING, ROUTE_LINE, ROUTE_LINE_FOCUS } from "@/lib/vizTokens";

type Props = {
  routes: RouteDetail[];
  focusedRouteId: number | null;
  /** Cuántos recorridos hay marcados, aunque sus paradas sigan cargando. */
  selectedCount: number;
  onFocusRoute: (routeId: number | null) => void;
};

type HoverInfo = {
  lat: number;
  lon: number;
  camera: string;
  status: TaskStatus;
  caption: string;
  observation: string | null;
};

type LatLon = { lat: number; lon: number };

const STOPS_LAYER = "registro-paradas";
const LINES_LAYER = "registro-lineas";
const LABEL_INK = "#0b0b0b";
// Opacidad de lo que no está enfocado cuando hay una jornada enfocada.
const DIMMED = 0.3;

export default function RegistroMap({ routes, focusedRouteId, selectedCount, onFocusRoute }: Props) {
  const mapRef = useRef<MapRef | null>(null);
  const [iconsReady, setIconsReady] = useState(false);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const hasFocus = focusedRouteId !== null && routes.some((route) => route.id === focusedRouteId);

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
            route: route.id,
            focused: route.id === focusedRouteId,
            label: `${formatDayLabel(route.date)} · Día ${route.day}`,
          },
        })),
    }),
    [routes, focusedRouteId],
  );

  const stops = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: routes.flatMap((route) =>
        route.stops.map((task) => ({
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [task.lon, task.lat] },
          properties: {
            route: route.id,
            focused: route.id === focusedRouteId,
            icon: statusIconId(task.status),
            status: task.status,
            order: String(task.order),
            camera: task.camera_id,
            caption: `${formatDayLabel(route.date)} · Día ${route.day} · parada ${task.order}`,
            observation: task.observation ?? "",
          },
        })),
      ),
    }),
    [routes, focusedRouteId],
  );

  const starts = useMemo(() => {
    const unique = new Map<string, { lat: number; lon: number; name: string }>();
    for (const route of routes) {
      unique.set(`${route.start_lat},${route.start_lon}`, {
        lat: route.start_lat,
        lon: route.start_lon,
        name: route.start_name ?? "Salida",
      });
    }
    return {
      type: "FeatureCollection" as const,
      features: [...unique.values()].map((start) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [start.lon, start.lat] },
        properties: { name: start.name },
      })),
    };
  }, [routes]);

  // ------------------------------------------------------------ encuadre

  const lastBoundsRef = useRef<LngLatBoundsLike | null>(null);
  const lastFitKeyRef = useRef<string | null>(null);

  const fitTo = useCallback((points: LatLon[]) => {
    const map = mapRef.current;
    if (!map || points.length === 0) return false;
    const lats = points.map((point) => point.lat);
    const lons = points.map((point) => point.lon);
    const bounds: LngLatBoundsLike = [
      [Math.min(...lons), Math.min(...lats)],
      [Math.max(...lons), Math.max(...lats)],
    ];
    lastBoundsRef.current = bounds;
    map.fitBounds(bounds, { padding: 60, maxZoom: 16, duration: 600 });
    return true;
  }, []);

  const routeIdsKey = routes.map((route) => route.id).join(",");

  // Encuadra cuando cambia qué se ve (o qué está enfocado), no cada vez que se
  // relee el registro: corregir el estado de una tarea no mueve el mapa.
  useEffect(() => {
    const fitKey = `${routeIdsKey}|${hasFocus ? focusedRouteId : ""}`;
    if (!iconsReady || lastFitKeyRef.current === fitKey) return;
    const target = hasFocus ? routes.filter((route) => route.id === focusedRouteId) : routes;
    const points = target.flatMap((route) => [
      ...route.stops,
      { lat: route.start_lat, lon: route.start_lon },
    ]);
    if (fitTo(points)) lastFitKeyRef.current = fitKey;
  }, [routeIdsKey, focusedRouteId, hasFocus, routes, iconsReady, fitTo]);

  // ------------------------------------------------------------ interacción

  const handleClick = useCallback(
    (event: { features?: { properties?: Record<string, unknown> }[] }) => {
      const feature = event.features?.[0];
      if (!feature) {
        onFocusRoute(null);
        return;
      }
      const routeId = Number(feature.properties?.route);
      onFocusRoute(routeId === focusedRouteId ? null : routeId);
    },
    [onFocusRoute, focusedRouteId],
  );

  const handleHover = useCallback(
    (event: {
      features?: { layer?: { id?: string }; properties?: Record<string, unknown> }[];
      lngLat: { lat: number; lng: number };
    }) => {
      const feature = event.features?.find((candidate) => candidate.layer?.id === STOPS_LAYER);
      if (!feature) {
        setHover(null);
        return;
      }
      const properties = feature.properties ?? {};
      setHover({
        lat: event.lngLat.lat,
        lon: event.lngLat.lng,
        camera: String(properties.camera ?? ""),
        status: properties.status as TaskStatus,
        caption: String(properties.caption ?? ""),
        observation: properties.observation ? String(properties.observation) : null,
      });
    },
    [],
  );

  const dim = (focusedValue: number) =>
    hasFocus ? ["case", ["get", "focused"], focusedValue, DIMMED] : focusedValue;

  return (
    <MapLibreMap
      ref={mapRef}
      initialViewState={{ longitude: -65.4117, latitude: -24.7859, zoom: 10 }}
      style={{ width: "100%", height: "100%" }}
      mapStyle={OSM_STYLE}
      interactiveLayerIds={iconsReady ? [STOPS_LAYER, LINES_LAYER] : []}
      onLoad={(event) => {
        addStatusIcons(event.target);
        setIconsReady(true);
      }}
      onClick={handleClick}
      onMouseMove={handleHover}
      onMouseOut={() => setHover(null)}
      onResize={() => {
        // En el celular el mapa estuvo oculto (tamaño cero): reencuadrar.
        if (lastBoundsRef.current) {
          mapRef.current?.fitBounds(lastBoundsRef.current, { padding: 60, maxZoom: 16, duration: 0 });
        }
      }}
      cursor={hover ? "pointer" : "grab"}
    >
      <NavigationControl position="top-right" />
      <ScaleControl position="bottom-left" />

      <div className="pointer-events-none absolute left-2 top-2 z-10 flex max-w-[calc(100%-4rem)] flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-slate-950/85 px-2.5 py-1.5 text-[11px] text-slate-200 shadow-lg ring-1 ring-white/10 backdrop-blur">
        {STATUSES.map((status) => (
          <span key={status} className="flex items-center gap-1">
            <StatusIcon status={status} className="h-3.5 w-3.5" />
            {STATUS_LABEL[status]}
          </span>
        ))}
        <span className="flex items-center gap-1">
          <span className="h-1 w-4 rounded-full" style={{ backgroundColor: ROUTE_LINE }} />
          Recorrido
        </span>
        <span className="flex items-center gap-1">
          <span className="h-1 w-4 rounded-full" style={{ backgroundColor: ROUTE_LINE_FOCUS }} />
          Enfocado
        </span>
      </div>

      {selectedCount === 0 && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-6">
          <div className="max-w-xs rounded-xl bg-slate-950/90 px-4 py-3 text-center text-sm text-slate-300 shadow-xl ring-1 ring-white/10 backdrop-blur">
            Marcá uno o más recorridos en la lista (o tocá un día del gráfico) para
            verlos en el mapa.
          </div>
        </div>
      )}
      {selectedCount > routes.length && (
        <div className="pointer-events-none absolute bottom-8 left-1/2 z-10 -translate-x-1/2 rounded-full bg-slate-950/85 px-3 py-1 text-xs text-slate-200 ring-1 ring-white/10">
          Cargando recorridos…
        </div>
      )}

      <Source id="registro-recorridos" type="geojson" data={lines}>
        <Layer
          id="registro-lineas-halo"
          type="line"
          layout={{ "line-cap": "round", "line-join": "round" }}
          paint={{
            "line-color": MARK_RING,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            "line-width": ["case", ["get", "focused"], 9, 6] as any,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            "line-opacity": dim(0.9) as any,
          }}
        />
        <Layer
          id={LINES_LAYER}
          type="line"
          layout={{ "line-cap": "round", "line-join": "round", "line-sort-key": ["case", ["get", "focused"], 1, 0] }}
          paint={{
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            "line-color": ["case", ["get", "focused"], ROUTE_LINE_FOCUS, ROUTE_LINE] as any,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            "line-width": ["case", ["get", "focused"], 5, 3.5] as any,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            "line-opacity": dim(0.9) as any,
          }}
        />
        <Layer
          id="registro-lineas-rotulo"
          type="symbol"
          minzoom={11}
          layout={{
            "symbol-placement": "line",
            "symbol-spacing": 320,
            "text-field": ["get", "label"],
            "text-font": ["Noto Sans Bold"],
            "text-size": 11,
          }}
          paint={{
            "text-color": LABEL_INK,
            "text-halo-color": MARK_RING,
            "text-halo-width": 2,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            "text-opacity": dim(1) as any,
          }}
        />
      </Source>

      <Source id="registro-salidas" type="geojson" data={starts}>
        <Layer
          id="registro-salidas-punto"
          type="circle"
          paint={{
            "circle-radius": 8,
            "circle-color": MARK_RING,
            "circle-stroke-width": 4,
            "circle-stroke-color": DEPOT_INK,
          }}
        />
        <Layer
          id="registro-salidas-rotulo"
          type="symbol"
          minzoom={11}
          layout={{
            "text-field": ["get", "name"],
            "text-font": ["Noto Sans Bold"],
            "text-size": 11,
            "text-offset": [0, -1.4],
            "text-anchor": "bottom",
          }}
          paint={{ "text-color": DEPOT_INK, "text-halo-color": MARK_RING, "text-halo-width": 1.5 }}
        />
      </Source>

      {iconsReady && (
        <Source id="registro-tareas" type="geojson" data={stops}>
          <Layer
            id={STOPS_LAYER}
            type="symbol"
            layout={{
              "icon-image": ["get", "icon"],
              "icon-allow-overlap": true,
              "icon-ignore-placement": true,
              "icon-size": ["interpolate", ["linear"], ["zoom"], 8, 0.7, 14, 1],
              // Lo enfocado arriba de lo atenuado.
              "symbol-sort-key": ["case", ["get", "focused"], 1, 0],
            }}
            paint={{
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              "icon-opacity": dim(1) as any,
            }}
          />
          <Layer
            id="registro-paradas-orden"
            type="symbol"
            minzoom={13}
            layout={{
              "text-field": ["get", "order"],
              "text-font": ["Noto Sans Bold"],
              "text-size": 10,
              "text-anchor": "left",
              "text-offset": [0.9, -0.6],
            }}
            paint={{
              "text-color": LABEL_INK,
              "text-halo-color": MARK_RING,
              "text-halo-width": 1.5,
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              "text-opacity": dim(1) as any,
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
          <div className="space-y-0.5 text-xs leading-relaxed text-slate-900">
            <div className="font-semibold">{hover.camera}</div>
            <div className="font-medium">{STATUS_LABEL[hover.status]}</div>
            <div className="capitalize text-slate-600">{hover.caption}</div>
            {hover.observation && <div className="italic text-slate-600">“{hover.observation}”</div>}
          </div>
        </Popup>
      )}
    </MapLibreMap>
  );
}
