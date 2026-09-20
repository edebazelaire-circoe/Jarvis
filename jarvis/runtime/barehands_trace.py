"""Traces de diagnostic Bare Hands : la liste blanche côté serveur, et le rangement.

Slice 10, architecture §12, décision 32 (« aucune image ni vidéo conservée ;
seulement des paramètres dérivés et des mesures de qualité »).

**Pourquoi ce module existe alors que le module JS refuse déjà.** Le module JS
est de notre côté ; le réseau ne l'est pas. `POST /api/barehands/traces` est une
route ouverte : n'importe quel appelant peut y poster n'importe quoi, et si le
serveur se contentait d'écrire ce qu'on lui donne, la garantie de la décision 32
tiendrait exactement aussi longtemps que la bonne volonté de l'appelant. C'est
le même raisonnement, et le même partage des rôles, que `barehands_profile`
pour le profil de calibration (§10).

**Ce qu'une trace a le droit de porter**, et la liste est courte : des nombres,
des booléens, et des mots de vocabulaires **fermés**. Rien d'autre n'est
recopié — pas refusé, *pas recopié*, ce qui est plus fort : une clé ajoutée
demain par un appelant distrait ne ressort pas de l'autre côté parce que
personne ne la lit.

Trois refus codés, tous rendus dans `X-Jarvis-Error-Code` :

- ``barehands_trace_schema_unknown`` — ce document n'est pas une trace ;
- ``barehands_trace_version_unsupported`` — une version que ce Jarvis ne lit
  pas. Elle se **refuse** plutôt que se deviner : deviner produirait des
  nombres, et des nombres faux sont pires que pas de nombres ;
- ``barehands_trace_invalid`` — la forme est celle d'une trace mais son contenu
  ne l'est pas (pas de liste d'images, trop d'images, nombres illisibles).

Rangement : ``<runtime_root>/barehands-traces/<horodatage>-<empreinte>.json``,
et **une** ligne de journal par trace (`RuntimeJournal`, constat F6 de la
Slice 00). Précédent : `jarvis/runtime/voice_metrics.py`, qui écrit ses rapports
sous `<runtime_root>/benchmarks/voice-sessions/`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

#: Le nom du schéma, tel que le module JS l'écrit. Il est dans le document et
#: non dans le nom du fichier : une trace relue dans six mois doit dire
#: elle-même ce qu'elle est.
TRACE_SCHEMA = "jarvis.barehands.trace"
SCHEMA_VERSION = 1

#: Le dossier, sous la racine d'exécution. Les traces ne sont pas des réglages :
#: elles ne vivent pas dans le fichier de configuration, et les effacer ne
#: casse rien.
TRACE_DIRNAME = "barehands-traces"

#: Bornes dures. Une trace est un document JSON que quelqu'un relira : au-delà,
#: on refuse plutôt que d'écrire un fichier que personne n'ouvrira. Le plafond
#: d'images est celui du module JS (`DEFAULTS.maxFrames`), doublé pour laisser
#: passer une trace enregistrée avec des options élargies sans laisser passer
#: n'importe quoi.
MAX_FRAMES = 18000
MAX_BYTES = 32 * 1024 * 1024

#: Les vocabulaires fermés, miroirs de ceux du contrat JS. Un mot ajouté d'un
#: seul côté est un mot qui traverse ici et pas là, ou l'inverse ; un test de
#: parité les compare aux tables de `control_center_barehands_contracts.js`.
HANDEDNESSES = ("left", "right", "unknown")
LIFECYCLES = ("off", "sleep", "active", "error")
INTERACTIONS = ("hover", "click", "context", "drag_start", "drag_move", "drag_end",
                "scroll", "select", "move", "resize")
PINCH_CHANNELS = ("primary", "secondary")
REGIONS = ("body", "edge", "corner")
REPRESENTATIONS = ("capsule", "window")
GESTURES = ("c_pose", "open_palm", "fist", "double_close", "clap")
GESTURE_PHASES = ("start", "hold", "end", "cancel")
#: Miroir de `TRACE_KINDS` du module JS (et non du `kind` libre du contrat, qui
#: est précisément la porte que la trace ferme).
TRACE_KINDS = ("scene_object", "link", "button", "tab", "field", "card", "notice",
               "control", "unknown", "other")

#: Les clés scalaires d'une main. Toutes des nombres ou `None` — jamais une
#: chaîne, jamais une structure.
HAND_NUMBERS = ("primaryRatio", "secondaryRatio", "cPose", "closure", "gapPalms",
                "indexReachPalms", "palmNorm", "rawX", "rawY", "filteredX", "filteredY",
                "palmX", "palmY", "quality", "stillness", "speedPxPerSec")
CANDIDATE_NUMBERS = ("x", "y", "w", "h")

MAX_HANDS = 2


class BarehandsTraceError(ValueError):
    """Une trace refusée, avec le code que l'en-tête et le journal portent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject(code: str, message: str) -> None:
    raise BarehandsTraceError(code, message)


