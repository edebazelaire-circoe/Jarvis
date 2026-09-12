"""JARVIS modifie son propre code — ailleurs que là où il tourne.

Tout se joue sur de vrais dépôts temporaires, avec un dépôt distant nu, une
copie de service et un worktree de construction. Ce qui est prouvé à chaque
scénario, y compris les ratés : la copie qui sert n'a pas bougé d'un octet, et
le bail a été rendu.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from jarvis.runtime import self_dev
from jarvis.runtime.self_dev import SelfDevelopmentRunner
from jarvis.runtime.worktrees import WorktreePool

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")

PASSING_TESTS = ("-c", "raise SystemExit(0)")
FAILING_TESTS = ("-c", "import sys; print('2 failed'); sys.exit(1)")


def run(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def writer(text: str = "écrit par l'agent\n", name: str = "ajout.txt") -> tuple[str, list[str]]:
    """Un « agent de code » minimal : il écrit un fichier dans son cwd."""
    return sys.executable, ["-c", f"open({name!r}, 'w', encoding='utf-8').write({text!r})"]


@pytest.fixture
def workshop(tmp_path):
    remote = tmp_path / "remote.git"
    remote.mkdir()
    run("init", "-q", "--bare", "-b", "main", cwd=remote)

    primary = tmp_path / "jarvis"
    run("clone", "-q", str(remote), str(primary), cwd=tmp_path)
    run("config", "user.email", "test@jarvis.local", cwd=primary)
    run("config", "user.name", "Test", cwd=primary)
    (primary / "fichier.txt").write_text("un\n", encoding="utf-8")
    run("add", "-A", cwd=primary)
    run("commit", "-q", "-m", "depart", cwd=primary)
    run("push", "-q", "-u", "origin", "main", cwd=primary)

    root = tmp_path / "sub-agents"
    root.mkdir()
    run("worktree", "add", "-q", "-b", "agent/un", str(root / "un"), cwd=primary)
    run("config", "user.email", "test@jarvis.local", cwd=root / "un")
    run("config", "user.name", "Test", cwd=root / "un")

    pool = WorktreePool(primary=primary, root=root, lease_root=tmp_path / "leases")
    runner = SelfDevelopmentRunner(
        pool=pool,
        runtime_root=tmp_path / "runtime",
        tests=PASSING_TESTS,
        python=sys.executable,
    )
    return runner, primary, remote, root


def snapshot(path: Path) -> tuple[str, str]:
    """De quoi prouver qu'une copie de travail n'a pas bougé."""
    return run("rev-parse", "HEAD", cwd=path).strip(), run("status", "--porcelain", cwd=path)


# ------------------------------------------------------------- chemin nominal


async def test_a_finished_job_hands_over_a_candidate_and_leaves_the_serving_copy_alone(workshop, monkeypatch):
    runner, primary, remote, _root = workshop
    before = snapshot(primary)
    monkeypatch.setattr(runner, "_agent_command", lambda *a: writer())

    job = await runner.run("Ajouter un fichier de démonstration")

    assert job.status == "succeeded" and job.step == "done"
    candidate = job.candidate
    assert candidate["branch"] == f"selfdev/{job.job_id}"
    assert candidate["files"] == ["ajout.txt"]
    assert candidate["base"] == "main" and candidate["base_revision"]
    assert candidate["revision"] != candidate["base_revision"]
    # La branche est réellement chez le distant, avec ce commit.
    pushed = run("rev-parse", candidate["branch"], cwd=remote).strip()
    assert pushed == candidate["revision"]
    # Et la copie qui sert n'a pas bougé : ni HEAD, ni un seul fichier.
    assert snapshot(primary) == before


async def test_the_lease_is_given_back_so_the_next_job_can_work(workshop, monkeypatch):
    runner, _primary, _remote, _root = workshop
    monkeypatch.setattr(runner, "_agent_command", lambda *a: writer())

    first = await runner.run("Premier chantier")
    assert runner.pool.leases() == []

    monkeypatch.setattr(runner, "_agent_command", lambda *a: writer("deux\n", "autre.txt"))
    second = await runner.run("Deuxième chantier")

    assert second.status == "succeeded"
    assert second.candidate["branch"] != first.candidate["branch"]


async def test_every_step_is_written_down_as_it_happens(workshop, monkeypatch):
    runner, _primary, _remote, _root = workshop
    monkeypatch.setattr(runner, "_agent_command", lambda *a: writer())

    job = await runner.run("Ajouter un fichier")

    # Relu depuis le disque : un chantier interrompu doit se raconter après coup.
    stored = runner.jobs.load(job.job_id)
    assert stored is not None and stored.status == "succeeded"
    assert stored.candidate == job.candidate
    from jarvis.runtime.journal import read_jsonl_tail

    steps = [
        event["data"]["step"]
        for event in read_jsonl_tail(runner.runtime_root / "trace.jsonl")
        if event["kind"] == "selfdev.step" and event["data"]["job_id"] == job.job_id
    ]
    assert steps == list(self_dev.STEPS)


# --------------------------------------------------------------------- ratés


async def test_red_tests_produce_no_candidate_and_nothing_is_pushed(workshop, monkeypatch):
    runner, primary, remote, _root = workshop
    before = snapshot(primary)
    runner.tests = FAILING_TESTS
    monkeypatch.setattr(runner, "_agent_command", lambda *a: writer())

    job = await runner.run("Casser quelque chose")

    assert job.status == "failed" and job.error_code == "selfdev_tests_failed"
    # Le chantier s'arrête à la validation : il a édité, il n'a rien validé.
    assert job.candidate is None and job.step == "edited"
    assert "2 failed" in job.error
    assert run("branch", "--list", cwd=remote).strip() == "* main"
    assert snapshot(primary) == before
    assert runner.pool.leases() == []


async def test_an_agent_that_changes_nothing_is_not_a_candidate(workshop, monkeypatch):
    runner, _primary, remote, _root = workshop
    monkeypatch.setattr(runner, "_agent_command", lambda *a: (sys.executable, ["-c", "pass"]))

    job = await runner.run("Ne rien faire")

    assert job.error_code == "selfdev_no_change"
    assert run("branch", "--list", cwd=remote).strip() == "* main"


async def test_a_failing_agent_leaves_the_serving_copy_and_the_lease_intact(workshop, monkeypatch):
    runner, primary, _remote, _root = workshop
    before = snapshot(primary)
    monkeypatch.setattr(runner, "_agent_command", lambda *a: (sys.executable, ["-c", "import sys; sys.exit(3)"]))

    job = await runner.run("Chantier condamné")

    assert job.error_code == "selfdev_agent_failed" and "3" in job.error
    assert snapshot(primary) == before
    assert runner.pool.leases() == []


async def test_an_absent_agent_is_named_not_swallowed(workshop, monkeypatch):
    runner, _primary, _remote, _root = workshop
    monkeypatch.setattr(runner, "_agent_command", lambda *a: ("agent-qui-n-existe-pas", []))

    job = await runner.run("Chantier sans agent")

    assert job.error_code == "selfdev_agent_missing"


async def test_a_rejected_push_fails_the_job_instead_of_forcing_it(workshop, monkeypatch):
    """Une branche déjà présente chez le distant, divergente : on échoue, on
    n'écrase pas. C'est exactement le cas où `--force` serait tentant."""

    runner, primary, remote, root = workshop
    monkeypatch.setattr(runner, "_agent_command", lambda *a: writer())
    job_id = "selfdev-collision"
    branch = f"selfdev/{job_id}"
    # Quelqu'un a déjà poussé cette branche, avec un autre contenu.
    run("branch", branch, "main", cwd=primary)
    (primary / "autre.txt").write_text("déjà là\n", encoding="utf-8")
    run("add", "-A", cwd=primary)
    run("commit", "-q", "-m", "travail d'un autre", cwd=primary)
    run("branch", "-f", branch, "HEAD", cwd=primary)
    run("push", "-q", "origin", branch, cwd=primary)
    theirs = run("rev-parse", branch, cwd=remote).strip()

    job = await runner.run("Chantier qui entre en collision", job_id=job_id)

    assert job.status == "failed"
    assert job.error_code in {"worktree_git_failed", "selfdev_failed"}
    # Le travail de l'autre est intact chez le distant.
    assert run("rev-parse", branch, cwd=remote).strip() == theirs
    assert runner.pool.leases() == []


async def test_without_a_free_worktree_the_job_fails_before_touching_anything(workshop):
    runner, primary, _remote, _root = workshop
    before = snapshot(primary)
    held = await runner.pool.lease_any(job_id="un-autre")

    job = await runner.run("Chantier sans place")

    assert job.error_code == "worktree_none_free"
    assert snapshot(primary) == before
    runner.pool.release(held)


async def test_an_empty_request_is_refused_before_a_worktree_is_even_borrowed(workshop):
    runner, _primary, _remote, _root = workshop
    job = await runner.run("   ")
    assert job.error_code == "selfdev_empty_request"
    assert runner.pool.leases() == []


async def test_the_serving_copy_can_never_be_the_place_where_a_job_runs(workshop):
    runner, primary, _remote, _root = workshop
    with pytest.raises(self_dev.SelfDevError) as error:
        await runner._exec(sys.executable, ["-c", "pass"], cwd=primary, timeout_s=5)
    assert error.value.code == "selfdev_primary_forbidden"


# ------------------------------------------------------------------ interdits


def test_no_destructive_git_shortcut_exists_anywhere_in_the_build_plane():
    """Ce que le code ne contient pas est ici aussi important que ce qu'il fait."""

    from jarvis.runtime import worktrees

    forbidden = ("--force", "-f", "--hard", "reset", "clean", "stash", "--theirs", "--ours", "rm")
    calls: list[str] = []
    for module in (self_dev, worktrees):
        for line in Path(module.__file__).read_text(encoding="utf-8").splitlines():
            if "git(" in line and not line.lstrip().startswith(("#", "async def", "def ")):
                calls.append(line)

    assert calls, "aucun appel git trouvé : le test ne prouverait rien"
    for line in calls:
        arguments = {value.strip("\"'") for value in line.split(",")}
        assert not arguments & set(forbidden), line.strip()


