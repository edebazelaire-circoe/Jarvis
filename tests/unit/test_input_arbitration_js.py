"""Reprise de la main par la souris, modèle pur exécuté par node (orbital-ui Slice 03).

Contrat : D5 de `tasks/jarvis-board-orbital-ui-workspace-rail/docs/06-resolved-architecture.md`
et `docs/control-center-shell.md` › Selection method. Ce fichier épingle la
partie sans DOM de `control_center_input_arbitration.js` :

- `decide(state, event, params)` : seulement des événements réels (jamais un
  événement synthétique ni un `pointerId` Bare Hands 9001-9002), seulement en
  `active` ; un appui/clic/molette/menu reprend tout de suite ; le mouvement
  exige trajet ET net dans la fenêtre — propriétés vérifiées sur 10 000 tirages
  (tremblement de moyenne nulle, dérive lente) ; une transition par épisode,
  délai de grâce après un retour à Bare Hands ;
- la projection du cycle de vie (`methodOf`) et les deux niveaux du sous-arc
  (`selectionItems`, `bareHandsItems`) ;
- l'insertion dans la page servie, après la roue et le contrôle Bare Hands.

Le navigateur (vrais événements CDP, vrai moteur Bare Hands) est éprouvé par
`test_selection_method_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    BAREHANDS_HUD_SCRIPT_MARKER,
    ControlCenter,
    INPUT_ARBITRATION_SCRIPT_FILE,
    INPUT_ARBITRATION_SCRIPT_MARKER,
    TOOL_WHEEL_SCRIPT_MARKER,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
MODULE = RUNTIME / INPUT_ARBITRATION_SCRIPT_FILE
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
SEEDS = 10_000


def run(tmp_path: Path, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "arb.js"
    script.write_text(
        f"const M=require({json.dumps(str(MODULE))});\n"
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        # Générateur déterministe (mulberry32) : un tirage = une graine.
        "const rng=seed=>()=>{seed|=0;seed=seed+0x6D2B79F5|0;let t=Math.imul(seed^seed>>>15,1|seed);"
        "t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296};\n"
        # Un état en `active`, délai de grâce écoulé à t=0.
        "const active=()=>M.decide(M.initialState(),{type:'lifecycle',lifecycle:'active',t:-100000}).state;\n"
        "const feed=(events,state,params)=>{let s=state||active();const took=[];"
        "for(const e of events){const r=M.decide(s,e,params||M.DEFAULTS);s=r.state;if(r.takeover)took.push({...r.takeover,t:e.t})}"
        "return {s,took}};\n"
        "const mv=(t,x,y,extra)=>({type:'pointermove',t,x,y,trusted:true,...(extra||{})});\n"
        + body,
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                          timeout=300, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------ critères d'acceptation


def test_click_takes_over_immediately(tmp_path):
    v = run(tmp_path, """
      const kinds=['pointerdown','click','wheel','contextmenu'];
      out(kinds.map(type=>feed([{type,t:10,x:5,y:5,trusted:true}]).took));""")
    for took in v:
        assert len(took) == 1 and took[0]["reason"] == "click"
        assert took[0]["window_ms"] == 400
    assert [t[0]["input"] for t in v] == ["pointerdown", "click", "wheel", "contextmenu"]


def test_untrusted_or_bh_pointer_id_ignored(tmp_path):
    v = run(tmp_path, """
      const ids=[C.pointerIdForSlot(0),C.pointerIdForSlot(1)];
      const bh=ids.map(id=>C.isBareHandsPointerId(id));
      const synthetic=feed([{type:'pointerdown',t:10,trusted:false},{type:'click',t:20,trusted:false},
        ...Array.from({length:40},(_,i)=>mv(30+i*5,i*20,0,{trusted:false}))]).took;
      const hand=feed([{type:'pointerdown',t:10,trusted:true,bareHands:true},
        ...Array.from({length:40},(_,i)=>mv(30+i*5,i*20,0,{bareHands:true}))]).took;
      out({ids,bh,synthetic,hand});""")
    assert v["ids"] == [9001, 9002] and v["bh"] == [True, True]
    assert v["synthetic"] == [] and v["hand"] == []


def test_jitter_below_net_threshold_never_takes_over(tmp_path):
    """Propriété : 10 000 marches aléatoires de moyenne nulle, bornées dans un
    disque de rayon < netPx/2 (une souris posée qui tremble), à cadence et
    réglages tirés au hasard : jamais une reprise. Le net entre deux points du
    disque est < netPx, donc c'est vrai par construction — c'est ce que le test
    vérifie, et non une chance."""

    v = run(tmp_path, f"""
      let worst=0,events=0,fails=[];
      for(let seed=1;seed<={SEEDS};seed+=1){{
        const r=rng(seed);
        const params=M.normalizeParams({{distancePx:24+Math.floor(r()*80),windowMs:150+Math.floor(r()*600)}});
        const p=M.normalizeParams({{netPx:Math.max(2,Math.floor(params.distancePx*(0.3+0.6*r())))}},params);
        const radius=(p.netPx/2)*(0.2+0.79*r());
        let x=0,y=0,t=0,s=active(),took=0;
        const n=50+Math.floor(r()*250);
        for(let i=0;i<n;i+=1){{
          t+=1+Math.floor(r()*16);
          x+=(r()-.5)*radius;y+=(r()-.5)*radius;           // pas de moyenne nulle
          const d=Math.hypot(x,y);if(d>radius){{x*=radius/d;y*=radius/d}}  // tenu dans le disque
          const out=M.decide(s,mv(t,x,y),p);s=out.state;events+=1;
          if(out.takeover){{took+=1;fails.push({{seed,p,radius}});break}}
          worst=Math.max(worst,s.samples.length?M.measure(s.samples).net/p.netPx:0);
        }}
      }}
      out({{fails:fails.slice(0,5),worst,events}});""")
    assert v["fails"] == [], v["fails"]
    assert v["worst"] < 1 and v["events"] > SEEDS * 50


def test_slow_drift_outside_window_never_takes_over(tmp_path):
    """Propriété : une dérive lente (vitesse < distancePx / windowMs), dans une
    direction tirée au hasard et sur une longue distance — le pointeur finit à
    des centaines de pixels —, ne reprend jamais : dans la fenêtre, le trajet
    n'atteint pas le seuil."""

    v = run(tmp_path, f"""
      let fails=[],far=0;
      for(let seed=1;seed<={SEEDS};seed+=1){{
        const r=rng(seed);
        const p=M.DEFAULTS;
        const speed=(p.distancePx/p.windowMs)*(0.1+0.85*r());   // px/ms
        const a=r()*2*Math.PI;let t=0,x=0,y=0,s=active();
        for(let i=0;i<400;i+=1){{
          const dt=2+Math.floor(r()*20);t+=dt;x+=Math.cos(a)*speed*dt;y+=Math.sin(a)*speed*dt;
          const out=M.decide(s,mv(t,x,y),p);s=out.state;
          if(out.takeover){{fails.push({{seed,speed}});break}}
        }}
        far=Math.max(far,Math.hypot(x,y));
      }}
      out({{fails:fails.slice(0,5),far}});""")
    assert v["fails"] == [], v["fails"]
    assert v["far"] > 300


