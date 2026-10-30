# Shard 01 unknown failures: read-only pretriage

Inspected while the root sequential gate continues. No pytest, Chrome, model,
product edit or root-worktree commit was performed for this pretriage. This is
source evidence and a proposed baseline check, not executed baseline acceptance.

## Observed completed gate evidence

Root revision `97d56f1144cb721e7c5303f43ff71d291ed1d9bc`.
Root `qa/evidence/shard-01.json`: 54 files, 1,371 collected, 1,362 passed,
2 failed, 7 skipped, exit 1, green false, no session problems. Both failures are
unknown to the dated known-failure list; there are no stale/expired/unseen
known entries in this shard. Log and JSON remain the authoritative gate output.

## Timeline dock source assertion

Node:
`tests/unit/test_control_center_timeline_ui.py::test_the_cosmos_theme_knows_every_dock_tool_and_moves_the_pills`

The completed shard traceback confirms line 165 requires an exact dock CSS
string with `right:var(--shell-gutter)`. Current and baseline HTML both have
`left:var(--shell-gutter)` at line 122 instead. The source test and
`control_center_work.js` are byte-identical between `c0858a80` and root HEAD.
HTML differs only by four new module markers at the scene injection point;
the entire dock navigation block is identical. Static inspection of the
preceding tool/icon/order/row/token/pill predicates found no other discrepancy.

SHA-256 evidence from git blob bytes:

| Input | c0858a80 and root |
| --- | --- |
| timeline UI test | `b3be61d6923de976eac32c4261390a7188f59f5207dc6314b470b61bdf7e1c34` |
| work/theme module | `6b2a9d4b53fbd2f0c44147884d45ed8dbb6ebf3f86858a20d594dcb2f194d68e` |
| extracted dock block | `9eb9e6ca45190cd5ec8784944ccaa04934fcfb702b03c24787da6e3c38aa3881` |

Provisional classification: pre-existing assertion drift around launcher
placement, unrelated to this feature's module injection. Actual exact-baseline
pytest reproduction is still required after the full gate before disposition.

## Presentation speech-kind source assertion

Naturally encountered in the same running log, then confirmed by completed
shard JSON:
`tests/unit/test_presentation_response_policy.py::test_aucun_site_de_production_ne_laisse_le_modele_nommer_sa_nature_de_parole`

The shard traceback identifies line 1185, comparison of AST-derived call-site
table against `SPEECH_KIND_SITES`. A bounded git-grep/AST source inventory of
tracked Python files mentioning SpeechRequest shows the same sole mismatch on
both baseline and root:

- `jarvis/runtime/speech_scheduler.py`: actual literal kinds
  `SpeechKind.ACK`, `SpeechKind.QUESTION`; expected table contains only
  `SpeechKind.QUESTION`.
- The five production files containing direct SpeechRequest calls are identical
  in path and SHA-256 between baseline and root. The test itself is identical,
  SHA-256 `a00eb21cf09eead11a5f8908e717a0d4ff66d63fc75de8d16751e634e55b0418`.

Provisional classification: pre-existing call-site inventory drift. This source
comparison does not claim that ACK policy is correct or that a model run passed;
it only establishes that this task did not introduce the observed site/table
change. Actual exact-baseline execution remains pending.

## Commands prepared; do not run during the full gate

Run only after PM releases the memory constraint. `movb` is the existing isolated
detached worktree at exact baseline `c0858a8000e2ca23b57231edb8f46c643080ad07`.
No checkout of the user's daily runtime is needed.

```powershell
Set-Location C:/Projects/jarvis/movb
git rev-parse HEAD
$env:PYTHONDONTWRITEBYTECODE='1'
& C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest --assert=plain --tb=short -p no:cacheprovider -q tests/unit/test_control_center_timeline_ui.py::test_the_cosmos_theme_knows_every_dock_tool_and_moves_the_pills tests/unit/test_presentation_response_policy.py::test_aucun_site_de_production_ne_laisse_le_modele_nommer_sa_nature_de_parole --junitxml=C:/Projects/jarvis/mov5/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/baseline-shard-01-unknowns.xml
```

Preserve stdout/stderr and JUnit. Compare each baseline failing line/cause with
the two current shard tracebacks; report mismatches instead of assuming them.
No product fix, blanket ignore, known-failure entry or full-suite rerun is
authorized by these notes. PM owns final classification and next actions.
