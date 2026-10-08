"""Rechargement a chaud d'une scene : vocabulaire et regles pures (handoff jarvis-interactive-presentation-studio, Slice 06).

Une edition de **source** (niveau 3, D11) publie une nouvelle revision immuable du prefab de la scene, epingle ce pin exact
dans la variante et re-patche l'unique fenetre « stage » : la regle de remontage de l'hote (changement de `(id, version)`)
recharge ce cadre-la et aucun autre (`docs/presentation-studio.md` › *Hot reload contract*). Ce module ne fait aucune E/S ;
le service Core est `jarvis/core/presentation_studio_reload.py`.

Contenu :

- `parse_source_edit` : la requete `{actor, basis, scene_id, files, request_id?, allow_state_reset?}` ;
- `source_prefab_id` / `compose_candidate` : le candidat `{manifest, template, style, behavior}` (le pin courant +
  les fichiers donnes) sous l'id propre a la scene ;
- `plan_carry_over` : ce que les **valeurs studio** (`props`/`data`, controles, ancres) deviennent sous le nouveau
  manifeste : conservees, remises a zero (`StateReset`, seulement si l'appelant l'a permis) ou refusees ;
- `ReloadStatus` / `ReloadResult` : les issues explicites ;
- `MountReport` : ce que l'hote dit avoir observe (jamais ce qui a ete demande).

Aucun resultat, evenement ni journal ne porte une **valeur** de scene ni le texte d'une source : des ids, des statuts, des
codes, des noms de cles et des comptes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
import re
from typing import Any

from jarvis.domain.prefab import (
    MAX_BEHAVIOR_BYTES, MAX_MANIFEST_BYTES, MAX_STYLE_BYTES, MAX_TEMPLATE_BYTES, PrefabManifest, PrefabRef,
    validate_value,
)
from jarvis.domain.presentation_studio import PresentationVariant
from jarvis.domain.presentation_studio_checks import (
    PresentationStudioError, PresentationStudioErrorCode as C, _check_int, _exact_keys, _fail, clip,
)
from jarvis.domain.presentation_studio_edit import StudioActor, unsafe_key_in
from jarvis.domain.presentation_studio_scene import StudioScene, check_scene

#: Corps d'une requete de source : quatre fichiers (plafonds des prefabs) plus l'echappement JSON.
MAX_SOURCE_BODY_BYTES = 2 * (MAX_MANIFEST_BYTES + MAX_TEMPLATE_BYTES + MAX_STYLE_BYTES + MAX_BEHAVIOR_BYTES)
SOURCE_FILES = ("manifest", "template", "style", "behavior")
_LIMITS = {"manifest": MAX_MANIFEST_BYTES, "template": MAX_TEMPLATE_BYTES, "style": MAX_STYLE_BYTES,
           "behavior": MAX_BEHAVIOR_BYTES}
REQUEST_ID = re.compile(r"psq_[0-9a-f]{12}\Z")
#: Code court (jamais un message) : meme grammaire que le protocole `jv:1` pour `reason`.
REASON = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
MAX_MOUNT_MESSAGE = 300
MAX_RESET_NAMES = 32
#: Pas de rafale de rechargements au-dela de cette borne dans la file d'historique du service (visible, jamais silencieuse).
MAX_RECENT_RELOADS = 64


class ReloadStatus(StrEnum):
    #: Publie, epingle, fenetre stage patchee ET montage confirme par l'hote ; les valeurs studio sont conservees.
    RELOADED = "reloaded"
    #: Comme `reloaded`, mais des valeurs studio n'ont pas pu etre conservees : `reset` les nomme (toujours visible).
    RELOADED_STATE_RESET = "reloaded_state_reset"
    #: Publie et epingle ; aucune fenetre stage n'affiche cette scene : rien n'a ete recharge, le pin attend d'etre vu monte.
    REPINNED = "repinned"
    #: Publie, epingle, stage patche ; l'hote n'a rien rapporte dans le delai. Le pin tient, le repli aussi : un rapport
    #: tardif d'echec le ramenera en arriere, un rapport de succes le confirmera.
    PENDING_MOUNT = "pending_mount"
    #: Refus avant toute publication (candidat invalide, valeurs incompatibles...) : rien n'a change.
    REFUSED_VALIDATION = "refused_validation"
    #: Le montage ou une etape a echoue : le pin est revenu a la derniere version valide, la scene est intacte.
    ROLLED_BACK = "rolled_back"
    #: La base de l'appelant est perimee (variante ou pin deja change) : relire puis recommencer.
    STALE = "stale"
    #: Le montage a echoue mais le retour arriere n'a pas pu se faire jusqu'au bout (fenetre stage ou variante non
    #: restauree apres des essais bornes) : la scene porte la nouvelle version, son repli (`last_valid_pin`) reste ecrit
    #: pour qu'un rechargement ou un redemarrage la repare. Toujours visible, jamais presente comme une reussite.
    DEGRADED = "degraded"

    @property
    def stood(self) -> bool:
        """Vrai si la nouvelle source est en place (confirmee ou en attente de confirmation)."""

        return self in (ReloadStatus.RELOADED, ReloadStatus.RELOADED_STATE_RESET, ReloadStatus.REPINNED,
                        ReloadStatus.PENDING_MOUNT)


HTTP_STATUS: Mapping[ReloadStatus, int] = {
    ReloadStatus.RELOADED: 200, ReloadStatus.RELOADED_STATE_RESET: 200, ReloadStatus.REPINNED: 200,
    ReloadStatus.PENDING_MOUNT: 202, ReloadStatus.REFUSED_VALIDATION: 400, ReloadStatus.ROLLED_BACK: 409,
    ReloadStatus.STALE: 409, ReloadStatus.DEGRADED: 409,
}


@dataclass(frozen=True, slots=True)
class ReloadOrigin:
    """Le jeton `origin` d'un commit ecrit par le rechargement a chaud (Slice 06), rendu aux abonnes de commit du service
    d'edition (`add_commit_listener`). Jamais lu d'un corps de requete : seul le service de rechargement le cree. La lecture
    (Slice 12) le reconnait : une scene dont la source est rechargee n'interrompt pas le run (pas de pause), le plan est
    relu et le run reste sur le meme element ; la fenetre stage, elle, a deja ete patchee par le rechargement."""

    scene_id: str
    step: str  # `pin` | `confirm` | `rollback`


# ------------------------------------------------------------------ requete

@dataclass(frozen=True, slots=True)
class SourceEditRequest:
    actor: StudioActor
    basis_revision: int
    scene_id: str
    #: Fichiers a **remplacer** (les autres restent ceux du pin courant) : `manifest` (objet), `template`, `style`, `behavior` (textes).
    files: Mapping[str, Any]
    request_id: str | None = None
    #: Permet de remettre a zero les valeurs studio devenues incompatibles (sinon : refus). Jamais implicite.
    allow_state_reset: bool = False


def parse_source_edit(raw: object) -> SourceEditRequest:
    data = _exact_keys(raw, "source edit", {"actor", "basis", "scene_id", "files"},
                       frozenset({"request_id", "allow_state_reset"}))
    try:
        actor = StudioActor(data["actor"])
    except ValueError:
        raise _fail("actor must be 'user' or 'brain'") from None
    basis = _exact_keys(data["basis"], "basis", {"variant_revision"})
    _check_int("basis.variant_revision", basis["variant_revision"], 1, 2**31 - 1)
    if not isinstance(data["scene_id"], str):
        raise _fail("scene_id must be a string")
    files = data["files"]
    if not isinstance(files, dict) or not files:
        raise _fail("files must be a non-empty object of manifest/template/style/behavior")
    unknown = sorted(str(key)[:40] for key in files if key not in SOURCE_FILES)
    if unknown:
        raise _fail(f"files: unknown keys {', '.join(unknown[:6])} (allowed: {', '.join(SOURCE_FILES)})")
    for name, value in files.items():
        if name == "manifest":
            if not isinstance(value, dict):
                raise _fail("files.manifest must be a JSON object")
        elif not isinstance(value, str):
            raise _fail(f"files.{name} must be a string")
        elif len(value.encode("utf-8", errors="surrogatepass")) > _LIMITS[name]:
            raise _fail(f"files.{name} exceeds {_LIMITS[name]} bytes")
    request_id = data.get("request_id")
    if request_id is not None and (not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id)):
        raise _fail("request_id must be a source request id (psq_ + 12 hex)")
    allow = data.get("allow_state_reset", False)
    if type(allow) is not bool:
        raise _fail("allow_state_reset must be a boolean")
    return SourceEditRequest(actor, basis["variant_revision"], data["scene_id"], dict(files), request_id, allow)


# ------------------------------------------------------------------ candidat

def source_prefab_id(presentation_id: str, scene_id: str) -> str:
    """L'id de prefab propre a la scene : `presentation-studio.p<12 hex>.s<12 hex>` (espace reserve a la retention, 01a).
    Une variante garde le meme id et se distingue par la version epinglee ; une scene de la presentation a le sien."""

    return f"presentation-studio.p{presentation_id.removeprefix('pst_')[:12]}.s{scene_id.removeprefix('pss_')[:12]}"


def compose_candidate(base_manifest: Mapping[str, Any], base_files: Mapping[str, str], files: Mapping[str, Any],
                      *, prefab_id: str) -> dict[str, Any]:
    """`{manifest, template, style, behavior}` : le pin courant, ses fichiers remplaces par ceux de la requete, sous
    l'id de la scene. Le numero de version du manifeste est celui de Core a la publication, jamais celui du candidat."""

    manifest = dict(files["manifest"]) if "manifest" in files else {
        key: value for key, value in base_manifest.items()}
    manifest["id"] = prefab_id
    manifest.setdefault("version", base_manifest.get("version", 1))
    return {"manifest": manifest,
            "template": files.get("template", base_files["template"]),
            "style": files.get("style", base_files["style"]),
            "behavior": files.get("behavior", base_files["behavior"])}


