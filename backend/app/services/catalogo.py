"""Catálogo de cámaras y sedes: lo que alimenta el Inicio y el selector de cámaras.

El catálogo guarda todas las cámaras, se planifiquen o no. Se carga
importando planillas (se combina por ID: nunca borra) y cada cámara lleva su
localidad, calculada por coordenadas (ver `localidades`). El cruce con el
registro es por el texto del ID, igual que entre planes.

Mismas convenciones que `registro.py`: las funciones reciben la conexión, las
columnas de la base están en castellano y la API las devuelve en inglés.
"""

import datetime as dt
import hashlib
import math
import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd

from ..ingesta import Ingested
from ..schemas import (
    CatalogCamera,
    CatalogCameraUpdate,
    CatalogCluster,
    CatalogClusterCamera,
    CatalogClusters,
    CatalogImport,
    CatalogImportResult,
    CatalogSummary,
    Depot,
    DepotIn,
    DepotReach,
    DiscardedRow,
    LocalitySummary,
    MonthTasks,
    TaskCounts,
    VisitAge,
)
from . import localidades
from .clustering import (
    DEPOT_MAX_KM,
    cluster_by_depot,
    haversine_km,
    nearest_depot,
    reassign_noise,
    run_dbscan,
)
from .registro import ConflictError, NotFoundError, _clean, _now

# Cuántos meses hacia atrás (contando el actual) muestra la serie de tareas,
# y hasta cuántos hacia adelante si ya hay jornadas programadas.
MONTHS_BACK = 12
MONTHS_AHEAD = 3

# Coordenadas iguales a esta precisión (~1 cm) son la misma ubicación: evita
# contar como "actualizada" una cámara que sólo cambió por redondeo.
_COORD_DIGITS = 7

_CAMERA_COLUMNS = """
    c.id, c.lat, c.lon, c.localidad AS locality,
    c.localidad_manual AS locality_manual, c.descripcion AS label,
    c.nodo AS node, c.observacion AS observation,
    c.creada_en AS created_at, c.actualizada_en AS updated_at,
    COALESCE(v.realizadas, 0) AS visits, v.ultima_visita AS last_visit,
    u.estado AS last_status, u.fecha AS last_planned
"""

# Lo que dice el registro de cada cámara: cuántas veces se hizo, cuándo fue la
# última, y el estado de su tarea más reciente (la del plan más nuevo).
_CAMERA_FROM = """
    FROM camaras c
    LEFT JOIN (
        SELECT pa.camara_id, COUNT(*) AS realizadas, MAX(r.fecha) AS ultima_visita
        FROM paradas pa JOIN recorridos r ON r.id = pa.recorrido_id
        WHERE pa.estado = 'realizada'
        GROUP BY pa.camara_id
    ) v ON v.camara_id = c.id
    LEFT JOIN (
        SELECT pa.camara_id, pa.estado, r.fecha,
               ROW_NUMBER() OVER (
                   PARTITION BY pa.camara_id
                   ORDER BY r.plan_id DESC, r.fecha DESC, pa.id DESC
               ) AS n
        FROM paradas pa JOIN recorridos r ON r.id = pa.recorrido_id
    ) u ON u.camara_id = c.id AND u.n = 1
"""


def list_cameras(conn: sqlite3.Connection) -> list[CatalogCamera]:
    rows = conn.execute(f"SELECT {_CAMERA_COLUMNS} {_CAMERA_FROM} ORDER BY c.id").fetchall()
    return [CatalogCamera(**dict(row)) for row in rows]


