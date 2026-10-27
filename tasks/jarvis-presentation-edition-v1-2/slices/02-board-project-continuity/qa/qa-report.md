# QA — Slice 02 `02-board-project-continuity`

- Relu : `3038b7aa..62939161` (`e3295b66` code/tests/docs, `62939161` LOG). Niveau : critical (consigne du cerveau + mémoire durable).
- Skills : `qa-verification`, `code-review`, `agent-trace-analysis`. Aucun code produit modifié.
- Preuves : `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s02qa\` (`full_base.json` / `full_app.json`, `evidence\trace.jsonl`, `board-memory\`, `db-copies\` avec `-wal`/`-shm`, `tools_all.txt` = digest des traces de l'implémenteur, `resume.txt`).

## Verdict : PASS avec réserves

0 bloquant, 1 majeur, 4 mineurs. Le cœur de la Slice est prouvé par tests et en vrai : convention en `presentation` seulement, `full` identique à l'octet, mise à jour du condensé par `replace` + `expected_sha256` sans doublon, dégradation sur condensé illisible, reprise sans « où en étions-nous ».

## Findings

### MAJEUR M1 — Une question d'entretien relayée n'entre pas dans le condensé : elle se perd à la reprise
- `jarvis/runtime/claude_local.py:179` : la liste « Quand » ne cite pas « question ouverte posée / relayée ». Le cerveau n'écrit donc pas `summary.md` quand il relaie une « QUESTION : » de l'Intervieweur.
- Scénario (trace de l'implémenteur, `v12s02\evidence\trace.jsonl`) : à 10:11:00, le condensé est créé ; à 10:11:18-20, la question « qu'est-ce qui retient les directeurs d'agence… » est relayée, sans écriture. Après le redémarrage (10:12:31), le cerveau répond depuis le condensé et ne parle pas de cette question. Elle reste seulement dans `missions/…/mission.md:20`, que la règle « n'ouvrez un document que si besoin » (`:181`) ne fait pas lire.
- Contre-épreuve (mon essai) : une question ouverte dite par l'utilisateur est bien écrite (`replace`, « Mettre des témoignages de clients ? (défaut : sans…) ») et reprise dans une nouvelle Session (« Il reste aussi à décider si l'on montre les prix et si l'on ajoute… »). Le défaut ne touche donc que les questions venues d'un sous-agent.
- Piste : ajouter à « Quand » « question d'entretien en attente de réponse », ou bien, à la reprise, quand l'État actuel dit « cadrage en cours », lire la dernière question du dossier de mission.

### MINEUR m1 — Deux consignes contredisent l'exception « le cerveau écrit lui-même »
- `claude_local.py:140` (bloc commun, inchangé) : « toute écriture (mémoire du Board, présentation) » part obligatoirement en sous-agent, et « Ne fais jamais ce travail toi-même ». `subagent_roles.py:873` (classe B) : « dans ce tour n'écris ni ne vérifies rien ».
- `:179` dit l'inverse pour `summary.md`, sans se présenter comme une exception à ces règles (le LOG parle d'« exception explicite », le prompt ne dit pas « exception »).
- Effet observé : au tour où la finalité est posée (classe B), aucun condensé n'est écrit (trace de l'implémenteur, tour 1). Si la Session tombe à ce moment-là, la finalité ne survit que dans le dossier de mission. Ailleurs, le modèle a suivi l'exception (3 écritures sur 3 tours significatifs).
- Confinement S01 : aucun outil nouveau. `board_memory_write`/`board_memory_read` (serveur `jarvis-workspace`) étaient déjà offerts au cerveau (`:34` du prompt rendu : « par vous ou par un sous-agent »). Le chemin reste borné au Board du tour, et `full` ne change pas. Le risque est faible et porte sur la latence, pas sur la sécurité (voir m4).
- Piste : en `presentation`, préciser à `:179` « exception à la règle qui délègue toute écriture et à la classe B : seulement summary.md ».

### MINEUR m2 — Condensé illisible : « ne jamais écraser sans relire » est impossible à suivre
- `:180` dit « ne l'écrasez jamais sans l'avoir relu », et `:182` « ne le remplacez qu'avec son accord ». Or un `summary.md` illisible ne donne aucun `sha256` à la lecture (`memory_not_text`). Le remplacement passe donc par un `replace` sans `expected_sha256`, ce que `board_memory_store.py:580` accepte. La consigne ne dit pas comment faire. Ce cas n'a pas été observé en vrai : le cerveau n'a rien tenté sans accord.

### MINEUR m3 — Nombre de tests faux dans le LOG
- Le LOG annonce « nouveau `test_presentation_project_continuity.py` (24) », mais le fichier contient **17** tests (`--collect-only`).

### MINEUR m4 — Latence d'un tour vocal qui met à jour le condensé
- Dans mon essai, le tour « décision + document clé » fait 13,9 s (`core.brain.turn_over_budget`, budget 8 s) : `ToolSearch`, deux lectures (condensé et catalogue, ce dernier lu par le cerveau lui-même), puis `replace`. Le prompt `presentation` passe de 13 462 à 16 586 octets (environ 800 jetons de plus à chaque tour). Le cerveau annonce aussi « J'ai mis à jour le résumé du projet », ce qui est du bavardage de gestion à l'oral.

## Flagged (hors Slice)
- Les écritures des sous-agents sont tracées `origin: "brain"` (`core.workspace.mutated`, trace de l'implémenteur, 10:09:41 et 10:10:21). C'est antérieur à la Slice.
- Un `[research]` fait `board_memory_tree` sur le Board `default`, puis `Grep` sur tout `data\sessions` et `data\boards` (lecture inter-Boards hors outils). C'est antérieur (S01/S03).
- `trace.jsonl` contient 3 lignes invalides après les arrêts forcés (déjà noté par l'implémenteur).

## Vérifié OK
- **`full` identique à l'octet** : refait de façon indépendante (archives `3038b7aa` et `62939161`, `dump_full.py` étendu à `render_brain_system_prompt(UNCONFINED|None)`) : `cmp` identique, 175 864 octets. J'ai contrôlé que chaque arbre est bien importé depuis sa propre racine.
- Gabarit < 600 octets ; cible 1 800 < plafond 2 048, non relevé ; projet riche à 1 405 octets, hydraté sans coupe (test). Condensés réels : 589 → 846 → 946 octets.
- `context_summary` borné à une ligne de gestion (`:183`), sans aucune écriture `board_update` dans les traces. Le prompt dit « rien d'un autre Board » ; l'A/B/A est testé et observé.
- Restes I-001 présents et pertinents : `Task`, `[coder]` sans profil, `[CODER]`, `[ coder ]`, marqueur dans le prompt seulement, `[éphémère]` en tête, et `Task` toujours permis en `full`. La doc m4 et la section *Real traces* sont faites.
- Docs : `boards.md` › *Presentation project digest* est cohérent avec le code ; il y a un renvoi dans `dossier.md` et une mise à jour de `product-capabilities.md`.
- **Tests** (`.venv` principal, depuis `pev12`) : continuité + périmètre S01 = 53 verts. Brief, mémoire (contrat, hydratation, magasin), confinées, Dossier (MCP, API, navigation), édition : 347 verts + 1 ignoré (lien symbolique). Hook (+ orchestration), hydratation Context, session_manager, workspace_mcp : 181 verts. Parité, délégation, prompts (registre, câblage, surcharges, argv) : 180 verts + 1 échec connu (`test_brain_capability_parity`, listé dans `known_failures.json`).
- **Mutations** (dans une copie d'archive, restaurées et vérifiées) : 5 sur 5 tuées. Section retirée du prompt ; `replace`+`expected_sha256` → `append` ; `AGENT_TOOLS` sans `Task` ; contrôle de `sha256` désactivé dans le magasin ; « pas à chaque phrase » → « à chaque phrase ».
- **Trace de l'implémenteur** : elle confirme ce qu'annonce le LOG. Création par le cerveau lui-même (`create` sans lecture préalable, ce qui est légitime puisque le condensé était absent) ; reprise sans aucun outil ; B neutre. Seule inefficacité : deux `ToolSearch` identiques en parallèle (10:10:53).
- **Essai réel** (archive `62939161` sous `%TEMP%\v12s02qa`, ports 50653-50656, `presentation`, `VISUALIZER_ENABLED=0`, `OPEN_BROWSER=0`, données, runtime et export dans le bac, lancé depuis `app`) :
  - Board A, condensé conforme déposé par l'API. Message : « 12 min au lieu de 8 + catalogue = document clé ». Le cerveau fait `board_memory_read summary.md` → `board_memory_write replace expected_sha256=d0ddbee9…`, un seul fichier mis à jour, sans `create` ni `append`. La décision est remplacée (pas dupliquée), le document est ajouté sous Documents clés, et une question ouverte est ajoutée avec sa valeur par défaut.
  - Tour suivant : `replace` avec le `sha256` rendu par l'écriture précédente (lecture évitée, toujours conditionnelle).
  - Board B, `summary.md` aux octets invalides : « le condensé du projet est illisible, donc je ne peux pas m'y fier », aucune écriture, aucun remplacement, proposition de recadrer.
  - Nouvelle Session sur A : aucun outil, reprise depuis le condensé avec la prochaine étape et les deux questions ouvertes.
  - Rien d'écrit hors du bac : Documents, Bureau et `C:\Users\Public` contrôlés en profondeur 5 par rapport au marqueur de départ ; dossier d'export vide.
- **Coût de la QA : 0,535 $** (0,301 + 0,098 + 0,062 + 0,075).
- Nettoyage : les 34 PID exacts de l'arbre du bac ont été arrêtés par `Stop-Process -Id`, sans `/T` ; aucun processus ne reste, aucun port 50653-50656 n'écoute. Bases copiées avec `-wal`/`-shm` avant suppression du bac. Le JARVIS vivant n'a été ni lancé ni touché.

## Non vérifié
- `memory_conflict` produit par le vrai cerveau derrière la CLI (prouvé seulement par les tests de la vraie pile Core).
- Board archivé derrière la CLI réelle ; mémoire `INDISPONIBLE`.
- Remplacement d'un condensé illisible avec l'accord de l'utilisateur (m2).
- Condensation d'un condensé reçu « coupé ».
- Reprise après redémarrage complet de Core dans mon essai : je n'ai testé qu'une nouvelle Session ; le redémarrage de Core a été observé par l'implémenteur.
