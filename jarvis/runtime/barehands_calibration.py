"""Séance de calibration vue par le Control Center (tâche adaptative, Slice 06, décisions 50 et 53).

La séance **vit dans la page** (décision 41 : mesures, retours, hypothèses ne la
quittent pas). Le serveur n'en tient que ce dont il a besoin pour trois
décisions qui ne peuvent pas attendre la page :

1. **le mode du cerveau** : un tour reçu pendant une séance ouverte porte le
   drapeau `calibration` et la consigne du mode (`build_agent_brief`) ;
2. **la porte des outils** : une commande `calibration_*` hors séance est
   refusée (`barehands_calibration_inactive`) avant toute attente ;
3. **l'accord de l'utilisateur** : `calibration_accept_trial` exige que la
   citation que le cerveau donne ait été **dite** par l'utilisateur, dans un
   tour reçu **après** l'application de l'essai en cours.

La page déclare la séance (`POST /api/barehands/calibration-session`) à son
ouverture, la confirme toutes les `HEARTBEAT_S` et la ferme à sa sortie. Sans
nouvelle depuis `SESSION_TTL_S`, elle est échue — un onglet tué ne laisse pas le
cerveau en mode calibration.

**Ce qui est gardé des paroles.** Les dernières phrases de l'utilisateur, en
mémoire seulement, pendant la séance seulement, pour la vérification d'accord ;
effacées à la fin de la séance. Jamais journalisées (le journal ne porte que
leur nombre et leur longueur), jamais écrites sur disque.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import re
import time
from typing import Any

from jarvis.domain.barehands_calibration import (
    SESSION_BUSY,
    SESSION_TTL_S,
    check_session_id,
    consent_found,
)
from jarvis.domain.barehands_command import BarehandsCommandError

#: Phrases gardées pour la vérification d'accord : l'accord suit l'essai de
#: quelques tours, pas de dizaines.
UTTERANCES_MAX = 12
UTTERANCE_CHARS_MAX = 500
#: Nom d'exercice rendu par la page (identifiant d'étape du contrat).
EXERCISE_CHARS_MAX = 40
_TRIAL_REF = re.compile(r"\Atr-[0-9]{1,9}\Z")


@dataclass(slots=True)
class _Session:
    session_id: str
    opened: float
    seen: float
    exercise: str | None = None
    #: Instant (horloge du serveur) où le dernier essai **appliqué** a été reçu ;
    #: `None` sans essai en cours. C'est l'origine de la fenêtre d'accord.
    trial_applied: float | None = None
    trial_ref: str | None = None
    #: La proposition en attente de l'accord de l'utilisateur (retour du 28/09) :
    #: seules les phrases dites **après** qu'elle a été préparée la valident.
    proposal_at: float | None = None
    proposal_ref: str | None = None
    utterances: list[tuple[float, str]] = field(default_factory=list)
    #: Le fil des événements de la séance (les derniers), et la plus haute révision vue.
    events: list[dict[str, Any]] = field(default_factory=list)
    revision: int = 0


class CalibrationSessionRegistry:
    """La séance de calibration déclarée par la page, bornée dans le temps."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, ttl_s: float = SESSION_TTL_S,
                 emit: Callable[..., None] | None = None) -> None:
        self._clock = clock
        self.ttl_s = ttl_s
        self._emit = emit
        self._session: _Session | None = None

    # ------------------------------------------------------------ page

    def report(self, session_id: object, active: object, exercise: object = None,
               trial: object = None) -> dict[str, Any]:
        """Ouverture, battement ou fermeture déclarés par la page ; rend `status()`.

        **Une séance à la fois** (décision 50, reprise QA) : tant qu'une séance
        vit, une autre page qui en déclare une est refusée
        (`barehands_calibration_session_busy`, 409) — deux calibrations qui se
        disputeraient l'agent rendraient chaque commande ambiguë (le long-poll
        la remet au premier onglet venu). La page refusée garde sa calibration,
        sans agent, et le dit.

        **L'essai en cours voyage avec le battement** (`trial` : `tr-N` ou
        `null`). Une séance recréée (échéance, Control Center redémarré) ou un
        battement qui voit un autre essai **rouvre** la fenêtre d'accord à cet
        instant : l'horloge de la page ne se traduit pas dans celle du serveur,
        donc on ne remonte pas le temps — seules les phrases dites **après** le
        battement comptent. Plus strict, jamais plus large.
        """

        sid = check_session_id(session_id)
        if not isinstance(active, bool):
            raise BarehandsCommandError("barehands_bad_request", "active : booléen attendu", 400)
        if trial is not None and not (isinstance(trial, str) and _TRIAL_REF.match(trial)):
            raise BarehandsCommandError("barehands_bad_request", "trial : tr-N ou null", 400)
        step = exercise if isinstance(exercise, str) and 0 < len(exercise) <= EXERCISE_CHARS_MAX else None
        now = self._clock()
        current = self._current(now)
        if active:
            if current is not None and current.session_id != sid:
                self._log("barehands.calibration_session_refused", "seconde séance de calibration refusée",
                          {"session": sid[:8], "holder": current.session_id[:8], "code": SESSION_BUSY})
                raise BarehandsCommandError(
                    SESSION_BUSY,
                    "Une autre page du Control Center tient déjà une séance de calibration : fermez-la d'abord.",
                    409)
            if current is None:
                current = self._session = _Session(sid, now, now, step)
                self._log("barehands.calibration_session_opened", "séance de calibration ouverte",
                          {"session": sid[:8], "exercise": step, "trial": trial})
            current.seen = now
            current.exercise = step
            if trial is None and current.trial_ref is not None:
                current.trial_applied = None
                current.trial_ref = None
            elif trial is not None and trial != current.trial_ref:
                current.trial_applied = now
                current.trial_ref = str(trial)
        elif current is not None and current.session_id == sid:
            self._close("page", now)
        return self.status()

    # ------------------------------------------------------------ lectures

    def _current(self, now: float) -> _Session | None:
        session = self._session
        if session is not None and now - session.seen > self.ttl_s:
            self._close("expired", now)
            return None
        return session

    def holder(self) -> str | None:
        """L'identifiant complet de la séance vivante (routage des commandes), ou `None`."""

        session = self._current(self._clock())
        return session.session_id if session is not None else None

    def active(self) -> bool:
        return self._current(self._clock()) is not None

    def status(self) -> dict[str, Any]:
        now = self._clock()
        session = self._current(now)
        if session is None:
            return {"active": False}
        return {"active": True, "session": session.session_id[:8], "exercise": session.exercise,
                "age_ms": round((now - session.opened) * 1000),
                "expires_in_ms": max(0, round((self.ttl_s - (now - session.seen)) * 1000)),
                "trial": session.trial_ref}

    def context(self) -> dict[str, Any] | None:
        """Le drapeau joint au tour du cerveau, ou `None` hors séance (contexte inchangé)."""

        session = self._current(self._clock())
        if session is None:
            return None
        return {"active": True, "exercise": session.exercise, "trial": session.trial_ref,
                "proposal": session.proposal_ref, "revision": session.revision,
                "events": [describe_calibration_event(event) for event in session.events[-8:]]}

    # ------------------------------------------------------------ événements

    def record_event(self, event: dict[str, Any]) -> bool:
        """Ranger un événement de la séance vivante (les `EVENTS_KEPT` derniers) ; `False` hors séance."""

        session = self._current(self._clock())
        if session is None:
            return False
        session.events.append(event)
        del session.events[:-EVENTS_KEPT]
        session.revision = max(session.revision, int(event.get("revision") or 0))
        return True

    def superseded(self, revision: int) -> bool:
        """Une transition du parcours plus récente que `revision` a-t-elle eu lieu ? (analyse caduque)"""

        session = self._current(self._clock())
        if session is None:
            return True
        return any(event["type"] in FLOW_TRANSITIONS and event["revision"] > revision for event in session.events)

    # ------------------------------------------------------------ paroles et accord

    def note_user_turn(self, text: str) -> bool:
        """Garder la phrase de l'utilisateur pour la vérification d'accord (séance ouverte seulement)."""

        now = self._clock()
        session = self._current(now)
        if session is None or not text.strip():
            return False
        session.utterances.append((now, text[:UTTERANCE_CHARS_MAX]))
        del session.utterances[:-UTTERANCES_MAX]
        return True

    def trial_applied(self, trial_ref: str | None) -> None:
        session = self._current(self._clock())
        if session is not None:
            session.trial_applied = self._clock()
            session.trial_ref = trial_ref

    def proposal_prepared(self, proposal_ref: str | None) -> None:
        """Une proposition vient d'être préparée : la fenêtre d'accord repart de maintenant."""

        session = self._current(self._clock())
        if session is not None:
            session.proposal_at = self._clock()
            session.proposal_ref = proposal_ref

    def proposal_closed(self) -> None:
        session = self._current(self._clock())
        if session is not None:
            session.proposal_at = None
            session.proposal_ref = None

    def trial_closed(self) -> None:
        session = self._current(self._clock())
        if session is not None:
            session.trial_applied = None
            session.trial_ref = None

    def consent(self, quote: str, *, proposal: bool = False) -> tuple[bool, str]:
        """La citation a-t-elle été dite **depuis** l'essai en cours (ou la proposition) ? `(trouvée, motif)`.

        Le motif dit ce qui manque, dans les mots que le cerveau doit relayer :
        pas d'essai, rien dit depuis, ou la citation n'y est pas mot pour mot.
        `proposal` : valider une proposition — la fenêtre part de sa
        préparation, et « applique », « vas-y », « on refait » accordent aussi.
        """

        session = self._current(self._clock())
        if session is None:
            return False, "aucune séance de calibration ouverte"
        if proposal:
            if session.proposal_at is None:
                return False, "aucune proposition préparée dans cette séance : il n'y a rien à valider"
            since = [said for at, said in session.utterances if at > session.proposal_at]
            if not since:
                return False, "l'utilisateur n'a rien dit depuis la proposition"
            return consent_found(quote, since, commit=True)
        if session.trial_applied is None:
            return False, "aucun essai appliqué dans cette séance : il n'y a rien à garder"
        since = [said for at, said in session.utterances if at > session.trial_applied]
        if not since:
            return False, "l'utilisateur n'a rien dit depuis l'application de l'essai"
        return consent_found(quote, since)

    # ------------------------------------------------------------ fin

    def close(self, why: str = "shutdown") -> None:
        """Fermer la séance tout de suite (arrêt, Bare Hands éteint)."""

        if self._session is not None:
            self._close(why, self._clock())

    def _close(self, why: str, now: float) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        self._log("barehands.calibration_session_closed", f"séance de calibration fermée ({why})",
                  {"session": session.session_id[:8], "why": why,
                   "duration_ms": round((now - session.opened) * 1000),
                   "utterances": len(session.utterances), "events": len(session.events)})
        session.utterances.clear()

    def _log(self, kind: str, message: str, data: dict[str, Any]) -> None:
        if self._emit is None:
            return
        try:
            self._emit(kind, message, data=data)
        except OSError:
            pass  # intentional: a full disk must not turn a declared session into a refused one


