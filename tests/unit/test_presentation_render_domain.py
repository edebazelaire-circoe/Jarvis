"""Domaine du rendu (Remotion Slice 16) : réglages, bornes, métadonnées plates, octets de sortie, PDF de pages-images, plan de la source gelée."""

from __future__ import annotations

import json
import re
import struct
import zlib

import pytest

from jarvis.domain import presentation_render as D
from jarvis.domain import presentation_render_output as O
from jarvis.domain.artifacts import ArtifactKind, new_artifact
from jarvis.domain.presentation_artifacts import RENDERS, RenderFormat
from jarvis.domain.presentation_render import RenderError, RenderErrorCode as C
from jarvis.domain.presentation_render_plan import choose_scene, plan_files, remotion_pins, render_props
from jarvis.domain.presentation_snapshot_package import read_package
from tests.fakes.presentation_world import SCENE_ID, PresentationWorld
from tests.fakes.remotion_scene import ENGINE

MP4, STILL, PDF = RenderFormat.MP4, RenderFormat.STILL, RenderFormat.PDF


def target(**changes) -> D.SceneTarget:
    base = dict(scene_id=SCENE_ID, prefab_id="presentation-studio.p000000000001.s000000000001", version=1, composition_id="Scene", width=1280,
                height=720, fps=30, duration_in_frames=90, engine_version="4.0.534", engine_lock_sha256="a" * 64, source_digest="d" * 64)
    base.update(changes)
    return D.SceneTarget(**base)


# ------------------------------------------------------------------ settings


def test_defaults_render_the_whole_scene_at_the_declared_size_and_cadence():
    resolved = D.resolve(MP4, D.parse_settings(MP4, None), target())
    assert (resolved.frame_start, resolved.frame_end, resolved.frames_total) == (0, 89, 90)
    assert (resolved.out_width, resolved.out_height) == (1280, 720)
    canonical = resolved.canonical()
    assert canonical["fps"] == 30 and canonical["codec"] == "h264" and canonical["pixel_format"] == "yuv420p" and canonical["crf"] == D.DEFAULT_CRF


def test_the_resolved_settings_are_deterministic_and_sensitive_to_every_choice():
    one = D.resolve(MP4, D.parse_settings(MP4, {"frame_end": 29}), target()).settings_sha256
    assert one == D.resolve(MP4, D.parse_settings(MP4, {"frame_end": 29}), target()).settings_sha256
    for changed in ({"frame_end": 30}, {"crf": 20}, {"scale": 0.5}, {"frame_start": 1, "frame_end": 29}):
        assert D.resolve(MP4, D.parse_settings(MP4, changed), target()).settings_sha256 != one, changed
    assert D.resolve(MP4, D.parse_settings(MP4, {"frame_end": 29}), target(version=2)).settings_sha256 != one  # another pin
    assert D.resolve(MP4, D.parse_settings(MP4, {"frame_end": 29}), target(source_digest="e" * 64)).settings_sha256 != one
    assert D.resolve(MP4, D.parse_settings(MP4, {"frame_end": 29}), target(engine_version="4.0.535")).settings_sha256 != one
    # a setting that does not change the pixels (concurrency) is not part of the identity of the render
    assert D.resolve(MP4, D.parse_settings(MP4, {"frame_end": 29, "concurrency": 2}), target()).settings_sha256 == one


@pytest.mark.parametrize("fmt,raw,needle", [
    (MP4, [], "must be an object"), (MP4, {"codec": "vp9"}, "unknown settings"), (MP4, {"frame": 3}, "do not apply"),
    (STILL, {"frame_start": 1}, "do not apply"), (PDF, {"frame": 1}, "do not apply"), (MP4, {"scene_id": "x"}, "scene id"),
    (MP4, {"scale": 3}, "scale must be"), (MP4, {"scale": True}, "scale must be"), (MP4, {"crf": 5}, "crf"), (MP4, {"crf": "23"}, "crf"),
    (MP4, {"concurrency": 3}, "concurrency"), (MP4, {"frame_start": -1}, "frame_start"), (MP4, {"frame_start": 1.5}, "frame_start"),
    (MP4, {"frame_start": 9, "frame_end": 3}, "before"), (PDF, {"frames": []}, "frames must be"), (PDF, {"frames": ["a"]}, "frames must be"),
    (PDF, {"frames": list(range(25))}, "frames must be")])
