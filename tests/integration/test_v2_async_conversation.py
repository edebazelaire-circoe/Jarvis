"""Conversation asynchrone de bout en bout (tâche 11).

Preuve d'ensemble de l'architecture : ce n'est plus une couche qui est
vérifiée, mais leur assemblage. Chaque scénario part d'une phrase de
l'utilisateur et va jusqu'à ce qu'il entend — en traversant le bridge, le
protocole local, `BrainOrchestrator`, le modèle fort et l'ordonnanceur de
parole.

Le harnais est dans `async_conversation_harness.py`. Trois doubles seulement :
la session Realtime, le périphérique audio et le modèle fort. Aucun réseau,
aucun fournisseur, aucun micro.

Ce qui n'est **pas** prouvé ici, et reste une recette poste de travail
(tâche 12) : le comportement acoustique. Que le son cesse dans les
haut-parleurs, en combien de millisecondes, et si les haut-parleurs
redéclenchent le VAD, ne se mesure que sur la machine cible avec de vrais
périphériques. Ici, `abort()` est appelé sur un double et le curseur de lecture
est une comptabilité d'octets.
"""

from __future__ import annotations

import pytest

from jarvis.core.brain_service import (
    BRAIN_INTENT_REVISED,
    BRAIN_SPEECH_REQUESTED,
    BRAIN_TURN_ACCEPTED,
    BRAIN_WORK_COMPLETED,
    BRAIN_WORK_STARTED,
)
from jarvis.domain.v2 import (
    SPEECH_DELIVERY_PARTIAL,
    AddressingDecision,
    SpeechKind,
    SpeechProvenance,
    VoiceLifecycleState,
)
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.realtime_tools import tools_for
from tests.integration.async_conversation_harness import (
    CHUNK_MS,
    TOKEN,
    FakeAudio,
    FakeClock,
    voice_stack,
    wait_until,
)

# Les scénarios de concurrence sont rejoués : une course qui ne se produit
# qu'une fois sur trois n'est pas prouvée par un seul passage.
REPLAYS = [0, 1, 2]


# ---------------------------------------------------------------------------
# 1. Tâche longue : accusé rapide, progression, résultat
# ---------------------------------------------------------------------------


