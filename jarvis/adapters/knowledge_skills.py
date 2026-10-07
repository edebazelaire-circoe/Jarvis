"""Skills as knowledge assets: versioned `SKILL.md` files, a local registry (Slice 09).

Root `<data_root>/knowledge/skills`. A skill is `<directory>/SKILL.md`: a front-matter
block (`id`, `version`, `description`, `scope`, `source`, optional `allowed_profiles`,
parsed by the memory front-matter parser) followed by the instructions. The directory
name is a hint; the identity is the front-matter `id`, so two directories may hold two
versions of one skill.

Enabled state is a sidecar file (`.skills-state.json`): a skill that was only copied in
is discovered but OFF until the user enables it. Version arbitration is pure
(`jarvis.domain.skills.arbitrate`): the highest enabled version wins, the others are
reported. Import is user-initiated only (`import_file`, `import_text`). There is no
autonomous extraction, no publication to other agents, and no execution: a skill is
text that a loadout names. Contract: `docs/skills-and-loadouts.md`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.adapters.memory_frontmatter import parse
from jarvis.adapters.safe_folders import is_link
from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.knowledge import AssetHit, AssetKind, AssetScope, KnowledgeAsset, SourceRef
from jarvis.domain.memory import (
    MAX_RECALL_ITEMS,
    MAX_SNIPPET_CHARS,
    CapabilityState,
    CapabilityStatus,
    MemoryErrorCode,
    MemoryStoreError,
    capability_ok,
)
from jarvis.domain.skills import (
    MAX_SKILL_BODY_CHARS,
    SkillCatalogView,
    SkillRecord,
    arbitrate,
    version_key,
)

_LOG = logging.getLogger(__name__)

SKILL_FILE = "SKILL.md"
STATE_FILE = ".skills-state.json"
#: Largest SKILL.md read (bytes); a UTF-8 body of `MAX_SKILL_BODY_CHARS` plus its block fits.
MAX_SKILL_BYTES = 4 * MAX_SKILL_BODY_CHARS + 8_192
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_TOKENS = re.compile(r"[^\W_]+", re.UNICODE)
_SCHEMA = 1


def _unavailable(message: str) -> MemoryStoreError:
    return MemoryStoreError(MemoryErrorCode.UNAVAILABLE, message)


def _not_found(skill_id: object) -> MemoryStoreError:
    return MemoryStoreError(MemoryErrorCode.NOT_FOUND, f"unknown skill {str(skill_id)[:80]!r}")


def _state_key(skill_id: str, version: str) -> str:
    return f"{skill_id}@{version}"


class _Parsed:
    """A validated SKILL.md: its record fields and its body."""

    __slots__ = ("record", "body")

    def __init__(self, record: SkillRecord, body: str) -> None:
        self.record = record
        self.body = body


def _parse_skill(text: str, directory: str) -> _Parsed:
    """Validate a SKILL.md. `ValueError` with the reason when it is not a usable skill."""

    block = parse(text)
    if block.corrupt:
        raise ValueError("front matter is corrupt (every line must be `key: <JSON value>`)")
    if not block.has_block:
        raise ValueError("front matter is missing")
    meta = block.meta
    missing = [name for name in ("id", "version", "description", "scope", "source") if name not in meta]
    if missing:
        raise ValueError(f"front matter lacks {', '.join(missing)}")
    for name in ("id", "version", "description", "scope", "source"):
        if not isinstance(meta[name], str):
            raise ValueError(f"{name} must be a JSON string")
    if not _ID.fullmatch(meta["id"]):
        raise ValueError("id must be a token (letters, digits, `_`, `.`, `-`)")
    try:
        scope = AssetScope(meta["scope"])
    except ValueError:
        raise ValueError("scope must be private, project or shared") from None
    profiles = meta.get("allowed_profiles", [])
    if not isinstance(profiles, list) or not all(isinstance(item, str) for item in profiles):
        raise ValueError("allowed_profiles must be a JSON array of strings")
    if not block.body.strip():
        raise ValueError("the skill has no instructions")
    if len(block.body) > MAX_SKILL_BODY_CHARS:
        raise ValueError("the skill body exceeds the size limit")
    try:
        record = SkillRecord(
            id=meta["id"], version=meta["version"], description=meta["description"].strip(), scope=scope,
            source=meta["source"].strip(), directory=directory, allowed_profiles=tuple(profiles),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)[:160]) from None
    return _Parsed(record, block.body.strip("\n"))


class SkillRegistry:
    """`KnowledgeAssetProvider` for skills, plus the discovery, enable and import lifecycle.

    Everything it lists, searches or reads is the arbitration winner of an enabled
    skill; a disabled skill, or a version that lost, is absent from those answers
    (it still shows in `catalog()`, which is the inspection view).
    """

    kind = AssetKind.SKILL

    def __init__(self, root: Path, clock: Callable[[], datetime] | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._state = self.root / STATE_FILE
        self._lock = threading.RLock()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _unavailable(f"skills root unusable: {exc.__class__.__name__}") from exc

    # ------------------------------------------------------------- discovery

    def catalog(self) -> SkillCatalogView:
        """Scan the root: every valid skill, the winners, the losers, the invalid ones. Never raises on content."""

        parsed, invalid = self._scan()
        enabled = self._enabled_keys()
        records = tuple(
            SkillRecord(
                id=p.record.id, version=p.record.version, description=p.record.description, scope=p.record.scope,
                source=p.record.source, directory=p.record.directory,
                allowed_profiles=p.record.allowed_profiles,
                enabled=_state_key(p.record.id, p.record.version) in enabled,
            )
            for p in parsed
        )
        winners, conflicts = arbitrate(records)
        return SkillCatalogView(records, winners, conflicts, tuple(invalid))

    def _scan(self) -> tuple[list[_Parsed], list[tuple[str, str]]]:
        parsed: list[_Parsed] = []
        invalid: list[tuple[str, str]] = []
        try:
            children = sorted(self.root.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            raise _unavailable(f"skills root unreadable: {exc.__class__.__name__}") from exc
        for child in children:
            if child.name.startswith("."):
                continue
            try:
                info = os.lstat(child)
            except OSError:
                continue
            if is_link(info):
                invalid.append((child.name, "skill directory is a symlink or junction"))
                continue
            if not child.is_dir():
                continue
            try:
                parsed.append(self._read_skill(child))
            except FileNotFoundError:
                continue  # a directory without SKILL.md is not a skill
            except (ValueError, OSError, UnicodeDecodeError) as exc:
                invalid.append((child.name, str(exc)[:160] or exc.__class__.__name__))
        return parsed, invalid

    def _read_skill(self, directory: Path) -> _Parsed:
        path = directory / SKILL_FILE
        info = os.lstat(path)  # FileNotFoundError: not a skill directory
        if is_link(info):
            raise ValueError("SKILL.md is a symlink or junction")
        with path.open("rb") as handle:
            data = handle.read(MAX_SKILL_BYTES + 1)
        if len(data) > MAX_SKILL_BYTES:
            raise ValueError("SKILL.md exceeds the size limit")
        return _parse_skill(data.decode("utf-8"), directory.name)

    def _winner_parsed(self, skill_id: str) -> _Parsed:
        view = self.catalog()
        winner = next((w for w in view.winners if w.id == skill_id), None)
        if winner is None:
            raise _not_found(skill_id)
        try:
            return self._read_skill(self.root / winner.directory)
        except (ValueError, OSError, UnicodeDecodeError) as exc:
            raise _unavailable(f"skill {skill_id} unreadable: {exc.__class__.__name__}") from exc

    # ------------------------------------------------------------------ port

    def status(self) -> CapabilityState:
        try:
            view = self.catalog()
        except MemoryStoreError as exc:
            return CapabilityState(CapabilityStatus.UNAVAILABLE, "skills_unavailable", exc.message[:200])
        if view.invalid:
            name, reason = view.invalid[0]
            return CapabilityState(
                CapabilityStatus.DEGRADED, "skills_invalid", f"{len(view.invalid)} invalid skill(s), first {name}: {reason}"[:300]
            )
        if view.conflicts:
            return CapabilityState(
                CapabilityStatus.DEGRADED, "skills_version_conflict", f"{len(view.conflicts)} version conflict(s) resolved by highest enabled version"
            )
        return capability_ok()

    def list(self, scope: AssetScope | None = None) -> tuple[KnowledgeAsset, ...]:
        view = self.catalog()
        found = [self._asset(r, body="") for r in view.winners if scope is None or r.scope is scope]
        return tuple(sorted(found, key=lambda a: a.asset_id))

    def search(self, query: str, limit: int, scope: AssetScope | None = None) -> Sequence[AssetHit]:
        limit = max(1, min(int(limit), MAX_RECALL_ITEMS))
        tokens = [t.lower() for t in _TOKENS.findall(query)[:12]]
        if not tokens:
            return []
        hits: list[AssetHit] = []
        for asset in self.list(scope):
            haystack = f"{asset.asset_id} {asset.summary}".lower()
            score = sum(haystack.count(token) for token in tokens)
            if score:
                hits.append(AssetHit(asset, asset.summary[:MAX_SNIPPET_CHARS], float(score)))
        hits.sort(key=lambda h: (-h.score, h.asset.asset_id))
        return hits[:limit]

    def read(self, asset_id: str, scope: AssetScope | None = None) -> KnowledgeAsset:
        """The winning enabled skill with its instructions. `scope` that differs from the skill's is denied."""

        if not isinstance(asset_id, str) or not _ID.fullmatch(asset_id):
            raise _not_found(asset_id)
        parsed = self._winner_parsed(asset_id)
        if scope is not None and parsed.record.scope is not scope:
            raise MemoryStoreError(MemoryErrorCode.SCOPE_DENIED, "skill is outside the requested scope")
        return self._asset(parsed.record, body=parsed.body)

    def rebuild(self) -> int:
        """No derived index exists: the files are the registry. Returns the effective skill count."""

        return len(self.catalog().winners)

    def _asset(self, record: SkillRecord, *, body: str) -> KnowledgeAsset:
        path = self.root / record.directory / SKILL_FILE
        try:
            fetched = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except OSError:
            fetched = self._clock()
        return KnowledgeAsset(
            asset_id=record.id, kind=AssetKind.SKILL, title=record.id, scope=record.scope,
            source=SourceRef(
                uri=record.source, version_or_commit=record.version, fetched_at=fetched,
                path=f"{record.directory}/{SKILL_FILE}",
            ),
            summary=record.description, body=body, version=record.version,
        )

    # ---------------------------------------------------------------- enable

    def enable(self, skill_id: str, version: str) -> None:
        self._set_enabled(skill_id, version, True)

    def disable(self, skill_id: str, version: str) -> None:
        self._set_enabled(skill_id, version, False)

    def _set_enabled(self, skill_id: str, version: str, enabled: bool) -> None:
        with self._lock:
            try:
                wanted = version_key(version)
            except ValueError:
                raise _not_found(f"{skill_id}@{version}") from None
            records = self.catalog().records
            if not any(r.id == skill_id and version_key(r.version) == wanted for r in records):
                raise _not_found(f"{skill_id}@{version}")
            # State is keyed by the version spelling the file declares, so `1` and `1.0` stay one switch.
            declared = next(r.version for r in records if r.id == skill_id and version_key(r.version) == wanted)
            keys = self._enabled_keys()
            (keys.add if enabled else keys.discard)(_state_key(skill_id, declared))
            self._write_state(keys)
        _LOG.info("skill %s@%s %s", skill_id, declared, "enabled" if enabled else "disabled")

    def _enabled_keys(self) -> set[str]:
        try:
            raw = json.loads(self._state.read_text(encoding="utf-8"))
            keys = raw["enabled"]
            if not isinstance(keys, list):
                raise TypeError("enabled")
            return {key for key in keys if isinstance(key, str)}
        except FileNotFoundError:
            return set()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Unreadable state means everything is off (deny by default), and it is said.
            _LOG.warning("skills state unreadable (%s): every skill is treated as disabled", exc.__class__.__name__)
            return set()

    def _write_state(self, keys: set[str]) -> None:
        payload: dict[str, Any] = {"schema": _SCHEMA, "enabled": sorted(keys)}
        self._atomic_write(self._state, json.dumps(payload, ensure_ascii=False, indent=1))

    # ---------------------------------------------------------------- import

    def import_file(self, path: Path | str, *, enable: bool = True) -> SkillRecord:
        """Import a SKILL.md the user names (a file, or a directory holding one). User-initiated only.

        Refused with `ValueError` when it is not a valid skill or that exact id and version are
        already imported; with `MemorySecurityError` when the path is, or goes through, a link.
        """

        raw = os.fspath(path)
        if "\x00" in raw:
            raise MemorySecurityError("skill source path is not valid")
        source = Path(os.path.abspath(raw))
        if source.is_dir() and not is_link(os.lstat(source)):
            source = source / SKILL_FILE
        try:
            info = os.lstat(source)
        except OSError as exc:
            raise ValueError(f"skill source unreadable: {exc.__class__.__name__}") from exc
        if is_link(info):
            raise MemorySecurityError("skill source is a symlink or junction")
        with source.open("rb") as handle:
            data = handle.read(MAX_SKILL_BYTES + 1)
        if len(data) > MAX_SKILL_BYTES:
            raise ValueError("skill source exceeds the size limit")
        return self.import_text(data.decode("utf-8"), enable=enable)

    def import_text(self, text: str, *, enable: bool = True) -> SkillRecord:
        """Import SKILL.md text the user holds. Validated first; nothing is written when it is invalid."""

        if not isinstance(text, str):
            raise TypeError("skill text must be a string")
        parsed = _parse_skill(text, "")
        skill_id, version = parsed.record.id, parsed.record.version
        with self._lock:
            existing = self.catalog().records
            wanted = version_key(version)
            if any(r.id == skill_id and version_key(r.version) == wanted for r in existing):
                raise ValueError(f"skill {skill_id}@{version} is already imported")
            directory = skill_id if not (self.root / skill_id).exists() else f"{skill_id}--v{version}"
            target = self.root / directory
            if target.exists():
                raise ValueError(f"directory {directory} already exists")
            try:
                target.mkdir()
            except OSError as exc:
                raise _unavailable(f"skill import failed: {exc.__class__.__name__}") from exc
            try:
                self._atomic_write(target / SKILL_FILE, text)
            except MemoryStoreError:
                try:
                    target.rmdir()
                except OSError:
                    pass
                raise
            if enable:
                keys = self._enabled_keys()
                keys.add(_state_key(skill_id, version))
                self._write_state(keys)
        _LOG.info("skill %s@%s imported into %s (enabled=%s)", skill_id, version, directory, enable)
        return SkillRecord(
            id=skill_id, version=version, description=parsed.record.description, scope=parsed.record.scope,
            source=parsed.record.source, directory=directory, allowed_profiles=parsed.record.allowed_profiles,
            enabled=enable,
        )

    def _atomic_write(self, target: Path, text: str) -> None:
        try:
            fd, tmp = tempfile.mkstemp(prefix=".skill-", suffix=".tmp", dir=str(target.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                replace_with_retry(Path(tmp), target)
            finally:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
        except OSError as exc:
            raise _unavailable(f"skill write failed: {exc.__class__.__name__}") from exc

