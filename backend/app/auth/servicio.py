"""Lógica de autenticación: login, bloqueo, segundo factor y sesiones.

Flujo:

    contraseña ──► desafío (pre-autenticación, cookie __Host-preauth, 5 min)
                    ├── sin factor: enrolar TOTP ──► confirmar código ──┐
                    └── con factor: código TOTP o de recuperación ──────┴► sesión

La cookie de sesión (__Host-sid) recién se emite al pasar el segundo factor.

Convenciones de este módulo:

- Todo error hacia el cliente es genérico ("Credenciales inválidas."); el
  motivo real (usuario inexistente, contraseña incorrecta, cuenta bloqueada…)
  queda sólo en la auditoría. Así no se puede averiguar qué usuarios existen.
- Las funciones internas *devuelven* el error en vez de lanzarlo: la
  transacción tiene que confirmarse igual para que el intento fallido quede
  auditado y contado. Las públicas lo lanzan después del COMMIT.
- Argon2 corre fuera de la transacción: tarda ~decenas de ms y no debe retener
  el lock de escritura de toda la base mientras tanto.
"""

import dataclasses
import datetime as dt
import hmac
import re
import secrets
import sqlite3
import unicodedata
from dataclasses import dataclass

from .. import config
from . import auditoria, contrasenas, cripto, reloj, totp
from .contexto import ContextoPedido
from .db import transaccion

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
RECOVERY_CODES = 10
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sin 0/O, 1/I/L
_USUARIO_VALIDO = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
# Revocaciones que hablan de un problema de seguridad: usar después una cookie
# así revocada se audita. Las de rutina (inactividad, logout) no.
_REVOCACIONES_DE_SEGURIDAD = frozenset(
    {"reuso_de_token", "otro_navegador", "administrador", "cambio_password", "bloqueo_permanente"}
)
MAX_BLOQUEO = dt.timedelta(hours=24)


# --------------------------------------------------------------------------
# Errores (el mensaje es lo único que ve el cliente)
# --------------------------------------------------------------------------


class ErrorAuth(Exception):
    status = 400
    mensaje = "Pedido inválido."

    def __init__(self, mensaje: str | None = None) -> None:
        super().__init__(mensaje or self.mensaje)
        if mensaje:
            self.mensaje = mensaje


class CredencialesInvalidas(ErrorAuth):
    status = 401
    mensaje = "Credenciales inválidas."


class DemasiadosIntentos(ErrorAuth):
    status = 429
    mensaje = "Demasiados intentos. Esperá unos minutos antes de volver a intentar."


class VerificacionVencida(ErrorAuth):
    status = 401
    mensaje = "La verificación venció o no es válida. Ingresá de nuevo."


class CodigoInvalido(ErrorAuth):
    status = 401
    mensaje = "Código inválido."


class SesionInvalida(ErrorAuth):
    status = 401
    mensaje = "La sesión no es válida o venció. Ingresá de nuevo."


class PedidoRechazado(ErrorAuth):
    """CSRF u origen inválido. Sin detalles: no ayudan a nadie legítimo."""

    status = 403
    mensaje = "Pedido rechazado."


class OperacionNoPermitida(ErrorAuth):
    status = 403
    mensaje = "No tenés permiso para esta acción."


class CambioPasswordRequerido(ErrorAuth):
    status = 403
    mensaje = "Tenés que cambiar la contraseña antes de continuar."


class PasswordRechazada(ErrorAuth):
    status = 422
    mensaje = "La contraseña nueva no cumple la política."


# --------------------------------------------------------------------------
# Resultados
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Desafio:
    token: str
    csrf: str
    proposito: str  # "verificar" | "enrolar"
    expira_en: dt.datetime


@dataclass(frozen=True)
class Enrolamiento:
    secreto: str
    uri: str
    qr: str


@dataclass(frozen=True)
class SesionActiva:
    sesion_id: str
    usuario_id: int
    usuario: str
    nombre: str
    rol: str
    csrf: str
    debe_cambiar_password: bool
    expira_inactividad: dt.datetime
    expira_absoluta: dt.datetime
    nuevo_token: str | None = None  # si se rotó, la cookie a emitir
    codigos_recuperacion: tuple[str, ...] | None = None  # recién enrolado
    codigos_restantes: int | None = None  # si entró con uno de recuperación


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------


def normalizar_usuario(texto: str) -> str:
    return unicodedata.normalize("NFKC", texto).strip().casefold()[:64]


def origen_permitido(origen: str | None) -> bool:
    """Sin Origin (clientes que no son navegador) se deja pasar: el token
    CSRF sigue siendo obligatorio. Con Origin, tiene que ser uno conocido."""
    return origen is None or origen in config.ALLOWED_ORIGINS


def _iso(momento: dt.datetime) -> str:
    return reloj.iso(momento)


