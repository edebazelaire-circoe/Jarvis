# 01 — Decision log

`LOCKED` decisions express direct human intent or a necessary safety consequence. `PROVISIONAL` decisions are implementation guidance the Project Manager may adjust if current repository contracts provide a cleaner path without violating the human intent.

| ID | Status | Decision | Rationale |
| --- | --- | --- | --- |
| D01 | LOCKED | A Board has one fixed user-facing type: Assistant, Présentation or Réunion. | Replaces mode switching mental model. |
| D02 | LOCKED | Board type is selected at creation and is not editable through ordinary UI afterward. | “Un board a un type et on ne peut plus switcher de type.” |
| D03 | LOCKED | Remove the user-facing SIMPLE/PRESENTATION/REUNION interaction-mode selector. | It duplicates/conflicts with Board type. |
| D04 | LOCKED | The active Board control moves to a compact bottom-left Board card. | One place answers “where am I?”. |
| D05 | LOCKED | Remove the old top-left Board selector and persistent `VOICE … RUNNING`-style status badge. | Reduce permanent chrome. |
| D06 | LOCKED | Remove the permanent hidden-object count/toggle from the main shell. | Hidden is temporary, not a storage area. |
| D07 | LOCKED | Wheel primary categories are exactly JARVIS / Sélection / Dossier / Capture / Paramètres for this refactor. | User converged on these and rejected Recherche/Outils. |
| D08 | LOCKED | Only the selected wheel category shows its second-level menu. | Explicit correction to the chosen generated reference. |
| D09 | LOCKED | The wheel receives a real graphic redesign toward `style-reference-radial-ui.png`. | User said this is an UI refactor and wheel graphics are especially important. |
| D10 | LOCKED | Reference image is style/composition inspiration only, not a pixel or feature specification. | Generated concepts contained wrong actions/layout. |
| D11 | LOCKED | Capture is one first-level category; screenshot, screen/video and audio are secondary actions. | Removes first-level fragmentation. |
| D12 | LOCKED | Active recording status is transient and visible only while relevant; audio/video may coexist. | Cleaner shell without hiding important active state. |
| D13 | LOCKED | Dossier is the human-readable documentary workspace of a Board, shared conceptually with Jarvis/agents. | Human must be able to inspect/correct Board context. |
| D14 | LOCKED | Dossier must not default to a technical dump. Raw IDs/logs/provenance are secondary/advanced. | Human clarity is central. |
| D15 | LOCKED | `Masquer` = temporary scene visibility. `Ranger` = ensure durable Dossier backing then remove/archive the scene representation. | Avoids hidden-object junk drawer. |
| D16 | LOCKED | Board view and Dossier view are complementary representations of the same work. | “Board” spatial vs “Dossier” documentary. |
| D17 | LOCKED | Search is not a first-level global wheel entry. Dossier may contain internal search; Jarvis voice/chat handles general research intent. | User explicitly rejected global Recherche. |
| D18 | LOCKED | Do not introduce a first-level generic `Outils` catch-all. | User explicitly rejected it. |
| D19 | LOCKED | Preserve current canonical backend owners and refuse fake/optimistic states. | UI should not lie about capture/runtime/Board truth. |
| D20 | LOCKED | Completed-task lifecycle is a follow-up Issue, not this task's implementation scope. | User explicitly called it a detour but asked to preserve it. |
| D21 | PROVISIONAL | Reuse existing `BoardKind` rather than inventing a parallel `BoardType` class if the current domain allows a clean migration. | Prefer one canonical vocabulary. |
| D22 | PROVISIONAL | Legacy `empty` Board kind migrates to Assistant; an explicit legacy Presentation/Meeting choice on an `empty` Board can seed the new type once. | Preserve user intent during migration. |
| D23 | PROVISIONAL | The legacy `InteractionMode` implementation may survive internally as a derived policy adapter until Presentation code is migrated, but its user mutation/persistence authority ends. | Avoid unnecessary rewrite while removing double truth. |
| D24 | PROVISIONAL | A Meeting Board remains openable even if dedicated meeting behaviour is still planned; use an explicit safe capability/fallback state rather than fake functionality or a separate user mode. | Do not block Board navigation on unfinished behaviour. |
| D25 | PROVISIONAL | Board favorites are nice-to-have. Implement only if a canonical persistence concept exists or can be added cheaply and coherently; recent/existing Board switching is mandatory. | User said “pourquoi pas”. |
| D26 | PROVISIONAL | Build Dossier as a projection over Board memory + linked Artifacts, with semantic operations added only where missing. | Avoid a fourth storage silo. |
| D27 | PROVISIONAL | Re-presenting a Dossier item on the Board creates/reuses a scene representation pointing to the same durable content; it must not clone the underlying document by default. | Content and representation are separate. |
| D28 | LOCKED | Existing mouse, keyboard and Bare Hands wheel activation mechanisms remain unless current HEAD proves they are obsolete; graphic redesign must not regress input accessibility. | Existing implementation already solves multi-input interaction. |

## Migration rule to validate in Slice 01

The planning recommendation is:

1. `board_kind = presentation` → Présentation.
2. `board_kind = meeting` → Réunion.
3. legacy `board_kind = empty` + explicit/stored `interaction_mode = presentation` → Présentation.
4. legacy `board_kind = empty` + explicit/stored `interaction_mode = meeting` → Réunion.
5. remaining `empty`/missing legacy kind → Assistant.
6. new writes use the new canonical type vocabulary; legacy values may be read only for migration/compatibility.
7. after migration, normal Board edits cannot change the type.
8. active behaviour derives from type; no independent user toggle remains.

Slice 00/01 must verify actual storage/schema/compatibility before locking this exact mechanism.
