"""Plan de contrôle du mode d'interaction (Slice 02, rendu dérivé par la Slice 01b
de `jarvis-board-ui-wheel-dossier-refactor`).

Ce que cette suite prouve, dans l'ordre où ça compte :

- **plus aucun écrivain hors de Core** : le Control Center refuse tout choix
  (409 `interaction_mode_derived`, journalisé), n'écrit ni ne lit la clé
  globale `interaction_mode` du fichier de réglages, et ne rejoue rien vers Core ;
- `/api/status` publie, en lecture seule, le mode effectif de Core **et** le
  mode que désigne le type du Board actif (`board_mode`) ;
- la **valeur effective** a un seul propriétaire, Core, avec une révision qui
  ne redescend jamais et qu'une écriture idempotente ne fait pas monter ;
- **REUNION** est annoncé partout et activable nulle part, avec le code stable
  `interaction_mode_not_implemented` ;
- **changer de mode ne redémarre pas Voice** (Décision D15) : ni
  `voice.switch.requested`, ni fichier de bascule, ni `configuration_id`
  différent.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.core.interaction_mode import (
    INTERACTION_MODE_CHANGED,
    InteractionModeDisposition,
    InteractionModeService,
    supported_modes,
)
from jarvis.domain.interaction_mode import (
    INTERACTION_MODE_DERIVED, INTERACTION_MODE_DERIVED_MESSAGE, InteractionMode, InteractionModeError,
)
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.interaction_mode_observer import InteractionModeObserver
from jarvis.runtime.interaction_mode_view import CoreInteractionModeView
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.voice_composition import resolve_voice_composition
from jarvis.runtime.voice_switch import REQUEST_FILE
from jarvis.domain.v2 import ProtocolEnvelope
from aiohttp import web


# --------------------------------------------------------------------- outils


class RecordingBus:
    """Bus minimal : garde ce qui a été publié, dans l'ordre."""

    def __init__(self) -> None:
        self.published: list[ProtocolEnvelope] = []

    async def publish(self, envelope: ProtocolEnvelope) -> None:
        self.published.append(envelope)


class BrokenBus:
    async def publish(self, envelope: ProtocolEnvelope) -> None:
        raise RuntimeError("bus down")


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):  # noqa: ANN001
        self.records.append((kind, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [kind for kind, _level, _data in self.records]


class ServiceReader:
    """Transport factice, en lecture seule : branche la vue du Control Center sur un vrai service Core."""

    def __init__(self, service: InteractionModeService) -> None:
        self.service = service
        self.reads = 0

    async def interaction_mode(self) -> dict:
        self.reads += 1
        return self.service.snapshot()

    async def close(self) -> None:
        return None


class UnreachableReader:
    async def interaction_mode(self) -> dict:
        raise ConnectionError("Core session token is unavailable")

    async def close(self) -> None:
        return None


class BoardSessions:
    """`GET /v1/boards/active` tel que Core le rend : seul le type du Board compte ici."""

    def __init__(self, board_kind: str | None) -> None:
        self.board_kind = board_kind

    async def active_board(self) -> dict:
        return {"board": {"board_id": "b1", "title": "Board", "board_kind": self.board_kind}}


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


#: Une vie de Core, pour les charges utiles fabriquées à la main.
EPOCH = "core-life-a"


def state(mode: str, revision: int, *, epoch: str | None = EPOCH) -> dict:
    """Ce que Core publie : un mode, une révision, et la vie qui les porte."""

    payload = {"mode": mode, "revision": revision}
    if epoch is not None:
        payload["epoch"] = epoch
    return payload


def build_control(tmp_path, *, reader=None, board_kind=None):
    service = InteractionModeService(events=RecordingBus())
    view = CoreInteractionModeView(ServiceReader(service) if reader is None else reader)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, interaction_mode_view=view)
    if board_kind is not None:
        control.sessions = BoardSessions(board_kind)
    return control, service, view


def trace_kinds(control) -> list[str]:
    return [item["kind"] for item in read_jsonl_tail(control.journal.trace_path, limit=500)]


# ------------------------------------------------ mode dérivé : aucun écrivain hors de Core (Slice 01b)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"mode": "presentation"}, {"mode": "assistant"}, {"mode": "meeting"}, {"mode": "fromage"},
    {}, None, "presentation", {"mode": "presentation", "schema_version": 4},
])
async def test_la_route_du_control_center_refuse_tout_choix_de_mode(tmp_path, payload):
    """`POST /api/interaction-mode` : 409 `interaction_mode_derived` quel que soit le corps.

    Rien n'est écrit (ni fichier de réglages, ni Core), la phrase française dit
    quoi faire à la place, le code stable voyage dans l'en-tête, et le refus
    laisse une ligne.
    """

    control, service, view = build_control(tmp_path)

    with pytest.raises(web.HTTPConflict) as refus:
        await control.save_interaction_mode(JsonRequest(payload))

    assert refus.value.headers["X-Jarvis-Error-Code"] == INTERACTION_MODE_DERIVED
    assert refus.value.text == INTERACTION_MODE_DERIVED_MESSAGE
    assert "Board Présentation" in refus.value.text
    assert service.mode is InteractionMode.ASSISTANT and service.revision == 0
    assert view.reader.reads == 0
    assert not (tmp_path / "control-center-settings.json").exists()
    [ligne] = [item for item in read_jsonl_tail(control.journal.trace_path, limit=50)
               if item["kind"] == "interaction.mode.refused"]
    assert ligne["level"] == "warning" and ligne["data"]["code"] == INTERACTION_MODE_DERIVED


