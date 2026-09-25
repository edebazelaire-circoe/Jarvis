# Slice 04 - Implementation report

| | |
| --- | --- |
| Branch | `task/jarvis-presentation-interaction-mode` |
| Commits | `4078acc` (implementation), `1814d84` (this report), plus the rework commit that carries section 11 |
| Scope | Bounded session-scoped state. **No producer** (Slice 06), **no consumer** (Slices 08/10), **no UI** (Slice 09). |
| Canonical doc | `docs/presentation-working-set.md` (new), linked from `docs/ARCHITECTURE.md` and `docs/interaction-mode.md` |
| New suite | `tests/unit/test_presentation_working_set.py` - **90 passed** |

## 1. What was built

### `jarvis/domain/presentation_working_set.py` (new, pure)

Types, bounds and pure eviction rules. Imports nothing but the standard library
and `jarvis.domain._checks`.

- Vocabularies: `UtteranceOrigin{ambient, addressed}`,
  `ResourceTemperature{hot, warm, discardable}` (with `rank` for eviction and
  `cooled()`), `ResourceKind{document, web_page, chart_descriptor, scene_object,
  dataset, note}`, `ClaimStatus{asserted, supported, contradicted, uncertain}`,
  `AttentionCategory`, `AttentionSeverity`.
- `ObservationProvenance(utterance_id, sequence, observed_at, origin, source_ids)`
  - copied into every record at creation and never rewritten afterwards.
- Seven record types: `PresentationTopic`, `PresentationEntity`,
  `PresentationClaim`, `PresentationSource`, `PreparedResource`, `OpenQuestion`,
  `AttentionItem`. All frozen, slotted, self-validating, each exposing
  `record_id` and `sort_key`.
- `ResourceReference(kind, locator, title, descriptor)` - the typed reference,
  with `check_descriptor` for the safe structured form.
- `PresentationTranscriptTail` and `PresentationWorkingSet` - each a bounded,
  self-validating immutable collection holder.
- `PresentationContextSnapshot` - the atomic pair, with
  `enrichment_lag_entries`, `enrichment_lag_s`, `counts()`, `to_payload()` and
  `authorizes_actions: ClassVar = False`.
- `PresentationObservation(observation_id, session_id, record)` - the single
  door into the working set, carrying the dedup key and the session guard.
- Pure rules: `in_eviction_order`, `evict_to_limit`, `prune_by_age`,
  `derived_temperature`.
- `PresentationWorkingSetError(code, message)` - Slice 01's error convention.

### `jarvis/core/presentation_working_set.py` (new, the store)

`PresentationWorkingSetStore` - single-owner, synchronous, in memory only.
`bind_session` / `end_session` / `retire` / `apply_interaction_mode` /
`observe` (tail) / `apply` (working set) / `use_resource` / `prune`.
Every call returns a `PresentationStateResult(disposition, code, revision,
evicted)`.

### `jarvis/core/interaction_mode.py` (+38 lines)

`InteractionModeService.add_listener(callable)` plus `_notify`, called inside
`_set` after the state is committed and **before** the bus publish. Narrow by
design: the listener receives the typed mode, is synchronous, and cannot block
the mode change - a raising listener is journalled as
`interaction.mode.listener_failed` at `error` and swallowed.

### `jarvis/core/v2_app.py` (+13 lines)

`self.presentation_working_set = PresentationWorkingSetStore(diagnostics=...)`,
next to `interaction_mode`, and one `add_listener` wiring the retirement.

### Docs

`docs/presentation-working-set.md` (new contract page, the repository's
convention since `state-model.md` / `scene-model.md`), linked from the *Core
contracts* domain-state-model line and the *Interaction mode* section of
`docs/ARCHITECTURE.md`, and from the *Deliberate limits* section of
`docs/interaction-mode.md`.

## 2. Every bound, with its rationale

