# 05 - Security threat model

## Security posture V1

Prototype local, single user, deny-by-default. Not a hardened enterprise agent.

## Assets to protect

- OpenAI API key ;
- microphone/camera access ;
- local personal memory ;
- notes displayed on the board ;
- ability to modify files ;
- conversation content.

## Primary threats

### T1 - Remote content executes in camera page

Mitigation: no runtime CDN. Vendor MediaPipe/Three.js/WASM/model, add CSP, verify asset hashes at build/update time.

### T2 - Local webpage calls Barehands command API

Mitigation: per-launch random session token, require token for mutating endpoints, SameSite/origin checks where practical, bind loopback only.

### T3 - Prompt injection triggers machine action

Mitigation: no shell tool. Explicit action registry and ActionBroker. External content cannot create new tool kinds.

### T4 - False spoken approval

Mitigation V1: push-to-talk only. Confirmation applies only to an active pending action and exact normalized approvals. Destructive/high-impact actions are not implemented in V1.

### T5 - Secrets leak into browser

Mitigation: browser never receives provider API keys. Provider calls happen in backend process only.

### T6 - Sensitive logs accumulate

Mitigation: content logging false by default, bounded rotating diagnostics, no raw audio persistence unless explicit debug flag is enabled.

### T7 - Path traversal

Mitigation: canonical `resolve()` and root containment checks for memory and media. Tests for `..`, symlinks, URL encoding.

### T8 - Upstream supply-chain change

Mitigation: pin exact commits, vendor critical JS assets, document checksums, update manually after review.

## Action policy V1

Allowed without confirmation:

- read memory ;
- search memory ;
- read board state ;
- present ephemeral card on board.

Requires confirmation:

- append/update memory note ;
- remove an ephemeral board item if persistence is later added.

Forbidden in V1:

- arbitrary shell ;
- arbitrary filesystem write ;
- delete files ;
- send email/message ;
- browser automation ;
- install/update software ;
- access credentials.

## License boundary

Barehands, ai-visualizer and backtalk are AGPL-licensed upstream projects. Before copying or modifying source into a proprietary codebase, preserve license obligations and obtain legal review if the target distribution model is closed-source. Prefer explicit third-party boundaries and record exact provenance.
