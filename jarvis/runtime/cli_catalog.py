"""Quels CLI d'agent sont réellement installés sur cette machine.

Proposer « Claude » et « Codex » dans un menu ne dit rien : ce qui compte est
de savoir lequel existe dans le PATH, à quelle version, et ce qu'il sait faire.
Tout ici est mesuré (`shutil.which` puis `--version`), jamais supposé.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import shutil
from typing import Any

# `--version` sur un CLI installé répond en moins d'une seconde ; au-delà, la
# réponse ne vaut plus la peine de faire attendre l'ouverture des réglages.
PROBE_TIMEOUT_S = 8.0


@dataclass(frozen=True, slots=True)
class AgentCliSpec:
    id: str
    label: str
    default_command: str
    # Fournisseur dont la clé sert à lister les modèles réels de ce CLI.
    model_provider: str
    description: str
    # Capacités que l'interface utilise pour n'afficher que les champs qui
    # existent vraiment pour ce CLI.
    features: tuple[str, ...] = field(default=())
    permission_modes: tuple[str, ...] = field(default=())
    permission_label: str = ""
    docs: str = ""


CLAUDE_PERMISSION_MODES = ("bypassPermissions", "acceptEdits", "dontAsk", "auto", "manual", "plan")
# `codex exec` parle de bac à sable, pas de permissions : les valeurs viennent
# de `codex exec --help` (possible values: read-only, workspace-write,
# danger-full-access), plus le contournement complet exposé par le CLI.
CODEX_SANDBOX_MODES = ("danger-full-access", "workspace-write", "read-only")

AGENT_CLIS: tuple[AgentCliSpec, ...] = (
    AgentCliSpec(
        id="claude",
        label="Claude Code",
        default_command="claude",
        model_provider="anthropic",
        description="Processus persistant piloté en stream-json. Console Windows et reprise de "
        "conversation disponibles.",
        features=("streaming", "console", "resume", "model", "permission_mode"),
        permission_modes=CLAUDE_PERMISSION_MODES,
        permission_label="Autorisations",
        docs="claude --help",
    ),
    AgentCliSpec(
        id="codex",
        label="Codex CLI",
        default_command="codex",
        model_provider="openai",
        description="Un processus par question (`codex exec --json`) ; le fil se poursuit d'une "
        "question à l'autre par son identifiant. Pas de processus permanent : « Kill » n'a "
        "donc rien à arrêter entre deux tours, et la console s'ouvre sans passation de main.",
        features=("resume", "model", "sandbox"),
        permission_modes=CODEX_SANDBOX_MODES,
        permission_label="Bac à sable",
        docs="codex exec --help",
    ),
)

AGENT_CLI_IDS: tuple[str, ...] = tuple(spec.id for spec in AGENT_CLIS)
_BY_ID: dict[str, AgentCliSpec] = {spec.id: spec for spec in AGENT_CLIS}
DEFAULT_AGENT_CLI = "claude"


class CliSettingsError(ValueError):
    """Réglage de CLI refusé, avec un code exploitable par l'interface."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_command(command: str) -> str:
    """Chemin complet de l'exécutable, extension comprise.

    Sous Windows, `CreateProcess` n'applique pas PATHEXT : « codex » installé
    par npm est un shim `codex.CMD` que seul son chemin complet permet de
    lancer — sans quoi le lancement échoue sur « [WinError 2] Le fichier
    spécifié est introuvable » alors que la commande marche au terminal.
    À défaut de résolution, la commande est rendue telle quelle pour que
    l'erreur nomme ce qui a réellement été demandé.
    """
    name = str(command or "").strip()
    if not name:
        return name
    return shutil.which(name) or name


def spec_for(agent_id: str) -> AgentCliSpec:
    return _BY_ID.get(str(agent_id or "").strip().lower(), _BY_ID[DEFAULT_AGENT_CLI])


def normalize_agent_cli(value: object) -> str:
    name = str(value or "").strip().lower()
    return name if name in _BY_ID else DEFAULT_AGENT_CLI


async def probe(command: str) -> dict[str, Any]:
    """Résoudre puis interroger un exécutable. Ne lève jamais."""
    name = str(command or "").strip()
    if not name:
        return {"available": False, "path": "", "version": "", "error": "Aucune commande renseignée."}
    resolved = shutil.which(name)
    if resolved is None:
        return {
            "available": False,
            "path": "",
            "version": "",
            "error": f"« {name} » est introuvable dans le PATH.",
        }
    try:
        process = await asyncio.create_subprocess_exec(
            resolved,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return {"available": False, "path": resolved, "version": "", "error": f"{type(exc).__name__}: {exc}"}
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=PROBE_TIMEOUT_S)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return {
            "available": False,
            "path": resolved,
            "version": "",
            "error": f"« {name} --version » n'a pas répondu en {PROBE_TIMEOUT_S:g} s.",
        }
    output = (stdout or b"").decode("utf-8", "replace").strip()
    if not output:
        output = (stderr or b"").decode("utf-8", "replace").strip()
    if process.returncode != 0:
        return {
            "available": False,
            "path": resolved,
            "version": "",
            "error": output or f"« {name} --version » a renvoyé le code {process.returncode}.",
        }
    # La première ligne suffit : certains CLI ajoutent des avis de mise à jour.
    return {"available": True, "path": resolved, "version": output.splitlines()[0].strip(), "error": ""}


def describe(spec: AgentCliSpec, *, command: str, detection: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": spec.id,
        "label": spec.label,
        "command": command,
        "default_command": spec.default_command,
        "model_provider": spec.model_provider,
        "description": spec.description,
        "features": list(spec.features),
        "permission_modes": list(spec.permission_modes),
        "permission_label": spec.permission_label,
        "docs": spec.docs,
        **detection,
    }


async def detect_all(commands: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Sonder tous les CLI connus en parallèle : l'attente est celle du plus lent."""
    overrides = commands or {}
    resolved = [str(overrides.get(spec.id) or spec.default_command).strip() or spec.default_command for spec in AGENT_CLIS]
    results = await asyncio.gather(*(probe(command) for command in resolved))
    return [
        describe(spec, command=command, detection=detection)
        for spec, command, detection in zip(AGENT_CLIS, resolved, results)
    ]
