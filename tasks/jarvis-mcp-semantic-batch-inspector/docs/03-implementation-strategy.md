# Implementation strategy


1. Freeze contracts.
2. Move selection/constellation semantics into domain with parity fixtures.
3. Add atomic selection scene operations.
4. Build canonical MCP catalog and typed results.
5. Migrate `jarvis-display` off per-object fan-out and rationalize the surface.
6. Add read-only Control Center catalog API.
7. Build MCP inspector UI.
8. Run runtime trace, context-budget, visual and regression QA, then clean stale docs/aliases.


Compatibility: inventory old tool-name references before removal. Temporary aliases require explicit deprecation and removal conditions and must not silently grow the final tool surface.


Likely touch points: `jarvis/domain/scene.py` or adjacent selection module, scene wire/Core store path, `display_mcp.py`, `settings_mcp.py`, `barehands_mcp.py`, `claude_local.py` for exposure status if needed, `control_center.py`, `control_center.html`, new `control_center_mcp_*.js`, scene interaction JS parity tests, MCP/scene tests, MCP docs.