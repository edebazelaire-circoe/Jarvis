"""Rendu d'une présentation GELÉE : réglages déterministes, bornes, états d'un travail, codes d'échec (Remotion Slice 16).

Contrat : `docs/remotion-render.md`. Pur : aucune E/S, aucune horloge, aucun processus.

Ce qui se rend : UNE scène (`scene_id`) d'un snapshot complet. La cadence, la taille et la durée sont celles que le manifeste de la scène
DÉCLARE (jamais lues dans le code de la scène) : l'utilisateur choisit seulement ce qui ne change pas le contenu (échelle de sortie,
plage d'images, image fixe, pages, qualité). Les réglages résolus sont enregistrés dans les métadonnées de l'Artifact dérivé : la même
source gelée et les mêmes réglages donnent les mêmes images.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from enum import StrEnum
from typing import Any

from jarvis.domain.presentation_artifacts import RenderFormat

CODEC = "h264"
PIXEL_FORMAT = "yuv420p"
IMAGE_FORMAT = {RenderFormat.MP4: "mp4", RenderFormat.STILL: "png", RenderFormat.PDF: "jpeg"}
SCALES = (0.25, 0.5, 1.0, 1.5, 2.0)
DEFAULT_CRF = 23
MIN_CRF, MAX_CRF = 16, 35
#: Mémoire de Chrome : un onglet de rendu pèse plusieurs centaines de Mo. Défaut 1, au plus 2, et le produit pixels x onglets est borné.
DEFAULT_CONCURRENCY = 1
MAX_CONCURRENCY = 2
MAX_PIXELS_TIMES_TABS = 3840 * 2160
JPEG_QUALITY = 90
#: Bornes de coût (taille, temps, disque). Une scène plus longue se rend par plages.
MAX_RENDER_FRAMES = 3600
MAX_PDF_PAGES = 24
MAX_OUTPUT_WIDTH, MAX_OUTPUT_HEIGHT = 3840, 2160
MAX_OUTPUT_BYTES = 512 * 1024 * 1024
MAX_JOB_DIR_BYTES = 2 * 1024 * 1024 * 1024
MIN_FREE_BYTES = 1536 * 1024 * 1024
TIMEOUT_BASE_S = 300.0
TIMEOUT_PER_FRAME_S = 1.0
TIMEOUT_CAP_S = 3600.0
#: Travaux non terminés (1 en cours + les autres en attente, créations en vol comprises), un seul rendu à la fois ; les 20 derniers
#: terminés restent en mémoire ; par snapshot, les 20 derniers rendus gardent leurs fichiers même en échec (rétention).
MAX_ACTIVE_JOBS = 8
KEEP_FINISHED = 20
KEEP_RENDERS_PER_SNAPSHOT = 20
CONCURRENCY_LIMIT = 1
SETTINGS_KEYS = frozenset({"scene_id", "frame_start", "frame_end", "frame", "frames", "scale", "crf", "concurrency"})
_SCENE_ID_PREFIX = "pss_"


class RenderErrorCode(StrEnum):
    INVALID = "presentation_render_invalid"
    UNAVAILABLE = "presentation_render_unavailable"
    RUNTIME_UNAVAILABLE = "presentation_render_runtime_unavailable"
    BROWSER_UNAVAILABLE = "presentation_render_browser_unavailable"
    UNKNOWN_JOB = "presentation_render_unknown_job"
    UNKNOWN_SCENE = "presentation_render_unknown_scene"
    SNAPSHOT_INVALID = "presentation_render_snapshot_invalid"
    SOURCE_REFUSED = "presentation_render_source_refused"
    ENGINE_MISMATCH = "presentation_render_engine_mismatch"
    QUEUE_FULL = "presentation_render_queue_full"
    NOT_CANCELLABLE = "presentation_render_not_cancellable"
    DISK_LOW = "presentation_render_disk_low"
    DISK_FULL = "presentation_render_disk_full"
    JOB_TOO_LARGE = "presentation_render_job_too_large"
    TIMEOUT = "presentation_render_timeout"
    CANCELLED = "presentation_render_cancelled"
    FAILED = "presentation_render_failed"
    CRASHED = "presentation_render_crashed"
    COMPOSITION_MISMATCH = "presentation_render_composition_mismatch"
    OUTPUT_INVALID = "presentation_render_output_invalid"
    OUTPUT_TOO_LARGE = "presentation_render_output_too_large"
    INTERRUPTED = "presentation_render_interrupted"
    SANDBOX_UNAVAILABLE = "presentation_render_sandbox_unavailable"
    GUARD_UNEXPECTED_ARGS = "presentation_render_guard_unexpected_args"
    GUARD_NOT_APPLIED = "presentation_render_guard_not_applied"
    LOCKED = "presentation_render_locked"
    STORE_FAILED = "presentation_render_store_failed"
    INTERNAL = "presentation_render_internal_error"


HTTP_STATUS: Mapping[RenderErrorCode, int] = {
    RenderErrorCode.INVALID: 400, RenderErrorCode.UNKNOWN_JOB: 404, RenderErrorCode.UNKNOWN_SCENE: 404,
    RenderErrorCode.UNAVAILABLE: 503, RenderErrorCode.RUNTIME_UNAVAILABLE: 409, RenderErrorCode.BROWSER_UNAVAILABLE: 409,
    RenderErrorCode.SNAPSHOT_INVALID: 409, RenderErrorCode.SOURCE_REFUSED: 409, RenderErrorCode.ENGINE_MISMATCH: 409,
    RenderErrorCode.LOCKED: 409, RenderErrorCode.QUEUE_FULL: 429, RenderErrorCode.NOT_CANCELLABLE: 409, RenderErrorCode.DISK_LOW: 507,
    RenderErrorCode.STORE_FAILED: 500, RenderErrorCode.INTERNAL: 500,
}


class RenderError(Exception):
    def __init__(self, code: RenderErrorCode, detail: str = "") -> None:
        self.code = RenderErrorCode(code)
        self.detail = detail if len(detail) <= 400 else detail[:399] + "…"
        self.status = HTTP_STATUS.get(self.code, 409)
        super().__init__(f"{self.code.value}: {self.detail}" if self.detail else self.code.value)


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (JobState.COMPLETE, JobState.FAILED, JobState.CANCELLED)


def _invalid(message: str) -> RenderError:
    return RenderError(RenderErrorCode.INVALID, message)


def _int(raw: Mapping[str, Any], key: str, low: int, high: int) -> int | None:
    value = raw.get(key)
    if value is None:
        return None
    if type(value) is not int or not low <= value <= high:
        raise _invalid(f"{key} must be an integer {low}..{high}")
    return value


@dataclass(frozen=True, slots=True)
class RenderSettings:
    """Ce que l'utilisateur peut choisir. Clés fermées ; tout le reste vient du manifeste figé."""

    scene_id: str | None = None
    frame_start: int | None = None
    frame_end: int | None = None
    frame: int | None = None
    frames: tuple[int, ...] | None = None
    scale: float = 1.0
    crf: int = DEFAULT_CRF
    concurrency: int = DEFAULT_CONCURRENCY


