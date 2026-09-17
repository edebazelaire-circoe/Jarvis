"""Independent oracle of the plain transcript body, re-derived from raw stored JSON (Slice 06 rework).

Written by QA without `reconstruct_conversation`, the transcript module or any
Jarvis domain helper: it pairs `mouth.speech.*` spans, applies the collapse rule
and formats lines from the encoded events alone. The rollout gate compares the
product's plain transcript body with it. Test helper, never used by production.
"""

from __future__ import annotations

from datetime import datetime, timezone

PUBLIC_INSTANT = {"user.transcript.accepted": "Utilisateur", "brain.message.published": "Brain",
                  "mouth.reflex.started": "Jarvis (réflexe)"}
MOUTH_CLOSES = {"mouth.speech.completed": "completed", "mouth.speech.interrupted": "interrupted",
                "mouth.speech.superseded": "superseded", "mouth.speech.expired": "expired",
                "mouth.speech.failed": "failed"}
PUBLIC_CLOSES = {"mouth.speech.completed", "mouth.speech.interrupted"}
NOTE = {"open": "en cours", "failed": "lecture en échec", "superseded": "remplacé avant la fin",
        "expired": "expiré avant la fin"}


def t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def dur(ms_f):
    ms = max(0, int(round(ms_f)))
    if ms < 1000:
        return f"{ms} ms"
    if ms < 59950:
        tenths = (ms + 50) // 100
        return f"{tenths // 10},{tenths % 10} s"
    sec = (ms + 500) // 1000
    m = sec // 60
    return f"{m} min {sec % 60:02d} s" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def clock(d: datetime) -> str:
    return d.strftime("%H:%M:%S.") + f"{d.microsecond // 1000:03d}"


def plain_body(raw_events: list[dict]) -> list[str]:
    """raw_events: codec JSON dicts in store (sequence) order."""
    seen, ev = set(), []
    for e in raw_events:
        if e["event_id"] in seen:
            continue
        seen.add(e["event_id"])
        ev.append(e)
    key = lambda e: (t(e["occurred_at"]), e["event_id"])
    opens, closes = {}, {}
    for e in ev:
        if e["event_type"] == "mouth.speech.started":
            opens.setdefault(e["span_id"], []).append(e)
        elif e["event_type"] in MOUTH_CLOSES:
            closes.setdefault(e["span_id"], []).append(e)
    items = []  # (started, item_id, label, notes, text, corr, type)
    for e in ev:
        et = e["event_type"]
        if et in PUBLIC_INSTANT:
            items.append([t(e["occurred_at"]), e["event_id"], PUBLIC_INSTANT[et], [], e.get("content"),
                          e.get("correlation_id"), et])
        elif et == "mouth.speech.started":
            first = min(opens[e["span_id"]], key=key)
            if first is not e:
                continue
            cl = sorted(closes.get(e["span_id"], []), key=key)
            attrs = dict(e.get("attributes") or {})
            notes = []
            text = e.get("content")
            if not cl:
                notes.append(NOTE["open"])
            else:
                c = cl[0]
                attrs.update(c.get("attributes") or {})
                if c.get("content") is not None:
                    text = c["content"]
                st = MOUTH_CLOSES[c["event_type"]]
                if st == "interrupted":
                    p = attrs.get("played_ms")
                    ok = not isinstance(p, bool) and isinstance(p, (int, float)) and p >= 0
                    notes.append(f"interrompu après {dur(p)} entendues" if ok else "interrompu, durée entendue inconnue")
                elif st in NOTE:
                    notes.append(NOTE[st])
            items.append([t(e["occurred_at"]), e["event_id"], "Jarvis", notes, text, e.get("correlation_id"), et])
        elif et in PUBLIC_CLOSES and e["span_id"] not in opens:
            first = min(closes[e["span_id"]], key=key)
            if first is not e:
                continue
            st = MOUTH_CLOSES[et]
            notes = []
            if st == "interrupted":
                p = (e.get("attributes") or {}).get("played_ms")
                ok = not isinstance(p, bool) and isinstance(p, (int, float)) and p >= 0
                notes.append(f"interrompu après {dur(p)} entendues" if ok else "interrompu, durée entendue inconnue")
            started = t(e["started_at"]) if e.get("started_at") else t(e["occurred_at"])
            items.append([started, e["event_id"], "Jarvis", notes, e.get("content"), e.get("correlation_id"), et])
    items.sort(key=lambda i: (i[0], i[1]))
    out, last, day = [], {}, None
    for started, _, label, notes, text, corr, et in items:
        if et == "brain.message.published" and corr is not None:
            if corr in last and last[corr] == text:
                continue
            last[corr] = text
        if started.date() != day:
            day = started.date()
            out.append(f"— {day.isoformat()} —")
        head = f"[{clock(started)}] {label}" + "".join(f" [{n}]" for n in notes) + " : "
        lines = (text if text is not None else "(texte non enregistré)").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        out.append(head + lines[0])
        out.extend("    " + l for l in lines[1:])
    return out


def body_of(transcript: str) -> list[str]:
    lines = transcript.split("\n")
    i = lines.index("")
    body = lines[i + 1:]
    if body and body[-1] == "":
        body = body[:-1]
    return [l for l in body if l not in ("(aucun échange public enregistré)",)]
