"""Rendered-frame quality detectors (handoff jarvis-remotion-native-studio-playback-fix, Slice 14).

Contract: `docs/presentation-studio.md` > *Rendered-frame quality gates (Level 3, Slice 14)*. Pure, standard library only (Core does not
depend on numpy): the frames come in already decoded, luma only, at a small working width (`WORK_WIDTH`), by
`jarvis/adapters/remotion_media_tools.py` (the pinned ffmpeg of the Remotion capability). The frames themselves are REAL rendered frames:
the guarded render host (`POST /v1/local-capabilities/remotion/render/preview`) or captures of the Variants Player; nothing here renders.

These are machine findings. They are reported apart from TSX compilation, the first-draft gate (`check_first_draft`) and the Human creative
assessment (`report_sections`), and they never replace the Human check.

- Frame detectors (`frame_findings`): `black`, `blank` (no detail at all: a uniform or smooth frame), `edge_clipped` (content touches a
  side of the frame), `edge_text_overflow` (text-like strokes cross a side). Severities depend on the frame's role in the scene and on the
  profile: `release_gate` (the machine gate deck: an empty frame anywhere but the very first is blocking) or `authored` (a real deck: an
  empty first or last frame is a deliberate fade, a warning; an empty middle frame is blocking).
- Sequence detectors: `repeated_findings` (sampled frames of a scene that never change), `frozen_spans` (captures of a playing Player that
  stay identical), `playback_findings` (early truncation, time carry, transition flash, stale progress against the composition clock).
- Page detectors (the scene's own DOM, read in the Player's sandbox page by the harness probe): `font_findings`, `asset_findings`,
  `dom_overflow_findings`.

Thresholds are named constants (`THRESHOLDS`), measured on the sample decks of Slice 14 (evidence: the Slice 14 evidence folder); the
clipping, overflow and repeated-frame classes start as warnings (decided by agent 0) until a measured false-positive rate says otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

#: Working width of a decoded frame (pixels): the detectors' scale. Height keeps the aspect ratio (even).
WORK_WIDTH = 320


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class Profile(StrEnum):
    #: The machine gate deck (Slice 03 `DECK`): every frame carries text, an empty frame is always a defect.
    RELEASE_GATE = "release_gate"
    #: A real deck: fades from and to an empty frame are an authoring choice.
    AUTHORED = "authored"


class Role(StrEnum):
    """Where a sampled frame sits in its scene (`smoke_frames`)."""

    FIRST = "first"
    ENTRY = "entry"        # frame 1: the first frame after the hand-over
    MIDDLE = "middle"
    EXIT = "exit"          # the frame before the last
    LAST = "last"
    PLAYBACK = "playback"  # a capture of a playing Player


@dataclass(frozen=True, slots=True)
class Thresholds:
    #: Two neighbouring pixels further apart than this (luma levels) make an edge.
    edge_step: int = 20
    #: Fewer edge pixels than this share of the frame: no detail, the frame is blank.
    blank_edge_density: float = 0.0008
    #: A blank frame whose mean luma is at most this is black.
    black_mean: float = 16.0
    #: A border pixel further than this from the background luma is ink.
    ink_delta: int = 48
    #: Depth (working pixels) of the band read along each side of the frame.
    band_depth: int = 4
    #: Share of a side where its band holds ink: content clipped by that side.
    clipped_ink_share: float = 0.05
    #: Smaller share that is enough when the ink is textured (text strokes cut by the side).
    overflow_ink_share: float = 0.02
    #: Share of the inked band pixels that are edges: text-like texture (a solid bar or a photo edge is smooth).
    overflow_texture: float = 0.4
    #: Mean absolute luma difference under which two frames are the same picture.
    repeat_mean_delta: float = 0.005  # identical renders decode to 0.0; a one-digit change measured 0.012-0.048
    #: A playing Player whose captures stay the same picture this long is frozen (ms).
    frozen_span_ms: int = 1000
    #: A scene that played less than this share of its authored length was cut early.
    truncation_share: float = 0.97
    #: Time (ms) the transport's position may trail or lead the Player's (its update cadence; measured lag at a scene entry: 250 to
    #: 283 ms over three recorded runs).
    stale_progress_ms: int = 500
    #: Scene-local share between the scene's own progress bar and its frame (gate deck only: its scene draws one).
    stale_bar_share: float = 0.08


THRESHOLDS = Thresholds()


@dataclass(frozen=True, slots=True)
class GrayFrame:
    """A decoded frame, luma (BT.709) only, row by row."""

    width: int
    height: int
    pixels: bytes

    def __post_init__(self) -> None:
        if self.width <= 1 or self.height <= 1 or len(self.pixels) != self.width * self.height:
            raise ValueError(f"a {self.width}x{self.height} luma frame needs {self.width * self.height} bytes, got {len(self.pixels)}")

    def row(self, y: int) -> bytes:
        return self.pixels[y * self.width:(y + 1) * self.width]

    def column(self, x: int) -> bytes:
        return self.pixels[x::self.width]


@dataclass(frozen=True, slots=True)
class Side:
    ink_share: float
    texture: float


@dataclass(frozen=True, slots=True)
class FrameMetrics:
    mean: float
    background: int
    edge_density: float
    sides: Mapping[str, Side]

    def to_dict(self) -> dict[str, Any]:
        return {"mean": round(self.mean, 1), "background": self.background, "edge_density": round(self.edge_density, 5),
                "sides": {name: {"ink_share": round(side.ink_share, 3), "texture": round(side.texture, 3)} for name, side in self.sides.items()}}


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    severity: Severity
    detail: str
    scene: str | None = None
    frame: int | None = None
    metric: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["severity"] = self.severity.value
        out["metric"] = dict(self.metric)
        return out


# ------------------------------------------------------------------ one frame


def _median(pixels: bytes) -> int:
    counts = [0] * 256
    for value in pixels:
        counts[value] += 1
    half, seen = len(pixels) // 2, 0
    for value, count in enumerate(counts):
        seen += count
        if seen > half:
            return value
    return 255


def _edges(line: bytes, step: int) -> int:
    return sum(1 for a, b in zip(line, line[1:]) if a - b > step or b - a > step)


def _side(lines: Sequence[bytes], background: int, thresholds: Thresholds) -> Side:
    """`lines`: the band of one side, outermost first, each line running along the side. Ink share: positions along the side where the
    band holds ink. Texture: share of the band's pixels, at inked positions, that differ from a neighbour (along or across) by an edge."""

    delta, step = thresholds.ink_delta, thresholds.edge_step
    length = len(lines[0])
    inked = [i for i in range(length) if any(abs(line[i] - background) > delta for line in lines)]
    if not inked:
        return Side(0.0, 0.0)
    edges = total = 0
    for depth, line in enumerate(lines):
        for i in inked:
            total += 1
            v = line[i]
            if (i + 1 < length and abs(v - line[i + 1]) > step) or (depth + 1 < len(lines) and abs(v - lines[depth + 1][i]) > step):
                edges += 1
    return Side(len(inked) / length, edges / total)


