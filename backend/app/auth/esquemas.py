"""Esquemas de entrada y salida de /auth.

Validación estricta antes de cualquier procesamiento (el equivalente de Zod
en este backend es pydantic): campos de más se rechazan (`extra="forbid"`),
sin conversiones de tipo (`strict=True`: un número no pasa por texto), largos
acotados y formatos con patrón. Un pedido inválido no llega al servicio.
"""

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LoginIn(_Entrada):
    # Sin patrón a propósito: un usuario con formato raro se trata igual que
    # uno inexistente ("Credenciales inválidas."), sin pistas de qué falló.
    usuario: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class CambioPasswordIn(_Entrada):
    password_actual: str = Field(min_length=1, max_length=256)
    password_nueva: str = Field(min_length=1, max_length=256)


class UsuarioOut(BaseModel):
    usuario: str
    nombre: str
    rol: str


class SesionOut(BaseModel):
    usuario: UsuarioOut
    csrf: str
    debe_cambiar_password: bool
    expira_inactividad_en: dt.datetime
    expira_absoluta_en: dt.datetime
    inactividad_minutos: int


class SesionListadaOut(BaseModel):
    id: str
    creada_en: dt.datetime
    ultima_actividad: dt.datetime
    ip_inicio: str
    ip_ultima: str
    user_agent: str
    actual: bool


class EventoAuditoriaOut(BaseModel):
    id: int
    ts: dt.datetime
    evento: str
    resultado: str
    usuario_intentado: str | None
    usuario_id: int | None
    ip: str
    ip_conexion: str
    x_forwarded_for: str | None
    user_agent: str | None
    motivo: str | None
    sesion_id: str | None
