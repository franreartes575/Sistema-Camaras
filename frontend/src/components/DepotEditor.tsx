"use client";

import { useEffect } from "react";

import { BUTTON } from "@/components/ui/controls";
import type { Depot } from "@/lib/api";

const STORAGE_KEY = "sistema-logistico:sedes";

/**
 * Lee las sedes guardadas en este navegador, o una lista vacía si no hay.
 *
 * Pensada para el inicializador de `useState` del dueño del estado: en el
 * render del servidor no hay `window` y devuelve vacío. No provoca desajustes
 * de hidratación porque las sedes recién se dibujan en el paso 3, que sólo
 * existe del lado del cliente.
 */
export function loadDepots(): Depot[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Depot[]) : [];
  } catch {
    return [];
  }
}

function saveDepots(depots: Depot[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(depots));
  } catch {
    // localStorage puede fallar (modo privado, cuota llena): no es crítico,
    // la lista sigue funcionando en memoria durante la sesión.
  }
}

type Props = {
  depots: Depot[];
  onChange: (depots: Depot[]) => void;
};

const INPUT =
  "w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-sky-400 focus:outline-none";

/** Lista editable de sedes: nombre + coordenadas, persistida en el navegador. */
export default function DepotEditor({ depots, onChange }: Props) {
  // Sincroniza hacia afuera (localStorage); no escribe estado de React.
  useEffect(() => {
    saveDepots(depots);
  }, [depots]);

  const addDepot = () => {
    onChange([...depots, { id: crypto.randomUUID(), name: "", lat: -24.7859, lon: -65.4117 }]);
  };

  const updateDepot = (id: string, patch: Partial<Depot>) => {
    onChange(depots.map((depot) => (depot.id === id ? { ...depot, ...patch } : depot)));
  };

  const removeDepot = (id: string) => {
    onChange(depots.filter((depot) => depot.id !== id));
  };

  return (
    <details className="rounded-lg border border-slate-800 px-3 py-2 open:pb-3" open={depots.length === 0}>
      <summary className="cursor-pointer select-none text-xs font-medium text-slate-400 hover:text-slate-200">
        Sedes guardadas ({depots.length})
      </summary>
      <div className="mt-3 space-y-2">
        {depots.length === 0 && (
          <p className="text-xs leading-relaxed text-slate-500">
            Guardá la base de la cuadrilla una vez y elegila en cada cluster. También
            podés usar coordenadas sueltas.
          </p>
        )}
        <ul className="space-y-2">
          {depots.map((depot) => (
            <li key={depot.id} className="space-y-1.5">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder="Nombre de la sede"
                  aria-label="Nombre de la sede"
                  value={depot.name}
                  onChange={(event) => updateDepot(depot.id, { name: event.target.value })}
                  className={INPUT}
                />
                <button type="button" onClick={() => removeDepot(depot.id)} className={`${BUTTON.ghost} text-red-300 hover:text-red-200`}>
                  Quitar
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="number"
                  step="0.0001"
                  placeholder="Latitud"
                  aria-label="Latitud de la sede"
                  value={depot.lat}
                  onChange={(event) => updateDepot(depot.id, { lat: Number(event.target.value) })}
                  className={INPUT}
                />
                <input
                  type="number"
                  step="0.0001"
                  placeholder="Longitud"
                  aria-label="Longitud de la sede"
                  value={depot.lon}
                  onChange={(event) => updateDepot(depot.id, { lon: Number(event.target.value) })}
                  className={INPUT}
                />
              </div>
            </li>
          ))}
        </ul>
        <button type="button" onClick={addDepot} className={BUTTON.secondary}>
          + Agregar sede
        </button>
      </div>
    </details>
  );
}
