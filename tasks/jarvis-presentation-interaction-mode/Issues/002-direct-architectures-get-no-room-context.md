# Issue 002: direct architectures answer without the Presentation context

Found by the Slice 05 implementer, 2026-10-05. **Decided by agent 0:** accepted as a V1 limitation. The Human's configured architecture is `continuous_brain`, where the context is transported.

On the SIMPLE/FRONT_BRAIN direct paths (P12), the realtime model answers by itself after admission. No brain turn exists, so the P4 projection (fresh tail, working set, prepared object ids) cannot reach the model that answers. As a result, deictic requests ("montre-moi ça") and named prepared objects are not resolved from room context on those architectures.

Closing it would need a second transport into the realtime session, e.g. a context injection before `request_conversation`. That is a design change that needs its own contract.