@pytest.mark.asyncio
async def test_la_cle_globale_reste_dans_le_fichier_sans_etre_lue_ni_ecrite(tmp_path):
    """Un ancien `interaction_mode` du fichier de réglages n'a plus aucun effet.

    Il n'est pas nettoyé (pas de nettoyage destructif d'un fichier de
    l'utilisateur), mais ni le statut, ni `/api/settings`, ni la route ne le
    lisent, et un refus le laisse octet pour octet.
    """

    control, service, _view = build_control(tmp_path, board_kind="assistant")
    settings = control._settings()
    settings["interaction_mode"] = {"schema_version": 1, "mode": "presentation"}
    control._write_settings(settings)
    before = (tmp_path / "control-center-settings.json").read_bytes()

    block = json.loads((await control.status(None)).text)["interaction_mode"]
    assert block["mode"] == "assistant" and block["board_mode"] == "assistant"
    assert "interaction_mode" not in json.loads((await control.get_settings(None)).text)
    with pytest.raises(web.HTTPConflict):
        await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))

    assert (tmp_path / "control-center-settings.json").read_bytes() == before
    assert service.revision == 0


def test_le_control_center_n_a_plus_aucun_chemin_de_rejeu():
    """`startup` / `core_restart` / `save_retry` sont supprimés, pas désactivés."""

    for name in ("_schedule_interaction_mode_replay", "_replay_interaction_mode", "_reconcile_interaction_mode",
                 "report_interaction_mode_preference", "_core_boards_own_interaction_mode"):
        assert not hasattr(ControlCenter, name), name
    assert not hasattr(CoreInteractionModeView, "request")


# ------------------------------------------------ défauts et migration


# ------------------------------------------------ refus de REUNION


def test_reunion_est_annonce_partout_et_activable_nulle_part():
    annonces = {entry["value"]: entry for entry in supported_modes()}
    assert set(annonces) == {"assistant", "presentation", "meeting"}
    assert annonces["meeting"]["label"] == "REUNION"
    assert annonces["meeting"]["implemented"] is False
    assert annonces["meeting"]["status"] == "planned"
    assert annonces["presentation"]["implemented"] is True


@pytest.mark.asyncio
async def test_core_refuse_le_mode_reunion_sans_toucher_a_la_valeur_effective():
    service = InteractionModeService(events=RecordingBus(), diagnostics=RecordingDiagnostics())
    with pytest.raises(InteractionModeError) as refus:
        await service.request("meeting", source="test")
    assert refus.value.code == "interaction_mode_not_implemented"
    assert service.mode is InteractionMode.ASSISTANT
    assert service.revision == 0


@pytest.mark.asyncio
async def test_la_route_de_lecture_rend_le_bloc_du_statut(tmp_path):
    """`GET /api/interaction-mode` : le même bloc que `/api/status.interaction_mode`.

    Son `mode` de premier niveau est le mode **effectif** de Core (il était la
    préférence globale, ce qui était trompeur) ; il n'y a plus de `stored_*`.
    """

    control, service, _view = build_control(tmp_path, board_kind="presentation")
    await service.request("presentation", source="board_switch")

    payload = json.loads((await control.get_interaction_mode(None)).text)
    status = json.loads((await control.status(None)).text)["interaction_mode"]

    assert payload == status
    assert payload["mode"] == "presentation" and payload["revision"] == 1
    assert payload["board_mode"] == "presentation"
    assert not [key for key in payload if key.startswith("stored") or key in ("effective", "behaving")]


# ------------------------------------------------ révision et idempotence


@pytest.mark.asyncio
async def test_la_revision_monte_sur_un_changement_et_jamais_sur_une_repetition():
    bus = RecordingBus()
    service = InteractionModeService(events=bus)
    assert service.revision == 0

    _state, disposition = await service.request("presentation", source="test")
    assert disposition is InteractionModeDisposition.APPLIED
    assert service.revision == 1

    _state, disposition = await service.request("presentation", source="test")
    assert disposition is InteractionModeDisposition.UNCHANGED
    assert service.revision == 1
    assert len(bus.published) == 1

    await service.request("assistant", source="test")
    assert service.revision == 2
    assert [envelope.payload["mode"] for envelope in bus.published] == ["presentation", "assistant"]
    assert {envelope.message_type for envelope in bus.published} == {INTERACTION_MODE_CHANGED}


