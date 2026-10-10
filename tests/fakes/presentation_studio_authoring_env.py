"""A real Core-side stack for the authoring planner tests: real `PrefabService` over a file library, real file store, real services.

`AuthoringEnv(root)` lays out `<root>/pkg` (the prefab package root, `lab.counter` installed as a pinnable existing prefab),
`<root>/data` (prefab data root) and `<root>/studio` (the Presentation store). Paths are kept short on purpose: the store refuses a
file path above the Windows limit (259), and a pytest `tmp_path` is already long.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.prefab_service import PrefabService
from jarvis.core.presentation_studio_authoring import PresentationStudioAuthoring
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.core.presentation_studio_variants import PresentationStudioVariants
from tests.fakes.prefabs import install_version
from tests.fakes.remotion_authoring import ScriptedCompiler, ScriptedLiveRefs, engine_pin


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, dict[str, Any]]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.rows.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[tuple[str, dict[str, Any]]]:
        return [(level, data) for k, level, data in self.rows if k == kind]


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class AuthoringEnv:
    def __init__(self, root: Path, *, pin_registry: Any | None = None) -> None:
        self.root = Path(root)
        self.pin_registry = pin_registry          # Slice 06: the real StudioPinRegistry, as `v2_app` wires it
        self.package, self.data, self.studio_root = self.root / "pkg", self.root / "data", self.root / "studio"
        for folder in (self.package, self.data, self.studio_root):
            folder.mkdir(parents=True, exist_ok=True)
        if not (self.package / "jarvis.counter").exists():           # a second stack on the same root (a restart) reuses the library
            install_version(self.package, "jarvis.counter", title="Base")
            install_version(self.data / LIBRARY_DIR, "lab.counter", 1)
        self.sink = Sink()
        self.clock = Clock()
        self.prefabs = PrefabService(FilePrefabLibrary(self.package, self.data), diagnostics=self.sink, pin_registry=pin_registry)
        self.studio: PresentationStudioService
        self.variants: PresentationStudioVariants
        self.authoring: PresentationStudioAuthoring

    async def start(self, *, checkpoint=None, store=None, compiler: Any = "scripted", live_refs: Any = None,
                    boards: Any = None) -> "AuthoringEnv":
        """`compiler`: the Remotion compiler (default a `ScriptedCompiler`, `None` for a Core without one); `live_refs`/`boards`: the
        Board context (default none: a draft with live references cannot be judged)."""

        await self.prefabs.start()
        await self._install_remotion_library_source()
        self.sink.rows.clear()                      # the library fixture is not part of what a test observes
        self.compiler = ScriptedCompiler() if compiler == "scripted" else compiler
        self.live_refs = live_refs
        self.studio = PresentationStudioService(store or FilePresentationStudioStore(self.studio_root), diagnostics=self.sink,
                                                clock=self.clock, prefabs=self.prefabs, pins=self.pin_registry)
        self.variants = PresentationStudioVariants(self.studio, diagnostics=self.sink, secret=b"k" * 32)
        self.authoring = PresentationStudioAuthoring(self.studio, self.prefabs, variants=self.variants,
                                                     pins=self.variants.pin_index, checkpoint=checkpoint, registry=self.pin_registry,
                                                     compiler=self.compiler, engine_pin=engine_pin, live_refs=live_refs, boards=boards)
        return self

    async def assemble_legacy_html(self, brief: dict, draft: dict, *, actor: str = "user"):
        """A LEGACY Slidecar presentation, built the way the planner built it before Slice 15 (HTML scenes, engine `slidecar`), written straight
        into the store. The planner no longer does this (it refuses an HTML source); the tests of what still reads and edits HTML documents
        (hot reload of a Slidecar scene, scene variants, release flows) need one, exactly like a user's older document on disk."""

        from jarvis.domain.prefab import CreatorActor, PrefabRef
        from jarvis.domain.presentation_studio_authoring import parse_brief, parse_draft
        from jarvis.domain.presentation_studio_authoring_build import build_presentation
        from jarvis.domain.presentation_studio_engine import Engine

        parsed = parse_draft(draft, parse_brief(brief))
        assert parsed.draft is not None, parsed.problems
        pins = {}
        for bundle in parsed.draft.bundles:
            publication = await self.prefabs.save(bundle.candidate, actor=CreatorActor(actor))
            pins[bundle.key] = PrefabRef(publication.prefab_id, publication.version)
        built = build_presentation(parse_brief(brief), parsed.draft, pins, self.studio.now(), actor, Engine.SLIDECAR)
        documents = built.documents()
        if self.pin_registry is not None:
            from jarvis.core.presentation_studio_service import variant_pins
            for item in built.variants:
                self.pin_registry.register_variant(built.presentation.presentation_id, item.variant.variant_id, variant_pins(item.variant.scenes))
        self.studio._store.create(built.presentation.presentation_id, documents.manifest, documents.variants, documents.scores,
                                        documents.art_directions)
        return built

    async def _install_remotion_library_source(self) -> None:
        """`lab.remotion` v1: an existing Remotion source a draft may pin (the Remotion counterpart of the HTML `lab.counter`)."""

        from jarvis.ports.prefabs import PrefabStoreError
        from tests.fakes import presentation_studio_fake_author as fa
        try:
            await self.prefabs.manifest("lab.remotion", 1)
        except PrefabStoreError:
            await self.prefabs.save(fa.candidate(
                "lab.remotion", props={"type": "object", "properties": {"label": {"type": "string", "max_length": 60, "default": "Compteur"}}},
                data={"type": "object", "properties": {"count": {"type": "integer"}, "notes": {"type": "text", "max_length": 600}}},
                sample={"props": {}, "data": {"count": 1, "notes": "Exemple"}}), actor="user")

    async def check(self, brief: dict, draft: dict, **extra: Any):
        return await self.authoring.check({"brief": brief, "draft": draft, **extra})

    async def assemble(self, brief: dict, draft: dict, **extra: Any):
        return await self.authoring.assemble({"brief": brief, "draft": draft, **extra})

    def folders(self) -> list[str]:
        base = self.studio_root / "presentations"
        return sorted(p.name for p in base.iterdir()) if base.exists() else []

    def prefab_versions(self) -> dict[str, list[str]]:
        base = self.data / LIBRARY_DIR
        return {p.name: sorted(v.name for v in p.iterdir()) for p in base.iterdir() if p.name.startswith("presentation-studio.")} \
            if base.exists() else {}
