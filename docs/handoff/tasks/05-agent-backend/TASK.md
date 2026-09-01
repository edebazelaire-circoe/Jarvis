# Task 05 - Implement AgentBackend and minimal tool registry

## Goal

Connecter un premier cerveau OpenAI a Jarvis sans coupler le domaine au provider.

## Context

La V1 doit repondre a des turns et proposer uniquement un petit ensemble d'outils metier securises.

## Scope
### In Scope
- Charger `/caveman` et `/coding-guideline`.
- OpenAIAgentBackend.
- Configurable model.
- Streaming if stable/current API supports it cleanly; otherwise typed non-streaming first.
- Tool registry with `memory_search`, `memory_append`, `board_present` contracts.
- No direct tool execution inside provider adapter.

### Out of Scope
- Shell.
- Gmail/calendar/browser.
- General filesystem tools.
- Multi-agent orchestration.

## Dependencies

Task 02 complete. Task 04 useful for live voice test but not required for core adapter unit tests.

## Implementation Steps

1. Implement AgentBackend using current official OpenAI API/SDK.
2. Translate domain turns to provider request.
3. Translate tool requests back to domain ActionRequest/ToolCall.
4. Keep execution in core/tool dispatcher, not adapter.
5. Add system instructions for concise spoken responses.
6. Add fake and provider-mocked tests.

## Files Likely Touched

- `jarvis/adapters/openai_agent.py`
- `jarvis/core/orchestrator.py`
- `jarvis/domain/actions.py`
- `jarvis/core/tools.py`
- `tests/unit/test_agent_adapter.py`

## Architecture Constraints

The provider may request actions but never executes mutations directly. No provider-specific tool-call object crosses into core.

## Testing Requirements

- Provider response mapping tests.
- Tool-call mapping tests.
- Unknown tool denied.
- Prompt injection text cannot register a new tool.

## Acceptance Criteria

- Normal text response works.
- The three V1 tool schemas are exposed.
- Unknown/general commands are impossible through registry.
- Core stays provider-independent.

## Documentation Updates

Document selected provider API surface and model config.

## Handoff Notes

Prioritize stable behavior over sophisticated agent frameworks for V1.
