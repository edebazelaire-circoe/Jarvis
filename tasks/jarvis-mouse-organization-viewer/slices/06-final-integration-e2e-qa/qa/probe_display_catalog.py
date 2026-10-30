"""Read-only catalog introspection; run from the revision being compared."""
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path.cwd()))

from jarvis.domain.scene import SceneOp
from jarvis.runtime.display_mcp import text_output_schemas
from jarvis.runtime.mcp_catalog import describe_tool, list_server_tools, server_meta


def digest(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


async def main():
    listed = await list_server_tools("jarvis-display")
    outputs = text_output_schemas()
    described = [describe_tool(server_meta("jarvis-display"), tool, outputs) for tool in listed]
    visible = [{"name": tool.name, "description": tool.description or "", "input_schema": tool.inputSchema}
               for tool in listed]
    print(json.dumps({
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "tool_count": len(listed), "names": [tool.name for tool in listed],
        "context_bytes": sum(tool["context_bytes"] for tool in described),
        "model_visible": digest(visible),
        "full_tools_list": digest([tool.model_dump(mode="json", exclude_none=True) for tool in listed]),
        "descriptors": digest(described), "text_output_schemas": digest(outputs),
        "layout_selection_advertised": "layout_selection" in json.dumps(described),
        "scene_ops": [op.value for op in SceneOp],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
