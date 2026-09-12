"""La façade : demander un chantier, suivre son avancée, déployer son candidat.

Trois règles de conduite, qui expliquent tout ce qui suit :

- **rien n'est automatique tant que personne ne l'a ouvert.** Construire et
  déployer sont deux autorisations distinctes, éteintes toutes les deux à
  l'installation ;
- **un chantier ne fait jamais attendre celui qui l'a demandé.** La demande
  rend un identifiant tout de suite, le travail continue en fond — c'est la
  même règle que pour les sous-agents du cerveau ;
- **un seul chantier à la fois par worktree, un seul déploiement à la fois.**
  Le bail et le verrou d'intégration s'en chargent ; cette façade ne les
  double pas.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from jarvis.runtime import self_dev
from jarvis.runtime.deployment import DeploymentCoordinator
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.self_dev import Job, SelfDevelopmentRunner, SelfDevError
from jarvis.runtime.worktrees import WorktreeError, WorktreePool, describe


class SelfDevelopmentService:
    def __init__(
        self,
        *,
        project_root: Path,
        runtime_root: Path,
        settings: Callable[[], dict[str, Any]],
        journal: RuntimeJournal | None = None,
        gate: Any = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.runtime_root = Path(runtime_root)
        self.read_settings = settings
        # Les portes rejouées après réconciliation. Par défaut la suite du
        # dépôt ; injectables pour qu'un test ne dépende pas d'elle.
        self.gate_command = gate
        self.journal = journal or RuntimeJournal(self.runtime_root)
        self.pool = WorktreePool(primary=self.project_root, lease_root=self.runtime_root / "worktree-leases")
        self.jobs = self_dev.JobStore(self.runtime_root / "self-dev")
        self._tasks: dict[str, asyncio.Task[Job]] = {}

    # ------------------------------------------------------------ lecture

    def gate(self) -> dict[str, bool]:
        return self_dev.load_gate(self.read_settings())

    async def state(self) -> dict[str, Any]:
        """Tout ce qu'il faut pour comprendre où en est l'auto-développement."""
        try:
            worktrees = await self.pool.discover()
            pool = describe(worktrees, self.pool.leases())
            pool_error = ""
        except WorktreeError as exc:
            pool, pool_error = {"worktrees": [], "leases": []}, str(exc)
        deployment = self._coordinator().marker.read()
        return {
            "ok": True,
            **self.gate(),
            "root": str(self.pool.root or ""),
            "pool_error": pool_error,
            **pool,
            "jobs": [job.as_dict() for job in self.jobs.all()],
            "running": sorted(self._tasks),
            "deployment": deployment.as_dict() if deployment is not None else None,
        }

    # ----------------------------------------------------------- chantier

    def start(self, request: str, *, profile: str = "code") -> Job:
        """Ouvrir un chantier et rendre la main tout de suite."""
        gate = self.gate()
        if not gate["enabled"]:
            raise SelfDevError(
                "selfdev_not_allowed",
                "L'auto-développement est éteint. Ouvrez-le dans les réglages avant de demander un chantier.",
            )
        runner = self._runner()
        job = Job(job_id=f"selfdev-{_ticket()}", request=str(request or "").strip(), profile=profile)
        self.jobs.save(job)
        self.journal.emit(
            "selfdev.requested",
            f"Chantier demandé : {job.request[:120]}",
            data={"code": "selfdev_requested", "job_id": job.job_id, "profile": profile},
        )
        task = asyncio.create_task(self._work(runner, job), name=f"jarvis-selfdev-{job.job_id}")
        self._tasks[job.job_id] = task
        task.add_done_callback(lambda _t, key=job.job_id: self._tasks.pop(key, None))
        return job

    async def _work(self, runner: SelfDevelopmentRunner, job: Job) -> Job:
        done = await runner.run(job.request, profile=job.profile, job_id=job.job_id)
        if done.status != "succeeded" or not done.candidate:
            return done
        if not self.gate()["auto_deploy"]:
            self.journal.emit(
                "selfdev.candidate",
                f"Candidat prêt : {done.candidate['branch']}. Le déploiement attend une demande explicite.",
                data={"code": "selfdev_candidate_ready", "job_id": done.job_id, **done.candidate},
            )
            return done
        await self.deploy(done.job_id)
        return done

    # --------------------------------------------------------- déploiement

    async def deploy(self, job_id: str) -> dict[str, Any]:
        """Intégrer le candidat d'un chantier. Le rechargement suit, s'il aboutit."""
        gate = self.gate()
        if not gate["enabled"]:
            raise SelfDevError("selfdev_not_allowed", "L'auto-développement est éteint.")
        job = self.jobs.load(job_id)
        if job is None:
            raise SelfDevError("selfdev_unknown_job", f"Chantier inconnu : {job_id}.")
        if not job.candidate:
            raise SelfDevError("selfdev_no_candidate", f"Le chantier {job_id} n'a produit aucun candidat.")
        deployment = await self._coordinator().integrate(job.candidate)
        return deployment.as_dict()

    # -------------------------------------------------------------- outils

    def _runner(self) -> SelfDevelopmentRunner:
        return SelfDevelopmentRunner(
            pool=self.pool,
            runtime_root=self.runtime_root,
            settings=self.read_settings(),
            journal=self.journal,
        )

    def _coordinator(self) -> DeploymentCoordinator:
        return DeploymentCoordinator(
            primary=self.project_root,
            runtime_root=self.runtime_root,
            journal=self.journal,
            gate=self.gate_command,
        )


def _ticket() -> str:
    import uuid

    return uuid.uuid4().hex[:12]