def test_malformed_settings_are_refused_with_a_reason(fmt, raw, needle):
    with pytest.raises(RenderError) as refused:
        D.parse_settings(fmt, raw)
    assert refused.value.code is C.INVALID and needle in refused.value.detail and refused.value.status == 400


@pytest.mark.parametrize("fmt,settings,needle", [
    (MP4, {"frame_end": 90}, "outside the scene"), (MP4, {"frame_start": 90}, "outside the scene"), (STILL, {"frame": 90}, "outside the scene"),
    (PDF, {"frames": [0, 90]}, "outside the scene"), (PDF, {"frames": [1, 1]}, "distinct"), (MP4, {"scale": 2.0}, None)])
def test_ranges_are_checked_against_the_declared_duration(fmt, settings, needle):
    if needle is None:
        assert D.resolve(fmt, D.parse_settings(fmt, settings), target()).out_width == 2560
        return
    with pytest.raises(RenderError) as refused:
        D.resolve(fmt, D.parse_settings(fmt, settings), target())
    assert needle in refused.value.detail


def test_the_output_size_the_frame_count_and_the_mp4_parity_are_bounded():
    with pytest.raises(RenderError) as huge:
        D.resolve(MP4, D.parse_settings(MP4, {"scale": 2.0}), target(width=2000, height=1200))
    assert "exceeds" in huge.value.detail
    with pytest.raises(RenderError) as long:
        D.resolve(MP4, D.parse_settings(MP4, {}), target(duration_in_frames=D.MAX_RENDER_FRAMES + 1))
    assert "exceed the bound" in long.value.detail
    assert D.resolve(MP4, D.parse_settings(MP4, {"frame_start": 10, "frame_end": 10 + D.MAX_RENDER_FRAMES - 1}),
                     target(duration_in_frames=D.MAX_RENDER_FRAMES + 20)).frames_total == D.MAX_RENDER_FRAMES
    with pytest.raises(RenderError) as odd:
        D.resolve(MP4, D.parse_settings(MP4, {}), target(width=1281))
    assert "even" in odd.value.detail
    assert D.resolve(STILL, D.parse_settings(STILL, {}), target(width=1281)).out_width == 1281  # an image may be odd


def test_chrome_memory_is_bounded_by_pixels_times_tabs_and_one_tab_is_the_default():
    assert (D.DEFAULT_CONCURRENCY, D.MAX_CONCURRENCY) == (1, 2) and D.parse_settings(MP4, None).concurrency == 1
    D.resolve(MP4, D.parse_settings(MP4, {"concurrency": 2}), target())  # 1280x720 x 2 tabs: fine
    D.resolve(MP4, D.parse_settings(MP4, {"scale": 2.0}), target(width=1920, height=1080))  # 3840x2160 x 1 tab: the largest allowed
    with pytest.raises(RenderError) as refused:
        D.resolve(MP4, D.parse_settings(MP4, {"scale": 2.0, "concurrency": 2}), target(width=1920, height=1080))
    assert "tabs" in refused.value.detail and "memory" in refused.value.detail
    with pytest.raises(RenderError):
        D.resolve(STILL, D.parse_settings(STILL, {"scale": 2.0, "concurrency": 2}), target(width=1920, height=1080))


def test_the_deadline_grows_with_the_work_and_is_capped():
    short = D.resolve(MP4, D.parse_settings(MP4, {"frame_end": 9}), target())
    full = D.resolve(MP4, D.parse_settings(MP4, {}), target(duration_in_frames=D.MAX_RENDER_FRAMES))
    assert short.timeout_s == D.TIMEOUT_BASE_S + 10 and full.timeout_s == min(D.TIMEOUT_CAP_S, D.TIMEOUT_BASE_S + D.MAX_RENDER_FRAMES)
    assert D.TIMEOUT_CAP_S == 3600


