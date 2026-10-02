"""Écrans Windows et capture GDI (handoff session-context-recording, Slice 07 ; D-SCREEN).

`ctypes` seulement, aucune dépendance :

- **DPI** : chaque appel bascule **le fil courant** en
  `DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2` puis rétablit l'ancien
  contexte. Sans cela, un processus non conscient du DPI (Core) voit des
  coordonnées virtualisées (1536×864 pour un écran 1920×1080 à 125 %) et la
  capture serait réduite ou décalée. Contrairement à `mss`, qui appelle
  `SetProcessDpiAwareness` et change tout le processus Core, l'effet reste
  borné à l'appel ;
- **écrans** : `EnumDisplayMonitors` + `GetMonitorInfoW` +
  `GetDpiForMonitor`, en pixels physiques. Ordre stable : l'écran principal
  est `display1`, les autres suivent de gauche à droite puis de haut en bas ;
- **capture** : `BitBlt(SRCCOPY | CAPTUREBLT)` de l'écran vers une DIB
  32 bits de haut en bas. Un bureau sécurisé (session verrouillée, invite
  UAC) refuse la copie : `permission_denied` ; tout autre refus GDI :
  `source_unavailable`, avec le code Windows.

Windows ne demande aucune autorisation de capture pour GDI : il n'existe pas
de chemin « autorisation » à franchir, seulement les refus ci-dessus.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import os
import re
from typing import Any, TypeVar

from jarvis.domain.capture import CaptureErrorCode
from jarvis.ports.capture import CaptureSourceError

PRIMARY_DISPLAY = "display1"
_DISPLAY_TOKEN = re.compile(r"display([1-9][0-9]?)")
#: DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
_PER_MONITOR_AWARE_V2 = -4
_SRCCOPY = 0x00CC0020
_CAPTUREBLT = 0x40000000
_ACCESS_DENIED = 5
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class Display:
    """Un écran, en pixels physiques du bureau virtuel."""

    name: str
    #: Nom Windows (`\\\\.\\DISPLAY1`), pour le diagnostic seulement.
    device: str
    left: int
    top: int
    width: int
    height: int
    primary: bool
    dpi: int

    @property
    def scale(self) -> float:
        return round(self.dpi / 96, 3)

    def details(self) -> dict[str, Any]:
        """Faits bornés pour les métadonnées d'un Artifact."""

        return {"display": self.name, "display_device": self.device[:64], "display_left": self.left,
                "display_top": self.top, "display_primary": self.primary, "dpi": self.dpi, "dpi_scale": self.scale}


@dataclass(frozen=True, slots=True)
class Frame:
    display: Display
    width: int
    height: int
    #: BGRA 8 bits, de haut en bas.
    bgra: bytes


def parse_display_token(token: str) -> int | None:
    """`default` -> `None` (écran principal) ; `displayN` -> N ; sinon `ValueError`."""

    if token == "default":
        return None
    match = _DISPLAY_TOKEN.fullmatch(token)
    if match is None:
        raise ValueError(f"display must be 'default' or 'display<N>', got {token[:40]!r}")
    return int(match.group(1))


def pick_display(displays: list[Display], token: str) -> Display:
    """L'écran demandé ; absent (débranché, index trop grand) : `source_unavailable`."""

    index = parse_display_token(token)
    if not displays:
        raise CaptureSourceError(CaptureErrorCode.SOURCE_UNAVAILABLE, "no display is attached")
    position = 1 if index is None else index
    if position > len(displays):
        raise CaptureSourceError(CaptureErrorCode.SOURCE_UNAVAILABLE,
                                 f"display{position} is not attached ({len(displays)} display(s))")
    return displays[position - 1]


def order_displays(raw: list[tuple[str, int, int, int, int, bool, int]]) -> list[Display]:
    """Principal d'abord, puis gauche -> droite, haut -> bas ; noms `display1..N` dans cet ordre."""

    ordered = sorted(raw, key=lambda m: (not m[5], m[1], m[2]))
    return [Display(name=f"display{i}", device=m[0], left=m[1], top=m[2], width=m[3], height=m[4], primary=m[5],
                    dpi=m[6]) for i, m in enumerate(ordered, start=1)]


