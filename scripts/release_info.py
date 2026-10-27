#!/usr/bin/env python3
"""Identité d'un candidat de release (Slice 10, `docs/release.md` › *Release info*).

    python scripts/release_info.py --package DIR --installer FILE.exe --out release-info.json
                                   [--gate-report FILE ...] [--smoke-report FILE]

Écrit `release-info.json` : version et révision du paquet (relues dans son manifeste, après `verify_package`),
`package_sha256`, empreinte et taille de l'installeur, empreinte du zip accolé (relue dans la remorque), empreintes des
entrées du build À LA RÉVISION du paquet (`git show`, jamais l'arbre de travail), outils du poste de build, contexte
de la CI (`GITHUB_*`) et verdicts joints (portes de tests, essai du paquet). Le nom d'archive suggéré porte la version,
la révision et l'empreinte de l'installeur : un artefact est adressable par SHA et jamais réécrit sous le même nom.
Refuse (code 1) un paquet altéré, un installeur sans remorque valide, ou un verdict joint qui n'est pas vert.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis import private_runtime as PR  # noqa: E402 - après le chemin du dépôt

SCHEMA = "jarvis.release-info"
#: Entrées du build dont l'empreinte identifie la recette (lues à la révision du paquet).
BUILD_INPUTS = ("pyproject.toml", "packaging/windows/runtimes.json", "packaging/windows/requirements.lock",
                "packaging/windows/third_party_policy.json", "packaging/windows/setup_stub.cs",
                "packaging/windows/build_package.py")
SETUP_MAGIC = b"JVSETUP1"
CI_VARIABLES = ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_REF", "GITHUB_WORKFLOW",
                "RUNNER_OS", "RUNNER_ARCH")


class ReleaseInfoError(RuntimeError):
    """Candidat refusé : jamais une identité écrite pour un paquet douteux."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_show_sha256(revision: str, relative: str) -> str:
    done = subprocess.run(["git", "-C", str(ROOT), "show", f"{revision}:{relative}"], capture_output=True, check=False)
    if done.returncode != 0:
        raise ReleaseInfoError(f"`git show {revision[:12]}:{relative}` a échoué : "
                               f"{done.stderr.decode('utf-8', errors='replace').strip()}")
    return hashlib.sha256(done.stdout).hexdigest()


def installer_payload(installer: Path) -> dict:
    """Position, longueur et empreinte du zip accolé à l'amorce (remorque `JVSETUP1`)."""

    size = installer.stat().st_size
    with open(installer, "rb") as handle:
        if size < 24:
            raise ReleaseInfoError("installeur trop court")
        handle.seek(-24, os.SEEK_END)
        trailer = handle.read(24)
        if trailer[:8] != SETUP_MAGIC:
            raise ReleaseInfoError("remorque de l'installeur absente")
        offset, length = int.from_bytes(trailer[8:16], "little"), int.from_bytes(trailer[16:24], "little")
        if offset <= 0 or length <= 0 or offset + length > size - 24:
            raise ReleaseInfoError("remorque de l'installeur incohérente")
        handle.seek(offset)
        digest, left = hashlib.sha256(), length
        while left:
            block = handle.read(min(left, 1 << 20))
            if not block:
                raise ReleaseInfoError("zip accolé tronqué")
            digest.update(block)
            left -= len(block)
    return {"stub_bytes": offset, "payload_bytes": length, "payload_sha256": digest.hexdigest()}


def read_verdict(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseInfoError(f"verdict {path.name} illisible : {exc}") from exc
    green = payload.get("green")
    if green is not True:
        raise ReleaseInfoError(f"verdict {path.name} n'est pas vert (green={green!r})")
    return payload


def tool_version(argv: list[str]) -> str | None:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return (done.stdout or done.stderr).strip().splitlines()[0][:120] if done.returncode == 0 else None


def build(package: Path, installer: Path, *, gate_reports: list[Path], smoke_report: Path | None) -> dict:
    manifest, problems = PR.verify_package(PR.PackageLayout(package))
    if manifest is None or problems:
        raise ReleaseInfoError("paquet altéré : " + "; ".join(problems or ["manifeste absent"]))
    product = manifest.get("product") or {}
    revision = str(product.get("source_revision") or "")
    if len(revision) != 40:
        raise ReleaseInfoError(f"révision du paquet illisible : {revision!r}")
    payload = installer_payload(installer)
    installer_sha = sha256_file(installer)
    version = str(product.get("version") or "unknown")
    info = {
        "schema": SCHEMA, "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "product": {"name": product.get("name"), "edition": product.get("edition"), "version": version},
        "source_revision": revision,
        "package_sha256": manifest["package_sha256"],
        "runtimes": {name: {"version": entry.get("version"), "tree_sha256": entry.get("tree_sha256")}
                     for name, entry in (manifest.get("runtimes") or {}).items()},
        "installer": {"file": installer.name, "sha256": installer_sha, "bytes": installer.stat().st_size, "signed": False,
                      **payload},
        "build_inputs_sha256": {relative: git_show_sha256(revision, relative) for relative in BUILD_INPUTS},
        "build_host": {"os": platform.platform(), "python": sys.version.split()[0],
                       "git": tool_version(["git", "--version"])},
        "ci": {name: os.environ[name] for name in CI_VARIABLES if os.environ.get(name)},
        "verdicts": {path.name: {key: read_verdict(path).get(key) for key in ("suite", "shard", "passed", "failed",
                                                                              "known_failures_seen", "intermittent_tolerated")}
                     for path in gate_reports},
        "artifact_name": f"jarvis-{version}-{revision[:12]}-{installer_sha[:12]}",
        "unverified": ["code signing (HV-PACKAGE-10 / HV-INSTALL-04: installer unsigned)",
                       "clean Windows machine trial (HV-PACKAGE-01, HV-INSTALL-01, HV-E2E-01)"],
    }
    if smoke_report is not None:
        smoke = read_verdict(smoke_report)
        info["package_smoke"] = {"green": True, "steps": [step.get("step") for step in smoke.get("steps", [])]}
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", required=True)
    parser.add_argument("--installer", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--gate-report", action="append", default=[])
    parser.add_argument("--smoke-report")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    out = Path(args.out)
    if out.exists():
        print(f"[release-info] ÉCHEC : {out} existe déjà (une identité n'est jamais réécrite)", file=sys.stderr)
        return 1
    try:
        info = build(Path(args.package).resolve(), Path(args.installer).resolve(),
                     gate_reports=[Path(p) for p in args.gate_report],
                     smoke_report=Path(args.smoke_report) if args.smoke_report else None)
    except (ReleaseInfoError, OSError) as exc:
        print(f"[release-info] ÉCHEC : {exc}", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "artifact_name": info["artifact_name"], "package_sha256": info["package_sha256"],
                      "installer_sha256": info["installer"]["sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
