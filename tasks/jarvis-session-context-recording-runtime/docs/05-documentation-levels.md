# 05 - Documentation levels

Levels: 0 implicit/ambiguous, 1 named/discoverable, 2 dedicated contract, 3 reusable implementation/schema/validator/conformance gate.

| Concept | Current level on inspected `main` | Required | Action |
| --- | ---: | ---: | --- |
| JarvisSession lifecycle | 3 | 3 | Existing contract is strong but has the wrong restart semantic for this target. Slice 01 amends contract and Slice 03 updates runtime/tests. |
| Board / BoardConversationBinding | 3 | 3 compatibility only | Do not extend new Context/Capture semantics with Board coupling. Preserve until separate removal/refactor work. |
| SessionContext | 0 | 3 | Slice 01 names/invariants; Slice 02 schema/repository/workspace; Slice 03 agent/runtime use. |
| Session free-form Context workspace | 0 | 2/3 | Define ownership/security/lifecycle, then provide reusable workspace locator/writer boundary. |
| Canonical Session activity ledger | 0/1 (`RuntimeJournal` is diagnostic, conversation events are narrower) | 3 | Slice 04 adds product activity contract/store/query. |
| Generic Artifact registry | 0/1 | 3 | Existing scene artifacts/captures are domain-specific. Slice 04 adds generic identity/provenance/index. |
| Explicit durable audio recording | 0 | 3 | Current `AudioCaptureHub` intentionally persists nothing. Slice 05/06 add explicit recording contract/adapter. |
| Ambient PRESENTATION transcription | 3 | 3 unchanged | Reuse components but preserve lossy/freshness privacy contract. |
| Canonical recording transcript | 0 | 3 | Slice 06 defines immutable segments, projection, retry and gap semantics. |
| Generic desktop screenshot | 0 | 3 | Existing scene capture is not desktop capture. Slice 07. |
| Screen recording | 0 | 3 | Slice 07. |
| Live Context enrichment / catch-up | 0 | 2/3 | Slice 08 contract + worker/replay gates. |
| Capture API/MCP | 0 | 3 | Slice 09 uses existing MCP catalog/metadata conventions. |
| MCP catalog/tool contract | 3 | 3 | Extend, do not fork metadata/schema source of truth. |
| Left floating tool palette | 3 for Bare Hands tools | 3 generalized | Slice 10 defines separate capture group in same rail without polluting `BH.TOOL`. |
| Scene-control safe area | 3 | 3 | Update selector/layout tests when left rail grows. |
| Capture retention/deletion | 0 | 2 minimum | User media is durable by default; specify deletion/cascade and recovery semantics before rollout. |

## Documentation prerequisite rule

Where a target concept is currently Level 0, its contract Slice precedes behavior. The PM may split a Slice further if the fresh audit finds a hidden owner or a current task that already established a canonical contract. Do not implement around ambiguous ownership and document the guess afterward.
