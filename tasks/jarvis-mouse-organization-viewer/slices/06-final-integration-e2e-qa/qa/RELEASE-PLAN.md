# Final release execution

PM accepted S01–S05 machine QA. Human acceptance is pending. Integration is isolated in `C:/Projects/jarvis/mov`, branch `task/jarvis-mouse-organization-viewer`; the daily checkout and runtime remain untouched.

Fresh `origin/main` is `c0858a8000e2ca23b57231edb8f46c643080ad07` (fetch2026-10-30); it is the task ancestor. No drift to merge at this checkpoint. S06 narrowly resolves the source-test comment false positive, removes the repaired group-drag known-failure entry and adds the queued selected-layout schematic before the one complete suite pass.

Use the canonical `scripts/release_test_gate.py --suite all --shard K/20 --report …` for K1..20, sequentially, with `PYTEST_ADDOPTS=--assert=plain --tb=short`. Preserve each log and verdict. A red verdict remains red: classify unknown/stale/unseen/session results, reproduce unexplained failures against the detached exact baseline `C:/Projects/jarvis/movb`, and send feature regressions to the owning Slice. Do not add blanket ignores or repeat the whole suite unnecessarily.

Then run `scripts/verify_release.py`, diff whitespace checks, independent review, and one bounded real browser coexistence check for viewer/fullscreen/panels. Earlier independent input, provider, two-theme/reduced-motion/200% and actual Core/SQLite evidence remains valid unless the final diff affects it.

The real CLI execution attempt exhausted the provider weekly quota. Its actual running→failed public state is recorded in S05; successful model inference is unverified. This feature changed no prompts/provider execution path. No paid retry or silent provider fallback is planned.

After machine gates converge, start the prepared bounded preview helper on unique sandbox data/ports, record the observed review URL/PID/expiry, and prepare the closeout with actual counts and remaining limits. No main merge, Drive done move, branch deletion or handoff cleanup before explicit Human acceptance under `handle-task`.
