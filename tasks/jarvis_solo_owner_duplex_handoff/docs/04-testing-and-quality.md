# 04 — Testing and Quality

## Regression gates

Do not accept regressions in the current voice suite. At baseline review, the latest voice-duplex report stated 883 tests passing and 4 skipped; use the repository's current test count at implementation time rather than hardcoding this number as a future target.

Mandatory test categories:

- echo-only playback never becomes owner speech;
- keyboard/transient noise never becomes owner speech;
- non-owner continuous conversation does not duck/cut JARVIS in `solo_owner`;
- owner interruption while non-owner speech is already active is eventually detected;
- owner-only interruption stops local audio before any provider response is required;
- sentence prefix survives verification latency and ring-buffer wrap;
- non-owner speech while JARVIS is silent does not reach brain or refresh useful activity;
- owner uncertain-addressing behavior still routes according to existing Decision 44 semantics;
- provider `speech_started` arriving early/late/never does not break a locally confirmed owner barge-in;
- cancellation/truncation failures degrade without killing Voice;
- AEC/verifier unavailable states are explicit;
- no raw voice embedding or audio bytes enter ordinary diagnostic payloads.

## Speaker verification benchmark metrics

For each engine and scenario capture:

- false acceptance rate for non-owner speakers;
- false rejection rate for owner;
- time-to-owner-confirmation P50/P95;
- CPU utilization;
- steady-state RAM;
- model load time;
- overlap handling (owner + another speaker);
- distance/noise sensitivity;
- effect of AEC on verification score;
- effect of far-field noise reduction on verification score.

Do not compare engines using different preprocessing unless explicitly running an ablation.

## Recommended scenario set

1. Quiet owner, JARVIS silent.
2. Quiet owner interrupts JARVIS.
3. One non-owner speaks continuously while JARVIS speaks.
4. Several non-owners converse while JARVIS speaks.
5. Owner starts speaking during a non-owner sentence.
6. Owner + non-owner overlap for 1–3 seconds.
7. Keyboard/mouse/desk impacts.
8. JARVIS-only loudspeaker echo at multiple volumes.
9. Headset path.
10. Laptop speaker path at multiple distances.

## Work-state tests

- provider tracker event -> normalized Core work state;
- idempotent duplicate observation handling;
- out-of-order progress never rewinds final state;
- process death transitions running subtasks predictably;
- brain context sees same normalized state as UI projection;
- UI cannot mutate authoritative Core work state;
- failure/completion events can trigger policy without forcing speech;
- bounded histories/snapshots prevent unbounded memory growth;
- unknown provider fields do not leak into domain contracts.

## Diagnostics

Add stable event kinds, suggested names:

- `voice.owner.candidate`
- `voice.owner.confirmed`
- `voice.owner.rejected`
- `voice.owner.unavailable`
- `voice.barge_in.owner_confirmed`
- `voice.input.non_owner_dropped`
- `core.work.observed`
- `core.work.updated`
- `core.work.failed`

Event names are provisional; use existing naming conventions if equivalent events already exist.

Never log raw audio, raw speaker embeddings, or unrestricted provider trace payloads in these events.
