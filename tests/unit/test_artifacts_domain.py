"""Contrat pur du registre d'Artifacts et du ledger d'activité (handoff session-context-recording, Slice 04).

Contrat : `docs/artifacts.md`. Aucune E/S.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from jarvis.domain.artifacts import (
    MAX_ARTIFACT_LIMIT, MAX_ARTIFACT_TEXT_CHARS, MAX_RELATIONS_PER_ARTIFACT, Artifact, ArtifactError,
    ArtifactErrorCode, ArtifactKind, ArtifactQuery, ArtifactRelation, ArtifactRelationKind, ArtifactState,
    check_artifact_update, check_relations, decode_artifact_cursor, enrich_artifact, fail_artifact,
    finalize_artifact, new_artifact, parse_payload_ref, payload_ref_for, update_pending,
)
from jarvis.domain.session_activity import (
    MAX_ACTIVITY_LIMIT, ActivityDraft, ActivityError, ActivityEvent, ActivityKind, ActivityQuery,
    context_transition_events, session_event,
)
from jarvis.domain.session_context import activate_context, create_context
from jarvis.domain.workspace_board import default_board, open_session

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
SID = "jsess_0123456789abcdef"
CID = "jctx_0123456789abcdef"
AID = "jart_0123456789abcdef"
OID = "jart_fedcba9876543210"


def t(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def audio(**overrides) -> Artifact:
    values = dict(kind=ArtifactKind.AUDIO_RECORDING, source="capture.audio", now=T0, jarvis_session_id=SID,
                  context_id=CID, payload_name="source.wav", mime_type="audio/wav", artifact_id=AID)
    values.update(overrides)
    return new_artifact(**values)


def code(caught) -> ArtifactErrorCode:  # noqa: ANN001
    return caught.value.code


# ------------------------------------------------------------------ identité et chemins


def test_new_artifact_is_pending_with_its_reserved_relative_payload():
    artifact = audio()
    assert artifact.state is ArtifactState.PENDING and artifact.is_pending
    assert artifact.payload_ref == f"artifacts/{AID}/source.wav" and artifact.payload_name == "source.wav"
    assert artifact.created_at == artifact.updated_at == T0
    generated = new_artifact(kind=ArtifactKind.SCREENSHOT, source="capture.screen", now=T0)
    assert generated.artifact_id.startswith("jart_") and generated.artifact_id == generated.artifact_id.lower()


@pytest.mark.parametrize("bad", ["jart_", "jart_A", "jart_a.b", "jart_../x", "jctx_abc", "jart_a/b", "", 3,
                                 "jart_" + "a" * 124])
def test_artifact_ids_are_lowercase_path_safe_segments(bad):
    with pytest.raises(ArtifactError) as caught:
        audio(artifact_id=bad)
    assert code(caught) is ArtifactErrorCode.INVALID_ARTIFACT


@pytest.mark.parametrize("name", ["..", "../x", "a/b", "A.wav", ".hidden", "x.wav.partial", "a..b", "", "a" * 65,
                                  "c:x", "a\\b"])
def test_payload_names_refuse_traversal_case_hidden_and_partial(name):
    with pytest.raises(ArtifactError):
        payload_ref_for(AID, name)


@pytest.mark.parametrize("ref", ["/artifacts/jart_a/x", "artifacts/jart_a/sub/x", "sessions/jart_a/x",
                                 "artifacts/jart_A/x", "C:/artifacts/jart_a/x", "artifacts/jart_a/..", 12])
def test_payload_ref_has_exactly_one_shape(ref):
    with pytest.raises(ArtifactError):
        parse_payload_ref(ref)
    assert parse_payload_ref("artifacts/jart_a/x.png") == ("jart_a", "x.png")


def test_payload_ref_must_live_in_the_artifacts_own_folder():
    with pytest.raises(ArtifactError) as caught:
        Artifact(artifact_id=AID, kind=ArtifactKind.SCREENSHOT, source="s", state=ArtifactState.PENDING,
                 created_at=T0, updated_at=T0, payload_ref=f"artifacts/{OID}/x.png")
    assert "own folder" in str(caught.value)


def test_context_needs_its_session_and_unknown_kinds_are_refused():
    with pytest.raises(ArtifactError):
        audio(jarvis_session_id=None)
    with pytest.raises(ArtifactError):
        Artifact.from_payload({**audio().to_payload(), "kind": "other"})
    with pytest.raises(ArtifactError):
        audio(mime_type="Audio/WAV")


# ------------------------------------------------------------------ états


def test_finalize_reaches_complete_or_partial_once():
    done = finalize_artifact(audio(), now=t(5), size_bytes=1024, ended_at=t(5), duration_ms=300_000)
    assert (done.state, done.size_bytes, done.duration_ms, done.updated_at) == (ArtifactState.COMPLETE, 1024,
                                                                              300_000, t(5))
    for again in (lambda a: finalize_artifact(a, now=t(6), size_bytes=1),
                  lambda a: fail_artifact(a, now=t(6), error_code="x"),
                  lambda a: update_pending(a, now=t(6), size_bytes=1)):
        with pytest.raises(ArtifactError) as caught:
            again(done)
        assert code(caught) is ArtifactErrorCode.ARTIFACT_NOT_PENDING
    partial = finalize_artifact(audio(), now=t(5), state=ArtifactState.PARTIAL, size_bytes=10,
                                error_code="artifact_recovered")
    assert partial.state is ArtifactState.PARTIAL and partial.error_code == "artifact_recovered"
    with pytest.raises(ArtifactError):
        finalize_artifact(audio(), now=t(5), state=ArtifactState.FAILED)


def test_state_invariants():
    with pytest.raises(ArtifactError):  # complete sans payload ni texte
        finalize_artifact(audio(payload_name=None), now=t(1))
    with pytest.raises(ArtifactError):  # complete à payload sans taille
        finalize_artifact(audio(), now=t(1))
    with pytest.raises(ArtifactError):  # complete ne porte pas de code d'erreur
        finalize_artifact(audio(), now=t(1), size_bytes=1, error_code="x")
    text = finalize_artifact(audio(payload_name=None, kind=ArtifactKind.TRANSCRIPT_SEGMENT), now=t(1), text="bonjour")
    assert text.state is ArtifactState.COMPLETE and text.text == "bonjour"
    with pytest.raises(ArtifactError):
        finalize_artifact(audio(payload_name=None), now=t(1), text="x" * (MAX_ARTIFACT_TEXT_CHARS + 1))
    failed = fail_artifact(audio(), now=t(1), error_code="source_lost")
    assert failed.state is ArtifactState.FAILED and failed.error_code == "source_lost"
    with pytest.raises(ArtifactError):
        fail_artifact(audio(), now=t(1), error_code="pas un jeton")


def test_pending_progress_and_time_order():
    progressing = update_pending(audio(), now=t(1), size_bytes=4096, duration_ms=1000)
    assert progressing.is_pending and progressing.size_bytes == 4096
    with pytest.raises(ArtifactError):
        audio(started_at=t(2)).__class__(**{**_fields(audio(started_at=t(2))), "ended_at": t(1)})
    with pytest.raises(ArtifactError):
        Artifact(artifact_id=AID, kind=ArtifactKind.SCREENSHOT, source="s", state=ArtifactState.PENDING,
                 created_at=T0, updated_at=T0 - timedelta(seconds=1))
    with pytest.raises(ArtifactError):
        Artifact(artifact_id=AID, kind=ArtifactKind.SCREENSHOT, source="s", state=ArtifactState.PENDING,
                 created_at=datetime(2026, 10, 1), updated_at=T0)


def _fields(artifact: Artifact) -> dict:
    return {name: getattr(artifact, name) for name in Artifact.__dataclass_fields__}


def test_enrichment_is_appendable_in_any_state_without_touching_acquisition():
    done = finalize_artifact(audio(), now=t(5), size_bytes=10)
    enriched = enrich_artifact(done, {"description": "réunion", "speakers": 2}, now=t(9))
    assert dict(enriched.enrichment) == {"description": "réunion", "speakers": 2}
    check_artifact_update(done, enriched)  # autorisé : seul l'enrichissement change
    removed = enrich_artifact(enriched, {"speakers": None}, now=t(10))
    assert dict(removed.enrichment) == {"description": "réunion"}
    with pytest.raises(ArtifactError):
        enrich_artifact(done, {"long": "x" * 4001}, now=t(9))
    with pytest.raises(ArtifactError):
        enrich_artifact(done, {"nested": {"a": 1}}, now=t(9))
    with pytest.raises(ArtifactError):
        enrich_artifact(done, {}, now=t(9))


def test_update_guard_freezes_identity_and_terminal_acquisition_fields():
    pending = audio()
    done = finalize_artifact(pending, now=t(5), size_bytes=10)
    check_artifact_update(pending, done)
    from dataclasses import replace
    with pytest.raises(ArtifactError) as caught:
        check_artifact_update(pending, replace(done, source="other"))
    assert code(caught) is ArtifactErrorCode.ARTIFACT_CONFLICT
    with pytest.raises(ArtifactError) as caught:
        check_artifact_update(done, replace(done, size_bytes=99, updated_at=t(6)))
    assert code(caught) is ArtifactErrorCode.ARTIFACT_NOT_PENDING
    with pytest.raises(ArtifactError):
        check_artifact_update(done, replace(done, updated_at=t(1)))


def test_codec_round_trips_and_is_strict():
    artifact = enrich_artifact(finalize_artifact(audio(started_at=T0), now=t(5), size_bytes=7, width=None),
                               {"k": "v"}, now=t(6))
    assert Artifact.from_payload(artifact.to_payload()) == artifact
    payload = artifact.to_payload()
    for broken in ({**payload, "extra": 1}, {k: v for k, v in payload.items() if k != "state"},
                   {**payload, "created_at": "2026-10-01T09:00:00"}, {**payload, "state": "done"},
                   {**payload, "size_bytes": True}, {**payload, "width": 10}):
        with pytest.raises(ArtifactError):
            Artifact.from_payload(broken)


# ------------------------------------------------------------------ relations


def test_relations_name_two_distinct_artifacts_with_a_closed_vocabulary():
    relation = ArtifactRelation(AID, ArtifactRelationKind.TRANSCRIBED_FROM, OID, T0)
    assert ArtifactRelation.from_payload(relation.to_payload()) == relation
    with pytest.raises(ArtifactError) as caught:
        ArtifactRelation(AID, ArtifactRelationKind.DERIVED_FROM, AID, T0)
    assert code(caught) is ArtifactErrorCode.INVALID_RELATION
    with pytest.raises(ArtifactError):
        ArtifactRelation.from_payload({**relation.to_payload(), "relation": "copied_from"})
    with pytest.raises(ArtifactError):
        check_relations(AID, (relation, relation))
    with pytest.raises(ArtifactError):
        check_relations(OID, (relation,))
    many = tuple(ArtifactRelation(AID, ArtifactRelationKind.DERIVED_FROM, f"jart_{i:04d}", T0)
                 for i in range(MAX_RELATIONS_PER_ARTIFACT + 1))
    with pytest.raises(ArtifactError):
        check_relations(AID, many)


# ------------------------------------------------------------------ requêtes


def test_artifact_query_bounds():
    ArtifactQuery(limit=MAX_ARTIFACT_LIMIT, kinds=(ArtifactKind.SCREENSHOT,), since=T0, until=t(1))
    for bad in (dict(limit=0), dict(limit=MAX_ARTIFACT_LIMIT + 1), dict(limit=True), dict(since=t(1), until=T0),
                dict(kinds=("screenshot",)), dict(kinds=tuple(ArtifactKind) * 3), dict(cursor="nope"),
                dict(since=datetime(2026, 1, 1)), dict(context_id="ctx")):
        with pytest.raises(ArtifactError):
            ArtifactQuery(**bad)
    assert decode_artifact_cursor(f"2026-10-01T09:00:00.000000+00:00|{AID}") == (
        "2026-10-01T09:00:00.000000+00:00", AID)


# ------------------------------------------------------------------ ledger d'activité


def test_activity_draft_requires_session_for_session_context_capture_families():
    with pytest.raises(ActivityError):
        ActivityDraft(kind=ActivityKind.CONTEXT_CREATED, occurred_at=T0, jarvis_session_id=SID)
    with pytest.raises(ActivityError):
        ActivityDraft(kind=ActivityKind.CAPTURE_STARTED, occurred_at=T0)
    with pytest.raises(ActivityError):
        ActivityDraft(kind=ActivityKind.ARTIFACT_CREATED, occurred_at=T0, context_id=CID)
    event = ActivityDraft(kind=ActivityKind.ARTIFACT_CREATED, occurred_at=T0, artifact_ids=(AID,))
    assert event.event_id.startswith("jact_") and event.jarvis_session_id is None


def test_activity_data_is_small_and_flat_never_media_or_long_text():
    with pytest.raises(ActivityError):
        ActivityDraft(kind=ActivityKind.CAPTURE_GAP, occurred_at=T0, jarvis_session_id=SID,
                      data={"text": "x" * 257})
    with pytest.raises(ActivityError):
        ActivityDraft(kind=ActivityKind.CAPTURE_GAP, occurred_at=T0, jarvis_session_id=SID, data={"pcm": b"\x00"})
    with pytest.raises(ActivityError):
        ActivityDraft(kind=ActivityKind.CAPTURE_GAP, occurred_at=T0, jarvis_session_id=SID,
                      data={f"k{i}": i for i in range(17)})
    with pytest.raises(ActivityError):
        ActivityDraft(kind=ActivityKind.ARTIFACT_CREATED, occurred_at=T0,
                      artifact_ids=tuple(f"jart_{i}" for i in range(17)))
    with pytest.raises(ActivityError):
        ActivityDraft(kind=ActivityKind.ARTIFACT_CREATED, occurred_at=T0, artifact_ids=(AID, AID))
    with pytest.raises(ActivityError):
        ActivityDraft(kind=ActivityKind.CAPTURE_GAP, occurred_at=T0, jarvis_session_id=SID, capture_ids=("a b",))


def test_activity_event_codec_round_trips_and_is_strict():
    draft = ActivityDraft(kind=ActivityKind.CAPTURE_GAP, occurred_at=T0, jarvis_session_id=SID, context_id=CID,
                          capture_ids=("jcap_1",), artifact_ids=(AID,), data={"lost_ms": 250})
    event = ActivityEvent(seq=3, draft=draft)
    assert event.kind is ActivityKind.CAPTURE_GAP and event.context_id == CID
    assert ActivityEvent.from_payload(event.to_payload()) == event
    for broken in ({**event.to_payload(), "seq": 0}, {**event.to_payload(), "kind": "capture.lost"},
                   {**event.to_payload(), "x": 1}, {**event.to_payload(), "artifact_ids": AID}):
        with pytest.raises(ActivityError):
            ActivityEvent.from_payload(broken)


def test_activity_query_bounds():
    ActivityQuery(after_seq=10, limit=MAX_ACTIVITY_LIMIT, kinds=(ActivityKind.CONTEXT_CREATED,))
    for bad in (dict(limit=0), dict(limit=MAX_ACTIVITY_LIMIT + 1), dict(after_seq=-1), dict(after_seq=1.5),
                dict(kinds=("context.created",)), dict(since=t(2), until=t(1))):
        with pytest.raises(ActivityError):
            ActivityQuery(**bad)


def test_context_transition_events_follow_the_write_order():
    session = open_session(default_board(now=T0), now=T0, jarvis_session_id=SID)
    first = create_context(session, (), now=t(1))
    second = create_context(session, first.contexts, now=t(2))
    events = context_transition_events(second, now=t(2), origin="protocol", created=True)
    assert [e.kind for e in events] == [ActivityKind.CONTEXT_DORMANT, ActivityKind.CONTEXT_CREATED]
    assert [e.context_id for e in events] == [first.active.context_id, second.active.context_id]
    back = activate_context(session, second.contexts, first.active.context_id, now=t(3))
    assert [e.kind for e in context_transition_events(back, now=t(3), origin="p", created=False)] == [
        ActivityKind.CONTEXT_DORMANT, ActivityKind.CONTEXT_ACTIVATED]
    same = activate_context(session, back.contexts, first.active.context_id, now=t(4))
    assert context_transition_events(same, now=t(4), origin="p", created=False) == ()
    with pytest.raises(ActivityError):
        session_event(ActivityKind.CONTEXT_CREATED, SID, now=T0, origin="x")
