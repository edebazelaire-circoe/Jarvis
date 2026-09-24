#!/usr/bin/env bash
# usage: run.sh <old|new> <api_port>
set -u
S=/c/Users/Clarice/AppData/Local/Temp/claude/C--Projects-jarvis-sub-agents-jarvis-agent-01/b7d45121-0ea1-4bc3-8741-e66996931033/scratchpad
PY=/c/Projects/jarvis/sub-agents/jarvis-agent-01/.venv/Scripts/python.exe
V=$1; APIPORT=$2; R=$S/run-$V
rm -rf $R; mkdir -p $R/cfg $R/rt
export PYTHONIOENCODING=utf-8
$PY $S/core_run.py $(cygpath -w $R/core) > $R/core.log 2>&1 &
CORE=$!
for i in $(seq 1 60); do [ -f $R/core/core.json ] && break; sleep 0.5; done
PORT=$($PY -c "import json;print(json.load(open(r'$(cygpath -w $R/core/core.json)'))['port'])")
TOK=$($PY -c "import json;print(json.load(open(r'$(cygpath -w $R/core/core.json)'))['token_file'])")
[ -n "$PORT" ] && [ "$PORT" != 17653 ] || { echo "NO PORT, abort"; kill $CORE; exit 1; }
$PY $S/fake_api.py $APIPORT $S/script.json $R/bodies.jsonl > $R/api.log 2>&1 &
API=$!
PP=""; [ "$V" = old ] && PP="$(cygpath -w $S/old)"
$PY - <<EOF
import json
env={"JARVIS_CORE_HOST":"127.0.0.1","JARVIS_CORE_PORT":"$PORT","JARVIS_CORE_TOKEN_FILE":r"$TOK","JARVIS_RUNTIME_DIR":r"$(cygpath -w $R/rt)","PYTHONIOENCODING":"utf-8"}
if r"$PP": env["PYTHONPATH"]=r"$PP"
cfg={"mcpServers":{"jarvis-display":{"type":"stdio","command":r"$(cygpath -w $PY)","args":["-m","jarvis","display-mcp"],"env":env}}}
open(r"$(cygpath -w $R/mcp.json)","w",encoding="utf-8").write(json.dumps(cfg))
EOF
sleep 1
cd $R
ANTHROPIC_BASE_URL=http://127.0.0.1:$APIPORT ANTHROPIC_API_KEY=sk-ant-dummy-not-real CLAUDE_CONFIG_DIR=$(cygpath -w $R/cfg) \
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 DISABLE_AUTOUPDATER=1 \
ANTHROPIC_AUTH_TOKEN= CLAUDE_CODE_OAUTH_TOKEN= \
timeout 180 claude -p "go" --mcp-config $(cygpath -w $R/mcp.json) --strict-mcp-config \
  --allowedTools "mcp__jarvis-display" --output-format stream-json --verbose --model claude-sonnet-4-5 > $R/stream.jsonl 2> $R/cli.err
echo "cli exit $?"
kill $API $CORE 2>/dev/null
taskkill //F //PID $(cat /proc/$API/winpid 2>/dev/null) >/dev/null 2>&1
taskkill //F //PID $(cat /proc/$CORE/winpid 2>/dev/null) >/dev/null 2>&1
wc -l $R/bodies.jsonl $R/stream.jsonl
