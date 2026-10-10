"""Promotion d'un travail de presentation en modele reutilisable (handoff jarvis-interactive-presentation-studio, Slice 20).

Contrat : `docs/presentation-studio.md` > *Template and prefab promotion contract*. Ce service est la seule porte, pour la page comme pour
l'agent (Slice 21) : `plan`, `promote`, `list_templates`, `get_template`, `instantiate`.

**Aucun second catalogue.** Le code reutilisable est publie dans la bibliotheque partagee par `PrefabService.save` (id
`studio-template.<slug>[-n]`, origine `fork` de la version de projet dont il derive, donc la provenance de derivation est dans
`publication.json`). Le document `ptp_...` ne garde que la composition (versions de la bibliotheque, valeurs neutres, controles choisis,
sections de direction artistique). Il est ecrit **apres** les publications ; une panne entre les deux laisse des prefabs publies mais non
references (la bibliotheque n'a pas de suppression), que la reprise d'une meme promotion **reutilise** (meme contenu, meme id : pas de
nouvelle version).

Ordre : tout est analyse et valide **avant** la premiere ecriture (selection, assainissement, detection, validation du candidat par
`PrefabService.validate_candidate`, ids libres ou deja ceux de la meme promotion). Un constat bloquant (`presentation_studio_template_leak`)
n'ecrit rien. Diagnostics `core.presentation_studio.template_{planned,promoted,instantiated,refused}` : ids et comptes, jamais un titre,
une valeur ni une chaine du projet.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any

from jarvis.domain.prefab import (
    PrefabInstanceRef, PrefabRef, bundle_fingerprint, canonical_json, with_version,
)
from jarvis.domain.presentation_studio import (
    PresentationStudioError, PresentationStudioErrorCode as C, dump_document, new_scene_id, stamp,
)
from jarvis.domain.presentation_studio_authoring import safe_text, scan_json
from jarvis.domain.presentation_studio_checks import _fail
from jarvis.domain.presentation_studio_scene import StudioScene
from jarvis.domain.presentation_studio_template import (
    MAX_TEMPLATES, DaSelection, PromoteRequest, SceneSelection, StudioTemplate, TemplateKind, TemplateScene,
    new_template_id, parse_instantiate, parse_promote, parse_template, prefab_id_for, template_scene_dicts,
    template_scene_id,
)
from jarvis.domain.presentation_studio_template_sanitize import (
    LOOK_TYPES, Finding, SceneBuild, SelectionError, build_scene, compose_profile, content_terms, content_values,
    decorate_manifest, leaf_role, leaves, sanitize_da_sections, scan_text, scan_value,
)
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode as PC
from jarvis.ports.v2 import DiagnosticSink

#: Les constats cites dans le message d'un refus (le plan les donne tous).
MESSAGE_FINDINGS = 3
_PREFAB_STATUS = {PC.INVALID_DEFINITION: C.SOURCE_INVALID, PC.VERSION_LIMIT: C.LIMIT_REACHED, PC.ID_LIMIT: C.LIMIT_REACHED,
                  PC.STORAGE_IO: C.STORAGE_IO, PC.VERSION_EXISTS: C.ALREADY_EXISTS, PC.BASE_PROTECTED: C.SOURCE_INVALID}


def _prefab_error(exc: PrefabStoreError) -> PresentationStudioError:
    return PresentationStudioError(_PREFAB_STATUS.get(exc.code, C.PREFAB_UNAVAILABLE), f"shared library: {exc.code.value}: {exc.message}",
                                   warn=exc.code is not PC.STORAGE_IO)


@dataclass(slots=True)
class _Scene:
    key: str
    selection: SceneSelection
    scene: StudioScene
    source: PrefabRef
    build: SceneBuild
    files: Mapping[str, str]


@dataclass(slots=True)
class _Group:
    number: int
    members: list[_Scene]
    prefab_id: str = ""
    #: `(version, identique)` quand l'id existe deja dans la bibliotheque.
    existing: tuple[int, bool] | None = None


@dataclass(slots=True)
class _Da:
    sections: dict[str, Any]
    counts: dict[str, int]
    source_id: str | None


@dataclass(slots=True)
class _Analysis:
    request: PromoteRequest
    presentation_id: str
    variant_id: str
    revision: int
    scenes: list[_Scene] = field(default_factory=list)
    groups: list[_Group] = field(default_factory=list)
    da: _Da | None = None
    findings: list[Finding] = field(default_factory=list)
    discovery: bool = False
    candidates: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    terms: frozenset[str] = frozenset()

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]


class PresentationStudioTemplates:
    def __init__(self, studio: Any, prefabs: Any, store: Any, *, edit: Any | None = None,
                 diagnostics: DiagnosticSink | None = None, clock: Callable[[], datetime] | None = None,
                 new_id: Callable[[], str] = new_template_id) -> None:
        self._studio = studio
        self._prefabs = prefabs
        self._store = store
        self._edit = edit
        self._diagnostics = diagnostics
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._new_id = new_id
        #: One promotion at a time: two concurrent promotions of the same slug must not both reach `PrefabService.save`.
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ plan (n'ecrit rien)

    async def plan(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        """Decrit la promotion sans rien ecrire : candidats, role de chaque controle, ids de prefab prevus, constats."""

        self._require_ids(presentation_id, variant_id)
        _guard_scan(raw)
        analysis = await self._analyse(presentation_id, variant_id, parse_promote(raw, strict=False))
        answer = self._plan_answer(analysis)
        self._trace("template_planned", "Promotion planifiee (rien d'ecrit)",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "kind": analysis.request.kind.value,
                          "scenes": len(analysis.scenes), "prefabs": len(analysis.groups), "findings": len(analysis.findings),
                          "blocking": len(analysis.blocking), "discovery": analysis.discovery})
        return answer

    def _plan_answer(self, a: _Analysis) -> dict[str, Any]:
        req = a.request
        scenes = []
        for item in a.scenes:
            group = next(g for g in a.groups if item in g.members)
            scenes.append({
                "scene_id": item.selection.scene_id, "key": item.key, "source": item.source.to_dict(),
                "prefab_id": group.prefab_id, "shared_with": [m.key for m in group.members if m is not item],
                "prefab_state": "new" if group.existing is None else "reused" if group.existing[1] else "taken",
                "controls": a.candidates.get(item.key, []),
                "kept": {"dimensions": len(item.selection.dimensions), "parameters": len(item.selection.parameters)},
                "stripped": dict(item.build.stripped)})
        da = None if a.da is None else {"sections": sorted(a.da.sections), "stripped": dict(a.da.counts)}
        return {"ok": not a.blocking, "kind": req.kind.value, "presentation_id": a.presentation_id, "variant_id": a.variant_id,
                "variant_revision": a.revision, "slug": req.slug, "title": req.title, "selection_required": a.discovery,
                "scenes": scenes, "art_direction": da,
                "would_publish": [g.prefab_id for g in a.groups if g.existing is None],
                "findings": [f.to_dict() for f in a.findings], "blocking": len(a.blocking)}

    # ------------------------------------------------------------ analyse commune au plan et a la promotion

    async def _analyse(self, presentation_id: str, variant_id: str, request: PromoteRequest) -> _Analysis:
        view = await self._studio.get(presentation_id)
        variant = await self._studio.get_variant(presentation_id, variant_id)
        if request.expected_revision is not None and request.expected_revision != variant.revision:
            raise PresentationStudioError(C.STALE_REVISION, f"the variant is at revision {variant.revision}, not "
                                                            f"{request.expected_revision}: read it again, then retry")
        a = _Analysis(request, presentation_id, variant_id, variant.revision,
                      discovery=request.scenes is None and request.kind is TemplateKind.PRESENTATION)
        a.findings.extend(scan_text("request", f"{request.title}\n{request.description}\n{' '.join(request.tags)}\n"
                                    + "\n".join(s.label for s in request.scenes or ()), frozenset()))
        project = [view.presentation.title, variant.title, *(r.to_payload() for r in view.presentation.resources)]
        if request.kind in (TemplateKind.PRESENTATION, TemplateKind.SCENE):
            await self._analyse_scenes(a, variant, project)
        art_terms = content_terms(project)
        if request.kind is TemplateKind.MOTION:
            a.da = await self._analyse_da(a, variant, DaSelection(("motion",)), art_terms)
        elif request.art_direction is not None:
            a.da = await self._analyse_da(a, variant, request.art_direction, art_terms)
        elif request.kind is TemplateKind.ART_DIRECTION:
            a.discovery = True
        return a

    async def _analyse_scenes(self, a: _Analysis, variant: Any, project: list[Any]) -> None:
        request = a.request
        by_id = {s.scene_id: s for s in variant.scenes}
        if request.kind is TemplateKind.PRESENTATION:
            if not variant.scenes:
                raise _fail("this variant has no scene to promote")
            picks = list(request.scenes) if request.scenes is not None else [
                SceneSelection(s.scene_id, "", (), ()) for s in variant.scenes]
            missing = set(by_id) - {p.scene_id for p in picks}
            if missing:
                raise PresentationStudioError(
                    C.TEMPLATE_SELECTION_REQUIRED,
                    f"a presentation template covers every scene of the variant: {len(missing)} scene(s) have no selection")
        else:
            if request.scenes is None:
                raise _fail("a scene template names its scene: scenes=[{scene_id, dimensions: [], parameters: []}]")
            picks = list(request.scenes)
        for p in picks:
            if p.scene_id not in by_id:
                raise PresentationStudioError(C.UNKNOWN_SCENE, f"{p.scene_id} is not a scene of this variant")
        order = {s.scene_id: n for n, s in enumerate(variant.scenes)}
        picks.sort(key=lambda p: order[p.scene_id])
        fetched: list[tuple[SceneSelection, StudioScene, PrefabRef, dict[str, Any], Mapping[str, str]]] = []
        for pick in picks:
            scene = by_id[pick.scene_id]
            if scene.last_valid_pin is not None:
                raise PresentationStudioError(C.SCENE_RELOADING,
                                              f"scene {scene.scene_id} has an unconfirmed hot reload: promote after it is confirmed")
            try:
                detail = (await self._prefabs.get(scene.prefab.prefab_id, scene.prefab.version)).to_dict(include_source=True)
            except PrefabStoreError as exc:
                raise _prefab_error(exc) from None
            if detail["manifest"].get("source") is not None:
                # Remotion Slice 15: an agent now authors Remotion scenes. The promotion pipeline sanitises and parameterises HTML sources
                # (template, style, behavior); promoting a Remotion source is the promotion Slice of the Remotion handoff. Said, typed, not a 500.
                raise PresentationStudioError(
                    C.ENGINE_UNSUPPORTED, f"scene {scene.scene_id} is a Remotion source: promoting a Remotion scene to a template is not "
                                          "available yet, the scene stays a project source")
            fetched.append((pick, scene, scene.prefab, detail["manifest"], detail["files"]))
        terms = content_terms(
            [*project, *(v for _, sc, _, man, _ in fetched for v in
                         (sc.title, sc.section, sc.preview.caption, sc.preview.alt,
                          *content_values(man, sc.controls, sc.props, sc.data)))])
        a.terms = terms
        a.candidates = {f"s{n}": _candidates(sc, man) for n, (_, sc, _, man, _) in enumerate(fetched, 1)}
        for n, (pick, scene, source, manifest, files) in enumerate(fetched, 1):
            key = f"s{n}"
            try:
                build = build_scene(manifest=manifest, files=files, props=scene.props, data=scene.data, controls=scene.controls,
                                    anchors=[x.to_dict() for x in scene.anchors], dimensions=pick.dimensions,
                                    parameters=pick.parameters, terms=terms, key=key, title=request.title,
                                    description=request.description, tags=request.tags)
            except SelectionError as exc:
                raise PresentationStudioError(C.INVALID_PRESENTATION, str(exc)) from None
            a.scenes.append(_Scene(key, pick, scene, source, build, files))
            a.findings.extend(build.findings)
        await self._group(a)

    async def _group(self, a: _Analysis) -> None:
        """Les scenes de meme candidat assaini partagent un prefab (un id de la bibliotheque, pas un par scene)."""

        seen: dict[str, _Group] = {}
        for item in a.scenes:
            body = dict(item.build.candidate["manifest"])
            for ident in ("id", "title", "description", "tags"):
                body.pop(ident, None)
            digest = canonical_json({"m": body, "t": item.build.candidate["template"], "s": item.build.candidate["style"],
                                     "b": item.build.candidate["behavior"]})
            group = seen.get(digest)
            if group is None:
                group = seen[digest] = _Group(len(seen) + 1, [])
                a.groups.append(group)
            group.members.append(item)
        single = a.request.kind is TemplateKind.SCENE
        for group in a.groups:
            group.prefab_id = prefab_id_for(a.request.slug, None if single else group.number)
            candidate = self._candidate(a, group)
            check = self._prefabs.validate_candidate(candidate)
            if not check.ok:
                a.findings.append(Finding("prefab_invalid", f"prefab:{group.prefab_id}",
                                          "the shared library refuses the candidate: " + safe_text(check.errors[0])[:200]))
                continue
            try:
                group.existing = await self._existing(group, candidate)
            except PrefabStoreError as exc:
                raise _prefab_error(exc) from None
            if group.existing is not None and not group.existing[1]:
                a.findings.append(Finding("prefab_id_taken", f"prefab:{group.prefab_id}",
                                          "the id already exists in the shared library with other content: choose another slug"))

    def _candidate(self, a: _Analysis, group: _Group) -> dict[str, Any]:
        first = group.members[0].build.candidate
        title = a.request.title if len(a.groups) <= 1 else f"{a.request.title} ({group.number})"
        manifest = decorate_manifest(first["manifest"], prefab_id=group.prefab_id or "studio-template.pending", title=title,
                                     description=a.request.description, tags=a.request.tags)
        return {"manifest": manifest, "template": first["template"], "style": first["style"], "behavior": first["behavior"]}

    async def _existing(self, group: _Group, candidate: Mapping[str, Any]) -> tuple[int, bool] | None:
        try:
            detail = await self._prefabs.get(group.prefab_id)
        except PrefabStoreError as exc:
            if exc.code is PC.UNKNOWN_PREFAB:
                return None
            raise
        version = detail.entry.version
        same = bundle_fingerprint(with_version(candidate["manifest"], version), candidate["template"], candidate["style"],
                                  candidate["behavior"]) == detail.entry.fingerprint
        return version, same

    async def _analyse_da(self, a: _Analysis, variant: Any, selection: DaSelection, terms: frozenset[str]) -> _Da:
        if variant.art_direction_id is None:
            raise PresentationStudioError(C.UNKNOWN_ART_DIRECTION, "this variant has no art direction to promote")
        document = (await self._studio.get_art_direction(a.presentation_id, a.variant_id))["art_direction"]
        profile = document["profile"]
        extra = content_terms([profile.get("name"), *profile.get("imagery", {}).get("motifs", ()),
                               *profile.get("provenance", {}).get("notes", ())])
        sections, counts, findings = sanitize_da_sections(profile, selection.sections, keep_motifs=selection.keep_motifs,
                                                          terms=terms | extra)
        a.findings.extend(findings)
        try:
            compose_profile(sections, a.request.title)
        except PresentationStudioError as exc:
            a.findings.append(Finding("art_direction_unfit", "art_direction",
                                      "the selected sections do not stand alone (select the sections they depend on, for example "
                                      "palette with dataviz): " + safe_text(exc.message)[:160]))
        return _Da(sections, counts, document["art_direction_id"])

    # ------------------------------------------------------------ promotion

    async def promote(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        """Publie le code reutilisable dans la bibliotheque partagee puis ecrit la composition. Rien n'est ecrit si l'analyse a un
        constat bloquant. 201 : `{template, prefabs, scenes, findings}`."""

        self._require_ids(presentation_id, variant_id)
        _guard_scan(raw)
        request = parse_promote(raw, strict=True)
        async with self._lock:
            return await self._promote(presentation_id, variant_id, request)

    async def _promote(self, presentation_id: str, variant_id: str, request: PromoteRequest) -> dict[str, Any]:
        if len(await self._ids()) >= MAX_TEMPLATES:
            raise PresentationStudioError(C.LIMIT_REACHED, f"at most {MAX_TEMPLATES} templates")
        analysis = await self._analyse(presentation_id, variant_id, request)
        if analysis.blocking:
            self._trace("template_refused", "Promotion refusee : le plan liste les constats", level="info",
                        data={"presentation_id": presentation_id, "variant_id": variant_id, "kind": request.kind.value,
                              "blocking": len(analysis.blocking), "codes": sorted({f.code for f in analysis.blocking})})
            head = "; ".join(f"{f.code} at {f.where}" for f in analysis.blocking[:MESSAGE_FINDINGS])
            raise PresentationStudioError(C.TEMPLATE_LEAK, f"{len(analysis.blocking)} blocking finding(s), nothing written: {head} "
                                                           "(run the plan for the full list)")
        template_id = self._new_id()
        # Dernier filet, avant toute ecriture : l'enregistrement tel qu'il sera ecrit (versions prevues) ne porte aucune trace du projet.
        predicted = {g.prefab_id: (g.existing[0] if g.existing else 1) for g in analysis.groups}
        draft = self._document(analysis, template_id, predicted)
        net = self._final_net(analysis, draft)
        if net:
            raise PresentationStudioError(C.TEMPLATE_LEAK, f"the final record still holds project traces ({net[0].code} at "
                                                           f"{net[0].where}); nothing written")
        published = await self._publish(analysis)
        versions = {pid: ref.version for pid, (ref, _) in published.items()}
        template = self._document(analysis, template_id, versions)
        await self._verify(template)
        try:
            await asyncio.to_thread(self._store.create, template_id, dump_template(template))
        except PresentationStudioError:
            self._trace("template_orphans", "Prefabs publies sans modele ecrit (reprise : meme promotion, memes ids)", level="warning",
                        data={"template_id": template_id, "prefabs": sorted(versions)})
            raise
        self._trace("template_promoted", "Modele promu",
                    data={"template_id": template_id, "kind": request.kind.value, "presentation_id": presentation_id,
                          "variant_id": variant_id, "scenes": len(template.scenes), "prefabs": len(published),
                          "reused": sum(1 for _, reused in published.values() if reused),
                          "parameters": len(template.parameters)})
        return {"template": template.summary(), "template_id": template_id, "kind": request.kind.value,
                "prefabs": [{"id": pid, "version": ref.version, "published": not reused, "reused": reused}
                            for pid, (ref, reused) in published.items()],
                "scenes": [{"key": s.key, "label": s.label, "prefab": s.scene.prefab.to_dict()} for s in template.scenes],
                "parameters": [dict(p) for p in template.parameters],
                "findings": [f.to_dict() for f in analysis.findings if not f.blocking],
                "derived_from": dict(template.derived_from)}

    async def _publish(self, a: _Analysis) -> dict[str, tuple[PrefabRef, bool]]:
        out: dict[str, tuple[PrefabRef, bool]] = {}
        for group in a.groups:
            candidate = self._candidate(a, group)
            if group.existing is not None:
                out[group.prefab_id] = (PrefabRef(group.prefab_id, group.existing[0]), True)
                continue
            try:
                publication = await self._prefabs.save(candidate, actor=a.request.actor, derived_from=group.members[0].source)
            except PrefabStoreError as exc:
                if out:
                    self._trace("template_orphans", "Promotion interrompue : des prefabs sont publies (la reprise les reutilise)",
                                level="warning", data={"prefabs": sorted(out), "code": exc.code.value})
                raise _prefab_error(exc) from None
            out[group.prefab_id] = (PrefabRef(group.prefab_id, publication.version), False)
        return out

    def _document(self, a: _Analysis, template_id: str, versions: Mapping[str, int]) -> StudioTemplate:
        req = a.request
        scenes: list[TemplateScene] = []
        params: list[dict[str, Any]] = []
        stripped: dict[str, int] = {}
        for index, item in enumerate(a.scenes):
            group = next(g for g in a.groups if item in g.members)
            ref = PrefabRef(group.prefab_id, versions[group.prefab_id])
            label = item.selection.label
            scene = StudioScene.from_dict({
                "scene_id": template_scene_id(template_id, index), "prefab": ref.to_dict(), "title": "", "section": "",
                "props": item.build.props, "data": item.build.data, "controls": list(item.build.controls),
                "anchors": list(item.build.anchors), "preview": {}}, f"template scene {item.key}")
            scenes.append(TemplateScene(item.key, label, scene))
            by_id = {c.control_id: c for c in scene.controls}
            for control_id, role in item.build.roles.items():
                params.append({"scene_key": item.key, "control_id": control_id, "kind": role["kind"], "role": role["role"],
                               "type": role["type"], "group": by_id[control_id].group.value, "label": by_id[control_id].label})
            for name, count in item.build.stripped.items():
                stripped[name] = stripped.get(name, 0) + count
        art = None
        if a.da is not None:
            art = {"sections": a.da.sections}
            for name, count in a.da.counts.items():
                stripped[name] = stripped.get(name, 0) + count
        prefabs = tuple(PrefabRef(pid, version) for pid, version in versions.items())
        derived: dict[str, Any] = {"presentation_id": a.presentation_id, "variant_id": a.variant_id, "variant_revision": a.revision}
        if a.scenes:
            derived["scenes"] = [{"key": i.key, "scene_id": i.selection.scene_id, "prefab": i.source.to_dict()} for i in a.scenes]
        if a.da is not None and a.da.source_id:
            derived["art_direction_id"] = a.da.source_id
        report = {"stripped": stripped, "scenes": len(scenes), "prefabs": len(prefabs)}
        return StudioTemplate(template_id, req.kind, req.title, req.description, req.tags, tuple(scenes), art, tuple(params),
                              prefabs, report, derived, req.actor, stamp(self._clock()))

    def _final_net(self, a: _Analysis, template: StudioTemplate) -> list[Finding]:
        """Tout le document, `derived_from` exclu (la seule trace admise du projet), contre identifiants, chemins et chaines."""

        body = template.to_document()
        body.pop("derived_from")
        for row in body["scenes"]:
            row["scene"].pop("scene_id")  # a record-local slot (`template_scene_id`), regenerated by every instantiation
        return [f for f in scan_value("record", body, a.terms) if f.blocking]

    async def _verify(self, template: StudioTemplate) -> None:
        """Aucune reference brisee : chaque version citee existe dans la bibliotheque partagee, saine, et n'est pas un prefab de projet."""

        for ref in template.prefabs:
            if ref.prefab_id.startswith("presentation-studio."):
                raise PresentationStudioError(C.TEMPLATE_LEAK, "a template must not pin a project (presentation-studio.*) prefab")
            try:
                await self._prefabs.manifest(ref.prefab_id, ref.version)
            except PrefabStoreError as exc:
                raise _prefab_error(exc) from None
        for item in template.scenes:
            result = await self._prefabs.validate_instance(PrefabInstanceRef(
                item.scene.prefab.prefab_id, item.scene.prefab.version, item.scene.props, item.scene.data))
            if not result.ok:
                raise PresentationStudioError(C.SCENE_INCOMPATIBLE, f"the neutral values of scene {item.key} do not fit its published "
                                                                    f"prefab: {safe_text(result.detail or '')[:160]}")

    # ------------------------------------------------------------ lecture

    async def list_templates(self, kind: str | None = None) -> dict[str, Any]:
        if kind is not None and kind not in {k.value for k in TemplateKind}:
            raise _fail("kind must be presentation, scene, art_direction or motion")
        rows, problems = [], []
        for template_id in await self._ids():
            try:
                template = await self._load(template_id)
            except PresentationStudioError as exc:
                problems.append({"template_id": template_id, "code": exc.code.value})
                continue
            if kind is None or template.kind.value == kind:
                rows.append(template.summary())
        return {"templates": rows, "count": len(rows), "problems": problems, "limit": MAX_TEMPLATES}

    async def get_template(self, template_id: str) -> dict[str, Any]:
        template = await self._load(template_id)
        availability = []
        for ref in template.prefabs:
            try:
                await self._prefabs.manifest(ref.prefab_id, ref.version)
                ok = True
            except PrefabStoreError:
                ok = False
            availability.append({**ref.to_dict(), "available": ok})
        return {"template": template.to_document(), "summary": template.summary(), "prefab_availability": availability}

    # ------------------------------------------------------------ instanciation

    async def instantiate(self, template_id: str, raw: object) -> dict[str, Any]:
        """Un modele devient du travail neuf : `presentation` (nouvelle Presentation), `scene` (ajoutee a une variante par l'API
        d'edition), `art_direction` / `motion` (sections posees sur la direction artistique d'une variante). 201."""

        _guard_scan(raw)
        request = parse_instantiate(raw)
        template = await self._load(template_id)
        await self._verify(template)
        if template.kind is TemplateKind.PRESENTATION:
            answer = await self._instantiate_presentation(template, request)
        else:
            if request.presentation_id is None or request.variant_id is None or request.expected_revision is None:
                raise _fail(f"a {template.kind.value} template needs presentation_id, variant_id and expected_revision (the variant's)")
            variant = await self._studio.get_variant(request.presentation_id, request.variant_id)
            if variant.revision != request.expected_revision:
                raise PresentationStudioError(C.STALE_REVISION, f"the variant is at revision {variant.revision}, not "
                                                                f"{request.expected_revision}: read it again, then retry")
            if template.kind is TemplateKind.SCENE:
                answer = await self._instantiate_scene(template, request)
            else:
                answer = await self._instantiate_art(template, request, variant)
        self._trace("template_instantiated", "Modele instancie",
                    data={"template_id": template_id, "kind": template.kind.value, "scenes": len(template.scenes)})
        return {"template_id": template_id, "kind": template.kind.value, **answer}

    async def _instantiate_presentation(self, template: StudioTemplate, request: Any) -> dict[str, Any]:
        if not request.title:
            raise _fail("a presentation template needs a title for the new presentation")
        view = await self._studio.create({"title": request.title})
        pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
        try:
            variant = await self._studio.get_variant(pid, vid)
            scenes = template_scene_dicts(template, new_scene_id)
            saved = await self._studio.save_variant(pid, vid, {
                "expected_revision": variant.revision, "title": variant.title, "scenes": scenes, "art_direction_id": None,
                "score_id": None})
            if template.art_direction is not None:
                profile = compose_profile(template.art_direction["sections"], template.title)
                art = await self._studio.create_art_direction(pid, vid, {"expected_variant_revision": saved.revision,
                                                                         "profile": profile.to_dict()})
            else:
                art = await self._studio.create_fallback_art_direction(
                    pid, vid, {"expected_variant_revision": saved.revision, "seed_context": {"title": request.title}})
            rendered = [await self._studio.describe_scene(pid, vid, s["scene_id"]) for s in scenes]
        except PresentationStudioError as exc:
            raise PresentationStudioError(exc.code, f"{exc.message} (presentation {pid} was created and is incomplete)") from None
        return {"presentation_id": pid, "variant_id": vid, "scene_ids": [s["scene_id"] for s in scenes],
                "art_direction_id": art["art_direction"]["art_direction_id"],
                "rendered": [{"scene_id": r["scene_id"], "prefab": r["prefab"], "payload": r["payload"], "problems": r["problems"]}
                             for r in rendered]}

    async def _instantiate_scene(self, template: StudioTemplate, request: Any) -> dict[str, Any]:
        if self._edit is None:
            raise PresentationStudioError(C.RELOAD_UNAVAILABLE, "the edit service is not wired")
        wire = template_scene_dicts(template, new_scene_id)[0]
        result = await self._edit.edit(request.presentation_id, request.variant_id, {
            "actor": request.actor, "mode": "commit", "basis": {"variant_revision": request.expected_revision},
            "ops": [{"op": "scene.add", "scene": wire}]})
        if result.status.value != "applied":
            try:
                code = C(result.code) if result.code else C.INVALID_PRESENTATION
            except ValueError:
                code = C.INVALID_PRESENTATION
            raise PresentationStudioError(code, result.message or "the scene could not be added")
        return {"presentation_id": request.presentation_id, "variant_id": request.variant_id, "scene_id": wire["scene_id"],
                "revision": result.revision}

    async def _instantiate_art(self, template: StudioTemplate, request: Any, variant: Any) -> dict[str, Any]:
        sections = template.art_direction["sections"]
        pid, vid = request.presentation_id, request.variant_id
        if variant.art_direction_id is None:
            profile = compose_profile(sections, template.title)
            made = await self._studio.create_art_direction(pid, vid, {"expected_variant_revision": variant.revision,
                                                                      "profile": profile.to_dict()})
        else:
            current = (await self._studio.get_art_direction(pid, vid))["art_direction"]
            profile = compose_profile(sections, None, current["profile"])
            made = await self._studio.save_art_direction(pid, vid, {"expected_revision": current["revision"],
                                                                    "profile": profile.to_dict()})
        art = made["art_direction"]
        return {"presentation_id": pid, "variant_id": vid, "art_direction_id": art["art_direction_id"],
                "art_direction_revision": art["revision"], "sections": sorted(sections)}

    # ------------------------------------------------------------ outils

    async def _ids(self) -> tuple[str, ...]:
        return await asyncio.to_thread(self._store.list_ids)

    async def _load(self, template_id: str) -> StudioTemplate:
        text = await asyncio.to_thread(self._store.read, template_id)
        try:
            return parse_template(json.loads(text))
        except (ValueError, TypeError):
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{template_id}: not a readable template document") from None

    @staticmethod
    def _require_ids(presentation_id: str, variant_id: str) -> None:
        from jarvis.domain.presentation_studio import is_presentation_id, is_variant_id

        if not is_presentation_id(presentation_id) or not is_variant_id(variant_id):
            raise _fail("presentation_id or variant_id is not a valid id")

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(f"core.presentation_studio.{kind}", message, level=level, data=dict(data))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal never undoes a promotion
            pass


def dump_template(template: StudioTemplate) -> str:
    return dump_document(template.to_document())


def _guard_scan(raw: object) -> None:
    problems = scan_json(raw)
    if problems:
        raise _fail(problems[0])


def _candidates(scene: StudioScene, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Pour le plan : chaque controle de la scene, son role et ce qu'on peut en choisir (jamais sa valeur)."""

    by_path = {c.path: c for c in scene.controls}
    rows = []
    for root in ("props", "data"):
        for leaf in leaves(manifest["inputs"][root], root):
            control = by_path.get(leaf.path)
            if control is None:
                continue
            role = leaf_role(leaf, control)
            rows.append({"control_id": control.control_id, "label": control.label, "group": control.group.value, "path": control.path,
                         "type": leaf.type, "role": role, "eligible_dimension": role == "look" and leaf.type in LOOK_TYPES})
    return rows
