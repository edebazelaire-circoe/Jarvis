"""Installation, mise à jour, réparation et désinstallation (presentation-edition-v1 Slice 07, `docs/product-install.md`).

Tout se passe dans `tmp_path` : paquet factice mais conforme (manifeste, empreintes), cible, maison, menu Démarrer et
Bureau simulés, ruche simulée (`FileRegistry`). Jamais le vrai registre, le vrai Bureau ni `%LOCALAPPDATA%`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from jarvis import private_runtime as PR
from jarvis import product_setup as S
from jarvis.installation import PRODUCT_MARKER, marker_payload


def make_package(root: Path, version: str = "0.2.0", extra: bytes = b"", python_exe: bytes | None = None) -> Path:
    (root / "app" / "jarvis").mkdir(parents=True)
    (root / "app" / "jarvis" / "__init__.py").write_text(f"VERSION = {version!r}\n", encoding="utf-8")
    (root / "app" / PRODUCT_MARKER).write_text(json.dumps(marker_payload()), encoding="utf-8")
    for name, exe in (("python", "python.exe"), ("node", "node.exe")):
        (root / "runtime" / name).mkdir(parents=True)
        (root / "runtime" / name / exe).write_bytes(b"MZ" + name.encode() + extra)
    if python_exe is not None:  # un vrai exécutable à la place de Python (essais de l'amorce)
        (root / "runtime" / "python" / "python.exe").write_bytes(python_exe)
    (root / "runtime" / "python" / "pythonw.exe").write_bytes(b"MZw")
    (root / "licenses").mkdir()
    (root / "licenses" / "LICENSE.txt").write_text("MIT\n", encoding="utf-8")
    (root / "third-party-manifest.json").write_text("{}\n", encoding="utf-8")
    runtimes = {}
    for name, exe in (("python", "python.exe"), ("node", "node.exe")):
        tree, count = PR.tree_sha256(root / "runtime" / name)
        runtimes[name] = {"version": "1", "root": f"runtime/{name}", "executable": f"runtime/{name}/{exe}",
                          "tree_sha256": tree, "files": count}
    manifest = {"schema": PR.RUNTIME_MANIFEST_SCHEMA, "schema_version": PR.RUNTIME_MANIFEST_VERSION,
                "product": {"name": "Jarvis", "edition": "presentation", "version": version, "source_revision": "x"},
                "app": {"root": "app", "tree_sha256": PR.tree_sha256(root / "app")[0]},
                "licenses": {"root": "licenses", "tree_sha256": PR.tree_sha256(root / "licenses")[0]},
                "third_party_manifest_sha256": PR.file_sha256(root / "third-party-manifest.json"),
                "runtimes": runtimes, "excluded": []}
    manifest["package_sha256"] = PR.package_digest(manifest)
    (root / PR.RUNTIME_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return root


class RecordingShortcuts:
    def __init__(self) -> None:
        self.made: list[dict] = []

    def create(self, path, **kwargs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("lnk", encoding="utf-8")
        self.made.append({"path": path, **kwargs})


def targets(tmp_path: Path) -> S.Targets:
    home = tmp_path / "Local" / "CIRCOE" / "Jarvis"
    return S.Targets(target=(tmp_path / "Local" / "Programs" / "CIRCOE" / "Jarvis").resolve(),
                     start_menu=tmp_path / "StartMenu", desktop=tmp_path / "Desktop",
                     registry=S.FileRegistry(tmp_path / "hive.json"), home=home)


def quiet() -> S.Progress:
    return S.Progress(None, echo=False)


def seed_home(t: S.Targets) -> Path:
    precious = t.home / "data" / "presentations" / "deck.json"
    precious.parent.mkdir(parents=True)
    precious.write_text('{"title": "Atelier"}', encoding="utf-8")
    return precious


def test_a_fresh_install_lays_down_the_program_shortcuts_and_the_uninstall_key(tmp_path):
    source = make_package(tmp_path / "src")
    t = targets(tmp_path)
    shortcuts = RecordingShortcuts()
    result = S.install(source, t, move=False, progress=quiet(), shortcuts=shortcuts)
    assert result["ok"] and result["mode"] == "install" and result["data_kept"]
    assert PR.verify_package(PR.PackageLayout(t.target))[1] == []
    assert [row["path"].name for row in shortcuts.made] == ["JARVIS.lnk", "JARVIS.lnk"]
    assert shortcuts.made[0]["target"].name == "pythonw.exe" and shortcuts.made[0]["arguments"] == "-B -m jarvis launch"
    values = t.registry.read()
    assert values["DisplayVersion"] == "0.2.0" and values["Publisher"] == "CIRCOE"
    assert values["InstallLocation"] == str(t.target)
    assert values["UninstallString"].endswith('pythonw.exe" -B -m jarvis.product_setup uninstall')
    assert not t.home.exists()  # l'installeur ne crée ni ne touche la maison


def test_an_update_replaces_the_program_and_keeps_the_home_byte_for_byte(tmp_path):
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "v1", "0.2.0"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    precious = seed_home(t)
    before = precious.read_bytes()
    result = S.install(make_package(tmp_path / "v2", "0.3.0"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    assert result["mode"] == "update" and result["previous_leftover"] is None
    assert "0.3.0" in (t.target / "app" / "jarvis" / "__init__.py").read_text(encoding="utf-8")
    assert precious.read_bytes() == before
    assert not list(t.target.parent.glob("Jarvis.previous-*"))
    assert t.registry.read()["DisplayVersion"] == "0.3.0"


def test_reinstalling_the_same_version_repairs_a_damaged_program(tmp_path):
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "v1"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    (t.target / "runtime" / "node" / "node.exe").unlink()
    assert PR.verify_package(PR.PackageLayout(t.target))[1]
    result = S.install(make_package(tmp_path / "again"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    assert result["mode"] == "repair" and PR.verify_package(PR.PackageLayout(t.target))[1] == []


def test_a_damaged_source_changes_nothing(tmp_path):
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "v1"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    bad = make_package(tmp_path / "bad", "0.3.0")
    (bad / "runtime" / "node" / "node.exe").write_bytes(b"tampered")
    with pytest.raises(S.SetupError) as refused:
        S.install(bad, t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    assert refused.value.code == "package_damaged"
    assert t.registry.read()["DisplayVersion"] == "0.2.0" and PR.verify_package(PR.PackageLayout(t.target))[1] == []


def test_a_failure_after_the_swap_puts_the_previous_program_back(tmp_path):
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "v1"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    with pytest.raises(S.SetupError) as refused:
        S.install(make_package(tmp_path / "v2", "0.3.0"), t, move=False, progress=quiet(),
                  shortcuts=RecordingShortcuts(), verify_copy=lambda source, target: ["app/jarvis/x.py: taille différente"])
    assert refused.value.code == "installed_copy_damaged"
    assert refused.value.extra["rolled_back"] is True and "L'ancienne version de JARVIS est remise en place" in str(refused.value)
    assert "0.2.0" in (t.target / "app" / "jarvis" / "__init__.py").read_text(encoding="utf-8")
    assert sorted(p.name for p in t.target.parent.iterdir()) == ["Jarvis"]  # ni .previous-*, ni .failed-*, ni état


def test_refusals_running_foreign_folder_overlap_and_unsafe_names(tmp_path):
    t = targets(tmp_path)
    (t.home / "runtime").mkdir(parents=True)
    (t.home / "runtime" / "launcher.json").write_text(json.dumps({"pid": 77}), encoding="utf-8")
    with pytest.raises(S.SetupError) as running:
        S.install(make_package(tmp_path / "src"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts(),
                  alive=lambda pid: pid == 77)
    assert running.value.code == "jarvis_running"
    foreign = targets(tmp_path / "f")
    foreign.target.mkdir(parents=True)
    (foreign.target / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(S.SetupError) as occupied:
        S.install(make_package(tmp_path / "src2"), foreign, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    assert occupied.value.code == "target_not_empty" and (foreign.target / "notes.txt").exists()
    inside = S.Targets(target=(t.home / "app").resolve(), start_menu=None, desktop=None,
                       registry=S.FileRegistry(tmp_path / "h2.json"), home=t.home)
    with pytest.raises(S.SetupError) as overlap:
        S.check_target(inside)
    assert overlap.value.code == "target_overlaps_home"
    unsafe = S.Targets(target=tmp_path / "a&b", start_menu=None, desktop=None, registry=S.FileRegistry(tmp_path / "h3.json"),
                       home=None)
    with pytest.raises(S.SetupError) as bad_name:
        S.check_target(unsafe)
    assert bad_name.value.code == "target_unsafe"


def test_uninstall_removes_program_shortcuts_and_key_and_keeps_the_home(tmp_path):
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "src"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    precious = seed_home(t)
    result = S.uninstall(t, progress=quiet())
    assert result["ok"] and not result["deferred_removal"] and result["data_kept"]
    assert not t.target.exists() and t.registry.read() is None
    assert not (t.start_menu / "JARVIS.lnk").exists() and not (t.desktop / "JARVIS.lnk").exists()
    assert precious.read_text(encoding="utf-8") == '{"title": "Atelier"}'


def hold_file(path: Path, seconds: float) -> subprocess.Popen:
    """Un AUTRE processus qui garde `path` ouvert `seconds` secondes (comme `pythonw.exe` tient son image et ses DLL
    pendant que la boîte « JARVIS est désinstallé » reste ouverte : sonde P1 de la QA de la Slice 07)."""

    code = ("import sys,time; h=open(sys.argv[1],'rb'); print('held', flush=True); time.sleep(float(sys.argv[2])); "
            "h.close()")
    child = subprocess.Popen([sys.executable, "-c", code, str(path), str(seconds)], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "held"
    return child


def wait_until(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return predicate()


def test_uninstall_from_inside_the_program_defers_the_folder_removal_to_a_script_that_waits_for_the_process(tmp_path):
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "src"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    spawned = []
    result = S.uninstall(t, progress=quiet(), running_from=t.target / "runtime" / "python", script_dir=tmp_path / "tmp",
                         pid=4242, image="pythonw.exe", spawn=lambda argv, **kwargs: spawned.append((argv, kwargs)))
    assert result["deferred_removal"] and t.target.exists()
    command, kwargs = spawned[0]
    script = Path(result["removal_script"])
    assert command == f'cmd.exe /d /s /c ""{script}""' and kwargs["cwd"] == str(tmp_path / "tmp")
    body = script.read_text(encoding="utf-8")
    # Attente de la FIN du processus, puis suppression avec reprises, puis seulement la clé et l'état.
    assert '/fi "PID eq 4242"' in body and '/i "pythonw.exe"' in body
    assert body.index(":wait") < body.index(":remove") < body.index("rmdir /s /q") < body.index(":removed")
    assert body.index(":removed") < body.index(t.registry.removal_command()) < body.index(":failed")
    # Les raccourcis partent tout de suite ; la clé et l'état d'opération restent jusqu'à la suppression effective.
    assert not (t.start_menu / "JARVIS.lnk").exists() and t.registry.read() is not None
    assert S.read_state(t.target)["operation"] == "uninstall"


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe")
def test_the_deferred_removal_waits_for_the_real_end_of_the_process_then_removes_key_and_state(tmp_path):
    """Sonde P1 de la QA : le processus qui désinstalle reste vivant plus de 3 s (boîte de fin ouverte) et tient un
    fichier du programme. Avant : dossier à moitié effacé, clé retirée, réinstallation refusée."""

    t = targets(tmp_path / "with space é")
    S.install(make_package(tmp_path / "src"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    # S10 (intermittent sous charge) : la boîte reste ouverte 8 s et l'attente se compte depuis sa prise, pas depuis la
    # fin de `uninstall`, qui peut durer plus d'une seconde sur une machine chargée.
    holder = hold_file(t.target / "runtime" / "python" / "pythonw.exe", 8)
    held_at = time.monotonic()
    try:
        result = S.uninstall(t, progress=quiet(), running_from=t.target / "runtime" / "python",
                             script_dir=tmp_path / "tmp", pid=holder.pid, image=Path(sys.executable).name)
        time.sleep(max(0.0, 3.5 - (time.monotonic() - held_at)))
        assert holder.poll() is None
        # Le processus vit encore : rien n'est effacé, rien n'est retiré.
        assert (t.target / PR.RUNTIME_MANIFEST).exists() and t.registry.read() is not None
    finally:
        holder.wait(timeout=30)
    assert wait_until(lambda: not t.target.exists() and t.registry.read() is None, 40)
    assert not S.state_path(t.target).exists() and not Path(result["removal_script"]).exists()
    assert "dossier supprime" in (tmp_path / "tmp" / S.UNINSTALL_LOG).read_text(encoding="utf-8")
    again = S.install(make_package(tmp_path / "src2"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    assert again["ok"] and again["mode"] == "install"


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe")
def test_a_deferred_removal_that_cannot_finish_keeps_the_key_and_the_next_install_resumes_over_the_leftover(tmp_path):
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "src"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    locked = t.target / "runtime" / "python" / "pythonw.exe"
    holder = hold_file(locked, 12)
    try:
        exited = subprocess.Popen([sys.executable, "-c", "pass"])
        exited.wait(timeout=30)
        result = S.uninstall(t, progress=quiet(), running_from=t.target / "runtime" / "python",
                             script_dir=tmp_path / "tmp", pid=exited.pid, image=Path(sys.executable).name,
                             deferred_attempts=1)
        assert wait_until(lambda: not Path(result["removal_script"]).exists(), 30)
        log = (tmp_path / "tmp" / S.UNINSTALL_LOG).read_text(encoding="utf-8")
        assert "ECHEC" in log and "cle de desinstallation gardee" in log
        # Reste réparable : la clé (désinstallation encore proposée) et l'état d'opération sont gardés.
        assert locked.exists() and not (t.target / PR.RUNTIME_MANIFEST).exists()
        assert t.registry.read() is not None and S.folder_kind(t.target) == "leftover"
    finally:
        holder.wait(timeout=30)
    again = S.install(make_package(tmp_path / "src2"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    assert again["ok"] and again["resumed"] and again["leftovers"] == []
    assert PR.verify_package(PR.PackageLayout(t.target))[1] == [] and not S.state_path(t.target).exists()
    assert sorted(p.name for p in t.target.parent.iterdir()) == ["Jarvis"]


def test_a_direct_uninstall_blocked_by_a_locked_file_keeps_the_key_and_can_be_run_again(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RETRY_DELAYS_S", (0.0,))
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "src"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    handle = open(t.target / "runtime" / "node" / "node.exe", "rb")
    try:
        with pytest.raises(S.SetupError) as refused:
            S.uninstall(t, progress=quiet())
        assert refused.value.code == "uninstall_incomplete" and "relancez la désinstallation" in str(refused.value)
        assert t.registry.read() is not None and S.folder_kind(t.target) == "leftover"
    finally:
        handle.close()
    result = S.uninstall(t, progress=quiet())
    assert result["removed"] and not t.target.exists() and t.registry.read() is None
    assert not S.state_path(t.target).exists()


@pytest.mark.parametrize("damage", ["unreadable_manifest", "no_marker", "other_product"])
def test_a_folder_without_both_proofs_is_never_deleted_nor_replaced(tmp_path, damage):
    """Sonde P2 / M1 de la QA runtime : un dossier au `runtime-manifest.json` illisible était effacé (désinstallation)
    ou « mis à jour » puis vidé (installation)."""

    t = targets(tmp_path)
    t.target.mkdir(parents=True)
    (t.target / "thesis.docx").write_text("precious", encoding="utf-8")
    if damage == "unreadable_manifest":
        (t.target / PR.RUNTIME_MANIFEST).write_text("not json", encoding="utf-8")
        (t.target / "app").mkdir()
        (t.target / "app" / PRODUCT_MARKER).write_text(json.dumps(marker_payload()), encoding="utf-8")
    else:
        package = make_package(tmp_path / "pkg")
        (t.target / PR.RUNTIME_MANIFEST).write_bytes((package / PR.RUNTIME_MANIFEST).read_bytes())
        if damage == "other_product":
            (t.target / "app").mkdir()
            (t.target / "app" / PRODUCT_MARKER).write_text(json.dumps({**marker_payload(), "product": "Other"}),
                                                           encoding="utf-8")
    before = {p.relative_to(t.target).as_posix(): p.read_bytes() for p in t.target.rglob("*") if p.is_file()}
    with pytest.raises(S.SetupError) as uninstall_refused:
        S.uninstall(t, progress=quiet())
    assert uninstall_refused.value.code == "not_a_jarvis_folder"
    with pytest.raises(S.SetupError) as install_refused:
        S.install(make_package(tmp_path / "src"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    assert install_refused.value.code == "target_not_empty"
    after = {p.relative_to(t.target).as_posix(): p.read_bytes() for p in t.target.rglob("*") if p.is_file()}
    assert after == before and not S.state_path(t.target).exists()


def test_a_state_file_never_turns_a_foreign_folder_into_a_leftover(tmp_path):
    t = targets(tmp_path)
    t.target.mkdir(parents=True)
    (t.target / "runtime").mkdir()
    S.write_state(t.target, "uninstall", entries={"runtime", "app"})
    assert S.folder_kind(t.target) == "leftover"
    (t.target / "thesis.docx").write_text("mine", encoding="utf-8")  # une entrée que JARVIS n'a jamais notée
    assert S.folder_kind(t.target) == "foreign"
    other = targets(tmp_path / "other")
    other.target.mkdir(parents=True)
    (other.target / "runtime").mkdir()
    S.state_path(other.target).write_text(S.state_path(t.target).read_text(encoding="utf-8"), encoding="utf-8")
    assert S.folder_kind(other.target) == "foreign"  # état d'une AUTRE cible : aucune preuve


def test_a_rollback_blocked_by_a_locked_file_says_so_and_the_next_install_repairs(tmp_path, monkeypatch):
    """Sonde P3 de la QA : la copie ratée ne pouvait pas être effacée (fichier verrouillé) ; `os.replace` levait
    `PermissionError`, l'ancienne version restait sous `Jarvis.previous-*` et l'amorce disait « rien n'a été effacé »."""

    monkeypatch.setattr(S, "RETRY_DELAYS_S", (0.0, 0.05))
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "v1"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    locks = []

    def bad_copy(source, target):
        locks.append(open(target / "app" / "jarvis" / "__init__.py", "rb"))
        return ["simulated: copy differs"]

    try:
        with pytest.raises(S.SetupError) as refused:
            S.install(make_package(tmp_path / "v2", "0.3.0"), t, move=False, progress=quiet(),
                      shortcuts=RecordingShortcuts(), verify_copy=bad_copy)
        error = refused.value
        assert error.code == "rollback_failed" and error.extra["rolled_back"] is False
        assert "Redémarrez Windows, puis relancez l'installation" in str(error)
        previous = Path(error.extra["previous"])
        assert previous.name.startswith("Jarvis.previous-") and S.is_jarvis_program(previous)
        assert S.read_state(t.target)["previous"] == str(previous) and S.folder_kind(t.target) == "leftover"
    finally:
        for handle in locks:
            handle.close()
    repaired = S.install(make_package(tmp_path / "v3", "0.3.0"), t, move=False, progress=quiet(),
                         shortcuts=RecordingShortcuts())
    assert repaired["ok"] and repaired["resumed"] and repaired["leftovers"] == []
    assert "0.3.0" in (t.target / "app" / "jarvis" / "__init__.py").read_text(encoding="utf-8")
    assert sorted(p.name for p in t.target.parent.iterdir()) == ["Jarvis"]  # ni .previous-*, ni .failed-*, ni état


