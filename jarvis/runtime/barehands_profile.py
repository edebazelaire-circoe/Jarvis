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
SCHEMA_VERSION = 2

#: Versions précédentes que ``load`` sait convertir. Même couture que celle des
#: réglages, au même endroit et de la même forme.
MIGRATED_SCHEMA_VERSIONS = (1,)

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
    "travel_slop_norm": (0.002, 0.15),
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
METRIC_KEYS: tuple[str, ...] = ("quality",)

#: Les clés dont la présence vaut « calibré ». Toute clé ajoutée demain calibre
#: par défaut : c'est l'exclusion qui s'écrit, jamais l'inclusion.
CALIBRATING_KEYS: tuple[str, ...] = tuple(
    key for key in (*HAND_BOUNDS, "reach_norm") if key not in METRIC_KEYS
)

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
STAGES: tuple[str, ...] = (
    "neutral", "c_pose", "pinch_primary", "pinch_secondary", "aim", "drag", "resize",
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


def _empty_stages() -> dict[str, Any]:
    return {stage: {"status": "skipped", "reason": None, "samples": 0} for stage in STAGES}


def defaults() -> dict[str, Any]:
    """Un profil vierge : rien de mesuré, rien de calibré, aucune étape jouée."""

    return {
        SCHEMA_KEY: SCHEMA_VERSION,
        "calibrated": False,
        "updated_at": None,
        "hands": {handedness: _empty_hand() for handedness in HANDEDNESSES},
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
    low, high = HAND_BOUNDS[key]
    return min(max(float(raw), low), high)


def _load_reach(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, Mapping):
        return None
    value: dict[str, float] = {}
    for key in REACH_KEYS:
        got = raw.get(key)
        if isinstance(got, bool) or not isinstance(got, (int, float)):
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
    for press, release in (("press_ratio", "release_ratio"),
                           ("secondary_press_ratio", "secondary_release_ratio")):
        if hand[press] is not None and hand[release] is not None and not hand[press] < hand[release]:
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
    stages = stored.get("stages")
    stages = stages if isinstance(stages, Mapping) else {}
    for stage in STAGES:
        value["stages"][stage] = _load_stage(stages.get(stage))
    at = stored.get("updated_at")
    value["updated_at"] = at if isinstance(at, (int, float)) and not isinstance(at, bool) else None
    # `calibrated` est **dérivé**, jamais repris de l'entrée : « calibré » sans
    # mesure ne vaut pas calibré (contrat §10).
    value["calibrated"] = _derive_calibrated(value)
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


def apply(settings: dict[str, Any], payload: Any) -> dict[str, Any]:
    """Valider puis ranger le profil dans ``settings`` (sans écrire le fichier).

    Écriture **stricte**, liste blanche : chaque clé est relue par son nom, donc
    rien de ce que le schéma ne nomme pas n'atteint le fichier. C'est ici que la
    décision 32 se tient contre un appelant qu'on n'a pas écrit — la page est de
    notre côté, le réseau ne l'est pas.

    Contrairement aux réglages, une clé **absente** n'est pas conservée : un
    profil est écrit **en entier** par une calibration, et fusionner une écriture
    partielle avec ce qui est enregistré mêlerait deux séances de mesure sur une
    même main sans que rien ne le dise.
    """

    if not isinstance(payload, Mapping):
        raise BarehandsProfileError(
            "barehands_profile_bad_payload", "Le profil de calibration attend un objet JSON.")
    unknown = set(map(str, payload)) - {SCHEMA_KEY, "hands", "stages", "updated_at", "calibrated"}
    if unknown:
        raise BarehandsProfileError(
            "barehands_profile_unknown_field",
            f"Champ inconnu dans le profil : {', '.join(sorted(unknown))}.",
        )
    version = payload.get(SCHEMA_KEY)
    if version is None or version != SCHEMA_VERSION:
        # La couture de migration : c'est ici qu'une version précédente
        # s'accepterait et se convertirait. Et la version est **obligatoire** à
        # l'écriture : un profil sans numéro est un profil dont on ne saura pas
        # quoi faire le jour où le schéma bougera.
        raise BarehandsProfileError(
            "barehands_profile_schema_version_unsupported",
            f"Profil de calibration en version {version!r} ; ce serveur n'écrit que la version {SCHEMA_VERSION}.",
        )
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
    if at is not None and (isinstance(at, bool) or not isinstance(at, (int, float))):
        raise BarehandsProfileError(
            "barehands_profile_not_derived", "« updated_at » doit être un horodatage en millisecondes.")
    value["updated_at"] = at
    # `calibrated` est **dérivé**, jamais repris : c'est la donnée qui décide,
    # pas l'annonce. Un appelant qui l'envoie ne se fait pas refuser — il se
    # fait ignorer, et `load` dira la vérité.
    value["calibrated"] = _derive_calibrated(value)
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
