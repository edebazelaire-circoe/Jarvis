/* Memory Center du Control Center (jarvis-memory-intelligence-knowledge, Slice 12 ; refonte-ui-settings, Slice 06).

   Atelier d'inspection et de décision, monté dans l'onglet « Memory Center » de Réglages › Mémoire & connaissances
   (section `memory_center`, maquette `tasks/refonte-ui-settings/references/ui/05-memory-center.png`). Il n'a plus
   de seconde maison : le bouton « Memory Center » de Sessions & Boards ouvre cet onglet (`open`).

   Données : `/api/memory/*` (relais de `/v1/memory/*`) et la section `memory` de `/api/settings` (réglages
   essentiels et loadouts, en LECTURE). Seule écriture : la décision d'un candidat
   (`POST /api/memory/candidates/{id}/decision`), après confirmation, appliquée de façon optimiste (la carte quitte la
   file tout de suite, revient avec la raison réelle si Core refuse : 404, 409 déjà décidé, 403, 503…).

   Règle d'affichage : ce qui est canonique (notes Markdown) et ce qui est dérivé (index, résultats de recherche,
   aperçu du rappel, état des étages) ne se confondent jamais ; chaque zone porte sa pastille. Aucun compteur,
   score ou niveau n'est inventé : ce que Core ne donne pas n'est pas affiché (pas de « taux de rappel », pas de
   rétention en pourcentage — la rétention est une classe). Les réglages essentiels sont des projections en lecture
   seule avec un lien vers leur seule place éditable (onglet Mémoire) : aucune seconde copie modifiable. */
