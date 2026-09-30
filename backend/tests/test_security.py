"""Tests de autenticación por API key y del limitador de tasa en memoria."""

import asyncio
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app import config
from app.security import SlidingWindowLimiter, require_api_key


def _check_api_key(x_api_key: str | None) -> None:
    """Corre la dependencia async fuera de un event loop, como en los tests."""
    asyncio.run(require_api_key(x_api_key=x_api_key))


# --------------------------------------------------------------------------
# require_api_key
# --------------------------------------------------------------------------


def test_require_api_key_deshabilitado_sin_configurar(monkeypatch) -> None:
    """Sin API_KEY seteada, el chequeo no bloquea nada (desarrollo local)."""
    monkeypatch.setattr(config, "API_KEY", "")

    _check_api_key(None)
    _check_api_key("cualquiera")


def test_require_api_key_rechaza_clave_incorrecta(monkeypatch) -> None:
    """Con API_KEY seteada, una clave ausente o distinta se rechaza con 401."""
    monkeypatch.setattr(config, "API_KEY", "secreta")

    with pytest.raises(HTTPException) as exc_info:
        _check_api_key(None)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info:
        _check_api_key("otra")
    assert exc_info.value.status_code == 401


def test_require_api_key_acepta_clave_correcta(monkeypatch) -> None:
    """La clave correcta pasa sin levantar excepción."""
    monkeypatch.setattr(config, "API_KEY", "secreta")

    _check_api_key("secreta")


# --------------------------------------------------------------------------
# SlidingWindowLimiter
# --------------------------------------------------------------------------


def test_limiter_permite_hasta_el_tope() -> None:
    """Las primeras `max_requests` solicitudes de una IP pasan sin error."""
    limiter = SlidingWindowLimiter(max_requests=3, window_s=60)

    for _ in range(3):
        limiter.check("1.2.3.4")


def test_limiter_bloquea_al_superar_el_tope() -> None:
    """La solicitud que excede el tope levanta 429."""
    limiter = SlidingWindowLimiter(max_requests=2, window_s=60)

    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")

    with pytest.raises(HTTPException) as exc_info:
        limiter.check("1.2.3.4")
    assert exc_info.value.status_code == 429


def test_limiter_no_mezcla_ips_distintas() -> None:
    """El tope es por clave: otra IP no se ve afectada por la primera."""
    limiter = SlidingWindowLimiter(max_requests=1, window_s=60)

    limiter.check("1.2.3.4")
    limiter.check("5.6.7.8")  # no debe levantar excepción


def test_limiter_libera_cupo_cuando_la_ventana_avanza(monkeypatch) -> None:
    """Pasada la ventana, los hits viejos se descartan y hay cupo de nuevo."""
    limiter = SlidingWindowLimiter(max_requests=1, window_s=60)
    reloj = Mock(side_effect=[0.0, 120.0])
    monkeypatch.setattr("app.security.time.monotonic", reloj)

    limiter.check("1.2.3.4")  # t=0, agota el único cupo de la ventana
    limiter.check("1.2.3.4")  # t=120, ya pasó la ventana: no debe levantar


def test_limiter_bloquea_dentro_de_la_misma_ventana(monkeypatch) -> None:
    """Dentro de la ventana, el segundo hit sigue contando y bloquea."""
    limiter = SlidingWindowLimiter(max_requests=1, window_s=60)
    reloj = Mock(side_effect=[0.0, 30.0])
    monkeypatch.setattr("app.security.time.monotonic", reloj)

    limiter.check("1.2.3.4")  # t=0

    with pytest.raises(HTTPException) as exc_info:
        limiter.check("1.2.3.4")  # t=30, todavía dentro de los 60s
    assert exc_info.value.status_code == 429
