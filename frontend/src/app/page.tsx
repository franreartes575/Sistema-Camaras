"use client";

import dynamic from "next/dynamic";
import { useCallback, useState } from "react";

import ControlPanel from "@/components/ControlPanel";
import {
  optimize,
  uploadExcel,
  type ClusterParams,
  type ColumnMapping,
  type OptimizeResponse,
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
  const [params, setParams] = useState<ClusterParams>({ eps_km: 1, min_samples: 2 });
  const [routing, setRouting] = useState<RouteParams>({
    provider: "auto",
    round_trip: false,
    time_limit_s: 5,
  });
  const [result, setResult] = useState<OptimizeResponse | null>(null);
  const [selectedCluster, setSelectedCluster] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFile = useCallback(async (picked: File) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setSelectedCluster(null);
    setFile(picked);

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
  }, []);

  const handleOptimize = useCallback(async () => {
    if (!file) return;

    setLoading(true);
    setError(null);
    setSelectedCluster(null);

    try {
      setResult(await optimize(file, mapping, params, routing));
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  }, [file, mapping, params, routing]);

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
            result={result}
            loading={loading}
            error={error}
            selectedCluster={selectedCluster}
            onFile={handleFile}
            onMappingChange={setMapping}
            onParamsChange={setParams}
            onRoutingChange={setRouting}
            onOptimize={handleOptimize}
            onSelectCluster={setSelectedCluster}
          />
        </aside>

        <section className="min-h-[400px] flex-1">
          <MapView
            cameras={result?.cameras ?? []}
            routes={result?.routes ?? []}
            selectedCluster={selectedCluster}
            onSelectCluster={setSelectedCluster}
          />
        </section>
      </div>
    </main>
  );
}
