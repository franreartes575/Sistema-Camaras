"use client";

import dynamic from "next/dynamic";
import { useCallback, useState } from "react";

import ControlPanel from "@/components/ControlPanel";
import {
  optimize,
  previewClusters,
  uploadExcel,
  type ClusterParams,
  type ClusterStart,
  type ColumnMapping,
  type Depot,
  type OptimizeResponse,
  type ProcessResponse,
  type RouteParams,
  type UploadExcelResponse,
} from "@/lib/api";

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
};

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
  });
  const [depots, setDepots] = useState<Depot[]>([]);
  const [preview, setPreview] = useState<ProcessResponse | null>(null);
  const [clusterStarts, setClusterStarts] = useState<Record<number, ClusterStart>>({});
  const [result, setResult] = useState<OptimizeResponse | null>(null);
  const [selectedCluster, setSelectedCluster] = useState<number | null>(null);
  // Jornada resaltada dentro del cluster seleccionado; null = todas.
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  const selectCluster = useCallback((cluster: number | null) => {
    setSelectedCluster(cluster);
    setSelectedDay(null);
  }, []);

  const selectRoute = useCallback((cluster: number | null, day: number | null) => {
    setSelectedCluster(cluster);
    setSelectedDay(day);
  }, []);

  // Puntos de partida asignados, para dibujarlos en el mapa: una base mal
  // cargada se ve al instante en vez de manifestarse como "no entra nada".
  const starts = Object.entries(clusterStarts).map(([cluster, start]) => ({
    cluster: Number(cluster),
    ...start,
  }));
  const [error, setError] = useState<string | null>(null);

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
      setLoading(true);
      setError(null);
      setSelectedCluster(null);
      setSelectedDay(null);
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
        });
      } catch (err) {
        setUpload(null);
        setError(err instanceof Error ? err.message : "Error desconocido");
      } finally {
        setLoading(false);
      }
    },
    [clearPreview],
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

    setLoading(true);
    setError(null);
    setSelectedCluster(null);
    setSelectedDay(null);

    try {
      setPreview(await previewClusters(file, mapping, params));
      setClusterStarts({});
      setResult(null);
    } catch (err) {
      setPreview(null);
      setError(err instanceof Error ? err.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  }, [file, mapping, params]);

  const handleOptimize = useCallback(async () => {
    if (!file) return;

    setLoading(true);
    setError(null);
    setSelectedCluster(null);
    setSelectedDay(null);

    try {
      setResult(await optimize(file, mapping, params, routing, clusterStarts));
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  }, [file, mapping, params, routing, clusterStarts]);

  return (
    <main className="flex h-screen flex-col bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-3">
        <h1 className="text-base font-semibold">Sistema Logistico Free</h1>
        <p className="text-xs text-slate-500">
          Mantenimiento de camaras · OpenStreetMap + DBSCAN + OR-Tools
        </p>
      </header>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <aside className="w-full shrink-0 overflow-y-auto border-b border-slate-800 p-5 md:w-84 md:border-b-0 md:border-r">
          <ControlPanel
            upload={upload}
            mapping={mapping}
            params={params}
            routing={routing}
            depots={depots}
            preview={preview}
            clusterStarts={clusterStarts}
            result={result}
            loading={loading}
            error={error}
            selectedCluster={selectedCluster}
            selectedDay={selectedDay}
            onFile={handleFile}
            onMappingChange={setMapping}
            onParamsChange={handleParamsChange}
            onRoutingChange={setRouting}
            onDepotsChange={setDepots}
            onClusterStartsChange={setClusterStarts}
            onPreview={handlePreview}
            onOptimize={handleOptimize}
            onSelectRoute={selectRoute}
          />
        </aside>

        <section className="min-h-[400px] flex-1">
          <MapView
            cameras={result?.cameras ?? []}
            routes={result?.routes ?? []}
            clusters={result?.clusters ?? []}
            depots={depots}
            starts={starts}
            selectedCluster={selectedCluster}
            selectedDay={selectedDay}
            onSelectCluster={selectCluster}
          />
        </section>
      </div>
    </main>
  );
}
