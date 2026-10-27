# QA — Slice 03 `03-research-reuse-freshness-orchestration`

QA indépendante, diff `1a3ac924..30ba18be` (`79cf6813` code et tests, `30ba18be` docs, LOG et I-002). Skills : `qa-verification`, `code-review`, `agent-trace-analysis`. Aucun code produit modifié.

## Verdict : **FAIL** (reprise ciblée sur la décision de fraîcheur)

La correction 1 d'I-002 (lectures bornées au Board, relance au rattachement), l'orchestration en arrière-plan et la réutilisation tiennent, sur le code comme en essai réel. Deux défauts de `research_freshness` empêchent cependant de réutiliser un document **dès qu'il vient d'être écrit**, en particulier le document comparatif produit par la direction de recherche. Or c'est la promesse de la Slice (« éviter le travail répété »). Les deux défauts sont prouvés sur des documents écrits par les agents eux-mêmes, au cours de l'essai réel.

## Findings

### B1 — MAJEUR, `blocking` : un front-matter de plus de 2 Kio est lu comme « sans date », donc « tout revérifier » à chaque tour
- Emplacement : `jarvis/domain/research_freshness.py:37` (`MAX_RESEARCH_HEAD_BYTES = 2_048`), alors que `:40` admet `MAX_SOURCES = 24`. Lecture à `jarvis/core/board_hydration.py:93`.
- Scénario réel (a) : la direction de recherche a écrit `documents/research/outils-video-presentation-ia-2026.md`, dont le front-matter fait **3 907 octets** (24 sources et plus, avec une longue `uncertainty`). La tête de 2 Kio n'atteint pas le `---` de fermeture, ce qui donne `unterminated_front_matter`. Le bloc du tour suivant, rendu par le vrai code (`with_board_research` puis `render_board_research` sur les données du bac), affiche : « `outils-video-presentation-ia-2026.md : sans sujet déclaré → tout revérifier (sans date de vérification lisible)` », le jour même de la vérification.
- Effet : le document le plus coûteux (2,3 $) n'est jamais réutilisable, et son sujet disparaît du bloc.
- Preuve : `scratchpad\v12s03qa\core_decision_after_runs.txt`, `board-memory\boards\default\memory\documents\research\`.

### B2 — MAJEUR, `blocking` : une source de volatilité forte publiée plus de 30 jours avant sa vérification reste « périmée » pour toujours
- Emplacement : `research_freshness.py:222-223`, où `(checked - source.date).days > max_age` ne dépend pas de la date du jour. Avec une demande d'actualité, le seuil tombe à 7 jours.
- Scénario réel (b) : le document Gamma, rafraîchi par le `[web-research]` à 11:35, cite `usagepricing.com … | date: 2026-09-08 | checked: 2026-10-27`. Juste après son rafraîchissement, à l'âge de 0 jour, il est déjà en `partial_refresh`. Le document (a), lui aussi à 0 jour, aurait 5 sources périmées s'il était lu en entier. Avec « derniers », un document vérifié le jour même passe en `full_refresh`/`stale` (sonde unitaire).
- Effet : le document est rafraîchi à chaque tour qui touche le sujet. Les tests unitaires couvrent la règle (`test_a_volatile_source_already_old_when_read_is_stale`), pas cet effet.

### M3 — MAJEUR, `polish` : les mots d'actualité donnent des faux positifs et la décision vaut pour tous les documents, sans lien avec le sujet du tour
- Emplacement : `research_freshness.py:86-93` et `board_hydration.py:97`. La même demande est appliquée à chaque document : le rapprochement entre le sujet et le document est laissé au modèle.
- Cas observés : « Modifie la dernière diapo », « maintenant », « actuellement », ou « 2026 » dans la question (a). Le tour (a) a ainsi marqué le document Gamma, sans rapport, « rafraîchir 4 sources ». « Modifie la dernière diapo » produit lui aussi « rafraîchir … et 1 autre(s) » sur Gamma. La tête affiche en plus la forme repliée « « derniere » » (`board_brief.py:210`).

### Mineurs (`polish`)
- **m4** : une vérification ratée compte comme faite. Le front-matter du document Gamma porte `checked: 2026-10-27 (échec HTTP 403, non lue)`, et `parse_day` ne retient que le préfixe : la source est jugée fraîche pendant 30 jours. Le format ne sait pas dire « échec ».
- **m5** : une date entre guillemets façon YAML (`'2026-10-20'`) n'est pas reconnue, donc `freshness_unknown`.
- **m6** : au-delà de 8 documents, le surplus (choisi dans l'ordre du `tree`) n'est compté que dans la trace (`unread`) ; le bloc du cerveau ne le dit pas.
- **m7, trous de tests** : deux mutations survivent. Comparer seulement le Board dans `board_scope_stale` (`claude_local.py:1410`) n'est attrapé par aucun test, faute de cas « même Board, autre Session ». Neutraliser la relance avant un tour (`control_center.py:6995`) n'est attrapé par aucun des 103 tests concernés. Cette relance n'a pas non plus été observée en vrai, ni par l'implémenteur ni ici.

## Vérifié OK
- **Pureté** : `decide` ne lit ni disque ni horloge. Date future tolérée à J+1 (fuseaux), rejetée à J+2. Horodatage ISO avec décalage pris par sa date. CRLF et BOM acceptés. Aucune exception sur une entrée mal formée. Panne de lecture : document jugé `freshness_unknown` ; panne du dossier : bloc gardé tel quel.
- **Coût par tour** : un `tree` (profondeur 2, 32 entrées) et au plus 8 lectures de 2 Kio, dans un thread, en Presentation seulement.
- **Consignes** : les rôles research, web-research et research-lead reçoivent le bloc en Presentation seulement. Le cas B est revu.
- **`full` à l'octet** : comparaison refaite (`dump_full.py` sur les archives `1a3ac924` et `30ba18be`), 185 542 octets, `cmp` identique. La garde d'empreinte des méthodes est verte.
- **I-002 correction 1** : relance seulement sans travail en cours (`has_work`), avec reprise `--resume`. En vrai : démarrage borné au Board `default` et à la Session ouverte. Un agent sans liaison ne perd que l'accès direct aux fichiers : Dossier et mémoire restent servis par MCP, `CONTEXT_GLOBAL`, `local_capabilities` et `artifacts` restent accordés.
- **Essai (b)** : `partial_refresh` sur la seule source de prix, puis un seul `[web-research]` en arrière-plan. Il lit d'abord le document existant, ne revérifie que les prix (la source d'aide garde `checked: 2026-10-10`) et signale la contradiction et le refus 403.
- **Essai (a)** : un `[research-lead]` en arrière-plan (Mission Owner, `deep-research@1`) lit d'abord l'existant du Board, ouvre un dossier de mission et **délègue à 3 `[web-research]`** (`caller_agent_id` renseigné). Il écrit ensuite le document avec son front-matter. Aucune relation `adversary` ni `qa` n'a été employée (permis, mais non observé).
- **Essai (c)** : bascule vers B à 11:36:31 pendant la recherche, retour à 11:37:06. Le cerveau de A passe en `background_running` sans relance. Le CLI de B démarre borné à `board_5810…` et à la Session ouverte, puis est suspendu au retour. Toutes les écritures restent sur `default`, rien n'apparaît dans B, la synthèse est relayée sur A. Rien n'est perdu ni mélangé.

## Tests
- Rejoués avec le `.venv` principal depuis `pev12` : `test_research_freshness` et `test_work_methods_fingerprint` (29) ; rôles, méthodes et instantané, relations, hook et orchestration, prompts confinés, périmètre S01, continuité S02, capacités (345) ; workspace_mcp, session_manager, board_brief, hydratation de la mémoire et du Context, board_brains ×5, hook de relations, routage des rôles (253) ; pièces jointes, orchestrateur v2, argv, service de Context, parité (107 et 1 échec connu `ui_intent_publish`).
- Total : **734 verts, 1 échec connu**.
- Mutations : 7 jouées, 5 tuées (seuil d'actualité, partiel vers total, règle de la source déjà vieille, garde de date future, grant de tout `boards`), 2 survivantes (m7).

## Trace de l'implémenteur (`scratchpad\v12s03\`)
Elle confirme les affirmations du LOG, en particulier (d) : `Grep` et `Glob` sur `boards` et `sessions` sont refusés. Trois remarques :
- à 11:17:25, le texte du cerveau commence par « 💭 L'agent est lancé ; une phrase de lancement suffit. » : la réflexion fuit dans le texte du tour (à signaler) ;
- `agent.declared` est émis deux fois par lancement, le second sans champs ;
- l'essai (d) était guidé (l'agent avait reçu l'ordre de tester).

## À signaler (hors Slice)
- **Coût d'une question large** : 2,3 $ pour une seule question (direction de recherche et 3 sous-agents Opus).
- **`agent.turn_over_budget` (`brain_inline_work`) à 4 tours sur 4** : le cerveau réécrit `summary.md` en plein tour (relève de la S02).

## Coût et nettoyage
- **Coût : 3,14 $** (`total_cost_usd` cumulé du CLI de A). (b) a coûté 0,68 $, CLI au démarrage compris ; (a) et (c) ont coûté 2,46 $. Le CLI de B n'a servi aucun tour.
- **Le budget de 1,20 $ est dépassé de 1,94 $.** La recherche large a coûté plus que prévu et le coût ne s'affiche qu'en fin de tour. J'ai choisi de la laisser finir pour prouver (c).
- Bac `%TEMP%\v12s03qa` : 34 PID exacts arrêtés par `Stop-Process -Id`, sans `/T`. Aucun processus restant, aucun port 54653-54656 à l'écoute. Bases, `-wal` et `-shm` copiées puis bac supprimé. Rien n'a été écrit hors du bac. Le JARVIS vivant n'a pas été touché.
- Preuves : `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s03qa\` (`evidence\trace.jsonl`, `trace-summary.txt`, `board-memory\`, `db-copies\`, `core_decision_after_runs.txt`, `base_full.json` / `head_full.json`).

## Non vérifié
- `knowledge_search` et Drive dans la découverte : non configurés au bac.
- Relance `board_scope` avant un tour, et changement de Session sur le même Board.
- Emploi réel d'`adversary`, `qa` ou `communication`.
- Comportement du cerveau face aux faux « tout revérifier » de B1 et M3 : non rejoué, faute de budget. Seul le bloc produit par Core est prouvé.
