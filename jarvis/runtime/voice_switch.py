"""Safe cross-process voice architecture switching.

The Voice process owns frontend teardown.  The supervisor owns process restart,
and Core owns conversation/work truth.  Files here carry only bounded control
metadata and a conversation pointer; they never copy provider-hidden state or
rewrite the heard-speech ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
import uuid

from jarvis.adapters.file_replace import replace_with_retry


SCHEMA_VERSION = 1
REQUEST_FILE = ".voice_switch_request"
RECEIPT_FILE = ".voice_switch_receipt"
HANDOFF_FILE = ".voice_switch_handoff"
CONVERSATION_FILE = ".voice_conversation"
_MAX_FILE_BYTES = 16_384


def _token(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or len(value) > 256 or value.strip() != value:
        raise ValueError(f"invalid {name}")
    return value


@dataclass(frozen=True, slots=True)
class VoiceSwitchRequest:
    request_id: str
    source_configuration_id: str
    target_configuration_id: str
    target_architecture: str
    target_model: str
    requested_at: float
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("request_id", "source_configuration_id", "target_configuration_id",
                     "target_architecture", "target_model"):
            _token(getattr(self, name), name)
        if self.source_configuration_id == self.target_configuration_id:
            raise ValueError("switch source and target must differ")
        if isinstance(self.requested_at, bool) or not isinstance(self.requested_at, (int, float)):
            raise ValueError("invalid requested_at")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported switch schema")

    def to_payload(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_payload(cls, value: object) -> "VoiceSwitchRequest":
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("invalid switch request fields")
        return cls(**value)


class VoiceSwitchBus:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def request(self, *, source_configuration_id: str, target_configuration_id: str,
                target_architecture: str, target_model: str) -> VoiceSwitchRequest:
        held = self.read_request()
        if held is not None and held.target_configuration_id == target_configuration_id:
            return held
        request = VoiceSwitchRequest(str(uuid.uuid4()), source_configuration_id,
                                     target_configuration_id, target_architecture,
                                     target_model, time.time())
        self._write(REQUEST_FILE, request.to_payload())
        return request

    def read_request(self) -> VoiceSwitchRequest | None:
        value = self._read(REQUEST_FILE)
        if value is None:
            return None
        try:
            return VoiceSwitchRequest.from_payload(value)
        except (TypeError, ValueError):
            return None

    def receipt(self) -> dict[str, object] | None:
        return self._read(RECEIPT_FILE)

    def complete(self, request: VoiceSwitchRequest, *, status: str,
                 message: str | None = None, remove_request: bool = True) -> None:
        if status not in {"blocked", "ready_for_restart", "applied", "failed"}:
            raise ValueError("invalid switch receipt status")
        self._write(RECEIPT_FILE, {"schema_version": 1, "request_id": request.request_id,
                    "target_configuration_id": request.target_configuration_id,
                    "status": status, "message": message, "updated_at": time.time()})
        if remove_request:
            current = self.read_request()
            if current is not None and current.request_id == request.request_id:
                (self.root / REQUEST_FILE).unlink(missing_ok=True)

    def write_handoff(self, request: VoiceSwitchRequest, *, conversation_id: str | None,
                      context: dict, work: dict, source_architecture: str | None = None,
                      source_model: str | None = None) -> None:
        context_bytes = json.dumps(context, sort_keys=True, ensure_ascii=False).encode()
        active = [item for item in work.get("items", []) if isinstance(item, dict)
                  and item.get("status") in {"pending", "running", "blocked"}]
        self._write(HANDOFF_FILE, {"schema_version": 1, "request_id": request.request_id,
                    "source_configuration_id": request.source_configuration_id,
                    "target_configuration_id": request.target_configuration_id,
                    "target_architecture": request.target_architecture,
                    "target_model": request.target_model, "conversation_id": conversation_id,
                    "source_architecture": source_architecture,
                    "source_model": source_model,
                    "context_fingerprint": hashlib.sha256(context_bytes).hexdigest(),
                    "recent_turn_count": len(context.get("recent_turns", [])),
                    "work_revision": work.get("revision"), "active_work_count": len(active),
                    "created_at": time.time()})

    def handoff(self, target_configuration_id: str) -> dict[str, object] | None:
        value = self._read(HANDOFF_FILE)
        if value is None or value.get("target_configuration_id") != target_configuration_id:
            return None
        conversation_id = value.get("conversation_id")
        if conversation_id is not None:
            try:
                _token(conversation_id, "conversation_id")
            except ValueError:
                return None
        return value

    def clear_handoff(self, request_id: object) -> None:
        held = self._read(HANDOFF_FILE)
        if held is not None and held.get("request_id") == request_id:
            (self.root / HANDOFF_FILE).unlink(missing_ok=True)

    def mark_handoff_loaded(self, handoff: dict[str, object]) -> None:
        if handoff.get("target_configuration_id") is None or handoff.get("request_id") is None:
            raise ValueError("invalid switch handoff")
        self._write(RECEIPT_FILE, {"schema_version": 1,
                    "request_id": handoff["request_id"],
                    "target_configuration_id": handoff["target_configuration_id"],
                    "status": "applied", "message": None, "updated_at": time.time()})

    def mark_handoff_failed(self, handoff: dict[str, object], *, code: str) -> None:
        _token(code, "failure code")
        self._write(RECEIPT_FILE, {"schema_version": 1,
                    "request_id": handoff.get("request_id"),
                    "target_configuration_id": handoff.get("target_configuration_id"),
                    "status": "failed", "message": code, "updated_at": time.time()})

    def mark_pending_restart_failed(self, *, code: str) -> None:
        receipt = self.receipt()
        target = receipt.get("target_configuration_id") if isinstance(receipt, dict) else None
        handoff = self.handoff(target) if isinstance(target, str) else None
        if receipt and receipt.get("status") == "ready_for_restart" and handoff is not None:
            self.mark_handoff_failed(handoff, code=code)

    def remember_conversation(self, conversation_id: str, configuration_id: str) -> None:
        _token(conversation_id, "conversation_id")
        _token(configuration_id, "configuration_id")
        self._write(CONVERSATION_FILE, {"schema_version": 1, "conversation_id": conversation_id,
                    "configuration_id": configuration_id, "updated_at": time.time()})

    def conversation_id(self) -> str | None:
        value = self._read(CONVERSATION_FILE)
        if value is None or value.get("schema_version") != 1:
            return None
        try:
            return _token(value.get("conversation_id"), "conversation_id")
        except ValueError:
            return None

    def _read(self, name: str) -> dict[str, object] | None:
        path = self.root / name
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                return None
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _write(self, name: str, payload: dict[str, object]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / name
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        if len(raw.encode()) > _MAX_FILE_BYTES:
            raise ValueError("switch control payload is too large")
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(raw, encoding="utf-8")
        replace_with_retry(tmp, path)


def active_task_context(work: object, *, max_items: int = 8, max_chars: int = 4096) -> str:
    """Project bounded public Core work summaries for a replacement frontend."""
    if not isinstance(work, dict) or not isinstance(work.get("items"), list):
        return ""
    lines = []
    for item in work["items"]:
        if not isinstance(item, dict) or item.get("status") not in {"pending", "running", "blocked"}:
            continue
        label = item.get("label") or item.get("kind") or "travail"
        detail = item.get("summary") or item.get("activity") or item.get("status")
        line = f"- {label}: {detail} [{item.get('status')}]"
        if len(line) > 700 or sum(map(len, lines)) + len(line) > max_chars:
            continue
        lines.append(line)
        if len(lines) >= max_items:
            break
    return "Travaux JARVIS actifs (continuent dans Core):\n" + "\n".join(lines) if lines else ""


def prompt_transition_evidence(applications: object) -> list[dict[str, object]]:
    """Keep prompt identities/revisions for traces while excluding prompt text."""
    if not isinstance(applications, (list, tuple)):
        return []
    return [{"program_id": item.get("program_id"),
             "layer_revisions": item.get("layer_revisions"),
             "static_fingerprint": item.get("static_fingerprint"),
             "application": item.get("application")}
            for item in applications if isinstance(item, dict)]


class VoiceSwitchCoordinator:
    def __init__(self, *, voice, core, bus: VoiceSwitchBus, configuration_id: str,
                 architecture: str, model: str, journal=None) -> None:
        self.voice, self.core, self.bus = voice, core, bus
        self.configuration_id, self.architecture, self.model = configuration_id, architecture, model
        self.journal = journal
        self._retry_after = 0.0

    async def poll(self) -> bool:
        request = self.bus.read_request()
        if request is None:
            return False
        if time.monotonic() < self._retry_after:
            return False
        if request.target_configuration_id == self.configuration_id:
            self.bus.complete(request, status="applied")
            return False
        conversation_id = self.voice.runtime.conversation_id
        try:
            context = await self.core.context(conversation_id) if conversation_id else {}
            work = await self.core.work_snapshot()
        except Exception as exc:
            self._retry_after = time.monotonic() + 5.0
            self.bus.complete(request, status="failed",
                              message=f"Snapshot Core indisponible: {type(exc).__name__}",
                              remove_request=False)
            self._emit("voice.switch.snapshot_failed", "Authoritative switch snapshot failed",
                       {"request_id": request.request_id, "code": "voice_switch_snapshot_failed",
                        "exception_type": type(exc).__name__}, level="error")
            return False
        self._emit("voice.switch.snapshot", "Authoritative state captured before voice switch",
                   {"request_id": request.request_id, "conversation_id": conversation_id,
                    "recent_turn_count": len(context.get("recent_turns", [])),
                    "work_revision": work.get("revision")})
        try:
            await self.voice.mode_switch()
        except Exception as exc:
            self._retry_after = time.monotonic() + 5.0
            self.bus.complete(request, status="failed",
                              message=f"Échec de fermeture: {type(exc).__name__}",
                              remove_request=False)
            self._emit("voice.switch.failed", "Old voice frontend failed to stop",
                       {"request_id": request.request_id, "code": "voice_switch_stop_failed",
                        "exception_type": type(exc).__name__}, level="error")
            return False
        self._retry_after = 0.0
        try:
            unresolved = await self.core.live_session_status()
        except Exception as exc:
            self._retry_after = time.monotonic() + 5.0
            self.bus.complete(request, status="blocked",
                              message="État Live Core illisible après fermeture; remplacement bloqué.",
                              remove_request=False)
            self._emit("voice.switch.blocked", "Core Live state unreadable after frontend stop",
                       {"request_id": request.request_id, "code": "voice_switch_live_unknown",
                        "exception_type": type(exc).__name__}, level="warning")
            return False
        if unresolved is None and self.voice.switch_close_pending():
            if self.voice.accept_reaped_live_close():
                await self.voice.mode_switch()
        if unresolved is not None or self.voice.switch_close_pending():
            self.bus.complete(request, status="blocked",
                              message="Ancienne session non résolue; le remplacement reste bloqué.",
                              remove_request=False)
            self._emit("voice.switch.blocked", "Voice switch blocked by unresolved frontend",
                       {"request_id": request.request_id, "code": "voice_switch_close_unresolved"},
                       level="warning")
            return False
        self.bus.write_handoff(request, conversation_id=conversation_id, context=context, work=work,
                               source_architecture=self.architecture, source_model=self.model)
        self.bus.complete(request, status="ready_for_restart")
        self._emit("voice.switch.ready", "Voice switch ready for supervised restart",
                   {"request_id": request.request_id,
                    "source_configuration_id": self.configuration_id,
                    "target_configuration_id": request.target_configuration_id,
                    "source_architecture": self.architecture,
                    "target_architecture": request.target_architecture,
                    "source_model": self.model, "target_model": request.target_model})
        self.voice.request_switch_exit()
        return True

    def _emit(self, kind: str, message: str, data: dict[str, object], *, level: str = "info") -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=data)
