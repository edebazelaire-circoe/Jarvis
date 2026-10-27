"""CLI Claude Code vue par la préparation du produit : trouver, lire la connexion, lancer la connexion (Slice 07).

Contrat : `docs/product-install.md` › *Brain*. La CLI est une **dépendance externe** (HV-PACKAGE-02, défaut sûr :
jamais redistribuée ni installée par JARVIS). L'utilisateur l'installe avec l'installeur officiel d'Anthropic ; la
préparation la retrouve, lit son état de connexion (`claude auth status --json`) et, sur un clic, ouvre la connexion
officielle (`claude auth login`) dans sa propre fenêtre.

Recherche (`locate`) :

1. `JARVIS_CLAUDE_CLI` s'il est posé (administration, tests) ;
2. le `PATH` du processus ;
3. **produit installé seulement** : les emplacements des installeurs officiels, parce que JARVIS lancé depuis le menu
   Démarrer garde le `PATH` d'avant l'installation de la CLI jusqu'à la prochaine session Windows :
   `%USERPROFILE%\\.local\\bin\\claude.exe` (installeur natif), `%APPDATA%\\npm\\claude.cmd` (npm),
   `%LOCALAPPDATA%\\Microsoft\\WinGet\\Links\\claude.exe` (winget).
   macOS (Slice 08 V1.2, non exécuté sur un Mac) : une application lancée depuis le Finder a un `PATH` minimal, d'où
   `~/.local/bin/claude` (installeur natif), `/opt/homebrew/bin/claude` et `/usr/local/bin/claude` (Homebrew).

En développement, rien ne change : `cli_catalog.resolve_command` garde `shutil.which`.

Lecture seule sauf `start_sign_in`, action nommée. Aucune adresse électronique ni identifiant de compte ne sort d'ici :
`auth status` est réduit à `loggedIn` et `authMethod`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from jarvis.domain.diagnostic_redaction import DiagnosticRedactor
from jarvis.domain.product_readiness import BrainFacts

CLI_ENV = "JARVIS_CLAUDE_CLI"
DEFAULT_COMMAND = "claude"
#: Page officielle d'installation de Claude Code (ouverte par « Ouvrir la page d'installation »).
INSTALL_GUIDE_URL = "https://code.claude.com/docs/en/setup"
VERSION_TIMEOUT_S = 15.0
STATUS_TIMEOUT_S = 20.0
CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000

Runner = Callable[[list[str], float], "subprocess.CompletedProcess[str]"]


def known_locations(environ: Mapping[str, str], *, platform: str | None = None) -> list[Path]:
    """Emplacements des installeurs officiels, dans l'ordre de préférence (`platform` : `sys.platform` simulé)."""

    if (sys.platform if platform is None else platform) == "darwin":
        home = str(environ.get("HOME") or "").strip()
        rows = [Path(home) / ".local" / "bin" / "claude"] if home.startswith("/") else []
        return rows + [Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude")]
    rows: list[Path] = []
    profile = str(environ.get("USERPROFILE") or "").strip()
    if profile:
        rows.append(Path(profile) / ".local" / "bin" / "claude.exe")
    appdata = str(environ.get("APPDATA") or "").strip()
    if appdata:
        rows.append(Path(appdata) / "npm" / "claude.cmd")
    local = str(environ.get("LOCALAPPDATA") or "").strip()
    if local:
        rows.append(Path(local) / "Microsoft" / "WinGet" / "Links" / "claude.exe")
    return rows


def locate(*, environ: Mapping[str, str] | None = None, installed: bool,
           which: Callable[[str], str | None] | None = None) -> str | None:
    """Chemin de la CLI, ou `None`. Voir l'en-tête du module pour l'ordre."""

    env = os.environ if environ is None else environ
    which = which or shutil.which
    configured = str(env.get(CLI_ENV) or "").strip()
    found = which(configured or DEFAULT_COMMAND)
    if found:
        return found
    if configured and Path(configured).is_file():
        return configured
    if installed:
        for candidate in known_locations(env):
            if candidate.is_file():
                return str(candidate)
    return None


def _run(argv: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout_s, stdin=subprocess.DEVNULL,
                          creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)


def parse_auth_status(text: str) -> tuple[bool | None, str | None]:
    """`(loggedIn, authMethod)` de `claude auth status --json` ; `(None, None)` si illisible. Rien d'autre n'est gardé."""

    try:
        payload = json.loads(text)
    except ValueError:
        return None, None
    if not isinstance(payload, dict) or not isinstance(payload.get("loggedIn"), bool):
        return None, None
    method = payload.get("authMethod")
    return payload["loggedIn"], method if isinstance(method, str) and len(method) <= 40 else None


def probe(cli: str | None, *, run: Runner = _run, sign_in_running: bool = False) -> BrainFacts:
    """Version et connexion de la CLI. Toute panne est dite (`error`), jamais devinée."""

    if cli is None:
        return BrainFacts(found=False, error="claude_cli_not_found: Claude Code is not installed or not on PATH")
    version: str | None = None
    try:
        done = run([cli, "--version"], VERSION_TIMEOUT_S)
        if done.returncode == 0:
            version = (done.stdout or "").strip().split(" ")[0][:40] or None
    except (OSError, subprocess.SubprocessError) as exc:
        return BrainFacts(found=False, error=f"claude_cli_unrunnable: {type(exc).__name__}: {exc}"[:300])
    try:
        done = run([cli, "auth", "status", "--json"], STATUS_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return BrainFacts(found=True, version=version, error=f"claude_auth_status_timeout: no answer in {STATUS_TIMEOUT_S:.0f} s",
                          sign_in_running=sign_in_running)
    except (OSError, subprocess.SubprocessError) as exc:
        return BrainFacts(found=True, version=version, error=f"claude_auth_status_failed: {type(exc).__name__}: {exc}"[:300],
                          sign_in_running=sign_in_running)
    logged_in, method = parse_auth_status(done.stdout or "")
    if logged_in is None:
        # I-009 point 5 : la dernière ligne de la CLI va au rapport et au journal ; masquée (secrets, adresses,
        # chemins personnels) avant d'être bornée.
        last = ((done.stderr or done.stdout or "").strip().splitlines() or [""])[-1]
        tail = DiagnosticRedactor(os.environ).text(last)[:200]
        return BrainFacts(found=True, version=version, error=f"claude_auth_status_unreadable: exit {done.returncode} {tail}".strip(),
                          sign_in_running=sign_in_running)
    return BrainFacts(found=True, version=version, logged_in=logged_in, auth_method=method,
                      sign_in_running=sign_in_running and not logged_in)


@dataclass
class SignIn:
    """La connexion officielle en cours (`claude auth login`), dans sa propre fenêtre de console."""

    process: Any
    started_at: float

    def running(self) -> bool:
        return self.process.poll() is None


def start_sign_in(cli: str, *, spawn: Callable[..., Any] = subprocess.Popen, clock: Callable[[], float]) -> SignIn:
    """Ouvre la connexion officielle de Claude Code. Sa propre fenêtre : la CLI y affiche ce qu'elle attend (navigateur,
    code à coller) ; JARVIS ne lit ni n'écrit rien dedans."""

    flags = CREATE_NEW_CONSOLE if os.name == "nt" else 0
    process = spawn([cli, "auth", "login"], creationflags=flags, stdin=None, stdout=None, stderr=None)
    return SignIn(process, clock())
