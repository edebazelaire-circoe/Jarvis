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
        if data is None:
            # Champ imbriqué facultatif absent (`delta` d'un lot) : pydantic sérialise
            # son défaut `None` avant que le parent ne le retire.
            return None
        return {key: value for key, value in data.items() if key in self.model_fields_set}


# ------------------------------------------------------------------ scène

SceneOutcome = Literal["applied", "duplicate"]


# Ordre des champs = ordre dans lequel les outils construisent leur dict : le CLI
# Claude rend au modèle le `structuredContent` (compact) plutôt que le bloc texte
# (mesure Slice 04, contrat §5.3), donc l'ordre sérialisé est ce que le modèle
# lit. Pas d'héritage de champs entre ces modèles : il mettrait `outcome` devant.
# Ensemble, ils réalisent le `SceneCommandResult` du contrat (§5.2) outil par outil ;
# les refus restent des erreurs d'outil (`isError`).


class SceneObjectResult(ToolResult):
    """`scene_create_object`, `scene_update_object`."""

    object_id: str
    #: `scene_update_object` : l'opération de domaine choisie (`patch_object`, `set_geometry`…).
    command: str = None  # type: ignore[assignment]
    outcome: SceneOutcome
    revision: int
    note: str = None  # type: ignore[assignment]
    scene_changed: str = None  # type: ignore[assignment]


class SceneRelationResult(ToolResult):
    """`scene_link`, `scene_unlink`."""

    relation_id: str
    outcome: SceneOutcome
    revision: int
    #: `scene_link` sur un lien déjà présent sans couche demandée : la couche gardée.
    layer: int = None  # type: ignore[assignment]
    note: str = None  # type: ignore[assignment]
    scene_changed: str = None  # type: ignore[assignment]


class SceneArtifactResult(ToolResult):
    """`scene_add_artifact` : artefact groupé et son lien `explains`, en une commande."""

    object_id: str
    target_id: str
    relation_id: str
    action: Literal["created", "updated"]
    category: str
    #: Nombre d'entrées de l'artefact après écriture.
    items: int
    outcome: SceneOutcome
    revision: int
    note: str = None  # type: ignore[assignment]
    scene_changed: str = None  # type: ignore[assignment]
    rule: str
    ignored: list[str] = None  # type: ignore[assignment]
    ignored_note: str = None  # type: ignore[assignment]
    grouping_note: str = None  # type: ignore[assignment]


class SceneBatchSkipped(ToolResult):
    id: str
    reason: str


class SceneOffset(ToolResult):
    dx: float
    dy: float


class SceneBatchDelta(ToolResult):
    """`scene_move` : écart demandé, écart effectif commun (borné par la zone sûre), et s'il a été borné."""

    requested: SceneOffset
    effective: SceneOffset
    clamped: bool


