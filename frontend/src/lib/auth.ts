/**
 * Cliente de /auth: login, sesión y cierre.
 *
 * El navegador guarda la sesión en una cookie HttpOnly que este código no
 * puede leer ni tocar. Lo que maneja acá es el token anti-CSRF que devuelve
 * el servidor, en memoria (ver lib/http.ts).
 */

import { apiFetch, apiError, apiJson, jsonBody, setCsrfToken } from "@/lib/http";

export type SessionUser = { usuario: string; nombre: string; rol: "admin" | "operador" };

export type Session = {
  usuario: SessionUser;
  csrf: string;
  debe_cambiar_password: boolean;
  expira_inactividad_en: string;
  expira_absoluta_en: string;
  inactividad_minutos: number;
};

function adopt(session: Session): Session {
  setCsrfToken(session.csrf);
  return session;
}

export async function login(usuario: string, password: string): Promise<Session> {
  return adopt(await apiJson<Session>("/auth/login", jsonBody("POST", { usuario, password }), "No se pudo ingresar"));
}

/** La sesión vigente, o null si no hay. Cuenta como actividad (y rota el token). */
export async function fetchSession(): Promise<Session | null> {
  const response = await apiFetch("/auth/sesion");
  if (response.status === 401) {
    setCsrfToken(null);
    return null;
  }
  if (!response.ok) throw await apiError(response, "No se pudo consultar la sesión");
  return adopt(await response.json());
}

/** Cierra la sesión en el servidor. Si falla la red, igual se olvida localmente. */
export async function logout(): Promise<void> {
  try {
    await apiFetch("/auth/logout", { method: "POST" });
  } catch {
    // Sin conexión: la cookie vence sola por inactividad en el servidor.
  } finally {
    setCsrfToken(null);
  }
}

export async function changePassword(actual: string, nueva: string): Promise<Session | null> {
  await apiJson<void>(
    "/auth/password",
    jsonBody("POST", { password_actual: actual, password_nueva: nueva }),
    "No se pudo cambiar la contraseña",
  );
  return fetchSession();
}
