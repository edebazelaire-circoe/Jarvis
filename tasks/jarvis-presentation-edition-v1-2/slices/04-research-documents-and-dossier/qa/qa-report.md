# QA — Slice 04 `04-research-documents-and-dossier`

- Code relu : `52919163..9df4b800` (`8c04a8ae`, `9df4b800`), worktree `pev12` (lecture seule ; seul ce rapport est écrit).
- Agent QA, 2026-10-27. Skills : qa-verification, code-review, agent-trace-analysis, runtime-validation.
- Preuves : `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s04qa\`.

## Verdict : **PASS avec réserves**

Aucun finding bloquant ni majeur. Quatre findings mineurs (affichage), non bloquants.

## Findings

### Mineurs

**M1. « Afficher sur le Board » : titre du nom de fichier et en-tête brut.**
`jarvis/core/dossier_service.py:672` : `present()` résout l'entrée par `_resolve_entry` sans `_research_details`.
La fenêtre posée sur le Board s'appelle donc `gamma-vs-pitch` alors que le Dossier affiche « Gamma vs Pitch : prix
d'entrée, export PowerPoint, collaboration ». Son `summary` commence par l'en-tête brut (`---\ntopic: gamma-vs-pitch\nscope: …`)
au lieu du Résumé.
Scénario : bac, `POST /v1/workspace/boards/default/dossier/present {"entry_id":"memory:documents/research/gamma-vs-pitch.md"}`
→ 201, puis `/api/scene` → `payload.title = "gamma-vs-pitch"`, `summary = "---\ntopic: …"`.
Le document s'affiche et la source est la même (exigence tenue), mais le titre n'est pas le même que dans le Dossier.

**M2. Titre coupé quand l'en-tête frôle 2 Kio.**
`jarvis/core/dossier_service.py:253-272` : on lit une tête de 2 048 octets. Si l'en-tête se ferme juste avant cette limite,
la ligne `# …` est lue à moitié. Le titre affiché est alors tronqué en plein mot. Si le `#` tombe entièrement après la
limite, le titre est le `topic`, que l'agent réel a écrit comme le nom de fichier.
Preuve, avec les fonctions du code : en-tête de 2 021 octets, `# Un titre assez long pour être coupé…` → titre
`'Un titre assez long pour'`. L'en-tête réel (8 sources) fait 1 489 octets : un document de 10 à 11 sources tombe dans
cette fenêtre. Piste : relire plus loin quand `eof` est faux et que la ligne du titre n'est pas terminée.

**M3. Sources de l'en-tête non repliées.** Dans le Dossier, `#dossierView .dsr-prose pre` (`overflow:auto`,
`control_center_dossier.js:1342`) affiche les lignes de sources longues coupées au bord droit, en 1440×900. Il faut
défiler horizontalement pour lire une URL (capture `shot-gamma-2.png`). Le défilement fonctionne : c'est un point de confort.

**M4. Préfixe avant « Document non enregistré ».** Lors de l'essai (c), le compte rendu de l'agent commence par
« BLOQUÉ : Document non enregistré : memory_conflict ». La consigne demande que le compte rendu *commence* par
« Document non enregistré ». Le cerveau l'a quand même relayé correctement. C'est sans conséquence, à noter si un
contrôle automatique s'appuie un jour sur ce début.

### Observations, hors périmètre S04

- Trace de l'implémenteur : quatre tours du cerveau sont au-delà de leur budget (`agent.turn_over_budget`, `brain_inline_work`)
  à cause des écritures de `summary.md` dans le tour. La nouvelle ligne S04 « Documents clés » ajoute une de ces écritures
  à chaque retour de recherche.
- Même trace : `[presentation-brief]` a fait un Glob/Grep dans `data\CONTEXT_GLOBAL`, hors du Board. La direction de
  recherche a ouvert une URL d'affiliation (`gamma.app/pricing?utm_…affiliate`). Le cerveau a émis un texte en anglais
  (« Memory is empty, so create directly. »).
- Essai (c) : le refus du magasin pour un parent qui est un fichier sort sous le code `memory_conflict`, avec le texte
  « le fichier a changé depuis ta lecture ». Ce texte est trompeur, mais l'agent a compris la cause.

## Vérifié OK

- **Gabarit compatible avec le lecteur S03** : `RESEARCH_DOCUMENT_TEMPLATE` = en-tête S03 + `#` + quatre sections.
  Le document réel (`tests/fixtures/research/gamma-vs-pitch.md`) est jugé conforme, avec la décision `reuse`. Les
  sources n'apparaissent qu'une fois, dans l'en-tête.
- **Nom stable** : `research_slug` / `research_path` produisent un nom en minuscules ASCII, sans date, de 60 caractères
  au plus, coupé sur un mot. Règle « un sujet, un fichier » : `replace` avec `expected_sha256`, et sur conflit, relire
  puis une seule nouvelle tentative.
- **Qui écrit** : l'agent qui conclut. La direction de recherche écrit, ses agents non ; le cerveau seulement
  `summary.md`. Vérifié dans la trace de l'implémenteur et dans l'essai (c).
- **Échec d'écriture** : le magasin publie par un fichier temporaire puis un remplacement atomique, et la version
  précédente reste intacte (test). En réel : le compte rendu dit « non enregistré » et contient le résultat entier. Le
  cerveau dit « Je n'ai pas pu enregistrer le document… » et ne l'écrit pas lui-même. L'agent n'a pas cherché à écrire
  ailleurs.
