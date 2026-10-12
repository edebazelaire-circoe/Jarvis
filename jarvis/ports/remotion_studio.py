"""Port du Studio Remotion optionnel (Slice 11 ; `docs/remotion-studio.md`) : tout effet disque et processus du Studio."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Ce que la matérialisation du dossier de travail a fait (jamais un chemin absolu)."""

    written: int
    removed: int
    unchanged: int
    edits_saved: tuple[str, ...]  # fichiers du dossier de travail modifiés hors de Jarvis, copiés avant d'être remplacés


@dataclass(frozen=True, slots=True)
class LaunchResult:
    process_ref: str  # `pid:heure de création`
    port: int
    launch_id: str


class StudioRunner(Protocol):
    """Seul endroit où le Studio écrit un fichier ou lance/arrête un processus. Lève `StudioError` (code stable)."""

    def configured_port(self) -> int | None:
        """Port imposé par l'opérateur (`JARVIS_REMOTION_STUDIO_PORT`), sinon `None` (port libre aléatoire)."""

    def runtime_ready(self) -> str | None:
        """`None` si l'environnement Node/Remotion permet de lancer le Studio, sinon la raison (jeton: phrase)."""

    def sync_work(self, files: Mapping[str, bytes]) -> SyncReport:
        """Rend le dossier de travail EXACTEMENT égal à `files` (générés en lecture seule), sans toucher un fichier identique."""

    def modified_work(self) -> tuple[str, ...]:
        """Fichiers du dossier de travail qui diffèrent de la dernière synchronisation."""

    def workspace_listing(self) -> tuple[tuple[str, ...], str]:
        """`(fichiers modifiés, empreinte de leur état)` : l'empreinte que la page renvoie avec `publish` (QA Slice 12, I1)."""

    def enforce_shape(self, files: Mapping[str, bytes]) -> tuple[str, ...]:
        """Avant chaque lancement : met de côté (`studio-edits`, jamais supprimé) tout ce qui n'est pas la forme de l'espace (fichier ou
        dossier de premier niveau étranger, lien, jonction, lien dur) et régénère les fichiers générés depuis `files` ; rend les chemins
        mis de côté. Lève `StudioError` si un déplacement est impossible (le lancement n'a pas lieu)."""

    def take_rotated(self) -> tuple[str, ...]:
        """Noms des dossiers `studio-edits/` retirés par la rotation depuis le dernier appel (le service les journalise)."""

    def save_modified(self) -> tuple[str, ...]:
        """Copie à part (jamais supprimée par une synchronisation) les fichiers modifiés hors de Jarvis ; rend leurs chemins."""

    def bind_parent(self) -> None:
        """Déclare CE Core (pid + heure de création) comme parent surveillé par le garde du Studio ; au lancement et à l'adoption."""

    def launch(self, *, port: int | None, idle_s: float) -> LaunchResult:
        """Lance le Studio sur la boucle locale, attend qu'il réponde AVEC l'identifiant de ce lancement, rend sa référence.
        `idle_s` : plafond d'inactivité transmis au garde (le Studio se termine seul au-delà, même si Core a disparu)."""

    def probe(self, port: int, launch_id: str) -> None:
        """Santé : lève si le serveur sur `port` n'est pas CE lancement."""

    def is_alive(self, process_ref: str) -> bool: ...

    def stop(self, process_ref: str) -> None:
        """Tue l'arbre du processus si (et seulement si) la référence désigne toujours notre processus."""

    def activity(self, launch_id: str) -> Mapping[str, Any]:
        """`{last_ms, ws_open, requests, blocked_egress}` écrits par le garde du Studio, `{}` si absent ou d'un autre lancement."""

    def log_tail(self, lines: int = 8) -> list[str]: ...

    def read_state(self) -> Mapping[str, Any] | None: ...

    def write_state(self, payload: Mapping[str, Any]) -> None: ...
