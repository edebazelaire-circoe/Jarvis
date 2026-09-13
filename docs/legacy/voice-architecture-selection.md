# Compatibility projection for new voice selection

Introduced by voice-architectures Task02. Old `VoiceArchitecture` values (`legacy`, `continuous_brain`) govern tool authority, prompts, lifecycle and capture. Their meaning is not equivalent to the new Simple architecture. Automatically renaming them would alter user behavior.

`runtime/voice_architecture_config.py::load_voice_architecture` projects absent new settings into `SimpleVoiceConfig`, attaching `LegacyVoiceCompatibility` with old execution mode, model/provider/source and stack options. This is metadata, not a fallback frontend, mock or new runtime path. Existing audio composition remains unchanged. The query API reports unknown models/readiness without claiming support; invalid existing combinations remain preserved for the existing runtime to reject.

Removal condition: explicit architecture switch coordinator (Task17) can snapshot state, close the old frontend, enforce billing cleanup, preserve prompts/tasks and start a validated new profile. Only an explicit completed transition should replace compatibility metadata; retain old settings for rollback until Task20's migration closure decision. Never remove or rewrite custom prompts/inactive profiles as a side effect of config migration.

Regression: `tests/unit/test_voice_architecture_config.py` covers both old modes, source precedence, unknown/missing models, environment-only stack, unchanged settings/prompt objects and versioned round trips. Existing migration/settings tests pass alongside the new suite.
