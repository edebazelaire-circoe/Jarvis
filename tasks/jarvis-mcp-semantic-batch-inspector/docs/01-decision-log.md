# Decision log


- D01: user intent is the unit of API design.
- D02: a true batch is a domain/Core batch, not merely one MCP wrapper around N mutations.
- D03: selection is a domain concept.
- D04: canonical constellation includes active explicit relations as undirected edges plus virtual runtime-signal owner edges using the same `signal_owners` fallback semantics.
- D05: no arbitrary boolean query language in this task; add only bounded selectors required by real intents.
- D06: moving a group uses relative `dx/dy` and one common effective delta so the figure remains rigid.
- D07: generic settings tools stay generic. Human inspector may show setting-level capabilities without adding wire tools.
- D08: inspector metadata comes from actual MCP contracts or shared descriptors consumed by FastMCP, with parity tests.
- D09: inspector/catalog helpers do not inflate model-visible tool context by default.
- D10: inspector is human-first: compact by default, expandable detail, readable parameters and output schema, raw JSON secondary only.
- D11: add `MCP` to the existing right-side Control Center dock and open a dedicated surface.
- D12: user example tool names are illustrative human semantics, not mandatory wire aliases.
- D13: no silent tool-count growth; semantic tools should replace redundant granular ones.