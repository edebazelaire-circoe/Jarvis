# 07 — Human-intent audit

This audit was performed **after** assembling the implementation plan, as explicitly requested by the user. It compares the handoff against the whole visible design conversation, including the initial complaints about the current UI and the later Dossier clarification.

## Audit checklist

| Human intent | Handoff coverage | Result |
| --- | --- | --- |
| Board has a type; no longer switch one Board through Simple/Presentation/Meeting | README, D01–D03, architecture §1, Slice 01 | PASS |
| Board type fixed after creation | D02, Slice 01/02 acceptance | PASS |
| Bottom-left becomes Board selector rather than mode selector | README, UI spec A, Slice 02 | PASS |
| Old top-left Board selector must go | removal table, Slice 02 | PASS |
| Old Voice/Claude persistent status must go/move into menu | removal table, JARVIS submenu, Slice 02/04 | PASS |
| Large mode selector + MODE SIMPLE must go | explicit deletion assertions, Slice 02 | PASS |
| Permanent hidden-object chip/count must go | D06, UI spec A, Slice 02/06 | PASS |
| Wheel graphics must be substantially redesigned | D09–D10, UI visual spec B, Slice 03 | PASS |
| Chosen generated image is a style reference, not literal layout | README visual reference rules, D10 | PASS |
| Only selected category opens submenu; generated image's simultaneous panels are wrong | D08, UI spec B, Slice 03 test invariant | PASS |
| Desired primary entries: Jarvis, Selection, Dossier, Capture, Settings | D07, wheel spec | PASS |
| No first-level Search | D17, removals, Slice 03 | PASS |
| No generic first-level Tools | D18, removals, Slice 03 | PASS |
| Dossier replaces “Files/Documents” as richer concept | D13, architecture §4, Slice 05/07 | PASS |
| Existing separate Video/Screenshot/Audio primary buttons should be consolidated into Capture | D11, Slice 03/04 | PASS |
| Active video should show REC; audio should show orb/wave; simultaneous recording allowed | D12, UI spec E, Slice 04 | PASS |
| Hidden is temporary, not another long-term folder | D15, architecture §5, Slice 06 | PASS |
| Ranger visible artifacts/content into Dossier | architecture Ranger operation, Slice 05/06 | PASS |
| Dossier items can be pulled back onto Board, reduced/starred, then put away | architecture `Afficher sur le Board`, Slice 05/06/07 | PASS |
| Dossier should be a polished full-screen browsing/reading workspace, not only folders | UI spec G, Slice 07 | PASS |
| Human and Jarvis both work on Board context; human corrections should help future agent context | D13–D14, architecture §4/§6, Slice 05/07/08 trace criteria | PASS |
| Jarvis should navigate/open Dossier content by voice | architecture §6, Slice 07 | PASS |
| Agent logs/internal memory should exist but not pollute human default UI | D14, Dossier advanced view | PASS |
| General search can be asked to Jarvis; Dossier may have local search | D17, Slice 07 | PASS |
| Settings remains a valid primary wheel item | D07, UI spec F | PASS |
| Existing useful runtime/capture owners should not be duplicated | D19, architecture, Slices 03–05 | PASS |
| Idea about finished task cards/report/archive must not be lost but is out of scope | D20, `Issues/task-completion-lifecycle-follow-up.md` | PASS |
| Focus on what disappears as well as what is added | README removal table, testing deletion assertions, Slice 02/03 | PASS |

## Potential ambiguity deliberately not overclaimed

### Board favorites

The user suggested favorites as a possible quick switch mechanism (“pourquoi pas”). This is preserved as a nice-to-have, not a locked acceptance blocker. Existing/recent Board switching and creation are locked.

### “Thinking mode” controls under JARVIS

The user wants a place to manually influence Jarvis's state/behaviour, but current canonical support must be audited. The handoff requires the JARVIS submenu and canonical Sleep/Wake/Voice status/actions; it forbids inventing fake model/thinking controls solely to match a concept image.

### Meeting runtime

The user wants Réunion as a fixed Board type, but the planning-time canonical InteractionMode contract still calls meeting behaviour planned. This handoff does **not** expand scope into implementing a whole meeting runtime. It requires the type to be canonical/openable and the runtime capability/fallback to be explicit and deterministic rather than maintaining a separate mode toggle.

## Final audit conclusion

No material human intent found in the visible conversation is omitted from the implementation plan. The two major risks are explicitly surfaced rather than hidden:

1. the repository's current Board/InteractionMode contract contradicts the desired fixed-type model and therefore needs a real migration before UI cleanup;
2. Dossier must be built on existing Board memory/artifact truth rather than becoming another storage system.

The completed-task lifecycle is intentionally retained as a follow-up Issue instead of being accidentally implemented inside the UI refactor.

## Re-audit by Slice 00 against HEAD `2fb66040` and the revised plan (2026-10-17)

`grill-session.md` and the checklist above were re-read row by row against the revised Slices (01a/01b split, `docs/08-readiness-audit.md`). All 28 rows stay PASS; the coverage moved as follows:

| Human intent (row above) | Revised coverage |
| --- | --- |
| Board has a type / fixed after creation | Slice 01a (contract, v9 migration, Core derivation, no stored divergence) + 01b (no live divergence: every user/agent mode writer retired) |
| Old Voice/Claude persistent status must go/move into menu | Slice 02 removes `.state`; Slice 04 JARVIS submenu shows the same facts (voice state, agent, sub-agents, wake key). The Voice **presentation presence report** that lived in the mode HUD moves to the Board card (Slice 02): critical feedback kept |
| Permanent hidden-object chip/count must go | At HEAD the chip had become the permanent eye `#hiddenEye` (orbital-ui S06): Slice 02 removes it, Slice 06 re-exposes « Afficher les masqués (N) » and « Tout réafficher » inside Sélection |
| Active video should show REC (« en haut à gauche »); audio orb; simultaneous | Slice 04 reuses the existing transient `#recIndicators` and moves them to the top-left zone freed by Slice 02 |
| Settings remains a valid primary wheel item | Slice 04 wires Paramètres to `#openSettings` and folds the duplicate launcher `SET` into « Plus d’outils » |
| Existing useful owners not duplicated | Slice 00 owner table (`docs/08` §2); Dossier = projection, five missing operations only (`docs/08` §6) |

Still bounded, not overclaimed: the grill's wish to « forcer manuellement par le clic le mode de pensée de Jarvis » has no canonical API at HEAD (no sleep/wake or thinking control route); the JARVIS submenu is status-only and the gap is stated, not faked. A Studio run may still switch the live mode transiently (activity, not a user selector), consistent with « Jarvis se met dans le type de board dans lequel il est » as the baseline.
