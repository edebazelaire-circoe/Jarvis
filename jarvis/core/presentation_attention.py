"""Le service qui lève — ou refuse — un point d'attention de Presentation.

Slice 09. Entre la voie spéculative (Slice 08), qui rend un verdict de
vérification, et deux sorties : l'ensemble de travail de la Slice 04, qui range
le point d'attention, et la trace, que le Control Center suit déjà pour ses
pastilles d'arrière-plan.

## Pourquoi il ne fait que ça

La décision — *cette vérification mérite-t-elle un signal ?* — est une fonction
pure du domaine (`decide_attention`). Ce service ne la réimplémente pas : il
lui fournit l'instantané, compte ce qu'elle répond, range ce qu'elle accepte, et
journalise. Cette séparation est ce qui rend la règle testable sans horloge,
sans magasin et sans journal.

## Ce qu'il ne fait jamais

Il ne parle pas, et il ne peut pas demander qu'on parle. D11 est tenue à trois
niveaux, et c'est voulu :

1. **la matrice de la Slice 07** — `may_speak(FACT_CHECK_ATTENTION, k)` est faux
   pour toute nature `k`, parce que la ligne porte `requires_explicit_address=
   False` et aucune `safety_speech_kinds` ;
2. **le type de l'événement** — `PresentationAttention` n'a aucun champ de
   parole, et deux `ClassVar` que `dataclasses.replace` ne peut pas retourner ;
3. **la fermeture d'imports**, déclarée en liste **blanche**
   (`ALLOWED_IMPORT_CLOSURE`), sur le modèle de la garde de la Slice 06 — parce
   qu'une liste d'interdiction laisse toujours passer l'import auquel personne
   n'a pensé, et que QA était passée à travers les deux denylists de la Slice 06.

Sur le troisième point, la phrase honnête n'est pas « aucune arête vers quoi
que ce soit qui parle ». Le **vocabulaire** de parole est dans la fermeture :
`presentation_policy` a besoin de `SpeechKind`, et c'est précisément ce qu'on
veut, puisque c'est lui qui rend `may_speak` lisible depuis ici. Ce qui n'y est
pas, et ce que la garde tient, c'est tout **producteur** de parole —
l'ordonnanceur, le cerveau, la voix, le registre d'outils — et plus
généralement tout `jarvis.core.*` autre que ce module.

## Le son, et qui le décide

Ce service ne joue aucun son : il pose une ligne de trace. Le registre
d'arrière-plan la classe en `attention`, le compteur de séquence monte, et
c'est le navigateur qui décide d'émettre le signal — une fois, sur une hausse
de séquence, et dans un seul onglet. La déduplication *sémantique* (deux fois
la même contradiction sur la même affirmation) est tenue plus bas encore, par
la coalescence du magasin de la Slice 04 sur `(catégorie, affirmation, sujet)` :
un point coalescé ne fait pas monter la séquence de la trace, donc ne sonne pas.

## L'acquittement ne touche pas les faits

Le Control Center acquitte des **pastilles**, dans son propre processus, sur un
registre en mémoire alimenté par la trace. Il n'a aucun chemin vers ce service
ni vers le magasin : écarter un avertissement ne peut donc pas modifier
l'ensemble de travail, et ce n'est pas une discipline, c'est une absence
d'arête.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable

from jarvis.domain.presentation_attention import (
    ATTENTION_RAISED_KIND,
    AttentionDecision,
    AttentionRefusal,
    FactCheckAssessment,
    PresentationAttention,
    decide_attention,
)
from jarvis.domain.presentation_working_set import PresentationObservation
from jarvis.ports.v2 import DiagnosticSink

#: Points d'attention levés dans une même remise. La Slice 04 en garde huit au
#: total ; en accepter davantage d'un coup ne ferait qu'en évincer d'autres
#: aussitôt, et ferait sonner une rafale là où D11 demande de la discrétion.
MAX_ATTENTION_PER_BATCH = 2


@dataclass(slots=True)
class AttentionCounters:
    """Tout ce que la porte a fait, en nombres. Aucun texte, jamais.

    Même raison qu'en Slice 04 et 08 : un invariant qu'on ne peut pas lire est
    un invariant qui dérive. Chaque refus a son propre compteur, sous le code
    exact de `AttentionRefusal`, pour qu'aucun ne soit rangé dans un fourre-tout.
    """

    assessed: int = 0
    raised: int = 0
    clipped_batch: int = 0
    #: Lots qui ne sont pas itérables. L'appelant s'est trompé ; cette voie le
    #: compte plutôt que de lever, comme tout le reste ici.
    batches_invalid: int = 0
    #: Le magasin a **levé** au lieu de refuser. Il est total par construction,
    #: mais c'est un `Any` injecté : la Slice 06 a payé exactement cette
    #: distinction sur son puits d'observation.
    store_failed: int = 0
    #: Refusé par `decide_attention`, compté sous le code du refus.
    refusals: dict[str, int] = field(default_factory=dict)
    #: Dispositions rendues par le magasin de la Slice 04, une à une.
    store_dispositions: dict[str, int] = field(default_factory=dict)
    #: Acceptés par la porte mais refusés par le magasin. Un signal *n'a donc
    #: pas* été rangé, et il faut pouvoir le compter séparément d'un refus de
    #: politique : les deux sont « pas d'alerte », pour des raisons opposées.
    dropped_by_store: int = 0
    #: Coalescés par le magasin : la même contradiction, déjà signalée.
    coalesced: int = 0
    #: Échecs du puits de diagnostic lui-même. Sans ce compteur, une trace
    #: cassée rend la voie muette tout en la laissant se déclarer en forme.
    diagnostic_failures: int = 0

    def refuse(self, refusal: AttentionRefusal) -> None:
        self.refusals[refusal.value] = self.refusals.get(refusal.value, 0) + 1

    def store(self, code: str) -> None:
        self.store_dispositions[code] = self.store_dispositions.get(code, 0) + 1

    def to_payload(self) -> dict[str, Any]:
        return {
            name: (dict(value) if isinstance(value, dict) else value)
            for name, value in ((f, getattr(self, f)) for f in self.__slots__)
        }


class PresentationAttentionService:
    """Juge une vérification, range ce qui passe, journalise tout.

    Ne lève jamais depuis `raise_from_assessments` : comme le magasin de la
    Slice 04 et la voie de la Slice 08, cette porte rend des valeurs typées —
    une exception se rattrape et se perd, une valeur se compte.
    """

    def __init__(
        self,
        *,
        store: Any,
        diagnostics: DiagnosticSink | None = None,
        clock: Callable[[], datetime] | None = None,
        max_per_batch: int = MAX_ATTENTION_PER_BATCH,
    ) -> None:
        if isinstance(max_per_batch, bool) or not isinstance(max_per_batch, int) or max_per_batch < 1:
            raise ValueError("max_per_batch must be a positive integer")
        self._store = store
        self._diagnostics = diagnostics
        self._clock = clock
        self._max_per_batch = int(max_per_batch)
        #: Les derniers points levés, lisibles. Même raison que
        #: `retired_resource_ids` en Slice 04 : sans une mémoire observable, un
        #: test ne peut pas distinguer « rien n'a été signalé » de « l'instantané
        #: n'a pas bougé ».
        self._raised_ids: tuple[str, ...] = ()
        self.counters = AttentionCounters()

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {"raised_ids": list(self._raised_ids), **self.counters.to_payload()}

    @property
    def raised_ids(self) -> tuple[str, ...]:
        return self._raised_ids

    # ------------------------------------------------------------------
    # La porte
    # ------------------------------------------------------------------

    def raise_from_assessments(
        self,
        assessments: Iterable[object],
        *,
        job_id: str,
        session_id: str,
        may_verify: bool,
    ) -> tuple[AttentionDecision, ...]:
        """Juger un lot de verdicts. Rend une décision par verdict, dans l'ordre.

        `may_verify` vient du jeton du travail (Slice 08) : une voie qui n'avait
        pas le droit de vérifier n'a pas le droit d'alerter. C'est la leçon la
        plus chère de la Slice 08 appliquée d'avance — *le seul effet durable de
        la voie était le seul que la table de capacités ne gardait pas* — et ici
        l'effet durable est le point d'attention rangé dans l'ensemble de
        travail, plus le son qu'il déclenche.
        """

        try:
            batch = list(assessments)
        except TypeError:
            self.counters.batches_invalid += 1
            self._trace(
                "batch_invalid", "Lot de verdicts non itérable", level="error",
                data={"job_id": job_id, "type": type(assessments).__name__},
            )
            return ()
        kept = batch[: self._max_per_batch]
        if len(batch) > len(kept):
            self.counters.clipped_batch += len(batch) - len(kept)
            self._trace(
                "batch_clipped", "Plus de verdicts que la borne par remise",
                level="warning",
                data={"job_id": job_id, "received": len(batch), "kept": len(kept)},
            )
        decisions: list[AttentionDecision] = []
        for index, assessment in enumerate(kept):
            decisions.append(self._judge(assessment, index, job_id=job_id,
                                         session_id=session_id, may_verify=may_verify))
        return tuple(decisions)

    def _judge(
        self,
        assessment: object,
        index: int,
        *,
        job_id: str,
        session_id: str,
        may_verify: bool,
    ) -> AttentionDecision:
        self.counters.assessed += 1
        attention_id = f"att-{job_id}-{index}"[:64]
        snapshot = getattr(self._store, "snapshot", None)
        working_set = getattr(snapshot, "working_set", None)
        claim_ids = frozenset(
            claim.record_id for claim in getattr(working_set, "claims", ()) or ()
        )
        source_ids = frozenset(
            source.record_id for source in getattr(working_set, "sources", ()) or ()
        )
        decision = decide_attention(
            assessment,
            attention_id=attention_id,
            # Une horloge qui lève est du code d'appelant : `None` traverse et
            # devient un refus typé, jamais une exception.
            raised_at=self._now(),
            known_claim_ids=claim_ids,
            known_source_ids=source_ids,
            may_verify=may_verify,
        )
        if decision.refusal is not None:
            self.counters.refuse(decision.refusal)
            # `info` : un verdict qui ne mérite pas d'alerte est le cas
            # **ordinaire**, pas une anomalie. Le journaliser à `warning`
            # remplirait la trace d'alarmes pour des vérifications réussies.
            self._trace(
                "not_raised", "Vérification sans signal", level="info",
                data={"job_id": job_id, "index": index, "code": decision.code,
                      "verdict": decision.verdict.value if decision.verdict else ""},
            )
            return decision
        raised = decision.raised
        if raised is None:  # pragma: no cover - `AttentionDecision` l'interdit
            return decision
        self._store_attention(raised, job_id=job_id, session_id=session_id)
        return decision

    def _store_attention(
        self, raised: PresentationAttention, *, job_id: str, session_id: str
    ) -> None:
        """Ranger le point d'attention, puis — et seulement alors — le signaler.

        L'ordre est la règle : **rien n'est signalé qui ne soit rangé.** Un son
        pour un point que l'ensemble de travail a refusé donnerait un
        avertissement que la Slice 10 ne pourrait pas expliquer si on le lui
        demandait, et `HV-PRES-ALERT-01` demande exactement cela.

        La coalescence du magasin est la déduplication sémantique : la même
        contradiction signalée deux fois rend `presentation_attention_coalesced`
        et **ne pose aucune nouvelle ligne de trace**, donc ne fait pas monter la
        séquence, donc ne sonne pas.
        """

        try:
            observation = PresentationObservation(
                observation_id=raised.attention_id, session_id=session_id, record=raised.to_item(),
            )
        except (TypeError, ValueError):
            self.counters.dropped_by_store += 1
            self._trace(
                "observation_refused", "Point d'attention non observable", level="error",
                data={"job_id": job_id, "attention_id": raised.attention_id},
            )
            return
        try:
            result = self._store.apply(observation)
        except Exception as exc:  # noqa: BLE001 - un magasin qui lève ne ferme pas la voie
            self.counters.store_failed += 1
            self._trace(
                "store_failed", "L'ensemble de travail a levé au lieu de refuser",
                level="error",
                data={"job_id": job_id, "attention_id": raised.attention_id,
                      "error_class": type(exc).__name__},
            )
            return
        code = str(getattr(result, "code", "") or "unknown")
        self.counters.store(code)
        if not bool(getattr(result, "applied", False)):
            self.counters.dropped_by_store += 1
            self._trace(
                "store_refused", "Point d'attention refusé par l'ensemble de travail",
                level="warning",
                data={"job_id": job_id, "attention_id": raised.attention_id, "code": code,
                      "disposition": _disposition_value(result)},
            )
            return
        if code.endswith("_coalesced"):
            # Rangé, mais fondu dans un point déjà signalé : pas de nouvelle
            # ligne, donc pas de second son pour la même contradiction.
            self.counters.coalesced += 1
            self._trace(
                "coalesced", "Contradiction déjà signalée : fondue dans le point existant",
                level="info",
                data={"job_id": job_id, "attention_id": raised.attention_id, "code": code},
            )
            return
        self.counters.raised += 1
        self._raised_ids = (self._raised_ids + (raised.attention_id,))[-16:]
        self._emit(raised, job_id=job_id)

    def _emit(self, raised: PresentationAttention, *, job_id: str) -> None:
        """La ligne que le Control Center suivra. Des références, jamais de parole.

        Le message est la phrase fixe de la catégorie et la charge utile est
        `to_trace_payload()`, qui laisse `reason` derrière lui. C'est la seule
        sortie de ce service vers un fichier durable.
        """

        self._trace(
            "raised", raised.headline, level="warning",
            data={"job_id": job_id, **raised.to_trace_payload()},
            kind=ATTENTION_RAISED_KIND,
        )

    # ------------------------------------------------------------------
    # Outils
    # ------------------------------------------------------------------

    def _now(self) -> datetime | None:
        """L'instant courant, ou `None` si l'horloge injectée casse.

        `None` descend dans `decide_attention`, qui le refuse typé. Rendre une
        heure inventée serait pire : la Slice 06 l'a écrit pour la provenance,
        et un horodatage faux sur un point d'attention est de la même famille.
        """

        if self._clock is not None:
            try:
                return self._clock()
            except Exception:  # noqa: BLE001 - une horloge d'appelant ne ferme pas la porte
                return None
        snapshot = getattr(self._store, "snapshot", None)
        as_of = getattr(snapshot, "as_of", None)
        if isinstance(as_of, datetime):
            return as_of
        from datetime import timezone

        return datetime.now(timezone.utc)

    def _trace(
        self,
        event: str,
        message: str,
        *,
        level: str = "info",
        data: dict[str, Any] | None = None,
        kind: str | None = None,
    ) -> None:
        """Journal : des identifiants, des nombres, des codes. Jamais de parole.

        Même règle et même raison qu'en Slices 04, 06 et 08. Aucun texte
        d'exception n'est repris non plus : un verdict arrive d'un exécutant à
        qui l'on a passé de la parole, et une exception qui recopierait son
        entrée la déposerait ici, dans un fichier durable.
        """

        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(
                kind or f"presentation.attention.{event}", message, level=level, data=data or {},
            )
        except Exception:  # noqa: BLE001 - un journal en panne n'arrête pas la voie qu'il observe
            # Mais il se compte : sans ce nombre, une trace morte et une voie
            # calme se lisent pareil, et c'est l'ambiguïté que tout ce module
            # combat.
            self.counters.diagnostic_failures += 1


def _disposition_value(result: object) -> str:
    disposition = getattr(result, "disposition", None)
    return getattr(disposition, "value", str(disposition))[:64]


#: Ce que ce module charge réellement, mesuré et **fermé**. Liste blanche : la
#: Slice 06 a montré qu'une liste d'interdiction laisse toujours passer l'import
#: auquel personne n'a pensé.
#:
#: Tout y est du domaine, des ports, ou ce module. Le vocabulaire de parole
#: (`voice_state`, `speech_presentation`, `voice_playback`) y entre par
#: `presentation_policy`, qui a besoin de `SpeechKind` pour que `may_speak` soit
#: lisible d'ici : c'est voulu, et c'est ce qui fait de D11 une lecture plutôt
#: qu'une promesse. Aucun **producteur** de parole n'y figure — ni
#: `jarvis.core.speech_scheduler`, ni le cerveau, ni la voix, ni le registre
#: d'outils — et aucun `jarvis.core.*` autre que ce module.
ALLOWED_IMPORT_CLOSURE: frozenset[str] = frozenset(
    {
        "jarvis",
        "jarvis.core",
        "jarvis.core.presentation_attention",
        "jarvis.domain",
        "jarvis.domain._checks",
        "jarvis.domain.back_brain",
        "jarvis.domain.brain_context",
        "jarvis.domain.conversation_event_query",
        "jarvis.domain.conversation_event_search",
        "jarvis.domain.conversation_event_store",
        "jarvis.domain.conversation_events",
        "jarvis.domain.conversation_transcript",
        "jarvis.domain.live_lifecycle",
        "jarvis.domain.output_disposition",
        "jarvis.domain.presentation_attention",
        "jarvis.domain.presentation_policy",
        "jarvis.domain.presentation_working_set",
        "jarvis.domain.speech_presentation",
        "jarvis.domain.v2",
        "jarvis.domain.voice_architecture",
        "jarvis.domain.voice_events",
        "jarvis.domain.voice_frontend",
        "jarvis.domain.voice_playback",
        "jarvis.domain.voice_state",
        "jarvis.domain.work_state",
        "jarvis.ports",
        "jarvis.ports.v2",
    }
)


__all__ = [
    "ALLOWED_IMPORT_CLOSURE",
    "MAX_ATTENTION_PER_BATCH",
    "AttentionCounters",
    "PresentationAttentionService",
]
