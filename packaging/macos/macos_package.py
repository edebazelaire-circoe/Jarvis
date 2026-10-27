r"""Plan et vérification du paquet macOS de Jarvis (Slice 08 de jarvis-presentation-edition-v1-2).

Contrat : `docs/macos-portability.md` › *Paquet macOS*. Ce module ne CONSTRUIT aucun paquet : aucun Mac, aucun
identifiant de signature, et un paquet non éprouvé ne doit pas exister sous un nom qui laisse croire le contraire.
Il fait ce qui se vérifie sans Mac :

    python packaging/macos/macos_package.py check-pins            runtimes épinglés : forme, empreintes, alignement Windows
    python packaging/macos/macos_package.py plan --arch arm64     disposition du bundle Jarvis.app (JSON)
    python packaging/macos/macos_package.py verify <package>      un arbre de paquet macOS : manifeste, empreintes, canal,
                                                                  aucun fichier ni module réservé à Windows

`verify` réutilise `jarvis.private_runtime.verify_package` avec la disposition POSIX (`PackageLayout(platform=MACOS)`) :
une seule vérification de paquet pour les deux plateformes, plus les écarts propres à macOS (`platform_policy.json`).

Codes de sortie : 0 = conforme, 1 = problèmes listés sur stderr, 2 = usage.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:  # lancé comme script : le paquet `jarvis` du même dépôt
    sys.path.insert(0, str(REPO))

from jarvis import private_runtime as PR  # noqa: E402
from jarvis.installation import HostPlatform  # noqa: E402

RUNTIMES_FILE = HERE / "runtimes.json"
POLICY_FILE = HERE / "platform_policy.json"
WINDOWS_RUNTIMES_FILE = REPO / "packaging" / "windows" / "runtimes.json"
INFO_PLIST = HERE / "Info.plist"
ENTITLEMENTS = HERE / "jarvis.entitlements"
ARCHITECTURES = ("arm64", "x64")
RUNTIME_NAMES = ("python", "node")
BUNDLE = "Jarvis.app"
#: Dossier d'installation (`CODE_ROOT.parent`) dans le bundle : le même arbre que le paquet Windows.
PACKAGE_IN_BUNDLE = "Contents/Resources/package"
LAUNCHER_IN_BUNDLE = "Contents/MacOS/jarvis-launcher"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- épingles

def pin_problems(runtimes: dict, windows_runtimes: dict | None = None) -> list[str]:
    """Écarts de `runtimes.json` : chaque architecture épingle Python et Node par URL https, SHA-256, taille, source des
    sommes publiée par l'éditeur ; versions égales à celles du paquet Windows (un seul code, un seul Python)."""

    problems: list[str] = []
    archs = runtimes.get("architectures") if isinstance(runtimes.get("architectures"), dict) else {}
    if runtimes.get("schema") != "jarvis.package-runtimes":
        problems.append("schema: jarvis.package-runtimes attendu")
    for arch in ARCHITECTURES:
        block = archs.get(arch)
        if not isinstance(block, dict):
            problems.append(f"{arch}: architecture absente")
            continue
        for name in RUNTIME_NAMES:
            entry = block.get(name)
            if not isinstance(entry, dict):
                problems.append(f"{arch}.{name}: runtime absent")
                continue
            for key in ("url", "checksum_source"):
                if not str(entry.get(key) or "").startswith("https://"):
                    problems.append(f"{arch}.{name}.{key}: URL https attendue")
            if not _SHA256.match(str(entry.get("sha256") or "")):
                problems.append(f"{arch}.{name}.sha256: à épingler (64 caractères hexadécimaux attendus)")
            if not isinstance(entry.get("size"), int) or entry["size"] <= 0:
                problems.append(f"{arch}.{name}.size: taille en octets attendue")
            if not PR._package_relative(entry.get("executable")):
                problems.append(f"{arch}.{name}.executable: chemin relatif au runtime attendu")
            if windows_runtimes is not None:
                expected = ((windows_runtimes.get("runtimes") or {}).get(name) or {}).get("version")
                if entry.get("version") != expected:
                    problems.append(f"{arch}.{name}.version: {entry.get('version')} ≠ {expected} du paquet Windows")
    return problems


