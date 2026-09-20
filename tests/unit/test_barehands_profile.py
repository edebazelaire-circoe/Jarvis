"""Profil de calibration Bare Hands : ce que le serveur en garde (Slice 08).

Le serveur ne mesure rien — la caméra, les mains et l'écran sont dans la page.
Ce qui est vérifié ici est donc ce qu'il **refuse** et ce qu'il **conserve** :

- la décision 32 tenue là où la charge utile est vraiment inconnue : une liste
  blanche par nom de clé, et un refus codé pour tout ce qui n'est pas un
  scalaire dérivé — le module JS est de notre côté, le réseau ne l'est pas ;
- la décision 31 : une mesure absente retombe sur le défaut du moteur, une
  étape non jouée n'est pas une étape ratée, et `calibrated` est **dérivé** de
  la donnée, jamais repris de l'annonce ;
- une hystérésis se calibre **par paire** ou pas du tout, parce qu'une moitié
  mesurée et l'autre au défaut peut inverser l'invariant que le moteur refuse ;
- la même protection qu'aux réglages contre un retour en arrière : un profil en
  version étrangère est archivé, jamais écrasé — une calibration coûte une
  minute à l'utilisateur ;
- et la parité avec le contrat, **en exécutant** le contrat sous node plutôt
  qu'en recopiant ses tables.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime import barehands_profile as profile
from jarvis.runtime.control_center import SETTINGS_ERROR_CODE_HEADER, ControlCenter
from jarvis.runtime.journal import read_jsonl_tail

# La séance de calibration est jouée par le **vrai** parcours, dans le fichier
# qui tient son double de DOM : une charge utile écrite à la main ne porte que
# les clés auxquelles son auteur a pensé.
from test_barehands_calibration_js import (  # noqa: E402
    payload_of_a_run_where_every_stage_failed,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "jarvis" / "runtime" / "control_center_barehands_contracts.js"


class JsonRequest:
    def __init__(self, payload) -> None:
        self.payload = payload

    async def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


@pytest.fixture
def control(tmp_path):
    return ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path)


async def state_of(control: ControlCenter) -> dict:
    return json.loads((await control.get_barehands_profile(None)).text)


def run_node(tmp_path: Path, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "profile-parity.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        + source,
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=30, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ lecture


def test_nothing_stored_means_nothing_calibrated_and_the_engine_keeps_its_defaults():
    """Décision 31 : l'absence de profil n'est pas une panne, c'est l'état normal."""

    blank = profile.load({})
    assert blank["calibrated"] is False and blank["updated_at"] is None
    assert set(blank["hands"]) == {"left", "right", "unknown"}
    assert all(value is None for value in blank["hands"]["left"].values())
    assert {stage: report["status"] for stage, report in blank["stages"].items()} == {
        stage: "skipped" for stage in profile.STAGES
    }


def test_a_measure_that_does_not_read_falls_back_instead_of_becoming_a_number():
    """Lecture **tolérante**, et le piège de Python : `bool` est une sous-classe
    de `int`, donc `True` passerait pour la mesure `1` — la même espèce que le
    `Number(null)` vaut 0 que le contrat a trouvée côté page."""

    loaded = profile.load({profile.SETTING_KEY: {"schema_version": 2, "hands": {"left": {
        "press_ratio": "beaucoup", "release_ratio": True, "jitter_px": None,
        "travel_slop_norm": 99, "quality": -4,
    }}}})
    hand = loaded["hands"]["left"]
    assert hand["press_ratio"] is None, "une mesure illisible n'est pas un zéro"
    assert hand["release_ratio"] is None, "`True` n'est pas la mesure 1"
    assert hand["jitter_px"] is None
    assert hand["travel_slop_norm"] == 0.15 and hand["quality"] == 0.0, "borné, pas refusé, à la lecture"
    assert loaded["calibrated"] is True, "deux mesures bornées restent des mesures"


def test_a_half_measured_hysteresis_is_dropped_whole_at_read_time():
    """Un pincement qui ne peut jamais se relâcher bloquerait la main sur
    l'objet capturé. À la lecture on laisse tomber la paire **entière** plutôt
    que d'en garder une moitié : garder le `press` seul et prendre le `release`
    du moteur, c'est fabriquer la paire que le moteur refuse."""

    loaded = profile.load({profile.SETTING_KEY: {"schema_version": 2, "hands": {
        "left": {"press_ratio": 0.6, "release_ratio": 0.1},
    }}})
    assert loaded["hands"]["left"]["press_ratio"] is None
    assert loaded["hands"]["left"]["release_ratio"] is None
    assert loaded["calibrated"] is False


