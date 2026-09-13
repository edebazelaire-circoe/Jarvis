# Task14 implementation evidence

Status: implementation submitted for parent review; no Task14 acceptance or
Task15/16/17 start implied.

## Files and contract

- `jarvis/runtime/voice_capabilities.py`: `settings_architectures()` projects
  architecture labels/descriptions, typed role fields, exact registry options,
  reasons/selectability, model-dependent reasoning and provider settings.
- `jarvis/runtime/voice_architecture_config.py`: inspection can preserve a
  structurally valid but now unsupported saved model; normal decode and explicit
  saving remain strict. Existing query model lists share enriched options.
- `jarvis/runtime/control_center.py`: `voice.architecture` GET projection;
  discriminated config POST validation; no canonical write on omission;
  injectable registry; optional corrupt Google cache isolation; existing atomic
  writer, legacy settings and origin checks retained.
- `jarvis/domain/voice_architecture.py`: idle range is checked before float
  finitude so giant finite JSON integers reject as validation errors.
- `jarvis/runtime/control_center.html`: generic architecture-first panels,
  explicit-change latch, same-mode model preservation, unavailable reasons,
  stale async-render guard, next-activation/restart notice.
- `tests/unit/test_control_center_voice_architecture.py`: real local HTTP
  persistence, no active Voice mutation, RuntimeJournal privacy, manual-turn
  compatibility rejection, actual Node rendering/draft/save and async race.
- `tests/unit/test_routing_settings_screen.py`: existing static assertion follows
  guarded panel publication; actual stale-render behavior is exercised in Node.
- Independent QA remains in `test_control_center_voice_architecture_review.py`
  and `test_control_center_voice_architecture_ui_review.py`; lead did not edit them.

The unchanged legacy projection remains dynamic: neither its model nor its
old environment-derived architecture is materialized into a canonical namespace.
A same-mode explicit activation preserves the selected model. Unsupported saved
models remain inspectable; explicit new values must pass `require_ready=True`.
Unknown account availability is not promoted to available. Google choices require
actual cached `bidiGenerateContent` records; optional malformed data cannot break
all Settings and its contents never enter diagnostics.

## Reproducible validation

Expanded gate, **344 passed in 11.44 seconds**, warnings as errors:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_control_center_voice_architecture.py tests/unit/test_control_center_voice_architecture_review.py tests/unit/test_control_center_voice_architecture_ui_review.py tests/unit/test_control_center_quality.py tests/unit/test_control_center_mvp.py tests/unit/test_settings_endpoints.py tests/unit/test_settings_workbench.py tests/unit/test_agent_routing_settings.py tests/unit/test_routing_settings_screen.py tests/unit/test_voice_architecture_config.py tests/unit/test_voice_composition.py tests/unit/test_app.py tests/unit/test_v2_architecture.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

`git diff --check` passed. The RuntimeJournal test reads actual trace files and
checks `settings.update`, stable `voice.settings.rejected` codes, and absence of
private prompt text. Cache QA checks sanitized `voice.settings.catalog_rejected`
with `voice_catalog_invalid`. No diagnostic payload contains model prompts,
credentials or corrupt raw cache values.

## Limits

Controlled loopback HTTP and Node execution only; no CLI inference, provider
network call, device session or billable smoke. No new availability claim.
No prompt editor, Live timer/Stop UI, benchmark dashboard or active mode switching.
The existing Voice composition reads configuration at process startup; users must
restart Voice before activating the newly saved configuration. Save does not
replace the active frontend or cancel its accepted Jobs. Task17 owns reload and
replacement orchestration. Full release/acceptance remains parent-owned.
