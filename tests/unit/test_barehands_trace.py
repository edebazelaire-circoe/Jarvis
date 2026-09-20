"""Traces de diagnostic Bare Hands, côté serveur (Slice 10, décision 32).

Le module JS est de notre côté ; le réseau ne l'est pas. Ce fichier épingle la
**seconde** moitié de la garantie : ce que `POST /api/barehands/traces` accepte
d'écrire sur le disque, ce qu'il refuse avec un code, et ce qu'il laisse dans
`runtime/trace.jsonl` — parce qu'un enregistrement dont rien ne reste dans le
journal rend « personne n'a enregistré » indiscernable de « l'enregistrement
est mort ».

Il épingle aussi le rejeu piloté depuis Python : déterminisme, refus d'un axe
inconnu, et le fait qu'un rejeu impossible se dit au lieu de rendre des mesures
vides.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from jarvis.runtime import barehands_replay, barehands_trace
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "jarvis" / "testlab" / "fixtures" / "barehands" / "golden.v1.json"


def minimal(**overrides) -> dict:
    payload = {
        "schema": barehands_trace.TRACE_SCHEMA,
        "schemaVersion": barehands_trace.SCHEMA_VERSION,
        "startedAt": 1700000000000,
        "durationMs": 320.0,
        "stoppedBecause": "asked",
        "viewport": {"width": 1280, "height": 720},
        "observedFrames": 2,
        "droppedFrames": 0,
        "frames": [
            {"t": 0, "lifecycle": "active",
             "hands": [{"handedness": "left", "primaryRatio": 0.8, "rawX": 10.0, "rawY": 20.0,
                        "quality": 0.9, "stillness": 0.95}],
             "candidates": [{"kind": "button", "region": "body", "actionable": True,
                             "x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}],
             "events": [{"type": "click", "channel": "primary", "onObject": True, "axes": 0}],
             "gestures": [{"name": "open_palm", "phase": "start", "suppressed": True}]},
            {"t": 16, "lifecycle": "active", "hands": [], "candidates": [],
             "events": [], "gestures": []},
        ],
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ la liste blanche


def test_the_server_rebuilds_a_trace_key_by_key_and_drops_everything_else():
    """**Ce que le schéma ne nomme pas n'atteint jamais le disque**, et pas
    parce qu'on le refuse : parce qu'on ne le recopie pas.

    On présente donc, à chaque niveau du document, ce qu'une trace ne doit
    jamais porter : les points d'une main, une image en base64, un objet libre,
    un identifiant de suivi, un identifiant d'objet, et un libellé — puis on
    relit le document **sérialisé**, une assertion clé par clé ne voyant pas
    une fuite au fond d'une poche imbriquée."""

    poison = {"landmarks": [{"x": 0.1, "y": 0.2, "z": 0.3}],
              "snapshot": "data:image/png;base64,iVBORw0KGgo=",
              "blob": {"pixels": [1, 2, 3]},
              "handTrackId": "hand-3f9a",
              "objectId": "sc-node-42",
              "label": "Mot de passe de Clarice"}
    payload = minimal()
    payload.update(poison)
    payload["viewport"].update(poison)
    for frame in payload["frames"]:
        frame.update(poison)
        for item in (*frame["hands"], *frame["candidates"], *frame["events"], *frame["gestures"]):
            item.update(poison)
    payload["frames"][0]["candidates"][0]["boundsPx"] = dict(poison)

    trace = barehands_trace.normalize(payload)
    text = json.dumps(trace, ensure_ascii=False)
    for leak in ("landmarks", "snapshot", "blob", "handTrackId", "hand-3f9a",
                 "sc-node-42", "label", "Mot de passe", "data:image", "pixels"):
        assert leak not in text, f"la trace écrite transporte « {leak} »"
    # Et ce qu'elle porte est exactement le schéma.
    assert set(trace) == {"schema", "schemaVersion", "startedAt", "durationMs",
                          "stoppedBecause", "viewport", "observedFrames",
                          "droppedFrames", "frames"}
    assert set(trace["viewport"]) == {"width", "height"}
    hand = trace["frames"][0]["hands"][0]
    assert set(hand) == {"slot", "handedness", *barehands_trace.HAND_NUMBERS}
    assert hand["slot"] == 0, "l'identité d'une main est une fente, jamais son identifiant"
    candidate = trace["frames"][0]["candidates"][0]
    assert set(candidate) == {"ref", "kind", "region", "representation", "actionable",
                              "x", "y", "w", "h"}
    assert candidate["ref"] == 0
    assert set(trace["frames"][0]["events"][0]) == {"type", "channel", "onObject", "axes"}


