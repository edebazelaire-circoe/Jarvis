"""Intention de sortie et puits d'affichage du mode présentation.

Handoff `jarvis-presentation-interaction-mode` (2026-10), Slice 07 (A3, R4).
Contrat : `docs/presentation-response-policy.md` › *Output intent and display
sink*. Les tests suivent la liste d'acceptation du contrat de la Slice, dans
son ordre.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from enum import Enum
import inspect
import json
from pathlib import Path
import subprocess
import sys

import pytest

from jarvis.core.presentation_display import (
    ALLOWED_IMPORT_CLOSURE,
    DisplayReceipt,
    PresentationDisplayPublisher,
    PresentationDisplaySink,
)
from jarvis.core.presentation_speculative import PreparedFinding
from jarvis.domain import presentation_intent
from jarvis.domain.explicit_address import ExplicitAddressSource, ExplicitAddressTrigger
from jarvis.domain.output_disposition import OutputDisposition
from jarvis.domain.presentation_addressed_turn import AddressedTurnAction
from jarvis.domain.presentation_attention import (
    AttentionCategory,
    AttentionEvidence,
    AttentionSeverity,
    PresentationAttention,
)
from jarvis.domain.presentation_intent import (
    MAX_INTENT_CONTEXT_REFS,
    DisplayIntent,
    DisplaySemantic,
    IntentUrgency,
    PresentationIntentError,
    PresentationOutputIntent,
    intent_for_attention,
    intent_for_plan,
)
from jarvis.domain.presentation_policy import PresentationSituation, may_speak
from jarvis.domain.presentation_speculative import SpeculativeAdmission
from jarvis.domain.presentation_working_set import ResourceKind, UtteranceOrigin
from jarvis.domain.v2 import SpeechKind
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.presentation_display_sink import DirectSceneDisplaySink
from jarvis.runtime.presentation_staging import DisplaySceneStager
from tests.unit.test_display_mcp import core, scene_object, tools  # noqa: F401 - fixtures réutilisées
from tests.unit.test_presentation_addressed_turn import (
    S10Clock,
    S10Journal,
    S10Speculative,
    build_service,
    build_store,
    open_turn,
    resource,
    say,
    topic,
)
from tests.unit.test_presentation_integration import ScriptedAgent, composition
from tests.unit.test_presentation_speculative import (
    ScriptedRunner,
    make_service,
    make_store,
    speak,
    stage_explicit,
)

ROOT = Path(__file__).resolve().parents[2]


class RecordingSink:
    """Puits d'affichage qui note ce qu'il reçoit. Il ne montre rien lui-même."""

    def __init__(self, *, receipt: DisplayReceipt | None = None, withdrawn: int = 0) -> None:
        self.published: list[PresentationOutputIntent] = []
        self.withdrawals: list[str] = []
        #: La corrélation reçue avec chaque retrait (polish p10), dans le même ordre.
        self.correlations: list[str] = []
        self._receipt = receipt or DisplayReceipt(True, "recorded")
        self._withdrawn = withdrawn

    async def publish(self, intent: PresentationOutputIntent) -> DisplayReceipt:
        self.published.append(intent)
        return self._receipt

    def withdraw_speculative(self, reason: str, *, correlation_id: str = "") -> int:
        self.withdrawals.append(reason)
        self.correlations.append(correlation_id)
        return self._withdrawn


def _attention(**overrides) -> PresentationAttention:  # noqa: ANN003
    fields = {
        "attention_id": "att-1", "category": next(iter(AttentionCategory)),
        "severity": next(iter(AttentionSeverity)), "confidence": 0.9,
        "raised_at": datetime(2026, 10, 5, tzinfo=timezone.utc), "claim_id": "c-1",
        "topic_id": "t-1",
        "evidence": (AttentionEvidence(source_id="s-1", locator="https://example.org/a"),),
        "reason": "la marge citée contredit le rapport officiel",
    }
    fields.update(overrides)
    return PresentationAttention(**fields)


async def _plan(action: AddressedTurnAction):
    """Un vrai plan, ouvert par le vrai service, pour chaque action."""

    store = build_store()
    clock = S10Clock()
    text = "montre-moi ca"
    if action is AddressedTurnAction.SHOW_PREPARED:
        say(store, 1, "voici la courbe de marge")
        topic(store, "u-001")
        resource(store, "u-001")
    elif action is AddressedTurnAction.CLARIFY:
        say(store, 1, "compare les deux scenarios")
        topic(store, "u-001")
        resource(store, "u-001", resource_id="r-a", locator="scene:obj-a")
        resource(store, "u-001", resource_id="r-b", locator="scene:obj-b")
    elif action is AddressedTurnAction.REFRESH:
        say(store, 1, "regardons le bilan Q3")
        topic(store, "u-001")
        resource(store, "u-001")
        say(store, 2, "en fait parlons de la tresorerie")
    else:
        say(store, 1, "la marge est a douze pourcent")
        text = "pourquoi la marge baisse ?"
    service = build_service(store, clock=clock, speculative=S10Speculative())
    opened = open_turn(service, clock, text)
    assert opened.plan is not None and opened.plan.action is action, "la garde n'est pas atteinte"
    return opened.plan


# ==========================================================================
# 1. Vocabulaire réutilisé, autorité nulle
# ==========================================================================


def test_intent_vocabulary_reuses_existing_enums():
    """Aucune énumération de parole nouvelle ; les noms du handoff sont mappés."""

    hints = {field.name: field.type for field in dataclasses.fields(PresentationOutputIntent)}
    assert hints["situation"] == "PresentationSituation"
    assert hints["disposition"] == "OutputDisposition"
    assert hints["speech_ceiling"] == "tuple[SpeechKind, ...]"
    assert "speech" not in hints and "kind" not in hints, "noms du handoff mappés, pas recopiés"

    defined = {
        obj for _, obj in inspect.getmembers(presentation_intent, inspect.isclass)
        if issubclass(obj, Enum) and obj.__module__ == presentation_intent.__name__
    }
    assert defined == {DisplaySemantic, IntentUrgency}
    values = {item.value for enum in defined for item in enum}
    assert not values & {kind.value for kind in SpeechKind}
    assert not values & {"concise", "normal", "none"}, "pas d'énumération de parole du handoff"

    doc = presentation_intent.__doc__ or ""
    for mapping in ("`kind` du handoff → `situation", "`speech` du handoff",
                    "`display` du handoff", "`urgency` du handoff"):
        assert mapping in doc, mapping


async def test_intent_never_authorizes_actions():
    assert PresentationOutputIntent.authorizes_actions is False
    intents = [intent_for_plan(await _plan(action)) for action in AddressedTurnAction]
    intents.append(intent_for_attention(_attention()))
    for intent in intents:
        assert intent.authorizes_actions is False
        assert intent.to_trace_payload()["authorizes_actions"] is False
        # `ClassVar` : `replace` ne peut pas le retourner.
        with pytest.raises(TypeError):
            dataclasses.replace(intent, authorizes_actions=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        intents[0].authorizes_actions = True  # type: ignore[misc]


# ==========================================================================
# 2. Une intention par action du tour adressé
# ==========================================================================


async def test_intent_per_addressed_action():
    show = intent_for_plan(await _plan(AddressedTurnAction.SHOW_PREPARED))
    assert show.display == DisplayIntent(DisplaySemantic.REVEAL_PREPARED, ("r-courbe",))
    assert show.urgency is IntentUrgency.IMMEDIATE
    assert show.disposition is OutputDisposition.VISUAL_ONLY
    assert show.speech_ceiling == ()
    assert show.correlation_id == "corr-1"
    assert show.context_refs == ("u-001", "r-courbe")

    clarify = intent_for_plan(await _plan(AddressedTurnAction.CLARIFY))
    assert clarify.display is None
    assert clarify.speech_ceiling == (SpeechKind.QUESTION,)
    assert clarify.disposition.speaks and not clarify.disposition.shows
    assert may_speak(clarify.situation, SpeechKind.QUESTION), "plafond lu sur la matrice"
    assert set(clarify.context_refs) >= {"r-a", "r-b"}

    refresh = intent_for_plan(await _plan(AddressedTurnAction.REFRESH))
    assert refresh.display is None
    assert refresh.urgency is IntentUrgency.OPPORTUNISTIC
    assert refresh.disposition is OutputDisposition.SILENT
    assert refresh.speech_ceiling == ()

    ask = intent_for_plan(await _plan(AddressedTurnAction.ASK_BRAIN))
    assert ask.display is None
    assert ask.situation is PresentationSituation.KNOWLEDGE_QUESTION
    assert ask.disposition is OutputDisposition.VISUAL_AND_VOICE
    assert ask.speech_ceiling == (SpeechKind.QUESTION, SpeechKind.RESULT)


async def test_outcome_action_overrides_the_plan():
    """Une révélation refusée devient un rafraîchissement : l'intention dit ce qui s'est fait."""

    plan = await _plan(AddressedTurnAction.SHOW_PREPARED)
    outcome = type("Outcome", (), {"action": AddressedTurnAction.REFRESH})()
    intent = intent_for_plan(plan, outcome)
    assert intent.display is None and intent.reason == "addressed_refresh"


def test_attention_intent_visual_only():
    intent = intent_for_attention(_attention())
    assert intent.situation is PresentationSituation.FACT_CHECK_ATTENTION
    assert intent.disposition is OutputDisposition.VISUAL_ONLY
    assert intent.speech_ceiling == ()
    assert intent.display == DisplayIntent(DisplaySemantic.SHOW_ATTENTION, ("att-1",))
    for kind in SpeechKind:
        assert not may_speak(intent.situation, kind) or kind not in intent.speech_ceiling
    payload = json.dumps(intent.to_trace_payload(), ensure_ascii=False)
    assert "contredit" not in payload, "le motif d'attention est de la parole : jamais dans l'intention"
    with pytest.raises(PresentationIntentError):
        intent_for_attention(object())  # type: ignore[arg-type]


# ==========================================================================
# 3. Les invariants portés par la donnée
# ==========================================================================


def test_intent_refuses_speech_beyond_the_policy_and_text_refs():
    base = {
        "situation": PresentationSituation.VISUAL_COMMAND,
        "disposition": OutputDisposition.VISUAL_ONLY,
        "display": None, "urgency": IntentUrgency.IMMEDIATE, "reason": "r",
    }
    PresentationOutputIntent(**base)
    with pytest.raises(PresentationIntentError) as caught:
        PresentationOutputIntent(**{**base, "disposition": OutputDisposition.VOICE_ONLY,
                                    "speech_ceiling": (SpeechKind.RESULT,)})
    assert caught.value.code == "presentation_intent_speech_beyond_policy"
    with pytest.raises(PresentationIntentError) as caught:
        PresentationOutputIntent(**{**base, "context_refs": ("la marge baisse",)})
    assert caught.value.code == "presentation_intent_ref_text"
    with pytest.raises(PresentationIntentError) as caught:
        PresentationOutputIntent(**{**base, "context_refs": tuple(f"r-{i}" for i in range(9))})
    assert caught.value.code == "presentation_intent_refs_overflow"
    PresentationOutputIntent(**{**base, "context_refs": tuple(f"r-{i}" for i in range(MAX_INTENT_CONTEXT_REFS))})
    with pytest.raises(PresentationIntentError) as caught:
        PresentationOutputIntent(**{**base, "disposition": OutputDisposition.SILENT,
                                    "display": DisplayIntent(DisplaySemantic.REVEAL_PREPARED, ("r-1",))})
    assert caught.value.code == "presentation_intent_display_hidden"
    with pytest.raises(PresentationIntentError):
        PresentationOutputIntent(**{**base, "reason": "une phrase entière"})


# ==========================================================================
# 4. Le tour adressé passe par le puits, et seulement par lui
# ==========================================================================


async def test_show_prepared_goes_through_sink_only():
    store = build_store()
    say(store, 1, "voici la courbe de marge")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    speculative = S10Speculative()
    sink = RecordingSink()
    journal = S10Journal()
    service = build_service(store, clock=clock, speculative=speculative, display=sink, journal=journal)

    opened = open_turn(service, clock, "montre-moi ca")
    outcome = await service.deliver(opened.plan)

    assert outcome.delivered and outcome.code == "addressed_resource_reused"
    assert speculative.reveals == [], "le service n'appelle plus la voie spéculative pour révéler"
    assert [intent.display for intent in sink.published] == [
        DisplayIntent(DisplaySemantic.REVEAL_PREPARED, ("r-courbe",))
    ]
    assert service.counters.revealed == 1
    assert service.counters.display_receipts == {"recorded": 1}
    kinds = journal.kinds()
    assert kinds.index("presentation.intent.published") < kinds.index("presentation.intent.receipt")
    assert kinds.index("presentation.intent.receipt") < kinds.index("presentation.addressed.reused")


async def test_a_refusing_sink_refreshes_and_says_so():
    store = build_store()
    say(store, 1, "voici la courbe de marge")
    topic(store, "u-001")
    resource(store, "u-001")
    clock = S10Clock()
    journal = S10Journal()
    sink = RecordingSink(receipt=DisplayReceipt(False, "sink_busy", detail="queue_full"))
    service = build_service(store, clock=clock, speculative=S10Speculative(), display=sink, journal=journal)

    outcome = await service.deliver(open_turn(service, clock, "montre-moi ca").plan)

    assert outcome.action is AddressedTurnAction.REFRESH
    assert service.counters.reveal_failures == 1
    refused = [e for e in journal.entries if e["data"].get("code") == "addressed_reveal_refused"]
    assert refused and refused[0]["data"]["receipt"] == "sink_busy"
    assert refused[0]["data"]["detail"] == "queue_full"


async def test_a_non_scene_resource_publishes_no_display_intent():
    store = build_store()
    say(store, 1, "voici le tableau de synthese")
    topic(store, "u-001")
    resource(store, "u-001", resource_id="r-tableau", kind=ResourceKind.DOCUMENT, locator="doc:synthese")
    clock = S10Clock()
    sink = RecordingSink()
    service = build_service(store, clock=clock, speculative=S10Speculative(), display=sink)

    outcome = await service.deliver(open_turn(service, clock, "montre-moi ca").plan)

    assert outcome.delivered
    assert sink.published == [], "rien à révéler : un document se réchauffe, il ne se montre pas"


async def test_explicit_turn_withdraws_speculative():
    store = build_store()
    say(store, 1, "voici la courbe de marge")
    clock = S10Clock()
    sink = RecordingSink(withdrawn=2)
    journal = S10Journal()
    service = build_service(store, clock=clock, speculative=S10Speculative(), display=sink, journal=journal)

    open_turn(service, clock, "montre-moi ca")

    assert sink.withdrawals == ["addressed_turn_armed"]
    assert service.counters.display_withdrawals == 1
    assert service.counters.display_withdrawn == 2
    assert "presentation_intent_withdrawn" in journal.codes()


async def test_direct_sink_withdraw_is_zero_and_said_in_the_trace():
    journal = S10Journal()
    sink = DirectSceneDisplaySink(S10Speculative(), journal=journal)
    assert sink.withdraw_speculative("addressed_turn_armed") == 0
    assert journal.codes() == ["display_withdraw_nothing_queued"]
    assert isinstance(sink, PresentationDisplaySink)


async def test_withdraw_lines_carry_the_turn_correlation():
    """Polish p10 : les deux lignes du retrait se relient au tour qui l'a causé.

    Le publieur et le puits direct partagent le journal, comme en production :
    `presentation.intent.withdrawn` et `presentation.display.withdraw_noop`
    portent la même corrélation. Sans tour (un appui, avant toute phrase),
    elles disent `None` plutôt qu'une chaîne vide."""

    journal = S10Journal()
    publisher = PresentationDisplayPublisher(
        DirectSceneDisplaySink(S10Speculative(), journal=journal), diagnostics=journal,
    )
    assert publisher.withdraw_speculative("addressed_vocative_turn", correlation_id="corr-p10") == 0
    assert publisher.withdraw_speculative("addressed_turn_armed") == 0

    lines = [(entry["kind"], entry["data"]) for entry in journal.entries]
    kinds = [kind for kind, _ in lines]
    assert kinds == ["presentation.display.withdraw_noop", "presentation.intent.withdrawn"] * 2
    assert [data["correlation_id"] for _, data in lines] == ["corr-p10", "corr-p10", None, None]


