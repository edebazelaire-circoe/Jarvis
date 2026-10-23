"""Configuration des cerveaux : descripteur par cerveau, lecture et écriture révisées (docs/brain-config.md).

Un descripteur ne montre que les champs que le cerveau **supporte réellement**, chacun avec `editable`, `reason`,
`applies` et son propriétaire (`owner`). Aucune valeur n'est copiée : chaque champ est lu chez son propriétaire et
s'y écrit.

| Cerveau | Champ | Propriétaire |
| --- | --- | --- |
| `core` | `provider`, `model` | `agent_cli`, `agent_cli_settings.<cli>.model` (commande, chemin, autorisations : hors contrat, Avancé) |
| `core` | `instructions` | surcharge `backend.system.addition` (`prompt_overrides`) |
| `core` | `delegation` | `brain-config.json` (`brain_config_store`), seule valeur propre à ce contrat |
| `voice` | `model` | `voice_architecture.config` (`conversation_model`, ou `reflex_model` en Front Brain) ; `voice_stack` en compatibilité (lecture seule) |
| `voice` | `instructions` | `live.duplex.addition` (Duplex) ou `voice.conversation.addition` |
| `luna` | `model`, `instructions` | `voice_architecture.config.analysis_model`, `front_brain.analysis.addition` |
| `tool_brain` | `model` | `tool_brain.model` (`JARVIS_TOOL_BRAIN_MODEL` posée : prioritaire, champ verrouillé) |
| `tool_brain` | `activation` | `tool_brain.mode`, écrit par le service du graphe (un seul écrivain) |

La mission est un texte en lecture seule fourni par le code (`BRAIN_MISSIONS`). Pas de personnalité ici : le ton,
la politesse, la longueur et l'humour (`voice.persona`) appartiennent à la page Personnalisation.

Révision : `c-<empreinte>` **calculée** à partir de ce qui porte les champs du cerveau (réglages, variables
d'environnement, révision de `brain-config.json`), comme la révision de topologie du graphe : une écriture faite par
une autre page la périme aussi. Les instructions gardent la révision du mécanisme des surcharges
(`effective_revision`, refus `prompt_override_stale|concurrent`), qui n'est pas dupliqué.

Ce module vit dans le processus du Control Center. Il n'est monté nulle part (`brain_config_http.py`, Slice 07).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from jarvis.domain.architecture_graph import Applies, ArchitectureGraphError, ArchitectureSnapshot, Node
from jarvis.domain.brain_config import (
    BRAIN_ABSENT, BRAIN_IDS, BRAIN_MISSIONS, CATALOG_UNAVAILABLE, FIELD_LOCKED, FIELD_UNSUPPORTED,
    MODEL_UNAVAILABLE, REQUEST_INVALID, REVISION_STALE, SNAPSHOT_FAILED, UNKNOWN_BRAIN, WRITE_FAILED,
    ACTIVATION_INVALID, BrainConfigError, delegation_choices, parse_delegation,
)
from jarvis.domain.errors import ConfigurationError
from jarvis.domain.prompt_registry import PromptError
from jarvis.domain.voice_architecture import (
    DuplexVoiceConfig, FrontBrainVoiceConfig, VoiceConfigError, VoiceModelRef,
)
from jarvis.runtime import cli_catalog
from jarvis.runtime.agent_settings import resolve_agent_settings
from jarvis.runtime.architecture_graph import ArchitectureGraphService
from jarvis.runtime.brain_config_store import (
    DELEGATING_BRAINS, BrainConfigStore, LoadedBrainConfig, launched_delegation,
)
from jarvis.runtime.prompt_overrides import PromptOverrideStore
from jarvis.runtime.tool_brain_decider import (
    DEFAULT_TOOL_BRAIN_MODEL, TOOL_BRAIN_MODEL_ENV, TOOL_BRAIN_MODEL_FIELD, tool_brain_model_source,
)
from jarvis.runtime.tool_brain_wiring import TOOL_BRAIN_MODE_ENV, TOOL_BRAIN_MODES, TOOL_BRAIN_SETTING, resolve_mode
from jarvis.runtime.voice_architecture_config import (
    VOICE_ARCHITECTURE_SETTING, decode_voice_architecture, load_voice_architecture, store_voice_architecture,
)
from jarvis.runtime.voice_composition import resolve_voice_composition

SCHEMA_VERSION = 1
REVISION_PREFIX = "c-"
#: `(surface, role) -> CatalogView.to_dict()`, la même vue que `GET /api/catalog` : le serveur reste la seule
#: source des modèles disponibles. La Slice 07 la branche sur l'assemblage du Control Center.
CatalogProvider = Callable[[str, str], Awaitable[Mapping[str, Any]]]

NOT_APPLICABLE = "not_applicable"
CLI_DEFAULT_LABEL = "Modèle par défaut du CLI"
_ARCH_HINT = "Changez d'architecture dans Avancé › Architecture & compatibilité."
#: Ce qu'aucun cerveau n'expose ici, dit une fois (fenêtre du cerveau, Slice 05).
OUT_OF_SCOPE = {
    "personality": "Ton, politesse, longueur et humour : page Personnalisation, pas la fenêtre du cerveau.",
    "subagent_models": "Le modèle de chaque rôle de sous-agent se règle dans l'onglet Sous-agents.",
    "cli_technical": "Commande, chemin et autorisations du CLI : Avancé › CLI.",
}
_PROMPT_APPLIES = {"core": Applies.CORE_RESTART, "voice": Applies.VOICE_RESTART, "luna": Applies.VOICE_RESTART}
#: Ce que chaque cerveau accepte dans un PATCH ; `provider` et `model` de Core peuvent aller ensemble (même fichier,
#: une seule écriture atomique), tout autre couple est refusé : deux propriétaires différents ne s'écrivent pas
#: atomiquement ensemble.
_WRITABLE = {"core": {"provider", "model", "instructions", "delegation"}, "voice": {"model", "instructions"},
             "luna": {"model", "instructions"}, "tool_brain": {"model", "activation"}}
_KNOWN_FIELDS = {"provider", "model", "instructions", "delegation", "activation", "mission"}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _field(value: object, *, editable: bool, reason: str = "", applies: Applies | str | None = None,
           owner: str | None = None, **extra: object) -> dict[str, object]:
    return {"value": value, "editable": editable, "reason": reason,
            "applies": applies.value if isinstance(applies, Applies) else applies, "owner": owner, **extra}


class BrainConfigService:
    """Lecture (`describe`) et écriture (`patch`) de la configuration d'un cerveau.

    Dépendances injectées : le service du graphe (identités, état, liaisons, et seul écrivain du mode du Tool
    Brain), le store de la tendance, le store des surcharges de prompt (celui de `/api/prompts`), le catalogue.
    """

    def __init__(self, graph: ArchitectureGraphService, *, store: BrainConfigStore | None = None,
                 prompts: PromptOverrideStore | None = None, catalog: CatalogProvider | None = None,
                 environ: Mapping[str, str] | None = None, journal: Any = None,
                 after_settings_write: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.graph = graph
        self.store = store or BrainConfigStore(graph.runtime_root)
        if prompts is None:
            from jarvis.runtime.prompt_catalog import default_prompt_registry
            prompts = PromptOverrideStore(default_prompt_registry(), read_settings=graph.store.read,
                                          write_settings=graph.store.write, diagnostics=journal)
        self.prompts = prompts
        self._catalog = catalog
        self._environ = environ
        self.journal = journal
        #: Crochet de la Slice 07 : reconfigurer les agents vivants (`ControlCenter._apply_agent_settings`) après une
        #: écriture du modèle de Core. Absent, l'écriture vaut au prochain démarrage (`applies: core_restart`).
        self._after_settings_write = after_settings_write

    @property
    def environ(self) -> Mapping[str, str]:
        return os.environ if self._environ is None else self._environ

    @property
    def runtime_root(self) -> Path:
        return self.graph.runtime_root

    # ------------------------------------------------------------------ lecture

    async def describe(self, brain_id: str) -> dict[str, Any]:
        if brain_id not in BRAIN_IDS:
            raise BrainConfigError(UNKNOWN_BRAIN, f"Cerveau inconnu : {str(brain_id)[:40]}.")
        try:
            settings = self.graph.store.read()
            snapshot = self.graph.snapshot()
        except (OSError, ValueError, ArchitectureGraphError) as exc:
            raise BrainConfigError(SNAPSHOT_FAILED, "Lecture des réglages ou de l'architecture impossible "
                                   f"({type(exc).__name__}: {exc}).") from exc
        node = snapshot.node(brain_id)
        if node is None:
            raise BrainConfigError(BRAIN_ABSENT, "Ce cerveau n'existe pas dans l'architecture vocale courante "
                                   f"({snapshot.voice_architecture.label}). {_ARCH_HINT}")
        loaded = self.store.load()
        catalog = _CatalogReader(self._catalog)
        fields: dict[str, Any] = {}
        builder = {"core": self._core_fields, "voice": self._voice_fields, "luna": self._luna_fields,
                   "tool_brain": self._tool_brain_fields}[brain_id]
        await builder(fields, settings, loaded, catalog, snapshot)
        fields["mission"] = _field(BRAIN_MISSIONS[brain_id], editable=False, owner="code:brain_config.BRAIN_MISSIONS",
                                   reason="Responsabilités décrites par le code ; aucune mission de cerveau n'est "
                                          "enregistrée aujourd'hui.")
        if "delegation" not in fields:
            fields["delegation"] = _field(NOT_APPLICABLE, editable=False, owner=None,
                                          reason=_NO_DELEGATION_REASON[brain_id])
        if "activation" not in fields:
            fields["activation"] = _field(node.state.value, editable=False, owner=None,
                                          reason=node.activation.reason or "Activation non réglable pour ce cerveau.")
        return {
            "schema_version": SCHEMA_VERSION,
            "brain_id": brain_id,
            "revision": self._revision(brain_id, settings, loaded),
            "label": node.label,
            "brain_type": node.brain_type,
            "process": node.process,
            "system": node.system,
            "state": {"state": node.state.value, "reason": node.state_reason},
            "voice_architecture": snapshot.voice_architecture.to_dict(),
            "fields": fields,
            "out_of_scope": dict(OUT_OF_SCOPE),
            "connections": _connections(snapshot, node),
            "catalog": catalog.status(),
            "store": {"status": "unreadable" if loaded.error_code else "ok", "code": loaded.error_code,
                      "reason": loaded.error_reason},
        }

    def _revision(self, brain_id: str, settings: Mapping[str, Any], loaded: LoadedBrainConfig) -> str:
        env = self.environ

        def env_of(*names: str) -> dict[str, str]:
            return {name: str(env.get(name, "") or "").strip() for name in names}

        if brain_id == "core":
            inputs: dict[str, object] = {
                "store": loaded.revision_token,
                "settings": {key: settings.get(key) for key in ("agent_cli", "agent_cli_settings", "claude_cli")},
                "env": env_of("JARVIS_CLAUDE_MODEL", "JARVIS_CLAUDE_CLI")}
        elif brain_id in ("voice", "luna"):
            inputs = {"settings": {key: settings.get(key) for key in (VOICE_ARCHITECTURE_SETTING, "voice_arch",
                                                                       "voice_stack", "voice_stack_settings")},
                      "env": env_of("JARVIS_VOICE_ARCH", "JARVIS_VOICE_STACK", "OPENAI_REALTIME_MODEL")}
        else:
            inputs = {"settings": {TOOL_BRAIN_SETTING: settings.get(TOOL_BRAIN_SETTING)},
                      "env": env_of(TOOL_BRAIN_MODE_ENV, TOOL_BRAIN_MODEL_ENV)}
        return REVISION_PREFIX + _digest({"brain": brain_id, **inputs})

    def _instructions(self, prompt_id: str | None, applies: Applies | None, *, reason_if_none: str = "") -> dict:
        if prompt_id is None:
            return _field(None, editable=False, reason=reason_if_none)
        try:
            layer = next(item for item in self.prompts.inspect()["layers"] if item["prompt_id"] == prompt_id)
        except (PromptError, OSError, ValueError, StopIteration) as exc:
            return _field(None, editable=False, owner=f"prompt_overrides.{prompt_id}",
                          reason=f"Surcharges de prompt illisibles ({type(exc).__name__}) : instructions non modifiables "
                                 "tant que le document n'est pas corrigé (Avancé › Prompts).")
        return _field(layer["current_text"], editable=bool(layer["editable"]), applies=applies,
                      owner=f"prompt_overrides.{prompt_id}", prompt_id=prompt_id,
                      reason="" if not layer.get("conflict") else f"Surcharge enregistrée ignorée ({layer['conflict']}).",
                      effective_revision=layer["effective_revision"], default_revision=layer["default_revision"],
                      max_length=_max_override())

    async def _core_fields(self, fields: dict, settings: Mapping[str, Any], loaded: LoadedBrainConfig,
                           catalog: "_CatalogReader", snapshot: ArchitectureSnapshot) -> None:
        agent_cli = cli_catalog.normalize_agent_cli(settings.get("agent_cli"))
        model = resolve_agent_settings(settings, agent_cli, environ=self.environ)["model"]
        items = await catalog.items("subagents", "text")
        fields["provider"] = _field(
            agent_cli, editable=True, applies=Applies.CORE_RESTART, owner="agent_cli",
            reason="Le CLI cerveau relit ce choix à son lancement (Back Brain : au démarrage de Core).",
            choices=_cli_choices(items, agent_cli, catalog))
        fields["model"] = _field(
            model, editable=True, applies=Applies.CORE_RESTART, owner=f"agent_cli_settings.{agent_cli}.model",
            reason="Vide : le CLI garde son modèle par défaut. Relu au lancement du CLI cerveau.",
            choices=_model_choices(items, model, catalog, agent_id=agent_cli, default_label=CLI_DEFAULT_LABEL))
        fields["instructions"] = self._instructions("backend.system.addition", _PROMPT_APPLIES["core"])
        level = loaded.document.delegation_for("core")
        launched = launched_delegation(self.runtime_root)
        stored_invalid = loaded.document.invalid.get("core")
        if loaded.error_code:
            reason, editable = loaded.error_reason, False
        elif stored_invalid:
            reason, editable = (f"Valeur enregistrée inconnue « {stored_invalid} » : le cerveau garde « standard » "
                                "jusqu'à un nouveau choix."), True
        elif agent_cli != "claude":
            reason, editable = ("Le CLI cerveau actuel ne lance pas de sous-agents ; le choix vaudra pour Claude "
                                "Code."), True
        else:
            reason, editable = "", True
        fields["delegation"] = _field(
            level.value, editable=editable, reason=reason, applies=Applies.CORE_RESTART,
            owner="brain_config.core.delegation", choices=delegation_choices(), stored_invalid=stored_invalid,
            store_revision=loaded.revision_token, enforcement=_DELEGATION_ENFORCEMENT,
            # Ce qu'a reçu le dernier CLI cerveau lancé (`None` : aucun lancement connu) ; `pending_relaunch` : la
            # valeur enregistrée attend sa relance (outil et consigne), même si le hook applique déjà `never`.
            launched=launched.value if launched is not None else None,
            pending_relaunch=launched is not None and launched is not level)

    async def _voice_fields(self, fields: dict, settings: Mapping[str, Any], loaded: LoadedBrainConfig,
                            catalog: "_CatalogReader", snapshot: ArchitectureSnapshot) -> None:
        arch = snapshot.voice_architecture.id
        selection, problem = self._selection(settings)
        if selection is None:
            fields["model"] = _field(None, editable=False, reason=f"Configuration vocale illisible : {problem}")
        elif selection.compatibility is not None:
            config = selection.config
            fields["model"] = _field(
                config.conversation_model.model_id, editable=False, owner="voice_stack",
                reason=("En architecture de compatibilité, le modèle suit la pile vocale (Avancé › Architecture & "
                        "compatibilité)."), provider=config.conversation_model.provider_id)
        else:
            config = selection.config
            ref = config.reflex_model if isinstance(config, FrontBrainVoiceConfig) else config.conversation_model
            slot = "reflex_model" if isinstance(config, FrontBrainVoiceConfig) else "conversation_model"
            role = "duplex" if isinstance(config, DuplexVoiceConfig) else "realtime"
            items = await catalog.items("voice", role)
            fields["model"] = _field(
                ref.model_id, editable=True, applies=Applies.VOICE_RESTART,
                owner=f"voice_architecture.config.{slot}", provider=ref.provider_id,
                reason="Le fournisseur suit l'architecture vocale ; changer de modèle relance la voix.",
                choices=_model_choices(items, ref.model_id, catalog, provider_id=ref.provider_id))
        prompt_id = "live.duplex.addition" if arch == "duplex" else "voice.conversation.addition"
        fields["instructions"] = self._instructions(prompt_id, _PROMPT_APPLIES["voice"])

    async def _luna_fields(self, fields: dict, settings: Mapping[str, Any], loaded: LoadedBrainConfig,
                           catalog: "_CatalogReader", snapshot: ArchitectureSnapshot) -> None:
        selection, problem = self._selection(settings)
        config = selection.config if selection is not None else None
        if not isinstance(config, FrontBrainVoiceConfig) or selection.compatibility is not None:  # type: ignore[union-attr]
            fields["model"] = _field(None, editable=False, reason=f"Configuration Front Brain illisible : {problem}")
        else:
            items = await catalog.items("voice", "analysis")
            ref = config.analysis_model
            fields["model"] = _field(
                ref.model_id, editable=True, applies=Applies.VOICE_RESTART,
                owner="voice_architecture.config.analysis_model", provider=ref.provider_id,
                reason="Modèle d'analyse de Luna ; relu au démarrage de la voix.",
                choices=_model_choices(items, ref.model_id, catalog, provider_id=ref.provider_id))
        fields["instructions"] = self._instructions("front_brain.analysis.addition", _PROMPT_APPLIES["luna"])

    async def _tool_brain_fields(self, fields: dict, settings: Mapping[str, Any], loaded: LoadedBrainConfig,
                                 catalog: "_CatalogReader", snapshot: ArchitectureSnapshot) -> None:
        model, source = tool_brain_model_source(self.environ, settings)
        env_model = str(self.environ.get(TOOL_BRAIN_MODEL_ENV, "") or "").strip()
        locked = (f"Imposé par l'environnement ({TOOL_BRAIN_MODEL_ENV}={env_model}) ; retirez la variable pour le "
                  "régler ici.") if source == "env" else ""
        items = await catalog.items("subagents", "text")
        fields["model"] = _field(
            model, editable=source != "env", applies=Applies.NEXT_TURN,
            owner=f"{TOOL_BRAIN_SETTING}.{TOOL_BRAIN_MODEL_FIELD}", source=source,
            reason=locked or "Relu à chaque décision du Tool Brain (CLI Claude sans outils).",
            choices=_model_choices(items, model if source != "default" else "", catalog, agent_id="claude",
                                   default_label=f"Défaut ({DEFAULT_TOOL_BRAIN_MODEL})"))
        fields["instructions"] = _field(None, editable=False, reason=(
            "La consigne du Tool Brain n'est pas au catalogue des prompts : elle n'est pas modifiable."))
        mode, mode_source = resolve_mode(settings, self.environ)
        env_mode = str(self.environ.get(TOOL_BRAIN_MODE_ENV, "") or "").strip()
        node = snapshot.node("tool_brain")
        fields["activation"] = _field(
            mode.value, editable=mode_source != "env", applies=Applies.CORE_RESTART,
            owner=f"{TOOL_BRAIN_SETTING}.mode", source=mode_source,
            live=(node.details.get("mode") if node is not None else None),
            reason=(f"Imposé par l'environnement ({TOOL_BRAIN_MODE_ENV}={env_mode}) ; retirez la variable pour le "
                    "régler ici.") if mode_source == "env" else "Lu au démarrage de Core ; même réglage que la "
                                                                 "liaison Core → Tool Brain du graphe.",
            choices=[{"value": value, "label": _MODE_LABELS[value]} for value in TOOL_BRAIN_MODES])

    def _selection(self, settings: Mapping[str, Any]):
        try:
            return load_voice_architecture(settings, environ=self.environ), None
        except (VoiceConfigError, ConfigurationError) as exc:
            return None, str(exc)

    # ------------------------------------------------------------------ écriture

    async def patch(self, brain_id: str, body: object) -> dict[str, Any]:
        """Appliquer un PATCH ; rend `{"changed", "applies", "config"}` ou lève `BrainConfigError`."""

        if brain_id not in BRAIN_IDS:
            raise BrainConfigError(UNKNOWN_BRAIN, f"Cerveau inconnu : {str(brain_id)[:40]}.")
        if not isinstance(body, Mapping):
            raise BrainConfigError(REQUEST_INVALID, "Le corps doit être un objet.")
        requested = set(body) - {"base_revision"}
        unknown = requested - _KNOWN_FIELDS
        if unknown or not requested:
            raise BrainConfigError(REQUEST_INVALID, "Champs attendus : un parmi provider, model, instructions, "
                                   "delegation, activation (avec base_revision).")
        unsupported = sorted(requested - _WRITABLE[brain_id])
        if unsupported:
            name = unsupported[0]
            reason = (_NO_DELEGATION_REASON.get(brain_id) if name == "delegation" else None) or (
                f"Ce cerveau ne règle pas « {name} » ici.")
            raise BrainConfigError(FIELD_UNSUPPORTED, reason, field=name)
        if len(requested) > 1 and requested != {"provider", "model"}:
            raise BrainConfigError(REQUEST_INVALID, "Un champ par écriture (seuls provider et model de Core vont "
                                   "ensemble) : chaque champ a son propre propriétaire.")
        current = await self.describe(brain_id)
        if body.get("base_revision") != current["revision"]:
            raise BrainConfigError(REVISION_STALE, "La configuration de ce cerveau a changé depuis votre lecture ; "
                                   "relisez-la avant de la modifier.")
        field = "model" if "model" in requested else next(iter(requested))
        descriptor = current["fields"][field]
        if not descriptor["editable"]:
            raise BrainConfigError(FIELD_LOCKED, descriptor["reason"] or "Champ non modifiable.", field=field)
        handler = {"delegation": self._write_delegation, "instructions": self._write_instructions,
                   "activation": self._write_activation, "model": self._write_model, "provider": self._write_model}
        changed, applies = await handler[field](brain_id, body, current)
        self._emit("brain_config.saved" if changed else "brain_config.unchanged",
                   f"Configuration du cerveau {brain_id} : {', '.join(sorted(requested))}"
                   + (" enregistré." if changed else " déjà dans l'état demandé."),
                   {"code": "brain_config_saved" if changed else "brain_config_unchanged", "brain_id": brain_id,
                    "fields": sorted(requested), "applies": applies,
                    **({"delegation": body["delegation"]} if field == "delegation" else {})})
        return {"changed": changed, "applies": applies, "config": await self.describe(brain_id)}

    async def _write_delegation(self, brain_id: str, body: Mapping[str, Any], current: Mapping) -> tuple[bool, str]:
        level = parse_delegation(body.get("delegation"))
        field = current["fields"]["delegation"]
        if brain_id not in DELEGATING_BRAINS:  # pragma: no cover - `_WRITABLE` already refuses it
            raise BrainConfigError(FIELD_UNSUPPORTED, field["reason"], field="delegation")
        if level.value == field["value"] and not field.get("stored_invalid"):
            return False, field["applies"]  # déjà effectif (le défaut compris) : rien n'est écrit
        self.store.set_delegation(brain_id, level, base_revision=field["store_revision"])
        return True, field["applies"]

    async def _write_instructions(self, brain_id: str, body: Mapping[str, Any], current: Mapping) -> tuple[bool, str]:
        raw = body.get("instructions")
        field = current["fields"]["instructions"]
        if (not isinstance(raw, Mapping) or not isinstance(raw.get("text"), str)
                or not isinstance(raw.get("effective_revision"), str)):
            # `effective_revision` est obligatoire : sans elle, une modification faite ailleurs serait écrasée.
            raise BrainConfigError(REQUEST_INVALID, "« instructions » attend {text, effective_revision} (la révision "
                                   "lue dans le descripteur).", field="instructions")
        descriptor = self.prompts.registry.require(field["prompt_id"])
        with self.graph.write_lock:
            try:
                result = self.prompts.edit(field["prompt_id"], text=raw["text"],
                                           base_revision=descriptor.default_revision,
                                           expected_effective_revision=raw.get("effective_revision"))
            except PromptError as exc:
                raise BrainConfigError(exc.code, _PROMPT_REASONS.get(exc.code, str(exc)), field="instructions") from exc
            except OSError as exc:
                raise BrainConfigError(WRITE_FAILED, f"Instructions non enregistrées ({type(exc).__name__}) ; rien "
                                       "n'a changé.", field="instructions") from exc
        return bool(result["changed"]), field["applies"]

    async def _write_activation(self, brain_id: str, body: Mapping[str, Any], current: Mapping) -> tuple[bool, str]:
        mode = body.get("activation")
        if not isinstance(mode, str) or mode not in TOOL_BRAIN_MODES:
            raise BrainConfigError(ACTIVATION_INVALID, "Activation inconnue : attendu off, shadow ou active.",
                                   field="activation")
        try:
            graph_revision = self.graph.snapshot().revision
            result = self.graph.set_tool_brain_mode(mode, base_revision=graph_revision)
        except ArchitectureGraphError as exc:
            code = {"architecture_revision_stale": REVISION_STALE, "connection_locked": FIELD_LOCKED,
                    "architecture_request_invalid": ACTIVATION_INVALID}.get(exc.code, WRITE_FAILED)
            raise BrainConfigError(code, exc.reason, field="activation") from exc
        return result.changed, current["fields"]["activation"]["applies"]

    async def _write_model(self, brain_id: str, body: Mapping[str, Any], current: Mapping) -> tuple[bool, str]:
        fields = current["fields"]
        if "provider" in body and not fields["provider"]["editable"]:  # pragma: no cover - same rule as model
            raise BrainConfigError(FIELD_LOCKED, fields["provider"]["reason"], field="provider")
        model = body.get("model", fields["model"]["value"]) if brain_id == "core" else body.get("model")
        if not isinstance(model, str):
            raise BrainConfigError(REQUEST_INVALID, "« model » doit être une chaîne (vide : défaut).", field="model")
        model = model.strip()
        if brain_id == "core":
            provider = body.get("provider", fields["provider"]["value"])
            if not isinstance(provider, str) or provider not in cli_catalog.AGENT_CLI_IDS:
                raise BrainConfigError(MODEL_UNAVAILABLE, f"CLI inconnu : {str(provider)[:40]}.", field="provider")
            choices = fields["model"]["choices"]
            if provider != fields["provider"]["value"]:
                if "model" not in body:  # le CLI choisi garde le modèle qui lui est déjà enregistré
                    model = resolve_agent_settings(self.graph.store.read(), provider, environ=self.environ)["model"]
                reader = _CatalogReader(self._catalog)
                choices = _model_choices(await reader.items("subagents", "text"), model, reader, agent_id=provider,
                                         default_label=CLI_DEFAULT_LABEL)
                _require_choice(current, fields["provider"]["choices"], provider, "provider")
            if provider == fields["provider"]["value"] and model == fields["model"]["value"]:
                return False, fields["model"]["applies"]  # avant le catalogue : la valeur en place reste légale
            if model:
                _require_choice(current, choices, model, "model")
            return self._write_settings(current, lambda settings: _store_core(settings, provider, model),
                                        voice=False, field="model"), fields["model"]["applies"]
        stored = fields["model"]["value"]
        if brain_id == "tool_brain" and fields["model"]["source"] == "default":
            stored = ""  # le défaut n'est écrit nulle part
        if model == stored:
            return False, fields["model"]["applies"]  # avant le catalogue : la valeur en place reste légale
        if model:
            _require_choice(current, fields["model"]["choices"], model, "model")
        if brain_id == "tool_brain":
            mutate = lambda settings: _store_tool_brain_model(settings, model)  # noqa: E731
            return self._write_settings(current, mutate, voice=False, field="model"), fields["model"]["applies"]
        if not model:
            raise BrainConfigError(REQUEST_INVALID, "Un modèle vocal est requis.", field="model")
        provider_id = fields["model"]["provider"]
        slot = fields["model"]["owner"].rsplit(".", 1)[1]
        env = self.environ

        def mutate(settings: dict[str, Any]) -> dict[str, Any]:
            selection = decode_voice_architecture(settings[VOICE_ARCHITECTURE_SETTING])
            updated = deepcopy(settings)
            store_voice_architecture(updated, replace(selection.config, **{slot: VoiceModelRef(provider_id, model)}))
            resolve_voice_composition(updated, environ=env)  # la voix doit pouvoir démarrer sur ces réglages
            return updated

        return self._write_settings(current, mutate, voice=True, field="model"), fields["model"]["applies"]

    def _write_settings(self, current: Mapping, mutate: Callable[[dict[str, Any]], dict[str, Any]], *, voice: bool,
                        field: str) -> bool:
        """Lecture-modification-écriture de `control-center-settings.json` sous le verrou du graphe ; révision
        revérifiée sur la lecture faite sous ce verrou (une écriture d'une autre page entre-temps est refusée)."""

        brain_id = current["brain_id"]
        with self.graph.write_lock:
            try:
                settings = self.graph.store.read()
            except (OSError, ValueError) as exc:
                raise BrainConfigError(WRITE_FAILED, f"Réglages illisibles ({type(exc).__name__}) ; rien n'a changé.",
                                       field=field) from exc
            if self._revision(brain_id, settings, self.store.load()) != current["revision"]:
                raise BrainConfigError(REVISION_STALE, "La configuration de ce cerveau a changé pendant l'écriture ; "
                                       "relisez-la.", field=field)
            try:
                updated = mutate(deepcopy(settings))
            except (VoiceConfigError, ConfigurationError) as exc:
                raise BrainConfigError(MODEL_UNAVAILABLE, f"Configuration refusée, rien n'a été écrit : {exc}",
                                       field=field) from exc
            try:
                self.graph.write_settings(settings, updated, voice=voice,
                                          context={"brain_id": brain_id, "field": field})
            except ArchitectureGraphError as exc:
                raise BrainConfigError(WRITE_FAILED, exc.reason, field=field) from exc
        if self._after_settings_write is not None and brain_id == "core":
            try:
                self._after_settings_write(updated)
            except Exception as exc:  # noqa: BLE001 - capture: persisted; the live agents keep their settings
                self._emit("brain_config.apply_failed", "Réglage enregistré, agents vivants non reconfigurés : il "
                           "vaudra au prochain démarrage.", {"code": "brain_config_apply_failed", "brain_id": brain_id,
                                                            "exception_type": type(exc).__name__}, level="error")
        return True

    def _emit(self, kind: str, message: str, data: Mapping[str, object], *, level: str = "info") -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=dict(data))
        except OSError:
            pass  # argued: the journal is evidence, never authority over a committed or refused write


