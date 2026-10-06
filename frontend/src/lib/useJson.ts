"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiJson } from "@/lib/http";

type State<T> = { key: string | null; data: T | null; error: string | null };

// Una lectura que falla por algo pasajero (el servidor no respondió, o el
// proxy de /api cortó la conexión) se reintenta una vez sola, a este tiempo.
const RETRY_MS = 800;

function isTransient(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 0 || err.status >= 500);
}

/**
 * Lee `path` del backend y lo vuelve a leer cuando cambia la ruta o `version`
 * (que se incrementa después de cada cambio en el registro o el catálogo).
 * Con `path` null no pide nada.
 *
 * Mientras llega la respuesta nueva conserva los datos anteriores: los
 * filtros responden sin que la lista parpadee vacía. `retry()` vuelve a pedir
 * lo mismo (para un botón "Reintentar" después de un error).
 */
export function useJson<T>(path: string | null, version: number) {
  const [attempt, setAttempt] = useState(0);
  const key = path === null ? null : `${version}|${attempt}|${path}`;
  const [state, setState] = useState<State<T>>({ key: null, data: null, error: null });

  useEffect(() => {
    if (key === null || path === null) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const load = (retried: boolean) => {
      apiJson<T>(path, { signal: controller.signal }).then(
        (data) => setState({ key, data, error: null }),
        (err: unknown) => {
          if (controller.signal.aborted) return;
          if (!retried && isTransient(err)) {
            timer = window.setTimeout(() => load(true), RETRY_MS);
            return;
          }
          const message = err instanceof Error ? err.message : "Error desconocido";
          setState((prev) => ({ key, data: prev.data, error: message }));
        },
      );
    };
    load(false);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [key, path]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  return {
    data: state.data,
    error: state.key === key ? state.error : null,
    loading: key !== null && state.key !== key,
    retry,
  };
}
