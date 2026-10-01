"""Registro de recorridos: guardar planes, consultar el avance y cargar seguimientos.

Todas las funciones reciben una conexión abierta (ver `database.get_db`) y
devuelven modelos listos para responder. Las lecturas van contra las vistas de
`esquema.sql`, que ya traen el estado efectivo de cada tarea (incluida la
"reprogramada", que no se guarda sino que se deriva).

Las columnas de la base están en castellano —es lo que lee quien la abre con
un cliente SQL— y la API conserva los nombres en inglés del resto del backend:
la traducción vive acá, en los alias de cada SELECT.
"""

import datetime as dt
import hashlib
import json
import sqlite3
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..schemas import (
    FollowUpImport,
    FollowUpResult,
    PlanSummary,
    PlanUpdate,
    RegistryPlanIn,
    RegistryRouteIn,
    RouteDetail,
    RouteSummary,
    Task,
    TaskUpdate,
)
from .export import read_plan_id
from .ingest import follow_up_mapping, read_dataframe, reported_status

# Tope de filas por consulta: varios meses de operación entran holgados, y un
# filtro mal puesto no arma una respuesta de cientos de MB.
MAX_ROWS = 5000
# Cuántos ids sin coincidencia se devuelven para mostrar en el aviso.
MAX_UNMATCHED_IDS = 20
# SQLite admite miles de parámetros, pero no conviene acercarse al límite.
_IN_CHUNK = 500


class NotFoundError(LookupError):
    """El plan, recorrido o tarea pedido no existe."""


class ConflictError(Exception):
    """El cambio pisaría información ya cargada por los técnicos."""


@dataclass(frozen=True)
class Filters:
    """Filtros comunes a recorridos y tareas. None = sin filtrar."""

    date_from: dt.date | None = None
    date_to: dt.date | None = None
    plan_id: int | None = None
    query: str | None = None


_PLAN_COLUMNS = """
    id, nombre AS name, creado_en AS created_at, archivo_origen AS source_file,
    motor AS provider, por_calle AS is_road_network, notas AS notes,
    recorridos AS route_count, fecha_desde AS date_from, fecha_hasta AS date_to,
    distancia_m AS distance_m, duracion_s AS duration_s,
    total, realizadas AS done, pendientes AS pending,
    no_realizadas AS not_done, reprogramadas AS rescheduled
"""

_ROUTE_COLUMNS = """
    v.id, v.plan_id, v.plan_nombre AS plan_name, v.fecha AS date,
    v.cluster_id, v.dia AS day, v.salida_nombre AS start_name,
    v.salida_lat AS start_lat, v.salida_lon AS start_lon,
    v.distancia_m AS distance_m, v.duracion_s AS duration_s,
    v.tramos_sin_conexion AS has_unreachable_legs,
    v.total, v.realizadas AS done, v.pendientes AS pending,
    v.no_realizadas AS not_done, v.reprogramadas AS rescheduled
"""

_TASK_COLUMNS = """
    v.id, v.recorrido_id AS route_id, v.plan_id, v.plan_nombre AS plan_name,
    v.fecha AS date, v.cluster_id, v.dia AS day, v.orden AS "order",
    v.camara_id AS camera_id, v.lat, v.lon, v.descripcion AS label,
    v.nodo_preliminar AS node, v.nodo_migrado AS migrated_node,
    v.observacion AS observation, v.estado_actual AS status,
    v.verificado_en AS verified_at
"""


def _now() -> str:
    return dt.datetime.now().isoformat(sep=" ", timespec="seconds")