# ------------------------------------------------------------------ helpers

_NO_DELEGATION_REASON = {
    "voice": "La voix ne lance pas de sous-agents : elle confie le travail au cerveau Core (liaison du graphe).",
    "luna": "Luna analyse et souffle des indications ; elle ne lance aucun sous-agent.",
    "tool_brain": "Le Tool Brain décide de l'affichage sans outil de lancement ; il ne lance aucun sous-agent.",
}
_MODE_LABELS = {"off": "Coupé", "shadow": "Observation (n'exécute rien)", "active": "Actif (pilote l'écran)"}
_PROMPT_REASONS = {
    "prompt_override_stale": "Le texte par défaut de ces instructions a changé ; relisez-les avant de les modifier.",
    "prompt_override_concurrent": "Ces instructions ont été modifiées ailleurs depuis votre lecture ; relisez-les.",
    "prompt_read_only": "Ces instructions ne sont pas modifiables.",
}
#: Comment `never` est appliqué, et quand chaque mécanisme prend effet (docs/brain-config.md § 3).
_DELEGATION_ENFORCEMENT = [
    {"mechanism": "routing_hook", "applies": Applies.LIVE.value,
     "detail": "Le hook refuse tout appel Agent du cerveau dès l'appel suivant (fichier relu à chaque appel)."},
    {"mechanism": "cli_disallowed_tools", "applies": Applies.CORE_RESTART.value,
     "detail": "L'outil Agent est retiré au lancement du CLI cerveau ; un job Back Brain le relit à chaque job."},
    {"mechanism": "brain_prompt", "applies": Applies.CORE_RESTART.value,
     "detail": "La consigne du niveau entre dans le prompt d'une conversation neuve ; une conversation reprise garde "
               "le sien."},
]