def get_camera(conn: sqlite3.Connection, camera_id: str) -> CatalogCamera:
    row = conn.execute(
        f"SELECT {_CAMERA_COLUMNS} {_CAMERA_FROM} WHERE c.id = ?", (camera_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"La cámara '{camera_id}' no está en el catálogo.")
    return CatalogCamera(**dict(row))


def update_camera(
    conn: sqlite3.Connection, camera_id: str, changes: CatalogCameraUpdate
) -> CatalogCamera:
    """Corrige la localidad a mano, o la devuelve al cálculo con None."""
    camera = get_camera(conn, camera_id)
    manual = _clean(changes.locality)
    locality = manual or localidades.localidad_de(camera.lat, camera.lon)
    with conn:
        conn.execute(
            """
            UPDATE camaras SET localidad = ?, localidad_manual = ?, actualizada_en = ?
            WHERE id = ?
            """,
            (locality, int(manual is not None), _now(), camera_id),
        )
    return get_camera(conn, camera_id)


def delete_camera(conn: sqlite3.Connection, camera_id: str) -> None:
    """Da de baja una cámara. Sus tareas del registro quedan como estaban."""
    with conn:
        cursor = conn.execute("DELETE FROM camaras WHERE id = ?", (camera_id,))
    if cursor.rowcount == 0:
        raise NotFoundError(f"La cámara '{camera_id}' no está en el catálogo.")


def recalcular_localidades(
    conn: sqlite3.Connection, limites: localidades.Limites | None = None
) -> int:
    """Vuelve a calcular la localidad de todo el catálogo (salvo las manuales).

    Devuelve cuántas cambiaron. Va dentro de la transacción de quien la llame.
    """
    limites = limites or localidades.cargar()
    rows = conn.execute(
        "SELECT id, lat, lon, localidad FROM camaras WHERE localidad_manual = 0"
    ).fetchall()
    changes = []
    for row in rows:
        locality = localidades.localidad_de(row["lat"], row["lon"], limites)
        if locality != row["localidad"]:
            changes.append((locality, row["id"]))
    conn.executemany("UPDATE camaras SET localidad = ? WHERE id = ?", changes)
    return len(changes)


def _text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return _clean(str(value))


def import_points(conn: sqlite3.Connection, ingested: Ingested) -> CatalogImportResult:
    """Combina la planilla con el catálogo, por ID.

    Agrega las cámaras nuevas y actualiza las que cambiaron. Nunca borra: una
    cámara que no viene en la planilla queda como estaba. Una celda vacía
    tampoco pisa lo que ya había (descripción, nodo, observación). Al final
    recalcula las localidades de todo el catálogo.
    """
    incoming: dict[str, dict] = {}
    for record in ingested.points.to_dict("records"):
        incoming[str(record["id"]).strip()] = {
            "lat": round(float(record["lat"]), _COORD_DIGITS),
            "lon": round(float(record["lon"]), _COORD_DIGITS),
            "descripcion": _text(record.get("label")),
            "nodo": _text(record.get("node")),
            "observacion": _text(record.get("observation")),
        }
    duplicates = len(ingested.points) - len(incoming)

    existing = {
        row["id"]: dict(row)
        for row in conn.execute(
            "SELECT id, lat, lon, descripcion, nodo, observacion FROM camaras"
        ).fetchall()
    }
    digest = hashlib.sha256(ingested.raw).hexdigest()
    now = _now()
    added = updated = unchanged = 0
    limites = localidades.cargar()

    with conn:
        previous = conn.execute(
            "SELECT cargado_en FROM cargas_catalogo WHERE sha256 = ? ORDER BY id DESC LIMIT 1",
            (digest,),
        ).fetchone()
        for camera_id, new in incoming.items():
            old = existing.get(camera_id)
            if old is None:
                conn.execute(
                    """
                    INSERT INTO camaras (
                        id, lat, lon, localidad, descripcion, nodo, observacion,
                        creada_en, actualizada_en
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        camera_id, new["lat"], new["lon"],
                        localidades.localidad_de(new["lat"], new["lon"], limites),
                        new["descripcion"], new["nodo"], new["observacion"], now, now,
                    ),
                )
                added += 1
                continue
            merged = {
                key: new[key] if new[key] is not None else old[key]
                for key in ("lat", "lon", "descripcion", "nodo", "observacion")
            }
            if all(merged[key] == old[key] for key in merged):
                unchanged += 1
                continue
            conn.execute(
                """
                UPDATE camaras
                SET lat = ?, lon = ?, descripcion = ?, nodo = ?, observacion = ?,
                    actualizada_en = ?
                WHERE id = ?
                """,
                (
                    merged["lat"], merged["lon"], merged["descripcion"], merged["nodo"],
                    merged["observacion"], now, camera_id,
                ),
            )
            updated += 1

        recalcular_localidades(conn, limites)
        cursor = conn.execute(
            """
            INSERT INTO cargas_catalogo (
                archivo, sha256, cargado_en, filas, nuevas, actualizadas,
                sin_cambios, descartadas
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ingested.filename, digest, now, ingested.total_rows, added, updated,
                unchanged, len(ingested.discarded),
            ),
        )

    camera_count = conn.execute("SELECT COUNT(*) FROM camaras").fetchone()[0]
    return CatalogImportResult(
        import_id=int(cursor.lastrowid or 0),
        filename=ingested.filename,
        rows=ingested.total_rows,
        valid=len(ingested.points),
        added=added,
        updated=updated,
        unchanged=unchanged,
        duplicates=duplicates,
        discarded=[DiscardedRow(**row) for row in ingested.discarded],
        camera_count=camera_count,
        municipalities_loaded=limites is not None,
        warning=ingested.warning,
        previously_loaded_at=previous["cargado_en"] if previous else None,
    )


def list_imports(conn: sqlite3.Connection) -> list[CatalogImport]:
    rows = conn.execute(
        """
        SELECT id, archivo AS filename, cargado_en AS loaded_at, filas AS "rows",
               nuevas AS added, actualizadas AS updated, sin_cambios AS unchanged,
               descartadas AS discarded
        FROM cargas_catalogo ORDER BY id DESC LIMIT 200
        """
    ).fetchall()
    return [CatalogImport(**dict(row)) for row in rows]


def cameras_for_selection(
    conn: sqlite3.Connection, ids: list[str]
) -> tuple[list[CatalogCamera], list[str]]:
    """Las cámaras pedidas, en el orden pedido y sin repetir, y las que faltan."""
    by_id = {camera.id: camera for camera in list_cameras(conn)}
    wanted = list(dict.fromkeys(camera_id.strip() for camera_id in ids if camera_id.strip()))
    found = [by_id[camera_id] for camera_id in wanted if camera_id in by_id]
    missing = [camera_id for camera_id in wanted if camera_id not in by_id]
    return found, missing


# --------------------------------------------------------------------------
# Clusters del catálogo, con colores
# --------------------------------------------------------------------------


def _edge_distances_km(clusters: list[dict]) -> np.ndarray:
    """Distancia entre los bordes de cada par de clusters (0 si se tocan)."""
    lat = np.array([cluster["centroid_lat"] for cluster in clusters])
    lon = np.array([cluster["centroid_lon"] for cluster in clusters])
    radius = np.array([cluster["radius_km"] for cluster in clusters])
    distances = np.vstack(
        [haversine_km(lat, lon, lat[i], lon[i]) for i in range(len(clusters))]
    )
    return np.maximum(distances - radius[:, None] - radius[None, :], 0.0)


def assign_colors(clusters: list[dict], palette_size: int) -> list[int]:
    """Un color por cluster, que los cercanos no compartan.

    De los más grandes a los más chicos, cada cluster toma el color cuyo
    cluster más cercano ya pintado está más lejos. Mientras quede un color sin
    usar cerca, lo usa; con más clusters que colores, los que se repiten
    quedan lo más separados posible. La identidad del cluster la sigue
    llevando el rótulo: el color sólo ayuda a separar vecinos.
    """
    if not clusters:
        return []
    distances = _edge_distances_km(clusters)
    order = sorted(range(len(clusters)), key=lambda i: (-clusters[i]["size"], clusters[i]["id"]))
    colors: list[int | None] = [None] * len(clusters)
    for index in order:
        best_color, best_distance = 0, -1.0
        for color in range(palette_size):
            same = [j for j, assigned in enumerate(colors) if assigned == color]
            nearest = min((distances[index, j] for j in same), default=math.inf)
            if nearest > best_distance:
                best_color, best_distance = color, nearest
        colors[index] = best_color
    return [int(color or 0) for color in colors]


def cluster_catalog(
    conn: sqlite3.Connection,
    eps_km: float,
    min_samples: int,
    noise_reassign_factor: float,
    palette_size: int,
    by_depot: bool = True,
    depot_max_km: float = DEPOT_MAX_KM,
) -> CatalogClusters:
    """Agrupa todo el catálogo como el planificador: por zona de sede (con las
    sedes guardadas) y, lo que queda lejos de toda sede, por cercanía."""
    empty = CatalogClusters(
        eps_km=eps_km, by_depot=by_depot, depot_max_km=depot_max_km,
        cameras=[], clusters=[], noise_count=0,
    )
    rows = conn.execute("SELECT id, lat, lon FROM camaras ORDER BY id").fetchall()
    if not rows:
        return empty

    points = pd.DataFrame([dict(row) for row in rows])
    depots = list_depots(conn) if by_depot else []
    if depots:
        labels, clusters, _ = cluster_by_depot(
            points, [(depot.lat, depot.lon) for depot in depots], depot_max_km,
            eps_km, min_samples, noise_reassign_factor,
        )
        for cluster in clusters:
            if cluster["depot"] is not None:
                depot = depots[int(cluster["depot"])]
                cluster["depot"] = {"name": depot.name, "lat": depot.lat, "lon": depot.lon}
    else:
        labels, clusters = run_dbscan(points, eps_km=eps_km, min_samples=min_samples)
        labels, clusters = reassign_noise(
            points, labels, clusters, max_km=eps_km * noise_reassign_factor
        )
    colors = assign_colors(clusters, palette_size)
    return CatalogClusters(
        eps_km=eps_km,
        by_depot=by_depot,
        depot_max_km=depot_max_km,
        cameras=[
            CatalogClusterCamera(id=row["id"], cluster=int(label))
            for row, label in zip(rows, labels, strict=True)
        ],
        clusters=[
            CatalogCluster(**cluster, color=color)
            for cluster, color in zip(clusters, colors, strict=True)
        ],
        noise_count=int(np.sum(labels == -1)),
    )


# --------------------------------------------------------------------------
# Sedes
# --------------------------------------------------------------------------

_DEPOT_COLUMNS = "id, nombre AS name, lat, lon, creada_en AS created_at"


def list_depots(conn: sqlite3.Connection) -> list[Depot]:
    rows = conn.execute(
        f"SELECT {_DEPOT_COLUMNS} FROM sedes ORDER BY nombre COLLATE NOCASE"
    ).fetchall()
    return [Depot(**dict(row)) for row in rows]


def _get_depot(conn: sqlite3.Connection, depot_id: int) -> Depot:
    row = conn.execute(f"SELECT {_DEPOT_COLUMNS} FROM sedes WHERE id = ?", (depot_id,)).fetchone()
    if row is None:
        raise NotFoundError("La sede no existe.")
    return Depot(**dict(row))


def _depot_name(depot: DepotIn) -> str:
    name = _clean(depot.name)
    if name is None:
        raise ValueError("La sede necesita un nombre.")
    return name


def create_depot(conn: sqlite3.Connection, depot: DepotIn) -> Depot:
    name = _depot_name(depot)
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO sedes (nombre, lat, lon) VALUES (?, ?, ?)",
                (name, depot.lat, depot.lon),
            )
    except sqlite3.IntegrityError as exc:
        raise ConflictError(f"Ya hay una sede llamada '{name}'.") from exc
    return _get_depot(conn, int(cursor.lastrowid or 0))


