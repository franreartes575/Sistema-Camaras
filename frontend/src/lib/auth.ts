/**
 * Cliente de /auth: login en dos pasos, sesión y cierre.
 *
 * El navegador guarda la sesión en una cookie HttpOnly que este código no
 * puede leer ni tocar. Lo que maneja acá es el token anti-CSRF que devuelve
 * cada paso, en memoria (ver lib/http.ts).
 */

import { apiFetch, apiError, apiJson, jsonBody, setCsrfToken } from "@/lib/http";

export type LoginStep = {
  /** "mfa": pedir el código. "enrolar_mfa": primer ingreso, configurar la app. */
  paso: "mfa" | "enrolar_mfa";
  csrf: string;
  expira_en: string;
};

export type Enrollment = {
  secreto: string;
  uri: string;
  /** data:image/svg+xml — se muestra con <img>, nunca como HTML. */
  qr: string;
};

export type SessionUser = { usuario: string; nombre: string; rol: "admin" | "operador" };

export type Session = {
  usuario: SessionUser;
  csrf: string;
  debe_cambiar_password: boolean;
  expira_inactividad_en: string;
  expira_absoluta_en: string;
  inactividad_minutos: number;
  /** Sólo al terminar de configurar el segundo factor: se muestran una vez. */
  codigos_recuperacion: string[] | null;
  /** Si se entró con un código de recuperación, cuántos quedan. */
  codigos_restantes: number | null;
};

function adopt(session: Session): Session {
  setCsrfToken(session.csrf);
  return session;
}

export async function login(usuario: string, password: string): Promise<LoginStep> {
  const step = await apiJson<LoginStep>("/auth/login", jsonBody("POST", { usuario, password }), "No se pudo ingresar");
  setCsrfToken(step.csrf);
  return step;
}

export function startTotpEnrollment(): Promise<Enrollment> {
  return apiJson<Enrollment>("/auth/mfa/totp/enrolar", { method: "POST" }, "No se pudo iniciar la configuración");
}

export async function confirmTotp(codigo: string): Promise<Session> {
  return adopt(await apiJson<Session>("/auth/mfa/totp/confirmar", jsonBody("POST", { codigo }), "No se pudo verificar"));
}

export async function verifyMfa(input: { codigo: string } | { codigo_recuperacion: string }): Promise<Session> {
  return adopt(await apiJson<Session>("/auth/mfa/verificar", jsonBody("POST", input), "No se pudo verificar"));
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
