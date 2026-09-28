"""Commandes de calibration du cerveau (tâche adaptative, Slice 06, décisions 50 à 55).

L'« agent de calibration » est le cerveau existant en **mode calibration**
(READINESS D1) : ses outils `calibration_*` sont déclarés en permanence par le
serveur `jarvis-barehands` et **refusent** hors d'une séance ouverte à l'écran.
Ils voyagent par le canal de commandes de la Slice 12 (§ 12 du contrat), étendu
ici (READINESS D2) :

- une commande de calibration porte une **charge utile bornée**, validée ici
  par un schéma fermé propre à chaque commande (`parse_calibration_payload`) ;
- son reçu porte un **résultat structuré** borné, lui aussi fermé par commande
  (`parse_calibration_result`) ;
- les cinq commandes d'avant gardent exactement leurs garanties : pas de charge
  utile, reçu `{outcome, lifecycle, code, reason}` ≤ 1 Ko, codes de
  `barehands_command.PAGE_CODES`.

Ce module ne tient que le vocabulaire, les bornes et les formes : sans E/S,
partagé par le courtier, la route du Control Center et le serveur MCP. La
**sémantique** (une hypothèse démentie ne se réessaie pas, un essai se juge sur
les mesures, une acceptation exige un accord) vit dans la page, dans
`control_center_barehands_calibration_agent.js`, parce que c'est elle qui
détient la séance (décision 41 : la preuve ne quitte pas la page).

**Miroirs.** Les vocabulaires fermés recopiés ici (catégories de retour, causes,
verdicts, métriques, résumés, clés d'essai) sont ceux du § 12 de
`control_center_barehands_contracts.js`. Ils ont désormais un lecteur Python —
le schéma d'entrée des outils, qui montre au cerveau les mots permis —, donc la
décision 42 permet le miroir, tenu par un test de parité qui exécute le contrat
sous node (`tests/unit/test_barehands_calibration_agent.py`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from jarvis.domain.barehands_command import COMMAND_UNKNOWN, FLOW_ABSENT, BarehandsCommandError

#: Les dix commandes de calibration, une par outil et **du même nom** : la
#: table outil → commande est l'identité, un test la tient.
#:
#: **Le cerveau propose, l'utilisateur décide** (retour du 28/09) : il n'y a
#: plus de commande « applique cet essai ». `calibration_prepare_trial` rend
#: une proposition **visible** (rien n'est appliqué) ; `calibration_commit_proposal`
#: l'applique seulement sur l'accord de l'utilisateur, retrouvé par le Control
#: Center dans ce qu'il a dit depuis la proposition, et par une transaction de
#: la page (appliquer, relire, refaire ou garder).
CALIBRATION_COMMANDS: tuple[str, ...] = (
    "calibration_status",
    "calibration_record_feedback",
    "calibration_propose_hypothesis",
    "calibration_prepare_trial",
    "calibration_commit_proposal",
    "calibration_resolve_trial",
    "calibration_rollback_trial",
    "calibration_accept_trial",
    "calibration_rerun_exercise",
    "calibration_next_exercise",
)

#: Bornes du fil. La demande du cerveau reste petite (un patch de huit clés, une
#: issue d'essai de quelques références) ; le reçu peut porter l'état d'une
#: séance (`calibration_status`) : 16 Ko, sous ce qu'un tour de modèle lit sans
#: se noyer, et quinze fois le reçu d'une commande de cycle de vie, qui garde
#: ses 1 024 octets.
MAX_CALIBRATION_REQUEST_BYTES = 4_096
MAX_CALIBRATION_RECEIPT_BYTES = 16_384

#: Codes de refus que la page rend pour une commande de calibration — liste
#: fermée, comme `PAGE_CODES`. Le refus **précis** du contrat
#: (`barehands_trial_invariant_violated`, `barehands_feedback_too_many_categories`…)
#: voyage dans `result.errors`, sous un motif vérifié : une cinquantaine de codes
#: du contrat ne se recopient pas ici un par un, et le code de tête reste fermé.
CALIBRATION_INACTIVE = "barehands_calibration_inactive"
CALIBRATION_REFUSED = "barehands_calibration_refused"
CALIBRATION_PAGE_CODES: tuple[str, ...] = (CALIBRATION_INACTIVE, CALIBRATION_REFUSED, FLOW_ABSENT, COMMAND_UNKNOWN)
#: Côté serveur : `calibration_accept_trial` sans accord de l'utilisateur
#: retrouvé dans ce qu'il a dit depuis l'essai (décision 53).
CONSENT_MISSING = "barehands_calibration_consent_missing"
#: Côté serveur MCP de réglages : `settings_set barehands.assistance|sensitivity`
#: pendant une séance (décision 54).
CALIBRATION_ACTIVE = "barehands_calibration_active"
#: Côté serveur : une seconde page déclare une séance pendant qu'une autre vit.
SESSION_BUSY = "barehands_calibration_session_busy"

#: Séance vue par le serveur (décision 50) : la page la déclare, puis la
#: confirme toutes les `HEARTBEAT_S` ; sans nouvelle depuis `SESSION_TTL_S`,
#: elle est échue. Trois battements manqués : un onglet fermé sans `pagehide`,
#: une page gelée ou un Control Center redémarré ne laissent pas le cerveau en
#: mode calibration.
HEARTBEAT_S = 10.0
SESSION_TTL_S = 30.0

#: Identifiant de séance choisi par la page (aléatoire).
_SESSION_ID = re.compile(r"\A[A-Za-z0-9_-]{16,64}\Z")

# ------------------------------------------------------------------ miroirs du contrat (§ 12)

FEEDBACK_CATEGORIES: tuple[str, ...] = (
    "fine", "press_missed", "false_click", "release_sticky", "release_early", "drag_starts_too_early",
    "drag_hard_to_start", "hard_to_aim", "wrong_target", "jumpy_pointer", "laggy", "pointer_unwanted",
    "wake_hard", "unclear",
)
HYPOTHESIS_CAUSES: tuple[str, ...] = (
    "press_threshold_too_strict", "press_threshold_too_loose", "release_threshold_too_far",
    "release_confirmation_too_slow", "release_confirmation_too_fast", "click_drag_separation_too_tight",
    "click_drag_separation_too_loose", "pointer_filter_too_smooth", "pointer_filter_too_noisy",
    "stillness_misjudged", "target_assist_too_weak", "target_assist_too_strong", "zone_hysteresis_too_narrow",
    "wake_too_sensitive", "wake_too_strict", "pointer_shown_without_intent", "tracking_quality", "user_learning",
)
HYPOTHESIS_STATUSES: tuple[str, ...] = ("open", "supported", "weakened", "rejected")
TRIAL_VERDICTS: tuple[str, ...] = ("improved", "no_change", "worse", "inconclusive")
METRIC_AGGREGATES: tuple[str, ...] = ("p50", "p95", "mean", "max", "count")
CALIBRATION_METRICS: tuple[str, ...] = (
    "press_latency_ms", "release_latency_ms", "episode_duration_ms", "episode_min_ratio", "open_baseline_ratio",
    "closing_velocity", "opening_velocity", "episode_travel_px", "episode_quality", "missed_press_rate",
    "missed_release_rate", "false_press_rate", "false_secondary_press_rate", "unintended_wake_rate",
    "unintended_target_rate", "unintended_pointer_rate", "pointer_jitter_px", "c_pose_gap_palms", "c_pose_fold_palms", "pointer_lag_ms", "acquisition_ms",
    "missed_click_count", "wrong_target_count", "false_click_count", "premature_drop_count",
    "reacquisition_count", "placement_error_px", "target_ambiguity", "drag_success_rate", "transition_ms",
    "timeout_count",
)
TRIAL_KEYS: tuple[str, ...] = (
    "pressRatio", "releaseRatio", "secondaryPressRatio", "secondaryReleaseRatio", "pressFrames",
    "releaseFrames", "releaseMs", "releaseDeltaRatio", "releaseDoubtMaxMs", "clickSlopPx", "dragSlopPx",
    "clickMaxMs", "clickStillnessMin", "minCutoffHz", "betaCutoff", "stillSpeedPx", "moveSpeedPx", "assistance",
    "targetZonePx", "targetZoneHoldPx", "targetSwitchPx", "targetAmbiguityMax", "targetHoldRatio", "wakeHoldMs",
    "wakeScore", "wakeGapMin", "pointingEnterScore", "pointingExitScore", "pointingEnterMs", "pointingExitMs",
    "pointingMotionFloor", "pointingFoldStartPalms", "pointingFoldEndPalms",
)
#: Les étapes (exercices) de la calibration (`STAGE` du contrat) : ce que
#: `calibration_rerun_exercise` peut nommer, et ce qu'un essai liste.
STAGES: tuple[str, ...] = (
    "neutral", "c_pose", "pinch_primary", "hold_release", "pinch_secondary", "aim", "drag", "resize", "drop",
    "natural_motion", "aim_no_click",
)
#: Les raisons de passer un exercice (`SKIP_REASONS` du contrat), mot court :
#: ce que `calibration_next_exercise.reason` peut dire (Slice 07, décision 57).
SKIP_REASONS: tuple[str, ...] = ("not_relevant", "cannot_perform", "tracking", "later")
#: Les décisions de revue d'un exercice que `calibration_status.reviews` rapporte.
#: `accepted_unverified` : l'utilisateur a gardé un réglage sans refaire
#: l'exercice (« Appliquer et continuer ») — jamais « validé par la calibration ».
REVIEW_DECISIONS: tuple[str, ...] = ("validated", "rerun", "skipped", "accepted_unverified")
#: Ce qu'une validation de proposition fait ensuite (`calibration_commit_proposal`).
COMMIT_ACTIONS: tuple[str, ...] = ("rerun", "continue")
#: États d'une proposition, et étapes du reçu de sa validation.
PROPOSAL_STATES: tuple[str, ...] = ("pending", "committed", "stale", "discarded", "superseded")
COMMIT_STEPS: tuple[str, ...] = ("applied", "verified", "rerun", "saved", "advanced")
#: Sur quoi repose un essai gardé : mesure, ressenti, rien, ou la seule
#: décision de l'utilisateur sans nouvelle mesure (« non revérifié »).
TRIAL_BASES: tuple[str, ...] = ("measured", "feeling", "none", "user_unverified")
#: Préfixes de référence de séance (`SESSION_REF`) et ceux qu'une mesure peut porter.
MEASUREMENT_REF_KINDS: tuple[str, ...] = ("se", "ep", "ng", "bm", "ex")

# Bornes des listes (le contrat refuse au-delà de 32 — `ADAPTIVE_LIST_MAX` —,
# celles-ci sont plus serrées parce que c'est un modèle qui écrit).
FEEDBACK_TEXT_MAX = 500
FEEDBACK_CATEGORIES_MAX = 3
EVIDENCE_MAX = 6
SOURCE_REFS_MAX = 24
FEEDBACK_REFS_MAX = 8
COMPARISONS_MAX = 8
OUTCOME_REFS_MAX = 32
PATCH_KEYS_MAX = 8
QUOTE_MAX = 200
QUOTE_MIN = 2
#: La phrase d'une proposition (ce qu'elle change, ce qu'elle ne touche pas).
PROPOSAL_TEXT_MAX = 300

_REF = re.compile(r"\A([a-z]{2})-(\d{1,9})\Z")
_ERROR_CODE = re.compile(r"\Abarehands_[a-z0-9_]{2,64}\Z")
_METRIC_KEY = re.compile(r"\A[a-z][a-z0-9_]{1,48}\Z")
_TRIAL_KEY = re.compile(r"\A[a-z][A-Za-z0-9]{1,48}\Z")
_WORD = re.compile(r"\A[a-z][a-z0-9_]{0,48}\Z")


def is_calibration_command(name: object) -> bool:
    return isinstance(name, str) and name in CALIBRATION_COMMANDS


def check_session_id(value: object) -> str:
    if not isinstance(value, str) or not _SESSION_ID.match(value):
        raise BarehandsCommandError(
            "barehands_bad_request", "session : 16 à 64 caractères de [A-Za-z0-9_-]", 400)
    return value


# ------------------------------------------------------------------ petits validateurs (fermés)

class _Bad(ValueError):
    """Faute de forme ; `where` dit laquelle, pour un message qui nomme le champ."""


Validator = Callable[[Any, str], Any]


def _fail(where: str, message: str) -> None:
    raise _Bad(f"{where} : {message}")


def _number(minimum: float | None = None, maximum: float | None = None) -> Validator:
    def check(value: Any, where: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (
                float("inf"), float("-inf")):
            _fail(where, "nombre fini attendu")
        if minimum is not None and value < minimum:
            _fail(where, f"au moins {minimum:g}")
        if maximum is not None and value > maximum:
            _fail(where, f"au plus {maximum:g}")
        return value
    return check


def _nullable(inner: Validator) -> Validator:
    def check(value: Any, where: str) -> Any:
        return None if value is None else inner(value, where)
    return check


def _string(maximum: int, minimum: int = 0) -> Validator:
    def check(value: Any, where: str) -> str:
        if not isinstance(value, str):
            _fail(where, "chaîne attendue")
        if len(value) > maximum:
            _fail(where, f"{maximum} caractères au plus")
        if len(value.strip()) < minimum:
            _fail(where, f"{minimum} caractère(s) au moins")
        return value
    return check


def _bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        _fail(where, "booléen attendu")
    return value


def _word(choices: tuple[str, ...] | None = None, pattern: re.Pattern[str] = _WORD) -> Validator:
    def check(value: Any, where: str) -> str:
        if not isinstance(value, str) or not pattern.match(value):
            _fail(where, "mot attendu")
        if choices is not None and value not in choices:
            _fail(where, f"« {value} » hors vocabulaire ({', '.join(choices[:8])}{'…' if len(choices) > 8 else ''})")
        return value
    return check


def _ref(kinds: tuple[str, ...]) -> Validator:
    def check(value: Any, where: str) -> str:
        match = _REF.match(value) if isinstance(value, str) else None
        if match is None or match.group(1) not in kinds:
            _fail(where, f"référence de séance {'/'.join(kinds)}-N attendue")
        return value
    return check


def _list(item: Validator, maximum: int, minimum: int = 0, unique: bool = False) -> Validator:
    def check(value: Any, where: str) -> list[Any]:
        if not isinstance(value, list):
            _fail(where, "liste attendue")
        if len(value) > maximum:
            _fail(where, f"{maximum} éléments au plus")
        if len(value) < minimum:
            _fail(where, f"{minimum} élément(s) au moins")
        out = [item(entry, f"{where}[{index}]") for index, entry in enumerate(value)]
        if unique and len({repr(entry) for entry in out}) != len(out):
            _fail(where, "doublon")
        return out
    return check


def _object(fields: Mapping[str, Validator], optional: tuple[str, ...] = ()) -> Validator:
    """Objet **fermé** : toute clé inconnue est refusée, toute clé non facultative est exigée."""

    def check(value: Any, where: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            _fail(where, "objet attendu")
        unknown = sorted(set(value) - set(fields))
        if unknown:
            _fail(where, "clé inconnue : " + ", ".join(str(key)[:40] for key in unknown[:6]))
        out: dict[str, Any] = {}
        for key, validator in fields.items():
            if key not in value:
                if key in optional:
                    continue
                _fail(where, f"{key} absent")
            out[key] = validator(value[key], f"{where}.{key}")
        return out
    return check


def _map(key: re.Pattern[str], item: Validator, maximum: int) -> Validator:
    def check(value: Any, where: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            _fail(where, "objet attendu")
        if len(value) > maximum:
            _fail(where, f"{maximum} clés au plus")
        out: dict[str, Any] = {}
        for name, entry in value.items():
            if not isinstance(name, str) or not key.match(name):
                _fail(where, f"clé « {str(name)[:40]} » hors forme")
            out[name] = item(entry, f"{where}.{name}")
        return out
    return check


#: Une valeur d'essai relue : un nombre, `null` (non lu), ou par main quand les
#: mains diffèrent (`shownValue` du gestionnaire d'essai, décision 48).
_HANDED = _object({"left": _nullable(_number()), "right": _nullable(_number()), "unknown": _nullable(_number())},
                  optional=("left", "right", "unknown"))


def _trial_value(value: Any, where: str) -> Any:
    if isinstance(value, dict):
        return _HANDED(value, where)
    return _nullable(_number())(value, where)


_VALUES = _map(_TRIAL_KEY, _trial_value, len(TRIAL_KEYS))
_MEASURE_REF = _ref(MEASUREMENT_REF_KINDS)
_FEEDBACK_REF = _ref(("fb",))
_EVIDENCE_REF = _ref(("ev",))
_HYPOTHESIS_REF = _ref(("hy",))
_TRIAL_REF = _ref(("tr",))
_EXERCISE_REF = _ref(("ex",))
_PROPOSAL_REF = _ref(("pr",))
_CATEGORY = _word(FEEDBACK_CATEGORIES)
_CAUSE = _word(HYPOTHESIS_CAUSES)
_METRIC = _word(CALIBRATION_METRICS)
_AGGREGATE = _word(METRIC_AGGREGATES)
_STAGE = _nullable(_word())
_COMPARISON = _object({"metric": _METRIC, "aggregate": _AGGREGATE})
_PATCH = _map(re.compile(r"\A(?:" + "|".join(TRIAL_KEYS) + r")\Z"), _number(), PATCH_KEYS_MAX)

# ------------------------------------------------------------------ charges utiles (cerveau → page)

_NO_PAYLOAD = _object({})
_PAYLOADS: dict[str, Validator] = {
    "calibration_status": _NO_PAYLOAD,
    "calibration_record_feedback": _object({
        "categories": _list(_CATEGORY, FEEDBACK_CATEGORIES_MAX, minimum=1, unique=True),
        "text": _string(FEEDBACK_TEXT_MAX, minimum=1),
    }),
    "calibration_propose_hypothesis": _object({
        "cause": _CAUSE,
        "confidence": _number(0.0, 1.0),
        "evidence": _list(_object({"metric": _METRIC, "aggregate": _AGGREGATE,
                                   "sourceRefs": _list(_MEASURE_REF, SOURCE_REFS_MAX, minimum=1, unique=True)}),
                          EVIDENCE_MAX),
        "feedbackRefs": _list(_FEEDBACK_REF, FEEDBACK_REFS_MAX, unique=True),
    }),
    # Une proposition visible, **rien n'est appliqué** : la cause testée, les
    # valeurs proposées, et en mots d'utilisateur ce qu'elle change (et ce
    # qu'elle ne touche pas).
    "calibration_prepare_trial": _object({
        "hypothesisRef": _HYPOTHESIS_REF, "patch": _PATCH,
        "summary": _string(PROPOSAL_TEXT_MAX, minimum=2),
        "untouched": _string(PROPOSAL_TEXT_MAX),
    }, optional=("untouched",)),
    # Ce que le **cerveau** envoie ; la route le remplace par l'accord vérifié
    # (`commit_payload`) : le cerveau n'écrit jamais `verified`.
    "calibration_commit_proposal": _object({
        "proposalRef": _PROPOSAL_REF, "action": _word(COMMIT_ACTIONS),
        "userQuote": _string(QUOTE_MAX, minimum=QUOTE_MIN),
    }),
    "calibration_resolve_trial": _object({
        "trialRef": _TRIAL_REF,
        "verdict": _word(TRIAL_VERDICTS),
        "comparisons": _list(_COMPARISON, COMPARISONS_MAX, unique=True),
        "beforeRefs": _list(_MEASURE_REF, OUTCOME_REFS_MAX, unique=True),
        "afterRefs": _list(_MEASURE_REF, OUTCOME_REFS_MAX, unique=True),
        "feedbackRefs": _list(_FEEDBACK_REF, FEEDBACK_REFS_MAX, unique=True),
    }),
    "calibration_rollback_trial": _NO_PAYLOAD,
    # Ce que le **cerveau** envoie. La route le remplace, après vérification,
    # par l'accord que la page lit (`consent_payload`) : le cerveau n'écrit
    # jamais `verified`.
    "calibration_accept_trial": _object({"userQuote": _string(QUOTE_MAX, minimum=QUOTE_MIN)}),
    # L'exercice à refaire, nommé (liste fermée) ; absent : celui de l'essai
    # non jugé en cours, ou le dernier joué.
    "calibration_rerun_exercise": _object({"exercise": _word(STAGES)}, optional=("exercise",)),
    # Valider la revue de l'exercice, ou le passer : passer (exercice non
    # soldé, ou échoué) exige une raison de la liste fermée (décision 57).
    "calibration_next_exercise": _object({"reason": _word(SKIP_REASONS)}, optional=("reason",)),
}


def parse_calibration_payload(name: str, raw: object) -> dict[str, Any]:
    """La charge utile d'une commande de calibration, validée ; `BarehandsCommandError` sinon.

    Absente vaut `{}` (commande sans argument). Une propriété inconnue, une
    valeur hors vocabulaire ou une liste trop longue se refusent **avant** toute
    remise à la page : rien ne part.
    """

    validator = _PAYLOADS[name]
    try:
        payload = validator({} if raw is None else raw, "payload")
    except _Bad as exc:
        raise BarehandsCommandError("barehands_bad_request", str(exc), 400) from None
    if name == "calibration_propose_hypothesis" and not payload["evidence"] and not payload["feedbackRefs"]:
        raise BarehandsCommandError(
            "barehands_bad_request", "payload : une hypothèse cite au moins une preuve ou un retour", 400)
    if name == "calibration_prepare_trial" and not payload["patch"]:
        raise BarehandsCommandError("barehands_bad_request", "payload.patch : au moins une clé d'essai", 400)
    return payload


def consent_payload(quote: str) -> dict[str, Any]:
    """Ce que la page reçoit pour `calibration_accept_trial` une fois l'accord **retrouvé** par le serveur."""

    return {"consent": {"source": "voice", "quote": quote, "verifiedBy": "control_center"}}