def update_depot(conn: sqlite3.Connection, depot_id: int, depot: DepotIn) -> Depot:
    _get_depot(conn, depot_id)
    name = _depot_name(depot)
    try:
        with conn:
            conn.execute(
                "UPDATE sedes SET nombre = ?, lat = ?, lon = ? WHERE id = ?",
                (name, depot.lat, depot.lon, depot_id),
            )
    except sqlite3.IntegrityError as exc:
        raise ConflictError(f"Ya hay una sede llamada '{name}'.") from exc
    return _get_depot(conn, depot_id)


def delete_depot(conn: sqlite3.Connection, depot_id: int) -> None:
    with conn:
        cursor = conn.execute("DELETE FROM sedes WHERE id = ?", (depot_id,))
    if cursor.rowcount == 0:
        raise NotFoundError("La sede no existe.")


# --------------------------------------------------------------------------
# Resumen para el Inicio
# --------------------------------------------------------------------------


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _localities(cameras: list[CatalogCamera]) -> list[LocalitySummary]:
    groups: dict[str, list[CatalogCamera]] = defaultdict(list)
    for camera in cameras:
        groups[camera.locality].append(camera)
    summaries = [
        LocalitySummary(
            name=name,
            cameras=len(members),
            visited=sum(1 for camera in members if camera.visits),
            pending=sum(
                1 for camera in members if camera.last_status in ("pendiente", "no_realizada")
            ),
            last_visit=max(
                (camera.last_visit for camera in members if camera.last_visit), default=None
            ),
        )
        for name, members in groups.items()
    ]
    return sorted(summaries, key=lambda item: (-item.cameras, item.name))


