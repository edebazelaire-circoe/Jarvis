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
def test_a_blob_sealed_without_the_jarvis_entropy_is_refused():
    import ctypes

    from jarvis.adapters.dpapi_sealer import CRYPTPROTECT_UI_FORBIDDEN, _blob, _DataBlob

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    source, _keep = _blob(SENTINEL)
    out = _DataBlob()
    # Same call as DpapiSealer.seal, but with no optional entropy.
    assert crypt32.CryptProtectData(ctypes.byref(source), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN,
                                    ctypes.byref(out))
    try:
        foreign = ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)
    with pytest.raises(SealerError, match="CryptUnprotectData failed"):
        DpapiSealer().unseal(foreign)


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
