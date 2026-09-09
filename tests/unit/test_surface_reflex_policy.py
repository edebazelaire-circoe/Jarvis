"""La frontière non négociable : la surface a les réflexes, le cerveau la vérité.

Ce fichier verrouille la politique de réflexes de la spec section 9 et des
Décisions 02 et 14. Il prouve quatre choses, et seulement celles-là :

1. le prompt construit en mode continu porte l'interdiction d'annoncer un
   résultat, une progression, un succès ou un échec ;
2. les jeux de règles legacy et continu sont **intentionnellement** distincts, et
   Gemini Live reçoit toujours le legacy (Décision 21) ;
3. les tours assistant produits par la surface sont persistés avec leur
   provenance — vérification de l'acquis de la Tâche 07, pas réimplémentation ;
4. le modèle de surface reste un réglage, jamais une constante métier
   (Décision 18).

Ce qui n'est **pas** prouvé ici, et qu'aucun test hors ligne ne peut prouver :
qu'un vrai modèle Realtime obéisse à ces règles. Le prompt réduit l'espace des
sorties, il ne le contraint pas. La seule preuve possible est une recette poste
de travail (Tâches 11 et 12).
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path

import pytest

from jarvis import app
from jarvis.adapters import gemini_live, openai_realtime
from jarvis.adapters.gemini_live import GeminiLiveSession
from jarvis.adapters.openai_realtime import (
    CONTINUOUS_BRAIN_OPERATING_RULES,
    JARVIS_PERSONA,
    OPERATING_RULES,
    SURFACE_ACKNOWLEDGEMENTS,
    SURFACE_HEARING_REPAIRS,
    OpenAIRealtimeSession,
    build_session_instructions,
    operating_rules_for,
)
from jarvis.domain.v2 import ProtocolEnvelope, SpeechProvenance
from jarvis.runtime.realtime_audio import CLAUDE_TOOL, RealtimeConversationBridge
from jarvis.runtime.realtime_tools import CLAUDE_TASK_TOOL, REALTIME_TOOLS, tools_for

TIMEOUT_S = 5.0
SOURCE_ROOT = Path(__file__).resolve().parents[2] / "jarvis"
APP = SOURCE_ROOT / "app.py"


# --------------------------------------------------------------------------
# Doubles


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        return None


class FakeHttp:
    """Session aiohttp réduite à ce que `connect()` en attend."""

    def __init__(self) -> None:
        self.ws = FakeWebSocket()
        self.url = ""

    async def ws_connect(self, url: str, **kwargs: object):  # noqa: ANN401
        del kwargs
        self.url = url
        return self.ws

    async def close(self) -> None:
        return None


class TurnRecordingCore:
    """Core vu depuis le bridge, réduit à la persistance des tours."""

    def __init__(self) -> None:
        self.appended: list[dict[str, object]] = []

    async def append_turn(self, conversation_id: str, *, kind: str, content: str, metadata=None) -> dict:  # noqa: ANN001
        del conversation_id
        self.appended.append({"kind": kind, "content": content, "metadata": metadata})
        return {}

    async def submit_brain_turn(self, conversation_id: str, *, content: str, correlation_id: str, source: str = "realtime", addressing: str = "addressed", provider_item_id=None, interrupted_speech_id=None) -> dict:  # noqa: ANN001
        del conversation_id, content, source, provider_item_id, interrupted_speech_id
        return {"turn_id": "turn-1", "correlation_id": correlation_id, "revision": 1}


class QueueSession:
    def __init__(self) -> None:
        self.inbox: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()

    async def events(self):
        while True:
            event = await self.inbox.get()
            if event is None:
                return
            yield event

    async def push(self, message_type: str, **payload: object) -> None:
        await self.inbox.put(ProtocolEnvelope(message_type=message_type, payload=payload))

    async def stop(self) -> None:
        await self.inbox.put(None)

    async def send_audio(self, pcm: bytes) -> None:
        del pcm

    async def send_tool_result(self, call_id: str, result: dict) -> None:
        del call_id, result

    async def send_context(self, text: str) -> None:
        del text

    async def keepalive(self) -> None:
        return None


class SilentAudio:
    input_device = output_device = None
    sample_rate = 24000
    captured_bytes = sent_bytes = 0

    def __init__(self) -> None:
        self._drained = asyncio.Event()

    async def start(self) -> None:
        return None

    async def pump_input(self, session) -> None:  # noqa: ANN001
        await self._drained.wait()

    async def stop_input(self) -> None:
        self._drained.set()

    def set_active_output(self, **identity) -> None:  # noqa: ANN003
        del identity

    async def play_b64(self, value: str) -> None:
        del value

    async def close(self) -> None:
        self._drained.set()


# --------------------------------------------------------------------------
# 1. Le prompt continu pose la frontière vérité / progression


def test_the_continuous_prompt_forbids_result_and_progress_claims():
    instructions = build_session_instructions({}, continuous_brain=True)

    # Le cerveau, pas la surface, détient la vérité et l'intention.
    assert "détient la vérité et l'intention" in instructions
    # L'interdiction porte sur les quatre catégories de la spec section 9.
    assert "interdit d'annoncer un résultat, une progression, un succès ou un échec" in instructions
    assert "d'inventer une progression pour meubler le silence" in instructions
    assert "de répondre sur le fond à la place du cerveau" in instructions
    # Prétendre qu'une opération a eu lieu est nommé explicitement.
    for target in ("fichier", "e-mail", "agenda"):
        assert target in instructions
    # Décider d'annuler un travail de fond appartient au cerveau (Décision 16).
    assert "d'annuler, de remplacer ou de relancer un travail en cours" in instructions
    # Le silence est préférable à une fausse progression (spec section 9).
    assert "Se taire vaut toujours mieux qu'inventer une progression." in instructions


def test_the_continuous_prompt_allows_exactly_the_reflexes_the_spec_permits():
    """« Exactement » veut dire ceux-là et aucun autre, pas « au moins ceux-là ».

    Vérifier l'inclusion seule laisserait passer une sixième phrase glissée dans
    la liste des permissions : c'est précisément l'écart que ce test doit fermer.
    L'exclusivité se prouve sur la clause d'autorisation — la phrase ouverte par
    « De toi-même, tu peux uniquement » — et non sur le prompt entier, qui cite
    aussi des tournures dans ses interdictions.
    """

    instructions = build_session_instructions({}, continuous_brain=True)

    allowance = next(
        (line for line in instructions.splitlines() if line.startswith("De toi-même, tu peux uniquement")),
        None,
    )
    assert allowance is not None, "la clause d'autorisation doit être identifiable"

    for phrase in SURFACE_ACKNOWLEDGEMENTS + SURFACE_HEARING_REPAIRS:
        assert phrase in allowance, "un réflexe autorisé doit être cité mot pour mot"
    # Et rien d'autre : aucune autre phrase citée ne se glisse dans la clause.
    quoted = re.findall(r"«\s*(.+?)\s*»", allowance)
    assert sorted(quoted) == sorted(SURFACE_ACKNOWLEDGEMENTS + SURFACE_HEARING_REPAIRS)
    # Les seules permissions sont ces deux listes et la clarification bornée :
    # trois clauses, pas quatre.
    permissions = [clause.strip() for clause in allowance.split(" ; ")]
    assert len(permissions) == 3
    assert permissions[0].startswith("De toi-même, tu peux uniquement : accuser réception")
    assert permissions[1].startswith("réparer une écoute")
    assert permissions[2].startswith("poser une question de clarification minimale")
    # La clarification reste bornée à ce qui a été entendu.
    assert "strictement sur ce que tu as entendu, jamais sur le fond" in permissions[2]


def test_the_continuous_prompt_never_asks_the_surface_to_relay_the_brain():
    """Décision 13 et question ouverte n°10.

    La parole du cerveau est prononcée par `speak()`, avec une consigne de
    restitution fidèle qui remplace les instructions de session. La surface ne
    doit donc ni l'anticiper, ni la répéter, ni la commenter — et la persona
    textuelle ne doit surtout pas être réinjectée dans ce chemin-là.
    """
    instructions = build_session_instructions({}, continuous_brain=True)

    assert "ne l'anticipe pas, ne la répète pas, ne la commente pas" in instructions
    assert JARVIS_PERSONA not in openai_realtime.VERBATIM_SPEECH_INSTRUCTION
    assert CONTINUOUS_BRAIN_OPERATING_RULES not in openai_realtime.VERBATIM_SPEECH_INSTRUCTION


def test_the_recent_context_is_appended_to_both_rule_sets():
    context = {"recent_turns": [{"kind": "user", "content": "bonjour"}]}

    for continuous in (False, True):
        instructions = build_session_instructions(context, continuous_brain=continuous)
        assert instructions.endswith("Conversation context:\nuser: bonjour")


# --------------------------------------------------------------------------
# 2. Deux jeux de règles, et Gemini garde le legacy


def test_the_two_rule_sets_are_intentionally_distinct():
    assert CONTINUOUS_BRAIN_OPERATING_RULES != OPERATING_RULES
    assert operating_rules_for(continuous_brain=False) is OPERATING_RULES
    assert operating_rules_for(continuous_brain=True) is CONTINUOUS_BRAIN_OPERATING_RULES

    # Le legacy demande à la surface de faire exactement ce que le continu lui
    # interdit : appeler l'outil, puis restituer le résultat.
    assert "claude_task" in OPERATING_RULES
    assert "restitue-le à voix haute" in OPERATING_RULES
    assert "claude_task" not in CONTINUOUS_BRAIN_OPERATING_RULES

    # ... et le continu porte l'interdiction que le legacy ne contient pas.
    assert "interdit d'annoncer un résultat" not in OPERATING_RULES
    assert "interdit d'annoncer un résultat" in CONTINUOUS_BRAIN_OPERATING_RULES


def test_the_legacy_rule_set_is_the_one_gemini_imports():
    """Décision 21 : Gemini Live reste sur le chemin legacy.

    `gemini_live` importe la constante, il n'en fabrique pas de copie : si le
    mode continu avait été écrit **dans** `OPERATING_RULES`, les deux piles
    auraient changé d'un coup, sans qu'aucun test ne le dise.
    """
    assert gemini_live.OPERATING_RULES is OPERATING_RULES


async def test_gemini_still_receives_the_legacy_rules():
    http = FakeHttp()

    await GeminiLiveSession.connect(
        api_key="k", model="gemini-live", voice="Puck", context={}, tools=REALTIME_TOOLS, session=http
    )

    setup = http.ws.sent[0]["setup"]
    instructions = setup["systemInstruction"]["parts"][0]["text"]
    assert instructions == JARVIS_PERSONA + " " + OPERATING_RULES
    assert "interdit d'annoncer un résultat" not in instructions
    # Le catalogue de Gemini reste complet : c'est lui qui exécute encore l'outil.
    names = {declaration["name"] for declaration in setup["tools"][0]["functionDeclarations"]}
    assert CLAUDE_TASK_TOOL in names


@pytest.mark.parametrize(
    "continuous,expected_rules",
    [(False, OPERATING_RULES), (True, CONTINUOUS_BRAIN_OPERATING_RULES)],
)
async def test_the_openai_session_sends_the_rule_set_of_its_architecture(continuous, expected_rules):  # noqa: ANN001
    http = FakeHttp()

    await OpenAIRealtimeSession.connect(
        api_key="k",
        model="surface-model",
        voice="cedar",
        context={},
        tools=tools_for(continuous_brain=continuous),
        continuous_brain=continuous,
        session=http,
    )

    session = http.ws.sent[0]["session"]
    assert session["instructions"] == JARVIS_PERSONA + " " + expected_rules


async def test_the_openai_session_defaults_to_the_legacy_rules():
    """Un appelant qui ignore le nouveau paramètre garde l'ancien comportement."""
    http = FakeHttp()

    await OpenAIRealtimeSession.connect(
        api_key="k", model="surface-model", voice="cedar", context={}, tools=REALTIME_TOOLS, session=http
    )

    assert http.ws.sent[0]["session"]["instructions"] == JARVIS_PERSONA + " " + OPERATING_RULES


