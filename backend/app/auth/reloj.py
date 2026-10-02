"""Hora del sistema de autenticación: siempre UTC, con microsegundos.

Todo pasa por `ahora()` para que los tests puedan mover el reloj, y todo se
guarda como texto ISO-8601 con el mismo desplazamiento (+00:00): así las
fechas se comparan como texto en SQL sin convertir nada.
"""

import datetime as dt


def ahora() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(momento: dt.datetime) -> str:
    return momento.astimezone(dt.timezone.utc).isoformat(timespec="microseconds")


def desde_iso(texto: str) -> dt.datetime:
    return dt.datetime.fromisoformat(texto)