def _usuario(conn: sqlite3.Connection, usuario_id: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()


def _bloqueada(fila: sqlite3.Row, momento: dt.datetime) -> str | None:
    """Motivo por el que la cuenta no puede entrar ahora, o None."""
    if not fila["activo"]:
        return "cuenta_deshabilitada"
    if fila["bloqueado_permanente"]:
        return "bloqueo_permanente"
    if fila["bloqueado_hasta"] and fila["bloqueado_hasta"] > _iso(momento):
        return "cuenta_bloqueada"
    return None


def _revocar(conn: sqlite3.Connection, sesion_id: str, motivo: str, momento: dt.datetime) -> None:
    conn.execute(
        "UPDATE sesiones SET revocada_en = ?, motivo_revocacion = ? WHERE id = ? AND revocada_en IS NULL",
        (_iso(momento), motivo, sesion_id),
    )


def _revocar_todas(
    conn: sqlite3.Connection, usuario_id: int, motivo: str, momento: dt.datetime, excepto: str | None = None
) -> int:
    return conn.execute(
        """
        UPDATE sesiones SET revocada_en = ?, motivo_revocacion = ?
        WHERE usuario_id = ? AND revocada_en IS NULL AND id IS NOT ?
        """,
        (_iso(momento), motivo, usuario_id, excepto),
    ).rowcount


def _registrar_fallo(
    conn: sqlite3.Connection,
    fila: sqlite3.Row,
    ctx: ContextoPedido,
    momento: dt.datetime,
    *,
    evento: str,
    motivo: str,
) -> bool:
    """Cuenta un fallo de credenciales y bloquea si corresponde.

    Devuelve True si la cuenta quedó bloqueada con este fallo.
    """
    auditoria.registrar(
        conn, evento, "fallo", ctx, usuario_intentado=fila["usuario"], usuario_id=fila["id"], motivo=motivo
    )
    intentos = fila["intentos_fallidos"] + 1
    if intentos < config.LOCKOUT_THRESHOLD:
        conn.execute("UPDATE usuarios SET intentos_fallidos = ? WHERE id = ?", (intentos, fila["id"]))
        return False

    bloqueos = fila["bloqueos_temporales"] + 1
    if bloqueos > config.LOCKOUT_MAX_TEMPORARY:
        conn.execute(
            """
            UPDATE usuarios SET bloqueado_permanente = 1, intentos_fallidos = 0,
                                bloqueos_temporales = ?
            WHERE id = ?
            """,
            (bloqueos, fila["id"]),
        )
        _revocar_todas(conn, fila["id"], "bloqueo_permanente", momento)
        auditoria.registrar(
            conn, "bloqueo_permanente", "info", ctx, usuario_intentado=fila["usuario"],
            usuario_id=fila["id"], motivo=f"{bloqueos - 1} bloqueos temporales previos",
        )
        return True

    duracion = min(dt.timedelta(minutes=config.LOCKOUT_BASE_MINUTES * 2 ** (bloqueos - 1)), MAX_BLOQUEO)
    conn.execute(
        """
        UPDATE usuarios SET bloqueado_hasta = ?, intentos_fallidos = 0, bloqueos_temporales = ?
        WHERE id = ?
        """,
        (_iso(momento + duracion), bloqueos, fila["id"]),
    )
    auditoria.registrar(
        conn, "bloqueo_temporal", "info", ctx, usuario_intentado=fila["usuario"], usuario_id=fila["id"],
        motivo=f"{int(duracion.total_seconds() // 60)} min (bloqueo {bloqueos})",
    )
    return True


def _limpiar_vencidos(conn: sqlite3.Connection, momento: dt.datetime) -> None:
    """Borra lo que ya no sirve. La auditoría, nunca."""
    hace_un_dia = _iso(momento - dt.timedelta(days=1))
    hace_un_mes = _iso(momento - dt.timedelta(days=30))
    conn.execute("DELETE FROM desafios_mfa WHERE expira_en < ?", (hace_un_dia,))
    conn.execute("DELETE FROM factores_mfa WHERE confirmado = 0 AND creado_en < ?", (hace_un_dia,))
    conn.execute(
        "DELETE FROM sesiones WHERE revocada_en < ? OR expira_absoluta < ?", (hace_un_mes, hace_un_mes)
    )


# --------------------------------------------------------------------------
# Usuarios (administración)
# --------------------------------------------------------------------------


def crear_usuario(
    conn: sqlite3.Connection,
    usuario: str,
    nombre: str,
    rol: str,
    password: str,
    ctx: ContextoPedido,
    *,
    debe_cambiar_password: bool = True,
) -> int:
    usuario = normalizar_usuario(usuario)
    if not _USUARIO_VALIDO.match(usuario):
        raise ErrorAuth(
            "El usuario debe tener de 3 a 64 caracteres: letras minúsculas, números, punto, guion o guion bajo."
        )
    if rol not in ("admin", "operador"):
        raise ErrorAuth("El rol debe ser 'admin' u 'operador'.")
    problemas = contrasenas.problemas_politica(password, usuario)
    if problemas:
        raise PasswordRechazada(" ".join(problemas))
    password_hash = contrasenas.hashear(password)
    momento = _iso(reloj.ahora())
    with transaccion(conn):
        try:
            cursor = conn.execute(
                """
                INSERT INTO usuarios (usuario, nombre, rol, password_hash, debe_cambiar_password,
                                      creado_en, password_cambiada_en)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (usuario, nombre.strip()[:120] or usuario, rol, password_hash,
                 int(debe_cambiar_password), momento, momento),
            )
        except sqlite3.IntegrityError as exc:
            raise ErrorAuth(f"Ya existe el usuario '{usuario}'.") from exc
        usuario_id = int(cursor.lastrowid or 0)
        auditoria.registrar(
            conn, "usuario_creado", "info", ctx, usuario_intentado=usuario, usuario_id=usuario_id,
            motivo=f"rol {rol}",
        )
    return usuario_id


def _usuario_por_nombre(conn: sqlite3.Connection, usuario: str) -> sqlite3.Row:
    fila = conn.execute(
        "SELECT * FROM usuarios WHERE usuario = ?", (normalizar_usuario(usuario),)
    ).fetchone()
    if fila is None:
        raise ErrorAuth(f"No existe el usuario '{usuario}'.")
    return fila


def administrar(conn: sqlite3.Connection, usuario: str, accion: str, ctx: ContextoPedido) -> None:
    """Acciones de un administrador sobre una cuenta (desde la consola)."""
    momento = reloj.ahora()
    with transaccion(conn):
        fila = _usuario_por_nombre(conn, usuario)
        uid = fila["id"]
        if accion == "desbloquear":
            conn.execute(
                """
                UPDATE usuarios SET bloqueado_permanente = 0, bloqueado_hasta = NULL,
                                    intentos_fallidos = 0, bloqueos_temporales = 0
                WHERE id = ?
                """,
                (uid,),
            )
        elif accion == "resetear_mfa":
            conn.execute("DELETE FROM factores_mfa WHERE usuario_id = ?", (uid,))
            conn.execute("DELETE FROM codigos_recuperacion WHERE usuario_id = ?", (uid,))
            _revocar_todas(conn, uid, "administrador", momento)
        elif accion == "deshabilitar":
            conn.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (uid,))
            _revocar_todas(conn, uid, "administrador", momento)
        elif accion == "habilitar":
            conn.execute("UPDATE usuarios SET activo = 1 WHERE id = ?", (uid,))
        elif accion == "revocar_sesiones":
            _revocar_todas(conn, uid, "administrador", momento)
        else:  # pragma: no cover - lo impide el CLI
            raise ErrorAuth(f"Acción desconocida: {accion}")
        auditoria.registrar(conn, f"admin_{accion}", "info", ctx, usuario_intentado=fila["usuario"], usuario_id=uid)


def resetear_password(conn: sqlite3.Connection, usuario: str, password: str, ctx: ContextoPedido) -> None:
    """Contraseña provisoria puesta por un administrador: obliga a cambiarla."""
    fila = _usuario_por_nombre(conn, usuario)
    problemas = contrasenas.problemas_politica(password, fila["usuario"])
    if problemas:
        raise PasswordRechazada(" ".join(problemas))
    password_hash = contrasenas.hashear(password)
    momento = reloj.ahora()
    with transaccion(conn):
        conn.execute(
            """
            UPDATE usuarios SET password_hash = ?, debe_cambiar_password = 1, password_cambiada_en = ?
            WHERE id = ?
            """,
            (password_hash, _iso(momento), fila["id"]),
        )
        _revocar_todas(conn, fila["id"], "administrador", momento)
        auditoria.registrar(
            conn, "admin_resetear_password", "info", ctx, usuario_intentado=fila["usuario"], usuario_id=fila["id"]
        )


def listar_usuarios(conn: sqlite3.Connection) -> list[dict]:
    filas = conn.execute(
        """
        SELECT u.usuario, u.nombre, u.rol, u.activo, u.bloqueado_permanente, u.bloqueado_hasta,
               u.ultimo_acceso_en, EXISTS (
                   SELECT 1 FROM factores_mfa f WHERE f.usuario_id = u.id AND f.confirmado = 1
               ) AS tiene_mfa
        FROM usuarios u ORDER BY u.usuario
        """
    ).fetchall()
    return [dict(fila) for fila in filas]


# --------------------------------------------------------------------------
# Paso 1: contraseña
# --------------------------------------------------------------------------


def _crear_desafio(
    conn: sqlite3.Connection, fila: sqlite3.Row, ctx: ContextoPedido, momento: dt.datetime
) -> Desafio:
    tiene_factor = conn.execute(
        "SELECT 1 FROM factores_mfa WHERE usuario_id = ? AND confirmado = 1", (fila["id"],)
    ).fetchone()
    proposito = "verificar" if tiene_factor else "enrolar"
    # Un solo desafío vivo por usuario: el nuevo invalida los anteriores.
    conn.execute(
        "UPDATE desafios_mfa SET consumido_en = ? WHERE usuario_id = ? AND consumido_en IS NULL",
        (_iso(momento), fila["id"]),
    )
    token, csrf = cripto.nuevo_token(), cripto.nuevo_token(24)
    expira = momento + dt.timedelta(minutes=config.PREAUTH_TTL_MINUTES)
    conn.execute(
        """
        INSERT INTO desafios_mfa (id, token_hash, usuario_id, proposito, csrf, creado_en, expira_en, ip, user_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cripto.nuevo_token(12), cripto.hash_token(token), fila["id"], proposito, csrf,
         _iso(momento), _iso(expira), ctx.ip, ctx.user_agent),
    )
    return Desafio(token, csrf, proposito, expira)


def iniciar_login(conn: sqlite3.Connection, usuario_ingresado: str, password: str, ctx: ContextoPedido) -> Desafio:
    """Verifica la contraseña. Si es correcta, abre el desafío del segundo factor."""
    usuario = normalizar_usuario(usuario_ingresado)
    momento = reloj.ahora()
    ventana = momento - dt.timedelta(minutes=config.LOGIN_WINDOW_MINUTES)

    # Límite por IP y por usuario (exista o no) ANTES de gastar Argon2: una
    # IP que ya falló demasiado no puede usar el login para quemar CPU.
    fallos_ip = auditoria.contar_fallos(conn, ventana, ip=ctx.ip, eventos=auditoria.FALLOS_POR_IP)
    if fallos_ip >= config.LOGIN_MAX_FAILURES_PER_IP:
        auditoria.registrar(conn, "login_limitado", "fallo", ctx, usuario_intentado=usuario, motivo="limite_por_ip")
        raise DemasiadosIntentos()
    if auditoria.contar_fallos(conn, ventana, usuario=usuario) >= config.LOGIN_MAX_FAILURES_PER_USER:
        auditoria.registrar(
            conn, "login_limitado", "fallo", ctx, usuario_intentado=usuario, motivo="limite_por_usuario"
        )
        raise DemasiadosIntentos()

    fila = conn.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    # Se verifica SIEMPRE, también contra un hash señuelo si el usuario no
    # existe: el tiempo de respuesta no delata qué cuentas hay.
    correcta = contrasenas.verificar(fila["password_hash"] if fila else contrasenas.hash_senuelo(), password)
    rehash = contrasenas.hashear(password) if fila and correcta and contrasenas.necesita_rehash(fila["password_hash"]) else None

    def _paso() -> Desafio | ErrorAuth:
        actual = conn.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
        if actual is None:
            auditoria.registrar(conn, "login_fallido", "fallo", ctx, usuario_intentado=usuario, motivo="usuario_inexistente")
            return CredencialesInvalidas()
        motivo = _bloqueada(actual, momento)
        if motivo:
            auditoria.registrar(
                conn, "login_fallido", "fallo", ctx, usuario_intentado=usuario, usuario_id=actual["id"], motivo=motivo
            )
            return CredencialesInvalidas()
        if not correcta:
            _registrar_fallo(conn, actual, ctx, momento, evento="login_fallido", motivo="password_incorrecta")
            return CredencialesInvalidas()
        if rehash:
            conn.execute("UPDATE usuarios SET password_hash = ? WHERE id = ?", (rehash, actual["id"]))
        auditoria.registrar(conn, "password_ok", "exito", ctx, usuario_intentado=usuario, usuario_id=actual["id"])
        _limpiar_vencidos(conn, momento)
        return _crear_desafio(conn, actual, ctx, momento)

    with transaccion(conn):
        resultado = _paso()
    if isinstance(resultado, ErrorAuth):
        raise resultado
    return resultado


# --------------------------------------------------------------------------
# Paso 2: segundo factor
# --------------------------------------------------------------------------


def _desafio_vigente(
    conn: sqlite3.Connection, token: str | None, csrf: str | None, ctx: ContextoPedido, momento: dt.datetime
) -> sqlite3.Row | ErrorAuth:
    if not token:
        return VerificacionVencida()
    fila = conn.execute("SELECT * FROM desafios_mfa WHERE token_hash = ?", (cripto.hash_token(token),)).fetchone()
    if fila is None or fila["consumido_en"] or fila["expira_en"] <= _iso(momento):
        return VerificacionVencida()
    if not origen_permitido(ctx.origen) or not hmac.compare_digest(fila["csrf"], csrf or ""):
        auditoria.registrar(conn, "csrf_rechazado", "fallo", ctx, usuario_id=fila["usuario_id"], motivo="desafio_mfa")
        return PedidoRechazado()
    # Atado al navegador que lo empezó: una cookie de pre-autenticación
    # copiada a otro equipo no sirve.
    if fila["user_agent"] != ctx.user_agent:
        conn.execute("UPDATE desafios_mfa SET consumido_en = ? WHERE id = ?", (_iso(momento), fila["id"]))
        auditoria.registrar(conn, "desafio_otro_navegador", "fallo", ctx, usuario_id=fila["usuario_id"])
        return VerificacionVencida()
    return fila


def _consumir(conn: sqlite3.Connection, desafio: sqlite3.Row, momento: dt.datetime) -> None:
    conn.execute("UPDATE desafios_mfa SET consumido_en = ? WHERE id = ?", (_iso(momento), desafio["id"]))


def _fallo_de_codigo(
    conn: sqlite3.Connection,
    desafio: sqlite3.Row,
    usuario: sqlite3.Row,
    ctx: ContextoPedido,
    momento: dt.datetime,
    motivo: str,
) -> ErrorAuth:
    """Un código incorrecto cuenta para el desafío y para el bloqueo de la cuenta:
    quien llegó hasta acá ya tiene la contraseña."""
    intentos = desafio["intentos"] + 1
    conn.execute("UPDATE desafios_mfa SET intentos = ? WHERE id = ?", (intentos, desafio["id"]))
    bloqueada = _registrar_fallo(conn, usuario, ctx, momento, evento="mfa_fallido", motivo=motivo)
    if bloqueada or intentos >= config.MFA_MAX_ATTEMPTS:
        _consumir(conn, desafio, momento)
        auditoria.registrar(conn, "mfa_desafio_agotado", "fallo", ctx, usuario_intentado=usuario["usuario"], usuario_id=usuario["id"])
        return VerificacionVencida()
    return CodigoInvalido()


def _usuario_del_desafio(
    conn: sqlite3.Connection, desafio: sqlite3.Row, ctx: ContextoPedido, momento: dt.datetime
) -> sqlite3.Row | ErrorAuth:
    usuario = _usuario(conn, desafio["usuario_id"])
    motivo = _bloqueada(usuario, momento)
    if motivo or desafio["intentos"] >= config.MFA_MAX_ATTEMPTS:
        _consumir(conn, desafio, momento)
        auditoria.registrar(
            conn, "mfa_fallido", "fallo", ctx, usuario_intentado=usuario["usuario"], usuario_id=usuario["id"],
            motivo=motivo or "desafio_agotado",
        )
        return VerificacionVencida()
    return usuario


def _secreto(factor: sqlite3.Row) -> str:
    return cripto.descifrar(factor["secreto_cifrado"], f"usuario:{factor['usuario_id']}")


def iniciar_enrolamiento(
    conn: sqlite3.Connection, token: str | None, csrf: str | None, ctx: ContextoPedido
) -> Enrolamiento:
    """Genera (o vuelve a mostrar) el secreto TOTP para escanear."""
    momento = reloj.ahora()

    def _paso() -> Enrolamiento | ErrorAuth:
        desafio = _desafio_vigente(conn, token, csrf, ctx, momento)
        if isinstance(desafio, ErrorAuth):
            return desafio
        if desafio["proposito"] != "enrolar":
            return OperacionNoPermitida()
        usuario = _usuario_del_desafio(conn, desafio, ctx, momento)
        if isinstance(usuario, ErrorAuth):
            return usuario
        if desafio["factor_pendiente_id"]:
            factor = conn.execute(
                "SELECT * FROM factores_mfa WHERE id = ?", (desafio["factor_pendiente_id"],)
            ).fetchone()
            secreto = _secreto(factor)
        else:
            secreto = totp.nuevo_secreto()
            cursor = conn.execute(
                "INSERT INTO factores_mfa (usuario_id, tipo, secreto_cifrado, creado_en) VALUES (?, 'totp', ?, ?)",
                (usuario["id"], cripto.cifrar(secreto, f"usuario:{usuario['id']}"), _iso(momento)),
            )
            conn.execute(
                "UPDATE desafios_mfa SET factor_pendiente_id = ? WHERE id = ?", (cursor.lastrowid, desafio["id"])
            )
        uri = totp.uri_aprovisionamiento(secreto, usuario["usuario"], config.TOTP_ISSUER)
        return Enrolamiento(secreto, uri, totp.qr_data_uri(uri))

    with transaccion(conn):
        resultado = _paso()
    if isinstance(resultado, ErrorAuth):
        raise resultado
    return resultado


def _codigos_de_recuperacion() -> list[str]:
    def uno() -> str:
        letras = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(12))
        return f"{letras[:4]}-{letras[4:8]}-{letras[8:]}"

    return [uno() for _ in range(RECOVERY_CODES)]


