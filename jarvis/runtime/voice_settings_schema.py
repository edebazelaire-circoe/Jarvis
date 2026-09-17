"""Projection normalisée des réglages Voice pour le Control Center.

Les validateurs et valeurs effectives restent dans leurs registres historiques.
Ce module ne fait que leur ajouter une vue de rendu stable : aucune lecture de
réglages, aucun catalogue réseau et aucune écriture.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from jarvis.runtime import shortcuts, voice_stack


VOICE_CATEGORIES: tuple[dict[str, str], ...] = (
    {"id": "architecture", "label": "Architecture"},
    {"id": "conversation", "label": "Conversation"},
    {"id": "turn_taking", "label": "Tours & interruptions"},
    {"id": "models", "label": "Modèles"},
    {"id": "audio", "label": "Audio"},
    {"id": "advanced", "label": "Avancé"},
    {"id": "diagnostic", "label": "Diagnostic"},
)

_STACK_PREFIX = {voice_stack.OPENAI_REALTIME.id: "openai", voice_stack.GEMINI_LIVE.id: "gemini"}
_STACK_CATEGORY = {
    "openai": {
        "model": "models", "voice": "models", "turn_mode": "turn_taking",
        "transcription_model": "models", "transcription_language": "conversation",
        "noise_reduction": "audio", "echo_cancellation": "turn_taking",
        "ack_delay_ms": "conversation", "vad_type": "turn_taking",
        "vad_eagerness": "turn_taking", "vad_threshold": "turn_taking",
        "vad_prefix_padding_ms": "turn_taking", "vad_silence_duration_ms": "turn_taking",
    },
    "gemini": {
        "model": "models", "voice": "models", "turn_mode": "turn_taking",
        "input_transcription": "conversation", "output_transcription": "conversation",
        "vad_start_sensitivity": "turn_taking", "vad_end_sensitivity": "turn_taking",
        "vad_prefix_padding_ms": "turn_taking", "vad_silence_duration_ms": "turn_taking",
    },
}
_STACK_ADVANCED = {
    "openai": frozenset({
        "transcription_language", "vad_eagerness", "vad_threshold",
        "vad_prefix_padding_ms", "vad_silence_duration_ms",
    }),
    "gemini": frozenset({
        "vad_start_sensitivity", "vad_end_sensitivity", "vad_prefix_padding_ms",
        "vad_silence_duration_ms",
    }),
}
_ARCH_CATEGORY = {
    "conversation_model": "models", "reflex_model": "models", "analysis_model": "models",
    "speculative_deltas": "conversation", "reasoning_effort": "models",
    "client_delegation": "architecture", "idle_timeout_s": "conversation",
}
_ARCH_ADVANCED = frozenset({"speculative_deltas", "reasoning_effort", "client_delegation"})
_ARCH_HELP = {
    "conversation_model": "Simple/Duplex ; choix filtré par architecture et capacités.",
    "reflex_model": "Front Brain seulement.",
    "analysis_model": "Front Brain seulement ; doit produire du texte structuré.",
    "speculative_deltas": "Front Brain ; exige les deltas de transcription.",
    "reasoning_effort": "Front Brain ; options du descripteur du modèle d'analyse.",
    "client_delegation": "Invariant Duplex, affiché en lecture seule.",
    "idle_timeout_s": "Durée facturable de la session Duplex.",
}

PERSISTABLE_OPTION_IDS: tuple[str, ...] = (
    "voice_stack", "voice_arch", "architecture", "conversation_model", "reflex_model",
    "analysis_model", "speculative_deltas", "reasoning_effort", "client_delegation",
    "idle_timeout_s", "openai.model", "openai.voice", "openai.turn_mode",
    "openai.transcription_model", "openai.transcription_language", "openai.noise_reduction",
    "openai.echo_cancellation", "openai.ack_delay_ms", "openai.vad_type",
    "openai.vad_eagerness", "openai.vad_threshold", "openai.vad_prefix_padding_ms",
    "openai.vad_silence_duration_ms", "gemini.model", "gemini.voice",
    "gemini.turn_mode", "gemini.input_transcription", "gemini.output_transcription",
    "gemini.vad_start_sensitivity", "gemini.vad_end_sensitivity",
    "gemini.vad_prefix_padding_ms", "gemini.vad_silence_duration_ms",
    "conversation_mode", "speaker_verification", "owner_buffer_ms", "owner_threshold",
    "owner_evidence_ms", "owner_short_evidence_ms", "owner_short_margin",
    "owner_profile_path", "audio_input_device", "audio_output_device", "active_timeout_s",
    "wake_toggle",
)

DIAGNOSTIC_OPTION_IDS: tuple[str, ...] = (
    "authorization.status", "authorization.runtime", "authorization.verifier",
    "authorization.worker", "echo_cancellation.status", "switch.status", "catalog.source",
    "model.adapter_status", "model.availability",
)


def _options(values: Iterable[Any], labels: Iterable[str] = ()) -> list[dict[str, Any]]:
    label_list = list(labels)
    result: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if isinstance(value, dict):
            if value.get("provider_id") is not None and value.get("model_id") is not None:
                item = {
                    key: deepcopy(value[key])
                    for key in (
                        "provider_id", "model_id", "label", "selectable", "reason",
                        "adapter_status", "availability", "reasoning_efforts",
                    )
                    if key in value
                }
                item["id"] = f"{value['provider_id']}/{value['model_id']}"
                item.setdefault("label", item["id"])
            else:
                item = {
                    key: deepcopy(value[key])
                    for key in ("id", "label", "description", "hint")
                    if key in value
                }
                item.setdefault("label", str(item.get("id", "")))
        else:
            item = {"id": value, "label": label_list[index] if index < len(label_list) else str(value)}
        result.append(item)
    return result


def _record(
    option_id: str,
    *,
    category: str,
    persistence: str | None,
    source: str,
    kind: str,
    label: str,
    help_text: str,
    default: Any,
    options: Iterable[Any] = (),
    option_labels: Iterable[str] = (),
    advanced: bool = False,
    runtime_status: str = "live",
    readonly: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    type_name = {
        "toggle": "boolean", "select": "enum", "model": "catalog-select",
        "device": "device-select", "key": "key", "path": "path",
        "projection": "diagnostic",
    }.get(kind, kind)
    record = {
        "id": option_id,
        "persistence": persistence,
        "category": category,
        "destination": f"voice.{category}",
        "source": source,
        "kind": kind,
        "type": type_name,
        "label": label,
        "help": help_text,
        "default": deepcopy(default),
        "options": _options(options, option_labels),
        "advanced": advanced,
        "runtime_status": runtime_status,
        "readonly": readonly,
    }
    record.update({key: deepcopy(value) for key, value in extra.items() if value is not None})
    return record


def _field_record(
    field: voice_stack.Field,
    *,
    option_id: str,
    category: str,
    persistence: str,
    source: str,
    advanced: bool,
    runtime_status: str = "live",
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if field.minimum is not None:
        extra["minimum"] = field.minimum
    if field.maximum is not None:
        extra["maximum"] = field.maximum
    if field.step is not None:
        extra["step"] = field.step
    if field.placeholder:
        extra["placeholder"] = field.placeholder
    if field.depends_on:
        prefix = option_id.rsplit(".", 1)[0]
        extra["depends_on"] = f"{prefix}.{field.depends_on}={field.depends_values[0]}"
    if option_id == "owner_threshold":
        extra["exclusive_minimum"] = 0.0
    options: Iterable[Any] = field.options
    option_labels: Iterable[str] = field.option_labels
    if field.kind == "select" and field.default == "" and field.placeholder:
        options = ("", *field.options)
        option_labels = (field.placeholder, *field.option_labels)
    record = _record(
        option_id,
        category=category,
        persistence=persistence,
        source=field.source or source,
        kind=field.kind,
        label=field.label,
        help_text=field.hint,
        default=field.default,
        options=options,
        option_labels=option_labels,
        advanced=advanced,
        runtime_status=runtime_status,
        **extra,
    )
    if field.source:
        record["type"] = "catalog-select"
    return record


def _architecture_records(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    architecture_options = [
        {"id": profile.get("id"), "label": profile.get("label", profile.get("id", ""))}
        for profile in profiles
    ]
    result = [_record(
        "architecture", category="architecture",
        persistence="voice_architecture.config.architecture", source="voice capability registry",
        kind="select", label="Architecture vocale",
        help_text="Sélection versionnée par le registre de capacités.", default=None,
        options=architecture_options, advanced=False, placeholder="Projection de compatibilité",
    )]
    fields: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for profile in profiles:
        profile_id = str(profile.get("id") or "")
        for field in profile.get("fields", []):
            if isinstance(field, dict) and field.get("key"):
                fields.setdefault(str(field["key"]), []).append((profile_id, field))
    if set(fields) != set(_ARCH_CATEGORY):
        raise RuntimeError(f"Unmapped voice architecture fields: {sorted(set(fields) ^ set(_ARCH_CATEGORY))}")

    for key in _ARCH_CATEGORY:
        variants = fields[key]
        first = variants[0][1]
        kind = str(first.get("kind") or "text")
        raw_options: list[Any] = []
        seen: set[str] = set()
        if kind == "model":
            for _profile_id, field in variants:
                for option in field.get("options", []):
                    identity = f"{option.get('provider_id', '')}/{option.get('model_id', '')}"
                    if identity not in seen:
                        seen.add(identity)
                        raw_options.append(option)
        elif first.get("options_from"):
            source_key = str(first["options_from"])
            prop = str(first.get("options_property") or "")
            for _profile_id, model_field in fields.get(source_key, []):
                for option in model_field.get("options", []):
                    for value in option.get(prop, []):
                        if str(value) not in seen:
                            seen.add(str(value))
                            raw_options.append(value)
        else:
            raw_options = list(first.get("options", []))

        defaults = {profile_id: deepcopy(field.get("default")) for profile_id, field in variants}
        default: Any = "registry default" if kind == "model" else first.get("default")
        record = _record(
            key,
            category=_ARCH_CATEGORY[key],
            persistence=f"voice_architecture.config.{key}",
            source="voice capability registry",
            kind="select" if first.get("options_from") else kind,
            label=str(first.get("label") or key),
            help_text=_ARCH_HELP[key],
            default=default,
            options=raw_options,
            advanced=key in _ARCH_ADVANCED,
            runtime_status="live-invariant" if key == "client_delegation" else "live",
            readonly=bool(first.get("readonly", False)),
            applicable_architectures=[profile_id for profile_id, _field in variants],
            defaults_by_architecture=defaults,
            minimum=first.get("min"),
            maximum=first.get("max"),
            step=first.get("step"),
        )
        if first.get("options_from"):
            record["type"] = "enum-from-model"
            record["options_from"] = str(first["options_from"])
        result.append(record)
    return result


def _stack_records() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for spec in voice_stack.VOICE_STACKS:
        prefix = _STACK_PREFIX[spec.id]
        live_keys = {field.key for field in spec.fields}
        if live_keys != set(_STACK_CATEGORY[prefix]):
            raise RuntimeError(f"Unmapped {spec.id} settings fields: {sorted(live_keys ^ set(_STACK_CATEGORY[prefix]))}")
        for field in spec.fields:
            result.append(_field_record(
                field,
                option_id=f"{prefix}.{field.key}",
                category=_STACK_CATEGORY[prefix][field.key],
                persistence=f"voice_stack_settings.{spec.id}.{field.key}",
                source=f"voice_stack.{spec.id}",
                advanced=field.key in _STACK_ADVANCED[prefix],
                runtime_status="live-compatibility" if field.key == "model" else "live",
            ))
    return result


def _authorization_records() -> list[dict[str, Any]]:
    category = {"conversation_mode": "conversation", "speaker_verification": "conversation", "owner_buffer_ms": "turn_taking"}
    advanced = {"owner_buffer_ms"}
    result = [
        _field_record(field, option_id=field.key, category=category[field.key], persistence=field.key,
                      source="voice_stack.AUTHORIZATION_FIELDS", advanced=field.key in advanced)
        for field in voice_stack.AUTHORIZATION_FIELDS
    ]
    result.extend(
        _field_record(field, option_id=field.key, category="advanced", persistence=field.key,
                      source="voice_stack.OWNER_TUNING_FIELDS", advanced=True)
        for field in voice_stack.OWNER_TUNING_FIELDS
    )
    result.append(_record(
        "owner_profile_path", category="diagnostic", persistence="owner_profile_path",
        source="authorization.verifier.stored.owner_profile_path", kind="path", label="Profil vocal",
        help_text="Affichage diagnostic seulement ; jamais écrit par l'écran.", default="runtime default",
        advanced=True, runtime_status="live-readonly", readonly=True,
    ))
    return result


def _external_records() -> list[dict[str, Any]]:
    wake = next(spec for spec in shortcuts.SHORTCUTS if spec.id == "wake_toggle")
    return [
        _record("audio_input_device", category="audio", persistence="audio_input_device",
                source="audio.devices", kind="device", label="Microphone",
                help_text="Périphérique de capture.", default="system"),
        _record("audio_output_device", category="audio", persistence="audio_output_device",
                source="audio.devices", kind="device", label="Haut-parleur",
                help_text="Périphérique de lecture.", default="system"),
        {**_record("active_timeout_s", category="conversation", persistence="active_timeout_s",
                   source="v2_config.parse_active_timeout", kind="number-or-empty",
                   label="Mise en veille après inactivité",
                   help_text="0 = jamais ; sinon 5 s minimum ; vide = environnement/défaut.",
                   default=90, minimum=0), "maximum": None},
        _record("wake_toggle", category="turn_taking", persistence="shortcuts.wake_toggle",
                source="shortcuts.SHORTCUTS", kind="key", label=wake.label,
                help_text=wake.description, default=wake.default),
    ]


def _diagnostic_records() -> list[dict[str, Any]]:
    labels = {
        "authorization.status": "État de l'autorisation",
        "authorization.runtime": "Autorisation appliquée par Voice",
        "authorization.verifier": "État du vérificateur vocal",
        "authorization.worker": "État du worker de vérification",
        "echo_cancellation.status": "État de l'annulation d'écho",
        "switch.status": "État du changement de pile",
        "catalog.source": "Source du catalogue modèles",
        "model.adapter_status": "État de l'adaptateur modèle",
        "model.availability": "Disponibilité du modèle",
    }
    return [
        _record(option_id, category="diagnostic", persistence=None, source=option_id,
                kind="projection", label=labels[option_id],
                help_text="Diagnostic calculé en lecture seule à partir de l'état existant.",
                default=None, advanced=False, runtime_status="live-readonly", readonly=True)
        for option_id in DIAGNOSTIC_OPTION_IDS
    ]


def describe_voice_settings(
    *, architecture_profiles: list[dict[str, Any]], legacy_arches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Construire une copie détachée, ordonnée et exhaustive du schéma Voice."""

    stack_options = [
        {"id": spec.id, "label": spec.label, "description": spec.description}
        for spec in voice_stack.VOICE_STACKS
    ]
    records = [
        _record(
            "voice_stack", category="architecture", persistence="voice_stack", source="voice_stack.VOICE_STACKS",
            kind="select", label="Pile vocale de compatibilité",
            help_text="Choisit la pile seulement sans architecture versionnée ; une architecture explicite dérive sa pile.",
            default=voice_stack.DEFAULT_VOICE_STACK, options=stack_options, advanced=True,
            runtime_status="live-compatibility",
        ),
        _record(
            "voice_arch", category="architecture", persistence="voice_arch", source="control_center._VOICE_ARCH_CHOICES",
            kind="select", label="Mode vocal historique",
            help_text="S'applique seulement sans architecture versionnée ; vide suit environnement/défaut.",
            default="", options=legacy_arches, advanced=True, runtime_status="live-compatibility",
            placeholder="Par défaut",
        ),
        *_architecture_records(architecture_profiles),
        *_stack_records(),
        *_authorization_records(),
        *_external_records(),
    ]
    by_id = {record["id"]: record for record in records}
    if len(by_id) != len(records) or set(by_id) != set(PERSISTABLE_OPTION_IDS):
        raise RuntimeError(f"Voice settings inventory drift: {sorted(set(by_id) ^ set(PERSISTABLE_OPTION_IDS))}")
    ordered = [by_id[option_id] for option_id in PERSISTABLE_OPTION_IDS]
    ordered.extend(_diagnostic_records())
    return {"categories": deepcopy(list(VOICE_CATEGORIES)), "option_metadata": deepcopy(ordered)}
