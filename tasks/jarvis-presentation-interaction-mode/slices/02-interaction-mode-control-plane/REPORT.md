# Slice 02 - Implementation report

| | |
| --- | --- |
| Branch | `task/jarvis-presentation-interaction-mode` |
| Scope | Live control plane: persistence, one effective value + revision, routes, event, reconciliation. **No UI selector** (Slice 03), **no Presentation behaviour** (Slices 06+). |
| Canonical doc | `docs/interaction-mode.md` § "Control plane (Slice 02)", plus a control-plane block in `docs/ARCHITECTURE.md` |
| New suites | `tests/unit/test_interaction_mode_control_plane.py` (72), `tests/unit/test_interaction_mode_protocol.py` (11) |

## 1. What was built

Three owners, one effective value, no fourth copy.

### Core owns the live truth — `jarvis/core/interaction_mode.py` (new)

`InteractionModeService`, wired into `JarvisCoreApplication` next to
`CoreEventBus`, in memory only (an effective mode is a fact of this process's
life; the preference that outlives it belongs to the Control Center).

- `InteractionModeState{mode, revision, source, changed_at}`, `to_payload()`.
- `request(value, source)` — the **explicit** path. `interaction_mode_unknown`
  for anything that is not a mode (never a silent fallback);
  `interaction_mode_not_implemented` for REUNION, raised by Slice 01's
  `ensure_activatable`, not re-invented.
- `reconcile(value, source)` — the **stored-value** path. Total: anything
  unreadable yields `assistant` and Jarvis starts. Not silent in the journal —
  the fallback is named, so "started in SIMPLE" and "its setting was corrupt"
  cannot look identical.
- One `asyncio.Lock`: concurrent requests produce one revision per real change.
  Idempotent — re-requesting the current mode bumps nothing and publishes
  nothing. Revision starts at 0 and only ever increases.
- Publishes `interaction.mode.changed` on `CoreEventBus`, **outside** the lock.
  A bus failure never loses the state (`interaction.mode.publish_failed`); a
  subscriber that missed the event finds everything in the snapshot.
- `supported_modes()` is the single door for "what exists", used by Core's
  snapshot, the event payload, `/api/status` and `/api/settings`.

### Control Center owns the persistence — `jarvis/runtime/interaction_mode_settings.py` (new)

Shape copied from `barehands_test_mode` / `scene_settings`: `SETTING_KEY`,
tolerant `load`, strict `apply`, `inspect`, `describe`. Root key
`interaction_mode`, `{"schema_version": 1, "mode": "..."}`.

- `load()` is the **display** reading (`stored_interaction_mode` — `meeting`
  survives). `behaving()` is the **behaviour** reading and is what is sent to
  Core. Both are exported and named apart.
- `inspect()`/`describe()` separate "default because new" from "default because
  unreadable", and keep `stored_value` visible rather than losing it silently.
- Strict write codes, all carried in `X-Jarvis-Error-Code`:
  `interaction_mode_bad_payload`, `_missing`, `_unknown`, `_unknown_field`,
  `_schema_version_unsupported`, `_not_implemented`.

### Control Center to Core — `jarvis/runtime/interaction_mode_view.py` (new)

`CoreInteractionModeTransport` (its own loopback connection, token re-read on
401) and `CoreInteractionModeView`, modelled on `CoreWorkView`:

- `read()` never raises. Core unreachable gives a **named** local fallback:
  `source: "settings"`, `core_reachable: false`, `revision: null`, an
  `error.code` from the work-view vocabulary (`not_configured`,
  `core_unreachable`, `core_refused`, `invalid_snapshot`). A screen must never
  show a local setting as if it were live truth.
- `request()` **raises** `InteractionModeUnavailable` when Core did not take it,
  carrying Core's own code untranslated. Nobody may believe a presentation is
  armed because a file was written.
- `_decode` refuses an out-of-contract response, including a *reserved* mode
  presented as effective.

### Voice observes — `jarvis/runtime/interaction_mode_observer.py` (new)

