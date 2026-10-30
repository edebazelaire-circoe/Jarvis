"""Independent Escape bridge mutations on copied JS only; product tree untouched."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
TEST = "tests/unit/test_prefab_escape_bridge.py"
MUTANTS = [
    ("focused_frame", "control_center_prefab_host.js", "||doc.activeElement!==rec.iframe", "",
     "test_host_only_delivers_focused_live_escape_and_rate_limits_locally"),
    ("plain_escape_only", "shim.js", "event.key!=='Escape'||", "",
     "test_shim_only_posts_trusted_plain_escape_after_init_and_removes_listener_on_teardown"),
    ("exact_shape", "control_center_prefab_protocol.js",
     "if(key!=='jv'&&key!=='type'&&!allowed.includes(key))",
     "if(data.type!=='escape'&&key!=='jv'&&key!=='type'&&!allowed.includes(key))",
     "test_protocol_accepts_only_exact_escape_notice"),
    ("rate_limit", "control_center_prefab_host.js", "if(!withinRate(rec,rec.escapesIn,1))break;",
     "/* QA mutant: no rate guard */",
     "test_host_only_delivers_focused_live_escape_and_rate_limits_locally"),
]

def main() -> int:
    records = []
    with tempfile.TemporaryDirectory(prefix="mov-escape-mutants-") as raw:
        scratch = Path(raw)
        copied = scratch / "runtime"
        copied.mkdir()
        for source in (ROOT / "jarvis/runtime").glob("*.js"):
            shutil.copy2(source, copied / source.name)
        for name in ("shim.js", "shell.css"):
            shutil.copy2(ROOT / "jarvis/prefabs/runtime" / name, copied / name)
        plugin = scratch / "escape_mutation_plugin.py"
        plugin.write_text(
            "from pathlib import Path\n"
            "def pytest_configure(config):\n"
            " import tests.fakes.prefab_js as f\n"
            f" p=Path({str(copied)!r})\n"
            " f.LAYOUT_JS=p/'control_center_scene_layout.js'\n"
            " f.PROTOCOL_JS=p/'control_center_prefab_protocol.js'\n"
            " f.HOST_JS=p/'control_center_prefab_host.js'\n"
            " f.SHIM_JS=p/'shim.js'\n"
            " f.SHELL_CSS=p/'shell.css'\n",
            encoding="utf-8",
        )
        env = dict(os.environ, PYTHONPATH=str(scratch) + os.pathsep + str(ROOT), PYTHONUTF8="1")
        def run(target: str):
            command = [sys.executable, "-m", "pytest", "-p", "escape_mutation_plugin",
                       "--assert=plain", "--tb=short", "-q", target]
            result = subprocess.run(command, cwd=ROOT, env=env, text=True, encoding="utf-8",
                                    errors="replace", capture_output=True, timeout=120)
            return {"command": command[1:], "returncode": result.returncode,
                    "output": result.stdout + result.stderr}
        baseline = run(TEST)
        if baseline["returncode"] != 0:
            raise RuntimeError("Unmutated copied bridge failed: " + baseline["output"][-4000:])
        for name, file, old, new, function in MUTANTS:
            path = copied / file
            original = path.read_bytes()
            source = original.decode("utf-8")
            if source.count(old) != 1:
                raise RuntimeError(f"{name}: expected exactly one mutation site")
            try:
                path.write_text(source.replace(old, new), encoding="utf-8")
                result = run(TEST + "::" + function)
                killed = result["returncode"] == 1 and function in result["output"] and "AssertionError" in result["output"]
                records.append({"mutation": name, "killed": killed, **result})
                print(f"{name}: {'killed' if killed else 'NOT KILLED'}", flush=True)
            finally:
                path.write_bytes(original)
    answer = {"method": "Fresh Node processes load copied JS via pytest plugin; repository sources never mutated.",
              "baseline": baseline, "mutations": records}
    (HERE / "mutation-results.json").write_text(json.dumps(answer, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(row["killed"] for row in records) else 1

if __name__ == "__main__":
    raise SystemExit(main())

