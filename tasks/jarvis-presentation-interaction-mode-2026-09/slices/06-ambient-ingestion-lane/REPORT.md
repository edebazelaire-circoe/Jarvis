# Slice 06 - Implementation report

| | |
| --- | --- |
| Branch | `task/jarvis-presentation-interaction-mode` |
| Commit | `4e85429` (implementation), plus this report |
| Scope | The ambient producer. **No composition-root wiring** (rollout slice), **no alert policy** (Slice 09), **no speculative execution** (Slice 08). |
| Canonical doc | `docs/presentation-ambient-lane.md` (new), linked from `docs/ARCHITECTURE.md` (x2), `docs/presentation-audio-capture.md` and `docs/presentation-working-set.md` |
| New suite | `tests/unit/test_ambient_ingestion_lane.py` - **75 passed** |

## 1. Files touched, and why

| File | Lines | Why |
| --- | ---: | --- |
| `jarvis/domain/ambient_observation.py` | +626 (new) | The types and the cheap analysis, pure. `AmbientUtterance`, `AmbientTrigger`, `AmbientTriggerKind`, `AmbientAnalysis`, `analyse_ambient_text`, `is_low_value_filler`, `looks_imperative`, `clip_ambient_text`. This is where D03 becomes a data structure. |
| `jarvis/audio/ambient_segmenter.py` | +344 (new) | `AmbientSegmenter` + `AmbientSegment`: utterance boundaries over the hub's PCM, reusing `duplex.frame_db` and `owner_verifier.SpeechGate`. Not in `domain/` **because it carries PCM**, and the session domain's one hard rule is that raw audio never enters it. |
| `jarvis/runtime/ambient_lane.py` | +933 (new) | `AmbientIngestionLane`: the hub subscription, three workers, two bounded queues, the disposition accounting, the telemetry. In `runtime/` because that is where the microphone and the hub live (the Voice process). |
| `jarvis/audio/capture.py` | +26/-7 | Extracted `pcm16_to_wav(pcm, sample_rate, channels)` from `SoundDeviceRecorder.stop()`, which was the only place that knew how to build the `AudioClip` the transcription port wants. `stop()` now calls it. A second copy would have been a second place to get `setsampwidth` wrong. |
| `tests/unit/test_ambient_ingestion_lane.py` | +1440 (new) | 75 tests, 100 after the rework. |
| `docs/presentation-ambient-lane.md` | +248 (new) | The contract page, the repository convention since `state-model.md`. |
| `docs/ARCHITECTURE.md` | +11 | The ambient-lane paragraph after the audio-ownership one, and the contract-page list at the top. |
| `docs/presentation-audio-capture.md` | +3/-2 | Its "what this contract does not yet do" said the ambient lane was Slice 06 and did not exist. It does now; the line points at the new page. |
| `docs/presentation-working-set.md` | +3/-2 | Same: "No producer. Nothing writes to this store yet" is no longer true. |

**No existing module behaviour was changed.** The only edit to live code outside the
new files is the `pcm16_to_wav` extraction, which is identical in effect
(`test_audio_capture.py` and `test_presentation_audio_capture.py` re-run green).

## 2. The seam, and why it is the least-duplicated one

`docs/presentation-ambient-lane.md` section 1 carries the full argument. Short form:

- **Audio in:** `AudioCaptureHub.subscribe("ambient_ingestion", sample_rate=None,
  max_blocks=64)`. Slice 05's `subscribe()` docstring names this lane by number.
  Nothing was added to the hub.
- **Speech to text:** `jarvis/ports/transcription.py::TranscriptionBackend`, the
  repository's only provider-neutral ASR seam: `AudioClip` in, `TranscriptionResult`
  out. **Not widened.** The one existing adapter (`OpenAITranscriptionBackend`)
  satisfies it unchanged, and so will a second provider. Before this slice the
  Protocol had *zero* importers - `factory.py` annotates the concrete class - so the
  lane is also the first thing in the repo to depend on the port rather than a vendor.
  **Corrected in the rework, R2.9: this was false as first written.** The lane
  declared a local look-alike Protocol returning `Any`, so the port was described
  rather than reused and still had zero importers. It is imported now, and the
  constructor annotation is the real contract.
- **Text out:** `PresentationWorkingSetStore.observe()` / `.apply()` / `.prune()`,
  exactly Slice 04's API. **No method was added to that store.** The lane declares a
  structural `PresentationObservationSink` Protocol over those three plus `snapshot`,
  satisfied by the store as it stands.
- **Only genuinely new code:** utterance segmentation (which did not exist in any
  form) and the cheap analysis.

### The seam I deliberately did not take, with evidence

The repository already produces ambient text a second way: the Realtime provider
transcribes continuously and `SoundDeviceRealtimeAudio.classify()` drops the
`AMBIENT` ones (`jarvis/runtime/realtime_audio.py`, around line 4430). Tapping there
would have looked like less duplication. It is the wrong seam:

1. in PRESENTATION the Realtime session is opened **for an addressed turn**, on an
   explicit-address trigger (D05). Ambient speech is by definition what happens when
   nobody is addressing JARVIS - there is no provider session then, so no transcript;
2. a Realtime session held open for a whole presentation is a metered connection with
   a hard ceiling (`PROVIDER_MAX_SESSION_SECONDS`), for audio that mostly needs
   nothing;
3. `tasks/.../docs/02-architecture.md` draws the ambient branch off the hub, in
   parallel with the explicit-address detector, precisely so ambient backlog cannot
   reach the command path.

The lane's text ingress is one method (`_observe`), so a future Realtime-derived
ambient transcript enters the same path rather than creating a second one.

### Anti-aliasing: the first branch, not a new filter

