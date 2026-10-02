"use client";

import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";

import AuthGate, { useAuth } from "@/components/auth/AuthGate";
import ControlPanel, { type RegistroSync } from "@/components/ControlPanel";
import { loadDepots } from "@/components/DepotEditor";
import RegistroView from "@/components/registro/RegistroView";
import { IconCalendar, IconDatabase, IconList, IconLogout, IconMap, IconRoute } from "@/components/ui/icons";
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
import { downloadBlob } from "@/lib/download";
import { assignRouteDates, firstWorkingDay, routeKey, todayIso } from "@/lib/planDates";
import {
  importFollowUp,
  RegistryError,
  savePlan,
  type PlanSummary,
  type RegistryPlanIn,
} from "@/lib/registro";

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
type Section = "plan" | "registro";

/**
 * Último plan guardado en el registro: de qué planilla y resultado salió y con
 * qué fechas. Mientras se siga trabajando sobre la misma planilla (recalcular,
 * mover fechas), guardar reemplaza ese plan en vez de crear otro.
 */
type SavedPlan = { file: File | null; result: OptimizeResponse; datesKey: string; plan: PlanSummary };

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Error desconocido";
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

/** El plan como lo guarda el registro: jornadas con fecha, paradas y polilínea. */
function toRegistryPlan(
  result: OptimizeResponse,
  routeDates: Record<string, string>,
  sourceFile: string | null,
): RegistryPlanIn {
  const cameras = new Map(result.cameras.map((camera) => [camera.id, camera]));
  return {
    source_file: sourceFile,
    provider: result.provider,
    is_road_network: result.is_road_network,
    routes: result.routes.map((route) => ({
      date: routeDates[routeKey(route)],
      cluster_id: route.cluster_id,
      day: route.vehicle_day,
      start_name: route.start_name,
      start_lat: route.start_lat,
      start_lon: route.start_lon,
      distance_m: route.total_distance_m,
      duration_s: route.total_duration_s,
      has_unreachable_legs: route.has_unreachable_legs,
      geometry: route.geometry,
      stops: route.stops.map((stop) => ({
        camera_id: stop.camera_id,
        lat: stop.lat,
        lon: stop.lon,
        label: stop.label,
        node: cameras.get(stop.camera_id)?.node ?? null,
        observation: cameras.get(stop.camera_id)?.observation ?? null,
      })),
    })),
  };
}

/** Quién está conectado y el botón para salir. */
function UserMenu() {
  const { session, logout } = useAuth();
  const { nombre, rol } = session.usuario;
  return (
    <div className="flex items-center gap-2">
      <span className="hidden text-right leading-tight lg:block">
        <span className="block text-xs font-medium text-slate-200">{nombre}</span>
        <span className="block text-[10px] uppercase tracking-wide text-slate-500">{rol}</span>
      </span>
      <button
        type="button"
        onClick={logout}
        title="Cerrar sesión"
        aria-label="Cerrar sesión"
        className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 px-2.5 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-600 hover:text-white"
      >
        <IconLogout className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">Salir</span>
      </button>
    </div>
  );
}

/**
 * La página exige sesión: sin ella no se monta nada de la aplicación (ver
 * AuthGate). Todo el estado de la operación vive dentro de `Aplicacion` y se
 * descarta al cerrar la sesión.
 */
export default function Home() {
  return (
    <AuthGate>
      <Aplicacion />
    </AuthGate>
  );
}

