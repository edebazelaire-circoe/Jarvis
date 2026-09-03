from __future__ import annotations

import io
import json
import tarfile

import pytest
from pathlib import Path

from scripts.bootstrap_third_party import (
    _safe_relative,
    git_blob_sha1,
    patch_server_py,
    patch_stage_html,
    tree_sha256,
    verify_sha512_integrity,
)


def test_lock_pins_exact_runtime_commits():
    lock = json.loads(Path("third_party/LOCK.json").read_text(encoding="utf-8"))
    assert lock["runtime_sources"]["barehands"]["commit"] == "eb23bed2d772f9d5a24de26fb92f46c3c76d69cf"
    assert lock["runtime_sources"]["ai-visualizer"]["commit"] == "6921e1d4b06bdd4a34c5264882d5257c4d5f70fd"
    assert len(lock["runtime_sources"]["barehands"]["critical_git_blobs"]["stage.html"]) == 40


def test_git_blob_hash_uses_git_object_format():
    # Official Git object hashing algorithm; known value for empty blob.
    assert git_blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def test_stage_patch_replaces_every_runtime_cdn_dependency():
    source = """
https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js
https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/
https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs
https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm
https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
"""
    patched = patch_stage_html(source)
    assert "cdn.jsdelivr.net" not in patched
    assert "storage.googleapis.com" not in patched
    assert "/vendor/three/build/three.module.js" in patched
    assert "/vendor/mediapipe/vision_bundle.mjs" in patched
    assert "/vendor/models/hand_landmarker.task" in patched


def test_server_patch_requires_session_token_origin_and_csp():
    source = '''import json\nimport urllib.parse\nfrom pathlib import Path\nHERE = Path(__file__).resolve().parent\nclass Handler:\n    def end_headers(self):\n        super().end_headers()\n    def do_POST(self):\n        if self.path == "/cmd":\n            try:\n                pass\n            except Exception:\n                pass\n'''
    patched = patch_server_py(source)
    assert "hmac.compare_digest" in patched
    assert "X-Jarvis-Token" in patched
    assert "forbidden origin" in patched
    assert "Content-Security-Policy" in patched
    assert "connect-src 'self'" in patched
    assert 'JARVIS_BOARD_TOKEN = os.environ.get("JARVIS_BOARD_TOKEN", "")' in patched


def test_archive_path_traversal_rejected():
    with pytest.raises(RuntimeError):
        _safe_relative("../escape")
    with pytest.raises(RuntimeError):
        _safe_relative("folder/../../escape")
    assert _safe_relative("folder/ok.txt").as_posix() == "folder/ok.txt"


def test_sha512_integrity_fails_closed():
    with pytest.raises(RuntimeError):
        verify_sha512_integrity(b"tampered", "AAAAAAAA")


def test_tree_hash_detects_executable_asset_tampering(tmp_path):
    root = tmp_path / "vendor"
    root.mkdir()
    (root / "a.js").write_text("one", encoding="utf-8")
    before = tree_sha256(root)
    (root / "a.js").write_text("two", encoding="utf-8")
    assert tree_sha256(root) != before


def test_tree_hash_can_exclude_generated_runtime_config(tmp_path):
    root = tmp_path / "visualizer"
    root.mkdir()
    (root / "index.html").write_text("static", encoding="utf-8")
    (root / "ai-visualizer.json").write_text("first", encoding="utf-8")
    before = tree_sha256(root, ignore={"ai-visualizer.json"})
    (root / "ai-visualizer.json").write_text("second", encoding="utf-8")
    assert tree_sha256(root, ignore={"ai-visualizer.json"}) == before


def _zip_snapshot(root_name: str, files: dict[str, bytes]) -> bytes:
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for rel, data in files.items():
            archive.writestr(f"{root_name}/{rel}", data)
    return out.getvalue()


