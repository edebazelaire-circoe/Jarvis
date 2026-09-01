from __future__ import annotations

import json

from jarvis.diagnostics.logger import build_logger


def test_privacy_logger_redacts_content_by_default(tmp_path):
    log = build_logger(tmp_path, log_content=False)
    log.event("test", text="secret", transcript="also secret", safe_count=3)
    line = (tmp_path / "jarvis.log").read_text(encoding="utf-8").strip()
    payload = json.loads(line)
    assert payload["text"] == "<redacted:6>"
    assert payload["transcript"] == "<redacted:11>"
    assert payload["safe_count"] == 3
    assert "secret" not in line
