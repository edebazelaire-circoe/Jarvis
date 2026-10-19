# Slice 07 — preuves

Captures PNG allégées (128 couleurs). Deux sources :

- `reel-*` : le vrai Control Center du bac à sable (Core et Control Center lancés depuis le worktree `wdr`,
  `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR` au scratchpad `s07`, visualiseur coupé, `BROWSER` neutralisé),
  Board « Projet Atlas » (type Présentation) avec cinq notes de mémoire et une image déposée sur le Board ;
  vrais tours de modèle par `/api/chat/turns`.
- `harnais-*` : la page servie dans Chrome sans tête avec le double de `_status_centre_browser.mjs`
  (`test_dossier_fullscreen_browser.py::test_evidence_captures`, `JARVIS_S07_DOSSIER_EVIDENCE_DIR`),
  aux trois tailles demandées.

| Scène | 1920×1032 | 1280×720 | 600×800 |
| --- | --- | --- | --- |
| Accueil (vue d'ensemble) | `harnais-accueil-1920x1032.png`, `reel-accueil-reel-1920x1032.png` | `harnais-accueil-1280x720.png`, `reel-accueil-reel-1280x720.png` | `harnais-accueil-600x800.png` |
| Entrée texte | `harnais-entree-texte-1920x1032.png` | `harnais-entree-texte-1280x720.png`, `reel-entree-reelle-1280x720.png` | `harnais-entree-texte-600x800.png` |
| Image | `harnais-image-1920x1032.png` | `harnais-image-1280x720.png`, `reel-image-reelle-1280x720.png` (payload réel du registre) | `harnais-image-600x800.png` |
| Deux entrées côte à côte | `harnais-deux-entrees-cote-a-cote-1920x1032.png`, `reel-jarvis-deux-notes-1920x1032.png` | `harnais-ouverture-par-jarvis-1280x720.png` | — (repli en onglets, testé) |
| Édition avec conflit | `harnais-edition-conflit-1920x1032.png` | `harnais-edition-conflit-1280x720.png`, `reel-edition-enregistree-1280x720.png` (enregistrement réel) | `harnais-edition-conflit-600x800.png` |
| Board archivé | `harnais-board-archive-1920x1032.png` | `harnais-board-archive-1280x720.png` | `harnais-board-archive-600x800.png` |
| Core indisponible | `harnais-core-indisponible-1920x1032.png` | `harnais-core-indisponible-1280x720.png` | `harnais-core-indisponible-600x800.png` |
| Ouverture pilotée par Jarvis | `reel-jarvis-compte-rendu-1920x1032.png`, `reel-jarvis-deux-notes-1920x1032.png`, `harnais-ouverture-par-jarvis-1920x1032.png` | `harnais-ouverture-par-jarvis-1280x720.png` | `harnais-ouverture-par-jarvis-600x800.png` |
| Vue avancée (détails techniques) | `harnais-vue-avancee-1920x1032.png` | `harnais-vue-avancee-1280x720.png` | `harnais-vue-avancee-600x800.png` |
| Roue › Dossier (entrées récentes) | `reel-roue-dossier-1920x1032.png` | | |
| Afficher sur le Board (même fichier) | `reel-jarvis-affiche-dossier-ouvert-1920x1032.png`, `reel-jarvis-affiche-sur-le-board-1920x1032.png` | | |

`agent-turns.log` : traces des vrais tours (outils appelés, événements `dossier.navigation.*` et `core.dossier.*`,
réponse finale). Trois passes : la première avec le prompt d'avant (le cerveau choisit `dossier_present` pour
« Montre-moi » et dit « à l'écran » alors que les fenêtres sont sous le Dossier ouvert), la deuxième après la
ligne Dossier de `BRAIN_WORKSPACE_PROMPT` (deux `dossier_view`, côte à côte) mais avec un onglet du navigateur de
l'utilisatrice qui prenait aussi les ordres, la troisième (« Run final », ports 28663/28664, une seule page) qui
fait foi.
