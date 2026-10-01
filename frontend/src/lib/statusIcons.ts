/**
 * Íconos de estado para el mapa del registro, dibujados en un canvas.
 *
 * Se dibujan acá y no con un glifo de texto porque el servidor de glifos de
 * OpenMapTiles no trae ✓ ni ✕. Cada estado tiene una forma propia además del
 * color (ver STATUS_INK): verde y rojo solos no se distinguen con daltonismo.
 */

import type { Map as MapLibre } from "maplibre-gl";

import type { TaskStatus } from "@/lib/registro";
import { MARK_RING, PENDING_RING, STATUS_INK } from "@/lib/vizTokens";

const SIZE = 22; // px CSS
const RATIO = 2; // nítido en pantallas de alta densidad

export const STATUSES: TaskStatus[] = ["realizada", "no_realizada", "pendiente", "reprogramada"];

export function statusIconId(status: TaskStatus): string {
  return `estado-${status}`;
}

function drawIcon(status: TaskStatus): ImageData {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE * RATIO;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D no disponible");
  ctx.scale(RATIO, RATIO);
  const center = SIZE / 2;

  // Halo blanco con una sombra suave: separa el ícono del mapa de fondo.
  ctx.shadowColor = "rgba(15, 23, 42, 0.45)";
  ctx.shadowBlur = 2;
  ctx.beginPath();
  ctx.arc(center, center, center - 1.5, 0, Math.PI * 2);
  ctx.fillStyle = MARK_RING;
  ctx.fill();
  ctx.shadowColor = "transparent";

  const body = center - 3.5;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  if (status === "pendiente") {
    // Hueco: todavía no pasó nada.
    ctx.beginPath();
    ctx.arc(center, center, body - 1, 0, Math.PI * 2);
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = PENDING_RING;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(center, center, 2, 0, Math.PI * 2);
    ctx.fillStyle = PENDING_RING;
    ctx.fill();
  } else {
    ctx.beginPath();
    ctx.arc(center, center, body, 0, Math.PI * 2);
    ctx.fillStyle = STATUS_INK[status];
    ctx.fill();
    ctx.strokeStyle = MARK_RING;
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    if (status === "realizada") {
      ctx.moveTo(center - 4, center + 0.2);
      ctx.lineTo(center - 1, center + 3);
      ctx.lineTo(center + 4.2, center - 3);
    } else if (status === "no_realizada") {
      ctx.moveTo(center - 3.4, center - 3.4);
      ctx.lineTo(center + 3.4, center + 3.4);
      ctx.moveTo(center + 3.4, center - 3.4);
      ctx.lineTo(center - 3.4, center + 3.4);
    } else {
      // Reprogramada: flecha hacia adelante ("pasó a otro plan").
      ctx.moveTo(center - 4, center);
      ctx.lineTo(center + 3.5, center);
      ctx.moveTo(center + 0.5, center - 3);
      ctx.lineTo(center + 3.5, center);
      ctx.lineTo(center + 0.5, center + 3);
    }
    ctx.stroke();
  }
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

/** Registra los íconos en el mapa (una vez; el estilo no se recarga). */
export function addStatusIcons(map: MapLibre): void {
  for (const status of STATUSES) {
    const id = statusIconId(status);
    if (!map.hasImage(id)) map.addImage(id, drawIcon(status), { pixelRatio: RATIO });
  }
}