def unsafe_manifest_key(manifest: Mapping[str, Any]) -> str | None:
    """Un nom de propriete `__proto__` / `constructor` / `prototype` declare par le manifeste (entrees, evenements,
    echantillon) : refuse, car le code de page qui patche par cle ne doit jamais le recevoir (QA S04/S05)."""

    for part in ("inputs", "events", "sample"):
        found = unsafe_key_in(manifest.get(part))
        if found is not None:
            return found
    return None


# ------------------------------------------------------------------ continuite des valeurs studio

@dataclass(frozen=True, slots=True)
class StateReset:
    """Ce qui n'a pas pu etre conserve : des **noms** (cles de premier niveau, ids de controle et d'ancre), jamais de valeur."""

    props: tuple[str, ...] = ()
    data: tuple[str, ...] = ()
    controls: tuple[str, ...] = ()
    anchors: tuple[str, ...] = ()
    #: Les valeurs vivantes du cadre (committees par ses evenements d'etat) etaient incompatibles : retour aux valeurs de la scene.
    runtime: bool = False

    @property
    def empty(self) -> bool:
        return not (self.props or self.data or self.controls or self.anchors or self.runtime)

    def to_dict(self) -> dict[str, Any]:
        return {"props": list(self.props[:MAX_RESET_NAMES]), "data": list(self.data[:MAX_RESET_NAMES]),
                "controls": list(self.controls[:MAX_RESET_NAMES]), "anchors": list(self.anchors[:MAX_RESET_NAMES]),
                "runtime_values": self.runtime}

    def merged(self, other: StateReset) -> StateReset:
        return StateReset(tuple(sorted({*self.props, *other.props})), tuple(sorted({*self.data, *other.data})),
                          tuple(sorted({*self.controls, *other.controls})), tuple(sorted({*self.anchors, *other.anchors})),
                          self.runtime or other.runtime)


