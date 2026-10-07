"""Choix dynamiques et manifeste de capacités du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, Slice 2).

Contrat : `docs/tool-brain-contracts.md` §8. Trois pièces, aucune ne possède d'état :

- **fournisseurs de choix** (`PROVIDERS`) : à partir d'un `UiState` lu chez les
  propriétaires (`SceneService`, `BoardService`), chacun rend les valeurs
  **légales à cet instant** d'un paramètre (`value` stable + `label` humain +
  `meta` compacte). Les ids de fournisseurs et les paramètres qui en dépendent
  sont déclarés dans `ToolMeta` (`mcp_tool_meta`, seule copie), jamais ici ;
- **validateur** (`validate_call`) : le même contrôle pour le Tool Brain et tout
  autre appelant Python. Un id fabriqué, retiré ou archivé est refusé avec le
  code du propriétaire (`unknown_object`, `object_archived`, `board_not_found`,
  `board_archived`...). Il **ne remplace pas** le réducteur : Core reste le seul
  maître de la mutation, et l'atomicité d'un appel reste `SceneService.apply_if` ;
- **manifeste** (`build_manifest`) : projection compacte du catalogue canonique
  (`mcp_catalog`) pour un décideur, avec le bloc `choices` de chaque paramètre.

Les libellés ne sont **pas** une autorité : seul `value` pilote l'exécution. Une
liste de choix n'accorde aucun droit (`ALLOWED_SCENE_OPS` et les services
restent juges). Il n'y a pas de révision par objet (décision G3) : la fraîcheur
est `(scene_id, epoch, revision)` + `active_board_id` (`StateRef`), le reste est
refusé par le réducteur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from jarvis.domain.browser_surface import (
    UNKNOWN_SURFACE, UNSAFE_URL, Surface, SurfaceError, check_surface_url, surfaces_of,
)
from jarvis.domain.scene import SceneObject, SceneRelation, SceneSnapshot, is_runtime_owned_relation
from jarvis.domain.workspace_board import Board, BoardStatus
from jarvis.ports.scene import SceneUnavailableError
from jarvis.runtime.mcp_tool_meta import UI_PRECONDITIONS, tool_meta

#: Plafond de choix **annoncés** par paramètre ; le validateur, lui, voit toute la liste légale.
MAX_ADVERTISED_CHOICES = 48
MAX_LABEL_CHARS = 60
MAX_PARAMETER_DESCRIPTION_CHARS = 100
MAX_SUMMARY_CHARS = 140
MANIFEST_SCHEMA = "tool_brain.manifest/1"

# Codes de refus : ceux du propriétaire quand il en a un (scene.SceneRefusal, BoardErrorCode).
UNKNOWN_TOOL = "unknown_tool"
NOT_UI_TOOL = "not_ui_tool"
SCENE_UNAVAILABLE = "scene_unavailable"
UNKNOWN_OBJECT = "unknown_object"
OBJECT_ARCHIVED = "object_archived"
UNKNOWN_RELATION = "unknown_relation"
RUNTIME_OWNED = "runtime_owned"
BOARD_NOT_FOUND = "board_not_found"
BOARD_ARCHIVED = "board_archived"
INVALID_CHOICE_TYPE = "invalid_choice_type"
STALE_SCENE_EPOCH = "stale_scene_epoch"
STALE_ACTIVE_BOARD = "stale_active_board"


# ------------------------------------------------------------------ état et références


@dataclass(frozen=True)
class StateRef:
    """Ce qu'un décideur a observé : de quoi détecter qu'il parle d'un autre monde (pas d'un autre instant).

    Une révision plus ancienne n'est pas un refus (les ids stables restent
    valides) : `validate_call` la rend en `revision_drift`. Une autre scène ou
    une autre époque, ou un autre Board actif, est un refus.
    """

    scene_id: str | None
    epoch: str | None
    revision: int | None
    active_board_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"scene_id": self.scene_id, "epoch": self.epoch, "revision": self.revision,
                "active_board_id": self.active_board_id}


@dataclass(frozen=True)
class UiState:
    """Lecture instantanée de l'état faisant autorité. `scene is None` : scène non servie."""

    scene: SceneSnapshot | None
    epoch: str | None
    boards: tuple[Board, ...]
    active_board_id: str | None

    @property
    def surfaces(self) -> tuple[Surface, ...]:
        """Surfaces de navigation ouvertes (fenêtres `jarvis.browser` de la scène) : dérivées, jamais stockées."""

        return surfaces_of(self.scene)

    def ref(self) -> StateRef:
        scene = self.scene
        return StateRef(scene.scene_id if scene else None, self.epoch, scene.revision if scene else None,
                        self.active_board_id)


