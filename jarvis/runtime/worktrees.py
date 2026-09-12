"""Les copies de travail où JARVIS a le droit de modifier son propre code.

Deux plans, jamais confondus :

- le **plan de service**, le dépôt principal, celui d'où tournent Core, l'UI et
  la voix en ce moment même. Aucun agent n'y écrit ;
- le **plan de construction**, des worktrees git frères, un par chantier. Tout
  s'y passe : édition, tests, commit, poussée de la branche candidate.

Un dossier ne prouve rien. Un répertoire nommé `sub-agents` peut contenir un
clone d'un autre dépôt, un dossier vide, ou la copie de travail d'un collègue.
L'identité est donc demandée à git — même dépôt commun, worktree déclaré,
état propre — et jamais déduite d'un chemin.

Un bail (`lease`) empêche deux chantiers d'écrire au même endroit. Les baux
vivent dans le `runtime` du plan de service, pas dans le worktree : un chantier
ne doit pas salir la copie qu'il emprunte.

Aucune commande destructrice n'existe dans ce module. Il lit, il sonde, il
prête. Ce qui écrit dans un worktree est le travail du chantier lui-même.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

#: Un bail dont le propriétaire n'existe plus est repris passé ce délai. Assez
#: long pour couvrir un chantier lent, assez court pour qu'un plantage ne
#: condamne pas un worktree jusqu'au prochain redémarrage.
STALE_LEASE_S = 6 * 3600.0
GIT_TIMEOUT_S = 60.0

#: Noms historiques du dossier frère qui contient les worktrees. Les deux sont
#: cherchés : la machine dit lequel existe, pas la documentation.
POOL_ROOT_NAMES = ("sub-agents", "sous-agents")
POOL_ROOT_ENV = "JARVIS_WORKTREE_ROOT"

_SLUG = re.compile(r"[^a-z0-9]+")


class WorktreeError(RuntimeError):
    """Refus d'un worktree, avec le code qui dit lequel des motifs s'applique."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------- git nu


async def git(*args: str, cwd: Path, timeout_s: float = GIT_TIMEOUT_S) -> str:
    """Une commande git, en tableau d'arguments, sans shell.

    Jamais de chaîne interpolée : un chemin contenant une espace, un accent ou
    une apostrophe doit rester un argument, pas devenir de la syntaxe.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, FileNotFoundError) as exc:
        raise WorktreeError("worktree_git_missing", f"git est introuvable : {exc}") from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise WorktreeError("worktree_git_timeout", f"« git {args[0]} » n'a pas répondu en {timeout_s:g} s.") from exc
    if process.returncode != 0:
        detail = (stderr or b"").decode("utf-8", "replace").strip()
        raise WorktreeError("worktree_git_failed", f"« git {' '.join(args)} » a échoué : {detail}")
    return (stdout or b"").decode("utf-8", "replace")


async def common_dir(path: Path) -> Path:
    """Le dépôt commun d'une copie de travail : l'identité, au sens de git."""
    raw = await git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=path)
    resolved = raw.strip()
    if not resolved:
        raise WorktreeError("worktree_not_a_repository", f"{path} n'est pas une copie de travail git.")
    return Path(resolved).resolve()


# --------------------------------------------------------------------- état


@dataclass(frozen=True, slots=True)
class Worktree:
    path: Path
    branch: str
    head: str
    dirty: bool
    # Renseigné quand le worktree ne peut pas servir, avec le code du refus.
    blocked: str = ""
    detail: str = ""

    @property
    def slug(self) -> str:
        return _SLUG.sub("-", self.path.name.lower()).strip("-") or "worktree"

    @property
    def usable(self) -> bool:
        return not self.blocked

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "branch": self.branch,
            "head": self.head,
            "dirty": self.dirty,
            "usable": self.usable,
            "blocked": self.blocked,
            "detail": self.detail,
        }


def _parse_porcelain(raw: str) -> list[dict[str, str]]:
    """`git worktree list --porcelain` : des blocs séparés par une ligne vide."""
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value.strip()
    if current:
        entries.append(current)
    return entries


def default_pool_root(primary: Path) -> Path | None:
    """Le dossier frère qui contient les worktrees, s'il existe.

    L'environnement l'emporte ; sinon le premier des noms connus qui existe
    réellement. Rien n'est créé ici : un dossier absent est une information,
    pas un problème à corriger en douce.
    """
    override = os.getenv(POOL_ROOT_ENV, "").strip()
    if override:
        return Path(override).resolve()
    for name in POOL_ROOT_NAMES:
        candidate = (primary.parent / name).resolve()
        if candidate.is_dir():
            return candidate
    return None


# --------------------------------------------------------------------- baux


@dataclass(frozen=True, slots=True)
class Lease:
    path: Path
    job_id: str
    pid: int
    acquired_at: str
    lease_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {"path": str(self.path), "job_id": self.job_id, "pid": self.pid, "acquired_at": self.acquired_at}


def _alive(pid: int) -> bool:
    """Le propriétaire d'un bail tourne-t-il encore ?

    `os.kill(pid, 0)` sous POSIX, `OpenProcess` sous Windows. Dans le doute —
    droits insuffisants, plateforme muette — on répond oui : reprendre le bail
    d'un chantier bien vivant serait la pire des erreurs.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        except (OSError, AttributeError, ValueError):
            return True
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _age_s(acquired_at: str) -> float:
    try:
        stamp = datetime.fromisoformat(acquired_at)
    except ValueError:
        return float("inf")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())


