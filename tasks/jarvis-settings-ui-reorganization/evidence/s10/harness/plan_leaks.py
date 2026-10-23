"""Plan 4 : cycle de vie. Minuteurs, écoutes globales et fetch instrumentés avant la page ; trois tournées complètes
des 25 sections, fermeture, attente, relevés comparés."""
import json, pathlib

S = pathlib.Path(__file__).resolve().parent.parent
INIT = r"""(()=>{
  const P=window.__probe={intervals:new Map(),timeouts:new Map(),listeners:new Map(),fetches:new Map(),log:[],seq:0,
    elListeners:0,elRemoved:0};
  const origin=()=>{const s=(new Error().stack||'').split('\n').slice(2,5).map(l=>l.trim().replace(/^at /,'').replace(/\(?https?:\/\/[^)]*\/([^/:)]*):(\d+):\d+\)?/,'@$1:$2')).join(' < ');return s.slice(0,200)};
  const si=window.setInterval,ci=window.clearInterval,st=window.setTimeout,ct=window.clearTimeout;
  window.setInterval=function(fn,ms,...a){const id=si.call(window,fn,ms,...a);P.intervals.set(id,{ms,origin:origin(),t:performance.now()});return id};
  window.clearInterval=function(id){P.intervals.delete(id);return ci.call(window,id)};
  window.setTimeout=function(fn,ms,...a){let id;const wrapped=typeof fn==='function'?function(){P.timeouts.delete(id);return fn.apply(this,arguments)}:fn;
    id=st.call(window,wrapped,ms,...a);if((ms||0)>=1000)P.timeouts.set(id,{ms,origin:origin(),t:performance.now()});return id};
  window.clearTimeout=function(id){P.timeouts.delete(id);return ct.call(window,id)};
  const ael=EventTarget.prototype.addEventListener,rel=EventTarget.prototype.removeEventListener;
  const key=(t,type,fn,opt)=>{const cap=typeof opt==='boolean'?opt:!!(opt&&opt.capture);return t===window?'window':t===document?'document':null};
  const reg=new WeakMap();
  EventTarget.prototype.addEventListener=function(type,fn,opt){const k=key(this);
    if(k&&fn){const cap=typeof opt==='boolean'?opt:!!(opt&&opt.capture);let m=reg.get(fn);if(!m){m=new Set();reg.set(fn,m)}const sig=k+'|'+type+'|'+cap;
      if(!m.has(sig)){m.add(sig);const id=k+'|'+type;const e=P.listeners.get(id)||{n:0,origins:{}};e.n++;const o=origin();e.origins[o]=(e.origins[o]||0)+1;P.listeners.set(id,e);
        if(opt&&opt.once){/* compté comme ajouté ; retiré au déclenchement non suivi */}}}
    else if(fn)P.elListeners++;
    return ael.call(this,type,fn,opt)};
  EventTarget.prototype.removeEventListener=function(type,fn,opt){const k=key(this);
    if(k&&fn){const cap=typeof opt==='boolean'?opt:!!(opt&&opt.capture);const m=reg.get(fn),sig=k+'|'+type+'|'+cap;
      if(m&&m.has(sig)){m.delete(sig);const e=P.listeners.get(k+'|'+type);if(e)e.n--}}
    else if(fn)P.elRemoved++;
    return rel.call(this,type,fn,opt)};
  const f=window.fetch;window.fetch=function(u,o){const id=++P.seq,path=String(u&&u.url||u).split('?')[0];
    P.fetches.set(id,{path,t:performance.now()});P.log.push({path,t:Math.round(performance.now()),open:!!(window.SET&&SET.open)});
    return f.apply(this,arguments).finally(()=>P.fetches.delete(id))};
  P.snap=label=>({label,t:Math.round(performance.now()),open:!!(window.SET&&SET.open),
    intervals:[...P.intervals.values()].map(v=>v.ms+'ms '+v.origin),
    longTimeouts:[...P.timeouts.values()].map(v=>v.ms+'ms '+v.origin),
    listeners:Object.fromEntries([...P.listeners.entries()].map(([k,v])=>[k,v.n])),
    inflight:[...P.fetches.values()].map(v=>v.path),elListeners:P.elListeners,elRemoved:P.elRemoved});
})();"""

CYCLE = r"""(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),R=window.JarvisSettingsRegistry;
  if(!SET.open){document.getElementById('dockMore').click();await pause(200);document.getElementById('openSettings').click();await pause(1200)}
  const perSection=[];
  for(const c of R.CATEGORY_IDS){for(const s of R.page.sections(c)){selectTab(s.id);await pause(s.id==='diagnostics'||s.id==='subagent_models'||s.id==='subagents'?1800:700);
    perSection.push({s:s.id,intervals:window.__probe.intervals.size})}}
  closeSettings();await pause(4000);
  return {perSection,snap:window.__probe.snap('after-cycle')}})()"""

acts = [
    {"a": "wait", "expr": "!!document.getElementById('openSettings')&&!!window.JarvisSettingsRegistry&&!!window.__probe", "timeoutMs": 15000},
    {"a": "sleep", "ms": 4000},
    {"a": "eval", "id": "s0", "expr": "window.__probe.snap('idle-before')"},
    {"a": "eval", "id": "c1", "expr": CYCLE},
    {"a": "eval", "id": "c2", "expr": CYCLE},
    {"a": "eval", "id": "c3", "expr": CYCLE},
    {"a": "sleep", "ms": 6000},
    {"a": "eval", "id": "s9", "expr": "window.__probe.snap('idle-after')"},
    {"a": "eval", "id": "fetchlog", "expr": "window.__probe.log"},
]
plan = {"init": INIT, "steps": [{"name": "leaks", "width": 1440, "height": 900, "settleMs": 2500, "actions": acts}]}
(S / "plan_leaks.json").write_text(json.dumps(plan), encoding="utf-8")
print("ok")
