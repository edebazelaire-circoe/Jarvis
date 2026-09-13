# Task14 parent review

Accepted on 2026-09-13 after implementation and two independent review lanes.

Settings now starts from the Simple, Front Brain or Duplex architecture and
renders its roles and controls from `VoiceCapabilityRegistry`. Model choices,
adapter readiness, account availability, unsupported reasons, reasoning choices
and Duplex idle bounds come from the server projection. The browser contains no
provider/model catalogue or architecture-specific switch.

Persistence is explicit and atomic. An ordinary Save of a legacy or
`continuous_brain` projection does not create `voice_architecture`, so environment
inheritance and compatibility execution remain unchanged. An explicit choice
stores the versioned canonical envelope without compatibility metadata and keeps
legacy fields, inactive profiles, prompts and unknown extensions. Invalid,
incompatible, unavailable, non-finite and malformed selections are rejected
before disk replacement with a stable error code.

Review repaired four material integration defects: projection lists initially
lost their selectability/reason metadata; same-mode activation initially replaced
the current compatible model with the first registry default; malformed optional
Google catalog records and malformed on-disk catalog envelopes could break the
whole Settings response; one post-projection rejection lacked the normal
sanitized journal event. Permanent HTTP, Node-executed UI and adversarial cache
tests cover these cases. Save never stops or replaces a running frontend. The UI
states that the saved configuration is read after Voice runtime restart; Task17
owns live replacement.

Parent focused gate: **346 passed**, warnings as errors. Final Task14 probes after
the last diagnostics repair: **59 passed**. Full release: **2996 passed, 5 skipped
in 332.31 seconds**; release verification passed. The skipped cases are the three
credential-gated provider smokes plus two platform-only tests. No provider,
billable session or audio device was used.
