"use client";

/**
 * Ventana para editar todos los datos de una tarea del registro.
 *
 * Usa el <dialog> nativo en modo modal: trae el foco atrapado, Esc para
 * cerrar y el fondo oscurecido sin código extra. Guarda sólo lo que cambió
 * (cada campo cambiado queda en el historial de correcciones con su autor).
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

import { STATUS_LABEL } from "@/components/registro/StatusBadge";
import { formatDayLabel } from "@/lib/format";
import {
  registryPaths,
  type ReportedStatus,
  type RouteSummary,
  type Task,
  type TaskChanges,
} from "@/lib/registro";
import { useJson } from "@/lib/useJson";

const REPORTABLE: ReportedStatus[] = ["pendiente", "realizada", "no_realizada"];

/** Mismos topes que el backend (`TaskUpdate`). */
const MAX = { id: 200, label: 500, node: 200, observation: 2000, crew: 100, truck: 100, pending: 1000 };

const FIELD =
  "mt-1 block w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm font-normal text-slate-100 placeholder:text-slate-600 focus:border-sky-400 focus:outline-none";

/** Lo que muestra el formulario: todo como texto, tal como se escribe. */
type Draft = {
  camera_id: string;
  label: string;
  node: string;
  lat: string;
  lon: string;
  route_id: string;
  status: string;
  reported_date: string;
  crew: string;
  truck: string;
  migrated_node: string;
  observation: string;
  pending: string;
  pendingAuto: boolean;
};

function draftOf(task: Task, status: ReportedStatus | undefined): Draft {
  return {
    camera_id: task.camera_id,
    label: task.label ?? "",
    node: task.node ?? "",
    lat: String(task.lat),
    lon: String(task.lon),
    route_id: String(task.route_id),
    status: status ?? task.status,
    reported_date: task.reported_date ?? "",
    crew: task.crew ?? "",
    truck: task.truck ?? "",
    migrated_node: task.migrated_node ?? "",
    observation: task.observation ?? "",
    pending: task.pending_manual ? (task.pending_actions ?? "") : "",
    pendingAuto: !task.pending_manual,
  };
}

const text = (value: string) => value.trim() || null;

/** Sólo lo que difiere de la tarea: lo demás no se manda (ni se registra). */
function changesOf(task: Task, draft: Draft): TaskChanges | string {
  const changes: TaskChanges = {};
  const lat = Number(draft.lat.replace(",", "."));
  const lon = Number(draft.lon.replace(",", "."));
  if (!draft.camera_id.trim()) return "El ID de la cámara no puede quedar vacío.";
  if (!Number.isFinite(lat) || lat < -90 || lat > 90) return "La latitud tiene que estar entre -90 y 90.";
  if (!Number.isFinite(lon) || lon < -180 || lon > 180) return "La longitud tiene que estar entre -180 y 180.";

  if (draft.camera_id.trim() !== task.camera_id) changes.camera_id = draft.camera_id.trim();
  if (text(draft.label) !== task.label) changes.label = text(draft.label);
  if (text(draft.node) !== task.node) changes.node = text(draft.node);
  if (lat !== task.lat) changes.lat = lat;
  if (lon !== task.lon) changes.lon = lon;
  if (Number(draft.route_id) !== task.route_id) changes.route_id = Number(draft.route_id);
  if (draft.status !== task.status && draft.status !== "reprogramada") {
    changes.status = draft.status as ReportedStatus;
  }
  if ((draft.reported_date || null) !== task.reported_date) changes.reported_date = draft.reported_date || null;
  if (text(draft.crew) !== task.crew) changes.crew = text(draft.crew);
  if (text(draft.truck) !== task.truck) changes.truck = text(draft.truck);
  if (text(draft.migrated_node) !== task.migrated_node) changes.migrated_node = text(draft.migrated_node);
  if (text(draft.observation) !== task.observation) changes.observation = text(draft.observation);
  const pending = draft.pendingAuto ? null : text(draft.pending);
  if (pending !== (task.pending_manual ? task.pending_actions : null)) changes.pending_actions = pending;
  return changes;
}

function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`block text-xs font-medium text-slate-300 ${wide ? "sm:col-span-2" : ""}`}>
      {label}
      {children}
    </label>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3 rounded-lg border border-slate-800 p-3">
      <legend className="px-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{title}</legend>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </fieldset>
  );
}

function routeLabel(route: RouteSummary): string {
  const start = route.start_name ? ` · ${route.start_name}` : "";
  return `${formatDayLabel(route.date)} · día ${route.day}${start}`;
}

