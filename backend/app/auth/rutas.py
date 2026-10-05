"""Endpoints de /auth: login, sesión, cierre y auditoría.

Son `def` (no `async def`): Argon2 y SQLite bloquean, y FastAPI corre las
funciones sincrónicas en un hilo sin frenar el event loop.
"""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from .. import config
from . import auditoria, servicio
from .contexto import ContextoPedido
from .dependencias import (
    COOKIE_SESION,
    AuthDb,
    programar_borrado,
    programar_cookie,
    requiere_admin,
    sesion_actual,
    validar,
)
from .esquemas import (
    CambioPasswordIn,
    EventoAuditoriaOut,
    LoginIn,
    SesionListadaOut,
    SesionOut,
    UsuarioOut,
)
from .servicio import SesionActiva

router = APIRouter(prefix="/auth", tags=["autenticación"])

Sesion = Annotated[SesionActiva, Depends(sesion_actual)]


def _salida(sesion: SesionActiva) -> SesionOut:
    return SesionOut(
        usuario=UsuarioOut(usuario=sesion.usuario, nombre=sesion.nombre, rol=sesion.rol),
        csrf=sesion.csrf,
        debe_cambiar_password=sesion.debe_cambiar_password,
        expira_inactividad_en=sesion.expira_inactividad,
        expira_absoluta_en=sesion.expira_absoluta,
        inactividad_minutos=config.SESSION_IDLE_MINUTES,
    )


def _emitir(request: Request, sesion: SesionActiva) -> SesionOut:
    """Contraseña correcta: recién ahora existe la cookie de sesión."""
    assert sesion.nuevo_token
    programar_cookie(request, COOKIE_SESION, sesion.nuevo_token)
    return _salida(sesion)


@router.post("/login", response_model=SesionOut)
def login(datos: LoginIn, request: Request, conn: AuthDb) -> SesionOut:
    """Usuario y contraseña. Nunca dice cuál de los dos falló."""
    ctx = ContextoPedido.de_request(request)
    if not servicio.origen_permitido(ctx.origen):
        auditoria.registrar(
            conn, "csrf_rechazado", "fallo", ctx, usuario_intentado=servicio.normalizar_usuario(datos.usuario),
            motivo="origen_login",
        )
        raise servicio.PedidoRechazado()
    return _emitir(request, servicio.iniciar_login(conn, datos.usuario, datos.password, ctx))


@router.get("/sesion", response_model=SesionOut)
def sesion_vigente(sesion: Sesion) -> SesionOut:
    """Quién soy, el token CSRF y cuándo vence. Llamarlo cuenta como actividad."""
    return _salida(sesion)


@router.post("/logout", status_code=204)
def logout(request: Request, conn: AuthDb) -> Response:
    try:
        sesion = validar(request, conn)
    except servicio.SesionInvalida:
        return Response(status_code=204)
    servicio.cerrar_sesion(conn, sesion, ContextoPedido.de_request(request))
    programar_borrado(request, COOKIE_SESION)
    return Response(status_code=204)


@router.get("/sesiones", response_model=list[SesionListadaOut])
def mis_sesiones(sesion: Sesion, conn: AuthDb) -> list[SesionListadaOut]:
    return [SesionListadaOut(**fila) for fila in servicio.listar_sesiones(conn, sesion)]


@router.delete("/sesiones/{sesion_id}", status_code=204)
def cerrar_una(
    sesion_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{10,64}$")],
    request: Request,
    sesion: Sesion,
    conn: AuthDb,
) -> Response:
    servicio.revocar_propia(conn, sesion, sesion_id, ContextoPedido.de_request(request))
    if sesion_id == sesion.sesion_id:
        programar_borrado(request, COOKIE_SESION)
    return Response(status_code=204)


@router.post("/sesiones/cerrar-otras")
def cerrar_otras(request: Request, sesion: Sesion, conn: AuthDb) -> dict[str, int]:
    return {"cerradas": servicio.revocar_propia(conn, sesion, None, ContextoPedido.de_request(request))}


@router.post("/password", status_code=204)
def cambiar_password(datos: CambioPasswordIn, request: Request, sesion: Sesion, conn: AuthDb) -> Response:
    """Cambia la contraseña: cierra las otras sesiones y rota el token de esta."""
    token = servicio.cambiar_password(
        conn, sesion, datos.password_actual, datos.password_nueva, ContextoPedido.de_request(request)
    )
    programar_cookie(request, COOKIE_SESION, token)
    return Response(status_code=204)


@router.get("/auditoria", response_model=list[EventoAuditoriaOut])
def ver_auditoria(
    _: Annotated[SesionActiva, Depends(requiere_admin)],
    conn: AuthDb,
    desde: dt.datetime | None = None,
    hasta: dt.datetime | None = None,
    usuario: Annotated[str | None, Query(max_length=64)] = None,
    ip: Annotated[str | None, Query(max_length=64)] = None,
    limite: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[EventoAuditoriaOut]:
    """Últimos eventos de acceso (sólo administradores)."""
    filas = auditoria.listar(
        conn,
        desde=desde.astimezone(dt.timezone.utc).isoformat(timespec="microseconds") if desde else None,
        hasta=hasta.astimezone(dt.timezone.utc).isoformat(timespec="microseconds") if hasta else None,
        usuario=servicio.normalizar_usuario(usuario) if usuario else None,
        ip=ip,
        limite=limite,
    )
    return [EventoAuditoriaOut(**fila) for fila in filas]
