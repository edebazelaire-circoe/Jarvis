"""Core isolé (données dans scratchpad), scène semée, attend l'arrêt."""
import asyncio, json, sys, pathlib
sys.path.insert(0, r"C:\Projects\jarvis\sub-agents\jarvis-agent-01")
from tests.integration.test_scene_transport import CoreProcess, artifact

TITLES = ['Résumé "marché" Q3', r"Notes C:\chemin\fichier", "Plan d'action"]


async def main():
    root = pathlib.Path(sys.argv[1]); root.mkdir(parents=True, exist_ok=True)
    core = CoreProcess(root)
    await core.start()
    for i, t in enumerate(TITLES):
        st, body, _ = await core.request("POST", "/v1/scene/commands", json=artifact(f"seed-{i}", title=t))
        assert st == 200, body
    (root / "core.json").write_text(json.dumps({"port": core.port, "token_file": str(core.token_file)}), encoding="utf-8")
    print("READY", core.port, flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await core.stop()

asyncio.run(main())
