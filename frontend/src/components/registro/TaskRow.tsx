"use client";

/** Una tarea del registro: su estado, lo informado y el acceso a editarla entera. */

import { useState } from "react";

import { StatusIcon, STATUS_LABEL } from "@/components/registro/StatusBadge";
import TaskEditor from "@/components/registro/TaskEditor";
import { IconEye, IconPencil } from "@/components/ui/icons";
import { formatDayLabel, formatShortDate, formatTimestamp } from "@/lib/format";
import type { ReportedStatus, Task, TaskChanges, TaskStatus } from "@/lib/registro";

const REPORTABLE: ReportedStatus[] = ["pendiente", "realizada", "no_realizada"];

/** Guarda los cambios; devuelve si se guardaron (para cerrar el editor). */
export type TaskUpdater = (changes: TaskChanges) => Promise<boolean>;

export function TaskStatusSelect({
  task,
  value,
  disabled,
  onChange,
}: {
  task: Task;
  value: TaskStatus;
  disabled: boolean;
  onChange: (status: ReportedStatus) => void;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      aria-label={`Estado de la cámara ${task.camera_id}`}
      onChange={(event) => onChange(event.target.value as ReportedStatus)}
      onClick={(event) => event.stopPropagation()}
      className="shrink-0 rounded-md border border-slate-700 bg-slate-950 px-1.5 py-1 text-xs text-slate-200 transition focus:border-sky-400 focus:outline-none disabled:opacity-50"
    >
      {/* Reprogramada se deriva: se muestra pero no se elige. */}
      {value === "reprogramada" && (
        <option value="reprogramada" disabled>
          {STATUS_LABEL.reprogramada}
        </option>
      )}
      {REPORTABLE.map((status) => (
        <option key={status} value={status}>
          {STATUS_LABEL[status]}
        </option>
      ))}
    </select>
  );
}

/**
 * Estado y edición de una tarea. El lápiz abre el editor con todos sus datos;
 * elegir «Realizada» en el selector también lo abre (con el estado ya puesto)
 * para cargar nodo y observación antes de guardar: en «Faltan» la tarea
 * desaparece de la lista apenas pasa a realizada. Sin `onUpdate` (quien no
 * es administrador) el estado se muestra sólo como texto.
 */
function useTaskEditing(task: Task, busy: boolean, onUpdate: TaskUpdater | undefined) {
  // null = cerrado; si no, el estado con el que abre el editor (o el actual).
  const [editing, setEditing] = useState<{ status?: ReportedStatus } | null>(null);

  if (!onUpdate) {
    const readOnly = <span className="shrink-0 py-1 text-xs text-slate-400">{STATUS_LABEL[task.status]}</span>;
    return { select: readOnly, editButton: null, editor: null };
  }

  const handleStatus = (status: ReportedStatus) => {
    if (status === "realizada") {
      setEditing({ status });
      return;
    }
    setEditing(null);
    void onUpdate({ status });
  };

  const select = (
    <TaskStatusSelect task={task} value={editing?.status ?? task.status} disabled={busy} onChange={handleStatus} />
  );
  const editButton = (
    <button
      type="button"
      onClick={() => setEditing({})}
      disabled={busy}
      aria-label={`Editar la tarea de la cámara ${task.camera_id}`}
      title="Editar tarea"
      className="rounded-md p-1 text-slate-400 transition hover:bg-slate-800 hover:text-slate-100 disabled:opacity-50"
    >
      <IconPencil className="h-3.5 w-3.5" />
    </button>
  );
  const editor = editing ? (
    <TaskEditor
      task={task}
      initialStatus={editing.status}
      busy={busy}
      onSave={onUpdate}
      onClose={() => setEditing(null)}
    />
  ) : null;
  return { select, editButton, editor };
}

/**
 * Cuándo pasó la cuadrilla (se haya hecho o no) y quién fue. El plan conserva
 * su fecha; si la ejecución fue otro día va «Fuera del plan», con rótulo y no
 * sólo en color: es lo que hay que poder encontrar.
 */
