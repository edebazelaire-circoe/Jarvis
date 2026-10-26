# Slice 04 — Contre-revue de la reprise QA (M1)

Date : 2026-10-26. Relecteur : agent de contre-revue, indépendant de l'implémentation. Aucun code produit modifié.
Périmètre : `10094459` (code, docs, tests) et `42ca5161` (LOG, `Issues/I-005-s04-leftovers.md`), au-dessus de
`de5ceafd` (`qa/code-review.md`, finding majeur M1). Comparaison `full` contre `cf3f7e44` (S3 approuvée).

## Verdict recommandé

**PASS** : aucun bloquant ni majeur. M1 est corrigé sur les surfaces qu'il nommait. Cinq mineurs, dont deux restes
de texte non déclarés dans I-005 et deux angles morts du test de parité. La décision revient au PM.

## Preuves (exécutées par ce relecteur)

Scratchpad : `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\crq\`.

| Vérification | Résultat |
|---|---|
| `argv_dump.py` sur l'archive de `cf3f7e44` (`crq/base`) et sur `pev1` HEAD, édition `full`, profils `conversation` et `job_result` | argv identiques (24 et 15 éléments). La consigne `--append-system-prompt-file` est identique (20 229 octets). Seule différence : le chemin du dossier de sortie (`o_base`/`o_head`), qui entre dans le hash du nom de fichier. Le snapshot gagne la clé `confined`, ajoutée par la S4 initiale. |
| `crq/tools/hookdump.py` : `routing_hook.run` complet (journal compris), 18 en-têtes (`[general] [interviewer]`, `[research]`, `[web-research]`, `[concept]`, `[research-lead]` ± `[mission]`, `[general]`/`[code] [qa]`, `[code] [coder]` ± `[mission]`, `[desktop]`, `[general]`, `[fast]`, `[general]`/`[code] [presentation-author]`, `[presentation-brief]`, `[presentation-review]`, `[éphémère]`), édition `full` | `hb.json` (`cf3f7e44`) et `hh.json` (HEAD) **identiques octet pour octet** (sorties et types d'événements du journal) |
| Même script en `presentation` (`hp.json`) et rendu de la consigne résolue (`crq/tools/render.py`, programme `conversation_display_studio_barehands_session`) + workspace | grep large (Write, Edit, MultiEdit, Bash, PowerShell, terminal, shell, commande, git, dépôt, code, navigateur, script, test, `[code]`, `[coder]`, `[desktop]`) : `crq/hits.txt`, analysé ci-dessous |
| Trace réelle du cas B de l'implémenteur (`scratchpad\s04rw\evidence\`) | relue : `trace.jsonl` contient le bloc « CAPACITÉS DE CETTE ÉDITION (SOUS-AGENT) », 3 `agent.role_applied`, aucun `confined_adaptation_missed` ; les transcripts des sous-agents écrivent par `board_memory_write` |
| Mutations sur une copie (`crq/mut`, `git archive HEAD`), `tests/unit/test_confined_prompts.py` | 4 tuées, 2 survivantes (voir m2) |
| Tests (`.venv` du dépôt principal, avant-plan, 4 lots) | confined_prompts, agent_capabilities, product_edition, subagent_roles, presentation_playbooks, agent_orchestration : **192 passed**. routing_hook(+orchestration), brain_delegation, prompt_registry(+review), brain_capability_parity, control_center_prompts : **186 passed, 1 failed** (préexistant `test_every_tool_of_a_declared_server_is_documented_in_the_brain_prompt`, `ui_intent_publish`). relations_runtime final/hook/rework, mission_orchestration_wiring, subagent_role_routing(+families), work_method_application, work_methods, global_context, back_brain_delegation : **185 passed**. claude_debug_console, claude_prompt_argv_limit, claude_tools_gateway_args, self_dev(+service), voice_to_claude : **89 passed**. |

### Mutations

| Mutation | Résultat |
|---|---|
| M1 `offers_role` rend toujours vrai (`[coder]` reproposé au cerveau et au catalogue) | tuée |
| M2 `subagent_note` jamais apposé par le hook | tuée |
| M3 cas B confiné : texte `full` (« sous le chemin absolu de la Mémoire du Board de ton contexte de tour ») | **survit** |
| M4 réécriture `research_sources` cassée (« la documentation et le code du dépôt » reste dans la méthode de `[research]`) | **survit** |
| M5 ligne de délégation `full` (« navigateur… modification de code… commande longue ») en confiné | tuée |
| M6 journal `agent.role.confined_adaptation_missed` supprimé | tuée |

## Point par point

1. **M1 corrigé.** La consigne `presentation` résolue ne contient ni outil de `--disallowedTools`, ni `[code]`, `[coder]`
   ou `[desktop]`. La ligne de délégation, la règle des profils (`[fast]`, `[general]`, `[general] [qa]`), l'auteur
   `[general] [presentation-author]`, l'exemple éphémère, le cas A (`[general] [research]`) et le cas B (dossier dans la
   mémoire du Board actif) sont rendus depuis le manifeste. Le hook, pour chaque en-tête offert, appose la méthode
   adaptée et le bloc sous-agent. Le dossier de mission passe par `board_memory_read`/`board_memory_write`
   (create, append, replace avec `expected_sha256`). Les briefs mission et relations citent `[general] [qa]`. Les
   restes trouvés par le grep sont analysés en m1 et m3.
2. **Source unique : oui, à une répétition près.** `offers_task_profile` dérive de `routing.TASK_PROFILES[*].requires`
   et du manifeste (`_CAPABILITY_NEEDS`, `NATIVE_WRITE_TOOLS`), sans seconde liste de rôles ni de profils. La règle
   « `code` si offert, sinon `general` » est toutefois recopiée cinq fois (m4). Pas d'échec silencieux :
   - `confined_adaptation_missed` est journalisé (tué par M6) ;
   - `agent_capabilities_unreadable` est journalisé, et la consigne part alors comme en `full`. C'est acceptable :
     Core refuse déjà de démarrer avec une édition illisible (`ConfigurationError`) ;
   - `agent_workdir_unavailable` est typé et journalisé.

   `PromptAdaptationError` ne peut pas toucher `full` : `workspace_prompt_for("full")` n'appelle `_replace_once` pour
   aucune ligne, puisque `restricts_board_kinds` est faux et `writes_files` vrai. Il ne porte que sur des constantes
   du code. Une surcharge utilisateur ne l'atteint pas : la section est dynamique et `PromptRegistry.resolve` appelle
   toujours le renderer. C'est donc une garde de développement, couverte par `test_confined_prompts` (rendu
   `presentation` complet) et par `test_a_missing_workspace_line_is_an_error_not_a_silent_skip`. Si elle levait, le
   lancement `presentation` échouerait avec le code `prompt_adaptation_line_missing` ; le message vise un
   développeur, pas l'utilisateur. Observation, sans action requise.
3. **`full` identique** : argv, consigne, fichiers runtime et sortie complète du hook sur 18 en-têtes, journal
   compris (tableau ci-dessus).
4. **Profil de l'auteur `code` → `general`.** `presentation-author` n'est pas un `SubagentRole` : aucune politique par
   rôle (`role_routing`) ne s'applique, et le hook route par profil (`resolve_for`).
   - Routage désactivé (défaut `COMPATIBILITY_POLICY`, cas d'une installation neuve) : `REASON_COMPATIBILITY`, aucun
     modèle imposé, le CLI garde son modèle configuré. Aucune différence entre `code` et `general` ; la trace réelle a
     tourné sur Opus.
   - Routage activé : l'auteur prend la liste du profil `general`, plus celle de `code`. Le changement est cohérent
     avec le manifeste, puisque `code` exige `CODE` et donc un outil d'écriture. Il a cependant deux effets pour
     l'utilisateur, notés en Observation O1.
5. **Test de parité** : utile (4 mutations sur 6 tuées, dont la réintroduction de `[coder]`), mais il ne mesure que
   les noms d'outils et les trois marqueurs (m2).

## Findings

### BLOQUANT
Aucun.

### MAJEUR
Aucun.

### MINEUR

- **m1 — La consigne de modification structurelle d'une scène renvoie à un fichier du dépôt, illisible en `presentation`
  (reste non déclaré dans I-005).**
  - `jarvis/runtime/claude_local.py:287`, section REMOTION de la consigne `presentation` résolue : « puis UN sous-agent
    d'arrière-plan édite la source … Donne-lui … la section « Édition de source d'une scène Remotion par un agent » de
    docs/OPERATIONS.md (dépôt courant) ».
  - En confiné, le sous-agent travaille dans `agent-workdir` et ne lit que les dossiers de JARVIS
    (`_confined_read_dirs`, `claude_local.py:1266`). Le dépôt n'est pas lisible, et `docs/` n'est sans doute pas livré
    dans le produit installé.
  - C'est le parcours « edit » du critère « research/author/edit/export still works ». Le sous-agent garde
    `presentation_source` (le bloc sous-agent nomme `presentation_*`), donc le parcours se dégrade (un Read refusé, une
    recherche d'outil) sans casser.
  - Non vérifié en réel. Reprise suggérée : en confiné, nommer `presentation_source` (read, write, preview) à la place
    du document.
- **m2 — Deux angles morts du test de parité** (`tests/unit/test_confined_prompts.py:35-40`, `:103-112`).
  - Seuls `FORBIDDEN_NATIVE_TOOLS` et `[code]`/`[coder]`/`[desktop]` sont cherchés. La mutation M4 (« la documentation
    et le code du dépôt » réapparaît dans `[research]`) survit.
  - La mutation M3 (cas B revenu au chemin absolu de la Mémoire du Board, texte `full`) survit aussi : l'assertion
    « dans la mémoire du Board actif » (`:109`) est déjà satisfaite par la section RETOURS UTILISATEUR confinée.
  - Suggestion : comparer `brain_rules(capabilities=PRESENTATION_CAPABILITIES)` à la phrase confinée exacte, et
    vérifier que chaque `ConfinedRewrite.new` figure dans le `role_brief` des rôles concernés.
- **m3 — Autres restes de texte non déclarés**, sans enforcement en jeu. Le bloc sous-agent les neutralise côté
  sous-agents, mais il n'est pas lu par le cerveau.
  - `jarvis/runtime/claude_local.py:168` (consigne du cerveau) : « c'est lui qui enquête, lit le code et la
    documentation ».
  - `jarvis/domain/presentation_studio_authoring_policy.py:208` (guide du planificateur, dans la consigne
    `presentation`) : « inspecte avec tes outils ce qui existe (… dossiers, dépôt, …) ».

  Les restes déclarés dans I-005 §8 sont bien d'effet nul sur le confinement :
  - `routing_hook.py:686-689` (`HANDOFF_IMPOSSIBLE_REASON`) et `relation_runtime.py:128` (`[code] [qa]`) ne servent qu'en
    message de refus ;
  - la charte `agent_charter.py:70` (« historique git ») est suivie du bloc sous-agent ; la trace réelle ne montre
    aucun outil absent tenté ;
  - `subagent_roles.py:412` (`when_relevant` de `[research]`) ne fait que citer le dépôt.

  Une nuance : le refus de relais propose `[code] [coder] [relais]`. En `presentation`, un agent qui le suit relance
  sous le profil `code` et le rôle `coder` (voir O2).
- **m4 — Règle « `code` si offert, sinon `general` » recopiée cinq fois** : `claude_local.py:155`,
  `routing_hook.py:111`, `routing_hook.py:285`, `agent_orchestration.py:248` et `subagent_roles.py:845`. Elle est
  dérivée du manifeste, mais une seconde édition confinée ou un nouveau profil demanderait cinq retouches.
  Suggestion : une seule propriété du manifeste (par exemple `review_profile` / `author_profile`).
- **m5 — `adapt_instructions` est calculé deux fois par appel** : dans `role_brief` (le résultat `_missed` est
  ignoré, `subagent_roles.py:734`) et dans `_log_confined_adaptation` (`routing_hook.py:603`). Le coût est
  négligeable, mais la journalisation ne dépend pas du texte réellement apposé. Une divergence future passerait
  inaperçue.

## Flagged / Observations

- **O1 — Réglages de routage en `presentation`.** Aucun fichier JS ni gabarit n'utilise
  `offered_task_profiles`/`offers_task_profile`. La page de routage par profil continue donc a priori d'offrir
  « Code avancé » et « Poste de travail ». Non vérifié dans le navigateur. Un utilisateur qui règle `code` sur un
  modèle fort pour « la production » n'affecte plus l'auteur, qui suit `general`. À trancher en S09/S10, avec le
  contrôle qualité et modèle de l'auteur déjà prévu dans I-005 §8.
- **O2 — Un `[code]`/`[desktop]`/`[coder]` annoncé quand même en `presentation`** (habitude du modèle, ancienne
  mémoire, message de refus m3) n'est ni refusé ni journalisé.
  - Le hook route sur le profil `code` et appose la méthode complète de `coder` (10 131 caractères,
    `crq/hp.json`), suivie du bloc sous-agent.
  - Sans effet sur l'enforcement. En revanche, la trace ne permet pas de repérer une dérive du cerveau.
  - Suggestion : un événement `agent.profile_unavailable_in_edition`.
- **O3 — L'aperçu de la page Prompts du Control Center** (`control_center.py:5258-5281`) résout la consigne sans
  variable `product_edition`. En `presentation`, il montre donc le texte `full`, différent du texte réellement
  lancé (`claude_local.py:1395`). Dette de la S04 initiale, non introduite par la reprise.

## Non vérifié

- Pas de lancement réel par ce relecteur. Je me suis appuyé sur la trace du cas B de l'implémenteur, que j'ai relue,
  sans la rejouer.
- Le parcours « modification structurelle d'une scène » en `presentation` (m1) n'a pas été exercé.
- L'interface des réglages de routage en `presentation` (O1) n'a pas été ouverte.
- Les suites navigateur n'ont pas été lancées.

## Risques résiduels

Ils portent sur les textes uniquement, puisque l'enforcement au lancement ne dépend d'aucune consigne. Un modèle peut
encore être orienté vers le dépôt (m1, m3) ou vers un profil absent (O2). Il perdrait alors un tour d'outil, sans
pouvoir sortir du confinement.
