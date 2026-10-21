"""Journal diagnostique : le texte des outils de relation n'est jamais recopié, les autres résultats sont bornés."""

import json

from jarvis.runtime.cli_stream import JOURNAL_TOOL_RESULT_CHARS, ToolContentRedactor

SENTINEL = "Proposition secrète 4291 : utiliser un seau à jetons"


def _call(tool_id: str, name: str, payload: dict) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tool_id, "name": name, "input": payload}]}}


def _result(tool_id: str, content) -> dict:
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": content}]},
        "tool_use_result": {"text": content}}


def test_a_relation_call_keeps_ids_and_codes_but_never_its_text():
    redactor = ToolContentRedactor()
    view = redactor.view(_call("toolu_1", "mcp__jarvis-workspace__relation_post",
                               {"relation_id": "rel_42", "kind": "proposal", "text": SENTINEL}))
    dumped = json.dumps(view, ensure_ascii=False)
    assert SENTINEL not in dumped
    payload = view["message"]["content"][0]["input"]
    assert payload["relation_id"] == "rel_42" and payload["kind"] == "proposal"
    assert payload["text"] == {"redacted_chars": len(SENTINEL)}


def test_the_result_of_a_relation_call_is_withheld_with_its_size():
    redactor = ToolContentRedactor()
    redactor.view(_call("toolu_2", "mcp__jarvis-workspace__relation_read", {"relation_id": "rel_42"}))
    view = redactor.view(_result("toolu_2", [{"type": "text", "text": SENTINEL}]))
    dumped = json.dumps(view, ensure_ascii=False)
    assert SENTINEL not in dumped
    block = view["message"]["content"][0]
    assert block["content_withheld"] is True and block["content_chars"] == len(SENTINEL)
    assert view["tool_use_result"]["withheld"] is True


def test_another_tool_result_is_bounded_and_a_short_one_is_untouched():
    redactor = ToolContentRedactor()
    long_text = "x" * (JOURNAL_TOOL_RESULT_CHARS * 3)
    bounded = redactor.view(_result("toolu_3", long_text))
    block = bounded["message"]["content"][0]
    assert block["content_chars"] == len(long_text)
    assert len(block["content"]) < len(long_text)
    short = _result("toolu_4", "ok")
    assert redactor.view(short) is short


def test_the_received_event_is_never_modified():
    redactor = ToolContentRedactor()
    event = _call("toolu_5", "mcp__jarvis-workspace__relation_post", {"text": SENTINEL})
    before = json.dumps(event, ensure_ascii=False)
    redactor.view(event)
    assert json.dumps(event, ensure_ascii=False) == before
