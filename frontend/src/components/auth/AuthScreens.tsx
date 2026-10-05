"use client";

/**
 * Pantallas de acceso: contraseña y cambio de contraseña.
 *
 * Los mensajes de error son los del servidor, que son genéricos a propósito
 * ("Credenciales inválidas."): esta pantalla no agrega pistas propias.
 */

import { useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from "react";

import { BUTTON, INPUT_CLASS, Notice } from "@/components/ui/controls";
import { IconLock, IconRoute, IconShield } from "@/components/ui/icons";
import { changePassword, login, type Session } from "@/lib/auth";

const PASSWORD_MIN_LENGTH = 14;

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : "Error desconocido";
}

/** Marco común: tarjeta centrada con la identidad del sistema. */
export function AuthShell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-slate-950 px-4 py-10 text-slate-100">
      <div className={`w-full ${wide ? "max-w-lg" : "max-w-sm"}`}>
        <div className="mb-6 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300 ring-1 ring-sky-400/30">
            <IconRoute className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-base font-semibold tracking-tight">Recorridos de cámaras</h1>
            <p className="text-xs text-slate-500">Acceso restringido a personal autorizado</p>
          </div>
        </div>
        <div className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/70 p-6 shadow-2xl shadow-black/40">
          {children}
        </div>
        <p className="mt-4 flex items-start gap-2 text-[11px] leading-relaxed text-slate-500">
          <IconShield className="mt-px h-3.5 w-3.5 shrink-0" />
          Cada intento de acceso queda registrado con fecha, hora, dirección IP y navegador.
        </p>
      </div>
    </main>
  );
}

function Field({
  label,
  hint,
  className = "",
  ...input
}: { label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-400">{label}</span>
      <input {...input} className={`${INPUT_CLASS} py-2.5 ${className}`} />
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

function useSubmit<T>(action: () => Promise<T>, onDone: (value: T) => void) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      onDone(await action());
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPending(false);
    }
  };
  return { pending, error, submit };
}

// ---------------------------------------------------------------- contraseña

export function LoginForm({ notice, onSession }: { notice: string | null; onSession: (session: Session) => void }) {
  const [usuario, setUsuario] = useState("");
  const [password, setPassword] = useState("");
  const { pending, error, submit } = useSubmit(() => login(usuario, password), (session) => {
    setPassword("");
    onSession(session);
  });

  return (
    <AuthShell>
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
        <IconLock className="h-4 w-4 text-slate-400" /> Ingresar
      </div>
      {notice && <Notice tone="info">{notice}</Notice>}
      {error && <Notice tone="error">{error}</Notice>}
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Field
          label="Usuario"
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
          maxLength={64}
          autoFocus
          value={usuario}
          onChange={(event) => setUsuario(event.target.value)}
        />
        <Field
          label="Contraseña"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={256}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <button type="submit" disabled={pending || !usuario.trim() || !password} className={BUTTON.primary}>
          {pending ? "Verificando…" : "Ingresar"}
        </button>
      </form>
    </AuthShell>
  );
}

// ---------------------------------------------------------------- cambio de contraseña

export function ChangePasswordForm({
  session,
  onSession,
  onLogout,
}: {
  session: Session;
  onSession: (session: Session | null) => void;
  onLogout: () => void;
}) {
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [repetida, setRepetida] = useState("");
  const { pending, error, submit } = useSubmit(() => changePassword(actual, nueva), onSession);
  const problems = [
    nueva.length > 0 && nueva.length < PASSWORD_MIN_LENGTH ? `Al menos ${PASSWORD_MIN_LENGTH} caracteres.` : null,
    repetida.length > 0 && repetida !== nueva ? "Las contraseñas nuevas no coinciden." : null,
  ].filter(Boolean);

  return (
    <AuthShell>
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
        <IconLock className="h-4 w-4 text-slate-400" /> Cambiá tu contraseña
      </div>
      <p className="text-sm leading-relaxed text-slate-400">
        Hola, {session.usuario.nombre}. La contraseña actual es provisoria: elegí una nueva
        para continuar. Una frase larga es más segura y más fácil de recordar que una
        palabra con símbolos.
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Field label="Contraseña actual" type="password" autoComplete="current-password" maxLength={256} value={actual} onChange={(event) => setActual(event.target.value)} autoFocus />
        <Field label="Contraseña nueva" type="password" autoComplete="new-password" maxLength={128} value={nueva} onChange={(event) => setNueva(event.target.value)} hint={`Mínimo ${PASSWORD_MIN_LENGTH} caracteres; sin tu nombre de usuario.`} />
        <Field label="Repetila" type="password" autoComplete="new-password" maxLength={128} value={repetida} onChange={(event) => setRepetida(event.target.value)} />
        {problems.length > 0 && <p className="text-xs text-amber-300">{problems.join(" ")}</p>}
        <button type="submit" disabled={pending || !actual || nueva.length < PASSWORD_MIN_LENGTH || nueva !== repetida} className={BUTTON.primary}>
          {pending ? "Guardando…" : "Cambiar y continuar"}
        </button>
      </form>
      <button type="button" onClick={onLogout} className={BUTTON.ghost}>
        Salir
      </button>
    </AuthShell>
  );
}
