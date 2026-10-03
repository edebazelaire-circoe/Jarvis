"""Opérations du cerveau sur les prefabs (`jarvis-display`, handoff prefab-foundation, Slice 07).

Contrat : `docs/prefabs.md` › *Agent tools*, *Base-edit gate* ; `docs/mcp/tool-contract.md` §10.13.
Vrai Core (`JarvisCoreApplication` derrière `LocalProtocolServer`, paquet livré +
racine de données de test), vrais outils (`SceneDisplayTools` + `PrefabDisplayTools`
sur leurs transports de production), et le vrai serveur FastMCP par une session MCP
en mémoire pour les schémas stricts.
"""

from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path

import pytest

from jarvis.core.conversation_event_emitter import PRODUCER_VOICE_ADMISSION, build_conversation_event
from jarvis.domain.conversation_events import ConversationEventType
from jarvis.domain.v2 import utc_now
from jarvis.runtime.core_sessions import CoreSessionTransport
from jarvis.runtime.display_mcp import DisplayToolError, SceneDisplayTools, build_server
from jarvis.runtime.display_prefabs import MAX_GET_SOURCE_BYTES, PrefabDisplayTools, fit_sources
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.prefab_relay import CorePrefabTransport
from jarvis.runtime.scene_view import CoreSceneTransport
from tests.fakes.prefabs import candidate
from tests.integration.test_scene_transport import CoreProcess


@pytest.fixture
async def core(tmp_path):
    process = CoreProcess(tmp_path)
    await process.start()
    try:
        yield process
    finally:
        await process.stop()


@pytest.fixture
async def prefabs(core, tmp_path):
    journal = RuntimeJournal(tmp_path / "runtime")
    tools = PrefabDisplayTools(CorePrefabTransport(CoreSessionTransport(
        host="127.0.0.1", port=core.port, token_file=core.token_file)), journal=journal)
    try:
        yield tools
    finally:
        await tools.close()


@pytest.fixture
async def display(core, prefabs, tmp_path):
    tools = SceneDisplayTools(CoreSceneTransport(host="127.0.0.1", port=core.port, token_file=core.token_file),
                              journal=prefabs.journal, prefabs=prefabs)
    try:
        yield tools
    finally:
        await tools.close()


def custom(prefab_id: str = "custom.counter", **changes) -> dict:
    return candidate("test.counter", id=prefab_id, **changes)


#: Défauts du schéma de `test.counter` (et de `custom.counter`) : Core stocke le bloc complété (reprise QA S04, A3).
PROPS_DEFAULTS = {"label": "Count", "accent": "#6ee7ff", "mode": "full"}
DATA_DEFAULTS = {"notes": "", "history": []}


def library_state(core: CoreProcess) -> list[tuple[str, int, int]]:
    """Chaque fichier de la bibliothèque de données : chemin relatif, taille, mtime (ns)."""

    root = core.data_root / "prefabs"
    if not root.exists():
        return []
    return sorted((str(path.relative_to(root)), path.stat().st_size, path.stat().st_mtime_ns)
                  for path in root.rglob("*") if path.is_file())


async def scene_object(core: CoreProcess, object_id: str) -> dict:
    status, body, _ = await core.request("GET", "/v1/scene/snapshot")
    assert status == 200
    return next(item for item in body["snapshot"]["objects"] if item["object_id"] == object_id)


async def record_user_turn(core: CoreProcess, text: str, *, minutes_ago: float = 0.0, turn: str = "t1") -> str:
    event = build_conversation_event(
        ConversationEventType.USER_TRANSCRIPT_ACCEPTED, producer=PRODUCER_VOICE_ADMISSION,
        conversation_id="conv-prefab", source_ids=(turn,), occurred_at=utc_now() - timedelta(minutes=minutes_ago),
        correlation_id=f"corr-{turn}", turn_id=f"turn-{turn}", content=text)
    [result] = await core.core.conversation_event_emitter.append_now([event])
    return event.event_id


def trace(tmp_path: Path) -> list[dict]:
    path = tmp_path / "runtime" / "trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


# ------------------------------------------------------------------ schémas stricts (vrai serveur, session MCP)

