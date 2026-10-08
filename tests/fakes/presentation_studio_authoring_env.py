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
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.package, self.data, self.studio_root = self.root / "pkg", self.root / "data", self.root / "studio"
        for folder in (self.package, self.data, self.studio_root):
            folder.mkdir(parents=True, exist_ok=True)
        if not (self.package / "jarvis.counter").exists():           # a second stack on the same root (a restart) reuses the library
            install_version(self.package, "jarvis.counter", title="Base")
            install_version(self.data / LIBRARY_DIR, "lab.counter", 1)
        self.sink = Sink()
        self.clock = Clock()
        self.prefabs = PrefabService(FilePrefabLibrary(self.package, self.data), diagnostics=self.sink)
        self.studio: PresentationStudioService
        self.variants: PresentationStudioVariants
        self.authoring: PresentationStudioAuthoring

    async def start(self, *, checkpoint=None, store=None) -> "AuthoringEnv":
        await self.prefabs.start()
        self.studio = PresentationStudioService(store or FilePresentationStudioStore(self.studio_root), diagnostics=self.sink,
                                                clock=self.clock, prefabs=self.prefabs)
        self.variants = PresentationStudioVariants(self.studio, diagnostics=self.sink, secret=b"k" * 32)
        self.authoring = PresentationStudioAuthoring(self.studio, self.prefabs, variants=self.variants,
                                                     pins=self.variants.pin_index, checkpoint=checkpoint)
        return self

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
