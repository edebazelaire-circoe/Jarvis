"""Sonde : le reflexe audible doit ceder la place a la reponse du cerveau.

Miroir de `test_a_preamble_is_cancelled_when_the_answer_arrives_before_it_plays`
(tests/unit/test_reflex_gate.py), mais apres le premier octet ecrit.
"""
from __future__ import annotations

import asyncio

import pytest

from jarvis.domain.v2 import SpeechRequest
from jarvis.runtime.output_admission import OutputAdmissionState
from tests.fakes.speech_context import source, context
from jarvis.runtime.speech_scheduler import SpeechScheduler
from tests.unit.test_voice_duplex import ControllableSession, EmptyCore, RecordingJournal


def scheduler():
    selected = SpeechScheduler(core=EmptyCore(), conversation_id="conversation",
                               session=ControllableSession(), journal=RecordingJournal(),
                               reflex_delay_s=.01, reflex_require_work=False)
    selected.update_speech_context(context("conversation", "c"))
    selected._running = True
    return selected


def due(selected):
    selected._reflex.due = asyncio.get_running_loop().time() - .001
    selected._reflex.next_check = selected._reflex.due


async def test_a_preamble_is_cut_when_the_answer_arrives_while_it_plays():
    selected = scheduler()
    selected.request_reflex("Compare les prix entre ces architectures", correlation_id="c")
    due(selected)
    await selected._maybe_speak_reflex()
    output = selected._live_reflex.output_id

    # Le reflexe est desormais audible : un octet PCM est parti vers la carte son.
    assert selected.output_admission(output).begin_write()
    assert selected.output_admission(output).state is OutputAdmissionState.WRITE_STARTED

    # La reponse du cerveau arrive : elle a la priorite sur le reflexe en cours.
    selected._enqueue(SpeechRequest("conversation", "La reponse du cerveau",
                                    correlation_id="c", source=source("c")))

    assert output in selected._reflex_cancelled, "le reflexe audible n'a pas ete coupe"
    assert selected.session.cancelled_reflexes, "aucune annulation envoyee a la surface"
    await selected.stop()
