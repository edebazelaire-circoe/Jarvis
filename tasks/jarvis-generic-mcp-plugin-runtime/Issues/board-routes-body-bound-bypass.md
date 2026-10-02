# Board relay: request body bound bypassed by a chunked body

`jarvis/runtime/board_routes.py` `BoardSessionRoutes._read_body` bounds a relayed body with a single
`request.content.read(MAX_PROXY_BODY_BYTES + 1)`. aiohttp's `read(n)` returns what has arrived, not
necessarily `n` bytes, so a body sent in chunks (no `Content-Length`) passes the 128 KiB check with a
partial read and the rest is silently dropped before relaying to Core. Core still bounds its own bodies, so
the impact is a truncated (malformed) relay rather than an oversized one. Found 2026-09-30 by the Slice 06
implementer while testing the plugin relay, whose `mcp_plugin_routes.py` reads in a bounded loop and has a
chunked-body test (`test_an_oversized_chunked_body_without_length_is_refused_too`). Suggested fix: the same
loop in `board_routes.py` plus the same test. Out of Slice 06 scope (Boards).