def _npm_tgz(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for rel, data in files.items():
            info = tarfile.TarInfo(f"package/{rel}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def test_full_synthetic_bootstrap_verify_and_tamper_detection(tmp_path, monkeypatch):
    import base64
    import hashlib
    import scripts.bootstrap_third_party as bootstrap

    bare_server = b'''import json\nimport urllib.parse\nfrom pathlib import Path\nHERE = Path(__file__).resolve().parent\nclass Handler:\n    def end_headers(self):\n        super().end_headers()\n    def do_POST(self):\n        if self.path == "/cmd":\n            try:\n                pass\n            except Exception:\n                pass\n'''
    bare_stage = b'''<script type="importmap">\nhttps://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js\nhttps://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/\nhttps://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs\nhttps://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm\nhttps://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task\n</script>'''
    visualizer_server = b"print('visualizer')\n"
    bare_zip = _zip_snapshot("barehands-deadbeef", {"server.py": bare_server, "stage.html": bare_stage, "LICENSE": b"AGPL"})
    visualizer_zip = _zip_snapshot("visualizer-feedface", {"server.py": visualizer_server, "index.html": b"face", "LICENSE": b"AGPL"})
    three_tgz = _npm_tgz({
        "build/three.module.js": b"export const THREE = 1;",
        "examples/jsm/loaders/GLTFLoader.js": b"export class GLTFLoader {}",
        "examples/jsm/environments/RoomEnvironment.js": b"export class RoomEnvironment {}",
    })
    mediapipe_tgz = _npm_tgz({
        "vision_bundle.mjs": b"export const FilesetResolver = {};",
        "wasm/vision_wasm_internal.wasm": b"wasm",
    })
    model = b"hand-model-fixture"

    def b64_sha512(data: bytes) -> str:
        return base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")

    lock = {
        "schema": 1,
        "runtime_sources": {
            "barehands": {
                "repository": "https://example.test/barehands",
                "commit": "deadbeef",
                "critical_git_blobs": {
                    "server.py": git_blob_sha1(bare_server),
                    "stage.html": git_blob_sha1(bare_stage),
                },
            },
            "ai-visualizer": {
                "repository": "https://example.test/visualizer",
                "commit": "feedface",
                "critical_git_blobs": {"server.py": git_blob_sha1(visualizer_server)},
            },
        },
        "browser_assets": {
            "three": {"url": "https://assets.test/three.tgz", "integrity_sha512_base64": b64_sha512(three_tgz)},
            "mediapipe_tasks_vision": {"url": "https://assets.test/mp.tgz", "integrity_sha512_base64": b64_sha512(mediapipe_tgz)},
            "hand_landmarker_model": {"url": "https://assets.test/hand.task", "sha256": hashlib.sha256(model).hexdigest()},
        },
    }
    third_party = tmp_path / "third_party"
    third_party.mkdir()
    lock_path = third_party / "LOCK.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(bootstrap, "THIRD_PARTY", third_party)
    monkeypatch.setattr(bootstrap, "LOCK_PATH", lock_path)

    downloads = {
        "https://example.test/barehands/archive/deadbeef.zip": bare_zip,
        "https://example.test/visualizer/archive/feedface.zip": visualizer_zip,
        "https://assets.test/three.tgz": three_tgz,
        "https://assets.test/mp.tgz": mediapipe_tgz,
        "https://assets.test/hand.task": model,
    }
    monkeypatch.setattr(bootstrap, "_download", lambda url: downloads[url])

    state = bootstrap.install()
    assert state["installed_tree_sha256"]["three"]
    assert "cdn.jsdelivr.net" not in (third_party / "barehands" / "stage.html").read_text(encoding="utf-8")
    assert "X-Jarvis-Token" in (third_party / "barehands" / "server.py").read_text(encoding="utf-8")
    assert bootstrap.verify_installed()["lock_sha256"] == state["lock_sha256"]

    (third_party / "barehands" / "vendor" / "three" / "build" / "three.module.js").write_text(
        "tampered", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="Three.js tree changed"):
        bootstrap.verify_installed()
