"""Strict source contracts and exact semantic presentation boundaries."""
from dataclasses import replace

import pytest

from jarvis.domain.speech_presentation import (
    MAX_SPEECH_CHUNK_TEXT, SpeechSource, SpeechTextSpan, semantic_text_spans,
)
from jarvis.domain.v2 import SpeechRequest
from tests.fakes.speech_context import source


@pytest.mark.parametrize("separator", ["\n\n", "\r\n\r\n", "\n \t\n"])
def test_exact_paragraph_spans_reconstruct_without_splitting_decimals(separator):
    text = "Dr. Example: 29.1 seconds. Still one paragraph." + separator + "35.9 seconds later."
    spans = semantic_text_spans(text)
    assert len(spans) == 2
    assert "".join(text[span.start:span.end] for span in spans) == text
    assert text[spans[0].start:spans[0].end].endswith(separator)


def test_long_chain_is_separate_from_provider_chunk_limit():
    text = "a" * 8000 + "\r\n\r\n" + "b" * 8000
    request = SpeechRequest("conversation", text, correlation_id="c", source=source("c"), chunks=semantic_text_spans(text))
    assert len(request.text) > MAX_SPEECH_CHUNK_TEXT
    assert all(span.end - span.start <= MAX_SPEECH_CHUNK_TEXT for span in request.chunks)
    assert SpeechRequest.from_payload(request.to_payload()) == request


@pytest.mark.parametrize("text", ["a" * 8193, "\n\n".join("paragraph" for _ in range(17)), "a" * 65537], ids=["oversize_paragraph", "too_many_parts", "oversize_result"])
def test_unpresentable_shape_is_explicit(text):
    with pytest.raises(ValueError):
        semantic_text_spans(text)


@pytest.mark.parametrize("epoch", [True, -1, 1.2, float("inf"), 2**63])
def test_source_epoch_is_strict(epoch):
    with pytest.raises(ValueError):
        replace(source(), intent_epoch=epoch)


def test_source_and_chunks_reject_ambiguous_payload():
    payload = source().to_payload()
    assert SpeechSource.from_payload(payload) == source()
    with pytest.raises(ValueError):
        SpeechSource.from_payload({**payload, "revision": 99})
    request = SpeechRequest("conversation", "One.\n\nTwo.", correlation_id="c", source=source("c"))
    for spans in ((SpeechTextSpan(0, 2),), (SpeechTextSpan(0, 6), SpeechTextSpan(5, 10))):
        with pytest.raises(ValueError):
            replace(request, chunks=spans)
    with pytest.raises(ValueError):
        replace(request, source=source("different"))
    with pytest.raises(ValueError):
        replace(request, interruptible="false")
