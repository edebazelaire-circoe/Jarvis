# 10 - Slice 00 audit and plan corrections

Audit d'agent 0 sur `main` @ `ad1e7f4d` (2026-10-23), branche `task/jarvis-architecture-agents-settings-editor`,
worktree `C:\Projects\jarvis\arch`. Deux explorations en lecture seule ont rassemblé les preuves (chemin:ligne) ;
les décisions ci-dessous sont celles d'agent 0. Aucun code produit n'a été modifié, aucun test lancé.

**Readiness : `READY`** (avec les corrections C1-C10, qui ne touchent aucune décision verrouillée).

## Faits établis

### Réglages

- Catégories figées dans `control_center_settings_registry.js:24-33`. L'id `agents_models` porte le libellé
  « Brains & Architecture » depuis `ad1e7f4d` (12:07). Le registre refuse une 7e catégorie.
- Sections actuelles de `agents_models` (`control_center.html:5307-5367`) : `main_agent` (CLI + modèle),
  `subagent_models` (select Auto/Dupliqué + catalogue `surface=subagents`), `subagents` (rôles,
  `control_center_subagents_settings.js`, 657 lignes). Le routage par profil est dans `runtime_cli`
  (Avancé, `#routingAdvanced`), `architecture_compat` (architecture vocale) aussi.
- Modules JS injectés par marqueurs dans `index()` (`control_center.py:463-817`, `2643-2648`) : un nouveau
  module = un marqueur + une entrée `index()` (Slice 07). Navigation par `openSettingsTab` / `openSettingsLink`,
  `data-settings-open`/`data-settings-focus` ; un seul alias hérité (`memory`).
- Endpoints existants : `GET/POST /api/settings` (fichier `<runtime>/control-center-settings.json`, écriture
  atomique, **sans révision**), `/api/models`, `/api/routing/candidates`, `/api/catalog`, `/api/cli/agents`,
  `GET /api/subagent-roles`, `POST /api/prompts/{id}` (révisions optimistes `prompt_override_stale|concurrent`).

### Rôles et routage

- 7 rôles actifs (`subagent_roles.py:367-478`) + alias `reviewer -> qa` : conforme au handoff.
- `default_profile` n'est **pas** utilisé par le routage : le hook (`routing_hook.decide`, `:307-349`) lit le
  profil écrit en tête de la description (`[code]`, `[general]`…), hôte `claude` seulement, hors ligne
  (`model-catalog.json`). Profils : `desktop`, `code`, `fast`, `general` (`routing.py:56-80`).
- `delegation_mode` = projection de `agent_routing.enabled` (défaut false = duplicate) ; il choisit un modèle,
  n'interdit rien.

### Topologie réelle

Le graphe dépend de l'architecture vocale effective (`voice_architecture_config.py:151-182`) :
`voice_architecture` ∈ {simple, front_brain, duplex} l'emporte, sinon `voice_arch` ∈ {legacy, continuous_brain}
(défaut code `legacy`). Le poste de l'utilisateur est vraisemblablement en `duplex` (`gpt-live-1`,
`brain_orchestration=true`).

