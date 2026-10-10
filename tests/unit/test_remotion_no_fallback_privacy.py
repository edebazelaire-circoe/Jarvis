"""Release blockers of the Remotion handoff (Slice 22): NO FALLBACK and the PRIVACY BOUNDARY, verified, not claimed.

"Do not release when the no-fallback policy or the privacy boundary is unverified" (SLICE.md). This file is that verification:

1. No code path plays HTML for a Remotion document: the engine is durable and immutable, the scene-level gate refuses the other engine's
   scenes in both directions, nothing in the engine policy sits in an error handler, and the places that name Slidecar are an enumerated,
   reviewed list (a new one fails here until a person reads it).
2. No agent or MCP path selects an engine: no tool of ANY declared server exposes an engine, an actor or an experiment flag, and the
   Core refuses an agent that names one (even the default).
3. The privacy boundary: what the committed real-browser evidence says reaches the sinks (HTTP, TCP, UDP, DNS, WebRTC) on the Player,
   the render and the Studio paths, which channels are documented as OPEN, and that no committed file of the handoff keeps a home path, a
   user name, an address or a token (the privacy sweep of the handoff).
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import re

import pytest

from jarvis.runtime.mcp_catalog import build_introspection_server
from jarvis.runtime.mcp_tool_meta import SERVERS
from tests.fakes.remotion_player_stack import RemotionStack

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "tasks" / "jarvis-remotion-presentation-integration"
EVIDENCE = TASK / "slices" / "22-end-to-end-release" / "evidence"
BASE = "/v1/presentation-studio"


# ------------------------------------------------------------------ 1. no fallback

#: Files of the product that name the Slidecar engine as a value. Each was read in the Slice 22 review: they implement the policy (the
#: engine value, the selection rules, the human experiment, the ledger of Slidecar uses, the legacy default) and none of them substitutes
#: an engine for another. A new file in this list is a decision to review, not a refactor to wave through.
ENGINE_VALUE_FILES = {
    "jarvis/core/presentation_studio_engine_choice.py", "jarvis/core/presentation_studio_service.py", "jarvis/core/v2_app.py",
    "jarvis/domain/prefab_catalog.py", "jarvis/domain/presentation_studio_engine.py", "jarvis/domain/presentation_studio_engine_request.py",
    "jarvis/domain/remotion_controls.py",
}


def referencing_slidecar() -> dict[str, list[ast.AST]]:
    found: dict[str, list[ast.AST]] = {}
    for path in sorted((ROOT / "jarvis").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "SLIDECAR"]
        if hits:
            found[path.relative_to(ROOT).as_posix()] = hits
    return found


def test_the_files_that_name_the_slidecar_engine_are_the_reviewed_list():
    assert set(referencing_slidecar()) == ENGINE_VALUE_FILES


def test_no_error_handler_and_no_default_branch_of_the_engine_policy_ever_yields_slidecar():
    """A fallback is, by construction, `except ...: engine = SLIDECAR` or a default branch of the resolver. Neither exists."""

    for relative, hits in referencing_slidecar().items():
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        inside_handler = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                inside_handler.update(id(child) for child in ast.walk(node))
        leaked = [h.lineno for h in hits if id(h) in inside_handler]
        assert not leaked, f"{relative}:{leaked} names Slidecar inside an error handler"
    resolver = next(n for n in ast.walk(ast.parse((ROOT / "jarvis/domain/presentation_studio_engine.py").read_text(encoding="utf-8")))
                    if isinstance(n, ast.FunctionDef) and n.name == "resolve_engine")
    assert not [n for n in ast.walk(resolver) if isinstance(n, ast.Attribute) and n.attr == "SLIDECAR"], "resolve_engine reads only the asked engine"


def test_the_stage_never_mounts_an_html_document_for_a_remotion_scene_in_the_page_scripts():
    """The page-side counterpart: the Remotion frame code never creates an HTML `srcdoc` frame, and the HTML prefab host never loads a Remotion bundle."""

    runtime = ROOT / "jarvis" / "runtime"
    for name in runtime.glob("control_center_remotion_*.js"):
        assert "srcdoc" not in name.read_text(encoding="utf-8"), f"{name.name} builds an HTML srcdoc frame"
    host = (runtime / "control_center_prefab_host.js").read_text(encoding="utf-8")
    assert "remotion" in host.lower(), "the prefab host routes a Remotion pin to the Remotion frame"


async def test_the_scene_gate_refuses_the_other_engines_scenes_in_both_directions(tmp_path):
    """HTML scene into a Remotion document, and Remotion scene into a (legacy/experimental) Slidecar document: both refused, typed, nothing stored."""

    from tests.unit.test_remotion_player_realpage_browser import A, PROPS, SAMPLE, SCENE_TSX, S1, scene

    async with RemotionStack(tmp_path, runtime_dir=None) as stack:
        await stack.publish(A, {"src/Scene.tsx": SCENE_TSX}, title="Un", props=PROPS, sample=SAMPLE)
        pid, vid = await stack.presentation([scene(S1, A, "Premier")])
        variants = f"{BASE}/presentations/{pid}/variants/{vid}"
        _, variant = await stack.call("GET", variants)
        html_scene = {"scene_id": "pss_000000000009", "prefab": {"id": "jarvis.window", "version": 1}, "title": "HTML", "props": {}, "data": {}}
        status, refused = await stack.call("PUT", variants, json={
            "expected_revision": variant["revision"], "title": variant["title"], "scenes": variant["scenes"] + [html_scene],
            "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]})
        assert status == 409 and refused["error"]["code"] == "presentation_studio_engine_unsupported", refused
        assert (await stack.call("GET", variants))[1]["revision"] == variant["revision"], "nothing was stored"
        # the explicit human experiment makes a Slidecar document; a Remotion scene cannot enter it
        made = await stack.core.presentation_studio.create({"title": "Essai", "engine": "slidecar", "actor": "user", "experimental_confirmed": True,
                                                            "reason": "release gate"})
        assert made.presentation.engine.value == "slidecar"
        sid, sv = made.presentation.presentation_id, made.variants[0].to_document()
        status, refused = await stack.call("PUT", f"{BASE}/presentations/{sid}/variants/{sv['variant_id']}", json={
            "expected_revision": sv["revision"], "title": sv["title"], "scenes": [scene(S1, A, "Premier")],
            "art_direction_id": sv["art_direction_id"], "score_id": sv["score_id"]})
        assert status == 409 and refused["error"]["code"] == "presentation_studio_engine_unsupported", refused


async def test_an_agent_cannot_name_an_engine_even_the_default_nor_forge_a_human(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=None) as stack:
        for body in ({"title": "x", "engine": "remotion", "actor": "brain"}, {"title": "x", "engine": "slidecar", "actor": "brain"},
                     {"title": "x", "engine": "slidecar"}, {"title": "x", "engine": "remotion"},
                     {"title": "x", "engine": "slidecar", "actor": "system"}):
            status, refused = await stack.call("POST", BASE + "/presentations", json=body)
            assert status in (400, 403), (body, status, refused)
        listed = (await stack.call("GET", BASE + "/presentations"))[1]["presentations"]
        assert listed == [], "no refused request created a document"
        status, created = await stack.call("POST", BASE + "/presentations", json={"title": "Sans moteur nomme"})
        assert status == 201 and created["presentation"]["engine"] == "remotion", "an unnamed engine is the default, Remotion"


# ------------------------------------------------------------------ 2. no agent / MCP path selects an engine

FORBIDDEN_NAME = re.compile(r"^(engine|engines|actor|slidecar|experiment\w*|experimental\w*|renderer|runtime_kind|fallback\w*|html_fallback\w*)$", re.IGNORECASE)


def property_names(node, found=None):
    found = [] if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                found.extend(value)
            property_names(value, found)
    elif isinstance(node, list):
        for item in node:
            property_names(item, found)
    return found


def enum_values(node, found=None):
    found = [] if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "enum" and isinstance(value, list):
                found.extend(str(v) for v in value)
            enum_values(value, found)
    elif isinstance(node, list):
        for item in node:
            enum_values(item, found)
    return found


@pytest.mark.parametrize("server", [meta.server for meta in SERVERS])
async def test_no_tool_of_any_declared_mcp_server_exposes_an_engine_an_actor_or_a_fallback(server):
    tools = list(await build_introspection_server(server).list_tools())
    assert tools, server
    for tool in tools:
        for name in property_names(tool.inputSchema):
            assert not FORBIDDEN_NAME.match(name), f"{server}.{tool.name} exposes the parameter {name!r}"
        for value in enum_values(tool.inputSchema):
            assert not re.fullmatch(r"slidecar|html", value, re.IGNORECASE), f"{server}.{tool.name} offers {value!r} as a choice"


def test_the_sweep_would_catch_a_leak():
    """Mutation guard of the sweep itself."""

    leaked = {"properties": {"op": {"enum": ["a", "slidecar"]}, "details": {"properties": {"engine": {"type": "string"}}}}}
    assert any(FORBIDDEN_NAME.match(n) for n in property_names(leaked))
    assert any(re.fullmatch(r"slidecar|html", v) for v in enum_values(leaked))


def test_the_agent_modules_and_adapters_never_import_or_route_the_engine_policy():
    """By identifier (a docstring may say what the module does NOT do): no import, name or attribute of the engine policy."""

    forbidden = {"EngineSelectionPolicy", "POLICY", "resolve_engine", "SLIDECAR", "Engine", "EngineActor"}
    for relative in ("runtime/presentation_studio_mcp.py", "runtime/presentation_studio_mcp_tools.py", "runtime/presentation_studio_mcp_support.py",
                     "runtime/remotion_mcp.py", "runtime/remotion_mcp_tools.py", "adapters/control_center_brain.py"):
        tree = ast.parse((ROOT / "jarvis" / relative).read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {alias.name.split(".")[-1] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for alias in n.names}
        keys = {k.value for n in ast.walk(tree) if isinstance(n, ast.Dict) for k in n.keys if isinstance(k, ast.Constant)}
        assert not (names & forbidden), (relative, names & forbidden)
        assert "experimental_confirmed" not in keys and "engine" not in keys, relative


# ------------------------------------------------------------------ 3. the privacy boundary

def evidence_json(name: str) -> dict:
    path = EVIDENCE / name
    assert path.is_file(), f"{name}: the release evidence was not committed"
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_player_sandbox_evidence_shows_zero_hits_on_the_http_tcp_udp_dns_and_webrtc_sinks_with_negative_controls():
    d = evidence_json("real-isolation.json")
    assert d["verdict"] == "PASSED" and all(c.get("ok") for c in d["checks"].values())
    seen = d["channel_observations"]
    hardened = {k: v for k, v in seen.items() if k.endswith(("_direct", "_evasive")) and not k.startswith("link_hints")}
    assert hardened, "the hostile samples were observed at the sinks"
    for name, sink in hardened.items():
        assert sink["udp_packets"] == 0 and sink["tcp_connections"] == 0 and sink["dns_lookups_logged"] == 0, f"{name} reached a sink: {sink}"
    # the negative control: with the hardening removed the same probe DOES reach the UDP sink (the harness would see a leak)
    assert seen["abl_nohard_webrtc_exfil"]["udp_packets"] > 0 and seen["control_webrtc_exfil"]["udp_packets"] > 0


def test_the_documented_open_channel_is_still_open_in_the_evidence_and_is_named_in_the_contract():
    """Honesty check: `dns-prefetch` / `preconnect` are NOT closed (best effort). The evidence measures it; the contract and the release
    report must say it. If a future Chrome or CSP closes it, this test fails and the documents must be updated, never the other way round."""

    seen = evidence_json("real-isolation.json")["channel_observations"]
    assert seen["link_hints_evasive"]["dns_lookups_logged"] > 0 or seen["link_hints_evasive"]["tcp_connections"] > 0
    isolation = (ROOT / "docs" / "remotion-isolation.md").read_text(encoding="utf-8")
    assert "dns-prefetch" in isolation and "aucune couche ne le ferme" in isolation
    assert "Discipline des props" in isolation, "props and data given to a scene are readable by its code: the discipline is stated"
    release = (ROOT / "docs" / "remotion-integration-release.md").read_text(encoding="utf-8")
    for needle in ("dns-prefetch", "preconnect", "WebRTC", "props", "data"):
        assert needle in release, f"the release report does not state {needle!r}"


def test_the_render_evidence_shows_zero_local_http_tcp_and_udp_hits_and_a_counted_denied_egress():
    for name in ("real-render-hostile.json",):
        d = evidence_json(name)
        by = {c["check"]: c for c in d["checks"] if isinstance(c, dict)} if isinstance(d["checks"], list) else d["checks"]
        guarded = next(v for k, v in by.items() if "guarded: the local HTTP service received 0 requests" in k)
        assert guarded["ok"] is True and guarded["http"] == [] and guarded["tcp"] == 0 and guarded["udp"] == 0
        denied = next(v for k, v in by.items() if "denied requests are COUNTED" in k)
        assert denied["ok"] is True and all(n > 0 for n in denied["denied"].values())
        control = next(v for k, v in by.items() if k.startswith("negative control (browser arguments not rewritten)"))
        assert control["ok"] is True and control["http_hits"] > 0, "the harness sees a leak when the guard is removed"


def test_the_studio_evidence_names_what_it_covers_and_what_it_does_not():
    early = evidence_json("real-studio.json")
    assert early["verdict"] == "PASSED"
    studio_doc = (ROOT / "docs" / "remotion-studio.md").read_text(encoding="utf-8")
    assert "Ce que la CSP ne couvre pas" in studio_doc
    release = (ROOT / "docs" / "remotion-integration-release.md").read_text(encoding="utf-8")
    assert "same-origin" in release.lower() or "même origine" in release.lower(), "the Studio's lack of a sandbox is stated in the release report"


def load_sweep():
    path = EVIDENCE / "privacy_sweep.py"
    spec = importlib.util.spec_from_file_location("remotion_task_privacy_sweep", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_committed_file_of_the_handoff_keeps_a_home_path_a_user_name_an_email_or_a_token():
    sweep = load_sweep()
    assert sweep.TASK == TASK.resolve()
    assert sweep.extra_files(), "the sweep also reads the Remotion documents, scripts and tests outside the handoff folder"
    assert sweep.sweep() == {}


def test_the_sweep_sees_each_category_it_claims_to_refuse():
    sweep = load_sweep()
    home = Path.home()
    assert "<home>" in sweep.findings(f"chemin {home}\\Documents\\x.txt")
    assert "<home>" in sweep.findings(str(home).replace("\\", "\\\\") + "\\\\x")
    for name in sweep.user_names():
        assert "<user>" in sweep.findings(f"auteur : {name}.")
    assert any(hit.startswith("email") for hit in sweep.findings("écrire à quelqu.un@exemple.org"))
    assert "token" in sweep.findings("Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345")
    assert "token" in sweep.findings('{"token": "abcdefghijklmnop1234"}')
    assert sweep.findings("Authorization: Bearer ${token}") == []


def test_the_sweep_would_catch_a_leak_planted_in_an_evidence_file(tmp_path):
    sweep = load_sweep()
    (tmp_path / "evidence.json").write_text(json.dumps({"work_dir": f"{Path.home()}\\AppData\\Local\\Temp\\x"}), encoding="utf-8")
    assert sweep.sweep(tmp_path) == {"evidence.json": ["<home>", "<user>"]} or "evidence.json" in sweep.sweep(tmp_path)