@dataclass(frozen=True, slots=True)
class CarryOver:
    """`scene` : la scene repinnee au nouveau manifeste (`None` : refus, `problems` dit pourquoi)."""

    scene: StudioScene | None
    reset: StateReset | None = None
    problems: tuple[str, ...] = ()


_TOP_KEY = re.compile(r"(props|data)\.([A-Za-z_][A-Za-z0-9_]*)")
_UNKNOWN_KEYS = re.compile(r"(props|data): unknown keys \[(.*)\]")


def _value_problems(manifest: PrefabManifest, props: Mapping[str, Any], data: Mapping[str, Any]) -> list[str]:
    return [*validate_value(manifest.props, props, "props")[1], *validate_value(manifest.data, data, "data")[1]]


def scene_problems(scene: StudioScene, manifest: PrefabManifest) -> list[str]:
    """Controles (chemin, bornes, defaut) et valeurs de la scene **repinnee** au manifeste (pur, sans catalogue)."""

    repinned = replace(scene, prefab=manifest.ref)
    return [*check_scene(repinned, manifest), *_value_problems(manifest, scene.props, scene.data)]


def _bad_keys(problems: list[str]) -> dict[str, set[str]]:
    """Les cles de premier niveau que les problemes de valeur nomment, par racine (`props` / `data`)."""

    keys: dict[str, set[str]] = {"props": set(), "data": set()}
    for problem in problems:
        unknown = _UNKNOWN_KEYS.match(problem)
        if unknown:
            keys[unknown.group(1)].update(item.strip().strip("'\"") for item in unknown.group(2).split(",") if item.strip())
            continue
        found = _TOP_KEY.match(problem)
        if found:
            keys[found.group(1)].add(found.group(2))
    return keys