@pytest.mark.parametrize("fmt,settings", [(MP4, {"frame_end": 59}), (STILL, {"frame": 7}), (PDF, {"frames": [0, 30, 60]})])
def test_the_recorded_metadata_fits_the_registry_and_names_the_origin_of_the_pixels(fmt, settings):
    resolved = D.resolve(fmt, D.parse_settings(fmt, settings), target())
    meta = {**resolved.to_metadata(), "render_format": fmt.value, "render_job_id": "rj_" + "a" * 12, "render_engine_drift": False,
            "render_output_sha256": "f" * 64, "render_verified_by": "ffprobe", "render_browser": "chrome 154.0.8037.99", "render_egress_denied": 4,
            "render_wall_ms": 12345, "render_pages": 3}
    spec = RENDERS[fmt]
    artifact = new_artifact(kind=spec.kind, source="presentation.studio", now=__import__("datetime").datetime(2026, 10, 10, tzinfo=__import__("datetime").timezone.utc),
                            payload_name=spec.payload_name, mime_type=spec.mime_type, metadata=meta)
    assert artifact.metadata["render_flat"] is True and artifact.metadata["render_scene_id"] == SCENE_ID
    assert artifact.metadata["render_prefab_id"] and artifact.metadata["render_prefab_version"] == 1 and len(meta) <= 32
    assert ("render_codec" in meta) is (fmt is MP4) and ("render_frames" in meta) is (fmt is not MP4)


def test_error_detail_never_carries_a_machine_path():
    text = D.clean_detail("Error: ENOENT C:\\Users\\Clarice\\AppData\\x.js and /home/me/.jarvis/data/y.db and \\\\srv\\share\\z")
    assert "Clarice" not in text and "/home/me" not in text and "srv" not in text and text.count("<path>") == 3
    assert len(D.clean_detail("x" * 1000)) == 300


def test_every_error_code_has_a_stable_prefixed_value_and_a_status():
    for code in C:
        assert code.value.startswith("presentation_render_")
    assert RenderError(C.QUEUE_FULL).status == 429 and RenderError(C.UNKNOWN_JOB).status == 404 and RenderError(C.DISK_LOW).status == 507
    assert RenderError(C.UNAVAILABLE).status == 503 and RenderError(C.INVALID).status == 400 and RenderError(C.FAILED).status == 409
    assert D.JobState.COMPLETE.terminal and not D.JobState.FINALIZING.terminal and D.JobState.CANCELLED.terminal


# ------------------------------------------------------------------ output bytes


def png(width=64, height=32) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    raw = b"".join(b"\x00" + b"\x10\x20\x30" * width for _ in range(height))
    return O.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def jpeg(width=64, height=32, components=3, extra: bytes = b"") -> bytes:
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 8 + 3 * components, 8, height, width, components) + b"\x01\x11\x00" * components
    return b"\xff\xd8" + extra + sof + b"\xff\xda\x00\x02\xff\xd9"


def test_png_and_jpeg_sizes_are_read_from_their_headers_and_lies_are_refused():
    assert O.png_size(png(64, 32)) == (64, 32) and O.jpeg_info(jpeg(80, 40)) == (80, 40, 3)
    assert O.jpeg_info(jpeg(10, 10, extra=b"\xff\xe0\x00\x04ab"))[:2] == (10, 10)  # an APP0 segment before the frame header
    for bad in (b"", b"\x89PNG", b"not a png at all" * 4, png()[:20]):
        with pytest.raises(O.OutputProblem):
            O.png_size(bad)
    for bad in (b"", b"\xff\xd8", b"GIF89a....", b"\xff\xd8\xff\xe0\x00\x04ab"):
        with pytest.raises(O.OutputProblem):
            O.jpeg_info(bad)


def test_the_pdf_has_one_page_per_image_a_valid_xref_and_no_dates_or_ids():
    pages = [jpeg(1280, 720), jpeg(1280, 720), jpeg(640, 360, components=1)]
    document, sizes = O.build_pdf(pages)
    assert sizes == [(1280, 720), (1280, 720), (640, 360)] and document.startswith(b"%PDF-1.4") and document.rstrip().endswith(b"%%EOF")
    assert O.pdf_page_count(document) == 3 and document.count(b"/Subtype /Image") == 3 and document.count(b"/Filter /DCTDecode") == 3
    assert b"/DeviceRGB" in document and b"/DeviceGray" in document and b"/MediaBox [0 0 960.0 540.0]" in document
    assert b"CreationDate" not in document and b"/ID" not in document  # deterministic: same pages, same bytes
    assert O.build_pdf(pages)[0] == document
    # every xref entry points at "<n> 0 obj"
    startxref = int(re.search(rb"startxref\n(\d+)\n", document).group(1))
    table = document[startxref:].split(b"\n")
    count = int(table[1].split()[1])
    offsets = [int(line.split()[0]) for line in table[3:2 + count]]
    assert len(offsets) == count - 1
    for number, offset in enumerate(offsets, 1):
        assert document[offset:].startswith(b"%d 0 obj" % number)
    assert b"not editable" in document