# ---------------------------------------------------------------- événements du parcours
#
# Retour utilisateur du 28/09 : l'assistant n'apprenait la fin d'un exercice que
# si l'utilisateur lui en parlait, et déduisait une validation à l'écran dix
# secondes plus tard d'un battement. La page envoie donc **chaque événement
# métier** de la calibration (`POST /api/barehands/calibration-event`), numéroté
# par une révision monotone de la séance :
#
#   stage_entered       un exercice commence (essai n°)
#   review_ready        il vient de se terminer : verdict, cause, résultats
#                       interprétés, valeurs, historique — l'écran attend une
#                       décision
#   decision_committed  validé, refait, passé ou accepté sans revérification,
#                       et l'étape d'après ; source bouton, voix ou panneau
#   proposal_ready      l'assistant a préparé une proposition (rien d'appliqué)
#   trial_applied       une proposition validée a été appliquée et relue
#   trial_resolved      un essai a été jugé
#   trial_rolled_back   un essai a été défait
#   report_ready        le rapport final est à l'écran
#
# Le Control Center garde les derniers (`CalibrationSessionRegistry.record_event`)
# et les joint à chaque tour du cerveau ; `review_ready` et `report_ready` ouvrent
# en plus un tour d'analyse dit à voix haute (accusé tout de suite, analyse
# ensuite). Une analyse qu'une transition plus récente a rendue caduque (l'étape
# a été validée pendant qu'il réfléchissait) n'est pas dite.

