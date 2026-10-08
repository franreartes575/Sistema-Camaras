"use client";

/**
 * Ventana para cambiar la fecha planificada de una jornada entera.
 *
 * Mismo patrón que `TaskEditor`: <dialog> nativo en modo modal, sin cerrarlo
 * en la limpieza del efecto (en desarrollo React monta y desmonta dos veces y
 * la ventana se cerraba sola).
 */

import { useEffect, useRef, useState } from "react";

import { formatDayLabel } from "@/lib/format";
import type { RouteSummary } from "@/lib/registro";

export default function RouteDateEditor({
  route,
  busy,
  onSave,
  onClose,
}: {
  route: RouteSummary;
  busy: boolean;
  onSave: (date: string) => Promise<boolean>;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [date, setDate] = useState(route.date);

  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
  }, []);

  const submit = async () => {
    if (!date || date === route.date) {
      onClose();
      return;
    }
    if (await onSave(date)) onClose();
  };

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      aria-labelledby={`jornada-${route.id}`}
      className="m-auto w-[min(26rem,calc(100vw-2rem))] rounded-xl border border-slate-700 bg-slate-900 p-0 text-slate-100 shadow-2xl backdrop:bg-slate-950/70"
    >
      <form
        method="dialog"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <header className="border-b border-slate-800 px-4 py-3">
          <h2 id={`jornada-${route.id}`} className="text-base font-semibold">
            Cambiar el día · Día {route.day}
          </h2>
          <p className="text-xs text-slate-400">
            {route.plan_name} · {route.total} cámara(s) · hoy planificado {formatDayLabel(route.date)}
          </p>
        </header>
        <div className="space-y-2 px-4 py-3">
          <label className="block text-xs font-medium text-slate-300">
            Fecha planificada
            <input
              type="date"
              required
              value={date}
              onChange={(event) => setDate(event.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-sky-400 focus:outline-none"
            />
          </label>
          <p className="text-[11px] text-slate-500">
            Cambia la fecha de todas las tareas de esta jornada. La fecha de ejecución de cada
            una no se toca, y lo «fuera del plan» se recalcula solo.
          </p>
        </div>
        <footer className="flex justify-end gap-2 border-t border-slate-800 px-4 py-3">
          <button type="button" onClick={onClose} disabled={busy}
            className="rounded-md px-3 py-1.5 text-sm text-slate-300 transition hover:bg-slate-800 hover:text-white disabled:opacity-50">
            Cancelar
          </button>
          <button type="submit" disabled={busy}
            className="rounded-md bg-sky-500 px-3 py-1.5 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:opacity-50">
            {busy ? "Guardando…" : "Guardar"}
          </button>
        </footer>
      </form>
    </dialog>
  );
}
