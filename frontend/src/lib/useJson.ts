"use client";

import { useEffect, useState } from "react";

import { getJson } from "@/lib/registro";

type State<T> = { key: string | null; data: T | null; error: string | null };

/**
 * Lee `path` del backend y lo vuelve a leer cuando cambia la ruta o `version`
 * (que se incrementa después de cada cambio en el registro). Con `path` null
 * no pide nada.
 *
 * Mientras llega la respuesta nueva conserva los datos anteriores: los
 * filtros responden sin que la lista parpadee vacía.
 */
export function useJson<T>(path: string | null, version: number) {
  const key = path === null ? null : `${version}|${path}`;
  const [state, setState] = useState<State<T>>({ key: null, data: null, error: null });

  useEffect(() => {
    if (key === null || path === null) return;
    const controller = new AbortController();
    getJson<T>(path, controller.signal).then(
      (data) => setState({ key, data, error: null }),
      (err: unknown) => {
        if (controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : "Error desconocido";
        setState((prev) => ({ key, data: prev.data, error: message }));
      },
    );
    return () => controller.abort();
  }, [key, path]);

  return {
    data: state.data,
    error: state.key === key ? state.error : null,
    loading: key !== null && state.key !== key,
  };
}
