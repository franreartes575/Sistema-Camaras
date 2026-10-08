"""«Pendientes» de una tarea: lo que queda por hacer, leído de las observaciones.

Los técnicos escriben en texto libre en Zeta; de ahí salen dos cosas que hay
que seguir: lo que hay que volver a programar y lo que quedó instalado y hay
que retirar (muchas veces con camión, porque está alto). Son reglas sobre
frases reales de las órdenes, no un modelo: si una frase nueva no entra,
se agrega acá con su test (`tests/test_pendientes.py`).

Se calcula al leer la tarea, no se guarda: si alguien corrige la
observación a mano, los pendientes la siguen.
"""

import re
import unicodedata

# Motivo de lo no realizado → detalle para «Reprogramar (…)». En orden: se
# listan todos los que aparezcan.
_REASONS = (
    (r"fin de turno|finde tu turno|falta de tiempo", "fin de turno"),
    (r"triangulaci|linea de vista|relevamiento ptp", "requiere triangulación"),
    (r"pendiente de equipo|falta de equipo|faltan? equipos?|no se tiene", "falta equipo"),
    (r"ausencia del cliente|no se encuentra|no esta en el domicilio", "ausencia del cliente"),
    (r"otra cuadrilla", "asignada a otra cuadrilla"),
    (r"sin energia", "sin energía"),
    (r"poste en mal estado|sin poste", "problema con el poste"),
)
# «No se retira (el) enlace/equipo/…»: lo que quedó instalado.
_NOT_REMOVED = re.compile(
    r"no se (?:lo |la |los |las )?retir\w*\s+(?:el |la |los |las |su )?"
    r"(enlace|equipo|soporte|poe|camara|antena|mickey|precinto)"
)
# Sin camión no se llega: lo dice la observación con estas palabras.
_NEEDS_TRUCK = re.compile(r"camion|hidro|grua|esta alto|en altura|escalera|no se llega")
# Valores de «INDICAR SI REQUIERE CAMION» que significan que no hace falta.
_NO_TRUCK = {"", "ninguno", "sin_datos", "sin datos", "no", "nan"}


def _plain(text: str) -> str:
    """Minúsculas y sin acentos, para buscar frases sin depender de cómo se tipearon."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def pendientes(status: str, observation: str | None, truck: str | None = None) -> str | None:
    """Lo que queda por hacer con una tarea, o None si nada.

    `status` es el estado efectivo (pendiente, realizada, no_realizada,
    reprogramada) y `truck`, la columna «INDICAR SI REQUIERE CAMION» de Zeta.
    """
    text = _plain(observation or "")
    actions: list[str] = []

    # Lo no realizado se reprograma (lo «reprogramada» ya está en un plan nuevo).
    if status == "no_realizada" or (status != "reprogramada" and "reprogram" in text):
        reasons = [label for pattern, label in _REASONS if re.search(pattern, text)]
        actions.append(f"Reprogramar ({'; '.join(reasons)})" if reasons else "Reprogramar")

    needs_truck = bool(_NEEDS_TRUCK.search(text))
    for item in dict.fromkeys(_NOT_REMOVED.findall(text)):
        actions.append(f"Retirar el {item} anterior" + (" con camión" if needs_truck else ""))

    flag = (truck or "").strip()
    if _plain(flag) not in _NO_TRUCK and not any("camión" in action for action in actions):
        actions.append(f"Requiere camión ({flag.lower()})")

    return "; ".join(actions) or None