def parse_settings(fmt: RenderFormat, raw: object) -> RenderSettings:
    """Réglages d'une demande : clés fermées, types stricts, ne s'appliquent qu'au format qui les lit."""

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise _invalid("settings must be an object")
    unknown = sorted(str(key)[:40] for key in raw if key not in SETTINGS_KEYS)
    if unknown:
        raise _invalid(f"unknown settings {unknown[:5]}; allowed: {sorted(SETTINGS_KEYS)}")
    scene_id = raw.get("scene_id")
    if scene_id is not None and (not isinstance(scene_id, str) or not scene_id.startswith(_SCENE_ID_PREFIX) or len(scene_id) > 40):
        raise _invalid("scene_id must be a scene id (pss_...)")
    scale = raw.get("scale", 1.0)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or float(scale) not in SCALES:
        raise _invalid(f"scale must be one of {list(SCALES)}")
    crf = raw.get("crf", DEFAULT_CRF)
    if type(crf) is not int or not MIN_CRF <= crf <= MAX_CRF:
        raise _invalid(f"crf must be an integer {MIN_CRF}..{MAX_CRF}")
    concurrency = raw.get("concurrency", DEFAULT_CONCURRENCY)
    if type(concurrency) is not int or not 1 <= concurrency <= MAX_CONCURRENCY:
        raise _invalid(f"concurrency must be an integer 1..{MAX_CONCURRENCY}")
    start, end = _int(raw, "frame_start", 0, 107_999), _int(raw, "frame_end", 0, 107_999)
    frame = _int(raw, "frame", 0, 107_999)
    frames_raw = raw.get("frames")
    frames: tuple[int, ...] | None = None
    if frames_raw is not None:
        if (not isinstance(frames_raw, list) or not 1 <= len(frames_raw) <= MAX_PDF_PAGES
                or any(type(item) is not int or not 0 <= item <= 107_999 for item in frames_raw)):
            raise _invalid(f"frames must be a list of 1..{MAX_PDF_PAGES} frame numbers")
        frames = tuple(frames_raw)
    allowed = {RenderFormat.MP4: {"frame_start", "frame_end"}, RenderFormat.STILL: {"frame"}, RenderFormat.PDF: {"frames"}}[fmt]
    stray = sorted(key for key in ("frame_start", "frame_end", "frame", "frames") if key in raw and key not in allowed)
    if stray:
        raise _invalid(f"{stray} do not apply to a {fmt.value} render")
    if fmt is RenderFormat.MP4 and start is not None and end is not None and end < start:
        raise _invalid("frame_end must not be before frame_start")
    return RenderSettings(scene_id, start, end, frame, frames, float(scale), crf, concurrency)


