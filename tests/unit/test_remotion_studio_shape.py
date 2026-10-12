"""The workspace shape before EVERY Remotion Studio launch, and the `studio-edits` rotation (QA Slice 12 rework, B1 and I4).

B1: reopening Remotion Studio on the same scene with unpublished edits keeps the workspace (Slice 12), and that path used to skip the only
step that removed foreign top-level files: Node then ran a planted `remotion.config.js`. Now `enforce_shape` runs before every launch, the
kept path included: only `src/**` and `public/**` regular files are user content, the generated files are regenerated, and anything else
(a top-level file or folder, a link, a junction, a hard link, anywhere) is MOVED into `studio-edits/` (never deleted, never followed), said in
the view and logged. Bench: the real `RemotionStudioRunner` on disk and the real `RemotionStudioService`; only the process is stubbed
(`launch` records what the workspace held at that instant). The real Node proof is `test_remotion_studio_shape_real.py` (opt-in).

I4: set-aside folders get sortable, monotonic names; the rotation keeps the 5 newest and names what it removed (logged by the service).
Contract: `docs/remotion-studio.md` § 2 bis and § 11.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis.adapters import remotion_studio_runner as R
from jarvis.core.remotion_studio_service import RemotionStudioService
from jarvis.domain import remotion_studio as D
from jarvis.domain.remotion_studio import StudioPin, StudioState
from jarvis.ports.remotion_studio import LaunchResult
from tests.unit.test_remotion_studio import Recorder, source_for

pytestmark = pytest.mark.asyncio

PIN = StudioPin("presentation-studio.p000000000001.s000000000001", 1)
CONFIG_JS = "require('node:fs').writeFileSync('../CONFIG_RAN.txt', 'ran');\n"


class StubbedProcessRunner(R.RemotionStudioRunner):
    """The real disk side; no Node process. `launch` records the top-level entries and every link seen at that instant."""

    def __init__(self, runtime: Path, **options) -> None:
        super().__init__(lambda: runtime, which=lambda name: None, **options)
        self.launched_with: list[list[str]] = []

    def runtime_ready(self):
        return None

    def launch(self, *, port, idle_s):
        work = self._work
        self.launched_with.append(sorted(os.listdir(work)))
        return LaunchResult("4242:1", 45000, "launch-1")

    def bind_parent(self):
        return None

    def is_alive(self, process_ref):
        return True

    def probe(self, port, launch_id):
        return None

    def stop(self, process_ref):
        return None

    def activity(self, launch_id):
        return {}


class Bench:
    def __init__(self, tmp_path: Path) -> None:
        self.runtime = tmp_path / "rt" / "local_capabilities" / "remotion" / "runtime"
        self.runtime.mkdir(parents=True)
        self.outside = tmp_path / "outside"
        self.outside.mkdir()
        self.runner = StubbedProcessRunner(self.runtime)
        self.events = Recorder()
        self.service = RemotionStudioService(self.runner, source_provider=self.provide, capability_status=lambda: "ready",
                                             diagnostics=self.events)

    async def provide(self, pin):
        return source_for(pin), {"title": "Bonjour"}

    @property
    def work(self) -> Path:
        return self.runtime / "studio" / "work"

    @property
    def edits(self) -> Path:
        return self.runtime.parent / R.EDITS_DIR

    def files(self) -> dict[str, bytes]:
        return D.plan_workspace(source_for(PIN), {"title": "Bonjour"})

    def materialize(self) -> None:
        """The workspace as an open then a close leave it, with one unpublished edit: the next open on the same pin KEEPS it."""

        self.runner.sync_work(self.files())
        self.runner.write_state(StudioState(pin=PIN).to_payload())
        (self.work / "src" / "Scene.tsx").write_bytes(b"export default () => null; // unpublished edit\n")

    def set_aside(self) -> list[Path]:
        return sorted(path for path in self.edits.rglob("*") if path.is_file() or path.is_symlink() or _is_junction(path))


def _is_junction(path: Path) -> bool:
    try:
        return bool(os.lstat(path).st_file_attributes & 0x400)
    except (OSError, AttributeError):
        return False


@pytest.fixture
def bench(tmp_path):
    b = Bench(tmp_path)
    b.materialize()
    return b


async def reopen(bench) -> dict:
    view = await bench.service.open(PIN, acknowledged=True)
    assert view["status"] == "ready", view
    assert "remotion_studio.workspace_kept" in bench.events.kinds(), "the kept path (same pin, unpublished edits) is what is tested"
    return view


def assert_kept_edit_and_clean_top_level(bench) -> None:
    [seen] = bench.runner.launched_with
    assert seen == sorted(["package.json", "public", "src", "studio-root.tsx"]) or seen == sorted(["package.json", "src", "studio-root.tsx"]), seen
    assert (bench.work / "src" / "Scene.tsx").read_bytes().endswith(b"// unpublished edit\n"), "the user's own edit is never set aside"


@pytest.mark.parametrize("name", ["remotion.config.js", "remotion.config.ts", "notes.txt", ".env"])
async def test_a_planted_top_level_file_is_set_aside_before_a_kept_reopen(bench, name):
    (bench.work / name).write_text(CONFIG_JS, encoding="utf-8")
    view = await reopen(bench)
    assert_kept_edit_and_clean_top_level(bench)
    assert not (bench.work / name).exists()
    [copy] = [path for path in bench.set_aside() if path.name == name]
    assert copy.read_text(encoding="utf-8") == CONFIG_JS, "moved, never deleted"
    assert view["work_copy"]["set_aside"] == [name] and view["work_copy"]["modified_files"] == ["src/Scene.tsx"]
    assert any("set aside in studio-edits before the launch" in line and name in line for line in view["diagnostics"]), "said in the view"
    [event] = [data for kind, level, data in bench.events.events if kind == "remotion_studio.workspace_set_aside"]
    assert event["paths"] == [name] and event["count"] == 1
    assert [level for kind, level, _ in bench.events.events if kind == "remotion_studio.workspace_set_aside"] == ["warning"]


async def test_a_planted_top_level_folder_is_set_aside_too(bench):
    (bench.work / "config").mkdir()
    (bench.work / "config" / "remotion.config.js").write_text(CONFIG_JS, encoding="utf-8")
    view = await reopen(bench)
    assert_kept_edit_and_clean_top_level(bench)
    assert view["work_copy"]["set_aside"] == ["config/"]
    assert any(path.name == "remotion.config.js" for path in bench.set_aside())


async def test_a_junction_under_src_is_set_aside_and_its_target_never_touched(bench):
    import _winapi
    (bench.outside / "Leak.tsx").write_text("export const leak = 1;\n", encoding="utf-8")
    _winapi.CreateJunction(str(bench.outside), str(bench.work / "src" / "lib2"))
    view = await reopen(bench)
    assert_kept_edit_and_clean_top_level(bench)
    assert not os.path.lexists(bench.work / "src" / "lib2") and view["work_copy"]["set_aside"] == ["src/lib2"]
    assert (bench.outside / "Leak.tsx").read_text(encoding="utf-8") == "export const leak = 1;\n", "the target is never moved nor emptied"
    moved = next(bench.edits.rglob("lib2"))
    assert _is_junction(moved), "the junction itself was moved aside"


async def test_a_hard_link_under_src_is_set_aside_and_the_outside_file_stays(bench):
    secret = bench.outside / "secret.ts"
    secret.write_text("export const token = 1;\n", encoding="utf-8")
    os.link(secret, bench.work / "src" / "hard.ts")
    view = await reopen(bench)
    assert_kept_edit_and_clean_top_level(bench)
    assert not (bench.work / "src" / "hard.ts").exists() and view["work_copy"]["set_aside"] == ["src/hard.ts"]
    assert secret.read_text(encoding="utf-8") == "export const token = 1;\n"


async def test_a_replaced_source_folder_is_set_aside_and_the_generated_files_are_regenerated(bench):
    import _winapi
    import shutil
    shutil.rmtree(bench.work / "public", ignore_errors=True)
    _winapi.CreateJunction(str(bench.outside), str(bench.work / "public"))
    os.chmod(bench.work / D.WORK_ROOT_FILE, 0o666)
    (bench.work / D.WORK_ROOT_FILE).write_text("require('child_process'); // tampered root\n", encoding="utf-8")
    os.chmod(bench.work / D.WORK_PACKAGE, 0o666)
    (bench.work / D.WORK_PACKAGE).unlink()   # a missing generated file is written back
    view = await reopen(bench)
    assert sorted(view["work_copy"]["set_aside"]) == ["public", D.WORK_ROOT_FILE]
    files = bench.files()
    for name in (D.WORK_ROOT_FILE, D.WORK_PACKAGE):
        assert (bench.work / name).read_bytes() == files[name], f"{name} is what Jarvis generates"
        assert not os.access(bench.work / name, os.W_OK), "generated files stay read-only"
    assert any(path.name == D.WORK_ROOT_FILE and b"tampered" in path.read_bytes() for path in bench.set_aside())


async def test_a_clean_workspace_sets_nothing_aside_and_says_nothing(bench):
    view = await reopen(bench)
    assert view["work_copy"]["set_aside"] == [] and view["diagnostics"] == [] and not bench.edits.exists()
    assert "remotion_studio.workspace_set_aside" not in bench.events.kinds()


async def test_a_move_that_fails_never_launches(bench, monkeypatch):
    (bench.work / "remotion.config.js").write_text(CONFIG_JS, encoding="utf-8")
    real_replace = R.os.replace

    def refuse(source, target):
        if str(source).endswith("remotion.config.js"):
            raise PermissionError(13, "locked by another program")
        return real_replace(source, target)

    monkeypatch.setattr(R.os, "replace", refuse)
    view = await bench.service.open(PIN, acknowledged=True)
    assert view["status"] == "failed" and view["last_error_code"] == "remotion_studio_sync_failed"
    assert "not launched" in view["last_error_detail"] and bench.runner.launched_with == [], "never launched with a foreign file"
    assert (bench.work / "remotion.config.js").exists(), "nothing deleted"


async def test_a_restart_enforces_the_shape_too(bench):
    await reopen(bench)
    (bench.work / "remotion.config.ts").write_text("export {};\n", encoding="utf-8")
    view = await bench.service.restart(acknowledged=True)
    assert view["status"] == "ready" and view["work_copy"]["set_aside"] == ["remotion.config.ts"]
    assert "remotion.config.ts" not in bench.runner.launched_with[-1]


# ------------------------------------------------------------------ I4: rotation of `studio-edits/`

async def test_seven_set_asides_in_the_same_second_keep_the_five_newest_and_name_the_removed(tmp_path):
    runtime = tmp_path / "rt" / "local_capabilities" / "remotion" / "runtime"
    runtime.mkdir(parents=True)
    frozen = 1_760_000_000 * 1_000_000_000   # the same wall-clock nanosecond for all seven
    runner = R.RemotionStudioRunner(lambda: runtime, which=lambda name: None, wall_ns=lambda: frozen)
    files = D.plan_workspace(source_for(PIN), {"title": "Bonjour"})
    runner.sync_work(files)
    for index in range(7):
        (runner._work / "src" / "Scene.tsx").write_bytes(f"// edit {index}\n".encode())
        assert runner.save_modified() == ("src/Scene.tsx",)
    folders = sorted((runtime.parent / R.EDITS_DIR).iterdir())
    kept = [(folder / "src" / "Scene.tsx").read_bytes().decode() for folder in folders]
    assert kept == [f"// edit {index}\n" for index in range(2, 7)], "the five NEWEST are kept, in order"
    removed = runner.take_rotated()
    assert len(removed) == 2 and removed == tuple(sorted(removed)) and all(name < folders[0].name for name in removed)
    assert runner.take_rotated() == (), "each removal is reported once"


async def test_the_service_logs_each_rotation_naming_what_was_removed(bench):
    for index in range(D.MAX_SAVED_EDITS + 1):
        (bench.work / f"stray{index}.txt").write_text("x", encoding="utf-8")
        await bench.service.restart(acknowledged=True) if index else await reopen(bench)
    rotated = [data for kind, level, data in bench.events.events if kind == "remotion_studio.edits_rotated"]
    assert len(rotated) == 1 and len(rotated[0]["removed"]) == 1 and rotated[0]["kept"] == D.MAX_SAVED_EDITS
    assert [level for kind, level, _ in bench.events.events if kind == "remotion_studio.edits_rotated"] == ["warning"]
    assert len(list(bench.edits.iterdir())) == D.MAX_SAVED_EDITS
