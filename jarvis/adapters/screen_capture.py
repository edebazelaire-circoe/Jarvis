"""Capture d'écran et enregistrement d'écran du bureau dans Core (handoff session-context-recording, Slice 07).

Sources du `CaptureService` pour le canal `screen` (D16, D18, D-CAP, D-SCREEN ;
contrat `docs/capture.md` › *Screen capture*). Distinctes de la capture de
scène (`runtime/scene-captures/`, diagnostic, rendu du canevas de Jarvis) :
rien ici ne la touche, et elle ne passe jamais par ici.

- **Capture d'écran** (`DesktopScreenshotSource`) : GDI `BitBlt` par `ctypes`
  (`windows_display`), PNG RGB encodé par la bibliothèque standard
  (`jarvis.media.png`). Aucune dépendance.
- **Enregistrement** (`ScreenRecordingSource`) : un **sous-processus ffmpeg**
  (binaire fourni par le paquet `imageio-ffmpeg`, extra `capture`), entrée
  `gdigrab` limitée au rectangle de l'écran choisi, H.264 (`libx264`,
  `veryfast`, `zerolatency`, CRF 30), **MP4 fragmenté** (fragments d'1 s) écrit
  directement dans le `.partial` du spool de l'Artifact (`CaptureSink.hand_over`).
  Un fragment complet est lisible seul : une mort brutale perd au plus la
  dernière seconde.
- **Supervision** (`FfmpegProcess`) : processus créé suspendu, placé dans un
  *Job Object* Windows `KILL_ON_JOB_CLOSE` (`OwnedProcessTree`, déjà utilisé
  pour les CLI d'agents) puis relancé : si Core meurt, le noyau ferme la
  poignée du job et tue ffmpeg — aucun encodeur orphelin ne continue
  d'enregistrer. stderr est vidé par un fil dans un tampon borné (40 lignes).
  Arrêt : `q` sur stdin, attente 5 s, puis fin du job (kill) et attente 3 s.
- **Perte** : encodeur sorti seul, plus aucun octet pendant 15 s, ou écran
  enregistré débranché / déplacé / redimensionné (vérifié toutes les 2 s) :
  `source_lost`, la capture s'arrête, la preuve finit `partial`.

`FragmentedMp4Repair` est la réparation de famille appliquée après une mort de
Core : fin déchirée tronquée en place, durée mesurée par ffmpeg s'il est là,
fichier sans aucun fragment complet déclaré illisible (`failed`).

Dépendances facultatives importées paresseusement : sans `imageio-ffmpeg`
(ni `JARVIS_FFMPEG_EXE`), l'enregistrement est refusé `source_unavailable` ;
la capture d'écran fonctionne sans rien. Hors Windows : `unsupported_platform`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Protocol

from jarvis.adapters.windows_display import Display, Frame, parse_display_token, pick_display
from jarvis.domain.capture import CaptureChannel, CaptureError, CaptureErrorCode, CaptureMode
from jarvis.domain.v2 import utc_now
from jarvis.media.fmp4 import scan
from jarvis.media.png import bgra_to_png
from jarvis.ports.capture import (
    CaptureSink, CaptureSource, CaptureSourceError, MediaInfo, OneShotResult, OneShotSource, RepairOutcome,
    RepairTarget, SourceHealth,
)

DESKTOP_SOURCE = "desktop"
#: 5 images/s : lisible pour relire un écran de travail, ≈ 21-24 % d'un cœur et 0,6-1,7 Mo/min
#: mesurés sur l'hôte (docs/capture.md › Screen capture).
DEFAULT_FPS = 5
MAX_FPS = 30
#: Une image clé toutes les 10 s : recherche et extraction d'images bornées, fichier petit.
KEYFRAME_INTERVAL_S = 10
FRAGMENT_US = 1_000_000
CRF = 30
READY_TIMEOUT_S = 10.0
STOP_GRACE_S = 5.0
KILL_WAIT_S = 3.0
STALL_S = 15.0
WATCH_INTERVAL_S = 0.5
DISPLAY_CHECK_S = 2.0
PROBE_TIMEOUT_S = 30.0
#: Mesure de durée à l'arrêt : bornée pour que arrêt propre (5 s) + mesure restent sous
#: l'échéance d'arrêt du service (10 s) ; au-delà, la durée vient de l'horloge.
STOP_PROBE_TIMEOUT_S = 2.0
STDERR_LINES = 40
STDERR_LINE_CHARS = 300
_TIME = re.compile(r"time=(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_PERMISSION_MARKERS = ("access is denied", "accès refusé", "permission denied")
_DISK_FULL_MARKERS = ("no space left", "there is not enough space", "espace insuffisant")


# ------------------------------------------------------------------ ffmpeg


def find_ffmpeg() -> str | None:
    """Binaire ffmpeg : `JARVIS_FFMPEG_EXE`, sinon celui du paquet `imageio-ffmpeg` (extra `capture`)."""

    configured = os.getenv("JARVIS_FFMPEG_EXE", "").strip()
    if configured:
        return configured if Path(configured).is_file() else None
    try:
        import imageio_ffmpeg  # extra `capture`, facultatif
    except ImportError:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - intentional: package present but binary missing -> "not installed"
        return None


def recording_args(ffmpeg: str, display: Display, output: Path, *, fps: int = DEFAULT_FPS) -> list[str]:
    """Arguments explicites de l'encodeur (aucun réglage implicite d'ffmpeg ne décide du format)."""

    return [
        ffmpeg, "-hide_banner", "-nostats", "-loglevel", "warning",
        "-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", "1",
        "-offset_x", str(display.left), "-offset_y", str(display.top),
        "-video_size", f"{display.width}x{display.height}", "-i", "desktop",
        # yuv420p exige des dimensions paires.
        "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-crf", str(CRF),
        "-pix_fmt", "yuv420p", "-g", str(fps * KEYFRAME_INTERVAL_S),
        "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-frag_duration", str(FRAGMENT_US),
        "-flush_packets", "1", "-f", "mp4", "-y", str(output),
    ]


def probe_duration_ms(ffmpeg: str | None, path: Path, *, timeout_s: float = PROBE_TIMEOUT_S) -> int | None:
    """Durée lisible d'une vidéo (copie de flux vers `null`, sans décodage) ; `None` si inconnue."""

    if ffmpeg is None:
        return None
    try:
        done = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-stats", "-i", str(path), "-map", "0:v:0",
                               "-c", "copy", "-f", "null", "-"], capture_output=True, timeout=timeout_s,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    matches = _TIME.findall(done.stderr.decode("utf-8", "replace"))
    if done.returncode != 0 or not matches:
        return None
    hours, minutes, seconds = matches[-1]
    return int(round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000))