def commit_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que la page reçoit pour `calibration_commit_proposal` une fois l'accord **retrouvé** par le serveur."""

    return {"proposalRef": payload["proposalRef"], "action": payload["action"],
            **consent_payload(str(payload["userQuote"]))}


# ------------------------------------------------------------------ résultats (page → cerveau)

_FEEDBACK_ROW = _object({"ref": _FEEDBACK_REF, "categories": _list(_CATEGORY, FEEDBACK_CATEGORIES_MAX),
                         "text": _string(FEEDBACK_TEXT_MAX), "source": _word(("voice", "ui")),
                         "t": _number(0), "stage": _STAGE, "exerciseRef": _nullable(_EXERCISE_REF)})
_EVIDENCE_ROW = _object({"ref": _EVIDENCE_REF, "metric": _nullable(_METRIC), "aggregate": _nullable(_AGGREGATE),
                         "sourceRefs": _list(_MEASURE_REF, SOURCE_REFS_MAX),
                         "feedbackRefs": _list(_FEEDBACK_REF, FEEDBACK_REFS_MAX),
                         "value": _nullable(_number())})
_HYPOTHESIS_ROW = _object({"ref": _HYPOTHESIS_REF, "cause": _CAUSE, "confidence": _number(0, 1),
                           "status": _word(HYPOTHESIS_STATUSES),
                           "evidenceRefs": _list(_EVIDENCE_REF, 32), "feedbackRefs": _list(_FEEDBACK_REF, 32),
                           "trialRefs": _list(_TRIAL_REF, 32),
                           "trialKeys": _list(_word(TRIAL_KEYS, _TRIAL_KEY), len(TRIAL_KEYS))})
