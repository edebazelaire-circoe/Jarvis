"""Slice 08: drive the real ClaudeLocalAgent (conversation profile, jarvis-display + jarvis-console) on the isolated Core/CC.
Harness-only changes: --chrome removed, --no-session-persistence added. Real model, default Claude config (read-only).
usage: brain8.py S W turns.json first_index"""
import asyncio, json, os, subprocess, sys, time
from pathlib import Path
S = Path(sys.argv[1]); W = Path(sys.argv[2]); turns = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")); first = int(sys.argv[4])
sys.path.insert(0, str(W)); sys.path.insert(0, str(S))
PORT = int(os.environ.get("JARVIS_CORE_PORT") or 0); UI = int(os.environ.get("JARVIS_UI_PORT") or 0)
if PORT in (0, 17653, 17654) or UI in (0, 17653, 17654): sys.exit("REFUSE port")
os.environ.pop("CLAUDE_CONFIG_DIR", None)
from corecli import snap
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.display_mcp import DisplayMcpTarget
from jarvis.runtime.settings_mcp import ConsoleMcpTarget
real_exec = asyncio.create_subprocess_exec
async def patched(*argv, **kw):
    argv = [a for a in argv if a != "--chrome"]
    argv.insert(2, "--no-session-persistence")
    (S / "brain-argv.json").write_text(json.dumps(argv, ensure_ascii=False, indent=1), encoding="utf-8")
    return await real_exec(*argv, **kw)
asyncio.create_subprocess_exec = patched
rt = Path(os.environ["JARVIS_RUNTIME_DIR"])
def shot(name):
    subprocess.run([sys.executable, str(S / "cdp5.py"), "shot", str(S / "shots" / name)], timeout=30, capture_output=True)
async def main():
    agent = ClaudeLocalAgent(runtime_root=S / "brain-rt", cwd=W,
        display_mcp=DisplayMcpTarget(core_host=os.environ["JARVIS_CORE_HOST"], core_port=PORT, token_file=rt / "core.token", runtime_root=rt),
        console_mcp=ConsoleMcpTarget("127.0.0.1", UI, rt))
    out = open(S / "turns.jsonl", "a", encoding="utf-8")
    try:
        i = first - 1
        for text in turns:
            if text.startswith("__sleep:"):
                print("sleep", text, flush=True); await asyncio.sleep(float(text.split(":")[1])); continue
            i += 1
            shot(f"t{i}-before.png")
            before = snap(); agent._events.clear(); agent._event_times.clear(); n0 = 0; t0 = time.time()
            res = await agent.ask(text, timeout_s=240)
            await asyncio.sleep(2.5)
            after = snap(); shot(f"t{i}-after.png")
            rec = {"turn": i, "text": text, "t0": t0, "t1": time.time(), "rev_before": before["revision"], "rev_after": after["revision"],
                   "answer": res.get("text"), "ok": res.get("ok"), "cost": res.get("cost_usd"), "duration_ms": res.get("duration_ms"),
                   "events": agent._events[n0:], "snap_after": after["snapshot"]}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
            print(f"T{i} [{rec['rev_before']}->{rec['rev_after']}] {text} => {res.get('text')!r} cost={res.get('cost_usd')}", flush=True)
    finally:
        await agent.stop()
asyncio.run(main())
