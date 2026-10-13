# Documentation levels and required contract maturation


Levels: L0 implicit; L1 canonical named term; L2 dedicated normative contract; L3 executable/reusable implementation or conformance gate.


| Concept | Known project baseline | Required after fix | Owner / Slice |
| --- | --- | --- | --- |
| Presentation Studio, Variants, source/variant pins | L2-L3 in `docs/presentation-studio.md` and existing services | L3; one stable variant source | 01,02,11,12,15 |
| Remotion runtime, player, native Studio | L2-L3 in `docs/remotion-runtime.md`, `docs/remotion-studio.md`, `docs/remotion-source.md` | L3 with native editing round trip | 01,04-06,11-12 |
| Canonical composition and time/frame semantics | Multiple existing contracts including `docs/remotion-runtime.md`, `docs/presentation-studio.md`; coherent global timeline unverified | L2 prerequisite then L3 frame mapping and tests | 02,03,04,05,06 |
| Score/cue/sidekick boundary | L2-L3 in `docs/presentation-mode.md`, `docs/presentation-studio.md` | L3 verified against video playback | 02,07 |
| Unified control hierarchy of Variants | L0/L1 user demand; existing browser controls in JS | L2 before frontend, L3 tested UI | 02,10 |
| Viewer lifecycle/deprecation | L1 scattered windows/modules; duplicates observable | L2 deprecation plan, L3 migrator/tests | 01,09,15 |
| Safe native authoring workspace and Studio sync | L2-L3 read-only Studio model in `docs/remotion-studio.md` | L2 explicit trust and write model, L3 persistence/hot reload | 12 |
| Agent-native creative creation | L2 playbooks/authoring rules exist; user reports worse quality | L2 optional versus required schema, L3 traces/benchmark | 13,14 |
| Visual QA | L1/L2 limited; no general visual objective in `docs/presentation-production.md` | L3 rendered-frame gates and Human review | 03,14,16 |
| Left rail final design | L0 future sketch pending | Remain unresolved; no UI spec invented | Not in this task |


The PM must independently audit current levels before reading/relying on these estimates; this is a planning map, not proof of acceptance.