_DELTA_ROW = _object({"metric": _METRIC, "aggregate": _AGGREGATE, "before": _nullable(_number()),
                      "after": _nullable(_number()), "delta": _nullable(_number()),
                      "direction": _nullable(_word(("better", "worse", "same")))})
_TRIAL_ROW = _object({"ref": _TRIAL_REF, "hypothesisRef": _HYPOTHESIS_REF, "baseRef": _nullable(_TRIAL_REF),
                      "patch": _VALUES, "applied": _VALUES,
                      "state": _word(("active", "rolled_back", "accepted")),
                      "verdict": _nullable(_word(TRIAL_VERDICTS)), "deltas": _list(_DELTA_ROW, COMPARISONS_MAX),
                      "appliedAt": _number(0), "exercises": _list(_word(STAGES), len(STAGES)),
                      # L'état effectif sur lequel l'essai a été appliqué, et le sien.
                      "baseStateId": _number(0), "stateId": _number(0),
                      # Sur quoi repose le verdict : mesure, avis seul, rien, ou
                      # la seule décision de l'utilisateur (non revérifié).
                      "basis": _nullable(_word(TRIAL_BASES))})
_MEASUREMENT_ROW = _object({"ref": _MEASURE_REF, "stage": _STAGE, "exerciseRef": _nullable(_EXERCISE_REF),
                            "trialRef": _nullable(_TRIAL_REF), "stateId": _nullable(_number(0)),
                            # Ms de séance, même horloge que `feedback.t` et `appliedAt` (décision 58).
                            "t": _nullable(_number(0)),
                            "metrics": _map(_METRIC_KEY, _nullable(_number()), len(CALIBRATION_METRICS))})
