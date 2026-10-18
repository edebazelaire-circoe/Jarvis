# Follow-up — brain behaviour seen in this task's real traces

## Origin

Real model turns of Slices 01b, 05, 06, 07 and 08 (sandbox evidence of each Slice; Slice 08:
`slices/08-integration-accessibility-regression/evidence/agent-turns.log`). None of these is caused by the
refactor's code: they are prompt and runtime behaviours of the brain.

## Observed

1. **Turns over the 8 s budget** (`agent.turn_over_budget`; 10 to 64 s in Slice 08), the known « Your previous
   response had no visible output » retry (Slice 08: « Ouvre le compte rendu du comité dans le Dossier », 36 s),
   once an English working sentence (Slice 07: « Note decision-budget plus arbitrages-licences, side by side. ») and
   a stray « Single small file read is allowed. » (Slice 05).
2. **Notes read with `Read` or `Bash cat` on the absolute path** instead of `board_memory_read`, although
   `BRAIN_WORKSPACE_PROMPT` says « une note se lit par board_memory_read » (Slices 05 and 07; Slice 08: « Que dit
   maintenant la note sur la décision budget ? » → `Read …\boards\<Projet Atlas>\memory\notes\decision-budget.md`).
   The file read is the canonical source (the one the Dossier edits; the human correction was read back), but the
   path comes from the turn context (`claude_local.py`: « Le savoir durable du Board actif va dans son dossier
   mémoire, donné par ton contexte de tour ») and the read bypasses the workspace service (no
   `core.workspace.read`, no Board check).
3. **Stale « Déjà dit »** (Slice 01b): after a switch announced in an earlier turn was executed and then left, the
   brief still carried « La bascule se fera à la fin de ce message » and the brain claimed a switch was « déjà
   programmé ». The Board-session context should mark an announced switch as done or left, or the brain should check
   `board_get_active` before stating a switch state.
4. **Small embellishments**: « remise en avant » on `dossier_present` `created:false` (Slice 07); after an external
   archive, « la note apparaît sans doute deux fois » instead of reading the scene (Slice 07).
5. **« Réduire »** is heard as `point` (étoile) (Slice 06). The wheel says Capsule = « titre seul » and Étoile =
   « réduite à un point »; the scene tool descriptions could say the same.

## Resolved in this task (not to redo)

« retire-la du Board » used to call `dossier_ranger` (writes a note, then archives). Since Slice 08 the
`dossier_ranger` description says « Pas « retirer du Board » : c'est scene_archive ». Real trace: « Retire du Board
la fenêtre « Brouillon à retirer » » → `scene_archive` → `archive_selection`, the same operation as the wheel's
« Retirer du Board ».

## Future questions

- whether the turn context should stop giving the memory folder's absolute path (point 2), or whether a `Read` of a
  Board memory path should be routed through the workspace service;
- a latency budget per tool family; the wording of the retry.