async def test_vocative_turn_without_window_withdraws_once_with_its_correlation():
    """Polish p11, côté service : le refus de fenêtre d'un vocatif **est** son autorisation.

    Un tour vocatif sans fenêtre retire le spéculatif une fois, sous sa
    corrélation ; une phrase de la salle ne retire rien ; un tour servi par
    une fenêtre a retiré à l'appui et ne retire pas une seconde fois, même
    quand sa phrase commence par « Jarvis »."""

    store = build_store()
    say(store, 1, "voici la courbe de marge")
    clock = S10Clock()
    sink = RecordingSink()
    service = build_service(store, clock=clock, speculative=S10Speculative(), display=sink,
                            journal=S10Journal())

    service.open("Jarvis, quel est le total ?", correlation_id="corr-voc")
    assert (sink.withdrawals, sink.correlations) == (["addressed_vocative_turn"], ["corr-voc"])

    service.open("la marge est de trente et un pour cent", correlation_id="corr-room")
    assert len(sink.withdrawals) == 1, "la salle ne retire rien"

    open_turn(service, clock, "Jarvis, montre-moi ça", correlation_id="corr-win")
    assert sink.withdrawals == ["addressed_vocative_turn", "addressed_turn_armed"]
    assert sink.correlations == ["corr-voc", "corr-win"]
    assert service.counters.display_withdrawals == 2


