"""Nouvelle version d'un prefab epingle : avertir, jamais mettre a jour, essayer dans une variante neuve (handoff
jarvis-remotion-presentation-integration, Slice 19 ; decisions D9 et D10).

Une scene du Studio epingle une version exacte et immuable `(prefab_id, version)`. Quand le meme id a depuis recu une version plus
recente (une edition de source dans une autre variante, une revision de la bibliotheque), l'utilisateur doit pouvoir le savoir et
l'essayer **sans que rien ne bouge sous lui** :

- `notices` : lecture seule. Pour chaque scene dont le pin n'est pas la derniere version saine, rend les versions plus recentes, si
  les valeurs et les controles de la scene tiennent dans la derniere (`fits`), si elle est utilisable par le moteur de la Presentation
  (`engine_ok`, natif seulement), son bloc de catalogue public (type, compatibilite, licence, amont) et les essais deja ouverts. Elle
  n'ecrit rien et ne met aucun pin a jour ; **rien ne l'appelle tout seul**.
- `try_version` : cree une variante ENFANT (l'operation de branche de la Slice 16, `transform=`) dont la scene designee prend la
  version choisie ; le reste est une copie. La variante source n'est ni modifiee ni activee, l'essai non plus : l'adoption est un acte
  explicite et distinct (activer la variante, ou la comparer et en melanger des dimensions avec la comparaison de la Slice 19 du
  handoff d'origine). Aucune valeur ni aucun controle n'est devine : si la nouvelle version ne tient pas la scene, l'essai est refuse
  avec la raison (`scene_incompatible`, `engine_unsupported`) et rien n'est ecrit.

La retention n'a rien de nouveau a savoir : la variante source garde son ancien pin, l'essai porte le nouveau, et le registre des pins
(`StudioPinRegistry`, variantes vivantes et archivees) retient les deux tant que les deux variantes existent.

Diagnostics `core.presentation_studio.upgrade_{checked,trial_created,trial_refused}` : identifiants, versions, comptes ; jamais un titre
ni une valeur. Contrat : `docs/presentation-studio.md` > *Newer prefab versions and trial variants*.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from jarvis.domain.prefab import PrefabRef
from jarvis.domain.presentation_studio_template_remotion import LICENCE_NOT_DECLARED, licence_of
from jarvis.domain.presentation_studio import (
    PresentationStudioError, PresentationStudioErrorCode as C, PresentationVariant, _check_title, is_presentation_id,
    is_variant_id,
)
from jarvis.domain.presentation_studio_checks import _check_int, _exact_keys, _fail, is_scene_id
from jarvis.domain.presentation_studio_scene import StudioScene
from jarvis.domain.presentation_studio_variants import check_rationale
from jarvis.ports.prefabs import PrefabStoreError

#: Les versions plus recentes citees par scene (les plus recentes d'abord) ; le compte exact est toujours donne.
MAX_LISTED_VERSIONS = 8
#: Prefixe de la raison de creation d'un essai : l'avis retrouve ainsi les essais ouverts sans second registre.
TRIAL_PREFIX = "Essai de "
_TRIAL = re.compile(r"Essai de (?P<prefab>\S+) v(?P<version>\d+) pour la scène (?P<scene>pss_[0-9a-f]{12})")


class PresentationStudioUpgrades:
    def __init__(self, studio: Any, variants: Any, prefabs: Any, *, edit: Any | None = None) -> None:
        self._studio = studio
        self._variants = variants
        self._prefabs = prefabs
        self._edit = edit

    # ------------------------------------------------------------ avis (lecture seule)

    async def notices(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        """`{notices: [...], count, auto_upgrade: false, trials: [...]}` ; n'ecrit rien, ne change aucun pin."""

        _require(presentation_id, variant_id)
        variant = await self._studio.get_variant(presentation_id, variant_id)
        trials = await self._open_trials(presentation_id, variant_id)
        rows: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []
        for scene in variant.scenes:
            try:
                row = await self._notice(presentation_id, scene)
            except PrefabStoreError as exc:
                unavailable.append({"scene_id": scene.scene_id, "prefab_id": scene.prefab.prefab_id, "code": exc.code.value})
                continue
            if row is not None:
                row["trials"] = [t for t in trials if t["scene_id"] == scene.scene_id]
                rows.append(row)
        self._trace("upgrade_checked", "Versions plus recentes recherchees (rien d'ecrit)",
                    data={"presentation_id": presentation_id, "variant_id": variant_id, "scenes": len(variant.scenes),
                          "newer": len(rows), "unavailable": len(unavailable)})
        return {"presentation_id": presentation_id, "variant_id": variant_id, "variant_revision": variant.revision,
                "notices": rows, "count": len(rows), "unavailable": unavailable, "trials": trials,
                "auto_upgrade": False}

    async def _notice(self, presentation_id: str, scene: StudioScene) -> dict[str, Any] | None:
        pin = scene.prefab
        detail = await self._prefabs.get(pin.prefab_id)
        newer = sorted((row["version"] for row in detail.history if row.get("status") == "ok" and row["version"] > pin.version),
                       reverse=True)
        if not newer:
            return None
        latest = PrefabRef(pin.prefab_id, newer[0])
        problem, engine_ok = await self._fits(presentation_id, scene, latest)
        view = (await self._prefabs.get(latest.prefab_id, latest.version)).to_dict(catalog=True)["catalog"]
        upstream = view.get("upstream") or {}
        pinned_licence, latest_licence, must_name = await self._licences(pin, latest)
        return {"pinned_licence": pinned_licence, "latest_licence": latest_licence, "licence_changed": pinned_licence != latest_licence,
                "licence_ack_required": must_name,"scene_id": scene.scene_id, "prefab_id": pin.prefab_id, "pinned_version": pin.version,
                "latest_version": latest.version, "newer_count": len(newer), "newer_versions": newer[:MAX_LISTED_VERSIONS],
                "reloading": scene.last_valid_pin is not None, "fits": problem is None, "problem": problem,
                "engine_ok": engine_ok,
                "latest_catalog": {"type": view.get("type"), "compatibility": view.get("compatibility"),
                                   "license": view.get("license"),
                                   "upstream": None if not upstream else {
                                       "name": upstream.get("name"), "verified_intact": upstream.get("verified_intact")}}}

    async def _licences(self, pin: PrefabRef, target: PrefabRef) -> tuple[str | None, str | None, str | None]:
        """`(licence epinglee, licence de la version visee, nom a reconnaitre ou None)` (QA B3). Une licence qui CHANGE se reconnait toujours,
        meme pour une plus permissive ; une licence non redistribuable ou non declaree d'un amont aussi."""

        def read(manifest: Any) -> tuple[str | None, str | None]:
            block = manifest.raw.get("catalog") or {}
            upstream = block.get("upstream") if isinstance(block.get("upstream"), dict) else {}
            return (block.get("license") or upstream.get("license") or "").strip() or None, licence_of(manifest.raw)

        before, _ = read(await self._prefabs.manifest(pin.prefab_id, pin.version))
        after, restrictive = read(await self._prefabs.manifest(target.prefab_id, target.version))
        if before != after:
            return before, after, after or LICENCE_NOT_DECLARED
        return before, after, restrictive

    async def _fits(self, presentation_id: str, scene: StudioScene, latest: PrefabRef) -> tuple[str | None, bool]:
        """`(raison de l'incompatibilite ou None, utilisable par le moteur)` ; jamais d'exception : c'est une information."""

        candidate = replace(scene, prefab=latest)
        catalog = self._studio.scene_catalog
        engine_ok = True
        problem: str | None = None
        try:
            await self._studio.require_native_pin(presentation_id, latest.prefab_id, latest.version,
                                                  what=f"scene {scene.scene_id} ({latest.prefab_id}@{latest.version})")
        except PresentationStudioError as exc:
            engine_ok, problem = False, exc.code.value
        if problem is None and catalog is not None:
            try:
                await catalog.check(candidate)
            except PresentationStudioError as exc:
                problem = exc.code.value
        return problem, engine_ok

    async def _open_trials(self, presentation_id: str, variant_id: str) -> list[dict[str, Any]]:
        graph = await self._variants.graph(presentation_id)
        found = []
        for node in graph["nodes"]:
            match = _TRIAL.match(node.get("rationale") or "")
            if match and node.get("parent_variant_id") == variant_id:
                found.append({"variant_id": node["variant_id"], "variant_number": node["variant_number"],
                              "scene_id": match["scene"], "prefab_id": match["prefab"], "version": int(match["version"]),
                              "active": node["active"]})
        return found

    # ------------------------------------------------------------ essai

    async def try_version(self, presentation_id: str, variant_id: str, raw: object) -> dict[str, Any]:
        """Une variante enfant dont la scene `scene_id` prend `version` (defaut : la derniere saine). Corps `{scene_id, version?, title?,
        actor?, expected_variant_revision?}` ; il n'y a pas de `activate` : un essai n'est jamais active par lui-meme."""

        _require(presentation_id, variant_id)
        data = _exact_keys(raw, "trial", {"scene_id"}, frozenset({"version", "title", "actor", "expected_variant_revision", "licence_ack"}))
        if not is_scene_id(data["scene_id"]):
            raise PresentationStudioError(C.UNKNOWN_SCENE, "unknown scene id")
        actor = data.get("actor", "user")
        if actor not in ("user", "brain"):
            raise _fail("actor must be 'user' or 'brain'")
        if data.get("version") is not None:
            _check_int("version", data["version"], 1, 9999)
        if data.get("expected_variant_revision") is not None:
            _check_int("expected_variant_revision", data["expected_variant_revision"], 1, 2**31 - 1)
        if data.get("title") is not None:
            _check_title("title", data["title"])
        acks = data.get("licence_ack", [])
        if not isinstance(acks, list) or len(acks) > 8 or not all(isinstance(a, str) and a and len(a) <= 120 and a == a.strip() and a.isprintable() for a in acks):
            raise _fail("licence_ack must be at most 8 licence names of at most 120 characters, as the notice shows them")
        if acks and actor != "user":
            raise _fail("licence_ack is the user's own acknowledgement: only the actor 'user' may give it")
        data = {**data, "licence_ack": acks}
        try:
            return await self._try(presentation_id, variant_id, data, actor)
        except PresentationStudioError as exc:
            self._trace("upgrade_trial_refused", "Essai de version refuse, rien d'ecrit", level="info",
                        data={"presentation_id": presentation_id, "variant_id": variant_id, "scene_id": data["scene_id"],
                              "code": exc.code.value})
            raise

    async def _try(self, presentation_id: str, variant_id: str, data: Mapping[str, Any], actor: str) -> dict[str, Any]:
        source = await self._studio.get_variant(presentation_id, variant_id)
        scene = next((s for s in source.scenes if s.scene_id == data["scene_id"]), None)
        if scene is None:
            raise PresentationStudioError(C.UNKNOWN_SCENE, f"{data['scene_id']} is not a scene of this variant")
        if data.get("expected_variant_revision") not in (None, source.revision):
            raise PresentationStudioError(
                C.STALE_REVISION, f"{variant_id} is at revision {source.revision}, not {data['expected_variant_revision']}: "
                                  "reload, then retry")
        self._studio.refuse_if_reloading(presentation_id, source)  # the branch rule: an unconfirmed source is never copied
        if scene.last_valid_pin is not None:
            raise PresentationStudioError(C.SCENE_RELOADING, f"scene {scene.scene_id} runs a source that was not seen mounted yet: "
                                                             "show it (or wait for its report), then try a version")
        pin = scene.prefab
        target = await self._target(pin, data.get("version"))
        _, _, must_name = await self._licences(pin, target)
        if must_name is not None and must_name not in data["licence_ack"]:
            raise _fail(f"the licence changes or needs a decision (it reads '{clip_text(must_name)}'): name it in licence_ack to try this version")
        trial = replace(scene, prefab=target, source_revision=scene.source_revision + 1)
        # What the original scene is checked against is NOT guessed here: the new version either holds the scene's values and
        # controls (and is native for the engine) or the trial is refused with the reason. Nothing is rebound silently.
        await self._studio.check_scenes(presentation_id, variant_id, (trial,), source.scenes)
        if self._edit is not None:
            broken = await self._edit.score_regression(source, tuple(trial if s.scene_id == scene.scene_id else s for s in source.scenes))
            if broken:
                raise PresentationStudioError(C.SCORE_INCOMPATIBLE, f"the new version would leave {len(broken)} score reference(s) "
                                                                    f"unresolved (first: {broken[0]})")
        reason = check_rationale(f"{TRIAL_PREFIX}{pin.prefab_id} v{target.version} pour la scène {scene.scene_id} "
                                 f"(depuis v{pin.version}) ; la variante d'origine n'est pas modifiée.")
        body = {"title": data.get("title") or f"Essai v{target.version}", "source_variant_id": variant_id, "actor": actor,
                "rationale": reason, "activate": False}
        answer = await self._variants.create_branch(
            presentation_id, body, transform=lambda base: _repinned(base, scene.scene_id, pin, target, source.revision))
        self._trace("upgrade_trial_created", "Essai d'une version plus recente dans une variante neuve",
                    data={"presentation_id": presentation_id, "source_variant_id": variant_id, "scene_id": scene.scene_id,
                          "prefab_id": pin.prefab_id, "from_version": pin.version, "to_version": target.version,
                          "variant_id": answer["node"]["variant_id"]})
        return {**answer, "trial": True, "adopted": False, "scene_id": scene.scene_id, "from": pin.to_dict(), "to": target.to_dict()}

    async def _target(self, pin: PrefabRef, wanted: int | None) -> PrefabRef:
        try:
            detail = await self._prefabs.get(pin.prefab_id)
            healthy = [row["version"] for row in detail.history if row.get("status") == "ok"]
            version = wanted if wanted is not None else (max(healthy) if healthy else pin.version)
            if version <= pin.version:
                raise _fail(f"version {version} is not newer than the pinned v{pin.version}: a trial is for a newer version")
            if version not in healthy:
                raise PresentationStudioError(C.PREFAB_UNAVAILABLE, f"{pin.prefab_id} has no healthy version {version}")
        except PrefabStoreError as exc:
            raise PresentationStudioError(C.PREFAB_UNAVAILABLE, f"{pin.prefab_id}: {exc.code.value}: {exc.message}") from None
        return PrefabRef(pin.prefab_id, version)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any]) -> None:
        self._studio.trace(f"core.presentation_studio.{kind}", message, level=level, data=data)