class SceneStateSource(Protocol):
    """Ce que `SceneService` offre (lecture seule)."""

    @property
    def epoch(self) -> str | None: ...

    async def snapshot(self) -> SceneSnapshot: ...


class BoardStateSource(Protocol):
    """Ce que `BoardService` offre (lecture seule)."""

    async def list(self, *, include_archived: bool = False) -> Sequence[Board]: ...

    async def active_board_id(self) -> str: ...


async def read_ui_state(scene: SceneStateSource | None, boards: BoardStateSource | None) -> UiState:
    """Lire l'état chez ses propriétaires. Une scène non servie donne `scene=None`, pas une exception.

    Toute autre panne remonte : un état deviné vaudrait un id fabriqué.
    """

    snapshot: SceneSnapshot | None = None
    epoch: str | None = None
    if scene is not None:
        try:
            snapshot, epoch = await scene.snapshot(), scene.epoch
        except SceneUnavailableError:
            snapshot, epoch = None, None  # dit par `scene_unavailable` au validateur, jamais deviné
    listed: tuple[Board, ...] = ()
    active: str | None = None
    if boards is not None:
        listed = tuple(await boards.list(include_archived=True))
        active = await boards.active_board_id()
    return UiState(scene=snapshot, epoch=epoch, boards=listed, active_board_id=active)


# ------------------------------------------------------------------ choix


@dataclass(frozen=True)
class Choice:
    """Une valeur légale : `value` pilote l'exécution, `label` est pour le modèle, `meta` borne la décision."""

    value: str
    label: str
    meta: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "label": self.label, "meta": dict(self.meta)}


@dataclass(frozen=True)
class ChoiceProvider:
    """Contrat d'un fournisseur : liste des choix légaux et motif de refus d'une valeur qui n'en fait pas partie."""

    provider_id: str
    list_choices: Callable[[UiState], tuple[Choice, ...]]
    refusal: Callable[[UiState, str], str]
    #: Source d'état indisponible (`scene_unavailable`) : vérifié avant la liste.
    needs_scene: bool = False


def _label(text: str, fallback: str) -> str:
    one_line = " ".join(text.split()) or fallback
    return one_line if len(one_line) <= MAX_LABEL_CHARS else one_line[: MAX_LABEL_CHARS - 1] + "…"


def _object_choice(item: SceneObject) -> Choice:
    title = item.payload.title
    return Choice(
        value=item.object_id,
        label=_label(title, item.category),
        meta={"kind": item.kind.value, "category": item.category, "representation": item.representation.value,
              "visibility": item.visibility.value, "exec_state": item.exec_state.value,
              "pinned": item.constraints.pinned_by_user, "placed": item.geometry is not None},
    )


def _scene_objects(state: UiState) -> tuple[Choice, ...]:
    assert state.scene is not None
    ordered = sorted(state.scene.objects, key=lambda item: (item.visibility.value != "visible", item.object_id))
    return tuple(_object_choice(item) for item in ordered)


def _object_refusal(state: UiState, value: str) -> str:
    assert state.scene is not None
    return OBJECT_ARCHIVED if value in state.scene.archived_ids else UNKNOWN_OBJECT


def _relation_choice(snapshot: SceneSnapshot, relation: SceneRelation) -> Choice:
    source, target = snapshot.get_object(relation.from_id), snapshot.get_object(relation.to_id)
    names = (_label(source.payload.title, source.category) if source else relation.from_id,
             _label(target.payload.title, target.category) if target else relation.to_id)
    return Choice(relation.relation_id, _label(f"{relation.kind.value}: {names[0]} -> {names[1]}", relation.relation_id),
                  {"kind": relation.kind.value, "from_id": relation.from_id, "to_id": relation.to_id})


