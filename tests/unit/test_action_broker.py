from __future__ import annotations

import pytest

from jarvis.core.actions import ActionBroker
from jarvis.domain.actions import ActionKind, ActionRequest, ActionStatus, RiskLevel


@pytest.mark.asyncio
async def test_write_never_executes_before_explicit_confirmation():
    calls = []

    async def execute(action):
        calls.append(action.action_id)
        return {"ok": True}

    broker = ActionBroker({ActionKind.MEMORY_APPEND: execute}, confirmation_timeout_s=10)
    action = ActionRequest(
        ActionKind.MEMORY_APPEND,
        "memoriser X",
        RiskLevel.WRITE,
        {"title": "X", "body": "Y"},
        True,
    )
    result = await broker.request(action, turn_id="t1")
    assert result.status == ActionStatus.PENDING
    assert calls == []

    ambiguous = await broker.resolve_confirmation("peut-être", action_id=action.action_id)
    assert ambiguous.status == ActionStatus.PENDING
    assert calls == []

    approved = await broker.resolve_confirmation("Oui !", action_id=action.action_id)
    assert approved.status == ActionStatus.EXECUTED
    assert calls == [action.action_id]


@pytest.mark.asyncio
async def test_denial_and_stale_ids_do_not_execute():
    calls = []

    async def execute(action):
        calls.append(action.action_id)

    broker = ActionBroker({ActionKind.MEMORY_APPEND: execute})
    action = ActionRequest(ActionKind.MEMORY_APPEND, "write", RiskLevel.WRITE, {}, True)
    await broker.request(action, turn_id="t1")
    stale = await broker.resolve_confirmation("oui", action_id="other")
    assert stale.status == ActionStatus.REJECTED
    assert broker.pending is not None
    denied = await broker.resolve_confirmation("non", action_id=action.action_id)
    assert denied.status == ActionStatus.DENIED
    assert calls == []


@pytest.mark.asyncio
async def test_confirmation_expiry_is_terminal_and_safe():
    now = [100.0]

    async def execute(action):
        raise AssertionError("must not execute")

    broker = ActionBroker(
        {ActionKind.MEMORY_APPEND: execute},
        confirmation_timeout_s=5,
        clock=lambda: now[0],
    )
    action = ActionRequest(ActionKind.MEMORY_APPEND, "write", RiskLevel.WRITE, {}, True)
    await broker.request(action, turn_id="t1")
    now[0] = 106
    result = await broker.resolve_confirmation("oui", action_id=action.action_id)
    assert result.status == ActionStatus.EXPIRED
    assert broker.pending is None


@pytest.mark.asyncio
async def test_policy_flags_cannot_be_downgraded_by_caller():
    broker = ActionBroker({ActionKind.MEMORY_APPEND: lambda action: None})
    forged = ActionRequest(
        ActionKind.MEMORY_APPEND,
        "write without confirm",
        RiskLevel.EPHEMERAL,
        {},
        False,
    )
    result = await broker.request(forged, turn_id="t")
    assert result.status == ActionStatus.REJECTED

@pytest.mark.asyncio
async def test_words_containing_yes_are_not_approval():
    calls = []

    async def execute(action):
        calls.append(action.action_id)

    broker = ActionBroker({ActionKind.MEMORY_APPEND: execute})
    action = ActionRequest(ActionKind.MEMORY_APPEND, "write", RiskLevel.WRITE, {}, True)
    await broker.request(action, turn_id="t")
    for phrase in ("yesterday", "oui mais non", "j'aimerais peut-être"):
        result = await broker.resolve_confirmation(phrase, action_id=action.action_id)
        assert result.status == ActionStatus.PENDING
    assert calls == []

@pytest.mark.asyncio
@pytest.mark.parametrize("phrase", ["ok", "confirme", "je confirme", "y", "annule"])
async def test_only_exact_yes_or_no_vocabulary_is_terminal(phrase):
    async def execute(action):
        return {"ok": True}

    broker = ActionBroker({ActionKind.MEMORY_APPEND: execute})
    action = ActionRequest(ActionKind.MEMORY_APPEND, "write", RiskLevel.WRITE, {}, True)
    await broker.request(action, turn_id="t")
    result = await broker.resolve_confirmation(phrase, action_id=action.action_id)
    assert result.status == ActionStatus.PENDING
    assert broker.pending is not None