async def test_a_long_task_acks_fast_then_speaks_progress_then_the_result(tmp_path, monkeypatch):
    """Étape 4 du TASK : la surface accuse tout de suite, le cerveau parle ensuite.

    Ce que ce scénario établit, et qu'aucun test unitaire ne pouvait établir :
    l'accusé de la surface part **avant** que le modèle fort ait produit quoi
    que ce soit, la progression et le résultat traversent le websocket
    `/v1/events` réel, et l'historique distingue les deux provenances.
    """

    async with voice_stack(tmp_path, monkeypatch) as stack:
        await stack.wake()

        handle = await stack.user_says("Prépare mon dossier de vol.")

        # L'ingress a rendu la main alors que le modèle fort n'a rien produit :
        # le tour est en vol, et la surface est déjà libre de parler.
        assert stack.core.brain.active_turn_count == 1
        await stack.session.surface_reflex("Je m'en occupe.")
        await stack.journal.wait_until(lambda: stack.journal.count("voice.assistant") == 1)

        await handle.start_work("work-1", label="lecture du dossier")
        progress = await handle.say("Je regarde les vols de demain.", work_id="work-1")
        await stack.wait_spoken(1)
        assert stack.session.texts() == ["Je regarde les vols de demain."]
        assert stack.session.active_output_id in stack.session._reserved_outputs
        assert stack.session.spoken[0].source.correlation_id == handle.correlation_id
        await stack.speak_and_finish(transcript=progress.text)

        result = await handle.say(
            "Ton vol part à 7 h 40, porte B12.",
            kind=SpeechKind.RESULT,
            work_id="work-1",
        )
        await handle.complete_work("work-1", summary=result.text)
        handle.finish(public_summary=result.text)

        await stack.wait_spoken(2)
        await stack.speak_and_finish(transcript=result.text)

        # Ce que l'utilisateur a entendu, dans l'ordre.
        assert stack.session.texts() == [
            "Je regarde les vols de demain.",
            "Ton vol part à 7 h 40, porte B12.",
        ]

        # Ce que Core a publié, dans l'ordre causal.
        await stack.events.wait_for(BRAIN_WORK_COMPLETED)
        published = [kind for kind in stack.events.types() if kind.startswith("brain.")]
        assert published.index(BRAIN_TURN_ACCEPTED) < published.index(BRAIN_WORK_STARTED)
        assert published.index(BRAIN_WORK_STARTED) < published.index(BRAIN_SPEECH_REQUESTED)
        assert BRAIN_WORK_COMPLETED in published

        # L'historique : un accusé de surface, puis deux paroles du cerveau.
        assistant = await stack.wait_for_assistant_turns(3)
        assert [turn.content for turn in assistant] == [
            "Je m'en occupe.",
            "Je regarde les vols de demain.",
            "Ton vol part à 7 h 40, porte B12.",
        ]
        assert assistant[0].metadata["provenance"] == SpeechProvenance.SURFACE_REFLEX.value
        assert [turn.metadata["provenance"] for turn in assistant[1:]] == [
            SpeechProvenance.BRAIN.value,
            SpeechProvenance.BRAIN.value,
        ]
        assert assistant[2].metadata["speech_kind"] == SpeechKind.RESULT.value
        assert assistant[2].metadata["work_id"] == "work-1"
        # Aucune parole n'a été marquée partiellement entendue : rien n'a été coupé.
        assert all(turn.metadata.get("delivery") is None for turn in assistant[1:])

        # Le tour utilisateur a été écrit une fois, par le seul chemin autoritaire.
        user = await stack.user_turns()
        assert [turn.content for turn in user] == ["Prépare mon dossier de vol."]
        assert user[0].metadata["authoritative"] is True

        assert stack.runtime.runtime.state is VoiceLifecycleState.ACTIVE


async def test_no_core_tool_is_executed_from_the_surface_in_continuous_mode(tmp_path, monkeypatch):
    """Décision 34 : le catalogue est vide, et rien ne s'exécute par la surface.

    Deux garanties, et il en faut deux, chacune exercée ici :

    - le catalogue vide empêche le modèle de surface de demander une action ;
    - le refus du bridge fait que, même si un appel arrivait quand même — outil
      hérité `claude_task` **ou** n'importe quel outil Core, ici `drive_delete` —
      aucun outil Core ne s'exécuterait. Le second cas échoue bruyamment : trace
      de niveau `error` et erreur d'outil rendue au fournisseur.
    """

    assert tools_for(continuous_brain=True) == []

    async with voice_stack(tmp_path, monkeypatch) as stack:
        executed: list[str] = []
        original = stack.core.tools.call

        async def spy(name, arguments, *, conversation_id=None):  # noqa: ANN001
            executed.append(name)
            return await original(name, arguments, conversation_id=conversation_id)

        monkeypatch.setattr(stack.core.tools, "call", spy)

        await stack.wake()
        handle = await stack.user_says("Jarvis, supprime ce fichier du Drive.")

        # La surface tente quand même l'outil hérité : le bridge répond que le
        # cerveau possède déjà la demande, sans rien exécuter.
        await stack.session.tool_call("claude_task", {"request": "supprime ce fichier"})
        await wait_until(lambda: stack.session.tool_results, message="résultat d'outil rendu")

        call_id, result = stack.session.tool_results[0]
        assert call_id == "call-1"
        assert result["code"] == "brain_owns_the_request"
        assert result["spoken"] == ""
        assert executed == []

        # Un tout autre outil, réellement exposé par Core hors mode continu :
        # il est refusé avant tout appel, et le refus est bruyant.
        assert "drive_delete" in {tool["name"] for tool in tools_for(continuous_brain=False)}
        await stack.session.tool_call("drive_delete", {"file_id": "abc"}, call_id="call-2")
        await wait_until(lambda: len(stack.session.tool_results) >= 2, message="refus d'outil rendu")

        call_id, result = stack.session.tool_results[1]
        assert call_id == "call-2"
        assert result["ok"] is False
        assert result["code"] == "surface_tool_forbidden_in_continuous"
        assert result["spoken"] == ""
        assert "drive_delete" in str(result["error"])
        assert executed == []
        refusals = stack.journal.of("tool.refused")
        assert [event["message"] for event in refusals] == ["drive_delete"]
        assert refusals[0]["level"] == "error"
        assert refusals[0]["data"]["code"] == "surface_tool_forbidden_in_continuous"

        # La demande, elle, est bien arrivée au cerveau.
        assert handle.turn.text == "Jarvis, supprime ce fichier du Drive."
        handle.finish(public_summary="")


