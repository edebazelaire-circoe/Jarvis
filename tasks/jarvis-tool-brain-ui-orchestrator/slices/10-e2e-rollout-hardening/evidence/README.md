# Slice 10: evidence index

Everything here was produced by the commands in `docs/tool-brain-contracts.md` section 18. Home paths, the OS user name and
the repo path are redacted; the sweep `tests/unit/test_tool_brain_evidence_privacy.py` re-checks the whole directory (targets
derived at run time). The Claude CLI `init` events are not recorded by the harness at all (the stream is consumed inside
`ClaudeLocalAgent`); the sweep forbids their shape.

| Path | What |
|---|---|
| `replay/scripted-report.json` | deterministic replay, 12 scenarios, scripted decider, fake clock |
| `live-model/final-run-*` | the real `ModelToolBrainDecider` (tool-less Claude CLI, `haiku`) on the same scenarios: decisions, queue ends, model calls (answers, sizes, tokens, cost; prompts reduced to a size breakdown) |
| `live-model/browser-display-rerun-*` | the one scenario re-run after the last fix (see trace-analysis F5) |
| `live-model/sample-prompt-final.txt` | one complete narrowed prompt as the model received it |
| `performance/` | local stage latencies, model latency/size/cost, per-iteration table, prompt size before/after |
| `real-session/` | isolated Core, real HTTP, real arbiter, stub and real decider, recorded conversation events, headless Chrome screenshots of the timeline lane |
| `trace-analysis.md` | `agent-trace-analysis` findings (severity, evidence, what was fixed, what stays open) |

## 1. Deterministic replay (CI layer)

`.venv/Scripts/python.exe -m tests.replay.tool_brain_replay` -> 12 scenarios, 21 proposed actions, 10 executed, 3 rejected
(fabricated id, unknown tool, `javascript:` URL), **0 invariant violations, 0 expectation mismatches**. The eight traces of
`docs/04-testing-and-quality.md` are all there, plus outage, no-decider, malformed output, churn and the rule baseline.

## 2. Real model (live) results

Final configuration, 6 scenarios (5 in `final-run-*`, browser-display re-run in `browser-display-rerun-*`): **0 invariant
violations, 0 expectation mismatches, 11 model calls for 10 decisions, $0.087**. The model honoured valid intents, tied
speech-bound reveals to speech or intent triggers, dropped everything after an interruption, replanned after an archived
object, switched the Board through the canonical seam and opened a URL as presentation.

**Budget honesty.** The brief capped the work at about 12 model calls and 2 dollars. The final evidence run uses 10 + 1 calls.
Reaching it took six exploratory runs (each found something real, see trace-analysis): 66 `claude` calls in the replay runs
(`performance/model-calls-per-run.json`) plus about 6 in the real-session runs, **about 72 calls and about $0.70 in total**.
The call cap was exceeded (six times over), the dollar cap was not.

## 3. Performance baseline (this machine, Windows 11, `claude` 2.1.292, `haiku`)

| Stage | p50 | p95 | Source |
|---|---|---|---|
| trigger -> decision recorded and action queued (instant decider) | 0.9 ms | 1.3 ms | bench, 12 objects |
| queued -> executed by the owner (SQLite commit included) | 1.8 ms | 2.0 ms | bench |
| invalidation -> replan decision starts | 1.0 ms | 1.2 ms | bench |
| perception build / manifest build + scope / `validate_call` | 0.13 / 0.25 / 0.03 ms | 0.23 / 0.42 / 0.05 ms | bench |
| **model decision call** (1 call) | **3.4 s** | **4.3 s** | 11 calls, final configuration (`model-performance-final.json`) |
| CLI-reported duration inside that call | 2.2 s | 3.3 s | same |
| decision prompt | 16.3 to 18.3 KB (was 32.3 to 34.1 KB) | | `prompt-size-breakdown.json` |
| manifest | 12.7 KB, 7 tools (was 29.4 KB, 22 tools) | | scope_tools (section 18.3) |
| cost per call | $0.0077 (was $0.0131) | | cache creation 5.6k tokens (was 10.1k), cache read always 0, thinking 0 |

The Tool Brain's own overhead is about 4 ms end to end; the user-visible latency is the model call, about 3.4 s p50. Documented
budget (contract 18.4): local pipeline p95 <= 25 ms; model decision p95 <= 6 s (hard timeout 30 s); a `now` action therefore
reaches the screen about 3.5 s p50, 4.5 s p95 after its intent; speech-bound actions are planned ahead and land on their chunk.

## 4. Real session (isolated Core)

`scripts/tool_brain_live_session.py`: temp data and runtime roots, ephemeral loopback port (17653/17654 refused), real
`JarvisCoreApplication` + HTTP server + `LocalCoreClient` + `build_tool_brain` + ownership arbiter. Stub decider unless stated.

| Check | Result |
|---|---|
| `shadow`: decision made, `would_apply`, nothing executed, scene unchanged, owner stays `jarvis_direct` | pass (`session-stub.json`) |
| `active`: reversible op (`scene_update_object` visible) executed through `SceneService.apply_if`, owner becomes `tool_brain` | pass, stub and **real model** (`session-model.json`, decision 3.1 s) |
| decider killed (errors) -> 2 failures -> fallback `jarvis_direct` reason `decider_failing`, queue empty, scene untouched | pass (about 6 s after the kill: 5 s backoff between the failures) |
| decider gone (no model) -> fallback `decider_unavailable` at once, scene untouched | pass |
| timeline in headless Chrome over CDP with the real recorded events: five lanes, Tool Brain lane with dots, one completed bar, ownership fallback dot, accessible names | pass (`timeline-real-session*.png`); at 1440 px the fifth lane starts at x=1350 and needs a horizontal scroll (polish, trace-analysis F10) |

## 5. Not verified here

- The Human's live Jarvis (voice, mic, speakers, real long answers) was deliberately not touched: perceived synchronization
  is a Human check. Core had no speech projection in these runs (`speech: not_wired`, contract 13.4), so speech-bound
  actions were only exercised by the replay harness, not in a real Core.
- The real Control Center server was not started (the page is rendered with the same fetch stub as the S9 browser test, fed with
  the events a real Core recorded).
- Voice-side `ToolBrainDisplaySink` does not exist yet (deferred S08); its intake is proven by a witness adapter test only.
