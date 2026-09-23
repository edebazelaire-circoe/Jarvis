"""Plan de contrôle du mode d'interaction (Slice 02).

Ce que cette suite prouve, dans l'ordre où ça compte :

- la **persistance** survit au disque, et elle survit surtout aux *autres*
  réglages — notamment au basculement de compatibilité vocale, dont la branche
  d'application supprime `voice_architecture` (constat G1) ;
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
from jarvis.domain.interaction_mode import DEFAULT_INTERACTION_MODE, InteractionMode, InteractionModeError
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime import interaction_mode_settings as mode_settings
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.interaction_mode_observer import InteractionModeObserver
from jarvis.runtime.interaction_mode_view import CoreInteractionModeView, InteractionModeUnavailable
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
    """Transport factice : branche la vue du Control Center sur un vrai service Core."""

    def __init__(self, service: InteractionModeService) -> None:
        self.service = service
        self.reads = 0
        self.writes: list[tuple[str, str | None]] = []

    async def interaction_mode(self) -> dict:
        self.reads += 1
        return self.service.snapshot()

    async def set_interaction_mode(self, mode: str, *, source: str | None = None) -> dict:
        self.writes.append((mode, source))
        try:
            state, disposition = await self.service.request(mode, source=source or "protocol")
        except InteractionModeError as exc:
            status = 409 if exc.code == "interaction_mode_not_implemented" else 400
            raise CoreProtocolError(status, exc.code, str(exc)) from exc
        return {**self.service.snapshot(), "disposition": disposition.value, "revision": state.revision}

    async def close(self) -> None:
        return None


class UnreachableReader:
    async def interaction_mode(self) -> dict:
        raise ConnectionError("Core session token is unavailable")

    async def set_interaction_mode(self, mode: str, *, source: str | None = None) -> dict:
        raise ConnectionError("Core session token is unavailable")

    async def close(self) -> None:
        return None


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


async def drain_replay(control) -> None:
    """Attendre le rattrapage que `/api/status` a armé en tâche de fond."""

    task = control._interaction_mode_replay
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def build_control(tmp_path, *, reader=None):
    service = InteractionModeService(events=RecordingBus())
    view = CoreInteractionModeView(ServiceReader(service) if reader is None else reader)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, interaction_mode_view=view)
    return control, service, view


def trace_kinds(control) -> list[str]:
    return [item["kind"] for item in read_jsonl_tail(control.journal.trace_path, limit=500)]


# ------------------------------------------------ persistance (contrainte G3)


def test_le_mode_enregistre_survit_a_une_relecture_depuis_le_disque(tmp_path):
    """La preuve demandée par G3 : écrire, relire *le fichier*, retrouver le mode.

    Un test en mémoire ne prouverait rien ici : ce qui échoue silencieusement
    dans ce dépôt, c'est la persistance d'un contrôle absent d'une liste blanche.
    """

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    settings = control._settings()
    mode_settings.apply(settings, {"mode": "presentation"})
    control._write_settings(settings)

    on_disk = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert on_disk["interaction_mode"] == {"schema_version": 1, "mode": "presentation"}

    relu = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    assert mode_settings.load(relu._settings()) is InteractionMode.PRESENTATION


@pytest.mark.asyncio
async def test_la_route_dediee_ecrit_le_mode_sur_le_disque_et_l_applique_a_core(tmp_path):
    control, service, _view = build_control(tmp_path)

    response = await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))
    payload = json.loads(response.text)

    assert payload["mode"] == "presentation"
    assert payload["label"] == "PRESENTATION"
    assert payload["effective"]["mode"] == "presentation"
    assert payload["effective"]["source"] == "core"
    assert service.mode is InteractionMode.PRESENTATION
    on_disk = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert on_disk["interaction_mode"]["mode"] == "presentation"


def test_le_mode_n_est_pas_range_dans_une_cle_ou_une_architecture_vocale_pourrait_atterrir(tmp_path):
    """Le piège nominatif de la Slice 01, tenu au niveau de la persistance.

    `VoiceArchitectureId.SIMPLE.name` vaut `"SIMPLE"`, qui est aussi
    l'étiquette du mode assistant. Le mode a donc sa clé à lui, et la valeur
    d'architecture `simple` n'y produit pas un mode.
    """

    settings: dict = {}
    mode_settings.apply(settings, {"mode": "assistant"})
    assert set(settings) == {"interaction_mode"}
    assert "voice_arch" not in settings and "voice_architecture" not in settings

    with pytest.raises(mode_settings.InteractionModeSettingsError) as refus:
        mode_settings.apply({}, {"mode": "simple"})
    assert refus.value.code == "interaction_mode_unknown"
    with pytest.raises(mode_settings.InteractionModeSettingsError):
        mode_settings.apply({}, {"mode": "continuous_brain"})


# ------------------------------------------------ défauts et migration


@pytest.mark.parametrize(
    "stored",
    [
        None,
        {},
        {"interaction_mode": None},
        {"interaction_mode": "presentation"},
        {"interaction_mode": []},
        {"interaction_mode": {"schema_version": 1}},
        {"interaction_mode": {"schema_version": 1, "mode": ""}},
        {"interaction_mode": {"schema_version": 1, "mode": "simple"}},
        {"interaction_mode": {"schema_version": 1, "mode": "presentation\x00"}},
        {"interaction_mode": {"schema_version": 1, "mode": 7}},
        {"interaction_mode": {"schema_version": "trois", "mode": "presentation"}},
        {"interaction_mode": {"schema_version": 99, "mode": "presentation"}},
    ],
)
def test_un_reglage_absent_ou_corrompu_donne_le_mode_assistant_sans_lever(stored):
    """Décision 14 : tant que rien de lisible n'a été choisi, rien ne change."""

    settings = dict(stored or {})
    assert mode_settings.load(settings) is DEFAULT_INTERACTION_MODE
    assert mode_settings.behaving(settings) is DEFAULT_INTERACTION_MODE
    assert mode_settings.describe(settings)["mode"] == "assistant"


