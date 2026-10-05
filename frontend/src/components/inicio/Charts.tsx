"use client";

/**
 * Piezas del Inicio: cifras, la tabla de localidades y los gráficos.
 *
 * Todo con CSS, como el resumen del registro: barras de una sola serie en
 * PANEL_BAR (la identidad la lleva el rótulo de la fila, no el color) y las
 * apiladas por estado con STATUS_INK, en el orden de `SEGMENTS` (lo pendiente
 * entre lo realizado y lo no realizado).
 */

import { useMemo, useState, type ReactNode } from "react";

import { StatusIcon, STATUS_LABEL } from "@/components/registro/StatusBadge";
import { SEGMENTS, StackedBar } from "@/components/registro/Summary";
import { IconCalendar, IconChevron } from "@/components/ui/icons";
import type { CatalogSummary, DepotReach, LocalitySummary, MonthTasks } from "@/lib/catalogo";
import { formatShortDate, percent } from "@/lib/format";
import type { PlanSummary } from "@/lib/registro";
import { PANEL_BAR, STATUS_INK } from "@/lib/vizTokens";

const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function monthLabel(month: string, withYear = false): string {
  const [year, number] = month.split("-");
  const name = MONTHS[Number(number) - 1] ?? month;
  return withYear ? `${name} ${year}` : name;
}

/** "2026-10-01" → "01/10/26". */
function shortDateWithYear(iso: string): string {
  return `${formatShortDate(iso)}/${iso.slice(2, 4)}`;
}

const number = new Intl.NumberFormat("es-AR");

export function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2.5">
      <header className="flex items-baseline justify-between gap-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
        {aside && <span className="text-[11px] text-slate-500">{aside}</span>}
      </header>
      {children}
    </section>
  );
}

// ---------------------------------------------------------------- Cifras

function Tile({
  label,
  value,
  detail,
  tone = "default",
  children,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: "default" | "warn";
  children?: ReactNode;
}) {
  return (
    <div className="rounded-xl bg-slate-900 px-3 py-2.5 ring-1 ring-white/5">
      <dt className="text-[11px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className={`text-2xl font-semibold tabular-nums ${tone === "warn" ? "text-amber-300" : "text-slate-50"}`}>
        {value}
      </dd>
      {detail && <dd className="truncate text-[11px] text-slate-500">{detail}</dd>}
      {children && <dd className="mt-1.5">{children}</dd>}
    </div>
  );
}

export function KpiTiles({ summary }: { summary: CatalogSummary }) {
  const { tasks, visit_age: age } = summary;
  const stale = age.older + age.never;
  const missing = tasks.pending + tasks.not_done;
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      <Tile
        label="Cámaras"
        value={number.format(summary.camera_count)}
        detail={`en ${summary.locality_count} localidad${summary.locality_count === 1 ? "" : "es"}`}
      />
      <Tile
        label="Planes"
        value={number.format(summary.plan_count)}
        detail={`${number.format(summary.route_count)} jornadas · ${number.format(Math.round(summary.distance_m / 1000))} km`}
      />
      <Tile
        label="Avance de tareas"
        value={`${percent(tasks.done, tasks.total)}%`}
        detail={`${number.format(tasks.done)} de ${number.format(tasks.total)} realizadas`}
      >
        <StackedBar counts={tasks} className="h-1.5" />
      </Tile>
      <Tile label="Tareas que faltan" value={number.format(missing)} detail={`${tasks.not_done} informadas como no realizadas`} />
      <Tile
        label="Sin visita reciente"
        value={number.format(stale)}
        tone={stale > 0 ? "warn" : "default"}
        detail={`más de 90 días o nunca (${age.never} nunca)`}
      />
      <Tile
        label="Visitadas en 30 días"
        value={`${percent(age.within_30, summary.camera_count)}%`}
        detail={`${number.format(age.within_30)} cámaras`}
      />
    </dl>
  );
}

// ---------------------------------------------------------------- Localidades

type SortKey = "name" | "cameras" | "visited" | "pending" | "last_visit";
const MAX_ROWS = 12;

