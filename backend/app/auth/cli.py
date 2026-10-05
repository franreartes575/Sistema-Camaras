"""Administración de cuentas y auditoría desde la consola del servidor.

    python -m app.auth.cli inicializar
    python -m app.auth.cli crear-usuario --usuario jperez --nombre "Juan Pérez" --rol operador
    python -m app.auth.cli listar-usuarios
    python -m app.auth.cli desbloquear --usuario jperez
    python -m app.auth.cli resetear-password --usuario jperez
    python -m app.auth.cli deshabilitar --usuario jperez        (y habilitar)
    python -m app.auth.cli revocar-sesiones --usuario jperez
    python -m app.auth.cli verificar-auditoria
    python -m app.auth.cli exportar-auditoria --salida accesos.csv [--desde 2026-10-01] [--hasta 2026-10-31]

No hay endpoint HTTP para crear o desbloquear cuentas a propósito: hace falta
acceso al servidor, que es una barrera más que una sesión web robada. Cada
acción queda en la auditoría con el usuario del sistema operativo.
"""

import argparse
import getpass
import sys
from pathlib import Path

from .. import config
from . import auditoria, cripto, db, servicio
from .contexto import ContextoPedido


def _pedir_password(usuario: str) -> str:
    from .contrasenas import problemas_politica

    while True:
        primera = getpass.getpass(f"Contraseña para '{usuario}': ")
        problemas = problemas_politica(primera, usuario)
        if problemas:
            print("  " + " ".join(problemas))
            continue
        if getpass.getpass("Repetila: ") != primera:
            print("  No coinciden.")
            continue
        return primera


def _inicializar(_: argparse.Namespace) -> None:
    if config.AUTH_MASTER_KEY:
        print("La clave maestra viene de AUTH_MASTER_KEY: no se crea archivo.")
    else:
        ruta = Path(config.AUTH_MASTER_KEY_FILE)
        if ruta.exists():
            print(f"La clave maestra ya existe en {ruta}. No se toca.")
        else:
            cripto.guardar_clave_maestra(ruta)
            print(f"Clave maestra creada en {ruta} (sólo lectura para el dueño).")
            print("RESPALDALA en un lugar seguro y separado de la base: sin ella no se")
            print("puede verificar la auditoría.")
    cripto.clave_maestra()
    db.connect().close()
    print(f"Base de seguridad lista en {config.AUTH_DB_PATH}.")


def _crear_usuario(args: argparse.Namespace) -> None:
    password = _pedir_password(args.usuario)
    conn = db.connect()
    try:
        servicio.crear_usuario(
            conn, args.usuario, args.nombre, args.rol, password, ContextoPedido.consola(),
            debe_cambiar_password=not args.sin_cambio_obligatorio,
        )
    finally:
        conn.close()
    print(f"Usuario '{servicio.normalizar_usuario(args.usuario)}' creado.")


def _listar(_: argparse.Namespace) -> None:
    conn = db.connect()
    try:
        filas = servicio.listar_usuarios(conn)
    finally:
        conn.close()
    print(f"{'usuario':<20} {'rol':<9} {'estado':<22} último acceso")
    for fila in filas:
        if not fila["activo"]:
            estado = "deshabilitado"
        elif fila["bloqueado_permanente"]:
            estado = "BLOQUEADO"
        elif fila["bloqueado_hasta"]:
            estado = f"bloqueo hasta {fila['bloqueado_hasta'][11:16]} UTC"
        else:
            estado = "activo"
        print(
            f"{fila['usuario']:<20} {fila['rol']:<9} {estado:<22} "
            f"{fila['ultimo_acceso_en'] or '—'}"
        )


def _accion(nombre: str):
    def ejecutar(args: argparse.Namespace) -> None:
        conn = db.connect()
        try:
            servicio.administrar(conn, args.usuario, nombre, ContextoPedido.consola())
        finally:
            conn.close()
        print(f"Hecho: {nombre.replace('_', ' ')} para '{args.usuario}'.")

    return ejecutar


def _resetear_password(args: argparse.Namespace) -> None:
    password = _pedir_password(args.usuario)
    conn = db.connect()
    try:
        servicio.resetear_password(conn, args.usuario, password, ContextoPedido.consola())
    finally:
        conn.close()
    print("Contraseña provisoria puesta; la va a tener que cambiar al entrar. Sesiones cerradas.")


def _verificar(_: argparse.Namespace) -> None:
    conn = db.connect()
    try:
        resultado = auditoria.verificar_cadena(conn)
    finally:
        conn.close()
    if resultado.integra:
        print(f"Auditoría íntegra: {resultado.filas} eventos, cadena completa.")
        return
    print(f"AUDITORÍA ALTERADA: la cadena se rompe en el evento id={resultado.primera_alterada}.")
    sys.exit(2)


def _exportar(args: argparse.Namespace) -> None:
    conn = db.connect()
    try:
        cantidad = auditoria.exportar_csv(conn, Path(args.salida), args.desde, args.hasta)
    finally:
        conn.close()
    print(f"{cantidad} eventos exportados a {args.salida}.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.auth.cli", description=__doc__.split("\n\n")[0])
    comandos = parser.add_subparsers(dest="comando", required=True)

    comandos.add_parser("inicializar", help="Crea la clave maestra y la base de seguridad").set_defaults(fn=_inicializar)

    crear = comandos.add_parser("crear-usuario", help="Alta de una cuenta (pide la contraseña)")
    crear.add_argument("--usuario", required=True)
    crear.add_argument("--nombre", required=True)
    crear.add_argument("--rol", choices=("admin", "operador"), default="operador")
    crear.add_argument(
        "--sin-cambio-obligatorio", action="store_true",
        help="No obligar a cambiar la contraseña en el primer ingreso",
    )
    crear.set_defaults(fn=_crear_usuario)

    comandos.add_parser("listar-usuarios").set_defaults(fn=_listar)

    for comando, accion, ayuda in (
        ("desbloquear", "desbloquear", "Levanta un bloqueo temporal o permanente"),
        ("deshabilitar", "deshabilitar", "Impide el acceso y cierra sus sesiones"),
        ("habilitar", "habilitar", "Vuelve a permitir el acceso"),
        ("revocar-sesiones", "revocar_sesiones", "Cierra todas sus sesiones ya mismo"),
    ):
        sub = comandos.add_parser(comando, help=ayuda)
        sub.add_argument("--usuario", required=True)
        sub.set_defaults(fn=_accion(accion))

    resetear = comandos.add_parser("resetear-password", help="Contraseña provisoria (obliga a cambiarla)")
    resetear.add_argument("--usuario", required=True)
    resetear.set_defaults(fn=_resetear_password)

    comandos.add_parser("verificar-auditoria", help="Comprueba que nadie alteró la auditoría").set_defaults(fn=_verificar)

    exportar = comandos.add_parser("exportar-auditoria", help="Auditoría a CSV (para un pedido judicial)")
    exportar.add_argument("--salida", required=True)
    exportar.add_argument("--desde", help="AAAA-MM-DD (UTC)")
    exportar.add_argument("--hasta", help="AAAA-MM-DD (UTC, inclusive)")
    exportar.set_defaults(fn=_exportar)

    args = parser.parse_args(argv)
    if getattr(args, "hasta", None) and len(args.hasta) == 10:
        args.hasta += "T23:59:59.999999+00:00"
    try:
        args.fn(args)
    except (servicio.ErrorAuth, cripto.ClaveMaestraFaltante) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
