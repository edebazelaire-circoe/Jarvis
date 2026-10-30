"""Six bounded, sequential QA mutations; exact source bytes restored in finally."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[5]
QA = Path(__file__).resolve().parent
TESTS = "tests/unit/test_scene_layout_selection.py::"


def main():
    cases = [
        ("stale_guard", "jarvis/domain/scene_batch.py", "    if stale:\n", "    if False and stale:\n",
         TESTS + "test_any_stale_compare_refuses_all_targets_in_selection_order_even_for_noop_targets"),
        ("target_identity", "jarvis/domain/scene.py", "            if set(self.selection.ids) != {target.object_id for target in self.targets.entries}:\n",
         "            if False and set(self.selection.ids) != {target.object_id for target in self.targets.entries}:\n",
         TESTS + "test_invalid_layout_wire_is_rejected_at_boundary"),
        ("runtime_authority", "jarvis/domain/scene_batch.py", "    if command.op not in ALLOWED_SCENE_OPS[command.actor]:\n",
         "    if command.op is not SceneOp.LAYOUT_SELECTION and command.op not in ALLOWED_SCENE_OPS[command.actor]:\n",
         TESTS + "test_runtime_is_refused_even_when_geometry_is_unchanged"),
        ("pin_without_request", "jarvis/domain/scene_batch.py", "    if command.pin:\n        for object_id, after in states.items():\n",
         "    if True:\n        for object_id, after in states.items():\n",
         TESTS + "test_duplicate_is_no_revision_and_revision_exhaustion_is_all_or_nothing"),
        ("unplaced_eligibility", "jarvis/domain/scene_batch.py", "_REQUIRE_PLACED = frozenset({SceneOp.TRANSLATE_SELECTION, SceneOp.PIN_SELECTION, SceneOp.LAYOUT_SELECTION})",
         "_REQUIRE_PLACED = frozenset({SceneOp.TRANSLATE_SELECTION, SceneOp.PIN_SELECTION})",
         TESTS + "test_unknown_or_unplaced_required_member_prevents_every_write"),
        ("publish_before_persist", "jarvis/core/scene_service.py", "            try:\n                await self._repository.commit(current, update.patch, update.snapshot)\n",
         "            self._snapshot = update.snapshot\n            try:\n                await self._repository.commit(current, update.patch, update.snapshot)\n",
         TESTS + "test_layout_persistence_failure_leaves_all_geometry_unchanged_and_is_logged"),
    ]
    originals = {path: (ROOT / path).read_bytes() for _, path, *_ in cases}
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    results = json.loads((QA / "mutation-results.json").read_text(encoding="utf-8"))["results"] if start else []
    if len(results) != start:
        raise AssertionError("resume index must equal recorded completed cases")
    try:
        for name, path, before, after, test in cases[start:]:
            target = ROOT / path
            raw = originals[path]
            source = raw.decode("utf-8")
            # Preserve checkout CRLF while matching the exact logical fragment.
            newline = "\r\n" if "\r\n" in source else "\n"
            before, after = before.replace("\n", newline), after.replace("\n", newline)
            if source.count(before) != 1:
                raise AssertionError(f"{name}: mutation anchor count {source.count(before)}")
            mutated = source.replace(before, after, 1).encode("utf-8")
            # Timestamp-based pyc validation also checks source byte length.
            # Different lengths plus fresh subprocess prevent stale mutant imports.
            if len(mutated) == len(raw):
                raise AssertionError(f"{name}: use a size-changing mutation to invalidate pyc")
            try:
                target.write_bytes(mutated)
                run = subprocess.run([sys.executable, "-m", "pytest", "--assert=plain", "--tb=short", "-q", test],
                                     cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=90)
                results.append({"mutation": name, "path": path, "test": test, "returncode": run.returncode,
                                "killed": run.returncode == 1, "output": (run.stdout + run.stderr)[-6500:]})
                print(name, "KILLED" if run.returncode == 1 else f"UNEXPECTED {run.returncode}", flush=True)
            finally:
                target.write_bytes(raw)
                if target.read_bytes() != raw:
                    raise AssertionError(f"{name}: restore failed")
    finally:
        for path, raw in originals.items():
            (ROOT / path).write_bytes(raw)
        (QA / "mutation-results.json").write_text(json.dumps({"results": results, "restored_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in originals}}, indent=2), encoding="utf-8")
    return 0 if len(results) == 6 and all(r["killed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
