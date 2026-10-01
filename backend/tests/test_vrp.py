"""Tests del ruteo con presupuesto de jornada y punto de partida externo."""

import pytest

from app.services.routing import HaversineProvider
from app.services.vrp import build_day_routes

DEPOT = (-34.6000, -58.3816)
# Cuatro cámaras a ~1 km del depósito, en direcciones distintas: agruparlas
# de a varias en un mismo vehículo sale caro en manejo, así que un
# presupuesto horario chico las fuerza a repartirse en vehículos separados.
CAM_N = (-34.5910, -58.3816)
CAM_S = (-34.6090, -58.3816)
CAM_E = (-34.6000, -58.3706)
CAM_W = (-34.6000, -58.3926)
# ~550 km al sur: ida y vuelta a 40 km/h supera de lejos las 8 horas.
CAM_LEJANA = (-39.5000, -58.3816)

DAY_BUDGET_8H = 8 * 3600
SERVICE_10MIN = 600


def test_todas_las_camaras_entran_en_un_solo_vehiculo() -> None:
    """Con presupuesto amplio, un cluster chico sale en un solo recorrido."""
    points = [DEPOT, CAM_N, CAM_S, CAM_E, CAM_W]

    plan = build_day_routes(
        points,
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
    )

    assert len(plan.routes) == 1
    assert len(plan.routes[0].stops) == 4
    assert plan.unserved == ()


def test_todas_las_camaras_aparecen_una_sola_vez() -> None:
    """Ninguna cámara se pierde ni se duplica entre los vehículos-jornada."""
    points = [DEPOT, CAM_N, CAM_S, CAM_E, CAM_W]

    plan = build_day_routes(
        points,
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
    )

    visitados = sorted(stop.index for route in plan.routes for stop in route.stops)
    assert visitados == [1, 2, 3, 4]


def test_presupuesto_chico_reparte_en_varios_vehiculos() -> None:
    """Si no entra todo en una jornada, se arman varios recorridos."""
    points = [DEPOT, CAM_N, CAM_S, CAM_E, CAM_W]
    # Ida y vuelta a una sola cámara (~90s a 40km/h) + 10 min de servicio
    # entra holgado en 20 minutos; combinar dos cámaras lejanas entre sí, no.
    presupuesto_ajustado = 20 * 60

    plan = build_day_routes(
        points,
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=presupuesto_ajustado,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
    )

    assert len(plan.routes) >= 2
    for route in plan.routes:
        assert route.total_duration_s <= presupuesto_ajustado
    visitados = sorted(stop.index for route in plan.routes for stop in route.stops)
    assert visitados == [1, 2, 3, 4]
    assert plan.unserved == ()


def test_camara_que_no_entra_ni_sola_queda_fuera_sin_error() -> None:
    """Un presupuesto imposible no aborta: la cámara se informa como no cubierta."""
    plan = build_day_routes(
        [DEPOT, CAM_N],
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=60,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
    )

    assert plan.routes == ()
    assert plan.unserved == (1,)


def test_camara_lejana_no_impide_recorrer_las_demas() -> None:
    """Una cámara fuera de alcance se deja afuera y el resto se recorre igual."""
    points = [DEPOT, CAM_N, CAM_LEJANA, CAM_S]

    plan = build_day_routes(
        points,
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
    )

    assert plan.unserved == (2,)
    visitadas = sorted(stop.index for route in plan.routes for stop in route.stops)
    assert visitadas == [1, 3]


def test_sin_camaras_devuelve_plan_vacio() -> None:
    """Un punto de partida sin cámaras asignadas no arma ningún recorrido."""
    plan = build_day_routes(
        [DEPOT],
        HaversineProvider(),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
    )

    assert plan.routes == ()
    assert plan.unserved == ()


def test_el_punto_de_partida_no_aparece_como_parada() -> None:
    """`stops` nunca incluye el depósito: no es una cámara a visitar."""
    points = [DEPOT, CAM_N, CAM_S]

    plan = build_day_routes(
        points,
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
    )

    indices = {stop.index for route in plan.routes for stop in route.stops}
    assert 0 not in indices


def test_total_duration_incluye_tiempo_de_servicio() -> None:
    """El total no es sólo manejo: suma el tiempo de servicio por parada."""
    plan = build_day_routes(
        [DEPOT, CAM_N],
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
    )

    assert len(plan.routes) == 1
    # Ida y vuelta a ~1km a 40km/h son unos 180s de manejo; con 600s de
    # servicio el total tiene que ser bastante mayor que el manejo solo.
    assert plan.routes[0].total_duration_s > 600


# --------------------------------------------------------------------------
# Sentido del recorrido: la parada más lejana primero
# --------------------------------------------------------------------------

# Tres cámaras en línea hacia el norte: a ~1, ~2 y ~3 km del depósito.
CAM_1KM = (-34.5910, -58.3816)
CAM_2KM = (-34.5820, -58.3816)
CAM_3KM = (-34.5730, -58.3816)


