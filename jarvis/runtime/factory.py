from __future__ import annotations

from dataclasses import dataclass

from jarvis.adapters.barehands_board import BarehandsBoardClient
from jarvis.adapters.file_state_bus import CompositeStatePublisher, FileStatePublisher
from jarvis.adapters.markdown_memory import MarkdownMemoryBackend
from jarvis.adapters.null_board import UnavailableBoardClient
from jarvis.adapters.openai_agent import OpenAIAgentBackend
from jarvis.adapters.openai_transcription import OpenAITranscriptionBackend
from jarvis.adapters.openai_tts import OpenAITTSBackend
from jarvis.adapters.silent_tts import SilentTTSBackend
from jarvis.audio.capture import SoundDeviceRecorder
from jarvis.config import AppConfig
from jarvis.core.actions import ActionBroker
from jarvis.core.executors import build_action_executors
from jarvis.core.orchestrator import JarvisOrchestrator
from jarvis.core.session import SessionStateMachine
from jarvis.core.tools import ToolRegistry
from jarvis.diagnostics.logger import PrivacyLogger, build_logger
from jarvis.domain.errors import ConfigurationError


@dataclass(slots=True)
class RuntimeBundle:
    recorder: SoundDeviceRecorder
    transcriber: OpenAITranscriptionBackend
    orchestrator: JarvisOrchestrator
    state: SessionStateMachine
    logger: PrivacyLogger


def create_runtime(config: AppConfig, *, speech_enabled: bool) -> RuntimeBundle:
    api_key = config.openai.api_key
    if not api_key:
        raise ConfigurationError("OPENAI_API_KEY est requis pour le runtime conversationnel")

    logger = build_logger(config.runtime.runtime_dir, level=config.runtime.log_level, log_content=config.runtime.log_content)
    memory = MarkdownMemoryBackend(config.runtime.memory_dir)
    board = BarehandsBoardClient(config.board.url, "v1-local") if config.board.enabled else UnavailableBoardClient()
    publisher = CompositeStatePublisher(FileStatePublisher(config.runtime.runtime_dir))
    state = SessionStateMachine(publisher)
    recorder = SoundDeviceRecorder(sample_rate=config.audio.sample_rate, channels=config.audio.channels, input_device=config.audio.input_device)
    transcriber = OpenAITranscriptionBackend(api_key=api_key, model=config.openai.transcription_model, base_url=config.openai.base_url, timeout_s=config.openai.timeout_s)
    agent = OpenAIAgentBackend(api_key=api_key, model=config.openai.agent_model, base_url=config.openai.base_url, timeout_s=config.openai.timeout_s)
    if speech_enabled:
        tts = OpenAITTSBackend(api_key=api_key, model=config.openai.tts_model, voice=config.openai.tts_voice, instructions=config.openai.tts_instructions, base_url=config.openai.base_url, timeout_s=config.openai.timeout_s)
    else:
        tts = SilentTTSBackend()
    broker = ActionBroker(build_action_executors(memory, board), confirmation_timeout_s=config.runtime.confirmation_timeout_s)
    orchestrator = JarvisOrchestrator(agent=agent, tts=tts, state=state, tools=ToolRegistry(), broker=broker, logger=logger)
    return RuntimeBundle(recorder=recorder, transcriber=transcriber, orchestrator=orchestrator, state=state, logger=logger)
