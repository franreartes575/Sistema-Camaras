"use client";

import { useEffect, useState } from "react";

import type { Depot } from "@/lib/api";

const STORAGE_KEY = "sistema-logistico:sedes";

/** Lee las sedes guardadas en este navegador, o una lista vacía si no hay. */
function loadDepots(): Depot[] {
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

/** Lista editable de sedes: nombre + coordenadas, persistida en el navegador. */
export default function DepotEditor({ depots, onChange }: Props) {
  const [hydrated, setHydrated] = useState(false);

  // Cargar desde localStorage una sola vez, después del primer render (evita
  // desajustes de hidratación entre servidor y cliente).
  useEffect(() => {
    if (!hydrated) {
      const stored = loadDepots();
      if (stored.length > 0) onChange(stored);
      setHydrated(true);
    }
  }, [hydrated, onChange]);

  useEffect(() => {
    if (hydrated) saveDepots(depots);
  }, [depots, hydrated]);

  const addDepot = () => {
    onChange([
      ...depots,
      { id: crypto.randomUUID(), name: "", lat: -24.7859, lon: -65.4117 },
    ]);
  };

  const updateDepot = (id: string, patch: Partial<Depot>) => {
    onChange(depots.map((depot) => (depot.id === id ? { ...depot, ...patch } : depot)));
  };

  const removeDepot = (id: string) => {
    onChange(depots.filter((depot) => depot.id !== id));
  };

  return (
    <div className="space-y-2.5 border-t border-slate-800 pt-4">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Sedes guardadas
      </h2>
      {depots.length === 0 && (
        <p className="text-xs text-slate-500">
          Sin sedes cargadas — podés agregar una o asignar coordenadas sueltas
          a cada cluster más abajo.
        </p>
      )}
      <ul className="space-y-2">
        {depots.map((depot) => (
          <li key={depot.id} className="space-y-1 rounded-md bg-slate-900 p-2">
            <div className="flex items-center gap-2">
              <input
                type="text"
                placeholder="Nombre de la sede"
                value={depot.name}
                onChange={(event) => updateDepot(depot.id, { name: event.target.value })}
                className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
              />
              <button
                type="button"
                onClick={() => removeDepot(depot.id)}
                className="rounded-md px-2 py-1 text-xs text-red-400 hover:bg-red-950"
              >
                Quitar
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input
                type="number"
                step="0.0001"
                placeholder="Latitud"
                value={depot.lat}
                onChange={(event) =>
                  updateDepot(depot.id, { lat: Number(event.target.value) })
                }
                className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
              />
              <input
                type="number"
                step="0.0001"
                placeholder="Longitud"
                value={depot.lon}
                onChange={(event) =>
                  updateDepot(depot.id, { lon: Number(event.target.value) })
                }
                className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
              />
            </div>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={addDepot}
        className="w-full rounded-md border border-dashed border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:border-sky-500 hover:text-sky-400"
      >
        + Agregar sede
      </button>
    </div>
  );
}
