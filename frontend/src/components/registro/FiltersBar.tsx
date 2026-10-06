"use client";

/** Filtros del registro: período (con atajos) y búsqueda de texto. El plan se elige aparte (PlanPicker). */

import { IconSearch, IconX } from "@/components/ui/icons";
import { formatShortDate } from "@/lib/format";
import { monthRangeIso, shiftIso, weekStartIso } from "@/lib/planDates";
import type { RegistryFilters } from "@/lib/registro";

type Preset = { id: string; label: string; range: (today: string) => { desde: string; hasta: string } };

const PRESETS: Preset[] = [
  { id: "todo", label: "Todo", range: () => ({ desde: "", hasta: "" }) },
  {
    id: "semana",
    label: "Esta semana",
    range: (today) => ({ desde: weekStartIso(today), hasta: shiftIso(weekStartIso(today), 6) }),
  },
  {
    id: "mes",
    label: "Este mes",
    range: (today) => {
      const { from, to } = monthRangeIso(today);
      return { desde: from, hasta: to };
    },
  },
  { id: "proximos", label: "Próximos", range: (today) => ({ desde: today, hasta: "" }) },
];

const DATE_INPUT =
  "w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 [color-scheme:dark] focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-400/20";

export default function FiltersBar({
  filters,
  search,
  today,
  onChange,
  onSearchChange,
}: {
  filters: RegistryFilters;
  /** Texto del buscador tal como se escribe (el filtro aplica con demora). */
  search: string;
  today: string;
  onChange: (filters: RegistryFilters) => void;
  onSearchChange: (text: string) => void;
}) {
  const active = PRESETS.find((preset) => {
    const range = preset.range(today);
    return range.desde === filters.desde && range.hasta === filters.hasta;
  });
  const set = (patch: Partial<RegistryFilters>) => onChange({ ...filters, ...patch });
  const hasFilters = Boolean(filters.desde || filters.hasta || search);

  return (
    <div className="space-y-2.5 rounded-xl border border-slate-800 bg-slate-900/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Filtros</h2>
        {hasFilters && (
          <button
            type="button"
            onClick={() => {
              onChange({ desde: "", hasta: "", planId: filters.planId, q: "" });
              onSearchChange("");
            }}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-slate-400 transition hover:bg-slate-800 hover:text-slate-100"
          >
            <IconX className="h-3 w-3" /> Limpiar
          </button>
        )}
      </div>

      <div role="radiogroup" aria-label="Período" className="flex flex-wrap gap-1.5">
        {PRESETS.map((preset) => {
          const isActive = active?.id === preset.id;
          return (
            <button
              key={preset.id}
              type="button"
              role="radio"
              aria-checked={isActive}
              onClick={() => set(preset.range(today))}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                isActive
                  ? "bg-sky-500 text-slate-950"
                  : "bg-slate-800/80 text-slate-300 hover:bg-slate-700 hover:text-white"
              }`}
            >
              {preset.label}
            </button>
          );
        })}
        {!active && (
          <span className="rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-sky-300 ring-1 ring-sky-400/40">
            {filters.desde ? formatShortDate(filters.desde) : "…"} – {filters.hasta ? formatShortDate(filters.hasta) : "…"}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="mb-1 block text-[11px] font-medium text-slate-500">Desde</span>
          <input
            type="date"
            value={filters.desde}
            max={filters.hasta || undefined}
            onChange={(event) => set({ desde: event.target.value })}
            className={DATE_INPUT}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-medium text-slate-500">Hasta</span>
          <input
            type="date"
            value={filters.hasta}
            min={filters.desde || undefined}
            onChange={(event) => set({ hasta: event.target.value })}
            className={DATE_INPUT}
          />
        </label>
      </div>

      <label className="relative block">
        <span className="sr-only">Buscar</span>
        <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
        <input
          type="search"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Buscar cámara, nodo, salida u observación…"
          className={`${DATE_INPUT} pl-8`}
        />
      </label>
    </div>
  );
}