def test_an_inconsistent_stage_report_reads_as_not_played():
    """Un `ok` qui porte un motif d'échec et un `failed` muet disent deux choses
    contraires ; à la lecture on retombe sur « pas jouée », qui ne ment pas."""

    loaded = profile.load({profile.SETTING_KEY: {"schema_version": 2, "stages": {
        "neutral": {"status": "ok", "reason": "barehands_stage_timeout"},
        "c_pose": {"status": "failed"},
        "aim": {"status": "failed", "reason": "barehands_stage_no_hand", "samples": 7},
        "drag": {"status": "ok", "samples": -3},
    }}})
    assert loaded["stages"]["neutral"]["status"] == "skipped"
    assert loaded["stages"]["c_pose"]["status"] == "skipped"
    assert loaded["stages"]["aim"] == {
        "status": "failed", "reason": "barehands_stage_no_hand", "samples": 7,
    }
    assert loaded["stages"]["drag"]["samples"] == 0


# ------------------------------------------------------------------ écriture


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (None, "barehands_profile_bad_payload"),
        ([1], "barehands_profile_bad_payload"),
        ({}, "barehands_profile_schema_version_unsupported"),
        ({"schema_version": 1}, "barehands_profile_schema_version_unsupported"),
        ({"schema_version": 99}, "barehands_profile_schema_version_unsupported"),
        ({"schema_version": 2, "camera": "front"}, "barehands_profile_unknown_field"),
        ({"schema_version": 2, "hands": {"gauche": {}}}, "barehands_profile_handedness_unknown"),
        # **Décision 32.** Ce sont les refus qui comptent : une suite de points,
        # une image, un commentaire libre. La charge utile vient du réseau.
        ({"schema_version": 2, "hands": {"left": {"landmarks": [{"x": 1}]}}},
         "barehands_profile_unknown_field"),
        ({"schema_version": 2, "hands": {"left": {"press_ratio": "data:image/png;base64,AA"}}},
         "barehands_profile_not_derived"),
        ({"schema_version": 2, "hands": {"left": {"press_ratio": [0.2]}}},
         "barehands_profile_not_derived"),
        ({"schema_version": 2, "hands": {"left": {"press_ratio": True}}},
         "barehands_profile_not_derived"),
        ({"schema_version": 2, "hands": {"left": {"reach_norm": {"x": 0, "y": 0, "w": 1, "h": 1,
                                                                 "blob": "AAAA"}}}},
         "barehands_profile_not_derived"),
        ({"schema_version": 2, "hands": {"left": {"reach_norm": [0, 0, 1, 1]}}},
         "barehands_profile_not_derived"),
        ({"schema_version": 2, "stages": {"neutral": {"note": "ça s'est bien passé"}}},
         "barehands_profile_unknown_field"),
        ({"schema_version": 2, "stages": {"neutral": {"status": "failed", "reason": "j'ai bougé"}}},
         "barehands_profile_stage_unknown"),
        ({"schema_version": 2, "stages": {"echauffement": {}}}, "barehands_profile_stage_unknown"),
        ({"schema_version": 2, "updated_at": "hier"}, "barehands_profile_not_derived"),
        # Bornes, hystérésis, portée plate.
        ({"schema_version": 2, "hands": {"left": {"press_ratio": 0.001}}},
         "barehands_profile_out_of_range"),
        ({"schema_version": 2, "hands": {"left": {"travel_slop_norm": 0.9}}},
         "barehands_profile_out_of_range"),
        ({"schema_version": 2, "hands": {"left": {"press_ratio": 0.6, "release_ratio": 0.1}}},
         "barehands_profile_thresholds_invalid"),
        ({"schema_version": 2, "hands": {"left": {"press_ratio": 0.2}}},
         "barehands_profile_thresholds_incomplete"),
        ({"schema_version": 2, "hands": {"left": {"reach_norm": {"x": 0, "y": 0, "w": 0, "h": 1}}}},
         "barehands_profile_reach_invalid"),
        ({"schema_version": 2, "stages": {"neutral": {"status": "ok",
                                                      "reason": "barehands_stage_timeout"}}},
         "barehands_profile_stage_inconsistent"),
        ({"schema_version": 2, "stages": {"neutral": {"status": "failed"}}},
         "barehands_profile_stage_inconsistent"),
    ],
)
def test_apply_refuses_anything_that_is_not_a_derived_measure(payload, code):
    settings: dict = {}
    with pytest.raises(profile.BarehandsProfileError) as caught:
        profile.apply(settings, payload)
    assert caught.value.code == code
    assert settings == {}, "un refus n'écrit rien"