`InteractionModeObserver`: last mode + revision, monotonic guard (an event with
a revision lower than or equal to the one held is ignored, so crossing messages
cannot walk backwards). `observe(envelope)` for the live event,
`adopt(snapshot)` for a resume after a stream gap — both through the same guard.
It applies `behaving_interaction_mode`, so a reserved mode can never become
running behaviour even if something upstream published one. Owned by
`PersistentVoiceRuntime` (process lifetime, not session lifetime) and fed by
`SpeechScheduler.handle_core_event`, the Voice process's only `/v1/events`
subscriber — routed **before** the brain-event filter, since the mode belongs to
no conversation.

### Routes

| Route | Meaning |
| --- | --- |
| `GET /v1/interaction-mode` | effective mode, revision, advertised modes |
| `POST /v1/interaction-mode` | request a mode; 409 + `interaction_mode_not_implemented`, 400 + `interaction_mode_unknown` |
| `GET /api/interaction-mode` | stored preference + an `effective` block read from Core |
| `POST /api/interaction-mode` | persist the preference, then apply it live |
| `GET /api/status` to `interaction_mode` | effective mode, revision, `stored`/`stored_label`, `modes` |
| `GET /api/settings` to `interaction_mode` | the stored preference only |

Client methods `LocalCoreClient.interaction_mode()` /
`.set_interaction_mode(mode, source=)`.

### Reconciliation

- `ControlCenter.start()` replays the stored preference towards Core. Never
  raises, never blocks startup (Core legitimately starts later); a failure is
  `interaction.mode.reconcile_failed` and the status keeps showing the named
  fallback.
- A Core that started **after** us is at revision 0 — the exact signal that it
  has never heard the preference. The 1 Hz status poll replays it once; the
  condition extinguishes itself as soon as Core takes the mode.
- Write order is deliberate: **persist, then apply**. Core unreachable gives
  HTTP 503 saying the mode is *saved but not yet applied*, with the settings
  file genuinely written so the choice survives.

## 2. Reuse — and what was deliberately not reused

**Reused**

- `barehands_test_mode` as the schema-versioned settings-module shape
  (`SETTING_KEY` / tolerant `load` / strict `apply` / `inspect` / `describe`,
  stable codes in `X-Jarvis-Error-Code`), and its "a dedicated route applies hot
  and does not revalidate the voice settings" precedent (finding F5).
- `CoreWorkView` + `CoreWorkTransport` for the Control-Center-to-Core read seam,
  including its unavailability code vocabulary, its 401 token re-read, and its
  "report an out-of-contract response once per exception type" rule.
- `CoreEventBus` + `/v1/events` as the live channel — the one Voice already
  consumes — rather than a second stream.
- Slice 01's `ensure_activatable`, `parse_interaction_mode`,
  `stored_interaction_mode`, `behaving_interaction_mode`, `INTERACTION_MODES`,
  `InteractionModeError`, and its stable codes. Not one of them was re-derived.
- `RuntimeJournal.emit` with dotted kinds; `DiagnosticSink` on the Core side,
  as every other Core service does.
- The `LocalProtocolServer` route/`_auth`/`_optional_text` conventions and the
  `LocalCoreClient._json` error-code decoding.

**Deliberately not reused**

- **`ControlCenter._apply_voice` and `POST /api/settings`** — constraint G1.
  The mode is its own axis with its own key and its own route.
- **`voice_settings_schema.PERSISTABLE_OPTION_IDS`** — constraint G3. Rather
  than extending a 47-entry allow-list that fails silently, the control lives
  outside it entirely, which is why a disk round-trip test is the acceptance
  proof and a test asserts the key is *not* in that tuple.
- **`VoiceComposition` / `VoiceSwitchBus`** — decision D15. Untouched, on
  purpose; `voice_composition.py` is listed in SLICE.md's "Files Likely
  Touched" and was not touched.
- **`barehands_test_mode`'s archive mechanism** (`ARCHIVE_KEY_PREFIX`). Argued
  trade-off: there is a single word at stake against a whole archival mechanism
  to maintain. A foreign block is not archived but it is *stated* — `unreadable`
  and `stored_value` in the payload, one `interaction.mode.foreign_version` line
  per process — so nothing disappears without a word.
