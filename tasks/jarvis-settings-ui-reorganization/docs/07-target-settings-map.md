# Target Settings Map

The target has exactly six top-level categories.

## 1. Voix & audio

### Conversation

- conversation mode / Solo Owner policy;
- speaker verification mode;
- inactivity/sleep behavior relevant to Voice conversation;
- simple reflex/acknowledgement behavior that a normal user can understand.

### Voice output & transcription

- active conversational Voice/model selection when user-facing;
- voice/persona voice choice;
- transcription model/language and input/output transcription toggles.

### Microphone & sound

- input device;
- output device;
- noise reduction;
- echo cancellation;
- audio test.

### Turns & interruptions

- automatic/manual end-of-turn;
- user-facing barge-in choice;
- only the minimum VAD controls appropriate to normal users.

### Wake word

- enable;
- engine;
- phrase;
- sensitivity;
- cooldown;
- restart requirement.

Wake detector trace/health details move to Advanced diagnostics.

## 2. Agents & modeles

### Main agent

- active CLI/agent identity;
- main model selection;
- clear availability state.

### Behavior

- verbosity;
- politeness/formality;
- sub-agent mode when user-facing.

### Sub-agents

- role roster and role identity;
- mission/relevance/capabilities summary;
- role instructions when this remains the canonical user-editable behavior surface;
- model/profile selection and availability;
- active role instances as concise context where useful.

Raw CLI command/path/permission and low-level routing lists move to Advanced. Work Method candidate promotion is routed to Advanced unless current contracts say it is ordinary role configuration.

## 3. Memoire & connaissances

### Recall

- enable recall;
- memories per turn;
- recall timeout.

### Semantic retrieval

- semantic search enable;
- embedding provider;
- private-scope permission.

### Consolidation

- manual/auto;
- confidence threshold;
- candidate budget.

### Knowledge sources

- Wiki;
- codegraph;
- Skills;
- Tencent/other external retrieval sources when they are genuinely memory/knowledge sources.

### Memory Center

- clear entry to inspect notes, candidates, knowledge and recall behavior.

Detailed memory-leg diagnostics can deep-link to Advanced diagnostics rather than dominate the ordinary page.

## 4. Interface & interactions

### Theme & visual scene

- Circuit imprime / Cosmos;
- star size, halo, animation, gravity/orbit/link visibility and related renderer preferences.

### Shortcuts

- every registered keyboard shortcut, including wake/send/interrupt;
- one canonical editor per shortcut.

### Bare Hands

- target preview;
- aiming assistance;
- gesture sensitivity;
- sleep timeout;
- calibration enable/launch and calibration profile reset where this is an ordinary interaction preference.

Benchmark, recording and raw diagnostics move to Advanced Labs.

## 5. Connexions

Provider-centric credential management:

- provider/service identity;
- configured/not-configured status;
- active credential binding;
- add/replace/delete credential;
- environment fallback indication;
- short contextual note on which Jarvis capability uses the provider.

Never reveal credential values. Do not invent OAuth-style connection semantics for providers that only support stored API credentials.

## 6. Avance & diagnostic

### Architecture & compatibility

- Voice architecture (`simple`, `front_brain`, `duplex`);
- historical/compatibility stack fields;
- client delegation invariant;
- brain orchestration;
- low-level VAD/buffer/speaker-verifier tuning.

### Prompts & instructions

- prompt workbench;
- effective prompt previews;
- advanced role/work-method instruction tooling when not kept in Agents.

### Runtime & CLI

- CLI command/path;
- permission/sandbox mode;
- re-probe/re-detect;
- advanced routing candidate ordering and fallbacks;
- detailed model/provider catalog source state.

### Diagnostics

- Voice authorization/verifier/worker;
- wake detector journal state;
- echo cancellation state;
- stack/model adapter status;
- detailed memory/service degradation;
- any read-only paths/diagnostic projections.

### Labs & test tools

- scene test gate and brain restart;
- Bare Hands on-screen diagnostic flag if kept operator-only;
- Bare Hands benchmark;
- diagnostic recording/replay;
- Work Method candidate promotion if treated as operator tooling;
- future experimental controls that are not ordinary preferences.

## Current -> target summary

| Current top-level destination | Target |
| --- | --- |
| Voix | Voix & audio + Avance & diagnostic |
| Mot d'eveil | Voix & audio + detector details in Avance |
| Prompts | Avance & diagnostic |
| Agent / CLI | Agents & modeles + Avance & diagnostic |
| API Keys | Connexions |
| Raccourcis | Interface & interactions |
| Memoire | Memoire & connaissances (+ detailed health in Avance) |
| Sous-agents | Agents & modeles (+ operator tooling in Avance) |
| Apparence | Interface & interactions |
| Experimental | Interface & interactions + Avance & diagnostic |