def _max_override() -> int:
    from jarvis.domain.prompt_registry import MAX_OVERRIDE_TEXT
    return MAX_OVERRIDE_TEXT


def _store_core(settings: dict[str, Any], provider: str, model: str) -> dict[str, Any]:
    """Même forme que `ControlCenter._store_agent` : seul `model` du CLI change, et `agent_cli`."""

    settings["agent_cli"] = provider
    stored = settings.get("agent_cli_settings")
    stored = dict(stored) if isinstance(stored, dict) else {}
    entry = dict(stored.get(provider) or {})
    entry["model"] = model
    stored[provider] = entry
    settings["agent_cli_settings"] = stored
    return settings


def _store_tool_brain_model(settings: dict[str, Any], model: str) -> dict[str, Any]:
    block = settings.get(TOOL_BRAIN_SETTING)
    block = dict(block) if isinstance(block, dict) else {}
    if model:
        block[TOOL_BRAIN_MODEL_FIELD] = model
    else:
        block.pop(TOOL_BRAIN_MODEL_FIELD, None)  # vide = revenir au défaut, sans clé fantôme
    settings[TOOL_BRAIN_SETTING] = block
    return settings


def _require_choice(current: Mapping, choices: list[Mapping[str, Any]], value: str, field: str) -> None:
    choice = next((item for item in choices if item["value"] == value), None)
    if choice is not None and choice["available"]:
        return
    catalog = current.get("catalog") or {}
    if catalog.get("status") != "ok":
        raise BrainConfigError(CATALOG_UNAVAILABLE, catalog.get("reason") or "Catalogue des modèles indisponible : "
                               "aucun choix ne peut être vérifié.", field=field)
    reason = (choice or {}).get("reason") or "Absent du catalogue du serveur pour ce cerveau."
    raise BrainConfigError(MODEL_UNAVAILABLE, f"« {value[:80]} » n'est pas sélectionnable : {reason}", field=field)