# --------------------------------------------------------------------------
# Le catalogue d'outils


def test_the_legacy_catalogue_is_unchanged():
    """Décision 34 : rien de ce que le mode continu retire ne touche le legacy."""
    legacy = tools_for(continuous_brain=False)

    assert legacy == REALTIME_TOOLS
    assert [tool["name"] for tool in legacy] == [tool["name"] for tool in REALTIME_TOOLS]
    assert legacy is not REALTIME_TOOLS, "l'appelant ne doit pas pouvoir muter le catalogue"


def test_no_tool_can_reappear_in_the_continuous_catalogue():
    """Décision 34 : la surface n'exécute plus rien, garantie mécaniquement.

    Le tour complet part au cerveau avant que la surface puisse appeler quoi que
    ce soit (Tâche 07) : garder `drive_delete` ou `calendar_invite` ici, c'est
    accepter qu'ils s'exécutent deux fois, ou qu'ils s'exécutent pendant que le
    cerveau décide qu'il ne faut pas. Aucune formulation de prompt n'empêche
    cela — seule l'absence de l'outil l'empêche.

    Ce test échoue si un seul outil réapparaît, y compris un outil de lecture,
    y compris un outil ajouté plus tard à `REALTIME_TOOLS`.
    """
    continuous = tools_for(continuous_brain=True)

    assert continuous == []
    offered = {tool.get("name") for tool in continuous}
    for tool in REALTIME_TOOLS:
        assert tool["name"] not in offered, f"{tool['name']} est revenu sur la surface"
    assert CLAUDE_TASK_TOOL not in offered


