"use client";

/**
 * Paso 1, modo catálogo: elegir las cámaras a planificar sin subir planilla.
 *
 * Tres formas de armar la selección, combinables: una lista desplegable con
 * todo el catálogo (filtrable por localidad, por cercanía a una sede y por
 * texto), pegar IDs de a muchos, y agregar de una vez todo lo filtrado. La
 * selección vive en la página: sobrevive a plegar el paso y la puede armar
 * también el Inicio ("planificar esta localidad").
 */

import { useMemo, useState } from "react";

import { BUTTON, INPUT_CLASS, Notice } from "@/components/ui/controls";
import { IconChevron, IconClipboard, IconCopy, IconSearch, IconX } from "@/components/ui/icons";
import type { Depot } from "@/lib/api";
import { parseIds, type CatalogCamera } from "@/lib/catalogo";
import { formatShortDate } from "@/lib/format";
import { haversineKm } from "@/lib/geo";

// Más filas que esto en la lista no se leen: se pide afinar el filtro.
const MAX_LISTED = 300;
// Chips de la selección a la vista antes de resumir.
const MAX_CHIPS = 40;

type Props = {
  cameras: CatalogCamera[] | null;
  error: string | null;
  depots: Depot[];
  selection: string[];
  isLoading: boolean;
  onSelectionChange: (ids: string[]) => void;
  onPlan: () => void;
  onRetry: () => void;
};

