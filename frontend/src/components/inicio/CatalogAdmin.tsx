"use client";

/**
 * Administración del catálogo (sólo administradores): importar planillas,
 * cargar las sedes y corregir o dar de baja cámaras sueltas.
 *
 * Importar combina por ID: agrega las nuevas, actualiza las que cambiaron y
 * nunca borra. Los encabezados y el mapeo sugerido salen de `/upload-excel/`,
 * el mismo paso que usa el planificador.
 */

import { useMemo, useState } from "react";

import DepotEditor from "@/components/DepotEditor";
import { searchable } from "@/components/panel/CatalogPicker";
import { BUTTON, ColumnField, INPUT_CLASS, Notice } from "@/components/ui/controls";
import { IconSearch, IconTrash, IconUpload } from "@/components/ui/icons";
import { uploadExcel, type ColumnMapping, type Depot, type UploadExcelResponse } from "@/lib/api";
import {
  catalogPaths,
  deleteCamera,
  importCatalog,
  setCameraLocality,
  type CatalogCamera,
  type CatalogImport,
  type CatalogImportResult,
} from "@/lib/catalogo";
import { formatTimestamp } from "@/lib/format";
import { useJson } from "@/lib/useJson";

const MAX_LISTED = 20;

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : "Error desconocido";
}

function mappingFrom(upload: UploadExcelResponse): ColumnMapping {
  const suggested = upload.suggested_mapping;
  return {
    col_id: suggested.id ?? upload.columns[0] ?? "",
    mode: suggested.mode,
    col_lat: suggested.lat ?? "",
    col_lon: suggested.lon ?? "",
    col_coords: suggested.coords ?? "",
    coord_order: "auto",
    col_label: suggested.label ?? "",
    col_node: suggested.node ?? "",
    col_obs: suggested.observation ?? "",
    col_done: "",
  };
}

function importSummary(result: CatalogImportResult): string {
  const parts = [
    `${result.added} nueva(s)`,
    `${result.updated} actualizada(s)`,
    `${result.unchanged} sin cambios`,
  ];
  if (result.discarded.length) parts.push(`${result.discarded.length} fila(s) descartada(s)`);
  if (result.duplicates) parts.push(`${result.duplicates} ID(s) repetidos en el archivo (vale la última fila)`);
  return `${parts.join(", ")}. El catálogo tiene ${result.camera_count} cámaras.`;
}