def test_the_pdf_refuses_what_it_cannot_embed():
    with pytest.raises(O.OutputProblem):
        O.build_pdf([])
    with pytest.raises(O.OutputProblem):
        O.build_pdf([b"not a jpeg"])
    with pytest.raises(O.OutputProblem):
        O.build_pdf([jpeg(components=4)])
    with pytest.raises(O.OutputProblem):
        O.pdf_page_count(b"%PDF-1.4 truncated")


def test_ffprobe_facts_require_exactly_one_h264_style_video_stream_with_a_size_and_a_duration():
    facts = O.video_facts({"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720, "nb_frames": "60",
                                        "r_frame_rate": "30/1", "duration": "2.000000"}], "format": {"duration": "2.0"}})
    assert (facts.width, facts.height, facts.frames, facts.duration_ms, facts.codec, facts.fps) == (1280, 720, 60, 2000, "h264", 30.0)
    assert O.video_facts({"streams": [{"codec_type": "video", "codec_name": "h264", "width": 2, "height": 2}], "format": {"duration": "0.5"}}).duration_ms == 500
    for bad in ({}, {"streams": []}, {"streams": [{"codec_type": "audio"}]},
                {"streams": [{"codec_type": "video", "width": 2, "height": 2}]},
                {"streams": [{"codec_type": "video", "width": 2, "height": 2, "duration": "x"}]},
                {"streams": [{"codec_type": "video", "width": 2, "height": 2, "duration": "1"}] * 2}):
        with pytest.raises(O.OutputProblem):
            O.video_facts(bad)


def test_headers_are_checked_per_format():
    O.check_header(MP4, b"\x00\x00\x00 ftypisom")
    O.check_header(STILL, O.PNG_SIGNATURE + b"..")
    O.check_header(PDF, b"%PDF-1.4")
    for fmt, head in ((MP4, b"\x00\x00\x00 moovisom"), (STILL, b"GIF89a......."), (PDF, b"<html>")):
        with pytest.raises(O.OutputProblem):
            O.check_header(fmt, head)


# ------------------------------------------------------------------ plan: a frozen package to the exact source of a render


@pytest.fixture
async def world(tmp_path):
    w = await PresentationWorld().open(tmp_path, runtime={"remotion_version": "4.0.534"})
    try:
        yield w
    finally:
        await w.close()


async def frozen_package(world, **options):
    pid, vid = await world.new_presentation(**options)
    snapshot = (await world.freeze(pid, vid))["artifact_id"]
    package = await world.packager.read_snapshot(snapshot)
    return package, pid, vid


async def test_the_plan_is_the_frozen_source_bytes_plus_two_generated_files(world):
    package, *_ = await frozen_package(world, props={"title": "A"})
    scene = choose_scene(package, None)
    files, props = plan_files(package, scene)
    frozen = {p.split("/", 3)[3]: d for p, d in package.files.items() if p.startswith("prefabs/") and p.split("/", 3)[3].startswith(("src/", "public/"))}
    assert {path: files[path] for path in frozen} == frozen
    assert set(files) - set(frozen) == {"studio-root.tsx", "package.json"}
    assert props == {"title": "A", "accent": "#3366ff"}  # frozen default of the schema, then the frozen instance value
    assert (scene.composition_id, scene.width, scene.height, scene.fps, scene.duration_in_frames) == ("Scene", 1280, 720, 30, 90)
    assert scene.engine_version == ENGINE.version and scene.source_digest


async def test_the_plan_reads_nothing_but_the_package(world):
    package, pid, vid = await frozen_package(world, props={"title": "Figé"})
    view = await world.studio.get(pid)
    variant = view.variants[0].to_document()
    scenes = variant["scenes"]
    scenes[0]["props"] = {"title": "Édité après"}
    await world.studio.save_variant(pid, vid, {"expected_revision": variant["revision"], "title": "x", "scenes": scenes,
                                                "art_direction_id": None, "score_id": None})
    scene = choose_scene(package, None)
    assert render_props(package, scene)["title"] == "Figé"  # the live edit does not reach a render of the frozen package


