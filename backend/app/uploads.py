"""Lectura validada de archivos subidos, compartida por todos los routers."""

from pathlib import Path

from fastapi import HTTPException, UploadFile

from .config import ALLOWED_UPLOAD_EXTENSIONS, MAX_UPLOAD_BYTES, UPLOAD_CHUNK_BYTES


async def read_upload(file: UploadFile) -> tuple[str, bytes]:
    """Valida la extensión y devuelve el contenido del archivo."""
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

    return filename, b"".join(chunks)