def _number(raw: Any) -> float | None:
    """Un nombre fini, ou ``None``.

    ``None`` est une **absence**, jamais zéro : c'est la leçon
    ``Number(null) === 0`` de cette tâche, où une valeur absente s'est lue comme
    une mesure au plancher. Et ``bool`` est exclu d'abord parce qu'il est une
    sous-classe de ``int`` en Python : sans cette ligne, ``True`` passerait
    pour la mesure ``1``.
    """

    if raw is None or isinstance(raw, bool):
        return None
    if not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _word(raw: Any, vocabulary: Iterable[str]) -> str | None:
    return raw if isinstance(raw, str) and raw in tuple(vocabulary) else None


def _flag(raw: Any) -> bool:
    return raw is True


def _count(raw: Any) -> int:
    value = _number(raw)
    return int(value) if value is not None and value > 0 else 0


def _hand(raw: Any, slot: int) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    hand: dict[str, Any] = {"slot": slot,
                            "handedness": _word(source.get("handedness"), HANDEDNESSES)}
    for key in HAND_NUMBERS:
        hand[key] = _number(source.get(key))
    return hand


def _candidate(raw: Any, ref: int) -> dict[str, Any]:
    """La géométrie vient de ``boundsPx`` (la forme du contrat) **ou** du plat.

    La lecture doit être idempotente : une trace relue du disque, ou rejouée,
    repasse par ici, et une lecture qui ne connaîtrait que ``boundsPx`` rendrait
    quatre ``None``. Le résolveur ne verrait alors plus aucune cible, et le banc
    d'essai dirait « aucun clic n'a atteint sa cible » d'une séance où tous
    l'avaient atteinte.
    """

    source = raw if isinstance(raw, dict) else {}
    box = source.get("boundsPx") if isinstance(source.get("boundsPx"), dict) else source
    candidate: dict[str, Any] = {
        "ref": ref,
        "kind": source.get("kind") if source.get("kind") in TRACE_KINDS else "other",
        "region": _word(source.get("region"), REGIONS),
        "representation": _word(source.get("representation"), REPRESENTATIONS),
        "actionable": _flag(source.get("actionable")),
    }
    for key in CANDIDATE_NUMBERS:
        candidate[key] = _number(box.get(key))
    return candidate