@pytest.mark.asyncio
async def test_une_demande_sans_effet_n_atteint_aucun_abonne_et_ne_publie_rien():
    """Slice 01a : plus aucun abonné ne reçoit les demandes sans effet (`with_unchanged` retiré avec l'écriture
    du mode sur le Board)."""

    bus = RecordingBus()
    service = InteractionModeService(events=bus)
    plain, full = [], []
    service.add_listener(plain.append)
    service.add_listener(full.append, with_state=True)
    with pytest.raises(TypeError):
        service.add_listener(full.append, with_unchanged=True)  # type: ignore[call-arg]

    state, disposition = await service.request("assistant", source="user")

    assert disposition is InteractionModeDisposition.UNCHANGED
    assert state.revision == 0 and service.state.source == "default"   # l'état effectif n'a pas bougé
    assert bus.published == [] and plain == [] and full == []

    await service.request("presentation", source="user")
    assert len(full) == 1 and len(plain) == 1 and full[0].source == "user"


@pytest.mark.asyncio
async def test_des_demandes_concurrentes_ne_produisent_qu_une_revision_par_changement():
    """Deux clics simultanés : une seule bascule, une seule révision, un seul évènement.

    Honnêteté sur ce que ce test prouve : aujourd'hui la section critique de
    `_set` ne contient aucun `await` qui rende la main, donc la garantie est
    tenue par la boucle asyncio mono-fil et ce test passerait aussi sans le
    verrou. Il verrouille le **comportement observable**, et le verrou reste
    pour le jour où cette section contiendra un point de suspension.
    """

    bus = RecordingBus()
    service = InteractionModeService(events=bus)

    results = await asyncio.gather(*(service.request("presentation", source=f"clic-{i}") for i in range(8)))

    applied = [d for _state, d in results if d is InteractionModeDisposition.APPLIED]
    assert len(applied) == 1
    assert service.revision == 1
    assert len(bus.published) == 1


@pytest.mark.asyncio
async def test_un_aller_retour_concurrent_laisse_une_revision_strictement_croissante():
    bus = RecordingBus()
    service = InteractionModeService(events=bus)

    await asyncio.gather(*(
        service.request(mode, source="test")
        for mode in ("presentation", "assistant", "presentation", "assistant", "presentation")
    ))

    revisions = [envelope.payload["revision"] for envelope in bus.published]
    assert revisions == sorted(set(revisions))
    assert revisions[-1] == service.revision
    assert service.revision >= 1


@pytest.mark.asyncio
async def test_une_panne_du_bus_ne_perd_pas_le_mode_et_le_dit():
    diagnostics = RecordingDiagnostics()
    service = InteractionModeService(events=BrokenBus(), diagnostics=diagnostics)

    state, disposition = await service.request("presentation", source="test")

    assert disposition is InteractionModeDisposition.APPLIED
    assert state.mode is InteractionMode.PRESENTATION
    assert service.snapshot()["mode"] == "presentation"
    assert "interaction.mode.publish_failed" in diagnostics.kinds()


@pytest.mark.asyncio
async def test_une_valeur_inconnue_demandee_explicitement_est_refusee_pas_repliee():
    service = InteractionModeService(events=RecordingBus())
    for value in ("simple", "continuous_brain", "", None, 3, "REUNION"):
        with pytest.raises(InteractionModeError) as refus:
            await service.request(value, source="test")
        assert refus.value.code == "interaction_mode_unknown"
    assert service.revision == 0


# ------------------------------------------------ réconciliation au démarrage


# ------------------------------------------------ /api/status


@pytest.mark.asyncio
async def test_le_statut_expose_le_mode_effectif_et_les_modes_annonces(tmp_path):
    control, service, _view = build_control(tmp_path)
    await service.request("presentation", source="test")

    response = await control.status(None)
    block = json.loads(response.text)["interaction_mode"]

    assert block["mode"] == "presentation"
    assert block["label"] == "PRESENTATION"
    assert block["revision"] == 1
    assert block["source"] == "core"
    assert block["core_reachable"] is True
    # Le mode du type du Board est nommé à part : ici le Control Center ne connaît pas Core.
    assert block["board_mode"] is None and block["board_mode_label"] is None
    assert [entry["value"] for entry in block["modes"]] == ["assistant", "presentation", "meeting"]
    assert [entry["implemented"] for entry in block["modes"]] == [True, True, False]


