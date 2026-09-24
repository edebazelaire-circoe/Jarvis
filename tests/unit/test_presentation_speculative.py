"""Conformance de la préparation spéculative de Presentation (Slice 08).

Les assertions portent sur du **comportement** et sur des **valeurs** — jamais
sur le texte source d'un module. L'unique exception est signalée sur place et
justifiée : prouver l'**absence** d'un appel, ce qu'aucun test comportemental ne
sait faire. C'est la règle posée par la Slice 03 et l'exception posée par la
Slice 05.

Chaque phrase d'en-tête de la forme « X ne peut jamais arriver » est traitée
comme un cas de test, et non comme une promesse (Slice 04). Et chaque garde est
exercée **dans l'état pour lequel elle existe**, pas seulement sur son chemin de
code : un outil d'écriture réellement branché, un bassin réellement saturé, un
résultat qui revient réellement après un retrait (Slices 06 et 07).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.core.presentation_speculative import (
    MAX_FINDINGS_PER_JOB,
    MAX_STAGED_OBJECTS,
    PreparedFinding,
    PresentationSpeculativeService,
    SpeculativeOutcome,
    SpeculativeRequest,
)
from jarvis.core.presentation_working_set import PresentationWorkingSetStore
from jarvis.domain.actions import RiskLevel
from jarvis.domain.ambient_observation import AmbientTrigger, AmbientTriggerKind
from jarvis.domain.presentation_speculative import (
    CAPABILITY_TOOLS,
    EXPLICIT_PRIORITIES,
    GRANTABLE_RISKS,
    MAX_SPECULATIVE_JOB_KEY_CHARS,
    MAX_SPECULATIVE_POOL,
    RESERVED_EXPLICIT_SLOTS,
    SPECULATIVE_PRIORITIES,
    AMBIENT_CAPABILITIES,
    SPECULATIVE_TOOL_RISK,
    STAGING_CAPABILITY,
    SpeculativeAdmission,
    SpeculativeCapability,
    SpeculativeError,
    SpeculativeGrant,
    SpeculativeJobKey,
    SpeculativePriority,
    TRIGGER_PREPARATION,
    job_key_text,
)
from jarvis.domain.presentation_working_set import (
    ResourceKind,
    ResourceTemperature,
    UtteranceOrigin,
)
from jarvis.domain.scene import Visibility
from jarvis.runtime.presentation_staging import (
    DisplaySceneStager,
    SceneStagingError,
    STAGED_KIND,
)
from jarvis.security.policy import FORBIDDEN_TOOL_NAMES

ROOT = Path(__file__).resolve().parents[2]
SESSION = "seance-08"
#: Plafond spéculatif, calculé comme le service le calcule : une seule source.
MAX_SPEC = MAX_SPECULATIVE_POOL - RESERVED_EXPLICIT_SLOTS
NOW = datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc)


# ==========================================================================
# Doublures
# ==========================================================================


class FakeStager:
    """Un monteur de scène qui retient ce qu'on lui demande, dans l'ordre."""

    def __init__(self, *, fail: bool = False, fail_discard: bool = False) -> None:
        self.staged: list[dict[str, str]] = []
        self.revealed: list[str] = []
        self.discarded: list[str] = []
        self.fail = fail
        self.fail_discard = fail_discard
        self._n = 0

    async def stage_hidden(self, *, category: str, title: str, summary: str) -> str:
        if self.fail:
            raise SceneStagingError("stage_boom", "montage impossible")
        self._n += 1
        object_id = f"brain-artifact-{self._n:03d}"
        self.staged.append({"object_id": object_id, "category": category, "title": title})
        return object_id

    async def reveal(self, object_id: str) -> None:
        self.revealed.append(object_id)

    async def discard(self, object_ids) -> None:
        if self.fail_discard:
            raise SceneStagingError("discard_boom", "reprise impossible")
        self.discarded.extend(object_ids)


class ScriptedRunner:
    """Un exécutant qui rend ce qu'on lui a dit de rendre, et note ce qu'il a vu."""

    def __init__(self, findings=(), *, delay_s: float = 0.0, boom: Exception | None = None) -> None:
        self._findings = tuple(findings)
        self._delay_s = delay_s
        self._boom = boom
        self.requests: list[SpeculativeRequest] = []

    async def prepare(self, request: SpeculativeRequest) -> SpeculativeOutcome:
        self.requests.append(request)
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._boom is not None:
            raise self._boom
        return SpeculativeOutcome(findings=self._findings)


class NeverFinishingRunner:
    """Un exécutant qui ne rend jamais : de quoi saturer un bassin pour de vrai."""

    def __init__(self) -> None:
        self.started = 0
        self.cancelled = 0

    async def prepare(self, request: SpeculativeRequest) -> SpeculativeOutcome:
        self.started += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return SpeculativeOutcome()


class WritingRunner:
    """Un exécutant qui **essaie vraiment** d'employer des outils d'écriture.

    Il ne simule pas une tentative : il appelle la boîte à outils avec des noms
    d'outils mutants qui sont **réellement branchés** dessus. Sans la garde, le
    fichier serait écrit. C'est la différence entre exercer le code d'une garde
    et atteindre l'état pour lequel elle existe.
    """

    def __init__(self, attempts: tuple[str, ...]) -> None:
        self.attempts = attempts
        self.refusals: list[str] = []

    async def prepare(self, request: SpeculativeRequest) -> SpeculativeOutcome:
        for name in self.attempts:
            try:
                await request.toolbox.invoke(name, "cible")
            except SpeculativeError as exc:
                self.refusals.append(exc.code)
        return SpeculativeOutcome()


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.lines: list[dict] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.lines.append({"kind": kind, "message": message, "level": level, "data": data or {}})


class FakeDisplayTools:
    """La part de `SceneDisplayTools` que le monteur emploie, et rien de plus."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._n = 0

    async def create_object(self, **kwargs):
        self._n += 1
        self.calls.append(("create_object", dict(kwargs)))
        return {"object_id": f"brain-artifact-{self._n:03d}", "outcome": "applied"}

    async def set_visibility(self, **kwargs):
        self.calls.append(("set_visibility", dict(kwargs)))
        return {"outcome": "applied"}

    async def archive(self, **kwargs):
        self.calls.append(("archive", dict(kwargs)))
        return {"applied": len(kwargs.get("object_ids") or [])}


# ==========================================================================
# Montage
# ==========================================================================


def make_store(session: str = SESSION) -> PresentationWorkingSetStore:
    store = PresentationWorkingSetStore()
    assert store.bind_session(session).applied
    return store


def speak(store, utterance_id: str, text: str = "on parle du rapport Ducroix", *, at=NOW):
    """Poser une énonciation dans le fil : c'est d'elle que vient la provenance."""

    result = store.observe(store.snapshot.session_id, utterance_id, text, spoken_at=at)
    assert result.applied, result.code
    return result


def make_service(store, runner, **kwargs) -> PresentationSpeculativeService:
    service = PresentationSpeculativeService(
        store=store, runner=runner, clock=lambda: NOW, **kwargs
    )
    assert service.bind_session(store.snapshot.session_id) is SpeculativeAdmission.ACCEPTED
    return service


def trigger(kind: AmbientTriggerKind, utterance_id: str, text: str, confidence: float = 0.5):
    return AmbientTrigger(kind=kind, utterance_id=utterance_id, text=text, confidence=confidence)


def stage_explicit(service, store, *, utterance_id="ux", topic="visuel"):
    """Admettre une préparation **explicite** portant la capacité de montage.

    Le montage n'est plus atteignable depuis l'ambiant : `DISPLAY_PREPARATION`
    est hors de `AMBIENT_CAPABILITIES`, donc un jeton ambiant ne peut même pas
    se construire avec elle.
    """

    return service.reserve_explicit(
        topic=topic, capabilities=(STAGING_CAPABILITY,),
        utterance_id=utterance_id, text="montre-moi le bilan",
    )


DOC_FINDING = PreparedFinding(
    kind=ResourceKind.DOCUMENT, locator="doc:rapport-ducroix-2026", title="Rapport Ducroix",
)


# ==========================================================================
# 1. La frontière de capacité est une donnée
# ==========================================================================


def test_aucune_capacite_ambiante_n_accorde_un_outil_de_risque_write():
    """D03 en données : rien de ce que l'ambiant peut porter n'écrit.

    Le risque est celui de `jarvis.domain.actions.RiskLevel`, que
    `V1_ACTION_POLICY` emploie déjà — pas un second vocabulaire.

    La portée est `AMBIENT_CAPABILITIES`, et c'est le point : `scene_create_object`
    est déclaré `WRITE` parce qu'il descend jusqu'à un `INSERT` durable, donc la
    capacité qui l'accorde est **hors** de ce que l'ambiant peut porter. Une
    première version le déclarait `EPHEMERAL` en suivant `BOARD_PRESENT`, dont
    le précédent ne transporte pas : ce tableau-là ne range rien.
    """

    for capability in AMBIENT_CAPABILITIES:
        for tool in CAPABILITY_TOOLS[capability]:
            risk = SPECULATIVE_TOOL_RISK[tool]
            assert risk is not RiskLevel.WRITE, (capability, tool)
            assert risk in GRANTABLE_RISKS, (capability, tool, risk)


def test_la_capacite_de_montage_est_hors_de_portee_de_l_ambiant():
    """B2/B3 : le seul effet durable de la voie n'est pas ambiant-accessible."""

    assert STAGING_CAPABILITY not in AMBIENT_CAPABILITIES
    assert AMBIENT_CAPABILITIES == set(SpeculativeCapability) - {STAGING_CAPABILITY}
    assert SPECULATIVE_TOOL_RISK["scene_create_object"] is RiskLevel.WRITE
    # Aucun déclencheur ambiant ne l'atteint.
    for _, capabilities in TRIGGER_PREPARATION.values():
        assert STAGING_CAPABILITY not in capabilities


def test_un_jeton_ambiant_ne_peut_pas_se_construire_avec_la_capacite_de_montage():
    """Le refus est à la construction, pas chez l'appelant.

    Un jeton ambiant illégal ne peut donc pas exister, et aucun chemin ne peut
    en recevoir un — ce qui est plus fort que « personne n'en fabrique ».
    """

    with pytest.raises(SpeculativeError) as caught:
        SpeculativeGrant((STAGING_CAPABILITY,), origin=UtteranceOrigin.AMBIENT)
    assert caught.value.code == "speculative_grant_not_ambient"
    # La même capacité est légale pour un tour explicite.
    grant = SpeculativeGrant((STAGING_CAPABILITY,), origin=UtteranceOrigin.ADDRESSED)
    assert grant.may_stage is True
    assert SpeculativeGrant(
        (SpeculativeCapability.RESEARCH_SEARCH,), origin=UtteranceOrigin.AMBIENT
    ).may_stage is False


def test_scene_update_object_n_est_accorde_a_personne():
    """B4 : l'outil retenu ne doit pas avoir un sur-ensemble accordé à côté.

    `SceneDisplayTools.update_object` accepte `visibility`, `geometry`, `layer`,
    `order` et un `object_id` quelconque : c'est `scene_set_visibility` et
    davantage, y compris l'autorité de placement de l'utilisateur (D12).
    """

    granted = {tool for tools in CAPABILITY_TOOLS.values() for tool in tools}
    for superset in ("scene_update_object", "scene_update_many", "scene_set_visibility",
                     "scene_archive", "scene_pin", "scene_add_artifact"):
        assert superset not in granted, superset
    assert "scene_update_object" not in SPECULATIVE_TOOL_RISK