async def test_publisher_never_lets_a_withdraw_failure_through_and_reraises_publish_failures():
    class Broken:
        async def publish(self, intent):  # noqa: ANN001
            raise RuntimeError("puits injoignable")

        def withdraw_speculative(self, reason, *, correlation_id=""):  # noqa: ANN001
            raise RuntimeError("puits injoignable")

    journal = S10Journal()
    publisher = PresentationDisplayPublisher(Broken(), diagnostics=journal)
    assert publisher.withdraw_speculative("x") == 0
    with pytest.raises(RuntimeError):
        await publisher.publish(intent_for_attention(_attention()))
    assert journal.codes(level="error") == [
        "presentation_intent_withdraw_failed", "presentation_intent_failed",
    ]
    assert "injoignable" not in journal.blob()


# ==========================================================================
# 5. L'adaptateur direct, contre le vrai monteur et les vrais outils de scène
# ==========================================================================


async def test_direct_sink_reveals_via_real_stager_and_scene_tools(core, tools):  # noqa: F811
    store = make_store()
    speak(store, "u1")
    stager = DisplaySceneStager(tools)
    finding = PreparedFinding(
        kind=ResourceKind.CHART_DESCRIPTOR, locator="chart:marges", title="Marges", stage_hidden=True,
    )
    speculative = make_service(store, ScriptedRunner((finding,)), stager=stager)
    assert stage_explicit(speculative, store, utterance_id="u1") is SpeculativeAdmission.ACCEPTED
    await speculative.drain()
    staged = store.snapshot.working_set.resources[0]
    object_id = staged.reference.locator
    assert staged.reference.kind is ResourceKind.SCENE_OBJECT
    assert (await scene_object(core, object_id))["visibility"] == "hidden"

    intent = PresentationOutputIntent(
        situation=PresentationSituation.VISUAL_COMMAND, disposition=OutputDisposition.VISUAL_ONLY,
        display=DisplayIntent(DisplaySemantic.REVEAL_PREPARED, (staged.resource_id,)),
        urgency=IntentUrgency.IMMEDIATE, reason="addressed_show_prepared",
    )
    receipt = await DirectSceneDisplaySink(speculative).publish(intent)

    assert receipt == DisplayReceipt(True, "display_revealed", detail="accepted")
    assert (await scene_object(core, object_id))["visibility"] == "visible"

    refused = await DirectSceneDisplaySink(speculative).publish(dataclasses.replace(
        intent, display=DisplayIntent(DisplaySemantic.REVEAL_PREPARED, ("inconnue",)),
    ))
    assert refused == DisplayReceipt(False, "display_reveal_refused", detail="rejected")
    attention = await DirectSceneDisplaySink(speculative).publish(intent_for_attention(_attention()))
    assert attention.delivered and attention.code == "display_attention_card_path"


