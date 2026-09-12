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

    print("Release verification passed.")


if __name__ == "__main__":
    main()
