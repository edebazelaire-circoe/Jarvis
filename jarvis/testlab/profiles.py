"""Test Lab execution profiles, capabilities, cost bounds and the permission check.

Binding contract: `docs/testlab.md` ("Profiles and permissions"). Pure: the
check compares declarations with a grant, it never probes a device or provider.
Detecting that a resource is actually available (and not held by the running
voice process) belongs to the runners (Slices 05, 08, 09).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from jarvis.testlab.validation import (
    FIELD_INVALID,
    check_enum,
    check_name,
    check_number,
    decode_enum,
    exact_fields,
    fail,
)

MAX_PROFILE_DURATION_S = 24 * 60 * 60
MAX_PROFILE_COST_USD = 1000
MAX_IMPLEMENTATION_CHARS = 96


class ProfileName(StrEnum):
    #: In-memory production path with controlled doubles. Free.
    VIRTUAL = "virtual"
    #: Real audio chain without physical acoustics or providers.
    AUDIO = "audio"
    #: Real provider session(s).
    LIVE = "live"
    #: Real workstation devices, no human action.
    HARDWARE_AUTO = "hardware:auto"
    #: Real workstation devices with the human as an explicit scenario actor.
    HARDWARE_GUIDED = "hardware:guided"


class Capability(StrEnum):
    """Scarce or costly resource a profile must be granted before it runs."""

    REALTIME_PROVIDER = "realtime_provider"
    LLM_PROVIDER = "llm_provider"
    AUDIO_INPUT_DEVICE = "audio_input_device"
    AUDIO_OUTPUT_DEVICE = "audio_output_device"
    HUMAN_PRESENCE = "human_presence"


PROVIDER_CAPABILITIES = frozenset({Capability.REALTIME_PROVIDER, Capability.LLM_PROVIDER})
DEVICE_CAPABILITIES = frozenset({Capability.AUDIO_INPUT_DEVICE, Capability.AUDIO_OUTPUT_DEVICE})


def _capabilities(values: object, name: str) -> frozenset[Capability]:
    if not isinstance(values, frozenset):
        raise fail(f"{name} must be a frozenset of capabilities")
    for value in values:
        check_enum(Capability, value, f"{name}[]")
    return values


def _decode_capabilities(values: object, name: str) -> frozenset[Capability]:
    if not isinstance(values, list):
        raise fail(f"{name} must be a list of capabilities")
    decoded = [decode_enum(Capability, value, f"{name}[{index}]") for index, value in enumerate(values)]
    if len(set(decoded)) != len(decoded):
        raise fail(f"{name} must not repeat a capability")
    return frozenset(decoded)


def _encode_capabilities(values: Iterable[Capability]) -> list[str]:
    return sorted(value.value for value in values)


@dataclass(frozen=True, slots=True)
class CostBounds:
    """Declared upper bounds of one run on this profile (estimates the gate compares to a grant)."""

    max_duration_s: float
    max_cost_usd: float

    def __post_init__(self) -> None:
        check_number(self.max_duration_s, "cost.max_duration_s", minimum=0, maximum=MAX_PROFILE_DURATION_S)
        if self.max_duration_s == 0:
            raise fail("cost.max_duration_s must be > 0")
        check_number(self.max_cost_usd, "cost.max_cost_usd", minimum=0, maximum=MAX_PROFILE_COST_USD)

    def to_dict(self) -> dict[str, Any]:
        return {"max_duration_s": self.max_duration_s, "max_cost_usd": self.max_cost_usd}

    @classmethod
    def from_dict(cls, payload: object) -> CostBounds:
        data = exact_fields(payload, _COST_FIELDS, "cost")
        return cls(data["max_duration_s"], data["max_cost_usd"])


_COST_FIELDS = frozenset({"max_duration_s", "max_cost_usd"})


def _check_profile_rules(name: ProfileName, requires: frozenset[Capability], cost: CostBounds) -> None:
    """Minimal requirements implied by each profile name (locked decisions 6, 11, 14)."""
    where = f"profile {name.value}"
    if name is ProfileName.VIRTUAL:
        if requires or cost.max_cost_usd != 0:
            raise fail(f"{where} must require no capability and cost nothing")
        return
    if Capability.HUMAN_PRESENCE in requires and name is not ProfileName.HARDWARE_GUIDED:
        raise fail(f"{where}: only hardware:guided may require human_presence")
    if name is ProfileName.AUDIO and requires & PROVIDER_CAPABILITIES:
        raise fail(f"{where} must not require a provider (use live)")
    if name is ProfileName.LIVE and not requires & PROVIDER_CAPABILITIES:
        raise fail(f"{where} must require at least one provider capability")
    if name in (ProfileName.HARDWARE_AUTO, ProfileName.HARDWARE_GUIDED) and not requires & DEVICE_CAPABILITIES:
        raise fail(f"{where} must require at least one audio device capability")
    if name is ProfileName.HARDWARE_GUIDED and Capability.HUMAN_PRESENCE not in requires:
        raise fail(f"{where} must require human_presence")


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """How one diagnostic runs on one profile: registered implementation, needs and cost."""

    name: ProfileName
    #: Registered implementation name (dotted lowercase), resolved by the catalog. Never code.
    implementation: str
    cost: CostBounds
    requires: frozenset[Capability] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        check_enum(ProfileName, self.name, "profile.name")
        check_name(self.implementation, "profile.implementation", max_chars=MAX_IMPLEMENTATION_CHARS)
        if not isinstance(self.cost, CostBounds):
            raise fail("profile.cost must be CostBounds")
        _capabilities(self.requires, "profile.requires")
        _check_profile_rules(self.name, self.requires, self.cost)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name.value, "implementation": self.implementation,
                "requires": _encode_capabilities(self.requires), "cost": self.cost.to_dict()}

    @classmethod
    def from_dict(cls, payload: object) -> ProfileSpec:
        data = exact_fields(payload, _PROFILE_FIELDS, "profile")
        return cls(decode_enum(ProfileName, data["name"], "profile.name"), data["implementation"],
                   CostBounds.from_dict(data["cost"]), _decode_capabilities(data["requires"], "profile.requires"))


_PROFILE_FIELDS = frozenset({"name", "implementation", "requires", "cost"})


# ------------------------------------------------------------- permission

@dataclass(frozen=True, slots=True)
class ResourceGrant:
    """What the caller authorizes for one run. The default grant allows only free, capability-less work."""

    capabilities: frozenset[Capability] = field(default_factory=frozenset)
    max_cost_usd: float = 0
    #: None: no duration budget. A number bounds the declared `max_duration_s`.
    max_duration_s: float | None = None

    def __post_init__(self) -> None:
        _capabilities(self.capabilities, "grant.capabilities")
        check_number(self.max_cost_usd, "grant.max_cost_usd", minimum=0, maximum=MAX_PROFILE_COST_USD)
        if self.max_duration_s is not None:
            check_number(self.max_duration_s, "grant.max_duration_s", minimum=0, maximum=MAX_PROFILE_DURATION_S)

    def to_dict(self) -> dict[str, Any]:
        return {"capabilities": _encode_capabilities(self.capabilities), "max_cost_usd": self.max_cost_usd,
                "max_duration_s": self.max_duration_s}

    @classmethod
    def from_dict(cls, payload: object) -> ResourceGrant:
        data = exact_fields(payload, _GRANT_FIELDS, "grant")
        return cls(_decode_capabilities(data["capabilities"], "grant.capabilities"), data["max_cost_usd"],
                   data["max_duration_s"])


_GRANT_FIELDS = frozenset({"capabilities", "max_cost_usd", "max_duration_s"})


class DenialReason(StrEnum):
    CAPABILITY_MISSING = "capability_missing"
    COST_BUDGET_EXCEEDED = "cost_budget_exceeded"
    DURATION_BUDGET_EXCEEDED = "duration_budget_exceeded"


@dataclass(frozen=True, slots=True)
class PermissionDenial:
    reason: DenialReason
    #: Set for `capability_missing` only.
    capability: Capability | None = None
    #: Declared bound and granted budget, set for the budget reasons only.
    required: float | None = None
    granted: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason.value, "capability": None if self.capability is None else self.capability.value,
                "required": self.required, "granted": self.granted}


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    profile: ProfileName
    denials: tuple[PermissionDenial, ...] = ()

    @property
    def allowed(self) -> bool:
        return not self.denials

    def to_dict(self) -> dict[str, Any]:
        return {"profile": self.profile.value, "allowed": self.allowed,
                "denials": [denial.to_dict() for denial in self.denials]}


def check_profile_permission(profile: ProfileSpec, grant: ResourceGrant) -> PermissionDecision:
    """Mechanical gate: every required capability granted and every declared bound within budget.

    Returns every denial at once (capabilities in vocabulary order, then cost,
    then duration) so a caller can show everything that is missing.
    """
    if not isinstance(profile, ProfileSpec) or not isinstance(grant, ResourceGrant):
        raise fail("check_profile_permission takes a ProfileSpec and a ResourceGrant", FIELD_INVALID)
    denials = [PermissionDenial(DenialReason.CAPABILITY_MISSING, capability=capability)
               for capability in Capability if capability in profile.requires and capability not in grant.capabilities]
    if profile.cost.max_cost_usd > grant.max_cost_usd:
        denials.append(PermissionDenial(DenialReason.COST_BUDGET_EXCEEDED, required=profile.cost.max_cost_usd,
                                        granted=grant.max_cost_usd))
    if grant.max_duration_s is not None and profile.cost.max_duration_s > grant.max_duration_s:
        denials.append(PermissionDenial(DenialReason.DURATION_BUDGET_EXCEEDED, required=profile.cost.max_duration_s,
                                        granted=grant.max_duration_s))
    return PermissionDecision(profile.name, tuple(denials))


def profiles_by_name(profiles: Iterable[ProfileSpec]) -> Mapping[ProfileName, ProfileSpec]:
    """Index profiles by name, rejecting duplicates."""
    indexed: dict[ProfileName, ProfileSpec] = {}
    for profile in profiles:
        if not isinstance(profile, ProfileSpec):
            raise fail("profiles must contain ProfileSpec values")
        if profile.name in indexed:
            raise fail(f"profile {profile.name.value} is declared twice")
        indexed[profile.name] = profile
    return indexed
