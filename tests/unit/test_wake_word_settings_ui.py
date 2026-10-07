"""Section « Mot d'éveil » des Réglages du Control Center (Slice 07 de jarvis-wake-word).

Deux niveaux, aucun ne lit la source comme du texte pour en déduire un
comportement :

- la logique pure (`control_center_wake_word.js`, objet `JarvisWakeWordSettings`)
  exécutée avec node, sur les VRAIES réponses de `wake_word_settings.describe`
  (jamais des réponses écrites à la main) : formulaire, charge utile, état dit,
  traduction des codes de refus, lecture du dernier événement du détecteur ;
- l'insertion dans la page que `ControlCenter.index` sert.

Le rendu, le clic, le clavier et les thèmes sont prouvés dans un vrai
navigateur par `test_wake_word_settings_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

from aiohttp.test_utils import make_mocked_request
import pytest

from jarvis.runtime import control_center as cc
from jarvis.runtime import wake_word_settings as ww

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
MODULE_JS = RUNTIME / "control_center_wake_word.js"
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="node absent")


def run_js(body: str, **data) -> object:
    """Exécute `body` avec `L` (la logique pure) et `D` (les données), rend le JSON de `out`."""

    script = (
        f"const L=require({json.dumps(str(MODULE_JS))});\n"
        f"const D={json.dumps(data, ensure_ascii=False)};\n"
        f"let out;\n{body}\nprocess.stdout.write(JSON.stringify(out));\n"
    )
    done = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def state_of(**block) -> dict:
    """La réponse réelle de la route pour un fichier de réglages donné."""

    return ww.describe({"wake_word": {"schema_version": 1, **block}} if block else {})


FOREIGN = {"wake_word": {"schema_version": 7, "enabled": True}}


# ------------------------------------------------------------ les codes dits


def server_codes() -> set[str]:
    """Tous les codes stables que le module serveur peut produire."""

    return set(re.findall(r'"(wake_word_[a-z_]+)"', (RUNTIME / "wake_word_settings.py").read_text(encoding="utf-8")))


def test_every_server_code_has_a_readable_french_sentence():
    table = run_js("out=L.ERROR_TEXT")
    missing = {code for code in server_codes() if code not in table
               and code not in {"wake_word_settings_invalid"}}  # message de journal, jamais un refus de route
    assert not missing, f"codes sans phrase : {sorted(missing)}"
    for code, text in table.items():
        assert code.startswith("wake_word_") and len(text) > 15, code
        assert (text[0].isupper() or text[0] == "«") and text.rstrip().endswith((".", "»")), code
        assert "wake_word" not in text.replace("« wake_word »", ""), f"jargon dans {code}"


def test_the_thirteen_stable_write_refusals_are_all_translated():
    thirteen = {
        "wake_word_bad_payload", "wake_word_unknown_field", "wake_word_schema_version_unsupported",
        "wake_word_foreign_version", "wake_word_enabled_invalid", "wake_word_provider_invalid",
        "wake_word_provider_unknown", "wake_word_keyword_invalid", "wake_word_keyword_unknown",
        "wake_word_sensitivity_invalid", "wake_word_sensitivity_out_of_range",
        "wake_word_cooldown_invalid", "wake_word_cooldown_out_of_range",
    }
    assert set(run_js("out=L.WRITE_REFUSALS")) == thirteen
    # …et ce sont bien ceux que `apply` lève : on les provoque un à un.
    raised: set[str] = set()
    for payload, settings in [
        ("x", {}), ({"nope": 1}, {}), ({"schema_version": 9}, {}), ({"enabled": True}, FOREIGN),
        ({"enabled": "oui"}, {}), ({"provider": 3}, {}), ({"provider": "x"}, {}),
        ({"keyword": 3}, {}), ({"keyword": "Hey"}, {}), ({"sensitivity": "a"}, {}),
        ({"sensitivity": 1.5}, {}), ({"cooldown_ms": "a"}, {}), ({"cooldown_ms": 5}, {}),
    ]:
        with pytest.raises(ww.WakeWordSettingsError) as caught:
            ww.apply(json.loads(json.dumps(settings)), payload)
        raised.add(caught.value.code)
    assert raised == thirteen


def test_a_code_is_explained_with_the_field_it_accuses():
    why = run_js("out=['wake_word_sensitivity_out_of_range','wake_word_cooldown_invalid',"
                 "'wake_word_foreign_version','wake_word_bad_payload'].map(c=>L.explainError(c,'détail'))")
    assert [w["field"] for w in why] == ["sensitivity", "cooldown_ms", None, None]
    assert all(w["known"] and w["code"] for w in why)
    assert "entre 0 et 1" in why[0]["text"]
    assert why[0]["detail"] == "détail", "le texte du serveur reste visible, en détail"


def test_an_unknown_code_is_said_as_unknown_never_swallowed():
    why = run_js("out=[L.explainError('wake_word_nouveau','x'),L.explainError(null,'panne réseau'),"
                 "L.explainError('<script>alert(1)</script>','')]")
    assert all(w["known"] is False for w in why)
    assert all("ne sait pas traduire" in w["text"] for w in why)
    assert why[0]["code"] == "wake_word_nouveau", "un code stable inconnu reste affiché tel quel"
    assert why[2]["code"] is None, "un jeton qui n'a pas la forme d'un code n'est pas affiché"


# ----------------------------------------------------- le formulaire, la charge


def test_the_form_starts_from_the_servers_defaults_not_from_the_page():
    form = run_js("out=L.formFromState(D.state)", state=state_of())
    assert form == {"enabled": False, "provider": "porcupine", "keyword": "jarvis",
                    "sensitivity": "0.5", "cooldown_ms": "2000"}


def test_the_payload_sends_what_was_typed_and_never_corrects_it():
    payload = run_js(
        "const f=L.formFromState(D.state);"
        "out=[L.buildPayload({...f,sensitivity:'1.5',cooldown_ms:'5'}),"
        "L.buildPayload({...f,sensitivity:'',cooldown_ms:'abc'}),"
        "L.buildPayload({...f,sensitivity:'0,8',enabled:true})]", state=state_of())
    assert payload[0]["sensitivity"] == 1.5 and payload[0]["cooldown_ms"] == 5, "pas de bornage côté page"
    assert payload[1]["sensitivity"] is None and payload[1]["cooldown_ms"] == "abc", "le serveur dira « attend un nombre »"
    assert payload[2]["sensitivity"] == 0.8 and payload[2]["enabled"] is True
    for item in payload:
        assert set(item) == {"enabled", "provider", "keyword", "sensitivity", "cooldown_ms"}


def test_every_payload_the_page_can_build_is_judged_by_the_server_alone():
    """La page ne valide pas : ce qu'elle envoie, le serveur le juge, et les codes concordent."""

    cases = run_js(
        "const f=L.formFromState(D.state);"
        "out=[{sensitivity:'1.5'},{sensitivity:''},{sensitivity:'x'},{cooldown_ms:'5'},{cooldown_ms:'2000.5'},"
        "{cooldown_ms:''},{keyword:'Hey Jarvis'},{keyword:''}].map(o=>({o,payload:L.buildPayload({...f,...o})}))",
        state=state_of())
    expected = ["wake_word_sensitivity_out_of_range", "wake_word_sensitivity_invalid", "wake_word_sensitivity_invalid",
                "wake_word_cooldown_out_of_range", "wake_word_cooldown_invalid", "wake_word_cooldown_invalid",
                "wake_word_keyword_unknown", "wake_word_keyword_unknown"]
    table = run_js("out=L.ERROR_TEXT")
    for case, code in zip(cases, expected):
        with pytest.raises(ww.WakeWordSettingsError) as caught:
            ww.apply({}, case["payload"])
        assert caught.value.code == code, case
        assert code in table