async def test_the_prefab_tools_refuse_unknown_arguments_and_shapes_before_sending(display, prefabs):
    from mcp.shared.memory import create_connected_server_and_client_session

    server = build_server(tools=display, prefabs=prefabs)
    async with create_connected_server_and_client_session(server) as session:
        listed = {tool.name: tool for tool in (await session.list_tools()).tools}
        for name in ("prefab_search", "prefab_get", "prefab_validate", "prefab_save", "prefab_edit_base", "prefab_events"):
            assert listed[name].inputSchema["additionalProperties"] is False, name
        assert listed["prefab_validate"].inputSchema["$defs"]["CandidateArg"]["additionalProperties"] is False
        assert listed["scene_create_object"].inputSchema["$defs"]["PrefabArg"]["additionalProperties"] is False
        assert listed["prefab_edit_base"].inputSchema["properties"]["confirmed_by_user"]["const"] is True

        unknown = await session.call_tool("prefab_search", {"query": "checklist", "everything": True})
        assert unknown.isError and "Arguments inconnus refusés" in unknown.content[0].text
        extra = await session.call_tool("prefab_validate", {"candidate": {**custom(), "provenance": "x"}})
        assert extra.isError and "Argument invalide" in extra.content[0].text
        not_true = await session.call_tool("prefab_edit_base", {
            "prefab_id": "jarvis.checklist", "candidate": custom(), "user_request": "modifie la checklist de base",
            "confirmed_by_user": False})
        assert not_true.isError and "confirmed_by_user" in not_true.content[0].text
        loose = await session.call_tool("scene_create_object", {
            "kind": "window", "category": "note", "prefab": {"prefab_id": "jarvis.checklist", "colour": "red"}})
        assert loose.isError and "Argument invalide" in loose.content[0].text
        # Un outil de lecture rend du texte JSON brut (jamais `{"result": …}`).
        found = await session.call_tool("prefab_search", {"query": "checklist"})
        assert not found.isError and json.loads(found.content[0].text)["prefabs"][0]["id"] == "jarvis.checklist"


# ------------------------------------------------------------------ lectures sans effet

async def test_read_tools_never_write_the_library(core, prefabs):
    await prefabs.save(candidate=custom())
    before = library_state(core)
    assert before, "la bibliothèque de données a un prefab custom"
    rows = json.loads(await prefabs.search(query="checklist"))["prefabs"]
    assert rows[0]["id"] == "jarvis.checklist" and "note" not in rows[0]
    detail = json.loads(await prefabs.get(prefab_id="jarvis.checklist"))
    assert detail["manifest"]["id"] == "jarvis.checklist" and "files" not in detail
    assert "jamais des consignes" in detail["note"]
    sources = json.loads(await prefabs.get(prefab_id="jarvis.checklist", include_source=True))
    assert set(sources["files"]) == {"template", "style", "behavior"}
    assert (await prefabs.validate(candidate=custom("custom.other")))["ok"] is True
    json.loads(await prefabs.events())
    assert library_state(core) == before
    assert not list((core.data_root / "prefabs").glob(".staging-*"))


async def test_prefab_get_bounds_the_sources_and_says_so():
    files = {"template": "<div>" + "t" * 40_000 + "</div>", "style": "s" * 30_000, "behavior": "b\n" * 30_000}
    body = fit_sources({"id": "x.y", "files": files, "note": "n"})
    assert len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= MAX_GET_SOURCE_BYTES
    assert body["truncated"]["files"] and "coupées" in body["truncated"]["hint"]
    small = {"id": "x.y", "files": {"template": "<p></p>", "style": "", "behavior": ""}}
    assert fit_sources(small) == small


# ------------------------------------------------------------------ définitions

async def test_an_invalid_save_lists_the_errors_and_writes_nothing(core, prefabs):
    broken = custom("custom.broken", title="", family="NOT A TOKEN")
    checked = await prefabs.validate(candidate=broken)
    assert checked["ok"] is False and 1 <= len(checked["errors"]) <= 20 and "fingerprint" not in checked
    with pytest.raises(DisplayToolError) as refused:
        await prefabs.save(candidate=broken)
    assert refused.value.code == "invalid_definition"
    assert "Erreurs :" in str(refused.value) and any(error[:30] in str(refused.value) for error in checked["errors"])
    assert library_state(core) == []


