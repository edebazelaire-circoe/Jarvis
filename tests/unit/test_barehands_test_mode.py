"""Barehands en mode test : réglage persistant et assets servis à la page.

Le serveur ne suit aucune main : il garde l'interrupteur (éteint par défaut,
rangé dans le fichier de réglages commun, refusé en HTTP 400 avec un code
stable s'il est mal formé) et ne sert à la page que la liste blanche des
fichiers MediaPipe vendorisés.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from aiohttp import web
import pytest

from jarvis.runtime import barehands_test_mode as barehands
from jarvis.runtime.control_center import BAREHANDS_SCRIPT_MARKER, SETTINGS_ERROR_CODE_HEADER, ControlCenter
from jarvis.runtime.journal import read_jsonl_tail


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class AssetRequest:
    def __init__(self, asset: str) -> None:
        self.match_info = {"asset": asset}


def install_assets(root: Path, names=barehands.REQUIRED_ASSETS) -> None:
    for name in names:
        relative, _ = barehands.ASSETS[name]
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"asset:" + name.encode())


@pytest.fixture
def vendor(tmp_path) -> Path:
    return tmp_path / "vendor"


@pytest.fixture
def control(tmp_path, vendor, monkeypatch):
    monkeypatch.delenv(barehands.VENDOR_ENV, raising=False)
    runtime = tmp_path / "runtime"
    return ControlCenter(runtime_root=runtime, project_root=tmp_path, barehands_vendor_root=vendor)


async def state_of(control: ControlCenter) -> dict:
    return json.loads((await control.get_barehands(None)).text)


# ------------------------------------------------------------------ réglage


def test_the_setting_is_off_by_default_and_any_doubtful_value_reads_as_off():
    assert barehands.load({}) == barehands.SETTINGS_DEFAULTS
    assert barehands.load({"barehands_test_mode": {"enabled": "true"}})["enabled"] is False
    assert barehands.load({"barehands_test_mode": True})["enabled"] is False
    assert barehands.load({"barehands_test_mode": {"enabled": True}})["enabled"] is True


def test_a_version_one_block_is_migrated_and_a_foreign_one_is_not_acted_upon():
    """La couture de migration, côté serveur.

    Un bloc v1 ne portait que `enabled` : le convertir, c'est donner leur
    défaut aux huit clés qu'il n'avait pas. Une version **étrangère**, elle,
    ne se devine pas — on n'en garde rien plutôt que d'agir sur des réglages
    qu'on ne sait pas lire, et le refus codé arrive à l'écriture.
    """

    migrated = barehands.load({"barehands_test_mode": {"enabled": True}})
    assert migrated["enabled"] is True
    assert migrated["tool"] == "pointer" and migrated["sleep_timeout_ms"] == 30000
    assert set(migrated) == set(barehands.SETTINGS_DEFAULTS)

    stranger = barehands.load({"barehands_test_mode": {"schema_version": 99, "enabled": True, "tool": "pan"}})
    assert stranger == barehands.SETTINGS_DEFAULTS
    assert stranger["enabled"] is False, "on n'allume pas Bare Hands sur des réglages illisibles"

    settings = {"barehands_test_mode": {"schema_version": 99, "enabled": True}}
    with pytest.raises(barehands.BarehandsSettingsError) as caught:
        barehands.apply(settings, {"enabled": True, "schema_version": 99})
    assert caught.value.code == "barehands_schema_version_unsupported"


def test_a_version_one_block_can_also_be_written_back_not_only_read(tmp_path):
    """**La migration marchait dans un sens seulement** (constat de la Slice 11).

    `load` convertissait une v1 ; `apply` refusait *toute* version autre que la
    courante, la v1 comprise. Une page qui relisait un bloc v1 et le
    réécrivait tel quel se faisait donc refuser par le serveur même qui venait
    de le lire : le bloc restait en v1 pour toujours, reconverti à chaque
    lecture, et la version enregistrée ne montait jamais.
    """

    assert 1 in barehands.MIGRATED_SCHEMA_VERSIONS

    settings = {"barehands_test_mode": {"enabled": False}}   # bloc v1 : `enabled` seul
    value = barehands.apply(settings, {"schema_version": 1, "enabled": True, "tool": "pan"})

    # Écrit dans la version **courante** : la prochaine lecture n'a plus rien à
    # convertir, et rien n'a été archivé — une v1 n'est pas un bloc illisible.
    assert settings["barehands_test_mode"]["schema_version"] == barehands.SCHEMA_VERSION
    assert barehands.archived_keys(settings) == []
    # Ce que la demande portait est pris ; les huit clés que la v1 n'avait pas
    # prennent leur défaut, exactement comme à la lecture.
    assert value["enabled"] is True and value["tool"] == "pan"
    assert value["sleep_timeout_ms"] == barehands.SETTINGS_DEFAULTS["sleep_timeout_ms"]
    assert set(settings["barehands_test_mode"]) == set(barehands.SETTINGS_DEFAULTS) | {"schema_version"}


def test_defaults_because_unreadable_and_defaults_because_fresh_are_not_the_same_answer():
    """`load()` rend le même dictionnaire dans les deux cas, à l'octet près.

    C'est le bon comportement — un fichier abîmé ne doit pas rendre Bare Hands
    injoignable — mais `describe()` annonçait `schema_version: 2` quoi qu'il ait
    lu, donc la page ne pouvait pas distinguer « des défauts parce
    qu'illisible » d'« des défauts parce que neuf ». Un premier lancement et une
    perte annoncée arrivaient identiques à l'écran.
    """

    fresh = barehands.inspect({})
    assert fresh == {"present": False, "stored_schema_version": None,
                     "unreadable": False, "archive_key": None}

    ours = barehands.inspect({"barehands_test_mode": {"schema_version": 2, "enabled": True}})
    assert ours["stored_schema_version"] == 2 and ours["unreadable"] is False

    # Un bloc v1 n'a pas de numéro : « écrit par nous », et converti.
    legacy = barehands.inspect({"barehands_test_mode": {"enabled": True}})
    assert legacy["stored_schema_version"] == barehands.SCHEMA_VERSION
    assert legacy["unreadable"] is False

    foreign = barehands.inspect({"barehands_test_mode": {"schema_version": 3, "enabled": True}})
    assert foreign["unreadable"] is True and foreign["stored_schema_version"] == 3
    assert foreign["archive_key"] == "barehands_test_mode_archived_v3"

    # Un numéro qui n'est pas un nombre est illisible aussi, et ne se range pas
    # sous une clé « v-1 » : un nom que personne ne saurait relire.
    junk = barehands.inspect({"barehands_test_mode": {"schema_version": "trois"}})
    assert junk["unreadable"] is True
    assert junk["archive_key"] == "barehands_test_mode_archived_vunknown"


def test_an_unreadable_block_is_kept_under_a_versioned_key_before_the_defaults_land(tmp_path):
    """Le scénario complet du constat R6, joué en entier.

    L'utilisateur lance un Jarvis plus récent qui écrit une v3, revient à cette
    version, rouvre l'onglet Expérimental et recoche Bare Hands. `apply` part de
    `load()` — c'est-à-dire des défauts — et réécrivait la clé **entière** : ses
    réglages v3 étaient détruits sans qu'un seul mot passe.
    """

    del tmp_path
    theirs = {"schema_version": 3, "enabled": True, "tool": "pan", "hover_dwell_ms": 250}
    settings: dict = {"barehands_test_mode": dict(theirs)}

    # Ce que la page apprend **avant** d'écrire : non appliqué, et pourquoi.
    assert barehands.describe(settings, Path("nowhere"))["unreadable"] is True
    assert barehands.describe(settings, Path("nowhere"))["stored_schema_version"] == 3
    assert barehands.describe(settings, Path("nowhere"))["archived"] == []
    assert barehands.describe(settings, Path("nowhere"))["enabled"] is False

    barehands.apply(settings, {"enabled": True})

    # Le bloc courant est bien reparti des défauts…
    assert settings["barehands_test_mode"]["schema_version"] == barehands.SCHEMA_VERSION
    assert settings["barehands_test_mode"]["tool"] == "pointer"
    # …et l'ancien est intact, **y compris la clé que cette version ne connaît
    # pas** : archiver en normalisant reviendrait à perdre ce qu'on prétend
    # garder.
    assert settings["barehands_test_mode_archived_v3"] == theirs

    state = barehands.describe(settings, Path("nowhere"))
    assert state["unreadable"] is False, "ce qui est écrit maintenant se relit"
    assert state["stored_schema_version"] == barehands.SCHEMA_VERSION
    assert state["archived"] == ["barehands_test_mode_archived_v3"], (
        "l'écran doit pouvoir nommer où ils sont passés, pas seulement dire qu'ils ont survécu"
    )


def test_a_readable_block_is_never_archived_and_two_foreign_versions_do_not_collide():
    """Archiver à chaque écriture doublerait le fichier de réglages pour rien.

    Et deux retours en arrière depuis deux versions différentes doivent laisser
    **deux** archives : une clé unique ferait de la seconde la destruction
    silencieuse que la première a évitée.
    """

    ordinary: dict = {"barehands_test_mode": {"schema_version": 2, "enabled": True}}
    barehands.apply(ordinary, {"enabled": False})
    assert barehands.archived_keys(ordinary) == []

    settings: dict = {"barehands_test_mode": {"schema_version": 3, "enabled": True}}
    barehands.apply(settings, {"enabled": True})
    settings["barehands_test_mode"] = {"schema_version": 4, "sensitivity": 3}
    barehands.apply(settings, {"enabled": True})
    assert barehands.archived_keys(settings) == [
        "barehands_test_mode_archived_v3", "barehands_test_mode_archived_v4",
    ]
    assert settings["barehands_test_mode_archived_v3"]["schema_version"] == 3
    assert settings["barehands_test_mode_archived_v4"]["sensitivity"] == 3

    # Même version deux fois : c'est le bloc **le plus récent** qui est gardé,
    # l'autre ayant déjà été remplacé par l'aller-retour précédent. La route le
    # dit dans le journal plutôt que de le taire.
    settings["barehands_test_mode"] = {"schema_version": 4, "sensitivity": 2}
    barehands.apply(settings, {"enabled": True})
    assert settings["barehands_test_mode_archived_v4"]["sensitivity"] == 2
    assert len(barehands.archived_keys(settings)) == 2


def test_a_refused_write_archives_nothing():
    """L'archive est une conséquence de l'écriture, pas de la tentative.

    Archiver avant de valider rangerait le bloc étranger **et** le laisserait
    en place : le fichier porterait deux copies, et la prochaine écriture
    valide écraserait l'archive par la même copie. Un refus ne touche à rien.
    """

    theirs = {"schema_version": 3, "enabled": True}
    settings: dict = {"barehands_test_mode": dict(theirs)}
    with pytest.raises(barehands.BarehandsSettingsError):
        barehands.apply(settings, {"enabled": True, "tool": "gomme"})
    assert settings == {"barehands_test_mode": theirs}, "un refus n'écrit rien, pas même une archive"


def test_a_stored_value_out_of_range_or_of_the_wrong_type_falls_back_to_its_default():
    """Lecture **tolérante** : un fichier abîmé ne rend pas Bare Hands
    injoignable. C'est l'écriture qui refuse, pas la lecture."""

    loaded = barehands.load({"barehands_test_mode": {
        "schema_version": 2, "enabled": True, "sleep_timeout_ms": "beaucoup",
        "assistance": 9, "sensitivity": -4, "tool": "draw", "diagnostics": "oui",
    }})
    assert loaded["enabled"] is True
    assert loaded["sleep_timeout_ms"] == 30000, "un nombre illisible vaut le défaut"
    assert loaded["assistance"] == 1.0 and loaded["sensitivity"] == 0.25, "hors bornes : borné"
    assert loaded["tool"] == "pointer", "un outil sans moteur ne se relit pas comme actif"
    assert loaded["diagnostics"] is False


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (None, "barehands_bad_payload"),
        ([True], "barehands_bad_payload"),
        ({}, "barehands_enabled_missing"),
        ({"enabled": "yes"}, "barehands_enabled_not_boolean"),
        ({"enabled": 1}, "barehands_enabled_not_boolean"),
        ({"enabled": True, "camera": "front"}, "barehands_unknown_field"),
        ({"enabled": True, "target_preview": "non"}, "barehands_setting_not_boolean"),
        ({"enabled": True, "diagnostics": 1}, "barehands_setting_not_boolean"),
        ({"enabled": True, "sleep_timeout_ms": "30s"}, "barehands_setting_not_a_number"),
        ({"enabled": True, "sleep_timeout_ms": True}, "barehands_setting_not_a_number"),
        ({"enabled": True, "sleep_timeout_ms": 4999}, "barehands_setting_out_of_range"),
        ({"enabled": True, "sleep_timeout_ms": 600001}, "barehands_setting_out_of_range"),
        ({"enabled": True, "assistance": 1.5}, "barehands_setting_out_of_range"),
        ({"enabled": True, "sensitivity": 0.1}, "barehands_setting_out_of_range"),
        ({"enabled": True, "tool": "gomme"}, "barehands_tool_unknown"),
        # `highlighter` et `draw` ont quitté la table : la couche d'annotation
        # est hors V1. Ils se refusent donc désormais comme n'importe quel nom
        # inconnu, et non plus comme « déclaré sans moteur ».
        ({"enabled": True, "tool": "highlighter"}, "barehands_tool_unknown"),
        ({"enabled": True, "tool": "draw"}, "barehands_tool_unknown"),
    ],
)
def test_apply_rejects_malformed_payloads_with_a_stable_code(payload, code):
    stored = {"schema_version": barehands.SCHEMA_VERSION, **barehands.SETTINGS_DEFAULTS, "enabled": True}
    settings: dict = {"barehands_test_mode": dict(stored)}
    with pytest.raises(barehands.BarehandsSettingsError) as caught:
        barehands.apply(settings, payload)
    assert caught.value.code == code
    assert settings == {"barehands_test_mode": stored}, "un refus n'écrit rien"


def test_a_tool_declared_without_an_engine_is_still_refused_by_its_own_name(monkeypatch):
    """La recette d'extension, vivante après le retrait de la couche d'annotation.

    ``TOOLS`` et ``INSTALLED_TOOLS`` coïncident aujourd'hui — la palette offre
    exactement ce qui marche —, donc ce refus n'est plus atteignable par un nom
    du produit. Il reste la seule chose qui empêche le **prochain** outil
    déclaré sans moteur d'être enregistré et sans effet, ce qui serait
    indiscernable d'un réglage appliqué. On le déclare donc ici comme une Slice
    future le déclarerait : dans ``TOOLS``, absent d'``INSTALLED_TOOLS``.
    """

    monkeypatch.setattr(barehands, "TOOLS", barehands.TOOLS + ("ink",))
    settings: dict = {}
    with pytest.raises(barehands.BarehandsSettingsError) as caught:
        barehands.apply(settings, {"enabled": True, "tool": "ink"})
    assert caught.value.code == "barehands_tool_not_installed"
    # Et la phrase nomme l'outil **et** ce qui reste possible : un refus qui
    # ne dit ni quoi ni quoi d'autre laisse l'appelant sans issue.
    assert "ink" in str(caught.value)
    assert "pointer, pan, select" in str(caught.value)
    assert settings == {}, "un refus n'écrit rien"


def test_the_whole_widened_payload_is_accepted_and_an_absent_key_keeps_what_is_stored():
    """La route reste utilisable avec le seul interrupteur (constat F5) : elle
    s'applique à chaud et ne doit dépendre de rien d'autre."""

    settings: dict = {}
    barehands.apply(settings, {
        "schema_version": barehands.SCHEMA_VERSION, "enabled": True, "target_preview": False,
        "sleep_timeout_ms": 45000, "tool": "pan", "assistance": 0.25, "sensitivity": 2,
        "tutorial_seen": True, "calibration_enabled": False, "diagnostics": True,
    })
    assert settings["barehands_test_mode"]["schema_version"] == barehands.SCHEMA_VERSION
    assert settings["barehands_test_mode"]["tool"] == "pan"

    # L'interrupteur seul : il éteint, et ne réinitialise pas les huit autres.
    value = barehands.apply(settings, {"enabled": False})
    assert value["enabled"] is False
    assert value["tool"] == "pan" and value["sleep_timeout_ms"] == 45000
    assert value["assistance"] == 0.25 and value["diagnostics"] is True


def test_the_tool_table_matches_the_contract_the_page_draws_from(tmp_path):
    """Le serveur refuse sur sa table, la palette dessine sur celle du contrat.
    Deux tables qui divergent, c'est un outil grisé à l'écran et accepté par la
    route, ou l'inverse. La parité est **exécutée**, pas supposée."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    contracts = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_barehands_contracts.js"
    script = tmp_path / "tools.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(contracts))});\n"
        "process.stdout.write(JSON.stringify({tools:C.TOOLS,installed:C.INSTALLED_TOOLS,"
        "version:C.SETTINGS_SCHEMA_VERSION,defaults:C.SETTINGS_DEFAULTS,"
        "bounds:C.SETTINGS_BOUNDS,wire:C.SETTINGS_WIRE_KEYS}));",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                          timeout=30, check=False)
    assert done.returncode == 0, done.stderr
    contract = json.loads(done.stdout)

    assert contract["tools"] == list(barehands.TOOLS)
    assert contract["installed"] == list(barehands.INSTALLED_TOOLS)
    assert contract["version"] == barehands.SCHEMA_VERSION
    # Les neuf clés, les mêmes des deux côtés, avec les mêmes défauts.
    assert set(contract["wire"].values()) == set(barehands.SETTINGS_DEFAULTS)
    for js_key, wire_key in contract["wire"].items():
        assert contract["defaults"][js_key] == barehands.SETTINGS_DEFAULTS[wire_key], wire_key
    for js_key, bound in contract["bounds"].items():
        low, high = barehands.SETTINGS_BOUNDS[contract["wire"][js_key]]
        assert (bound["min"], bound["max"]) == (low, high), js_key


