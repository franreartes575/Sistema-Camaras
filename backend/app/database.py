"""Base SQLite del registro de recorridos.

El planificador (/process/, /optimize/, /export/) sigue sin estado: la base es
sólo del registro — qué se planificó cada día y qué informaron los técnicos.
SQLite viene con Python, así que no suma dependencias ni un servidor que
administrar. El esquema vive en `esquema.sql`, legible y abrible con cualquier
cliente SQL (DB Browser for SQLite, DBeaver, la CLI `sqlite3`).
"""

import sqlite3
from pathlib import Path
from threading import Lock
from typing import Iterator

from . import config

# Subirlo cuando cambie el esquema, junto con la migración que corresponda.
# 2: catálogo de cámaras, sedes e importaciones del catálogo. Son tablas
#    nuevas, así que `IF NOT EXISTS` alcanza y no hace falta migrar nada.
# 3: historial de correcciones manuales y actividad sobre los planes (tablas
#    nuevas, tampoco hace falta migrar).
# 4: `paradas.plan_id` (copia del plan de su jornada) para que "reprogramada"
#    se resuelva con un índice; ver `_migrate`.
# 5: `paradas.cuadrilla` y `paradas.fecha_informada` (lo que dice el
#    seguimiento) y `v_paradas.fuera_de_plan`.
# 6: `paradas.requiere_camion` (para los pendientes).
# 7: `paradas.pendientes_manual` y `correcciones` sin la lista fija de campos
#    (el editor corrige cualquiera): SQLite no altera un CHECK, se rehace la tabla.
SCHEMA_VERSION = 7

_CORRECTIONS_COLUMNS = (
    "id, parada_id, plan_id, camara_id, fecha, corregido_en, usuario, nombre, campo, "
    "valor_anterior, valor_nuevo"
)

# Vistas que dependen de `paradas`: el esquema las crea con IF NOT EXISTS, así
# que para cambiarlas hay que borrarlas antes (de la que depende de otra a la base).
_VIEWS = ("v_planes", "v_recorridos", "v_paradas")

_SCHEMA_FILE = Path(__file__).with_name("esquema.sql")

# Bases a las que ya se les aplicó el esquema en este proceso: evita releer y
# correr el script en cada request.
_initialized: set[str] = set()
_init_lock = Lock()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _rebuild_corrections(conn: sqlite3.Connection) -> None:
    """v7: `correcciones` sin el CHECK de campos, conservando las filas."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'correcciones'"
    ).fetchone()
    if row is None or "CHECK (campo" not in row[0]:
        return
    conn.execute("ALTER TABLE correcciones RENAME TO correcciones_v6")
    conn.execute("DROP INDEX IF EXISTS idx_correcciones_parada")
    conn.execute(
        """
        CREATE TABLE correcciones (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            parada_id      INTEGER REFERENCES paradas (id) ON DELETE SET NULL,
            plan_id        INTEGER NOT NULL,
            camara_id      TEXT    NOT NULL,
            fecha          TEXT    NOT NULL,
            corregido_en   TEXT    NOT NULL,
            usuario        TEXT    NOT NULL,
            nombre         TEXT    NOT NULL,
            campo          TEXT    NOT NULL,
            valor_anterior TEXT,
            valor_nuevo    TEXT
        )
        """
    )
    conn.execute(
        f"INSERT INTO correcciones ({_CORRECTIONS_COLUMNS}) "
        f"SELECT {_CORRECTIONS_COLUMNS} FROM correcciones_v6"
    )
    conn.execute("DROP TABLE correcciones_v6")


def _migrate(conn: sqlite3.Connection) -> None:
    """Lleva una base existente al esquema actual. Corre antes de `esquema.sql`,
    que sólo crea lo que falta y no altera tablas ni vistas que ya existen."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    with conn:
        if "paradas" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}:
            columns = _columns(conn, "paradas")
            if "plan_id" not in columns:  # v4
                conn.execute("ALTER TABLE paradas ADD COLUMN plan_id INTEGER")
                conn.execute(
                    "UPDATE paradas SET plan_id = "
                    "(SELECT r.plan_id FROM recorridos r WHERE r.id = paradas.recorrido_id)"
                )
            for column in ("cuadrilla", "fecha_informada", "requiere_camion", "pendientes_manual"):
                if column not in columns:  # v5, v6 y v7
                    conn.execute(f"ALTER TABLE paradas ADD COLUMN {column} TEXT")
        _rebuild_corrections(conn)
        for view in _VIEWS:
            conn.execute(f"DROP VIEW IF EXISTS {view}")


def _ensure_schema(conn: sqlite3.Connection, db_path: str) -> None:
    with _init_lock:
        if db_path in _initialized:
            return
        # WAL: las lecturas del registro no se bloquean mientras se carga un
        # seguimiento, y una caída a mitad de escritura no corrompe la base.
        conn.execute("PRAGMA journal_mode = WAL")
        _migrate(conn)
        conn.executescript(_SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        _initialized.add(db_path)


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """Abre la base (creándola con su esquema si no existe)."""
    path = db_path or config.DB_PATH
    if not Path(path).exists():
        # Si alguien borró el archivo con el backend andando, hay que volver a
        # crear las tablas: el caché de arriba ya no vale para esa ruta.
        _initialized.discard(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False: FastAPI puede abrir la conexión en un hilo del
    # pool y usarla en otro. Es seguro porque cada request tiene la suya y la
    # usa de a una operación por vez.
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn, path)
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    """Dependencia de FastAPI: una conexión por request, cerrada al terminar."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
