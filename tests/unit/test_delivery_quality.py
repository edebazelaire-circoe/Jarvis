"""Qualité de restitution d'un Mission Owner (handoff jarvis-organic-agent-orchestration, Slice 11).

Contrat : `docs/subagent-roles.md` §5bis, `docs/prefabs.md` « Consumers ». Politique pure
(`jarvis/domain/delivery_quality.py`), assemblage de la consigne par le vrai hook (`routing_hook.run`), et repli
d'un affichage de prefab par les vrais outils d'affichage contre un vrai Core (`tests/integration` `CoreProcess`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.domain import delivery_quality as dq
from jarvis.domain.agent_orchestration import MISSION_MARK, MissionDecision, mission_brief
from jarvis.domain.delivery_quality import DeliveryShape, classify_delivery
from jarvis.runtime import routing_hook
from jarvis.runtime.core_sessions import CoreSessionTransport
from jarvis.runtime.display_mcp import DisplayToolError, SceneDisplayTools
from jarvis.runtime.display_prefabs import PrefabDisplayTools
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.prefab_relay import CorePrefabTransport
from jarvis.runtime.scene_view import CoreSceneTransport
from tests.integration.test_scene_transport import CoreProcess

BASE = Path(__file__).resolve().parents[2] / "jarvis" / "prefabs" / "base"


# ---------------------------------------------------------------- heuristique de forme


@pytest.mark.parametrize("text", [
    "Combien de fichiers Markdown y a-t-il dans docs/legacy ? Réponds par un nombre.",
    "Corrige la coquille du bouton Enregistrer.",
    "Quelle heure est-il à Tokyo ?",
    "La latence a-t-elle baissé par rapport à hier ?",  # « par rapport » n'est pas un rapport
    "Fais-le et rends-moi un compte rendu.",  # tout appelant demande un compte rendu : ce n'est pas une forme
    "",
])
def test_a_simple_request_stays_simple(text):
    assert classify_delivery(text) is DeliveryShape.SIMPLE


@pytest.mark.parametrize("text", [
    "Compare trois ORM Python sur la performance, la maturité et la licence.",
    "PostgreSQL versus SQLite pour JARVIS : lequel choisir ?",
    "Avantages et inconvénients de Remotion et de Motion Canvas",
    "Rédige un rapport comparatif des micros USB",  # comparaison avant rapport
    "Benchmark des modèles de transcription",
])
def test_a_comparison_prefers_a_table(text):
    assert classify_delivery(text) is DeliveryShape.COMPARISON
    assert dq.surface_for(DeliveryShape.COMPARISON).prefab_id == "jarvis.table"


@pytest.mark.parametrize("text", [
    "Écris un rapport sur l'état de la voix duplex.",
    "Fais une synthèse des retours utilisateur de la semaine.",
    "Recherche approfondie sur les licences des modèles de voix",
    "Une étude des coûts d'hébergement",
])
def test_a_serious_report_prefers_a_document(text):
    assert classify_delivery(text) is DeliveryShape.REPORT
    assert dq.surface_for(DeliveryShape.REPORT).prefab_id == "jarvis.document"


def test_a_checklist_request_prefers_the_checklist():
    assert classify_delivery("Prépare une checklist de mise en service") is DeliveryShape.CHECKLIST
    assert dq.surface_for(DeliveryShape.CHECKLIST).prefab_id == "jarvis.checklist"
    assert dq.surface_for(DeliveryShape.SIMPLE).prefab_id is None


def test_classify_never_raises_on_a_non_text():
    assert classify_delivery(None) is DeliveryShape.SIMPLE  # type: ignore[arg-type]


# ---------------------------------------------------------------- consigne de restitution


def test_the_delivery_brief_teaches_surfaces_display_and_fallback_without_a_template():
    text = dq.delivery_brief("")
    assert text.startswith(dq.DELIVERY_MARK)
    for needle in ("jarvis.table", "jarvis.document", "jarvis.checklist", dq.DISPLAY_TOOL, dq.SEARCH_TOOL,
                   "ToolSearch", "object_id", "ne dites pas", "Markdown structuré", "sans fenêtre ni document"):
        assert needle in text
    lowered = text.lower()
    for forbidden in ("étape 1", "toujours", "obligatoirement", "complexité minimale", "au moins"):
        assert forbidden not in lowered


def test_a_simple_request_gets_no_hint_toward_a_heavy_artifact():
    assert "Indice" not in dq.delivery_brief("Combien de fichiers dans docs ?")


@pytest.mark.parametrize(("request_text", "surface"), [
    ("Compare trois ORM", "jarvis.table"), ("Écris un rapport sur la voix", "jarvis.document"),
    ("Une checklist de mise en service", "jarvis.checklist")])
def test_a_shaped_request_gets_a_hint_that_leaves_the_judgement_to_the_owner(request_text, surface):
    hint = dq.delivery_brief(request_text).splitlines()[-1]
    assert hint.startswith("Indice :") and surface in hint and "sauf si le résultat réel tient en une phrase" in hint


def _manifest_data(prefab_id: str) -> dict:
    manifest = json.loads((BASE / prefab_id / "1" / "manifest.json").read_text(encoding="utf-8"))
    return manifest["inputs"]["data"]["properties"]


def test_the_stated_bounds_are_the_shipped_manifests():
    table = _manifest_data("jarvis.table")
    assert table["columns"]["max_items"] == dq.TABLE_MAX_COLUMNS
    assert table["columns"]["items"]["properties"]["label"]["max_length"] == dq.TABLE_MAX_COLUMN_LABEL
    assert table["rows"]["max_items"] == dq.TABLE_MAX_ROWS
    assert table["rows"]["items"]["items"]["max_length"] == dq.TABLE_MAX_CELL
    assert _manifest_data("jarvis.document")["body"]["max_length"] == dq.DOCUMENT_MAX_BODY
    assert _manifest_data("jarvis.checklist")["items"]["max_items"] == dq.CHECKLIST_MAX_ITEMS
    for shape, surface in dq.SURFACES.items():
        assert surface.shape is shape
        assert surface.prefab_id is None or (BASE / surface.prefab_id / "1" / "manifest.json").is_file()


def test_the_mission_brief_carries_the_delivery_paragraph_once_and_last():
    text = mission_brief(MissionDecision(mission_owner=True, mission_id="m"), request="Compare deux micros")
    assert text.startswith(MISSION_MARK) and text.count(dq.DELIVERY_MARK) == 1
    assert text.endswith(dq.delivery_brief("Compare deux micros"))
    assert mission_brief(MissionDecision(), request="Compare deux micros") is None


# ---------------------------------------------------------------- assemblage par le vrai hook


def _call(description: str, prompt: str, *, tool_use_id: str = "toolu_S11", agent_id: str | None = None) -> dict:
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": tool_use_id, "session_id": "s1",
             "tool_input": {"description": description, "prompt": prompt, "subagent_type": "general-purpose"}}
    if agent_id:
        event["agent_id"] = agent_id
    return event


def _prompt(output: dict) -> str:
    return (output.get("hookSpecificOutput") or {}).get("updatedInput", {}).get("prompt", "")


def test_a_mission_owner_receives_the_delivery_paragraph_with_the_hint_of_its_request(tmp_path):
    brief = _prompt(routing_hook.run(_call("[general] [research-lead] Comparatif ORM",
                                           "Compare SQLAlchemy, Peewee et Pony sur trois critères."), tmp_path))
    assert brief.count(dq.DELIVERY_MARK) == 1 and brief.index(MISSION_MARK) < brief.index(dq.DELIVERY_MARK)
    assert "Indice : la consigne ressemble à une comparaison" in brief


def test_the_hint_reads_the_callers_words_never_the_appended_blocks(tmp_path):
    # La charte, le rôle et la méthode apposés parlent de rapports et de comptes rendus : seul le texte de
    # l'appelant compte, et une demande simple ne reçoit aucun indice.
    brief = _prompt(routing_hook.run(_call("[code] [coder] Corriger la coquille", "Corrige la coquille du bouton."),
                                     tmp_path))
    assert dq.DELIVERY_MARK in brief and "Indice" not in brief


def test_a_member_or_a_plain_agent_gets_no_delivery_paragraph(tmp_path):
    member = _prompt(routing_hook.run(_call("[code] [coder] Comparer", "Compare A et B.", tool_use_id="t2",
                                            agent_id="a1"), tmp_path))
    plain = _prompt(routing_hook.run(_call("[general] [research] Comparer", "Compare A et B.", tool_use_id="t3"),
                                     tmp_path))
    assert dq.DELIVERY_MARK not in member and dq.DELIVERY_MARK not in plain


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


def test_the_fallback_note_never_pretends_and_survives_a_malformed_argument():
    note = dq.fallback_note({"prefab_id": "jarvis.document", "data": {"body": "Rapport."}})
    assert note.startswith(dq.FALLBACK_MARK) and "n'est pas affichée" in note and note.endswith("Rapport.")
    bare = dq.fallback_note("n'importe quoi")
    assert bare.startswith(dq.FALLBACK_MARK) and "Contenu prêt" not in bare


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


NINE_COLUMNS = {"columns": [{"label": f"C{index}"} for index in range(9)], "rows": [["Secret 4291"] * 9]}


async def test_a_refused_table_returns_the_cause_and_a_readable_fallback(core, display, tmp_path):
    _, before, _ = await core.request("GET", "/v1/scene/snapshot")
    with pytest.raises(DisplayToolError) as refused:
        await display.create_object(kind="window", category="research", title="Comparatif",
                                    prefab={"prefab_id": "jarvis.table", "data": NINE_COLUMNS})
    message = str(refused.value)
    assert refused.value.code == "scene_refused" and "prefab_invalid" in message  # la vraie cause, gardée
    assert dq.FALLBACK_MARK in message and "| C0 | C1 |" in message and "Secret 4291" in message
    _, after, _ = await core.request("GET", "/v1/scene/snapshot")
    assert after["snapshot"]["revision"] == before["snapshot"]["revision"]  # rien à l'écran
    events = _trace(tmp_path)
    assert [e["data"]["code"] for e in events if e["kind"] == "display.prefab_fallback"] == ["scene_refused"]
    assert any(e["kind"] == "display.tool_refused" for e in events)
    assert "4291" not in json.dumps(events)  # le journal ne garde jamais le contenu


async def test_an_unknown_prefab_also_falls_back(core, display):
    with pytest.raises(DisplayToolError) as refused:
        await display.update_object(object_id="brain-window-x", title="x",
                                    prefab={"prefab_id": "custom.none", "data": {"body": "Synthèse."}})
    assert refused.value.code == "unknown_prefab" and dq.FALLBACK_MARK in str(refused.value)
    assert str(refused.value).endswith("Synthèse.")


async def test_a_displayed_document_succeeds_without_any_fallback(core, display, tmp_path):
    created = await display.create_object(kind="window", category="research", title="Rapport",
                                          prefab={"prefab_id": "jarvis.document", "data": {"body": "# Rapport"}})
    assert created["object_id"].startswith("brain-window-") and created["prefab"]["id"] == "jarvis.document"
    assert not [e for e in _trace(tmp_path) if e["kind"] == "display.prefab_fallback"]


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
    finally:
        await tools.close()