# ---------------------------------------------------------------------------
# 2. Interruption : la sortie s'arrête, l'intention est révisée
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("replay", REPLAYS)
async def test_an_interruption_stops_the_output_and_the_result_follows_the_new_intent(tmp_path, monkeypatch, replay):
    """Étape 5 du TASK, et la course la plus serrée de l'architecture.

    L'utilisateur coupe une progression, donne une nouvelle intention, et le
    cerveau retire explicitement l'ancien travail pendant que la tâche du tour
    précédent essaie encore d'en publier le résultat. Trois invariants tiennent
    ensemble :

    - couper la parole n'annule rien : la révision du nouveau tour republie
      l'ancien travail dans `retained_work_ids` (Décision 35) ;
    - seule une décision nommée du cerveau retire du travail, et Core retient
      alors la parole devenue fausse plutôt que de laisser la surface en juger
      (Décision 13) ;
    - la phrase coupée est persistée entière mais marquée partiellement
      entendue (Décision 36).
    """

    del replay
    async with voice_stack(tmp_path, monkeypatch) as stack:
        await stack.wake()

        first = await stack.user_says("Prépare mon dossier de vol.")
        await first.start_work("work-1", label="lecture du dossier")
        progress = await first.say("Je regarde tous les vols de la semaine.", work_id="work-1")
        await stack.wait_spoken(1)

        # JARVIS parle depuis 200 ms quand l'utilisateur reprend la parole.
        await stack.session.play_audio(chunks=2)
        await wait_until(lambda: stack.audio.played_output_ms >= 2 * CHUNK_MS, message="audio joué")
        await stack.session.interrupt()
        await stack.journal.wait_until(lambda: stack.journal.count("voice.barge_in") == 1)

        # La sortie a été coupée localement d'abord, puis chez le fournisseur.
        assert stack.audio.stop_output_calls == 1
        cursor = stack.session.cancelled_cursors[-1]
        assert cursor is not None and cursor.speech_id == progress.id
        assert cursor.played_ms == 2 * CHUNK_MS
        assert [c.speech_id for c in stack.session.truncated_cursors] == [progress.id]
        # Le micro n'a pas été refermé : le tour de l'utilisateur commence
        # justement par la phrase qui coupe JARVIS.
        assert stack.audio.stop_input_calls == 0
        assert stack.session.closed is False

        second = await stack.user_says("En fait, seulement le vol de Paul.")
        assert stack.core.brain.active_turn_count == 2

        # Interrompre n'est pas annuler : le travail en cours est explicitement
        # retenu par la révision que publie le nouveau tour (la deuxième : le
        # premier tour en avait déjà publié une, aux listes vides).
        revision = await stack.events.wait_for(BRAIN_INTENT_REVISED, count=2)
        assert revision.payload["retained_work_ids"] == ["work-1"]
        assert revision.payload["cancelled_work_ids"] == []
        assert stack.core.brain.working_state(stack.conversation_id).active_work_ids == ("work-1",)

        # Le cerveau, lui, décide : l'ancien travail est annulé, le nouveau
        # répond à la dernière intention.
        await second.cancel_work("work-1")
        cancellation = await stack.events.wait_for(BRAIN_INTENT_REVISED, count=3)
        assert cancellation.payload["cancelled_work_ids"] == ["work-1"]
        assert cancellation.payload["retained_work_ids"] == []

        # Course : la tâche du premier tour publie son résultat après coup.
        # Core le retient, il n'atteint jamais la surface.
        stale = await first.say("Voici les sept vols de la semaine.", kind=SpeechKind.RESULT, work_id="work-1")
        first.finish(public_summary="")
        await wait_until(
            lambda: stack.core_journal.count("core.brain.speech_dropped") == 1,
            message="parole périmée retenue par Core",
        )

        await second.start_work("work-2", label="vol de Paul")
        final = await second.say("Le vol de Paul part à 7 h 40.", kind=SpeechKind.RESULT, work_id="work-2")
        await second.complete_work("work-2", summary=final.text)
        second.finish(public_summary=final.text)

        await stack.wait_spoken(2)
        await stack.speak_and_finish(transcript=final.text)

        # Ce que l'utilisateur a entendu : la progression coupée, puis le
        # résultat de la **dernière** intention. Jamais le résultat périmé.
        assert stack.session.texts() == [progress.text, final.text]
        assert stale.text not in stack.session.texts()

        assistant = await stack.wait_for_assistant_turns(2)
        cut = next(turn for turn in assistant if turn.content == progress.text)
        # Le texte n'est pas réécrit (Décision 13), mais l'historique dit qu'il
        # n'a pas été entendu jusqu'au bout (Décision 36).
        assert cut.metadata["delivery"] == SPEECH_DELIVERY_PARTIAL
        assert cut.metadata["played_ms"] == 2 * CHUNK_MS

        # Une phrase partielle n'entre pas dans les faits publics connus.
        await wait_until(
            lambda: final.text in stack.core.brain.working_state(stack.conversation_id).known_public_facts,
            message="résultat inscrit dans l'état public",
        )
        state = await stack.core.brain.rehydrate(stack.conversation_id)
        assert progress.text not in state["known_public_facts"]
        assert final.text in state["known_public_facts"]

        # Le tour qui a coupé porte l'identifiant de la parole interrompue.
        user = await stack.user_turns()
        assert user[-1].metadata["interrupted_speech_id"] == progress.id
        assert stack.runtime.runtime.state is VoiceLifecycleState.ACTIVE


