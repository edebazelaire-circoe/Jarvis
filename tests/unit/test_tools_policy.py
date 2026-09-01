from __future__ import annotations

import pytest

from jarvis.core.tools import ToolRegistry
from jarvis.domain.actions import ActionKind, RiskLevel
from jarvis.domain.errors import ActionPolicyError
from jarvis.domain.messages import ToolCall


def test_registry_contains_only_v1_tools():
    registry = ToolRegistry()
    assert {d.name for d in registry.definitions()} == {
        "memory_search", "memory_append", "board_present"
    }


def test_unknown_or_shell_tool_denied():
    registry = ToolRegistry()
    for name in ("shell", "bash", "delete_file", "totally_new_tool"):
        with pytest.raises(ActionPolicyError):
            registry.to_action(ToolCall("c1", name, {}))


def test_memory_append_is_locked_write_with_confirmation():
    action = ToolRegistry().to_action(
        ToolCall("c1", "memory_append", {"title": "Fact", "body": "Value"})
    )
    assert action.kind == ActionKind.MEMORY_APPEND
    assert action.risk == RiskLevel.WRITE
    assert action.requires_confirmation is True


def test_board_is_ephemeral_without_confirmation():
    action = ToolRegistry().to_action(
        ToolCall("c1", "board_present", {"title": "Card", "body": "Hello", "x": 0.2})
    )
    assert action.kind == ActionKind.BOARD_PRESENT
    assert action.risk == RiskLevel.EPHEMERAL
    assert action.requires_confirmation is False
    assert action.payload["x"] == pytest.approx(0.2)


@pytest.mark.parametrize(
    "call",
    [
        ToolCall("c1", "memory_search", {"query": "x", "limit": 0}),
        ToolCall("c1", "memory_search", {"query": "x", "extra": 1}),
        ToolCall("c1", "memory_append", {"title": "", "body": "b"}),
        ToolCall("c1", "board_present", {"title": "x", "body": "b", "x": 2}),
    ],
)
def test_tool_arguments_are_validated(call):
    with pytest.raises(ActionPolicyError):
        ToolRegistry().to_action(call)