def test_une_preference_ecrite_par_une_version_plus_recente_est_dite_pas_devinee():
    """Le défaut « parce que neuf » et le défaut « parce qu'illisible » se distinguent."""

    neuf = mode_settings.describe({})
    assert neuf["unreadable"] is False and neuf["stored_schema_version"] is None

    etranger = mode_settings.describe({"interaction_mode": {"schema_version": 99, "mode": "presentation"}})
    assert etranger["unreadable"] is True
    assert etranger["stored_schema_version"] == 99
    # Non appliquée, mais pas perdue : la valeur brute reste lisible à l'écran.
    assert etranger["stored_value"] == "presentation"
    assert etranger["mode"] == "assistant"


def test_une_valeur_inconnue_dans_un_bloc_lisible_est_signalee_comme_telle():
    seen = mode_settings.inspect({"interaction_mode": {"schema_version": 1, "mode": "fromage"}})
    assert seen["unreadable"] is False
    assert seen["invalid_value"] is True
    assert seen["stored_value"] == "fromage"


def test_un_meeting_enregistre_reste_affichable_mais_ne_se_comporte_pas():
    """Les deux lectures de la Slice 01, du bon côté chacune (Décision 02)."""

    settings = {"interaction_mode": {"schema_version": 1, "mode": "meeting"}}
    assert mode_settings.load(settings) is InteractionMode.MEETING
    assert mode_settings.describe(settings)["label"] == "REUNION"
    assert mode_settings.behaving(settings) is InteractionMode.ASSISTANT


# ------------------------------------------------ refus de REUNION


def test_reunion_est_annonce_partout_et_activable_nulle_part():
    annonces = {entry["value"]: entry for entry in supported_modes()}
    assert set(annonces) == {"assistant", "presentation", "meeting"}
    assert annonces["meeting"]["label"] == "REUNION"
    assert annonces["meeting"]["implemented"] is False
    assert annonces["meeting"]["status"] == "planned"
    assert annonces["presentation"]["implemented"] is True


def test_l_ecriture_du_mode_reunion_est_refusee_avec_le_code_stable():
    with pytest.raises(mode_settings.InteractionModeSettingsError) as refus:
        mode_settings.apply({}, {"mode": "meeting"})
    assert refus.value.code == "interaction_mode_not_implemented"
    assert "REUNION" in str(refus.value)


