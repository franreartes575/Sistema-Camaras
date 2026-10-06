"use client";

/**
 * Panel lateral: la planificación como una secuencia de cinco pasos.
 *
 * Este componente sólo decide el estado de cada paso (bloqueado, activo,
 * listo), cuál está desplegado y qué resumen muestra plegado; el contenido de
 * cada paso vive en `components/panel/`.
 */

import { useState } from "react";

import FileStep, { type CatalogInput, type InputMode } from "@/components/panel/FileStep";
import PlanStep from "@/components/panel/PlanStep";
import { ClusterStep, RulesStep, StartsStep } from "@/components/panel/SetupSteps";
import { Notice } from "@/components/ui/controls";
import { IconCalendar, IconLayers, IconPin, IconSheet, IconSliders } from "@/components/ui/icons";
import Step, { type StepStatus } from "@/components/ui/Step";
import type {
  ClusterParams,
  ClusterStart,
  ColumnMapping,
  Depot,
  OptimizeResponse,
  ProcessResponse,
  RouteParams,
  UploadExcelResponse,
} from "@/lib/api";
import type { FollowUpResult } from "@/lib/registro";

/** Qué pasó con el registro al subir la planilla actual en el paso 1. */
export type RegistroSync =
  | { file: File; kind: "synced"; result: FollowUpResult }
  | { file: File; kind: "error"; message: string }
  | { file: File; kind: "from-registry" };

export type RegistroStatus = "unsaved" | "saved" | "outdated";

type Props = {
  upload: UploadExcelResponse | null;
  mapping: ColumnMapping;
  params: ClusterParams;
  routing: RouteParams;
  depots: Depot[];
  preview: ProcessResponse | null;
  clusterStarts: Record<number, ClusterStart>;
  result: OptimizeResponse | null;
  isLoading: boolean;
  error: string | null;
  selectedCluster: number | null;
  selectedDay: number | null;
  routeDates: Record<string, string>;
  planStart: string;
  skipWeekends: boolean;
  isExporting: boolean;
  onFile: (file: File) => void;
  onMappingChange: (mapping: ColumnMapping) => void;
  onParamsChange: (params: ClusterParams) => void;
  onRoutingChange: (routing: RouteParams) => void;
  /** Sólo los administradores cambian las sedes. */
  canEditDepots: boolean;
  onDepotsChanged: () => void;
  inputMode: InputMode;
  catalog: CatalogInput;
  onInputModeChange: (mode: InputMode) => void;
  onClusterStartsChange: (starts: Record<number, ClusterStart>) => void;
  onPreview: () => void;
  onOptimize: () => void;
  /** Resalta una jornada (cluster + día); `(null, null)` deselecciona. */
  onSelectRoute: (cluster: number | null, day: number | null) => void;
  onPlanStartChange: (iso: string) => void;
  onSkipWeekendsChange: (skip: boolean) => void;
  onRouteDateChange: (key: string, iso: string) => void;
  onExport: () => void;
  /** Si el plan actual ya está en el registro (y con estas fechas). */
  registroStatus: RegistroStatus;
  savedPlanName: string | null;
  isSavingPlan: boolean;
  registroNotice: { tone: "warn" | "error"; text: string } | null;
  registroSync: RegistroSync | null;
  onSaveToRegistry: () => void;
  onOpenRegistry: () => void;
};

type StepId = "file" | "cluster" | "starts" | "rules" | "plan";

function hasCoordinateColumns(mapping: ColumnMapping): boolean {
  return mapping.mode === "single"
    ? Boolean(mapping.col_coords)
    : Boolean(mapping.col_lat && mapping.col_lon);
}

function rulesSummary(routing: RouteParams): string {
  const { min_stops_per_day: min, max_stops_per_day: max } = routing;
  const perDay =
    min && max ? (min === max ? `${min}` : `${min}–${max}`) : max ? `hasta ${max}` : min ? `${min}+` : "sin límite de";
  return `${routing.day_budget_s / 3600} h · ${perDay} cámaras/día · ${routing.service_time_s / 60} min c/u`;
}

