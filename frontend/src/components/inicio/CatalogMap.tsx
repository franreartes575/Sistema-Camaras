"use client";

/**
 * Mapa del catálogo: todas las cámaras, un color por cluster y las sedes.
 *
 * Los clusters son los del mismo DBSCAN del planificador, sobre el catálogo
 * entero (`/catalogo/clusters`). El color ayuda a separar vecinos; la
 * identidad la lleva el rótulo "C n" de cada cluster (ver CLUSTER_PALETTE).
 * Al enfocar una localidad se dibujan sólo sus cámaras.
 */

import type { LngLatBoundsLike, MapRef } from "react-map-gl/maplibre";
import { Layer, Map as MapLibreMap, NavigationControl, Popup, ScaleControl, Source } from "react-map-gl/maplibre";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";

import type { Depot } from "@/lib/api";
import type { CatalogCamera, CatalogClusters } from "@/lib/catalogo";
import { formatShortDate } from "@/lib/format";
import { circlePolygon } from "@/lib/geo";
import { OSM_STYLE } from "@/lib/mapStyle";
import {
  CLUSTER_COLOR_EXPRESSION,
  CLUSTER_PALETTE,
  DEPOT_INK,
  MARK_RING,
  NOISE_INK,
} from "@/lib/vizTokens";

type Props = {
  cameras: CatalogCamera[];
  clusters: CatalogClusters | null;
  depots: Depot[];
  focusedLocality: string | null;
  epsKm: number;
  /** Una sede, un cluster (true) o sólo por cercanía (false). */
  byDepot: boolean;
  depotMaxKm: number;
  isClustering: boolean;
  onEpsChange: (eps: number) => void;
  onByDepotChange: (byDepot: boolean) => void;
  onDepotMaxKmChange: (km: number) => void;
};

type HoverInfo = { lat: number; lon: number; camera: CatalogCamera; cluster: number };
type LatLon = { lat: number; lon: number };

const POINTS_LAYER = "catalogo-punto";
// Texto sobre el mapa: tinta de texto, nunca el color de la serie.
const LABEL_INK = "#0b0b0b";
// Filtro "todo": MapLibre rechaza la capa si `filter` no es un array.
const MATCH_ALL = ["has", "id"];
const EPS_OPTIONS = [2, 5, 10, 20, 30, 50];
const DEPOT_KM_OPTIONS = [30, 45, 60, 80, 100];
const SELECT_CLASS = "rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-[11px] text-slate-100";