@pytest.mark.asyncio
async def test_core_refuse_le_mode_reunion_sans_toucher_a_la_valeur_effective():
    service = InteractionModeService(events=RecordingBus(), diagnostics=RecordingDiagnostics())
    with pytest.raises(InteractionModeError) as refus:
        await service.request("meeting", source="test")
    assert refus.value.code == "interaction_mode_not_implemented"
    assert service.mode is InteractionMode.ASSISTANT
    assert service.revision == 0


@pytest.mark.asyncio
async def test_la_route_du_control_center_refuse_reunion_en_409_avec_son_code(tmp_path):
    control, service, _view = build_control(tmp_path)

    with pytest.raises(web.HTTPConflict) as refus:
        await control.save_interaction_mode(JsonRequest({"mode": "meeting"}))
    assert refus.value.headers["X-Jarvis-Error-Code"] == "interaction_mode_not_implemented"
    assert service.mode is InteractionMode.ASSISTANT
    # Rien n'est enregistré : un refus ne doit pas laisser une préférence
    # que la réconciliation du démarrage rejouerait.
    assert not (tmp_path / "control-center-settings.json").exists()
    assert "interaction.mode.refused" in trace_kinds(control)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload, code",
    [
        (None, "interaction_mode_bad_payload"),
        ("presentation", "interaction_mode_bad_payload"),
        ({}, "interaction_mode_missing"),
        ({"mode": "fromage"}, "interaction_mode_unknown"),
        ({"mode": "SIMPLE"}, "interaction_mode_unknown"),
        ({"mode": "presentation", "schema_version": 4}, "interaction_mode_schema_version_unsupported"),
        ({"mode": "presentation", "enabled": True}, "interaction_mode_unknown_field"),
    ],
)
async def test_chaque_refus_d_ecriture_porte_son_code_stable_en_en_tete(tmp_path, payload, code):
    control, _service, _view = build_control(tmp_path)

    with pytest.raises(web.HTTPBadRequest) as refus:
        await control.save_interaction_mode(JsonRequest(payload))
    assert refus.value.headers["X-Jarvis-Error-Code"] == code


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


@pytest.mark.asyncio
async def test_la_reconciliation_rejoue_la_preference_enregistree_vers_core(tmp_path):
    control, service, _view = build_control(tmp_path)
    settings = control._settings()
    mode_settings.apply(settings, {"mode": "presentation"})
    control._write_settings(settings)

    live = await control._reconcile_interaction_mode(control._settings(), source="startup")

    assert service.mode is InteractionMode.PRESENTATION
    assert live["revision"] == 1
    assert live["core_reachable"] is True
    assert "interaction.mode.reconciled" in trace_kinds(control)


@pytest.mark.asyncio
async def test_la_reconciliation_ne_demande_jamais_un_mode_reserve(tmp_path):
    """Un `meeting` enregistré reste affiché, mais n'est jamais demandé à Core."""

    control, service, view = build_control(tmp_path)
    settings = control._settings()
    settings["interaction_mode"] = {"schema_version": 1, "mode": "meeting"}
    control._write_settings(settings)

    await control._reconcile_interaction_mode(control._settings(), source="startup")

    assert view.reader.writes == [("assistant", "startup")]
    assert service.mode is InteractionMode.ASSISTANT


@pytest.mark.asyncio
async def test_un_core_injoignable_ne_bloque_pas_le_demarrage_et_laisse_une_ligne(tmp_path):
    control, _service, _view = build_control(tmp_path, reader=UnreachableReader())
    settings = control._settings()
    mode_settings.apply(settings, {"mode": "presentation"})
    control._write_settings(settings)

    live = await control._reconcile_interaction_mode(control._settings(), source="startup")

    assert live["core_reachable"] is False
    assert live["error"]["code"] == "core_unreachable"
    # Le repli est **nommé** : personne ne doit prendre le réglage local pour
    # la vérité vivante de Core.
    assert live["source"] == "settings"
    assert live["mode"] == "presentation"
    assert "interaction.mode.reconcile_failed" in trace_kinds(control)


