"""Moteur Remotion de Core : disponibilité, descripteur de lecture, porte du moteur, compatibilité scène/moteur (Slice 10).

Vrai `PrefabService` sur dossiers temporaires, vrai `PresentationStudioService` ; seuls le compilateur et le bac à sable sont des
doubles (leur processus et leur socket sont éprouvés dans `test_remotion_sandbox_server.py` et dans le navigateur
`test_remotion_player_realpage_browser.py`). Contrat : `docs/presentation-engine.md` > *Runtime wiring status*.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import FilePrefabLibrary
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.prefab_service import PrefabService
from jarvis.core.presentation_studio_engine_gate import StudioEngineGate
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.core.remotion_player import RemotionPlayerService
from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_engine import Engine, EngineAvailability
from jarvis.domain.remotion_compile import (
    CompiledArtifact, CompileDiagnostic, CompileTarget, CompiledFile, CompileErrorCode, InstalledEngine, RemotionCompileError,
)
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from jarvis.ports.remotion import SandboxBindError
from tests.fakes.conversation_events import RecordingDiagnostics
from tests.fakes.prefabs import candidate as html_candidate, install_version
from tests.fakes.remotion_scene import scene_candidate

NOW = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
SCENE = "presentation-studio.p000000000001.s000000000001"
ENGINE = InstalledEngine("4.0.534", "19.3.0", "a" * 64, "c" * 64)


class FakeCompiler:
    def __init__(self, *, reason: str | None = None, error: Exception | None = None) -> None:
        self.reason, self.error = reason, error
        self.calls: list[str] = []

    def unavailable_reason(self):
        return self.reason

    def _artifact(self, target: CompileTarget, key: str) -> CompiledArtifact:
        return CompiledArtifact(target, key, (CompiledFile("scene.js", 10, "f" * 64),), ENGINE, source_digest="d" * 64,
                                engine_pinned={"version": "4.0.534", "react_version": "19.3.0", "lock_sha256": "a" * 64})

    def compile_host(self):
        self.calls.append("host")
        if self.error:
            raise self.error
        return self._artifact(CompileTarget.HOST, "host-" + "1" * 32)

    def compile_scene(self, source):
        self.calls.append("scene")
        if self.error:
            raise self.error
        return self._artifact(CompileTarget.SCENE, "scene-" + "2" * 32)


class FakeSandbox:
    configured_origin = "http://127.77.0.2:17655"
    embedder_origin = "http://127.0.0.1:17654"

    def __init__(self, *, bind_error: str | None = None) -> None:
        self.bind_error, self.started = bind_error, 0

    @property
    def origin(self):
        return self.configured_origin if self.started else None

    async def ensure_started(self):
        if self.bind_error:
            raise SandboxBindError(self.bind_error)
        self.started += 1
        return self.configured_origin


@pytest.fixture
async def prefabs(tmp_path: Path):
    package, data = tmp_path / "package", tmp_path / "data"
    package.mkdir()
    data.mkdir()
    install_version(package, "jarvis.counter", title="Base counter")
    service = PrefabService(FilePrefabLibrary(package, data), clock=lambda: NOW)
    await service.save(scene_candidate(), actor="user")
    return service


def player(prefabs, compiler="default", sandbox="default"):
    compiler = FakeCompiler() if compiler == "default" else compiler
    sandbox = FakeSandbox() if sandbox == "default" else sandbox
    return RemotionPlayerService(prefabs, compiler, sandbox, diagnostics=RecordingDiagnostics()), compiler, sandbox


# ------------------------------------------------------------------ availability: the only reading of "is Remotion ready"

def test_remotion_is_ready_only_when_its_compiler_its_capability_and_its_sandbox_are_all_there():
    ready, _, _ = player(None)
    assert ready.availability() == EngineAvailability(True)
    no_compiler, _, _ = player(None, compiler=None)
    state = no_compiler.availability()
    assert not state.ready and "no Remotion adapter" in state.reason and state.repair
    no_sandbox, _, _ = player(None, sandbox=None)
    assert not no_sandbox.availability().ready and "sandbox" in no_sandbox.availability().reason
    missing, _, _ = player(None, compiler=FakeCompiler(reason="the Remotion capability is not_installed"))
    state = missing.availability()
    assert not state.ready and state.reason == "the Remotion capability is not_installed" and "install" in state.repair


def test_the_sandbox_info_names_the_origin_the_control_center_must_allow():
    service, _, sandbox = player(None)
    assert service.sandbox_info() == {"configured": True, "origin": sandbox.configured_origin,
                                      "embedder_origin": sandbox.embedder_origin, "listening": False}
    assert player(None, sandbox=None)[0].sandbox_info()["configured"] is False


# ------------------------------------------------------------------ describe

async def test_describe_compiles_opens_the_sandbox_and_hands_a_browser_what_it_needs_and_nothing_more(prefabs):
    service, compiler, sandbox = player(prefabs)
    body = await service.describe(SCENE, 1)
    assert compiler.calls == ["host", "scene"] and sandbox.started == 1
    assert body["kind"] == "remotion" and body["engine"] == "remotion" and body["prefab_id"] == SCENE
    assert body["page_url"] == f"{sandbox.configured_origin}/page/scene-{'2' * 32}/host-{'1' * 32}"
    assert body["composition"] == {"id": "Scene", "width": 1280, "height": 720, "fps": 30, "durationInFrames": 90}
    assert body["defaults"] == {"title": "Bonjour", "accent": "#3366ff"}
    assert body["embedder_origin"] == sandbox.embedder_origin and body["engine_drift"] is False
    text = str(body)
    assert "\\" not in text and "compiled/" not in text and "C:" not in text, "no disk path ever reaches a browser or a Board"


async def test_an_unready_engine_refuses_with_its_real_reason_and_compiles_nothing(prefabs):
    service, compiler, sandbox = player(prefabs, compiler=FakeCompiler(reason="the Remotion capability is not_installed"))
    with pytest.raises(PresentationStudioError) as caught:
        await service.describe(SCENE, 1)
    assert caught.value.code is C.ENGINE_UNAVAILABLE
    assert "not_installed" in caught.value.message and "Repair" in caught.value.message
    assert compiler.calls == [] and sandbox.started == 0, "nothing was compiled and no port was opened"


async def test_compile_runtime_unavailable_is_said_engine_unavailable_at_this_boundary(prefabs):
    error = RemotionCompileError(CompileErrorCode.RUNTIME_UNAVAILABLE, "the Remotion capability is repair_required")
    service, _, _ = player(prefabs, compiler=FakeCompiler(error=error))
    with pytest.raises(PresentationStudioError) as caught:
        await service.describe(SCENE, 1)
    assert caught.value.code is C.ENGINE_UNAVAILABLE and "repair_required" in caught.value.message


async def test_a_compile_error_keeps_its_file_line_and_column(prefabs):
    error = RemotionCompileError(CompileErrorCode.SOURCE_ERROR, "src/Scene.tsx:3:5: unexpected token",
                                 diagnostics=(CompileDiagnostic("src/Scene.tsx", 3, 5, "unexpected token"),))
    service, _, sandbox = player(prefabs, compiler=FakeCompiler(error=error))
    with pytest.raises(RemotionCompileError) as caught:
        await service.describe(SCENE, 1)
    assert caught.value.code is CompileErrorCode.SOURCE_ERROR and caught.value.status == 422
    assert [d.to_dict() for d in caught.value.diagnostics] == [{"file": "src/Scene.tsx", "line": 3, "column": 5, "text": "unexpected token"}]
    assert sandbox.started == 0


async def test_a_port_that_cannot_be_opened_is_an_unavailable_engine_not_a_blank_frame(prefabs):
    service, _, _ = player(prefabs, sandbox=FakeSandbox(bind_error="cannot bind the Remotion sandbox on 127.77.0.2:17655: busy"))
    with pytest.raises(PresentationStudioError) as caught:
        await service.describe(SCENE, 1)
    assert caught.value.code is C.ENGINE_UNAVAILABLE and "cannot bind" in caught.value.message
    assert "core.remotion_player.sandbox_bind_failed" in service._diagnostics.kinds()


async def test_a_html_prefab_is_never_described_as_a_remotion_scene(prefabs):
    service, compiler, _ = player(prefabs)
    with pytest.raises(PrefabStoreError) as caught:
        await service.describe("jarvis.counter", 1)
    assert caught.value.code is PrefabStoreErrorCode.INVALID_DEFINITION and compiler.calls == []


# ------------------------------------------------------------------ the engine gate: a `remotion` document NEVER plays HTML

def gate(state: EngineAvailability) -> StudioEngineGate:
    return StudioEngineGate(lambda: {Engine.SLIDECAR: EngineAvailability(True), Engine.REMOTION: state},
                            diagnostics=RecordingDiagnostics())


@pytest.fixture
def studio(tmp_path: Path, prefabs):
    (tmp_path / "studio").mkdir()

    def make(state: EngineAvailability):
        return PresentationStudioService(FilePresentationStudioStore(tmp_path / "studio"), prefabs=prefabs,
                                         engine_gate=gate(state), diagnostics=RecordingDiagnostics())
    return make


async def test_the_gate_refuses_a_remotion_document_when_its_adapter_is_not_ready_and_never_asks_for_slidecar(studio):
    service = studio(EngineAvailability(False, "the Remotion capability is not_installed", "install it"))
    view = await service.create({"title": "Remotion"})
    assert view.presentation.engine is Engine.REMOTION
    for action in ("play", "edit", "preview"):
        with pytest.raises(PresentationStudioError) as caught:
            await service.require_engine(view.presentation.presentation_id, action)
        assert caught.value.code is C.ENGINE_UNAVAILABLE and "not_installed" in caught.value.message
        assert "slidecar" not in caught.value.message.lower()


async def test_the_gate_lets_a_ready_engine_through(studio):
    service = studio(EngineAvailability(True))
    view = await service.create({"title": "R"})
    resolution = await service.require_engine(view.presentation.presentation_id, "play")
    assert resolution.engine is Engine.REMOTION


async def test_without_a_gate_the_service_behaves_as_before_the_slice(tmp_path: Path, prefabs):
    (tmp_path / "studio").mkdir()
    service = PresentationStudioService(FilePresentationStudioStore(tmp_path / "studio"), prefabs=prefabs)
    view = await service.create({"title": "Legacy world"})
    assert await service.require_engine(view.presentation.presentation_id, "play") is None


async def test_scene_add_requires_the_source_to_be_compatible_with_the_presentation_engine(studio):
    service = studio(EngineAvailability(True))
    view = await service.create({"title": "Compat"})
    pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
    variant = await service.get_variant(pid, vid)
    remotion_scene = {"scene_id": "pss_000000000001", "prefab": {"id": SCENE, "version": 1}, "title": "Remotion",
                      "props": {"title": "Bonjour", "accent": "#3366ff"}, "data": {}, "controls": [], "anchors": []}
    html_scene = {"scene_id": "pss_000000000002", "prefab": {"id": "jarvis.counter", "version": 1}, "title": "Html",
                  "props": {}, "data": {}, "controls": [], "anchors": []}
    base = {"expected_revision": variant.revision, "title": variant.title, "art_direction_id": variant.art_direction_id,
            "score_id": variant.score_id}
    saved = await service.save_variant(pid, vid, {**base, "scenes": [remotion_scene]})
    assert [s.scene_id for s in saved.scenes] == ["pss_000000000001"], "a Remotion source in a Remotion presentation is native"
    with pytest.raises(PresentationStudioError) as caught:
        await service.save_variant(pid, vid, {**base, "expected_revision": saved.revision, "scenes": [remotion_scene, html_scene]})
    assert caught.value.code is C.ENGINE_UNSUPPORTED and "jarvis.counter@1" in caught.value.message
    assert "remotion" in caught.value.message


# ------------------------------------------------------------------ B1: `adapter` is declared, not usable (PM decision)

CATALOG = {"type": "component", "compatibility": {"slidecar": "native", "remotion": "adapter"}, "stack": ["html"], "dependencies": [],
           "license": "MIT", "upstream": {"name": "t", "url": "https://example.test/t"}}


def html_adapter_candidate():
    """An HTML prefab that DECLARES `slidecar: native, remotion: adapter` (manifest v3)."""

    raw = html_candidate()
    raw["manifest"] = {**raw["manifest"], "schema_version": 3, "catalog": copy.deepcopy(CATALOG)}
    return raw


def remotion_slidecar_adapter_candidate(prefab_id: str):
    raw = scene_candidate(prefab_id)
    raw["manifest"] = {**raw["manifest"], "schema_version": 3, "catalog": {
        "type": "composition", "compatibility": {"remotion": "native", "slidecar": "adapter"}, "stack": ["react", "remotion"],
        "dependencies": [], "license": "MIT", "upstream": {"name": "t", "url": "https://example.test/t"}}}
    return raw


def scene_of(scene_id: str, prefab_id: str, data: dict | None = None, **props):
    return {"scene_id": scene_id, "prefab": {"id": prefab_id, "version": 1}, "title": "S", "props": props, "data": data or {}, "controls": [],
            "anchors": []}


async def save_only(service, pid, vid, scene):
    variant = await service.get_variant(pid, vid)
    return await service.save_variant(pid, vid, {"expected_revision": variant.revision, "title": variant.title, "scenes": [scene],
                                                 "art_direction_id": variant.art_direction_id, "score_id": variant.score_id})


async def test_an_html_prefab_that_declares_remotion_adapter_is_refused_in_a_remotion_document(studio, prefabs):
    adapter_id = html_adapter_candidate()["manifest"]["id"]
    await prefabs.save(html_adapter_candidate(), actor="user")
    service = studio(EngineAvailability(True))
    view = await service.create({"title": "R"})
    pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
    with pytest.raises(PresentationStudioError) as caught:
        await save_only(service, pid, vid, scene_of("pss_000000000001", adapter_id, label="x"))
    assert caught.value.code is C.ENGINE_UNSUPPORTED
    assert "adapter" in caught.value.message and "cannot be used" in caught.value.message
    assert (await service.get_variant(pid, vid)).scenes == (), "nothing was stored: the document never holds HTML for a Remotion engine"


async def test_a_remotion_source_that_declares_slidecar_adapter_is_refused_in_a_slidecar_document(studio, prefabs, monkeypatch):
    import functools
    from jarvis.core import presentation_studio_service as module
    monkeypatch.setattr(module, "new_presentation", functools.partial(module.new_presentation, engine=Engine.SLIDECAR))
    other = "presentation-studio.p000000000001.s000000000002"
    await prefabs.save(remotion_slidecar_adapter_candidate(other), actor="user")
    service = studio(EngineAvailability(True))
    view = await service.create({"title": "Legacy"})
    assert view.presentation.engine is Engine.SLIDECAR
    pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
    with pytest.raises(PresentationStudioError) as caught:
        await save_only(service, pid, vid, scene_of("pss_000000000001", other, title="x", accent="#3366ff"))
    assert caught.value.code is C.ENGINE_UNSUPPORTED and "adapter" in caught.value.message and "slidecar" in caught.value.message
    # ... and the plain Remotion source (native in Remotion, unsupported in Slidecar) is refused as before
    with pytest.raises(PresentationStudioError) as plain:
        await save_only(service, pid, vid, scene_of("pss_000000000001", SCENE, title="x", accent="#3366ff"))
    assert plain.value.code is C.ENGINE_UNSUPPORTED and "not supported by slidecar" in plain.value.message


def test_require_native_is_native_only_and_the_triage_function_is_unchanged():
    from jarvis.domain.presentation_studio_engine import Support, require_compatible, require_native
    declared = {"slidecar": "native", "remotion": "adapter"}
    assert require_native(declared, Engine.SLIDECAR) is Support.NATIVE
    assert require_compatible(declared, Engine.REMOTION) is Support.ADAPTER, "the declaration stays readable (Slice 17 labels)"
    for engine in (Engine.REMOTION,):
        with pytest.raises(PresentationStudioError) as caught:
            require_native(declared, engine, what="x")
        assert caught.value.code is C.ENGINE_UNSUPPORTED and "declared, not usable" in caught.value.message
    with pytest.raises(PresentationStudioError):
        require_native({"slidecar": "native"}, Engine.REMOTION)
    with pytest.raises(PresentationStudioError):
        require_native(None, Engine.REMOTION)


# ------------------------------------------------------------------ B2: every block that reaches the stage is checked against the engine

async def test_a_block_pin_is_checked_for_the_presentation_engine_on_every_stage_path(studio, prefabs):
    await prefabs.save(html_adapter_candidate(), actor="user")
    html_id = html_adapter_candidate()["manifest"]["id"]
    service = studio(EngineAvailability(True))
    view = await service.create({"title": "R"})
    pid = view.presentation.presentation_id
    await service.require_native_pin(pid, SCENE, 1, what="detour block")                    # native: passes
    for what in ("detour block", "preview", "scene"):
        with pytest.raises(PresentationStudioError) as caught:
            await service.require_native_pin(pid, html_id, 1, what=what)
        assert caught.value.code is C.ENGINE_UNSUPPORTED and what in caught.value.message
    with pytest.raises(PresentationStudioError) as unknown:
        await service.require_native_pin(pid, "no.such.prefab", 1, what="detour block")
    assert unknown.value.code in (C.PREFAB_UNAVAILABLE, C.STORAGE_IO), "an unknown block is refused, never shown"


async def test_every_stored_scene_is_rechecked_not_only_the_changed_ones(tmp_path, prefabs):
    """A document stored before the check (or written by a path that skipped it) holds an HTML scene in a Remotion document: a run
    refuses to start on it. Two services share one store: the first has no gate (the old world), the second is the gated Core."""

    (tmp_path / "studio").mkdir()
    await prefabs.save(html_adapter_candidate(), actor="user")
    html_id = html_adapter_candidate()["manifest"]["id"]
    old_world = PresentationStudioService(FilePresentationStudioStore(tmp_path / "studio"), prefabs=prefabs)
    view = await old_world.create({"title": "Stored"})
    pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
    saved = await save_only(old_world, pid, vid, scene_of("pss_000000000001", html_id, {"count": 1}, label="x"))
    assert saved.scenes[0].prefab.prefab_id == html_id
    gated = PresentationStudioService(FilePresentationStudioStore(tmp_path / "studio"), prefabs=prefabs,
                                      engine_gate=gate(EngineAvailability(True)))
    with pytest.raises(PresentationStudioError) as caught:
        await gated.require_native_scenes(pid, (await gated.get_variant(pid, vid)).scenes)
    assert caught.value.code is C.ENGINE_UNSUPPORTED and "pss_000000000001" in caught.value.message
