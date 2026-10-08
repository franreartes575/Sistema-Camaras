"use client";

/**
 * Ancho del panel lateral de una sección, elegido por quien la usa.
 *
 * Se guarda en `localStorage` por sección: es una comodidad de este
 * navegador, no un dato del sistema. Se lee con `useSyncExternalStore` (y no
 * en un efecto): en el servidor no hay `localStorage`, y así el primer render
 * usa el ancho por defecto sin desajuste al hidratar. Si el almacenamiento no
 * está disponible (ventana privada, bloqueado), se usa el ancho por defecto.
 */

import { useCallback, useState, useSyncExternalStore, type CSSProperties } from "react";

const PREFIX = "panel-ancho:";
const CHANGED = "panel-ancho-cambio";

/** El panel no baja de esto y el mapa siempre conserva al menos MAP_MIN. */
export const PANEL_MIN = 280;
export const MAP_MIN = 320;

function read(key: string): number | null {
  try {
    const value = Number(window.localStorage.getItem(PREFIX + key));
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange); // otra pestaña
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** El ancho más grande que deja lugar al mapa en esta ventana. */
export function panelMax(): number {
  return Math.max(PANEL_MIN, window.innerWidth - MAP_MIN);
}

export function clampPanel(width: number): number {
  return Math.round(Math.min(Math.max(width, PANEL_MIN), panelMax()));
}

export function usePanelWidth(key: string, defaultWidth: number) {
  const stored = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => null,
  );

  const save = useCallback(
    (width: number | null) => {
      try {
        if (width === null) window.localStorage.removeItem(PREFIX + key);
        else window.localStorage.setItem(PREFIX + key, String(clampPanel(width)));
      } catch {
        // Sin almacenamiento: el ancho vale hasta recargar la página.
      }
      window.dispatchEvent(new Event(CHANGED));
    },
    [key],
  );

  return { width: stored ?? defaultWidth, save, reset: () => save(null) };
}

/**
 * Todo lo que necesita una sección con panel ajustable: el estilo del panel
 * (el ancho va en la variable `--panel-w`, que usa la clase
 * `md:w-[var(--panel-w)]`: en el celular el panel sigue ocupando todo) y las
 * propiedades del divisor. Mientras se arrastra, el ancho es el de la vista
 * previa; al soltar se guarda.
 */
export function useResizablePanel(key: string, defaultWidth: number) {
  const panel = usePanelWidth(key, defaultWidth);
  const [preview, setPreview] = useState<number | null>(null);
  const width = preview ?? panel.width;
  return {
    panelStyle: { "--panel-w": `${width}px` } as CSSProperties,
    resizer: {
      width,
      onPreview: setPreview,
      onCommit: (value: number) => {
        panel.save(value);
        setPreview(null);
      },
      onReset: () => {
        panel.reset();
        setPreview(null);
      },
    },
  };
}

/**
 * Clases del panel lateral ajustable: el ancho elegido en pantallas medianas
 * o más, sin bajar del mínimo ni dejar al mapa sin lugar.
 */
export const RESIZABLE_PANEL =
  "md:w-[var(--panel-w)] md:min-w-[280px] md:max-w-[calc(100vw-320px)] md:shrink-0";
