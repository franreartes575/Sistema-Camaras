"""Quién hace un pedido y desde dónde: lo que queda en la auditoría."""

import getpass
import socket
from dataclasses import dataclass

from fastapi import Request

from ..red import client_address

MAX_USER_AGENT = 512


@dataclass(frozen=True)
class ContextoPedido:
    ip: str
    ip_conexion: str
    forwarded_for: str | None
    user_agent: str
    origen: str | None  # header Origin, para el chequeo anti-CSRF

    @classmethod
    def de_request(cls, request: Request) -> "ContextoPedido":
        direccion = client_address(request)
        return cls(
            ip=direccion.ip,
            ip_conexion=direccion.peer,
            forwarded_for=direccion.forwarded_for,
            user_agent=(request.headers.get("user-agent") or "")[:MAX_USER_AGENT],
            origen=request.headers.get("origin"),
        )

    @classmethod
    def consola(cls) -> "ContextoPedido":
        """Acciones administrativas desde la línea de comandos."""
        try:
            operador = getpass.getuser()
        except Exception:  # sin usuario del sistema (contenedores mínimos)
            operador = "desconocido"
        return cls(
            ip="cli",
            ip_conexion="cli",
            forwarded_for=None,
            user_agent=f"cli:{operador}@{socket.gethostname()}"[:MAX_USER_AGENT],
            origen=None,
        )
