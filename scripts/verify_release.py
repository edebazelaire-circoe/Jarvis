#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def _package_of(path: Path, level: int) -> str:
    """Paquet de base d'un import relatif : `from . import x` dans `jarvis/runtime/` → `jarvis.runtime`."""

    if not level:
        return ""
    folders = path.resolve().relative_to(ROOT).parts[:-1]
    return ".".join(folders[: len(folders) - (level - 1)])


#: Tests that must exist for the release gate of the Presentation Studio (Slice 11 carry-forward, item 3): the crash drills of the authoring
#: planner and the privacy assertions that no draft text reaches a log. The sweep runs them; here they must at least be present and non-empty.
STUDIO_REQUIRED_TESTS = {
    "tests/unit/test_presentation_studio_authoring_crash.py": 5,
    "tests/unit/test_presentation_studio_authoring_service.py": "test_untrusted_text_is_stored_as_text_and_never_reaches_the_logs",
    "tests/unit/test_presentation_studio_authoring_routes.py": 1,
    "tests/unit/test_presentation_studio_release_faults.py": "test_no_draft_title_note_or_label_text_reaches_a_log_a_trace_or_the_event_store",
}


def presentation_studio_findings(root: Path = ROOT) -> list[str]:
    """Findings (an empty list is a pass) of the release verifier items of the Presentation Studio that need no model.

    The authoring planner prompt must be registered, read only, not editable, and attached to exactly the conversation programs that declare
    the presentation tools; its content fingerprint must be the one every committed piece of evidence was gathered with; the crash drills
    and the privacy assertions of the authoring must exist. Importing the package is the only side effect.
    """

    sys.path.insert(0, str(root))
    try:
        from jarvis.domain.presentation_studio_authoring_policy import PLANNER_PROMPT, PROMPT_FINGERPRINT, PROMPT_ID
        from jarvis.runtime.prompt_catalog import default_prompt_registry
    finally:
        sys.path.pop(0)
    found: list[str] = []
    registry = default_prompt_registry()
    try:
        descriptor = registry.require(PROMPT_ID)
    except Exception as exc:  # noqa: BLE001 - a missing prompt is the finding, whatever the registry raises
        return [f"planner prompt {PROMPT_ID} is not registered: {exc}"]
    if descriptor.default_text != PLANNER_PROMPT:
        found.append("registered planner text differs from PLANNER_PROMPT")
    if descriptor.apply_policy != "read_only" or descriptor.editable:
        found.append("planner prompt is editable or not read_only")
    declaring = {p.program_id for p in registry.programs
                 if any(step.prompt_id == "backend.claude.conversation.presentation" for step in p.steps)}
    attached = {p.program_id for p in registry.programs if any(step.prompt_id == PROMPT_ID for step in p.steps)}
    if not declaring or attached != declaring:
        found.append(f"planner attached to {sorted(attached)} but the presentation tools are declared by {sorted(declaring)}")
    evidence = root / "tasks" / "jarvis-interactive-presentation-studio" / "slices"
    recorded: dict[str, str] = {}
    rig = evidence / "11-authoring-planner-first-draft" / "evidence" / "fake-author-rig.json"
    if rig.is_file():
        recorded["scripted rig (Slice 11)"] = json.loads(rig.read_text(encoding="utf-8"))["prompt"]["fingerprint"]
    for path in sorted((evidence / "22-end-to-end-hardening" / "evidence").glob("authoring-real-traces*.json")):
        recorded[path.name] = json.loads(path.read_text(encoding="utf-8")).get("planner_fingerprint", "")
    if "scripted rig (Slice 11)" not in recorded:
        found.append("the Slice 11 rig evidence is missing")
    for name, fingerprint in recorded.items():
        if fingerprint != PROMPT_FINGERPRINT:
            found.append(f"evidence {name} was gathered with planner fingerprint {fingerprint[:12]!r}, the code has {PROMPT_FINGERPRINT[:12]!r}")
    for relative, needed in STUDIO_REQUIRED_TESTS.items():
        path = root / relative
        if not path.is_file():
            found.append(f"missing release test file {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        count = text.count("\ndef test_") + text.count("\nasync def test_")
        if isinstance(needed, int) and count < needed:
            found.append(f"{relative} has {count} tests, expected at least {needed}")
        if isinstance(needed, str) and needed not in text:
            found.append(f"{relative} lost {needed}")
    return found


def main() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        text=True,
        check=False,
    )
    if result.returncode:
        fail("pytest failed")

    forbidden_core_imports = ("openai", "httpx", "sounddevice", "pynput")
    for path in (ROOT / "jarvis" / "core").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] in forbidden_core_imports for name in names):
                fail(f"provider/runtime dependency leaked into core: {path}: {names}")

    # Outillage de mesure (banc d'essai des vérificateurs de locuteur, tâche 09
    # du handoff Solo Owner) : il relance `sys.executable` pour isoler un moteur
    # et interroge la synthèse vocale Windows, avec des listes d'arguments fixes
    # et jamais de shell. Il est hors du chemin d'exécution ; l'invariant vérifié
    # ci-dessous est exactement celui-là : personne d'autre que son point d'entrée
    # en ligne de commande (et les tests) ne le nomme, ni par un `import`, ni par
    # `importlib`, ni par un `-m`. La règle sur les primitives reste totale
    # partout ailleurs.
    tooling = {
        ROOT / "jarvis" / "runtime" / "speaker_benchmark.py",
        ROOT / "jarvis" / "runtime" / "speaker_benchmark_fixtures.py",
    }
    entry_points = {ROOT / "scripts" / "benchmark_speaker_verification.py"}
    missing = sorted(path.name for path in tooling | entry_points if not path.is_file())
    if missing:
        fail(f"benchmark tooling allow-list points at missing files: {missing}")
    tooling_modules = {f"jarvis.runtime.{path.stem}" for path in tooling}
    scanned = [
        path
        for root in (ROOT / "jarvis", ROOT / "scripts")
        for path in root.rglob("*.py")
        if path not in tooling and path not in entry_points and path != Path(__file__).resolve()
    ]
    for path in scanned:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = ".".join(p for p in (_package_of(path, node.level), node.module or "") if p)
                names = [base] + [f"{base}.{a.name}" if base else a.name for a in node.names]
            else:
                continue
            if any(name in tooling_modules for name in names):
                fail(f"benchmark tooling imported by a production module: {path}")
        # `importlib.import_module(...)`, `__import__`, `subprocess -m …` : le
        # nom pointé ne peut apparaître que dans du code qui va le charger.
        if any(module in source for module in tooling_modules):
            fail(f"benchmark tooling named outside its allow-list: {path}")

    source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "jarvis").rglob("*.py") if p not in tooling)
    dangerous = ["subprocess.run(", "os.system(", "shell=True"]
    for needle in dangerous:
        if needle in source:
            fail(f"dangerous execution primitive in Jarvis package: {needle}")
    tooling_source = "\n".join(p.read_text(encoding="utf-8") for p in sorted(tooling))
    for needle in ("os.system(", "shell=True"):
        if needle in tooling_source:
            fail(f"dangerous execution primitive in the benchmark tooling: {needle}")

    lock = json.loads((ROOT / "third_party" / "LOCK.json").read_text(encoding="utf-8"))
    if not lock["runtime_sources"]["barehands"]["commit"] or not lock["runtime_sources"]["ai-visualizer"]["commit"]:
        fail("unpinned runtime source")

    example = (ROOT / "config" / "jarvis.example.toml").read_text(encoding="utf-8")
    if "log_content = false" not in example:
        fail("privacy logging is not disabled by default")

    for finding in presentation_studio_findings():
        fail(f"presentation studio: {finding}")

    print("Release verification passed.")


if __name__ == "__main__":
    main()