async def test_default_state_is_off_and_reports_missing_assets(control):
    state = await state_of(control)

    assert state["enabled"] is False
    assert state["status"] == "experimental"
    assert state["assets"]["installed"] is False
    assert state["assets"]["missing"] == list(barehands.REQUIRED_ASSETS)
    assert state["assets"]["install_hint"] == "python scripts/bootstrap_third_party.py"


async def test_toggle_is_persisted_in_the_shared_settings_file_and_survives_a_restart(control, tmp_path, vendor):
    control.settings_path.parent.mkdir(parents=True, exist_ok=True)
    control.settings_path.write_text(json.dumps({"agent_cli": "codex", "manual_wake_key": "f8"}), encoding="utf-8")

    response = await control.save_barehands(JsonRequest({"enabled": True}))

    assert json.loads(response.text)["enabled"] is True
    stored = json.loads(control.settings_path.read_text(encoding="utf-8"))
    assert stored["barehands_test_mode"] == {
        "schema_version": barehands.SCHEMA_VERSION, **barehands.SETTINGS_DEFAULTS, "enabled": True,
    }
    assert stored["agent_cli"] == "codex" and stored["manual_wake_key"] == "f8"

    restarted = ControlCenter(runtime_root=control.runtime_root, project_root=tmp_path, barehands_vendor_root=vendor)
    assert (await state_of(restarted))["enabled"] is True

    await restarted.save_barehands(JsonRequest({"enabled": False}))
    assert (await state_of(control))["enabled"] is False
    assert json.loads(control.settings_path.read_text(encoding="utf-8"))["barehands_test_mode"]["enabled"] is False

    events = [event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
              if event.get("kind") == "settings.barehands"]
    assert [event["data"]["enabled"] for event in events] == [True, False]


