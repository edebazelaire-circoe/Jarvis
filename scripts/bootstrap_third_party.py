#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
THIRD_PARTY = ROOT / "third_party"
LOCK_PATH = THIRD_PARTY / "LOCK.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_sha256(root: Path, *, ignore: set[str] | None = None) -> str:
    """Hash file names + contents deterministically for post-install integrity."""
    ignored = ignore or set()
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel in ignored:
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def git_blob_sha1(data: bytes) -> str:
    prefix = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(prefix + data).hexdigest()


def verify_sha512_integrity(data: bytes, expected_base64: str) -> None:
    actual = base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")
    if actual != expected_base64:
        raise RuntimeError(f"SHA-512 integrity mismatch: {actual}")


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Jarvis-V1-bootstrap/1"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def _safe_relative(name: str) -> Path:
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"Unsafe archive path: {name}")
    return Path(*pure.parts)


def extract_zip_snapshot(data: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist() if n and not n.endswith("/")]
        if not names:
            raise RuntimeError("Empty upstream archive")
        prefixes = {PurePosixPath(n).parts[0] for n in names}
        if len(prefixes) != 1:
            raise RuntimeError("Unexpected archive layout")
        prefix = next(iter(prefixes))
        for info in archive.infolist():
            if info.is_dir():
                continue
            parts = PurePosixPath(info.filename).parts
            if not parts or parts[0] != prefix:
                raise RuntimeError("Unexpected archive prefix")
            rel = _safe_relative(PurePosixPath(*parts[1:]).as_posix())
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def extract_npm_tgz(data: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != "package":
                continue
            rel = _safe_relative(PurePosixPath(*parts[1:]).as_posix())
            source = archive.extractfile(member)
            if source is None:
                continue
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())


def verify_git_blobs(root: Path, expected: dict[str, str]) -> None:
    for rel, wanted in expected.items():
        path = root / rel
        data = path.read_bytes()
        actual = git_blob_sha1(data)
        if actual != wanted:
            raise RuntimeError(f"Pinned upstream blob mismatch for {rel}: {actual} != {wanted}")


def patch_stage_html(text: str) -> str:
    replacements = {
        "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js": "/vendor/three/build/three.module.js",
        "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/": "/vendor/three/examples/jsm/",
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs": "/vendor/mediapipe/vision_bundle.mjs",
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm": "/vendor/mediapipe/wasm",
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task": "/vendor/models/hand_landmarker.task",
    }
    for old, new in replacements.items():
        if old not in text:
            raise RuntimeError(f"Barehands stage upstream shape changed; missing {old}")
        text = text.replace(old, new)
    if "cdn.jsdelivr.net" in text or "storage.googleapis.com/mediapipe-models" in text:
        raise RuntimeError("Runtime remote assets remain after Barehands patch")
    return text


def patch_server_py(text: str) -> str:
    if "import json\n" not in text or "import urllib.parse\n" not in text:
        raise RuntimeError("Barehands server imports changed upstream")
    text = text.replace("import json\n", "import hmac\nimport json\nimport os\n", 1)
    here = "HERE = Path(__file__).resolve().parent\n"
    if here not in text:
        raise RuntimeError("Barehands HERE marker changed upstream")
    text = text.replace(
        here,
        here + 'JARVIS_BOARD_TOKEN = os.environ.get("JARVIS_BOARD_TOKEN", "")\n',
        1,
    )

    end_marker = "        super().end_headers()\n"
    if end_marker not in text:
        raise RuntimeError("Barehands end_headers changed upstream")
    headers = '''        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; worker-src 'self' blob:; connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")\n        self.send_header("X-Content-Type-Options", "nosniff")\n        self.send_header("Referrer-Policy", "no-referrer")\n        self.send_header("Cross-Origin-Resource-Policy", "same-origin")\n'''
    text = text.replace(end_marker, headers + end_marker, 1)

    cmd_marker = '''        if self.path == "/cmd":\n            try:\n'''
    if cmd_marker not in text:
        raise RuntimeError("Barehands /cmd marker changed upstream")
    guard = '''        if self.path == "/cmd":\n            provided = self.headers.get("X-Jarvis-Token", "")\n            if not JARVIS_BOARD_TOKEN or not hmac.compare_digest(provided, JARVIS_BOARD_TOKEN):\n                self._json({"error": "unauthorized"}, 401)\n                return\n            origin = self.headers.get("Origin")\n            if origin:\n                host = urllib.parse.urlparse(origin).hostname\n                if host not in {"127.0.0.1", "localhost", "::1"}:\n                    self._json({"error": "forbidden origin"}, 403)\n                    return\n            try:\n'''
    text = text.replace(cmd_marker, guard, 1)
    return text


def harden_barehands(root: Path, lock: dict) -> dict[str, str]:
    expected = lock["runtime_sources"]["barehands"]["critical_git_blobs"]
    verify_git_blobs(root, expected)
    stage_path = root / "stage.html"
    server_path = root / "server.py"
    stage_path.write_text(patch_stage_html(stage_path.read_text(encoding="utf-8")), encoding="utf-8")
    server_path.write_text(patch_server_py(server_path.read_text(encoding="utf-8")), encoding="utf-8")
    return {
        "patched_stage_sha256": sha256_bytes(stage_path.read_bytes()),
        "patched_server_sha256": sha256_bytes(server_path.read_bytes()),
    }