# ---------------------------------------------------------------------------
# 3. « Jarvis Mute » pendant le travail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("replay", REPLAYS)
async def test_jarvis_mute_leaves_the_work_in_core_and_speaks_nothing_stale(tmp_path, monkeypatch, replay):
    """Étape 6 du TASK : Décisions 11, 33 et 31 réunies dans une seule séquence.

    Le mute arrive pendant que le cerveau travaille. Le travail se termine dans
    Core, sa parole périme au lieu d'être mise de côté, aucune reprise surprise
    n'a lieu.

    Le partage de la reprise est celui que tranche la Décision 38 : le résultat
    manqué revient au **cerveau**, par l'état public passé à `run_turn` au tour
    suivant ; la **surface**, elle, ne reçoit rien à la réactivation, parce que
    la Décision 34 lui interdit d'énoncer un résultat substantiel.
    """

    del replay
    async with voice_stack(tmp_path, monkeypatch) as stack:
        await stack.wake()
        first_session = stack.session

        handle = await stack.user_says("Prépare mon dossier de vol.")
        await handle.start_work("work-1", label="lecture du dossier")
        conversation_id = stack.conversation_id

        # Course voulue : une parole est en file — la surface parle encore —
        # au moment précis où l'utilisateur coupe la voix.
        await first_session.push("realtime.output_started", output_id="busy-1")
        queued = await handle.say("Je consulte la première compagnie.", work_id="work-1")
        await stack.journal.wait_until(lambda: stack.journal.count("voice.speech.queued") == 1)

        await first_session.user_says("Jarvis mute")
        await stack.wait_background()
        assert first_session.closed is True
        assert stack.audio.closed is True

        # La file n'est pas gardée pour « plus tard » : elle périme (Décision 33).
        expired = [event["data"] for event in stack.journal.of("voice.speech.expired")]
        assert [data["speech_id"] for data in expired] == [queued.id]
        assert [data["reason"] for data in expired] == ["voice_background"]
        assert expired[0]["correlation_id"] == handle.correlation_id
        assert expired[0]["conversation_id"] == conversation_id
        assert expired[0]["work_id"] == "work-1"

        # Le travail n'a pas été touché : ni annulé, ni interrompu.
        assert stack.core.brain.active_turn_count == 1
        assert stack.core.brain.working_state(conversation_id).active_work_ids == ("work-1",)
        assert stack.core.health.ready is True

        # Le cerveau termine alors que plus personne n'écoute.
        result = await handle.say("Ton vol part à 7 h 40, porte B12.", kind=SpeechKind.RESULT, work_id="work-1")
        await handle.complete_work("work-1", summary=result.text)
        handle.finish(public_summary=result.text)
        await stack.events.wait_for(BRAIN_WORK_COMPLETED)
        await wait_until(lambda: stack.core.brain.active_turn_count == 0, message="tour cerveau soldé")

        # Core a publié les deux paroles ; la voix, au fond, n'en a dit aucune.
        assert [event.payload["text"] for event in stack.events.of(BRAIN_SPEECH_REQUESTED)] == [
            queued.text,
            result.text,
        ]
        assert first_session.spoken == []
        assert stack.wakeword.resumptions == 1

        # Réactivation : même conversation, aucune parole rejouée — ni celle
        # qui avait péri au mute, ni le résultat publié pendant le silence.
        # Un nouveau tour le prouve mieux qu'une attente : la session suivante
        # ne prononce que ce qui vient d'être demandé.
        await stack.wake()
        assert stack.session is not first_session
        assert stack.conversation_id == conversation_id

        again = await stack.user_says("Et le retour ?")
        # (a) Le chemin de reprise de la Décision 33 passe par le **cerveau** :
        # l'état public passé à `run_turn` porte le résultat que l'utilisateur
        # a manqué, donc le cerveau peut décider d'en reparler. C'est ce que la
        # Décision 38 constate et retient comme chemin de reprise réel.
        assert result.text in again.state.known_public_facts
        assert again.state.current_user_intent == "Et le retour ?"

        answer = await again.say("Retour lundi à 18 h.", kind=SpeechKind.RESULT, work_id="work-2")
        again.finish(public_summary=answer.text)
        await stack.wait_spoken(1)
        await stack.speak_and_finish(transcript=answer.text)
        assert stack.session.texts() == [answer.text]

        # Le même contenu est lisible par la projection de reprise.
        state = await stack.core.brain.rehydrate(conversation_id)
        assert result.text in state["known_public_facts"]
        assert state["active_work_ids"] == []

        # (b) La surface, elle, ne reçoit rien à la réactivation — et c'est
        # **voulu** (Décision 38). `activate()` ne lit que
        # `GET /v1/conversations/{id}/context`, qui ne rend que les tours
        # persistés ; une parole jamais prononcée n'y figure pas. Alimenter la
        # surface Realtime avec l'état public serait lui remettre un résultat
        # substantiel qu'elle n'a pas le droit d'énoncer (Décision 34, spec
        # section 9) : le silence au réveil est le comportement attendu, pas
        # un manque.
        context = await stack.client.context(conversation_id)
        assert result.text not in [turn["content"] for turn in context["recent_turns"]]