_EXERCISE = _object({"step": _STAGE, "phase": _nullable(_word()), "running": _bool,
                     "finished": _bool})
#: Une décision de revue (Slice 07, décision 56) : l'exercice, ce qui a été
#: décidé, son verdict, la raison d'un passage, l'essai n° et l'instant (ms de séance).
_REVIEW_ROW = _object({"stage": _word(STAGES), "decision": _word(REVIEW_DECISIONS),
                       "status": _word(("ok", "failed", "skipped")),
                       "reason": _nullable(_word(SKIP_REASONS)), "attempt": _number(1), "t": _number(0)})
#: Une valeur proposée, telle que l'écran la montre (retour du 28/09) :
#: proposée par le cerveau, corrigée ou non par l'utilisateur, à côté de
#: l'enregistrée et de l'effective relues.
_PROPOSAL_KEY = _object({"key": _word(TRIAL_KEYS, _TRIAL_KEY), "proposed": _number(), "value": _number(),
                         "effective": _nullable(_number()), "saved": _nullable(_number()), "perHand": _bool,
                         "min": _number(), "max": _number(), "step": _number(), "unit": _word()})
_COMMIT_RECEIPT = _object({"action": _word(COMMIT_ACTIONS), "steps": _list(_word(COMMIT_STEPS), len(COMMIT_STEPS)),
                           "trialRef": _TRIAL_REF, "ok": _bool, "attempt": _nullable(_number(1)),
                           "decision": _nullable(_word(("rerun", "accepted_unverified")))},
                          optional=("attempt", "decision"))