def test_chaque_capacite_declaree_a_une_table_et_chaque_outil_un_risque():
    """Une capacité sans table accorderait l'ensemble vide, en silence."""

    assert set(CAPABILITY_TOOLS) == set(SpeculativeCapability)
    for capability, tools in CAPABILITY_TOOLS.items():
        assert tools, capability
        assert tools <= set(SPECULATIVE_TOOL_RISK), capability


def test_aucun_outil_accorde_n_est_dans_la_liste_interdite_du_depot():
    """Recoupement indépendant par la liste d'interdiction déjà présente.

    `FORBIDDEN_TOOL_NAMES` (`jarvis/security/policy.py`) est une liste
    d'interdiction, donc insuffisante seule — c'est pour cela que l'admission
    passe par une liste d'**autorisation**. Elle reste un bon contrôle croisé :
    les deux mécanismes se trompent rarement de la même façon.

    La comparaison est faite en minuscules parce que cette liste-là est écrite
    en minuscules et que « Bash » ne doit pas passer à côté de « bash ».
    """

    forbidden = {name.lower() for name in FORBIDDEN_TOOL_NAMES}
    granted = {tool.lower() for tools in CAPABILITY_TOOLS.values() for tool in tools}
    assert granted & forbidden == set()


def test_aucune_capacite_n_accorde_la_visibilite_de_la_scene():
    """Révéler n'est jamais un geste de la préparation elle-même (D12).

    Une préparation qui pourrait se rendre visible rendrait « normalement
    invisible » dépendant de sa bonne volonté. Le contrôle porte sur toutes les
    capacités, présentes et futures.
    """

    granted = {tool for tools in CAPABILITY_TOOLS.values() for tool in tools}
    assert "scene_set_visibility" not in granted
    assert "scene_archive" not in granted
    assert "scene_pin" not in granted


def test_un_jeton_refuse_tout_ce_qui_n_est_pas_accorde():
    """Liste d'autorisation : un nom inconnu est refusé parce qu'inconnu."""

    grant = SpeculativeGrant((SpeculativeCapability.DOCUMENT_RESOLUTION,))
    assert grant.permits("Read") is True
    for hostile in ("Write", "Edit", "Bash", "bash", "NotebookEdit", "memory_append",
                    "scene_set_visibility", "", "READ", None, 42, b"Read"):
        assert grant.permits(hostile) is False, hostile
        with pytest.raises(SpeculativeError) as caught:
            grant.check(hostile)
        assert caught.value.code == "speculative_tool_not_granted"


def test_un_jeton_ne_peut_pas_se_declarer_autorisant():
    """`authorizes_actions` est un `ClassVar` : aucune instance ne dit l'inverse."""

    grant = SpeculativeGrant((SpeculativeCapability.RESEARCH_SEARCH,))
    assert grant.authorizes_actions is False
    assert SpeculativeGrant.authorizes_actions is False
    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(grant, "authorizes_actions", True)
        assert grant.authorizes_actions is False


def test_un_jeton_vide_ou_malforme_est_refuse():
    for bad, code in (
        ((), "speculative_grant_empty"),
        (("research_search",), "speculative_grant_invalid_capability"),
        ((SpeculativeCapability.RESEARCH_SEARCH, SpeculativeCapability.RESEARCH_SEARCH),
         "speculative_grant_duplicate_capability"),
    ):
        with pytest.raises(SpeculativeError) as caught:
            SpeculativeGrant(bad)
        assert caught.value.code == code


# ==========================================================================
# 2. Un travail ambiant n'atteint aucun outil mutant
# ==========================================================================


@pytest.mark.asyncio
async def test_un_travail_ambiant_ne_peut_atteindre_aucun_etat_durable(tmp_path):
    """B2, dans l'état pour lequel la garde existe.

    Un `new_topic` ambiant demande explicitement un montage. Son jeton ne porte
    que `RESEARCH_SEARCH`. Le monteur est **réellement branché** et créerait
    vraiment l'objet. Sans la garde, la scène recevrait un objet durable et le
    magasin une ressource `scene_object` — ce qui s'est produit, et c'est le
    seul effet de cette voie qui atteigne un état durable.
    """

    store = make_store()
    speak(store, "u1")
    stager = FakeStager()
    finding = PreparedFinding(kind=ResourceKind.NOTE, locator="note:x", stage_hidden=True)
    service = make_service(store, ScriptedRunner((finding,)), stager=stager)

    assert service.submit_trigger(
        trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge du trimestre")
    ) is SpeculativeAdmission.ACCEPTED
    request_grant = None
    await service.drain()

    assert stager.staged == [], "un travail ambiant a monté un objet de scène"
    assert store.snapshot.working_set.resources == ()
    assert service.counters.stage_refused == 1
    assert service.counters.stage_failures == 0


def test_un_jeton_ambiant_n_accorde_aucun_outil_mutant():
    """La frontière durable : `allowed_tools` est ce qu'un `--tools` recevra.

    C'est le seam qui survivra à la Slice de déploiement, donc c'est lui qu'on
    teste, plutôt qu'un répartiteur d'outils en mémoire qu'aucun exécutant de
    production n'emploiera.
    """

    for capability in AMBIENT_CAPABILITIES:
        grant = SpeculativeGrant((capability,), origin=UtteranceOrigin.AMBIENT)
        assert grant.allowed_tools, capability
        for tool in grant.allowed_tools:
            assert SPECULATIVE_TOOL_RISK[tool] is not RiskLevel.WRITE, (capability, tool)
        for mutating in ("Write", "Edit", "bash", "delete_file", "memory_append",
                         "scene_set_visibility", "scene_update_object", "scene_archive"):
            assert grant.permits(mutating) is False, (capability, mutating)


def test_la_nature_d_un_declencheur_ambiant_n_ouvre_jamais_une_capacite_mutante():
    """Toute la table d'aiguillage, pas seulement les natures d'aujourd'hui."""

    for kind in AmbientTriggerKind:
        priority, capabilities = TRIGGER_PREPARATION[kind.value]
        assert priority in SPECULATIVE_PRIORITIES, kind
        grant = SpeculativeGrant(tuple(capabilities), origin=UtteranceOrigin.AMBIENT)
        for tool in grant.allowed_tools:
            assert SPECULATIVE_TOOL_RISK[tool] is not RiskLevel.WRITE, (kind, tool)


def test_toutes_les_natures_de_declencheur_de_la_slice_06_ont_une_preparation():
    """Une nature non aiguillée doit être **refusée**, jamais héritée par défaut.

    Si la Slice 06 ajoute une nature, cette voie doit décider ce qu'elle en
    fait. Le test fixe l'égalité, pas l'inclusion.
    """

    assert set(TRIGGER_PREPARATION) == {kind.value for kind in AmbientTriggerKind}


@pytest.mark.asyncio
async def test_une_nature_hors_table_est_refusee_et_comptee():
    store = make_store()
    speak(store, "u1")
    service = make_service(store, ScriptedRunner())

    class Impostor:
        kind = type("K", (), {"value": "execute"})()
        utterance_id = "u1"
        text = "supprime la ligne 12"
        confidence = 0.9
        authorizes_actions = False

    assert service.submit_trigger(Impostor()) is SpeculativeAdmission.REJECTED
    assert service.counters.refused_rejected == 1
    assert service.in_flight == ()


# ==========================================================================
# 3. Un déclencheur lance un travail borné
# ==========================================================================


@pytest.mark.asyncio
async def test_un_declencheur_ambiant_lance_un_travail_borne_et_rend_sa_place():
    store = make_store()
    speak(store, "u1")
    runner = ScriptedRunner((DOC_FINDING,))
    service = make_service(store, runner)

    assert service.submit_trigger(
        trigger(AmbientTriggerKind.EXTERNAL_REFERENCE, "u1", "voir le rapport Ducroix page 12")
    ) is SpeculativeAdmission.ACCEPTED
    assert len(service.in_flight) == 1
    await service.drain()

    assert service.in_flight == ()  # la place est rendue, toujours
    assert service.counters.admitted == 1
    assert service.counters.completed == 1
    request = runner.requests[0]
    assert request.priority is SpeculativePriority.P3_REFERENCE_RESOLUTION
    assert request.grant.origin is UtteranceOrigin.AMBIENT
    assert request.session_id == SESSION


@pytest.mark.asyncio
async def test_un_travail_qui_depasse_sa_limite_de_temps_est_annule_et_compte():
    store = make_store()
    speak(store, "u1")
    service = make_service(store, ScriptedRunner(delay_s=5.0), job_timeout_s=0.05)
    assert service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge")) \
        is SpeculativeAdmission.ACCEPTED
    await service.drain()
    assert service.counters.timed_out == 1
    assert service.in_flight == ()


@pytest.mark.asyncio
async def test_un_exécutant_qui_leve_ne_ferme_pas_la_voie():
    store = make_store()
    speak(store, "u1")
    speak(store, "u2", "on parle de l'étude Meyer")
    service = make_service(store, ScriptedRunner(boom=RuntimeError("provider down")))
    assert service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge")) \
        is SpeculativeAdmission.ACCEPTED
    await service.drain()
    assert service.counters.failed == 1
    # La voie accepte encore : un échec n'est pas une fermeture.
    assert service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u2", "l'écart")) \
        is SpeculativeAdmission.ACCEPTED
    await service.drain()


@pytest.mark.asyncio
async def test_le_nombre_de_decouvertes_par_travail_est_borne():
    store = make_store()
    speak(store, "u1")
    findings = tuple(
        PreparedFinding(kind=ResourceKind.NOTE, locator=f"note:{i}", title=f"n{i}")
        for i in range(MAX_FINDINGS_PER_JOB + 3)
    )
    service = make_service(store, ScriptedRunner(findings))
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    await service.drain()
    assert service.counters.findings_received == MAX_FINDINGS_PER_JOB + 3
    assert service.counters.findings_dropped_bound == 3
    assert len(store.snapshot.working_set.resources) == MAX_FINDINGS_PER_JOB


# ==========================================================================
# 4. Déduplication et coalescence
# ==========================================================================


@pytest.mark.asyncio
async def test_deux_declencheurs_de_meme_sujet_et_ressource_coalescent():
    store = make_store()
    speak(store, "u1")
    speak(store, "u2")
    runner = NeverFinishingRunner()
    service = make_service(store, runner)

    first = service.submit_trigger(
        trigger(AmbientTriggerKind.EXTERNAL_REFERENCE, "u1", "le rapport Ducroix")
    )
    second = service.submit_trigger(
        trigger(AmbientTriggerKind.EXTERNAL_REFERENCE, "u2", "  Le RAPPORT  Ducroix.  ")
    )
    assert first is SpeculativeAdmission.ACCEPTED
    assert second is SpeculativeAdmission.COALESCED
    assert len(service.in_flight) == 1
    await asyncio.sleep(0)  # laisser la tâche admise démarrer pour de bon
    assert runner.started == 1
    assert service.counters.coalesced == 1
    await service.stop()