def plan_carry_over(scene: StudioScene, manifest: PrefabManifest, *, allow_reset: bool) -> CarryOver:
    """Les valeurs studio de `scene` sous `manifest` (le manifeste du **candidat** ou d'une version publiee).

    1. Aucun probleme : la scene est repinnee telle quelle (valeurs, controles et ancres conserves).
    2. Problemes et `allow_reset` faux : refus, la liste des problemes est rendue (bornee, sans valeur).
    3. Problemes et `allow_reset` vrai : on retire ce qui ne tient plus, **par nom** : les cles de premier niveau de
       `props`/`data` que le manifeste refuse, les controles dont le chemin/les bornes ne tiennent plus, et le lien
       controle des ancres concernees (l'ancre reste). Ce qui reste doit etre valide ; sinon refus (ex. une cle
       maintenant requise sans defaut ne se « remet pas a zero »).
    """

    problems = scene_problems(scene, manifest)
    repinned = replace(scene, prefab=manifest.ref)
    if not problems:
        return CarryOver(repinned)
    if not allow_reset:
        return CarryOver(None, None, tuple(problems))
    props, data = dict(scene.props), dict(scene.data)
    dropped = {"props": set(), "data": set()}
    for _ in range(3):  # a removed key can expose a nested error one pass later; three passes always suffice in practice
        bad = _bad_keys(_value_problems(manifest, props, data))
        if not (bad["props"] or bad["data"]):
            break
        for root, values in (("props", props), ("data", data)):
            for key in bad[root]:
                if key in values:
                    del values[key]
                    dropped[root].add(key)
    kept_controls: list[Any] = []
    lost_controls: list[str] = []
    for control in scene.controls:
        probe = replace(repinned, props=props, data=data, controls=(control,), anchors=())
        if check_scene(probe, manifest):
            lost_controls.append(control.control_id)
        else:
            kept_controls.append(control)
    kept_ids = {control.control_id for control in kept_controls}
    anchors, lost_anchors = [], []
    for anchor in scene.anchors:
        if anchor.control_id is not None and anchor.control_id not in kept_ids:
            anchors.append(replace(anchor, control_id=None))
            lost_anchors.append(anchor.anchor_id)
        else:
            anchors.append(anchor)
    candidate = replace(repinned, props=props, data=data, controls=tuple(kept_controls), anchors=tuple(anchors))
    left = scene_problems(candidate, manifest)
    if left:
        return CarryOver(None, None, tuple(left))
    reset = StateReset(tuple(sorted(dropped["props"])), tuple(sorted(dropped["data"])), tuple(lost_controls),
                       tuple(lost_anchors))
    return CarryOver(candidate, None if reset.empty else reset)


def carry_live_values(manifest: PrefabManifest, scene: StudioScene, live_props: Mapping[str, Any],
                      live_data: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], StateReset | None]:
    """Les valeurs **vivantes** du bloc de la fenetre stage (celles que les evenements d'etat du cadre ont committees)
    sous le nouveau manifeste : conservees si valides, sinon retour aux valeurs de la scene (`runtime=True`)."""

    if not _value_problems(manifest, live_props, live_data):
        return dict(live_props), dict(live_data), None
    return dict(scene.props), dict(scene.data), StateReset(runtime=True)


# ------------------------------------------------------------------ montage rapporte par l'hote

class MountOutcome(StrEnum):
    MOUNTED = "mounted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MountReport:
    """Ce que l'hote a **observe** pour un cadre : monte (pret, stable) ou en echec (raison courte, message du cadre borne)."""

    object_id: str
    prefab: PrefabRef
    outcome: MountOutcome
    reason: str = ""
    message: str = ""


