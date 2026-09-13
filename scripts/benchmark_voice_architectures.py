#!/usr/bin/env python3
"""CLI entry point for the deterministic offline voice architecture suite."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from jarvis.runtime.voice_architecture_benchmark import (
    BenchmarkEvidenceRun,
    default_suite_path,
    load_benchmark_suite,
    required_evidence_nodes,
    run_cross_architecture_benchmark,
)


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run production-seam offline voice architecture benchmark")
    parser.add_argument("--suite", type=Path, default=default_suite_path())
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    suite = load_benchmark_suite(args.suite)
    nodes = required_evidence_nodes(suite)
    command = (
        sys.executable, "-m", "pytest", *nodes, "-q", "-W", "error",
        "-o", "asyncio_default_fixture_loop_scope=function", "--tb=short",
    )
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode:
        return completed.returncode
    evidence = BenchmarkEvidenceRun(
        ("python", "-m", "pytest", *nodes, "-q", "-W", "error",
         "-o", "asyncio_default_fixture_loop_scope=function", "--tb=short"),
        completed.returncode,
        frozenset(nodes),
    )
    _report, path = run_cross_architecture_benchmark(
        suite_path=args.suite, output_root=args.output_root, evidence_run=evidence)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
