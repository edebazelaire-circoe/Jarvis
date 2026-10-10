"""The scripted fake-author rig and its committed, redacted evidence (jarvis-interactive-presentation-studio, Slice 11).

The evidence file is regenerated deliberately (`python -m tests.replay.presentation_studio_authoring_rig`); this test fails when the
code, the rules, the prompt or the fixtures moved without it, and when the evidence says anything a scripted rig cannot prove.
"""

from __future__ import annotations

import json
import re

from jarvis.domain.presentation_studio_authoring_gate import RULES
from tests.fakes import presentation_studio_fake_author as fa
from tests.replay.presentation_studio_authoring_rig import EVIDENCE, NOT_IN_THE_TABLE, render, run


async def test_the_committed_evidence_is_what_the_rig_produces_now():
    result = await run()
    committed = json.loads((EVIDENCE / "fake-author-rig.json").read_text(encoding="utf-8"))
    assert result == committed, "regenerate: python -m tests.replay.presentation_studio_authoring_rig"
    assert (EVIDENCE / "fake-author-rig.md").read_text(encoding="utf-8") == render(result)


async def test_the_evidence_does_not_depend_on_where_the_tree_lives(monkeypatch):
    """QA-1 B1: the registry's `default_revision` hashes the absolute source path, so it differs in every other checkout. The evidence pins
    the content fingerprint, which must come out the same when every module claims to live somewhere else."""

    from pathlib import Path

    from jarvis.runtime import prompt_catalog

    monkeypatch.setattr(prompt_catalog, "_path", lambda module: str(Path("/some/other/checkout") / Path(module.__file__).name))
    committed = json.loads((EVIDENCE / "fake-author-rig.json").read_text(encoding="utf-8"))
    assert (await run()) == committed
    assert "/some/other" not in json.dumps(committed) and "bips" not in json.dumps(committed)


async def test_the_rig_proves_what_it_claims_and_claims_no_more():
    result = await run()
    good = {row["scenario"]: row for row in result["scenarios"]}
    assert all(r["assemble"] == "delivered" and r["errors"] == [] and r["skipped"] == [] for r in good.values())
    assert good["good 12-scene directed deck"]["scenes"] == 12 and good["good 12-scene directed deck"]["da_origins"] == ["inferred"]
    assert good["exploratory, 3 divergent candidates"]["variants"] == 3 == good["exploratory, 3 divergent candidates"]["draft_variants"]
    assert all(row["caught"] and row["assemble"] == "refused" and not row["written"] for row in result["careless_author"])
    covered = set(result["careless_author_covers"]) | set(NOT_IN_THE_TABLE)
    assert covered <= {r.code for r in RULES} and len(result["careless_author_covers"]) == len(fa.VIOLATIONS)
    assert result["prompt"]["attached_to_a_program"] is True and result["prompt"]["attached_programs"] == 4 and result["rules"] == len(RULES) == 62


def test_the_evidence_is_redacted_and_states_that_it_is_not_a_model_trace():
    text = (EVIDENCE / "fake-author-rig.md").read_text(encoding="utf-8") + (EVIDENCE / "fake-author-rig.json").read_text(encoding="utf-8")
    assert "not a model trace" in text and "Slices 21 and 22" in text
    for pattern in (r"pst_[0-9a-f]{8}", r"psv_[0-9a-f]{8}", r"pss_[0-9a-f]{8}", r"psr_[0-9a-f]{8}", r"\d{4}-\d{2}-\d{2}T", "Revue du trimestre",
                    "Lorem", "Bonjour a tous", "Users"):
        assert not re.search(pattern, text), pattern
