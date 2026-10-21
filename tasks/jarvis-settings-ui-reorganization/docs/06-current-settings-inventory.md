# Current Settings Inventory

Source snapshot: `main` at `20292e5c292dc8ab9a012ccf00ecb82b5c7f820e` (audited 2026-10-21).

The base `control_center.html` currently declares seven top-level tabs: Voice, Prompts, Agent / CLI, API Keys, Shortcuts, Memory, and Sub-agents. Other modules inject Wake word, Appearance, and Experimental, producing ten effective top-level destinations.

## 1. Voix

The Voice screen already contains seven internal categories: Architecture, Conversation, Tours & interruptions, Modeles, Audio, Avance, Diagnostic.

Major settings/capabilities include:

- versioned Voice architecture (`simple`, `front_brain`, `duplex`);
- compatibility Voice stack / historical Voice mode;
- conversation, reflex and analysis model selection;
- reasoning effort, speculative deltas, client delegation, brain orchestration, idle timeout;
- conversation mode and speaker verification;
- owner speaker-verifier tuning and profile-path diagnostic;
- OpenAI Realtime model, voice, transcription model/language, noise reduction, echo cancellation, reflex acknowledgement, VAD type/eagerness/threshold/padding/silence;
- Gemini Live model, voice, input/output transcription and VAD sensitivity/padding/silence;
- microphone and speaker selection;
- active/inactivity timeout;
- audio device test;
- Voice model catalogs;
- global `wake_toggle` shortcut currently exposed from Voice;
- read-only diagnostic projections for authorization, verifier/worker, echo cancellation, stack switching, catalog/model adapter status and model availability.

## 2. Mot d'eveil

Injected after Voice by `control_center_wake_word.js`.

Editable settings:

- enable wake word;
- engine/provider: Porcupine or openWakeWord;
- keyword / wake phrase;
- sensitivity;
- cooldown / anti-bounce delay.

Non-setting/operator content mixed into the page:

- saved block/schema state;
- unreadable/foreign-version diagnostics;
- ignored keys;
- restart-Voice notice;
- last detector event from the trace journal;
- refresh/read detector action.

## 3. Prompts

A prompt workbench rather than a normal preference page:

- active programs and layers;
- prompt IDs and source path/symbol;
- channel/operation/application policy;
- editable override layers;
- save/reset override;
- effective composed prompt preview;
- runtime/provider limitations.

## 4. Agent / CLI

Normal-user and technical concerns are mixed:

- primary Agent/CLI selection;
- model selection;
- sub-agent mode (`Auto` / `Duplique`);
- response verbosity;
- politeness/formality;
- CLI command/path and re-probe;
- permission/sandbox mode;
- provider model catalog state;
- sub-agent model catalog;
- advanced routing profiles (`desktop`, `code`, `fast`, `general`), ordered candidates and General fallback.

## 5. API Keys

Credential management:

- saved credentials by provider;
- active binding per provider;
- masked credential hint only, never full value;
- add/delete credential;
- environment fallback discovery.

The surface is structurally coherent but exposes an implementation term (`API Keys`) rather than the user's goal of connecting providers/services.

## 6. Raccourcis

Registered shortcuts include:

- wake/send/interrupt (`F9` default, but edited from Voice today);
- open Settings;
- close window/panel;
- Errors panel;
- Trace panel;
- Agents panel;
- next Settings tab;
- previous Settings tab.

The page intentionally excludes `wake_toggle`, creating a split canonical-home problem.

## 7. Memoire

Sections are already schema-driven:

- Recall: enable, items per turn, timeout;
- Semantic search: enable, embedding provider, private-scope permission;
- Consolidation: manual/auto, confidence threshold, candidates per run;
- Tencent sidecar: enable, URL, service ID, private-scope permission;
- Knowledge: Wiki, codegraph, Skills;
- current memory-leg state and degraded explanations;
- Memory Center entry point;
- per-agent knowledge/loadout summary (read-only here);
- restart-required notices.

## 8. Sous-agents

Newly landed top-level surface from `control_center_subagents_settings.js`:

- role registry listing and visual identity;
- role name, marker, description, mission and relevance;
- capabilities/tools/skills and Work Methods;
- enabled/spawn/mission/offering facts;
- running instances from Agent tasks;
- editable role instructions through canonical prompt overrides;
- reset/re-read with optimistic revision handling;
- Work Method candidates and explicit promotion flow;
- local error/retry/timeout states.

This is a major new reason the old top-level navigation cannot scale. The target IA absorbs normal role/model behavior into `Agents & modeles` and treats Work Method promotion as an advanced operator action unless Slice 00 finds a newer contract.

## 9. Apparence

Injected by `control_center_work.js` and extended by the scene page.

- theme choice: Circuit imprime / Cosmos;
- Cosmos/star-scene display preferences such as star size, halo, breathing halo, gravity, orbit amplitude/speed, links between objects, ephemeral-task display;
- reset appearance preferences;
- browser/localStorage ownership and immediate renderer application.

## 10. Experimental

Created by Bare Hands and shared with scene settings.

Scene test controls include:

- enable/disable scene and brain scene tools;
- effective state/source information;
- brain restart when required.

Bare Hands ordinary settings include:

- target preview;
- aiming assistance;
- gesture sensitivity;
- return-to-sleep timeout;
- on-screen diagnostics;
- offer/enable calibration;
- reset settings.

Bare Hands operator/test content includes:

- MediaPipe asset state;
- calibration profile detail and delete-profile action;
- calibration flow;
- six-exercise benchmark/test;
- diagnostic recording start/stop;
- last Voice command received;
- known limitations/documentation.

The Bare Hands tool itself and lifecycle are intentionally controlled elsewhere (wheel/session interaction), not by Settings. That ownership must remain intact.
