"""Les deux capacités, ensemble, sur un vrai dépôt.

Ce que ce fichier prouve, et qu'aucun test unitaire ne peut prouver seul : que
la politique d'aiguillage choisit bien le modèle qui atteint la commande de
l'agent de code, que deux chantiers en parallèle ne se marchent pas dessus, et
qu'une panne à n'importe quel moment laisse la copie qui sert dans un état sûr.

Les agents et les modèles sont simulés — aucune clé, aucun réseau. Ce qui est
réel, et c'est là que sont les pièges : git, les worktrees, les baux, les
verrous, les fichiers d'état.
"""

from __future__ import annotations

import asyncio
import json
from functools import partial
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from jarvis.domain import routing
from jarvis.runtime import agent_routing, routing_hook, self_dev
from jarvis.runtime.deployment import BLOCKED, COMMITTED, PENDING, ROLLED_BACK, DeploymentCoordinator
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.self_dev import SelfDevelopmentRunner
from jarvis.runtime.worktrees import WorktreePool

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")

AGENTS = [
    {
        "id": "claude",
        "label": "Claude Code",
        "model_provider": "anthropic",
        "capabilities": [routing.CODE, routing.SEMANTIC, routing.COMPUTER_USE],
        "available": True,
        "error": "",
    }
]
MODELS = {
    "anthropic": [
        {"id": "grand", "label": "Grand", "roles": ("text",)},
        {"id": "petit", "label": "Petit", "roles": ("text",)},
    ]
}


