# Slice execution plan

## Blocking prerequisite
`task_type_unresolved`: no authoritative Workspace Task Type catalog was available during task creation. Slice 00 must resolve exact approved labels/ids/keys and assign a valid Task Type before any implementation Slice is dispatched. Do not invent/default to `code`.

## Order
00 Project Manager readiness gate -> 01 Scene domain contract -> 02 Scene store. Then 03 transport and 04 runtime projection can proceed. 05 renderer depends on 03; 06 brain MCP depends on 01/02/03; 07 artifacts depends on 04/06; 08 interactions depends on 03/05; 09 inspect/screenshot depends on 03/05/06; 10 restart/reconciliation depends on 02/03/04/05; 11 rollout/QA/docs depends on 04-10.

Note (PM, Slice 00): 04 needs 01/02 only; 03 is not required for 04.

## Status
- [x] 00 Project Manager readiness gate — READY (Human waived Task Type gate; Drive left in to-do). See LOG.
- [x] 01 Scene domain contract — APPROVED (c4a7b48, 22bdd2a, 3018cbd)
- [x] 02 Scene store & persistence — APPROVED (see LOG)
- [x] 03 Scene transport — APPROVED (see LOG)
- [x] 04 Runtime topology projection — APPROVED (see LOG)
- [ ] 05 Layered renderer & AutoResolver
- [ ] 06 Brain display MCP
- [ ] 07 Semantic artifacts
- [ ] 08 User interaction & lifecycle
- [ ] 09 Scene inspection & screenshot
- [ ] 10 Restart reconciliation
- [ ] 11 Rollout, quality & docs

## Task done when
Runtime creates real agent stars/links/errors without brain; brain can inspect/manipulate same persistent scene via MCP; grouped artifacts explain completed work; renderer honors layered 2D/pins/intentional overlap; reload/restart preserves state and reconciles truth; completed work stays until user disposition; archive is user-only; legacy Control Center/voice/work behavior remains operational; all QA and Human checks pass.