async def test_the_journal_names_the_settings_that_changed_not_only_the_switch(control):
    """Le journal durable est la seule trace qui survit à la session : il doit
    dire **ce qui a changé**.

    La route porte les neuf réglages depuis la Slice 07, et le message n'avait
    pas suivi : trois déplacements du curseur de sensibilité écrivaient trois
    lignes identiques disant « Barehands (mode test) activé », et aucun des
    huit autres réglages n'apparaissait nulle part. Un journal qui dit la même
    chose quoi qu'il arrive ne dit rien."""

    await control.save_barehands(JsonRequest({"enabled": True}))
    await control.save_barehands(JsonRequest({"enabled": True, "sensitivity": 2}))
    await control.save_barehands(JsonRequest({"enabled": True, "sensitivity": 3}))
    await control.save_barehands(JsonRequest({"enabled": True, "tool": "select", "diagnostics": True}))
    # Une écriture qui ne change rien arrive pour de bon, et se dit telle quelle.
    await control.save_barehands(JsonRequest({"enabled": True}))
    await control.save_barehands(JsonRequest({"enabled": False}))

    events = [event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
              if event.get("kind") == "settings.barehands"]
    messages = [event["message"] for event in events]

    assert messages == [
        "Bare Hands activé (mode test)",
        "Réglages Bare Hands : sensitivity=2",
        "Réglages Bare Hands : sensitivity=3",
        "Réglages Bare Hands : diagnostics=True, tool=select",
        "Réglages Bare Hands réécrits sans changement",
        "Bare Hands désactivé (mode test)",
    ], messages
    # Et la donnée porte le détail, relisible par une machine.
    assert [event["data"]["changed"] for event in events] == [
        {"enabled": True}, {"sensitivity": 2}, {"sensitivity": 3},
        {"tool": "select", "diagnostics": True}, {}, {"enabled": False},
    ]
    # L'interrupteur reste lisible où il l'a toujours été.
    assert [event["data"]["enabled"] for event in events] == [True] * 5 + [False]


