"""The provider seam of the `live` profile: what opens a REAL Realtime session, and what may.

Binding contract: `docs/testlab.md` ("Live profile"). Every gate is here, in one
place, and every one of them is mechanical:

1. **Capability** — the profile must declare `realtime_provider`, and the caller's
   `ResourceGrant` must hold it (`check_profile_permission`, Slice 01).
2. **Budget** — the profile's declared `max_cost_usd` must fit the grant's, checked
   by the same gate before the run is queued, and the mid-run estimate must stay
   under it (`jarvis.testlab.live.cost.CostBudget`).
3. **Explicit opt-in** — `JARVIS_TESTLAB_LIVE=1` in the supervisor's environment.
   Nothing derives it, nothing defaults it on. The supervisor refuses a provider
   reservation without it (`live_opt_in_missing`), so a live run cannot happen
   because a test forgot a flag.
4. **A key** — `OPENAI_API_KEY`. Slice 05 empties provider keys in a worker's
   environment unless the profile declares a provider capability, so a `virtual`
   or `audio` worker physically cannot reach a provider even with this module
   imported.

The factory itself is injectable (`LiveSessionFactory`), which is how the default
test suite exercises the whole live runner — budget gate, usage folding, mid-run
abort, metadata — against a double, with no network and no cost.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from typing import Any, Protocol

from jarvis.testlab.validation import TestLabError, fail

#: The one switch. Deliberate, per-process, never inferred.
LIVE_OPT_IN_ENV = "JARVIS_TESTLAB_LIVE"
API_KEY_ENV = "OPENAI_API_KEY"
MODEL_ENV = "OPENAI_REALTIME_MODEL"
VOICE_ENV = "OPENAI_REALTIME_VOICE"
DEFAULT_VOICE = "cedar"

LIVE_OPT_IN_MISSING = "testlab_live_opt_in_missing"
LIVE_PROVIDER_UNAVAILABLE = "testlab_live_provider_unavailable"


class LiveGateError(TestLabError):
    """A live run was attempted without one of its explicit gates."""


def live_opt_in(environ: Any = None) -> bool:
    """Is the explicit live opt-in set in this environment?"""
    source = os.environ if environ is None else environ
    return source.get(LIVE_OPT_IN_ENV) == "1"


def live_key_present(environ: Any = None) -> bool:
    source = os.environ if environ is None else environ
    return bool(source.get(API_KEY_ENV))


def check_live_gates(environ: Any = None) -> None:
    """Raise `LiveGateError` unless the opt-in AND a key are present. Never logs either."""
    source = os.environ if environ is None else environ
    if not live_opt_in(source):
        raise LiveGateError(LIVE_OPT_IN_MISSING,
                            f"a live run needs the explicit opt-in {LIVE_OPT_IN_ENV}=1; it is not set")
    if not live_key_present(source):
        raise LiveGateError(LIVE_OPT_IN_MISSING,
                            f"a live run needs {API_KEY_ENV} in the worker environment; it is empty")


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    """Who answered, and with what configuration. Recorded on every live run."""

    provider: str
    model_id: str
    voice: str
    #: `build_config_snapshot(...).fingerprint` of the run's effective settings.
    config_fingerprint: str | None = None
    #: The provider's own session id, once it has one.
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "model_id": self.model_id, "voice": self.voice,
                "config_fingerprint": self.config_fingerprint, "session_id": self.session_id}


def resolve_identity(environ: Any = None, *, config_fingerprint: str | None = None) -> ProviderIdentity:
    """The provider, model and voice a live run WILL use, resolved the way production resolves them.

    Same precedence as `jarvis.v2_config`: the environment overrides the recommended
    model for the continuous architecture. Reading it before connecting is what lets
    the run record its identity even when the connection fails.
    """
    from jarvis.v2_config import DEFAULT_CONTINUOUS_SURFACE_MODEL

    source = os.environ if environ is None else environ
    return ProviderIdentity(provider="openai",
                            model_id=source.get(MODEL_ENV) or DEFAULT_CONTINUOUS_SURFACE_MODEL,
                            voice=source.get(VOICE_ENV) or DEFAULT_VOICE,
                            config_fingerprint=config_fingerprint)


class LiveSessionFactory(Protocol):
    """Opens one provider session for a run. A double satisfies this in the default suite."""

    async def __call__(self, context: Any, session_id: str) -> Any:
        ...


def openai_realtime_factory(identity: ProviderIdentity, *, environ: Any = None,
                            log: Callable[[str], None] | None = None) -> LiveSessionFactory:
    """The REAL factory: one `OpenAIRealtimeSession` per activation.

    It re-checks the gates at connection time, not only at reservation time: a
    supervisor and its worker are different processes, and the check that matters
    is the one in the process that would make the call.
    """
    source = os.environ if environ is None else environ

    async def connect(context: Any, session_id: str) -> Any:
        del context, session_id
        check_live_gates(source)
        try:
            from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
            from jarvis.runtime.realtime_tools import tools_for
        except ImportError as exc:
            raise LiveGateError(LIVE_PROVIDER_UNAVAILABLE,
                                f"the OpenAI Realtime adapter is not importable ({type(exc).__name__})") from exc
        if log is not None:
            log(f"opening a REAL provider session: provider={identity.provider} model={identity.model_id} "
                f"voice={identity.voice}")
        return await OpenAIRealtimeSession.connect(
            api_key=source[API_KEY_ENV], model=identity.model_id, voice=identity.voice,
            context={}, tools=tools_for(continuous_brain=True), auto_turn=True, continuous_brain=True)

    return connect


def factory_or_refuse(identity: ProviderIdentity, *, environ: Any = None,
                      log: Callable[[str], None] | None = None) -> LiveSessionFactory:
    """The real factory, after checking the gates once up front so the refusal is early and clear."""
    check_live_gates(os.environ if environ is None else environ)
    return openai_realtime_factory(identity, environ=environ, log=log)


def require_session_id(session: Any) -> str | None:
    """The provider's own session id, when the session exposes one. Never invented."""
    value = getattr(session, "session_id", None)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise fail("a provider session exposed a session_id that is not a non-empty string")
    return value
