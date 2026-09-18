"""In-code registry of diagnostic implementations: `ProfileSpec.implementation` names resolve here.

Binding contract: `docs/testlab.md` ("Manifests"). Pure: no I/O, no clock, and above
all no dynamic import. A manifest carries a NAME; the factory that a name resolves to
is written in this module, reviewed like any other code. An unknown name fails the
catalog at load time, so a manifest can never point at arbitrary code.

A name that a later Slice will implement is RESERVED, not absent: the catalog then
describes that profile as `unavailable` with a reason, instead of hiding it. Slice 06
turns the virtual reservations into registrations, Slices 08 and 09 the others.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from jarvis.testlab.profiles import MAX_IMPLEMENTATION_CHARS, ProfileName
from jarvis.testlab.validation import (
    REFERENCE_INVALID,
    SIMPLE_NAME,
    check_enum,
    check_name,
    check_text,
    fail,
    name_for_message,
)

MAX_UNAVAILABLE_DETAIL_CHARS = 240
IMPLEMENTATION_UNKNOWN = "testlab_implementation_unknown"

#: What a registered name produces. The product type is the profile runner that Slices 05/06
#: define; the catalog only resolves the name and never calls the factory.
ImplementationFactory = Callable[[], Any]


class ImplementationAvailability(StrEnum):
    AVAILABLE = "available"
    #: The name is declared and reviewed, but no runner is registered yet.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ImplementationEntry:
    """One implementation name: the profile it runs, and either a factory or a reason it cannot run."""

    name: str
    profile: ProfileName
    factory: ImplementationFactory | None = None
    #: snake_case code, set exactly when there is no factory.
    unavailable_reason: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        check_name(self.name, "implementation.name", max_chars=MAX_IMPLEMENTATION_CHARS)
        check_enum(ProfileName, self.profile, f"implementation {self.name}.profile")
        if (self.factory is None) == (self.unavailable_reason is None):
            raise fail(f"implementation {self.name} declares either a factory or an unavailable reason")
        if self.factory is not None and not callable(self.factory):
            raise fail(f"implementation {self.name}.factory must be callable")
        check_name(self.unavailable_reason, f"implementation {self.name}.unavailable_reason", pattern=SIMPLE_NAME,
                   optional=True)
        check_text(self.detail, f"implementation {self.name}.detail", max_chars=MAX_UNAVAILABLE_DETAIL_CHARS,
                   optional=True)

    @property
    def availability(self) -> ImplementationAvailability:
        return (ImplementationAvailability.AVAILABLE if self.factory is not None
                else ImplementationAvailability.UNAVAILABLE)

    def to_dict(self) -> dict[str, Any]:
        """Introspection form: what the name is, never how it is implemented."""
        return {"implementation": self.name, "profile": self.profile.value, "availability": self.availability.value,
                "unavailable_reason": self.unavailable_reason, "detail": self.detail}


def registered(name: str, profile: ProfileName, factory: ImplementationFactory) -> ImplementationEntry:
    return ImplementationEntry(name, profile, factory=factory)


def reserved(name: str, profile: ProfileName, reason: str, detail: str) -> ImplementationEntry:
    """Declare a name a later Slice will implement; the catalog reports it `unavailable` with `reason`."""
    return ImplementationEntry(name, profile, unavailable_reason=reason, detail=detail)


class ImplementationRegistry:
    """Immutable name -> entry map. Registration happens in code (`default_implementations`)."""

    def __init__(self, entries: Iterable[ImplementationEntry]) -> None:
        indexed: dict[str, ImplementationEntry] = {}
        for entry in entries:
            if not isinstance(entry, ImplementationEntry):
                raise fail("an implementation registry holds ImplementationEntry values")
            if entry.name in indexed:
                raise fail(f"implementation {entry.name} is registered twice")
            indexed[entry.name] = entry
        self._entries = MappingProxyType(dict(sorted(indexed.items())))

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> Mapping[str, ImplementationEntry]:
        return self._entries

    def get(self, name: str) -> ImplementationEntry:
        entry = self._entries.get(name)
        if entry is None:
            raise fail(f"implementation {name_for_message(name)} is not registered", IMPLEMENTATION_UNKNOWN)
        return entry

    def resolve(self, name: str, profile: ProfileName) -> ImplementationEntry:
        """The entry for `name`, which must be declared for exactly this profile."""
        entry = self.get(name)
        if entry.profile is not profile:
            raise fail(f"implementation {entry.name} runs profile {entry.profile.value}, not {profile.value}",
                       REFERENCE_INVALID)
        return entry

    def with_entries(self, entries: Iterable[ImplementationEntry]) -> ImplementationRegistry:
        """A registry with more names (tests and later Slices compose; never mutates)."""
        return ImplementationRegistry((*self._entries.values(), *entries))

    def registering(self, entries: Iterable[ImplementationEntry]) -> ImplementationRegistry:
        """A registry where each entry REPLACES the reserved name it implements.

        This is how a Slice turns its reservations into runners (Slice 06 for `virtual`,
        08 and 09 for the others) without the declaration module importing the runner:
        the name, its profile and its review stay here; the factory comes from the
        profile's own package. Replacing anything but a reserved entry of the same
        profile is refused, so a registration can never silently take over another
        diagnostic's name or change the profile a manifest was checked against.
        """
        replacements: dict[str, ImplementationEntry] = {}
        for entry in entries:
            if entry.name in replacements:
                # Same rule as the constructor: a name given twice is a mistake, not a
                # last-one-wins precedence, and silently keeping one of two reviewed
                # factories is exactly the kind of accident this registry exists to stop.
                raise fail(f"implementation {entry.name} is registered twice")
            existing = self.get(entry.name)
            if existing.factory is not None:
                raise fail(f"implementation {entry.name} is already registered")
            if existing.profile is not entry.profile:
                raise fail(f"implementation {entry.name} is declared for profile {existing.profile.value}",
                           REFERENCE_INVALID)
            if entry.factory is None:
                raise fail(f"implementation {entry.name} must bring a factory to be registered")
            replacements[entry.name] = entry
        return ImplementationRegistry([replacements.get(name, entry) for name, entry in self._entries.items()])


#: Reason codes (closed, documented in docs/testlab.md).
RUNNER_NOT_REGISTERED = "runner_not_registered"

#: Every implementation name the official catalog may reference today. All are reserved:
#: Slice 04 ships declarations, not runners.
DEFAULT_IMPLEMENTATIONS: tuple[ImplementationEntry, ...] = (
    reserved("testlab.scenario.virtual", ProfileName.VIRTUAL, RUNNER_NOT_REGISTERED,
             "Generic scenario runner on the virtual conversation harness; Slice 06 registers it."),
    reserved("testlab.scenario.audio", ProfileName.AUDIO, RUNNER_NOT_REGISTERED,
             "Generic scenario runner on the real audio chain; Slice 08 registers it."),
    reserved("testlab.scenario.live", ProfileName.LIVE, RUNNER_NOT_REGISTERED,
             "Generic scenario runner against a real provider session; Slice 08 registers it."),
    reserved("testlab.scenario.hardware_auto", ProfileName.HARDWARE_AUTO, RUNNER_NOT_REGISTERED,
             "Generic scenario runner on workstation devices; Slice 09 registers it."),
    reserved("testlab.scenario.hardware_guided", ProfileName.HARDWARE_GUIDED, RUNNER_NOT_REGISTERED,
             "Generic scenario runner with the human as an actor; Slice 09 registers it."),
    reserved("voice.self_echo.virtual", ProfileName.VIRTUAL, RUNNER_NOT_REGISTERED,
             "Specialized self-echo runner; Slice 06 registers it, Slice 12 tunes it."),
    reserved("speech.payload_integrity.virtual", ProfileName.VIRTUAL, RUNNER_NOT_REGISTERED,
             "Compares scripted and delivered payloads in the harness; Slice 06 registers it."),
    reserved("speech.stale_supersession.virtual", ProfileName.VIRTUAL, RUNNER_NOT_REGISTERED,
             "Drives the stale/superseded speech scenario; Slice 06 registers it."),
    reserved("voice.queue_latency.virtual", ProfileName.VIRTUAL, RUNNER_NOT_REGISTERED,
             "Measures queue and speech-to-audio delays on virtual time; Slice 06 registers it."),
    reserved("voice.self_echo.audio", ProfileName.AUDIO, RUNNER_NOT_REGISTERED,
             "Self-echo over the real duplex capture and echo canceller; Slice 08 registers it."),
    reserved("voice.queue_latency.live", ProfileName.LIVE, RUNNER_NOT_REGISTERED,
             "Measures the real provider's own generation latency; Slice 08 registers it."),
    reserved("voice.self_echo.hardware_auto", ProfileName.HARDWARE_AUTO, RUNNER_NOT_REGISTERED,
             "Self-echo through the workstation's real speaker and microphone; Slice 09 registers it."),
    reserved("voice.self_echo.hardware_guided", ProfileName.HARDWARE_GUIDED, RUNNER_NOT_REGISTERED,
             "Self-echo with the human asked to stay silent, then to interrupt; Slice 09 registers it."),
)


def default_implementations() -> ImplementationRegistry:
    """The registry the official catalog loads with."""
    return ImplementationRegistry(DEFAULT_IMPLEMENTATIONS)
