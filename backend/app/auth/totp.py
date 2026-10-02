"""TOTP (RFC 6238) para apps autenticadoras: Google Authenticator, Aegis, etc.

Implementado acá —son veinte líneas sobre `hmac`— en vez de sumar una
dependencia: queda auditable y se prueba contra los vectores del RFC.

Parámetros fijos y compatibles con todas las apps: SHA-1, 6 dígitos, 30 s.
"""

import base64
import datetime as dt
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote, urlencode

import segno

DIGITOS = 6
PERIODO_S = 30
# Se acepta el intervalo anterior y el siguiente: tolera relojes corridos
# hasta ~30 s sin agrandar mucho la ventana de un código robado.
VENTANA = 1


def nuevo_secreto() -> str:
    """160 bits al azar (lo que recomienda el RFC 4226 para SHA-1), en base32."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _clave(secreto: str) -> bytes:
    relleno = "=" * (-len(secreto) % 8)
    return base64.b32decode(secreto.upper() + relleno)


def codigo(secreto: str, paso: int, digitos: int = DIGITOS, algoritmo=hashlib.sha1) -> str:
    """El código para un intervalo dado (RFC 4226, truncado dinámico)."""
    resumen = hmac.new(_clave(secreto), struct.pack(">Q", paso), algoritmo).digest()
    corrimiento = resumen[-1] & 0x0F
    valor = struct.unpack(">I", resumen[corrimiento : corrimiento + 4])[0] & 0x7FFFFFFF
    return str(valor % 10**digitos).zfill(digitos)


def paso(momento: dt.datetime) -> int:
    return int(momento.timestamp()) // PERIODO_S


def verificar(secreto: str, ingresado: str, momento: dt.datetime, ultimo_paso: int | None) -> int | None:
    """Devuelve el intervalo del código si es válido, o None.

    Un código ya usado (intervalo <= `ultimo_paso`) no vale de nuevo aunque
    siga dentro de la ventana: quien lo vea por encima del hombro no puede
    reutilizarlo.
    """
    actual = paso(momento)
    for delta in (0, -1, 1):
        candidato = actual + delta
        if ultimo_paso is not None and candidato <= ultimo_paso:
            continue
        if hmac.compare_digest(codigo(secreto, candidato), ingresado):
            return candidato
    return None


def uri_aprovisionamiento(secreto: str, usuario: str, emisor: str) -> str:
    """URI otpauth:// que leen las apps al escanear el QR."""
    etiqueta = quote(f"{emisor}:{usuario}")
    parametros = urlencode(
        {"secret": secreto, "issuer": emisor, "algorithm": "SHA1", "digits": DIGITOS, "period": PERIODO_S}
    )
    return f"otpauth://totp/{etiqueta}?{parametros}"


def qr_data_uri(uri: str) -> str:
    """El QR como imagen SVG en un data URI.

    Se muestra con <img>, nunca insertado como HTML: un SVG en <img> no
    ejecuta scripts.
    """
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2, dark="#0f172a", light="#ffffff")