def test_a_failed_first_install_says_nothing_was_installed_and_leaves_no_shortcut(tmp_path):
    t = targets(tmp_path)

    class BrokenRegistry(S.FileRegistry):
        def write(self, values):
            raise OSError("registry refused")

    t.registry = BrokenRegistry(tmp_path / "hive.json")
    with pytest.raises(S.SetupError) as refused:
        S.install(make_package(tmp_path / "src"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    assert refused.value.code == "setup_failed" and refused.value.extra["had_previous"] is False
    assert "Rien n'a été installé" in str(refused.value) and "précédente" not in str(refused.value)
    assert not t.target.exists() and not (t.start_menu / "JARVIS.lnk").exists() and not S.state_path(t.target).exists()


def test_the_target_may_not_be_an_ancestor_of_the_home(tmp_path):
    """Mutation M1 de la QA (survivante) : ce refus protège la maison à la désinstallation."""

    home = tmp_path / "Local" / "CIRCOE" / "Jarvis"
    for target in (tmp_path / "Local", tmp_path / "Local" / "CIRCOE", home, home / "data"):
        with pytest.raises(S.SetupError) as refused:
            S.check_target(S.Targets(target=target.resolve(), start_menu=None, desktop=None,
                                     registry=S.FileRegistry(tmp_path / "h.json"), home=home))
        assert refused.value.code == "target_overlaps_home", target
    S.check_target(S.Targets(target=(tmp_path / "Local" / "Programs" / "CIRCOE" / "Jarvis").resolve(), start_menu=None,
                             desktop=None, registry=S.FileRegistry(tmp_path / "h.json"), home=home))


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe")
def test_the_deferred_removal_really_deletes_a_folder_with_spaces(tmp_path):
    """Essai réel de la commande différée (QA de la Slice : la forme en liste ne supprimait rien)."""

    t = targets(tmp_path / "with space")
    S.install(make_package(tmp_path / "src"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    exited = subprocess.Popen([sys.executable, "-c", "pass"])
    exited.wait(timeout=30)
    S.uninstall(t, progress=quiet(), running_from=t.target / "runtime" / "python", script_dir=tmp_path / "tmp",
                pid=exited.pid, image=Path(sys.executable).name)
    assert wait_until(lambda: not t.target.exists(), 30)
    assert t.target.parent.exists() and wait_until(lambda: t.registry.read() is None, 10)


def test_uninstall_refuses_a_folder_that_is_not_jarvis(tmp_path):
    t = targets(tmp_path)
    t.target.mkdir(parents=True)
    (t.target / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(S.SetupError) as refused:
        S.uninstall(t, progress=quiet())
    assert refused.value.code == "not_a_jarvis_folder" and (t.target / "keep.txt").exists()


def test_the_command_line_writes_progress_and_result_and_returns_its_code(tmp_path):
    source = make_package(tmp_path / "src")
    target = tmp_path / "Programs" / "Jarvis"
    progress = tmp_path / "progress.jsonl"
    result = tmp_path / "result.json"
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}
    code = S.main(["install", "--source", str(source), "--target", str(target), "--registry-file", str(tmp_path / "hive.json"),
                   "--progress", str(progress), "--result", str(result)], environ=env)
    outcome = json.loads(result.read_text(encoding="utf-8"))
    assert code == 0 and outcome["ok"] and outcome["shortcuts"] == []
    phases = [json.loads(line)["phase"] for line in progress.read_text(encoding="utf-8").splitlines()]
    assert phases[0] == "verify_source" and phases[-1] == "done"
    code = S.main(["uninstall", "--registry-file", str(tmp_path / "hive.json"), "--quiet", "--result", str(result)],
                  environ=env)
    assert code == 0 and not target.exists()
    code = S.main(["uninstall", "--registry-file", str(tmp_path / "hive.json"), "--quiet", "--target", str(target),
                   "--result", str(result)], environ=env)
    assert code == 0  # rien à retirer : déjà désinstallé


def test_real_shortcuts_are_written_with_wscript_shell_into_a_simulated_folder(tmp_path):
    pytest.importorskip("win32com.client")
    link = tmp_path / "Simulated Start Menu" / "JARVIS.lnk"
    S.ShellShortcuts().create(link, target=Path(r"C:\Windows\System32\notepad.exe"), arguments="-B -m jarvis launch",
                              working_dir=tmp_path, description="Ouvrir JARVIS", icon=Path(r"C:\Windows\System32\notepad.exe"))
    import pythoncom
    import win32com.client

    def read() -> tuple[str, str]:
        shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(link))
        return str(shortcut.Arguments), str(shortcut.TargetPath)

    pythoncom.CoInitialize()
    try:
        arguments, target = read()
    finally:
        pythoncom.CoUninitialize()
    assert arguments == "-B -m jarvis launch" and target.lower().endswith("notepad.exe")


def test_the_copy_check_names_missing_extra_and_resized_files(tmp_path):
    source = make_package(tmp_path / "src")
    copy = tmp_path / "copy"
    import shutil

    shutil.copytree(source, copy)
    assert S.copy_matches(source, copy) == []
    (copy / "licenses" / "LICENSE.txt").write_text("changed size\n", encoding="utf-8")
    (copy / "runtime" / "node" / "node.exe").unlink()
    (copy / "stray.txt").write_text("x", encoding="utf-8")
    problems = S.copy_matches(source, copy)
    assert "runtime/node/node.exe: absent de la copie" in problems
    assert "stray.txt: en trop dans la copie" in problems
    assert "licenses/LICENSE.txt: taille différente" in problems


def test_progress_never_breaks_the_installation_when_its_file_cannot_be_written(tmp_path, monkeypatch):
    """Essai réel de la Slice : l'amorce lisait le fichier de progression sans partage d'écriture ; l'ajout de Python
    échouait et l'installation tombait sans écrire son issue."""

    blocked = tmp_path / "progress.jsonl"
    blocked.mkdir()  # ouvrir un dossier en ajout échoue à chaque essai
    monkeypatch.setattr(S.time, "sleep", lambda seconds: None)
    S.Progress(blocked, echo=False).step("verify_source", "Vérification…")
    target = tmp_path / "Programs" / "Jarvis"
    code = S.main(["install", "--source", str(make_package(tmp_path / "src")), "--target", str(target), "--registry-file",
                   str(tmp_path / "hive.json"), "--progress", str(blocked), "--result", str(tmp_path / "out" / "result.json")],
                  environ={"LOCALAPPDATA": str(tmp_path / "Local")})
    assert code == 0 and json.loads((tmp_path / "out" / "result.json").read_text(encoding="utf-8"))["ok"] is True


def test_a_reused_launcher_pid_does_not_block_the_installer(tmp_path):
    """I-009 point 2 : après un plantage du lanceur, son PID réemployé par un autre processus ne vaut plus « ouvert »."""

    t = targets(tmp_path)
    (t.home / "runtime").mkdir(parents=True)
    state = t.home / "runtime" / "launcher.json"
    state.write_text(json.dumps({"pid": 77, "process_ref": "77:1000"}), encoding="utf-8")
    result = S.install(make_package(tmp_path / "src"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts(),
                       alive=lambda pid: True, ref_alive=lambda ref: False)
    assert result["ok"] and result["mode"] == "install"
    with pytest.raises(S.SetupError) as running:
        S.uninstall(t, progress=quiet(), alive=lambda pid: True, ref_alive=lambda ref: ref == "77:1000")
    assert running.value.code == "jarvis_running"


def test_a_locked_program_is_refused_before_the_package_verification(tmp_path):
    """I-009 point 1 : un fichier tenu par un autre programme est dit en secondes, avant la longue vérification."""

    t = targets(tmp_path)
    S.install(make_package(tmp_path / "v1"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    verified = []

    def locked(source, destination):
        raise PermissionError(32, "Le processus ne peut pas accéder au fichier", str(source))

    with pytest.raises(S.SetupError) as refused:
        S.install(make_package(tmp_path / "v2", "0.3.0"), t, move=False, progress=quiet(),
                  shortcuts=RecordingShortcuts(), rename=locked,
                  verify=lambda layout: verified.append(layout) or (None, ["never"]))
    assert refused.value.code == "jarvis_running" and "antivirus" in str(refused.value)
    assert verified == []  # refusé AVANT la vérification du paquet
    assert sorted(p.name for p in t.target.parent.iterdir()) == ["Jarvis"]  # rien de mis de côté, aucun état
    assert PR.verify_package(PR.PackageLayout(t.target))[1] == []


def test_a_probe_that_cannot_put_the_program_back_is_resumed_by_the_next_install(tmp_path, monkeypatch):
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "v1"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    calls = []

    def sticky(source, destination):
        calls.append((source.name, destination.name))
        if len(calls) > 1:
            raise PermissionError(5, "Accès refusé", str(source))  # la remise en place échoue à chaque reprise
        os.replace(source, destination)

    monkeypatch.setattr(S, "RETRY_DELAYS_S", (0.0,))
    with pytest.raises(S.SetupError) as refused:
        S.install(make_package(tmp_path / "v2", "0.3.0"), t, move=False, progress=quiet(),
                  shortcuts=RecordingShortcuts(), rename=sticky)
    monkeypatch.undo()
    assert refused.value.code == "rollback_failed" and "Redémarrez Windows" in str(refused.value)
    aside = Path(refused.value.extra["previous"])
    assert not t.target.exists() and aside.is_dir() and aside.name.startswith("Jarvis" + S.PREVIOUS_SUFFIX)
    assert S.read_state(t.target)["previous"] == str(aside)
    result = S.install(make_package(tmp_path / "v3", "0.3.0"), t, move=False, progress=quiet(),
                       shortcuts=RecordingShortcuts())
    assert result["ok"] and sorted(p.name for p in t.target.parent.iterdir()) == ["Jarvis"]
