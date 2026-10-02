"""Primitivas criptográficas del módulo de autenticación.

Una sola clave maestra (32 bytes) y, derivadas de ella con HKDF, una clave por
propósito: si una se filtrara por un uso, no sirve para los otros. La maestra
nunca toca la base de datos.
"""

import base64
import hashlib
import hmac
import os
import secrets
import stat
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .. import config

MASTER_KEY_BYTES = 32
_NONCE_BYTES = 12


class ClaveMaestraFaltante(RuntimeError):
    """No hay clave maestra configurada (o no tiene el formato esperado)."""


def generar_clave_maestra() -> str:
    return base64.b64encode(secrets.token_bytes(MASTER_KEY_BYTES)).decode()


def guardar_clave_maestra(ruta: Path) -> None:
    """Crea el archivo de la clave con permisos sólo para el dueño.

    Falla si ya existe: pisar la clave dejaría ilegibles los secretos TOTP y
    rota la verificación de la auditoría.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(ruta, flags, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w", encoding="ascii") as archivo:
        archivo.write(generar_clave_maestra())


@lru_cache(maxsize=4)
def _decodificar(texto: str) -> bytes:
    try:
        clave = base64.b64decode(texto.strip(), validate=True)
    except ValueError as exc:
        raise ClaveMaestraFaltante("La clave maestra no es base64 válido.") from exc
    if len(clave) != MASTER_KEY_BYTES:
        raise ClaveMaestraFaltante(
            f"La clave maestra debe tener {MASTER_KEY_BYTES} bytes (tiene {len(clave)})."
        )
    return clave


def clave_maestra() -> bytes:
    if config.AUTH_MASTER_KEY:
        return _decodificar(config.AUTH_MASTER_KEY)
    ruta = Path(config.AUTH_MASTER_KEY_FILE)
    if not ruta.is_file():
        raise ClaveMaestraFaltante(
            "Falta la clave maestra. Generala con `python -m app.auth.cli inicializar` "
            "o definí AUTH_MASTER_KEY."
        )
    return _decodificar(ruta.read_text(encoding="ascii"))


@lru_cache(maxsize=16)
def _derivar(maestra: bytes, proposito: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"recorridos-camaras/{proposito}".encode(),
    ).derive(maestra)


def subclave(proposito: str) -> bytes:
    return _derivar(clave_maestra(), proposito)


def cifrar(texto: str, contexto: str) -> str:
    """AES-256-GCM. `contexto` (p. ej. el id del usuario) va como dato
    asociado: un secreto copiado a la fila de otro usuario no descifra."""
    nonce = secrets.token_bytes(_NONCE_BYTES)
    cifrado = AESGCM(subclave("totp")).encrypt(nonce, texto.encode(), contexto.encode())
    return base64.b64encode(nonce + cifrado).decode()


def descifrar(blob: str, contexto: str) -> str:
    crudo = base64.b64decode(blob)
    nonce, cifrado = crudo[:_NONCE_BYTES], crudo[_NONCE_BYTES:]
    return AESGCM(subclave("totp")).decrypt(nonce, cifrado, contexto.encode()).decode()


def firmar(proposito: str, datos: str) -> str:
    return hmac.new(subclave(proposito), datos.encode(), hashlib.sha256).hexdigest()


def nuevo_token(bytes_aleatorios: int = 32) -> str:
    """Token opaco de 256 bits por defecto, apto para una cookie."""
    return secrets.token_urlsafe(bytes_aleatorios)


def hash_token(token: str) -> str:
    """Los tokens se guardan sólo como hash: con la base robada no se puede
    reconstruir una cookie. SHA-256 alcanza porque el token ya es aleatorio
    de 256 bits (no hay diccionario que probar)."""
    return hashlib.sha256(token.encode()).hexdigest()
