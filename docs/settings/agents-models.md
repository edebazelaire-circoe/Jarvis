# Réglages : Brains & Architecture et ses destinations

**Statut :** contrat de surface (niveau 3 : sections enregistrées + tests de conformité).
**Introduit :** tâche `jarvis-settings-ui-reorganization`, Slice 04.
**S'appuie sur :** [`navigation-registry.md`](navigation-registry.md) (sections réservées), [`settings-shell.md`](settings-shell.md)
(montage d'une section), [`INDEX.md`](INDEX.md) (contrat backend Agent / CLI, inchangé),
[`../subagent-roles.md`](../subagent-roles.md) § 8 (écran des rôles), [`../work-methods.md`](../work-methods.md) (promotion).

- Sections : `control_center.html` (`AGENT_SECTIONS`, `agentSectionSpec`, `SUBAGENT_SECTIONS`, `subagentSectionSpec`,
  `installAgentSettingsSections`), `control_center_subagents_settings.js` (`create(host, {view})`, vues `roles` et
  `work_methods`).
- Conformité : `tests/unit/test_agent_cli_settings_ui.py` (charge figée clé par clé, champs répartis entre Agent principal
  et Runtime & CLI, cycle de vie du catalogue), `tests/unit/test_routing_settings_screen.py`,
  `tests/unit/test_control_center_subagents_settings_js.py` (vues, conflits de révision, promotion),
  `tests/unit/test_control_center_settings_registry_js.py` (alias), `tests/unit/test_agents_models_settings_browser.py`
  (vrai Chrome : sections, alias, enregistrement et relecture, débordement).

## 1. Ce que voit un utilisateur ordinaire

`agents_models` (Brains & Architecture) n'a plus d'onglet `Agent / CLI` ni `Sous-agents` : quatre sections orientées tâche.

| Section | Contenu | Enregistrement |
| --- | --- | --- |
| `main_agent` · Agent principal | le CLI piloté (Claude Code, Codex…) avec sa version, l'état de sa clé et sa disponibilité ; le modèle principal de ce CLI (catalogue du fournisseur, `/api/models`) ; renvoi vers Runtime & CLI | pied « Enregistrer » |
| `agent_behavior` · Comportement | longueur des réponses, politesse/formalité (métadonnées `cli.behavior.fields`), rappels de rendez-vous (`agenda_reminders`) | pied « Enregistrer » |
| `subagent_models` · Modèles des sous-agents | mode des sous-agents Auto / Dupliqué (`cli.delegation_mode_metadata`), inventaire comparatif `JarvisCatalog` (`surface=subagents`, `role=subagent`), renvoi vers Runtime & CLI pour les profils | pied « Enregistrer » |
| `subagents` · Rôles des sous-agents | liste des rôles, identité, mission, quand l'employer, capacités (lecture seule), Work Methods (lecture seule), ordre de la consigne, instructions éditables, instances en cours (repliées) ; renvoi vers Work Methods apprises pour un rôle porteur de mission | la section s'enregistre (`save: 'self'`) |

- Les trois premières écrivent dans le brouillon partagé `SET.draft` : « Enregistrer » envoie `/api/settings` exactement
  comme l'ancien onglet (`cli={agent,settings,delegation_mode,behavior}`, `routing={profiles}`, plus `voice`, `audio`,
  `agenda_reminders` ; `test_agent_cli_save_payload_is_frozen_key_by_key`). Le brouillon survit aux changements de
  section et de catégorie.
- Le modèle principal reste le sélecteur alimenté par le catalogue du fournisseur ; l'inventaire comparatif reste
  l'unique `JarvisCatalog` : aucune seconde liste de modèles. Son contrôleur est créé au montage de Modèles des
  sous-agents et détruit par son `destroy` (changement de section, de catégorie, fermeture).
- Les rôles : lecture `GET /api/subagent-roles` et `GET /api/agent/tasks` ; seule écriture, les instructions, par la
  voie canonique des prompts (`subagent_role.<id>`, `base_revision` + `expected_effective_revision`, conflit
  `prompt_override_concurrent` / `prompt_override_stale` : texte gardé, révisions relues). Brouillons dans
  `SET.subagentDrafts`, d'une section à l'autre.