def test_a_complete_profile_round_trips_and_calibrated_is_derived_not_announced():
    settings: dict = {}
    written = profile.apply(settings, {
        "schema_version": 2,
        "calibrated": False,          # l'annonce est ignorée : c'est la donnée qui décide
        "updated_at": 1700000000000,
        "hands": {
            "left": {"press_ratio": 0.22, "release_ratio": 0.39,
                     "secondary_press_ratio": 0.25, "secondary_release_ratio": 0.44,
                     "jitter_px": 2.5, "travel_slop_norm": 0.009,
                     "reach_norm": {"x": 0.12, "y": 0.2, "w": 0.7, "h": 0.6}, "quality": 0.82},
        },
        "stages": {
            "neutral": {"status": "ok", "samples": 60},
            "resize": {"status": "failed", "reason": "barehands_stage_needs_two_hands", "samples": 4},
        },
    })
    assert written["calibrated"] is True, "« calibré » se dérive des mesures présentes"
    assert written["hands"]["left"]["press_ratio"] == 0.22
    assert written["hands"]["right"]["press_ratio"] is None, "l'autre main n'est pas inventée"
    assert written["stages"]["resize"]["reason"] == "barehands_stage_needs_two_hands"
    assert written["stages"]["aim"]["status"] == "skipped"
    assert profile.load(settings) == written, "ce qui est écrit se relit à l'identique"


def test_an_announced_calibration_without_a_single_measure_stays_uncalibrated(tmp_path):
    """« Calibré » sans mesure ne vaut pas calibré — même règle que le contrat.

    C'est le cas d'un parcours dont **toutes** les étapes ont échoué : il est
    légitime de l'enregistrer (le rapport par étape dit ce qui s'est passé), et
    il ne doit surtout pas faire croire que le moteur a été adapté.

    **La charge utile vient d'une vraie séance**, jouée par le vrai parcours et
    rendue telle que la page l'enverrait. La version écrite à la main de ce
    test visait déjà ce cas — et le manquait, parce qu'elle omettait le bloc
    `hands` en entier et ne portait donc jamais `hands.left.quality`, la
    métrique par laquelle `calibrated` devenait vrai sans une seule mesure. Un
    dictionnaire écrit à la main ne porte que les clés auxquelles son auteur a
    pensé ; c'est précisément le reproche que la sonde de la décision 32 fait
    aux profils « remplis de valeurs plausibles »."""

    built = payload_of_a_run_where_every_stage_failed(tmp_path)
    wire = {
        "schema_version": built["schemaVersion"],
        "updated_at": built["updatedAt"],
        "hands": {handedness: {profile.HAND_WIRE_KEYS[js_key]: value
                               for js_key, value in hand.items()}
                  for handedness, hand in built["hands"].items()},
        "stages": built["stages"],
        # L'annonce de la page, reprise telle quelle : c'est la donnée qui
        # décide, jamais l'annonce.
        "calibrated": True,
    }
    # La séance a bien **vu** la main : la métrique est là, et c'est elle qui
    # faisait basculer le drapeau.
    assert wire["hands"]["left"]["quality"] is not None

    settings: dict = {}
    written = profile.apply(settings, wire)
    assert written["calibrated"] is False, (
        "une séance qui n'a rien mesuré affichait « Calibré » et activait "
        "« Effacer le profil »"
    )
    assert written["hands"]["left"]["quality"] is not None, "la métrique reste persistée"
    for key in profile.CALIBRATING_KEYS:
        for handedness in profile.HANDEDNESSES:
            assert written["hands"][handedness][key] is None, (handedness, key)
    assert all(report["status"] == "failed" for report in written["stages"].values())
    # Et la relecture dit la même chose que l'écriture.
    assert profile.load(settings)["calibrated"] is False


