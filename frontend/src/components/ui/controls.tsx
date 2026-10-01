/** Controles de formulario del panel, con un único lenguaje visual. */

import type { ReactNode } from "react";

/** Clases de botón por jerarquía: una acción primaria por paso, como mucho. */
export const BUTTON = {
  primary:
    "inline-flex w-full items-center justify-center gap-2 rounded-lg bg-sky-500 px-3 py-2.5 text-sm font-semibold text-slate-950 shadow-sm shadow-sky-500/20 transition hover:bg-sky-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-500 disabled:shadow-none",
  secondary:
    "inline-flex w-full items-center justify-center gap-2 rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 text-sm font-medium text-slate-100 transition hover:border-slate-500 hover:bg-slate-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300 disabled:cursor-not-allowed disabled:text-slate-500",
  ghost:
    "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-slate-400 transition hover:bg-slate-800 hover:text-slate-100 focus-visible:outline-2 focus-visible:outline-sky-300",
} as const;

const FIELD =
  "w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-2 text-sm text-slate-100 transition focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-400/20";

export const INPUT_CLASS = FIELD;

export function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="mb-1 block text-xs font-medium text-slate-400">{children}</span>;
}

export function Select({
  label,
  value,
  options,
  hint,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; text: string }[];
  hint?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <FieldLabel>{label}</FieldLabel>
      <select value={value} onChange={(event) => onChange(event.target.value)} className={FIELD}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.text}
          </option>
        ))}
      </select>
      {hint && <span className="mt-1 block text-xs leading-relaxed text-slate-500">{hint}</span>}
    </label>
  );
}

/** Selector de columna de la planilla; con `optional`, admite "ninguna". */
export function ColumnField({
  label,
  value,
  columns,
  optional,
  onChange,
}: {
  label: string;
  value: string;
  columns: string[];
  optional?: boolean;
  onChange: (value: string) => void;
}) {
  const options = [
    ...(optional ? [{ value: "", text: "— ninguna —" }] : []),
    ...columns.map((column) => ({ value: column, text: column })),
  ];
  return <Select label={label} value={value} options={options} onChange={onChange} />;
}

export function Slider({
  label,
  value,
  display,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  display: string;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-baseline justify-between gap-2 text-xs text-slate-400">
        <span>{label}</span>
        <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] font-medium text-slate-100">
          {display}
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-sky-400"
      />
    </label>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 text-sm text-slate-300">
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 accent-sky-400"
      />
    </label>
  );
}

/** Cifra corta con rótulo, para los totales del resultado. */
export function Stat({ label, value, tone = "default" }: {
  label: string;
  value: ReactNode;
  tone?: "default" | "muted" | "warn";
}) {
  const valueColor =
    tone === "warn" ? "text-amber-300" : tone === "muted" ? "text-slate-400" : "text-slate-50";
  return (
    <div className="rounded-lg bg-slate-900 px-3 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className={`text-lg font-semibold tabular-nums ${valueColor}`}>{value}</dd>
    </div>
  );
}

/** Aviso en línea. `tone` define la gravedad; el texto siempre explica. */
export function Notice({ tone, children }: { tone: "warn" | "error" | "info"; children: ReactNode }) {
  const styles = {
    warn: "border-amber-500/30 bg-amber-500/10 text-amber-100",
    error: "border-red-500/40 bg-red-500/10 text-red-100",
    info: "border-sky-500/30 bg-sky-500/10 text-sky-100",
  }[tone];
  return (
    <p role={tone === "error" ? "alert" : "status"} className={`rounded-lg border px-3 py-2 text-sm leading-relaxed ${styles}`}>
      {children}
    </p>
  );
}
