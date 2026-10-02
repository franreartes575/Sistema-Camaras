"use client";

import { useState } from "react";

import { INPUT_CLASS } from "@/components/ui/controls";

/**
 * Campo para escribir un entero. Sólo acepta dígitos y confirma al salir del
 * campo o con Enter, así los acoplamientos entre campos (p. ej. mínimo y
 * máximo) no se disparan con cada tecla. Vacío equivale a 0 y se muestra con
 * `emptyText` como texto de relleno.
 */
export default function IntegerField({
  label,
  value,
  max,
  emptyText,
  onChange,
}: {
  label: string;
  value: number;
  max: number;
  emptyText: string;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);

  function commit() {
    if (draft === null) return;
    const parsed = draft === "" ? 0 : Math.min(Number(draft), max);
    setDraft(null);
    if (parsed !== value) onChange(parsed);
  }

  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-slate-400">{label}</span>
      <input
        type="text"
        inputMode="numeric"
        autoComplete="off"
        value={draft ?? (value === 0 ? "" : String(value))}
        placeholder={emptyText}
        onFocus={(event) => event.target.select()}
        onChange={(event) => setDraft(event.target.value.replace(/\D/g, "").slice(0, 3))}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") setDraft(null);
        }}
        className={INPUT_CLASS}
      />
    </label>
  );
}
