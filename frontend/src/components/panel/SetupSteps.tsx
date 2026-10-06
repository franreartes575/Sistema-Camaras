"use client";

/**
 * Pasos 2 a 4: agrupar, elegir salidas y fijar las reglas del día. Son la
 * configuración previa al plan; el paso 5 (el plan en sí) vive en PlanStep.
 */

import DepotEditor from "@/components/DepotEditor";
import CoordinateField from "@/components/ui/CoordinateField";
import { BUTTON, Notice, Select, Slider, Toggle } from "@/components/ui/controls";
import IntegerField from "@/components/ui/IntegerField";
import type {
  Cluster,
  ClusterParams,
  ClusterStart,
  Depot,
  ProcessResponse,
  ProviderChoice,
  RouteParams,
} from "@/lib/api";

// ---------------------------------------------------------------- Paso 2

export function ClusterStep({
  params,
  preview,
  canPreview,
  isLoading,
  onParamsChange,
  onPreview,
}: {
  params: ClusterParams;
  preview: ProcessResponse | null;
  canPreview: boolean;
  isLoading: boolean;
  onParamsChange: (params: ClusterParams) => void;
  onPreview: () => void;
}) {
  return (
    <>
      <p className="text-xs leading-relaxed text-slate-500">
        Junta las cámaras cercanas entre sí; cada grupo (cluster) sale desde su
        propio punto de partida.
      </p>
      <Slider
        label="Radio de vecindad"
        value={params.eps_km}
        display={`${params.eps_km} km`}
        min={0.5}
        max={50}
        step={0.5}
        onChange={(eps_km) => onParamsChange({ ...params, eps_km })}
      />
      <details className="rounded-lg border border-slate-800 px-3 py-2 open:pb-3">
        <summary className="cursor-pointer select-none text-xs font-medium text-slate-400 hover:text-slate-200">
          Ajustes avanzados
        </summary>
        <div className="mt-3 space-y-3">
          <Slider
            label="Mínimo de cámaras por cluster"
            value={params.min_samples}
            display={String(params.min_samples)}
            min={1}
            max={20}
            step={1}
            onChange={(min_samples) => onParamsChange({ ...params, min_samples })}
          />
          <Slider
            label="Reasignar cámaras sueltas hasta"
            value={params.noise_reassign_factor}
            display={`× ${params.noise_reassign_factor} radio`}
            min={0}
            max={10}
            step={0.5}
            onChange={(noise_reassign_factor) => onParamsChange({ ...params, noise_reassign_factor })}
          />
        </div>
      </details>
      <button type="button" onClick={onPreview} disabled={!canPreview} className={BUTTON.primary}>
        {isLoading ? "Agrupando…" : preview ? "Volver a agrupar" : "Agrupar cámaras"}
      </button>
      {preview && preview.stats.done_rows > 0 && (
        <Notice tone="info">
          {preview.stats.done_rows} cámara(s) ya figuran como realizadas y no se
          vuelven a planificar.
        </Notice>
      )}
    </>
  );
}

// ---------------------------------------------------------------- Paso 3

const SELECT_CLASS =
  "w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-sky-400 focus:outline-none";

function sameStart(a: ClusterStart | undefined, b: ClusterStart | undefined): boolean {
  if (!a || !b) return a === b;
  return a.lat === b.lat && a.lon === b.lon && a.name === b.name;
}

/**
 * Elige un punto de partida: una sede guardada o coordenadas sueltas.
 * `fallback` son las coordenadas con que arranca la opción personalizada.
 * `mixed` marca que no hay un único valor (la salida general cuando cada
 * cluster tiene la suya).
 */
