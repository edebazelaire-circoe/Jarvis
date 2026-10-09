"""`docs/remotion-isolation.md` contre le code (Slice 06) : chaque règle, borne, directive et fichier cité existe et dit vrai."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.domain import remotion_isolation as iso
from jarvis.domain import remotion_sandbox as sb
from jarvis.domain import remotion_source as rs

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "remotion-isolation.md").read_text(encoding="utf-8")
SOURCE_DOC = (ROOT / "docs" / "remotion-source.md").read_text(encoding="utf-8")


def js_limits() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    script = f"process.stdout.write(JSON.stringify(require({json.dumps(str(ROOT / 'jarvis/runtime/remotion_sandbox_protocol.js'))}).LIMITS))"
    return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30).stdout)


def test_every_static_rule_code_is_documented_in_the_table():
    for rule in iso.MODULE_RULES:
        assert f"| `{rule.code}` |" in DOC, rule.code
    assert "`svg_*`" in DOC and all(rule.code.startswith("svg_") for rule in iso.SVG_RULES)
    for code in ("asset_signature", "archive_symlink", "archive_nested", "archive_path", "archive_ratio", "archive_size"):
        assert code in DOC, code


def test_the_documented_static_and_archive_bounds_are_the_code_bounds():
    assert f"`MAX_LINE_CHARS` = {iso.MAX_LINE_CHARS:,}".replace(",", " ") in DOC
    assert f"Au plus {iso.MAX_FINDINGS_PER_FILE} par fichier" in DOC
    assert f"plus de {iso.MAX_ARCHIVE_ENTRIES} entrées" in DOC and f"plus de {iso.MAX_ARCHIVE_BYTES // (1024 * 1024)} Mio extraits" in DOC
    assert f"> {iso.MAX_COMPRESSION_RATIO}:1" in DOC
    for suffix in iso.ARCHIVE_SUFFIXES:
        assert suffix.lstrip(".") in DOC, suffix


def test_the_documented_sandbox_contract_is_the_code_contract():
    csp = sb.page_csp("n" * 24, "http://127.77.0.1:17653")
    for directive in csp.replace("n" * 24, "<24 car. neufs par réponse>").replace("http://127.77.0.1:17653", "<origine de l'hôte>").split("; "):
        assert directive in DOC, directive
    assert f'sandbox="{sb.SANDBOX_VALUE}"' in DOC
    for token in sb.FORBIDDEN_SANDBOX_TOKENS & {"allow-same-origin", "allow-popups", "allow-forms", "allow-top-navigation", "allow-modals"}:
        assert token in DOC, token
    for name in ("X-Content-Type-Options: nosniff", "Referrer-Policy: no-referrer", "Cross-Origin-Resource-Policy: cross-origin",
                 "Cross-Origin-Opener-Policy: same-origin", "Access-Control-Allow-Origin: *", "Cache-Control: no-store"):
        assert name in DOC, name
    assert sb.FILE_CSP in DOC
    assert "/page/<scene-clé>/<host-clé>" in DOC and "/f/<clé>/scene.js" in DOC
    assert f"{sb.MAX_PATH_CHARS} caractères" in DOC


def test_the_documented_protocol_limits_are_the_js_limits():
    limits = js_limits()
    assert f"`silentMs` = {limits['silentMs'] // 1000} s" in DOC and f"`maxViolations` = {limits['maxViolations']}" in DOC
    assert f"`maxHeapMb` = {limits['maxHeapMb']}" in DOC and f"{limits['maxChildMessagesPerSecond']} messages par seconde" in DOC
    assert f"{limits['readyMs'] // 1000} s" in DOC and f"{limits['maxReportsPerSecond']} par seconde" in DOC
    assert f"props {limits['maxPropsBytes'] // 1024} Kio" in DOC and f"cadre -> hôte {limits['maxChildBytes'] // 1024} Kio" in DOC
    assert f"{limits['minCompositionPx']} à {limits['maxCompositionPx']:,} px".replace(",", " ") in DOC
    assert limits["maxFrame"] == rs.MAX_DURATION_FRAMES and limits["maxFps"] == rs.MAX_FPS
    for name in ("init", "props", "control", "cue", "ping", "teardown", "ready", "pong", "violation", "error"):
        assert f"`{name} " in DOC or f"`{name}`" in DOC, name


def test_the_files_the_doc_cites_exist_and_the_source_doc_links_here():
    for relative in re.findall(r"`((?:jarvis|scripts|tests|tasks)/[A-Za-z0-9_./-]+\.(?:py|js|mjs|json))`", DOC):
        assert (ROOT / relative).exists() or "evidence" in relative, relative
    assert "remotion-isolation.md" in SOURCE_DOC
    assert "SOURCE_GUARDS = (isolation_guard,)" in DOC and iso.isolation_guard in rs.SOURCE_GUARDS