function SortButton({
  label,
  column,
  sort,
  onSort,
  className = "",
}: {
  label: string;
  column: SortKey;
  sort: { key: SortKey; desc: boolean };
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = sort.key === column;
  return (
    <th scope="col" aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"} className={`py-1.5 font-medium ${className}`}>
      <button
        type="button"
        onClick={() => onSort(column)}
        className={`inline-flex items-center gap-0.5 hover:text-slate-200 ${active ? "text-slate-200" : ""}`}
      >
        {label}
        {active && <IconChevron className={`h-3 w-3 ${sort.desc ? "" : "rotate-180"}`} />}
      </button>
    </th>
  );
}

export function LocalityTable({
  localities,
  focused,
  onFocus,
  onPlan,
}: {
  localities: LocalitySummary[];
  focused: string | null;
  onFocus: (name: string | null) => void;
  onPlan: (name: string) => void;
}) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "cameras", desc: true });
  const [showAll, setShowAll] = useState(false);
  const max = Math.max(1, ...localities.map((item) => item.cameras));

  const sorted = useMemo(() => {
    const value = (item: LocalitySummary): number | string => {
      if (sort.key === "name") return item.name;
      if (sort.key === "visited") return item.cameras ? item.visited / item.cameras : 0;
      if (sort.key === "last_visit") return item.last_visit ?? "";
      return item[sort.key];
    };
    return [...localities].sort((a, b) => {
      const [x, y] = [value(a), value(b)];
      const order = typeof x === "string" ? x.localeCompare(String(y), "es") : x - Number(y);
      return (sort.desc ? -order : order) || a.name.localeCompare(b.name, "es");
    });
  }, [localities, sort]);

  if (localities.length === 0) {
    return <p className="rounded-lg border border-dashed border-slate-800 px-3 py-4 text-center text-xs text-slate-500">Sin cámaras cargadas.</p>;
  }

  const rows = showAll ? sorted : sorted.slice(0, MAX_ROWS);
  const onSort = (key: SortKey) =>
    setSort((prev) => (prev.key === key ? { key, desc: !prev.desc } : { key, desc: key !== "name" }));

  return (
    <div>
      <table className="w-full table-fixed text-left text-xs">
        <thead className="text-[11px] text-slate-500">
          <tr className="border-b border-slate-800">
            <SortButton label="Localidad" column="name" sort={sort} onSort={onSort} className="w-[34%]" />
            <SortButton label="Cámaras" column="cameras" sort={sort} onSort={onSort} />
            <SortButton label="Visitadas" column="visited" sort={sort} onSort={onSort} className="w-[17%] text-right" />
            <SortButton label="Faltan" column="pending" sort={sort} onSort={onSort} className="w-[13%] text-right" />
            <SortButton label="Última" column="last_visit" sort={sort} onSort={onSort} className="hidden w-[15%] text-right sm:table-cell" />
            <th scope="col" className="w-9">
              <span className="sr-only">Planificar</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => {
            const isFocused = focused === item.name;
            return (
              <tr
                key={item.name}
                className={`border-b border-slate-800/60 ${isFocused ? "bg-sky-500/10" : "hover:bg-slate-900"}`}
              >
                <td className="py-1.5 pr-2">
                  <button
                    type="button"
                    onClick={() => onFocus(isFocused ? null : item.name)}
                    aria-pressed={isFocused}
                    title={isFocused ? "Ver todas en el mapa" : "Ver sólo esta localidad en el mapa"}
                    className={`block w-full truncate text-left font-medium ${isFocused ? "text-sky-200" : "text-slate-200 hover:text-white"}`}
                  >
                    {item.name}
                  </button>
                </td>
                <td className="py-1.5 pr-2">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 min-w-0 flex-1">
                      <span
                        className="block h-full rounded-r-[4px]"
                        style={{ width: `${(item.cameras / max) * 100}%`, backgroundColor: PANEL_BAR }}
                      />
                    </span>
                    <span className="w-8 shrink-0 text-right tabular-nums text-slate-200">{item.cameras}</span>
                  </span>
                </td>
                <td className="py-1.5 text-right tabular-nums text-slate-300">{percent(item.visited, item.cameras)}%</td>
                <td className={`py-1.5 text-right tabular-nums ${item.pending ? "text-amber-300" : "text-slate-500"}`}>
                  {item.pending}
                </td>
                <td className="hidden py-1.5 text-right tabular-nums text-slate-400 sm:table-cell">
                  {item.last_visit ? shortDateWithYear(item.last_visit) : "—"}
                </td>
                <td className="py-1 text-right">
                  <button
                    type="button"
                    onClick={() => onPlan(item.name)}
                    title={`Planificar las ${item.cameras} cámaras de ${item.name}`}
                    aria-label={`Planificar ${item.name}`}
                    className="rounded-md p-1 text-slate-500 hover:bg-slate-800 hover:text-sky-300"
                  >
                    <IconCalendar className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {sorted.length > MAX_ROWS && (
        <button type="button" onClick={() => setShowAll((value) => !value)} className="mt-1.5 text-xs text-sky-300 hover:text-sky-200">
          {showAll ? "Ver menos" : `Ver las ${sorted.length} localidades`}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Tareas por mes

export function MonthlyChart({ months, today }: { months: MonthTasks[]; today: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const totals = months.map((month) => month.done + month.pending + month.not_done + month.rescheduled);
  const max = Math.max(1, ...totals);
  const current = today.slice(0, 7);
  const hovered = hover === null ? null : months[hover];

  if (totals.every((total) => total === 0)) {
    return (
      <p className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-xs text-slate-500">
        Todavía no hay planes guardados en el registro.
      </p>
    );
  }

  return (
    <figure>
      <figcaption className="mb-2 min-h-4 text-[11px] text-slate-500">
        {hovered ? (
          <span className="text-slate-200">
            <span className="capitalize">{monthLabel(hovered.month, true)}</span>: {hovered.done} realizadas
            {hovered.pending > 0 && ` · ${hovered.pending} pendientes`}
            {hovered.not_done > 0 && ` · ${hovered.not_done} no realizadas`}
            {hovered.rescheduled > 0 && ` · ${hovered.rescheduled} reprogramadas`}
          </span>
        ) : (
          "Pasá por un mes para ver el detalle"
        )}
      </figcaption>
      <div
        role="list"
        aria-label="Tareas por mes, por estado"
        className="flex h-32 items-end gap-[3px]"
        onMouseLeave={() => setHover(null)}
      >
        {months.map((month, index) => (
          <div
            key={month.month}
            role="listitem"
            tabIndex={0}
            aria-label={`${monthLabel(month.month, true)}: ${month.done} realizadas, ${month.pending} pendientes, ${month.not_done} no realizadas, ${month.rescheduled} reprogramadas`}
            onMouseEnter={() => setHover(index)}
            onFocus={() => setHover(index)}
            className={`flex h-full min-w-0 flex-1 flex-col justify-end rounded-sm outline-none focus-visible:ring-1 focus-visible:ring-sky-300 ${
              hover === index ? "bg-slate-800/80" : ""
            }`}
          >
            <span
              className={`flex w-full flex-col-reverse gap-[2px] ${month.month > current ? "opacity-55" : ""}`}
              style={{ height: `${(totals[index] / max) * 100}%` }}
            >
              {SEGMENTS.filter(({ key }) => key !== "total" && month[key as keyof MonthTasks]).map(({ status, key }) => (
                <span
                  key={status}
                  className="w-full first:rounded-b-[2px] last:rounded-t-[4px]"
                  style={{
                    flexGrow: Number(month[key as keyof MonthTasks]),
                    flexBasis: 0,
                    backgroundColor: STATUS_INK[status],
                  }}
                />
              ))}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-[3px] border-t border-slate-800 pt-1 text-[10px] text-slate-500">
        {months.map((month) => (
          <span key={month.month} className={`min-w-0 flex-1 truncate text-center ${month.month === current ? "font-semibold text-slate-300" : ""}`}>
            {monthLabel(month.month)}
          </span>
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-400">
        {SEGMENTS.map(({ status }) => (
          <li key={status} className="flex items-center gap-1">
            <StatusIcon status={status} className="h-3.5 w-3.5" />
            {STATUS_LABEL[status]}
          </li>
        ))}
        <li className="text-slate-500">· atenuado: meses por venir</li>
      </ul>
    </figure>
  );
}

// ---------------------------------------------------------------- Barras de una serie

/** Filas rótulo + barra + cifra: magnitudes de una sola serie. */
export function BarList({
  rows,
  total,
  empty,
}: {
  rows: { key: string; label: ReactNode; value: number; detail?: ReactNode }[];
  total?: number;
  empty: string;
}) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  if (rows.length === 0) {
    return <p className="rounded-lg border border-dashed border-slate-800 px-3 py-4 text-center text-xs text-slate-500">{empty}</p>;
  }
  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={row.key} className="text-xs">
          <div className="mb-0.5 flex items-baseline justify-between gap-2">
            <span className="min-w-0 truncate text-slate-300">{row.label}</span>
            <span className="shrink-0 tabular-nums text-slate-200">
              {number.format(row.value)}
              {total ? <span className="text-slate-500"> · {percent(row.value, total)}%</span> : null}
            </span>
          </div>
          <div className="h-2 rounded-r-[4px] bg-slate-800/60">
            <div className="h-full rounded-r-[4px]" style={{ width: `${(row.value / max) * 100}%`, backgroundColor: PANEL_BAR }} />
          </div>
          {row.detail && <div className="mt-0.5 text-[11px] text-slate-500">{row.detail}</div>}
        </li>
      ))}
    </ul>
  );
}

export function VisitAgeBars({ summary }: { summary: CatalogSummary }) {
  const { visit_age: age } = summary;
  return (
    <BarList
      total={summary.camera_count}
      empty="Sin cámaras cargadas."
      rows={
        summary.camera_count === 0
          ? []
          : [
              { key: "30", label: "Hasta 30 días", value: age.within_30 },
              { key: "90", label: "De 31 a 90 días", value: age.within_90 },
              { key: "older", label: "Más de 90 días", value: age.older },
              { key: "never", label: "Nunca visitadas", value: age.never },
            ]
      }
    />
  );
}

export function DepotReachBars({ depots }: { depots: DepotReach[] }) {
  return (
    <BarList
      empty="Todavía no hay sedes cargadas."
      rows={depots.map((depot) => ({
        key: String(depot.id),
        label: depot.name,
        value: depot.cameras,
        detail:
          depot.average_km === null
            ? "ninguna cámara la tiene como la más cercana"
            : `a ${depot.average_km.toFixed(1)} km en promedio · la más lejana a ${depot.max_km?.toFixed(1)} km`,
      }))}
    />
  );
}

// ---------------------------------------------------------------- Planes

export function RecentPlans({ plans, onOpen }: { plans: PlanSummary[]; onOpen: () => void }) {
  if (plans.length === 0) {
    return <p className="rounded-lg border border-dashed border-slate-800 px-3 py-4 text-center text-xs text-slate-500">Todavía no hay planes guardados.</p>;
  }
  return (
    <ul className="space-y-1.5">
      {plans.slice(0, 5).map((plan) => (
        <li key={plan.id}>
          <button
            type="button"
            onClick={onOpen}
            className="w-full space-y-1.5 rounded-lg bg-slate-900 px-3 py-2 text-left ring-1 ring-white/5 hover:bg-slate-800/80"
          >
            <span className="flex items-baseline justify-between gap-2 text-xs">
              <span className="truncate font-medium text-slate-100">{plan.name}</span>
              <span className="shrink-0 tabular-nums text-slate-300">{percent(plan.done, plan.total)}%</span>
            </span>
            <StackedBar counts={plan} className="h-1.5" />
            <span className="block text-[11px] text-slate-500">
              {plan.route_count} jornada{plan.route_count === 1 ? "" : "s"} · {plan.done} de {plan.total} tareas
              {plan.date_from && ` · ${formatShortDate(plan.date_from)}`}
              {plan.date_to && plan.date_to !== plan.date_from && ` al ${formatShortDate(plan.date_to)}`}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
