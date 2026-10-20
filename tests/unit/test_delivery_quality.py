"""Qualité de restitution d'un Mission Owner (handoff jarvis-organic-agent-orchestration, Slice 11).

Contrat : `docs/subagent-roles.md` §5bis, `docs/prefabs.md` « Consumers ». Politique pure
(`jarvis/domain/delivery_quality.py`), assemblage réel de la consigne par le hook (`routing_hook.run`), et repli
d'un affichage de prefab par les vrais outils d'affichage contre un vrai Core (`tests/integration` `CoreProcess`).
La reprise QA (B1, B2, N2 à N7) est couverte ici, sonde de la QA comprise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.domain import delivery_quality as dq
from jarvis.domain.agent_charter import REPORT_PARAGRAPH_END, sign_brief
from jarvis.domain.agent_orchestration import MISSION_MARK, MissionDecision, mission_brief
from jarvis.runtime import routing_hook
from jarvis.runtime.core_sessions import CoreSessionTransport
from jarvis.runtime.display_mcp import DisplayToolError, SceneDisplayTools
from jarvis.runtime.display_prefabs import PrefabDisplayTools
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.prefab_relay import CorePrefabTransport
from jarvis.runtime.scene_view import CoreSceneTransport
from tests.integration.test_scene_transport import CoreProcess

BASE = Path(__file__).resolve().parents[2] / "jarvis" / "prefabs" / "base"
#: Début du paragraphe de restitution lui-même (la marque est aussi citée par la charte et la méthode du rôle).
PARAGRAPH = f"{dq.DELIVERY_MARK}\nL'utilisateur ne lit pas votre compte rendu"


# ---------------------------------------------------------------- consigne de restitution


def test_the_delivery_brief_is_a_judgement_on_the_result_not_on_the_request():
    text = dq.delivery_brief()
    assert text.startswith(dq.DELIVERY_MARK)
    for needle in ("jugez sa forme sur lui, pas sur les mots de la demande", "une ou deux phrases",
                   "sans fenêtre", "état des lieux", "bilan", "audit", "liste d'actions",
                   "tout ce que l'utilisateur voudra relire", "jarvis.table", "jarvis.document", "jarvis.checklist",
                   dq.DISPLAY_TOOL, dq.SEARCH_TOOL, "ToolSearch", "object_id", "ne dites jamais affiché"):
        assert needle in text, needle
    lowered = text.lower()
    for forbidden in ("indice", "étape 1", "toujours", "obligatoirement", "complexité minimale", "au moins"):
        assert forbidden not in lowered


def test_no_keyword_heuristic_survives():
    # Arbitrage de l'agent 0 : la forme se juge sur le résultat ; l'indice par mots-clés est retiré.
    for name in ("classify_delivery", "DeliveryShape", "surface_for", "SURFACES"):
        assert not hasattr(dq, name), name


def test_every_real_bound_is_stated():
    text = dq.delivery_brief()
    for needle in (f"label ≤ {dq.TABLE_MAX_COLUMN_LABEL} car.", f"{dq.TABLE_MAX_COLUMNS} colonnes",
                   f"{dq.TABLE_MAX_ROWS} lignes", f"{dq.TABLE_MAX_CELLS_PER_ROW} cellules par ligne",
                   f"chaîne ≤ {dq.TABLE_MAX_CELL} car.", f"Markdown ≤ {dq.DOCUMENT_MAX_BODY} car.",
                   f"id ≤ {dq.CHECKLIST_MAX_ID} car.", f"label ≤ {dq.CHECKLIST_MAX_LABEL} car.",
                   f"note? ≤ {dq.CHECKLIST_MAX_NOTE} car.", f"{dq.CHECKLIST_MAX_ITEMS} éléments"):
        assert needle in text, needle


def _latest_data(prefab_id: str) -> dict:
    versions = sorted(int(path.name) for path in (BASE / prefab_id).iterdir() if path.name.isdigit())
    manifest = json.loads((BASE / prefab_id / str(versions[-1]) / "manifest.json").read_text(encoding="utf-8"))
    return manifest["inputs"]["data"]["properties"]


def test_the_stated_bounds_are_the_latest_shipped_manifests():
    table = _latest_data("jarvis.table")
    assert table["columns"]["max_items"] == dq.TABLE_MAX_COLUMNS
    assert table["columns"]["items"]["properties"]["label"]["max_length"] == dq.TABLE_MAX_COLUMN_LABEL
    assert table["rows"]["max_items"] == dq.TABLE_MAX_ROWS
    assert table["rows"]["items"]["max_items"] == dq.TABLE_MAX_CELLS_PER_ROW
    assert table["rows"]["items"]["items"] == {"type": "string", "max_length": dq.TABLE_MAX_CELL}
    assert _latest_data("jarvis.document")["body"]["max_length"] == dq.DOCUMENT_MAX_BODY
    checklist = _latest_data("jarvis.checklist")["items"]
    assert checklist["max_items"] == dq.CHECKLIST_MAX_ITEMS
    item = checklist["items"]["properties"]
    assert (item["id"]["max_length"], item["label"]["max_length"], item["note"]["max_length"]) == (
        dq.CHECKLIST_MAX_ID, dq.CHECKLIST_MAX_LABEL, dq.CHECKLIST_MAX_NOTE)


def test_the_mission_brief_opens_with_the_delivery_paragraph():
    text = mission_brief(MissionDecision(mission_owner=True, mission_id="m"))
    assert text.startswith(MISSION_MARK) and text.count(PARAGRAPH) == 1
    assert text.index(PARAGRAPH) < text.index("Le résultat et sa qualité vous appartiennent")
    assert text.rstrip().endswith("rien de ce que vous ne faites qu'envisager.")
    assert mission_brief(MissionDecision()) is None


def test_the_report_note_lands_right_after_the_charter_report_paragraph_once():
    signed = sign_brief(f"Consigne qui cite : {REPORT_PARAGRAPH_END}", report_note=dq.REPORT_NOTE)
    assert f"{REPORT_PARAGRAPH_END}\n{dq.REPORT_NOTE}" in signed and signed.count(dq.REPORT_NOTE) == 1
    assert signed.index(dq.REPORT_NOTE) < signed.index("--- consigne ---")
    assert dq.REPORT_NOTE not in sign_brief("Consigne.")
    assert sign_brief(signed, report_note=dq.REPORT_NOTE) == signed  # déjà signée : jamais doublée


# ---------------------------------------------------------------- assemblage par le vrai hook


def _call(description: str, prompt: str, *, tool_use_id: str = "toolu_S11", agent_id: str | None = None) -> dict:
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": tool_use_id, "session_id": "s1",
             "tool_input": {"description": description, "prompt": prompt, "subagent_type": "general-purpose"}}
    if agent_id:
        event["agent_id"] = agent_id
    return event


def _prompt(output: dict) -> str:
    return (output.get("hookSpecificOutput") or {}).get("updatedInput", {}).get("prompt", "")


@pytest.mark.parametrize("description", ["[general] [research-lead] Bilan", "[code] [coder] Corriger"])
def test_a_mission_owner_reads_one_consistent_rule_in_the_real_assembly_order(tmp_path, description):
    brief = _prompt(routing_hook.run(_call(description, "Fais un bilan de la migration."), tmp_path))
    order = [brief.index(REPORT_PARAGRAPH_END), brief.index(dq.REPORT_NOTE), brief.index("--- consigne ---"),
             brief.index(MISSION_MARK), brief.index(PARAGRAPH), brief.index("Le résultat et sa qualité")]
    assert order == sorted(order), order
    assert brief.index(dq.REPORT_NOTE) == brief.index(REPORT_PARAGRAPH_END) + len(REPORT_PARAGRAPH_END) + 1
    assert brief.count(PARAGRAPH) == 1 and brief.count(dq.REPORT_NOTE) == 1


def test_the_research_lead_report_rule_agrees_with_the_delivery(tmp_path):
    brief = _prompt(routing_hook.run(_call("[general] [research-lead] Bilan", "Fais un bilan."), tmp_path))
    report = brief[brief.index("COMPTE RENDU\n"):brief.index(MISSION_MARK)]
    assert "la synthèse s'affiche à l'écran" in report and "object_id et la conclusion" in report


def test_a_member_or_a_plain_agent_gets_neither_the_paragraph_nor_the_note(tmp_path):
    member = _prompt(routing_hook.run(_call("[code] [coder] Comparer", "Compare A et B.", tool_use_id="t2",
                                            agent_id="a1"), tmp_path))
    plain = _prompt(routing_hook.run(_call("[general] [research] Comparer", "Compare A et B.", tool_use_id="t3"),
                                     tmp_path))
    for text in (member, plain):
        assert PARAGRAPH not in text and dq.REPORT_NOTE not in text and REPORT_PARAGRAPH_END in text


# ---------------------------------------------------------------- repli : forme lisible


def test_a_table_falls_back_to_a_markdown_table():
    text = dq.readable_content("jarvis.table", {
        "columns": [{"label": "Option"}, {"label": "Coût", "align": "right"}],
        "rows": [["A | B", "3 €"], ["C"], ["D", "1 €", "extra"]]})
    lines = text.splitlines()
    assert lines[0] == "| Option | Coût |" and lines[1] == "|---|---|"
    assert lines[2] == "| A \\| B | 3 € |" and lines[3] == "| C |  |" and lines[4] == "| D | 1 € | extra |"


def test_a_document_falls_back_to_its_body_and_a_checklist_to_boxes():
    assert dq.readable_content("jarvis.document", {"body": "# Titre\n\nTexte."}) == "# Titre\n\nTexte."
    assert dq.readable_content("jarvis.checklist", {"items": [
        {"id": "a", "label": "Un", "done": True}, {"id": "b", "label": "Deux", "note": "détail"}]}) == \
        "- [x] Un\n- [ ] Deux — détail"


def test_another_prefab_falls_back_to_its_data_and_nothing_is_said_for_no_data():
    assert json.loads(dq.readable_content("custom.counter", {"count": 2})) == {"count": 2}
    assert dq.readable_content("jarvis.table", {}) is None and dq.readable_content("jarvis.table", None) is None
    assert json.loads(dq.readable_content("jarvis.table", {"rows": [["x"]]})) == {"rows": [["x"]]}


def test_the_fallback_content_is_bounded_and_says_so():
    text = dq.readable_content("jarvis.document", {"body": "x" * (dq.MAX_FALLBACK_CHARS + 500)})
    assert len(text) < dq.MAX_FALLBACK_CHARS + 100 and text.endswith(f"coupé à {dq.MAX_FALLBACK_CHARS} caractères]")


# ---------------------------------------------------------------- repli : l'état réel de l'écran (B1)


def test_a_refused_creation_says_nothing_new_is_on_screen():
    note = dq.fallback_note({"prefab_id": "jarvis.document", "data": {"body": "Rapport."}}, operation="create",
                            code="scene_refused")
    assert note.startswith(dq.FALLBACK_MARK) and "rien de nouveau n'est à l'écran" in note
    assert note.endswith("Rapport.")


def test_a_refused_update_says_the_window_keeps_its_previous_content():
    note = dq.fallback_note({"prefab_id": "jarvis.document", "data": {"body": "V2"}}, operation="update",
                            code="scene_refused", object_id="brain-window-1")
    assert "La mise à jour n'est pas appliquée : la fenêtre brain-window-1 garde son contenu précédent" in note
    assert "rien" not in note.split("\n")[1]


@pytest.mark.parametrize("code", sorted(dq.UNKNOWN_OUTCOME_CODES))
@pytest.mark.parametrize("operation", ["create", "update"])
def test_a_transport_failure_says_the_state_is_unknown(code, operation):
    note = dq.fallback_note({"prefab_id": "jarvis.table", "data": {}}, operation=operation, code=code,
                            object_id="brain-window-1")
    assert "L'état de l'affichage est inconnu" in note and "relisez la scène" in note
    assert "garde son contenu" not in note and "rien de nouveau" not in note


def test_the_fallback_note_is_neutral_toward_its_caller():
    # Reprise QA N5 : le serveur ne distingue pas le cerveau d'un sous-agent.
    note = dq.fallback_note({"prefab_id": "jarvis.table", "data": {"columns": [{"label": "A"}]}},
                            operation="create", code="scene_refused")
    assert "compte rendu" not in note.lower() and "à l'oral, résumez-le au lieu de le lire" in note


def test_the_retry_advice_does_not_contradict_the_scene_changed_hint():
    # Reprise QA N4 : la remarque `scene_changed` (« relis-la ») porte sur d'autres objets.
    note = dq.fallback_note({"prefab_id": "jarvis.table"}, operation="create", code="scene_refused")
    assert "scene_changed éventuelle ne concerne que d'autres objets" in note


@pytest.mark.parametrize("prefab", [{}, {"prefab_id": ""}, "n'importe quoi", None])
def test_an_argument_without_a_prefab_id_gets_a_clean_note(prefab):
    # Reprise QA N6 : plus de « fenêtre ? ».
    note = dq.fallback_note(prefab, operation="create", code="invalid_argument")
    assert "?" not in note.split("\n", 2)[2] and "ne nomme aucun prefab_id" in note and "Contenu prêt" not in note


# ---------------------------------------------------------------- repli : vrais outils contre un vrai Core


@pytest.fixture
async def core(tmp_path):
    process = CoreProcess(tmp_path)
    await process.start()
    try:
        yield process
    finally:
        await process.stop()


@pytest.fixture
async def display(core, tmp_path):
    journal = RuntimeJournal(tmp_path / "runtime")
    prefabs = PrefabDisplayTools(CorePrefabTransport(CoreSessionTransport(
        host="127.0.0.1", port=core.port, token_file=core.token_file)), journal=journal)
    tools = SceneDisplayTools(CoreSceneTransport(host="127.0.0.1", port=core.port, token_file=core.token_file),
                              journal=journal, prefabs=prefabs)
    try:
        yield tools
    finally:
        await tools.close()
        await prefabs.close()


def _trace(tmp_path: Path) -> list[dict]:
    path = tmp_path / "runtime" / "trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def _scene_object(core: CoreProcess, object_id: str) -> dict | None:
    _, body, _ = await core.request("GET", "/v1/scene/snapshot")
    return next((item for item in body["snapshot"]["objects"] if item["object_id"] == object_id), None)


NINE_COLUMNS = {"columns": [{"label": f"C{index}"} for index in range(9)], "rows": [["Secret 4291"] * 9]}


async def test_a_refused_table_returns_the_cause_and_a_readable_fallback(core, display, tmp_path):
    _, before, _ = await core.request("GET", "/v1/scene/snapshot")
    with pytest.raises(DisplayToolError) as refused:
        await display.create_object(kind="window", category="research", title="Comparatif",
                                    prefab={"prefab_id": "jarvis.table", "data": NINE_COLUMNS})
    message = str(refused.value)
    assert refused.value.code == "scene_refused" and "prefab_invalid" in message  # la vraie cause, gardée
    assert dq.FALLBACK_MARK in message and "rien de nouveau n'est à l'écran" in message
    assert "| C0 | C1 |" in message and "Secret 4291" in message
    _, after, _ = await core.request("GET", "/v1/scene/snapshot")
    assert after["snapshot"]["revision"] == before["snapshot"]["revision"]  # rien à l'écran
    events = _trace(tmp_path)
    assert [e["data"]["code"] for e in events if e["kind"] == "display.prefab_fallback"] == ["scene_refused"]
    assert any(e["kind"] == "display.tool_refused" for e in events)
    assert "4291" not in json.dumps(events)  # le journal ne garde jamais le contenu


async def test_update_fallback_on_a_displayed_window(core, display):
    # Sonde de la QA (B1), retournée : la note ne prétend plus que l'écran est vide.
    created = await display.create_object(kind="window", category="research", title="Rapport",
                                          prefab={"prefab_id": "jarvis.document", "data": {"body": "# V1 visible"}})
    object_id = created["object_id"]
    with pytest.raises(DisplayToolError) as refused:
        await display.update_object(object_id=object_id, prefab={"prefab_id": "jarvis.document",
                                                                 "data": {"body": "y" * 12001}})
    message = str(refused.value)
    assert "rien n'est à l'écran" not in message and "rien de nouveau" not in message
    assert f"la fenêtre {object_id} garde son contenu précédent" in message
    stored = await _scene_object(core, object_id)
    assert stored["payload"]["prefab"]["id"] == "jarvis.document"
    assert stored["payload"]["prefab"]["data"]["body"] == "# V1 visible"


async def test_an_unknown_prefab_on_update_also_falls_back(core, display):
    created = await display.create_object(kind="window", category="research", title="Rapport",
                                          prefab={"prefab_id": "jarvis.document", "data": {"body": "# V1"}})
    with pytest.raises(DisplayToolError) as refused:
        await display.update_object(object_id=created["object_id"], title="x",
                                    prefab={"prefab_id": "custom.none", "data": {"body": "Synthèse."}})
    assert refused.value.code == "unknown_prefab" and "garde son contenu précédent" in str(refused.value)
    assert str(refused.value).endswith("Synthèse.")


async def test_update_with_prefab_on_unknown_object(core, display):
    # Sonde de la QA (revérification) : aucune fenêtre sous ce nom, la note ne parle pas de « contenu précédent ».
    with pytest.raises(DisplayToolError) as refused:
        await display.update_object(object_id="brain-window-nope", prefab={"prefab_id": "jarvis.document",
                                                                           "data": {"body": "x"}})
    message = str(refused.value)
    assert refused.value.reason == "unknown_object"
    assert "Aucune fenêtre brain-window-nope n'existe" in message and "rien n'est affiché sous ce nom" in message
    assert "garde son contenu précédent" not in message and "inconnu" not in message.split(dq.FALLBACK_MARK)[1]
    assert await _scene_object(core, "brain-window-nope") is None


def test_an_archived_target_is_named_as_such():
    note = dq.fallback_note({"prefab_id": "jarvis.document"}, operation="update", code="scene_refused",
                            object_id="brain-window-1", reason="object_archived")
    assert "Aucune fenêtre brain-window-1 n'existe (elle est archivée)" in note


def test_the_unknown_outcome_codes_are_only_codes_a_create_or_update_can_raise():
    # `protocol_error` n'est levé que par un lot ; `core_refused` (toute erreur HTTP hors 400/413, 5xx compris)
    # reste inconnu : le statut ne remonte pas jusqu'à la note.
    assert "protocol_error" not in dq.UNKNOWN_OUTCOME_CODES and "core_refused" in dq.UNKNOWN_OUTCOME_CODES
    assert "command_not_sent" not in dq.UNKNOWN_OUTCOME_CODES


async def test_a_displayed_document_succeeds_without_any_fallback(core, display, tmp_path):
    created = await display.create_object(kind="window", category="research", title="Rapport",
                                          prefab={"prefab_id": "jarvis.document", "data": {"body": "# Rapport"}})
    assert created["object_id"].startswith("brain-window-") and created["prefab"]["id"] == "jarvis.document"
    assert not [e for e in _trace(tmp_path) if e["kind"] == "display.prefab_fallback"]


async def test_the_bound_holds_on_a_maximal_table(core, display):
    # Sonde de la QA : 9 colonnes × 64 lignes de 200 caractères.
    data = {"columns": [{"label": f"C{i}"} for i in range(9)], "rows": [["z" * 200] * 9 for _ in range(64)]}
    with pytest.raises(DisplayToolError) as refused:
        await display.create_object(kind="window", category="research", title="T",
                                    prefab={"prefab_id": "jarvis.table", "data": data})
    tail = str(refused.value).split("au lieu de le lire) :\n", 1)[1]
    assert len(tail) <= dq.MAX_FALLBACK_CHARS + 60


@pytest.mark.parametrize("prefab", [{}, {"prefab_id": "  "}, {"data": {"body": "x"}}])
async def test_an_empty_prefab_argument_is_refused_before_sending(core, display, prefab):
    # Reprise QA : rien n'est parti, donc un refus explicite (`invalid_argument`), jamais « état inconnu ».
    _, before, _ = await core.request("GET", "/v1/scene/snapshot")
    with pytest.raises(DisplayToolError) as refused:
        await display.create_object(kind="window", category="research", title="T", prefab=prefab)
    message = str(refused.value)
    assert refused.value.code == "invalid_argument" and "rien n'a été envoyé" in message
    assert "ne nomme aucun prefab_id" in message and "rien de nouveau n'est à l'écran" in message
    assert "inconnu" not in message and "fenêtre ?" not in message
    _, after, _ = await core.request("GET", "/v1/scene/snapshot")
    assert after["snapshot"]["revision"] == before["snapshot"]["revision"]


async def test_prefabs_out_of_reach_fall_back_and_a_plain_failure_is_untouched(core, tmp_path):
    tools = SceneDisplayTools(CoreSceneTransport(host="127.0.0.1", port=core.port, token_file=core.token_file),
                              journal=RuntimeJournal(tmp_path / "runtime"), prefabs=None)
    try:
        with pytest.raises(DisplayToolError) as unavailable:
            await tools.create_object(kind="window", category="note", title="x",
                                      prefab={"prefab_id": "jarvis.document", "data": {"body": "Corps."}})
        assert unavailable.value.code == "prefab_unavailable" and str(unavailable.value).endswith("Corps.")
        with pytest.raises(DisplayToolError) as plain:
            await tools.create_object(kind="agent", category="note", title="x")
        assert dq.FALLBACK_MARK not in str(plain.value)
        with pytest.raises(DisplayToolError) as plain_update:
            await tools.update_object(object_id="brain-window-nope", title="x")
        assert dq.FALLBACK_MARK not in str(plain_update.value)
    finally:
        await tools.close()


async def test_a_core_out_of_reach_says_the_display_state_is_unknown(tmp_path):
    token = tmp_path / "core.token"
    token.write_text("x" * 48, encoding="utf-8")
    prefabs = PrefabDisplayTools(CorePrefabTransport(CoreSessionTransport(host="127.0.0.1", port=1,
                                                                          token_file=token)), timeout_s=3.0)
    tools = SceneDisplayTools(CoreSceneTransport(host="127.0.0.1", port=1, token_file=token),
                              journal=RuntimeJournal(tmp_path / "runtime"), prefabs=prefabs)
    try:
        with pytest.raises(DisplayToolError) as failed:
            await tools.create_object(kind="window", category="note", title="x",
                                      prefab={"prefab_id": "jarvis.document", "data": {"body": "Corps."}})
        assert failed.value.code in dq.UNKNOWN_OUTCOME_CODES
        assert "L'état de l'affichage est inconnu" in str(failed.value)
    finally:
        await tools.close()
        await prefabs.close()