async def test_a_rollback_says_on_screen_and_in_the_journal_where_the_old_settings_went(control):
    """**Constat R6, refermé.** Le fichier survivait ; la parole, non.

    Un Jarvis plus récent écrit une v3, l'utilisateur revient à cette version,
    rouvre l'onglet, recoche Bare Hands. Rien n'apparaissait : ni bandeau, ni
    toast, ni ligne de journal, et la première écriture ordinaire remplaçait le
    bloc. Ici la lecture le dit, l'écriture le range, et les deux laissent une
    trace durable — la seule qui survive à la session.
    """

    control.settings_path.parent.mkdir(parents=True, exist_ok=True)
    theirs = {"schema_version": 3, "enabled": True, "tool": "pan", "hover_dwell_ms": 250}
    control.settings_path.write_text(
        json.dumps({"agent_cli": "codex", "barehands_test_mode": theirs}), encoding="utf-8")

    seen = await state_of(control)
    assert seen["unreadable"] is True and seen["stored_schema_version"] == 3
    assert seen["schema_version"] == barehands.SCHEMA_VERSION, "ce que ce serveur écrit, inchangé"
    assert seen["enabled"] is False, "on n'allume pas sur des réglages illisibles"
    assert seen["archived"] == [], "rien n'est encore rangé : le bloc est intact"

    read_lines = [event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
                  if event.get("kind") == "settings.barehands.foreign_version"]
    assert len(read_lines) == 1
    assert read_lines[0]["data"]["stored_schema_version"] == 3
    assert read_lines[0]["data"]["code"] == "barehands_stored_version_unreadable"
    assert "barehands_test_mode_archived_v3" in read_lines[0]["message"]

    # La lecture part à chaque ouverture de l'onglet : une ligne par processus,
    # pas une par requête — un journal noyé est un journal illisible.
    await state_of(control)
    await state_of(control)
    assert len([event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
                if event.get("kind") == "settings.barehands.foreign_version"]) == 1

    await control.save_barehands(JsonRequest({"enabled": True}))

    stored = json.loads(control.settings_path.read_text(encoding="utf-8"))
    assert stored["barehands_test_mode"]["schema_version"] == barehands.SCHEMA_VERSION
    assert stored["barehands_test_mode_archived_v3"] == theirs, "le bloc v3 a survécu, tel quel"
    assert stored["agent_cli"] == "codex", "et le reste du fichier n'a pas bougé"

    after = await state_of(control)
    assert after["unreadable"] is False
    assert after["archived"] == ["barehands_test_mode_archived_v3"]

    archived = [event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
                if event.get("kind") == "settings.barehands.archived"]
    assert len(archived) == 1, "l'archivage a sa propre ligne, pas un champ noyé dans l'autre"
    assert archived[0]["data"] == {
        "code": "barehands_stored_version_archived", "stored_schema_version": 3,
        "schema_version": barehands.SCHEMA_VERSION,
        "archive_key": "barehands_test_mode_archived_v3", "replaced_previous_archive": False,
    }
    assert "conservés" in archived[0]["message"] and "v3" in archived[0]["message"]

    # Une écriture ordinaire ensuite n'archive plus rien et ne redit rien.
    await control.save_barehands(JsonRequest({"enabled": False}))
    assert len([event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
                if event.get("kind") == "settings.barehands.archived"]) == 1