Slice 05's constraint was "either subscribe at the hub's native rate, or resample
properly". I took the first branch: the lane subscribes with `sample_rate=None` and
hands the hub's own 24 kHz PCM to the provider in a WAV that *states* its rate. No
resampler, no FIR, no numpy on this path, nothing new to get wrong. A provider that
wants 16 kHz converts with its own filter - that is its job, and it has one.
`test_le_segmenteur_travaille_a_la_frequence_du_hub_et_ne_convertit_rien` proves it by
bytes (a slice of the input is present verbatim in the segment), and mutation M2
(subscribing at 16 kHz) is caught by 26 tests.

## 3. Queue budgets, with rationale

| Budget | Value | Why this number |
| --- | ---: | --- |
| `DEFAULT_CAPTURE_BLOCKS` | 64 blocks (3.2 s, 150 KB) | the drain task only does energy arithmetic; 3.2 s covers a GC pause or a contended scheduler without losing a sentence |
| `DEFAULT_SEGMENT_QUEUE` | 3 | a segment is at most 12 s, so about 36 s of backlog. Past that the tail is so late that a deictic resolved on it is wrong - the staleness D06 exists to prevent |
| `DEFAULT_ANALYSIS_QUEUE` | 8 | analysis costs microseconds; this queue absorbs a burst and must never push back on the tail |
| `DEFAULT_TRANSCRIPTION_TIMEOUT_S` | 20 s | the largest clip is 12 s; a provider silent for 20 s describes a room that has changed subject |
| `MAX_SEGMENT_AGE_S` | 30 s | a segment that waited this long is discarded **and said**, not filed behind fresher speech |
| `MAX_CONSECUTIVE_TRANSCRIPTION_FAILURES` | 3 | the hub's number and the hub's reason: one or two are a hiccup, three are a fault that lasts |
| `IDLE_PRUNE_PERIOD_S` | 30 s | the store's age budgets are measured from the newest speech; with no speech nothing would fire them, and Slice 04 assigned that sweep here explicitly |
| `DEFAULT_MIN_UTTERANCE_MS` | 500 | below this it is a chair or a throat: a provider call that returns nothing |
| `DEFAULT_SILENCE_HANGOVER_MS` | 700 | above the pauses inside a sentence (200-400 ms), below the pause between two. Deliberately shorter than the provider VAD's 1500 ms default: the ambient lane prefers slightly over-cut utterances to a late tail |
| `DEFAULT_MAX_UTTERANCE_MS` | 12000 | the forced cut. 12 s of 24 kHz PCM is 576 KB; a longer clip makes the tail late. The continuation becomes a **revision** of the same utterance |
| `DEFAULT_LEAD_IN_MS` | 200 | kept before the first voiced frame so the attack of the first syllable is not eaten; same idea and order as `duplex.OWNER_REPLAY_MARGIN_MS` |

Policy is `drop_oldest` everywhere, the hub's rule and the hub's reason. Every drop
increments a named counter (`segments_dropped_queue`, `segments_dropped_stale`,
`segments_cancelled`, `analysis_dropped_queue`, `analysis_cancelled`,
`transcripts_failed` / `_timeout` / `_empty` / `_clipped`, `filler_suppressed`,
`imperative_utterances`, `trigger_callback_failures`, `revisions`, `prunes`, plus a
per-disposition table for each of the two store surfaces) and **`lane.stats()` prints
all of it**. An invariant that cannot be read is an invariant that drifts - Slice 04's
`retired_resource_ids` lesson, applied up front.

**Exactly one transcription worker.** The store assigns an utterance's rank at the
moment of the call, so two concurrent transcriptions would make tail order depend on
provider latency, and a sentence said earlier could be filed later. Parallelism would
be bought with the only thing the tail guarantees. Written into the module header.

## 4. How each binding constraint is discharged