def normalizar_codigo_recuperacion(texto: str) -> str:
    plano = re.sub(r"[\s-]", "", texto).upper()
    return f"{plano[:4]}-{plano[4:8]}-{plano[8:]}"


def _hmac_recuperacion(usuario_id: int, codigo: str) -> str:
    return cripto.firmar("recuperacion", f"{usuario_id}:{normalizar_codigo_recuperacion(codigo)}")


def confirmar_enrolamiento(
    conn: sqlite3.Connection, token: str | None, csrf: str | None, codigo: str, ctx: ContextoPedido
) -> SesionActiva:
    """El primer código de la app confirma el factor y abre la sesión."""
    momento = reloj.ahora()

    def _paso() -> SesionActiva | ErrorAuth:
        desafio = _desafio_vigente(conn, token, csrf, ctx, momento)
        if isinstance(desafio, ErrorAuth):
            return desafio
        if desafio["proposito"] != "enrolar" or not desafio["factor_pendiente_id"]:
            return OperacionNoPermitida()
        usuario = _usuario_del_desafio(conn, desafio, ctx, momento)
        if isinstance(usuario, ErrorAuth):
            return usuario
        factor = conn.execute("SELECT * FROM factores_mfa WHERE id = ?", (desafio["factor_pendiente_id"],)).fetchone()
        paso = totp.verificar(_secreto(factor), codigo, momento, None)
        if paso is None:
            return _fallo_de_codigo(conn, desafio, usuario, ctx, momento, "codigo_de_enrolamiento_incorrecto")

        conn.execute(
            "UPDATE factores_mfa SET confirmado = 1, confirmado_en = ?, ultimo_paso = ? WHERE id = ?",
            (_iso(momento), paso, factor["id"]),
        )
        conn.execute(
            "DELETE FROM factores_mfa WHERE usuario_id = ? AND confirmado = 0", (usuario["id"],)
        )
        codigos = _codigos_de_recuperacion()
        conn.execute("DELETE FROM codigos_recuperacion WHERE usuario_id = ?", (usuario["id"],))
        conn.executemany(
            "INSERT INTO codigos_recuperacion (usuario_id, codigo_hmac) VALUES (?, ?)",
            [(usuario["id"], _hmac_recuperacion(usuario["id"], codigo_nuevo)) for codigo_nuevo in codigos],
        )
        auditoria.registrar(conn, "mfa_enrolado", "exito", ctx, usuario_intentado=usuario["usuario"], usuario_id=usuario["id"], motivo="totp")
        _consumir(conn, desafio, momento)
        sesion = _abrir_sesion(conn, usuario, ctx, momento, "totp")
        return dataclasses.replace(sesion, codigos_recuperacion=tuple(codigos))

    with transaccion(conn):
        resultado = _paso()
    if isinstance(resultado, ErrorAuth):
        raise resultado
    return resultado


