"""Runner réel du rendu Remotion (Slice 16 ; `docs/remotion-render.md`).

Tout effet disque et processus d'un rendu passe ici. Il n'écrit que sous `<runtime>/render/jobs/<job_id>/` (le dossier `runtime/` de la
capacité, `docs/remotion-runtime.md` §1) :

    work/               la source GELÉE (`src/**`, `public/**`, deux fichiers générés) : la racine Remotion du processus
    bundle/             le paquet navigateur produit par `@remotion/bundler`
    tmp/                TEMP du processus (profil du navigateur) : effacé avec le travail
    out.mp4|out.png|out.pdf, pages/   le résultat
    spec.json progress.json result.json egress.json render.log   dialogue avec `render-host.cjs` et son garde
    render-guard.cjs render-host.cjs   copies des fichiers livrés (`jarvis/capabilities/remotion/`), comparées à chaque rendu
    job.json            enregistrement de reprise (référence du processus `pid:heure`, Artifact) ; seul fichier gardé après la fin

Le processus est `node --require render-guard.cjs render-host.cjs spec.json`, cwd = `work/`, environnement en liste blanche
(`process_tree.clean_env`) SANS variable de proxy, avec seulement `JARVIS_RENDER_*` (dossier, runtime, navigateur). Aucun jeton, aucune
route de Core, aucune base n'est lisible depuis ce dossier. Le navigateur est celui de l'utilisateur (jamais un téléchargement) et ses
arguments sont réécrits par le garde (aucun réseau, y compris la boucle locale hors serveur de rendu).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

from jarvis.adapters import process_tree
from jarvis.adapters.node_capability_runner import _remove_tree, extended_path
from jarvis.adapters.remotion_compiler import read_installed_engine
from jarvis.adapters.remotion_studio_runner import safe_relative
from jarvis.domain import presentation_render as D
from jarvis.domain import presentation_render_output as O
from jarvis.domain.presentation_artifacts import RenderFormat
from jarvis.domain.presentation_render import RenderError, RenderErrorCode as C
from jarvis.domain.remotion_studio import StudioError
from jarvis.ports.remotion_render import BrowserInfo, RunOutcome, VerifiedOutput

SHIPPED_DIR = Path(__file__).resolve().parents[1] / "capabilities" / "remotion"
GUARD_FILE, HOST_FILE = "render-guard.cjs", "render-host.cjs"
RENDER_DIR, JOBS_DIR = "render", "jobs"
LOG_FILE = "render.log"
LOG_MAX_BYTES = 1_000_000
POLL_S = 0.4
DIR_CHECK_EVERY_S = 2.0
COPY_CHUNK = 1 << 20
NODE_FLAGS = ("--max-old-space-size=2048",)
FFPROBE_TIMEOUT_S = 30.0
PROXY_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_VERSION_DIR = re.compile(r"\d+\.\d+\.\d+\.\d+\Z")
_JOB_ID = re.compile(r"rj_[0-9a-f]{12}\Z")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dir_bytes(root: Path) -> int:
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    else:
                        try:
                            total += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
        except OSError:
            continue
    return total


def _browser_candidates(environ: Mapping[str, str], which: Callable[[str], str | None]) -> list[str]:
    explicit = environ.get("JARVIS_REMOTION_RENDER_BROWSER", "").strip()
    if explicit:
        return [explicit]
    found: list[str] = []
    if sys.platform == "win32":
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = environ.get(var, "")
            if base:
                found.append(str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"))
        base = environ.get("PROGRAMFILES(X86)", "")
        if base:
            found.append(str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    elif sys.platform == "darwin":
        found.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            path = which(name)
            if path:
                found.append(path)
    return found


class RemotionRenderRunner:
    def __init__(self, runtime_dir: Callable[[], Path], *, which: Callable[[str], str | None] = shutil.which,
                 environ: Mapping[str, str] | None = None, spawn=process_tree.spawn_tracked, clock=time.monotonic,
                 free_bytes: Callable[[Path], int] | None = None) -> None:
        self._runtime_dir = runtime_dir
        self._which = which
        self._environ = os.environ if environ is None else environ
        self._spawn = spawn
        self._clock = clock
        self._free = free_bytes or (lambda path: shutil.disk_usage(path).free)

    # ------------------------------------------------------------------ emplacements

    @property
    def _jobs(self) -> Path:
        return Path(self._runtime_dir()) / RENDER_DIR / JOBS_DIR

    def job_dir(self, job_id: str) -> Path:
        if not _JOB_ID.fullmatch(str(job_id)):
            raise RenderError(C.INVALID, "not a render job id")
        return self._jobs / job_id

    def runtime_ready(self) -> str | None:
        runtime = Path(self._runtime_dir())
        if self._which("node") is None:
            return "node_missing: Node.js is no longer on PATH"
        for package in ("bundler", "renderer"):
            if not (runtime / "node_modules" / "@remotion" / package / "package.json").is_file():
                return f"{package}_missing: @remotion/{package} is not installed in the Remotion runtime; run repair"
        return None

    def installed_engine(self):
        return read_installed_engine(Path(self._runtime_dir()))

    # ------------------------------------------------------------------ navigateur et contrôle média

    def find_browser(self) -> BrowserInfo | None:
        for candidate in _browser_candidates(self._environ, self._which):
            path = Path(candidate)
            if path.is_file():
                return BrowserInfo(str(path), self._version_of(path))
        return None

    @staticmethod
    def _version_of(path: Path) -> str:
        """Version d'après le dossier `<version>/` d'une installation Chrome Windows ; JAMAIS en lançant le navigateur (un `--version`
        d'un Chrome déjà ouvert s'adresse à la session de l'utilisateur)."""

        try:
            versions = sorted((e.name for e in os.scandir(path.parent) if e.is_dir() and _VERSION_DIR.fullmatch(e.name)),
                              key=lambda v: tuple(int(p) for p in v.split(".")))
        except OSError:
            versions = []
        name = path.stem.lower()
        label = "edge" if "msedge" in name else "chrome"
        return f"{label} {versions[-1]}" if versions else "unknown"

    def _ffprobe(self) -> Path | None:
        modules = Path(self._runtime_dir()) / "node_modules" / "@remotion"
        try:
            for entry in sorted(os.scandir(modules), key=lambda e: e.name):
                if entry.name.startswith("compositor-"):
                    for name in ("ffprobe.exe", "ffprobe"):
                        if (Path(entry.path) / name).is_file():
                            return Path(entry.path) / name
        except OSError:
            return None
        return None

    # ------------------------------------------------------------------ travail

    def prepare(self, job_id: str, files: Mapping[str, bytes]) -> None:
        job = self.job_dir(job_id)
        try:
            self._jobs.mkdir(parents=True, exist_ok=True)
            free = self._free(self._jobs)
            if free < D.MIN_FREE_BYTES:
                raise RenderError(C.DISK_LOW, f"{free // (1 << 20)} MiB free, a render needs at least {D.MIN_FREE_BYTES // (1 << 20)} MiB")
            _remove_tree(job)
            for name in ("work", "tmp", "pages"):
                (job / name).mkdir(parents=True, exist_ok=True)
            for path, data in files.items():
                safe_relative(path)
                target = job / "work" / Path(*path.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bytes(data))
            for name in (GUARD_FILE, HOST_FILE):
                shutil.copyfile(SHIPPED_DIR / name, job / name)
        except StudioError as exc:
            raise RenderError(C.SOURCE_REFUSED, f"a source path is not a plain relative path ({exc.detail[:100]})") from None
        except OSError as exc:
            raise RenderError(C.DISK_FULL if getattr(exc, "errno", None) == 28 else C.STORE_FAILED,
                              f"{type(exc).__name__}: the render folder could not be prepared") from None

    def _env(self, job: Path, browser: BrowserInfo) -> dict[str, str]:
        env = process_tree.clean_env({"NO_COLOR": "1", "FORCE_COLOR": "0", "CI": "1"}, environ=self._environ)
        for name in list(env):
            if name.upper() in PROXY_ENV:
                env.pop(name)
        tmp = str(job / "tmp")
        env.update(TEMP=tmp, TMP=tmp, TMPDIR=tmp, JARVIS_RENDER_DIR=str(job), JARVIS_RENDER_RUNTIME=str(Path(self._runtime_dir())),
                   JARVIS_RENDER_BROWSER=browser.path)
        return env

    def run(self, job_id: str, spec: Mapping[str, Any], *, browser: BrowserInfo, cancel: threading.Event, timeout_s: float,
            on_start: Callable[[str], None], on_progress: Callable[[Mapping[str, Any]], None]) -> RunOutcome:
        job = self.job_dir(job_id)
        node = self._which("node")
        if node is None:
            return RunOutcome(False, C.RUNTIME_UNAVAILABLE.value, "node_missing: Node.js is no longer on PATH")
        full = {**spec, "runtime": str(Path(self._runtime_dir())), "work": str(job / "work"), "bundle_dir": str(job / "bundle"),
                "progress": str(job / "progress.json"), "result": str(job / "result.json"), "pages_dir": str(job / "pages"),
                "out": str(job / self._out_name(spec["format"])), "browser": browser.path}
        (job / "spec.json").write_text(json.dumps(full), encoding="utf-8")
        for stale in ("progress.json", "result.json", "egress.json"):
            try:
                (job / stale).unlink()
            except OSError:
                pass
        argv = [node, *NODE_FLAGS, "--require", str(job / GUARD_FILE), str(job / HOST_FILE), str(job / "spec.json")]
        started = self._clock()
        try:
            proc = self._spawn(argv, cwd=job / "work", env=self._env(job, browser), log_path=job / LOG_FILE)
        except OSError as exc:
            return RunOutcome(False, C.RUNTIME_UNAVAILABLE.value, f"{type(exc).__name__}: the render process could not be launched")
        ref = process_tree.make_process_ref(proc.pid)
        if not ref:
            process_tree.kill_tree(proc.pid)
            return RunOutcome(False, C.FAILED.value, "process_identity_unavailable: the render process start time could not be read")
        on_start(ref)
        code, detail = "", ""
        last_dir_check = 0.0
        while True:
            returncode = proc.poll()
            progress = self._read_json(job / "progress.json")
            if progress:
                on_progress(progress)
            if returncode is not None:
                break
            now = self._clock()
            if cancel.is_set():
                code, detail = C.CANCELLED.value, "cancelled by the user"
            elif now - started > timeout_s:
                code, detail = C.TIMEOUT.value, f"the render exceeded its {int(timeout_s)} s limit"
            elif now - last_dir_check >= DIR_CHECK_EVERY_S:
                last_dir_check = now
                used = _dir_bytes(job)
                if used > D.MAX_JOB_DIR_BYTES:
                    code, detail = C.JOB_TOO_LARGE.value, f"the render folder grew past {D.MAX_JOB_DIR_BYTES // (1 << 20)} MiB"
                elif self._free(job) < (64 << 20):
                    code, detail = C.DISK_FULL.value, "the disk is nearly full"
            if code:
                if not process_tree.kill_tree(proc.pid):
                    detail += "; the process tree is still alive after the kill"
                try:
                    proc.wait(timeout=process_tree.KILL_GRACE_S)
                except Exception:  # noqa: BLE001 - argued: the kill result is already in `detail`; nothing else to do with a stuck wait
                    pass
                break
            time.sleep(POLL_S)
        self._rotate_log(job)
        elapsed = self._clock() - started
        result = self._read_json(job / "result.json") or {}
        egress = result.get("egress") if isinstance(result.get("egress"), dict) else (self._read_json(job / "egress.json") or {})
        tail = self._log_tail(job)
        if code:
            return RunOutcome(False, code, detail, egress=egress, elapsed_s=elapsed, log_tail=tail)
        if proc.returncode == 0 and result.get("ok") is True:
            outputs = [Path(item) for item in result.get("outputs", []) if isinstance(item, str)]
            return RunOutcome(True, outputs=outputs, egress=egress, elapsed_s=elapsed, log_tail=tail)
        message = D.clean_detail(result.get("message") or " | ".join(tail[-3:]) or f"exit code {proc.returncode}")
        reported = str(result.get("code") or "")
        if "ENOSPC" in message or "no space left" in message.lower():
            return RunOutcome(False, C.DISK_FULL.value, message, egress=egress, elapsed_s=elapsed, log_tail=tail)
        mapped = {"composition_mismatch": C.COMPOSITION_MISMATCH, "render_crashed": C.CRASHED}.get(reported, C.FAILED)
        return RunOutcome(False, mapped.value, message, egress=egress, elapsed_s=elapsed, log_tail=tail)

    # ------------------------------------------------------------------ résultat

    @staticmethod
    def _out_name(fmt: str) -> str:
        return {"mp4": "out.mp4", "still": "out.png", "pdf": "out.pdf"}[fmt]

    def verify(self, job_id: str, fmt: str, *, width: int, height: int, frames: int | None, pages: int | None) -> VerifiedOutput:
        job = self.job_dir(job_id)
        kind = RenderFormat(fmt)

        def bad(message: str) -> RenderError:
            return RenderError(C.OUTPUT_INVALID, message)

        try:
            if kind is RenderFormat.PDF:
                files = sorted((job / "pages").glob("page-*.jpg"))
                if pages is None or len(files) != pages:
                    raise bad(f"expected {pages} page images, found {len(files)}")
                images = [path.read_bytes() for path in files]
                document, sizes = O.build_pdf(images)
                if any(size != (width, height) for size in sizes):
                    raise bad(f"a page image is not {width}x{height}")
                (job / "out.pdf").write_bytes(document)
            path = job / self._out_name(fmt)
            if not path.is_file():
                raise bad("the render finished without producing its output file")
            size = path.stat().st_size
            if size == 0:
                raise bad("the output file is empty")
            if size > D.MAX_OUTPUT_BYTES:
                raise RenderError(C.OUTPUT_TOO_LARGE, f"the output is {size} bytes, at most {D.MAX_OUTPUT_BYTES}")
            with path.open("rb") as handle:
                O.check_header(kind, handle.read(16))
            sha = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(COPY_CHUNK), b""):
                    sha.update(chunk)
            if kind is RenderFormat.STILL:
                actual = O.png_size(path.read_bytes())
                if actual != (width, height):
                    raise bad(f"the still is {actual[0]}x{actual[1]}, expected {width}x{height}")
                return VerifiedOutput(path, size, sha.hexdigest(), width, height, None, None, None, "png")
            if kind is RenderFormat.PDF:
                count = O.pdf_page_count(path.read_bytes())
                if count != pages:
                    raise bad(f"the PDF has {count} pages, expected {pages}")
                return VerifiedOutput(path, size, sha.hexdigest(), width, height, None, None, count, "pdf")
            return self._verify_video(path, size, sha.hexdigest(), width, height, frames, bad)
        except O.OutputProblem as exc:
            raise bad(str(exc)) from None
        except OSError as exc:
            raise bad(f"{type(exc).__name__}: the output could not be read") from None

    def _verify_video(self, path: Path, size: int, sha: str, width: int, height: int, frames: int | None, bad) -> VerifiedOutput:
        ffprobe = self._ffprobe()
        if ffprobe is None:
            return VerifiedOutput(path, size, sha, width, height, None, None, None, "header")
        try:
            result = subprocess.run(
                [str(ffprobe), "-v", "error", "-show_entries",
                 "stream=codec_type,codec_name,width,height,nb_frames,r_frame_rate,duration:format=duration", "-of", "json", str(path)],
                cwd=str(path.parent), env=process_tree.clean_env(environ=self._environ), capture_output=True, text=True, timeout=FFPROBE_TIMEOUT_S,
                check=False, creationflags=process_tree._creationflags())
        except (OSError, subprocess.SubprocessError) as exc:
            raise bad(f"ffprobe could not run ({type(exc).__name__})") from None
        if result.returncode != 0:
            raise bad("ffprobe could not read the video: " + D.clean_detail(result.stderr, 160))
        try:
            facts = O.video_facts(json.loads(result.stdout))
        except (ValueError, O.OutputProblem) as exc:
            raise bad(f"the video is not readable: {D.clean_detail(exc, 160)}") from None
        if (facts.width, facts.height) != (width, height) or facts.codec != D.CODEC:
            raise bad(f"the video is {facts.width}x{facts.height} {facts.codec}, expected {width}x{height} {D.CODEC}")
        if frames is not None and facts.frames is not None and facts.frames != frames:
            raise bad(f"the video holds {facts.frames} frames, expected {frames}")
        return VerifiedOutput(path, size, sha, facts.width, facts.height, facts.duration_ms, facts.frames, None, "ffprobe")

    def copy_output(self, job_id: str, verified: VerifiedOutput, write: Callable[[bytes], Any]) -> None:
        with verified.path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(COPY_CHUNK), b""):
                write(chunk)

    # ------------------------------------------------------------------ reprise, nettoyage

    def cleanup(self, job_id: str) -> None:
        """Efface tout le dossier du travail SAUF `job.json` (la trace du travail, petite) et le journal."""

        job = self.job_dir(job_id)
        try:
            for entry in os.scandir(extended_path(job)):
                if entry.name in ("job.json", LOG_FILE, "result.json", "egress.json"):
                    continue
                _remove_tree(Path(entry.path))
        except OSError:
            pass

    def stop(self, process_ref: str) -> bool:
        parsed = process_tree.parse_process_ref(process_ref)
        if parsed is None or not process_tree.ref_alive(process_ref):
            return True  # parti, ou le pid appartient à un autre programme : on ne tue jamais à l'aveugle
        return process_tree.kill_tree(parsed[0])

    def alive(self, process_ref: str) -> bool:
        return process_tree.ref_alive(process_ref)

    def write_record(self, job_id: str, record: Mapping[str, Any]) -> None:
        job = self.job_dir(job_id)
        try:
            job.mkdir(parents=True, exist_ok=True)
            temporary = job / f"job.json.{secrets.token_hex(3)}.tmp"
            temporary.write_text(json.dumps(dict(record), sort_keys=True), encoding="utf-8")
            os.replace(temporary, job / "job.json")
        except OSError as exc:
            raise RenderError(C.STORE_FAILED, f"{type(exc).__name__}: the render record could not be written") from None

    def records(self) -> list[Mapping[str, Any]]:
        found: list[Mapping[str, Any]] = []
        try:
            entries = sorted(e.name for e in os.scandir(self._jobs) if e.is_dir() and _JOB_ID.fullmatch(e.name))
        except OSError:
            return found
        for name in entries:
            record = self._read_json(self._jobs / name / "job.json")
            found.append(record if isinstance(record, dict) and record.get("job_id") == name else {"job_id": name, "unreadable": True})
        return found

    # ------------------------------------------------------------------ petits utilitaires

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return raw if isinstance(raw, dict) else None

    @staticmethod
    def _rotate_log(job: Path) -> None:
        log = job / LOG_FILE
        try:
            if log.stat().st_size > LOG_MAX_BYTES:
                data = log.read_bytes()[-LOG_MAX_BYTES // 2:]
                log.write_bytes(data)
        except OSError:
            pass

    @staticmethod
    def _log_tail(job: Path, lines: int = 8) -> list[str]:
        try:
            text = (job / LOG_FILE).read_text(encoding="utf-8", errors="replace")[-6000:]
        except OSError:
            return []
        out = [D.clean_detail(_ANSI.sub("", line), 200) for line in text.splitlines()]
        return [line for line in out if line][-lines:]