# ---------------------------------------------------------------------------
# 4. Bruit ambiant pendant LIVE
# ---------------------------------------------------------------------------


async def test_ambient_noise_during_live_does_not_keep_the_session_alive(tmp_path, monkeypatch):
    """Étape 7 du TASK : Décision 10, vérifiée sur la pile complète.

    Le pendant est vérifié dans le même scénario : un tour adressé, lui,
    réarme le délai. Sans les deux moitiés, le test ne prouverait qu'une
    session qui meurt.
    """

    clock = FakeClock()
    async with voice_stack(tmp_path, monkeypatch, clock=clock, active_timeout_s=10.0) as stack:
        await stack.wake()

        clock.advance(8)
        for partial in ("il", "il fait", "il fait beau"):
            await stack.session.push("realtime.transcript_delta", text=partial, item_id="item-ambient")
        ambient = "une longue conversation entre plusieurs personnes qui ne concerne pas du tout l'assistant"
        await stack.session.ambient(ambient)
        await stack.journal.wait_until(
            lambda: any(
                event["kind"] == "voice.transcript" and event["data"].get("addressing") != "addressed"
                for event in stack.journal.events
            )
        )

        clock.advance(3)
        assert stack.runtime.activity.expired() is True
        assert await stack.runtime.check_timeout() is True
        await stack.wait_background()
        assert stack.core.health.ready is True

        # Le pendant : réveillée, une phrase adressée — et l'accusé du cerveau
        # qu'elle déclenche — rendent du temps à l'utilisateur.
        await stack.wake()
        clock.advance(8)
        handle = await stack.user_says("Et demain ?")
        clock.advance(3)
        assert stack.runtime.activity.expired() is False
        assert await stack.runtime.check_timeout() is False
        assert stack.runtime.runtime.state is VoiceLifecycleState.ACTIVE
        handle.finish(public_summary="")