def test_a_write_replaces_the_profile_whole_instead_of_merging_two_sessions():
    """Contrairement aux réglages, une clé absente n'est **pas** conservée.

    Un profil est écrit en entier par une calibration. Fusionner une écriture
    partielle avec ce qui est enregistré mêlerait deux séances de mesure sur une
    même main sans que rien ne le dise — et la seconde séance est précisément
    celle que l'utilisateur vient de juger nécessaire."""

    settings: dict = {}
    profile.apply(settings, {"schema_version": 2, "hands": {
        "left": {"press_ratio": 0.22, "release_ratio": 0.39, "jitter_px": 9.0}}})
    after = profile.apply(settings, {"schema_version": 2, "hands": {
        "right": {"jitter_px": 1.0}}})
    assert after["hands"]["left"]["press_ratio"] is None, "la séance précédente ne survit pas"
    assert after["hands"]["left"]["jitter_px"] is None
    assert after["hands"]["right"]["jitter_px"] == 1.0


def test_clearing_removes_the_block_rather_than_leaving_an_empty_shell():
    settings: dict = {"other": 1}
    profile.apply(settings, {"schema_version": 2, "hands": {"left": {"jitter_px": 3.0}}})
    assert profile.SETTING_KEY in settings
    cleared = profile.clear(settings)
    assert profile.SETTING_KEY not in settings, "« aucun profil » et « profil vide » se relisent pareil"
    assert cleared["calibrated"] is False
    assert settings == {"other": 1}


# ------------------------------------------- retour en arrière (même règle qu'aux réglages)


def test_a_profile_from_a_newer_jarvis_is_archived_before_the_defaults_land():
    theirs = {"schema_version": 3, "hands": {"left": {"pressRatio": 0.2}}, "grip_strength": 4}
    settings: dict = {profile.SETTING_KEY: dict(theirs)}

    seen = profile.describe(settings)
    assert seen["unreadable"] is True and seen["stored_schema_version"] == 3
    assert seen["calibrated"] is False, "on n'applique pas un profil qu'on ne sait pas lire"
    assert seen["archived"] == []

    profile.apply(settings, {"schema_version": 2, "hands": {"left": {"jitter_px": 2.0}}})
    assert settings["barehands_calibration_profile_archived_v3"] == theirs, "gardé tel quel"
    after = profile.describe(settings)
    assert after["unreadable"] is False
    assert after["archived"] == ["barehands_calibration_profile_archived_v3"]


def test_a_fresh_install_and_an_unreadable_profile_are_not_the_same_answer():
    fresh = profile.describe({})
    assert fresh["stored_schema_version"] is None and fresh["unreadable"] is False
    ours = profile.describe({profile.SETTING_KEY: {"schema_version": 2}})
    assert ours["stored_schema_version"] == 2 and ours["unreadable"] is False
    foreign = profile.describe({profile.SETTING_KEY: {"schema_version": 7}})
    assert foreign["stored_schema_version"] == 7 and foreign["unreadable"] is True


# ------------------------------------------------------------------ la route


async def test_the_route_saves_rereads_and_resets_and_the_journal_says_what_was_measured(control):
    empty = await state_of(control)
    assert empty["calibrated"] is False and empty["stage_order"] == list(profile.STAGES)

    saved = json.loads((await control.save_barehands_profile(JsonRequest({
        "schema_version": 2, "updated_at": 1700,
        "hands": {"left": {"press_ratio": 0.22, "release_ratio": 0.39, "jitter_px": 2.0},
                  "right": {"travel_slop_norm": 0.01}},
        "stages": {"neutral": {"status": "ok", "samples": 60},
                   "resize": {"status": "failed", "reason": "barehands_stage_needs_two_hands"}},
    }))).text)
    assert saved["calibrated"] is True
    assert (await state_of(control))["hands"]["left"]["press_ratio"] == 0.22

    # Il survit à un redémarrage : c'est tout l'intérêt de le persister.
    restarted = ControlCenter(runtime_root=control.runtime_root, project_root=control.project_root)
    assert (await state_of(restarted))["hands"]["left"]["press_ratio"] == 0.22

    events = [event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
              if event.get("kind") == "settings.barehands.profile"]
    assert len(events) == 1
    # Le journal dit **ce qui a été mesuré**, pas « profil enregistré » : une
    # calibration complète et une qui a tout raté ne s'y lisent pas pareil.
    assert events[0]["data"]["measured"] == ["left.jitter_px", "left.press_ratio",
                                             "left.release_ratio", "right.travel_slop_norm"]
    assert events[0]["data"]["stages"]["neutral"] == "ok"
    assert events[0]["data"]["stages"]["resize"] == "failed"
    assert "resize" in events[0]["message"]

    reset = json.loads((await control.reset_barehands_profile(None)).text)
    assert reset["calibrated"] is False
    assert (await state_of(control))["hands"]["left"]["press_ratio"] is None
    assert [event["data"]["had_profile"] for event in read_jsonl_tail(control.journal.trace_path, limit=50)
            if event.get("kind") == "settings.barehands.profile_reset"] == [True]


