"""Installation, mise à jour et désinstallation du produit Windows (Slice 07, `docs/product-install.md` › *Installer*).

Exécuté par le Python **du paquet** : l'installeur (`JARVIS-Setup-<version>.exe`, amorce de
`packaging/windows/setup_stub.cs`) extrait le paquet à côté de la cible puis lance

    <paquet>\\runtime\\python\\python.exe -B -m jarvis.product_setup install --source <paquet> --move [...]

et la désinstallation de Windows (« Applications installées ») lance

    <installation>\\runtime\\python\\pythonw.exe -B -m jarvis.product_setup uninstall

Règles (contrat) :

- **le programme appartient à l'installeur, la maison appartient à JARVIS** : rien ici n'écrit, ne déplace ni n'efface
  `%LOCALAPPDATA%\\CIRCOE\\Jarvis` (données, réglages, présentations, `CONTEXT_GLOBAL`). Mise à jour, réparation
  (réinstaller la même version) et désinstallation la gardent intacte ; la désinstallation dit où elle reste ;
- **par utilisateur, sans droits d'administrateur** (recommandation sous HV-PACKAGE-10) : cible par défaut
  `%LOCALAPPDATA%\\Programs\\CIRCOE\\Jarvis`, raccourcis de l'utilisateur, clé de désinstallation sous `HKCU` ;
- **mise à jour atomique** : le paquet source est vérifié (`private_runtime.verify_package`) avant tout ; l'ancien
  programme est renommé `<cible>.previous-<horodatage>` (un JARVIS ouvert l'empêche : refus `jarvis_running`), le
  nouveau prend sa place, il est revérifié, puis seulement l'ancien est effacé ; tout échec remet l'ancien en place ;
- **cibles injectables** (essais, CI, déploiement silencieux) : `--target`, `--start-menu`, `--desktop`/`--no-desktop`,
  `--registry-file` (une ruche simulée en JSON au lieu de `HKCU`). Aucun essai n'écrit dans le vrai registre ni sur le
  vrai Bureau ;
- **visible** : `--progress` (une ligne JSON par étape) et `--result` (issue finale) sont lus par l'amorce ; un refus
  dit sa cause en mots de produit ; aucun secret n'est jamais écrit (rien d'ici n'en lit).

Bibliothèque standard + `jarvis.private_runtime` seulement (plus `win32com` pour les raccourcis) : ce module tourne
avant que le produit soit en place.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Protocol

from jarvis import private_runtime as PR
from jarvis.installation import LOCALAPPDATA_ENV, PRODUCT_DIR, VENDOR_DIR, product_home

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CIRCOE.Jarvis"
DISPLAY_NAME = "JARVIS — Presentation Edition"
PUBLISHER = "CIRCOE"
SHORTCUT_NAME = "JARVIS.lnk"
LAUNCH_ARGS = "-B -m jarvis launch"
PREVIOUS_SUFFIX = ".previous-"
#: Caractères refusés dans une cible : ils casseraient la ligne de commande de la désinstallation différée.
UNSAFE_TARGET_CHARS = frozenset('"%!^&|<>')
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000


class SetupError(RuntimeError):
    """Refus typé : `code` stable, message pour l'utilisateur, `detail` technique."""

    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------- ports (cibles injectables)


class Registry(Protocol):
    def write(self, values: Mapping[str, Any]) -> None: ...
    def read(self) -> dict[str, Any] | None: ...
    def delete(self) -> bool: ...


class WinRegistry:
    """`HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CIRCOE.Jarvis` (installation par utilisateur)."""

    def __init__(self, key: str = UNINSTALL_KEY) -> None:
        self.key = key

    def write(self, values: Mapping[str, Any]) -> None:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.key, 0, winreg.KEY_WRITE) as handle:
            for name, value in values.items():
                kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
                winreg.SetValueEx(handle, name, 0, kind, value)

    def read(self) -> dict[str, Any] | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key) as handle:
                values, index = {}, 0
                while True:
                    try:
                        name, value, _kind = winreg.EnumValue(handle, index)
                    except OSError:
                        return values
                    values[name] = value
                    index += 1
        except FileNotFoundError:
            return None

    def delete(self) -> bool:
        import winreg

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.key)
            return True
        except FileNotFoundError:
            return False


