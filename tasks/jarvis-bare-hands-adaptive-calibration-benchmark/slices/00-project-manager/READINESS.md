# Slice 00 — Registre de readiness

État : **READY**

Date : 2026-09-25. Branche : `task/jarvis-bare-hands-adaptive-calibration-benchmark`, créée sur `5ee06d7` (= `main` @ `f2005eb`, le SHA revu par le handoff, + un commit de correctifs non commités trouvé sur `main`, voir D0). `origin/main...main` : `0 0` au démarrage.

---

## 1. Ce que le handoff déclare

Successeur de `jarvis-bare-hands-ui-calibration-refinement`, fusionnée en `e684a46` — **vérifié ancêtre de HEAD** (`git merge-base --is-ancestor`). Aucune branche active (`task/jarvis-mcp-semantic-batch-inspector`, `fix/orb-live-state-colors`, `fix/session-par-lancement`, `fix/wave-amplitude-orchestration-color`) n'a de diff non fusionné contre HEAD : aucun travail concurrent sur Bare Hands, voix, MCP ou scène.

## 2. Audit aveugle — faits du handoff confrontés au code (HEAD `5ee06d7`)

Conduit par deux audits en lecture seule (moteur Bare Hands ; voix/agent/MCP) avant confrontation aux conclusions du handoff. « core » = `jarvis/runtime/control_center_barehands.js` (7021 lignes).

| Fait déclaré | Verdict | Preuve |
| --- | --- | --- |
| Défauts pincement `.28/.42/2/2/60/400` | VRAI | core:23-50 ; + `releaseDeltaRatio:.15` (core:44, apporté par D0) |
| Filtre pointeur `minCutoffHz/betaCutoff/dCutoffHz`… | VRAI | core:67-73, validés core:185, 212-215 ; aucun n'est un réglage utilisateur |
| `targetAssistPx`, hystérésis de zone, candidat le plus proche, survol | PARTIEL | assist core:159, rayon = `targetAssistPx × assistance × 2` (core:1756-1765) ; **survol limité aux `capsule`/`window`** (core:4283, contracts:749) — boutons et étoiles `point`/`signal` exclus |
| Réglages assistance/sensibilité appliqués en direct | PARTIEL | en direct depuis les curseurs de la page seulement ; un `settings_set` serveur n'atteint la page qu'au rechargement (core:5192-5197) |
| Champs de profil | PARTIEL | ratios et `travelSlopNorm` lus (core:4797-4806, 5087-5101) ; **`jitterPx` et `reachNorm` lus par personne** mais dans `CALIBRATING_KEYS` (contracts:1178, `barehands_profile.py:103`) → `calibrated:true` sans effet moteur |
| Dérivation par quantile sur toutes les images | VRAI | `deriveHysteresis` q.1/q.9 (calibration:293-314) |
| Machine `INTRO→ARMED→RUNNING→RESULT→NEXT`, auto-avance | VRAI | `resultMs:1100` (calibration:2633-2634) |
| Jeton dessiné dès qu'une main est suivie | VRAI | `overlay.render` pour chaque main suivie en ACTIVE (core:3463, 3977-4010) ; SLEEP : anneau de réveil seul |
| Recorder scalaire, liste blanche | VRAI | recorder.js:186-191, `assertDerivedOnly` :361-397 ; miroir Python `barehands_trace.py:80-85` |
| Pincement primaire dans le vide ferme le menu contextuel | **FAUX (lacune confirmée)** | `dom.emit` sort sans cible (core:4429-4433) ; menu fermé seulement sur `mousedown` DOM |
| Voix n'expose pas de réglage arbitraire | VRAI avec réserve | `barehands_mcp.py` : 5 outils sans argument ; mais `jarvis-console` `settings_set barehands.*` écrit et **persiste** ces réglages (settings_mcp.py:85-123) |

### Baseline mesurée (branch point `5ee06d7`, worktree détaché `C:/Projects/jarvis/bwt`)

Suite complète `tests/unit` (275 fichiers, 8 lots au premier plan) : **8478 passés, 9 échecs, 4 ignorés**. Bare Hands seul : 22 fichiers `test_barehands_*.py`, **531 tests collectés**.

Échecs hérités — **pas à l'implémenteur, ne pas corriger dans une Slice** :

| Fichier | # | Cause |
| --- | --- | --- |
| `test_barehands_interaction_js.py` | 2 | `…moved_by_one_zone_through_the_real_engine`, `…resizes_only_on_two_distinct_compatible_zones` — attentes de cadre dépassées depuis `6116f35`/scène 2D ; échouent aussi sans D0 |
| `test_barehands_tutorial_retired_js.py` | 1 | `…deprecated_and_opens_calibration` : cherche « l'interrupteur est à lui », le prompt dit désormais « il est à toi comme à lui » |
| `test_brain_delegation.py` | 1 | `…agent_tool_available` : attend `BRAIN_SYSTEM_PROMPT` exact, le prompt inclut maintenant `BRAIN_SETTINGS_PROMPT` |
| `test_scene_group_drag_js.py` | 5 | **vrai bug produit** : `ReferenceError: orbitTurns is not defined` (`control_center_scene_interact.js:1414`) — mauvaise fusion probable de `fix/scene-deplacement-2d`. Issue `ISSUE-01` |

