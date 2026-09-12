"""Un chantier où JARVIS modifie son propre code, loin de ce qui sert.

Le chantier produit un **candidat** : une branche poussée, validée, décrite.
Il ne déploie rien. Personne ici ne touche à la copie de travail qui sert, ne
force une poussée, ne réécrit une branche d'un autre, ne résout un conflit à la
place de quelqu'un. Ces interdits ne sont pas des précautions de style : ce
sont les seules choses qui rendent l'auto-modification acceptable.

Déroulé d'un chantier :

1. emprunter un worktree sain (`worktrees.WorktreePool`) ;
2. y ramener `main` à jour depuis le dépôt distant, sans rien détruire ;
3. ouvrir une branche dédiée au chantier ;
4. y lancer l'agent de code choisi par la politique d'aiguillage ;
5. exiger un diff non vide, un état propre et des tests verts ;
6. valider, pousser, décrire le candidat ;
7. rendre le bail, quoi qu'il soit arrivé.

L'état du chantier est écrit sur disque à chaque étape : un chantier interrompu
doit pouvoir être raconté après coup, pas deviné.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
from typing import Any, Sequence
import uuid

from jarvis.domain import routing
from jarvis.domain.routing import RoutingDecision, RoutingError, RoutingPolicy
from jarvis.runtime import agent_routing, cli_catalog, routing_hook
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.worktrees import Lease, WorktreeError, WorktreePool, git

#: Préfixe des branches de chantier. Un humain doit reconnaître d'un coup d'œil
#: ce qui vient de JARVIS lui-même.
BRANCH_PREFIX = "selfdev"
DEFAULT_REMOTE = "origin"
DEFAULT_BASE = "main"

#: L'agent de code a besoin de temps ; il n'en a pas besoin de façon illimitée.
AGENT_TIMEOUT_S = 45 * 60.0
TESTS_TIMEOUT_S = 30 * 60.0

#: Étapes, dans l'ordre. Elles servent au journal, à l'état durable et aux
#: tests : une étape absente de cette liste n'existe pas.
STEPS = (
    "leased",
    "synced",
    "branched",
    "edited",
    "validated",
    "committed",
    "pushed",
    "done",
)


class SelfDevError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Candidate:
    """Ce qu'un chantier réussi remet à l'intégration. Rien de plus."""

    job_id: str
    branch: str
    revision: str
    base: str
    base_revision: str
    remote: str
    worktree: str
    files: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    routing: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["files"] = list(self.files)
        payload["tests"] = list(self.tests)
        return payload


@dataclass(slots=True)
class Job:
    """Le chantier, tel qu'il est raconté sur disque du début à la fin."""

    job_id: str
    request: str
    profile: str = "code"
    status: str = "pending"
    step: str = ""
    started_at: str = field(default_factory=_now)
    ended_at: str = ""
    error_code: str = ""
    error: str = ""
    worktree: str = ""
    branch: str = ""
    candidate: dict[str, Any] | None = None
    routing: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobStore:
    """Les chantiers sur disque : un fichier par chantier, écrit à chaque étape."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def save(self, job: Job) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path(job.job_id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(job.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path(job.job_id))

    def load(self, job_id: str) -> Job | None:
        try:
            raw = json.loads(self.path(job_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return Job(**raw) if isinstance(raw, dict) else None

    def all(self) -> list[Job]:
        jobs: list[Job] = []
        for path in sorted(self.root.glob("*.json")) if self.root.is_dir() else ():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(raw, dict):
                try:
                    jobs.append(Job(**raw))
                except TypeError:
                    continue
        return sorted(jobs, key=lambda job: job.started_at, reverse=True)


# ------------------------------------------------------------------ chantier


class SelfDevelopmentRunner:
    """Conduit un chantier de bout en bout, dans un worktree emprunté."""

    def __init__(
        self,
        *,
        pool: WorktreePool,
        runtime_root: Path,
        settings: dict[str, Any] | None = None,
        journal: RuntimeJournal | None = None,
        remote: str = DEFAULT_REMOTE,
        base: str = DEFAULT_BASE,
        tests: Sequence[str] = ("-m", "pytest", "-q"),
        python: str | None = None,
    ) -> None:
        self.pool = pool
        self.runtime_root = Path(runtime_root)
        self.settings = settings if settings is not None else {}
        self.journal = journal or RuntimeJournal(self.runtime_root)
        self.remote = remote
        self.base = base
        self.tests = tuple(tests)
        self.python = python or _default_python()
        self.jobs = JobStore(self.runtime_root / "self-dev")

    # ------------------------------------------------------------ public

    async def run(self, request: str, *, profile: str = "code", job_id: str | None = None) -> Job:
        """Mener un chantier. Ne lève pas : l'échec est un état du chantier."""
        job = Job(job_id=job_id or f"selfdev-{uuid.uuid4().hex[:12]}", request=request.strip(), profile=profile)
        self.jobs.save(job)
        if not job.request:
            return self._fail(job, "selfdev_empty_request", "Un chantier sans demande n'a rien à faire.")

        lease: Lease | None = None
        try:
            lease = await self.pool.lease_any(job_id=job.job_id)
            job.worktree, job.status = str(lease.path), "running"
            self._step(job, "leased")
            await self._build(job, lease.path)
        except WorktreeError as exc:
            return self._fail(job, exc.code, str(exc))
        except SelfDevError as exc:
            return self._fail(job, exc.code, str(exc))
        except asyncio.CancelledError:
            self._fail(job, "selfdev_cancelled", "Chantier annulé.")
            raise
        except Exception as exc:  # noqa: BLE001 - un chantier ne fait jamais tomber JARVIS
            return self._fail(job, "selfdev_failed", f"{type(exc).__name__}: {exc}")
        finally:
            if lease is not None:
                # Rendre le bail même après un échec : un worktree condamné par
                # un chantier mort serait perdu jusqu'au prochain redémarrage.
                self.pool.release(lease)
        job.status, job.ended_at = "succeeded", _now()
        self._step(job, "done")
        return job

    # ----------------------------------------------------------- étapes

    async def _build(self, job: Job, worktree: Path) -> None:
        await self._sync(job, worktree)
        base_revision = (await git("rev-parse", f"{self.remote}/{self.base}", cwd=worktree)).strip()
        branch = f"{BRANCH_PREFIX}/{job.job_id}"
        await self._branch(job, worktree, branch, base_revision)
        job.branch = branch

        decision = self._route(job)
        await self._edit(job, worktree, decision)

        files = await self._changes(worktree)
        if not files:
            raise SelfDevError("selfdev_no_change", "L'agent de code n'a rien modifié : aucun candidat à intégrer.")
        await self._validate(job, worktree)

        revision = await self._commit(job, worktree, files)
        await self._push(job, worktree, branch)

        job.candidate = Candidate(
            job_id=job.job_id,
            branch=branch,
            revision=revision,
            base=self.base,
            base_revision=base_revision,
            remote=self.remote,
            worktree=str(worktree),
            files=tuple(files),
            tests=self.tests,
            routing=job.routing,
        ).as_dict()

    async def _sync(self, job: Job, worktree: Path) -> None:
        """Ramener les références distantes. Rien n'est écrasé ici."""
        await git("fetch", self.remote, self.base, "--quiet", cwd=worktree)
        self._step(job, "synced")

    async def _branch(self, job: Job, worktree: Path, branch: str, base_revision: str) -> None:
        """Ouvrir la branche du chantier sur la base voulue.

        `checkout -b` échoue si la branche existe déjà : c'est voulu. Réutiliser
        une branche de chantier voudrait dire écraser un candidat précédent, et
        un identifiant de chantier ne se répète pas.
        """
        await git("checkout", "-q", "-b", branch, base_revision, cwd=worktree)
        self._step(job, "branched")

    def _route(self, job: Job) -> RoutingDecision:
        """Quel agent de code, quel modèle : la politique décide, pas le code.

        Aucun nom de modèle n'est écrit ici. Sans politique, c'est le CLI
        configuré qui travaille, avec son modèle — le comportement d'avant.
        """
        policy: RoutingPolicy = agent_routing.load_policy(self.settings)
        candidates = routing_hook.offline_candidates(self.runtime_root, policy)
        try:
            decision = routing_hook.resolve_for(job.profile, policy, candidates, source="self-dev")
        except RoutingError as exc:
            raise SelfDevError(getattr(exc, "code", "routing_failed"), str(exc)) from exc
        job.routing = decision.as_dict()
        return decision

    async def _edit(self, job: Job, worktree: Path, decision: RoutingDecision) -> None:
        """Lancer l'agent de code, enfermé dans le worktree emprunté."""
        agent_id = decision.agent or cli_catalog.normalize_agent_cli(self.settings.get("agent_cli"))
        command, args = self._agent_command(agent_id, decision.model, job.request)
        code, output = await self._exec(command, args, cwd=worktree, timeout_s=AGENT_TIMEOUT_S)
        if code != 0:
            raise SelfDevError("selfdev_agent_failed", f"L'agent de code a échoué (code {code}) : {_tail(output)}")
        self._step(job, "edited")

    def _agent_command(self, agent_id: str, model: str, request: str) -> tuple[str, list[str]]:
        spec = cli_catalog.spec_for(agent_id)
        executable = cli_catalog.resolve_command(self.settings_command(spec.id) or spec.default_command)
        if spec.id == "codex":
            args = ["exec", "--skip-git-repo-check"]
            if model:
                args += ["-m", model]
            return executable, [*args, request]
        args = ["-p", "--permission-mode", "bypassPermissions"]
        if model:
            args += ["--model", model]
        return executable, [*args, request]

    def settings_command(self, agent_id: str) -> str:
        stored = self.settings.get("agent_cli_settings")
        entry = stored.get(agent_id) if isinstance(stored, dict) and isinstance(stored.get(agent_id), dict) else {}
        return str(entry.get("command") or "")

    async def _validate(self, job: Job, worktree: Path) -> None:
        """Les tests, dans le worktree. Rouge : pas de candidat, point final."""
        code, output = await self._exec(self.python, list(self.tests), cwd=worktree, timeout_s=TESTS_TIMEOUT_S)
        if code != 0:
            raise SelfDevError("selfdev_tests_failed", f"Les tests refusent ce travail : {_tail(output)}")
        self._step(job, "validated")

    async def _changes(self, worktree: Path) -> list[str]:
        raw = await git("status", "--porcelain", cwd=worktree)
        return sorted({line[3:].strip().strip('"') for line in raw.splitlines() if line.strip()})

    async def _commit(self, job: Job, worktree: Path, files: Sequence[str]) -> str:
        await git("add", "-A", cwd=worktree)
        message = _commit_message(job, files)
        await git("commit", "-q", "-m", message, cwd=worktree)
        self._step(job, "committed")
        return (await git("rev-parse", "HEAD", cwd=worktree)).strip()

    async def _push(self, job: Job, worktree: Path, branch: str) -> None:
        """Pousser la branche du chantier. Jamais `--force`, jamais une autre branche."""
        await git("push", "--set-upstream", self.remote, f"{branch}:{branch}", cwd=worktree)
        self._step(job, "pushed")

    # ------------------------------------------------------------ outils

    async def _exec(self, command: str, args: Sequence[str], *, cwd: Path, timeout_s: float) -> tuple[int, str]:
        """Un processus, dans le worktree, sans shell et sans héritage de cwd.

        `cwd` est le seul endroit où l'agent a le droit d'écrire. Ce n'est pas
        une prison — un agent déterminé en sortirait — mais c'est la garantie
        qu'aucun chemin relatif ne tombe par accident sur la copie qui sert.
        """
        if Path(cwd).resolve() == self.pool.primary:
            raise SelfDevError("selfdev_primary_forbidden", "Un chantier ne s'exécute jamais dans la copie qui sert.")
        try:
            process = await asyncio.create_subprocess_exec(
                command,
                *args,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except (OSError, FileNotFoundError) as exc:
            raise SelfDevError("selfdev_agent_missing", f"« {command} » est introuvable : {exc}") from exc
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise SelfDevError(
                "selfdev_timeout",
                f"« {os.path.basename(command)} » n'a pas fini en {timeout_s / 60:.0f} min.",
            ) from exc
        return int(process.returncode or 0), (stdout or b"").decode("utf-8", "replace")

    def _step(self, job: Job, step: str) -> None:
        job.step = step
        self.jobs.save(job)
        self.journal.emit(
            "selfdev.step",
            f"Chantier {job.job_id} : {step}",
            data={"code": "selfdev_step", "job_id": job.job_id, "step": step, "worktree": job.worktree, "branch": job.branch},
        )

    def _fail(self, job: Job, code: str, message: str) -> Job:
        job.status, job.error_code, job.error, job.ended_at = "failed", code, message, _now()
        self.jobs.save(job)
        self.journal.emit(
            "selfdev.failed",
            f"Chantier {job.job_id} abandonné : {message}",
            level="warning",
            data={"code": code, "job_id": job.job_id, "step": job.step, "worktree": job.worktree},
        )
        return job


def _default_python() -> str:
    import sys

    return sys.executable


def _tail(output: str, *, lines: int = 20) -> str:
    kept = [line for line in output.splitlines() if line.strip()][-lines:]
    return " / ".join(kept) if kept else "(aucune sortie)"


def _commit_message(job: Job, files: Sequence[str]) -> str:
    """Un message qui dit d'où vient le commit, sans recopier la demande entière."""
    title = " ".join(job.request.split())[:72]
    body = [
        "",
        f"Chantier : {job.job_id}",
        f"Profil : {job.profile}",
        f"Fichiers : {len(files)}",
    ]
    if job.routing.get("model"):
        body.append(f"Modèle : {job.routing['model']} ({job.routing.get('reason', routing.REASON_COMPATIBILITY)})")
    return "\n".join([title, *body, ""])


def quote(args: Sequence[str]) -> str:
    """Rendre une commande lisible dans le journal, sans jamais la réexécuter."""
    return " ".join(shlex.quote(str(arg)) for arg in args)