#: Ce que la voix dit tout de suite, avant l'analyse du cerveau : une analyse
#: prend plusieurs secondes, et le silence pendant ce temps se lisait « il ne
#: m'a pas entendu ». Rédigé par le Control Center, pas par le cerveau : c'est
#: un accusé de réception fixe, pas une réponse.
CALIBRATION_ANALYSIS_ACK = "Tes résultats viennent d'arriver, je les analyse."
#: Durée de vie de l'accusé (relais `ack`, tâche jarvis-voice-stale-speech-
#: presentation, Slice 03). Il ne vaut qu'au moment où les résultats arrivent :
#: « viennent d'arriver » est faux 15 s plus tard, et l'analyse (le vrai
#: contenu) arrive en quelques secondes. 15 s laissent finir une phrase en cours
#: de lecture (quelques secondes) sans laisser l'accusé survivre à l'écran qu'il
#: accompagne ; c'est trois fois plus court que l'échéance par défaut d'un
#: transitoire (`DEFAULT_TRANSIENT_SPEECH_TTL_S`, 45 s), pensée pour des étapes
#: de travail longues.
CALIBRATION_ACK_TTL_S = 15.0


def calibration_notice_key(event: dict) -> str:
    """Emplacement de parole partagé par l'accusé d'un évènement et son analyse.

    `calibration:<séance>:<révision>` : la révision numérote les évènements
    d'une séance, donc deux évènements n'ont jamais la même clé, et l'analyse
    d'un évènement remplace son propre accusé s'il n'a pas démarré
    (`supersedes_key`, règle de l'ordonnanceur vocal).
    """

    return f"calibration:{event['session']}:{event['revision']}"
