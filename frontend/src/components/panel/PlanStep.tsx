"use client";

/** Paso 5: el plan — días con su fecha, totales y exportación a Excel. */

import type { RegistroStatus } from "@/components/ControlPanel";
import { BUTTON, INPUT_CLASS, Notice, Stat, Toggle } from "@/components/ui/controls";
import { IconCalendar, IconCheck, IconDatabase, IconDownload } from "@/components/ui/icons";
import type { ClusterRoute, OptimizeResponse } from "@/lib/api";
import { formatDistance, formatDuration, formatWeekday } from "@/lib/format";
import { routeKey } from "@/lib/planDates";
import { dayColor } from "@/lib/vizTokens";

type Props = {
  result: OptimizeResponse;
  routeDates: Record<string, string>;
  planStart: string;
  skipWeekends: boolean;
  selectedCluster: number | null;
  selectedDay: number | null;
  isExporting: boolean;
  onPlanStartChange: (iso: string) => void;
  onSkipWeekendsChange: (skip: boolean) => void;
  onRouteDateChange: (key: string, iso: string) => void;
  onSelectRoute: (cluster: number | null, day: number | null) => void;
  onExport: () => void;
  registroStatus: RegistroStatus;
  savedPlanName: string | null;
  isSavingPlan: boolean;
  registroNotice: { tone: "warn" | "error"; text: string } | null;
  onSaveToRegistry: () => void;
  onOpenRegistry: () => void;
};

