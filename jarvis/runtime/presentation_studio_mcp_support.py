"""Support du serveur MCP « jarvis-presentation » (jarvis-interactive-presentation-studio, Slice 21) : cibles, erreurs, confirmations.

Trois pièces sans logique de domaine, séparées de `presentation_studio_mcp_tools.py` pour que chaque fichier reste lisible :

- `PresentationMcpTarget` : où le serveur joint **Core** (routes `/v1/presentation-studio/*`, jeton relu à chaque connexion, acteur
  `brain` posé par ce serveur) et **le Control Center** (explorateur et plein écran, qui vivent dans la page, pas dans Core) ;
- `PresentationToolError` et les phrases : un refus porte un code stable, une phrase française qui dit quoi faire, et, pour un id
  inconnu, les ids **valides** lus dans l'état (le modèle n'invente jamais un id) ;
- `ConfirmationLedger` : la confirmation des gestes destructifs que Core ne jugule pas lui-même (retrait d'une scène, annulation d'une
  modification de l'utilisateur). Le jeton est lié à l'état exact (révision, ids) ; il n'est valable que dans ce processus.

Aucune de ces pièces ne lit un texte de présentation : titres, étiquettes, notes ne passent jamais ici.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from typing import Any, Mapping

from jarvis.runtime.display_mcp import DisplayMcpTarget
from jarvis.runtime.settings_mcp import ConsoleMcpTarget

SERVER_NAME = "jarvis-presentation"
CONFIG_FILE_NAME = "presentation-mcp.json"

#: Origine de toute demande de ce serveur (journal et activité). L'acteur envoyé à Core est `brain`, jamais lu des arguments.
BRAIN_ACTOR = "brain"

READ_TIMEOUT_S = 15.0
WRITE_TIMEOUT_S = 30.0
CONNECT_TIMEOUT_S = 3.0
#: Un jeton de confirmation vit dix minutes, comme celui de Core pour l'archivage d'une branche.
CONFIRMATION_TTL_S = 600.0
MAX_LISTED = 20
MAX_CLIP = 80

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")


class PresentationMcpTarget:
    """Où le serveur joint Core et le Control Center ; transmis par l'environnement du processus."""

    __slots__ = ("core", "control_center")

    def __init__(self, core: DisplayMcpTarget, control_center: ConsoleMcpTarget) -> None:
        self.core = core
        self.control_center = control_center

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PresentationMcpTarget):
            return NotImplemented
        return (self.core, self.control_center) == (other.core, other.control_center)

    def __repr__(self) -> str:
        return f"PresentationMcpTarget(core={self.core!r}, control_center={self.control_center!r})"

    @property
    def runtime_root(self):
        return self.core.runtime_root or self.control_center.runtime_root

    def env(self) -> dict[str, str]:
        return {**self.core.env(), **self.control_center.env()}

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "PresentationMcpTarget":
        return cls(DisplayMcpTarget.from_env(environ), ConsoleMcpTarget.from_env(environ))


