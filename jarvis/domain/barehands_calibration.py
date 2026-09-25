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

#: Les neuf commandes de calibration, une par outil et **du même nom** : la
#: table outil → commande est l'identité, un test la tient.
CALIBRATION_COMMANDS: tuple[str, ...] = (
    "calibration_status",
    "calibration_record_feedback",
    "calibration_propose_hypothesis",
    "calibration_apply_trial",
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
    "unintended_target_rate", "unintended_pointer_rate", "pointer_jitter_px", "pointer_lag_ms", "acquisition_ms",
    "missed_click_count", "wrong_target_count", "false_click_count", "premature_drop_count",
    "reacquisition_count", "placement_error_px", "target_ambiguity", "drag_success_rate", "transition_ms",
)
TRIAL_KEYS: tuple[str, ...] = (
    "pressRatio", "releaseRatio", "secondaryPressRatio", "secondaryReleaseRatio", "pressFrames",
    "releaseFrames", "releaseMs", "releaseDeltaRatio", "releaseDoubtMaxMs", "clickSlopPx", "dragSlopPx",
    "clickMaxMs", "clickStillnessMin", "minCutoffHz", "betaCutoff", "stillSpeedPx", "moveSpeedPx", "assistance",
    "targetZonePx", "targetZoneHoldPx", "targetSwitchPx", "targetAmbiguityMax", "targetHoldRatio", "wakeHoldMs",
    "wakeScore", "pointingEnterScore", "pointingExitScore", "pointingEnterMs", "pointingExitMs",
    "pointingMotionFloor", "pointingFoldStartPalms", "pointingFoldEndPalms",
)
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
    "calibration_apply_trial": _object({"hypothesisRef": _HYPOTHESIS_REF, "patch": _PATCH}),
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
    "calibration_rerun_exercise": _NO_PAYLOAD,
    "calibration_next_exercise": _NO_PAYLOAD,
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
    if name == "calibration_apply_trial" and not payload["patch"]:
        raise BarehandsCommandError("barehands_bad_request", "payload.patch : au moins une clé d'essai", 400)
    return payload


def consent_payload(quote: str) -> dict[str, Any]:
    """Ce que la page reçoit pour `calibration_accept_trial` une fois l'accord **retrouvé** par le serveur."""

    return {"consent": {"source": "voice", "quote": quote, "verifiedBy": "control_center"}}


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
                      "appliedAt": _number(0)})
_MEASUREMENT_ROW = _object({"ref": _MEASURE_REF, "stage": _STAGE, "exerciseRef": _nullable(_EXERCISE_REF),
                            "trialRef": _nullable(_TRIAL_REF),
                            "metrics": _map(_METRIC_KEY, _nullable(_number()), len(CALIBRATION_METRICS))})
_EXERCISE = _object({"step": _STAGE, "phase": _nullable(_word()), "running": _bool,
                     "finished": _bool})
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
    "calibration_apply_trial": _object({
        "trialRef": _TRIAL_REF, "hypothesisRef": _HYPOTHESIS_REF, "baseRef": _nullable(_TRIAL_REF),
        "applied": _VALUES, "appliedAt": _number(0),
    }),
    "calibration_resolve_trial": _object({
        "trialRef": _TRIAL_REF, "verdict": _word(TRIAL_VERDICTS), "deltas": _list(_DELTA_ROW, COMPARISONS_MAX),
        "hypotheses": _list(_CONFIDENCE_ROW, 4),
    }),
    "calibration_rollback_trial": _object({
        "trialRef": _TRIAL_REF, "undone": _list(_TRIAL_REF, 50), "restored": _VALUES,
        # L'essai encore en cours après le retour arrière (empilés), ou `null`.
        "active": _nullable(_TRIAL_REF),
    }),
    "calibration_accept_trial": _object({
        "trialRef": _TRIAL_REF, "accepted": _VALUES, "applied": _VALUES,
        "consent": _object({"source": _word(("voice", "ui")), "quote": _string(QUOTE_MAX)}),
    }),
    "calibration_rerun_exercise": _object({"exercise": _EXERCISE}),
    "calibration_next_exercise": _object({"exercise": _EXERCISE}),
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
# citation comme une sous-chaîne : « le garde » se trouvait dans « non, ne le
# garde surtout pas », « oui » dans « oui mais c'est pire, annule-le » (QA de la
# Slice 06). La règle est maintenant trois fois plus étroite :
#
# 1. **la phrase entière ne doute de rien** : aucun mot de `REFUSAL_MARKERS`
#    (négation, annulation, doute, attente) n'y figure — une phrase qui en porte
#    un n'accorde rien, même si une de ses propositions le ferait seule ;
# 2. **la citation est une proposition entière** de la phrase, coupée à la
#    ponctuation et aux coordinations (`CLAUSE_BREAKERS`), jamais un morceau ;
# 3. **un accord d'un mot** (« oui », « ok », « garde-le »…) doit être la phrase
#    **entière** et appartenir à `SHORT_AFFIRMATIONS` ; ailleurs, une citation
#    d'un seul mot ne vaut rien.
#
# Les listes sont fermées et testées. Elles refusent trop plutôt que pas assez :
# un accord manqué se redemande en une phrase, un faux accord range un réglage.

