# Real execution infrastructure probe — quota blocked

2026-10-30. This is infrastructure evidence, **not S05 acceptance**. The
implementation was still unintegrated. One actual Claude CLI request was made;
no mocked result, fallback provider, retry or completed model response was used.

The existing user CLI setting is `sonnet`. Restricted mode ignores user
settings, so the harness explicitly replayed that existing alias. The CLI init
reported `claude-sonnet-5-5`. Tools and MCP were both empty; observed tool uses
were zero. Skills/commands and hooks were disabled for this disposable request.
The fixed request only asks for `QA_OK`, with no tools. Budget was bounded at
$0.10 and the owned process had a 55-second deadline. Reported charge was $0.

The provider refused the request:

> You've hit your weekly limit · resets Oct 31, 7pm (Europe/Paris)

CLI exit code was 1; `result.is_error` was true even though `result.subtype`
was `success`. The QA worker checks both flags, so Core settled the job as
`failed`. The real production agent-detail reader, using actual Control Center
HTTP and Core Work State transports, observed `running` then `failed`, with an
end timestamp and canonical Stop changing from enabled to disabled. This was a
real attempted execution, not seeded running/terminal facts.

The ad-hoc QA job had no mission/instance declaration. The canonical mission
lookup therefore returned HTTP404, and the reader correctly marked its model
`degraded` while retaining the authoritative Work State status. No objective,
published plan, findings, counters or model-success result was invented.

Evidence is [real-execution.json](real-execution.json). It contains the public
reader results and an allowlist of CLI metadata/result fields. Raw stream,
provider trace, thinking and prompt were never exported into the view model or
persisted as evidence. No tool calls, routing recovery or retries occurred.
There is no successful inference trace to analyze; model execution validation
remains unavailable until quota resets. No product optimization is inferred
from this account-level limit.

The opt-in [real_execution.py](real_execution.py) uses the existing isolated
`CoreProcess` fixture and the canonical `JobService` worker seam. Core data,
project and Control Center runtime live in one temporary directory; Core and
HTTP use ephemeral ports. The Control Center app is served directly without
starting the user's runtime. Python's event loop remains active while the
Node reader performs public HTTP reads. Cleanup addresses only exact subprocess
handles and the owned fixture; no process-name or process-tree termination.

Run explicitly from the worktree with the main venv interpreter:

```powershell
C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe tasks/jarvis-mouse-organization-viewer/slices/05-scene-integration-organize-viewer/qa/real_execution.py --execute
```

The recorded run returned exit1 as expected for the provider failure. No full
suite or second paid request was run. This evidence does not replace the S05
browser/interaction tests or independently reviewed final code.
