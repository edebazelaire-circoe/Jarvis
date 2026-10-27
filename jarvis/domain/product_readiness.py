"""Préparation du produit : la matrice « prêt / pas prêt » de l'édition installée (Slice 07).

Contrat : `docs/product-install.md` › *Readiness*. Handoff `tasks/jarvis-presentation-edition-v1/` (Slice 07).

Ce module est **pur** : il reçoit des faits déjà relevés (`ReadinessFacts`, rassemblés par
`jarvis/runtime/product_readiness.py`) et rend un rapport en mots de produit. Il ne lit rien, n'écrit
rien, ne lance rien. Les sondes et les actions nommées vivent dans le runtime ; le texte vit ici, pour
qu'il n'y ait qu'une source de ce que l'utilisateur lit.

Chaque ligne (`ReadinessItem`) dit :

- `state` : `ready` (Prêt), `action_needed` (À faire), `in_progress` (En cours), `optional` (facultatif, pas
  encore fait), `unavailable` (rien à faire ici pour l'instant : service à venir, Core arrêté…) ;
- `required` : une ligne requise pas `ready` rend le rapport « pas prêt » ;
- `summary` : une phrase pour l'utilisateur, sans jargon (ni « MCP », ni « npm », ni « CLI ») ;
- `detail` : le diagnostic exact (code, cause d'origine), montré sous « Détails », jamais réécrit ;
- `actions` : les actions NOMMÉES qu'il peut lancer (`ActionId`) : une réparation, une connexion, une page.

Le rapport n'est « prêt » que si chaque ligne requise l'est (`ready`). Il ne devine jamais : un fait non
relevé (Core injoignable, sonde en échec) rend la ligne `unavailable` avec sa cause, jamais `ready`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

SCHEMA = "jarvis.product-readiness"
SCHEMA_VERSION = 1

#: En dessous : l'installation d'un composant ou un rendu peut échouer faute de place (À faire).
DISK_LOW_BYTES = 2 * 1024 ** 3
#: En dessous : rien ne peut plus s'écrire proprement (bloquant).
DISK_CRITICAL_BYTES = 512 * 1024 ** 2


class ReadinessState(StrEnum):
    READY = "ready"
    ACTION_NEEDED = "action_needed"
    IN_PROGRESS = "in_progress"
    OPTIONAL = "optional"
    UNAVAILABLE = "unavailable"


STATE_LABELS: Mapping[ReadinessState, str] = {
    ReadinessState.READY: "Prêt",
    ReadinessState.ACTION_NEEDED: "À faire",
    ReadinessState.IN_PROGRESS: "En cours",
    ReadinessState.OPTIONAL: "Facultatif",
    ReadinessState.UNAVAILABLE: "Indisponible",
}


class ItemGroup(StrEnum):
    #: Ce sans quoi une présentation ne se crée ni ne se rend.
    ESSENTIALS = "essentials"
    #: Comptes et services reliés : tous facultatifs.
    SERVICES = "services"
    #: Le poste : son, disque, dossier d'export.
    COMPUTER = "computer"


GROUP_LABELS: Mapping[ItemGroup, str] = {
    ItemGroup.ESSENTIALS: "Indispensable",
    ItemGroup.SERVICES: "Comptes et services",
    ItemGroup.COMPUTER: "Ce poste",
}


class ActionId(StrEnum):
    """Actions nommées : la seule façon de changer quelque chose depuis la préparation."""

    RECHECK = "recheck"
    PREPARE_DATA = "prepare_data"
    VERIFY_INSTALLATION = "verify_installation"
    RENDER_INSTALL = "render_install"
    RENDER_REPAIR = "render_repair"
    RENDER_UPDATE = "render_update"
    RENDER_ENABLE = "render_enable"
    BRAIN_INSTALL_GUIDE = "brain_install_guide"
    BRAIN_SIGN_IN = "brain_sign_in"
    CONNECT_CIRCOE = "connect_circoe"
    OPEN_CONNECTIONS = "open_connections"


class ActionKind(StrEnum):
    #: Lancée par le serveur (réparation, connexion) ; son issue se relit dans le rapport.
    RUN = "run"
    #: Ouvre une adresse rendue par le serveur (page officielle, consentement d'un compte).
    OPEN = "open"
    #: Mène à une page du Control Center.
    NAVIGATE = "navigate"


ACTION_TEXT: Mapping[ActionId, tuple[str, ActionKind]] = {
    ActionId.RECHECK: ("Vérifier à nouveau", ActionKind.RUN),
    ActionId.PREPARE_DATA: ("Préparer le dossier", ActionKind.RUN),
    ActionId.VERIFY_INSTALLATION: ("Vérifier l'installation", ActionKind.RUN),
    ActionId.RENDER_INSTALL: ("Préparer", ActionKind.RUN),
    ActionId.RENDER_REPAIR: ("Réparer", ActionKind.RUN),
    ActionId.RENDER_UPDATE: ("Mettre à jour", ActionKind.RUN),
    ActionId.RENDER_ENABLE: ("Réactiver", ActionKind.RUN),
    ActionId.BRAIN_INSTALL_GUIDE: ("Ouvrir la page d'installation", ActionKind.OPEN),
    ActionId.BRAIN_SIGN_IN: ("Se connecter", ActionKind.RUN),
    ActionId.CONNECT_CIRCOE: ("Relier le compte CIRCOE", ActionKind.OPEN),
    ActionId.OPEN_CONNECTIONS: ("Ouvrir Connexions", ActionKind.NAVIGATE),
}


@dataclass(frozen=True, slots=True)
class ReadinessAction:
    action_id: ActionId
    primary: bool = True

    def to_payload(self) -> dict[str, Any]:
        label, kind = ACTION_TEXT[self.action_id]
        return {"action_id": self.action_id.value, "label": label, "kind": kind.value, "primary": self.primary}


@dataclass(frozen=True, slots=True)
class ReadinessItem:
    item_id: str
    group: ItemGroup
    label: str
    required: bool
    state: ReadinessState
    summary: str
    detail: str | None = None
    actions: tuple[ReadinessAction, ...] = ()

    @property
    def blocking(self) -> bool:
        return self.required and self.state is not ReadinessState.READY

    def to_payload(self) -> dict[str, Any]:
        return {"item_id": self.item_id, "group": self.group.value, "label": self.label, "required": self.required,
                "state": self.state.value, "state_label": STATE_LABELS[self.state], "summary": self.summary,
                "detail": self.detail, "actions": [action.to_payload() for action in self.actions]}


# ---------------------------------------------------------------------- faits relevés


@dataclass(frozen=True, slots=True)
class Probe:
    """Résultat d'une sonde : `value` si elle a répondu, sinon `error` (code + phrase d'origine)."""

    value: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class BrainFacts:
    """Ce que dit la CLI Claude Code (dépendance externe, HV-PACKAGE-02 : jamais redistribuée)."""

    found: bool
    version: str | None = None
    logged_in: bool | None = None
    auth_method: str | None = None
    error: str | None = None
    sign_in_running: bool = False


@dataclass(frozen=True, slots=True)
class ReadinessFacts:
    installed: bool
    #: `GET /v1/health` de Core, ou l'erreur du relais.
    core: Probe
    #: `GET /v1/boards/edition`.
    edition: Probe
    #: `GET /v1/edition/connectors`.
    connectors: Probe
    #: Vue publique de la capacité `remotion` (`GET /v1/local-capabilities/remotion`).
    render: Probe
    brain: BrainFacts
    #: Libellé du navigateur de rendu (`chrome 1xx`, `edge …`) ou `None` s'il manque.
    browser: Probe
    #: `{"inputs": n, "outputs": n}`.
    audio: Probe
    #: Octets libres sous la maison du produit.
    disk_free: Probe
    #: Sous-dossiers manquants de la maison du produit (`data`, `runtime`, `config`) ; vide = complet.
    layout_missing: tuple[str, ...] = ()
    #: `GET /v1/exports/root` › `root`.
    export_root: Probe = field(default_factory=Probe)
    #: Résultat de la dernière vérification complète de l'installation (`verify_installation`), s'il y en a une.
    integrity: Probe | None = None
    #: Actions nommées en cours (`ActionId` → secondes écoulées).
    running: Mapping[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------- assemblage


def _err(probe: Probe) -> str:
    return probe.error or "unknown"


def _core_item(facts: ReadinessFacts) -> ReadinessItem:
    label = "Moteur de JARVIS"
    if not facts.core.ok:
        return ReadinessItem("core", ItemGroup.ESSENTIALS, label, True, ReadinessState.UNAVAILABLE,
                             "Le moteur de JARVIS ne répond pas. Il redémarre en général seul ; sinon, quittez puis "
                             "relancez JARVIS.", _err(facts.core), (ReadinessAction(ActionId.RECHECK),))
    health = facts.core.value or {}
    if not health.get("ready"):
        return ReadinessItem("core", ItemGroup.ESSENTIALS, label, True, ReadinessState.IN_PROGRESS,
                             "Le moteur de JARVIS démarre.", str(health.get("detail") or health.get("status") or ""),
                             (ReadinessAction(ActionId.RECHECK),))
    return ReadinessItem("core", ItemGroup.ESSENTIALS, label, True, ReadinessState.READY,
                         "Le moteur de JARVIS fonctionne.", None)


def _data_item(facts: ReadinessFacts) -> ReadinessItem:
    label = "Dossier de JARVIS"
    if facts.layout_missing:
        missing = ", ".join(facts.layout_missing)
        return ReadinessItem("data", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                             "Le dossier où JARVIS range vos présentations n'est pas complet.",
                             f"layout_incomplete: {missing}", (ReadinessAction(ActionId.PREPARE_DATA),))
    installation = (facts.core.value or {}).get("installation") if facts.core.ok else None
    if facts.core.ok and isinstance(installation, Mapping):
        source = ((installation.get("data_root") or {}).get("source"))
        if facts.installed and source not in ("product_home", "override"):
            return ReadinessItem("data", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                                 "JARVIS n'utilise pas son dossier habituel.", f"data_root_source: {source}",
                                 (ReadinessAction(ActionId.RECHECK),))
    return ReadinessItem("data", ItemGroup.ESSENTIALS, label, True, ReadinessState.READY,
                         "Vos présentations et vos réglages sont rangés dans votre profil Windows.", None)


def _runtimes_item(facts: ReadinessFacts) -> ReadinessItem | None:
    if not facts.installed:
        return None
    label = "Composants de JARVIS"
    verify = (ReadinessAction(ActionId.VERIFY_INSTALLATION, primary=False),)
    if ActionId.VERIFY_INSTALLATION.value in facts.running:
        return ReadinessItem("runtimes", ItemGroup.ESSENTIALS, label, True, ReadinessState.IN_PROGRESS,
                             "Vérification des fichiers de JARVIS…", None)
    if facts.integrity is not None and not facts.integrity.ok:
        return ReadinessItem("runtimes", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                             "Des fichiers de JARVIS sont abîmés ou manquants. Relancez l'installation de JARVIS "
                             "pour les réparer : vos présentations sont conservées.", _err(facts.integrity), verify)
    block = ((facts.core.value or {}).get("installation") or {}).get("runtimes") if facts.core.ok else None
    status = block.get("status") if isinstance(block, Mapping) else None
    if status in ("degraded", "invalid"):
        problems = ", ".join(f"{p.get('component')}: {p.get('code')}" for p in block.get("problems") or []
                             if isinstance(p, Mapping))
        return ReadinessItem("runtimes", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                             "Des fichiers de JARVIS manquent. Relancez l'installation de JARVIS pour les remettre : "
                             "vos présentations sont conservées.", problems or status, verify)
    if not facts.core.ok:
        return ReadinessItem("runtimes", ItemGroup.ESSENTIALS, label, True, ReadinessState.UNAVAILABLE,
                             "Vérifiable quand le moteur de JARVIS répond.", _err(facts.core), verify)
    checked = " Fichiers vérifiés." if facts.integrity is not None else ""
    return ReadinessItem("runtimes", ItemGroup.ESSENTIALS, label, True, ReadinessState.READY,
                         f"Les composants livrés avec JARVIS sont en place.{checked}", None, verify)


def _brain_item(facts: ReadinessFacts) -> ReadinessItem:
    label = "Claude, le cerveau de JARVIS"
    brain = facts.brain
    if not brain.found:
        return ReadinessItem("brain", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                             "JARVIS réfléchit avec Claude Code, à installer une fois depuis le site d'Anthropic. "
                             "Revenez ici ensuite.", brain.error or "claude_cli_not_found",
                             (ReadinessAction(ActionId.BRAIN_INSTALL_GUIDE), ReadinessAction(ActionId.RECHECK, False)))
    if brain.sign_in_running:
        return ReadinessItem("brain", ItemGroup.ESSENTIALS, label, True, ReadinessState.IN_PROGRESS,
                             "Terminez la connexion dans la fenêtre de Claude qui vient de s'ouvrir.", None,
                             (ReadinessAction(ActionId.RECHECK, False),))
    if brain.logged_in is None:
        return ReadinessItem("brain", ItemGroup.ESSENTIALS, label, True, ReadinessState.UNAVAILABLE,
                             "Claude Code est installé, mais son état de connexion n'a pas pu être lu.",
                             brain.error or "claude_auth_status_unreadable",
                             (ReadinessAction(ActionId.RECHECK), ReadinessAction(ActionId.BRAIN_SIGN_IN, False)))
    if not brain.logged_in:
        return ReadinessItem("brain", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                             "Connectez Claude Code à votre compte Anthropic (abonnement Claude ou clé de la console).",
                             brain.error, (ReadinessAction(ActionId.BRAIN_SIGN_IN), ReadinessAction(ActionId.RECHECK, False)))
    how = {"claude.ai": "votre abonnement Claude", "console": "la console Anthropic"}.get(str(brain.auth_method or ""),
                                                                                      "votre compte Anthropic")
    version = f" (Claude Code {brain.version})" if brain.version else ""
    return ReadinessItem("brain", ItemGroup.ESSENTIALS, label, True, ReadinessState.READY,
                         f"Connecté avec {how}{version}.", None)


_RENDER_RUNNING = {ActionId.RENDER_INSTALL.value: "Préparation du moteur de rendu…",
                   ActionId.RENDER_REPAIR.value: "Réparation du moteur de rendu…",
                   ActionId.RENDER_UPDATE.value: "Mise à jour du moteur de rendu…"}


def _render_item(facts: ReadinessFacts) -> ReadinessItem:
    label = "Moteur de rendu des vidéos"
    for action_id, sentence in _RENDER_RUNNING.items():
        if action_id in facts.running:
            return ReadinessItem("render", ItemGroup.ESSENTIALS, label, True, ReadinessState.IN_PROGRESS,
                                 f"{sentence} Cela prend une à deux minutes et demande Internet.", None)
    if not facts.render.ok:
        return ReadinessItem("render", ItemGroup.ESSENTIALS, label, True, ReadinessState.UNAVAILABLE,
                             "État du moteur de rendu illisible pour l'instant.", _err(facts.render),
                             (ReadinessAction(ActionId.RECHECK),))
    view = facts.render.value or {}
    status = str(view.get("status") or "")
    cause = " ".join(str(part) for part in (view.get("last_error_code"), view.get("last_error_detail")) if part) or None
    missing = _render_runtime_problems(facts)
    if missing and status not in ("installing", "uninstalling", "starting", "stopping"):
        # QA runtime m2 : « Prêt » alors que le Node privé manquait. La capacité ne peut pas tourner sans lui, et
        # la réparer ne le remet pas : seule une réinstallation de JARVIS le fait.
        return ReadinessItem("render", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                             "Un composant du moteur de rendu manque. Relancez l'installation de JARVIS pour le "
                             "remettre : vos présentations sont conservées.", missing,
                             (ReadinessAction(ActionId.VERIFY_INSTALLATION, primary=False),))
    if status in ("ready", "running"):
        if view.get("update_required"):
            return ReadinessItem("render", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                                 "Le moteur de rendu doit être mis à jour pour cette version de JARVIS.", None,
                                 (ReadinessAction(ActionId.RENDER_UPDATE),))
        return ReadinessItem("render", ItemGroup.ESSENTIALS, label, True, ReadinessState.READY,
                             "Prêt à produire vos vidéos, images et PDF.", None)
    if status == "not_installed":
        return ReadinessItem("render", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                             "À préparer une fois (une à deux minutes, connexion Internet nécessaire).", None,
                             (ReadinessAction(ActionId.RENDER_INSTALL),))
    if status in ("installing", "uninstalling", "starting", "stopping"):
        # Aucun mot brut (« installing ») : la ligne dit ce qui se passe (QA runtime m1).
        return ReadinessItem("render", ItemGroup.ESSENTIALS, label, True, ReadinessState.IN_PROGRESS,
                             _RENDER_BUSY_SENTENCE.get(status, "Le moteur de rendu se prépare."), None,
                             (ReadinessAction(ActionId.RECHECK, False),))
    if status == "disabled":
        return ReadinessItem("render", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                             "Le moteur de rendu a été désactivé.", None, (ReadinessAction(ActionId.RENDER_ENABLE),))
    # install_failed, repair_needed, crashed, state_unreadable : une réparation réinstalle aux versions épinglées.
    return ReadinessItem("render", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                         _render_failure_sentence(view.get("last_error_code")), cause or status,
                         (ReadinessAction(ActionId.RENDER_REPAIR),))


_RENDER_BUSY_SENTENCE = {
    "installing": "Le moteur de rendu se prépare (une à deux minutes, connexion Internet nécessaire).",
    "uninstalling": "Le moteur de rendu est en cours de retrait.",
    "starting": "Le moteur de rendu démarre.",
    "stopping": "Le moteur de rendu s'arrête.",
}
#: Composants livrés dont le moteur de rendu dépend (`runtimes` de `/v1/health`, Slice 06).
_RENDER_COMPONENTS = frozenset({"node"})


def _render_runtime_problems(facts: ReadinessFacts) -> str | None:
    """`node: private_runtime_missing`… si un composant livré dont dépend le rendu manque (produit installé)."""

    if not facts.installed or not facts.core.ok:
        return None
    block = ((facts.core.value or {}).get("installation") or {}).get("runtimes")
    problems = block.get("problems") if isinstance(block, Mapping) else None
    found = [f"{p.get('component')}: {p.get('code')}" for p in problems or []
             if isinstance(p, Mapping) and p.get("component") in _RENDER_COMPONENTS]
    return ", ".join(found) or None


def _render_failure_sentence(code: object) -> str:
    code = str(code or "")
    if code.endswith("install_offline"):
        return "La préparation du moteur de rendu demande Internet : vérifiez la connexion puis réparez."
    if code.endswith("install_disk_full"):
        return "Pas assez de place sur le disque pour le moteur de rendu : libérez de l'espace puis réparez."
    if code.endswith("install_permission_denied"):
        return "Windows a refusé l'écriture du moteur de rendu (antivirus ou dossier protégé) : réessayez la réparation."
    if code.endswith("requirement_missing"):
        return "Un composant de JARVIS manquait quand le moteur de rendu a été préparé. Réparez-le maintenant."
    return "Le moteur de rendu ne fonctionne pas. Une réparation le remet en place sans toucher à vos présentations."


def _browser_item(facts: ReadinessFacts) -> ReadinessItem:
    label = "Navigateur pour le rendu"
    if not facts.browser.ok:
        return ReadinessItem("browser", ItemGroup.ESSENTIALS, label, True, ReadinessState.UNAVAILABLE,
                             "Le navigateur de rendu n'a pas pu être recherché.", _err(facts.browser),
                             (ReadinessAction(ActionId.RECHECK),))
    if not facts.browser.value:
        return ReadinessItem("browser", ItemGroup.ESSENTIALS, label, True, ReadinessState.ACTION_NEEDED,
                             "Les vidéos se fabriquent avec Microsoft Edge ou Google Chrome, introuvables sur ce poste. "
                             "Installez l'un des deux, puis vérifiez à nouveau.", "render_browser_missing",
                             (ReadinessAction(ActionId.RECHECK),))
    return ReadinessItem("browser", ItemGroup.ESSENTIALS, label, True, ReadinessState.READY,
                         f"Trouvé : {facts.browser.value}.", None)


def _connector_items(facts: ReadinessFacts) -> list[ReadinessItem]:
    if not facts.connectors.ok:
        return [ReadinessItem("connectors", ItemGroup.SERVICES, "Comptes et services", False,
                              ReadinessState.UNAVAILABLE, "Liste des services illisible pour l'instant.",
                              _err(facts.connectors), (ReadinessAction(ActionId.RECHECK),))]
    items: list[ReadinessItem] = []
    for row in (facts.connectors.value or {}).get("connectors") or []:
        if not isinstance(row, Mapping):
            continue
        connector_id = str(row.get("connector_id") or "")
        state = str(row.get("state") or "")
        summary = str(row.get("detail") or row.get("description") or "")
        actions: tuple[ReadinessAction, ...] = ()
        circoe = str(row.get("integration")) == "remote_plugin"
        if state == "ready":
            mapped = ReadinessState.READY
        elif state == "contract_pending":
            mapped = ReadinessState.UNAVAILABLE
        elif state == "unavailable":
            mapped, actions = ReadinessState.OPTIONAL, (ReadinessAction(ActionId.RECHECK),)
        else:
            mapped = ReadinessState.OPTIONAL
            if circoe and state in ("not_configured", "needs_authorization"):
                actions = (ReadinessAction(ActionId.CONNECT_CIRCOE),)
            elif state == "disabled":
                actions = (ReadinessAction(ActionId.OPEN_CONNECTIONS),)
        if connector_id == "google_drive" and state == "not_configured":
            summary = ("Facultatif. Relier Google Drive demande une configuration préparée par CIRCOE : "
                       "elle n'est pas encore proposée dans cette version.")
        items.append(ReadinessItem(f"connector:{connector_id}", ItemGroup.SERVICES,
                                   str(row.get("label") or connector_id), False, mapped,
                                   summary or str(row.get("state_label") or ""), state or None, actions))
    return items


def _audio_item(facts: ReadinessFacts) -> ReadinessItem:
    label = "Micro et haut-parleurs"
    if not facts.audio.ok:
        return ReadinessItem("audio", ItemGroup.COMPUTER, label, False, ReadinessState.OPTIONAL,
                             "Les périphériques audio n'ont pas pu être lus. La voix est facultative : le clavier suffit.",
                             _err(facts.audio), (ReadinessAction(ActionId.RECHECK),))
    counts = facts.audio.value or {}
    inputs, outputs = int(counts.get("inputs") or 0), int(counts.get("outputs") or 0)
    if inputs and outputs:
        return ReadinessItem("audio", ItemGroup.COMPUTER, label, False, ReadinessState.READY,
                             f"{inputs} micro(s) et {outputs} sortie(s) audio trouvés.", None)
    missing = "aucun micro" if not inputs else "aucune sortie audio"
    return ReadinessItem("audio", ItemGroup.COMPUTER, label, False, ReadinessState.OPTIONAL,
                         f"Facultatif : {missing} trouvé. Branchez-en un pour parler à JARVIS.", None,
                         (ReadinessAction(ActionId.RECHECK),))


def _disk_item(facts: ReadinessFacts) -> ReadinessItem:
    label = "Espace disque"
    if not facts.disk_free.ok:
        return ReadinessItem("disk", ItemGroup.COMPUTER, label, False, ReadinessState.OPTIONAL,
                             "L'espace libre n'a pas pu être lu.", _err(facts.disk_free))
    free = int(facts.disk_free.value or 0)
    gigabytes = f"{free / 1024 ** 3:.1f} Go libres".replace(".", ",")
    if free < DISK_CRITICAL_BYTES:
        return ReadinessItem("disk", ItemGroup.COMPUTER, label, True, ReadinessState.ACTION_NEEDED,
                             f"Le disque est presque plein ({gigabytes}) : libérez de la place, sinon JARVIS ne pourra "
                             "plus enregistrer.", "disk_critical", (ReadinessAction(ActionId.RECHECK),))
    if free < DISK_LOW_BYTES:
        return ReadinessItem("disk", ItemGroup.COMPUTER, label, False, ReadinessState.OPTIONAL,
                             f"Peu de place ({gigabytes}) : une vidéo longue pourrait ne pas tenir.", "disk_low",
                             (ReadinessAction(ActionId.RECHECK),))
    return ReadinessItem("disk", ItemGroup.COMPUTER, label, False, ReadinessState.READY, f"{gigabytes}.", None)


def _export_item(facts: ReadinessFacts) -> ReadinessItem:
    label = "Dossier d'export"
    if not facts.export_root.ok:
        return ReadinessItem("export", ItemGroup.COMPUTER, label, False, ReadinessState.UNAVAILABLE,
                             "Dossier d'export non vérifié pour l'instant.", _err(facts.export_root))
    root = facts.export_root.value or {}
    name = str(root.get("root") or r"Documents\Jarvis")
    if not root.get("available"):
        return ReadinessItem("export", ItemGroup.COMPUTER, label, False, ReadinessState.OPTIONAL,
                             f"Les exports ne peuvent pas aller dans {name} : {root.get('message') or 'dossier refusé'}.",
                             str(root.get("code") or "export_root_unavailable"))
    if root.get("exists"):
        return ReadinessItem("export", ItemGroup.COMPUTER, label, False, ReadinessState.READY,
                             f"Vos exports arrivent dans {name}.", None)
    return ReadinessItem("export", ItemGroup.COMPUTER, label, False, ReadinessState.READY,
                         f"{name} sera créé à votre premier export.", None)


def assemble(facts: ReadinessFacts) -> list[ReadinessItem]:
    """Les lignes du rapport, dans l'ordre de lecture (indispensable, comptes, poste)."""

    items: list[ReadinessItem] = [_core_item(facts), _data_item(facts)]
    runtimes = _runtimes_item(facts)
    if runtimes is not None:
        items.append(runtimes)
    items += [_brain_item(facts), _render_item(facts), _browser_item(facts)]
    items += _connector_items(facts)
    items += [_audio_item(facts), _disk_item(facts), _export_item(facts)]
    return items


def report_payload(facts: ReadinessFacts, *, checked_at: str, onboarding: Mapping[str, Any],
                   launcher: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Charge de `GET /api/product/readiness`."""

    items = assemble(facts)
    blocking = [item for item in items if item.blocking]
    edition = (facts.edition.value or {}).get("edition") if facts.edition.ok else None
    return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "checked_at": checked_at,
            "edition": edition, "installed": facts.installed,
            "ready": not blocking, "blocking_count": len(blocking),
            "blocking": [item.item_id for item in blocking],
            "groups": [{"group": group.value, "label": GROUP_LABELS[group]} for group in ItemGroup],
            "items": [item.to_payload() for item in items],
            "running": sorted(facts.running),
            "onboarding": dict(onboarding), "launcher": dict(launcher or {"managed": False})}


def items_by_id(items: Sequence[ReadinessItem]) -> dict[str, ReadinessItem]:
    return {item.item_id: item for item in items}