def _removable_relations(state: UiState) -> tuple[Choice, ...]:
    snapshot = state.scene
    assert snapshot is not None
    return tuple(_relation_choice(snapshot, relation) for relation in sorted(snapshot.relations, key=lambda r: r.relation_id)
                 if not is_runtime_owned_relation(snapshot, relation))


def _relation_refusal(state: UiState, value: str) -> str:
    assert state.scene is not None
    existing = state.scene.get_relation(value)
    return RUNTIME_OWNED if existing is not None and is_runtime_owned_relation(state.scene, existing) else UNKNOWN_RELATION


def _board_choice(board: Board, active_id: str | None) -> Choice:
    return Choice(board.board_id, _label(board.title, board.board_id),
                  {"status": board.status.value, "active": board.board_id == active_id,
                   "board_kind": board.board_kind.value})


def _switchable_boards(state: UiState) -> tuple[Choice, ...]:
    return tuple(_board_choice(board, state.active_board_id) for board in state.boards
                 if board.status is BoardStatus.ACTIVE)


def _readable_boards(state: UiState) -> tuple[Choice, ...]:
    return tuple(_board_choice(board, state.active_board_id) for board in state.boards)


def _board_refusal(state: UiState, value: str) -> str:
    known = next((board for board in state.boards if board.board_id == value), None)
    return BOARD_ARCHIVED if known is not None and known.status is BoardStatus.ARCHIVED else BOARD_NOT_FOUND


def _surface_choice(surface: Surface) -> Choice:
    page = surface.page
    return Choice(surface.surface_id, _label((page.label or surface.meta()["host"]) if page else "", surface.surface_id),
                  surface.meta())


def _browser_surfaces(state: UiState) -> tuple[Choice, ...]:
    return tuple(_surface_choice(surface) for surface in state.surfaces)


#: Une implémentation par id de `mcp_tool_meta.CHOICE_PROVIDERS` (test de parité).
PROVIDERS: dict[str, ChoiceProvider] = {
    "scene.object": ChoiceProvider("scene.object", _scene_objects, _object_refusal, needs_scene=True),
    "scene.relation": ChoiceProvider("scene.relation", _removable_relations, _relation_refusal, needs_scene=True),
    "board.switchable": ChoiceProvider("board.switchable", _switchable_boards, _board_refusal),
    "board.readable": ChoiceProvider("board.readable", _readable_boards, _board_refusal),
    "surface.browser": ChoiceProvider("surface.browser", _browser_surfaces, lambda _state, _value: UNKNOWN_SURFACE,
                                      needs_scene=True),
}


# ------------------------------------------------------------------ validateur


@dataclass(frozen=True)
class Refusal:
    code: str
    parameter: str | None
    value: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "parameter": self.parameter, "value": self.value, "detail": self.detail}


@dataclass(frozen=True)
class Validation:
    """`ok` vaut « aucun refus » ; `revision_drift` : révisions de scène écoulées depuis l'observation (info)."""

    refusals: tuple[Refusal, ...]
    revision_drift: int | None = None

    @property
    def ok(self) -> bool:
        return not self.refusals

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "refusals": [item.to_dict() for item in self.refusals],
                "revision_drift": self.revision_drift}


