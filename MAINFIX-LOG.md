# MAINFIX — ce que `main` avait perdu, et comment c'est revenu

Branche `fix/main-baseline-and-timeline`, sur `origin/main` (`b86f228`).

Sur `b86f228`, neuf tests décrivent un comportement dont l'implémentation n'existe
plus. Ce ne sont pas des tests écrits en avance : le code a existé, puis a été
effacé par une fusion. Ce fichier dit lequel, quand, et ce qui est revenu.

## 1. Le fait mesuré : la fusion `10b455e`

`10b455e` — « Merge branch 'main' of https://github.com/edebazelaire-circoe/Jarvis »,
17 septembre 2026 — réunit deux côtés :

| | commit | ce qu'il portait |
| --- | --- | --- |
| notre côté | `c914f7d` (par `56c7892`, `a6056be`) | le choix d'aiguillage en deux temps (`90d3234`) et l'état « armé » de la carte Brain (`56c7892`) |
| l'autre côté | `7ed67bb` | le catalogue, la section « Configuration avancée des sous-agents », le mode de délégation |

Base commune : `f0aec10`.

Mesure ligne à ligne des ajouts de chaque côté, absents du résultat de la fusion :

```
=== merge 10b455e, côté c914f7d ===
  jarvis/runtime/agent_routing.py    : 41/41 lignes ajoutées absentes du résultat
  jarvis/runtime/control_center.html : 94/95 lignes ajoutées absentes du résultat
=== merge 10b455e, côté 7ed67bb ===
  (rien)
```

La fusion a donc gardé l'autre côté **en entier** pour ces deux fichiers, et jeté
le nôtre. Les *tests*, eux, ont bien été fusionnés (`tests/unit/test_agent_routing_settings.py`,
`test_brain_card_state.py` gardés tels quels ; `test_routing_settings_screen.py`
fusionné en gardant les tests des **deux** côtés). D'où l'état de `main` :
la spécification est là, l'implémentation non.

Les deux autres fusions récentes ont été passées au même crible :
`d7e9ca4` (observabilité des conversations) et `7ed67bb` ne perdent **rien**.
Aucun fichier, dans aucune fusion de l'historique de `main`, n'est revenu à la
version de la base commune.

### Correction d'un point du pré-diagnostic

Il avait été rapporté que `9ff56b7` et `4833e62` portaient encore la version à
13 `def` de `agent_routing.py`. C'est faux : ces deux commits sont sur la branche
`7ed67bb`, issue de `f0aec10`, qui n'a **jamais** eu `group_by_harness`. Les seuls
commits qui l'ont sont `90d3234`, `56c7892`, `a6056be`, `c914f7d`. Le compte de
`def` est par ailleurs trompeur : `main` en a *plus* (13 contre 10), parce que le
mode de délégation en a ajouté trois — seul `group_by_harness` manquait.

## 2. Ce qui a été perdu, et d'où il revient

### `jarvis/runtime/agent_routing.py` — depuis `90d3234`

- `group_by_harness(candidates)` : les mêmes candidats rangés en deux niveaux
  (harness → ses modèles). Restauré à l'identique, docstring française comprise.
- `build_candidates` : remplissage de `agent_label` / `model_label` sur chaque
  `ModelCandidate`, et extraction de `model_label` en variable.
- `with_saved` : `agent_label` / `model_label` sur le candidat fantôme.
- `describe` : la clé `"harnesses"`, et le paragraphe de docstring qui explique
  que c'est la même information que `candidates`, pas une autre vérité.

`jarvis/domain/routing.py` avait **survécu** à la fusion : les champs
`agent_label` / `model_label` de `ModelCandidate` étaient toujours là, mais plus
personne ne les remplissait. C'est ce qui rendait la perte silencieuse.

Adaptations rendues nécessaires par ce qui a changé depuis :

- `with_saved` prend maintenant `unavailable_reasons_by_agent` (catalogue
  fournisseur absent ou périmé). Les deux moitiés de libellé ont été ajoutées
  **sans** toucher à ce paramètre ni à la raison qu'il calcule.
- Le mode de délégation (`DELEGATION_MODES`, `delegation_mode`,
  `apply_delegation_mode`, `describe_delegation_modes`) est postérieur : conservé
  intact.
- `jarvis/runtime/control_center.py` n'a demandé aucune retouche :
  `routing_candidates` sert `**agent_routing.describe(...)`, donc `harnesses`
  arrive tout seul dans la réponse.

### `jarvis/runtime/control_center.html`, carte Brain — depuis `56c7892`

Le cas vécu : un Brain passé sur Codex s'affichait « arrêté » quoi qu'on fasse,
« Redémarrer » réussissait en silence, « Arrêter » restait grisé. `codex exec`
n'a pas de processus permanent : l'agent se déclare `ready` entre deux tours, et
la page ne connaissait que `running`.

Restauré tel quel, commentaire français compris :