_PROPOSAL_ROW = _object({
    "ref": _PROPOSAL_REF, "state": _word(PROPOSAL_STATES), "hypothesisRef": _HYPOTHESIS_REF, "cause": _CAUSE,
    "stage": _word(STAGES), "attempt": _number(1), "summary": _string(PROPOSAL_TEXT_MAX),
    "untouched": _nullable(_string(PROPOSAL_TEXT_MAX)), "version": _number(1), "rerunStage": _nullable(_word(STAGES)),
    "keys": _list(_PROPOSAL_KEY, PATCH_KEYS_MAX),
    "errors": _list(_object({"key": _nullable(_string(60)), "code": _word(pattern=_ERROR_CODE),
                             "message": _string(300)}), 16),
    "receipt": _nullable(_COMMIT_RECEIPT),
})
_CONFIDENCE_ROW = _object({"ref": _HYPOTHESIS_REF, "cause": _CAUSE, "before": _number(0, 1),
                           "confidence": _number(0, 1), "status": _word(HYPOTHESIS_STATUSES)})

_RESULTS: dict[str, Validator] = {
    "calibration_status": _object({
        "exercise": _EXERCISE,
        "values": _object({"effective": _VALUES, "saved": _VALUES, "trial": _VALUES}),
        "measurements": _list(_MEASUREMENT_ROW, 24),
        "measurementCount": _number(0),
        "feedback": _list(_FEEDBACK_ROW, 12),
        "evidence": _list(_EVIDENCE_ROW, 12),
        "hypotheses": _list(_HYPOTHESIS_ROW, 16),
        "trials": _list(_TRIAL_ROW, 10),
        # Les dernières décisions de revue d'exercice (Slice 07).
        "reviews": _list(_REVIEW_ROW, 12),
        # La proposition en cours, ou `null` (retour du 28/09).
        "proposal": _nullable(_PROPOSAL_ROW),
        # La révision du dernier événement de la séance (monotone).
        "revision": _number(0),
        # Lignes retirées pour tenir le budget du reçu (les plus anciennes).
        "truncated": _object({"measurements": _number(0), "feedback": _number(0), "evidence": _number(0),
                              "trials": _number(0)}),
    }),
    "calibration_record_feedback": _object({
        "feedback": _FEEDBACK_ROW,
        "suggestedCauses": _list(_CAUSE, len(HYPOTHESIS_CAUSES)),
    }),
    "calibration_propose_hypothesis": _object({
        "hypothesis": _HYPOTHESIS_ROW,
        "evidence": _list(_EVIDENCE_ROW, EVIDENCE_MAX),
    }),
    # La proposition telle que l'écran la montre : **rien n'est appliqué**.
    "calibration_prepare_trial": _object({"proposal": _PROPOSAL_ROW}),
    # La transaction entière : appliqué, relu, puis refait ou gardé et avancé.
    "calibration_commit_proposal": _object({
        "proposalRef": _PROPOSAL_REF, "action": _word(COMMIT_ACTIONS), "trialRef": _TRIAL_REF,
        "applied": _VALUES, "verified": _bool, "steps": _list(_word(COMMIT_STEPS), len(COMMIT_STEPS)),
        "exercise": _EXERCISE, "decision": _word(("rerun", "accepted_unverified")),
        "attempt": _nullable(_number(1)),
    }),
    "calibration_resolve_trial": _object({
        "trialRef": _TRIAL_REF, "verdict": _word(TRIAL_VERDICTS), "basis": _word(("measured", "feeling", "none")),
        "deltas": _list(_DELTA_ROW, COMPARISONS_MAX),
        "hypotheses": _list(_CONFIDENCE_ROW, 4),
    }),
    "calibration_rollback_trial": _object({
        "trialRef": _TRIAL_REF, "undone": _list(_TRIAL_REF, 50), "restored": _VALUES,
        # L'essai encore en cours après le retour arrière (empilés), ou `null`.
        "active": _nullable(_TRIAL_REF),
    }),
    "calibration_accept_trial": _object({
        "trialRef": _TRIAL_REF, "accepted": _VALUES, "applied": _VALUES,
        "basis": _nullable(_word(TRIAL_BASES)),
        "consent": _object({"source": _word(("voice", "ui")), "quote": _string(QUOTE_MAX)}),
    }),
    "calibration_rerun_exercise": _object({"exercise": _EXERCISE}),
    # Ce que la page a décidé : l'étape validée, ou passée (Slice 07, décisions 56-57).
    "calibration_next_exercise": _object({"exercise": _EXERCISE, "decision": _word(("validated", "skipped"))}),
}
#: Un refus de calibration porte ses fautes précises, sous un motif vérifié.
_REFUSAL = _object({"errors": _list(_object({"code": _word(pattern=_ERROR_CODE), "message": _string(200)}),
                                    8, minimum=1)})