Nœuds réels : Micro (entrée audio, + mot d'éveil), Surface vocale (Realtime ou Live, process Voice),
Front Brain « Luna » (seulement `front_brain`), Core Brain (BrainOrchestrator + CLI cerveau du Control Center,
`board_brains.py`, + Back Brain Job Worker), Tool Brain (`JARVIS_TOOL_BRAIN` off|shadow|active, défaut off,
**aucun réglage d'interface**, modèle `JARVIS_TOOL_BRAIN_MODEL`, Claude seulement), Sous-agents CLI (outil
`Agent` + hook), Haut-parleurs (sortie : la surface dit le texte du cerveau ; pas de TTS séparé en v0.2).

Liaisons et mutabilité prouvées :

| Liaison | Canal | Interrupteur aujourd'hui | Verdict |
| --- | --- | --- | --- |
| Micro → Surface vocale | audio | aucun | `required_locked` |
| Surface vocale → Haut-parleurs | audio | aucun | `required_locked` |
| Micro → Mot d'éveil | audio | bloc `wake_word` | basculable (réglage existant, hors page) |
| Surface Live → Core (`brain-turns`) | requête texte | `voice_architecture.config.brain_orchestration` | `toggleable` (off = job spéculatif sans outils) |
| Surface continue → Core | requête texte, chaque tour | aucun dans le mode | `required_locked` |
| Surface simple/front → Core (job `back_brain_delegate`) | appel d'outil | aucun (outil toujours fourni) | à rendre `toggleable` (C4) |
| Surface legacy → Control Center (`claude_task`) | appel d'outil | architecture | projeté, `required_locked` dans le mode |
| Transcriptions → Luna | analyse | architecture, `speculative_deltas` | projeté avec l'architecture |
| Core → Voice (parole `brain.speech.requested`) | événement | indirect seulement | `required_locked` |
| Core → Tool Brain (réveils, intentions UI) | événement | `JARVIS_TOOL_BRAIN` (env) | `toggleable` après promotion en réglage (C5) |
| Tool Brain → écran | appel d'outil | `active` seulement | dérivé de l'état du Tool Brain |
| Core → Sous-agents | outil `Agent` | **aucun** | gouverné par la tendance de délégation (C6) |

Mission : n'existe que pour les sous-agents. Prompts éditables par cerveau : `voice.conversation.addition`,
`front_brain.analysis.addition`, `live.duplex.addition`, `backend.system.addition`/`backend.turn.addition`.
`BRAIN_SYSTEM_PROMPT` (« dans le doute, délègue ») est en lecture seule ; le prompt du Tool Brain n'est pas au
catalogue. Le Back Brain worker fige ses réglages CLI au démarrage de Core (`app.py:819-829`).

## Corrections du plan

- **C1 - L'ancienne Slice 04 est déjà livrée.** `jarvis-settings-ui-reorganization` S04 est approuvée et dans
  `main` (`b0b53b51`). Rien à bloquer ; la Slice 07 de cette tâche **remplace** les sections `main_agent`,
  `subagent_models`, `subagents` par la page à deux onglets et garde `runtime_cli` / routage par profil /
  `architecture_compat` / `work_methods` dans Avancé. Consigné dans le LOG de la tâche liée.
- **C2 - Nom de la catégorie.** L'id `agents_models` ne change pas (ids figés). Son libellé passe de
  « Brains & Architecture » à « Architecture & Agents » : le handoff (12:41) est postérieur au renommage du hub
  (12:07) et D01 le verrouille. Slice 07.
- **C3 - Graphe par architecture vocale.** Le snapshot (Slice 01) projette l'architecture vocale effective ;
  il ne montre que les nœuds réels de ce mode (Luna seulement en `front_brain`). Changer d'architecture reste
  dans Avancé (`architecture_compat`) ; le graphe l'indique en lecture seule avec un lien.
- **C4 - Voix seule en simple/front_brain.** Slice 01 ajoute un réglage canonique qui retire l'outil
  `back_brain_delegate` de la surface (liaison Surface → Core `toggleable`) : la voix traite alors seule,
  l'exemple exact du grill. En duplex la même liaison s'appuie sur `brain_orchestration`.
- **C5 - Tool Brain.** Slice 01 promeut `JARVIS_TOOL_BRAIN` (et Slice 02 `JARVIS_TOOL_BRAIN_MODEL`) en réglage
  persistant ; une variable d'environnement posée garde la priorité et rend la liaison `required_locked` avec
  la raison « imposé par l'environnement ». Le nœud Tool Brain est affiché même `off` (état inactif), il
  existe réellement (D11).
- **C6 - Core → Sous-agents.** La liaison est montrée, en lecture seule sur le graphe, « gouvernée par la
  tendance de délégation » avec un lien vers la fenêtre du cerveau. Un seul écrivain : le champ de délégation
  de Slice 02. `never` doit réellement retirer la capacité de lancer des agents (outil/hook), pas seulement le
  prompt.
- **C7 - Application différée.** Toute mutation déclare `applies: live | next_turn | core_restart`. Une
  mutation à effet au redémarrage est acceptée, persistée et affichée « effective au prochain démarrage de
  Core » ; aucun agent ne redémarre JARVIS (CLAUDE.md). Les preuves runtime passent par un bac à sable.
- **C8 - Révisions.** `/api/settings` n'a pas de révision : les nouveaux stores (topologie, config cerveau,
  politique de rôles) portent une révision et refusent une écriture périmée (`409` + code stable), sans
  réécrire tout le brouillon de `/api/settings`.
- **C9 - Routage par rôle.** Le hook résout aujourd'hui un profil ; Slice 03 ajoute la résolution par rôle
  (marqueur de rôle déjà présent dans la description) avec héritage du profil `default_profile`, puis du
  profil annoncé, sans perdre la politique par profil existante.
- **C10 - Commandes globales de la maquette.** Seul « repli automatique » a un réglage réel
  (`allow_general_fallback`). Analyse d'intention, charge, validation, coût, délai, collaboration : omis.

## Recoupements actifs

- Le checkout principal porte un travail non commité de Personnalisation (`control_center.html/.py`,
  `agent_behavior.py`) et `eph` (tâches éphémères) touche `control_center.html` : la Slice 07 merge `main`
  au début et à la fin.
- `tests/unit/test_agents_models_settings_browser.py:55` attend encore « Comportement » dans `agents_models` :
  probablement déjà rouge sur `main` ; à constater en Slice 08, pas à imputer.

## Task Types et routage des agents

Le vocabulaire Workspace Task Type n'est toujours pas exposé : levé par `waived-by-agent-0`, précédents
`jarvis-organic-agent-orchestration` et `jarvis-settings-ui-reorganization`. Agents Claude pour tout
(front compris).

## Dispatch

Machine limitée (≤ 3 agents, tests par petits lots) : le lot prêt part en deux vagues, chaque Slice dans son
worktree issu de la branche de tâche, fusionnée par agent 0.

- Vague A : 01 (graphe runtime), 03 (routage par rôle), 04 (canevas UI sur fixtures du contrat).
- Vague B : 02 (config cerveau, après 01 pour les ids), 05 (fenêtre cerveau), 06 (onglet Sous-agents).
- Puis 07 → 08.