@pytest.mark.asyncio
async def test_une_meme_phrase_de_nature_differente_est_un_travail_different():
    """Vérifier une affirmation et retrouver un document ne sont pas le même travail."""

    store = make_store()
    speak(store, "u1")
    runner = NeverFinishingRunner()
    service = make_service(store, runner)
    phrase = "le rapport Ducroix est le plus complet"
    assert service.submit_trigger(trigger(AmbientTriggerKind.CHECKABLE_CLAIM, "u1", phrase)) \
        is SpeculativeAdmission.ACCEPTED
    assert service.submit_trigger(trigger(AmbientTriggerKind.EXTERNAL_REFERENCE, "u1", phrase)) \
        is SpeculativeAdmission.ACCEPTED
    assert len(service.in_flight) == 2
    await service.stop()


@pytest.mark.asyncio
async def test_une_cle_liberee_peut_etre_repreparee():
    """Un travail terminé rend sa clé : re-préparer plus tard doit marcher.

    C'est le pendant du défaut que la Slice 04 a corrigé pour cette Slice : un
    refus ne bannit plus un identifiant, et une clé ne doit pas non plus rester
    prise pour toujours.
    """

    store = make_store()
    speak(store, "u1")
    service = make_service(store, ScriptedRunner())
    assert service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge")) \
        is SpeculativeAdmission.ACCEPTED
    await service.drain()
    assert service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge")) \
        is SpeculativeAdmission.ACCEPTED
    await service.drain()
    assert service.counters.admitted == 2
    assert service.counters.coalesced == 0


def test_la_normalisation_d_une_cle_rapproche_deux_formulations_voisines():
    assert job_key_text("  Le RAPPORT  Ducroix. ") == job_key_text("le rapport ducroix")
    assert job_key_text(None) == ""
    with pytest.raises(SpeculativeError) as caught:
        SpeculativeJobKey("")
    assert caught.value.code == "speculative_key_empty"
    with pytest.raises(SpeculativeError):
        SpeculativeJobKey(" x")


# ==========================================================================
# 5. D08 — réserve et préemption
# ==========================================================================


@pytest.mark.asyncio
async def test_un_bassin_speculatif_sature_laisse_toujours_la_reserve_libre():
    """La phrase d'en-tête, prise comme cas de test.

    Le bassin est saturé **pour de vrai** — autant de travaux spéculatifs que
    le plafond l'autorise, tous réellement en vol — et la réserve explicite
    reste intacte.
    """

    store = make_store()
    runner = NeverFinishingRunner()
    service = make_service(store, runner)
    for index in range(MAX_SPEC):
        speak(store, f"u{index}", f"sujet numero {index}")
        assert service.submit_trigger(
            trigger(AmbientTriggerKind.NEW_TOPIC, f"u{index}", f"sujet numero {index}")
        ) is SpeculativeAdmission.ACCEPTED

    assert service.speculative_in_flight == MAX_SPEC
    refused = service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u0", "un de trop"))
    assert refused is SpeculativeAdmission.CAPACITY
    assert service.counters.refused_capacity == 1
    # La réserve n'a pas été entamée, et elle vaut ce qu'elle promet.
    assert service.free_explicit_slots == RESERVED_EXPLICIT_SLOTS
    assert service.explicit_in_flight == 0
    await service.stop()


@pytest.mark.asyncio
async def test_une_preparation_explicite_passe_sur_un_bassin_speculatif_sature():
    store = make_store()
    runner = NeverFinishingRunner()
    service = make_service(store, runner)
    for index in range(MAX_SPEC):
        speak(store, f"u{index}", f"sujet numero {index}")
        service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, f"u{index}", f"sujet numero {index}"))
    assert service.speculative_in_flight == MAX_SPEC

    speak(store, "ux", "montre-moi le bilan")
    admitted = service.reserve_explicit(
        topic="bilan", capabilities=(SpeculativeCapability.DATA_ANALYSIS,),
        utterance_id="ux", text="montre-moi le bilan",
    )
    assert admitted is SpeculativeAdmission.ACCEPTED
    assert service.explicit_in_flight == 1
    # Aucun spéculatif n'a été sacrifié : la réserve a suffi.
    assert service.counters.preempted == 0
    assert service.speculative_in_flight == MAX_SPEC
    await service.stop()


@pytest.mark.asyncio
async def test_un_bassin_entierement_plein_sacrifie_du_speculatif_pour_l_explicite():
    """D08 active : la réserve épuisée, le spéculatif est préempté.

    On remplit le bassin **entier** — plafond spéculatif plus toute la réserve
    — puis on demande une place explicite de plus.
    """

    store = make_store()
    runner = NeverFinishingRunner()
    service = make_service(store, runner)
    for index in range(MAX_SPEC):
        speak(store, f"u{index}", f"sujet numero {index}")
        service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, f"u{index}", f"sujet numero {index}"))
    for index in range(RESERVED_EXPLICIT_SLOTS):
        speak(store, f"e{index}", f"demande explicite {index}")
        assert service.reserve_explicit(
            topic=f"explicite{index}", capabilities=(SpeculativeCapability.DATA_ANALYSIS,),
            utterance_id=f"e{index}", text=f"demande explicite {index}",
        ) is SpeculativeAdmission.ACCEPTED
    assert len(service.in_flight) == MAX_SPECULATIVE_POOL
    assert service.free_explicit_slots == 0

    speak(store, "e9", "et le detail des marges")
    assert service.reserve_explicit(
        topic="marges", capabilities=(SpeculativeCapability.DATA_ANALYSIS,),
        utterance_id="e9", text="et le detail des marges",
    ) is SpeculativeAdmission.ACCEPTED
    assert service.counters.preempted == 1
    assert service.explicit_in_flight == RESERVED_EXPLICIT_SLOTS + 1
    assert service.speculative_in_flight == MAX_SPEC - 1
    await service.stop()


@pytest.mark.asyncio
async def test_un_tour_adresse_p0_n_est_jamais_admis_mais_fait_de_la_place():
    """P0 vit dans le cerveau. Cette voie ne lui doit qu'une place libre."""

    store = make_store()
    runner = NeverFinishingRunner()
    service = make_service(store, runner)
    # Le bassin doit être **plein** : tant qu'il reste une place, D08 est déjà
    # satisfaite et jeter du travail utile ne sert personne. Une première
    # version sacrifiait un travail alors que sept places étaient libres.
    for index in range(MAX_SPEC):
        speak(store, f"u{index}", f"sujet numero {index}")
        service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, f"u{index}", f"sujet numero {index}"))
    for index in range(RESERVED_EXPLICIT_SLOTS):
        speak(store, f"e{index}", f"demande explicite {index}")
        service.reserve_explicit(
            topic=f"explicite{index}", capabilities=(SpeculativeCapability.DATA_ANALYSIS,),
            utterance_id=f"e{index}", text=f"demande explicite {index}",
        )
    await asyncio.sleep(0)
    assert runner.started == MAX_SPECULATIVE_POOL  # tout tourne pour de bon
    assert service.free_explicit_slots == 0

    freed = service.note_addressed_turn()
    assert len(freed) == 1
    assert service.speculative_in_flight == MAX_SPEC - 1
    assert service.counters.preempted == 1
    # Laisser la seule tâche annulée traiter son `CancelledError`. Un `drain()`
    # ici attendrait aussi les sept autres, qui ne finissent jamais.
    for _ in range(3):
        await asyncio.sleep(0)
    assert runner.cancelled == 1
    await service.stop()


@pytest.mark.asyncio
async def test_un_tour_adresse_ne_sacrifie_rien_quand_le_bassin_a_de_la_place():
    """D08 demande que l'explicite passe, pas qu'on jette du travail utile."""

    store = make_store()
    runner = NeverFinishingRunner()
    service = make_service(store, runner)
    speak(store, "u1", "la marge")
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    await asyncio.sleep(0)
    assert service.free_explicit_slots > 0

    assert service.note_addressed_turn() == ()
    assert service.speculative_in_flight == 1
    assert service.counters.preempted == 0
    await service.stop()


@pytest.mark.asyncio
async def test_le_sacrifice_prend_le_rang_le_plus_bas_puis_le_plus_recent():
    """On jette P4 avant P2, et le plus récent avant le plus ancien à rang égal.

    L'ordre attendu est **calculé** depuis les rangs réellement admis, pas
    écrit à la main : une première version de ce test nommait trois
    identifiants et se trompait dès qu'un travail de remplissage était plus
    récent que le plus ancien. Le test disait alors que le code avait tort
    alors qu'il appliquait exactement la règle documentée.

    Le bassin est tenu plein tout du long : chaque place libérée est reprise
    par un rang explicite, sinon la préemption suivante n'aurait pas lieu
    d'être.
    """

    store = make_store()
    runner = NeverFinishingRunner()
    service = make_service(store, runner)
    plan = [
        (AmbientTriggerKind.CHECKABLE_CLAIM, "affirmation verifiable"),      # P2
        (AmbientTriggerKind.NEW_TOPIC, "premier sujet"),                     # P4
        (AmbientTriggerKind.NEW_TOPIC, "second sujet"),                      # P4
        (AmbientTriggerKind.CHECKABLE_CLAIM, "autre affirmation nette"),     # P2
        (AmbientTriggerKind.EXTERNAL_REFERENCE, "le rapport Ducroix"),       # P3
        (AmbientTriggerKind.NEW_TOPIC, "troisieme sujet"),                   # P4
    ]
    assert len(plan) == MAX_SPEC
    for index, (kind, text) in enumerate(plan):
        speak(store, f"u{index}", text)
        assert service.submit_trigger(trigger(kind, f"u{index}", text)) is SpeculativeAdmission.ACCEPTED
    for index in range(RESERVED_EXPLICIT_SLOTS):
        speak(store, f"e{index}", f"demande explicite {index}")
        service.reserve_explicit(
            topic=f"explicite{index}", capabilities=(SpeculativeCapability.DATA_ANALYSIS,),
            utterance_id=f"e{index}", text=f"demande explicite {index}",
        )
    assert service.free_explicit_slots == 0

    # L'ordre que la règle impose : rang le plus bas d'abord, puis le plus récent.
    expected = [
        job.job_id
        for job in sorted(
            (j for j in service._jobs.values() if j.speculative),
            key=lambda item: (-int(item.priority), -item.admitted_seq),
        )
    ]
    assert len(expected) == MAX_SPEC
    priorities = [int(service._jobs[job_id].priority) for job_id in expected]
    assert priorities == sorted(priorities, reverse=True), priorities

    observed = []
    for round_index, wanted in enumerate(expected):
        freed = service.note_addressed_turn()
        assert freed == (wanted,), (round_index, freed, wanted)
        observed.append(freed[0])
        # Reprendre la place pour que le bassin reste plein.
        speak(store, f"x{round_index}", f"reprise numero {round_index}")
        service.reserve_explicit(
            topic=f"reprise{round_index}", capabilities=(SpeculativeCapability.DATA_ANALYSIS,),
            utterance_id=f"x{round_index}", text=f"reprise numero {round_index}",
        )
    assert observed == expected
    assert service.speculative_in_flight == 0
    assert service.explicit_in_flight == MAX_SPECULATIVE_POOL
    await service.stop()


