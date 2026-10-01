"use client";

/**
 * Avance de lo filtrado: porcentaje realizado, una barra apilada por estado y
 * un gráfico de tareas por día.
 *
 * Orden de los segmentos en todas las barras: realizadas, pendientes, no
 * realizadas, reprogramadas. Lo pendiente queda entre el verde y el rojo a
 * propósito — ese par no se distingue con daltonismo y nunca va contiguo.
 */

import { useState } from "react";

import { StatusIcon, STATUS_LABEL } from "@/components/registro/StatusBadge";
import { formatDayLabel, percent } from "@/lib/format";
import type { RouteSummary, TaskCounts, TaskStatus } from "@/lib/registro";
import { STATUS_INK } from "@/lib/vizTokens";

const SEGMENTS: { status: TaskStatus; key: keyof TaskCounts }[] = [
  { status: "realizada", key: "done" },
  { status: "pendiente", key: "pending" },
  { status: "no_realizada", key: "not_done" },
  { status: "reprogramada", key: "rescheduled" },
];

// Más días que esto no entran legibles en el ancho del panel.
const MAX_CHART_DAYS = 60;

type DayTotals = TaskCounts & { date: string; routes: number };

export function countsOf(routes: RouteSummary[]): TaskCounts {
  return routes.reduce(
    (sum, route) => ({
      total: sum.total + route.total,
      done: sum.done + route.done,
      pending: sum.pending + route.pending,
      not_done: sum.not_done + route.not_done,
      rescheduled: sum.rescheduled + route.rescheduled,
    }),
    { total: 0, done: 0, pending: 0, not_done: 0, rescheduled: 0 },
  );
}

/** Totales por fecha, de la más vieja a la más nueva (los últimos MAX_CHART_DAYS). */
function dailyTotals(routes: RouteSummary[]): DayTotals[] {
  const byDate = new Map<string, DayTotals>();
  for (const route of routes) {
    const day = byDate.get(route.date) ?? {
      date: route.date, routes: 0, total: 0, done: 0, pending: 0, not_done: 0, rescheduled: 0,
    };
    byDate.set(route.date, {
      ...day,
      routes: day.routes + 1,
      total: day.total + route.total,
      done: day.done + route.done,
      pending: day.pending + route.pending,
      not_done: day.not_done + route.not_done,
      rescheduled: day.rescheduled + route.rescheduled,
    });
  }
  return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date)).slice(-MAX_CHART_DAYS);
}

/** Barra horizontal apilada por estado, con 2px de separación entre tramos. */
export function StackedBar({ counts, className = "h-2.5" }: { counts: TaskCounts; className?: string }) {
  if (counts.total === 0) return <div className={`${className} rounded-full bg-slate-800`} />;
  return (
    <div className={`flex gap-[2px] overflow-hidden rounded-full ${className}`}>
      {SEGMENTS.filter(({ key }) => counts[key] > 0).map(({ status, key }) => (
        <span
          key={status}
          className="h-full first:rounded-l-full last:rounded-r-full"
          style={{ width: `${(counts[key] / counts.total) * 100}%`, backgroundColor: STATUS_INK[status] }}
        />
      ))}
    </div>
  );
}