function ImportCatalog({ onImported }: { onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<UploadExcelResponse | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CatalogImportResult | null>(null);

  const pick = (picked: File) => {
    setFile(picked);
    setUpload(null);
    setMapping(null);
    setResult(null);
    setError(null);
    setBusy(true);
    uploadExcel(picked).then(
      (response) => {
        setUpload(response);
        setMapping(mappingFrom(response));
        setBusy(false);
      },
      (err: unknown) => {
        setError(errorText(err));
        setBusy(false);
      },
    );
  };

  const run = () => {
    if (!file || !mapping) return;
    setBusy(true);
    setError(null);
    importCatalog(file, mapping).then(
      (response) => {
        setResult(response);
        setBusy(false);
        setFile(null);
        setUpload(null);
        setMapping(null);
        onImported();
      },
      (err: unknown) => {
        setError(errorText(err));
        setBusy(false);
      },
    );
  };

  const columns = upload?.columns ?? [];
  const set = (patch: Partial<ColumnMapping>) => mapping && setMapping({ ...mapping, ...patch });
  const ready = Boolean(
    mapping && mapping.col_id && (mapping.mode === "single" ? mapping.col_coords : mapping.col_lat && mapping.col_lon),
  );

  return (
    <div className="space-y-2.5">
      <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed border-slate-700 bg-slate-900/60 px-3 py-2.5 transition hover:border-sky-400/60 focus-within:border-sky-400">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-sky-500/10 text-sky-300">
          <IconUpload className="h-4 w-4" />
        </span>
        <span className="min-w-0 text-sm">
          <span className="block truncate font-medium text-slate-100">
            {file ? file.name : busy ? "Leyendo…" : "Importar planilla de cámaras"}
          </span>
          <span className="block text-xs text-slate-500">
            Excel o CSV con ID y coordenadas. Se combina por ID: no borra nada.
          </span>
        </span>
        <input
          type="file"
          accept=".xlsx,.xlsm,.csv"
          className="sr-only"
          onChange={(event) => {
            const picked = event.target.files?.[0];
            if (picked) pick(picked);
            event.target.value = "";
          }}
        />
      </label>

      {upload && mapping && (
        <div className="space-y-2 rounded-lg bg-slate-900 p-3">
          <ColumnField label="Identificador de la cámara" value={mapping.col_id} columns={columns} onChange={(col_id) => set({ col_id })} />
          {mapping.mode === "single" ? (
            <ColumnField label="Coordenadas (lat, lon)" value={mapping.col_coords} columns={columns} onChange={(col_coords) => set({ col_coords })} />
          ) : (
            <div className="grid grid-cols-2 gap-2">
              <ColumnField label="Latitud" value={mapping.col_lat} columns={columns} onChange={(col_lat) => set({ col_lat })} />
              <ColumnField label="Longitud" value={mapping.col_lon} columns={columns} onChange={(col_lon) => set({ col_lon })} />
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            <ColumnField label="Descripción" value={mapping.col_label ?? ""} columns={columns} optional onChange={(col_label) => set({ col_label })} />
            <ColumnField label="Nodo" value={mapping.col_node ?? ""} columns={columns} optional onChange={(col_node) => set({ col_node })} />
          </div>
          <ColumnField label="Observación" value={mapping.col_obs ?? ""} columns={columns} optional onChange={(col_obs) => set({ col_obs })} />
          <button type="button" onClick={run} disabled={!ready || busy} className={BUTTON.primary}>
            {busy ? "Importando…" : "Importar al catálogo"}
          </button>
        </div>
      )}

      {error && <Notice tone="error">{error}</Notice>}
      {result && (
        <div className="space-y-1.5">
          <Notice tone={result.added + result.updated > 0 ? "info" : "warn"}>
            <b>{result.filename}:</b> {importSummary(result)}
            {result.previously_loaded_at && ` Este mismo archivo ya se había importado el ${formatTimestamp(result.previously_loaded_at)}.`}
          </Notice>
          {result.warning && <Notice tone="warn">{result.warning}</Notice>}
          {result.discarded.length > 0 && (
            <details className="rounded-lg border border-slate-800 px-3 py-2 text-xs text-slate-400">
              <summary className="cursor-pointer">Filas descartadas ({result.discarded.length})</summary>
              <ul className="mt-1.5 max-h-40 space-y-0.5 overflow-y-auto">
                {result.discarded.slice(0, 100).map((row) => (
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

function CameraRow({
  camera,
  localities,
  onChanged,
}: {
  camera: CatalogCamera;
  localities: string[];
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(camera.locality);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    action().then(
      () => {
        setBusy(false);
        setEditing(false);
        onChanged();
      },
      (err: unknown) => {
        setBusy(false);
        setError(errorText(err));
      },
    );
  };

  return (
    <li className="space-y-1.5 rounded-lg bg-slate-900 px-3 py-2 text-xs">
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0">
          <span className="block truncate font-mono font-medium text-slate-100">{camera.id}</span>
          <span className="block truncate text-slate-500">
            {camera.locality}
            {camera.locality_manual ? " (corregida a mano)" : ""}
            {camera.label ? ` · ${camera.label}` : ""}
          </span>
        </span>
        <span className="flex shrink-0 gap-0.5">
          <button type="button" onClick={() => setEditing((value) => !value)} className={BUTTON.ghost}>
            Localidad
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              if (window.confirm(`¿Dar de baja la cámara ${camera.id} del catálogo? El registro no se toca.`)) {
                run(() => deleteCamera(camera.id));
              }
            }}
            title="Dar de baja"
            aria-label={`Dar de baja ${camera.id}`}
            className={`${BUTTON.ghost} text-red-300 hover:text-red-200`}
          >
            <IconTrash className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>
      {editing && (
        <div className="flex flex-wrap items-center gap-1.5">
          <input
            list="localidades-conocidas"
            value={draft}
            maxLength={120}
            onChange={(event) => setDraft(event.target.value)}
            aria-label={`Localidad de ${camera.id}`}
            className={`${INPUT_CLASS} min-w-0 flex-1 py-1 text-xs`}
          />
          <datalist id="localidades-conocidas">
            {localities.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
          <button
            type="button"
            disabled={busy || !draft.trim()}
            onClick={() => run(() => setCameraLocality(camera.id, draft.trim()))}
            className="rounded-md bg-sky-500 px-2.5 py-1 font-semibold text-slate-950 hover:bg-sky-400 disabled:bg-slate-800 disabled:text-slate-500"
          >
            Guardar
          </button>
          {camera.locality_manual && (
            <button type="button" disabled={busy} onClick={() => run(() => setCameraLocality(camera.id, null))} className={BUTTON.ghost}>
              Volver al cálculo
            </button>
          )}
        </div>
      )}
      {error && <Notice tone="error">{error}</Notice>}
    </li>
  );
}

function ManageCameras({ cameras, onChanged }: { cameras: CatalogCamera[]; onChanged: () => void }) {
  const [query, setQuery] = useState("");
  const localities = useMemo(() => [...new Set(cameras.map((camera) => camera.locality))].sort(), [cameras]);
  const matches = useMemo(() => {
    const words = searchable(query).split(/\s+/).filter(Boolean);
    if (words.length === 0) return [];
    return cameras.filter((camera) => {
      const text = searchable([camera.id, camera.label, camera.locality].filter(Boolean).join(" "));
      return words.every((word) => text.includes(word));
    });
  }, [cameras, query]);

  return (
    <div className="space-y-2">
      <label className="relative block">
        <span className="sr-only">Buscar una cámara</span>
        <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Buscar una cámara para corregirla o darla de baja"
          className={`${INPUT_CLASS} pl-8`}
        />
      </label>
      {query.trim() && matches.length === 0 && <p className="text-xs text-slate-500">Ninguna coincide.</p>}
      <ul className="space-y-1.5">
        {matches.slice(0, MAX_LISTED).map((camera) => (
          <CameraRow
            key={`${camera.id}|${camera.locality}|${camera.locality_manual}`}
            camera={camera}
            localities={localities}
            onChanged={onChanged}
          />
        ))}
      </ul>
      {matches.length > MAX_LISTED && (
        <p className="text-[11px] text-slate-500">
          Se muestran {MAX_LISTED} de {matches.length}: afiná la búsqueda.
        </p>
      )}
    </div>
  );
}

export default function CatalogAdmin({
  cameras,
  depots,
  version,
  municipalitiesLoaded,
  onChanged,
}: {
  cameras: CatalogCamera[];
  depots: Depot[];
  version: number;
  municipalitiesLoaded: boolean;
  onChanged: () => void;
}) {
  const imports = useJson<CatalogImport[]>(catalogPaths.imports, version);

  return (
    <div className="space-y-4">
      {!municipalitiesLoaded && (
        <Notice tone="warn">
          Faltan los límites de los municipios, así que la localidad de cada cámara figura como
          &quot;Sin calcular&quot;. En el servidor, corré una vez{" "}
          <code className="rounded bg-slate-800 px-1 font-mono text-[11px]">python -m app.catalogo_cli preparar-municipios</code>{" "}
          (baja los límites oficiales del IGN y recalcula todo el catálogo).
        </Notice>
      )}
      <ImportCatalog onImported={onChanged} />
      <DepotEditor depots={depots} canEdit onChanged={onChanged} open={depots.length === 0} />
      <details className="rounded-lg border border-slate-800 px-3 py-2 open:pb-3">
        <summary className="cursor-pointer select-none text-xs font-medium text-slate-400 hover:text-slate-200">
          Corregir o dar de baja cámaras
        </summary>
        <div className="mt-3">
          <ManageCameras cameras={cameras} onChanged={onChanged} />
        </div>
      </details>
      {imports.data && imports.data.length > 0 && (
        <details className="rounded-lg border border-slate-800 px-3 py-2 open:pb-3">
          <summary className="cursor-pointer select-none text-xs font-medium text-slate-400 hover:text-slate-200">
            Importaciones ({imports.data.length})
          </summary>
          <ul className="mt-2 space-y-1 text-xs">
            {imports.data.slice(0, 10).map((item) => (
              <li key={item.id} className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 truncate text-slate-300">{item.filename}</span>
                <span className="shrink-0 tabular-nums text-slate-500">
                  {formatTimestamp(item.loaded_at)} · +{item.added} / ~{item.updated}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
