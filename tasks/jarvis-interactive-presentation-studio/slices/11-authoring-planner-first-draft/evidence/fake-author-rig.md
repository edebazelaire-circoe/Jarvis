# Slice 11 - fake-author rig evidence (redacted)

> Scripted rig, not a model trace. The real-model trace analysis (does Claude follow the policy, how many tool calls, do the questions stay in the budget, is the first draft respectable) is a required gate of Slices 21 and 22.

Planner prompt `presentation_studio.authoring.planner`: 6885 characters, content fingerprint `bc25a1bba7229ad5...` (path-independent: the registry's own `default_revision` also hashes the source path), operations `presentation_draft_check`, `presentation_draft_assemble`, `presentation_draft_finalize`, attached to a prompt program: True.
Gate: 48 rules. Question cap: {'one_shot': 0, 'exploratory': 1, 'directed': 3}.

## Scripted authors

| Scenario | Workflow | Check ok | Assemble | Errors | Warnings | Variants (draft) | Scenes | Prefabs | DA origin |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| good one-shot (report display) | one_shot | True | delivered (201) | - | - | 1 (0) | 1 | 1 | generated |
| good 12-scene directed deck | directed | True | delivered (201) | - | - | 1 (0) | 12 | 1 | inferred |
| exploratory, 3 divergent candidates | exploratory | True | delivered (201) | - | - | 3 (3) | 3 | 1 | generated, generated, generated |

## The careless author: one rule broken at a time

| Violated rule | Assemble | Errors raised | Caught | Anything written |
| --- | --- | --- | --- | --- |
| `da_missing` | refused (400) | da_missing | True | False |
| `da_incoherent` | refused (400) | da_incoherent | True | False |
| `contrast_low` | refused (400) | contrast_low | True | False |
| `arc_incomplete` | refused (400) | arc_incomplete | True | False |
| `scene_no_score` | refused (400) | notes_missing, scene_no_score | True | False |
| `transition_missing` | refused (400) | transition_missing | True | False |
| `placeholder_text` | refused (400) | placeholder_text | True | False |
| `repeated_filler` | refused (400) | repeated_filler | True | False |
| `text_density` | refused (400) | text_density | True | False |
| `duration_off` | refused (400) | duration_off | True | False |
| `presenter_mismatch` | refused (400) | presenter_mismatch | True | False |
| `controls_too_many` | refused (400) | controls_too_many | True | False |
| `control_unlabelled` | refused (400) | control_unlabelled | True | False |
| `control_unbounded` | refused (400) | control_unbounded | True | False |
| `cue_weak` | refused (400) | cue_weak | True | False |
| `cue_ambiguous` | refused (400) | cue_ambiguous | True | False |
| `motion_unguarded` | refused (400) | motion_unguarded | True | False |
| `prefab_namespace` | refused (400) | prefab_namespace | True | False |
| `pin_unknown` | refused (400) | pin_unknown | True | False |
| `scene_incompatible` | refused (400) | scene_incompatible | True | False |
| `score_incompatible` | refused (400) | score_incompatible | True | False |
| `notes_missing` | refused (400) | notes_missing | True | False |
| `content_thin` | refused (400) | content_thin | True | False |
| `filler_numeric_variants` | refused (400) | filler_numeric_variants | True | False |
| `cue_stopword_phrase` | refused (400) | cue_stopword_phrase | True | False |
| `control_label_meaningless` | refused (400) | control_label_meaningless | True | False |
| `must_cover_missing` | refused (400) | must_cover_missing | True | False |
| `language_mismatch` | refused (400) | language_mismatch | True | False |
| `behavior_risky` | refused (400) | behavior_risky | True | False |

Rules exercised by their own unit tests rather than by this table: brief_invalid, candidates_count, candidates_not_divergent, document_invalid, draft_schema, placeholder_allowed, prefab_invalid, scene_unbound, and every warning-level rule.

Kill drills: see tests/unit/test_presentation_studio_authoring_crash.py (real Popen.kill at: before publication, after a published bundle, documents built, inside the store write x3, right after the commit).