| Constant | Value | Why this number |
| --- | ---: | --- |
| `MAX_WORKING_SET_TOPICS` | 12 | same order as `MAX_BRAIN_WORK_ACTIVE`; past a dozen live topics nobody follows, neither the speaker nor the brain |
| `MAX_WORKING_SET_ENTITIES` | 24 | two entities per live topic |
| `MAX_WORKING_SET_CLAIMS` | 24 | two checkable claims per live topic |
| `MAX_WORKING_SET_SOURCES` | 12 | one source per claim actually verified |
| `MAX_PREPARED_RESOURCES` | 16 | speculative work is sacrificial (D08); beyond this we prepare more than we will ever show |
| `MAX_OPEN_QUESTIONS` | 12 | one per live topic |
| `MAX_ATTENTION_ITEMS` | 8 | same bound as `MAX_BRAIN_WORK_ATTENTION`: what can be signalled without drowning |
| `MAX_TAIL_ENTRIES` | 16 | a deictic reaches back a handful of sentences, not a chapter |
| `MAX_TAIL_CHARS` | 4000 | the tail is a window, not a transcript |
| `MAX_TAIL_ENTRY_CHARS` | 600 | one utterance; producers clip with `clip_text` beyond it |
| `MAX_PRESENTATION_ID_CHARS` | 64 | shorter than the domain's 128: these ids are minted here, never copied from a provider, and they weigh in the snapshot |
| `MAX_TOPIC_LABEL_CHARS` / `MAX_ENTITY_LABEL_CHARS` / `MAX_ENTITY_KIND_CHARS` | 120 / 96 / 32 | one-line labels |
| `MAX_CLAIM_CHARS` | 320 | a claim is a sentence; what does not fit in 320 is not a checkable claim |
| `MAX_QUESTION_CHARS` | 200 | an open question, not an essay |
| `MAX_SOURCE_TITLE_CHARS` / `MAX_RESOURCE_TITLE_CHARS` | 120 | one-line titles |
| `MAX_REFERENCE_CHARS` | 300 | a URL, a path, a document or scene-object id |
| `MAX_DESCRIPTOR_CHARS` / `_KEYS` / `_ITEMS` / `_TEXT_CHARS` | 600 / 16 / 32 / 120 | a chart series, not a dataset |
| `MAX_ATTENTION_REASON_CHARS` | 160 | one line for Slice 09's floating warning |
| `MAX_PROVENANCE_SOURCES` / `MAX_ATTENTION_RESOURCES` | 4 / 4 | citations, not bibliographies |
| `MAX_WORKING_SET_CHARS` | 120000 | hard ceiling on the compact JSON form, proving "max count x max size" is finite and known. **Not** a prompt budget - that is Slice 10's projection, as `MAX_BRAIN_WORK_CONTEXT_CHARS` is for work. Raised from 80000 in the rework: the real maximum is 92265 (section 11, B3) |
| `MAX_TAIL_AGE_S` | 180 | three minutes of speech is "recent"; older is not |
| `MAX_WORKING_SET_AGE_S` | 1800 | half an hour: an ordinary presentation |
| `MAX_RESOURCE_IDLE_S` | 600 | ten minutes untouched and a prepared resource is no longer warm |
| `MAX_SEEN_OBSERVATIONS` | 128 | above anything an ambient producer can replay at once (the whole set is about 100 records) |
| `MAX_RETIRED_RESOURCE_KEYS` | 64 | same rule as `MAX_EVICTED_KEYS` in the work store, at session scale |

**Corrected claim (rework B3).** The first version of this report said the
ceiling "can never refuse a legal set", proved by a test that built a
*half*-maximal set. The genuinely maximal set measures 92265 characters against
the old ceiling of 80000. The ceiling is now 120000, the test builds the
actually maximal set
(`test_le_plafond_de_caracteres_passe_au_dessus_de_l_ensemble_reellement_maximal`),
and hitting the ceiling anyway is a typed `CAPACITY` refusal rather than a bare
`ValueError` out of a public method.

## 3. Eviction rules

Every record exposes `sort_key`; collections are held in that order, and
eviction always removes **from the head**. Every `sort_key` ends with the record
id, so two records sharing a timestamp are evicted in a stable, reproducible
order (`test_deux_enregistrements_de_meme_date_sont_evinces_dans_un_ordre_stable`
builds the same store three times and compares).

| Collection | `sort_key` |
| --- | --- |
| topics / entities / claims | `(last_seen_at, id)` |
| sources | `(retrieved_at, id)` |
| questions | `(asked_at, id)` |
| attention | `(raised_at, id)` |
| **resources** | `(temperature.rank, last_used_at, id)` - discardable, then warm, then hot |
| tail | `(sequence,)` |

Order of operations in `_bounded_working_set`: age prune, then the topic count
bound, then the derived temperatures (which depend on the surviving topics),
then the resource count bound. That order is what makes the cascade meaningful:
a topic that falls first cools what was prepared for it, and only then does the
resource budget choose.

The tail is bounded age, then total chars, then count, always from the head.

