"""Connecteurs de l'édition produit : manifeste, états produit, politique des outils externes.

Contrat : `docs/product-connectors.md` (jarvis-presentation-edition-v1, Slice 05). Le contrat
générique des plugins MCP distants reste `docs/mcp/plugins.md` ; ce module ne le redécide pas,
il dit **quels** connecteurs une édition propose, comment leur état se lit en mots de produit, et
ce qu'un outil externe peut faire selon son effet de bord.

Une seule source, comme `product_edition.py` : `connector_policy(edition)` est consommée par Core
(`McpPluginService` : refus à l'appel, catalogue filtré, cadrage des résultats), par la route de
statut `GET /v1/edition/connectors` (onboarding/santé, Slice 07) et par les serveurs MCP enfants
(`jarvis-drive` : cadrage). Aucune autre table de connecteurs ne doit exister.

- `full` (développement) : comportement d'avant cette Slice. Tout outil externe s'appelle, aucun
  cadrage ajouté, portées Google complètes.
- `presentation` : un outil externe en lecture s'appelle ; une écriture demande une confirmation
  que V1 n'a pas encore de canal pour recueillir, donc refusée (`mcp_tool_confirmation_required`) ;
  un outil destructeur (ou non annoté, défaut MCP) est refusé (`mcp_tool_side_effect_refused`).
  Le contenu rendu par un connecteur est cadré comme donnée non fiable. Portées Google minimales.

CIRCOE Mail et IGuard sont des **entrées externes non fournies** : leur contrat d'intégration est
un gabarit (`docs/connectors/circoe-mail.md`, `docs/connectors/iguard.md`). Ils figurent au
manifeste en `contract_pending`, sans endpoint, sans nom d'outil. Le point de branchement est
`ConnectorSpec.plugin_match` : quand le contrat réel arrive, il nomme l'origine et l'identité
serveur attendues, et l'état se lit alors du plugin MCP correspondant (`plugin_state`).

Pur : aucune E/S.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from jarvis.domain.product_edition import ProductEdition, ProductEditionPolicy


class ConnectorId(StrEnum):
    """Identifiants stables, jamais traduits."""

    GOOGLE_DRIVE = "google_drive"
    CALENDAR = "calendar"
    CIRCOE_MAIL = "circoe_mail"
    IGUARD = "iguard"
    DOCUMENT_SEARCH = "document_search"


class ConnectorRequirement(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class ConnectorIntegration(StrEnum):
    """Comment le connecteur est branché aujourd'hui."""

    #: Adaptateur natif de Core (Google Drive, Google Agenda).
    NATIVE = "native"
    #: Plugin MCP distant du runtime générique (`docs/mcp/plugins.md`).
    REMOTE_PLUGIN = "remote_plugin"
    #: Contrat d'intégration attendu : rien n'est branché, rien n'est inventé.
    CONTRACT_PENDING = "contract_pending"


class ConnectorState(StrEnum):
    """État produit d'un connecteur, lu par l'onboarding et la santé (Slice 07)."""

    READY = "ready"
    NOT_CONFIGURED = "not_configured"
    NEEDS_AUTHORIZATION = "needs_authorization"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    CONTRACT_PENDING = "contract_pending"


#: Libellé et action proposée de chaque état. Mots de produit : ni « MCP », ni « plugin », ni code.
STATE_TEXT: Mapping[ConnectorState, tuple[str, str]] = MappingProxyType({
    ConnectorState.READY: ("Prêt", "none"),
    ConnectorState.NOT_CONFIGURED: ("À configurer", "configure"),
    ConnectorState.NEEDS_AUTHORIZATION: ("Autorisation à renouveler", "authorize"),
    ConnectorState.UNAVAILABLE: ("Service injoignable", "retry"),
    ConnectorState.DISABLED: ("Désactivé", "enable"),
    ConnectorState.CONTRACT_PENDING: ("Bientôt disponible", "none"),
})


