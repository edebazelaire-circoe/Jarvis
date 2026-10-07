# Issue 003: the Control Center serves sensitive reads to any local process without a token

Found by the Slice 06/07 security re-verification on 2026-10-06. This predates the task.

## The gap

Core (`127.77.0.1:17653`) requires a Bearer token on every route. The Control Center (`127.0.0.1:17654`) has no token: it relies on Origin, Host and `Sec-Fetch-Site` checks, and a non-browser client passes all three. The following are therefore readable by any local process:

- `GET /api/trace`
- `/api/errors`
- `/api/agent/transcript`
- `/api/settings`
- `/api/conversations/*`

## Why it matters for Presentation

Preparation sub-agents hold WebFetch, and room speech or a fetched page can steer them. Today the only barrier is the CLI's WebFetch behaviour: it upgrades `http://` to `https://`, so the plain-HTTP JARVIS servers answer with a TLS error. QA verified this with a real probe. That barrier is CLI behaviour, not something JARVIS controls.

## Suggested hardening

- Put a token, or the Core token, on the Control Center's sensitive read routes.
- Refuse WebFetch to loopback and private addresses for `presentation_preparation`.
