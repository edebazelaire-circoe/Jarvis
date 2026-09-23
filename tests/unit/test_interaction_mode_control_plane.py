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
from jarvis.runtime.journal import read_jsonl_tail
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
    """Deux clics simultanés : une seule bascule, une seule révision, un seul évènement."""

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
async def test_un_core_demarre_apres_nous_est_rattrape_par_le_sondage_du_statut(tmp_path):
    """Révision 0 côté Core = il n'a jamais entendu parler de la préférence."""

    control, service, view = build_control(tmp_path)
    settings = control._settings()
    mode_settings.apply(settings, {"mode": "presentation"})
    control._write_settings(settings)
    assert service.revision == 0

    block = await control._interaction_mode_status(control._settings())

    assert service.mode is InteractionMode.PRESENTATION
    assert block["mode"] == "presentation"
    assert block["revision"] == 1
    # Et la condition s'éteint : le sondage suivant ne redemande rien.
    ecritures = len(view.reader.writes)
    await control._interaction_mode_status(control._settings())
    assert len(view.reader.writes) == ecritures


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
        message_type=INTERACTION_MODE_CHANGED,
        payload={"mode": "presentation", "revision": 1},
    ))

    assert changed is True
    assert observer.mode is InteractionMode.PRESENTATION
    assert observer.revision == 1


def test_l_observateur_ignore_un_evenement_plus_ancien_que_ce_qu_il_tient():
    observer = InteractionModeObserver()
    observer.adopt({"mode": "presentation", "revision": 5})

    assert observer.adopt({"mode": "assistant", "revision": 4}) is False
    assert observer.adopt({"mode": "assistant", "revision": 5}) is False
    assert observer.mode is InteractionMode.PRESENTATION

    assert observer.adopt({"mode": "assistant", "revision": 6}) is True
    assert observer.mode is InteractionMode.ASSISTANT


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
    observer.adopt({"mode": "presentation", "revision": 2})

    assert observer.adopt(payload) is False
    assert observer.mode is InteractionMode.PRESENTATION
    assert observer.revision == 2


def test_l_observateur_ne_joue_jamais_un_comportement_de_reunion():
    observer = InteractionModeObserver()

    changed = observer.adopt({"mode": "meeting", "revision": 1})

    assert changed is False
    assert observer.mode is InteractionMode.ASSISTANT
    # La révision avance quand même : cet état a bien été vu.
    assert observer.revision == 1


def test_l_observateur_ignore_les_evenements_qui_ne_sont_pas_le_mode():
    observer = InteractionModeObserver()
    assert observer.observe(ProtocolEnvelope(message_type="brain.state.updated", payload={"revision": 9})) is False
    assert observer.revision == 0


def test_l_ordonnanceur_de_parole_route_le_mode_vers_l_observateur_du_processus():
    """Le seul abonné `/v1/events` de Voice relaie le mode, sans rien en décider."""

    import inspect

    from jarvis.runtime import speech_scheduler

    source = inspect.getsource(speech_scheduler.SpeechScheduler.handle_core_event)
    assert "INTERACTION_MODE_CHANGED" in source
    assert "self.interaction_mode.observe(envelope)" in source
    signature = inspect.signature(speech_scheduler.SpeechScheduler.__init__)
    assert "interaction_mode" in signature.parameters


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


@pytest.mark.asyncio
async def test_le_journal_dit_la_demande_l_application_et_le_refus_sans_contenu_utilisateur(tmp_path):
    control, _service, _view = build_control(tmp_path)

    await control.save_interaction_mode(JsonRequest({"mode": "presentation"}))
    with pytest.raises(web.HTTPConflict):
        await control.save_interaction_mode(JsonRequest({"mode": "meeting"}))

    lignes = [item for item in read_jsonl_tail(control.journal.trace_path, limit=500)
              if item["kind"].startswith("interaction.mode.")]
    kinds = [item["kind"] for item in lignes]
    assert "interaction.mode.requested" in kinds
    assert "interaction.mode.applied" in kinds
    assert "interaction.mode.refused" in kinds
    # Aucune trace ne porte de transcription ni de texte libre : seules des
    # valeurs de mode, des codes et des révisions.
    autorise = {"requested", "previous", "mode", "code", "revision", "source",
                "previous_mode", "stored_schema_version", "schema_version"}
    for item in lignes:
        assert set(item["data"]) <= autorise, item


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


@pytest.mark.asyncio
async def test_la_reconciliation_dit_quand_elle_replie_sur_le_defaut():
    diagnostics = RecordingDiagnostics()
    service = InteractionModeService(events=RecordingBus(), diagnostics=diagnostics)

    await service.reconcile("fromage")

    assert "interaction.mode.refused" in diagnostics.kinds()
    assert service.mode is InteractionMode.ASSISTANT
    # Un repli sur le défaut ne doit pas ressembler à un démarrage ordinaire.
    refus = [data for kind, _level, data in diagnostics.records if kind == "interaction.mode.refused"]
    assert refus[0]["code"] == "interaction_mode_unreadable"


@pytest.mark.asyncio
async def test_la_reconciliation_d_un_meeting_enregistre_dit_pourquoi_elle_ne_l_applique_pas():
    diagnostics = RecordingDiagnostics()
    service = InteractionModeService(events=RecordingBus(), diagnostics=diagnostics)

    await service.reconcile("meeting")

    refus = [data for kind, _level, data in diagnostics.records if kind == "interaction.mode.refused"]
    assert refus[0]["code"] == "interaction_mode_not_implemented"
    assert service.mode is InteractionMode.ASSISTANT


@pytest.mark.asyncio
async def test_la_reconciliation_ne_leve_jamais_quoi_qu_elle_lise():
    service = InteractionModeService(events=RecordingBus())
    for value in (None, "", "fromage", 3, b"presentation", object(), "meeting"):
        state, _disposition = await service.reconcile(value)
        assert state.mode is InteractionMode.ASSISTANT
    state, disposition = await service.reconcile("presentation")
    assert state.mode is InteractionMode.PRESENTATION
