"""Shared test setup for the backend suite.

The frontend suite enforces "no test contacts a third-party service" by running MSW
with `onUnhandledRequest: 'error'`. This is the backend's equivalent: outbound network
connections are blocked outright, so the guarantee is enforced rather than asserted.

It matters more here than it looks. Per ADR 0005 nothing in the request path may call a
third party — a Pipeline Run does that on a schedule instead. If someone later adds a
convenient `requests.get` inside an endpoint, this fails immediately rather than
producing a suite that quietly depends on the network being up.
"""

import socket

import pytest

_real_socket_connect = socket.socket.connect

# Loopback is allowed: the ASGI test client and any local fixtures need it.
_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def block_outbound_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that tries to reach outside this machine."""

    def guarded_connect(self: socket.socket, address: object) -> object:
        host = address[0] if isinstance(address, tuple) else address
        if host not in _ALLOWED_HOSTS:
            raise RuntimeError(
                f"Test attempted an outbound connection to {host!r}. "
                "Backend tests must not contact third-party services."
            )
        return _real_socket_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