def _event(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    axes = source.get("axes")
    return {"type": _word(source.get("type"), INTERACTIONS),
            "channel": _word(source.get("channel"), PINCH_CHANNELS),
            # Idempotent comme `_candidate` : la page envoie un `objectId` et
            # une liste d'axes, une trace porte un booléen et un compte.
            "onObject": _flag(source.get("onObject")) or bool(str(source.get("objectId") or "")),
            "axes": _count(len(axes) if isinstance(axes, list) else axes)}


def _gesture(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    return {"name": _word(source.get("name"), GESTURES),
            "phase": _word(source.get("phase"), GESTURE_PHASES),
            "suppressed": _flag(source.get("suppressed"))}


def _list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _frame(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    at = _number(source.get("t"))
    return {
        "t": max(0.0, at) if at is not None else 0.0,
        "lifecycle": _word(source.get("lifecycle"), LIFECYCLES),
        "hands": [_hand(hand, slot)
                  for slot, hand in enumerate(_list(source.get("hands"))[:MAX_HANDS])],
        "candidates": [_candidate(candidate, ref)
                       for ref, candidate in enumerate(_list(source.get("candidates")))],
        "events": [_event(event) for event in _list(source.get("events"))],
        "gestures": [_gesture(gesture) for gesture in _list(source.get("gestures"))],
    }


def normalize(payload: Any) -> dict[str, Any]:
    """Reconstruire une trace **clé par clé**, ou refuser avec un code.

    Rien de la source n'est recopié : chaque clé du document rendu est écrite
    ici, à la main, depuis une valeur qui a traversé un lecteur typé. Ce que le
    schéma ne nomme pas n'atteint jamais le disque.
    """

    if not isinstance(payload, dict):
        _reject("barehands_trace_schema_unknown",
                "Trace attendue sous forme d'objet JSON.")
    if payload.get("schema") != TRACE_SCHEMA:
        _reject("barehands_trace_schema_unknown",
                f"Ce document n'est pas une trace Bare Hands (schema « {payload.get('schema')!s} »).")
    version = payload.get("schemaVersion")
    if version != SCHEMA_VERSION:
        _reject("barehands_trace_version_unsupported",
                f"Trace en version {version!s} ; ce Jarvis lit la version {SCHEMA_VERSION}. "
                "Une version inconnue se refuse plutôt que se deviner : rejouée au jugé, "
                "elle produirait des nombres sans rapport avec ce qui a été enregistré.")
    frames_raw = payload.get("frames")
    if not isinstance(frames_raw, list):
        _reject("barehands_trace_invalid", "Une trace doit porter une liste « frames ».")
    if len(frames_raw) > MAX_FRAMES:
        _reject("barehands_trace_invalid",
                f"Trace de {len(frames_raw)} images : au-delà de {MAX_FRAMES}, elle est refusée "
                "plutôt qu'écrite en un fichier que personne n'ouvrira.")
    viewport = payload.get("viewport") if isinstance(payload.get("viewport"), dict) else {}
    return {
        "schema": TRACE_SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "startedAt": _number(payload.get("startedAt")) or 0.0,
        "durationMs": _number(payload.get("durationMs")) or 0.0,
        "stoppedBecause": _word(payload.get("stoppedBecause"),
                                ("asked", "deadline", "max_frames")),
        "viewport": {"width": _number(viewport.get("width")) or 0.0,
                     "height": _number(viewport.get("height")) or 0.0},
        "observedFrames": _count(payload.get("observedFrames")),
        "droppedFrames": _count(payload.get("droppedFrames")),
        "frames": [_frame(frame) for frame in frames_raw],
    }


_SAFE = re.compile(r"[^a-z0-9-]")


def trace_id(trace: dict[str, Any], *, now: datetime | None = None) -> str:
    """Un identifiant lisible et **stable** : horodatage + empreinte du contenu.

    L'empreinte porte sur la trace **normalisée**, c'est-à-dire sur ce qui sera
    réellement écrit : hacher ce qu'on a reçu dirait l'empreinte d'un document
    qui n'existe nulle part.
    """

    at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    digest = hashlib.sha256(
        json.dumps(trace, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        .encode("utf-8")).hexdigest()[:12]
    return _SAFE.sub("-", f"{at.strftime('%Y%m%dt%H%M%S')}-{digest}")


def directory(runtime_root: Path) -> Path:
    return Path(runtime_root) / TRACE_DIRNAME


def store(runtime_root: Path, payload: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Normaliser, écrire, et rendre de quoi le dire à l'écran et au journal.

    Le refus remonte tel quel : c'est l'appelant (la route) qui sait le
    traduire en en-tête et en ligne de journal.
    """

    trace = normalize(payload)
    encoded = json.dumps(trace, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        _reject("barehands_trace_invalid",
                f"Trace de plus de {MAX_BYTES} octets une fois normalisée : refusée.")
    identifier = trace_id(trace, now=now)
    folder = directory(runtime_root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{identifier}.json"
    path.write_text(encoded, encoding="utf-8")
    return {"trace_id": identifier, "path": str(path), "frames": len(trace["frames"]),
            "observed_frames": trace["observedFrames"],
            "dropped_frames": trace["droppedFrames"],
            "duration_ms": trace["durationMs"],
            "stopped_because": trace["stoppedBecause"],
            "bytes": len(encoded.encode("utf-8"))}


def load(path: Path) -> dict[str, Any]:
    """Relire une trace du disque, **par la même porte** que le réseau.

    Un fichier n'est pas plus digne de confiance qu'une requête : il a pu être
    écrit par un autre Jarvis, édité à la main, ou porter une version d'un an.
    Il repasse donc par `normalize`, et une version inconnue s'y refuse.
    """

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BarehandsTraceError(
            "barehands_trace_invalid", f"Trace illisible ({path}) : {exc}") from exc
    return normalize(payload)