def test_normalizing_a_trace_twice_gives_the_same_trace():
    """La liste blanche doit savoir **se relire** : une trace relue du disque,
    ou rejouée, repasse par elle. Sans cela la géométrie d'une candidate
    (envoyée dans ``boundsPx``, stockée à plat) et le drapeau ``onObject``
    (envoyé comme ``objectId``, stocké comme booléen) disparaîtraient au second
    passage — et le banc d'essai dirait « aucun clic n'a atteint sa cible »
    d'une séance où tous l'avaient atteinte."""

    payload = minimal()
    payload["frames"][0]["candidates"][0] = {
        "kind": "button", "region": "body", "actionable": True,
        "objectId": "sc-node-42", "boundsPx": {"x": 600, "y": 300, "w": 140, "h": 44}}
    payload["frames"][0]["events"][0] = {
        "type": "drag_move", "channel": "primary", "objectId": "star-7", "axes": ["x", "y"]}
    once = barehands_trace.normalize(payload)
    twice = barehands_trace.normalize(once)
    assert json.dumps(once, sort_keys=True) == json.dumps(twice, sort_keys=True)
    candidate = twice["frames"][0]["candidates"][0]
    assert (candidate["x"], candidate["y"], candidate["w"], candidate["h"]) == (600.0, 300.0, 140.0, 44.0)
    assert twice["frames"][0]["events"][0]["onObject"] is True
    assert twice["frames"][0]["events"][0]["axes"] == 2
    # Et la trace d'or, qui est déjà normalisée, passe le même test.
    golden = barehands_trace.load(GOLDEN)
    assert json.dumps(golden, sort_keys=True) == json.dumps(
        barehands_trace.normalize(golden), sort_keys=True)


def test_an_absent_measurement_stays_absent_and_a_boolean_is_never_a_measurement():
    """**`Number(null) === 0` a déjà coûté une lecture fausse sur cette tâche.**
    Une clé absente, illisible ou infinie vaut `None` — jamais zéro, qui se
    lirait comme « mesuré, et au plancher ».

    Et `True` n'est pas la mesure `1` : `bool` est une sous-classe de `int` en
    Python, donc sans exclusion explicite un booléen passerait pour un nombre.
    C'est le même piège que `barehands_profile` a nommé au § 10."""

    payload = minimal()
    payload["frames"][0]["hands"][0] = {
        "handedness": "gauche",          # hors vocabulaire
        "primaryRatio": None,
        "secondaryRatio": "0.4",          # une chaîne n'est pas une mesure
        "cPose": True,                    # un booléen non plus
        "quality": float("nan"),
        "stillness": float("inf"),
        "rawX": 0,                        # zéro **est** une mesure, lui
    }
    hand = barehands_trace.normalize(payload)["frames"][0]["hands"][0]
    assert hand["handedness"] is None, "un mot hors vocabulaire ne traverse pas"
    assert hand["primaryRatio"] is None
    assert hand["secondaryRatio"] is None
    assert hand["cPose"] is None, "True passerait pour la mesure 1 sans l'exclusion des booléens"
    assert hand["quality"] is None and hand["stillness"] is None
    assert hand["rawX"] == 0.0, "zéro mesuré reste zéro : ce n'est pas une absence"
    # Toutes les autres clés du schéma sont présentes et absentes, pas manquantes.
    for key in barehands_trace.HAND_NUMBERS:
        assert key in hand


@pytest.mark.parametrize("payload,code", [
    (None, "barehands_trace_schema_unknown"),
    ({"schema": "autre.chose", "schemaVersion": 1, "frames": []}, "barehands_trace_schema_unknown"),
    (minimal(schemaVersion=2), "barehands_trace_version_unsupported"),
    (minimal(schemaVersion=0), "barehands_trace_version_unsupported"),
    (minimal(schemaVersion="1"), "barehands_trace_version_unsupported"),
    (minimal(frames="beaucoup"), "barehands_trace_invalid"),
    (minimal(frames=None), "barehands_trace_invalid"),
])
def test_a_trace_the_server_cannot_read_is_refused_with_a_code(payload, code):
    """**Un refus codé plutôt qu'un défaut plausible.** Une version inconnue se
    refuse au lieu de se deviner : devinée, elle rendrait des mesures sans
    rapport avec ce qui a été enregistré — et elles seraient crues, parce
    qu'elles ont la forme de mesures."""

    with pytest.raises(barehands_trace.BarehandsTraceError) as caught:
        barehands_trace.normalize(payload)
    assert caught.value.code == code