def test_changing_the_provider_changes_the_keyword_like_the_server_does():
    out = run_js(
        "const s=D.state,f=L.formFromState(s);"
        "const toOpen=L.changeProvider(f,'openwakeword',s);"
        "const back=L.changeProvider(toOpen,'porcupine',s);"
        "const typed=L.changeProvider({...f,keyword:'hey google'},'porcupine',s);"
        "out={toOpen,back,typed}", state=state_of())
    assert out["toOpen"]["provider"] == "openwakeword" and out["toOpen"]["keyword"] == "hey_jarvis"
    assert out["back"]["provider"] == "porcupine" and out["back"]["keyword"] == "jarvis"
    assert out["typed"]["keyword"] == "hey google", "un mot Porcupine valide est gardé"
    # Le serveur fait pareil : le même changement, sans mot donné.
    settings: dict = {}
    assert ww.apply(settings, {"provider": "openwakeword"}).keyword == "hey_jarvis"


@pytest.mark.parametrize("word", [
    "jarvis", "hey google", "ok google", "a b c d", "Jarvis", "jarvis!", "hey_jarvis", "", " jarvis",
    "jarvis ", "a b c d e", "x" * 40, "é", "jarvis\n", "hey  google",
])
def test_the_advice_on_a_porcupine_word_matches_the_servers_verdict(word):
    advice = run_js("out=L.keywordAdvice('porcupine',D.word)", word=word)
    try:
        ww.apply({}, {"keyword": word})
        accepted = True
    except ww.WakeWordSettingsError:
        accepted = False
    assert (advice is None) is accepted, (word, advice)


