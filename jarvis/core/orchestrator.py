from __future__ import annotations

from dataclasses import dataclass
import time
import uuid

from jarvis.core.actions import ActionBroker
from jarvis.core.session import SessionStateMachine
from jarvis.core.tools import ToolRegistry
from jarvis.diagnostics.logger import PrivacyLogger
from jarvis.domain.actions import ActionStatus
from jarvis.domain.errors import ActionPolicyError, AudioDeviceError, ProviderError
from jarvis.domain.events import JarvisState
from jarvis.domain.messages import CancellationToken, ToolCall, ToolOutput, UserTurn
from jarvis.domain.results import AgentResult, TurnOutcome
from jarvis.ports.agent import AgentBackend
from jarvis.ports.tts import TTSBackend


@dataclass(slots=True)
class _PendingAgentFlow:
    action_id: str
    continuation_token: str | None
    call: ToolCall
    prior_outputs: tuple[ToolOutput, ...]
    remaining_calls: tuple[ToolCall, ...]
    original_turn_id: str
    tool_round: int


class JarvisOrchestrator:
    def __init__(
        self,
        *,
        agent: AgentBackend,
        tts: TTSBackend,
        state: SessionStateMachine,
        tools: ToolRegistry,
        broker: ActionBroker,
        logger: PrivacyLogger | None = None,
        max_tool_rounds: int = 6,
    ) -> None:
        self.agent = agent
        self.tts = tts
        self.state = state
        self.tools = tools
        self.broker = broker
        self.logger = logger
        self.max_tool_rounds = max_tool_rounds
        self._pending_flow: _PendingAgentFlow | None = None
        self._speech_token: CancellationToken | None = None

    @property
    def awaiting_confirmation(self) -> bool:
        return self._pending_flow is not None and self.broker.pending is not None

    async def handle_text(self, text: str, *, turn_id: str | None = None) -> TurnOutcome:
        turn_id = turn_id or uuid.uuid4().hex
        started = time.perf_counter()
        if self.logger:
            self.logger.event("turn.received", turn_id=turn_id, text=text)
        try:
            if self._pending_flow is not None:
                outcome = await self._handle_confirmation(text, turn_id=turn_id)
            else:
                await self._enter_thinking(turn_id)
                result = await self.agent.respond(UserTurn(turn_id=turn_id, text=text), self.tools)
                outcome = await self._handle_agent_result(result, turn_id=turn_id, tool_round=0)
            if self.logger:
                self.logger.event(
                    "turn.completed",
                    turn_id=turn_id,
                    total_ms=int((time.perf_counter() - started) * 1000),
                    awaiting_confirmation=outcome.awaiting_confirmation,
                )
            return outcome
        except Exception as exc:
            if self.logger:
                self.logger.event("turn.failed", turn_id=turn_id, error_class=type(exc).__name__)
            return await self.handle_runtime_error(exc, turn_id=turn_id, context="agent")

    async def handle_runtime_error(
        self,
        exc: Exception,
        *,
        turn_id: str | None = None,
        context: str = "runtime",
    ) -> TurnOutcome:
        """Surface an expected runtime failure without leaking provider internals.

        Voice capture/transcription failures happen before ``handle_text`` owns the
        turn, so the runtime needs a public, state-safe path that applies the same
        visible + spoken error contract as agent failures.
        """
        turn_id = turn_id or uuid.uuid4().hex
        error_text = self._public_error_text(exc, context=context)
        if self.logger:
            self.logger.event(
                "runtime.failed",
                turn_id=turn_id,
                context=context,
                error_class=type(exc).__name__,
            )
        await self._announce_error(error_text, turn_id=turn_id, error_class=type(exc).__name__)
        return TurnOutcome(
            turn_id=turn_id,
            text=error_text,
            diagnostics={"error_class": type(exc).__name__, "context": context},
        )

    @staticmethod
    def _public_error_text(exc: Exception, *, context: str) -> str:
        if isinstance(exc, ProviderError):
            if context == "transcription" or exc.operation == "transcription":
                return "Je n'arrive pas a transcrire ta voix pour le moment. Reessaie dans un instant."
            if context == "tts" or exc.operation in {"speech", "tts"}:
                return "Je n'arrive pas a utiliser la synthese vocale pour le moment."
            return "Je n'arrive pas a joindre le service d'IA pour le moment. Reessaie dans un instant."
        if isinstance(exc, AudioDeviceError):
            return "Je n'arrive pas a utiliser le peripherique audio. Verifie le micro ou les haut-parleurs."
        return "Je n'ai pas pu terminer cette demande. Reessaie dans un instant."

    async def begin_listening(self, *, turn_id: str | None = None) -> bool:
        if self.state.state in {JarvisState.SPEAKING, JarvisState.ERROR} and self._speech_token:
            self._speech_token.cancel()
            await self.state.transition(JarvisState.LISTENING, turn_id=turn_id)
            return True
        if self.state.state in {JarvisState.IDLE, JarvisState.AWAITING_CONFIRMATION}:
            await self.state.transition(JarvisState.LISTENING, turn_id=turn_id)
            return True
        return False

    async def begin_transcribing(self, *, turn_id: str | None = None) -> None:
        await self.state.transition(JarvisState.TRANSCRIBING, turn_id=turn_id)

    async def _enter_thinking(self, turn_id: str) -> None:
        if self.state.state in {JarvisState.IDLE, JarvisState.TRANSCRIBING, JarvisState.AWAITING_CONFIRMATION}:
            await self.state.transition(JarvisState.THINKING, turn_id=turn_id)
        elif self.state.state != JarvisState.THINKING:
            raise RuntimeError(f"Cannot think from {self.state.state.value}")

    async def _handle_agent_result(self, result: AgentResult, *, turn_id: str, tool_round: int) -> TurnOutcome:
        if tool_round > self.max_tool_rounds:
            return await self._finalize_text("J'ai interrompu une boucle d'outils trop longue.", turn_id=turn_id)
        if result.tool_calls:
            return await self._process_tool_calls(
                calls=result.tool_calls,
                continuation_token=result.continuation_token,
                turn_id=turn_id,
                tool_round=tool_round,
                prior_outputs=(),
            )
        text = result.text.strip() or "D'accord."
        return await self._finalize_text(text, turn_id=turn_id)

    async def _process_tool_calls(
        self,
        *,
        calls: tuple[ToolCall, ...],
        continuation_token: str | None,
        turn_id: str,
        tool_round: int,
        prior_outputs: tuple[ToolOutput, ...],
    ) -> TurnOutcome:
        outputs = list(prior_outputs)
        for index, call in enumerate(calls):
            try:
                action = self.tools.to_action(call)
                action_result = await self.broker.request(action, turn_id=turn_id)
            except ActionPolicyError as exc:
                outputs.append(ToolOutput(call.call_id, call.name, {"error": str(exc)}, True))
                continue

            if action_result.status == ActionStatus.PENDING:
                self._pending_flow = _PendingAgentFlow(
                    action_id=action_result.action_id,
                    continuation_token=continuation_token,
                    call=call,
                    prior_outputs=tuple(outputs),
                    remaining_calls=tuple(calls[index + 1 :]),
                    original_turn_id=turn_id,
                    tool_round=tool_round,
                )
                await self.state.transition(
                    JarvisState.AWAITING_CONFIRMATION,
                    turn_id=turn_id,
                    message=action_result.message,
                )
                await self._speak(action_result.message, turn_id=turn_id, after=JarvisState.AWAITING_CONFIRMATION)
                return TurnOutcome(
                    turn_id=turn_id,
                    text=action_result.message,
                    awaiting_confirmation=True,
                    action_id=action_result.action_id,
                )

            outputs.append(
                ToolOutput(
                    call_id=call.call_id,
                    name=call.name,
                    output={"status": action_result.status.value, "message": action_result.message, "output": action_result.output},
                    is_error=action_result.status != ActionStatus.EXECUTED,
                )
            )

        if continuation_token:
            await self._enter_thinking(turn_id)
            result = await self.agent.respond(
                UserTurn(
                    turn_id=turn_id,
                    continuation_token=continuation_token,
                    tool_outputs=tuple(outputs),
                ),
                self.tools,
            )
            return await self._handle_agent_result(result, turn_id=turn_id, tool_round=tool_round + 1)
        return await self._finalize_text("Action terminee.", turn_id=turn_id)

    async def _handle_confirmation(self, text: str, *, turn_id: str) -> TurnOutcome:
        flow = self._pending_flow
        if flow is None:
            await self._enter_thinking(turn_id)
            return await self._finalize_text("Aucune confirmation n'est en attente.", turn_id=turn_id)
        await self._enter_thinking(turn_id)
        result = await self.broker.resolve_confirmation(text, action_id=flow.action_id)
        if result.status == ActionStatus.PENDING:
            await self.state.transition(JarvisState.AWAITING_CONFIRMATION, turn_id=turn_id, message=result.message)
            await self._speak(result.message, turn_id=turn_id, after=JarvisState.AWAITING_CONFIRMATION)
            return TurnOutcome(turn_id, result.message, True, flow.action_id)

        self._pending_flow = None
        pending_output = ToolOutput(
            call_id=flow.call.call_id,
            name=flow.call.name,
            output={"status": result.status.value, "message": result.message, "output": result.output},
            is_error=result.status != ActionStatus.EXECUTED,
        )
        prior = flow.prior_outputs + (pending_output,)
        if flow.remaining_calls:
            return await self._process_tool_calls(
                calls=flow.remaining_calls,
                continuation_token=flow.continuation_token,
                turn_id=turn_id,
                tool_round=flow.tool_round,
                prior_outputs=prior,
            )
        if flow.continuation_token:
            agent_result = await self.agent.respond(
                UserTurn(
                    turn_id=turn_id,
                    continuation_token=flow.continuation_token,
                    tool_outputs=prior,
                ),
                self.tools,
            )
            return await self._handle_agent_result(agent_result, turn_id=turn_id, tool_round=flow.tool_round + 1)
        return await self._finalize_text(result.message, turn_id=turn_id)

    async def _finalize_text(self, text: str, *, turn_id: str) -> TurnOutcome:
        await self._speak(text, turn_id=turn_id, after=JarvisState.IDLE)
        if self.state.state == JarvisState.THINKING:
            await self.state.transition(JarvisState.IDLE, turn_id=turn_id)
        return TurnOutcome(turn_id=turn_id, text=text)

    async def _speak(self, text: str, *, turn_id: str, after: JarvisState) -> None:
        # If an interruption already moved the state to listening, do not steal
        # the microphone state back just to play a late response.
        if self.state.state == JarvisState.LISTENING:
            return
        await self.state.transition(JarvisState.SPEAKING, turn_id=turn_id)
        token = CancellationToken()
        self._speech_token = token
        try:
            await self.tts.speak(text, interrupt=token)
        except Exception as exc:
            if self.logger:
                self.logger.event("tts.failed", turn_id=turn_id, error_class=type(exc).__name__)
        finally:
            if self._speech_token is token:
                self._speech_token = None
        if self.state.state == JarvisState.SPEAKING:
            await self.state.transition(after, turn_id=turn_id)

    async def _announce_error(self, text: str, *, turn_id: str, error_class: str) -> None:
        if self.state.state != JarvisState.ERROR:
            try:
                await self.state.transition(JarvisState.ERROR, turn_id=turn_id, message=error_class)
            except Exception:
                await self.state.recover_to_idle(turn_id=turn_id, message=error_class)
                return
        token = CancellationToken()
        self._speech_token = token
        try:
            await self.tts.speak(text, interrupt=token)
        except Exception as exc:
            if self.logger:
                self.logger.event("tts.error_announcement_failed", turn_id=turn_id, error_class=type(exc).__name__)
        finally:
            if self._speech_token is token:
                self._speech_token = None
        if self.state.state == JarvisState.ERROR:
            await self.state.transition(JarvisState.IDLE, turn_id=turn_id)

