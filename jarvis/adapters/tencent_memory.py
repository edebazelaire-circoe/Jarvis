"""Optional Tencent MemoryCore sidecar: a recall leg and an outward mirror (Slice 06).

Tencent is derived, disposable state. The canonical Markdown store stays the
only authority; this module never writes to it and never trusts the sidecar:

- `TencentMemoryRetriever` is the `RecallLeg` named `tencent`. It asks the
  sidecar for a ranking, resolves every hit to a canonical `memory_id`, drops
  what does not resolve, and reads the snippet from canonical. Tencent supplies
  ranks only, never text.
- `TencentMirrorSink` pushes canonical notes outward, asynchronously and
  loss-tolerant (a dropped or failed push is repaired by `resync`).
- Identity: team = configured constant, user = owner, agent = agent id. The
  scope and agent isolation are enforced HERE, on canonical data, before and
  after the call; the sidecar's own isolation is a second layer, not the first.
- A circuit breaker (3 consecutive failures, open 60 s) turns a dead sidecar
  into `degraded: tencent_unavailable` at once, without waiting for timeouts.
- Nothing runs at import or construction: no network, no startup probe.
  Disabled (the default) means `register_retriever` returns `None`.

The wire shape is pinned in `docs/memory-tencent.md` (upstream
TencentDB-Agent-Memory@0468a2a, MemoryCore v3 API). The wire is NOT verified
against a running sidecar; the live test is the check.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from jarvis.adapters.memory_leg_pool import LegPool
from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.memory import (
    PRIVATE_SCOPE,
    CapabilityState,
    CapabilityStatus,
    DegradedReason,
    MemoryErrorCode,
    MemoryFilters,
    MemoryNote,
    MemoryStoreError,
    RecallQuery,
    capability_ok,
)
from jarvis.domain.memory_leg import (
    LEG_TENCENT,
    LEG_TOP,
    LegDegraded,
    LegHit,
    LegResult,
    clip_text,
    is_valid_at,
    provenance_ref,
)
from jarvis.domain.memory_settings import TencentSettings
from jarvis.runtime.credentials import secret_for

_LOG = logging.getLogger("jarvis")

CAPABILITY_ID = LEG_TENCENT
MIRROR_CAPABILITY_ID = "tencent_mirror"
DEFAULT_TEAM = "jarvis"
DEFAULT_USER = "owner"
#: Agent bucket of a note (or a query) that names no agent.
DEFAULT_AGENT = "jarvis"
#: One L0 session holds the whole mirror (the sidecar requires a session id).
MIRROR_SESSION = "jarvis-memory-mirror"

BREAKER_THRESHOLD = 3
BREAKER_OPEN_S = 60.0
#: A sidecar answer is read up to this size; more is hostile or broken.
MAX_RESPONSE_BYTES = 512 * 1024
#: Hits read from one answer (the sidecar caps `limit` at 100).
MAX_HITS_READ = 100
#: Sidecar limits (v3 doc): query 2 048 chars, message content 8 192 chars.
MAX_QUERY_CHARS = 2_048
MAX_CONTENT_CHARS = 8_192
#: Ask for more than the leg needs: dropped hits must not eat the slots.
_OVERFETCH = 3
_SNIPPET_CHARS = 1_500
MAX_PENDING = 1_000
_LIST_PAGE = 500

PATH_SEARCH = "/v3/conversation/search"
PATH_ADD = "/v3/conversation/add"
PATH_DELETE = "/v3/conversation/delete"
#: Header the data plane requires besides the bearer token (the sidecar instance id; not a secret).
HEADER_SERVICE_ID = "x-tdai-service-id"
#: `message_ids` of `conversation/delete` holds at most 5 000 ids (upstream doc).
MAX_DELETE_IDS = 5_000

_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
# `[jarvis:<memory_id>:r<revision>]` opens every mirrored message: the only way
# back to a canonical note, since the sidecar keeps no custom metadata.
_MARKER = re.compile(r"\A\[jarvis:([A-Za-z0-9_.-]{1,64}):r(\d{1,9})\]")


# ------------------------------------------------------------------ errors
class TencentConfigError(ValueError):
    """The configured sidecar URL is not acceptable. The message never holds the URL."""


class TencentError(Exception):
    """A sidecar call failed. The message is ours (never the token, never the body)."""


class TencentTimeout(TencentError):
    pass


class TencentUnavailable(TencentError):
    """Transport failure, bad status, malformed answer, or the breaker is open."""


# ------------------------------------------------------------------ config and identity
def validate_url(url: str) -> str:
    """The normalised base URL, or `TencentConfigError`.

    `https` anywhere; plain `http` only on loopback (the bearer token would
    cross the network in clear). No credentials, query or fragment in the URL.
    """

    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise TencentConfigError("the sidecar URL must be http(s) with a host")
    if parts.username is not None or parts.password is not None:
        raise TencentConfigError("the sidecar URL must not carry credentials")
    if parts.query or parts.fragment:
        raise TencentConfigError("the sidecar URL must not carry a query or fragment")
    if parts.scheme == "http" and parts.hostname.lower() not in _LOOPBACK:
        raise TencentConfigError("plain http is accepted on loopback only; use https")
    try:
        parts.port  # noqa: B018 - a bad port raises ValueError here
    except ValueError as exc:
        raise TencentConfigError("the sidecar URL has an invalid port") from exc
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


@dataclass(frozen=True, slots=True)
class TencentConfig:
    base_url: str
    team: str = DEFAULT_TEAM
    user: str = DEFAULT_USER
    allow_private: bool = False
    mirror_timeout_s: float = 5.0
    #: Instance id sent as `x-tdai-service-id` when set. An identifier, not a credential.
    service_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", validate_url(self.base_url))
        for name in ("team", "user"):
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", getattr(self, name)):
                raise TencentConfigError(f"{name} must be a short token")
        if self.service_id and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", self.service_id):
            raise TencentConfigError("service_id must be a short identifier")


@dataclass(frozen=True, slots=True)
class TencentIdentity:
    """The sidecar's isolation trio. `team` is a constant, `user` the owner, `agent` the agent id."""

    team: str
    user: str
    agent: str

    def body(self) -> dict[str, str]:
        return {"team_id": self.team, "user_id": self.user, "agent_id": self.agent}