class FileRegistry:
    """Ruche simulée (essais, CI) : la clé de désinstallation dans un fichier JSON."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def write(self, values: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"key": "HKCU\\" + UNINSTALL_KEY, "values": dict(values)}, indent=2,
                                        ensure_ascii=False) + "\n", encoding="utf-8")

    def read(self) -> dict[str, Any] | None:
        try:
            return dict(json.loads(self.path.read_text(encoding="utf-8")).get("values") or {})
        except FileNotFoundError:
            return None

    def delete(self) -> bool:
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False


class Shortcuts(Protocol):
    def create(self, path: Path, *, target: Path, arguments: str, working_dir: Path, description: str,
               icon: Path) -> None: ...


class ShellShortcuts:
    """Raccourcis `.lnk` par `WScript.Shell` (pywin32, livré dans le paquet)."""

    def create(self, path: Path, *, target: Path, arguments: str, working_dir: Path, description: str,
               icon: Path) -> None:
        import pythoncom
        import win32com.client

        def save() -> None:
            # Objets COM locaux à cette fonction : libérés AVANT `CoUninitialize` (sinon violation d'accès à leur
            # destruction tardive).
            link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
            link.TargetPath = str(target)
            link.Arguments = arguments
            link.WorkingDirectory = str(working_dir)
            link.Description = description
            link.IconLocation = f"{icon},0"
            link.Save()

        path.parent.mkdir(parents=True, exist_ok=True)
        pythoncom.CoInitialize()
        try:
            save()
        finally:
            pythoncom.CoUninitialize()


def special_folder(name: str) -> Path:
    """`Programs` (menu Démarrer de l'utilisateur) ou `Desktop`, par `WScript.Shell.SpecialFolders`."""

    import pythoncom
    import win32com.client

    def read() -> str:
        return str(win32com.client.Dispatch("WScript.Shell").SpecialFolders(name) or "")

    pythoncom.CoInitialize()
    try:
        value = read()
    finally:
        pythoncom.CoUninitialize()
    if not value:
        raise SetupError("special_folder_unavailable", f"Windows n'a pas donné le dossier {name}.")
    return Path(value)


# ---------------------------------------------------------------------- plan


@dataclass
class Targets:
    target: Path
    start_menu: Path | None
    desktop: Path | None
    registry: Registry
    home: Path | None

    @property
    def shortcut_paths(self) -> list[Path]:
        return [folder / SHORTCUT_NAME for folder in (self.start_menu, self.desktop) if folder is not None]


def default_target(environ: Mapping[str, str]) -> Path:
    base = str(environ.get(LOCALAPPDATA_ENV) or "").strip()
    if not base:
        raise SetupError("localappdata_missing", "Le dossier des applications de votre profil Windows est introuvable.",
                         f"{LOCALAPPDATA_ENV} absent")
    return Path(base) / "Programs" / VENDOR_DIR / PRODUCT_DIR


def resolve_targets(args: argparse.Namespace, environ: Mapping[str, str]) -> Targets:
    target = Path(args.target) if getattr(args, "target", None) else default_target(environ)
    registry = FileRegistry(Path(args.registry_file)) if getattr(args, "registry_file", None) else WinRegistry()
    start_menu = Path(args.start_menu) if getattr(args, "start_menu", None) else None
    desktop = Path(args.desktop) if getattr(args, "desktop", None) else None
    if start_menu is None and not getattr(args, "registry_file", None):
        start_menu = special_folder("Programs")
    if desktop is None and not getattr(args, "no_desktop", False) and not getattr(args, "registry_file", None):
        desktop = special_folder("Desktop")
    try:
        home = product_home(environ).root
    except Exception:  # noqa: BLE001 - argued: without LOCALAPPDATA the home-overlap check below is moot
        home = None
    return Targets(target=target.resolve(), start_menu=start_menu, desktop=desktop, registry=registry, home=home)


def check_target(targets: Targets) -> None:
    text = str(targets.target)
    if any(char in UNSAFE_TARGET_CHARS for char in text):
        raise SetupError("target_unsafe", "Ce dossier d'installation contient un caractère refusé.", text)
    if targets.home is not None:
        home = targets.home.resolve()
        if targets.target == home or home in targets.target.parents or targets.target in home.parents:
            raise SetupError("target_overlaps_home", "JARVIS ne s'installe pas dans son propre dossier de données.",
                             f"{targets.target} vs {home}")


# ---------------------------------------------------------------------- étapes


class Progress:
    def __init__(self, path: Path | None, *, echo: bool) -> None:
        self.path = path
        self.echo = echo

    def step(self, phase: str, message: str, **data: Any) -> None:
        row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "phase": phase, "message": message, **data}
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if self.echo and sys.stdout is not None:
            print(f"[setup] {message}", flush=True)


