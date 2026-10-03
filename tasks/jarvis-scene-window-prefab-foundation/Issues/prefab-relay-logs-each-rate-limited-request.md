# The Control Center relay logs every rate-limited prefab event as a warning.

Found by: Slice 09 stress (2026-10-03). Status: open — minor.

During a 200-event flood, Core logged one `core.prefab.event_rate_limited` warning and one end (after the S09 fix,
`cdab695`), but the Control Center relay (`jarvis/runtime/prefab_relay.py`, `prefab.request.relayed`) logged one
**warning per 429** (150 lines). Per-request relay logging is the relay's convention and no error is raised, so the
journal stays readable, but a stuck frame or a hostile page could fill it. Option: log 429 `rate_limited` relays at
info or count them per burst like Core.
