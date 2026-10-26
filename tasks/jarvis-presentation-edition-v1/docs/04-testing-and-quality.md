# Testing and quality

## Mandatory QA composition
Every implemented Slice gets `qa-verification`.

Add:
- `code-review` for code changes;
- `runtime-validation` for user-visible or runtime behavior;
- `agent-trace-analysis` with real trace evidence for changes to prompts, tools, routing, agent capability exposure, CLI launch/runtime or sub-agent behavior.

The Project Manager owns the final decision after QA. A regression introduced by the Slice is blocking and cannot be moved to `Issues/`.

## Human validation doctrine
Human validation occurs only after machine validation is exhausted. Human checks focus on judgments a machine cannot fully establish: visual quality, physical audio behavior, clean-machine installer experience, and whether the constrained product still feels usable.

## Automated release gates expected by the end
At minimum:
- focused unit/integration tests for each changed contract;
- full relevant Presentation/Board/storage/security suites;
- product-edition negative tests proving unavailable Board kinds fail at Core/API/MCP, not just UI;
- path/security tests proving internal writes cannot escape the product root;
- agent capability tests and real traces proving general shell/write tools are absent in Presentation product sessions/sub-agents;
- export tests proving outputs are copies and internal state survives export deletion;
- private runtime probes for Python/Node/Remotion/FFmpeg;
- installer smoke on clean Windows environment;
- upgrade/migration/restart/crash tests;
- release artifact integrity/hash checks;
- a CI pipeline that runs against the same build inputs distributed to users.

## Physical workstation acceptance
The final V1 must explicitly exercise on target Windows hardware:
- install with no Git/system Python/system Node/system FFmpeg prerequisites;
- first-run connector setup;
- microphone/speaker and Presentation listening/addressed-turn behavior if voice is enabled in the product build;
- create/import/research/author/preview/edit/play/export a Presentation;
- CIRCOE Mail/Calendar and Google Drive access;
- IGuard when its contract is available;
- crash/restart and interrupted render recovery;
- attempted write outside allowed internal/export boundaries;
- update over an existing profile with data preservation.

## Security regression examples
Automate or runtime-test attempts equivalent to:
- write `C:\Users\<user>\Desktop\outside.txt` through the brain;
- path traversal from Board memory/export APIs;
- symlink/junction escape from internal roots;
- arbitrary PowerShell/Bash execution from a product brain turn;
- connector data attempting to instruct the agent to exfiltrate/write secrets.

Expected outcome is explicit refusal/capability absence, not prompt-level politeness while the tool remains available.

## CI rule
Do not call a release green because tests passed in a developer checkout if the installer was assembled differently. The packaged artifact must be built from pinned inputs and receive its own smoke/health validation.
