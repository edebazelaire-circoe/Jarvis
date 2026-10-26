"""Dossier Documents de l'utilisateur, par l'API des dossiers connus de Windows (`docs/export.md` › *Export root*).

`SHGetKnownFolderPath(FOLDERID_Documents)` rend le vrai dossier, déplacé ou redirigé compris (OneDrive, autre
lecteur), et jamais un nom localisé deviné (« Documents », « Mes documents »…). Aucun dossier n'est créé ici
(`KF_FLAG_DEFAULT`, lecture seule).

Hors Windows (développement, tests POSIX) : `$XDG_DOCUMENTS_DIR` absolu s'il est défini, sinon `~/Documents`.
Une erreur de l'API est rendue telle quelle (`KnownFolderError`), jamais remplacée par un repli silencieux.
"""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path


class KnownFolderError(OSError):
    """Le système n'a pas rendu le dossier Documents (code HRESULT ou cause dans le message)."""


#: {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
FOLDERID_DOCUMENTS = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"


def _windows_documents() -> Path:
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    raw = FOLDERID_DOCUMENTS.strip("{}").replace("-", "")
    data4 = bytes.fromhex(raw[16:])
    guid = GUID(int(raw[0:8], 16), int(raw[8:12], 16), int(raw[12:16], 16), (ctypes.c_ubyte * 8)(*data4))
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32")
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                                             ctypes.POINTER(ctypes.c_wchar_p)]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None
    out = ctypes.c_wchar_p()
    hresult = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out))
    try:
        if hresult != 0 or not out.value:
            raise KnownFolderError(f"SHGetKnownFolderPath(FOLDERID_Documents) failed: HRESULT 0x{hresult & 0xFFFFFFFF:08X}")
        return Path(out.value)
    finally:
        if out:
            ole32.CoTaskMemFree(ctypes.cast(out, ctypes.c_void_p))


def documents_folder(environ: Mapping[str, str] | None = None) -> Path:
    """Le dossier Documents de l'utilisateur courant (absolu). `KnownFolderError` si le système ne le donne pas."""

    if os.name == "nt":
        return _windows_documents()
    env = os.environ if environ is None else environ
    xdg = str(env.get("XDG_DOCUMENTS_DIR") or "").strip()
    if xdg and Path(xdg).is_absolute():
        return Path(xdg)
    return Path.home() / "Documents"
