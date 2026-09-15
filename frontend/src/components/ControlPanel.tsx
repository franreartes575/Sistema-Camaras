"use client";

import type {
  ClusterParams,
  ColumnMapping,
  CoordOrder,
  OptimizeResponse,
  ProviderChoice,
  RouteParams,
  UploadExcelResponse,
} from "@/lib/api";
import { NOISE_INK, SERIES_BASE, SERIES_SELECTED } from "@/lib/vizTokens";

type Props = {
  upload: UploadExcelResponse | null;
  mapping: ColumnMapping;
  params: ClusterParams;
  routing: RouteParams;
  result: OptimizeResponse | null;
  loading: boolean;
  error: string | null;
  selectedCluster: number | null;
  onFile: (file: File) => void;
  onMappingChange: (mapping: ColumnMapping) => void;
  onParamsChange: (params: ClusterParams) => void;
  onRoutingChange: (routing: RouteParams) => void;
  onOptimize: () => void;
  onSelectCluster: (cluster: number | null) => void;
};

/** Formatea metros como km con un decimal, o como metros redondos si es corto. */
function formatDistance(meters: number | null): string {
  // null significa que la red vial no conecta el tramo, no que mida cero.
  if (meters === null) return "sin conexión";
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
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

export default function ControlPanel({
  upload,
  mapping,
  params,
  routing,
  result,
  loading,
  error,
  selectedCluster,
  onFile,
  onMappingChange,
  onParamsChange,
  onRoutingChange,
  onOptimize,
  onSelectCluster,
}: Props) {
  const columns = upload?.columns ?? [];
  const hasCoords =
    mapping.mode === "single"
      ? Boolean(mapping.col_coords)
      : Boolean(mapping.col_lat && mapping.col_lon);
  const canOptimize = Boolean(mapping.col_id) && hasCoords && !loading;

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
              Agrupamiento
            </h2>
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
          </div>

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
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                id="round-trip"
                type="checkbox"
                checked={routing.round_trip}
                onChange={(event) =>
                  onRoutingChange({ ...routing, round_trip: event.target.checked })
                }
                className="accent-sky-500"
              />
              Volver al punto de partida
            </label>
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
            >
              {loading ? "Optimizando…" : "Optimizar recorridos"}
            </button>
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
              return (
                <li key={route.cluster_id}>
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
                      <span className="font-medium">Cluster {route.cluster_id}</span>
                      <span className="text-xs text-slate-400">
                        {route.stop_count} paradas ·{" "}
                        {formatDistance(route.total_distance_m)}
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
