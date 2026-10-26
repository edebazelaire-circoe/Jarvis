# I-005 — Slice 04 leftovers (QA 2026-10-26)

Details and evidence: `slices/04-agent-confinement-capability-policy/qa/code-review.md` (m1-m7) and the Slice 04 entries of `LOG.md` (runtime QA, rework). M1, m2, m5 and m6 are fixed in the rework; everything below is open and non-blocking (the launch confinement holds whatever the texts say).

1. **Runtime QA**: `POST /api/settings {"self_development":{"enabled":true}}` is accepted with HTTP 200 in `presentation` and read back as `true`, while the service stays closed (`self_development_unavailable_in_edition`). The setting should be refused (or shown locked) like the permission mode.
2. **Runtime QA**: an instruction hidden in a document is ignored, but the user is not told right away. The brain should say at once that the document carried an instruction it did not follow.
3. **Runtime QA**: the author drafts the whole presentation (about $1) before discovering `presentation_studio_engine_unavailable`. Check the engine state (`remotion_status`) before delegating the author.
4. m1: no enforcement test on four surfaces (mutations survived): flat `claude_permission_mode` lock (`control_center.py`), Codex refusal and "unavailable" choice of the Architecture page (`brain_config.py`), codex→claude mapping of the Control Center, Codex console refusal (`codex_local.py`) and self-dev `deploy` guard; no HTTP test of `GET /api/settings` → `agent_capabilities`.
5. m3: sending the imposed `dontAsk` back is accepted and **stored** in `agent_cli_settings` (`control_center.py`), against the `_mirror_legacy` comment. No effect in `presentation`.
6. m4: the confined launch does not require a native argv (unlike the restricted profiles, `claude_local.py`). `claude.EXE` is native today; nothing guarantees it for a `.cmd`.
7. m7: mixed register: the confined prompt sections say "vous", the base `BRAIN_SYSTEM_PROMPT` says "tu" (older debt). The Interviewer's question in the real trace said "toi" (relayed by the brain with "vous").
8. Rework leftovers (texts, no enforcement effect):
   - `[code] [coder] [relais] Suite` in `HANDOFF_IMPOSSIBLE_REASON` (`routing_hook.py`) and `[code] [qa]` in the relation error hint `qa_reviewer_role` (`relation_runtime.py`): refusal messages, not yet derived from the manifest.
   - The charter (`AGENT_TASK_CHARTER`) still says "lis le code, l'historique git"; the confined `subagent_note()` appended after it tells the sub-agent this only goes through Jarvis tools.
   - The `research` role's `when_relevant` ("la mémoire ou le dépôt") still names the repository, unreadable in `presentation`.
   - `[presentation-author]` now runs under the `general` profile in `presentation` (`code` is not offered): model routing follows `general`. Check the author's quality/model on a real run (Slice 09/10).
9. Real trace cost: the case B run cost $1.43 (budget $1.00). The three Opus sub-agents (one web research with 40 searches/fetches) are billed only when they finish; a budget guard cannot stop them between two brain turns. Use a cheaper routing for future QA runs.
