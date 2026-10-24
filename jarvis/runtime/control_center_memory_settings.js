/* Réglages mémoire du Control Center (jarvis-memory-intelligence-knowledge, Slice 11 ; rangés en sections par
   jarvis-settings-ui-reorganization, Slice 05 — `docs/settings/memory.md`).

   Rend la section `memory` de la lecture des réglages (`schema`, `values`, `effective`, `downgraded`, `secrets`,
   `loadouts`, `status`) et écrit un correctif `{memory: {...}}` par la même route. Aucune borne, aucune liste
   d'options, aucun libellé de champ, aucune destination n'est copié ici : tout vient du schéma serveur, et chaque
   champ dit lui-même la section de Réglages qui l'édite (`surface.section`). Jamais de secret : seulement `has_secret`.

   Vues d'un même état partagé (`createStore`, un par ouverture des Réglages) :
   - `memory` : l'onglet « Mémoire » (refonte-ui-settings, Slice 05, maquette 04) : cartes Rappel, Consolidation,
     Recherche sémantique, résumé du système, entrée du Memory Center avec ses compteurs réels, bandeau Avancé ;
   - `knowledge` : l'onglet « Connaissances » : sources (préférence ET disponibilité réelle), portées, loadouts ;
   - `fields` : les champs d'UNE section (`options.section`) en liste simple — Avancé › Mémoire (`memory_advanced`) ;
   (le Memory Center a sa propre section et son module, `control_center_memory.js`, depuis la Slice 06) ;
   - `diagnostics` : l'état détaillé des étages et des valeurs coupées (partie « Mémoire » d'Avancé › Diagnostics).
   Le brouillon vit dans l'état partagé : il survit au passage d'une section mémoire à l'autre (une règle de
   compatibilité peut ramener un champ d'une autre section), et « Enregistrer la mémoire » envoie tout le brouillon.
   Une vue détruite (`destroy`) ne dessine plus rien et ignore les réponses tardives.
   L'état VIVANT de Core (`/api/memory/status`, nombre de notes et de candidats en attente) est lu une fois par
   ouverture (`loadLive`, vues `memory` et `knowledge`) : jamais inventé ; « — » et la raison réelle si Core se tait. */
