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

#: Racine du dépôt, et le répertoire que le Test Lab (Slice 10) compose sous la racine
#: runtime RÉELLE quand un test oublie de lui donner un `tmp_path`.
REPO_ROOT = Path(__file__).resolve().parents[1]
TESTLAB_REAL_ROOT = REPO_ROOT / "runtime" / "testlab"


@pytest.fixture(autouse=True)
def testlab_stays_in_its_temporary_root(request):
    """Un test du Test Lab qui compose contre le `runtime/` du dépôt échoue tout de suite.

    Un `TestLabApi` construit sans racine explicite tombe sur `JARVIS_RUNTIME_DIR`, donc
    sur `runtime/` — il y crée `testlab/work/.supervisor.lock` et, le temps du test, ferme
    le Test Lab au Jarvis qui tourne sur ce poste. C'est arrivé une fois pendant la
    Slice 10 ; ce garde-fou refuse au lieu de compter sur quelqu'un pour le remarquer.

    Deux mesures, la première suffisant seule : aucune racine composée ne doit sortir du
    dépôt-temporaire, et `runtime/testlab` ne doit pas apparaître pendant le test.
    """
    module = Path(str(getattr(request.node, "fspath", ""))).name
    if not module.startswith("test_testlab"):
        yield
        return
    from jarvis.testlab import composition

    existed = TESTLAB_REAL_ROOT.exists()
    composed: list[Path] = []
    original = composition.TestLab.__init__

    def recording(self, config, **options):  # noqa: ANN001 - même signature que l'original
        composed.append(Path(config.root))
        original(self, config, **options)

    composition.TestLab.__init__ = recording
    try:
        yield
    finally:
        composition.TestLab.__init__ = original
    inside_repo = [root for root in composed if _under(root, REPO_ROOT)]
    appeared = TESTLAB_REAL_ROOT.exists() and not existed
    if appeared:
        shutil.rmtree(TESTLAB_REAL_ROOT, ignore_errors=True)
    assert not inside_repo, (f"{request.node.nodeid} a composé un Test Lab dans le dépôt "
                             f"({inside_repo[0]}) au lieu d'un tmp_path")
    assert not appeared, f"{request.node.nodeid} a créé {TESTLAB_REAL_ROOT} (supprimé)"


def _under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


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