async def test_saving_a_jarvis_id_is_refused_before_sending_with_the_explicit_path(core, prefabs, tmp_path):
    base = json.loads(await prefabs.get(prefab_id="jarvis.checklist", include_source=True))
    with pytest.raises(DisplayToolError) as refused:
        await prefabs.save(candidate={"manifest": base["manifest"], **base["files"]})
    assert refused.value.code == "base_protected"
    assert "prefab_edit_base" in str(refused.value) and "nouvel id" in str(refused.value)
    assert "rien n'a été envoyé" in str(refused.value)
    assert library_state(core) == []
    assert any(entry["kind"] == "display.tool_refused" and entry["data"]["code"] == "base_protected"
               for entry in trace(tmp_path))


async def test_save_fork_and_revision_carry_core_provenance(prefabs, tmp_path):
    first = await prefabs.save(candidate=custom())
    assert first == {"prefab_id": "custom.counter", "version": 1, "origin": "custom",
                     "fingerprint": first["fingerprint"]}
    fork = await prefabs.save(candidate=custom("custom.counter_red"),
                              derived_from={"prefab_id": "custom.counter", "version": 1})
    assert fork["origin"] == "fork" and fork["derived_from"] == {"id": "custom.counter", "version": 1}
    revision = await prefabs.save(candidate=custom(title="Compteur v2"))
    assert (revision["version"], revision["origin"]) == (2, "revision")
    saved = [entry for entry in trace(tmp_path) if entry["kind"] == "display.prefab"
             and entry["data"]["tool"] == "prefab_save"]
    assert [(e["data"]["prefab_id"], e["data"]["version"], e["data"]["actor"]) for e in saved] == [
        ("custom.counter", 1, "brain"), ("custom.counter_red", 1, "brain"), ("custom.counter", 2, "brain")]


# ------------------------------------------------------------------ porte d'édition de base (témoin réel)

async def _base_candidate(prefabs: PrefabDisplayTools) -> dict:
    base = json.loads(await prefabs.get(prefab_id="jarvis.checklist", include_source=True))
    manifest = {**base["manifest"], "description": base["manifest"]["description"] + " Rouge."}
    return {"manifest": manifest, **base["files"]}


async def test_a_base_edit_without_the_users_words_is_refused(core, prefabs, tmp_path):
    wanted = await _base_candidate(prefabs)
    with pytest.raises(DisplayToolError) as refused:
        await prefabs.edit_base(prefab_id="jarvis.checklist", candidate=wanted,
                                user_request="modifie la checklist de base en rouge", confirmed_by_user=True)
    assert refused.value.code == "base_edit_unconfirmed" and "mots exacts" in str(refused.value)
    assert library_state(core) == []
    # Même avec un tour de l'utilisateur… qui ne dit pas cela, ou qui est trop ancien.
    await record_user_turn(core, "Affiche une checklist pour la release", turn="a")
    await record_user_turn(core, "Modifie la checklist de base en rouge", minutes_ago=45, turn="b")
    with pytest.raises(DisplayToolError):
        await prefabs.edit_base(prefab_id="jarvis.checklist", candidate=wanted,
                                user_request="modifie la checklist de base en rouge", confirmed_by_user=True)
    assert library_state(core) == []


async def test_a_base_edit_quoting_a_recent_user_turn_publishes_into_the_data_root(core, prefabs):
    event_id = await record_user_turn(core, "Jarvis, modifie le prefab de base checklist : accent rouge, s'il te plaît !")
    wanted = await _base_candidate(prefabs)
    published = await prefabs.edit_base(prefab_id="jarvis.checklist", candidate=wanted,
                                        user_request="modifie le prefab de base checklist — accent rouge",
                                        confirmed_by_user=True)
    assert published["origin"] == "base_edit" and published["version"] == 2
    assert published["derived_from"] == {"id": "jarvis.checklist", "version": 1}
    stored = json.loads((core.data_root / "prefabs" / "jarvis.checklist" / "2" / "publication.json").read_text("utf-8"))
    assert stored["provenance"]["base_edit"]["witness"] == f"conversation_event:{event_id}"
    # Le paquet livré n'est jamais écrit : la base éditée vit dans la racine de données.
    assert not (Path(core.core.prefabs._library._package_root) / "jarvis.checklist" / "2").exists()


