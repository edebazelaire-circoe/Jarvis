"""Fixture déterministe de `/api/memory/*` pour les tests navigateur de la mémoire (refonte-ui-settings, Slices 05/06).

Le Control Center isolé des tests (`served`) n'a pas de Core : ses routes `/api/memory/*` répondent `core_unavailable`.
`MEMORY_STUB` remplace, DANS la page, le `fetch` de ces seules routes par des réponses de la forme exacte de Core
(`jarvis/protocol/memory_routes.py`) : notes, recherche, état des étages, candidats, décisions, test de rappel. Les
autres routes (`/api/settings`…) restent réelles. Rien n'est inventé côté produit : ce sont des données de test.

Réglages du faux Core (avant `MEMORY_STUB`, par `window.__memStub = {...}`) :
- `notes` : nombre de notes (défaut 23) ; `cands` : nombre de candidats proposés (défaut 4) ;
- `down` : `true` -> toutes les routes mémoire répondent 503 `core_unavailable` (état dégradé) ;
- `refuse` : `true` -> une décision de candidat répond 409 `memory_conflict_revision` ;
- `delay` : délai (ms) des réponses, pour voir les états de chargement ;
- `tencent` : état publié de l'étage Tencent (`ok`, `degraded`, `unavailable`…) ; absent -> `disabled`.
Chaque requête mémoire est notée dans `window.__memCalls` (`[méthode, chemin+requête, corps]`).
"""

from __future__ import annotations

import json

from jarvis.domain.knowledge import AssetKind

#: Étages de connaissance tels que Core les publie (`knowledge:<AssetKind>`, `memory_wiring.register_knowledge`) :
#: dérivés de l'énumération, pour qu'un écart de clé côté interface ne puisse pas passer. Le graphe de code n'a pas
#: de fournisseur monté, comme dans une installation sans dépôt branché : Core ne le déclare pas.
KNOWLEDGE_LEGS = {f"knowledge:{kind.value}": {"status": "ok", "reason_code": None, "reason": ""}
                  for kind in AssetKind if kind is not AssetKind.CODEGRAPH}