#: Mots qui, **n'importe où** dans la phrase, la rendent impropre à accorder.
#: Comparés mot à mot après normalisation (apostrophes et traits d'union
#: coupent les mots : « n'est » donne « n », « peut-être » donne « peut être »).
REFUSAL_MARKERS: frozenset[str] = frozenset({
    "non", "ne", "n", "pas", "jamais", "rien",
    "annule", "annules", "annuler", "annulez", "annulé",
    "retire", "retirer", "retirez", "enlève", "enleve", "enlever", "enlevez",
    "remets", "remettre", "remettez", "défais", "defais", "défaire", "defaire",
    "reviens", "revenir", "arrête", "arrete", "stop",
    "pire", "bof", "moyen", "attends", "attendez", "attendre", "hésite", "hesite", "doute",
    "sûr",
})
#: Suites de mots qui marquent aussi le doute.
REFUSAL_PHRASES: tuple[str, ...] = ("peut être", "pas sûr", "je sais pas", "on verra")
#: Ce qui coupe une phrase en propositions, en plus de la ponctuation.
CLAUSE_BREAKERS: frozenset[str] = frozenset({
    "mais", "et", "sauf", "ou", "puis", "cependant", "pourtant", "sinon", "car", "donc", "alors",
})
_CLAUSE_PHRASES = ("par contre", "en revanche")
#: Les seuls accords d'un mot (ou d'une locution figée) — valables seulement
#: quand ils **sont** la phrase entière.
SHORT_AFFIRMATIONS: frozenset[str] = frozenset({
    "oui", "ouais", "ok", "okay", "d'accord", "parfait", "impeccable", "nickel", "super", "top",
    "garde", "garde le", "garde la", "garde les", "gardes le", "vas y", "allez y", "c'est bon", "ça marche",
    "exactement", "carrément", "valide", "je valide", "on garde", "on le garde",
})

_PUNCTUATION = re.compile(r"[,.;:!?…\n\r\t()«»\"]+")
_WORDS = re.compile(r"[^\w']+", re.UNICODE)


def normalize_utterance(text: str) -> str:
    """Casse repliée, ponctuation et blancs réduits à une espace : ce que la
    transcription écrit et ce que le cerveau recopie se comparent sur les mots."""

    return " ".join(_WORDS.sub(" ", text.casefold().replace("’", "'")).split())


def _tokens(normalized: str) -> list[str]:
    return normalized.replace("'", " ").split()


def refusal_marker(text: str) -> str | None:
    """Le premier mot (ou la locution) de doute de la phrase, ou `None`."""

    normalized = normalize_utterance(text)
    spaced = f" {' '.join(_tokens(normalized))} "
    for phrase in REFUSAL_PHRASES:
        if f" {phrase} " in spaced:
            return phrase
    for token in _tokens(normalized):
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


def consent_found(quote: str, utterances: list[str]) -> tuple[bool, str]:
    """La citation est-elle un **accord** dit dans l'une des phrases ? `(trouvé, motif)`.

    Le motif dit, dans les mots que le cerveau relaie, pourquoi rien n'a été
    retrouvé : citation trop courte, phrase qui doute, morceau de proposition.
    """

    wanted = normalize_utterance(quote)
    if len(wanted) < QUOTE_MIN:
        return False, "la citation est vide"
    short = wanted in SHORT_AFFIRMATIONS
    if not short and len(_tokens(wanted)) < 2:
        return False, f"« {wanted} » n'est pas un accord à lui seul"
    why = "la citation ne se retrouve pas comme une proposition entière de ce que l'utilisateur a dit"
    for said in utterances:
        marker = refusal_marker(said)
        if short:
            if normalize_utterance(said) != wanted:
                continue
        elif wanted not in clauses(said):
            continue
        if marker is not None:
            why = f"la phrase citée contient « {marker} » : elle n'accorde rien"
            continue
        return True, ""
    return False, why


def quote_found(quote: str, utterances: list[str]) -> bool:
    """Compatibilité de lecture : `consent_found` sans le motif."""

    return consent_found(quote, utterances)[0]