async def _gate(prefabs: PrefabDisplayTools, request: str, prefab_id: str = "jarvis.checklist") -> tuple[str, object]:
    """Issue de la porte (vrai Core, vrais Conversation Events) : ("ACCEPTED", version) ou ("REFUSED", code)."""

    base = json.loads(await prefabs.get(prefab_id=prefab_id, include_source=True))
    wanted = {"manifest": {**base["manifest"], "description": base["manifest"]["description"] + " Rouge."},
              **base["files"]}
    try:
        published = await prefabs.edit_base(prefab_id=prefab_id, candidate=wanted, user_request=request,
                                            confirmed_by_user=True)
    except DisplayToolError as exc:
        return "REFUSED", exc.code
    return "ACCEPTED", published["version"]


async def test_a_quote_too_short_once_normalized_is_refused(core, prefabs):
    # Sonde QA P1 : 15 caractères bruts, « oui » une fois normalisé, sous-chaîne de « fouiller ».
    await record_user_turn(core, "Je vais fouiller le dossier des factures", turn="p1")
    assert await _gate(prefabs, "........... oui") == ("REFUSED", "base_edit_unconfirmed")
    assert library_state(core) == []


async def test_a_quote_that_does_not_name_the_prefab_is_refused(core, prefabs):
    # Sonde QA P2 : une confirmation générique, dite pour autre chose, ne nomme pas la checklist.
    await record_user_turn(core, "Oui je confirme, vas-y pour le rendez-vous de demain", turn="p2")
    assert await _gate(prefabs, "oui je confirme, vas-y pour le rendez-vous") == ("REFUSED", "base_edit_unconfirmed")
    assert library_state(core) == []


async def test_the_quote_matches_whole_words_in_the_real_journal(core, prefabs):
    await record_user_turn(core, "remodifie la checklist de base en rougeâtre", turn="wb")
    assert await _gate(prefabs, "modifie la checklist de base en rouge") == ("REFUSED", "base_edit_unconfirmed")
    await record_user_turn(core, "Bon : modifie la checklist de base en rouge.", turn="wb2")
    assert await _gate(prefabs, "modifie la checklist de base en rouge") == ("ACCEPTED", 2)


async def test_an_alias_names_the_prefab(core, prefabs):
    await record_user_turn(core, "Modifie la fenêtre de base, mets l'accent en rouge.", turn="win")
    assert await _gate(prefabs, "modifie la fenêtre de base, mets l'accent en rouge", "jarvis.window") == ("ACCEPTED", 2)


@pytest.mark.parametrize("event_type,producer", [
    (ConversationEventType.BRAIN_MESSAGE_PUBLISHED, "brain_service"),  # sonde QA P3
])
async def test_only_the_users_own_turn_witnesses_in_the_real_journal(core, prefabs, event_type, producer):
    text = "Modifie le prefab de base checklist en rouge s'il te plait"
    event = build_conversation_event(event_type, producer=producer, conversation_id="conv-prefab", source_ids=("b1",),
                                     occurred_at=utc_now(), correlation_id="corr-b1", outcome_id="out-b1", content=text)
    await core.core.conversation_event_emitter.append_now([event])
    assert await _gate(prefabs, text) == ("REFUSED", "base_edit_unconfirmed")


async def test_the_refusal_names_the_rule_and_forbids_a_retry(core, prefabs):
    await record_user_turn(core, "Affiche une checklist pour la release", turn="r")
    wanted = await _base_candidate(prefabs)
    with pytest.raises(DisplayToolError) as refused:
        await prefabs.edit_base(prefab_id="jarvis.checklist", candidate=wanted,
                                user_request="modifie la checklist de base en rouge", confirmed_by_user=True)
    text = str(refused.value)
    assert refused.value.code == "base_edit_unconfirmed"
    assert "personne ne réessaie" in text and "nomment ce prefab" in text and "prefab_save" in text
    # Trace S09 : un sous-agent a supposé que la vérification dépendait de l'appelant ; le cerveau a relancé.
    assert "quel que soit l'appelant (cerveau ou sous-agent)" in text