def parse_calibration_result(name: str, outcome: str, raw: object) -> dict[str, Any] | None:
    """Le `result` du reçu d'une commande de calibration ; `BarehandsCommandError(BAD_RECEIPT)` sinon.

    Un succès (`applied`/`duplicate`) porte **exactement** le schéma de sa
    commande ; un refus porte `{errors:[{code, message}]}` ou rien.
    """

    try:
        if outcome == "refused":
            return None if raw is None else _REFUSAL(raw, "result")
        if raw is None:
            _fail("result", "absent d'un succès de calibration")
        return _RESULTS[name](raw, "result")
    except _Bad as exc:
        raise BarehandsCommandError("barehands_bad_receipt", str(exc), 400) from None


# ------------------------------------------------------------------ accord de l'utilisateur (décision 53)
#
# **Une citation n'est pas un accord.** La première version cherchait la
# citation comme une sous-chaîne (« le garde » se trouvait dans « non, ne le
# garde surtout pas ») ; la deuxième refusait trop (« Bon. Oui, garde-le,
# c'est mieux ! ») et laissait passer « nan, on garde l'ancien » (QA de la
# Slice 06, deux passes). La règle, dans cet ordre :
#
# 1. **Les tournures positives qui contiennent un mot de négation** (« rien à
#    redire », « pas mal », « ne colle plus »…) sont d'abord neutralisées
#    (`POSITIVE_IDIOMS`, liste fermée) : elles disent que le défaut a disparu.
# 2. **La phrase entière ne doute de rien** : aucun marqueur de refus, de
#    doute, de retour en arrière, d'indifférence ou de plaisanterie
#    (`REFUSAL_MARKERS`, `REFUSAL_PHRASES`), et pas de question (« ? »).
#    Une phrase qui en porte un n'accorde rien, même si une de ses
#    propositions le ferait seule.
# 3. **La citation est une suite de propositions entières** de la phrase
#    (coupées à la ponctuation et aux coordinations, `CLAUSE_BREAKERS`), jamais
#    un morceau de proposition.
# 4. **La citation contient un mot de garde** (`KEEP_WORDS`, `KEEP_PHRASES` :
#    garde*, conserve, oui, ok, d'accord, valide, enregistre, adopte, « c'est
#    bon », parfait, nickel, « vas-y »…). « c'est mieux » constate, il ne
#    demande pas de garder.
#
# **Limites, dites** : les listes sont fermées et françaises ; une ironie sans
# marqueur (« génial, garde ça… ») passe ; « c'est mieux qu'avant » passe
# (seuls « comme avant », « mieux avant », « l'ancien » refusent) ; une
# tournure positive absente de `POSITIVE_IDIOMS` qui contient une négation
# (« ça ne bégaie plus ») fait refuser. On refuse plutôt que d'accepter : un
# accord manqué se redemande en une phrase, un faux accord range un réglage.