def test_the_continuous_prompt_promises_no_action_of_its_own():
    """Le prompt et le catalogue doivent dire la même chose au modèle."""
    instructions = build_session_instructions({}, continuous_brain=True)

    assert "Tu n'exécutes aucune action toi-même : tu ne disposes d'aucun outil." in instructions
    assert "appartient au cerveau" in instructions
    # Les promesses d'exécution du jeu legacy ne doivent pas avoir survécu.
    assert "résultat d'outil" not in instructions
    assert "pose une question fermée oui/non" not in instructions
    for name in (tool["name"] for tool in REALTIME_TOOLS):
        assert name not in instructions, f"le prompt continu nomme encore l'outil {name}"


async def test_an_empty_catalogue_forbids_tool_calls_at_the_provider():
    """La surface ne se contente pas de ne rien offrir : elle le déclare.

    « auto » sur une liste vide est une contradiction que rien n'oblige le
    fournisseur à trancher comme nous l'entendons.
    """
    continuous_http, legacy_http = FakeHttp(), FakeHttp()

    await OpenAIRealtimeSession.connect(
        api_key="k", model="m", voice="cedar", context={},
        tools=tools_for(continuous_brain=True), continuous_brain=True, session=continuous_http,
    )
    await OpenAIRealtimeSession.connect(
        api_key="k", model="m", voice="cedar", context={},
        tools=tools_for(continuous_brain=False), session=legacy_http,
    )

    assert continuous_http.ws.sent[0]["session"]["tools"] == []
    assert continuous_http.ws.sent[0]["session"]["tool_choice"] == "none"
    # Le legacy garde exactement le comportement qu'il avait.
    assert legacy_http.ws.sent[0]["session"]["tools"] == REALTIME_TOOLS
    assert legacy_http.ws.sent[0]["session"]["tool_choice"] == "auto"


