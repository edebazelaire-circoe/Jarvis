"""Issue 002 (2026-09), Slice 11 — un segment écarté ne laisse pas ses mots au journal.

`voice.transcript_dropped` dit **pourquoi** un segment a été écarté (motif,
code, longueur), jamais **ce qui** a été dit. Ceci vaut dans tous les modes :
SIMPLE (bruit filtré, doute sur la voie directe) comme PRESENTATION (bruit
reconnu dans une fenêtre adressée vivante, où la ligne `voice.transcript`
n'est pas encore écrite — c'était la dernière fuite de la salle).

Le vrai `RealtimeConversationBridge` et le vrai `RuntimeJournal` : le fichier
`trace.jsonl` est relu tel qu'il est sur disque.
"""

from __future__ import annotations

import json

import pytest

from jarvis.audio import input_ownership
from jarvis.runtime.journal import RuntimeJournal
from tests.unit.test_presentation_turn_authority import arm, live_service, make_bridge, say

#: Un mot qui n'existe dans aucun vocabulaire de JARVIS.
PLANTED = "Zorglub7731"
#: Une formule de sous-titrage connue (`HALLUCINATED_PHRASES`) suivie du mot planté.
NOISE = f"Merci d'avoir regardé cette vidéo {PLANTED} budget confidentiel"
#: Une phrase longue sans marque d'adresse : UNCERTAIN pour le classifieur.
UNCERTAIN = f"le chiffre d'affaires du trimestre {PLANTED} a beaucoup progressé grâce aux clients en europe"


@pytest.fixture(autouse=True)
def clean_input_registry():
    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


def _lines(journal: RuntimeJournal) -> list[dict]:
    return [json.loads(line) for line in journal.trace_path.read_text(encoding="utf-8").splitlines()]


def _dropped(journal: RuntimeJournal) -> dict:
    [line] = [line for line in _lines(journal) if line["kind"] == "voice.transcript_dropped"]
    return line


def _assert_text_free(line: dict, text: str, reason: str) -> None:
    raw = json.dumps(line, ensure_ascii=False)
    assert PLANTED not in raw and "confidentiel" not in raw and "trimestre" not in raw
    assert line["data"]["reason"] == reason
    assert line["data"]["chars"] == len(text)


async def test_dropped_transcript_trace_carries_no_text_in_simple_noise(tmp_path) -> None:
    journal = RuntimeJournal(tmp_path)
    bridge, core, _ = make_bridge(journal=journal)
    await say(bridge, NOISE)

    assert core.brain_turns == []
    _assert_text_free(_dropped(journal), NOISE.strip(), "hallucination")


async def test_dropped_transcript_trace_carries_no_text_in_simple_direct_uncertain(tmp_path) -> None:
    journal = RuntimeJournal(tmp_path)
    bridge, core, _ = make_bridge(journal=journal, engaged=False, direct=True)
    await say(bridge, UNCERTAIN)

    _assert_text_free(_dropped(journal), UNCERTAIN, "uncertain_direct")


async def test_dropped_transcript_trace_carries_no_text_in_presentation(tmp_path) -> None:
    """Bruit dans une fenêtre armée, voie cerveau : rien de la phrase nulle part au journal."""

    journal = RuntimeJournal(tmp_path)
    service, clock = live_service(journal)
    arm(service, clock)
    bridge, core, calls = make_bridge(turns=service, engaged=False, journal=journal)
    await say(bridge, NOISE)

    assert core.brain_turns == [] and calls.addressed == 0
    _assert_text_free(_dropped(journal), NOISE.strip(), "hallucination")
    trace = journal.trace_path.read_text(encoding="utf-8")
    assert PLANTED not in trace and "confidentiel" not in trace


async def test_dropped_transcript_trace_carries_no_text_in_echo_of_jarvis(tmp_path) -> None:
    """Le chemin « écho » de la première émission : JARVIS s'entend lui-même, près de sa parole."""

    spoken = f"Voici le plan du budget {PLANTED} confidentiel pour le trimestre prochain"
    journal = RuntimeJournal(tmp_path)
    bridge, core, _ = make_bridge(journal=journal)
    bridge._echo.remember(spoken)
    bridge._last_segment_near_playback = True
    await say(bridge, spoken)

    assert core.brain_turns == []
    line = _dropped(journal)
    assert line["data"]["near_playback"] is True
    _assert_text_free(line, spoken, "echo")


async def test_dropped_transcript_trace_carries_no_text_when_the_window_is_refused_at_open(tmp_path) -> None:
    """La troisième émission : la fenêtre vue vivante expire avant `open()` ; motif et longueur seulement."""

    planted = f"{PLANTED} budget confidentiel du trimestre"
    journal = RuntimeJournal(tmp_path)
    service, clock = live_service(journal)
    arm(service, clock)
    clock.advance(60.0)

    class StaleProbe:
        """Le pré-contrôle voit la fenêtre vivante ; l'ouverture, elle, la refuse."""

        def __init__(self, inner) -> None:  # noqa: ANN001
            self.inner = inner

        def window_live(self) -> bool:
            return True

        def __getattr__(self, name: str):  # noqa: ANN204
            return getattr(self.inner, name)

    bridge, core, calls = make_bridge(turns=StaleProbe(service), engaged=True, journal=journal)
    await say(bridge, planted)

    assert core.brain_turns == [] and calls.addressed == 0
    line = _dropped(journal)
    assert line["data"]["code"] == "transcript_presentation_window_refused"
    _assert_text_free(line, planted, "presentation_window_refused")
    trace = journal.trace_path.read_text(encoding="utf-8")
    assert PLANTED not in trace and "confidentiel" not in trace
