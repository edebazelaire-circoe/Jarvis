# Issue — raw trace readable through DNS rebinding (`/api/trace`, `/api/errors`)

Found by Slice 04 QA (2026-09-16), pre-existing, outside this task's scope.

- The Control Center origin guard only protects mutating methods on existing routes. `GET /api/trace` and `GET /api/errors` with `Host: evil.example` return 200.
- These routes serve raw `runtime/trace.jsonl` lines: spoken text in `message`, `agent.event` provider stream events (including thinking blocks), raw tool arguments.
- A DNS-rebinding page in the user's browser could therefore read what the conversation drill-down deliberately redacts.
- Slice 04 applies an exact loopback Host check (+ Origin / `Sec-Fetch-Site`) to `/api/conversations...` only.
- Recommended separate fix: apply the same Host guard to every `/api` read route (the server only binds 127.0.0.1, so legitimate clients always send a loopback Host), with a regression test over all registered GET routes.
