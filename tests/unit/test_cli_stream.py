"""Lecture des flux des CLI enfants (handoff jarvis-constellation-scene-runtime, Slice 09, reprise QA).

- une ligne au-delà de la borne est écartée **entière** (aucun fragment ne revient comme ligne) ;
- toute donnée base64 d'une image, où qu'elle soit (contenu du résultat, `tool_use_result`, forme MCP),
  ne garde que sa taille : ni journal, ni API, ni historique, ni traces de sous-tâches ;
- un événement trop gros est journalisé en résumé ; `/api/trace` lit la fin du fichier par blocs ;
- Claude, Codex et le superviseur lisent par ce module ; un Codex qui s'attarde est tué à l'échéance.
Fixture : la forme réelle d'un événement du CLI 2.1.274 portant la capture, base64 synthétique de même longueur.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import random
import sys
import textwrap
import time

import pytest

from jarvis.runtime import claude_local, codex_local, journal
from jarvis.runtime.cli_stream import (
    MAX_JOURNAL_EVENT_BYTES,
    OversizeLine,
    iter_lines,
    journal_view,
    may_carry_media,
    redact_media,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cli_scene_capture_tool_result_event.json"
PNG_B64_MARK = "iVBOR"


def real_event() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ lignes


async def lines_of(chunks: list[bytes], limit: int) -> list:
    reader = asyncio.StreamReader()
    for chunk in chunks:
        reader.feed_data(chunk)
    reader.feed_eof()
    return [item async for item in iter_lines(reader, limit=limit, chunk_bytes=7)]


async def test_an_oversize_line_is_dropped_whole_and_the_next_line_is_intact():
    rng = random.Random(3)
    data = b"a" * 10 + b"\n" + b"X" * 100 + b"\n" + b"b" * 20 + b"\n" + b"c" * 21 + b"\n" + b"tail-no-newline"
    for _ in range(30):
        cuts = sorted(rng.sample(range(1, len(data)), 12))
        chunks = [data[i:j] for i, j in zip([0, *cuts], [*cuts, len(data)])]
        result = await lines_of(chunks, limit=20)
        assert result == [b"a" * 10, OversizeLine(100), b"b" * 20, OversizeLine(21), b"tail-no-newline"]
    assert await lines_of([b"Y" * 50], limit=20) == [OversizeLine(50)]  # trop long jusqu'à la fin du flux
    assert await lines_of([b"\n\n"], limit=5) == [b"", b""]


async def test_line_only_test_doubles_keep_the_same_contract():
    class Doubled:
        def __init__(self) -> None:
            self.lines = [b"ok\n", b"Z" * 30 + b"\n", b"last"]

        async def readline(self) -> bytes:
            return self.lines.pop(0) if self.lines else b""

    assert [item async for item in iter_lines(Doubled(), limit=10)] == [b"ok", OversizeLine(30), b"last"]


# ------------------------------------------------------------------ images


def test_every_base64_copy_in_the_real_cli_event_shape_keeps_only_its_size():
    event = real_event()
    raw = json.dumps(event).encode()
    assert raw.count(PNG_B64_MARK.encode()) == 2 and may_carry_media(raw)  # deux copies dans l'événement réel
    redacted = redact_media(event)
    text = json.dumps(redacted)
    assert PNG_B64_MARK not in text and len(text) < 3000
    for block in (redacted["message"]["content"][0]["content"][1], redacted["tool_use_result"][1]):
        assert block == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "omitted_bytes": 39124}}
    assert redacted["message"]["content"][0]["content"][0] is event["message"]["content"][0]["content"][0]  # texte non copié
    assert PNG_B64_MARK in json.dumps(event)  # l'original n'est pas modifié
    other = {"type": "user", "deep": [{"x": {"type": "image", "mimeType": "image/png", "data": "iVBOR" + "A" * 99}},
                                      {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBER" * 10}}]}
    cleaned = redact_media(other)
    assert cleaned["deep"][0]["x"] == {"type": "image", "mimeType": "image/png", "omitted_bytes": 104}
    assert cleaned["deep"][1]["source"] == {"type": "base64", "media_type": "application/pdf", "omitted_bytes": 50}
    plain = {"type": "assistant", "message": {"content": [{"type": "text", "text": "image"}]}}
    assert redact_media(plain) is plain


def test_a_huge_event_is_journaled_as_a_bounded_summary():
    small = {"type": "user", "text": "x"}
    assert journal_view(small, size=10) is small
    big = {"type": "stdout", "text": "t" * (MAX_JOURNAL_EVENT_BYTES + 10), "session_id": "s"}
    view = journal_view(big, size=MAX_JOURNAL_EVENT_BYTES + 40)
    assert view["journal_truncated"] is True and view["bytes"] > MAX_JOURNAL_EVENT_BYTES and view["session_id"] == "s"
    assert len(json.dumps(view)) < 3000


def test_the_trace_tail_reads_blocks_from_the_end(tmp_path, monkeypatch):
    path = tmp_path / "trace.jsonl"
    path.write_text("".join(json.dumps({"i": i, "pad": "x" * (i % 5 * 900)}) + "\n" for i in range(60)) + "not json\n",
                    encoding="utf-8")
    monkeypatch.setattr(journal, "TAIL_BLOCK_BYTES", 512)
    assert [item["i"] for item in journal.read_jsonl_tail(path, limit=5)] == [56, 57, 58, 59]  # la ligne illisible compte dans la limite, comme avant
    assert len(journal.read_jsonl_tail(path, limit=500)) == 60
    monkeypatch.setattr(journal, "MAX_TAIL_BYTES", 12 * 1024)
    assert 0 < len(journal.read_jsonl_tail(path, limit=500)) < 60  # borne de lecture respectée


# ------------------------------------------------------------------ Claude, vrai sous-processus


FAKE_CLAUDE = textwrap.dedent(r'''
    import json, sys
    event = json.loads(open(sys.argv[1], encoding="utf-8").read())
    out = sys.stdout.buffer
    def write(data):
        for i in range(0, len(data), 65536):
            out.write(data[i:i + 65536]); out.flush()
    write(json.dumps({"type": "system", "subtype": "init", "session_id": "fake"}).encode() + b"\n")
    for raw in sys.stdin.buffer:
        msg = json.loads(raw)
        uuid = msg.get("uuid")
        for _ in range(40):  # 40 résultats d'outil portant l'image, chacun en deux copies
            write(json.dumps(event).encode() + b"\n")
        write(b'{"type":"user","message":{"content":[{"type":"text","text":"' + b"L" * (17 * 1024 * 1024) + b'"}]}}\n')
        write(json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "p" * 300000}]}}).encode() + b"\n")
        sys.stderr.buffer.write(b"E" * (17 * 1024 * 1024) + b"\nstderr after\n"); sys.stderr.buffer.flush()
        write(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok", "session_id": "fake",
                          "duration_ms": 5, "total_cost_usd": 0.0, "user_message_uuids": [uuid]}).encode() + b"\n")
''')


async def test_claude_never_stores_base64_or_fragments_anywhere(monkeypatch, tmp_path):
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLAUDE, encoding="utf-8")
    real_exec = asyncio.create_subprocess_exec

    async def fake_exec(program, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return await real_exec(sys.executable, str(script), str(FIXTURE), **kwargs)

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    agent = claude_local.ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path, command="claude")
    if agent._process_tree is not None:
        monkeypatch.setattr(agent._process_tree, "attach_and_resume", lambda pid: None)
    await agent.start(resume=False)
    try:
        answer = await agent.ask("bonjour", timeout_s=60)
        await asyncio.sleep(0.5)
        assert answer["ok"] is True and answer["text"] == "ok", answer
        trace_text = (tmp_path / "runtime" / "trace.jsonl").read_text(encoding="utf-8")
        entries = [json.loads(line) for line in trace_text.splitlines()]
        assert PNG_B64_MARK not in trace_text
        assert max(len(line) for line in trace_text.splitlines()) < MAX_JOURNAL_EVENT_BYTES + 4096
        too_long = [e["data"] for e in entries if e["kind"] == "agent.stream_line_too_long"]
        assert sorted(item["stream"] for item in too_long) == ["stderr", "stdout"]
        assert not any(e["kind"] == "agent.event" and e["data"].get("type") == "stdout" for e in entries)  # aucun fragment
        assert [e["message"] for e in entries if e["kind"] == "agent.stderr"] == ["stderr after"]
        assert any(e["data"].get("journal_truncated") for e in entries if e["kind"] == "agent.event")
        for surface in (agent.snapshot(), agent.transcript(limit=500), agent.task_trace("brain", limit=500), agent.tasks_snapshot(),
                        agent._events):
            assert PNG_B64_MARK not in json.dumps(surface, default=str)
        assert sum(len(json.dumps(event)) for event in agent._events) < 2 * 1024 * 1024  # 40 images ne restent pas en mémoire
        tool_results = [e["data"] for e in entries if e["kind"] == "agent.event" and "tool_use_result" in e["data"]]
        assert len(tool_results) == 40 and tool_results[0]["tool_use_result"][1]["source"]["omitted_bytes"] == 39124
    finally:
        await agent.stop()


# ------------------------------------------------------------------ Codex, vrai sous-processus


FAKE_CODEX = textwrap.dedent(r'''
    import json, sys, time
    sys.stdin.buffer.read()
    mode = sys.argv[1]
    out = sys.stdout.buffer
    out.write(json.dumps({"type": "thread.started", "thread_id": "t1"}).encode() + b"\n")
    out.write(json.dumps({"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "o" * 100000}}).encode() + b"\n")
    out.write(b'{"type":"noise","pad":"' + b"Q" * (17 * 1024 * 1024) + b'"}\n')
    out.write(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "réponse"}}).encode() + b"\n")
    out.write(json.dumps({"type": "turn.completed", "usage": {}}).encode() + b"\n"); out.flush()
    if mode == "linger":
        for _ in range(40):
            out.write(b'{"type":"noise","pad":"' + b"x" * 60000 + b'"}\n'); out.flush()
        time.sleep(60)
''')


@pytest.mark.parametrize("mode", ["exit", "linger"])
async def test_codex_reads_long_lines_and_a_lingering_process_is_killed_at_the_deadline(monkeypatch, tmp_path, mode):
    script = tmp_path / "fake_codex.py"
    script.write_text(FAKE_CODEX, encoding="utf-8")
    real_exec = asyncio.create_subprocess_exec

    async def fake_exec(*argv, **kwargs):  # noqa: ANN002, ANN003
        return await real_exec(sys.executable, str(script), mode, **kwargs)

    monkeypatch.setattr(codex_local.asyncio, "create_subprocess_exec", fake_exec)
    agent = codex_local.CodexLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path, command=sys.executable)
    agent._started = True
    if getattr(agent, "_process_tree", None) is not None:
        monkeypatch.setattr(agent._process_tree, "attach_and_resume", lambda pid: None)
    started = time.monotonic()
    answer = await asyncio.wait_for(agent.ask("bonjour", timeout_s=4), 20)
    elapsed = time.monotonic() - started
    entries = [json.loads(line) for line in (tmp_path / "runtime" / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = [e["kind"] for e in entries]
    assert "agent.stream_line_too_long" in kinds
    assert not any(e["kind"] == "agent.event" and e["data"].get("type") == "stdout" for e in entries)
    if mode == "exit":
        assert answer["ok"] is True and answer["text"] == "réponse" and elapsed < 4
    else:
        assert answer["code"] == "codex_timeout" and elapsed < 12 and "agent.ask_timeout" in kinds
    assert agent.process is None


# ------------------------------------------------------------------ superviseur


async def test_the_supervisor_stderr_pump_drops_an_oversize_line_whole(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("supervisor_v2_test", Path(__file__).resolve().parents[2] / "scripts" / "supervisor_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Journal:
        def emit(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return None

    supervisor = module.Supervisor(journal=Journal(), runtime_root=tmp_path)
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c",
        "import sys; e=sys.stderr.buffer; e.write(b'avant\\n' + b'E' * (17 * 1024 * 1024) + b'\\napres\\n'); e.flush()",
        stderr=asyncio.subprocess.PIPE,
    )
    await supervisor._pump_stderr("voice", process)
    await process.wait()
    tail = list(supervisor._tails["voice"])
    assert tail[0] == "avant" and tail[-1] == "apres" and len(tail) == 3 and "ignorée" in tail[1]
    log = (tmp_path / "logs" / "voice.log").read_text(encoding="utf-8")
    assert "EEEE" not in log