| Constraint | Discharge | Test that proves it |
| --- | --- | --- |
| **G7 / D03 - ambient never becomes an addressed turn** | `AddressingDecision` untouched; both `AMBIENT` refusals untouched; `BackBrainTaskService` untouched (not imported, not referenced); `authorizes_actions` is a `ClassVar False` on `AmbientUtterance` / `AmbientTrigger` / `AmbientAnalysis`; `AmbientTriggerKind` is closed and holds only investigation natures | `test_aucun_declencheur_ambiant_n_autorise_une_action` (walks the whole enum), `test_une_enonciation_ambiante_n_autorise_jamais_une_action` (incl. `dataclasses.replace` and `FrozenInstanceError`), `test_un_tour_ambiant_ne_peut_pas_entrer_dans_l_admission_adressee` (drives both existing refusals), `test_l_enum_d_adressage_reste_fermee` |
| **Ambient imperative text authorizes nothing** | the analysis recognises the imperative, counts it (`AmbientAnalysis.imperative`, `counters.imperative_utterances`) and produces at most a topic; an imperative sentence is also not filed as a checkable claim | `test_une_phrase_a_l_imperatif_entendue_dans_la_salle_n_autorise_rien` (5 phrases incl. "ouvre le fichier" and "supprime la ligne 12"), plus end-to-end `test_une_consigne_entendue_dans_la_salle_ne_produit_aucune_autorisation_de_bout_en_bout`, which drives the real hub and the real store and then re-checks that the stored text still cannot become a `BrainTurnInput` |
| **Queued, not inline** (Slice 05: a slow inline sink starves its siblings, 10 blocks in 0.506 s) | `hub.subscribe(..., sink=None)` | `test_la_lane_est_un_abonne_queued_et_jamais_en_ligne` (`inline is False`, policy, rate). Mutation M3 fails 33 tests |
| **Native rate, no silent reuse of the wake resampler** | `sample_rate=None`; no resampler anywhere on the path | `test_le_segmenteur_travaille_a_la_frequence_du_hub_et_ne_convertit_rien` (byte-for-byte), mutation M2 |
| **Slice 04: the right text rule** | speech goes through the tail (`bounded_text`, `<` allowed); the lane creates no `ResourceReference`, so `safe_reference_text` is never reached | `test_une_analyse_ordinaire_contenant_un_chevron_ne_fait_pas_tomber_la_lane` |
| **Slice 04: typed dispositions handled explicitly** | `_DISPOSITION_POLICY` maps all seven values to (counter, journal level, is-a-loss); an unknown value is counted as `unknown` and said at `error` | `test_toutes_les_dispositions_du_magasin_ont_une_politique` (iterates `VoiceStateDisposition`), `test_chaque_disposition_du_fil_est_comptee_et_dite` (parametrized over all seven), `test_une_disposition_inconnue_est_dite_a_error_plutot_qu_ignoree`, `test_une_seance_retiree_ecarte_la_parole_sans_la_ranger_ailleurs` |
| **A refusal stops the enrichment too** | `_observe` returns without enqueueing analysis when the tail refused | `test_une_parole_refusee_par_le_fil_n_enrichit_rien` (4 dispositions) - **added after mutation M6 survived** |
| **D06 - tail before analysis** | `sink.observe()` is called before anything reaches the analysis queue, and the analysis has its own queue and its own task | `test_le_fil_est_ecrit_avant_toute_analyse` (order spy), `test_le_retard_de_l_enrichissement_se_lit_dans_l_instantane`, `test_la_parole_continue_met_le_fil_a_jour`. Mutation M1 fails 4 tests |
| **Provenance cites the real rank** | the assigned `sequence` is read back from the snapshot after each successful append | `test_la_provenance_cite_le_rang_reel_de_l_enonciation`; mutation M22 caught |
| **Revision and dedupe** | a force-cut segment's continuation revises the same utterance, keeping its rank; the store's `duplicate` is counted; two mentions of one topic coalesce instead of duplicating | `test_une_coupe_d_office_revise_l_enonciation_au_lieu_d_en_creer_une_seconde`, `test_deux_mentions_du_meme_sujet_sont_coalescees_et_non_dupliquees`, the `duplicate` row of the parametrized disposition test. Mutation M10 caught |
| **Bounded queues with counted drops** | `drop_oldest` plus counters plus one journal line per event | `test_une_file_de_segments_pleine_ecarte_le_plus_ancien_et_le_compte`, `test_une_file_d_analyse_pleine_ecarte_la_plus_ancienne_et_le_compte`, `test_le_segmenteur_ne_retient_jamais_plus_que_sa_borne`, `test_un_orateur_qui_ne_respire_pas_est_coupe_d_office`. Mutations M4, M5, M16, M17 caught |
| **Stale ambient work cancellable (D08)** | `discard_pending(reason)` drains both queues, counts, bumps `generation`; a transcript that returns after the cancellation is refused | `test_le_travail_ambiant_en_attente_s_annule`, `test_un_segment_trop_vieux_est_ecarte_plutot_que_servi_comme_du_frais`. **A real defect was found here on the first run** - see section 6 |
| **D04 - ambient backlog never delays explicit admission** | the lane holds no reference to `ExplicitAddressLane` and awaits nothing that belongs to it | `test_un_ouvrier_ambiant_lent_ne_retarde_pas_l_admission_d_un_declencheur`: a real `PresentationAudioSession` plus the lane on one hub, every transcription held 0.5 s, backlog confirmed, then the manual key pressed and the admission **measured** under 150 ms |
| **Failure isolation - ambient failure must not disable the command lane** | transcription failures are counted, said in the provider's own words, and the loop continues; after 3 consecutive the lane degrades (said once) and keeps trying rather than detaching | `test_une_transcription_en_echec_laisse_la_touche_manuelle_vivante` (same hub, same process, transcription dead for the whole session, manual key still delivers a trigger), `test_trois_echecs_consecutifs_degradent_la_lane_et_le_disent_une_fois`, `test_une_lane_degradee_se_retablit_et_le_dit`, `test_apres_un_retablissement_un_echec_isole_ne_redegrade_pas_la_lane`, `test_un_delai_de_transcription_libere_l_ouvrier` |
| **No raw audio anywhere** | PCM lives in a bounded `bytearray`, a bounded queue and an in-memory WAV; `AmbientSegment.__repr__` and `.to_payload()` carry counters only | `test_un_segment_ne_montre_jamais_son_pcm`, `test_aucune_ligne_de_journal_ne_porte_d_audio_brut`. Mutation M24 caught |
| **No transcript text in any trace line** | every journal line carries ids, counts, durations and codes, clipped at 64 chars | `test_aucune_ligne_de_journal_ne_porte_la_parole` (plants a phrase, drives the lane, searches every line - **and asserts the normal path is journalled**, so an empty journal cannot pass), `test_le_chemin_normal_est_journalise_autant_que_les_refus`. Mutation M15 caught |
| **Cheap analysis first, no heavy brain per utterance** | `analyse_ambient_text` is pure string shape tests: no model, no network, no agent. The lane imports nothing that could delegate | `test_l_analyse_bon_marche_reste_bon_marche` (measured, asserts under 2 ms per utterance) plus the import-graph guard |
| **Exactly one microphone owner** | the lane subscribes, it does not open | `test_la_lane_ambiante_n_ouvre_aucun_micro` (`open_input_stream_count() == 1`, device opens == 1) |
| **Filler suppression** | `is_low_value_filler`; the speech still reaches the tail (it *is* speech), nothing is enriched | `test_le_remplissage_est_supprime_et_compte`. Mutation M19 caught |

## 5. Test quality

