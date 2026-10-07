"""Skills registry (Slice 09): discovery, enable/disable, version arbitration, user-initiated import.

Every test works in a temp directory; nothing touches a real data root.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import jarvis
from jarvis.adapters.knowledge_skills import SKILL_FILE, STATE_FILE, SkillRegistry
from jarvis.adapters.memory_frontmatter import compose
from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.knowledge import AssetKind, AssetScope
from jarvis.domain.memory import CapabilityStatus, MemoryErrorCode, MemoryStoreError
from jarvis.domain.skills import (
    CONFLICT_DUPLICATE,
    CONFLICT_LOWER_VERSION,
    SkillRecord,
    arbitrate,
    version_key,
)
from jarvis.ports.knowledge import KnowledgeAssetProvider


def skill_text(
    skill_id: str = "code-review",
    version: str = "1.0",
    *,
    scope: str = "shared",
    profiles: list[str] | None = None,
    description: str = "Review a change before merge",
    source: str = "manual",
    body: str = "# Steps\n\nRead the diff first.\n",
) -> str:
    meta: dict = {"id": skill_id, "version": version, "description": description, "scope": scope, "source": source}
    if profiles is not None:
        meta["allowed_profiles"] = profiles
    return compose(meta, body)


def place(root, directory: str, text: str) -> None:
    (root / directory).mkdir(parents=True, exist_ok=True)
    (root / directory / SKILL_FILE).write_text(text, encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    return tmp_path / "skills"


@pytest.fixture
def registry(root):
    return SkillRegistry(root)


def test_tests_run_against_this_worktree():
    assert Path(jarvis.__file__).resolve().parents[1] == Path(__file__).resolve().parents[2]


def test_registry_is_a_knowledge_asset_provider(registry):
    assert isinstance(registry, KnowledgeAssetProvider)
    assert registry.kind is AssetKind.SKILL


# ------------------------------------------------------------------ discovery


def test_a_copied_in_skill_is_discovered_but_off_until_enabled(registry, root):
    place(root, "code-review", skill_text())
    view = registry.catalog()
    assert [(r.id, r.version, r.enabled) for r in view.records] == [("code-review", "1.0", False)]
    assert view.winners == () and registry.list() == ()
    with pytest.raises(MemoryStoreError) as caught:
        registry.read("code-review")
    assert caught.value.code is MemoryErrorCode.NOT_FOUND
    registry.enable("code-review", "1.0")
    assert [a.asset_id for a in registry.list()] == ["code-review"]


def test_front_matter_fields_reach_the_asset(registry, root):
    place(root, "x", skill_text("caveman", "2.1", scope="project", profiles=["code", "reviewer"], source="import:/a/b"))
    registry.enable("caveman", "2.1")
    asset = registry.read("caveman")
    assert (asset.version, asset.scope, asset.kind) == ("2.1", AssetScope.PROJECT, AssetKind.SKILL)
    assert asset.source.uri == "import:/a/b" and asset.source.version_or_commit == "2.1"
    assert asset.source.path == f"x/{SKILL_FILE}"
    assert asset.summary == "Review a change before merge"
    assert "Read the diff first." in asset.body
    record = registry.catalog().records[0]
    assert record.allowed_profiles == ("code", "reviewer")
    assert registry.list()[0].body == ""  # list never carries the instructions


def test_the_directory_name_is_a_hint_the_front_matter_id_is_the_identity(registry, root):
    place(root, "whatever-name", skill_text("real-id"))
    registry.enable("real-id", "1.0")
    assert registry.read("real-id").asset_id == "real-id"


@pytest.mark.parametrize(
    "text",
    [
        "no front matter at all\n",
        '---\nid: "a"\nthis is not json\n---\nbody\n',
        compose({"id": "a", "version": "1", "description": "d", "scope": "shared"}, "body"),  # no source
        skill_text(scope="world"),
        skill_text(version="v1"),
        skill_text(version="1.2.3.4.5"),
        skill_text(version="١٢"),  # Arabic-Indic digits: `\d` would have accepted them
        skill_text(version="1.２"),  # fullwidth digit
        skill_text(skill_id="has space"),
        skill_text(skill_id="../escape"),
        skill_text(description=""),
        skill_text(body="   \n"),
        skill_text(profiles=["a"] * 2),
        compose({"id": "a", "version": 1, "description": "d", "scope": "shared", "source": "s"}, "body"),
        compose({"id": "a", "version": "1", "description": "d", "scope": "shared", "source": "s",
                 "allowed_profiles": "code"}, "body"),
    ],
)
def test_an_invalid_skill_is_reported_and_never_listed(registry, root, text):
    place(root, "good", skill_text("good-one"))
    place(root, "bad", text)
    registry.enable("good-one", "1.0")
    view = registry.catalog()
    assert [name for name, _reason in view.invalid] == ["bad"]
    assert all(reason for _name, reason in view.invalid)
    assert [r.id for r in view.records] == ["good-one"]
    assert [a.asset_id for a in registry.list()] == ["good-one"]
    state = registry.status()
    assert state.status is CapabilityStatus.DEGRADED and state.reason_code == "skills_invalid"


def test_an_oversized_skill_is_invalid_not_read(registry, root):
    place(root, "huge", skill_text(body="x" * 300_000))
    assert [name for name, _ in registry.catalog().invalid] == ["huge"]


def test_a_directory_without_skill_md_and_hidden_entries_are_ignored(registry, root):
    (root / "empty-dir").mkdir()
    (root / ".hidden").mkdir()
    (root / "note.txt").write_text("x", encoding="utf-8")
    view = registry.catalog()
    assert view.records == () and view.invalid == ()
    assert registry.status().is_ok


def test_a_symlinked_skill_file_or_directory_is_refused(registry, root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / SKILL_FILE).write_text(skill_text("leak"), encoding="utf-8")
    try:
        os.symlink(outside, root / "linked-dir", target_is_directory=True)
        (root / "real").mkdir()
        os.symlink(outside / SKILL_FILE, root / "real" / SKILL_FILE)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need privileges on this host")
    view = registry.catalog()
    assert view.records == ()
    assert sorted(name for name, _ in view.invalid) == ["linked-dir", "real"]


# ------------------------------------------------------------- enable/disable


def test_disable_removes_the_skill_everywhere_and_enable_restores_it(registry, root):
    place(root, "a", skill_text("alpha", description="alpha skill about tests"))
    registry.enable("alpha", "1.0")
    assert registry.search("tests", 5)
    registry.disable("alpha", "1.0")
    assert registry.list() == () and registry.search("tests", 5) == []
    with pytest.raises(MemoryStoreError):
        registry.read("alpha")
    assert [r.enabled for r in registry.catalog().records] == [False]
    registry.enable("alpha", "1.0")
    assert registry.read("alpha").asset_id == "alpha"


def test_enable_of_an_unknown_skill_or_version_is_not_found(registry, root):
    place(root, "a", skill_text("alpha"))
    for args in (("nope", "1.0"), ("alpha", "9.9"), ("alpha", "not-a-version")):
        with pytest.raises(MemoryStoreError) as caught:
            registry.enable(*args)
        assert caught.value.code is MemoryErrorCode.NOT_FOUND


def test_enable_state_survives_a_new_registry_and_is_a_plain_file(registry, root):
    place(root, "a", skill_text("alpha"))
    registry.enable("alpha", "1.0")
    assert json.loads((root / STATE_FILE).read_text(encoding="utf-8"))["enabled"] == ["alpha@1.0"]
    assert [a.asset_id for a in SkillRegistry(root).list()] == ["alpha"]


def test_a_corrupt_state_file_turns_everything_off_and_never_raises(registry, root):
    place(root, "a", skill_text("alpha"))
    registry.enable("alpha", "1.0")
    (root / STATE_FILE).write_text("{not json", encoding="utf-8")
    assert registry.list() == ()
    registry.enable("alpha", "1.0")  # recovers by rewriting the file
    assert [a.asset_id for a in registry.list()] == ["alpha"]


# ----------------------------------------------------------- version conflicts


def test_highest_enabled_version_wins_and_the_loser_is_reported(registry, root):
    place(root, "review", skill_text("review", "1.0", body="old"))
    place(root, "review--v2", skill_text("review", "2.0", body="new"))
    registry.enable("review", "1.0")
    registry.enable("review", "2.0")
    view = registry.catalog()
    assert [(w.id, w.version) for w in view.winners] == [("review", "2.0")]
    assert [c.as_dict() for c in view.conflicts] == [{
        "skill_id": "review", "winner_version": "2.0", "loser_version": "1.0",
        "loser_directory": "review", "reason": CONFLICT_LOWER_VERSION,
    }]
    assert registry.read("review").body == "new" and registry.read("review").version == "2.0"
    assert [a.version for a in registry.list()] == ["2.0"]
    state = registry.status()
    assert state.status is CapabilityStatus.DEGRADED and state.reason_code == "skills_version_conflict"


def test_a_disabled_higher_version_does_not_win_and_is_not_a_conflict(registry, root):
    place(root, "review", skill_text("review", "1.0", body="old"))
    place(root, "review--v2", skill_text("review", "2.0", body="new"))
    registry.enable("review", "1.0")
    view = registry.catalog()
    assert [(w.version) for w in view.winners] == ["1.0"] and view.conflicts == ()
    assert registry.read("review").body == "old"
    assert registry.status().is_ok


def test_disabling_the_winner_promotes_the_next_enabled_version(registry, root):
    place(root, "review", skill_text("review", "1.0", body="old"))
    place(root, "review--v2", skill_text("review", "2.0", body="new"))
    registry.enable("review", "1.0")
    registry.enable("review", "2.0")
    registry.disable("review", "2.0")
    assert registry.read("review").body == "old"
    assert registry.catalog().conflicts == ()


def test_versions_compare_numerically_not_as_text():
    assert version_key("10") > version_key("9")
    assert version_key("1.10") > version_key("1.9")
    assert version_key("1") == version_key("1.0.0")
    with pytest.raises(ValueError):
        version_key("1.x")


def test_numeric_ordering_decides_a_real_conflict(registry, root):
    for directory, version in (("a", "9"), ("b", "10"), ("c", "1.10")):
        place(root, directory, skill_text("s", version, body=f"v{version}"))
        registry.enable("s", version)
    assert registry.read("s").version == "10"
    assert sorted(c.loser_version for c in registry.catalog().conflicts) == ["1.10", "9"]


def test_same_id_and_version_in_two_directories_is_a_reported_duplicate(registry, root):
    place(root, "b-copy", skill_text("dup", "1.0", body="B"))
    place(root, "a-copy", skill_text("dup", "1.0", body="A"))
    registry.enable("dup", "1.0")  # one switch for the pair
    view = registry.catalog()
    assert [(w.directory) for w in view.winners] == ["a-copy"]  # name order breaks the tie, deterministically
    assert [(c.loser_directory, c.reason) for c in view.conflicts] == [("b-copy", CONFLICT_DUPLICATE)]


def test_arbitrate_is_pure_over_records():
    def record(version: str, enabled: bool, directory: str) -> SkillRecord:
        return SkillRecord("s", version, "d", AssetScope.SHARED, "src", directory, enabled=enabled)

    winners, conflicts = arbitrate([record("1", True, "a"), record("3", False, "b"), record("2", True, "c")])
    assert [w.version for w in winners] == ["2"]
    assert [(c.loser_version, c.loser_directory) for c in conflicts] == [("1", "a")]
    assert arbitrate([record("1", False, "a")]) == ((), ())


# -------------------------------------------------------------- read / search


def test_read_denies_a_scope_mismatch_and_refuses_hostile_ids(registry, root):
    place(root, "a", skill_text("alpha", scope="private"))
    registry.enable("alpha", "1.0")
    with pytest.raises(MemoryStoreError) as caught:
        registry.read("alpha", AssetScope.SHARED)
    assert caught.value.code is MemoryErrorCode.SCOPE_DENIED
    assert registry.read("alpha", AssetScope.PRIVATE).scope is AssetScope.PRIVATE
    for hostile in ("..", "../alpha", "a/b", "", "x" * 300, 5):
        with pytest.raises(MemoryStoreError) as hit:
            registry.read(hostile)  # type: ignore[arg-type]
        assert hit.value.code is MemoryErrorCode.NOT_FOUND


def test_list_and_search_honour_an_explicit_scope(registry, root):
    place(root, "a", skill_text("alpha", scope="private", description="private notes helper"))
    place(root, "b", skill_text("beta", scope="shared", description="shared notes helper"))
    registry.enable("alpha", "1.0")
    registry.enable("beta", "1.0")
    assert [a.asset_id for a in registry.list(AssetScope.SHARED)] == ["beta"]
    assert [a.asset_id for a in registry.list(AssetScope.PRIVATE)] == ["alpha"]
    assert [a.asset_id for a in registry.list(AssetScope.PROJECT)] == []
    assert [h.asset.asset_id for h in registry.search("notes", 10, AssetScope.SHARED)] == ["beta"]
    assert sorted(h.asset.asset_id for h in registry.search("notes", 10)) == ["alpha", "beta"]
    assert registry.search("", 5) == [] and registry.search("zzz-none", 5) == []


def test_rebuild_has_no_derived_state_and_counts_effective_skills(registry, root):
    place(root, "a", skill_text("alpha"))
    place(root, "b", skill_text("beta"))
    registry.enable("alpha", "1.0")
    before = sorted(p.name for p in root.iterdir())
    assert registry.rebuild() == 1
    assert sorted(p.name for p in root.iterdir()) == before


# --------------------------------------------------------------------- import


def test_import_text_is_user_initiated_validated_and_enabled(registry, root):
    record = registry.import_text(skill_text("caveman", "1.0"))
    assert (record.id, record.version, record.enabled, record.directory) == ("caveman", "1.0", True, "caveman")
    assert registry.read("caveman").body.startswith("# Steps")
    assert (root / "caveman" / SKILL_FILE).read_text(encoding="utf-8") == skill_text("caveman", "1.0")


def test_import_without_enabling_leaves_the_skill_off(registry):
    record = registry.import_text(skill_text("quiet"), enable=False)
    assert record.enabled is False and registry.list() == ()
    registry.enable("quiet", "1.0")
    assert registry.list()


def test_a_newer_version_is_imported_beside_the_old_one_and_wins(registry, root):
    registry.import_text(skill_text("review", "1.0", body="old"))
    record = registry.import_text(skill_text("review", "2.0", body="new"))
    assert record.directory == "review--v2.0"
    assert registry.read("review").body == "new"
    assert [(c.loser_version) for c in registry.catalog().conflicts] == ["1.0"]
    assert (root / "review" / SKILL_FILE).exists()  # the old version stays on disk


def test_importing_the_same_id_and_version_twice_is_refused(registry):
    registry.import_text(skill_text("review", "1.0"))
    with pytest.raises(ValueError, match="already imported"):
        registry.import_text(skill_text("review", "1.0.0", body="other"))


def test_an_invalid_import_writes_nothing(registry, root):
    for text in ("plain text", skill_text(scope="nope"), skill_text(body="")):
        with pytest.raises(ValueError):
            registry.import_text(text)
    assert [p.name for p in root.iterdir()] == []


def test_import_file_reads_a_file_or_a_directory(registry, tmp_path):
    source = tmp_path / "download"
    source.mkdir()
    (source / SKILL_FILE).write_text(skill_text("from-dir"), encoding="utf-8")
    other = tmp_path / "loose.md"
    other.write_text(skill_text("from-file"), encoding="utf-8")
    assert registry.import_file(source).id == "from-dir"
    assert registry.import_file(other).id == "from-file"
    assert sorted(a.asset_id for a in registry.list()) == ["from-dir", "from-file"]
    assert (source / SKILL_FILE).exists() and other.exists()  # the source is never moved or touched


def test_import_file_refuses_missing_oversized_and_linked_sources(registry, tmp_path):
    with pytest.raises(ValueError):
        registry.import_file(tmp_path / "missing.md")
    big = tmp_path / "big.md"
    big.write_text(skill_text(body="x" * 300_000), encoding="utf-8")
    with pytest.raises(ValueError):
        registry.import_file(big)
    real = tmp_path / "real.md"
    real.write_text(skill_text("linked"), encoding="utf-8")
    try:
        os.symlink(real, tmp_path / "link.md")
    except (OSError, NotImplementedError):
        return
    with pytest.raises(MemorySecurityError):
        registry.import_file(tmp_path / "link.md")
    with pytest.raises(MemorySecurityError):
        registry.import_file("bad\x00path")


def test_there_is_no_execution_and_no_autonomous_path(registry):
    public = {name for name in dir(registry) if not name.startswith("_")}
    assert not {name for name in public if name.startswith(("run", "exec", "extract", "publish", "share"))}
