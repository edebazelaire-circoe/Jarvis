"""Frise de l'autorité de parole des Boards : une seule conversation parle à la fois.

Handoff board-session, Slice 08. Contrat : `docs/boards.md` › *Speech
authority*. La frise se construit depuis deux sources, chacune complète pour ce
qu'elle voit :

- le **bus** de Core (`brain.speech.requested`, seul chemin vers Voice, et
  `board.voice_binding.changed`, publié à chaque bascule et nouvelle Session) ;
- la **trace** (`runtime/trace.jsonl`) : `core.session.opened` /
  `core.board.switched` (l'autorité change), `core.brain.notice_relayed` (un
  relais dit par la voix), `core.brain.speech_withheld_inactive_board` (retenu).

`check_single_authority` rejoue la frise : chaque parole doit appartenir à la
conversation qui détient l'autorité à cet instant, et chaque retenue doit
viser une autre conversation que celle-là (sinon la porte aurait bloqué le
Board actif). Utilisée par `test_board_session_e2e.py` et par le script de
preuve réelle de la Slice 08 (trace d'un vrai `claude`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

AUTHORITY = "authority"
SPEECH = "speech"
WITHHELD = "withheld"

BUS_SPEECH = "brain.speech.requested"
BUS_REBIND = "board.voice_binding.changed"
TRACE_AUTHORITY = ("core.session.opened", "core.board.switched")
TRACE_SPEECH = "core.brain.notice_relayed"
TRACE_WITHHELD = "core.brain.speech_withheld_inactive_board"


@dataclass(frozen=True)
class Mark:
    kind: str
    conversation_id: str | None
    source: str
    ts: str = ""
    board_id: str | None = None


@dataclass
class AuthorityReport:
    segments: list[dict] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def speeches(self) -> int:
        return sum(segment["spoken"] for segment in self.segments)

    @property
    def withheld(self) -> int:
        return sum(segment["withheld"] for segment in self.segments)


def authority(conversation_id: str, *, source: str = "start", board_id: str | None = None) -> Mark:
    return Mark(AUTHORITY, conversation_id, source, board_id=board_id)


def marks_from_bus(envelopes: Iterable[object]) -> list[Mark]:
    """Enveloppes du bus de Core (dans l'ordre de publication)."""

    marks = []
    for envelope in envelopes:
        kind = getattr(envelope, "message_type", "")
        payload = getattr(envelope, "payload", {}) or {}
        if kind == BUS_REBIND:
            marks.append(Mark(AUTHORITY, payload.get("conversation_id"), f"bus:{payload.get('reason')}",
                              board_id=payload.get("board_id")))
        elif kind == BUS_SPEECH:
            marks.append(Mark(SPEECH, getattr(envelope, "conversation_id", None) or payload.get("conversation_id"),
                              "bus:speech"))
    return marks


def marks_from_trace(rows: Iterable[dict]) -> list[Mark]:
    """Lignes de `trace.jsonl` (dans l'ordre du fichier)."""

    marks = []
    for row in rows:
        kind, data = row.get("kind", ""), row.get("data") or {}
        ts = str(row.get("ts", ""))
        if kind in TRACE_AUTHORITY:
            marks.append(Mark(AUTHORITY, data.get("conversation_id"), kind, ts, data.get("board_id")))
        elif kind == TRACE_SPEECH:
            marks.append(Mark(SPEECH, data.get("conversation_id"), kind, ts))
        elif kind == TRACE_WITHHELD:
            marks.append(Mark(WITHHELD, data.get("conversation_id"), kind, ts, data.get("board_id")))
    return marks


def check_single_authority(marks: Iterable[Mark]) -> AuthorityReport:
    """Rejouer la frise ; rend les segments (une autorité chacun) et les violations."""

    report = AuthorityReport()
    current: dict | None = None
    for index, mark in enumerate(marks):
        if mark.kind == AUTHORITY:
            if not mark.conversation_id:
                report.violations.append(f"#{index} {mark.source}: authority without conversation")
                continue
            current = {"conversation_id": mark.conversation_id, "board_id": mark.board_id,
                       "source": mark.source, "ts": mark.ts, "spoken": 0, "withheld": 0}
            report.segments.append(current)
            continue
        if current is None:
            report.violations.append(f"#{index} {mark.source}: {mark.kind} before any authority")
            continue
        if mark.kind == SPEECH:
            if mark.conversation_id != current["conversation_id"]:
                report.violations.append(
                    f"#{index} {mark.source}: {mark.conversation_id} spoke while "
                    f"{current['conversation_id']} held the authority")
            else:
                current["spoken"] += 1
        elif mark.kind == WITHHELD:
            # `work_wake` retenu : `conversation_id` nul, le Board seul est nommé.
            if mark.conversation_id is not None and mark.conversation_id == current["conversation_id"]:
                report.violations.append(f"#{index} {mark.source}: the speaking conversation was withheld")
            else:
                current["withheld"] += 1
    return report
