/** Estado de una tarea con ícono + rótulo: el color nunca va solo. */

import { IconArrowRight, IconCheck, IconCircle, IconX } from "@/components/ui/icons";
import type { TaskStatus } from "@/lib/registro";
import { STATUS_INK } from "@/lib/vizTokens";

export const STATUS_LABEL: Record<TaskStatus, string> = {
  realizada: "Realizada",
  no_realizada: "No realizada",
  pendiente: "Pendiente",
  reprogramada: "Reprogramada",
};

const GLYPH = {
  realizada: IconCheck,
  no_realizada: IconX,
  pendiente: IconCircle,
  reprogramada: IconArrowRight,
} as const;

/** Ícono redondo del estado; lo pendiente va hueco, igual que en el mapa. */
export function StatusIcon({ status, className = "h-5 w-5" }: { status: TaskStatus; className?: string }) {
  const Glyph = GLYPH[status];
  const hollow = status === "pendiente";
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center rounded-full ${className}`}
      style={
        hollow
          ? { boxShadow: `inset 0 0 0 2px ${STATUS_INK.pendiente}` }
          : { backgroundColor: STATUS_INK[status] }
      }
    >
      {hollow ? (
        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: STATUS_INK.pendiente }} />
      ) : (
        <Glyph className="h-3 w-3 text-white [&_path]:stroke-[3]" />
      )}
    </span>
  );
}

export function StatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-200">
      <StatusIcon status={status} className="h-4 w-4" />
      {STATUS_LABEL[status]}
    </span>
  );
}