async def test_a_fresh_install_never_claims_that_something_was_unreadable(control):
    """L'autre moitié du constat : ne pas crier au loup au premier lancement.

    Sans bloc enregistré, `stored_schema_version` vaut `null` et `unreadable`
    est faux. Un drapeau toujours vrai ne dirait rien de plus qu'un drapeau
    toujours faux."""

    fresh = await state_of(control)
    assert fresh["stored_schema_version"] is None
    assert fresh["unreadable"] is False and fresh["archived"] == []

    await control.save_barehands(JsonRequest({"enabled": True}))
    ours = await state_of(control)
    assert ours["stored_schema_version"] == barehands.SCHEMA_VERSION
    assert ours["unreadable"] is False and ours["archived"] == []
    assert [event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
            if str(event.get("kind", "")).startswith("settings.barehands.foreign")] == []


async def test_rejected_toggle_writes_nothing_and_answers_400_with_its_code(control):
    await control.save_barehands(JsonRequest({"enabled": True}))
    before = control.settings_path.read_text(encoding="utf-8")

    for payload in ({"enabled": "on"}, ValueError("not json")):
        with pytest.raises(web.HTTPBadRequest) as caught:
            await control.save_barehands(JsonRequest(payload))
        assert caught.value.headers[SETTINGS_ERROR_CODE_HEADER].startswith("barehands_")

    assert control.settings_path.read_text(encoding="utf-8") == before