async def test_a_calibration_that_measured_nothing_is_recorded_as_such(control, tmp_path):
    """La branche « sans aucune mesure » du journal, exercée sur une **vraie**
    séance ratée plutôt que sur un dictionnaire sans bloc `hands`.

    Elle ne tirait jamais dans le produit : `quality` étant écrite dès qu'une
    image a été vue, une séance dont les sept étapes avaient échoué se
    journalisait « 1 mesure(s), 0/7 étape(s) réussie(s) » avec
    `calibrated: true`."""

    built = payload_of_a_run_where_every_stage_failed(tmp_path)
    await control.save_barehands_profile(JsonRequest({
        "schema_version": built["schemaVersion"],
        "updated_at": built["updatedAt"],
        "hands": {handedness: {profile.HAND_WIRE_KEYS[js_key]: value
                               for js_key, value in hand.items()}
                  for handedness, hand in built["hands"].items()},
        "stages": built["stages"],
    }))
    events = [event for event in read_jsonl_tail(control.journal.trace_path, limit=50)
              if event.get("kind") == "settings.barehands.profile"]
    assert "sans aucune mesure" in events[0]["message"], events[0]["message"]
    assert events[0]["data"]["calibrated"] is False
    # La métrique n'est pas comptée comme une mesure : elle n'adapte rien.
    assert events[0]["data"]["measured"] == []


async def test_a_refused_profile_answers_400_with_its_code_and_writes_nothing(control):
    await control.save_barehands_profile(JsonRequest({
        "schema_version": 2, "hands": {"left": {"jitter_px": 3.0}}}))
    before = control.settings_path.read_text(encoding="utf-8")
    with pytest.raises(Exception) as caught:
        await control.save_barehands_profile(JsonRequest({
            "schema_version": 2, "hands": {"left": {"landmarks": [{"x": 1, "y": 2}]}}}))
    response = caught.value
    assert getattr(response, "status", None) == 400
    assert response.headers[SETTINGS_ERROR_CODE_HEADER] == "barehands_profile_unknown_field"
    assert control.settings_path.read_text(encoding="utf-8") == before, "un refus n'écrit rien"
    assert [event["data"]["code"] for event in read_jsonl_tail(control.journal.trace_path, limit=50)
            if event.get("kind") == "settings.barehands.profile_rejected"] == [
        "barehands_profile_unknown_field"]


async def test_the_profile_route_does_not_disturb_the_settings_block(control):
    """Deux blocs, deux numéros de schéma, deux routes. Écrire l'un ne revalide
    pas l'autre — c'est la raison d'être de la séparation."""

    await control.save_barehands(JsonRequest({"enabled": True, "sensitivity": 2}))
    await control.save_barehands_profile(JsonRequest({
        "schema_version": 2, "hands": {"left": {"jitter_px": 3.0}}}))
    stored = json.loads(control.settings_path.read_text(encoding="utf-8"))
    assert stored["barehands_test_mode"]["enabled"] is True
    assert stored["barehands_test_mode"]["sensitivity"] == 2
    assert stored["barehands_calibration_profile"]["hands"]["left"]["jitter_px"] == 3.0
    assert stored["barehands_test_mode"].get("schema_version") == 2
    assert stored["barehands_calibration_profile"]["schema_version"] == 2

    await control.reset_barehands_profile(None)
    stored = json.loads(control.settings_path.read_text(encoding="utf-8"))
    assert stored["barehands_test_mode"]["enabled"] is True, "réinitialiser le profil n'éteint rien"


# ------------------------------------------------------------------ parité