(function(root){
  'use strict';
  const MOUNT_ID='memorySettingsMount';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const STATUS={ok:['Actif','ok'],disabled:['Désactivé','info'],unavailable:['Indisponible','bad']};
  const LEG_LABEL={lexical:'Recherche par mots',recall:'Rappel dans le tour',semantic:'Recherche sémantique',tencent:'Sidecar Tencent',
    'knowledge:wiki':'Wiki','knowledge:codegraph':'Graphe de code','knowledge:skills':'Skills','knowledge:skill':'Skills'};
  const SECRET_HINT={semantic:'Clé du fournisseur',tencent:'Jeton du sidecar'};
  const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);

  /* Pictogrammes au trait (24×24), partagés avec le Memory Center (`JarvisMemorySettings.icon`). */
  const ICONS=Object.freeze({
    brain:'<path d="M9.5 4A3 3 0 0 0 6.5 7v.3A3 3 0 0 0 4.5 10.5a3 3 0 0 0 .9 2.2A3.2 3.2 0 0 0 6.5 18a3 3 0 0 0 3 2 2.5 2.5 0 0 0 2.5-2.5V6.5A2.5 2.5 0 0 0 9.5 4z"/><path d="M14.5 4A3 3 0 0 1 17.5 7v.3a3 3 0 0 1 2 3.2 3 3 0 0 1-.9 2.2A3.2 3.2 0 0 1 17.5 18a3 3 0 0 1-3 2 2.5 2.5 0 0 1-2.5-2.5"/><path d="M8.5 10.5h1.5M14 13.5h1.5"/>',
    search:'<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    db:'<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13"/><path d="M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>',
    gear:'<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.6M12 18.6v2.6M2.8 12h2.6M18.6 12h2.6M5.5 5.5l1.8 1.8M16.7 16.7l1.8 1.8M5.5 18.5l1.8-1.8M16.7 7.3l1.8-1.8"/>',
    user:'<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/>',
    users:'<circle cx="9" cy="8" r="3.2"/><path d="M3 20c.7-3.3 3-5 6-5s5.3 1.7 6 5"/><path d="M15.5 4.9a3.2 3.2 0 0 1 0 6.2M17.5 15.2c1.8.6 3 2.2 3.5 4.8"/>',
    shield:'<path d="M12 3 5 6v5c0 4.6 3 8.4 7 10 4-1.6 7-5.4 7-10V6z"/><path d="m9.5 12 1.8 1.8 3.4-3.6"/>',
    doc:'<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/>',
    chevron:'<path d="m9 6 6 6-6 6"/>',
    chevronLeft:'<path d="m15 6-6 6 6 6"/>',
    wrench:'<path d="M14.7 6.3a4 4 0 0 0 5 5L11.5 19.5a2.1 2.1 0 0 1-3-3z"/><path d="M14.7 6.3 17 4"/>',
    lock:'<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    star:'<path d="m12 3.5 2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.2-4.1 5.8-.8z"/>',
    bars:'<path d="M5 20v-6M10 20V8M15 20v-9M20 20V4"/>',
    nodes:'<circle cx="12" cy="5" r="2.2"/><circle cx="5" cy="18" r="2.2"/><circle cx="19" cy="18" r="2.2"/><path d="M11 7 6 16M13 7l5 9M7.2 18h9.6"/>',
    book:'<path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5z"/><path d="M5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3"/>',
    code:'<path d="m8.5 8-4 4 4 4M15.5 8l4 4-4 4M13.5 5l-3 14"/>',
    cube:'<path d="M12 3 20 7.5v9L12 21l-8-4.5v-9z"/><path d="M12 12 20 7.5M12 12 4 7.5M12 12v9"/>',
    layers:'<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    cloud:'<path d="M7 18a4.5 4.5 0 0 1-.5-9A6 6 0 0 1 18 9.5a4 4 0 0 1-.5 8.5z"/>',
    folder:'<path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4.5l2 2.5H19a1.5 1.5 0 0 1 1.5 1.5v8.5A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    refresh:'<path d="M20 11a8 8 0 0 0-14.3-4.5L4 8"/><path d="M4 4v4h4M4 13a8 8 0 0 0 14.3 4.5L20 16"/><path d="M20 20v-4h-4"/>',
    check:'<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    close:'<path d="M6 6l12 12M18 6 6 18"/>',
    play:'<path d="M8 5.5v13l10-6.5z"/>',
    more:'<circle cx="12" cy="5.5" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="12" cy="18.5" r="1.2"/>',
  });
  const icon=(name,cls)=>`<svg class="mem-ico${cls?' '+cls:''}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICONS[name]||''}</svg>`;

  /* Feuille de la page Mémoire & connaissances, injectée une fois (préfixe `.mem-`). Jetons du shell seulement
     (`--set-*`, `--shell-*`, `--accent`, `--ok`…) : la fondation visuelle partagée (Slice 01) les redéfinit. */
  const STYLE_ID='jarvisMemorySettingsStyle';
  const STYLE=`
.mem-page,.mem-card{--set-tone:var(--mem-hue)}
.mem-page{--mem-hue:var(--accent);--mem-violet:var(--role-accent-violet,#b9a2ff);--mem-line:color-mix(in srgb,var(--mem-hue) 22%,var(--set-hair-2,#1b3442));
  --mem-glass:var(--shell-glass-strong,rgba(4,10,15,.8));--mem-ink-2:var(--set-ink-2,#a9c2cf);--mem-ink-3:var(--set-ink-3,#8aa5b3);--mem-hair:var(--set-hair-2,#24414f);--mem-r:14px;
  container-type:inline-size;display:grid;gap:16px;min-width:0;color:var(--set-ink,var(--text));font-size:13.5px;line-height:1.5}
.mem-page *{box-sizing:border-box}
.mem-page .sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.mem-ico{width:20px;height:20px;flex:none;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.mem-grid{display:grid;gap:16px;grid-template-columns:minmax(0,1fr);align-items:start}
@container (min-width:720px){.mem-grid{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
.mem-col{display:grid;gap:16px;align-content:start;min-width:0}
/* Panneaux (.set-panel), médaillons, interrupteurs, curseurs, cartes de choix, pastilles et boutons : primitives de la
   fondation (Slice 07 de refonte-ui-settings) ; les classes .mem-* ne gardent que la composition et servent d'accroches. */
.mem-card{display:grid;gap:14px}
.mem-card:focus-visible,.mem-card[data-settings-landed]:focus{outline:2px solid var(--accent);outline-offset:3px}
.mem-head{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:14px;align-items:center}
.mem-medal .mem-ico{width:50%;height:50%}
.mem-head-2{grid-template-columns:auto minmax(0,1fr)}
.mem-title{margin:0;font-size:18px;font-weight:600;line-height:1.25;letter-spacing:-.005em}
.mem-sub{margin:2px 0 0;color:var(--mem-ink-2);font-size:13px}
.mem-text{margin:0;color:var(--mem-ink-2);max-width:62ch}
.mem-label{margin:0;font-size:13px;font-weight:600;color:var(--set-ink,var(--text))}
.mem-hint{margin:0;color:var(--mem-ink-3);font-size:12px}
.mem-hint.warn{color:var(--warn)}.mem-hint.bad{color:var(--danger)}
.mem-meter{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:6px 14px;align-items:center;padding:14px 16px;border:1px solid var(--mem-line);border-radius:12px;background:rgba(3,9,13,.5)}
.mem-meter>.mem-ico{width:26px;height:26px;color:var(--mem-hue)}
.mem-meter .mem-label{font-weight:500}
.mem-meter .set-range,.mem-meter .mem-hint{grid-column:1/-1}
.mem-out{font-size:24px;font-weight:600;line-height:1;color:var(--set-ink,var(--text));font-variant-numeric:tabular-nums;white-space:nowrap}
.mem-out small{font-size:15px;font-weight:500;color:var(--mem-ink-2)}
.mem-out.sm{font-size:13px;padding:3px 9px;border:1px solid var(--mem-line);border-radius:8px}
.mem-pair{display:grid;gap:18px 22px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));align-items:start}
.mem-slider{display:grid;gap:6px;min-width:0}
.mem-slider-head{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:42px}
.mem-modes{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.mem-modes legend{padding:0;margin:0 0 10px;font-size:13px;font-weight:600}
/* Carte de choix de la fondation, avec son témoin radio visible au coin (lisible désactivé, contraste ≥ 4,5:1). */
.mem-mode{display:grid;grid-template-columns:auto minmax(0,1fr);gap:2px 12px;align-items:center;padding-right:34px}
.mem-mode input{appearance:none;-webkit-appearance:none;inset:auto;top:12px;right:12px;width:16px;height:16px;opacity:1;border:2px solid currentColor;border-radius:50%;color:var(--set-ink,var(--text));background:transparent;cursor:inherit}
.mem-mode input:checked{border-color:var(--mem-hue);background:radial-gradient(circle,var(--mem-hue) 0 3px,transparent 4px)}
.mem-mode input:focus-visible{outline:none}
.mem-mode .mem-ico{grid-row:1/3;width:26px;height:26px;color:var(--mem-ink-2)}
.mem-mode strong{font-size:14px;font-weight:600}
.mem-mode span{font-size:12px;color:var(--mem-ink-2)}
.mem-mode:has(input:checked) .mem-ico{color:var(--mem-hue)}
.mem-mode:has(input:disabled){opacity:1;border-style:dashed}
.mem-mode:has(input:disabled) strong{color:var(--mem-ink-2)}
.mem-select{display:flex;align-items:center;gap:12px;padding:0 14px;border:1px solid var(--mem-line);border-radius:12px;background:rgba(3,9,13,.5)}
.mem-select>.mem-ico{color:var(--mem-hue)}
.mem-select select{flex:1;min-width:0;height:46px;padding:0;border:0;background:transparent;color:var(--set-ink,var(--text));font-size:15px;cursor:pointer}
.mem-select select option{background:#08121a}
.mem-select:has(select:focus-visible){outline:2px solid var(--accent);outline-offset:2px}
.mem-select select:focus-visible{outline:none}
.mem-field{display:grid;gap:8px;min-width:0}
.mem-inline{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:4px 12px;align-items:center;padding-top:14px;border-top:1px solid var(--set-hair,rgba(151,191,209,.13))}
.mem-inline .mem-medal{color:var(--mem-ink-2);border-color:var(--mem-hair);box-shadow:none;background:none}
.mem-inline .mem-hint{grid-column:2/-1}
.mem-secretline{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;font-size:12.5px;color:var(--mem-ink-2)}
.mem-pill{white-space:nowrap}
.mem-tone-bad{color:var(--danger)}
.mem-rows{display:grid;gap:8px;margin:0;padding:0;list-style:none}
.mem-row{display:grid;grid-template-columns:auto minmax(0,1fr) minmax(0,1.1fr) auto;gap:12px;align-items:center;width:100%;min-height:46px;padding:8px 12px;
  border:1px solid var(--mem-hair);border-radius:10px;background:rgba(3,9,13,.4);color:inherit;font:inherit;text-align:left;cursor:pointer}
.mem-row:hover{border-color:color-mix(in srgb,var(--mem-hue) 45%,transparent)}
.mem-row>.mem-ico{color:var(--mem-ink-2)}
.mem-row-k{font-weight:500}
.mem-row-v{display:inline-flex;align-items:center;gap:8px;min-width:0;font-size:12.5px}
.mem-row-v span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mem-cta{--mem-hue:var(--mem-violet)}
.mem-cta-open{display:grid;place-items:center;width:38px;height:38px;border:1px solid transparent;border-radius:50%;background:none;color:var(--set-ink,var(--text));cursor:pointer}
.mem-cta-open:hover{border-color:var(--mem-violet)}
.mem-tiles{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(118px,1fr))}
.mem-tile{display:grid;gap:2px;align-content:start;min-height:62px;padding:10px 12px;border:1px solid color-mix(in srgb,var(--mem-violet) 40%,transparent);
  border-radius:12px;background:rgba(10,6,24,.4);color:inherit;font:inherit;text-align:left;cursor:pointer}
.mem-tile:hover{border-color:var(--mem-violet);box-shadow:0 0 14px color-mix(in srgb,var(--mem-violet) 28%,transparent)}
.mem-tile-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:4px}
.mem-tile-top .mem-ico:first-child{width:24px;height:24px;color:var(--mem-violet)}
.mem-tile-top .mem-ico:last-child{width:16px;height:16px;color:var(--mem-ink-2)}
.mem-tile strong{font-size:13.5px;font-weight:600}
.mem-tile small{font-size:12px;color:var(--mem-ink-2)}
.mem-adv{grid-template-columns:auto minmax(0,1fr);align-items:center;gap:14px 18px;--mem-hue:var(--mem-ink-3)}
.mem-adv-note{display:flex;align-items:center;gap:10px;color:var(--mem-ink-2);font-size:12.5px;grid-column:1/-1}
.mem-adv-actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;grid-column:1/-1}
@container (min-width:820px){.mem-adv{grid-template-columns:auto minmax(0,.9fr) minmax(0,1.3fr) auto}
  .mem-adv-note{grid-column:auto;padding-left:18px;border-left:1px dashed var(--mem-hair)}.mem-adv-actions{grid-column:auto;flex-direction:column;align-items:flex-end}}
.mem-btn .mem-ico{width:16px;height:16px}
.mem-savebar{position:relative;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px 16px;padding:10px 16px;
  border:1px solid var(--mem-hair);border-radius:12px;background:color-mix(in srgb,var(--solid,#070d13) 92%,transparent);backdrop-filter:blur(14px)}
.mem-savebar.dirty{position:sticky;bottom:0;border-color:color-mix(in srgb,var(--warn) 45%,transparent);box-shadow:0 -8px 24px rgba(0,0,0,.35)}
.mem-savebar .set-actions{margin:0}
.mem-savebar-text{margin:0;font-size:12.5px;color:var(--mem-ink-2)}
.mem-savebar.dirty .mem-savebar-text{color:var(--warn)}
.mem-messages{display:grid;gap:8px}.mem-messages:empty{display:none}
.mem-sources{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.mem-source{align-content:start}
.mem-source .mem-head{grid-template-columns:auto minmax(0,1fr)}
.mem-source-foot{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;padding-top:12px;border-top:1px solid var(--set-hair,rgba(151,191,209,.13))}
.mem-scopes{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));margin:0;padding:0;list-style:none}
.mem-scopes li{display:grid;gap:2px;padding:10px 12px;border:1px solid var(--mem-hair);border-radius:10px;background:rgba(3,9,13,.4)}
.mem-scopes strong{font-size:13px}.mem-scopes span{font-size:12px;color:var(--mem-ink-2)}
.mem-loadouts{display:grid;gap:0;margin:0;padding:0;list-style:none}
.mem-loadouts li{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:6px 12px;padding:8px 0;border-bottom:1px solid var(--set-hair,rgba(151,191,209,.13));font-size:12.5px}
.mem-loading{display:inline-flex;align-items:center;gap:8px;color:var(--mem-ink-2);font-size:12.5px}
.mem-spin{width:14px;height:14px;flex:none;border-radius:50%;border:2px solid color-mix(in srgb,var(--accent) 25%,transparent);border-top-color:var(--accent);animation:memSpin .8s linear infinite}
@keyframes memSpin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.mem-spin{animation:none}.mem-page *{transition:none!important}}
.mem-linkish{padding:0;border:0;background:none;color:var(--accent);font:inherit;font-size:12.5px;text-decoration:underline;text-underline-offset:2px;cursor:pointer}
`;
  function injectStyle(){
    const doc=root.document;
    if(!doc||!doc.head||doc.getElementById(STYLE_ID))return;
    const el=doc.createElement('style');el.id=STYLE_ID;el.textContent=STYLE;doc.head.appendChild(el);
  }

  /* Étages d'une section du bloc : le sien (`recall`, `semantic`, `tencent`), ou ses `knowledge:*`. */
  function legsOf(legs,sectionId){return Object.keys(legs).filter(k=>k===sectionId||k.startsWith(sectionId+':'))}
  function fields(schema){return (schema.sections||[]).flatMap(s=>s.fields.map(f=>({...f,section:s.id})))}
  /* `views` : le dessin de chaque vue vivante du store. Une lecture ou un enregistrement redessine toutes les vues à sa
     fin : la section qui l'a lancé a pu être quittée entre-temps, celle qui est affichée doit refléter le résultat. */
  function createStore(){return {memory:null,draft:{},busy:false,message:null,restart:false,loading:null,live:null,views:new Set()}}

  /* Primitives du shell (`JarvisSettingsUI`) : celles passées par la page, sinon celles de la page. */
  function primitives(opts){
    const ui=opts.ui||root.JarvisSettingsUI;
    if(!ui)throw new Error('JarvisSettingsUI absent : les réglages mémoire se dessinent avec les primitives du shell.');
    return ui;
  }

  function create(host,options){
    const opts=options||{};
    const ui=primitives(opts);
    const mode=opts.mode||'fields';
    const fetchJson=opts.fetch||(async(path,init)=>{
      const r=await root.fetch(path,init),text=await r.text();let body={};try{body=text?JSON.parse(text):{}}catch{body={error:text}}
      if(!r.ok){const err=body.error,msg=err&&typeof err==='object'?err.message:err;const e=new Error(msg||body.message||('HTTP '+r.status));
        e.code=r.headers.get('X-Settings-Error-Code')||r.headers.get('X-Jarvis-Error-Code')||(err&&typeof err==='object'&&err.code)||'';e.status=r.status;throw e}
      return body;
    });
    const st=opts.store||createStore();
    if(!st.views)st.views=new Set();
    /* Le message et l'avis d'après-enregistrement disent ce qui vient d'arriver : une vue montée plus tard ne les reprend
       pas, sauf si l'enregistrement est encore en cours (elle en recevra l'issue). */
    if(!st.busy){st.message=null;st.restart=false}
    let dead=false;

    const stored=p=>st.memory.values[p];
    const current=p=>own(st.draft,p)?st.draft[p]:stored(p);
    const dirty=()=>Object.keys(st.draft).length>0;
    const field=p=>fields(st.memory.schema).find(f=>f.path===p);
    const restartHit=()=>(st.memory.status.restart_required||[]).filter(p=>own(st.draft,p));
    const inSection=f=>!!f.surface&&f.surface.section===opts.section;

    /* Ce que le brouillon rend impossible : l'interrupteur reste éteint et dit pourquoi. */
    function blocked(f){
      if(f.path==='semantic.enabled'&&current('semantic.provider')==='none')return 'Choisissez d’abord un fournisseur d’embeddings.';
      if(f.path==='tencent.enabled'&&!String(current('tencent.url')||'').trim())return 'Renseignez d’abord l’URL du sidecar.';
      return '';
    }
    function blockedOption(f,opt){
      if(f.path==='consolidation.mode'&&opt.id==='auto'&&!current('semantic.enabled'))return 'exige la recherche sémantique';
      return '';
    }

    function legBadge(leg){const [txt,tone]=STATUS[leg.status]||[leg.status,'info'];return ui.badge(tone,txt)}
    function problems(){
      const legs=st.memory.status.legs||{},down=Object.values(st.memory.status.downgraded||{});
      return Object.keys(legs).filter(k=>legs[k].status==='unavailable'||down.includes(legs[k].reason_code)).length
        +down.filter(c=>!Object.values(legs).some(l=>l.reason_code===c)).length;
    }
    /* Ligne d'état courte de la page ordinaire : le détail vit dans Avancé › Diagnostics. */
    function statusLine(legKeys){
      const legs=st.memory.status.legs||{},n=problems();
      const marks=legKeys.map(k=>`<span class="mem-leg-mark">${esc(LEG_LABEL[k]||k)} ${legBadge(legs[k])}</span>`).join('');
      const text=n?`${n} point${n>1?'s':''} à vérifier dans la mémoire.`:'Aucun problème détecté dans la mémoire.';
      return `<div class="mem-status">${marks}<span class="mem-status-text${n?' bad':''}">${esc(text)}</span>`
        +`<button type="button" class="linkish" data-mem-diagnostics>Voir le diagnostic mémoire</button></div>`;
    }

    function control(f){
      const id='mem_'+f.path.replace(/\./g,'_'),v=current(f.path),eff=(st.memory.effective||{})[f.path]||{},env=eff.source==='env';
      const dis=env||st.busy?' disabled':'';
      const why=blocked(f);
      const hint=`${f.help||''}${env?' Valeur imposée par l’environnement ('+f.env+') : modifiez-la là.':''}${why&&!v?' '+why:''}`;
      const effNote=eff.downgraded&&!env?` <span class="tag">effectif : ${esc(String(eff.value))}</span>`:'';
      const described=` aria-describedby="${id}-hint"`;
      let input;
      if(f.type==='bool'){
        const off=!v&&why?' disabled':'';
        input=`<input type="checkbox" id="${id}" data-mem="${esc(f.path)}"${v?' checked':''}${dis}${off}${described}>${effNote}`;
        return ui.field({id,label:f.label,hint,inline:true,control:input});
      }
      if(f.type==='enum'){
        const opt=f.options.map(o=>{const b=blockedOption(f,o),x=b&&o.id!==v;return `<option value="${esc(o.id)}"${o.id===v?' selected':''}${x?' disabled':''}>${esc(o.label)}${x?' ('+esc(b)+')':''}</option>`}).join('');
        input=`<select id="${id}" data-mem="${esc(f.path)}"${dis}${described}>${opt}</select>${effNote}`;
      }else if(f.type==='int'||f.type==='float'){
        const step=f.type==='float'?'0.05':'1';
        input=`<span class="mem-number"><input id="${id}" type="number" inputmode="decimal" min="${esc(f.min)}" max="${esc(f.max)}" step="${step}" value="${esc(v)}" data-mem="${esc(f.path)}"${dis}${described}><span class="tag">${esc(f.min)} à ${esc(f.max)}</span></span>`;
      }else{
        input=`<input id="${id}" type="${f.type==='text'?'url':'text'}" maxlength="${esc(f.max_length||512)}" value="${esc(v||'')}" autocomplete="off" spellcheck="false" data-mem="${esc(f.path)}"${dis}${described}>`;
      }
      return ui.field({id,label:f.label,hint,control:input});
    }

    function secretLine(sectionId){
      const s=(st.memory.secrets||{})[sectionId];if(!s)return '';
      return `<p class="hint mem-secret">${esc(SECRET_HINT[sectionId]||'Clé')} : <strong>${s.has_secret?'présent':'absent'}</strong>. Il se règle dans `
        +`<button type="button" class="linkish" data-mem-open="providers">Plugins & MCP › Fournisseurs</button>, jamais ici.</p>`;
    }
    /* Moment d'application d'un groupe de champs, lu dans `restart_required` du serveur ; `null` si le groupe mélange. */
    function applies(list){
      const restart=st.memory.status.restart_required||[],hits=list.filter(f=>restart.includes(f.path)).length;
      return hits===0?'next_turn':hits===list.length?'next_core_start':null;
    }
    function loadoutsHtml(){
      const rules=Object.entries(st.memory.loadouts||{});
      const body=rules.length?`<ul class="mem-legs">${rules.map(([k,r])=>`<li><code>${esc(k)}</code><span class="hint">${(r.memory_scopes||[]).length} scope(s)${r.wiki===false?', sans wiki':''}${r.codegraph===false?', sans graphe':''}${r.skills===false?', sans skills':''}</span></li>`).join('')}</ul>`
        :'<p class="hint">Aucune règle : les préréglages par agent s’appliquent.</p>';
      return `<div class="mem-group" data-mem-loadouts><h4>Connaissances par agent</h4>${body}<p class="hint">Lecture seule ici ; les règles se définissent dans le fichier de réglages.</p></div>`;
    }
    function restartHtml(){
      const need=restartHit();
      const after=st.restart?ui.notice({kind:'ok',live:'polite',text:'Enregistré. La recherche sémantique et le sidecar ne s’appliquent qu’au prochain démarrage de Core ; le rappel, les budgets et les connaissances dès le prochain tour.'}):'';
      const pending=need.length?ui.notice({kind:'info',live:'polite',body:`<span class="set-notice-text">Redémarrage de Core nécessaire pour : ${need.map(p=>`<code>${esc((field(p)||{}).label||p)}</code>`).join(', ')}.</span>`}):'';
      return after+pending;
    }
    /* Le brouillon est commun aux sections mémoire : on dit ce qu'il porte ailleurs, puisque l'enregistrement l'envoie. */
    function elsewhereHtml(){
      const other=Object.keys(st.draft).map(field).filter(f=>f&&!inSection(f));
      return other.length?`<p class="hint mem-elsewhere">Enregistre aussi les changements en attente dans d’autres sections : ${other.map(f=>`<code>${esc(f.label)}</code>`).join(', ')}.</p>`:'';
    }
    function messageHtml(){
      if(!st.message)return '';
      return ui.notice({kind:st.message.tone,live:st.message.tone==='bad'?'assertive':'polite',text:st.message.text});
    }
    /* `aria-disabled` plutôt que `disabled` : un bouton désactivé perd le focus, qui tomberait sur `body` pendant et
       après l'enregistrement (finitions avant la Slice 10). Les écoutes refusent le clic tant qu'il ne sert à rien. */
    function actionsHtml(){
      const off=dirty()&&!st.busy?'':' aria-disabled="true"';
      return ui.actions(`<button type="button" class="action primary" data-mem-save${off}>${st.busy?'Enregistrement…':'Enregistrer la mémoire'}</button>`
        +`<button type="button" class="action" data-mem-reset${off}>Annuler les changements</button>`);
    }

    function fieldsHtml(){
      const groups=(st.memory.schema.sections||[]).map(s=>({s,list:s.fields.filter(inSection)})).filter(g=>g.list.length);
      const legs=st.memory.status.legs||{};
      const single=groups.length===1;
      const body=groups.map(({s,list})=>{
        const inner=list.map(control).join('')+secretLine(s.id);
        if(single)return inner;
        const when=applies(list),badge=legs[s.id]?' '+legBadge(legs[s.id]):'';
        return `<div class="mem-group"><h4>${esc(s.label)}${badge}${when?' '+ui.appliesBadge(when):''}</h4>${inner}</div>`;
      }).join('');
      const loadouts=(st.memory.schema.loadouts||{}).surface;
      const when=single?applies(groups[0].list):null;
      return ui.section({id:`memSection_${opts.section}`,title:opts.label||opts.section,description:opts.description||'',
        applies:when||undefined,
        body:statusLine(groups.flatMap(g=>legsOf(legs,g.s.id)))+body+(loadouts&&loadouts.section===opts.section?loadoutsHtml():'')
          +restartHtml()+messageHtml()+elsewhereHtml()+actionsHtml()});
    }
    /* Partie « Mémoire » des diagnostics : chaque étage, ce qui le dégrade et comment le réparer, les combinaisons
       coupées à la lecture, et les valeurs imposées par l'environnement. Lecture seule. */
    function diagnosticsHtml(){
      const legs=st.memory.status.legs||{},down=Object.entries(st.memory.status.downgraded||{});
      const items=Object.keys(legs).map(k=>`<li><span class="mem-leg">${esc(LEG_LABEL[k]||k)}</span>${legBadge(legs[k])}</li>`).join('');
      const notes=Object.keys(legs).filter(k=>legs[k].status==='unavailable'||down.some(([,c])=>c===legs[k].reason_code))
        .map(k=>ui.notice({kind:'bad',title:LEG_LABEL[k]||k,body:`<span class="set-notice-text">${esc(legs[k].reason)} <code>${esc(legs[k].reason_code)}</code></span>${legs[k].how_to_fix?`<span class="hint">${esc(legs[k].how_to_fix)}</span>`:''}`})).join('');
      const rest=down.filter(([,c])=>!Object.keys(legs).some(k=>legs[k].reason_code===c))
        .map(([p,c])=>ui.notice({kind:'bad',body:`<span class="set-notice-text"><code>${esc(p)}</code> : combinaison incohérente dans le fichier, coupée à la lecture (${esc(c)}).</span>`})).join('');
      const env=fields(st.memory.schema).filter(f=>((st.memory.effective||{})[f.path]||{}).source==='env');
      const envHtml=env.length?`<p class="hint">Valeurs imposées par l’environnement : ${env.map(f=>`<code>${esc(f.env)}</code> (${esc(f.label)})`).join(', ')}.</p>`:'';
      return `<ul class="mem-legs" aria-label="État des étages mémoire">${items}</ul>${notes}${rest}${envHtml}
        <p class="hint">État déduit des réglages, sans appel réseau. L’état en direct (sidecar injoignable, index en synchronisation) est dans le Memory Center, onglet Santé des index. La mémoire canonique (notes Markdown) reste utilisable même si tous les étages optionnels sont coupés.</p>`;
    }


    /* ---------------------------------------------------------------- page « Mémoire » (maquette 04)
       Présentation : titres et textes des cartes. Données : champs, bornes, options et libellés du schéma servi,
       valeurs du brouillon, état enregistré (`status`) et état vivant (`st.live`). Rien de la maquette n'est recopié :
       pas de « profil de rappel » (aucun réglage réel derrière), pas de fournisseur hors du schéma. */
    const idOf=p=>'mem_'+p.replace(/\./g,'_');
    const effOf=p=>(st.memory.effective||{})[p]||{};
    const has=p=>!!field(p);
    /* Aide d'un contrôle : l'aide servie (`help`) reste le nom accessible détaillé ; elle n'est affichée que si
       `shown`. Une contrainte (valeur imposée par l'environnement, dépendance non remplie) s'affiche toujours. */
    function hintOf(f,shown){
      const env=effOf(f.path).source==='env',why=blocked(f),v=current(f.path);
      const warn=[env?`Valeur imposée par l’environnement (${f.env}) : modifiez-la là.`:'',why&&!v?why:''].filter(Boolean);
      if(warn.length)return `<p class="mem-hint warn" id="${idOf(f.path)}-hint">${esc(warn.join(' '))}<span class="sr"> ${esc(f.help||'')}</span></p>`;
      return `<p class="mem-hint${shown?'':' sr'}" id="${idOf(f.path)}-hint">${esc(f.help||'')}</p>`;
    }
    function locked(f){return effOf(f.path).source==='env'||st.busy}
    function toggle(path){
      const f=field(path);if(!f)return '';
      const id=idOf(path),v=!!current(path),why=blocked(f);
      const dis=locked(f)||(!v&&why)?' disabled':'';
      /* Primitive partagée (Slice 07) : bouton `role=switch`, état dans `aria-checked`, mot d'état à côté. */
      return ui.toggle({id,checked:v,label:f.label,describedBy:`${id}-hint`,stateText:{on:'Activé',off:'Désactivé'},disabled:!!dis,data:{mem:path}});
    }
    const fill=(f,v)=>Math.max(0,Math.min(100,((Number(v)-f.min)/((f.max-f.min)||1))*100)).toFixed(1)+'%';
    const percent=v=>Math.round(Number(v)*100)+' %';
    function rangeInput(f,format){
      const id=idOf(f.path),v=current(f.path),step=f.type==='float'?'0.05':'1';
      return `<input type="range" class="set-range" id="${id}" data-mem="${esc(f.path)}" data-mem-range min="${esc(f.min)}" max="${esc(f.max)}" step="${step}" value="${esc(v)}"`
        +` style="--set-range-fill:${fill(f,v)}" aria-label="${esc(f.label)}" aria-valuetext="${esc(format(v))}" aria-describedby="${id}-hint"${locked(f)?' disabled':''}>`;
    }
    function slider(path,format,ends,shown){
      const f=field(path);if(!f)return '';
      return `<div class="mem-slider"><div class="mem-slider-head"><label class="mem-label" for="${idOf(path)}">${esc(f.label)}</label>`
        +`<output class="mem-out sm" for="${idOf(path)}" data-mem-out="${esc(path)}">${esc(format(current(path)))}</output></div>`
        +rangeInput(f,format)+`<div class="set-range-ends" aria-hidden="true"><span>${esc(ends[0])}</span><span>${esc(ends[1])}</span></div>${hintOf(f,shown)}</div>`;
    }
    function head(iconName,title,sub,trailing,id){
      return `<div class="mem-head"><span class="set-medallion mem-medal">${icon(iconName)}</span><div><h3 class="mem-title"${id?` id="${id}"`:''}>${esc(title)}</h3>`
        +`${sub?`<p class="mem-sub">${esc(sub)}</p>`:''}</div>${trailing||'<span></span>'}</div>`;
    }
    /* Pastille d'état : la primitive `.set-dot` (Slice 07) ; `mem-pill` reste l'accroche des tests. */
    function pill(tone,text){return ui.dot(tone,text).replace('class="set-dot','class="mem-pill set-dot')}
    const savedLegs=()=>st.memory.status.legs||{};

    function recallCard(){
      const max=field('recall.max_items');
      const legs=savedLegs(),sem=legs.semantic&&legs.semantic.status,semText=sem==='ok'?' (c’est le cas)':sem==='unavailable'?' (activée, mais indisponible pour l’instant)':' (elle ne l’est pas)';
      const meter=max?`<div class="mem-meter">${icon('db')}<label class="mem-label" for="${idOf(max.path)}">${esc(max.label)}</label>`
        +`<output class="mem-out" for="${idOf(max.path)}" data-mem-out="${esc(max.path)}" data-mem-max="${esc(max.max)}">${esc(current(max.path))} <small>/ ${esc(max.max)}</small></output>`
        +rangeInput(max,v=>`${v} sur ${max.max}`)+hintOf(max)+'</div>':'';
      return `<section class="set-panel mem-card" id="memCardRecall" tabindex="-1" aria-labelledby="memRecallTitle">
        ${head('brain','Rappel','Injection de souvenirs contextuels',toggle('recall.enabled'),'memRecallTitle')}
        ${has('recall.enabled')?hintOf(field('recall.enabled')):''}
        <p class="mem-text">JARVIS récupère les souvenirs pertinents pour enrichir chaque réponse avec votre contexte. La recherche par mots
          fonctionne toujours ; la recherche sémantique s’y ajoute quand elle est active${semText}.</p>
        ${meter}
        <p class="mem-hint">Le délai maximal du rappel est un réglage d’opérateur : Avancé &amp; diagnostic › Mémoire.</p>
      </section>`;
    }

    const MODE_ART={auto:['gear','Analyse et enregistre automatiquement au-dessus du seuil.'],manual:['user','Vous validez chaque candidat dans le Memory Center.']};
    function consolidationCard(){
      const mode=field('consolidation.mode');
      const modes=mode?`<fieldset class="set-choices mem-modes" aria-describedby="${idOf(mode.path)}-hint"><legend>${esc(mode.label)}</legend>${mode.options.map(o=>{
        const id=`${idOf(mode.path)}_${o.id}`,on=current(mode.path)===o.id,b=blockedOption(mode,o),off=(b&&!on)||locked(mode);
        const [ico,text]=MODE_ART[o.id]||['gear',''];
        return `<label class="set-choice mem-mode" for="${id}"><input type="radio" name="${idOf(mode.path)}" id="${id}" value="${esc(o.id)}" data-mem="${esc(mode.path)}"${on?' checked':''}${off?' disabled':''}>`
          +`${icon(ico)}<strong>${esc(o.label)}</strong><span>${esc(b&&!on?`Indisponible : ${b}.`:text)}</span></label>`}).join('')}</fieldset>${hintOf(mode)}`:'';
      const auto=current('consolidation.mode')==='auto';
      return `<section class="set-panel mem-card" id="memCardConsolidation" tabindex="-1" aria-labelledby="memConsTitle">
        ${head('db','Consolidation','Gestion et enrichissement de la mémoire','','memConsTitle')}
        <p class="mem-text">La consolidation repère dans vos échanges ce qui mérite d’être retenu et en fait des <strong>candidats</strong> :
          des propositions, pas encore des souvenirs. Un candidat devient une note de la mémoire quand vous l’acceptez${auto?', ou automatiquement au-dessus du seuil de confiance':''}.</p>
        ${modes}
        <div class="mem-pair">${slider('consolidation.auto_min_confidence',percent,['Plus permissif','Plus strict'],true)}
          ${slider('consolidation.max_candidates_per_run',v=>String(v),['Moins','Plus'])}</div>
      </section>`;
    }

    function semanticCard(){
      const prov=field('semantic.provider'),priv=field('semantic.allow_private');
      const select=prov?`<div class="mem-field"><label class="mem-label" for="${idOf(prov.path)}">${esc(prov.label)}</label>`
        +`<div class="mem-select">${icon('cloud')}<select id="${idOf(prov.path)}" data-mem="${esc(prov.path)}" aria-describedby="${idOf(prov.path)}-hint"${locked(prov)?' disabled':''}>`
        +prov.options.map(o=>`<option value="${esc(o.id)}"${o.id===current(prov.path)?' selected':''}>${esc(o.label)}</option>`).join('')+`</select></div>${hintOf(prov)}</div>`:'';
      const s=(st.memory.secrets||{}).semantic;
      const secret=s?`<p class="mem-secretline">Clé du fournisseur : ${s.has_secret?pill('ok','présente'):pill('warn','absente')}`
        +` <button type="button" class="mem-linkish" data-mem-open="providers">Plugins & MCP › Fournisseurs</button></p>`:'';
      const leg=savedLegs().semantic;
      const degraded=leg&&leg.status==='unavailable'?`<p class="mem-hint bad" role="status">${esc(leg.reason)} ${esc(leg.how_to_fix||'')}</p>`:'';
      const privRow=priv?`<div class="mem-inline"><span class="set-medallion set-medallion-sm mem-medal sm">${icon('shield')}</span><div><p class="mem-label">${esc(priv.label)}</p></div>${toggle(priv.path)}${hintOf(priv,true)}</div>`:'';
      return `<section class="set-panel mem-card" id="memCardSemantic" tabindex="-1" aria-labelledby="memSemTitle">
        ${head('search','Recherche sémantique','Retrouver un souvenir par son sens',toggle('semantic.enabled'),'memSemTitle')}
        ${has('semantic.enabled')?hintOf(field('semantic.enabled')):''}
        <p class="mem-text">Trouve aussi les souvenirs qui disent la même chose avec d’autres mots. Facultative : sans elle, le rappel par mots
          continue de fonctionner normalement.</p>
        ${degraded}${select}${secret}${privRow}
        <p class="mem-hint">${ui.appliesBadge('next_core_start')} Ces trois réglages s’appliquent au prochain démarrage de Core.</p>
      </section>`;
    }

    function liveStatus(){return st.live&&st.live.core}
    function summaryCard(){
      const legs=savedLegs(),eff=p=>(effOf(p).value),core=liveStatus();
      let canon;
      if(!st.live||st.live.state==='loading')canon=['info','Lecture…'];
      else if(core&&core.ok){
        const store=core.data.available===false?null:(core.data.legs||{}).store;
        canon=core.data.available===false?['bad',`Indisponible (${core.data.reason_code||'raison inconnue'})`]
          :store?(store.status==='ok'?['ok','Active']:['bad',store.reason||store.reason_code||'Dégradée']):['ok','Active'];
      }else canon=['warn','Inconnu'];
      const recall=!eff('recall.enabled')?['off','Désactivé']:legs.semantic&&legs.semantic.status==='ok'?['ok','Par mots + sémantique']:['info','Par mots'];
      const modeField=field('consolidation.mode'),mode=eff('consolidation.mode');
      const modeLabel=modeField?(modeField.options.find(o=>o.id===mode)||{label:mode}).label:mode;
      const out=[eff('semantic.enabled')&&eff('semantic.allow_private')?'fournisseur d’embeddings':'',eff('tencent.enabled')&&eff('tencent.allow_private')?'sidecar Tencent':''].filter(Boolean);
      const priv=out.length?['warn','Envoyée au '+out.join(' et au ')]:['ok','Reste sur ce PC'];
      const row=(ico,label,[tone,text],attr)=>`<li><button type="button" class="mem-row" ${attr}>${icon(ico)}<span class="mem-row-k">${esc(label)}</span>`
        +`<span class="mem-row-v">${pill(tone,text)}</span>${icon('chevron')}</button></li>`;
      return `<section class="set-panel mem-card" aria-labelledby="memSumTitle">
        <div class="mem-head mem-head-2"><span class="set-medallion set-medallion-sm mem-medal sm">${icon('doc')}</span><h3 class="mem-title" id="memSumTitle">Résumé du système mémoire</h3></div>
        <ul class="mem-rows">
          ${row('db','Mémoire canonique',canon,'data-mem-center-tab="notes"')}
          ${row('brain','Rappel',recall,'data-mem-focus="memCardRecall"')}
          ${row('layers','Consolidation',[mode==='auto'?'info':'warn',modeLabel],'data-mem-focus="memCardConsolidation"')}
          ${row('shield','Mémoire privée',priv,'data-mem-focus="memCardSemantic"')}
        </ul>
        <p class="mem-hint">État enregistré. La mémoire canonique, ce sont vos notes Markdown ; les index de recherche en sont dérivés.</p>
      </section>`;
    }

    function liveCount(part,unit){
      if(!st.live||st.live.state==='loading')return 'Lecture…';
      const x=st.live[part];
      if(!x||!x.ok)return '— indisponible';
      if(part==='cands'&&x.available===false)return 'Revue non branchée';
      return `${x.capped?x.count+'+':x.count} ${unit}`;
    }
    function centerCard(){
      const tile=(tab,ico,title,sub)=>`<button type="button" class="mem-tile" data-mem-center-tab="${tab}"><span class="mem-tile-top">${icon(ico)}${icon('chevron')}</span><strong>${esc(title)}</strong><small>${esc(sub)}</small></button>`;
      const err=st.live&&st.live.state==='ready'&&!(st.live.core&&st.live.core.ok)
        ?`<p class="mem-hint warn" role="status">Compteurs indisponibles : ${esc(st.live.core&&st.live.core.error||'Core ne répond pas')}. <button type="button" class="mem-linkish" data-mem-live-retry>Réessayer</button></p>`:'';
      return `<section class="set-panel set-panel-hot mem-card mem-cta" aria-labelledby="memCtaTitle">
        <div class="mem-head"><span class="set-medallion mem-medal">${icon('nodes')}</span><div><h3 class="mem-title" id="memCtaTitle">Ouvrir le Memory Center</h3>
          <p class="mem-sub">Explorez vos notes, décidez des candidats et testez le rappel dans un espace dédié.</p></div>
          <button type="button" class="mem-cta-open" data-mem-center-tab="notes" aria-label="Ouvrir le Memory Center">${icon('chevron')}</button></div>
        <div class="mem-tiles">${tile('notes','doc','Notes',liveCount('notes','notes'))}${tile('candidates','star','Candidats',liveCount('cands','en attente'))}
          ${tile('recall','bars','Test de rappel','Évaluer la pertinence')}</div>${err}
      </section>`;
    }

    function advancedBand(){
      const n=problems();
      return `<section class="set-panel set-panel-quiet mem-card mem-adv" aria-labelledby="memAdvTitle">
        <span class="set-medallion mem-medal">${icon('wrench')}</span>
        <div><h3 class="mem-title" id="memAdvTitle">Avancé &amp; diagnostic</h3><p class="mem-sub">Réglages d’opérateur et diagnostics.</p></div>
        <p class="mem-adv-note">${icon('lock')}<span>Le délai du rappel, le sidecar Tencent et l’état détaillé des index sont réglés dans le mode avancé.
          ${n?`<strong class="mem-tone-bad">${n} point${n>1?'s':''} à vérifier.</strong>`:''}</span></p>
        <div class="mem-adv-actions"><button type="button" class="set-btn set-btn-sm mem-btn" data-mem-open="memory_advanced">Ouvrir les paramètres avancés ${icon('chevron')}</button>
          <button type="button" class="mem-linkish" data-mem-diagnostics>Voir le diagnostic mémoire</button></div>
      </section>`;
    }

    /* Barre d'enregistrement commune aux deux onglets : le brouillon est partagé, un seul envoi. */
    function saveBar(){
      const n=Object.keys(st.draft).length;
      const text=st.busy?'Enregistrement…':n?`${n} modification${n>1?'s':''} non enregistrée${n>1?'s':''}.`:'Tout est enregistré.';
      return `<div class="mem-messages">${restartHtml()}${messageHtml()}${elsewhereHtml()}</div>
        <div class="mem-savebar${n?' dirty':''}"><p class="mem-savebar-text" role="status">${esc(text)}</p>${actionsHtml()}</div>`;
    }

    function memoryHtml(){
      return `<div class="mem-page" id="memSection_${esc(opts.section||'recall')}" data-mem-view="memory">
        <div class="mem-grid"><div class="mem-col">${recallCard()}${consolidationCard()}</div>
          <div class="mem-col">${semanticCard()}${summaryCard()}${centerCard()}</div></div>
        ${saveBar()}${advancedBand()}</div>`;
    }

    /* ---------------------------------------------------------------- onglet « Connaissances »
       Préférence (réglage) ET disponibilité réelle (`/api/memory/status` de Core) : une source activée n'est
       « Active » que si Core la déclare saine ; sans fournisseur monté (graphe de code), elle est « Indisponible ». */
    /* [identifiant de carte, réglage, étage publié par Core (`knowledge:<AssetKind>` : `skill` au singulier), icône, texte]. */
    const SOURCES=Object.freeze([
      ['wiki','knowledge.wiki_enabled','knowledge:wiki','book','Pages du wiki proposées au cerveau comme connaissances.'],
      ['codegraph','knowledge.codegraph_enabled','knowledge:codegraph','code','Structure du code d’un dépôt, quand un fournisseur de dépôt est monté.'],
      ['skills','knowledge.skills_enabled','knowledge:skill','cube','Skills et loadouts disponibles pour les agents.'],
    ]);
    function sourceState(legKey,path){
      if(!current(path))return ['off','Désactivé',''];
      const core=liveStatus();
      if(!st.live||st.live.state==='loading')return ['info','Lecture…',''];
      if(!core||!core.ok)return ['warn','État inconnu',`Activé dans les réglages ; état réel inconnu : ${core&&core.error||'Core ne répond pas'}.`];
      if(core.data.available===false)return ['bad','Indisponible',`La mémoire n’est pas disponible côté Core (${core.data.reason_code||'raison inconnue'}).`];
      const leg=(core.data.legs||{})[legKey];
      if(!leg)return ['bad','Indisponible','Aucun fournisseur monté par Core pour cette source.'];
      if(leg.status==='ok')return own(st.draft,path)?['info','Activé (à enregistrer)','']:['ok','Actif',''];
      if(leg.status==='disabled')return ['off','Désactivé côté Core',leg.reason||''];
      return ['bad','Indisponible',`${leg.reason||''}${leg.reason_code?` (${leg.reason_code})`:''}`];
    }
    /* Sidecar Tencent : Désactivé (préférence) ; activé, son état réel vient de Core (Actif / Indisponible / inconnu). */
    function tencentState(){
      if(!effOf('tencent.enabled').value)return ['off','Désactivé'];
      const core=liveStatus();
      if(!st.live||st.live.state==='loading')return ['info','Lecture…'];
      if(!core||!core.ok||core.data.available===false)return ['warn','Activé · état inconnu'];
      const leg=(core.data.legs||{}).tencent;
      if(!leg)return ['bad','Indisponible'];
      return leg.status==='ok'?['ok','Actif']:leg.status==='disabled'?['off','Désactivé côté Core']:['bad',leg.status==='degraded'?'En panne':'Indisponible'];
    }
    function knowledgeHtml(){
      const cards=SOURCES.filter(([,p])=>has(p)).map(([kind,path,legKey,ico,text])=>{
        const f=field(path),[tone,label,why]=sourceState(legKey,path);
        return `<section class="set-panel mem-card mem-source" aria-labelledby="memSrc_${kind}">
          <div class="mem-head"><span class="set-medallion mem-medal">${icon(ico)}</span><div><h3 class="mem-title" id="memSrc_${kind}">${esc(f.label)}</h3><p class="mem-sub">${esc(text)}</p></div></div>
          ${why?`<p class="mem-hint${tone==='bad'?' bad':tone==='warn'?' warn':''}">${esc(why)}</p>`:''}
          <div class="mem-source-foot">${pill(tone,label)}${toggle(path)}</div>${hintOf(f)}</section>`;
      }).join('');
      const rules=Object.entries(st.memory.loadouts||{});
      const flags=r=>[r.wiki===false?'sans wiki':'',r.codegraph===false?'sans graphe de code':'',r.skills===false?'sans skills':'',r.allow_private?'mémoire privée autorisée':''].filter(Boolean).join(', ');
      const loadouts=rules.length?`<ul class="mem-loadouts">${rules.map(([k,r])=>`<li><code>${esc(k)}</code><span class="mem-hint">${(r.memory_scopes||[]).length} portée(s)${flags(r)?' · '+esc(flags(r)):''}</span></li>`).join('')}</ul>`
        :'<p class="mem-hint">Aucune règle personnalisée : les préréglages par agent s’appliquent (aucun sous-agent ne reçoit la mémoire privée).</p>';
      const live=st.live&&st.live.state==='ready'&&!(st.live.core&&st.live.core.ok)
        ?`<p class="mem-hint warn" role="status">État réel des sources indisponible. <button type="button" class="mem-linkish" data-mem-live-retry>Réessayer</button></p>`:'';
      return `<div class="mem-page" id="memSection_${esc(opts.section||'knowledge_sources')}" data-mem-view="knowledge">
        <p class="mem-text">Les connaissances enrichissent les réponses du cerveau sans jamais devenir de la mémoire canonique.
          Chaque source dit ce que vous avez choisi et ce que Core peut réellement fournir.</p>${live}
        <div class="mem-sources">${cards}</div>
        <section class="set-panel mem-card" aria-labelledby="memScopesTitle">${head('folder','Portées de la mémoire','Qui peut lire quoi','','memScopesTitle')}
          <ul class="mem-scopes"><li><strong>Privée</strong><span>Vous seul et le cerveau principal. Jamais envoyée à un fournisseur sans votre accord.</span></li>
            <li><strong>Partagée</strong><span>Ce que les agents peuvent lire pour vous aider.</span></li>
            <li><strong>Projet</strong><span>Rattachée à un projet ; lue par les agents qui travaillent dessus.</span></li></ul></section>
        <section class="set-panel mem-card" aria-labelledby="memLoadTitle" data-mem-loadouts>${head('users','Accès par agent','Ce que chaque agent peut lire','','memLoadTitle')}
          ${loadouts}<p class="mem-hint">Lecture seule ici ; les règles se définissent dans le fichier de réglages.</p></section>
        <section class="set-panel set-panel-quiet mem-card mem-adv" aria-labelledby="memExtTitle"><span class="set-medallion mem-medal">${icon('cloud')}</span>
          <div><h3 class="mem-title" id="memExtTitle">Source externe</h3><p class="mem-sub">Sidecar Tencent : réglage d’opérateur.</p></div>
          <p class="mem-adv-note">${icon('lock')}<span>Son adresse, son identifiant et son état vivent dans Avancé &amp; diagnostic ${pill(...tencentState())}</span></p>
          <div class="mem-adv-actions"><button type="button" class="set-btn set-btn-sm mem-btn" data-mem-open="memory_advanced">Ouvrir les paramètres avancés ${icon('chevron')}</button>
            <button type="button" class="mem-linkish" data-mem-diagnostics>Voir le diagnostic mémoire</button></div></section>
        ${saveBar()}</div>`;
    }

    /* État vivant (Core) : une lecture par ouverture des Réglages, partagée par les vues. Chaque partie échoue seule. */
    function loadLive(force){
      if(st.live&&st.live.pending&&!force)return st.live.pending;
      if(st.live&&st.live.state==='ready'&&!force)return Promise.resolve(st.live);
      const live={state:'loading',core:null,notes:null,cands:null};st.live=live;
      const fail=e=>({ok:false,error:(e&&e.message||String(e))+(e&&e.code?` (${e.code})`:'')});
      live.pending=Promise.allSettled([fetchJson('/api/memory/status'),fetchJson('/api/memory/notes?limit=200'),fetchJson('/api/memory/candidates?state=proposed&limit=200')])
        .then(([s,n,c])=>{
          live.core=s.status==='fulfilled'?{ok:true,data:s.value}:fail(s.reason);
          live.notes=n.status==='fulfilled'?{ok:true,count:(n.value.notes||[]).length,capped:(n.value.notes||[]).length>=200}:fail(n.reason);
          live.cands=c.status==='fulfilled'?{ok:true,count:(c.value.candidates||[]).length,capped:(c.value.candidates||[]).length>=200,available:c.value.available!==false}:fail(c.reason);
          if(!live.core.ok)console.warn('memory_settings_live_unavailable',{error:live.core.error});
          live.state='ready';live.pending=null;renderAll();return live;
        });
      renderAll();
      return live.pending;
    }

    /* Chaque rendu remplace la vue : le contrôle qui avait le focus le reprend (`keepFocus` du shell). */
    function render(){
      if(dead)return;
      if(!st.memory){host.innerHTML='<div class="empty">Chargement…</div>';return}
      const body={memory:memoryHtml,knowledge:knowledgeHtml,diagnostics:diagnosticsHtml}[mode]||fieldsHtml;
      const draw=()=>{host.innerHTML=`<div class="mem-settings">${body()}</div>`;bind()};
      if(typeof ui.keepFocus==='function')ui.keepFocus(host,draw);else draw();
    }
    function coerce(el,f){
      if(f.type==='bool')return el.tagName==='BUTTON'?el.getAttribute('aria-checked')==='true':!!el.checked;
      if(f.type==='int'||f.type==='float'){if(el.value.trim()==='')return stored(f.path);const n=Number(el.value);return f.type==='int'?Math.trunc(n):n}
      return f.type==='text'||f.type==='id'?el.value.trim():el.value;
    }
    function set(p,v){if(v===stored(p))delete st.draft[p];else st.draft[p]=v}
    function bind(){
      host.querySelectorAll('[data-mem]').forEach(el=>{const sw=el.tagName==='BUTTON';el.addEventListener(sw?'click':'change',()=>{
        if(sw){if(el.disabled)return;ui.setToggle(el,el.getAttribute('aria-checked')!=='true')}
        const f=field(el.dataset.mem);set(f.path,coerce(el,f));
        st.message=null;st.restart=false;
        /* Un choix qui rend un autre réglage incohérent le ramène à l'état sûr (même dans une autre section). */
        if(current('semantic.provider')==='none'&&current('semantic.enabled'))set('semantic.enabled',false);
        if(!current('semantic.enabled')&&current('consolidation.mode')==='auto')set('consolidation.mode','manual');
        if(!String(current('tencent.url')||'').trim()&&current('tencent.enabled'))set('tencent.enabled',false);
        const id=el.id;render();const again=id&&host.querySelector('#'+id);if(again&&again.focus&&!(again.ownerDocument&&again===again.ownerDocument.activeElement))again.focus();
      })});
      const on=(sel,fn)=>host.querySelectorAll(sel).forEach(el=>el.addEventListener('click',()=>fn(el)));
      on('[data-mem-save]',()=>submit());
      on('[data-mem-reset]',()=>{if(!dirty()||st.busy)return;st.draft={};st.message=null;render()});
      on('[data-mem-diagnostics]',()=>{if(opts.openDiagnostics)opts.openDiagnostics()});
      on('[data-mem-open]',el=>{if(opts.open)opts.open(el.dataset.memOpen)});
      /* Curseurs : la valeur affichée suit le pouce pendant le geste ; le brouillon change au relâchement (`change`). */
      host.querySelectorAll('[data-mem-range]').forEach(el=>el.addEventListener('input',()=>{
        const f=field(el.dataset.mem),out=host.querySelector(`[data-mem-out="${el.dataset.mem}"]`);
        el.style.setProperty('--set-range-fill',fill(f,el.value));
        const text=f.type==='float'?percent(el.value):String(el.value);el.setAttribute('aria-valuetext',text);
        if(out)out.innerHTML=out.dataset.memMax?`${esc(el.value)} <small>/ ${esc(out.dataset.memMax)}</small>`:esc(text);
      }));
      on('[data-mem-center-tab]',el=>{
        if(opts.openCenter)return opts.openCenter(el.dataset.memCenterTab);
        if(root.JarvisMemoryCenter&&root.JarvisMemoryCenter.open)root.JarvisMemoryCenter.open(el.dataset.memCenterTab);
      });
      on('[data-mem-focus]',el=>{const card=host.querySelector('#'+el.dataset.memFocus);if(!card)return;
        if(card.scrollIntoView)card.scrollIntoView({block:'nearest',behavior:'smooth'});if(ui.landFocus)ui.landFocus(card);else card.focus()});
      on('[data-mem-live-retry]',()=>{loadLive(true)});
    }

    /* Correctif à plat -> imbriqué : `{recall:{enabled:false}}`. Seuls les champs modifiés partent. */
    function patch(){
      const out={};
      for(const [p,v] of Object.entries(st.draft)){const [s,n]=p.split('.');(out[s]=out[s]||{})[n]=v}
      return out;
    }
    /* Une lecture par état partagé : une vue montée pendant la lecture attend la même réponse. */
    async function load(){
      if(!st.memory){
        if(!st.loading){
          st.loading=fetchJson('/api/settings').then(data=>{st.memory=data.memory;st.draft={};return st.memory})
            .finally(()=>{st.loading=null;renderAll()});
        }
        const pending=st.loading;
        render();
        await pending;
      }
      if(!dead&&(mode==='memory'||mode==='knowledge'))loadLive();
      render();return st.memory;
    }
    async function submit(){
      if(!dirty()||st.busy)return;
      const needed=restartHit().length>0;
      st.busy=true;st.message=null;render();
      try{
        const data=await fetchJson('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({memory:patch()})});
        st.memory=data.memory;st.draft={};st.restart=needed;st.message={tone:'ok',text:'Réglages mémoire enregistrés.'};
      }catch(e){
        st.message={tone:'bad',text:(e.message||'Enregistrement refusé.')+(e.code?' ('+e.code+')':'')+' Rien n’a été écrit.'};
      }finally{st.busy=false;renderAll()}
    }
    function renderAll(){[...st.views].forEach(draw=>draw())}
    function destroy(){dead=true;st.views.delete(render)}
    injectStyle();
    host.setAttribute('data-memory-settings','1');
    st.views.add(render);
    render();
    return {load,loadLive,render,state:st,patch,submit,destroy,get destroyed(){return dead}};
  }

  root.JarvisMemorySettings=Object.freeze({mountId:MOUNT_ID,mount:()=>root.document?root.document.getElementById(MOUNT_ID):null,
    create,createStore,icon,ICONS,STYLE_ID});
})(typeof window!=='undefined'?window:globalThis);
