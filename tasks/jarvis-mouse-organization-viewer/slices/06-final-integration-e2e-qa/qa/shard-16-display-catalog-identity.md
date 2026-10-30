# Shard 16 follow-up: SceneOp does not expand the model-visible catalog

PM requested a bounded check that the six known MCP count/context failures
did not conceal a new model-visible expansion caused by S01's new enum member.

## Actual deterministic comparison

Ran [probe_display_catalog.py](probe_display_catalog.py) in two fresh foreground
Python processes, first with cwd `C:/Projects/jarvis/movb` at exact baseline
`c0858a8000e2ca23b57231edb8f46c643080ad07`, then cwd `C:/Projects/jarvis/mov`
at frozen root `97d56f1144cb721e7c5303f43ff71d291ed1d9bc`. Used
`C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe` and
`PYTHONDONTWRITEBYTECODE=1` for both. The probe inserts its current workdir at
the start of `sys.path`, so the baseline process imports baseline modules,
not the worktree storing the probe. Each process completed with exit 0 in
under two seconds.

The probe calls existing production `list_server_tools('jarvis-display')`,
`describe_tool` and `text_output_schemas`, which instantiate the real FastMCP
registration with `_Inert` tool/prefab backends for introspection only. It
never invokes a tool or starts a server, model, browser, hardware adapter or
network listener/client request.

Retained outputs:
[baseline](baseline-display-catalog.json), [frozen root](root-display-catalog.json).
An assertion-based comparison of their named fields passed:

| Measurement | Both revisions |
| --- | --- |
| Tool count | **21** |
| Production `context_bytes` sum | **40015** |
| Names and order | identical |
| Model-visible names/descriptions/input schemas | identical, 41094 canonical bytes |
| Complete `tools/list` model dumps | identical, 60863 canonical bytes |
| Complete catalog descriptors | identical, 119132 canonical bytes |
| Text output schemas | identical, 12391 canonical bytes |
| `layout_selection` anywhere in described catalog | false |

Canonical JSON uses sorted keys, UTF-8 and compact separators. Identical
SHA-256 values at both revisions:

```text
model_visible:      71fd26fc10de209c95b979c5be93416da686122ab832cb8386211371278b9dc9
full_tools_list:    edf57314b69baea791612b72a9f1097e8f22eceb185438fb3ebcf9625a1ba4d1
descriptors:       5d8df7b47f35ac3408c81b75f1c3f4792ceef555a98307b1041d3800b8420894
text_output_schemas: 06c9d07248ff0ab80dbb2a6791825c7d76b9d502a6e9592107f420baddd7ac54
```

The only added `SceneOp` enum value is `layout_selection`; it does not appear
in any compared tool descriptor. The existing assertions expecting 20 tools
and 39513 bytes already disagree with the actual baseline introspection.

## Source trace and limits

`display_mcp.py`, `display_prefabs.py`, `mcp_catalog.py`, `mcp_tool_meta.py` and
`mcp_results.py` are unchanged from baseline to root. `display_mcp` references
specific named `SceneOp` members when constructing internal commands; it
does not iterate or publish that enum as an input operation field. Its
registered tool arguments use the established explicit signatures and closed
argument structures. The catalog introspects those signatures and shared
metadata; it does not generate tools from `SceneOp`.

Other display text schemas do enumerate established object/actor/state/shape/
relation enums, which is why actual schema outputs were compared as well as
source text. The measured hashes establish that the new enum member did not
change those outputs indirectly.

This is bounded catalog/introspection evidence, not a new AI trace, tool
execution or server API replay. No product, prompt, protocol or registry was
changed, and no additional pytest/baseline/browser campaign was run. The
original canonical shard remains truthfully red with its six known failures.
