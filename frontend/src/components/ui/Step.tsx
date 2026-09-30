/**
 * Un paso de la guía lateral: número, título, estado y, plegado, un resumen.
 *
 * Los pasos cuelgan de un riel vertical (la línea que los une) en vez de ir
 * dentro de tarjetas: el panel se lee como una secuencia, no como una pila de
 * cajas, y el contenido de cada paso no queda "tarjeta dentro de tarjeta".
 */

import type { ReactNode } from "react";

import { IconCheck, IconChevron } from "./icons";

export type StepStatus = "done" | "active" | "locked";

type Props = {
  number: number;
  title: string;
  icon: ReactNode;
  status: StepStatus;
  /** Una línea que resume lo resuelto; se ve con el paso plegado. */
  summary?: string;
  /** Qué falta para habilitarlo; se ve mientras está bloqueado. */
  lockedHint?: string;
  isOpen: boolean;
  isLast?: boolean;
  onToggle: () => void;
  children: ReactNode;
};

const BADGE = {
  done: "bg-emerald-500/15 text-emerald-300 ring-emerald-400/40",
  active: "bg-sky-500 text-slate-950 ring-sky-300/60",
  locked: "bg-slate-900 text-slate-500 ring-slate-700",
} as const;

export default function Step({
  number,
  title,
  icon,
  status,
  summary,
  lockedHint,
  isOpen,
  isLast,
  onToggle,
  children,
}: Props) {
  const locked = status === "locked";
  const bodyId = `paso-${number}`;
  const caption = locked ? lockedHint : !isOpen ? summary : undefined;

  return (
    <section className="relative grid grid-cols-[2rem_1fr] gap-x-3">
      {!isLast && (
        <span aria-hidden="true" className="absolute bottom-0 left-4 top-9 w-px bg-slate-800" />
      )}
      <span
        className={`relative z-10 mt-0.5 flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold ring-1 ${BADGE[status]}`}
      >
        {status === "done" ? <IconCheck className="h-4 w-4" /> : number}
      </span>

      <div className="min-w-0 pb-6">
        <button
          type="button"
          onClick={onToggle}
          disabled={locked}
          aria-expanded={isOpen}
          aria-controls={bodyId}
          className="group flex w-full items-start justify-between gap-2 rounded-md text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-300 disabled:cursor-not-allowed"
        >
          <span className="min-w-0">
            <span
              className={`flex items-center gap-1.5 text-sm font-semibold ${locked ? "text-slate-500" : "text-slate-100"}`}
            >
              <span className={locked ? "text-slate-600" : "text-slate-400"}>{icon}</span>
              {title}
            </span>
            {caption && (
              <span className="mt-0.5 block truncate text-xs text-slate-500">{caption}</span>
            )}
          </span>
          {!locked && (
            <IconChevron
              className={`mt-0.5 h-4 w-4 shrink-0 text-slate-500 transition-transform group-hover:text-slate-300 ${isOpen ? "rotate-180" : ""}`}
            />
          )}
        </button>

        {isOpen && !locked && (
          <div id={bodyId} className="mt-3 space-y-3">
            {children}
          </div>
        )}
      </div>
    </section>
  );
}
