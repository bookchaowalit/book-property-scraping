"""Test-wide guard: the suite must never touch the network.

Every test replays fixtures or mocks the HTTP layer. Any real socket
connection fails loudly instead of silently hitting a live site.
"""

import socket

import pytest


class NetworkAccessBlocked(RuntimeError):
    pass


def _blocked(*_args, **_kwargs):
    raise NetworkAccessBlocked("network access is disabled in tests; use fixtures or mocks")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield
