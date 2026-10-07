"""Skill records and version conflicts, pure (Slice 09).

A skill is a versioned, reusable instruction file (`SKILL.md`), delivered to an
agent as text and never executed. This module only says what a valid skill is
and how two versions of the same id are arbitrated: the highest ENABLED version
wins and every other enabled version is reported as the loser. Disk, state and
import live in `jarvis/adapters/knowledge_skills.py`. Contract page:
`docs/skills-and-loadouts.md`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re

from jarvis.domain._checks import check_text, check_token
from jarvis.domain.knowledge import MAX_LOADOUT_ENTRIES, AssetScope
from jarvis.domain.memory import MAX_REF_CHARS, MAX_REASON_CHARS, check_bool, check_enum

#: Numeric dotted version, one to four parts: `1`, `2.1`, `1.4.2`. ASCII digits only: `\d` also matches other scripts' digits. Anything else is invalid.
SKILL_VERSION = re.compile(r"[0-9]{1,6}(\.[0-9]{1,6}){0,3}\Z", re.ASCII)
MAX_SKILL_DESCRIPTION_CHARS = 300
MAX_SKILL_BODY_CHARS = 64_000

#: Why a skill lost to another version of the same id.
CONFLICT_LOWER_VERSION = "lower_version"
CONFLICT_DUPLICATE = "duplicate_version"


def version_key(version: str) -> tuple[int, ...]:
    """Sort key of a valid skill version (numeric, so `10` > `9`; `1` equals `1.0`). `ValueError` when invalid."""

    if not isinstance(version, str) or not SKILL_VERSION.fullmatch(version):
        raise ValueError("version must be dotted numbers such as 1 or 2.1.0")
    parts = [int(part) for part in version.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


@dataclass(frozen=True, slots=True)
class SkillRecord:
    """One `SKILL.md` as discovered. `directory` is where it lives under the skills root."""

    id: str
    version: str
    description: str
    scope: AssetScope
    source: str
    directory: str
    allowed_profiles: tuple[str, ...] = ()
    enabled: bool = False

    def __post_init__(self) -> None:
        check_token("id", self.id, 128, required=True)
        version_key(self.version)
        check_text("description", self.description, MAX_SKILL_DESCRIPTION_CHARS)
        if not self.description.strip():
            raise ValueError("description is required")
        check_enum("scope", self.scope, AssetScope)
        check_text("source", self.source, MAX_REF_CHARS)
        if not self.source.strip():
            raise ValueError("source is required")
        check_text("directory", self.directory, 160)
        if isinstance(self.allowed_profiles, (str, bytes)) or not isinstance(self.allowed_profiles, Iterable):
            raise TypeError("allowed_profiles must be a sequence")
        profiles = tuple(self.allowed_profiles)
        if len(profiles) > MAX_LOADOUT_ENTRIES:
            raise ValueError(f"allowed_profiles holds at most {MAX_LOADOUT_ENTRIES} entries")
        for entry in profiles:
            check_token("allowed_profiles", entry, 32, required=True)
        if len(set(profiles)) != len(profiles):
            raise ValueError("allowed_profiles must not repeat an entry")
        object.__setattr__(self, "allowed_profiles", profiles)
        check_bool("enabled", self.enabled)

    def allows(self, profile: str, role: str | None) -> bool:
        """Empty `allowed_profiles` means every profile; otherwise the profile or the role must be listed."""

        if not self.allowed_profiles:
            return True
        return profile in self.allowed_profiles or (role is not None and role in self.allowed_profiles)


@dataclass(frozen=True, slots=True)
class SkillConflict:
    """Two enabled records of one id: `loser_version` (in `loser_directory`) lost to `winner_version`."""

    skill_id: str
    winner_version: str
    loser_version: str
    loser_directory: str
    reason: str

    def __post_init__(self) -> None:
        check_token("skill_id", self.skill_id, 128, required=True)
        version_key(self.winner_version)
        version_key(self.loser_version)
        check_text("loser_directory", self.loser_directory, 160)
        check_text("reason", self.reason, MAX_REASON_CHARS)

    def as_dict(self) -> dict[str, str]:
        return {
            "skill_id": self.skill_id, "winner_version": self.winner_version,
            "loser_version": self.loser_version, "loser_directory": self.loser_directory,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SkillCatalogView:
    """What discovery found. `records` is everything valid, enabled or not; `winners` is
    one record per id (the highest enabled version); `invalid` is `(directory, reason)`."""

    records: tuple[SkillRecord, ...] = ()
    winners: tuple[SkillRecord, ...] = ()
    conflicts: tuple[SkillConflict, ...] = ()
    invalid: tuple[tuple[str, str], ...] = ()


def arbitrate(records: Iterable[SkillRecord]) -> tuple[tuple[SkillRecord, ...], tuple[SkillConflict, ...]]:
    """Pick the winner of each id among the ENABLED records; report each enabled loser.

    Highest numeric version wins. Two enabled records with the same id and version are
    a duplicate: the first directory in name order wins, the other is reported.
    Disabled records never win and are not conflicts (they are simply off).
    """

    by_id: dict[str, list[SkillRecord]] = {}
    for record in records:
        if record.enabled:
            by_id.setdefault(record.id, []).append(record)
    winners: list[SkillRecord] = []
    conflicts: list[SkillConflict] = []
    for skill_id in sorted(by_id):
        # Stable sorts: directory name first, then highest version first (ties keep name order).
        ranked = sorted(sorted(by_id[skill_id], key=lambda r: r.directory),
                        key=lambda r: version_key(r.version), reverse=True)
        winner = ranked[0]
        winners.append(winner)
        for loser in ranked[1:]:
            same = version_key(loser.version) == version_key(winner.version)
            conflicts.append(SkillConflict(
                skill_id, winner.version, loser.version, loser.directory,
                CONFLICT_DUPLICATE if same else CONFLICT_LOWER_VERSION,
            ))
    return tuple(winners), tuple(conflicts)
