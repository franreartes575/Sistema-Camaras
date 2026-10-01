"use client";

import { useState } from "react";

import { INPUT_CLASS } from "@/components/ui/controls";
import { formatCoordinatePair, parseCoordinatePair, type LatLon } from "@/lib/coordinates";

/**
 * Un solo campo de texto "latitud, longitud" para pegar directo desde Google
 * Maps. Es texto libre (no `type="number"`) para poder borrar y reescribir sin
 * que el campo se rellene con 0; sólo avisa hacia afuera cuando el contenido
 * es un par válido, y al salir vuelve al último valor bueno si quedó a medias.
 */
export default function CoordinateField({
  value,
  onChange,
  label,
}: {
  value: LatLon;
  onChange: (value: LatLon) => void;
  label: string;
}) {
  const [draft, setDraft] = useState(() => formatCoordinatePair(value));
  const isInvalid = draft.trim() !== "" && parseCoordinatePair(draft) === null;

  return (
    <div className="space-y-1">
      <input
        type="text"
        inputMode="text"
        autoComplete="off"
        spellCheck={false}
        placeholder="-24.775119, -65.427213"
        aria-label={label}
        aria-invalid={isInvalid}
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
          const pair = parseCoordinatePair(event.target.value);
          if (pair) onChange(pair);
        }}
        onBlur={() => {
          if (parseCoordinatePair(draft) === null) setDraft(formatCoordinatePair(value));
        }}
        className={`${INPUT_CLASS} ${isInvalid ? "border-red-400 focus:border-red-400 focus:ring-red-400/20" : ""}`}
      />
      <p className={`text-xs ${isInvalid ? "text-red-300" : "text-slate-500"}`}>
        {isInvalid
          ? "Formato: latitud, longitud (ej. -24.775119, -65.427213)"
          : "Pegá las coordenadas como las copia Google Maps"}
      </p>
    </div>
  );
}