class ToolCategory(StrEnum):
    """Familles d'outils qu'un connecteur apporte (risque lisible sans connaître ses outils)."""

    DOCUMENTS_SEARCH = "documents.search"
    DOCUMENTS_READ = "documents.read"
    DOCUMENTS_EXPORT = "documents.export"
    CALENDAR_READ = "calendar.read"
    CALENDAR_WRITE = "calendar.write"
    MAIL_READ = "mail.read"
    MAIL_SEND = "mail.send"


class RemoteToolDisposition(StrEnum):
    """Ce que l'édition permet d'un outil externe, selon son `side_effect` (`docs/mcp/plugins.md` §5.1)."""

    ALLOW = "allow"
    #: Exige une confirmation de l'utilisateur. V1 n'a aucun canal pour la recueillir à l'appel : refus codé.
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PluginMatch:
    """Point de branchement d'un connecteur sur un plugin MCP distant : ce que son contrat réel fixe.

    `endpoint_origin` (`https://hôte[:port]`) et/ou `server_name` (champ `name` de l'identité
    serveur rendue à `initialize`). Aucun n'est renseigné tant que le contrat n'est pas fourni.
    """

    endpoint_origin: str | None = None
    server_name: str | None = None

    def matches(self, summary: Mapping[str, Any]) -> bool:
        if self.endpoint_origin is None and self.server_name is None:
            return False
        if self.endpoint_origin is not None and _origin(summary.get("endpoint")) != self.endpoint_origin:
            return False
        identity = summary.get("server_identity")
        name = identity.get("name") if isinstance(identity, Mapping) else None
        return self.server_name is None or name == self.server_name


def _origin(endpoint: object) -> str | None:
    if not isinstance(endpoint, str):
        return None
    parts = urlsplit(endpoint)
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.scheme and parts.netloc else None


@dataclass(frozen=True, slots=True)
class ConnectorSpec:
    connector_id: ConnectorId
    label: str
    description: str
    requirement: ConnectorRequirement
    integration: ConnectorIntegration
    categories: tuple[ToolCategory, ...]
    #: Page de contrat (gabarit pour un contrat attendu).
    contract_doc: str
    #: Connecteur dont l'état décide de celui-ci (la recherche documentaire lit le Drive).
    depends_on: ConnectorId | None = None
    plugin_match: PluginMatch | None = None
    #: Point à confirmer par l'Humain, affiché tel quel dans les diagnostics (jamais une décision).
    open_question: str | None = None


_DRIVE = ConnectorSpec(
    ConnectorId.GOOGLE_DRIVE, "Google Drive",
    "Source de documents à lire et destination d'export choisie. Les données de JARVIS n'y sont jamais rangées.",
    ConnectorRequirement.OPTIONAL, ConnectorIntegration.NATIVE,
    (ToolCategory.DOCUMENTS_SEARCH, ToolCategory.DOCUMENTS_READ, ToolCategory.DOCUMENTS_EXPORT),
    "docs/product-connectors.md#google-drive")
_CALENDAR = ConnectorSpec(
    ConnectorId.CALENDAR, "Agenda CIRCOE",
    "Rendez-vous du compte Google Agenda de CIRCOE ; toute suppression ou invitation est confirmée.",
    ConnectorRequirement.OPTIONAL, ConnectorIntegration.NATIVE,
    (ToolCategory.CALENDAR_READ, ToolCategory.CALENDAR_WRITE),
    "docs/product-connectors.md#agenda",
    open_question="Le compte CIRCOE est-il un compte Google Workspace ? (amendement E1)")
_MAIL = ConnectorSpec(
    ConnectorId.CIRCOE_MAIL, "Messagerie CIRCOE",
    "Lecture et envoi de courriels CIRCOE, quand le contrat d'intégration sera fourni.",
    ConnectorRequirement.OPTIONAL, ConnectorIntegration.CONTRACT_PENDING,
    (ToolCategory.MAIL_READ, ToolCategory.MAIL_SEND),
    "docs/connectors/circoe-mail.md", plugin_match=None,
    open_question="Fournisseur, protocole et authentification de la messagerie CIRCOE (amendement E1/X2)")
