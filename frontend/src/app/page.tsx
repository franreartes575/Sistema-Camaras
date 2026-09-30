"use client";

import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";

import ControlPanel from "@/components/ControlPanel";
import { loadDepots } from "@/components/DepotEditor";
import { IconList, IconMap, IconRoute } from "@/components/ui/icons";
import {
  exportPlan,
  optimize,
  previewClusters,
  uploadExcel,
  type ClusterParams,
  type ClusterStart,
  type ColumnMapping,
  type Depot,
  type ExportDay,
  type OptimizeResponse,
  type ProcessResponse,
  type RouteParams,
  type UploadExcelResponse,
} from "@/lib/api";
import { assignRouteDates, firstWorkingDay, routeKey, todayIso } from "@/lib/planDates";

// MapLibre toca `window`, asi que el mapa se carga solo en el cliente.
const MapView = dynamic(() => import("@/components/MapView"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-slate-500">
      Cargando mapa…
    </div>
  ),
});

const EMPTY_MAPPING: ColumnMapping = {
  col_id: "",
  mode: "split",
  col_lat: "",
  col_lon: "",
  col_coords: "",
  coord_order: "auto",
  col_label: "",
  col_node: "",
  col_obs: "",
  col_done: "",
};

type MobileView = "panel" | "map";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Error desconocido";
}

