"""Loadout resolver (Slice 09, critical: isolation).

Resolution per profile and role, deny-by-scope, explicit scope on every provider call,
skill version arbitration, the manifest cap, the hook snapshot and the routing hook.
Real Wiki and skills registries run in temp directories; fakes stand in for CodeGraph
and for providers that misbehave. Nothing touches a real data root.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import socket

import pytest

from jarvis.adapters.knowledge_skills import SkillRegistry
from jarvis.adapters.knowledge_wiki import WikiProvider
from jarvis.adapters.memory_frontmatter import compose
from jarvis.core.loadout_resolver import (
    KnowledgeLoadoutResolver,
    loadout_keys,
    manifest_for,
    preset_rule,
    register_knowledge,
)
from jarvis.domain.agent_charter import CHARTER_MARK
from jarvis.domain.knowledge import (
    MAX_LOADOUT_ENTRIES,
    MAX_LOADOUT_MANIFEST_CHARS,
    AssetKind,
    AssetScope,
    KnowledgeAsset,
    Loadout,
    SourceRef,
)
from jarvis.domain.loadout_view import MANIFEST_MARK, LoadoutView, ManifestEntry, render_manifest
from jarvis.domain.memory import MemoryErrorCode, MemoryStoreError
from jarvis.domain.memory_settings import (
    BRAIN_PROFILE,
    KnowledgeSettings,
    LoadoutPolicy,
    LoadoutRule,
    loadout_key,
)
from jarvis.ports.knowledge import LoadoutResolver, NullLoadoutResolver
from jarvis.runtime import loadout_snapshot, routing_hook
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.loadout_snapshot import read_manifest, snapshot_path, write_loadout_snapshot
from jarvis.runtime.memory_settings import apply_memory_settings, read_loadout_policy

NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)
PROJECT = "jarvis"
#: Everything the fixture world holds that must NEVER reach a non-Brain loadout.
PRIVATE_IDS = {"priv-doc", "priv-skill", "priv-repo"}


def asset(asset_id: str, kind: AssetKind, scope: AssetScope, *, version: str = "1", title: str = "Title") -> KnowledgeAsset:
    return KnowledgeAsset(
        asset_id=asset_id, kind=kind, title=title, scope=scope, version=version,
        source=SourceRef(uri="file:///x", version_or_commit="abc", fetched_at=NOW), summary="s",
    )


class FakeProvider:
    """Records the scope of every `list` call; `leaky` ignores it, `fail` raises."""

    def __init__(self, kind: AssetKind, assets, *, leaky: bool = False, fail: Exception | None = None) -> None:
        self.kind = kind
        self.assets = tuple(assets)
        self.leaky = leaky
        self.fail = fail
        self.calls: list[AssetScope | None] = []

    def list(self, scope=None):
        self.calls.append(scope)
        if self.fail is not None:
            raise self.fail
        return tuple(a for a in self.assets if self.leaky or scope is None or a.scope is scope)


def skill_text(skill_id: str, version: str = "1.0", scope: str = "shared", profiles: list[str] | None = None) -> str:
    meta = {"id": skill_id, "version": version, "description": f"{skill_id} skill", "scope": scope, "source": "manual"}
    if profiles is not None:
        meta["allowed_profiles"] = profiles
    return compose(meta, f"BODY-OF-{skill_id}\n")


class World:
    def __init__(self, tmp_path, *, leaky: bool = False, policy=None, knowledge=None, project_id: str | None = PROJECT) -> None:
        self.wiki = WikiProvider(tmp_path / "wiki", allowed_roots=[])
        for page_id, scope in (("shared-doc", AssetScope.SHARED), ("proj-doc", AssetScope.PROJECT),
                               ("priv-doc", AssetScope.PRIVATE)):
            self.wiki.import_text(f"https://example.test/{page_id}", page_id, f"BODY-OF-{page_id}", scope, page_id)
        self.skills = SkillRegistry(tmp_path / "skills")
        for skill_id, scope, profiles in (
            ("shared-skill", "shared", None), ("code-skill", "shared", ["code"]),
            ("review-skill", "shared", ["reviewer"]), ("research-skill", "shared", ["research"]),
            ("proj-skill", "project", ["code"]), ("priv-skill", "private", None),
        ):
            self.skills.import_text(skill_text(skill_id, scope=scope, profiles=profiles))
        self.codegraph = FakeProvider(AssetKind.CODEGRAPH, [
            asset("jarvis-aaaa", AssetKind.CODEGRAPH, AssetScope.PROJECT),
            asset("priv-repo", AssetKind.CODEGRAPH, AssetScope.PRIVATE),
        ], leaky=leaky)
        self.resolver = register_knowledge(
            wiki=self.wiki if not leaky else FakeProvider(AssetKind.WIKI, [
                asset("shared-doc", AssetKind.WIKI, AssetScope.SHARED), asset("proj-doc", AssetKind.WIKI, AssetScope.PROJECT),
                asset("priv-doc", AssetKind.WIKI, AssetScope.PRIVATE)], leaky=True),
            codegraph=self.codegraph, skills=self.skills, policy=policy, knowledge=knowledge, project_id=project_id,
        )


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def ids(loadout: Loadout) -> dict[str, tuple[str, ...]]:
    return {"scopes": loadout.memory_scopes, "wiki": loadout.wiki_ids, "repos": loadout.codegraph_repos,
            "skills": loadout.skill_ids}


# ------------------------------------------------------------------ port shape


def test_the_resolver_satisfies_the_port_and_null_still_grants_nothing(world):
    assert isinstance(world.resolver, LoadoutResolver)
    assert NullLoadoutResolver().resolve("code").is_empty


# ----------------------------------------------------------- per profile / role


EXPECTED = {
    ("code", None): {
        "scopes": ("shared", f"project:{PROJECT}"), "wiki": ("proj-doc", "shared-doc"), "repos": ("jarvis-aaaa",),
        "skills": ("code-skill", "proj-skill", "shared-skill"),
    },
    ("general", None): {
        "scopes": ("shared", f"project:{PROJECT}"), "wiki": ("proj-doc", "shared-doc"), "repos": (),
        "skills": ("shared-skill",),
    },
    ("desktop", None): {"scopes": ("shared",), "wiki": ("shared-doc",), "repos": (), "skills": ("shared-skill",)},
    ("fast", None): {"scopes": ("shared",), "wiki": ("shared-doc",), "repos": (), "skills": ("shared-skill",)},
    # coder = code ; reviewer = code + role ; research = general + role (profile left unmarked = general).
    ("general", "coder"): {
        "scopes": ("shared", f"project:{PROJECT}"), "wiki": ("proj-doc", "shared-doc"), "repos": ("jarvis-aaaa",),
        "skills": ("code-skill", "proj-skill", "shared-skill"),
    },
    ("general", "reviewer"): {
        "scopes": ("shared", f"project:{PROJECT}"), "wiki": ("proj-doc", "shared-doc"), "repos": ("jarvis-aaaa",),
        "skills": ("code-skill", "proj-skill", "review-skill", "shared-skill"),
    },
    ("general", "research"): {
        "scopes": ("shared", f"project:{PROJECT}"), "wiki": ("proj-doc", "shared-doc"), "repos": (),
        "skills": ("research-skill", "shared-skill"),
    },
    # An explicit profile is never overridden by the role: a desktop reviewer stays a desktop agent.
    ("desktop", "reviewer"): {"scopes": ("shared",), "wiki": ("shared-doc",), "repos": (),
                              "skills": ("review-skill", "shared-skill")},
    ("code", "reviewer"): {
        "scopes": ("shared", f"project:{PROJECT}"), "wiki": ("proj-doc", "shared-doc"), "repos": ("jarvis-aaaa",),
        "skills": ("code-skill", "proj-skill", "review-skill", "shared-skill"),
    },
    (BRAIN_PROFILE, None): {
        "scopes": ("private", "shared", f"project:{PROJECT}"), "wiki": ("priv-doc", "proj-doc", "shared-doc"),
        "repos": ("jarvis-aaaa",), "skills": ("priv-skill", "shared-skill"),
    },
}


@pytest.mark.parametrize(("profile", "role"), list(EXPECTED))
def test_resolution_per_profile_and_role(world, profile, role):
    loadout = world.resolver.resolve(profile, role)
    assert ids(loadout) == EXPECTED[(profile, role)]
    assert (loadout.profile, loadout.role) == (profile, role)
    assert loadout.allow_private is (profile == BRAIN_PROFILE)


@pytest.mark.parametrize(("profile", "role"), list(EXPECTED))
def test_every_entry_carries_the_reason_it_is_included(world, profile, role):
    loadout = world.resolver.resolve(profile, role)
    expected = ({f"scope:{s}" for s in loadout.memory_scopes} | {f"wiki:{i}" for i in loadout.wiki_ids}
                | {f"codegraph:{i}" for i in loadout.codegraph_repos} | {f"skill:{i}" for i in loadout.skill_ids})
    assert set(loadout.reasons) == expected
    assert all(reason and "preset" in reason for reason in loadout.reasons.values())


def test_the_effective_loadout_is_inspectable_as_json_data(world):
    view = world.resolver.explain("code", "reviewer")
    data = json.loads(json.dumps(view.as_dict()))
    assert data["profile"] == "code" and data["role"] == "reviewer"
    assert data["skill_ids"] == ["code-skill", "proj-skill", "review-skill", "shared-skill"]
    assert data["versions"]["skill:review-skill"] == "1.0" and data["versions"]["wiki:proj-doc"] == "1"
    assert "enabled skill 1.0" in data["reasons"]["skill:review-skill"] and "delivered to reviewer" in data["reasons"]["skill:review-skill"]
    assert data["allow_private"] is False and data["conflicts"] == [] and data["degraded"] == []


def test_explain_all_covers_every_profile_with_and_without_role_plus_the_brain(world):
    views = world.resolver.explain_all()
    keys = [loadout_key(profile, role) for profile, role in loadout_keys()]
    assert list(views) == keys and len(keys) == 4 * 4 + 1
    assert views["code:reviewer"].loadout.role == "reviewer" and views["brain"].loadout.profile == BRAIN_PROFILE


# --------------------------------------------------------- conflicts, disabled


def test_a_conflicting_skill_version_resolves_to_the_highest_enabled_and_reports_the_loser(world):
    world.skills.import_text(skill_text("shared-skill", "2.0"))
    view = world.resolver.explain("fast")
    assert view.loadout.skill_ids == ("shared-skill",)
    assert {e.id: e.version for e in view.entries if e.kind == "skill"} == {"shared-skill": "2.0"}
    assert [(c.skill_id, c.winner_version, c.loser_version) for c in view.conflicts] == [("shared-skill", "2.0", "1.0")]
    assert view.as_dict()["conflicts"][0]["loser_version"] == "1.0"
    assert "shared-skill@2.0" in render_manifest(view) and "shared-skill@1.0" not in render_manifest(view)


def test_a_conflict_on_a_skill_the_loadout_does_not_hold_is_not_reported(world):
    world.skills.import_text(skill_text("code-skill", "2.0", profiles=["code"]))
    assert world.resolver.explain("fast").conflicts == ()
    assert [c.skill_id for c in world.resolver.explain("code").conflicts] == ["code-skill"]


def test_a_disabled_skill_is_absent_and_a_disabled_winner_hands_over(world):
    world.skills.disable("shared-skill", "1.0")
    assert "shared-skill" not in world.resolver.resolve("code").skill_ids
    assert "skill:shared-skill" not in world.resolver.resolve("code").reasons
    world.skills.enable("shared-skill", "1.0")
    world.skills.import_text(skill_text("shared-skill", "2.0"))
    world.skills.disable("shared-skill", "2.0")
    view = world.resolver.explain("fast")
    assert {e.id: e.version for e in view.entries if e.kind == "skill"} == {"shared-skill": "1.0"}
    assert view.conflicts == ()


def test_knowledge_settings_switch_each_kind_off_without_even_calling_its_provider(tmp_path):
    world = World(tmp_path, knowledge=lambda: KnowledgeSettings(wiki_enabled=False, codegraph_enabled=False, skills_enabled=False))
    loadout = world.resolver.resolve("code")
    assert (loadout.wiki_ids, loadout.codegraph_repos, loadout.skill_ids) == ((), (), ())
    assert loadout.memory_scopes == ("shared", f"project:{PROJECT}")
    assert world.codegraph.calls == []


# ------------------------------------------------------ isolation (critical)


NON_BRAIN = [(p, r) for p, r in loadout_keys() if p != BRAIN_PROFILE]


@pytest.mark.parametrize("leaky", [False, True], ids=["well-behaved-providers", "providers-ignoring-scope"])
@pytest.mark.parametrize(("profile", "role"), NON_BRAIN)
def test_private_memory_never_appears_in_a_shared_loadout_matrix(tmp_path, leaky, profile, role):
    world = World(tmp_path, leaky=leaky)
    view = world.resolver.explain(profile, role)
    loadout = view.loadout
    everything = {*loadout.wiki_ids, *loadout.codegraph_repos, *loadout.skill_ids}
    assert not everything & PRIVATE_IDS
    assert "private" not in loadout.memory_scopes and loadout.allow_private is False
    assert not any(PRIVATE_IDS & set(key.split(":", 1)[1:]) for key in loadout.reasons)
    manifest = render_manifest(view)
    assert not any(secret in manifest for secret in PRIVATE_IDS) and "private" not in manifest
    assert not any(secret in json.dumps(view.as_dict()) for secret in PRIVATE_IDS)


def test_a_provider_that_ignores_the_scope_cannot_widen_a_loadout(tmp_path):
    world = World(tmp_path, leaky=True)
    loadout = world.resolver.resolve("fast")  # shared only
    assert loadout.wiki_ids == ("shared-doc",) and loadout.codegraph_repos == ()


def test_private_reaches_the_brain_only(world):
    brain = world.resolver.resolve(BRAIN_PROFILE)
    assert "private" in brain.memory_scopes and brain.allow_private
    assert {"priv-doc", "priv-skill"} <= {*brain.wiki_ids, *brain.skill_ids}
    assert preset_rule(BRAIN_PROFILE).allow_private
    assert not any(preset_rule(profile, PROJECT).allow_private or "private" in preset_rule(profile, PROJECT).memory_scopes
                   for profile in ("desktop", "code", "fast", "general"))


def test_only_an_explicit_policy_rule_lets_private_reach_a_non_brain_loadout(tmp_path):
    rule = LoadoutRule(memory_scopes=("private", "shared"), allow_private=True)
    world = World(tmp_path, policy=lambda: LoadoutPolicy({"code": rule}))
    code = world.resolver.resolve("code")
    assert code.allow_private and "private" in code.memory_scopes
    assert {"priv-doc", "priv-skill"} <= {*code.wiki_ids, *code.skill_ids}
    assert "settings rule code" in code.reasons["scope:private"]
    for other in ("desktop", "fast", "general"):  # the rule is for `code` only
        assert not {*world.resolver.resolve(other).wiki_ids, *world.resolver.resolve(other).skill_ids} & PRIVATE_IDS


def test_a_rule_naming_private_without_allow_private_cannot_exist():
    with pytest.raises(ValueError, match="allow_private"):
        LoadoutRule(memory_scopes=("private",))
    with pytest.raises(ValueError, match="allow_private"):
        Loadout(profile="code", memory_scopes=("private",))


def test_the_resolver_filters_private_even_from_a_rule_that_bypassed_validation(tmp_path):
    rule = LoadoutRule(memory_scopes=("shared",))
    object.__setattr__(rule, "memory_scopes", ("private", "shared"))  # a future caller that skips __post_init__
    world = World(tmp_path, policy=lambda: LoadoutPolicy({"code": rule}))
    code = world.resolver.resolve("code")
    assert code.memory_scopes == ("shared",) and code.allow_private is False
    assert not {*code.wiki_ids, *code.skill_ids} & PRIVATE_IDS


def test_a_corrupt_stored_private_rule_falls_back_to_the_preset_never_to_private(tmp_path):
    block = {"loadouts": {"code": {"memory_scopes": ["private", "shared"], "allow_private": False}}}
    world = World(tmp_path, policy=lambda: read_loadout_policy(block))
    code = world.resolver.resolve("code")
    assert not {*code.wiki_ids, *code.skill_ids} & PRIVATE_IDS and "private" not in code.memory_scopes
    assert "preset code" in code.reasons["scope:shared"]


# ------------------------------------------------ scope pass-through, project


def test_every_provider_call_carries_an_explicit_scope(world):
    seen: list[AssetScope | None] = []

    class Spy(FakeProvider):
        def list(self, scope=None):
            seen.append(scope)
            return super().list(scope)

    spy_wiki = Spy(AssetKind.WIKI, [asset("shared-doc", AssetKind.WIKI, AssetScope.SHARED)])
    spy_code = Spy(AssetKind.CODEGRAPH, [asset("jarvis-aaaa", AssetKind.CODEGRAPH, AssetScope.PROJECT)])
    resolver = KnowledgeLoadoutResolver(wiki=spy_wiki, codegraph=spy_code, skills=world.skills, project_id=PROJECT)
    for profile, role in loadout_keys():
        resolver.resolve(profile, role)
    assert seen and all(scope is not None for scope in seen)
    assert set(spy_wiki.calls) == {AssetScope.SHARED, AssetScope.PROJECT, AssetScope.PRIVATE}
    assert set(spy_code.calls) == {AssetScope.PROJECT}  # CodeGraph is project-scoped: nothing else is ever asked


def test_a_shared_only_loadout_never_asks_a_provider_for_another_scope(tmp_path):
    world = World(tmp_path)
    world.resolver.resolve("fast")
    assert world.codegraph.calls == []  # fast has no code graph
    world.resolver.resolve("code")
    assert world.codegraph.calls == [AssetScope.PROJECT]


def test_the_project_scope_is_qualified_with_the_project_id(tmp_path):
    loadout = World(tmp_path, project_id="my.proj-1").resolver.resolve("code")
    assert "project:my.proj-1" in loadout.memory_scopes and "project" not in loadout.memory_scopes


def test_without_a_project_id_no_preset_grants_a_project_scope(tmp_path):
    world = World(tmp_path, project_id=None)
    for profile, role in loadout_keys():
        loadout = world.resolver.resolve(profile, role)
        assert not any(scope.startswith("project") for scope in loadout.memory_scopes)
        assert "proj-doc" not in loadout.wiki_ids and "proj-skill" not in loadout.skill_ids
        if profile != BRAIN_PROFILE:
            assert loadout.codegraph_repos == ()


@pytest.mark.parametrize("bad", ["", "a b", "x/y", ".dot", "p" * 120])
def test_an_unqualifiable_project_id_is_refused_at_construction(bad):
    with pytest.raises(ValueError):
        KnowledgeLoadoutResolver(project_id=bad)


# ------------------------------------------------------------- user rules


def test_a_settings_rule_replaces_the_preset_and_the_role_key_wins(tmp_path):
    policy = LoadoutPolicy({
        "code": LoadoutRule(memory_scopes=("shared",), codegraph=False),
        "code:reviewer": LoadoutRule(memory_scopes=("shared", f"project:{PROJECT}"), wiki=False, skills=False),
    })
    world = World(tmp_path, policy=lambda: policy)
    code = world.resolver.resolve("code")
    assert (code.memory_scopes, code.codegraph_repos, code.wiki_ids) == (("shared",), (), ("shared-doc",))
    reviewer = world.resolver.resolve("code", "reviewer")
    assert reviewer.wiki_ids == () and reviewer.skill_ids == () and reviewer.codegraph_repos == ("jarvis-aaaa",)
    assert "settings rule code:reviewer" in reviewer.reasons[f"scope:project:{PROJECT}"]
    # An unmentioned key keeps its preset.
    assert world.resolver.resolve("fast").skill_ids == ("shared-skill",)


def test_a_rule_is_read_from_the_settings_block_on_every_resolution(tmp_path):
    settings: dict = {}
    world = World(tmp_path, policy=lambda: read_loadout_policy(settings.get("memory")))
    assert world.resolver.resolve("fast").wiki_ids == ("shared-doc",)
    apply_memory_settings(settings, {"loadouts": {"fast": {"memory_scopes": ["shared"], "wiki": False}}})
    assert world.resolver.resolve("fast").wiki_ids == ()
    apply_memory_settings(settings, {"loadouts": {"fast": None}})
    assert world.resolver.resolve("fast").wiki_ids == ("shared-doc",)


# ---------------------------------------------------- failure, truncation


def test_a_failing_provider_contributes_nothing_and_is_reported(tmp_path):
    world = World(tmp_path)
    broken = FakeProvider(AssetKind.WIKI, [], fail=MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "disk gone"))
    resolver = KnowledgeLoadoutResolver(wiki=broken, codegraph=world.codegraph, skills=world.skills, project_id=PROJECT)
    view = resolver.explain("code")
    assert view.loadout.wiki_ids == () and view.loadout.codegraph_repos == ("jarvis-aaaa",) and view.loadout.skill_ids
    assert ("wiki", "memory_unavailable") in view.degraded
    crash = KnowledgeLoadoutResolver(wiki=FakeProvider(AssetKind.WIKI, [], fail=RuntimeError("boom")))
    assert ("wiki", "provider_failed") in crash.explain("code").degraded


def test_resolve_never_raises_even_when_the_policy_or_registry_blows_up(tmp_path):
    def explode():
        raise RuntimeError("settings unreadable")

    resolver = KnowledgeLoadoutResolver(policy=explode)
    loadout = resolver.resolve("code", "reviewer")
    assert loadout.is_empty and (loadout.profile, loadout.role) == ("code", "reviewer")
    assert resolver.explain("code").degraded == (("resolver", "resolver_failed"),)

    class BrokenRegistry:
        def catalog(self):
            raise RuntimeError("registry gone")

    view = KnowledgeLoadoutResolver(skills=BrokenRegistry()).explain("code")
    assert view.loadout.skill_ids == () and ("skill", "provider_failed") in view.degraded


def test_an_oversized_kind_is_truncated_to_the_contract_bound_and_reported():
    many = [asset(f"doc-{i:03}", AssetKind.WIKI, AssetScope.SHARED) for i in range(MAX_LOADOUT_ENTRIES + 6)]
    view = KnowledgeLoadoutResolver(wiki=FakeProvider(AssetKind.WIKI, many)).explain("fast")
    assert len(view.loadout.wiki_ids) == MAX_LOADOUT_ENTRIES
    assert ("wiki", "loadout_truncated") in view.degraded
    assert {e.id for e in view.entries if e.kind == "wiki"} == set(view.loadout.wiki_ids)
    assert not any(key.startswith("wiki:doc-0") and key.split(":")[1] not in view.loadout.wiki_ids for key in view.loadout.reasons)


def test_register_knowledge_with_nothing_registered_grants_only_preset_scopes():
    loadout = register_knowledge().resolve("code")
    assert loadout.memory_scopes == ("shared",) and (loadout.wiki_ids, loadout.skill_ids) == ((), ())


# --------------------------------------------------------------- manifest


def test_the_manifest_lists_ids_and_versions_only_never_bodies_or_titles(tmp_path):
    world = World(tmp_path)
    world.wiki.import_text("https://example.test/t", "TITLE-SENTINEL", "BODY-SENTINEL", AssetScope.SHARED, "titled-doc")
    manifest = manifest_for(world.resolver, "code", "reviewer")
    assert manifest.startswith(MANIFEST_MARK) and "rôle reviewer" in manifest and "profil code" in manifest
    for expected in ("review-skill@1.0", "titled-doc@1", "jarvis-aaaa", f"project:{PROJECT}"):
        assert expected in manifest
    for forbidden in ("BODY-SENTINEL", "TITLE-SENTINEL", "BODY-OF-", "skill\n", "Review a change"):
        assert forbidden not in manifest


def test_the_manifest_never_exceeds_the_cap_and_says_how_much_it_dropped():
    entries = tuple(ManifestEntry("wiki", f"{'long-identifier-' * 6}{i:02}", "1") for i in range(MAX_LOADOUT_ENTRIES))
    view = LoadoutView(Loadout(profile="code", role="reviewer"), entries)
    manifest = render_manifest(view)
    assert 0 < len(manifest) <= MAX_LOADOUT_MANIFEST_CHARS == 1_024
    dropped = MAX_LOADOUT_ENTRIES - manifest.count("@1")
    assert dropped > 0 and f"(+{dropped} autres" in manifest
    assert len(render_manifest(view, limit=120)) <= 120 and render_manifest(view, limit=0) == ""


def test_the_cap_drops_from_the_longest_group_first_keeping_the_small_ones():
    entries = (
        *(ManifestEntry("wiki", f"{'w' * 40}{i:02}") for i in range(40)),
        ManifestEntry("skill", "tiny-skill", "1"), ManifestEntry("scope", "shared"),
    )
    manifest = render_manifest(LoadoutView(Loadout(profile="fast"), entries))
    assert len(manifest) <= MAX_LOADOUT_MANIFEST_CHARS
    assert "tiny-skill@1" in manifest and "mémoire: shared" in manifest


def test_an_empty_loadout_renders_no_manifest(world):
    assert render_manifest(LoadoutView(Loadout(profile="code"))) == ""
    assert manifest_for(KnowledgeLoadoutResolver(), "code") != ""  # a shared scope alone is still worth stating


# ----------------------------------------------------------- hook snapshot


def test_the_snapshot_round_trips_each_manifest_and_carries_the_inspectable_view(world, tmp_path):
    runtime = tmp_path / "runtime"
    views = world.resolver.explain_all()
    path = write_loadout_snapshot(runtime, views, now=NOW)
    assert path == snapshot_path(runtime)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == 1 and data["written_at"] == NOW.isoformat()
    assert data["loadouts"]["code:reviewer"]["view"]["skill_ids"] == list(views["code:reviewer"].loadout.skill_ids)
    for (profile, role), key in ((k, loadout_key(*k)) for k in loadout_keys()):
        assert read_manifest(runtime, profile, role) == render_manifest(views[key])
    assert not [p for p in runtime.iterdir() if p.name != path.name]  # no temp file left behind


def test_the_snapshot_is_rewritten_atomically_over_the_previous_one(world, tmp_path):
    write_loadout_snapshot(tmp_path, world.resolver.explain_all())
    world.skills.disable("shared-skill", "1.0")
    write_loadout_snapshot(tmp_path, world.resolver.explain_all())
    assert "shared-skill" not in read_manifest(tmp_path, "fast", None)


@pytest.mark.parametrize(
    "content",
    [
        json.dumps({"schema": 99, "loadouts": {"fast": {"manifest": f"{MANIFEST_MARK} x"}}}),
        json.dumps({"schema": 1, "loadouts": {}}),
        json.dumps({"schema": 1, "loadouts": {"fast": {"manifest": "no mark here"}}}),
        json.dumps({"schema": 1, "loadouts": {"fast": {"manifest": 5}}}),
        json.dumps({"schema": 1, "loadouts": {"fast": "x"}}),
        json.dumps([1, 2]),
        json.dumps({"schema": 1, "loadouts": []}),
    ],
)
def test_a_snapshot_that_does_not_fit_the_contract_yields_no_manifest(tmp_path, content):
    snapshot_path(tmp_path).write_text(content, encoding="utf-8")
    assert read_manifest(tmp_path, "fast", None) == ""


def test_the_snapshot_reader_is_defensive_about_a_hostile_file(tmp_path):
    assert read_manifest(tmp_path, "fast", None) == ""  # absent
    hostile = f"{MANIFEST_MARK} profil fast\x00\x1b[31m" + "A" * 5_000
    snapshot_path(tmp_path).write_text(
        json.dumps({"schema": 1, "loadouts": {"fast": {"manifest": hostile}}}), encoding="utf-8")
    text = read_manifest(tmp_path, "fast", None)
    assert len(text) <= MAX_LOADOUT_MANIFEST_CHARS and "\x00" not in text and "\x1b" not in text
    snapshot_path(tmp_path).write_text("x" * (loadout_snapshot.MAX_SNAPSHOT_BYTES + 1), encoding="utf-8")
    assert read_manifest(tmp_path, "fast", None) == ""
    snapshot_path(tmp_path).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):  # JSONDecodeError: the hook catches it and leaves the call alone
        read_manifest(tmp_path, "fast", None)


# --------------------------------------------------------------- the hook


def agent_call(description: str = "[code] Corriger le bug", prompt: str = "Fais-le.", **extra) -> dict:
    return {
        "hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "toolu-1",
        "tool_input": {"description": description, "prompt": prompt, **extra},
    }


def brief(output: dict) -> str:
    return str((output.get("hookSpecificOutput") or {}).get("updatedInput", {}).get("prompt") or "")


@pytest.fixture
def snapshot(world, tmp_path):
    runtime = tmp_path / "runtime"
    write_loadout_snapshot(runtime, world.resolver.explain_all())
    return runtime


def test_the_hook_appends_the_loadout_manifest_after_the_charter_and_the_brief(snapshot, world):
    output = routing_hook.run(agent_call(), snapshot)
    text = brief(output)
    assert text.startswith(CHARTER_MARK) and "Fais-le." in text
    assert text.endswith(render_manifest(world.resolver.explain("code")))
    assert text.index("Fais-le.") < text.index(MANIFEST_MARK)
    assert len(text.split(MANIFEST_MARK, 1)[1]) <= MAX_LOADOUT_MANIFEST_CHARS
    assert "Manifeste du loadout" in output["hookSpecificOutput"]["permissionDecisionReason"]
    assert output["hookSpecificOutput"]["updatedInput"]["description"] == "[code] Corriger le bug"


@pytest.mark.parametrize(
    ("description", "key"),
    [
        ("[code] [reviewer] Relire", "code:reviewer"),
        ("[reviewer] Relire", "general:reviewer"),
        ("[general] [research] Chercher", "general:research"),
        ("[code] Relire", "code"),
        ("[fast] [coder] Écrire", "fast:coder"),
        ("sans marqueur", "general"),
        ("[code] [inconnu] Relire", "code"),
    ],
)
def test_the_hook_picks_the_snapshot_entry_from_the_profile_and_role_markers(snapshot, world, description, key):
    expected = render_manifest(world.resolver.explain_all()[key])
    assert brief(routing_hook.run(agent_call(description), snapshot)).endswith(expected)
    assert routing_hook.strip_profile(description).startswith(("Relire", "Chercher", "Écrire", "sans", "[inconnu]"))


def test_the_charter_keeps_the_profile_and_role_markers_in_front(snapshot):
    text = brief(routing_hook.run(agent_call("x", prompt="[code] [reviewer] Relire le diff."), snapshot))
    assert text.startswith("[code] [reviewer] ") and CHARTER_MARK in text


def test_without_a_snapshot_the_agent_call_is_exactly_what_it_was(tmp_path):
    assert read_manifest(tmp_path, "code", None) == ""
    output = routing_hook.run(agent_call(), tmp_path)
    assert MANIFEST_MARK not in brief(output)
    assert brief(output).startswith(CHARTER_MARK) and brief(output).endswith("Fais-le.")
    assert "Manifeste" not in output["hookSpecificOutput"]["permissionDecisionReason"]
    assert not (tmp_path / "errors.jsonl").exists()


@pytest.mark.parametrize("content", ["{not json", "\x00\x00", "[]", ""])
def test_a_broken_snapshot_leaves_the_agent_call_untouched_and_silent(snapshot, tmp_path, capsys, content):
    clean = brief(routing_hook.run(agent_call(), tmp_path / "other"))
    snapshot_path(snapshot).write_text(content, encoding="utf-8")
    output = routing_hook.run(agent_call(), snapshot)
    assert brief(output) == clean and MANIFEST_MARK not in brief(output)
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert capsys.readouterr().out == ""


def test_a_failure_while_reading_the_snapshot_is_traced_and_never_raised(snapshot, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("disk unplugged")

    monkeypatch.setattr(loadout_snapshot, "read_manifest", boom)
    output = routing_hook.run(agent_call(), snapshot)
    assert brief(output).startswith(CHARTER_MARK) and MANIFEST_MARK not in brief(output)
    [failure] = [e for e in (*read_jsonl_tail(snapshot / "errors.jsonl"), *read_jsonl_tail(snapshot / "trace.jsonl"))
                 if e["kind"] == "agent.loadout.failed"]
    assert failure["data"]["code"] == "loadout_snapshot_failed" and failure["data"]["exception_type"] == "OSError"


def test_the_hook_never_touches_the_network(snapshot, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("the routing hook opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert MANIFEST_MARK in brief(routing_hook.run(agent_call(), snapshot))


def test_a_brief_that_already_carries_a_manifest_is_not_given_a_second_one(snapshot):
    first = brief(routing_hook.run(agent_call(), snapshot))
    again = brief(routing_hook.run(agent_call(prompt=first), snapshot))
    assert again == ""  # signed and already carrying a manifest: nothing left to rewrite
    assert routing_hook.loadout_input(agent_call(prompt=first), snapshot, first) is None


def test_a_tool_that_is_not_a_subagent_launch_gets_no_manifest(snapshot):
    event = {"tool_name": "Bash", "tool_input": {"command": "ls", "prompt": "ls"}}
    assert routing_hook.run(event, snapshot) == {}
    assert routing_hook.loadout_input(event, snapshot, "ls") is None
    assert routing_hook.loadout_input(agent_call(), snapshot, "   ") is None


def test_a_refused_call_stays_refused_and_carries_no_manifest(snapshot, monkeypatch):
    codex = {"id": "codex", "label": "Codex", "model_provider": "openai", "capabilities": ["code", "semantic"],
             "available": True, "error": ""}
    monkeypatch.setattr(routing_hook, "local_agents", lambda: [codex])
    (snapshot / "control-center-settings.json").write_text(json.dumps({"agent_routing": {
        "enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude", "model": "petit"}],
                                               "allow_general_fallback": False}}}}), encoding="utf-8")
    output = routing_hook.run(agent_call(), snapshot)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "updatedInput" not in output["hookSpecificOutput"]


def test_the_trace_records_what_was_injected_without_its_text(snapshot, world):
    routing_hook.run(agent_call("[code] [reviewer] Relire"), snapshot)
    [event] = [e for e in read_jsonl_tail(snapshot / "trace.jsonl") if e["kind"] == "agent.loadout.applied"]
    data = event["data"]
    assert (data["code"], data["profile"], data["role"]) == ("loadout_manifest_applied", "code", "reviewer")
    assert data["tool_use_id"] == "toolu-1"
    assert 0 < data["manifest_chars"] <= MAX_LOADOUT_MANIFEST_CHARS + len(routing_hook.BRIEF_GAP)
    assert MANIFEST_MARK not in json.dumps(event) and "review-skill" not in json.dumps(event)
