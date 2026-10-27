#!/usr/bin/env python3
"""Porte des tests de la release (Slice 10, `docs/release.md` › *Known failures*).

    python scripts/release_test_gate.py --suite unit|browser|release|all [--shard K/N] [--report FILE] [--list]

Lance pytest sur la suite choisie (fichiers triés, découpables en `N` parts pour les petites machines et la matrice
de la CI) et juge le résultat contre `tests/known_failures.json`, une liste EXPLICITE et DATÉE :

- un échec qui n'est pas dans la liste fait échouer la porte ;
- un test `failing` de la liste qui PASSE fait échouer la porte (l'entrée est périmée : la retirer) ;
- un test `intermittent` de la liste qui échoue est relancé seul, au plus deux fois ; il doit alors passer ;
- une entrée dont `review_by` est dépassée fait échouer la porte ;
- une erreur de collecte (import) est un échec, jamais un saut.

Il n'existe aucun « ignore » global. Code de sortie : 0 porte verte, 1 porte rouge, 2 usage ou liste invalide.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
KNOWN_FAILURES = ROOT / "tests" / "known_failures.json"
KNOWN_SCHEMA = "jarvis.known-test-failures"
KINDS = ("failing", "intermittent")
INTERMITTENT_RERUNS = 2
#: Fichiers qui pilotent un vrai navigateur ou Node (lents, lourds en mémoire).
BROWSER_PATTERNS = ("*_browser.py", "*_js.py")
#: Suite courte « produit et sécurité » de la release (édition, confinement, export, paquet, installation, données).
RELEASE_PATTERNS = ("test_product_*.py", "test_windows_*.py", "test_private_runtime*.py", "test_installed_product_root*.py",
                    "test_agent_capabilit*.py", "test_confined_prompts*.py", "test_export*.py", "test_data_root*.py",
                    "test_global_context*.py", "test_schema_migrations.py", "test_release_*.py", "test_diagnostic_redaction*.py",
                    "test_support_bundle*.py", "test_owned_process_tree*.py", "test_process_tree*.py",
                    "test_control_center_relay_whitelist*.py", "test_product_edition*.py", "test_wake_word_install*.py",
                    "test_document_export*.py", "test_remotion_export_save_mcp.py", "test_presentation_export_after_edit.py",
                    "test_board_edition*.py", "test_workspace_board_contract.py")
SUITES = ("unit", "browser", "release", "all")


class GateError(RuntimeError):
    """Liste des échecs connus invalide, ou usage incorrect : code 2."""


@dataclass(frozen=True)
class Known:
    nodeid: str
    kind: str
    review_by: date
    issue: str


def load_known(path: Path = KNOWN_FAILURES) -> dict[str, Known]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"{path.name} illisible : {exc}") from exc
    if payload.get("schema") != KNOWN_SCHEMA or payload.get("schema_version") != 1:
        raise GateError(f"{path.name} : schéma inattendu {payload.get('schema')!r}")
    known: dict[str, Known] = {}
    for index, row in enumerate(payload.get("failures") or []):
        try:
            entry = Known(str(row["nodeid"]), str(row["kind"]), date.fromisoformat(str(row["review_by"])), str(row["issue"]))
            date.fromisoformat(str(row["since"]))
            str(row["reason"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GateError(f"{path.name} : entrée {index} incomplète (nodeid, kind, since, review_by, issue, reason) : {exc}") from exc
        if entry.kind not in KINDS:
            raise GateError(f"{path.name} : {entry.nodeid} a le type {entry.kind!r} (attendu {KINDS})")
        if entry.nodeid in known:
            raise GateError(f"{path.name} : {entry.nodeid} listé deux fois")
        known[entry.nodeid] = entry
    return known


def test_files(root: Path = ROOT) -> list[str]:
    found = []
    for path in sorted((root / "tests").rglob("test_*.py")):
        relative = path.relative_to(root).as_posix()
        if "/fakes/" in relative or "/fixtures/" in relative or "__pycache__" in relative:
            continue
        found.append(relative)
    return found


def _matches(relative: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(relative.rsplit("/", 1)[-1], pattern) for pattern in patterns)


def suite_files(suite: str, root: Path = ROOT) -> list[str]:
    files = test_files(root)
    if suite == "all":
        return files
    if suite == "browser":
        return [f for f in files if _matches(f, BROWSER_PATTERNS)]
    if suite == "unit":
        return [f for f in files if not _matches(f, BROWSER_PATTERNS)]
    if suite == "release":
        return [f for f in files if _matches(f, RELEASE_PATTERNS) and not _matches(f, BROWSER_PATTERNS)]
    raise GateError(f"suite inconnue {suite!r} (attendu {SUITES})")


def shard(files: list[str], spec: str | None) -> list[str]:
    if not spec:
        return files
    try:
        index, count = (int(part) for part in spec.split("/"))
    except ValueError as exc:
        raise GateError(f"--shard {spec!r} : attendu K/N") from exc
    if not 1 <= index <= count:
        raise GateError(f"--shard {spec!r} : K doit être entre 1 et N")
    return [name for position, name in enumerate(files) if position % count == index - 1]


def run_pytest(targets: list[str], report: Path, *, extra: list[str] | None = None) -> dict:
    env = {**os.environ, "JARVIS_TEST_GATE_REPORT": str(report)}
    report.unlink(missing_ok=True)
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "scripts.release_test_gate_plugin", *(extra or []),
            *targets]
    done = subprocess.run(argv, cwd=ROOT, env=env, check=False)
    try:
        return json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # pytest died before its session finished (crash, killed): the gate cannot judge anything, so it is red.
        return {"exitstatus": done.returncode, "tests": {"<pytest>": {"session": "failed"}}, "crash": str(exc)}


def failed_ids(result: dict) -> set[str]:
    return {nodeid for nodeid, phases in result.get("tests", {}).items() if "failed" in phases.values()}


def passed_ids(result: dict) -> set[str]:
    return {nodeid for nodeid, phases in result.get("tests", {}).items()
            if phases.get("call") == "passed" and "failed" not in phases.values()}


@dataclass
class Verdict:
    unknown: list[str]
    stale: list[str]
    expired: list[str]
    tolerated: list[str]
    known_failed: list[str]
    passed: int
    failed: int

    @property
    def green(self) -> bool:
        return not (self.unknown or self.stale or self.expired)

    def to_payload(self) -> dict:
        return {"green": self.green, "passed": self.passed, "failed": self.failed, "unknown_failures": self.unknown,
                "stale_known_failures": self.stale, "expired_entries": self.expired,
                "intermittent_tolerated": self.tolerated, "known_failures_seen": self.known_failed}


def judge(result: dict, known: dict[str, Known], *, today: date, rerun) -> Verdict:
    failed, passed = failed_ids(result), passed_ids(result)
    unknown, tolerated, known_failed = [], [], []
    for nodeid in sorted(failed):
        entry = known.get(nodeid)
        if entry is None:
            unknown.append(nodeid)
        elif entry.kind == "failing":
            known_failed.append(nodeid)
        elif rerun(nodeid):
            tolerated.append(nodeid)
        else:
            unknown.append(f"{nodeid} (intermittent listé, mais échoue aussi seul)")
    stale = sorted(nodeid for nodeid in passed if nodeid in known and known[nodeid].kind == "failing")
    expired = sorted(f"{k.nodeid} (review_by {k.review_by.isoformat()}, {k.issue})" for k in known.values() if k.review_by < today)
    return Verdict(unknown, stale, expired, tolerated, known_failed, len(passed), len(failed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--suite", choices=SUITES, required=True)
    parser.add_argument("--shard", action="append", default=[],
                        help="K/N : seulement la K-ième part sur N des fichiers ; répétable (3/10 puis 1/2 : la moitié de la part 3)")
    parser.add_argument("--report", help="écrit le verdict JSON dans ce fichier")
    parser.add_argument("--list", action="store_true", help="liste les fichiers sans lancer pytest")
    parser.add_argument("--today", help=argparse.SUPPRESS)  # tests de la porte
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        known = load_known()
        files = suite_files(args.suite)
        for spec in args.shard:
            files = shard(files, spec)
    except GateError as exc:
        print(f"[test-gate] ERREUR : {exc}", file=sys.stderr)
        return 2
    if args.list:
        print("\n".join(files))
        return 0
    if not files:
        print("[test-gate] ERREUR : aucun fichier dans cette suite/part", file=sys.stderr)
        return 2
    today = date.fromisoformat(args.today) if args.today else date.today()
    with tempfile.TemporaryDirectory(prefix="jarvis-test-gate-") as work:
        result = run_pytest(files, Path(work) / "run.json")

        def rerun(nodeid: str) -> bool:
            for attempt in range(1, INTERMITTENT_RERUNS + 1):
                again = run_pytest([nodeid], Path(work) / f"rerun-{attempt}.json")
                if nodeid in passed_ids(again) and not failed_ids(again):
                    return True
            return False

        verdict = judge(result, known, today=today, rerun=rerun)
    shards = ",".join(args.shard) or None
    payload = {"suite": args.suite, "shard": shards, "files": len(files), "known_failures_file": KNOWN_FAILURES.name,
               **verdict.to_payload()}
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[test-gate] suite {args.suite}{' ' + shards if shards else ''} : {len(files)} fichiers, "
          f"{verdict.passed} passés, {verdict.failed} en échec dont {len(verdict.known_failed)} connus")
    for label, rows in (("échec NON listé", verdict.unknown), ("entrée périmée (le test passe : la retirer)", verdict.stale),
                        ("entrée à revoir (review_by dépassé)", verdict.expired), ("intermittent toléré (passé seul)", verdict.tolerated)):
        for row in rows:
            print(f"[test-gate]   {label} : {row}")
    print(f"[test-gate] {'VERT' if verdict.green else 'ROUGE'}")
    return 0 if verdict.green else 1


if __name__ == "__main__":
    raise SystemExit(main())
