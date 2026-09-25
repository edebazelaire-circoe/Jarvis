S=/c/Users/Clarice/AppData/Local/Temp/claude/C--Projects-jarvis-sub-agents-jarvis-agent-01/b7d45121-0ea1-4bc3-8741-e66996931033/scratchpad/s8
W=/c/Projects/jarvis/sub-agents/jarvis-agent-01
PY=$W/.venv/Scripts/python.exe
export JARVIS_DATA_ROOT=$(cygpath -w $S/data) JARVIS_RUNTIME_DIR=$(cygpath -w $S/rt)
export JARVIS_CORE_PORT=17683 JARVIS_UI_PORT=17685 JARVIS_SCENE_ENABLED=1 JARVIS_VISUALIZER_ENABLED=0
export JARVIS_CORE_HOST=127.77.0.1 PYTHONIOENCODING=utf-8
# Phase A (real brain driven by brain8.py): the CC's own brain is disabled.
# Phase B (inspector): QA_PHASE=B -> CC brain = wrapper to the fake endpoint ($0).
if [ "${QA_PHASE:-A}" = B ]; then
  export JARVIS_CLAUDE_CLI=$(cygpath -w $S/wrap/claudeqa.exe) QA_WRAP_DIR=$(cygpath -w $S/wrap) QA_FAKE_PORT=17689 QA_FAKE_CFG=$(cygpath -w $S/fakecfg)
else
  export JARVIS_CLAUDE_CLI=__qa_no_brain_claude__
fi
for p in "$JARVIS_CORE_PORT" "$JARVIS_UI_PORT" "${QA_FAKE_PORT:-17689}"; do
  if [ -z "$p" ] || [ "$p" = 17653 ] || [ "$p" = 17654 ]; then echo "REFUSE: bad port '$p'"; exit 1; fi
done
case "$JARVIS_RUNTIME_DIR$JARVIS_DATA_ROOT" in *Projects*jarvis\jarvis*|"") echo "REFUSE live dir"; exit 1;; esac