export default function TaskEditor({
  task,
  initialStatus,
  busy,
  onSave,
  onClose,
}: {
  task: Task;
  /** Estado con el que abre (p. ej. al elegir «Realizada» en el selector). */
  initialStatus?: ReportedStatus;
  busy: boolean;
  onSave: (changes: TaskChanges) => Promise<boolean>;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState<Draft>(() => draftOf(task, initialStatus));
  const [error, setError] = useState<string | null>(null);
  const routes = useJson<RouteSummary[]>(
    registryPaths.routes({ desde: "", hasta: "", q: "", planId: task.plan_id }),
    0,
  );

  // Sin limpieza a propósito: cerrarlo al desmontar dispara «close» → onClose,
  // y en desarrollo React monta, desmonta y vuelve a montar cada componente:
  // la ventana se cerraba sola apenas se abría. Al quitar el componente, el
  // navegador saca el <dialog> de la capa superior solo.
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
  }, []);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const submit = async () => {
    const changes = changesOf(task, draft);
    if (typeof changes === "string") {
      setError(changes);
      return;
    }
    if (Object.keys(changes).length === 0) {
      onClose();
      return;
    }
    setError(null);
    if (await onSave(changes)) onClose();
  };

  const planRoutes = routes.data ?? [];
  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      aria-labelledby={`editar-${task.id}`}
      className="m-auto w-[min(44rem,calc(100vw-2rem))] rounded-xl border border-slate-700 bg-slate-900 p-0 text-slate-100 shadow-2xl backdrop:bg-slate-950/70"
    >
      <form
        method="dialog"
        className="flex max-h-[85dvh] flex-col"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <header className="border-b border-slate-800 px-4 py-3">
          <h2 id={`editar-${task.id}`} className="text-base font-semibold">
            Editar tarea · {task.camera_id}
          </h2>
          <p className="text-xs text-slate-400">
            {task.plan_name} · planificada {formatDayLabel(task.date)}, día {task.day}
          </p>
        </header>

        <div className="space-y-3 overflow-y-auto px-4 py-3">
          <Section title="Cámara">
            <Field label="ID de la cámara">
              <input className={FIELD} value={draft.camera_id} maxLength={MAX.id} required
                onChange={(event) => set("camera_id", event.target.value)} />
            </Field>
            <Field label="Nodo preliminar">
              <input className={FIELD} value={draft.node} maxLength={MAX.node}
                onChange={(event) => set("node", event.target.value)} />
            </Field>
            <Field label="Descripción" wide>
              <input className={FIELD} value={draft.label} maxLength={MAX.label}
                onChange={(event) => set("label", event.target.value)} />
            </Field>
            <Field label="Latitud">
              <input className={FIELD} value={draft.lat} inputMode="decimal"
                onChange={(event) => set("lat", event.target.value)} />
            </Field>
            <Field label="Longitud">
              <input className={FIELD} value={draft.lon} inputMode="decimal"
                onChange={(event) => set("lon", event.target.value)} />
            </Field>
          </Section>

          <Section title="Plan">
            <Field label="Jornada planificada" wide>
              <select className={FIELD} value={draft.route_id} disabled={routes.loading && !planRoutes.length}
                onChange={(event) => set("route_id", event.target.value)}>
                {planRoutes.length === 0 && <option value={task.route_id}>{formatDayLabel(task.date)} · día {task.day}</option>}
                {planRoutes.map((route) => (
                  <option key={route.id} value={route.id}>{routeLabel(route)}</option>
                ))}
              </select>
              <span className="mt-1 block text-[11px] font-normal text-slate-500">
                Pasarla a otra jornada cambia su fecha planificada; va al final de ese día.
              </span>
            </Field>
          </Section>

          <Section title="Seguimiento">
            <Field label="Estado">
              <select className={FIELD} value={draft.status} onChange={(event) => set("status", event.target.value)}>
                {draft.status === "reprogramada" && (
                  <option value="reprogramada" disabled>{STATUS_LABEL.reprogramada}</option>
                )}
                {REPORTABLE.map((status) => (
                  <option key={status} value={status}>{STATUS_LABEL[status]}</option>
                ))}
              </select>
            </Field>
            <Field label="Fecha de ejecución">
              <input type="date" className={FIELD} value={draft.reported_date}
                onChange={(event) => set("reported_date", event.target.value)} />
            </Field>
            <Field label="Cuadrilla">
              <input className={FIELD} value={draft.crew} maxLength={MAX.crew} placeholder="Ej.: AE414WY"
                onChange={(event) => set("crew", event.target.value)} />
            </Field>
            <Field label="Requiere camión">
              <input className={FIELD} value={draft.truck} maxLength={MAX.truck} placeholder="Ninguno"
                onChange={(event) => set("truck", event.target.value)} />
            </Field>
            <Field label="Nodo al que se migró" wide>
              <input className={FIELD} value={draft.migrated_node} maxLength={MAX.node}
                placeholder={task.node ? `Preliminar: ${task.node}` : "Sin nodo"}
                onChange={(event) => set("migrated_node", event.target.value)} />
            </Field>
            <Field label="Observación" wide>
              <textarea className={`${FIELD} resize-y`} rows={3} value={draft.observation} maxLength={MAX.observation}
                placeholder="Sin observación" onChange={(event) => set("observation", event.target.value)} />
            </Field>
          </Section>

          <fieldset className="space-y-2 rounded-lg border border-slate-800 p-3">
            <legend className="px-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Pendientes</legend>
            <label className="flex items-center gap-2 text-xs text-slate-300">
              <input type="checkbox" className="h-4 w-4 accent-sky-400" checked={draft.pendingAuto}
                onChange={(event) => set("pendingAuto", event.target.checked)} />
              Calcularlos solos a partir de la observación
            </label>
            {draft.pendingAuto ? (
              <p className="text-xs text-slate-400">
                {task.pending_manual ? "Al guardar vuelven a calcularse." : (task.pending_actions ?? "Nada pendiente.")}
              </p>
            ) : (
              <textarea className={`${FIELD} resize-y`} rows={2} value={draft.pending} maxLength={MAX.pending}
                placeholder="Lo que queda por hacer" aria-label="Pendientes escritos a mano"
                onChange={(event) => set("pending", event.target.value)} />
            )}
          </fieldset>

          {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
        </div>

        <footer className="flex justify-end gap-2 border-t border-slate-800 px-4 py-3">
          <button type="button" onClick={onClose} disabled={busy}
            className="rounded-md px-3 py-1.5 text-sm text-slate-300 transition hover:bg-slate-800 hover:text-white disabled:opacity-50">
            Cancelar
          </button>
          <button type="submit" disabled={busy}
            className="rounded-md bg-sky-500 px-3 py-1.5 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:opacity-50">
            {busy ? "Guardando…" : "Guardar"}
          </button>
        </footer>
      </form>
    </dialog>
  );
}
