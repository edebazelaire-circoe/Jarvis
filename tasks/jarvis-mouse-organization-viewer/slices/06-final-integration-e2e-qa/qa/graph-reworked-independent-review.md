# Independent dense-graph correction review and final QA recommendation

**Recommendation: accept the bounded test-only graph correction and present
S06 for Human review.** The unique modified original test passes all three
scenarios in **19.67seconds**. This is a recommendation to PM, not final task
approval or an all-green suite claim.

## Independent source review

Candidate `2fc46551f708970b62c2d6ca8e164419743a44f3`, integrated as `9f39e6ff`,
changes only the target graph test and its QA note. Reviewed current QA merge
revision is `d6b5a120fec4d6f1d50492b06f83ee98e27e1133`.

The200% plan activates the existing rail close control only when its host is
visible. That button calls the existing owner
`toggle(false,{restoreFocus:true})`: ordinary save/render/display publication
and focus handling remain canonical. The test does not set hidden/style/storage
or owner state itself. It then asserts host hidden and owner.visiblefalse.

One ready/visible/viewport/fractional-center EFP observation precedes the
unchanged real CDP click. It is an assertion, not a favorable-orbit wait,
retry, frozen animation or replacement click. Moving-target failure between
observation and native dispatch remains possible and would still fail the
original Board assertion. Shared driver and existing eight-second WAIT_BOARD
are unchanged. Independent AST inspection retains all **eight original
assertion predicates**, adds two precondition assertions and verifies
WAIT_BOARD AST identity with exact baselinec085. The other two plans are
unchanged in the reviewed diff.

## One actual run and retained evidence

`run_graph_reworked.py` refuses an existing manifest, starts only this exact
pytest case, and retains its foreground log/JUnit and unique sandbox. The
QA output plugin saves the original Node process stdout after it exits and
before pytest asserts. It adds zero CDP calls and changes neither browser
harness nor plan. Its metadata records the actual harness hash and empty
Node stderr. There was no second run.

Measured200% facts:

- `folded_rail={present:true,hidden:true,visible:false}`.
- Document ready; mark present/visible; fractional center
  (460.9390259,191.1654816) is in720x450viewport; EFP is BUTTON `rel_comm`.
- Original native click opens communication Board `rel_comm`;
  `waitBoard=0`, `open=true`, rectangle x202..702/y64..382.
- Hostile message remains text (`imgs=0`, `xss=false`), title receives focus.
- All three scenarios have no Runtime/error-console entries. Original dense
  layout, forced-colour and Cosmos assertions pass.

Visual inspection of the retained dense Board, forced-colour and Cosmos PNGs
confirms the measured open Board, retracted rail, visible graph/link treatments
and existing theme surfaces. This is local UI regression evidence using the
original fetch fixture, not a real-model/Core execution claim.

Artifacts: `graph-reworked.log`, `graph-reworked.xml`,
`graph-reworked-run.json`, `graph-reworked-raw.json` and metadata;
`graph-reworked-captures/` contains all four original screenshots. QA scripts
are `run_graph_reworked.py` and `graph_result_retention_plugin.py`.

## Final acceptance bounds

The correction is supported by the separately retained exact-baseline natural
occlusion witness (`daef90ef`, `graph-baseline-occlusion-review.md`): old rail
interception can produce a null Board under the unchanged native click/wait.
That witness does **not** establish the actual event target of either historical
current failure; those red logs/raw reports remain unchanged. The successful
corrected run establishes the graph navigation contract with an explicit
unrelated-panel precondition; it does not retroactively turn earlier reds green.

My prior independent S05 actual Core/SQLite/browser acceptance, chat freshness
recheck, S06 F2 arrival-order recheck, Architecture readiness review and the
bounded baseline comparisons remain their separate evidence. The S03 shell
and Escape bridge were authored by me and accepted independently by PM/S2;
this report does not self-certify those changes. No additional product blocker
was found in the assigned final review and rechecks.

Root's broad-gate result remains25378passed/43failed/162skipped at its frozen
revision, with historical debt and PM source/evidence dispositions retained.
No full-suite-green or complete original-failure-cause claim is made. The
real-model request remains quota-limited evidence where previously recorded;
seeded Work State is not presented as model-driven execution. PM still owns
final dispositions and the bounded isolated Human preview/review; no main merge,
live-user runtime change or Drive completion follows from this QA commit.