- `brainArmed(b)` — `running` **ou** `ready` ;
- `brainState` reconnaît `ready` → « prêt » ;
- `timerHtml`, la ligne d'activité de `cardHtml` et `menuItems` se règlent sur
  « armé », plus sur un état de processus.

Côté serveur, `CodexLocalAgent.state` renvoyait déjà `ready` : rien à restaurer
là (le test correspondant passait déjà sur `b86f228`).

### `jarvis/runtime/control_center.html`, écran d'aiguillage — depuis `90d3234`

C'est la seule partie qui **ne pouvait pas** revenir telle quelle : entre-temps,
l'écran d'aiguillage a cessé d'être un onglet. Il est devenu la section
« Configuration avancée des sous-agents » de l'onglet Agent / CLI, chargée à la
demande, avec garde de révision de rendu et compteur de génération. Le
comportement en deux temps a donc été reposé **dans cette structure-là** :

- `harnessOf`, `modelOf`, `routingPick`, `routingEntry`, `candidateLabel(state,ref)`
  — restaurés à l'identique ;
- `routingRow(profile,ref,rank,state)` — restauré : la ligne décrit désormais un
  candidat **retenu** (rang, « monter », « retirer », raison d'indisponibilité),
  au lieu d'une case à cocher par couple possible ;
- `routingPicker(profile,state)` — restauré : deux sélecteurs en cascade, le
  second n'offrant que les modèles du harness choisi, et un bouton « ajouter » ;
- `routingAdvancedBody` — la liste plate de tous les couples est remplacée par
  « ce qui est retenu + le sélecteur », en gardant ce que la section avait gagné
  depuis (case « Profil actif », état des sources, bouton « rafraîchir », état
  d'erreur avec « réessayer ») ;
- les gestes (`harness`, `model`, `add`, `drop`, `up`, `fallback`) sont revenus
  dans `bindRoutingAdvanced`, pas dans `bindTab` : c'est la section rechargée qui
  les porte maintenant. Choisir ne salit pas le brouillon ; seul « ajouter » pose
  `SET.dirty`.

Deux écarts assumés par rapport à `90d3234`, pour ne pas ressusciter du code mort :

1. **`data-routing-enabled` n'est pas revenu.** L'interrupteur d'aiguillage est
   désormais le sélecteur « Mode des sous-agents » (`auto` / `duplicate`), qui est
   la projection canonique de `agent_routing.enabled`. La liaison de ce sélecteur
   a été extraite de `bindTab` dans `bindDelegationMode()`, où elle peut être
   nommée et expliquée pour ce qu'elle est.
2. **`tabRouting()` ne rend plus un onglet.** Elle est devenue la fonction qui
   *demande au serveur* l'état de l'écran d'aiguillage, appelée par
   `hydrateRoutingAdvanced`, qui garde la garde de révision et le compteur de
   génération. Un échec revient en état affichable (`{ok:false,error}`) : la
   section dit pourquoi et propose « réessayer », elle ne reste jamais vide et
   muette.

## 3. Ce qui n'a délibérément pas été restauré

- L'onglet « Aiguillage » et son entrée dans `TABS`. Il a été retiré exprès
  (`test_policy_ui_is_advanced_inside_agent_cli_and_saved_canonically` l'interdit),
  et l'écran vit maintenant dans Agent / CLI.
- L'interrupteur `routing.enabled` de la page et l'envoi
  `routing:{enabled:...}` : remplacés, exprès, par `cli.delegation_mode`.
- `candidateLabel(c)` à un seul argument : la version à deux arguments
  (`state,ref`) la remplace, puisque le libellé se recompose depuis les harness.
- Rien d'autre n'a été touché : aucun symbole public ne manque dans
  `model_catalog.py`, `cli_catalog.py`, `domain/routing.py`, ni dans
  `control_center_*.js`, comparés à `90d3234`, `56c7892`, `9ff56b7` et `4833e62`.

## 4. Un test non protégé a dû bouger — à valider par l'agent 0

`tests/unit/test_agent_cli_settings_ui.py::test_agent_cli_sections_are_in_locked_order_and_advanced_policy_is_disclosed`
affirmait `"rank>=0?'checked'" in body`. Cette assertion épingle la **liste plate
à cases à cocher**, que les neuf tests protégés interdisent explicitement
(`assert "data-routing-candidate" not in page`). Les deux ne peuvent pas être
vraies en même temps : c'est le même conflit de fusion, vu depuis l'autre côté.

L'assertion a été remplacée par `"rank===0?'préféré'" in body`, qui tient le même
invariant dans le vocabulaire du choix en deux temps : la section dit ce qu'elle a
retenu, dans quel ordre, et pourquoi un candidat n'est pas utilisable. Aucune
autre assertion n'a été touchée, et **aucun des neuf tests** n'a été modifié.

Les deux autres échecs de ce fichier ont été réparés côté code, sans toucher aux
tests : le mot « Aiguillage » ne réapparaît pas dans la page, et `tabRouting` est
déclarée *après* `hydrateRoutingAdvanced` pour rester dans la tranche que
`test_advanced_policy_is_lazy_local_and_last_render_wins` exécute sous Node.

## 5. Documentation

`docs/OPERATIONS.md` décrivait « l'ordre des cases cochées est la préférence ».
Il n'y a plus de cases : le paragraphe dit maintenant le choix en deux temps et
ce que « monter » fait. `docs/ARCHITECTURE.md` ne décrit que l'existence de
`GET /api/routing/candidates` — toujours exact, laissé tel quel.

## 6. Validation

### Les neuf tests

Sur `b86f228` (avant) : **9 échecs / 25 passés**.

```
FAILED test_agent_routing_settings.py::test_the_candidates_are_also_served_grouped_by_harness_for_a_two_step_choice
FAILED test_agent_routing_settings.py::test_a_saved_candidate_that_vanished_keeps_its_place_in_the_two_step_choice
FAILED test_agent_routing_settings.py::test_the_described_payload_carries_no_secret_and_no_hardcoded_model
FAILED test_routing_settings_screen.py::test_the_candidates_endpoint_measures_instead_of_assuming
FAILED test_routing_settings_screen.py::test_the_page_shows_why_a_candidate_cannot_be_used
FAILED test_routing_settings_screen.py::test_the_choice_is_made_in_two_steps_harness_then_model
FAILED test_routing_settings_screen.py::test_changing_the_harness_clears_the_model_and_only_adding_changes_the_policy
FAILED test_brain_card_state.py::test_the_card_says_a_ready_brain_is_armed_not_stopped
FAILED test_brain_card_state.py::test_start_stop_and_the_service_timer_follow_the_armed_state
9 failed, 25 passed
```

Sur cette branche (après) : **34 passés**.

### Suites voisines

`test_agent_cli_settings_ui`, `test_agent_routing`, `test_agent_routing_settings`,
`test_routing_settings_screen`, `test_routing_hook`, `test_brain_card_state`,
`test_settings_endpoints`, `test_settings_ia_contract`, `test_settings_workbench`,
`test_catalog_view`, `test_deployment`, `test_documented_routes`,
`test_v2_architecture` : **252 passés**.

Le JavaScript de la page est reparsé entier (`node --check` sur le bloc
`<script>`) après chaque retouche.

### Suite complète, en morceaux

L'hôte ne tient pas un pytest entier (≈ 2 Go libres) : six morceaux d'unitaires,
puis l'intégration, puis e2e + replay.

| morceau | résultat |
| --- | --- |
| unitaires 1/6 (30 fichiers) | 502 passés |
| unitaires 2/6 (23 fichiers) | 556 passés |
| unitaires 3/6 (27 fichiers) | 610 passés, 1 ignoré (`signals are POSIX-only`) |
| unitaires 4/6 (29 fichiers) | 575 passés, 2 ignorés (symlinks, modèle owner-voice absent) |
| unitaires 5/6 (30 fichiers) | 617 passés, 1 ignoré (modèle owner-voice absent) |
| unitaires 6/6 (28 fichiers) | 867 passés, 2 ignorés (`livekit` absent) |
| `tests/integration` | 287 passés, 4 ignorés (base d'état vivante, OpenAI en direct) |
| `tests/e2e` + `tests/replay` | 1 passé |

**3727 unitaires + 287 intégration + 1 e2e : 0 échec.** Tous les tests ignorés
le sont pour une raison d'environnement (POSIX, modèle non téléchargé, clé
absente), aucun à cause de ce changement.

`scripts/verify_release.py`, son unique sous-processus pytest neutralisé (la
suite ayant déjà tourné en morceaux) : `Release verification passed.`

### Recette au navigateur

Chrome à soi, en headless, profil jetable, port CDP à soi ; le ControlCenter
servi en processus sur un port libre — jamais le lanceur, qui ouvrirait un
onglet dans le Chrome de l'utilisateur. Les CLI et les catalogues fournisseurs
sont simulés (Claude Code disponible avec Modèle A / Modèle B, Codex CLI absent
du PATH), sans quoi l'écran dépendrait de la machine.

Verdict identique dans les deux thèmes (`classic`, `omega`) :

```json
{"harnesses":["Choisir un harness…","Claude Code","Codex CLI — indisponible"],
 "models":["Modèle par défaut du CLI","Modèle A","Modèle B"],
 "retenus":1,"plat":false}
```

Lu à l'écran : le second sélecteur n'offre que les modèles de Claude Code, le CLI
absent reste proposé avec sa raison, « ajouter » pose un candidat retenu
« Claude Code · Modèle B — disponible — préféré » avec « retirer », les autres
profils affichent « Choisir d'abord un harness », et la liste plate de tous les
couples (`data-routing-candidate`) a bien disparu.

Captures : `routing-two-step-classic.png`, `routing-two-step-omega.png`
(répertoire de travail de l'agent, hors dépôt).
