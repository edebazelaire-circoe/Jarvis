"""Demander un chantier, suivre où il en est, décider de déployer.

La question à laquelle chaque test répond : qu'est-ce qui peut arriver sans que
l'utilisateur l'ait ouvert ? Réponse attendue partout : rien.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from jarvis.runtime import self_dev
from jarvis.runtime.self_dev import SelfDevError
from jarvis.runtime.self_dev_service import SelfDevelopmentService

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


def run(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_WORKTREE_ROOT", raising=False)
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
    run("worktree", "add", "-q", "-b", "agent/un", str(root / "un"), cwd=primary)
    for key, value in (("user.email", "t@j.local"), ("user.name", "T")):
        run("config", key, value, cwd=root / "un")

    async def green(_worktree) -> tuple[int, str]:
        return 0, ""

    settings: dict = {}
    made = SelfDevelopmentService(
        project_root=primary,
        runtime_root=tmp_path / "runtime",
        settings=lambda: settings,
        gate=green,
    )
    return made, settings, primary


def allow(settings: dict, **values) -> None:
    self_dev.apply_gate(settings, {"enabled": True, **values})


def patch_runner(service, monkeypatch, *, name: str = "ajout.txt") -> None:
    """Remplacer l'agent de code par un script qui écrit un fichier."""
    real = service._runner

    def build():  # noqa: ANN202
        runner = real()
        runner.tests = ("-c", "raise SystemExit(0)")
        runner.python = sys.executable
        monkeypatch.setattr(
            runner,
            "_agent_command",
            lambda *a: (sys.executable, ["-c", f"open({name!r},'w',encoding='utf-8').write('fait\\n')"]),
        )
        return runner

    monkeypatch.setattr(service, "_runner", build)


async def settle(service) -> None:
    await asyncio.gather(*list(service._tasks.values()), return_exceptions=True)


# ------------------------------------------------------------- autorisation


async def test_nothing_can_be_built_while_the_capability_is_closed(service):
    made, _settings, primary = service
    head = run("rev-parse", "HEAD", cwd=primary).strip()

    with pytest.raises(SelfDevError) as error:
        made.start("Fais quelque chose")

    assert error.value.code == "selfdev_not_allowed"
    assert run("rev-parse", "HEAD", cwd=primary).strip() == head
    assert made.jobs.all() == []


def test_the_capability_is_closed_on_a_fresh_install(service):
    made, _settings, _primary = service
    assert made.gate() == {"enabled": False, "auto_deploy": False}


def test_automatic_deployment_cannot_be_opened_on_its_own(service):
    _made, settings, _primary = service
    with pytest.raises(SelfDevError) as error:
        self_dev.apply_gate(settings, {"auto_deploy": True})
    assert error.value.code == "selfdev_deploy_without_build"
    assert settings.get(self_dev.SETTING_KEY) is None


def test_an_unknown_setting_is_refused_rather_than_ignored(service):
    _made, settings, _primary = service
    with pytest.raises(SelfDevError) as error:
        self_dev.apply_gate(settings, {"enabled": True, "deploy_everything": True})
    assert error.value.code == "selfdev_unknown_field"


# ------------------------------------------------------------------ chantier


async def test_a_request_returns_at_once_and_the_work_continues_behind(service, monkeypatch):
    made, settings, primary = service
    allow(settings)
    patch_runner(made, monkeypatch)

    job = made.start("Ajouter un fichier")

    # Rendu immédiatement, avant même que le chantier ait commencé.
    assert job.status == "pending" and job.job_id in made._tasks
    await settle(made)

    done = made.jobs.load(job.job_id)
    assert done.status == "succeeded" and done.candidate["branch"] == f"selfdev/{job.job_id}"
    # Sans déploiement automatique, le service n'a pas bougé.
    assert not (primary / "ajout.txt").exists()


async def test_a_ready_candidate_waits_for_an_explicit_decision(service, monkeypatch):
    made, settings, primary = service
    allow(settings)
    patch_runner(made, monkeypatch)
    job = made.start("Ajouter un fichier")
    await settle(made)

    from jarvis.runtime.journal import read_jsonl_tail

    events = [e for e in read_jsonl_tail(made.runtime_root / "trace.jsonl") if e["kind"] == "selfdev.candidate"]
    assert events and events[-1]["data"]["job_id"] == job.job_id
    assert made._coordinator().marker.read() is None

    deployment = await made.deploy(job.job_id)

    assert deployment["state"] == "pending"
    assert (primary / "ajout.txt").is_file()


async def test_with_automatic_deployment_the_candidate_goes_all_the_way(service, monkeypatch):
    made, settings, primary = service
    allow(settings, auto_deploy=True)
    patch_runner(made, monkeypatch)

    made.start("Ajouter un fichier")
    await settle(made)

    assert (primary / "ajout.txt").is_file()
    assert made._coordinator().marker.read().state == "pending"
    # Le rechargement est demandé : le superviseur le verra.
    assert (made.runtime_root / "reload.request").is_file()


async def test_deploying_an_unknown_or_empty_job_is_refused_clearly(service, monkeypatch):
    made, settings, _primary = service
    allow(settings)

    with pytest.raises(SelfDevError) as unknown:
        await made.deploy("selfdev-fantome")
    assert unknown.value.code == "selfdev_unknown_job"

    patch_runner(made, monkeypatch)
    made._runner().tests = ("-c", "raise SystemExit(1)")
    job = self_dev.Job(job_id="selfdev-vide", request="rien")
    made.jobs.save(job)
    with pytest.raises(SelfDevError) as empty:
        await made.deploy(job.job_id)
    assert empty.value.code == "selfdev_no_candidate"


# --------------------------------------------------------------------- état


async def test_the_state_tells_where_everything_stands(service, monkeypatch):
    made, settings, _primary = service
    allow(settings)
    patch_runner(made, monkeypatch)
    job = made.start("Ajouter un fichier")
    await settle(made)

    state = await made.state()

    assert state["enabled"] is True and state["auto_deploy"] is False
    assert [item["path"].endswith("un") for item in state["worktrees"]] == [True]
    assert state["leases"] == []  # rendu à la fin du chantier
    assert [entry["job_id"] for entry in state["jobs"]] == [job.job_id]
    assert state["running"] == []
    assert Path(state["root"]).name == "sub-agents"


async def test_a_missing_pool_is_reported_without_breaking_the_screen(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_WORKTREE_ROOT", raising=False)
    lonely = tmp_path / "sans-depot"
    lonely.mkdir()
    made = SelfDevelopmentService(project_root=lonely, runtime_root=tmp_path / "runtime", settings=dict)

    state = await made.state()

    assert state["ok"] is True and state["worktrees"] == []
    assert state["root"] == ""


# ------------------------------------------------------------------- routes


async def test_the_control_center_exposes_the_capability_and_its_gate(tmp_path, monkeypatch):
    from jarvis.runtime.control_center import ControlCenter

    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path / "projet")

    payload = json.loads((await control.get_settings(None)).text)
    assert payload["self_development"] == {"enabled": False, "auto_deploy": False}

    class Post:
        def __init__(self, body: dict) -> None:
            self._body = body

        async def json(self) -> dict:
            return self._body

    refused = json.loads((await control.self_dev_start(Post({"request": "fais un truc"}))).text)
    assert refused["ok"] is False and refused["code"] == "selfdev_not_allowed"

    saved = json.loads((await control.save_settings(Post({"self_development": {"enabled": True}}))).text)
    assert saved["self_development"]["enabled"] is True

    state = json.loads((await control.self_dev_state(None)).text)
    assert state["enabled"] is True and state["ok"] is True
