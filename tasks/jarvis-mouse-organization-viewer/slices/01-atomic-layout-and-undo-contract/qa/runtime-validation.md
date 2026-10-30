# S01 independent runtime evidence

Sandbox only: existing `CoreProcess` pytest fixture creates real SQLite data under its temporary directory and serves authenticated `LocalProtocolServer` on dynamically reserved loopback ports. Control Center relay runs through `aiohttp` TestServer. Nothing targets or controls the user's Jarvis runtime/data.

Executed the four `tests/integration/test_scene_layout_transport.py` scenarios plus independent `qa/test_adversarial.py`:

1. Two distinct target geometries + compares + pin → one revision, two patch operations; repeating stale compare → `invalid/geometry_changed`, no writes.
2. Control Center refuses actor spoof (`brain`, HTTP403), uses `user` when actor omitted, returns `patch_omitted`, subsequent patch polling delivers both geometries and pins.
3. Invalid geometry or selection mismatch → HTTP400; runtime actor → HTTP403; snapshot preserved.
4. Oversized compared layout → HTTP413, no chunking or snapshot change.
5. Independent persistence scenario: seed two notes; apply compared layout; stop/start that isolated Core; exact stored snapshot returns; compare-based geometry undo succeeds in one next revision and preserves pins; replay refuses with no revision change.

Seven tests passed (three independent probes + four existing protocol scenarios). The independent later-stale-member probe checks all-or-nothing behavior even when an earlier valid member would otherwise move and become pinned. Target payload injection probe checks strict whitelist.

No browser organization/undo UI exists in S01; those runtime user journeys remain S05/S06 requirements. No external model tested because this change introduces no model/agent behavior. Findings and mutation details: code-review.md and mutation-results.json.
