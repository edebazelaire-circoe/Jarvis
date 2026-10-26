# QA code-review — Slice 04 (confinement des agents)

Relecteur : agent QA « code-review », 2026-10-26. Branche `task/jarvis-presentation-edition-v1` @ `5484d8e4`.
Périmètre : `git diff cf3f7e44..5484d8e4` (4 commits S04 ; aucun merge S05 dans cet intervalle).
Aucun code produit modifié. Le JARVIS vivant n'a été ni lancé ni arrêté, et aucune base n'a été touchée.

## Verdict : PASS avec un MAJEUR (aucun BLOQUANT)

La frontière de sécurité tient : en `presentation`, les lancements sont confinés par la CLI elle-même, et une valeur enregistrée ne peut pas l'élargir. L'édition `full` est identique octet pour octet (argv, cwd, consigne). Le seul écart majeur porte sur la consigne et les méthodes des rôles de sous-agents : elles prescrivent encore des écritures de fichiers et du code que l'édition retire.

## Preuves observées

- **`full` identique octet pour octet** : un script (`scratchpad/argv_dump.py`) lance un `ClaudeLocalAgent` avec un faux `create_subprocess_exec` depuis l'arbre `cf3f7e44` (via `git archive`) et depuis HEAD, pour le profil `conversation` (console, passerelle, contexte global, Boards, `--add-dir`) et le profil `job_result`. La comparaison porte sur l'argv, le cwd, la consigne (`--append-system-prompt-file`, 19 632 caractères) et les fichiers runtime écrits : tout est identique, aux horodatages près. Le snapshot gagne seulement la clé `confined`.
- **Argv de `presentation`** (même script) : on y trouve `--restricted --strict-mcp-config --disable-slash-commands --permission-prompts none --tools Read,Glob,Grep,WebSearch,WebFetch,Agent,ToolSearch,TaskStop,SendMessage --allowedTools …,mcp__jarvis-console,mcp__jarvis-tools --disallowedTools Bash,PowerShell,…`, ainsi que `--permission-mode dontAsk`. Il n'y a pas de `--chrome`. Le cwd vaut `<runtime>/agent-workdir` et les `--add-dir` sont `sessions`, `CONTEXT_GLOBAL`, `boards`, `local_capabilities` et `scene-captures`. `job_result` est confiné de la même façon (sans MCP ni `--add-dir`).
- **CLI installée 2.1.310** (`claude --help`) : `--restricted`, `--tools`, `--disallowedTools`, `--permission-prompts` et `--strict-mcp-config` existent bien, avec la sémantique documentée.
- **Traces réelles** relues (`<scratchpad c414c0a5>/s04i/evidence/b-summary.txt`) : à l'init du cerveau, les outils sont Task, Glob, Grep, Read, SendMessage, ToolSearch, WebFetch, WebSearch et des MCP `jarvis-*` uniquement. Un sous-agent qui cherche Write, Edit, Bash ou PowerShell par ToolSearch ne trouve rien, et les refus sont expliqués à l'utilisateur. Réserve : `jarvis-tools` était hors ligne pendant la série b.
- **Tests exécutés** (en avant-plan, par lots, avec le `.venv` du dépôt principal) :
  - `test_agent_capabilities`, `test_product_edition`, `test_global_context` : 77 réussis ;
  - CLI settings, back brain, brain_config, codex, self_dev, settings_mcp, brain_delegation : 235 réussis ;
  - debug console, argv limit, passerelle, control center mvp/prompts, board brains, voice_to_claude : 121 réussis ;
  - routing hook, subagent roles, passerelle MCP, prompt registry, board brains readiness/rework : 231 réussis ;
  - `test_app`, `test_brain_capability_parity`, `test_product_connectors` : 143 réussis, 2 échecs déjà connus sur main (`tools_gateway_target`, `ui_intent_publish`) ;
  - routing settings, back brain protocol/speculative/tasks, enrichment, installed root, settings endpoints/IA, preparation workspace : 242 réussis, 2 ignorés (privilège de lien symbolique).
