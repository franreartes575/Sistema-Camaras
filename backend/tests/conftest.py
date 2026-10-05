"""Fixtures compartidas por toda la suite."""

import base64
import dataclasses
import datetime as dt

import pytest

from app import config
from app.auth.dependencias import sesion_actual
from app.auth.servicio import SesionActiva
from app.catalogo_route import catalogo_rate_limit
from app.export_route import export_rate_limit
from app.main import app, _optimize_rate_limit, _process_rate_limit, _upload_rate_limit
from app.registro_route import registro_rate_limit

_LIMITADORES = (
    _upload_rate_limit,
    _process_rate_limit,
    _optimize_rate_limit,
    export_rate_limit,
    registro_rate_limit,
    catalogo_rate_limit,
)


# Clave maestra fija para los tests (32 bytes). Nunca se usa fuera de acá.
CLAVE_DE_PRUEBA = base64.b64encode(bytes(range(32))).decode()

SESION_DE_PRUEBA = SesionActiva(
    sesion_id="sesion-de-prueba",
    usuario_id=1,
    usuario="pruebas",
    nombre="Pruebas",
    rol="admin",
    csrf="csrf-de-prueba",
    debe_cambiar_password=False,
    expira_inactividad=dt.datetime(2099, 1, 1, tzinfo=dt.timezone.utc),
    expira_absoluta=dt.datetime(2099, 1, 1, tzinfo=dt.timezone.utc),
)


@pytest.fixture(autouse=True)
def _base_temporal(tmp_path, monkeypatch):
    """Cada test escribe en sus propias bases SQLite, nunca en las de data/."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "registro.db"))
    monkeypatch.setattr(config, "AUTH_DB_PATH", str(tmp_path / "seguridad.db"))
    monkeypatch.setattr(config, "AUTH_MASTER_KEY", CLAVE_DE_PRUEBA)
    # Sin límites de municipios salvo que el test los escriba (ver
    # test_localidades.py): el resultado no depende del archivo del repo.
    monkeypatch.setattr(config, "MUNICIPIOS_PATH", str(tmp_path / "municipios.geojson"))


SESION_DE_OPERADOR = dataclasses.replace(
    SESION_DE_PRUEBA, sesion_id="sesion-de-operador", usuario_id=2, usuario="operador",
    nombre="Operador", rol="operador",
)


@pytest.fixture
def como_operador():
    """Cambia la sesión simulada por la de un operador (sin permisos de admin)."""
    app.dependency_overrides[sesion_actual] = lambda: SESION_DE_OPERADOR
    yield


@pytest.fixture(autouse=True)
def _sesion_simulada(request):
    """Los tests de la aplicación corren con una sesión de administrador ya
    abierta: prueban planificación y registro, no el login. Los de
    autenticación (marcados `auth_real`) pasan por el flujo completo."""
    if request.node.get_closest_marker("auth_real"):
        yield
        return
    app.dependency_overrides[sesion_actual] = lambda: SESION_DE_PRUEBA
    yield
    app.dependency_overrides.pop(sesion_actual, None)


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
