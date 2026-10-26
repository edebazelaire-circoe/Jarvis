# I-001 — Slice 01 non-blocking leftovers (QA 2026-10-26)

Origin: Slice 01 QA (code review + runtime). None blocks V1 and none is a regression.

1. Prompt line 44 (`BRAIN_WORKSPACE_PROMPT`, "passe en mode présentation / simple / réunion") is still rendered as-is in the `presentation` edition. It offers no type and line 63 contradicts it; an edition variant would be cleaner. Possible owner: Slice 04 (product prompt) or Slice 08.
2. `board_list` does not return per-Board availability. The model learns about the refusal by attempting the switch (one extra call). This would change `BoardSummary` and the typed results.
3. The fallback that creates a new Board emits `core.session.binding_rebuilt` as a warning, although it is expected behaviour.
4. No test covers a closed Session whose last Board is a legacy one (`_open_at_start`). It goes through the same `_start_board`.
5. The prompt preview / workshop resolves without `product_edition` and shows the `full` version.
6. Deferred switch from the screen (`origin=user`): no check before sending, only Core's refusal. Correct but late.
7. Refusing `empty` shows `board_kind 'assistant'` (normalised alias).
8. Present on `main` 2d6ca879, unrelated to this task: `test_tool_brain_choices::test_ui_projection_is_consistent_in_the_single_metadata_copy` (`reversibility='irreversible'` on `presentation_library`). Sandbox: `--chrome` opens a tab in the user's Chrome.