export default function ControlPanel(props: Props) {
  const { upload, mapping, routing, preview, clusterStarts, result, isLoading, error } = props;
  const [expanded, setExpanded] = useState<Partial<Record<StepId, boolean>>>({});

  const mappingReady = Boolean(upload && mapping.col_id && hasCoordinateColumns(mapping));
  const missingStarts =
    preview?.clusters.filter((cluster) => clusterStarts[cluster.id] === undefined).length ?? 0;
  const startsReady = preview !== null && preview.clusters.length > 0 && missingStarts === 0;

  const status: Record<StepId, StepStatus> = {
    file: preview ? "done" : "active",
    cluster: !mappingReady ? "locked" : preview ? "done" : "active",
    starts: !preview ? "locked" : startsReady ? "done" : "active",
    rules: !startsReady ? "locked" : result ? "done" : "active",
    plan: result ? "active" : "locked",
  };
  // Sin elección explícita del usuario, se despliega lo que está por hacerse.
  const isOpen = (id: StepId) => expanded[id] ?? status[id] === "active";
  const toggle = (id: StepId) => setExpanded((prev) => ({ ...prev, [id]: !isOpen(id) }));
  const stepProps = (id: StepId) => ({ status: status[id], isOpen: isOpen(id), onToggle: () => toggle(id) });

  const assigned = preview ? preview.clusters.length - missingStarts : 0;

  return (
    <div>
      {error && (
        <div className="mb-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      {result?.warning && (
        <div className="mb-4">
          <Notice tone="warn">{result.warning}</Notice>
        </div>
      )}

      <Step
        number={1}
        title="Cámaras"
        icon={<IconSheet />}
        summary={
          !upload
            ? undefined
            : props.catalog.plannedCount !== null
              ? `${props.catalog.plannedCount} cámara(s) del catálogo`
              : `${upload.filename}${mapping.col_done ? " · seguimiento" : ""}`
        }
        {...stepProps("file")}
      >
        <FileStep
          upload={upload}
          mapping={mapping}
          isLoading={isLoading}
          registroSync={props.registroSync}
          inputMode={props.inputMode}
          catalog={props.catalog}
          onInputModeChange={props.onInputModeChange}
          onFile={props.onFile}
          onMappingChange={props.onMappingChange}
          onOpenRegistry={props.onOpenRegistry}
        />
      </Step>

      <Step
        number={2}
        title="Agrupar cámaras"
        icon={<IconLayers />}
        lockedHint="Primero elegí las cámaras del catálogo o subí una planilla."
        summary={
          preview
            ? `${preview.stats.valid_rows} cámaras · ${preview.stats.cluster_count} cluster(s)` +
              (preview.stats.discarded_rows ? ` · ${preview.stats.discarded_rows} descartadas` : "")
            : undefined
        }
        {...stepProps("cluster")}
      >
        <ClusterStep
          params={props.params}
          preview={preview}
          depotCount={props.depots.length}
          canPreview={mappingReady && !isLoading}
          isLoading={isLoading}
          onParamsChange={props.onParamsChange}
          onPreview={props.onPreview}
        />
      </Step>

      <Step
        number={3}
        title="Puntos de partida"
        icon={<IconPin />}
        lockedHint="Primero agrupá las cámaras."
        summary={preview ? `${assigned} de ${preview.clusters.length} cluster(s) con salida` : undefined}
        {...stepProps("starts")}
      >
        {preview && (
          <StartsStep
            depots={props.depots}
            canEditDepots={props.canEditDepots}
            preview={preview}
            clusterStarts={clusterStarts}
            onDepotsChanged={props.onDepotsChanged}
            onClusterStartsChange={props.onClusterStartsChange}
          />
        )}
      </Step>

      <Step
        number={4}
        title="Reglas del día"
        icon={<IconSliders />}
        lockedHint={
          missingStarts > 0 ? `Falta la salida de ${missingStarts} cluster(s).` : "Primero elegí las salidas."
        }
        summary={rulesSummary(routing)}
        {...stepProps("rules")}
      >
        <RulesStep
          routing={routing}
          canOptimize={startsReady && !isLoading}
          isLoading={isLoading}
          hasResult={result !== null}
          onRoutingChange={props.onRoutingChange}
          onOptimize={props.onOptimize}
        />
      </Step>

      <Step
        number={5}
        title="Plan y fechas"
        icon={<IconCalendar />}
        lockedHint="Calculá los recorridos para ver el plan."
        isLast
        {...stepProps("plan")}
      >
        {result && (
          <PlanStep
            result={result}
            routeDates={props.routeDates}
            planStart={props.planStart}
            skipWeekends={props.skipWeekends}
            selectedCluster={props.selectedCluster}
            selectedDay={props.selectedDay}
            isExporting={props.isExporting}
            onPlanStartChange={props.onPlanStartChange}
            onSkipWeekendsChange={props.onSkipWeekendsChange}
            onRouteDateChange={props.onRouteDateChange}
            onSelectRoute={props.onSelectRoute}
            onExport={props.onExport}
            registroStatus={props.registroStatus}
            savedPlanName={props.savedPlanName}
            isSavingPlan={props.isSavingPlan}
            registroNotice={props.registroNotice}
            onSaveToRegistry={props.onSaveToRegistry}
            onOpenRegistry={props.onOpenRegistry}
          />
        )}
      </Step>
    </div>
  );
}
