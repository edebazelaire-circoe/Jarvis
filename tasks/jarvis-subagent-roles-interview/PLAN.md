# MVP Sous-agents & Mode Interview — plan

## Contexte
Aujourd'hui le cerveau (CLI Claude Code permanent, `BRAIN_SYSTEM_PROMPT`, `jarvis/runtime/claude_local.py:80`) délègue tout travail long par l'outil `Agent`. Il a une seule consigne sur le flou : « tranche en une question courte ». Il n'existe ni registre de rôles, ni classification du type de demande, ni Intervieweur. Le résultat : JARVIS part trop vite dans une exécution longue.

L'existant à étendre :
- les marqueurs `[profil] [rôle]` lus par le hook `PreToolUse` (`jarvis/runtime/routing_hook.py`) ;
- la méthode de rôle apposée d'office sur la consigne, comme pour `presentation_playbooks.with_playbook` (`presentation_playbooks.py:149`) ;
- le suivi des instances, `AgentTaskTracker` (`agent_tasks.py`), exposé par `/api/agent/tasks` et `/api/work` ;
- les surcharges de prompts versionnées, `PromptOverrideStore` (`jarvis/runtime/prompt_overrides.py`, route `POST /api/prompts/{id}`).

Vos décisions :
1. Quand l'Intervieweur juge le cadrage prêt, il rend « PRÊT ». Le cerveau résume alors en une phrase et demande votre accord oral. La politique vit à un seul endroit pour la changer plus tard (§17 reste ouvert).
2. Un nouvel onglet Settings « Sous-agents » montre les rôles et, à part, les instances actives.
3. Les instructions des rôles sont modifiables et persistées.

Travail dans un worktree dédié `subag`, branche `task/jarvis-subagent-roles-interview`, depuis `main`. Pas de migration SQLite : aucune donnée nouvelle n'a besoin de survivre en base.

## 1. Registre des rôles (source unique)
Nouveau module pur `jarvis/domain/subagent_roles.py`. Il contient un `SubagentRole` figé avec les champs suivants :
- `id` / `marker` ;
- `name`, `description`, `mission`, `instructions` (prompt initial) ;
- `skills`, `tools`, `when_relevant` ;
- `default_profile`, `enabled`.

Les 5 rôles, avec des marqueurs ASCII compatibles avec `_BRACKET` :

| Rôle | Marqueur | Profil | Lien existant |
|---|---|---|---|
| Intervieweur | `interviewer` | general | nouveau |
| Recherche documentaire | `research` | general | rôle de loadout existant, conservé |
| Recherche web | `web-research` | general | nouveau |
| Développement | `coder` | code | rôle de loadout existant, conservé |
| Conceptualisation | `concept` | general | nouveau |

API du module :
- `ROLES` ;
- `role_for(marker)` ;
- `with_role_instructions(prompt, marker, overrides)`, calqué sur `with_playbook`, avec une marque anti-doublon ;
- `brain_rules(roles)`, qui génère la section du prompt cerveau.

Instructions de l'Intervieweur (le cœur du MVP) :
- lire d'abord le dossier de mission ;
- ne jamais reposer une question déjà répondue ou déductible ;
- poser une seule question à la fois ;
- terminer chaque tour par `QUESTION : …` ou par `PRÊT : <cahier des charges>` ;
- ne rien produire de livrable.

## 2. Dossier de mission : le contexte partagé d'une tâche
Chaque tâche cadrée a un dossier de mission, `<mémoire du Board>/missions/<slug-date>/mission.md`. Il contient l'intention, les échanges questions/réponses et les apports des autres agents (marqués dit / trouvé / déduit, comme dans le skill jarvis-presentation).
- Le cerveau le crée au lancement et passe son chemin à chaque instance.
- Les agents de recherche et de conceptualisation y ajoutent leurs trouvailles.
- L'Intervieweur le relit à chaque tour.

C'est ce qui couvre les critères 5, 6 et 8 :
- le contexte est propre à la mission ;
- l'enrichissement se fait en parallèle ;
- les instances ne se mélangent pas, puisque deux interviews ont deux dossiers.

