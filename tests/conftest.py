from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from jarvis.domain.events import StateEvent
from jarvis.domain.messages import CancellationToken, UserTurn
from jarvis.domain.results import AgentResult, SpeechResult

#: Logique pure de la page du Control Center : le fichier même que
#: `ControlCenter.index` insère dans la page servie au navigateur.
CONTROL_CENTER_WORK_JS = Path(__file__).resolve().parents[1] / "jarvis" / "runtime" / "control_center_work.js"
CONTROL_CENTER_SCENE_JS = CONTROL_CENTER_WORK_JS.with_name("control_center_scene.js")
_NODE = shutil.which("node")


@pytest.fixture
def page_logic():
    """Exécuter la logique pure de la page avec node, et rendre son résultat.

    Les règles de l'interface (garde de révision, durées, projection d'un
    travail Core, cohérence mode/vérification) sont ainsi prouvées en
    exécutant le code servi, pas en relisant sa source : une erreur de logique
    qui conserverait le texte ne passerait plus.

    `body` est le corps d'une fonction ; `W` y désigne le module chargé, et la
    valeur rendue revient décodée depuis JSON.
    """

    def run(body: str) -> Any:
        if _NODE is None:
            pytest.skip("node absent")
        script = (
            f"const W=require({json.dumps(str(CONTROL_CENTER_WORK_JS))});"
            f"console.log(JSON.stringify((()=>{{{body}}})()))"
        )
        result = subprocess.run(
            [_NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    return run


@pytest.fixture
def scene_logic(tmp_path):
    """Exécuter le client pur de la scène (`control_center_scene.js`) avec node.

    Même principe que `page_logic` : `body` est le corps d'une fonction où `S`
    désigne le module chargé et `D` les données `data` (écrites dans un
    fichier : un parcours de parité dépasse la longueur d'une ligne de
    commande). Node absent : le test est sauté.
    """

    def run(body: str, data: Any = None) -> Any:
        if _NODE is None:
            pytest.skip("node absent")
        data_file = tmp_path / f"scene-data-{len(list(tmp_path.glob('scene-data-*')))}.json"
        data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        script = (
            f"const S=require({json.dumps(str(CONTROL_CENTER_SCENE_JS))});"
            f"const D=JSON.parse(require('fs').readFileSync({json.dumps(str(data_file))},'utf8'));"
            f"console.log(JSON.stringify((()=>{{{body}}})()))"
        )
        result = subprocess.run(
            [_NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=120
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    return run


@dataclass
class RecordingStatePublisher:
    events: list[StateEvent] = field(default_factory=list)
    waveforms: list[list[float] | None] = field(default_factory=list)
    cleaned: bool = False

    async def publish(self, event: StateEvent, *, waveform=None):
        self.events.append(event)
        self.waveforms.append(None if waveform is None else list(waveform))

    async def cleanup(self):
        self.cleaned = True


class ScriptedAgent:
    def __init__(self, *results: AgentResult):
        self.results = deque(results)
        self.turns: list[UserTurn] = []

    async def respond(self, turn, tools):
        self.turns.append(turn)
        if not self.results:
            raise AssertionError("No scripted agent result left")
        return self.results.popleft()


class RecordingTTS:
    def __init__(self):
        self.texts: list[str] = []
        self.tokens: list[CancellationToken] = []

    async def speak(self, text: str, *, interrupt: CancellationToken):
        self.texts.append(text)
        self.tokens.append(interrupt)
        return SpeechResult(
            duration_ms=1,
            interrupted=interrupt.cancelled,
            provider="fake",
            model="fake",
        )


class RecordingBoard:
    def __init__(self, *, fail: bool = False):
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def present(self, title, body, *, x=None, y=None):
        if self.fail:
            raise ConnectionError("board down")
        payload = {"title": title, "body": body, "x": x, "y": y}
        self.calls.append(payload)
        return {"presented": True, **payload}

    async def health(self):
        return not self.fail


@pytest.fixture
def agent_result_factory():
    def make(text="", tool_calls=(), continuation_token=None):
        return AgentResult(
            text=text,
            tool_calls=tuple(tool_calls),
            provider="fake",
            model="fake",
            duration_ms=1,
            continuation_token=continuation_token,
        )
    return make
