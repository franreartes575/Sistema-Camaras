"use client";

/**
 * Pestaña Tareas: cada cámara a visitar con su estado. Desde "Faltan" se arma
 * el próximo plan: lo pendiente se exporta en el formato del seguimiento y
 * entra directo al planificador.
 */

import { TaskRow } from "@/components/registro/TaskRow";
import { BUTTON } from "@/components/ui/controls";
import { IconDownload, IconRoute } from "@/components/ui/icons";
import type { StatusFilter, Task, TaskChanges } from "@/lib/registro";

export type TaskView =
  | "faltan"
  | "realizada"
  | "no_realizada"
  | "reprogramada"
  | "fuera_de_plan"
  | "todas";

export const TASK_VIEWS: { id: TaskView; label: string; statuses: StatusFilter[] }[] = [
  { id: "faltan", label: "Faltan", statuses: ["faltan"] },
  { id: "realizada", label: "Realizadas", statuses: ["realizada"] },
  { id: "no_realizada", label: "No realizadas", statuses: ["no_realizada"] },
  { id: "reprogramada", label: "Reprogramadas", statuses: ["reprogramada"] },
  // Trabajadas otro día que el planificado (p. ej. por otra cuadrilla).
  { id: "fuera_de_plan", label: "Fuera del plan", statuses: ["fuera_de_plan"] },
  { id: "todas", label: "Todas", statuses: [] },
];

// Más filas que esto no se leen en un panel; el Excel trae todas.
const MAX_RENDERED = 300;

export default function TaskList({
  tasks,
  loading,
  view,
  busyTaskId,
  isPlanning,
  isDownloading,
  onViewChange,
  onTaskUpdate,
  onShowRoute,
  onPlan,
  onDownload,
}: {
  tasks: Task[];
  loading: boolean;
  view: TaskView;
  busyTaskId: number | null;
  isPlanning: boolean;
  isDownloading: boolean;
  onViewChange: (view: TaskView) => void;
  /** Sin él (no es administrador), las tareas se ven en sólo lectura. */
  onTaskUpdate?: (task: Task, changes: TaskChanges) => Promise<boolean>;
  onShowRoute: (task: Task) => void;
  onPlan: () => void;
  onDownload: () => void;
}) {
  const shown = tasks.slice(0, MAX_RENDERED);
  return (
    <div className="space-y-3">
      <div role="radiogroup" aria-label="Estado de las tareas" className="flex flex-wrap gap-1.5">
        {TASK_VIEWS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={view === id}
            onClick={() => onViewChange(id)}
            className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${
              view === id ? "bg-slate-100 text-slate-900" : "bg-slate-800/70 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {view === "faltan" && tasks.length > 0 && (
        <div className="space-y-2 rounded-xl border border-sky-500/30 bg-sky-500/5 p-3">
          <p className="text-sm text-slate-200">
            <span className="font-semibold text-white">{tasks.length}</span> tarea(s) por hacer con
            estos filtros.
          </p>
          <button type="button" onClick={onPlan} disabled={isPlanning} className={BUTTON.primary}>
            <IconRoute className="h-4 w-4" />
            {isPlanning ? "Preparando…" : "Planificar los próximos recorridos"}
          </button>
          <p className="text-xs leading-relaxed text-slate-400">
            Las lleva al planificador con sus coordenadas, nodo y observación. Ahí
            elegís las salidas y las reglas del día como siempre.
          </p>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-slate-500">
        <span aria-live="polite">
          {loading ? "Cargando…" : `${tasks.length} tarea(s)`}
          {tasks.length > MAX_RENDERED && ` · se muestran ${MAX_RENDERED}`}
        </span>
        <button
          type="button"
          onClick={onDownload}
          disabled={isDownloading || tasks.length === 0}
          className={BUTTON.ghost}
        >
          <IconDownload className="h-3.5 w-3.5" />
          {isDownloading ? "Generando…" : "Descargar Excel"}
        </button>
      </div>

      {!loading && tasks.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-sm text-slate-500">
          {view === "faltan" ? "No falta nada con estos filtros." : "No hay tareas con estos filtros."}
        </p>
      )}

      <ul className="space-y-1.5">
        {shown.map((task) => (
          <TaskRow
            key={task.id}
            task={task}
            busy={busyTaskId === task.id}
            onUpdate={onTaskUpdate && ((changes) => onTaskUpdate(task, changes))}
            onShowRoute={() => onShowRoute(task)}
          />
        ))}
      </ul>
    </div>
  );
}