def verificar_mfa(
    conn: sqlite3.Connection,
    token: str | None,
    csrf: str | None,
    ctx: ContextoPedido,
    *,
    codigo: str | None = None,
    codigo_recuperacion: str | None = None,
) -> SesionActiva:
    """Segundo factor: código de la app o, si se perdió, uno de recuperación."""
    momento = reloj.ahora()

    def _paso() -> SesionActiva | ErrorAuth:
        desafio = _desafio_vigente(conn, token, csrf, ctx, momento)
        if isinstance(desafio, ErrorAuth):
            return desafio
        if desafio["proposito"] != "verificar":
            return OperacionNoPermitida()
        usuario = _usuario_del_desafio(conn, desafio, ctx, momento)
        if isinstance(usuario, ErrorAuth):
            return usuario

        metodo: str | None = None
        restantes: int | None = None
        if codigo is not None:
            factor = conn.execute(
                "SELECT * FROM factores_mfa WHERE usuario_id = ? AND tipo = 'totp' AND confirmado = 1",
                (usuario["id"],),
            ).fetchone()
            paso = totp.verificar(_secreto(factor), codigo, momento, factor["ultimo_paso"]) if factor else None
            if paso is not None:
                conn.execute("UPDATE factores_mfa SET ultimo_paso = ? WHERE id = ?", (paso, factor["id"]))
                metodo = "totp"
        elif codigo_recuperacion is not None:
            usado = conn.execute(
                """
                UPDATE codigos_recuperacion SET usado_en = ?
                WHERE usuario_id = ? AND codigo_hmac = ? AND usado_en IS NULL
                """,
                (_iso(momento), usuario["id"], _hmac_recuperacion(usuario["id"], codigo_recuperacion)),
            ).rowcount
            if usado:
                metodo = "recuperacion"
                restantes = conn.execute(
                    "SELECT COUNT(*) FROM codigos_recuperacion WHERE usuario_id = ? AND usado_en IS NULL",
                    (usuario["id"],),
                ).fetchone()[0]

        if metodo is None:
            return _fallo_de_codigo(conn, desafio, usuario, ctx, momento, "codigo_incorrecto")
        _consumir(conn, desafio, momento)
        sesion = _abrir_sesion(conn, usuario, ctx, momento, metodo)
        return dataclasses.replace(sesion, codigos_restantes=restantes)

    with transaccion(conn):
        resultado = _paso()
    if isinstance(resultado, ErrorAuth):
        raise resultado
    return resultado


