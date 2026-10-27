#!/usr/bin/env python3
"""Porte des tests de la release (Slice 10, `docs/release.md` › *Known failures*).

    python scripts/release_test_gate.py --suite unit|browser|release|all [--shard K/N] [--report FILE] [--list]

Lance pytest sur la suite choisie (fichiers triés, découpables en `N` parts pour les petites machines et la matrice
de la CI) et juge le résultat contre `tests/known_failures.json`, une liste EXPLICITE et DATÉE :

- un échec qui n'est pas dans la liste fait échouer la porte ;
- un test `failing` de la liste qui PASSE fait échouer la porte (l'entrée est périmée : la retirer) ;
- un test `intermittent` de la liste qui échoue est relancé seul, au plus deux fois ; il doit alors passer ;
- une entrée dont `review_by` est dépassée fait échouer la porte ;
- une erreur de collecte (import) est un échec, jamais un saut ;
- une session de pytest qui n'est pas allée au bout fait échouer la porte (QA S10 B1) : code de sortie autre que 0, ou
  1 sans échec constaté, session interrompue (`KeyboardInterrupt`, `pytest.exit`, arrêt demandé), moins de tests
  exécutés que collectés, rapport absent, aucun test passé (tout sauté) ;
- un test `failing` de la liste dont le fichier a tourné mais qui n'a pas échoué (sauté, par exemple sans Chrome) fait
  échouer la porte : l'échec connu n'a pas été VU (QA S10 m1). Le rapport compte les tests sautés et la durée.

Il n'existe aucun « ignore » global. Code de sortie : 0 porte verte, 1 porte rouge, 2 usage ou liste invalide.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

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
#: Codes de sortie de pytest qui disent que la session est allée au bout (0 tout passe, 1 des tests échouent).
PYTEST_FINISHED = (0, 1)
PYTEST_CODES = {2: "interrompue", 3: "erreur interne de pytest", 4: "erreur d'usage", 5: "aucun test collecté"}


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
        result = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # pytest died before its session finished (crash, killed): the gate cannot judge anything, so it is red.
        return {"exitstatus": done.returncode, "returncode": done.returncode, "tests": {"<pytest>": {"session": "failed"}},
                "crash": str(exc)}
    result["returncode"] = done.returncode
    return result


def failed_ids(result: dict) -> set[str]:
    return {nodeid for nodeid, phases in result.get("tests", {}).items() if "failed" in phases.values()}


def passed_ids(result: dict) -> set[str]:
    return {nodeid for nodeid, phases in result.get("tests", {}).items()
            if phases.get("call") == "passed" and "failed" not in phases.values()}


def skipped_ids(result: dict) -> set[str]:
    return {nodeid for nodeid, phases in result.get("tests", {}).items()
            if "skipped" in phases.values() and "failed" not in phases.values() and phases.get("call") != "passed"}


def session_problems(result: dict) -> list[str]:
    """Pourquoi la session de pytest ne permet pas de juger (liste vide : elle est allée au bout)."""

    problems = []
    status, returncode = result.get("exitstatus"), result.get("returncode", result.get("exitstatus"))
    if result.get("crash"):
        problems.append(f"rapport de pytest absent (code {returncode}) : la session est morte avant sa fin")
    elif returncode != status:
        problems.append(f"code de sortie de pytest {returncode}, différent de celui de son rapport ({status})")
    if status not in PYTEST_FINISHED:
        problems.append(f"pytest a fini avec le code {status} ({PYTEST_CODES.get(status, 'inconnu')}) : session non jugeable")
    if result.get("interrupted"):
        problems.append("session interrompue avant sa fin (arrêt demandé)")
    if status == 1 and not failed_ids(result):
        problems.append("code 1 sans aucun échec constaté")
    ran = sum(1 for phases in result.get("tests", {}).values() if set(phases) & {"setup", "call", "teardown"})
    collected = result.get("collected")
    if isinstance(collected, int) and ran < collected:
        problems.append(f"{collected} tests collectés, {ran} exécutés : session coupée")
    if not result.get("crash") and not passed_ids(result):
        problems.append("aucun test n'a passé (tout sauté, ou rien lancé)")
    return problems


@dataclass
class Verdict:
    unknown: list[str]
    stale: list[str]
    expired: list[str]
    tolerated: list[str]
    known_failed: list[str]
    passed: int
    failed: int
    skipped: int = 0
    unseen: list[str] = field(default_factory=list)
    session: list[str] = field(default_factory=list)
    exitstatus: int | None = None
    collected: int | None = None

    @property
    def green(self) -> bool:
        return not (self.unknown or self.stale or self.expired or self.unseen or self.session)

    def to_payload(self) -> dict:
        return {"green": self.green, "passed": self.passed, "failed": self.failed, "skipped": self.skipped,
                "collected": self.collected, "exitstatus": self.exitstatus, "session_problems": self.session,
                "unknown_failures": self.unknown, "stale_known_failures": self.stale,
                "unseen_known_failures": self.unseen, "expired_entries": self.expired,
                "intermittent_tolerated": self.tolerated, "known_failures_seen": self.known_failed}


def judge(result: dict, known: dict[str, Known], *, today: date, rerun, files: list[str] | None = None) -> Verdict:
    """`files` : les fichiers lancés ; un test `failing` listé d'un de ces fichiers doit y avoir échoué (m1)."""

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
    ran_files = set(files or ())
    unseen = sorted(f"{k.nodeid} (listé `failing`, ni échoué ni passé : sauté ou absent)" for k in known.values()
                    if k.kind == "failing" and k.nodeid.split("::", 1)[0] in ran_files
                    and k.nodeid not in failed and k.nodeid not in passed)
    expired = sorted(f"{k.nodeid} (review_by {k.review_by.isoformat()}, {k.issue})" for k in known.values() if k.review_by < today)
    collected = result.get("collected")
    return Verdict(unknown, stale, expired, tolerated, known_failed, len(passed), len(failed), len(skipped_ids(result)),
                   unseen, session_problems(result), result.get("exitstatus"), collected if isinstance(collected, int) else None)