@dataclass(frozen=True, slots=True)
class SceneTarget:
    """La scène choisie dans le snapshot, telle que le paquet la fige."""

    scene_id: str
    prefab_id: str
    version: int
    composition_id: str
    width: int
    height: int
    fps: int
    duration_in_frames: int
    engine_version: str
    engine_lock_sha256: str
    source_digest: str


@dataclass(frozen=True, slots=True)
class ResolvedRender:
    """Les réglages résolus contre la composition déclarée : ce qui sera rendu, et ce qui sera enregistré."""

    fmt: RenderFormat
    target: SceneTarget
    settings: RenderSettings
    frame_start: int
    frame_end: int
    frames: tuple[int, ...]
    out_width: int
    out_height: int

    @property
    def frames_total(self) -> int:
        return self.frame_end - self.frame_start + 1 if self.fmt is RenderFormat.MP4 else len(self.frames)

    @property
    def timeout_s(self) -> float:
        return min(TIMEOUT_CAP_S, TIMEOUT_BASE_S + TIMEOUT_PER_FRAME_S * self.frames_total)

    def canonical(self) -> dict[str, Any]:
        t = self.target
        return {"format": self.fmt.value, "scene_id": t.scene_id, "prefab_id": t.prefab_id, "prefab_version": t.version,
                "composition": t.composition_id, "source_digest": t.source_digest, "fps": t.fps, "width": self.out_width,
                "height": self.out_height, "scale": self.settings.scale, "codec": CODEC if self.fmt is RenderFormat.MP4 else None,
                "pixel_format": PIXEL_FORMAT if self.fmt is RenderFormat.MP4 else None,
                "crf": self.settings.crf if self.fmt is RenderFormat.MP4 else None,
                "image_format": IMAGE_FORMAT[self.fmt], "frame_start": self.frame_start if self.fmt is RenderFormat.MP4 else None,
                "frame_end": self.frame_end if self.fmt is RenderFormat.MP4 else None,
                "frames": list(self.frames) if self.fmt is not RenderFormat.MP4 else None,
                "engine": t.engine_version, "engine_lock_sha256": t.engine_lock_sha256}

    @property
    def settings_sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.canonical(), sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()

    def to_metadata(self) -> dict[str, Any]:
        """Métadonnées d'acquisition de l'Artifact dérivé : scalaires plats (bornes du registre), figées à l'état terminal."""

        t = self.target
        meta: dict[str, Any] = {
            "render_scene_id": t.scene_id, "render_prefab_id": t.prefab_id, "render_prefab_version": t.version,
            "render_composition": t.composition_id, "render_source_digest": t.source_digest, "render_fps": t.fps,
            "render_width": self.out_width, "render_height": self.out_height, "render_scale": self.settings.scale,
            "render_image_format": IMAGE_FORMAT[self.fmt], "render_engine": t.engine_version,
            "render_engine_lock_sha256": t.engine_lock_sha256, "render_settings_sha256": self.settings_sha256,
            "render_flat": True}
        if self.fmt is RenderFormat.MP4:
            meta.update(render_codec=CODEC, render_pixel_format=PIXEL_FORMAT, render_crf=self.settings.crf,
                        render_frame_start=self.frame_start, render_frame_end=self.frame_end)
        else:
            meta["render_frames"] = ",".join(str(f) for f in self.frames)
        return meta


