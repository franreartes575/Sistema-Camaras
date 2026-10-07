"""Tests del limitador de tasa en memoria."""

from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.security import SlidingWindowLimiter


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
