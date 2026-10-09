"""File-backed candidate store: Markdown proposals under `<memory>/_candidates/` (Slice 04).

One human-readable file per candidate, `<id>.md`, in the memory note format
(front-matter block, then `# Title` and the body), so the Memory Center and a
human with a text editor read the same thing. The directory starts with `_`:
the canonical store never indexes or recalls it.

    _candidates/<id>.md                  the proposal and its state
    _candidates/.runs/<evidence hash>.json   run marker (idempotence)
    _candidates/.intents/<id>.json           decision intent (crash recovery)

No SQLite table and no migration (architecture D6). Writes are atomic
(temp file, fsync, replace) and refuse a path with a symlink or junction in
its chain, like the canonical store. A file that cannot be read as a candidate
is skipped with a warning: one hand-broken file never blocks the queue.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

from jarvis.adapters import memory_frontmatter
from jarvis.adapters.file_replace import replace_with_retry
from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.memory import (
    Candidate,
    CandidateDecision,
    CandidateState,
    MemoryErrorCode,
    MemoryKind,
    MemoryLevel,
    MemoryStoreError,
    Provenance,
    RetentionClass,
    SourceType,
)
from jarvis.ports.memory_candidates import DecisionIntent

_LOG = logging.getLogger("jarvis")

CANDIDATES_DIR = "_candidates"
RUNS_DIR = ".runs"
INTENTS_DIR = ".intents"
#: A candidate file larger than this is not a candidate (hostile or broken): skipped.
MAX_FILE_BYTES = 512_000
_ID = re.compile(r"[A-Za-z0-9]{1,64}\Z")
_HASH = re.compile(r"[A-Za-z0-9]{8,128}\Z")


class FileCandidateStore:
    def __init__(self, memory_root: Path) -> None:
        self.memory_root = Path(memory_root).expanduser().resolve()
        self.root = self.memory_root / CANDIDATES_DIR
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ port
    def save(self, candidate: Candidate) -> Candidate:
        if not isinstance(candidate, Candidate):
            raise TypeError("candidate must be a Candidate")
        text = self._render(candidate)
        with self._lock:
            self._write(self._candidate_path(candidate.id), text)
        return candidate

    def get(self, candidate_id: str) -> Candidate:
        path = self._candidate_path(candidate_id)
        candidate = self._read(path) if path.is_file() and not path.is_symlink() else None
        if candidate is None or candidate.id != candidate_id:
            raise MemoryStoreError(MemoryErrorCode.NOT_FOUND, f"no candidate {candidate_id}")
        return candidate

    def list(self, state: CandidateState | None = None, limit: int = 500) -> Sequence[Candidate]:
        found: list[Candidate] = []
        directory = self.root
        if not directory.is_dir() or directory.is_symlink():
            return ()
        for path in sorted(directory.glob("*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            candidate = self._read(path)
            if candidate is None or candidate.id != path.stem:
                continue
            if state is None or candidate.state is state:
                found.append(candidate)
        found.sort(key=lambda item: (item.created_at, item.id))
        return tuple(found[:max(0, limit)])

    def mark_run(self, evidence_hash: str, candidate_ids: Sequence[str]) -> None:
        self._check_hash(evidence_hash)
        payload = {"evidence_hash": evidence_hash, "candidate_ids": list(candidate_ids)}
        with self._lock:
            self._write(self._side_path(RUNS_DIR, evidence_hash), json.dumps(payload, ensure_ascii=False))

    def run_candidates(self, evidence_hash: str) -> tuple[str, ...] | None:
        self._check_hash(evidence_hash)
        payload = self._read_json(self._side_path(RUNS_DIR, evidence_hash))
        if payload is None:
            return None
        ids = payload.get("candidate_ids")
        if not isinstance(ids, list) or not all(isinstance(item, str) and _ID.fullmatch(item) for item in ids):
            return None  # unreadable marker: treated as never processed, dedup absorbs the replay
        return tuple(ids)

    def begin_decision(self, intent: DecisionIntent) -> None:
        self._check_id(intent.candidate_id)
        payload = {
            "candidate_id": intent.candidate_id, "decision": intent.decision.value,
            "actor": intent.actor, "at": intent.at.isoformat(),
        }
        with self._lock:
            self._write(self._side_path(INTENTS_DIR, intent.candidate_id), json.dumps(payload))

    def end_decision(self, candidate_id: str) -> None:
        self._check_id(candidate_id)
        path = self._side_path(INTENTS_DIR, candidate_id)
        with self._lock:
            try:
                path.unlink()
            except FileNotFoundError:
                pass  # intentional: ending an intent twice (a recovery re-run) is normal
            except OSError as exc:
                # A leftover intent is harmless (recovery only acts on a still-proposed candidate).
                _LOG.warning("candidate intent %s not removed: %s", candidate_id, exc)

    def pending_decisions(self) -> Sequence[DecisionIntent]:
        directory = self.root / INTENTS_DIR
        if not directory.is_dir() or directory.is_symlink():
            return ()
        intents: list[DecisionIntent] = []
        for path in sorted(directory.glob("*.json")):
            payload = self._read_json(path)
            try:
                if payload is None:
                    raise ValueError("unreadable")
                intents.append(DecisionIntent(
                    candidate_id=str(payload["candidate_id"]),
                    decision=CandidateDecision(payload["decision"]),
                    actor=str(payload["actor"]),
                    at=datetime.fromisoformat(str(payload["at"])),
                ))
            except (KeyError, ValueError, TypeError):
                _LOG.warning("candidate intent file skipped: %s", path.name)
        return tuple(intents)

    # ------------------------------------------------------------ file format
    @staticmethod
    def _render(candidate: Candidate) -> str:
        meta: dict[str, Any] = {
            "id": candidate.id, "state": candidate.state.value, "level": candidate.level.value,
            "kind": candidate.kind.value, "retention": candidate.retention.value, "scope": candidate.scope,
            "confidence": candidate.confidence, "evidence_hash": candidate.evidence_hash,
            "created_at": candidate.created_at.isoformat(),
            "sources": [{"type": s.type.value, "ref": s.ref, "at": s.at.isoformat()} for s in candidate.sources],
        }
        if candidate.conflicts:
            meta["conflicts"] = list(candidate.conflicts)
        if candidate.decided_at is not None:
            meta["decided_at"] = candidate.decided_at.isoformat()
        if candidate.decided_by is not None:
            meta["decided_by"] = candidate.decided_by
        if candidate.committed_memory_id is not None:
            meta["committed_memory_id"] = candidate.committed_memory_id
        body = candidate.body.strip("\n")
        return memory_frontmatter.compose(meta, f"# {candidate.title.strip()}\n" + (f"\n{body}\n" if body else ""))

    def _read(self, path: Path) -> Candidate | None:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("candidate file too large")
            parsed = memory_frontmatter.parse(path.read_text(encoding="utf-8"))
            if not parsed.has_block:
                raise ValueError("no metadata block")
            meta = parsed.meta
            title, body = _split_title(parsed.body.replace("\r\n", "\n"))

            def moment(name: str, *, required: bool = True) -> datetime | None:
                value = meta.get(name)
                if value is None and not required:
                    return None
                if not isinstance(value, str):
                    raise TypeError(f"{name} must be an ISO string")
                return datetime.fromisoformat(value)

            return Candidate(
                id=meta["id"], title=title, body=body, level=MemoryLevel(meta["level"]),
                kind=MemoryKind(meta["kind"]), retention=RetentionClass(meta["retention"]), scope=meta["scope"],
                confidence=meta["confidence"], evidence_hash=meta["evidence_hash"],
                created_at=moment("created_at"), state=CandidateState(meta["state"]),
                sources=tuple(
                    Provenance(SourceType(item["type"]), item["ref"], datetime.fromisoformat(item["at"]))
                    for item in meta.get("sources", ())
                ),
                conflicts=tuple(meta.get("conflicts", ())),
                decided_at=moment("decided_at", required=False), decided_by=meta.get("decided_by"),
                committed_memory_id=meta.get("committed_memory_id"),
            )
        except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError) as exc:
            # A hand-edited or damaged file is skipped, never raised: the queue keeps working.
            _LOG.warning("memory candidate file skipped: %s: %s: %s", path.name, type(exc).__name__, exc)
            return None

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, RecursionError):
            return None  # intentional: a missing or damaged side file is the same as no side file
        return payload if isinstance(payload, dict) else None

    # ------------------------------------------------------------------ paths
    @staticmethod
    def _check_id(candidate_id: str) -> None:
        if not isinstance(candidate_id, str) or not _ID.fullmatch(candidate_id):
            raise MemorySecurityError("candidate id is not a token")

    @staticmethod
    def _check_hash(value: str) -> None:
        if not isinstance(value, str) or not _HASH.fullmatch(value):
            raise MemorySecurityError("evidence hash is not a token")

    def _candidate_path(self, candidate_id: str) -> Path:
        self._check_id(candidate_id)
        return self.root / f"{candidate_id}.md"

    def _side_path(self, kind: str, name: str) -> Path:
        if kind == INTENTS_DIR:
            self._check_id(name)
        else:
            self._check_hash(name)
        return self.root / kind / f"{name}.json"

    def _assert_plain_chain(self, path: Path) -> None:
        expected = os.path.normcase(os.path.abspath(path))
        if os.path.normcase(os.path.realpath(path)) != expected:
            raise MemorySecurityError("candidate path crosses a link")

    def _write(self, target: Path, text: str) -> None:
        """Atomic write under `_candidates/`; refuses a link anywhere in the chain."""

        directory = target.parent
        try:
            self._assert_plain_chain(directory)
            directory.mkdir(parents=True, exist_ok=True)
            self._assert_plain_chain(directory)
            fd, tmp_name = tempfile.mkstemp(prefix=".jarvis-cand-", suffix=".tmp", dir=str(directory))
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                replace_with_retry(tmp, target)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
        except (OSError, UnicodeEncodeError) as exc:
            raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, f"candidate not written: {exc}") from exc


def _split_title(text: str) -> tuple[str, str]:
    lines = text.split("\n")
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None or not lines[first].startswith("# ") or not lines[first][2:].strip():
        raise ValueError("a candidate starts with a '# Title' line")
    return lines[first][2:].strip(), "\n".join(lines[first + 1:]).strip("\n")