function StartPicker({
  label,
  start,
  depots,
  fallback,
  mixed = false,
  onChange,
}: {
  label: string;
  start: ClusterStart | undefined;
  depots: Depot[];
  fallback: ClusterStart;
  mixed?: boolean;
  onChange: (start: ClusterStart) => void;
}) {
  const matchedDepot = depots.find(
    (depot) =>
      start && depot.lat === start.lat && depot.lon === start.lon && depot.name === start.name,
  );
  const mode = mixed ? "mixed" : start === undefined ? "" : matchedDepot ? String(matchedDepot.id) : "custom";

  return (
    <>
      <select
        value={mode}
        aria-label={label}
        onChange={(event) => {
          const value = event.target.value;
          if (value === "custom") {
            onChange(fallback);
            return;
          }
          const depot = depots.find((candidate) => String(candidate.id) === value);
          if (depot) onChange({ lat: depot.lat, lon: depot.lon, name: depot.name });
        }}
        className={SELECT_CLASS}
      >
        <option value="" disabled>
          — elegir punto de partida —
        </option>
        {mixed && (
          <option value="mixed" disabled>
            Distinta en cada cluster
          </option>
        )}
        {depots.map((depot) => (
          <option key={depot.id} value={depot.id}>
            {depot.name || "Sede sin nombre"}
          </option>
        ))}
        <option value="custom">Coordenadas personalizadas</option>
      </select>
      {mode === "custom" && start && (
        <CoordinateField
          label="Coordenadas de la salida"
          value={{ lat: start.lat, lon: start.lon }}
          onChange={(coords) => onChange({ ...start, ...coords })}
        />
      )}
    </>
  );
}

function ClusterStartRow({
  cluster,
  depots,
  start,
  onChange,
}: {
  cluster: Cluster;
  depots: Depot[];
  start: ClusterStart | undefined;
  onChange: (start: ClusterStart) => void;
}) {
  return (
    <li className="space-y-2 rounded-lg bg-slate-900 p-3">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-semibold text-slate-100">Cluster {cluster.id}</span>
        <span className="text-slate-500">
          {cluster.size} cámaras · radio {cluster.radius_km.toFixed(1)} km
        </span>
      </div>
      <StartPicker
        label={`Punto de partida del cluster ${cluster.id}`}
        start={start}
        depots={depots}
        fallback={{ lat: cluster.centroid_lat, lon: cluster.centroid_lon, name: null }}
        onChange={onChange}
      />
    </li>
  );
}

export function StartsStep({
  depots,
  canEditDepots,
  preview,
  clusterStarts,
  onDepotsChanged,
  onClusterStartsChange,
}: {
  depots: Depot[];
  canEditDepots: boolean;
  preview: ProcessResponse;
  clusterStarts: Record<number, ClusterStart>;
  onDepotsChanged: () => void;
  onClusterStartsChange: (starts: Record<number, ClusterStart>) => void;
}) {
  const { clusters } = preview;
  // Salida general: lo que comparten todos los clusters. Si difieren, se
  // muestra como "distinta en cada cluster" y elegir una la pisa en todos.
  const sample = clusters.length > 0 ? clusterStarts[clusters[0].id] : undefined;
  const allSame = clusters.every((cluster) => sameStart(clusterStarts[cluster.id], sample));
  const mixed = !allSame && clusters.some((cluster) => clusterStarts[cluster.id] !== undefined);
  const biggest = clusters.reduce((a, b) => (b.size > a.size ? b : a), clusters[0]);

  return (
    <>
      {clusters.length === 0 ? (
        <Notice tone="warn">No se formó ningún cluster con estos parámetros.</Notice>
      ) : (
        <>
          {clusters.length > 1 && (
            <div className="space-y-2 rounded-lg border border-sky-500/30 bg-sky-500/5 p-3">
              <div className="text-xs font-semibold text-slate-100">Salida general</div>
              <p className="text-xs leading-relaxed text-slate-400">
                Se aplica a todos los clusters. Después podés cambiar la de uno solo.
              </p>
              <StartPicker
                label="Punto de partida general"
                start={allSame ? sample : undefined}
                depots={depots}
                fallback={{ lat: biggest.centroid_lat, lon: biggest.centroid_lon, name: null }}
                mixed={mixed}
                onChange={(start) =>
                  onClusterStartsChange(
                    Object.fromEntries(clusters.map((cluster) => [cluster.id, start])) as Record<
                      number,
                      ClusterStart
                    >,
                  )
                }
              />
            </div>
          )}
          <ul className="space-y-2">
            {clusters.map((cluster) => (
              <ClusterStartRow
                key={cluster.id}
                cluster={cluster}
                depots={depots}
                start={clusterStarts[cluster.id]}
                onChange={(start) => onClusterStartsChange({ ...clusterStarts, [cluster.id]: start })}
              />
            ))}
          </ul>
        </>
      )}
      <DepotEditor depots={depots} canEdit={canEditDepots} onChanged={onDepotsChanged} />
    </>
  );
}

// ---------------------------------------------------------------- Paso 4

const MAX_STOPS_PER_DAY = 100;

