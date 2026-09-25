# Reconstructed planning / grill session

> Reconstructed from the active 2026-09-25 conversation because the task creator does not have a verbatim transcript export. This file preserves product decisions and corrections without claiming implementation.

## Why the old calibration was challenged

The user reported that the existing calibration was hard to understand as a tester and did not produce a convincing improvement in real use. Concrete complaints included false clicks, missed clicks, sticky/late releases, a desire for very fast pinches, difficulty selecting stars near their edges, lack of clear preselection feedback, pointer/cursor noise during normal hand movement, and context menus remaining open after an empty primary click.

Repository inspection showed that the current calibration already changes primary/secondary pinch thresholds and click-vs-drag tolerance, but several recorded values are diagnostic or not clearly wired into runtime behavior. The current target step also measures click travel more than true aiming accuracy.

## Calibration becomes an evidence-gathering conversation

The user rejected a “measure once, derive fixed threshold, save” mental model. Calibration should gather enough evidence to explain failures and drive bounded experiments.

Example: after a targeting exercise, the user may say “j'ai du mal à viser, je me suis repris plusieurs fois, ça lag”. The system should combine the session telemetry with that statement, generate several plausible causes, test one with a temporary configuration, and use the retest to raise or lower confidence. It must not keep returning to the same hard-coded diagnosis after the experiment disproves it.

The conversation converged on this distinction:

- deterministic code produces measurements, events, invariants, and reproducible benchmark scores;
- heuristics may produce candidate explanations and evidence summaries;
- the LLM calibration agent interprets measurements plus free-form user feedback, compares hypotheses, chooses a bounded next experiment, explains it, and continues the dialogue;
- the LLM never fabricates measurements and does not sit inside the per-frame tracking loop.

## Pinch measurement correction

The current quantile-over-all-frames derivation can bias against short, fast pinches because a rapid click contributes few fully-closed frames. The desired derivation segments each intentional gesture into open baseline, closing, minimum, opening, and new open baseline, computes per-gesture values, then aggregates gestures.

The session must also collect negative examples: normal movement and aiming without clicks. False press/wake events during these windows are valuable calibration evidence.

## User feedback as data

After an exercise, the flow does not automatically advance. The user can accept, retry, or adjust. Voice should allow natural statements such as “le release colle”, “ça saute”, “j'arrive pas à viser”, “le drag part trop vite”, or “là c'est nickel”. UI controls remain as a fallback.

Feedback is not a direct setting assignment. It constrains interpretation of measured evidence.

## Trial profiles

Tuning uses an in-session trial profile. Changes are applied live but remain temporary until explicit acceptance. The user can ask for another adjustment or revert to the previous trial. This is required so calibration can experiment without turning every hypothesis into permanent state.

## Pointing intent and cursor visibility

The user explicitly rejected seeing a large tracked cursor while making ordinary hand movements. Tracking, pointing intent, and active interaction must be separate. In SLEEP, normal movement should render nothing. A dotted wake/progress cursor appears only after a credible pointing/C/pre-pinch posture begins. In ACTIVE, a normal tracked hand that is not currently pointing should likewise not require a permanent pointer.

## Targeting and preselection

The nearest reasonable actionable target should be preselected before the click and highlighted so the user knows what will be selected. This should apply to stars as well as manipulation zones. Assistance distance should itself be calibrated, with ambiguity between nearby targets limiting how strong the assistance can become.

## Calibration versus Test

The user proposed reviving a separate Test surface as a short game-like benchmark. This was accepted as a distinct concept:

- Calibration changes and retests settings.
- Test never changes settings and measures the current profile.

Controlled mini-exercises should cover target acquisition, false positives, nearby targets, drag/drop into a destination, moving targets, release reliability, and chained interactions. Scores compare the configured interaction system, not human worth or skill.

The benchmark can be playful, but open-ended arcade games are deferred because game skill and learning would pollute the calibration metric.

## Repository status discovery

The old Drive handoff `jarvis-bare-hands-ui-calibration-refinement` was found still under `to-do`, but GitHub proves it was implemented and merged on 2026-09-20 as commit `e684a46824a116216a2bee327de068bfcac37464`, with the commit message naming that task explicitly. Searches found no remaining matching Bare Hands/calibration/refinement branches and no matching PR. The task therefore must not be replayed from its historical branch. This successor begins from current `main`.