@pytest.mark.asyncio
@pytest.mark.parametrize("board_kind, board_mode, label", [
    ("assistant", "assistant", "SIMPLE"), ("presentation", "presentation", "PRESENTATION"),
    ("meeting", "meeting", "REUNION"),
])
async def test_le_statut_publie_le_mode_que_designe_le_type_du_board_actif(tmp_path, board_kind, board_mode, label):
    """Décision 02 : un Board Réunion garde REUNION visible, sans qu'il se comporte."""

    control, _service, _view = build_control(tmp_path, board_kind=board_kind)

    block = json.loads((await control.status(None)).text)["interaction_mode"]

    assert (block["board_mode"], block["board_mode_label"]) == (board_mode, label)
    # Ce qui tourne reste ce que Core dit (ici, son défaut).
    assert block["mode"] == "assistant" and block["source"] == "core"


@pytest.mark.asyncio
async def test_un_board_actif_hors_contrat_est_dit_et_ne_designe_aucun_mode(tmp_path):
    control, _service, _view = build_control(tmp_path, board_kind="workshop")

    for _ in range(3):
        block = json.loads((await control.status(None)).text)["interaction_mode"]

    assert block["board_mode"] is None and block["mode"] == "assistant"
    lignes = [item for item in read_jsonl_tail(control.journal.trace_path, limit=100)
              if item["kind"] == "interaction.mode.board_unknown"]
    # Une ligne, pas une par battement.
    assert [item["data"]["code"] for item in lignes] == ["invalid_board_snapshot"]


@pytest.mark.asyncio
async def test_le_statut_ne_tombe_pas_quand_core_est_injoignable(tmp_path):
    control, _service, _view = build_control(tmp_path, reader=UnreachableReader())

    block = json.loads((await control.status(None)).text)["interaction_mode"]

    assert block["core_reachable"] is False
    assert block["error"]["code"] == "core_unreachable"
    assert block["mode"] == "assistant"


@pytest.mark.asyncio
async def test_les_reglages_ne_publient_plus_de_mode(tmp_path):
    """Réglages n'offre aucun choix de mode : le mode n'est pas un réglage."""

    control, _service, _view = build_control(tmp_path)

    payload = json.loads((await control.get_settings(None)).text)

    assert "interaction_mode" not in payload


# ------------------------------------------------ G1 : l'axe reste à part


def test_le_mode_n_est_pas_un_reglage_vocal_persistable():
    """Il n'entre pas dans la liste blanche de la voix (G3) : il n'est plus un réglage du tout."""

    from jarvis.runtime.voice_settings_schema import PERSISTABLE_OPTION_IDS

    assert "interaction_mode" not in PERSISTABLE_OPTION_IDS


# ------------------------------------------------ D15 : aucun redémarrage


@pytest.mark.asyncio
async def test_changer_de_mode_ne_demande_aucun_redemarrage_de_voice(tmp_path):
    """Décision D15, la contrainte qui protège une présentation en cours.

    Le mode change dans Core (bascule de Board, lecture du Studio) ; les choix
    refusés du Control Center n'y changent rien non plus. Deux preuves
    indépendantes : aucune ligne `voice.switch.requested`, aucun fichier de
    bascule, et le `configuration_id` identique en garde-fou.
    """

    control, service, _view = build_control(tmp_path)
    avant = resolve_voice_composition(control._settings()).configuration_id

    await service.request("presentation", source="board_switch")
    for mode in ("presentation", "assistant"):
        with pytest.raises(web.HTTPConflict):
            await control.save_interaction_mode(JsonRequest({"mode": mode}))
    await service.request("assistant", source="board_switch")

    apres = resolve_voice_composition(control._settings()).configuration_id
    assert apres == avant
    assert "voice.switch.requested" not in trace_kinds(control)
    assert not (tmp_path / REQUEST_FILE).exists()


def test_le_condense_de_composition_ignore_la_cle_du_mode_d_interaction():
    """Le mode n'entre pas dans l'identité qui décide du redémarrage (clé héritée d'un ancien fichier comprise)."""

    base: dict = {}
    reference = resolve_voice_composition(base).configuration_id
    for value in ("assistant", "presentation"):
        settings: dict = {"interaction_mode": {"schema_version": 1, "mode": value}}
        assert resolve_voice_composition(settings).configuration_id == reference


# ------------------------------------------------ Voice observe sans redémarrer


def test_l_observateur_part_du_mode_assistant_et_suit_les_evenements():
    observer = InteractionModeObserver()
    assert observer.mode is InteractionMode.ASSISTANT
    assert observer.revision == 0

    changed = observer.observe(ProtocolEnvelope(
        message_type=INTERACTION_MODE_CHANGED, payload=state("presentation", 1),
    ))

    assert changed is True
    assert observer.mode is InteractionMode.PRESENTATION
    assert observer.revision == 1
    assert observer.epoch == EPOCH


