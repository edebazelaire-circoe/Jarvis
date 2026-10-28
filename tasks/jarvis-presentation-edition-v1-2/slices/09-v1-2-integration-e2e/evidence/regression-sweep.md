# Slice 09 A : balayage de régression complet

- Révision : `bfb66bd7` (branche `task/jarvis-presentation-edition-v1-2`, V1 00-10 + V1.2 00-08 fusionnées).
- Outil : `scripts/release_test_gate.py` contre `tests/known_failures.json` ; Python
  `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe` (3.14), Windows 11, Chrome local, du 27 au 28/10/2026.
- Parts lancées une par une en avant-plan. Chaque part CI est découpée en sous-parts emboîtées
  (`--shard K/4 --shard J/5` pour `unit`, `--shard K/10 --shard J/3 [--shard H/2]` pour `browser`) pour tenir
  dans 10 minutes par appel. Six sous-parts navigateur ont dépassé 10 minutes : l'outil les a basculées en
  arrière-plan et l'agent a attendu leur fin avant de lancer la suivante, sans chevauchement.
  Un seul écart : les sous-parts unit `u06` et `u07` ont tourné en même temps (deux appels partis dans le même
  message) ; les deux sont vertes.
- Le JARVIS vivant n'a pas été touché. Un Chrome orphelin du 27/10 à 01:31 (profil
  `%TEMP%\jarvis-pse-cdp-rcAUqI`, parent disparu, antérieur au balayage) a été arrêté par PID, sans `/T`.
- Rapports JSON et journaux de chaque sous-part : scratchpad de la session 448345f0, dossier `sweep/`.

## Tableau par part

| Part | Fichiers | Passés | Échecs listés | Échecs NON listés | Sautés | Durée (s) | Porte |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `release` | 33 | 902 | 0 | 0 | 4 | 264 | VERT |
| `unit` 1/4 (5 sous-parts) | 214 | 6 059 | 9 | 1 | 20 | 1 224 | ROUGE |
| `unit` 2/4 | 214 | 5 353 | 0 | 1 | 16 | 1 233 | ROUGE |
| `unit` 3/4 | 214 | 5 139 | 0 | 0 | 35 | 1 369 | VERT |
| `unit` 4/4 | 214 | 5 864 | 1 | 2 | 27 | 1 410 | ROUGE |
| **`unit` total** | **856** | **22 415** | **10** | **4** | **98** | **5 236** | **ROUGE** |
| `browser` 1/10 | 19 | 265 | 0 | 0 | 14 | 1 483 | VERT |
| `browser` 2/10 | 19 | 276 | 2 | 1 | 17 | 1 020 | ROUGE |
| `browser` 3/10 | 19 | 334 | 0 | 3 | 0 | 1 468 | ROUGE |
| `browser` 4/10 | 19 | 269 | 1 | 1 | 2 | 1 115 | ROUGE |
| `browser` 5/10 | 19 | 322 | 6 | 0 | 3 | 1 052 | VERT |
| `browser` 6/10 | 19 | 298 | 0 | 0 | 1 | 832 | VERT |
| `browser` 7/10 | 19 | 301 | 3 | 0 | 3 | 1 200 | VERT |
| `browser` 8/10 | 19 | 207 | 0 | 0 | 3 | 851 | VERT |
| `browser` 9/10 | 18 | 261 | 0 | 0 | 16 | 692 | VERT |
| `browser` 10/10 | 18 | 236 | 0 | 0 | 4 | 840 | VERT |
| **`browser` total** | **188** | **2 769** | **12** | **5** | **63** | **10 553** | **ROUGE** |

Détail des sous-parts `unit` (fichiers / passés / listés / non listés / sautés / s) :
u01 43/1235/0/0/1/265 · u02 43/1076/0/1/3/203 · u03 43/1194/2/0/6/177 · u04 43/1212/0/0/7/258 ·
u05 42/1342/7/0/3/322 · u06 43/1159/0/0/1/242 · u07 43/1061/0/0/4/244 · u08 43/803/0/0/2/299 ·
u09 43/1415/0/1/6/201 · u10 42/915/0/0/3/247 · u11 43/1010/0/0/23/164 · u12 43/1025/0/0/4/243 ·
u13 43/1164/0/0/4/224 · u14 43/980/0/0/1/514 · u15 42/960/0/0/3/224 · u16 43/1034/0/0/5/235 ·
u17 43/1040/1/0/15/374 · u18 43/1377/0/1/1/294 · u19 43/1143/0/1/2/251 · u20 42/1270/0/0/4/256.

