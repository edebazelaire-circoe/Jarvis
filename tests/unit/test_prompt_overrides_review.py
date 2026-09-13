"""Independent Task15A review of bounded prompt override persistence.

These tests exercise only pure registry resolution and an in-memory settings
writer.  They never create a provider session or materialize prompt defaults.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from jarvis.domain.prompt_registry import (
    MAX_OVERRIDE_ENTRIES,
    MAX_OVERRIDE_TEXT,
    PromptDescriptor,
    PromptError,
    PromptProgram,
    PromptRegistry,
    PromptStep,
    PromptTarget,
    decode_prompt_overrides,
)
from jarvis.runtime.prompt_overrides import PROMPT_OVERRIDES_SETTING, PromptOverrideStore


class AtomicSettings:
    def __init__(self, value: dict | None = None) -> None:
        self.value = deepcopy(value or {})
        self.writes: list[dict] = []
        self.fail = False

    def read(self) -> dict:
        return deepcopy(self.value)

    def write(self, value: dict) -> None:
        if self.fail:
            raise OSError("simulated atomic replace failure")
        copied = deepcopy(value)
        self.writes.append(copied)
        self.value = copied


class Diagnostics:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, channel, message, *, level="info", data=None) -> None:  # noqa: ANN001
        self.events.append({"channel": channel, "message": message, "level": level, "data": deepcopy(data)})


@pytest.fixture
def registry() -> PromptRegistry:
    descriptors = (
        PromptDescriptor(
            "review.editable",
            __file__,
            "registry",
            "Answer the request: {request}",
            editable=True,
            variables=("request",),
        ),
        PromptDescriptor("review.read_only", __file__, "registry", "Enforced runtime invariant"),
        # Registered but absent from the active program: its override must survive
        # edits made while this mode/model is inactive.
        PromptDescriptor("review.inactive", __file__, "registry", "Inactive default", editable=True),
    )
    program = PromptProgram(
        "review.program",
        PromptTarget("conversation", "simple", "openai", "review-model"),
        (
            PromptStep("review.read_only", "session.instructions", separator="\n"),
            PromptStep("review.editable", "session.instructions", separator="\n"),
        ),
    )
    return PromptRegistry(descriptors, (program,))


def envelope(entries: dict) -> dict:
    return {"schema_version": 1, "overrides": deepcopy(entries)}


@pytest.mark.parametrize(
    ("document", "code"),
    [
        (None, "prompt_override_schema_invalid"),
        ({}, "prompt_override_schema_invalid"),
        ({"schema_version": 1, "overrides": {}, "future": True}, "prompt_override_schema_invalid"),
        ({"schema_version": True, "overrides": {}}, "prompt_override_version_unsupported"),
        ({"schema_version": 2, "overrides": {}}, "prompt_override_version_unsupported"),
        ({"schema_version": 1, "overrides": []}, "prompt_override_bound"),
        (envelope({"bad id!": {"base_revision": "0" * 64, "text": "x"}}), "prompt_id_invalid"),
        (envelope({"review.editable": {"base_revision": "token", "text": "x"}}), "prompt_revision_invalid"),
    ],
)
def test_codec_rejects_wrong_shapes_versions_and_types(document, code):  # noqa: ANN001
    with pytest.raises(PromptError) as failure:
        decode_prompt_overrides(document)
    assert failure.value.code == code


def test_codec_rejects_unknown_fields_bounds_and_non_text_values(registry):
    revision = registry.require("review.editable").default_revision
    invalid_documents = (
        envelope({"review.editable": {"base_revision": revision, "text": "x", "extra": False}}),
        envelope({"review.editable": {"base_revision": revision, "text": True}}),
        envelope({"review.editable": {"base_revision": revision, "text": "x\x00y"}}),
        envelope({"review.editable": {"base_revision": revision, "text": "x" * (MAX_OVERRIDE_TEXT + 1)}}),
        envelope({f"future.{index}": {"base_revision": "0" * 64, "text": "x"}
                  for index in range(MAX_OVERRIDE_ENTRIES + 1)}),
    )
    for document in invalid_documents:
        with pytest.raises(PromptError):
            decode_prompt_overrides(document)


def test_codec_returns_a_detached_copy(registry):
    revision = registry.require("review.editable").default_revision
    document = envelope({"review.editable": {"base_revision": revision, "text": "Changed {request}"}})
    decoded = decode_prompt_overrides(document)
    decoded["review.editable"]["text"] = "mutated"
    assert document["overrides"]["review.editable"]["text"] == "Changed {request}"


@pytest.mark.parametrize(
    ("identifier", "text", "expected_code"),
    [
        ("review.read_only", "changed", "prompt_read_only"),
        ("review.unknown", "changed", "prompt_unknown"),
        ("review.editable", "missing required slot", "prompt_placeholder_invalid"),
        ("review.editable", "{request} and {request}", "prompt_placeholder_invalid"),
        ("review.editable", "{request!r}", "prompt_placeholder_invalid"),
        ("review.editable", "{request:>4}", "prompt_placeholder_invalid"),
        ("review.editable", "{unknown}", "prompt_placeholder_invalid"),
        ("review.editable", True, "prompt_text_invalid"),
    ],
)
def test_edit_accepts_only_editable_descriptors_and_preserves_template_invariants(
    registry, identifier, text, expected_code
):
    settings = AtomicSettings({"unrelated": {"keep": True}})
    store = PromptOverrideStore(registry, read_settings=settings.read, write_settings=settings.write)
    revision = registry.require("review.editable").default_revision
    with pytest.raises(PromptError) as failure:
        store.edit(identifier, text=text, base_revision=revision)
    assert failure.value.code == expected_code
    assert settings.value == {"unrelated": {"keep": True}}
    assert settings.writes == []


def test_edit_and_reset_preserve_unrelated_inactive_and_unknown_entries(registry):
    active = registry.require("review.editable")
    inactive = registry.require("review.inactive")
    original = {
        "unrelated": {"nested": [1, 2, 3]},
        PROMPT_OVERRIDES_SETTING: envelope({
            "review.editable": {"base_revision": active.default_revision, "text": "Old {request}"},
            "review.inactive": {"base_revision": inactive.default_revision, "text": "Inactive custom"},
            "future.layer": {"base_revision": "f" * 64, "text": "Preserve future value"},
        }),
    }
    settings = AtomicSettings(original)
    store = PromptOverrideStore(registry, read_settings=settings.read, write_settings=settings.write)

    edited = store.edit("review.editable", text="New {request}", base_revision=active.default_revision)
    assert edited["changed"] is True
    assert settings.value["unrelated"] == original["unrelated"]
    assert settings.value[PROMPT_OVERRIDES_SETTING]["overrides"]["review.inactive"]["text"] == "Inactive custom"
    assert settings.value[PROMPT_OVERRIDES_SETTING]["overrides"]["future.layer"]["text"] == "Preserve future value"

    reset = store.reset("review.editable")
    assert reset["changed"] is True
    remaining = settings.value[PROMPT_OVERRIDES_SETTING]["overrides"]
    assert set(remaining) == {"review.inactive", "future.layer"}
    inspected = store.inspect()
    assert inspected["unknown_overrides"] == {
        "future.layer": {"base_revision": "f" * 64, "text": "Preserve future value"}
    }


def test_absence_means_default_and_default_edit_or_reset_is_a_noop(registry):
    settings = AtomicSettings({"unrelated": "kept"})
    store = PromptOverrideStore(registry, read_settings=settings.read, write_settings=settings.write)
    descriptor = registry.require("review.editable")

    inspected = store.inspect()
    layer = next(item for item in inspected["layers"] if item["prompt_id"] == descriptor.prompt_id)
    assert layer["current_text"] == descriptor.default_text
    assert layer["override"] is None
    assert PROMPT_OVERRIDES_SETTING not in settings.value

    edited = store.edit(descriptor.prompt_id, text=descriptor.default_text, base_revision=descriptor.default_revision)
    reset = store.reset(descriptor.prompt_id)
    assert edited["changed"] is False
    assert reset["changed"] is False
    assert settings.writes == []
    assert settings.value == {"unrelated": "kept"}


def test_stale_override_is_inspectable_but_a_stale_edit_is_rejected(registry):
    descriptor = registry.require("review.editable")
    stale = {"base_revision": "0" * 64, "text": "Stale {request}"}
    original = {PROMPT_OVERRIDES_SETTING: envelope({descriptor.prompt_id: stale})}
    settings = AtomicSettings(original)
    diagnostics = Diagnostics()
    store = PromptOverrideStore(
        registry, read_settings=settings.read, write_settings=settings.write, diagnostics=diagnostics
    )

    inspected = store.inspect()
    layer = next(item for item in inspected["layers"] if item["prompt_id"] == descriptor.prompt_id)
    assert layer["override"] == stale
    assert layer["conflict"] == "prompt_override_stale"
    assert layer["current_text"] == descriptor.default_text

    with pytest.raises(PromptError) as failure:
        store.edit(descriptor.prompt_id, text="New {request}", base_revision=stale["base_revision"])
    assert failure.value.code == "prompt_override_stale"
    assert settings.value == original
    assert settings.writes == []
    assert diagnostics.events[-1]["data"]["code"] == "prompt_override_stale"


def test_expected_effective_revision_rejects_a_lost_update(registry):
    descriptor = registry.require("review.editable")
    settings = AtomicSettings()
    diagnostics = Diagnostics()
    store = PromptOverrideStore(
        registry, read_settings=settings.read, write_settings=settings.write, diagnostics=diagnostics
    )
    original_revision = next(
        item["effective_revision"]
        for item in store.inspect()["layers"]
        if item["prompt_id"] == descriptor.prompt_id
    )

    first = store.edit(
        descriptor.prompt_id,
        text="First {request}",
        base_revision=descriptor.default_revision,
        expected_effective_revision=original_revision,
    )
    saved_after_first = deepcopy(settings.value)
    with pytest.raises(PromptError) as failure:
        store.edit(
            descriptor.prompt_id,
            text="Second {request}",
            base_revision=descriptor.default_revision,
            expected_effective_revision=original_revision,
        )
    assert failure.value.code == "prompt_override_concurrent"
    assert settings.value == saved_after_first
    assert len(settings.writes) == 1
    assert first["changed"] is True
    assert diagnostics.events[-1]["channel"] == "prompt.override.rejected"
    assert diagnostics.events[-1]["data"]["code"] == "prompt_override_concurrent"


def test_reset_can_remove_one_unknown_future_id_without_touching_other_state(registry):
    inactive = registry.require("review.inactive")
    original = {
        "unrelated": {"keep": "exactly"},
        PROMPT_OVERRIDES_SETTING: envelope({
            "future.remove": {"base_revision": "a" * 64, "text": "Remove me"},
            "future.keep": {"base_revision": "b" * 64, "text": "Keep me"},
            "review.inactive": {"base_revision": inactive.default_revision, "text": "Inactive custom"},
        }),
    }
    settings = AtomicSettings(original)
    store = PromptOverrideStore(registry, read_settings=settings.read, write_settings=settings.write)

    result = store.reset("future.remove")

    assert result["changed"] is True
    assert settings.value["unrelated"] == original["unrelated"]
    assert settings.value[PROMPT_OVERRIDES_SETTING]["overrides"] == {
        "future.keep": {"base_revision": "b" * 64, "text": "Keep me"},
        "review.inactive": {"base_revision": inactive.default_revision, "text": "Inactive custom"},
    }


def test_atomic_writer_failure_does_not_report_a_save_or_change_read_state(registry):
    descriptor = registry.require("review.editable")
    settings = AtomicSettings({"unrelated": "original"})
    settings.fail = True
    diagnostics = Diagnostics()
    store = PromptOverrideStore(
        registry, read_settings=settings.read, write_settings=settings.write, diagnostics=diagnostics
    )

    with pytest.raises(OSError, match="atomic replace failure"):
        store.edit(descriptor.prompt_id, text="Secret {request}", base_revision=descriptor.default_revision)
    assert settings.value == {"unrelated": "original"}
    assert settings.writes == []
    assert [event["channel"] for event in diagnostics.events] == ["prompt.override.write_failed"]
    assert diagnostics.events[0]["data"]["code"] == "prompt_write_failed"


def test_effective_fingerprints_change_with_composition_but_not_with_noop_save(registry):
    target = PromptTarget("conversation", "simple", "openai", "review-model")
    descriptor = registry.require("review.editable")
    settings = AtomicSettings()
    store = PromptOverrideStore(registry, read_settings=settings.read, write_settings=settings.write)
    before = registry.resolve(target, variables={"request": "bounded data"}).to_payload()

    first = store.edit(descriptor.prompt_id, text="Custom {request}", base_revision=descriptor.default_revision)
    after = registry.resolve(target, overrides=first["document"], variables={"request": "bounded data"}).to_payload()
    second = store.edit(descriptor.prompt_id, text="Custom {request}", base_revision=descriptor.default_revision)
    no_op = registry.resolve(target, overrides=second["document"], variables={"request": "bounded data"}).to_payload()

    assert first["changed"] is True
    assert after["static_fingerprint"] != before["static_fingerprint"]
    assert after["render_fingerprint"] != before["render_fingerprint"]
    assert after["layers"][1]["effective_revision"] != before["layers"][1]["effective_revision"]
    assert second["changed"] is False
    assert second["fingerprint"] == first["fingerprint"]
    assert no_op["static_fingerprint"] == after["static_fingerprint"]
    assert no_op["render_fingerprint"] == after["render_fingerprint"]
    assert len(settings.writes) == 1


def test_diagnostics_contain_codes_and_fingerprints_without_override_text(registry):
    descriptor = registry.require("review.editable")
    secret = "DO-NOT-LOG-THIS {request}"
    settings = AtomicSettings()
    diagnostics = Diagnostics()
    store = PromptOverrideStore(
        registry, read_settings=settings.read, write_settings=settings.write, diagnostics=diagnostics
    )

    result = store.edit(descriptor.prompt_id, text=secret, base_revision=descriptor.default_revision)
    serialized_events = repr(diagnostics.events)
    event = diagnostics.events[-1]
    assert event["channel"] == "prompt.override.saved"
    assert event["data"]["code"] == "prompt_edit"
    assert event["data"]["fingerprint"] == result["fingerprint"]
    assert len(event["data"]["fingerprint"]) == 64
    assert secret not in serialized_events
    assert "DO-NOT-LOG-THIS" not in serialized_events
