"""Installation, mise à jour et désinstallation du produit Windows (Slice 07, `docs/product-install.md` › *Installer*).

Exécuté par le Python **du paquet** : l'installeur (`JARVIS-Setup-<version>.exe`, amorce de
`packaging/windows/setup_stub.cs`) extrait le paquet à côté de la cible puis lance

    <paquet>\\runtime\\python\\python.exe -B -m jarvis.product_setup install --source <paquet> --target <cible> [...]

(`--move` existe pour un appelant qui veut déplacer le paquet au lieu de le copier ; l'amorce ne le passe pas : le
Python qui tourne vit dans le paquet et Windows refuserait le déplacement) et la désinstallation de Windows
(« Applications installées ») lance

    <installation>\\runtime\\python\\pythonw.exe -B -m jarvis.product_setup uninstall

Règles (contrat) :

- **le programme appartient à l'installeur, la maison appartient à JARVIS** : rien ici n'écrit, ne déplace ni n'efface
  `%LOCALAPPDATA%\\CIRCOE\\Jarvis` (données, réglages, présentations, `CONTEXT_GLOBAL`). Mise à jour, réparation
  (réinstaller la même version) et désinstallation la gardent intacte ; la désinstallation dit où elle reste ;
- **par utilisateur, sans droits d'administrateur** (recommandation sous HV-PACKAGE-10) : cible par défaut
  `%LOCALAPPDATA%\\Programs\\CIRCOE\\Jarvis`, raccourcis de l'utilisateur, clé de désinstallation sous `HKCU` ;
- **rien n'est effacé sans preuve que c'est JARVIS** (`folder_kind`) : marqueur produit de la Slice 02 dans `app\\`
  ET `runtime-manifest.json` lisible au nom du produit ; ou un reste reconnu par l'état d'opération
  `<cible>.setup-state.json` (posé à côté de la cible avant toute opération destructrice, retiré quand elle a abouti)
  et dont chaque entrée figure dans la liste qu'il a notée. Tout autre dossier est refusé (`not_a_jarvis_folder`,
  `target_not_empty`) ;
- **mise à jour atomique** : le paquet source est vérifié (`private_runtime.verify_package`) avant tout ; l'ancien
  programme est renommé `<cible>.previous-<horodatage>` (un JARVIS ouvert l'empêche : refus `jarvis_running`), le
  nouveau prend sa place, il est revérifié, puis seulement l'ancien est effacé. Tout échec écarte la copie ratée
  (renommée `<cible>.failed-<horodatage>`, avec reprises) puis remet l'ancien en place ; si un fichier verrouillé
  l'empêche, le refus `rollback_failed` le dit et l'état d'opération garde l'installation suivante capable de réparer ;
- **désinstallation réparable** : raccourcis retirés d'abord (ils lanceraient un programme à moitié effacé) ; la clé
  de désinstallation n'est retirée qu'une fois le dossier effectivement supprimé. Lancée depuis le programme, la
  suppression est confiée à un script `cmd.exe` détaché qui attend la FIN RÉELLE de ce processus (PID), puis reprend
  la suppression tant que des fichiers restent verrouillés (antivirus) ; son journal : `%TEMP%\\jarvis-uninstall.log` ;
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
import tempfile
import time
from typing import Any, Protocol

from jarvis import private_runtime as PR
from jarvis.domain.errors import ConfigurationError
from jarvis.installation import LOCALAPPDATA_ENV, PRODUCT_DIR, VENDOR_DIR, product_home, read_product_marker

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CIRCOE.Jarvis"
DISPLAY_NAME = "JARVIS — Presentation Edition"
PUBLISHER = "CIRCOE"
SHORTCUT_NAME = "JARVIS.lnk"
LAUNCH_ARGS = "-B -m jarvis launch"
PREVIOUS_SUFFIX = ".previous-"
FAILED_SUFFIX = ".failed-"
#: État d'une opération destructrice en cours, À CÔTÉ de la cible (jamais dedans : il survit à l'effacement).
STATE_SUFFIX = ".setup-state.json"
STATE_SCHEMA = "jarvis.setup-state"
#: Pauses entre les reprises d'un renommage ou d'une suppression (antivirus, fichier encore ouvert) : ~7 s au total.
RETRY_DELAYS_S: tuple[float, ...] = (0.2, 0.5, 1.0, 2.0, 3.0)
#: Suppression différée : attente de la fin du processus (secondes), puis nombre de reprises espacées de ~3 s.
DEFERRED_WAIT_S = 1800
DEFERRED_ATTEMPTS = 40
UNINSTALL_LOG = "jarvis-uninstall.log"
#: Caractères refusés dans une cible : ils casseraient la ligne de commande de la désinstallation différée.
UNSAFE_TARGET_CHARS = frozenset('"%!^&|<>')
CREATE_NO_WINDOW = 0x08000000


class SetupError(RuntimeError):
    """Refus typé : `code` stable, message pour l'utilisateur, `detail` technique."""

    def __init__(self, code: str, message: str, detail: str = "", **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail
        #: Champs ajoutés tels quels à l'issue (`--result`) : `rolled_back`, `had_previous`, chemins laissés…
        self.extra = extra


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------- ports (cibles injectables)


class Registry(Protocol):
    def write(self, values: Mapping[str, Any]) -> None: ...
    def read(self) -> dict[str, Any] | None: ...
    def delete(self) -> bool: ...
    #: La même suppression en une ligne de script `cmd.exe` (suppression différée, après la fin de ce processus).
    def removal_command(self) -> str: ...


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

    def removal_command(self) -> str:
        return f'"%SystemRoot%\\System32\\reg.exe" delete "HKCU\\{self.key}" /f >nul 2>&1'


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

    def removal_command(self) -> str:
        return f'del /f /q "{self.path}" >nul 2>&1'


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
        """Une ligne de progression. Jamais une exception : l'amorce lit ce fichier pendant qu'il s'écrit (essai réel :
        une lecture concurrente refusait l'ouverture et faisait tomber l'installation sans issue écrite). Quelques
        reprises brèves, puis la ligne est abandonnée : l'issue (`--result`) reste la source de vérité."""

        row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "phase": phase, "message": message, **data}
        if self.path is not None:
            line = json.dumps(row, ensure_ascii=False) + "\n"
            for attempt in range(10):
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as handle:
                        handle.write(line)
                    break
                except OSError:
                    time.sleep(0.05 * (attempt + 1))  # intentional: progress is advisory, the result file is the truth
        if self.echo and sys.stdout is not None:
            print(f"[setup] {message}", flush=True)