def test_la_camara_mas_lejana_va_en_la_primera_mitad() -> None:
    """Se sale hacia lo más lejano y se vuelve acercándose a la base."""
    plan = build_day_routes(
        [DEPOT, CAM_1KM, CAM_2KM, CAM_3KM],
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
    )

    assert len(plan.routes) == 1
    orden = [stop.index for stop in plan.routes[0].stops]
    assert orden == [3, 2, 1]


def test_el_orden_de_las_paradas_es_correlativo() -> None:
    """`order` numera las paradas 0..n-1 en el sentido final del recorrido."""
    plan = build_day_routes(
        [DEPOT, CAM_1KM, CAM_2KM, CAM_3KM],
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
    )

    assert [stop.order for stop in plan.routes[0].stops] == [0, 1, 2]
    assert plan.routes[0].stops[0].distance_from_previous_m > 3000


# --------------------------------------------------------------------------
# Tope de cámaras por jornada
# --------------------------------------------------------------------------

# Doce cámaras en una grilla compacta: sin tope entran todas en una jornada.
GRID = [(-34.6000 + 0.002 * (i // 4), -58.3816 + 0.002 * (i % 4)) for i in range(12)]


def test_tope_de_camaras_por_dia_reparte_en_jornadas() -> None:
    """Con tope 5, doce cámaras salen en exactamente tres jornadas (5+5+2 o similar)."""
    plan = build_day_routes(
        [DEPOT, *GRID],
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
        max_stops_per_day=5,
    )

    assert len(plan.routes) == 3
    assert all(len(route.stops) <= 5 for route in plan.routes)
    visitadas = sorted(stop.index for route in plan.routes for stop in route.stops)
    assert visitadas == list(range(1, 13))


def test_sin_tope_no_cambia_el_comportamiento() -> None:
    """`max_stops_per_day=None` deja sólo el límite horario."""
    plan = build_day_routes(
        [DEPOT, *GRID],
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
        max_stops_per_day=None,
    )

    assert len(plan.routes) == 1
    assert len(plan.routes[0].stops) == 12


def test_minimo_por_dia_deja_a_lo_sumo_un_dia_corto() -> None:
    """Con mínimo 5, doce cámaras salen 5+5+2: sólo el día "resto" queda corto."""
    plan = build_day_routes(
        [DEPOT, *GRID],
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
        max_stops_per_day=5,
        min_stops_per_day=5,
    )

    cortos = [route for route in plan.routes if len(route.stops) < 5]
    assert len(cortos) <= 1
    visitadas = sorted(stop.index for route in plan.routes for stop in route.stops)
    assert visitadas == list(range(1, 13))


@pytest.mark.parametrize("minimo", [None, 5], ids=["sin minimo", "minimo 5"])
def test_el_dia_con_menos_camaras_queda_ultimo(minimo: int | None) -> None:
    """El día más liviano va al final: ahí se suman los pendientes de los demás."""
    plan = build_day_routes(
        [DEPOT, *GRID],
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
        max_stops_per_day=5,
        min_stops_per_day=minimo,
    )

    cantidades = [len(route.stops) for route in plan.routes]
    assert len(cantidades) == 3
    assert cantidades[-1] == min(cantidades)


def test_minimo_imposible_deja_camaras_fuera_por_regla_no_por_distancia() -> None:
    """Si el presupuesto no deja juntar el mínimo, las que sobran se informan aparte.

    Con 20 minutos sólo entra una cámara por jornada, así que con mínimo 2
    únicamente el día "resto" puede salir: tres de las cuatro quedan fuera,
    pero todas entrarían solas — no están fuera de alcance.
    """
    plan = build_day_routes(
        [DEPOT, CAM_N, CAM_S, CAM_E, CAM_W],
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=20 * 60,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
        min_stops_per_day=2,
    )

    assert len(plan.routes) == 1
    assert len(plan.unserved) == 3
    assert plan.out_of_reach == ()


def test_camara_lejana_figura_como_fuera_de_alcance() -> None:
    """`out_of_reach` distingue las que no entran ni yendo solas."""
    plan = build_day_routes(
        [DEPOT, CAM_N, CAM_LEJANA],
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
    )

    assert plan.unserved == (2,)
    assert plan.out_of_reach == (2,)


def test_tope_mayor_que_el_cluster_no_divide() -> None:
    """Si el tope supera la cantidad de cámaras, sale una sola jornada."""
    plan = build_day_routes(
        [DEPOT, CAM_N, CAM_S],
        HaversineProvider(average_speed_kmh=40),
        day_budget_s=DAY_BUDGET_8H,
        service_time_s=SERVICE_10MIN,
        time_limit_s=2,
        max_stops_per_day=5,
    )

    assert len(plan.routes) == 1