def _visit_age(cameras: list[CatalogCamera], today: dt.date) -> VisitAge:
    never = within_30 = within_90 = older = 0
    for camera in cameras:
        if camera.last_visit is None:
            never += 1
            continue
        days = (today - camera.last_visit).days
        if days <= 30:
            within_30 += 1
        elif days <= 90:
            within_90 += 1
        else:
            older += 1
    return VisitAge(never=never, within_30=within_30, within_90=within_90, older=older)


def _months(conn: sqlite3.Connection, today: dt.date) -> list[MonthTasks]:
    first = _shift_month(today.year, today.month, -(MONTHS_BACK - 1))
    last_allowed = _shift_month(today.year, today.month, MONTHS_AHEAD)
    rows = conn.execute(
        """
        SELECT substr(fecha, 1, 7) AS month,
               SUM(estado_actual = 'realizada') AS done,
               SUM(estado_actual = 'pendiente') AS pending,
               SUM(estado_actual = 'no_realizada') AS not_done,
               SUM(estado_actual = 'reprogramada') AS rescheduled
        FROM v_paradas
        WHERE fecha >= ? AND fecha < ?
        GROUP BY month
        """,
        (
            f"{first[0]:04d}-{first[1]:02d}-01",
            "{:04d}-{:02d}-01".format(*_shift_month(*last_allowed, 1)),
        ),
    ).fetchall()
    by_month = {row["month"]: dict(row) for row in rows}
    # Hacia adelante, sólo hasta el último mes que ya tiene jornadas.
    last = (today.year, today.month)
    for month in by_month:
        year, number = int(month[:4]), int(month[5:7])
        last = max(last, (year, number))

    months: list[MonthTasks] = []
    current = first
    while current <= last:
        key = f"{current[0]:04d}-{current[1]:02d}"
        row = by_month.get(key, {})
        months.append(
            MonthTasks(
                month=key,
                done=row.get("done") or 0,
                pending=row.get("pending") or 0,
                not_done=row.get("not_done") or 0,
                rescheduled=row.get("rescheduled") or 0,
            )
        )
        current = _shift_month(*current, 1)
    return months