def test_l_observateur_ignore_un_evenement_plus_ancien_de_la_meme_vie_de_core():
    observer = InteractionModeObserver()
    observer.adopt(state("presentation", 5))

    assert observer.adopt(state("assistant", 4)) is False
    assert observer.adopt(state("presentation", 5)) is False
    assert observer.mode is InteractionMode.PRESENTATION

    assert observer.adopt(state("assistant", 6)) is True
    assert observer.mode is InteractionMode.ASSISTANT


def test_un_core_redemarre_est_cru_sans_condition_malgre_sa_revision_repartie_de_zero():
    """B1 : la panne muette que la garde monotone seule produisait.

    La révision appartient à une vie de Core et repart de 0 à son démarrage,
    alors que l'observateur vit dans le processus Voice et survit aux coupures
    du flux. Sans l'époque, l'utilisateur choisissait SIMPLE, Core l'appliquait,
    et Voice servait PRESENTATION — sans une ligne nulle part.
    """

    observer = InteractionModeObserver()
    for revision, mode in ((1, "presentation"), (2, "assistant"), (3, "presentation")):
        observer.adopt(state(mode, revision, epoch="vie-1"))
    assert (observer.mode, observer.revision) == (InteractionMode.PRESENTATION, 3)

    # Core redémarre : nouvelle vie, révisions qui repartent de 1.
    assert observer.adopt(state("presentation", 1, epoch="vie-2")) is False
    assert observer.revision == 1
    assert observer.epoch == "vie-2"
    # Et le choix suivant de l'utilisateur est servi tout de suite, au lieu
    # d'être écarté comme « plus vieux » pendant trois bascules.
    assert observer.adopt(state("assistant", 2, epoch="vie-2")) is True
    assert observer.mode is InteractionMode.ASSISTANT


def test_un_redemarrage_de_core_laisse_une_ligne_au_lieu_d_une_revision_qui_recule(tmp_path):
    journal = RuntimeJournal(tmp_path)
    observer = InteractionModeObserver(journal=journal)
    observer.adopt(state("presentation", 4, epoch="vie-1"))

    observer.adopt(state("assistant", 1, epoch="vie-2"))

    lignes = [item for item in read_jsonl_tail(journal.trace_path, limit=50)
              if item["data"].get("code") == "interaction_mode_core_restarted"]
    assert len(lignes) == 1
    assert lignes[0]["data"]["previous_revision"] == 4


def test_un_core_sans_epoque_est_cru_plutot_que_presume_perime():
    """Décalage de version : on penche vers la fraîcheur, jamais vers la panne."""

    observer = InteractionModeObserver()
    observer.adopt(state("presentation", 9, epoch="vie-1"))

    assert observer.adopt({"mode": "assistant", "revision": 1}) is True
    assert observer.mode is InteractionMode.ASSISTANT
    assert observer.epoch is None


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "presentation",
        {"mode": "presentation"},
        {"mode": "presentation", "revision": -1},
        {"mode": "presentation", "revision": True},
        {"mode": "presentation", "revision": "1"},
        {"mode": "fromage", "revision": 3},
        {"mode": "simple", "revision": 3},
    ],
)
def test_un_evenement_de_mode_abime_laisse_le_mode_tenu_en_place(payload):
    observer = InteractionModeObserver()
    observer.adopt(state("presentation", 2))

    assert observer.adopt(payload) is False
    assert observer.mode is InteractionMode.PRESENTATION
    assert observer.revision == 2


def test_une_revision_egale_qui_change_de_mode_est_ecartee_et_dite(tmp_path):
    """Trancher au hasard ferait diverger deux processus sans que personne ne le sache."""

    journal = RuntimeJournal(tmp_path)
    observer = InteractionModeObserver(journal=journal)
    observer.adopt(state("presentation", 3))

    assert observer.adopt(state("assistant", 3)) is False

    assert observer.mode is InteractionMode.PRESENTATION
    codes = [item["data"].get("code") for item in read_jsonl_tail(journal.trace_path, limit=50)]
    assert "interaction_mode_event_revision_conflict" in codes


def test_l_observateur_ne_joue_jamais_un_comportement_de_reunion_et_le_dit(tmp_path):
    journal = RuntimeJournal(tmp_path)
    observer = InteractionModeObserver(journal=journal)

    changed = observer.adopt(state("meeting", 1))

    assert changed is False
    assert observer.mode is InteractionMode.ASSISTANT
    # La révision avance quand même : cet état a bien été vu.
    assert observer.revision == 1
    # Le repli est le bon comportement ; le taire ne l'était pas.
    codes = [item["data"].get("code") for item in read_jsonl_tail(journal.trace_path, limit=50)]
    assert "interaction_mode_event_reserved_mode" in codes