class WindowsDisplays:
    """Énumération des écrans et capture GDI, DPI conscient par fil. Windows seulement."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise CaptureSourceError(CaptureErrorCode.UNSUPPORTED_PLATFORM,
                                     "desktop capture is implemented for Windows only")
        from ctypes import wintypes as w

        self._w = w
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        try:
            self._shcore: Any = ctypes.WinDLL("shcore", use_last_error=True)
        except OSError:
            self._shcore = None
        u, g = self._user32, self._gdi32
        u.GetDC.argtypes, u.GetDC.restype = [w.HWND], w.HDC
        u.ReleaseDC.argtypes, u.ReleaseDC.restype = [w.HWND, w.HDC], ctypes.c_int
        g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [w.HDC], w.HDC
        g.DeleteDC.argtypes, g.DeleteDC.restype = [w.HDC], w.BOOL
        g.SelectObject.argtypes, g.SelectObject.restype = [w.HDC, w.HGDIOBJ], w.HGDIOBJ
        g.DeleteObject.argtypes, g.DeleteObject.restype = [w.HGDIOBJ], w.BOOL
        g.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HDC, ctypes.c_int,
                             ctypes.c_int, w.DWORD]
        g.BitBlt.restype = w.BOOL
        g.CreateDIBSection.argtypes = [w.HDC, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p),
                                       w.HANDLE, w.DWORD]
        g.CreateDIBSection.restype = w.HBITMAP
        g.GdiFlush.argtypes, g.GdiFlush.restype = [], w.BOOL
        self._set_context = getattr(u, "SetThreadDpiAwarenessContext", None)
        if self._set_context is not None:
            self._set_context.argtypes, self._set_context.restype = [ctypes.c_void_p], ctypes.c_void_p

    # ------------------------------------------------------------ DPI

    @contextmanager
    def _per_monitor_aware(self) -> Iterator[bool]:
        """Fil courant en conscience DPI par écran le temps du bloc ; rend faux si Windows ne l'offre pas."""

        if self._set_context is None:
            yield False
            return
        previous = self._set_context(ctypes.c_void_p(_PER_MONITOR_AWARE_V2))
        try:
            yield bool(previous)
        finally:
            if previous:
                self._set_context(ctypes.c_void_p(previous))

    def _aware(self, action: Callable[[], _T]) -> _T:
        with self._per_monitor_aware():
            return action()

    # ------------------------------------------------------------ écrans

    def displays(self) -> list[Display]:
        return self._aware(self._enumerate)

    def _enumerate(self) -> list[Display]:
        w = self._w

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT), ("dwFlags", w.DWORD),
                        ("szDevice", w.WCHAR * 32)]

        found: list[tuple[str, int, int, int, int, bool, int]] = []
        callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HMONITOR, w.HDC, ctypes.POINTER(w.RECT), w.LPARAM)

        def on_monitor(handle, _dc, _rect, _param):  # noqa: ANN001, ANN202 - Win32 callback signature
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(MonitorInfo)
            if not self._user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                return True
            dpi = 96
            if self._shcore is not None:
                dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
                if self._shcore.GetDpiForMonitor(handle, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
                    dpi = int(dpi_x.value) or 96
            rect = info.rcMonitor
            found.append((info.szDevice, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top,
                          bool(info.dwFlags & 1), dpi))
            return True

        if not self._user32.EnumDisplayMonitors(None, None, callback_type(on_monitor), 0):
            raise self._error("EnumDisplayMonitors")
        return order_displays(found)

    # ------------------------------------------------------------ capture

    def grab(self, token: str) -> Frame:
        """Image BGRA de l'écran `token` (`default`, `displayN`), en pixels physiques."""

        def run() -> Frame:
            display = pick_display(self._enumerate(), token)
            return Frame(display=display, width=display.width, height=display.height,
                         bgra=self._blit(display.left, display.top, display.width, display.height))

        return self._aware(run)

    def _blit(self, left: int, top: int, width: int, height: int) -> bytes:
        w, u, g = self._w, self._user32, self._gdi32

        class BitmapInfoHeader(ctypes.Structure):
            _fields_ = [("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG), ("biPlanes", w.WORD),
                        ("biBitCount", w.WORD), ("biCompression", w.DWORD), ("biSizeImage", w.DWORD),
                        ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD),
                        ("biClrImportant", w.DWORD)]

        screen = u.GetDC(None)
        if not screen:
            raise self._error("GetDC")
        memory = bitmap = previous = None
        try:
            memory = g.CreateCompatibleDC(screen)
            if not memory:
                raise self._error("CreateCompatibleDC")
            header = BitmapInfoHeader(biSize=ctypes.sizeof(BitmapInfoHeader), biWidth=width, biHeight=-height,
                                      biPlanes=1, biBitCount=32, biCompression=0)
            bits = ctypes.c_void_p()
            bitmap = g.CreateDIBSection(memory, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
            if not bitmap or not bits.value:
                raise self._error("CreateDIBSection")
            previous = g.SelectObject(memory, bitmap)
            if not g.BitBlt(memory, 0, 0, width, height, screen, left, top, _SRCCOPY | _CAPTUREBLT):
                raise self._error("BitBlt")
            g.GdiFlush()
            return ctypes.string_at(bits.value, width * height * 4)
        finally:
            if memory and previous:
                g.SelectObject(memory, previous)
            if bitmap:
                g.DeleteObject(bitmap)
            if memory:
                g.DeleteDC(memory)
            u.ReleaseDC(None, screen)

    @staticmethod
    def _error(call: str) -> CaptureSourceError:
        code = ctypes.get_last_error()
        if code == _ACCESS_DENIED:
            return CaptureSourceError(CaptureErrorCode.PERMISSION_DENIED,
                                      f"{call} refused by Windows (access denied: locked session or secure desktop)")
        return CaptureSourceError(CaptureErrorCode.SOURCE_UNAVAILABLE, f"{call} failed (Windows error {code})")


__all__ = ["Display", "Frame", "PRIMARY_DISPLAY", "WindowsDisplays", "order_displays", "parse_display_token",
           "pick_display"]
