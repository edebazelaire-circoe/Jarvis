# I-003 — Slice 03 leftovers (QA 2026-10-26)

Origin: Slice 03 QA (runtime, trace, code review) after the rework. Not blocking; owners:

1. **Slices 08/09**: the explicit copy to Documents has a button only after « Exporter la vidéo » (Variants, MP4 of the whole video). The Board's Artifacts view has no « Enregistrer une copie dans Documents » for a PNG still or a PDF yet; the contract and route already accept them (`POST /api/exports {artifact_id}`).
2. **Slices 08/09**: default file names use English class labels (`<title> - video|image|pdf`, `Jarvis export`). Product decision: French labels for the user's folder.
3. **Human check (HV)**: a Documents folder synchronised by OneDrive. The policy admits `IO_REPARSE_TAG_CLOUD*` folders and refuses every other reparse point; `lstat`/`st_reparse_tag` behaviour on a real OneDrive (Files On-Demand, Known Folder Move) was not exercised. A false refusal shows `export_destination_unsafe`. To check on a real OneDrive workstation.
4. **Slice 04**: the risky path seen in the trace (a sub-agent writing the file with native PowerShell/Write tools) is closed by removing those tools from the product brain; Slice 03 only made the safe path the natural one (prompt + refusal advice).
5. Present before this task: `test_control_center_mcp_api.py` (6 tests) count 21 `jarvis-display` tools instead of 20 (`ui_intent_publish`, same cause as `test_brain_capability_parity`); no display file is touched by Slice 03.

## Additions from runtime QA (2026-10-26, agent 0)
- **Slice 04 (critical)**: during the sandbox QA, a brain still holding PowerShell/Write copied files into the user's **real** `Documents` (twice) and into `C:\Users\Public` (once). It happened once on a hostile request and once on a neutral turn of a session reloaded with its old history (delegation to a sub-agent, then a native copy). Each file was checked (size/SHA/date) and deleted by the QA. Slice 04 must make this impossible; the hostile scenario must be re-run there.
- Browser harness: `tests/unit/_cdp_profile.mjs` treats the `JARVIS_CORE_PORT`/`JARVIS_UI_PORT` of its own environment as "live" ports, so it refuses the sandbox itself unless those variables are removed from its launch (`env -u …`).
- With `JARVIS_EXPORT_ROOT`, the label returned to the brain/UI is `JARVIS_EXPORT_ROOT\…` (sandbox only; the default root gives `Documents\Jarvis`).
