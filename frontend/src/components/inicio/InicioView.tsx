"use client";

/**
 * Inicio: lo primero que se ve al entrar. Un resumen del catálogo de cámaras
 * (cuántas hay y dónde), de los planes y del avance de las tareas, y el mapa
 * del catálogo con sus clusters y las sedes.
 *
 * Desde acá se salta a planificar: tocar "planificar" en una localidad deja
 * sus cámaras elegidas en el paso 1 de Planificar.
 */

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";

import CatalogAdmin from "@/components/inicio/CatalogAdmin";
import {
  DepotReachBars,
  KpiTiles,
  LocalityTable,
  MonthlyChart,
  RecentPlans,
  Section,
  VisitAgeBars,
} from "@/components/inicio/Charts";
import { BUTTON, Notice } from "@/components/ui/controls";
import { IconCalendar, IconDatabase, IconShield } from "@/components/ui/icons";
import type { Depot } from "@/lib/api";
import {
  catalogPaths,
  LOCALITY_UNKNOWN,
  type CatalogCamera,
  type CatalogClusters,
  type CatalogSummary,
} from "@/lib/catalogo";
import { formatTimestamp } from "@/lib/format";
import { registryPaths, type PlanSummary } from "@/lib/registro";
import { useJson } from "@/lib/useJson";
import { CLUSTER_PALETTE } from "@/lib/vizTokens";

// MapLibre toca `window`: el mapa se carga sólo en el cliente.
const CatalogMap = dynamic(() => import("@/components/inicio/CatalogMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-slate-500">Cargando mapa…</div>
  ),
});

type AppSection = "inicio" | "plan" | "registro";

type Props = {
  /** Cambia cuando cambian el catálogo o el registro: hay que volver a leer. */
  version: number;
  cameras: CatalogCamera[] | null;
  camerasError: string | null;
  depots: Depot[];
  isAdmin: boolean;
  mobileView: "panel" | "map";
  onCatalogChanged: () => void;
  onPlanCameras: (ids: string[]) => void;
  onOpenSection: (section: AppSection) => void;
};