async def test_brain_work_in_flight_keeps_the_session_alive(tmp_path, monkeypatch):
    """Décision 32 : le cerveau qui travaille est de l'activité utile.

    Complément direct du scénario précédent : ce n'est pas le silence de la
    pièce qui compte, c'est qu'il se passe quelque chose d'utile — ici dans un
    autre processus, ce qui n'était pas observable avant la tâche 07.
    """

    clock = FakeClock()
    async with voice_stack(tmp_path, monkeypatch, clock=clock, active_timeout_s=10.0) as stack:
        await stack.wake()
        handle = await stack.user_says("Prépare mon dossier de vol.")

        clock.advance(8)
        assert stack.runtime.activity.expired() is False
        await handle.start_work("work-1", label="lecture du dossier")
        await stack.events.wait_for(BRAIN_WORK_STARTED)
        # L'évènement doit avoir traversé le websocket avant qu'on ne juge le délai.
        await wait_until(
            lambda: not stack.runtime.activity.expired(),
            message="activité réarmée par le cerveau",
        )

        clock.advance(9)
        assert stack.runtime.activity.expired() is False
        assert await stack.runtime.check_timeout() is False
        assert stack.runtime.runtime.state is VoiceLifecycleState.ACTIVE

        # Mais un cerveau muet finit par rendre la session : le délai repart du
        # **dernier** évènement, il n'est pas suspendu.
        clock.advance(11)
        assert stack.runtime.activity.expired() is True
        handle.finish(public_summary="")


