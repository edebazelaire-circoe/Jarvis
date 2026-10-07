# A base-edit confirmation typed outside Core's intake never witnesses.

Found by: Slice 07 real traces (scenario c2), recorded by Slice 09 (2026-10-03). Status: open — by design, needs a product decision.

The base-edit gate (`PrefabService.edit_base`, `jarvis/core/prefab_witness.py`) accepts a quote only if it is found in
a `user.transcript.accepted` Conversation Event of actor `user` from the last 30 minutes. Turns admitted by Core (voice
admission, `POST /v1/conversations/{id}/brain-turns`) produce that event; a turn posted straight to the Control Center (`POST /api/agent/ask`, panel,
legacy gateway) does not. In S07 c2 the user really confirmed in such a turn and the gate refused twice
(`base_edit_unconfirmed`, `core.prefab.witness_lookup {found: false}`), nothing was written — correct per contract,
surprising for a user who typed the request.

For the Human checks (HV-PREFAB-LIBRARY-01, HV-PREFAB-E2E-01): **the base-edit request must be spoken (or entered
through a path Core records)**. If a typed path must be able to edit a base, that path has to record the user turn in
Conversation Events first; the gate itself must not be weakened. Documented in `docs/prefabs.md` › *Known limitations*.
