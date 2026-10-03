"""Notifications du système de fichiers : « ce fichier vient de changer », sans sondage.

Windows : `ReadDirectoryChangesW` en E/S asynchrones (ctypes, aucune dépendance),
un fil bloqué par dossier surveillé, réveillé par le noyau à chaque écriture,
création, renommage ou suppression. Le rappel reçoit le chemin complet normalisé
(`normalize`) depuis la boucle asyncio. Un dossier qui n'existe pas encore est
surveillé par son plus proche ancêtre existant (sous-arbre compris).

Ce que cela couvre : toute écriture faite sur ce poste, par Core, un sous-agent,
un éditeur ou l'utilisateur, remplacement atomique (écrire puis renommer)
compris. Ce que cela ne couvre pas : un dossier réseau ou distant qui ne
transmet pas les notifications, et les systèmes autres que Windows (aucun
notificateur : `available` est faux, l'appelant le dit).
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading

from jarvis.ports.file_changes import ChangeCallback as Callback
from jarvis.ports.file_changes import normalize


class FileChangeNotifier:
    """Surveille des dossiers et appelle `callback(chemin)` dans la boucle donnée à chaque changement."""

    available = sys.platform == "win32"

    def __init__(self, loop: asyncio.AbstractEventLoop, callback: Callback) -> None:
        self._loop = loop
        self._callback = callback
        self._watches: dict[str, _DirectoryWatch] = {}
        self._lock = threading.Lock()

    def watch(self, directory: str) -> bool:
        """Surveiller `directory` (ou son plus proche ancêtre existant). Rend faux si impossible."""

        if not self.available:
            return False
        target = normalize(directory)
        subtree = False
        while not os.path.isdir(target):
            parent = os.path.dirname(target)
            if parent == target:
                return False
            target, subtree = parent, True
        with self._lock:
            existing = self._watches.get(target)
            if existing is not None and (existing.subtree or not subtree):
                return True
            watch = _DirectoryWatch(target, subtree, self._emit)
            if not watch.start():
                return False
            if existing is not None:
                existing.stop()
            self._watches[target] = watch
            return True

    def keep_only(self, directories: set[str]) -> None:
        """Cesser de surveiller tout dossier qui n'est plus demandé."""

        wanted = set()
        for directory in directories:
            target = normalize(directory)
            while not os.path.isdir(target) and os.path.dirname(target) != target:
                target = os.path.dirname(target)
            wanted.add(target)
        with self._lock:
            for key in [key for key in self._watches if key not in wanted]:
                self._watches.pop(key).stop()

    def close(self) -> None:
        with self._lock:
            watches, self._watches = list(self._watches.values()), {}
        for watch in watches:
            watch.stop()

    def _emit(self, path: str) -> None:
        try:
            self._loop.call_soon_threadsafe(self._callback, path)
        except RuntimeError:
            pass  # boucle fermée : plus personne à prévenir


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _HANDLE = ctypes.c_void_p
    _k32.CreateFileW.restype = _HANDLE
    _k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, wintypes.DWORD, _HANDLE]
    _k32.CreateEventW.restype = _HANDLE
    _k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    _k32.SetEvent.argtypes = [_HANDLE]
    _k32.CloseHandle.argtypes = [_HANDLE]
    _k32.CancelIoEx.argtypes = [_HANDLE, ctypes.c_void_p]
    _k32.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(_HANDLE), wintypes.BOOL, wintypes.DWORD]
    _k32.GetOverlappedResult.argtypes = [_HANDLE, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
    _k32.ReadDirectoryChangesW.argtypes = [_HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, ctypes.c_void_p]

    class _OVERLAPPED(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t), ("Offset", wintypes.DWORD),
                    ("OffsetHigh", wintypes.DWORD), ("hEvent", _HANDLE)]

    _INVALID = _HANDLE(-1).value
    _FILE_LIST_DIRECTORY = 0x1
    _SHARE_ALL = 0x7
    _OPEN_EXISTING = 3
    _BACKUP_SEMANTICS_OVERLAPPED = 0x02000000 | 0x40000000
    # nom de fichier, taille, dernière écriture, création
    _FILTER = 0x1 | 0x8 | 0x10 | 0x40
    _BUFFER = 64 * 1024
    _WAIT_OBJECT_0 = 0


class _DirectoryWatch:
    """Un dossier, un fil, une boucle de `ReadDirectoryChangesW`."""

    def __init__(self, directory: str, subtree: bool, emit: Callback) -> None:
        self.directory, self.subtree, self._emit = directory, subtree, emit
        self._thread: threading.Thread | None = None
        self._stop_event = None
        self._handle = None
        self._ready = threading.Event()

    def start(self) -> bool:
        self._handle = _k32.CreateFileW(self.directory, _FILE_LIST_DIRECTORY, _SHARE_ALL, None, _OPEN_EXISTING,
                                        _BACKUP_SEMANTICS_OVERLAPPED, None)
        if self._handle in (None, _INVALID):
            return False
        self._stop_event = _k32.CreateEventW(None, True, False, None)
        self._thread = threading.Thread(target=self._run, name=f"file-change-{os.path.basename(self.directory)}", daemon=True)
        self._thread.start()
        # Premier appel posé avant de rendre la main : aucune écriture ne passe entre la demande et l'écoute.
        self._ready.wait(2.0)
        return True

    def stop(self) -> None:
        if self._stop_event is not None:
            _k32.SetEvent(self._stop_event)
        if self._thread is not None:
            self._thread.join(2.0)
        if self._stop_event is not None:
            _k32.CloseHandle(self._stop_event)
            self._stop_event = None

    def _run(self) -> None:
        buffer = ctypes.create_string_buffer(_BUFFER)
        overlapped = _OVERLAPPED()
        overlapped.hEvent = _k32.CreateEventW(None, True, False, None)
        handles = (_HANDLE * 2)(overlapped.hEvent, self._stop_event)
        try:
            while True:
                _k32.ReadDirectoryChangesW(self._handle, buffer, _BUFFER, self.subtree, _FILTER, None,
                                           ctypes.byref(overlapped), None)
                self._ready.set()
                if _k32.WaitForMultipleObjects(2, handles, False, 0xFFFFFFFF) != _WAIT_OBJECT_0:
                    _k32.CancelIoEx(self._handle, ctypes.byref(overlapped))
                    _k32.GetOverlappedResult(self._handle, ctypes.byref(overlapped), ctypes.byref(wintypes.DWORD()), True)
                    return
                received = wintypes.DWORD()
                ok = _k32.GetOverlappedResult(self._handle, ctypes.byref(overlapped), ctypes.byref(received), False)
                if not ok:
                    return  # dossier supprimé ou volume démonté : la veille suivante recréera la surveillance
                if received.value == 0:
                    self._emit(self.directory)  # débordement du tampon : tout le dossier est suspect
                    continue
                for name in _parse(buffer.raw[:received.value]):
                    self._emit(os.path.normcase(os.path.join(self.directory, name)))
        finally:
            _k32.CloseHandle(overlapped.hEvent)
            _k32.CloseHandle(self._handle)
            self._ready.set()


def _parse(data: bytes) -> list[str]:
    """Noms relatifs d'un tampon de `FILE_NOTIFY_INFORMATION`."""

    names, offset = [], 0
    while offset + 12 <= len(data):
        next_offset = int.from_bytes(data[offset:offset + 4], "little")
        length = int.from_bytes(data[offset + 8:offset + 12], "little")
        names.append(data[offset + 12:offset + 12 + length].decode("utf-16-le", errors="replace"))
        if not next_offset:
            break
        offset += next_offset
    return names
