"""Integración con FastAPI: cookies, dependencias de sesión, cabeceras y errores.

Las cookies se programan en `request.state` y las aplica el middleware al
final, sobre la respuesta que sea: así una rotación de token llega también en
las descargas de Excel, que se devuelven como `Response` directa.
"""

import sqlite3
from typing import Annotated

import anyio
from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from .. import config
from ..red import is_https
from . import auditoria, db, servicio
from .contexto import ContextoPedido
from .servicio import ErrorAuth, SesionActiva

# __Host-: el navegador sólo la acepta con Secure, Path=/ y sin Domain, así
# que ningún subdominio puede pisarla ni leerla.
COOKIE_SESION = "__Host-sid"
COOKIE_PREAUTH = "__Host-preauth"
HEADER_CSRF = "x-csrf-token"
# Los pedidos de /auth son JSON chicos; un cuerpo grande sólo puede ser abuso.
MAX_AUTH_BODY = 8 * 1024


def programar_cookie(request: Request, nombre: str, valor: str, max_age: int | None = None) -> None:
    pendientes = getattr(request.state, "cookies_auth", [])
    pendientes.append((nombre, valor, max_age))
    request.state.cookies_auth = pendientes


def programar_borrado(request: Request, nombre: str) -> None:
    programar_cookie(request, nombre, "", 0)


def _aplicar_cookies(request: Request, response: Response) -> None:
    for nombre, valor, max_age in getattr(request.state, "cookies_auth", []):
        # Sin max_age: cookie de sesión del navegador (muere al cerrarlo). El
        # vencimiento real lo decide el servidor igual.
        response.set_cookie(
            nombre, valor, max_age=max_age, path="/", secure=True, httponly=True, samesite="strict",
        )


def _cabeceras(request: Request, response: Response) -> None:
    cabeceras = response.headers
    # Ninguna respuesta de la API se cachea: llevan datos de la operación.
    cabeceras["Cache-Control"] = "no-store"
    cabeceras["Pragma"] = "no-cache"
    cabeceras["X-Content-Type-Options"] = "nosniff"
    cabeceras["X-Frame-Options"] = "DENY"
    cabeceras["Referrer-Policy"] = "no-referrer"
    cabeceras["Cross-Origin-Opener-Policy"] = "same-origin"
    cabeceras["Cross-Origin-Resource-Policy"] = "same-origin"
    if not (config.API_DOCS and request.url.path in ("/docs", "/docs/oauth2-redirect")):
        cabeceras["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if is_https(request):
        cabeceras["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"


class SeguridadMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith("/auth/") and request.method not in servicio.SAFE_METHODS:
            largo = request.headers.get("content-length")
            if largo is None and request.headers.get("transfer-encoding"):
                return JSONResponse({"detail": "Falta Content-Length."}, status_code=411)
            if largo is not None and (not largo.isdigit() or int(largo) > MAX_AUTH_BODY):
                return JSONResponse({"detail": "Pedido demasiado grande."}, status_code=413)
        response = await call_next(request)
        _aplicar_cookies(request, response)
        _cabeceras(request, response)
        return response


# --------------------------------------------------------------------------
# Dependencias
# --------------------------------------------------------------------------

AuthDb = Annotated[sqlite3.Connection, Depends(db.get_auth_db)]


def validar(request: Request, conn) -> SesionActiva:
    ctx = ContextoPedido.de_request(request)
    try:
        sesion = servicio.validar_sesion(
            conn, request.cookies.get(COOKIE_SESION), ctx,
            metodo_http=request.method, csrf=request.headers.get(HEADER_CSRF),
        )
    except servicio.SesionInvalida:
        programar_borrado(request, COOKIE_SESION)
        raise
    if sesion.nuevo_token:
        programar_cookie(request, COOKIE_SESION, sesion.nuevo_token)
    return sesion


def sesion_actual(request: Request, conn: AuthDb) -> SesionActiva:
    """Sesión válida, aunque tenga pendiente el cambio de contraseña."""
    return validar(request, conn)


def requiere_sesion(sesion: Annotated[SesionActiva, Depends(sesion_actual)]) -> SesionActiva:
    """Lo que exige cualquier endpoint de la aplicación."""
    if sesion.debe_cambiar_password:
        raise servicio.CambioPasswordRequerido()
    return sesion


def requiere_admin(sesion: Annotated[SesionActiva, Depends(requiere_sesion)]) -> SesionActiva:
    if sesion.rol != "admin":
        raise servicio.OperacionNoPermitida()
    return sesion


# --------------------------------------------------------------------------
# Instalación en la app
# --------------------------------------------------------------------------


async def _error_auth(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ErrorAuth)
    response = JSONResponse({"detail": exc.mensaje}, status_code=exc.status)
    _aplicar_cookies(request, response)
    return response


def _auditar_rechazo(ctx: ContextoPedido) -> None:
    conn = db.connect()
    try:
        auditoria.registrar(conn, "login_rechazado", "fallo", ctx, motivo="formato_invalido")
    finally:
        conn.close()


async def _validacion(request: Request, exc: Exception) -> Response:
    """En /auth, un pedido mal formado no devuelve el detalle de pydantic: ese
    detalle repite lo que se mandó, contraseña incluida."""
    assert isinstance(exc, RequestValidationError)
    if not request.url.path.startswith("/auth/"):
        return await request_validation_exception_handler(request, exc)
    if request.url.path == "/auth/login":
        # También es un intento de inicio de sesión: queda auditado y cuenta
        # para el límite por IP.
        await anyio.to_thread.run_sync(_auditar_rechazo, ContextoPedido.de_request(request))
    return JSONResponse({"detail": "Pedido inválido."}, status_code=422)


def instalar(app: FastAPI) -> None:
    app.add_middleware(SeguridadMiddleware)
    app.add_exception_handler(ErrorAuth, _error_auth)
    app.add_exception_handler(RequestValidationError, _validacion)
