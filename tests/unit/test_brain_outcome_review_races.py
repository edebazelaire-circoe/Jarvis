"""Independent outcome review: concurrent observations retain first provenance."""
import asyncio

from jarvis.domain.speech_presentation import OutcomeKind
from tests.unit.test_core_brain_outcomes import store, source_for


async def test_concurrent_owner_change_does_not_break_same_outcome_dedup(store, monkeypatch):
    repo, conversations, conv, service, _ = store
    await source_for(repo, conversations, conv, "describing-turn")
    save = repo.save_brain_outcome
    both_prepared = asyncio.Event()
    entered = 0

    async def coordinated_save(outcome):
        nonlocal entered
        entered += 1
        if entered == 2:
            both_prepared.set()
        await asyncio.wait_for(both_prepared.wait(), 1)
        return await save(outcome)

    monkeypatch.setattr(repo, "save_brain_outcome", coordinated_save)
    arguments = dict(conversation_id=conv, correlation_id="describing-turn",
                     work_id="reused-work", text="The same public result.", kind=OutcomeKind.WORK_RESULT)
    # An older work owner can disappear between two concurrent notifications.
    # Both observations saw no persisted version before reaching the save.
    results = await asyncio.gather(
        service.retain(**arguments, dependency_known=False),
        service.retain(**arguments, dependency_known=True), return_exceptions=True,
    )
    assert not [result for result in results if isinstance(result, BaseException)]
    assert results[0] == results[1]
    assert await repo.list_brain_outcomes(conv) == (results[0],)