def test_the_tool_name_stays_in_sync_with_the_bridge():
    """Le nom est dupliqué pour ne pas faire dépendre le catalogue de l'audio.

    `_brain_owns_the_request()` reste en place côté bridge : c'est le filet si un
    modèle hallucine un appel d'outil qui ne lui a jamais été offert.
    """
    assert CLAUDE_TASK_TOOL == CLAUDE_TOOL


# --------------------------------------------------------------------------
# 3. Provenance des tours assistant de surface (vérification)


async def test_a_surface_reflex_is_persisted_as_a_surface_reflex():
    """Vérification de l'acquis de la Tâche 07, pas réimplémentation.

    La politique ne tient que si le cerveau peut distinguer, dans l'historique,
    ce qu'il a fait dire à JARVIS de ce que la surface a dit toute seule
    (spec section 15). Sans cette étiquette, un « Je m'en occupe. » relu plus
    tard se lit comme un engagement du cerveau.
    """
    core = TurnRecordingCore()
    session = QueueSession()
    bridge = RealtimeConversationBridge(
        core=core,
        session=session,
        conversation_id="conv-1",
        audio=SilentAudio(),
        on_addressed=lambda: None,
        on_mute=lambda: None,
        auto_turn=True,
        continuous=True,
    )

    running = asyncio.create_task(bridge.run())
    await session.push("realtime.assistant_transcript", text="Je m'en occupe.")
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)

    assert core.appended == [
        {
            "kind": "assistant",
            "content": "Je m'en occupe.",
            "metadata": {"provenance": SpeechProvenance.SURFACE_REFLEX.value},
        }
    ]


