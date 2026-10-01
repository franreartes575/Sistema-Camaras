"use client";

import type { RegistroSync } from "@/components/ControlPanel";
import { followUpSummary } from "@/components/registro/ImportPanel";
import type { ColumnMapping, CoordOrder, UploadExcelResponse } from "@/lib/api";
import { BUTTON, ColumnField, Notice, Select } from "@/components/ui/controls";
import { IconDatabase, IconUpload } from "@/components/ui/icons";

type Props = {
  upload: UploadExcelResponse | null;
  mapping: ColumnMapping;
  isLoading: boolean;
  registroSync: RegistroSync | null;
  onFile: (file: File) => void;
  onMappingChange: (mapping: ColumnMapping) => void;
  onOpenRegistry: () => void;
};

/** Qué pasó con el registro al subir esta planilla. */
function RegistroSyncNotice({ sync, onOpenRegistry }: { sync: RegistroSync; onOpenRegistry: () => void }) {
  if (sync.kind === "from-registry") {
    return (
      <Notice tone="info">
        Son las tareas que faltan según el <b>registro</b>. Revisá el mapeo y
        agrupalas para armar los próximos recorridos.
      </Notice>
    );
  }
  if (sync.kind === "error") {
    return <Notice tone="warn">No se pudo actualizar el registro con este seguimiento: {sync.message}</Notice>;
  }
  return (
    <div className="space-y-1.5">
      <Notice tone={sync.result.matched > 0 ? "info" : "warn"}>
        <b>{sync.result.matched > 0 ? "Registro actualizado." : "Ninguna fila coincide con el registro."}</b>{" "}
        {followUpSummary(sync.result)}
      </Notice>
      <button type="button" onClick={onOpenRegistry} className={BUTTON.ghost}>
        <IconDatabase className="h-3.5 w-3.5" /> Ver el avance en el registro
      </button>
    </div>
  );
}

/** Paso 1: subir la planilla (o el Excel de seguimiento) y mapear columnas. */
export default function FileStep({
  upload,
  mapping,
  isLoading,
  registroSync,
  onFile,
  onMappingChange,
  onOpenRegistry,
}: Props) {
  const columns = upload?.columns ?? [];
  const set = (patch: Partial<ColumnMapping>) => onMappingChange({ ...mapping, ...patch });

  return (
    <>
      <label className="group flex cursor-pointer items-center gap-3 rounded-lg border border-dashed border-slate-700 bg-slate-900/60 px-3 py-3 transition hover:border-sky-400/60 hover:bg-slate-900 focus-within:border-sky-400">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-sky-500/10 text-sky-300">
          <IconUpload className="h-5 w-5" />
        </span>
        <span className="min-w-0 text-sm">
          <span className="block truncate font-medium text-slate-100">
            {upload ? upload.filename : isLoading ? "Leyendo…" : "Elegir planilla"}
          </span>
          <span className="block text-xs text-slate-500">
            {upload
              ? `${upload.column_count} columnas · tocá para cambiarla`
              : "Excel o CSV — también el Excel de seguimiento completado"}
          </span>
        </span>
        <input
          type="file"
          accept=".xlsx,.xlsm,.csv"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onFile(file);
            event.target.value = ""; // permite volver a elegir el mismo archivo
          }}
        />
      </label>

      {upload && (
        <>
          <ColumnField
            label="Identificador de la cámara"
            value={mapping.col_id}
            columns={columns}
            onChange={(col_id) => set({ col_id })}
          />

          <div role="radiogroup" aria-label="Formato de coordenadas" className="grid grid-cols-2 gap-1 rounded-lg bg-slate-900 p-1">
            {(
              [
                ["split", "Lat y lon separadas"],
                ["single", "En una columna"],
              ] as const
            ).map(([value, text]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={mapping.mode === value}
                onClick={() => set({ mode: value })}
                className={`rounded-md px-2 py-1.5 text-xs font-medium transition ${
                  mapping.mode === value
                    ? "bg-slate-700 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {text}
              </button>
            ))}
          </div>

          {mapping.mode === "split" ? (
            <div className="grid grid-cols-2 gap-2">
              <ColumnField label="Latitud" value={mapping.col_lat} columns={columns} onChange={(col_lat) => set({ col_lat })} />
              <ColumnField label="Longitud" value={mapping.col_lon} columns={columns} onChange={(col_lon) => set({ col_lon })} />
            </div>
          ) : (
            <>
              <ColumnField label="Coordenadas" value={mapping.col_coords} columns={columns} onChange={(col_coords) => set({ col_coords })} />
              <Select
                label="Orden dentro de la celda"
                value={mapping.coord_order}
                options={[
                  { value: "auto", text: "Detectar automáticamente" },
                  { value: "latlon", text: "Latitud, Longitud" },
                  { value: "lonlat", text: "Longitud, Latitud" },
                ]}
                hint="La detección sólo distingue cuando un valor excede ±90; si no, asume lat,lon. Verificá en el mapa."
                onChange={(value) => set({ coord_order: value as CoordOrder })}
              />
            </>
          )}

          <details className="group rounded-lg border border-slate-800 px-3 py-2 open:pb-3" open={Boolean(mapping.col_node || mapping.col_obs || mapping.col_done)}>
            <summary className="cursor-pointer select-none text-xs font-medium text-slate-400 hover:text-slate-200">
              Columnas de seguimiento (opcionales)
            </summary>
            <div className="mt-3 space-y-2.5">
              <ColumnField label="Nodo preliminar" value={mapping.col_node ?? ""} columns={columns} optional onChange={(col_node) => set({ col_node })} />
              <ColumnField label="Observación" value={mapping.col_obs ?? ""} columns={columns} optional onChange={(col_obs) => set({ col_obs })} />
              <ColumnField label="Realizado" value={mapping.col_done ?? ""} columns={columns} optional onChange={(col_done) => set({ col_done })} />
              <ColumnField label="Descripción" value={mapping.col_label ?? ""} columns={columns} optional onChange={(col_label) => set({ col_label })} />
            </div>
          </details>

          {mapping.col_done && (
            <Notice tone="info">
              Es un Excel de seguimiento: las cámaras con <b>Realizado = Sí</b> no se
              vuelven a planificar; las pendientes y las filas nuevas sí.
            </Notice>
          )}
          {registroSync && <RegistroSyncNotice sync={registroSync} onOpenRegistry={onOpenRegistry} />}
        </>
      )}
    </>
  );
}