def _version(manifest: Mapping[str, Any]) -> str:
    return str((manifest.get("product") or {}).get("version") or "0")


def launcher_running(home: Path | None, *, alive: Callable[[int], bool]) -> bool:
    """Vrai si un lanceur vivant est publié dans la maison (`runtime\\launcher.json`)."""

    if home is None:
        return False
    try:
        state = json.loads((home / "runtime" / "launcher.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    pid = state.get("pid") if isinstance(state, dict) else None
    return isinstance(pid, int) and alive(pid)


def pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def dir_size_kb(root: Path) -> int:
    total = 0
    for _relative, path in PR.iter_tree(root):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total // 1024


def install(source: Path, targets: Targets, *, move: bool, progress: Progress,
            shortcuts: Shortcuts | None = None, alive: Callable[[int], bool] = pid_alive,
            verify: Callable[[PR.PackageLayout], tuple[dict | None, list[str]]] = PR.verify_package) -> dict[str, Any]:
    """Installe (ou met à jour, ou répare) le paquet `source` dans `targets.target`. Voir l'en-tête du module."""

    check_target(targets)
    source = Path(source).resolve()
    progress.step("verify_source", "Vérification du paquet…")
    manifest, problems = verify(PR.PackageLayout(source))
    if manifest is None or problems:
        raise SetupError("package_damaged", "Le fichier d'installation est abîmé : téléchargez-le à nouveau.",
                         "; ".join(problems)[:1000])
    version = _version(manifest)
    target = targets.target
    previous: Path | None = None
    existing = None
    if target.exists():
        try:
            existing = PR.PackageLayout(target).manifest()
        except ValueError:
            existing = {"product": {"version": "?"}}
        if existing is None and any(target.iterdir()):
            raise SetupError("target_not_empty", "Ce dossier contient déjà autre chose que JARVIS.", str(target))
    if launcher_running(targets.home, alive=alive):
        raise SetupError("jarvis_running", "JARVIS est ouvert : quittez-le, puis relancez l'installation.")
    mode = "install" if existing is None else ("repair" if _version(existing) == version else "update")
    progress.step("plan", {"install": "Installation de JARVIS…", "repair": "Réparation de JARVIS…",
                           "update": "Mise à jour de JARVIS…"}[mode], mode=mode, version=version)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        previous = target.with_name(target.name + PREVIOUS_SUFFIX + utc_stamp())
        try:
            os.replace(target, previous)
        except OSError as exc:
            raise SetupError("jarvis_running", "Des fichiers de JARVIS sont encore utilisés : quittez JARVIS, puis "
                             "relancez l'installation.", f"{type(exc).__name__}: {exc}") from exc
    try:
        progress.step("copy", "Mise en place des fichiers…")
        if move:
            try:
                os.replace(source, target)
            except OSError:
                shutil.copytree(source, target)
        else:
            shutil.copytree(source, target)
        progress.step("verify_target", "Vérification de l'installation…")
        _installed, after = verify(PR.PackageLayout(target))
        if after:
            raise SetupError("installed_copy_damaged", "La copie installée ne correspond pas au paquet.",
                             "; ".join(after)[:1000])
        progress.step("shortcuts", "Raccourcis…")
        write_shortcuts(target, targets, shortcuts or ShellShortcuts())
        targets.registry.write(registration(target, version))
    except BaseException as exc:
        progress.step("rollback", "Échec : l'installation précédente est remise en place.",
                      error=f"{type(exc).__name__}: {exc}"[:300])
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if previous is not None and previous.exists():
            os.replace(previous, target)
        raise
    leftover = None
    if previous is not None:
        progress.step("cleanup", "Nettoyage de l'ancienne version…")
        shutil.rmtree(previous, ignore_errors=True)
        leftover = str(previous) if previous.exists() else None
    progress.step("done", "JARVIS est installé.", mode=mode, version=version)
    return {"ok": True, "mode": mode, "version": version, "target": str(target),
            "shortcuts": [str(path) for path in targets.shortcut_paths], "previous_leftover": leftover,
            "data_home": str(targets.home) if targets.home else None, "data_kept": True}


def write_shortcuts(target: Path, targets: Targets, shortcuts: Shortcuts) -> None:
    layout = PR.PackageLayout(target)
    pythonw = layout.python_dir / "pythonw.exe"
    for path in targets.shortcut_paths:
        shortcuts.create(path, target=pythonw, arguments=LAUNCH_ARGS, working_dir=target,
                         description="Ouvrir JARVIS", icon=pythonw)


def registration(target: Path, version: str) -> dict[str, Any]:
    layout = PR.PackageLayout(target)
    pythonw = layout.python_dir / "pythonw.exe"
    uninstall = f'"{pythonw}" -B -m jarvis.product_setup uninstall'
    return {"DisplayName": DISPLAY_NAME, "DisplayVersion": version, "Publisher": PUBLISHER,
            "InstallLocation": str(target), "DisplayIcon": str(pythonw), "UninstallString": uninstall,
            "QuietUninstallString": uninstall + " --quiet", "NoModify": 1, "NoRepair": 1,
            "EstimatedSize": dir_size_kb(target), "InstallDate": datetime.now().strftime("%Y%m%d")}


def uninstall(targets: Targets, *, progress: Progress, alive: Callable[[int], bool] = pid_alive,
              running_from: Path | None = None, spawn: Callable[..., Any] = subprocess.Popen) -> dict[str, Any]:
    """Retire le programme, ses raccourcis et sa clé ; la maison (données) reste. Lancé depuis le programme lui-même
    (`running_from`), l'effacement du dossier est confié à un `cmd.exe` détaché qui attend la fin de ce processus."""

    check_target(targets)
    target = targets.target
    if launcher_running(targets.home, alive=alive):
        raise SetupError("jarvis_running", "JARVIS est ouvert : quittez-le, puis relancez la désinstallation.")
    if target.exists():
        try:
            manifest = PR.PackageLayout(target).manifest()
        except ValueError:
            manifest = {}
        if manifest is None:
            raise SetupError("not_a_jarvis_folder", "Ce dossier ne contient pas JARVIS : rien n'est effacé.", str(target))
    progress.step("shortcuts", "Retrait des raccourcis…")
    for path in targets.shortcut_paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass  # intentional: already removed by hand
    targets.registry.delete()
    deferred = False
    if target.exists():
        progress.step("files", "Retrait des fichiers du programme…")
        inside = running_from is not None and (running_from == target or target in running_from.parents)
        if inside:
            deferred = True
            command = f'ping 127.0.0.1 -n 4 > nul & rmdir /s /q "{target}"'
            spawn(["cmd.exe", "/d", "/c", command], cwd=str(target.parent), close_fds=True,
                  creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            shutil.rmtree(target)
    progress.step("done", "JARVIS est désinstallé. Vos présentations et réglages sont conservés.")
    return {"ok": True, "target": str(target), "deferred_removal": deferred,
            "data_home": str(targets.home) if targets.home else None, "data_kept": True}


# ---------------------------------------------------------------------- ligne de commande


def _ask(question: str) -> bool:
    if os.name != "nt":
        return True
    import ctypes

    return ctypes.windll.user32.MessageBoxW(None, question, "JARVIS", 0x4 | 0x20 | 0x40000) == 6  # YES/NO, IDYES


def _tell(text: str, *, error: bool = False) -> None:
    if sys.stdout is not None and sys.stdout.isatty():
        print(text)
        return
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "JARVIS", (0x10 if error else 0x40) | 0x40000)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m jarvis.product_setup", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "uninstall", "status"):
        command = sub.add_parser(name)
        command.add_argument("--target")
        command.add_argument("--start-menu")
        command.add_argument("--desktop")
        command.add_argument("--no-desktop", action="store_true")
        command.add_argument("--registry-file")
        command.add_argument("--result")
        command.add_argument("--progress")
        command.add_argument("--quiet", action="store_true")
        if name == "install":
            command.add_argument("--source", required=True)
            command.add_argument("--move", action="store_true")
    return parser


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    progress = Progress(Path(args.progress) if args.progress else None, echo=sys.stdout is not None)
    result: dict[str, Any]
    try:
        if args.command == "uninstall" and not args.target:
            registered = (FileRegistry(Path(args.registry_file)) if args.registry_file else WinRegistry()).read() or {}
            args.target = registered.get("InstallLocation") or str(PR.package_layout().install_root
                                                                    if PR.package_layout() else "")
            if not args.target:
                raise SetupError("not_installed", "JARVIS n'est pas installé pour cet utilisateur.")
        targets = resolve_targets(args, env)
        if args.command == "status":
            result = {"ok": True, "registered": targets.registry.read(), "target": str(targets.target),
                      "installed": PR.PackageLayout(targets.target).manifest_path.is_file()}
        elif args.command == "install":
            result = install(Path(args.source), targets, move=args.move, progress=progress)
        else:
            if not args.quiet and not _ask("Désinstaller JARVIS ?\n\nVos présentations et vos réglages restent dans "
                                           "votre profil Windows (%LOCALAPPDATA%\\CIRCOE\\Jarvis)."):
                result = {"ok": False, "code": "cancelled", "message": "Désinstallation annulée."}
            else:
                layout = PR.package_layout()
                result = uninstall(targets, progress=progress,
                                   running_from=layout.install_root.resolve() if layout else None)
                if not args.quiet:
                    _tell("JARVIS est désinstallé.\n\nVos présentations et vos réglages sont conservés dans "
                          "%LOCALAPPDATA%\\CIRCOE\\Jarvis.")
    except SetupError as exc:
        result = {"ok": False, "code": exc.code, "message": str(exc), "detail": exc.detail}
        progress.step("failed", str(exc), code=exc.code)
        if args.command == "uninstall" and not args.quiet:
            _tell(str(exc), error=True)
    except Exception as exc:  # noqa: BLE001 - surfaced: typed result + visible message, never a silent exit
        result = {"ok": False, "code": "setup_failed", "message": "L'installation a échoué.",
                  "detail": f"{type(exc).__name__}: {exc}"[:1000]}
        progress.step("failed", result["message"], code="setup_failed", detail=result["detail"])
    if args.result:
        Path(args.result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if sys.stdout is not None and (args.quiet or sys.stdout.isatty() or not args.result):
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