# ---------------------------------------------------------------------- disposition

def bundle_plan(arch: str, runtimes: dict) -> dict:
    """Disposition prévue de `Jarvis.app` pour une architecture (aucune E/S hors lecture des épingles)."""

    if arch not in ARCHITECTURES:
        raise ValueError(f"architecture inconnue {arch!r} (attendu : {', '.join(ARCHITECTURES)})")
    pins = runtimes["architectures"][arch]
    package = f"{BUNDLE}/{PACKAGE_IN_BUNDLE}"
    return {
        "bundle": BUNDLE,
        "architecture": arch,
        "launcher": {"path": f"{BUNDLE}/{LAUNCHER_IN_BUNDLE}",
                     "argv": [f"../Resources/package/{PR.RUNTIME_DIR}/{PR.PYTHON_DIR}/{pins['python']['executable']}",
                              "-B", "-m", "jarvis", "launch"]},
        "package_root": package,
        "code_root": f"{package}/{PR.APP_DIR}",
        "runtimes": {name: {"root": f"{package}/{PR.RUNTIME_DIR}/{name}",
                            "executable": f"{package}/{PR.RUNTIME_DIR}/{name}/{pins[name]['executable']}",
                            "version": pins[name]["version"], "sha256": pins[name]["sha256"]}
                     for name in RUNTIME_NAMES},
        "manifests": [f"{package}/{PR.RUNTIME_MANIFEST}", f"{package}/{PR.THIRD_PARTY_MANIFEST}"],
        "licenses": f"{package}/{PR.LICENSES_DIR}",
        "info_plist": f"{BUNDLE}/Contents/Info.plist",
        "entitlements": ENTITLEMENTS.name,
        "user_state": "~/Library/Application Support/CIRCOE/Jarvis (hors du bundle, jamais écrit dedans)",
        "exports": "~/Documents/Jarvis (export seulement)",
        "distribution": f"Jarvis-<version>-macos-{arch}.dmg, signé Developer ID et notarisé (non exécuté)",
        "supported": False,
        "support_gate": "HV-V12-MAC-01",
    }


# ---------------------------------------------------------------------- vérification

def platform_problems(install_root: Path, policy: dict) -> list[str]:
    """Ce qu'un paquet macOS ne doit jamais porter : fichiers Windows, modules réservés à Windows."""

    root = Path(install_root)
    suffixes = tuple(policy.get("windows_file_suffixes") or ())
    problems = [f"{relative}: fichier Windows dans un paquet macOS"
                for relative, _path in PR.iter_tree(root) if relative.lower().endswith(suffixes)]
    site = PR.PackageLayout(root, HostPlatform.MACOS).site_packages
    for module in sorted(policy.get("windows_only_packages") or {}):
        names = {module, module.replace("-", "_")}
        if any((site / name).exists() or any(site.glob(f"{name}-*.dist-info")) for name in names):
            problems.append(f"{module}: module réservé à Windows dans un paquet macOS")
    return problems


def verify(install_root: Path, policy: dict | None = None) -> tuple[dict | None, list[str]]:
    """`verify_package` (disposition POSIX) + écarts propres à macOS. Lecture seule."""

    layout = PR.PackageLayout(Path(install_root), HostPlatform.MACOS)
    manifest, problems = PR.verify_package(layout)
    return manifest, problems + platform_problems(layout.install_root, policy or load_json(POLICY_FILE))


# ---------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-pins")
    plan = sub.add_parser("plan")
    plan.add_argument("--arch", choices=ARCHITECTURES, required=True)
    check = sub.add_parser("verify")
    check.add_argument("package", type=Path)
    args = parser.parse_args(argv)
    if args.command == "check-pins":
        problems = pin_problems(load_json(RUNTIMES_FILE), load_json(WINDOWS_RUNTIMES_FILE))
    elif args.command == "plan":
        print(json.dumps(bundle_plan(args.arch, load_json(RUNTIMES_FILE)), indent=2, ensure_ascii=False))
        return 0
    else:
        _manifest, problems = verify(args.package)
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"macos_package {args.command}: {'OK' if not problems else f'{len(problems)} problème(s)'}",
          file=sys.stderr if problems else sys.stdout)
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
