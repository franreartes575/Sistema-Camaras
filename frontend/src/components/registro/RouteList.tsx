"use client";

/**
 * Pestaña Recorridos: jornadas agrupadas por día, con su avance. Cada una se
 * marca para verla en el mapa; al tocarla se enfoca y despliega sus paradas.
 */

import { useState } from "react";

import RouteDateEditor from "@/components/registro/RouteDateEditor";
import { StackedBar } from "@/components/registro/Summary";
import { StatusIcon } from "@/components/registro/StatusBadge";
import { StopRow } from "@/components/registro/TaskRow";
import { IconCalendar, IconChevron, IconPencil } from "@/components/ui/icons";
import { formatDistance, formatDuration, formatLongDay } from "@/lib/format";
import { shiftIso } from "@/lib/planDates";
import {
  missing,
  routeState,
  type TaskChanges,
  type RouteDetail,
  type RouteState,
  type RouteSummary,
  type Task,
} from "@/lib/registro";

export type StateFilter = RouteState | "todos";

export const STATE_FILTERS: { id: StateFilter; label: string }[] = [
  { id: "todos", label: "Todos" },
  { id: "faltan", label: "Con faltantes" },
  { id: "completo", label: "Completos" },
  { id: "programado", label: "Programados" },
  { id: "reprogramado", label: "Reprogramados" },
];

function StateChip({ route, today }: { route: RouteSummary; today: string }) {
  const state = routeState(route, today);
  const base = "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium";
  if (state === "completo") {
    return (
      <span className={`${base} bg-slate-800 text-slate-200`}>
        <StatusIcon status="realizada" className="h-3.5 w-3.5" /> Completo
      </span>
    );
  }
  if (state === "programado") {
    return (
      <span className={`${base} bg-sky-500/10 text-sky-200`}>
        <IconCalendar className="h-3 w-3" /> Programado
      </span>
    );
  }
  if (state === "reprogramado") {
    return (
      <span className={`${base} bg-slate-800 text-slate-400`}>
        <StatusIcon status="reprogramada" className="h-3.5 w-3.5" /> Reprogramado
      </span>
    );
  }
  return (
    <span className={`${base} bg-amber-500/10 text-amber-200`}>
      <StatusIcon status={route.not_done > 0 ? "no_realizada" : "pendiente"} className="h-3.5 w-3.5" />
      Faltan {missing(route)}
    </span>
  );
}

function dayCaption(date: string, today: string): string | null {
  if (date === today) return "hoy";
  if (date === shiftIso(today, 1)) return "mañana";
  if (date === shiftIso(today, -1)) return "ayer";
  return null;
}

function RouteCard({
  route,
  today,
  isSelected,
  isFocused,
  isExpanded,
  detail,
  busyTaskId,
  onToggle,
  onFocus,
  onTaskUpdate,
  onRouteDate,
  isRouteBusy = false,
}: {
  route: RouteSummary;
  today: string;
  isSelected: boolean;
  isFocused: boolean;
  isExpanded: boolean;
  detail: RouteDetail | undefined;
  busyTaskId: number | null;
  onToggle: () => void;
  onFocus: () => void;
  /** Sin él (no es administrador), las tareas se ven en sólo lectura. */
  onTaskUpdate?: (task: Task, changes: TaskChanges) => Promise<boolean>;
  /** Sin él (no es administrador), la fecha del día no se edita. */
  onRouteDate?: (date: string) => Promise<boolean>;
  isRouteBusy?: boolean;
}) {
  const [isEditingDate, setIsEditingDate] = useState(false);
  return (
    <li
      className={`overflow-hidden rounded-lg border transition ${
        isFocused
          ? "border-orange-400/70 bg-slate-800/70 shadow-lg shadow-orange-500/5"
          : isSelected
            ? "border-slate-600 bg-slate-900"
            : "border-slate-800 bg-slate-900/60 hover:border-slate-700"
      }`}
    >
      <div className="flex items-start gap-2.5 px-3 py-2.5">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onToggle}
          aria-label={`Mostrar en el mapa el día ${route.day} del ${route.date}`}
          className="mt-1 h-4 w-4 shrink-0 cursor-pointer accent-sky-400"
        />
        <button
          type="button"
          onClick={onFocus}
          aria-expanded={isExpanded}
          className="min-w-0 flex-1 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300"
        >
          <span className="flex items-start justify-between gap-2">
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold text-slate-50">
                Día {route.day}
                <span className="font-normal text-slate-400">
                  {" "}
                  · {route.start_name ?? `Cluster ${route.cluster_id}`}
                </span>
              </span>
              <span className="block truncate text-[11px] text-slate-500">{route.plan_name}</span>
            </span>
            <StateChip route={route} today={today} />
          </span>
          <StackedBar counts={route} className="mt-2 h-1.5" />
          <span className="mt-1.5 flex items-center justify-between gap-2 text-[11px] text-slate-400">
            <span>
              <span className="font-semibold text-slate-200">{route.done}</span>/{route.total} realizadas
              {route.not_done > 0 && <span> · {route.not_done} no realizada(s)</span>}
            </span>
            <span className="flex items-center gap-1 tabular-nums">
              {formatDistance(route.distance_m)} · {formatDuration(route.duration_s)}
              <IconChevron className={`h-3.5 w-3.5 transition-transform ${isExpanded ? "rotate-180" : ""}`} />
            </span>
          </span>
        </button>
        {onRouteDate && (
          <button
            type="button"
            onClick={() => setIsEditingDate(true)}
            disabled={isRouteBusy}
            aria-label={`Cambiar la fecha del día ${route.day} (${route.date})`}
            title="Cambiar la fecha del día"
            className="shrink-0 rounded-md p-1 text-slate-400 transition hover:bg-slate-800 hover:text-slate-100 disabled:opacity-50"
          >
            <IconPencil className="h-3.5 w-3.5" />
          </button>
        )}
        {isEditingDate && onRouteDate && (
          <RouteDateEditor
            route={route}
            busy={isRouteBusy}
            onSave={onRouteDate}
            onClose={() => setIsEditingDate(false)}
          />
        )}
      </div>
      {isExpanded && (
        <div className="border-t border-slate-700/60 bg-slate-950/40 px-3 py-1.5">
          {detail ? (
            <ol className="divide-y divide-slate-800/80">
              {detail.stops.map((task) => (
                <StopRow
                  key={task.id}
                  task={task}
                  busy={busyTaskId === task.id}
                  onUpdate={onTaskUpdate && ((changes) => onTaskUpdate(task, changes))}
                />
              ))}
            </ol>
          ) : (
            <p className="py-2 text-xs text-slate-500">Cargando paradas…</p>
          )}
        </div>
      )}
    </li>
  );
}