async def test_edit_base_only_targets_base_ids(prefabs):
    with pytest.raises(DisplayToolError) as refused:
        await prefabs.edit_base(prefab_id="custom.counter", candidate=custom(), user_request="x" * 20,
                                confirmed_by_user=True)
    assert refused.value.code == "invalid_argument" and "prefab_save" in str(refused.value)


# ------------------------------------------------------------------ instances (outils de scène)

async def test_create_with_a_prefab_and_no_version_pins_the_latest(core, display, prefabs):
    await prefabs.save(candidate=custom())
    await prefabs.save(candidate=custom(title="Compteur v2"))
    created = await display.create_object(kind="window", category="note", title="Compteur",
                                          prefab={"prefab_id": "custom.counter", "data": {"count": 3}})
    assert created["outcome"] == "applied" and created["prefab"] == {"id": "custom.counter", "version": 2}
    stored = await scene_object(core, created["object_id"])
    assert stored["payload"]["prefab"]["version"] == 2 and stored["payload"]["prefab"]["data"]["count"] == 3
    assert stored["representation"] == "window"


async def test_the_presentation_seam_stages_a_hidden_prefab_window_and_reveals_it_with_its_block(core, display):
    """Couture Presentation (`docs/prefabs.md` › *Consumers*, Slice 09) : une fenêtre prefab née masquée
    (`create_object(visibility="hidden")`, aucune image visible entre deux commandes), révélée par
    `update_object(visibility="visible")` — le bloc prefab traverse les deux écritures intact."""

    items = [{"id": "a", "label": "Diapo 1"}]
    created = await display.create_object(kind="window", category="presentation", title="Plan",
                                          visibility="hidden",
                                          prefab={"prefab_id": "jarvis.checklist", "data": {"items": items}})
    assert created["outcome"] == "applied" and created["prefab"] == {"id": "jarvis.checklist", "version": 1}
    staged = await scene_object(core, created["object_id"])
    assert staged["visibility"] == "hidden"
    block = staged["payload"]["prefab"]
    assert block["data"]["items"] == [{"id": "a", "label": "Diapo 1", "done": False}]
    await display.update_object(object_id=created["object_id"], visibility="visible")
    shown = await scene_object(core, created["object_id"])
    assert shown["visibility"] == "visible" and shown["payload"]["prefab"] == block


async def test_a_prefab_on_a_non_window_kind_is_refused_clearly(core, display):
    with pytest.raises(DisplayToolError) as refused:
        await display.create_object(kind="artifact", category="note", title="x",
                                    prefab={"prefab_id": "jarvis.checklist"})
    assert refused.value.code == "invalid_argument"
    assert "seulement sur une fenêtre (kind window)" in str(refused.value) and "artifact" in str(refused.value)
    note = await display.create_object(kind="artifact", category="note", title="note")
    with pytest.raises(DisplayToolError) as again:
        await display.update_object(object_id=note["object_id"], prefab={"prefab_id": "jarvis.checklist"})
    assert "seulement sur une fenêtre" in str(again.value)


async def test_scene_get_shows_the_pinned_and_the_latest_version(core, display, prefabs):
    await prefabs.save(candidate=custom())
    created = await display.create_object(kind="window", category="note", title="Compteur",
                                          prefab={"prefab_id": "custom.counter", "version": 1, "data": {"count": 4}})
    await prefabs.save(candidate=custom(title="Compteur v2"))
    body = json.loads(await display.get(object_ids=[created["object_id"]]))
    block = body["objects"][0]["prefab"]
    assert (block["id"], block["version"], block["latest_version"]) == ("custom.counter", 1, 2)
    assert block["props"] == PROPS_DEFAULTS and block["data"] == {"count": 4, **DATA_DEFAULTS}
    from jarvis.runtime.display_mcp import get_text_schema
    import jsonschema

    jsonschema.validate(body, get_text_schema())