class SceneBatchResult(ToolResult):
    """Lot atomique sur une `SceneSelection` (contrat §5.2) : `scene_update_many`, `scene_move`, `scene_archive`, `scene_pin`.

    Tiré du `SceneBatchReport` du domaine (`batch` de la réponse de Core) :
    `*_count` exacts, listes d'ids bornées à `MAX_BULK_REPORTED_IDS` (20).
    `hidden_count` (toujours présent) : membres masqués avant la commande. Un
    refus n'est jamais un résultat : c'est une erreur d'outil.
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
    hidden_count: int
    cascade_ids: list[str] = None  # type: ignore[assignment]
    delta: SceneBatchDelta = None  # type: ignore[assignment]
    pinned: bool = None  # type: ignore[assignment]
    note: str = None  # type: ignore[assignment]
    scene_changed: str = None  # type: ignore[assignment]


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


# ------------------------------------------------------------------ Boards et Sessions (board-session, Slice 05)
#
# Vues du cerveau sur les réponses de `/api/boards*` / `/api/sessions*`
# (`console_boards.py`) : l'écran d'un Board, sans `scene_ref` ni
# `runtime_metadata` qui appartiennent au runtime. Ordre = ordre du dict construit.


class BoardSummary(ToolResult):
    """Une ligne de `board_list` : reconnaître un Board sans lire son contenu."""

    board_id: str
    title: str
    status: Literal["active", "archived"]
    #: Le Board actif de la Session : celui où la conversation et la voix sont.
    active: bool
    interaction_mode: str
    last_opened_at: str | None


class BoardListResult(ToolResult):
    """`board_list`."""

    active_board_id: str
    boards: list[BoardSummary]


class BoardResult(ToolResult):
    """`board_get`, `board_get_active`, `board_create`, `board_update`, `board_archive` : le Board relu par Core."""

    board_id: str
    title: str
    status: Literal["active", "archived"]
    active: bool
    interaction_mode: str
    last_opened_at: str | None
    context_summary: str
    task_refs: list[str]
    artifact_refs: list[str]
    project_refs: list[str]
    updated_at: str


class BoardSwitchResult(ToolResult):
    """`board_switch` : `scheduled` (dès la fin du tour), `applied` (hors tour) ou `unchanged` (déjà actif)."""

    status: Literal["applied", "scheduled", "unchanged"]
    board_id: str
    title: str
    #: `applied` seulement : le Board quitté.
    previous_board_id: str | None = None  # type: ignore[assignment]
    note: str


class SessionCurrentResult(ToolResult):
    """`session_current` : la Session ouverte et la conversation de son Board actif."""

    jarvis_session_id: str
    started_at: str
    active_board_id: str
    visited_board_ids: list[str]
    conversation_id: str


class SessionNewResult(ToolResult):
    """`session_new` : `scheduled` (dès la fin du tour) ou `applied` (hors tour)."""

    status: Literal["applied", "scheduled"]
    #: La Session fermée par cette demande (lue juste avant de la faire).
    closed_session_id: str
    board_id: str
    #: `applied` seulement : la Session ouverte.
    jarvis_session_id: str = None  # type: ignore[assignment]
    note: str


# ------------------------------------------------------------------ Bare Hands

class BarehandsCommandResult(ToolResult):
    """Ce que la page a **constaté** après la commande (jamais un faux succès)."""

    command: str
    outcome: SceneOutcome
    lifecycle: str | None
    note: str


# ------------------------------------------------------------------ calibration (Slice 06 adaptative)
#
# Ce que la page a **constaté**, recopié du reçu : le serveur du Control Center
# a déjà validé chaque ligne contre le schéma fermé de sa commande
# (`jarvis/domain/barehands_calibration.py`). Les noms des champs sont ceux du
# contrat de séance (§ 17 : `trialRef`, `evidenceRefs`…), en camelCase comme
# dans la page ; les **arguments** des outils restent en snake_case comme tous
# les outils de Jarvis. Les lignes imbriquées sont des objets ouverts ici parce
# qu'un seul schéma les tient déjà, celui du domaine — le recopier en pydantic
# ferait deux vérités.


class CalibrationStatusResult(ToolResult):
    """`calibration_status` : exercice, valeurs (effectives, enregistrées, essai), mesures, séance."""

    outcome: SceneOutcome
    note: str
    exercise: dict[str, Any]
    values: dict[str, Any]
    measurements: list[dict[str, Any]]
    measurementCount: int
    feedback: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    hypotheses: list[dict[str, Any]]
    trials: list[dict[str, Any]]
    reviews: list[dict[str, Any]]
    proposal: dict[str, Any] | None
    revision: int
    truncated: dict[str, Any]


class CalibrationFeedbackResult(ToolResult):
    """`calibration_record_feedback` : le retour rangé et les causes que sa catégorie suggère."""

    outcome: SceneOutcome
    note: str
    feedback: dict[str, Any]
    suggestedCauses: list[str]


class CalibrationHypothesisResult(ToolResult):
    """`calibration_propose_hypothesis` : l'hypothèse et ses preuves, **chiffrées par le code**."""

    outcome: SceneOutcome
    note: str
    hypothesis: dict[str, Any]
    evidence: list[dict[str, Any]]


class CalibrationProposalResult(ToolResult):
    """`calibration_prepare_trial` : la proposition affichée, **non appliquée**."""

    outcome: SceneOutcome
    note: str
    proposal: dict[str, Any]


class CalibrationCommitResult(ToolResult):
    """`calibration_commit_proposal` : la transaction (appliqué, relu, refait ou gardé et avancé)."""

    outcome: SceneOutcome
    note: str
    proposalRef: str
    action: str
    trialRef: str
    applied: dict[str, Any]
    verified: bool
    steps: list[str]
    exercise: dict[str, Any]
    decision: str
    attempt: int | None


class CalibrationResolveResult(ToolResult):
    """`calibration_resolve_trial` : deltas calculés et confiance mise à jour."""

    outcome: SceneOutcome
    note: str
    trialRef: str
    verdict: str
    basis: str
    deltas: list[dict[str, Any]]
    hypotheses: list[dict[str, Any]]


class CalibrationRollbackResult(ToolResult):
    """`calibration_rollback_trial` : l'essai défait et les valeurs d'avant, relues."""

    outcome: SceneOutcome
    note: str
    trialRef: str
    undone: list[str]
    restored: dict[str, Any]
    active: str | None


class CalibrationAcceptResult(ToolResult):
    """`calibration_accept_trial` : ce qui a été **rangé**, relu, et l'accord qui l'a permis."""

    outcome: SceneOutcome
    note: str
    trialRef: str
    accepted: dict[str, Any]
    applied: dict[str, Any]
    basis: str | None
    consent: dict[str, Any]


class CalibrationNextResult(ToolResult):
    """`calibration_next_exercise` : l'exercice à l'écran et **ce qui a été décidé** (validé ou passé)."""

    outcome: SceneOutcome
    note: str
    exercise: dict[str, Any]
    decision: str


class CalibrationExerciseResult(ToolResult):
    """`calibration_rerun_exercise`, `calibration_next_exercise` : l'exercice à l'écran après l'appel."""

    outcome: SceneOutcome
    note: str
    exercise: dict[str, Any]


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