def resolve(fmt: RenderFormat, settings: RenderSettings, target: SceneTarget) -> ResolvedRender:
    """Réglages contre la composition DÉCLARÉE : plages dans la durée, taille de sortie bornée, nombre d'images borné."""

    last = target.duration_in_frames - 1
    out_width = math.ceil(target.width * settings.scale)
    out_height = math.ceil(target.height * settings.scale)
    if out_width > MAX_OUTPUT_WIDTH or out_height > MAX_OUTPUT_HEIGHT:
        raise _invalid(f"output {out_width}x{out_height} exceeds {MAX_OUTPUT_WIDTH}x{MAX_OUTPUT_HEIGHT}: lower the scale")
    if out_width * out_height * settings.concurrency > MAX_PIXELS_TIMES_TABS:
        raise _invalid(f"{out_width}x{out_height} with {settings.concurrency} tabs needs more memory than the bound allows: use 1 tab or a lower scale")
    if fmt is RenderFormat.MP4:
        if out_width % 2 or out_height % 2:
            raise _invalid(f"an MP4 needs even dimensions, {out_width}x{out_height} is not: choose another scale")
        start = 0 if settings.frame_start is None else settings.frame_start
        end = last if settings.frame_end is None else settings.frame_end
        if start > last or end > last or end < start:
            raise _invalid(f"frame range {start}..{end} is outside the scene ({target.duration_in_frames} frames, 0..{last})")
        if end - start + 1 > MAX_RENDER_FRAMES:
            raise _invalid(f"{end - start + 1} frames exceed the bound of {MAX_RENDER_FRAMES}: render a shorter range")
        frames: tuple[int, ...] = ()
    else:
        start, end = 0, last
        if fmt is RenderFormat.STILL:
            frames = (0 if settings.frame is None else settings.frame,)
        else:
            frames = settings.frames if settings.frames is not None else (0,)
        if any(f > last for f in frames):
            raise _invalid(f"frame {max(frames)} is outside the scene (0..{last})")
        if len(set(frames)) != len(frames):
            raise _invalid("frames must be distinct")
    return ResolvedRender(fmt, target, settings, start, end, frames, out_width, out_height)


def scene_target(manifest: Mapping[str, Any], scene_id: str | None, *, source_blocks: Mapping[tuple[str, int], Mapping[str, Any]],
                 digests: Mapping[tuple[str, int], str]) -> SceneTarget:
    """La scène à rendre d'après le manifeste figé et le bloc `source.json` de son pin. `scene_id` absent : la première scène
    Remotion du snapshot (l'ordre est celui de la variante) ; plusieurs scènes sans choix explicite ne sont pas devinées."""

    candidates = []
    for scene in manifest["scenes"]:
        key = (scene["prefab"]["id"], scene["prefab"]["version"])
        if key in source_blocks:
            candidates.append((scene, key))
    if scene_id is None:
        if len(candidates) != 1:
            raise RenderError(RenderErrorCode.UNKNOWN_SCENE, f"this snapshot holds {len(candidates)} renderable scenes: pass settings.scene_id "
                                                             f"(one of {[c[0]['scene_id'] for c in candidates][:12]})")
        scene, key = candidates[0]
    else:
        match = next(((s, k) for s, k in candidates if s["scene_id"] == scene_id), None)
        if match is None:
            raise RenderError(RenderErrorCode.UNKNOWN_SCENE, f"scene {scene_id} is not a Remotion scene of this snapshot")
        scene, key = match
    block = source_blocks[key]
    comp, engine = block["composition"], block["engine"]
    return SceneTarget(scene["scene_id"], key[0], key[1], comp["id"], comp["width"], comp["height"], comp["fps"],
                       comp["duration_in_frames"], engine["version"], engine["lock_sha256"], digests[key])


def clean_detail(text: object, limit: int = 300) -> str:
    """Un message de processus rendu à l'utilisateur : une ligne, sans chemin absolu de la machine."""

    import re
    line = " ".join(str(text).split())
    line = re.sub(r"(?:[A-Za-z]:[\\/]|\\\\\?\\|\\\\[^\\/\s]+[\\/])[^\s\"'|<>)\]]*", "<path>", line)
    line = re.sub(r"(?<![\w./-])/(?:[\w.@~+-]+/)+[\w.@~+-]*", "<path>", line)
    return line[:limit]


def frames_of(sequence: Sequence[int]) -> str:
    return ",".join(str(item) for item in sequence)
