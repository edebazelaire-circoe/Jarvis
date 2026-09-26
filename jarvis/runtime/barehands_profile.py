"""Profil de calibration Bare Hands : ce que le serveur en garde (Slice 08).

Le parcours de calibration vit dans la page — c'est là qu'il y a une caméra, des
mains et un écran. Le serveur ne mesure rien : il **range** le résultat, et il
refuse tout ce qui n'est pas une mesure dérivée.

Forme du module, calquée sur ``barehands_test_mode`` plutôt que réinventée :
``SETTING_KEY``, une lecture **tolérante** (``load``), une écriture **stricte**
(``apply``, qui lève un ``BarehandsProfileError`` au ``code`` stable repris dans
l'en-tête ``X-Jarvis-Error-Code``), un ``describe``, et l'archivage d'un bloc en
version étrangère avant de le remplacer — le même mécanisme, pour la même raison
et avec les mêmes mots.

**Clé distincte de celle des réglages, et route distincte.** Un profil n'est pas
un réglage : il est produit par une mesure et non par un choix, il a son propre
numéro de schéma (``PROFILE_SCHEMA_VERSION`` du contrat, qui n'avance pas au même
rythme que ``SETTINGS_SCHEMA_VERSION``), et l'écrire ne doit pas revalider les
neuf réglages. Les mêler aurait donné un seul numéro à deux choses qui changent
séparément — exactement ce que la couture de migration des réglages existe pour
éviter.

**Décision 32 : aucune image, aucune vidéo, aucun point.** Cette promesse est
tenue ici par une liste blanche — ``apply`` reconstruit le profil clé par clé —
et par un refus explicite de tout ce qui n'est pas un scalaire dérivé. C'est le
côté serveur qui compte : la charge utile qui arrive sur la route vient du
réseau, pas du module JS qu'on a écrit.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

#: Bloc du profil, à la racine du fichier de réglages, à côté de
#: ``barehands_test_mode``. Absent, rien n'est calibré et le moteur garde ses
#: défauts (décision 31).
SETTING_KEY = "barehands_calibration_profile"

#: Version du schéma du profil. Elle vaut celle du contrat
#: (``PROFILE_SCHEMA_VERSION`` dans ``control_center_barehands_contracts.js``),
#: et un test de parité l'exécute plutôt que de la supposer.
#:
#: **Version 2 (Slice 08)** : la v1 n'avait ni ``travel_slop_norm`` ni le rapport
#: par étape. Elle se convertit — ses six mesures restent valides — plutôt que de
#: se refuser.
#:
#: **Version 3 (tâche adaptative, Slice 04, décision 48)** : le bloc ``tuning``
#: porte les valeurs d'essai **acceptées**. Le numéro monte pour qu'un Jarvis
#: plus ancien refuse un profil v3 (et l'archive à sa première écriture) au lieu
#: d'en jeter ``tuning`` sans un mot. La v2 se convertit sans perte : ``tuning``
#: vide.
SCHEMA_VERSION = 3

#: Versions précédentes que ``load`` sait convertir. Même couture que celle des
#: réglages, au même endroit et de la même forme.
MIGRATED_SCHEMA_VERSIONS = (1, 2)

#: Préfixe des clés d'archive d'un profil illisible. Même mécanisme que pour les
#: réglages (constat R6) : un profil écrit par un Jarvis plus récent est **rangé**
#: avant d'être remplacé, jamais écrasé sans un mot. Une calibration coûte une
#: minute à l'utilisateur ; la détruire en silence est pire ici qu'ailleurs.
ARCHIVE_KEY_PREFIX = "barehands_calibration_profile_archived_v"

#: Clé de version dans la charge utile et dans le fichier.
SCHEMA_KEY = "schema_version"

#: Latéralités, miroir de ``HANDEDNESSES`` du contrat. Le seau ``unknown`` existe
#: parce que le traqueur n'étiquette pas toujours la main : sans lui, toute main
#: non étiquetée perdait sa calibration en silence.
HANDEDNESSES: tuple[str, ...] = ("left", "right", "unknown")

#: Les clés mesurables d'une main et leurs bornes, miroir de
#: ``normalizeHandProfile``. Le contrat **borne** (il relit un schéma stocké) ;
#: cette route **refuse** (elle écrit ce que quelqu'un a demandé). Les deux
#: tables sont comparées en exécutant le contrat sous node.
HAND_BOUNDS: dict[str, tuple[float, float]] = {
    "press_ratio": (0.05, 0.9),
    "release_ratio": (0.05, 1.5),
    "secondary_press_ratio": (0.05, 0.9),
    "secondary_release_ratio": (0.05, 1.5),
    "jitter_px": (0.0, 200.0),
    # Plafond 0,014 (~27 px en 1920) : voir `travelSlopMax` de la calibration.
    # À 0,15, une mesure ratée armait le glissement au-delà de 500 px.
    "travel_slop_norm": (0.002, 0.014),
    "quality": (0.0, 1.0),
}

#: ``reachNorm`` : quatre nombres, et rien d'autre. Nommée à part parce que c'est
#: la seule forme imbriquée du schéma, donc la seule qui pourrait devenir la
#: poche où tout passe.
REACH_KEYS: tuple[str, ...] = ("x", "y", "w", "h")

#: **Mesuré n'est pas calibrant.** ``quality`` est une *métrique* de la séance,
#: pas un seuil : le parcours le dit (« c'est une métrique, pas un seuil — elle
#: ne change rien au moteur ») et rien côté moteur ne la lit. Mais la page
#: l'écrit pour tout seau de main ayant vu une image, si bien qu'une séance dont
#: les sept étapes ont échoué se relisait ``calibrated: True`` : l'onglet
#: affichait « Calibré », le toast annonçait « Bare Hands utilise vos mesures »,
#: et la branche « sans aucune mesure » du journal ne tirait jamais.
#:
#: Elle reste bornée, persistée et rendue comme avant. Elle ne **lève** plus le
#: drapeau, qui répond à « le moteur a-t-il été adapté à cette main ? ».
#: Miroir de ``PROFILE_METRIC_KEYS`` du contrat, tenu par le test de parité.
#:
#: **Et ``jitter_px``, ``reach_norm`` non plus** (tâche adaptative, Slice 04,
#: READINESS D4) : aucune fonction du moteur ne les lit. Ils restent mesurés et
#: rangés — la migration ne perd rien — mais un profil qui ne portait qu'eux ne
#: se dit plus calibré.
METRIC_KEYS: tuple[str, ...] = ("jitter_px", "reach_norm", "quality")

#: Les clés dont la présence vaut « calibré ». Toute clé ajoutée demain calibre
#: par défaut : c'est l'exclusion qui s'écrit, jamais l'inclusion.
CALIBRATING_KEYS: tuple[str, ...] = tuple(
    key for key in (*HAND_BOUNDS, "reach_norm") if key not in METRIC_KEYS
)

#: **Les valeurs d'essai acceptées** (décision 48), miroir de
#: ``PROFILE_TUNING_BOUNDS`` du contrat : ``(min, max, défaut, entier)``. Réglages
#: du moteur entier, pas par main. ``click_slop_px``/``drag_slop_px`` sont rangés
#: **à sensibilité 1** (effectif = rangé ÷ sensitivity), d'où l'étendue élargie
#: par celle de ``sensitivity`` (0,25 – 4). Tenu par un test de parité qui
#: exécute le contrat sous node.
TUNING_BOUNDS: dict[str, tuple[float, float, float, bool]] = {
    # Seuils acceptés pour les mains **sans** paire mesurée (une main mesurée
    # garde sa paire, mise à jour de la seule clé essayée).
    "press_ratio": (0.1, 0.4, 0.28, False),
    "release_ratio": (0.2, 0.8, 0.42, False),
    "secondary_press_ratio": (0.1, 0.4, 0.28, False),
    "secondary_release_ratio": (0.2, 0.8, 0.42, False),
    "press_frames": (1, 4, 2, True),
    "release_frames": (1, 5, 2, True),
    "release_ms": (0, 250, 60, False),
    "release_delta_ratio": (0.05, 0.35, 0.15, False),
    "release_doubt_max_ms": (100, 800, 400, False),
    "click_slop_px": (0.75, 192, 12, False),
    "drag_slop_px": (1.5, 416, 26, False),
    "click_max_ms": (150, 900, 400, False),
    "click_stillness_min": (0.2, 0.9, 0.5, False),
    "min_cutoff_hz": (0.3, 4, 1.2, False),
    "beta_cutoff": (0, 0.05, 0.012, False),
    "still_speed_px": (8, 80, 28, False),
    "move_speed_px": (200, 900, 420, False),
    "target_zone_px": (6, 30, 14, False),
    "target_zone_hold_px": (8, 40, 20, False),
    "target_switch_px": (0, 12, 8, False),
    "target_ambiguity_max": (0.5, 1, 0.8, False),
    "target_hold_ratio": (0.3, 0.8, 0.5, False),
    "wake_hold_ms": (400, 2000, 1000, False),
    "wake_score": (0.3, 0.8, 0.5, False),
    "pointing_enter_score": (0.3, 0.9, 0.5, False),
    "pointing_exit_score": (0.1, 0.6, 0.3, False),
    "pointing_enter_ms": (0, 600, 150, False),
    "pointing_exit_ms": (200, 1000, 300, False),
    "pointing_motion_floor": (0, 1, 0.4, False),
    "pointing_fold_start_palms": (1.3, 1.55, 1.45, False),
    "pointing_fold_end_palms": (1.5, 1.8, 1.6, False),
}

#: Les paires d'``options()`` que deux valeurs rangées peuvent inverser, miroir
#: de ``PROFILE_TUNING_PAIRS`` : ``(bas, haut, stricte)``. Une moitié absente se
#: juge contre le défaut de l'autre.
TUNING_PAIRS: tuple[tuple[str, str, bool], ...] = (
    ("press_ratio", "release_ratio", True),
    ("secondary_press_ratio", "secondary_release_ratio", True),
    ("click_slop_px", "drag_slop_px", False),
    ("still_speed_px", "move_speed_px", True),
    ("target_zone_px", "target_zone_hold_px", False),
    ("target_hold_ratio", "target_ambiguity_max", False),
    ("pointing_exit_score", "pointing_enter_score", False),
    ("pointing_fold_start_palms", "pointing_fold_end_palms", True),
)

#: L'ancre ``wakeGapMin`` (0,46) : un relâchement rangé reste en dessous, sinon
#: un pincement en cours se lirait comme une posture de réveil. Miroir de
#: ``PROFILE_TUNING_ANCHORS``.
TUNING_ANCHORS: dict[str, float] = {"release_ratio": 0.46}

#: Nom d'une clé de main sur le fil -> nom dans le contrat. Une seule table de
#: passage, testée aller-retour, comme ``SETTINGS_WIRE_KEYS``.
HAND_WIRE_KEYS: dict[str, str] = {
    "pressRatio": "press_ratio",
    "releaseRatio": "release_ratio",
    "secondaryPressRatio": "secondary_press_ratio",
    "secondaryReleaseRatio": "secondary_release_ratio",
    "jitterPx": "jitter_px",
    "travelSlopNorm": "travel_slop_norm",
    "reachNorm": "reach_norm",
    "quality": "quality",
}

#: Les étapes du parcours, miroir de ``STAGE`` du contrat, dans l'ordre.
#: ``natural_motion`` et ``aim_no_click`` (exemples négatifs, tâche adaptative
#: Slice 03) sont ajoutées **en fin** : un profil v2 enregistré avant elles se
#: relit tel quel, ces deux étapes valant alors ``skipped`` (``_load_stage``).
STAGES: tuple[str, ...] = (
    # Slice 07 adaptative (décision 56) : l'ordre est celui du parcours —
    # ``hold_release`` après le pincement primaire, ``drop`` après ``resize``.
    # Un profil range ses étapes par nom : un profil v3 enregistré avant elles
    # les relit ``skipped``.
    "neutral", "c_pose", "pinch_primary", "hold_release", "pinch_secondary", "aim", "drag", "resize",
    "drop", "natural_motion", "aim_no_click",
)

#: États d'une étape, miroir de ``STAGE_STATUS``.
STAGE_STATUSES: tuple[str, ...] = ("ok", "failed", "skipped")

#: Motifs d'échec, miroir de ``STAGE_REASON``. Liste **fermée** : c'est la seule
#: chaîne de texte qu'un profil a le droit de porter, et la fermer est ce qui
#: empêche le champ « motif » de devenir un commentaire libre — donc un endroit
#: où quelque chose d'autre qu'une mesure pourrait voyager (décision 32).
STAGE_REASONS: tuple[str, ...] = (
    "barehands_stage_no_hand",
    "barehands_stage_timeout",
    "barehands_stage_too_few_samples",
    "barehands_stage_not_separable",
    "barehands_stage_out_of_band",
    "barehands_stage_needs_two_hands",
    "barehands_stage_cancelled",
    # Slice 07 (divergence D4) : l'étape de manipulation de fenêtre emprunte
    # l'échelle de la scène pour manipuler un vrai cadre. Scène éteinte,
    # l'échelle vaut None : l'étape est **passée** avec ce motif plutôt que
    # jouée contre un faux cadre. Miroir de ``STAGE_REASON.SCENE_UNAVAILABLE``.
    "barehands_stage_scene_unavailable",
    # Slice 07 adaptative (décision 57) : une étape passée par l'utilisateur
    # porte la raison choisie dans cette liste fermée. Miroir de ``SKIP_REASON``.
    "barehands_stage_skip_not_relevant",
    "barehands_stage_skip_cannot_perform",
    "barehands_stage_skip_tracking",
    "barehands_stage_skip_later",
)


class BarehandsProfileError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _empty_hand() -> dict[str, Any]:
    value: dict[str, Any] = {key: None for key in HAND_BOUNDS}
    value["reach_norm"] = None
    return value


def _derive_calibrated(value: Mapping[str, Any]) -> bool:
    """« Calibré » se **dérive** des mesures présentes, jamais de l'annonce.

    Une seule mesure suffit — une calibration partielle est valide (décision 31).
    Mais elle doit être une mesure qui **adapte le moteur** : ``quality`` est
    une métrique de séance (``METRIC_KEYS``), et un parcours dont tout a échoué
    n'en portait qu'elle.
    """

    return any(
        value["hands"][handedness][key] is not None
        for handedness in HANDEDNESSES
        for key in CALIBRATING_KEYS
    )


def _derive_tuned(value: Mapping[str, Any]) -> bool:
    """Des valeurs d'essai **acceptées** sont rangées (`tuning`) : le moteur est
    adapté, mais sans mesure — ce n'est pas « calibré » (reprise QA de la
    Slice 06 adaptative : un réglage gardé sans profil disait `calibrated`)."""

    return any(value["tuning"][key] is not None for key in TUNING_BOUNDS)


def _empty_tuning() -> dict[str, Any]:
    return {key: None for key in TUNING_BOUNDS}


def _pair_broken(tuning: Mapping[str, Any], low: str, high: str, strict: bool) -> bool:
    lo = tuning[low] if tuning[low] is not None else TUNING_BOUNDS[low][2]
    hi = tuning[high] if tuning[high] is not None else TUNING_BOUNDS[high][2]
    return not (lo < hi if strict else lo <= hi)


def _load_tuning(raw: Any) -> dict[str, Any]:
    """Lecture tolérante du bloc ``tuning`` : bornée, ``None`` pour l'illisible,
    et une paire inversée tombe en entier (même règle que ``_load_hand``)."""

    source = raw if isinstance(raw, Mapping) else {}
    tuning = _empty_tuning()
    for key, (low, high, _default, integer) in TUNING_BOUNDS.items():
        got = source.get(key)
        if got is None or isinstance(got, bool) or not isinstance(got, (int, float)) \
                or not math.isfinite(got):
            continue
        value = float(round(got)) if integer else float(got)
        tuning[key] = min(max(value, low), high)
    for low, high, strict in TUNING_PAIRS:
        if (tuning[low] is not None or tuning[high] is not None) and _pair_broken(tuning, low, high, strict):
            tuning[low] = None
            tuning[high] = None
    for key, ceiling in TUNING_ANCHORS.items():
        if tuning[key] is not None and not tuning[key] < ceiling:
            tuning[key] = None
    return tuning


def _apply_tuning(raw: Any) -> dict[str, Any]:
    """Écriture stricte du bloc ``tuning`` : nombre fini dans ses bornes, entier
    quand la clé l'est, paires dans l'ordre. Une valeur acceptée qui ne
    s'écrirait pas telle quelle se refuse — jamais bornée en silence."""

    if raw is None:
        return _empty_tuning()
    if not isinstance(raw, Mapping):
        raise BarehandsProfileError("barehands_profile_bad_payload", "« tuning » doit être un objet.")
    unknown = set(map(str, raw)) - set(TUNING_BOUNDS)
    if unknown:
        raise BarehandsProfileError(
            "barehands_profile_unknown_field",
            f"Réglage accepté inconnu dans « tuning » : {', '.join(sorted(unknown))}.",
        )
    tuning = _empty_tuning()
    for key, (low, high, _default, integer) in TUNING_BOUNDS.items():
        got = raw.get(key)
        if got is None:
            continue
        if isinstance(got, bool) or not isinstance(got, (int, float)) or not math.isfinite(got):
            raise BarehandsProfileError(
                "barehands_profile_not_derived", f"« tuning.{key} » doit être un nombre fini.")
        if integer and float(got) != round(got):
            raise BarehandsProfileError(
                "barehands_profile_out_of_range", f"« tuning.{key} » doit être entier (reçu {got}).")
        if not low <= got <= high:
            raise BarehandsProfileError(
                "barehands_profile_out_of_range",
                f"« tuning.{key} » doit rester entre {low} et {high} (reçu {got}).",
            )
        tuning[key] = float(got)
    for low, high, strict in TUNING_PAIRS:
        if (tuning[low] is not None or tuning[high] is not None) and _pair_broken(tuning, low, high, strict):
            raise BarehandsProfileError(
                "barehands_profile_tuning_invalid",
                f"« tuning » : {low} doit rester {'sous' if strict else 'au plus'} {high}.",
            )
    for key, ceiling in TUNING_ANCHORS.items():
        if tuning[key] is not None and not tuning[key] < ceiling:
            raise BarehandsProfileError(
                "barehands_profile_tuning_invalid",
                f"« tuning.{key} » doit rester sous {ceiling} : au-delà, un pincement se lirait comme un réveil.",
            )
    return tuning


