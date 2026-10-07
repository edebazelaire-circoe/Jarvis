"""The real `LoadoutResolver`: which knowledge an agent profile may see (Slice 09).

Deny by scope. A loadout is built from one rule per key (`<profile>` or
`<profile>:<role>`): a user rule from `memory.loadouts` when one exists, else a
built-in preset. The rule names the memory scopes the loadout may read; the Wiki,
CodeGraph and Skills assets it lists are then fetched with an EXPLICIT scope each
(a provider called without a scope sees every scope, Slice 07 gap) and the result is
re-checked against the allowed scopes, so a provider that ignores its `scope` argument
still cannot leak a private asset. The private scope reaches a loadout only through the
Brain preset, or a rule that names it together with `allow_private`.

Roles (`coder`, `reviewer`, `research`) map to a base profile (`code`, `code`,
`general`) when the brief carried no explicit profile; a skill lists a role in
`allowed_profiles` to be delivered to that role (the "+role" of the presets).

`resolve` never raises: a provider that fails contributes nothing, and the view says
so. Pure orchestration over ports; the Core wiring (Slice 05/05b) calls
`register_knowledge(...)`. Contract page: `docs/skills-and-loadouts.md`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
from typing import Protocol

from jarvis.domain.knowledge import MAX_LOADOUT_ENTRIES, AssetScope, KnowledgeAsset, Loadout
from jarvis.domain.loadout_view import LoadoutView, ManifestEntry, render_manifest
from jarvis.domain.memory import MAX_REASON_CHARS, PRIVATE_SCOPE, SHARED_SCOPE, MemoryStoreError, check_scope
from jarvis.domain.memory_settings import (
    BRAIN_PROFILE,
    LOADOUT_ROLES,
    KnowledgeSettings,
    LoadoutPolicy,
    LoadoutRule,
    loadout_key,
)
from jarvis.domain.routing import GENERAL_PROFILE, TASK_PROFILE_IDS
from jarvis.domain.skills import SkillCatalogView, SkillConflict
from jarvis.ports.knowledge import KnowledgeAssetProvider

_LOG = logging.getLogger(__name__)

#: A brief that names only a role (the hook defaults the profile to `general`) gets this base profile.
ROLE_BASE_PROFILE = {"coder": "code", "reviewer": "code", "research": GENERAL_PROFILE}


class SkillCatalog(Protocol):
    """What the resolver needs of the skills registry beyond the provider port."""

    def catalog(self) -> SkillCatalogView: ...


def _why(text: str) -> str:
    return text[:MAX_REASON_CHARS]


def _project_scopes(project_id: str | None) -> tuple[str, ...]:
    return () if project_id is None else (f"project:{project_id}",)


def preset_rule(profile: str, project_id: str | None = None) -> LoadoutRule:
    """The built-in rule of a base profile. Only the Brain preset names the private scope."""

    project = _project_scopes(project_id)
    if profile == BRAIN_PROFILE:
        return LoadoutRule(memory_scopes=(PRIVATE_SCOPE, SHARED_SCOPE, *project), allow_private=True)
    if profile == "code":
        return LoadoutRule(memory_scopes=(SHARED_SCOPE, *project))
    if profile == GENERAL_PROFILE:
        return LoadoutRule(memory_scopes=(SHARED_SCOPE, *project), codegraph=False)
    # desktop, fast: shared knowledge only, no code structure.
    return LoadoutRule(memory_scopes=(SHARED_SCOPE,), codegraph=False)


def _asset_scopes(memory_scopes: Iterable[str]) -> tuple[AssetScope, ...]:
    """The asset scopes a set of memory scopes opens (`board:*` opens none). Stable order."""

    found: dict[AssetScope, None] = {}
    for scope in memory_scopes:
        kind = scope.partition(":")[0]
        if kind in (AssetScope.PRIVATE, AssetScope.SHARED, AssetScope.PROJECT):
            found[AssetScope(kind)] = None
    return tuple(found)


def loadout_keys() -> tuple[tuple[str, str | None], ...]:
    """Every `(profile, role)` a snapshot covers: each task profile alone and with each role, plus the Brain."""

    keys: list[tuple[str, str | None]] = []
    for profile in TASK_PROFILE_IDS:
        keys.append((profile, None))
        keys.extend((profile, role) for role in LOADOUT_ROLES)
    keys.append((BRAIN_PROFILE, None))
    return tuple(keys)


class KnowledgeLoadoutResolver:
    """`LoadoutResolver` over the Wiki, CodeGraph and Skills providers."""

    def __init__(
        self,
        *,
        wiki: KnowledgeAssetProvider | None = None,
        codegraph: KnowledgeAssetProvider | None = None,
        skills: SkillCatalog | None = None,
        policy: Callable[[], LoadoutPolicy] | None = None,
        knowledge: Callable[[], KnowledgeSettings] | None = None,
        project_id: str | None = None,
    ) -> None:
        if project_id is not None:
            check_scope("project_id", f"project:{project_id}")
        self._wiki = wiki
        self._codegraph = codegraph
        self._skills = skills
        self._policy = policy or LoadoutPolicy
        self._knowledge = knowledge or KnowledgeSettings
        self.project_id = project_id

    # ------------------------------------------------------------------ port

    def resolve(self, profile: str, role: str | None = None) -> Loadout:
        """Effective loadout with the reason each entry is included. Never raises."""

        return self.explain(profile, role).loadout

    # ----------------------------------------------------------- inspection

    def explain(self, profile: str, role: str | None = None) -> LoadoutView:
        """The loadout plus versions, skill losers and provider failures. Never raises."""

        try:
            return self._explain(profile, role)
        except Exception as exc:  # noqa: BLE001 - a resolver that raises would block an agent launch
            _LOG.error("loadout resolution failed for %s/%s: %s", profile, role, exc.__class__.__name__)
            return LoadoutView(
                Loadout(profile=profile, role=role), degraded=(("resolver", "resolver_failed"),)
            )

    def explain_all(self) -> dict[str, LoadoutView]:
        """One view per snapshot key (`loadout_keys`): what the hook snapshot is written from."""

        return {loadout_key(profile, role): self.explain(profile, role) for profile, role in loadout_keys()}

    # -------------------------------------------------------------- internals

    def _base_profile(self, profile: str, role: str | None) -> str:
        if role in ROLE_BASE_PROFILE and profile == GENERAL_PROFILE:
            return ROLE_BASE_PROFILE[role]
        return profile

    def _rule(self, profile: str, role: str | None, base: str) -> tuple[LoadoutRule, str]:
        policy = self._policy()
        for key in dict.fromkeys((loadout_key(profile, role) if role else profile, base)):
            rule = policy.rule_for(key)
            if rule is not None:
                return rule, f"settings rule {key}"
        return preset_rule(base, self.project_id), f"preset {base}"

    def _explain(self, profile: str, role: str | None) -> LoadoutView:
        base = self._base_profile(profile, role)
        rule, origin = self._rule(profile, role, base)
        toggles = self._knowledge()
        allow_private = rule.allow_private
        # Deny by default, twice: a rule cannot name `private` without `allow_private` (the
        # domain refuses it), and the filter below keeps that true for any rule that slips by.
        scopes = tuple(s for s in rule.memory_scopes if s != PRIVATE_SCOPE or allow_private)
        asset_scopes = _asset_scopes(scopes)
        reasons: dict[str, str] = {f"scope:{scope}": _why(f"memory scope allowed by {origin}") for scope in scopes}
        entries: list[ManifestEntry] = [ManifestEntry("scope", scope) for scope in scopes]
        degraded: list[tuple[str, str]] = []
        wiki_ids: list[str] = []
        repos: list[str] = []
        skill_ids: list[str] = []
        conflicts: list[SkillConflict] = []

        if rule.wiki and toggles.wiki_enabled and self._wiki is not None:
            for asset in self._assets("wiki", self._wiki, asset_scopes, degraded):
                wiki_ids.append(asset.asset_id)
                entries.append(ManifestEntry("wiki", asset.asset_id, asset.version))
                reasons[f"wiki:{asset.asset_id}"] = _why(f"wiki page, {asset.scope.value} scope allowed by {origin}")
        if rule.codegraph and toggles.codegraph_enabled and self._codegraph is not None:
            project_only = tuple(s for s in asset_scopes if s is AssetScope.PROJECT)
            for asset in self._assets("codegraph", self._codegraph, project_only, degraded):
                repos.append(asset.asset_id)
                entries.append(ManifestEntry("codegraph", asset.asset_id))
                reasons[f"codegraph:{asset.asset_id}"] = _why(f"code graph, project scope allowed by {origin}")
        if rule.skills and toggles.skills_enabled and self._skills is not None:
            view = self._skill_view(degraded)
            if view is not None:
                for record in view.winners:
                    if record.scope not in asset_scopes or (record.scope is AssetScope.PRIVATE and not allow_private):
                        continue
                    if not record.allows(base, role):
                        continue
                    skill_ids.append(record.id)
                    entries.append(ManifestEntry("skill", record.id, record.version))
                    listed = ", ".join(record.allowed_profiles) or "every profile"
                    reasons[f"skill:{record.id}"] = _why(
                        f"enabled skill {record.version}, {record.scope.value} scope allowed by {origin}, "
                        f"delivered to {listed}"
                    )
                conflicts = [c for c in view.conflicts if c.skill_id in skill_ids]

        for kind, ids in (("wiki", wiki_ids), ("codegraph", repos), ("skill", skill_ids)):
            if len(ids) > MAX_LOADOUT_ENTRIES:
                degraded.append((kind, "loadout_truncated"))
                dropped = set(ids[MAX_LOADOUT_ENTRIES:])
                del ids[MAX_LOADOUT_ENTRIES:]
                entries = [e for e in entries if not (e.kind == kind and e.id in dropped)]
                for gone in dropped:
                    reasons.pop(f"{kind}:{gone}", None)
        loadout = Loadout(
            profile=profile, role=role, memory_scopes=scopes, wiki_ids=tuple(wiki_ids),
            codegraph_repos=tuple(repos), skill_ids=tuple(skill_ids), allow_private=allow_private,
            reasons=reasons,
        )
        return LoadoutView(loadout, tuple(entries), tuple(conflicts), tuple(degraded))

    def _assets(
        self,
        kind: str,
        provider: KnowledgeAssetProvider,
        scopes: tuple[AssetScope, ...],
        degraded: list[tuple[str, str]],
    ) -> list[KnowledgeAsset]:
        """Assets of the allowed scopes, one explicit-scope `list` call per scope, re-checked."""

        found: dict[str, KnowledgeAsset] = {}
        for scope in scopes:
            try:
                listed = provider.list(scope)
            except MemoryStoreError as exc:
                _LOG.warning("%s provider unavailable for loadouts: %s", kind, exc.code.value)
                degraded.append((kind, exc.code.value))
                continue
            except Exception as exc:  # noqa: BLE001 - one broken provider must not blank the others
                _LOG.warning("%s provider failed for loadouts: %s", kind, exc.__class__.__name__)
                degraded.append((kind, "provider_failed"))
                continue
            for asset in listed:
                if asset.scope is scope:  # a provider that ignored `scope` cannot widen the loadout
                    found.setdefault(asset.asset_id, asset)
        return sorted(found.values(), key=lambda a: a.asset_id)

    def _skill_view(self, degraded: list[tuple[str, str]]) -> SkillCatalogView | None:
        try:
            return self._skills.catalog()
        except MemoryStoreError as exc:
            _LOG.warning("skills registry unavailable for loadouts: %s", exc.code.value)
            degraded.append(("skill", exc.code.value))
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("skills registry failed for loadouts: %s", exc.__class__.__name__)
            degraded.append(("skill", "provider_failed"))
        return None


def register_knowledge(
    *,
    wiki: KnowledgeAssetProvider | None = None,
    codegraph: KnowledgeAssetProvider | None = None,
    skills: SkillCatalog | None = None,
    policy: Callable[[], LoadoutPolicy] | None = None,
    knowledge: Callable[[], KnowledgeSettings] | None = None,
    project_id: str | None = None,
) -> KnowledgeLoadoutResolver:
    """The single entry point for the Core wiring (Slice 05/05b): build the real resolver.

    Call once at startup with the providers that exist (`None` leaves a kind out) and hand the
    result wherever `NullLoadoutResolver` was the default. `policy` and `knowledge` are
    callables, re-read on every resolution, so a settings change applies on the next turn:
    pass `lambda: read_loadout_policy(block)` and `lambda: read_memory_settings(block).knowledge`
    (both from `jarvis.runtime.memory_settings`, imported by the wiring, not by Core logic).
    `project_id` qualifies the project scope as `project:<id>`; without it no project scope is
    granted by a preset. The wiring also writes the hook snapshot, see
    `jarvis.runtime.loadout_snapshot.write_loadout_snapshot(runtime_root, resolver.explain_all())`.
    """

    return KnowledgeLoadoutResolver(
        wiki=wiki, codegraph=codegraph, skills=skills, policy=policy, knowledge=knowledge, project_id=project_id,
    )


def manifest_for(resolver: KnowledgeLoadoutResolver, profile: str, role: str | None = None) -> str:
    """The manifest a sub-agent brief receives for `(profile, role)`; empty when nothing is granted."""

    return render_manifest(resolver.explain(profile, role))