def test_a_trace_with_too_many_frames_is_refused_rather_than_written(tmp_path):
    """Une borne dure : au-delà, on refuse plutôt que d'écrire un fichier que
    personne n'ouvrira. Et la borne est **exacte** — le plafond lui-même passe."""

    frame = {"t": 0, "lifecycle": "active", "hands": [], "candidates": [],
             "events": [], "gestures": []}
    at_limit = minimal(frames=[dict(frame) for _ in range(barehands_trace.MAX_FRAMES)])
    assert len(barehands_trace.normalize(at_limit)["frames"]) == barehands_trace.MAX_FRAMES
    too_many = minimal(frames=[dict(frame) for _ in range(barehands_trace.MAX_FRAMES + 1)])
    with pytest.raises(barehands_trace.BarehandsTraceError) as caught:
        barehands_trace.normalize(too_many)
    assert caught.value.code == "barehands_trace_invalid"


def test_two_hands_is_the_ceiling_and_a_third_never_reaches_the_disk():
    """Le contrat n'en connaît que deux (`MAX_HANDS`). Une troisième main dans
    un document posté est soit une erreur, soit une tentative : dans les deux
    cas elle ne s'écrit pas."""

    payload = minimal()
    payload["frames"][0]["hands"] = [{"handedness": "left"}, {"handedness": "right"},
                                     {"handedness": "left"}]
    hands = barehands_trace.normalize(payload)["frames"][0]["hands"]
    assert [hand["slot"] for hand in hands] == [0, 1]


# ------------------------------------------------------------------ le rangement et le journal


def test_storing_a_trace_writes_one_file_and_one_journal_line(tmp_path):
    """**Le chemin normal se journalise aussi.** Un journal qui ne porte que
    les échecs rend « rien dans le journal » indiscernable de « mort » — et
    pour une fonctionnalité qui observe, savoir qu'elle a tourné et combien de
    temps est précisément ce qu'un humain voudra relire."""

    runtime = tmp_path / "runtime"
    stored = barehands_trace.store(runtime, minimal())
    path = Path(stored["path"])
    assert path.is_file() and path.parent.name == barehands_trace.TRACE_DIRNAME
    assert path.name == f"{stored['trace_id']}.json"
    assert stored["frames"] == 2 and stored["observed_frames"] == 2
    # Relu par la **même** porte que le réseau : un fichier n'est pas plus digne
    # de confiance qu'une requête.
    assert barehands_trace.load(path)["frames"] == barehands_trace.normalize(minimal())["frames"]

    # L'identifiant est stable pour un même contenu, et distinct sinon.
    other = minimal()
    other["frames"][0]["t"] = 1
    assert barehands_trace.trace_id(barehands_trace.normalize(minimal())) \
        != barehands_trace.trace_id(barehands_trace.normalize(other))


def test_a_file_that_drifted_to_an_unknown_version_is_refused_when_reread(tmp_path):
    """Une trace écrite par un autre Jarvis, ou éditée à la main, repasse par la
    liste blanche. Sans cela, le disque serait une porte dérobée autour de la
    route."""

    folder = tmp_path / "runtime" / barehands_trace.TRACE_DIRNAME
    folder.mkdir(parents=True)
    path = folder / "drifted.json"
    path.write_text(json.dumps(minimal(schemaVersion=9)), encoding="utf-8")
    with pytest.raises(barehands_trace.BarehandsTraceError) as caught:
        barehands_trace.load(path)
    assert caught.value.code == "barehands_trace_version_unsupported"
    path.write_text("{ pas du json", encoding="utf-8")
    with pytest.raises(barehands_trace.BarehandsTraceError) as caught:
        barehands_trace.load(path)
    assert caught.value.code == "barehands_trace_invalid"


