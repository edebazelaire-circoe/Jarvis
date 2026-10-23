# 00 - Overview

## Goal

Replace the old "Agents & modeles" concept with a single **Architecture & Agents** Settings page that exposes the real Jarvis brain topology and the real sub-agent routing configuration in an understandable product model.

## Scope

### In scope

- Two-tab page: `Architecture` and `Sous-agents`.
- Real, editable 2D architecture graph.
- Audio input/output endpoints.
- Current real brains shown from runtime data.
- Generic future brain/node support.
- Semantic connection types, mutability and runtime enforcement.
- Contextual floating brain configuration popup.
- Brain model/provider/mission/instructions/delegation settings.
- Global sub-agent role/model/harness/fallback configuration.
- Reuse/migration of current role registry, routing and model catalog.
- Legacy UI cleanup and Advanced routing for technical controls.
- Visual implementation consistent with the approved neon references.

### Out of scope

- Personality/voice style settings (tone, politeness, humor, response length, verbosity).
- Inventing future brains in the default runtime diagram.
- A permanent `Brains` tab.
- A decorative central Jarvis hub with arbitrary links.
- A browser-owned duplicate model/provider inventory.
- General CLI installation, path, sandbox/permission, diagnostic or compatibility controls in the normal page.
- Preset management, flow testing and architecture analytics unless Slice 00 proves an existing supported runtime capability makes them necessary. The reference images may show such widgets, but they are not locked requirements.

## Mental model

Three independent responsibilities must remain separate:

1. **Topology** - who can communicate with whom, through what typed connection, and whether the edge is mutable.
2. **Brain policy** - what a brain is for and how aggressively it delegates.
3. **Sub-agent policy** - for a requested role, which available harness/model candidates are preferred and how fallback works.

This separation is the core architecture and the core UI information architecture.
