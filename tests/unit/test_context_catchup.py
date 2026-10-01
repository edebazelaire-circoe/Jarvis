"""Rattrapage rapide du cerveau (Slice 08 session-context) et modèle CLI d'enrichissement.

Contrat : `docs/session-context.md` › *Brain catch-up*, *Enrichment worker*
(modèle). Bases temporaires ; aucun CLI réel lancé.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jarvis.core.context_catchup import activity_lines, tail_text
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.artifacts import ArtifactKind, ArtifactQuery, ArtifactRelationKind, ArtifactState
from jarvis.domain.brain_context import (
    MAX_BRAIN_CATCHUP_ACTIVITY, MAX_BRAIN_TRANSCRIPT_TAIL_CHARS, BrainSessionContext,
)
from jarvis.domain.session_activity import ActivityDraft, ActivityEvent, ActivityKind
from jarvis.ports.context_enrichment import MODEL_TIMEOUT, EnrichmentImage, EnrichmentModelError
from jarvis.runtime.agent_settings import AgentExecutionSettings
from jarvis.runtime.context_enrichment_model import (
    DEFAULT_ENRICHMENT_MODEL, ClaudeCliEnrichmentModel, enrichment_model_name, enrichment_model_provider,
)
from jarvis.runtime.session_context_brief import (
    BRIEF_AMBIENT_RULE, MAX_CATCHUP_BRIEF_BYTES, render_catchup, render_session_context_brief,
)


class Journal:
    def emit(self, kind, message, *, level="info", data=None) -> None:
        pass


@pytest.fixture
async def core(tmp_path):
    app = JarvisCoreApplication(data_root=tmp_path, diagnostics=Journal())
    await app.start()
    await app.context_enrichment.close()
    try:
        yield app
    finally:
        await app.stop()


async def conversation_id(core) -> str:
    return (await core.sessions.current()).binding.conversation_id


async def transcript_with_segments(core, view, texts):
    ctx = view.context
    audio = await core.artifacts.create(kind=ArtifactKind.AUDIO_RECORDING, source="capture.audio",
                                        jarvis_session_id=ctx.jarvis_session_id, context_id=ctx.context_id,
                                        payload_name="audio.wav")
    projection = await core.artifacts.create(kind=ArtifactKind.TRANSCRIPT, source="stt",
                                             jarvis_session_id=ctx.jarvis_session_id, context_id=ctx.context_id,
                                             payload_name="transcript.txt", artifact_id=f"{audio.artifact_id}_transcript",
                                             origins=((ArtifactRelationKind.TRANSCRIBED_FROM, audio.artifact_id),))
    for seq, text in enumerate(texts):
        await core.artifacts.record_text(
            artifact_id=f"{audio.artifact_id}_seg{seq}", kind=ArtifactKind.TRANSCRIPT_SEGMENT, source="stt",
            text=text, jarvis_session_id=ctx.jarvis_session_id, context_id=ctx.context_id, started_at=None,
            ended_at=None, duration_ms=1000, metadata={"audio_artifact_id": audio.artifact_id, "start_ms": seq * 1000,
                                                       "transcript_artifact_id": projection.artifact_id},
            origins=((ArtifactRelationKind.SEGMENT_OF, projection.artifact_id),),
            event=(ActivityKind.TRANSCRIPT_SEGMENT_CREATED, {"seq": seq}))
    await core.artifacts.update_pending(projection.artifact_id, text="\n".join(texts))
    return audio, projection


async def test_the_turn_block_carries_activity_transcript_tail_and_refs_of_the_active_context(core, monkeypatch):
    view = await core.sessions.current_context()
    long_text = "mot " * 600  # 2 400 caractères : seule la queue part
    audio, projection = await transcript_with_segments(core, view, ["Début de la réunion.", long_text + "FIN"])
    monkeypatch.setattr(core, "_live_capture_ids", lambda: frozenset({audio.artifact_id}))  # enregistrement en cours
    block = await core._session_context(await conversation_id(core))
    assert block.transcript_ref == projection.artifact_id
    assert block.transcript_tail.endswith("FIN") and len(block.transcript_tail) <= MAX_BRAIN_TRANSCRIPT_TAIL_CHARS
    assert "Début de la réunion" not in block.transcript_tail
    # Activité : natures, ids, heures ; les segments se replient ; jamais de texte.
    joined = "\n".join(block.activity)
    assert "transcript.segment.created ×2" in joined and "mot" not in joined
    assert any(ref.startswith("transcript ") for ref in block.artifact_refs)
    assert block.latest_seq == await core.artifacts.latest_seq()
    lines = render_session_context_brief(block.to_payload())
    text = "\n".join(lines)
    assert BRIEF_AMBIENT_RULE in text and "Activité récente du Context" in text and "FIN" in text


async def test_dormant_context_content_never_enters_the_catch_up(core):
    first = await core.sessions.current_context()
    await transcript_with_segments(core, first, ["secret du premier Context"])
    # La projection du premier est finie : seul un enregistrement **en cours** traverse un changement.
    page = await core.artifacts.query(ArtifactQuery(context_id=first.context.context_id,
                                                    kinds=(ArtifactKind.TRANSCRIPT,)))
    await core.artifacts.finalize(page.items[0].artifact_id, state=ArtifactState.PARTIAL)
    await core.sessions.create_context(title="Second")
    block = await core._session_context(await conversation_id(core))
    payload_text = str(block.to_payload())
    assert "secret du premier Context" not in payload_text
    assert first.context.context_id not in "\n".join(block.activity + block.artifact_refs)
    assert block.transcript_tail == ""


def event(seq: int, kind: ActivityKind, *, minute: int = 0, **data) -> ActivityEvent:
    return ActivityEvent(seq, ActivityDraft(kind=kind, occurred_at=datetime(2026, 10, 1, 9, minute, tzinfo=timezone.utc),
                                            jarvis_session_id="jsess_a", context_id="jctx_a",
                                            artifact_ids=(f"jart_{seq}",), data=data))


def test_activity_lines_fold_segment_runs_drop_noise_and_stay_bounded():
    events = [event(1, ActivityKind.CAPTURE_STARTED, channel="audio")]
    events += [event(seq, ActivityKind.TRANSCRIPT_SEGMENT_CREATED, minute=seq % 60) for seq in range(2, 40)]
    events += [event(40, ActivityKind.TRANSCRIPT_PROJECTION_UPDATED)]
    events += [event(seq, ActivityKind.ARTIFACT_FINALIZED, artifact_kind="screenshot") for seq in range(41, 60)]
    lines = activity_lines(tuple(events))
    assert len(lines) == MAX_BRAIN_CATCHUP_ACTIVITY
    assert not any("projection" in line for line in lines)
    assert lines[-1].endswith("artifact.finalized screenshot jart_59")
    folded = activity_lines(tuple(events[:39]))
    assert any("transcript.segment.created ×38 (dernier jart_39)" in line for line in folded)


def test_tail_text_starts_on_a_whole_word():
    tail = tail_text("alpha " * 400, 100)
    assert len(tail) <= 100 and tail.startswith("…alpha")


def test_worst_case_catch_up_rendering_stays_within_its_byte_budget():
    block = {
        "transcript_tail": "é" * MAX_BRAIN_TRANSCRIPT_TAIL_CHARS, "transcript_ref": "jart_" + "a" * 123,
        "artifact_refs": ["screenshot jart_" + "b" * 120 + " complete"] * 8,
        "activity": ["09:00 " + "x" * 154] * MAX_BRAIN_CATCHUP_ACTIVITY, "latest_seq": 123456,
    }
    lines = render_catchup(block)
    assert sum(len(line.encode("utf-8")) + 1 for line in lines) <= MAX_CATCHUP_BRIEF_BYTES
    assert lines[0].startswith("Transcription ambiante récente") and BRIEF_AMBIENT_RULE in lines[0]
    assert render_catchup({}) == []


def test_the_turn_block_refuses_an_unbounded_catch_up():
    base = dict(jarvis_session_id="jsess_a", context_id="jctx_a", workspace_path="C:/w", sessions_root="C:/s")
    with pytest.raises(ValueError):
        BrainSessionContext(**base, activity=("x",) * (MAX_BRAIN_CATCHUP_ACTIVITY + 1))
    with pytest.raises(ValueError):
        BrainSessionContext(**base, transcript_tail="x" * (MAX_BRAIN_TRANSCRIPT_TAIL_CHARS + 1))
    assert "activity" not in BrainSessionContext(**base).to_payload()  # bloc d'avant inchangé sans rattrapage


# ------------------------------------------------------------------ modèle CLI


class FakeAgent:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[tuple] = []
        self.closed = False

    async def ask(self, text, *, timeout_s, **kwargs):
        self.calls.append((text, timeout_s, kwargs))
        return self.result

    async def close_owned(self):
        self.closed = True
        return True


def settings(tmp_path, agent_cli="claude") -> AgentExecutionSettings:
    return AgentExecutionSettings(agent_cli, "anthropic", "claude", "opus", "bypassPermissions", tmp_path, tmp_path)


async def test_the_cli_model_returns_text_cost_and_closes_its_owned_agent(tmp_path):
    agent = FakeAgent({"ok": True, "text": "# R", "cost_usd": 0.0031, "duration_ms": 900,
                       "usage": {"input_tokens": 1200, "output_tokens": 80, "other": "x"}})
    model = ClaudeCliEnrichmentModel(settings(tmp_path), "haiku", agent_factory=lambda s, m: agent)
    reply = await model.complete("p", timeout_s=5, images=(EnrichmentImage("image/png", b"png"),))
    assert (reply.text, reply.cost_usd, reply.model) == ("# R", 0.0031, "haiku")
    assert reply.usage == {"input_tokens": 1200, "output_tokens": 80}
    assert agent.calls[0][2]["images"] == (("image/png", b"png"),) and agent.closed
    evidence = agent.calls[0][2]["prompt_evidence"]
    assert evidence["program_id"] == "backend.claude.context_enrichment.describe_turn"
    assert evidence["static_fingerprint"] and "text" not in evidence


async def test_the_cli_model_maps_a_timeout_and_keeps_the_provider_cause(tmp_path):
    agent = FakeAgent({"ok": False, "code": "claude_timeout", "error": "Claude n'a pas répondu en 5 secondes."})
    model = ClaudeCliEnrichmentModel(settings(tmp_path), "haiku", agent_factory=lambda s, m: agent)
    with pytest.raises(EnrichmentModelError) as caught:
        await model.complete("p", timeout_s=5)
    assert caught.value.code == MODEL_TIMEOUT and "5 secondes" in caught.value.detail and agent.closed


def test_the_provider_needs_a_native_claude_cli_and_reads_the_model_from_env(tmp_path, monkeypatch):
    provider = enrichment_model_provider(lambda: {"agent_cli": "codex"}, cwd=tmp_path, runtime_root=tmp_path)
    assert provider() is None
    assert enrichment_model_name({}) == DEFAULT_ENRICHMENT_MODEL == "haiku"
    assert enrichment_model_name({"JARVIS_CONTEXT_ENRICHMENT_MODEL": " sonnet "}) == "sonnet"


async def test_images_are_refused_outside_the_tool_less_profile(tmp_path):
    from jarvis.runtime.claude_local import ClaudeLocalAgent

    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude", execution_profile="conversation")
    with pytest.raises(ValueError):
        await agent.send("x", images=(("image/png", b"x"),))