export default function CatalogMap({
  cameras,
  clusters,
  depots,
  focusedLocality,
  epsKm,
  byDepot,
  depotMaxKm,
  isClustering,
  onEpsChange,
  onByDepotChange,
  onDepotMaxKmChange,
}: Props) {
  const mapRef = useRef<MapRef | null>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);

  const byId = useMemo(() => new Map(cameras.map((camera) => [camera.id, camera])), [cameras]);
  const clusterOf = useMemo(
    () => new Map((clusters?.cameras ?? []).map((item) => [item.id, item.cluster])),
    [clusters],
  );
  const colorOf = useMemo(
    () => new Map((clusters?.clusters ?? []).map((cluster) => [cluster.id, cluster.color])),
    [clusters],
  );

  const points = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: cameras.map((camera) => {
        const cluster = clusterOf.get(camera.id) ?? -1;
        return {
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [camera.lon, camera.lat] },
          properties: {
            id: camera.id,
            locality: camera.locality,
            cluster,
            color: cluster === -1 ? -1 : (colorOf.get(cluster) ?? -1),
          },
        };
      }),
    }),
    [cameras, clusterOf, colorOf],
  );

  // Con una localidad enfocada, los clusters que no tienen cámaras en ella no
  // se dibujan.
  const visibleClusters = useMemo(() => {
    const all = clusters?.clusters ?? [];
    if (!focusedLocality) return all;
    const present = new Set(
      cameras.filter((camera) => camera.locality === focusedLocality).map((camera) => clusterOf.get(camera.id)),
    );
    return all.filter((cluster) => present.has(cluster.id));
  }, [clusters, focusedLocality, cameras, clusterOf]);

  const boundaries = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: visibleClusters.map((cluster) => ({
        type: "Feature" as const,
        geometry: circlePolygon(cluster.centroid_lat, cluster.centroid_lon, cluster.radius_km),
        properties: { id: cluster.id, color: cluster.color, sede: Boolean(cluster.depot) },
      })),
    }),
    [visibleClusters],
  );

  const clusterById = useMemo(
    () => new Map((clusters?.clusters ?? []).map((cluster) => [cluster.id, cluster])),
    [clusters],
  );

  const labels = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: visibleClusters.map((cluster) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [cluster.centroid_lon, cluster.centroid_lat] },
        properties: { id: cluster.id, tag: `C${cluster.id}` },
      })),
    }),
    [visibleClusters],
  );

  const depotPoints = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: depots.map((depot) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [depot.lon, depot.lat] },
        properties: { name: depot.name },
      })),
    }),
    [depots],
  );

  // Último encuadre pedido. Si el mapa todavía no cargó (los datos suelen
  // llegar antes), queda pendiente y se aplica en `onLoad`.
  const lastFitRef = useRef<LatLon[] | null>(null);
  const fitTo = useCallback((subset: LatLon[], duration = 600) => {
    if (subset.length === 0) return;
    lastFitRef.current = subset;
    const map = mapRef.current;
    if (!map) return;
    const lats = subset.map((point) => point.lat);
    const lons = subset.map((point) => point.lon);
    const bounds: LngLatBoundsLike = [
      [Math.min(...lons), Math.min(...lats)],
      [Math.max(...lons), Math.max(...lats)],
    ];
    map.fitBounds(bounds, { padding: 60, maxZoom: 15, duration });
  }, []);

  // Encuadre: la localidad enfocada, o las cámaras agrupadas (una suelta a
  // cientos de km obligaría a alejar tanto que los clusters serían un punto).
  const fitKey = `${cameras.length}|${focusedLocality ?? ""}|${clusters ? "c" : ""}`;
  const fitKeyRef = useRef("");
  useEffect(() => {
    if (fitKeyRef.current === fitKey) return;
    fitKeyRef.current = fitKey;
    if (focusedLocality) {
      fitTo(cameras.filter((camera) => camera.locality === focusedLocality));
      return;
    }
    const grouped = cameras.filter((camera) => (clusterOf.get(camera.id) ?? -1) !== -1);
    fitTo(grouped.length > 0 ? grouped : cameras);
  }, [fitKey, focusedLocality, cameras, clusterOf, fitTo]);

  const filter = useMemo(
    () => (focusedLocality ? ["==", ["get", "locality"], focusedLocality] : MATCH_ALL),
    [focusedLocality],
  );

  const handleHover = useCallback(
    (event: { features?: { properties?: Record<string, unknown> }[]; lngLat: { lat: number; lng: number } }) => {
      const properties = event.features?.[0]?.properties;
      const camera = properties ? byId.get(String(properties.id)) : undefined;
      if (!camera) {
        setHover(null);
        return;
      }
      setHover({ lat: camera.lat, lon: camera.lon, camera, cluster: Number(properties?.cluster) });
    },
    [byId],
  );

  return (
    <MapLibreMap
      ref={mapRef}
      initialViewState={{ longitude: -65.4117, latitude: -24.7859, zoom: 7 }}
      style={{ width: "100%", height: "100%" }}
      mapStyle={OSM_STYLE}
      interactiveLayerIds={cameras.length > 0 ? [POINTS_LAYER] : []}
      onMouseMove={handleHover}
      onMouseOut={() => setHover(null)}
      onLoad={() => {
        if (lastFitRef.current) fitTo(lastFitRef.current, 0);
      }}
      onResize={() => {
        if (lastFitRef.current) fitTo(lastFitRef.current, 0);
      }}
      cursor={hover ? "pointer" : "grab"}
    >
      <NavigationControl position="top-right" />
      <ScaleControl position="bottom-left" />

      <div className="absolute left-2 top-2 z-10 max-w-[calc(100%-4rem)] space-y-1.5 rounded-lg bg-slate-950/85 px-2.5 py-2 text-[11px] text-slate-200 shadow-lg ring-1 ring-white/10 backdrop-blur">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="flex items-center gap-1">
            <span className="flex">
              {CLUSTER_PALETTE.map((color) => (
                <span key={color} className="h-2.5 w-2 first:rounded-l-full last:rounded-r-full" style={{ backgroundColor: color }} />
              ))}
            </span>
            Cluster (rótulo C n)
          </span>
          {byDepot && (
            <span className="flex items-center gap-1">
              <span className="w-3 border-t-2 border-dashed border-slate-300" />
              Sin sede
            </span>
          )}
          <span className="flex items-center gap-1">
            <span className="h-2.5 w-2.5 rounded-full ring-1 ring-white" style={{ backgroundColor: NOISE_INK }} />
            Suelta
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2.5 w-2.5 rounded-sm bg-white ring-2" style={{ ["--tw-ring-color" as string]: DEPOT_INK }} />
            Sede
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-slate-400">
          <label className="flex items-center gap-1.5">
            Agrupar
            <select
              value={byDepot ? "sede" : "cercania"}
              onChange={(event) => onByDepotChange(event.target.value === "sede")}
              className={SELECT_CLASS}
            >
              <option value="sede">por sede</option>
              <option value="cercania">por cercanía</option>
            </select>
          </label>
          {byDepot && (
            <label className="flex items-center gap-1.5">
              hasta
              <select
                value={depotMaxKm}
                onChange={(event) => onDepotMaxKmChange(Number(event.target.value))}
                aria-label="Zona de cada sede"
                className={SELECT_CLASS}
              >
                {DEPOT_KM_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {value} km
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="flex items-center gap-1.5">
            {byDepot ? "· sin sede, a" : "a"}
            <select
              value={epsKm}
              onChange={(event) => onEpsChange(Number(event.target.value))}
              aria-label="Radio de agrupamiento"
              className={SELECT_CLASS}
            >
              {EPS_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value} km
                </option>
              ))}
            </select>
          </label>
          {clusters && (
            <span className="text-slate-300">
              · {clusters.clusters.length} cluster{clusters.clusters.length === 1 ? "" : "s"}
              {clusters.noise_count ? ` · ${clusters.noise_count} suelta${clusters.noise_count === 1 ? "" : "s"}` : ""}
            </span>
          )}
          {isClustering && <span className="text-slate-500">· calculando…</span>}
        </div>
      </div>

      {boundaries.features.length > 0 && (
        <Source id="catalogo-limites" type="geojson" data={boundaries}>
          <Layer
            id="catalogo-limites-relleno"
            type="fill"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            paint={{ "fill-color": CLUSTER_COLOR_EXPRESSION as any, "fill-opacity": 0.1 }}
          />
          {/* La zona de una sede va con borde lleno; lo agrupado sin sede, punteado.
              `line-dasharray` no admite expresiones por dato: son dos capas. */}
          <Layer
            id="catalogo-limites-borde"
            type="line"
            filter={["==", ["get", "sede"], true]}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            paint={{ "line-color": CLUSTER_COLOR_EXPRESSION as any, "line-width": 2, "line-opacity": 0.7 }}
          />
          <Layer
            id="catalogo-limites-borde-sin-sede"
            type="line"
            filter={["==", ["get", "sede"], false]}
            paint={{
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              "line-color": CLUSTER_COLOR_EXPRESSION as any,
              "line-width": 1.5,
              "line-opacity": 0.7,
              "line-dasharray": [2, 2],
            }}
          />
        </Source>
      )}

      {/* Las sedes van debajo de las cámaras y los rótulos: suelen estar en
          medio de un cluster y lo taparían. Su nombre va arriba de todo. */}
      {depots.length > 0 && (
        <Source id="catalogo-sedes" type="geojson" data={depotPoints}>
          <Layer
            id="catalogo-sedes-punto"
            type="circle"
            paint={{
              // Centro blanco con anillo verde: "acá sale una cuadrilla", el
              // mismo signo que las salidas del planificador.
              "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 6, 12, 10],
              "circle-color": MARK_RING,
              "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 6, 3, 12, 4],
              "circle-stroke-color": DEPOT_INK,
            }}
          />
        </Source>
      )}

      {cameras.length > 0 && (
        <Source id="catalogo-camaras" type="geojson" data={points}>
          <Layer
            id={POINTS_LAYER}
            type="circle"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            filter={filter as any}
            paint={{
              "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 3, 10, 5, 14, 8],
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              "circle-color": CLUSTER_COLOR_EXPRESSION as any,
              "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 6, 1, 12, 2],
              "circle-stroke-color": MARK_RING,
              "circle-opacity": 0.95,
            }}
          />
        </Source>
      )}

      {labels.features.length > 0 && (
        <Source id="catalogo-rotulos" type="geojson" data={labels}>
          <Layer
            id="catalogo-rotulo"
            type="symbol"
            layout={{
              "text-field": ["get", "tag"],
              "text-font": ["Noto Sans Bold"],
              "text-size": 12,
              // Siempre visibles (son pocos) y al costado del centro, donde no
              // los tapa el punto de una cámara ni el de una sede.
              "text-allow-overlap": true,
              "text-offset": [1.2, 0],
              "text-anchor": "left",
            }}
            paint={{ "text-color": LABEL_INK, "text-halo-color": MARK_RING, "text-halo-width": 2 }}
          />
        </Source>
      )}

      {depots.length > 0 && (
        <Source id="catalogo-sedes-nombres" type="geojson" data={depotPoints}>
          <Layer
            id="catalogo-sedes-rotulo"
            type="symbol"
            layout={{
              "text-field": ["get", "name"],
              "text-font": ["Noto Sans Bold"],
              "text-size": 12,
              "text-offset": [0, -1.4],
              "text-anchor": "bottom",
              "text-allow-overlap": true,
            }}
            paint={{ "text-color": LABEL_INK, "text-halo-color": MARK_RING, "text-halo-width": 2 }}
          />
        </Source>
      )}

      {cameras.length === 0 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <p className="rounded-lg bg-slate-950/85 px-3 py-2 text-sm text-slate-300 ring-1 ring-white/10">
            Todavía no hay cámaras en el catálogo.
          </p>
        </div>
      )}

      {hover && (
        <Popup
          longitude={hover.lon}
          latitude={hover.lat}
          closeButton={false}
          closeOnClick={false}
          offset={12}
          maxWidth="260px"
        >
          <div className="space-y-0.5 text-xs text-slate-800">
            <div className="font-mono font-semibold text-slate-950">{hover.camera.id}</div>
            {hover.camera.label && <div>{hover.camera.label}</div>}
            <div>
              {hover.camera.locality} · {hover.cluster === -1
                ? "suelta"
                : `cluster C${hover.cluster}${
                    clusterById.get(hover.cluster)?.depot
                      ? ` (zona ${clusterById.get(hover.cluster)?.depot?.name})`
                      : byDepot
                        ? " (sin sede)"
                        : ""
                  }`}
            </div>
            <div className="text-slate-600">
              {hover.camera.last_visit
                ? `Última visita: ${formatShortDate(hover.camera.last_visit)}`
                : "Sin visitas registradas"}
              {hover.camera.last_status === "pendiente" || hover.camera.last_status === "no_realizada"
                ? " · tiene una tarea pendiente"
                : ""}
            </div>
          </div>
        </Popup>
      )}
    </MapLibreMap>
  );
}