def _values(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def validate_call(server: str, tool: str, arguments: Mapping[str, Any], state: UiState, *,
                  observed: StateRef | None = None) -> Validation:
    """Contrôle d'un appel d'outil d'interface contre l'état courant. Fonction pure ; tous les refus sont rendus.

    1. outil inconnu ou hors interface : refus ;
    2. `observed` (facultatif) : autre scène/époque ou autre Board actif : refus ;
    3. préconditions déclarées (`scene_available`) ;
    4. chaque paramètre à fournisseur : toute valeur doit être dans la liste légale **complète** (pas
       seulement les choix annoncés). Un paramètre absent (`None`) n'est pas contrôlé : le schéma décide.
    """

    try:
        meta = tool_meta(server, tool)
    except KeyError:
        return Validation((Refusal(UNKNOWN_TOOL, None, None, f"{server}/{tool}"),))
    if meta.ui_surface is None:
        return Validation((Refusal(NOT_UI_TOOL, None, None, f"{server}/{tool} is not a UI tool"),))
    refusals: list[Refusal] = []
    drift: int | None = None
    scene_tool = meta.ui_surface in ("scene", "browser")
    if scene_tool and state.scene is None:
        return Validation((Refusal(SCENE_UNAVAILABLE, None, None, "the scene is not served"),))
    if observed is not None:
        if scene_tool and state.scene is not None:
            if observed.scene_id != state.scene.scene_id or observed.epoch != state.epoch:
                refusals.append(Refusal(STALE_SCENE_EPOCH, None, None, "scene or epoch changed since the observation"))
            elif observed.revision is not None:
                drift = max(0, state.scene.revision - observed.revision)
        if meta.ui_surface == "board" and observed.active_board_id != state.active_board_id:
            refusals.append(Refusal(STALE_ACTIVE_BOARD, None, None, "the active Board changed since the observation"))
    if meta.ui_surface == "browser" and arguments.get("url") is not None:
        try:
            check_surface_url(arguments["url"])
        except SurfaceError as exc:  # l'adresse n'est jamais redite en entier : elle peut être longue ou hostile
            refusals.append(Refusal(UNSAFE_URL, "url", str(arguments["url"])[:80], exc.detail))
    for parameter, provider_id in meta.choice_providers.items():
        raw = arguments.get(parameter)
        if raw is None:
            continue
        provider = PROVIDERS[provider_id]
        legal = {choice.value for choice in provider.list_choices(state)}
        for value in _values(raw):
            if not isinstance(value, str):
                refusals.append(Refusal(INVALID_CHOICE_TYPE, parameter, None, "expected a string id"))
            elif value not in legal:
                refusals.append(Refusal(provider.refusal(state, value), parameter, value[:80],
                                        f"not a current value of {provider_id}"))
    return Validation(tuple(refusals), drift)


# ------------------------------------------------------------------ manifeste


def _parameter_mode(parameter: Mapping[str, Any], provider_id: str | None) -> str:
    """`provider` (liste d'état), `enum` (liste du schéma), `bounded` (bool / bornes numériques), `free_form`."""

    if provider_id is not None:
        return "provider"
    constraints = parameter.get("constraints") or {}
    if "enum" in constraints or "const" in constraints:
        return "enum"
    if parameter.get("type") == "boolean" or any(key in constraints for key in
                                                  ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")):
        return "bounded"
    return "free_form"


def _choices_block(provider_id: str, state: UiState) -> dict[str, Any]:
    provider = PROVIDERS[provider_id]
    if provider.needs_scene and state.scene is None:
        return {"provider": provider_id, "total": 0, "truncated": False, "items": [], "unavailable": SCENE_UNAVAILABLE}
    choices = provider.list_choices(state)
    return {"provider": provider_id, "total": len(choices), "truncated": len(choices) > MAX_ADVERTISED_CHOICES,
            "items": [choice.to_dict() for choice in choices[:MAX_ADVERTISED_CHOICES]]}


def _manifest_parameter(parameter: Mapping[str, Any], providers: Mapping[str, str]) -> dict[str, Any]:
    name = parameter["name"]
    provider_id = providers.get(name)
    mode = _parameter_mode(parameter, provider_id)
    entry: dict[str, Any] = {
        "name": name, "type": parameter["type"], "required": parameter["required"], "mode": mode,
        "description": str(parameter.get("description") or "")[:MAX_PARAMETER_DESCRIPTION_CHARS],
    }
    if parameter.get("has_default"):
        entry["default"] = parameter.get("default")
    if mode in ("enum", "bounded"):
        entry["constraints"] = {key: value for key, value in (parameter.get("constraints") or {}).items()
                                if key in ("enum", "const", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")}
    if provider_id is not None:
        entry["choices_ref"] = provider_id  # la liste est dite une fois, dans `manifest["choices"]`
    return entry


def build_manifest(catalog: Mapping[str, Any], state: UiState, *, include_surfaces: Sequence[str] | None = None,
                   include_tools: Sequence[str] | None = None) -> dict[str, Any]:
    """Manifeste de capacités : les outils d'interface du catalogue canonique, avec leurs choix à cet instant.

    `choices` dit chaque liste légale **une fois** par fournisseur ; un paramètre la désigne par `choices_ref`.
    Lit `catalog["tools"]` (descripteurs de `mcp_catalog.describe_tool`, clé `ui`) : un outil sans `ui` n'y est
    pas. `state` est la référence de fraîcheur (`state.ref()`) que le décideur renvoie à `validate_call`.
    """

    tools: list[dict[str, Any]] = []
    used: set[str] = set()
    codes: set[str] = set()
    for tool in catalog["tools"]:
        ui = tool.get("ui")
        if ui is None or (include_surfaces is not None and ui["surface"] not in include_surfaces):
            continue
        if include_tools is not None and tool["name"] not in include_tools:
            continue
        providers = ui["choice_providers"]
        used.update(providers.values())
        codes.update(ui["preconditions"])
        tools.append({
            "name": tool["name"], "server": tool["server"], "label": tool["label"],
            "summary": tool["summary"][:MAX_SUMMARY_CHARS],
            "surface": ui["surface"], "side_effect": tool["side_effect"], "reversibility": ui["reversibility"],
            "idempotent": tool["idempotent"], "atomicity": tool["atomicity"],
            "preconditions": list(ui["preconditions"]),
            "parameter_rules": list(tool["parameter_rules"]),
            "parameters": [_manifest_parameter(parameter, providers) for parameter in tool["parameters"]],
        })
    return {"schema": MANIFEST_SCHEMA, "state": state.ref().to_dict(),
            "precondition_rules": {code: UI_PRECONDITIONS[code] for code in sorted(codes)},
            "choices": {provider_id: _choices_block(provider_id, state) for provider_id in sorted(used)},
            "tools": tools}


async def tool_brain_manifest(scene: SceneStateSource | None, boards: BoardStateSource | None, *,
                              include_surfaces: Sequence[str] | None = None,
                              include_tools: Sequence[str] | None = None) -> dict[str, Any]:
    """Manifeste d'un instant : lit l'état chez ses propriétaires et le catalogue canonique (mis en cache)."""

    from jarvis.runtime.mcp_catalog import cached_catalog

    return build_manifest(await cached_catalog(), await read_ui_state(scene, boards),
                          include_surfaces=include_surfaces, include_tools=include_tools)


# ------------------------------------------------------------------ portée du manifeste (S10)


def scope_tools(manifest: Mapping[str, Any], *, executable: Callable[[str, str], bool] | None = None,
                wake_classes: Sequence[str] = (), intents: Sequence[Mapping[str, Any]] = ()) -> tuple[str, ...]:
    """Noms d'outils qu'un réveil donné doit voir. Mesure S10 : le manifeste complet pèse ~30 Ko (~10k jetons payés à
    chaque appel) et un modèle réel y propose des outils qu'aucun adaptateur n'exécute (lectures, création).

    Règles (une seule table, §18.3) : (1) seuls les outils exécutables restent (les lectures passent par les
    inspections du runtime, pas par des actions) ; (2) un outil dont un paramètre **requis** n'a aucun choix légal
    maintenant est retiré (`surface_zoom` sans surface, `scene_unlink` sans lien, `board_switch` sans autre Board) ;
    (3) un outil irréversible n'est montré que si une intention `dismiss` est là et que le réveil n'est pas le simple tick.
    La portée n'est **pas** un contrôle d'accès : `validate_call` et la garde jugent toujours sur le catalogue complet.
    """

    choices = manifest.get("choices") or {}
    dismiss = any(item.get("kind") == "dismiss" for item in intents) and set(wake_classes) != {"tick"}
    kept: list[str] = []
    for tool in manifest["tools"]:
        if executable is not None and not executable(tool["server"], tool["name"]):
            continue
        if tool.get("reversibility") == "irreversible" and not dismiss:
            continue
        if any(parameter["mode"] == "provider" and parameter["required"]
               and not (choices.get(parameter["choices_ref"]) or {}).get("total")
               for parameter in tool["parameters"]):
            continue
        kept.append(tool["name"])
    return tuple(kept)