def test_l_observateur_ignore_les_evenements_qui_ne_sont_pas_le_mode():
    observer = InteractionModeObserver()
    assert observer.observe(ProtocolEnvelope(message_type="brain.state.updated", payload={"revision": 9})) is False
    assert observer.revision == 0


# ------------------------------------------------ la vue et ses refus


@pytest.mark.asyncio
async def test_la_vue_refuse_une_reponse_hors_contrat_au_lieu_de_la_croire(tmp_path):
    class Menteur:
        def __init__(self, payload):
            self.payload = payload

        async def interaction_mode(self):
            return self.payload

        async def close(self):
            return None

    for payload in ([], {"mode": "fromage", "revision": 1}, {"mode": "presentation"},
                    {"mode": "presentation", "revision": -1}, {"mode": "meeting", "revision": 1}):
        view = CoreInteractionModeView(Menteur(payload))
        rendu = await view.read(InteractionMode.ASSISTANT)
        assert rendu["core_reachable"] is False
        assert rendu["error"]["code"] == "invalid_snapshot"


@pytest.mark.asyncio
async def test_sans_core_configure_la_vue_le_dit_au_lieu_d_inventer_une_revision():
    view = CoreInteractionModeView(None)

    rendu = await view.read(InteractionMode.PRESENTATION)

    assert rendu["core_reachable"] is False
    assert rendu["revision"] is None
    assert rendu["error"]["code"] == "not_configured"
    assert rendu["source"] == "local"


# ------------------------------------------------ diagnostics


#: Tous les champs qu'un émetteur `interaction.mode.*` a le droit d'écrire.
#: Des valeurs de mode, des codes stables, des révisions, des compteurs et des
#: noms de type — jamais une transcription, jamais un texte d'utilisateur. Une
#: valeur refusée est tronquée à 64 caractères par son émetteur, pour qu'un
#: champ de saisie ne puisse pas remplir le journal.
CHAMPS_DE_JOURNAL_AUTORISES = {
    "requested", "previous", "mode", "code", "revision", "source", "previous_mode",
    "previous_revision", "stored_schema_version", "schema_version", "suppressed",
    "retryable", "mode_held", "revision_held", "payload_type", "exception_type", "error",
    "changed", "disposition", "stored_value",
}


@pytest.mark.asyncio
async def test_aucune_trace_de_mode_ne_porte_de_contenu_utilisateur(tmp_path):
    """Les lignes des trois émetteurs, exercées puis inspectées une par une.

    La portée est explicite : ce test **produit** les lignes de la route
    (refus), du Board actif hors contrat, de la vue et de l'observateur, puis
    vérifie que chacune ne porte que des champs de la liste.
    """

    control, _service, view = build_control(tmp_path, board_kind="workshop")
    observer = InteractionModeObserver(journal=control.journal)

    # 1. la route : refusée, y compris pour une valeur démesurée.
    with pytest.raises(web.HTTPConflict):
        await control.save_interaction_mode(JsonRequest({"mode": "meeting"}))
    with pytest.raises(web.HTTPConflict):
        await control.save_interaction_mode(JsonRequest({"mode": "not a mode at all " * 20}))
    # 2. le Board actif hors contrat.
    await control.get_interaction_mode(None)
    # 3. la vue qui refuse une réponse hors contrat (journal branché, comme en production).
    journalisee = CoreInteractionModeView(view.reader, journal=control.journal)
    journalisee._report(ValueError("interaction mode response carries an unknown mode: 'fromage'"))
    # 4. l'observateur, sur un évènement abîmé et sur un mode réservé.
    observer.adopt({"mode": "x" * 500, "revision": 1})
    observer.adopt({"mode": "meeting", "revision": 1})

    lignes = [item for item in read_jsonl_tail(control.journal.trace_path, limit=500)
              if item["kind"].startswith("interaction.mode.")]
    kinds = {item["kind"] for item in lignes}
    assert {"interaction.mode.refused", "interaction.mode.board_unknown",
            "interaction.mode.view_invalid", "interaction.mode.ignored"} <= kinds
    for item in lignes:
        assert set(item["data"]) <= CHAMPS_DE_JOURNAL_AUTORISES, item
        for value in item["data"].values():
            assert len(str(value)) <= 200, item


