# Planning / Grill Session — Reconstructed

> This is a faithful reconstruction of the current design conversation. It is not claimed to be a byte-for-byte transcript. Decisions are separated from exploratory ideas so implementation agents do not treat speculation as locked scope.

## 1. Problem identified

The user described the current Jarvis Brain as carrying too many responsibilities at once: understanding and reasoning, producing speech, loading context, launching work, and manipulating what is shown on screen. UI tool use can therefore arrive late relative to the spoken answer, especially for long responses.

The proposed direction was to split display/tool decision-making into a separate brain running beside Jarvis.

## 2. From UI Brain to Tool Brain

The user renamed the concept from **UI Brain** to **Tool Brain** because the long-term idea may eventually delegate more tools to it. V1 is intentionally narrower: only UI tools are delegated. Non-UI tools remain directly available to Jarvis.

Jarvis must know this architecture exists. It should understand the UI capabilities that Jarvis-as-a-system possesses, but should not normally perform those UI tool calls itself. This prevents both double control and misleading statements such as claiming the system cannot display something while the Tool Brain is doing exactly that.

## 3. Jarvis intents rather than UI commands

Jarvis should provide structured intent/relevance information to the Tool Brain, not micromanage positions or low-level calls. Tool Brain remains free to decide whether and how to act.

The two brains should communicate through structured state/events rather than natural-language commands to each other.

## 4. Speech timing and future chunks

A long Jarvis message can take many seconds to speak. Tool Brain therefore needs more than the final response text. It needs to know:

- what Jarvis has already said;
- what chunk is currently being spoken;
- what chunks remain and will be spoken later;
- where current speech progress sits inside the generated response.

This lets it prepare or schedule UI actions before the relevant spoken section arrives.

## 5. Hybrid decision loop

The user accepted a hybrid wake-up strategy:

- immediate wake on important events, such as new user input, speech chunk changes, interruption, artifact/scene changes, Board changes, or failed/invalid actions;
- a short periodic tick as a fallback rather than waiting several seconds for every decision.

## 6. Tool-call queue

Tool Brain manages a queue, not only one tool call at a time. It can schedule actions for now or later, including against speech progress/events, and may cancel, replace, reprioritize or delay pending actions when the context changes.

If the UI state changes between planning and execution, the runtime rejects stale actions, provides fresh state, and wakes Tool Brain to replan.

## 7. Autonomy

The user accepted near-total Tool Brain autonomy over reversible UI actions. Destructive/irreversible actions should have mechanical guardrails.

## 8. Choice-constrained tool parameters

A key design requirement is that the model should not invent arbitrary IDs or parameters when the runtime already knows the legal values.

For example, if `move` can only target the currently existing scene objects, the Tool Brain should receive the valid IDs and a human-readable description for each. The same principle should apply across UI tools wherever practical.

Tool definitions therefore need rich parameter metadata and dynamic choice providers derived from current state. The Tool Brain may first call read/inspection methods to learn more about an ID before choosing a mutating action.

## 9. Perception module

The user asked for a dedicated perception layer that prepares a compact but useful world representation for Tool Brain. The default snapshot should describe what the user currently sees, including the active Board and scene objects such as stars, points, capsules and windows, with IDs and type/status metadata.

Agent/task/process objects should expose relevant condensed state such as whether work is running or complete. Tool Brain can call a method such as `get_information_on(id)` to retrieve richer metadata only when needed.

Stable IDs are mandatory for an object during its lifetime.

The same world representation should include relevant desktop/browser UI state so that a request like “open a new window” can be interpreted relative to the browser/window the user is already using.

## 10. UI tool scope

The user explicitly included Board switching as a Tool Brain concern and discussed creating or adapting operations for:

- current Board and scene inspection;
- selecting/manipulating live process/agent objects;
- opening/focusing/moving windows;
- opening a URL or browser surface;
- scrolling/navigating a displayed web page.

In V1 those browser operations are display/navigation capabilities, not permission for Tool Brain to conduct independent web research.

## 11. Existing transcription / observability surface

The user noted that a transcription tool/view already exists. The correct implementation is to adapt that existing live view so Tool Brain activity is visible alongside user transcription, Reflex/Mouth response and Backbrain/Brain activity.

The purpose is debugging and understanding timing: see Tool Brain decisions, scheduled calls, executed calls, cancellations and failures on the same time axis. Do not build a second transcript system.

## 12. Model choice

Fast/specialized models and later fine-tuning were discussed, but no specific model was selected. The architecture should make the decision model swappable and create trace/evaluation data that could support later training.
