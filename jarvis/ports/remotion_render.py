"""Port du rendu Remotion (Slice 16 ; `docs/remotion-render.md`) : tout effet disque et processus d'un rendu."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class BrowserInfo:
    path: str
    version: str  # "chrome 154.0.8037.99" ou "unknown" : jamais obtenu en LANÇANT le navigateur de l'utilisateur


@dataclass(slots=True)
class RunOutcome:
    ok: bool
    code: str = ""  # code `RenderErrorCode` quand `ok` est faux
    detail: str = ""
    outputs: list[Path] = field(default_factory=list)
    egress: dict[str, Any] = field(default_factory=dict)
    elapsed_s: float = 0.0
    log_tail: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class VerifiedOutput:
    path: Path
    size_bytes: int
    sha256: str
    width: int
    height: int
    duration_ms: int | None
    frames: int | None
    pages: int | None
    verified_by: str  # "ffprobe" | "header" | "png" | "pdf"


class RenderRunner(Protocol):
    """Seul endroit où un rendu écrit un fichier ou lance/arrête un processus. Lève `RenderError` (code stable)."""

    def runtime_ready(self) -> str | None:
        """`None` si Node, `@remotion/bundler` et `@remotion/renderer` sont installés, sinon la raison."""

    def installed_engine(self) -> Any | None:
        """Ce que la capacité a réellement installé (`InstalledEngine`, d'après `install-record.json`), ou `None` si illisible."""

    def find_browser(self) -> BrowserInfo | None:
        """Le navigateur à utiliser (réglage explicite, puis installations usuelles) ; jamais un téléchargement."""

    def prepare(self, job_id: str, files: Mapping[str, bytes]) -> None:
        """Dossier de travail du rendu : la source gelée exactement, rien d'autre. Refuse un disque trop plein."""

    def run(self, job_id: str, spec: Mapping[str, Any], *, browser: BrowserInfo, cancel: threading.Event, timeout_s: float,
            on_start: Callable[[str], None], on_progress: Callable[[Mapping[str, Any]], None]) -> RunOutcome:
        """Lance le processus de rendu, suit sa progression, le tue au délai, à l'annulation ou au dépassement du disque."""

    def verify(self, job_id: str, fmt: str, *, width: int, height: int, frames: int | None, pages: int | None) -> VerifiedOutput:
        """Contrôle le fichier produit (en-tête, dimensions, durée, nombre d'images). Lève `output_invalid`."""

    def copy_output(self, job_id: str, verified: VerifiedOutput, write: Callable[[bytes], Any]) -> None:
        """Lit le fichier vérifié par blocs et les passe à `write` (le spool de l'Artifact)."""

    def cleanup(self, job_id: str) -> None: ...

    def stop(self, process_ref: str) -> bool:
        """Tue l'arbre si (et seulement si) la référence désigne toujours notre processus ; vrai si plus rien ne vit."""

    def alive(self, process_ref: str) -> bool: ...

    def write_record(self, job_id: str, record: Mapping[str, Any]) -> None: ...

    def records(self) -> list[Mapping[str, Any]]:
        """Les enregistrements `job.json` laissés sur disque (reprise après un arrêt de Core)."""
