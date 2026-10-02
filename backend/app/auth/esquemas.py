"""Esquemas de entrada y salida de /auth.

Validación estricta antes de cualquier procesamiento (el equivalente de Zod
en este backend es pydantic): campos de más se rechazan (`extra="forbid"`),
sin conversiones de tipo (`strict=True`: un número no pasa por texto), largos
acotados y formatos con patrón. Un pedido inválido no llega al servicio.
"""

import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LoginIn(_Entrada):
    # Sin patrón a propósito: un usuario con formato raro se trata igual que
    # uno inexistente ("Credenciales inválidas."), sin pistas de qué falló.
    usuario: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class CodigoTotpIn(_Entrada):
    codigo: str = Field(pattern=r"^\d{6}$")


class VerificarMfaIn(_Entrada):
    codigo: str | None = Field(None, pattern=r"^\d{6}$")
    codigo_recuperacion: str | None = Field(None, min_length=12, max_length=20)

    @field_validator("codigo_recuperacion")
    @classmethod
    def _formato_recuperacion(cls, valor: str | None) -> str | None:
        if valor is not None and not re.fullmatch(r"[A-Za-z0-9]{12}", re.sub(r"[\s-]", "", valor)):
            raise ValueError("formato inválido")
        return valor

    @model_validator(mode="after")
    def _uno_solo(self) -> "VerificarMfaIn":
        if (self.codigo is None) == (self.codigo_recuperacion is None):
            raise ValueError("Indicá el código de la app o uno de recuperación, no ambos.")
        return self


class CambioPasswordIn(_Entrada):
    password_actual: str = Field(min_length=1, max_length=256)
    password_nueva: str = Field(min_length=1, max_length=256)


class PasoLoginOut(BaseModel):
    paso: Literal["mfa", "enrolar_mfa"]
    csrf: str
    expira_en: dt.datetime


class EnrolamientoOut(BaseModel):
    secreto: str = Field(..., description="Para cargarlo a mano si no se puede escanear")
    uri: str
    qr: str = Field(..., description="data:image/svg+xml — mostrar con <img>, nunca como HTML")


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
    codigos_recuperacion: list[str] | None = Field(
        None, description="Sólo al enrolar el segundo factor: se muestran una vez"
    )
    codigos_restantes: int | None = Field(
        None, description="Si se entró con un código de recuperación, cuántos quedan"
    )


class SesionListadaOut(BaseModel):
    id: str
    creada_en: dt.datetime
    ultima_actividad: dt.datetime
    ip_inicio: str
    ip_ultima: str
    user_agent: str
    metodo_mfa: str
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
