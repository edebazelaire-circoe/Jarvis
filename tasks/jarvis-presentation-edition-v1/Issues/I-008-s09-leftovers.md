# I-008 — Slice 09 leftovers (QA 2026-10-26)

Origin: Slice 09 QA (code review `slices/09-presentation-editing-ui/qa/code-review.md`, runtime QA) and its rework. The rework fixed the
blocking and major findings (draft lost when Variants changes the scene, Core stopped during an edit, deck written by the real author not
editable, export of a branch made by « Nouvelle variante… », blank image/PDF of a fading scene, image/PDF export without a scene choice,
keyboard and focus, undo racing a queued write, missing tests). What follows was deliberately left out. Not blocking; owners:

1. **Replacing a visual is deferred after V1 (PM decision).** `SLICE.md` › *In Scope* « media/image replacement » and step 6 « bounded
   internal assets » are not delivered: a choice of image bounded to Jarvis's internal assets (never a filesystem path) needs an asset
   contract on Core's side first (list, import, quota, provenance, how a scene control of type `url` points to an asset). Texts, colours
   and motion stay editable from « Modifier ». Written in the V1 known limits of `docs/presentation-studio.md` › *Editing from Variants
   (V1)*; HV-EDIT-01 no longer asks to replace a visual. Owner: a post-V1 task (Core asset contract, then the editor's picker).
2. **The undo ring is in memory.** Lost when Core restarts (said by the tooltip and the contract). A durable history needs a schema change
   (versioned migration). Owner: post-V1.
3. **Editing jargon still on screen** (seen by the runtime QA, not changed by this rework): « Fallback - Corporate calm · secours »,
   « DA · RÉV. 1 », « GÉNÉRÉE / REPLI », « Partition liée », « Racine de l'arbre », « Pourquoi cette branche ? », « 0/800 octets »,
   « INSPECTEUR », « Artefact jart_… » (Variants' metadata, the editor's art-direction chip and title, the export line). Owner: Slice 10
   (production readiness) or a wording pass before the final acceptance (Slice 11).
4. **`remotion_setup` refused when the brain delegates** (`remotion_user_turn_required`): already I-005; seen again by the Slice 09 runtime
   QA (a `[presentation-author]` asked to install Remotion and was refused, the deck was not created). The Slice 09 rework installed Remotion
   from the page before its real brain turn. Owner: as in I-005.
5. **Remotion Studio really starting in the `full` edition** was not exercised (the QA stopped at the confirmation dialog). Owner: Slice 11
   (final end-to-end acceptance).
6. **Observations of the rework (no action decided)**:
   - The editor's move queue saves a value typed when Variants changes the scene; while it cannot (Core unreachable), the editor stays on
     its scene and Variants may show another one for a while. Said on screen; a pause of Variants' play at the first keystroke was not
     chosen (it would stop the user's play for a typo).
   - The native authoring gate now requires a content control per scene (`NATIVE_REQUIRED`); a deck assembled before this rework keeps its
     scenes without controls (no migration of existing decks: « Modifier » says « Cette scène n'expose aucun réglage » there).
7. **Left by the QA re-check of the rework (2026-10-27, `slices/09-…/qa/rework-review.md`), not treated by the mini-rework**:
   - **m4 — the native floor is met by a dead control.** `scene_no_controls` (native) asks for one `content` control, but a control whose
     prop the TSX never reads stays a warning (`tsx_props_unread`): « Modifier » may then offer a field that changes nothing on the
     image. Watch it in the authors' traces; the full floor would make `tsx_props_unread` an error for `content` controls. Owner: Slice 10
     or a post-V1 authoring pass.
   - **Variants' notice « Core ne répond plus… » stays after Core is back**, through a variant creation and a successful export (`c10`),
     until × or « Relire ». Older than Slice 09 (the rework only changed its words). Owner: Slice 10.
   - **Jargon of an image render**: its line shows « scène pss_604563c21abd » (`c11-b`), with the other words of n° 3. Owner: as n° 3.
   - **A frozen copy made before `448c055c`** (a variant whose lineage was frozen with its `sources`) is still refused at render (French
     message, no « Réessayer »): it has to be frozen again. Deduced from the code, not exercised. Owner: Slice 10 (a recovery or a clear
     « regeler » action) or accepted as a known limit.