/** Dispara la descarga de un archivo generado en memoria. */
function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** El plan en el formato que espera /export/, con la fecha de cada día. */
function toExportDays(
  result: OptimizeResponse,
  routeDates: Record<string, string>,
): ExportDay[] {
  const cameras = new Map(result.cameras.map((camera) => [camera.id, camera]));
  return result.routes.map((route) => ({
    date: routeDates[routeKey(route)],
    cluster_id: route.cluster_id,
    day: route.vehicle_day,
    start_name: route.start_name,
    distance_m: route.total_distance_m,
    duration_s: route.total_duration_s,
    stops: route.stops.map((stop) => ({
      camera_id: stop.camera_id,
      lat: stop.lat,
      lon: stop.lon,
      node: cameras.get(stop.camera_id)?.node ?? null,
      observation: cameras.get(stop.camera_id)?.observation ?? null,
    })),
  }));
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<UploadExcelResponse | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping>(EMPTY_MAPPING);
  // 5 km agrupa una ciudad entera; con 1 km casi nada llega a formar grupo.
  const [params, setParams] = useState<ClusterParams>({
    eps_km: 5,
    min_samples: 2,
    noise_reassign_factor: 3,
  });
  const [routing, setRouting] = useState<RouteParams>({
    provider: "auto",
    day_budget_s: 8 * 3600,
    service_time_s: 15 * 60,
    average_speed_kmh: 35,
    time_limit_s: 5,
    max_stops_per_day: 5,
    min_stops_per_day: 0,
  });
  const [depots, setDepots] = useState<Depot[]>(loadDepots);
  const [preview, setPreview] = useState<ProcessResponse | null>(null);
  const [clusterStarts, setClusterStarts] = useState<Record<number, ClusterStart>>({});
  const [result, setResult] = useState<OptimizeResponse | null>(null);
  const [selectedCluster, setSelectedCluster] = useState<number | null>(null);
  // Jornada resaltada dentro del cluster seleccionado; null = todas.
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [planStart, setPlanStart] = useState(() => firstWorkingDay(todayIso(), true));
  const [skipWeekends, setSkipWeekends] = useState(true);
  // Fechas cargadas a mano por día; mandan sobre la secuencia sugerida.
  const [dateOverrides, setDateOverrides] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mobileView, setMobileView] = useState<MobileView>("panel");

  const routeDates = useMemo(
    () => assignRouteDates(result?.routes ?? [], { start: planStart, skipWeekends }, dateOverrides),
    [result, planStart, skipWeekends, dateOverrides],
  );

  const clearSelection = useCallback(() => {
    setSelectedCluster(null);
    setSelectedDay(null);
  }, []);

  const selectCluster = useCallback((cluster: number | null) => {
    setSelectedCluster(cluster);
    setSelectedDay(null);
  }, []);

  const selectRoute = useCallback((cluster: number | null, day: number | null) => {
    setSelectedCluster(cluster);
    setSelectedDay(day);
    // En el celular el mapa y el panel no entran juntos: al elegir un día,
    // mostrar el recorrido es lo que el usuario quiere ver.
    if (day !== null && window.matchMedia("(max-width: 767px)").matches) setMobileView("map");
  }, []);

  // Puntos de partida asignados, para dibujarlos en el mapa: una base mal
  // cargada se ve al instante en vez de manifestarse como "no entra nada".
  const starts = Object.entries(clusterStarts).map(([cluster, start]) => ({
    cluster: Number(cluster),
    ...start,
  }));

  // Los clusters de una vista previa vieja no necesariamente corresponden a
  // los de la nueva: forzar a reasignar puntos de partida en vez de arrastrar
  // asignaciones que podrían apuntar a un cluster distinto.
  const clearPreview = useCallback(() => {
    setPreview(null);
    setClusterStarts({});
    setResult(null);
  }, []);

  const handleFile = useCallback(
    async (picked: File) => {
      setIsLoading(true);
      setError(null);
      clearSelection();
      setFile(picked);
      clearPreview();

      try {
        const response = await uploadExcel(picked);
        setUpload(response);
        // Precarga el mapeo con lo que el backend logro inferir por nombre.
        const suggested = response.suggested_mapping;
        setMapping({
          col_id: suggested.id ?? response.columns[0] ?? "",
          mode: suggested.mode,
          col_lat: suggested.lat ?? "",
          col_lon: suggested.lon ?? "",
          col_coords: suggested.coords ?? "",
          coord_order: "auto",
          col_label: suggested.label ?? "",
          col_node: suggested.node ?? "",
          col_obs: suggested.observation ?? "",
          col_done: suggested.done ?? "",
        });
      } catch (err) {
        setUpload(null);
        setError(errorMessage(err));
      } finally {
        setIsLoading(false);
      }
    },
    [clearPreview, clearSelection],
  );

  const handleParamsChange = useCallback(
    (next: ClusterParams) => {
      setParams(next);
      clearPreview();
    },
    [clearPreview],
  );

  const handlePreview = useCallback(async () => {
    if (!file) return;
    setIsLoading(true);
    setError(null);
    clearSelection();
    try {
      setPreview(await previewClusters(file, mapping, params));
      setClusterStarts({});
      setResult(null);
    } catch (err) {
      setPreview(null);
      setError(errorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }, [file, mapping, params, clearSelection]);

  const handleOptimize = useCallback(async () => {
    if (!file) return;
    setIsLoading(true);
    setError(null);
    clearSelection();
    try {
      setResult(await optimize(file, mapping, params, routing, clusterStarts));
      setDateOverrides({});
    } catch (err) {
      setResult(null);
      setError(errorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }, [file, mapping, params, routing, clusterStarts, clearSelection]);

  const handleExport = useCallback(async () => {
    if (!result) return;
    const days = toExportDays(result, routeDates);
    const withoutDate = days.find((day) => !day.date);
    if (withoutDate) {
      setError(`Falta la fecha del día ${withoutDate.day}: elegila en la lista antes de exportar.`);
      return;
    }
    setIsExporting(true);
    setError(null);
    try {
      const { blob, filename } = await exportPlan(days);
      downloadBlob(blob, filename);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsExporting(false);
    }
  }, [result, routeDates]);

  const handleRouteDateChange = useCallback((key: string, iso: string) => {
    setDateOverrides((prev) => ({ ...prev, [key]: iso }));
  }, []);

  const handlePlanStartChange = useCallback((iso: string) => {
    // Una nueva fecha de inicio rearma la secuencia: los ajustes manuales
    // quedaban relativos al calendario anterior.
    setPlanStart(iso);
    setDateOverrides({});
  }, []);

  const viewTab = (view: MobileView) =>
    `inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition ${
      mobileView === view ? "bg-slate-700 text-white" : "text-slate-400"
    }`;

  return (
    <main className="flex h-dvh flex-col bg-slate-950 text-slate-100">
      <header className="flex items-center justify-between gap-3 border-b border-slate-800 bg-slate-950 px-4 py-2.5 md:px-5">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sky-500/15 text-sky-300 ring-1 ring-sky-400/30">
            <IconRoute className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold tracking-tight">Recorridos de cámaras</h1>
            <p className="truncate text-[11px] text-slate-500">Planificación de cuadrillas · Salta</p>
          </div>
        </div>
        <nav aria-label="Vista" className="flex gap-1 rounded-lg bg-slate-900 p-1 md:hidden">
          <button type="button" onClick={() => setMobileView("panel")} aria-pressed={mobileView === "panel"} className={viewTab("panel")}>
            <IconList className="h-3.5 w-3.5" /> Plan
          </button>
          <button type="button" onClick={() => setMobileView("map")} aria-pressed={mobileView === "map"} className={viewTab("map")}>
            <IconMap className="h-3.5 w-3.5" /> Mapa
          </button>
        </nav>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside
          className={`${mobileView === "panel" ? "block" : "hidden"} w-full overflow-y-auto border-slate-800 md:block md:w-[23rem] md:shrink-0 md:border-r lg:w-[25rem]`}
        >
          <div className="px-4 py-5 md:px-5">
            <ControlPanel
              upload={upload}
              mapping={mapping}
              params={params}
              routing={routing}
              depots={depots}
              preview={preview}
              clusterStarts={clusterStarts}
              result={result}
              isLoading={isLoading}
              error={error}
              selectedCluster={selectedCluster}
              selectedDay={selectedDay}
              routeDates={routeDates}
              planStart={planStart}
              skipWeekends={skipWeekends}
              isExporting={isExporting}
              onFile={handleFile}
              onMappingChange={setMapping}
              onParamsChange={handleParamsChange}
              onRoutingChange={setRouting}
              onDepotsChange={setDepots}
              onClusterStartsChange={setClusterStarts}
              onPreview={handlePreview}
              onOptimize={handleOptimize}
              onSelectRoute={selectRoute}
              onPlanStartChange={handlePlanStartChange}
              onSkipWeekendsChange={setSkipWeekends}
              onRouteDateChange={handleRouteDateChange}
              onExport={handleExport}
            />
          </div>
        </aside>

        <section
          aria-label="Mapa de recorridos"
          className={`${mobileView === "map" ? "block" : "hidden"} relative min-h-0 flex-1 md:block`}
        >
          <MapView
            cameras={result?.cameras ?? preview?.cameras ?? []}
            routes={result?.routes ?? []}
            clusters={result?.clusters ?? preview?.clusters ?? []}
            depots={depots}
            starts={starts}
            routeDates={routeDates}
            selectedCluster={selectedCluster}
            selectedDay={selectedDay}
            onSelectCluster={selectCluster}
          />
        </section>
      </div>
    </main>
  );
}
