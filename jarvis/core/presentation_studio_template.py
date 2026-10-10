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
from typing import Any

from jarvis.core.presentation_studio_template_embed import (
    EmbeddedSources, complete_remotion, inventory, note_licence, prefab_error as _prefab_error, record_catalog,
)
from jarvis.core.presentation_studio_template_guard import blank, mark_failed, record_size_finding, spoken_words
from jarvis.domain.prefab import (
    PrefabInstanceRef, PrefabRef, canonical_json, is_remotion_manifest, with_version,
)
from jarvis.domain.presentation_studio import (
    PresentationStudioError, PresentationStudioErrorCode as C, dump_document, load_document, new_scene_id, stamp,
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
from jarvis.domain.presentation_studio_template_remotion import content_hash, licence_findings
from jarvis.domain.presentation_studio_template_score import instantiate_score, score_skeleton
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode as PC
from jarvis.ports.v2 import DiagnosticSink

#: Les constats cites dans le message d'un refus (le plan les donne tous).
MESSAGE_FINDINGS = 3


@dataclass(slots=True)
class _Scene:
    key: str
    selection: SceneSelection
    scene: StudioScene
    source: PrefabRef
    build: SceneBuild
    files: Mapping[str, str]
    #: Slice 19 : le manifeste promu (bloc `catalog` pose) est dans `build.candidate` ; `remotion` : la source lue (TSX), `verified` :
    #: les clefs de verification de l'importeur survivent (fichiers intacts).
    remotion: bool = False
    verified: bool = False


@dataclass(slots=True)
class _Group:
    number: int
    members: list[_Scene]
    prefab_id: str = ""
    #: `(version, identique)` quand l'id existe deja dans la bibliotheque.
    existing: tuple[int, bool] | None = None
    #: Slice 19 : empreinte de contenu de la source integree (modele de presentation) ; `""` pour une publication de bibliotheque.
    digest: str = ""


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
    #: Slice 19 : la partition de la variante (document), le squelette qu'elle donne et ses comptes retires.
    score_doc: dict[str, Any] | None = None
    #: Licences a reconnaitre : `{licence: [ou]}`.
    licences: dict[str, list[str]] = field(default_factory=dict)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    @property
    def embed(self) -> bool:
        """Une presentation entiere : un seul artefact, ses sources integrees au modele, rien publie dans la bibliotheque."""

        return self.request.kind is TemplateKind.PRESENTATION


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
        self._embedded = EmbeddedSources(prefabs)
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
                "prefab_id": "" if a.embed else group.prefab_id, "shared_with": [m.key for m in group.members if m is not item],
                "engine": "remotion" if item.remotion else "slidecar", "verified_import": item.verified,
                "prefab_state": "embedded" if a.embed else "new" if group.existing is None else "reused" if group.existing[1] else "taken",
                "controls": a.candidates.get(item.key, []),
                "kept": {"dimensions": len(item.selection.dimensions), "parameters": len(item.selection.parameters)},
                "stripped": dict(item.build.stripped)})
        da = None if a.da is None else {"sections": sorted(a.da.sections), "stripped": dict(a.da.counts)}
        return {"ok": not a.blocking, "kind": req.kind.value, "presentation_id": a.presentation_id, "variant_id": a.variant_id,
                "variant_revision": a.revision, "slug": req.slug, "title": req.title, "selection_required": a.discovery,
                "scenes": scenes, "art_direction": da, "publishes_to_library": not a.embed,
                "embedded": [{"hash": g.digest, "scenes": [m.key for m in g.members]} for g in a.groups] if a.embed else [],
                "score": None if a.score_doc is None else {"items": len(a.score_doc["items"]), "carried": "skeleton"},
                "licences": {name: list(where) for name, where in a.licences.items()},
                "would_publish": [] if a.embed else [g.prefab_id for g in a.groups if g.existing is None],
                "findings": [f.to_dict() for f in a.findings], "blocking": len(a.blocking)}

    # ------------------------------------------------------------ analyse commune au plan et a la promotion

    async def _analyse(self, presentation_id: str, variant_id: str, request: PromoteRequest) -> _Analysis:
        view = await self._studio.get(presentation_id)
        variant = await self._studio.get_variant(presentation_id, variant_id)
        if request.expected_revision is not None and request.expected_revision != variant.revision:
            raise PresentationStudioError(C.STALE_REVISION, f"the variant is at revision {variant.revision}, not "
                                                            f"{request.expected_revision}: read it again, then retry")
        if request.actor != "user" and (request.licence_ack or request.keep_assets):
            raise _fail("licence_ack and keep_assets are the user's own acknowledgement: only the actor 'user' may give them")
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
        a.findings.extend(licence_findings(a.licences, request.licence_ack))
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
        fetched: list[tuple[SceneSelection, StudioScene, PrefabRef, dict[str, Any], Mapping[str, str], Any]] = []
        for pick in picks:
            scene = by_id[pick.scene_id]
            if scene.last_valid_pin is not None:
                raise PresentationStudioError(C.SCENE_RELOADING,
                                              f"scene {scene.scene_id} has an unconfirmed hot reload: promote after it is confirmed")
            try:
                detail = (await self._prefabs.get(scene.prefab.prefab_id, scene.prefab.version)).to_dict(include_source=True)
                # Slice 19: a Remotion source is read as TEXT through the library's gate (the isolation guards run on every read).
                tsx = await self._prefabs.remotion_source(scene.prefab.prefab_id, scene.prefab.version) \
                    if is_remotion_manifest(detail["manifest"]) else None
            except PrefabStoreError as exc:
                raise _prefab_error(exc) from None
            fetched.append((pick, scene, scene.prefab, detail["manifest"], detail["files"], tsx))
        if variant.score_id is not None:
            a.score_doc = (await self._studio.get_score(a.presentation_id, variant.variant_id))["score"]
        spoken = spoken_words(a.score_doc)
        terms = content_terms(
            [*project, *spoken, *(v for _, sc, _, man, _, _ in fetched for v in
                         (sc.title, sc.section, sc.preview.caption, sc.preview.alt,
                          *content_values(man, sc.controls, sc.props, sc.data)))])
        a.terms = terms
        a.candidates = {f"s{n}": _candidates(sc, man) for n, (_, sc, _, man, _, _) in enumerate(fetched, 1)}
        for n, (pick, scene, source, manifest, files, tsx) in enumerate(fetched, 1):
            key = f"s{n}"
            try:
                build = build_scene(manifest=manifest, files=None if tsx is not None else files, props=scene.props, data=scene.data, controls=scene.controls,
                                    anchors=[x.to_dict() for x in scene.anchors], dimensions=pick.dimensions,
                                    parameters=pick.parameters, terms=terms, key=key, title=request.title,
                                    description=request.description, tags=request.tags)
            except SelectionError as exc:
                raise PresentationStudioError(C.INVALID_PRESENTATION, str(exc)) from None
            item = _Scene(key, pick, scene, source, build, files, remotion=tsx is not None)
            a.scenes.append(item)
            a.findings.extend(build.findings)
            if tsx is not None:
                complete_remotion(a, item, tsx, manifest)
            else:
                note_licence(a, item, manifest)
        await self._group(a)
        if a.embed:
            await self._carry_score(a)
            self._size_finding(a)

    def _size_finding(self, a: _Analysis) -> None:
        try:
            found = record_size_finding(self._document(a, "ptp_000000000000", {}).to_document())
        except (PresentationStudioError, KeyError):
            return  # another finding already says why the record cannot be drawn
        a.findings.extend([found] if found else [])

    async def _carry_score(self, a: _Analysis) -> None:
        """Slice 19: the template carries the SKELETON of the score (no speech, cue, sequence or control value)."""

        if a.score_doc is None:
            return
        slots = {item.selection.scene_id: template_scene_id("ptp_000000000000", n) for n, item in enumerate(a.scenes)}
        try:
            score_skeleton(a.score_doc, slot_of=slots, template_id="ptp_000000000000")
        except (PresentationStudioError, KeyError):
            a.findings.append(Finding("score_unfit", "score", "the score does not reduce to a stand-alone skeleton (an item names a "
                                                              "scene outside the template): fix the score, then promote"))

    async def _group(self, a: _Analysis) -> None:
        """Les scenes de meme candidat assaini partagent un prefab (un id de la bibliotheque, pas un par scene)."""

        seen: dict[str, _Group] = {}
        for item in a.scenes:
            body = dict(item.build.candidate["manifest"])
            for ident in ("id", "title", "description", "tags"):
                body.pop(ident, None)
            digest = canonical_json({"m": body, **{k: v for k, v in item.build.candidate.items() if k != "manifest"}})
            group = seen.get(digest)
            if group is None:
                group = seen[digest] = _Group(len(seen) + 1, [])
                a.groups.append(group)
            group.members.append(item)
        single = a.request.kind is TemplateKind.SCENE
        for group in a.groups:
            group.prefab_id = prefab_id_for(a.request.slug, None if single else group.number)
            candidate = self._candidate(a, group)
            group.digest = content_hash(candidate) if a.embed else ""
            check = self._prefabs.validate_candidate(candidate)
            if not check.ok:
                a.findings.append(Finding("prefab_invalid", f"prefab:{group.prefab_id}",
                                          "the shared library refuses the candidate: " + safe_text(check.errors[0])[:200]))
                continue
            if a.embed:  # one artefact: nothing is looked up, nothing is published in the shared library
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
        return {**first, "manifest": manifest}

    async def _existing(self, group: _Group, candidate: Mapping[str, Any]) -> tuple[int, bool] | None:
        try:
            detail = await self._prefabs.get(group.prefab_id)
        except PrefabStoreError as exc:
            if exc.code is PC.UNKNOWN_PREFAB:
                return None
            raise
        version = detail.entry.version
        same = self._prefabs.validate_candidate(
            {**candidate, "manifest": with_version(candidate["manifest"], version)}).fingerprint == detail.entry.fingerprint
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
        published = {} if analysis.embed else await self._publish(analysis)  # one artefact: the library is untouched
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
                          "embedded": len(template.embedded or ()), "score": template.score is not None,
                          "reused": sum(1 for _, reused in published.values() if reused),
                          "parameters": len(template.parameters)})
        return {"template": template.summary(), "template_id": template_id, "kind": request.kind.value,
                "published_to_library": not analysis.embed and bool(published),
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
                publication = await self._prefabs.save(candidate, actor=a.request.actor, derived_from=group.members[0].source,
                                                       verified_import=group.members[0].verified)
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
        embed = a.embed
        for index, item in enumerate(a.scenes):
            group = next(g for g in a.groups if item in g.members)
            ref = PrefabRef(group.prefab_id, 1 if embed else versions[group.prefab_id])
            label = item.selection.label
            scene = StudioScene.from_dict({
                "scene_id": template_scene_id(template_id, index), "prefab": ref.to_dict(), "title": "", "section": "",
                "props": item.build.props, "data": item.build.data, "controls": list(item.build.controls),
                "anchors": list(item.build.anchors), "preview": {}}, f"template scene {item.key}")
            scenes.append(TemplateScene(item.key, label, scene, group.digest if embed else None))
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
        embedded = {g.digest: self._candidate(a, g) for g in a.groups} if embed else None
        catalog = record_catalog([(i.remotion, self._candidate(a, next(g for g in a.groups if i in g.members))["manifest"])
                                  for i in a.scenes], req.licence_ack) if embed else None
        skeleton, score_report = None, None
        if embed and a.score_doc is not None:
            slots = {i.selection.scene_id: template_scene_id(template_id, n) for n, i in enumerate(a.scenes)}
            skeleton, score_report = score_skeleton(a.score_doc, slot_of=slots, template_id=template_id)
        derived: dict[str, Any] = {"presentation_id": a.presentation_id, "variant_id": a.variant_id, "variant_revision": a.revision}
        if a.scenes:
            derived["scenes"] = [{"key": i.key, "scene_id": i.selection.scene_id, "prefab": i.source.to_dict()} for i in a.scenes]
        if a.da is not None and a.da.source_id:
            derived["art_direction_id"] = a.da.source_id
        report: dict[str, Any] = {"stripped": stripped, "scenes": len(scenes), "prefabs": len(prefabs)}
        if score_report is not None:
            report["score_dropped"] = score_report
        return StudioTemplate(template_id, req.kind, req.title, req.description, req.tags, tuple(scenes), art, tuple(params),
                              prefabs, report, derived, req.actor, stamp(self._clock()), 1, skeleton, embedded, catalog)

    def _final_net(self, a: _Analysis, template: StudioTemplate) -> list[Finding]:
        """Tout le document, `derived_from` exclu (la seule trace admise du projet), contre identifiants, chemins et chaines."""

        body = template.to_document()
        body.pop("derived_from")
        # The skeleton's ids are record-local slots (`template_scene_id`, `skeleton_item_id`), like a scene's own: blanked, so a
        # real project id left in the score would still be found.
        slots = {row.scene.scene_id for row in template.scenes} | {i["item_id"] for i in (template.score or {}).get("items", ())}
        if body.get("score") is not None:
            body["score"] = blank(body["score"], slots)
        for row in body["scenes"]:
            row["scene"].pop("scene_id")  # a record-local slot (`template_scene_id`), regenerated by every instantiation
        for candidate in (body.get("embedded") or {}).values():
            if "assets" in candidate:  # base64 of binary files: a string search over it means nothing (listed by path instead)
                candidate["assets"] = sorted(candidate["assets"])
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
            if item.source is not None:
                continue  # embedded: published fresh at instantiation, checked by `EmbeddedSources.precheck`
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
        document = template.to_document()
        if template.embedded:  # the answer lists what is embedded, it does not ship the sources
            document["embedded"] = {h: inventory(c) for h, c in template.embedded.items()}
        return {"template": document, "summary": template.summary(), "prefab_availability": availability}

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
        if template.embedded:
            await self._embedded.precheck(template)  # before anything is created: a source today's guards refuse leaves no half presentation
        view = await self._studio.create({"title": request.title})
        pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
        try:
            variant = await self._studio.get_variant(pid, vid)
            states: list[dict[str, str]] = []
            fresh = iter([new_scene_id() for _ in template.scenes])
            scenes = template_scene_dicts(template, lambda: next(fresh))
            if template.embedded:
                refs, states = await self._embedded.install(template, pid, [w["scene_id"] for w in scenes], request.actor)
                for wire, ref in zip(scenes, refs):
                    wire["prefab"] = ref.to_dict()
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
            score_id = None
            if template.score is not None:
                current = await self._studio.get_variant(pid, vid)
                slots = {row.scene.scene_id: wire["scene_id"] for row, wire in zip(template.scenes, scenes)}
                content = instantiate_score(template.score, slots)
                made = await self._studio.create_score(pid, vid, {"expected_variant_revision": current.revision, **content})
                score_id = made["score"]["score_id"]
            rendered = [await self._studio.describe_scene(pid, vid, s["scene_id"]) for s in scenes]
        except Exception as exc:  # noqa: BLE001 - whatever stopped the build, the half-made presentation is marked and named, then the cause is raised
            marked, code = await mark_failed(self._studio, pid, request.title, exc)
            self._trace("template_instantiation_failed", "Instanciation interrompue : la presentation est signalee, rien n'est supprime",
                        level="warning", data={"presentation_id": pid, "code": code})
            if not isinstance(exc, PresentationStudioError):
                raise
            raise PresentationStudioError(exc.code, f"{exc.message} (presentation {pid} was created and is incomplete: {marked})") from None
        return {"presentation_id": pid, "variant_id": vid, "scene_ids": [s["scene_id"] for s in scenes], "score_id": score_id,
                "art_direction_id": art["art_direction"]["art_direction_id"],
                "provenance": states,
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
            raw = load_document(text)   # the strict loader of every Studio document: a duplicate key or NaN is corruption, not a quiet merge (QA e)
        except PresentationStudioError:
            raise PresentationStudioError(C.CORRUPT_DOCUMENT, f"{template_id}: not a readable template document") from None
        return parse_template(raw)

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