- `subagents` est l'ID même de la section des rôles ; l'ancien ID `cli` n'est plus un alias depuis la Slice 09.

## 2. Ce qui part dans Avancé & Diagnostics

| Section | Groupe | Contenu | Enregistrement |
| --- | --- | --- | --- |
| `runtime_cli` · Runtime & CLI | `runtime_cli` | commande et chemin résolu du CLI choisi, « re-détecter » (enregistre puis relance la sonde), mode d'autorisation / bac à sable ; « Configuration avancée des sous-agents » : profils actifs, candidats ordonnés (harness puis modèle), recours au profil Général, source des listes de modèles | pied « Enregistrer » |
| `work_methods` · Work Methods apprises | `labs` | approches observées dans les missions closes (`GET /api/work-methods/candidates`), un bloc par rôle porteur de mission, promotion explicite confirmée en deux temps (`POST /api/work-methods/promotions`) | la section s'enregistre |

- La configuration avancée n'est demandée au serveur (`/api/routing/candidates`) qu'à l'ouverture de sa divulgation ;
  elle reste ouverte quand la section est remontée (enregistrement), se referme quand on quitte Runtime & CLI.
- L'ancien ID `routing` (et sa redirection historique vers `cli`) n'est plus un alias depuis la Slice 09.
- **Pourquoi la promotion va dans Avancé.** [`../subagent-roles.md`](../subagent-roles.md) § 1bis et § 8 : « capacités et
  méthode par défaut suivent le code » ; la seule écriture d'un rôle est ses instructions, la promotion est une « autre
  écriture », « explicite » ; [`../work-methods.md`](../work-methods.md) : « la promotion est un acte explicite, jamais un
  effet de bord », faite à partir de l'historique des missions. Aucun document ne la classe comme configuration ordinaire
  d'un rôle : c'est un outil d'opérateur (`docs/07-target-settings-map.md`, Labs).
- La Slice 08 regroupe les sections d'Avancé ; ces deux identifiants et leurs groupes sont stables.

## 3. Table de correspondance réglage → section

| Réglage (clé de la charge ou route) | Destination |
| --- | --- |
| `cli.agent` | `agents_models` › `main_agent` |
| `cli.settings[<CLI>].model` | `agents_models` › `main_agent` |
| `cli.settings[<CLI>].command` | `advanced_diagnostics` › `runtime_cli` |
| `cli.settings[<CLI>].permission_mode` | `advanced_diagnostics` › `runtime_cli` |
| re-détection (`/api/cli/agents`) | `advanced_diagnostics` › `runtime_cli` (état et version aussi dans `main_agent`) |
| `cli.behavior.response_verbosity` | `agents_models` › `agent_behavior` |
| `cli.behavior.politeness_formality` | `agents_models` › `agent_behavior` |
| `agenda_reminders.*` | `agents_models` › `agent_behavior` |
| `cli.delegation_mode` | `agents_models` › `subagent_models` |
| catalogue des modèles de sous-agents (`JarvisCatalog`) | `agents_models` › `subagent_models` |
| `routing.profiles` (actif, candidats, recours) | `advanced_diagnostics` › `runtime_cli` |
| instructions d'un rôle (`subagent_role.<id>`) | `agents_models` › `subagents` |
| promotion d'un candidat de Work Method | `advanced_diagnostics` › `work_methods` |

`delegation_mode` est placé avec les modèles des sous-agents, non dans Comportement (`docs/07` le citait sous
Behavior « when user-facing ») : c'est l'interrupteur qui fait appliquer ou non les profils de candidats ; il sert au
choix du modèle d'un sous-agent, pas au ton des réponses. Les rappels de rendez-vous, absents de `docs/07`, suivent
l'onglet qui les portait : Comportement, puisqu'ils règlent ce que JARVIS fait de lui-même.
