"use client";

/** Elección del plan que se ve en el mapa y en las listas del Registro. */

import { IconDownload } from "@/components/ui/icons";
import { formatShortDate, percent } from "@/lib/format";
import { missing, type PlanSummary } from "@/lib/registro";

const SELECT =
  "w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-2 text-sm font-medium text-slate-100 focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-400/20";

export default function PlanPicker({
  plans,
  planId,
  chosen,
  isDownloading,
  onChange,
  onDownload,
}: {
  plans: PlanSummary[];
  planId: number | null;
  /** false mientras el usuario no eligió (ni "Todos los planes"). */
  chosen: boolean;
  isDownloading: boolean;
  onChange: (choice: number | null | "none") => void;
  onDownload: () => void;
}) {
  const active = plans.find((plan) => plan.id === planId);
  const range =
    active?.date_from && active.date_to
      ? active.date_from === active.date_to
        ? formatShortDate(active.date_from)
        : `${formatShortDate(active.date_from)} → ${formatShortDate(active.date_to)}`
      : null;

  return (
    <div className="space-y-2 rounded-xl border border-sky-500/30 bg-sky-500/5 p-3">
      <label className="block">
        <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-400">
          Plan en el mapa
        </span>
        <select
          value={chosen ? (planId ?? "") : "none"}
          onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
          className={SELECT}
        >
          {!chosen && (
            <option value="none" disabled>
              — Elegí un plan —
            </option>
          )}
          <option value="">Todos los planes</option>
          {plans.map((plan) => (
            <option key={plan.id} value={plan.id}>
              {plan.name} · {percent(plan.done, plan.total)}%
            </option>
          ))}
        </select>
      </label>
      <p className="text-[11px] leading-relaxed text-slate-400">
        {!chosen
          ? "Elegí un plan para ver sus recorridos en el mapa."
          : active
            ? `${range ? `${range} · ` : ""}${active.route_count} recorrido(s) · ${
                missing(active) > 0 ? `faltan ${missing(active)}` : "no falta nada"
              }`
            : "Se ven los días que marques, de cualquier plan."}
      </p>
      <button
        type="button"
        onClick={onDownload}
        disabled={isDownloading || !chosen}
        title={
          active
            ? "Todas las tareas del plan con lo que se informó hasta ahora"
            : "Todas las tareas de todos los planes con lo que se informó hasta ahora"
        }
        className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs font-medium text-slate-100 transition hover:border-slate-500 hover:bg-slate-800 disabled:cursor-not-allowed disabled:text-slate-500"
      >
        <IconDownload className="h-3.5 w-3.5" />
        {isDownloading ? "Generando…" : "Descargar Excel actualizado"}
      </button>
    </div>
  );
}