function DailyChart({
  days,
  today,
  onSelectDate,
}: {
  days: DayTotals[];
  today: string;
  onSelectDate: (date: string) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...days.map((day) => day.total));
  const hovered = hover === null ? null : days[hover];

  if (days.length === 0) {
    return (
      <div className="flex h-full min-h-28 items-center justify-center rounded-lg border border-dashed border-slate-800 text-xs text-slate-500">
        Sin recorridos guardados con estos filtros.
      </div>
    );
  }

  return (
    <figure className="flex h-full flex-col">
      <figcaption className="mb-2 flex items-baseline justify-between gap-2 text-[11px]">
        <span className="font-semibold uppercase tracking-wide text-slate-500">Tareas por día</span>
        <span className="truncate text-slate-500">
          {hovered ? (
            <span className="text-slate-200">
              <span className="capitalize">{formatDayLabel(hovered.date)}</span> · {hovered.done}/{hovered.total} realizadas
              {hovered.not_done > 0 && ` · ${hovered.not_done} no`}
              {hovered.pending > 0 && ` · ${hovered.pending} pend.`}
              {hovered.rescheduled > 0 && ` · ${hovered.rescheduled} reprog.`}
            </span>
          ) : (
            "Tocá un día para verlo en el mapa"
          )}
        </span>
      </figcaption>
      <div
        role="list"
        aria-label="Tareas por día, por estado"
        className="flex min-h-24 flex-1 items-end gap-[3px]"
        onMouseLeave={() => setHover(null)}
      >
        {days.map((day, index) => {
          const isFuture = day.date > today;
          return (
            <button
              key={day.date}
              type="button"
              role="listitem"
              aria-label={`${formatDayLabel(day.date)}: ${day.done} realizadas, ${day.pending} pendientes, ${day.not_done} no realizadas, ${day.rescheduled} reprogramadas`}
              onMouseEnter={() => setHover(index)}
              onFocus={() => setHover(index)}
              onClick={() => onSelectDate(day.date)}
              className={`group flex h-full min-w-[3px] max-w-[40px] flex-1 flex-col justify-end rounded-sm focus-visible:outline-2 focus-visible:outline-sky-300 ${
                hover === index ? "bg-slate-800/80" : ""
              }`}
            >
              <span
                className={`flex w-full flex-col-reverse gap-[2px] ${isFuture ? "opacity-55" : ""}`}
                style={{ height: `${(day.total / max) * 100}%` }}
              >
                {SEGMENTS.filter(({ key }) => day[key] > 0).map(({ status, key }) => (
                  <span
                    key={status}
                    className="w-full first:rounded-b-[2px] last:rounded-t-[4px]"
                    style={{ flexGrow: day[key], flexBasis: 0, backgroundColor: STATUS_INK[status] }}
                  />
                ))}
              </span>
            </button>
          );
        })}
      </div>
      <div className="mt-1.5 flex justify-between border-t border-slate-800 pt-1 text-[10px] tabular-nums text-slate-500">
        <span className="capitalize">{formatDayLabel(days[0].date)}</span>
        {days.length > 1 && <span className="capitalize">{formatDayLabel(days[days.length - 1].date)}</span>}
      </div>
    </figure>
  );
}

export default function Summary({
  routes,
  planCount,
  today,
  onSelectDate,
}: {
  routes: RouteSummary[];
  planCount: number;
  today: string;
  onSelectDate: (date: string) => void;
}) {
  const counts = countsOf(routes);
  const days = dailyTotals(routes);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="space-y-3">
        <div className="flex items-end justify-between gap-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Avance</div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-semibold tracking-tight text-slate-50">
                {percent(counts.done, counts.total)}
                <span className="text-lg text-slate-400">%</span>
              </span>
              <span className="text-xs text-slate-400">
                {counts.done} de {counts.total} tareas realizadas
              </span>
            </div>
          </div>
          <div className="text-right text-xs leading-tight text-slate-400">
            <div>
              <span className="font-semibold text-slate-100">{routes.length}</span> recorrido(s)
            </div>
            <div>
              <span className="font-semibold text-slate-100">{planCount}</span> plan(es)
            </div>
          </div>
        </div>
        <StackedBar counts={counts} />
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4 md:grid-cols-2 lg:grid-cols-4">
          {SEGMENTS.map(({ status, key }) => (
            <div key={status} className="flex flex-col-reverse rounded-lg bg-slate-900 px-2.5 py-2">
              <dt className="whitespace-nowrap text-[11px] text-slate-400">{STATUS_LABEL[status]}s</dt>
              <dd className="flex items-center gap-1.5 text-lg font-semibold tabular-nums text-slate-50">
                <StatusIcon status={status} className="h-4 w-4" />
                {counts[key]}
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <DailyChart days={days} today={today} onSelectDate={onSelectDate} />
    </div>
  );
}