export default function InicioView({
  version,
  cameras,
  camerasError,
  depots,
  isAdmin,
  mobileView,
  onCatalogChanged,
  onPlanCameras,
  onOpenSection,
}: Props) {
  const [epsKm, setEpsKm] = useState(20);
  const [focused, setFocused] = useState<string | null>(null);
  // null = automático (abierto con el catálogo vacío). Una vez abierto o
  // cerrado, queda así: importar no lo vuelve a cerrar y esconde el resultado.
  const [adminOpen, setAdminOpen] = useState<boolean | null>(null);

  const summary = useJson<CatalogSummary>(catalogPaths.summary, version);
  const plans = useJson<PlanSummary[]>(registryPaths.plans, version);
  const clusters = useJson<CatalogClusters>(catalogPaths.clusters(epsKm, CLUSTER_PALETTE.length), version);

  const allCameras = useMemo(() => cameras ?? [], [cameras]);
  const data = summary.data;

  const planLocality = (name: string) => {
    onPlanCameras(allCameras.filter((camera) => camera.locality === name).map((camera) => camera.id));
  };

  const loadError = summary.error;
  const isAdminOpen = adminOpen ?? data?.camera_count === 0;

  return (
    <div className="flex min-h-0 flex-1">
      <div
        className={`${mobileView === "panel" ? "block" : "hidden"} w-full overflow-y-auto border-slate-800 md:block md:w-[28rem] md:shrink-0 md:border-r lg:w-[34rem] xl:w-[38rem]`}
      >
        <div className="space-y-6 px-4 py-5 md:px-5">
          <header className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h1 className="text-lg font-semibold tracking-tight text-slate-50">Resumen de cámaras</h1>
              <p className="text-xs text-slate-500">
                {data?.last_import_at
                  ? `Catálogo actualizado el ${formatTimestamp(data.last_import_at)}`
                  : "Catálogo, planes y avance de las cuadrillas"}
              </p>
            </div>
            <button
              type="button"
              onClick={() => onOpenSection("plan")}
              className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-sky-400"
            >
              <IconCalendar className="h-3.5 w-3.5" /> Planificar
            </button>
          </header>

          {loadError && !data && (
            <div className="space-y-2">
              <Notice tone="error">No se pudo leer el resumen: {loadError}</Notice>
              <button type="button" onClick={summary.retry} className={BUTTON.secondary}>
                Reintentar
              </button>
            </div>
          )}
          {camerasError && !cameras && (
            <Notice tone="warn">No se pudieron leer las cámaras del mapa: {camerasError}</Notice>
          )}
          {!data && !loadError && <p className="text-sm text-slate-500">Cargando el resumen…</p>}

          {data && (
            <>
              {data.camera_count === 0 && (
                <Notice tone="info">
                  El catálogo todavía está vacío.{" "}
                  {isAdmin
                    ? "Importá la planilla de cámaras en \"Administrar catálogo\", más abajo."
                    : "Un administrador tiene que importar la planilla de cámaras."}
                </Notice>
              )}
              {data.camera_count > 0 && !data.municipalities_loaded && !isAdmin && (
                <Notice tone="info">
                  Las localidades todavía no se calcularon: falta que un administrador cargue los
                  límites de los municipios.
                </Notice>
              )}
              {data.planned_outside_catalog > 0 && (
                <Notice tone="info">
                  {data.planned_outside_catalog} cámara(s) con tareas en el registro no están en el
                  catálogo: no cuentan en las localidades ni en el mapa.
                </Notice>
              )}

              <KpiTiles summary={data} />

              <Section
                title="Cámaras por localidad"
                aside={focused ? (
                  <button type="button" onClick={() => setFocused(null)} className="text-sky-300 hover:text-sky-200">
                    Ver todas en el mapa
                  </button>
                ) : (
                  "tocá una para verla en el mapa"
                )}
              >
                <LocalityTable
                  localities={data.localities}
                  focused={focused}
                  onFocus={setFocused}
                  onPlan={planLocality}
                />
                {data.localities.some((item) => item.name === LOCALITY_UNKNOWN) && isAdmin && (
                  <p className="text-[11px] text-slate-500">
                    &quot;{LOCALITY_UNKNOWN}&quot;: faltan los límites de los municipios (ver Administrar catálogo).
                  </p>
                )}
              </Section>

              <Section title="Tareas por mes" aside={`${data.tasks.total} en total`}>
                <MonthlyChart months={data.months} today={data.today} />
              </Section>

              <div className="grid gap-6 sm:grid-cols-2">
                <Section title="Última visita">
                  <VisitAgeBars summary={data} />
                </Section>
                <Section title="Cámaras por sede más cercana">
                  <DepotReachBars depots={data.depots} />
                </Section>
              </div>

              <Section
                title="Últimos planes"
                aside={
                  <button type="button" onClick={() => onOpenSection("registro")} className="inline-flex items-center gap-1 text-sky-300 hover:text-sky-200">
                    <IconDatabase className="h-3 w-3" /> Ver el registro
                  </button>
                }
              >
                <RecentPlans plans={plans.data ?? []} onOpen={() => onOpenSection("registro")} />
              </Section>
            </>
          )}

          {isAdmin && (
            <details
              className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2.5 open:pb-3"
              open={isAdminOpen}
            >
              <summary
                onClick={(event) => {
                  event.preventDefault();
                  setAdminOpen(!isAdminOpen);
                }}
                className="flex cursor-pointer select-none items-center gap-2 text-sm font-medium text-slate-200"
              >
                <IconShield className="h-4 w-4 text-slate-400" /> Administrar catálogo y sedes
              </summary>
              <div className="mt-3">
                <CatalogAdmin
                  cameras={allCameras}
                  depots={depots}
                  version={version}
                  municipalitiesLoaded={data?.municipalities_loaded ?? true}
                  onChanged={() => {
                    // Lo que se hizo adentro (importar, una sede) se ve abierto,
                    // aunque el catálogo haya dejado de estar vacío.
                    setAdminOpen(true);
                    onCatalogChanged();
                  }}
                />
              </div>
            </details>
          )}
          {!isAdmin && depots.length === 0 && data && data.camera_count > 0 && (
            <p className="text-xs text-slate-500">Todavía no hay sedes cargadas.</p>
          )}
          {data && data.camera_count > 0 && (
            <button type="button" onClick={() => onOpenSection("plan")} className={`${BUTTON.secondary} md:hidden`}>
              Ir a planificar
            </button>
          )}
        </div>
      </div>

      <section
        aria-label="Mapa del catálogo"
        className={`${mobileView === "map" ? "block" : "hidden"} relative min-h-0 flex-1 md:block`}
      >
        <CatalogMap
          cameras={allCameras}
          clusters={clusters.data}
          depots={depots}
          focusedLocality={focused}
          epsKm={epsKm}
          isClustering={clusters.loading}
          onEpsChange={setEpsKm}
        />
        {focused && (
          <div className="absolute bottom-8 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-lg bg-slate-950/90 px-3 py-1.5 text-xs text-slate-200 shadow-lg ring-1 ring-white/10">
            <span>
              Sólo <b>{focused}</b>
            </span>
            <button type="button" onClick={() => planLocality(focused)} className="font-semibold text-sky-300 hover:text-sky-200">
              Planificar
            </button>
            <button type="button" onClick={() => setFocused(null)} className="text-slate-400 hover:text-white">
              Ver todas
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