def source_revision(root: Path = ROOT) -> str | None:
    """Révision testée (`HEAD`), écrite dans le rapport : `release_info.py` refuse un verdict d'une autre révision (m7)."""

    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    revision = done.stdout.strip()
    return revision if done.returncode == 0 and len(revision) == 40 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--suite", choices=SUITES, required=True)
    parser.add_argument("--shard", action="append", default=[],
                        help="K/N : seulement la K-ième part sur N des fichiers ; répétable (3/10 puis 1/2 : la moitié de la part 3)")
    parser.add_argument("--only", action="append", default=[],
                        help="motif de nom de fichier (fnmatch), répétable : seulement ces fichiers de la suite")
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
        if args.only:
            files = [f for f in files if _matches(f, tuple(args.only))]
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
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="jarvis-test-gate-") as work:
        result = run_pytest(files, Path(work) / "run.json")

        def rerun(nodeid: str) -> bool:
            for attempt in range(1, INTERMITTENT_RERUNS + 1):
                again = run_pytest([nodeid], Path(work) / f"rerun-{attempt}.json")
                if nodeid in passed_ids(again) and not failed_ids(again) and not session_problems(again):
                    return True
            return False

        verdict = judge(result, known, today=today, rerun=rerun, files=files)
    shards = ",".join(args.shard) or None
    payload = {"suite": args.suite, "shard": shards, "only": args.only or None, "files": len(files), "known_failures_file": KNOWN_FAILURES.name,
               "duration_seconds": round(time.monotonic() - started, 1), "source_revision": source_revision(),
               **verdict.to_payload()}
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[test-gate] suite {args.suite}{' ' + shards if shards else ''} : {len(files)} fichiers, "
          f"{verdict.passed} passés, {verdict.failed} en échec dont {len(verdict.known_failed)} connus, {verdict.skipped} sautés, "
          f"{payload['duration_seconds']} s")
    for label, rows in (("session non jugeable", verdict.session), ("échec NON listé", verdict.unknown),
                        ("entrée périmée (le test passe : la retirer)", verdict.stale),
                        ("échec connu non vu (le test n'a pas échoué)", verdict.unseen),
                        ("entrée à revoir (review_by dépassé)", verdict.expired), ("intermittent toléré (passé seul)", verdict.tolerated)):
        for row in rows:
            print(f"[test-gate]   {label} : {row}")
    print(f"[test-gate] {'VERT' if verdict.green else 'ROUGE'}")
    return 0 if verdict.green else 1


if __name__ == "__main__":
    raise SystemExit(main())