def _depot_reach(
    cameras: list[CatalogCamera], depots: list[Depot], max_km: float
) -> tuple[list[DepotReach], int]:
    """Para cada sede, las cámaras de su zona: las que la tienen como la más
    cercana, a `max_km` o menos. Devuelve también cuántas quedan sin sede."""
    if not depots:
        return [], 0
    assigned: dict[int, list[float]] = {depot.id: [] for depot in depots}
    outside = 0
    if cameras:
        points = pd.DataFrame({"lat": [c.lat for c in cameras], "lon": [c.lon for c in cameras]})
        nearest, distance = nearest_depot(points, [(depot.lat, depot.lon) for depot in depots])
        for depot_index, km in zip(nearest, distance, strict=True):
            if km > max_km:
                outside += 1
            else:
                assigned[depots[int(depot_index)].id].append(float(km))
    reach = [
        DepotReach(
            id=depot.id,
            name=depot.name,
            cameras=len(assigned[depot.id]),
            average_km=round(sum(assigned[depot.id]) / len(assigned[depot.id]), 1)
            if assigned[depot.id]
            else None,
            max_km=round(max(assigned[depot.id]), 1) if assigned[depot.id] else None,
        )
        for depot in depots
    ]
    return reach, outside


def summary(
    conn: sqlite3.Connection,
    today: dt.date | None = None,
    depot_max_km: float = DEPOT_MAX_KM,
) -> CatalogSummary:
    today = today or dt.date.today()
    cameras = list_cameras(conn)
    reach, outside_depots = _depot_reach(cameras, list_depots(conn), depot_max_km)
    localities = _localities(cameras)
    plans = conn.execute(
        """
        SELECT (SELECT COUNT(*) FROM planes) AS plan_count,
               (SELECT COUNT(*) FROM recorridos) AS route_count,
               (SELECT COALESCE(SUM(distancia_m), 0) FROM recorridos) AS distance_m
        """
    ).fetchone()
    tasks = conn.execute(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(estado_actual = 'realizada'), 0) AS done,
               COALESCE(SUM(estado_actual = 'pendiente'), 0) AS pending,
               COALESCE(SUM(estado_actual = 'no_realizada'), 0) AS not_done,
               COALESCE(SUM(estado_actual = 'reprogramada'), 0) AS rescheduled
        FROM v_paradas
        """
    ).fetchone()
    outside = conn.execute(
        """
        SELECT COUNT(DISTINCT camara_id) FROM paradas
        WHERE camara_id NOT IN (SELECT id FROM camaras)
        """
    ).fetchone()[0]
    last_import = conn.execute("SELECT MAX(cargado_en) FROM cargas_catalogo").fetchone()[0]
    return CatalogSummary(
        today=today,
        camera_count=len(cameras),
        locality_count=sum(
            1 for item in localities if item.name != localidades.SIN_CALCULAR
        ),
        municipalities_loaded=localidades.cargar() is not None,
        localities=localities,
        visit_age=_visit_age(cameras, today),
        plan_count=plans["plan_count"],
        route_count=plans["route_count"],
        distance_m=plans["distance_m"],
        tasks=TaskCounts(**dict(tasks)),
        months=_months(conn, today),
        depots=reach,
        depot_max_km=depot_max_km,
        outside_depots=outside_depots,
        planned_outside_catalog=outside,
        last_import_at=last_import,
    )
