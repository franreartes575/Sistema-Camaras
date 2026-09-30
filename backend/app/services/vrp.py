"""Ruteo con presupuesto de jornada, desde un punto de partida externo.

A diferencia de `optimizer.build_route` (un solo vehículo, TSP simple sobre
las cámaras mismas), acá el punto de partida es una ubicación real —una sede
guardada o una coordenada elegida a mano para ese cluster— que no es una
cámara a visitar. El recorrido se corta por tiempo: si el presupuesto de la
jornada (manejo real más un tiempo fijo de servicio por parada) no alcanza
para todas las cámaras del cluster, se reparten en varios recorridos
—vehículo-jornada— desde ese mismo punto, en vez de dejar cámaras sin cubrir.

Si una cámara no entra en ninguna jornada (ni yendo sola desde el punto de
partida, o porque la red vial no la conecta), queda fuera y se informa en
`DayPlan.unserved`: una cámara imposible no impide recorrer las demás.
"""

import math
from dataclasses import dataclass

import numpy as np
from ortools.constraint_solver import pywrapcp

from .optimizer import DEFAULT_TIME_LIMIT_S, Stop, default_search_parameters
from .routing import BudgetInfeasibleError, Point, RoutingProvider

# Mismo sustituto que optimizer.py para los pares que la red vial no conecta.
UNREACHABLE_COST = 10**9

# Costo ficticio por vehículo usado: empuja al solver a consolidar cámaras en
# menos vehículos-jornada en vez de repartirlas de a una, mientras el
# presupuesto horario lo permita.
VEHICLE_FIXED_COST = 3600

# Penalidad por dejar una cámara sin visitar. Supera con holgura el costo de
# cualquier jornada (a lo sumo 24 h de manejo) más un vehículo extra, así que
# el solver sólo descarta cámaras que de verdad no entran en ninguna jornada.
DROP_PENALTY = 10**7


@dataclass(frozen=True)
class DayRoute:
    """Un recorrido de un vehículo-jornada, dentro del presupuesto horario.

    `stops` nunca incluye el punto de partida: es una ubicación, no una
    cámara. `total_duration_s` ya incluye el tiempo de servicio de cada
    parada, no sólo el manejo.
    """

    stops: tuple[Stop, ...]
    total_distance_m: float
    total_duration_s: float
    has_unreachable_legs: bool


@dataclass(frozen=True)
class DayPlan:
    """Los recorridos de un cluster más las cámaras que no entraron en ninguno.

    `unserved` son índices de `points` (siempre >= 1) en orden ascendente.
    """

    routes: tuple[DayRoute, ...]
    unserved: tuple[int, ...]


def _to_int_matrix(matrix: np.ndarray) -> list[list[int]]:
    """Convierte a enteros, reemplazando los tramos inalcanzables."""
    finite = np.where(np.isfinite(matrix), matrix, UNREACHABLE_COST)
    return finite.round().astype(np.int64).tolist()


def _estimate_vehicle_count(
    durations_s: np.ndarray,
    service_time_s: float,
    day_budget_s: float,
    max_stops_per_day: int | None = None,
) -> int:
    """Cota superior de vehículos-jornada necesarios, segura por exceso.

    Estimación deliberadamente pesimista (cada cámara "cuesta" en promedio ir
    y volver sola desde el punto de partida): sobrestimar no tiene costo real,
    los vehículos sin uso simplemente no aparecen en el resultado. Con tope de
    cámaras por jornada, nunca baja de las jornadas que ese tope exige.
    """
    n_cameras = len(durations_s) - 1
    if n_cameras <= 0:
        return 1

    from_start = durations_s[0, 1:]
    finite = from_start[np.isfinite(from_start)]
    # Si ningún tramo es finito (OSRM no puede conectar nada desde acá), usar
    # el propio presupuesto como estimación: no hay mejor información.
    average_leg = float(finite.mean()) if len(finite) else day_budget_s

    estimate_s = service_time_s * n_cameras + 2.0 * average_leg * n_cameras
    by_time = math.ceil(estimate_s / day_budget_s) + 1
    by_stops = math.ceil(n_cameras / max_stops_per_day) + 1 if max_stops_per_day else 1
    return min(n_cameras, max(1, by_time, by_stops))


def _fits_alone(
    durations_s: np.ndarray, node: int, service_time_s: float, day_budget_s: float
) -> bool:
    """True si ir sólo a esta cámara y volver entra en una jornada."""
    trip = durations_s[0, node] + service_time_s + durations_s[node, 0]
    return bool(np.isfinite(trip)) and trip <= day_budget_s


def _solve(
    points: list[Point],
    durations_s: np.ndarray,
    num_vehicles: int,
    service_time_s: float,
    day_budget_s: float,
    time_limit_s: int,
    max_stops_per_day: int | None = None,
):
    """Arma y resuelve el modelo OR-Tools multi-vehículo con presupuesto horario."""
    costs = _to_int_matrix(durations_s)
    size = len(points)
    manager = pywrapcp.RoutingIndexManager(
        size, num_vehicles, [0] * num_vehicles, [0] * num_vehicles
    )
    routing = pywrapcp.RoutingModel(manager)

    def transit(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        # El tiempo de servicio se carga al llegar a una cámara, nunca al
        # volver al punto de partida (nodo 0).
        service = 0 if to_node == 0 else int(service_time_s)
        return costs[from_node][to_node] + service

    transit_index = routing.RegisterTransitCallback(transit)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_index)
    routing.AddDimension(transit_index, 0, int(day_budget_s), True, "Jornada")
    routing.SetFixedCostOfAllVehicles(VEHICLE_FIXED_COST)

    # Cada cámara es opcional con una penalidad alta: si alguna no entra en
    # ninguna jornada, el solver la deja afuera en vez de declarar inviable
    # el cluster entero.
    for node in range(1, size):
        routing.AddDisjunction([manager.NodeToIndex(node)], DROP_PENALTY)

    if max_stops_per_day:
        # Cada cámara pesa 1 y el punto de partida 0: la capacidad del
        # vehículo es el tope de cámaras que la cuadrilla atiende por jornada.
        demand_index = routing.RegisterUnaryTransitCallback(
            lambda index: 0 if manager.IndexToNode(index) == 0 else 1
        )
        routing.AddDimensionWithVehicleCapacity(
            demand_index, 0, [max_stops_per_day] * num_vehicles, True, "Camaras"
        )

    solution = routing.SolveWithParameters(default_search_parameters(time_limit_s))
    return manager, routing, solution


