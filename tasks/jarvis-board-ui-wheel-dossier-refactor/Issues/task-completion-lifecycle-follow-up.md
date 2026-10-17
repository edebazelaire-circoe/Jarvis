# Follow-up — completed task lifecycle and result replacement

## Origin

During the UI/Dossier discussion the user noted that completed task cards quickly clutter the scene and asked for this idea to be kept “de côté”, while explicitly acknowledging it was outside the immediate UI topic.

## Product idea

When a task/work item reaches completion, emit a completion event into a lifecycle policy that asks:

1. Does the task itself still deserve visible screen space?
2. Is there something the human must know about the result?
3. Should a concise notification, result card, report, artifact or Dossier document replace the execution/task representation?
4. What durable context/memory should be updated so Jarvis can recall what happened?
5. After useful output is preserved, can the finished execution representation be archived from the active scene in background?

The default should **not** be “always generate a report”. Ephemeral or low-value tasks may simply complete and archive after a small notification or no replacement at all.

## Relationship to current task

The UI refactor may expose existing archive/hide controls, but it must not implement this autonomous completion policy unless a separate task explicitly approves it.

## Future questions

- policy inputs: duration, task type, result value, user attention, errors, produced artifacts;
- replacement artifact taxonomy;
- notification lifetime and dismissal;
- Dossier/memory write criteria;
- traceability back to archived work item;
- user preferences and manual override;
- interaction with background tasks and Boards not currently active.
