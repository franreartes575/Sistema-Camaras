"""Configuración central del backend.

Todos los servicios externos son de código abierto y self-hosted:
- OSRM: motor de ruteo local (matriz de distancias + polilíneas).
"""

import os
from pathlib import Path

# Instancia local de OSRM. Sin dependencias de Google Maps.
OSRM_BASE_URL: str = os.getenv("OSRM_BASE_URL", "http://localhost:5000")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


# Orígenes desde los que el navegador puede mandar pedidos que cambian algo
# (chequeo de `Origin` contra CSRF). El frontend llega al backend a través del
# rewrite `/api` de Next.js, así que es el origen del frontend, no el del
# backend. En producción: la URL HTTPS pública, y nada más.
ALLOWED_ORIGINS: list[str] = _csv(
    "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
)

# Documentación interactiva (/docs, /openapi.json). Apagada por defecto: expone
# la superficie completa de la API. Para desarrollo: API_DOCS=1.
API_DOCS: bool = os.getenv("API_DOCS", "").lower() in ("1", "true", "yes")

# Base SQLite del registro de recorridos. Es un único archivo: respaldarlo es
# copiarlo (o descargarlo desde la sección Registro). `data/` está ignorada por
# git — los registros son datos de operación, no código.
DB_PATH: str = os.getenv("DB_PATH", str(_DATA_DIR / "recorridos.db"))

# Límites de los municipios de Salta (capa `municipio` del IGN), con los que se
# calcula la localidad de cada cámara del catálogo sin consultar servicios
# externos. Va con el código (no es dato de operación) y se genera una sola vez
# con `python -m app.catalogo_cli preparar-municipios`.
MUNICIPIOS_PATH: str = os.getenv(
    "MUNICIPIOS_PATH",
    str(Path(__file__).resolve().parent / "data" / "municipios_salta.geojson"),
)

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
# El registro se consulta seguido (cada filtro es una lectura): tope holgado.
RATE_LIMIT_REGISTRO_MAX: int = int(os.getenv("RATE_LIMIT_REGISTRO_MAX", "240"))
# El catálogo también: el Inicio y el selector de cámaras lo leen al abrirse.
RATE_LIMIT_CATALOGO_MAX: int = int(os.getenv("RATE_LIMIT_CATALOGO_MAX", "240"))

# Proxies cuyo `X-Forwarded-For` se cree (CIDR separados por coma). La IP real
# del cliente es la primera, contando desde la derecha, que NO es uno de estos.
# Por defecto sólo loopback: el rewrite `/api` de Next.js corre en la misma
# máquina. Un header de un par que no está en la lista se ignora: si no, el
# cliente podría inventarse la IP con que queda en la auditoría.
TRUSTED_PROXIES: list[str] = _csv("TRUSTED_PROXIES", "127.0.0.1/32,::1/128")

# --------------------------------------------------------------------------
# Autenticación
# --------------------------------------------------------------------------

# Base de seguridad: usuarios, sesiones y auditoría. Separada de
# la del registro a propósito: el respaldo del registro no debe llevarse hashes
# de contraseñas ni la auditoría.
AUTH_DB_PATH: str = os.getenv("AUTH_DB_PATH", str(_DATA_DIR / "seguridad.db"))

# Clave maestra (32 bytes en base64) de la que se derivan las claves para
# firmar la cadena de auditoría. Por variable de entorno, o en un archivo que crea
# `python -m app.auth.cli inicializar`. Sin clave el backend no arranca.
AUTH_MASTER_KEY: str = os.getenv("AUTH_MASTER_KEY", "")
AUTH_MASTER_KEY_FILE: str = os.getenv(
    "AUTH_MASTER_KEY_FILE", str(_DATA_DIR / "clave_maestra.key")
)

# Sesión: se cierra tras SESSION_IDLE_MINUTES sin actividad y, pase lo que
# pase, a las SESSION_ABSOLUTE_HOURS. El token se rota cada
# SESSION_ROTATE_MINUTES; el anterior sigue valiendo SESSION_ROTATION_GRACE_S
# segundos para los pedidos que ya estaban en vuelo, y después usarlo se toma
# como robo: se revoca la sesión entera.
SESSION_IDLE_MINUTES: int = _int("SESSION_IDLE_MINUTES", 15)
SESSION_ABSOLUTE_HOURS: int = _int("SESSION_ABSOLUTE_HOURS", 8)
SESSION_ROTATE_MINUTES: int = _int("SESSION_ROTATE_MINUTES", 5)
SESSION_ROTATION_GRACE_S: int = _int("SESSION_ROTATION_GRACE_S", 30)
MAX_SESSIONS_PER_USER: int = _int("MAX_SESSIONS_PER_USER", 3)
# Un cambio de navegador a mitad de sesión es una cookie copiada a otro equipo.
SESSION_BIND_USER_AGENT: bool = os.getenv("SESSION_BIND_USER_AGENT", "1").lower() in (
    "1", "true", "yes",
)

# Bloqueo de cuenta: LOCKOUT_THRESHOLD fallos seguidos bloquean
# LOCKOUT_BASE_MINUTES, el doble cada vez; al bloqueo número
# LOCKOUT_MAX_TEMPORARY + 1 la cuenta queda bloqueada hasta que la desbloquee
# un administrador.
LOCKOUT_THRESHOLD: int = _int("LOCKOUT_THRESHOLD", 5)
LOCKOUT_BASE_MINUTES: int = _int("LOCKOUT_BASE_MINUTES", 15)
LOCKOUT_MAX_TEMPORARY: int = _int("LOCKOUT_MAX_TEMPORARY", 3)

# Límite de intentos fallidos en la ventana, por IP y por nombre de usuario
# (exista o no: si no, el límite delataría qué usuarios existen). Se cuentan en
# la auditoría, así que sobreviven a un reinicio del proceso.
LOGIN_WINDOW_MINUTES: int = _int("LOGIN_WINDOW_MINUTES", 15)
LOGIN_MAX_FAILURES_PER_IP: int = _int("LOGIN_MAX_FAILURES_PER_IP", 20)
LOGIN_MAX_FAILURES_PER_USER: int = _int("LOGIN_MAX_FAILURES_PER_USER", 10)

PASSWORD_MIN_LENGTH: int = _int("PASSWORD_MIN_LENGTH", 14)
