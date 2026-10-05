"""Auditoría de accesos: registro de sólo agregado con cadena de HMAC.

Cada fila guarda HMAC(clave "auditoria", hash_anterior | contenido). Borrar,
editar o reordenar filas rompe la cadena desde ese punto, y rehacerla exige la
clave maestra, que no está en la base. `verificar_cadena` recorre la tabla y
dice en qué fila se rompió.
"""

import csv
import datetime as dt
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import cripto, reloj
from .contexto import ContextoPedido
from .db import transaccion

GENESIS = "0" * 64
FALLOS_DE_CREDENCIALES = ("login_fallido",)
# Por IP cuentan también los pedidos de login con formato inválido: una IP que
# manda basura en cantidad no merece más intentos.
FALLOS_POR_IP = (*FALLOS_DE_CREDENCIALES, "login_rechazado")

# Caracteres de control y separadores de línea: un nombre de usuario con un
# salto de línea podría falsear renglones al leer la auditoría como texto.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
_COLUMNAS = (
    "ts", "evento", "resultado", "usuario_intentado", "usuario_id", "ip",
    "ip_conexion", "x_forwarded_for", "user_agent", "motivo", "sesion_id",
)


def limpiar(texto: str | None, maximo: int) -> str | None:
    if texto is None:
        return None
    return _CONTROL.sub("?", texto)[:maximo]


def _contenido(valores: dict) -> str:
    return json.dumps([valores[columna] for columna in _COLUMNAS], ensure_ascii=False, separators=(",", ":"))


def registrar(
    conn: sqlite3.Connection,
    evento: str,
    resultado: str,
    ctx: ContextoPedido,
    *,
    usuario_intentado: str | None = None,
    usuario_id: int | None = None,
    motivo: str | None = None,
    sesion_id: str | None = None,
) -> None:
    """Agrega un evento. Dentro de la transacción del llamador si la hay: el
    evento se confirma junto con el cambio que describe, o no se confirma."""
    if not conn.in_transaction:
        with transaccion(conn):
            registrar(
                conn, evento, resultado, ctx, usuario_intentado=usuario_intentado,
                usuario_id=usuario_id, motivo=motivo, sesion_id=sesion_id,
            )
        return

    valores = {
        "ts": reloj.iso(reloj.ahora()),
        "evento": evento,
        "resultado": resultado,
        "usuario_intentado": limpiar(usuario_intentado, 64),
        "usuario_id": usuario_id,
        "ip": limpiar(ctx.ip, 64),
        "ip_conexion": limpiar(ctx.ip_conexion, 64),
        "x_forwarded_for": limpiar(ctx.forwarded_for, 1024),
        "user_agent": limpiar(ctx.user_agent, 512),
        "motivo": limpiar(motivo, 200),
        "sesion_id": sesion_id,
    }
    fila = conn.execute("SELECT hash FROM auditoria_accesos ORDER BY id DESC LIMIT 1").fetchone()
    anterior = fila["hash"] if fila else GENESIS
    firma = cripto.firmar("auditoria", f"{anterior}|{_contenido(valores)}")
    conn.execute(
        f"""
        INSERT INTO auditoria_accesos ({", ".join(_COLUMNAS)}, hash_anterior, hash)
        VALUES ({", ".join("?" for _ in _COLUMNAS)}, ?, ?)
        """,
        [valores[columna] for columna in _COLUMNAS] + [anterior, firma],
    )


def contar_fallos(
    conn: sqlite3.Connection,
    desde: dt.datetime,
    *,
    ip: str | None = None,
    usuario: str | None = None,
    eventos: tuple[str, ...] = FALLOS_DE_CREDENCIALES,
) -> int:
    """Fallos de credenciales en la ventana, por IP o por usuario intentado."""
    campo, valor = ("ip", ip) if ip is not None else ("usuario_intentado", usuario)
    marcas = ", ".join("?" for _ in eventos)
    return conn.execute(
        f"""
        SELECT COUNT(*) FROM auditoria_accesos
        WHERE {campo} = ? AND ts >= ? AND evento IN ({marcas})
        """,
        [valor, reloj.iso(desde), *eventos],
    ).fetchone()[0]


@dataclass(frozen=True)
class Verificacion:
    integra: bool
    filas: int
    primera_alterada: int | None  # id de la primera fila que no cierra


def verificar_cadena(conn: sqlite3.Connection) -> Verificacion:
    anterior = GENESIS
    filas = 0
    for fila in conn.execute("SELECT * FROM auditoria_accesos ORDER BY id"):
        filas += 1
        esperado = cripto.firmar("auditoria", f"{anterior}|{_contenido(dict(fila))}")
        if fila["hash_anterior"] != anterior or fila["hash"] != esperado:
            return Verificacion(False, filas, fila["id"])
        anterior = fila["hash"]
    return Verificacion(True, filas, None)


def listar(
    conn: sqlite3.Connection,
    *,
    desde: str | None = None,
    hasta: str | None = None,
    usuario: str | None = None,
    ip: str | None = None,
    limite: int = 500,
) -> list[dict]:
    condiciones, parametros = [], []
    for campo, operador, valor in (
        ("ts", ">=", desde), ("ts", "<=", hasta), ("usuario_intentado", "=", usuario), ("ip", "=", ip),
    ):
        if valor is not None:
            condiciones.append(f"{campo} {operador} ?")
            parametros.append(valor)
    donde = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    filas = conn.execute(
        f"SELECT id, {', '.join(_COLUMNAS)} FROM auditoria_accesos {donde} ORDER BY id DESC LIMIT ?",
        [*parametros, limite],
    ).fetchall()
    return [dict(fila) for fila in filas]


def _celda_segura(valor: object) -> object:
    """Evita inyección de fórmulas al abrir el CSV en Excel: un texto que
    empieza con = + - @ (o tab/CR) se ejecutaría como fórmula."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


def exportar_csv(conn: sqlite3.Connection, destino: Path, desde: str | None, hasta: str | None) -> int:
    columnas = ("id", *_COLUMNAS, "hash_anterior", "hash")
    condiciones, parametros = [], []
    if desde:
        condiciones.append("ts >= ?")
        parametros.append(desde)
    if hasta:
        condiciones.append("ts <= ?")
        parametros.append(hasta)
    donde = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    filas = conn.execute(
        f"SELECT {', '.join(columnas)} FROM auditoria_accesos {donde} ORDER BY id", parametros
    ).fetchall()
    with destino.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(columnas)
        for fila in filas:
            escritor.writerow([_celda_segura(fila[columna]) for columna in columnas])
    return len(filas)