Age is measured **from the newest known speech / the newest commit**, never from
a wall clock, which is what makes the rules deterministic under test.
`prune(now)` is the explicit sweep for a store that stops hearing anything
(Slice 06's idle tick).

Two refusals rather than accept-then-drop: if the incoming record is the one
that would be evicted, the call returns `CAPACITY`
(`presentation_<collection>_full`) or `STALE` (`presentation_record_too_old`).
A caller told "applied" can always read back what it stored.

**Corrected claim (rework B1).** The first version of this report said "nothing
is written" on a refusal. That was true of the snapshot and false of the store:
the bounding computation retired resource ids while it was still deciding. It
is now true without qualification — see section 11, B1.

## 4. What was reused, and what deliberately was not

**Reused**

- **`VoiceStateDisposition`** (`jarvis/core/voice_state.py`), imported and used
  as-is. "Applied / ignored / duplicate / stale / stale_session / rejected /
  capacity" is exactly the question asked of every observation; a second
  vocabulary for the same question is how two truths start. All seven values are
  reachable, and
  `test_le_magasin_parle_le_vocabulaire_de_disposition_deja_en_place` drives six
  of them in one store. The per-call `code` says *why*, as in `VoiceStateResult`.
- **The `VoiceStateResult` shape** - `(disposition, code, revision)` plus
  `authorizes_actions = False`. Renamed `PresentationStateResult` (a result named
  `Voice*` in a presentation store would be a lie) and given one extra field,
  `evicted`.
- **`VoiceConversationState`'s single-owner discipline** and its "atomic between
  awaits, never from a thread" contract, quoted in the module header.
- **`jarvis/domain/_checks.check_text`** - which is *also* how the no-raw-audio
  rule is held: it refuses anything that is not a `str`.
- **The `MAX_*` module-constant convention with the rationale in the header**,
  from `jarvis/domain/brain_context.py` and `jarvis/domain/work_state.py`.
- **`brain_context._compact_size`'s technique** for the size ceiling
  (`compact_chars`, compact JSON).
- **`work_state`'s `MAX_EVICTED_KEYS` idea** - a bounded memory of what was
  dropped so a late message cannot resurrect it - re-applied to prepared
  resources at session scale.
- **`MAX_JOURNALLED_VALUE_CHARS = 64`** and the `_short()` helper, from
  `jarvis/runtime/control_center.py` (Slice 02's lesson).
- **Slice 01's `behaving_interaction_mode`** for the lifecycle, and its
  `XxxError(code, message)` convention.
- **`WorkStateStore`'s "in memory only, a restart starts empty"** ownership
  stance, and the `DiagnosticSink` + dotted-kind journalling of every other Core
  service.

**Deliberately not reused**

- **`jarvis/runtime/conversation_context.py` / `selected_voice_context`.** It is
  a different thing: it projects the last 8 *committed* turns of a conversation
  into a provider context, lives as long as the conversation, and only knows
  addressed speech. The tail holds *ambient, revisable, uncommitted* utterances,
  for one session, with an age budget, and exists precisely so a command can be
  resolved *before* enrichment commits anything. Reusing it would have tied the
  freshness guarantee to committed turns - the exact staleness D06 forbids. Its
  "bounded count + bounded total chars" shape is reused; its code is not. It
  also lives in `runtime`, which Core must not import.
- **`WorkItem` / `WorkStateStore`.** Constraint G5: the work lane has no
  priority field and keeps none. Nothing here is a work item, nothing was added
  to `WorkItem`, and no P0-P4 exists in this slice.
- **`AddressingDecision`** - untouched (G7). Origin is a local
  `UtteranceOrigin{ambient, addressed}` on tail entries and provenance, not a
  widening of the closed, wire-encoded, persisted enum.
- **`BackBrainTaskService`'s 5-tuple dedup key.** Its shape is right for a
  cross-process submission; here the producer is in-process and a single
  `observation_id` plus the session guard covers replay. The *flat capacity of
  32* idea did carry over as `MAX_SEEN_OBSERVATIONS`.
- **`CoreEventBus` for the lifecycle.** Argued at the end of section 5.
- **The scene's `Disposition{active, archived}`** - not imported, not shadowed,
  not extended (G2).
- **Any persistence.** No repository, no adapter, no history store, no
  `sqlite3` - D13.

## 5. How each binding constraint is discharged

| Constraint | Discharge | Test that proves it |
| --- | --- | --- |
| **Raw audio never enters, never persisted** | every text field goes through `check_text`, which raises on a non-`str`; the tail refuses the buffer with `REJECTED` / `presentation_tail_entry_invalid` | `test_le_fil_refuse_un_tampon_d_audio_brut` (x3: `bytes`, `bytearray`, `memoryview`), `test_aucun_champ_de_texte_d_un_enregistrement_n_accepte_un_tampon_d_audio` (12 construction sites x 3 payloads), `test_aucun_champ_d_enregistrement_ne_porte_un_nom_d_audio` |
| **Prepared resources are typed references, not payloads** | `ResourceReference` refuses `<`, `javascript:`, `data:text/html` in locator, title and every descriptor string, with the typed code `presentation_resource_not_a_reference`; `check_descriptor` allows only a flat table of scalars or bounded scalar lists | `test_une_ressource_preparee_refuse_une_charge_utile_executable` (5 spellings), `test_un_descripteur_ne_peut_pas_cacher_du_balisage`, `test_un_descripteur_n_accepte_ni_structure_profonde_ni_objet_vivant` (nested dict, nested list, a callable, NaN, a non-mapping), `test_un_descripteur_est_borne_en_cles_en_valeurs_et_en_taille`, and `test_un_descripteur_legitime_de_graphique_passe` so the rule is not merely restrictive |
| and the tail is *not* subject to it | speech may contain `<`; the tail validates size and type only | `test_le_texte_du_fil_peut_contenir_un_chevron_car_ce_n_est_pas_une_reference` |
| **Bounded and deterministic** | `MAX_*` constants with rationale in the header; `sort_key` ending in the id; eviction always from the head | `test_chaque_collection_de_l_ensemble_de_travail_tient_sa_borne` (parametrized over all 7 collections), the three tail-bound tests, `test_deux_enregistrements_de_meme_date_sont_evinces_dans_un_ordre_stable`, `test_une_ressource_jetable_part_avant_une_tiede_et_une_tiede_avant_une_chaude`, `test_les_sujets_partent_du_plus_anciennement_mentionne_au_plus_recent`, `test_une_collection_pleine_refuse_plutot_que_d_accepter_puis_de_jeter` |
| **No accidental trace widening** | journal lines carry counts, bounded ids and stable codes; values clipped at 64 | `test_le_journal_ne_porte_jamais_le_texte_de_ce_qui_a_ete_dit` (plants a secret phrase, drives 6 operations, searches every emitted kind/message/data for it), `test_les_cles_du_journal_restent_dans_une_liste_blanche` (allow-list + scalar-only + length), `test_le_chemin_normal_est_journalise_autant_que_les_refus` |
| **Lifecycle: mode change or session end retires** | `apply_interaction_mode` reads `behaving_interaction_mode` and retires on anything that is not PRESENTATION; `end_session`/`bind_session` retire too | `test_quitter_presentation_retire_la_seance_immediatement`, `test_le_mode_reserve_reunion_ne_maintient_pas_une_seance_de_presentation`, `test_un_mode_illisible_retire_la_seance_plutot_que_de_la_laisser_vivre` (5 hostile values), `test_rester_en_presentation_ne_retire_rien`, `test_la_fin_de_seance_vide_les_deux_moities`, `test_lier_une_nouvelle_seance_retire_la_precedente_et_fait_monter_la_generation`, `test_une_observation_de_la_seance_retiree_n_atterrit_pas_dans_la_suivante`, and **`test_core_cable_la_memoire_de_seance_sur_le_mode_vivant`**, which builds a real `JarvisCoreApplication` and drives its own `interaction_mode.request` |
| **`behaving_`, never `stored_`** | the only mode reading in the module | `test_le_mode_reserve_reunion_ne_maintient_pas_une_seance_de_presentation` - REUNION retires, which `stored_interaction_mode` would not have caused |
| **Domain/core import no provider or UI** | domain imports stdlib + `jarvis.domain._checks`; core imports `jarvis.core.voice_state`, `jarvis.domain.*`, `jarvis.ports.v2.DiagnosticSink` | `test_v2_architecture.py` (re-run green) plus three local guards: `test_le_domaine_de_la_seance_ne_depend_que_de_la_bibliotheque_standard`, `test_le_magasin_ne_prend_du_port_de_diagnostic_que_le_puits`, `test_ni_le_domaine_ni_le_magasin_n_importent_de_persistance` |
| **D13 - not long-term memory, never auto-appended** | no persistence import, no repository parameter, in-memory only | the AST guard above **and** `test_rien_ne_survit_a_la_reconstruction_du_magasin`, which fills a store, builds a second one the same way, and finds it empty even after binding the same session id |
| **D06 - the tail is fresh independently of enrichment** | two separate write paths that never call each other; both lag readings are measured from `observed_sequence` | `test_le_fil_reste_frais_quand_l_enrichissement_prend_du_retard`, `test_l_instantane_dit_combien_d_enonciations_l_analyse_n_a_pas_rattrapees`, `test_un_deictique_se_resout_sur_la_derniere_parole_pas_sur_le_dernier_fait`, `test_une_analyse_jamais_partie_annonce_le_retard_maximal_pas_zero`, `test_un_enregistrement_sans_provenance_ne_remet_pas_le_retard_a_zero`, `test_le_retard_de_l_enrichissement_se_mesure_aussi_en_secondes`, `test_un_enrichissement_a_jour_ne_declare_aucun_retard`. **Corrected claim (rework B2)**: the first version framed `enrichment_lag_s` as the D06 measure while it computed time since the last commit of anything - see section 11, B2 |
| **Snapshot atomicity - no torn read** | one `self._snapshot` reference, rebound whole; a refused call rebinds nothing | `test_une_lecture_faite_pendant_une_ecriture_voit_un_instant_coherent` (re-entrant read from inside the store's own journal call: the tail write left the working set whole and vice versa, and the journalled counts describe the same instant as the snapshot read), `test_une_validation_qui_leve_pendant_le_commit_laisse_l_instantane_intact` (the snapshot constructor is made to raise; the held snapshot is still the identical object), `test_une_operation_refusee_ne_change_ni_la_revision_ni_le_contenu` (4 refusal shapes), `test_un_instantane_deja_pris_ne_bouge_pas_quand_le_magasin_ecrit`, `test_un_instantane_est_immuable_et_n_autorise_aucune_action` |
| **Dedup / coalescing** | `observation_id` memory for replay; per-type merge; attention deduped by `(category, claim_id, topic_id)` | `test_une_observation_rejouee_ne_recompte_pas_la_mention_d_un_sujet`, `test_deux_mentions_distinctes_du_meme_sujet_sont_coalescees`, `test_deux_fois_la_meme_contradiction_ne_font_qu_un_point_d_attention`, `test_deux_contradictions_sur_deux_affirmations_restent_deux_points`, `test_la_meme_revision_deux_fois_est_un_doublon_et_non_un_changement`, `test_la_memoire_des_observations_vues_est_bornee` |
| **Provenance preserved through eviction** | provenance and `first_seen_at` are never rewritten by a merge | `test_la_coalescence_ne_reecrit_jamais_la_provenance_ni_la_premiere_vue`, `test_la_provenance_survit_a_l_eviction_de_l_enonciation_qu_elle_cite` (the utterance leaves the tail; the claim still names it, with its sequence and time), `test_une_affirmation_verifiee_garde_la_provenance_de_qui_l_a_dite` |
| **A stale prepared resource does not resurrect** | bounded retired-id memory, `STALE` / `presentation_resource_retired` | `test_une_ressource_evincee_ne_renait_pas_d_une_preparation_tardive`, `test_utiliser_une_ressource_retiree_est_refuse_et_ne_la_recree_pas`, `test_la_memoire_des_ressources_retirees_est_bornee` (proves both that the memory is bounded and that a recent key is still refused) |
| **Tail order / revision** | a revision keeps the original sequence; an older revision is refused | `test_une_revision_de_transcription_garde_le_rang_de_l_enonciation`, `test_une_revision_plus_ancienne_que_celle_detenue_est_ecartee` |

### Why the lifecycle listener is synchronous and not a bus subscriber

Core already publishes `interaction.mode.changed` on `CoreEventBus`, and Voice
consumes it through `/v1/events`. That is the right channel to *learn* a mode
change. It is the wrong channel to *stop holding what was said in the room*: a
bus subscriber is a queue plus a consumer task, so the session would stay alive
for at least one event-loop hop after the user left PRESENTATION, and a full
subscriber queue (the bus evicts or drops) could leave it alive indefinitely.

So `InteractionModeService` gained `add_listener`, called inside `_set` after
the state is committed and before `_publish`. The contract is deliberately
narrow: typed mode in, synchronous, cannot veto, and a raising listener is
journalled (`interaction.mode.listener_failed`, level `error`) and swallowed -
a state that refuses to retire must not block a user leaving PRESENTATION.
`test_un_observateur_de_mode_en_echec_n_empeche_pas_le_changement_de_mode`
pins that.

This is the only change to a module Slice 02 owns: +38 lines, additive, with no
existing behaviour altered. `test_interaction_mode_control_plane.py` (72) and
`test_interaction_mode_protocol.py` (11) are green.

## 6. Test quality - the Slice 03 lesson

No test in this suite asserts on source text. There is no `inspect.getsource`
and no substring match over a module. The three structural tests parse the AST
and assert on the **import graph**, which is the same technique
`test_v2_architecture.py` already uses, not a text search over prose.

Because "the tests pass" is not the same as "the tests would catch it", six
mutations were introduced one at a time into the production modules and the
suite re-run each time:

| Mutation | Result |
| --- | --- |
| journal the tail entry's **text** instead of its length | **caught** (1 failed) |
| drop `temperature` from the resource `sort_key` | **caught** |
| remove the retired-resource guard | **caught** |
| accept a transcript revision older than the one held | **caught** |
| give a revision a new sequence (so a correction becomes the freshest speech) | **caught** |
| accept-then-evict instead of refusing a full collection | **caught** |

All six were reverted; the committed tree is the unmutated one.

## 7. Failure paths, enumerated

| Case | Answer | Test |
| --- | --- | --- |
| No session bound | `IGNORED` / `presentation_working_set_inactive`, revision unchanged | `test_un_magasin_sans_seance_ecarte_tout_sans_rien_fabriquer` |
| Observation from a retired session | `STALE_SESSION` | `test_une_observation_de_la_seance_retiree_n_atterrit_pas_dans_la_suivante` |
| Replayed observation | `DUPLICATE`, no second mention | `test_une_observation_rejouee_ne_recompte_pas_la_mention_d_un_sujet` |
| Same tail revision again | `DUPLICATE`, snapshot identical | `test_la_meme_revision_deux_fois_est_un_doublon_et_non_un_changement` |
| Older tail revision | `STALE` | `test_une_revision_plus_ancienne_que_celle_detenue_est_ecartee` |
| Speech older than the window | `STALE` / `presentation_tail_entry_too_old`, not stored-then-dropped | `test_une_parole_arrivee_trop_tard_est_dite_perimee_plutot_que_rangee_puis_jetee` |
| Record older than the age budget | `STALE` / `presentation_record_too_old` | `test_une_observation_plus_vieille_que_le_budget_d_age_est_dite_perimee` |
| Collection full, incoming record is the loser | `CAPACITY`, nothing written | `test_une_collection_pleine_refuse_plutot_que_d_accepter_puis_de_jeter` |
| Retired resource re-prepared or used | `STALE` / `presentation_resource_retired` | two tests |
| Unknown resource used | `IGNORED` / `presentation_resource_unknown` | `test_utiliser_une_ressource_inconnue_ne_fabrique_rien` |
| Not an observation, raw audio, over-long text | `REJECTED`, nothing journalled about the content | `test_une_operation_refusee_ne_change_ni_la_revision_ni_le_contenu` |
| Journal unavailable (raises on every emit) | the session is still held | `test_un_journal_en_panne_n_empeche_pas_de_retenir_la_seance` |
| Mode listener raises | mode change succeeds, failure journalled at `error` | `test_un_observateur_de_mode_en_echec_n_empeche_pas_le_changement_de_mode` |
| Unreadable mode value | the session is retired, not kept | `test_un_mode_illisible_retire_la_seance_plutot_que_de_la_laisser_vivre` |
| Retire twice | `IGNORED`, no spurious generation bump | `test_retirer_une_seance_deja_retiree_ne_fait_rien_et_le_dit` |

The expected path is journalled at `info` (`bound`, `applied`, `observed`,
`retired`, `evicted`) alongside the refusals, so "nothing in the journal" cannot
mean both "fine" and "nothing is getting in".

## 8. Validation

All foreground, narrow file lists (the host runs under 2 GB free RAM).

```
.venv/Scripts/python.exe -m pytest FILES -q -p no:cacheprovider
```

| Files | Result |
| --- | --- |
| `tests/unit/test_presentation_working_set.py` | **90 passed** |
| `test_v2_architecture.py test_brain_work_context.py test_work_state_store.py test_interaction_mode_contract.py test_interaction_mode_control_plane.py` (the five mandated re-runs) | **291 passed** |
| `test_interaction_mode_protocol.py test_v2_event_bus.py test_v2_persistence.py test_app.py` | **43 passed** |
| `test_v2_domain.py test_v2_wire_form.py test_back_brain_speculative.py test_scene_projector.py` | **68 passed** |
| `test_v2_speech_scheduler.py test_control_center_mvp.py test_v2_voice_toggle.py` | **92 passed** |
| `test_documented_routes.py test_control_center_quality.py` (after the doc edits) | **76 passed** |
| `test_scene_service.py test_scene_settings.py` (baseline probe) | **4 failed, 61 passed** - exactly the four declared in `READINESS.md` section 4 and re-measured identically by Slice 02 |

**Zero new failures.** None of the 26 pre-existing baseline failures was
touched, fixed or added to.

## 9. Where SLICE.md and the live repository disagreed

Reported, not silently resolved.

1. **"Bounded in-memory/session-scoped store owned by Core or Core service"
   leaves the *lifecycle trigger* unspecified, and the repository has no seam for
   it.** Slice 02 put the live mode on `CoreEventBus`; the only Core-side
   subscriber pattern in the repository is a queue plus a consumer task
   (`_work_attention_task`). Using it would make the retirement asynchronous,
   which is wrong for this particular state (see the end of section 5). I added a
   narrow synchronous `add_listener` to `InteractionModeService` instead - a
   change to a module Slice 02 owns. It is additive, 38 lines, and both Slice 02
   suites are green, but it is a boundary the coordinator should look at rather
   than discover.

2. **SLICE.md names "unresolved items" and "attention items" as separate
   in-scope types; `docs/02-architecture.md` names "open questions/uncertainties"
   and "attention items".** I implemented `OpenQuestion` (open questions and
   uncertainties) and `AttentionItem`, and treated "unresolved items" as the same
   concept as "open questions", because nothing in the decision log distinguishes
   them. If the coordinator meant a third type, it is missing.

3. **`AttentionCategory` and `AttentionSeverity` are declared here, while
   `docs/02-architecture.md` gives the typed `PresentationAttention` event to the
   Slice 09 notification path.** I kept only the minimal vocabulary this store
   needs to hold an attention item and said so in the contract page; Slice 09 may
   widen the categories. Two enums for one concept is a risk the coordinator
   should track - Slice 09 should extend these rather than declare its own.

4. **The `coding-guideline` documentation chain names `docs/CONTEXT.md` and
   `docs/documentation-level-registry.yaml`, neither of which exists in this
   repository** - already reported by Slices 01 and 02. The actual convention was
   followed: a dedicated `docs/<concept>.md` contract page (as `state-model.md`
   and `scene-model.md` do), linked from `docs/ARCHITECTURE.md`. No feature
   `INDEX.md` exists for this surface.

5. **The `error-handling` skill's contract (`send_error_response`,
   `obsClientLog`, `docs/observability/error-handling.md`) does not exist in this
   repository** - reported by Slice 02, still true. The rules were followed
   through the repository's actual machinery: `DiagnosticSink.emit` with dotted
   kinds, typed refusals with stable codes, and every broad `except` either
   re-raising, recording through the journal, or carrying a written argument
   (there are two: the journal's own `except` and the mode listener's, both
   argued in place).

   Rule Zero's *visible feedback* obligation has no surface to land on in this
   slice - there is no user-facing path yet, by design. It is discharged as far
   as this layer can: every operation returns a typed disposition and a stable
   code rather than a silent no-op, and the expected path is journalled, so the
   consumer built in Slices 08-10 has something true to show.

## 10. Nothing refused

Every SLICE.md acceptance criterion is implemented and covered: the working set
is deterministic and bounded, the transcript tail is independently fresh and
bounded, there is one safe atomic context snapshot, and leaving Presentation
follows a rule written down in `docs/presentation-working-set.md`, section
*Lifecycle*. The four out-of-scope items (ambient producers, sub-agent
execution, UI rendering, automatic long-term memory writes) are untouched - and
the last of them is enforced by a test, not by intention.


---

# Slice 04 - rework pass (third commit)

Four blocking defects and ten smaller items, from two independent QA passes.
Everything below is inside this slice's own surface, plus the two documentation
files it touches.

## The method note, taken

None of B1-B4 was in my six mutations, and the reason is worth writing down:
mutation testing proves the tests catch changes to the paths they already
drive, and says nothing about paths they do not. All four blockers lived in the
gap between an invariant **stated in a header** and the same invariant
**exercised at its edge**. Every fix below therefore carries a test aimed at
the edge, and the rework closes with a second mutation round that targets each
fixed defect specifically.

## B1 - a refused `apply()` wrote to store state

`_bounded_working_set` retired resource ids through `_retire_resource` *while
it was still deciding*, so a refusal returned after the store had already been
written. Two reproduced symptoms: a resource visible in the snapshot became
permanently unserviceable, and a `CAPACITY` refusal permanently banned an id
that was never stored - which is precisely what Slice 08's speculative lane
would have hit, since re-preparing after a capacity refusal is what it does.

**Fixed by making the computation pure with respect to the store.**
`_bounded_working_set` now returns a `_BoundedSet(working_set, dropped,
retired)` value and touches nothing; only the commit path calls
`_retire_resources(bounded.retired)`, immediately after `_commit`. It also
returns `None` rather than raising when the result would exceed the char
ceiling, so the caller turns that into a typed refusal.

The root cause of symptom (a) is closed a second time, at the domain door: a
record could carry a provenance of *now* and a recency of *an hour ago*, which
let it push the store's clock forward and then fail the age check itself.
`_span` now refuses a record observed after it was last seen.

`retired_resource_ids` is exposed read-only, because without it a test cannot
tell "nothing was written" from "the snapshot did not move" - which is exactly
how this defect survived the first round.

Tests: `test_un_refus_de_capacite_n_ecrit_rien_et_ne_bannit_aucune_ressource`
(and re-prepares the same id successfully afterwards),
`test_l_instantane_ne_peut_pas_annoncer_une_ressource_que_le_magasin_refusera`
(every resource still in the snapshot is still served after a refusal),
`test_un_enregistrement_observe_apres_sa_derniere_vue_est_refuse_a_la_porte`,
and `test_une_operation_refusee_ne_change_ni_la_revision_ni_le_contenu` now
asserts on `retired_resource_ids` too.

## B2 - `enrichment_lag_s` did not report the lag

It measured time since the last commit of *anything*. A never-enriched store
reported `0.0` - the worst possible lag, indistinguishable from caught up - and
a `PresentationSource`, which deliberately does not advance `observed_sequence`,
reset it to zero without a sentence having been understood. The two lag
readings actively contradicted each other.

**Fixed by computing both readings from `observed_sequence`.** The lag in
seconds is now the span between the last utterance the working set cites and
the newest one in the tail; when nothing has ever been enriched, the floor is
the oldest utterance still in the tail, so a store that never started reports
the largest lag. `committed_at` keeps its one job - advancing the age-budget
clock - and says so in a field comment.

Tests: `test_une_analyse_jamais_partie_annonce_le_retard_maximal_pas_zero`
(QA's case A, and the caught-up case beside it so the two are distinguishable),
`test_un_enregistrement_sans_provenance_ne_remet_pas_le_retard_a_zero` (cases B
and C, plus an assertion that the two readings never disagree on sign).

## B3 - the char ceiling was below the module's own maximum, and escaped untyped

Two faults in one. The ceiling was 80000 while the genuinely maximal set
measures **92265**; the test that claimed to prove it safe built a set with
short ids, empty descriptors and empty tuples, which is why its own margin
assertion was only `> MAX // 4`. And `apply()` wrapped nothing, so hitting the
ceiling raised a bare `ValueError` out of a public method whose entire contract
is that every call returns a typed disposition.

**Both fixed.** `MAX_WORKING_SET_CHARS` is 120000, about 30% above the measured
maximum - enough that a field correction will not flip it, little enough that
it still bounds something. `_bounded_working_set` returns `None` on the
ceiling and every caller turns it into `CAPACITY` /
`presentation_working_set_too_large`. The tail commit is wrapped the same way.

Tests: `test_le_plafond_de_caracteres_passe_au_dessus_de_l_ensemble_reellement_maximal`
(builds the actually maximal set: 64-char ids everywhere, full `source_ids`, a
maximal descriptor on all sixteen resources, a full attention reason - and
asserts both `<= MAX` and `> MAX // 2`), and
`test_le_plafond_de_caracteres_est_un_refus_type_et_non_une_exception`.

## B4 - the markup filter applied to all speech-derived text

`safe_text` was called from every record's `__post_init__`, so
`PresentationClaim(statement="la marge < 10 %")` raised - with a code naming a
*resource*, and out of a constructor the producer calls before `apply()` ever
sees the record. Slice 06 would have got exceptions instead of dispositions on
a path ordinary French analysis output hits.

**Fixed by splitting the check in two.** `bounded_text` (type + length +
required) is what speech-derived fields use: claim statements, topic and entity
labels, questions, attention reasons. `safe_reference_text` is what references
use: locators, source and resource titles, descriptor strings.

Tests: `test_le_texte_venu_de_la_parole_garde_le_droit_au_chevron` (five record
kinds), `test_une_affirmation_avec_un_chevron_se_range_normalement` (it goes
through the store and comes back intact), and the reference rules keep their
own tests.

## Also fixed

| # | Item | Fix and test |
| ---: | --- | --- |
| 1 | the synchronous-retirement guarantee was unfalsifiable | `test_la_seance_est_retiree_avant_que_le_changement_ne_soit_publie` - the listener reads `len(bus.published)` **at the moment it is called** and must see 0, so moving `_notify` after `_publish` fails it. Plus `test_un_abonne_de_mode_lit_deja_la_nouvelle_valeur_quand_il_est_appele` for the other half of the ordering |
| 2 | the refusal test drove only early refusals | the two B1 tests drive the capacity and age refusals, and the original now asserts `retired_resource_ids == ()` |
| 3 | the lag tests could not tell "never started" from "caught up" | the two B2 tests, which assert both cases side by side |
| 4 | unbounded exception text in `interaction_mode.py` | `MAX_TRACE_EXCEPTION_CHARS = 200` and a `_clip()` helper, applied to both sites (the listener failure and the publish failure). The test now keeps `message` and asserts the real cause is named *and* the line is bounded, against a 5000-character exception |
| 5 | scheme denylist | `ALLOWED_LOCATOR_SCHEMES` allowlist (`http`, `https`, `file`, `doc`, `chart`, `scene`, `dataset`, `note`); a scheme is at least two letters so `C:\rapports` stays a Windows path. `vbscript:` and `data:image/svg+xml` are now refused, and `test_un_localisateur_legitime_passe_la_liste_blanche` keeps the rule from being merely restrictive |
| 6 | attention coalescing never refreshed `raised_at` | `_merge_attention` takes `max()` of the two, like every other merge. `test_une_contradiction_toujours_signalee_ne_vieillit_pas_sur_place` re-raises at +90 s with a 100 s budget and then prunes at +150 s |
| 7 | dead members | deleted: `ResourceTemperature.cooled()` + `_TEMPERATURE_COOLED`, `PresentationWorkingSet.record_count`, `AttentionItem.resource_ids` + `MAX_ATTENTION_RESOURCES`, `ObservationProvenance.source_ids` (the live binding is `PresentationClaim.source_ids`, and the docstring now says why there is only one), and `TranscriptTailEntry.final` including its `observe()` parameter and its journal key |
| 8 | documentation on the module Slice 02 owns | `interaction.mode.listener_failed` added to the diagnostics table; the `add_listener` seam documented in *Live-truth owner - Core* with its ordering guarantee and its one caller; the link to the new page moved out of the Slice 01 *Deliberate limits* section and into the control-plane section |
| 9 | `_next_sequence` survived `retire()` and was bumped before the commit | reset to 1 in `retire()`, and bumped **after** `_commit`. `test_le_rang_des_enonciations_repart_de_zero_a_chaque_seance` and `test_un_commit_qui_leve_ne_brule_pas_un_rang_d_enonciation` |
| 10 | mixed encoding register | `jarvis/core/presentation_working_set.py` rewritten with accents throughout |

## Mutation round 2 - each fixed defect, re-broken

Every fix was reverted one at a time and the suite re-run:

| Mutation | Result |
| --- | --- |
| retire resources during the age prune (B1) | **caught** |
| retire resources during the capacity eviction (B1) | **caught** |
| measure the lag from `committed_at` (B2) | **caught**, 2 failures |
| lower the ceiling back to 80000 (B3) | **caught** |
| let the ceiling escape as `ValueError` (B3) | **caught** |
| put claim statements back through the reference rule (B4) | **caught**, 2 failures |
| publish before notifying (item 1) | **caught** |
| drop `raised_at=max(...)` from the attention merge (item 6) | **caught** |
| stop resetting `_next_sequence` in `retire()` (item 9) | **caught** |
| swap the scheme allowlist back for a denylist (item 5) | **caught** |

Ten for ten. All reverted; the committed tree is the unmutated one.

## Validation after the rework

| Files | Result |
| --- | --- |
| `test_presentation_working_set.py` | **118 passed** (was 90) |
| `test_presentation_working_set.py test_v2_architecture.py test_interaction_mode_contract.py test_interaction_mode_control_plane.py test_interaction_mode_protocol.py` | **337 passed** |
| `test_brain_work_context.py test_work_state_store.py test_v2_domain.py test_app.py` | **107 passed** |
| `test_v2_speech_scheduler.py test_control_center_mvp.py test_documented_routes.py test_control_center_quality.py` | **133 passed** |
| `test_v2_event_bus.py test_v2_persistence.py test_v2_wire_form.py test_back_brain_speculative.py test_scene_projector.py test_v2_voice_toggle.py` | **111 passed** |
| `test_scene_service.py test_scene_settings.py` (baseline probe) | **4 failed, 61 passed** - the same four as before |

Zero new failures; the 26 pre-existing baseline failures are untouched.

## Not re-justified

The cross-slice listener's design, the reuse claims, the raw-audio guarantee and
the trace hygiene were all checked and confirmed by QA; nothing about them
changed except the two additions above (the ordering test and the clipped
exception message).
