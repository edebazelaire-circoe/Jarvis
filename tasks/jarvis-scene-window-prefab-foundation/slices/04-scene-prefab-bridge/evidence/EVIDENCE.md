# Slice 04 — preuve navigateur (pont scène ↔ prefab)

## Montage

- Vrai Chrome installé, `--headless=new`, profil jetable `--user-data-dir`
  (supprimé après), piloté par CDP : `browser_probe.mjs` (même méthode que la
  Slice 03). Aucune fenêtre ouverte dans le Chrome de l'utilisateur.
- Core (`python -m jarvis core`, `JARVIS_CORE_PORT=18993`, hôte par défaut
  `127.77.0.1`) et Control Center (`python -m jarvis control-center`,
  `JARVIS_UI_PORT=18994`, `JARVIS_SCENE_ENABLED=1`, visualiseur coupé) lancés
  depuis le worktree `bpf`, `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR` dans un
  scratch de session. Ports 17653/17654 (Jarvis vivant) jamais touchés. Les
  deux arbres de processus ont été arrêtés après le run (plus aucune écoute sur
  18993/18994).
- Bibliothèque de scratch : `test.counter@1` publié par
  `tests/fakes/prefabs.install_version` ; aucun code ne le nomme.
- Fenêtre créée **par l'utilisateur** à travers le Control Center :

  ```
  POST /api/scene/commands  {"schema_version":1,"op":"upsert_object","object_id":"counter-1",
    "fields":{"kind":"window","category":"note","representation":"window",
      "geometry":{"x":-60,"y":-40,"w":56,"h":34},
      "payload":{"title":"Compteur prefab","summary":"Compteur de test (S04)","items":[],
        "prefab":{"id":"test.counter","version":1,"props":{"label":"Clics","accent":"#6fe3a4"},"data":{"count":3}}}}}
  -> 200 outcome applied, revision 1
  ```

  Même commande avec `version: 7` : `200 {"outcome":"invalid","reason":"prefab_invalid",
  "detail":"counter-bad: unknown_version: test.counter has no version 7"}` (rien commis, révision 1)
  — corps complet dans `create-refused.json`.
- Deux runs complets, sur deux scratchs neufs ; le second sur le code commis
  final (le contact LRU de `syncScene` ajouté entre les deux). Mêmes résultats
  à chaque étape ; les fichiers ci-dessous sont ceux du second run.

Relance : `node browser_probe.mjs http://127.0.0.1:18994/ "<chrome.exe>" . http://127.77.0.1:18993 <runtime>/core.token`

## Résultats (`browser-results.json`, captures PNG)

| Preuve | Observé |
| --- | --- |
| Dessin | nœud `sc-window … sc-prefab-window`, enfants `sc-head`, `sc-wtitle`, `sc-prefab-slot`, `sc-grip` ; iframe `sandbox="allow-scripts"`, hauteur 99 px rapportée par le cadre ; `data-representation="window"` |
| Cadre | origine `null`, compteur `3`, libellé `Clics`, `--jv-accent` = `#6fe3a4` (prop `accent`) — `scene-prefab.png` |
| Sélection (clic sur la tête) | `sc-selected`, `JarvisScene.inspect().selected = "counter-1"` |
| Glisser par la tête (souris CDP) | géométrie `(-60,-40)` → `(-25,-22.5)`, `pinned_by_user: true` (Décision 9), icône d'épingle dans la tête, révision 3 ; **même iframe** (marqueur posé sur l'élément conservé) |
| Redimensionner par la poignée | `56×34` → `78.5×40`, révision 5 ; même iframe |
| Bare Hands (`JarvisScene.frames`) | `begin` rend `{representation: "window", box}` ; `preview` + `commit` → `x -25 → -65`, révision 6 ; même iframe |
| Vrai clic « +1 » dans le cadre | événement `incremented {count: 4}` avec `basis {count: 3}` → Core `applied` (révision 7, `data` complétée des défauts : `{count: 4, notes: "", history: []}`) → flux de scène → `update` → le cadre affiche `4` ; même iframe (aucun remontage) — `scene-prefab-clicked.png` |
| Anneau | `GET /api/prefabs/events` : une entrée `seq 1 … incremented state {count: 4} applied` |
| Basis périmée (envoyée par la page, `actor: "brain"`) | `200 {"outcome":"stale","reason":"stale","detail":"data.count changed since the frame last saw it","revision":7}` : rien écrit, l'acteur forcé à `user` par le relais |
| Clé non déclarée | `200 {"outcome":"refused","reason":"invalid_event","detail":"payload writes undeclared keys ['notes']; incremented writes ['count', 'history']"}` |
| Rechargement de la page | nouveau cadre (marqueur absent), compteur **`4`** (état de Core, révision 7), géométrie et épingle intactes — `scene-prefab-reloaded.png` |
| Capture (Core, acteur brain) | `POST /v1/scene/captures` → 200 (PNG rendu et envoyé par la page meneuse visible) ; l'image montre tête, titre, ligne `prefab test.counter@1` et le résumé `Compteur de test (S04)` — `scene-capture.png` |
| Console de la page | `scene.prefab_mounted` (×2 : avant et après rechargement), `scene.prefab_event` ; aucune erreur ni exception |

## Remarques

- Premier run seulement : après le rechargement, une révision 8 avait ramené
  la hauteur de `40` à `38.5`. `fitBrainWindows` ajuste une fenêtre dont la
  page n'a pas vu le redimensionnement dans **cette** vie de page (`userSized`
  est local), comme pour une fenêtre legacy ; la hauteur naturelle est celle
  que le cadre a rapportée. Non reproduit au second run (révision 7 gardée) ;
  comportement du chemin legacy, pas du pont.
- Un cadre sandboxé ne se rastérise pas depuis la page : la capture montre le
  repli dit (limite documentée, `docs/prefabs.md` › *Capture*).
