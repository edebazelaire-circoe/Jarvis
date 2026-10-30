# Independent Architecture readiness conformance rework

Reviewed PM integration `bddc1c95` (source `f8673df1`), merged into QA at
`924d19d0`. Product/shared driver/OPEN remain unchanged. No product edits by QA.

The two affected plans now wait for readyState complete, registered Settings/
Personalization owners and the actual Settings button rather than existence
before handler initialization. `settleMs:1` makes this explicit predicate carry
readiness instead of hiding a longer sleep. Unaffected plans retain OPEN.
Runtime/CLI TOUR polls actual SET.clis and both command/permission fields within
the existing standard5-second browser wait budget explicitly authorized by PM.
It does not retry the click, invent missing fields or change a product/Core/
process deadline. On timeout the original assertions still evaluate actual
state, now with rt included as failure detail. The original assertion
conditions and all architecture/Core/subagent behavior checks remain intact.

Independently ran only the two exact modified cases, one direct pytest batch:
**2 passed in56.29seconds**, `pending-reworked-architecture.xml`, with log,
captures and exact command/PID/revision manifest beside it. No other six-plus
Settings cases or full file were repeated. No model/hardware/user runtime.

Recommend PM accept this bounded test-only conformance correction. Earlier
unmodified baseline/current two-case passes remain separate evidence and do
not fabricate a baseline failure. Original full-gate reds are retained; this
rework addresses their source-established readiness assumptions without
claiming their exact original timing was measured.