75 tests. No test asserts on source text **except** the two import-graph guards, whose
docstrings say why the rule does not apply: they assert on the *absence* of an import,
which no behavioural test can prove - a behavioural test shows "this scenario
authorized nothing", never "no scenario can". They assert on module names via `ast`,
the same technique as `test_v2_architecture.py` and Slice 04's three structural guards,
not on prose.

**Both guards were probed**, the Slice 01 / 05 technique:

- `from jarvis.domain.v2 import BrainTurnInput` dropped into `ambient_lane.py` made
  `test_la_lane_ambiante_n_importe_aucune_voie_d_autorisation` fail by name;
- `import sqlite3` plus `from jarvis.ports.transcription import TranscriptionBackend`
  dropped into `ambient_observation.py` made the domain-purity guard flag the
  `jarvis.ports` import but **not** `sqlite3`, because I had only checked
  `jarvis.`-prefixed names. The guard was widened to a stdlib / IO forbidden set
  (`sqlite3`, `os`, `io`, `pathlib`, `socket`, `httpx`, `aiohttp`, `asyncio`, `numpy`)
  and re-probed: it then failed. Both probes removed; a grep for the probe marker
  returns nothing in the committed tree.

Header sentences of the form "X can never happen" each have their test. "A buffer can
never grow without bound" gives `test_un_orateur_qui_ne_respire_pas_est_coupe_d_office`
and `test_le_segmenteur_ne_retient_jamais_plus_que_sa_borne`. "A disposition can never
be swallowed" gives `test_toutes_les_dispositions_du_magasin_ont_une_politique`. "A
stopped lane cannot be restarted" gives `test_une_lane_arretee_ne_se_relance_pas`. "The
lane gives back what it took" gives `test_la_lane_rend_son_abonnement_a_l_arret`.
"Without speech nothing would fire the age budgets" gives
`test_le_silence_declenche_un_balayage_d_age`.

## 6. Mutation testing: 26 runs, 2 survivors, both real test defects

Driven by a script that applies one mutation, runs the whole suite in the foreground,
and restores the file. **The first attempt reported 24/24 caught and was wrong**: I had
passed `--timeout=120` to a pytest without `pytest-timeout`, so every run exited 4
before collecting a single test. Re-run without it. Worth writing down, because
"everything caught" is exactly the answer a broken harness gives.

| # | Mutation | Verdict |
| --- | --- | --- |
| M1 | analysis before the tail (D06 inverted) | caught (4 failed) |
| M2 | subscribe at 16 kHz (the anti-aliasing trap) | caught (26 failed) |
| M3 | subscribe inline instead of queued | caught (33 failed) |
| M4 | segment queue unbounded | caught |
| M5 | segment drop not counted | caught |
| **M6** | **`_account` always returns "applied" (a refusal swallowed)** | **SURVIVED** |
| M7 | a lost disposition not journalled | caught (6 failed) |
| M8 | cancellation ignored when the transcript returns | caught |
| M9 | segment age ignored | caught |
| M10 | a revision takes a fresh rank | caught |
| M11 | an imperative becomes a checkable claim | caught (3 failed) |
| M12 | `AmbientTrigger.authorizes_actions = True` | caught (8 failed) |
| M13 | never degrade | caught |
| **M14** | **`_recover` does not reset the consecutive-failure counter** | **SURVIVED** |
| M15 | transcript text into the trace | caught |
| M16 | no forced cut | caught (3 failed) |
| M17 | no minimum utterance | caught |
| M18 | no idle prune | caught |
| M19 | nothing is filler | caught (4 failed) |
| M20 | subscription not released on stop | caught |
| M21 | consumer failure not counted | caught |
| M22 | fabricated provenance rank | caught |
| M23 | provider text not clipped | caught |
| M24 | PCM into the journallable payload | caught |

Both survivors were fixed by new tests and **re-run: caught**. Those are runs 25 and 26.

### M6 - a swallowed refusal, and what it would have cost

`_account` returning `True` regardless means a tail append refused for `CAPACITY`,
`REJECTED` or `STALE` still feeds the analysis queue. The working set would then be
enriched from speech that is **not in the tail**, with a provenance citing a rank that
does not exist - which is exactly what makes `enrichment_lag_entries`, the D06 measure,
meaningless. The code was right; nothing asserted it.
`test_une_parole_refusee_par_le_fil_n_enrichit_rien` now drives four dispositions and
asserts the store received no `apply()`.

### M14 - "consecutive" that was not consecutive

`_recover` not resetting `_consecutive_failures` means the counter measures "since the
beginning" rather than "in a row", so one hiccup an hour would eventually declare the
lane dead. The old recovery test only looked at the flag and the line, both of which
still behave under the mutation. The replacement test scripts 3 failures, 1 success, 1
isolated failure, and asserts the journal carries **exactly one**
`ambient_lane_degraded`.

### One real defect the tests found before the mutations did

`test_le_travail_ambiant_en_attente_s_annule` failed on its first run: a segment already
dequeued and in flight inside `transcribe()` still landed in the tail after
`discard_pending()`, because the generation was only checked *before* the provider call.
Speculation that survives its own cancellation is not sacrificial (D08). Fixed by
re-checking the generation on return (`ambient_segment_stale_cancelled`), and mutation
M8 now guards it.

## 7. Failure paths

`docs/presentation-ambient-lane.md` section 8 is the table. Every row has a stable code,
a counter, and a journal line at the right level; the expected path is journalled at
`info` too, so an empty trace cannot mean both "fine" and "deaf". The one deliberate
silence is the journal's own failure, argued in place: a broken journal must not take
down the lane it observes, and there is no second channel to fall back to
(`test_un_journal_en_panne_n_arrete_pas_la_lane`).

## 8. Validation