# --------------------------------------------------------------------------
# 4. Le modèle de surface reste un réglage


def test_the_recommended_surface_model_follows_the_architecture(monkeypatch, tmp_path):
    """Décision 18 : un défaut recommandé, jamais une constante métier."""
    from jarvis.v2_config import DEFAULT_CONTINUOUS_SURFACE_MODEL, DEFAULT_REALTIME_MODEL, V2Settings

    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_REALTIME_MODEL", raising=False)

    monkeypatch.setenv("JARVIS_VOICE_ARCH", "legacy")
    assert V2Settings.load().realtime_model == DEFAULT_REALTIME_MODEL

    monkeypatch.setenv("JARVIS_VOICE_ARCH", "continuous_brain")
    assert V2Settings.load().realtime_model == DEFAULT_CONTINUOUS_SURFACE_MODEL


@pytest.mark.parametrize("arch", ["legacy", "continuous_brain"])
def test_the_surface_model_stays_overridable(monkeypatch, tmp_path, arch):  # noqa: ANN001
    from jarvis.v2_config import V2Settings

    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("JARVIS_VOICE_ARCH", arch)
    monkeypatch.setenv("OPENAI_REALTIME_MODEL", "un-modele-a-moi")

    assert V2Settings.load().realtime_model == "un-modele-a-moi"


def test_no_provider_model_id_reaches_core_or_domain():
    """Aucun identifiant de modèle fournisseur dans Core ni dans le domaine.

    Le défaut recommandé vit dans la couche de configuration ; s'il descend d'un
    étage, la logique métier se met à dépendre d'un catalogue fournisseur qui
    change plus vite que l'architecture (Décision 18).
    """
    needles = ("gpt-realtime", "gpt-4o", "gemini-", "claude-3", "claude-opus", "claude-sonnet")
    offenders: list[str] = []
    for package in ("core", "domain"):
        for path in sorted((SOURCE_ROOT / package).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            offenders.extend(f"{path.name}: {needle}" for needle in needles if needle in text)

    assert offenders == []


# --------------------------------------------------------------------------
# Le câblage réel dans `jarvis/app.py`


def _connect_keywords(function: str, session_class: str) -> dict[str, str]:
    """Les arguments nommés passés à `<session_class>.connect()` dans `function`."""
    module = ast.parse(APP.read_text(encoding="utf-8"))
    for node in ast.walk(module):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != function:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr != "connect" or not isinstance(call.func.value, ast.Name):
                continue
            if call.func.value.id != session_class:
                continue
            return {kw.arg: ast.unparse(kw.value) for kw in call.keywords if kw.arg}
    raise AssertionError(f"{session_class}.connect() introuvable dans {function}()")


def test_the_openai_surface_is_wired_to_the_architecture():
    keywords = _connect_keywords("_run_voice_v2", "OpenAIRealtimeSession")

    assert keywords["continuous_brain"] == "continuous_brain"
    assert keywords["tools"] == "surface_tools"
    assert "tools_for(continuous_brain=continuous_brain)" in APP.read_text(encoding="utf-8")


def test_the_gemini_surface_keeps_the_legacy_wiring():
    """Décision 21 : rien de ce que la tâche 06 ajoute ne doit atteindre Gemini."""
    keywords = _connect_keywords("_run_voice_v2", "GeminiLiveSession")

    assert keywords["tools"] == "REALTIME_TOOLS"
    assert "continuous_brain" not in keywords


class _FakeCoreClient:
    """Client Core minimal : `_run_voice_v2` n'a besoin que de `health()` avant le garde-fou."""

    def __init__(self, **_kwargs) -> None:
        self.closed = False

    async def health(self) -> dict[str, object]:
        return {"ready": True}

    async def close(self) -> None:
        self.closed = True


class _FakeWakeBackend:
    """Réveil clavier neutre : sa vraie implémentation accroche le clavier de la machine."""

    def __init__(self, **_kwargs) -> None:
        pass


def _voice_environment(tmp_path, monkeypatch, *, arch: str, model: str = "") -> list[str]:
    """Poser le décor minimal d'un lancement Voice sur la pile Gemini.

    Rend la liste des appels à `GeminiLiveSession.connect`, qui doit rester vide :
    c'est elle qui prouve que le refus tombe **avant** toute connexion fournisseur.
    """

    from jarvis.adapters import wakeword_keyboard, wakeword_porcupine  # noqa: F401
    from jarvis.protocol import client as protocol_client

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "core.token").write_text("jeton-de-test", encoding="utf-8")
    overrides: dict[str, object] = {"voice_stack": "gemini_live", "google_api_key": "cle-de-test"}
    if model:
        overrides["voice_stack_settings"] = {"gemini_live": {"model": model}}
    (runtime_root / "control-center-settings.json").write_text(json.dumps(overrides), encoding="utf-8")

    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("JARVIS_VOICE_ARCH", arch)
    monkeypatch.setattr(protocol_client, "LocalCoreClient", _FakeCoreClient)
    monkeypatch.setattr(wakeword_keyboard, "KeyboardWakeWordBackend", _FakeWakeBackend)

    connects: list[str] = []

    async def _refuse_connect(**kwargs):
        connects.append(str(kwargs.get("model") or ""))
        raise AssertionError("GeminiLiveSession.connect ne doit pas être atteint")

    monkeypatch.setattr(GeminiLiveSession, "connect", staticmethod(_refuse_connect))
    return connects