/** Minúsculas y sin acentos: "Orán" se encuentra escribiendo "oran". */
export function searchable(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function CameraStatus({ camera }: { camera: CatalogCamera }) {
  if (camera.last_status === "pendiente" || camera.last_status === "no_realizada") {
    return <span className="text-amber-300">falta {camera.last_planned ? `(${formatShortDate(camera.last_planned)})` : ""}</span>;
  }
  if (camera.last_visit) return <span>visitada {formatShortDate(camera.last_visit)}</span>;
  return <span>sin visitas</span>;
}

export default function CatalogPicker({
  cameras,
  error,
  depots,
  selection,
  isLoading,
  onSelectionChange,
  onPlan,
  onRetry,
}: Props) {
  const [query, setQuery] = useState("");
  const [localities, setLocalities] = useState<string[]>([]);
  const [depotId, setDepotId] = useState("");
  const [radiusKm, setRadiusKm] = useState(15);
  const [listOpen, setListOpen] = useState(false);
  const [pasted, setPasted] = useState("");
  const [pasteResult, setPasteResult] = useState<{ added: number; repeated: number; missing: string[] } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const all = useMemo(() => cameras ?? [], [cameras]);
  const byId = useMemo(() => new Map(all.map((camera) => [camera.id, camera])), [all]);
  const selected = useMemo(() => new Set(selection), [selection]);

  const localityCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const camera of all) counts.set(camera.locality, (counts.get(camera.locality) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "es"));
  }, [all]);

  const depot = depots.find((candidate) => String(candidate.id) === depotId) ?? null;
  const distances = useMemo(() => {
    if (!depot) return null;
    return new Map(all.map((camera) => [camera.id, haversineKm(depot.lat, depot.lon, camera.lat, camera.lon)]));
  }, [all, depot]);

  const filtered = useMemo(() => {
    const words = searchable(query).split(/\s+/).filter(Boolean);
    const wanted = new Set(localities);
    const list = all.filter((camera) => {
      if (wanted.size > 0 && !wanted.has(camera.locality)) return false;
      if (distances && (distances.get(camera.id) ?? Infinity) > radiusKm) return false;
      if (words.length === 0) return true;
      const text = searchable([camera.id, camera.label, camera.node, camera.locality].filter(Boolean).join(" "));
      return words.every((word) => text.includes(word));
    });
    return distances
      ? list.sort((a, b) => (distances.get(a.id) ?? 0) - (distances.get(b.id) ?? 0))
      : list.sort((a, b) => a.locality.localeCompare(b.locality, "es") || a.id.localeCompare(b.id, "es", { numeric: true }));
  }, [all, localities, distances, radiusKm, query]);

  const filteredSelected = filtered.filter((camera) => selected.has(camera.id)).length;
  const isFiltering = query.trim() !== "" || localities.length > 0 || depot !== null;

  const toggle = (id: string) =>
    onSelectionChange(selected.has(id) ? selection.filter((other) => other !== id) : [...selection, id]);

  const addFiltered = () => {
    const extra = filtered.map((camera) => camera.id).filter((id) => !selected.has(id));
    onSelectionChange([...selection, ...extra]);
  };

  const removeFiltered = () => {
    const out = new Set(filtered.map((camera) => camera.id));
    onSelectionChange(selection.filter((id) => !out.has(id)));
  };

  const addPasted = () => {
    const ids = parseIds(pasted);
    const missing: string[] = [];
    const extra: string[] = [];
    let repeated = 0;
    for (const id of ids) {
      if (!byId.has(id)) missing.push(id);
      else if (selected.has(id) || extra.includes(id)) repeated += 1;
      else extra.push(id);
    }
    onSelectionChange([...selection, ...extra]);
    setPasteResult({ added: extra.length, repeated, missing });
    // Lo que no se encontró queda en el cuadro para corregirlo.
    setPasted(missing.join("\n"));
  };

  const copySelection = () => {
    // Uno por línea: pegado en Excel, queda una columna.
    navigator.clipboard.writeText(selection.join("\n")).then(
      () => setCopied(`${selection.length} ID(s) copiados`),
      () => setCopied("El navegador no dejó copiar: seleccioná y copiá a mano"),
    );
    window.setTimeout(() => setCopied(null), 3000);
  };

  if (error && !cameras) {
    return (
      <div className="space-y-2">
        <Notice tone="error">No se pudo leer el catálogo: {error}</Notice>
        <button type="button" onClick={onRetry} className={BUTTON.secondary}>
          Reintentar
        </button>
      </div>
    );
  }
  if (!cameras) return <p className="text-sm text-slate-500">Leyendo el catálogo…</p>;
  if (all.length === 0) {
    return (
      <Notice tone="info">
        Todavía no hay cámaras en el catálogo. Un administrador las carga desde
        <b> Inicio</b>; mientras, podés subir una planilla.
      </Notice>
    );
  }

  const localityLabel =
    localities.length === 0
      ? "Todas"
      : localities.length <= 2
        ? localities.join(", ")
        : `${localities.slice(0, 2).join(", ")} y ${localities.length - 2} más`;

  return (
    <div className="space-y-3">
      {/* ------------------------------------------------ Filtros */}
      <div className="space-y-2 rounded-lg border border-slate-800 p-2.5">
        <label className="relative block">
          <span className="sr-only">Buscar cámaras</span>
          <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="ID, dirección, nodo o localidad"
            className={`${INPUT_CLASS} pl-8`}
          />
        </label>

        <details className="group rounded-lg bg-slate-900">
          <summary className="flex cursor-pointer select-none items-center justify-between gap-2 px-2.5 py-2 text-xs">
            <span className="text-slate-400">
              Localidad: <span className="font-medium text-slate-100">{localityLabel}</span>
            </span>
            <IconChevron className="h-3.5 w-3.5 text-slate-500 transition group-open:rotate-180" />
          </summary>
          <div className="border-t border-slate-800 px-2.5 py-2">
            <div className="mb-1.5 flex gap-1">
              <button type="button" onClick={() => setLocalities([])} className={BUTTON.ghost}>
                Todas
              </button>
            </div>
            <ul className="max-h-52 space-y-0.5 overflow-y-auto pr-1">
              {localityCounts.map(([name, count]) => (
                <li key={name}>
                  <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-xs text-slate-300 hover:bg-slate-800">
                    <input
                      type="checkbox"
                      checked={localities.includes(name)}
                      onChange={() =>
                        setLocalities((prev) =>
                          prev.includes(name) ? prev.filter((other) => other !== name) : [...prev, name],
                        )
                      }
                      className="h-3.5 w-3.5 accent-sky-400"
                    />
                    <span className="min-w-0 flex-1 truncate">{name}</span>
                    <span className="tabular-nums text-slate-500">{count}</span>
                  </label>
                </li>
              ))}
            </ul>
          </div>
        </details>

        <div className="grid grid-cols-[minmax(0,1fr)_5.5rem] gap-2">
          <label className="block">
            <span className="mb-1 block text-xs text-slate-400">Cerca de la sede</span>
            <select value={depotId} onChange={(event) => setDepotId(event.target.value)} className={INPUT_CLASS}>
              <option value="">— cualquiera —</option>
              {depots.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-400">Radio (km)</span>
            <input
              type="number"
              min={1}
              max={600}
              value={radiusKm}
              disabled={!depot}
              onChange={(event) => setRadiusKm(Math.max(1, Number(event.target.value) || 1))}
              className={`${INPUT_CLASS} tabular-nums disabled:opacity-50`}
            />
          </label>
        </div>
        {depots.length === 0 && (
          <p className="text-[11px] text-slate-500">Sin sedes cargadas no se puede filtrar por cercanía.</p>
        )}
      </div>

      {/* ------------------------------------------------ Lista desplegable */}
      <div className="rounded-lg border border-slate-800">
        <button
          type="button"
          onClick={() => setListOpen((open) => !open)}
          aria-expanded={listOpen}
          className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm"
        >
          <span>
            <span className="font-medium text-slate-100">
              {isFiltering ? `${filtered.length} de ${all.length}` : `${all.length}`} cámaras
            </span>
            {filteredSelected > 0 && (
              <span className="text-xs text-slate-500"> · {filteredSelected} elegidas</span>
            )}
          </span>
          <IconChevron className={`h-4 w-4 text-slate-500 transition ${listOpen ? "rotate-180" : ""}`} />
        </button>
        {listOpen && (
          <div className="border-t border-slate-800">
            <div className="flex flex-wrap gap-1 px-2 py-1.5">
              <button
                type="button"
                onClick={addFiltered}
                disabled={filteredSelected === filtered.length}
                className={`${BUTTON.ghost} text-sky-300 disabled:opacity-40`}
              >
                + Agregar {isFiltering ? "las filtradas" : "todas"} ({filtered.length - filteredSelected})
              </button>
              {filteredSelected > 0 && (
                <button type="button" onClick={removeFiltered} className={BUTTON.ghost}>
                  Quitar {isFiltering ? "las filtradas" : "todas"} ({filteredSelected})
                </button>
              )}
            </div>
            {filtered.length === 0 ? (
              <p className="px-3 pb-3 text-xs text-slate-500">Ninguna cámara cumple los filtros.</p>
            ) : (
              <ul className="max-h-72 overflow-y-auto border-t border-slate-800/70">
                {filtered.slice(0, MAX_LISTED).map((camera) => (
                  <li key={camera.id}>
                    <label className="flex cursor-pointer items-start gap-2 px-3 py-1.5 hover:bg-slate-900">
                      <input
                        type="checkbox"
                        checked={selected.has(camera.id)}
                        onChange={() => toggle(camera.id)}
                        className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-sky-400"
                      />
                      <span className="min-w-0 flex-1 text-xs">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="truncate font-mono font-medium text-slate-100">{camera.id}</span>
                          {distances && (
                            <span className="shrink-0 tabular-nums text-slate-400">
                              {(distances.get(camera.id) ?? 0).toFixed(1)} km
                            </span>
                          )}
                        </span>
                        <span className="block truncate text-slate-500">
                          {camera.locality}
                          {camera.label ? ` · ${camera.label}` : ""} · <CameraStatus camera={camera} />
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
            {filtered.length > MAX_LISTED && (
              <p className="border-t border-slate-800 px-3 py-1.5 text-[11px] text-slate-500">
                Se muestran {MAX_LISTED} de {filtered.length}: refiná el filtro para ver el resto (agregar
                las filtradas las suma todas).
              </p>
            )}
          </div>
        )}
      </div>

      {/* ------------------------------------------------ Pegar IDs */}
      <details className="group rounded-lg border border-slate-800 px-3 py-2 open:pb-3">
        <summary className="flex cursor-pointer select-none items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-slate-200">
          <IconClipboard className="h-3.5 w-3.5" /> Pegar IDs
        </summary>
        <div className="mt-2 space-y-2">
          <textarea
            value={pasted}
            onChange={(event) => setPasted(event.target.value)}
            rows={4}
            spellCheck={false}
            placeholder={"Pegá una columna de Excel o una lista:\nCAM-001\nCAM-002, CAM-003"}
            aria-label="IDs de cámaras para agregar"
            className={`${INPUT_CLASS} font-mono text-xs`}
          />
          <button type="button" onClick={addPasted} disabled={!pasted.trim()} className={BUTTON.secondary}>
            Agregar a la selección
          </button>
          {pasteResult && (
            <Notice tone={pasteResult.missing.length ? "warn" : "info"}>
              {pasteResult.added} agregada(s)
              {pasteResult.repeated ? `, ${pasteResult.repeated} ya estaban` : ""}.
              {pasteResult.missing.length > 0 && (
                <>
                  {" "}
                  {pasteResult.missing.length} no están en el catálogo:{" "}
                  <span className="font-mono">{pasteResult.missing.slice(0, 10).join(", ")}</span>
                  {pasteResult.missing.length > 10 ? ` y ${pasteResult.missing.length - 10} más` : ""}.
                </>
              )}
            </Notice>
          )}
        </div>
      </details>

      {/* ------------------------------------------------ Selección */}
      <div className="space-y-2 rounded-lg bg-slate-900 p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-semibold text-slate-100">
            {selection.length} cámara{selection.length === 1 ? "" : "s"} elegida{selection.length === 1 ? "" : "s"}
          </span>
          {selection.length > 0 && (
            <span className="flex shrink-0 gap-1 whitespace-nowrap">
              <button type="button" onClick={copySelection} className={BUTTON.ghost} title="Copia los IDs, uno por línea">
                <IconCopy className="h-3.5 w-3.5" /> Copiar IDs
              </button>
              <button type="button" onClick={() => onSelectionChange([])} className={BUTTON.ghost}>
                Limpiar
              </button>
            </span>
          )}
        </div>
        {copied && <p role="status" className="text-xs text-emerald-300">{copied}</p>}
        {selection.length === 0 ? (
          <p className="text-xs text-slate-500">Elegí cámaras de la lista, agregá las filtradas o pegá IDs.</p>
        ) : (
          <ul className="flex flex-wrap gap-1">
            {selection.slice(0, MAX_CHIPS).map((id) => (
              <li key={id}>
                <button
                  type="button"
                  onClick={() => toggle(id)}
                  title={`Quitar ${id}`}
                  className="inline-flex items-center gap-1 rounded-md bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] text-slate-200 hover:bg-slate-700"
                >
                  {id} <IconX className="h-3 w-3 text-slate-500" />
                </button>
              </li>
            ))}
            {selection.length > MAX_CHIPS && (
              <li className="px-1 py-0.5 text-[11px] text-slate-500">y {selection.length - MAX_CHIPS} más</li>
            )}
          </ul>
        )}
      </div>

      <button
        type="button"
        onClick={onPlan}
        disabled={selection.length === 0 || isLoading}
        className={BUTTON.primary}
      >
        {isLoading ? "Armando la planilla…" : `Planificar ${selection.length || ""} cámara${selection.length === 1 ? "" : "s"}`}
      </button>
    </div>
  );
}