class _CatalogReader:
    """Lectures du catalogue d'un même descripteur, avec l'état (`ok` | `unavailable`) et sa raison."""

    def __init__(self, provider: CatalogProvider | None) -> None:
        self._provider = provider
        self._cache: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        self.error = "" if provider is not None else "Catalogue des modèles non branché : disponibilité non mesurée."

    async def items(self, surface: str, role: str) -> list[Mapping[str, Any]]:
        if self._provider is None:
            return []
        key = (surface, role)
        if key not in self._cache:
            try:
                view = await self._provider(surface, role)
                items = view.get("items") if isinstance(view, Mapping) else None
                self._cache[key] = [item for item in items if isinstance(item, Mapping)] if isinstance(items, list) else []
                if not isinstance(items, list):
                    self.error = f"Catalogue {surface}/{role} mal formé : disponibilité non mesurée."
            except Exception as exc:  # noqa: BLE001 - capture: the descriptor stays readable without the catalog
                self._cache[key] = []
                self.error = f"Catalogue des modèles indisponible ({type(exc).__name__}) : disponibilité non mesurée."
        return self._cache[key]

    def status(self) -> dict[str, str]:
        return {"status": "unavailable" if self.error else "ok", "reason": self.error}


#: État du catalogue d'un CLI détecté dont le modèle par défaut et l'authentification ne sont pas invoqués
#: (`catalog_view`, jamais `selectable` : seul un modèle listé par le compte l'est). Pour le choix du CLI et pour
#: « défaut du CLI », c'est un choix **légal** (le comportement d'avant cette fenêtre) : constat de la Slice 08 en
#: bac à sable, sans quoi Codex détecté ne pouvait pas être choisi et le CLI qui tourne se disait « indisponible ».
UNVERIFIED_STATE = "configured_unverified"
UNVERIFIED_REASON = "CLI détecté ; son modèle par défaut et son authentification ne se vérifient qu'à l'usage."