def measure(frame: GrayFrame, thresholds: Thresholds = THRESHOLDS) -> FrameMetrics:
    w, h, step, d = frame.width, frame.height, thresholds.edge_step, max(1, min(thresholds.band_depth, frame.width // 2, frame.height // 2))
    edges = sum(_edges(frame.row(y), step) for y in range(h)) + sum(_edges(frame.column(x), step) for x in range(w))
    background = _median(frame.pixels)
    sides = {"top": _side([frame.row(y) for y in range(d)], background, thresholds),
             "bottom": _side([frame.row(h - 1 - y) for y in range(d)], background, thresholds),
             "left": _side([frame.column(x) for x in range(d)], background, thresholds),
             "right": _side([frame.column(w - 1 - x) for x in range(d)], background, thresholds)}
    return FrameMetrics(sum(frame.pixels) / len(frame.pixels), background, edges / (2 * w * h), sides)


def _empty_severity(role: Role, profile: Profile) -> Severity:
    if role is Role.FIRST:
        return Severity.WARNING  # a scene may open on its background before its first reveal
    if profile is Profile.AUTHORED and role in (Role.LAST, Role.EXIT, Role.ENTRY):
        return Severity.WARNING  # a deliberate fade in / out
    return Severity.BLOCKING


def frame_findings(metrics: FrameMetrics, *, role: Role, profile: Profile = Profile.RELEASE_GATE, scene: str | None = None,
                   frame: int | None = None, thresholds: Thresholds = THRESHOLDS) -> list[Finding]:
    out: list[Finding] = []
    if metrics.edge_density < thresholds.blank_edge_density:
        code = "black" if metrics.mean <= thresholds.black_mean else "blank"
        out.append(Finding(code, _empty_severity(role, profile), f"{role.value} frame has no detail (edge density "
                                                                 f"{metrics.edge_density:.5f}, mean luma {metrics.mean:.0f})",
                           scene, frame, {"edge_density": round(metrics.edge_density, 5), "mean": round(metrics.mean, 1)}))
        return out  # an empty frame has nothing to clip
    for name, side in metrics.sides.items():
        if side.ink_share >= thresholds.overflow_ink_share and side.texture >= thresholds.overflow_texture:
            out.append(Finding("edge_text_overflow", Severity.WARNING, f"text-like strokes are cut by the {name} side "
                                                                       f"(texture {side.texture:.2f} over {side.ink_share:.0%} of it)",
                               scene, frame, {"side": name, "texture": round(side.texture, 3), "ink_share": round(side.ink_share, 3)}))
        elif side.ink_share >= thresholds.clipped_ink_share:
            out.append(Finding("edge_clipped", Severity.WARNING, f"content touches the {name} side ({side.ink_share:.0%} of it)",
                               scene, frame, {"side": name, "ink_share": round(side.ink_share, 3)}))
    return out


def difference(a: GrayFrame, b: GrayFrame) -> float:
    """Mean absolute luma difference of two frames of the same size."""

    if (a.width, a.height) != (b.width, b.height):
        raise ValueError(f"frames differ in size: {a.width}x{a.height} and {b.width}x{b.height}")
    return sum(abs(x - y) for x, y in zip(a.pixels, b.pixels)) / len(a.pixels)


# ------------------------------------------------------------------ smoke paths


def smoke_frames(duration_in_frames: int) -> tuple[tuple[int, Role], ...]:
    """The frames a smoke renders for one scene: first, entry, middle, exit, last (deduplicated, at most `MAX_PREVIEW_FRAMES` = 6)."""

    if type(duration_in_frames) is not int or duration_in_frames < 1:
        raise ValueError("duration_in_frames must be a positive integer")
    last = duration_in_frames - 1
    picked: dict[int, Role] = {}
    for at, role in ((0, Role.FIRST), (1, Role.ENTRY), (last // 2, Role.MIDDLE), (last - 1, Role.EXIT), (last, Role.LAST)):
        if 0 <= at <= last:
            picked[at] = role  # a later role wins on a short scene (frame 0 of a 1-frame scene is its last)
    return tuple(sorted(picked.items()))


def transition_pairs(scene_ids: Sequence[str]) -> list[tuple[tuple[str, Role], tuple[str, Role]]]:
    """The critical transition frames: the last frame of each scene beside the first frame of the next one."""

    return [((a, Role.LAST), (b, Role.FIRST)) for a, b in zip(scene_ids, scene_ids[1:])]


def repeated_findings(samples: Sequence[tuple[int, GrayFrame]], *, scene: str | None = None,
                      thresholds: Thresholds = THRESHOLDS) -> list[Finding]:
    """A scene whose sampled frames (first to last) are all the same picture never moves: `static_scene` (warning; a still title card is
    legitimate). Two consecutive sampled frames that are the same picture are reported as `repeated_frames` (info)."""

    if len(samples) < 2:
        return []
    deltas = [(a[0], b[0], difference(a[1], b[1])) for a, b in zip(samples, samples[1:])]
    if all(d < thresholds.repeat_mean_delta for _a, _b, d in deltas):
        return [Finding("static_scene", Severity.WARNING, f"{len(samples)} sampled frames are the same picture", scene, samples[-1][0],
                        {"max_delta": round(max(d for _a, _b, d in deltas), 3)})]
    return [Finding("repeated_frames", Severity.INFO, f"frames {a} and {b} are the same picture", scene, b, {"delta": round(d, 3)})
            for a, b, d in deltas if d < thresholds.repeat_mean_delta]


def frozen_spans(captures: Sequence[tuple[int, GrayFrame, bool]], *, thresholds: Thresholds = THRESHOLDS) -> list[Finding]:
    """`captures` = `(ms, frame, playing)` of a Player, in time order. A run of identical pictures while it plays, at least
    `frozen_span_ms` long, is `frozen_playback` (warning: a held title is legitimate; the gate deck asserts none, its scenes move every frame)."""

    out: list[Finding] = []
    run: list[int] = []  # [first ms, last ms] of the current run of identical playing pictures

    def flush() -> None:
        if run and run[1] - run[0] >= thresholds.frozen_span_ms:
            out.append(Finding("frozen_playback", Severity.WARNING, f"the playing picture did not change for {run[1] - run[0]} ms",
                               metric={"from_ms": run[0], "to_ms": run[1]}))
        run.clear()

    for (ms_a, a, playing_a), (ms_b, b, playing_b) in zip(captures, captures[1:]):
        if playing_a and playing_b and difference(a, b) < thresholds.repeat_mean_delta:
            run[:] = [run[0] if run else ms_a, ms_b]
        else:
            flush()
    flush()
    return out


# ------------------------------------------------------------------ playback (the 9-scene flow)


def playback_findings(scenes: Sequence[Mapping[str, Any]], *, thresholds: Thresholds = THRESHOLDS) -> list[Finding]:
    """Per scene shown in a continuous play: `{scene, duration_in_frames, fps, max_frame, played_ms, first_frame}`.

    - `truncated` (blocking): the scene never reached its last frame, or played less than `truncation_share` of its authored length
      (the « cut at 8 s » defect);
    - `time_carry` (blocking): the scene did not start on its frame 0 (the previous scene's time carried into it)."""

    out: list[Finding] = []
    for row in scenes:
        scene, duration, fps = str(row["scene"]), int(row["duration_in_frames"]), int(row["fps"])
        expected_ms = 1000 * (duration - 1) / fps
        max_frame, played = row.get("max_frame"), row.get("played_ms")
        if max_frame is None or max_frame < duration - 1 or played is None or played < thresholds.truncation_share * expected_ms:
            out.append(Finding("truncated", Severity.BLOCKING, f"played to frame {max_frame} of {duration - 1} in {played} ms "
                                                               f"(authored {round(expected_ms)} ms)", scene, max_frame,
                               {"max_frame": max_frame, "played_ms": played, "expected_ms": round(expected_ms)}))
        first = row.get("first_frame")
        if first is not None and first != 0:
            out.append(Finding("time_carry", Severity.BLOCKING, f"entered on frame {first}, not frame 0", scene, first, {"first_frame": first}))
    return out


def flash_findings(captures: Sequence[tuple[int, FrameMetrics]], *, thresholds: Thresholds = THRESHOLDS) -> list[Finding]:
    """Captures of the playing deck that are black or blank: a flash at a hand-over (blocking on the gate deck, whose frames all
    carry text)."""

    return [Finding("transition_flash", Severity.BLOCKING, f"a {'black' if m.mean <= thresholds.black_mean else 'blank'} picture was on screen",
                    metric={"ms": ms, "edge_density": round(m.edge_density, 5), "mean": round(m.mean, 1)})
            for ms, m in captures if m.edge_density < thresholds.blank_edge_density]


def stale_progress_findings(samples: Iterable[Mapping[str, Any]], *, fps: int, tolerance_frames: int = 0,
                            thresholds: Thresholds = THRESHOLDS) -> list[Finding]:
    """`samples` = `{ms, transport, expected, transport_tolerance?, bar_share?, local_share?, bar_tolerance?}`: the transport's composition frame (the Variants slider) beside the
    composition frame derived from the Player's own clock (`CompositionMap.frame_of`, `fps` = the composition's master rate), and, on the gate deck, the share of the scene's
    own progress bar beside the scene-local share of its frame. A gap beyond the tolerance is `stale_progress` (blocking). The per-sample
    tolerances bound what the sampling itself cannot know: the frame read and the pixels are some milliseconds apart (the caller derives
    them from the next read of the same Player and the capture interval)."""

    out: list[Finding] = []
    for row in samples:
        transport, expected = row.get("transport"), row.get("expected")
        allowed = row.get("transport_tolerance", tolerance_frames) + thresholds.stale_progress_ms * fps / 1000
        if transport is not None and expected is not None and abs(transport - expected) > allowed:
            out.append(Finding("stale_progress", Severity.BLOCKING, f"transport at frame {transport}, Player at composition frame {expected}",
                               metric={"ms": row.get("ms"), "transport": transport, "expected": expected}))
        bar, local = row.get("bar_share"), row.get("local_share")
        if bar is not None and local is not None and abs(bar - local) > thresholds.stale_bar_share + row.get("bar_tolerance", 0.0):
            out.append(Finding("stale_scene_bar", Severity.BLOCKING, f"the scene's bar shows {bar:.0%}, its frame is at {local:.0%}",
                               metric={"ms": row.get("ms"), "bar_share": round(bar, 3), "local_share": round(local, 3)}))
    return out


def content_box(frame: GrayFrame, *, black: int = 12) -> tuple[int, int, int, int]:
    """`(left, top, right, bottom)` (exclusive) of the picture inside a capture: the letterbox rows and columns (max luma <= `black`) of
    the Player's frame are cut off."""

    rows = [y for y in range(frame.height) if max(frame.row(y)) > black]
    cols = [x for x in range(frame.width) if max(frame.column(x)) > black]
    if not rows or not cols:
        return 0, 0, frame.width, frame.height
    return cols[0], rows[0], cols[-1] + 1, rows[-1] + 1


def bar_share(frame: GrayFrame, *, threshold: int = 200, band: float = 0.1, start_within: float = 0.05) -> float:
    """Gate deck only (`presentation_playback_gate_world.SCENE_TSX`): the share of the picture's width covered by the scene's white progress
    bar along its bottom. Letterbox cut off; in the bottom `band` of the picture, the longest run of white pixels that starts within the
    first `start_within` of the width (a capture's rounded corners and border hide the very first pixels)."""

    left, top, right, bottom = content_box(frame)
    width = max(1, right - left)
    best = 0
    for y in range(max(top, bottom - max(1, round(band * (bottom - top)))), bottom):
        line = frame.row(y)[left:right]
        start = next((x for x in range(min(len(line), max(1, round(start_within * width)))) if line[x] >= threshold), None)
        if start is None:
            continue
        run = 0
        for value in line[start:]:
            if value < threshold:
                break
            run += 1
        best = max(best, start + run)
    return best / width if best > 1 else 0.0


# ------------------------------------------------------------------ the scene's page (DOM probe records)

GENERIC_FAMILIES = frozenset({"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
                              "ui-monospace", "ui-rounded", "math", "emoji", "fangsong"})


def font_findings(records: Iterable[Mapping[str, Any]], *, scene: str | None = None) -> list[Finding]:
    """`records` from the page probe: `{family: "<computed font-family>", available: {name: bool}, failed_faces: [name]}`.

    - `font_load_failed` (blocking): a declared `@font-face` failed to load (a missing font file);
    - `font_fallback` (blocking): no family of the declared list is available and the list names no generic family: the browser's
      default font is drawn instead;
    - `font_substituted` (warning): the first family is missing, a later one of the declared stack is drawn."""

    out: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        for name in record.get("failed_faces") or []:
            if ("failed", name) not in seen:
                seen.add(("failed", name))
                out.append(Finding("font_load_failed", Severity.BLOCKING, f"the font file of '{name}' did not load", scene, metric={"family": name}))
        stack = [part.strip().strip("'\"") for part in str(record.get("family") or "").split(",") if part.strip()]
        if not stack:
            continue
        available = record.get("available") or {}
        usable = [name for name in stack if name.lower() in GENERIC_FAMILIES or available.get(name)]
        key = ",".join(stack)
        if ("stack", key) in seen:
            continue
        seen.add(("stack", key))
        if not usable:
            out.append(Finding("font_fallback", Severity.BLOCKING, f"no font of '{key}' is available: the browser default is drawn",
                               scene, metric={"family": key}))
        elif usable[0] != stack[0]:
            out.append(Finding("font_substituted", Severity.WARNING, f"'{stack[0]}' is missing, '{usable[0]}' is drawn", scene,
                               metric={"family": key, "drawn": usable[0]}))
    return out


def asset_findings(records: Iterable[Mapping[str, Any]], *, scene: str | None = None) -> list[Finding]:
    """`records`: `{kind: "image"|"media"|"resource", url, status?}` from the page probe (a broken `<img>`, a `<video>`/`<audio>` in error,
    a resource answered >= 400). Every one is `asset_missing` (blocking). The URL is reduced to its last path segment."""

    out: list[Finding] = []
    for record in records:
        url = str(record.get("url") or "")
        name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1][:120] or "<inline>"
        out.append(Finding("asset_missing", Severity.BLOCKING, f"{record.get('kind', 'resource')} '{name}' did not load"
                           + (f" (HTTP {record['status']})" if record.get("status") else ""), scene,
                           metric={"kind": record.get("kind"), "name": name, "status": record.get("status")}))
    return out


def dom_overflow_findings(records: Iterable[Mapping[str, Any]], *, scene: str | None = None, frame: int | None = None) -> list[Finding]:
    """`records`: `{text, outside: {left, top, right, bottom}}` (composition pixels beyond the composition box) or `{text, clipped: true}`
    (a text box whose content is larger than the box and hidden). Both are `text_overflow` (warning: an element animating in from outside
    the frame is legitimate while it moves)."""

    out: list[Finding] = []
    for record in records:
        text = str(record.get("text") or "")[:40]
        if record.get("clipped"):
            out.append(Finding("text_overflow", Severity.WARNING, f"the text '{text}' is larger than its box and cut", scene, frame,
                               {"text": text, "clipped": True}))
        elif record.get("outside"):
            beyond = {k: v for k, v in dict(record["outside"]).items() if v}
            out.append(Finding("text_overflow", Severity.WARNING, f"the text '{text}' runs out of the frame ({beyond})", scene, frame,
                               {"text": text, "outside": beyond}))
    return out


# ------------------------------------------------------------------ report


def verdict(findings: Iterable[Finding]) -> str:
    """`blocked` if any finding blocks, `warnings` if any warns, `clean` otherwise."""

    severities = {f.severity for f in findings}
    return "blocked" if Severity.BLOCKING in severities else "warnings" if Severity.WARNING in severities else "clean"


def report_sections(findings: Sequence[Finding], *, compilation: Mapping[str, Any] | None = None,
                    first_draft_gate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The quality record of a deck, step 5 of the Slice: four sections that never merge. `frame_quality` is the machine finding of this
    module; `compilation` and `first_draft_gate` are copied as given (their own owners decide them); `human_assessment` is always
    pending here: no machine verdict stands in for it."""

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.code] = counts.get(finding.code, 0) + 1
    return {"compilation": dict(compilation) if compilation is not None else {"status": "not_run_here"},
            "first_draft_gate": dict(first_draft_gate) if first_draft_gate is not None else {"status": "not_run_here"},
            "frame_quality": {"verdict": verdict(findings), "counts": counts, "findings": [f.to_dict() for f in findings],
                              "thresholds": asdict(THRESHOLDS)},
            "human_assessment": {"status": "pending", "note": "machine findings never replace the Human creative assessment"}}
