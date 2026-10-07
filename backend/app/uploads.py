"""Lectura validada de archivos subidos, compartida por todos los routers."""

import io
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile

from . import config
from .config import ALLOWED_UPLOAD_EXTENSIONS, MAX_UPLOAD_BYTES, UPLOAD_CHUNK_BYTES

_ZIPPED_EXTENSIONS = (".xlsx", ".xlsm")


def _check_uncompressed_size(raw: bytes) -> None:
    """Rechaza un .xlsx que descomprimido supera el tope (bomba zip).

    Mira sólo el índice del zip, sin descomprimir nada. Si no es un zip
    válido no decide acá: lo rechaza después openpyxl con el error de
    siempre ("no se pudo leer la planilla").
    """
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            total = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        return
    if total > config.MAX_XLSX_UNCOMPRESSED_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"La planilla descomprimida supera el límite de "
                f"{config.MAX_XLSX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB."
            ),
        )


async def read_upload(file: UploadFile) -> tuple[str, bytes]:
    """Valida la extensión y el tamaño, y devuelve el contenido del archivo."""
    filename = file.filename or "sin-nombre"
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Extensión '{suffix or 'desconocida'}' no soportada. "
                f"Use: {', '.join(ALLOWED_UPLOAD_EXTENSIONS)}"
            ),
        )

    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"El archivo supera el límite de "
                    f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                ),
            )
        chunks.append(chunk)

    if not chunks:
        raise HTTPException(status_code=400, detail="El archivo llegó vacío.")

    raw = b"".join(chunks)
    if suffix in _ZIPPED_EXTENSIONS:
        _check_uncompressed_size(raw)
    return filename, raw