@pytest.mark.asyncio
async def test_un_core_demarre_apres_nous_est_rattrape_hors_du_chemin_de_lecture(tmp_path):
    """Révision 0 côté Core = il n'a jamais entendu parler de la préférence.

    Le rattrapage est **armé** par le sondage et **exécuté à côté** : le pouls
    de la page ne contient pas d'écriture réseau, et il rend ce que Core dit
    aujourd'hui plutôt que d'attendre un aller-retour de plus.
    """

    control, service, view = build_control(tmp_path)
    settings = control._settings()
    mode_settings.apply(settings, {"mode": "presentation"})
    control._write_settings(settings)
    assert service.revision == 0

    block = await control._interaction_mode_status(control._settings())

    # Ce battement-ci n'a rien écrit : il rend l'état d'avant le rattrapage.
    assert block["revision"] == 0
    assert view.reader.writes == []
    assert control._interaction_mode_replay is not None
    # La tâche de fond, elle, applique.
    for _ in range(50):
        if service.mode is InteractionMode.PRESENTATION:
            break
        await asyncio.sleep(0)
    assert service.mode is InteractionMode.PRESENTATION
    assert view.reader.writes == [("presentation", "core_restart")]
    await drain_replay(control)
    # Le sondage suivant voit une révision non nulle et n'arme plus rien.
    suivant = await control._interaction_mode_status(control._settings())
    assert suivant["revision"] == 1
    assert len(view.reader.writes) == 1


@pytest.mark.asyncio
async def test_un_core_qui_refuse_pour_toujours_n_ecrit_pas_une_ligne_par_seconde(tmp_path):
    """La page bat chaque seconde : un avertissement par battement est une panne."""

    control, _service, _view = build_control(tmp_path, reader=UnreachableReader())
    settings = control._settings()
    mode_settings.apply(settings, {"mode": "presentation"})
    control._write_settings(settings)

    for _ in range(5):
        await control._reconcile_interaction_mode(control._settings(), source="core_restart")

    lignes = [kind for kind in trace_kinds(control) if kind == "interaction.mode.reconcile_failed"]
    assert lignes == ["interaction.mode.reconcile_failed"]


@pytest.mark.asyncio
async def test_le_statut_n_arme_qu_un_seul_rattrapage_a_la_fois(tmp_path):
    control, _service, view = build_control(tmp_path)
    settings = control._settings()
    mode_settings.apply(settings, {"mode": "presentation"})
    control._write_settings(settings)

    for _ in range(4):
        await control._interaction_mode_status(control._settings())

    for _ in range(50):
        if view.reader.writes:
            break
        await asyncio.sleep(0)
    assert view.reader.writes == [("presentation", "core_restart")]
    await drain_replay(control)


@pytest.mark.asyncio
async def test_le_mode_enregistre_par_defaut_ne_declenche_aucune_reconciliation(tmp_path):
    control, _service, view = build_control(tmp_path)

    await control._interaction_mode_status(control._settings())

    assert view.reader.writes == []


@pytest.mark.asyncio
async def test_une_demande_que_core_n_a_pas_prise_echoue_en_503_en_le_disant(tmp_path):
    control, _service, _view = build_control(tmp_path, reader=UnreachableReader())

    with pytest.raises(web.HTTPServiceUnavailable) as echec:
        await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))

    assert echec.value.headers["X-Jarvis-Error-Code"] == "core_unreachable"
    assert "enregistré" in echec.value.text
    # La préférence est bien écrite : le choix de l'utilisateur survit et sera
    # rejoué, mais la réponse ne fait pas croire qu'il est appliqué.
    on_disk = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert on_disk["interaction_mode"]["mode"] == "presentation"
    assert "interaction.mode.not_applied" in trace_kinds(control)


# ------------------------------------------------ /api/status


@pytest.mark.asyncio
async def test_le_statut_expose_le_mode_effectif_la_preference_et_les_modes_annonces(tmp_path):
    control, service, _view = build_control(tmp_path)
    await service.request("presentation", source="test")

    response = await control.status(None)
    block = json.loads(response.text)["interaction_mode"]

    assert block["mode"] == "presentation"
    assert block["label"] == "PRESENTATION"
    assert block["revision"] == 1
    assert block["source"] == "core"
    assert block["core_reachable"] is True
    # La préférence est nommée à part : ici elle n'a pas encore été écrite.
    assert block["stored"] == "assistant"
    assert [entry["value"] for entry in block["modes"]] == ["assistant", "presentation", "meeting"]
    assert [entry["implemented"] for entry in block["modes"]] == [True, True, False]