L'état vit dans le fichier. L'interview survit donc aussi bien à une reprise par `SendMessage` (outil déjà listé dans `DELEGATION_TOOLS`, `claude_local.py:471`) qu'à une relance d'un nouvel Intervieweur si la reprise échoue.

## 3. Injection par le hook
- `routing_hook._markers` / `read_role` : reconnaître aussi les marqueurs du registre, pas seulement `LOADOUT_ROLES` et `PLAYBOOK_ROLES`.
- `charter_input` : après `with_playbook`, apposer `with_role_instructions` (texte effectif = surcharge, sinon défaut du code).
- Le hook reste pur et sans réseau. Les surcharges effectives sont écrites dans un instantané `runtime/subagent-roles.json` (pattern de `loadout_snapshot.py`) :
  - à l'enregistrement d'une édition ;
  - au lancement du CLI.

  Si l'instantané est illisible, le hook prend les défauts du code.
- Le hook émet un événement de journal `agent.role_applied` (rôle, profil), pour l'observabilité et l'analyse de trace.

## 4. Cerveau : raisonner en type de demande
Dans `BRAIN_SYSTEM_PROMPT`, ajouter une section « TYPE DE DEMANDE », générée par `subagent_roles.brain_rules()`. Elle remplace la puce « quand sa demande peut se lire de deux façons » (l.92) et `PROFILE_RULE` reste en place.
- **A. Action claire** : un seul agent du rôle adapté, par exemple `[code] [coder]` pour un bug. Pas d'Intervieweur.
- **B. Intention à cadrer** : création, livrable important, résultat attendu flou.
  - Créer le dossier de mission.
  - Lancer `[general] [interviewer]` en arrière-plan.
  - Si utile, lancer en parallèle `[general] [research]`, `[general] [web-research]` ou `[general] [concept]`, chacun avec le chemin du dossier.
  - Relayer chaque `QUESTION :` en une phrase.
  - Renvoyer la réponse à l'Intervieweur par `SendMessage`, ou le relancer avec le dossier.
  - Quand une trouvaille arrive, la signaler à l'Intervieweur au prochain tour.
- **C. Expertises complémentaires** : plusieurs rôles en parallèle, puis agrégation progressive dans le dossier de mission.
- **Passage à l'exécution** : sur `PRÊT :`, résumer le cahier des charges en une phrase et demander « je lance ? ». Ne lancer l'exécution qu'après votre oui. La règle est isolée dans une constante `EXECUTION_GATE_RULE` pour être remplaçable.
- La règle présentation existante (`PRESENTATION_PRODUCTION_RULE`) n'est pas touchée : une demande de vidéo floue passe d'abord par le cas B, puis par la production habituelle.

⚠ Le CLI garde l'instantané du prompt système (`claude_local.py:75-79`). Le nouveau comportement ne sera actif sur le JARVIS vivant qu'après un redémarrage, que vous ferez vous-même.

## 5. Instances observables
- `AgentTaskTracker` (`agent_tasks.py`) : ajouter `role` (lu par `routing_hook.read_role` sur la description) au snapshot de tâche.
- Le champ `role` est exposé dans `/api/agent/tasks`, et dans `/api/work` si `WorkItem` porte déjà des métadonnées libres ; sinon seulement dans `/api/agent/tasks`.
- Une instance est donc : rôle + description (mission) + statut + durée + trace existante.

## 6. Settings > onglet « Sous-agents »
**Backend Control Center (`control_center.py`) :**
- `GET /api/subagent-roles` : le registre, avec pour chaque rôle le texte d'instructions effectif, sa révision et un indicateur `modified`.
- L'édition passe par le registre de prompts. Chaque rôle est déclaré `subagent_role.<id>` dans `default_prompt_registry()` (`prompt_catalog.py:119`), ce qui réutilise tel quel `POST /api/prompts/{id}` (édition, réinitialisation, révision optimiste).
- Après une mutation, réécrire `subagent-roles.json`.
- Ajouter la route à `READ_GUARDED_ROUTES` si les prompts y sont.

