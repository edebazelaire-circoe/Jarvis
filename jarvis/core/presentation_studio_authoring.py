"""Core service of the authoring planner: check and assemble a first draft (handoff jarvis-interactive-presentation-studio, Slice 11).

The Jarvis brain (an LLM) does the creative work and hands it over as ONE submission (`{actor, brief, draft}`,
`jarvis/domain/presentation_studio_authoring.py`). This service is the deterministic side of that exchange; it makes quality a
property of the code path, not of the prompt:

- **`check`** (dry run) : parse, resolve the prefabs, assemble the documents in memory, run every validation and the quality
  gate, return the report. **Nothing is written, nothing is published**; the same draft gives the same report.
- **`assemble`** : the same preparation, then, only if the gate has no error: publish the new prefab bundles, assemble the
  documents with the real pins, validate again, and store the whole Presentation (manifest, every variant, every score, every
  art direction) in **one atomic folder rename**. A draft the gate refuses is refused with the complete list of failures; the
  brain fixes and resubmits (`MAX_FIX_ROUNDS` in the prompt).

**Atomicity and the crash rule.** The only things this service writes are (1) immutable prefab versions, one `PrefabService.save`
each, under the `presentation-studio.` namespace (so the Slice 01a retention can archive an unpinned one), and (2) the
Presentation folder, published by `FilePresentationStudioStore.create` as a whole or not at all. So a crash leaves one of:
nothing; some published prefab versions that no variant pins (harmless, immutable, reported by `reconcile`, archived by the
retention when it runs); a `.staging-*` folder (swept at start). It never leaves a half-built Presentation, and nothing found
afterwards is adopted or deleted here (the Slice 16 convention: orphans are reported, never silently adopted).

**Why `PrefabService.save` and not the draft coalescer.** The Slice 01a coalescer merges a *burst of edits of the same id* (hot
reload, spoken retouches) into one version. An assembly publishes each id once, so there is nothing to merge: the coalescer would
only add its quiet period. `PrefabService.save` is the retention-aware path the coalescer itself ends in.

**Remotion (Slice 15).** The drafts this service accepts are **Remotion drafts**: a source is the generator object `{remotion: {...}}`
(`presentation_studio_authoring_remotion.py`) or a Remotion candidate, a pinned scene is a Remotion source, the Presentation is created with
engine `remotion`. An HTML (Slidecar) source or pin is `prefab_engine_mismatch`, never converted and never a fallback. Before anything is
written every Remotion source is **compiled** by the Slice 05 compiler (`tsx_compile`, diagnostics with file, line, column); a runtime that
cannot compile is a typed `presentation_studio_engine_unavailable` (409), not a degraded draft. Live Board references the sources declare are
resolved against the Boards the user works with (`authorised_boards`, derived HERE from the active Board, never from the declaration), and
an inspiration the draft names is accepted only when Core verified its upstream provenance (`derived_from` records the lineage).

**Actor.** The body carries `actor` (`user` | `brain`); it is written as the creator of the variants. The Control Center relay
forces `user`; `brain` reaches Core only through the tool layer of Slice 21 (the same rule as the edit API).

**Required Slice 09 / Slice 12 hand-offs, honoured here.** `require_art_directions` runs on the documents about to be stored
(before) and `PresentationStudioService.require_art_direction` on what was stored (after): a serious draft never leaves this
service without a DA that resolves.

Diagnostics (`core.presentation_studio.authoring_*`; ids, codes, counts, never the brain's text): the normal path at `info`, a refused
draft at `info` with its codes, an unreferenced prefab version left by a failed assembly at `warning`, a fault at `error`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field
import hashlib
import time
from typing import Any, Protocol

from jarvis.core.prefab_service import annotate_provenance
from jarvis.domain.prefab import CreatorActor, PrefabManifest, PrefabRef, canonical_json, parse_remotion_bundle
from jarvis.domain.presentation_live_refs import LIVE_REFS_PATH, LiveRef, LiveRefError, parse_declaration
from jarvis.domain.presentation_studio_engine import Engine
from jarvis.domain.remotion_compile import CompileErrorCode, RemotionCompileError
from jarvis.domain.remotion_source import EnginePin
from jarvis.domain.presentation_studio_art_direction import parse_art_direction
from jarvis.domain.presentation_studio_authoring import (
    BUNDLE_NAMESPACE, AuthoringBrief, PresentationDraft, Problem, Workflow, parse_brief, parse_draft, safe_text,
)
from jarvis.domain.presentation_studio_authoring_finalize import NOT_JUDGED, draft_from_stored, manifests_by_scene
from jarvis.domain.presentation_studio_score import parse_score
from jarvis.domain.presentation_studio_authoring_build import (
    BuildFailure, BuiltPresentation, build_presentation, provisional_pins, require_art_directions, validate_built,
)
from jarvis.domain.presentation_studio_authoring_gate import QualityReport, check_first_draft, finding_from_problem
from jarvis.domain.presentation_studio import is_presentation_id, is_variant_id
from jarvis.domain.presentation_studio_checks import (
    PresentationStudioError, PresentationStudioErrorCode as C, _exact_keys, _fail, clip,
)
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode

#: Deterministic stop points for the real kill drills (`Popen.kill()`): called with the step that has just been done.
Checkpoint = Callable[[str], None]
#: Wall-clock budget of the compilations of one draft (the compiler itself bounds each at 60 s): past it the remaining sources are
#: reported as not compiled, which blocks, instead of holding the request for 16 times the bound.
COMPILE_BUDGET_S = 100.0
MAX_DIAGNOSTIC_TEXT = 240
ACTORS = frozenset({"user", "brain"})
#: Ids one catalogue search can report (`PrefabService.MAX_SEARCH_LIMIT`).
ORPHAN_SEARCH_LIMIT = 50
MAX_REPORTED = 20
ENGINE_MISMATCH_BUNDLE = ("an HTML source is a Slidecar source, and Slidecar is the user's experiment: write the scene as a Remotion source "
                          "(`{remotion: {title, files, props, data}}`)")
ENGINE_MISMATCH_PIN = ("this scene pins an HTML (Slidecar) prefab: an agent draft pins Remotion sources only (search the library for a "
                       "Remotion source, or write one with the `remotion` generator object)")


class AuthoringPrefabs(Protocol):
    """What authoring asks the prefab authority (`jarvis.core.prefab_service.PrefabService` is the only implementation)."""

    def validate_candidate(self, candidate: object, *, core_written: bool = False) -> Any: ...

    async def save(self, candidate: object, *, actor: CreatorActor | str, derived_from: PrefabRef | None = None) -> Any: ...

    async def manifest(self, prefab_id: str, version: int) -> PrefabManifest: ...

    async def get(self, prefab_id: str, version: int | None = None) -> Any: ...

    async def remotion_source(self, prefab_id: str, version: int) -> Any: ...

    async def search(self, query: str | None = None, *, family: str | None = None, class_filter: Any = None,
                     limit: int = 20) -> Any: ...


class SceneCompiler(Protocol):
    """What authoring asks the Remotion compiler (`jarvis.adapters.remotion_compiler.RemotionCompiler`): synchronous, run in a thread."""

    def unavailable_reason(self) -> str | None: ...

    def compile_scene(self, source: Any, *, minify: bool = True) -> Any: ...


class LiveRefReader(Protocol):
    """What authoring asks the live-reference resolver (`jarvis.core.presentation_live_refs.LiveRefResolver`)."""

    async def resolve_all(self, refs: Any, *, authorised_boards: Collection[str], expected: Mapping[str, str] | None = None) -> Mapping[str, Any]: ...


PinIndex = Callable[[], Awaitable[Mapping[Any, frozenset[tuple[str, int]]]]]


@dataclass(frozen=True, slots=True)
class AuthoringOutcome:
    """What a route answers: `status` is `checked`, `refused` or `delivered`; `http_status` is 200, 400 or 201."""

    status: str
    body: Mapping[str, Any]
    http_status: int

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, **self.body}


@dataclass(slots=True)
class _Prepared:
    actor: str
    report: QualityReport
    brief: AuthoringBrief | None = None
    draft: PresentationDraft | None = None
    built: BuiltPresentation | None = None
    #: Manifests of the existing pins the scenes name, by `(id, version)` (the draft bundles are not here: they have no version yet).
    pinned: dict[tuple[str, int], PrefabManifest] = field(default_factory=dict)
    digests: dict[str, str] = field(default_factory=dict)
    #: One row per compiled source (`key`, `cache_key`, `reused`, `duration_ms`): what the delivered provenance reports.
    compiled: list[dict[str, Any]] = field(default_factory=list)
    #: The reason the engine cannot judge a Remotion draft at all (no compiler, runtime not ready): a 409, not a quality finding.
    engine_unavailable: str | None = None
    #: Inspirations Core confirmed, by bundle key: `{id, version, upstream, license, commit}` (provenance, never content).
    inspirations: dict[str, dict[str, Any]] = field(default_factory=dict)
    skipped: tuple[str, ...] = ()


def parse_request(raw: object) -> tuple[str, object, object]:
    """`{actor?, brief, draft}` -> `(actor, brief, draft)`; the two payloads are parsed by the domain, with every problem collected."""

    try:
        data = _exact_keys(raw, "authoring request", {"brief", "draft"}, frozenset({"actor"}))
    except PresentationStudioError as exc:
        raise PresentationStudioError(exc.code, safe_text(exc.message)) from None     # an unknown key name is the author's text
    actor = data.get("actor", "user")
    if actor not in ACTORS:
        raise _fail("actor must be user or brain")
    return actor, data["brief"], data["draft"]


def parse_finalize(raw: object) -> tuple[str, str, str, bool]:
    """`{presentation_id, variant_id, actor?, activate?}` -> `(presentation_id, variant_id, actor, activate)`."""

    try:
        data = _exact_keys(raw, "finalize request", {"presentation_id", "variant_id"}, frozenset({"actor", "activate"}))
    except PresentationStudioError as exc:
        raise PresentationStudioError(exc.code, safe_text(exc.message)) from None
    actor, activate = data.get("actor", "user"), data.get("activate", True)
    if actor not in ACTORS:
        raise _fail("actor must be user or brain")
    if type(activate) is not bool:
        raise _fail("activate must be true or false")
    if not is_presentation_id(data["presentation_id"]):
        raise PresentationStudioError(C.UNKNOWN_PRESENTATION, "unknown presentation id")
    if not is_variant_id(data["variant_id"]):
        raise PresentationStudioError(C.UNKNOWN_VARIANT, "unknown variant id")
    return data["presentation_id"], data["variant_id"], actor, activate


def _digest(value: object) -> str:
    try:
        return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:16]
    except (TypeError, ValueError):
        return "unhashable"


def _problem_report(workflow: Workflow | None, problems: list[Problem], *, stage: str, declared: str | None = None,
                    strict: bool = False) -> QualityReport:
    """The report of a submission that could not be judged further. `workflow` `None`: the brief was refused, the levels are the
    `directed` ones and the report says what the author declared."""

    levels = workflow or Workflow.DIRECTED
    findings = tuple(f for f in (finding_from_problem(p, levels, strict) for p in problems) if f is not None)
    return QualityReport(workflow, findings, (), {}, {}, len({f.code for f in findings}), stage, declared)


class PresentationStudioAuthoring:
    """Voir l'en-tête du module. `studio` : `PresentationStudioService` ; `prefabs` : `PrefabService` ; `variants` (optionnel) :
    `PresentationStudioVariants`, pour le contrôle de graphe après livraison ; `pins` : `PresentationStudioVariants.pin_index`."""

    def __init__(self, studio: Any, prefabs: AuthoringPrefabs, *, variants: Any | None = None, pins: PinIndex | None = None,
                 checkpoint: Checkpoint | None = None, registry: Any | None = None, compiler: SceneCompiler | None = None,
                 engine_pin: Callable[[], EnginePin] | None = None, live_refs: LiveRefReader | None = None,
                 boards: Callable[[], Awaitable[Collection[str]]] | None = None) -> None:
        #: Slice 15. `compiler` : the Remotion compiler (absent: a Remotion draft is `engine_unavailable`); `engine_pin` : the engine set the
        #: generated sources declare (absent: the generator object is refused); `live_refs` + `boards` : the resolver and the Boards the user
        #: works with (absent: a draft with live references cannot be judged, said in `skipped`, and the references block as unresolved).
        self._compiler = compiler
        self._engine_pin = engine_pin
        self._live_refs = live_refs
        self._boards = boards
        #: `registry` : `StudioPinRegistry` (Slice 06). `reconcile` asks it, so "unreferenced" means held by NO pin source (variant
        #: documents live and archived, undo stacks, live windows, in-flight holds), the same definition that retention uses.
        self._registry = registry
        self._studio = studio
        self._prefabs = prefabs
        self._variants = variants
        self._pins = pins
        self._checkpoint = checkpoint

    def _pause(self, step: str) -> None:
        if self._checkpoint is not None:
            self._checkpoint(step)

    # ------------------------------------------------------------ dry run

    async def check(self, raw: object) -> AuthoringOutcome:
        """The quality report of a submission; writes and publishes nothing."""

        return await self._studio.guarded("authoring_check", None, self._check(raw))

    async def _check(self, raw: object) -> AuthoringOutcome:
        prepared = await self._prepare(raw)
        report = prepared.report
        self._trace("core.presentation_studio.authoring_checked", "Brouillon verifie (rien n'est ecrit)",
                    data=self._report_data(report))
        return AuthoringOutcome("checked", {"ok": report.ok, "workflow": report.workflow_name, "report": report.to_dict()}, 200)

    # ------------------------------------------------------------ assembly

    async def assemble(self, raw: object) -> AuthoringOutcome:
        """Delivers the whole Presentation in one transaction, or refuses with the full report and writes nothing."""

        return await self._studio.guarded("authoring_assemble", None, self._assemble(raw))

    async def _assemble(self, raw: object) -> AuthoringOutcome:
        prepared = await self._prepare(raw)
        report, brief, draft, built = prepared.report, prepared.brief, prepared.draft, prepared.built
        if prepared.engine_unavailable is not None:
            self._trace("core.presentation_studio.authoring_engine_unavailable", "Brouillon Remotion non juge: le compilateur est indisponible",
                        level="warning", data={**self._report_data(report), "reason": prepared.engine_unavailable[:160]})
            return AuthoringOutcome("refused", {"workflow": report.workflow_name, "report": report.to_dict(), "error": {
                "code": C.ENGINE_UNAVAILABLE.value,
                "message": clip(f"the Remotion engine cannot compile this draft ({prepared.engine_unavailable}); nothing was written and no other "
                                "engine takes over: repair Remotion, then resubmit")}}, 409)
        if not report.ok or brief is None or draft is None or built is None:
            self._trace("core.presentation_studio.authoring_refused", "Brouillon refuse par la porte de qualite",
                        data=self._report_data(report))
            codes = sorted({f.code for f in report.failures})
            message = f"{len(report.failures)} blocking finding(s) ({', '.join(codes[:8])}): fix them all, then resubmit"
            return AuthoringOutcome("refused", {"workflow": report.workflow_name, "report": report.to_dict(),
                                                "error": {"code": C.DRAFT_REFUSED.value, "message": clip(message)}}, 400)
        serious = brief.workflow.serious
        require_art_directions(built, serious=serious)
        await self._studio.require_room()          # a full store is refused before anything is published
        self._pause("validated")
        published: list[dict[str, Any]] = []
        try:
            pins = await self._publish(draft, prepared.actor, published)
            final = await self._build_final(prepared, pins)
            documents = final.documents()
            self._pause("documents_ready")
            await self._studio.create_assembled(
                final.presentation.presentation_id, documents.manifest, documents.variants, documents.scores,
                documents.art_directions)
            self._pause("created")
        except BaseException as exc:
            self._warn_unreferenced(published, exc)
            if isinstance(exc, BuildFailure):
                raise _fail("the assembled documents are not valid: " + "; ".join(p.message for p in exc.problems[:3])) from exc
            raise
        pid = final.presentation.presentation_id
        await self._verify(final, serious=serious)
        self._trace("core.presentation_studio.authoring_delivered", "Presentation livree en une transaction",
                    data={"presentation_id": pid, "workflow": brief.workflow.value, "variants": len(final.variants),
                          "scenes": len(draft.scenes), "bundles": len(published), "warnings": len(report.warnings),
                          "engine": final.presentation.engine.value, "compiled": len(prepared.compiled),
                          "inspirations": len(prepared.inspirations)})
        return AuthoringOutcome("delivered", self._delivered(prepared, final, published), 201)

    async def _publish(self, draft: PresentationDraft, actor: str, published: list[dict[str, Any]]) -> dict[str, PrefabRef]:
        pins: dict[str, PrefabRef] = {}
        for index, bundle in enumerate(draft.bundles, start=1):
            try:
                publication = await self._prefabs.save(bundle.candidate, actor=CreatorActor(actor), derived_from=bundle.inspiration)
            except PrefabStoreError as exc:
                fault = exc.code is PrefabStoreErrorCode.STORAGE_IO
                raise PresentationStudioError(
                    C.STORAGE_IO if fault else C.PREFAB_UNAVAILABLE,
                    f"bundle {bundle.key}: publishing refused ({exc.code.value}): {exc.message}", warn=not fault) from exc
            pins[bundle.key] = PrefabRef(publication.prefab_id, publication.version)
            published.append({"key": bundle.key, "id": publication.prefab_id, "version": publication.version,
                              "fingerprint": publication.fingerprint,
                              # an id the Studio already had: a new immutable version of it, earlier presentations keep their pin
                              "revision": publication.provenance.origin.value == "revision",
                              "origin": publication.provenance.origin.value})
            self._pause(f"published:{index}")
        return pins

    async def _build_final(self, prepared: _Prepared, pins: Mapping[str, PrefabRef]) -> BuiltPresentation:
        """The documents with the REAL pins, judged again against the REAL manifests (the published ones, read back)."""

        assert prepared.brief is not None and prepared.draft is not None
        manifests = dict(prepared.pinned)
        for pin in pins.values():
            manifests[(pin.prefab_id, pin.version)] = await self._manifest(pin.prefab_id, pin.version)
        final = build_presentation(prepared.brief, prepared.draft, pins, self._studio.now(), prepared.actor, Engine.REMOTION)
        problems = validate_built(final, manifests)
        if problems:
            raise BuildFailure(tuple(problems))
        require_art_directions(final, serious=prepared.brief.workflow.serious)
        return final

    async def _manifest(self, prefab_id: str, version: int) -> PrefabManifest:
        try:
            return await self._prefabs.manifest(prefab_id, version)
        except PrefabStoreError as exc:
            fault = exc.code is not PrefabStoreErrorCode.UNKNOWN_PREFAB and exc.code is not PrefabStoreErrorCode.UNKNOWN_VERSION
            raise PresentationStudioError(C.STORAGE_IO if exc.code is PrefabStoreErrorCode.STORAGE_IO else C.PREFAB_UNAVAILABLE,
                                          f"{prefab_id}@{version}: {exc.code.value}: {exc.message}", warn=not fault) from exc

    async def _verify(self, final: BuiltPresentation, *, serious: bool) -> None:
        """Reads the stored result back (disk only): the folder parses, every variant resolves its DA (Slice 09), every score resolves."""

        pid = final.presentation.presentation_id
        try:
            await self._studio.get(pid)
            for item in final.variants:
                vid = item.variant.variant_id
                await self._studio.require_art_direction(pid, vid, serious=serious)
                stored = await self._studio.get_score(pid, vid)
                if stored["problems"]:
                    raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"stored score of {vid} does not resolve")
            if self._variants is not None:
                report = await self._variants.check(pid)
                if not report.get("clean", False):
                    raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"stored graph of {pid} is not clean")
        except PresentationStudioError as exc:
            raise PresentationStudioError(
                C.STORAGE_IO, f"presentation {pid} was stored but failed its read-back ({exc.code.value}): {exc.message}; "
                              "the folder is left in place, nothing was deleted") from exc

    # ------------------------------------------------------------ finalize: the directed gate on a stored variant

    async def finalize(self, raw: object) -> AuthoringOutcome:
        """Re-gates a stored variant (typically an exploratory candidate) as `directed`; on success it can become the active variant. The
        only gated way to adopt a draft candidate: nothing about a plain `activate` changes (that stays the user's own choice)."""

        return await self._studio.guarded("authoring_finalize", None, self._finalize(raw))

    async def _finalize(self, raw: object) -> AuthoringOutcome:
        pid, vid, actor, activate = parse_finalize(raw)
        view = await self._studio.get(pid)
        variant = next((v for v in view.variants if v.variant_id == vid), None)
        if variant is None:
            raise PresentationStudioError(C.UNKNOWN_VARIANT, f"{vid} is not a live variant of this presentation")
        self._studio.refuse_if_reloading(pid, variant)       # Slice 06: never judge or activate a variant mid-reload (409)
        stored = await self._studio.get_score(pid, vid)
        if stored["problems"]:
            raise PresentationStudioError(C.SCORE_INCOMPATIBLE, f"the stored score does not resolve in the variant: {len(stored['problems'])} problem(s)")
        score = parse_score(stored["score"])
        try:
            art = parse_art_direction((await self._studio.get_art_direction(pid, vid))["art_direction"])
        except PresentationStudioError as exc:
            if exc.code is not C.UNKNOWN_ART_DIRECTION:
                raise
            art = None
        manifests: dict[tuple[str, int], PrefabManifest] = {}
        problems: list[Problem] = []
        sources = []
        for scene in variant.scenes:
            pin = (scene.prefab.prefab_id, scene.prefab.version)
            if pin in manifests:
                continue
            try:
                manifests[pin] = await self._manifest(*pin)
            except PresentationStudioError as exc:
                if exc.code is C.STORAGE_IO:
                    raise
                problems.append(Problem("pin_unknown", f"scene:{scene.scene_id}", exc.message))
                continue
            if pin[0].startswith(BUNDLE_NAMESPACE):
                parsed = (await self._prefabs.get(*pin)).entry.bundle          # the stored sources: no frame runtime needed
                if parsed is not None and parsed.is_remotion and not parsed.holds_bytes:
                    # The catalogue keeps a Remotion version's manifest and inventory only: the gate reads its bytes (re-checked by the
                    # prefab authority against the inventory, and by the Slice 06 guards).
                    try:
                        source = await self._prefabs.remotion_source(*pin)
                    except PrefabStoreError as exc:
                        problems.append(Problem("pin_unknown", f"scene:{pin[0]}@{pin[1]}", f"the stored source is not readable ({exc.code.value})"))
                        continue
                    parsed = parse_remotion_bundle(manifests[pin].raw, source.files)
                sources.append((f"{pin[0]}@{pin[1]}", {"manifest": dict(parsed.manifest.raw), **parsed.files()}, parsed))
        draft, brief, built = draft_from_stored(view.presentation, variant, score, art, sources)
        report = await asyncio.to_thread(
            check_first_draft, draft, brief, manifests_by_scene(variant, manifests), built, problems=tuple(problems),
                                   not_judged=NOT_JUDGED)
        base = {"presentation_id": pid, "variant_id": vid, "report": report.to_dict()}
        if not report.ok:
            self._trace("core.presentation_studio.authoring_refused", "Variante refusee a la finalisation", data=self._report_data(report))
            codes = sorted({f.code for f in report.failures})
            return AuthoringOutcome("refused", {**base, "error": {
                "code": C.DRAFT_REFUSED.value,
                "message": clip(f"{len(report.failures)} blocking finding(s) ({', '.join(codes[:8])}): fix the variant, then finalize again")}}, 400)
        activated = False
        if activate and self._variants is not None and view.presentation.active_variant_id != vid:
            await self._variants.switch(pid, vid, {"actor": actor})
            activated = True
        self._trace("core.presentation_studio.authoring_finalized", "Variante finalisee (porte directed)",
                    data={"presentation_id": pid, "variant_id": vid, "activated": activated, "warnings": len(report.warnings)})
        return AuthoringOutcome("finalized", {**base, "activated": activated}, 200)

    # ------------------------------------------------------------ preparation (shared by check and assemble)

    async def _prepare(self, raw: object) -> _Prepared:
        actor, brief_raw, draft_raw = parse_request(raw)
        try:
            brief = parse_brief(brief_raw)
        except PresentationStudioError as exc:
            declared = brief_raw.get("workflow") if isinstance(brief_raw, dict) else None
            declared = declared if declared in {w.value for w in Workflow} else None
            problems = [Problem("brief_invalid", "brief", exc.message)]
            return _Prepared(actor, _problem_report(None, problems, stage="brief", declared=declared))
        digests = {"brief": _digest(brief_raw), "draft": _digest(draft_raw)}
        try:
            parsed = parse_draft(draft_raw, brief, self._engine_pin() if self._engine_pin is not None else None)
        except (OverflowError, RecursionError, ValueError, TypeError, MemoryError) as exc:   # net behind scan_json: never a 500
            problem = Problem("draft_schema", "draft", f"the draft could not be analysed ({type(exc).__name__})")
            return _Prepared(actor, _problem_report(brief.workflow, [problem], stage="schema", strict=brief.strict_content), brief,
                             digests=digests)
        if parsed.draft is None:
            if parsed.partial is not None:
                report = check_first_draft(parsed.partial, brief, None, None, problems=tuple(parsed.problems), partial=True)
            else:
                report = _problem_report(brief.workflow, list(parsed.problems), stage="schema", strict=brief.strict_content)
            return _Prepared(actor, report, brief, digests=digests)
        draft = parsed.draft
        problems: list[Problem] = []
        by_bundle = self._check_bundles(draft, problems)
        manifests: dict[str, PrefabManifest] = {}
        pinned: dict[tuple[str, int], PrefabManifest] = {}
        for scene in draft.scenes:
            if scene.bundle_key is not None:
                manifests[scene.key] = by_bundle[scene.bundle_key]
                continue
            pin = scene.scene.prefab
            manifest = pinned.get((pin.prefab_id, pin.version))
            if manifest is None:
                try:
                    manifest = await self._manifest(pin.prefab_id, pin.version)
                except PresentationStudioError as exc:
                    if exc.code is C.STORAGE_IO:
                        raise
                    problems.append(Problem("pin_unknown", f"scene:{scene.key}", exc.message))
                    continue
                pinned[(pin.prefab_id, pin.version)] = manifest
            if manifest.source is None:
                problems.append(Problem("prefab_engine_mismatch", f"scene:{scene.key}", ENGINE_MISMATCH_PIN))
            manifests[scene.key] = manifest
        extra: list[Problem] = []
        prepared = _Prepared(actor, None, brief, draft, None, pinned, digests)           # type: ignore[arg-type] - report set below
        if not problems:
            await self._remotion_checks(draft, extra, prepared)
        built: BuiltPresentation | None = None
        if not problems:
            try:
                built, more = self._provisional(brief, draft, pinned, by_bundle, actor)
            except (OverflowError, RecursionError, ValueError, TypeError) as exc:     # net: never a 500 on a hostile number
                built, more = None, [Problem("draft_schema", "draft", f"the draft could not be assembled ({type(exc).__name__})")]
            problems.extend(more)
        # Off the event loop: the gate reads author-controlled text (the lint is linear and has its own budget; this keeps Core responsive anyway).
        report = await asyncio.to_thread(check_first_draft, draft, brief, manifests, built, problems=(*problems, *extra), skipped=prepared.skipped)
        prepared.report, prepared.built = report, built if not problems else None
        return prepared

    # ------------------------------------------------------------ Remotion checks (Slice 15)

    async def _remotion_checks(self, draft: PresentationDraft, problems: list[Problem], prepared: _Prepared) -> None:
        """Compile every Remotion source, resolve its live Board references, confirm its inspiration. All problems are collected (the
        brain fixes them in one round); none of this writes anything."""

        await self._compile(draft, problems, prepared)
        await self._resolve_live_refs(draft, problems, prepared)
        await self._confirm_inspirations(draft, problems, prepared)

    async def _compile(self, draft: PresentationDraft, problems: list[Problem], prepared: _Prepared) -> None:
        sources = [b for b in draft.bundles if b.is_remotion]
        if not sources:
            return
        reason = "no Remotion compiler is configured on this Core" if self._compiler is None else self._compiler.unavailable_reason()
        if reason:
            prepared.engine_unavailable = reason
            problems.append(Problem("tsx_compile", "draft", f"{CompileErrorCode.RUNTIME_UNAVAILABLE.value}: {reason}"[:300]))
            return
        assert self._compiler is not None
        deadline = time.monotonic() + COMPILE_BUDGET_S
        for bundle in sources:
            where = f"bundle:{bundle.key}"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                problems.append(Problem("tsx_compile_budget", where, "compile budget exhausted: this source was not compiled, send fewer sources"))
                continue
            try:
                # Bounded by what is LEFT of the budget (the typed client waits `AUTHORING_TIMEOUT_S`, above it): never a compile that outlives the request.
                artifact = await asyncio.wait_for(asyncio.to_thread(self._compiler.compile_scene, bundle.bundle.remotion_source()), remaining)
            except TimeoutError:
                problems.append(Problem("tsx_compile_budget", where, f"this source was still compiling when the {COMPILE_BUDGET_S:g} s budget ended: "
                                                                     "send fewer or smaller sources"))
                continue
            except RemotionCompileError as exc:
                rows = tuple({"file": d.file, "line": d.line, "column": d.column, "text": " ".join(str(d.text).split())[:MAX_DIAGNOSTIC_TEXT]}
                             for d in exc.diagnostics[:10])
                if exc.code is CompileErrorCode.RUNTIME_UNAVAILABLE:
                    prepared.engine_unavailable = exc.message
                problems.append(Problem("tsx_compile", where, f"{exc.code.value}: {exc.message}", rows))
                self._trace("core.presentation_studio.authoring_compile_refused", "Source Remotion refusee a la compilation", level="info",
                            data={"bundle": bundle.key, "code": exc.code.value, "diagnostics": len(rows)})
                continue
            except Exception as exc:  # noqa: BLE001 - argued: a compiler fault is reported as a typed finding and logged at error, never a 500 or a silent pass
                problems.append(Problem("tsx_compile", where, f"{CompileErrorCode.COMPILER_FAILED.value}: the compiler failed ({type(exc).__name__})"))
                self._trace("core.presentation_studio.authoring_compile_failed", "Echec du compilateur Remotion", level="error",
                            data={"bundle": bundle.key, "error": type(exc).__name__})
                continue
            public = artifact.to_public() if hasattr(artifact, "to_public") else {}
            prepared.compiled.append({"key": bundle.key, "cache_key": public.get("cache_key"), "reused": bool(public.get("reused")),
                                      "duration_ms": public.get("duration_ms"), "bytes": sum(f.get("bytes", 0) for f in public.get("files", []))})
        self._trace("core.presentation_studio.authoring_compiled", "Sources Remotion compilees avant ecriture", data={
            "sources": len(sources), "compiled": len(prepared.compiled), "refused": len(sources) - len(prepared.compiled),
            "reused": sum(1 for row in prepared.compiled if row["reused"])})

    async def _resolve_live_refs(self, draft: PresentationDraft, problems: list[Problem], prepared: _Prepared) -> None:
        """Each source's `src/live-refs.json` against the Boards the user works with. Default deny: with no resolver or no Board context the
        references are reported as unresolved (never assumed fine)."""

        declared: list[tuple[str, tuple[LiveRef, ...]]] = []
        for bundle in draft.bundles:
            if not bundle.is_remotion or LIVE_REFS_PATH not in bundle.bundle.sources:
                continue
            try:
                refs = parse_declaration(bundle.bundle.sources[LIVE_REFS_PATH])
            except LiveRefError:
                continue                                       # the gate reports tsx_live_ref_invalid
            if refs:
                declared.append((bundle.key, refs))
        if not declared:
            return
        if self._live_refs is None or self._boards is None:
            prepared.skipped = (*prepared.skipped, "tsx_live_ref_unresolved")
            problems.extend(Problem("tsx_live_ref_unresolved", f"bundle:{key}",
                                    f"{len(refs)} live reference(s) cannot be checked: this Core has no Board context to authorise them")
                            for key, refs in declared)
            return
        authorised = frozenset(await self._boards())
        for key, refs in declared:
            resolved = await self._live_refs.resolve_all(refs, authorised_boards=authorised)
            bad = [(name, getattr(item.state, "value", str(item.state))) for name, item in resolved.items() if not item.usable]
            if bad:
                problems.append(Problem("tsx_live_ref_unresolved", f"bundle:{key}", "live reference(s) not usable: " + ", ".join(
                    f"{name} ({state})" for name, state in bad[:6])))
        self._trace("core.presentation_studio.authoring_live_refs", "References vivantes de Board verifiees", data={
            "sources": len(declared), "references": sum(len(refs) for _, refs in declared), "authorised_boards": len(authorised)})

    async def _confirm_inspirations(self, draft: PresentationDraft, problems: list[Problem], prepared: _Prepared) -> None:
        """An inspiration is an existing Remotion source whose upstream Core verified (Slice 18). Nothing is copied and nothing is chosen
        for the author: the draft names it, Core confirms it exists and is attested, and the lineage is recorded."""

        for bundle in draft.bundles:
            ref = bundle.inspiration
            if ref is None:
                continue
            where = f"bundle:{bundle.key}"
            try:
                detail = await self._prefabs.get(ref.prefab_id, ref.version)
            except PrefabStoreError as exc:
                problems.append(Problem("tsx_inspiration_unconfirmed", where, f"the inspiration is not readable ({exc.code.value})"))
                continue
            found = detail.entry.bundle
            if found is None or not found.is_remotion:
                problems.append(Problem("tsx_inspiration_unconfirmed", where, "the inspiration is not a Remotion source"))
                continue
            view = found.manifest.catalog_view(parameters=False)
            annotate_provenance(view, found, detail.siblings)
            upstream = view.get("upstream")
            if not isinstance(upstream, dict) or not upstream.get("commit"):
                problems.append(Problem("tsx_inspiration_unconfirmed", where,
                                        "the inspiration has no Core-verified upstream provenance: import the template first (an upstream "
                                        "template is optional inspiration only when its provenance is confirmed)"))
                continue
            prepared.inspirations[bundle.key] = {
                "id": ref.prefab_id, "version": ref.version, "upstream": upstream.get("name"), "commit": upstream.get("commit"),
                "license": upstream.get("license") or view.get("license"), "verified_intact": bool(upstream.get("verified_intact"))}

    def _check_bundles(self, draft: PresentationDraft, problems: list[Problem]) -> dict[str, PrefabManifest]:
        """Namespace, one bundle per id, and the prefab authority's own verdict (`PrefabService.validate_candidate`)."""

        manifests: dict[str, PrefabManifest] = {}
        seen: dict[str, str] = {}
        for bundle in draft.bundles:
            where = f"bundle:{bundle.key}"
            if not bundle.prefab_id.startswith(BUNDLE_NAMESPACE):
                problems.append(Problem("prefab_namespace", where,
                                        f"a published source lives under {BUNDLE_NAMESPACE!r} (retention-aware), not {bundle.prefab_id!r}"))
            if bundle.prefab_id in seen:
                problems.append(Problem("prefab_invalid", where, f"bundles {seen[bundle.prefab_id]!r} and {bundle.key!r} share one prefab id"))
            seen[bundle.prefab_id] = bundle.key
            if not bundle.is_remotion:
                problems.append(Problem("prefab_engine_mismatch", where, ENGINE_MISMATCH_BUNDLE))
            verdict = self._prefabs.validate_candidate(bundle.candidate, core_written=True)
            if not verdict.ok:
                problems.append(Problem("prefab_invalid", where, "; ".join(verdict.errors[:2]) or "refused by the prefab authority"))
            manifests[bundle.key] = bundle.bundle.manifest
        return manifests

    def _provisional(self, brief: AuthoringBrief, draft: PresentationDraft, pinned: Mapping[tuple[str, int], PrefabManifest],
                     by_bundle: Mapping[str, PrefabManifest], actor: str) -> tuple[BuiltPresentation | None, list[Problem]]:
        """The documents with the candidates' own pins, validated against the manifests; nothing is published for this."""

        manifests = dict(pinned)
        for manifest in by_bundle.values():
            manifests[(manifest.prefab_id, manifest.version)] = manifest
        try:
            built = build_presentation(brief, draft, provisional_pins(draft), self._studio.now(), actor, Engine.REMOTION)
        except BuildFailure as exc:
            return None, list(exc.problems)
        return built, validate_built(built, manifests)

    # ------------------------------------------------------------ results and reports

    def _delivered(self, prepared: _Prepared, final: BuiltPresentation, published: list[dict[str, Any]]) -> dict[str, Any]:
        brief, draft = prepared.brief, prepared.draft
        assert brief is not None and draft is not None
        entries = {e.variant_id: e for e in final.presentation.variants}
        variants = [{"variant_id": b.variant.variant_id, "variant_number": b.variant.variant_number, "title": b.variant.title,
                     "parent_variant_id": b.variant.parent_variant_id, "art_direction_id": b.variant.art_direction_id,
                     "score_id": b.variant.score_id, "draft": b.draft, "rationale": entries[b.variant.variant_id].rationale}
                    for b in final.variants]
        first = final.variants[0].variant
        scenes = [{"scene_key": final.key_of(s.scene_id), "scene_id": s.scene_id, "title": s.title,
                   "prefab": s.prefab.to_dict(), "controls": [c.control_id for c in s.controls],
                   "anchors": [a.anchor_id for a in s.anchors]} for s in first.scenes]
        provenance = {
            "workflow": brief.workflow.value, "actor": prepared.actor, "brief_digest": prepared.digests.get("brief"),
            "draft_digest": prepared.digests.get("draft"), "resources": len(brief.resources),
            "art_directions": [{"variant_id": b.variant.variant_id,
                                "origin": b.art.profile.provenance.origin.value if b.art else None,
                                "fallback": bool(b.art and b.art.profile.provenance.fallback),
                                "confidence": b.art.profile.provenance.confidence if b.art else None} for b in final.variants],
            "prefabs": published, "gate": {"errors": 0, "warnings": len(prepared.report.warnings)},
            "engine": final.presentation.engine.value, "compiled": prepared.compiled,
            "inspirations": [{"bundle": key, **row} for key, row in prepared.inspirations.items()]}
        return {"workflow": brief.workflow.value, "engine": final.presentation.engine.value,
                "presentation_id": final.presentation.presentation_id,
                "active_variant_id": final.presentation.active_variant_id, "variants": variants, "scenes": scenes,
                "prefabs": published, "report": prepared.report.to_dict(), "provenance": provenance}

    @staticmethod
    def _report_data(report: QualityReport) -> dict[str, Any]:
        return {"workflow": report.workflow_name, "ok": report.ok, "errors": len(report.failures),
                "warnings": len(report.warnings), "codes": sorted({f.code for f in report.findings})[:MAX_REPORTED],
                "skipped": list(report.skipped)[:MAX_REPORTED]}

    def _warn_unreferenced(self, published: list[dict[str, Any]], exc: BaseException) -> None:
        """A failure after some bundles were published: they stay (immutable, unpinned, archivable by the retention). Said, not hidden."""

        if not published:
            return
        self._trace("core.presentation_studio.authoring_unreferenced",
                    "Assemblage interrompu: des versions de prefab publiees ne sont epinglees par aucune variante (inoffensives, rapportees)",
                    level="warning", data={"prefabs": [f"{p['id']}@{p['version']}" for p in published][:MAX_REPORTED],
                                           "cause": type(exc).__name__,
                                           "code": getattr(getattr(exc, "code", None), "value", None)})

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        self._studio.trace(kind, message, level=level, data=data)

    # ------------------------------------------------------------ crash report

    async def reconcile(self) -> dict[str, Any]:
        """A report, after a crash or at any time: prefab versions under `presentation-studio.` that no variant pins, and the
        Presentation folders that cannot be read. **Reads only**: nothing is adopted, archived or deleted (the retention archives
        an unpinned version on its own schedule; a damaged folder is left for the owner, `docs/OPERATIONS.md`)."""

        listing = await self._studio.list_presentations()
        pinned: set[tuple[str, int]] | None = None
        if self._pins is not None:
            index = await self._pins()
            pinned = {pin for pins in index.values() for pin in pins}
        found = await self._prefabs.search(BUNDLE_NAMESPACE, class_filter="custom", limit=ORPHAN_SEARCH_LIMIT)
        versions = [(row.prefab_id, v) for row in found if row.prefab_id.startswith(BUNDLE_NAMESPACE) for v in row.versions]
        if pinned is not None and self._registry is not None:
            try:
                held = await self._registry.pinned_versions(sorted({i for i, _ in versions}))
                pinned |= {(i, v) for i, vs in held.items() for v in vs}
            except RuntimeError:
                pinned = None                                  # the registry is closed: pins unknown, nothing is claimed
        unreferenced = [] if pinned is None else [{"id": i, "version": v} for i, v in versions if (i, v) not in pinned]
        report = {"pins_known": pinned is not None, "studio_prefab_versions": len(versions),
                  "unreferenced_prefabs": unreferenced[:MAX_REPORTED], "unreferenced_count": len(unreferenced),
                  "truncated": len(found) >= ORPHAN_SEARCH_LIMIT,
                  "unreadable_presentations": [dict(p) for p in listing.problems]}
        self._trace("core.presentation_studio.authoring_reconciled", "Rapport de reprise de l'assemblage",
                    level="warning" if unreferenced or listing.problems else "info",
                    data={"unreferenced": len(unreferenced), "unreadable": len(listing.problems), "pins_known": pinned is not None})
        return report