def extract_frame(ffmpeg: str, video: Path, *, at_ms: int, timeout_s: float = PROBE_TIMEOUT_S) -> bytes:
    """Une image PNG d'un enregistrement fini à `at_ms` (primitive pour l'enrichissement, Slice 08).

    Décodage d'une seule image (recherche à l'image clé précédente) ; la
    création de l'Artifact dérivé (`frame_from`) appartient à l'appelant.
    `CaptureSourceError` (`source_unavailable`) si ffmpeg échoue ou ne rend rien.
    """

    try:
        done = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-ss",
                               f"{max(0, at_ms) / 1000:.3f}", "-i", str(video), "-frames:v", "1", "-f", "image2pipe",
                               "-c:v", "png", "-"], capture_output=True, timeout=timeout_s,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CaptureSourceError(CaptureErrorCode.SOURCE_UNAVAILABLE, f"frame extraction failed: {type(exc).__name__}: "
                                 f"{exc}"[:300]) from exc
    if done.returncode != 0 or not done.stdout:
        reason = done.stderr.decode("utf-8", "replace").strip()[-200:] or "no frame at this time"
        raise CaptureSourceError(CaptureErrorCode.SOURCE_UNAVAILABLE, f"frame extraction failed: {reason}")
    return done.stdout


class EncoderProcess(Protocol):
    """Un encodeur lancé : ce que la source en utilise (réel : `FfmpegProcess` ; tests : faux scénarisés)."""

    def poll(self) -> int | None: ...

    def request_stop(self) -> None:
        """Demande d'arrêt propre (`q` sur stdin, puis fin de stdin) ; ne lève pas."""
        ...

    def wait(self, timeout_s: float) -> int | None:
        """Code de sortie, ou `None` si toujours vivant après `timeout_s`."""
        ...

    def kill(self) -> None: ...

    def stderr_tail(self) -> list[str]: ...

    def close(self) -> None:
        """Libère les poignées (job, tubes) une fois le processus fini."""
        ...


