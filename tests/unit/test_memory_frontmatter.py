from __future__ import annotations

import pytest

from jarvis.adapters import memory_frontmatter as fm


def test_round_trip_keeps_values_order_and_body():
    meta = {
        "id": "abc123", "level": "L1", "confidence": 0.75, "revision": 3, "flag": True, "none": None,
        "tags": ["a", "é", 3], "sources": [{"type": "turn", "ref": "t-1", "at": "2026-10-07T09:00:00+00:00"}],
        "quote": 'dit "oui": ok', "unicode": "ligne\u2028séparée \U0001f600",
    }
    body = "# Titre\n\nCorps avec --- au milieu\n---\nfin\n"
    parsed = fm.parse(fm.compose(meta, body))
    assert parsed.has_block and not parsed.corrupt
    assert dict(parsed.meta) == meta
    assert list(parsed.meta) == list(meta)
    assert parsed.body == body


def test_text_without_a_block_is_all_body():
    for text in ("", "# Titre\n\ncorps\n", "pas --- de bloc\n", "texte\n---\nid: 1\n---\n"):
        parsed = fm.parse(text)
        assert not parsed.has_block and not parsed.corrupt
        assert dict(parsed.meta) == {} and parsed.body == text


def test_unterminated_block_is_a_horizontal_rule_not_metadata():
    text = '---\nid: "x"\n# Titre\n'
    parsed = fm.parse(text)
    assert not parsed.has_block and parsed.body == text


def test_empty_block_and_blank_lines_are_valid():
    parsed = fm.parse("---\n---\ncorps")
    assert parsed.has_block and dict(parsed.meta) == {} and parsed.body == "corps"
    parsed = fm.parse('---\n\nid: "x"\n\n---\ncorps')
    assert parsed.has_block and dict(parsed.meta) == {"id": "x"}


def test_crlf_and_bom_are_tolerated():
    parsed = fm.parse('\ufeff---\r\nid: "x"\r\nrevision: 2\r\n---\r\n# T\r\n')
    assert parsed.has_block and dict(parsed.meta) == {"id": "x", "revision": 2}
    assert parsed.body == "# T\r\n"


@pytest.mark.parametrize("block", [
    "id: 'single quotes'",       # not JSON
    "id = 1",                    # not key: value
    "just text",                 # not key: value
    'id: "a"\nid: "b"',          # duplicate key
    "score: NaN",                # JSON extension refused
    "score: Infinity",
    "id:",                       # empty value
    "9bad: 1",                   # key is not an identifier
    "id: [1, 2",                 # truncated JSON
])
def test_corrupt_block_falls_back_to_whole_text_as_body(block):
    text = f"---\n{block}\n---\n# Titre\n\ncorps\n"
    parsed = fm.parse(text)
    assert parsed.corrupt and not parsed.has_block
    assert dict(parsed.meta) == {}
    assert parsed.body == text, "nothing the human wrote is dropped"


def test_meta_is_read_only():
    parsed = fm.parse('---\nid: "x"\n---\n')
    with pytest.raises(TypeError):
        parsed.meta["id"] = "y"  # type: ignore[index]


@pytest.mark.parametrize("meta", [
    {"bad key": 1}, {"9x": 1}, {"k": float("nan")}, {"k": float("inf")}, {"k": object()}, {"k": {1, 2}}, {1: "x"},
])
def test_render_refuses_what_the_parser_would_refuse(meta):
    with pytest.raises(ValueError):
        fm.render(meta)


def test_render_never_emits_a_raw_newline_inside_a_value():
    text = fm.render({"k": "a\nb\r\nc"})
    assert text == '---\nk: "a\\nb\\r\\nc"\n---\n'
    assert dict(fm.parse(text + "x").meta) == {"k": "a\nb\r\nc"}
