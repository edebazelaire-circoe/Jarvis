"""Contrat pur du Context de Session (handoff session-context-recording, Slice 01).

Domaine pur : rien n'est persisté, servi ni affiché ici. Voir `docs/session-context.md`.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
import json
from pathlib import PurePosixPath

import pytest

from jarvis.domain.session_context import (
    CONTEXT_ID_PREFIX, HTTP_STATUS, MAX_SOURCE_CONTEXTS, ContextOrigin, ContextStatus, SessionContext,
    SessionContextError, SessionContextErrorCode, activate_context, adopt_context, check_contexts,
    context_workspace_path, create_context, dormant_contexts_of_closed_session, ensure_active, new_context_id,
    touch_context,
)
from jarvis.domain.workspace_board import (
    MAX_RUNTIME_METADATA_KEYS, MAX_TITLE_CHARS, SessionEndReason, close_session, default_board, open_session,
)

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
SID = "jsess_0123abcd"


def t(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def code_of(excinfo: pytest.ExceptionInfo[SessionContextError]) -> str:
    return excinfo.value.code.value


@pytest.fixture
def session():
    return open_session(default_board(now=T0), now=T0, jarvis_session_id=SID)


def ctx(context_id: str = "jctx_a", **kwargs) -> SessionContext:
    base = {"context_id": context_id, "jarvis_session_id": SID, "created_at": T0, "activated_at": T0,
            "last_active_at": T0}
    return SessionContext(**{**base, **kwargs})


# ---------------------------------------------------------------- codes et identifiants


def test_error_codes_are_stable_and_all_mapped_to_http():
    assert {c.value for c in SessionContextErrorCode} == {
        "invalid_context", "context_not_found", "context_conflict", "context_dormant", "session_closed"}
    assert set(HTTP_STATUS) == set(SessionContextErrorCode)
    assert {c.value: HTTP_STATUS[c] for c in SessionContextErrorCode} == {
        "invalid_context": 400, "context_not_found": 404, "context_conflict": 409, "context_dormant": 409,
        "session_closed": 409}
    err = SessionContextError(SessionContextErrorCode.CONTEXT_DORMANT, "x")
    assert isinstance(err, ValueError) and err.code == "context_dormant" and err.status == 409


def test_new_ids_are_prefixed_unique_and_valid():
    a, b = new_context_id(), new_context_id()
    assert a.startswith(CONTEXT_ID_PREFIX) and a != b
    assert ctx(a).context_id == a


def test_status_and_origin_wire_values_are_stable():
    assert [s.value for s in ContextStatus] == ["active", "dormant"]
    assert [o.value for o in ContextOrigin] == ["created", "adopted"]


def test_the_value_has_no_board_key():
    """D06 : un Context est indexé par la Session, jamais par un Board."""

    assert not any("board" in f.name for f in dataclasses.fields(SessionContext))
    assert not any("board" in key for key in ctx().to_payload())


# ---------------------------------------------------------------- validation et bornes


@pytest.mark.parametrize("kwargs", [
    {"context_id": "ctx_1"},  # mauvais préfixe
    {"context_id": "jctx_"},  # préfixe seul
    {"context_id": "jctx_../x"},
    {"context_id": "jctx_a.b"},
    {"context_id": "jctx_a b"},
    {"context_id": "jctx_" + "a" * 124},  # > 128
    {"context_id": 7},
    {"jarvis_session_id": "jsess_a/../b"},
    {"jarvis_session_id": "board_x"},
    {"created_at": datetime(2026, 10, 1)},  # naïf
    {"activated_at": T0 - timedelta(seconds=1)},  # avant created_at
    {"last_active_at": T0 - timedelta(seconds=1)},
    {"status": "active"},  # chaîne, pas l'énum
    {"origin": "created"},
    {"title": ""},
    {"title": " padded "},
    {"title": "deux\nlignes"},
    {"title": "x" * (MAX_TITLE_CHARS + 1)},
    {"title": 3},
    {"source_context_ids": ["jctx_b"]},  # liste, pas tuple
    {"source_context_ids": ("jctx_b", "jctx_b")},
    {"source_context_ids": ("jctx_a",)},  # lui-même
    {"source_context_ids": ("../jctx_b",)},
    {"source_context_ids": tuple(f"jctx_{i}" for i in range(MAX_SOURCE_CONTEXTS + 1))},
    {"runtime_metadata": []},
    {"runtime_metadata": {f"k{i}": i for i in range(MAX_RUNTIME_METADATA_KEYS + 1)}},
    {"runtime_metadata": {"bad key": 1}},
    {"runtime_metadata": {"k": {"nested": 1}}},
    {"runtime_metadata": {"k": "x" * 257}},
])
def test_invalid_contexts_are_refused(kwargs):
    with pytest.raises(SessionContextError) as exc:
        ctx(**kwargs)
    assert code_of(exc) == "invalid_context"


def test_bounds_are_inclusive_and_metadata_is_frozen():
    meta = {"agent_cli": "claude", "n": 2, "flag": True, "none": None}
    value = ctx(title="x" * MAX_TITLE_CHARS, source_context_ids=tuple(f"jctx_{i}" for i in range(MAX_SOURCE_CONTEXTS)),
                runtime_metadata=meta)
    meta["agent_cli"] = "codex"
    assert value.runtime_metadata["agent_cli"] == "claude"
    with pytest.raises(TypeError):
        value.runtime_metadata["x"] = 1  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        value.status = ContextStatus.DORMANT  # type: ignore[misc]


# ---------------------------------------------------------------- chemin dérivé


def test_workspace_path_is_derived_relative_and_posix():
    path = context_workspace_path(SID, "jctx_a")
    assert path == PurePosixPath("sessions", SID, "contexts", "jctx_a")
    assert str(path) == f"sessions/{SID}/contexts/jctx_a" and not path.is_absolute()
    assert ctx().workspace_path == path


@pytest.mark.parametrize("session_id, context_id", [
    ("jsess_..", "jctx_a"), (SID, "jctx_.."), ("..", "jctx_a"), (SID, "../jctx_a"), (SID, "jctx_a/../../x"),
    (SID, "jctx_a\\b"), ("jsess_C:", "jctx_a"), ("/abs", "jctx_a"), (SID, ""), (SID, None), (SID, "jctx_a\x00"),
    (SID, "board_x"), ("jsess_a", "jctx_é"),
])
def test_workspace_path_rejects_anything_that_is_not_a_valid_id(session_id, context_id):
    with pytest.raises(SessionContextError) as exc:
        context_workspace_path(session_id, context_id)
    assert code_of(exc) == "invalid_context"


# ---------------------------------------------------------------- transitions


def test_create_in_an_empty_open_session_makes_it_active(session):
    tr = create_context(session, (), now=t(1), title="  Recherche  ", source_context_ids=["jctx_old"])
    c = tr.active
    assert (c.status, c.origin, c.title, c.source_context_ids) == (
        ContextStatus.ACTIVE, ContextOrigin.CREATED, "Recherche", ("jctx_old",))
    assert (c.created_at, c.activated_at, c.last_active_at) == (t(1), t(1), t(1))
    assert tr.dormanted is None and tr.contexts == (c,) and tr.changed == (c,)
    assert c.jarvis_session_id == session.jarvis_session_id
    assert create_context(session, (), now=t(1), title="   ").active.title is None


def test_create_dormants_the_previous_active_in_the_same_result(session):
    first = create_context(session, (), now=t(1)).active
    tr = create_context(session, (first,), now=t(5), title="B")
    assert tr.dormanted == dataclasses.replace(first, status=ContextStatus.DORMANT, last_active_at=t(5))
    assert tr.contexts == (tr.dormanted, tr.active) and tr.changed == (tr.dormanted, tr.active)
    assert [c.status for c in tr.contexts] == [ContextStatus.DORMANT, ContextStatus.ACTIVE]
    check_contexts(session, tr.contexts)
    assert first.is_active  # valeurs immuables : l'original ne bouge pas


def test_reactivating_a_dormant_context_is_explicit_and_atomic(session):
    a = create_context(session, (), now=t(1)).active
    tr = create_context(session, (a,), now=t(2))
    back = activate_context(session, tr.contexts, a.context_id, now=t(3))
    assert back.active.context_id == a.context_id and back.active.is_active
    assert (back.active.created_at, back.active.activated_at, back.active.last_active_at) == (t(1), t(3), t(3))
    assert back.dormanted.context_id == tr.active.context_id and back.dormanted.last_active_at == t(3)
    assert [c.context_id for c in back.contexts] == [a.context_id, tr.active.context_id]  # ordre reçu
    assert back.changed == (back.dormanted, back.active)  # l'ancien actif s'endort, puis la réactivation
    check_contexts(session, back.contexts)


def test_activating_the_active_context_changes_nothing(session):
    tr = create_context(session, (), now=t(1))
    same = activate_context(session, tr.contexts, tr.active.context_id, now=t(9))
    assert same.active is tr.active and same.changed == () and same.dormanted is None


def test_activating_an_unknown_context_is_not_found_and_a_bad_id_is_invalid(session):
    tr = create_context(session, (), now=t(1))
    with pytest.raises(SessionContextError) as exc:
        activate_context(session, tr.contexts, "jctx_missing", now=t(2))
    assert code_of(exc) == "context_not_found"
    with pytest.raises(SessionContextError) as exc:
        activate_context(session, tr.contexts, "../etc", now=t(2))
    assert code_of(exc) == "invalid_context"


def test_exactly_one_active_context_per_open_session_holds_across_any_sequence(session):
    contexts: tuple[SessionContext, ...] = ()
    ids = []
    for minute in range(1, 6):
        tr = create_context(session, contexts, now=t(minute))
        contexts, ids = tr.contexts, [*ids, tr.active.context_id]
        assert sum(c.is_active for c in contexts) == 1
    for minute, target in enumerate((ids[0], ids[3], ids[0], ids[4]), start=10):
        contexts = activate_context(session, contexts, target, now=t(minute)).contexts
        assert [c.context_id for c in contexts if c.is_active] == [target]


def test_check_contexts_refuses_broken_sets(session):
    a = ctx("jctx_a")
    b = ctx("jctx_b")
    for broken, code in (
        ((a, b), "context_conflict"),  # deux actifs
        ((a, a), "context_conflict"),  # id répété
        ((ctx("jctx_c", jarvis_session_id="jsess_other"),), "context_conflict"),  # autre Session
        ((ctx("jctx_d", status=ContextStatus.DORMANT),), "context_conflict"),  # Session ouverte sans actif
        (("jctx_a",), "invalid_context"),
    ):
        with pytest.raises(SessionContextError) as exc:
            check_contexts(session, broken)  # type: ignore[arg-type]
        assert code_of(exc) == code
    assert check_contexts(session, ()) == ()  # pas encore adoptée
    for action in (lambda: create_context(session, (a, b), now=t(1)),
                   lambda: activate_context(session, (a, b), "jctx_a", now=t(1))):
        with pytest.raises(SessionContextError) as exc:
            action()
        assert code_of(exc) == "context_conflict"


def test_create_refuses_a_duplicate_id_and_a_string_as_sources(session):
    a = create_context(session, (), now=t(1), context_id="jctx_a")
    with pytest.raises(SessionContextError) as exc:
        create_context(session, a.contexts, now=t(2), context_id="jctx_a")
    assert code_of(exc) == "context_conflict"
    with pytest.raises(SessionContextError) as exc:
        create_context(session, a.contexts, now=t(2), source_context_ids="jctx_a")  # type: ignore[arg-type]
    assert code_of(exc) == "invalid_context"


def test_a_backwards_clock_is_refused_instead_of_clamped(session):
    a = create_context(session, (), now=t(5))
    b = create_context(session, a.contexts, now=t(6))
    for action in (lambda: create_context(session, b.contexts, now=t(4)),
                   lambda: activate_context(session, b.contexts, a.active.context_id, now=t(5))):
        with pytest.raises(SessionContextError) as exc:
            action()
        assert code_of(exc) == "invalid_context"


def test_nothing_is_created_or_activated_in_a_closed_session(session):
    tr = create_context(session, (), now=t(1))
    closed = close_session(session, reason=SessionEndReason.NEW_SESSION, now=t(2))
    dormant = dormant_contexts_of_closed_session(closed, tr.contexts, now=t(2))
    for action in (
        lambda: create_context(closed, dormant, now=t(3)),
        lambda: activate_context(closed, dormant, tr.active.context_id, now=t(3)),
        lambda: adopt_context(closed, (), now=t(3)),
    ):
        with pytest.raises(SessionContextError) as exc:
            action()
        assert code_of(exc) == "session_closed"


def test_closing_a_session_dormants_its_active_context(session):
    a = create_context(session, (), now=t(1))
    b = create_context(session, a.contexts, now=t(2))
    closed = close_session(session, reason=SessionEndReason.NEW_SESSION, now=t(4))
    with pytest.raises(SessionContextError) as exc:
        check_contexts(closed, b.contexts)  # Session close avec un actif : incohérent
    assert code_of(exc) == "context_conflict"
    (slept,) = dormant_contexts_of_closed_session(closed, b.contexts, now=t(4))
    assert slept.context_id == b.active.context_id and not slept.is_active and slept.last_active_at == t(4)
    check_contexts(closed, (b.dormanted, slept))
    with pytest.raises(SessionContextError) as exc:
        dormant_contexts_of_closed_session(session, b.contexts, now=t(4))  # encore ouverte
    assert code_of(exc) == "invalid_context"
    with pytest.raises(SessionContextError) as exc:
        dormant_contexts_of_closed_session(closed, (ctx("jctx_z", jarvis_session_id="jsess_other"),), now=t(4))
    assert code_of(exc) == "context_conflict"


def test_adoption_gives_a_legacy_session_one_adopted_context_once(session):
    tr = adopt_context(session, (), now=t(1))
    assert tr.active.origin is ContextOrigin.ADOPTED and tr.active.is_active and tr.contexts == (tr.active,)
    assert tr.active.source_context_ids == () and tr.active.title is None  # aucun historique fabriqué
    with pytest.raises(SessionContextError) as exc:
        adopt_context(session, tr.contexts, now=t(2))
    assert code_of(exc) == "context_conflict"


def test_a_dormant_context_is_not_an_implicit_write_target(session):
    a = create_context(session, (), now=t(1))
    b = create_context(session, a.contexts, now=t(2))
    with pytest.raises(SessionContextError) as exc:
        ensure_active(b.dormanted)
    assert code_of(exc) == "context_dormant"
    with pytest.raises(SessionContextError) as exc:
        touch_context(b.dormanted, now=t(3))
    assert code_of(exc) == "context_dormant"
    ensure_active(b.active)
    assert touch_context(b.active, now=t(3)).last_active_at == t(3)
    assert touch_context(b.active, now=t(1)).last_active_at == t(2)  # jamais en arrière


# ---------------------------------------------------------------- sérialisation


def test_payload_round_trip_through_json(session):
    a = create_context(session, (), now=t(1))
    b = create_context(session, a.contexts, now=t(2), title="Réunion", source_context_ids=[a.active.context_id],
                       runtime_metadata={"agent_cli": "claude", "n": 1, "flag": False, "none": None})
    for value in b.contexts:
        assert SessionContext.from_payload(value.to_payload()) == value
        assert SessionContext.from_payload(json.loads(json.dumps(value.to_payload()))) == value
    assert set(b.active.to_payload()) == {
        "context_id", "jarvis_session_id", "status", "origin", "created_at", "activated_at", "last_active_at",
        "title", "source_context_ids", "runtime_metadata"}


def test_optional_fields_default_when_absent():
    payload = ctx().to_payload()
    for key in ("title", "source_context_ids", "runtime_metadata"):
        del payload[key]
    assert SessionContext.from_payload(payload) == ctx()


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(extra=1),
    lambda p: p.update(board_id="default"),
    lambda p: p.pop("status"),
    lambda p: p.pop("activated_at"),
    lambda p: p.update(status="closed"),
    lambda p: p.update(status="ACTIVE"),
    lambda p: p.update(origin="imported"),
    lambda p: p.update(created_at="hier"),
    lambda p: p.update(created_at=1_700_000_000),
    lambda p: p.update(created_at="2026-10-01T09:00:00"),  # naïf
    lambda p: p.update(source_context_ids="jctx_b"),
    lambda p: p.update(source_context_ids=[3]),
    lambda p: p.update(runtime_metadata=[["k", 1]]),
    lambda p: p.update(context_id="jctx_../../x"),
    lambda p: p.update(workspace_path="/etc"),  # le chemin n'est jamais une entrée
])
def test_malformed_payloads_are_refused(mutate):
    payload = ctx().to_payload()
    mutate(payload)
    with pytest.raises(SessionContextError) as exc:
        SessionContext.from_payload(payload)
    assert code_of(exc) == "invalid_context"


@pytest.mark.parametrize("payload", [None, [], "x", 1])
def test_non_object_payloads_are_refused(payload):
    with pytest.raises(SessionContextError) as exc:
        SessionContext.from_payload(payload)
    assert code_of(exc) == "invalid_context"
