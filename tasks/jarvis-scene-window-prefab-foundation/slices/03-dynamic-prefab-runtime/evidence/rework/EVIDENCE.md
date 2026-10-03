# Slice 03 — rework QA : confinement des cadres de prefab

Constats QA F1–F5 (`qa-s03`). Contrat corrigé : `docs/prefabs.md` › *Runtime* ›
*Containment*, *Message protocol*, *Hygiene lint* ; `docs/SECURITY.md` §16.

## Tests de régression (échouent avant, passent après)

`tests/unit/test_prefab_frame_containment.py` — sur `888937c` (avant
correctif) : **20 échecs, 1 succès** (le témoin « `load` de l'`about:blank`
initial n'est pas une navigation », garde contre les faux positifs, passe des
deux côtés). Après : 21/21.

| Constat | Test | Échec avant |
| --- | --- | --- |
| F1a CSP de la page | `test_the_page_frames_only_the_configured_visualizer`, `test_without_visualizer_the_page_frames_nothing_by_url`, `test_frame_src_policy_is_one_origin_or_none[8]` | `KeyError: 'Content-Security-Policy'` ; `frame_src_policy` absent |
| F1b navigation | `test_a_frame_that_navigates_is_removed_and_never_initialized_again`, `test_reload_after_a_violation_mounts_a_fresh_frame` | état `ready` après le second `load`, cadre gardé |
| F1c second `ready` | `test_a_second_ready_is_a_protocol_violation_and_gets_no_second_init` | `['init', 'init'] != ['init']` |
| F1d lint | `test_lint_refuses_area_links` (+ `area` dans `test_lint_refuses_each_forbidden_template_tag`) | aucune erreur pour `<AREA` |
| F2 bornes | `test_an_oversized_message_is_refused_before_any_serialization_or_regex` | espions `{stringify: 1, replace: 1, test: 1}` au lieu de 0 |
| F2 resize | `test_a_resize_flood_is_coalesced` | `[2000, '529px'] != [1, '30px']` |
| F2 error | `test_an_error_flood_is_rate_limited` | `1000 != 10` |
| F3 plafond de journal | `test_the_per_frame_log_cap_restarts_on_reload` | `second: 5 != 6` |
| F4 cache | `test_the_bundle_cache_is_bounded_and_forgets_an_unusable_bundle` | pas de borne, paquet refusé gardé (1 seule requête) |
| F5 `open_url` | `test_open_url_from_a_frame_refuses_local_and_private_hosts` | 13 adresses locales/privées acceptées |

Coût du protocole sur 64 MiB (node, même machine) : événement 240 ms → 0,25 ms,
erreur 43 ms → 0,03 ms.

## Preuve navigateur (Chrome headless réel, CDP, profil jetable hors dépôt)

Phase *hostile* — Core (`python -m jarvis core`, 18973) et CC
(`python -m jarvis control-center`, 18974) isolés depuis ce worktree,
visualiseur coupé, bibliothèque de scratch remplie par `install_hostile.py`
(tous passent le lint S02), écouteur HTTP sur 18975 qui journalise toute
requête. Relance : `node containment_probe.mjs hostile http://127.0.0.1:18974/ "<chrome.exe>" . 18975`.
Résultats : `containment-hostile.json`, `containment.png`.

| Preuve | Observé |
| --- | --- |
| En-tête de la page | `Content-Security-Policy: frame-src 'none'` |
| Aucune requête ne sort | écouteur : **0 requête** (QA avant : `/exfil?d=…SECRET…`, `/area-click`) |
| Navigation bloquée par Chrome | 3 × « Framing 'http://127.0.0.1:18975/' violates … "frame-src 'none'". The request has been blocked. » |
| `qa.navexfil` (`location.href`) | état `error`, 0 cadre, bande « …failed: the frame navigated away from its document », `scene.prefab_error` `navigation` |
| `qa.domarea` (`<area>` créé par le comportement, cliqué) | idem (le lint ne le voit pas : la page et l'hôte, si) |
| `qa.reready` | état `error`, bande « second ready … », `scene.prefab_error` `protocol` |
| `init` reçus | 1 par génération : `obj_area` 1, `obj_reready` 1, `obj_open` 1, `obj_big` 1, `obj_nav` 2 (= 2 générations : « Recharger » remonte un cadre neuf, qui refait la même violation, 2 erreurs journalisées) |
| Témoin sain `test.counter` | `ready`, 1 cadre, pas de bande : le contrôle de `load` ne donne pas de faux positif |
| `qa.openlocal` (F5) | `opened = ["https://example.com/ok"]` seul ; 127.0.0.1, localhost, 192.168.1.1, 169.254.169.254, [::1] refusés |
| `qa.bigmsg` (F2) | événement refusé `event payload too large`, erreur bornée à 300, **2 resize appliqués** (QA avant : 2009) ; trou max du fil principal ~1 s, identique à avant : c'est la désérialisation par Chrome des deux messages de 64 MiB, avant tout gestionnaire |

Phase *visualizer* — la vraie méthode `ControlCenter.index` avec
`visualizer_url=http://127.0.0.1:18975/faces/board/` (`index_with_visualizer.py`,
18974 ; le CLI ne pose cette URL que s'il lance `third_party/ai-visualizer`,
absent d'un worktree), visualiseur factice servi par l'écouteur.
Résultats : `containment-visualizer.json`.

| Preuve | Observé |
| --- | --- |
| En-tête | `frame-src http://127.0.0.1:18975` |
| Le visualiseur charge | requête `GET /faces/board/` (`sec-fetch-dest: iframe`) ; message `{visualizer: "loaded"}` d'origine `http://127.0.0.1:18975` reçu par la page |
| Autre origine toujours bloquée | cadre sandboxé `srcdoc` naviguant vers 18973 : « Framing 'http://127.0.0.1:18973/' violates … "frame-src http://127.0.0.1:18975" » |

Tous les processus (Core, CC, banc, Chrome) arrêtés après les runs ; ports
17653/17654 jamais touchés.

## Limite résiduelle documentée

Un cadre peut naviguer vers l'origine du visualiseur (boucle locale, notre
serveur) puisque la page doit l'encadrer : l'hôte détecte le second `load`,
retire le cadre et n'envoie pas d'`init`.