export default function RouteList({
  routes,
  today,
  stateFilter,
  stateCounts,
  selected,
  focusedId,
  expandedId,
  details,
  busyTaskId,
  onStateFilterChange,
  onToggle,
  onSetMany,
  onFocus,
  onTaskUpdate,
  onRouteDate,
  busyRouteId = null,
}: {
  routes: RouteSummary[];
  today: string;
  stateFilter: StateFilter;
  stateCounts: Record<StateFilter, number>;
  selected: Set<number>;
  focusedId: number | null;
  expandedId: number | null;
  details: Record<number, RouteDetail>;
  busyTaskId: number | null;
  onStateFilterChange: (filter: StateFilter) => void;
  onToggle: (id: number) => void;
  onSetMany: (ids: number[], on: boolean) => void;
  onFocus: (id: number) => void;
  /** Sin él (no es administrador), las tareas se ven en sólo lectura. */
  onTaskUpdate?: (task: Task, changes: TaskChanges) => Promise<boolean>;
  /** Cambia la fecha planificada de una jornada; sin él, no se edita. */
  onRouteDate?: (route: RouteSummary, date: string) => Promise<boolean>;
  busyRouteId?: number | null;
}) {
  const groups: { date: string; routes: RouteSummary[] }[] = [];
  for (const route of routes) {
    const last = groups[groups.length - 1];
    if (last && last.date === route.date) last.routes.push(route);
    else groups.push({ date: route.date, routes: [route] });
  }
  const visibleIds = routes.map((route) => route.id);
  const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));

  return (
    <div className="space-y-3">
      <div role="radiogroup" aria-label="Estado de los recorridos" className="flex flex-wrap gap-1.5">
        {STATE_FILTERS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={stateFilter === id}
            onClick={() => onStateFilterChange(id)}
            className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${
              stateFilter === id
                ? "bg-slate-100 text-slate-900"
                : "bg-slate-800/70 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {label} <span className="tabular-nums opacity-70">{stateCounts[id]}</span>
          </button>
        ))}
      </div>

      {routes.length > 0 && (
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>
            {selected.size > 0 ? `${selected.size} en el mapa` : "Marcá recorridos para verlos en el mapa"}
          </span>
          <button
            type="button"
            onClick={() => onSetMany(visibleIds, !allSelected)}
            className="rounded-md px-2 py-1 font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white"
          >
            {allSelected ? "Quitar todos del mapa" : "Ver todos en el mapa"}
          </button>
        </div>
      )}

      {routes.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-sm text-slate-500">
          No hay recorridos con estos filtros.
        </p>
      )}

      {groups.map((group) => {
        const ids = group.routes.map((route) => route.id);
        const groupSelected = ids.every((id) => selected.has(id));
        const caption = dayCaption(group.date, today);
        return (
          <section key={group.date} className="space-y-1.5">
            <header className="flex items-center justify-between gap-2 pt-1">
              <h3 className="flex items-center gap-2 text-xs font-semibold text-slate-300">
                <span>{formatLongDay(group.date)}</span>
                {caption && (
                  <span className="rounded-full bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-300">
                    {caption}
                  </span>
                )}
              </h3>
              <button
                type="button"
                onClick={() => onSetMany(ids, !groupSelected)}
                className="rounded-md px-1.5 py-0.5 text-[11px] text-slate-500 transition hover:bg-slate-800 hover:text-slate-200"
              >
                {groupSelected ? "Quitar del mapa" : "Ver día"}
              </button>
            </header>
            <ul className="space-y-1.5">
              {group.routes.map((route) => (
                <RouteCard
                  key={route.id}
                  route={route}
                  today={today}
                  isSelected={selected.has(route.id)}
                  isFocused={focusedId === route.id}
                  isExpanded={expandedId === route.id}
                  detail={details[route.id]}
                  busyTaskId={busyTaskId}
                  onToggle={() => onToggle(route.id)}
                  onFocus={() => onFocus(route.id)}
                  onTaskUpdate={onTaskUpdate}
                  onRouteDate={onRouteDate && ((date) => onRouteDate(route, date))}
                  isRouteBusy={busyRouteId === route.id}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