function ExecutionNote({ task }: { task: Task }) {
  if (!task.reported_date && !task.crew) return null;
  const crew = task.crew ? ` · ${task.crew}` : "";
  if (!task.reported_date) return <span className="block truncate">{task.crew}</span>;
  if (!task.off_plan) {
    return (
      <span className="block truncate">
        Ejecutada el {formatShortDate(task.reported_date)}
        {crew}
      </span>
    );
  }
  return (
    <span className="block truncate text-amber-300">
      <span className="font-semibold">Fuera del plan:</span> ejecutada el{" "}
      {formatShortDate(task.reported_date)}
      {crew} (planificada {formatShortDate(task.date)})
    </span>
  );
}

/** Detalle secundario: ejecución, pendientes, nodo, observación y última corrección, si los hay. */
function TaskNotes({ task }: { task: Task }) {
  const hasExecution = task.reported_date || task.crew;
  if (
    !hasExecution && !task.pending_actions && !task.node && !task.migrated_node &&
    !task.observation && !task.corrected_by
  ) {
    return null;
  }
  return (
    <span className="mt-0.5 block space-y-0.5 text-[11px] leading-snug text-slate-400">
      <ExecutionNote task={task} />
      {task.pending_actions && (
        <span className="block text-sky-200">
          <span className="font-semibold">Pendiente:</span> {task.pending_actions}
        </span>
      )}
      {(task.node || task.migrated_node) && (
        <span className="block truncate">
          Nodo {task.node ?? "—"}
          {task.migrated_node && <span className="text-slate-300"> → {task.migrated_node}</span>}
        </span>
      )}
      {task.observation && <span className="block italic text-slate-300">“{task.observation}”</span>}
      {task.corrected_by && (
        <span className="block truncate text-slate-500">
          Corregida por {task.corrected_by}
          {task.corrected_at && ` · ${formatTimestamp(task.corrected_at)}`}
        </span>
      )}
    </span>
  );
}

/** Parada dentro de un recorrido desplegado: orden de visita + estado. */
export function StopRow({ task, busy, onUpdate }: { task: Task; busy: boolean; onUpdate?: TaskUpdater }) {
  const { select, editButton, editor } = useTaskEditing(task, busy, onUpdate);
  return (
    <li className="py-1.5">
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 w-5 shrink-0 text-right font-mono text-[11px] text-slate-500">{task.order}</span>
        <StatusIcon status={task.status} className="mt-0.5 h-4 w-4" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-medium text-slate-100">{task.camera_id}</span>
          {task.label && <span className="block truncate text-[11px] text-slate-500">{task.label}</span>}
          <TaskNotes task={task} />
        </span>
        <span className="flex shrink-0 items-center gap-1">
          {editButton}
          {select}
        </span>
      </div>
      {editor && <div className="pl-[3.25rem]">{editor}</div>}
    </li>
  );
}

/** Tarea suelta en la pestaña Tareas: con su día, plan y acceso al mapa. */
export function TaskRow({
  task,
  busy,
  onUpdate,
  onShowRoute,
}: {
  task: Task;
  busy: boolean;
  onUpdate?: TaskUpdater;
  onShowRoute: () => void;
}) {
  const { select, editButton, editor } = useTaskEditing(task, busy, onUpdate);
  return (
    <li className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
      <div className="flex items-start gap-2.5">
        <StatusIcon status={task.status} className="mt-0.5 h-5 w-5" />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className="truncate text-sm font-medium text-slate-50">{task.camera_id}</span>
            <span className="shrink-0 text-[11px] capitalize text-slate-500">
              {formatDayLabel(task.date)} · día {task.day} · {task.order}°
            </span>
          </span>
          <span className="block truncate text-[11px] text-slate-500">
            {task.label ? `${task.label} · ` : ""}
            {task.plan_name}
          </span>
          <TaskNotes task={task} />
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1.5">
          <span className="flex items-center gap-1">
            {editButton}
            {select}
          </span>
          <button
            type="button"
            onClick={onShowRoute}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-slate-400 transition hover:bg-slate-800 hover:text-slate-100"
          >
            <IconEye className="h-3.5 w-3.5" /> Ver en mapa
          </button>
        </span>
      </div>
      {editor && <div className="pl-7">{editor}</div>}
    </li>
  );
}
