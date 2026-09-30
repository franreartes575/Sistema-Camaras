"""Fixtures compartidas por toda la suite."""

import pytest

from app.export_route import export_rate_limit
from app.main import app, _optimize_rate_limit, _process_rate_limit, _upload_rate_limit

_LIMITADORES = (
    _upload_rate_limit,
    _process_rate_limit,
    _optimize_rate_limit,
    export_rate_limit,
)


@pytest.fixture(autouse=True)
def _sin_limite_de_tasa():
    """Desactiva el rate limiting sólo en los tests HTTP.

    La suite hace bastantes más llamadas a /optimize/ por sesión de las que
    el límite de producción permite por minuto — eso prueba código de
    aplicación, no el rate limiter en sí (que ya tiene su propio test en
    test_security.py, contra SlidingWindowLimiter directamente).
    """
    for limitador in _LIMITADORES:
        app.dependency_overrides[limitador] = lambda: None
    yield
    for limitador in _LIMITADORES:
        app.dependency_overrides.pop(limitador, None)
