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

# Clave exigida en el header `X-API-Key` para los endpoints que reciben
# archivos. Vacía por defecto: deshabilita el chequeo para desarrollo local
# sin configuración extra. Antes de exponer el servicio a la red hay que
# setearla — ver la sección correspondiente en CLAUDE.md.
API_KEY: str = os.getenv("API_KEY", "")

# Limitación de tasa en memoria, por IP de origen. No sobrevive un reinicio
# del proceso ni se comparte entre réplicas: alcanza para un único backend
# detrás de un reverse proxy, que es el despliegue que asume este proyecto.
RATE_LIMIT_WINDOW_S: float = float(os.getenv("RATE_LIMIT_WINDOW_S", "60"))
RATE_LIMIT_UPLOAD_MAX: int = int(os.getenv("RATE_LIMIT_UPLOAD_MAX", "30"))
RATE_LIMIT_PROCESS_MAX: int = int(os.getenv("RATE_LIMIT_PROCESS_MAX", "20"))
# /optimize/ corre OR-Tools hasta time_limit_s por cluster: el tope más bajo
# es a propósito, es el endpoint caro de este servicio.
RATE_LIMIT_OPTIMIZE_MAX: int = int(os.getenv("RATE_LIMIT_OPTIMIZE_MAX", "10"))

# Si el backend corre detrás de un reverse proxy que setea `X-Forwarded-For`
# con la IP real del cliente, esto habilita usarla para el rate limiting por
# IP en vez de la IP del proxy (que sería la misma para todo el mundo).
# Deshabilitado por defecto: confiar en ese header sin controlar que venga
# del proxy esperado permite falsificar la IP de origen.
TRUST_PROXY_HEADERS: bool = os.getenv("TRUST_PROXY_HEADERS", "").lower() in (
    "1",
    "true",
    "yes",
)