# ---------------------------------------------------------------------------
# 5. Coupure et reprise du flux d'évènements Core
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("replay", REPLAYS)
async def test_the_core_event_stream_reconnects_without_replaying_stale_progress(tmp_path, monkeypatch, replay):
    """Étape 8 du TASK : Décisions 25 et 31.

    Le websocket `/v1/events` tombe pendant que le cerveau travaille. Deux
    paroles sont en jeu : une progression déjà en file, et une autre publiée
    pendant la coupure. Ni l'une ni l'autre ne doit être prononcée après la
    reprise — la première parce qu'un trou dans le flux la rend suspecte, la
    seconde parce que rien n'est rejoué. Le résultat, lui, arrive et se dit.
    """

    del replay
    async with voice_stack(tmp_path, monkeypatch) as stack:
        await stack.wake()

        handle = await stack.user_says("Prépare mon dossier de vol.")
        await handle.start_work("work-1", label="lecture du dossier")

        # Occuper la surface avec une sortie qui ne se termine pas : la
        # progression reste alors en file au lieu d'être dite tout de suite.
        await stack.session.push("realtime.output_started", output_id="busy-1")
        queued = await handle.say("Je consulte la première compagnie.", work_id="work-1")
        await stack.journal.wait_until(lambda: stack.journal.count("voice.speech.queued") == 1)
        assert stack.session.texts() == []

        # Le serveur tombe : l'abonné ne reçoit aucune erreur, juste le silence.
        await stack.server.stop()
        # Fermeture nette ou transport rompu : les deux sont des trous dans le
        # flux, et l'ordonnanceur les traite pareil — il se réabonne.
        await stack.journal.wait_until(
            lambda: stack.journal.count("voice.speech.stream_closed")
            + stack.journal.count("voice.speech.stream_failed")
            >= 1
        )
        # Décision 31 : ce qui attendait et n'est plus sûrement vrai est jeté.
        await stack.journal.wait_until(
            lambda: any(
                event["data"].get("reason") == "stream_gap"
                for event in stack.journal.of("voice.speech.superseded")
            )
        )
        assert stack.runtime.runtime.state is VoiceLifecycleState.ACTIVE

        # Publiée pendant la coupure : personne ne l'écoute, et elle ne sera
        # jamais rejouée.
        lost = await handle.say("Je consulte la deuxième compagnie.", work_id="work-1")

        stack.server = LocalProtocolServer(stack.core, host="127.0.0.1", port=stack.port, token=TOKEN)
        await stack.server.start()
        await wait_until(
            lambda: stack.core.events.subscriber_count >= stack._expected_subscribers(),
            message="ordonnanceur réabonné après la coupure",
        )

        result = await handle.say("Ton vol part à 7 h 40, porte B12.", kind=SpeechKind.RESULT, work_id="work-1")
        await handle.complete_work("work-1", summary=result.text)
        handle.finish(public_summary=result.text)

        await stack.session.push("realtime.response_done", output_id="busy-1", status="completed")
        await stack.wait_spoken(1)
        await stack.speak_and_finish(transcript=result.text)

        # Seul le résultat est prononcé : les deux progressions sont perdues,
        # et c'est le comportement voulu.
        assert stack.session.texts() == [result.text]
        assert queued.text not in stack.session.texts()
        assert lost.text not in stack.session.texts()


async def test_a_republished_speech_is_never_spoken_twice(tmp_path, monkeypatch):
    """Concurrence : un doublon d'évènement ne fait pas répéter JARVIS.

    Core n'émet normalement chaque parole qu'une fois, mais rien dans le
    transport ne l'interdit — une reconnexion, un backend bavard. Répéter une
    phrase à voix haute est une régression visible ; l'ordonnanceur déduplique
    donc par `speech_id`.
    """

    async with voice_stack(tmp_path, monkeypatch) as stack:
        await stack.wake()
        handle = await stack.user_says("Prépare mon dossier de vol.")
        result = await handle.say("Ton vol part à 7 h 40.", kind=SpeechKind.RESULT, work_id="work-1")
        await stack.wait_spoken(1)

        await handle.resend(result)
        await stack.journal.wait_until(
            lambda: any(
                event["data"].get("reason") == "duplicate_speech_id"
                for event in stack.journal.of("voice.speech.ignored")
            )
        )
        assert stack.session.texts() == [result.text]

        await stack.speak_and_finish(transcript=result.text)
        handle.finish(public_summary=result.text)
        assistant = await stack.wait_for_assistant_turns(1)
        assert [turn.content for turn in assistant] == [result.text]


# ---------------------------------------------------------------------------
# 6. Plusieurs tours dans une seule session
# ---------------------------------------------------------------------------


