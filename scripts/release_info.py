#!/usr/bin/env python3
"""Identité d'un candidat de release (Slice 10, `docs/release.md` › *Release info*).

    python scripts/release_info.py --package DIR --installer FILE.exe --out release-info.json
                                   --gate-report FILE [--gate-report FILE ...] --smoke-report FILE

Écrit `release-info.json` : version et révision du paquet (relues dans son manifeste, après `verify_package`),
`package_sha256`, empreinte et taille de l'installeur, empreinte du zip accolé (relue dans la remorque), empreintes des
entrées du build À LA RÉVISION du paquet (`git show`, jamais l'arbre de travail), outils du poste de build, contexte
de la CI (`GITHUB_*`) et verdicts joints (portes de tests, essai du paquet). Le nom d'archive suggéré porte la version,
la révision et l'empreinte de l'installeur : un artefact est adressable par SHA et jamais réécrit sous le même nom.
Refuse (code 1) un paquet altéré, un installeur sans remorque valide, un verdict joint qui n'est pas vert, et toute
paire qui ne se tient pas (QA S10 R2, m7) : au moins un rapport de porte vert, tous faits à la révision du paquet ;
le rapport `package_smoke` vert, fait sur CET installeur (même SHA-256) et ayant installé CE paquet ; le paquet
embarqué dans l'installeur (manifeste lu dans le zip accolé) égal au paquet déclaré (`package_sha256`,
`source_revision`) ; en CI, `GITHUB_SHA` égal à la révision.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

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


class _Slice(io.RawIOBase):
    """Fenêtre en lecture seule sur `[offset, offset + length)` d'un fichier : le zip accolé, sans le recopier."""

    def __init__(self, handle, offset: int, length: int) -> None:
        self._handle, self._offset, self._length, self._position = handle, offset, length, 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, position: int, whence: int = os.SEEK_SET) -> int:
        base = {os.SEEK_SET: 0, os.SEEK_CUR: self._position, os.SEEK_END: self._length}[whence]
        self._position = max(0, min(self._length, base + position))
        return self._position

    def readinto(self, buffer) -> int:
        size = min(len(buffer), self._length - self._position)
        if size <= 0:
            return 0
        self._handle.seek(self._offset + self._position)
        data = self._handle.read(size)
        buffer[:len(data)] = data
        self._position += len(data)
        return len(data)


def embedded_manifest(installer: Path, payload: dict) -> dict:
    """Le manifeste du paquet EMBARQUÉ dans l'installeur (lu dans le zip accolé, jamais extrait sur le disque)."""

    with open(installer, "rb") as handle:
        window = io.BufferedReader(_Slice(handle, payload["stub_bytes"], payload["payload_bytes"]))
        try:
            with zipfile.ZipFile(window) as bundle:
                return json.loads(bundle.read(PR.RUNTIME_MANIFEST).decode("utf-8"))
        except (zipfile.BadZipFile, KeyError, ValueError) as exc:
            raise ReleaseInfoError(f"paquet embarqué dans l'installeur illisible ({PR.RUNTIME_MANIFEST}) : {exc}") from exc


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


def build(package: Path, installer: Path, *, gate_reports: list[Path], smoke_report: Path | None,
          environ: dict[str, str] | None = None) -> dict:
    env = os.environ if environ is None else environ
    manifest, problems = PR.verify_package(PR.PackageLayout(package))
    if manifest is None or problems:
        raise ReleaseInfoError("paquet altéré : " + "; ".join(problems or ["manifeste absent"]))
    product = manifest.get("product") or {}
    revision = str(product.get("source_revision") or "")
    if len(revision) != 40:
        raise ReleaseInfoError(f"révision du paquet illisible : {revision!r}")
    if env.get("GITHUB_SHA") and env["GITHUB_SHA"] != revision:
        raise ReleaseInfoError(f"le paquet est de la révision {revision[:12]}, la CI construit {env['GITHUB_SHA'][:12]}")
    payload = installer_payload(installer)
    installer_sha = sha256_file(installer)
    version = str(product.get("version") or "unknown")
    embedded = embedded_manifest(installer, payload)
    embedded_product = embedded.get("product") or {}
    if embedded.get("package_sha256") != manifest["package_sha256"] or embedded_product.get("source_revision") != revision:
        raise ReleaseInfoError(
            f"l'installeur embarque un autre paquet : {str(embedded.get('package_sha256'))[:12]} de la révision "
            f"{str(embedded_product.get('source_revision'))[:12]}, déclaré {manifest['package_sha256'][:12]} de {revision[:12]}")
    if not gate_reports:
        raise ReleaseInfoError("aucun rapport de porte des tests : une identité exige au moins un verdict vert")
    verdicts = {}
    for path in gate_reports:
        verdict = read_verdict(path)
        if verdict.get("source_revision") != revision:
            raise ReleaseInfoError(f"verdict {path.name} fait à la révision {str(verdict.get('source_revision'))[:12]}, "
                                   f"pas à celle du paquet ({revision[:12]})")
        verdicts[path.name] = {key: verdict.get(key) for key in ("suite", "shard", "only", "files", "passed", "failed", "skipped",
                                                                 "known_failures_seen", "intermittent_tolerated",
                                                                 "duration_seconds", "source_revision")}
    if smoke_report is None:
        raise ReleaseInfoError("rapport de l'essai du paquet installé (package_smoke) absent")
    smoke = read_verdict(smoke_report)
    if smoke.get("installer_sha256") != installer_sha:
        raise ReleaseInfoError(f"l'essai {smoke_report.name} a installé un autre installeur "
                               f"({str(smoke.get('installer_sha256'))[:12]}, déclaré {installer_sha[:12]})")
    installed = [step.get("package_sha256") for step in smoke.get("steps", []) if step.get("step") == "install"]
    if installed != [manifest["package_sha256"]]:
        raise ReleaseInfoError(f"l'essai {smoke_report.name} n'a pas installé ce paquet (étape install : {installed!r})")
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
        "verdicts": verdicts,
        "package_smoke": {"green": True, "installer_sha256": smoke.get("installer_sha256"),
                          "finished_at": smoke.get("finished_at"), "steps": [step.get("step") for step in smoke.get("steps", [])]},
        "artifact_name": f"jarvis-{version}-{revision[:12]}-{installer_sha[:12]}",
        "unverified": ["code signing (HV-PACKAGE-10 / HV-INSTALL-04: installer unsigned)",
                       "clean Windows machine trial (HV-PACKAGE-01, HV-INSTALL-01, HV-E2E-01)"],
    }
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", required=True)
    parser.add_argument("--installer", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--gate-report", action="append", default=[], help="rapport vert de la porte des tests ; au moins un")
    parser.add_argument("--smoke-report", required=True, help="rapport vert de scripts/package_smoke.py sur CET installeur")
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