/** Mínimo por día sin superar el tope: si lo supera, el tope sube con él. */
function withMinStops(routing: RouteParams, min: number): RouteParams {
  const max = routing.max_stops_per_day;
  return { ...routing, min_stops_per_day: min, max_stops_per_day: max !== 0 && min > max ? min : max };
}

/** Tope sin quedar por debajo del mínimo: si baja de él, lo arrastra. */
function withMaxStops(routing: RouteParams, max: number): RouteParams {
  const min = routing.min_stops_per_day;
  return { ...routing, max_stops_per_day: max, min_stops_per_day: max !== 0 && min > max ? max : min };
}

export function RulesStep({
  routing,
  canOptimize,
  isLoading,
  hasResult,
  onRoutingChange,
  onOptimize,
}: {
  routing: RouteParams;
  canOptimize: boolean;
  isLoading: boolean;
  hasResult: boolean;
  onRoutingChange: (routing: RouteParams) => void;
  onOptimize: () => void;
}) {
  const { min_stops_per_day: min, max_stops_per_day: max } = routing;
  return (
    <>
      <Slider
        label="Duración de la jornada"
        value={routing.day_budget_s / 3600}
        display={`${(routing.day_budget_s / 3600).toFixed(1)} h`}
        min={1}
        max={16}
        step={0.5}
        onChange={(hours) => onRoutingChange({ ...routing, day_budget_s: hours * 3600 })}
      />
      <div className="grid grid-cols-2 gap-3">
        <IntegerField
          label="Mín. cámaras/día"
          value={min}
          max={MAX_STOPS_PER_DAY}
          emptyText="—"
          onChange={(value) => onRoutingChange(withMinStops(routing, value))}
        />
        <IntegerField
          label="Máx. cámaras/día"
          value={max}
          max={MAX_STOPS_PER_DAY}
          emptyText="sin tope"
          onChange={(value) => onRoutingChange(withMaxStops(routing, value))}
        />
      </div>
      <p className="-mt-1 text-xs leading-relaxed text-slate-500">
        Con mínimo y máximo iguales, cada día lleva exactamente esa cantidad. El
        día con menos cámaras queda siempre último, para sumarle pendientes.
      </p>
      <Toggle
        label="Juntar clusters con la misma salida en un mismo día"
        checked={routing.merge_clusters}
        onChange={(merge_clusters) => onRoutingChange({ ...routing, merge_clusters })}
      />
      <p className="-mt-1 text-xs leading-relaxed text-slate-500">
        Sólo se juntan los clusters que comparten el punto de partida, y si entran
        en la jornada. Evita días casi vacíos por clusters chicos.
      </p>
      <Slider
        label="Tiempo por cámara"
        value={routing.service_time_s / 60}
        display={`${routing.service_time_s / 60} min`}
        min={0}
        max={60}
        step={5}
        onChange={(minutes) => onRoutingChange({ ...routing, service_time_s: minutes * 60 })}
      />
      <details className="rounded-lg border border-slate-800 px-3 py-2 open:pb-3">
        <summary className="cursor-pointer select-none text-xs font-medium text-slate-400 hover:text-slate-200">
          Motor de cálculo
        </summary>
        <div className="mt-3 space-y-3">
          <Select
            label="Distancias"
            value={routing.provider}
            options={[
              { value: "auto", text: "Automático (por calle si OSRM está)" },
              { value: "osrm", text: "Por calle (OSRM)" },
              { value: "haversine", text: "Línea recta" },
            ]}
            onChange={(value) => onRoutingChange({ ...routing, provider: value as ProviderChoice })}
          />
          <Slider
            label="Velocidad sin OSRM"
            value={routing.average_speed_kmh}
            display={`${routing.average_speed_kmh} km/h`}
            min={10}
            max={120}
            step={5}
            onChange={(average_speed_kmh) => onRoutingChange({ ...routing, average_speed_kmh })}
          />
          <Slider
            label="Tiempo de cálculo"
            value={routing.time_limit_s}
            display={`${routing.time_limit_s} s`}
            min={1}
            max={30}
            step={1}
            onChange={(time_limit_s) => onRoutingChange({ ...routing, time_limit_s })}
          />
        </div>
      </details>
      <button type="button" onClick={onOptimize} disabled={!canOptimize} className={BUTTON.primary}>
        {isLoading ? "Calculando recorridos…" : hasResult ? "Recalcular recorridos" : "Calcular recorridos"}
      </button>
    </>
  );
}
