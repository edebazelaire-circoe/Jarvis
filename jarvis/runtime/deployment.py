"""Faire passer un candidat du plan de construction au plan de service.

Fusionner n'est pas déployer. Un déploiement n'est fini que lorsque le code
tourne et répond ; tant qu'il n'a pas répondu, il est en cours, et s'il ne
répond pas, on revient à ce qui marchait.

La transaction, dans l'ordre, avec un marqueur durable écrit avant chaque
franchissement :

1. **verrou d'intégration** — un seul candidat à la fois, quel que soit le
   nombre de chantiers qui construisent en parallèle ;
2. **gardes du plan de service** — la copie qui sert doit être propre, sur la
   bonne branche, et ne pas avoir divergé. Sinon on s'arrête : du travail
   humain non validé ne se sacrifie pas pour un déploiement automatique ;
3. **réconciliation** — le candidat rejoint le `main` le plus récent dans son
   propre worktree. Un conflit arrête tout et rend le candidat à son chantier ;
   jamais de résolution automatique ;
4. **portes rejouées** — après réconciliation, ce n'est plus le même code : les
   tests repassent ;
5. **intégration** — poussée en avance rapide seulement. Pas de `--force` ;
6. **mise à jour du service** — `merge --ff-only` dans la copie qui sert ;
7. **rechargement** — le superviseur relance ses enfants sur le nouveau code ;
8. **santé** — Core prêt, sinon retour à la révision connue bonne.

Rien ici n'efface, ne réinitialise ni ne remise le travail de quelqu'un. Quand
le retour en arrière lui-même serait dangereux, la transaction s'arrête et le
dit : une escalade vaut mieux qu'une destruction.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.worktrees import WorktreeError, git

#: Un verrou d'intégration abandonné par un processus mort est repris après ce
#: délai. Court : une intégration qui dépasse l'heure a déjà échoué.
STALE_LOCK_S = 3600.0
GATE_TIMEOUT_S = 30 * 60.0
#: Attente maximale de la réponse de Core après un rechargement.
READY_TIMEOUT_S = 120.0
READY_POLL_S = 0.5

#: États du marqueur. `pending` est le seul qui demande une reprise au
#: démarrage : il veut dire « le service a été touché, l'issue est inconnue ».
PENDING = "pending"
COMMITTED = "committed"
ROLLED_BACK = "rolled_back"
BLOCKED = "blocked"

RELOAD_REQUEST = "reload.request"


class DeploymentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -------------------------------------------------------------------- verrou


class IntegrationLock:
    """Le goulot volontaire : plusieurs chantiers construisent, un seul intègre."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._held = False

    def acquire(self, *, job_id: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        holder = self._holder()
        if holder is not None:
            raise DeploymentError(
                "deploy_locked",
                f"Une intégration est déjà en cours (chantier « {holder.get('job_id')} », pid {holder.get('pid')}).",
            )
        self.path.unlink(missing_ok=True)
        try:
            with self.path.open("x", encoding="utf-8") as handle:
                json.dump({"job_id": job_id, "pid": os.getpid(), "acquired_at": _now()}, handle, ensure_ascii=False)
        except FileExistsError as exc:
            raise DeploymentError("deploy_locked", "Une intégration vient de commencer ailleurs.") from exc
        self._held = True

    def release(self) -> None:
        if self._held:
            self.path.unlink(missing_ok=True)
            self._held = False

    def _holder(self) -> dict[str, Any] | None:
        """Le détenteur, s'il est encore vivant et pas trop vieux."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        from jarvis.runtime.worktrees import _age_s, _alive

        if not _alive(int(raw.get("pid") or 0)) or _age_s(str(raw.get("acquired_at") or "")) >= STALE_LOCK_S:
            return None
        return raw

    def __enter__(self) -> "IntegrationLock":
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


# ------------------------------------------------------------------ marqueur


@dataclass(slots=True)
class Deployment:
    """Ce qu'on saura du déploiement même si le processus meurt au milieu."""

    job_id: str
    state: str = PENDING
    step: str = ""
    old_revision: str = ""
    new_revision: str = ""
    branch: str = ""
    started_at: str = field(default_factory=_now)
    ended_at: str = ""
    error_code: str = ""
    error: str = ""
    health: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeploymentMarker:
    """Le marqueur durable, écrit avant d'agir, jamais après."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def read(self) -> Deployment | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        try:
            return Deployment(**raw)
        except TypeError:
            return None

    def write(self, deployment: Deployment) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(deployment.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


# ---------------------------------------------------------------- inspection


async def revision(path: Path, ref: str = "HEAD") -> str:
    return (await git("rev-parse", ref, cwd=path)).strip()


async def current_branch(path: Path) -> str:
    return (await git("rev-parse", "--abbrev-ref", "HEAD", cwd=path)).strip()


async def is_clean(path: Path) -> bool:
    return not (await git("status", "--porcelain", cwd=path)).strip()


async def is_ancestor(path: Path, older: str, newer: str) -> bool:
    try:
        await git("merge-base", "--is-ancestor", older, newer, cwd=path)
    except WorktreeError:
        return False
    return True


# ------------------------------------------------------------- coordination


Gate = Callable[[Path], Awaitable[tuple[int, str]]]
Health = Callable[[], Awaitable[dict[str, Any]]]


class DeploymentCoordinator:
    """Une intégration à la fois, du candidat jusqu'à un service qui répond."""

    def __init__(
        self,
        *,
        primary: Path,
        runtime_root: Path,
        journal: RuntimeJournal | None = None,
        remote: str = "origin",
        base: str = "main",
        gate: Gate | None = None,
        python: str | None = None,
        tests: Sequence[str] = ("-m", "pytest", "-q"),
    ) -> None:
        self.primary = Path(primary).resolve()
        self.runtime_root = Path(runtime_root)
        self.journal = journal or RuntimeJournal(self.runtime_root)
        self.remote = remote
        self.base = base
        self.tests = tuple(tests)
        self.python = python or _default_python()
        self.gate = gate or self._default_gate
        self.lock = IntegrationLock(self.runtime_root / "integration.lock")
        self.marker = DeploymentMarker(self.runtime_root / "deployment.json")

    # -------------------------------------------------------------- gardes

    async def guard_primary(self) -> str:
        """Vérifier que la copie qui sert peut être mise à jour sans rien perdre.

        Sale, sur une autre branche, ou partie devant le distant : on s'arrête.
        Chacun de ces états veut dire qu'un humain travaille là, et son travail
        passe avant un déploiement automatique.
        """
        branch = await current_branch(self.primary)
        if branch != self.base:
            raise DeploymentError(
                "deploy_primary_branch",
                f"La copie qui sert est sur « {branch} », pas sur « {self.base} » : rien n'est déployé.",
            )
        if not await is_clean(self.primary):
            raise DeploymentError(
                "deploy_primary_dirty",
                "La copie qui sert a des modifications non validées : validez-les ou mettez-les de côté vous-même.",
            )
        await git("fetch", self.remote, self.base, "--quiet", cwd=self.primary)
        local = await revision(self.primary)
        remote_head = await revision(self.primary, f"{self.remote}/{self.base}")
        if local != remote_head and not await is_ancestor(self.primary, local, remote_head):
            raise DeploymentError(
                "deploy_primary_diverged",
                "La copie qui sert a divergé du dépôt distant : réconciliez-la à la main.",
            )
        return local

    # --------------------------------------------------------- intégration

    async def integrate(self, candidate: dict[str, Any]) -> Deployment:
        """Intégrer un candidat et laisser le service prêt à recharger.

        Rend un déploiement `pending` : le code est en place, la santé n'est pas
        encore prouvée. C'est `finish` qui conclut, après le rechargement.
        """
        job_id = str(candidate.get("job_id") or "inconnu")
        branch = str(candidate.get("branch") or "")
        worktree = Path(str(candidate.get("worktree") or ""))
        deployment = Deployment(job_id=job_id, branch=branch)
        try:
            # Un refus reste un état du déploiement, jamais une exception qui
            # remonte : l'appelant a toujours quelque chose à raconter.
            if not branch or not worktree.is_dir():
                raise DeploymentError("deploy_bad_candidate", "Candidat incomplet : branche ou worktree manquant.")
            if worktree.resolve() == self.primary:
                raise DeploymentError("deploy_bad_candidate", "Un candidat ne se réconcilie jamais dans la copie qui sert.")
            self.lock.acquire(job_id=job_id)

            old = await self.guard_primary()
            deployment.old_revision = old
            self._step(deployment, "guarded")

            await self._reconcile(deployment, worktree)
            await self._rerun_gates(deployment, worktree)
            deployment.new_revision = await revision(worktree)

            self._step(deployment, "integrating")
            await self._fast_forward_main(worktree, branch)

            # Marqueur écrit *avant* de toucher au service : une coupure ici
            # doit laisser une trace exploitable au redémarrage.
            self._step(deployment, "updating")
            self.marker.write(deployment)
            await self._update_primary(deployment)
            self._step(deployment, "reload_requested")
            self.request_reload()
        except DeploymentError as exc:
            return self._block(deployment, exc.code, str(exc))
        except WorktreeError as exc:
            return self._block(deployment, exc.code, str(exc))
        finally:
            self.lock.release()
        return deployment

    async def _reconcile(self, deployment: Deployment, worktree: Path) -> None:
        """Ramener le candidat sur le `main` le plus récent, dans son worktree.

        Un conflit n'est pas résolu ici, ni ailleurs : la fusion est annulée,
        le worktree retrouve son état d'avant, et le candidat repart en
        chantier avec une raison lisible.
        """
        await git("fetch", self.remote, self.base, "--quiet", cwd=worktree)
        target = await revision(worktree, f"{self.remote}/{self.base}")
        if await is_ancestor(worktree, target, "HEAD"):
            self._step(deployment, "reconciled")
            return
        try:
            await git("merge", "--no-edit", f"{self.remote}/{self.base}", cwd=worktree)
        except WorktreeError as exc:
            await self._abort_merge(worktree)
            raise DeploymentError(
                "deploy_conflict",
                f"Le candidat entre en conflit avec {self.base} : il doit être repris en chantier. {exc}",
            ) from exc
        self._step(deployment, "reconciled")

    @staticmethod
    async def _abort_merge(worktree: Path) -> None:
        try:
            await git("merge", "--abort", cwd=worktree)
        except WorktreeError:
            # Rien à annuler (la fusion n'avait pas commencé) : l'état est déjà
            # celui d'avant.
            pass

    async def _rerun_gates(self, deployment: Deployment, worktree: Path) -> None:
        """Après réconciliation, ce n'est plus le code qui avait été validé."""
        code, output = await self.gate(worktree)
        if code != 0:
            raise DeploymentError(
                "deploy_gate_failed",
                f"Les tests refusent le candidat réconcilié avec {self.base} : {_tail(output)}",
            )
        self._step(deployment, "gated")

    async def _fast_forward_main(self, worktree: Path, branch: str) -> None:
        """Publier le candidat sur `main`, en avance rapide uniquement.

        La poussée part du worktree et vise directement la branche distante :
        aucune copie de travail n'a besoin d'avoir `main` sorti, et le distant
        refuse tout seul ce qui ne serait pas une avance rapide.
        """
        try:
            await git("push", self.remote, f"HEAD:refs/heads/{self.base}", cwd=worktree)
        except WorktreeError as exc:
            raise DeploymentError(
                "deploy_push_rejected",
                f"Le dépôt distant a refusé l'intégration de {branch} : {exc}",
            ) from exc

    async def _update_primary(self, deployment: Deployment) -> None:
        """Mettre la copie qui sert au niveau, sans jamais forcer."""
        await git("fetch", self.remote, self.base, "--quiet", cwd=self.primary)
        try:
            await git("merge", "--ff-only", f"{self.remote}/{self.base}", cwd=self.primary)
        except WorktreeError as exc:
            raise DeploymentError(
                "deploy_primary_refused",
                f"La copie qui sert refuse l'avance rapide : {exc}",
            ) from exc
        deployment.new_revision = await revision(self.primary)

    # ------------------------------------------------------------- service

    def request_reload(self) -> None:
        """Demander au superviseur de relancer ses enfants sur le nouveau code."""
        path = self.runtime_root / RELOAD_REQUEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_now(), encoding="utf-8")

    def take_reload_request(self) -> bool:
        """Le superviseur consomme la demande. Vraie une seule fois."""
        path = self.runtime_root / RELOAD_REQUEST
        if not path.is_file():
            return False
        path.unlink(missing_ok=True)
        return True

    async def finish(self, *, health: Health) -> Deployment | None:
        """Conclure un déploiement en cours : santé prouvée, ou retour en arrière.

        Appelée au démarrage du service. Sans marqueur `pending`, il n'y a rien
        à conclure — c'est le cas de tous les démarrages ordinaires.
        """
        deployment = self.marker.read()
        if deployment is None or deployment.state != PENDING:
            return None
        report = await self._await_health(health)
        deployment.health = report
        if report.get("ready"):
            deployment.state, deployment.ended_at = COMMITTED, _now()
            self.marker.write(deployment)
            self.journal.emit(
                "deploy.committed",
                f"Déploiement confirmé : {deployment.new_revision[:12]} répond.",
                data={"code": "deploy_committed", **deployment.as_dict()},
            )
            return deployment
        return await self._rollback(deployment, report)

    async def _await_health(self, health: Health, *, timeout_s: float = READY_TIMEOUT_S) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        last: dict[str, Any] = {"ready": False, "error": "aucune réponse"}
        while loop.time() < deadline:
            try:
                last = dict(await health())
            except Exception as exc:  # noqa: BLE001 - un Core mort lève de mille façons
                last = {"ready": False, "error": f"{type(exc).__name__}: {exc}"}
            if last.get("ready"):
                return last
            await asyncio.sleep(READY_POLL_S)
        return last

    async def _rollback(self, deployment: Deployment, report: dict[str, Any]) -> Deployment:
        """Revenir à la révision connue bonne, sans rien détruire.

        La copie qui sert est détachée sur l'ancienne révision : la branche
        `main` garde ce qu'elle a, aucun commit ne disparaît, et un humain
        décide ensuite quoi faire du code fautif. Si même cela est impossible —
        typiquement parce que quelqu'un travaille dans la copie — on s'arrête et
        on le dit plutôt que d'écraser.
        """
        old = deployment.old_revision
        try:
            if not old:
                raise DeploymentError("deploy_no_known_good", "Aucune révision connue bonne n'a été enregistrée.")
            if not await is_clean(self.primary):
                raise DeploymentError(
                    "deploy_rollback_unsafe",
                    "La copie qui sert a été modifiée depuis : le retour en arrière écraserait ce travail.",
                )
            await git("switch", "--detach", old, cwd=self.primary)
        except (DeploymentError, WorktreeError) as exc:
            deployment.state = BLOCKED
            deployment.error_code = getattr(exc, "code", "deploy_rollback_failed")
            deployment.error = str(exc)
            deployment.ended_at = _now()
            self.marker.write(deployment)
            self.journal.emit(
                "deploy.blocked",
                f"Déploiement en échec et retour en arrière impossible : {exc}",
                level="error",
                data={"code": deployment.error_code, **deployment.as_dict()},
            )
            return deployment

        deployment.state, deployment.ended_at = ROLLED_BACK, _now()
        deployment.error_code = "deploy_unhealthy"
        deployment.error = str(report.get("error") or "Core n'a pas répondu prêt.")
        self.marker.write(deployment)
        self.journal.emit(
            "deploy.rolled_back",
            f"Déploiement annulé : retour à {old[:12]}, qui répondait. La branche {self.base} est inchangée.",
            level="warning",
            data={"code": "deploy_rolled_back", **deployment.as_dict()},
        )
        self.request_reload()
        return deployment

    # -------------------------------------------------------------- outils

    async def _default_gate(self, worktree: Path) -> tuple[int, str]:
        process = await asyncio.create_subprocess_exec(
            self.python,
            *self.tests,
            cwd=str(worktree),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=GATE_TIMEOUT_S)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return 1, f"Les tests n'ont pas fini en {GATE_TIMEOUT_S / 60:.0f} min."
        return int(process.returncode or 0), (stdout or b"").decode("utf-8", "replace")

    def _step(self, deployment: Deployment, step: str) -> None:
        deployment.step = step
        self.journal.emit(
            "deploy.step",
            f"Déploiement {deployment.job_id} : {step}",
            data={"code": "deploy_step", "job_id": deployment.job_id, "step": step, "branch": deployment.branch},
        )

    def _block(self, deployment: Deployment, code: str, message: str) -> Deployment:
        deployment.state = BLOCKED
        deployment.error_code, deployment.error, deployment.ended_at = code, message, _now()
        # Un blocage avant toute écriture dans le service ne laisse pas de
        # marqueur `pending` : il n'y a rien à reprendre au démarrage.
        if deployment.step in {"updating", "reload_requested"}:
            self.marker.write(deployment)
        self.journal.emit(
            "deploy.blocked",
            f"Déploiement refusé : {message}",
            level="warning",
            data={"code": code, **deployment.as_dict()},
        )
        return deployment


def _default_python() -> str:
    import sys

    return sys.executable


def _tail(output: str, *, lines: int = 20) -> str:
    kept = [line for line in output.splitlines() if line.strip()][-lines:]
    return " / ".join(kept) if kept else "(aucune sortie)"
