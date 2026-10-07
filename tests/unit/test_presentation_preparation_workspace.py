"""Dossier de travail des sous-agents de préparation : vide, dédié, jamais la racine du dépôt.

S6 rework 2 (sécurité), décidé par agent 0. La racine du dépôt porte `.env`,
`runtime/core.token` et `runtime/trace.jsonl` ; depuis `761fa7d`, une
préparation a `WebFetch` permis. Un sous-agent lancé là pouvait donc lire un
secret et l'emporter dans une URL. `--restricted` confine la lecture au
dossier courant : le dossier courant doit donc être un dossier **vide**, sous
la racine de données de l'instance, créé au début du travail et retiré à sa
fin. Contrat : `docs/presentation-speculative-preparation.md` › *Secrets and
working directory*.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.domain.interaction_mode import InteractionMode
from jarvis.domain.presentation_speculative import SpeculativeCapability
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.presentation_preparation import (
    PreparationError,
    PreparationWorkspace,
    PresentationPreparationRunner,
)
from tests.unit.test_presentation_integration import (
    RecordingJournal,
    ScriptedAgent,
    _request,
    composition,
)

ROOT = Path(__file__).resolve().parents[2]


def _spawns(monkeypatch) -> list[dict]:  # noqa: ANN001
    """Capturer le dossier courant **et son contenu** au lancement du processus."""

    spawned: list[dict] = []

    async def fake_exec(*argv, **kwargs):  # noqa: ANN002, ANN003
        cwd = Path(kwargs["cwd"])
        spawned.append({"argv": list(argv), "cwd": cwd,
                        "listing": sorted(p.name for p in cwd.iterdir()) if cwd.is_dir() else None})
        raise RuntimeError("processus capturé : rien n'est lancé")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr("jarvis.runtime.cli_catalog.resolve_command", lambda command: "C:/fake/claude.exe")
    return spawned


def _compose_claude(tmp_path: Path):
    """Le **vrai** `_presentation_composition`, avec le CLI Claude choisi."""

    from jarvis.app import _presentation_composition

    settings = SimpleNamespace(
        runtime_root=tmp_path / "runtime", data_root=tmp_path / "data",
        core_host="127.0.0.1", core_port=1, token_file=tmp_path / "token",
    )
    stack = SimpleNamespace(credential_provider="none", id="test", label="Test", input_sample_rate=24000)
    return _presentation_composition(
        settings=settings, overrides={"agent_cli": "claude"}, journal=RecordingJournal(),
        stack=stack, api_key="", wake_key="", manual_key="f9", audio_input_device=None,
        behaving_mode=lambda: InteractionMode.PRESENTATION,
    )


async def test_preparation_runs_in_dedicated_empty_cwd_not_repo_root(tmp_path, monkeypatch):
    """Le processus réel reçoit un dossier vide sous la racine de données, jamais le dépôt."""

    spawned = _spawns(monkeypatch)
    built = _compose_claude(tmp_path)
    assert built.preparation_root == tmp_path / "data" / "presentation" / "prep"
    assert built.cwd == ROOT, "le dossier des autres usages ne bouge pas"

    runner = built.preparation_runner(
        record_source=lambda kind, locator, title: None, claims_for=None,
    )
    with pytest.raises(PreparationError):
        await runner.prepare(_request(SpeculativeCapability.FACT_VERIFICATION))

    assert len(spawned) == 1
    cwd = spawned[0]["cwd"]
    assert cwd.parent == built.preparation_root, cwd
    assert spawned[0]["listing"] == [], "vide au lancement : rien à lire"
    assert ROOT not in (cwd, *cwd.parents), "jamais dans le dépôt"
    assert not (cwd / ".env").exists()
    assert any("WebFetch" in part for part in spawned[0]["argv"]), "le scénario dangereux est bien celui-ci"
    assert not cwd.exists(), "retiré à la fin du travail, même raté"


async def test_preparation_cwd_removed_after_job_and_orphans_swept(tmp_path):
    root = tmp_path / "data" / "presentation" / "prep"
    seen: list[Path] = []

    def factory(tools, cwd):  # noqa: ANN001
        seen.append(Path(cwd))
        (Path(cwd) / "scratch.txt").write_text("trace du sous-agent", encoding="utf-8")
        return ScriptedAgent('{"findings": []}')

    runner = PresentationPreparationRunner(
        agent_factory=factory, record_source=lambda kind, locator, title: None,
        workspace=PreparationWorkspace(root),
    )
    await runner.prepare(_request(SpeculativeCapability.RESEARCH_SEARCH))
    assert seen and not seen[0].exists(), "retiré après un travail réussi"

    # Un travail annulé (séance retirée) retire aussi son dossier.
    hold = asyncio.Event()

    class HeldAgent(ScriptedAgent):
        async def ask(self, text, **kwargs):  # noqa: ANN001, ANN003
            await hold.wait()
            return await super().ask(text, **kwargs)

    held: list[Path] = []

    def held_factory(tools, cwd):  # noqa: ANN001
        held.append(Path(cwd))
        return HeldAgent('{"findings": []}')

    held_runner = PresentationPreparationRunner(
        agent_factory=held_factory, record_source=lambda kind, locator, title: None,
        workspace=PreparationWorkspace(root),
    )
    task = asyncio.create_task(held_runner.prepare(_request(SpeculativeCapability.RESEARCH_SEARCH)))
    for _ in range(20):
        await asyncio.sleep(0)
        if held and held[0].exists():
            break
    assert held and held[0].exists()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not held[0].exists(), "retiré quand la séance annule le travail"

    # Un arrêt brutal laisse un orphelin : balayé à l'entrée en PRESENTATION…
    orphan = root / "prep-orphan"
    orphan.mkdir(parents=True)
    (orphan / "leak.txt").write_text("reste d'une vie précédente", encoding="utf-8")
    journal = RecordingJournal()
    built, *_ = composition(tmp_path, journal)
    import dataclasses

    built = dataclasses.replace(built, preparation_root=root)
    stack = built.build("pres-sweep-1")
    await stack.start()
    try:
        assert not orphan.exists(), "balayé à l'entrée"
    finally:
        await stack.stop("test")

    # … et au démarrage de Voice, même sans outils de scène.
    orphan.mkdir(parents=True)
    reclaim = dataclasses.replace(built, scene_tools_factory=None).reclaimer()
    assert reclaim is not None
    await reclaim()
    assert not orphan.exists(), "balayé au démarrage de Voice"
    assert root.exists() and list(root.iterdir()) == []


def test_workspace_never_removes_outside_its_root(tmp_path):
    root = tmp_path / "prep"
    outside = tmp_path / "precious"
    outside.mkdir()
    workspace = PreparationWorkspace(root)
    assert workspace.release(outside) is False
    assert outside.exists()
    assert workspace.release(root) is False, "la racine elle-même n'est pas un dossier de travail"


def _link(target: Path, at: Path, kind: str) -> None:
    """Poser une jonction (Windows, sans privilège) ou un lien symbolique, ou sauter."""

    if kind == "junction":
        try:
            import _winapi
        except ImportError:
            pytest.skip("jonctions : Windows seulement")
        _winapi.CreateJunction(str(target), str(at))
        return
    try:
        at.symlink_to(target, target_is_directory=True)
    except OSError as exc:  # privilège de création de lien absent
        pytest.skip(f"lien symbolique impossible ici : {exc}")


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_sweep_refuses_a_linked_root_and_says_so(tmp_path, kind):
    """Polish p8 : une racine liée ailleurs n'est pas balayée.

    Sans ce refus, chaque dossier de la cible passe pour un « enfant direct » :
    `release` compare des chemins résolus et les efface."""

    precious = tmp_path / "precious"
    (precious / "projet").mkdir(parents=True)
    (precious / "projet" / "notes.txt").write_text("à garder", encoding="utf-8")
    (precious / "fichier.txt").write_text("à garder aussi", encoding="utf-8")
    root = tmp_path / "data" / "presentation" / "prep"
    root.parent.mkdir(parents=True)
    _link(precious, root, kind)
    journal = RecordingJournal()

    assert PreparationWorkspace(root, journal=journal).sweep() == 0
    assert (precious / "projet" / "notes.txt").is_file()
    assert (precious / "fichier.txt").is_file()
    refused = [entry for entry in journal.entries if entry["data"].get("code") == "presentation_preparation_root_linked"]
    assert len(refused) == 1, journal.entries
    assert refused[0]["level"] == "error" and refused[0]["data"]["link"] == kind


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_sweep_traces_a_linked_child_it_leaves_in_place(tmp_path, kind):
    """Polish p9 : l'enfant lié était épargné en silence ; il l'est maintenant à voix haute."""

    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "notes.txt").write_text("à garder", encoding="utf-8")
    root = tmp_path / "prep"
    (root / "prep-orphan").mkdir(parents=True)
    _link(precious, root / "lien-pose", kind)
    journal = RecordingJournal()

    assert PreparationWorkspace(root, journal=journal).sweep() == 1, "l'orphelin réel est retiré"
    assert (precious / "notes.txt").is_file()
    assert (root / "lien-pose").exists(), "le lien est laissé en place"
    skipped = [entry for entry in journal.entries
               if entry["data"].get("code") == "presentation_preparation_link_skipped"]
    assert len(skipped) == 1, journal.entries
    assert skipped[0]["data"]["name"] == "lien-pose" and skipped[0]["data"]["link"] == kind


@pytest.mark.parametrize("profile", ["speculative_analysis", "conversation", "job_result"])
async def test_other_profiles_cwd_unchanged(tmp_path, monkeypatch, profile):
    """Seul `presentation_preparation` change de dossier ; les autres partent d'où on les lance."""

    spawned = _spawns(monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    agent = ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=repo, command="claude",
                             execution_profile=profile)
    with pytest.raises(RuntimeError):
        await agent.start(resume=False)
    assert spawned[-1]["cwd"] == repo

    built = _compose_claude(tmp_path)
    assert built.cwd == ROOT