def _extract_route(
    manager,
    routing,
    solution,
    vehicle: int,
    distances_m: np.ndarray,
    durations_s: np.ndarray,
    service_time_s: float,
) -> DayRoute | None:
    """Lee el recorrido de un vehículo de la solución; None si no se usó."""
    start = routing.Start(vehicle)
    if solution.Value(routing.NextVar(start)) == routing.End(vehicle):
        return None

    stops: list[Stop] = []
    total_distance = 0.0
    total_duration = 0.0
    unreachable = False
    previous_node = manager.IndexToNode(start)
    index = solution.Value(routing.NextVar(start))

    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        leg_distance = distances_m[previous_node][node]
        leg_duration = durations_s[previous_node][node]
        reachable = bool(np.isfinite(leg_distance))
        if reachable:
            total_distance += float(leg_distance)
            total_duration += float(leg_duration) + service_time_s
        else:
            unreachable = True
        stops.append(
            Stop(
                order=len(stops),
                index=node,
                distance_from_previous_m=(
                    round(float(leg_distance), 1) if reachable else None
                ),
            )
        )
        previous_node = node
        index = solution.Value(routing.NextVar(index))

    # Tramo de vuelta al punto de partida: cuenta para el total, no se
    # lista como parada.
    return_distance = distances_m[previous_node][0]
    return_duration = durations_s[previous_node][0]
    if np.isfinite(return_distance):
        total_distance += float(return_distance)
        total_duration += float(return_duration)
    else:
        unreachable = True

    return DayRoute(
        stops=tuple(stops),
        total_distance_m=round(total_distance, 1),
        total_duration_s=round(total_duration, 1),
        has_unreachable_legs=unreachable,
    )


def _solve_plan(
    points: list[Point],
    distances_m: np.ndarray,
    durations_s: np.ndarray,
    num_vehicles: int,
    service_time_s: float,
    day_budget_s: float,
    time_limit_s: int,
    max_stops_per_day: int | None,
) -> DayPlan:
    """Resuelve con `num_vehicles` y arma el plan con las cámaras descartadas."""
    manager, routing, solution = _solve(
        points,
        durations_s,
        num_vehicles,
        service_time_s,
        day_budget_s,
        time_limit_s,
        max_stops_per_day,
    )
    if solution is None:
        # Con todas las cámaras opcionales siempre existe una solución (la
        # vacía); si no aparece, al solver le faltó tiempo, no presupuesto.
        raise BudgetInfeasibleError(
            "El optimizador no encontró ninguna solución para este cluster: "
            "pruebe con más tiempo de cálculo."
        )

    routes = []
    for vehicle in range(num_vehicles):
        route = _extract_route(
            manager, routing, solution, vehicle, distances_m, durations_s, service_time_s
        )
        if route is not None:
            routes.append(route)

    visited = {stop.index for route in routes for stop in route.stops}
    unserved = tuple(node for node in range(1, len(points)) if node not in visited)
    return DayPlan(routes=tuple(routes), unserved=unserved)


def build_day_routes(
    points: list[Point],
    provider: RoutingProvider,
    day_budget_s: float,
    service_time_s: float,
    time_limit_s: int = DEFAULT_TIME_LIMIT_S,
    max_stops_per_day: int | None = None,
) -> DayPlan:
    """Reparte `points[1:]` en tantos vehículos-jornada como haga falta.

    `points[0]` es el punto de partida (sede o coordenada elegida a mano):
    no es una cámara y nunca aparece en `DayRoute.stops`. Cada vehículo sale
    y vuelve a `points[0]` sin superar `day_budget_s` de manejo real más
    `service_time_s` por cámara visitada, ni `max_stops_per_day` cámaras si
    se indica. El solver agrupa en cada jornada las cámaras cercanas entre sí,
    así que el tope arma "sub-clusters" diarios sin un paso de agrupado aparte.
    Las cámaras que no entran en ninguna jornada vuelven en `unserved`.
    """
    num_cameras = len(points) - 1
    if num_cameras <= 0:
        return DayPlan(routes=(), unserved=())

    distances_m, durations_s = provider.travel_matrix(points)

    def solve(num_vehicles: int) -> DayPlan:
        return _solve_plan(
            points,
            distances_m,
            durations_s,
            num_vehicles,
            service_time_s,
            day_budget_s,
            time_limit_s,
            max_stops_per_day,
        )

    num_vehicles = _estimate_vehicle_count(
        durations_s, service_time_s, day_budget_s, max_stops_per_day
    )
    plan = solve(num_vehicles)

    dropped_but_feasible = any(
        _fits_alone(durations_s, node, service_time_s, day_budget_s)
        for node in plan.unserved
    )
    if dropped_but_feasible and num_vehicles < num_cameras:
        # La estimación de vehículos se quedó corta: quedó afuera una cámara
        # que sola sí entra. Reintentar con el máximo seguro (un vehículo por
        # cámara) antes de darla por no cubierta.
        plan = solve(num_cameras)

    return plan
