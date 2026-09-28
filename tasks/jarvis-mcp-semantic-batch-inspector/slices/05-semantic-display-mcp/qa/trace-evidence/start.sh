. /c/Users/Clarice/AppData/Local/Temp/claude/C--Projects-jarvis-sub-agents-jarvis-agent-01/b7d45121-0ea1-4bc3-8741-e66996931033/scratchpad/s5/env.sh || exit 1
cd $W
$PY -m jarvis core > $S/core.log 2>&1 &
echo $! > $S/core.pid
for i in $(seq 1 60); do grep -qi "ready\|listening" $S/core.log && break; sleep 0.5; done
$PY -c "import webbrowser,runpy,sys; webbrowser.open=lambda *a,**k: True; sys.argv=['jarvis','control-center']; runpy.run_module('jarvis', run_name='__main__')" > $S/cc.log 2>&1 &
echo $! > $S/cc.pid
for i in $(seq 1 60); do grep -q "Control Center ready" $S/cc.log && break; sleep 0.5; done
tail -3 $S/core.log $S/cc.log
