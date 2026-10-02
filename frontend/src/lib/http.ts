/**
 * Todas las llamadas al backend pasan por acá.
 *
 * - Van a `/api/...` en el MISMO origen: Next.js las reenvía al backend
 *   (rewrite en next.config.ts). Así las cookies de sesión son de primera
 *   parte y `SameSite=Strict` funciona; no hace falta CORS.
 * - La sesión viaja en una cookie HttpOnly que JavaScript no puede leer. Lo
 *   único que vive acá es el token anti-CSRF, y sólo en memoria: nunca en
 *   localStorage ni sessionStorage, donde sobreviviría al cierre de sesión y
 *   lo leería cualquier script.
 * - Un 401 fuera de /auth avisa que la sesión se perdió (venció, se revocó).
 */

export const API_BASE_URL = "/api";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

let csrfToken: string | null = null;
const sessionLostListeners = new Set<() => void>();

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Suscribe a "la sesión dejó de valer"; devuelve la desuscripción. */
export function onSessionLost(listener: () => void): () => void {
  sessionLostListeners.add(listener);
  return () => sessionLostListeners.delete(listener);
}

/** Error del backend con su código HTTP. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (!SAFE_METHODS.has(method) && csrfToken) headers.set("X-CSRF-Token", csrfToken);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError("No se pudo conectar con el servidor. Verificá que esté corriendo.", 0);
  }

  if (response.status === 401 && !path.startsWith("/auth/")) {
    for (const listener of sessionLostListeners) listener();
  }
  return response;
}

/** El mensaje del backend (`detail`) o uno genérico con el código. */
export async function apiError(response: Response, fallback: string): Promise<ApiError> {
  const payload = await response.json().catch(() => null);
  const detail = payload?.detail;
  return new ApiError(
    typeof detail === "string" ? detail : `${fallback} (error ${response.status})`,
    response.status,
  );
}

/** apiFetch + JSON, lanzando ApiError si la respuesta no es 2xx. */
export async function apiJson<T>(path: string, init: RequestInit = {}, fallback = "Error del servidor"): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) throw await apiError(response, fallback);
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export function jsonBody(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}
