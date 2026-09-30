"use client";

import type {
  Cluster,
  ClusterParams,
  ClusterStart,
  ColumnMapping,
  CoordOrder,
  Depot,
  OptimizeResponse,
  ProcessResponse,
  ProviderChoice,
  RouteParams,
  UploadExcelResponse,
} from "@/lib/api";
import DepotEditor from "@/components/DepotEditor";
import { NOISE_INK, SERIES_BASE, SERIES_SELECTED } from "@/lib/vizTokens";

type Props = {
  upload: UploadExcelResponse | null;
  mapping: ColumnMapping;
  params: ClusterParams;
  routing: RouteParams;
  depots: Depot[];
  preview: ProcessResponse | null;
  clusterStarts: Record<number, ClusterStart>;
  result: OptimizeResponse | null;
  loading: boolean;
  error: string | null;
  selectedCluster: number | null;
  onFile: (file: File) => void;
  onMappingChange: (mapping: ColumnMapping) => void;
  onParamsChange: (params: ClusterParams) => void;
  onRoutingChange: (routing: RouteParams) => void;
  onDepotsChange: (depots: Depot[]) => void;
  onClusterStartsChange: (starts: Record<number, ClusterStart>) => void;
  onPreview: () => void;
  onOptimize: () => void;
  onSelectCluster: (cluster: number | null) => void;
};

/** Formatea metros como km con un decimal, o como metros redondos si es corto. */
function formatDistance(meters: number | null): string {
  // null significa que la red vial no conecta el tramo, no que mida cero.
  if (meters === null) return "sin conexión";
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
}

/** Formatea segundos como "Xh Ym" (o sólo minutos si dura menos de una hora). */
function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours === 0 ? `${minutes} min` : `${hours} h ${minutes} min`;
}

function Select({
  label,
  value,
  options,
  hint,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; text: string }[];
  hint?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-400">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.text}
          </option>
        ))}
      </select>
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

function Field({
  label,
  value,
  columns,
  optional,
  onChange,
}: {
  label: string;
  value: string;
  columns: string[];
  optional?: boolean;
  onChange: (value: string) => void;
}) {
  const options = [
    ...(optional ? [{ value: "", text: "—" }] : []),
    ...columns.map((column) => ({ value: column, text: column })),
  ];
  return (
    <Select
      label={optional ? `${label} (opcional)` : label}
      value={value}
      options={options}
      onChange={onChange}
    />
  );
}

function Slider({
  label,
  value,
  display,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  display: string;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 flex justify-between text-xs text-slate-400">
        <span>{label}</span>
        <span className="font-medium text-slate-200">{display}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-sky-500"
      />
    </label>
  );
}

/** Un cluster + el selector de su punto de partida (sede guardada o manual). */
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
  const matchedDepot = depots.find(
    (depot) =>
      start && depot.lat === start.lat && depot.lon === start.lon && depot.name === start.name,
  );
  const mode = start === undefined ? "" : matchedDepot ? matchedDepot.id : "custom";

  return (
    <li className="space-y-1.5 rounded-md bg-slate-900 p-2">
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span className="font-medium text-slate-200">Cluster {cluster.id}</span>
        <span>
          {cluster.size} cámaras · radio {cluster.radius_km.toFixed(1)} km
        </span>
      </div>
      <select
        value={mode}
        onChange={(event) => {
          const value = event.target.value;
          if (value === "custom") {
            onChange({
              lat: cluster.centroid_lat,
              lon: cluster.centroid_lon,
              name: null,
            });
            return;
          }
          const depot = depots.find((candidate) => candidate.id === value);
          if (depot) onChange({ lat: depot.lat, lon: depot.lon, name: depot.name });
        }}
        className="w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
      >
        <option value="" disabled>
          — elegir punto de partida —
        </option>
        {depots.map((depot) => (
          <option key={depot.id} value={depot.id}>
            {depot.name || "Sede sin nombre"}
          </option>
        ))}
        <option value="custom">Coordenadas personalizadas</option>
      </select>
      {mode === "custom" && start && (
        <div className="grid grid-cols-2 gap-2">
          <input
            type="number"
            step="0.0001"
            value={start.lat}
            onChange={(event) => onChange({ ...start, lat: Number(event.target.value) })}
            className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
          />
          <input
            type="number"
            step="0.0001"
            value={start.lon}
            onChange={(event) => onChange({ ...start, lon: Number(event.target.value) })}
            className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
          />
        </div>
      )}
    </li>
  );
}

