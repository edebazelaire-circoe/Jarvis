# Follow-up — the page's selection and focused pane reach the brain

## Origin

Slice 06 implementation polish 1 and Slice 07 implementation polish 4 of this task, still true at Slice 08.
« masque ça », « range ça », « affiche cette note sur le Board » are resolved by the brain from the scene or the
Dossier list, never from what the user selected on the page or from the Dossier pane that has the focus
(perception gap G1: there is no page → Core channel for the selection).

## Observed

- Slice 06 sandbox: « masque ça » hid the only drawn window while two windows were drawn as stars; the brain said
  « la seule fenêtre ouverte ».
- Slice 07 sandbox: « Affiche cette note sur le Board » with two notes side by side was answered by a question
  (honest, but the user had one of them in front of her).

## Product idea

Report, with each turn, a bounded description of what the user is pointing at on the page: the selected scene
object ids (≤ 20, the Ranger bound), the Dossier entry of the active tab and of the pane with focus, and the
displayed Board. `scene_*`, `dossier_ranger` and `dossier_present` then default to it when the user says « ça » or
« cette note ».

## Relationship to current task

Outside its scope: a new page → Core channel and a new turn-context field. The wheel's Sélection actions already
act on the page selection through the canonical routes; only the voice path guesses.

## Future questions

- freshness: the selection at the moment the user spoke, not when the turn starts;
- size and privacy bounds of the field; one source of truth with `JarvisScene.inspect().selection`;
- what the brain says when the selection changed meanwhile.