@pytest.mark.asyncio
async def test_le_statut_garde_reunion_visible_quand_il_est_le_mode_enregistre(tmp_path):
    """Décision 02 : l'écran continue de montrer ce que l'utilisateur a choisi."""

    control, _service, _view = build_control(tmp_path)
    settings = control._settings()
    settings["interaction_mode"] = {"schema_version": 1, "mode": "meeting"}
    control._write_settings(settings)

    block = json.loads((await control.status(None)).text)["interaction_mode"]

    assert block["stored"] == "meeting"
    assert block["stored_label"] == "REUNION"
    # Mais rien ne se comporte en réunion.
    assert block["mode"] == "assistant"


@pytest.mark.asyncio
async def test_le_statut_ne_tombe_pas_quand_core_est_injoignable(tmp_path):
    control, _service, _view = build_control(tmp_path, reader=UnreachableReader())

    block = json.loads((await control.status(None)).text)["interaction_mode"]

    assert block["core_reachable"] is False
    assert block["error"]["code"] == "core_unreachable"
    assert block["mode"] == "assistant"


@pytest.mark.asyncio
async def test_les_reglages_publient_la_preference_et_sa_version_de_schema(tmp_path):
    control, _service, _view = build_control(tmp_path)
    settings = control._settings()
    mode_settings.apply(settings, {"mode": "presentation"})
    control._write_settings(settings)

    payload = json.loads((await control.get_settings(None)).text)["interaction_mode"]

    assert payload["mode"] == "presentation"
    assert payload["schema_version"] == mode_settings.SCHEMA_VERSION
    assert [entry["value"] for entry in payload["modes"]] == ["assistant", "presentation", "meeting"]


@pytest.mark.asyncio
async def test_la_route_dediee_rend_la_preference_et_la_valeur_effective(tmp_path):
    control, service, _view = build_control(tmp_path)
    await service.request("presentation", source="test")

    payload = json.loads((await control.get_interaction_mode(None)).text)

    assert payload["mode"] == "assistant"          # préférence : rien d'enregistré
    assert payload["effective"]["mode"] == "presentation"  # vérité vivante de Core
    assert payload["effective"]["revision"] == 1


@pytest.mark.asyncio
async def test_une_preference_de_version_inconnue_laisse_une_ligne_une_seule_fois(tmp_path):
    control, _service, _view = build_control(tmp_path)
    settings = control._settings()
    settings["interaction_mode"] = {"schema_version": 99, "mode": "presentation"}
    control._write_settings(settings)

    await control.get_interaction_mode(None)
    await control.get_interaction_mode(None)

    lignes = [kind for kind in trace_kinds(control) if kind == "interaction.mode.foreign_version"]
    assert lignes == ["interaction.mode.foreign_version"]


# ------------------------------------------------ G1 : l'axe reste à part


@pytest.mark.asyncio
async def test_le_mode_survit_a_un_basculement_de_compatibilite_vocale(tmp_path):
    """Contrainte G1, prouvée sur la branche qui supprime `voice_architecture`.

    `_apply_voice` est une alternative à trois branches mutuellement
    exclusives ; sa première branche efface `voice_architecture`. Le mode
    d'interaction ne passe pas par là, et cette écriture-ci le vérifie sur le
    fichier, pas sur l'objet en mémoire.
    """

    control, _service, _view = build_control(tmp_path)
    await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))

    await control.save_settings(JsonRequest({"voice": {"brain_compatibility": True}}))

    on_disk = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert on_disk["voice_arch"] == "continuous_brain"
    assert "voice_architecture" not in on_disk
    assert on_disk["interaction_mode"] == {"schema_version": 1, "mode": "presentation"}
    assert mode_settings.load(control._settings()) is InteractionMode.PRESENTATION


@pytest.mark.asyncio
async def test_enregistrer_le_mode_ne_touche_a_aucun_des_deux_axes_d_architecture(tmp_path):
    control, _service, _view = build_control(tmp_path)
    settings = control._settings()
    settings["voice_arch"] = "continuous_brain"
    control._write_settings(settings)

    await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))

    on_disk = json.loads((tmp_path / "control-center-settings.json").read_text(encoding="utf-8"))
    assert on_disk["voice_arch"] == "continuous_brain"
    assert on_disk["interaction_mode"]["mode"] == "presentation"


