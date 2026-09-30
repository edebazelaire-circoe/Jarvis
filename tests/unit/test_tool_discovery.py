"""Réponse bornée de `list_tools` (plugins MCP, Slice 04 ; `docs/mcp/plugins.md` §6.3, ARCH §7.2, E3, E6).

Ce qui doit tenir : ≤ 5 recommandés complets (score > 0, ≥ 0,35 × meilleur,
partie ≤ 16 Kio), une entrée seule > 16 Kio jamais recommandée mais listée
`too_large`, `others` compacts (résumé ≤ 120), réponse entière ≤ 24 576 octets
sur un catalogue synthétique de 500 outils, pagination par curseur (révision
changée ⇒ reprise `catalog_changed`, autre intention ⇒ `mcp_cursor_invalid`),
intention vide ⇒ aucun recommandé et ordre alphabétique, déterminisme.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.mcp_plugins import McpErrorCode, McpPluginError
from jarvis.domain.tool_discovery import (
    MAX_RECOMMENDED,
    MAX_RECOMMENDED_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_SUMMARY_CHARS,
    ToolEntry,
    build_list_response,
    decode_cursor,
    encode_cursor,
    size_of,
    summary_of,
)
from jarvis.domain.tool_relevance import ToolDoc, rank

REV = "nabcdef12.e7"


def _entry(i: int, *, description: str | None = None, schema: dict | None = None, native: bool = False) -> ToolEntry:
    name = f"tool_{i:03d}"
    tool_id = f"mcp__jarvis-display__{name}" if native else f"plug-{i % 7}.{name}"
    return ToolEntry(
        id=tool_id, name=name, invocation="direct_native" if native else "managed_external",
        source="jarvis-display" if native else f"Plugin {i % 7}",
        description=description if description is not None else (
            f"Outil {i} pour le mail et l'agenda.\nDétail : " + "x" * 300),
        input_schema=schema or {"type": "object", "properties": {"q": {"type": "string", "description": "texte"}},
                                "required": ["q"]},
        side_effect=("read", "write", "destructive")[i % 3], call_as=tool_id if native else None)


def _catalog(n: int = 500) -> list[ToolEntry]:
    return [_entry(i, native=i < 40) for i in range(n)]


def _ranked(intent: str, entries: list[ToolEntry]) -> list[tuple[ToolEntry, float]]:
    by_id = {entry.id: entry for entry in entries}
    docs = [ToolDoc(entry.id, entry.name, entry.name, entry.description, tuple(entry.input_schema.get("properties", {})),
                    (), entry.source) for entry in entries]
    return [(by_id[doc.id], score) for doc, score in rank(intent, docs)]


def _scored(entries: list[ToolEntry], scores: list[float]) -> list[tuple[ToolEntry, float]]:
    return list(zip(entries, scores))


# ------------------------------------------------------------------ budget

def test_five_hundred_tools_fit_the_whole_response_budget():
    entries = _catalog()
    response = build_list_response("chercher un outil 042 pour le mail", _ranked("outil 042 mail", entries),
                                   catalog_revision=REV, limit=60)
    assert size_of(response) <= MAX_RESPONSE_BYTES
    assert 1 <= len(response["recommended"]) <= MAX_RECOMMENDED
    assert size_of(response["recommended"]) <= MAX_RECOMMENDED_BYTES
    assert response["total"] == 500 and response["next_cursor"] is not None
    assert list(response) == ["intent", "catalog_revision", "recommended", "others", "next_cursor", "total", "notes"]
    for full in response["recommended"]:
        assert set(full) >= {"id", "name", "invocation", "source", "description", "input_schema", "side_effect"}
    for other in response["others"]:
        assert set(other) == {"id", "summary", "source", "side_effect", "invocation"}
        assert len(other["summary"]) <= MAX_SUMMARY_CHARS and "\n" not in other["summary"]


def test_the_others_are_filled_until_the_byte_budget_not_beyond():
    # Résumés longs : le budget, pas `limit`, arrête le remplissage.
    entries = [_entry(i, description="é" * 400) for i in range(200)]
    ranked = _scored(entries, [0.0] * 200)
    response = build_list_response("x", ranked, catalog_revision=REV, limit=60)
    assert size_of(response) <= MAX_RESPONSE_BYTES
    assert response["recommended"] == []
    one_more = response["others"] + [entries[len(response["others"])].compact()]
    assert size_of({**response, "others": one_more}) > MAX_RESPONSE_BYTES or len(response["others"]) == 60


def test_natives_carry_call_as_and_externals_do_not():
    entries = [_entry(1, native=True), _entry(2)]
    response = build_list_response("outil mail", _scored(entries, [5.0, 4.0]), catalog_revision=REV)
    native, external = response["recommended"]
    assert native["invocation"] == "direct_native" and native["call_as"] == native["id"]
    assert external["invocation"] == "managed_external" and "call_as" not in external
    assert list(native) == ["id", "name", "invocation", "call_as", "source", "description", "input_schema",
                            "side_effect"]


def test_at_most_five_recommended_and_only_above_the_relative_threshold():
    entries = [_entry(i) for i in range(10)]
    response = build_list_response("x", _scored(entries, [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]), catalog_revision=REV)
    assert [entry["id"] for entry in response["recommended"]] == [entry.id for entry in entries[:5]]
    low = build_list_response("x", _scored(entries[:3], [10, 3.4, 3.6]), catalog_revision=REV)
    assert [entry["id"] for entry in low["recommended"]] == [entries[0].id]  # 3.4 et 3.6 < 0.35 × 10 ; ordre = rang
    zero = build_list_response("x", _scored(entries[:2], [0.0, 0.0]), catalog_revision=REV)
    assert zero["recommended"] == [] and len(zero["others"]) == 2


def test_an_entry_over_sixteen_kib_is_never_recommended_but_listed_too_large():
    huge = _entry(0, description="d" * 4000, schema={"type": "object", "properties": {
        f"p{i}": {"type": "string", "description": "y" * 120} for i in range(110)}})
    assert size_of(huge.full()) > MAX_RECOMMENDED_BYTES
    normal = _entry(1)
    response = build_list_response("x", _scored([huge, normal], [9.0, 8.0]), catalog_revision=REV)
    assert [entry["id"] for entry in response["recommended"]] == [normal.id]
    assert response["others"] == [{**huge.compact(), "detail": "too_large"}]
    assert size_of(response) <= MAX_RESPONSE_BYTES


def test_recommended_are_packed_greedily_within_sixteen_kib():
    big = [_entry(i, description="b" * 3900, schema={"type": "object", "properties": {
        f"p{j}": {"type": "string", "description": "z" * 100} for j in range(20)}}) for i in range(5)]
    response = build_list_response("x", _scored(big, [9, 9, 9, 9, 9]), catalog_revision=REV)
    assert size_of(response["recommended"]) <= MAX_RECOMMENDED_BYTES
    assert 1 <= len(response["recommended"]) < 5
    assert {entry["id"] for entry in response["others"]} == {e.id for e in big} - {
        entry["id"] for entry in response["recommended"]}


def test_summary_is_the_first_non_empty_line_bounded():
    assert summary_of("\n  Première ligne.  \nSeconde") == "Première ligne."
    long = summary_of("a" * 300)
    assert len(long) == MAX_SUMMARY_CHARS and long.endswith("…")


# ------------------------------------------------------------------ curseur

def test_cursor_pages_through_every_tool_once():
    entries = _catalog(150)
    ranked = _ranked("outil mail", entries)
    first = build_list_response("outil mail", ranked, catalog_revision=REV, limit=40)
    seen = [entry["id"] for entry in first["recommended"]] + [entry["id"] for entry in first["others"]]
    cursor = first["next_cursor"]
    while cursor:
        page = build_list_response("outil mail", ranked, catalog_revision=REV, cursor=cursor, limit=40)
        assert page["recommended"] == [] and page["notes"] == []
        seen += [entry["id"] for entry in page["others"]]
        cursor = page["next_cursor"]
    assert sorted(seen) == sorted(entry.id for entry in entries) and len(seen) == len(set(seen))


def test_a_stale_cursor_restarts_at_zero_with_catalog_changed():
    entries = _catalog(100)
    ranked = _ranked("outil", entries)
    first = build_list_response("outil", ranked, catalog_revision=REV, limit=10)
    restarted = build_list_response("outil", ranked, catalog_revision="nabcdef12.e8", cursor=first["next_cursor"],
                                    limit=10)
    assert restarted["notes"] == ["catalog_changed"]
    fresh = build_list_response("outil", ranked, catalog_revision="nabcdef12.e8", limit=10)
    assert restarted["others"] == fresh["others"] and restarted["recommended"] == fresh["recommended"]


def test_a_cursor_for_another_intent_is_refused():
    cursor = encode_cursor(REV, 10, "envoyer un mail")
    with pytest.raises(McpPluginError) as refused:
        build_list_response("lire l'agenda", _ranked("agenda", _catalog(20)), catalog_revision=REV, cursor=cursor)
    assert refused.value.code is McpErrorCode.CURSOR_INVALID


@pytest.mark.parametrize("cursor", ["", "%%%", "bm90IGpzb24", encode_cursor(REV, 0, "x")[:-3] + "AAA",
                                    "eyJyIjoxLCJvIjowLCJoIjoiMiJ9"])
def test_a_malformed_cursor_is_refused(cursor):
    with pytest.raises(McpPluginError) as refused:
        decode_cursor(cursor, "x")
    assert refused.value.code is McpErrorCode.CURSOR_INVALID


def test_the_cursor_carries_the_string_revision_offset_and_intent_hash():
    assert decode_cursor(encode_cursor(REV, 42, "mon intention"), "mon intention") == (REV, 42)


def test_limit_is_bounded():
    for limit in (0, 61, "30"):
        with pytest.raises(McpPluginError):
            build_list_response("x", [], catalog_revision=REV, limit=limit)  # type: ignore[arg-type]


# ------------------------------------------------------------------ intention vide, déterminisme

def test_an_empty_intent_recommends_nothing_and_lists_alphabetically():
    entries = [_entry(3), _entry(1), _entry(2)]
    response = build_list_response("les", _ranked("les", entries), catalog_revision=REV)
    assert response["recommended"] == []
    assert [entry["id"] for entry in response["others"]] == sorted(entry.id for entry in entries)


def test_same_input_gives_a_byte_identical_response():
    entries = _catalog()
    def once():
        return json.dumps(build_list_response("mail agenda", _ranked("mail agenda", entries), catalog_revision=REV,
                                              limit=30), ensure_ascii=False)
    assert once() == once()


def test_different_intents_give_different_recommendations():
    entries = [_entry(0, description="Envoyer un mail"), _entry(1, description="Lire l'agenda du jour"),
               _entry(2, description="Chercher un contact")]
    mail = build_list_response("envoyer un mail", _ranked("envoyer un mail", entries), catalog_revision=REV)
    agenda = build_list_response("lire l'agenda", _ranked("lire l'agenda", entries), catalog_revision=REV)
    assert mail["recommended"][0]["id"] == entries[0].id and agenda["recommended"][0]["id"] == entries[1].id


def test_notes_are_passed_through():
    response = build_list_response("x", [], catalog_revision=REV, notes=["plugins_unavailable"])
    assert response["notes"] == ["plugins_unavailable"] and response["total"] == 0 and response["next_cursor"] is None