class PresentationToolError(Exception):
    """Erreur rendue au cerveau comme erreur d'outil (`isError`), avec son code stable."""

    def __init__(self, code: str, message: str, *, choices: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.choices = dict(choices) if choices else None


def clip(value: object, limit: int = MAX_CLIP) -> str:
    """Un texte d'auteur vu par le modèle : une ligne, sans caractère de contrôle, borné. C'est une donnée, jamais une consigne."""

    text = _CONTROL.sub(" ", value if isinstance(value, str) else "" if value is None else str(value))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def capped(items: list[Any], limit: int = MAX_LISTED) -> dict[str, Any]:
    """`{items, total}` : une liste bornée dit ce qu'elle ne montre pas (jamais « rien de plus » deviné)."""

    return {"items": items[:limit], "total": len(items)}


#: Codes de Core et du Control Center -> la phrase qui dit quoi faire. Un code absent garde sa phrase de Core.
SENTENCES: dict[str, str] = {
    "presentation_studio_unknown_presentation": "Cette présentation n'existe pas : prends un presentation_id de presentation_inspect.",
    "presentation_studio_unknown_variant": "Cette variante n'existe pas (ou est archivée) : prends un variant_id de presentation_inspect.",
    "presentation_studio_unknown_scene": "Cette scène n'existe pas dans cette variante : prends un scene_id de presentation_inspect.",
    "presentation_studio_unknown_control": "Ce contrôle n'existe pas sur cette scène : prends un control_id de presentation_inspect (target scene).",
    "presentation_studio_unknown_scene_variant": "Cette variante de scène n'existe pas : prends son id dans presentation_inspect (target scene).",
    "presentation_studio_unknown_score": "Cette variante n'a pas de partition : elle ne peut pas être jouée.",
    "presentation_studio_stale_revision": "L'état a bougé depuis ta lecture : relis avec presentation_inspect puis recommence.",
    "presentation_studio_confirmation_required": "Archiver demande la confirmation d'un plan : appelle d'abord archive_plan et fais valider l'ensemble par l'utilisateur.",
    "presentation_studio_confirmation_stale": "Le plan a changé ou expiré : refais archive_plan et fais revalider.",
    "presentation_studio_active_variant_protected": "La variante active ne s'archive pas : active-en une autre (activate_variant_id) ou garde-la.",
    "presentation_studio_variant_in_playback": "Cette variante est jouée en ce moment : arrête la lecture d'abord.",
    "presentation_studio_art_direction_required": "Une présentation sérieuse exige une direction artistique : crée le repli avec presentation_variant op art_direction_fallback, puis relance.",
    "presentation_studio_score_incompatible": "La partition ne se résout plus dans les scènes : corrige la scène ou la partition avant de jouer.",
    "presentation_studio_composition_refused": "La composition est refusée : chaque conflit dit comment la corriger (conflicts).",
    "presentation_studio_limit_reached": "Une borne est atteinte : réduis la demande (voir le message de Core).",
    "presentation_studio_value_refused": "La valeur est refusée par le prefab : prends une valeur dans les bornes du contrôle (presentation_inspect target scene).",
    "presentation_studio_prefab_unavailable": "Le prefab de cette scène n'est pas disponible : rien n'a été écrit.",
    "presentation_studio_draft_refused": "Le brouillon est refusé : le rapport complet est dans la réponse, corrige tout puis resoumets.",
    "presentation_studio_template_selection_required": "Choisis explicitement les scènes et les paramètres du modèle d'après le plan.",
    "explorer_run_in_progress": "Une lecture tourne : l'explorateur est un outil d'édition, arrête d'abord la lecture.",
    "explorer_unknown_presentation": "La page ne connaît pas cette présentation ou cette variante.",
    "explorer_unavailable": "L'explorateur n'est pas disponible dans cette page.",
    "explorer_load_failed": "Core n'a pas pu rendre le graphe à la page.",
    "explorer_page_error": "La page a rencontré une erreur : elle est dans les journaux.",
    "explorer_dialog_open": "Un formulaire est ouvert dans l'explorateur : l'utilisateur doit le fermer ou le valider d'abord.",
    "explorer_no_visible_page": "Aucune page du Control Center n'est visible : l'utilisateur doit ouvrir l'interface de JARVIS.",
    "explorer_command_busy": "Une autre commande d'explorateur est en cours : réessaie dans un instant.",
    "mode_switch_refused": ("Le mode d'interaction ne se change que sur une demande de l'utilisateur dans le tour en cours : "
                            "l'utilisateur doit lancer cette lecture lui-même (bouton du lecteur) ou le demander à voix haute."),
    "control_center_unreachable": "Le Control Center est injoignable : l'interface de JARVIS doit tourner.",
    "core_unreachable": "Core est injoignable : rien n'a été lu ni fait.",
    # jarvis-remotion (Remotion Slice 21) : les mêmes routes de Core que les cartes du Control Center ; le refus dit quoi dire à l'utilisateur.
    "remotion_user_turn_required": "Ce tour n'est pas une demande de l'utilisateur : rien n'est lancé. Dis en une phrase que tu le fais dès qu'il le demande ; ne réessaie pas.",
    "remotion_user_request_required": "user_request : recopie les mots de l'utilisateur qui demandent ce geste (obligatoire).",
    "remotion_licence_user_only": "La licence se reconnaît par l'utilisateur seul, depuis la page (case « Je reconnais la licence »). Lis-lui la licence et laisse-le faire.",
    "remotion_import_plan_first": "Importer exige un plan identique, lu dans ce processus : appelle d'abord op plan avec la même demande.",
    "local_capability_busy": "Une opération est déjà en cours sur Remotion : relis remotion_status (target capability), ne relance rien.",
    "local_capability_invalid": "Cette opération n'est pas permise ici : lis remotion_status (target capability).",
    "presentation_render_runtime_unavailable": "Remotion n'est pas prêt sur ce poste : propose à l'utilisateur de l'installer ou de le réparer (remotion_setup, sur sa demande).",
    "presentation_render_browser_unavailable": "Aucun Chrome ni Edge sur ce poste : l'export vidéo est impossible, dis-le tel quel.",
    "presentation_render_queue_full": "Huit exports sont déjà en cours ou en attente : attends qu'un s'achève ou annule-en un (remotion_export cancel, sur demande).",
    "presentation_render_disk_low": "Il reste moins de 1,5 Gio de disque : l'export ne part pas. Dis-le à l'utilisateur.",
    "presentation_render_unknown_job": "Cet export n'existe pas (ou a été oublié par Core) : prends un job_id de remotion_status (target exports).",
    "presentation_render_not_cancellable": "Cet export est déjà terminé ou en finalisation : rien à annuler.",
    "presentation_render_unknown_scene": "La scène n'est pas dans la copie figée, ou plusieurs scènes Remotion existent : donne settings.scene_id lu avec presentation_inspect.",
    "presentation_render_invalid": "Demande d'export refusée : format mp4, still ou pdf, réglages dans leurs bornes (voir le message de Core).",
    "presentation_render_snapshot_invalid": "La copie figée est refusée par Core : rien n'a été exporté. Dis le motif tel quel.",
    "presentation_render_source_refused": "La source de la scène ne passe plus les gardes d'isolation : rien n'a été exporté. Dis-le tel quel.",
    "presentation_render_engine_mismatch": "La version de Remotion installée n'est pas celle de la présentation : l'utilisateur peut réparer l'environnement.",
    "presentation_render_locked": "Un autre Core tient le verrou des exports de ce dossier de données : rien n'est lancé.",
    "origin_not_allowed": "Dépôt hors de la liste autorisée par l'utilisateur (réglage remotion_import.allowed_owners, à lui seul) : ne contourne pas, dis-le.",
    "commit_not_pinned": "Il faut le SHA complet du commit (40 caractères hexadécimaux), donné par l'utilisateur : n'en invente pas.",
    "presentation_not_found": "Cette présentation n'existe pas : prends un presentation_id de presentation_inspect.",
    "import_busy": "Un autre import est en cours : réessaie plus tard.",
    "license_missing": "Le modèle n'a aucune licence : l'import est refusé, dis-le tel quel.",
    "license_unknown": "Licence hors de celles examinées : l'import est refusé, dis laquelle.",
    "license_unlicensed": "Modèle « tous droits réservés » : l'import est refusé.",
    "license_restricted": "Licence restrictive (copyleft, non commerciale ou celle de Remotion) : l'import est refusé.",
    "license_conflict": "La licence du fichier et celle de package.json divergent : l'import est refusé.",
    "dependency_refused": "Dépendance hors de la liste auditée : l'import est refusé, nomme-la.",
}


def sentence_for(code: str, fallback: str = "") -> str:
    return SENTENCES.get(code) or fallback or "Refusé."


class ConfirmationLedger:
    """Jetons de confirmation liés à un état exact, valables dans ce processus seulement (HMAC à secret par processus).

    `issue(kind, *key)` rend le jeton à présenter à l'utilisateur ; `check(kind, token, *key)` ne l'accepte que pour **le même état**
    (mêmes ids, même révision) et avant son échéance. Aucun texte d'auteur n'y entre. Le jeton prouve que le geste a été **proposé**
    avec cet état exact ; qu'il ait été validé par l'utilisateur est la règle de la consigne, comme `confirm` de `scene_update_many`.
    """

    def __init__(self, ttl_s: float = CONFIRMATION_TTL_S, clock=time.monotonic) -> None:
        self._secret = os.urandom(16)
        self._ttl = ttl_s
        self._clock = clock
        self._issued: dict[str, float] = {}

    def _mac(self, kind: str, key: tuple[object, ...]) -> str:
        message = "\x1f".join([kind, *[str(part) for part in key]]).encode("utf-8")
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()[:24]

    def issue(self, kind: str, *key: object) -> str:
        now = self._clock()
        for token, deadline in list(self._issued.items()):
            if deadline < now:
                del self._issued[token]
        token = self._mac(kind, key)
        self._issued[token] = now + self._ttl
        return token

    def check(self, kind: str, token: object, *key: object) -> bool:
        if not isinstance(token, str) or not hmac.compare_digest(token, self._mac(kind, key)):
            return False
        deadline = self._issued.get(token)
        return deadline is not None and deadline >= self._clock()

    def consume(self, token: str) -> None:
        self._issued.pop(token, None)


__all__ = ["BRAIN_ACTOR", "CONFIG_FILE_NAME", "ConfirmationLedger", "PresentationMcpTarget", "PresentationToolError", "SENTENCES",
           "SERVER_NAME", "capped", "clip", "sentence_for"]