Échecs listés : les 22 entrées `failing` ont toutes été VUES en échec (10 unit, 12 browser) ; aucune entrée
périmée, non vue ni expirée ; aucun intermittent listé ne s'est déclenché ; aucune session interrompue.

## Régressions de la V1.2 (échec reproductible, Slice identifiée)

### R1 — fermetures d'import Presentation : `jarvis.domain.research_freshness` en trop (Slice 03 V1.2)

- `tests/unit/test_presentation_attention.py::test_le_juge_d_attention_ne_charge_que_des_modules_declares`
- `tests/unit/test_presentation_intent.py::test_intent_and_port_modules_import_no_runtime_or_scene`
- `tests/unit/test_presentation_speculative.py::test_la_fermeture_du_service_speculatif_est_exactement_celle_qui_est_declaree`

Message commun : `{'unexpected': ['jarvis.domain.research_freshness'], 'declared_but_absent': []}`.
Seuls : 9 échecs sur 9 (3 × 3). Cause : `jarvis/domain/brain_context.py:36` importe
`jarvis.domain.research_freshness` (trace d'import : seul importeur dans la fermeture de
`jarvis.core.presentation_attention`). Bisect léger sur arbres exportés (`git archive`) : les 3 tests passent à
`79cf6813^`, échouent à `79cf6813` « S3: recherche existant d'abord, fraîcheur décidée par Core… ». Responsable :
**Slice 03 V1.2**. Les listes `ALLOWED_IMPORT_CLOSURE` / `SPECULATIVE_SERVICE_CLOSURE` n'ont pas été mises à jour
(ou l'import doit sortir du domaine).

### R2 — Bare Hands clean room : second `web.FileResponse` sous `jarvis/` (Slice 07 V1.2)

- `tests/unit/test_barehands_clean_room.py::test_mediapipe_reaches_the_page_only_through_the_closed_whitelist`

Seul : 3 échecs sur 3. Le test exige un unique service de fichiers sous `jarvis/` (le servant d'assets Bare
Hands). `git grep FileResponse` : 1 occurrence à `3dcc7036^`, 2 à `3dcc7036` « S7: Signaler un problème - paquet
de diagnostic complet… » (`jarvis/runtime/support_routes.py:461` aujourd'hui, téléchargement du paquet de
diagnostic). Responsable : **Slice 07 V1.2**. À décider : déclarer cette seconde porte dans le test (avec sa
justification) ou servir le paquet autrement.

## Échec non listé, reproductible, ANTÉRIEUR à la V1.2

- `tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`
  — `ValueError: substring not found` (ligne 128) ; seul : 3 échecs sur 3. Les ancres
  `async function commitGroupMove(move){`, `const sent=[];`, `if(g.mode==='move'&&g.carried.length>1){` sont
  absentes de `jarvis/runtime/control_center_scene_page.js` à `2d6ca879` (main), `63697cfa` (V1 S10) et HEAD :
  dette de main (cf. Issue `67a8c688` « drag de groupe, commande unique perdue »). Non causé par la V1.2, mais il
  rend la porte `browser` 3/10 rouge tant qu'il n'est ni corrigé ni listé. Jamais vu par la S10 V1, dont le
  balayage navigateur était partiel (A4 : 65 fichiers).

## Instables (passent parfois)

| Test | Taux d'échec mesuré | Antérieur à la V1.2 ? |
| --- | --- | --- |
| `test_presentation_attention_browser.py::test_ecarter_l_avertissement_n_emet_aucune_requete` | HEAD : 6 échecs / 8 (porte + 7 seuls) ; main `2d6ca879` : 4/5 ; mêmes résultats mêlés sur des commits V1 sans rapport (S0 doc : échec, S3 V1 : succès) | oui. Cause visible : la requête automatique de Chrome `GET /favicon.ico` tombe entre les deux marqueurs |
| `test_settings_accessibility_browser.py::test_a_part_reached_by_a_link_comes_to_the_top_of_the_content` | HEAD : 3 échecs / 4 (porte + 3 seuls) ; main `2d6ca879` : 3/4 ; avant S6 V1.2 (`95d069a7^`) : 3/4 ; à `95d069a7` : 4/4 | oui (même taux sur main) ; `{'top': -105, …}` |
| `test_control_center_chat_tabs_browser.py::test_two_visible_chat_tabs_stay_responsive_and_a_follower_send_succeeds` | 1 échec / 4 (porte en échec, 3/3 seul) | non bisecté (passe seul) ; échec sous charge `[9000, 4]` |
| `test_control_center_chat_tabs_browser.py::test_the_chat_adds_no_held_connection_with_three_tabs_and_a_timeline` | 1 échec / 4 (porte en échec, 3/3 seul, 158 s chacun) | non bisecté (passe seul) ; `/api/conversations/events` tenu une fois sous charge |

## Comparaison avec la S10 V1 (A3 : 845 fichiers, 22 013 passés, 10 échecs connus, 96 sautés)

- `unit` : 856 fichiers (+11), 22 415 passés (+402), 22 527 tests collectés, 98 sautés (+2), 10 échecs
  connus vus (identiques), **4 nouveaux échecs** (R1, R2 : tests qui passaient en S10 V1).
- `release` : 33 fichiers (29 en S10 V1 : +4, `test_support_report*`, `test_wake_word_install*`,
  `test_macos_portability`), 902 passés, 4 sautés.
- `browser` : 188 fichiers (185 + 3 nouveaux). Pas de référence complète V1 (A4 partiel) : c'est le premier
  balayage navigateur complet de la branche.
- Tests disparus : aucun. `git diff --name-status 63697cfa..HEAD -- tests` et `2d6ca879..HEAD -- tests` : aucun
  fichier supprimé ni renommé ; 14 fichiers ajoutés. Une seule ligne `def test_` retirée
  (`test_wake_word_settings_browser.py::test_enregistrer_ecrit_le_fichier_affiche_le_bandeau_et_se_relit`), qui
  existe toujours avec une signature étendue (`monkeypatch`). 272 `def test_` ajoutés.
- Fichiers des Slices V1.2 présents et collectés (pytest `--collect-only`) : `test_presentation_brain_scope` 36
  (unit), `test_presentation_project_continuity` 20 (unit), `test_research_freshness` 69 (unit),
  `test_work_methods_fingerprint` 3 (unit), `test_research_documents` 18 (unit), `test_voice_lifecycle` 54
  (unit), `test_wake_word_installed_default` 15 (release + unit), `test_support_report` 23 (release + unit),
  `test_support_report_qa` 56 (release + unit), `test_support_report_browser` 4 (browser),
  `test_support_report_js` 4 (browser), `test_support_mode` 18 (unit), `test_novice_settings_browser` 10
  (browser), `test_macos_portability` 54 (release + unit ; 2 sautés hors macOS, attendu).

## Vérifications statiques

- `python scripts/verify_release.py` : « Release verification passed. » (28 s).
- `git diff --check 2d6ca879..HEAD` : aucun défaut (code 0).

## Verdict : ROUGE

- Porte `release` verte ; portes `unit` (1/4, 2/4, 4/4) et `browser` (2/10, 3/10, 4/10) rouges.
- 2 régressions V1.2 à reprendre : R1 (Slice 03, 3 tests), R2 (Slice 07, 1 test).
- 1 échec déterministe antérieur, non listé (`test_scene_group_drag_js`) : corriger ou lister avec issue.
- 4 instables, tous visibles seulement sous charge ou déjà instables sur main : à lister en `intermittent`
  datés avec issue, ou à stabiliser, sinon les parts CI concernées resteront rouges par intermittence.
- Durée totale : 16 053 s de tests au rapport des portes (≈ 4 h 28 : release 264 s, unit 5 236 s, browser
  10 553 s), plus environ 25 min de relances et de bisect.
