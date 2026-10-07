"""Wiki knowledge assets: import, update, delete, rebuild, stale, allowlist, scope (Slice 07).

Temporary roots only. Link escapes use a real symlink and a real Windows junction.
Contract: `docs/knowledge-assets.md`.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

import pytest

from jarvis.adapters.knowledge_wiki import DEFAULT_ALLOWED_ROOT, WikiProvider
from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.knowledge import AssetKind, AssetScope
from jarvis.domain.memory import CapabilityStatus, MemoryErrorCode, MemoryStoreError
from jarvis.ports.knowledge import KnowledgeAssetProvider

PROJECT, PRIVATE = AssetScope.PROJECT, AssetScope.PRIVATE


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "deploy.md").write_text("# Deploy guide\n\nRun the pipeline with the zebra flag.\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "api.md").write_text("# API\n\nEndpoints use the quokka token.\n", encoding="utf-8")
    return root


@pytest.fixture
def wiki(tmp_path: Path, docs: Path) -> WikiProvider:
    return WikiProvider(tmp_path / "knowledge" / "wiki", allowed_roots=[docs])


def junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        pytest.skip("NTFS junctions exist only on Windows; the symlink test covers POSIX")
    import _winapi

    try:
        _winapi.CreateJunction(str(target), str(link))
    except OSError as exc:
        pytest.skip(f"junction creation refused by the host: {exc}")


def test_provider_satisfies_the_port_and_defaults_to_repo_docs(tmp_path: Path):
    provider = WikiProvider(tmp_path / "w")
    assert isinstance(provider, KnowledgeAssetProvider)
    assert provider.kind is AssetKind.WIKI
    assert provider.allowed_roots == (DEFAULT_ALLOWED_ROOT.resolve(),)
    assert provider.status().is_ok


def test_import_carries_source_version_and_provenance(wiki: WikiProvider, docs: Path):
    asset = wiki.import_file(docs / "deploy.md")
    assert asset.title == "Deploy guide"
    assert asset.version == "1" and not asset.stale
    assert asset.source.uri == (docs / "deploy.md").resolve().as_uri()
    assert asset.source.path == "deploy.md"
    assert asset.source.version_or_commit.startswith("sha256:")
    assert asset.source.fetched_at.tzinfo is not None
    assert "zebra" in asset.body
    assert wiki.read(asset.asset_id) == asset
    [listed] = wiki.list()
    assert listed.body == "" and listed.source == asset.source and listed.version == "1"
    [hit] = wiki.search("zebra", 5)
    assert hit.asset.source == asset.source and hit.asset.body == "" and "zebra" in hit.snippet


def test_update_bumps_version_only_when_content_changes(tmp_path: Path, docs: Path):
    ticks = iter(datetime(2026, 1, d, tzinfo=timezone.utc) for d in range(1, 30))
    wiki = WikiProvider(tmp_path / "w", allowed_roots=[docs], clock=lambda: next(ticks))
    first = wiki.import_file(docs / "deploy.md")
    same = wiki.import_file(docs / "deploy.md")
    assert same.version == "1" and same.source.fetched_at == first.source.fetched_at
    (docs / "deploy.md").write_text("# Deploy guide\n\nNow with the walrus flag.\n", encoding="utf-8")
    assert wiki.read(first.asset_id).stale
    updated = wiki.refresh(first.asset_id)
    assert updated.asset_id == first.asset_id and updated.version == "2" and not updated.stale
    assert updated.source.version_or_commit != first.source.version_or_commit
    assert updated.source.fetched_at > first.source.fetched_at
    assert wiki.search("zebra", 5) == []
    assert [h.asset.asset_id for h in wiki.search("walrus", 5)] == [first.asset_id]
    assert len(wiki.list()) == 1


def test_delete_then_rebuild_keeps_it_gone(wiki: WikiProvider, docs: Path):
    keep = wiki.import_file(docs / "sub" / "api.md")
    gone = wiki.import_file(docs / "deploy.md")
    wiki.delete(gone.asset_id)
    assert [a.asset_id for a in wiki.list()] == [keep.asset_id]
    assert wiki.search("zebra", 5) == []
    assert wiki.rebuild() == 1
    assert wiki.search("zebra", 5) == []
    with pytest.raises(MemoryStoreError) as err:
        wiki.read(gone.asset_id)
    assert err.value.code is MemoryErrorCode.NOT_FOUND
    with pytest.raises(MemoryStoreError):
        wiki.delete(gone.asset_id)


def test_index_deleted_loses_nothing(tmp_path: Path, docs: Path):
    root = tmp_path / "w"
    wiki = WikiProvider(root, allowed_roots=[docs])
    report = wiki.import_tree(docs)
    assert len(report.imported) == 2 and report.skipped == ()
    before = wiki.list()
    index = root / "index"
    assert index.is_dir()
    for leftover in index.iterdir():
        leftover.unlink()
    # a fresh provider on the same root: the pages are the truth, the index comes back
    again = WikiProvider(root, allowed_roots=[docs])
    assert again.list() == before
    assert [h.asset.title for h in again.search("quokka", 5)] == ["API"]
    assert again.rebuild() == 2
    assert again.read(before[0].asset_id).body


def test_corrupt_index_is_recreated(tmp_path: Path, docs: Path):
    root = tmp_path / "w"
    wiki = WikiProvider(root, allowed_roots=[docs])
    wiki.import_file(docs / "deploy.md")
    (root / "index" / "wiki-index.sqlite3").write_bytes(b"not a database" * 100)
    assert len(wiki.search("zebra", 5)) == 1
    assert wiki.status().is_ok


def test_stale_by_hash_not_by_touch_and_when_source_vanishes(wiki: WikiProvider, docs: Path):
    page = wiki.import_file(docs / "deploy.md")
    st = (docs / "deploy.md").stat()
    os.utime(docs / "deploy.md", ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert not wiki.read(page.asset_id).stale
    (docs / "deploy.md").write_text("# Deploy guide\n\nchanged\n", encoding="utf-8")
    assert wiki.read(page.asset_id).stale
    assert wiki.list()[0].stale and wiki.search("zebra", 5)[0].asset.stale
    (docs / "deploy.md").unlink()
    assert wiki.read(page.asset_id).stale
    assert "zebra" in wiki.read(page.asset_id).body  # the copy survives the source


def test_stale_when_the_allowlist_no_longer_covers_the_source(tmp_path: Path, docs: Path):
    root = tmp_path / "w"
    page = WikiProvider(root, allowed_roots=[docs]).import_file(docs / "deploy.md")
    narrowed = WikiProvider(root, allowed_roots=[tmp_path / "elsewhere"])
    assert narrowed.read(page.asset_id).stale
    with pytest.raises(MemorySecurityError):
        narrowed.refresh(page.asset_id)


def test_traversal_and_outside_paths_are_refused(wiki: WikiProvider, docs: Path, tmp_path: Path):
    outside = tmp_path / "secret.md"
    outside.write_text("# Secret\n\nhunter2\n", encoding="utf-8")
    for bad in (outside, docs / ".." / "secret.md", str(docs) + "/sub/../../secret.md", "..", "\x00"):
        with pytest.raises(MemorySecurityError):
            wiki.import_file(bad)
    with pytest.raises(MemorySecurityError):
        wiki.import_tree(tmp_path)
    assert wiki.list() == () and wiki.search("hunter2", 5) == []


def test_sibling_prefix_directory_is_not_inside_the_allowlist(wiki: WikiProvider, docs: Path):
    sibling = docs.parent / "docs-evil"
    sibling.mkdir()
    (sibling / "x.md").write_text("# X\n\nbody\n", encoding="utf-8")
    with pytest.raises(MemorySecurityError):
        wiki.import_file(sibling / "x.md")


def test_symlink_and_junction_are_never_followed(wiki: WikiProvider, docs: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.md").write_text("# Leak\n\nexfiltrated\n", encoding="utf-8")
    file_link = docs / "link.md"
    try:
        file_link.symlink_to(outside / "leak.md")
        dir_link = docs / "dirlink"
        dir_link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(MemorySecurityError):
        wiki.import_file(file_link)
    with pytest.raises(MemorySecurityError):
        wiki.import_file(dir_link / "leak.md")
    report = wiki.import_tree(docs)
    assert sorted(a.title for a in report.imported) == ["API", "Deploy guide"]
    assert wiki.search("exfiltrated", 5) == []


def test_junction_is_never_followed(wiki: WikiProvider, docs: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.md").write_text("# Leak\n\nexfiltrated\n", encoding="utf-8")
    junction(docs / "jun", outside)
    with pytest.raises(MemorySecurityError):
        wiki.import_file(docs / "jun" / "leak.md")
    assert sorted(a.title for a in wiki.import_tree(docs).imported) == ["API", "Deploy guide"]
    assert wiki.search("exfiltrated", 5) == []


def test_source_that_turns_into_a_link_later_reads_as_stale(wiki: WikiProvider, docs: Path, tmp_path: Path):
    page = wiki.import_file(docs / "sub" / "api.md")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "api.md").write_text("# API\n\nEndpoints use the quokka token.\n", encoding="utf-8")
    (docs / "sub" / "api.md").unlink()
    (docs / "sub").rename(docs / "sub-old")
    junction(docs / "sub", outside)
    assert wiki.read(page.asset_id).stale  # same bytes, but no longer reachable without a link


def test_non_markdown_oversized_and_binary_sources_are_refused(wiki: WikiProvider, docs: Path):
    (docs / "notes.txt").write_text("# t\n", encoding="utf-8")
    (docs / "bin.md").write_bytes(b"\xff\xfe\x00bad")
    (docs / "big.md").write_text("x" * 70_000, encoding="utf-8")
    for name in ("notes.txt", "bin.md", "big.md"):
        with pytest.raises(ValueError):
            wiki.import_file(docs / name)
    report = wiki.import_tree(docs)
    assert sorted(Path(p).name for p, _ in report.skipped) == ["big.md", "bin.md"]
    assert len(report.imported) == 2


def test_scope_isolation_private_page_is_invisible_to_project(wiki: WikiProvider, docs: Path):
    private = wiki.import_file(docs / "deploy.md", PRIVATE)
    project = wiki.import_file(docs / "sub" / "api.md", PROJECT)
    assert [a.asset_id for a in wiki.list(PROJECT)] == [project.asset_id]
    assert [a.asset_id for a in wiki.list(PRIVATE)] == [private.asset_id]
    assert wiki.search("zebra", 5, PROJECT) == []
    assert [h.asset.asset_id for h in wiki.search("zebra", 5, PRIVATE)] == [private.asset_id]
    assert wiki.search("zebra quokka", 5, AssetScope.SHARED) == []
    assert len(wiki.search("zebra quokka", 5)) == 2
    with pytest.raises(MemoryStoreError) as err:
        wiki.read(private.asset_id, scope=PROJECT)
    assert err.value.code is MemoryErrorCode.SCOPE_DENIED
    assert wiki.read(private.asset_id, scope=PRIVATE).body


def test_scope_change_on_reimport_moves_the_page_in_the_index(wiki: WikiProvider, docs: Path):
    page = wiki.import_file(docs / "deploy.md", PRIVATE)
    wiki.import_file(docs / "deploy.md", PROJECT)
    assert wiki.search("zebra", 5, PRIVATE) == []
    assert [h.asset.asset_id for h in wiki.search("zebra", 5, PROJECT)] == [page.asset_id]
    assert wiki.read(page.asset_id).version == "1"


def test_index_scope_is_not_trusted_over_the_page(tmp_path: Path, docs: Path):
    root = tmp_path / "w"
    wiki = WikiProvider(root, allowed_roots=[docs])
    page = wiki.import_file(docs / "deploy.md", PRIVATE)
    import sqlite3

    with sqlite3.connect(root / "index" / "wiki-index.sqlite3") as conn:  # tampered derived file
        conn.execute("UPDATE wiki_fts SET scope = 'project'")
    assert wiki.search("zebra", 5, PROJECT) == []
    assert page.scope is PRIVATE


def test_url_is_recorded_never_fetched(wiki: WikiProvider, monkeypatch: pytest.MonkeyPatch):
    import socket

    def boom(*_a, **_k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    page = wiki.import_text("https://example.test/wiki/page", "Remote page", "Body about the narwhal.\n")
    assert page.source.uri == "https://example.test/wiki/page" and page.source.path is None
    assert page.source.version_or_commit.startswith("sha256:") and page.version == "1" and not page.stale
    assert [h.asset.asset_id for h in wiki.search("narwhal", 5)] == [page.asset_id]
    with pytest.raises(ValueError):
        wiki.refresh(page.asset_id)
    for bad in ("file:///etc/passwd", "ftp://x/y", "https://", "notaurl"):
        with pytest.raises(ValueError):
            wiki.import_text(bad, "t", "b")


def test_unknown_and_malformed_ids_are_not_found(wiki: WikiProvider):
    for bad in ("nope", "../x", "a/b", "", "x" * 300):
        with pytest.raises(MemoryStoreError) as err:
            wiki.read(bad)
        assert err.value.code is MemoryErrorCode.NOT_FOUND


def test_search_edge_cases_and_hostile_queries(wiki: WikiProvider, docs: Path):
    wiki.import_tree(docs)
    assert wiki.search("", 5) == [] and wiki.search("!!! ---", 5) == []
    assert wiki.search('zebra" OR "x', 5)  # quotes are stripped, no FTS syntax error
    assert len(wiki.search("zebra quokka", 1)) == 1


def test_status_degraded_on_corrupt_page(tmp_path: Path, docs: Path):
    root = tmp_path / "w"
    wiki = WikiProvider(root, allowed_roots=[docs])
    wiki.import_file(docs / "deploy.md")
    (root / "pages" / "page-broken.json").write_text("{nope", encoding="utf-8")
    state = wiki.status()
    assert state.status is CapabilityStatus.DEGRADED and state.reason_code == "wiki_corrupt_pages"
    assert len(wiki.list()) == 1


def test_data_root_holds_no_state_outside_the_wiki_root(tmp_path: Path, docs: Path):
    root = tmp_path / "knowledge" / "wiki"
    WikiProvider(root, allowed_roots=[docs]).import_tree(docs)
    assert {p.relative_to(tmp_path).parts[0] for p in tmp_path.rglob("*") if "knowledge" in p.parts} == {"knowledge"}
    assert not list(docs.rglob("*.sqlite3")) and not list(docs.rglob("*.json"))


# ------------------------------------------------------------------ rework


def test_link_detection_survives_python_without_isjunction(
    wiki: WikiProvider, docs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """`os.path.isjunction` is 3.12+; the project supports 3.11. The reparse-point fallback must catch a real junction."""

    from jarvis.adapters import knowledge_wiki

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.md").write_text("# Leak\n\nexfiltrated\n", encoding="utf-8")
    junction(docs / "jun", outside)
    monkeypatch.delattr(os.path, "isjunction", raising=False)
    assert not hasattr(os.path, "isjunction")
    assert knowledge_wiki._is_link(docs / "jun")
    assert not knowledge_wiki._is_link(docs / "sub") and not knowledge_wiki._is_link(docs / "missing")
    with pytest.raises(MemorySecurityError):
        wiki.import_file(docs / "jun" / "leak.md")
    report = wiki.import_tree(docs)
    assert sorted(a.title for a in report.imported) == ["API", "Deploy guide"]
    [page] = wiki.search("zebra", 5)
    assert not wiki.read(page.asset.asset_id).stale and len(wiki.list()) == 2
    assert wiki.search("exfiltrated", 5) == []


def test_failed_atomic_replace_keeps_old_page_and_leaves_no_temp(
    wiki: WikiProvider, docs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    page = wiki.import_file(docs / "deploy.md")
    (docs / "deploy.md").write_text("# Deploy guide\n\nreplaced by the walrus\n", encoding="utf-8")

    def refuse(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(MemoryStoreError) as err:
        wiki.refresh(page.asset_id)
    assert err.value.code is MemoryErrorCode.UNAVAILABLE
    monkeypatch.undo()
    assert not list((tmp_path / "knowledge" / "wiki" / "pages").glob(".wiki-*.tmp"))
    kept = wiki.read(page.asset_id)
    assert kept.version == "1" and "zebra" in kept.body
    assert wiki.search("walrus", 5) == [] and len(wiki.search("zebra", 5)) == 1


def test_rebuild_purges_orphan_index_rows(tmp_path: Path, docs: Path):
    import sqlite3

    root = tmp_path / "w"
    wiki = WikiProvider(root, allowed_roots=[docs])
    wiki.import_file(docs / "deploy.md")
    with sqlite3.connect(root / "index" / "wiki-index.sqlite3") as conn:
        conn.execute("INSERT INTO wiki_fts(asset_id, scope, title, body) VALUES('ghost','project','Ghost','zebra ghost')")
    assert wiki.rebuild() == 1
    with sqlite3.connect(root / "index" / "wiki-index.sqlite3") as conn:
        assert conn.execute("SELECT asset_id FROM wiki_fts").fetchall() == [(wiki.list()[0].asset_id,)]


def test_orphan_and_tampered_rows_do_not_crowd_out_real_hits(tmp_path: Path, docs: Path):
    import sqlite3

    root = tmp_path / "w"
    wiki = WikiProvider(root, allowed_roots=[docs])
    page = wiki.import_file(docs / "deploy.md", PROJECT)
    with sqlite3.connect(root / "index" / "wiki-index.sqlite3") as conn:
        conn.executemany(
            "INSERT INTO wiki_fts(asset_id, scope, title, body) VALUES(?,?,?,?)",
            [(f"ghost{i}", "project", "zebra zebra", "zebra " * 50) for i in range(100)],
        )
    assert [h.asset.asset_id for h in wiki.search("zebra", 1)] == [page.asset_id]


def test_same_file_with_different_case_is_one_page(wiki: WikiProvider, docs: Path):
    if os.name != "nt":
        pytest.skip("case-insensitive path spelling is a Windows concern")
    first = wiki.import_file(docs / "deploy.md")
    second = wiki.import_file(Path(str(docs / "deploy.md").swapcase()))
    assert second.asset_id == first.asset_id and second.source.uri == first.source.uri
    assert len(wiki.list()) == 1


def test_case_colliding_asset_id_is_refused(wiki: WikiProvider, docs: Path):
    wiki.import_file(docs / "deploy.md", asset_id="Guide")
    with pytest.raises(ValueError, match="collides"):
        wiki.import_file(docs / "sub" / "api.md", asset_id="guide")
    wiki.import_file(docs / "deploy.md", asset_id="Guide")  # the same id still updates
    assert [a.asset_id for a in wiki.list()] == ["Guide"]


def test_missing_directory_and_device_names_raise_value_error(wiki: WikiProvider, docs: Path):
    (docs / "adir.md").mkdir()
    for name in ("absent.md", "adir.md", "nul.md", "con.md"):
        with pytest.raises(ValueError):
            wiki.import_file(docs / name)
    assert wiki.list() == ()