#: Tournures positives qui contiennent un mot de négation, neutralisées avant
#: la recherche des marqueurs (comparées sur les mots normalisés).
POSITIVE_IDIOMS: tuple[str, ...] = (
    "rien à redire", "pas mal", "ne colle plus", "colle plus", "ne saute plus", "saute plus",
    "ne lâche plus", "lâche plus", "ne tremble plus", "tremble plus", "ne bouge plus tout seul",
    "plus de clics fantômes", "plus de clic fantôme", "plus de clics", "ne clique plus tout seul",
    "pas de souci", "pas de problème", "sans problème",
)
#: Mots qui, **n'importe où** dans la phrase, la rendent impropre à accorder.
#: Comparés mot à mot après normalisation (apostrophes et traits d'union
#: coupent les mots : « n'est » donne « n », « peut-être » donne « peut être »).
REFUSAL_MARKERS: frozenset[str] = frozenset({
    # négation, refus
    "non", "nan", "no", "nope", "ne", "n", "pas", "jamais", "rien", "nul",
    # annulation, retour en arrière
    "annule", "annules", "annuler", "annulez", "annulé", "annulle",
    "retire", "retirer", "retirez", "enlève", "enleve", "enlever", "enlevez",
    "remets", "remettre", "remettez", "défais", "defais", "défaire", "defaire",
    "reviens", "revenir", "arrête", "arrete", "stop", "oublie", "oublier", "oubliez",
    "ancien", "ancienne", "anciens", "autre",
    # doute, attente, indifférence, plaisanterie
    "pire", "bof", "moyen", "pareil", "attends", "attendez", "attendre", "hésite", "hesite", "doute",
    "sûr", "hmm", "hm", "euh", "rigole", "plaisante", "blague", "fiche", "fous",
})
#: Suites de mots qui marquent aussi le refus ou le doute.
REFUSAL_PHRASES: tuple[str, ...] = (
    "peut être", "pas sûr", "je sais pas", "on verra", "laisse tomber", "comme avant", "mieux avant",
    "avant c'était", "moins bien", "si tu veux", "comme tu veux",
)
#: Ce qui coupe une phrase en propositions, en plus de la ponctuation.
CLAUSE_BREAKERS: frozenset[str] = frozenset({
    "mais", "et", "sauf", "ou", "puis", "cependant", "pourtant", "sinon", "car", "donc", "alors",
})
_CLAUSE_PHRASES = ("par contre", "en revanche")
#: Les mots qui **demandent** de garder : la citation en contient au moins un.
KEEP_WORDS: frozenset[str] = frozenset({
    "garde", "gardes", "garder", "gardons", "gardez", "gardé", "conserve", "conserver", "conservons", "conservez",
    "oui", "ouais", "ok", "okay", "d'accord", "valide", "valider", "validé", "enregistre", "enregistrer",
    "enregistrez", "adopte", "adopter", "adopté", "parfait", "nickel",
})
KEEP_PHRASES: tuple[str, ...] = ("c'est bon", "vas y", "allez y")
#: **Valider une proposition** (`calibration_commit_proposal`) : garder, mais
#: aussi appliquer, essayer, refaire ou continuer — l'utilisateur répond à
#: « je l'applique ? ». Mêmes règles que garder (propositions entières, phrase
#: qui ne doute de rien) ; seuls les mots qui accordent s'élargissent.
COMMIT_WORDS: frozenset[str] = KEEP_WORDS | frozenset({
    "applique", "appliquer", "appliquez", "appliquons", "essaie", "essaye", "essayer", "essayez", "essayons",
    "refais", "refaire", "refaisons", "relance", "relancer", "continue", "continuer", "continuons", "go",
})
COMMIT_PHRASES: tuple[str, ...] = KEEP_PHRASES + ("on essaie", "on y va")

