"""Monde de test de la promotion de modeles (jarvis-interactive-presentation-studio, Slice 20).

Vrai magasin de fichiers, vrai `PrefabService` et vraie API d'edition sous `tmp_path`. Le prefab « projet » est `lab.counter` (une scene
du projet y est epinglee) ; `hero_source` en fabrique des variantes dont la source ecrit en dur du contenu ou des references du projet.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from jarvis.adapters.file_prefab_library import LIBRARY_DIR
from jarvis.adapters.file_presentation_template_store import FilePresentationTemplateStore
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_template import PresentationStudioTemplates
from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.domain.presentation_studio_art_direction_authoring import generate_fallback_profile
from tests.fakes.prefabs import candidate, install_version
from tests.unit.test_presentation_studio_edit_service import Events
from tests.unit.test_presentation_studio_score_service import Env, S1, S2, scene_body

PROJECT_TITLE = "Atelier"
PROJECT_WORDS = ("Visiteurs", "Chiffre")  # the scene's headline and title in the shared fixture


def hero_source(*, template: str | None = None, style: str | None = None, behavior: str | None = None) -> dict:
    """La source de `lab.counter` avec, si demande, du contenu ou des references du projet ecrits en dur (la fuite a detecter)."""

    source = copy.deepcopy(candidate())
    if template is not None:
        source["template"] = template
    if style is not None:
        source["style"] = style
    if behavior is not None:
        source["behavior"] = behavior
    return source


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.env = Env(tmp_path)

    async def open(self, scenes=(S1, S2), *, sources: dict[str, dict] | None = None, scene_prefab: str = "lab.counter",
                   art: bool = True, props: dict | None = None, extra_versions: tuple[int, ...] = (), bodies=None):
        for prefab_id, source in (sources or {}).items():
            install_version(self.env.data / LIBRARY_DIR, prefab_id, 1, source=source)
        for version in extra_versions:
            install_version(self.env.data / LIBRARY_DIR, "lab.counter", version)
        self.studio = await self.env.service()
        self.sink = self.env.sink
        self.edit = PresentationStudioEditService(self.studio, diagnostics=self.sink, events=Events(),
                                                  new_id=lambda: "pss_0000000000f1")
        self.store = FilePresentationTemplateStore(self.env.root)
        self.templates = self.service()
        if bodies is None:
            bodies = [scene_body(s) for s in scenes]
            for body in bodies:
                body["prefab"] = {"id": scene_prefab, "version": 1}
                body["props"] = {**body["props"], **(props or {})}
        view = await self.studio.create({"title": PROJECT_TITLE})
        self.pid, self.vid = view.presentation.presentation_id, view.presentation.active_variant_id
        variant = await self.studio.get_variant(self.pid, self.vid)
        await self.studio.save_variant(self.pid, self.vid, {"expected_revision": variant.revision, "title": variant.title,
                                                            "scenes": bodies, "art_direction_id": None, "score_id": None})
        if art:
            await self.add_art()
        return self

    def service(self) -> PresentationStudioTemplates:
        return PresentationStudioTemplates(self.studio, self.env.prefabs, self.store, edit=self.edit, diagnostics=self.sink)

    async def add_art(self, profile=None):
        variant = await self.studio.get_variant(self.pid, self.vid)
        profile = profile or generate_fallback_profile({"title": PROJECT_TITLE})
        return await self.studio.create_art_direction(self.pid, self.vid, {"expected_variant_revision": variant.revision,
                                                                           "profile": profile.to_dict()})

    # -- demandes

    def body(self, kind="presentation", *, slug="rapport", title="Rapport type", scenes=None, **extra) -> dict:
        """`scenes=None` : la selection par defaut (accent en dimension, titre et valeur en parametres) ; `scenes=False` : aucune
        selection (le mode decouverte du plan)."""

        if scenes is None and kind in ("presentation", "scene"):
            ids = (S1, S2) if kind == "presentation" else (S1,)
            scenes = [{"scene_id": s, "dimensions": ["accent"], "parameters": ["headline", "count"]} for s in ids]
        out = {"kind": kind, "slug": slug, "title": title, **extra}
        if scenes:
            out["scenes"] = scenes
        return out

    async def plan(self, body):
        return await self.templates.plan(self.pid, self.vid, body)

    async def promote(self, body):
        return await self.templates.promote(self.pid, self.vid, body)

    @staticmethod
    async def refused(awaitable, code):
        try:
            await awaitable
        except PresentationStudioError as exc:
            assert exc.code is code, exc
            return exc
        raise AssertionError(f"expected {code}")

    # -- ce qui est sur le disque

    def library_files(self) -> dict[str, str]:
        root = self.env.data / LIBRARY_DIR
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*")) if p.is_file()}

    def template_files(self) -> dict[str, str]:
        root = self.env.root / "presentation_templates"
        if not root.exists():
            return {}
        return {p.name: p.read_text(encoding="utf-8") for p in sorted(root.glob("*.json"))}

    def project_files(self) -> dict[str, bytes]:
        return self.env.snapshot(self.pid)

    def promoted_text(self) -> str:
        """Tout ce qu'une promotion a laisse : fichiers des prefabs `studio-template.*` (sans `publication.json`, qui porte la
        derivation voulue) et documents de modeles (sans `derived_from`)."""

        root = self.env.data / LIBRARY_DIR
        parts = [p.read_text(encoding="utf-8") for p in sorted(root.glob("studio-template.*/*/*"))
                 if p.is_file() and p.name != "publication.json"]
        for text in self.template_files().values():
            document = json.loads(text)
            document.pop("derived_from")
            for row in document["scenes"]:
                row["scene"].pop("scene_id")  # a record-local slot, regenerated by every instantiation
            parts.append(json.dumps(document, ensure_ascii=False))
        return "\n".join(parts)
