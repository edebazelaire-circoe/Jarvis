"""Explicit synthetic Core authority for scheduler tests; never used by production."""
from jarvis.domain.speech_presentation import SpeechSource, SpeechDependency


def source(correlation="corr-1", *, epoch=1, intent=None, work_id=None):
    return SpeechSource("turn-" + correlation, correlation, intent or f"intent-{epoch}", epoch,
                        (SpeechDependency(work_id, correlation),) if work_id else ())


def context(conversation, correlation="corr-1", *, epoch=1, complete=True, invalid=()):
    return {"schema_version": 1, "conversation_id": conversation,
            "current_speech_source": source(correlation, epoch=epoch).to_payload(),
            "source_complete": complete, "invalidated_dependencies": [item.to_payload() for item in invalid]}