def _install_snapshot(name: str, meta: dict, destination: Path) -> str:
    url = f"{meta['repository']}/archive/{meta['commit']}.zip"
    archive = _download(url)
    with tempfile.TemporaryDirectory(prefix=f"jarvis-{name}-") as tmp:
        temp_root = Path(tmp) / name
        extract_zip_snapshot(archive, temp_root)
        verify_git_blobs(temp_root, meta.get("critical_git_blobs", {}))
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(temp_root, destination)
    return sha256_bytes(archive)


def install(force: bool = False) -> dict:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    state_path = THIRD_PARTY / "INSTALL-STATE.json"
    if state_path.exists() and not force:
        raise RuntimeError("third_party already bootstrapped; pass --force to replace pinned snapshots")

    barehands = THIRD_PARTY / "barehands"
    visualizer = THIRD_PARTY / "ai-visualizer"
    archive_hashes = {}
    archive_hashes["barehands"] = _install_snapshot(
        "barehands", lock["runtime_sources"]["barehands"], barehands
    )
    archive_hashes["ai-visualizer"] = _install_snapshot(
        "ai-visualizer", lock["runtime_sources"]["ai-visualizer"], visualizer
    )

    assets = lock["browser_assets"]
    three_data = _download(assets["three"]["url"])
    verify_sha512_integrity(three_data, assets["three"]["integrity_sha512_base64"])
    mp_data = _download(assets["mediapipe_tasks_vision"]["url"])
    verify_sha512_integrity(mp_data, assets["mediapipe_tasks_vision"]["integrity_sha512_base64"])
    model = _download(assets["hand_landmarker_model"]["url"])
    model_hash = sha256_bytes(model)
    if model_hash != assets["hand_landmarker_model"]["sha256"]:
        raise RuntimeError(f"Hand-landmarker SHA-256 mismatch: {model_hash}")

    vendor = barehands / "vendor"
    if vendor.exists():
        shutil.rmtree(vendor)
    extract_npm_tgz(three_data, vendor / "three")
    extract_npm_tgz(mp_data, vendor / "mediapipe")
    (vendor / "models").mkdir(parents=True, exist_ok=True)
    (vendor / "models" / "hand_landmarker.task").write_bytes(model)

    patch_hashes = harden_barehands(barehands, lock)
    state = {
        "schema": 1,
        "lock_sha256": sha256_bytes(LOCK_PATH.read_bytes()),
        "upstream_archive_sha256": archive_hashes,
        "browser_asset_sha256": {
            "three_tgz": sha256_bytes(three_data),
            "mediapipe_tasks_vision_tgz": sha256_bytes(mp_data),
            "hand_landmarker_model": model_hash,
        },
        "installed_tree_sha256": {
            "three": tree_sha256(vendor / "three"),
            "mediapipe": tree_sha256(vendor / "mediapipe"),
            "ai_visualizer": tree_sha256(visualizer),
        },
        **patch_hashes,
    }
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state


def verify_installed() -> dict:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    state_path = THIRD_PARTY / "INSTALL-STATE.json"
    if not state_path.is_file():
        raise RuntimeError("third_party/INSTALL-STATE.json missing")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("lock_sha256") != sha256_bytes(LOCK_PATH.read_bytes()):
        raise RuntimeError("Third-party lock changed since bootstrap")
    barehands = THIRD_PARTY / "barehands"
    visualizer = THIRD_PARTY / "ai-visualizer"
    if not (barehands / "server.py").is_file() or not (visualizer / "server.py").is_file():
        raise RuntimeError("Runtime snapshot missing")
    if sha256_bytes((barehands / "server.py").read_bytes()) != state.get("patched_server_sha256"):
        raise RuntimeError("Patched Barehands server changed")
    if sha256_bytes((barehands / "stage.html").read_bytes()) != state.get("patched_stage_sha256"):
        raise RuntimeError("Patched Barehands stage changed")
    if sha256_bytes((barehands / "vendor/models/hand_landmarker.task").read_bytes()) != lock["browser_assets"]["hand_landmarker_model"]["sha256"]:
        raise RuntimeError("Hand-landmarker model changed")
    installed_trees = state.get("installed_tree_sha256", {})
    expected_three = installed_trees.get("three")
    expected_mediapipe = installed_trees.get("mediapipe")
    expected_visualizer = installed_trees.get("ai_visualizer")
    if not all((expected_three, expected_mediapipe, expected_visualizer)):
        raise RuntimeError("Installed third-party tree hashes missing")
    if tree_sha256(barehands / "vendor/three") != expected_three:
        raise RuntimeError("Vendored Three.js tree changed")
    if tree_sha256(barehands / "vendor/mediapipe") != expected_mediapipe:
        raise RuntimeError("Vendored MediaPipe tree changed")
    # The launcher writes this local user/runtime config after bootstrap; it is
    # intentionally excluded while every shipped executable/static file stays
    # covered by the installation hash.
    if tree_sha256(visualizer, ignore={"ai-visualizer.json"}) != expected_visualizer:
        raise RuntimeError("ai-visualizer runtime tree changed")
    stage = (barehands / "stage.html").read_text(encoding="utf-8")
    if "cdn.jsdelivr.net" in stage or "storage.googleapis.com/mediapipe-models" in stage:
        raise RuntimeError("Remote runtime asset URL reintroduced")
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="Install and harden pinned Jarvis V1 third-party components")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    state = verify_installed() if args.verify else install(force=args.force)
    print(json.dumps(state, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
