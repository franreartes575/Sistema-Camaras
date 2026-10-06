"use client";

/**
 * Selector de días del Registro: una grilla por semana (lunes a domingo) con un
 * casillero por cada día que tiene recorridos. La barra de color de cada día
 * dice cómo va: completo, con faltantes, programado o reprogramado.
 */

import { formatLongDay, formatShortDate } from "@/lib/format";
import { shiftIso, weekStartIso } from "@/lib/planDates";
import { missing, routeState, type RouteState, type RouteSummary } from "@/lib/registro";

const WEEKDAYS = ["L", "M", "M", "J", "V", "S", "D"];
const GRID = "grid grid-cols-[3.25rem_repeat(7,minmax(0,1fr))] gap-1";

const STATE_BAR: Record<RouteState, string> = {
  completo: "bg-emerald-400",
  faltan: "bg-amber-400",
  programado: "bg-sky-400",
  reprogramado: "bg-slate-500",
};

const STATE_LABEL: Record<RouteState, string> = {
  completo: "Completo",
  faltan: "Con faltantes",
  programado: "Programado",
  reprogramado: "Reprogramado",
};

const STATE_ORDER: RouteState[] = ["faltan", "programado", "reprogramado", "completo"];

/** El estado más urgente de las jornadas del día: una con faltantes lo marca "con faltantes". */
function dayState(routes: RouteSummary[], today: string): RouteState {
  const states = routes.map((route) => routeState(route, today));
  return STATE_ORDER.find((state) => states.includes(state)) ?? "completo";
}

export default function DayPicker({
  routes,
  selected,
  today,
  onSetMany,
  onReplace,
}: {
  routes: RouteSummary[];
  selected: Set<number>;
  today: string;
  onSetMany: (ids: number[], on: boolean) => void;
  onReplace: (ids: number[]) => void;
}) {
  const byDate = new Map<string, RouteSummary[]>();
  for (const route of routes) byDate.set(route.date, [...(byDate.get(route.date) ?? []), route]);
  const dates = [...byDate.keys()].sort();
  if (dates.length === 0) return null;

  const weeks = new Map<string, string[]>();
  for (const date of dates) {
    const monday = weekStartIso(date);
    weeks.set(monday, [...(weeks.get(monday) ?? []), date]);
  }

  const idsOf = (date: string) => (byDate.get(date) ?? []).map((route) => route.id);
  const isOn = (ids: number[]) => ids.length > 0 && ids.every((id) => selected.has(id));
  const daysOn = dates.filter((date) => isOn(idsOf(date))).length;
  const action =
    "rounded-md px-2 py-0.5 text-[11px] font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white";

  return (
    <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-900/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Días en el mapa</h3>
        <span className="flex gap-1">
          <button type="button" onClick={() => onReplace(routes.map((route) => route.id))} className={action}>
            Todos
          </button>
          <button type="button" onClick={() => onReplace([])} className={action}>
            Ninguno
          </button>
        </span>
      </div>

      <div role="group" aria-label="Días con recorridos" className="space-y-1">
        <div aria-hidden="true" className={`${GRID} text-center text-[10px] font-medium text-slate-500`}>
          <span />
          {WEEKDAYS.map((letter, index) => (
            <span key={index}>{letter}</span>
          ))}
        </div>
        {[...weeks].map(([monday, weekDates]) => {
          const weekIds = weekDates.flatMap(idsOf);
          const weekOn = isOn(weekIds);
          return (
            <div key={monday} className={`${GRID} items-stretch`}>
              <button
                type="button"
                onClick={() => onSetMany(weekIds, !weekOn)}
                title={`${weekOn ? "Quitar" : "Ver"} la semana del ${formatShortDate(monday)}`}
                className="rounded-md text-left text-[10px] leading-tight text-slate-500 transition hover:text-slate-200"
              >
                Sem. {formatShortDate(monday)}
              </button>
              {Array.from({ length: 7 }, (_, offset) => {
                const date = shiftIso(monday, offset);
                const dayRoutes = byDate.get(date);
                if (!dayRoutes) return <span key={date} aria-hidden="true" className="rounded-md bg-slate-900/30" />;
                const ids = idsOf(date);
                const on = isOn(ids);
                const partial = !on && ids.some((id) => selected.has(id));
                const state = dayState(dayRoutes, today);
                const faltan = dayRoutes.reduce((sum, route) => sum + missing(route), 0);
                return (
                  <button
                    key={date}
                    type="button"
                    aria-pressed={on}
                    onClick={() => onSetMany(ids, !on)}
                    title={`${formatLongDay(date)}${date === today ? " (hoy)" : ""} · ${dayRoutes.length} recorrido(s) · ${STATE_LABEL[state].toLowerCase()}${faltan > 0 ? ` (faltan ${faltan})` : ""}`}
                    className={`flex flex-col items-center rounded-md px-1 pb-1 pt-1.5 text-slate-100 transition focus-visible:outline-2 focus-visible:outline-sky-300 ${
                      on
                        ? "bg-sky-500/25 ring-1 ring-sky-400"
                        : partial
                          ? "bg-slate-800/70 ring-1 ring-sky-400/40 hover:bg-slate-700"
                          : "bg-slate-800/70 hover:bg-slate-700"
                    }`}
                  >
                    <span className={`text-sm tabular-nums ${date === today ? "font-bold text-sky-200" : "font-semibold"}`}>
                      {Number(date.slice(8))}
                    </span>
                    <span className="h-3 text-[9px] leading-3 text-slate-400">
                      {dayRoutes.length > 1 ? `×${dayRoutes.length}` : ""}
                    </span>
                    <span className={`h-1 w-full rounded-full ${STATE_BAR[state]}`} />
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-500">
        <span className="font-medium text-slate-400">
          {daysOn} de {dates.length} días
        </span>
        {STATE_ORDER.map((state) => (
          <span key={state} className="inline-flex items-center gap-1">
            <span className={`h-1.5 w-3 rounded-full ${STATE_BAR[state]}`} />
            {STATE_LABEL[state]}
          </span>
        ))}
      </div>
    </div>
  );
}