def _require(presentation_id: str, variant_id: str) -> None:
    if not is_presentation_id(presentation_id):
        raise PresentationStudioError(C.UNKNOWN_PRESENTATION, "unknown presentation id")
    if not is_variant_id(variant_id):
        raise PresentationStudioError(C.UNKNOWN_VARIANT, "unknown variant id")


def clip_text(text: str) -> str:
    return "".join(ch for ch in text if ch.isprintable())[:120]


def _repinned(base: PresentationVariant, scene_id: str, pin: PrefabRef, target: PrefabRef, revision: int) -> PresentationVariant:
    """Pure : la copie de la source dont UNE scene prend la nouvelle version. Refus si la copie ne porte plus le pin attendu (la
    source a bouge depuis la lecture) : jamais un pin remplace a l'aveugle."""

    # Runs INSIDE the variants lock: what was checked outside (values, controls, engine, score) held for this exact revision of the source.
    if base.revision != revision:
        raise PresentationStudioError(C.STALE_REVISION, f"the variant moved from revision {revision} to {base.revision} while the new version was "
                                                        "being checked: read it again, then retry")
    scenes = []
    for scene in base.scenes:
        if scene.scene_id == scene_id:
            if scene.prefab != pin:
                raise PresentationStudioError(C.STALE_REVISION, f"scene {scene_id} no longer pins {pin.prefab_id}@{pin.version}: "
                                                                "read the variant again, then retry")
            scene = replace(scene, prefab=target, last_valid_pin=None, source_revision=scene.source_revision + 1)
        scenes.append(scene)
    return replace(base, scenes=tuple(scenes))
