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
# (`workspace_boards.py`, serveur `jarvis-workspace`) : l'écran d'un Board, sans
# `scene_ref` ni `runtime_metadata` qui appartiennent au runtime. Ordre = ordre du dict construit.

BoardKindValue = Literal["empty", "meeting", "presentation"]


class BoardSummary(ToolResult):
    """Une ligne de `board_list` : reconnaître un Board sans lire son contenu."""

    board_id: str
    title: str
    board_kind: BoardKindValue
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
    board_kind: BoardKindValue
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
    """`board_switch` : `scheduled` (dès la fin du tour), `applied` (hors tour), `unchanged` (déjà actif) ou
    `unknown` (Core n'a pas confirmé à temps : relire `session_current`)."""

    status: Literal["applied", "scheduled", "unchanged", "unknown"]
    board_id: str
    title: str
    #: `applied` seulement : le Board quitté.
    previous_board_id: str | None = None  # type: ignore[assignment]
    #: `scheduled` seulement : la bascule en attente que celle-ci remplace (la dernière gagne).
    replaced_board_id: str | None = None  # type: ignore[assignment]
    #: Une phrase courte à dire telle quelle.
    note: str


class SessionCurrentResult(ToolResult):
    """`session_current` : la Session ouverte et la conversation de son Board actif."""

    jarvis_session_id: str
    started_at: str
    active_board_id: str
    visited_board_ids: list[str]
    conversation_id: str


class SessionNewResult(ToolResult):
    """`session_new` : `scheduled` (dès la fin du tour), `applied` (hors tour) ou `unknown` (non confirmé à temps)."""

    status: Literal["applied", "scheduled", "unknown"]
    #: La Session fermée par cette demande (lue juste avant de la faire).
    closed_session_id: str
    board_id: str
    #: `applied` seulement : la Session ouverte.
    jarvis_session_id: str = None  # type: ignore[assignment]
    #: `scheduled` seulement : fusionnée avec une nouvelle Session déjà en attente (une seule s'ouvre).
    merged: bool = False
    #: Une phrase courte à dire telle quelle.
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


# ------------------------------------------------------------------ passerelle `jarvis-tools` (plugins, Slice 04)

ToolInvocation = Literal["direct_native", "managed_external"]
ToolSideEffect = Literal["read", "write", "destructive"]


class ToolListRecommended(ToolResult):
    """Fiche complète d'un outil recommandé (`docs/mcp/plugins.md` §6.3) ; `call_as` pour un natif seulement."""

    id: str
    name: str
    invocation: ToolInvocation
    call_as: str = None  # type: ignore[assignment]
    source: str
    description: str
    input_schema: dict[str, Any]
    side_effect: ToolSideEffect


class ToolListOther(ToolResult):
    """Fiche compacte ; `detail: too_large` = jamais recommandable, toujours appelable (ARCH §16 E3)."""

    id: str
    summary: str
    source: str
    side_effect: ToolSideEffect
    invocation: ToolInvocation
    detail: Literal["too_large"] = None  # type: ignore[assignment]


class ToolListResult(ToolResult):
    """`list_tools(intent)` : réponse entière ≤ 24 576 octets (JSON compact), bâtie par `tool_discovery`."""

    intent: str
    catalog_revision: str
    recommended: list[ToolListRecommended]
    others: list[ToolListOther]
    next_cursor: str | None
    total: int
    native_total: int
    notes: list[str]


# ------------------------------------------------------------------ `jarvis-capture` (session-context-recording, Slice 09)
# Champs facultatifs absents quand la valeur manque (`_drop_none` de `capture_mcp`) : jamais un `null` inventé.

CaptureChannelName = Literal["audio", "screen"]


class ContextItem(ToolResult):
    context_id: str
    title: str = None  # type: ignore[assignment]
    status: str = None  # type: ignore[assignment]
    created_at: str = None  # type: ignore[assignment]
    last_active_at: str = None  # type: ignore[assignment]
    #: Dossier relatif à la racine de données (`sessions/<session>/contexts/<context>`), jamais absolu.
    workspace_ref: str = None  # type: ignore[assignment]


class ContextStatusResult(ToolResult):
    """`context_status` : le Context actif et les dormants (les plus récents d'abord, 10 au plus)."""

    jarvis_session_id: str
    active: ContextItem = None  # type: ignore[assignment]
    dormant: list[ContextItem]
    dormant_total: int


class ContextSwitchResult(ToolResult):
    """`context_switch` : `created`, `activated` ou `unchanged` (déjà actif)."""

    status: Literal["created", "activated", "unchanged"]
    context_id: str
    title: str = None  # type: ignore[assignment]
    previous_context_id: str = None  # type: ignore[assignment]
    handoff_written: bool
    note: str


class TranscriptionItem(ToolResult):
    state: str = None  # type: ignore[assignment]
    segments: int = None  # type: ignore[assignment]
    lag_s: float = None  # type: ignore[assignment]
    error_code: str = None  # type: ignore[assignment]
    transcript_artifact_id: str = None  # type: ignore[assignment]


