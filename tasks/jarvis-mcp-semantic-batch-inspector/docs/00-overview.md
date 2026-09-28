# Overview


## Goal
Make Jarvis MCP intent-oriented rather than object-loop-oriented, and expose the resulting capability contract in a clean human inspector.


## Mental model
`human/UI/gesture/brain intent -> canonical SceneSelection -> one semantic scene command -> Core resolves + validates + applies -> one scene revision/patch`.


For documentation: `canonical MCP contract -> FastMCP exposure + Control Center inspector`, guarded by parity tests.


## In scope
- canonical `SceneSelection`;
- canonical constellation resolver including runtime signal-owner fallback;
- atomic selection update/translate/pin/archive;
- semantic `jarvis-display` migration;
- typed MCP input/output contracts and catalog metadata;
- Control Center read-only catalog API;
- dedicated MCP inspector UI;
- tests, docs, migration/deprecation and real runtime traces.


## Out of scope
- new Bare Hands gesture bindings;
- arbitrary MCP execution playground;
- full boolean selector DSL;
- one tool per setting;
- arbitrary probing of unknown third-party MCP servers.