/** Si el plan está guardado en el registro y cómo guardarlo o actualizarlo. */
function RegistroBox({
  status,
  planName,
  isSaving,
  notice,
  onSave,
  onOpen,
}: {
  status: RegistroStatus;
  planName: string | null;
  isSaving: boolean;
  notice: { tone: "warn" | "error"; text: string } | null;
  onSave: () => void;
  onOpen: () => void;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-slate-800 p-3">
      <div className="flex items-start gap-2.5">
        <span
          className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${
            status === "saved" ? "bg-emerald-500/15 text-emerald-300" : "bg-slate-800 text-slate-400"
          }`}
        >
          {status === "saved" ? <IconCheck className="h-4 w-4" /> : <IconDatabase className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1 text-xs leading-relaxed">
          {status === "saved" && (
            <>
              <p className="font-medium text-slate-100">Guardado en el registro</p>
              <p className="truncate text-slate-500">{planName}</p>
            </>
          )}
          {status === "outdated" && (
            <>
              <p className="font-medium text-amber-200">El plan cambió desde que se guardó</p>
              <p className="truncate text-slate-500">{planName}</p>
              <p className="text-slate-500">Al exportar se actualiza solo, o actualizalo ahora.</p>
            </>
          )}
          {status === "unsaved" && (
            <>
              <p className="font-medium text-slate-200">Todavía no está en el registro</p>
              <p className="text-slate-500">Se guarda solo al exportar el Excel.</p>
            </>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1">
        {status !== "saved" && (
          <button type="button" onClick={onSave} disabled={isSaving} className={BUTTON.ghost}>
            {isSaving ? "Guardando…" : status === "outdated" ? "Actualizar registro" : "Guardar sin exportar"}
          </button>
        )}
        <button type="button" onClick={onOpen} className={BUTTON.ghost}>
          Ver el registro
        </button>
      </div>
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
    </div>
  );
}

function PlanTotals({ result }: { result: OptimizeResponse }) {
  const { routes, stats } = result;
  const seconds = routes.reduce((sum, route) => sum + route.total_duration_s, 0);
  const meters = routes.reduce((sum, route) => sum + route.total_distance_m, 0);
  const cameras = routes.reduce((sum, route) => sum + route.stop_count, 0);
  const average = routes.length ? seconds / routes.length : 0;
  return (
    <>
      <dl className="grid grid-cols-3 gap-2">
        <Stat label="Días" value={routes.length} />
        <Stat label="Cámaras" value={cameras} />
        <Stat
          label={stats.done_rows > 0 ? "Hechas" : "Descart."}
          value={stats.done_rows > 0 ? stats.done_rows : stats.discarded_rows}
          tone={stats.done_rows > 0 ? "muted" : stats.discarded_rows > 0 ? "warn" : "muted"}
        />
      </dl>
      <p className="text-xs leading-relaxed text-slate-400">
        <span className="font-medium text-slate-200">{formatDuration(seconds)}</span> en total ·{" "}
        {formatDuration(average)} por día · {formatDistance(meters)}{" "}
        {result.is_road_network ? (
          <span className="text-emerald-400">por calle</span>
        ) : (
          <span className="text-amber-300">en línea recta</span>
        )}
      </p>
    </>
  );
}

function DayItem({
  route,
  date,
  isActive,
  onSelect,
  onDateChange,
}: {
  route: ClusterRoute;
  date: string | undefined;
  isActive: boolean;
  onSelect: () => void;
  onDateChange: (iso: string) => void;
}) {
  return (
    <li
      className={`overflow-hidden rounded-lg border transition ${
        isActive ? "border-slate-500 bg-slate-800/70" : "border-slate-800 bg-slate-900 hover:border-slate-700"
      }`}
    >
      <div className="flex items-stretch">
        <span aria-hidden="true" className="w-1 shrink-0" style={{ backgroundColor: dayColor(route.vehicle_day) }} />
        <button type="button" onClick={onSelect} aria-pressed={isActive} className="min-w-0 flex-1 px-3 py-2 text-left">
          <span className="flex items-baseline gap-2">
            <span className="text-sm font-semibold text-slate-50">Día {route.vehicle_day}</span>
            {date && <span className="text-xs capitalize text-slate-400">{formatWeekday(date)}</span>}
          </span>
          <span className="block text-xs text-slate-500">
            {route.stop_count} cám. · {formatDistance(route.total_distance_m)} ·{" "}
            {formatDuration(route.total_duration_s)}
            {route.has_unreachable_legs && (
              <span className="ml-1 text-amber-400" title="Hay tramos sin conexión vial: el total subestima el real.">*</span>
            )}
          </span>
        </button>
        <input
          type="date"
          value={date ?? ""}
          aria-label={`Fecha del día ${route.vehicle_day}`}
          onChange={(event) => onDateChange(event.target.value)}
          className="my-2 mr-2 w-[7.6rem] shrink-0 rounded-md border border-slate-700 bg-slate-950 px-1 text-xs text-slate-200 [color-scheme:dark] focus:border-sky-400 focus:outline-none"
        />
      </div>
      {isActive && (
        <ol className="space-y-1 border-t border-slate-700/60 px-3 py-2 text-xs">
          {route.stops.map((stop) => (
            <li key={stop.camera_id} className="flex items-baseline justify-between gap-2">
              <span className="truncate text-slate-300">
                <span className="mr-1.5 font-mono text-slate-500">
                  {route.vehicle_day}·{stop.order + 1}
                </span>
                {stop.label ?? stop.camera_id}
              </span>
              {stop.order > 0 && (
                <span className="shrink-0 tabular-nums text-slate-500">
                  {formatDistance(stop.distance_from_previous_m)}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </li>
  );
}

export default function PlanStep({
  result,
  routeDates,
  planStart,
  skipWeekends,
  selectedCluster,
  selectedDay,
  isExporting,
  onPlanStartChange,
  onSkipWeekendsChange,
  onRouteDateChange,
  onSelectRoute,
  onExport,
  registroStatus,
  savedPlanName,
  isSavingPlan,
  registroNotice,
  onSaveToRegistry,
  onOpenRegistry,
}: Props) {
  if (result.routes.length === 0) {
    return <Notice tone="warn">No se pudo armar ningún recorrido con estas reglas.</Notice>;
  }
  const clusterCount = new Set(result.routes.flatMap((route) => route.cluster_ids)).size;

  return (
    <>
      <PlanTotals result={result} />

      <div className="space-y-2.5 rounded-lg border border-slate-800 p-3">
        <label className="flex items-center justify-between gap-3 text-sm text-slate-300">
          <span className="flex items-center gap-1.5">
            <IconCalendar className="h-4 w-4 text-slate-400" /> Primer día
          </span>
          <input
            type="date"
            value={planStart}
            onChange={(event) => onPlanStartChange(event.target.value)}
            className={`${INPUT_CLASS} w-auto py-1 [color-scheme:dark]`}
          />
        </label>
        <Toggle label="Saltear sábados y domingos" checked={skipWeekends} onChange={onSkipWeekendsChange} />
        <p className="text-xs leading-relaxed text-slate-500">
          Un día hábil por recorrido, en orden. Podés cambiar la fecha de cada día
          en la lista.
        </p>
      </div>

      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Recorridos{clusterCount > 1 ? ` · ${clusterCount} clusters` : ""}
        </h3>
        {selectedCluster !== null && (
          <button type="button" onClick={() => onSelectRoute(null, null)} className={BUTTON.ghost}>
            Ver todos
          </button>
        )}
      </div>
      <ul className="space-y-1.5">
        {result.routes.map((route) => {
          const key = routeKey(route);
          const isActive = route.cluster_id === selectedCluster && route.vehicle_day === selectedDay;
          return (
            <DayItem
              key={key}
              route={route}
              date={routeDates[key]}
              isActive={isActive}
              onSelect={() => (isActive ? onSelectRoute(null, null) : onSelectRoute(route.cluster_id, route.vehicle_day))}
              onDateChange={(iso) => onRouteDateChange(key, iso)}
            />
          );
        })}
      </ul>

      <button type="button" onClick={onExport} disabled={isExporting} className={BUTTON.primary}>
        <IconDownload className="h-4 w-4" />
        {isExporting ? "Generando Excel…" : "Exportar Excel de seguimiento"}
      </button>
      <p className="text-xs leading-relaxed text-slate-500">
        Los técnicos completan <b className="text-slate-400">Realizado</b>,{" "}
        <b className="text-slate-400">Observación</b> y el nodo. Después lo subís
        en el paso 1 (o en el Registro): se actualiza el avance, lo hecho se
        descarta y lo pendiente (más las filas nuevas que agregues) se vuelve a
        planificar.
      </p>
      <RegistroBox
        status={registroStatus}
        planName={savedPlanName}
        isSaving={isSavingPlan}
        notice={registroNotice}
        onSave={onSaveToRegistry}
        onOpen={onOpenRegistry}
      />

      {result.discarded.length > 0 && (
        <details className="text-xs text-slate-400">
          <summary className="cursor-pointer py-1 hover:text-slate-200">
            {result.discarded.length} fila(s) descartada(s) de la planilla
          </summary>
          <ul className="mt-1 space-y-0.5">
            {result.discarded.slice(0, 50).map((row) => (
              <li key={row.row}>
                Fila {row.row}: {row.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
