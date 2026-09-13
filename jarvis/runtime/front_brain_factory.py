"""Composition-only Luna construction. Failure leaves direct conversation intact."""
import hashlib
import json
import os

from jarvis.adapters.openai_front_brain import LunaFrontBrainAnalyzer
from jarvis.domain.front_brain_prompt import FRONT_BRAIN_PROMPT_ID
from jarvis.runtime.credentials import secret_for
from jarvis.runtime.front_brain_sidecar import FrontBrainSidecar, FrontBrainSidecarConfig
from jarvis.runtime.conversation_context import selected_voice_context


def attach_front_brain(session, config, context: dict, *, overrides: dict, journal=None) -> None:
    key = secret_for(overrides, config.analysis_model.provider_id)
    if not key:
        if journal is not None:
            journal.emit("voice.hint.unavailable", "Front Brain credentials unavailable", data={"reason": "credentials_missing"})
        return
    try:
        analyzer = LunaFrontBrainAnalyzer(api_key=key, model=config.analysis_model.model_id,
            reasoning_effort=config.reasoning_effort or "low", base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            diagnostics=journal, prompt_overrides=overrides.get("prompt_overrides"))
        identity = hashlib.sha256(json.dumps({"model": config.analysis_model.model_id, "effort": config.reasoning_effort,
            "prompt": FRONT_BRAIN_PROMPT_ID, "prompt_fingerprint": analyzer.prompt_static_fingerprint,
            "speculative": config.speculative_deltas}, sort_keys=True).encode()).hexdigest()
        sidecar = FrontBrainSidecar(analyzer, session_id=session.session_id, configuration_id=identity,
            config=FrontBrainSidecarConfig(speculative_deltas=config.speculative_deltas), diagnostics=journal)
        sidecar.update_context(selected_voice_context(context), source=None, source_complete=False)
        session.analysis = sidecar
        sidecar.start()
    except (ValueError, TypeError) as exc:
        if journal is not None:
            journal.emit("voice.hint.unavailable", "Front Brain configuration unavailable", data={"reason": "configuration_invalid", "exception_type": type(exc).__name__})