@pytest.mark.asyncio
async def test_core_journalise_l_application_le_refus_et_la_repetition():
    diagnostics = RecordingDiagnostics()
    service = InteractionModeService(events=RecordingBus(), diagnostics=diagnostics)

    await service.request("presentation", source="board_switch")
    await service.request("presentation", source="board_switch")
    with pytest.raises(InteractionModeError):
        await service.request("meeting", source="board_switch")
    refus = service.refuse_external_request("presentation", source="control_center")

    assert diagnostics.kinds() == [
        "interaction.mode.applied", "interaction.mode.unchanged", "interaction.mode.refused",
        "interaction.mode.refused",
    ]
    assert refus.code == INTERACTION_MODE_DERIVED and str(refus) == INTERACTION_MODE_DERIVED_MESSAGE
    assert diagnostics.records[-1][2] == {"code": INTERACTION_MODE_DERIVED, "source": "control_center",
                                          "mode": "presentation"}
    # Le refus ne touche à rien.
    assert service.mode is InteractionMode.PRESENTATION and service.revision == 1


def test_le_service_core_n_a_plus_de_seconde_porte_tolerante():
    """Une seule porte stricte (`request`), plus aucune variante tolérante."""

    service = InteractionModeService(events=RecordingBus())
    assert not hasattr(service, "reconcile")


# ------------------------------------------------ le câblage côté Voice


class StubSession:
    """Le minimum de `RealtimeOutputControl` que l'ordonnanceur touche ici."""

    async def speak(self, *args, **kwargs):  # pragma: no cover - jamais appelé
        raise AssertionError("aucune parole dans ces tests")

    async def cancel_output(self, *args, **kwargs):  # pragma: no cover
        return None

    async def truncate(self, *args, **kwargs):  # pragma: no cover
        return None


class StubVoiceCore:
    """Ce que Voice voit de Core : un instantané de mode, et rien d'autre."""

    def __init__(self, snapshot: dict | None = None, *, failure: Exception | None = None) -> None:
        self.snapshot = snapshot
        self.failure = failure
        self.reads = 0

    async def interaction_mode(self) -> dict:
        self.reads += 1
        if self.failure is not None:
            raise self.failure
        return dict(self.snapshot or {})


def build_voice_scheduler(core, observer):
    from jarvis.runtime.speech_scheduler import SpeechScheduler

    return SpeechScheduler(
        core=core, conversation_id="conv-a", session=StubSession(),  # type: ignore[arg-type]
        reconnect_delay_s=0.0, interaction_mode=observer,
    )


@pytest.mark.asyncio
async def test_l_ordonnanceur_de_parole_remet_le_mode_a_l_observateur_du_processus():
    """Comportement, pas texte source : l'évènement entre, l'observateur change."""

    observer = InteractionModeObserver()
    scheduler = build_voice_scheduler(StubVoiceCore(), observer)

    await scheduler.handle_core_event(ProtocolEnvelope(
        message_type=INTERACTION_MODE_CHANGED, payload=state("presentation", 1),
    ))

    assert observer.mode is InteractionMode.PRESENTATION
    assert observer.revision == 1


@pytest.mark.asyncio
async def test_un_evenement_de_mode_ne_traverse_pas_le_filtre_des_evenements_cerveau():
    """Le mode n'appartient à aucune conversation : il ne doit pas être filtré comme tel."""

    observer = InteractionModeObserver()
    scheduler = build_voice_scheduler(StubVoiceCore(), observer)
    payload = {**state("presentation", 1), "conversation_id": "une-autre-conversation"}

    await scheduler.handle_core_event(ProtocolEnvelope(
        message_type=INTERACTION_MODE_CHANGED, payload=payload,
    ))

    assert observer.mode is InteractionMode.PRESENTATION


@pytest.mark.asyncio
async def test_un_abonnement_reussi_relit_le_mode_chez_core():
    """`CoreEventBus` ne rejoue rien : sans cette relecture, Voice reste au défaut."""

    observer = InteractionModeObserver()
    core = StubVoiceCore({**state("presentation", 7), "modes": []})
    scheduler = build_voice_scheduler(core, observer)
    scheduler._running = True

    scheduler._subscription_ready()
    for _ in range(50):
        if observer.mode is InteractionMode.PRESENTATION:
            break
        await asyncio.sleep(0)

    assert core.reads == 1
    assert observer.mode is InteractionMode.PRESENTATION
    assert observer.revision == 7
    await scheduler.stop()


@pytest.mark.asyncio
async def test_une_relecture_de_mode_qui_echoue_est_dite_et_n_arrete_pas_l_abonnement(tmp_path):
    journal = RuntimeJournal(tmp_path)
    observer = InteractionModeObserver()
    core = StubVoiceCore(failure=ConnectionError("Core down"))
    scheduler = build_voice_scheduler(core, observer)
    scheduler.journal = journal
    scheduler._running = True

    scheduler._subscription_ready()
    for _ in range(50):
        if any(item["kind"] == "interaction.mode.resync_failed"
               for item in read_jsonl_tail(journal.trace_path, limit=50)):
            break
        await asyncio.sleep(0)

    codes = [item["data"].get("code") for item in read_jsonl_tail(journal.trace_path, limit=50)]
    assert "interaction_mode_resync_failed" in codes
    assert observer.mode is InteractionMode.ASSISTANT
    await scheduler.stop()


