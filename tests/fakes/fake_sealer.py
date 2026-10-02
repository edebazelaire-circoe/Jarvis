"""`FakeSealer` : scellement réversible et déterministe pour les tests (ARCH §3.3).

XOR avec une clé fixe + marqueur : le blob ne contient jamais le clair, et un
blob altéré (marqueur absent) est refusé comme DPAPI le ferait. Le schéma est
celui de production (`dpapi-user-v1`) parce que la colonne
`mcp_credentials.scheme` n'accepte que lui (CHECK de la migration v4).
Jamais utilisé hors des tests.
"""

from __future__ import annotations

from jarvis.ports.mcp_plugins import SealerError

MARKER = b"FAKESEAL1:"
_KEY = b"jarvis-test-sealer-key"


def _xor(data: bytes) -> bytes:
    return bytes(byte ^ _KEY[index % len(_KEY)] for index, byte in enumerate(data))


class FakeSealer:
    scheme = "dpapi-user-v1"

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.sealed = 0
        self.unsealed = 0

    def seal(self, plaintext: bytes) -> bytes:
        if not self.available:
            raise SealerError("fake sealer unavailable")
        self.sealed += 1
        return MARKER + _xor(plaintext)

    def unseal(self, blob: bytes) -> bytes:
        if not self.available:
            raise SealerError("fake sealer unavailable")
        if not blob.startswith(MARKER):
            raise SealerError("fake sealer: blob tampered")
        self.unsealed += 1
        return _xor(blob[len(MARKER):])