def _plain_keys(raw: object, where: str, required: set[str], optional: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Objet exact **sans** le refus des noms d'etat d'execution : un rapport de montage parle justement d'un
    `object_id` (un handle d'execution), qui n'entre jamais dans un document mais circule ici."""

    if not isinstance(raw, dict):
        raise _fail(f"{where} must be a JSON object")
    unknown, missing = set(raw) - required - optional, required - set(raw)
    if unknown:
        raise _fail(f"{where}: unknown keys {', '.join(sorted(map(str, unknown))[:6])}")
    if missing:
        raise _fail(f"{where}: missing keys {', '.join(sorted(missing)[:6])}")
    return raw


def parse_mount_report(raw: object) -> MountReport:
    data = _plain_keys(raw, "mount report", {"object_id", "prefab", "outcome"}, frozenset({"reason", "message"}))
    object_id = data["object_id"]
    if not isinstance(object_id, str) or not 0 < len(object_id) <= 128 or not object_id.isprintable():
        raise _fail("object_id must be a printable id of at most 128 characters")
    prefab = _plain_keys(data["prefab"], "prefab", {"id", "version"})
    try:
        ref = PrefabRef(prefab["id"], prefab["version"])
    except Exception:  # noqa: BLE001 - re-raised as the coded refusal below, naming the field
        raise _fail("prefab must name a valid {id, version}") from None
    try:
        outcome = MountOutcome(data["outcome"])
    except ValueError:
        raise _fail("outcome must be 'mounted' or 'failed'") from None
    reason = data.get("reason", "")
    if not isinstance(reason, str) or (reason and not REASON.fullmatch(reason)):
        raise _fail("reason must be a short code ([a-z][a-z0-9_]{0,39})")
    message = data.get("message", "")
    if not isinstance(message, str):
        raise _fail("message must be a string")
    # The frame's own words are untrusted text: one clipped printable line, kept for the Human, never evented.
    message = clip(re.sub(r"[\x00-\x1f\x7f]+", " ", message).strip(), MAX_MOUNT_MESSAGE)
    if outcome is MountOutcome.MOUNTED and (reason or message):
        raise _fail("a mounted report carries no reason or message")
    return MountReport(object_id, ref, outcome, reason, message)


# ------------------------------------------------------------------ resultat

@dataclass(frozen=True, slots=True)
class ReloadResult:
    status: ReloadStatus
    actor: StudioActor
    presentation_id: str
    variant_id: str
    scene_id: str
    basis_revision: int
    #: Revision de la variante apres l'operation (inchangee si rien n'a ete ecrit).
    revision: int
    #: Compteur monotone de la scene apres l'operation.
    source_revision: int
    #: Le pin **en vigueur** apres l'operation (le nouveau, ou le dernier valide apres un retour arriere).
    prefab: PrefabRef | None
    #: Le pin d'avant l'operation.
    previous: PrefabRef | None
    #: Le candidat publie (meme quand il a ete ecarte par un retour arriere) : `None` si rien n'a ete publie.
    published: PrefabRef | None = None
    code: str = ""
    message: str = ""
    #: Cause courte rapportee par l'hote ou par une etape (`frame`, `bundle`, `stage_changed`...) ; jamais un message.
    reason: str = ""
    reset: StateReset | None = None
    #: Plusieurs retouches d'une meme rafale ont donne UNE publication : ce resultat est celui de cette publication.
    merged: bool = False
    #: `True` monte confirme, `False` echec rapporte, `None` pas de fenetre / pas de rapport.
    mounted: bool | None = None
    request_id: str | None = None
    #: Ce qui n'a pas bouge : variante, scene, position de partition rapportee par la lecture (`None` : pas de lecture).
    preserved: Mapping[str, Any] = field(default_factory=dict)
    #: Attente du rapport de montage, en secondes (pour la barre visible et les journaux).
    waited_s: float | None = None

    @property
    def http_status(self) -> int:
        return HTTP_STATUS[self.status]

    def to_dict(self) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "status": self.status.value, "actor": self.actor.value, "presentation_id": self.presentation_id,
            "variant_id": self.variant_id, "scene_id": self.scene_id, "basis": {"variant_revision": self.basis_revision},
            "revision": self.revision, "source_revision": self.source_revision,
            "prefab": None if self.prefab is None else self.prefab.to_dict(),
            "previous": None if self.previous is None else self.previous.to_dict(),
            "published": None if self.published is None else self.published.to_dict(),
            "merged": self.merged, "mounted": self.mounted, "reset": None if self.reset is None else self.reset.to_dict(),
            "preserved": dict(self.preserved), "request_id": self.request_id, "waited_s": self.waited_s,
        }
        if self.code:
            wire["code"] = self.code
        if self.message:
            wire["message"] = self.message
        if self.reason:
            wire["reason"] = self.reason
        if self.status not in (ReloadStatus.RELOADED, ReloadStatus.RELOADED_STATE_RESET, ReloadStatus.REPINNED):
            wire["error"] = {"code": self.code or self.status.value, "message": self.message or self.status.value}
        return wire


def variant_scene(variant: PresentationVariant, scene_id: str) -> StudioScene:
    scene = next((item for item in variant.scenes if item.scene_id == scene_id), None)
    if scene is None:
        raise PresentationStudioError(C.UNKNOWN_SCENE, f"{scene_id} is not a scene of this variant")
    return scene

