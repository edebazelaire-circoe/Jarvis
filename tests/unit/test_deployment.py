"""Fusionner n'est pas déployer.

Chaque scénario ici finit par la même question : dans quel état est la copie
qui sert ? Un déploiement réussi la fait avancer ; un déploiement refusé ne la
touche pas ; un déploiement malade la ramène à ce qui répondait. Aucun de ces
chemins n'a le droit de détruire du travail.
"""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from jarvis.runtime import deployment as deploy
from jarvis.runtime.deployment import (
    BLOCKED,
    COMMITTED,
    PENDING,
    ROLLED_BACK,
    DeploymentCoordinator,
    DeploymentError,
    IntegrationLock,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


def run(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


async def green(_worktree: Path) -> tuple[int, str]:
    return 0, ""


async def red(_worktree: Path) -> tuple[int, str]:
    return 1, "1 failed"


def healthy():
    async def check() -> dict:
        return {"ready": True}

    return check


def unhealthy():
    async def check() -> dict:
        return {"ready": False, "error": "Core ne répond pas"}

    return check


@pytest.fixture
def field(tmp_path):
    """Un distant nu, la copie qui sert, et deux worktrees de construction."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    run("init", "-q", "--bare", "-b", "main", cwd=remote)

    primary = tmp_path / "jarvis"
    run("clone", "-q", str(remote), str(primary), cwd=tmp_path)
    for key, value in (("user.email", "t@j.local"), ("user.name", "T")):
        run("config", key, value, cwd=primary)
    (primary / "fichier.txt").write_text("un\n", encoding="utf-8")
    run("add", "-A", cwd=primary)
    run("commit", "-q", "-m", "depart", cwd=primary)
    run("push", "-q", "-u", "origin", "main", cwd=primary)

    root = tmp_path / "sub-agents"
    root.mkdir()
    worktrees = {}
    for name in ("un", "deux"):
        path = root / name
        run("worktree", "add", "-q", "-b", f"agent/{name}", str(path), cwd=primary)
        for key, value in (("user.email", "t@j.local"), ("user.name", "T")):
            run("config", key, value, cwd=path)
        worktrees[name] = path

    coordinator = DeploymentCoordinator(
        primary=primary,
        runtime_root=tmp_path / "runtime",
        gate=green,
        python=sys.executable,
    )
    return coordinator, primary, remote, worktrees


def candidate(worktree: Path, *, job_id: str, text: str = "deux\n", name: str = "ajout.txt") -> dict:
    """Une branche de chantier prête à intégrer, comme le runner en produit."""
    branch = f"selfdev/{job_id}"
    base = run("rev-parse", "origin/main", cwd=worktree).strip()
    run("checkout", "-q", "-b", branch, base, cwd=worktree)
    (worktree / name).write_text(text, encoding="utf-8")
    run("add", "-A", cwd=worktree)
    run("commit", "-q", "-m", f"travail {job_id}", cwd=worktree)
    run("push", "-q", "-u", "origin", f"{branch}:{branch}", cwd=worktree)
    return {
        "job_id": job_id,
        "branch": branch,
        "worktree": str(worktree),
        "base": "main",
        "base_revision": base,
        "revision": run("rev-parse", "HEAD", cwd=worktree).strip(),
    }


def head(path: Path) -> str:
    return run("rev-parse", "HEAD", cwd=path).strip()


# ------------------------------------------------------------------- verrou


def test_only_one_integration_can_hold_the_lock(tmp_path):
    lock = IntegrationLock(tmp_path / "integration.lock")
    lock.acquire(job_id="un")

    other = IntegrationLock(tmp_path / "integration.lock")
    with pytest.raises(DeploymentError) as error:
        other.acquire(job_id="deux")
    assert error.value.code == "deploy_locked" and "un" in str(error.value)

    lock.release()
    other.acquire(job_id="deux")
    other.release()


def test_a_lock_left_by_a_dead_process_is_taken_over(tmp_path, monkeypatch):
    lock = IntegrationLock(tmp_path / "integration.lock")
    lock.acquire(job_id="mort")
    monkeypatch.setattr("jarvis.runtime.worktrees._alive", lambda pid: False)

    IntegrationLock(tmp_path / "integration.lock").acquire(job_id="vivant")


# ---------------------------------------------------------------- nominal


async def test_a_healthy_deployment_moves_the_serving_copy_and_is_confirmed(field):
    coordinator, primary, remote, worktrees = field
    before = head(primary)

    result = await coordinator.integrate(candidate(worktrees["un"], job_id="j1"))

    assert result.state == PENDING and result.step == "reload_requested"
    assert result.old_revision == before and result.new_revision != before
    # Le service a avancé, et `main` chez le distant aussi.
    assert head(primary) == result.new_revision
    assert run("rev-parse", "main", cwd=remote).strip() == result.new_revision
    # Le rechargement est demandé, une fois.
    assert coordinator.take_reload_request() is True
    assert coordinator.take_reload_request() is False

    confirmed = await coordinator.finish(health=healthy())
    assert confirmed.state == COMMITTED
    assert coordinator.marker.read().state == COMMITTED


async def test_an_ordinary_start_has_no_deployment_to_conclude(field):
    coordinator, _primary, _remote, _worktrees = field
    assert await coordinator.finish(health=healthy()) is None


# --------------------------------------------------------- sérialisation


async def test_the_second_candidate_reconciles_with_the_main_the_first_one_made(field):
    """Deux chantiers partis de la même base : le second doit rejoindre le
    nouveau `main` et repasser les tests avant d'intégrer."""

    coordinator, primary, _remote, worktrees = field
    first = candidate(worktrees["un"], job_id="j1", text="premier\n", name="a.txt")
    second = candidate(worktrees["deux"], job_id="j2", text="second\n", name="b.txt")
    assert first["base_revision"] == second["base_revision"]

    gates: list[Path] = []

    async def counting(worktree: Path) -> tuple[int, str]:
        gates.append(worktree)
        return 0, ""

    coordinator.gate = counting

    await coordinator.integrate(first)
    await coordinator.finish(health=healthy())
    after_first = head(primary)

    result = await coordinator.integrate(second)

    assert result.state == PENDING
    # Les portes ont bien été rejouées dans le worktree du second, après fusion.
    assert gates[-1] == worktrees["deux"]
    # Les deux travaux sont présents : rien n'a été perdu en route.
    assert (primary / "a.txt").is_file() and (primary / "b.txt").is_file()
    assert head(primary) != after_first


async def test_two_integrations_cannot_run_at_the_same_time(field):
    coordinator, _primary, _remote, worktrees = field
    coordinator.lock.acquire(job_id="deja-la")

    result = await coordinator.integrate(candidate(worktrees["un"], job_id="j1"))

    assert result.state == BLOCKED and result.error_code == "deploy_locked"


# --------------------------------------------------------------- refus


async def test_a_dirty_serving_copy_blocks_the_deployment_without_touching_it(field):
    coordinator, primary, _remote, worktrees = field
    (primary / "en-cours.txt").write_text("travail humain\n", encoding="utf-8")
    before = head(primary)

    result = await coordinator.integrate(candidate(worktrees["un"], job_id="j1"))

    assert result.state == BLOCKED and result.error_code == "deploy_primary_dirty"
    assert head(primary) == before
    assert (primary / "en-cours.txt").read_text(encoding="utf-8") == "travail humain\n"
    # Rien à reprendre au démarrage : le service n'a pas été touché.
    assert coordinator.marker.read() is None


async def test_a_serving_copy_on_another_branch_blocks_too(field):
    coordinator, primary, _remote, worktrees = field
    run("checkout", "-q", "-b", "essai-humain", cwd=primary)

    result = await coordinator.integrate(candidate(worktrees["un"], job_id="j1"))

    assert result.error_code == "deploy_primary_branch"


async def test_a_diverged_serving_copy_is_never_reconciled_automatically(field):
    coordinator, primary, _remote, worktrees = field
    (primary / "local.txt").write_text("commit local\n", encoding="utf-8")
    run("add", "-A", cwd=primary)
    run("commit", "-q", "-m", "travail local non poussé", cwd=primary)
    before = head(primary)
    prepared = candidate(worktrees["un"], job_id="j1")

    result = await coordinator.integrate(prepared)

    assert result.error_code == "deploy_primary_diverged"
    assert head(primary) == before


async def test_a_conflicting_candidate_stops_and_leaves_its_worktree_as_it_was(field):
    coordinator, primary, _remote, worktrees = field
    # Les deux chantiers touchent la même ligne du même fichier.
    first = candidate(worktrees["un"], job_id="j1", text="version A\n", name="partage.txt")
    second = candidate(worktrees["deux"], job_id="j2", text="version B\n", name="partage.txt")
    await coordinator.integrate(first)
    await coordinator.finish(health=healthy())
    after_first = head(primary)

    result = await coordinator.integrate(second)

    assert result.state == BLOCKED and result.error_code == "deploy_conflict"
    assert head(primary) == after_first
    # Le worktree du candidat est rendu propre : la fusion a été annulée.
    assert not run("status", "--porcelain", cwd=worktrees["deux"]).strip()
    assert (primary / "partage.txt").read_text(encoding="utf-8") == "version A\n"


async def test_red_gates_after_reconciliation_stop_the_integration(field):
    coordinator, primary, remote, worktrees = field
    coordinator.gate = red
    before = head(primary)

    result = await coordinator.integrate(candidate(worktrees["un"], job_id="j1"))

    assert result.error_code == "deploy_gate_failed" and "1 failed" in result.error
    assert head(primary) == before
    assert run("rev-parse", "main", cwd=remote).strip() == before


async def test_an_incomplete_candidate_is_refused_before_anything_happens(field):
    coordinator, _primary, _remote, _worktrees = field
    result = await coordinator.integrate({"job_id": "j", "branch": "", "worktree": ""})
    assert result.error_code == "deploy_bad_candidate"


async def test_the_serving_copy_is_never_the_place_where_a_candidate_is_reconciled(field):
    coordinator, primary, _remote, _worktrees = field
    result = await coordinator.integrate({"job_id": "j", "branch": "selfdev/j", "worktree": str(primary)})
    assert result.error_code == "deploy_bad_candidate"


# ----------------------------------------------------- santé et retour arrière


async def test_a_deployment_that_never_answers_goes_back_to_what_did(field, monkeypatch):
    coordinator, primary, remote, worktrees = field
    # Le défaut est lié à la définition : passer le budget au vrai poller.
    monkeypatch.setattr(coordinator, "_await_health", partial(coordinator._await_health, timeout_s=0.05))
    monkeypatch.setattr(deploy, "READY_POLL_S", 0.01)
    prepared = candidate(worktrees["un"], job_id="j1")
    result = await coordinator.integrate(prepared)
    known_good = result.old_revision

    rolled = await coordinator.finish(health=unhealthy())

    assert rolled.state == ROLLED_BACK and rolled.error_code == "deploy_unhealthy"
    # Le service est revenu sur ce qui répondait...
    assert head(primary) == known_good
    # ...sans qu'aucun commit ne disparaisse : `main` garde la révision fautive.
    assert run("rev-parse", "main", cwd=remote).strip() == result.new_revision
    assert coordinator.take_reload_request() is True


async def test_a_rollback_that_would_crush_someone_s_work_stops_and_says_so(field, monkeypatch):
    coordinator, primary, _remote, worktrees = field
    monkeypatch.setattr(coordinator, "_await_health", partial(coordinator._await_health, timeout_s=0.05))
    monkeypatch.setattr(deploy, "READY_POLL_S", 0.01)
    await coordinator.integrate(candidate(worktrees["un"], job_id="j1"))
    # Quelqu'un est intervenu dans la copie qui sert entre-temps.
    (primary / "urgence.txt").write_text("correctif à chaud\n", encoding="utf-8")

    blocked = await coordinator.finish(health=unhealthy())

    assert blocked.state == BLOCKED and blocked.error_code == "deploy_rollback_unsafe"
    assert (primary / "urgence.txt").read_text(encoding="utf-8") == "correctif à chaud\n"


async def test_an_interrupted_deployment_is_concluded_at_the_next_start(field):
    """Le processus est mort après la mise à jour du service : au redémarrage,
    le marqueur suffit à reprendre, sans rien redemander à personne."""

    coordinator, primary, _remote, worktrees = field
    result = await coordinator.integrate(candidate(worktrees["un"], job_id="j1"))
    assert coordinator.marker.read().state == PENDING

    # Nouveau processus : rien en mémoire, tout sur le disque.
    reborn = DeploymentCoordinator(primary=primary, runtime_root=coordinator.runtime_root, gate=green)
    concluded = await reborn.finish(health=healthy())

    assert concluded.state == COMMITTED and concluded.new_revision == result.new_revision


async def test_a_deployment_already_concluded_is_not_replayed(field):
    coordinator, _primary, _remote, worktrees = field
    await coordinator.integrate(candidate(worktrees["un"], job_id="j1"))
    await coordinator.finish(health=healthy())

    assert await coordinator.finish(health=unhealthy()) is None


def test_an_unreadable_marker_is_treated_as_no_deployment(field):
    coordinator, _primary, _remote, _worktrees = field
    coordinator.marker.path.parent.mkdir(parents=True, exist_ok=True)
    coordinator.marker.path.write_text("{ pas du json", encoding="utf-8")
    assert coordinator.marker.read() is None


# ------------------------------------------------------------------ interdits


def test_the_deployment_path_contains_no_destructive_git_command():
    forbidden = {"--force", "-f", "--hard", "reset", "clean", "stash", "--theirs", "--ours"}
    calls = [
        line
        for line in Path(deploy.__file__).read_text(encoding="utf-8").splitlines()
        if "git(" in line and not line.lstrip().startswith(("#", "async def", "def "))
    ]

    assert calls
    for line in calls:
        assert not {value.strip("\"'") for value in line.split(",")} & forbidden, line.strip()


def test_the_supervisor_concludes_the_deployment_only_after_core_answered():
    source = Path(__file__).resolve().parents[2] / "scripts" / "supervisor_v2.py"
    text = source.read_text(encoding="utf-8")
    body = text[text.index("async def run(") :]

    assert body.index("wait_core_ready") < body.index("settle_deployment")
    # Et le rechargement se fait après avoir arrêté les enfants.
    reload_body = text[text.index("async def _reload(") : text.index("async def run(")]
    assert reload_body.index("await self.stop()") < reload_body.index("os.execv")