def test_the_two_halves_of_the_profile_schema_name_the_same_things(tmp_path):
    """Les deux moitiés du schéma sont tenues par un test qui **exécute**
    l'autre côté, comme celui des réglages : une clé renommée d'un côté sort ici
    en écart de table, pas en défaut silencieux."""

    contract = run_node(tmp_path, """
      out({
        version:C.PROFILE_SCHEMA_VERSION,
        migrated:C.PROFILE_MIGRATED_VERSIONS,
        keys:C.PROFILE_MEASURED_KEYS,
        handedness:C.HANDEDNESSES,
        stages:C.STAGES,
        statuses:C.STAGE_STATUSES,
        reasons:C.STAGE_REASONS,
        // Les bornes, lues du contrat en le **sollicitant** : une valeur
        // volontairement hors plage revient bornée, ce qui nomme la borne.
        bounds:Object.fromEntries(C.PROFILE_MEASURED_KEYS
          .filter(k=>k!=='reachNorm')
          .map(k=>[k,[C.normalizeProfile({hands:{left:{[k]:-1e6}}}).hands.left[k],
                      C.normalizeProfile({hands:{left:{[k]:1e6}}}).hands.left[k]]])),
      });
    """)
    assert contract["version"] == profile.SCHEMA_VERSION
    assert contract["migrated"] == list(profile.MIGRATED_SCHEMA_VERSIONS)
    assert contract["handedness"] == list(profile.HANDEDNESSES)
    assert contract["stages"] == list(profile.STAGES)
    assert contract["statuses"] == list(profile.STAGE_STATUSES)
    assert contract["reasons"] == list(profile.STAGE_REASONS)
    # Les noms : `camelCase` au contrat, `snake_case` sur le fil, une seule
    # table de passage.
    assert sorted(contract["keys"]) == sorted(profile.HAND_WIRE_KEYS)
    assert sorted(profile.HAND_WIRE_KEYS.values()) == sorted([*profile.HAND_BOUNDS, "reach_norm"])
    for js_key, wire_key in profile.HAND_WIRE_KEYS.items():
        if wire_key == "reach_norm":
            continue
        low, high = profile.HAND_BOUNDS[wire_key]
        assert contract["bounds"][js_key] == [low, high], js_key


def test_the_payload_the_page_builds_is_accepted_by_the_real_route(tmp_path):
    """La boucle fermée : ce que `toProfilePayload` construit part dans le
    **vrai** gestionnaire de route et revient par `GET`. C'est ce test qui
    interdit que les deux moitiés dérivent — une clé renommée d'un côté sort en
    `barehands_profile_unknown_field`."""

    import asyncio

    built = run_node(tmp_path, """
      const profile=C.normalizeProfile({updatedAt:1700,hands:{
        left:{pressRatio:.22,releaseRatio:.39,secondaryPressRatio:.25,
              secondaryReleaseRatio:.44,jitterPx:2.5,travelSlopNorm:.009,
              reachNorm:{x:.1,y:.2,w:.7,h:.6},quality:.8},
        unknown:{jitterPx:4}},
        stages:{neutral:{status:'ok',samples:60},
                resize:{status:'failed',reason:'barehands_stage_needs_two_hands',samples:2}}});
      out(C.toProfilePayload(profile));
    """)
    # Le contrat parle `camelCase` ; la route parle `snake_case`. Le passage est
    # la table, pas une conversion improvisée à l'appel.
    wire = {
        "schema_version": built["schemaVersion"],
        "updated_at": built["updatedAt"],
        "hands": {
            handedness: {
                profile.HAND_WIRE_KEYS[js_key]: value
                for js_key, value in hand.items()
            }
            for handedness, hand in built["hands"].items()
        },
        "stages": built["stages"],
    }

    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path)
    saved = json.loads(asyncio.run(control.save_barehands_profile(JsonRequest(wire))).text)
    assert saved["calibrated"] is True
    assert saved["hands"]["left"]["press_ratio"] == pytest.approx(0.22)
    assert saved["hands"]["left"]["reach_norm"] == {"x": 0.1, "y": 0.2, "w": 0.7, "h": 0.6}
    assert saved["hands"]["unknown"]["jitter_px"] == 4
    assert saved["stages"]["resize"]["reason"] == "barehands_stage_needs_two_hands"
    assert saved["schema_version"] == profile.SCHEMA_VERSION
