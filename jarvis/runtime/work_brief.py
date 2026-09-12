"""Rendu, dans la consigne de l'agent, du travail en cours que Core lui remet.

Handoff work-state, tâche 12. Core joint au tour (`context.work` de
`POST /api/agent/ask`) la forme de fil de `BrainWorkContext` ; le Control
Center, qui possède l'agent et la formulation de ce qu'on lui dit
(Décision 23), la rend ici en quelques lignes françaises. C'est ce qui permet
au cerveau de répondre à « où en sont mes tâches ? » depuis l'état de Core,
sans lire le Control Center.

Lecture en liste blanche, champ par champ, comme `_BRIEF_STATE_FIELDS` :
identifiants, révision et horodatages bruts restent dans la charge utile et
n'atteignent pas le modèle. Chaque valeur est tronquée : la charge utile est
déjà bornée par Core, ce rendu ne fait pas confiance à une borne distante.
"""

from __future__ import annotations

from typing import Any

from jarvis.domain.work_state import WorkStatus

#: Nombre maximal de lignes de travaux rendues (Core en envoie au plus 18).
MAX_BRIEF_WORK_LINES = 18
#: Changements inattendus rendus sur la ligne « Nouveau depuis ton dernier tour ».
MAX_BRIEF_ATTENTION = 8
_MAX_VALUE_CHARS = 240

_STATUS_LABELS = {
    WorkStatus.PENDING.value: "en attente",
    WorkStatus.RUNNING.value: "en cours",
    WorkStatus.BLOCKED.value: "bloquée (attend l'utilisateur)",
    WorkStatus.COMPLETED.value: "terminée",
    WorkStatus.FAILED.value: "échouée",
    WorkStatus.CANCELLED.value: "annulée",
    WorkStatus.INTERRUPTED.value: "interrompue",
}
_ACTIVE_STATUSES = frozenset({WorkStatus.PENDING.value, WorkStatus.RUNNING.value, WorkStatus.BLOCKED.value})

#: Dernière ligne du bloc : dit au modèle d'où vient la liste et qu'elle fait foi.
BRIEF_WORK_SOURCE_NOTE = (
    "Cette liste est l'état tenu par Core : appuie-toi dessus si l'utilisateur "
    "demande où en est son travail."
)
#: Accompagne les changements inattendus : les connaître n'oblige pas à les dire (D17).
BRIEF_ATTENTION_NOTE = "Ne l'annonce que si cela compte pour l'utilisateur."


def _text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= _MAX_VALUE_CHARS else text[: _MAX_VALUE_CHARS - 1].rstrip() + "…"


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _duration(seconds: Any) -> str:
    """42 s, 3 min 12 s, 1 h 05 min : une durée qui se dit."""

    total = _count(seconds)
    if total < 60:
        return f"{total} s"
    if total < 3600:
        minutes, rest = divmod(total, 60)
        return f"{minutes} min {rest} s" if rest else f"{minutes} min"
    hours, rest = divmod(total // 60, 60)
    return f"{hours} h {rest:02d} min"


def _entry_line(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "")
    label = _text(item.get("label")) or "(sans libellé)"
    head = _STATUS_LABELS.get(status, _text(status) or "état inconnu")
    if status in _ACTIVE_STATUSES:
        head = f"{head} depuis {_duration(item.get('elapsed_s'))}"
    else:
        head = f"{head} il y a {_duration(item.get('ended_ago_s'))} (durée {_duration(item.get('elapsed_s'))})"
    parts = [f"- {head} : « {label} »"]
    for key, name in (("activity", "activité"), ("model", "modèle"), ("error_class", "erreur"), ("summary", "résumé")):
        value = _text(item.get(key))
        if value:
            parts.append(f"{name} : {value}")
    fraction = item.get("progress_fraction")
    if isinstance(fraction, (int, float)) and not isinstance(fraction, bool) and 0 <= fraction <= 1:
        parts.append(f"avancement {round(fraction * 100)} %")
    return " — ".join(parts)


def _attention_part(note: dict[str, Any]) -> str:
    label = _text(note.get("label")) or "(sans libellé)"
    status = _STATUS_LABELS.get(str(note.get("status") or ""), "a changé d'état")
    error = _text(note.get("error_class"))
    return f"« {label} » {status}" + (f" ({error})" if error else "")


def render_work_brief(work: Any) -> list[str]:
    """Lignes à insérer dans la consigne ; rien si Core n'a pas joint de travail."""

    if not isinstance(work, dict):
        return []
    raw_items = work.get("items")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    items = items[:MAX_BRIEF_WORK_LINES]
    raw_notes = work.get("attention")
    notes = [note for note in raw_notes if isinstance(note, dict)] if isinstance(raw_notes, list) else []
    active_total = _count(work.get("active_total"))
    finished_total = _count(work.get("finished_total"))

    lines: list[str] = []
    if not items and not active_total and not finished_total:
        lines.append("Tâches suivies par Core : aucune.")
    else:
        lines.append(f"Tâches suivies par Core : {active_total} en cours, {finished_total} terminée(s) récemment.")
        lines.extend(_entry_line(item) for item in items)
        listed_active = sum(1 for item in items if str(item.get("status") or "") in _ACTIVE_STATUSES)
        omitted_active = max(0, active_total - listed_active)
        omitted_finished = max(0, finished_total - (len(items) - listed_active))
        if omitted_active or omitted_finished:
            lines.append(f"(non listées : {omitted_active} en cours, {omitted_finished} terminée(s))")
    if notes:
        parts = [_attention_part(note) for note in notes[-MAX_BRIEF_ATTENTION:]]
        lines.append("Nouveau depuis ton dernier tour : " + " ; ".join(parts) + ". " + BRIEF_ATTENTION_NOTE)
    lines.append(BRIEF_WORK_SOURCE_NOTE)
    return lines