All foreground, narrow file lists (the host runs under 2 GB free RAM).

    .venv/Scripts/python.exe -m pytest FILES -q -p no:cacheprovider

| Files | Result |
| --- | --- |
| `tests/unit/test_ambient_ingestion_lane.py` | **75 passed** |
| `test_presentation_working_set.py test_presentation_audio_capture.py test_audio_capture.py` | **215 passed** |
| `test_v2_domain.py test_voice_turn_admission.py test_v2_architecture.py test_interaction_mode_control_plane.py` | **168 passed** |
| `test_back_brain_tasks.py test_voice_admission_protocol.py test_voice_conversation_state.py test_interaction_mode_contract.py` | **191 passed** |
| `test_back_brain_tasks.py` alone | **34 passed** |
| `test_realtime_audio_lifecycle.py test_conversation_transcript.py test_voice_duplex.py test_owner_input_gate.py` | **223 passed** |
| `test_realtime_frontend_pipeline.py test_v2_voice_activity.py test_voice_event_codec.py test_documented_routes.py` | **57 passed** |
| `test_control_center_quality.py test_app.py test_v2_persistence.py` (after the doc edits) | **95 passed** |

**1024 passed, zero failures, zero new failures.** The blast radius was measured rather
than guessed: `jarvis/audio/capture.py` is the only pre-existing module touched, and a
grep gives its importers as `app.py`, `factory.py`, `input_ownership.py` and the two
audio suites, all re-run.

## 9. Where SLICE.md, the handoff and the live repository disagreed

Stated, not silently resolved.

1. **SLICE.md does not reference `docs/presentation-audio-capture.md`**, which is the
   binding contract for the audio side - the dispatch brief said so explicitly and
   Slice 05's LOG entry predicted the omission. I followed the contract page.
2. **`test_back_brain_tasks.py` has no failure on this machine today.** The dispatch
   brief and `READINESS.md` section 4 list one pre-existing failure there. Run alone it
   is **34 passed**; run with three neighbours, 191 passed. I touched neither that file
   nor anything it imports. Reporting the discrepancy rather than claiming a fix: the
   baseline may have been measured in a different file combination, or the failure may
   be order-dependent.
3. **`jarvis core` and `jarvis voice` are two processes** (`app.py`, the `core` and
   `voice` subcommands). Slice 04 put the working-set store on `JarvisCoreApplication`;
   the hub and this lane live in Voice. SLICE.md's "working-set service" under *Files
   Likely Touched* reads as though they were co-located. I did not add a protocol route
   or a forwarder - that is a cross-process surface with its own latency budget, and it
   would have contradicted "append to the tail **promptly**" (the existing
   `CoreBatchForwarder` batches on a flush interval). Instead the lane takes a
   structural `PresentationObservationSink` satisfied by the store as it stands, so an
   in-process composition needs no adapter and a cross-process one needs only a relay.
   **The rollout slice must decide which**, and that decision is now a one-line
   substitution rather than a redesign.
4. **No composition root passes a lane**, the same stance and the same reason as
   Slice 05: wiring it would open the room microphone in production, and the operator's
   live Voice process holds that device. This is not an omission, it is the rollout
   slice's job - but it does mean **Slice 11 must wire the lane as well as the
   session**, and `HV-PRES-AUDIO-01` should grow an ambient half.
5. **The repository already writes transcript text into a trace line.**
   `jarvis/runtime/realtime_audio.py` emits `voice.transcript_dropped` with `text[:300]`
   as its message. That predates this slice, is on the Realtime path, and is not changed
   here. My "no transcript text in any trace line" test is therefore scoped to the
   ambient lane's journal, and section 9 of the contract page says so out loud rather
   than letting a reader infer a repository-wide guarantee that does not exist.
   **Flagged as a candidate Issue for agent 0**, not fixed inside this slice.
6. **`scipy` / `soxr` / `webrtcvad` are neither installed nor declared**; only `numpy`
   is, and only in the `voice` / `speaker` extras. That is what made "subscribe at the
   native rate" the right branch rather than merely the cheap one: a hand-rolled
   anti-aliased downsampler in pure Python would cost roughly 0.3 s of loop-blocking CPU
   per second of audio, which would have broken the very independence claim this slice
   has to prove.

## 10. Honest limits

- **The heuristics are heuristics.** French shape tests on a bounded string: a
  determiner-then-noun topic rule, a digit-or-superlative claim rule, a noun list for
  references, a filler set. They will mislabel. The cost of a false positive is one
  entry in a bounded, self-evicting collection; the cost of the alternative - a model
  call per utterance - is exactly what D08 forbids on the ambient path. Where the bound
  matters, it is tested (`test_l_analyse_reste_bornee_quoi_qu_on_lui_donne`).
- **A segment carries its trailing hangover silence** (up to 700 ms). Transcribing it
  costs nothing measurable and it preserves natural sentence-final context; trimming it
  would be a second boundary decision with its own failure mode. Noted rather than
  optimised.