def test_deliberate_move_takes_over_once_and_resets(tmp_path):
    v = run(tmp_path, """
      const sweep=Array.from({length:12},(_,i)=>mv(100+i*10,i*15,0));       // 165 px en 110 ms
      const more=Array.from({length:12},(_,i)=>mv(300+i*10,200+i*15,0));
      const r=feed([...sweep,...more,{type:'pointerdown',t:500,trusted:true}]);
      // Le cycle de vie suit (off), puis Bare Hands revient : un nouvel épisode.
      let s=M.decide(r.s,{type:'lifecycle',lifecycle:'off',t:600}).state;
      s=M.decide(s,{type:'lifecycle',lifecycle:'active',t:700}).state;
      const again=feed([...Array.from({length:12},(_,i)=>mv(3000+i*10,i*15,0))],s);
      out({took:r.took,pending:r.s.pending,samples:r.s.samples.length,again:again.took});""")
    took = v["took"]
    assert len(took) == 1 and took[0]["reason"] == "movement"
    assert took[0]["distance_px"] >= 48 and took[0]["net_px"] >= 24 and took[0]["window_ms"] == 400
    # Une transition par épisode, accumulateur remis à zéro.
    assert v["pending"] is True and v["samples"] == 0
    assert len(v["again"]) == 1


def test_no_transition_when_not_active(tmp_path):
    v = run(tmp_path, """
      const states=['off','sleep','error','starting'];
      out(states.map(l=>{
        const s=M.decide(M.initialState(),{type:'lifecycle',lifecycle:l,t:-100000}).state;
        return feed([{type:'pointerdown',t:10,trusted:true},{type:'click',t:20,trusted:true},
          ...Array.from({length:30},(_,i)=>mv(30+i*5,i*20,0))],s).took.length}));""")
    assert v == [0, 0, 0, 0]


def test_cooldown_after_explicit_bare_hands(tmp_path):
    v = run(tmp_path, """
      // Retour explicite à Bare Hands à t=1000 : le cycle de vie atterrit en `active` à t=1200.
      let s=M.decide(M.initialState(),{type:'explicit',method:'bare_hands',t:1000}).state;
      s=M.decide(s,{type:'lifecycle',lifecycle:'active',t:1200}).state;
      const during=feed([{type:'pointerdown',t:1300,trusted:true},
        ...Array.from({length:12},(_,i)=>mv(1400+i*10,i*20,0))],s);
      const after=feed([{type:'pointerdown',t:2800,trusted:true}],during.s);
      // Réglable : sans délai de grâce, la même souris reprend tout de suite.
      const p=M.normalizeParams({cooldownMs:0});
      let z=M.decide(M.initialState(),{type:'lifecycle',lifecycle:'active',t:1200},p).state;
      const none=feed([{type:'pointerdown',t:1300,trusted:true}],z,p);
      out({until:s.cooldownUntil,during:during.took,after:after.took,none:none.took});""")
    assert v["until"] == 1200 + 1500
    assert v["during"] == []
    assert len(v["after"]) == 1 and v["after"][0]["reason"] == "click"
    assert len(v["none"]) == 1