**Front :** module `jarvis/runtime/control_center_subagents_settings.js`.
- Pattern de `control_center_memory_settings.js` : IIFE, `create(host,{fetch})`, injecté par marqueur (`control_center.py:767`, boucle `2515-2521`).
- Onglet ajouté à `TABS` (`control_center.html:4028`), monté depuis `renderTab`.
- Mise en page :
  - à gauche, la liste des rôles en cartes (nom, description, puces skills et outils, badge statut ou « modifié ») ;
  - à droite, le détail structuré en sections Mission / Quand l'utiliser / Skills / Outils / Instructions. Les instructions s'éditent dans une zone de texte avec Enregistrer / Rétablir le défaut ;
  - en dessous, une zone « Instances actives » distincte, alimentée par `/api/agent/tasks` (polling seulement quand l'onglet est visible) : rôle, mission, statut, durée.
- Uniquement des tokens `--shell-*` / `--sem-*`, les deux skins, clavier et accessibilité. Passe de design avec le skill `impeccable`.

**Docs :**
- `docs/settings/INDEX.md` ;
- nouvelle page `docs/subagent-roles.md` : rôles et instances, dossier de mission, flux A/B/C, §17 toujours ouvert ;
- renvoi depuis `docs/skills-and-loadouts.md`.

## Fichiers clés
- Nouveaux :
  - `jarvis/domain/subagent_roles.py` ;
  - `jarvis/runtime/subagent_roles_snapshot.py` ;
  - `jarvis/runtime/control_center_subagents_settings.js` ;
  - `docs/subagent-roles.md`.
- Modifiés :
  - `jarvis/runtime/routing_hook.py` ;
  - `jarvis/runtime/claude_local.py` (prompt cerveau, écriture de l'instantané au lancement) ;
  - `jarvis/runtime/agent_tasks.py` ;
  - `jarvis/runtime/prompt_catalog.py` ;
  - `jarvis/runtime/control_center.py` ;
  - `jarvis/runtime/control_center.html`.

## Vérification
1. **Unitaires** (en avant-plan, par petits lots) :
   - registre : marqueurs valides et uniques, `with_role_instructions` idempotent ;
   - hook : apposition par rôle, surcharge et repli sur les défauts, cohabitation avec la charte et le playbook ;
   - `brain_rules` présent dans le prompt ;
   - `role` dans le snapshot du tracker ;
   - route API, édition et réinitialisation via `/api/prompts`, réécriture de l'instantané ;
   - test node `test_control_center_subagents_settings_js.py` (modèle : `test_control_center_memory_settings_js.py`).
2. **Navigateur** : `_subagents_settings_browser.mjs` piloté depuis Python (modèle : `test_wake_word_settings_browser.py`), sur les deux skins, au clavier, avec captures.
3. **Non-régression** : balayage large de `tests/unit` sur le hook, le routage, les présentations, les prompts et le Control Center.
4. **Essai réel en bac à sable**, jamais sur le JARVIS vivant. On lance `python -m jarvis core|control-center` depuis le worktree, avec `JARVIS_DATA_ROOT` et le répertoire runtime dans le scratchpad, `CORE_PORT 27653`, `UI_PORT 27654` et `VISUALIZER_ENABLED=0`, puis :
   - chat texte « Il y a un bug sur ce bouton, corrige-le » : un seul `[code] [coder]`, pas d'Intervieweur ;
   - « Je voudrais faire une belle vidéo » : dossier de mission créé, Intervieweur avec deux ou trois questions successives qui tiennent compte des réponses, une recherche en parallèle dont la trouvaille change la question suivante, puis `PRÊT` et une demande d'accord sans lancement automatique.

   Les traces sont analysées avec le skill `agent-trace-analysis` (journal `agent.role_applied`, consignes signées). L'onglet Sous-agents est contrôlé pendant l'essai : instances actives avec leur rôle.
5. Après approbation : merge de `origin/main` dans la branche, puis remise à vous pour le merge dans `main`. Redémarrage de JARVIS par vous.
