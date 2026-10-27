# I-002 — Slice 02 leftovers (QA 2026-10-26)

Origin: Slice 02 QA (runtime 7/7 PASS, code review with no blocker). Owners:

1. **Slice 06**: `__pycache__` written into the program folder. Precompile or disable bytecode writing in the package.
2. **Slice 06**: the child MCP servers' `*-mcp.json` files name the repository's venv python as their command. In the QA they got the right code only through an inherited `PYTHONPATH`. In product mode they must point at the packaged runtime.
3. **Slice 07**: `config\` is not created on first launch, only read if it exists. Onboarding should create the layout.
4. **Slice 07**: startup refusals (corrupt marker, missing `LOCALAPPDATA`) are only visible on a console, with broken encoding when redirected, and leave no durable trace. Without a console, the product needs a visible/durable refusal.
5. **Slices 07/10**: `core.context.workspace_failed` ("path is 249 characters") with a long sandbox path. Check the real headroom with a long user name or a redirected `LOCALAPPDATA` (long-path policy / margin in `context_workspace`).
6. **Slice 04**: the brain and agents' cwd = `CODE_ROOT` (`app.py:832,954,1380`, `control_center.py:1759-1762`). Self-dev / worktrees stay development tools, to confine.
7. Observation: the Claude CLI writes its cache to `%LOCALAPPDATA%\claude-cli-nodejs` (CLI state, not JARVIS state). Take it into account in the Slice 06 provisioning.
8. Present before this task: `test_app::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings` (stub without `data_root`) and `test_surface_reflex_policy::test_no_provider_model_id_reaches_core_or_domain` fail on `main` 2d6ca879.

## Slice 07 status (2026-10-26)
- Point 3: done. The launcher (`python -B -m jarvis launch`) creates `data`, `runtime`, `config` at first launch; the readiness action `prepare_data` recreates them.
- Point 4: done. Launcher refusals are shown (message box without a console) and written (`runtime/logs/launcher.log`, `errors.jsonl`, or `%TEMP%/jarvis-launcher-error.log` before any home exists). Proven in the simulated install (LOCALAPPDATA removed).
- Point 5: not re-measured (simulated home under `%TEMP%`, no long-path failure seen); stays with Slice 10.

## Slice 10 status (2026-10-27)
- Point 5: measured, closed. The longest file JARVIS writes itself in a Context folder of the installed product
  (`…\data\sessions\jsess_<32 hex>\contexts\jctx_<32 hex>\.jarvis-enrichment.json`) is 165 characters for
  `C:\Users\Jean` and 181 for a 20-character user name (the Windows maximum), so at least 78 characters of margin
  under `MAX_PATH`. The QA failure came from a sandbox home under a long `%TEMP%\claude\…\scratchpad` path. Files an
  agent writes deeper inside its Context stay checked by `safe_folders.check_file_path` (typed refusal, no crash).
