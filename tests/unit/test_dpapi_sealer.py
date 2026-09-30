"""`DpapiSealer` réel (Windows) et `UnavailableSealer` (Slice 02 ; ARCH §3.3)."""

from __future__ import annotations

import sys

import pytest

from jarvis.adapters.dpapi_sealer import DPAPI_SCHEME, DpapiSealer, UnavailableSealer, default_sealer
from jarvis.ports.mcp_plugins import SealerError

SENTINEL = b"SENTINEL-SECRET-7f3a"

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI exists only on Windows")


@windows_only
def test_real_dpapi_round_trip():
    sealer = DpapiSealer()
    assert sealer.available and sealer.scheme == DPAPI_SCHEME
    blob = sealer.seal(SENTINEL)
    assert blob != SENTINEL and SENTINEL not in blob
    assert sealer.unseal(blob) == SENTINEL
    assert sealer.seal(SENTINEL) != blob  # salted: two seals differ


@windows_only
def test_real_dpapi_refuses_a_tampered_blob():
    sealer = DpapiSealer()
    blob = bytearray(sealer.seal(SENTINEL))
    blob[len(blob) // 2] ^= 0xFF
    with pytest.raises(SealerError, match="CryptUnprotectData failed"):
        sealer.unseal(bytes(blob))


@windows_only
def test_real_dpapi_refuses_garbage_and_empty():
    sealer = DpapiSealer()
    with pytest.raises(SealerError):
        sealer.unseal(b"not a dpapi blob")
    assert sealer.unseal(sealer.seal(b"")) == b""


@windows_only
def test_default_sealer_is_dpapi_on_windows():
    assert isinstance(default_sealer(), DpapiSealer)


def test_unavailable_sealer_refuses_everything():
    sealer = UnavailableSealer()
    assert sealer.available is False
    with pytest.raises(SealerError):
        sealer.seal(SENTINEL)
    with pytest.raises(SealerError):
        sealer.unseal(b"x")


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows fallback")
def test_default_sealer_is_unavailable_elsewhere():
    assert isinstance(default_sealer(), UnavailableSealer)
