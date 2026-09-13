# Realtime compatibility facade

Introduced by `jarvis_voice_architectures_handoff` Task05. Owner: existing voice runtime composition.

`app._run_voice_v2` creates `RealtimeFrontendSession` for OpenAI Mini/full. Its sole provider owner is `OpenAIRealtimeFrontend`, which owns `OpenAIRealtimeSession` and its one wire reader. The facade translates canonical events into the existing bridge's internal envelopes, preserving ordered playout fences and existing tool/address/owner authorization. It exposes no raw session. Gemini keeps its existing implementation. Existing `legacy` and `continuous_brain` execution policy is retained; the temporary Simple-shaped frontend configuration does not select the new Simple runtime policy.

`VoiceObservationDispatcher` merges canonical receipt evidence with local playback evidence. Only Core's ledger projects confirmed assistant text into persistent history. The bridge and speech scheduler bypass their old assistant-history writes when `canonical_history` is present.

Task05 reports playback as a conservative lower bound (`PARTIAL`, then `UNKNOWN`) without confirming generated words. Current hardware code has no verified natural drain boundary. Task07 must establish device drain/epoch/interruption/reopen evidence before migration17 and benchmark20. A provider response end, exhausted Python queue or cached latency estimate is insufficient. Naturally generated assistant text therefore remains absent from canonical heard context until that device work establishes confirmation.

Removal criterion: bridge and scheduler consume canonical frontend/observation interfaces directly while retaining owner authorization, user admission, ordering and interruption tests. Remove reverse envelope translation, `canonical_history` and compatibility controls only with replacement consumers and production composition tests. No alternate runtime/provider framework is introduced.
