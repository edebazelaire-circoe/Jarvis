"""Installation, mise à jour, réparation et désinstallation (presentation-edition-v1 Slice 07, `docs/product-install.md`).

Tout se passe dans `tmp_path` : paquet factice mais conforme (manifeste, empreintes), cible, maison, menu Démarrer et
Bureau simulés, ruche simulée (`FileRegistry`). Jamais le vrai registre, le vrai Bureau ni `%LOCALAPPDATA%`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis import private_runtime as PR
from jarvis import product_setup as S
from jarvis.installation import PRODUCT_MARKER, marker_payload


def make_package(root: Path, version: str = "0.2.0", extra: bytes = b"") -> Path:
    (root / "app" / "jarvis").mkdir(parents=True)
    (root / "app" / "jarvis" / "__init__.py").write_text(f"VERSION = {version!r}\n", encoding="utf-8")
    (root / "app" / PRODUCT_MARKER).write_text(json.dumps(marker_payload()), encoding="utf-8")
    for name, exe in (("python", "python.exe"), ("node", "node.exe")):
        (root / "runtime" / name).mkdir(parents=True)
        (root / "runtime" / name / exe).write_bytes(b"MZ" + name.encode() + extra)
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
    calls = {"n": 0}

    def verify(layout):
        calls["n"] += 1
        manifest, problems = PR.verify_package(layout)
        return (manifest, problems) if calls["n"] == 1 else (manifest, ["app: arbre modifié"])

    with pytest.raises(S.SetupError) as refused:
        S.install(make_package(tmp_path / "v2", "0.3.0"), t, move=False, progress=quiet(),
                  shortcuts=RecordingShortcuts(), verify=verify)
    assert refused.value.code == "installed_copy_damaged"
    assert "0.2.0" in (t.target / "app" / "jarvis" / "__init__.py").read_text(encoding="utf-8")
    assert not list(t.target.parent.glob("Jarvis.previous-*"))


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


def test_uninstall_from_inside_the_program_defers_the_folder_removal(tmp_path):
    t = targets(tmp_path)
    S.install(make_package(tmp_path / "src"), t, move=False, progress=quiet(), shortcuts=RecordingShortcuts())
    spawned = []
    result = S.uninstall(t, progress=quiet(), running_from=t.target / "runtime" / "python",
                         spawn=lambda argv, **kwargs: spawned.append((argv, kwargs)))
    assert result["deferred_removal"] and t.target.exists()
    argv, kwargs = spawned[0]
    assert argv[:3] == ["cmd.exe", "/d", "/c"] and f'rmdir /s /q "{t.target}"' in argv[3]
    assert kwargs["cwd"] == str(t.target.parent)


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