def test_routes_are_registered(control):
    paths = {resource.get_info().get("path") or resource.get_info().get("formatter")
             for resource in control._app.router.resources()}
    assert {"/api/barehands", "/barehands/assets/{asset}"} <= paths


# ------------------------------------------------------------------- assets


def test_vendor_root_defaults_to_the_bootstrap_install_and_can_be_overridden(tmp_path):
    assert barehands.vendor_root(tmp_path, {}) == tmp_path / "third_party" / "barehands" / "vendor"
    assert barehands.vendor_root(tmp_path, {barehands.VENDOR_ENV: str(tmp_path / "elsewhere")}) == tmp_path / "elsewhere"


async def test_installed_assets_are_served_with_their_type_and_nothing_else(control, vendor, tmp_path):
    install_assets(vendor)
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")

    assert (await state_of(control))["assets"] == {
        "installed": True, "missing": [], "base_url": "/barehands/assets",
        "install_hint": "python scripts/bootstrap_third_party.py",
    }

    wasm = await control.barehands_asset(AssetRequest("wasm/vision_wasm_internal.wasm"))
    assert isinstance(wasm, web.FileResponse)
    assert wasm.headers["Content-Type"] == "application/wasm"
    module = await control.barehands_asset(AssetRequest("vision_bundle.mjs"))
    assert module.headers["Content-Type"] == "text/javascript"

    for name in ("../../secret.txt", "mediapipe/vision_bundle.mjs", "wasm/vision_wasm_nosimd_internal.wasm", ""):
        with pytest.raises(web.HTTPNotFound):
            await control.barehands_asset(AssetRequest(name))


def test_the_page_receives_the_pointer_script_in_place_of_its_marker(control):
    import asyncio

    served = asyncio.run(control.index(None)).text
    assert BAREHANDS_SCRIPT_MARKER not in served
    assert "const JarvisBarehandsCore=" in served
    assert "window.JarvisBarehands=" in served