def test_les_rangs_explicites_et_speculatifs_partitionnent_l_enumeration():
    assert EXPLICIT_PRIORITIES | SPECULATIVE_PRIORITIES == set(SpeculativePriority)
    assert EXPLICIT_PRIORITIES & SPECULATIVE_PRIORITIES == set()
    assert SpeculativePriority.P0_ADDRESSED_TURN in EXPLICIT_PRIORITIES
    assert MAX_SPEC == MAX_SPECULATIVE_POOL - RESERVED_EXPLICIT_SLOTS
    assert MAX_SPEC >= 1


def test_une_reserve_egale_au_bassin_ne_se_construit_pas():
    """Une voie qui ne peut rien préparer n'est pas une voie."""

    with pytest.raises(ValueError):
        PresentationSpeculativeService(store=make_store(), runner=ScriptedRunner(), pool=4, reserved=4)
    with pytest.raises(ValueError):
        PresentationSpeculativeService(store=make_store(), runner=ScriptedRunner(), pool=0)


@pytest.mark.asyncio
async def test_un_bassin_speculatif_sature_ne_consomme_aucune_place_du_back_brain():
    """La preuve structurelle : les deux voies ne partagent aucun compteur.

    `BackBrainTaskService` garde sa capacité et son admission adressée. Cette
    voie ne l'importe pas, ne l'appelle pas, et ne peut donc pas la remplir —
    c'est ce qui fait qu'un bassin spéculatif saturé ne bloque jamais une
    requête adressée, indépendamment de toute réserve.
    """

    store = make_store()
    service = make_service(store, NeverFinishingRunner())
    for index in range(MAX_SPEC):
        speak(store, f"u{index}", f"sujet numero {index}")
        service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, f"u{index}", f"sujet numero {index}"))
    assert service.speculative_in_flight == MAX_SPEC

    closure = _closure("jarvis.core.presentation_speculative")
    assert "jarvis.core.back_brain" not in closure
    assert "jarvis.core.owned_job_execution" not in closure
    await service.stop()


# ==========================================================================
# 6. Normalisation dans l'ensemble de travail, avec provenance
# ==========================================================================


@pytest.mark.asyncio
async def test_un_resultat_devient_une_ressource_preparee_avec_sa_provenance():
    store = make_store()
    speak(store, "u1", "on cite le rapport Ducroix", at=NOW)
    service = make_service(store, ScriptedRunner((DOC_FINDING,)))
    service.submit_trigger(trigger(AmbientTriggerKind.EXTERNAL_REFERENCE, "u1", "le rapport Ducroix"))
    await service.drain()

    resources = store.snapshot.working_set.resources
    assert len(resources) == 1
    resource = resources[0]
    assert resource.reference.kind is ResourceKind.DOCUMENT
    assert resource.reference.locator == "doc:rapport-ducroix-2026"
    assert resource.temperature is ResourceTemperature.WARM
    # La provenance est **lue** dans le fil, jamais fabriquée.
    assert resource.provenance.utterance_id == "u1"
    assert resource.provenance.sequence == store.snapshot.tail.entries[0].sequence
    assert resource.provenance.observed_at == NOW
    assert resource.provenance.origin is UtteranceOrigin.AMBIENT
    assert service.counters.store_dispositions == {"applied": 1}


@pytest.mark.asyncio
async def test_une_provenance_introuvable_ne_range_rien():
    """Phrase d'en-tête : « une provenance inventée serait pire qu'une perte ».

    L'énonciation a quitté le fil avant le retour du travail. Rien n'est rangé,
    et le refus est compté.
    """

    store = make_store()
    speak(store, "u1")
    service = make_service(store, ScriptedRunner((DOC_FINDING,)))
    service.submit_trigger(trigger(AmbientTriggerKind.EXTERNAL_REFERENCE, "u1", "le rapport"))
    # Le fil est rebâti sans `u1` pendant que le travail est en vol.
    store.retire("test")
    store.bind_session(SESSION)
    speak(store, "u9", "autre chose")
    await service.drain()

    assert store.snapshot.working_set.resources == ()
    assert service.counters.store_dispositions.get("applied", 0) == 0


@pytest.mark.asyncio
async def test_une_reference_illegale_est_refusee_par_le_contrat_de_la_slice_04():
    """On ne refait pas le validateur de la Slice 04, on s'appuie dessus.

    Schéma hors liste blanche et balise dans un locator : deux refus typés,
    comptés, sans exception qui sorte.
    """

    store = make_store()
    speak(store, "u1")
    hostile = (
        PreparedFinding(kind=ResourceKind.WEB_PAGE, locator="javascript:alert(1)"),
        PreparedFinding(kind=ResourceKind.WEB_PAGE, locator="vbscript:x"),
        PreparedFinding(kind=ResourceKind.DOCUMENT, locator="doc:<script>"),
    )
    service = make_service(store, ScriptedRunner(hostile))
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    await service.drain()

    assert store.snapshot.working_set.resources == ()
    assert service.counters.findings_invalid == len(hostile)
    assert service.counters.completed == 1  # le travail a fini, ses découvertes non


@pytest.mark.asyncio
async def test_un_descripteur_structure_sûr_est_accepte_et_reste_des_donnees():
    store = make_store()
    speak(store, "u1")
    finding = PreparedFinding(
        kind=ResourceKind.CHART_DESCRIPTOR, locator="chart:marges-2026", title="Marges",
        descriptor={"serie": ["T1", "T2"], "valeur": [11.5, 9.2], "seuil": "marge > 10"},
    )
    service = make_service(store, ScriptedRunner((finding,)))
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "les marges"))
    await service.drain()

    resource = store.snapshot.working_set.resources[0]
    assert resource.reference.descriptor["valeur"] == [11.5, 9.2]
    assert resource.reference.descriptor["seuil"] == "marge > 10"


@pytest.mark.asyncio
async def test_toutes_les_dispositions_du_magasin_sont_comptees_sous_leur_nom():
    """Aucune disposition n'est bucketée en silence (leçon de la Slice 06)."""

    store = make_store()
    speak(store, "u1")
    service = make_service(store, ScriptedRunner((DOC_FINDING,)))
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    await service.drain()
    assert service.counters.store_dispositions == {"applied": 1}

    class BrokenStore:
        @property
        def snapshot(self):
            return store.snapshot

        def apply(self, observation):
            return object()

    service._store = BrokenStore()
    speak(store, "u2", "autre")
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u2", "autre sujet"))
    await service.drain()
    assert service.counters.store_dispositions.get("unknown") == 1


# ==========================================================================
# 7. Montage masqué, et révélation
# ==========================================================================


@pytest.mark.asyncio
async def test_un_visuel_prepare_est_monte_masque_et_le_reste_jusqu_a_sa_revelation():
    store = make_store()
    speak(store, "u1")
    stager = FakeStager()
    finding = PreparedFinding(
        kind=ResourceKind.CHART_DESCRIPTOR, locator="chart:marges", title="Marges",
        stage_hidden=True,
    )
    service = make_service(store, ScriptedRunner((finding,)), stager=stager)
    assert stage_explicit(service, store, utterance_id="u1") is SpeculativeAdmission.ACCEPTED
    await service.drain()

    assert len(stager.staged) == 1
    assert stager.revealed == []  # rien n'est montré tant que rien ne le demande
    resource = store.snapshot.working_set.resources[0]
    assert resource.reference.kind is ResourceKind.SCENE_OBJECT
    assert resource.reference.locator == stager.staged[0]["object_id"]

    assert await service.reveal(resource.resource_id) is SpeculativeAdmission.ACCEPTED
    assert stager.revealed == [stager.staged[0]["object_id"]]
    assert service.counters.resources_revealed == 1
    # La révélation réchauffe la ressource dans l'ensemble de travail.
    assert store.snapshot.working_set.resources[0].temperature is ResourceTemperature.HOT


@pytest.mark.asyncio
async def test_un_montage_en_echec_ne_range_rien_et_ne_montre_rien():
    """Phrase d'en-tête : « aucun repli sur un objet visible »."""

    store = make_store()
    speak(store, "u1")
    stager = FakeStager(fail=True)
    finding = PreparedFinding(kind=ResourceKind.NOTE, locator="note:x", stage_hidden=True)
    service = make_service(store, ScriptedRunner((finding,)), stager=stager)
    assert stage_explicit(service, store, utterance_id="u1") is SpeculativeAdmission.ACCEPTED
    await service.drain()

    assert stager.staged == []
    assert stager.revealed == []
    assert store.snapshot.working_set.resources == ()
    assert service.counters.stage_failures == 1


@pytest.mark.asyncio
async def test_reveler_une_ressource_non_montee_ou_inconnue_est_refuse():
    store = make_store()
    speak(store, "u1")
    stager = FakeStager()
    service = make_service(store, ScriptedRunner((DOC_FINDING,)), stager=stager)
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    await service.drain()

    resource = store.snapshot.working_set.resources[0]
    assert resource.reference.kind is ResourceKind.DOCUMENT
    assert await service.reveal(resource.resource_id) is SpeculativeAdmission.REJECTED
    assert await service.reveal("inconnue") is SpeculativeAdmission.REJECTED
    assert stager.revealed == []


@pytest.mark.asyncio
async def test_le_monteur_cree_l_objet_masque_en_une_seule_commande():
    """Phrase d'en-tête : créer puis masquer laisserait un clignotement.

    Le contrôle porte sur les appels réellement passés à l'outil d'affichage :
    exactement une création, portant `hidden`, et **aucun** changement de
    visibilité avant la révélation.
    """

    tools = FakeDisplayTools()
    stager = DisplaySceneStager(tools)
    object_id = await stager.stage_hidden(category="preparation", title="Marges", summary="chart:marges")

    assert [name for name, _ in tools.calls] == ["create_object"]
    created = tools.calls[0][1]
    assert created["visibility"] == Visibility.HIDDEN.value
    assert created["kind"] == STAGED_KIND
    assert object_id == "brain-artifact-001"

    await stager.reveal(object_id)
    assert [name for name, _ in tools.calls] == ["create_object", "set_visibility"]
    assert tools.calls[1][1] == {"object_id": object_id, "visibility": Visibility.VISIBLE.value}


@pytest.mark.asyncio
async def test_un_monteur_qui_ne_rend_pas_d_identifiant_est_une_erreur():
    class Mute(FakeDisplayTools):
        async def create_object(self, **kwargs):
            self.calls.append(("create_object", dict(kwargs)))
            return {"outcome": "applied"}

    stager = DisplaySceneStager(Mute())
    with pytest.raises(SceneStagingError) as caught:
        await stager.stage_hidden(category="c", title="t", summary="s")
    assert caught.value.code == "presentation_stage_no_object_id"


