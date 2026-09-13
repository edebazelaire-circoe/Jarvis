# Task17 — safe architecture/model switching evidence

Accepted 2026-09-13.

Task17 adds a phase-driven switch coordinator across Settings, Voice, Core and
the supervisor. Voice snapshots canonical conversation and normalized work
state before stopping the old frontend with `VoiceStopReason.SWITCH`. It blocks
replacement on a pending local close, unresolved GPT-Live lease, or unreadable
Core Live status. Confirmed teardown produces a metadata-only handoff and clean
Voice exit; the supervisor restarts it without charging the crash-loop budget.

The replacement keeps the same Core conversation ID. Its first session
re-fetches bounded canonical user/actually-spoken history and active task
summaries. Back-brain jobs remain owned by Core. Provider-hidden state is not
migrated and the spoken ledger is not rewritten. Same-architecture model
changes take the identical new-session path. Correlated traces include
architecture/model IDs and prompt revisions/fingerprints without prompt text.

Verification:

- Focused switch/composition/supervisor gate: **170 passed**.
- Broad Voice/Live/Control Center/supervisor gate: **1123 passed, 1830 deselected**.
- First release run found one compatibility regression: an intentionally
  incomplete Gemini projection was treated as a runnable switch target. The
  coordinator now leaves model-less compatibility settings inspectable without
  stopping Voice; its direct 63-test repair gate passed.
- Final release: **3075 passed, 5 skipped in 320.42 s**; all release checks passed.
- Python compilation, Node syntax validation and `git diff --check` passed.

The synthetic sequence covers Simple -> Front Brain -> Duplex -> Simple and a
same-architecture model restart. No provider, billable session or audio device
was used; real-provider reconnect quality remains a Task20 benchmark concern.
