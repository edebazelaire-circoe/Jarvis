"""Magasin de séance du mode PRESENTATION. Un seul propriétaire, un seul instant.

Handoff `jarvis-presentation-interaction-mode`, Slice 04. Core possède cet état
comme il possède l'état de travail (`jarvis/core/work_state.py`) : **en mémoire
seulement**. Un redémarrage repart d'un magasin vide, et c'est voulu — une
mémoire de séance qui survivrait au processus serait de la mémoire à long
terme, ce que la Décision D13 interdit. Rien ici n'écrit dans la mémoire
canonique, et ce module n'importe aucun port de persistance : c'est la forme
exécutable de « la séance est éphémère ».

## Deux moitiés, un seul instantané

`PresentationWorkingSet` (ce que l'enrichissement a compris) et
`PresentationTranscriptTail` (ce qui vient d'être dit) vivent séparément —
Décision D06 — mais le magasin ne publie jamais l'une sans l'autre : il détient
**une seule** référence, `self._snapshot`, et chaque opération la remplace d'un
bloc. Un lecteur ne peut donc pas voir un fil de la seconde d'après avec un
ensemble de travail de la seconde d'avant. Une opération refusée ne remplace
rien : il n'y a pas d'écriture partielle à observer.

C'est la même discipline que `VoiceConversationState`
(`jarvis/core/voice_state.py`) : atomique entre deux `await`, appelée depuis un
seul propriétaire de boucle, jamais depuis un thread.

## Ce qu'une opération répond

Le vocabulaire de disposition est celui de `VoiceStateDisposition`, **réutilisé
tel quel** plutôt que redécliné : « appliqué / ignoré / doublon / périmé /
séance périmée / refusé / plus de place » est exactement la question posée à
chaque observation, et deux vocabulaires pour une même question finissent par
diverger. Le code, lui, est propre à ce magasin et dit *pourquoi*.

## Cycle de vie — la règle, écrite une fois

- `bind_session(session_id)` ouvre une séance. Une nouvelle séance **retire**
  d'abord la précédente, elle ne s'y ajoute pas.
- `end_session()` retire la séance en cours.
- `apply_interaction_mode(value)` lit le mode avec `behaving_interaction_mode`
  (Slice 01/02 : la lecture *de comportement*, celle où `meeting` ne se
  comporte pas) et **retire tout dès que le mode effectif n'est plus
  PRESENTATION**.
- Retirer, c'est vider les deux moitiés, oublier la séance, oublier les
  identifiants retirés et faire monter `generation`. Rien n'est recopié
  ailleurs. Une observation portant l'identifiant de la séance retirée est
  écartée en `STALE_SESSION` : elle ne peut pas atterrir dans la suivante.

Le retrait est **synchrone avec le changement de mode**, pas un tour de boucle
plus tard : quitter PRESENTATION ne doit pas laisser la mémoire de la séance
vivante le temps d'un aller-retour de bus.

## Journal

Les lignes portent des comptes, des identifiants bornés et des codes stables.
**Jamais de texte de parole, ni de libellé, ni d'énoncé.** La borne de recopie
est celle du Control Center (`MAX_JOURNALLED_VALUE_CHARS = 64`) : un identifiant
hostile ne fait pas grossir le journal. Le chemin normal est journalisé au même
titre que les refus — sinon « rien dans le journal » voudrait dire à la fois
« tout va bien » et « plus rien ne rentre ».
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, ClassVar

from jarvis.core.voice_state import VoiceStateDisposition
from jarvis.domain.interaction_mode import InteractionMode, behaving_interaction_mode
from jarvis.domain.presentation_working_set import (
    MAX_TAIL_AGE_S,
    MAX_TAIL_CHARS,
    MAX_TAIL_ENTRIES,
    MAX_WORKING_SET_AGE_S,
    RECORD_COLLECTIONS,
    AttentionItem,
    AttentionSeverity,
    OpenQuestion,
    PreparedResource,
    PresentationClaim,
    PresentationContextSnapshot,
    PresentationEntity,
    PresentationObservation,
    PresentationSource,
    PresentationTopic,
    PresentationTranscriptTail,
    PresentationWorkingSet,
    ResourceTemperature,
    TranscriptTailEntry,
    UtteranceOrigin,
    derived_temperature,
    evict_to_limit,
    in_eviction_order,
    presentation_id,
    prune_by_age,
)
from jarvis.domain.v2 import utc_now
from jarvis.ports.v2 import DiagnosticSink

#: Observations déjà vues, gardées pour écarter un rejeu. Dimensionné au-dessus
#: de ce qu'un producteur ambiant peut rejouer d'un coup : l'ensemble complet
#: (une centaine d'enregistrements au grand maximum) tient dedans.
MAX_SEEN_OBSERVATIONS = 128
#: Identifiants de ressources sorties de l'ensemble. Une préparation tardive
#: qui nomme une ressource déjà jetée ne la fait pas renaître — même règle que
#: `MAX_EVICTED_KEYS` du magasin de travail, à l'échelle d'une séance.
MAX_RETIRED_RESOURCE_KEYS = 64
#: Recopie maximale d'une valeur dans le journal.
MAX_JOURNALLED_VALUE_CHARS = 64

BOUND_KIND = "presentation.working_set.bound"
RETIRED_KIND = "presentation.working_set.retired"
APPLIED_KIND = "presentation.working_set.applied"
REFUSED_KIND = "presentation.working_set.refused"
EVICTED_KIND = "presentation.working_set.evicted"
TAIL_KIND = "presentation.tail.observed"
TAIL_REFUSED_KIND = "presentation.tail.refused"


@dataclass(frozen=True, slots=True)
class PresentationStateResult:
    """Ce qu'une opération a produit. Forme de `VoiceStateResult`, nom à part.

    `disposition` dit ce qui est arrivé, `code` pourquoi, `revision` où en est
    le magasin, `evicted` combien d'enregistrements sont sortis au passage.
    `authorizes_actions` est faux et ne se règle pas : appliquer une
    observation n'autorise jamais une action (Décision D03).
    """

    disposition: VoiceStateDisposition
    code: str
    revision: int
    evicted: int = 0
    authorizes_actions: ClassVar[bool] = False

    @property
    def applied(self) -> bool:
        return self.disposition is VoiceStateDisposition.APPLIED


def _short(value: object) -> str:
    return str(value)[:MAX_JOURNALLED_VALUE_CHARS]


class PresentationWorkingSetStore:
    """Propriétaire unique de la mémoire de séance. Synchrone, borné, éphémère.

    Aucun producteur n'est câblé ici : la Slice 06 écrira les observations et le
    fil, les Slices 08 et 10 liront l'instantané. Ce magasin n'a ni tâche, ni
    abonnement, ni écriture disque — il répond, et c'est tout.
    """

    def __init__(
        self,
        *,
        diagnostics: DiagnosticSink | None = None,
        tail_max_entries: int = MAX_TAIL_ENTRIES,
        tail_max_chars: int = MAX_TAIL_CHARS,
        tail_max_age_s: float = MAX_TAIL_AGE_S,
        record_max_age_s: float = MAX_WORKING_SET_AGE_S,
    ) -> None:
        for name, value, ceiling in (
            ("tail_max_entries", tail_max_entries, MAX_TAIL_ENTRIES),
            ("tail_max_chars", tail_max_chars, MAX_TAIL_CHARS),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= ceiling:
                raise ValueError(f"invalid {name} retention limit")
        for name, value, ceiling in (
            ("tail_max_age_s", tail_max_age_s, MAX_TAIL_AGE_S),
            ("record_max_age_s", record_max_age_s, MAX_WORKING_SET_AGE_S),
        ):
            if not isinstance(value, (int, float)) or not 0 < float(value) <= ceiling:
                raise ValueError(f"invalid {name} retention limit")
        self._diagnostics = diagnostics
        self._tail_max_entries = tail_max_entries
        self._tail_max_chars = tail_max_chars
        self._tail_max_age_s = float(tail_max_age_s)
        self._record_max_age_s = float(record_max_age_s)
        self._generation = 0
        self._next_sequence = 1
        self._seen: list[str] = []
        self._retired_resources: list[str] = []
        self._snapshot = PresentationContextSnapshot(
            session_id=None, generation=0, revision=0, as_of=utc_now(),
        )

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    @property
    def snapshot(self) -> PresentationContextSnapshot:
        """Les deux moitiés du même instant. Une seule lecture, jamais déchirée."""

        return self._snapshot

    @property
    def revision(self) -> int:
        return self._snapshot.revision

    @property
    def generation(self) -> int:
        """Numéro de séance dans cette vie du processus. Monte à chaque retrait."""

        return self._generation

    @property
    def active(self) -> bool:
        return self._snapshot.session_id is not None

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def bind_session(self, session_id: str) -> PresentationStateResult:
        """Ouvrir une séance. Une séance déjà liée est d'abord retirée."""

        try:
            presentation_id("session_id", session_id)
        except (TypeError, ValueError):
            return self._refuse(VoiceStateDisposition.REJECTED, "presentation_session_invalid")
        if self._snapshot.session_id == session_id:
            return self._result(VoiceStateDisposition.DUPLICATE, "presentation_session_already_bound")
        if self._snapshot.session_id is not None:
            self.retire("session_replaced")
        self._generation += 1
        self._snapshot = PresentationContextSnapshot(
            session_id=session_id, generation=self._generation, revision=self._snapshot.revision + 1,
            as_of=utc_now(),
        )
        self._trace(
            BOUND_KIND, "Mémoire de séance PRESENTATION ouverte",
            data={"session_id": _short(session_id), "generation": self._generation,
                  "revision": self._snapshot.revision},
        )
        return self._result(VoiceStateDisposition.APPLIED, "presentation_session_bound")

    def end_session(self, reason: str = "session_ended") -> PresentationStateResult:
        """Fin de séance : le même retrait que celui d'un changement de mode."""

        return self.retire(reason)

    def retire(self, reason: str) -> PresentationStateResult:
        """Vider la mémoire de séance. Rien n'est recopié, rien ne survit.

        Le compte de ce qui disparaît est journalisé — pas son contenu — parce
        qu'« on a retiré une séance vide » et « on a retiré trente faits » ne
        doivent pas laisser la même ligne.
        """

        if self._snapshot.session_id is None:
            return self._result(VoiceStateDisposition.IGNORED, "presentation_working_set_inactive")
        counts = self._snapshot.counts()
        session_id = self._snapshot.session_id
        self._generation += 1
        self._seen.clear()
        self._retired_resources.clear()
        self._snapshot = PresentationContextSnapshot(
            session_id=None, generation=self._generation, revision=self._snapshot.revision + 1,
            as_of=utc_now(),
        )
        self._trace(
            RETIRED_KIND, f"Mémoire de séance PRESENTATION retirée ({reason})",
            data={"reason": _short(reason), "session_id": _short(session_id),
                  "generation": self._generation, "revision": self._snapshot.revision, **counts},
        )
        return self._result(VoiceStateDisposition.APPLIED, "presentation_working_set_retired")

    def apply_interaction_mode(self, value: object, *, source: str = "core") -> PresentationStateResult:
        """Suivre le mode vivant. Quitter PRESENTATION retire tout, tout de suite.

        `behaving_interaction_mode` est la seule lecture admise ici : c'est
        celle qui *pilote un comportement*. `stored_interaction_mode` garderait
        `meeting` visible, ce qui est bon pour un écran et faux pour un magasin
        — aucun comportement de réunion n'existe, donc REUNION n'est pas
        PRESENTATION et la séance doit se retirer.
        """

        mode = behaving_interaction_mode(value)
        if mode is InteractionMode.PRESENTATION:
            return self._result(VoiceStateDisposition.IGNORED, "presentation_mode_still_active")
        return self.retire(f"interaction_mode_left:{mode.value}:{source}")

    # ------------------------------------------------------------------
    # Le fil récent — indépendant de l'enrichissement
    # ------------------------------------------------------------------

    def observe(
        self,
        session_id: str,
        utterance_id: str,
        text: str,
        *,
        spoken_at: datetime | None = None,
        origin: UtteranceOrigin = UtteranceOrigin.AMBIENT,
        revision: int = 0,
        final: bool = True,
    ) -> PresentationStateResult:
        """Ajouter ou réviser une énonciation. **Aucun enrichissement requis.**

        C'est le chemin court, et il ne croise jamais `apply` : une analyse
        ambiante peut être en retard de dix énonciations, le fil reste à jour
        et l'instantané le dit (`enrichment_lag_entries`).

        Une révision garde le rang (`sequence`) de l'énonciation d'origine :
        une correction tardive ne doit pas se faire passer pour la parole la
        plus fraîche. Une révision plus ancienne que celle détenue est écartée.
        """

        if self._snapshot.session_id is None:
            return self._refuse(
                VoiceStateDisposition.IGNORED, "presentation_working_set_inactive", tail=True,
            )
        if session_id != self._snapshot.session_id:
            return self._refuse(VoiceStateDisposition.STALE_SESSION, "presentation_tail_stale_session", tail=True)
        held = {item.utterance_id: item for item in self._snapshot.tail.entries}
        existing = held.get(utterance_id)
        if existing is not None:
            if revision < existing.revision:
                return self._refuse(VoiceStateDisposition.STALE, "presentation_tail_revision_stale", tail=True)
            if revision == existing.revision:
                return self._refuse(VoiceStateDisposition.DUPLICATE, "presentation_tail_duplicate", tail=True)
        sequence = existing.sequence if existing is not None else self._next_sequence
        try:
            entry = TranscriptTailEntry(
                utterance_id=utterance_id, sequence=sequence, text=text,
                spoken_at=spoken_at or utc_now(), origin=origin, revision=revision, final=final,
            )
        except (TypeError, ValueError):
            # La valeur est refusée sans un mot de son contenu : un texte
            # d'énonciation n'a rien à faire dans un journal, et un tampon
            # d'audio brut encore moins.
            return self._refuse(VoiceStateDisposition.REJECTED, "presentation_tail_entry_invalid", tail=True)
        others = tuple(item for item in self._snapshot.tail.entries if item.utterance_id != utterance_id)
        candidates = tuple(sorted((*others, entry), key=lambda item: item.sequence))
        now = max((item.spoken_at for item in candidates), default=entry.spoken_at)
        kept, dropped = self._bounded_tail(candidates, now=now)
        if entry not in kept:
            # Une parole arrivée après coup, plus vieille que la fenêtre : on ne
            # la range pas pour la jeter dans la foulée, on dit qu'elle est
            # périmée.
            return self._refuse(VoiceStateDisposition.STALE, "presentation_tail_entry_too_old", tail=True)
        code = "presentation_tail_revised" if existing is not None else "presentation_tail_appended"
        if existing is None:
            self._next_sequence = sequence + 1
        tail = PresentationTranscriptTail(entries=kept)
        self._commit(working_set=self._snapshot.working_set, tail=tail)
        self._trace(
            TAIL_KIND, "Parole récente retenue dans le fil de séance",
            data={"code": code, "utterance_id": _short(utterance_id), "sequence": entry.sequence,
                  "revision": entry.revision, "origin": entry.origin.value, "final": entry.final,
                  "chars": len(entry.text), "entries": len(kept), "dropped": len(dropped),
                  "store_revision": self._snapshot.revision},
        )
        return self._result(VoiceStateDisposition.APPLIED, code, evicted=len(dropped))

    def prune(self, now: datetime | None = None) -> PresentationStateResult:
        """Balayage d'âge explicite, pour un magasin qui n'entend plus rien.

        Les bornes d'âge sont mesurées depuis la parole la plus récente quand
        une observation arrive — ce qui rend les tests déterministes sans
        horloge murale. Sans parole, plus rien ne les déclencherait : c'est ce
        que cet appel rattrape, et c'est à l'appelant (Slice 06, sur sa boucle
        de repos) de le faire.
        """

        if self._snapshot.session_id is None:
            return self._result(VoiceStateDisposition.IGNORED, "presentation_working_set_inactive")
        moment = now or utc_now()
        tail, tail_dropped = self._bounded_tail(self._snapshot.tail.entries, now=moment)
        working_set, dropped = self._bounded_working_set(self._snapshot.working_set, now=moment)
        total = len(tail_dropped) + dropped
        if not total:
            return self._result(VoiceStateDisposition.IGNORED, "presentation_nothing_to_prune")
        self._commit(working_set=working_set, tail=PresentationTranscriptTail(entries=tail))
        self._trace(
            EVICTED_KIND, "Balayage d'âge de la mémoire de séance",
            data={"code": "presentation_pruned", "tail_dropped": len(tail_dropped),
                  "records_dropped": dropped, "revision": self._snapshot.revision,
                  **self._snapshot.counts()},
        )
        return self._result(VoiceStateDisposition.APPLIED, "presentation_pruned", evicted=total)

    # ------------------------------------------------------------------
    # L'ensemble de travail — le chemin lent
    # ------------------------------------------------------------------

    def apply(self, observation: object) -> PresentationStateResult:
        """Ranger une chose comprise. Une seule porte, une seule disposition."""

        if not isinstance(observation, PresentationObservation):
            return self._refuse(VoiceStateDisposition.REJECTED, "presentation_observation_invalid")
        if self._snapshot.session_id is None:
            return self._refuse(VoiceStateDisposition.IGNORED, "presentation_working_set_inactive")
        if observation.session_id != self._snapshot.session_id:
            return self._refuse(VoiceStateDisposition.STALE_SESSION, "presentation_observation_stale_session")
        if observation.observation_id in self._seen:
            return self._refuse(VoiceStateDisposition.DUPLICATE, "presentation_observation_duplicate")
        record = observation.record
        collection = observation.collection
        if isinstance(record, PreparedResource) and record.resource_id in self._retired_resources:
            # Une preparation tardive qui nomme une ressource deja jetee ne la
            # ressuscite pas : elle serait rangee avec une fraicheur qu'elle
            # n'a plus, et la voie prioritaire montrerait un ecran perime.
            return self._refuse(VoiceStateDisposition.STALE, "presentation_resource_retired")
        held = getattr(self._snapshot.working_set, collection)
        merged, code = _coalesce(held, record)
        # `merged` porte toujours l'identite conservee : soit celle du nouvel
        # enregistrement, soit celle de l'existant qu'il rejoint. Tout le reste
        # de la collection est repris tel quel.
        candidates = (*(item for item in held if item.record_id != merged.record_id), merged)
        stamp = _observed_at(record)
        now = max(stamp, self._snapshot.working_set.committed_at or stamp)
        working_set, dropped = self._bounded_working_set(
            self._snapshot.working_set, now=now, override=(collection, candidates),
        )
        if merged.record_id not in {item.record_id for item in getattr(working_set, collection)}:
            # Refuser plutot qu'accepter-puis-jeter : un appelant a qui on
            # repond « applique » doit pouvoir relire ce qu'il a range. Et le
            # refus dit lequel des deux budgets a parle.
            if (now - _stamp(merged)).total_seconds() > self._record_max_age_s:
                return self._refuse(VoiceStateDisposition.STALE, "presentation_record_too_old")
            return self._refuse(VoiceStateDisposition.CAPACITY, f"presentation_{collection}_full")
        sequence = max(working_set.observed_sequence, _observed_sequence(record))
        working_set = replace(working_set, observed_sequence=sequence, committed_at=now)
        self._commit(working_set=working_set, tail=self._snapshot.tail)
        self._remember(observation.observation_id)
        self._trace(
            APPLIED_KIND, "Observation de seance rangee dans l'ensemble de travail",
            data={"code": code, "collection": collection, "record_id": _short(merged.record_id),
                  "observation_id": _short(observation.observation_id), "dropped": dropped,
                  "observed_sequence": sequence, "revision": self._snapshot.revision,
                  **self._snapshot.counts()},
        )
        return self._result(VoiceStateDisposition.APPLIED, code, evicted=dropped)

    def use_resource(self, resource_id: str, *, at: datetime | None = None) -> PresentationStateResult:
        """Une ressource vient de servir : elle redevient `hot` et rajeunit."""

        if self._snapshot.session_id is None:
            return self._refuse(VoiceStateDisposition.IGNORED, "presentation_working_set_inactive")
        if resource_id in self._retired_resources:
            return self._refuse(VoiceStateDisposition.STALE, "presentation_resource_retired")
        held = self._snapshot.working_set.resources
        target = next((item for item in held if item.resource_id == resource_id), None)
        if target is None:
            return self._refuse(VoiceStateDisposition.IGNORED, "presentation_resource_unknown")
        moment = at or utc_now()
        if moment < target.last_used_at:
            return self._refuse(VoiceStateDisposition.STALE, "presentation_resource_use_stale")
        refreshed = replace(target, temperature=ResourceTemperature.HOT, last_used_at=moment)
        others = tuple(item for item in held if item.resource_id != resource_id)
        working_set, dropped = self._bounded_working_set(
            self._snapshot.working_set, now=moment, override=("resources", (*others, refreshed)),
        )
        self._commit(working_set=working_set, tail=self._snapshot.tail)
        self._trace(
            APPLIED_KIND, "Ressource préparée réchauffée par son usage",
            data={"code": "presentation_resource_used", "collection": "resources",
                  "record_id": _short(resource_id), "dropped": dropped,
                  "revision": self._snapshot.revision, **self._snapshot.counts()},
        )
        return self._result(VoiceStateDisposition.APPLIED, "presentation_resource_used", evicted=dropped)

    # ------------------------------------------------------------------
    # Mécanique interne
    # ------------------------------------------------------------------

    def _commit(
        self, *, working_set: PresentationWorkingSet, tail: PresentationTranscriptTail
    ) -> None:
        """Le seul endroit qui remplace l'instantané. Un nom, une affectation.

        Tout ce qui précède travaille sur des copies ; si une validation lève
        ici, l'instantané détenu est encore celui d'avant, entier. C'est ce qui
        rend impossible de lire un état à moitié écrit.
        """

        self._snapshot = PresentationContextSnapshot(
            session_id=self._snapshot.session_id,
            generation=self._generation,
            revision=self._snapshot.revision + 1,
            as_of=utc_now(),
            working_set=working_set,
            tail=tail,
        )

    def _bounded_tail(
        self, entries: tuple[TranscriptTailEntry, ...], *, now: datetime
    ) -> tuple[tuple[TranscriptTailEntry, ...], tuple[TranscriptTailEntry, ...]]:
        """Âge, puis taille, puis compte. Toujours par la tête, toujours pareil."""

        ordered = tuple(sorted(entries, key=lambda item: item.sequence))
        kept, dropped = prune_by_age(
            ordered, now=now, max_age_s=self._tail_max_age_s, stamp=lambda item: item.spoken_at,
        )
        kept = tuple(sorted(kept, key=lambda item: item.sequence))
        dropped = list(dropped)
        while sum(len(item.text) for item in kept) > self._tail_max_chars and kept:
            dropped.append(kept[0])
            kept = kept[1:]
        while len(kept) > self._tail_max_entries:
            dropped.append(kept[0])
            kept = kept[1:]
        return kept, tuple(dropped)

    def _bounded_working_set(
        self,
        working_set: PresentationWorkingSet,
        *,
        now: datetime,
        override: tuple[str, tuple] | None = None,
    ) -> tuple[PresentationWorkingSet, int]:
        """Age, temperatures derivees, cascade des sujets, puis comptes.

        L'ordre compte : la temperature d'une ressource depend des sujets encore
        presents, donc les sujets sont bornes **d'abord**, et la cascade applique
        aux ressources la consequence — `discardable` — avant que leur propre
        borne de compte ne choisisse quoi jeter. Un sujet qui tombe emporte donc
        d'abord la chaleur de ce qu'on avait prepare pour lui ; les faits appris
        sous lui, eux, restent, avec leur provenance.
        """

        # Les candidats traversent la fonction sous forme de tuples nus : un
        # `PresentationWorkingSet` intermediaire porterait une collection
        # au-dela de sa borne, donc invalide, et refuserait de se construire.
        # On ne fabrique l'objet qu'une fois, borne.
        incoming = {name: getattr(working_set, name) for name, _ in RECORD_COLLECTIONS.values()}
        if override is not None:
            incoming[override[0]] = tuple(override[1])
        values: dict[str, tuple] = {}
        dropped = 0
        for cls, (name, cap) in RECORD_COLLECTIONS.items():
            kept, aged = prune_by_age(
                incoming[name], now=now, max_age_s=self._record_max_age_s, stamp=_stamp,
            )
            dropped += len(aged)
            if cls is PreparedResource:
                for item in aged:
                    self._retire_resource(item.resource_id)
                values[name] = kept
                continue
            bounded, evicted = evict_to_limit(kept, cap)
            dropped += len(evicted)
            values[name] = bounded
        topic_ids = frozenset(item.topic_id for item in values["topics"])
        resources = in_eviction_order(
            tuple(
                replace(item, temperature=derived_temperature(item, now=now, topic_ids=topic_ids))
                for item in values["resources"]
            )
        )
        resources, evicted = evict_to_limit(resources, RECORD_COLLECTIONS[PreparedResource][1])
        dropped += len(evicted)
        values["resources"] = resources
        for item in evicted:
            self._retire_resource(item.resource_id)
        return replace(working_set, **values), dropped

    def _retire_resource(self, resource_id: str) -> None:
        if resource_id in self._retired_resources:
            return
        self._retired_resources.append(resource_id)
        while len(self._retired_resources) > MAX_RETIRED_RESOURCE_KEYS:
            self._retired_resources.pop(0)

    def _remember(self, observation_id: str) -> None:
        self._seen.append(observation_id)
        while len(self._seen) > MAX_SEEN_OBSERVATIONS:
            self._seen.pop(0)

    def _result(
        self, disposition: VoiceStateDisposition, code: str, *, evicted: int = 0
    ) -> PresentationStateResult:
        return PresentationStateResult(disposition, code, self._snapshot.revision, evicted)

    def _refuse(
        self, disposition: VoiceStateDisposition, code: str, *, tail: bool = False
    ) -> PresentationStateResult:
        """Refus journalisé, sans contenu. Un refus muet serait indiscernable."""

        self._trace(
            TAIL_REFUSED_KIND if tail else REFUSED_KIND,
            "Observation de séance écartée",
            level="info" if disposition in _EXPECTED else "warning",
            data={"code": code, "disposition": disposition.value,
                  "revision": self._snapshot.revision},
        )
        return self._result(disposition, code)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=data or {})
        except Exception:  # noqa: BLE001 - un journal indisponible n'efface pas la séance
            pass