@pytest.mark.asyncio
async def test_le_monteur_ne_construit_aucune_commande_de_scene_lui_meme():
    """Absence d'appel : la seule exception admise à la règle « pas de texte source ».

    Aucun test comportemental ne peut prouver qu'un module **n'appelle pas**
    `apply_scene_command` ni ne construit de `SceneCommand` : il faudrait
    énumérer tous les chemins. La Slice 05 a posé l'exception et sa
    justification ; elle s'applique mot pour mot ici, et c'est pourquoi ce test
    lit la source. **Ne pas le supprimer au motif de la règle générale.**

    Ce qu'il protège : D12. Le jour où ce module fabrique une `SceneCommand`,
    il contourne `SceneDisplayTools` et perd d'un coup les refus d'épingle, de
    géométrie explicite et de vérité d'exécution que le réducteur applique.
    """

    import ast

    path = ROOT / "jarvis" / "runtime" / "presentation_staging.py"
    # `utf-8-sig` : la Slice 01 a trouvé un BOM qui fait échouer `ast.parse`.
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    # Les **noms réellement employés**, pas le texte du fichier : une recherche
    # de sous-chaîne trouverait aussi les mots de cette docstring, et c'est
    # exactement le piège que la Slice 03 a payé trois fois.
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    used |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            used |= {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            used |= {alias.name for alias in node.names}
    for forbidden in ("SceneCommand", "apply_scene_command", "SceneActor", "SceneOp",
                      "SceneObjectFields", "scene_wire", "SceneSnapshot"):
        assert forbidden not in used, forbidden


# ==========================================================================
# 8. Annulation et éviction sur changement de séance et de mode
# ==========================================================================


@pytest.mark.asyncio
async def test_un_changement_de_seance_annule_tout_ce_qui_est_en_vol():
    store = make_store()
    runner = NeverFinishingRunner()
    service = make_service(store, runner)
    for index in range(3):
        speak(store, f"u{index}", f"sujet numero {index}")
        service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, f"u{index}", f"sujet numero {index}"))
    assert len(service.in_flight) == 3
    await asyncio.sleep(0)
    assert runner.started == 3  # les trois tournent vraiment avant le retrait

    assert service.bind_session("seance-suivante") is SpeculativeAdmission.ACCEPTED
    assert service.in_flight == ()
    assert service.counters.cancelled_session == 3
    await service.drain()
    assert runner.cancelled == 3


@pytest.mark.asyncio
async def test_quitter_presentation_retire_la_voie_et_annule_tout():
    store = make_store()
    runner = NeverFinishingRunner()
    service = make_service(store, runner)
    speak(store, "u1", "la marge")
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))

    assert service.apply_interaction_mode("presentation") is SpeculativeAdmission.INACTIVE
    assert len(service.in_flight) == 1
    assert service.apply_interaction_mode("assistant") is SpeculativeAdmission.ACCEPTED
    assert service.in_flight == ()
    assert service.active is False
    assert service.counters.cancelled_mode == 1
    await service.drain()


@pytest.mark.asyncio
async def test_un_mode_illisible_retire_aussi():
    """Une voie qui ne peut pas savoir qu'elle est en Presentation s'arrête."""

    store = make_store()
    service = make_service(store, NeverFinishingRunner())
    speak(store, "u1", "la marge")
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    assert service.apply_interaction_mode("fromage") is SpeculativeAdmission.ACCEPTED
    assert service.active is False
    await service.drain()


@pytest.mark.asyncio
async def test_une_voie_retiree_n_admet_plus_rien():
    store = make_store()
    service = make_service(store, ScriptedRunner())
    service.retire("test")
    speak(store, "u1")
    assert service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge")) \
        is SpeculativeAdmission.INACTIVE
    assert service.counters.refused_inactive == 1


# ==========================================================================
# 9. Rejet du périmé
# ==========================================================================


@pytest.mark.asyncio
async def test_un_resultat_revenu_apres_un_retrait_n_atteint_jamais_le_magasin():
    """Phrase d'en-tête : « le compteur de génération monte avant les annulations ».

    Le travail est libéré du bassin **sans** être annulé — c'est le cas
    difficile, celui où le résultat revient réellement — puis il revient après
    le retrait de la séance.
    """

    store = make_store()
    speak(store, "u1")
    gate = asyncio.Event()

    class Slow:
        async def prepare(self, request):
            await gate.wait()
            return SpeculativeOutcome((DOC_FINDING,))

    service = make_service(store, Slow())
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    job = service._jobs[service.in_flight[0]]
    task = job.task
    service._release(job)  # la place est rendue, la tâche continue

    service.retire("mode_change")
    gate.set()
    await asyncio.gather(task, return_exceptions=True)

    assert service.counters.results_stale_generation == 1
    assert store.snapshot.working_set.resources == ()


@pytest.mark.asyncio
async def test_une_admission_qui_nomme_une_autre_seance_est_periMee():
    store = make_store()
    speak(store, "u1")
    service = make_service(store, ScriptedRunner())
    assert service.submit_trigger(
        trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"), session_id="autre-seance"
    ) is SpeculativeAdmission.STALE_SESSION
    assert service.counters.refused_stale_session == 1
    assert service.in_flight == ()


@pytest.mark.asyncio
async def test_une_ressource_deja_retiree_n_est_pas_ressuscitee():
    """Le magasin répond `stale` et la voie le compte sous ce nom."""

    store = make_store()
    speak(store, "u1")
    service = make_service(store, ScriptedRunner((DOC_FINDING,)))
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    await service.drain()
    resource_id = store.snapshot.working_set.resources[0].resource_id
    assert service.counters.store_dispositions["applied"] == 1

    # Rejouer exactement la même observation : le magasin répond `duplicate`.
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    await service.drain()
    assert set(service.counters.store_dispositions) <= {"applied", "duplicate"}
    assert resource_id in {r.resource_id for r in store.snapshot.working_set.resources}


# ==========================================================================
# 10. Observabilité et journal
# ==========================================================================


@pytest.mark.asyncio
async def test_le_journal_ne_porte_jamais_de_parole():
    """Même règle que la voie ambiante et le magasin : des codes, pas des phrases."""

    phrase = "le chiffre d'affaires du troisieme trimestre est de quarante-deux millions"
    store = make_store()
    speak(store, "u1", phrase)
    diagnostics = RecordingDiagnostics()
    service = make_service(store, ScriptedRunner((DOC_FINDING,)), diagnostics=diagnostics)
    service.submit_trigger(trigger(AmbientTriggerKind.CHECKABLE_CLAIM, "u1", phrase))
    await service.drain()
    service.retire("fin")

    assert diagnostics.lines, "le chemin normal doit être journalisé"
    blob = json.dumps(diagnostics.lines, ensure_ascii=False)
    for fragment in ("quarante-deux", "chiffre d'affaires", "troisieme trimestre"):
        assert fragment not in blob, fragment
    # La clé journalisée est une empreinte, jamais la phrase dont elle vient.
    admitted = next(l for l in diagnostics.lines if l["kind"].endswith(".admitted"))
    assert len(admitted["data"]["key"]) == 12
    assert admitted["data"]["key"].isalnum()
    kinds = {line["kind"] for line in diagnostics.lines}
    assert "presentation.speculative.admitted" in kinds
    assert "presentation.speculative.prepared" in kinds
    assert "presentation.speculative.retired" in kinds


@pytest.mark.asyncio
async def test_stats_expose_tout_ce_qui_pourrait_deriver():
    store = make_store()
    service = make_service(store, ScriptedRunner())
    stats = service.stats()
    for key in ("pool", "reserved", "max_speculative", "in_flight", "speculative_in_flight",
                "explicit_in_flight", "free_explicit_slots", "admitted", "coalesced",
                "refused_capacity", "preempted", "store_dispositions", "tracked_keys",
                "results_stale_generation", "stage_failures", "stage_refused", "generation",
                "staged_objects", "staged_budget", "staged_objects_discarded",
                "discard_failures", "diagnostic_failures"):
        assert key in stats, key


@pytest.mark.asyncio
async def test_un_journal_en_panne_n_arrete_pas_la_voie():
    class Broken:
        def emit(self, *args, **kwargs):
            raise RuntimeError("journal down")

    store = make_store()
    speak(store, "u1")
    service = make_service(store, ScriptedRunner((DOC_FINDING,)), diagnostics=Broken())
    assert service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge")) \
        is SpeculativeAdmission.ACCEPTED
    await service.drain()
    assert len(store.snapshot.working_set.resources) == 1


def test_la_confiance_d_un_declencheur_n_est_jamais_un_seuil_d_admission():
    """Caveat §11 de la Slice 06 : un rang, pas une probabilité.

    Un déclencheur de confiance nulle est admis exactement comme un autre.
    """

    async def run():
        store = make_store()
        speak(store, "u1")
        service = make_service(store, ScriptedRunner())
        assert service.submit_trigger(
            trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge", confidence=0.0)
        ) is SpeculativeAdmission.ACCEPTED
        await service.drain()

    asyncio.run(run())


# ==========================================================================
# 11. Fermeture d'import
# ==========================================================================