def identity_for(config: TencentConfig, agent: str | None) -> TencentIdentity:
    return TencentIdentity(config.team, config.user, agent or DEFAULT_AGENT)


def readable_scopes(scopes: Sequence[str], allow_private: bool) -> tuple[str, ...]:
    """Scopes that may leave the machine: `private` only when explicitly allowed."""

    return tuple(scope for scope in scopes if allow_private or scope != PRIVATE_SCOPE)


# ------------------------------------------------------------------ circuit breaker
class CircuitBreaker:
    """Closed until `threshold` consecutive failures; then open for `open_s`.

    After that one trial call is let through (half-open): success closes the
    breaker, failure re-opens it for another `open_s`.
    """

    def __init__(
        self, threshold: int = BREAKER_THRESHOLD, open_s: float = BREAKER_OPEN_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._open_s = open_s
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._trial = False

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self._open_s or self._trial:
                return False
            self._trial = True
            return True

    def record_success(self) -> bool:
        """True when this success closed an open breaker."""

        with self._lock:
            reopened = self._opened_at is not None
            self._failures = 0
            self._opened_at = None
            self._trial = False
            return reopened

    def record_failure(self) -> bool:
        """True when this failure opened (or re-opened) the breaker."""

        with self._lock:
            self._trial = False
            self._failures += 1
            if self._failures >= self._threshold:
                self._opened_at = self._clock()
                return True
            return False

    def abandon(self) -> None:
        """A trial call was cancelled without an outcome: let the next one try."""

        with self._lock:
            self._trial = False

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._opened_at is not None and (self._clock() - self._opened_at < self._open_s or self._trial)

    def retry_in(self) -> float:
        with self._lock:
            if self._opened_at is None:
                return 0.0
            return max(self._open_s - (self._clock() - self._opened_at), 0.0)


# ------------------------------------------------------------------ transport
def _bearer(token: object) -> str:
    """The token as a header value, or a coded refusal that quotes no part of it."""

    if not isinstance(token, str):
        raise TencentUnavailable("the sidecar token is not a string")
    token = token.strip()
    if token and not (token.isascii() and token.isprintable() and " " not in token):
        raise TencentUnavailable("the sidecar token holds characters an HTTP header cannot carry")
    return token


class TencentClient:
    """Bounded JSON-over-httpx client of the sidecar, behind the circuit breaker.

    The token is read through `token` on every call (a token saved later works
    without a restart) and never appears in an error, a log or a status.
    """

    def __init__(
        self,
        config: TencentConfig | None,
        token: Callable[[], str],
        *,
        breaker: CircuitBreaker | None = None,
        refusal: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.breaker = breaker or CircuitBreaker()
        self.last_error = ""
        self._token = token
        self._refusal = refusal  # a refused configuration: no call is ever made
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    @property
    def refusal(self) -> str:
        return self._refusal

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            # trust_env=False: a proxy from the environment must not see sidecar traffic.
            self._http = httpx.AsyncClient(
                transport=self._transport, follow_redirects=False, trust_env=False,
                limits=httpx.Limits(max_connections=4),
            )
        return self._http

    async def aclose(self) -> None:
        http, self._http = self._http, None
        if http is not None:
            await http.aclose()

    async def post(
        self, path: str, body: Mapping[str, Any], *, timeout_s: float,
        valid: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> Mapping[str, Any]:
        """The envelope's `data` mapping, or `TencentError`. Counts toward the breaker.

        `valid` checks the shape of `data`: an answer that fails it is a failure
        (breaker included), not a success that the caller later distrusts.
        """

        if self.config is None:
            raise TencentUnavailable(self._refusal or "the sidecar is not configured")
        if not self.breaker.allow():
            raise TencentUnavailable(f"circuit open, next trial in {self.breaker.retry_in():.0f} s")
        settled = False  # the breaker got an outcome (a half-open trial must never stay claimed)
        try:
            try:
                data = await asyncio.wait_for(self._exchange(path, body, timeout_s, valid), timeout_s)
            except asyncio.TimeoutError:
                settled = True
                self._failed(TencentTimeout(f"no answer within {timeout_s * 1000:.0f} ms"))
                raise TencentTimeout(self.last_error) from None
            except TencentError as exc:
                settled = True
                self._failed(exc)
                raise
            except asyncio.CancelledError:
                raise  # released by the finally: a cancelled trial has no outcome
            except Exception as exc:  # noqa: BLE001 - nothing may leave the breaker unsettled
                # Our own sentence only: the original message may quote a token character.
                settled = True
                failure = TencentUnavailable(f"unexpected {type(exc).__name__} during the sidecar call")
                self._failed(failure)
                raise failure from None
            settled = True
            if self.breaker.record_success():
                _LOG.info("tencent sidecar answers again: circuit closed")
            self.last_error = ""
            return data
        finally:
            if not settled:
                self.breaker.abandon()

    def _failed(self, exc: TencentError) -> None:
        self.last_error = str(exc)[:200]
        if self.breaker.record_failure():
            _LOG.warning("tencent sidecar failed repeatedly: circuit open for %.0f s (%s)", BREAKER_OPEN_S, self.last_error)
        else:
            _LOG.info("tencent call failed: %s", self.last_error)

    async def _exchange(
        self, path: str, body: Mapping[str, Any], timeout_s: float, valid: Callable[[Mapping[str, Any]], bool] | None,
    ) -> Mapping[str, Any]:
        assert self.config is not None
        headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
        bearer = _bearer(self._token())
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        if self.config.service_id:
            headers[HEADER_SERVICE_ID] = self.config.service_id
        raw = bytearray()
        try:
            async with self._client().stream(
                "POST", self.config.base_url + path, content=json.dumps(body).encode("utf-8"),
                headers=headers, timeout=timeout_s,
            ) as response:
                if response.status_code != 200:
                    raise TencentUnavailable(f"sidecar answered HTTP {response.status_code}")
                if response.headers.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
                    # We asked for identity. Never decode: a compressed answer is how a bomb arrives.
                    raise TencentUnavailable("sidecar answer is compressed")
                async for chunk in response.aiter_raw():
                    raw += chunk
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise TencentUnavailable("sidecar answer too large")
        except httpx.TimeoutException as exc:
            raise TencentTimeout(f"no answer within {timeout_s * 1000:.0f} ms") from exc
        except httpx.HTTPError as exc:
            raise TencentUnavailable(f"sidecar unreachable ({type(exc).__name__})") from exc
        try:
            envelope = json.loads(bytes(raw))
        except (ValueError, RecursionError) as exc:  # RecursionError: a deeply nested `[[[[...` body
            raise TencentUnavailable("sidecar answer is not JSON") from exc
        if not isinstance(envelope, dict):
            raise TencentUnavailable("sidecar answer is malformed")
        code = envelope.get("code")
        if type(code) is not int:
            raise TencentUnavailable("sidecar answer is malformed")
        if code != 0:
            raise TencentUnavailable(f"sidecar refused the call (code {code})")
        data = envelope.get("data")
        if not isinstance(data, dict) or (valid is not None and not valid(data)):
            raise TencentUnavailable("sidecar answer is malformed")
        return data

    def status(self) -> CapabilityState:
        if self.config is None:
            return CapabilityState(CapabilityStatus.UNAVAILABLE, "tencent_config_invalid", self._refusal[:300])
        if self.breaker.is_open:
            return CapabilityState(
                CapabilityStatus.DEGRADED, "tencent_unavailable",
                f"circuit open after repeated failures; next trial in {self.breaker.retry_in():.0f} s",
            )
        if self.last_error:
            return CapabilityState(CapabilityStatus.DEGRADED, "tencent_unavailable", f"last call failed: {self.last_error}"[:300])
        return capability_ok()


# ------------------------------------------------------------------ marker
def mirror_content(note: MemoryNote) -> str:
    """The text mirrored for a note: the marker first, then the canonical text."""

    return clip_text(f"[jarvis:{note.id}:r{note.revision}]\n{note.title}\n{note.body}", MAX_CONTENT_CHARS)


def parse_marker(content: object) -> str | None:
    """The canonical `memory_id` a sidecar message names, or `None` (the hit is dropped)."""

    if not isinstance(content, str):
        return None
    found = _MARKER.match(content[:128])
    return found.group(1) if found else None


class NoteStore(Protocol):
    """The slice of `MarkdownMemoryBackend` the leg and the sink use (synchronous, called in a thread)."""

    def get(self, memory_id: str) -> MemoryNote: ...

    def list(self, filters: MemoryFilters) -> tuple[MemoryNote, ...]: ...


# ------------------------------------------------------------------ recall leg
class TencentMemoryRetriever:
    """`RecallLeg` over the sidecar's L0 search. Ranks only; canonical text and canonical scope."""

    name = LEG_TENCENT
    capability_id = CAPABILITY_ID

    def __init__(self, client: TencentClient, store: NoteStore) -> None:
        self._client = client
        self._store = store
        self._pool = LegPool("tencent")

    async def hits(self, query: RecallQuery, limit: int = LEG_TOP, timeout_s: float = 0.25) -> LegResult:
        config = self._client.config
        allow_private = bool(config and config.allow_private)
        scopes = readable_scopes(query.scopes, allow_private)
        if not scopes or not query.text.strip():
            return LegResult()  # nothing that may leave the machine: no call, the text is not sent
        identity = identity_for(config, query.agent) if config else None
        body: dict[str, Any] = {
            "query": query.text[:MAX_QUERY_CHARS], "limit": min(max(limit, 1) * _OVERFETCH, MAX_HITS_READ),
            **(identity.body() if identity else {}),
        }
        try:
            data = await self._client.post(
                PATH_SEARCH, body, timeout_s=max(timeout_s * 0.9, 0.005),
                valid=lambda data: isinstance(data.get("messages"), list),
            )
        except TencentTimeout as exc:
            raise LegDegraded(DegradedReason.TENCENT_TIMEOUT, str(exc)) from exc
        except TencentError as exc:
            raise LegDegraded(DegradedReason.TENCENT_UNAVAILABLE, str(exc)) from exc
        messages = data["messages"]
        ranked: dict[str, None] = {}
        for message in messages[:MAX_HITS_READ]:
            memory_id = parse_marker(message.get("content")) if isinstance(message, dict) else None
            if memory_id is not None:
                ranked.setdefault(memory_id, None)  # a note counts once, at its first rank
        try:
            hits = await self._pool.run(self._hydrate, query, scopes, identity, tuple(ranked), limit)
        except MemoryStoreError as exc:
            _LOG.warning("tencent leg could not read canonical notes: %s", exc)
            raise LegDegraded(DegradedReason.TENCENT_UNAVAILABLE, exc.message) from exc
        return LegResult(tuple(hits))

    def _hydrate(
        self, query: RecallQuery, scopes: Sequence[str], identity: TencentIdentity | None,
        memory_ids: Sequence[str], limit: int,
    ) -> list[LegHit]:
        """Resolve each id on canonical; whatever does not resolve or is out of bounds is dropped."""

        at = query.at or datetime.now(timezone.utc)
        agent = identity.agent if identity else (query.agent or DEFAULT_AGENT)
        hits: list[LegHit] = []
        for memory_id in memory_ids:
            try:
                note = self._store.get(memory_id)
            except MemoryStoreError as exc:
                if exc.code is not MemoryErrorCode.NOT_FOUND:
                    raise
                continue
            except MemorySecurityError:
                continue
            if note.scope not in scopes or (note.agent or DEFAULT_AGENT) != agent:
                continue  # isolation is judged on canonical data, whatever the sidecar returned
            if query.retentions and note.retention not in query.retentions:
                continue
            if query.levels and note.level not in query.levels:
                continue
            if not query.include_history and (note.is_superseded or not is_valid_at(note.valid_from, note.valid_to, at)):
                continue
            hits.append(LegHit(
                memory_id=note.id, revision=note.revision, updated_at=note.updated_at, title=note.title,
                snippet=clip_text(note.body.strip(), _SNIPPET_CHARS), level=note.level, retention=note.retention,
                provenance_ref=provenance_ref(note.retention, note.id), superseded=note.is_superseded,
                why=f"tencent rank {len(hits) + 1}",
            ))
            if len(hits) >= limit:
                break
        return hits

    def status(self) -> CapabilityState:
        return self._client.status()


# ------------------------------------------------------------------ mirror
@dataclass(frozen=True, slots=True)
class _Entry:
    """What the sidecar holds for a note: the digest pushed and the sidecar's own message ids."""

    digest: str
    ids: tuple[str, ...]
    agent: str


class MirrorLedger:
    """Which notes are mirrored, and under which sidecar ids. Derived: losing it only costs a re-push.

    `set` and `pop` only mark it dirty; `flush()` writes it (atomically, off the
    event loop, at most once per batch), so a burst of pushes is one write.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._entries: dict[str, _Entry] = {}
        self._dirty = False
        self._write_lock = threading.Lock()
        if path is not None:
            self._load(path)

    def _load(self, path: Path) -> None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            entries = {}
            for key, value in raw["entries"].items():
                ids = value["ids"]
                if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                    raise TypeError("ids must be a list of strings")
                entries[str(key)] = _Entry(str(value["digest"]), tuple(ids), str(value["agent"]))
            self._entries = entries
        except FileNotFoundError:
            pass  # intentional: no ledger yet is the normal first run
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
            _LOG.warning("tencent mirror ledger %s unreadable (%s): starting empty, resync repairs it", path.name, type(exc).__name__)
            self._entries = {}

    def get(self, memory_id: str) -> _Entry | None:
        return self._entries.get(memory_id)

    def ids(self) -> list[str]:
        return list(self._entries)

    def set(self, memory_id: str, entry: _Entry) -> None:
        self._entries[memory_id] = entry
        self._dirty = True

    def pop(self, memory_id: str) -> None:
        if self._entries.pop(memory_id, None) is not None:
            self._dirty = True

    async def flush(self) -> None:
        """Write the ledger if it changed. Never raises: a failed write leaves it dirty for the next flush."""

        if self._path is None or not self._dirty:
            return
        self._dirty = False
        payload = {"version": 1, "entries": {
            key: {"digest": e.digest, "ids": list(e.ids), "agent": e.agent} for key, e in self._entries.items()
        }}
        try:
            await asyncio.to_thread(self._write, payload)
        except OSError as exc:
            # The ledger is derived: the in-memory copy stays and the next flush retries.
            self._dirty = True
            _LOG.warning("tencent mirror ledger could not be saved (%s)", type(exc).__name__)

    def _write(self, payload: dict[str, Any]) -> None:
        assert self._path is not None
        with self._write_lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._path.with_name(self._path.name + ".tmp")
            temp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temp, self._path)


@dataclass(frozen=True, slots=True)
class ResyncReport:
    pushed: int = 0
    unchanged: int = 0
    removed: int = 0
    failed: int = 0
    #: `circuit_open` when the run stopped early; empty when it completed.
    stopped: str = ""


def _accepted_ids_ok(data: Mapping[str, Any]) -> bool:
    accepted = data.get("accepted_ids")
    return isinstance(accepted, list) and 1 <= len(accepted) <= MAX_HITS_READ and all(
        isinstance(item, str) and 0 < len(item) <= 128 for item in accepted
    )


def _digest(note: MemoryNote, agent: str) -> str:
    parts = (note.title, note.body, note.scope, str(note.revision), agent)
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


#: A failed push is retried after this many retry intervals, doubling per attempt up to the cap.
_BACKOFF_CAP = 8
_FLUSH_EVERY = 100


class TencentMirrorSink:
    """Pushes canonical notes to the sidecar, off the write path.

    `notify_written(memory_id)` is callable from any thread and never blocks or
    raises: the store calls it after a canonical write, whatever the sidecar
    state. A background task (`start`) pushes; a failed push is retried with a
    backoff (also while writes keep arriving) and repaired by `resync`. Which
    notes leave the machine: not `private` unless `allow_private`, not superseded.
    One note is never pushed twice at once (per-note lock), and the background
    run and `resync` never interleave.
    """

    capability_id = MIRROR_CAPABILITY_ID

    def __init__(
        self, client: TencentClient, store: NoteStore, *, ledger: MirrorLedger | None = None,
        retry_interval_s: float = 60.0, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if client.config is None:
            raise ValueError("the mirror needs a valid sidecar configuration")
        self._client = client
        self._config = client.config
        self._store = store
        self._ledger = ledger or MirrorLedger()
        self._retry_interval_s = retry_interval_s
        self._clock = clock
        self._pending: dict[str, None] = {}
        #: memory_id -> (attempts, monotonic time of the next try)
        self._failed: dict[str, tuple[int, float]] = {}
        self._dropped = 0
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._resync_lock = asyncio.Lock()
        self._note_locks: dict[str, list] = {}

    # ----------------------------------------------------------- write side
    def notify_written(self, memory_id: str) -> None:
        with self._lock:
            if memory_id not in self._pending and len(self._pending) >= MAX_PENDING:
                self._dropped += 1  # loss-tolerant: resync repairs what was dropped
                return
            self._pending[memory_id] = None
            loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass  # intentional: the loop is closed (shutdown); the note stays pending for resync

    def _take(self) -> list[str]:
        """The pending ids plus the failed ones whose backoff is over, in one batch."""

        now = self._clock()
        with self._lock:
            for memory_id in [i for i, (_n, due) in self._failed.items() if due <= now]:
                self._pending.setdefault(memory_id, None)
            batch = list(self._pending)
            self._pending.clear()
            return batch

    def _defer(self, memory_id: str) -> None:
        with self._lock:
            attempts = self._failed.get(memory_id, (0, 0.0))[0] + 1
            delay = self._retry_interval_s * min(2 ** (attempts - 1), _BACKOFF_CAP)
            self._failed[memory_id] = (attempts, self._clock() + delay)

    def _settled(self, memory_id: str) -> None:
        with self._lock:
            self._failed.pop(memory_id, None)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        with self._lock:
            if self._pending:
                self._wake.set()
        self._task = asyncio.create_task(self._run(), name="tencent-mirror")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # intentional: we cancelled it ourselves
        await self._ledger.flush()

    async def _run(self) -> None:
        wake = self._wake
        assert wake is not None
        while True:
            try:
                await asyncio.wait_for(wake.wait(), self._retry_interval_s)
            except asyncio.TimeoutError:
                pass  # intentional: the retry tick; `_take` requeues what is due
            wake.clear()
            batch = self._take()
            if not batch:
                continue
            async with self._resync_lock:
                for memory_id in batch:
                    await self._push_quietly(memory_id)
                await self._ledger.flush()

    async def _push_quietly(self, memory_id: str) -> None:
        try:
            await self.push(memory_id)
        except TencentError as exc:
            self._defer(memory_id)
            _LOG.info("tencent mirror push of %s deferred: %s", memory_id, exc)
        except MemoryStoreError as exc:
            self._defer(memory_id)
            _LOG.warning("tencent mirror could not read %s: %s", memory_id, exc)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the mirror loop must outlive one bad note
            self._defer(memory_id)
            _LOG.exception("tencent mirror push of %s crashed", memory_id)
        else:
            self._settled(memory_id)

    # ---------------------------------------------------------------- push
    def wants(self, note: MemoryNote) -> bool:
        if note.is_superseded:
            return False
        return self._config.allow_private or note.scope != PRIVATE_SCOPE

    @asynccontextmanager
    async def _note_lock(self, memory_id: str) -> AsyncIterator[None]:
        entry = self._note_locks.setdefault(memory_id, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self._note_locks.pop(memory_id, None)

    async def push(self, memory_id: str) -> str:
        """Mirror (or unmirror) one canonical note: `pushed`, `unchanged` or `removed`.

        Reads the note under the per-note lock, so two pushes of one note (the
        background run and a resync) serialise and the later one sees the first's ledger entry.
        Does not flush the ledger: batch callers do.
        """

        async with self._note_lock(memory_id):
            try:
                note = await asyncio.to_thread(self._store.get, memory_id)
            except MemoryStoreError as exc:
                if exc.code is not MemoryErrorCode.NOT_FOUND:
                    raise
                return "removed" if await self._remove(memory_id) else "unchanged"
            if not self.wants(note):
                return "removed" if await self._remove(memory_id) else "unchanged"
            return await self._sync_note(note)

    async def _sync_note(self, note: MemoryNote) -> str:
        agent = note.agent or DEFAULT_AGENT
        digest = _digest(note, agent)
        entry = self._ledger.get(note.id)
        if entry is not None and entry.digest == digest:
            return "unchanged"
        if entry is not None and entry.ids:  # the sidecar has no idempotency key: replace, never duplicate
            await self._delete(entry.ids, identity_for(self._config, entry.agent))  # where it was written
            self._ledger.set(note.id, _Entry("", (), entry.agent))
        identity = identity_for(self._config, agent)
        body = {
            "session_id": MIRROR_SESSION, **identity.body(),
            "messages": [{"role": "user", "content": mirror_content(note), "timestamp": note.updated_at.isoformat()}],
        }
        data = await self._client.post(PATH_ADD, body, timeout_s=self._config.mirror_timeout_s, valid=_accepted_ids_ok)
        self._ledger.set(note.id, _Entry(digest, tuple(data["accepted_ids"]), agent))
        return "pushed"

    async def _delete(self, ids: Sequence[str], identity: TencentIdentity) -> None:
        for start in range(0, len(ids), MAX_DELETE_IDS):
            await self._client.post(
                PATH_DELETE, {"message_ids": list(ids[start:start + MAX_DELETE_IDS]), **identity.body()},
                timeout_s=self._config.mirror_timeout_s,
            )

    async def _remove(self, memory_id: str) -> bool:
        entry = self._ledger.get(memory_id)
        if entry is None:
            return False
        if entry.ids:
            await self._delete(entry.ids, identity_for(self._config, entry.agent))
        self._ledger.pop(memory_id)
        return True

    # -------------------------------------------------------------- resync
    async def resync(self) -> ResyncReport:
        """Make the mirror equal canonical. Idempotent: a second run pushes and removes nothing.

        Each note is re-read under its lock (`push`), so a write that lands during the run is
        never overwritten by the older listing.
        """

        async with self._resync_lock:
            notes = await asyncio.to_thread(self._list_all)
            ids = list(dict.fromkeys([note.id for note in notes if self.wants(note)] + self._ledger.ids()))
            counts = {"pushed": 0, "unchanged": 0, "removed": 0, "failed": 0}
            stopped = ""
            for index, memory_id in enumerate(ids, start=1):
                try:
                    counts[await self.push(memory_id)] += 1
                    self._settled(memory_id)
                except (TencentError, MemoryStoreError) as exc:
                    counts["failed"] += 1
                    self._defer(memory_id)
                    if self._client.breaker.is_open:
                        stopped = "circuit_open"
                        break
                    _LOG.info("tencent resync of %s failed: %s", memory_id, exc)
                if index % _FLUSH_EVERY == 0:
                    await self._ledger.flush()
            await self._ledger.flush()
            report = ResyncReport(stopped=stopped, **counts)
            if not report.failed and not report.stopped:
                with self._lock:
                    self._dropped = 0  # the mirror equals canonical again: nothing is lost any more
            _LOG.info(
                "tencent resync: pushed=%d unchanged=%d removed=%d failed=%d stopped=%s",
                report.pushed, report.unchanged, report.removed, report.failed, report.stopped or "-",
            )
            return report

    def _list_all(self) -> list[MemoryNote]:
        notes: list[MemoryNote] = []
        offset = 0
        while True:
            page = self._store.list(MemoryFilters(limit=_LIST_PAGE, offset=offset))
            notes.extend(page)
            if len(page) < _LIST_PAGE:
                return notes
            offset += _LIST_PAGE

    def status(self) -> CapabilityState:
        with self._lock:
            behind = len(self._failed) + len(self._pending)
            dropped = self._dropped
            failed = bool(self._failed)
        if dropped:
            return CapabilityState(
                CapabilityStatus.DEGRADED, "tencent_mirror_behind", f"{dropped} writes were not queued; run resync",
            )
        if failed:
            return CapabilityState(
                CapabilityStatus.DEGRADED, "tencent_mirror_behind", f"{behind} notes wait for the sidecar",
            )
        return capability_ok()


# ------------------------------------------------------------------ wiring entry point
@dataclass(frozen=True, slots=True)
class TencentRegistration:
    """What Core keeps when the sidecar is enabled: the leg, the sink (`None` when the URL is refused)."""

    leg: TencentMemoryRetriever
    sink: TencentMirrorSink | None
    client: TencentClient
    #: The mirror's own client and breaker: a slow or failing mirror call must not degrade recall.
    mirror_client: TencentClient | None = None

    async def start(self) -> None:
        if self.sink is not None:
            await self.sink.start()

    async def aclose(self) -> None:
        if self.sink is not None:
            await self.sink.stop()
        await self.client.aclose()
        if self.mirror_client is not None:
            await self.mirror_client.aclose()


def register_retriever(
    tencent: TencentSettings,
    credentials: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
    store: NoteStore,
    *,
    ledger_path: Path | None = None,
    allow_private: bool = False,
    team: str = DEFAULT_TEAM,
    user: str = DEFAULT_USER,
    service_id: str = "",
    transport: httpx.AsyncBaseTransport | None = None,
) -> TencentRegistration | None:
    """The entry point Core's memory wiring calls (docs/memory-tencent.md).

    Returns `None` when `tencent.enabled` is false: nothing is built, nothing
    can touch the network. Otherwise builds the leg (add it to the
    `HybridRetriever` legs) and the mirror sink (Core calls
    `sink.notify_written(id)` after each canonical write and `await
    registration.start()` once the loop runs). No network happens here. A
    refused URL still yields a registration whose leg reports
    `unavailable: tencent_config_invalid` and never calls out.
    """

    if not tencent.enabled:
        return None

    def token() -> str:
        current = credentials() if callable(credentials) else credentials
        return secret_for(dict(current), "tencent")

    try:
        config = TencentConfig(tencent.url, team=team, user=user, allow_private=allow_private, service_id=service_id)
    except TencentConfigError as exc:
        _LOG.warning("tencent sidecar refused: %s", exc)
        client = TencentClient(None, token, refusal=str(exc))
        return TencentRegistration(TencentMemoryRetriever(client, store), None, client)
    client = TencentClient(config, token, transport=transport)
    mirror_client = TencentClient(config, token, transport=transport)
    sink = TencentMirrorSink(mirror_client, store, ledger=MirrorLedger(ledger_path))
    _LOG.info("tencent sidecar enabled at %s (no startup probe)", urlsplit(config.base_url).netloc)
    return TencentRegistration(TencentMemoryRetriever(client, store), sink, client, mirror_client)
