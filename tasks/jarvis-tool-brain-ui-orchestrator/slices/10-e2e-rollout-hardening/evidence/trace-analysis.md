# Trace analysis: Tool Brain decision model (Slice 10)

Scope: `ModelToolBrainDecider` on the tool-less Claude CLI (`--tools ""`, `--strict-mcp-config`, no session; the Human's MCP
servers are never loaded), model `haiku` (default), scenarios of `tests/fixtures/tool_brain_replay/`. Trace source: the
recorded request/answer of every call (`performance/`, `live-model/`), the decision log of the runtime and the queue end states.
Method: `agent-trace-analysis` axes (functional correctness, architecture conformance, call quality, error/recovery,
efficiency). Seven iterations; every MAJOR below was fixed with a regression test and re-measured.

## Execution path (one decision)

wake (coalesce, rate limit) -> `read_ui_state` -> perception (0.7 to 1.3 KB) -> manifest (scoped) -> intents -> **one model call**
-> strict JSON codec -> `validate_call` on a fresh read (the model has no handle on any service) -> queue admission -> executor
revalidation at fire time -> owner (`apply_if` / Board seam). The model proposes; four deterministic gates dispose.

## Findings

| # | Severity | Finding (evidence) | Status |
|---|---|---|---|
| F1 | MAJOR | The prompt was 32 to 34 KB per call, 29.4 KB of it manifest (22 tools), about 10k tokens written to cache at $0.0131 per call. Nine of those tools have no adapter (reads, creation): the model proposed one (`scene_get` as an action, run 1) that the queue could only refuse. | **Fixed**: `scope_tools` keeps executable tools with a legal choice (7 tools, 12.7 KB, -57 %), prompt 16 to 18 KB, $0.0077 per call (-41 %). Not a permission: `validate_call` still judges the whole catalog. |
| F2 | MAJOR | Inspection loop: for a hidden object the model asked `get_information_on` on the same id on every round although the answer was already in `inspection_results` (run 2: 8 of 12 calls, scenario 1 never acted). | **Fixed** three ways: prompt rules; `duplicate_read` guard (one final call with 0 reads left); the runtime prefetches the read of every object a valid intent names. Final run: 0 inspection rounds for a reveal. |
| F3 | MAJOR | Timing: intents with `timing: with_speech` were acted on immediately, with no trigger (run 2, long-response: both notes shown at once instead of at their chunk). | **Fixed** in the prompt (intent timing -> `intent` / `speech` / `speech_chunk` trigger). Final run: reveals tied to speech, none executed after the cut. |
| F4 | MAJOR | After an interruption the model re-proposed the dead intent's action with **no trigger** (run 5 scenario 3: 2 actions executed after the cut). The "no obsolete speech-bound action" invariant held for trigger-bound actions only. | **Fixed** mechanically: `intent_is_gone` refuses at admission an action citing an intent whose speech will not be said (`speech_obsolete`); intent rows now carry `status` so the model sees `obsolete` (final run: it says so in its rationale). |
| F5 | MAJOR | An action tied to a `now` intent by an `intent` trigger waited for its expiry when no speech is wired, which is how Core runs today (run 6: browser-display stayed `pending`). The S4 rule says `now` is always due. | **Fixed** in `_speech_verdict`; re-run (run 7): executed. |
| F6 | MINOR (open) | Churn: a second wake for the same, already satisfied intent re-proposes the same reveal (scenario 1: 2 executions for one visible effect; the second is a no-op for the owner). | Open, OPTIMIZATION: skip a proposal whose effect already holds in the fresh state. Idempotent, no UI harm. |
| F7 | FLAGGED | `cache_read_input_tokens` is 0 on every call: each call is a fresh process that writes a 5.6k-token cache nobody reads (5 min TTL). | Inherent to the isolation profile (no shared session); cost stays under 1 cent per decision. |
| F8 | FLAGGED | Latency floor: about 2.2 s of the 3.4 s p50 is the CLI cold start and one round trip. A `now` action cannot appear before about 3 s after its intent. | Documented budget; the speech-bound path hides it when the answer is long enough. |
| F9 | FLAGGED | First intent after an `active` start: the Tool Brain owns the screen only after one completed decision (S8), so an intent that arrives before that is decided but not queued (Jarvis acts). Seen once with the real model (session run 2). | By design (contract 16); documented in the rollout, nothing to fix. |
| F10 | MINOR (open) | Timeline at 1440 px: the Tool Brain lane starts at x=1350 and needs a horizontal scroll (`scroll_extent` 1650 > 1440). | Open polish for the Human; layout is the S9 grid. |

## Validity of returned plans (final run, 11 calls)

11 of 11 answers parsed; 0 `invalid_output`; 0 rejected proposals (invalid id, unknown tool, irreversible tool: the three
attacks are scripted, not elicited, and are all refused). Replies are 290 to 560 bytes (about 150 output tokens), thinking
tokens 0. Rationales cite intent ids and `ref_refusals` correctly (stale scenario: "ref_refusals contains object_archived").

## Unnecessary / redundant calls

Before: 8 of 12 calls were repeated reads (F2). After: 11 calls for 10 decisions; the one extra is the replan after an
invalidation, which is the intended path (invalidation -> immediate replan, 3 consecutive max).

## Error, retry, fallback

Outage and unavailability are covered by the replay (failed -> backoff -> recovery; unavailable) and by the real session (killed
decider -> `decider_failing` after 2 failures; no decider -> `decider_unavailable`; ownership back to Jarvis, queue emptied,
scene untouched, every step on the timeline). No silent catch observed; every failure carried the provider's own words.

## Missing trace evidence

- Prompts are not stored in full (only one sample and a per-key size breakdown): they hold only synthetic scene titles but
  would bloat the repository; the harness can keep them (`model-calls.json`).
- No real voice session: speech progress came from fixtures, not from `SpeechScheduler`.
- One model, one machine, n = 11 final calls: the percentiles are a baseline, not a distribution.

## Suggested next model / agent improvements

1. Skip proposals whose effect already holds (F6) and let the decider see `unchanged` outcomes of past actions.
2. A persistent restricted session per Tool Brain (cache reads, about 1.5 s saved) once a tool-less session mode exists.
3. A smaller manifest per wake class still: `speech`-only wakes need only queue ops and trigger tools.
4. Train or distil a specialist on the recorded decisions (`model-calls.json` of future runs); the port is already swappable.