def _legal_when_detected(choice: dict[str, Any]) -> dict[str, Any]:
    if choice.get("state") == UNVERIFIED_STATE and not choice["available"]:
        return {**choice, "available": True, "reason": UNVERIFIED_REASON}
    return choice


def _choice(item: Mapping[str, Any]) -> dict[str, Any]:
    identity = item.get("identity") or {}
    availability = item.get("availability") or {}
    return {"value": str(identity.get("model_id") or ""), "label": str(item.get("label") or identity.get("model_id")),
            "provider_id": identity.get("provider_id"), "agent_id": identity.get("agent_id"),
            "available": availability.get("selectable") is True, "state": availability.get("state"),
            "reason_code": availability.get("reason_code") or "", "reason": availability.get("reason") or ""}


def _model_choices(items: list[Mapping[str, Any]], current: str, catalog: _CatalogReader, *,
                   agent_id: str | None = None, provider_id: str | None = None,
                   default_label: str = "") -> list[dict[str, Any]]:
    """Choix du catalogue serveur pour ce cerveau ; la valeur enregistrée absente reste visible, avec sa raison."""

    choices = []
    for item in items:
        identity = item.get("identity") or {}
        if agent_id is not None and identity.get("agent_id") != agent_id:
            continue
        if provider_id is not None and identity.get("provider_id") != provider_id:
            continue
        choice = _choice(item)
        if not choice["value"]:
            if not default_label:
                continue
            choice["label"] = default_label
            choice = _legal_when_detected(choice)
        choices.append(choice)
    if default_label and not any(choice["value"] == "" for choice in choices):
        # Le défaut (aucune clé enregistrée) est toujours un choix légal : il revient au comportement d'avant.
        choices.insert(0, {"value": "", "label": default_label, "provider_id": provider_id, "agent_id": agent_id,
                           "available": True, "state": "default", "reason_code": "", "reason": ""})
    if current and not any(choice["value"] == current for choice in choices):
        choices.append({"value": current, "label": current, "provider_id": provider_id, "agent_id": agent_id,
                        "available": False, "state": "unlisted", "reason_code": "brain_config_model_unlisted",
                        "reason": catalog.error or "Valeur enregistrée absente du catalogue du serveur : elle reste "
                                                   "appliquée, mais ne peut pas être choisie à nouveau ici."})
    return choices


