import ipaddress

from fastapi import Request

from app.config import Settings

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def _parse_peer(peer: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not peer:
        return None
    try:
        return ipaddress.ip_address(peer)
    except ValueError:
        return None


def trusted_proxy_networks(settings: Settings) -> list[IpNetwork]:
    nets: list[IpNetwork] = []
    for item in settings.trusted_proxy_cidrs.split(","):
        raw = item.strip()
        if raw:
            nets.append(ipaddress.ip_network(raw, strict=False))
    return nets


def peer_is_trusted_proxy(peer: str, settings: Settings) -> bool:
    addr = _parse_peer(peer)
    if addr is None:
        return False
    return any(addr in network for network in trusted_proxy_networks(settings))


def _client_ip_from_forwarded(header: str) -> str | None:
    parts = [item.strip() for item in header.split(",") if item.strip()]
    if not parts:
        return None
    return parts[0]


def resolve_client_ip(request: Request, settings: Settings) -> str:
    peer = request.client.host if request.client else ""
    if not settings.trust_proxy or not peer_is_trusted_proxy(peer, settings):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        from_header = _client_ip_from_forwarded(forwarded)
        if from_header:
            return from_header
    return peer
