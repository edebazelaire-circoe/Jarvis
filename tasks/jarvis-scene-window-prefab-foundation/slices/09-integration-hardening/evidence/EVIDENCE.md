# Slice 09 — preuves : stress du cycle de vie, traces réelles du cerveau, confidentialité

Date : 2026-10-03. Worktree `bpf`, branche `task/jarvis-scene-window-prefab-foundation`.
Ports 18993 (Core) / 18994 (Control Center) seulement, sur des racines de scratch neuves,
arrêtés après chaque passe ; 17653/17654 (Jarvis vivant) jamais touchés. Un seul Chrome à la fois,
`--headless=new`, profil jetable `--user-data-dir` supprimé après.

## 1. Stress (`stress_probe.mjs`, `stress_core_journal.py`)

Vrai Chrome piloté par CDP sur la page servie par un vrai CC relié à un vrai Core
(`python -m jarvis core` / `control-center`, `JARVIS_SCENE_ENABLED=1`, visualiseur coupé).
Commandes utilisateur `POST /api/scene/commands`. Compteurs du moteur : `Memory.getDOMCounters`
après deux GC ; écouteurs `message` de la page : `DOMDebugger.getEventListeners(window)`.

Relance : `node stress_probe.mjs http://127.0.0.1:18994/ "<chrome.exe>" .` puis
`python stress_core_journal.py <runtime>/trace.jsonl stress-core-journal.json`.

