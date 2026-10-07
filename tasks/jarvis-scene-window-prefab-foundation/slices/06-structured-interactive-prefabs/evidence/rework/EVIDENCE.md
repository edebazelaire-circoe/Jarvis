# Reprise QA de la Slice 06 — preuves

Commit : `432adcb` (`S6: rework — …`), sur la plateforme de `adecd7b`.
`jarvis.checklist` v1 n'est pas publiée sur `main` : sa `publication.json` et
son entrée de `catalog.lock.json` ont été supprimées puis régénérées par
`python -m scripts.lock_base_prefabs` (`--check` = 0).

## Tests (échec avant / réussite après)

`fails-before.txt` : sorties de pytest sur le comportement d'avant (et, pour
B6, sur la plateforme de `b00c142`).

| Point | Test | Avant |
| --- | --- | --- |
| B0 | `test_prefab_base_catalog.py::test_no_base_prefab_removes_the_keyboard_focus_ring`, `…colours_come_from_shell_tokens` | échouent sur `b00c142` |
| B1 | `test_prefab_checklist_js.py::test_a_refused_or_stale_write_is_undone_at_once_from_its_event_result_b1`, `…stale_note_survives_the_forced_resync_and_the_newer_list_b1` | échouent |
| B2 | `…late_confirmation_after_the_timeout_confirms_and_still_announces_completion_b2`, `…late_verdict_of_a_timed_out_write_changes_nothing_b2` | échouent |
| B3 | `…notice_lives_in_the_sticky_head_as_a_status_b3` | échoue |
| B4 | `…lows_replacement_clears_space_repeat_french_only_and_an_untick_cancels_completion_b4` | échoue |
| B5 | `…same_ids_with_another_done_during_a_write_is_not_a_confirmation_b5` | passe ; **mutant M3** (égalité sans `done`) : échoue |
| B6 | `test_prefab_checklist_js.py::test_sixty_four_long_labels_stay_tickable_above_8_kib_b6`, `test_prefab_checklist.py::test_sixty_four_long_labels_are_tickable_through_core_b6` | échouent sur `b00c142` (`payload is 8407 bytes, at most 8192`) |

## Navigateur

Chrome réel `--headless=new`, profil jetable, CDP ; Core 18963 / CC 18964 sur
une racine de scratch neuve, arrêtés après. Sonde : `rework_probe.mjs`
(commune avec la Slice 04). Relance : `node rework_probe.mjs
http://127.0.0.1:18964/ "<chrome.exe>" <OUT4> <OUT6> http://127.77.0.1:18963
<runtime>/core.token`. Résultats : `browser-results.json`.

- **B6** : `ck-64`, 64 éléments de 95 caractères ; la ligne 63 amenée dans le
  cadre et cliquée à la souris → écrite dans Core (révision 10, anneau
  `applied`) — `long-list-top.png`.
- **B3 / B1** : liste défilée en bas (`scrollTop` 3544), POST refusé par la
  page (Core injoignable) → la coche est défaite aussitôt et la note
  « Jarvis est injoignable : votre coche n’a pas été enregistrée. »
  (`role=status`) se lit dans la tête collée (haut 21 px dans un cadre de
  367 px, fond `rgb(4, 10, 15)` opaque) — `long-list-scrolled-notice.png`.
- **B2** : POST retardé de 6,5 s → à 5,0 s la ligne revient décochée avec
  « Coche pas encore confirmée : la liste affichée est la dernière
  enregistrée. » (`late-confirmation-pending.png`) ; à 6,6 s Core a écrit, la
  note s'efface et la ligne est cochée (`late-confirmation-confirmed.png`),
  `done` lu dans Core.
- Thèmes : `long-list-circuit.png`, `long-list-cosmos.png`.
- Console : aucune exception ; `scene.prefab_event_unsent` / `_failed`
  attendus (panne simulée).
