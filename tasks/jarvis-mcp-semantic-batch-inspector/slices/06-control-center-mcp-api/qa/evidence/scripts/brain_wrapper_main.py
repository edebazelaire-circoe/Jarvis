"""QA wrapper for the brain CLI: strip --chrome, log argv, fake Messages endpoint, tee stdout. No product code."""
import json, os, subprocess, sys, threading, time
LOG = os.environ["QA_WRAP_DIR"]
REAL = r"C:\Users\Clarice\.local\bin\claude.exe"
argv = [a for a in sys.argv[1:] if a != "--chrome"]
n = int(time.time() * 1000)
with open(os.path.join(LOG, "launches.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"t": n, "pid": os.getpid(), "chrome_stripped": "--chrome" in sys.argv[1:], "argv": argv}, ensure_ascii=False) + "\n")
env = dict(os.environ)
env.update({"ANTHROPIC_BASE_URL": "http://127.0.0.1:" + os.environ["QA_FAKE_PORT"], "ANTHROPIC_API_KEY": "sk-ant-dummy-not-real",
            "CLAUDE_CONFIG_DIR": os.environ["QA_FAKE_CFG"], "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1", "DISABLE_AUTOUPDATER": "1",
            "ANTHROPIC_AUTH_TOKEN": "", "CLAUDE_CODE_OAUTH_TOKEN": ""})
p = subprocess.Popen([REAL, *argv], stdin=sys.stdin, stdout=subprocess.PIPE, stderr=sys.stderr, env=env)
out = open(os.path.join(LOG, f"stream-{n}.jsonl"), "ab")
for line in p.stdout:
    out.write(line); out.flush()
    sys.stdout.buffer.write(line); sys.stdout.buffer.flush()
sys.exit(p.wait())
