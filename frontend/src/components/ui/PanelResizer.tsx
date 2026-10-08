"use client";

/**
 * Divisor arrastrable entre el panel lateral y el mapa (sólo en pantallas
 * medianas o más: en el celular se elige panel o mapa con el selector).
 *
 * Se arrastra con el mouse o el dedo, se mueve con ← y → (Shift: pasos más
 * grandes, Inicio y Fin: los topes) y con doble clic vuelve al ancho por
 * defecto. Mientras se arrastra, el ancho cambia en vivo (`onPreview`) y se
 * guarda recién al soltar.
 */

import { useRef, type KeyboardEvent, type PointerEvent } from "react";

import { PANEL_MIN, clampPanel } from "@/lib/usePanelWidth";

const STEP = 16;
const BIG_STEP = 64;

export default function PanelResizer({
  width,
  label,
  onPreview,
  onCommit,
  onReset,
}: {
  width: number;
  /** Qué panel cambia de tamaño, para el lector de pantalla. */
  label: string;
  onPreview: (width: number) => void;
  onCommit: (width: number) => void;
  onReset: () => void;
}) {
  const drag = useRef<{ startX: number; startWidth: number; last: number } | null>(null);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { startX: event.clientX, startWidth: width, last: width };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current) return;
    current.last = clampPanel(current.startWidth + event.clientX - current.startX);
    onPreview(current.last);
  };

  const finish = (event: PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current) return;
    drag.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    onCommit(current.last);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? BIG_STEP : STEP;
    const next = {
      ArrowLeft: width - step,
      ArrowRight: width + step,
      Home: PANEL_MIN,
      End: Number.POSITIVE_INFINITY,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    onCommit(clampPanel(next));
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={`Ancho de ${label}`}
      aria-valuemin={PANEL_MIN}
      aria-valuenow={width}
      tabIndex={0}
      title="Arrastrá para cambiar el ancho · doble clic: ancho original"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      className="group relative z-20 -mx-1 hidden w-2 shrink-0 cursor-col-resize touch-none outline-none md:block"
    >
      {/* La línea visible; el área para agarrar es más ancha que ella. */}
      <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-slate-800 transition-colors group-hover:w-0.5 group-hover:bg-sky-400 group-focus-visible:w-0.5 group-focus-visible:bg-sky-400" />
    </div>
  );
}