async def test_gemini_cannot_be_started_in_continuous_mode(tmp_path, monkeypatch):
    """Ce que ce test prouve : le lancement échoue réellement, et avant `connect()`.

    Il exécute `_run_voice_v2()` avec la pile Gemini sélectionnée et
    JARVIS_VOICE_ARCH=continuous_brain, et vérifie que l'appel lève, que le
    message nomme la pile et la variable, et que `GeminiLiveSession.connect`
    n'a jamais été appelé. L'ancienne version cherchait par AST un `raise`
    mentionnant « Gemini Live » sous un `if continuous_brain:` : elle serait
    restée verte si la branche avait été placée après la connexion, ou si le
    refus n'avait jamais été atteint.

    Décision 21 : Gemini n'implémente ni le port de contrôle de sortie ni les
    règles de surface du mode continu. Le laisser démarrer donnerait une voix
    qui commente le travail du cerveau sans pouvoir être interrompue.
    """

    connects = _voice_environment(tmp_path, monkeypatch, arch="continuous_brain", model="gemini-live-x")

    # Le refus doit tomber tout de suite : sans lui, `_run_voice_v2` irait au bout
    # du montage vocal et ne rendrait jamais la main. Le délai fait donc partie de
    # la preuve, il n'est pas une précaution de confort.
    with pytest.raises(RuntimeError) as refus:
        await asyncio.wait_for(app._run_voice_v2(), TIMEOUT_S)

    message = str(refus.value)
    assert "Gemini Live" in message
    assert "continuous_brain" in message
    assert connects == []


async def test_the_gemini_refusal_is_specific_to_continuous_mode(tmp_path, monkeypatch):
    """Ce que ce test prouve : le garde-fou ne bloque pas Gemini en legacy.

    Même décor, `JARVIS_VOICE_ARCH=legacy` et aucun modèle choisi : le
    lancement échoue sur le contrôle **suivant** — le modèle Gemini manquant —
    et non sur le refus du mode continu. Sans ce contraste, le test ci-dessus
    resterait vert si `_run_voice_v2` refusait Gemini en toutes circonstances.
    """

    connects = _voice_environment(tmp_path, monkeypatch, arch="legacy")

    with pytest.raises(RuntimeError) as refus:
        await asyncio.wait_for(app._run_voice_v2(), TIMEOUT_S)

    message = str(refus.value)
    assert "modèle Gemini Live" in message
    assert "continuous_brain" not in message
    assert connects == []
