"""Où JARVIS a le droit d'écrire son propre code, et où il ne l'a jamais.

Tout se passe sur de vrais dépôts git temporaires : un pool qui se trompe de
dossier ferait des dégâts réels, et seul git peut prouver qu'un worktree
appartient bien au dépôt. Aucun test ne touche la copie de travail qui sert.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime import worktrees
from jarvis.runtime.worktrees import Worktree, WorktreeError, WorktreePool

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


def run(*args: str, cwd: Path) -> str:
    """git, en direct : la mise en place des fixtures n'est pas le code testé."""
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run("init", "-q", "-b", "main", cwd=path)
    run("config", "user.email", "test@jarvis.local", cwd=path)
    run("config", "user.name", "Test", cwd=path)
    (path / "fichier.txt").write_text("un\n", encoding="utf-8")
    run("add", "-A", cwd=path)
    run("commit", "-q", "-m", "depart", cwd=path)
    return path


def add_worktree(primary: Path, root: Path, name: str) -> Path:
    target = root / name
    run("worktree", "add", "-q", "-b", f"agent/{name}", str(target), cwd=primary)
    return target


@pytest.fixture
def pool(tmp_path) -> WorktreePool:
    primary = make_repo(tmp_path / "jarvis")
    root = tmp_path / "sub-agents"
    root.mkdir()
    add_worktree(primary, root, "un")
    return WorktreePool(primary=primary, root=root, lease_root=tmp_path / "leases")


# ------------------------------------------------------------- découverte


async def test_the_pool_finds_the_sibling_worktree_and_never_the_serving_copy(pool):
    found = await pool.discover()

    assert [item.path.name for item in found] == ["un"]
    assert all(item.path != pool.primary for item in found)
    assert found[0].branch == "agent/un" and found[0].usable


async def test_a_second_and_a_third_worktree_need_no_change_at_all(pool):
    add_worktree(pool.primary, pool.root, "deux")
    add_worktree(pool.primary, pool.root, "trois")

    assert [item.path.name for item in await pool.available()] == ["deux", "trois", "un"]


async def test_a_foreign_repository_hiding_under_the_pool_name_is_refused(pool, tmp_path):
    """Un dossier ne prouve rien : seul le dépôt commun de git fait foi."""

    stranger = make_repo(pool.root / "etranger")
    assert stranger.is_dir()

    # Il n'est pas un worktree de ce dépôt : il n'apparaît simplement jamais.
    assert [item.path.name for item in await pool.discover()] == ["un"]

    outsider = Worktree(path=stranger, branch="main", head="", dirty=False)
    lease = pool.acquire(outsider, job_id="j1")  # l'objet n'a pas traversé discover()
    pool.release(lease)
    # ...mais la découverte, elle, ne le proposera jamais.
    assert stranger not in {item.path for item in await pool.discover()}


async def test_a_worktree_created_outside_the_pool_root_is_not_in_the_pool(pool, tmp_path):
    """Les worktrees de l'outillage d'agent vivent dans `.claude/` : ils ne sont
    pas le plan de construction de JARVIS et ne doivent pas être empruntés."""

    elsewhere = tmp_path / "ailleurs"
    run("worktree", "add", "-q", "-b", "agent/ailleurs", str(elsewhere), cwd=pool.primary)

    assert [item.path.name for item in await pool.discover()] == ["un"]


async def test_a_dirty_worktree_is_seen_blocked_rather_than_cleaned(pool):
    """On ne nettoie pas le travail d'un autre : on refuse de s'en servir."""

    (pool.root / "un" / "fichier.txt").write_text("modifié à la main\n", encoding="utf-8")

    [found] = await pool.discover()
    assert found.dirty and not found.usable and found.blocked == "worktree_dirty"
    assert await pool.available() == []
    with pytest.raises(WorktreeError) as error:
        pool.acquire(found, job_id="j1")
    assert error.value.code == "worktree_dirty"
    # Et le fichier de l'autre est intact.
    assert (pool.root / "un" / "fichier.txt").read_text(encoding="utf-8") == "modifié à la main\n"


async def test_a_vanished_worktree_folder_is_reported_not_ignored(pool):
    shutil.rmtree(pool.root / "un")
    [found] = await pool.discover()
    assert found.blocked == "worktree_missing"


def test_without_a_sibling_folder_the_pool_says_what_to_create(tmp_path, monkeypatch):
    monkeypatch.delenv(worktrees.POOL_ROOT_ENV, raising=False)
    primary = make_repo(tmp_path / "jarvis")
    empty = WorktreePool(primary=primary, lease_root=tmp_path / "leases")

    assert empty.root is None