#: Bornes du corps d'un événement (la page n'envoie que des mots d'écran).
EVENT_TEXT_MAX = 200
EVENT_LINES_MAX = 16
EVENT_TYPES = frozenset({"stage_entered", "review_ready", "decision_committed", "proposal_ready", "trial_applied",
                         "trial_resolved", "trial_rolled_back", "report_ready"})
#: Les événements qui ouvrent un tour d'analyse dit à voix haute.
ANALYSED_EVENT_TYPES = frozenset({"review_ready", "report_ready"})
#: Les transitions du parcours : une analyse plus ancienne qu'elles est caduque.
#: (Les propositions et essais que le cerveau déclenche **pendant** son analyse
#: ne la périment pas.)
FLOW_TRANSITIONS = frozenset({"stage_entered", "review_ready", "decision_committed", "report_ready"})
EVENT_SOURCES = ("ui", "voice", "panel", "brain")
ASSESSMENTS = ("good", "warning", "bad", "neutral")
#: Combien d'événements le Control Center garde pour le cerveau.
EVENTS_KEPT = 12
_STATUS_WORDS = {"ok": "réussi", "failed": "échoué", "skipped": "passé"}
_ASSESSMENT_WORDS = {"good": "bon", "warning": "à surveiller", "bad": "mauvais", "neutral": "sans jugement"}
_DECISION_WORDS = {"validated": "validé", "rerun": "à refaire", "skipped": "passé",
                   "accepted_unverified": "réglage accepté par l'utilisateur, non revérifié sur cet exercice"}