- **No runtime validation.** Nothing in a running JARVIS reaches this code: there is no
  composition-root wiring, and exercising it for real needs both the room microphone
  (held by the operator's live Voice process) and a real transcription credential.
  Everything here is proven against the real hub, the real store, the real
  `PresentationAudioSession` and a fake device plus a fake provider. That is a faithful
  stand-in and it is **not** a running JARVIS - the same sentence Slice 05 had to write,
  and the same conclusion: this belongs to Slice 11's end-to-end validation.
- **`AmbientTranscriber` is a documentation Protocol.** It restates
  `TranscriptionBackend` in the lane's own module so the intent is readable at the call
  site; it is structurally identical and the lane would accept the port directly. If a
  reviewer prefers the port imported instead, that is a one-line change - I kept the
  local Protocol because importing `jarvis.ports.transcription` would pull
  `jarvis.domain.results` in for a type that never appears in a signature, while the
  lane already imports `AudioClip` from `jarvis.domain.messages`.

## 11. Handoff to the next slices

- **Slice 08** subscribes `on_trigger`. It receives only `AmbientTrigger`, whose
  `authorizes_actions` is `False` and whose `kind` is one of four investigation
  natures. A trigger cites the utterance it came from, so the working-set record and
  the tail entry can both be found from it.
- **Slice 09** should read `AttentionCategory` / `AttentionSeverity` from
  `presentation_working_set` (Slice 04's instruction) and may consume
  `AmbientTriggerKind.CHECKABLE_CLAIM`. This slice deliberately raises **no** attention
  item: a lead is not a warning.
- **Slice 10** reads the snapshot. `enrichment_lag_entries` is now a real measurement
  because the lane reads back the rank the store assigned; a consumer can gate a
  deictic on it.
- **Slice 11** wires both `PresentationAudioSession` and `AmbientIngestionLane`, and
  must decide the in-process / cross-process question in section 9 item 3.

---

# Rework — commit `S6: reprise`

Four blocking defects and fifteen smaller items, from two QA passes. Everything
below is in the rework commit; §1-§11 above describe the first round and are
left standing except where a section says otherwise.

## R1. The four blockers

### B1 — a dangling `_pending_revision` wrote stale speech with a fresh timestamp

A forced cut *promises* a continuation. The promise was cleared only by a
subsequent **successful** `_observe` or by `discard_pending()`, so every failure
between the cut and the continuation left it set indefinitely: transcription
raising, timing out, returning empty, a generation- or age-stale refusal, a
`drop_oldest`, and a continuation the segmenter drops under `min_frames`. The
next successful transcript — a minute or an hour later — was joined onto the
twelve-second-old text under the **old** utterance id, with `revision + 1` and a
`spoken_at` computed from the *new* segment. Stale speech wearing a current
timestamp, in the one field a deictic resolves against, with no counter, no code
and no line. Every other piece of cross-call state in the module was bounded;
this one was not.

Fixed with a typed `_PendingRevision` carrying `generation` and `stamped_at`:

- validated **before every use** (`_expire_pending_revision`), so no failure path
  needs to be enumerated to be covered;
- swept on the idle tick;
- abandoned explicitly on the paths we can name — transcription failure, timeout,
  empty transcript, cancellation, stale generation, stale age, backpressure,
  worker crash, tail refusal, bound reached, deafness, `discard_pending`;
- **armed only after the store accepted** the text it promises to extend. It was
  armed before the store call, so a refused text could promise a continuation;
- counted (`revisions_abandoned`) and said (`ambient_revision_abandoned`) with its
  reason, and `stats()["pending_revision"]` exposes whether one is open.

Tests: `test_une_suite_qui_n_arrive_jamais_ne_recolle_pas_de_la_vieille_parole`
(parametrized over a failing and an empty continuation),
`test_une_promesse_de_revision_perimee_n_est_jamais_honoree`,
`test_un_refus_du_fil_annule_la_promesse_qu_une_coupe_avait_posee`,
`test_la_contre_pression_casse_la_continuite_et_le_dit`. Mutations M25-M28.

### B2 — the transcription worker was the only one with no exception guard

`_capture_worker` and `_analysis_worker` each had one. Anything raising inside
`_transcribe_and_observe` **outside its own narrow try** — the WAV build, the
clock, `sink.observe()`, the `AmbientUtterance` construction, the rank read-back
— killed the single transcription task permanently, while `stats()` still said
`started=True, degraded=False` and nothing was journalled, because a task's
exception is not retrieved until `stop()` (which swallowed it).

"A conforming store never raises" was a can-never-happen sentence with no test
behind it, and `sink` is a Protocol over an arbitrary object that this slice's own
doc says Slice 11 may back with a cross-process relay. A relay will raise.

The worker now has the same guard as its siblings: counted (`worker_crashes`),
said in the failure's own words through `_note_failure`, pending revision
abandoned, **loop restarts**. Test:
`test_l_ouvrier_de_transcription_survit_a_un_magasin_qui_leve` drives a sink that
raises twice and then answers, and asserts the third utterance is filed. Mutation
M29.

### B3 — the hub's number without the hub's window

The code and the doc both claimed "the hub's value and the hub's reason". The
hub's mechanism is `MAX_CONSECUTIVE_SINK_FAILURES = 3` **plus**
`SINK_FAILURE_WINDOW_S = 2.0`, and `capture_hub.py` names the exact failure this
slice had, at the line where it resets its own counter: *« la rafale précédente
est oubliée plutôt que cumulée, sinon trois accrocs espacés d'une minute
finiraient par détacher l'abonné »*. `_recover()` reset only on success, never on
a lull, so three transcription failures spread across a quiet afternoon declared
the lane degraded.

This is Slice 05's finding recurring, and this time the correct pattern was in the
module cited as the source. Added `TRANSCRIPTION_FAILURE_WINDOW_S = 120.0`,
injectable for tests, with the reason for 120 rather than the hub's 2 stated in
place (an inline subscriber gets a block every 50 ms; an ambient segment arrives
every few seconds at best). Tests:
`test_trois_accrocs_espaces_ne_degradent_pas_la_lane` and — the other half, so the
window cannot silently disarm the guard —
`test_une_rafale_serree_degrade_toujours_la_lane`. Mutations M30, M31.

### B4 — both import guards were denylists, and QA walked through both

Confirmed exactly as reported. `from jarvis.core.tools import ToolRegistry` and
`from jarvis.core.executors import *` dropped into `ambient_lane.py` left 75/75
green; `import subprocess` and `import urllib.request` in the domain module did
the same. A nine-name forbidden list is a guess about which names matter, on the
task's most important constraint.

Replaced with **transitive-closure allowlists**, the property QA measured:
`test_la_lane_ambiante_ne_charge_que_des_modules_declares` imports the lane in a
fresh interpreter and asserts the set of loaded `jarvis` modules equals a declared
set of twenty; `test_le_domaine_ambiant_ne_charge_que_des_modules_declares` does
the same for the domain (five). A third,
`test_le_domaine_ambiant_ne_touche_ni_io_ni_reseau_ni_sous_processus`, allowlists
the standard-library imports the domain may have. The by-name test is kept
alongside, deliberately redundant: when it fails, its *name* says what broke,
where a set difference makes you read the list.

**Probed.** `from jarvis.core.tools import ToolRegistry` in the lane now fails by
name, and the failure message enumerates the six modules it dragged in
(`jarvis.core`, `jarvis.core.tools`, `jarvis.domain.actions`,
`jarvis.domain.tools`, `jarvis.security`, `jarvis.security.policy`). `import
subprocess` + `import urllib.request` in the domain fails the stdlib guard.
Probes removed. Mutation M41 widens the declared closure by two names and is
caught.

## R2. The fifteen

1. **`prune()` now accounts its disposition** like `observe` and `apply`
   (`prune_dispositions`, journalled through the same `_account`). The test
   fixture was itself part of the gap — `ScriptedSink.prune` returned a hardcoded
   `IGNORED` — so it now answers the scripted disposition.
   `test_le_balayage_de_repos_compte_et_dit_sa_disposition`. Mutation M32.
2. **The D06 test is replaced.** The old one asserted call order, which a true
   inversion passes, because the analysis runs in another task. Replaced by
   `test_l_analyse_ne_peut_pas_preceder_le_fil_parce_qu_elle_en_depend`, which
   measures the **data dependency**: every working-set record's provenance cites
   exactly the rank the store assigned to its utterance, and the tail already held
   the utterance at the first `apply()`. Mutation M40 decorrelates the rank and is
   caught. The doc's §5 now leads with the data-dependency argument, which — as
   the review said — is the better one.
3. **The D04 precondition has teeth**: the queue must be **at its bound** with at
   least three segments already dropped, not merely non-empty.
4. **`_tail_sequence` no longer fabricates rank 1 silently.** The not-found
   fall-through counts (`sequence_not_found`) and says
   `ambient_sequence_not_found` at `error`, with the reason written in place: a
   lagging relay is exactly that shape, and an invented 1 would make an up-to-date
   working set report maximal staleness. `test_un_rang_introuvable_est_dite...`,
   mutation M34.
5. **The capture worker's clean exit is a state now.** `blocks()` returning
   normally (hub detached, device lost) sets `deaf` / `deaf_reason` and says
   `ambient_capture_ended` at `error`; the exception path sets the same state.
   Deafness and a quiet room no longer leave identical numbers.
   `test_une_lane_devenue_sourde_le_dit_au_lieu_de_ressembler_au_silence`,
   mutation M33.
6. **`flush()`'s docstring named a caller that does not exist.** Corrected to say
   what is true: the lane does not call it, because `stop()` is terminal and
   cancels the transcription worker, so a segment produced there has no path to a
   provider. The speech held at that moment is sacrificial (D08) but no longer
   silent — `discard_pending()` counts it as `speech_dropped_at_stop_ms`.
   `test_la_parole_jetee_a_l_arret_est_comptee`, mutation M35.
7. **The failure table is exhaustive**: eleven rows added, including
   `ambient_capture_failed` / `ambient_capture_ended` (what an operator diagnosing
   "Presentation stopped hearing the room" actually looks for),
   `ambient_analysis_failed`, `ambient_prune_failed`, `ambient_unsubscribe_failed`,
   `ambient_sequence_not_found`, `ambient_segment_stale_generation`,
   `ambient_transcription_worker_failed`, `ambient_revision_abandoned`.
8. **Unreachable public surface deleted**: `AmbientUtterance.to_payload` /
   `.to_journal` / `.empty`, `AmbientTrigger.to_payload`,
   `AmbientAnalysis.worth_enriching`. `AmbientAnalysis.triggers` is now a
   **derived property**, so the `_add` closure, the stored field and its
   validation row are gone and the same sentence can no longer live twice in one
   object (`test_les_declencheurs_sont_derives_et_ne_peuvent_pas_diverger`,
   mutation M39). `AmbientLaneCounters.to_payload` is `asdict(self)` instead of
   twenty hand-copied names, with a test asserting the payload keys equal the
   declared fields — a counter added and not copied would otherwise be invisible.
9. **The port is reused, not described.** `jarvis/ports/transcription.py` is
   imported and `AmbientTranscriber` is now an alias of `TranscriptionBackend`, so
   the constructor annotation is the real contract. It costs exactly three modules
   in the closure (`jarvis.ports`, `jarvis.ports.transcription`,
   `jarvis.domain.results`) and none of them leads to a tool or a brain.
   **§2 of this report was wrong and is corrected**: before the rework the port
   still had zero importers, and §10's "documentation Protocol" was the accurate
   half of a contradiction. `test_la_lane_annote_son_transcripteur_avec_le_port_du_depot`,
   mutation M36.
10. **O1 is in the doc** (§7), where Slice 11 will read it: the sink Protocol is
    synchronous and `_analyse` calls `apply()` up to fourteen times with no await,
    so a cross-process relay behind it is blocking IO on the Voice event loop —
    the loop that carries the explicit-address lane. The cross-process branch is
    therefore **not** a one-line substitution; it needs an async sink or a
    non-blocking hand-off, and choosing it without choosing that is a D04
    violation.
11. **`looks_imperative` widened**, and its limit stated in doc §6. It tested only
    the first word of each sentence, sentences split on `.!?…`; unpunctuated room
    transcripts are one sentence, so *"et donc tu sais ouvre le fichier"* scored
    `False`. It now looks for an action stem anywhere, minus a subject in front
    ("il **ouvre** la séance") or a determiner ("la **lance** du chevalier").
    `test_l_imperatif_se_reconnait_sans_ponctuation` (5 cases), mutation M37. D03
    never depended on it; its *observability* did, which is why the caveat is in
    the contract page and not only here.
12. **Elided determiners**: `"l'"` could never match because `_WORD` keeps the
    apostrophe inside the token, so `l'écart`, `l'objectif`, `l'équipe` were
    invisible to topic extraction — a large hole in French. `_tokens()` now undoes
    the elision and `"l"` is an ordinary determiner.
    `test_un_determinant_elide_donne_quand_meme_un_sujet`, mutation M38.
13. **The confidences and `_references` are declared as caveats** in a new doc §11
    written for Slice 08: 0.6 / 0.5 / 0.5 / 0.3 are *posed, not calibrated* — a
    rank, never a probability — and `_references` yields a whole sentence for any
    of nineteen nouns, which notices a citation without extracting it.
14. **`segments = 3` is re-argued in the right unit**: a **memory** bound
    (3 × 576 KB), with `MAX_SEGMENT_AGE_S` named as the staleness authority
    because it says it in seconds and applies it on every take. The "12 s each →
    ~36 s" framing was a worst case for an invariant already enforced elsewhere,
    and the two numbers disagreed.
15. **The three small ones**: the idle sweep's non-execution during continuous
    speech is documented in both the code and doc §11; the 3.2 s capture budget's
    rationale now says "RMS **plus `SpeechGate`'s percentile over a 250-value
    window**, two orders of magnitude under a transcription" instead of "only
    energy arithmetic"; and
    `test_une_analyse_ordinaire_contenant_un_chevron_ne_fait_pas_tomber_la_lane`
    now drives the whole lane, as its name always claimed, and asserts the
    dispositions rather than restating its own input.

**On the analysis queue**: the doc no longer calls 8 a burst absorber. It says
plainly that it absorbs nothing today — the analysis is synchronous, behind a
single transcription worker, and the test proving `analysis_dropped_queue` has to
cancel the worker to fill it — and that it exists because SLICE.md contracts the
shape and because it is what guarantees the analysis can never push back on the
tail *the day it stops being cheap*.

## R3. What held, restated once

Not re-justified here, because QA verified it independently and more strongly than
the first report argued: G7/D03 (six hostile texts end to end, and the import
closure that makes a mutation tool unreachable by construction), the anti-aliasing
branch (verified by bytes), queued-not-inline, failure isolation, trace hygiene,
and the rejection of the Realtime stream. The one correction in the slice's favour
is folded in as item 2 above: D06 is a **data dependency**, not line order.

## R4. Rework mutations: 18 runs, 1 survivor, fixed

| # | Mutation | Verdict |
| --- | --- | --- |
| M25 | pending revision with no deadline | caught |
| **M26** | **promise armed before the tail accepted the text** | **SURVIVED** |
| M27 | a transcription failure keeps the promise | caught |
| M28 | backpressure keeps the promise | caught |
| M29 | transcription worker with no guard | caught |
| M30 | threshold without window (B3) | caught |
| M31 | window without threshold | caught (4 failed) |
| M32 | prune disposition not accounted | caught (2 failed) |
| M33 | silent deafness | caught |
| M34 | rank invented in silence | caught |
| M35 | speech dropped at stop not counted | caught |
| M36 | port re-described instead of imported | caught |
| M37 | imperative only at sentence head | caught (2 failed) |
| M38 | elision not undone | caught (2 failed) |
| M39 | triggers unbounded | caught |
| M40 | provenance rank decorrelated from the tail | caught (2 failed) |
| M41 | import closure quietly widened by two names | caught |

**M26** is worth the paragraph. Removing `_abandon_pending_revision("tail_refused")`
changed nothing, because my test refused *every* observe — so no promise was ever
armed and the abandon was a no-op. The bug is only visible when the refusal lands
**in the middle** of a cut phrase: cut succeeds, continuation is refused, and the
speech after it must not be glued across the hole. The test now scripts exactly
that (`RefuseTheSecond`) and drives a third utterance to prove it opens fresh.
Re-run: caught. That is the 19th run, and it is the same failure mode as the first
round's M6 — a test that exercises a guard's *code* without ever reaching the
*state* the guard exists for.

## R5. Validation after the rework

Foreground, narrow lists, `-q -p no:cacheprovider`.

| Files | Result |
| --- | --- |
| `test_ambient_ingestion_lane.py` | **100 passed** (was 75) |
| `test_presentation_working_set.py test_presentation_audio_capture.py test_audio_capture.py` | **215 passed** |
| `test_v2_domain.py test_voice_turn_admission.py test_v2_architecture.py test_interaction_mode_control_plane.py` | **168 passed** |
| `test_back_brain_tasks.py test_voice_admission_protocol.py test_voice_conversation_state.py test_interaction_mode_contract.py` | **191 passed** |
| `test_realtime_audio_lifecycle.py test_conversation_transcript.py test_voice_duplex.py test_owner_input_gate.py test_v2_voice_activity.py` | **234 passed** |
| `test_control_center_quality.py test_app.py test_documented_routes.py test_realtime_frontend_pipeline.py` | **102 passed** |

**1010 passed, zero failures, zero new failures.** The two closure tests each
spawn a fresh interpreter, which is why the new suite went from ~3 s to ~5 s.
