from __future__ import annotations

import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import TurnKind


@pytest.mark.asyncio
async def test_core_headless_restart_preserves_conversation(tmp_path):
    core = JarvisCoreApplication(data_root=tmp_path)
    await core.start()
    conversation = await core.conversations.create()
    await core.conversations.append_turn(conversation.id, TurnKind.USER, "Question", correlation_id="one")
    await core.stop()

    core2 = JarvisCoreApplication(data_root=tmp_path)
    await core2.start()
    context = await core2.conversations.rehydration_context(conversation.id)
    assert context["conversation_id"] == conversation.id
    assert context["recent_turns"][-1]["content"] == "Question"
    await core2.stop()
