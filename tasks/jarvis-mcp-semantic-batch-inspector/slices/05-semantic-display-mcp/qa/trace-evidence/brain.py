"""Pilote le vrai ClaudeLocalAgent (profil conversation + jarvis-display) sur le Core isolé.
Seuls écarts harnais : --chrome retiré, --no-session-persistence ajouté. Modèle réel, config Claude par défaut."""
import asyncio, json, os, sys, time
from pathlib import Path
S = Path(sys.argv[1]); W = Path(sys.argv[2]); turns = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
sys.path.insert(0, str(W)); sys.path.insert(0, str(S))
PORT = int(os.environ.get("JARVIS_CORE_PORT") or 0)
if PORT in (0, 17653, 17654): sys.exit("REFUSE port")
os.environ.pop("CLAUDE_CONFIG_DIR", None)
from corecli import snap
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.display_mcp import DisplayMcpTarget
real_exec = asyncio.create_subprocess_exec
async def patched(*argv, **kw):
    argv = [a for a in argv if a != "--chrome"]
    argv.insert(2, "--no-session-persistence")
    (S / "brain-argv.json").write_text(json.dumps(argv, ensure_ascii=False, indent=1), encoding="utf-8")
    return await real_exec(*argv, **kw)
asyncio.create_subprocess_exec = patched
rt = Path(os.environ["JARVIS_RUNTIME_DIR"])
import subprocess
def shot(name):
    subprocess.run([sys.executable, str(S / "cdp.py"), "shot", str(S / "shots" / name)], timeout=30, capture_output=True)
async def main():
    agent = ClaudeLocalAgent(runtime_root=S / "brain-rt", cwd=W, display_mcp=DisplayMcpTarget(
        core_host=os.environ["JARVIS_CORE_HOST"], core_port=PORT, token_file=rt / "core.token", runtime_root=rt))
    out = open(S / "turns.jsonl", "a", encoding="utf-8")
    try:
        for i, text in enumerate(turns, 1):
            shot(f"t{i+6}-before.png")
            before = snap(); n0 = len(agent._events); t0 = time.time()
            res = await agent.ask(text, timeout_s=240)
            await asyncio.sleep(2.5)
            after = snap(); shot(f"t{i+6}-after.png")
            rec = {"text": text, "t0": t0, "t1": time.time(), "rev_before": before["revision"], "rev_after": after["revision"],
                   "answer": res.get("text"), "ok": res.get("ok"), "cost": res.get("cost_usd"), "duration_ms": res.get("duration_ms"),
                   "events": agent._events[n0:], "snap_after": after["snapshot"]}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
            print(f"[{rec['rev_before']}->{rec['rev_after']}] {text} => {res.get('text')!r}", flush=True)
    finally:
        await agent.stop()
asyncio.run(main())
