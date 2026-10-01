"use client";

/**
 * Carga de seguimientos: el Excel que completaron los técnicos actualiza el
 * registro. Arriba la zona para soltar el archivo; en la pestaña Cargas, el
 * historial.
 */

import { useState } from "react";

import { Notice } from "@/components/ui/controls";
import { IconUpload } from "@/components/ui/icons";
import { formatTimestamp } from "@/lib/format";
import type { FollowUpImport, FollowUpResult } from "@/lib/registro";

/** Resumen en una línea de lo que cambió con un seguimiento. */
export function followUpSummary(result: FollowUpResult): string {
  const parts = [`${result.done} realizada(s)`];
  if (result.not_done) parts.push(`${result.not_done} no realizada(s)`);
  if (result.no_news) parts.push(`${result.no_news} sin novedad`);
  let text = `${result.matched} de ${result.rows} fila(s) coinciden con el registro: ${parts.join(", ")}.`;
  if (result.updated === 0 && result.matched > 0) text += " No había nada nuevo para actualizar.";
  if (result.unmatched) {
    const ids = result.unmatched_ids.join(", ");
    text += ` ${result.unmatched} sin recorrido guardado (${ids}${result.unmatched > result.unmatched_ids.length ? "…" : ""}).`;
  }
  if (result.previously_loaded_at) {
    text += ` Este mismo archivo ya se había cargado el ${formatTimestamp(result.previously_loaded_at)}.`;
  }
  return text;
}

export function ImportDropzone({
  isUploading,
  result,
  error,
  onFile,
  onDismiss,
}: {
  isUploading: boolean;
  result: FollowUpResult | null;
  error: string | null;
  onFile: (file: File) => void;
  onDismiss: () => void;
}) {
  const [isDragging, setIsDragging] = useState(false);

  return (
    <div className="space-y-2">
      <label
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          const file = event.dataTransfer.files?.[0];
          if (file) onFile(file);
        }}
        className={`flex cursor-pointer items-center gap-3 rounded-xl border border-dashed px-3 py-3 transition focus-within:border-sky-400 ${
          isDragging
            ? "border-sky-400 bg-sky-500/10"
            : "border-slate-700 bg-slate-900/60 hover:border-sky-400/60 hover:bg-slate-900"
        }`}
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-300">
          <IconUpload className="h-5 w-5" />
        </span>
        <span className="min-w-0 text-sm">
          <span className="block font-medium text-slate-100">
            {isUploading ? "Actualizando el registro…" : "Cargar seguimiento verificado"}
          </span>
          <span className="block text-xs text-slate-500">
            Soltá o elegí el Excel que completaron los técnicos
          </span>
        </span>
        <input
          type="file"
          accept=".xlsx,.xlsm,.csv"
          className="sr-only"
          disabled={isUploading}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onFile(file);
            event.target.value = "";
          }}
        />
      </label>
      {error && <Notice tone="error">{error}</Notice>}
      {result && (
        <div className="relative">
          <Notice tone={result.matched > 0 ? "info" : "warn"}>
            <b className="font-semibold">{result.filename}</b>
            {result.plan_name && <> · {result.plan_name}</>}
            <br />
            {followUpSummary(result)}
          </Notice>
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Cerrar aviso"
            className="absolute right-1.5 top-1.5 rounded px-1.5 text-sky-200/70 hover:text-white"
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}

export function ImportHistory({ imports }: { imports: FollowUpImport[] }) {
  if (imports.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-sm text-slate-500">
        Todavía no se cargó ningún seguimiento.
      </p>
    );
  }
  return (
    <ol className="space-y-1.5">
      {imports.map((item) => (
        <li key={item.id} className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-sm font-medium text-slate-100">{item.filename}</span>
            <span className="shrink-0 text-[11px] tabular-nums text-slate-500">
              {formatTimestamp(item.loaded_at)}
            </span>
          </div>
          <p className="text-[11px] text-slate-400">
            {item.plan_name ?? "Sin plan asociado"} · {item.matched}/{item.rows} coinciden ·{" "}
            {item.done} realizada(s)
            {item.not_done > 0 && ` · ${item.not_done} no realizada(s)`}
            {item.unmatched > 0 && <span className="text-amber-300"> · {item.unmatched} sin recorrido</span>}
            {" · "}
            {item.updated} cambio(s)
          </p>
        </li>
      ))}
    </ol>
  );
}