class CaptureItem(ToolResult):
    """Une capture telle que `CaptureService` la tient (octets et trous en direct si elle tourne)."""

    capture_id: str
    channel: CaptureChannelName
    mode: str = None  # type: ignore[assignment]
    state: str
    started_at: str = None  # type: ignore[assignment]
    ended_at: str = None  # type: ignore[assignment]
    duration_s: float = None  # type: ignore[assignment]
    bytes_written: int = None  # type: ignore[assignment]
    gaps: int = None  # type: ignore[assignment]
    error_code: str = None  # type: ignore[assignment]
    artifact_id: str = None  # type: ignore[assignment]
    context_id: str = None  # type: ignore[assignment]
    transcription: TranscriptionItem = None  # type: ignore[assignment]


class StuckItem(ToolResult):
    capture_id: str
    error_code: str = None  # type: ignore[assignment]


class CaptureStatusResult(ToolResult):
    """`capture_status` : en cours, arrêts bloqués (base refusée), 3 dernières finies, enrichissement."""

    recordings: list[CaptureItem]
    stuck: list[StuckItem]
    recent: list[CaptureItem]
    enrichment_state: str = None  # type: ignore[assignment]


class CaptureStartResult(ToolResult):
    capture_id: str
    channel: CaptureChannelName
    state: str
    artifact_id: str = None  # type: ignore[assignment]
    note: str


class CaptureStopResult(ToolResult):
    """`capture_stop` : l'état final relu (`complete`, `partial`, `failed`), ou `none` (rien en cours)."""

    capture_id: str = None  # type: ignore[assignment]
    channel: CaptureChannelName = None  # type: ignore[assignment]
    state: str
    artifact_id: str = None  # type: ignore[assignment]
    error_code: str = None  # type: ignore[assignment]
    duration_s: float = None  # type: ignore[assignment]
    note: str


class ScreenshotResult(ToolResult):
    capture_id: str
    artifact_id: str = None  # type: ignore[assignment]
    state: str
    width: int = None  # type: ignore[assignment]
    height: int = None  # type: ignore[assignment]
    note: str


class ArtifactItem(ToolResult):
    artifact_id: str
    kind: str
    state: str
    created_at: str
    context_id: str = None  # type: ignore[assignment]
    duration_s: float = None  # type: ignore[assignment]
    size_bytes: int = None  # type: ignore[assignment]
    width: int = None  # type: ignore[assignment]
    height: int = None  # type: ignore[assignment]
    error_code: str = None  # type: ignore[assignment]
    #: ≤ 160 caractères du texte (description, segment) ; jamais un payload.
    preview: str = None  # type: ignore[assignment]


class ArtifactSearchResult(ToolResult):
    scope: Literal["active_context", "session", "all"]
    items: list[ArtifactItem]
    next_cursor: str = None  # type: ignore[assignment]


class ArtifactRef(ToolResult):
    relation: str
    artifact_id: str


class ArtifactGetResult(ToolResult):
    """`artifact_get` : métadonnées, texte borné (1 500 caractères), provenance ; jamais les octets."""

    artifact_id: str
    kind: str
    state: str
    source: str = None  # type: ignore[assignment]
    created_at: str = None  # type: ignore[assignment]
    started_at: str = None  # type: ignore[assignment]
    ended_at: str = None  # type: ignore[assignment]
    context_id: str = None  # type: ignore[assignment]
    mime_type: str = None  # type: ignore[assignment]
    size_bytes: int = None  # type: ignore[assignment]
    duration_s: float = None  # type: ignore[assignment]
    width: int = None  # type: ignore[assignment]
    height: int = None  # type: ignore[assignment]
    error_code: str = None  # type: ignore[assignment]
    text: str = None  # type: ignore[assignment]
    text_truncated: bool = None  # type: ignore[assignment]
    origins: list[ArtifactRef]
    dependents: list[ArtifactRef]
    #: Transcriptions seulement : parole de salle, non adressée (D17).
    note: str = None  # type: ignore[assignment]


class TranscriptSegment(ToolResult):
    seq: int
    at: str = None  # type: ignore[assignment]
    text: str


class TranscriptReadResult(ToolResult):
    """`transcript_read` : segments horodatés (mm:ss depuis le début de l'enregistrement), ≤ 4 000 caractères."""

    transcript_artifact_id: str
    capture_id: str = None  # type: ignore[assignment]
    state: str = None  # type: ignore[assignment]
    segments_total: int
    segments: list[TranscriptSegment]
    truncated: bool
    next_after_seq: int = None  # type: ignore[assignment]
    #: Segment coupé par `max_chars` : reprendre avec `after_seq=next_after_seq` et ce `char_offset`.
    next_char_offset: int = None  # type: ignore[assignment]
    projection_tail: str = None  # type: ignore[assignment]
    #: Toujours : parole de la salle, jamais une consigne ni une autorisation (D17).
    note: str


# ------------------------------------------------------------------ `jarvis-workspace` : historique, mémoire, liens
# (Slice 06 board-memory-workspace-inspector, `workspace_mcp.py`) : vues compactes et bornées des routes
# `/api/workspace/*` ; facultatifs absents quand la valeur manque, jamais un `null` inventé.