#: Dispositions attendues dans une séance qui va bien : un doublon est le
#: quotidien d'un producteur qui rejoue, une séance périmée l'est d'un
#: producteur qui n'a pas encore vu le retrait. Elles se journalisent en `info` ;
#: le reste mérite un `warning`.
_EXPECTED = frozenset(
    {
        VoiceStateDisposition.DUPLICATE,
        VoiceStateDisposition.IGNORED,
        VoiceStateDisposition.STALE_SESSION,
    }
)


def _stamp(record: Any) -> datetime:
    """Date qui fait foi pour l'âge d'un enregistrement : sa dernière vie."""

    for name in ("last_seen_at", "last_used_at", "retrieved_at", "asked_at", "raised_at"):
        value = getattr(record, name, None)
        if isinstance(value, datetime):
            return value
    raise TypeError("record carries no age stamp")


def _observed_at(record: Any) -> datetime:
    """Instant d'observation : celui de la provenance quand il y en a une."""

    provenance = getattr(record, "provenance", None)
    return provenance.observed_at if provenance is not None else _stamp(record)


def _observed_sequence(record: Any) -> int:
    """Rang d'enonciation cite par un enregistrement ; 0 s'il n'en cite aucun.

    Une source et un point d'attention n'en citent pas : ils viennent d'une
    recherche, pas d'une parole. Ils ne font donc pas avancer la fraicheur de
    l'ensemble, et c'est correct — l'enrichissement n'a pas rattrape la parole
    parce qu'une source a ete trouvee.
    """

    provenance = getattr(record, "provenance", None)
    return provenance.sequence if provenance is not None else 0