def run(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def identify(path: Path) -> None:
    for key, value in (("user.email", "t@j.local"), ("user.name", "T")):
        run("config", key, value, cwd=path)


async def green(_worktree) -> tuple[int, str]:
    return 0, ""


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Un distant, une copie de service, deux worktrees de construction."""
    monkeypatch.delenv("JARVIS_WORKTREE_ROOT", raising=False)
    remote = tmp_path / "remote.git"
    remote.mkdir()
    run("init", "-q", "--bare", "-b", "main", cwd=remote)

    primary = tmp_path / "jarvis"
    run("clone", "-q", str(remote), str(primary), cwd=tmp_path)
    identify(primary)
    (primary / "fichier.txt").write_text("un\n", encoding="utf-8")
    run("add", "-A", cwd=primary)
    run("commit", "-q", "-m", "depart", cwd=primary)
    run("push", "-q", "-u", "origin", "main", cwd=primary)

    root = tmp_path / "sub-agents"
    root.mkdir()
    for name in ("un", "deux"):
        run("worktree", "add", "-q", "-b", f"agent/{name}", str(root / name), cwd=primary)
        identify(root / name)

    runtime = tmp_path / "runtime"
    pool = WorktreePool(primary=primary, root=root, lease_root=runtime / "leases")
    coordinator = DeploymentCoordinator(primary=primary, runtime_root=runtime, gate=green)
    return pool, coordinator, primary, remote, runtime


def settings_with(policy: list[dict], *, enabled: bool = True) -> dict:
    settings: dict = {}
    agent_routing.apply(settings, {"enabled": enabled, "profiles": {"code": {"candidates": policy}}})
    return settings


def catalogue(monkeypatch, *, models=None) -> None:
    """Le catalogue et les CLI, sans réseau ni PATH."""
    monkeypatch.setattr(
        routing_hook,
        "offline_candidates",
        lambda root, policy: agent_routing.with_saved(
            agent_routing.build_candidates(AGENTS, models if models is not None else MODELS), policy
        ),
    )


def runner_for(pool, runtime, settings, monkeypatch, *, name: str, seen: list) -> SelfDevelopmentRunner:
    made = SelfDevelopmentRunner(
        pool=pool,
        runtime_root=runtime,
        settings=settings,
        tests=("-c", "raise SystemExit(0)"),
        python=sys.executable,
    )

    def command(agent_id: str, model: str, request: str):  # noqa: ANN202
        seen.append((agent_id, model))
        return sys.executable, ["-c", f"open({name!r},'w',encoding='utf-8').write({request!r})"]

    monkeypatch.setattr(made, "_agent_command", command)
    return made


def head(path: Path) -> str:
    return run("rev-parse", "HEAD", cwd=path).strip()


# ================================================================ bout en bout


async def test_the_policy_chooses_the_model_that_actually_builds_and_ships(site, monkeypatch):
    """Politique → modèle → commande de l'agent → candidat → service à jour."""

    pool, coordinator, primary, remote, runtime = site
    catalogue(monkeypatch)
    settings = settings_with([{"agent": "claude", "model": "grand"}])
    seen: list = []
    runner = runner_for(pool, runtime, settings, monkeypatch, name="ajout.txt", seen=seen)

    job = await runner.run("Ajouter un fichier de démonstration")
    assert job.status == "succeeded"
    # Le modèle autorisé est bien celui qui a travaillé.
    assert seen == [("claude", "grand")]
    assert job.routing["reason"] == routing.REASON_PREFERRED

    deployment = await coordinator.integrate(job.candidate)
    assert deployment.state == PENDING
    assert head(primary) == deployment.new_revision
    assert run("rev-parse", "main", cwd=remote).strip() == deployment.new_revision

    async def healthy() -> dict:
        return {"ready": True}

    assert (await coordinator.finish(health=healthy)).state == COMMITTED
    # La preuve tient dans la trace : profil, modèle, révisions, sans raisonnement.
    trace = read_jsonl_tail(runtime / "trace.jsonl", limit=500)
    committed = [e for e in trace if e["kind"] == "deploy.committed"]
    assert committed and committed[-1]["data"]["new_revision"] == deployment.new_revision
    assert "Ajouter un fichier" not in json.dumps(committed[-1], ensure_ascii=False)


async def test_an_unavailable_preferred_model_falls_back_and_says_so(site, monkeypatch):
    pool, _coordinator, _primary, _remote, runtime = site
    # Le modèle préféré a quitté le catalogue du fournisseur depuis le réglage.
    catalogue(monkeypatch, models={"anthropic": [{"id": "petit", "label": "Petit", "roles": ("text",)}]})
    settings = settings_with([{"agent": "claude", "model": "grand"}, {"agent": "claude", "model": "petit"}])
    seen: list = []
    runner = runner_for(pool, runtime, settings, monkeypatch, name="ajout.txt", seen=seen)

    job = await runner.run("Travail de repli")

    assert seen == [("claude", "petit")]
    assert job.routing["reason"] == routing.REASON_FALLBACK
    assert job.routing["fallback_from"] == {"agent": "claude", "model": "grand"}
    assert job.routing["fallback_code"] == routing.REJECT_MODEL_UNAVAILABLE


async def test_two_jobs_build_at_the_same_time_but_integrate_one_after_the_other(site, monkeypatch):
    """Le cas qui casse tout si l'on s'y prend mal : deux chantiers partis de la
    même base, chacun dans son worktree, et un seul `main`."""

    pool, coordinator, primary, _remote, runtime = site
    catalogue(monkeypatch)
    settings = settings_with([{"agent": "claude", "model": "grand"}])
    first = runner_for(pool, runtime, settings, monkeypatch, name="a.txt", seen=[])
    second = runner_for(pool, runtime, settings, monkeypatch, name="b.txt", seen=[])

    jobs = await asyncio.gather(first.run("Chantier A"), second.run("Chantier B"))

    assert [job.status for job in jobs] == ["succeeded", "succeeded"]
    # Chacun a eu son worktree : les baux ont fait leur travail.
    assert len({job.worktree for job in jobs}) == 2
    assert jobs[0].candidate["base_revision"] == jobs[1].candidate["base_revision"]
    assert pool.leases() == []

    # Intégrés l'un après l'autre : le second doit rejoindre le main du premier.
    results = [await coordinator.integrate(job.candidate) for job in jobs]

    assert [result.state for result in results] == [PENDING, PENDING]
    assert (primary / "a.txt").is_file() and (primary / "b.txt").is_file()
    assert results[1].old_revision == results[0].new_revision


async def test_a_second_integration_during_the_first_one_is_refused_not_queued(site, monkeypatch):
    pool, coordinator, _primary, _remote, runtime = site
    catalogue(monkeypatch)
    settings = settings_with([{"agent": "claude", "model": "grand"}])
    runner = runner_for(pool, runtime, settings, monkeypatch, name="a.txt", seen=[])
    job = await runner.run("Chantier A")

    coordinator.lock.acquire(job_id="quelqu-un-d-autre")
    blocked = await coordinator.integrate(job.candidate)
    coordinator.lock.release()

    assert blocked.state == BLOCKED and blocked.error_code == "deploy_locked"
    assert (await coordinator.integrate(job.candidate)).state == PENDING


# ==================================================================== pannes


async def test_a_deployment_that_never_answers_comes_back_to_what_worked(site, monkeypatch):
    pool, coordinator, primary, remote, runtime = site
    from jarvis.runtime import deployment as deploy

    # Le défaut est lié à la définition : passer le budget au vrai poller.
    monkeypatch.setattr(coordinator, "_await_health", partial(coordinator._await_health, timeout_s=0.05))
    monkeypatch.setattr(deploy, "READY_POLL_S", 0.01)
    catalogue(monkeypatch)
    settings = settings_with([{"agent": "claude", "model": "grand"}])
    runner = runner_for(pool, runtime, settings, monkeypatch, name="casse.txt", seen=[])
    job = await runner.run("Un changement qui ne démarre pas")
    result = await coordinator.integrate(job.candidate)
    known_good = result.old_revision

    async def silent() -> dict:
        return {"ready": False, "error": "Core muet"}

    rolled = await coordinator.finish(health=silent)

    assert rolled.state == ROLLED_BACK
    assert head(primary) == known_good
    assert not (primary / "casse.txt").exists()
    # Rien n'a disparu : le commit fautif est toujours sur `main`.
    assert run("rev-parse", "main", cwd=remote).strip() == result.new_revision
    # Et le retour en arrière est dit, pas caché.
    assert [e for e in read_jsonl_tail(runtime / "trace.jsonl", limit=500) if e["kind"] == "deploy.rolled_back"]


async def test_an_interrupted_deployment_is_concluded_by_the_next_process(site, monkeypatch):
    pool, coordinator, primary, _remote, runtime = site
    catalogue(monkeypatch)
    settings = settings_with([{"agent": "claude", "model": "grand"}])
    runner = runner_for(pool, runtime, settings, monkeypatch, name="a.txt", seen=[])
    job = await runner.run("Chantier A")
    result = await coordinator.integrate(job.candidate)

    # Le processus meurt ici. Un autre démarre, sans rien en mémoire.
    reborn = DeploymentCoordinator(primary=primary, runtime_root=runtime, gate=green)

    async def healthy() -> dict:
        return {"ready": True}

    concluded = await reborn.finish(health=healthy)

    assert concluded.state == COMMITTED and concluded.new_revision == result.new_revision


async def test_a_human_editing_the_serving_copy_stops_everything_before_it_starts(site, monkeypatch):
    pool, coordinator, primary, _remote, runtime = site
    catalogue(monkeypatch)
    settings = settings_with([{"agent": "claude", "model": "grand"}])
    runner = runner_for(pool, runtime, settings, monkeypatch, name="a.txt", seen=[])
    job = await runner.run("Chantier A")

    (primary / "brouillon.txt").write_text("en cours d'écriture\n", encoding="utf-8")
    before = head(primary)

    blocked = await coordinator.integrate(job.candidate)

    assert blocked.error_code == "deploy_primary_dirty"
    assert head(primary) == before
    assert (primary / "brouillon.txt").read_text(encoding="utf-8") == "en cours d'écriture\n"
    # Le candidat n'est pas perdu pour autant : il attend.
    assert job.candidate["branch"]


async def test_a_forbidden_model_can_never_reach_a_subagent_launch(site, monkeypatch):
    """La même politique, vue depuis le cerveau : le hook corrige l'appel."""

    _pool, _coordinator, _primary, _remote, runtime = site
    policy = agent_routing.load_policy(settings_with([{"agent": "claude", "model": "petit"}]))
    candidates = agent_routing.build_candidates(AGENTS, MODELS)

    output, decision = routing_hook.decide(
        {"tool_name": "Agent", "tool_input": {"description": "[code] Corriger", "model": "grand"}},
        policy,
        candidates,
    )

    assert output["hookSpecificOutput"]["updatedInput"] == {"model": "petit"}
    assert decision.model == "petit"


async def test_the_whole_chain_stays_off_until_the_user_opens_it(site):
    """Aucun de ces morceaux ne s'active tout seul."""

    _pool, _coordinator, _primary, _remote, _runtime = site
    assert self_dev.load_gate({}) == {"enabled": False, "auto_deploy": False}
    assert agent_routing.load_policy({}).enabled is False
    assert routing_hook.run({"tool_name": "Agent", "tool_input": {"model": "n-importe-quoi"}}, Path(".")) == {}