def test_the_porcupine_pattern_is_the_servers_pattern():
    assert run_js("out=[L.PORCUPINE_PATTERN,L.PORCUPINE_MAX_LENGTH]") == [
        ww._PORCUPINE_TOKEN.pattern, ww._PORCUPINE_MAX_LENGTH]  # noqa: SLF001 - parité figée


def test_the_openwakeword_choices_and_bounds_come_from_the_server_response():
    out = run_js("out={k:L.keywordChoices(D.state),dirty:L.isDirty(L.formFromState(D.state),D.state)}", state=state_of())
    assert out == {"k": list(ww.OPENWAKEWORD_KEYWORDS), "dirty": False}
    assert run_js("const f=L.formFromState(D.state);out=L.isDirty({...f,sensitivity:'0.7'},D.state)", state=state_of()) is True


# ------------------------------------------------------ l'état que l'écran dit


def test_the_default_state_is_disabled_and_says_no_microphone_is_opened():
    model = run_js("out=L.describe(D.state)", state=state_of())
    assert model["kind"] == "disabled" and model["canSave"] is True and model["foreign"] is False
    assert model["pill"] == "Désactivé"
    assert "Aucun micro" in model["detail"]
    assert model["serverState"] == ww.describe({})["state"], "l'état du serveur est repris tel quel"


def test_an_enabled_setting_is_never_said_to_be_listening():
    model = run_js("out=L.describe(D.state)", state=state_of(enabled=True, provider="openwakeword", keyword="hey_jarvis"))
    assert model["kind"] == "enabled" and model["canSave"] is True
    assert "prochain démarrage de Voice" in model["detail"]
    assert "ne sait pas si Voice a redémarré" in model["detail"]
    for text in (model["pill"], model["title"], model["detail"]):
        assert "en écoute" not in text.lower() and "écoute à cet instant" not in text.lower()


def test_a_foreign_version_gets_its_own_message_and_cannot_be_saved():
    model = run_js("out=L.describe(D.state)", state=ww.describe(FOREIGN))
    assert model["kind"] == "foreign" and model["foreign"] is True and model["canSave"] is False
    assert model["pill"] == "Version étrangère"
    assert "autre version" in model["detail"] and "Enregistrer est désactivé" in model["detail"]
    assert run_js("out=L.isForeign(D.state)", state=ww.describe(FOREIGN)) is True
    # Une version illisible (texte) est étrangère aussi ; un bloc simplement abîmé ne l'est pas.
    assert run_js("out=L.isForeign(D.state)", state=ww.describe({"wake_word": {"schema_version": "deux"}})) is True
    assert run_js("out=L.isForeign(D.state)", state=ww.describe({"wake_word": {"schema_version": 1, "sensitivity": 9}})) is False


