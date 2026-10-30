# Shard 18: runtime host assertion follows the reviewed Escape amendment

The original frozen-root failure at
`test_presentation_studio_reload_host_js.py::test_the_sandbox_and_the_protocol_are_exactly_what_they_were`
line 197 expected the old five frame types. As assigned by PM, this is the
same test-conformance issue as shard 16: the accepted S03 Escape bridge must
remain, while hot reload must not add state-export/snapshot messages. It is
not classified as a baseline failure or a product rollback.

Renamed the test to
`test_reload_preserves_sandbox_and_protocol_with_only_the_fieldless_escape_bridge`
and clarified its historical module description. It still mounts a real
production `PrefabHost` through the existing `_node`/catalog-bundle harness.
It now requires the exact old five frame types plus only `escape`, and the
exact unchanged four host types; removed the permissive `None` alternatives.
The sandbox, no `allow`/`allowfullscreen`, restrictive CSP and no
snapshot/reload export-key assertions remain.

The same production protocol parser must accept only the fieldless Escape
notice and normalize it to `{type:'escape'}`. Added checks reject extra key
or payload fields, arbitrary key-message type and wrong protocol version.
No parser was copied or replaced. The docstring points to canonical
`docs/prefabs.md` and the existing complete behavioral bridge guards.

Focused actual foreground validation: **27 passed in 8.17 seconds**. Main
venv Python, cwd `mov5`, `PYTHONDONTWRITEBYTECODE=1`:

```powershell
python -m pytest --assert=plain --tb=short -p no:cacheprovider -q `
  tests/unit/test_presentation_studio_reload_host_js.py `
  tests/unit/test_prefab_escape_bridge.py `
  --junitxml=tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/shard-18-host-conformance.xml
```

Retained [console](shard-18-host-conformance.log) and
[JUnit](shard-18-host-conformance.xml). The complete host file also exercised
reload reporting, stabilization, teardown/resource bounds and staged-swap
behavior. Existing bridge tests exercised exact shape, trusted key/init/
teardown, focused live/source/origin/rate guards, stale/paused/staged denial,
absent callback and visible/logged callback failure.

Only test and QA evidence changed. No product/protocol code, registry ignore,
Chrome, physical adapter, model or full-suite run was involved. Queue this
host test file in the final corrective canonical file gate alongside the
previous renderer/desk and reload-doc corrections after 20/20 shards finish.
Original frozen-root raw red reports remain unchanged. The separate current
owned-read failure is not resolved or reclassified by this host correction.
