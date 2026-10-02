"""Conexión a la base de seguridad (AUTH_DB_PATH).

A diferencia del registro, acá las transacciones son explícitas
(`isolation_level=None` + `transaccion()`): la auditoría encadena cada fila con
la anterior, y leer el último hash e insertar tiene que pasar bajo el mismo
lock de escritura. `BEGIN IMMEDIATE` lo toma al empezar, así dos procesos no
pueden bifurcar la cadena.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Iterator

from .. import config

SCHEMA_VERSION = 1
_SCHEMA_FILE = Path(__file__).with_name("esquema.sql")
_initialized: set[str] = set()
_init_lock = Lock()


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or config.AUTH_DB_PATH
    if not Path(path).exists():
        _initialized.discard(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with _init_lock:
        if path not in _initialized:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA_FILE.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            _initialized.add(path)
    return conn


@contextmanager
def transaccion(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transacción con el lock de escritura tomado desde el principio."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def get_auth_db() -> Iterator[sqlite3.Connection]:
    """Dependencia de FastAPI: una conexión por pedido."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
