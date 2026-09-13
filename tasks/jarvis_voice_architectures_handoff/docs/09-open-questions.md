# Open Questions

1. Default GPT-Live idle timeout: configurable is locked; 60 seconds is the frozen offline comparison value, not a validated live default. Exact value needs provider usage and continuity data.
2. Default architecture remains unresolved after Task20. The safe operational default stays `legacy` until an authorized provider/audio campaign measures quality, latency, availability, usage and cost. Front Brain uses Luna as the initial analysis candidate, not a winner.
3. Partial transcript analysis frequency/budget: benchmark correction rate and cost.
4. Gemini inventory resolved (Task01): no production hard-coded/default model or selected local model. Candidates are discovered from Google's `bidiGenerateContent` capability; the adapter supports only the existing legacy path and lacks semantic output controls. `gemini-live-2.5-flash` occurs in a catalog test fixture, not verified provider availability. Live account/model compatibility still requires discovery at runtime; see `current-code-map.md`.
5. Default Realtime Semantic VAD eagerness: test low/medium with real owner speech.
6. Actual-spoken evidence clarified by accepted Tasks04–07: the canonical OpenAI path uses generated text plus an exact audio-part inventory and checked local device drain before confirming full text. Missing/contradictory inventory, interruption, uncertain native cleanup or unknown alignment remain PARTIAL/UNKNOWN; elapsed milliseconds never imply exact words. Gemini retains its legacy limitations, and Live's primary protocol does not provide authoritative transcript completion or exact word/audio alignment. Remaining provider/acoustic validation belongs to Tasks12/18–20; see `review-07.md` and the verified provider notes.
7. Priority rule for interrupting current topic with a completed backend result.
8. Whether completed background work may automatically reopen GPT-Live; default should be conservative.
9. Prompt persistence scope: global vs architecture vs model profile.
10. Cost UI: elapsed billable time is mandatory; exact dollar display must distinguish estimate from provider usage.
11. The current Front Brain Settings preset selects full Realtime plus Luna, while the frozen comparison uses Realtime Mini plus Luna. Live evidence must decide whether to reorder that preset.
12. Quiet ambient and long-monologue scenarios need per-architecture device/provider runs; Duplex also lacks a direct-question run in the frozen offline suite.
