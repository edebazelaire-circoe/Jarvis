# Target architecture

## Boundaries

```text
Capture/Transcription
  ambient lane
      |
      v
Presentation Context Runtime
  - recent transcript tail
  - authority classification
  - bounded working set
  - prepared resource index
      |
      +-----------------------------+
      |                             |
      v                             v
Background preparation         Explicit address
(non-blocking)                 -> Main Brain
      |                             |
      +---------------+-------------+
                      v
              Presentation Policy
          output kind + urgency + intent
              /                   \
             v                     v
        Speech path             Tool Brain
                                  |
                                  v
                    Scene / Prefab / Browser tools
```

## 1. Presentation mode state

Use the current canonical interaction-mode owner and persistence scope found in the repository. Presentation mode may not invent a parallel settings store. SIMPLE must remain the safe/default fallback.

The effective mode should be observable to the ambient lane, Brain/context assembly, presentation policy, Tool Brain and Control Center.

## 2. Ambient authority classification

Every speech segment consumed by Presentation must carry an explicit authority classification. At minimum distinguish:

- `ambient_context`: room/presenter speech with no Jarvis action authority;
- `explicit_address`: wake/manual addressed Jarvis interaction;
- `system/runtime`: non-human runtime events.

Do not rely on downstream prompt wording to keep these lanes separate. Encode the distinction structurally.

## 3. Fresh transcript tail

Maintain a bounded, low-latency sequence of the most recent ambient transcript segments with timestamps and stable segment IDs. Its purpose is temporal reference resolution, not durable memory.

This tail should make "ça", "ce chiffre", "le slide précédent", etc. resolvable against the immediately preceding presentation context.

## 4. Presentation working set

Maintain a bounded, session-scoped enriched view containing items such as:

- current topics/entities;
- salient claims/numbers;
- source/document references;
- prepared research results;
- prepared visual/resource handles;
- unresolved questions/contradictions;
- freshness/provenance/confidence metadata.

The implementation should prefer references/structured summaries over copying unlimited transcript text. The working set is disposable/rebuildable session state, not canonical memory.

## 5. Background intelligence

Background work may be triggered from ambient context when expected value is high enough, for example:

- fact-checking a concrete claim;
- resolving a mentioned document;
- preloading a likely report;
- calculating a likely-needed number;
- preparing a chart/table/window from already available data.

All background work must have clear cancellation/deprioritization semantics. It must not hold locks or scarce resources needed by explicit turns.

## 6. Priority and preemption

Recommended priority order:

1. explicit addressed user command/question;
2. runtime safety/error/required acknowledgement;
3. already-committed user-visible Presentation action;
4. high-value background preparation nearing completion;
5. speculative background work.

An explicit addressed turn may cancel/replace queued speculative UI intentions and deprioritize/cancel speculative sub-agent work.

## 7. Presentation output intent

The Presentation policy should produce a structured semantic result rather than directly invoke UI tools. Suggested conceptual shape:

```json
{
  "kind": "visual_command | question_answer | attention | none",
  "speech": "none | concise | normal",
  "display_intent": { "semantic": "...", "resource_refs": [] },
  "urgency": "immediate | soon | opportunistic",
  "reason": "...",
  "context_refs": []
}
```

Names are provisional; the implementer must reconcile them with existing intent/event contracts.

## 8. Tool Brain boundary

On the normal path Presentation should not choose low-level window coordinates, direct browser tool invocations, focus operations or concrete prefab IDs unless the semantic intent contract explicitly requires a pre-resolved resource reference.

Tool Brain combines Presentation intent with actual visible UI state and decides concrete UI actions/timing.

## 9. Scene/Prefab boundary

Presentation visuals should be prepared as reusable/parameterized prefab-backed scene resources when appropriate. A prepared resource should be referenceable later without rerunning expensive research or regenerating markup.

The Presentation task may define integration/adaptation glue only after the scene/prefab foundation exposes its canonical public API.

## 10. Contradiction/attention path

Ambient fact-checking may produce a candidate issue. Before manifesting attention, apply deterministic policy based on relevance, confidence, freshness and user impact. The visible outcome is a small attention/fact-check signal; the explanation remains latent until requested.

## 11. Observability

Emit enough structured events to reconstruct:

- effective interaction mode;
- ambient segment receipt/classification;
- working-set updates;
- background job start/cancel/complete;
- explicit-turn preemption;
- manifestation-policy decision and reason;
- Tool Brain intent publication;
- fact-check attention raised/cleared.

Use existing event IDs/trace links so the live timeline can correlate presentation decisions with Brain/sub-agent/UI activity.