def test_the_pool_root_is_the_sibling_folder_that_actually_exists(tmp_path, monkeypatch):
    monkeypatch.delenv(worktrees.POOL_ROOT_ENV, raising=False)
    primary = make_repo(tmp_path / "jarvis")
    (tmp_path / "sous-agents").mkdir()

    assert worktrees.default_pool_root(primary) == (tmp_path / "sous-agents").resolve()

    # Les deux orthographes existent dans la nature ; la machine tranche.
    (tmp_path / "sub-agents").mkdir()
    assert worktrees.default_pool_root(primary) == (tmp_path / "sub-agents").resolve()

    monkeypatch.setenv(worktrees.POOL_ROOT_ENV, str(tmp_path / "ailleurs"))
    assert worktrees.default_pool_root(primary) == (tmp_path / "ailleurs").resolve()


# -------------------------------------------------------------------- baux


async def test_two_jobs_cannot_hold_the_same_worktree(pool):
    [free] = await pool.discover()
    first = pool.acquire(free, job_id="chantier-1")

    with pytest.raises(WorktreeError) as error:
        pool.acquire(free, job_id="chantier-2")
    assert error.value.code == "worktree_leased"
    assert "chantier-1" in str(error.value)

    pool.release(first)
    second = pool.acquire(free, job_id="chantier-2")
    assert second.job_id == "chantier-2"


async def test_a_leased_worktree_leaves_the_pool_until_it_is_given_back(pool):
    add_worktree(pool.primary, pool.root, "deux")
    lease = await pool.lease_any(job_id="chantier-1")

    remaining = [item.path.name for item in await pool.available()]
    assert lease.path.name not in remaining and len(remaining) == 1

    pool.release(lease)
    assert len(await pool.available()) == 2


async def test_a_lease_left_by_a_dead_job_is_taken_over_not_worshipped(pool, monkeypatch):
    [free] = await pool.discover()
    abandoned = pool.acquire(free, job_id="mort")

    # Le processus propriétaire n'existe plus.
    monkeypatch.setattr(worktrees, "_alive", lambda pid: False)

    taken = pool.acquire(free, job_id="vivant")
    assert taken.job_id == "vivant"
    assert json.loads(abandoned.lease_path.read_text(encoding="utf-8"))["job_id"] == "vivant"


async def test_a_lease_older_than_the_limit_is_taken_over_too(pool, monkeypatch):
    [free] = await pool.discover()
    pool.acquire(free, job_id="oublie")
    monkeypatch.setattr(worktrees, "_age_s", lambda stamp: worktrees.STALE_LEASE_S + 1)

    assert pool.acquire(free, job_id="neuf").job_id == "neuf"


async def test_a_job_never_takes_back_a_lease_that_was_reassigned(pool, monkeypatch):
    """Rendre son bail après s'être fait déposséder libérerait le worktree d'un
    chantier qui travaille."""

    [free] = await pool.discover()
    old = pool.acquire(free, job_id="ancien")
    monkeypatch.setattr(worktrees, "_alive", lambda pid: False)
    new = pool.acquire(free, job_id="nouveau")

    pool.release(old)

    assert new.lease_path.is_file()
    assert json.loads(new.lease_path.read_text(encoding="utf-8"))["job_id"] == "nouveau"


async def test_releasing_twice_is_not_an_error(pool):
    [free] = await pool.discover()
    lease = pool.acquire(free, job_id="j")
    pool.release(lease)
    pool.release(lease)
    assert pool.leases() == []


async def test_asking_for_a_worktree_when_none_is_free_says_what_to_do(pool):
    lease = await pool.lease_any(job_id="j1")

    with pytest.raises(WorktreeError) as error:
        await pool.lease_any(job_id="j2")

    assert error.value.code == "worktree_none_free"
    assert "un" in str(error.value)
    pool.release(lease)


async def test_the_serving_copy_is_refused_even_when_asked_by_name(pool):
    itself = Worktree(path=pool.primary, branch="main", head="", dirty=False)
    with pytest.raises(WorktreeError) as error:
        pool.acquire(itself, job_id="j")
    assert error.value.code == "worktree_is_primary"


def test_an_unreadable_lease_file_does_not_block_the_pool(pool, tmp_path):
    pool.lease_root.mkdir(parents=True, exist_ok=True)
    (pool.lease_root / "cassé.json").write_text("{ pas du json", encoding="utf-8")
    assert pool.leases() == []


def test_a_live_process_is_recognised_as_alive():
    assert worktrees._alive(os.getpid()) is True
    assert worktrees._alive(0) is False