def _like(text: str) -> str:
    """Patrón LIKE de "contiene", con los comodines del usuario escapados."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _clean(text: str | None) -> str | None:
    """Texto sin espacios de más; vacío = None."""
    return (text or "").strip() or None


def _contains(*columns: str) -> str:
    """Condición "alguna de estas columnas contiene el texto buscado"."""
    return " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in columns)


# Buscar en recorridos mira la salida, el plan y las cámaras de la jornada:
# escribir el ID de una cámara encuentra el día en que se visita.
_ROUTE_SEARCH = (
    _contains("v.salida_nombre", "v.plan_nombre")
    + " OR EXISTS (SELECT 1 FROM paradas x WHERE x.recorrido_id = v.id AND ("
    + _contains(
        "x.camara_id", "x.nodo_preliminar", "x.nodo_migrado", "x.descripcion", "x.observacion"
    )
    + "))"
)
_TASK_SEARCH = _contains(
    "v.camara_id", "v.nodo_preliminar", "v.nodo_migrado",
    "v.descripcion", "v.observacion", "v.plan_nombre",
)


def _where(
    filters: Filters, search_sql: str, extra: tuple[str, list] | None = None
) -> tuple[str, list]:
    """WHERE con los filtros de fecha y plan, la búsqueda de texto y `extra`.

    Todos los `?` de `search_sql` se ligan al mismo patrón de búsqueda.
    """
    conditions: list[str] = []
    params: list = []
    if filters.date_from:
        conditions.append("v.fecha >= ?")
        params.append(filters.date_from.isoformat())
    if filters.date_to:
        conditions.append("v.fecha <= ?")
        params.append(filters.date_to.isoformat())
    if filters.plan_id is not None:
        conditions.append("v.plan_id = ?")
        params.append(filters.plan_id)
    query = _clean(filters.query)
    if query:
        conditions.append(f"({search_sql})")
        params.extend([_like(query)] * search_sql.count("?"))
    if extra:
        conditions.append(extra[0])
        params.extend(extra[1])
    return (" WHERE " + " AND ".join(conditions)) if conditions else "", params


# --------------------------------------------------------------------------
# Planes
# --------------------------------------------------------------------------


def _range_name(first: dt.date, last: dt.date) -> str:
    """Nombre automático de un plan según las fechas que abarca."""
    if first == last:
        return f"Plan del {first:%d/%m/%Y}"
    return f"Plan del {first:%d/%m} al {last:%d/%m/%Y}"


def _default_name(plan: RegistryPlanIn) -> str:
    dates = [route.date for route in plan.routes]
    return _range_name(min(dates), max(dates))


def _insert_routes(conn: sqlite3.Connection, plan_id: int, routes: list[RegistryRouteIn]) -> None:
    for route in routes:
        try:
            cursor = conn.execute(
                """
                INSERT INTO recorridos (
                    plan_id, fecha, cluster_id, dia, salida_nombre, salida_lat,
                    salida_lon, distancia_m, duracion_s, tramos_sin_conexion, geometria
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id, route.date.isoformat(), route.cluster_id, route.day,
                    _clean(route.start_name), route.start_lat, route.start_lon,
                    route.distance_m, route.duration_s, int(route.has_unreachable_legs),
                    json.dumps([[lat, lon] for lat, lon in route.geometry]),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"El plan repite la jornada {route.day} del cluster {route.cluster_id}."
            ) from exc
        conn.executemany(
            """
            INSERT INTO paradas (
                recorrido_id, orden, camara_id, lat, lon, descripcion,
                nodo_preliminar, observacion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    cursor.lastrowid, order, stop.camera_id.strip(), stop.lat, stop.lon,
                    _clean(stop.label), _clean(stop.node), _clean(stop.observation),
                )
                for order, stop in enumerate(route.stops, start=1)
            ],
        )


def get_plan(conn: sqlite3.Connection, plan_id: int) -> PlanSummary:
    row = conn.execute(f"SELECT {_PLAN_COLUMNS} FROM v_planes WHERE id = ?", (plan_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"No existe el plan {plan_id} en el registro.")
    return PlanSummary(**dict(row))


def list_plans(conn: sqlite3.Connection) -> list[PlanSummary]:
    rows = conn.execute(f"SELECT {_PLAN_COLUMNS} FROM v_planes ORDER BY id DESC").fetchall()
    return [PlanSummary(**dict(row)) for row in rows]


def create_plan(conn: sqlite3.Connection, plan: RegistryPlanIn) -> PlanSummary:
    """Guarda un plan nuevo con todas sus jornadas y paradas."""
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO planes (nombre, creado_en, archivo_origen, motor, por_calle)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                _clean(plan.name) or _default_name(plan), _now(),
                _clean(plan.source_file), _clean(plan.provider), int(plan.is_road_network),
            ),
        )
        plan_id = int(cursor.lastrowid or 0)
        _insert_routes(conn, plan_id, plan.routes)
    return get_plan(conn, plan_id)


def replace_plan(conn: sqlite3.Connection, plan_id: int, plan: RegistryPlanIn) -> PlanSummary:
    """Reemplaza las jornadas de un plan que todavía no tiene seguimiento.

    Es lo que pasa al volver a exportar el mismo plan con otras fechas: no
    tiene sentido duplicarlo. Si los técnicos ya informaron algo, reemplazarlo
    borraría lo informado, así que se rechaza.
    """
    with conn:
        reported = conn.execute(
            """
            SELECT COUNT(*) FROM paradas pa
            JOIN recorridos r ON r.id = pa.recorrido_id
            WHERE r.plan_id = ? AND (pa.estado <> 'pendiente' OR pa.verificado_en IS NOT NULL)
            """,
            (plan_id,),
        ).fetchone()[0]
        if reported:
            raise ConflictError(
                f"El plan {plan_id} ya tiene {reported} tarea(s) informadas por los "
                f"técnicos: guardalo como un plan nuevo para no perder lo cargado."
            )
        # Si el nombre es el automático de las fechas viejas (nadie lo
        # renombró), sigue a las fechas nuevas; uno puesto a mano se respeta.
        current = get_plan(conn, plan_id)
        auto_named = (
            current.date_from is not None
            and current.date_to is not None
            and current.name == _range_name(current.date_from, current.date_to)
        )
        name = _clean(plan.name) or (_default_name(plan) if auto_named else None)
        conn.execute("DELETE FROM recorridos WHERE plan_id = ?", (plan_id,))
        conn.execute(
            """
            UPDATE planes
            SET nombre = COALESCE(?, nombre), archivo_origen = ?, motor = ?, por_calle = ?
            WHERE id = ?
            """,
            (name, _clean(plan.source_file), _clean(plan.provider), int(plan.is_road_network), plan_id),
        )
        _insert_routes(conn, plan_id, plan.routes)
    return get_plan(conn, plan_id)


def update_plan(conn: sqlite3.Connection, plan_id: int, changes: PlanUpdate) -> PlanSummary:
    with conn:
        get_plan(conn, plan_id)
        if "name" in changes.model_fields_set and _clean(changes.name):
            conn.execute("UPDATE planes SET nombre = ? WHERE id = ?", (_clean(changes.name), plan_id))
        if "notes" in changes.model_fields_set:
            conn.execute("UPDATE planes SET notas = ? WHERE id = ?", (_clean(changes.notes), plan_id))
    return get_plan(conn, plan_id)


def delete_plan(conn: sqlite3.Connection, plan_id: int) -> None:
    with conn:
        if conn.execute("DELETE FROM planes WHERE id = ?", (plan_id,)).rowcount == 0:
            raise NotFoundError(f"No existe el plan {plan_id} en el registro.")


# --------------------------------------------------------------------------
# Recorridos y tareas
# --------------------------------------------------------------------------


def list_routes(conn: sqlite3.Connection, filters: Filters) -> list[RouteSummary]:
    """Jornadas con su avance, de la más reciente a la más vieja."""
    where, params = _where(filters, _ROUTE_SEARCH)
    rows = conn.execute(
        f"""
        SELECT {_ROUTE_COLUMNS} FROM v_recorridos v {where}
        ORDER BY v.fecha DESC, v.plan_id DESC, v.cluster_id, v.dia
        LIMIT {MAX_ROWS}
        """,
        params,
    ).fetchall()
    return [RouteSummary(**dict(row)) for row in rows]


def list_tasks(
    conn: sqlite3.Connection, filters: Filters, statuses: list[str] | None = None
) -> list[Task]:
    """Tareas (paradas) en orden de fecha y visita, opcionalmente por estado."""
    extra = None
    if statuses:
        extra = (f"v.estado_actual IN ({', '.join('?' for _ in statuses)})", list(statuses))
    where, params = _where(filters, _TASK_SEARCH, extra)
    rows = conn.execute(
        f"""
        SELECT {_TASK_COLUMNS} FROM v_paradas v {where}
        ORDER BY v.fecha DESC, v.plan_id DESC, v.cluster_id, v.dia, v.orden
        LIMIT {MAX_ROWS}
        """,
        params,
    ).fetchall()
    return [Task(**dict(row)) for row in rows]


def route_details(conn: sqlite3.Connection, route_ids: list[int]) -> list[RouteDetail]:
    """Jornadas completas (paradas + polilínea), en el orden pedido."""
    unique = list(dict.fromkeys(route_ids))
    if not unique:
        return []
    marks = ", ".join("?" for _ in unique)
    summaries = {
        row["id"]: dict(row)
        for row in conn.execute(
            f"SELECT {_ROUTE_COLUMNS} FROM v_recorridos v WHERE v.id IN ({marks})", unique
        )
    }
    geometries = {
        row["id"]: json.loads(row["geometria"])
        for row in conn.execute(f"SELECT id, geometria FROM recorridos WHERE id IN ({marks})", unique)
    }
    stops: dict[int, list[Task]] = {route_id: [] for route_id in unique}
    for row in conn.execute(
        f"SELECT {_TASK_COLUMNS} FROM v_paradas v WHERE v.recorrido_id IN ({marks}) ORDER BY v.orden",
        unique,
    ):
        stops[row["route_id"]].append(Task(**dict(row)))
    return [
        RouteDetail(**summaries[route_id], geometry=geometries[route_id], stops=stops[route_id])
        for route_id in unique
        if route_id in summaries
    ]


def get_task(conn: sqlite3.Connection, task_id: int) -> Task:
    row = conn.execute(f"SELECT {_TASK_COLUMNS} FROM v_paradas v WHERE v.id = ?", (task_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"No existe la tarea {task_id} en el registro.")
    return Task(**dict(row))


def update_task(conn: sqlite3.Connection, task_id: int, changes: TaskUpdate) -> Task:
    """Corrección manual: estado, observación o nodo migrado de una tarea."""
    fields = changes.model_fields_set
    assignments: list[str] = []
    params: list = []
    if "status" in fields and changes.status is not None:
        assignments.append("estado = ?")
        params.append(changes.status)
    if "observation" in fields:
        assignments.append("observacion = ?")
        params.append(_clean(changes.observation))
    if "migrated_node" in fields:
        assignments.append("nodo_migrado = ?")
        params.append(_clean(changes.migrated_node))
    with conn:
        get_task(conn, task_id)
        if assignments:
            conn.execute(
                f"UPDATE paradas SET {', '.join(assignments)}, verificado_en = ? WHERE id = ?",
                params + [_now(), task_id],
            )
    return get_task(conn, task_id)


# --------------------------------------------------------------------------
# Carga de seguimientos
# --------------------------------------------------------------------------


@dataclass
class _Candidate:
    """Una tarea guardada que podría corresponder a una fila del seguimiento."""

    id: int
    plan_id: int
    date: dt.date
    status: str
    observation: str | None
    migrated_node: str | None


@dataclass(frozen=True)
class _FollowUpRow:
    camera_id: str
    date: dt.date | None
    status: str | None
    observation: str | None
    migrated_node: str | None


def _cell_text(value: object) -> str | None:
    """Texto de una celda; los números enteros sin el ".0" que agrega pandas."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip() or None


def _cell_date(value: object) -> dt.date | None:
    """Fecha de una celda: fecha de Excel, ISO o dd/mm/aaaa."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
        return None if pd.isna(parsed) else parsed.date()


def _read_follow_up(filename: str, raw: bytes) -> list[_FollowUpRow]:
    try:
        frame = read_dataframe(filename, raw)
    except Exception as exc:  # pandas/openpyxl levantan tipos muy variados
        raise ValueError(
            "No se pudo leer el archivo. Verifique que sea el Excel de seguimiento "
            "(.xlsx) o un CSV válido."
        ) from exc

    columns = follow_up_mapping([str(column) for column in frame.columns])
    if not columns["id"] or not columns["done"]:
        raise ValueError(
            "No parece un Excel de seguimiento: hacen falta la columna con el ID "
            "de la cámara y la columna Realizado."
        )
    frame.columns = [str(column) for column in frame.columns]

    def get(record: dict, role: str) -> object:
        column = columns[role]
        return record[column] if column else None

    rows: list[_FollowUpRow] = []
    for record in frame.to_dict("records"):
        camera_id = _cell_text(get(record, "id"))
        if not camera_id:
            continue
        rows.append(
            _FollowUpRow(
                camera_id=camera_id,
                date=_cell_date(get(record, "date")),
                status=reported_status(get(record, "done")),
                observation=_cell_text(get(record, "observation")),
                migrated_node=_cell_text(get(record, "migrated_node")),
            )
        )
    return rows


def _load_candidates(
    conn: sqlite3.Connection, camera_ids: set[str], plan_id: int | None
) -> dict[str, list[_Candidate]]:
    by_camera: dict[str, list[_Candidate]] = {}
    ids = sorted(camera_ids)
    for start in range(0, len(ids), _IN_CHUNK):
        chunk = ids[start:start + _IN_CHUNK]
        sql = f"""
            SELECT pa.id, pa.camara_id, pa.estado, pa.observacion, pa.nodo_migrado,
                   r.plan_id, r.fecha
            FROM paradas pa JOIN recorridos r ON r.id = pa.recorrido_id
            WHERE pa.camara_id IN ({', '.join('?' for _ in chunk)})
        """
        params: list = list(chunk)
        if plan_id is not None:
            sql += " AND r.plan_id = ?"
            params.append(plan_id)
        for row in conn.execute(sql, params):
            by_camera.setdefault(row["camara_id"], []).append(
                _Candidate(
                    id=row["id"], plan_id=row["plan_id"],
                    date=dt.date.fromisoformat(row["fecha"]), status=row["estado"],
                    observation=row["observacion"], migrated_node=row["nodo_migrado"],
                )
            )
    return by_camera


def _pick_targets(candidates: list[_Candidate], date: dt.date | None) -> list[_Candidate]:
    """Tareas a actualizar para una fila: misma cámara y fecha, del plan más nuevo.

    Si la fecha no coincide con ninguna (o la fila no la trae), se toma la tarea
    más reciente de esa cámara: el técnico pudo haber corregido la fecha.
    """
    if not candidates:
        return []
    if date is not None:
        exact = [candidate for candidate in candidates if candidate.date == date]
        if exact:
            newest = max(candidate.plan_id for candidate in exact)
            return [candidate for candidate in exact if candidate.plan_id == newest]
    return [max(candidates, key=lambda candidate: (candidate.plan_id, candidate.date))]


def import_follow_up(conn: sqlite3.Connection, filename: str, raw: bytes) -> FollowUpResult:
    """Actualiza el registro con un Excel de seguimiento completado.

    Cada fila se cruza con su tarea por cámara y fecha planificada (y por plan,
    si el Excel salió del registro y trae la hoja oculta). "Sí" la marca
    realizada y "No" no realizada; una celda vacía no cambia el estado, pero la
    observación y el nodo migrado se actualizan igual si vienen cargados.
    Cargar el mismo archivo dos veces deja el registro igual.
    """
    rows = _read_follow_up(filename, raw)
    plan_hint = read_plan_id(filename, raw)
    if plan_hint is not None and conn.execute(
        "SELECT 1 FROM planes WHERE id = ?", (plan_hint,)
    ).fetchone() is None:
        plan_hint = None  # el plan se borró del registro: se cruza sin él

    candidates = _load_candidates(conn, {row.camera_id for row in rows}, plan_hint)
    digest = hashlib.sha256(raw).hexdigest()
    now = _now()

    matched = updated = done = not_done = no_news = 0
    unmatched: list[str] = []
    touched_plans: Counter[int] = Counter()
    with conn:
        previous = conn.execute(
            "SELECT cargado_en FROM cargas_seguimiento WHERE sha256 = ? ORDER BY id DESC LIMIT 1",
            (digest,),
        ).fetchone()
        for row in rows:
            targets = _pick_targets(candidates.get(row.camera_id, []), row.date)
            if not targets:
                unmatched.append(row.camera_id)
                continue
            matched += 1
            if row.status == "realizada":
                done += 1
            elif row.status == "no_realizada":
                not_done += 1
            else:
                no_news += 1
            for target in targets:
                touched_plans[target.plan_id] += 1
                status = row.status or target.status
                observation = row.observation or target.observation
                migrated = row.migrated_node or target.migrated_node
                if (status, observation, migrated) == (
                    target.status, target.observation, target.migrated_node
                ):
                    continue
                conn.execute(
                    """
                    UPDATE paradas
                    SET estado = ?, observacion = ?, nodo_migrado = ?, verificado_en = ?
                    WHERE id = ?
                    """,
                    (status, observation, migrated, now, target.id),
                )
                target.status, target.observation, target.migrated_node = (
                    status, observation, migrated,
                )
                updated += 1

        plan_id = plan_hint or (touched_plans.most_common(1)[0][0] if touched_plans else None)
        cursor = conn.execute(
            """
            INSERT INTO cargas_seguimiento (
                archivo, sha256, cargado_en, plan_id, filas, coincidencias,
                actualizadas, realizadas, no_realizadas, sin_coincidencia
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (filename, digest, now, plan_id, len(rows), matched, updated, done, not_done, len(unmatched)),
        )

    plan_name = None
    if plan_id is not None:
        plan_name = conn.execute("SELECT nombre FROM planes WHERE id = ?", (plan_id,)).fetchone()[0]
    return FollowUpResult(
        import_id=int(cursor.lastrowid or 0),
        filename=filename,
        plan_id=plan_id,
        plan_name=plan_name,
        rows=len(rows),
        matched=matched,
        updated=updated,
        done=done,
        not_done=not_done,
        no_news=no_news,
        unmatched=len(unmatched),
        unmatched_ids=list(dict.fromkeys(unmatched))[:MAX_UNMATCHED_IDS],
        previously_loaded_at=previous["cargado_en"] if previous else None,
    )


def list_imports(conn: sqlite3.Connection) -> list[FollowUpImport]:
    rows = conn.execute(
        """
        SELECT c.id, c.archivo AS filename, c.cargado_en AS loaded_at, c.plan_id,
               p.nombre AS plan_name, c.filas AS "rows", c.coincidencias AS matched,
               c.actualizadas AS updated, c.realizadas AS done,
               c.no_realizadas AS not_done, c.sin_coincidencia AS unmatched
        FROM cargas_seguimiento c LEFT JOIN planes p ON p.id = c.plan_id
        ORDER BY c.id DESC
        LIMIT 500
        """
    ).fetchall()
    return [FollowUpImport(**dict(row)) for row in rows]


def backup(conn: sqlite3.Connection) -> bytes:
    """La base completa como un archivo .sqlite autónomo.

    `VACUUM INTO` arma una copia consistente, compactada y sin modo WAL: se abre
    tal cual con cualquier cliente, sin el archivo -wal al lado. (Serializar la
    conexión copiaría la marca de WAL del encabezado.)
    """
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "respaldo.sqlite"
        conn.execute("VACUUM INTO ?", (str(target),))
        return target.read_bytes()
