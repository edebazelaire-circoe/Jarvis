# Overview

## Goal

Make external MCP servers first-class managed Jarvis plugins and give Jarvis a scalable, intent-aware way to discover only the tools it needs while retaining a bounded awareness of the rest.

## Scope

This task owns five connected capabilities:

1. persistent plugin definitions and secure credential references;
2. generic remote MCP connection/auth/session management;
3. dynamic external tool ingestion into the existing canonical MCP catalog;
4. an agent-facing `list_tools(intent)` + generic execution gateway usable repeatedly by Brain and subagents;
5. a Control Center plugin-management UX built into the existing MCP surface.

## Mental model

```text
Control Center MCP UI
        |
        v
Plugin Registry ---- Credential Vault
        |                  |
        v                  |
Remote MCP Connection Manager
        |
        v
Canonical MCP Catalog / Global Tool Registry
        |
        +--> list_tools(intent) --> recommended FULL descriptors
        |                         + compact remainder
        |
        +--> call_tool(plugin.tool, args)
                 |
                 v
           remote MCP server

Brain + delegated subagents use the stable Jarvis gateway, not plugin secrets.
```

## Non-goals

- Meeting-mode transcription or presentation UI.
- A public plugin marketplace/store.
- Per-board or per-agent plugin enablement policy in V1.
- MCP Apps embedded UI rendering.
- Rewriting every native Jarvis MCP tool to go through the generic gateway unless required for a coherent contract.
- Hard-coding Google Drive, Circuit Toolbox, Slack, or other providers into the generic runtime.