def test_a_damaged_block_lists_its_problems_in_french_and_stays_savable():
    state = ww.describe({"wake_word": {"schema_version": 1, "enabled": True, "sensitivity": 9, "colour": "red"}})
    model = run_js("out=L.describe(D.state)", state=state)
    assert model["kind"] == "unreadable" and model["canSave"] is True
    assert [p["code"] for p in model["problems"]] == ["wake_word_sensitivity_out_of_range"]
    assert "entre 0 et 1" in model["problems"][0]["text"]
    assert model["ignored"] == ["colour"]
    malformed = run_js("out=L.describe(D.state).problems", state=ww.describe({"wake_word": "oui"}))
    assert malformed[0]["code"] == "wake_word_block_malformed" and malformed[0]["known"] is True


def test_the_provider_requirements_and_the_license_are_said():
    info = run_js("out={o:L.providerInfo('openwakeword'),p:L.providerInfo('porcupine')}")
    assert "wakeword" in " ".join(info["o"]["requires"]) and "hey_jarvis" in " ".join(info["o"]["requires"])
    assert "non commercial" in info["o"]["license"] and "hey_jarvis" in info["o"]["license"]
    assert "Picovoice" in " ".join(info["p"]["requires"]) and info["p"]["license"] is None


# --------------------------------------------- le dernier événement du détecteur


def ev(kind: str, ts: str = "2026-10-07T10:00:00+00:00", **data) -> dict:
    return {"ts": ts, "kind": kind, "level": "error" if kind.endswith("failed") else "info",
            "message": "SECRET C:\\Users\\Nom\\fichier.py", "data": data}


def detector(lines: list, **options) -> dict:
    return run_js("out=L.detectorFromTrace(D.lines,{...D.options,formatTime:ts=>'à '+ts.slice(11,16)})",
                  lines=lines, options=options)


def test_no_detector_event_is_said_as_nothing_found_not_as_healthy():
    for lines in ([], [ev("voice.wake"), {"kind": "voice.transcript"}], None, ["x", 3]):
        out = detector(lines)
        assert out["kind"] == "none" and out["tone"] == ""
        assert "500 dernières lignes" in out["detail"]


def test_a_started_detector_is_a_past_event_not_a_live_measure():
    out = detector([ev("noise"), ev("wake.own_stream.started", provider="openwakeword")])
    assert out["kind"] == "started" and "démarré" in out["title"] and "(openwakeword)" in out["title"]
    assert "pas une mesure en direct" in out["detail"] and "ne prouve pas" in out["detail"]
    assert "10:00" in out["detail"]


def test_a_failure_is_said_with_its_cause_in_french_and_the_free_text_is_never_shown():
    out = detector([ev("wake.shared_pcm.started"),
                    ev("wake.shared_pcm.failed", code="wake_engine_unavailable", cause_code="wake_package_missing",
                       provider="openwakeword")])
    assert out["kind"] == "failed" and out["tone"] == "bad"
    assert "extra Python" in out["detail"] and "wake_package_missing" in out["detail"]
    assert out["codes"] == ["wake_package_missing", "wake_engine_unavailable"]
    assert "SECRET" not in json.dumps(out) and "Users" not in json.dumps(out)


def test_a_failure_survives_the_closing_that_follows_it():
    out = detector([ev("wake.own_stream.started"), ev("wake.own_stream.failed", code="wake_input_unavailable"),
                    ev("wake.own_stream.stopped")])
    assert out["kind"] == "failed" and "micro a refusé" in out["detail"]


def test_a_restart_after_a_failure_reads_as_started():
    out = detector([ev("wake.own_stream.failed", code="wake_input_unavailable"), ev("wake.own_stream.started")])
    assert out["kind"] == "started"


def test_stopped_and_offline_voice_are_said():
    stopped = detector([ev("wake.own_stream.started"), ev("wake.own_stream.stopped")])
    assert stopped["kind"] == "stopped" and "arrêté" in stopped["title"]
    offline = detector([ev("wake.shared_pcm.started")], voiceOnline=False)
    assert "Voice est hors ligne" in offline["detail"]
    assert "hors ligne" not in detector([ev("wake.shared_pcm.started")], voiceOnline=True)["detail"]
    assert "hors ligne" not in detector([ev("wake.shared_pcm.started")])["detail"], "inconnu n'est pas hors ligne"