# ==========================================================================
# 6. La trace du chemin composé : intention, puis effet
# ==========================================================================


async def test_composed_show_prepared_trace_orders_intent_before_reveal(tmp_path):
    """Agent-trace : `presentation.intent.published` précède `presentation.staging.revealed`.

    La pile est celle de production (`PresentationComposition.build`), avec
    des doubles aux bords et un **vrai** `RuntimeJournal` : c'est
    `trace.jsonl` qu'on lit, pas une liste en mémoire.
    """

    from jarvis.core.presentation_addressed_turn import REFRESH_CAPABILITIES

    journal = RuntimeJournal(tmp_path / "runtime")
    built, _, _, scene = composition(tmp_path, journal)
    built = dataclasses.replace(
        built, agent_factory=lambda tools: ScriptedAgent(json.dumps({"findings": [
            {"kind": "url", "locator": "https://example.org/bilan", "title": "Bilan Q3"},
        ]})),
    )
    stack = built.build("pres-intent-1")
    await stack.start()
    try:
        assert stack.store.observe("pres-intent-1", "u-001", "regardons le bilan Q3",
                                   origin=UtteranceOrigin.AMBIENT).applied
        assert stack.speculative.reserve_explicit(
            topic="addressed-u-001", capabilities=REFRESH_CAPABILITIES,
            utterance_id="u-001", text="addressed-u-001",
        ).value == "accepted"
        await stack.speculative.drain()
        assert scene.created and scene.revealed == []

        trigger = ExplicitAddressTrigger.admitted(
            ExplicitAddressSource.MANUAL_KEY, "f9", sequence=0, clock=built.clock,
        )
        assert stack.turns.arm(trigger, correlation_id="corr-trace").applied
        opened = stack.turns.open("montre-moi ça", correlation_id="corr-trace")
        assert opened.plan is not None and opened.plan.action is AddressedTurnAction.SHOW_PREPARED
        outcome = await stack.turns.deliver(opened.plan)
        assert outcome.delivered and scene.revealed == [scene.created[0]["object_id"]]
    finally:
        await stack.stop("test")

    lines = [json.loads(line) for line in journal.trace_path.read_text(encoding="utf-8").splitlines()]
    kinds = [line.get("kind") for line in lines]
    for needed in ("presentation.display.withdraw_noop", "presentation.intent.withdrawn",
                   "presentation.intent.published", "presentation.staging.revealed",
                   "presentation.intent.receipt", "presentation.addressed.reused"):
        assert needed in kinds, needed
    assert kinds.index("presentation.intent.withdrawn") < kinds.index("presentation.intent.published")
    # Polish p10 : les deux lignes du retrait portent la corrélation de l'appui.
    for kind in ("presentation.display.withdraw_noop", "presentation.intent.withdrawn"):
        assert lines[kinds.index(kind)]["data"]["correlation_id"] == "corr-trace", kind
    assert kinds.index("presentation.intent.published") < kinds.index("presentation.staging.revealed")
    assert kinds.index("presentation.staging.revealed") < kinds.index("presentation.intent.receipt")
    assert kinds.index("presentation.intent.receipt") < kinds.index("presentation.addressed.reused")
    published = lines[kinds.index("presentation.intent.published")]
    blob = json.dumps(published, ensure_ascii=False)
    assert "montre-moi" not in blob and "bilan Q3" not in blob, "identifiants et codes seulement"


