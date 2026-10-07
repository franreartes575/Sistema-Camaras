"use client";

/** Una tarea del registro con su estado y la corrección manual de estado, nodo migrado y observación. */

import { useState, type KeyboardEvent } from "react";

import { StatusIcon, STATUS_LABEL } from "@/components/registro/StatusBadge";
import { IconEye, IconPencil } from "@/components/ui/icons";
import { formatDayLabel } from "@/lib/format";
import type { ReportedStatus, Task, TaskChanges, TaskStatus } from "@/lib/registro";

const REPORTABLE: ReportedStatus[] = ["pendiente", "realizada", "no_realizada"];

/** Mismos topes que el backend (`TaskUpdate`). */
const OBSERVATION_MAX = 2000;
const NODE_MAX = 200;

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

const FIELD =
  "mt-1 block w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs font-normal text-slate-100 placeholder:text-slate-600 focus:border-sky-400 focus:outline-none";

/** Lo que se completa al dar una tarea por realizada. */
type DoneDetails = { observation: string; migratedNode: string };

function DoneEditor({
  task,
  busy,
  onSave,
  onCancel,
}: {
  task: Task;
  busy: boolean;
  onSave: (details: DoneDetails) => void;
  onCancel: () => void;
}) {
  const [observation, setObservation] = useState(task.observation ?? "");
  const [migratedNode, setMigratedNode] = useState(task.migrated_node ?? "");
  const cancelOnEscape = (event: KeyboardEvent) => {
    if (event.key === "Escape") onCancel();
  };
  return (
    <form
      className="mt-2 space-y-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({ observation, migratedNode });
      }}
    >
      <label className="block text-[11px] font-medium text-slate-300">
        Nodo al que se migró
        <input
          type="text"
          value={migratedNode}
          onChange={(event) => setMigratedNode(event.target.value)}
          onKeyDown={cancelOnEscape}
          maxLength={NODE_MAX}
          autoFocus
          placeholder={task.node ? `Preliminar: ${task.node}` : "Sin nodo"}
          className={FIELD}
        />
      </label>
      <label className="block text-[11px] font-medium text-slate-300">
        Observación
        <textarea
          value={observation}
          onChange={(event) => setObservation(event.target.value)}
          onKeyDown={cancelOnEscape}
          maxLength={OBSERVATION_MAX}
          rows={2}
          placeholder="Sin observación"
          className={`${FIELD} resize-y`}
        />
      </label>
      <span className="flex justify-end gap-1.5">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="rounded-md px-2 py-1 text-[11px] text-slate-400 transition hover:bg-slate-800 hover:text-slate-100 disabled:opacity-50"
        >
          Cancelar
        </button>
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-sky-500 px-2.5 py-1 text-[11px] font-semibold text-slate-950 transition hover:bg-sky-400 disabled:opacity-50"
        >
          {busy ? "Guardando…" : "Guardar"}
        </button>
      </span>
    </form>
  );
}

/**
 * Estado, nodo migrado y observación de una tarea. Elegir "Realizada" no
 * guarda enseguida: abre el nodo y la observación y se guarda todo junto (en "Faltan" la
 * tarea desaparece de la lista apenas pasa a realizada). Una tarea que ya
 * está realizada muestra un lápiz para volver a editarla. Sin `onUpdate`
 * (quien no es administrador) el estado se muestra sólo como texto.
 */
function useTaskEditing(task: Task, busy: boolean, onUpdate: TaskUpdater | undefined) {
  // Estado al que va a pasar la tarea mientras se edita la observación; null = sin editar.
  const [editing, setEditing] = useState<ReportedStatus | null>(null);

  if (!onUpdate) {
    const readOnly = <span className="shrink-0 py-1 text-xs text-slate-400">{STATUS_LABEL[task.status]}</span>;
    return { select: readOnly, editButton: null, editor: null };
  }

  const handleStatus = (status: ReportedStatus) => {
    if (status === "realizada") {
      setEditing(status);
      return;
    }
    setEditing(null);
    void onUpdate({ status });
  };

  const save = async ({ observation, migratedNode }: DoneDetails) => {
    if (!editing) return;
    const changes: TaskChanges = {
      observation: observation.trim() || null,
      migrated_node: migratedNode.trim() || null,
      ...(editing !== task.status && { status: editing }),
    };
    if (await onUpdate(changes)) setEditing(null);
  };

  const select = (
    <TaskStatusSelect task={task} value={editing ?? task.status} disabled={busy} onChange={handleStatus} />
  );
  const editButton =
    task.status === "realizada" && !editing ? (
      <button
        type="button"
        onClick={() => setEditing("realizada")}
        disabled={busy}
        aria-label={`Editar el nodo y la observación de la cámara ${task.camera_id}`}
        title="Editar nodo y observación"
        className="rounded-md p-1 text-slate-400 transition hover:bg-slate-800 hover:text-slate-100 disabled:opacity-50"
      >
        <IconPencil className="h-3.5 w-3.5" />
      </button>
    ) : null;
  const editor = editing ? (
    <DoneEditor task={task} busy={busy} onSave={save} onCancel={() => setEditing(null)} />
  ) : null;
  return { select, editButton, editor };
}

/** "AAAA-MM-DD HH:MM:SS" (hora local del servidor) → "DD/MM HH:MM". */
function shortStamp(stamp: string): string {
  const [date, time = ""] = stamp.split(" ");
  return `${date.slice(8, 10)}/${date.slice(5, 7)} ${time.slice(0, 5)}`.trim();
}

/** Detalle secundario: nodo, observación y última corrección manual, si los hay. */
function TaskNotes({ task }: { task: Task }) {
  if (!task.node && !task.migrated_node && !task.observation && !task.corrected_by) return null;
  return (
    <span className="mt-0.5 block space-y-0.5 text-[11px] leading-snug text-slate-400">
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
          {task.corrected_at && ` · ${shortStamp(task.corrected_at)}`}
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