class FfmpegProcess:
    """Encodeur supervisé : job `KILL_ON_JOB_CLOSE`, stderr borné, arrêt `q` puis kill."""

    def __init__(self, args: Sequence[str]) -> None:
        from jarvis.runtime.owned_process_tree import OwnedProcessTree

        try:
            # Le job d'abord : un encodeur qui ne peut pas être contenu ne démarre pas
            # (il pourrait survivre à Core et enregistrer sans propriétaire).
            self._tree = OwnedProcessTree()
        except OSError as exc:
            raise CaptureSourceError(CaptureErrorCode.SOURCE_UNAVAILABLE,
                                     f"encoder containment unavailable: {exc}"[:300]) from exc
        try:
            self._process = subprocess.Popen(list(args), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.PIPE, creationflags=OwnedProcessTree.creationflags)
        except OSError as exc:
            self._close_tree()
            raise CaptureSourceError(CaptureErrorCode.SOURCE_UNAVAILABLE,
                                     f"encoder did not start: {type(exc).__name__}: {exc}"[:300]) from exc
        try:
            self._tree.attach_and_resume(self._process.pid)
        except OSError as exc:
            self._process.kill()
            self._process.wait()
            self._close_tree()
            raise CaptureSourceError(CaptureErrorCode.SOURCE_UNAVAILABLE,
                                     f"encoder could not be contained: {exc}"[:300]) from exc
        self._tail: deque[str] = deque(maxlen=STDERR_LINES)
        self._drain = threading.Thread(target=self._drain_stderr, name="screen-encoder-stderr", daemon=True)
        self._drain.start()

    @property
    def pid(self) -> int:
        return self._process.pid

    def _drain_stderr(self) -> None:
        stream = self._process.stderr
        assert stream is not None
        try:
            for line in iter(stream.readline, b""):
                text = line.decode("utf-8", "replace").strip()
                if text:
                    self._tail.append(text[:STDERR_LINE_CHARS])
        except (OSError, ValueError):
            return  # intentional: tube fermé à la fin du processus

    def poll(self) -> int | None:
        return self._process.poll()

    def request_stop(self) -> None:
        stdin = self._process.stdin
        if stdin is None:
            return
        try:
            stdin.write(b"q")
            stdin.flush()
        except OSError:
            pass  # intentional: déjà sorti, le code de sortie le dira
        try:
            stdin.close()
        except OSError:
            pass  # intentional: même raison

    def wait(self, timeout_s: float) -> int | None:
        try:
            return self._process.wait(timeout_s)
        except subprocess.TimeoutExpired:
            return None

    def kill(self) -> None:
        try:
            self._tree.terminate()
        except OSError:
            self._process.kill()

    def stderr_tail(self) -> list[str]:
        return list(self._tail)

    def close(self) -> None:
        self._drain.join(2.0)
        if self._process.stderr is not None:
            self._process.stderr.close()
        self._close_tree()

    def _close_tree(self) -> None:
        try:
            self._tree.close_if_empty()
        except OSError:
            pass  # intentional: poignée libérée par Windows à la sortie de Core


# ------------------------------------------------------------------ écrans


