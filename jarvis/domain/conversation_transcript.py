"""Readable text transcript of a conversation, derived only from Conversation Events (Slice 06).

Binding contract: `docs/conversation-events.md`, section "Readable transcript".
One deterministic renderer shared by every surface: the Core route, the Control
Center (which relays Core's text), and offline reconstruction of an export
(`conversation_event_export.transcript_from_export`). No model writes or
rewrites a line; the same events always give the same bytes.

Invariants:

- pure domain: no I/O, no clock, no locale. Times are UTC unless the caller
  passes an explicit `utc_offset_minutes` (stated in the header, part of the
  rendering inputs), numbers use a fixed French format, so a transcript
  rendered live and one rendered from a re-imported export with the same inputs
  are byte-identical;
- the transcript is a projection of `reconstruct_conversation`. Jarvis speech
  text is the **text sent for playback** (contract note 5): an interrupted
  speech is annotated with the heard duration the events carry
  (`attributes.played_ms`), never with a guess of the words heard;
- duplicate Brain publications collapse with exactly the rule of the timeline
  (`collapseMessages` in `control_center_timeline.js`, parity-tested): a
  `brain.message.published` whose text equals the previous published message of
  the same `correlation_id` is merged into it;
- *plain* mode shows public items only (user speech, Jarvis speech and
  reflexes, Brain messages); *detailed* mode adds diagnostic items with their
  allowlisted metadata (work, sub-agent and tool spans with durations, failures
  with codes). Nothing outside the event envelope ever appears.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from jarvis.domain.conversation_events import (
    ConversationActor, ConversationEvent, ConversationEventError, ConversationEventType as T, ConversationItem,
    ConversationVisibility, reconstruct_conversation,
)

TRANSCRIPT_FORMAT_VERSION = 1
#: Events kept in memory to render one transcript. Above it the renderer
#: refuses (`TranscriptTooLargeError`): the machine-readable export streams any size.
MAX_TRANSCRIPT_EVENTS = 50_000
#: Text the renderer may hold: UTF-8 bytes of kept event content plus
#: `LINE_OVERHEAD_BYTES` per kept event, checked at each `add` (so refusing is cheap).
MAX_TRANSCRIPT_CONTENT_BYTES = 16 * 1024 * 1024
LINE_OVERHEAD_BYTES = 64
#: Accepted local offsets (UTC−14:00 .. UTC+14:00).
MAX_UTC_OFFSET_MINUTES = 14 * 60


class TranscriptMode(StrEnum):
    PLAIN = "plain"
    DETAILED = "detailed"


class TranscriptTooLargeError(Exception):
    """More than `MAX_TRANSCRIPT_EVENTS` events or `MAX_TRANSCRIPT_CONTENT_BYTES` of text would have to be held."""


def check_utc_offset(value: object) -> int:
    """Whole minutes in ±`MAX_UTC_OFFSET_MINUTES`; `ValueError` naming the rule otherwise."""
    if type(value) is not int or abs(value) > MAX_UTC_OFFSET_MINUTES:
        raise ValueError(f"utc_offset_minutes must be an integer between -{MAX_UTC_OFFSET_MINUTES} and "
                         f"{MAX_UTC_OFFSET_MINUTES}")
    return value


def offset_label(minutes: int) -> str:
    """`UTC` or `UTC+02:00` / `UTC-05:30`."""
    if minutes == 0:
        return "UTC"
    sign = "+" if minutes > 0 else "-"
    return f"UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


#: Types that can produce, or pair into, a public item. `mouth.speech.*`
#: diagnostic closes are kept because they close a public `started` span.
PLAIN_EVENT_TYPES = frozenset({
    T.USER_TRANSCRIPT_ACCEPTED, T.BRAIN_MESSAGE_PUBLISHED, T.MOUTH_SPEECH_STARTED, T.MOUTH_SPEECH_COMPLETED,
    T.MOUTH_SPEECH_INTERRUPTED, T.MOUTH_SPEECH_SUPERSEDED, T.MOUTH_SPEECH_EXPIRED, T.MOUTH_SPEECH_FAILED,
    T.MOUTH_REFLEX_STARTED,
})
#: Detailed mode leaves out only the scheduling marker `mouth.speech.queued`
#: (its speech is the Jarvis line itself).
DETAILED_EVENT_TYPES = frozenset(T) - {T.MOUTH_SPEECH_QUEUED}

_STATUS = {"open": "en cours", "completed": "terminé", "finished": "terminé", "interrupted": "interrompu",
           "superseded": "remplacé", "expired": "expiré", "failed": "échec", "stopped": "arrêté",
           "cancelled": "annulé", "accepted": "accepté", "requested": "demandé", "failure": "échec"}
_MOUTH_NOTE = {"open": "en cours", "failed": "lecture en échec", "superseded": "remplacé avant la fin",
               "expired": "expiré avant la fin"}
_GENERIC_SUBAGENT_TYPES = frozenset({"", "general-purpose", "general", "fork", "default", "agent", "task", "subagent"})


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    """A reconstructed item with what the transcript needs from its events."""

    item: ConversationItem
    correlation_id: str | None
    producer: str
    #: Open attributes overlaid by the close's (same merge as the timeline).
    attributes: Mapping[str, Any]
    #: Content of the span's open event (a sub-agent description, a work label), else None.
    open_text: str | None = None
    #: Identical publications merged into this one (`collapse_published_messages`).
    collapsed: tuple[ConversationItem, ...] = ()


def transcript_entries(events: Iterable[ConversationEvent], *,
                       include_diagnostic: bool = True) -> tuple[TranscriptEntry, ...]:
    """Reconstruct, attach correlation/producer/attributes, then collapse duplicate publications."""
    events = list(events)
    by_id: dict[str, ConversationEvent] = {}
    for event in events:
        if isinstance(event, ConversationEvent):
            by_id.setdefault(event.event_id, event)  # first copy, like reconstruct_conversation
    entries = []
    for item in reconstruct_conversation(events, include_diagnostic=include_diagnostic):
        primary = by_id[item.event_ids[0]]
        close = by_id[item.event_ids[1]] if len(item.event_ids) > 1 else None
        correlation = next((e.correlation_id for e in (primary, close) if e is not None and e.correlation_id), None)
        attributes = dict(primary.attributes)
        if close is not None:
            attributes.update(close.attributes)
        open_text = primary.content if len(item.event_ids) > 1 or item.status == "open" else None
        entries.append(TranscriptEntry(item, correlation, primary.producer, attributes, open_text))
    return collapse_published_messages(entries)


def collapse_published_messages(entries: Iterable[TranscriptEntry]) -> tuple[TranscriptEntry, ...]:
    """Merge a publication equal to the previous publication of its correlation (A, B, A stays three)."""
    out: list[TranscriptEntry] = []
    last: dict[str, int] = {}
    for entry in entries:
        if entry.item.event_type is T.BRAIN_MESSAGE_PUBLISHED and entry.correlation_id is not None:
            at = last.get(entry.correlation_id)
            if at is not None and out[at].item.text == entry.item.text:
                out[at] = replace(out[at], collapsed=(*out[at].collapsed, entry.item))
                continue
            last[entry.correlation_id] = len(out)
        out.append(entry)
    return tuple(out)


# ------------------------------------------------------------------ format

def format_clock(value: datetime) -> str:
    return value.strftime("%H:%M:%S.") + f"{value.microsecond // 1000:03d}"


def format_duration_ms(value: float) -> str:
    """Fixed French format: `850 ms`, `1,4 s`, `2 min 05 s`, `1 h 02 min`."""
    ms = max(0, int(round(value)))
    if ms < 1000:
        return f"{ms} ms"
    if ms < 59_950:  # below it, one decimal never rounds up to "60,0 s"
        tenths = (ms + 50) // 100
        return f"{tenths // 10},{tenths % 10} s"
    seconds = (ms + 500) // 1000
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min {seconds % 60:02d} s"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def _duration(item: ConversationItem) -> str | None:
    if item.ended_at is None:
        return None
    return format_duration_ms((item.ended_at - item.started_at).total_seconds() * 1000)


def _status(status: str) -> str:
    return _STATUS.get(status, status)


def _text_block(prefix: str, text: str) -> list[str]:
    """First line after the prefix; continuation lines indented, content otherwise untouched."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return [prefix + lines[0], *("    " + line for line in lines[1:])]


