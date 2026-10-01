"use client";

/** Una tarea del registro con su estado y la corrección manual del estado. */

import { StatusIcon, STATUS_LABEL } from "@/components/registro/StatusBadge";
import { IconEye } from "@/components/ui/icons";
import { formatDayLabel } from "@/lib/format";
import type { ReportedStatus, Task } from "@/lib/registro";

const REPORTABLE: ReportedStatus[] = ["pendiente", "realizada", "no_realizada"];

export function TaskStatusSelect({
  task,
  disabled,
  onChange,
}: {
  task: Task;
  disabled: boolean;
  onChange: (status: ReportedStatus) => void;
}) {
  return (
    <select
      value={task.status}
      disabled={disabled}
      aria-label={`Estado de la cámara ${task.camera_id}`}
      onChange={(event) => onChange(event.target.value as ReportedStatus)}
      onClick={(event) => event.stopPropagation()}
      className="shrink-0 rounded-md border border-slate-700 bg-slate-950 px-1.5 py-1 text-xs text-slate-200 transition focus:border-sky-400 focus:outline-none disabled:opacity-50"
    >
      {/* Reprogramada se deriva: se muestra pero no se elige. */}
      {task.status === "reprogramada" && (
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

/** Detalle secundario: nodo y observación, si los hay. */
function TaskNotes({ task }: { task: Task }) {
  if (!task.node && !task.migrated_node && !task.observation) return null;
  return (
    <span className="mt-0.5 block space-y-0.5 text-[11px] leading-snug text-slate-400">
      {(task.node || task.migrated_node) && (
        <span className="block truncate">
          Nodo {task.node ?? "—"}
          {task.migrated_node && <span className="text-slate-300"> → {task.migrated_node}</span>}
        </span>
      )}
      {task.observation && <span className="block italic text-slate-300">“{task.observation}”</span>}
    </span>
  );
}

/** Parada dentro de un recorrido desplegado: orden de visita + estado. */
export function StopRow({
  task,
  busy,
  onStatusChange,
}: {
  task: Task;
  busy: boolean;
  onStatusChange: (status: ReportedStatus) => void;
}) {
  return (
    <li className="flex items-start gap-2.5 py-1.5">
      <span className="mt-0.5 w-5 shrink-0 text-right font-mono text-[11px] text-slate-500">{task.order}</span>
      <StatusIcon status={task.status} className="mt-0.5 h-4 w-4" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-medium text-slate-100">{task.camera_id}</span>
        {task.label && <span className="block truncate text-[11px] text-slate-500">{task.label}</span>}
        <TaskNotes task={task} />
      </span>
      <TaskStatusSelect task={task} disabled={busy} onChange={onStatusChange} />
    </li>
  );
}

/** Tarea suelta en la pestaña Tareas: con su día, plan y acceso al mapa. */
export function TaskRow({
  task,
  busy,
  onStatusChange,
  onShowRoute,
}: {
  task: Task;
  busy: boolean;
  onStatusChange: (status: ReportedStatus) => void;
  onShowRoute: () => void;
}) {
  return (
    <li className="flex items-start gap-2.5 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
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
        <TaskStatusSelect task={task} disabled={busy} onChange={onStatusChange} />
        <button
          type="button"
          onClick={onShowRoute}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-slate-400 transition hover:bg-slate-800 hover:text-slate-100"
        >
          <IconEye className="h-3.5 w-3.5" /> Ver en mapa
        </button>
      </span>
    </li>
  );
}
