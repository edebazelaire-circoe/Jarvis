# Slice execution order

1. `00-project-manager` — readiness gate and freshness reconciliation
2. `01-plugin-and-tool-discovery-contracts` — freeze canonical contracts/migration plan
3. `02-plugin-registry-and-credential-vault` — persistence and secret boundary
4. `03-remote-mcp-connection-manager` — transport + auth + discovery runtime
5. `04-intent-tool-registry-and-gateway` — dynamic catalog + `list_tools(intent)` + generic invocation
6. `05-agent-subagent-capability-propagation` — Claude/Codex/subagent access
7. `06-control-center-plugin-manager-ui` — plugin cards and management flows in existing MCP surface
8. `07-circoe-drive-integration-validation` — live Circuit Toolbox proof + Drive migration classification
9. `08-release-qa-and-documentation` — final regression/context/security/docs cleanup

Do not dispatch any implementation Slice until Slice 00 records `READY`.
