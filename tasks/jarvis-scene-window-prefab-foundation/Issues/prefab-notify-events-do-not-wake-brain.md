# Notify events don't wake the brain.

Found by: Slice 00 audit (2026-10-03). Status: open.

They wait for the next user turn. A user action meant to trigger JARVIS (for example "explain this row") needs a wake policy like `WorkAttentionPolicy` (rate-limited, never speaks by itself). Follow-up.
