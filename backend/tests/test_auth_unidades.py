"""Tests unitarios de las piezas criptográficas y de red del login."""

import base64
import datetime as dt
import hashlib
import os
import stat

import pytest

from app import config, red
from app.auth import cripto, totp

# --------------------------------------------------------------------------
# TOTP: vectores oficiales del RFC 6238 (apéndice B, SHA-1, 8 dígitos)
# --------------------------------------------------------------------------

SECRETO_RFC = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(
    ("segundos", "esperado"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_totp_vectores_rfc_6238(segundos, esperado) -> None:
    assert totp.codigo(SECRETO_RFC, segundos // 30, digitos=8, algoritmo=hashlib.sha1) == esperado


def test_totp_ventana_y_anti_reuso() -> None:
    secreto = totp.nuevo_secreto()
    ahora = dt.datetime(2026, 10, 2, 12, 0, 15, tzinfo=dt.timezone.utc)
    paso = totp.paso(ahora)

    assert totp.verificar(secreto, totp.codigo(secreto, paso), ahora, None) == paso
    assert totp.verificar(secreto, totp.codigo(secreto, paso - 1), ahora, None) == paso - 1  # reloj atrasado
    assert totp.verificar(secreto, totp.codigo(secreto, paso + 1), ahora, None) == paso + 1  # adelantado
    assert totp.verificar(secreto, totp.codigo(secreto, paso - 2), ahora, None) is None  # fuera de ventana
    assert totp.verificar(secreto, totp.codigo(secreto, paso), ahora, paso) is None  # ya usado
    assert totp.verificar(secreto, totp.codigo(secreto, paso + 1), ahora, paso) == paso + 1


def test_totp_secreto_de_160_bits() -> None:
    secreto = totp.nuevo_secreto()

    assert len(secreto) == 32  # 160 bits en base32, sin relleno
    assert len(base64.b32decode(secreto)) == 20


def test_totp_uri_para_las_apps() -> None:
    uri = totp.uri_aprovisionamiento("ABC", "j.perez", "Recorridos Camaras")

    assert uri.startswith("otpauth://totp/Recorridos%20Camaras%3Aj.perez?")
    assert "secret=ABC" in uri and "digits=6" in uri and "period=30" in uri


# --------------------------------------------------------------------------
# IP real detrás de proxies
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("par", "forwarded", "esperada"),
    [
        ("198.51.100.7", None, "198.51.100.7"),  # directo, sin header
        ("198.51.100.7", "10.0.0.1", "198.51.100.7"),  # directo: el header no se cree
        ("127.0.0.1", "203.0.113.9", "203.0.113.9"),  # detrás del rewrite de Next
        ("127.0.0.1", "1.1.1.1, 203.0.113.9", "203.0.113.9"),  # la de la izquierda es inventable
        ("127.0.0.1", "203.0.113.9, 127.0.0.1", "203.0.113.9"),  # saltea proxies de confianza
        ("127.0.0.1", "no-es-ip, 203.0.113.9", "203.0.113.9"),
        ("127.0.0.1", "203.0.113.9, basura", "127.0.0.1"),  # basura a la derecha corta la cadena
        ("127.0.0.1", "203.0.113.9:4711", "203.0.113.9"),  # con puerto
        ("127.0.0.1", "[2001:db8::1]:443", "2001:db8::1"),
        ("::ffff:127.0.0.1", "203.0.113.9", "203.0.113.9"),  # loopback mapeado a IPv6
        ("testclient", "203.0.113.9", "testclient"),  # par que no es IP: no se confía
    ],
)
def test_resolver_ip_del_cliente(par, forwarded, esperada) -> None:
    assert red.resolve_client(par, forwarded).ip == esperada


def test_proxy_de_confianza_configurable(monkeypatch) -> None:
    monkeypatch.setattr(config, "TRUSTED_PROXIES", ["10.0.0.0/8"])

    # El balanceador interno 10.1.2.3 delante de otro proxy 10.9.9.9.
    assert red.resolve_client("10.9.9.9", "203.0.113.9, 10.1.2.3").ip == "203.0.113.9"
    # Loopback ya no es de confianza con esta configuración.
    assert red.resolve_client("127.0.0.1", "203.0.113.9").ip == "127.0.0.1"


def test_header_gigante_se_recorta() -> None:
    direccion = red.resolve_client("127.0.0.1", "1.1.1.1," * 1000)

    assert len(direccion.forwarded_for) == red.MAX_FORWARDED_LENGTH


# --------------------------------------------------------------------------
# Cripto
# --------------------------------------------------------------------------


def test_cifrado_autenticado_con_contexto() -> None:
    blob = cripto.cifrar("JBSWY3DPEHPK3PXP", "usuario:1")

    assert cripto.descifrar(blob, "usuario:1") == "JBSWY3DPEHPK3PXP"
    assert cripto.cifrar("JBSWY3DPEHPK3PXP", "usuario:1") != blob  # nonce nuevo cada vez
    alterado = base64.b64encode(base64.b64decode(blob)[:-1] + b"\x00").decode()
    with pytest.raises(Exception):
        cripto.descifrar(alterado, "usuario:1")


def test_subclaves_independientes_por_proposito() -> None:
    assert cripto.subclave("totp") != cripto.subclave("auditoria") != cripto.subclave("recuperacion")
    assert cripto.subclave("totp") != cripto.clave_maestra()


@pytest.mark.parametrize("valor", ["no-es-base64!!", base64.b64encode(b"corta").decode()])
def test_clave_maestra_invalida(monkeypatch, valor) -> None:
    monkeypatch.setattr(config, "AUTH_MASTER_KEY", valor)

    with pytest.raises(cripto.ClaveMaestraFaltante):
        cripto.clave_maestra()


def test_archivo_de_clave_solo_para_el_dueno_y_sin_pisar(monkeypatch, tmp_path) -> None:
    ruta = tmp_path / "clave.key"
    monkeypatch.setattr(config, "AUTH_MASTER_KEY", "")
    monkeypatch.setattr(config, "AUTH_MASTER_KEY_FILE", str(ruta))

    cripto.guardar_clave_maestra(ruta)

    assert len(cripto.clave_maestra()) == 32
    if os.name == "posix":  # en Windows los permisos son ACL: ver la guía de despliegue
        assert stat.S_IMODE(ruta.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        cripto.guardar_clave_maestra(ruta)


def test_hash_de_token_y_tokens_de_256_bits() -> None:
    token = cripto.nuevo_token()

    assert len(base64.urlsafe_b64decode(token + "=")) == 32
    assert cripto.hash_token(token) == hashlib.sha256(token.encode()).hexdigest()
    assert cripto.nuevo_token() != token
