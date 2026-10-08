"use client";

/**
 * Sección Registro: los recorridos guardados, su avance y la carga de los
 * seguimientos que completan los técnicos.
 *
 * El panel tiene la carga de seguimientos, los filtros y cuatro pestañas
 * (recorridos, tareas, planes, cargas); a la derecha, el resumen de avance y el
 * mapa con los recorridos marcados. Todo lo que se ve sale de la base: después
 * de cada cambio se incrementa `version` y las lecturas se repiten.
 */

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";

import DayPicker from "@/components/registro/DayPicker";
import { ImportDropzone, ImportHistory } from "@/components/registro/ImportPanel";
import PlanList from "@/components/registro/PlanList";
import PlanPicker from "@/components/registro/PlanPicker";
import RouteList, { STATE_FILTERS, type StateFilter } from "@/components/registro/RouteList";
import Summary from "@/components/registro/Summary";
import TaskList, { TASK_VIEWS, type TaskView } from "@/components/registro/TaskList";
import FiltersBar from "@/components/registro/FiltersBar";
import PanelResizer from "@/components/ui/PanelResizer";
import { RESIZABLE_PANEL, useResizablePanel } from "@/lib/usePanelWidth";
import { Notice } from "@/components/ui/controls";
import { IconDatabase } from "@/components/ui/icons";
import { downloadBlob } from "@/lib/download";
import { assignDayColors } from "@/lib/vizTokens";
import { todayIso } from "@/lib/planDates";
import {
  deletePlan,
  downloadBackup,
  downloadTasks,
  fetchRouteDetails,
  importFollowUp,
  registryPaths,
  routeState,
  updatePlan,
  updateRoute,
  updateTask,
  type FollowUpImport,
  type FollowUpResult,
  type PlanSummary,
  type RegistryFilters,
  type TaskChanges,
  type RouteDetail,
  type RouteSummary,
  type Task,
} from "@/lib/registro";
import { useJson } from "@/lib/useJson";

const RegistroMap = dynamic(() => import("@/components/registro/RegistroMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-slate-500">Cargando mapa…</div>
  ),
});

type Tab = "recorridos" | "tareas" | "planes" | "cargas";

const EMPTY_FILTERS: RegistryFilters = { desde: "", hasta: "", planId: null, q: "" };
const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Error desconocido";
}

/**
 * Qué se ve en el mapa antes de que el usuario marque días: con un plan elegido,
 * todos sus días; con "Todos los planes", nada (los días se marcan a mano).
 */
function defaultSelection(routes: RouteSummary[], planId: number | null): number[] {
  return planId !== null ? routes.map((route) => route.id) : [];
}

/** Del primer día al último; el mismo día, por plan, cluster y número de jornada. */
function sortRoutes(routes: RouteSummary[]): RouteSummary[] {
  return [...routes].sort(
    (a, b) => a.date.localeCompare(b.date) || a.plan_id - b.plan_id || a.cluster_id - b.cluster_id || a.day - b.day,
  );
}

function sortTasks(tasks: Task[]): Task[] {
  return [...tasks].sort(
    (a, b) =>
      a.date.localeCompare(b.date) ||
      a.plan_id - b.plan_id ||
      a.cluster_id - b.cluster_id ||
      a.day - b.day ||
      a.order - b.order,
  );
}

type Props = {
  /** Se incrementa desde afuera cuando el planificador guardó o sincronizó algo. */
  refreshKey: number;
  /** Corregir tareas a mano es sólo de administradores (el backend lo exige igual). */
  canEditTasks: boolean;
  mobileView: "panel" | "map";
  onShowMap: () => void;
  /** Lleva un Excel de tareas pendientes al planificador. */
  onPlanTasks: (file: File) => void;
};