# ------------------------------------------------------------ réglages, projection, sous-arcs


def test_params_are_tunable_and_refuse_nonsense(tmp_path):
    v = run(tmp_path, """
      const codes=[];for(const bad of [{distancePx:-1},{windowMs:'x'},{netPx:100,distancePx:48},{nope:1}]){
        try{M.normalizeParams(bad)}catch(e){codes.push(e.code)}}
      out({d:M.DEFAULTS,ok:M.normalizeParams({distancePx:80,netPx:40}),codes});""")
    assert v["d"] == {"distancePx": 48, "netPx": 24, "windowMs": 400, "cooldownMs": 1500}
    assert v["ok"]["distancePx"] == 80 and v["ok"]["netPx"] == 40
    assert v["codes"] == ["input_arbitration_bad_param"] * 3 + ["input_arbitration_unknown_param"]


def test_projection_follows_the_lifecycle_table(tmp_path):
    v = run(tmp_path, """
      out({off:M.methodOf({lifecycle:'off'}),sleep:M.methodOf({lifecycle:'sleep'}),
        active:M.methodOf({lifecycle:'active'}),starting:M.methodOf({lifecycle:'off',starting:true},7.4),
        error:M.methodOf({lifecycle:'error',code:'camera_denied',title:'Caméra refusée'}),none:M.methodOf(null),
        items:M.selectionItems(M.methodOf({lifecycle:'error',code:'camera_denied'}))});""")
    assert v["off"]["method"] == "mouse" and v["none"]["method"] == "mouse"
    assert v["sleep"]["method"] == v["active"]["method"] == "bare_hands"
    assert v["starting"]["method"] == "bare_hands" and v["starting"]["tone"] == "wait"
    assert "7 s" in v["starting"]["text"] and "Souris pour annuler" in v["starting"]["note"]
    # Une panne n'est jamais montrée comme Souris, et dit sa cause.
    assert v["error"]["method"] == "bare_hands" and v["error"]["tone"] == "error"
    assert "camera_denied" in v["error"]["text"] and "camera_denied" in v["error"]["note"]
    items = v["items"]
    assert [(i["id"], i["label"], i["checked"]) for i in items] == [("mouse", "Souris", False),
                                                                     ("bare_hands", "Bare Hands", True)]
    assert items[1]["tone"] == "error"


def test_bare_hands_items_follow_installed_tools_and_quick_refusals(tmp_path):
    v = run(tmp_path, """
      const tools=[...C.describeTools(),{id:'ink',label:'Encre',installed:false,reason:'barehands_tool_not_installed'}];
      const quick=[{act:'calibration',label:'Calibrer… — Bare Hands est éteint : choisissez Veille ou Actif d’abord.',
        note:'barehands_calibration_lifecycle_off'},{act:'help',label:'Aide · Gestes…'}];
      out(M.bareHandsItems({tools,tool:'pan',lifecycle:'sleep',quick}));""")
    assert [i["id"] for i in v] == ["tool:pointer", "tool:pan", "tool:select", "tool:ink",
                                    "sleep", "help", "diagnostics", "calibration"]
    assert [i.get("checked") for i in v[:4]] == [False, True, False, False]
    assert v[3]["disabled"] is True and v[3]["detail"] == "barehands_tool_not_installed"
    assert v[4]["note"] == "en cours"
    cal = v[-1]
    assert cal["disabled"] is True and "choisissez Veille ou Actif" in cal["detail"]
    assert v[5]["disabled"] is False


async def test_inserted_after_the_wheel_and_the_hud_in_the_served_page(tmp_path):
    page = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    order = [page.index(m) for m in (BAREHANDS_HUD_SCRIPT_MARKER, TOOL_WHEEL_SCRIPT_MARKER,
                                     INPUT_ARBITRATION_SCRIPT_MARKER)]
    assert order == sorted(order)
    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    assert INPUT_ARBITRATION_SCRIPT_MARKER not in served
    source = MODULE.read_text(encoding="utf-8")
    assert source in served
    # Aucun réseau ; une seule minuterie, le compteur du démarrage.
    assert "fetch(" not in source and source.count("setInterval(") == 1
    # Rien n'est empêché : la reprise n'avale jamais le clic qui la déclenche.
    assert "preventDefault" not in source and "stopPropagation" not in source