# ==========================================================================
# 7. Fermeture d'import
# ==========================================================================


def _closure(module: str) -> set[str]:
    """Modules `jarvis` chargés par l'import de `module`, dans un interpréteur neuf."""

    code = (
        "import sys, json; before=set(sys.modules); "
        f"import {module}; "
        "print(json.dumps(sorted(m for m in set(sys.modules)-before "
        "if m.split('.')[0]=='jarvis')))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return set(json.loads(out.stdout))


def test_intent_and_port_modules_import_no_runtime_or_scene():
    """Égalité pour le port (liste blanche), et domaine pur pour l'intention."""

    port = _closure("jarvis.core.presentation_display")
    assert port == set(ALLOWED_IMPORT_CLOSURE), {
        "unexpected": sorted(port - set(ALLOWED_IMPORT_CLOSURE)),
        "declared_but_absent": sorted(set(ALLOWED_IMPORT_CLOSURE) - port),
    }
    assert {m for m in port if m.startswith("jarvis.core.")} == {"jarvis.core.presentation_display"}

    intent = _closure("jarvis.domain.presentation_intent")
    assert intent <= port
    assert all(m == "jarvis" or m.startswith("jarvis.domain") for m in intent), sorted(intent)

    for closure in (port, intent):
        for forbidden in closure:
            assert not forbidden.startswith(("jarvis.runtime", "jarvis.adapters")), forbidden
            assert "scene" not in forbidden and "display_mcp" not in forbidden, forbidden
