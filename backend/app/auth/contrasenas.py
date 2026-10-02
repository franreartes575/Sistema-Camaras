"""Contraseñas: Argon2id y la política para elegir una nueva.

Argon2id con los parámetros por defecto de argon2-cffi (RFC 9106, perfil de
baja memoria: 64 MiB, 3 pasadas, 4 hilos). Si se suben, `necesita_rehash`
avisa y el login vuelve a hashear con los nuevos al entrar.

La política sigue NIST SP 800-63B: largo mínimo alto, sin reglas de
composición (empujan a "Salta2026!"), y rechazo de contraseñas conocidas o
derivadas del nombre de usuario.
"""

import secrets
import unicodedata
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .. import config

PASSWORD_MAX_LENGTH = 128

_hasher = PasswordHasher()

# Las más usadas y las obvias para este sistema. No reemplaza una lista de
# filtradas (no hay salida a internet para consultarla), pero corta lo peor.
_COMUNES = frozenset(
    {
        "123456789012", "1234567890123", "12345678901234", "123456789012345",
        "qwertyuiopasdf", "qwertyuiop1234", "contraseña1234", "contrasena1234",
        "password123456", "passwordpassword", "administrador1", "administrador123",
        "salta123456789", "camaras1234567", "policia1234567", "seguridad12345",
        "aaaaaaaaaaaaaa", "abcdefghijklmn", "abcdef12345678", "iloveyou123456",
    }
)


def normalizar(password: str) -> str:
    """NFKC: la misma contraseña tipeada en otro teclado da los mismos bytes."""
    return unicodedata.normalize("NFKC", password)


def hashear(password: str) -> str:
    return _hasher.hash(normalizar(password))


def verificar(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, normalizar(password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def necesita_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@lru_cache(maxsize=1)
def hash_senuelo() -> str:
    """Hash de una contraseña al azar, para verificar contra él cuando el
    usuario no existe: el login tarda lo mismo exista o no, y el tiempo de
    respuesta no delata qué usuarios hay."""
    return _hasher.hash(secrets.token_urlsafe(32))


def problemas_politica(password: str, usuario: str) -> list[str]:
    """Por qué una contraseña nueva no sirve (vacío = sirve)."""
    texto = normalizar(password)
    plano = texto.casefold()
    problemas: list[str] = []
    if len(texto) < config.PASSWORD_MIN_LENGTH:
        problemas.append(f"Tiene que tener al menos {config.PASSWORD_MIN_LENGTH} caracteres.")
    if len(texto) > PASSWORD_MAX_LENGTH:
        problemas.append(f"No puede superar los {PASSWORD_MAX_LENGTH} caracteres.")
    if usuario and usuario.casefold() in plano:
        problemas.append("No puede contener el nombre de usuario.")
    if plano in _COMUNES or len(set(plano)) <= 3:
        problemas.append("Es demasiado común o repetitiva.")
    if any(unicodedata.category(caracter) == "Cc" for caracter in texto):
        problemas.append("No puede tener caracteres de control.")
    return problemas