- **Mutations** (copie de l'arbre au scratchpad, 9 mutations, `test_agent_capabilities.py`) :
  - tuées (4) : verrou du mode dans `cli.settings`, drapeau de lecture seule de `CONTEXT_GLOBAL`, `--strict-mcp-config`, filtre `jarvis-` d'`--allowedTools` ;
  - survivantes (5) : voir m1.

## Findings

### MAJEUR

**M1 — La consigne et les méthodes des rôles décrivent encore des capacités absentes en `presentation`. Le parcours « mission » (cas B) dépend de Write/Edit.**
- Où :
  - `jarvis/runtime/claude_local.py:105`, qui prescrit « toute modification de code ou de fichier, une commande longue… navigateur » ;
  - `jarvis/runtime/routing_hook.py:95`, qui définit `[code]` « écrire ou corriger du code » et `[desktop]` « piloter le navigateur » ;
  - `jarvis/runtime/claude_local.py:308`, qui dit « board_memory_write… comme tes outils fichiers » ;
  - `jarvis/domain/subagent_roles.py:220-229`, `_DOSSIER` : « créez-le », « modification ciblée » ;
  - `jarvis/domain/subagent_roles.py:276` et `:291`, où les rôles research et web-research ajoutent au dossier de mission ;
  - le rôle `[code] [coder]` (`subagent_roles.py:410`), encore proposé au cerveau par `brain_rules` (`:688`).
- `brain_system_prompt_for` ne remplace que les lignes mémoire et retours. La consigne `presentation` rendue (vérifiée) contient donc à la fois « Vous et vos sous-agents n'avez ni terminal… ni outil qui écrit » et l'offre de `[code] [coder]` ou du cas B où « [interviewer] crée le dossier ». Le hook de routage (`--settings`/`--agents`, conservé en lancement confiné) injecte ces méthodes, inchangées, dans les sous-agents.
- Scénario : en `presentation`, l'utilisateur demande une création floue (« préparez-moi un dossier sur X »). Le cerveau classe la demande en cas B et lance `[general] [interviewer]`, dont la méthode dit de créer `mission.md` puis de l'éditer de façon ciblée. Write et Edit n'existent pas, et `board_memory_write` n'est ni cité ni adapté (append en fin de fichier, ou replace avec `expected_sha256`). Les agents `[research]` qui « ajoutent au dossier » échouent de la même façon. Le parcours se dégrade sans preuve qu'il aboutisse.
- Écart au contrat : SLICE.md, étape 8 (« prompts must not describe unavailable tools ») et critère « normal Presentation research/author/edit/export still works ». La trace réelle (a) ne couvre que le chemin direct `[presentation-author]`.
- Reprise proposée :
  - en édition confinée, adapter `_DOSSIER` et les méthodes de rôle à `board_memory_write` (append, ou replace avec `expected_sha256`) ;
  - ne pas proposer `[coder]`, `[code]` ni `[desktop]`, et ajuster les lignes de routage ;
  - ajouter un test de parité « consigne `presentation` sans Write, Edit, Bash, PowerShell, commande ni navigateur piloté » ;
  - faire une trace réelle du cas B en bac à sable.

### MINEUR

- **m1 — Tests d'enforcement manquants sur 4 surfaces** (mutations survivantes). Effet sécurité nul aujourd'hui grâce à la défense en profondeur : le lancement impose le manifeste et Codex refuse au `start`.
  - Champ plat `claude_permission_mode` (`control_center.py:5533-5542`) : verrou non testé.
  - Refus du `provider` codex et choix « indisponible » de la page Architecture (`brain_config.py:427-431`, `:672-676`) : aucun test.
  - Correspondance codex → claude du Control Center (`control_center.py:1440`, `:1741`, `:1958`, `:4007`, `:5256`) : aucun test.
  - Refus de la console Codex (`codex_local.py:739`) et garde `deploy` du self-dev (`self_dev_service.py:133`) : aucun test.
  - Aucun test HTTP de `GET /api/settings` → `agent_capabilities`.
- **m2 — `job_result` confiné sans `--add-dir` ni MCP** : un job Back Brain ne lit plus que `agent-workdir` (vide) et le web. C'est voulu, mais `docs/product-capabilities.md` (« confined (no MCP) ») ne dit pas qu'il ne lit aucun dossier de JARVIS.
- **m3 — La valeur imposée est enregistrée** : renvoyer `dontAsk` est accepté puis stocké dans `agent_cli_settings` (`control_center.py:5545`, `:5739`). Cela contredit le commentaire de `_mirror_legacy` (« un fichier de réglages ne doit pas garder `dontAsk` »). Sans effet en `presentation`.
- **m4 — Le lancement confiné n'exige pas d'argv natif**, contrairement aux profils restreints (`claude_local.py:1381-1384`). Aujourd'hui `claude.EXE` est natif et les arguments ajoutés ne contiennent aucun métacaractère, mais rien ne le garantit pour un `.cmd`.
- **m5 — `_confined_workdir`** (`claude_local.py:1184`) : un `mkdir` en échec lève une `OSError` brute, sans journal typé, alors que `_confined_read_dirs` journalise `agent_read_dir_unavailable`.
- **m6 — Doc** : `docs/SECURITY.md`, puce des risques résiduels : « policy In the » (point manquant). Couplage fragile : `brain_system_prompt_for` remplace des lignes exactes, donc une surcharge de consigne qui les modifie annule l'adaptation en silence (l'enforcement reste intact).
- **m7 — Registre mixte** : la consigne confinée vouvoie, alors que le socle `BRAIN_SYSTEM_PROMPT` tutoie (dette antérieure).

## Flagged (hors Slice ou à surveiller)

- Le `base_instruction.md` semé dans `CONTEXT_GLOBAL` dit encore « Tiens-le à jour ». Les règles en lecture seule priment (risque résiduel documenté).
- `Agent` accepte `isolation: "remote"` (agent cloud), selon la disponibilité du compte. Ce n'est pas une écriture locale, mais la doc pourrait le citer.
- `JARVIS_PRODUCT_EDITION=full` déconfine un produit installé. C'est voulu (Slice 01, administration), mais `product-capabilities.md` pourrait le rappeler.

## Non vérifié

- Pas de nouvelle trace réelle (pas de CLI lancée par ce relecteur). Le cas B en confiné n'a jamais été éprouvé.
- Pas de suites navigateur ni de test de bout en bout du 409 de la console côté UI (Slice 08).
- La parité `jarvis-tools` en confiné n'est pas prouvée par trace, la passerelle étant hors ligne pendant la série b.