def test_the_route_stores_a_trace_and_says_so_in_the_runtime_journal(tmp_path):
    """La route de bout en bout : elle range, elle rend l'identifiant, et elle
    laisse **une** ligne dans `runtime/trace.jsonl` avec son code stable
    (constat F6 de la Slice 00). Un refus y laisse une ligne `error`, qui part
    aussi dans `errors.jsonl`."""

    from jarvis.runtime.control_center import ControlCenter

    runtime = tmp_path / "runtime"
    control = ControlCenter(runtime_root=runtime, project_root=tmp_path,
                            barehands_vendor_root=tmp_path / "vendor")

    class Request:
        def __init__(self, payload):
            self._payload = payload

        async def json(self):
            if self._payload is _BROKEN:
                raise ValueError("pas du json")
            return self._payload

    response = asyncio.run(control.save_barehands_trace(Request(minimal())))
    body = json.loads(response.text)
    assert body["frames"] == 2
    assert (runtime / barehands_trace.TRACE_DIRNAME / f"{body['trace_id']}.json").is_file()

    lines = read_jsonl_tail(RuntimeJournal(runtime).trace_path, limit=20)
    recorded = [line for line in lines if line.get("kind") == "barehands.trace_recorded"]
    assert len(recorded) == 1, "un enregistrement doit laisser exactement une ligne"
    assert recorded[0]["data"]["code"] == "barehands_trace_recorded"
    assert recorded[0]["data"]["trace_id"] == body["trace_id"]
    assert recorded[0]["data"]["frames"] == 2
    assert "image(s)" in recorded[0]["message"]

    # Et un refus : 400, le code dans l'en-tête, une ligne `error`.
    from aiohttp import web

    with pytest.raises(web.HTTPBadRequest) as caught:
        asyncio.run(control.save_barehands_trace(Request(minimal(schemaVersion=7))))
    assert caught.value.headers["X-Jarvis-Error-Code"] == "barehands_trace_version_unsupported"
    errors = read_jsonl_tail(RuntimeJournal(runtime).error_path, limit=20)
    assert any(line.get("kind") == "barehands.trace_rejected" for line in errors)

    # Un corps illisible est refusé de la même façon, jamais écrit à moitié.
    with pytest.raises(web.HTTPBadRequest):
        asyncio.run(control.save_barehands_trace(Request(_BROKEN)))
    written = list((runtime / barehands_trace.TRACE_DIRNAME).glob("*.json"))
    assert len(written) == 1, "un refus ne doit rien laisser sur le disque"


_BROKEN = object()


# ------------------------------------------------------------------ le rejeu, piloté par Python


def test_the_golden_trace_carries_nothing_it_should_not_and_reads_back():
    """La trace d'or est **livrée avec le dépôt** : c'est elle que le Test Lab
    rejoue à chaque exécution, donc c'est elle qu'il faut regarder de près.

    Elle est **synthétique** — personne n'a mis la main devant une caméra pour
    la produire — et elle passe la même liste blanche que n'importe quelle
    trace postée."""

    raw = GOLDEN.read_text(encoding="utf-8")
    for leak in ("landmarks", "handTrackId", "hand-3f9a", "star-7", "sc-node-42",
                 "data:image", "objectId"):
        assert leak not in raw, f"la trace d'or transporte « {leak} »"
    trace = barehands_trace.load(GOLDEN)
    assert trace["schemaVersion"] == barehands_trace.SCHEMA_VERSION
    assert len(trace["frames"]) > 120, "la trace d'or doit porter de quoi mesurer"
    assert trace["viewport"]["width"] > 0, "sans largeur d'image, aucune distance n'est mesurable"
    # Elle couvre ce que les mesures lisent : des clics, un glissement, un
    # redimensionnement, un geste étouffé et une perte de main.
    kinds = {event["type"] for frame in trace["frames"] for event in frame["events"]}
    assert {"click", "context", "drag_move", "resize"} <= kinds
    assert any(gesture["suppressed"] for frame in trace["frames"] for gesture in frame["gestures"])
    assert any(len(frame["hands"]) == 2 for frame in trace["frames"])


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent")
def test_replaying_the_golden_trace_is_deterministic_and_two_configurations_differ():
    """**Le critère d'acceptation de la Slice**, depuis Python : « un
    développeur peut rejouer la même séance enregistrée sous au moins deux
    configurations et comparer des mesures objectives »."""

    configs = [
        {"name": "usine", "config": {}},
        {"name": "filtre-doux", "config": {"filter": {"minCutoffHz": 0.3}}},
    ]
    first = barehands_replay.compare(GOLDEN, configs)
    second = barehands_replay.compare(GOLDEN, configs)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True), (
        "deux rejeux de la même trace sous la même configuration doivent rendre "
        "des nombres identiques : sans cela, comparer deux configurations ne "
        "compare que le bruit"
    )
    assert first["identical"] is False
    assert "pointer.stationary_jitter_p95_norm" in first["changed"]
    assert [row["name"] for row in first["rows"]] == ["usine", "filtre-doux"]
    for row in first["rows"]:
        assert set(row["metrics"]) == set(barehands_replay.METRIC_KEYS)


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent")
def test_an_unknown_replay_axis_is_refused_instead_of_silently_doing_nothing():
    """Un axe inconnu accepté serait une configuration **sans effet**, et deux
    colonnes identiques se liraient « ce réglage ne change rien » au lieu de
    « ce réglage n'a pas été appliqué ». C'est la même espèce d'erreur qu'un
    faux succès."""

    with pytest.raises(barehands_replay.ReplayFailed) as caught:
        barehands_replay.replay(GOLDEN, [{"name": "faute", "config": {"filtre": {}}}])
    assert "filtre" in str(caught.value)
    # Et comparer une seule configuration ne dit rien : refusé.
    with pytest.raises(barehands_replay.ReplayFailed):
        barehands_replay.compare(GOLDEN, [{"name": "seule", "config": {}}])