class DisplayProvider(Protocol):
    def displays(self) -> list[Display]: ...

    def grab(self, token: str) -> Frame: ...


def _windows_displays() -> DisplayProvider:
    from jarvis.adapters.windows_display import WindowsDisplays

    return WindowsDisplays()


def _check_device(device: str) -> None:
    try:
        parse_display_token(device)
    except ValueError as exc:
        raise CaptureError(CaptureErrorCode.INVALID_CAPTURE, str(exc)) from None


# ------------------------------------------------------------------ capture d'écran


class DesktopScreenshotSource:
    """Une image PNG de l'écran choisi (`default` = principal), en pixels physiques."""

    payload_name = "screenshot.png"
    mime_type = "image/png"

    def __init__(self, *, displays: DisplayProvider, device: str) -> None:
        self._displays = displays
        self._device = device

    async def capture(self) -> OneShotResult:
        return await asyncio.to_thread(self._capture)

    def _capture(self) -> OneShotResult:
        captured_at = utc_now()
        started = time.perf_counter()
        frame = self._displays.grab(self._device)
        try:
            data = bgra_to_png(frame.width, frame.height, frame.bgra)
        except ValueError as exc:
            raise CaptureSourceError(CaptureErrorCode.WRITE_FAILED, f"PNG encoding refused: {exc}") from exc
        details = {**frame.display.details(), "captured_at": captured_at.isoformat(), "capture_backend": "gdi_bitblt",
                   "image_format": "png_rgb8", "capture_ms": int((time.perf_counter() - started) * 1000)}
        return OneShotResult(data=data, width=frame.width, height=frame.height, details=details)


# ------------------------------------------------------------------ enregistrement


@dataclass
class _Watch:
    last_size: int = 0
    last_growth: float = 0.0
    last_display_check: float = 0.0


