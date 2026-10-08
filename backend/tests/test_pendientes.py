"""Tests de la columna «Pendientes»: lo que queda por hacer, leído de las observaciones.

Las frases son de las órdenes de trabajo reales (Zeta) del plan de Martearena.
"""

import pytest

from app.services.pendientes import pendientes


@pytest.mark.parametrize(
    ("observacion", "esperado"),
    [
        ("Fin de turno", "Reprogramar (fin de turno)"),
        (
            "Fin de turno. No se realiza por fin de turno se informa a supervisor Flavio Concepción",
            "Reprogramar (fin de turno)",
        ),
        (
            "Sin linea de vista. No se realiza migración de camara 1-1494 ya que no tiene línea de "
            "vista para poder migrarlo hacia otro nodo requiere una triangulacion",
            "Reprogramar (requiere triangulación)",
        ),
        ("Pendiente de equipo. Sin Observaciones.", "Reprogramar (falta equipo)"),
        ("Fin de turno. Finde tu turno y a su vez no se tiene más 450 de alta", "Reprogramar (fin de turno; falta equipo)"),
        ("Se asigna a otra cuadrilla", "Reprogramar (asignada a otra cuadrilla)"),
        (None, "Reprogramar"),
    ],
)
def test_lo_no_realizado_hay_que_reprogramarlo(observacion, esperado) -> None:
    assert pendientes("no_realizada", observacion) == esperado


def test_enlace_que_quedo_instalado_y_hay_que_retirar_con_camion() -> None:
    """Caso 1-0384: se migró, pero el enlace anterior sigue en el poste."""
    observacion = (
        "Se realiza asistencia con exito de camara 1-0384 se deja el servicio funcionando "
        "correctamente comprobado por IDA y el departamento de ids se coloca enlace y se lo "
        "migramos a atocha no se retira enlace previamente instalado ya que es para camion se "
        "informa a supervisor a cargo se demora por configuraciones de ids"
    )

    assert pendientes("realizada", observacion) == "Retirar el enlace anterior con camión"


def test_equipo_en_altura_tambien_pide_camion() -> None:
    """Caso 1-1244: «está alto y con escalera no se llega»."""
    observacion = (
        "Se realiza asistencia con exito se deja el servicio funcionando correctamente comprobado "
        "por IDA y el departamento de ids se migra de nodo se coloca enlace y se realiza un nuevo "
        "cableado no se retira equipo que ya tenia porq esta alto y con escalera no se llega se "
        "informa a supervisor y logística"
    )

    assert pendientes("realizada", observacion) == "Retirar el equipo anterior con camión"


def test_lo_que_no_se_retiro_sin_necesidad_de_camion() -> None:
    assert pendientes("realizada", "Se retira force 190 con soprte de 2 mts. No se retira poe") == (
        "Retirar el poe anterior"
    )


@pytest.mark.parametrize(
    "observacion",
    [
        "Asistencia con éxito , se migra de nodo y se deja funcionando correctamente, verificado por IDA e IDS",
        "Migración de nodo con éxito , se deja funcionando verificado por IDA e IDS.",
        None,
    ],
)
def test_una_tarea_hecha_sin_novedades_no_deja_pendientes(observacion) -> None:
    assert pendientes("realizada", observacion) is None


def test_lo_pendiente_sin_informar_no_dice_nada() -> None:
    assert pendientes("pendiente", None) is None


def test_la_columna_de_camion_de_zeta_cuenta_aunque_la_observacion_no_lo_diga() -> None:
    assert pendientes("realizada", "Se cambia trafo de 12v la camara", "ENLACE") == (
        "Requiere camión (enlace)"
    )
    assert pendientes("realizada", "Todo ok", "ENLACE Y CAMARA") == "Requiere camión (enlace y camara)"


@pytest.mark.parametrize("valor", ["NINGUNO", "sin_datos", "", None])
def test_sin_camion_en_zeta_no_agrega_nada(valor) -> None:
    assert pendientes("realizada", "Todo ok", valor) is None


def test_no_repite_el_camion_si_la_observacion_ya_lo_pide() -> None:
    observacion = "no se retira enlace previamente instalado ya que es para camion"

    assert pendientes("realizada", observacion, "ENLACE") == "Retirar el enlace anterior con camión"


def test_una_reprogramada_ya_se_volvio_a_planificar() -> None:
    """Si ya está en un plan posterior, reprogramarla no es un pendiente; retirar, sí."""
    assert pendientes("reprogramada", "Fin de turno") is None
    assert pendientes("reprogramada", "no se retira enlace es para camion") == (
        "Retirar el enlace anterior con camión"
    )


def test_varias_cosas_pendientes_van_juntas() -> None:
    observacion = "Sin linea de vista. Requiere triangulacion. No se retira el soporte, esta alto"

    assert pendientes("no_realizada", observacion, "ESTANCO") == (
        "Reprogramar (requiere triangulación); Retirar el soporte anterior con camión"
    )
