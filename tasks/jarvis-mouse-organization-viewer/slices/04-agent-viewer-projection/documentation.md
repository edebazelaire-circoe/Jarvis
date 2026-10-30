# Audited implementation context

Read ../00-project-manager/READINESS.md for source evidence, routing fallback, boundaries and QA tiers. Canonical architecture starts at docs/ARCHITECTURE.md (repository root), docs/scene-selection-batch.md, docs/scene-model.md, docs/mission-history.md, docs/agent-orchestration.md and docs/chat.md. Existing source is authoritative over planning-time path guesses. No duplicate geometry, prefab renderer, fullscreen state machine, status owner or communication bus.

Environment: work only in assigned isolated worktree, use C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe for pytest with working directory set to worktree (pyproject pythonpath=. ensures local imports). Node available. Tests foreground, small focused batches; no full suite before S06. Do not launch/stop user's runtime. Isolated ControlCenter harnesses and own data/ports are permitted. Read CLAUDE.md. Load caveman, coding-guideline, ponytail, error-handling; frontend additionally impeccable. Implementer reports in IMPLEMENTATION.md; independent reviewer writes qa/. Prefix implementation commits S<n>: with Slice number. Do not commit other Slice files.

Exact lifecycle: remote folder current; final Human acceptance pending. No merge to main/push main/cleanup local handoff.

## Read seams verified during readiness
- `GET /api/work`: CoreWorkView public `{source:'core', core_reachable, store_id, revision, items, updated_at, stale, error}`. Only Work State fields, not `/api/agent/tasks` diagnostics. Source/external_id identity exact; no title join.
- `GET /api/missions/work/{source}/{external_id}` then mission tree reads: `jarvis/runtime/mission_view.py`, `jarvis/protocol/mission_routes.py`, `InstanceView` in domain/mission_history.py. Mission status never overrides missing Work State. Avoid forwarding whole mission/instance `declaration` structures: explicitly whitelist public objective/role/identity and summary facts.
- Artifacts: scene relations and registry IDs only; `registry_artifact_id`/`artifact_id` and validated scene relations. `GET /api/workspace/artifacts` is Board membership, not proof of authorship.
- Stop: POST `/api/jobs/cancel` with `{source,external_id}`; backend strictly only source job. CLI sub-agents have disabled Stop with explicit reason, no invented cancel mechanism. Actual outcome/refusal must survive adapter.
- Ask: main `JarvisChat.open` exists, direct question/prefill API absent. Emit target identity/main-chat prefill descriptor; S05 adds minimal canonical chat prefill seam, never sends automatically.
- Existing Work State has no future public steps. Keep `published_plan:null` and actual children only; no prompt/provider changes required.
- Prefer new bounded JS composition of existing public reads + pure projector if that is smallest. New Python endpoint is optional, not a requirement. S05 inserts modules into served page; avoid shared host insertion here.

