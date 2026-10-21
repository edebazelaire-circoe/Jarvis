# Grill Session

> Reconstructed from the active project conversation on 2026-10-20 and the publication correction on 2026-10-21. The exact full chat export was not available to the task writer; this reconstruction preserves user intent and explicit decisions without inventing new product requirements.

## Initial user request

The user supplied a screenshot of the current Jarvis Settings window and explained that the UI is difficult to read, difficult to understand, badly organized, and visually poor. The user asked for a complete audit of the Settings present on the `main` branch, with the immediate goal of reorganizing them before redesigning the pages.

The user specifically wanted:

- a complete listing of existing Settings capabilities;
- identification of settings that are unnecessary, misplaced, duplicated, or too technical for ordinary Settings;
- grouping of settings that belong together;
- a clear answer to how many distinct Settings menus should exist and what belongs inside each;
- the repository, not memory, to be the source of truth.

## Repository audit summarized in the discussion

At the time of the first audit, the Settings surface exposed nine top-level destinations after dynamic injection. The rebuilt handoff rechecked `main` on 2026-10-21 and found that a new top-level `Sous-agents` destination had landed, bringing the current effective navigation to ten destinations.

The current Settings UI mixes ordinary preferences with architecture switches, diagnostics, read-only runtime state, model catalogs, CLI installation details, prompt workbenches, role/work-method tooling, benchmarks, repair actions, experimental feature gates, and testing tools.

The `Voix` tab itself already contains seven internal categories: Architecture, Conversation, Tours & interruptions, Modeles, Audio, Avance, Diagnostic.

The audit also identified cross-surface inconsistencies, including the global wake/send/interrupt shortcut being persisted in the shortcut registry but edited from Voice rather than from the Shortcuts page.

## Agreed target organization

The proposed reorganization was accepted as the basis for the task:

1. **Voix & audio** - conversation, Voice output, microphone/sound, turn taking and interruption, wake word; advanced VAD/buffer details hidden behind advanced disclosure or the advanced category.
2. **Agents & modeles** - primary agent/model, response behavior, sub-agent mode, sub-agent roles/models/profile selection; low-level CLI installation details moved out.
3. **Memoire & connaissances** - recall, semantic retrieval/embeddings, consolidation, knowledge sources, Memory Center.
4. **Interface & interactions** - theme, constellation display preferences, all keyboard shortcuts, user-facing Bare Hands preferences and calibration.
5. **Connexions** - credentials and provider connection state, replacing the narrow user-facing name `API Keys`.
6. **Avance & diagnostic** - Voice architecture/compatibility, prompt workbench, low-level CLI/runtime settings, diagnostics, scene test gate, Bare Hands benchmark/recording/developer tools.

Additional accepted principles:

- `Mot d'eveil` is no longer a top-level menu; it becomes a Voice section.
- `Prompts` is not an ordinary Settings page; it moves to Advanced.
- `Agent / CLI` is split between user-facing intelligence choices and low-level CLI/runtime configuration.
- `API Keys` becomes `Connexions`.
- `Raccourcis` is folded into Interface & interactions; the F9 wake/send/interrupt shortcut gains one canonical editable home there.
- `Memoire` remains a major category, renamed `Memoire & connaissances`.
- `Apparence` becomes part of Interface & interactions.
- `Experimental` is dismantled as a junk-drawer tab: user-facing Bare Hands preferences move to Interface; diagnostics/test/recording and experimental scene controls move to Advanced.
- The newly landed `Sous-agents` surface is absorbed into `Agents & modeles`; it must not become a seventh top-level category.
- Backend capabilities are preserved even when removed from normal Settings navigation.

## Visual direction already established

The preferred Settings visual language is a dark blurred Jarvis background, more spacious and identifiable category surfaces, no large enclosing Settings frame, a clear close control, and a less cramped composition. This task treats that direction as the target shell language while `/impeccable` remains responsible for frontend refinement.

## Task creation and correction

The user requested `@Create Task` to materialize the implementation handoff. The first attempt created only a partial local/Drive structure and was not visible to the user as a complete Jarvis task. On 2026-10-21 the user explicitly requested that the task be reimplemented. This rebuilt handoff supersedes the incomplete publication attempt while keeping the same project and task identity.
