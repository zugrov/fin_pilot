from types import SimpleNamespace

import pytest
from app.config import Settings
from app.security.client_ip import peer_is_trusted_proxy, resolve_client_ip


def _request(*, peer: str, xff: str | None = None) -> SimpleNamespace:
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=headers,
    )


def test_forwarded_ignored_without_trust_proxy() -> None:
    settings = Settings(trust_proxy=False)
    ip = resolve_client_ip(_request(peer="172.18.0.2", xff="203.0.113.10"), settings)
    assert ip == "172.18.0.2"


def test_forwarded_ignored_from_untrusted_peer() -> None:
    settings = Settings(trust_proxy=True)
    ip = resolve_client_ip(_request(peer="203.0.113.50", xff="203.0.113.10"), settings)
    assert ip == "203.0.113.50"


def test_forwarded_used_from_trusted_docker_peer() -> None:
    settings = Settings(trust_proxy=True)
    ip = resolve_client_ip(_request(peer="172.18.0.2", xff="198.51.100.7"), settings)
    assert ip == "198.51.100.7"


@pytest.mark.parametrize(
    ("peer", "expected"),
    [
        ("172.18.0.2", True),
        ("10.5.0.3", False),
        ("203.0.113.1", False),
        ("testclient", False),
    ],
)
def test_peer_is_trusted_proxy(peer: str, expected: bool) -> None:
    settings = Settings()
    assert peer_is_trusted_proxy(peer, settings) is expected
