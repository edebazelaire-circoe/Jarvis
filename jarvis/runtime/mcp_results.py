"""Résultats typés des outils MCP de Jarvis (contrat `docs/mcp/tool-contract.md` §5.2).

Chaque modèle est l'annotation de retour d'un outil : FastMCP en tire
l'`outputSchema` annoncé et valide le résultat avant d'en faire le
`structuredContent`. Les outils continuent de rendre un `dict` : le bloc texte
que lit le cerveau reste le JSON de ce dict, **inchangé octet pour octet**.

Règles communes (`ToolResult`) :

- `extra="forbid"` : un champ rendu mais non déclaré ici fait échouer l'appel.
  C'est voulu — le schéma annoncé est la vérité — et les tests de sortie réelle
  (`tests/unit/test_mcp_catalog.py`) parcourent chaque chemin de résultat ;
- un champ facultatif absent du résultat reste absent du `structuredContent`
  (sémantique `NotRequired`), jamais `null` inventé ; un `null` rendu reste `null` ;
- le schéma ne porte pas `"default": null` pour un facultatif : absent ≠ `null`.

Importe `pydantic` : chargé par `build_server` et par le catalogue, jamais au
chargement des modules serveurs.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_serializer


def _drop_null_defaults(schema: dict[str, Any]) -> None:
    for prop in schema.get("properties", {}).values():
        if "default" in prop and prop["default"] is None:
            del prop["default"]


class ToolResult(BaseModel):
    """Base : champs fermés, facultatifs absents gardés absents."""

    model_config = ConfigDict(extra="forbid", json_schema_extra=_drop_null_defaults)

    @model_serializer(mode="wrap")
    def _given_fields_only(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        return {key: value for key, value in data.items() if key in self.model_fields_set}


# ------------------------------------------------------------------ scène

SceneOutcome = Literal["applied", "duplicate"]


class SceneCommandResult(ToolResult):
    """Une commande Core acceptée (`applied` ou `duplicate`). Les refus sont des erreurs d'outil."""

    outcome: SceneOutcome
    revision: int
    #: `duplicate` : « rien n'a changé ».
    note: str = None  # type: ignore[assignment]
    #: La scène a bougé depuis la dernière lecture du cerveau : phrase à lire.
    scene_changed: str = None  # type: ignore[assignment]


class SceneObjectResult(SceneCommandResult):
    """`scene_create_object`, `scene_update_object`."""

    object_id: str
    #: `scene_update_object` : l'opération de domaine choisie (`patch_object`, `set_geometry`…).
    command: str = None  # type: ignore[assignment]


class SceneRelationResult(SceneCommandResult):
    """`scene_link`, `scene_unlink`."""

    relation_id: str
    #: `scene_link` sur un lien déjà présent sans couche demandée : la couche gardée.
    layer: int = None  # type: ignore[assignment]


class SceneArtifactResult(SceneCommandResult):
    """`scene_add_artifact` : artefact groupé et son lien `explains`, en une commande."""

    object_id: str
    target_id: str
    relation_id: str
    action: Literal["created", "updated"]
    category: str
    #: Nombre d'entrées de l'artefact après écriture.
    items: int
    rule: str
    ignored: list[str] = None  # type: ignore[assignment]
    ignored_note: str = None  # type: ignore[assignment]
    grouping_note: str = None  # type: ignore[assignment]


class SceneBatchSkipped(ToolResult):
    id: str
    reason: str


class SceneBatchDelta(ToolResult):
    requested: list[float]
    effective: list[float]
    clamped: bool


class SceneBatchResult(ToolResult):
    """Lot atomique sur une `SceneSelection` (contrat §5.2) — **défini ici, rempli par la Slice 05**.

    Aucun outil ne le rend encore : `scene_update_many`, `scene_archive` et
    `scene_pin` bouclent objet par objet jusqu'à leur migration. Listes d'ids
    bornées à `MAX_BULK_REPORTED_IDS` (20).
    """

    op: str
    outcome: SceneOutcome
    revision: int
    matched_count: int
    changed_count: int
    unchanged_count: int
    skipped_count: int
    matched_ids: list[str]
    changed_ids: list[str]
    unchanged_ids: list[str]
    skipped: list[SceneBatchSkipped]
    hidden_count: int = None  # type: ignore[assignment]
    cascade_ids: list[str] = None  # type: ignore[assignment]
    delta: SceneBatchDelta = None  # type: ignore[assignment]
    pinned: bool = None  # type: ignore[assignment]
    note: str = None  # type: ignore[assignment]
    scene_changed: str = None  # type: ignore[assignment]


class SceneCaptureText(ToolResult):
    """Bloc texte JSON de `scene_capture` (sortie `json_text+image`, schéma du catalogue seulement)."""

    path: str
    width: int
    height: int
    bytes: int
    duration_ms: int | float | None
    note: str


# ------------------------------------------------------------------ réglages

class SettingValue(ToolResult):
    label: str
    #: Valeur telle que le Control Center la projette (booléen, nombre, texte, liste…).
    value: Any
    type: str
    options: list[Any]
    readonly: bool
    help: str


class SettingsGetResult(ToolResult):
    settings: dict[str, SettingValue]


class SettingsSetResult(ToolResult):
    option_id: str
    label: str
    before: Any
    #: Relue après écriture : ce que le serveur a retenu.
    after: Any
    changed: bool
    restart_required: str | None


# ------------------------------------------------------------------ Bare Hands

class BarehandsCommandResult(ToolResult):
    """Ce que la page a **constaté** après la commande (jamais un faux succès)."""

    command: str
    outcome: SceneOutcome
    lifecycle: str | None
    note: str


# ------------------------------------------------------------------ violation du contrat de sortie

#: Phrase rendue au cerveau quand un résultat ne passe pas son propre schéma :
#: l'action a pu partir (la validation vient **après** l'appel), donc jamais
#: « rien n'a été envoyé ».
OUTPUT_CONTRACT_MESSAGE = ("Résultat non conforme au schéma annoncé ({fields}) : l'action a pu être appliquée "
                           "malgré tout ; relis l'état avant de réessayer.")


def output_contract_fields(exc: BaseException | None) -> list[str] | None:
    """Champs fautifs quand `exc` est l'échec de validation du **résultat** d'un outil, sinon `None`.

    FastMCP valide les arguments avec un modèle nommé `<outil>Arguments` et le
    résultat avec le modèle de retour : le titre de l'erreur les distingue.
    """

    from pydantic import ValidationError

    if not isinstance(exc, ValidationError) or exc.title.endswith("Arguments"):
        return None
    errors = exc.errors(include_url=False, include_input=False, include_context=False)
    return [".".join(str(part) for part in error.get("loc", ())) or "?" for error in errors][:16]
