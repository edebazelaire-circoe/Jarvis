"""The presenter view says WHY the run paused (`interrupt_source`), so the page can tell the user instead of pausing in silence."""

from __future__ import annotations

import pytest

from tests.fakes.presentation_studio_presenter import item_content, make_presenter
from tests.unit.test_presentation_studio_playback_service import applied
from tests.unit.test_presentation_studio_presenter_sequences import open_rig, where


@pytest.mark.parametrize("signal, source", [("user_turn", "user_turn"), ("floor", "floor_taken")])
async def test_the_view_exposes_why_the_presenter_paused_and_clears_it_on_resume(tmp_path, signal, source):
    rig = await open_rig(tmp_path, item_content(interruption="allow"))
    presenter, brain, voice = make_presenter(rig)
    applied(await rig.service.start(rig.start_body("jarvis_presenter")))
    await presenter.pump()
    assert presenter.view()["interrupted"] is False and presenter.view()["interrupt_source"] is None
    getattr(voice, signal)()
    await presenter.pump()
    view = presenter.view()
    assert where(rig)["phase"] == "paused" and view["interrupted"] is True and view["interrupt_source"] == source
    applied(await rig.run("resume"))
    await presenter.pump()
    assert presenter.view()["interrupted"] is False and presenter.view()["interrupt_source"] is None
    await rig.close()
