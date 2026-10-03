# Reprise QA de la Slice 04 — preuves

Commit : `adecd7b` (`S4: rework — …`), sur `b00c142`.

## Tests (échec avant / réussite après)

`fails-before.txt` : sorties de pytest avant correction (code de `b00c142` ou
mutant), un fichier à la fois.

| Point | Test | Avant |
| --- | --- | --- |
| A1 (F1) | `test_scene_service_prefab.py::test_a_block_equal_only_by_python_equality_is_revalidated_f1` | échoue (`True`/`1.0` passent sans validation) |
| A2 (F2) | `test_prefab_domain.py::test_a_missing_basis_key_reads_as_null_like_a_missing_data_key`, `test_prefab_host_js.py::test_a_written_key_the_frame_never_saw_goes_out_as_a_null_basis_a2`, `test_prefab_events.py::test_a_written_key_absent_from_core_data_is_a_null_basis_f2` | échouent (`basis lacks written key`, clé omise par l'hôte) |
| A3 | `test_scene_service_prefab.py::test_core_stores_the_defaulted_validated_block_a3[create/upsert/patch]`, `…_no_longer_fits_the_scene_is_refused_not_raised_a3` | échouent (bloc stocké tel qu'écrit) |
| A4 | `test_prefab_host_js.py::test_the_frame_learns_every_event_outcome_and_stale_forces_an_update_a4`, `…host_side_drops_are_told_to_the_frame_a4`, `test_prefab_shim_js.py::test_event_results_reach_the_behavior_and_a_forced_update_is_never_deduped_a4`, `test_prefab_protocol_js.py::test_event_result_and_forced_update_are_additive_host_messages_a4` | échouent |
| A5 | `test_prefab_domain.py::test_state_event_payload_size_is_bounded`, `test_prefab_events.py::test_notify_keeps_8_kib_while_state_events_take_16`, `test_prefab_host_js.py::test_a_state_event_may_carry_up_to_16_kib_a5`, `test_prefab_shim_js.py::test_emit_pre_checks_the_state_bound_of_16_kib_a5` | échouent (8 Kio) |
| A6 | `test_scene_window_fit_js.py::test_a_short_window_is_never_fitted_below_the_readable_height_a6` (vraie `fitBrainWindows`, vrai layout) | échoue (`capsule`) |
| A7 (F3) | `test_scene_service_prefab.py::test_refusal_diagnostics_carry_paths_and_codes_never_values_f3`, `test_prefab_events.py::test_event_diagnostics_never_carry_values_f3`, `test_prefab_domain.py::test_detail_paths_name_inputs_never_values` | échouent (valeur dans le journal) |
| A8 (F4) | `test_scene_service_prefab.py::test_a_long_object_id_and_validator_detail_are_clipped_inside_the_lock_f4` | passe ; **mutant M08** (découpe retirée) : échoue (`ValueError` dans le verrou) |
| A9 (F5) | NEW `test_scene_prefab_page_js.py` (vraies `element`, `fill`, `syncPrefab`, `applyNodes`) | **M17** (fill détache le conteneur) tué par le test de redessin ; **M19** (pas de démontage au retrait) tué par le test de retrait |
| A10 | `test_prefab_routes.py::test_a_scene_that_cannot_write_an_event_answers_503_like_the_scene_route` | échoue (500) |

## Navigateur

Chrome réel `--headless=new`, profil jetable, CDP ; Core 18963 / CC 18964 sur
une racine de scratch neuve (`test.counter` installé dans sa bibliothèque),
arrêtés après. Sonde : `../../../06-structured-interactive-prefabs/evidence/rework/rework_probe.mjs`
(commune aux deux Slices). Résultats : `browser-results.json`.

- **A3** : compteur créé par la page avec `props: {}`, `data: {count: 3}` →
  stocké `props {label: "Count", accent: "#6ee7ff", mode: "full"}`,
  `data {count: 3, notes: "", history: []}`.
- **A2** : premier vrai clic « +1 » (hit-test : `IFRAME.sc-prefab-frame`) →
  `applied`, `count` 4.
- **A4** : deux écritures émises dans le cadre sur la même basis → anneau
  `applied`, `stale` ; le cadre reçoit `event_result stale` puis l'`update`
  forcé 0,2 ms après, puis le flux de scène (`count` 7) —
  `counter-after-stale.png`.
- **A6** : checklist courte vidée par Jarvis (HTTP, acteur `brain`) → après
  ajustement `h` 19,4 u = 97 px dessinés, classe `sc-window`, 1 iframe, « Aucun
  élément. » — `short-list-after-fit.png`.
- Console : aucune exception ; `scene.prefab_event_failed` / `_unsent`
  attendus (stale provoqué, Core injoignable simulé côté S06).