_IGUARD = ConnectorSpec(
    ConnectorId.IGUARD, "IGuard",
    "Service IGuard, quand son contrat d'intégration sera fourni.",
    ConnectorRequirement.OPTIONAL, ConnectorIntegration.CONTRACT_PENDING, (),
    "docs/connectors/iguard.md", plugin_match=None,
    open_question="Transport, adresse, authentification et inventaire d'outils d'IGuard (X1)")
_SEARCH = ConnectorSpec(
    ConnectorId.DOCUMENT_SEARCH, "Recherche documentaire",
    "Recherche et lecture dans les documents du Google Drive connecté.",
    ConnectorRequirement.OPTIONAL, ConnectorIntegration.NATIVE,
    (ToolCategory.DOCUMENTS_SEARCH, ToolCategory.DOCUMENTS_READ),
    "docs/product-connectors.md#recherche-documentaire", depends_on=ConnectorId.GOOGLE_DRIVE)

CONNECTOR_SPECS: tuple[ConnectorSpec, ...] = (_DRIVE, _SEARCH, _CALENDAR, _MAIL, _IGUARD)


class GoogleScopeProfile(StrEnum):
    #: Portées historiques (`drive`, `calendar`) : développement.
    FULL = "full"
    #: Portées minimales du produit (`drive.readonly` + `drive.file`, `calendar.events`).
    MINIMAL = "minimal"


@dataclass(frozen=True, slots=True)
class ConnectorPolicy:
    edition: ProductEdition
    connectors: tuple[ConnectorSpec, ...]
    remote_tools: Mapping[str, RemoteToolDisposition]
    frame_untrusted_content: bool
    google_scopes: GoogleScopeProfile
    #: Clés API et jetons OAuth locaux scellés (DPAPI) plutôt qu'en clair (amendement E3).
    seal_local_secrets: bool

    @property
    def restricts_remote_tools(self) -> bool:
        return any(value is not RemoteToolDisposition.ALLOW for value in self.remote_tools.values())

    def remote_tool_disposition(self, side_effect: object) -> RemoteToolDisposition:
        """`read` / `write` / `destructive` ; toute autre valeur est traitée comme `destructive` (défaut MCP)."""

        key = side_effect if isinstance(side_effect, str) and side_effect in self.remote_tools else "destructive"
        return self.remote_tools[key]

    def spec(self, connector_id: ConnectorId) -> ConnectorSpec:
        return next(spec for spec in self.connectors if spec.connector_id is ConnectorId(connector_id))


_ALLOW_ALL = MappingProxyType({"read": RemoteToolDisposition.ALLOW, "write": RemoteToolDisposition.ALLOW,
                               "destructive": RemoteToolDisposition.ALLOW})
_PRODUCT_TOOLS = MappingProxyType({"read": RemoteToolDisposition.ALLOW, "write": RemoteToolDisposition.CONFIRM,
                                   "destructive": RemoteToolDisposition.DENY})

CONNECTOR_POLICIES: Mapping[ProductEdition, ConnectorPolicy] = MappingProxyType({
    ProductEdition.FULL: ConnectorPolicy(ProductEdition.FULL, CONNECTOR_SPECS, _ALLOW_ALL,
                                         frame_untrusted_content=False, google_scopes=GoogleScopeProfile.FULL,
                                         seal_local_secrets=False),
    ProductEdition.PRESENTATION: ConnectorPolicy(ProductEdition.PRESENTATION, CONNECTOR_SPECS, _PRODUCT_TOOLS,
                                                 frame_untrusted_content=True,
                                                 google_scopes=GoogleScopeProfile.MINIMAL, seal_local_secrets=True),
})


def connector_policy(edition: ProductEditionPolicy | ProductEdition) -> ConnectorPolicy:
    key = edition.edition if isinstance(edition, ProductEditionPolicy) else ProductEdition(edition)
    return CONNECTOR_POLICIES[key]


# ------------------------------------------------------------------ états


