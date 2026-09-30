# Reconstructed planning session

> This is a faithful reconstruction of the relevant decisions from the current conversation. It is not a verbatim transcript.

## 1. Why this task exists

The broader Jarvis roadmap includes a meeting mode with continuous transcription and an on-demand assistant. Before that, the user decided to solve the generic tool/MCP layer first so the same capability system can later serve meeting mode and ordinary Jarvis usage.

## 2. Generic external MCP plugins

The user wants a ChatGPT-like plugin experience: add an MCP endpoint, connect/authenticate it, disconnect it, enable or disable it, inspect what it exposes, and let Jarvis use those capabilities. Circuit Toolbox is the first concrete remote MCP to connect:

`https://circoetoolbox-server-production.up.railway.app/mcp`

The system must scale to future MCPs without provider-specific integration code. A Google Drive capability is another desired example. The current Jarvis Drive integration must be audited because it may be a special/legacy server rather than a true generic managed plugin.

## 3. Intent-aware tool discovery

The user explicitly approved a `list_tools(intent)` mechanism and refined its response contract.

The intended interaction is iterative. Example:

1. Jarvis asks `list_tools("envoyer un mail aux personnes concernées")`.
2. It receives the relevant mail tool with enough schema to call it immediately.
3. It realizes the tool needs an email or user id.
4. It calls `list_tools(...)` again with a new intent to discover how to resolve that missing prerequisite.

This repeated discovery loop is a feature, not a failure mode.

The user rejected a normal flow where `list_tools` only returns thin cards and every selected tool requires another `get_tool` call. Instead:

- tools selected/recommended for the current intent include their complete actionable schema/details in the `list_tools` response;
- all other accessible tools remain visible in a compact form so the agent can notice alternatives;
- the compact remainder must be bounded/paginated when the accessible catalog becomes large.

## 4. Agent/subagent scope

The user wants enabled plugin tools to be usable by Jarvis and by delegated subagents. A subagent sent to perform a task should be able to discover and invoke the same enabled external capabilities without asking the user to authenticate again or receiving raw credentials.

The architecture should therefore centralize external MCP sessions and credentials in Jarvis rather than duplicating them in every agent runtime.

## 5. UI direction

The existing MCP area is not to be discarded. It should evolve into one MCP control center with clearly separated internal exposure and external plugins.

External plugins should appear as compact checkable cards/boxes with connection state, enabled state, optional icon/fallback, and a management view. Adding a plugin starts with a URL, then follows the server's auth requirements. OAuth and token/API-key fallback must be supported. Clicking into a plugin should reuse the existing clean tool inspector rather than introduce a second tool viewer.

## 6. Security and lifecycle decisions

Connection/authentication and enablement are separate. Secrets remain outside the Brain/model. Tool ids are namespaced. A plugin can be disabled without forcing re-authentication; disconnect/revoke and removal are separate actions.

## 7. Explicitly deferred

Meeting transcription/presentation mode, plugin marketplace/catalog browsing, per-board/per-agent plugin permission rules, and provider-specific SaaS workflows are not part of this task.
