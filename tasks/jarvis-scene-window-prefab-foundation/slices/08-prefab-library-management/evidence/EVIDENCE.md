# Slice 08 — preuve navigateur (bibliothèque des prefabs, vue `PFB`)

## Montage

- Vrai Chrome installé, `--headless=new`, profil jetable `--user-data-dir`
  (supprimé après), piloté par CDP : `browser_probe.mjs` (harnais des Slices
  03-06). Aucune fenêtre ouverte dans le Chrome de l'utilisateur. 1600 × 1000,
  puis 760 × 1000 pour l'étroit.
- Core : `core_with_witness.py` (le Core de `jarvis.app._run_core_v2` réduit :
  mêmes `V2Settings`, jeton, serveur), `JARVIS_CORE_PORT=18993`, hôte
  `127.77.0.1`. Au démarrage il **enregistre un tour utilisateur** comme le
  fait l'admission vocale (`build_conversation_event`,
  `PRODUCER_VOICE_ADMISSION` — le chemin de `test_display_mcp_prefabs.py`)
  puis appelle la **vraie** route `POST /v1/prefabs/jarvis.table/base-edits`
  (acteur `brain`, jeton) avec ces mots : `HTTP 201`, `jarvis.table` v2
  `origin base_edit`, témoin `conversation_event:cev-35c6…`. La porte n'est
  pas affaiblie : sans ce tour, Core refuse (`base_edit_unconfirmed`, S07).
- Control Center : `python -m jarvis control-center`, `JARVIS_UI_PORT=18994`,
  `JARVIS_SCENE_ENABLED=1`, `JARVIS_VISUALIZER_ENABLED=0`.
- `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR` dans un scratch de session
  **neuf** pour la passe finale (trois passes au total, la dernière sur
  racines neuves). Ports 17653/17654 jamais touchés ; serveurs et Chrome
  arrêtés après (plus aucune écoute sur 18993/18994).

Relance : `node browser_probe.mjs http://127.0.0.1:18994/ "<chrome.exe>" . http://127.77.0.1:18993 <runtime>/core.token`

## Résultats (`browser-results.json`, captures PNG)

| Preuve | Observé |
| --- | --- |
| Dock | `PFB` après `WSP` (`dock-circuit.png`) ; Cosmos : icône, 9 outils sur une ligne (`dock-cosmos.png`) |
| Ouvrir | vrai clic sur `#openPrefabs` : `aria-expanded=true`, reste de la page `inert`, focus sur la recherche ; liste lue sur Core : 3 `Base`, `jarvis.table` `Base modifiée à votre demande` ; intro avec légende des quatre natures et règle des bases — `library-open.png` |
| Noms accessibles (arbre d'accessibilité de Chrome) | dialogue « Bibliothèque des prefabs », champ « Rechercher un prefab », liste « Famille », groupe « Nature des prefabs » (« Tous : 4 », « Base : 3 »…), lignes « Table, jarvis.table, version 2, base modifiée à votre demande », région « Prefab choisi », note « Protection des prefabs de base » |
| Chercher « check » | saisi au clavier : une ligne, `jarvis.checklist` — `search-check.png` |
| Clavier | ↓ depuis la recherche → focus sur la ligne ; Entrée → sélection ; ↓ ↓ ↑ dans la liste changent la sélection ; Échap ferme et rend le focus à `PFB` ; Entrée sur `PFB` rouvre ; `/` va à la recherche |
| Aperçu | un iframe `sandbox="allow-scripts"`, la checklist avec ses 3 éléments d'exemple ; note de protection « Prefab de base · protégé » ; **aucun** bouton d'édition de base — `checklist-detail.png` |
| Événement d'aperçu | vrai clic sur la ligne 2 dans le cadre → « item_toggled · ÉTAT · {items…} » dans le journal local ; anneau d'événements de Core : 0 avant, **0 après** — `preview-event-log.png` |
| Placer sur la scène | `user-prefab-b64ff488241f` dans la scène de Core : `kind window`, **`origin user`**, `prefab jarvis.checklist@1`, 3 éléments — `placed.png` |
| Fork `jarvis.checklist-red` | avertissement en direct sous le champ ; Core refuse `base_protected · HTTP 403`, le formulaire l'affiche avec son explication, champ `aria-invalid`, focus rendu au champ — `fork-base-protected.png` |
| Fork `team.checklist-red` | titre « Checklist rouge », accent `#ff4d5e` (`fork-form.png`) ; Core : v1 `origin fork`, `derived_from jarvis.checklist v1`, `created_by user` ; liste : badge `Fork` + « de jarvis.checklist v1 », ligne focalisée ; avis « Fork publié… l'original n'a pas changé » ; chaîne « Fork de jarvis.checklist v1 » ; aperçu rouge (`--jv-accent` `#ff4d5e`, un seul iframe) — `fork-listed.png` |
| Lien de parent | clic sur « jarvis.checklist v1 » → la base est sélectionnée, focus sur son titre |
| Publié par le cerveau | vue fermée ; `POST {Core}/v1/prefabs` acteur `brain` (`lab.brief-window`, `201`) ; réouverture : la recherche « check » est gardée (la case la montre), `/` puis effacer → `lab.brief-window` `Custom` listé, sans rechargement de page — `brain-prefab-after-reopen.png` |
| Base modifiée | filtre « Base modifiée » → `jarvis.table` seul ; note de protection + « modifié à votre demande une fois » ; historique : `v2 ÉDITION DE BASE par JARVIS · depuis v1`, citation « Jarvis, modifie le prefab de base tableau : accent orange par défaut, s'il te plaît. », « Confirmée par vous · témoin : conversation_event:… » — `base-edited-top.png`, `base-edited-history.png` |
| Thèmes | Cosmos : vue identique (jetons de la page), dock en icônes — `library-cosmos.png` |
| Étroit (760 px) | liste au-dessus du détail, aucun défilement horizontal (`scrollWidth = clientWidth = 760`) — `library-narrow.png` |
| Console | aucune erreur ni exception ; un seul avertissement, attendu : `prefabs.fork_failed {code: base_protected}` |

## Passes de design (lues sur les captures)

1. Noms accessibles en capitales (« PREFABS », « BASE MODIFIÉE… ») : Chrome
   reporte le `text-transform` dans le nom → `aria-label` en clair sur le
   dialogue, la recherche, la famille, les filtres et chaque ligne.
2. Deux badges pour une base modifiée dans la liste, un seul dans la légende →
   un seul badge ambre « Base modifiée à votre demande » partout.
3. Après un fork, le détail gardait le défilement du formulaire (avis hors de
   vue) → retour en haut à chaque changement de prefab. Note de protection à
   la largeur de son texte ; aperçu 360 px ; aide d'identifiant raccourcie ;
   bordure rouge retirée dès la frappe ; légende de citation en casse normale.
4. Détecteur `/impeccable` (`detect.mjs`) sur le module et la feuille : aucun
   constat.

## Constats hors périmètre

- La date de publication de `jarvis.table` v1 (paquet livré, S05) est
  postérieure à celle de son édition v2 faite pendant la preuve : la
  publication livrée porte une date fixe, pas celle de l'installation.
