"""Limitación de tasa en memoria, por IP de origen.

Pensado para un único proceso backend: ver la justificación junto a la
implementación. La autenticación vive en `app/auth/`.
"""

import time
from collections import OrderedDict
from threading import Lock
from typing import Callable

from fastapi import HTTPException, Request

from . import config
from .red import client_ip

# Tope de IPs distintas rastreadas por limitador. Sin esto, un proceso
# expuesto a la red acumula una entrada por cada IP de origen que le llegue,
# sin límite, mientras siga corriendo.
MAX_TRACKED_KEYS = 10_000


class SlidingWindowLimiter:
    """Limitador por clave (típicamente la IP de origen), ventana deslizante."""

    def __init__(self, max_requests: int, window_s: float) -> None:
        self.max_requests = max_requests
        self.window_s = window_s
        # OrderedDict como LRU: cada acceso mueve la clave al final, así el
        # tope de tamaño descarta primero a las IPs menos recientes.
        self._hits: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = Lock()

    def check(self, key: str) -> None:
        """Registra una solicitud y levanta 429 si supera el tope de la ventana."""
        now = time.monotonic()
        cutoff = now - self.window_s
        with self._lock:
            hits = self._hits.setdefault(key, [])
            self._hits.move_to_end(key)
            while hits and hits[0] < cutoff:
                hits.pop(0)
            if len(hits) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail="Demasiadas solicitudes. Espere antes de reintentar.",
                )
            hits.append(now)

            while len(self._hits) > MAX_TRACKED_KEYS:
                self._hits.popitem(last=False)


def rate_limiter(max_requests: int, window_s: float | None = None) -> Callable:
    """Fábrica de dependencias de FastAPI: una instancia de limitador por endpoint.

    Se llama una sola vez por endpoint al armar las rutas, para que el estado
    (los hits por IP) se comparta entre requests en vez de reiniciarse en cada
    una.
    """
    limiter = SlidingWindowLimiter(
        max_requests, window_s if window_s is not None else config.RATE_LIMIT_WINDOW_S
    )

    async def _dependency(request: Request) -> None:
        limiter.check(client_ip(request))

    return _dependency