async def test_live_data_copied_at_freeze_time_is_laid_under_public_live(world):
    from jarvis.domain.presentation_live_refs import LIVE_REFS_FORMAT, LIVE_REFS_PATH
    from jarvis.domain.board_memory import BoardMemoryPath
    from jarvis.ports.board_memory import WriteMode
    world.memory.write("default", BoardMemoryPath.parse("notes/a.md"), "# Note\n", mode=WriteMode.REPLACE)
    files = {"src/Scene.tsx": "export default function Scene(){return null}\n",
             LIVE_REFS_PATH: json.dumps({"format": LIVE_REFS_FORMAT, "refs": [{"name": "note", "ref": "board:default/memory/notes/a.md"}]})}
    package, *_ = await frozen_package(world, files=files)
    planned, _ = plan_files(package, choose_scene(package, None))
    assert planned["public/live/note.md"] == b"# Note\n"


async def test_a_package_without_defaults_still_renders_with_the_instance_values(world):
    package, *_ = await frozen_package(world, props={"title": "B"})
    scene = choose_scene(package, None)
    row = next(r for r in package.manifest["prefabs"] if r["prefab_id"] == scene.prefab_id)
    assert row["props_defaults"] == {"title": "Bonjour", "accent": "#3366ff"}
    row.pop("props_defaults")  # an older snapshot, frozen before the defaults were recorded
    assert render_props(package, scene) == {"title": "B"}


DATA_SCHEMA = {"type": "object", "properties": {"body": {"type": "string", "default": "corps par défaut", "max_length": 200},
                                                "figure": {"type": "integer", "default": 7, "min": 0, "max": 100}}}


async def test_the_data_input_travels_with_the_props_into_a_render(world):
    """Slice 22 (release journey): an authored scene reads `props.data.*`; the render must hand it the same `data` the Player does (frozen
    manifest defaults under the frozen instance values), or the export of every authored deck fails with a TypeError in the browser."""

    package, *_ = await frozen_package(world, props={"title": "A"}, data_schema=DATA_SCHEMA, data={"body": "texte figé"})
    scene = choose_scene(package, None)
    row = next(r for r in package.manifest["prefabs"] if r["prefab_id"] == scene.prefab_id)
    assert row["data_defaults"] == {"body": "corps par défaut", "figure": 7}
    assert render_props(package, scene) == {"title": "A", "accent": "#3366ff", "data": {"body": "texte figé", "figure": 7}}
    _, props = plan_files(package, scene)
    assert props["data"]["body"] == "texte figé"


async def test_a_scene_without_data_gets_no_data_key_and_an_older_snapshot_still_renders(world):
    package, *_ = await frozen_package(world, props={"title": "A"})
    scene = choose_scene(package, None)
    assert "data" not in render_props(package, scene), "a scene that declares no data input is rendered exactly as before"
    row = next(r for r in package.manifest["prefabs"] if r["prefab_id"] == scene.prefab_id)
    row.pop("data_defaults", None)  # a snapshot frozen before the data defaults were recorded
    assert "data" not in render_props(package, scene)


async def test_the_frozen_source_is_revalidated_by_todays_guards(world, monkeypatch):
    from jarvis.domain import remotion_source as rsrc
    package, *_ = await frozen_package(world)
    scene = choose_scene(package, None)
    monkeypatch.setattr(rsrc, "SOURCE_GUARDS", (lambda source: ["a guard added after the freeze"],))
    with pytest.raises(RenderError) as refused:
        plan_files(package, scene)
    assert refused.value.code is C.SOURCE_REFUSED and "added after the freeze" in refused.value.detail


async def test_a_package_that_is_not_remotion_has_nothing_to_render(world, tmp_path):
    package, *_ = await frozen_package(world)
    forged = type(package)({**package.manifest, "prefabs": [{**package.manifest["prefabs"][0], "kind": "html"}]}, package.files)
    with pytest.raises(RenderError) as refused:
        choose_scene(forged, None)
    assert refused.value.code is C.UNKNOWN_SCENE and "0 renderable" in refused.value.detail
    assert remotion_pins(forged) == ({}, {})


async def test_a_damaged_source_block_is_a_snapshot_error(world):
    package, *_ = await frozen_package(world)
    key = next(path for path in package.files if path.endswith("/source.json"))
    broken = type(package)(package.manifest, {**package.files, key: b"{not json"})
    with pytest.raises(RenderError) as refused:
        choose_scene(broken, None)
    assert refused.value.code is C.SNAPSHOT_INVALID
    assert read_package  # the package format itself is verified by read_package (Slice 09), not here