def _empty_stages() -> dict[str, Any]:
    return {stage: {"status": "skipped", "reason": None, "samples": 0} for stage in STAGES}


def defaults() -> dict[str, Any]:
    """Un profil vierge : rien de mesuré, rien de calibré, aucune étape jouée."""

    return {
        SCHEMA_KEY: SCHEMA_VERSION,
        "calibrated": False,
        "tuned": False,
        "updated_at": None,
        "hands": {handedness: _empty_hand() for handedness in HANDEDNESSES},
        "tuning": _empty_tuning(),
        "stages": _empty_stages(),
    }


def _stored_version(stored: Mapping[str, Any]) -> int:
    """Version du bloc enregistré. Absente = « écrit par nous »."""

    raw = stored.get(SCHEMA_KEY)
    if raw is None:
        return SCHEMA_VERSION
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def _archive_key(version: int | None) -> str:
    return f"{ARCHIVE_KEY_PREFIX}{version if isinstance(version, int) and version >= 0 else 'unknown'}"


def inspect(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que le bloc stocké dit de lui-même, avant toute tolérance.

    Même rôle que ``barehands_test_mode.inspect`` : séparer « des défauts parce
    qu'illisible » de « des défauts parce que neuf ». Pour un profil, la
    distinction est plus lourde encore — le second est « pas encore calibré »,
    le premier est « une calibration existe et on ne sait pas la lire ».
    """

    stored = settings.get(SETTING_KEY)
    present = isinstance(stored, Mapping)
    version = _stored_version(stored) if present else None
    unreadable = present and version != SCHEMA_VERSION and version not in MIGRATED_SCHEMA_VERSIONS
    return {
        "present": present,
        "stored_schema_version": version,
        "unreadable": unreadable,
        "archive_key": _archive_key(version) if unreadable else None,
    }


def archived_keys(settings: Mapping[str, Any]) -> list[str]:
    return sorted(key for key in settings if str(key).startswith(ARCHIVE_KEY_PREFIX))


def archive_unreadable(settings: dict[str, Any]) -> str | None:
    """Ranger un profil illisible sous sa clé de version. Rend la clé, ou ``None``."""

    seen = inspect(settings)
    if not seen["unreadable"]:
        return None
    key = str(seen["archive_key"])
    settings[key] = dict(settings[SETTING_KEY])
    return key


def _bounded(key: str, raw: Any) -> float | None:
    """Lecture tolérante d'une mesure : borne, ou ``None`` si elle ne se lit pas.

    ``None`` est une **absence**, jamais un zéro : c'est la mine que le contrat a
    trouvée du côté page (``Number(null)`` vaut 0, donc une mesure absente était
    bornée sur son plancher et se relisait « calibrée »). Le même piège existe
    ici sous une autre forme — ``bool`` est une sous-classe de ``int`` en Python,
    donc ``True`` passerait pour la mesure 1 — et il se refuse de la même façon.
    """

    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    # `NaN` n'est **pas** un nombre lisible, et il traversait : `min`/`max` le
    # propagent en silence, `json` de la bibliothèque standard l'écrit et le
    # relit, et un seuil `NaN` rend toute comparaison du moteur fausse — donc
    # un pincement qui ne se déclenche jamais, sans une ligne nulle part.
    # L'écriture le refuse déjà (`_check_number` : aucune comparaison n'est
    # vraie), la lecture le laissait passer.
    if not math.isfinite(raw):
        return None
    low, high = HAND_BOUNDS[key]
    return min(max(float(raw), low), high)


def _load_reach(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, Mapping):
        return None
    value: dict[str, float] = {}
    for key in REACH_KEYS:
        got = raw.get(key)
        if isinstance(got, bool) or not isinstance(got, (int, float)) or not math.isfinite(got):
            return None
        value[key] = min(max(float(got), 0.0), 1.0)
    # Une portée plate ramène tout l'écran sur un point : elle défait le repli
    # qu'elle devait remplacer, donc elle ne se lit pas (contrat §10).
    return value if value["w"] > 0 and value["h"] > 0 else None


def _load_hand(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, Mapping) else {}
    hand = _empty_hand()
    for key in HAND_BOUNDS:
        hand[key] = _bounded(key, source.get(key))
    hand["reach_norm"] = _load_reach(source.get("reach_norm"))
    # Un pincement qui ne peut jamais se relâcher n'est pas une calibration
    # exigeante, c'est une mesure ratée : à la lecture on la laisse tomber en
    # entier plutôt que d'en garder une moitié qui bloquerait la main sur
    # l'objet capturé. L'écriture, elle, refuse avec son code.
    #
    # **Et une demi-paire tombe pour la même raison.** `apply` la refuse
    # (`barehands_profile_thresholds_incomplete`) parce qu'un seuil mesuré
    # mélangé à un défaut du moteur peut inverser `press < release` ; la lecture
    # la gardait pourtant, si bien qu'un fichier édité à la main ou un profil v1
    # portant une moitié rendait `calibrated` vrai et faisait lister par l'onglet
    # un seuil que le moteur, lui, ignorait — « profil enregistré ≠ profil
    # appliqué ». Les deux portes disent maintenant la même chose.
    for press, release in (("press_ratio", "release_ratio"),
                           ("secondary_press_ratio", "secondary_release_ratio")):
        low, high = hand[press], hand[release]
        if (low is None) != (high is None) or (
                low is not None and high is not None and not low < high):
            hand[press] = None
            hand[release] = None
    return hand


def _load_stage(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, Mapping) else {}
    status = source.get("status")
    status = status if status in STAGE_STATUSES else "skipped"
    reason = source.get("reason")
    reason = reason if reason in STAGE_REASONS else None
    samples = source.get("samples")
    samples = int(samples) if isinstance(samples, int) and not isinstance(samples, bool) and samples >= 0 else 0
    # Un `ok` qui porte un motif d'échec et un `failed` muet disent deux choses
    # contraires ; à la lecture on retombe sur « pas jouée », qui ne ment pas.
    if status == "ok" and reason is not None:
        status, reason = "skipped", None
    if status == "failed" and reason is None:
        status = "skipped"
    return {"status": status, "reason": reason, "samples": samples}


def load(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Le profil tel qu'il s'applique. Toute valeur douteuse vaut « non mesuré ».

    Lecture **tolérante**, comme celle des réglages : un fichier abîmé ne doit
    pas rendre Bare Hands injoignable, et une mesure illisible retombe sur le
    défaut du moteur, ce qui est exactement la décision 31. Une version
    **étrangère** ne se devine pas : on n'en garde rien, le moteur garde ses
    défauts, et le bloc est archivé à la première écriture.
    """

    stored = settings.get(SETTING_KEY)
    stored = stored if isinstance(stored, Mapping) else {}
    if inspect(settings)["unreadable"]:
        return defaults()
    value = defaults()
    given = stored.get("hands")
    given = given if isinstance(given, Mapping) else {}
    for handedness in HANDEDNESSES:
        value["hands"][handedness] = _load_hand(given.get(handedness))
    value["tuning"] = _load_tuning(stored.get("tuning"))
    stages = stored.get("stages")
    stages = stages if isinstance(stages, Mapping) else {}
    for stage in STAGES:
        value["stages"][stage] = _load_stage(stages.get(stage))
    at = stored.get("updated_at")
    # Même règle que pour les mesures : `NaN` n'est pas un horodatage, et il
    # ressortirait en date illisible à l'écran.
    value["updated_at"] = (at if isinstance(at, (int, float)) and not isinstance(at, bool)
                           and math.isfinite(at) else None)
    # `calibrated` est **dérivé**, jamais repris de l'entrée : « calibré » sans
    # mesure ne vaut pas calibré (contrat §10).
    value["calibrated"] = _derive_calibrated(value)
    value["tuned"] = _derive_tuned(value)
    return value


def _check_number(where: str, key: str, raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise BarehandsProfileError(
            "barehands_profile_not_derived",
            f"« {where}.{key} » doit être un nombre : un profil ne porte que des mesures dérivées.",
        )
    low, high = HAND_BOUNDS[key]
    if not low <= raw <= high:
        raise BarehandsProfileError(
            "barehands_profile_out_of_range",
            f"« {where}.{key} » doit rester entre {low} et {high} (reçu {raw}).",
        )
    return float(raw)


def _apply_reach(where: str, raw: Any) -> dict[str, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise BarehandsProfileError(
            "barehands_profile_not_derived", f"« {where}.reach_norm » doit être un objet {{x,y,w,h}}.")
    unknown = set(map(str, raw)) - set(REACH_KEYS)
    if unknown:
        # La seule forme imbriquée du schéma ne devient pas la poche où tout
        # passe : quatre nombres, et rien d'autre (décision 32).
        raise BarehandsProfileError(
            "barehands_profile_not_derived",
            f"« {where}.reach_norm » ne porte que {{x,y,w,h}} ; reçu aussi : {', '.join(sorted(unknown))}.",
        )
    value: dict[str, float] = {}
    for key in REACH_KEYS:
        got = raw.get(key)
        if isinstance(got, bool) or not isinstance(got, (int, float)):
            raise BarehandsProfileError(
                "barehands_profile_not_derived", f"« {where}.reach_norm.{key} » doit être un nombre.")
        if not 0.0 <= got <= 1.0:
            raise BarehandsProfileError(
                "barehands_profile_out_of_range",
                f"« {where}.reach_norm.{key} » est en coordonnées normalisées 0..1 (reçu {got}).",
            )
        value[key] = float(got)
    if not (value["w"] > 0 and value["h"] > 0):
        raise BarehandsProfileError(
            "barehands_profile_reach_invalid",
            f"« {where}.reach_norm » est dégénérée : largeur et hauteur doivent être positives.",
        )
    return value


def _apply_hand(where: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise BarehandsProfileError("barehands_profile_bad_payload", f"« {where} » doit être un objet.")
    unknown = set(map(str, raw)) - set(HAND_BOUNDS) - {"reach_norm"}
    if unknown:
        raise BarehandsProfileError(
            "barehands_profile_unknown_field",
            f"Mesure inconnue dans « {where} » : {', '.join(sorted(unknown))}.",
        )
    hand = _empty_hand()
    for key in HAND_BOUNDS:
        got = raw.get(key)
        hand[key] = None if got is None else _check_number(where, key, got)
    hand["reach_norm"] = _apply_reach(where, raw.get("reach_norm"))
    for press, release, label in (("press_ratio", "release_ratio", "primaire"),
                                  ("secondary_press_ratio", "secondary_release_ratio", "secondaire")):
        low, high = hand[press], hand[release]
        if low is not None and high is not None and not low < high:
            raise BarehandsProfileError(
                "barehands_profile_thresholds_invalid",
                f"Calibration {label} impossible ({where}) : press ({low}) doit rester sous release ({high}).",
            )
        # **Une hystérésis se calibre par paire, ou pas du tout.** Une moitié
        # mesurée et l'autre au défaut du moteur peut inverser l'invariant
        # `press < release` — une calibration partielle (décision 31) produirait
        # alors un réglage que le moteur refuse. On refuse la demi-mesure ici,
        # où l'on peut encore la nommer, plutôt qu'à l'application.
        if (low is None) != (high is None):
            raise BarehandsProfileError(
                "barehands_profile_thresholds_incomplete",
                f"Calibration {label} incomplète ({where}) : press et release se mesurent ensemble ou pas du tout.",
            )
    return hand


def _apply_stage(where: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise BarehandsProfileError("barehands_profile_bad_payload", f"« {where} » doit être un objet.")
    unknown = set(map(str, raw)) - {"status", "reason", "samples"}
    if unknown:
        raise BarehandsProfileError(
            "barehands_profile_unknown_field",
            f"Champ inconnu dans « {where} » : {', '.join(sorted(unknown))}.",
        )
    status = raw.get("status", "skipped")
    if status not in STAGE_STATUSES:
        raise BarehandsProfileError(
            "barehands_profile_stage_unknown", f"État d'étape inconnu ({where}) : {status!r}.")
    reason = raw.get("reason")
    if reason is not None and reason not in STAGE_REASONS:
        # Le motif est la seule chaîne qu'un profil porte : la fermer est ce qui
        # empêche ce champ de devenir un commentaire libre (décision 32).
        raise BarehandsProfileError(
            "barehands_profile_stage_unknown", f"Motif d'étape inconnu ({where}) : {reason!r}.")
    if status == "ok" and reason is not None:
        raise BarehandsProfileError(
            "barehands_profile_stage_inconsistent",
            f"Étape réussie portant un motif d'échec ({where}) : {reason}.",
        )
    if status == "failed" and reason is None:
        raise BarehandsProfileError(
            "barehands_profile_stage_inconsistent",
            f"Étape échouée sans motif ({where}) : un échec sans raison ne se distingue pas d'une panne.",
        )
    samples = raw.get("samples", 0)
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 0:
        raise BarehandsProfileError(
            "barehands_profile_not_derived", f"« {where}.samples » doit être un entier positif ou nul.")
    return {"status": status, "reason": reason, "samples": samples}


#: Les paires d'hystérésis d'une main : elles se remplacent entières.
PROFILE_PAIRS: tuple[tuple[str, str], ...] = (
    ("press_ratio", "release_ratio"), ("secondary_press_ratio", "secondary_release_ratio"))


def _read_replaces(raw: Any) -> dict[str, Any]:
    """``replaces`` validé, miroir de ``readReplaces`` du contrat (parité testée)."""

    def bad(message: str) -> None:
        raise BarehandsProfileError("barehands_profile_replaces_invalid", f"Fusion du profil : {message}")

    if not isinstance(raw, Mapping):
        bad("« replaces » doit être un objet.")
    for key in raw:
        if key not in ("hands", "stages"):
            bad(f"champ inconnu « {key} ».")
    hands_in = raw.get("hands", {})
    if not isinstance(hands_in, Mapping):
        bad("« replaces.hands » doit être un objet.")
    measured = (*HAND_BOUNDS, "reach_norm")
    hands: dict[str, list[str]] = {}
    for handedness, keys in hands_in.items():
        if handedness not in HANDEDNESSES:
            bad(f"latéralité inconnue « {handedness} ».")
        if not isinstance(keys, list):
            bad(f"« replaces.hands.{handedness} » doit être une liste.")
        for key in keys:
            if not isinstance(key, str) or key not in measured:
                bad(f"clé inconnue « {key} ».")
        if len(set(keys)) != len(keys):
            bad(f"clé en double dans « replaces.hands.{handedness} ».")
        for press, release in PROFILE_PAIRS:
            if (press in keys) != (release in keys):
                raise BarehandsProfileError(
                    "barehands_profile_thresholds_incomplete",
                    f"Fusion du profil : {press} et {release} se remplacent ensemble (main {handedness}).",
                )
        if keys:
            hands[handedness] = list(keys)
    stages_in = raw.get("stages", [])
    if not isinstance(stages_in, list):
        bad("« replaces.stages » doit être une liste.")
    for stage in stages_in:
        if not isinstance(stage, str) or stage not in STAGES:
            bad(f"étape inconnue « {stage} ».")
    if len(set(stages_in)) != len(stages_in):
        bad("étape en double dans « replaces.stages ».")
    if not hands and not stages_in:
        raise BarehandsProfileError(
            "barehands_profile_replaces_empty", "Fusion du profil : rien n'est annoncé comme remplacé.")
    return {"hands": hands, "stages": list(stages_in)}


def _apply_merge(settings: dict[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """**L'enregistrement fusionné** (tâche adaptative, Slice 09, décision 69).

    La charge utile **annonce** ce qu'elle remplace (``replaces``) ; seules ces
    clés et ces étapes changent, tout le reste de ce qui est enregistré reste —
    une étape passée ou échouée, l'autre main. Validation stricte : une clé
    annoncée a une valeur, une valeur non annoncée se refuse, les étapes
    envoyées sont exactement celles annoncées. ``tuning`` absent : gardé ;
    présent : remplacé comme avant (décision 48). Miroir de ``mergeProfile``.
    """

    claims = _read_replaces(payload.get("replaces"))

    def mismatch(message: str) -> None:
        raise BarehandsProfileError("barehands_profile_replaces_mismatch", f"Fusion du profil : {message}")

    value = load(settings)
    hands = payload.get("hands")
    hands = {} if hands is None else hands
    if not isinstance(hands, Mapping):
        raise BarehandsProfileError("barehands_profile_bad_payload", "« hands » doit être un objet.")
    for handedness, hand in hands.items():
        if handedness not in HANDEDNESSES:
            raise BarehandsProfileError(
                "barehands_profile_handedness_unknown", f"Latéralité inconnue : {handedness}.")
        if hand is None:
            continue
        if not isinstance(hand, Mapping):
            raise BarehandsProfileError(
                "barehands_profile_bad_payload", f"« hands.{handedness} » doit être un objet.")
        for key, got in hand.items():
            if got is not None and key not in claims["hands"].get(handedness, []):
                mismatch(f"« {handedness}.{key} » a une valeur mais n'est pas annoncée.")
    for handedness in HANDEDNESSES:
        keys = claims["hands"].get(handedness, [])
        if not keys:
            continue
        merged = dict(value["hands"][handedness])
        given = hands.get(handedness) or {}
        for key in keys:
            if given.get(key) is None:
                mismatch(f"« {handedness}.{key} » est annoncée sans valeur.")
            merged[key] = given[key]
        value["hands"][handedness] = _apply_hand(f"hands.{handedness}", merged)
    stages = payload.get("stages")
    stages = {} if stages is None else stages
    if not isinstance(stages, Mapping):
        raise BarehandsProfileError("barehands_profile_bad_payload", "« stages » doit être un objet.")
    sent = [stage for stage, got in stages.items() if got is not None]
    if sorted(sent) != sorted(claims["stages"]):
        mismatch(f"les étapes envoyées ({', '.join(sent) or 'aucune'}) ne sont pas celles annoncées "
                 f"({', '.join(claims['stages']) or 'aucune'}).")
    for stage in claims["stages"]:
        value["stages"][stage] = _apply_stage(f"stages.{stage}", stages[stage])
    if "tuning" in payload:
        value["tuning"] = _apply_tuning(payload.get("tuning"))
    at = payload.get("updated_at")
    if at is not None and (isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at)):
        raise BarehandsProfileError(
            "barehands_profile_not_derived", "« updated_at » doit être un horodatage en millisecondes.")
    if at is not None:
        value["updated_at"] = at
    value["calibrated"] = _derive_calibrated(value)
    value["tuned"] = _derive_tuned(value)
    archive_unreadable(settings)
    settings[SETTING_KEY] = dict(value)
    return dict(value)


def apply(settings: dict[str, Any], payload: Any) -> dict[str, Any]:
    """Valider puis ranger le profil dans ``settings`` (sans écrire le fichier).

    Écriture **stricte**, liste blanche : chaque clé est relue par son nom, donc
    rien de ce que le schéma ne nomme pas n'atteint le fichier. C'est ici que la
    décision 32 se tient contre un appelant qu'on n'a pas écrit — la page est de
    notre côté, le réseau ne l'est pas.

    **Deux sens, choisis par la charge utile** (décision 69). Avec
    ``replaces``, l'écriture est **fusionnée** (``_apply_merge``) : seules les
    clés et les étapes annoncées changent. Sans ``replaces``, l'ancien sens
    reste : une clé absente n'est pas conservée, le profil est remplacé en
    entier — c'est ce que fait l'acceptation d'un essai, qui envoie un profil
    complet. Une calibration envoie toujours ``replaces`` depuis la Slice 09
    adaptative.
    """

    if not isinstance(payload, Mapping):
        raise BarehandsProfileError(
            "barehands_profile_bad_payload", "Le profil de calibration attend un objet JSON.")
    unknown = set(map(str, payload)) - {SCHEMA_KEY, "hands", "tuning", "stages", "updated_at", "calibrated", "tuned",
                                        "replaces"}
    if unknown:
        raise BarehandsProfileError(
            "barehands_profile_unknown_field",
            f"Champ inconnu dans le profil : {', '.join(sorted(unknown))}.",
        )
    version = payload.get(SCHEMA_KEY)
    if version is None or (version != SCHEMA_VERSION and version not in MIGRATED_SCHEMA_VERSIONS):
        # La version reste **obligatoire** à l'écriture : un profil sans numéro
        # est un profil dont on ne saura pas quoi faire le jour où le schéma
        # bougera. Une version étrangère reste refusée : on ne la convertit pas.
        raise BarehandsProfileError(
            "barehands_profile_schema_version_unsupported",
            f"Profil de calibration en version {version!r} ; ce serveur n'écrit que la version {SCHEMA_VERSION}.",
        )
    # **La couture de migration, des deux côtés** (constat de la Slice 11, même
    # asymétrie que dans `barehands_test_mode`). `load` convertissait une v1 —
    # ses six mesures restent valides, `travel_slop_norm` et le rapport par
    # étape retombent sur « non mesuré » — mais `apply` refusait la v1 comme une
    # version inconnue. Une calibration v1 relue puis réenregistrée se faisait
    # donc refuser par le serveur même qui venait de la lire, et le bloc ne
    # montait jamais en v2. La conversion n'a rien à faire de plus ici : `value`
    # part de `defaults()`, qui porte déjà `SCHEMA_KEY: SCHEMA_VERSION`, et
    # aucune clé du schéma v2 n'est obligatoire dans la charge utile — une v1
    # qui n'en porte pas laisse simplement « non mesuré » là où elle ne mesurait
    # rien, ce qui est exactement ce que `load` en faisait.
    if "replaces" in payload:
        return _apply_merge(settings, payload)
    value = defaults()
    hands = payload.get("hands")
    if hands is not None:
        if not isinstance(hands, Mapping):
            raise BarehandsProfileError("barehands_profile_bad_payload", "« hands » doit être un objet.")
        unknown_hands = set(map(str, hands)) - set(HANDEDNESSES)
        if unknown_hands:
            raise BarehandsProfileError(
                "barehands_profile_handedness_unknown",
                f"Latéralité inconnue : {', '.join(sorted(unknown_hands))}.",
            )
        for handedness in HANDEDNESSES:
            got = hands.get(handedness)
            if got is not None:
                value["hands"][handedness] = _apply_hand(f"hands.{handedness}", got)
    value["tuning"] = _apply_tuning(payload.get("tuning"))
    stages = payload.get("stages")
    if stages is not None:
        if not isinstance(stages, Mapping):
            raise BarehandsProfileError("barehands_profile_bad_payload", "« stages » doit être un objet.")
        unknown_stages = set(map(str, stages)) - set(STAGES)
        if unknown_stages:
            raise BarehandsProfileError(
                "barehands_profile_stage_unknown",
                f"Étape inconnue : {', '.join(sorted(unknown_stages))}.",
            )
        for stage in STAGES:
            got = stages.get(stage)
            if got is not None:
                value["stages"][stage] = _apply_stage(f"stages.{stage}", got)
    at = payload.get("updated_at")
    if at is not None and (isinstance(at, bool) or not isinstance(at, (int, float))
                           or not math.isfinite(at)):
        raise BarehandsProfileError(
            "barehands_profile_not_derived", "« updated_at » doit être un horodatage en millisecondes.")
    value["updated_at"] = at
    # `calibrated` est **dérivé**, jamais repris : c'est la donnée qui décide,
    # pas l'annonce. Un appelant qui l'envoie ne se fait pas refuser — il se
    # fait ignorer, et `load` dira la vérité.
    value["calibrated"] = _derive_calibrated(value)
    value["tuned"] = _derive_tuned(value)
    archive_unreadable(settings)
    settings[SETTING_KEY] = dict(value)
    return dict(value)


def clear(settings: dict[str, Any]) -> dict[str, Any]:
    """Réinitialiser le profil : le moteur revient à ses défauts (décision 31).

    Le bloc est **retiré**, pas rempli de nulls : « aucun profil » et « un profil
    vide » doivent se relire pareil, et le fichier ne doit pas garder une coquille
    qui ressemble à une calibration.
    """

    settings.pop(SETTING_KEY, None)
    return defaults()


def describe(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que ``GET``/``POST /api/barehands/profile`` rendent.

    ``stored_schema_version`` et ``unreadable`` séparent « pas encore calibré »
    de « une calibration existe et cette version ne sait pas la lire » — les deux
    rendent le même profil vierge, et ils ne veulent pas dire la même chose.
    """

    seen = inspect(settings)
    return {
        **load(settings),
        "stored_schema_version": seen["stored_schema_version"],
        "unreadable": seen["unreadable"],
        "archived": archived_keys(settings),
        "stage_order": list(STAGES),
    }
