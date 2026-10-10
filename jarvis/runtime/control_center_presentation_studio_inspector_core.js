/* Inspecteur d'édition du Studio, partie 1/3 : constantes, styles et fonctions PURES (handoff jarvis-interactive-presentation-studio, Slice 07).
   Exposé en `window.JarvisStudioInspectorCore` et en `module.exports`. Aucun DOM, aucun réseau, aucun état : `widgetSpec` (la seule table
   widget <- ligne d'introspection), `validateValue`, `setAtPath` (propriétés définies, jamais affectées par clé dynamique), `diffControls`,
   `describeRefusal`, la CSS du panneau et les bornes d'aperçu / d'enregistrement. Le contrat est dans `control_center_presentation_studio_inspector.js`
   (contrôleur) et dans docs/presentation-studio.md › *Edit inspector UI*. */
(function(root){
  'use strict';

  const ROUTE='/api/presentation-studio/presentations';
  const GROUPS=Object.freeze(['content','visual','layout','motion']);
  const GROUP_LABEL=Object.freeze({content:'Contenu',visual:'Style',layout:'Mise en page',motion:'Mouvement'});
  const PANEL_ID='jvStudioInspector';
  const BUTTON_ID='openStudioInspector';
  const STYLE_ID='jv-studio-inspector-style';
  const PREVIEW_OBJECT_ID='studio-inspector-preview';
  const STORAGE_KEY='jarvis.studio_inspector.ui';
  const PLAYBACK_EVENT='jarvis:studio-playback';
  const PREVIEW_MIN_MS=120;          /* au plus ~8 aperçus par seconde, la dernière valeur seule */
  const TEXT_PREVIEW_MS=250;
  const IDLE_COMMIT_MS=700;          /* clavier, ± : une pause sans nouvel appui enregistre UNE fois */
  const REQUEST_TIMEOUT_MS=15000;
  const READ_TIMEOUT_MS=15000;
  const POLL_MS=4000;
  const AVAILABILITY_MS=500;
  const SAVED_FLASH_MS=2200;
  const RELOAD_RETRY_MS=Object.freeze([800,1500,2500,4000,6000]);   /* 5 tentatives, ~15 s au plus */
  const UNSAFE_KEYS=new Set(['__proto__','constructor','prototype']);
  const HEX_COLOR=/^#[0-9a-fA-F]{6}$/;
  /* Les 5 variables que le cadre applique (`THEME_VARS` de `jarvis/prefabs/runtime/shim.js`) et les 10 que la DA produit mais que
     rien ne peut poser aujourd'hui (revue QA-1 de la Slice 09, I2) : montrées « non appliqué ». Un test les compare à
     `ALLOWED_THEME_VARIABLES` et au shim, il ne peut donc pas dériver en silence. */
  const APPLIED_THEME=Object.freeze(['--jv-accent','--jv-text','--jv-muted','--jv-surface','--jv-scale']);
  const NOT_APPLIED_THEME=Object.freeze(['--jv-font','--jv-radius','--jv-gap','--jv-ground','--jv-veil','--jv-title','--jv-link','--jv-body','--jv-edge','--jv-wash']);

  /* ------------------------------------------------------------------ styles */
  const CSS=`
#${PANEL_ID}{position:absolute;z-index:34;top:18px;right:86px;bottom:18px;width:min(420px,calc(100% - 120px));box-sizing:border-box;display:flex;flex-direction:column;
  background:var(--panel,rgba(6,12,18,.94));color:var(--text,#d8edf7);border:1px solid var(--line,#183343);border-radius:10px;overflow:hidden;
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);box-shadow:0 0 50px rgba(0,0,0,.45);font:13px/1.45 system-ui,sans-serif;container-type:inline-size}
#${PANEL_ID}[hidden]{display:none}
#${PANEL_ID} *{box-sizing:border-box}
#${PANEL_ID} button,#${PANEL_ID} input,#${PANEL_ID} select,#${PANEL_ID} textarea{font:inherit;color:inherit}
#${PANEL_ID} .jvi-sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
#${PANEL_ID} .jvi-bar,#${PANEL_ID} .jvi-top,#${PANEL_ID} .jvi-stage,#${PANEL_ID} .jvi-tabs{flex:none}
#${PANEL_ID} .jvi-top{max-height:46%;overflow:auto;padding-bottom:10px;scrollbar-width:thin}
#${PANEL_ID} .jvi-bar{display:flex;align-items:center;gap:8px;padding:12px 12px 10px 14px;border-bottom:1px solid var(--line,#183343)}
#${PANEL_ID} .jvi-title{flex:1 1 auto;min-width:0;margin:0;font-size:12px;font-weight:650;letter-spacing:.12em;text-transform:uppercase;outline:none}
#${PANEL_ID} .jvi-icon{flex:none;display:inline-grid;place-items:center;min-width:32px;height:32px;padding:0 8px;border:1px solid var(--line,#183343);border-radius:7px;
  background:rgba(7,13,19,.7);cursor:pointer;transition:border-color .15s,background-color .15s,color .15s}
#${PANEL_ID} .jvi-icon:hover:not(:disabled){border-color:var(--accent,#6ee7ff);color:var(--accent,#6ee7ff)}
#${PANEL_ID} .jvi-icon:disabled{opacity:.42;cursor:not-allowed}
#${PANEL_ID} :is(button,input,select,textarea,summary,[tabindex]):focus-visible{outline:2px solid var(--accent,#6ee7ff);outline-offset:2px}
#${PANEL_ID} .jvi-pick{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:6px;align-items:center;padding:10px 14px 0}
#${PANEL_ID} .jvi-pick.is-solo{grid-template-columns:minmax(0,1fr)}
#${PANEL_ID} .jvi-field{display:flex;flex-direction:column;gap:3px;min-width:0;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted,#7190a0)}
#${PANEL_ID} select,#${PANEL_ID} input[type=text],#${PANEL_ID} input[type=url],#${PANEL_ID} input[type=number],#${PANEL_ID} textarea{width:100%;min-height:32px;padding:5px 9px;
  background:#071015;border:1px solid var(--line,#183343);border-radius:6px;letter-spacing:0;text-transform:none;font-size:13px}
#${PANEL_ID} select:hover,#${PANEL_ID} input:hover:not([type=range]):not([type=color]),#${PANEL_ID} textarea:hover{border-color:#24485c}
#${PANEL_ID} [aria-invalid=true]{border-color:var(--danger,#ff6577)!important}
#${PANEL_ID} .jvi-status{display:flex;flex-wrap:wrap;align-items:center;gap:6px 9px;margin:10px 14px 0;padding:8px 10px;border:1px solid var(--line,#183343);border-left:3px solid var(--accent,#6ee7ff);border-radius:7px;background:rgba(7,13,19,.7)}
#${PANEL_ID} .jvi-status[hidden]{display:none}
#${PANEL_ID} .jvi-status[data-kind=ok]{border-left-color:var(--ok,#68e0a0)}
#${PANEL_ID} .jvi-status[data-kind=warn]{border-left-color:var(--warn,#ffb85c)}
#${PANEL_ID} .jvi-status[data-kind=bad]{border-left-color:var(--danger,#ff6577)}
#${PANEL_ID} .jvi-status .jvi-msgtext{flex:1 1 160px;min-width:0;overflow-wrap:anywhere}
#${PANEL_ID} .jvi-status .jvi-msgtext strong{display:block;font-weight:650}
#${PANEL_ID} .jvi-status .jvi-clock{display:block;color:var(--muted,#7190a0);font:11.5px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace}
#${PANEL_ID} .jvi-spin{flex:none;width:13px;height:13px;border:2px solid var(--line,#183343);border-top-color:var(--accent,#6ee7ff);border-radius:50%;animation:jviSpin .9s linear infinite}
#${PANEL_ID} .jvi-spin[hidden]{display:none}
#${PANEL_ID} .jvi-btn{flex:none;min-height:28px;padding:3px 10px;border:1px solid var(--line,#183343);border-radius:6px;background:transparent;cursor:pointer}
#${PANEL_ID} .jvi-btn:hover{border-color:var(--accent,#6ee7ff);background:rgba(110,231,255,.08)}
#${PANEL_ID} .jvi-da{margin:10px 14px 0;border:1px solid var(--line,#183343);border-radius:8px;background:rgba(7,13,19,.55)}
#${PANEL_ID} .jvi-da>summary{display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;padding:7px 10px;cursor:pointer;list-style:none;min-height:34px}
#${PANEL_ID} .jvi-da>summary::-webkit-details-marker{display:none}
#${PANEL_ID} .jvi-da-name{font-weight:600;overflow-wrap:anywhere}
#${PANEL_ID} .jvi-chip{display:inline-flex;align-items:center;gap:4px;padding:0 7px;border:1px solid rgba(113,144,160,.45);border-radius:4px;font-size:10.5px;line-height:18px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted,#7190a0);white-space:nowrap}
#${PANEL_ID} .jvi-chip.is-ok{color:var(--ok,#68e0a0);border-color:rgba(104,224,160,.5)}
#${PANEL_ID} .jvi-chip.is-warn{color:var(--warn,#ffb85c);border-color:rgba(255,184,92,.55)}
#${PANEL_ID} .jvi-chip.is-bad{color:var(--danger,#ff6577);border-color:rgba(255,101,119,.5)}
#${PANEL_ID} .jvi-da-body{padding:2px 10px 10px;font-size:12px}
#${PANEL_ID} .jvi-swatches{display:flex;gap:4px;margin:4px 0 8px}
#${PANEL_ID} .jvi-swatch{width:22px;height:22px;border-radius:5px;border:1px solid rgba(216,237,247,.28)}
#${PANEL_ID} .jvi-theme{margin:0;padding:0;list-style:none;display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:2px 10px}
#${PANEL_ID} .jvi-theme li{display:flex;justify-content:space-between;gap:8px;color:var(--text,#d8edf7)}
#${PANEL_ID} .jvi-theme li.is-off{color:var(--muted,#7190a0)}
#${PANEL_ID} .jvi-theme code{font:11.5px ui-monospace,SFMono-Regular,Consolas,monospace}
#${PANEL_ID} .jvi-tabs{display:flex;gap:2px;padding:10px 10px 0;border-bottom:1px solid var(--line,#183343);overflow-x:auto;scrollbar-width:none}
#${PANEL_ID} .jvi-tab{flex:none;display:inline-flex;align-items:center;gap:6px;min-height:34px;padding:0 11px;border:0;border-bottom:2px solid transparent;background:transparent;color:var(--muted,#7190a0);cursor:pointer;white-space:nowrap}
#${PANEL_ID} .jvi-tab:hover{color:var(--text,#d8edf7)}
#${PANEL_ID} .jvi-tab[aria-selected=true]{color:var(--accent,#6ee7ff);border-bottom-color:var(--accent,#6ee7ff)}
#${PANEL_ID} .jvi-tab .jvi-n{min-width:18px;padding:0 5px;border-radius:8px;background:rgba(113,144,160,.18);font-size:10.5px;text-align:center;color:var(--text,#d8edf7)}
#${PANEL_ID} .jvi-main{flex:1 1 0;min-height:0;overflow:auto;scrollbar-width:thin;padding-bottom:14px}
#${PANEL_ID} .jvi-list{margin:0;padding:6px 10px;list-style:none}
#${PANEL_ID} .jvi-row{position:relative;display:grid;gap:6px;padding:11px 10px 11px 12px;border:1px solid transparent;border-left:3px solid transparent;border-radius:8px}
#${PANEL_ID} .jvi-row+.jvi-row{margin-top:2px}
#${PANEL_ID} .jvi-row:hover{background:rgba(110,231,255,.035)}
#${PANEL_ID} .jvi-row.is-dirty{border-left-color:var(--accent,#6ee7ff);background:rgba(110,231,255,.06)}
#${PANEL_ID} .jvi-row.is-saved{border-left-color:var(--ok,#68e0a0)}
#${PANEL_ID} .jvi-row.is-bad{border-left-color:var(--danger,#ff6577)}
#${PANEL_ID} .jvi-row.is-unsupported{opacity:.72;border-left-style:dashed}
#${PANEL_ID} .jvi-row.is-busy{opacity:.78}
#${PANEL_ID} .jvi-head{display:flex;align-items:center;gap:8px;min-width:0}
#${PANEL_ID} .jvi-label{flex:1 1 auto;min-width:0;font-weight:600;overflow-wrap:anywhere}
#${PANEL_ID} .jvi-state{flex:none;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted,#7190a0)}
#${PANEL_ID} .jvi-row.is-dirty .jvi-state{color:var(--accent,#6ee7ff)}
#${PANEL_ID} .jvi-row.is-saved .jvi-state{color:var(--ok,#68e0a0)}
#${PANEL_ID} .jvi-reset{flex:none;min-width:28px;height:28px;padding:0 7px;border:1px solid transparent;border-radius:6px;background:transparent;cursor:pointer;color:var(--muted,#7190a0)}
#${PANEL_ID} .jvi-reset:hover:not(:disabled){border-color:var(--line,#183343);color:var(--text,#d8edf7)}
#${PANEL_ID} .jvi-reset:disabled{opacity:.3;cursor:default}
#${PANEL_ID} .jvi-meaning{margin:0;color:#a9c0cb;font-size:12px}
#${PANEL_ID} .jvi-default{margin:0;color:var(--muted,#7190a0);font-size:11.5px}
#${PANEL_ID} .jvi-msg{margin:0;font-size:12px;color:var(--danger,#ff6577);overflow-wrap:anywhere}
#${PANEL_ID} .jvi-msg[data-kind=info]{color:var(--muted,#7190a0)}
#${PANEL_ID} .jvi-msg[data-kind=warn]{color:var(--warn,#ffb85c)}
#${PANEL_ID} .jvi-msg[hidden]{display:none}
#${PANEL_ID} .jvi-msg .jvi-btn{margin-left:6px}
#${PANEL_ID} .jvi-ctl{display:flex;align-items:center;gap:8px;min-width:0}
#${PANEL_ID} .jvi-num{flex:0 0 84px;width:84px;text-align:right;font-variant-numeric:tabular-nums}
#${PANEL_ID} .jvi-step{flex:none;width:30px;height:30px;padding:0;border:1px solid var(--line,#183343);border-radius:6px;background:#071015;cursor:pointer}
#${PANEL_ID} .jvi-step:hover:not(:disabled){border-color:var(--accent,#6ee7ff)}
#${PANEL_ID} .jvi-step:disabled{opacity:.35;cursor:not-allowed}
#${PANEL_ID} .jvi-range{--pct:50%;flex:1 1 auto;min-width:60px;height:28px;margin:0;background:transparent;-webkit-appearance:none;appearance:none;cursor:pointer;touch-action:none}
#${PANEL_ID} .jvi-range::-webkit-slider-runnable-track{height:6px;border-radius:3px;background:linear-gradient(90deg,var(--accent,#6ee7ff) var(--pct),#16303f var(--pct))}
#${PANEL_ID} .jvi-range::-moz-range-track{height:6px;border-radius:3px;background:#16303f}
#${PANEL_ID} .jvi-range::-moz-range-progress{height:6px;border-radius:3px;background:var(--accent,#6ee7ff)}
#${PANEL_ID} .jvi-range::-webkit-slider-thumb{-webkit-appearance:none;width:20px;height:20px;margin-top:-7px;border-radius:50%;background:#e9f9ff;border:2px solid var(--accent,#6ee7ff);box-shadow:0 1px 6px rgba(0,0,0,.5);transition:transform .12s}
#${PANEL_ID} .jvi-range::-moz-range-thumb{width:16px;height:16px;border-radius:50%;background:#e9f9ff;border:2px solid var(--accent,#6ee7ff)}
#${PANEL_ID} .jvi-range:active::-webkit-slider-thumb{transform:scale(1.18)}
#${PANEL_ID} .jvi-seg{display:flex;flex-wrap:wrap;gap:4px}
#${PANEL_ID} .jvi-seg button{min-height:32px;padding:0 11px;border:1px solid var(--line,#183343);border-radius:6px;background:#071015;cursor:pointer;color:#a9c0cb}
#${PANEL_ID} .jvi-seg button:hover{border-color:#2b5469;color:var(--text,#d8edf7)}
#${PANEL_ID} .jvi-seg button[aria-checked=true]{color:var(--text,#d8edf7);border-color:var(--accent,#6ee7ff);background:rgba(110,231,255,.1)}
#${PANEL_ID} .jvi-switch{position:relative;flex:none;width:40px;height:22px;padding:0;border:1px solid var(--line,#183343);border-radius:11px;background:#16303f;cursor:pointer;transition:background-color .15s,border-color .15s}
#${PANEL_ID} .jvi-switch::after{content:'';position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:#cfe3ec;transition:transform .15s}
#${PANEL_ID} .jvi-switch[aria-checked=true]{background:rgba(110,231,255,.28);border-color:var(--accent,#6ee7ff)}
#${PANEL_ID} .jvi-switch[aria-checked=true]::after{transform:translateX(18px);background:#fff}
#${PANEL_ID} .jvi-swatchbtn{flex:none;width:34px;height:30px;padding:0;border:1px solid var(--line,#183343);border-radius:6px;background:#071015;cursor:pointer}
#${PANEL_ID} .jvi-hex{flex:0 0 96px;width:96px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
#${PANEL_ID} textarea{min-height:76px;resize:vertical;line-height:1.5}
#${PANEL_ID} textarea.jvi-json{font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}
#${PANEL_ID} .jvi-count{font-size:11px;color:var(--muted,#7190a0);font-variant-numeric:tabular-nums;text-align:right}
#${PANEL_ID} .jvi-grad{height:14px;border-radius:7px;border:1px solid rgba(216,237,247,.25)}
#${PANEL_ID} .jvi-stops{display:grid;gap:6px;margin:0;padding:0;list-style:none}
#${PANEL_ID} .jvi-stop{display:flex;align-items:center;gap:6px}
#${PANEL_ID} .jvi-readonly{margin:0;padding:6px 8px;border:1px dashed var(--line,#183343);border-radius:6px;font:11.5px ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;color:#a9c0cb}
#${PANEL_ID} .jvi-stage{margin:10px 14px 0;border:1px solid var(--line,#183343);border-radius:8px;background:rgba(3,8,12,.6);overflow:hidden}
#${PANEL_ID} .jvi-stage>summary{display:flex;align-items:center;gap:8px;min-height:32px;padding:0 10px;cursor:pointer;color:var(--muted,#7190a0);font-size:11px;letter-spacing:.1em;text-transform:uppercase}
#${PANEL_ID} .jvi-slot{max-height:clamp(110px,26vh,280px);overflow:auto;padding:0 0 8px;scrollbar-width:thin}
#${PANEL_ID} .jvi-stagenote{margin:0;padding:0 10px 8px;color:var(--muted,#7190a0);font-size:11.5px}
#${PANEL_ID} .jvi-empty{margin:18px 14px;color:#a9c0cb}
#${PANEL_ID} .jvi-issues{margin:4px 0 0;padding-left:18px;color:var(--warn,#ffb85c)}
@keyframes jviSpin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){#${PANEL_ID} .jvi-spin{animation:none;border-top-color:var(--accent,#6ee7ff);border-style:dotted}
  #${PANEL_ID} .jvi-switch,#${PANEL_ID} .jvi-switch::after,#${PANEL_ID} .jvi-range::-webkit-slider-thumb,#${PANEL_ID} .jvi-icon{transition:none}}
@media (max-width:700px){#${PANEL_ID}{left:12px;right:76px;top:12px;bottom:12px;width:auto}}
@media (max-height:480px){#${PANEL_ID}{right:136px}}
/* Écran bas (700 px et moins) : l'aperçu ouvert reste compact et sa note disparaît, la liste de réglages garde de la place. */
@media (max-height:700px){#${PANEL_ID} .jvi-slot{max-height:150px}#${PANEL_ID} .jvi-stagenote{display:none}#${PANEL_ID} .jvi-pick{padding-top:8px}}
@container (max-width:320px){#${PANEL_ID} .jvi-num{flex-basis:70px;width:70px}#${PANEL_ID} .jvi-hex{flex-basis:84px;width:84px}}
#${BUTTON_ID}:disabled{opacity:.4;cursor:not-allowed}
`;

  /* ------------------------------------------------------------------ fonctions pures */
  function describe(error){
    return error&&typeof error==='object'&&typeof error.message==='string'?error.message:String(error);
  }
  function clip(text,limit){
    const value=String(text==null?'':text).replace(/[\u0000-\u001f\u007f]+/g,' ').trim();
    return value.length>limit?value.slice(0,limit-1)+'…':value;
  }
  function cloneJson(value){return value===undefined?undefined:JSON.parse(JSON.stringify(value))}
  function canonical(value){
    if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
    if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map((k)=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
    return JSON.stringify(value===undefined?null:value);
  }
  function sameJson(a,b){return canonical(a)===canonical(b)}
  function pathParts(path){
    const parts=String(path||'').split('.');
    if(parts.length<2||(parts[0]!=='props'&&parts[0]!=='data'))return null;
    return parts.some((p)=>!p||UNSAFE_KEYS.has(p))?null:parts;
  }
  /* Valeurs de l'instance `{props, data}` avec `value` posée au chemin d'un réglage (`undefined` : la clé disparaît). Copie ; les
     noms réservés sont refusés ; les propriétés sont DÉFINIES, jamais affectées par clé dynamique. */
  function setAtPath(values,path,value){
    const parts=Array.isArray(path)?path:pathParts(path);
    if(!parts)throw new TypeError('chemin de réglage refusé : '+String(path));
    const out={props:cloneJson(values&&values.props||{}),data:cloneJson(values&&values.data||{})};
    let node=parts[0]==='props'?out.props:out.data;
    for(let i=1;i<parts.length-1;i++){
      const key=parts[i];
      const next=Object.prototype.hasOwnProperty.call(node,key)?node[key]:undefined;
      if(next===null||typeof next!=='object'||Array.isArray(next))Object.defineProperty(node,key,{value:{},enumerable:true,writable:true,configurable:true});
      node=node[key];
    }
    const last=parts[parts.length-1];
    if(value===undefined)delete node[last];
    else Object.defineProperty(node,last,{value:cloneJson(value),enumerable:true,writable:true,configurable:true});
    return out;
  }
  /* Valeurs de l'aperçu : celles de la scène, puis la valeur courante des réglages QUI SONT POSÉS (un réglage non posé laisse le
     prefab prendre son défaut de manifeste, comme sur la scène projetée), puis les brouillons. */
  function previewValues(scene,rows,drafts){
    let out={props:cloneJson(scene&&scene.props||{}),data:cloneJson(scene&&scene.data||{})};
    for(const row of rows||[]){
      if(row.is_set&&pathParts(row.path))out=setAtPath(out,row.path,row.current);
    }
    for(const draft of drafts||[]){
      if(pathParts(draft.path))out=setAtPath(out,draft.path,draft.value);
    }
    return out;
  }
  /* « Quel widget pour cette ligne d'introspection ? » La seule table : le type et le widget viennent de Core, jamais d'un nom. */
  function widgetSpec(row){
    const type=row&&row.type,widget=row&&row.widget,b=(row&&row.bounds)||{};
    if(type==='integer'||type==='number'){
      const lo=Number.isFinite(b.min)?b.min:null,hi=Number.isFinite(b.max)?b.max:null;
      return {kind:widget==='slider'&&lo!==null&&hi!==null?'slider':'number',integer:type==='integer',min:lo,max:hi,step:stepFor(row)};
    }
    if(type==='boolean')return {kind:'toggle'};
    if(type==='color')return {kind:'color'};
    if(type==='enum'){
      const choices=Array.isArray(b.choices)?b.choices.slice():[];
      return {kind:choices.length>0&&choices.length<=4&&choices.every((c)=>String(c).length<=14)?'segmented':'select',choices};
    }
    if(type==='string')return {kind:'text',maxLength:Number.isInteger(b.max_length)?b.max_length:null};
    if(type==='text')return {kind:'textarea',maxLength:Number.isInteger(b.max_length)?b.max_length:null};
    if(type==='url')return {kind:'url'};
    if(type==='array'){
      const cur=row.current;
      const stops=Array.isArray(cur)&&cur.length>0&&cur.every((v)=>typeof v==='string'&&HEX_COLOR.test(v));
      return {kind:stops?'stops':'json',maxItems:Number.isInteger(b.max_items)?b.max_items:null};
    }
    return {kind:'readonly'};
  }
  /* Pas d'un curseur : 1 pour un entier ; sinon une puissance de dix lisible, environ 1/100 de l'étendue. */
  function stepFor(row){
    const b=(row&&row.bounds)||{};
    if(row&&row.type==='integer')return 1;
    if(Number.isFinite(b.min)&&Number.isFinite(b.max)&&b.max>b.min){
      const exp=Math.floor(Math.log10((b.max-b.min)/100));
      return Math.pow(10,Number.isFinite(exp)?exp:-2);
    }
    return 0.1;
  }
  function decimalsOf(step){
    const text=String(step);
    if(text.includes('e-'))return Number(text.split('e-')[1]);
    const dot=text.indexOf('.');
    return dot<0?0:text.length-dot-1;
  }
  function roundTo(value,step){
    const decimals=Math.min(decimalsOf(step),8);
    return Number((Math.round(value/step)*step).toFixed(decimals));
  }
  function formatValue(row,value){
    if(value===undefined||value===null)return '—';
    if(typeof value==='boolean')return value?'activé':'désactivé';
    if(typeof value==='number')return String(value);
    if(typeof value==='string')return value===''?'(vide)':clip(value,60);
    if(Array.isArray(value))return value.every((v)=>typeof v==='string')?clip(value.join(' · '),60):value.length+' élément'+(value.length>1?'s':'');
    return clip(JSON.stringify(value),60);
  }
  /* Validation sensible aux bornes, avant tout envoi. Core reste l'autorité (et peut refuser davantage : motif, version du modèle) ;
     ici on évite seulement un aller-retour pour une erreur évidente. `null` : acceptable. */
  function validateValue(row,value){
    const b=(row&&row.bounds)||{};
    switch(row&&row.type){
      case 'integer':case 'number':{
        if(typeof value!=='number'||!Number.isFinite(value))return 'Saisissez un nombre.';
        if(row.type==='integer'&&!Number.isInteger(value))return 'Saisissez un nombre entier.';
        if(Number.isFinite(b.min)&&value<b.min)return `Doit être au moins ${b.min}.`;
        if(Number.isFinite(b.max)&&value>b.max)return `Doit être au plus ${b.max}.`;
        return null;
      }
      case 'boolean':return typeof value==='boolean'?null:'Valeur attendue : activé ou désactivé.';
      case 'color':return typeof value==='string'&&HEX_COLOR.test(value)?null:'Couleur attendue au format #rrggbb.';
      case 'enum':return Array.isArray(b.choices)&&b.choices.includes(value)?null:'Choisissez l\'une des valeurs proposées.';
      case 'url':return typeof value==='string'&&/^https?:\/\/[^\s/?#]+\S*$/i.test(value)&&value.length<=2048?null:'URL http(s) attendue.';
      case 'string':
        if(typeof value!=='string')return 'Texte attendu.';
        if(/[\u0000-\u001f\u007f]/.test(value))return 'Une seule ligne, sans caractère de contrôle.';
        return Number.isInteger(b.max_length)&&value.length>b.max_length?`Au plus ${b.max_length} caractères (${value.length}).`:null;
      case 'text':
        if(typeof value!=='string')return 'Texte attendu.';
        if(/[\u0000-\u0008\u000b-\u001f\u007f]/.test(value))return 'Caractère de contrôle refusé (seuls retour à la ligne et tabulation passent).';
        return Number.isInteger(b.max_length)&&value.length>b.max_length?`Au plus ${b.max_length} caractères (${value.length}).`:null;
      case 'array':
        if(!Array.isArray(value))return 'Un tableau JSON est attendu.';
        return Number.isInteger(b.max_items)&&value.length>b.max_items?`Au plus ${b.max_items} éléments (${value.length}).`:null;
      default:return 'Ce type de réglage n\'est pas modifiable ici.';
    }
  }
  /* Différences entre deux lectures de la scène, pour dire à l'utilisateur ce qui a changé sous ses doigts. */
  function diffControls(before,after){
    const old=new Map((before||[]).map((r)=>[r.control_id,r]));
    const out=[];
    for(const row of after||[]){
      const prev=old.get(row.control_id);
      if(!prev)out.push({control_id:row.control_id,label:row.label,before:undefined,after:row.current,added:true});
      else if(!sameJson(prev.current,row.current))out.push({control_id:row.control_id,label:row.label,before:prev.current,after:row.current});
      old.delete(row.control_id);
    }
    for(const row of old.values())out.push({control_id:row.control_id,label:row.label,before:row.current,after:undefined,removed:true});
    return out;
  }
  function luminance(hex){
    const channel=(i)=>{const c=parseInt(hex.slice(1+i*2,3+i*2),16)/255;return c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4)};
    return 0.2126*channel(0)+0.7152*channel(1)+0.0722*channel(2);
  }
  function contrastRatio(a,b){
    if(!HEX_COLOR.test(a||'')||!HEX_COLOR.test(b||''))return null;
    const la=luminance(a),lb=luminance(b);
    return (Math.max(la,lb)+0.05)/(Math.min(la,lb)+0.05);
  }
  const PROVENANCE=Object.freeze({provided:'fournie',inferred:'déduite',generated:'générée'});
  /* Les refus typés de Core, dits avec SES mots (jamais un libellé générique qui masquerait la cause). */
  function describeRefusal(code,message){
    const why=message?` ${clip(message,300)}`:'';
    switch(code){
      case 'presentation_studio_value_refused':return `Valeur refusée par Core.${why}`;
      case 'presentation_studio_unknown_control':return `Ce réglage n'existe plus sur cette scène.${why}`;
      case 'presentation_studio_scene_incompatible':return `Cette valeur ne convient pas à la version du modèle de la scène.${why}`;
      case 'presentation_studio_prefab_unavailable':return `Le modèle de la scène est indisponible.${why}`;
      case 'presentation_studio_limit_reached':return `Limite atteinte.${why}`;
      case 'presentation_studio_unknown_scene':return `Cette scène n'existe plus.${why}`;
      case 'presentation_studio_unknown_variant':return `Cette variante n'existe plus.${why}`;
      case 'presentation_studio_unknown_presentation':return `Cette présentation n'existe plus.${why}`;
      case 'presentation_studio_storage_io':return `Core n'a pas pu écrire sur le disque.${why}`;
      case 'presentation_studio_invalid':return `Requête refusée par Core.${why}`;
      default:return `${why.trim()||'Refus de Core.'} (${code||'inconnu'})`;
    }
  }
  const HISTORY_TEXT=Object.freeze({
    history_unavailable:'Historique indisponible',nothing_to_undo:'Rien à annuler',nothing_to_redo:'Rien à rétablir',
    stale:'L\'historique a changé',refused:'Refusé'});

  class InspectorError extends Error{
    constructor(message,code,status){super(message);this.name='InspectorError';this.code=code||'unreachable';this.status=status||0}
  }


  const api={ROUTE,GROUPS,GROUP_LABEL,PANEL_ID,BUTTON_ID,STYLE_ID,PREVIEW_OBJECT_ID,STORAGE_KEY,PLAYBACK_EVENT,PREVIEW_MIN_MS,TEXT_PREVIEW_MS,IDLE_COMMIT_MS,REQUEST_TIMEOUT_MS,READ_TIMEOUT_MS,POLL_MS,AVAILABILITY_MS,SAVED_FLASH_MS,RELOAD_RETRY_MS,UNSAFE_KEYS,HEX_COLOR,APPLIED_THEME,NOT_APPLIED_THEME,CSS,describe,clip,cloneJson,canonical,sameJson,pathParts,setAtPath,previewValues,widgetSpec,stepFor,decimalsOf,roundTo,formatValue,validateValue,diffControls,luminance,contrastRatio,PROVENANCE,describeRefusal,HISTORY_TEXT,InspectorError};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.JarvisStudioInspectorCore=api;
})(typeof globalThis!=='undefined'?globalThis:this);
