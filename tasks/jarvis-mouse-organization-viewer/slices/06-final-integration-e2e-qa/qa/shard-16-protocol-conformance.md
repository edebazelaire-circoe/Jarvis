# Shard 16: reconcile historical protocol assertion with reviewed Escape bridge

Frozen root `97d56f1144cb721e7c5303f43ff71d291ed1d9bc` completed shard 16:
**1502 passed, 7 failed, 6 skipped**. Six MCP count/context assertions match
the existing registry. The only new conformance failure was
`test_presentation_studio_reload_docs.py::test_the_protocol_a_frame_speaks_did_not_gain_a_message`,
line 136, freezing the old five frame message types. Original root log and
JSON remain under this Slice's `qa/evidence/shard-16.*`, unmodified and red.

PM assigned contract-test correction: S03's independently reviewed Escape-only
bridge is required behavior, not a product rollback or baseline issue.

The renamed test
`test_the_frame_protocol_keeps_the_reload_boundary_with_only_the_reviewed_escape_notice`
now pins the exact original five frame types plus only `escape`, the exact
unchanged four host types, and the complete exact frame payload-field table
(including `escape:[]`). The original `allow-scripts` sandbox and absence of
snapshot protocol text remain asserted. No wildcard acceptance was added.

The test also verifies the canonical `docs/prefabs.md` contract states the
exact fieldless `{jv:1,type:"escape"}` notice, optional local UI callback only,
and its existing bridge conformance-test reference. The docstring separates
hot reload's unchanged no-snapshot/restore decision from the later S03 UI
amendment and names the existing behavioral guards instead of duplicating a
parser.

Focused foreground validation: **18 passed in 9.13 seconds**, with retained
[console](shard-16-protocol-conformance.log) and
[JUnit](shard-16-protocol-conformance.xml). Main venv Python, workdir `mov5`,
`PYTHONDONTWRITEBYTECODE=1`, exact arguments:

```powershell
python -m pytest --assert=plain --tb=short -p no:cacheprovider -q `
  tests/unit/test_presentation_studio_reload_docs.py `
  tests/unit/test_prefab_escape_bridge.py `
  tests/unit/test_prefab_protocol_js.py::test_sandbox_and_csp_are_the_contract_values `
  tests/unit/test_prefab_protocol_js.py::test_parse_frame_message_accepts_the_contract_and_nothing_else `
  --junitxml=tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/shard-16-protocol-conformance.xml
```

Existing bridge checks cover exact shape/refusal of extra fields, non-Escape
and wrong-version notices; trusted/plain/nonrepeated input only after init;
listener teardown; focused/current/ready/source/origin/rate boundaries;
old/unmounted/paused/staged rejection; absent callback; and visible/logged
callback failure. These exercised actual JS modules in Node, without Chrome,
model, hardware or a full-suite rerun. No product/protocol/canonical document
was modified, and no known-failure ignore was added.

Queue `tests/unit/test_presentation_studio_reload_docs.py` in the final
corrective canonical file gate alongside the renderer/hold-desk files, after
all immutable full-gate shards finish. Root remains untouched meanwhile.
