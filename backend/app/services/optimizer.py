"""Optimización del orden de visita dentro de cada cluster.

Cada cluster de cámaras se resuelve como un TSP independiente: la cuadrilla
entra a la zona, recorre todas sus cámaras y sale. Separar por cluster antes de
optimizar mantiene el problema chico —OR-Tools escala mal con cientos de
paradas— y refleja cómo se reparte el trabajo en la práctica.
"""

from dataclasses import dataclass

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .routing import Point, RoutingError, RoutingProvider

# Sustituto finito para los pares que la red vial no conecta. Alto para que el
# solver los evite, pero no infinito, que desborda el entero del solver.
UNREACHABLE_COST = 10**9

DEFAULT_TIME_LIMIT_S = 5


@dataclass(frozen=True)
class Stop:
    """Una parada del recorrido, ya ordenada.

    `distance_from_previous_m` vale None cuando el motor de ruteo no puede
    conectar este tramo por la red vial: reportarlo como 0 haría parecer que
    las paradas son contiguas cuando en realidad el recorrido no es transitable.
    """

    order: int
    index: int
    distance_from_previous_m: float | None


@dataclass(frozen=True)
class Route:
    """Recorrido resuelto para un conjunto de puntos.

    `total_distance_m` suma sólo los tramos transitables; si
    `has_unreachable_legs` es True ese total subestima el recorrido real y hay
    que advertírselo al usuario en vez de mostrarlo como un número firme.
    """

    order: tuple[int, ...]
    stops: tuple[Stop, ...]
    total_distance_m: float
    geometry: tuple[Point, ...]
    has_unreachable_legs: bool = False


def _to_int_matrix(matrix: np.ndarray) -> list[list[int]]:
    """Convierte a enteros, reemplazando los tramos inalcanzables."""
    finite = np.where(np.isfinite(matrix), matrix, UNREACHABLE_COST)
    return finite.round().astype(np.int64).tolist()


def default_search_parameters(
    time_limit_s: int,
    first_solution_strategy: int = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC,
):
    """Estrategia de búsqueda: solución inicial golosa y luego mejora local.

    Pública porque `vrp.py` la reutiliza para el modelo multi-vehículo: es
    la misma búsqueda local, sólo cambian el modelo y la solución inicial.
    """
    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = first_solution_strategy
    parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    parameters.time_limit.FromSeconds(time_limit_s)
    return parameters


def solve_order(
    matrix: np.ndarray,
    depot: int = 0,
    round_trip: bool = False,
    time_limit_s: int = DEFAULT_TIME_LIMIT_S,
) -> list[int]:
    """Devuelve el orden de visita que minimiza la distancia total.

    Con `round_trip=False` el recorrido es abierto: la cuadrilla termina en la
    última cámara y no vuelve al punto de partida. Eso se modela poniendo en
    cero el costo de regreso a la base.
    """
    size = len(matrix)
    if size == 0:
        return []
    if size <= 2:
        # Con una o dos paradas el orden ya es óptimo, pero el regreso al
        # depósito sigue siendo parte del recorrido si se pidió cerrado.
        trivial = list(range(size))
        return trivial + [depot] if round_trip and size > 1 else trivial

    costs = _to_int_matrix(matrix)
    manager = pywrapcp.RoutingIndexManager(size, 1, depot)
    routing = pywrapcp.RoutingModel(manager)

    def distance(from_index: int, to_index: int) -> int:
        """Costo del arco, en la indexación interna del solver."""
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        # Recorrido abierto: volver al depósito no cuesta nada, así que el
        # solver no deforma el orden para acortar ese último tramo.
        if not round_trip and to_node == depot:
            return 0
        return costs[from_node][to_node]

    transit = routing.RegisterTransitCallback(distance)
    routing.SetArcCostEvaluatorOfAllVehicles(transit)

    solution = routing.SolveWithParameters(default_search_parameters(time_limit_s))
    if solution is None:
        raise RoutingError("OR-Tools no encontró un recorrido válido para este cluster.")

    order: list[int] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        order.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))

    if round_trip:
        order.append(depot)

    return order


def _leg_distance(matrix: np.ndarray, previous: int, current: int) -> float | None:
    """Distancia de un tramo, o None si la red vial no lo conecta."""
    raw = matrix[previous][current]
    return float(raw) if np.isfinite(raw) else None


def build_route(
    points: list[Point],
    provider: RoutingProvider,
    depot: int = 0,
    round_trip: bool = False,
    time_limit_s: int = DEFAULT_TIME_LIMIT_S,
) -> Route:
    """Resuelve el orden de visita y arma la geometría del recorrido."""
    if not points:
        return Route(order=(), stops=(), total_distance_m=0.0, geometry=())

    matrix = provider.distance_matrix(points)
    order = solve_order(
        matrix, depot=depot, round_trip=round_trip, time_limit_s=time_limit_s
    )

    stops: list[Stop] = []
    total = 0.0
    unreachable = False
    for position, node in enumerate(order):
        leg = (
            0.0 if position == 0 else _leg_distance(matrix, order[position - 1], node)
        )
        if leg is None:
            unreachable = True
        else:
            total += leg
        stops.append(
            Stop(
                order=position,
                index=node,
                distance_from_previous_m=None if leg is None else round(leg, 1),
            )
        )

    ordered_points = [points[node] for node in order]

    return Route(
        order=tuple(order),
        stops=tuple(stops),
        total_distance_m=round(total, 1),
        geometry=tuple(provider.route_geometry(ordered_points)),
        has_unreachable_legs=unreachable,
    )