# --------------------------------------------------------------------------
# Sesiones
# --------------------------------------------------------------------------


def _expiraciones(fila: sqlite3.Row) -> tuple[dt.datetime, dt.datetime]:
    absoluta = reloj.desde_iso(fila["expira_absoluta"])
    inactividad = reloj.desde_iso(fila["ultima_actividad"]) + dt.timedelta(minutes=config.SESSION_IDLE_MINUTES)
    return min(inactividad, absoluta), absoluta


def _activa(fila: sqlite3.Row, usuario: sqlite3.Row, nuevo_token: str | None = None) -> SesionActiva:
    inactividad, absoluta = _expiraciones(fila)
    return SesionActiva(
        sesion_id=fila["id"],
        usuario_id=usuario["id"],
        usuario=usuario["usuario"],
        nombre=usuario["nombre"],
        rol=usuario["rol"],
        csrf=fila["csrf"],
        debe_cambiar_password=bool(usuario["debe_cambiar_password"]),
        expira_inactividad=inactividad,
        expira_absoluta=absoluta,
        nuevo_token=nuevo_token,
    )


def _abrir_sesion(
    conn: sqlite3.Connection, usuario: sqlite3.Row, ctx: ContextoPedido, momento: dt.datetime, metodo: str
) -> SesionActiva:
    # Tope de sesiones simultáneas: se cierran las menos usadas.
    activas = conn.execute(
        """
        SELECT id FROM sesiones
        WHERE usuario_id = ? AND revocada_en IS NULL AND expira_absoluta > ?
        ORDER BY ultima_actividad
        """,
        (usuario["id"], _iso(momento)),
    ).fetchall()
    for vieja in activas[: max(0, len(activas) - (config.MAX_SESSIONS_PER_USER - 1))]:
        _revocar(conn, vieja["id"], "limite_de_sesiones", momento)
        auditoria.registrar(
            conn, "sesion_revocada", "info", ctx, usuario_intentado=usuario["usuario"], usuario_id=usuario["id"],
            motivo="limite_de_sesiones", sesion_id=vieja["id"],
        )

    token = cripto.nuevo_token()
    sesion_id = cripto.nuevo_token(16)
    conn.execute(
        """
        INSERT INTO sesiones (id, usuario_id, token_hash, rotado_en, csrf, metodo_mfa, creada_en,
                              ultima_actividad, expira_absoluta, ip_inicio, ip_ultima, user_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (sesion_id, usuario["id"], cripto.hash_token(token), _iso(momento), cripto.nuevo_token(24), metodo,
         _iso(momento), _iso(momento), _iso(momento + dt.timedelta(hours=config.SESSION_ABSOLUTE_HOURS)),
         ctx.ip, ctx.ip, ctx.user_agent),
    )
    conn.execute(
        """
        UPDATE usuarios SET intentos_fallidos = 0, bloqueos_temporales = 0, bloqueado_hasta = NULL,
                            ultimo_acceso_en = ?
        WHERE id = ?
        """,
        (_iso(momento), usuario["id"]),
    )
    auditoria.registrar(
        conn, "mfa_ok", "exito", ctx, usuario_intentado=usuario["usuario"], usuario_id=usuario["id"], motivo=metodo
    )
    auditoria.registrar(
        conn, "sesion_iniciada", "exito", ctx, usuario_intentado=usuario["usuario"], usuario_id=usuario["id"],
        sesion_id=sesion_id,
    )
    fila = conn.execute("SELECT * FROM sesiones WHERE id = ?", (sesion_id,)).fetchone()
    return _activa(fila, _usuario(conn, usuario["id"]), nuevo_token=token)


def _buscar_sesion(
    conn: sqlite3.Connection, token: str, ctx: ContextoPedido, momento: dt.datetime
) -> tuple[sqlite3.Row, bool] | ErrorAuth:
    """La sesión de un token y si es el anterior a una rotación reciente."""
    huella = cripto.hash_token(token)
    fila = conn.execute("SELECT * FROM sesiones WHERE token_hash = ?", (huella,)).fetchone()
    if fila is not None:
        return fila, False
    fila = conn.execute("SELECT * FROM sesiones WHERE token_anterior_hash = ?", (huella,)).fetchone()
    if fila is None:
        return SesionInvalida()
    rotado = reloj.desde_iso(fila["rotado_en"])
    if fila["revocada_en"] is None and momento - rotado <= dt.timedelta(seconds=config.SESSION_ROTATION_GRACE_S):
        # Pedidos que salieron antes de recibir la cookie nueva.
        return fila, True
    if fila["revocada_en"] is None:
        # El token viejo apareció fuera de la gracia: alguien más lo tiene.
        # Se revoca la sesión entera, también para el dueño legítimo.
        _revocar(conn, fila["id"], "reuso_de_token", momento)
        auditoria.registrar(
            conn, "token_reusado", "fallo", ctx, usuario_id=fila["usuario_id"], sesion_id=fila["id"],
            motivo="token anterior a una rotación, fuera de la ventana de gracia",
        )
    return SesionInvalida()


def validar_sesion(
    conn: sqlite3.Connection,
    token: str | None,
    ctx: ContextoPedido,
    *,
    metodo_http: str,
    csrf: str | None,
) -> SesionActiva:
    """Valida la cookie en cada pedido: vencimientos, navegador, CSRF y rotación."""
    momento = reloj.ahora()

    def _paso() -> SesionActiva | ErrorAuth:
        if not token:
            return SesionInvalida()
        encontrada = _buscar_sesion(conn, token, ctx, momento)
        if isinstance(encontrada, ErrorAuth):
            return encontrada
        fila, es_anterior = encontrada

        usuario = _usuario(conn, fila["usuario_id"])
        quien = {"usuario_intentado": usuario["usuario"], "usuario_id": usuario["id"], "sesion_id": fila["id"]}

        def cerrar(motivo: str, evento: str, resultado: str = "info") -> ErrorAuth:
            _revocar(conn, fila["id"], motivo, momento)
            auditoria.registrar(conn, evento, resultado, ctx, motivo=motivo, **quien)
            return SesionInvalida()

        if fila["revocada_en"]:
            if fila["motivo_revocacion"] in _REVOCACIONES_DE_SEGURIDAD:
                auditoria.registrar(
                    conn, "sesion_revocada_usada", "fallo", ctx, motivo=fila["motivo_revocacion"], **quien
                )
            return SesionInvalida()
        inactividad, absoluta = _expiraciones(fila)
        if momento >= absoluta:
            return cerrar("vencida", "sesion_expirada")
        if momento >= inactividad:
            return cerrar("inactividad", "sesion_expirada")
        if _bloqueada(usuario, momento):
            return cerrar("cuenta_bloqueada", "sesion_revocada")
        if config.SESSION_BIND_USER_AGENT and fila["user_agent"] != ctx.user_agent:
            return cerrar("otro_navegador", "sesion_otro_navegador", "fallo")
        if metodo_http.upper() not in SAFE_METHODS:
            if not origen_permitido(ctx.origen) or not hmac.compare_digest(fila["csrf"], csrf or ""):
                auditoria.registrar(
                    conn, "csrf_rechazado", "fallo", ctx,
                    motivo="origen" if not origen_permitido(ctx.origen) else "token", **quien,
                )
                return PedidoRechazado()

        if ctx.ip != fila["ip_ultima"]:
            auditoria.registrar(
                conn, "sesion_ip_cambiada", "info", ctx, motivo=f"{fila['ip_ultima']} -> {ctx.ip}", **quien
            )
        conn.execute(
            "UPDATE sesiones SET ultima_actividad = ?, ip_ultima = ? WHERE id = ?",
            (_iso(momento), ctx.ip, fila["id"]),
        )

        nuevo: str | None = None
        rotado = reloj.desde_iso(fila["rotado_en"])
        if not es_anterior and momento - rotado >= dt.timedelta(minutes=config.SESSION_ROTATE_MINUTES):
            candidato = cripto.nuevo_token()
            # Condicionado al hash actual: si dos pedidos rotan a la vez, sólo
            # uno gana y el otro no emite una cookie que ya no sirve.
            rotadas = conn.execute(
                """
                UPDATE sesiones SET token_anterior_hash = token_hash, token_hash = ?, rotado_en = ?
                WHERE id = ? AND token_hash = ?
                """,
                (cripto.hash_token(candidato), _iso(momento), fila["id"], fila["token_hash"]),
            ).rowcount
            nuevo = candidato if rotadas else None
        actualizada = conn.execute("SELECT * FROM sesiones WHERE id = ?", (fila["id"],)).fetchone()
        return _activa(actualizada, usuario, nuevo)

    with transaccion(conn):
        resultado = _paso()
    if isinstance(resultado, ErrorAuth):
        raise resultado
    return resultado


def cerrar_sesion(conn: sqlite3.Connection, sesion: SesionActiva, ctx: ContextoPedido, motivo: str = "logout") -> None:
    momento = reloj.ahora()
    with transaccion(conn):
        _revocar(conn, sesion.sesion_id, motivo, momento)
        auditoria.registrar(
            conn, motivo, "exito", ctx, usuario_intentado=sesion.usuario, usuario_id=sesion.usuario_id,
            sesion_id=sesion.sesion_id,
        )


def listar_sesiones(conn: sqlite3.Connection, sesion: SesionActiva) -> list[dict]:
    filas = conn.execute(
        """
        SELECT id, creada_en, ultima_actividad, ip_inicio, ip_ultima, user_agent, metodo_mfa
        FROM sesiones WHERE usuario_id = ? AND revocada_en IS NULL AND expira_absoluta > ?
        ORDER BY ultima_actividad DESC
        """,
        (sesion.usuario_id, _iso(reloj.ahora())),
    ).fetchall()
    return [{**dict(fila), "actual": fila["id"] == sesion.sesion_id} for fila in filas]


def revocar_propia(conn: sqlite3.Connection, sesion: SesionActiva, sesion_id: str | None, ctx: ContextoPedido) -> int:
    """Cierra una sesión propia (por id) o todas las demás (id None)."""
    momento = reloj.ahora()
    with transaccion(conn):
        if sesion_id is None:
            cantidad = _revocar_todas(conn, sesion.usuario_id, "cerrada_por_usuario", momento, excepto=sesion.sesion_id)
        else:
            cantidad = conn.execute(
                """
                UPDATE sesiones SET revocada_en = ?, motivo_revocacion = 'cerrada_por_usuario'
                WHERE id = ? AND usuario_id = ? AND revocada_en IS NULL
                """,
                (_iso(momento), sesion_id, sesion.usuario_id),
            ).rowcount
        auditoria.registrar(
            conn, "sesion_revocada", "info", ctx, usuario_intentado=sesion.usuario, usuario_id=sesion.usuario_id,
            sesion_id=sesion_id or sesion.sesion_id,
            motivo="cerrada_por_usuario" if sesion_id else f"otras {cantidad} cerradas por el usuario",
        )
    return cantidad


def cambiar_password(
    conn: sqlite3.Connection, sesion: SesionActiva, actual: str, nueva: str, ctx: ContextoPedido
) -> str:
    """Cambia la contraseña, cierra las demás sesiones y devuelve un token nuevo."""
    fila = _usuario(conn, sesion.usuario_id)
    correcta = contrasenas.verificar(fila["password_hash"], actual)
    problemas = contrasenas.problemas_politica(nueva, fila["usuario"])
    if contrasenas.normalizar(nueva) == contrasenas.normalizar(actual):
        problemas.append("Tiene que ser distinta de la actual.")
    nuevo_hash = contrasenas.hashear(nueva) if correcta and not problemas else None
    momento = reloj.ahora()

    def _paso() -> str | ErrorAuth:
        usuario = _usuario(conn, sesion.usuario_id)
        if not correcta:
            # Cuenta para el bloqueo: una sesión robada no puede probar
            # contraseñas para quedarse con la cuenta.
            _registrar_fallo(conn, usuario, ctx, momento, evento="password_cambio_fallido", motivo="password_actual_incorrecta")
            return CredencialesInvalidas()
        if problemas:
            return PasswordRechazada(" ".join(problemas))
        conn.execute(
            """
            UPDATE usuarios SET password_hash = ?, debe_cambiar_password = 0, password_cambiada_en = ?
            WHERE id = ?
            """,
            (nuevo_hash, _iso(momento), usuario["id"]),
        )
        _revocar_todas(conn, usuario["id"], "cambio_password", momento, excepto=sesion.sesion_id)
        token = cripto.nuevo_token()
        conn.execute(
            "UPDATE sesiones SET token_anterior_hash = NULL, token_hash = ?, rotado_en = ? WHERE id = ?",
            (cripto.hash_token(token), _iso(momento), sesion.sesion_id),
        )
        auditoria.registrar(
            conn, "password_cambiada", "exito", ctx, usuario_intentado=usuario["usuario"], usuario_id=usuario["id"],
            sesion_id=sesion.sesion_id,
        )
        return token

    with transaccion(conn):
        resultado = _paso()
    if isinstance(resultado, ErrorAuth):
        raise resultado
    return resultado