_WORD = re.compile(r"\A[a-z][a-z0-9_]{0,48}\Z")
_REF = re.compile(r"\A[a-z]{2}-[0-9]{1,9}\Z")
_TRIAL_KEY = re.compile(r"\A[a-z][A-Za-z0-9]{1,48}\Z")


def _clip(value: object, limit: int = EVENT_TEXT_MAX) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) and not isinstance(
        value, bool) else ""


def _texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for text in (_clip(item) for item in value[:EVENT_LINES_MAX]) if text]


def _rows(value: object, keys: tuple[str, ...]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [{key: _clip(item.get(key)) for key in keys} for item in value[:EVENT_LINES_MAX] if isinstance(item, dict)]


def _word(value: object, choices: tuple[str, ...] | frozenset[str] | None = None) -> str | None:
    if not isinstance(value, str) or not _WORD.match(value):
        return None
    return value if choices is None or value in choices else None


def _ref(value: object) -> str | None:
    return value if isinstance(value, str) and _REF.match(value) else None


def _count(value: object, minimum: int = 0) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= minimum else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (
            float("inf"), float("-inf")):
        return None
    return round(float(value), 4)


def _assessed(value: object, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Des lignes `{…, assessment, word}` : l'interprétation vient de la page, dans le vocabulaire fermé."""

    rows = _rows(value, keys + ("word",))
    raw = value if isinstance(value, list) else []
    for row, item in zip(rows, raw):
        row["assessment"] = _word(item.get("assessment"), ASSESSMENTS) or "neutral"
    return rows


def _review_context(value: object) -> dict[str, Any]:
    """Ce que la séance de l'agent joint à une revue : valeurs, historique, essais, ressentis."""

    if not isinstance(value, dict):
        return {"values": [], "history": [], "trials": [], "feedback": []}
    values = []
    for item in value["values"][:EVENT_LINES_MAX] if isinstance(value.get("values"), list) else []:
        key = item.get("key") if isinstance(item, dict) else None
        if not isinstance(key, str) or not _TRIAL_KEY.match(key):
            continue
        values.append({"key": key, "label": _clip(item.get("label")), "saved": _number(item.get("saved")),
                       "effective": _number(item.get("effective"))})
    history = [{"decision": _word(item.get("decision")), "status": _word(item.get("status")),
                "attempt": _count(item.get("attempt"), 1), "reason": _word(item.get("reason"))}
               for item in (value.get("history") or [])[:8] if isinstance(item, dict)] if isinstance(
        value.get("history"), list) else []
    trials = [{"ref": _ref(item.get("ref")), "cause": _word(item.get("cause")), "state": _word(item.get("state")),
               "verdict": _word(item.get("verdict")), "basis": _word(item.get("basis"))}
              for item in (value.get("trials") or [])[:4] if isinstance(item, dict)] if isinstance(
        value.get("trials"), list) else []
    feedback = [{"ref": _ref(item.get("ref")), "text": _clip(item.get("text"))}
                for item in (value.get("feedback") or [])[:3] if isinstance(item, dict)] if isinstance(
        value.get("feedback"), list) else []
    return {"values": values, "history": history, "trials": trials, "feedback": feedback}


def _proposal_keys(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:8]:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            continue
        out.append({"key": _clip(item["key"], 48), "label": _clip(item.get("label")),
                    "proposed": _number(item.get("proposed")), "effective": _number(item.get("effective")),
                    "saved": _number(item.get("saved"))})
    return out


def parse_calibration_event(body: object) -> dict[str, Any]:
    """Le corps d'un événement de calibration, borné et réduit aux champs connus.

    Lève `BarehandsCommandError` (400) sur un corps qui n'est pas un événement :
    `type` inconnu, séance absente, révision absente. Les champs de texte
    inconnus sont ignorés, les listes tronquées, chaque texte coupé à
    `EVENT_TEXT_MAX`, les mots hors vocabulaire mis à `None`.
    """

    if not isinstance(body, dict):
        raise BarehandsCommandError("barehands_bad_request", "corps attendu : un objet", 400)
    kind = body.get("type")
    if kind not in EVENT_TYPES:
        raise BarehandsCommandError("barehands_bad_request", f"type attendu : {', '.join(sorted(EVENT_TYPES))}", 400)
    revision = _count(body.get("revision"), 1)
    if revision is None:
        raise BarehandsCommandError("barehands_bad_request", "revision : entier ≥ 1 attendu", 400)
    stage = body.get("stage")
    event: dict[str, Any] = {
        "type": kind, "session": check_session_id(body.get("session")), "revision": revision,
        "stage": stage if isinstance(stage, str) and 0 < len(stage) <= EXERCISE_CHARS_MAX else None,
        "source": _word(body.get("source"), EVENT_SOURCES),
    }
    if kind == "stage_entered":
        event.update({"label": _clip(body.get("label")), "attempt": _count(body.get("attempt"), 1) or 1})
    elif kind == "review_ready":
        event.update({
            "label": _clip(body.get("label")),
            "status": body.get("status") if body.get("status") in _STATUS_WORDS else None,
            "reason": _clip(body.get("reason")),
            "cause": _clip(body.get("cause")),
            "checks": _assessed(body.get("checks"), ("label",)),
            "attempt": _count(body.get("attempt"), 1) or 1,
            "held": body.get("held") is True,
            "lines": _assessed(body.get("lines"), ("label", "text")),
            "context": _review_context(body.get("context")),
        })
    elif kind == "decision_committed":
        event.update({
            "decision": _word(body.get("decision"), tuple(_DECISION_WORDS)),
            "status": body.get("status") if body.get("status") in _STATUS_WORDS else None,
            "attempt": _count(body.get("attempt"), 1) or 1,
            "reason": _word(body.get("reason")),
            "next_stage": body.get("next_stage") if isinstance(body.get("next_stage"), str)
            and 0 < len(body["next_stage"]) <= EXERCISE_CHARS_MAX else None,
        })
    elif kind == "proposal_ready":
        event.update({"proposal_ref": _ref(body.get("proposal_ref")), "attempt": _count(body.get("attempt"), 1),
                      "summary": _clip(body.get("summary"), 300), "untouched": _clip(body.get("untouched"), 300),
                      "keys": _proposal_keys(body.get("keys"))})
    elif kind == "trial_applied":
        applied = body.get("applied") if isinstance(body.get("applied"), dict) else {}
        event.update({"proposal_ref": _ref(body.get("proposal_ref")), "trial_ref": _ref(body.get("trial_ref")),
                      "action": _word(body.get("action"), ("rerun", "continue")),
                      "verified": body.get("verified") is True,
                      "applied": {_clip(key, 48): _number(value) for key, value in list(applied.items())[:8]
                                  if isinstance(key, str) and not isinstance(value, dict)}})
    elif kind == "trial_resolved":
        event.update({"trial_ref": _ref(body.get("trial_ref")), "verdict": _word(body.get("verdict")),
                      "basis": _word(body.get("basis")), "status": _word(body.get("status"))})
    elif kind == "trial_rolled_back":
        event.update({"trial_ref": _ref(body.get("trial_ref"))})
    else:
        event.update({
            "saving": body.get("saving") is True,
            "stages": _rows(body.get("stages"), ("label", "status", "detail")),
            "will_save": _texts(body.get("willSave")),
            "kept": _texts(body.get("kept")),
            "trials": _texts(body.get("trials")),
        })
    return event


def _stage_name(event: dict[str, Any]) -> str:
    return event.get("label") or event.get("stage") or "l'exercice"


def describe_calibration_event(event: dict[str, Any]) -> str:
    """Une ligne française pour le fil que le cerveau lit à chaque tour (« r47 · C validé, essai 3 → pinch_primary »)."""

    kind = event["type"]
    head = f"r{event['revision']} · "
    source = f" (source : {event['source']})" if event.get("source") else ""
    if kind == "stage_entered":
        return f"{head}exercice ouvert : {_stage_name(event)} ({event.get('stage')}), essai n° {event.get('attempt')}"
    if kind == "review_ready":
        status = _STATUS_WORDS.get(event.get("status") or "", "terminé")
        return f"{head}revue prête : {_stage_name(event)} {status}, essai n° {event.get('attempt')}"
    if kind == "decision_committed":
        decision = _DECISION_WORDS.get(event.get("decision") or "", event.get("decision") or "?")
        after = event.get("next_stage")
        where = "rapport final" if after == "report" else (after or "—")
        reason = f", raison : {event['reason']}" if event.get("reason") else ""
        return (f"{head}décision : {event.get('stage')} {decision}{reason}, essai n° {event.get('attempt')} ; "
                f"maintenant : {where}{source}")
    if kind == "proposal_ready":
        keys = ", ".join(f"{k['key']} {k['effective']} → {k['proposed']}" for k in event.get("keys") or [])
        return f"{head}proposition {event.get('proposal_ref')} prête, NON appliquée : {keys}"
    if kind == "trial_applied":
        action = "exercice relancé" if event.get("action") == "rerun" else "gardé sans refaire l'exercice"
        verified = "valeurs relues" if event.get("verified") else "relecture absente"
        return (f"{head}proposition {event.get('proposal_ref')} appliquée ({event.get('trial_ref')}, {verified}), "
                f"{action}{source}")
    if kind == "trial_resolved":
        return f"{head}essai {event.get('trial_ref')} jugé : {event.get('verdict')} ({event.get('basis')})"
    if kind == "trial_rolled_back":
        return f"{head}essai {event.get('trial_ref')} défait{source}"
    return f"{head}rapport final à l'écran"


_EVENT_HEADER = (
    "[Événement de la calibration — personne n'a parlé : c'est l'écran qui t'écrit]\n"
    f"L'utilisateur vient d'entendre « {CALIBRATION_ANALYSIS_ACK} » : ne le redis pas, commence par ton analyse."
)
_EVENT_RULES = (
    "Réponds dans ce tour, toi-même, sans sous-agent. Les valeurs et leurs interprétations ci-dessus sont celles "
    "que le runtime a calculées et que l'écran affiche : tu peux les citer telles quelles, sans les arrondir ni en "
    "calculer d'autres, et tu ne contredis jamais une interprétation (« mauvais » n'est pas « correct »). "
    "calibration_status donne le détail si tu en as besoin. Pour cette analyse : trois phrases au plus, "
    "quarante-cinq mots au plus, en mots d'utilisateur, sans nom de paramètre."
)


def _value_text(value: object) -> str:
    return "—" if value is None else f"{value:g}".replace(".", ",") if isinstance(value, float) else str(value)


def render_calibration_event(event: dict[str, Any]) -> str:
    """La demande que le cerveau reçoit pour un événement analysé (texte français)."""

    lines = [_EVENT_HEADER, f"Révision de séance : {event['revision']}."]
    if event["type"] == "review_ready":
        label = _stage_name(event)
        status = _STATUS_WORDS.get(event.get("status") or "", "terminé")
        head = f"L'exercice « {label} » ({event.get('stage')}) vient de se terminer : {status}, essai n° {event.get('attempt') or 1}"
        if event.get("reason"):
            head += f", motif : {event['reason']}"
        lines.append(head + ". L'écran est sur sa revue et attend une décision de l'utilisateur.")
        if event.get("cause"):
            lines.append(f"Cause constatée par le moteur : {event['cause']}")
        if event.get("checks"):
            lines.append("Critères, un par un (runtime) :")
            lines.extend(f"- {row['label']} : {row['word']} [{row['assessment']}]" for row in event["checks"]
                         if row.get("label"))
        if event.get("lines"):
            lines.append("Résultats (valeur — interprétation du runtime) :")
            lines.extend(f"- {row['label']} : {row['text']} — {row['word'] or _ASSESSMENT_WORDS[row['assessment']]} "
                         f"[{row['assessment']}]" for row in event["lines"] if row.get("label"))
        else:
            lines.append("Aucune mesure chiffrée pour cet exercice : il se juge sur le geste lui-même.")
        context = event.get("context") or {}
        if context.get("values"):
            lines.append("Réglages qui concernent cet exercice (enregistré → effectif maintenant) :")
            lines.extend(f"- {row['key']} ({row['label']}) : {_value_text(row['saved'])} → {_value_text(row['effective'])}"
                         for row in context["values"])
        if context.get("history"):
            lines.append("Historique de cet exercice : " + " ; ".join(
                f"essai {row['attempt']} {row['status']} → {_DECISION_WORDS.get(row['decision'] or '', row['decision'])}"
                for row in context["history"]) + ".")
        if context.get("trials"):
            lines.append("Essais sur cet exercice : " + " ; ".join(
                f"{row['ref']} ({row['cause']}) {row['state']}, verdict {row['verdict'] or 'non jugé'}"
                for row in context["trials"]) + ".")
        if context.get("feedback"):
            lines.append("Ressentis notés : " + " ; ".join(f"{row['ref']} « {row['text']} »" for row in context["feedback"])
                         + ".")
        if event.get("held"):
            lines.append("Un réglage d'essai attend d'être jugé sur cet exercice : ces mesures ont été prises sous lui "
                         "(juge-le avec calibration_resolve_trial).")
        lines.append(
            "Analyse ces résultats pour l'utilisateur :\n"
            "- d'abord ton verdict : tout va bien, ou ce qui cloche d'après la cause et les interprétations "
            "ci-dessus, et ce qu'il a probablement ressenti ;\n"
            "- si un réglage semble pertinent, PRÉPARE-le (calibration_propose_hypothesis puis "
            "calibration_prepare_trial, avec summary en mots d'utilisateur) : il s'affiche dans le panneau, "
            "NON appliqué ; dis ce qu'il changerait pour lui ;\n"
            "- termine par une question simple (« je l'applique et on refait ? », « on passe à la suite ? »). "
            "Tu n'appliques rien, tu ne valides rien et tu n'avances pas le parcours dans ce tour : c'est "
            "l'utilisateur qui décide (panneau, bouton ou parole)."
        )
    else:
        lines.append("La calibration est terminée : l'écran montre le rapport final.")
        if event.get("stages"):
            lines.append("Exercice par exercice :")
            lines.extend(f"- {row['label']} : {row['detail'] or row['status']}" for row in event["stages"] if row.get("label"))
        if event.get("will_save"):
            lines.append("« Enregistrer » rangera : " + " ; ".join(event["will_save"]) + ".")
        elif not event.get("saving"):
            lines.append("Aucune mesure n'a été retenue : il n'y a rien à enregistrer.")
        if event.get("kept"):
            lines.append("Conservé du profil d'avant : " + " ; ".join(event["kept"]) + ".")
        if event.get("trials"):
            lines.append("Réglages déjà gardés pendant la séance : " + " ; ".join(event["trials"]) + ".")
        lines.append(
            "Fais-lui le bilan : ce qui va bien, ce qui reste fragile s'il y en a, et dis-lui que « Enregistrer » "
            "range ces mesures (ou qu'il n'y a rien à enregistrer). Un réglage « accepté par l'utilisateur, non "
            "revérifié » se dit tel quel, jamais « validé par la calibration ». Termine en lui demandant s'il "
            "enregistre."
        )
    lines.append(_EVENT_RULES)
    return "\n".join(lines)
