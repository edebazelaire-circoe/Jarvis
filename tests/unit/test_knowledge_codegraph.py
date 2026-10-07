"""CodeGraph provider (memory handoff, Slice 08). Contract page: `docs/codegraph.md`.

The fixture repo lives in `tests/fixtures/codegraph_repo` without a `.git`; each
test copies it to a temp dir and creates its git state there.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

import pytest

from jarvis.adapters.knowledge_codegraph import (
    CONFIDENCE,
    CodeGraphProvider,
    GraphAnswer,
    repo_id,
)
from jarvis.domain.knowledge import AssetKind, AssetScope
from jarvis.domain.memory import CapabilityStatus, MemoryErrorCode, MemoryStoreError
from jarvis.ports.knowledge import KnowledgeAssetProvider

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "codegraph_repo"
REPO_ROOT = Path(__file__).resolve().parents[2]


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.email=t@example.test", "-c", "user.name=t", "-c", "commit.gpgsign=false",
         "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return done.stdout.strip()


def commit_all(repo: Path, message: str = "change") -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    target = tmp_path / "work" / "sample"
    shutil.copytree(FIXTURE, target)
    git(target, "init", "-q")
    commit_all(target, "fixture")
    return target


@pytest.fixture
def provider(tmp_path: Path, repo: Path) -> CodeGraphProvider:
    return CodeGraphProvider(tmp_path / "knowledge" / "codegraph", [repo])


def rows(answer: GraphAnswer, *keys: str) -> list[tuple]:
    return [tuple(item[k] for k in keys) for item in answer.items]


def dump(provider: CodeGraphProvider) -> dict[str, list[tuple]]:
    """Whole derived graph minus the snapshot clock, comparable between two builds."""

    con = sqlite3.connect(provider.db_path())
    try:
        out = {
            table: sorted(con.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
            for table in ("files", "symbols", "edges")
        }
        out["meta"] = sorted(
            (k, v) for k, v in con.execute("SELECT key, value FROM meta") if k not in ("indexed_at", "tree"))
        return out
    finally:
        con.close()


# ------------------------------------------------------------- known fixture graph
def test_symbol_definitions_exact(provider: CodeGraphProvider) -> None:
    assert rows(provider.symbol("helper"), "id", "kind", "line") == [("pkg/util.py::helper", "function", 1)]
    assert rows(provider.symbol("Engine.run"), "id", "kind", "line") == [("pkg/core.py::Engine.run", "method", 5)]
    assert rows(provider.symbol("pkg/core.py::Engine"), "id", "kind", "line") == [("pkg/core.py::Engine", "class", 4)]
    assert provider.symbol("nope").items == ()


def test_usages_exact(provider: CodeGraphProvider) -> None:
    assert rows(provider.usages("helper"), "path", "line", "kind", "in") == [
        ("pkg/core.py", 1, "import", "pkg/core.py::<module>"),
        ("pkg/core.py", 6, "call", "pkg/core.py::Engine.run"),
    ]
    assert rows(provider.usages("start"), "path", "line", "kind", "in") == [
        ("app.py", 1, "import", "app.py::<module>"),
        ("app.py", 6, "call", "app.py::main"),
    ]
    assert rows(provider.usages("Engine"), "path", "line", "kind", "in") == [
        ("pkg/core.py", 10, "call", "pkg/core.py::start"),
        ("pkg/models.py", 1, "import", "pkg/models.py::<module>"),
        ("pkg/models.py", 5, "call", "pkg/models.py::build"),
    ]
    assert provider.usages("unused").items == ()


def test_impact_exact(provider: CodeGraphProvider) -> None:
    assert rows(provider.impact("helper"), "id", "depth", "via") == [
        ("pkg/core.py::Engine.run", 1, "pkg/util.py::helper"),
        ("pkg/core.py::start", 2, "pkg/core.py::Engine.run"),
        ("app.py::main", 3, "pkg/core.py::start"),
        ("app.py::<module>", 4, "app.py::main"),
    ]
    assert rows(provider.impact("Engine"), "id", "depth") == [
        ("pkg/core.py::start", 1),
        ("pkg/models.py::build", 1),
        ("app.py::main", 2),
        ("app.py::<module>", 3),
    ]
    assert provider.impact("unused").items == ()
    assert provider.impact("main").truncated == ()


def test_neighbors_symbol_and_file(provider: CodeGraphProvider) -> None:
    around = provider.neighbors("pkg/core.py::start")
    assert rows(around, "direction", "relation", "id") == [
        ("in", "call", "app.py::main"),
        ("out", "call", "pkg/core.py::Engine"),
        ("out", "call", "pkg/core.py::Engine.run"),
    ]
    file_edges = provider.neighbors("pkg/core.py")
    assert rows(file_edges, "direction", "relation", "id") == [
        ("in", "import", "app.py"),
        ("in", "import", "pkg/models.py"),
        ("out", "defines", "pkg/core.py::Engine"),
        ("out", "defines", "pkg/core.py::Engine.run"),
        ("out", "defines", "pkg/core.py::start"),
        ("out", "import", "pkg/util.py"),
    ]
    assert rows(provider.neighbors("web/page.js"), "direction", "id") == [("out", "web/lib.js")]


def test_path_symbols_files_and_absence(provider: CodeGraphProvider) -> None:
    assert [s["id"] for s in provider.path("main", "helper").items] == [
        "app.py::main", "pkg/core.py::start", "pkg/core.py::Engine.run", "pkg/util.py::helper"]
    assert [s["id"] for s in provider.path("app.py", "pkg/util.py").items] == [
        "app.py", "pkg/core.py", "pkg/util.py"]
    assert provider.path("helper", "main").items == ()
    shallow = provider.path("main", "helper", max_depth=2)
    assert shallow.items == () and shallow.truncated == ("depth",)


def test_answers_carry_snapshot_and_confidence(provider: CodeGraphProvider, repo: Path) -> None:
    answer = provider.usages("helper")
    snap = answer.snapshot
    assert snap.repo == str(repo.resolve())
    assert snap.commit == git(repo, "rev-parse", "HEAD")
    assert snap.stale is False and snap.indexed_at.tzinfo is not None
    assert answer.confidence == CONFIDENCE == "name_match"
    payload = answer.as_dict()
    assert set(payload["snapshot"]) == {"repo", "commit", "indexed_at", "stale"}
    assert payload["confidence"] == "name_match"


def test_non_python_files_get_a_file_and_import_graph(provider: CodeGraphProvider) -> None:
    provider.refresh()
    con = sqlite3.connect(provider.db_path())
    try:
        assert con.execute("SELECT lang FROM files WHERE path = 'web/page.js'").fetchone() == ("javascript",)
        assert con.execute("SELECT count(*) FROM symbols WHERE file LIKE 'web/%'").fetchone() == (0,)
    finally:
        con.close()
    assert rows(provider.neighbors("web/lib.js"), "direction", "id") == [("in", "web/page.js")]


# ------------------------------------------------------------------ refresh rules
def test_incremental_refresh_touches_only_changed_files(provider: CodeGraphProvider, repo: Path) -> None:
    first = provider.refresh()
    assert len(first.parsed) == 7 and first.unchanged == 0
    assert provider.refresh().parsed == ()
    (repo / "pkg" / "util.py").write_text("def helper(x):\n    return x + 2\n", encoding="utf-8")
    (repo / "pkg" / "extra.py").write_text("from pkg.util import helper\n", encoding="utf-8")
    (repo / "web" / "lib.js").unlink()
    report = provider.refresh()
    assert report.parsed == ("pkg/extra.py", "pkg/util.py")
    assert report.removed == ("web/lib.js",)
    assert report.unchanged == 5
    assert provider.refresh().parsed == ()


def test_stale_after_edit_and_after_new_commit(provider: CodeGraphProvider, repo: Path) -> None:
    assert provider.usages("helper").snapshot.stale is False
    (repo / "pkg" / "util.py").write_text("def helper(x):\n    return x * 3\n", encoding="utf-8")
    assert provider.usages("helper").snapshot.stale is True  # working tree differs
    assert provider.status().status is CapabilityStatus.DEGRADED
    provider.refresh()
    assert provider.usages("helper").snapshot.stale is False
    new_head = commit_all(repo, "second")  # same content, new commit
    stale = provider.usages("helper").snapshot
    assert stale.stale is True and stale.commit != new_head
    report = provider.refresh()
    assert report.parsed == () and report.commit == new_head
    fresh = provider.usages("helper").snapshot
    assert fresh.stale is False and fresh.commit == new_head


def test_new_untracked_file_is_indexed_and_ignored_one_is_not(provider: CodeGraphProvider, repo: Path) -> None:
    (repo / ".gitignore").write_text("skipped.py\n", encoding="utf-8")
    (repo / "skipped.py").write_text("def hidden(): pass\n", encoding="utf-8")
    (repo / "fresh.py").write_text("def brand_new(): pass\n", encoding="utf-8")
    provider.refresh()
    assert rows(provider.symbol("brand_new"), "path") == [("fresh.py",)]
    assert provider.symbol("hidden").items == ()


def test_syntax_error_file_is_skipped_with_a_diagnostic(provider: CodeGraphProvider, repo: Path) -> None:
    provider.refresh()
    (repo / "broken.py").write_text("def ok():\n    pass\ndef broken(:\n", encoding="utf-8")
    report = provider.refresh()
    assert report.parsed == ("broken.py",)
    assert len(report.diagnostics) == 1 and report.diagnostics[0].startswith("broken.py: syntax_error line 3")
    answer = provider.symbol("ok")
    assert answer.items == () and answer.diagnostics == report.diagnostics
    assert rows(provider.usages("helper"), "line") == [(1,), (6,)]  # the rest of the graph is intact
    asset = provider.read(repo_id(repo))
    assert "broken.py: syntax_error" in asset.body
    assert provider.refresh().parsed == ()  # an unchanged broken file is not re-parsed


def test_rebuild_from_scratch_equals_incremental(provider: CodeGraphProvider, repo: Path) -> None:
    (repo / "pkg" / "extra.py").write_text("from pkg import util\n\n\ndef again():\n    return util.helper(1)\n",
                                           encoding="utf-8")
    (repo / "pkg" / "core.py").write_text(
        "from pkg.util import helper\nfrom pkg.extra import again\n\n\nclass Engine:\n"
        "    def run(self, x):\n        return helper(x) + again()\n\n\ndef start(x):\n    return Engine().run(x)\n",
        encoding="utf-8")
    (repo / "pkg" / "models.py").unlink()
    (repo / "app.py").write_text("from pkg.core import start\n\nstart(1)\n", encoding="utf-8")
    (repo / "broken.py").write_text("x = (\n", encoding="utf-8")
    provider.refresh()
    incremental = dump(provider)
    assert provider.rebuild() == 1
    assert dump(provider) == incremental
    assert rows(provider.neighbors("pkg/extra.py"), "direction", "id")[0] == ("in", "pkg/core.py")


def test_unreadable_database_is_dropped_and_rebuilt(provider: CodeGraphProvider) -> None:
    provider.refresh()
    provider.db_path().write_bytes(b"not a database at all" * 20)
    assert rows(provider.usages("helper"), "line") == [(1,), (6,)]


# ------------------------------------------------------------------------- caps
def test_impact_depth_and_size_caps(provider: CodeGraphProvider) -> None:
    depth = provider.impact("helper", max_depth=2)
    assert [i["id"] for i in depth.items] == ["pkg/core.py::Engine.run", "pkg/core.py::start"]
    assert depth.truncated == ("depth",)
    size = provider.impact("helper", max_nodes=3)
    assert len(size.items) == 3 and size.truncated == ("size",)
    exact = provider.impact("helper", max_nodes=4)
    assert len(exact.items) == 4 and exact.truncated == ()
    exact_depth = provider.impact("helper", max_depth=4)
    assert exact_depth.truncated == ()


def test_result_limit_and_argument_ranges(provider: CodeGraphProvider) -> None:
    cut = provider.usages("Engine", limit=2)
    assert len(cut.items) == 2 and cut.truncated == ("limit",)
    for bad in (0, 501):
        with pytest.raises(ValueError):
            provider.usages("Engine", limit=bad)
    with pytest.raises(ValueError):
        provider.impact("helper", max_depth=0)
    with pytest.raises(ValueError):
        provider.impact("helper", max_nodes=2_001)
    with pytest.raises(ValueError):
        provider.path("a", "b", max_depth=21)


# -------------------------------------------------------------- provider contract
def test_knowledge_asset_provider_contract(provider: CodeGraphProvider, repo: Path, tmp_path: Path) -> None:
    assert isinstance(provider, KnowledgeAssetProvider) and provider.kind is AssetKind.CODEGRAPH
    asset_id = repo_id(repo)
    provider.refresh()
    (listed,) = provider.list()
    assert listed.asset_id == asset_id and listed.body == "" and listed.scope is AssetScope.PROJECT
    assert listed.confidence == "name_match" and listed.stale is False
    assert listed.source.version_or_commit == git(repo, "rev-parse", "HEAD")
    assert provider.list(AssetScope.PRIVATE) == ()
    read = provider.read(asset_id)
    assert "confidence: name_match" in read.body and "pkg/core.py (3)" in read.body
    with pytest.raises(MemoryStoreError) as caught:
        provider.read("missing-00000000")
    assert caught.value.code is MemoryErrorCode.NOT_FOUND
    hits = provider.search("engine", 5)
    assert [h.snippet for h in hits][0] == "class Engine at pkg/core.py:4"
    assert hits[0].score == 1.0 and hits[0].asset.body == ""
    assert provider.search("", 5) == () and provider.search("engine", 5, AssetScope.SHARED) == ()
    assert provider.status().is_ok
    assert provider.rebuild() == 1


def test_list_and_status_do_not_index(tmp_path: Path, repo: Path) -> None:
    cold = CodeGraphProvider(tmp_path / "cold", [repo])
    (asset,) = cold.list()
    assert asset.stale is True and asset.summary == "not indexed yet"
    assert cold.status().status is CapabilityStatus.DEGRADED
    assert cold.search("helper", 3) == ()


def test_status_without_repo_or_git(tmp_path: Path) -> None:
    assert CodeGraphProvider(tmp_path / "g").status().status is CapabilityStatus.DISABLED
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.py").write_text("x = 1\n", encoding="utf-8")
    bare = CodeGraphProvider(tmp_path / "g", [plain])
    assert bare.status().status is CapabilityStatus.UNAVAILABLE
    assert bare.list() == ()
    with pytest.raises(MemoryStoreError) as caught:
        bare.symbol("x")
    assert caught.value.code is MemoryErrorCode.UNAVAILABLE


def test_repo_selection(tmp_path: Path, repo: Path) -> None:
    other = tmp_path / "work" / "other"
    shutil.copytree(FIXTURE, other)
    git(other, "init", "-q")
    commit_all(other)
    both = CodeGraphProvider(tmp_path / "g", [repo, other])
    with pytest.raises(ValueError):
        both.symbol("helper")
    assert both.symbol("helper", repo_id(other)).snapshot.repo == str(other.resolve())
    assert both.symbol("helper", other).items == both.symbol("helper", repo).items
    with pytest.raises(MemoryStoreError):
        both.symbol("helper", tmp_path / "nowhere")
    assert both.rebuild() == 2


# ------------------------------------------------------------------- performance
def test_index_this_repository_records_timing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Records indexing time on the real repository. No time gate: it only has to finish."""

    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    own = CodeGraphProvider(tmp_path / "own", [REPO_ROOT])
    start = time.perf_counter()
    cold = own.refresh()
    cold_s = time.perf_counter() - start
    start = time.perf_counter()
    warm = own.refresh()
    warm_s = time.perf_counter() - start
    with capsys.disabled():
        print(f"\ncodegraph timing: cold {cold_s:.2f}s ({len(cold.parsed)} files parsed), "
              f"warm {warm_s:.2f}s ({warm.unchanged} unchanged)")
    assert cold.parsed and warm.parsed == ()
    assert own.symbol("CodeGraphProvider").items