def _codes(attributes: Mapping[str, Any]) -> str:
    parts = [f"{label} {attributes[key]}" for key, label in (("code", "code"), ("reason", "raison"),
                                                              ("error_class", "classe"))
             if isinstance(attributes.get(key), (str, int, float)) and not isinstance(attributes.get(key), bool)]
    return ", ".join(parts)


def _played(attributes: Mapping[str, Any]) -> str | None:
    played = attributes.get("played_ms")
    if isinstance(played, bool) or not isinstance(played, (int, float)) or played < 0:
        return None
    return format_duration_ms(played)


def _public_lines(entry: TranscriptEntry, *, detailed: bool, shift: timedelta) -> list[str]:
    item, attributes = entry.item, entry.attributes
    stamp = f"[{format_clock(item.started_at + shift)}] "
    notes: list[str] = []
    if item.event_type is T.USER_TRANSCRIPT_ACCEPTED:
        label = "Utilisateur"
    elif item.event_type is T.BRAIN_MESSAGE_PUBLISHED:
        label = "Brain"
        if detailed and entry.collapsed:
            notes.append(f"publié {len(entry.collapsed) + 1} fois")
    elif item.event_type is T.MOUTH_REFLEX_STARTED:
        label = "Jarvis (réflexe)"
    else:
        label = "Jarvis"
        if item.status == "interrupted":
            played = _played(attributes)
            notes.append(f"interrompu après {played} entendues" if played else "interrompu, durée entendue inconnue")
        elif item.status in _MOUTH_NOTE:
            notes.append(_MOUTH_NOTE[item.status])
            if detailed and _codes(attributes):
                notes.append(_codes(attributes))
    if detailed and item.anomalies:
        notes.append("anomalies : " + ", ".join(a.split(":", 1)[0] for a in item.anomalies))
    head = f"{stamp}{label}{''.join(f' [{note}]' for note in notes)} : "
    return _text_block(head, item.text if item.text is not None else "(texte non enregistré)")


