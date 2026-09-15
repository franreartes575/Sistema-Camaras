"""Configuración central del backend.

Todos los servicios externos son de código abierto y self-hosted:
- OSRM: motor de ruteo local (matriz de distancias + polilíneas).
"""

import os

# Instancia local de OSRM. Sin dependencias de Google Maps.
OSRM_BASE_URL: str = os.getenv("OSRM_BASE_URL", "http://localhost:5000")

# Orígenes permitidos para el frontend Next.js en desarrollo.
CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Extensiones aceptadas en la carga de planillas.
ALLOWED_UPLOAD_EXTENSIONS: tuple[str, ...] = (".xlsx", ".xlsm", ".csv")

# Tope de subida. Una planilla de cámaras real pesa unos pocos MB; el límite
# existe para que un archivo enorme no agote la memoria del proceso, sea por
# error o a propósito. Se aplica leyendo por partes, no después de cargar todo.
MAX_UPLOAD_BYTES: int = 32 * 1024 * 1024

# Tamaño de cada bloque al leer el archivo subido.
UPLOAD_CHUNK_BYTES: int = 1024 * 1024