# ------------------------------------------------ le transport et ses reprises


class RestartedCoreClient:
    """Core redémarré : le premier appel avec l'ancien jeton répond 401."""

    def __init__(self) -> None:
        self.calls = 0

    def _guard(self) -> None:
        self.calls += 1
        if self.calls == 1:
            raise CoreProtocolError(401, "unauthorized", "invalid local session credential")

    async def interaction_mode(self) -> dict:
        self._guard()
        return {**state("presentation", 2), "modes": []}

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_un_jeton_perime_est_relu_et_l_appel_rejoue_une_fois(tmp_path, monkeypatch):
    """Core écrit un jeton neuf à chaque démarrage ; la lecture n'y meurt pas."""

    from jarvis.runtime.interaction_mode_view import CoreInteractionModeTransport

    token_file = tmp_path / "token"
    token_file.write_text("vieux-jeton", encoding="utf-8")
    transport = CoreInteractionModeTransport(host="127.0.0.1", port=1, token_file=token_file)
    client = RestartedCoreClient()
    connexions: list[str] = []
    fermetures: list[int] = []

    def connect():
        connexions.append(token_file.read_text(encoding="utf-8").strip())
        return client

    async def close():
        fermetures.append(client.calls)

    monkeypatch.setattr(transport, "_connect", connect)
    monkeypatch.setattr(transport, "close", close)

    reponse = await transport.interaction_mode()

    assert reponse["mode"] == "presentation"
    # Deux connexions : le jeton est **relu** entre les deux, et la session
    # périmée est fermée au milieu plutôt que réutilisée.
    assert len(connexions) == 2
    assert fermetures == [1]


@pytest.mark.asyncio
async def test_un_refus_qui_n_est_pas_un_401_n_est_pas_rejoue(tmp_path, monkeypatch):
    from jarvis.runtime.interaction_mode_view import CoreInteractionModeTransport

    token_file = tmp_path / "token"
    token_file.write_text("jeton", encoding="utf-8")
    transport = CoreInteractionModeTransport(host="127.0.0.1", port=1, token_file=token_file)

    class Refusing:
        def __init__(self) -> None:
            self.calls = 0

        async def interaction_mode(self):
            self.calls += 1
            raise CoreProtocolError(403, "forbidden", "refusé")

    client = Refusing()
    monkeypatch.setattr(transport, "_connect", lambda: client)

    with pytest.raises(CoreProtocolError) as refus:
        await transport.interaction_mode()

    assert refus.value.status == 403
    assert client.calls == 1


# ------------------------------------------------ cohérences de charge utile


@pytest.mark.asyncio
async def test_le_repli_local_ne_presente_jamais_un_mode_reserve_comme_effectif(tmp_path):
    """La même loi des deux côtés : `_decode` refuse REUNION, le repli aussi.

    Le champ `mode` est celui qu'un consommateur lit comme « effectif ». Y
    laisser le `meeting` d'un Board Réunion y mettrait une valeur que la même
    vue refuse quand elle vient de Core. Le mode du type, lui, reste publié à part.
    """

    control, _service, _view = build_control(tmp_path, reader=UnreachableReader(), board_kind="meeting")

    block = json.loads((await control.status(None)).text)["interaction_mode"]

    assert block["core_reachable"] is False and block["source"] == "local"
    assert block["mode"] == "assistant"
    assert block["label"] == "SIMPLE"
    # …et REUNION reste visible là où il doit l'être (Décision 02).
    assert block["board_mode"] == "meeting"
    assert block["board_mode_label"] == "REUNION"


@pytest.mark.asyncio
async def test_core_injoignable_le_repli_est_le_comportement_du_type_du_board(tmp_path):
    control, _service, _view = build_control(tmp_path, reader=UnreachableReader(), board_kind="presentation")

    block = json.loads((await control.status(None)).text)["interaction_mode"]

    assert block["core_reachable"] is False and block["revision"] is None
    assert block["mode"] == "presentation" and block["error"]["code"] == "core_unreachable"


def test_l_evenement_ne_porte_pas_le_catalogue_des_modes():
    """Une seconde porte vers « ce qui existe » est une porte de trop."""

    async def run():
        bus = RecordingBus()
        service = InteractionModeService(events=bus)
        await service.request("presentation", source="test")
        return bus.published[0].payload

    payload = asyncio.run(run())
    assert "modes" not in payload
    assert set(payload) == {"mode", "label", "revision", "epoch", "source", "changed_at"}
    # L'instantané, lui, le porte : c'est lui la porte unique.
    assert "modes" in InteractionModeService(events=RecordingBus()).snapshot()


# ------------------------------------------------ ce que le journal compte