async def test_the_routing_policy_chooses_the_coding_model_not_a_hardcoded_name(workshop, monkeypatch):
    from jarvis.runtime import agent_routing, routing_hook

    runner, _primary, _remote, _root = workshop
    agent_routing.apply(
        runner.settings,
        {"enabled": True, "profiles": {"code": {"candidates": [{"agent": "claude", "model": "modele-choisi"}]}}},
    )
    monkeypatch.setattr(
        routing_hook,
        "offline_candidates",
        lambda root, policy: agent_routing.build_candidates(
            [
                {
                    "id": "claude",
                    "label": "Claude",
                    "model_provider": "anthropic",
                    "capabilities": ["code", "semantic"],
                    "available": True,
                    "error": "",
                }
            ],
            {"anthropic": [{"id": "modele-choisi", "label": "M", "roles": ("text",)}]},
        ),
    )
    seen: list[tuple[str, str]] = []

    def spy(agent_id: str, model: str, request: str):  # noqa: ANN202
        seen.append((agent_id, model))
        return writer()

    monkeypatch.setattr(runner, "_agent_command", spy)

    job = await runner.run("Chantier aiguillé")

    assert seen == [("claude", "modele-choisi")]
    assert job.routing["model"] == "modele-choisi"
    # La décision voyage jusque dans le commit, pour qu'un humain la retrouve.
    message = run("log", "-1", "--format=%B", f"selfdev/{job.job_id}", cwd=runner.pool.root / "un")
    assert "modele-choisi" in message