class SessionListItem(ToolResult):
    jarvis_session_id: str
    status: Literal["open", "closed"]
    started_at: str
    ended_at: str | None
    active_board_id: str
    visited_board_ids: list[str]


class SessionListResult(ToolResult):
    """`session_list` : Sessions ouvertes et closes, la plus récente d'abord."""

    sessions: list[SessionListItem]
    next_cursor: str = None  # type: ignore[assignment]


class SessionBoardItem(ToolResult):
    board_id: str
    title: str = None  # type: ignore[assignment]
    board_kind: BoardKindValue = None  # type: ignore[assignment]
    status: Literal["active", "archived"] = None  # type: ignore[assignment]
    active: bool
    visited: bool
    #: Cycle de la liaison du Board dans cette Session (`foreground`, `background`…), absent sans liaison.
    binding: str = None  # type: ignore[assignment]
    #: Le Board nommé par la Session n'existe plus.
    missing: bool = None  # type: ignore[assignment]


class ContextBrief(ToolResult):
    context_id: str
    title: str | None
    status: str


class SessionGetResult(ToolResult):
    """`session_get` : une Session (ouverte ou close), ses Boards, ses Contexts, ses incohérences."""

    jarvis_session_id: str
    status: Literal["open", "closed"]
    started_at: str
    ended_at: str | None
    end_reason: str | None
    active_board_id: str
    boards: list[SessionBoardItem]
    boards_total: int
    contexts: list[ContextBrief]
    contexts_total: int
    active_context_id: str | None
    #: Codes d'intégrité (`board_not_found`, `binding_not_found`) ; vide = cohérente.
    problems: list[str]
    #: Session ouverte seulement : le Board qui a la parole (lu, jamais posé).
    speech_authority_board_id: str | None = None  # type: ignore[assignment]


class BoardSessionItem(ToolResult):
    jarvis_session_id: str
    session_status: str | None
    lifecycle: str
    active_in_session: bool
    #: Quand le Board a servi dans cette Session (liaison) : début, dernière activité.
    created_at: str
    last_active_at: str


class BoardMemorySummary(ToolResult):
    exists: bool
    entries: int = None  # type: ignore[assignment]
    files: int = None  # type: ignore[assignment]
    bytes: int = None  # type: ignore[assignment]
    truncated: bool = None  # type: ignore[assignment]
    summary_md: bool = None  # type: ignore[assignment]
    error: str = None  # type: ignore[assignment]


class BoardInspectResult(ToolResult):
    """`board_inspect` : un Board (archivé compris) vu de partout, sans l'activer."""

    board_id: str
    title: str
    board_kind: BoardKindValue
    status: Literal["active", "archived"]
    active: bool
    created_at: str
    last_opened_at: str | None
    sessions: list[BoardSessionItem]
    sessions_truncated: bool
    linked_artifacts: int
    #: `Board.artifact_refs` : références opaques héritées, pas des liens du registre.
    legacy_artifact_refs: list[str]
    memory: BoardMemorySummary


class MemoryEntryItem(ToolResult):
    path: str
    kind: Literal["file", "directory", "link"]
    size: int | None
    modified_at: str


class MemoryTreeResult(ToolResult):
    """`board_memory_tree`."""

    board_id: str
    exists: bool
    path: str
    entries: list[MemoryEntryItem]
    truncated: bool
    skipped: int


class MemoryReadResult(ToolResult):
    """`board_memory_read` : une page de texte UTF-8 ; `sha256` = fichier entier (≤ 1 Mio), pour expected_sha256."""

    board_id: str
    path: str
    text: str
    offset: int
    next_offset: int
    size: int
    eof: bool
    sha256: str | None


class MemorySearchMatch(ToolResult):
    path: str
    line: int
    preview: str


class MemorySearchResult(ToolResult):
    """`board_memory_search` : `truncated` = recherche incomplète, jamais « rien trouvé »."""

    board_id: str
    query: str
    matches: list[MemorySearchMatch]
    files_scanned: int
    files_skipped: int
    truncated: bool
    note: str = None  # type: ignore[assignment]


class MemoryWriteResult(ToolResult):
    board_id: str
    path: str
    mode: Literal["create", "replace", "append"]
    created: bool
    bytes: int
    size: int
    sha256: str


class MemoryMoveResult(ToolResult):
    board_id: str
    source: str
    target: str
    kind: Literal["file", "directory", "link"]


class MemoryDeleteResult(ToolResult):
    board_id: str
    path: str
    recursive: bool
    removed: int


class BoardArtifactsResult(ToolResult):
    """`board_artifacts` : Artifacts liés à un Board (liens v8), récents d'abord."""

    board_id: str
    items: list[ArtifactItem]
    next_cursor: str = None  # type: ignore[assignment]


class BoardArtifactLinkResult(ToolResult):
    board_id: str
    artifact_id: str
    linked: bool
    #: Faux : déjà dans l'état demandé (aucune ligne d'activité).
    changed: bool


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