async def test_three_turns_run_in_one_session_without_a_second_wake(tmp_path, monkeypatch):
    """Garde-fou anti-régression : la session LIVE couvre toute la conversation.

    Un seul éveil, un seul micro, une seule session, trois tours — et trois
    tours utilisateur persistés, pas six : le double chemin d'écriture que la
    Décision 30 interdit se verrait ici immédiatement.
    """

    async with voice_stack(tmp_path, monkeypatch) as stack:
        await stack.wake()
        session = stack.session

        for index in (1, 2, 3):
            handle = await stack.user_says(f"Question numéro {index} ?")
            answer = await handle.say(
                f"Réponse numéro {index}.",
                kind=SpeechKind.RESULT,
                work_id=f"work-{index}",
            )
            handle.finish(public_summary=answer.text)
            await stack.wait_spoken(index)
            await stack.speak_and_finish(transcript=answer.text)
            assert stack.runtime.runtime.state is VoiceLifecycleState.ACTIVE

        assert session.texts() == ["Réponse numéro 1.", "Réponse numéro 2.", "Réponse numéro 3."]
        assert stack.sessions == [session]
        assert session.closed is False
        assert session.finish_calls == 0
        assert len(FakeAudio.instances) == 1
        assert stack.audio.stop_input_calls == 0
        assert stack.wakeword.suspensions == 1

        user = await stack.user_turns()
        assert [turn.content for turn in user] == [
            "Question numéro 1 ?",
            "Question numéro 2 ?",
            "Question numéro 3 ?",
        ]
        assert len({turn.correlation_id for turn in user}) == 3
        assistant = await stack.wait_for_assistant_turns(3)
        assert [turn.content for turn in assistant] == [
            "Réponse numéro 1.",
            "Réponse numéro 2.",
            "Réponse numéro 3.",
        ]


# ---------------------------------------------------------------------------
# 10. Adressage incertain : le doute ne devient pas la vérité de Core
# ---------------------------------------------------------------------------


async def test_an_overheard_sentence_never_becomes_the_truth_core_states(tmp_path, monkeypatch):
    """Décision 44, moitié aval, sur la pile complète.

    Une phrase longue qui ne commence pas par « jarvis » est classée
    `uncertain` : depuis la Décision 44 la surface la route au lieu de la
    jeter. Ce scénario prouve la conséquence qui manquait — tant que le cerveau
    n'a pas montré qu'il prenait ce tour, l'intention courante et la question
    ouverte de Core survivent, et c'est **cet** état-là que la Décision 45
    remet au cerveau avec le tour.
    """

    async with voice_stack(tmp_path, monkeypatch) as stack:
        await stack.wake()

        first = await stack.user_says("Jarvis prépare mon dossier de vol.")
        question = await first.say("Quelle compagnie ?", kind=SpeechKind.QUESTION, work_id="work-1")
        await stack.wait_spoken(1)
        await stack.speak_and_finish(transcript=question.text)

        before = stack.core.brain.working_state(stack.conversation_id)
        assert before.current_user_intent == "Jarvis prépare mon dossier de vol."
        assert before.unresolved_questions == ("Quelle compagnie ?",)

        overheard = await stack.user_says(
            "il faudrait vraiment que quelqu un rappelle le plombier demain matin"
        )
        assert overheard.turn.addressing is AddressingDecision.UNCERTAIN
        # Ce que Core affirme au cerveau pour ce tour-là est encore la vérité
        # d'avant, pas la phrase captée.
        assert overheard.state.current_user_intent == "Jarvis prépare mon dossier de vol."
        assert overheard.state.unresolved_questions == ("Quelle compagnie ?",)

        # Le cerveau se récuse : `[pas-pour-moi]` arrive ici en résumé vide.
        overheard.finish(public_summary="")
        await wait_until(
            lambda: overheard.correlation_id not in stack.core.brain._tasks,  # noqa: SLF001
            message="tour incertain soldé",
        )

        after = stack.core.brain.working_state(stack.conversation_id)
        assert after.current_user_intent == "Jarvis prépare mon dossier de vol."
        assert after.unresolved_questions == ("Quelle compagnie ?",)
        assert after.revision == before.revision
        # Le tour reste écrit : ce qui a été dit a été dit (Décisions 06 et 30).
        user = await stack.user_turns()
        assert [turn.content for turn in user] == [
            "Jarvis prépare mon dossier de vol.",
            "il faudrait vraiment que quelqu un rappelle le plombier demain matin",
        ]
        assert user[1].metadata["addressing"] == "uncertain"

        first.finish(public_summary="")