async def test_without_a_policy_the_configured_cli_keeps_working_as_before(workshop, monkeypatch):
    runner, _primary, _remote, _root = workshop
    seen: list[tuple[str, str]] = []

    def spy(agent_id: str, model: str, request: str):  # noqa: ANN202
        seen.append((agent_id, model))
        return writer()

    monkeypatch.setattr(runner, "_agent_command", spy)

    job = await runner.run("Chantier sans politique")

    assert seen == [("claude", "")]
    assert job.routing["reason"] == "compatibility"
    assert job.status == "succeeded"


def test_the_job_store_survives_an_unreadable_file(workshop):
    runner, _primary, _remote, _root = workshop
    runner.jobs.root.mkdir(parents=True, exist_ok=True)
    (runner.jobs.root / "cassé.json").write_text("{ pas du json", encoding="utf-8")
    assert runner.jobs.all() == []
    assert runner.jobs.load("inconnu") is None


def test_the_agent_command_never_hardcodes_a_model(workshop):
    runner, _primary, _remote, _root = workshop
    executable, args = runner._agent_command("claude", "", "fais un truc")
    assert "--model" not in args
    _executable, with_model = runner._agent_command("claude", "un-modele", "fais un truc")
    assert with_model[with_model.index("--model") + 1] == "un-modele"
    assert json.dumps(args)  # sérialisable : c'est ce qui part au journal