def test_a_replay_that_cannot_run_says_so_instead_of_returning_empty_metrics():
    """**Une mesure qu'on n'a pas pu prendre n'est pas une mesure à zéro.**
    Sans node, le rejeu lève `ReplayUnavailable` : des métriques vides se
    liraient comme un produit parfait."""

    with pytest.raises(barehands_replay.ReplayUnavailable) as caught:
        barehands_replay.replay(GOLDEN, [{"name": "usine", "config": {}}],
                                node="node-qui-nexiste-pas")
    assert "node" in str(caught.value)


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent")
def test_the_testlab_runner_measures_the_golden_trace_under_its_parameters(tmp_path):
    """Le diagnostic enregistré dans le Test Lab, exercé pour de vrai : il lit
    ses paramètres, rejoue, et rend des mesures dont les noms sont exactement
    ceux que son manifeste déclare."""

    from jarvis.testlab.barehands.runners import InputQualityRunner
    from jarvis.testlab.catalog import load_catalog

    catalog = load_catalog()
    entry = catalog.describe("barehands.input_quality", 1)
    spec = entry.diagnostic
    declared = {metric.name for metric in spec.metrics}
    assert declared == set(barehands_replay.METRIC_KEYS), (
        "le manifeste et le rejeu ne nomment pas les mêmes mesures"
    )

    class Artifacts:
        def __init__(self):
            self.seen = []

        def put(self, path, *, kind, media_type, data):
            self.seen.append(path)
            return path

    class Context:
        parameters = {parameter.name: parameter.default for parameter in spec.parameters}
        committed: list = []

        def __init__(self):
            self.artifacts = Artifacts()
            self.lines: list[str] = []

        def log(self, line):
            self.lines.append(line)

        def put_artifact(self, path, *, kind, media_type, data):
            return self.artifacts.put(path, kind=kind, media_type=media_type, data=data)

    context = Context()
    outcome = asyncio.run(InputQualityRunner().run(context))
    # Les mesures rendues sont déclarées, et le compte d'images est réel.
    assert set(outcome.metrics) <= declared
    assert outcome.metrics["replay.frames_count"] > 120
    assert "barehands-replay.json" in context.artifacts.seen
    # Et l'assertion bloquante du manifeste passe sur la trace d'or : un
    # diagnostic livré qui échoue sur sa propre référence n'apprend rien.
    for assertion in spec.assertions:
        if not assertion.blocking:
            continue
        value = outcome.metrics.get(assertion.metric)
        assert value is not None, assertion.assertion_id
        if assertion.comparator == "ge":
            assert value >= assertion.threshold, assertion.assertion_id
        elif assertion.comparator == "le":
            assert value <= assertion.threshold, assertion.assertion_id