class WorktreePool:
    """Les worktrees disponibles, leur identité prouvée, et qui les tient."""

    def __init__(self, *, primary: Path, root: Path | None = None, lease_root: Path | None = None) -> None:
        self.primary = Path(primary).resolve()
        self._root = Path(root).resolve() if root is not None else None
        self.lease_root = Path(lease_root) if lease_root is not None else self.primary / "runtime" / "worktree-leases"

    @property
    def root(self) -> Path | None:
        return self._root if self._root is not None else default_pool_root(self.primary)

    # -------------------------------------------------------- découverte

    async def discover(self) -> list[Worktree]:
        """Tous les worktrees du dépôt, sous la racine du pool, avec leur état.

        Le principal est exclu par construction : il sert, il ne se prête pas.
        Un worktree hors de la racine (ceux que l'outillage d'agent crée dans
        `.claude/`) n'appartient pas au pool et n'est pas rendu.
        """
        root = self.root
        if root is None:
            return []
        mine = await common_dir(self.primary)
        entries = _parse_porcelain(await git("worktree", "list", "--porcelain", cwd=self.primary))

        found: list[Worktree] = []
        for entry in entries:
            raw_path = entry.get("worktree")
            if not raw_path:
                continue
            path = Path(raw_path).resolve()
            if path == self.primary or not _within(path, root):
                continue
            found.append(await self._inspect(path, entry, mine))
        return sorted(found, key=lambda item: str(item.path))

    async def _inspect(self, path: Path, entry: dict[str, str], mine: Path) -> Worktree:
        branch = str(entry.get("branch") or "").removeprefix("refs/heads/")
        head = str(entry.get("HEAD") or "")
        if not path.is_dir():
            return Worktree(path, branch, head, False, "worktree_missing", "Le dossier a disparu.")
        try:
            theirs = await common_dir(path)
        except WorktreeError as exc:
            return Worktree(path, branch, head, False, "worktree_foreign", str(exc))
        if theirs != mine:
            return Worktree(path, branch, head, False, "worktree_foreign", "Copie de travail d'un autre dépôt.")
        try:
            status = await git("status", "--porcelain", cwd=path)
        except WorktreeError as exc:
            return Worktree(path, branch, head, False, "worktree_unreadable", str(exc))
        dirty = bool(status.strip())
        if dirty:
            return Worktree(path, branch, head, True, "worktree_dirty", "Des modifications non validées s'y trouvent.")
        return Worktree(path, branch, head, False)

    async def available(self) -> list[Worktree]:
        leased = self.leases()
        held = {lease.path for lease in leased}
        return [item for item in await self.discover() if item.usable and item.path not in held]

    # --------------------------------------------------------------- baux

    def _lease_path(self, worktree: Worktree) -> Path:
        return self.lease_root / f"{worktree.slug}.json"

    def leases(self) -> list[Lease]:
        """Les baux en cours, ceux devenus caducs exclus."""
        alive: list[Lease] = []
        for path in sorted(self.lease_root.glob("*.json")) if self.lease_root.is_dir() else ():
            lease = _read_lease(path)
            if lease is None:
                continue
            if _alive(lease.pid) and _age_s(lease.acquired_at) < STALE_LEASE_S:
                alive.append(lease)
        return alive

    def acquire(self, worktree: Worktree, *, job_id: str) -> Lease:
        """Prendre un worktree pour un chantier. Échoue plutôt que de partager.

        Le fichier est créé en exclusif (`x`) : deux chantiers qui demandent au
        même instant ne peuvent pas réussir tous les deux, même dans deux
        processus qui ne se voient pas.
        """
        if not worktree.usable:
            raise WorktreeError(worktree.blocked or "worktree_unusable", f"{worktree.path} : {worktree.detail}")
        if worktree.path == self.primary:
            raise WorktreeError("worktree_is_primary", "La copie de travail qui sert ne se prête pas.")

        self.lease_root.mkdir(parents=True, exist_ok=True)
        path = self._lease_path(worktree)
        existing = _read_lease(path)
        if existing is not None:
            if _alive(existing.pid) and _age_s(existing.acquired_at) < STALE_LEASE_S:
                raise WorktreeError(
                    "worktree_leased",
                    f"{worktree.path} est déjà pris par le chantier « {existing.job_id} » (pid {existing.pid}).",
                )
            # Bail caduc : son propriétaire est mort ou parti sans rendre.
            path.unlink(missing_ok=True)

        lease = Lease(
            path=worktree.path,
            job_id=job_id,
            pid=os.getpid(),
            acquired_at=datetime.now(timezone.utc).isoformat(),
            lease_path=path,
        )
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(lease.as_dict(), handle, ensure_ascii=False, indent=2)
        except FileExistsError as exc:
            raise WorktreeError("worktree_leased", f"{worktree.path} vient d'être pris par un autre chantier.") from exc
        return lease

    def release(self, lease: Lease) -> None:
        """Rendre un bail. Rendre deux fois n'est pas une erreur."""
        current = _read_lease(lease.lease_path)
        if current is not None and current.job_id != lease.job_id:
            # Le bail a déjà été repris : l'effacer volerait le worktree à son
            # nouveau propriétaire.
            return
        lease.lease_path.unlink(missing_ok=True)

    async def lease_any(self, *, job_id: str) -> Lease:
        """Le premier worktree libre et sain. Sinon, un refus qui dit quoi faire."""
        candidates = await self.discover()
        for worktree in candidates:
            if not worktree.usable:
                continue
            try:
                return self.acquire(worktree, job_id=job_id)
            except WorktreeError as exc:
                if exc.code != "worktree_leased":
                    raise
        raise WorktreeError("worktree_none_free", _shortage(candidates, self.root))


def _shortage(candidates: Sequence[Worktree], root: Path | None) -> str:
    if root is None:
        names = " ou ".join(POOL_ROOT_NAMES)
        return f"Aucun plan de construction : créez un dossier frère {names} avec un worktree de ce dépôt."
    if not candidates:
        return f"Aucun worktree dans {root} : ajoutez-en un avec « git worktree add »."
    blocked = [f"{item.path.name} ({item.blocked or 'occupé'})" for item in candidates]
    return "Aucun worktree libre : " + ", ".join(blocked) + "."


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _read_lease(path: Path) -> Lease | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or not raw.get("path"):
        return None
    try:
        pid = int(raw.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    return Lease(
        path=Path(str(raw["path"])),
        job_id=str(raw.get("job_id") or ""),
        pid=pid,
        acquired_at=str(raw.get("acquired_at") or ""),
        lease_path=path,
    )


def describe(worktrees: Iterable[Worktree], leases: Iterable[Lease]) -> dict[str, Any]:
    held = {str(lease.path): lease.as_dict() for lease in leases}
    return {
        "worktrees": [{**item.as_dict(), "lease": held.get(str(item.path))} for item in worktrees],
        "leases": list(held.values()),
    }