def _quoted(text: str | None) -> str:
    return f" « {text} »" if text else ""


def _span_outcome(item: ConversationItem, attributes: Mapping[str, Any]) -> str:
    duration = _duration(item)
    outcome = _status(item.status) if duration is None else f"{_status(item.status)} en {duration}"
    codes = _codes(attributes)
    return f"{outcome} ({codes})" if codes else outcome


def _diagnostic_lines(entry: TranscriptEntry, *, shift: timedelta) -> list[str]:
    item, attributes = entry.item, entry.attributes
    stamp = f"[{format_clock(item.started_at + shift)}] -- "
    kind = item.event_type
    if kind is T.BRAIN_TURN_ACCEPTED:
        source = attributes.get("source")
        line = "Brain : tour accepté" + (f" (source {source})" if isinstance(source, str) else "")
    elif kind is T.BRAIN_TURN_FAILED:
        codes = _codes(attributes)
        line = "Brain : tour en échec" + (f" ({codes})" if codes else "")
    elif kind is T.SYSTEM_FAILURE:
        where = "voix" if entry.producer.startswith("voice.") else "Core"
        codes = _codes(attributes)
        line = f"Système ({where}) : échec" + (f" ({codes})" if codes else "")
    elif kind is T.BRAIN_SPEECH_REQUESTED:
        return _text_block(f"{stamp}Brain : parole demandée : ", item.text or "(texte non enregistré)")
    elif item.actor is ConversationActor.MOUTH:
        # A close without a recorded start: this speech was never played.
        return _text_block(f"{stamp}Jarvis : parole non prononcée [{_status(item.status)}] : ",
                           item.text or "(texte non enregistré)")
    elif item.actor is ConversationActor.BRAIN:
        line = f"Brain · travail{_quoted(entry.open_text or item.text)} : {_span_outcome(item, attributes)}"
    elif item.actor is ConversationActor.SUBAGENT:
        subagent_type = str(attributes.get("subagent_type") or "")
        name = entry.open_text or item.text or "Sous-agent"
        extras = []
        if subagent_type.lower() not in _GENERIC_SUBAGENT_TYPES:
            extras.append(f"type {subagent_type}")
        for key, label in (("model", "modèle"), ("tokens", "jetons"), ("tool_uses", "outils")):
            value = attributes.get(key)
            if isinstance(value, bool) or not isinstance(value, (str, int, float)) or value in ("", 0):
                continue  # unknown usage is reported as 0 by the tracker: never print it as a fact
            extras.append(f"{label} {value}" if key == "model" else f"{value} {label}")
        line = f"Sous-agent « {name} » : {_span_outcome(item, attributes)}" + (f" · {' · '.join(extras)}" if extras else "")
    elif item.actor is ConversationActor.TOOL:
        tool = attributes.get("tool_name") if isinstance(attributes.get("tool_name"), str) else "inconnu"
        status = attributes.get("status")
        outcome = _span_outcome(item, {k: v for k, v in attributes.items() if k in ("error_class", "code")})
        line = f"Outil {tool} : {outcome}" + (f" · statut {status}" if isinstance(status, str) else "")
    else:  # an event type added to the contract later: named, never dropped
        line = f"{kind.value} : {_status(item.status)}"
    if item.anomalies:
        line += " [anomalies : " + ", ".join(a.split(":", 1)[0] for a in item.anomalies) + "]"
    return [stamp + line]