_PUNCTUATION = re.compile(r"[,.;:!?…\n\r\t()«»\"]+")
_WORDS = re.compile(r"[^\w']+", re.UNICODE)


def normalize_utterance(text: str) -> str:
    """Casse repliée, ponctuation et blancs réduits à une espace : ce que la
    transcription écrit et ce que le cerveau recopie se comparent sur les mots."""

    return " ".join(_WORDS.sub(" ", text.casefold().replace("’", "'")).split())


def _tokens(normalized: str) -> list[str]:
    return normalized.replace("'", " ").split()


def _spaced(text: str) -> str:
    return f" {' '.join(_tokens(normalize_utterance(text)))} "


def refusal_marker(text: str) -> str | None:
    """Le premier marqueur de refus ou de doute de la phrase, ou `None` (tournures positives neutralisées)."""

    if "?" in text:
        return "?"
    spaced = _spaced(text)
    for idiom in POSITIVE_IDIOMS:
        spaced = spaced.replace(f" {' '.join(_tokens(idiom))} ", " ")
    for phrase in REFUSAL_PHRASES:
        if f" {' '.join(_tokens(phrase))} " in spaced:
            return phrase
    for token in spaced.split():
        if token in REFUSAL_MARKERS:
            return token
    return None


def clauses(text: str) -> list[str]:
    """Les propositions de la phrase, normalisées, coupées à la ponctuation et aux coordinations."""

    out: list[str] = []
    for chunk in _PUNCTUATION.split(text.casefold().replace("’", "'")):
        normalized = f" {normalize_utterance(chunk)} "
        for phrase in _CLAUSE_PHRASES:
            normalized = normalized.replace(f" {phrase} ", " | ")
        current: list[str] = []
        for word in normalized.split():
            if word == "|" or word in CLAUSE_BREAKERS:
                if current:
                    out.append(" ".join(current))
                current = []
                continue
            current.append(word)
        if current:
            out.append(" ".join(current))
    return out


def keeps(text: str, words: frozenset[str] = KEEP_WORDS, phrases: tuple[str, ...] = KEEP_PHRASES) -> bool:
    """Le texte contient-il un mot qui **demande** de garder (ou, pour une validation, d'appliquer) ?"""

    spaced = _spaced(text)
    found = set(normalize_utterance(text).split()) | set(spaced.split())
    return bool(found & words) or any(f" {' '.join(_tokens(p))} " in spaced for p in phrases)


def consent_found(quote: str, utterances: list[str], *, commit: bool = False) -> tuple[bool, str]:
    """La citation est-elle un **accord** dit dans l'une des phrases ? `(trouvé, motif)`.

    Le motif dit, dans les mots que le cerveau relaie, pourquoi rien n'a été
    retrouvé : citation vide, sans mot de garde, morceau de proposition, phrase
    qui doute.
    """

    wanted = clauses(quote)
    if len(normalize_utterance(quote)) < QUOTE_MIN or not wanted:
        return False, "la citation est vide"
    if commit and not keeps(quote, COMMIT_WORDS, COMMIT_PHRASES):
        return False, "la citation n'accepte pas la proposition (ni « oui », ni « applique », ni « vas-y »…)"
    if not commit and not keeps(quote):
        return False, "la citation ne demande pas de garder (ni « garde », ni « oui », ni « d'accord »…)"
    why = "la citation ne se retrouve pas comme une suite de propositions entières de ce que l'utilisateur a dit"
    for said in utterances:
        found = clauses(said)
        if not any(found[i:i + len(wanted)] == wanted for i in range(len(found) - len(wanted) + 1)):
            continue
        marker = refusal_marker(said)
        if marker is not None:
            why = f"la phrase citée contient « {marker} » : elle n'accorde rien"
            continue
        return True, ""
    return False, why


def quote_found(quote: str, utterances: list[str]) -> bool:
    """Compatibilité de lecture : `consent_found` sans le motif."""

    return consent_found(quote, utterances)[0]