def _cli_choices(items: list[Mapping[str, Any]], current: str, catalog: _CatalogReader) -> list[dict[str, Any]]:
    choices = []
    for spec in cli_catalog.AGENT_CLIS:
        entry = next((item for item in items if (item.get("identity") or {}).get("agent_id") == spec.id
                      and not (item.get("identity") or {}).get("model_id")), None)
        if entry is None:
            choices.append({"value": spec.id, "label": spec.label, "available": False,
                            "reason": catalog.error or "CLI non mesuré par le catalogue."})
            continue
        choice = _legal_when_detected(_choice(entry))
        choices.append({"value": spec.id, "label": spec.label, "available": choice["available"],
                        "reason": choice["reason"]})
    del current
    return choices


def _connections(snapshot: ArchitectureSnapshot, node: Node) -> dict[str, Any]:
    """Résumé en lecture seule des liaisons du cerveau ; leur édition reste sur le graphe (un seul écrivain)."""

    def view(conn, peer: str) -> dict[str, Any]:
        data = conn.to_dict()
        return {key: data[key] for key in ("id", "channel", "purpose", "enabled", "mutability", "locked_reason",
                                           "applies", "pending", "governed_by")} | {"peer": peer}

    return {"graph_revision": snapshot.revision, "edit_on": "graph",
            "incoming": [view(conn, conn.source.node) for conn in snapshot.connections if conn.target.node == node.id],
            "outgoing": [view(conn, conn.target.node) for conn in snapshot.connections if conn.source.node == node.id]}