def _version(manifest: Mapping[str, Any]) -> str:
    return str((manifest.get("product") or {}).get("version") or "0")


def launcher_running(home: Path | None, *, alive: Callable[[int], bool],
                     ref_alive: Callable[[str], bool] | None = None) -> bool:
    """Vrai si un lanceur vivant est publié dans la maison (`runtime\\launcher.json`)."""

    # PID et heure de création comparés quand l'état les porte (`product_launcher.launcher_alive`, I-009 point 2).
    from jarvis.runtime.product_launcher import launcher_alive

    if home is None:
        return False
    try:
        state = json.loads((home / "runtime" / "launcher.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return launcher_alive(state, pid_alive=alive, ref_alive=ref_alive)


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


def copy_matches(source: Path, target: Path) -> list[str]:
    """La copie a-t-elle exactement les fichiers (chemins et tailles) du paquet vérifié, et le même manifeste ?

    Le paquet source vient d'être vérifié en entier (empreintes). Le refaire sur la copie relirait chaque fichier une
    seconde fois : sur un poste protégé par l'antivirus, chaque première lecture d'un fichier neuf est analysée
    (mesuré : ~3,5 min pour 11 000 fichiers). La copie est donc vérifiée par sa forme exacte ; une installation
    altérée plus tard est trouvée par « Vérifier l'installation » (`verify_package`, empreintes complètes).
    """

    def listing(root: Path) -> dict[str, int]:
        return {relative: path.stat().st_size for relative, path in PR.iter_tree(root)}

    expected, actual = listing(source), listing(target)
    problems = [f"{name}: absent de la copie" for name in sorted(set(expected) - set(actual))[:20]]
    problems += [f"{name}: en trop dans la copie" for name in sorted(set(actual) - set(expected))[:20]]
    problems += [f"{name}: taille différente" for name in sorted(set(expected) & set(actual))
                 if expected[name] != actual[name]][:20]
    if (source / PR.RUNTIME_MANIFEST).read_bytes() != (target / PR.RUNTIME_MANIFEST).read_bytes():
        problems.append(f"{PR.RUNTIME_MANIFEST}: différent")
    return problems


# ---------------------------------------------------------------------- identité du dossier et état d'opération


def is_jarvis_program(folder: Path) -> bool:
    """Vrai seulement avec les DEUX preuves : marqueur produit de la Slice 02 (`app\\jarvis-product.json`, schéma,
    fournisseur et produit attendus) ET `runtime-manifest.json` lisible, de schéma connu, au nom du produit."""

    layout = PR.PackageLayout(folder)
    try:
        manifest = layout.manifest()
    except ValueError:
        return False
    if not manifest or (manifest.get("product") or {}).get("name") != PRODUCT_DIR:
        return False
    try:
        marker = read_product_marker(layout.app)
    except ConfigurationError:
        return False
    return bool(marker) and marker.get("vendor") == VENDOR_DIR and marker.get("product") == PRODUCT_DIR


def state_path(target: Path) -> Path:
    return target.with_name(target.name + STATE_SUFFIX)


def read_state(target: Path) -> dict[str, Any] | None:
    """L'état d'opération de CETTE cible, ou `None` (absent, illisible, ou pour une autre cible : jamais une preuve)."""

    try:
        state = json.loads(state_path(target).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None  # intentional: an unreadable state proves nothing; the folder is then judged on its own proofs
    if not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA or state.get("target") != str(target):
        return None
    return state


def write_state(target: Path, operation: str, *, entries: set[str], **data: Any) -> None:
    payload = {"schema": STATE_SCHEMA, "schema_version": 1, "operation": operation, "target": str(target),
               "entries": sorted(entries), "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               **data}
    path = state_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def restore_state(target: Path, state: Mapping[str, Any] | None) -> None:
    """Remet l'état d'opération tel qu'il était (`None` : aucun)."""

    if state is None:
        clear_state(target)
        return
    path = state_path(target)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(dict(state), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def clear_state(target: Path) -> None:
    try:
        state_path(target).unlink()
    except FileNotFoundError:
        pass  # intentional: no operation was pending


def free_sibling(target: Path, suffix: str) -> Path:
    """`<cible><suffixe><horodatage>` libre (deux opérations dans la même seconde ne se marchent jamais dessus)."""

    stamp = utc_stamp()
    candidate = target.with_name(target.name + suffix + stamp)
    index = 2
    while candidate.exists():
        candidate = target.with_name(f"{target.name}{suffix}{stamp}-{index}")
        index += 1
    return candidate


def top_entries(folder: Path) -> set[str]:
    try:
        return {child.name for child in folder.iterdir()}
    except (FileNotFoundError, NotADirectoryError):
        return set()


def folder_kind(target: Path) -> str:
    """`absent`, `empty`, `jarvis` (les deux preuves de `is_jarvis_program`), `leftover` (reste d'une opération de
    JARVIS : état d'opération de CETTE cible, et chaque entrée du dossier figure dans la liste qu'il a notée), ou
    `foreign` : un dossier étranger n'est jamais effacé ni remplacé."""

    if not target.exists():
        return "absent"
    if not target.is_dir():
        return "foreign"
    entries = top_entries(target)
    if not entries:
        return "empty"
    if is_jarvis_program(target):
        return "jarvis"
    state = read_state(target)
    if state is not None and entries <= set(state.get("entries") or ()):
        return "leftover"
    return "foreign"


# ---------------------------------------------------------------------- reprises (antivirus, fichier encore ouvert)


def _retry(operation: Callable[[], None], *, done: Callable[[], bool]) -> bool:
    """`operation`, puis reprises espacées de `RETRY_DELAYS_S` jusqu'à `done()`. Vrai si c'est fait."""

    for delay in (0.0, *RETRY_DELAYS_S):
        if delay:
            time.sleep(delay)
        try:
            operation()
        except OSError:
            pass  # intentional: retried below; the caller reports what is left with its own sentence
        if done():
            return True
    return False


def _rmtree_once(folder: Path) -> None:
    def writable_then_retry(function: Callable[[str], Any], path: str, _exc: BaseException) -> None:
        try:
            os.chmod(path, 0o666)
            function(path)
        except OSError:
            pass  # intentional: a locked file stays; `remove_tree` checks what is left and retries

    if folder.exists():
        shutil.rmtree(folder, onexc=writable_then_retry)


def remove_tree(folder: Path) -> bool:
    """Supprime `folder` avec reprises ; vrai s'il n'existe plus. Réservé aux dossiers reconnus (`folder_kind`)."""

    return _retry(lambda: _rmtree_once(folder), done=lambda: not folder.exists())


def rename_with_retries(source: Path, destination: Path) -> bool:
    return _retry(lambda: os.replace(source, destination), done=lambda: destination.exists() and not source.exists())


# ---------------------------------------------------------------------- installation


def probe_swappable(target: Path, *, rename: Callable[[Path, Path], None] = os.replace) -> None:
    """Sonde du remplacement (I-009 point 1) : renomme le programme installé puis le remet, AVANT la vérification du
    paquet (plusieurs minutes). Un fichier tenu par autre chose que JARVIS (antivirus, éditeur) est dit en secondes,
    et non après la vérification. L'état d'opération nomme le dossier mis de côté pendant la sonde : si la remise en
    place échouait, l'installation suivante le reconnaît comme ancien programme et l'efface après son succès."""

    pending = read_state(target)
    aside = free_sibling(target, PREVIOUS_SUFFIX)
    write_state(target, "probe", entries=top_entries(target) | set((pending or {}).get("entries") or ()),
                previous=str(aside))
    try:
        rename(target, aside)
    except OSError as exc:
        restore_state(target, pending)
        raise SetupError("jarvis_running", "Des fichiers de JARVIS sont encore utilisés (JARVIS, un antivirus ou un "
                         "autre programme) : fermez-le, puis relancez l'installation.",
                         f"{type(exc).__name__}: {exc}") from exc
    if not _retry(lambda: rename(aside, target), done=lambda: target.exists() and not aside.exists()):
        raise SetupError("rollback_failed", "JARVIS n'a pas pu être remis en place après une vérification. Redémarrez "
                         "Windows, puis relancez l'installation : elle réparera JARVIS.",
                         f"programme mis de côté : {aside}", rolled_back=False, had_previous=True,
                         previous=str(aside))
    restore_state(target, pending)


def install(source: Path, targets: Targets, *, move: bool, progress: Progress,
            shortcuts: Shortcuts | None = None, alive: Callable[[int], bool] = pid_alive,
            ref_alive: Callable[[str], bool] | None = None,
            verify: Callable[[PR.PackageLayout], tuple[dict | None, list[str]]] = PR.verify_package,
            verify_copy: Callable[[Path, Path], list[str]] = copy_matches,
            rename: Callable[[Path, Path], None] = os.replace) -> dict[str, Any]:
    """Installe (ou met à jour, ou répare, ou reprend une opération inachevée) le paquet `source` dans
    `targets.target`. Voir l'en-tête du module."""

    check_target(targets)
    # Avant la vérification du paquet (plusieurs minutes) : un JARVIS ouvert est dit tout de suite.
    if launcher_running(targets.home, alive=alive, ref_alive=ref_alive):
        raise SetupError("jarvis_running", "JARVIS est ouvert : quittez-le, puis relancez l'installation.")
    if folder_kind(targets.target) == "jarvis":
        probe_swappable(targets.target, rename=rename)
    source = Path(source).resolve()
    progress.step("verify_source", "Vérification de chaque fichier du paquet (quelques minutes)…")
    manifest, problems = verify(PR.PackageLayout(source))
    if manifest is None or problems:
        raise SetupError("package_damaged", "Le fichier d'installation est abîmé : téléchargez-le à nouveau.",
                         "; ".join(problems)[:1000])
    version = _version(manifest)
    target = targets.target
    kind = folder_kind(target)
    if kind == "foreign":
        raise SetupError("target_not_empty", "Ce dossier contient déjà autre chose que JARVIS : rien n'y a été touché.",
                         str(target))
    pending = read_state(target)
    if kind == "jarvis":
        mode = "repair" if _version(PR.PackageLayout(target).manifest() or {}) == version else "update"
    else:
        mode = "install"
    progress.step("plan", {"install": "Installation de JARVIS…", "repair": "Réparation de JARVIS…",
                           "update": "Mise à jour de JARVIS…"}[mode], mode=mode, version=version,
                  resumed=kind == "leftover")
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind == "empty":
        try:
            target.rmdir()
        except OSError as exc:
            raise SetupError("target_unusable", "Le dossier d'installation est verrouillé : fermez ce qui l'utilise, "
                             "puis relancez l'installation.", f"{type(exc).__name__}: {exc}") from exc
    entries = top_entries(source) | top_entries(target) | set((pending or {}).get("entries") or ())
    previous: Path | None = None
    write_state(target, "install", entries=entries, previous=None)
    if kind in ("jarvis", "leftover"):
        previous = free_sibling(target, PREVIOUS_SUFFIX)
        try:
            os.replace(target, previous)
        except OSError as exc:
            restore_state(target, pending)
            raise SetupError("jarvis_running", "Des fichiers de JARVIS sont encore utilisés : quittez JARVIS, puis "
                             "relancez l'installation.", f"{type(exc).__name__}: {exc}") from exc
        write_state(target, "install", entries=entries, previous=str(previous))
    written: list[Path] = []
    try:
        progress.step("copy", "Mise en place des fichiers…")
        moved = False
        if move:
            try:
                os.replace(source, target)
                moved = True
            except OSError:
                # intentional: the running installer Python lives in `source` (Windows refuses to move it); copy instead
                shutil.copytree(source, target)
        else:
            shutil.copytree(source, target)
        progress.step("verify_target", "Vérification de l'installation…")
        after = [] if moved else verify_copy(source, target)
        if after:
            raise SetupError("installed_copy_damaged", "La copie installée ne correspond pas au paquet.",
                             "; ".join(after)[:1000])
        progress.step("shortcuts", "Raccourcis…")
        written = list(targets.shortcut_paths)
        write_shortcuts(target, targets, shortcuts or ShellShortcuts())
        targets.registry.write(registration(target, version))
    except BaseException as exc:
        failure = _roll_back(exc, targets, previous=previous, previous_kind=kind, pending=pending,
                             shortcuts_written=written, progress=progress)
        if not isinstance(exc, Exception):
            raise  # KeyboardInterrupt / SystemExit: rolled back above, then propagated as is
        raise failure from exc
    clear_state(target)
    leftovers: list[str] = []
    stale = [previous]
    earlier = Path(str(pending["previous"])) if pending and pending.get("previous") else None
    if (earlier is not None and earlier != previous and earlier.parent == target.parent
            and earlier.name.startswith(target.name + PREVIOUS_SUFFIX) and is_jarvis_program(earlier)):
        stale.append(earlier)  # l'ancien programme d'une mise à jour dont le retour arrière avait échoué
    for old in stale:
        if old is None or not old.exists():
            continue
        progress.step("cleanup", "Nettoyage de l'ancienne version…")
        if not remove_tree(old):
            leftovers.append(str(old))
    progress.step("done", "JARVIS est installé.", mode=mode, version=version)
    return {"ok": True, "mode": mode, "version": version, "target": str(target), "resumed": kind == "leftover",
            "shortcuts": [str(path) for path in targets.shortcut_paths],
            "previous_leftover": leftovers[0] if leftovers else None, "leftovers": leftovers,
            "data_home": str(targets.home) if targets.home else None, "data_kept": True}


def _roll_back(exc: BaseException, targets: Targets, *, previous: Path | None, previous_kind: str,
               pending: Mapping[str, Any] | None, shortcuts_written: list[Path], progress: Progress) -> SetupError:
    """Retour à l'état d'avant, sans jamais supprimer avant de restaurer : la copie ratée est d'abord écartée
    (renommée `.failed-…`, reprises), l'ancien programme remis à sa place, puis seulement la copie ratée effacée.
    Rend le refus à lever, dont le message dit ce qui est VRAI après coup."""

    target = targets.target
    cause = f"{type(exc).__name__}: {exc}"[:300]
    progress.step("rollback", "Échec : retour à l'état d'avant…", error=cause)
    base = exc if isinstance(exc, SetupError) else SetupError("setup_failed", "L'installation a échoué.",
                                                               f"{type(exc).__name__}: {exc}"[:1000])
    aside: Path | None = None
    if target.exists():
        aside = free_sibling(target, FAILED_SUFFIX)
        if not rename_with_retries(target, aside):
            aside = None
            remove_tree(target)
    restored = False
    if not target.exists() and previous is not None and previous.exists():
        restored = rename_with_retries(previous, target)
    left: list[str] = []
    if aside is not None and not remove_tree(aside):
        left.append(str(aside))
    if previous is None and not target.exists():
        for path in shortcuts_written:  # première installation : aucun raccourci vers un programme absent
            try:
                path.unlink()
            except FileNotFoundError:
                pass  # intentional: never written
            except OSError as error:
                left.append(f"{path} ({type(error).__name__})")
    back_in_place = restored if previous is not None else not target.exists()
    detail = base.detail
    if left:
        detail = (detail + " | restes : " + ", ".join(left))[:1000]
    if not back_in_place:
        # L'état d'opération reste : la prochaine installation reconnaît ce dossier et le répare.
        where = f" ; ancienne version mise de côté : {previous}" if previous is not None and previous.exists() else ""
        progress.step("rollback_failed", "Retour arrière incomplet : des fichiers sont encore utilisés.",
                      target=str(target), previous=str(previous) if previous else None)
        return SetupError("rollback_failed",
                          f"{base} Des fichiers sont encore utilisés et l'état d'avant n'a pas pu être remis en place. "
                          "Redémarrez Windows, puis relancez l'installation : elle réparera JARVIS. Vos présentations "
                          "et vos réglages sont conservés.",
                          (f"{base.code}: {base.detail}"[:600] + f" ; cible : {target}{where}")[:1000],
                          rolled_back=False, had_previous=previous is not None,
                          previous=str(previous) if previous is not None else None, leftovers=left)
    if previous_kind == "leftover":
        restore_state(target, pending)  # le reste d'avant est revenu tel quel : son état d'opération aussi
        tail = " Le dossier est revenu dans son état d'avant : relancez l'installation pour terminer."
    else:
        clear_state(target)
        tail = (" L'ancienne version de JARVIS est remise en place." if previous is not None
                else " Rien n'a été installé : vous pouvez relancer l'installation.")
    progress.step("rolled_back", tail.strip())
    return SetupError(base.code, f"{base}{tail}", detail, rolled_back=True, had_previous=previous is not None,
                      leftovers=left, **{k: v for k, v in base.extra.items() if k not in {"rolled_back", "had_previous",
                                                                                         "leftovers"}})


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


# ---------------------------------------------------------------------- désinstallation


def deferred_removal_script(target: Path, *, registry: Registry, pid: int, image: str, log: Path,
                            wait_s: int = DEFERRED_WAIT_S, attempts: int = DEFERRED_ATTEMPTS) -> str:
    """Script `cmd.exe` de la suppression différée (B1 de la QA de la Slice 07) :

    1. attend la FIN RÉELLE du processus `pid` (`tasklist`, une fois par seconde, au plus `wait_s`) : la boîte
       « JARVIS est désinstallé » garde `pythonw.exe` vivant aussi longtemps que l'utilisateur la lit ;
    2. supprime le dossier, avec `attempts` reprises espacées de ~3 s (antivirus, fichier encore ouvert) ;
    3. alors seulement retire la clé de désinstallation et l'état d'opération ; sinon les garde (la désinstallation
       reste proposée par Windows, et un nouvel essai ou une réinstallation reconnaît le reste) ;
    4. écrit chaque étape dans `log`, puis s'efface lui-même.

    Cible sans `" % ! ^ & | < >` (`check_target`) : elle se place telle quelle entre guillemets.
    """

    system = r'"%SystemRoot%\System32'
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "setlocal EnableExtensions DisableDelayedExpansion",
        f'set "TARGET={target}"',
        f'set "STATE={state_path(target)}"',
        f'set "LOG={log}"',
        f'call :log "debut : attente de la fin du processus {pid} ({image})"',
        "set /a waited=0",
        ":wait",
        f'{system}\\tasklist.exe" /fi "PID eq {pid}" /nh 2>nul | {system}\\find.exe" /i "{image}" >nul',
        "if errorlevel 1 goto remove",
        "set /a waited+=1",
        f"if %waited% geq {int(wait_s)} goto remove_anyway",
        f'{system}\\PING.EXE" -n 2 127.0.0.1 >nul',
        "goto wait",
        ":remove_anyway",
        f'call :log "processus {pid} encore vivant apres {int(wait_s)} s : suppression tentee quand meme"',
        ":remove",
        'call :log "processus termine : suppression du dossier"',
        "set /a attempt=0",
        ":retry",
        "set /a attempt+=1",
        'if exist "%TARGET%\\" rmdir /s /q "%TARGET%" >nul 2>&1',
        'if not exist "%TARGET%\\" goto removed',
        f"if %attempt% geq {int(attempts)} goto failed",
        'call :log "essai %attempt% : des fichiers sont encore utilises, nouvel essai dans 3 s"',
        f'{system}\\PING.EXE" -n 4 127.0.0.1 >nul',
        "goto retry",
        ":removed",
        registry.removal_command(),
        'del /f /q "%STATE%" >nul 2>&1',
        'call :log "dossier supprime, cle de desinstallation retiree : %TARGET%"',
        "goto end",
        ":failed",
        'call :log "ECHEC : %TARGET% encore present apres %attempt% essais ; cle de desinstallation gardee"',
        ":end",
        '(goto) 2>nul & del /f /q "%~f0"',
        ":log",
        '>>"%LOG%" echo %DATE% %TIME% [jarvis-uninstall] %~1',
        "exit /b 0",
    ]
    return "\r\n".join(lines) + "\r\n"


def uninstall(targets: Targets, *, progress: Progress, alive: Callable[[int], bool] = pid_alive,
              ref_alive: Callable[[str], bool] | None = None,
              running_from: Path | None = None, spawn: Callable[..., Any] = subprocess.Popen,
              script_dir: Path | None = None, pid: int | None = None, image: str | None = None,
              deferred_wait_s: int = DEFERRED_WAIT_S, deferred_attempts: int = DEFERRED_ATTEMPTS) -> dict[str, Any]:
    """Retire le programme, ses raccourcis et sa clé ; la maison (données) reste. Rien n'est effacé sans preuve que
    c'est JARVIS (`folder_kind`). Lancé depuis le programme lui-même (`running_from`), l'effacement est confié à un
    script `cmd.exe` détaché (`deferred_removal_script`) qui attend la fin réelle de ce processus (`pid`)."""

    check_target(targets)
    target = targets.target
    if launcher_running(targets.home, alive=alive, ref_alive=ref_alive):
        raise SetupError("jarvis_running", "JARVIS est ouvert : quittez-le, puis relancez la désinstallation.")
    kind = folder_kind(target)
    if kind == "foreign":
        raise SetupError("not_a_jarvis_folder", "Ce dossier ne contient pas JARVIS : rien n'est effacé.", str(target))
    pending = read_state(target)
    progress.step("shortcuts", "Retrait des raccourcis…")
    for path in targets.shortcut_paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass  # intentional: already removed by hand
    base = {"ok": True, "target": str(target), "data_home": str(targets.home) if targets.home else None,
            "data_kept": True}
    if kind in ("absent", "empty"):
        if kind == "empty" and not remove_tree(target):
            raise SetupError("uninstall_incomplete", "Le dossier de JARVIS est verrouillé : fermez ce qui l'utilise, "
                             "puis relancez la désinstallation.", str(target))
        targets.registry.delete()
        clear_state(target)
        progress.step("done", "JARVIS est désinstallé. Vos présentations et réglages sont conservés.")
        return {**base, "deferred_removal": False, "removed": True}
    write_state(target, "uninstall", entries=top_entries(target) | set((pending or {}).get("entries") or ()))
    progress.step("files", "Retrait des fichiers du programme…")
    inside = running_from is not None and (running_from == target or target in running_from.parents)
    if inside:
        folder = Path(script_dir) if script_dir is not None else Path(tempfile.gettempdir())
        folder.mkdir(parents=True, exist_ok=True)
        owner = os.getpid() if pid is None else pid
        script = folder / f"jarvis-uninstall-{owner}-{utc_stamp()}.cmd"
        log = folder / UNINSTALL_LOG
        script.write_text(deferred_removal_script(target, registry=targets.registry, pid=owner,
                                                  image=image or Path(sys.executable).name, log=log,
                                                  wait_s=deferred_wait_s, attempts=deferred_attempts),
                          encoding="utf-8", newline="")
        # Ligne en CHAÎNE : `/s` retire les seuls guillemets extérieurs, le chemin du script reste cité. Console
        # cachée (`CREATE_NO_WINDOW`) et NON `DETACHED_PROCESS` : sans console, le tube `tasklist | find` du script ne
        # rend jamais la main (mesuré). Le script survit à la fin de ce processus (aucun Job Object ne le tient).
        spawn(f'cmd.exe /d /s /c ""{script}""', cwd=str(folder), close_fds=True,
              creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        progress.step("done", "JARVIS est désinstallé. Ses derniers fichiers sont retirés dès la fin de cette "
                      "désinstallation. Vos présentations et réglages sont conservés.", log=str(log))
        return {**base, "deferred_removal": True, "removed": False, "removal_log": str(log), "removal_script": str(script)}
    if not remove_tree(target):
        left = sorted(top_entries(target))
        raise SetupError("uninstall_incomplete", "Des fichiers de JARVIS sont encore utilisés et n'ont pas pu être "
                         "retirés. Fermez JARVIS (ou redémarrez Windows), puis relancez la désinstallation.",
                         f"restes sous {target} : {', '.join(left)[:600]}", leftovers=left)
    targets.registry.delete()
    clear_state(target)
    progress.step("done", "JARVIS est désinstallé. Vos présentations et réglages sont conservés.")
    return {**base, "deferred_removal": False, "removed": True}


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
                      "installed": PR.PackageLayout(targets.target).manifest_path.is_file(),
                      "folder": folder_kind(targets.target), "pending": read_state(targets.target)}
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
                    # La suppression différée attend la fin de CE processus : cette boîte peut rester ouverte.
                    _tell("JARVIS est désinstallé.\n\n"
                          + ("Ses derniers fichiers sont retirés dès que vous fermez cette fenêtre.\n\n"
                             if result.get("deferred_removal") else "")
                          + "Vos présentations et vos réglages sont conservés dans %LOCALAPPDATA%\\CIRCOE\\Jarvis.")
    except SetupError as exc:
        result = {**exc.extra, "ok": False, "code": exc.code, "message": str(exc), "detail": exc.detail}
        progress.step("failed", str(exc), code=exc.code)
        if args.command == "uninstall" and not args.quiet:
            _tell(str(exc), error=True)
    except Exception as exc:  # noqa: BLE001 - surfaced: typed result + visible message, never a silent exit
        what = {"install": "L'installation", "uninstall": "La désinstallation"}.get(args.command, "L'opération")
        result = {"ok": False, "code": "setup_failed", "message": f"{what} a échoué.",
                  "detail": f"{type(exc).__name__}: {exc}"[:1000]}
        progress.step("failed", result["message"], code="setup_failed", detail=result["detail"])
        if args.command == "uninstall" and not args.quiet:
            _tell(f"{result['message']}\n\nDétail : {result['detail'][:300]}", error=True)
    if args.result:
        written = Path(args.result)
        written.parent.mkdir(parents=True, exist_ok=True)
        temp = written.with_name(written.name + ".tmp")
        temp.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, written)
    if sys.stdout is not None and (args.quiet or sys.stdout.isatty() or not args.result):
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
