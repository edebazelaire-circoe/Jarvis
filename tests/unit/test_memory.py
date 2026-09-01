from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
from jarvis.domain.errors import MemorySecurityError


@pytest.mark.asyncio
async def test_append_is_markdown_canonical_and_survives_restart(tmp_path: Path):
    memory = MarkdownMemoryBackend(tmp_path)
    record = await memory.append_note("Projet Atlas", "Le budget est 42.")
    source = tmp_path / record.memory_id
    assert source.is_file()
    assert source.read_text(encoding="utf-8") == "# Projet Atlas\n\nLe budget est 42.\n"

    restarted = MarkdownMemoryBackend(tmp_path)
    hits = await restarted.search("budget Atlas")
    assert any(h.memory_id == record.memory_id for h in hits)
    read = await restarted.read(record.memory_id)
    assert read.body == source.read_text(encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "memory_id",
    [
        "../secret.md",
        "%2e%2e/secret.md",
        "%252e%252e/secret.md",
        "/etc/passwd",
    ],
)
async def test_memory_read_blocks_traversal_and_encoded_traversal(tmp_path: Path, memory_id: str):
    memory = MarkdownMemoryBackend(tmp_path)
    with pytest.raises(MemorySecurityError):
        await memory.read(memory_id)


@pytest.mark.asyncio
async def test_symlink_escape_is_not_indexed_or_readable(tmp_path: Path):
    outside = tmp_path.parent / "jarvis-outside.md"
    outside.write_text("# Outside\n\nsecret sentinel", encoding="utf-8")
    link = tmp_path / "escape.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    memory = MarkdownMemoryBackend(tmp_path)
    await memory.rebuild_index()
    assert await memory.search("sentinel") == []
    with pytest.raises(MemorySecurityError):
        await memory.read("escape.md")


@pytest.mark.asyncio
async def test_empty_or_punctuation_query_returns_empty(tmp_path: Path):
    memory = MarkdownMemoryBackend(tmp_path)
    assert await memory.search("... ---") == []

@pytest.mark.asyncio
async def test_deleting_derived_index_and_rebuilding_restores_search(tmp_path: Path):
    memory = MarkdownMemoryBackend(tmp_path)
    record = await memory.append_note("Persistance", "sentinelle rebâtissable")
    # All connections are short-lived; the derived SQLite file can be deleted safely.
    memory.db_path.unlink()
    rebuilt = MarkdownMemoryBackend(tmp_path)
    hits = await rebuilt.search("sentinelle")
    assert any(hit.memory_id == record.memory_id for hit in hits)


@pytest.mark.asyncio
async def test_restart_resyncs_external_markdown_edits(tmp_path: Path):
    source = tmp_path / "external.md"
    source.write_text("# External\n\nancienne valeur", encoding="utf-8")
    first = MarkdownMemoryBackend(tmp_path)
    assert await first.search("ancienne")

    source.write_text("# External\n\nnouvelle sentinelle", encoding="utf-8")
    restarted = MarkdownMemoryBackend(tmp_path)
    assert await restarted.search("nouvelle sentinelle")
    assert await restarted.search("ancienne") == []


@pytest.mark.asyncio
async def test_corrupt_derived_index_is_rebuilt_from_markdown(tmp_path: Path):
    source = tmp_path / "canonical.md"
    source.write_text("# Canonical\n\nfait recuperable", encoding="utf-8")
    memory = MarkdownMemoryBackend(tmp_path)
    assert await memory.search("recuperable")
    memory.db_path.write_bytes(b"not a sqlite database")

    recovered = MarkdownMemoryBackend(tmp_path)
    hits = await recovered.search("recuperable")
    assert hits and hits[0].title == "Canonical"


@pytest.mark.asyncio
async def test_index_failure_after_atomic_write_repairs_from_markdown(tmp_path: Path, monkeypatch):
    import sqlite3

    memory = MarkdownMemoryBackend(tmp_path)

    def fail_once(doc):
        monkeypatch.setattr(memory, "_upsert_doc", original)
        raise sqlite3.OperationalError("simulated index failure")

    original = memory._upsert_doc
    monkeypatch.setattr(memory, "_upsert_doc", fail_once)
    record = await memory.append_note("Réparation", "la source Markdown gagne toujours")
    assert (tmp_path / record.memory_id).is_file()
    hits = await memory.search("Markdown gagne")
    assert any(hit.memory_id == record.memory_id for hit in hits)


@pytest.mark.asyncio
async def test_persistent_write_reports_success_even_if_derived_index_repair_also_fails(tmp_path: Path, monkeypatch):
    import sqlite3

    memory = MarkdownMemoryBackend(tmp_path)

    def broken_upsert(doc):
        raise sqlite3.OperationalError("index unavailable")

    def broken_rebuild():
        raise sqlite3.OperationalError("index rebuild unavailable")

    monkeypatch.setattr(memory, "_upsert_doc", broken_upsert)
    monkeypatch.setattr(memory, "_rebuild_index_sync", broken_rebuild)

    record = await memory.append_note("Durable", "ce contenu est canonique")
    source = tmp_path / record.memory_id
    assert source.is_file()
    assert "ce contenu est canonique" in source.read_text(encoding="utf-8")