def _closure(module: str) -> set[str]:
    """Modules `jarvis` chargés par l'import de `module`, dans un interpréteur neuf.

    Même technique que la Slice 06 : un sous-processus, et l'ensemble exact
    plutôt qu'une liste d'interdiction. Une liste d'interdiction ne voit que ce
    à quoi on a pensé ; une fermeture voit tout ce qui est arrivé.
    """

    code = (
        "import sys, json; before=set(sys.modules); "
        f"import {module}; "
        "print(json.dumps(sorted(m for m in set(sys.modules)-before "
        "if m.split('.')[0]=='jarvis')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return set(json.loads(out.stdout))


SPECULATIVE_DOMAIN_CLOSURE = {
    "jarvis",
    "jarvis.domain",
    "jarvis.domain._checks",
    "jarvis.domain.actions",
    "jarvis.domain.presentation_speculative",
    "jarvis.domain.presentation_working_set",
    "jarvis.security",
    "jarvis.security.policy",
}


def test_le_domaine_speculatif_ne_charge_que_des_modules_declares():
    """La table des capacités ne doit rien traîner : ni scène, ni agent, ni Core.

    Égalité, pas inclusion. Un import ajouté se voit, et le message dit lequel.
    """

    loaded = _closure("jarvis.domain.presentation_speculative")
    assert loaded == SPECULATIVE_DOMAIN_CLOSURE, {
        "unexpected": sorted(loaded - SPECULATIVE_DOMAIN_CLOSURE),
        "declared_but_absent": sorted(SPECULATIVE_DOMAIN_CLOSURE - loaded),
    }


def test_le_service_speculatif_n_atteint_ni_le_back_brain_ni_le_registre_d_outils():
    """La voie n'a aucune arête vers l'admission adressée ni vers un outil réel.

    Ce n'est pas une liste d'interdiction déguisée : la fermeture entière est
    calculée, et on affirme l'absence des paquets dont la présence signifierait
    que cette voie peut atteindre l'exécution adressée (son sémaphore unique)
    ou un registre d'outils vivant.
    """

    loaded = _closure("jarvis.core.presentation_speculative")
    for forbidden in ("jarvis.core.back_brain", "jarvis.core.owned_job_execution",
                      "jarvis.core.tools", "jarvis.core.executors", "jarvis.core.brain_service",
                      "jarvis.runtime.claude_local", "jarvis.runtime.display_mcp"):
        assert forbidden not in loaded, forbidden


def test_la_voie_ambiante_ne_depend_toujours_pas_de_la_preparation():
    """Le couplage reste à sens unique : la Slice 06 remet, elle n'appelle pas.

    La fermeture exacte de la voie ambiante est gardée par son propre test
    (`test_ambient_ingestion_lane.py`). Celui-ci dit la moitié qui appartient à
    la Slice 08 : rien de cette Slice n'est entré là-bas.
    """

    loaded = _closure("jarvis.runtime.ambient_lane")
    assert "jarvis.core.presentation_speculative" not in loaded
    assert "jarvis.domain.presentation_speculative" not in loaded
    assert "jarvis.runtime.presentation_staging" not in loaded


# ==========================================================================
# 12. Gardes exercées dans l'état pour lequel elles existent
#
# Cette section entière est née des survivants d'une série de mutations. Trois
# d'entre eux disaient la même chose : la garde de chargement de la table de
# capacités n'était jamais atteinte dans l'état qu'elle surveille — le
# troisième motif d'échec de test catalogué par cette tâche (Slices 06 et 07).
# ==========================================================================


def test_la_garde_de_table_refuse_un_outil_de_risque_write():
    """M03 : `GRANTABLE_RISKS` doit exclure `WRITE`, et la garde doit le dire.

    La garde tournait à chaque import sans jamais rencontrer une table fautive,
    donc élargir `GRANTABLE_RISKS` à tout `RiskLevel` ne cassait rien. On la met
    ici devant la table qu'elle existe pour refuser.
    """

    from jarvis.domain import presentation_speculative as module

    assert RiskLevel.WRITE not in GRANTABLE_RISKS
    saved_risk = dict(module.SPECULATIVE_TOOL_RISK)
    saved_tools = dict(module.CAPABILITY_TOOLS)
    try:
        module.SPECULATIVE_TOOL_RISK["memory_append"] = RiskLevel.WRITE
        module.CAPABILITY_TOOLS[SpeculativeCapability.DATA_ANALYSIS] = frozenset(
            {"Read", "memory_append"}
        )
        with pytest.raises(RuntimeError) as caught:
            module._check_capability_table()
        assert "memory_append" in str(caught.value)
    finally:
        module.SPECULATIVE_TOOL_RISK.clear()
        module.SPECULATIVE_TOOL_RISK.update(saved_risk)
        module.CAPABILITY_TOOLS.clear()
        module.CAPABILITY_TOOLS.update(saved_tools)
    module._check_capability_table()  # la vraie table repasse


def test_la_garde_de_table_refuse_un_outil_interdit_quelle_que_soit_sa_casse():
    """M05 : la comparaison doit être insensible à la casse.

    « Bash » et « bash » sont le même outil ; `FORBIDDEN_TOOL_NAMES` est écrite
    en minuscules. Sans mise en minuscules, un outil nommé « Bash » passait la
    garde — et aucun test ne le lui avait jamais présenté.
    """

    from jarvis.domain import presentation_speculative as module

    saved_risk = dict(module.SPECULATIVE_TOOL_RISK)
    saved_tools = dict(module.CAPABILITY_TOOLS)
    try:
        module.SPECULATIVE_TOOL_RISK["Bash"] = RiskLevel.READ  # menteur sur son risque
        module.CAPABILITY_TOOLS[SpeculativeCapability.CODE_INSPECTION] = frozenset({"Read", "Bash"})
        with pytest.raises(RuntimeError) as caught:
            module._check_capability_table()
        assert "Bash" in str(caught.value)
    finally:
        module.SPECULATIVE_TOOL_RISK.clear()
        module.SPECULATIVE_TOOL_RISK.update(saved_risk)
        module.CAPABILITY_TOOLS.clear()
        module.CAPABILITY_TOOLS.update(saved_tools)
    module._check_capability_table()


def test_la_garde_de_table_refuse_un_outil_non_declare_et_une_capacite_sans_table():
    from jarvis.domain import presentation_speculative as module

    saved_tools = dict(module.CAPABILITY_TOOLS)
    try:
        module.CAPABILITY_TOOLS[SpeculativeCapability.DATA_ANALYSIS] = frozenset({"Inconnu"})
        with pytest.raises(RuntimeError) as caught:
            module._check_capability_table()
        assert "Inconnu" in str(caught.value)

        module.CAPABILITY_TOOLS.clear()
        module.CAPABILITY_TOOLS.update(saved_tools)
        del module.CAPABILITY_TOOLS[SpeculativeCapability.CODE_INSPECTION]
        with pytest.raises(RuntimeError) as caught:
            module._check_capability_table()
        assert "code_inspection" in str(caught.value)
    finally:
        module.CAPABILITY_TOOLS.clear()
        module.CAPABILITY_TOOLS.update(saved_tools)
    module._check_capability_table()


def test_la_table_des_risques_ne_contredit_jamais_la_politique_canonique():
    """M01 : deux tables qui parlent du même outil doivent s'accorder.

    `V1_ACTION_POLICY` est la source canonique du risque d'une action. Là où un
    nom est commun aux deux, le risque doit être le même — sinon cette voie
    aurait sa propre opinion sur ce qu'écrire veut dire, ce qui est la façon
    dont deux vocabulaires finissent par diverger en silence.
    """

    from jarvis.security.policy import V1_ACTION_POLICY

    canonical = {kind.value: policy.risk for kind, policy in V1_ACTION_POLICY.items()}
    for tool, risk in SPECULATIVE_TOOL_RISK.items():
        if tool in canonical:
            assert risk is canonical[tool], (tool, risk, canonical[tool])
    # `memory_append` est `WRITE` dans la politique canonique : il ne doit donc
    # ni apparaitre ici avec un autre risque, ni etre accorde.
    assert canonical["memory_append"] is RiskLevel.WRITE
    assert SPECULATIVE_TOOL_RISK.get("memory_append") is None


@pytest.mark.asyncio
async def test_la_preemption_ne_sacrifie_jamais_un_travail_explicite():
    """M12 : seul le spéculatif est sacrificiel (D08).

    Le bassin ne contient **que** des travaux explicites : il n'y a rien à
    sacrifier, et un tour adressé n'a pas le droit d'en prendre un.
    """

    store = make_store()
    runner = NeverFinishingRunner()
    service = make_service(store, runner)
    # Le bassin doit être **plein**, et plein d'explicites seulement. Sinon
    # `note_addressed_turn` sort avant d'avoir à choisir une victime, et le
    # filtre que ce test existe pour garder n'est jamais atteint — c'est
    # exactement le motif que cette tâche a catalogué trois fois.
    for index in range(MAX_SPECULATIVE_POOL):
        speak(store, f"e{index}", f"demande explicite {index}")
        assert service.reserve_explicit(
            topic=f"explicite{index}", capabilities=(SpeculativeCapability.DATA_ANALYSIS,),
            utterance_id=f"e{index}", text=f"demande explicite {index}",
        ) is SpeculativeAdmission.ACCEPTED
    await asyncio.sleep(0)
    assert service.explicit_in_flight == MAX_SPECULATIVE_POOL
    assert service.speculative_in_flight == 0
    assert service.free_explicit_slots == 0  # la garde est bien atteinte

    assert service.note_addressed_turn() == ()
    assert service.explicit_in_flight == MAX_SPECULATIVE_POOL
    assert service.counters.preempted == 0
    assert runner.cancelled == 0
    await service.stop()


@pytest.mark.asyncio
async def test_une_cle_terminee_est_rendue_et_la_table_ne_grossit_pas():
    """M16 : la table de coalescence ne doit pas fuir.

    Aucun comportement visible ne changeait quand la clé restait inscrite — le
    travail mort n'étant plus dans le bassin, une nouvelle admission passait
    quand même. Seule la taille de la table le dit, d'où `tracked_keys`.
    """

    store = make_store()
    service = make_service(store, ScriptedRunner())
    for index in range(4):
        speak(store, f"u{index}", f"sujet numero {index}")
        service.submit_trigger(
            trigger(AmbientTriggerKind.NEW_TOPIC, f"u{index}", f"sujet numero {index}")
        )
        # Pendant le vol la cle EST suivie : sans cette moitie, un
        # `tracked_keys` cable a zero passerait le test et la fuite reviendrait.
        assert service.stats()["tracked_keys"] == 1
        await service.drain()
        assert service.stats()["tracked_keys"] == 0
    assert service.stats()["in_flight"] == 0


@pytest.mark.asyncio
async def test_la_provenance_porte_l_heure_de_la_parole_pas_celle_du_rangement():
    """M17 : `observed_at` vient du fil, jamais de l'horloge du service.

    Le test d'origine faisait parler l'énonciation à l'instant même où l'horloge
    du service était figée : les deux valeurs étaient identiques, donc les
    confondre ne cassait rien. C'est la Slice 06 mot pour mot — un test qui
    exerce le code d'une garde sans atteindre l'état qu'elle garde — et ici le
    champ est celui sur lequel D06 mesure le retard.
    """

    spoken = NOW - timedelta(seconds=90)
    store = make_store()
    speak(store, "u1", "on cite le rapport", at=spoken)
    service = make_service(store, ScriptedRunner((DOC_FINDING,)))  # horloge figée à NOW
    service.submit_trigger(trigger(AmbientTriggerKind.EXTERNAL_REFERENCE, "u1", "le rapport"))
    await service.drain()

    resource = store.snapshot.working_set.resources[0]
    assert resource.provenance.observed_at == spoken
    assert resource.provenance.observed_at != NOW
    assert resource.prepared_at == NOW  # la préparation, elle, date de maintenant


@pytest.mark.asyncio
async def test_un_montage_rate_est_impute_au_montage_et_pas_a_la_reference():
    """M24 : un identifiant vide ne doit pas devenir une référence invalide.

    Sans l'arrêt net, la ressource partait avec un locator vide et se faisait
    refuser par le contrat de la Slice 04 : même résultat visible, mais le
    compteur accusait la référence au lieu du monteur. Un diagnostic qui désigne
    le mauvais coupable coûte plus cher qu'une absence de diagnostic.
    """

    store = make_store()
    speak(store, "u1")
    stager = FakeStager(fail=True)
    finding = PreparedFinding(kind=ResourceKind.NOTE, locator="note:x", stage_hidden=True)
    service = make_service(store, ScriptedRunner((finding,)), stager=stager)
    assert stage_explicit(service, store, utterance_id="u1") is SpeculativeAdmission.ACCEPTED
    await service.drain()

    assert service.counters.stage_failures == 1
    assert service.counters.findings_invalid == 0
    assert store.snapshot.working_set.resources == ()


@pytest.mark.asyncio
async def test_un_resultat_revenu_dans_une_seance_du_meme_nom_est_quand_meme_perime():
    """M30 : la génération, pas seulement l'identifiant de séance.

    Une séance retirée puis rouverte **sous le même nom** rend la comparaison
    d'identifiants muette. Seul le compteur de génération distingue les deux
    vies, et sans lui un travail de la vie précédente rangerait sa préparation
    dans la nouvelle.
    """

    store = make_store()
    speak(store, "u1")
    gate = asyncio.Event()

    class Slow:
        async def prepare(self, request):
            await gate.wait()
            return SpeculativeOutcome((DOC_FINDING,))

    service = make_service(store, Slow())
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    job = service._jobs[service.in_flight[0]]
    task = job.task
    service._release(job)

    service.retire("mode_change")
    service.bind_session(SESSION)  # même nom, autre vie
    gate.set()
    await asyncio.gather(task, return_exceptions=True)

    assert service.counters.results_stale_generation == 1
    assert store.snapshot.working_set.resources == ()


class _CapturingTransport:
    """Transport de scène qui retient la commande sérialisée et répond `applied`."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def scene_command(self, wire, *, connect_timeout_s, read_timeout_s):
        self.sent.append(wire)
        return {"outcome": "applied", "reason": None, "scene_id": "s1", "epoch": "e", "revision": 7,
                "patch": {"schema_version": 1, "revision": 7,
                          "ops": [{"op": "delete_relation", "relation_id": "x"}]}}

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_l_outil_d_affichage_reel_envoie_bien_une_creation_masquee():
    """M25 : la modification de `display_mcp` est exercée pour de vrai.

    Les autres tests de montage emploient un faux outil d'affichage, donc rien
    ne prouvait que `SceneDisplayTools.create_object` transporte réellement la
    visibilité. Ici c'est la **vraie** classe, et l'assertion porte sur la
    commande sérialisée qui part vers Core.
    """

    from jarvis.runtime.display_mcp import SceneDisplayTools

    transport = _CapturingTransport()
    tools = SceneDisplayTools(transport, id_factory=lambda: "abc123")
    answer = await tools.create_object(
        kind="artifact", category="preparation", title="Marges", summary="chart:marges",
        visibility=Visibility.HIDDEN.value,
    )

    assert answer["object_id"] == "brain-artifact-abc123"
    assert len(transport.sent) == 1
    wire = transport.sent[0]
    assert wire["op"] == "upsert_object"
    assert wire["actor"] == "brain"
    assert wire["fields"]["visibility"] == Visibility.HIDDEN.value


@pytest.mark.asyncio
async def test_l_outil_d_affichage_reel_omet_la_visibilite_quand_on_ne_la_donne_pas():
    """Le pendant : le chemin du cerveau n'est pas modifié par cette Slice.

    Sans ce test, « la visibilité est transportée » et « la visibilité est
    toujours posée » auraient la même preuve, et l'outil du cerveau aurait pu
    changer de comportement sans que rien ne le dise.
    """

    from jarvis.runtime.display_mcp import SceneDisplayTools

    transport = _CapturingTransport()
    tools = SceneDisplayTools(transport, id_factory=lambda: "abc123")
    await tools.create_object(kind="artifact", category="preparation", title="Marges")
    assert "visibility" not in transport.sent[0]["fields"]


def test_l_outil_mcp_du_cerveau_n_expose_pas_la_visibilite_a_la_creation():
    """La visibilité à la création est un chemin interne, pas une capacité du cerveau.

    Assertion sur la **signature** de la fonction que FastMCP publie, pas sur du
    texte source : c'est elle que le CLI voit, et son paramètre `visibility` ne
    doit pas exister. Le cerveau crée ce qu'il montre ; seule la préparation
    monte du masqué.
    """

    import inspect

    from jarvis.runtime import display_mcp

    internal = inspect.signature(display_mcp.SceneDisplayTools.create_object)
    assert "visibility" in internal.parameters  # le chemin interne existe
    assert internal.parameters["visibility"].default is None


# ==========================================================================
# 13. Les chemins qu'aucun test n'empruntait
#
# Cinq des six defauts bloquants de la revue vivaient sur des chemins ou aucun
# test n'entrait : `stop()` apres la fin des travaux, le montage depuis un
# travail ambiant, la duree de vie d'un objet monte, la borne d'une cle, et la
# fonction que FastMCP publie reellement. La mutation ne pouvait pas les voir :
# elle prouve que les tests attrapent un changement sur les chemins qu'ils
# parcourent deja. On entre donc d'abord dans l'etat, puis on mute.
# ==========================================================================


@pytest.mark.asyncio
async def test_stop_rend_la_main_quand_tout_est_deja_termine():
    """B1 : le cas que les trente-huit appels existants n'atteignaient pas.

    Tous entraient dans `drain()`/`stop()` pendant qu'une tâche tournait
    encore, où l'ordre des rappels `done` sauvait la mise. Ici les travaux sont
    **déjà terminés** quand `stop()` est appelé : attendre un `gather` dont
    tous les enfants sont finis ne suspend pas, donc les rappels `done` en
    attente ne tournent jamais et la boucle tournait à vide pour toujours.

    Le scénario est celui d'un appelant ordinaire : préparer, attendre que le
    bassin se vide, puis arrêter la voie. `_jobs` se vide un tour avant
    `_tasks`, donc le bassin dit « rien en vol » alors qu'une tâche est encore
    inscrite.

    **Limite assumée de ce test.** En cas de régression il *bloque* au lieu
    d'échouer proprement, et le `wait_for` ci-dessous n'y change rien : le
    défaut est une boucle d'attente active qui affame la boucle d'événements,
    donc aucune échéance interne ne peut se déclencher pendant qu'elle tourne
    (mesuré : 710 550 tours en deux secondes, un minuteur de 0,2 s incapable de
    partir). Seule une échéance **hors processus** ferait mieux, et
    `pytest-timeout` n'est pas installé dans cet environnement. Un blocage en
    intégration continue reste un échec ; il est simplement moins lisible, et
    il valait mieux l'écrire que le découvrir.
    """

    store = make_store()
    service = make_service(store, ScriptedRunner())
    for index in range(3):
        speak(store, f"u{index}", f"sujet numero {index}")
        service.submit_trigger(
            trigger(AmbientTriggerKind.NEW_TOPIC, f"u{index}", f"sujet numero {index}")
        )

    # Attendre comme un appelant le ferait : jusqu'à ce que le bassin soit vide.
    for _ in range(200):
        await asyncio.sleep(0)
        if not service.in_flight:
            break
    assert service.in_flight == ()

    await asyncio.wait_for(service.stop(), timeout=5.0)
    assert service.active is False
    # Et une seconde fois : `stop()` doit rester idempotent.
    await asyncio.wait_for(service.stop(), timeout=5.0)


@pytest.mark.asyncio
async def test_drain_rend_la_main_sur_des_taches_deja_terminees():
    """Le même piège, sur `drain()` seul, sans passer par `stop()`."""

    store = make_store()
    service = make_service(store, ScriptedRunner())
    speak(store, "u1")
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    await asyncio.wait_for(service.drain(), timeout=5.0)
    # Deuxième passage : plus rien à attendre, et surtout pas de boucle folle.
    await asyncio.wait_for(service.drain(), timeout=5.0)
    assert service.in_flight == ()


@pytest.mark.asyncio
async def test_un_objet_monte_est_repris_quand_la_seance_se_termine():
    """B3 : un objet de scène est durable, donc la voie doit savoir l'effacer.

    Il descend jusqu'à `INSERT INTO scene_objects` et survit au redémarrage du
    processus. Sans reprise, chaque préparation en laissait un pour toujours —
    et un `scene_set_visibility(scope="all_hidden")` du cerveau les révélait
    ensuite tous d'un coup, y compris ceux que l'utilisateur n'avait jamais
    demandés.
    """

    store = make_store()
    speak(store, "u1")
    stager = FakeStager()
    finding = PreparedFinding(kind=ResourceKind.NOTE, locator="note:x", stage_hidden=True)
    service = make_service(store, ScriptedRunner((finding,)), stager=stager)
    assert stage_explicit(service, store, utterance_id="u1") is SpeculativeAdmission.ACCEPTED
    await service.drain()
    assert len(stager.staged) == 1
    assert service.stats()["staged_objects"] == 1

    service.retire("session_ended")
    await service.drain()

    assert stager.discarded == [stager.staged[0]["object_id"]]
    assert service.stats()["staged_objects"] == 0
    assert service.counters.staged_objects_discarded == 1


@pytest.mark.asyncio
async def test_quitter_presentation_reprend_aussi_les_objets_montes():
    """Le mode compte autant que la séance : D13 vaut pour les deux sorties."""

    store = make_store()
    speak(store, "u1")
    stager = FakeStager()
    finding = PreparedFinding(kind=ResourceKind.NOTE, locator="note:x", stage_hidden=True)
    service = make_service(store, ScriptedRunner((finding,)), stager=stager)
    stage_explicit(service, store, utterance_id="u1")
    await service.drain()
    assert len(stager.staged) == 1

    service.apply_interaction_mode("assistant")
    await service.drain()
    assert len(stager.discarded) == 1


@pytest.mark.asyncio
async def test_une_reprise_en_echec_est_comptee_et_dite_jamais_avalee():
    store = make_store()
    speak(store, "u1")
    stager = FakeStager(fail_discard=True)
    finding = PreparedFinding(kind=ResourceKind.NOTE, locator="note:x", stage_hidden=True)
    diagnostics = RecordingDiagnostics()
    service = make_service(store, ScriptedRunner((finding,)), stager=stager, diagnostics=diagnostics)
    stage_explicit(service, store, utterance_id="u1")
    await service.drain()

    service.retire("session_ended")
    await service.drain()
    assert service.counters.discard_failures == 1
    assert service.counters.staged_objects_discarded == 0
    assert any(line["kind"].endswith(".discard_failed") for line in diagnostics.lines)


@pytest.mark.asyncio
async def test_le_nombre_d_objets_montes_est_borne():
    """Un objet durable sans plafond finit par remplir la scène (`SCENE_FULL`)."""

    store = make_store()
    stager = FakeStager()
    findings = tuple(
        PreparedFinding(kind=ResourceKind.NOTE, locator=f"note:{i}", stage_hidden=True)
        for i in range(MAX_FINDINGS_PER_JOB)
    )
    service = make_service(store, ScriptedRunner(findings), stager=stager)
    for index in range(4):
        speak(store, f"u{index}", f"visuel numero {index}")
        service.reserve_explicit(
            topic=f"visuel{index}", capabilities=(STAGING_CAPABILITY,),
            utterance_id=f"u{index}", text=f"visuel numero {index}",
        )
        await service.drain()

    assert len(stager.staged) == MAX_STAGED_OBJECTS
    assert service.counters.stage_refused > 0
    assert service.stats()["staged_objects"] == MAX_STAGED_OBJECTS


def test_une_cle_longue_reste_une_demande_legale():
    """B5 : la troncature ne doit pas rendre illégale une demande qui ne l'est pas.

    Couper à 64 une chaîne aux espaces réduits tombe régulièrement sur un
    espace ; la clé était alors refusée `speculative_key_untrimmed`, le refus
    avalé, et le déclencheur répondu `REJECTED / speculative_trigger_unkeyable`
    — « ce n'était pas une demande légale » alors que si. Et comme
    `_references` (Slice 06) rend des phrases entières, les déclencheurs longs
    sont le cas **courant**.
    """

    hostile = "a" * 63 + " bbbbbb cccc"
    assert job_key_text(hostile) == job_key_text(hostile).strip()
    SpeculativeJobKey(job_key_text(hostile))  # ne lève pas

    # Balayer toutes les positions de coupe : aucune ne doit produire de clé illégale.
    for width in range(1, 140):
        text = " ".join("mot" + str(n) for n in range(width))
        key = job_key_text(text)
        assert key == key.strip(), width
        if key:
            SpeculativeJobKey(key)


@pytest.mark.asyncio
async def test_un_declencheur_long_est_admis_et_non_refuse():
    """Le même défaut, vu du service : la réponse doit être une admission."""

    store = make_store()
    long_text = "le rapport trimestriel de la direction financiere " + "a" * 40
    speak(store, "u1", long_text)
    service = make_service(store, ScriptedRunner())
    assert service.submit_trigger(
        trigger(AmbientTriggerKind.EXTERNAL_REFERENCE, "u1", long_text)
    ) is SpeculativeAdmission.ACCEPTED
    assert service.counters.refused_rejected == 0
    await service.drain()


def test_la_coalescence_peut_fusionner_deux_affirmations_distinctes():
    """La borne de clé fait aussi des faux positifs, et il vaut mieux le dire.

    64 caractères contre `MAX_TRIGGER_TEXT_CHARS = 320` : deux phrases qui ne
    diffèrent qu'après le 64e caractère tombent sur la même clé, et la seconde
    est répondue `COALESCED` sans être préparée. C'est borné et l'échec va dans
    le sens sûr — on prépare moins, jamais plus — mais ce n'est pas la
    coalescence « par sujet » que le nom laisse croire.
    """

    base = "le chiffre a baisse de dix-sept pour cent au troisieme trimestre en "
    assert len(base) > MAX_SPECULATIVE_JOB_KEY_CHARS
    assert job_key_text(base + "France") == job_key_text(base + "Allemagne")


@pytest.mark.asyncio
async def test_l_outil_du_cerveau_ne_cree_jamais_un_objet_masque():
    """B6 : la garde d'origine testait la mauvaise fonction — et la deuxième aussi.

    La première inspectait `SceneDisplayTools.create_object`, le chemin
    interne, sous une docstring qui prétendait viser la surface MCP. La
    deuxième lisait le **schéma** publié par FastMCP — et j'ai reposé sur elle
    la mutation de QA (l'outil MCP passe `visibility="hidden"`) : elle est
    passée aussi. Un schéma ne voit pas un corps de fonction.

    La seule propriété qui compte est **comportementale** : appeler l'outil que
    le cerveau appelle doit produire une commande de scène **sans** visibilité,
    donc un objet visible. On traverse donc le serveur réellement construit
    jusqu'à la commande sérialisée.
    """

    from jarvis.runtime.display_mcp import SceneDisplayTools, build_server

    transport = _CapturingTransport()
    server = build_server(tools=SceneDisplayTools(transport, id_factory=lambda: "abc123"))
    await server.call_tool(
        "scene_create_object", {"kind": "artifact", "category": "research", "title": "Synthese"}
    )

    assert len(transport.sent) == 1
    fields = transport.sent[0]["fields"]
    assert "visibility" not in fields, (
        "le cerveau crée ce qu'il montre : seule la préparation spéculative monte du masqué"
    )
    assert fields["kind"] == "artifact"  # l'outil a bien fait son travail


def test_l_outil_du_cerveau_n_expose_pas_la_visibilite_dans_son_schema():
    """Le pendant déclaratif : le modèle ne peut pas non plus la demander.

    Nécessaire mais **pas** suffisant — voir le test précédent, qui est celui
    qui attrape une régression dans le corps de l'outil.
    """

    import asyncio as _asyncio

    from jarvis.runtime.display_mcp import build_server

    server = build_server(tools=FakeDisplayTools())
    published = [
        tool for tool in _asyncio.run(server.list_tools())
        if tool.name == "scene_create_object"
    ]
    assert len(published) == 1, "l'outil doit exister, sinon l'absence ne prouve rien"
    properties = set(published[0].inputSchema.get("properties", {}))
    assert "visibility" not in properties
    assert {"kind", "category", "title", "summary"} <= properties
    # Le chemin interne, lui, la porte : c'est ce qui rend le montage atomique.
    assert "visibility" in inspect.signature(
        __import__("jarvis.runtime.display_mcp", fromlist=["x"]).SceneDisplayTools.create_object
    ).parameters


@pytest.mark.asyncio
async def test_aucune_ligne_de_trace_ne_porte_le_texte_d_une_panne():
    """Item 2 : trois lignes fuyaient de la parole par `f"...{exc}"`.

    L'exécutant reçoit `request.text`, donc de la parole. N'importe lequel qui
    renvoie son entrée dans un message d'erreur la déposait dans la trace, au
    niveau `error`, dans un fichier durable. Le test conduit les chemins
    d'échec — pas seulement le chemin heureux, où la règle est vraie sans
    effort — et c'est cette moitié-là qui manquait.
    """

    phrase = "le chiffre d affaires du troisieme trimestre est de quarante-deux millions"
    store = make_store()
    speak(store, "u1", phrase)
    diagnostics = RecordingDiagnostics()

    class EchoingRunner:
        """Un exécutant qui renvoie son entrée dans son exception. Cas réaliste."""

        async def prepare(self, request):
            raise RuntimeError(f"le fournisseur a refuse : {request.text}")

    service = make_service(store, EchoingRunner(), diagnostics=diagnostics)
    service.submit_trigger(trigger(AmbientTriggerKind.CHECKABLE_CLAIM, "u1", phrase))
    await service.drain()

    # Et le chemin de montage en échec, qui fuyait deux fois.
    stager = FakeStager(fail=True)
    speak(store, "u2", phrase)
    service2 = make_service(store, ScriptedRunner((
        PreparedFinding(kind=ResourceKind.NOTE, locator="note:x", stage_hidden=True),
    )), stager=stager, diagnostics=diagnostics)
    stage_explicit(service2, store, utterance_id="u2")
    await service2.drain()

    assert service.counters.failed == 1
    assert any(line["kind"].endswith(".failed") for line in diagnostics.lines)
    blob = json.dumps(diagnostics.lines, ensure_ascii=False)
    for fragment in ("quarante-deux", "chiffre d affaires", "troisieme trimestre"):
        assert fragment not in blob, fragment


@pytest.mark.asyncio
async def test_un_journal_en_panne_se_compte_au_lieu_de_disparaitre():
    """Item 4 : sinon `stats()` annonce une voie saine et la trace est vide."""

    class Broken:
        def emit(self, *args, **kwargs):
            raise RuntimeError("journal down")

    store = make_store()
    speak(store, "u1")
    service = make_service(store, ScriptedRunner((DOC_FINDING,)), diagnostics=Broken())
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    await service.drain()

    assert len(store.snapshot.working_set.resources) == 1  # la voie fonctionne
    assert service.stats()["diagnostic_failures"] > 0      # et elle le dit


@pytest.mark.asyncio
async def test_un_refus_nomme_le_sujet_qu_il_refuse():
    """Item 5 : « pourquoi rien n'a-t-il été préparé sur ce sujet ? »"""

    store = make_store()
    speak(store, "u1")
    diagnostics = RecordingDiagnostics()
    service = make_service(store, ScriptedRunner(), diagnostics=diagnostics)
    assert service.submit_trigger(
        trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"), session_id="autre-seance"
    ) is SpeculativeAdmission.STALE_SESSION
    refused = next(line for line in diagnostics.lines if line["kind"].endswith(".refused"))
    assert len(refused["data"]["key"]) == 12
    await service.drain()


def test_submit_trigger_ne_leve_jamais_sans_boucle_d_evenements():
    """Item 6 : sa docstring promet une valeur typée, y compris ici.

    Sans boucle, `asyncio.create_task` lève `RuntimeError`. Slice 06 rattrape
    ce que son consommateur de déclencheurs lève, donc la panne aurait été
    comptée par la voie **ambiante** et n'aurait paru nulle part ici.
    """

    store = make_store()
    store_session = store.snapshot.session_id
    service = PresentationSpeculativeService(store=store, runner=ScriptedRunner(), clock=lambda: NOW)
    service.bind_session(store_session)
    store.observe(store_session, "u1", "la marge", spoken_at=NOW)

    answer = service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    assert answer is SpeculativeAdmission.INACTIVE
    assert service.in_flight == ()


@pytest.mark.asyncio
async def test_la_generation_monte_avant_les_annulations():
    """Item 7 : la docstring disait l'inverse du code.

    Inoffensif tant qu'aucun `await` ne s'intercale — et c'est précisément pour
    survivre au jour où quelqu'un en ajoute un que l'invariant existe. Le test
    lit la génération **depuis l'intérieur** de l'annulation.
    """

    store = make_store()
    speak(store, "u1")
    seen = {}

    class Watching:
        async def prepare(self, request):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                seen["generation"] = service.generation
                raise

    service = make_service(store, Watching())
    before = service.generation
    service.submit_trigger(trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge"))
    await asyncio.sleep(0)

    service.retire("test")
    for _ in range(3):
        await asyncio.sleep(0)

    assert seen["generation"] == before + 1, "la génération doit avoir monté avant l'annulation"


def test_une_admission_sans_boucle_ne_laisse_pas_de_coroutine_orpheline():
    """M51 : `create_task` echoue apres que la coroutine existe deja.

    Sans `runnable.close()`, elle est collectee plus tard avec
    « coroutine was never awaited » — un avertissement qui apparait dans un
    test **sans rapport**, souvent des tours plus loin, et qu'on passe alors du
    temps a attribuer au mauvais endroit. Le refus typé etait correct ; le
    menage ne l'etait pas, et rien ne le voyait.
    """

    import gc
    import warnings

    store = make_store()
    session = store.snapshot.session_id
    service = PresentationSpeculativeService(store=store, runner=ScriptedRunner(), clock=lambda: NOW)
    service.bind_session(session)
    store.observe(session, "u1", "la marge", spoken_at=NOW)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert service.submit_trigger(
            trigger(AmbientTriggerKind.NEW_TOPIC, "u1", "la marge")
        ) is SpeculativeAdmission.INACTIVE
        gc.collect()

    orphans = [w for w in caught if "never awaited" in str(w.message)]
    assert orphans == [], [str(w.message) for w in orphans]


@pytest.mark.asyncio
async def test_le_journal_du_monteur_porte_une_phrase_lisible():
    """M52 : une ligne dont le message est son propre `kind` n'apprend rien.

    Une premiere version passait le nom de l'evenement comme message, donc la
    colonne « message » du journal repetait la colonne « kind » et l'operateur
    lisait deux fois la meme chose.
    """

    lines: list[dict] = []

    class Journal:
        def emit(self, kind, message, *, level="info", data=None):
            lines.append({"kind": kind, "message": message, "level": level, "data": data or {}})

    tools = FakeDisplayTools()
    stager = DisplaySceneStager(tools, journal=Journal())
    object_id = await stager.stage_hidden(category="preparation", title="Marges", summary="chart:marges")
    await stager.reveal(object_id)
    await stager.discard([object_id])

    assert [line["kind"] for line in lines] == [
        "presentation.staging.staged",
        "presentation.staging.revealed",
        "presentation.staging.discarded",
    ]
    for line in lines:
        assert line["message"] != line["kind"], line
        assert " " in line["message"], line  # une phrase, pas un identifiant
        assert len(line["message"]) > 12, line


@pytest.mark.asyncio
async def test_un_journal_de_monteur_en_panne_est_compte():
    """Meme regle que la voie : un puits casse ne disparait pas en silence."""

    class Broken:
        def emit(self, *args, **kwargs):
            raise RuntimeError("journal down")

    tools = FakeDisplayTools()
    stager = DisplaySceneStager(tools, journal=Broken())
    object_id = await stager.stage_hidden(category="preparation", title="T", summary="s")
    assert object_id  # le montage aboutit malgre le journal casse
    assert stager.diagnostic_failures == 1