MEMORY_STUB = r"""(()=>{
  const cfg=Object.assign({notes:23,cands:4,down:false,refuse:false,delay:30},window.__memStub||{});
  window.__memCalls=[];
  const KINDS=['preference','fact','scenario','profile','episode'],LEVELS=['L1','L2','L3','L2','L1'];
  const RET=['long_term_memory','long_term_memory','eternal_memory','short_term_memory','plastic_memory'];
  const SUBJECTS=['préfère des réponses concises avec des exemples concrets','travaille sur un projet d’agent IA pour la productivité',
    'utilise principalement Visual Studio Code','est basé en France','s’intéresse à l’IA et à l’automatisation',
    'veut des interfaces modernes et lisibles','prépare une présentation sur les agents','cite OpenAI, Claude et Gemini comme outils favoris'];
  const pad=n=>String(n).padStart(2,'0');
  const notes=Array.from({length:cfg.notes},(_,i)=>({id:'n'+(i+1),title:'Vous '+SUBJECTS[i%SUBJECTS.length]+(i>=SUBJECTS.length?' ('+(i+1)+')':''),
    level:LEVELS[i%5],kind:KINDS[i%5],retention:RET[i%5],scope:i%4===3?'project:jarvis':i%3===2?'shared':'private',revision:1+(i%3),
    created_at:`2026-10-${pad(20-(i%19))}T09:${pad(i%60)}:00`,updated_at:`2026-10-${pad(23-(i%22))}T1${i%10}:${pad((i*7)%60)}:00`,
    valid_from:null,valid_to:null,confidence:Math.round((0.95-(i%7)*0.04)*100)/100,agent:'brain',superseded_by:null,supersedes:[],contradicts:i===2?['n9']:[],
    sources:[{type:'turn',ref:'turn-'+(100+i),at:`2026-10-${pad(20-(i%19))}T09:00:00`}],excerpt:'Note de test numéro '+(i+1)+'.',
    body:'# Note '+(i+1)+'\nVous '+SUBJECTS[i%SUBJECTS.length]+'.'}));
  const CANDS=['Vous semblez travailler sur plusieurs maquettes UI pour JARVIS','Vous préférez un style visuel futuriste avec un thème bleu',
    'Vous souhaitez une cohérence globale entre les pages de réglages','Vous testez souvent le rappel avant une démonstration',
    'Vous relisez les candidats le matin'];
  let cands=Array.from({length:cfg.cands},(_,i)=>({id:'c'+(i+1),title:CANDS[i%CANDS.length],state:'proposed',level:'L1',kind:i%2?'preference':'scenario',
    retention:'long_term_memory',scope:'private',confidence:Math.round((0.82-i*0.05)*100)/100,created_at:`2026-10-2${i%4}T08:30:00`,conflicts:i===1?['n6']:[],
    decided_by:null,decided_at:null,committed_memory_id:null,sources:[{type:'session',ref:'s-'+(i+1),at:'2026-10-20T08:30:00'}],
    excerpt:'Proposition de test '+(i+1)+'.',body:'Proposition de test '+(i+1)+'.'}));
  const json=(body,status)=>new Response(JSON.stringify(body),{status:status||200,headers:{'Content-Type':'application/json'}});
  const refuse=(status,code,message)=>json({error:{code,message}},status);
  const later=v=>new Promise(r=>setTimeout(()=>r(v),cfg.delay));
  const real=window.fetch.bind(window);
  window.fetch=(input,init)=>{
    const url=new URL(String(input),location.href);
    if(!url.pathname.startsWith('/api/memory/'))return real(input,init);
    const method=(init&&init.method)||'GET',q=url.searchParams,path=url.pathname.slice('/api/memory'.length);
    window.__memCalls.push([method,path+url.search,init&&init.body||null]);
    if(cfg.down)return later(refuse(503,'core_unavailable','core is not ready'));
    if(path==='/status')return later(json({available:true,index_ready:true,recall_enabled:true,legs:{
      store:{status:'ok',reason_code:null,reason:''},lexical:{status:'ok',reason_code:null,reason:''},
      semantic:{status:'disabled',reason_code:'semantic_disabled',reason:'Recherche sémantique : désactivée dans les réglages.'},
      tencent:cfg.tencent?{status:cfg.tencent,reason_code:cfg.tencent==='ok'?null:'tencent_'+cfg.tencent,reason:''}
        :{status:'disabled',reason_code:'tencent_disabled',reason:'Sidecar Tencent : désactivé.'},
      ...__KNOWLEDGE_LEGS__}}));
    if(path==='/notes'){
      let list=notes.filter(n=>(!q.get('level')||n.level===q.get('level'))&&(!q.get('kind')||n.kind===q.get('kind'))&&(!q.get('retention')||n.retention===q.get('retention')));
      const limit=+(q.get('limit')||50),offset=+(q.get('offset')||0);
      return later(json({notes:list.slice(offset,offset+limit),limit,offset,derived:false}));
    }
    if(path.startsWith('/notes/')){const n=notes.find(x=>x.id===path.slice(7));return later(n?json({note:n}):refuse(404,'memory_not_found','no such note'))}
    if(path==='/search'){const t=(q.get('q')||'').toLowerCase();
      return later(json({hits:notes.filter(n=>n.title.toLowerCase().includes(t)).slice(0,+(q.get('limit')||20)).map((n,i)=>({id:n.id,title:n.title,snippet:n.excerpt,
        score:Math.round((9.5-i)*100)/100,level:n.level,retention:n.retention,kind:n.kind,scope:n.scope,revision:n.revision,updated_at:n.updated_at})),derived:true,ranking:'lexical_bm25'}))}
    if(path==='/candidates'){const st=q.get('state');return later(json({candidates:cands.filter(c=>!st||c.state===st),available:true}))}
    const dec=path.match(/^\/candidates\/([^/]+)\/decision$/);
    if(dec&&method==='POST'){
      if(cfg.refuse)return later(refuse(409,'memory_conflict_revision','candidate already decided'));
      const c=cands.find(x=>x.id===dec[1]);if(!c)return later(refuse(404,'memory_not_found','no such candidate'));
      const d=JSON.parse(init.body).decision;c.state=d==='accept'?'accepted':'rejected';c.decided_by='human.owner';c.decided_at='2026-10-24T10:00:00';
      if(d==='accept')c.committed_memory_id='n'+(notes.length+1);
      return later(json({candidate:{...c,body:c.body}}));
    }
    if(path.startsWith('/candidates/')){const c=cands.find(x=>x.id===path.slice(12));return later(c?json({candidate:c}):refuse(404,'memory_not_found','no such candidate'))}
    if(path==='/recall-explain'){const t=(q.get('q')||'').toLowerCase(),max=+(q.get('max_items')||6);
      const items=notes.filter((n,i)=>i%3===0||n.title.toLowerCase().includes(t)).slice(0,Math.min(3,max)).map((n,i)=>({id:n.id,title:n.title,snippet:n.excerpt,
        score:Math.round((0.0328-i*0.0041)*10000)/10000,rank_sources:{lexical:i+1},why:'mots communs avec la phrase',level:n.level,retention:n.retention,source:n.sources[0].ref,revision:n.revision}));
      return later(json({scopes:['private','shared'],degraded:[],timings_ms:{lexical:11.6},budget:{max_items:max,timeout_ms:400,item_chars:400,total_chars:6000},items}))}
    return later(refuse(404,'not_found','unrouted '+path));
  };
  return true})()""".replace("__KNOWLEDGE_LEGS__", json.dumps(KNOWLEDGE_LEGS))
