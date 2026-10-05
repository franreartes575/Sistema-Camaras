"use client";

import { useState } from "react";

import CoordinateField from "@/components/ui/CoordinateField";
import { BUTTON, INPUT_CLASS, Notice } from "@/components/ui/controls";
import type { Depot } from "@/lib/api";
import { createDepot, deleteDepot, updateDepot, type DepotIn } from "@/lib/catalogo";
import { formatCoordinatePair } from "@/lib/coordinates";

type Props = {
  depots: Depot[];
  /** Sólo los administradores cambian las sedes; el resto las ve. */
  canEdit: boolean;
  /** Avisa que cambió algo en el servidor, para volver a leer la lista. */
  onChanged: () => void;
  open?: boolean;
};

// Plaza 9 de Julio: arranque razonable para una sede nueva en Salta.
const NEW_DEPOT: DepotIn = { name: "", lat: -24.7859, lon: -65.4117 };

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : "Error desconocido";
}

/** Una sede editable: los cambios se guardan con el botón, no al tipear. */
function DepotRow({
  depot,
  onSave,
  onRemove,
  onCancel,
}: {
  depot: DepotIn & { id?: number };
  onSave: (depot: DepotIn) => Promise<void>;
  onRemove?: () => Promise<void>;
  onCancel?: () => void;
}) {
  const [draft, setDraft] = useState<DepotIn>({ name: depot.name, lat: depot.lat, lon: depot.lon });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty =
    depot.id === undefined ||
    draft.name.trim() !== depot.name ||
    draft.lat !== depot.lat ||
    draft.lon !== depot.lon;

  const run = (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    action().then(
      () => setBusy(false),
      (err: unknown) => {
        setBusy(false);
        setError(errorText(err));
      },
    );
  };

  return (
    <li className="space-y-1.5 rounded-lg bg-slate-900 p-2.5">
      <input
        type="text"
        placeholder="Nombre de la sede"
        aria-label="Nombre de la sede"
        value={draft.name}
        maxLength={120}
        onChange={(event) => setDraft({ ...draft, name: event.target.value })}
        className={INPUT_CLASS}
      />
      <CoordinateField
        label="Coordenadas de la sede"
        value={{ lat: draft.lat, lon: draft.lon }}
        onChange={(coords) => setDraft({ ...draft, ...coords })}
      />
      <div className="flex flex-wrap items-center justify-end gap-1">
        {onRemove && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              if (window.confirm(`¿Quitar la sede "${depot.name}"?`)) run(onRemove);
            }}
            className={`${BUTTON.ghost} text-red-300 hover:text-red-200`}
          >
            Quitar
          </button>
        )}
        {onCancel && (
          <button type="button" onClick={onCancel} className={BUTTON.ghost}>
            Cancelar
          </button>
        )}
        {dirty && (
          <button
            type="button"
            disabled={busy || !draft.name.trim()}
            onClick={() => run(() => onSave({ ...draft, name: draft.name.trim() }))}
            className="rounded-md bg-sky-500 px-2.5 py-1 text-xs font-semibold text-slate-950 transition hover:bg-sky-400 disabled:bg-slate-800 disabled:text-slate-500"
          >
            {busy ? "Guardando…" : "Guardar"}
          </button>
        )}
      </div>
      {error && <Notice tone="error">{error}</Notice>}
    </li>
  );
}

/**
 * Las sedes (bases operativas) guardadas en el servidor: las mismas para
 * todos. Los administradores las cargan y corrigen; el resto las elige.
 */
export default function DepotEditor({ depots, canEdit, onChanged, open }: Props) {
  const [adding, setAdding] = useState(false);
  // Abierto de entrada si no hay sedes; después manda el usuario (si no, al
  // guardar la primera se cerraría solo).
  const [isOpen, setIsOpen] = useState<boolean | null>(null);
  const shown = isOpen ?? open ?? depots.length === 0;

  return (
    <details className="rounded-lg border border-slate-800 px-3 py-2 open:pb-3" open={shown}>
      <summary
        onClick={(event) => {
          event.preventDefault();
          setIsOpen(!shown);
        }}
        className="cursor-pointer select-none text-xs font-medium text-slate-400 hover:text-slate-200"
      >
        Sedes ({depots.length})
      </summary>
      <div className="mt-3 space-y-2">
        {depots.length === 0 && (
          <p className="text-xs leading-relaxed text-slate-500">
            {canEdit
              ? "Cargá las bases de las cuadrillas una vez y elegilas en cada cluster."
              : "Todavía no hay sedes cargadas: las carga un administrador. Mientras, podés usar coordenadas sueltas."}
          </p>
        )}
        {canEdit ? (
          <ul className="space-y-2">
            {depots.map((depot) => (
              <DepotRow
                // La clave cambia con el contenido: al guardar, el borrador se
                // vuelve a armar con lo que quedó en el servidor.
                key={`${depot.id}|${depot.name}|${depot.lat}|${depot.lon}`}
                depot={depot}
                onSave={async (changes) => {
                  await updateDepot(depot.id, changes);
                  onChanged();
                }}
                onRemove={async () => {
                  await deleteDepot(depot.id);
                  onChanged();
                }}
              />
            ))}
            {adding && (
              <DepotRow
                depot={NEW_DEPOT}
                onSave={async (changes) => {
                  await createDepot(changes);
                  setAdding(false);
                  onChanged();
                }}
                onCancel={() => setAdding(false)}
              />
            )}
          </ul>
        ) : (
          <ul className="space-y-1">
            {depots.map((depot) => (
              <li key={depot.id} className="flex items-baseline justify-between gap-2 rounded-md bg-slate-900 px-2.5 py-1.5 text-xs">
                <span className="truncate font-medium text-slate-200">{depot.name}</span>
                <span className="shrink-0 font-mono text-[11px] text-slate-500">
                  {formatCoordinatePair({ lat: depot.lat, lon: depot.lon })}
                </span>
              </li>
            ))}
          </ul>
        )}
        {canEdit && !adding && (
          <button
            type="button"
            onClick={() => {
              setAdding(true);
              setIsOpen(true);
            }}
            className={BUTTON.secondary}
          >
            + Agregar sede
          </button>
        )}
      </div>
    </details>
  );
}
