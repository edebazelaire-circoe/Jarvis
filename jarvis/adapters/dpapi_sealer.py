"""Scellement local des secrets de plugins MCP (generic-mcp-plugin-runtime, Slice 02 ; ARCH §3.3).

- `DpapiSealer` : Windows DPAPI **CurrentUser** (`CryptProtectData` /
  `CryptUnprotectData` de `crypt32`, par `ctypes`), `CRYPTPROTECT_UI_FORBIDDEN`,
  entropie `jarvis-mcp-v1`. Un blob copié sur une autre session Windows ou
  altéré est refusé (`SealerError`).
- `UnavailableSealer` : hors Windows. `available` faux ⇒ le coffre refuse tout
  secret (`mcp_vault_unavailable`), **aucun repli en clair**.

Modèle de menace (`docs/mcp/plugins.md` §3.2) : DPAPI CurrentUser protège
contre les autres utilisateurs et les copies de la base, pas contre un
processus malveillant du même utilisateur.
"""

from __future__ import annotations

import ctypes
import sys

from jarvis.ports.mcp_plugins import SealerError

#: Valeur de `mcp_credentials.scheme` (CHECK de la migration v4).
DPAPI_SCHEME = "dpapi-user-v1"
DPAPI_ENTROPY = b"jarvis-mcp-v1"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


class DpapiSealer:
    """`Sealer` Windows (DPAPI CurrentUser)."""

    scheme = DPAPI_SCHEME

    def __init__(self) -> None:
        self._crypt32 = None
        self._kernel32 = None
        self._load_error: str | None = None
        if sys.platform != "win32":
            self._load_error = "DPAPI exists only on Windows"
            return
        try:
            self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except OSError as exc:
            self._load_error = f"crypt32 unavailable: {exc}"

    @property
    def available(self) -> bool:
        return self._crypt32 is not None

    @property
    def unavailable_reason(self) -> str | None:
        return self._load_error

    def _call(self, name: str, data: bytes) -> bytes:
        if self._crypt32 is None or self._kernel32 is None:
            raise SealerError(self._load_error or "DPAPI unavailable")
        source, _keep = _blob(data)
        entropy, _keep_entropy = _blob(DPAPI_ENTROPY)
        out = _DataBlob()
        # Same argument layout for both calls: (in, description, entropy,
        # reserved, prompt, flags, out); the description is neither set nor read.
        ok = getattr(self._crypt32, name)(ctypes.byref(source), None, ctypes.byref(entropy), None, None,
                                          CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
        if not ok:
            error = ctypes.get_last_error()
            raise SealerError(f"{name} failed: {ctypes.FormatError(error).strip()} (winerror {error})")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            self._kernel32.LocalFree(out.pbData)

    def seal(self, plaintext: bytes) -> bytes:
        return self._call("CryptProtectData", plaintext)

    def unseal(self, blob: bytes) -> bytes:
        return self._call("CryptUnprotectData", blob)


class UnavailableSealer:
    """`Sealer` des plateformes sans coffre : refuse tout, ne scelle jamais en clair."""

    scheme = "unavailable"
    available = False

    def __init__(self, reason: str = "no local secret sealer on this platform") -> None:
        self.unavailable_reason = reason

    def seal(self, plaintext: bytes) -> bytes:
        raise SealerError(self.unavailable_reason)

    def unseal(self, blob: bytes) -> bytes:
        raise SealerError(self.unavailable_reason)


def default_sealer() -> DpapiSealer | UnavailableSealer:
    """DPAPI sous Windows, sinon `UnavailableSealer` (injecté par `app.py:_run_core_v2`)."""

    if sys.platform == "win32":
        sealer = DpapiSealer()
        if sealer.available:
            return sealer
        return UnavailableSealer(sealer.unavailable_reason or "DPAPI unavailable")
    return UnavailableSealer()