- **Core persistence.** `InteractionModeService` writes nothing to SQLite; two
  persisted truths about one mode is the divergence this slice exists to
  prevent.

## 3. How each binding constraint is discharged

| Constraint | Discharge | Test |
| --- | --- | --- |
| **D15** — no restart | Nothing on the mode path recomputes a composition or writes on `VoiceSwitchBus`; the mode travels by event | `test_changer_de_mode_ne_demande_aucun_redemarrage_de_voice` — three independent assertions: `configuration_id` identical across three toggles, no `voice.switch.requested` line, no switch-request file. Plus `test_le_condense_de_composition_ignore_la_cle_du_mode_d_interaction` (the hash is byte-identical with `assistant` and with `presentation` stored) and `test_un_changement_de_mode_arrive_sur_le_flux_d_evenements` (the event really reaches a `/v1/events` subscriber) |
| **G1** — not through `_apply_voice` | Own key, own route, own apply path | `test_le_mode_survit_a_un_basculement_de_compatibilite_vocale` — asserts on the *file*: `voice_arch == "continuous_brain"`, `voice_architecture` deleted, `interaction_mode` unchanged. Plus `test_enregistrer_le_mode_ne_touche_a_aucun_des_deux_axes_d_architecture` (the reverse direction, both axes) |
| **G3** — silent persistence failure | Outside `PERSISTABLE_OPTION_IDS` by design, dedicated route | `test_le_mode_enregistre_survit_a_une_relecture_depuis_le_disque` — writes, reads the JSON file, rebuilds a second `ControlCenter` from disk. Plus `test_le_mode_n_est_pas_un_reglage_vocal_persistable` and the route-level `test_la_route_dediee_ecrit_le_mode_sur_le_disque_et_l_applique_a_core` |
| **G4/D15 restart semantics** | Core owns mode + revision, Voice observes | the observer suite (5 tests) + `test_l_ordonnanceur_de_parole_route_le_mode_vers_l_observateur_du_processus` |
| **Slice 01 label trap** | Stored value read only through the *value* door, in its own key | `test_le_mode_n_est_pas_range_dans_une_cle_ou_une_architecture_vocale_pourrait_atterrir` (`simple`, `continuous_brain` refused; only `interaction_mode` written), `{"mode": "SIMPLE"}` refused at the route, `"SIMPLE"` refused at the protocol |
| **Right reader** | `stored_` for display (`/api/status`'s `stored`, `/api/settings`, `describe`), `behaving_` for behaviour (Core reconcile, observer, the value sent to Core) | `test_un_meeting_enregistre_reste_affichable_mais_ne_se_comporte_pas`, `test_le_statut_garde_reunion_visible_quand_il_est_le_mode_enregistre`, `test_la_reconciliation_ne_demande_jamais_un_mode_reserve` |
| **Meeting** | Advertised in `supported_modes()` (`implemented: false`, `status: planned`), refused by `ensure_activatable` | `test_reunion_est_annonce_partout_et_activable_nulle_part`, `test_l_ecriture_du_mode_reunion_est_refusee_avec_le_code_stable`, `test_core_refuse_le_mode_reunion_sans_toucher_a_la_valeur_effective`, `test_la_route_du_control_center_refuse_reunion_en_409_avec_son_code`, `test_le_mode_reunion_est_refuse_en_409_avec_son_code_stable` |
| **Default on missing/invalid/corrupt/upgrade** | tolerant `load`, total `reconcile` | a 12-case parametrization + `test_la_reconciliation_ne_leve_jamais_quoi_qu_elle_lise` (bytes, `object()`, `None`, ints) |
| **Diagnostics without content leakage** | dotted kinds, values truncated to 64 chars | `test_le_journal_dit_la_demande_l_application_et_le_refus_sans_contenu_utilisateur` asserts every `interaction.mode.*` record's `data` keys are within an allow-list |

## 4. Failure paths, enumerated

| Case | Behaviour | Test |
| --- | --- | --- |
| Empty / absent setting | default `assistant`, not an error | parametrized |
| Corrupt setting | default + named in `describe` + journal | parametrized, `test_une_valeur_inconnue_dans_un_bloc_lisible_est_signalee_comme_telle` |
| Foreign schema version | default, block kept, one line per process | `test_une_preference_ecrite_par_une_version_plus_recente_est_dite_pas_devinee`, `test_une_preference_de_version_inconnue_laisse_une_ligne_une_seule_fois` |
| Refused (REUNION) | 409, stable code, nothing persisted | `test_la_route_du_control_center_refuse_reunion_en_409_avec_son_code` |
| Malformed payload | 400 + stable code, per shape | 7-case parametrization |
| Core unreachable, read | named fallback, status stays up | `test_le_statut_ne_tombe_pas_quand_core_est_injoignable` |
| Core unreachable, write | 503 saying saved-not-applied, `interaction.mode.not_applied` at `error` | `test_une_demande_que_core_n_a_pas_prise_echoue_en_503_en_le_disant` |
| Core out of contract | refused, not believed | `test_la_vue_refuse_une_reponse_hors_contrat_au_lieu_de_la_croire` (5 shapes) |
| Concurrent / double click | one revision, one event | `test_des_demandes_concurrentes_ne_produisent_qu_une_revision_par_changement` |
| Event bus down | state kept, `publish_failed` at `error` | `test_une_panne_du_bus_ne_perd_pas_le_mode_et_le_dit` |
| Crossing / stale events | ignored by the revision guard | `test_l_observateur_ignore_un_evenement_plus_ancien_que_ce_qu_il_tient` |
| Malformed event | mode held in place, `ignored` line | 8-case parametrization |
| Unauthenticated | 401 on both verbs | `test_la_lecture_et_l_ecriture_exigent_le_jeton_de_session` |

The expected path is logged too, at `info` (`requested`, `applied`,
`unchanged`, `reconciled`, `observed`) — otherwise "nothing in the journal"
would mean both "fine" and "dead".

## 5. Validation

All foreground, narrow file lists, `-q -p no:cacheprovider` (the host runs under
2 GB free RAM).

```
.venv/Scripts/python.exe -m pytest <files> -q -p no:cacheprovider
```

| Files | Result |
| --- | --- |
| `test_interaction_mode_control_plane.py` | **72 passed** |
| `test_interaction_mode_protocol.py` | **11 passed** |
| `test_control_center_mvp.py test_voice_architecture_config.py test_voice_composition.py` | **90 passed** |
| `test_voice_settings_schema.py test_v2_architecture.py test_documented_routes.py test_interaction_mode_contract.py` | **122 passed** |
| `test_documented_routes.py test_interaction_mode_contract.py test_control_center_quality.py` (re-run after the doc edits) | **176 passed** |
| `test_v2_speech_scheduler.py test_speech_scheduler_review_races.py test_speech_presentation_scheduler.py test_voice_switch.py` | **68 passed** |
| `test_settings_endpoints.py test_control_center_voice_architecture.py test_control_center_quality.py` | **145 passed** |
| `test_settings_ia_contract.py test_settings_workbench.py test_settings_mcp.py test_voice_settings_ui.py test_control_center_appearance.py` | **69 passed** |
| `test_v2_voice_toggle.py test_back_brain_protocol.py test_voice_admission_protocol.py test_voice_ledger_protocol.py test_live_lifecycle_protocol.py` | **97 passed** |
| `test_v2_event_bus.py test_v2_wire_form.py test_v2_persistence.py test_work_state_store.py` | **67 passed** |
| `test_app.py test_environment.py test_live_idle_policy.py test_live_runtime_safety.py` | **46 passed** |
| `test_owner_barge_in.py test_owner_input_gate.py test_device_playback_completion.py test_live_idle_composition_review.py test_speaker_verifier.py` | **174 passed** |
| `test_scene_settings.py test_scene_service.py` (baseline probe) | **4 failed, 61 passed** — exactly the 4 declared in `READINESS.md` section 4, and `test_scene_commands_never_reach_the_core_event_bus` still fails on its own scene-revision assertion (`assert 5 == 4`), not on the bus |

Every mandated re-run suite is in the table. **Zero new failures.** None of the
26 pre-existing baseline failures was touched, fixed, or added to.

## 6. Where SLICE.md and the live repository disagreed

Reported, not silently resolved.

1. **"Voice observes mode/live changes without restart" — only in continuous
   mode.** The Voice process's *only* `/v1/events` subscription lives in
   `SpeechScheduler`, which `PersistentVoiceRuntime` creates only when
   `self.continuous`. In legacy mode nothing in Voice subscribes, so the
   observer stays at the default until something calls `adopt()` with a
   snapshot. I wired the event path where it exists and gave the observer the
   snapshot seam SLICE.md explicitly allows ("or safe mode snapshot seam"), and
   opened no second subscription for a consumer that does not exist yet. The
   limit is written down in `docs/interaction-mode.md`.

2. **`voice_composition.py` is listed in "Files Likely Touched"** — and was
   deliberately not touched, because D15 says the mode must not enter
   `configuration_id`. The handoff document predates the decision; the decision
   wins.

3. **The `error-handling` skill's binding contract does not exist in this
   repository.** It names `docs/observability/error-handling.md`,
   `send_error_response`, `record_route_failure`, `obsClientLog`,
   `app/Displayer/frontend/js/error_surface.js` and an `/api/error-logs` viewer.
   None of those paths or symbols exist here (`grep` for `send_error_response`
   across `*.py`: zero hits; `app/` and `docs/observability/` are absent). The
   skill describes the Symphonia/Displayer codebase. I followed the *rules*
   (visible on screen, durable record, real cause preserved, three legal catch
   shapes, failure paths tested) through this repository's actual machinery:
   aiohttp HTTP exceptions carrying the plain message in the body plus the
   stable code in `X-Jarvis-Error-Code`, and `RuntimeJournal.emit` /
   `DiagnosticSink.emit`. Every broad `except` in the new code either re-raises
   a typed error, records through the journal, or carries a written argument.

4. **The `coding-guideline` documentation chain names `docs/CONTEXT.md` and
   `docs/documentation-level-registry.yaml`, neither of which exists here** —
   already reported by Slice 01. The repository convention (a dedicated
   `docs/<concept>.md`, linked from `docs/ARCHITECTURE.md`) was followed
   instead: `docs/interaction-mode.md` was extended rather than a new page
   created, and `docs/ARCHITECTURE.md`'s interaction-mode section now carries
   the control-plane ownership block and the three-process diagram.

5. **Judgement calls worth a reviewer's eye, recorded rather than hidden:**
   - *REUNION is 409, not 400.* The request is well formed and the mode exists;
     it is the behaviour that does not. The stable code — the thing Slice 03
     will branch on — is identical either way.
   - *`/api/status` gained a second Core round-trip per poll.* It already awaits
     `_live_status`, which reads Core, so this is consistent with the existing
     design; it is the price of the page never showing a stale mode. A
     `read()` failure cannot take the status down.
   - *A foreign settings block is not archived.* Argued above.
   - *`supported_modes()` lives in Core*, and `interaction_mode_settings`
     imports it, creating a `runtime -> core` import. That direction already
     exists in this repository (`speech_scheduler`, `realtime_audio`,
     `conversation_event_forwarder`, `factory`). One door for "what exists"
     beats two tables that can drift.

## 7. Nothing refused

Every acceptance criterion in SLICE.md is implemented and covered. The two
explicit exclusions — the UI selector and Presentation behaviour — are untouched
by design, and not a line of meeting behaviour was invented.

---

# Slice 02 — rework pass (second commit)

One blocking defect and ten smaller items, all inside this slice's own surface.
Delivered as a second commit; `52ab8cf` is untouched.

## B1 (blocking) — a Core restart made Voice serve the wrong mode, silently

The observer's guard was `revision <= self._revision`. Core's revision is
process-local and resets to 0 on restart, while the observer is owned by
`PersistentVoiceRuntime` and survives stream gaps — `_consume_core_events`
reconnects forever rather than rebuilding anything. So after a Core restart the
observer discarded every new revision as "older", and the user's explicit SIMPLE
never reached Voice. It emitted nothing, `adopt()` passed through the same guard
so no resync could repair it, and no test covered it. `READINESS.md` §3 G4 had
written this down as D15's residual risk.

**Fixed as decided.** `InteractionModeService` draws an `epoch` once at
construction (`new_id()`); it is a field of `InteractionModeState`, carried in
`to_payload()` and therefore in both `GET /v1/interaction-mode` and
`interaction.mode.changed`. The observer holds `(epoch, revision)`:

- different epoch, **or none at all** (older Core): taken unconditionally, the
  revision floor restarts from it, and a line says a new Core life was seen.
  Version skew fails safe towards freshness, not staleness;
- same epoch: the monotonic guard, unchanged.

Re-ran the coordinator's own reproduction against the fix:

```
observer after 3 toggles: presentation @rev 3
--- Core restarts, revision resets to 0 ---
  Core says rev=1 mode=presentation -> adopted=False  observer holds presentation@1
  Core says rev=2 mode=assistant    -> adopted=True   observer holds assistant@2
  Core says rev=3 mode=presentation -> adopted=True   observer holds presentation@3
  Core says rev=4 mode=assistant    -> adopted=True   observer holds assistant@4
```

Line 1 is `False` only because the mode did not change; the revision floor is
already reset to 1, and line 2 — the failure in the report — now adopts.

**And the resync the docs promised is wired.**
`SpeechScheduler._subscription_ready` now calls `_resync_interaction_mode()`, a
detached task that fetches `GET /v1/interaction-mode` and feeds it to
`adopt()`. The subscription never waits on it, and a failure is
`interaction.mode.resync_failed` at `warning`. `adopt()` had zero production
callers before this.

Tests: `test_un_core_redemarre_est_cru_sans_condition_malgre_sa_revision_repartie_de_zero`,
`test_un_redemarrage_de_core_laisse_une_ligne_au_lieu_d_une_revision_qui_recule`,
`test_un_core_sans_epoque_est_cru_plutot_que_presume_perime`,
`test_un_abonnement_reussi_relit_le_mode_chez_core`,
`test_une_relecture_de_mode_qui_echoue_est_dite_et_n_arrete_pas_l_abonnement`,
plus `test_l_instantane_et_l_evenement_portent_la_meme_vie_de_core` at the
protocol level.

## The ten

| | Fix |
| --- | --- |
| **R2** | `/api/status` is read-only again. The replay is *armed* by the poll and executed by `_replay_interaction_mode`, one task at a time, with `INTERACTION_MODE_REPLAY_BACKOFF_S = 30 s` before another poll can arm the next. The warning goes through a `ReportThrottle` (the one this file already owned) and says how many lines it swallowed. The two Core reads on the heartbeat are now `asyncio.gather`ed instead of serial. `stop()` cancels a sleeping replay. |
| **R3** | `InteractionModeService.reconcile()` deleted — it had no production caller and its `interaction_mode_unreadable` branch was unreachable, because the Control Center normalises the value before Core ever sees it. The "defaulted because unreadable / because reserved" line now comes from `ControlCenter.report_interaction_mode_preference()`, which runs at startup **before** any network call and independently of whether there is anything to replay. `docs/interaction-mode.md` rewritten to match. New: `test_un_reglage_qui_n_est_pas_celui_qui_s_applique_est_nomme` (4 cases), `test_un_reglage_sain_ne_produit_aucune_ligne_de_repli`, `test_le_service_core_n_a_plus_de_seconde_porte_tolerante`. |
| **R4** | `POST /v1/interaction-mode` builds its response from `state.to_payload()` + `supported_modes()`, so the `(mode, revision)` pair is the one this call produced. Test: `test_la_reponse_d_une_demande_porte_le_couple_mode_revision_de_cet_appel`. |
| **R5** | The 503 branches on `exc.code in {CORE_UNREACHABLE, NOT_CONFIGURED}`. Transport failure keeps "Il sera repris dès que Core répondra" and arms a replay; Core's own refusal says "elle ne sera pas réessayée telle quelle" and arms nothing. Punctuation fixed. `retryable` is in the journal record. Tests: `test_un_refus_de_core_ne_promet_pas_une_reprise_qui_n_aura_pas_lieu`, `test_une_panne_de_transport_promet_et_arme_la_reprise`. |
| **R6** | `local_payload` runs the stored preference through `behaving_interaction_mode`, so the `mode` field can never carry `meeting` — the same rule `_decode` applies to Core's answer. `stored`/`stored_label` still carry REUNION, which is where decision 02 needs it. Test: `test_le_repli_local_ne_presente_jamais_un_mode_reserve_comme_effectif`. |
| **R7** | Both silences closed. An equal revision carrying a different mode emits `interaction_mode_event_revision_conflict`; a reserved mode arriving as effective emits `interaction_mode_event_reserved_mode`. The docstring and the code now say the same thing. Tests: `test_une_revision_egale_qui_change_de_mode_est_ecartee_et_dite`, `test_l_observateur_ne_joue_jamais_un_comportement_de_reunion_et_le_dit`. |
| **R8** | `interaction.mode.changed` carries the state only; `supported_modes()` stays in the snapshot. `/api/status` calls `interaction_mode_settings.supported_modes()` instead of re-running `describe()` (which re-ran `inspect` + `load` + `behaving`) once a second for a constant. Test: `test_l_evenement_ne_porte_pas_le_catalogue_des_modes`, and the protocol suite asserts `"modes" not in` the event. |
| **R9** | `interaction.mode.view_invalid`, `.defaulted` and `.resync_failed` added to the diagnostics table. The "never blocks the startup" claim is now true rather than reworded: startup no longer awaits a network write at all. A new "Epoch: why a revision alone is not enough" section, and a fourth bullet in "Restart reconciliation" covering Core-then-Voice, the combination that produced B1. |
| **R10** | `test_l_ordonnanceur_de_parole_route_le_mode_vers_l_observateur_du_processus` (source-substring) replaced by two behavioural tests that build a real `SpeechScheduler`, `await handle_core_event(...)` and assert `observer.mode` — one of them with a foreign `conversation_id`, pinning that the mode is routed *before* the brain filter. Added `CoreInteractionModeTransport` 401-retry coverage (both verbs, plus a non-401 that must not be replayed). The two concurrency tests and the first assertion of the D15 test now carry written notes saying exactly what they do and do not prove, and `InteractionModeService.__init__` carries the comment that today's guarantee comes from the single-threaded loop, the lock being the future-proofing. |

## The two overstated claims, corrected

- **Content leakage.** The previous claim ("every `interaction.mode.*` record's
  `data` keys are within an allow-list") was broader than the test, which only
  observed the lines two route calls produced. There was no actual leakage —
  `view_invalid` carries an exception type and a truncated exception message,
  `ignored` carries mode values and counters — but the test did not cover them.
  It now **drives** all four emitters (routes, preference reporting, view,
  observer), asserts the seven kinds are present, and checks each line against
  one named allow-list plus a 200-character bound per value. Renamed
  `test_aucune_trace_de_mode_ne_porte_de_contenu_utilisateur`.
- **The `adopt()` snapshot seam** was described as wired when it had no caller.
  It now has one (`SpeechScheduler._subscription_ready`), and the doc says
  where.

## Validation, rework pass

```
.venv/Scripts/python.exe -m pytest <files> -q -p no:cacheprovider
```

| Files | Result |
| --- | --- |
| `test_interaction_mode_control_plane.py test_interaction_mode_protocol.py test_interaction_mode_contract.py` | **204 passed** (92 + 12 + 100; control plane 72 → 92, protocol 11 → 12) |
| `test_v2_speech_scheduler.py test_control_center_mvp.py` | **57 passed** |
| `test_documented_routes.py test_app.py` | **23 passed** |
| `test_speech_scheduler_review_races.py test_speech_presentation_scheduler.py test_voice_switch.py test_voice_composition.py` | **41 passed** |
| `test_settings_endpoints.py test_control_center_quality.py test_v2_event_bus.py` | **149 passed** |
| `test_live_idle_policy.py test_live_runtime_safety.py test_owner_barge_in.py test_v2_voice_toggle.py` | **69 passed** |
| `test_scene_settings.py test_scene_service.py` (baseline probe) | **4 failed, 61 passed** — the same 4 declared in `READINESS.md` §4 |

Zero new failures. The 26 baseline failures are untouched.

## Not changed, as instructed

The `runtime → core` import for `supported_modes()` stays: the precedent is real
and plural, `test_v2_architecture.py` permits it, and one door beats two tables
that drift.

---

# Slice 02 — journal-truth pass (third commit)

Runtime validation found no blockers. Two notes left, both about the journal
telling the truth — which is this slice's own thesis.

## N1 — an idempotent write no longer counts as a mode change

Re-posting the current mode emitted `interaction.mode.applied` ("réenregistré
sur PRESENTATION") right after Core's correct `interaction.mode.unchanged`. The
revision and the bus were already right; only the journal over-counted — 19
`.applied` against 2 `.unchanged` in the validation run, so anyone grepping
`.applied` to count real mode changes read a wrong number.

The Control Center now journals `interaction.mode.applied` **or**
`interaction.mode.unchanged`, and both carry an explicit `changed` boolean plus
the `disposition` they came from.

The verdict comes from **Core**, not from comparing two local preferences.
`CoreInteractionModeView._decode` keeps the `disposition` (`applied` /
`unchanged`) that a `POST` answers with; a `GET` has none, and the local
fallback carries `None`. This matters because the stored preference and the live
value can legitimately diverge — after a direct protocol call, writing
PRESENTATION for the first time here changes the preference but moves nothing,
and a local comparison would have written `.applied`. A Core that answers
without a disposition (older) falls back to the local comparison rather than
going silent.

Tests: `test_une_reecriture_sans_changement_ne_se_compte_pas_comme_un_changement`
(2 real toggles against 3 no-ops, asserted apart),
`test_le_verdict_vient_de_core_pas_d_une_comparaison_de_preferences_locales`,
`test_sans_verdict_de_core_le_journal_retombe_sur_la_comparaison_locale`.

## N2 — the unreadable-setting line names what was stored

`interaction.mode.defaulted` carried only `stored_schema_version` on the
`invalid_value` branch, while the reserved-mode branch of the *same kind*
carried `"mode": "meeting"`. From the trace alone `fromage` and `gruyere` were
the same incident, and telling them apart meant calling
`GET /api/interaction-mode` — a route with no caller until Slice 03.

Both branches now carry `stored_value`, and the unreadable one names it in the
message too. A mode value is a short operator-chosen token, not user content,
and it is bounded exactly as the other emitters bound theirs:
`MAX_JOURNALLED_VALUE_CHARS = 64`, applied by a `_short()` helper, so a
hand-edited settings file cannot fill `trace.jsonl`.

Tests: `test_la_ligne_d_un_reglage_illisible_nomme_ce_qui_etait_enregistre`
(`fromage` / `gruyere` parametrized),
`test_les_deux_branches_du_repli_nomment_la_valeur_enregistree`,
`test_une_valeur_enregistree_demesuree_est_bornee_avant_le_journal`.
`CHAMPS_DE_JOURNAL_AUTORISES` gains `changed`, `disposition` and
`stored_value`, so the content-leakage test still covers every field these
emitters write.

## Validation

```
.venv/Scripts/python.exe -m pytest <files> -q -p no:cacheprovider
```

| Files | Result |
| --- | --- |
| `test_interaction_mode_control_plane.py` | **99 passed** (92 → 99) |
| `test_interaction_mode_protocol.py test_interaction_mode_contract.py` | **112 passed** (12 + 100) |
| `test_control_center_mvp.py test_v2_speech_scheduler.py test_documented_routes.py` | **60 passed** |
| `test_settings_endpoints.py test_control_center_quality.py` | **140 passed** |

Zero new failures; the 26 baseline failures are untouched.

## Left alone, as instructed

The 2 s `/api/status` cost of the interaction-mode read. It is a judgement call
for the Human, not something to change here.
