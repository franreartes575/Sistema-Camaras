"""POST /export/: el plan con sus fechas, como Excel de seguimiento.

Vive fuera de `main.py` para no seguir engordándolo; se incluye como router.
Igual que el resto de la API, no guarda estado: el plan llega completo en el
cuerpo del request y el archivo se arma en memoria.
"""

from fastapi import APIRouter, Depends, Response

from .config import RATE_LIMIT_UPLOAD_MAX
from .schemas import ExportRequest
from .security import rate_limiter
from .services.export import build_plan_workbook, export_filename

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter()
export_rate_limit = rate_limiter(RATE_LIMIT_UPLOAD_MAX)


@router.post(
    "/export/",
    response_class=Response,
    dependencies=[Depends(export_rate_limit)],
)
def export_plan(plan: ExportRequest) -> Response:
    """Devuelve el .xlsx de seguimiento para que lo completen los técnicos.

    Es `def` y no `async def` a propósito: openpyxl es sincrónico, y FastAPI
    corre las funciones sincrónicas en un hilo sin frenar el event loop.
    """
    return Response(
        content=build_plan_workbook(plan),
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename(plan)}"'
        },
    )