## 3. Divergences et réparations de planification

### D0 — correctifs non commités sur `main`

`main` portait 7 fichiers modifiés non commités (10:06 le 25/09, retours utilisateur : relâchement relatif `releaseDeltaRatio`, prise d'une fenêtre à deux mains, étape AIM exigeant d'être sur le point). Verts hors échecs hérités. **Décidé par agent 0 (autonomie déléguée) :** préservés tels quels dans `fix/barehands-retours-2026-09-25` (`5ee06d7`), base de la branche de tâche ; `main` inchangé. La fusion de ce correctif dans `main` reste une décision humaine. Dette documentaire : `releaseDeltaRatio` absent de `docs/barehands-contracts.md` → Slice 01.

### D1 — l'agent de calibration ne peut pas être un processus séparé muni d'outils propres

Le cerveau est le CLI Claude ; ses outils MCP sont fixés **au lancement** (`claude_local.py:874-955`) ; les profils restreints n'ont pas de MCP (`--strict-mcp-config`). Aucun jeu d'outils « à la session » n'existe. **Décidé par agent 0 :** l'« agent de calibration » est le cerveau existant en **mode calibration**, sur le patron du mode présentation : drapeau de contexte par tour (`observe_interaction_mode`, `control_center_brain.py:274-288`) + addendum de brief + outils `calibration_*` toujours déclarés par le serveur `jarvis-barehands` qui **refusent** hors session active (code nommé). Slice 06 porte ce choix.

### D2 — le canal de commandes ne transporte ni argument ni valeur de retour

Outils sans argument (`barehands_mcp.py:384-389`), reçu fermé `{outcome,lifecycle,code,reason}` ≤ 1 Ko (`domain/barehands_command.py:209-243`). `apply_trial` a besoin d'un patch en entrée et d'une relecture des valeurs effectives en sortie. **Réparation :** Slice 04 construit le gestionnaire d'essai **dans la page** (le moteur y vit) avec API publique `JarvisBarehands.trial.*` et reçus structurés ; Slice 06 étend le transport (commande à charge utile bornée + reçu structuré, patron `scene_capture`) sans relâcher les garanties du canal existant.

### D3 — `settings_set` contourne toute couche d'essai

`jarvis-console` persiste `barehands.*` immédiatement. Slice 06 : pendant une session de calibration, le brief interdit `settings_set barehands.*` au profit des outils d'essai, et le reçu d'`accept` est la seule persistance.

### D4 — métriques « calibrantes » sans lecteur

`jitterPx`, `reachNorm` : Slice 04 (règle « un paramètre sans lecteur moteur ne peut être annoncé comme calibré ») — les brancher ou les retirer de `CALIBRATING_KEYS`, avec migration. Avancé de la Slice 10 à la Slice 04. Idem `RATIO = 26/12` figé entre `clickSlop` et `dragSlop` (core:5086) → Slice 04.

### D5 — dérives documentaires

`travel_slop_norm` : doc 0,002–0,15 contre code 0,002–0,014 ; `releaseDeltaRatio` non documenté ; aide MCP de `sensitivity` fausse (« facteur de déplacement du pointeur », settings_mcp.py:108-109 — elle divise les tolérances clic/glissement). → Slice 01.

## 4. Bloqueurs de planification résolus

- **Task Type :** vocabulaire introuvable (`docs/` n'en contient aucun). Porte levée comme pour les cinq tâches précédentes ; `task_type: null` conservé, ce paragraphe tient lieu de résolution. Décidé par agent 0 (autonomie déléguée).
- **Fraîcheur :** vérification ciblée avant chaque dispatch (voix/agent, catalogue MCP, scène, contrats Bare Hands).
- **Contrôles humains HV-BH-ADAPT-02…10 :** exigent une webcam réelle. La QA machine avance Slice par Slice ; les HV sont regroupés dans la liste de contrôles de clôture, dans l'ordre des Slices, et ne remplacent aucune QA machine.

## 5. Ordonnancement

Presque toutes les Slices écrivent dans `control_center_barehands.js` (7021 lignes) et `…_calibration.js` (2959). **Un seul implémenteur à la fois, un seul arbre** ; QA à mutation compte comme implémenteur. Ordre séquentiel : 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 (08 n'est pas avancée en parallèle malgré le graphe).

## 6. Porte

Readiness **READY**.