# ----------------------------------------------------------------- builder

class TranscriptBuilder:
    """Accumulate events page by page (live store reads or an export file), then render once.

    Keeps only the event types the mode needs (bounded by `max_events`) but
    counts every event it is given, so paging order and page size never change
    the output.
    """

    def __init__(self, conversation_id: str, *, mode: TranscriptMode = TranscriptMode.PLAIN,
                 max_events: int | None = None, max_content_bytes: int | None = None,
                 utc_offset_minutes: int = 0) -> None:
        self.conversation_id = conversation_id
        self.mode = TranscriptMode(mode)
        self.max_events = MAX_TRANSCRIPT_EVENTS if max_events is None else max_events
        self.max_content_bytes = MAX_TRANSCRIPT_CONTENT_BYTES if max_content_bytes is None else max_content_bytes
        self.utc_offset_minutes = check_utc_offset(utc_offset_minutes)
        self.content_bytes = 0
        self.event_count = 0
        self.skipped_rows = 0
        self._kept: list[ConversationEvent] = []
        self._types = DETAILED_EVENT_TYPES if self.mode is TranscriptMode.DETAILED else PLAIN_EVENT_TYPES

    def add(self, event: ConversationEvent) -> None:
        if not isinstance(event, ConversationEvent):
            raise ConversationEventError("transcript accepts ConversationEvent values only")
        if event.conversation_id != self.conversation_id:
            raise ConversationEventError("transcript received an event of another conversation")
        self.event_count += 1
        if event.event_type not in self._types:
            return
        if len(self._kept) >= self.max_events:
            raise TranscriptTooLargeError(
                f"transcript needs more than {self.max_events} events; use the JSONL export instead")
        self.content_bytes += LINE_OVERHEAD_BYTES + (len(event.content.encode("utf-8")) if event.content else 0)
        if self.content_bytes > self.max_content_bytes:
            raise TranscriptTooLargeError(
                f"transcript text exceeds {self.max_content_bytes // (1024 * 1024)} MiB; use the JSONL export instead")
        self._kept.append(event)

    def note_skipped_rows(self, count: int) -> None:
        self.skipped_rows += max(0, int(count))

    def render(self) -> str:
        detailed = self.mode is TranscriptMode.DETAILED
        entries = transcript_entries(self._kept, include_diagnostic=detailed)
        lines = [
            f"Transcription de conversation · {self.conversation_id}",
            "Projection déterministe des Conversation Events (contrat v1) ; aucune ligne n'est écrite par un modèle.",
            f"Mode : {'détaillé' if detailed else 'simple'} · heures {offset_label(self.utc_offset_minutes)} · "
            f"{self.event_count} événement"
            f"{'s' if self.event_count > 1 else ''} lu{'s' if self.event_count > 1 else ''}"
            + (f" · {self.skipped_rows} ligne{'s' if self.skipped_rows > 1 else ''} illisible"
               f"{'s' if self.skipped_rows > 1 else ''} ignorée{'s' if self.skipped_rows > 1 else ''} par Core"
               if self.skipped_rows else ""),
            "Parole de Jarvis : texte envoyé à la lecture ; une parole coupée n'indique que la durée entendue.",
        ]
        if detailed:
            lines.append("Lignes « -- » : diagnostic (travaux, sous-agents, outils, échecs), jamais entendu tel quel.")
        lines.append("")
        day = None
        shown = 0
        shift = timedelta(minutes=self.utc_offset_minutes)
        for entry in entries:
            item = entry.item  # plain mode: `transcript_entries` already kept public items only
            if (item.started_at + shift).date() != day:
                day = (item.started_at + shift).date()
                lines.append(f"— {day.isoformat()} —")
            if item.visibility is ConversationVisibility.PUBLIC:
                lines.extend(_public_lines(entry, detailed=detailed, shift=shift))
            else:
                lines.extend(_diagnostic_lines(entry, shift=shift))
            shown += 1
        if not shown:
            lines.append("(aucun échange public enregistré)" if not detailed else "(aucun événement enregistré)")
        return "\n".join(lines) + "\n"


def render_transcript(events: Iterable[ConversationEvent], *, conversation_id: str,
                      mode: TranscriptMode = TranscriptMode.PLAIN, skipped_rows: int = 0,
                      utc_offset_minutes: int = 0) -> str:
    builder = TranscriptBuilder(conversation_id, mode=mode, utc_offset_minutes=utc_offset_minutes)
    for event in events:
        builder.add(event)
    builder.note_skipped_rows(skipped_rows)
    return builder.render()