async def test_updates_keep_the_block_replace_given_inputs_and_explain_refusals(core, display, prefabs):
    await prefabs.save(candidate=custom())
    await prefabs.save(candidate=custom(title="Compteur v2"))
    created = await display.create_object(kind="window", category="note", title="Compteur",
                                          prefab={"prefab_id": "custom.counter", "version": 1, "data": {"count": 2}})
    object_id = created["object_id"]
    # Changer le titre ne fait pas perdre le bloc prefab (régression de `_merged_payload`).
    await display.update_object(object_id=object_id, title="Compteur renommé")
    assert (await scene_object(core, object_id))["payload"]["prefab"]["data"] == {"count": 2, **DATA_DEFAULTS}
    # Même id sans version : la version de l'instance reste ; data donné remplace.
    updated = await display.update_object(object_id=object_id, prefab={"prefab_id": "custom.counter",
                                                                       "data": {"count": 7}})
    assert updated["prefab"] == {"id": "custom.counter", "version": 1}
    stored = (await scene_object(core, object_id))["payload"]["prefab"]
    assert stored["version"] == 1 and stored["data"] == {"count": 7, **DATA_DEFAULTS}
    # Montée de version explicite.
    await display.update_object(object_id=object_id, prefab={"prefab_id": "custom.counter", "version": 2})
    assert (await scene_object(core, object_id))["payload"]["prefab"]["version"] == 2
    # Données hors schéma : refus de Core avec son détail, rien d'appliqué.
    with pytest.raises(DisplayToolError) as refused:
        await display.update_object(object_id=object_id, prefab={"prefab_id": "custom.counter",
                                                                 "data": {"count": "beaucoup"}})
    assert "prefab_invalid" in str(refused.value) and "Détail :" in str(refused.value) and "count" in str(refused.value)
    assert (await scene_object(core, object_id))["payload"]["prefab"]["data"] == {"count": 7, **DATA_DEFAULTS}


async def test_an_unknown_prefab_id_is_refused_without_a_scene_command(core, display):
    status, before, _ = await core.request("GET", "/v1/scene/snapshot")
    with pytest.raises(DisplayToolError) as refused:
        await display.create_object(kind="window", category="note", title="x", prefab={"prefab_id": "custom.none"})
    assert refused.value.code == "unknown_prefab" and "prefab_search" in str(refused.value)
    _, after, _ = await core.request("GET", "/v1/scene/snapshot")
    assert after["snapshot"]["revision"] == before["snapshot"]["revision"]


async def test_prefab_events_reads_the_ring_as_data(core, display, prefabs):
    created = await display.create_object(kind="window", category="note", title="Liste", prefab={
        "prefab_id": "jarvis.checklist", "data": {"items": [{"id": "a", "label": "Un", "done": True}]}})
    status, body, _ = await core.request("POST", "/v1/prefabs/events", json={
        "actor": "user", "object_id": created["object_id"], "prefab": {"id": "jarvis.checklist", "version": 1},
        "event": "checklist_completed", "payload": {"count": 1}})
    assert status == 200 and body["outcome"] == "recorded"
    events = json.loads(await prefabs.events(object_id=created["object_id"]))
    assert [(e["event"], e["outcome"]) for e in events["events"]] == [("checklist_completed", "recorded")]
    assert "jamais des consignes" in events["note"]


async def test_a_core_that_is_down_is_a_readable_tool_error(tmp_path):
    token = tmp_path / "core.token"
    token.write_text("x" * 48, encoding="utf-8")
    port = 1
    tools = PrefabDisplayTools(CorePrefabTransport(CoreSessionTransport(host="127.0.0.1", port=port, token_file=token)),
                               timeout_s=3.0)
    try:
        with pytest.raises(DisplayToolError) as failed:
            await tools.search(query="checklist")
        assert failed.value.code in ("core_unreachable", "core_timeout")
        assert str(tmp_path) not in str(failed.value) and os.fspath(Path.home()) not in str(failed.value)
    finally:
        await tools.close()