@dataclass(frozen=True, slots=True)
class ConnectorFacts:
    """Ce que Core sait au moment de la lecture. Rien d'autre n'entre dans le calcul."""

    drive_available: bool = False
    calendar_persisted: bool = False
    #: Résumés des plugins MCP (`plugin_id`, `enabled`, `connection_status`, `auth_status`, `endpoint`,
    #: `server_identity`) : seuls les connecteurs à `plugin_match` les lisent.
    plugins: Sequence[Mapping[str, Any]] = ()


def plugin_state(summary: Mapping[str, Any]) -> ConnectorState:
    """État produit d'un plugin MCP (deux axes de `docs/mcp/plugins.md` §2 : `enabled`, connexion/autorisation)."""

    if not summary.get("enabled", False):
        return ConnectorState.DISABLED
    auth = summary.get("auth_status")
    if auth in ("required", "expired", "failed", "authorizing"):
        return ConnectorState.NEEDS_AUTHORIZATION
    status = summary.get("connection_status")
    if status == "connected":
        return ConnectorState.READY
    if status == "error":
        return ConnectorState.UNAVAILABLE
    return ConnectorState.NOT_CONFIGURED


def _native_state(connector_id: ConnectorId, facts: ConnectorFacts) -> tuple[ConnectorState, str | None]:
    if connector_id is ConnectorId.GOOGLE_DRIVE:
        return (ConnectorState.READY, None) if facts.drive_available else (
            ConnectorState.NOT_CONFIGURED, "Aucun compte Google Drive n'est relié à JARVIS.")
    if connector_id is ConnectorId.CALENDAR:
        return (ConnectorState.READY, None) if facts.calendar_persisted else (
            ConnectorState.NOT_CONFIGURED,
            "Aucun agenda réel n'est relié : les rendez-vous ne seraient gardés qu'en mémoire.")
    raise KeyError(connector_id)


def connector_status(spec: ConnectorSpec, facts: ConnectorFacts,
                     resolved: Mapping[ConnectorId, ConnectorState] | None = None) -> dict[str, Any]:
    detail: str | None = None
    if spec.integration is ConnectorIntegration.CONTRACT_PENDING and spec.plugin_match is None:
        state = ConnectorState.CONTRACT_PENDING
        detail = "Le contrat d'intégration de ce service n'a pas encore été fourni."
    elif spec.plugin_match is not None:
        matched = next((item for item in facts.plugins if spec.plugin_match.matches(item)), None)
        state = ConnectorState.NOT_CONFIGURED if matched is None else plugin_state(matched)
    elif spec.depends_on is not None:
        parent = (resolved or {}).get(spec.depends_on)
        state = parent if parent is not None else _native_state(spec.depends_on, facts)[0]
        if state is not ConnectorState.READY:
            detail = "Disponible dès que Google Drive est relié."
    else:
        state, detail = _native_state(spec.connector_id, facts)
    label, action = STATE_TEXT[state]
    return {"connector_id": spec.connector_id.value, "label": spec.label, "description": spec.description,
            "requirement": spec.requirement.value, "integration": spec.integration.value,
            "categories": [category.value for category in spec.categories],
            "state": state.value, "state_label": label, "action": action, "detail": detail,
            "contract_doc": spec.contract_doc, "open_question": spec.open_question}


def connectors_payload(policy: ConnectorPolicy, facts: ConnectorFacts) -> dict[str, Any]:
    """`GET /v1/edition/connectors` : manifeste + états + règles des outils externes. Jamais un secret."""

    resolved: dict[ConnectorId, ConnectorState] = {}
    items: list[dict[str, Any]] = []
    for spec in policy.connectors:
        status = connector_status(spec, facts, resolved)
        resolved[spec.connector_id] = ConnectorState(status["state"])
        items.append(status)
    return {"edition": policy.edition.value, "connectors": items,
            "external_tools": {key: value.value for key, value in policy.remote_tools.items()},
            "untrusted_content_framed": policy.frame_untrusted_content,
            "google_scopes": policy.google_scopes.value, "local_secrets_sealed": policy.seal_local_secrets}