def _coalesce(held: tuple, record: Any) -> tuple[Any, str]:
    """Fusionner avec ce qui est déjà là, ou rendre l'enregistrement tel quel.

    **La provenance et la date de première vue ne sont jamais réécrites.** Une
    coalescence met à jour ce qui bouge — la récence, le compte de mentions,
    l'état de vérification, la référence préparée — et laisse intact ce qui dit
    *d'où ça vient*. C'est ce qui fait qu'une affirmation évincée du fil, puis
    recroisée, cite toujours l'énonciation d'origine.
    """

    existing = next((item for item in held if item.record_id == record.record_id), None)
    if existing is None and isinstance(record, AttentionItem):
        existing = next(
            (item for item in held if item.dedup_key == record.dedup_key), None,
        )
        if existing is not None:
            return (
                replace(
                    existing,
                    severity=max((existing.severity, record.severity), key=_SEVERITY_RANK.get),
                    confidence=max(existing.confidence, record.confidence),
                ),
                "presentation_attention_coalesced",
            )
    if existing is None:
        return record, f"presentation_{_SINGULAR[type(record)]}_added"
    if isinstance(record, PresentationTopic):
        merged = replace(
            existing,
            label=record.label,
            last_seen_at=max(existing.last_seen_at, record.last_seen_at),
            mention_count=existing.mention_count + 1,
        )
    elif isinstance(record, PresentationEntity):
        merged = replace(
            existing, label=record.label, kind=record.kind, topic_id=record.topic_id,
            last_seen_at=max(existing.last_seen_at, record.last_seen_at),
        )
    elif isinstance(record, PresentationClaim):
        merged = replace(
            existing, status=record.status, confidence=record.confidence,
            source_ids=record.source_ids, topic_id=record.topic_id,
            last_seen_at=max(existing.last_seen_at, record.last_seen_at),
        )
    elif isinstance(record, PresentationSource):
        merged = replace(
            existing, reference=record.reference, title=record.title, kind=record.kind,
            retrieved_at=max(existing.retrieved_at, record.retrieved_at),
        )
    elif isinstance(record, PreparedResource):
        merged = replace(
            existing, reference=record.reference, temperature=record.temperature,
            topic_id=record.topic_id, claim_id=record.claim_id,
            last_used_at=max(existing.last_used_at, record.last_used_at),
        )
    elif isinstance(record, OpenQuestion):
        merged = replace(existing, text=record.text, topic_id=record.topic_id)
    else:
        merged = replace(
            existing,
            severity=max((existing.severity, record.severity), key=_SEVERITY_RANK.get),
            confidence=max(existing.confidence, record.confidence),
        )
    return merged, f"presentation_{_SINGULAR[type(record)]}_coalesced"


#: Ordre de gravite, pour qu'une coalescence garde toujours le plus fort des
#: deux signaux : deux indices faibles ne doivent pas effacer un avertissement.
_SEVERITY_RANK = {
    AttentionSeverity.INFO: 0,
    AttentionSeverity.NOTICE: 1,
    AttentionSeverity.WARNING: 2,
}

#: Nom au singulier de chaque nature, pour des codes lisibles
#: (`presentation_entity_added`, pas `presentation_entities_added`).
_SINGULAR = {
    PresentationTopic: "topic",
    PresentationEntity: "entity",
    PresentationClaim: "claim",
    PresentationSource: "source",
    PreparedResource: "resource",
    OpenQuestion: "question",
    AttentionItem: "attention",
}