def test_an_unsafe_code_or_provider_from_the_journal_is_not_echoed():
    out = detector([ev("wake.shared_pcm.failed", code="<b>x</b>", cause_code="wake_zzz", provider="<img src=x>")])
    blob = json.dumps(out, ensure_ascii=False)
    assert "<b>" not in blob and "<img" not in blob
    assert "code inconnu de cette page" in out["detail"] and "wake_zzz" in out["detail"]


def test_every_failure_code_the_detectors_write_has_a_sentence():
    table = run_js("out=L.DETECTOR_TEXT")
    written = set()
    for name in ("wakeword_shared_pcm.py", "wakeword_own_stream.py", "wakeword_openwakeword.py"):
        text = (RUNTIME.parent / "adapters" / name).read_text(encoding="utf-8")
        written |= set(re.findall(r'"(wake_(?:package|model|engine|inference|input|config|subscription|consume|backend)_[a-z_]+)"', text))
    # Les avertissements (file pleine, délai) ne sont pas des pannes : ils ne démarrent jamais « failed ».
    warnings = {"wake_inference_slow", "wake_engine_delete_failed", "wake_engine_release_failed", "wake_input_close_failed",
                "wake_model_download_failed", "wake_model_install_failed", "wake_engine_closed", "wake_frame_invalid"}
    missing = {code for code in written - warnings if code not in table}
    assert not missing, sorted(missing)


# ------------------------------------------------------------ la page servie


def test_the_script_is_declared_and_inserted_in_the_page():
    assert cc.WAKE_WORD_SCRIPT_FILE == "control_center_wake_word.js"
    assert cc.WAKE_WORD_SCRIPT_MARKER.startswith("/*__CONTROL_CENTER_") and cc.WAKE_WORD_SCRIPT_MARKER.endswith("__*/")
    html = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    assert html.count(cc.WAKE_WORD_SCRIPT_MARKER) == 1


async def test_the_served_page_carries_the_module_and_no_marker_is_left(tmp_path):
    control = cc.ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    response = await control.index(make_mocked_request("GET", "/"))
    html = response.text
    assert "JarvisWakeWordSettings" in html and "installJarvisWakeWordSettings" in html
    assert cc.WAKE_WORD_SCRIPT_MARKER not in html
    assert "Redémarrage de Voice requis" in html and "non commercial" in html


# ----------------------------------------- la page ne stocke rien, n'écrit qu'une route


def test_the_page_stores_nothing_locally():
    source = MODULE_JS.read_text(encoding="utf-8")
    for forbidden in ("localStorage", "sessionStorage", "indexedDB", "document.cookie", "caches.", "BroadcastChannel"):
        assert forbidden not in source, forbidden


def test_the_only_write_the_page_makes_is_the_wake_word_post():
    source = MODULE_JS.read_text(encoding="utf-8")
    assert source.count("method:'POST'") == 1
    assert re.search(r"api\(Logic\.ROUTE,\{method:'POST'", source), "le POST vise la route de la Slice 03"
    assert "method:'PUT'" not in source and "method:'DELETE'" not in source and "'PATCH'" not in source
    routes = set(re.findall(r"""['"`](/api/[a-z\-/?=${}A-Z_.]+)""", source))
    assert routes <= {"/api/wake-word", "/api/trace", "/api/trace?limit=${TRACE_LIMIT}", "/api/status"}, routes


# ------------------------------------------------ la fiche Human dit ce que l'écran fait


def test_the_human_validation_sheet_matches_what_the_screen_really_says():
    folder = Path(__file__).resolve().parents[2] / "tasks" / "jarvis-wake-word" / "slices" / "07-control-center-ui"
    sheet = json.loads((folder / "human-validation.json").read_text(encoding="utf-8"))
    text = sheet["checks"][0]["instructions"]
    assert "passe de désactivé à en écoute" not in text
    for said in ("Activé dans le réglage", "JAMAIS « en écoute »", "dernier événement", "wake_package_missing",
                 "wake_model_missing", "openWakeWord", "Redémarrage de Voice requis", "Porcupine"):
        assert said in text, said
    criteria = (folder / "SLICE.md").read_text(encoding="utf-8").split("## Acceptance Criteria")[1].split("##")[0]
    assert "en écoute" in criteria and "Jamais « en écoute »" in criteria
