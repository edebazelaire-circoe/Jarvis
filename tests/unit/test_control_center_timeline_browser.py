"""La lane Tool Brain de la chronologie, mesurée dans un vrai navigateur (Slice 09 de jarvis-tool-brain-ui-orchestrator).

`test_control_center_timeline_js.py` prouve la logique pure sous node ; ici on charge la page **telle que
`ControlCenter.index` la sert** dans Chrome sans tête (le harnais CDP de `test_interaction_mode_hud_browser.py`), on
ouvre la chronologie par un vrai clic, et on relève des rectangles, des styles **calculés** et des noms
accessibles. Les routes `/api/conversations*` sont servies par un `fetch` de remplacement installé avant le module de
la page : il rend de **vrais évènements** (ceux que `ToolBrainEvents` écrit, ou le fixture doré), au format exact de
Core. C'est le seul niveau où « la cinquième colonne apparaît seulement s'il y a du Tool Brain » veut dire quelque chose.

Se saute proprement si Chrome ou node est absent ; ne se saute pas en silence si la page ne se compose pas.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.conversation_events import encode_conversation_event
from tests.unit.test_control_center_timeline_js import fixture_payloads, tool_brain_events
from tests.unit.test_interaction_mode_hud_browser import HARNESS, _chrome, _served_page, _shots, _wait

#: Remplace `fetch` pour les routes de conversation avant que le module de la page ne le capture.
STUB = r"""<script>(()=>{
  const DATA=__DATA__, real=window.fetch.bind(window);
  const json=body=>Promise.resolve(new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}}));
  window.fetch=(input,init)=>{
    /* La page est un fichier : sous Windows `/api/x` se résout en `file:///C:/api/x`, on retire la lettre de lecteur. */
    const url=new URL(String(input&&input.url||input),location.href),path=url.pathname.replace(/^\/[A-Za-z]:(?=\/)/,'');
    if(!path.startsWith('/api/conversations'))return real(input,init);
    if(path==='/api/conversations')return json({ok:true,summaries:[DATA.summary]});
    if(path==='/api/conversations/sessions')return json({ok:true,summaries:[]});
    if(path==='/api/conversations/events'){
      const after=Number(url.searchParams.get('after_sequence'))||0,rows=DATA.rows.filter(r=>r.sequence>after);
      const page={ok:true,events:rows,next_cursor:rows.length?rows[rows.length-1].sequence:after,has_more:false,skipped_rows:0};
      /* Long-poll sans rien de neuf : la page attend, comme avec Core. */
      return rows.length||!url.searchParams.get('wait_ms')?json(page):new Promise(done=>setTimeout(()=>done(json(page)),4000));
    }
    return json({ok:true,status:'no_trace_ref',event_id:'x',trace_ref:null,agent_task:null,scan:null});
  };
})()</script>"""

OPEN = [
    {"a": "click", "selector": "#openTimeline"},
    _wait("document.querySelectorAll('#tlItems .tl-e').length>0", 6000),
]
#: Ce que la page affiche de ses lanes : en-têtes visibles, compteurs, colonnes de la grille, entrées par lane.
LANES = """(()=>{
  const shown=[...document.querySelectorAll('#tlHeads .tl-hcell[data-lane]')].filter(c=>c.offsetWidth>0);
  const counts=Object.fromEntries([...document.querySelectorAll('#tlHeads [data-count]')].map(c=>[c.dataset.count,c.textContent]));
  const lanes=[...document.querySelectorAll('#tlCanvas .tl-lane')].filter(c=>c.offsetWidth>0).map(c=>c.dataset.lane);
  const entries={};
  for(const e of document.querySelectorAll('#tlItems .tl-e')){
    const lane=[...e.classList].find(c=>/^tl-(user|mouth|brain|tool_brain|subagent)$/.test(c));
    (entries[lane]=entries[lane]||[]).push(e.className);
  }
  const columns=getComputedStyle(document.getElementById('tlHeads')).gridTemplateColumns.split(' ').length;
  const cellWidths=Object.fromEntries(shown.map(c=>[c.dataset.lane,Math.round(c.getBoundingClientRect().width)]));
  return {shown:shown.map(c=>c.dataset.lane),lanes,counts,entries,columns,cellWidths};
})()"""


def _page(tmp_path: Path, payloads: list[dict]) -> Path:
    served = _served_page(tmp_path)
    rows = [{"sequence": index + 1, "recorded_at": event["occurred_at"], "event": event}
            for index, event in enumerate(payloads)]
    stamps = [event["occurred_at"] for event in payloads]
    data = {"summary": {"conversation_id": payloads[0]["conversation_id"], "event_count": len(rows),
                        "first_occurred_at": min(stamps), "last_occurred_at": max(stamps)}, "rows": rows}
    html = served.read_text(encoding="utf-8")
    assert "<head>" in html
    served.write_text(html.replace("<head>", "<head>" + STUB.replace("__DATA__", json.dumps(data)), 1), encoding="utf-8")
    return served


def _drive(page: Path, plan: list) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    done = subprocess.run([node, str(HARNESS), str(page), _chrome(), json.dumps(plan)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_conversation_without_tool_brain_keeps_its_four_lanes_in_a_real_browser(tmp_path):
    page = _page(tmp_path, fixture_payloads())
    plan = [{"width": 1440, "height": 900, "actions": [*OPEN, {"a": "eval", "expr": LANES}]}]
    seen = _drive(page, plan)[0]["actions"]
    assert seen[0]["a"] == "click" and seen[1]["ok"], "the timeline never rendered an entry: this test would prove nothing"
    lanes = seen[2]["value"]
    assert lanes["shown"] == ["user", "mouth", "brain", "subagent"]
    assert lanes["lanes"] == ["user", "mouth", "brain", "subagent"]
    assert lanes["columns"] == 5  # the ruler + the four lanes: the optional column is not in the grid
    assert "tool_brain" not in lanes["entries"]


def test_the_tool_brain_lane_appears_with_bars_dots_and_accessible_names(tmp_path):
    page = _page(tmp_path, [encode_conversation_event(e) for e in tool_brain_events()])
    shots = _shots(tmp_path)
    plan = [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        {"a": "eval", "expr": LANES},
        {"a": "eval", "expr": """(()=>{
          const bars=[...document.querySelectorAll('#tlItems .tl-tool_brain.tl-railbar')];
          const dots=[...document.querySelectorAll('#tlItems .tl-tool_brain.tl-dot')];
          const style=el=>{const s=getComputedStyle(el);return {border:s.borderTopStyle,color:s.borderTopColor,width:Math.round(el.getBoundingClientRect().width),height:Math.round(el.getBoundingClientRect().height)}};
          const byStatus=Object.fromEntries(bars.map(b=>[[...b.classList].find(c=>c.startsWith('st-')),{...style(b),tone:[...b.classList].find(c=>c.startsWith('is-')),label:b.getAttribute('aria-label')}]));
          const warnDot=dots.find(d=>d.classList.contains('is-warn')),inner=warnDot&&getComputedStyle(warnDot.querySelector('.tl-d'));
          return {bars:bars.length,dots:dots.length,byStatus,
            warnDot:warnDot?{label:warnDot.getAttribute('aria-label'),background:inner.backgroundColor}:null,
            dotLabels:dots.map(d=>d.getAttribute('aria-label'))};
        })()"""},
        {"a": "click", "selector": "#tlItems .tl-tool_brain.tl-railbar.st-cancelled"},
        _wait("!document.getElementById('tlDrawer').hidden && document.getElementById('tlDrawerBody').textContent.includes('Action du Tool Brain')", 5000),
        {"a": "eval", "expr": "document.getElementById('tlDrawer').textContent"},
        {"a": "ax", "selector": "#tlItems .tl-tool_brain.tl-railbar.st-failed"},
        {"a": "shot", "path": str(shots / "timeline-tool-brain.png")},
        {"a": "key", "key": "Escape"},
    ]}]
    seen = _drive(page, plan)[0]["actions"]
    assert seen[1]["ok"], "the timeline never rendered an entry"
    lanes = seen[2]["value"]
    assert lanes["shown"] == ["user", "mouth", "brain", "tool_brain", "subagent"] and lanes["columns"] == 6
    assert lanes["counts"]["tool_brain"] == "12"
    assert min(lanes["cellWidths"].values()) >= 100  # every lane stays readable next to the fifth
    measured = seen[3]["value"]
    assert measured["bars"] == 4 and measured["dots"] == 8
    by_status = measured["byStatus"]
    assert set(by_status) == {"st-completed", "st-cancelled", "st-invalidated", "st-failed"}
    # computed styles, not the stylesheet text: a cancelled/invalidated action is dashed, a failure is red, a success solid
    assert by_status["st-cancelled"]["border"] == "dashed" and by_status["st-invalidated"]["border"] == "dashed"
    assert by_status["st-completed"]["border"] == "solid" and by_status["st-completed"]["tone"] == "is-ok"
    assert by_status["st-failed"]["tone"] == "is-bad" and by_status["st-failed"]["color"] == "rgb(255, 101, 119)"
    assert all(bar["height"] >= 6 and bar["width"] >= 8 for bar in by_status.values())
    # colour never carries the meaning alone: every entry has an accessible name saying lane, kind, status and time
    assert "Tool Brain" in by_status["st-failed"]["label"] and "échec" in by_status["st-failed"]["label"]
    assert "scene_move" in by_status["st-failed"]["label"] and "Entrée pour le détail" in by_status["st-failed"]["label"]
    assert by_status["st-cancelled"]["label"].count("annulé") >= 1 and "speech_obsolete" in by_status["st-cancelled"]["label"]
    assert measured["warnDot"] and "repli" in measured["warnDot"]["label"] and measured["warnDot"]["background"] == "rgb(255, 184, 92)"
    # the drill-down opened by a real click names the action, its outcome and the causal ids
    drawer = seen[6]["value"]
    for expected in ("Tool Brain", "annulé", "speech_obsolete", "act-b", "scene_move", "c-1", "Statut"):
        assert expected.lower() in drawer.lower(), expected
    assert "object_ids" not in drawer and "attributes.dx" not in drawer  # arguments are never shown, only that they exist
    ax = seen[7]
    assert ax["role"] == "button" and "Tool Brain" in ax["name"] and "échec" in ax["name"]


def test_on_a_phone_the_lanes_scroll_inside_the_view_and_the_page_never_overflows(tmp_path):
    page = _page(tmp_path, [encode_conversation_event(e) for e in tool_brain_events()])
    plan = [{"width": 390, "height": 800, "actions": [
        *OPEN,
        {"a": "eval", "expr": "({doc:document.documentElement.scrollWidth,view:innerWidth,"
                              "lanes:[document.getElementById('tlScroll').scrollWidth,document.getElementById('tlScroll').clientWidth]})"},
    ]}]
    seen = _drive(page, plan)[0]["actions"]
    assert seen[1]["ok"]
    sizes = seen[2]["value"]
    assert sizes["doc"] == sizes["view"] == 390  # no horizontal page scroll
    assert sizes["lanes"][0] > sizes["lanes"][1]  # the five lanes keep their need and scroll inside the region
