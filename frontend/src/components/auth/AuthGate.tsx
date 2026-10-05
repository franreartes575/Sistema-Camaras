"use client";

/**
 * Puerta de acceso: la aplicación sólo se monta con una sesión válida.
 *
 * Al perderse la sesión (logout, inactividad, revocación desde el servidor)
 * la app se DESMONTA entera: los datos de la operación que tenía en memoria
 * —planillas, recorridos, mapa— desaparecen con ella. En una terminal
 * compartida, nadie encuentra el trabajo del anterior.
 *
 * Inactividad: el servidor cierra la sesión a los N minutos sin pedidos. Acá
 * se cuenta la actividad REAL (teclado, mouse, toques): si la hubo, cada
 * minuto se avisa al servidor con /auth/sesion; si no, a un minuto del cierre
 * se muestra un aviso, y al llegar al límite se cierra la sesión.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { AuthShell, ChangePasswordForm, LoginForm } from "@/components/auth/AuthScreens";
import { BUTTON, Notice } from "@/components/ui/controls";
import { fetchSession, logout as logoutRequest, type Session } from "@/lib/auth";
import { onSessionLost } from "@/lib/http";

type State =
  | { kind: "checking" }
  | { kind: "login"; notice: string | null }
  | { kind: "password"; session: Session }
  | { kind: "ready"; session: Session };

type AuthContextValue = { session: Session; logout: () => void };

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth fuera de AuthGate");
  return value;
}

const HEARTBEAT_MS = 60_000;
const WARNING_MS = 60_000;
const TICK_MS = 1_000;
const ACTIVITY_EVENTS = ["mousedown", "mousemove", "keydown", "touchstart", "wheel", "scroll"] as const;

const NOTICES = {
  expired: "La sesión venció o se cerró desde el servidor. Ingresá de nuevo.",
  idle: "Se cerró la sesión por inactividad.",
  absolute: "La sesión llegó a su duración máxima. Ingresá de nuevo.",
  logout: "Cerraste la sesión.",
} as const;

/** Estado inicial según la sesión del servidor. */
function stateFor(session: Session | null, notice: string | null = null): State {
  if (!session) return { kind: "login", notice };
  if (session.debe_cambiar_password) return { kind: "password", session };
  return { kind: "ready", session };
}

function IdleWatcher({
  session,
  onExpire,
  onSession,
}: {
  session: Session;
  onExpire: (notice: string) => void;
  onSession: (session: Session) => void;
}) {
  const lastInput = useRef(0);
  const lastBeat = useRef(0);
  const [remaining, setRemaining] = useState<number | null>(null);
  const idleMs = session.inactividad_minutos * 60_000;
  const absoluteAt = Date.parse(session.expira_absoluta_en);

  useEffect(() => {
    lastInput.current = Date.now();
    lastBeat.current = Date.now();
    const mark = () => {
      lastInput.current = Date.now();
    };
    for (const name of ACTIVITY_EVENTS) window.addEventListener(name, mark, { passive: true });

    const timer = window.setInterval(() => {
      const now = Date.now();
      if (now >= absoluteAt) {
        onExpire(NOTICES.absolute);
        return;
      }
      const idle = now - lastInput.current;
      // Margen de 5 s: cerrar del lado del cliente antes que el servidor.
      if (idle >= idleMs - 5_000) {
        onExpire(NOTICES.idle);
        return;
      }
      setRemaining(idle >= idleMs - WARNING_MS ? Math.ceil((idleMs - idle) / 1000) : null);
      if (now - lastBeat.current >= HEARTBEAT_MS && lastInput.current > lastBeat.current) {
        lastBeat.current = now;
        fetchSession().then(
          (fresh) => (fresh ? onSession(fresh) : onExpire(NOTICES.expired)),
          () => undefined, // un corte de red no cierra la sesión; el próximo latido reintenta
        );
      }
    }, TICK_MS);

    return () => {
      window.clearInterval(timer);
      for (const name of ACTIVITY_EVENTS) window.removeEventListener(name, mark);
    };
  }, [absoluteAt, idleMs, onExpire, onSession]);

  if (remaining === null) return null;
  return (
    <div role="alertdialog" aria-live="assertive" className="fixed inset-x-0 bottom-4 z-50 flex justify-center px-4">
      <div className="flex max-w-md items-center gap-3 rounded-xl border border-amber-500/40 bg-slate-900 px-4 py-3 text-sm text-amber-100 shadow-2xl">
        <span>
          Por inactividad, la sesión se cierra en <b className="whitespace-nowrap tabular-nums">{remaining} s</b>.
        </span>
        <button
          type="button"
          onClick={() => {
            lastInput.current = Date.now();
            setRemaining(null);
          }}
          className="shrink-0 rounded-md bg-amber-400 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-amber-300"
        >
          Seguir conectado
        </button>
      </div>
    </div>
  );
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ kind: "checking" });
  const [checkError, setCheckError] = useState<string | null>(null);

  useEffect(() => {
    fetchSession().then(
      (session) => setState(stateFor(session)),
      (err: unknown) => setCheckError(err instanceof Error ? err.message : "Error desconocido"),
    );
  }, []);

  useEffect(
    () => onSessionLost(() => setState((prev) => (prev.kind === "ready" ? { kind: "login", notice: NOTICES.expired } : prev))),
    [],
  );

  const end = useCallback((notice: string) => {
    setState({ kind: "login", notice });
    void logoutRequest();
  }, []);

  const logout = useCallback(() => end(NOTICES.logout), [end]);
  const onSession = useCallback((session: Session) => setState(stateFor(session)), []);
  const refresh = useCallback(
    (session: Session) => setState((prev) => (prev.kind === "ready" ? { kind: "ready", session } : prev)),
    [],
  );

  switch (state.kind) {
    case "checking":
      return (
        <AuthShell>
          {checkError ? (
            <>
              <Notice tone="error">{checkError}</Notice>
              <button type="button" onClick={() => window.location.reload()} className={BUTTON.secondary}>
                Reintentar
              </button>
            </>
          ) : (
            <p className="text-sm text-slate-400">Verificando la sesión…</p>
          )}
        </AuthShell>
      );
    case "login":
      return <LoginForm notice={state.notice} onSession={onSession} />;
    case "password":
      return (
        <ChangePasswordForm
          session={state.session}
          onSession={(session) => setState(stateFor(session, NOTICES.expired))}
          onLogout={logout}
        />
      );
    case "ready":
      return (
        <AuthContext.Provider value={{ session: state.session, logout }}>
          {children}
          <IdleWatcher session={state.session} onExpire={end} onSession={refresh} />
        </AuthContext.Provider>
      );
  }
}