export default function ControlPanel({
  upload,
  mapping,
  params,
  routing,
  depots,
  preview,
  clusterStarts,
  result,
  loading,
  error,
  selectedCluster,
  onFile,
  onMappingChange,
  onParamsChange,
  onRoutingChange,
  onDepotsChange,
  onClusterStartsChange,
  onPreview,
  onOptimize,
  onSelectCluster,
}: Props) {
  const columns = upload?.columns ?? [];
  const hasCoords =
    mapping.mode === "single"
      ? Boolean(mapping.col_coords)
      : Boolean(mapping.col_lat && mapping.col_lon);
  const canPreview = Boolean(mapping.col_id) && hasCoords && !loading;
  const allStartsAssigned =
    preview !== null &&
    preview.clusters.every((cluster) => clusterStarts[cluster.id] !== undefined);
  const canOptimize = allStartsAssigned && !loading;
  const missingStarts =
    preview?.clusters.filter((cluster) => clusterStarts[cluster.id] === undefined)
      .length ?? 0;
  // Visible bajo el botón: con sólo un `title` el motivo del bloqueo no se ve.
  const optimizeHint = !preview
    ? "Primero tocá «Agrupar cámaras»."
    : missingStarts > 0
      ? `Elegí el punto de partida de ${missingStarts} cluster(s) en «Punto de partida por cluster».`
      : null;

  const setClusterStart = (clusterId: number, start: ClusterStart) => {
    onClusterStartsChange({ ...clusterStarts, [clusterId]: start });
  };

  return (
    <div className="space-y-5">
      <div>
        <span className="mb-1.5 block text-xs font-medium text-slate-400">
          Planilla de cámaras
        </span>
        <input
          id="planilla"
          type="file"
          accept=".xlsx,.xlsm,.csv"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onFile(file);
          }}
          className="block w-full text-sm text-slate-300 file:mr-3 file:rounded-md file:border-0 file:bg-sky-600 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white hover:file:bg-sky-500"
        />
        {upload && (
          <p className="mt-1.5 text-xs text-slate-500">
            {upload.column_count} columnas · {upload.filename}
          </p>
        )}
      </div>

      {upload && (
        <>
          <div className="space-y-2.5 border-t border-slate-800 pt-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Mapeo de columnas
            </h2>
            <Field
              label="Identificador"
              value={mapping.col_id}
              columns={columns}
              onChange={(value) => onMappingChange({ ...mapping, col_id: value })}
            />

            <div className="grid grid-cols-2 gap-1 rounded-md bg-slate-900 p-1">
              {(
                [
                  ["split", "Dos columnas"],
                  ["single", "Una columna"],
                ] as const
              ).map(([value, text]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => onMappingChange({ ...mapping, mode: value })}
                  className={`rounded px-2 py-1 text-xs font-medium transition ${
                    mapping.mode === value
                      ? "bg-sky-600 text-white"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {text}
                </button>
              ))}
            </div>

            {mapping.mode === "split" ? (
              <div className="grid grid-cols-2 gap-2">
                <Field
                  label="Latitud"
                  value={mapping.col_lat}
                  columns={columns}
                  onChange={(value) => onMappingChange({ ...mapping, col_lat: value })}
                />
                <Field
                  label="Longitud"
                  value={mapping.col_lon}
                  columns={columns}
                  onChange={(value) => onMappingChange({ ...mapping, col_lon: value })}
                />
              </div>
            ) : (
              <>
                <Field
                  label="Coordenadas"
                  value={mapping.col_coords}
                  columns={columns}
                  onChange={(value) =>
                    onMappingChange({ ...mapping, col_coords: value })
                  }
                />
                <Select
                  label="Orden dentro de la celda"
                  value={mapping.coord_order}
                  options={[
                    { value: "auto", text: "Detectar automáticamente" },
                    { value: "latlon", text: "Latitud, Longitud" },
                    { value: "lonlat", text: "Longitud, Latitud" },
                  ]}
                  hint="La detección automática sólo resuelve el caso en que un valor excede ±90. Si ambos caben en el rango de latitud, asume lat,lon — verificá en el mapa que los puntos caigan donde esperás."
                  onChange={(value) =>
                    onMappingChange({ ...mapping, coord_order: value as CoordOrder })
                  }
                />
              </>
            )}
            <Field
              label="Descripción"
              value={mapping.col_label ?? ""}
              columns={columns}
              optional
              onChange={(value) => onMappingChange({ ...mapping, col_label: value })}
            />
          </div>

          <div className="space-y-3 border-t border-slate-800 pt-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Agrupamiento de cámaras remotas
            </h2>
            <p className="text-xs text-slate-500">
              Sólo afecta a cámaras sin ninguna sede alcanzable: cómo se
              agrupan entre sí por cercanía antes de armarles recorridos.
            </p>
            <Slider
              label="Radio de vecindad"
              value={params.eps_km}
              display={`${params.eps_km} km`}
              min={0.1}
              max={20}
              step={0.1}
              onChange={(eps_km) => onParamsChange({ ...params, eps_km })}
            />
            <Slider
              label="Mínimo por cluster"
              value={params.min_samples}
              display={String(params.min_samples)}
              min={1}
              max={20}
              step={1}
              onChange={(min_samples) => onParamsChange({ ...params, min_samples })}
            />
            <Slider
              label="Reasignación de ruido"
              value={params.noise_reassign_factor}
              display={`× ${params.noise_reassign_factor} eps`}
              min={0}
              max={10}
              step={0.5}
              onChange={(noise_reassign_factor) =>
                onParamsChange({ ...params, noise_reassign_factor })
              }
            />
            <button
              type="button"
              onClick={onPreview}
              disabled={!canPreview}
              className="w-full rounded-md bg-slate-700 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-600 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-500"
            >
              {loading ? "Agrupando…" : "Agrupar cámaras"}
            </button>
          </div>

          <DepotEditor depots={depots} onChange={onDepotsChange} />

          {preview && (
            <div className="space-y-2.5 border-t border-slate-800 pt-4">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Punto de partida por cluster
              </h2>
              {preview.clusters.length === 0 ? (
                <p className="text-xs text-slate-500">
                  No se formó ningún cluster con estos parámetros.
                </p>
              ) : (
                <ul className="space-y-2">
                  {preview.clusters.map((cluster) => (
                    <ClusterStartRow
                      key={cluster.id}
                      cluster={cluster}
                      depots={depots}
                      start={clusterStarts[cluster.id]}
                      onChange={(start) => setClusterStart(cluster.id, start)}
                    />
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className="space-y-3 border-t border-slate-800 pt-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Ruteo
            </h2>
            <Select
              label="Motor de distancias"
              value={routing.provider}
              options={[
                { value: "auto", text: "Automático (OSRM si está)" },
                { value: "osrm", text: "OSRM — distancias por calle" },
                { value: "haversine", text: "Línea recta" },
              ]}
              onChange={(value) =>
                onRoutingChange({ ...routing, provider: value as ProviderChoice })
              }
            />
            <Slider
              label="Presupuesto de jornada"
              value={routing.day_budget_s / 3600}
              display={`${(routing.day_budget_s / 3600).toFixed(1)} h`}
              min={1}
              max={16}
              step={0.5}
              onChange={(hours) =>
                onRoutingChange({ ...routing, day_budget_s: hours * 3600 })
              }
            />
            <Slider
              label="Cámaras por día"
              value={routing.max_stops_per_day}
              display={
                routing.max_stops_per_day === 0
                  ? "sin tope"
                  : `máx. ${routing.max_stops_per_day}`
              }
              min={0}
              max={30}
              step={1}
              onChange={(max_stops_per_day) =>
                onRoutingChange({ ...routing, max_stops_per_day })
              }
            />
            <Slider
              label="Tiempo de servicio por parada"
              value={routing.service_time_s / 60}
              display={`${routing.service_time_s / 60} min`}
              min={0}
              max={60}
              step={5}
              onChange={(minutes) =>
                onRoutingChange({ ...routing, service_time_s: minutes * 60 })
              }
            />
            <Slider
              label="Velocidad asumida sin OSRM"
              value={routing.average_speed_kmh}
              display={`${routing.average_speed_kmh} km/h`}
              min={10}
              max={120}
              step={5}
              onChange={(average_speed_kmh) =>
                onRoutingChange({ ...routing, average_speed_kmh })
              }
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
            <button
              type="button"
              onClick={onOptimize}
              disabled={!canOptimize}
              className="w-full rounded-md bg-sky-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-500"
              title={optimizeHint ?? undefined}
            >
              {loading ? "Optimizando…" : "Optimizar recorridos"}
            </button>
            {optimizeHint && !loading && (
              <p className="text-xs text-amber-300">{optimizeHint}</p>
            )}
          </div>
        </>
      )}

      {error && (
        <p className="rounded-md bg-red-950 px-3 py-2 text-sm text-red-300">{error}</p>
      )}

      {result?.warning && (
        <p className="rounded-md bg-amber-950 px-3 py-2 text-sm text-amber-200">
          {result.warning}
        </p>
      )}

      {result && (
        <div className="space-y-3 border-t border-slate-800 pt-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Resultado
          </h2>

          <dl className="grid grid-cols-2 gap-2">
            {(
              [
                ["Válidas", result.stats.valid_rows],
                ["Recorridos", result.routes.length],
                ["Sin cluster", result.stats.noise_count],
                ["Descartadas", result.stats.discarded_rows],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="rounded-md bg-slate-900 px-3 py-2">
                <dt className="text-xs text-slate-500">{label}</dt>
                <dd className="text-lg font-semibold text-slate-100">{value}</dd>
              </div>
            ))}
          </dl>

          <p className="text-xs text-slate-500">
            Distancias{" "}
            {result.is_road_network ? (
              <span className="text-emerald-400">reales por calle (OSRM)</span>
            ) : (
              <span className="text-amber-400">en línea recta</span>
            )}
          </p>

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
            {(
              [
                [SERIES_SELECTED, "Seleccionado"],
                [SERIES_BASE, "En cluster"],
                [NOISE_INK, "Ruido"],
              ] as const
            ).map(([color, label]) => (
              <span key={label} className="flex items-center gap-1.5">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full ring-1 ring-white"
                  style={{ backgroundColor: color }}
                />
                {label}
              </span>
            ))}
          </div>

          <ul className="max-h-72 space-y-1 overflow-y-auto">
            {result.routes.map((route) => {
              const active = route.cluster_id === selectedCluster;
              const cluster = result.clusters.find((c) => c.id === route.cluster_id);
              return (
                <li key={`${route.cluster_id}-${route.vehicle_day}`}>
                  <button
                    type="button"
                    onClick={() => onSelectCluster(active ? null : route.cluster_id)}
                    className={`w-full rounded-md px-3 py-1.5 text-left text-sm transition ${
                      active
                        ? "bg-orange-500/20 text-orange-200 ring-1 ring-orange-500/50"
                        : "bg-slate-900 text-slate-300 hover:bg-slate-800"
                    }`}
                  >
                    <span className="flex items-center justify-between">
                      <span className="font-medium">
                        Cluster {route.cluster_id}
                        {route.vehicle_day_count > 1 &&
                          ` · día ${route.vehicle_day}/${route.vehicle_day_count}`}
                      </span>
                      <span className="text-xs text-slate-400">
                        {route.stop_count} paradas ·{" "}
                        {formatDistance(route.total_distance_m)} ·{" "}
                        {formatDuration(route.total_duration_s)}
                        {route.has_unreachable_legs && (
                          <span
                            className="ml-1 text-amber-400"
                            title="Incluye tramos que la red vial no conecta: el total subestima el recorrido real."
                          >
                            *
                          </span>
                        )}
                      </span>
                    </span>
                    {route.start_name && (
                      <span className="block text-[11px] text-slate-500">
                        Desde {route.start_name}
                        {cluster && ` · radio del cluster ${cluster.radius_km.toFixed(1)} km`}
                      </span>
                    )}
                  </button>

                  {active && (
                    <ol className="mt-1 space-y-0.5 pl-3 text-xs text-slate-400">
                      {route.stops.map((stop) => (
                        <li key={stop.camera_id} className="flex justify-between gap-2">
                          <span className="truncate">
                            {stop.order + 1}. {stop.label ?? stop.camera_id}
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
            })}
          </ul>

          {result.discarded.length > 0 && (
            <details className="text-xs text-slate-400">
              <summary className="cursor-pointer py-1 hover:text-slate-200">
                {result.discarded.length} filas descartadas
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
        </div>
      )}
    </div>
  );
}