- **Note « RECHERCHES DU BOARD »** : présente une seule fois dans `[presentation-brief]` et `[presentation-author]` en
  `presentation`. Absente des rôles de recherche et de `full`.
- **`full` identique à l'octet** : `dump_full.py` relancé sur deux nouvelles archives, `52919163` et `9df4b800`. Les
  deux sorties sont égales (217 347 caractères comparés ; seule la clé `jarvis_file` est exclue).
- **Taille en `presentation`** :
  - prompt du cerveau : 17 221 → 17 713 octets (+492) ;
  - `research`, `web-research` et `research-lead` : environ +1,4 Kio chacun ;
  - hook brief et auteur : +722 octets ;
  - `brain_rules` inchangées.
- **Aucun type d'Artifact ajouté**, aucune migration, aucun contrat MCP modifié.
- **Dossier dans un vrai Chrome sans tête** (Control Center réel du bac, `_interaction_mode_browser.mjs`) :
  - collection « Recherches » (3) ;
  - lignes « Recherche · vérifiée le 27 octobre 2026 · 8 sources (1 non lue) » ;
  - titre `#` affiché ;
  - en-tête gardé en bloc à chasse fixe ;
  - document sans en-tête : « en-tête à réécrire ».
- **XSS** : document piégé (`<img onerror>` dans le titre, `<script>` dans le `topic`, sources `javascript:` et
  `"><img …>`, corps HTML, lien `javascript:`). Résultat : `window.__xss` reste nul, 0 `img`, 0 `script` et 0 lien
  `javascript:` dans `#dossierView`. Tout le contenu est rendu en texte (`textContent`), sans erreur de console.
- **Documentation** : `docs/boards.md` › *Research documents*, `docs/dossier.md` (ligne `research`, collection) et
  `docs/subagent-roles.md` § 12 sont cohérents avec le code.

## Tests

| Lot | Résultat |
| --- | --- |
| `test_research_documents.py` + `test_dossier_core_js.py` | 25 verts |
| fraîcheur, continuité, prompts confinés, périmètre du cerveau, playbooks, rôles, routage des rôles (+ familles) | 275 verts |
| Dossier (MCP, navigation, API), `workspace_mcp`, routage UI JS, délégation, parité | 224 verts + 1 échec connu (`ui_intent_publish`, `tests/known_failures.json`) |
| `test_dossier_fullscreen_browser`, `test_dossier_navigation_browser`, `test_routing_hook` | 59 verts, 3 ignorés (captures) |

Mutations, sur une copie de l'archive, toutes tuées :

1. Titre du document de recherche non appliqué : 2 échecs.
2. Note ajoutée même hors `presentation` : 1 échec.
3. En-tête non gardé en bloc (JS) : 1 échec.
4. Collection « Recherches » désactivée : 1 échec.
5. Coupe du slug hors fin de mot : 1 échec.
6. Règle d'échec affaiblie (« dites toujours qu'il est enregistré ») : 1 échec.

## Analyse de la trace de l'implémenteur

Deux tours.

- **Tour 1** : une seule `[research-lead]` en arrière-plan, seule, avec 7 WebSearch et 13 WebFetch. Elle écrit une fois
  `documents/research/gamma-vs-pitch.md` (`create`), après convergence. Le cerveau ajoute ensuite le document sous
  Documents clés (`replace`).
- **Tour 2** : décision `reuse/fresh`. Un seul `[presentation-brief]` porte la note. Il lit le document et
  `summary.md`, sans aucun appel web. Le coût de 1,37 $ correspond au LOG.
- La correction du titre (`topic` = nom de fichier) est justifiée par cette trace. Voir les observations ci-dessus.

## Essai réel (bac `%TEMP%\v12s04qa`, archive `9df4b800`, ports 59653-59656, `presentation`)

- **(a) Question isolée sur un Board vierge.** « Quel est le prix du plan Pro de Pitch ? » lance un seul
  `[web-research]`, qui répond (Team 15 €/siège/mois). **Aucun document de recherche**, aucune écriture mémoire.
- **(c) Échec d'écriture provoqué.** Un fichier `documents/research` bloque le dossier. Le cerveau lance un
  `[research]`, dont l'écriture est refusée (`memory_conflict`). Le compte rendu dit « Document non enregistré » et
  contient le contenu. Le cerveau répond « Je n'ai pas pu enregistrer le document… » et demande quoi faire.
  `summary.md` dit « document non enregistré ».
- **(b) Dossier dans le navigateur** : voir « Vérifié OK ».
- **Nettoyage** : 34 PID exacts arrêtés (`Stop-Process -Id`, sans `/T`), arbre des deux processus lancés par ce QA.
  Aucun processus restant, aucun port en écoute. Rien n'a été écrit hors du bac ; l'export est vide. Les bases (avec
  `-wal` et `-shm`), la trace, les journaux, la mémoire et les captures ont été copiés avant la suppression du bac. Le
  JARVIS vivant n'a pas été touché.

## Coût

0,747 $, cumul de la CLI du bac (a : 0,475 $ ; c : +0,272 $). Le budget était de 0,80 $.

## Non vérifié

- Rafraîchissement réel d'un document existant (`replace` + `expected_sha256`) par un agent dans cette Slice.
- Board archivé pendant une recherche : remplacé par le blocage du dossier.
- Délégation effective par la direction de recherche à ses agents.
- Lecture du Dossier par Jarvis à la voix.
