"use client";

/** Pestaña Planes: cada plan guardado con su avance, para filtrar, renombrar o borrar. */

import { useState } from "react";

import { StackedBar } from "@/components/registro/Summary";
import { INPUT_CLASS } from "@/components/ui/controls";
import { IconPencil, IconTrash } from "@/components/ui/icons";
import { formatDistance, formatShortDate, formatTimestamp, percent } from "@/lib/format";
import { missing, type PlanSummary } from "@/lib/registro";

const ACTION =
  "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white disabled:opacity-50";

function PlanCard({
  plan,
  isFiltered,
  busy,
  onFilter,
  onRename,
  onDelete,
}: {
  plan: PlanSummary;
  isFiltered: boolean;
  busy: boolean;
  onFilter: () => void;
  onRename: (name: string) => void;
  onDelete: () => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const range =
    plan.date_from && plan.date_to
      ? plan.date_from === plan.date_to
        ? formatShortDate(plan.date_from)
        : `${formatShortDate(plan.date_from)} → ${formatShortDate(plan.date_to)}`
      : "sin jornadas";

  return (
    <li
      className={`space-y-2.5 rounded-lg border p-3 ${
        isFiltered ? "border-sky-400/60 bg-sky-500/5" : "border-slate-800 bg-slate-900/60"
      }`}
    >
      {draft === null ? (
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-slate-50">{plan.name}</h3>
            <p className="text-[11px] text-slate-500">
              {range} · {plan.route_count} recorrido(s) · {formatDistance(plan.distance_m)}
              {plan.is_road_network ? " por calle" : " en línea recta"}
            </p>
            <p className="text-[11px] text-slate-600">
              Guardado {formatTimestamp(plan.created_at)}
              {plan.source_file && ` · ${plan.source_file}`}
            </p>
          </div>
          <span className="shrink-0 text-right">
            <span className="block text-lg font-semibold tabular-nums text-slate-50">
              {percent(plan.done, plan.total)}%
            </span>
            <span className="block text-[11px] text-slate-500">
              {plan.done}/{plan.total}
            </span>
          </span>
        </div>
      ) : (
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.trim()) onRename(draft.trim());
            setDraft(null);
          }}
        >
          <input
            autoFocus
            value={draft}
            maxLength={200}
            aria-label="Nombre del plan"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => event.key === "Escape" && setDraft(null)}
            className={`${INPUT_CLASS} py-1.5`}
          />
          <button type="submit" className={`${ACTION} bg-slate-800`}>
            Guardar
          </button>
        </form>
      )}

      <StackedBar counts={plan} className="h-1.5" />
      <p className="text-[11px] text-slate-400">
        {missing(plan) > 0 ? `Faltan ${missing(plan)}` : "No falta nada"}
        {plan.not_done > 0 && ` (${plan.not_done} no realizada/s)`}
        {plan.rescheduled > 0 && ` · ${plan.rescheduled} reprogramada(s)`}
      </p>

      {confirming ? (
        <div className="flex items-center justify-between gap-2 rounded-md bg-red-500/10 px-2.5 py-2 text-xs text-red-100">
          <span>¿Borrar el plan y sus {plan.total} tareas? No se puede deshacer.</span>
          <span className="flex shrink-0 gap-1">
            <button type="button" onClick={() => setConfirming(false)} className={ACTION}>
              Cancelar
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onDelete}
              className="rounded-md bg-red-500 px-2 py-1 text-xs font-semibold text-white transition hover:bg-red-400 disabled:opacity-50"
            >
              Borrar
            </button>
          </span>
        </div>
      ) : (
        <div className="flex flex-wrap gap-1">
          <button type="button" onClick={onFilter} className={ACTION} aria-pressed={isFiltered}>
            {isFiltered ? "Ver todos los planes" : "Filtrar por este plan"}
          </button>
          <button type="button" onClick={() => setDraft(plan.name)} className={ACTION}>
            <IconPencil className="h-3.5 w-3.5" /> Renombrar
          </button>
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className={`${ACTION} text-red-300 hover:bg-red-500/10 hover:text-red-200`}
          >
            <IconTrash className="h-3.5 w-3.5" /> Borrar
          </button>
        </div>
      )}
    </li>
  );
}

export default function PlanList({
  plans,
  filteredPlanId,
  busyPlanId,
  onFilter,
  onRename,
  onDelete,
}: {
  plans: PlanSummary[];
  filteredPlanId: number | null;
  busyPlanId: number | null;
  onFilter: (planId: number | null) => void;
  onRename: (planId: number, name: string) => void;
  onDelete: (planId: number) => void;
}) {
  if (plans.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-sm leading-relaxed text-slate-500">
        Todavía no hay planes guardados. Se guardan solos al exportar el Excel de
        seguimiento desde el planificador.
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {plans.map((plan) => (
        <PlanCard
          key={plan.id}
          plan={plan}
          isFiltered={filteredPlanId === plan.id}
          busy={busyPlanId === plan.id}
          onFilter={() => onFilter(filteredPlanId === plan.id ? null : plan.id)}
          onRename={(name) => onRename(plan.id, name)}
          onDelete={() => onDelete(plan.id)}
        />
      ))}
    </ul>
  );
}