| Mesure | Observé (`stress-results.json`, passe finale) |
| --- | --- |
| 200 cycles créer → cadre monté → archiver → cadre démonté (`jarvis.window@1`) | 0 refus ; au plus **1** cadre à tout moment ; 42 s |
| Croissance (départ → cycle 50/100/150/200 → fin) | documents 1 → 1, nœuds 1060 → 1060, écouteurs JS 236 → 236, écouteurs `message` 0 → 0 (l'hôte n'écoute que tant qu'un cadre existe), cibles `about:srcdoc` 0 → 0 ; **croissance nulle** |
| 30 fenêtres prefab simultanées | **24** cadres vivants + **6** cartes « En pause : au plus 24 prefabs vivants… » (`stress-30-windows.png`) |
| Sélection d'une fenêtre en pause (vrai clic sur sa tête) | elle reprend, une autre passe en pause : toujours 24 + 6 |
| Tout archiver | 0 cadre, 0 carte, compteurs identiques au départ |
| Rafale côté cadre : 100 `jarvis.emit` synchrones | **10** enregistrés par Core (plafond de l'hôte 10/s), 2 lignes console `scene.prefab_event_rate_limited` |
| Rafale côté Core : 200 `POST /api/prefabs/events` simultanés | 50 `recorded`, 150 `429 rate_limited` (seau 30 + recharge pendant la rafale) ; un envoi 1,5 s après : 200 |
| Journal de Core pendant toute la passe (`stress-core-journal.json`) | **0** erreur `core.*` ; `core.prefab.event_rate_limited` : **1** avertissement + **1** fin ; 60 `core.prefab.event recorded` |
| Console de la page | 0 erreur, 0 exception |

Constat corrigé par cette Slice (`cdab695`) : la **première** passe donnait 19 avertissements +
20 fins pour 148 refus — chaque jeton rendu pendant le flot clôturait la rafale et le refus suivant en
rouvrait une. Une rafale ne se clôt plus qu'au premier événement admis seau plein (≥ 1 s de calme).
Constat non corrigé (Issue `prefab-relay-logs-each-rate-limited-request`) : le relais du CC journalise
chaque 429 en avertissement (`prefab.request.relayed`, 150 lignes) — aucune erreur.

## 2. Traces réelles du cerveau (agent-trace-analysis)

Dispositif : harnais S07 étendu, `trace_s9.py` (Core + CC isolés, CC lancé par
`../../07-agent-prefab-operations/evidence/run_cc_strict.py` en `--strict-mcp-config`, CLI Claude
Code 2.1.286, consigne de production `conversation_display_session`). Tours réels par
`POST /api/agent/ask` (`context.addressing = addressed`). Le travail délégué (sous-agents) est attendu
dans le même fichier de tour. `tick` = vrais clics souris dans le cadre (`tick_probe.mjs`).
Sorties : `out/*.json` (expurgées par `redact_s9.py`), résumé par `summarize_s9.py <tour>`.
**9 tours utilisateur**, 3 sessions CLI, coût rapporté par le CLI : 0,763 $ + 0,984 $ + 0,332 $ = **2,08 $**.

| # | Entrée | Chemin observé | Verdict |
| --- | --- | --- | --- |
| t1 découverte → instancier | « Affiche-moi une checklist pour préparer la démo de vendredi : … » | délégué (général) : `scene_inspect` → `prefab_search "checklist"` (1 ligne) → `prefab_get jarvis.checklist` → `scene_create_object kind=window prefab jarvis.checklist` (4 éléments, `done:false`) → applied | **PASS** — réutilise `jarvis.checklist`, rien d'inventé, aucun HTML |
| t2 interagir | 2 vrais clics souris dans le cadre (Chrome sans tête) | `item_toggled` ×2 `state` → `applied` ; Core : `salle`, `projecteur` cochés | **PASS** |
| t3 lire l'état | « Qu'est-ce qui est déjà fait dans la checklist de la démo ? » | `scene_get` de la fenêtre → « Deux points sont faits : la salle… le projecteur… Il reste… » | **PASS** — lit l'état de Core, ne devine pas |
| t4 fork/save | « Fais-en une variante avec un accent rouge et une priorité sur chaque élément, et garde-la… « checklist démo rouge » » | délégué (code) : `prefab_get include_source` → `scene_get` → `prefab_validate` ok → `prefab_save` `custom.checklist-demo-rouge` v1 **`fork`, `derived_from jarvis.checklist@1`** → `scene_update_object` (même fenêtre, coches gardées) | **PASS** — base intacte |
| t5 redécouvrir | « Quels modèles de checklist as-tu dans la bibliothèque ? » | `prefab_search "checklist"` → 2 lignes : base + variante | **PASS** |
| t6 | nouvelle Session (`POST /api/sessions/new`) | nouvelle conversation, `agent_session_id: null` → nouvelle session CLI | – |
| t7 réutiliser (nouvelle Session) | « Affiche la checklist démo rouge pour la réunion de lundi : … » | `prefab_search` (2) → `prefab_get custom.checklist-demo-rouge` → `scene_create_object` avec ce prefab → applied | **PASS** |
| t8 « améliore le prefab fenêtre » (implicite) | « Améliore le prefab fenêtre, je le trouve un peu terne. » | délégué : le cerveau lit « fenêtre » comme la fenêtre affichée (la variante rouge), le dit ; `prefab_validate` ×2 → `prefab_save` `custom.checklist-demo-rouge` v2 **`revision`** → fenêtre montée en v2 ; `scene_capture` ×2 `no_visible_page` (aucune page ouverte dans le harnais) | **PASS** pour la règle (aucune base touchée, aucun `prefab_edit_base`) ; FLAGGED : interprétation |
| t9 précision, toujours implicite | « Non, je parlais du modèle de fenêtre générique, pas de la checklist. Il est terne. » | `prefab_search family=window` → « jarvis.window est un prefab de base… seulement si vous me le demandez expressément… une variante… Que préférez-vous ? » ; rien écrit | **PASS** — demande, n'édite pas |
| t10 re-trace S07 c2 (confirmation tapée hors admission de Core) | « Oui, je confirme : modifie le prefab de base jarvis.window pour que l'accent soit orange par défaut, rien d'autre. » | délégué : `prefab_validate` ok → `prefab_edit_base` → `witness_lookup found:false` → `base_edit_unconfirmed` ; le sous-agent écrit « cette vérification ne peut pas passer depuis mon côté » ; **le cerveau principal relance** `prefab_edit_base` (même citation) → même refus ; rien écrit | **FAIL** (relance) → corrigé `d0d50cf` |
| t11 re-trace c2 après correctif (pile neuve) | même phrase | délégué : `prefab_validate` ok → `prefab_edit_base` → refus ; **aucune relance** ; « Ce refus vaut pour tous les appelants, donc je ne réessaie pas… une variante orange… ? » ; bibliothèque vide | **PASS** |

**Efficacité.** Lectures avant écritures partout ; un seul `prefab_search` par besoin ; `prefab_validate`
avant chaque `prefab_save`/`prefab_edit_base`. Délégation des tours d'écriture (t1, t4, t8, t10, t11)
selon la règle existante du cerveau ; t3, t5, t7, t9 dans le tour.

**Constats.**
- FIXED (`d0d50cf`) — t10 : relance du cerveau principal après le refus d'un sous-agent. Cause : le
  sous-agent a supposé que la vérification dépendait de l'appelant. Le refus dit maintenant qu'il est
  le même pour tout appelant ; `BRAIN_PREFAB_PROMPT` dit qu'un refus, le sien ou celui d'un sous-agent,
  est définitif. Re-trace t11 : PASS.
- FLAGGED — t8 : « prefab fenêtre » lu comme « la fenêtre affichée » ; hypothèse dite à l'utilisateur,
  aucune base touchée, mais la variante a été modifiée sans question. À regarder en HV-PREFAB-E2E-01 (5).
- FLAGGED — t11 : la réponse suggère de « reformuler la demande en nommant jarvis.window » ; reformuler
  dans le même canal (CC) ne suffit pas : la confirmation doit être dite à la voix (Issue
  `base-edit-witness-needs-core-intake`).
- FLAGGED — t11 : le sous-agent a lu le dépôt par `Bash grep` pour trouver la couleur ; outils shell
  du cerveau préexistants, aucune écriture.
- OPTIMIZATION — t7 : un `Bash echo` inutile ; t1 : `scene_inspect` lu sans être utilisé.
- Préexistant, hors périmètre : `agent.subagent.conversation_unattributed` pour les sous-agents nés
  d'un tour posté au CC ; `agent.turn_over_budget` (8 s) sur les tours qui délèguent.

## 3. Confidentialité (`privacy_sweep.py`)

`python privacy_sweep.py` balaie tout `tasks/jarvis-scene-window-prefab-foundation/**` (dossier
personnel sous ses formes Windows/JSON/Git Bash, noms d'utilisateur de la machine, adresses, formes de
jeton ; cibles lues à l'exécution) ; `tests/unit/test_task_evidence_privacy.py` le fait tourner.
Fuites trouvées puis corrigées : chemin de scratch dans `04…/browser-results.json`, nom de session
utilisé comme donnée d'exemple dans les sondes S05 et leurs résultats (+ 11 PNG regénérés). Résultat
final : `ok: 138 fichiers texte` (84 images, vérifiées à l'œil pour les captures de tableau S05).
Les versions antérieures restent dans l'historique git des commits précédents (réécriture = décision
humaine).
