"""Références vivantes d'une scène et paquet autonome : domaine pur (Remotion Slice 09).

Contrat : `docs/presentation-live-refs.md`, `docs/presentation-artifacts.md`. Aucune E/S ici.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from jarvis.domain import presentation_live_refs as lr
from jarvis.domain import presentation_snapshot_package as pkg
from tests.fakes.remotion_scene import PNG_1X1

ART = "jart_" + "a" * 32
GOOD_MEMORY = "board:board_abc/memory/notes/a.md"
GOOD_ARTIFACT = f"board:default/artifact/{ART}"


def declaration(*refs: tuple[str, str], **extra) -> bytes:
    doc = {"format": lr.LIVE_REFS_FORMAT, "refs": [{"name": n, "ref": r} for n, r in refs], **extra}
    return json.dumps(doc).encode()


def test_a_memory_and_an_artifact_reference_parse_and_print_back():
    memory = lr.parse_live_ref("notes", GOOD_MEMORY)
    artifact = lr.parse_live_ref("photo", GOOD_ARTIFACT)
    assert (memory.kind, memory.board_id, memory.locator) == ("memory", "board_abc", "notes/a.md")
    assert (artifact.kind, artifact.board_id, artifact.locator) == ("artifact", "default", ART)
    assert str(memory) == GOOD_MEMORY and str(artifact) == GOOD_ARTIFACT


@pytest.mark.parametrize("value", [
    "board:default/memory/../secrets.md", "board:default/memory/a/../../b.md", "board:default/memory//etc/passwd",
    "board:default/memory/\\\\host\\share\\a.md", "board:default/memory/C:/Windows/win.ini", "board:default/memory/a\\b.md",
    "board:default/memory/con.txt", "board:default/memory/", "board:default/memory/" + "a/" * 200 + "b.md",
    "file:///etc/passwd", "http://example.com/a.png", "C:\\Users\\x\\a.png", "/etc/passwd", "../a.png", "board:default",
    "board:/memory/a.md", "board:BOARD_X/memory/a.md", "board:other/memory/a.md", "board:default/disk/a.md",
    "board:default/artifact/not-an-artifact", "board:default/artifact/jart_../x", None, 12, "",
])
def test_a_path_escape_or_a_foreign_scheme_is_refused_before_any_read(value):
    with pytest.raises(lr.LiveRefError) as caught:
        lr.parse_live_ref("x", value)
    assert caught.value.code is lr.LiveRefErrorCode.INVALID


@pytest.mark.parametrize("value", ["presentation:pst_" + "a" * 32, f"board:default/artifact/jart_ps_{'a' * 32}_{'b' * 32}_p1_v1_a1"])
def test_a_presentation_or_a_snapshot_is_never_a_board_item(value):
    with pytest.raises(lr.LiveRefError) as caught:
        lr.parse_live_ref("x", value)
    assert caught.value.code is lr.LiveRefErrorCode.CROSS_PRESENTATION


@pytest.mark.parametrize("name", ["Notes", "1a", "a-b", "", "a" * 41, "é", None])
def test_a_name_follows_the_sandbox_protocol_grammar(name):
    with pytest.raises(lr.LiveRefError):
        lr.parse_live_ref(name, GOOD_MEMORY)


def test_a_declaration_is_strict():
    refs = lr.parse_declaration(declaration(("notes", GOOD_MEMORY), ("photo", GOOD_ARTIFACT)))
    assert [r.name for r in refs] == ["notes", "photo"]
    assert lr.parse_declaration(declaration()) == ()
    bad = [
        declaration(("a", GOOD_MEMORY), ("a", GOOD_MEMORY)),                      # duplicate name
        declaration(**{"unknown": 1}),                                          # extra key
        declaration(*[(f"n{i}", GOOD_MEMORY) for i in range(lr.MAX_REFS_PER_SOURCE + 1)]),
        b"not json", b"\xff\xfe", b"[]", json.dumps({"format": "other/1", "refs": []}).encode(),
        json.dumps({"format": lr.LIVE_REFS_FORMAT, "refs": [{"name": "a", "ref": GOOD_MEMORY, "extra": 1}]}).encode(),
        json.dumps({"format": lr.LIVE_REFS_FORMAT, "refs": [{"name": "a"}]}).encode(),
        b" " * (lr.MAX_DECLARATION_BYTES + 1),
    ]
    for data in bad:
        with pytest.raises(lr.LiveRefError):
            lr.parse_declaration(data)


def resolved(name, state=lr.LiveRefState.OK, data=b"hello", mime="text/plain", message=""):
    ref = lr.parse_live_ref(name, GOOD_MEMORY)
    return lr.ResolvedLiveRef(ref, state, message, mime if data is not None else None, data,
                              None if data is None else pkg.sha256_hex(data))


def test_the_sandbox_only_gets_data_never_the_reference_the_board_or_a_path():
    big = b"x" * (lr.MAX_INLINE_TEXT_BYTES + 1)
    payload = lr.sandbox_payload({
        "small": resolved("small"), "long": resolved("long", data=big), "photo": resolved("photo", data=PNG_1X1, mime="image/png"),
        "gone": resolved("gone", lr.LiveRefState.MISSING, data=None, message="the artifact no longer exists")})
    assert payload["small"]["text"] == "hello" and "file" not in payload["small"]
    assert payload["long"]["file"] == "live/long.txt" and "text" not in payload["long"]
    assert payload["photo"]["file"] == "live/photo.png" and payload["photo"]["size"] == len(PNG_1X1)
    assert payload["gone"] == {"state": "missing", "message": "the artifact no longer exists"}
    text = json.dumps(payload)
    for leaked in ("board:", "board_abc", "notes/a.md", "memory", "\\\\", "C:"):
        assert leaked not in text
    assert len(text.encode()) < 64 * 1024  # fits the protocol's maxPropsBytes


def test_inline_text_is_bounded_in_total():
    items = {f"n{i}": resolved(f"n{i}", data=b"y" * lr.MAX_INLINE_TEXT_BYTES) for i in range(5)}
    payload = lr.sandbox_payload(items)
    assert sum("text" in v for v in payload.values()) == 2  # 48 KiB / 24 KiB
    assert all("text" in v or "file" in v for v in payload.values())


def test_signatures_are_checked_per_mime():
    assert lr.binary_signature_ok("image/png", PNG_1X1)
    assert not lr.binary_signature_ok("image/png", b"<svg onload=alert(1)>")
    assert not lr.binary_signature_ok("image/svg+xml", b"<svg/>")
    assert lr.binary_signature_ok("image/jpeg", b"\xff\xd8\xff\xe0" + b"0" * 12)
    assert lr.binary_signature_ok("image/gif", b"GIF89a" + b"0" * 10)


# ------------------------------------------------------------------ package


CORE = {"provenance": {"source_kind": "presentation"}, "frozen_at": "2026-10-09T10:00:00+00:00", "scenes": [],
        "prefabs": [], "live_refs": [{"prefab_id": "a.b", "version": 1, "name": "notes",
                                       "path": "prefabs/a.b/1/live/notes.md"}], "runtime": None}
FILES = {"presentation/presentation.json": b"{}", "prefabs/a.b/1/src/Scene.tsx": b"export default 1;",
         "prefabs/a.b/1/live/notes.md": b"# frozen"}


def zip_of(members: dict[str, bytes], *, symlink: str | None = None, encrypted: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, body in members.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            if name == symlink:
                info.external_attr = 0o120777 << 16
            archive.writestr(info, body)
    data = bytearray(buffer.getvalue())
    if encrypted:  # set the "encrypted" flag in every central directory header
        at = data.find(b"PK")
        while at != -1:
            data[at + 8] |= 0x1
            at = data.find(b"PK", at + 4)
    return bytes(data)


def test_a_package_round_trips_and_is_deterministic():
    first, second = pkg.build_package(CORE, FILES), pkg.build_package(CORE, dict(reversed(list(FILES.items()))))
    assert first == second
    opened = pkg.read_package(first)
    assert dict(opened.files) == FILES
    assert opened.live("a.b", 1, "notes") == b"# frozen" and opened.live("a.b", 1, "nope") is None
    assert opened.manifest["format"] == pkg.PACKAGE_FORMAT and opened.package_digest == pkg.digest_of(opened.manifest["files"])


def test_any_changed_byte_member_or_digest_is_refused():
    good = pkg.read_package(pkg.build_package(CORE, FILES))
    members = {pkg.MANIFEST_PATH: pkg.canonical_json(dict(good.manifest)), **FILES}
    assert pkg.read_package(zip_of(members)).package_digest == good.package_digest

    def refused(mutated: dict[str, bytes], **kw):
        with pytest.raises(lr.LiveRefError) as caught:
            pkg.read_package(zip_of(mutated, **kw))
        assert caught.value.code is lr.LiveRefErrorCode.PACKAGE_INVALID

    refused({**members, "prefabs/a.b/1/live/notes.md": b"# changed"})                       # a byte
    refused({**members, "extra.txt": b"x"})                                                  # a member not in the manifest
    refused({k: v for k, v in members.items() if k != "presentation/presentation.json"})     # a missing member
    refused({k: v for k, v in members.items() if k != pkg.MANIFEST_PATH})                    # no manifest
    forged = dict(good.manifest)
    forged["package_digest"] = "0" * 64
    refused({**members, pkg.MANIFEST_PATH: pkg.canonical_json(forged)})
    refused({**members, "../evil.txt": b"x"})
    refused({**members, "/abs.txt": b"x"})
    refused({**members, "a\\b.txt": b"x"})
    refused({**members, "C:/x.txt": b"x"})
    refused({**members, "CON": b"x"})
    refused(members, symlink="presentation/presentation.json")
    refused(members, encrypted=True)
    with pytest.raises(lr.LiveRefError):
        pkg.read_package(b"not a zip")


def test_case_duplicates_and_oversized_packages_are_refused():
    base = pkg.read_package(pkg.build_package(CORE, FILES))
    members = {pkg.MANIFEST_PATH: pkg.canonical_json(dict(base.manifest)), **FILES}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
        archive.writestr("PRESENTATION/presentation.json", b"{}")
    with pytest.raises(lr.LiveRefError):
        pkg.read_package(buffer.getvalue())
    with pytest.raises(lr.LiveRefError) as caught:
        pkg.build_package(CORE, {f"f{i}.txt": b"x" for i in range(pkg.MAX_PACKAGE_FILES)})
    assert caught.value.code is lr.LiveRefErrorCode.PACKAGE_TOO_LARGE
    with pytest.raises(lr.LiveRefError):
        pkg.build_package(CORE, {"../x": b"x"})
    with pytest.raises(lr.LiveRefError):
        pkg.build_package(CORE, {pkg.MANIFEST_PATH: b"x"})


def test_the_manifest_holds_no_absolute_path():
    manifest = pkg.read_package(pkg.build_package(CORE, FILES)).manifest
    text = json.dumps(dict(manifest))
    assert "\\\\" not in text and ":/" not in text.replace("T10:00:00", "")


@pytest.mark.parametrize("path", ["prefabs/a.b/1/src/CON.tsx", "prefabs/a.b/1/public/nul.png", "prefabs/a.b/1/lpt1",
                                  "prefabs/a.b/1/src/Com9.txt", "prefabs/a.b/1/src/a./x", "prefabs/a.b/1/src/a /x"])
def test_windows_device_names_and_odd_segments_are_refused(path):
    assert pkg.package_path_problem(path) is not None
    with pytest.raises(lr.LiveRefError):
        pkg.build_package(CORE, {path: b"x"})


def test_the_depth_limit_holds_the_slice_05_source_depth_plus_the_package_prefix():
    from jarvis.domain.remotion_source import MAX_DEPTH
    deepest = "prefabs/some.prefab.id/12/" + "/".join(["d"] * (MAX_DEPTH - 1)) + "/f.tsx"
    assert pkg.package_path_problem(deepest) is None and pkg.MAX_PATH_SEGMENTS >= MAX_DEPTH + 3 + 1
    assert pkg.package_path_problem("/".join(["d"] * (pkg.MAX_PATH_SEGMENTS + 1))) is not None
