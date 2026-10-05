"""Tests unitarios de las piezas criptográficas y de red del login."""

import base64
import hashlib
import os
import stat

import pytest

from app import config, red
from app.auth import cripto

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


def test_subclaves_independientes_por_proposito() -> None:
    assert cripto.subclave("auditoria") != cripto.subclave("otro-proposito")
    assert cripto.subclave("auditoria") == cripto.subclave("auditoria")  # determinista
    assert cripto.subclave("auditoria") != cripto.clave_maestra()


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
