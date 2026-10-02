"use client";

/**
 * Pantallas de acceso: contraseña, segundo factor, configuración de la app
 * autenticadora, códigos de recuperación y cambio de contraseña.
 *
 * Los mensajes de error son los del servidor, que son genéricos a propósito
 * ("Credenciales inválidas."): esta pantalla no agrega pistas propias.
 */

import { useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from "react";

import { BUTTON, INPUT_CLASS, Notice } from "@/components/ui/controls";
import { IconLock, IconRoute, IconShield } from "@/components/ui/icons";
import {
  changePassword,
  confirmTotp,
  login,
  startTotpEnrollment,
  verifyMfa,
  type Enrollment,
  type LoginStep,
  type Session,
} from "@/lib/auth";
import { downloadBlob } from "@/lib/download";

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

export function LoginForm({ notice, onStep }: { notice: string | null; onStep: (step: LoginStep) => void }) {
  const [usuario, setUsuario] = useState("");
  const [password, setPassword] = useState("");
  const { pending, error, submit } = useSubmit(() => login(usuario, password), (step) => {
    setPassword("");
    onStep(step);
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
          {pending ? "Verificando…" : "Continuar"}
        </button>
      </form>
    </AuthShell>
  );
}

// ---------------------------------------------------------------- segundo factor

function CodeField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <Field
      label="Código de 6 dígitos de la app autenticadora"
      name="otp"
      inputMode="numeric"
      autoComplete="one-time-code"
      pattern="\d{6}"
      maxLength={6}
      autoFocus
      required
      value={value}
      onChange={(event) => onChange(event.target.value.replace(/\D/g, "").slice(0, 6))}
      className="tracking-[0.5em]"
    />
  );
}

export function MfaForm({ onSession, onRestart }: { onSession: (session: Session) => void; onRestart: () => void }) {
  const [useRecovery, setUseRecovery] = useState(false);
  const [codigo, setCodigo] = useState("");
  const [recuperacion, setRecuperacion] = useState("");
  const { pending, error, submit } = useSubmit(
    () => verifyMfa(useRecovery ? { codigo_recuperacion: recuperacion } : { codigo }),
    onSession,
  );
  const ready = useRecovery ? recuperacion.replace(/[\s-]/g, "").length === 12 : /^\d{6}$/.test(codigo);

  return (
    <AuthShell>
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
        <IconShield className="h-4 w-4 text-slate-400" /> Segundo factor
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <form onSubmit={submit} className="space-y-3" noValidate>
        {useRecovery ? (
          <Field
            label="Código de recuperación"
            name="recovery"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            placeholder="XXXX-XXXX-XXXX"
            maxLength={20}
            autoFocus
            value={recuperacion}
            onChange={(event) => setRecuperacion(event.target.value)}
            hint="Cada código sirve una sola vez."
          />
        ) : (
          <CodeField value={codigo} onChange={setCodigo} />
        )}
        <button type="submit" disabled={pending || !ready} className={BUTTON.primary}>
          {pending ? "Verificando…" : "Ingresar"}
        </button>
      </form>
      <div className="flex justify-between text-xs">
        <button type="button" onClick={() => setUseRecovery(!useRecovery)} className={BUTTON.ghost}>
          {useRecovery ? "Usar la app autenticadora" : "Perdí el teléfono: usar un código de recuperación"}
        </button>
        <button type="button" onClick={onRestart} className={BUTTON.ghost}>
          Volver
        </button>
      </div>
    </AuthShell>
  );
}

export function EnrollForm({ onSession, onRestart }: { onSession: (session: Session) => void; onRestart: () => void }) {
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [codigo, setCodigo] = useState("");
  const start = useSubmit(startTotpEnrollment, setEnrollment);
  const confirm = useSubmit(() => confirmTotp(codigo), onSession);
  const grouped = enrollment?.secreto.match(/.{1,4}/g)?.join(" ") ?? "";

  return (
    <AuthShell wide>
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
        <IconShield className="h-4 w-4 text-slate-400" /> Configurá el segundo factor
      </div>
      <p className="text-sm leading-relaxed text-slate-400">
        Es obligatorio. Vas a necesitar una app autenticadora en el teléfono (Google
        Authenticator, Microsoft Authenticator, Aegis, FreeOTP…).
      </p>
      {(start.error || confirm.error) && <Notice tone="error">{start.error ?? confirm.error}</Notice>}
      {!enrollment ? (
        <form onSubmit={start.submit}>
          <button type="submit" disabled={start.pending} className={BUTTON.primary}>
            {start.pending ? "Generando…" : "Generar el código QR"}
          </button>
        </form>
      ) : (
        <form onSubmit={confirm.submit} className="space-y-4" noValidate>
          <ol className="space-y-4 text-sm text-slate-300">
            <li>
              <span className="font-medium text-slate-100">1.</span> Escaneá este código con la app:
              <span className="mt-2 flex justify-center rounded-xl bg-white p-3">
                {/* Un SVG dentro de <img> no ejecuta scripts. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={enrollment.qr} alt="Código QR para la app autenticadora" className="h-48 w-48" />
              </span>
              <span className="mt-2 block text-xs text-slate-500">
                ¿No podés escanearlo? Cargá esta clave a mano:
                <code className="mt-1 block select-all break-all rounded-md bg-slate-950 px-2 py-1.5 font-mono text-[13px] tracking-wider text-slate-200">
                  {grouped}
                </code>
              </span>
            </li>
            <li>
              <span className="font-medium text-slate-100">2.</span> Escribí el código que muestra la app:
              <div className="mt-2">
                <CodeField value={codigo} onChange={setCodigo} />
              </div>
            </li>
          </ol>
          <button type="submit" disabled={confirm.pending || !/^\d{6}$/.test(codigo)} className={BUTTON.primary}>
            {confirm.pending ? "Verificando…" : "Confirmar y entrar"}
          </button>
        </form>
      )}
      <button type="button" onClick={onRestart} className={BUTTON.ghost}>
        Volver
      </button>
    </AuthShell>
  );
}

// ---------------------------------------------------------------- recuperación

export function RecoveryCodes({ codes, onContinue }: { codes: string[]; onContinue: () => void }) {
  const [saved, setSaved] = useState(false);
  return (
    <AuthShell wide>
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
        <IconShield className="h-4 w-4 text-emerald-300" /> Segundo factor configurado
      </div>
      <Notice tone="warn">
        Guardá estos códigos de recuperación en un lugar seguro y fuera del teléfono.
        Sirven para entrar si perdés la app; cada uno, una sola vez. <b>No se vuelven a mostrar.</b>
      </Notice>
      <ul className="grid grid-cols-2 gap-2 rounded-xl bg-slate-950 p-3 font-mono text-sm tracking-wider text-slate-100">
        {codes.map((code) => (
          <li key={code} className="select-all text-center">
            {code}
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() =>
          downloadBlob(
            new Blob([`Códigos de recuperación — Recorridos de cámaras\n\n${codes.join("\n")}\n`], { type: "text/plain" }),
            "codigos-recuperacion.txt",
          )
        }
        className={BUTTON.secondary}
      >
        Descargar como .txt
      </button>
      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input type="checkbox" checked={saved} onChange={(event) => setSaved(event.target.checked)} className="h-4 w-4 accent-sky-400" />
        Ya los guardé en un lugar seguro
      </label>
      <button type="button" disabled={!saved} onClick={onContinue} className={BUTTON.primary}>
        Continuar
      </button>
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