function Aplicacion() {
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
  const [section, setSection] = useState<Section>("plan");
  // El registro se monta la primera vez que se abre y después queda montado
  // (oculto) para no perder sus filtros ni su selección al ir y volver.
  const [registroOpened, setRegistroOpened] = useState(false);
  // Se incrementa cuando el planificador cambia algo en el registro.
  const [registroVersion, setRegistroVersion] = useState(0);
  const [savedPlan, setSavedPlan] = useState<SavedPlan | null>(null);
  const [isSavingPlan, setIsSavingPlan] = useState(false);
  const [registroNotice, setRegistroNotice] = useState<{ tone: "warn" | "error"; text: string } | null>(null);
  const [registroSync, setRegistroSync] = useState<RegistroSync | null>(null);

  const routeDates = useMemo(
    () => assignRouteDates(result?.routes ?? [], { start: planStart, skipWeekends }, dateOverrides),
    [result, planStart, skipWeekends, dateOverrides],
  );

  const openSection = useCallback((next: Section) => {
    setSection(next);
    if (next === "registro") setRegistroOpened(true);
  }, []);

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
    async (picked: File, origin: "usuario" | "registro" = "usuario") => {
      setIsLoading(true);
      setError(null);
      clearSelection();
      setFile(picked);
      clearPreview();
      setRegistroSync(origin === "registro" ? { file: picked, kind: "from-registry" } : null);

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
        // Un Excel de seguimiento completado también actualiza el registro: lo
        // que informaron los técnicos queda guardado aunque no se replanifique.
        // Corre aparte, sin frenar el flujo del planificador.
        if (origin === "usuario" && suggested.done) {
          importFollowUp(picked).then(
            (result) => {
              setRegistroSync({ file: picked, kind: "synced", result });
              setRegistroVersion((version) => version + 1);
            },
            (err: unknown) => setRegistroSync({ file: picked, kind: "error", message: errorMessage(err) }),
          );
        }
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

  // Estado del plan actual en el registro: guardado tal cual, guardado con
  // otras fechas (hay que actualizarlo) o sin guardar.
  const datesKey = JSON.stringify(routeDates);
  const savedForPlan =
    savedPlan && result && (savedPlan.result === result || savedPlan.file === file) ? savedPlan : null;
  const registroStatus = !savedForPlan
    ? "unsaved"
    : savedForPlan.result === result && savedForPlan.datesKey === datesKey
      ? "saved"
      : "outdated";

  /** Fecha faltante en algún día, o null si todas están. */
  const missingDateError = useCallback(() => {
    if (!result) return null;
    const route = result.routes.find((candidate) => !routeDates[routeKey(candidate)]);
    return route
      ? `Falta la fecha del día ${route.vehicle_day}: elegila en la lista antes de exportar.`
      : null;
  }, [result, routeDates]);

  /**
   * Guarda el plan en el registro y devuelve su resumen. Si ya está guardado
   * tal cual no hace nada; si cambió (fechas o recálculo sobre la misma
   * planilla) reemplaza el guardado. Si ese ya tiene seguimiento cargado (409)
   * o lo borraron del registro (404), lo guarda como un plan nuevo.
   */
  const persistPlan = useCallback(async (): Promise<PlanSummary | null> => {
    if (!result) return null;
    if (registroStatus === "saved" && savedForPlan) return savedForPlan.plan;
    const payload = toRegistryPlan(result, routeDates, upload?.filename ?? null);
    let plan: PlanSummary;
    try {
      plan = await savePlan(payload, savedForPlan?.plan.id ?? null);
    } catch (err) {
      const replaceable = err instanceof RegistryError && (err.status === 404 || err.status === 409);
      if (!savedForPlan || !replaceable) throw err;
      plan = await savePlan(payload, null);
    }
    setSavedPlan({ file, result, datesKey, plan });
    setRegistroVersion((version) => version + 1);
    return plan;
  }, [result, routeDates, datesKey, registroStatus, savedForPlan, upload, file]);

  const handleSaveToRegistry = useCallback(async () => {
    const missing = missingDateError();
    if (missing) {
      setError(missing);
      return;
    }
    setIsSavingPlan(true);
    setRegistroNotice(null);
    try {
      await persistPlan();
    } catch (err) {
      setRegistroNotice({ tone: "error", text: `No se pudo guardar en el registro: ${errorMessage(err)}` });
    } finally {
      setIsSavingPlan(false);
    }
  }, [missingDateError, persistPlan]);

  const handleExport = useCallback(async () => {
    if (!result) return;
    const missing = missingDateError();
    if (missing) {
      setError(missing);
      return;
    }
    setIsExporting(true);
    setError(null);
    setRegistroNotice(null);
    // Exportar también guarda: el Excel lleva el id del plan y, cuando vuelva
    // completado, actualiza justo este plan. Si el registro falla, el Excel
    // sale igual — los técnicos no tienen por qué esperar.
    let planId: number | null = null;
    try {
      planId = (await persistPlan())?.id ?? null;
    } catch (err) {
      setRegistroNotice({
        tone: "warn",
        text: `El Excel se exportó, pero no se pudo guardar en el registro: ${errorMessage(err)}`,
      });
    }
    try {
      const { blob, filename } = await exportPlan(toExportDays(result, routeDates), planId);
      downloadBlob(blob, filename);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsExporting(false);
    }
  }, [result, routeDates, missingDateError, persistPlan]);

  /** Tareas pendientes del registro → paso 1 del planificador. */
  const handlePlanTasks = useCallback(
    (picked: File) => {
      setSection("plan");
      setMobileView("panel");
      void handleFile(picked, "registro");
    },
    [handleFile],
  );

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
      <header className="flex items-center justify-between gap-2 border-b border-slate-800 bg-slate-950 px-4 py-2.5 sm:gap-3 md:px-5">
        {/* En el celular no entra junto a las secciones, la vista y Salir. */}
        <div className="hidden min-w-0 items-center gap-2.5 sm:flex">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sky-500/15 text-sky-300 ring-1 ring-sky-400/30">
            <IconRoute className="h-4 w-4" />
          </span>
          <div className="hidden min-w-0 sm:block">
            <h1 className="truncate text-sm font-semibold tracking-tight">Recorridos de cámaras</h1>
            <p className="truncate text-[11px] text-slate-500">Planificación de cuadrillas · Salta</p>
          </div>
        </div>
        <nav aria-label="Sección" className="flex gap-1 rounded-lg bg-slate-900 p-1">
          {(
            [
              ["plan", "Planificar", IconCalendar],
              ["registro", "Registro", IconDatabase],
            ] as const
          ).map(([id, label, Icon]) => (
            <button
              key={id}
              type="button"
              onClick={() => openSection(id)}
              aria-current={section === id ? "page" : undefined}
              className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-semibold transition sm:px-3 ${
                section === id ? "bg-sky-500 text-slate-950 shadow-sm" : "text-slate-400 hover:text-slate-100"
              }`}
            >
              <Icon className="h-3.5 w-3.5" /> {label}
            </button>
          ))}
        </nav>
        <nav aria-label="Vista" className="flex gap-1 rounded-lg bg-slate-900 p-1 md:hidden">
          <button type="button" onClick={() => setMobileView("panel")} aria-pressed={mobileView === "panel"} className={viewTab("panel")}>
            <IconList className="h-3.5 w-3.5" /> <span className="sr-only sm:not-sr-only">Lista</span>
          </button>
          <button type="button" onClick={() => setMobileView("map")} aria-pressed={mobileView === "map"} className={viewTab("map")}>
            <IconMap className="h-3.5 w-3.5" /> <span className="sr-only sm:not-sr-only">Mapa</span>
          </button>
        </nav>
        <UserMenu />
      </header>

      <div className={`${section === "plan" ? "flex" : "hidden"} min-h-0 flex-1`}>
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
              registroStatus={registroStatus}
              savedPlanName={savedForPlan?.plan.name ?? null}
              isSavingPlan={isSavingPlan}
              registroNotice={registroNotice}
              registroSync={registroSync?.file === file ? registroSync : null}
              onSaveToRegistry={handleSaveToRegistry}
              onOpenRegistry={() => openSection("registro")}
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

      {registroOpened && (
        <div className={`${section === "registro" ? "flex" : "hidden"} min-h-0 flex-1`}>
          <RegistroView
            refreshKey={registroVersion}
            mobileView={mobileView}
            onShowMap={() => {
              if (window.matchMedia("(max-width: 767px)").matches) setMobileView("map");
            }}
            onPlanTasks={handlePlanTasks}
          />
        </div>
      )}
    </main>
  );
}