class ScreenRecordingSource:
    """Enregistrement continu d'un écran par un encodeur ffmpeg supervisé (une instance par capture)."""

    payload_name = "screen.mp4"
    mime_type = "video/mp4"

    def __init__(
        self,
        *,
        ffmpeg: str,
        displays: DisplayProvider,
        device: str,
        fps: int = DEFAULT_FPS,
        spawn: Callable[[Sequence[str]], EncoderProcess] = FfmpegProcess,
        probe: Callable[[Path], int | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        ready_timeout_s: float = READY_TIMEOUT_S,
        stop_grace_s: float = STOP_GRACE_S,
        kill_wait_s: float = KILL_WAIT_S,
        stall_s: float = STALL_S,
        watch_interval_s: float = WATCH_INTERVAL_S,
        display_check_s: float = DISPLAY_CHECK_S,
    ) -> None:
        if not 1 <= fps <= MAX_FPS:
            raise CaptureError(CaptureErrorCode.INVALID_CAPTURE, f"fps must be 1..{MAX_FPS}, got {fps}")
        self._ffmpeg = ffmpeg
        self._displays = displays
        self._device = device
        self._fps = fps
        self._spawn = spawn
        self._probe = probe if probe is not None else (
            lambda path: probe_duration_ms(ffmpeg, path, timeout_s=STOP_PROBE_TIMEOUT_S))
        self._clock = clock
        self._ready_timeout_s = ready_timeout_s
        self._stop_grace_s = stop_grace_s
        self._kill_wait_s = kill_wait_s
        self._stall_s = stall_s
        self._watch_interval_s = watch_interval_s
        self._display_check_s = display_check_s
        self._process: EncoderProcess | None = None
        self._sink: CaptureSink | None = None
        self._path: Path | None = None
        self._display: Display | None = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._lost: str | None = None
        self._watcher: threading.Thread | None = None
        self._watch = _Watch()
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._exit_code: int | None = None
        self._killed = False
        self._duration_source = "unknown"
        self._duration_ms: int | None = None

    # ------------------------------------------------------------ cycle de vie

    async def start(self, sink: CaptureSink) -> None:
        await asyncio.to_thread(self._start, sink)

    def _start(self, sink: CaptureSink) -> None:
        display = pick_display(self._displays.displays(), self._device)
        self._display = display
        self._sink = sink
        path = sink.hand_over()
        self._path = path
        process = self._spawn(recording_args(self._ffmpeg, display, path, fps=self._fps))
        self._process = process
        deadline = self._clock() + self._ready_timeout_s
        while True:
            code = process.poll()
            if code is not None:
                process.close()
                raise self._start_error(f"encoder exited with code {code} before writing", process.stderr_tail())
            if self._size() > 0:
                break
            if self._clock() >= deadline:
                process.kill()
                process.wait(self._kill_wait_s)
                process.close()
                raise CaptureSourceError(CaptureErrorCode.SOURCE_UNAVAILABLE,
                                         f"encoder wrote nothing within {self._ready_timeout_s:g} s: "
                                         f"{' | '.join(process.stderr_tail()[-3:])}"[:300])
            time.sleep(0.05)
        now = self._clock()
        self._started_at = now
        self._watch = _Watch(last_size=self._size(), last_growth=now, last_display_check=now)
        self._watcher = threading.Thread(target=self._watch_loop, name="screen-encoder-watch", daemon=True)
        self._watcher.start()

    async def stop(self) -> None:
        await asyncio.to_thread(self._stop)

    def _stop(self) -> None:
        self._stopping.set()
        process = self._process
        if process is None:
            return
        failure: CaptureSourceError | None = None
        code = process.poll()
        if code is None:
            process.request_stop()
            code = process.wait(self._stop_grace_s)
            if code is None:
                self._killed = True
                process.kill()
                code = process.wait(self._kill_wait_s)
                failure = CaptureSourceError(
                    CaptureErrorCode.SOURCE_TIMEOUT,
                    f"encoder did not stop within {self._stop_grace_s:g} s and was killed "
                    f"(the last fragment, up to 1 s, may be lost)")
        self._stopped_at = self._clock()
        self._exit_code = code
        if self._watcher is not None:
            self._watcher.join(self._watch_interval_s * 4 + 1)
        tail = process.stderr_tail()
        process.close()
        if failure is None and code not in (0, None) and self._lost is None:
            failure = self._run_error(f"encoder exited with code {code}", tail)
        # Encodeur tué : pas de mesure (l'échéance d'arrêt est presque consommée).
        self._measure(probe=not self._killed)
        if failure is not None:
            raise failure

    def _measure(self, *, probe: bool) -> None:
        duration = None
        if probe and self._path is not None and self._size() > 0:
            try:
                duration = self._probe(self._path)
            except Exception:  # noqa: BLE001 - optional fact: wall clock below, source said in details
                duration = None
        if duration is not None:
            self._duration_ms, self._duration_source = duration, "probe"
        elif self._started_at is not None and self._stopped_at is not None:
            self._duration_ms = int((self._stopped_at - self._started_at) * 1000)
            self._duration_source = "wall_clock"

    # ------------------------------------------------------------ surveillance

    def _watch_loop(self) -> None:
        process = self._process
        assert process is not None
        while not self._stopping.wait(self._watch_interval_s):
            code = process.poll()
            if code is not None:
                if not self._stopping.is_set():
                    self._report_lost(f"encoder exited by itself with code {code}: "
                                      f"{' | '.join(process.stderr_tail()[-3:])}")
                return
            now = self._clock()
            size = self._size()
            if size > self._watch.last_size:
                self._watch.last_size, self._watch.last_growth = size, now
            elif now - self._watch.last_growth >= self._stall_s:
                self._report_lost(f"no new video fragment for {self._stall_s:g} s")
                process.kill()
                return
            if now - self._watch.last_display_check >= self._display_check_s:
                self._watch.last_display_check = now
                changed = self._display_changed()
                if changed is not None:
                    # ffmpeg filmerait un rectangle qui n'est plus cet écran : arrêt dit.
                    self._report_lost(changed)
                    return

    def _display_changed(self) -> str | None:
        display = self._display
        assert display is not None
        try:
            current = self._displays.displays()
        except CaptureSourceError as exc:
            return f"displays unreadable: {exc}"
        for candidate in current:
            if (candidate.device, candidate.left, candidate.top, candidate.width, candidate.height) == (
                    display.device, display.left, display.top, display.width, display.height):
                return None
        return (f"{display.name} ({display.width}x{display.height} at {display.left},{display.top}) was "
                f"disconnected, moved or resized")

    def _report_lost(self, reason: str) -> None:
        with self._lock:
            if self._lost is not None:
                return
            self._lost = reason
        if self._sink is not None:
            self._sink.lost(CaptureErrorCode.SOURCE_LOST, reason[:200])

    # ------------------------------------------------------------ état

    def _size(self) -> int:
        try:
            return os.stat(self._path).st_size if self._path is not None else 0
        except OSError:
            return 0

    def health(self) -> SourceHealth:
        process = self._process
        running = process is not None and process.poll() is None
        if self._lost is not None:
            return SourceHealth(ok=False, code=CaptureErrorCode.SOURCE_LOST.value, detail=self._lost[:200])
        return SourceHealth(ok=running, code=None if running else "encoder_stopped")

    def media_info(self) -> MediaInfo:
        display = self._display
        details: dict[str, Any] = {"fps": self._fps, "video_codec": "h264", "video_encoder": "libx264",
                                   "container": "mp4_fragmented", "capture_backend": "gdigrab",
                                   "keyframe_interval_s": KEYFRAME_INTERVAL_S, "encoder_exit_code": self._exit_code,
                                   "encoder_killed": self._killed, "duration_source": self._duration_source}
        if display is not None:
            details.update(display.details())
        return MediaInfo(duration_ms=self._duration_ms, width=None if display is None else display.width // 2 * 2,
                         height=None if display is None else display.height // 2 * 2, details=details)

    # ------------------------------------------------------------ erreurs

    @staticmethod
    def _start_error(what: str, tail: list[str]) -> CaptureSourceError:
        text = " | ".join(tail[-3:])
        code = (CaptureErrorCode.PERMISSION_DENIED if any(m in text.lower() for m in _PERMISSION_MARKERS)
                else CaptureErrorCode.SOURCE_UNAVAILABLE)
        return CaptureSourceError(code, f"{what}: {text}"[:300])

    @staticmethod
    def _run_error(what: str, tail: list[str]) -> CaptureSourceError:
        text = " | ".join(tail[-3:])
        code = (CaptureErrorCode.STORAGE_FULL if any(m in text.lower() for m in _DISK_FULL_MARKERS)
                else CaptureErrorCode.WRITE_FAILED)
        return CaptureSourceError(code, f"{what}: {text}"[:300])


# ------------------------------------------------------------------ registre


class ScreenCaptureSources:
    """`CaptureSourceRegistry` du canal `screen` : `desktop` (défaut) ; le reste refusé.

    Device : `default` (écran principal) ou `displayN` (principal = `display1`,
    puis gauche -> droite). L'écran est résolu à chaque prise / démarrage.
    """

    def __init__(self, *, displays_factory: Callable[[], DisplayProvider] = _windows_displays,
                 ffmpeg_locator: Callable[[], str | None] = find_ffmpeg, fps: int = DEFAULT_FPS,
                 platform_name: str = os.name, **recording_options: Any) -> None:
        self._displays_factory = displays_factory
        self._ffmpeg_locator = ffmpeg_locator
        self._fps = fps
        self._platform = platform_name
        self._options = recording_options

    def _check(self, channel: CaptureChannel, source: str | None, device: str) -> None:
        if CaptureChannel(channel) is not CaptureChannel.SCREEN or source not in (None, DESKTOP_SOURCE):
            raise CaptureError(CaptureErrorCode.UNSUPPORTED_SOURCE,
                               f"no capture source {source or 'default'!r} for channel {CaptureChannel(channel).value}")
        if self._platform != "nt":
            raise CaptureError(CaptureErrorCode.UNSUPPORTED_PLATFORM,
                               "desktop capture is implemented for Windows only")
        _check_device(device)

    def _displays(self) -> DisplayProvider:
        try:
            return self._displays_factory()
        except CaptureSourceError as exc:
            raise CaptureError(exc.code, str(exc)) from exc

    def continuous(self, channel: CaptureChannel, *, source: str | None, device: str) -> CaptureSource:
        self._check(channel, source, device)
        ffmpeg = self._ffmpeg_locator()
        if ffmpeg is None:
            raise CaptureError(CaptureErrorCode.SOURCE_UNAVAILABLE,
                               "screen recording needs ffmpeg: install the 'capture' extra "
                               "(pip install -e \".[capture]\") or set JARVIS_FFMPEG_EXE")
        return ScreenRecordingSource(ffmpeg=ffmpeg, displays=self._displays(), device=device, fps=self._fps,
                                     **self._options)

    def one_shot(self, channel: CaptureChannel, *, source: str | None, device: str) -> OneShotSource:
        self._check(channel, source, device)
        return DesktopScreenshotSource(displays=self._displays(), device=device)

    def source_name(self, channel: CaptureChannel, mode: CaptureMode, source: str | None) -> str:
        if CaptureChannel(channel) is not CaptureChannel.SCREEN or source not in (None, DESKTOP_SOURCE):
            raise CaptureError(CaptureErrorCode.UNSUPPORTED_SOURCE,
                               f"no capture source {source or 'default'!r} for channel {CaptureChannel(channel).value}")
        return DESKTOP_SOURCE


# ------------------------------------------------------------------ réparation


class FragmentedMp4Repair:
    """`CaptureRepair` du canal `screen` : MP4 fragmenté d'un enregistrement interrompu par la mort de Core.

    La fin déchirée (fragment en cours d'écriture) est tronquée en place ; le
    reste, fait de fragments complets, est lisible tel quel. Durée mesurée par
    ffmpeg quand il est installé (sinon inconnue). Aucun fragment complet
    (encodeur tué avant la première seconde) : `usable=False`, la capture finit
    `failed`.
    """

    def __init__(self, *, ffmpeg_locator: Callable[[], str | None] = find_ffmpeg,
                 probe: Callable[[str | None, Path], int | None] = probe_duration_ms) -> None:
        self._ffmpeg_locator = ffmpeg_locator
        self._probe = probe

    def repair(self, target: RepairTarget) -> RepairOutcome:
        if target.partial_bytes:
            path, size = target.partial_path, target.partial_bytes
        elif target.final_bytes:
            path, size = target.final_path, target.final_bytes
        else:
            return RepairOutcome(repaired=False, detail="no_bytes")
        with open(path, "r+b") as handle:
            found = scan(handle, size)
            if not found.usable:
                return RepairOutcome(repaired=False, usable=False,
                                     detail=(f"unreadable: ftyp={found.has_ftyp} moov={found.has_moov} "
                                             f"fragments={found.fragments} {found.problem or ''}").strip()[:200])
            repaired = found.torn_bytes > 0
            if repaired:
                handle.truncate(found.readable_end)
                handle.flush()
                os.fsync(handle.fileno())
        duration = self._probe(self._ffmpeg_locator(), path)
        return RepairOutcome(repaired=repaired, duration_ms=duration,
                             detail=f"mp4_fragments={found.fragments} trimmed_bytes={found.torn_bytes}"
                                    + ("" if duration is not None else " duration_unknown"))


__all__ = [
    "DEFAULT_FPS", "DESKTOP_SOURCE", "DesktopScreenshotSource", "EncoderProcess", "FfmpegProcess",
    "FragmentedMp4Repair", "ScreenCaptureSources", "ScreenRecordingSource", "extract_frame", "find_ffmpeg",
    "probe_duration_ms", "recording_args",
]
