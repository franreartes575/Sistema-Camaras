"""IP real del cliente detrás de proxies y balanceadores.

`X-Forwarded-For` lo puede escribir cualquiera: un cliente directo manda el
valor que quiera. Por eso sólo se lo cree cuando la conexión viene de un proxy
de `TRUSTED_PROXIES`, y aun así se lo recorre de derecha a izquierda: cada
proxy agrega al final la IP de quien le habló, así que la primera dirección
—desde la derecha— que no es un proxy de confianza es la del cliente. Tomar la
primera desde la izquierda, que es lo habitual, deja que el cliente elija con
qué IP queda en la auditoría.
"""

import ipaddress
from functools import lru_cache
from typing import NamedTuple

from fastapi import Request

from . import config

# Un header más largo que esto no viene de una cadena de proxies razonable.
MAX_FORWARDED_LENGTH = 1024


class ClientAddress(NamedTuple):
    """De dónde viene un pedido, como se registra en la auditoría."""

    ip: str  # la del cliente, resuelta
    peer: str  # la de la conexión TCP (el último proxy, o el cliente)
    forwarded_for: str | None  # el header tal como llegó, para peritaje


@lru_cache(maxsize=8)
def _networks(spec: tuple[str, ...]) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(item, strict=False) for item in spec)


def _parse(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    text = value.strip()
    # Algunos proxies agregan el puerto ("1.2.3.4:5678", "[::1]:80").
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]
    elif text.count(":") == 1:
        text = text.split(":")[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    # ::ffff:1.2.3.4 es la misma IPv4: se registra como tal.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(address in network for network in _networks(tuple(config.TRUSTED_PROXIES)))


def resolve_client(peer: str | None, forwarded_for: str | None) -> ClientAddress:
    """Resuelve la IP del cliente a partir del par TCP y `X-Forwarded-For`."""
    peer_text = peer or "desconocida"
    raw = forwarded_for[:MAX_FORWARDED_LENGTH] if forwarded_for else None
    peer_address = _parse(peer_text)

    if peer_address is None or not _trusted(peer_address) or not raw:
        return ClientAddress(str(peer_address or peer_text), peer_text, raw)

    client = peer_address
    for hop in reversed(raw.split(",")):
        address = _parse(hop)
        if address is None:
            # Un valor ilegible corta la cadena: lo que esté a su izquierda ya
            # no es confiable. Queda la última dirección válida.
            break
        client = address
        if not _trusted(address):
            break
    return ClientAddress(str(client), peer_text, raw)


def client_address(request: Request) -> ClientAddress:
    return resolve_client(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
    )


def client_ip(request: Request) -> str:
    """Sólo la IP del cliente (para el rate limiting)."""
    return client_address(request).ip


def is_https(request: Request) -> bool:
    """Si el cliente llegó por HTTPS (directo o según el proxy de confianza)."""
    if request.url.scheme == "https":
        return True
    peer = _parse(request.client.host) if request.client else None
    proto = request.headers.get("x-forwarded-proto", "")
    return peer is not None and _trusted(peer) and proto.split(",")[0].strip().lower() == "https"
