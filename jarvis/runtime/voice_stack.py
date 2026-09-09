"""Les piles vocales disponibles et, pour chacune, ses réglages propres.

Un seul endroit décrit ce qui existe : l'interface y lit les champs à afficher,
`app.py` y lit comment construire la session. Sans ça, ajouter une option à
Gemini demanderait de la répéter dans le HTML, dans le validateur et dans le
lanceur — et les trois finiraient par diverger.

Un champ décrit ici est un champ qui est réellement transmis au fournisseur.
Les listes de modèles ne sont pas écrites ici : elles viennent de
`model_catalog`, donc de l'API du fournisseur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TURN_MODES = ("auto", "manual")

# OpenAI ne publie pas d'endpoint « liste des voix » : ces timbres sont ceux
# que gpt-realtime accepte, du plus grave au plus clair.
OPENAI_REALTIME_VOICES = (
    "cedar", "ash", "verse", "ballad", "echo", "sage", "alloy", "marin", "coral", "shimmer",
)

# Idem côté Google : les voix préconstruites de l'API Live ne sont exposées par
# aucun endpoint, seulement par la documentation.
GEMINI_LIVE_VOICES = ("Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr")

SENSITIVITIES = ("LOW", "HIGH")


@dataclass(frozen=True, slots=True)
class Field:
    key: str
    label: str
    kind: str  # select | number | toggle | text
    default: Any
    hint: str = ""
    options: tuple[str, ...] = ()
    # Renseigné quand la liste doit venir du catalogue réel du fournisseur,
    # sous la forme "<fournisseur>:<usage>" (ex. "openai:transcription").
    source: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    # N'afficher ce champ que si un autre vaut l'une de ces valeurs.
    depends_on: str = ""
    depends_values: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "default": self.default,
            "hint": self.hint,
        }
        if self.options:
            payload["options"] = list(self.options)
        if self.source:
            payload["source"] = self.source
        for name, value in (("min", self.minimum), ("max", self.maximum), ("step", self.step)):
            if value is not None:
                payload[name] = value
        if self.depends_on:
            payload["depends_on"] = self.depends_on
            payload["depends_values"] = list(self.depends_values)
        return payload


TURN_MODE_FIELD = Field(
    key="turn_mode",
    label="Fin de tour",
    kind="select",
    default="auto",
    options=TURN_MODES,
    hint="Automatique : le fournisseur clôt le tour dès que vous vous taisez, la touche de "
    "réveil ne sert plus qu'à interrompre. Manuelle : deuxième appui pour envoyer.",
)


@dataclass(frozen=True, slots=True)
class VoiceStackSpec:
    id: str
    label: str
    credential_provider: str
    # Fréquences imposées par le fournisseur, pas des préférences.
    input_sample_rate: int
    output_sample_rate: int
    model_role: str
    description: str
    fields: tuple[Field, ...] = field(default=())

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "credential_provider": self.credential_provider,
            "input_sample_rate": self.input_sample_rate,
            "output_sample_rate": self.output_sample_rate,
            "model_role": self.model_role,
            "description": self.description,
            "fields": [item.describe() for item in self.fields],
        }

    def defaults(self) -> dict[str, Any]:
        return {item.key: item.default for item in self.fields}


OPENAI_REALTIME = VoiceStackSpec(
    id="openai_realtime",
    label="ChatGPT Live (OpenAI Realtime)",
    credential_provider="openai",
    input_sample_rate=24000,
    output_sample_rate=24000,
    model_role="realtime",
    description="Websocket bidirectionnel gpt-realtime. C'est la pile utilisée par JARVIS "
    "aujourd'hui : voix, outils Core et appel de Claude passent par elle.",
    fields=(
        Field(
            key="model",
            label="Modèle Realtime",
            kind="select",
            default="",
            source="openai:realtime",
            hint="Liste demandée à l'API OpenAI ; vide = valeur de OPENAI_REALTIME_MODEL.",
        ),
        Field(
            key="voice",
            label="Voix",
            kind="select",
            default="cedar",
            options=OPENAI_REALTIME_VOICES,
            hint="OpenAI ne publie pas de liste de voix : ces timbres sont ceux acceptés par gpt-realtime.",
        ),
        TURN_MODE_FIELD,
        Field(
            key="transcription_model",
            label="Transcription de votre voix",
            kind="select",
            default="gpt-4o-mini-transcribe",
            source="openai:transcription",
            hint="Sert à écrire ce que vous dites dans l'historique et à décider si JARVIS est "
            "concerné. N'affecte pas la réponse audio.",
        ),
        Field(
            key="vad_threshold",
            label="Seuil de détection de parole",
            kind="number",
            default=0.55,
            minimum=0.0,
            maximum=1.0,
            step=0.05,
            depends_on="turn_mode",
            depends_values=("auto",),
            hint="Plus haut = il faut parler plus fort pour déclencher un tour.",
        ),
        Field(
            key="vad_prefix_padding_ms",
            label="Audio conservé avant la parole (ms)",
            kind="number",
            default=300,
            minimum=0,
            maximum=2000,
            step=50,
            depends_on="turn_mode",
            depends_values=("auto",),
        ),
        Field(
            key="vad_silence_duration_ms",
            label="Silence qui clôt le tour (ms)",
            kind="number",
            default=1500,
            minimum=100,
            maximum=4000,
            step=50,
            depends_on="turn_mode",
            depends_values=("auto",),
            hint="Trop court, JARVIS vous coupe ; trop long, il tarde à répondre.",
        ),
    ),
)

GEMINI_LIVE = VoiceStackSpec(
    id="gemini_live",
    label="Gemini Live (Google)",
    credential_provider="google",
    # Imposé par l'API Live : 16 kHz en entrée, 24 kHz en sortie.
    input_sample_rate=16000,
    output_sample_rate=24000,
    model_role="realtime",
    description="Websocket BidiGenerateContent. Seuls les modèles que l'API Google déclare "
    "compatibles `bidiGenerateContent` sont proposés.",
    fields=(
        Field(
            key="model",
            label="Modèle Live",
            kind="select",
            default="",
            source="google:realtime",
            hint="Liste demandée à l'API Google, filtrée sur la capacité bidiGenerateContent.",
        ),
        Field(
            key="voice",
            label="Voix",
            kind="select",
            default="Puck",
            options=GEMINI_LIVE_VOICES,
            hint="Voix préconstruites de l'API Live ; Google ne les expose par aucun endpoint.",
        ),
        TURN_MODE_FIELD,
        Field(
            key="input_transcription",
            label="Transcrire votre voix",
            kind="toggle",
            default=True,
            hint="Nécessaire pour l'historique et pour « jarvis mute ». Désactivez-la pour "
            "réduire la latence si l'historique ne vous sert pas.",
        ),
        Field(
            key="output_transcription",
            label="Transcrire les réponses",
            kind="toggle",
            default=True,
            hint="Écrit dans l'historique ce que JARVIS a dit.",
        ),
        Field(
            key="vad_start_sensitivity",
            label="Sensibilité au début de parole",
            kind="select",
            default="LOW",
            options=SENSITIVITIES,
            depends_on="turn_mode",
            depends_values=("auto",),
            hint="HIGH déclenche plus facilement, au risque des bruits de fond.",
        ),
        Field(
            key="vad_end_sensitivity",
            label="Sensibilité à la fin de parole",
            kind="select",
            default="LOW",
            options=SENSITIVITIES,
            depends_on="turn_mode",
            depends_values=("auto",),
        ),
        Field(
            key="vad_prefix_padding_ms",
            label="Audio conservé avant la parole (ms)",
            kind="number",
            default=300,
            minimum=0,
            maximum=2000,
            step=50,
            depends_on="turn_mode",
            depends_values=("auto",),
        ),
        Field(
            key="vad_silence_duration_ms",
            label="Silence qui clôt le tour (ms)",
            kind="number",
            default=1500,
            minimum=100,
            maximum=4000,
            step=50,
            depends_on="turn_mode",
            depends_values=("auto",),
        ),
    ),
)

VOICE_STACKS: tuple[VoiceStackSpec, ...] = (OPENAI_REALTIME, GEMINI_LIVE)
VOICE_STACK_IDS: tuple[str, ...] = tuple(spec.id for spec in VOICE_STACKS)
DEFAULT_VOICE_STACK = OPENAI_REALTIME.id
_BY_ID = {spec.id: spec for spec in VOICE_STACKS}


class VoiceStackError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_stack(value: object) -> str:
    name = str(value or "").strip().lower()
    return name if name in _BY_ID else DEFAULT_VOICE_STACK


def stack_spec(value: object) -> VoiceStackSpec:
    return _BY_ID[normalize_stack(value)]


def describe_stacks() -> list[dict[str, Any]]:
    return [spec.describe() for spec in VOICE_STACKS]


def coerce(spec: VoiceStackSpec, payload: dict[str, Any]) -> dict[str, Any]:
    """Valider les réglages d'une pile, champ par champ, en refusant l'inconnu.

    Un réglage refusé remonte avec son code : mieux vaut un message précis
    qu'une valeur silencieusement remplacée par un défaut, qui donnerait
    l'impression que l'interface n'enregistre rien.
    """
    out: dict[str, Any] = {}
    for item in spec.fields:
        if item.key not in payload or payload[item.key] is None:
            continue
        raw = payload[item.key]
        if item.kind == "toggle":
            out[item.key] = raw if isinstance(raw, bool) else str(raw).strip().lower() in {"1", "true", "on", "yes"}
        elif item.kind == "number":
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise VoiceStackError(
                    "voice_field_not_a_number", f"« {item.label} » attend un nombre."
                ) from exc
            if item.minimum is not None and value < item.minimum:
                raise VoiceStackError(
                    "voice_field_out_of_range", f"« {item.label} » ne peut pas descendre sous {item.minimum:g}."
                )
            if item.maximum is not None and value > item.maximum:
                raise VoiceStackError(
                    "voice_field_out_of_range", f"« {item.label} » ne peut pas dépasser {item.maximum:g}."
                )
            out[item.key] = value if isinstance(item.default, float) else int(value)
        elif item.kind == "select" and item.options:
            value = str(raw).strip()
            if value and value not in item.options:
                raise VoiceStackError(
                    "voice_field_unknown_option", f"« {value} » n'est pas une valeur acceptée pour {item.label}."
                )
            out[item.key] = value
        else:
            # Les modèles viennent d'un catalogue distant : on ne peut pas les
            # valider hors ligne, seulement refuser ce qui n'est pas du texte.
            out[item.key] = str(raw).strip()
    return out


# Anciens champs plats du Control Center, avant que les réglages ne soient
# rangés par pile. Un fichier de configuration écrit par la version précédente
# doit continuer à être lu, sinon la voix change de timbre sans prévenir.
# (ancien champ, champ de pile, pile concernée ; vide = toutes les piles)
LEGACY_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("voice_turn_mode", "turn_mode", ""),
    ("realtime_voice", "voice", OPENAI_REALTIME.id),
)


def settings_for(settings: dict[str, Any], stack: object = None) -> dict[str, Any]:
    """Réglages effectifs d'une pile : ses défauts, l'ancien format, puis le nouveau."""
    spec = stack_spec(stack if stack is not None else settings.get("voice_stack"))
    values = spec.defaults()
    for legacy_key, field_key, only_stack in LEGACY_FIELDS:
        if only_stack and only_stack != spec.id:
            continue
        legacy = settings.get(legacy_key)
        if field_key in values and legacy not in (None, ""):
            values[field_key] = legacy
    stored = settings.get("voice_stack_settings")
    saved = stored.get(spec.id) if isinstance(stored, dict) and isinstance(stored.get(spec.id), dict) else {}
    values.update({key: saved[key] for key in values if key in saved})
    return values


def store_for(settings: dict[str, Any], stack: str, values: dict[str, Any]) -> None:
    stored = settings.get("voice_stack_settings")
    stored = dict(stored) if isinstance(stored, dict) else {}
    current = dict(stored.get(stack) or {})
    current.update(values)
    stored[stack] = current
    settings["voice_stack_settings"] = stored