def test_le_mode_n_est_pas_un_reglage_vocal_persistable():
    """Il n'entre pas dans la liste blanche de la voix : il a sa route à lui (G3)."""

    from jarvis.runtime.voice_settings_schema import PERSISTABLE_OPTION_IDS

    assert "interaction_mode" not in PERSISTABLE_OPTION_IDS
    assert mode_settings.SETTING_KEY not in PERSISTABLE_OPTION_IDS


# ------------------------------------------------ D15 : aucun redémarrage


@pytest.mark.asyncio
async def test_changer_de_mode_ne_demande_aucun_redemarrage_de_voice(tmp_path):
    """Décision D15, la contrainte qui protège une présentation en cours.

    Trois preuves indépendantes, parce qu'une seule se contournerait :
    le `configuration_id` est identique, aucune ligne `voice.switch.requested`
    n'est écrite, et aucun fichier de bascule n'apparaît.
    """

    control, _service, _view = build_control(tmp_path)
    # Ce premier couple est un garde-fou, pas la preuve : il recalcule le
    # condensé depuis les réglages, donc il tiendrait même si un redémarrage
    # avait été demandé. Ce sont les deux assertions suivantes — le journal et
    # le fichier de bascule — qui portent D15, et
    # `test_le_condense_de_composition_ignore_la_cle_du_mode_d_interaction`
    # qui prouve que la clé n'entre pas dans l'identité.
    avant = resolve_voice_composition(control._settings()).configuration_id

    await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))
    await control.save_interaction_mode(JsonRequest({"mode": "assistant"}))
    await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))

    apres = resolve_voice_composition(control._settings()).configuration_id
    assert apres == avant
    assert "voice.switch.requested" not in trace_kinds(control)
    assert not (tmp_path / REQUEST_FILE).exists()


def test_le_condense_de_composition_ignore_la_cle_du_mode_d_interaction():
    """Le mode n'entre pas dans l'identité qui décide du redémarrage."""

    base: dict = {}
    reference = resolve_voice_composition(base).configuration_id
    for value in ("assistant", "presentation"):
        settings: dict = {}
        mode_settings.apply(settings, {"mode": value})
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

        async def set_interaction_mode(self, mode, *, source=None):
            return self.payload

        async def close(self):
            return None

    for payload in ([], {"mode": "fromage", "revision": 1}, {"mode": "presentation"},
                    {"mode": "presentation", "revision": -1}, {"mode": "meeting", "revision": 1}):
        view = CoreInteractionModeView(Menteur(payload))
        rendu = await view.read(InteractionMode.ASSISTANT)
        assert rendu["core_reachable"] is False
        assert rendu["error"]["code"] == "invalid_snapshot"
        with pytest.raises(InteractionModeUnavailable) as echec:
            await view.request(InteractionMode.PRESENTATION, source="test")
        assert echec.value.code == "invalid_snapshot"


@pytest.mark.asyncio
async def test_un_refus_metier_de_core_remonte_avec_son_code_intact(tmp_path):
    service = InteractionModeService(events=RecordingBus())
    view = CoreInteractionModeView(ServiceReader(service))

    with pytest.raises(InteractionModeUnavailable) as echec:
        await view.request(InteractionMode.MEETING, source="test")

    assert echec.value.code == "interaction_mode_not_implemented"


@pytest.mark.asyncio
async def test_sans_core_configure_la_vue_le_dit_au_lieu_d_inventer_une_revision():
    view = CoreInteractionModeView(None)

    rendu = await view.read(InteractionMode.PRESENTATION)

    assert rendu["core_reachable"] is False
    assert rendu["revision"] is None
    assert rendu["error"]["code"] == "not_configured"
    with pytest.raises(InteractionModeUnavailable) as echec:
        await view.request(InteractionMode.PRESENTATION, source="test")
    assert echec.value.code == "not_configured"


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
}