export default function RegistroView({ refreshKey, canEditTasks, mobileView, onShowMap, onPlanTasks }: Props) {
  const [today] = useState(todayIso);
  const registroPanel = useResizablePanel("registro", 432);
  const [baseFilters, setBaseFilters] = useState<RegistryFilters>(EMPTY_FILTERS);
  // "none": todavía no eligió nada, no se muestra ningún plan. null: eligió "Todos los planes".
  const [planChoice, setPlanChoice] = useState<number | null | "none">("none");
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<Tab>("recorridos");
  const [stateFilter, setStateFilter] = useState<StateFilter>("todos");
  const [taskView, setTaskView] = useState<TaskView>("faltan");
  // null = selección automática (ver defaultSelection) hasta que el usuario elija.
  const [selection, setSelection] = useState<number[] | null>(null);
  const [focusedId, setFocusedId] = useState<number | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [localVersion, setLocalVersion] = useState(0);
  const [busyTaskId, setBusyTaskId] = useState<number | null>(null);
  const [busyRouteId, setBusyRouteId] = useState<number | null>(null);
  const [busyPlanId, setBusyPlanId] = useState<number | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<FollowUpResult | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isPlanning, setIsPlanning] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);

  // Las dos crecen siempre: la suma cambia ante cualquier novedad.
  const version = refreshKey + localVersion;
  const refresh = useCallback(() => setLocalVersion((value) => value + 1), []);

  // El buscador filtra con una pequeña demora para no consultar por cada tecla.
  useEffect(() => {
    const timer = setTimeout(
      () => setBaseFilters((prev) => (prev.q === search ? prev : { ...prev, q: search })),
      300,
    );
    return () => clearTimeout(timer);
  }, [search]);

  const plansQuery = useJson<PlanSummary[]>(registryPaths.plans, version);
  const plans = useMemo(() => plansQuery.data ?? [], [plansQuery.data]);
  // El usuario elige el plan: hasta entonces no se muestra ninguno. Si el elegido
  // se borra, vuelve a "sin elegir".
  const planId = typeof planChoice === "number" && plans.some((plan) => plan.id === planChoice) ? planChoice : null;
  const hasChoice = planChoice === null || planId !== null;
  const filters = useMemo<RegistryFilters>(() => ({ ...baseFilters, planId }), [baseFilters, planId]);

  /** Elige el plan visible: el mapa pasa a mostrar todos los días del nuevo. */
  const choosePlan = useCallback((choice: number | null | "none") => {
    setPlanChoice(choice);
    setSelection(null);
    setFocusedId(null);
    setExpandedId(null);
  }, []);

  const taskStatuses = TASK_VIEWS.find((view) => view.id === taskView)?.statuses ?? [];
  const routesQuery = useJson<RouteSummary[]>(hasChoice ? registryPaths.routes(filters) : null, version);
  const importsQuery = useJson<FollowUpImport[]>(tab === "cargas" ? registryPaths.imports : null, version);
  const tasksQuery = useJson<Task[]>(
    tab === "tareas" && hasChoice ? registryPaths.tasks(filters, taskStatuses) : null,
    version,
  );

  // useJson conserva lo último que leyó: sin plan elegido no se muestra nada de eso.
  const routes = useMemo(() => (hasChoice ? sortRoutes(routesQuery.data ?? []) : []), [hasChoice, routesQuery.data]);
  const tasks = useMemo(() => (hasChoice ? sortTasks(tasksQuery.data ?? []) : []), [hasChoice, tasksQuery.data]);
  // Un color por fecha entre todas las de la vista, no sólo las marcadas.
  const dayColors = useMemo(() => assignDayColors(routes.map((route) => route.date)), [routes]);

  const stateCounts = useMemo(() => {
    const counts = Object.fromEntries(STATE_FILTERS.map(({ id }) => [id, 0])) as Record<StateFilter, number>;
    counts.todos = routes.length;
    for (const route of routes) counts[routeState(route, today)] += 1;
    return counts;
  }, [routes, today]);
  const listedRoutes =
    stateFilter === "todos" ? routes : routes.filter((route) => routeState(route, today) === stateFilter);

  // Sólo cuenta lo que está dentro de los filtros: lo demás queda guardado en
  // la selección y reaparece si el filtro vuelve a incluirlo.
  const selected = useMemo(() => {
    const ids = new Set(routes.map((route) => route.id));
    return (selection ?? defaultSelection(routes, filters.planId)).filter((id) => ids.has(id));
  }, [selection, routes, filters.planId]);
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  // ------------------------------------------------------------ detalle para el mapa

  // Jornadas completas ya leídas. Si `version` avanzó (cambió algo en el
  // registro) se vuelven a pedir, pero mientras tanto se siguen mostrando las
  // anteriores: corregir una tarea no hace parpadear el mapa.
  const [detailState, setDetailState] = useState<{ version: number; routes: Record<number, RouteDetail> }>({
    version: 0,
    routes: {},
  });
  const details = detailState.routes;
  const isFresh = detailState.version === version;
  const [detailError, setDetailError] = useState<string | null>(null);
  const missingKey = selected.filter((id) => !isFresh || !details[id]).join(",");

  useEffect(() => {
    if (!missingKey) return;
    const ids = missingKey.split(",").map(Number);
    const controller = new AbortController();
    fetchRouteDetails(ids, controller.signal).then(
      (loaded) => {
        setDetailError(null);
        setDetailState((prev) => {
          // Con una versión nueva se descarta lo viejo (pudo haberse borrado).
          const next = { ...(prev.version === version ? prev.routes : {}) };
          for (const route of loaded) next[route.id] = route;
          return { version, routes: next };
        });
      },
      (err: unknown) => {
        if (!controller.signal.aborted) setDetailError(errorMessage(err));
      },
    );
    return () => controller.abort();
  }, [missingKey, version]);

  const mapRoutes = selected.map((id) => details[id]).filter((route): route is RouteDetail => Boolean(route));

  // ------------------------------------------------------------ selección

  const select = useCallback((ids: number[]) => setSelection([...new Set(ids)]), []);

  const toggleRoute = (id: number) => {
    if (selectedSet.has(id)) {
      select(selected.filter((other) => other !== id));
      if (focusedId === id) setFocusedId(null);
    } else {
      select([...selected, id]);
    }
  };

  /** Deja en el mapa exactamente estas jornadas. */
  const replaceSelection = (ids: number[]) => {
    select(ids);
    if (focusedId !== null && !ids.includes(focusedId)) {
      setFocusedId(null);
      setExpandedId(null);
    }
  };

  const setMany = (ids: number[], on: boolean) => {
    if (on) select([...selected, ...ids]);
    else {
      select(selected.filter((id) => !ids.includes(id)));
      if (focusedId !== null && ids.includes(focusedId)) setFocusedId(null);
    }
  };

  /** Enfoca una jornada (y la despliega); tocarla de nuevo la suelta. */
  const focusRoute = (id: number | null) => {
    if (id === null || id === focusedId) {
      setFocusedId(null);
      setExpandedId(null);
      return;
    }
    if (!selectedSet.has(id)) select([...selected, id]);
    setFocusedId(id);
    setExpandedId(id);
  };

  const selectDate = (date: string) => {
    select(routes.filter((route) => route.date === date).map((route) => route.id));
    setFocusedId(null);
    setExpandedId(null);
    onShowMap();
  };

  const showTaskRoute = (task: Task) => {
    if (!selectedSet.has(task.route_id)) select([...selected, task.route_id]);
    setFocusedId(task.route_id);
    setExpandedId(task.route_id);
    onShowMap();
  };

  // ------------------------------------------------------------ acciones

  /** Cambia la fecha planificada de un día entero; devuelve si se guardó. */
  const changeRouteDate = async (route: RouteSummary, date: string): Promise<boolean> => {
    setBusyRouteId(route.id);
    setActionError(null);
    try {
      await updateRoute(route.id, { date });
      refresh();
      return true;
    } catch (err) {
      setActionError(errorMessage(err));
      return false;
    } finally {
      setBusyRouteId(null);
    }
  };

  const changeTask = async (task: Task, changes: TaskChanges): Promise<boolean> => {
    setBusyTaskId(task.id);
    setActionError(null);
    try {
      await updateTask(task.id, changes);
      refresh();
      return true;
    } catch (err) {
      setActionError(errorMessage(err));
      return false;
    } finally {
      setBusyTaskId(null);
    }
  };

  const handleImport = async (file: File) => {
    setIsUploading(true);
    setUploadError(null);
    setUploadResult(null);
    try {
      setUploadResult(await importFollowUp(file));
      refresh();
    } catch (err) {
      setUploadError(errorMessage(err));
    } finally {
      setIsUploading(false);
    }
  };

  const renamePlan = async (planId: number, name: string) => {
    setBusyPlanId(planId);
    setActionError(null);
    try {
      await updatePlan(planId, { name });
      refresh();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusyPlanId(null);
    }
  };

  const removePlan = async (planId: number) => {
    setBusyPlanId(planId);
    setActionError(null);
    try {
      await deletePlan(planId);
      if (planChoice === planId) choosePlan("none");
      refresh();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusyPlanId(null);
    }
  };

  const planPending = async () => {
    setIsPlanning(true);
    setActionError(null);
    try {
      const { blob, filename } = await downloadTasks(filters, ["faltan"]);
      onPlanTasks(new File([blob], filename, { type: XLSX_MIME }));
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setIsPlanning(false);
    }
  };

  const downloadTaskList = async () => {
    setIsDownloading(true);
    setActionError(null);
    try {
      const { blob, filename } = await downloadTasks(filters, taskStatuses);
      downloadBlob(blob, filename);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setIsDownloading(false);
    }
  };

  /** Excel con todas las tareas del plan (o de todos), con lo informado hasta ahora. */
  const downloadUpdated = async (forPlanId: number | null) => {
    setIsDownloading(true);
    setActionError(null);
    try {
      const { blob, filename } = await downloadTasks(
        { desde: "", hasta: "", q: "", planId: forPlanId },
        [],
      );
      downloadBlob(blob, filename);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setIsDownloading(false);
    }
  };

  const downloadDatabase = async () => {
    setActionError(null);
    try {
      const { blob, filename } = await downloadBackup();
      downloadBlob(blob, filename);
    } catch (err) {
      setActionError(errorMessage(err));
    }
  };

  // ------------------------------------------------------------ vista

  const tabs: { id: Tab; label: string }[] = [
    { id: "recorridos", label: "Recorridos" },
    { id: "tareas", label: "Tareas" },
    { id: "planes", label: "Planes" },
    { id: "cargas", label: "Cargas" },
  ];

  const summary = (
    <Summary
      routes={routes}
      planCount={new Set(routes.map((route) => route.plan_id)).size}
      today={today}
      onSelectDate={selectDate}
    />
  );
  const loadError = routesQuery.error ?? plansQuery.error;

  return (
    <div className="flex min-h-0 flex-1">
      <aside
        style={registroPanel.panelStyle}
        className={`${mobileView === "panel" ? "block" : "hidden"} w-full overflow-y-auto border-slate-800 md:block md:border-r ${RESIZABLE_PANEL}`}
      >
        <div className="space-y-4 px-4 py-5 md:px-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold tracking-tight text-slate-50">Registro de recorridos</h2>
              <p className="text-xs text-slate-500">Lo planificado por día y lo que informaron los técnicos</p>
            </div>
            <button
              type="button"
              onClick={downloadDatabase}
              title="Descargar la base completa (.sqlite) como respaldo"
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-slate-800 px-2 py-1 text-xs text-slate-400 transition hover:border-slate-600 hover:text-slate-100"
            >
              <IconDatabase className="h-3.5 w-3.5" /> Respaldo
            </button>
          </div>

          {loadError && <Notice tone="error">{loadError}</Notice>}
          {actionError && <Notice tone="error">{actionError}</Notice>}

          <ImportDropzone
            isUploading={isUploading}
            result={uploadResult}
            error={uploadError}
            onFile={handleImport}
            onDismiss={() => setUploadResult(null)}
          />

          <PlanPicker
            plans={plans}
            planId={filters.planId}
            chosen={hasChoice}
            isDownloading={isDownloading}
            onChange={choosePlan}
            onDownload={() => downloadUpdated(filters.planId)}
          />

          <FiltersBar
            filters={filters}
            search={search}
            today={today}
            onChange={setBaseFilters}
            onSearchChange={setSearch}
          />

          <div className="md:hidden">{summary}</div>

          <div role="tablist" aria-label="Vistas del registro" className="grid grid-cols-4 gap-1 rounded-lg bg-slate-900 p-1">
            {tabs.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                className={`inline-flex items-center justify-center gap-1 rounded-md px-1 py-1.5 text-xs font-medium transition ${
                  tab === id ? "bg-slate-700 text-white shadow-sm" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div role="tabpanel">
            {(tab === "recorridos" || tab === "tareas") && !hasChoice && (
              <p className="rounded-lg border border-dashed border-slate-700 px-3 py-6 text-center text-sm leading-relaxed text-slate-400">
                Elegí un plan arriba para ver sus recorridos y tareas.
              </p>
            )}
            {tab === "recorridos" && hasChoice && (
              <div className="space-y-3">
              <DayPicker
                routes={routes}
                dayColors={dayColors}
                selected={selectedSet}
                today={today}
                onSetMany={setMany}
                onReplace={replaceSelection}
              />
              <RouteList
                routes={listedRoutes}
                today={today}
                stateFilter={stateFilter}
                stateCounts={stateCounts}
                selected={selectedSet}
                focusedId={focusedId}
                expandedId={expandedId}
                details={details}
                busyTaskId={busyTaskId}
                onStateFilterChange={setStateFilter}
                onToggle={toggleRoute}
                onSetMany={setMany}
                onFocus={focusRoute}
                onTaskUpdate={canEditTasks ? changeTask : undefined}
                onRouteDate={canEditTasks ? changeRouteDate : undefined}
                busyRouteId={busyRouteId}
              />
              </div>
            )}
            {tab === "tareas" && hasChoice && (
              <TaskList
                tasks={tasks}
                loading={tasksQuery.loading}
                view={taskView}
                busyTaskId={busyTaskId}
                isPlanning={isPlanning}
                isDownloading={isDownloading}
                onViewChange={setTaskView}
                onTaskUpdate={canEditTasks ? changeTask : undefined}
                onShowRoute={showTaskRoute}
                onPlan={planPending}
                onDownload={downloadTaskList}
              />
            )}
            {tab === "planes" && (
              <PlanList
                plans={plans}
                filteredPlanId={filters.planId}
                busyPlanId={busyPlanId}
                onFilter={(planId) => {
                  choosePlan(planId);
                  if (planId !== null) {
                    setTab("recorridos");
                    onShowMap();
                  }
                }}
                onRename={renamePlan}
                onDelete={removePlan}
                onDownload={downloadUpdated}
              />
            )}
            {tab === "cargas" && <ImportHistory imports={importsQuery.data ?? []} />}
          </div>
        </div>
      </aside>
      <PanelResizer label="el panel del Registro" {...registroPanel.resizer} />

      <section
        aria-label="Avance y mapa del registro"
        className={`${mobileView === "map" ? "flex" : "hidden"} min-h-0 min-w-0 flex-1 flex-col md:flex`}
      >
        <div className="hidden border-b border-slate-800 bg-slate-950 px-5 py-4 md:block">{summary}</div>
        {detailError && (
          <div className="border-b border-slate-800 px-4 py-2">
            <Notice tone="error">{detailError}</Notice>
          </div>
        )}
        <div className="relative min-h-0 flex-1">
          <RegistroMap
            routes={mapRoutes}
            dayColors={dayColors}
            focusedRouteId={focusedId}
            selectedCount={selected.length}
            onFocusRoute={focusRoute}
          />
        </div>
      </section>
    </div>
  );
}