(function(root){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const TABS=Object.freeze([['notes','Notes','doc'],['candidates','Candidats','users'],['knowledge','Connaissances','layers'],['recall','Test de rappel','bars']]);
  const LEVELS=Object.freeze({L0:'Preuve brute',L1:'Fait atomique',L2:'Scénario',L3:'Profil stable'});
  const RETENTIONS=Object.freeze({short_term_memory:'Court terme',long_term_memory:'Long terme',traumatic_memory:'Traumatique',eternal_memory:'Éternelle',plastic_memory:'Plastique'});
  const KINDS=Object.freeze({fact:'Fait',preference:'Préférence',scenario:'Scénario',profile:'Profil',episode:'Épisode'});
  const SOURCES=Object.freeze({turn:'Tour',session:'Session',artifact:'Artefact',agent:'Agent',user:'Utilisateur',import:'Import',note:'Note'});
  const CAND_STATES=Object.freeze({proposed:'À décider',accepted:'Accepté',rejected:'Rejeté',superseded_by_newer:'Remplacé par un plus récent'});
  const LEG_LABEL=Object.freeze({store:'Notes Markdown',lexical:'Lexical',semantic:'Sémantique',tencent:'Tencent',
    'knowledge:wiki':'Wiki','knowledge:codegraph':'Graphe de code','knowledge:skills':'Skills'});
  const LEG_ICON=Object.freeze({store:'doc',lexical:'doc',semantic:'nodes',tencent:'cloud','knowledge:wiki':'book','knowledge:codegraph':'code','knowledge:skills':'cube'});
  const STATUS=Object.freeze({ok:['Actif','mc-ok'],disabled:['Désactivé','mc-off'],unavailable:['Indisponible','mc-bad'],degraded:['Dégradé','mc-warn']});
  const DEGRADED=Object.freeze({index_syncing:'Index en synchronisation',recall_timeout:'Délai de rappel dépassé',semantic_unavailable:'Étage sémantique indisponible'});
  const PAGE_SIZE=10,COUNT_LIMIT=200,RAIL_CANDS=3;
  const STYLE_ID='jarvisMemoryCenterStyle';
  const STYLE=`
.mcw{--mc-hue:var(--accent);--mc-violet:var(--role-accent-violet,#b9a2ff);--mc-line:color-mix(in srgb,var(--mc-hue) 22%,var(--set-hair-2,#1b3442));
  --mc-hair:var(--set-hair-2,#24414f);--mc-hair-1:var(--set-hair,rgba(151,191,209,.13));--mc-glass:var(--shell-glass-strong,rgba(4,10,15,.8));
  --mc-ink-2:var(--set-ink-2,#a9c2cf);--mc-ink-3:var(--set-ink-3,#8aa5b3);
  container-type:inline-size;display:grid;gap:14px;min-width:0;color:var(--set-ink,var(--text));font-size:13px;line-height:1.45}
.mcw *{box-sizing:border-box}
.mcw .sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.mcw .mem-ico{width:18px;height:18px;flex:none;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.mc-card{position:relative;display:grid;gap:12px;align-content:start;min-width:0;container-type:inline-size;padding:16px 18px;border:1px solid var(--mc-line);border-radius:14px;
  background:radial-gradient(120% 90% at 0% 0%,color-mix(in srgb,var(--mc-hue) 6%,transparent),transparent 55%),var(--mc-glass);box-shadow:inset 0 1px 0 rgba(255,255,255,.035)}
.mc-cardhead{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;align-items:center}
.mc-cardhead h3{margin:0;font-size:16px;font-weight:600;line-height:1.25}
.mc-cardhead p{margin:2px 0 0;color:var(--mc-ink-2);font-size:12.5px}
.mc-medal{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;color:var(--mc-hue);border:1.5px solid color-mix(in srgb,var(--mc-hue) 60%,transparent);
  background:radial-gradient(circle at 50% 40%,color-mix(in srgb,var(--mc-hue) 18%,transparent),transparent 72%);box-shadow:0 0 14px color-mix(in srgb,var(--mc-hue) 22%,transparent)}
.mc-medal .mem-ico{width:21px;height:21px}
.mc-hero{grid-template-columns:minmax(0,1fr);align-items:center;gap:16px;padding:18px 20px;border-color:color-mix(in srgb,var(--mc-hue) 45%,transparent);
  background:radial-gradient(90% 140% at 0% 50%,color-mix(in srgb,var(--mc-hue) 14%,transparent),transparent 60%),var(--mc-glass);
  box-shadow:0 0 0 1px color-mix(in srgb,var(--mc-hue) 12%,transparent),0 0 30px color-mix(in srgb,var(--mc-hue) 12%,transparent)}
.mc-hero-id{display:grid;grid-template-columns:auto minmax(0,1fr);gap:16px;align-items:center}
.mc-hero-id .mc-medal{width:64px;height:64px}.mc-hero-id .mc-medal .mem-ico{width:30px;height:30px}
.mc-hero h2{margin:0;font-size:24px;font-weight:600;letter-spacing:-.01em;line-height:1.15}
.mc-hero-id p{margin:4px 0 0;color:var(--mc-ink-2);max-width:56ch}
.mc-stats{display:grid;gap:10px;grid-template-columns:repeat(2,minmax(0,1fr));margin:0;padding:0;list-style:none}
.mc-stat{display:grid;gap:4px;align-content:start;min-height:88px;padding:10px 12px;border:1px solid var(--mc-line);border-radius:12px;background:rgba(3,9,13,.55)}
.mc-stat .mem-ico{width:22px;height:22px;color:var(--mc-violet)}
.mc-stat strong{font-size:22px;font-weight:600;line-height:1.1;font-variant-numeric:tabular-nums}
.mc-stat strong.sm{font-size:15px}
.mc-stat span{font-size:12px;color:var(--mc-ink-2)}
@container (min-width:620px){.mc-stats{grid-template-columns:repeat(4,minmax(0,1fr))}}
@container (min-width:860px){.mc-hero{grid-template-columns:minmax(0,.9fr) minmax(0,1.4fr)}}
.mc-tabs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.mc-tab{display:flex;align-items:center;justify-content:center;gap:10px;min-height:42px;padding:6px 10px;border:1px solid var(--mc-hair);border-radius:10px;
  background:rgba(3,9,13,.45);color:var(--mc-ink-2);font:inherit;font-size:13.5px;cursor:pointer;white-space:nowrap;overflow:hidden}
.mc-tab:hover{border-color:color-mix(in srgb,var(--mc-violet) 50%,transparent);color:var(--set-ink,var(--text))}
.mc-tab[aria-selected=true]{color:var(--set-ink,var(--text));border-color:var(--mc-violet);background:color-mix(in srgb,var(--mc-violet) 16%,rgba(3,9,13,.5));
  box-shadow:0 0 0 1px color-mix(in srgb,var(--mc-violet) 35%,transparent),0 0 16px color-mix(in srgb,var(--mc-violet) 25%,transparent)}
.mc-tab[aria-selected=true] .mem-ico{color:var(--mc-violet)}
.mc-tab-n{display:inline-grid;place-items:center;min-width:22px;height:20px;padding:0 6px;border-radius:999px;background:color-mix(in srgb,var(--mc-violet) 30%,transparent);font-size:11.5px;font-weight:600;color:var(--set-ink,var(--text))}
@container (max-width:560px){.mc-tabs{grid-template-columns:repeat(2,minmax(0,1fr))}}
.mc-work{display:grid;gap:14px;grid-template-columns:minmax(0,1fr);align-items:start}
.mc-main,.mc-rail{display:grid;gap:14px;align-content:start;min-width:0}
@container (min-width:860px){.mc-work.with-rail{grid-template-columns:minmax(0,1.9fr) minmax(260px,1fr)}}
.mc-filters{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.mc-search{display:flex;align-items:center;gap:8px;flex:1 1 200px;min-width:0;height:36px;padding:0 10px;border:1px solid var(--mc-hair);border-radius:9px;background:rgba(3,9,13,.5)}
.mc-search .mem-ico{width:16px;height:16px;color:var(--mc-ink-3)}
.mc-search input{flex:1;min-width:0;height:100%;border:0;background:transparent;color:inherit;font:inherit}
.mc-search input:focus-visible{outline:none}.mc-search:has(input:focus-visible){outline:2px solid var(--accent);outline-offset:2px}
.mc-select{height:36px;max-width:100%;padding:0 8px;border:1px solid var(--mc-hair);border-radius:9px;background:rgba(3,9,13,.5);color:inherit;font:inherit;font-size:12.5px}
.mc-select option{background:#08121a}
.mc-check{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--mc-ink-2)}
.mc-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:34px;padding:5px 12px;border:1px solid color-mix(in srgb,var(--accent) 40%,transparent);border-radius:9px;
  background:rgba(3,9,13,.5);color:var(--set-ink,var(--text));font:inherit;font-size:12.5px;cursor:pointer;white-space:nowrap}
.mc-btn:hover{border-color:var(--accent);box-shadow:0 0 10px color-mix(in srgb,var(--accent) 22%,transparent)}
.mc-btn:disabled,.mc-btn[aria-disabled=true]{opacity:.6;cursor:not-allowed;box-shadow:none}
.mc-btn .mem-ico{width:15px;height:15px}
.mc-btn.primary{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 18%,rgba(3,9,13,.5));font-weight:600}
.mc-btn.ok{border-color:color-mix(in srgb,var(--ok) 55%,transparent);color:var(--ok)}
.mc-btn.bad{border-color:color-mix(in srgb,var(--danger) 55%,transparent);color:var(--danger)}
.mc-link{padding:0;border:0;background:none;color:var(--accent);font:inherit;font-size:12.5px;text-decoration:underline;text-underline-offset:2px;cursor:pointer}
.mc-tablewrap{min-width:0;overflow-x:auto;container-type:inline-size}
.mc-table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:12.5px}
.mc-table th{padding:8px 8px;border-bottom:1px solid var(--mc-hair);color:var(--mc-ink-2);font-weight:500;text-align:left;white-space:nowrap}
.mc-table td{padding:9px 8px;border-bottom:1px solid var(--mc-hair-1);vertical-align:middle;min-width:0}
.mc-table tbody tr:hover{background:rgba(110,231,255,.04)}
.mc-table tbody tr.on{background:color-mix(in srgb,var(--mc-violet) 10%,transparent)}
.mc-table .c-note{width:auto}.mc-table .c-lvl{width:58px}.mc-table .c-kind{width:96px}.mc-table .c-scope{width:92px}.mc-table .c-ret{width:96px}.mc-table .c-date{width:86px}.mc-table .c-act{width:40px}
.mc-notebtn{display:grid;gap:2px;width:100%;padding:0;border:0;background:none;color:inherit;font:inherit;text-align:left;cursor:pointer}
.mc-notebtn strong{font-weight:500;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.mc-notebtn span{color:var(--mc-ink-3);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mc-ellip{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mc-date{color:var(--mc-ink-2);font-variant-numeric:tabular-nums;line-height:1.3}
.mc-lvl{display:inline-grid;place-items:center;min-width:32px;height:24px;padding:0 6px;border:1px solid currentColor;border-radius:7px;font-size:11.5px;font-weight:700;
  background:color-mix(in srgb,currentColor 12%,transparent)}
.mc-lvl-L0{color:var(--mc-ink-2)}.mc-lvl-L1{color:var(--ok)}.mc-lvl-L2{color:var(--role-accent-sky,#74c6ff)}.mc-lvl-L3{color:var(--mc-violet)}
.mc-iconbtn{display:grid;place-items:center;width:30px;height:30px;padding:0;border:1px solid transparent;border-radius:8px;background:none;color:var(--mc-ink-2);cursor:pointer}
.mc-iconbtn:hover{border-color:var(--mc-hair);color:var(--set-ink,var(--text))}
@container (max-width:720px){.mc-table .c-scope,.mc-table .c-ret{display:none}}
@container (max-width:430px){.mc-table .c-kind,.mc-table .c-date{display:none}}
.mc-foot{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 12px;color:var(--mc-ink-2);font-size:12.5px}
.mc-pages{display:flex;align-items:center;gap:6px}
.mc-page{display:inline-grid;place-items:center;min-width:34px;height:32px;padding:0 8px;border:1px solid var(--mc-hair);border-radius:8px;background:rgba(3,9,13,.45);color:inherit;font:inherit;cursor:pointer}
.mc-page[aria-current=page]{border-color:var(--accent);color:var(--set-ink,var(--text));background:color-mix(in srgb,var(--accent) 18%,transparent);font-weight:600}
.mc-page:disabled{opacity:.45;cursor:not-allowed}
.mc-chip{display:inline-flex;align-items:center;gap:5px;padding:1px 8px;border:1px solid var(--mc-hair);border-radius:999px;font-size:11.5px;font-weight:600;color:var(--mc-ink-2);white-space:nowrap}
.mc-chip.canon{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 40%,transparent)}
.mc-chip.derived{color:var(--role-accent-sky,#74c6ff);border-color:color-mix(in srgb,var(--role-accent-sky,#74c6ff) 40%,transparent)}
.mc-chip.prop{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 40%,transparent)}
.mc-count{display:inline-grid;place-items:center;min-width:26px;height:24px;padding:0 7px;border-radius:999px;background:color-mix(in srgb,var(--mc-violet) 30%,transparent);color:var(--set-ink,var(--text));font-weight:700;font-size:12px}
.mc-cands{display:grid;gap:8px;margin:0;padding:0;list-style:none}
.mc-cand{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 10px;align-items:center;padding:10px 12px;border:1px solid var(--mc-hair);border-radius:10px;background:rgba(3,9,13,.45)}
.mc-cand.pending{opacity:.6}
.mc-cand-t{margin:0;font-size:12.5px;line-height:1.4}
.mc-cand-m{grid-column:1;display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;color:var(--mc-ink-3);font-size:11.5px}
.mc-cand-a{grid-row:1/3;grid-column:2;display:grid;gap:6px}
.mc-cand-confirm{grid-column:1/-1;display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding-top:8px;border-top:1px dashed var(--mc-hair)}
.mc-cand-confirm p{flex:1 1 180px;margin:0;font-size:12px;color:var(--set-ink,var(--text))}
.mc-cand-err{grid-column:1/-1;margin:0;color:var(--danger);font-size:12px}
.mc-cand-body{grid-column:1/-1;display:grid;gap:6px;padding-top:8px;border-top:1px solid var(--mc-hair-1);font-size:12px;color:var(--mc-ink-2)}
.mc-cand-body pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;color:var(--set-ink,var(--text))}
@container (min-width:860px){.mc-cand.full{grid-template-columns:minmax(0,1fr) auto}.mc-cand.full .mc-cand-a{grid-auto-flow:column}}
.mc-recallform{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:end}
.mc-recallform label{grid-column:1/-1;font-size:12.5px;font-weight:600}
.mc-input{height:38px;min-width:0;padding:0 10px;border:1px solid var(--mc-hair);border-radius:9px;background:rgba(3,9,13,.5);color:inherit;font:inherit}
.mc-results{display:grid;gap:6px;margin:0;padding:0;list-style:none}
.mc-result{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:4px 10px;align-items:center;padding:7px 2px;border-bottom:1px solid var(--mc-hair-1)}
.mc-result .mc-notebtn strong{-webkit-line-clamp:2}
.mc-score{display:grid;justify-items:end;gap:3px;min-width:70px;font-variant-numeric:tabular-nums;font-size:12px}
.mc-bar{width:70px;height:5px;border-radius:999px;background:rgba(113,144,160,.22);overflow:hidden}
.mc-bar i{display:block;height:100%;background:var(--accent);border-radius:inherit}
.mc-why{grid-column:2/-1;margin:0;color:var(--mc-ink-2);font-size:12px}
.mc-legs{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(76px,1fr));margin:0;padding:0;list-style:none}
.mc-leg{display:grid;justify-items:center;gap:4px;padding:10px 6px;border:1px solid var(--mc-hair);border-radius:10px;background:rgba(3,9,13,.45);text-align:center;font-size:12px}
.mc-leg .mem-ico{width:20px;height:20px;color:var(--mc-hue)}
.mc-state{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600}
.mc-dot{width:8px;height:8px;border-radius:50%;background:currentColor;box-shadow:0 0 7px currentColor;flex:none}
.mc-ok{color:var(--ok)}.mc-off{color:var(--mc-ink-3)}.mc-bad{color:var(--danger)}.mc-warn{color:var(--warn)}.mc-info{color:var(--accent)}
.mc-essentials{display:grid;gap:10px;grid-template-columns:repeat(2,minmax(0,1fr))}
@container (min-width:700px){.mc-essentials{grid-template-columns:repeat(4,minmax(0,1fr))}}
.mc-ess{display:grid;gap:6px;align-content:start;padding:12px;border:1px solid var(--mc-hair);border-radius:10px;background:rgba(3,9,13,.45)}
.mc-ess-h{display:flex;align-items:center;gap:8px;font-weight:600;font-size:13px}
.mc-ess-h .mem-ico{color:var(--mc-hue)}
.mc-ess p{margin:0;color:var(--mc-ink-2);font-size:12px}
.mc-loading{display:flex;align-items:center;gap:8px;padding:10px 0;color:var(--mc-ink-2);font-size:12.5px}
.mc-spin{width:14px;height:14px;flex:none;border-radius:50%;border:2px solid color-mix(in srgb,var(--accent) 25%,transparent);border-top-color:var(--accent);animation:mcSpin .8s linear infinite}
@keyframes mcSpin{to{transform:rotate(360deg)}}
.mc-empty{margin:0;padding:14px;border:1px dashed var(--mc-hair);border-radius:10px;color:var(--mc-ink-2);font-size:12.5px;text-align:center}
.mc-error{display:grid;gap:8px;justify-items:start;padding:12px 14px;border:1px solid color-mix(in srgb,var(--danger) 40%,transparent);border-radius:10px;background:rgba(255,101,119,.06);font-size:12.5px}
.mc-note{display:grid;gap:4px 0;margin:0;padding:0}
.mc-note dt{color:var(--mc-ink-3);font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;margin-top:8px}
.mc-note dd{margin:0}
.mc-dialog{width:min(640px,calc(100vw - 32px));max-height:calc(100vh - 64px);padding:0;border:1px solid var(--mc-line);border-radius:14px;background:var(--solid,#070d13);color:var(--set-ink,var(--text));
  box-shadow:0 30px 80px rgba(0,0,0,.6)}
.mc-dialog::backdrop{background:rgba(2,6,9,.6);backdrop-filter:blur(3px)}
.mc-dialog-in{display:grid;gap:12px;padding:20px 22px;font:13px/1.5 var(--set-font,system-ui)}
.mc-dialog h3{margin:0;font-size:17px}
.mc-dialog pre{margin:0;padding:12px 14px;max-height:36vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;border:1px solid var(--mc-hair);border-radius:9px;background:#060d12;font:12.5px/1.6 var(--set-mono,monospace)}
.mc-dialog-x{position:absolute;top:12px;right:12px}
.mc-row2{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px}
.mc-kv{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 14px;margin:0;font-size:12.5px}
.mc-kv dt{color:var(--mc-ink-3)}.mc-kv dd{margin:0;min-width:0;overflow-wrap:anywhere}
.mc-sources{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
@media (prefers-reduced-motion:reduce){.mc-spin{animation:none}.mcw *{transition:none!important}}
`;

  const label=(map,key)=>map[key]||String(key??'—');
  const day=v=>v?esc(String(v).slice(0,10).split('-').reverse().join('/')):'—';
  const hour=v=>v&&String(v).length>15?esc(String(v).slice(11,16)):'';
  const q=obj=>Object.entries(obj).filter(([,v])=>v!==''&&v!==false&&v!=null).map(([k,v])=>`${encodeURIComponent(k)}=${encodeURIComponent(v===true?'1':v)}`).join('&');
  const icon=(name,cls)=>root.JarvisMemorySettings&&root.JarvisMemorySettings.icon?root.JarvisMemorySettings.icon(name,cls):'';
  function injectStyle(){
    const doc=root.document;
    if(!doc||!doc.head||doc.getElementById(STYLE_ID))return;
    const el=doc.createElement('style');el.id=STYLE_ID;el.textContent=STYLE;doc.head.appendChild(el);
  }

  function create(host,options){
    const opts=options||{};
    const fetchJson=opts.fetch||(async(path,init)=>{
      const r=await root.fetch(path,init),text=await r.text();let body={};try{body=text?JSON.parse(text):{}}catch{body={error:{message:text}}}
      if(!r.ok){const err=body.error||{};const e=new Error(typeof err==='string'?err:(err.message||'HTTP '+r.status));e.code=err.code||'';e.status=r.status;throw e}
      return body;
    });
    const fail=e=>({status:'error',error:(e&&e.message||'Erreur inconnue')+(e&&e.code?' ('+e.code+')':'')});
    const st={tab:TABS.some(([k])=>k===opts.tab)?opts.tab:'notes',focus:null,announce:'',
      live:{status:'idle',data:null,error:''},
      count:{status:'idle',notes:null,capped:false},
      notes:{status:'idle',items:[],q:'',hits:null,level:'',retention:'',kind:'',superseded:false,page:0,more:false,error:''},
      note:{id:null,status:'idle',data:null,error:''},
      cands:{status:'idle',items:[],available:true,filter:'proposed',error:'',confirm:null,pending:{},errors:{},open:null,detail:{}},
      settings:{status:'idle',memory:null,error:''},
      recall:{q:'',max:6,status:'idle',data:null,error:''}};
    let dead=false;
    const say=t=>{st.announce=t};
    const proposedCount=()=>st.cands.filter==='proposed'?st.cands.items.filter(c=>c.state==='proposed'&&!st.cands.pending[c.id]).length:null;

    /* ------------------------------------------------------------ chargements (chacun échoue seul) */
    async function loadLive(){
      const l=st.live;l.status='loading';l.error='';render();
      try{l.data=await fetchJson('/api/memory/status');l.status='ready'}catch(e){Object.assign(l,fail(e))}
      render();
    }
    async function loadCount(){
      const c=st.count;c.status='loading';
      try{const d=await fetchJson('/api/memory/notes?'+q({limit:COUNT_LIMIT}));const n=(d.notes||[]).length;c.notes=n;c.capped=n>=COUNT_LIMIT;c.status='ready'}
      catch(e){Object.assign(c,fail(e))}
      render();
    }
    async function loadNotes(){
      const n=st.notes;n.status='loading';n.error='';render();
      try{
        if(n.q.trim()){
          const d=await fetchJson('/api/memory/search?'+q({q:n.q.trim(),level:n.level,retention:n.retention,limit:30}));
          n.hits=d.hits||[];n.items=[];n.more=false;
        }else{
          const d=await fetchJson('/api/memory/notes?'+q({limit:PAGE_SIZE+1,offset:n.page*PAGE_SIZE,level:n.level,retention:n.retention,kind:n.kind,include_superseded:n.superseded}));
          const list=d.notes||[];n.more=list.length>PAGE_SIZE;n.items=list.slice(0,PAGE_SIZE);n.hits=null;
        }
        n.status='ready';say(`${(n.hits||n.items).length} note(s) affichée(s).`);
      }catch(e){Object.assign(n,fail(e));n.hits=null}
      render();
    }
    async function loadCands(){
      const c=st.cands;c.status='loading';c.error='';render();
      try{
        const d=await fetchJson('/api/memory/candidates?'+q({state:c.filter,limit:COUNT_LIMIT}));
        c.items=d.candidates||[];c.available=d.available!==false;c.status='ready';c.errors={};
      }catch(e){Object.assign(c,fail(e))}
      render();
    }
    async function loadSettings(){
      const s=st.settings;s.status='loading';s.error='';render();
      try{const d=await fetchJson('/api/settings');s.memory=d.memory||null;s.status='ready'}catch(e){Object.assign(s,fail(e))}
      render();
    }
    async function openNote(id){
      const s=st.note;s.id=id;s.status='loading';s.error='';s.data=null;render();showDialog();
      try{const d=await fetchJson('/api/memory/notes/'+encodeURIComponent(id));if(s.id!==id)return;s.data=d.note;s.status='ready'}
      catch(e){if(s.id!==id)return;Object.assign(s,fail(e))}
      render();
    }
    function closeNote(){
      const id=st.note.id;st.note={id:null,status:'idle',data:null,error:''};
      const dlg=dialogEl();if(dlg&&dlg.open&&dlg.close)dlg.close();
      st.focus=id?`[data-act="note"][data-id="${id}"]`:null;render();
    }
    async function toggleCand(id){
      const c=st.cands;c.open=c.open===id?null:id;render();
      if(c.open&&!c.detail[id]){
        try{const d=await fetchJson('/api/memory/candidates/'+encodeURIComponent(id));c.detail[id]=d.candidate}
        catch(e){c.detail[id]={error:fail(e).error}}
        render();
      }
    }
    function askDecision(id,decision){const c=st.cands;c.confirm={id,decision};delete c.errors[id];st.focus=`[data-act="decide"][data-id="${id}"]`;render()}
    function cancelDecision(){const c=st.cands,k=c.confirm;c.confirm=null;st.focus=k?`[data-act="cand-${k.decision}"][data-id="${k.id}"]`:null;render()}
    /* Optimiste : la carte quitte la file (et les compteurs) avant la réponse ; un refus la remet, avec sa raison. */
    async function decide(){
      const c=st.cands,k=c.confirm;if(!k||c.pending[k.id])return;
      const cand=c.items.find(x=>x.id===k.id);c.confirm=null;c.pending[k.id]=k.decision;
      say(k.decision==='accept'?`Acceptation de « ${cand?cand.title:k.id} »…`:`Rejet de « ${cand?cand.title:k.id} »…`);render();
      try{
        const d=await fetchJson(`/api/memory/candidates/${encodeURIComponent(k.id)}/decision`,
          {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:k.decision})});
        const done=d.candidate||{};delete c.pending[k.id];
        if(c.filter==='proposed')c.items=c.items.filter(x=>x.id!==k.id);else c.items=c.items.map(x=>x.id===k.id?{...x,...done}:x);
        say(k.decision==='accept'?`Accepté : note canonique ${done.committed_memory_id||''} créée.`:'Candidat rejeté ; aucune note créée.');
        if(k.decision==='accept'){if(st.count.status==='ready'&&!st.count.capped)st.count.notes++;if(st.notes.status!=='idle')loadNotes()}
      }catch(e){
        delete c.pending[k.id];
        c.errors[k.id]=`Décision refusée : ${e.message||'erreur'}${e.code?' ('+e.code+')':''}. Rien n’a été modifié.`;
        say(c.errors[k.id]);st.focus=`[data-act="cand-${k.decision}"][data-id="${k.id}"]`;
        if(root.console)root.console.warn('memory_center_decision_refused',{candidate:k.id,code:e.code||'',status:e.status||0});
      }
      render();
    }
    async function runRecall(){
      const r=st.recall;if(!r.q.trim()){r.status='error';r.error='Saisissez une phrase à tester.';render();return}
      r.status='loading';r.error='';r.data=null;render();
      try{r.data=await fetchJson('/api/memory/recall-explain?'+q({q:r.q.trim(),max_items:r.max}));r.status='ready';say(`${(r.data.items||[]).length} souvenir(s) rappelé(s).`)}
      catch(e){Object.assign(r,fail(e))}
      st.focus='#mcRecallResult';render();
    }
    function load(){
      const jobs=[loadLive(),loadCount(),loadCands(),loadSettings()];
      if(st.tab==='notes'||st.notes.status==='idle')jobs.push(loadNotes());
      return Promise.all(jobs);
    }
    function setTab(tab){
      if(!TABS.some(([k])=>k===tab))return Promise.resolve();
      st.tab=tab;st.focus=`#mc-tab-${tab}`;render();
      if(tab==='notes'&&st.notes.status==='idle')return loadNotes();
      return Promise.resolve();
    }

    /* ------------------------------------------------------------ rendu */
    const busy=text=>`<div class="mc-loading" role="status"><span class="mc-spin" aria-hidden="true"></span>${esc(text||'Chargement…')}</div>`;
    const errBox=(msg,retry)=>`<div class="mc-error" role="alert"><span>${esc(msg)}</span>${retry?`<button type="button" class="mc-btn" data-act="${retry}">${icon('refresh')}Réessayer</button>`:''}</div>`;
    const lvl=l=>`<span class="mc-lvl mc-lvl-${esc(l)}" title="${esc(label(LEVELS,l))}">${esc(l)}</span>`;
    const state=(status)=>{const [txt,cls]=STATUS[status]||[status||'—','mc-off'];return `<span class="mc-state ${cls}"><span class="mc-dot" aria-hidden="true"></span>${esc(txt)}</span>`};
    const legs=()=>st.live.status==='ready'&&st.live.data&&st.live.data.available!==false?st.live.data.legs||{}:null;

    function heroHtml(){
      const live=st.live,cnt=st.count,legsNow=legs();
      const notes=cnt.status==='ready'?`${cnt.notes}${cnt.capped?'+':''}`:cnt.status==='error'?'—':'…';
      const pending=st.cands.status==='ready'&&st.cands.filter==='proposed'?String(proposedCount()):st.cands.status==='error'?'—':st.cands.status==='ready'?'—':'…';
      let sources='…',srcSub='Sources de connaissances';
      if(legsNow){const k=Object.entries(legsNow).filter(([n])=>n.startsWith('knowledge:'));const on=k.filter(([,l])=>l.status==='ok');
        sources=String(on.length);srcSub=on.length?`Sources actives (${on.map(([n])=>label(LEG_LABEL,n)).join(', ')})`:'Aucune source active'}
      else if(live.status==='error'||(live.data&&live.data.available===false))sources='—';
      let index='…',idxCls='';
      if(live.status==='error'){index='Injoignable';idxCls=' sm'}
      else if(live.data&&live.data.available===false){index='Indisponible';idxCls=' sm'}
      else if(live.data){index=live.data.index_ready===false?'En synchro':'Prêt';idxCls=' sm'}
      const stat=(ico,value,text,cls)=>`<li class="mc-stat">${icon(ico)}<strong class="${cls||''}">${esc(value)}</strong><span>${esc(text)}</span></li>`;
      const why=live.status==='error'?`<p class="mc-why" role="status" style="grid-column:1/-1">État vivant indisponible : ${esc(live.error)}. <button type="button" class="mc-link" data-act="reload-live">Réessayer</button></p>`:'';
      return `<section class="mc-card mc-hero" aria-labelledby="mcHeroTitle">
        <div class="mc-hero-id"><span class="mc-medal">${icon('db')}</span><div><h2 id="mcHeroTitle">Memory Center</h2>
          <p>Inspectez les notes canoniques, décidez des candidats de la consolidation et testez le rappel.</p></div></div>
        <ul class="mc-stats" aria-label="Résumé de la mémoire">${stat('doc',notes,'Notes mémoire')}${stat('users',pending,'Candidats en attente')}
          ${stat('layers',sources,srcSub)}${stat('bars',index,'Index de rappel (dérivé)',idxCls)}</ul>${why}</section>`;
    }

    function tabsHtml(){
      const n=proposedCount();
      return `<div class="mc-tabs" role="tablist" aria-label="Vues du Memory Center">${TABS.map(([k,l,ico])=>
        `<button type="button" role="tab" class="mc-tab" id="mc-tab-${k}" data-act="tab" data-tab="${k}" aria-selected="${st.tab===k}" aria-controls="mcPanel" tabindex="${st.tab===k?0:-1}">${icon(ico)}<span>${esc(l)}</span>${k==='candidates'&&n?`<span class="mc-tab-n" aria-label="${n} en attente">${n}</span>`:''}</button>`).join('')}</div>`;
    }

    function notesTable(){
      const n=st.notes;
      if(n.status==='loading'||n.status==='idle')return busy('Lecture des notes…');
      if(n.status==='error')return errBox(n.error,'reload-notes');
      const derived=!!n.hits,rows=derived?n.hits:n.items;
      if(!rows.length)return `<p class="mc-empty">${n.q.trim()?'Aucune note ne correspond à cette recherche.':n.level||n.kind||n.retention?'Aucune note avec ces filtres.':'Aucune note en mémoire pour l’instant. Elles apparaissent quand JARVIS retient quelque chose ou qu’un candidat est accepté.'}</p>`;
      const body=rows.map(x=>`<tr class="${st.note.id===x.id?'on':''}">
          <td class="c-note"><button type="button" class="mc-notebtn" data-act="note" data-id="${esc(x.id)}"><strong>${esc(x.title||x.id)}</strong><span>${esc(derived?x.snippet:x.excerpt)}</span></button></td>
          <td class="c-lvl">${lvl(x.level)}</td><td class="c-kind"><span class="mc-ellip">${esc(label(KINDS,x.kind))}</span></td>
          <td class="c-scope"><span class="mc-ellip" title="${esc(x.scope)}">${esc(x.scope)}</span></td>
          <td class="c-ret"><span class="mc-ellip">${esc(label(RETENTIONS,x.retention))}</span></td>
          <td class="c-date"><span class="mc-date">${day(x.updated_at)}<br>${hour(x.updated_at)}</span></td>
          <td class="c-act"><button type="button" class="mc-iconbtn" data-act="note" data-id="${esc(x.id)}" aria-label="Détails de « ${esc(x.title||x.id)} »">${icon('more')}</button></td></tr>`).join('');
      return `<div class="mc-tablewrap"><table class="mc-table"><caption class="sr">${derived?'Résultats de recherche (index dérivé), par pertinence':'Notes canoniques, les plus récentes d’abord'}</caption>
        <thead><tr><th class="c-note" scope="col">Contenu de la note</th><th class="c-lvl" scope="col">Niveau</th><th class="c-kind" scope="col">Type</th>
        <th class="c-scope" scope="col">Portée</th><th class="c-ret" scope="col">Rétention</th><th class="c-date" scope="col">${derived?'Modifiée':'Modifiée ↓'}</th><th class="c-act"><span class="sr">Actions</span></th></tr></thead>
        <tbody>${body}</tbody></table></div>`;
    }
    function notesFoot(){
      const n=st.notes;if(n.status!=='ready')return '';
      if(n.hits)return `<div class="mc-foot"><span>${n.hits.length} résultat(s) de l’index lexical, classés par pertinence.</span></div>`;
      const from=n.page*PAGE_SIZE+1,to=n.page*PAGE_SIZE+n.items.length,filtered=!!(n.level||n.kind||n.retention||n.superseded);
      const total=!filtered&&st.count.status==='ready'&&!st.count.capped?st.count.notes:null;
      const pages=total!=null?Math.max(1,Math.ceil(total/PAGE_SIZE)):null;
      const nums=pages&&pages<=7?Array.from({length:pages},(_,i)=>`<button type="button" class="mc-page" data-act="page" data-page="${i}"${i===n.page?' aria-current="page"':''} aria-label="Page ${i+1}">${i+1}</button>`).join('')
        :`<span class="mc-page" aria-current="page">${n.page+1}</span>`;
      return `<div class="mc-foot"><span>${n.items.length?`Notes ${from}–${to}${total!=null?` sur ${total}`:''}`:''}</span>
        <nav class="mc-pages" aria-label="Pages de notes"><button type="button" class="mc-page" data-act="page" data-page="${n.page-1}"${n.page?'':' disabled'} aria-label="Page précédente">${icon('chevronLeft')}</button>
        ${nums}<button type="button" class="mc-page" data-act="page" data-page="${n.page+1}"${n.more?'':' disabled'} aria-label="Page suivante">${icon('chevron')}</button></nav></div>`;
    }
    const opt=(map,value,all)=>`<option value="">${all}</option>${Object.entries(map).map(([k,v])=>`<option value="${esc(k)}"${value===k?' selected':''}>${esc(k.startsWith('L')&&k.length===2?k+' · '+v:v)}</option>`).join('')}`;
    function notesCard(){
      const n=st.notes;
      return `<section class="mc-card" aria-labelledby="mcNotesTitle">
        <div class="mc-cardhead"><span class="mc-medal">${icon('doc')}</span><div><h3 id="mcNotesTitle">Notes mémoire</h3>
          <p>${n.hits?'<span class="mc-chip derived">Dérivé</span> Résultats de l’index lexical ; ouvrir une note affiche son contenu canonique.':'<span class="mc-chip canon">Canonique</span> Notes Markdown retenues par JARVIS.'}</p></div><span></span></div>
        <form class="mc-filters" data-form="notes" role="search" aria-label="Rechercher et filtrer les notes">
          <label class="mc-search">${icon('search')}<span class="sr">Rechercher une note</span><input id="mcQuery" type="search" value="${esc(n.q)}" placeholder="Rechercher une note…" autocomplete="off"></label>
          <label><span class="sr">Niveau</span><select class="mc-select" id="mcLevel" data-filter>${opt(LEVELS,n.level,'Tous les niveaux')}</select></label>
          <label><span class="sr">Rétention</span><select class="mc-select" id="mcRetention" data-filter>${opt(RETENTIONS,n.retention,'Toutes rétentions')}</select></label>
          ${n.q.trim()?'':`<label><span class="sr">Type</span><select class="mc-select" id="mcKind" data-filter>${opt(KINDS,n.kind,'Tous les types')}</select></label>
          <label class="mc-check"><input id="mcSuper" type="checkbox" data-filter${n.superseded?' checked':''}> Remplacées</label>`}
          <button type="submit" class="mc-btn">Rechercher</button></form>
        ${notesTable()}${notesFoot()}</section>`;
    }

    function candCard(x,full){
      const c=st.cands,pending=c.pending[x.id],confirm=c.confirm&&c.confirm.id===x.id?c.confirm:null,err=c.errors[x.id];
      const meta=`<span class="mc-chip prop">Proposition</span>${lvl(x.level)}<span>${esc(label(KINDS,x.kind))}</span><span>confiance ${esc(Math.round(Number(x.confidence)*100))} %</span>${x.conflicts&&x.conflicts.length?`<span class="mc-warn">${x.conflicts.length} conflit(s)</span>`:''}`;
      const acts=x.state==='proposed'?`<div class="mc-cand-a">${pending?busy(pending==='accept'?'Acceptation…':'Rejet…')
        :`<button type="button" class="mc-btn ok" data-act="cand-accept" data-id="${esc(x.id)}" aria-label="Accepter « ${esc(x.title)} »">${icon('check')}Accepter</button>
          <button type="button" class="mc-btn bad" data-act="cand-reject" data-id="${esc(x.id)}" aria-label="Rejeter « ${esc(x.title)} »">${icon('close')}Rejeter</button>`}</div>`
        :`<div class="mc-cand-a"><span class="mc-chip">${esc(label(CAND_STATES,x.state))}</span></div>`;
      const ask=confirm?`<div class="mc-cand-confirm" role="group" aria-label="Confirmer la décision">
          <p>${confirm.decision==='accept'?`Créer une note canonique « ${esc(x.title)} » ? Elle pourra être rappelée par le cerveau.`:'Rejeter ce candidat ? Aucune note n’est créée.'}</p>
          <button type="button" class="mc-btn ${confirm.decision==='accept'?'primary':'bad'}" data-act="decide" data-id="${esc(x.id)}">${confirm.decision==='accept'?'Confirmer l’acceptation':'Confirmer le rejet'}</button>
          <button type="button" class="mc-btn" data-act="cancel" data-id="${esc(x.id)}">Annuler</button></div>`:'';
      const d=full&&c.open===x.id?c.detail[x.id]:null;
      const detail=full&&c.open===x.id?`<div class="mc-cand-body">${!d?busy():d.error?errBox(d.error):`<pre>${esc(d.body)}</pre>
          <dl class="mc-kv"><dt>Portée</dt><dd>${esc(d.scope)}</dd><dt>Rétention</dt><dd>${esc(label(RETENTIONS,d.retention))}</dd>
          <dt>Provenance</dt><dd>${(d.sources||[]).map(s=>`${esc(label(SOURCES,s.type))} <code>${esc(s.ref)}</code>`).join(', ')||'—'}</dd>
          <dt>Conflits</dt><dd>${d.conflicts&&d.conflicts.length?d.conflicts.map(id=>`<button type="button" class="mc-link" data-act="note" data-id="${esc(id)}">${esc(id)}</button>`).join(' ')+' — rien n’est écrasé : accepter crée une nouvelle révision ou une nouvelle note.':'aucun'}</dd></dl>`}</div>`:'';
      return `<li class="mc-cand${full?' full':''}${pending?' pending':''}" data-cand="${esc(x.id)}"><p class="mc-cand-t">${esc(x.title||x.id)}</p>${acts}<div class="mc-cand-m">${meta}
        ${full?`<button type="button" class="mc-link" data-act="cand-open" data-id="${esc(x.id)}" aria-expanded="${c.open===x.id}">${c.open===x.id?'Masquer le détail':'Détail et provenance'}</button>`:''}</div>
        ${err?`<p class="mc-cand-err" role="alert">${esc(err)}</p>`:''}${ask}${detail}</li>`;
    }
    function candsBody(full){
      const c=st.cands;
      if(c.status==='loading'||c.status==='idle')return busy('Lecture des candidats…');
      if(c.status==='error')return errBox(c.error,'reload-cands');
      if(!c.available)return '<p class="mc-empty">La consolidation n’est pas branchée dans cette installation : aucune proposition à relire.</p>';
      const list=c.items.filter(x=>!(c.filter==='proposed'&&c.pending[x.id]&&!c.errors[x.id])||full);
      const shown=full?c.items:list.filter(x=>!c.pending[x.id]).slice(0,RAIL_CANDS);
      if(!shown.length)return `<p class="mc-empty">${c.filter==='proposed'?'Aucun candidat à décider. La consolidation en propose quand elle repère un souvenir durable.':'Aucun candidat dans cet état.'}</p>`;
      return `<ul class="mc-cands">${shown.map(x=>candCard(x,full)).join('')}</ul>`;
    }
    function candsRail(){
      const n=proposedCount();
      return `<section class="mc-card" aria-labelledby="mcCandTitle">
        <div class="mc-cardhead"><span class="mc-medal">${icon('users')}</span><div><h3 id="mcCandTitle">Candidats de consolidation</h3>
          <p>Propositions, pas encore des souvenirs : seule une acceptation crée une note.</p></div>${n?`<span class="mc-count" aria-label="${n} en attente">${n}</span>`:'<span></span>'}</div>
        ${candsBody(false)}${n>RAIL_CANDS?`<button type="button" class="mc-btn" data-act="tab" data-tab="candidates">Voir les ${n} candidats ${icon('chevron')}</button>`:''}</section>`;
    }
    function candsView(){
      const c=st.cands;
      return `<section class="mc-card" aria-labelledby="mcCandAllTitle">
        <div class="mc-cardhead"><span class="mc-medal">${icon('users')}</span><div><h3 id="mcCandAllTitle">Candidats de consolidation</h3>
          <p>Relisez chaque proposition, sa provenance et ses conflits avant de décider.</p></div>
          <label><span class="sr">État</span><select class="mc-select" id="mcCandState">${Object.entries(CAND_STATES).map(([k,v])=>`<option value="${k}"${c.filter===k?' selected':''}>${esc(v)}</option>`).join('')}</select></label></div>
        ${candsBody(true)}</section>`;
    }

    function recallForm(compact){
      const r=st.recall;
      return `<form class="mc-recallform" data-form="recall"><label for="mcRecallQ">Phrase à tester</label>
        <input class="mc-input" id="mcRecallQ" type="text" value="${esc(r.q)}" placeholder="Ce que vous diriez à JARVIS" autocomplete="off">
        <button type="submit" class="mc-btn primary"${r.status==='loading'?' disabled':''}>${icon('play')}Tester</button>
        ${compact?'':`<label class="mc-check" style="grid-column:1/-1">Souvenirs au plus <input class="mc-input" id="mcRecallMax" type="number" min="1" max="10" value="${esc(r.max)}" style="width:72px;height:32px"></label>`}</form>`;
    }
    function recallResults(full){
      const r=st.recall;
      if(r.status==='loading')return busy('Rappel en cours…');
      if(r.status==='error')return errBox(r.error);
      if(!r.data)return full?'<p class="mc-empty">Saisissez une phrase : vous verrez ce que le cerveau recevrait, dans l’ordre, avec les scores. Rien n’est écrit ni injecté.</p>':'';
      const d=r.data,items=d.items||[],top=Math.max(...items.map(i=>Number(i.score)||0),0)||1;
      const deg=(d.degraded||[]).map(c=>`<span class="mc-chip prop" title="${esc(c)}">${esc(label(DEGRADED,c))}</span>`).join('');
      const t=Object.entries(d.timings_ms||{}).map(([k,v])=>`${esc(k)} ${esc(Math.round(v))} ms`).join(' · ');
      const list=items.length?`<ol class="mc-results">${items.map(i=>`<li class="mc-result">${lvl(i.level)}
          <button type="button" class="mc-notebtn" data-act="note" data-id="${esc(i.id)}"><strong>${esc(i.title||i.id)}</strong></button>
          <span class="mc-score"><span>${esc(Number(i.score).toFixed(3))}</span><span class="mc-bar" aria-hidden="true"><i style="width:${Math.max(4,Math.round((Number(i.score)||0)/top*100))}%"></i></span></span>
          ${full?`<p class="mc-why"><strong>Pourquoi :</strong> ${esc(i.why||'—')}${i.rank_sources&&Object.keys(i.rank_sources).length?` · rang ${Object.entries(i.rank_sources).map(([k,v])=>`${esc(k)} ${esc(v)}`).join(', ')}`:''} · source <code>${esc(i.source)}</code></p>`:''}</li>`).join('')}</ol>`
        :`<p class="mc-empty">Rien ne serait rappelé pour cette phrase.${deg?' Un étage dégradé peut l’expliquer.':''}</p>`;
      return `<div id="mcRecallResult" tabindex="-1" class="mc-row2" style="display:grid;gap:8px">
        <p class="mc-why" style="margin:0"><span class="mc-chip derived">Aperçu dérivé</span> Résultats (${items.length} souvenir${items.length>1?'s':''} rappelé${items.length>1?'s':''}), score de rang relatif au meilleur.${full?` Budget : ${esc(d.budget.max_items)} éléments de ${esc(d.budget.item_chars)} caractères.`:''}</p>
        ${deg?`<p class="mc-row2" style="margin:0">${deg}</p>`:''}${full&&t?`<p class="mc-why" style="margin:0">Durées : ${t}</p>`:''}${list}</div>`;
    }
    function recallCard(full){
      return `<section class="mc-card" aria-labelledby="mcRecallTitle">
        <div class="mc-cardhead"><span class="mc-medal">${icon('bars')}</span><div><h3 id="mcRecallTitle">Test de rappel</h3>
          <p>Ce que JARVIS retrouverait pour une phrase. Rien n’est écrit ni injecté.</p></div><span></span></div>
        ${recallForm(!full)}${recallResults(full)}</section>`;
    }

    function healthCard(){
      const live=st.live;let body;
      if(live.status==='loading'||live.status==='idle')body=busy();
      else if(live.status==='error')body=errBox(`Core ne répond pas : ${live.error}`,'reload-live');
      else if(live.data.available===false)body=`<p class="mc-empty">La mémoire n’est pas disponible côté Core${live.data.reason_code?` (${esc(live.data.reason_code)})`:''}.</p>`;
      else{
        const list=Object.entries(live.data.legs||{}).filter(([n])=>n!=='store');
        body=`${live.data.index_ready===false?'<p class="mc-why mc-warn" role="status" style="margin:0">Index en synchronisation : les tours se passent de rappel jusqu’à la fin ; les notes sont intactes.</p>':''}
          <ul class="mc-legs">${list.map(([n,l])=>`<li class="mc-leg" title="${esc(l.reason||'')}">${icon(LEG_ICON[n]||'layers')}<span>${esc(label(LEG_LABEL,n))}</span>${state(l.status)}</li>`).join('')}</ul>`;
      }
      return `<section class="mc-card" aria-labelledby="mcHealthTitle">
        <div class="mc-cardhead"><span class="mc-medal">${icon('db')}</span><div><h3 id="mcHealthTitle">Santé des index</h3>
          <p><span class="mc-chip derived">Dérivé</span> Index jetables, reconstruits depuis les notes.</p></div><span></span></div>
        ${body}<button type="button" class="mc-link" data-act="diagnostics">Détail dans Avancé › Diagnostics</button></section>`;
    }

    function essentialsCard(){
      const s=st.settings;let body;
      if(s.status==='loading'||s.status==='idle')body=busy();
      else if(s.status==='error'||!s.memory)body=errBox(s.error||'Réglages mémoire illisibles.','reload-settings');
      else{
        const eff=p=>((s.memory.effective||{})[p]||{}).value;
        const modeField=(s.memory.schema.sections||[]).flatMap(x=>x.fields).find(f=>f.path==='consolidation.mode');
        const mode=eff('consolidation.mode'),modeLabel=modeField?(modeField.options.find(o=>o.id===mode)||{label:mode}).label:mode;
        const tile=(ico,title,text,value,on)=>`<div class="mc-ess"><span class="mc-ess-h">${icon(ico)}${esc(title)}</span><p>${esc(text)}</p>
          <span class="mc-state ${on?'mc-ok':'mc-off'}"><span class="mc-dot" aria-hidden="true"></span>${esc(value)}</span></div>`;
        body=`<div class="mc-essentials">${tile('brain','Rappel','Utilise la mémoire pertinente en conversation.',eff('recall.enabled')?'Activé':'Désactivé',!!eff('recall.enabled'))}
          ${tile('layers','Souvenirs par tour','Limite des souvenirs injectés par réponse.',`${eff('recall.max_items')} au plus`,true)}
          ${tile('search','Recherche sémantique','Recherche par le sens (embeddings).',eff('semantic.enabled')?'Activée':'Désactivée',!!eff('semantic.enabled'))}
          ${tile('gear','Consolidation',mode==='auto'?'Accepte seule au-dessus du seuil.':'Vous validez les candidats.',modeLabel,true)}</div>`;
      }
      return `<section class="mc-card" aria-labelledby="mcEssTitle">
        <div class="mc-cardhead"><span class="mc-medal">${icon('gear')}</span><div><h3 id="mcEssTitle">Réglages essentiels</h3>
          <p>État enregistré ; ces réglages se modifient dans l’onglet Mémoire.</p></div>
          <button type="button" class="mc-btn" data-act="settings">Modifier ${icon('chevron')}</button></div>${body}</section>`;
    }

    function knowledgeView(){
      const live=st.live,s=st.settings;let sources;
      if(live.status==='loading'||live.status==='idle')sources=busy();
      else if(live.status==='error')sources=errBox(`État des sources inconnu : ${live.error}`,'reload-live');
      else{
        const k=Object.entries((live.data&&live.data.legs)||{}).filter(([n])=>n.startsWith('knowledge:'));
        sources=k.length?`<div class="mc-sources">${k.map(([n,l])=>`<div class="mc-ess"><span class="mc-ess-h">${icon(LEG_ICON[n]||'layers')}${esc(label(LEG_LABEL,n))}</span>
          ${state(l.status)}${l.reason&&l.status!=='ok'?`<p>${esc(l.reason)}${l.reason_code?` (${esc(l.reason_code)})`:''}</p>`:''}</div>`).join('')}</div>`
          :'<p class="mc-empty">Aucune source de connaissance déclarée par Core.</p>';
      }
      const rules=s.memory?Object.entries(s.memory.loadouts||{}):null;
      const loads=rules==null?(s.status==='error'?errBox(s.error,'reload-settings'):busy())
        :rules.length?`<dl class="mc-kv">${rules.map(([a,r])=>`<dt><code>${esc(a)}</code></dt><dd>${(r.memory_scopes||[]).length} portée(s) mémoire${r.wiki===false?', sans wiki':''}${r.codegraph===false?', sans graphe':''}${r.skills===false?', sans skills':''}</dd>`).join('')}</dl>`
        :'<p class="mc-empty">Aucune règle personnalisée : les préréglages par agent s’appliquent.</p>';
      return `<section class="mc-card" aria-labelledby="mcKnowTitle">
        <div class="mc-cardhead"><span class="mc-medal">${icon('layers')}</span><div><h3 id="mcKnowTitle">Connaissances</h3>
          <p><span class="mc-chip derived">Importé ou dérivé</span> Wiki, graphe de code et Skills enrichissent le cerveau sans être de la mémoire canonique. Lecture seule.</p></div>
          <button type="button" class="mc-btn" data-act="knowledge-settings">Modifier ${icon('chevron')}</button></div>
        ${sources}<h4 class="mc-why" style="margin:4px 0 0;font-weight:600;color:inherit">Accès par agent</h4>${loads}</section>`;
    }

    function noteDialogBody(){
      const s=st.note;
      if(!s.id)return '';
      if(s.status==='loading')return busy('Lecture de la note…');
      if(s.status==='error')return errBox(s.error);
      const n=s.data;if(!n)return '';
      const link=id=>`<button type="button" class="mc-link" data-act="note" data-id="${esc(id)}">${esc(id)}</button>`;
      const rel=[n.contradicts&&n.contradicts.length?`Contredit ${n.contradicts.map(link).join(' ')}`:'',n.supersedes&&n.supersedes.length?`Remplace ${n.supersedes.map(link).join(' ')}`:'',n.superseded_by?`Remplacée par ${link(n.superseded_by)}`:''].filter(Boolean).join(' · ');
      return `<h3 id="mcNoteTitle">${esc(n.title)}</h3>
        <p class="mc-row2"><span class="mc-chip canon">Canonique</span><span class="mc-chip">Révision ${esc(n.revision)}</span>${n.superseded_by?'<span class="mc-chip prop">Remplacée</span>':''}</p>
        <dl class="mc-kv" aria-label="Dimensions de la mémoire"><dt>Abstraction</dt><dd>${lvl(n.level)} ${esc(label(LEVELS,n.level))}</dd>
          <dt>Rétention</dt><dd>${esc(label(RETENTIONS,n.retention))}</dd><dt>Type</dt><dd>${esc(label(KINDS,n.kind))}</dd><dt>Portée</dt><dd><code>${esc(n.scope)}</code></dd>
          <dt>Modifiée</dt><dd>${day(n.updated_at)} ${hour(n.updated_at)}</dd><dt>Confiance</dt><dd>${n.confidence==null?'—':esc(Math.round(n.confidence*100)+' %')}</dd>
          <dt>Provenance</dt><dd>${(n.sources||[]).map(x=>`${esc(label(SOURCES,x.type))} <code>${esc(x.ref)}</code>`).join(', ')||'Aucune source enregistrée.'}</dd>
          <dt>Liens</dt><dd>${rel||'Aucun conflit ni remplacement.'}</dd></dl>
        <pre aria-label="Contenu canonique">${esc(n.body)}</pre>`;
    }
    function dialogEl(){return host.querySelector?host.querySelector('#mcNoteDialog'):null}
    function showDialog(){const dlg=dialogEl();if(dlg&&!dlg.open&&typeof dlg.showModal==='function'){try{dlg.showModal()}catch{dlg.setAttribute('open','')}}}

    function panelHtml(){
      if(st.tab==='candidates')return `<div class="mc-work">${candsView()}</div>`;
      if(st.tab==='knowledge')return `<div class="mc-work">${knowledgeView()}</div>`;
      if(st.tab==='recall')return `<div class="mc-work with-rail"><div class="mc-main">${recallCard(true)}</div><div class="mc-rail">${healthCard()}</div></div>`;
      return `<div class="mc-work with-rail"><div class="mc-main">${notesCard()}${essentialsCard()}</div>
        <div class="mc-rail">${candsRail()}${recallCard(false)}${healthCard()}</div></div>`;
    }
    function render(){
      if(dead)return;
      const doc=host.ownerDocument,active=doc&&doc.activeElement;
      const keep=active&&host.contains&&host.contains(active)?(active.id?'#'+active.id:active.dataset&&active.dataset.act?`[data-act="${active.dataset.act}"]${active.dataset.id?`[data-id="${active.dataset.id}"]`:''}${active.dataset.tab?`[data-tab="${active.dataset.tab}"]`:''}`:null):null;
      const dlg=dialogEl(),wasOpen=!!(dlg&&dlg.open);
      host.innerHTML=`<div class="mcw" data-memory-center="1">${heroHtml()}${tabsHtml()}
        <div id="mcPanel" role="tabpanel" aria-labelledby="mc-tab-${st.tab}">${panelHtml()}</div>
        <dialog class="mc-dialog" id="mcNoteDialog" aria-labelledby="mcNoteTitle"><div class="mc-dialog-in">
          <button type="button" class="mc-iconbtn mc-dialog-x" data-act="close-note" aria-label="Fermer la note">${icon('close')}</button>${noteDialogBody()}</div></dialog>
        <div class="sr" role="status" aria-live="polite">${esc(st.announce)}</div></div>`;
      if(st.note.id&&(wasOpen||st.note.status!=='idle'))showDialog();
      const target=st.focus||keep;st.focus=null;
      const el=target&&host.querySelector&&host.querySelector(target);
      if(el&&el.focus)el.focus({preventScroll:!st.focus});
    }

    /* ------------------------------------------------------------ événements */
    function act(name,data){
      data=data||{};
      switch(name){
        case 'tab':return setTab(data.tab);
        case 'reload-live':return loadLive();
        case 'reload-notes':return loadNotes();
        case 'reload-cands':return loadCands();
        case 'reload-settings':return loadSettings();
        case 'page':{const p=Number(data.page);if(!(p>=0))return undefined;st.notes.page=p;return loadNotes()}
        case 'note':return openNote(data.id);
        case 'close-note':return closeNote();
        case 'cand-open':return toggleCand(data.id);
        case 'cand-accept':case 'cand-reject':return askDecision(data.id,name.slice(5));
        case 'cancel':return cancelDecision();
        case 'decide':return decide();
        case 'settings':return opts.open&&opts.open('recall');
        case 'knowledge-settings':return opts.open&&opts.open('knowledge_sources');
        case 'diagnostics':return opts.openDiagnostics&&opts.openDiagnostics();
        default:return undefined;
      }
    }
    function submit(form,fields){
      if(form==='notes'){
        const n=st.notes;n.q=fields.mcQuery||'';n.level=fields.mcLevel||'';n.retention=fields.mcRetention||'';n.kind=fields.mcKind||'';n.superseded=!!fields.mcSuper;n.page=0;
        return loadNotes();
      }
      if(form==='recall'){st.recall.q=fields.mcRecallQ||'';if(fields.mcRecallMax!=null)st.recall.max=Math.min(10,Math.max(1,parseInt(fields.mcRecallMax,10)||6));return runRecall()}
      return undefined;
    }
    function tabKey(key,index){
      if(key==='ArrowRight')return (index+1)%TABS.length;
      if(key==='ArrowLeft')return (index-1+TABS.length)%TABS.length;
      if(key==='Home')return 0;
      if(key==='End')return TABS.length-1;
      return null;
    }
    function fieldsOf(form){const out={};for(const x of form.querySelectorAll('input[id],select[id]'))out[x.id]=x.type==='checkbox'?x.checked:x.value;return out}
    const listeners=[];
    function listen(target,type,fn,capture){target.addEventListener(type,fn,capture);listeners.push([target,type,fn,capture])}
    function bind(){
      listen(host,'click',ev=>{
        const t=ev.target.closest&&ev.target.closest('[data-act]');
        if(!t||t.disabled)return;
        act(t.dataset.act,{...t.dataset});
      });
      listen(host,'submit',ev=>{
        const f=ev.target.closest&&ev.target.closest('form[data-form]');if(!f)return;
        ev.preventDefault();submit(f.dataset.form,fieldsOf(f));
      });
      listen(host,'change',ev=>{
        const t=ev.target;
        if(t.id==='mcCandState'){st.cands.filter=t.value;st.cands.confirm=null;st.cands.open=null;loadCands();return}
        /* Un filtre de notes s'applique dès qu'il change ; la recherche, à l'envoi. */
        if(t.hasAttribute&&t.hasAttribute('data-filter')){const f=t.closest('form[data-form=notes]');if(f)submit('notes',fieldsOf(f))}
      });
      listen(host,'keydown',ev=>{
        const t=ev.target.closest&&ev.target.closest('[role="tab"]');if(!t)return;
        const tabs=[...host.querySelectorAll('[role="tab"]')],next=tabKey(ev.key,tabs.indexOf(t));
        if(next===null)return;
        ev.preventDefault();act('tab',{tab:tabs[next].dataset.tab});
      });
      /* Le `<dialog>` se ferme seul sur Échap (événement `cancel`) : on garde l'état aligné. */
      listen(host,'cancel',ev=>{if(ev.target&&ev.target.id==='mcNoteDialog'){ev.preventDefault();closeNote()}},true);
      /* Échap ferme d'abord la confirmation ouverte, avant que le shell ne ferme les Réglages. */
      if(root.addEventListener)listen(root,'keydown',ev=>{if(ev.key==='Escape'&&dismiss()){ev.preventDefault();ev.stopImmediatePropagation()}},true);
    }
    function dismiss(){
      if(st.note.id){closeNote();return true}
      if(st.cands.confirm){cancelDecision();return true}
      return false;
    }
    function destroy(){dead=true;for(const [t,type,fn,c] of listeners.splice(0))t.removeEventListener(type,fn,c);const dlg=dialogEl();if(dlg&&dlg.open&&dlg.close)dlg.close()}
    injectStyle();
    if(host.addEventListener)bind();
    render();
    return {load,render,state:st,act,submit,setTab,tabKey,openNote,decide,runRecall,dismiss,destroy,get destroyed(){return dead}};
  }

  /* ------------------------------------------------------------ entrée depuis Sessions & Boards
     Une seule maison : le bouton « Memory Center » du gestionnaire ferme celui-ci et ouvre l'onglet Memory Center des
     Réglages (`openSettingsTab`), sur l'onglet interne demandé. */
  const entry={tab:null};
  function open(tab){
    entry.tab=TABS.some(([k])=>k===tab)?tab:null;
    if(root.JarvisWorkspace&&typeof root.JarvisWorkspace.close==='function'){try{root.JarvisWorkspace.close()}catch(e){root.console&&root.console.warn('memory_center_workspace_close_failed',{error:String(e&&e.message||e)})}}
    if(typeof root.openSettingsTab!=='function'){root.console&&root.console.error('memory_center_settings_missing');return false}
    root.openSettingsTab('memory_center');
    return true;
  }
  /* L'onglet interne demandé par la dernière ouverture, consommé par le montage suivant. */
  function takeTab(){const t=entry.tab;entry.tab=null;return t}
  const button=root.document&&root.document.getElementById('wspMemoryCenter');
  if(button)button.addEventListener('click',()=>open());

  root.JarvisMemoryCenter=Object.freeze({create,open,takeTab,LEVELS,RETENTIONS,KINDS,TABS,STYLE_ID});
})(typeof window!=='undefined'?window:globalThis);