@pytest.mark.asyncio
async def test_aucune_trace_de_mode_ne_porte_de_contenu_utilisateur(tmp_path):
    """Les lignes des quatre émetteurs, exercées puis inspectées une par une.

    La portée est explicite : ce test **produit** les lignes des routes, du
    rattrapage, de la vue et de l'observateur, puis vérifie que chacune ne
    porte que des champs de la liste. Une version antérieure n'observait que
    les deux appels de route, ce qui laissait `interaction.mode.view_invalid`
    et `.ignored` hors de portée alors que le commentaire affirmait le
    contraire.
    """

    control, _service, view = build_control(tmp_path)
    observer = InteractionModeObserver(journal=control.journal)

    # 1. les routes : demandé, appliqué, refusé.
    await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))
    with pytest.raises(web.HTTPConflict):
        await control.save_interaction_mode(JsonRequest({"mode": "meeting"}))
    with pytest.raises(web.HTTPBadRequest):
        await control.save_interaction_mode(JsonRequest({"mode": "not a mode at all " * 20}))
    # 2. la préférence illisible, et la version étrangère.
    settings = control._settings()
    settings["interaction_mode"] = {"schema_version": 99, "mode": "presentation"}
    control._write_settings(settings)
    control.report_interaction_mode_preference(control._settings(), source="startup")
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
    assert {"interaction.mode.requested", "interaction.mode.applied", "interaction.mode.refused",
            "interaction.mode.defaulted", "interaction.mode.foreign_version",
            "interaction.mode.view_invalid", "interaction.mode.ignored"} <= kinds
    for item in lignes:
        assert set(item["data"]) <= CHAMPS_DE_JOURNAL_AUTORISES, item
        for value in item["data"].values():
            assert len(str(value)) <= 200, item


@pytest.mark.asyncio
async def test_core_journalise_l_application_le_refus_et_la_repetition():
    diagnostics = RecordingDiagnostics()
    service = InteractionModeService(events=RecordingBus(), diagnostics=diagnostics)

    await service.request("presentation", source="control_center")
    await service.request("presentation", source="control_center")
    with pytest.raises(InteractionModeError):
        await service.request("meeting", source="control_center")

    assert diagnostics.kinds() == [
        "interaction.mode.applied", "interaction.mode.unchanged", "interaction.mode.refused",
    ]


@pytest.mark.parametrize(
    "stored, code",
    [
        ({"schema_version": 1, "mode": "fromage"}, "interaction_mode_unreadable"),
        ({"schema_version": 1, "mode": 7}, "interaction_mode_unreadable"),
        ({"schema_version": 99, "mode": "presentation"}, "interaction_mode_unreadable"),
        ({"schema_version": 1, "mode": "meeting"}, "interaction_mode_not_implemented"),
    ],
)
def test_un_reglage_qui_n_est_pas_celui_qui_s_applique_est_nomme(tmp_path, stored, code):
    """C'est le propriétaire de la persistance qui dit la perte, parce que lui seul la voit.

    Core ne reçoit jamais la valeur brute du disque : le Control Center la lit
    et la normalise avant de la demander. Sans cette ligne-ci, « démarré en
    SIMPLE » et « son réglage était illisible » laissent la même trace.
    """

    control, _service, _view = build_control(tmp_path)
    settings = control._settings()
    settings["interaction_mode"] = stored
    control._write_settings(settings)

    control.report_interaction_mode_preference(control._settings(), source="startup")

    lignes = [item for item in read_jsonl_tail(control.journal.trace_path, limit=200)
              if item["kind"] == "interaction.mode.defaulted"]
    assert [item["data"]["code"] for item in lignes] == [code]


def test_un_reglage_sain_ne_produit_aucune_ligne_de_repli(tmp_path):
    control, _service, _view = build_control(tmp_path)
    settings = control._settings()
    mode_settings.apply(settings, {"mode": "presentation"})
    control._write_settings(settings)

    control.report_interaction_mode_preference(control._settings(), source="startup")

    assert "interaction.mode.defaulted" not in trace_kinds(control)


def test_le_service_core_n_a_plus_de_seconde_porte_tolerante():
    """La tolérance appartient au propriétaire de la persistance, et à lui seul."""

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

    async def set_interaction_mode(self, mode: str, *, source: str | None = None) -> dict:
        self._guard()
        return {**state(mode, 3), "modes": [], "disposition": "applied"}

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("verbe", ["interaction_mode", "set_interaction_mode"])
async def test_un_jeton_perime_est_relu_et_l_appel_rejoue_une_fois(tmp_path, monkeypatch, verbe):
    """Core écrit un jeton neuf à chaque démarrage ; ni la lecture ni la demande n'y meurent.

    Le rejeu est sûr : un 401 est rendu avant que Core ne lise le corps, donc
    rien n'a été appliqué — et redemander le même mode est de toute façon
    idempotent.
    """

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

    appel = getattr(transport, verbe)
    reponse = await (appel() if verbe == "interaction_mode" else appel("presentation", source="test"))

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

        async def set_interaction_mode(self, mode, *, source=None):
            self.calls += 1
            raise CoreProtocolError(409, "interaction_mode_not_implemented", "réservé")

    client = Refusing()
    monkeypatch.setattr(transport, "_connect", lambda: client)

    with pytest.raises(CoreProtocolError) as refus:
        await transport.set_interaction_mode("meeting", source="test")

    assert refus.value.status == 409
    assert client.calls == 1


# ------------------------------------------------ cohérences de charge utile


@pytest.mark.asyncio
async def test_le_repli_local_ne_presente_jamais_un_mode_reserve_comme_effectif(tmp_path):
    """La même loi des deux côtés : `_decode` refuse REUNION, le repli aussi.

    Le champ `mode` est celui qu'un consommateur lit comme « effectif ». Y
    laisser le `meeting` enregistré y mettrait une valeur que la même vue
    refuse quand elle vient de Core. La préférence, elle, reste publiée à part.
    """

    control, _service, _view = build_control(tmp_path, reader=UnreachableReader())
    settings = control._settings()
    settings["interaction_mode"] = {"schema_version": 1, "mode": "meeting"}
    control._write_settings(settings)

    block = json.loads((await control.status(None)).text)["interaction_mode"]

    assert block["core_reachable"] is False
    assert block["mode"] == "assistant"
    assert block["label"] == "SIMPLE"
    # …et REUNION reste visible là où il doit l'être (Décision 02).
    assert block["stored"] == "meeting"
    assert block["stored_label"] == "REUNION"


@pytest.mark.asyncio
async def test_la_reponse_d_une_demande_porte_le_couple_mode_revision_de_cet_appel(tmp_path):
    """Une révision ordonne des observations : le couple rendu doit avoir existé."""

    service = InteractionModeService(events=RecordingBus())
    view = CoreInteractionModeView(ServiceReader(service))
    reponse = await view.request(InteractionMode.PRESENTATION, source="test")

    assert (reponse["mode"], reponse["revision"]) == ("presentation", 1)
    assert reponse["epoch"] == service.epoch


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


@pytest.mark.asyncio
async def test_un_refus_de_core_ne_promet_pas_une_reprise_qui_n_aura_pas_lieu(tmp_path):
    """Une panne de transport se rattrape ; un refus, jamais."""

    class RefusingReader:
        async def interaction_mode(self):
            raise CoreProtocolError(400, "interaction_mode_unknown", "mode inconnu de ce Core")

        async def set_interaction_mode(self, mode, *, source=None):
            raise CoreProtocolError(400, "interaction_mode_unknown", "mode inconnu de ce Core")

        async def close(self):
            return None

    control, _service, _view = build_control(tmp_path, reader=RefusingReader())

    with pytest.raises(web.HTTPServiceUnavailable) as echec:
        await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))

    assert echec.value.headers["X-Jarvis-Error-Code"] == "interaction_mode_unknown"
    assert "ne sera pas réessayée" in echec.value.text
    # Et aucun rattrapage n'est armé pour une demande que Core vient de refuser.
    assert control._interaction_mode_replay is None
    lignes = [item for item in read_jsonl_tail(control.journal.trace_path, limit=200)
              if item["kind"] == "interaction.mode.not_applied"]
    assert lignes[0]["data"]["retryable"] is False


@pytest.mark.asyncio
async def test_une_panne_de_transport_promet_et_arme_la_reprise(tmp_path):
    control, _service, _view = build_control(tmp_path, reader=UnreachableReader())

    with pytest.raises(web.HTTPServiceUnavailable) as echec:
        await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))

    assert "Il sera repris" in echec.value.text
    assert control._interaction_mode_replay is not None
    lignes = [item for item in read_jsonl_tail(control.journal.trace_path, limit=200)
              if item["kind"] == "interaction.mode.not_applied"]
    assert lignes[0]["data"]["retryable"] is True
    await drain_replay(control)
