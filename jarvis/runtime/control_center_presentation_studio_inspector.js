/* Inspecteur d'édition d'une présentation du Studio (handoff jarvis-interactive-presentation-studio, Slice 07).
   Module DOM exposé en `window.JarvisStudioInspector` dans la page et en `module.exports` pour node.

   Ce que ce module est :
   - un panneau accroché au dock (bouton `INS`), contextuel : la scène choisie de la variante active d'une présentation, ses
     réglages rangés par groupe (contenu, style, mise en page, mouvement). Les widgets sont GÉNÉRÉS à partir de la route
     d'introspection (`GET .../variants/{vid}/scenes/{scene_id}/controls`) : type, bornes, défaut, valeur courante, sens. Aucun
     widget n'est écrit à la main pour un réglage précis (`widgetSpec` est la seule table) ;
   - une interface de la MÊME porte que la voix : toute modification passe par `POST .../variants/{vid}/edits` du relais (acteur
     `user` imposé côté serveur), avec les mêmes refus, la même base (`variant_revision`, `if_current`) et le même enregistrement
     d'annulation. Il n'existe aucun chemin d'écriture propre à l'inspecteur : rien dans `localStorage` sauf des préférences
     d'affichage (onglet, aperçu replié) ;
   - exigence de la Slice 08 : UNE modification = UNE entrée d'historique (l'anneau en garde 32). Un réglage continu (curseur,
     saisie, sélecteur de couleur) envoie des aperçus (`mode: preview`, jamais écrits, limités en débit, regroupés : seule la
     dernière valeur part) et n'est enregistré qu'UNE fois, au relâchement, à la sortie du champ ou sur Entrée (au clavier :
     après une courte pause sans nouvel appui) ;
   - lisible : chaque état est dit à l'écran ET journalisé (`[studio-inspector]`, et `obsClientLog` quand la page en a un) :
     chargement avec compteur, refus typés de Core avec ses propres mots, base périmée (valeurs relues et différences dites),
     scène en rechargement (409, nouvelles tentatives bornées et visibles), source dégradée, historique indisponible.

   Ce que ce module ne fait PAS :
   - il ne garde aucun état de présentation : tout vient de Core et y retourne ; l'aperçu local est un cadre de prefab en mode
     `preview` de l'hôte (rien ne part vers Core, les événements du cadre sont ignorés), jamais la scène projetée ;
   - il ne touche pas aux touches de la présentation : ses écouteurs sont posés sur son panneau, jamais sur le document en
     capture ; en lecture (une exécution tourne) ou en plein écran il est caché ENTIÈREMENT (`hidden` + `inert`, brouillons
     abandonnés) ; une saisie dans l'un de ses champs ne déclenche aucun raccourci de la page ;
   - il ne fait aucune édition de source (palier 3, voix/agent) : il montre seulement l'état de rechargement lu sur Core.

   Direction artistique : un chip en lecture seule (nom, provenance, contraste) lu par `GET .../art-direction`. La DA a SA PROPRE
   révision (l'enregistrer ne change pas celle de la variante) : c'est elle qu'on compare. Des 15 variables `--jv-*`, seules 5
   atteignent le cadre aujourd'hui (`THEME_VARS` du shim) ; les 10 autres sont montrées « non appliqué », jamais cachées.

   Clés : aucune écriture par clé dynamique dans un objet simple (les noms de propriétés d'un prefab peuvent valoir `__proto__`) ;
   `setAtPath` refuse ces noms et définit les propriétés avec `defineProperty`. Tout texte d'auteur passe par `textContent`. */
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
#${PANEL_ID} .jvi-top{max-height:36%;overflow:auto;padding-bottom:2px;scrollbar-width:thin}
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
#${PANEL_ID} .jvi-status{display:flex;align-items:center;gap:9px;margin:10px 14px 0;padding:8px 10px;border:1px solid var(--line,#183343);border-left:3px solid var(--accent,#6ee7ff);border-radius:7px;background:rgba(7,13,19,.7)}
#${PANEL_ID} .jvi-status[hidden]{display:none}
#${PANEL_ID} .jvi-status[data-kind=ok]{border-left-color:var(--ok,#68e0a0)}
#${PANEL_ID} .jvi-status[data-kind=warn]{border-left-color:var(--warn,#ffb85c)}
#${PANEL_ID} .jvi-status[data-kind=bad]{border-left-color:var(--danger,#ff6577)}
#${PANEL_ID} .jvi-status .jvi-msgtext{flex:1 1 auto;min-width:0;overflow-wrap:anywhere}
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
#${PANEL_ID} .jvi-slot{max-height:clamp(84px,15vh,190px);overflow:auto;padding:0 0 8px;scrollbar-width:thin}
#${PANEL_ID} .jvi-stagenote{margin:0;padding:0 10px 8px;color:var(--muted,#7190a0);font-size:11.5px}
#${PANEL_ID} .jvi-empty{margin:18px 14px;color:#a9c0cb}
#${PANEL_ID} .jvi-issues{margin:4px 0 0;padding-left:18px;color:var(--warn,#ffb85c)}
@keyframes jviSpin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){#${PANEL_ID} .jvi-spin{animation:none;border-top-color:var(--accent,#6ee7ff);border-style:dotted}
  #${PANEL_ID} .jvi-switch,#${PANEL_ID} .jvi-switch::after,#${PANEL_ID} .jvi-range::-webkit-slider-thumb,#${PANEL_ID} .jvi-icon{transition:none}}
@media (max-width:700px){#${PANEL_ID}{left:12px;right:76px;top:12px;bottom:12px;width:auto}}
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

  /* ------------------------------------------------------------------ contrôleur */
  function createStudioInspector(deps){
    const d=deps||{};
    const doc=d.document||root.document;
    const win=d.window||root;
    const later=d.setTimeout||((fn,ms)=>setTimeout(fn,ms));
    const cancelLater=d.clearTimeout||((id)=>clearTimeout(id));
    const every=d.setInterval||((fn,ms)=>setInterval(fn,ms));
    const stopEvery=d.clearInterval||((id)=>clearInterval(id));
    const now=d.now||(()=>Date.now());
    const fetchImpl=d.fetch||(typeof root.fetch==='function'?root.fetch.bind(root):null);
    const notify=typeof d.toast==='function'?d.toast:(typeof root.toast==='function'?root.toast:null);
    const playing=d.playing||(()=>{
      const player=root.JarvisStudioPlayer,view=player&&typeof player.view==='function'?player.view():null;
      return !!view&&view.running===true&&view.phase!=='stopped'&&view.phase!=='idle';
    });
    const inFullscreen=d.fullscreen||(()=>!!(doc&&doc.fullscreenElement));
    const storage=d.storage||(()=>{try{return root.localStorage||null}catch(_error){return null /* intentional: blocked storage only costs the remembered tab */}});
    const stats={previews:0,previewsCoalesced:0,writesSuperseded:0,commits:0,staleHandled:0,reloadRetries:0,undo:0,redo:0,failures:0,renders:0,polls:0,hiddenByPlayback:0};
    const S={
      open:false,available:true,hiddenReason:null,presentations:[],presentationId:null,variant:null,sceneId:null,scene:null,
      tab:'content',showPreview:true,history:null,art:{state:'idle',doc:null,revision:null,message:''},
      reload:{pending:[],rows:[],degraded:null},loading:null,fatal:null,status:null,reloading:null,generation:0,
    };
    const ui={};
    const widgets=new Map();     /* control_id -> {row, el, update(row), session} */
    const sessions=new Map();    /* control_id -> brouillon en cours */
    const queue={tail:Promise.resolve(),pending:new Map()};
    let pollTimer=null,availTimer=null,loadingTimer=null,saveTimer=null;
    let previewHost=null,previewMounted=null,storedScene=null;
    let primedReload=false;
    let pendingRetry=null;

    /* -------------------------------------------------------------- journal et retour visible (RULE ZERO) */
    function log(key,data,level){
      const line=`[studio-inspector] ${key} ${JSON.stringify(data||{})}`;
      try{
        const sink=d.console||root.console;
        if(sink){if(level==='error')sink.error(line);else if(level==='warn')sink.warn(line);else sink.info(line)}
      }catch(_error){/* intentional: a broken console never breaks the editor */}
      if(level==='error'||level==='warn'){
        try{const obs=d.obsClientLog||root.obsClientLog;if(typeof obs==='function')obs(level,level==='error'?'ERROR':'WARN',`studio_inspector_${key}`,data||{})}
        catch(_error){/* intentional: the console line above is the record when the page's logger is absent or broken */}
      }
    }
    function tell(title,sub,kind){
      if(!notify)return;
      try{notify({title,sub:sub||'',kind:kind||'info',ms:kind==='bad'?9000:5000})}catch(_error){/* intentional: the inline message is the surface, the toast a courtesy */}
    }
    function announce(text){if(ui.live)ui.live.textContent=text}
    function prefs(){
      try{const store=storage();const raw=store&&store.getItem(STORAGE_KEY);const p=raw?JSON.parse(raw):null;return p&&typeof p==='object'?p:{}}
      catch(_error){return {} /* intentional: unreadable preference = defaults */}
    }
    function savePrefs(){
      try{const store=storage();if(store)store.setItem(STORAGE_KEY,JSON.stringify({tab:S.tab,preview:S.showPreview}))}
      catch(_error){/* intentional: a preference that cannot be stored is only forgotten */}
    }

    /* -------------------------------------------------------------- DOM */
    function el(tag,cls,text){
      const node=doc.createElement(tag);
      if(cls)node.className=cls;
      if(text!==undefined&&text!==null)node.textContent=text;
      return node;
    }
    function attrs(node,map){for(const [k,v] of Object.entries(map))node.setAttribute(k,String(v));return node}
    function clear(node){while(node.firstChild)node.removeChild(node.firstChild)}
    function button(label,cls,onClick,extra){
      const b=el('button',cls,label);
      b.setAttribute('type','button');
      if(extra)attrs(b,extra);
      if(onClick)b.addEventListener('click',onClick);
      return b;
    }
    let idSeq=0;
    const uid=(p)=>`jvi-${p}-${++idSeq}`;

    function ensureStyle(){
      if(!doc||typeof doc.getElementById!=='function'||doc.getElementById(STYLE_ID))return;
      const style=doc.createElement('style');
      style.id=STYLE_ID;style.textContent=CSS;
      (doc.head||doc.body).appendChild(style);
    }

    function build(){
      if(ui.root)return ui.root;
      ensureStyle();
      const panel=el('aside');
      panel.id=PANEL_ID;
      attrs(panel,{role:'region','aria-label':'Inspecteur de présentation'});
      panel.hidden=true;
      ui.title=el('h2','jvi-title','Inspecteur');
      ui.title.id='jviTitle';ui.title.setAttribute('tabindex','-1');
      ui.undo=button('↶','jvi-icon',()=>{runHistory('undo')},{'aria-label':'Annuler la dernière modification',title:'Annuler (Ctrl+Z dans l\'inspecteur)'});
      ui.redo=button('↷','jvi-icon',()=>{runHistory('redo')},{'aria-label':'Rétablir la modification annulée',title:'Rétablir (Ctrl+Y dans l\'inspecteur)'});
      ui.undo.disabled=true;ui.redo.disabled=true;
      ui.close=button('×','jvi-icon',()=>{close({restoreFocus:true})},{'aria-label':'Fermer l\'inspecteur',title:'Fermer (Échap)'});
      const bar=el('div','jvi-bar');
      [ui.title,ui.undo,ui.redo,ui.close].forEach((n)=>bar.appendChild(n));
      ui.live=el('div','jvi-sr');attrs(ui.live,{role:'status','aria-live':'polite'});
      ui.pick=el('div','jvi-pick');
      ui.status=el('div','jvi-status');ui.status.hidden=true;
      ui.spin=el('span','jvi-spin');ui.spin.setAttribute('aria-hidden','true');
      ui.statusText=el('div','jvi-msgtext');
      ui.statusActions=el('div');ui.statusActions.style.display='flex';ui.statusActions.style.gap='6px';
      ui.status.appendChild(ui.spin);ui.status.appendChild(ui.statusText);ui.status.appendChild(ui.statusActions);
      ui.reloadBanner=el('div','jvi-status');ui.reloadBanner.hidden=true;
      ui.reloadText=el('div','jvi-msgtext');ui.reloadBanner.appendChild(ui.reloadText);
      ui.da=el('details','jvi-da');ui.da.hidden=true;
      ui.stage=el('details','jvi-stage');ui.stage.hidden=true;
      ui.stageSummary=el('summary',null,'Aperçu local');
      ui.slot=el('div','jvi-slot');
      ui.stageNote=el('p','jvi-stagenote','Aperçu local : rien n\'est écrit avant le relâchement.');
      ui.stage.appendChild(ui.stageSummary);ui.stage.appendChild(ui.slot);ui.stage.appendChild(ui.stageNote);
      ui.stage.addEventListener('toggle',()=>{S.showPreview=!!ui.stage.open;savePrefs();if(S.showPreview)syncPreview()});
      ui.tabs=el('div','jvi-tabs');attrs(ui.tabs,{role:'tablist','aria-label':'Groupes de réglages'});
      ui.main=el('div','jvi-main');
      ui.issues=el('div');
      ui.panels=el('div');
      ui.empty=el('p','jvi-empty');ui.empty.hidden=true;
      ui.top=el('div','jvi-top');
      [ui.pick,ui.status,ui.reloadBanner].forEach((n)=>ui.top.appendChild(n));
      [ui.da,ui.empty,ui.issues,ui.panels].forEach((n)=>ui.main.appendChild(n));
      [bar,ui.live,ui.top,ui.stage,ui.tabs,ui.main].forEach((n)=>panel.appendChild(n));
      panel.addEventListener('keydown',onPanelKey);
      ui.root=panel;
      /* Même repère que le panneau latéral (`.panel`) : le parent du dock (le bouton est dans un `.tool` du `nav.dock`). */
      const nav=ui.dock&&typeof ui.dock.closest==='function'?ui.dock.closest('.dock'):null;
      (nav&&nav.parentNode||doc.body).appendChild(panel);
      return panel;
    }

    /* -------------------------------------------------------------- réseau */
    async function call(url,options){
      const o=options||{};
      if(!fetchImpl)throw new InspectorError('fetch indisponible dans cette page','unreachable',0);
      const controller=typeof AbortController==='function'?new AbortController():null;
      const timeoutMs=o.timeoutMs||REQUEST_TIMEOUT_MS;
      let expired=false;
      const deadline=later(()=>{expired=true;if(controller)controller.abort()},timeoutMs);
      try{
        const response=await fetchImpl(url,{method:o.method||'GET',cache:'no-store',
          headers:o.body!==undefined?{'Content-Type':'application/json'}:undefined,
          body:o.body!==undefined?JSON.stringify(o.body):undefined,signal:controller?controller.signal:undefined});
        const text=await response.text();
        let json=null;
        try{json=text?JSON.parse(text):null}catch(_error){json=null /* a non-JSON answer is reported by its status below */}
        return {status:response.status,ok:response.ok,body:json};
      }catch(error){
        if(expired)throw new InspectorError(`Core n'a pas répondu en ${Math.round(timeoutMs/1000)} s`,'timeout',0);
        if(error&&error.name==='AbortError')throw new InspectorError('requête annulée','cancelled',0);
        throw new InspectorError(describe(error),'unreachable',0);
      }finally{cancelLater(deadline)}
    }
    function envelopeOf(response){
      const error=response.body&&response.body.error;
      return {code:error&&error.code?String(error.code):`http_${response.status}`,
        message:error&&error.message?String(error.message):`HTTP ${response.status}`,http:response.status};
    }
    async function read(url,what){
      const response=await call(url,{timeoutMs:READ_TIMEOUT_MS});
      if(!response.ok||!response.body||response.body.error){
        const e=envelopeOf(response);
        throw new InspectorError(`${what} : ${e.message}`,e.code,e.http);
      }
      return response.body;
    }
    const base=()=>`${ROUTE}/${encodeURIComponent(S.presentationId)}`;
    const variantBase=()=>`${base()}/variants/${encodeURIComponent(S.variant.variant_id)}`;

    /* -------------------------------------------------------------- attente visible */
    function setLoading(what){
      S.loading=what?{what,since:now()}:null;
      renderStatus();
    }
    /* Une seule horloge de 500 ms tant qu'une attente (chargement, rechargement) est à l'écran. */
    function syncClock(){
      const needed=!!(S.loading||S.reloading);
      if(needed&&loadingTimer===null)loadingTimer=every(()=>renderStatus(),500);
      else if(!needed&&loadingTimer!==null){stopEvery(loadingTimer);loadingTimer=null}
    }
    function setFatal(error,retry){
      S.fatal=error?{message:describe(error),code:error.code||'error',retry}:null;
      renderStatus();
    }
    function setStatus(kind,title,text,actions){
      S.status=kind?{kind,title,text,actions:actions||[],at:now()}:null;
      renderStatus();
    }

    function renderStatus(){
      if(!ui.status)return;
      syncClock();
      clear(ui.statusActions);
      const spinning=!!S.loading||!!S.reloading;
      let shown=null;
      if(S.fatal)shown={kind:'bad',title:'Chargement impossible',text:`${S.fatal.message} (${S.fatal.code})`,
        actions:S.fatal.retry?[{label:'Réessayer',run:S.fatal.retry}]:[]};
      else if(S.reloading){
        const r=S.reloading;
        const left=Math.max(0,Math.ceil((r.nextAt-now())/1000));
        shown={kind:'warn',title:'Rechargement en cours',clock:`tentative ${r.attempt}/${r.max} · prochaine dans ${left} s`,
          text:'La source de cette scène est en train de se recharger : votre modification est mise en attente et repartira toute seule.',
          actions:[{label:'Arrêter d\'attendre',run:()=>giveUpReload()}]};
      }else if(S.loading){
        const sec=Math.floor((now()-S.loading.since)/1000);
        shown={kind:'info',title:S.loading.what,clock:`${sec} s / ${READ_TIMEOUT_MS/1000} s`,text:''};
      }else if(S.status)shown=S.status;
      ui.status.hidden=!shown;
      if(!shown)return;
      ui.status.setAttribute('data-kind',shown.kind);
      ui.spin.hidden=!spinning;
      ui.status.setAttribute('role',shown.kind==='bad'||shown.kind==='warn'?'alert':'status');
      clear(ui.statusText);
      ui.statusText.appendChild(el('strong',null,shown.title));
      if(shown.text)ui.statusText.appendChild(doc.createTextNode(shown.text));
      if(shown.clock)ui.statusText.appendChild(el('span','jvi-clock',shown.clock));
      for(const action of shown.actions||[])ui.statusActions.appendChild(button(action.label,'jvi-btn',action.run));
      if(!shown.actions||!shown.actions.length){
        if(shown.kind==='ok'||shown.kind==='info')return;
        ui.statusActions.appendChild(button('Fermer','jvi-btn',()=>setStatus(null)));
      }
    }

    /* -------------------------------------------------------------- chargement */
    async function loadPresentations(){
      const generation=++S.generation;
      setLoading('Chargement des présentations…');setFatal(null);
      try{
        const list=await read(ROUTE,'Liste des présentations');
        if(generation!==S.generation)return;
        S.presentations=Array.isArray(list.presentations)?list.presentations:[];
        const problems=Array.isArray(list.problems)?list.problems.length:0;
        log('presentations_loaded',{count:S.presentations.length,problems});
        if(!S.presentations.some((p)=>p.presentation_id===S.presentationId))S.presentationId=S.presentations.length?S.presentations[0].presentation_id:null;
        renderPick();
        if(S.presentationId)await selectPresentation(S.presentationId,{keepScene:true});
        else{S.variant=null;S.scene=null;renderAll()}
      }catch(error){
        stats.failures++;
        setFatal(error,()=>{loadPresentations()});
        log('presentations_failed',{code:error.code,error:describe(error)},'error');
        tell('Inspecteur : présentations illisibles',describe(error),'bad');
      }finally{setLoading(null)}
    }
    async function selectPresentation(id,options){
      const keep=options&&options.keepScene;
      S.presentationId=id;
      abandonDrafts('presentation');
      const body=await read(`${ROUTE}/${encodeURIComponent(id)}`,'Présentation');
      const active=body.presentation&&body.presentation.active_variant_id;
      let variant=(body.variants||[]).find((v)=>v.variant_id===active)||null;
      if(!variant&&active)variant=await read(`${ROUTE}/${encodeURIComponent(id)}/variants/${encodeURIComponent(active)}`,'Variante');
      S.variant=variant;
      S.history=null;S.art={state:'idle',doc:null,revision:null,message:''};
      const scenes=variant&&Array.isArray(variant.scenes)?variant.scenes:[];
      if(!keep||!scenes.some((s)=>s.scene_id===S.sceneId))S.sceneId=scenes.length?scenes[0].scene_id:null;
      renderPick();
      log('variant_loaded',{presentation_id:id,variant_id:variant&&variant.variant_id,scenes:scenes.length,revision:variant&&variant.revision});
      await Promise.all([loadScene(),loadHistory(),loadArtDirection()]);
      pollReloads();
    }
    async function loadScene(options){
      const o=options||{};
      if(!S.variant||!S.sceneId){S.scene=null;storedScene=null;renderAll();return null}
      const generation=++S.generation;
      if(!o.quiet)setLoading('Chargement des réglages…');
      try{
        const [variant,scene]=await Promise.all([
          read(variantBase(),'Variante'),
          read(`${variantBase()}/scenes/${encodeURIComponent(S.sceneId)}/controls`,'Réglages de la scène')]);
        if(generation!==S.generation)return null;
        const before=S.scene&&S.scene.scene_id===scene.scene_id?S.scene.controls:null;
        S.variant=variant;
        storedScene=(variant.scenes||[]).find((s)=>s.scene_id===S.sceneId)||null;
        S.scene=scene;
        setFatal(null);
        renderAll();
        if(!o.quiet)log('scene_loaded',{scene_id:scene.scene_id,controls:(scene.controls||[]).length,revision:scene.variant_revision,problems:(scene.problems||[]).length});
        return before?{before,after:scene.controls}:null;
      }catch(error){
        stats.failures++;
        if(error.code==='presentation_studio_unknown_scene'&&S.variant){
          log('scene_gone',{scene_id:S.sceneId},'warn');
          const scenes=S.variant.scenes||[];
          S.sceneId=scenes.length?scenes[0].scene_id:null;
          setStatus('warn','La scène n\'existe plus','Une autre modification l\'a retirée : la première scène est affichée.');
          return loadScene({quiet:true});
        }
        setFatal(error,()=>{loadScene()});
        log('scene_failed',{scene_id:S.sceneId,code:error.code,error:describe(error)},'error');
        tell('Inspecteur : réglages illisibles',describe(error),'bad');
        return null;
      }finally{if(!o.quiet)setLoading(null)}
    }
    async function loadHistory(){
      if(!S.variant)return;
      try{
        S.history=await read(`${variantBase()}/history`,'Historique');
        renderHistory();
      }catch(error){
        S.history=null;renderHistory();
        log('history_failed',{code:error.code,error:describe(error)},'warn');
      }
    }
    async function loadArtDirection(){
      if(!S.variant)return;
      const previous=S.art.revision;
      try{
        const response=await call(`${variantBase()}/art-direction`,{timeoutMs:READ_TIMEOUT_MS});
        if(response.status===404&&response.body&&response.body.error&&response.body.error.code==='presentation_studio_unknown_art_direction'){
          S.art={state:'absent',doc:null,revision:null,message:''};
        }else if(!response.ok||!response.body||!response.body.art_direction){
          const e=envelopeOf(response);
          throw new InspectorError(e.message,e.code,e.http);
        }else{
          const doc_=response.body.art_direction;
          S.art={state:'ok',doc:doc_,revision:doc_.revision,message:''};
          if(previous!==null&&previous!==doc_.revision){
            log('art_direction_changed',{from:previous,to:doc_.revision});
            announce('La direction artistique a été mise à jour.');
          }
        }
      }catch(error){
        S.art={state:'error',doc:null,revision:null,message:describe(error)};
        log('art_direction_failed',{code:error.code,error:describe(error)},'warn');
      }
      renderArt();
    }
    async function pollReloads(){
      if(!S.open||!S.available||!S.presentationId||(doc&&doc.hidden))return;
      stats.polls++;
      try{
        const body=await read(`${base()}/reloads`,'Rechargements');
        S.reload.pending=Array.isArray(body.pending)?body.pending:[];
        S.reload.rows=Array.isArray(body.reloads)?body.reloads:[];
        const mine=S.sceneId;
        const rows=S.reload.rows.filter((r)=>r.scene_id===mine&&(!S.variant||r.variant_id===S.variant.variant_id));
        const last=rows.length?rows[rows.length-1]:null;
        const pending=S.reload.pending.find((p)=>p.scene_id===mine);
        const next=pending?{kind:'warn',title:'Source récente non confirmée',
          text:'Un nouveau modèle est en place mais la page ne l\'a pas encore vu monter : le repli enregistré reste disponible.'}:
          last&&last.status==='degraded'?{kind:'bad',title:'Source dégradée',
            text:'Le nouveau modèle n\'a pas monté et le retour arrière a échoué. La scène garde son repli enregistré : demandez un rechargement ou redémarrez Core.'}:null;
        const key=next?next.title:null;
        if(key!==S.reload.degraded){S.reload.degraded=key;if(next)log('reload_state',{scene_id:mine,state:next.title},next.kind==='bad'?'error':'warn')}
        renderReloadBanner(next);
        primedReload=true;
        if(stats.polls%2===0)loadArtDirection();
      }catch(error){
        log('reloads_failed',{code:error.code,error:describe(error)},'warn');
      }
    }

    /* -------------------------------------------------------------- rendu */
    function renderPick(){
      if(!ui.pick)return;
      clear(ui.pick);
      const solo=S.presentations.length<=1;
      ui.pick.className='jvi-pick'+(solo?' is-solo':'');
      if(!S.presentations.length)return;
      if(!solo){
        const label=el('label','jvi-field');label.appendChild(el('span',null,'Présentation'));
        const select=el('select');select.setAttribute('aria-label','Présentation');
        for(const p of S.presentations){
          const o=el('option',null,p.title||p.presentation_id);o.value=p.presentation_id;
          if(p.presentation_id===S.presentationId)o.selected=true;
          select.appendChild(o);
        }
        select.addEventListener('change',()=>{selectPresentation(select.value).catch((error)=>{setFatal(error,()=>{loadPresentations()});log('presentation_failed',{error:describe(error)},'error')})});
        label.appendChild(select);ui.pick.appendChild(label);
      }
      const scenes=(S.variant&&S.variant.scenes)||[];
      const field=el('label','jvi-field');
      field.appendChild(el('span',null,S.variant?`Scène · ${S.variant.title||'variante active'}`:'Scène'));
      const sel=el('select');sel.setAttribute('aria-label','Scène');sel.id='jviScene';
      scenes.forEach((s,i)=>{
        const o=el('option',null,`${i+1}. ${s.title||'(sans titre)'}${s.section?' · '+s.section:''}`);o.value=s.scene_id;
        if(s.scene_id===S.sceneId)o.selected=true;
        sel.appendChild(o);
      });
      sel.addEventListener('change',()=>{chooseScene(sel.value)});
      field.appendChild(sel);
      const index=scenes.findIndex((s)=>s.scene_id===S.sceneId);
      const prev=button('‹','jvi-icon',()=>{if(index>0)chooseScene(scenes[index-1].scene_id)},{'aria-label':'Scène précédente',title:'Scène précédente'});
      const next=button('›','jvi-icon',()=>{if(index>=0&&index<scenes.length-1)chooseScene(scenes[index+1].scene_id)},{'aria-label':'Scène suivante',title:'Scène suivante'});
      prev.disabled=index<=0;next.disabled=index<0||index>=scenes.length-1;
      if(solo){
        const row=el('div');row.style.display='grid';row.style.gridTemplateColumns='minmax(0,1fr) auto auto';row.style.gap='6px';row.style.alignItems='end';
        row.appendChild(field);row.appendChild(prev);row.appendChild(next);ui.pick.appendChild(row);
      }else{ui.pick.appendChild(field);ui.pick.appendChild(prev);ui.pick.appendChild(next)}
    }
    function chooseScene(id){
      if(id===S.sceneId)return;
      abandonDrafts('scene');
      S.sceneId=id;S.reload.degraded=null;renderReloadBanner(null);
      renderPick();
      loadScene().then(()=>pollReloads());
    }

    function renderHistory(){
      if(!ui.undo)return;
      const h=S.history;
      const canUndo=!!h&&h.undo_count>0,canRedo=!!h&&h.redo_count>0;
      ui.undo.disabled=!canUndo;ui.redo.disabled=!canRedo;
      const who=(e)=>e&&e.actor==='brain'?' (faite par Jarvis)':'';
      ui.undo.title=canUndo?`Annuler la dernière modification${who(h.next_undo)} (Ctrl+Z dans l'inspecteur)`:'Rien à annuler';
      ui.redo.title=canRedo?`Rétablir la modification annulée${who(h.next_redo)} (Ctrl+Y dans l'inspecteur)`:'Rien à rétablir';
      if(!canUndo)ui.undo.title=h&&h.tracked===false?'Rien à annuler : l\'historique ne garde que les modifications faites depuis le démarrage de Core':'Rien à annuler';
    }

    function renderArt(){
      if(!ui.da)return;
      const a=S.art;
      ui.da.hidden=a.state==='idle';ui.da.style.margin='10px 14px 0';
      clear(ui.da);
      if(a.state==='idle')return;
      const summary=el('summary');
      if(a.state==='ok'){
        const p=a.doc.profile||{},prov=p.provenance||{},pal=p.palette||{};
        summary.appendChild(el('span','jvi-chip',`DA · rév. ${a.doc.revision}`));
        summary.appendChild(el('span','jvi-da-name',p.name||'(sans nom)'));
        summary.appendChild(el('span','jvi-chip',PROVENANCE[prov.origin]||String(prov.origin||'?')));
        if(prov.fallback)summary.appendChild(el('span','jvi-chip is-warn','repli'));
        const ratio=contrastRatio(pal.text,pal.background);
        if(ratio===null)summary.appendChild(el('span','jvi-chip is-warn','contraste inconnu'));
        else summary.appendChild(el('span','jvi-chip '+(ratio>=4.5?'is-ok':'is-bad'),`contraste ${ratio.toFixed(1)} : 1 ${ratio>=4.5?'✓':'✗'}`));
        ui.da.appendChild(summary);
        const body=el('div','jvi-da-body');
        const sw=el('div','jvi-swatches');sw.setAttribute('aria-hidden','true');
        for(const name of ['background','surface','text','muted','accent']){
          if(!HEX_COLOR.test(pal[name]||''))continue;
          const s=el('span','jvi-swatch');s.style.background=pal[name];s.title=`${name} ${pal[name]}`;sw.appendChild(s);
        }
        body.appendChild(sw);
        body.appendChild(el('p','jvi-default','Lecture seule. Livré au cadre de la scène aujourd\'hui : 5 variables ; les autres sont produites par la direction artistique mais aucun chemin ne les pose encore.'));
        const list=el('ul','jvi-theme');
        for(const name of APPLIED_THEME){const li=el('li');li.appendChild(el('code',null,name));li.appendChild(el('span',null,'appliqué'));list.appendChild(li)}
        for(const name of NOT_APPLIED_THEME){
          const li=el('li','is-off');li.title='Aucun chemin de livraison vers le cadre aujourd\'hui';
          li.appendChild(el('code',null,name));li.appendChild(el('span',null,'non appliqué'));list.appendChild(li);
        }
        body.appendChild(list);
        ui.da.appendChild(body);
      }else if(a.state==='absent'){
        summary.appendChild(el('span','jvi-chip','DA'));
        summary.appendChild(el('span','jvi-da-name','Aucune direction artistique pour cette variante'));
        ui.da.appendChild(summary);
      }else{
        summary.appendChild(el('span','jvi-chip is-bad','DA'));
        summary.appendChild(el('span','jvi-da-name',`Direction artistique illisible : ${clip(a.message,120)}`));
        ui.da.appendChild(summary);
        const body=el('div','jvi-da-body');body.appendChild(button('Réessayer','jvi-btn',()=>{loadArtDirection()}));ui.da.appendChild(body);
      }
    }
    function renderReloadBanner(info){
      if(!ui.reloadBanner)return;
      ui.reloadBanner.hidden=!info;
      if(!info)return;
      ui.reloadBanner.setAttribute('data-kind',info.kind);
      ui.reloadBanner.setAttribute('role',info.kind==='bad'?'alert':'status');
      clear(ui.reloadText);
      ui.reloadText.appendChild(el('strong',null,info.title));
      ui.reloadText.appendChild(doc.createTextNode(info.text));
    }

    /* Un réglage rendu : structure stable tant que la liste de réglages ne change pas. */
    function signature(scene){
      return canonical((scene.controls||[]).map((r)=>[r.control_id,r.type,r.widget,r.group,r.bounds,r.label,r.meaning,r.default,
        widgetSpec(r).kind]));
    }
    function renderAll(){
      if(!ui.root)return;
      stats.renders++;
      renderPick();renderHistory();renderArt();
      const scene=S.scene;
      ui.empty.hidden=true;
      if(!S.presentations.length&&!S.loading&&!S.fatal){
        ui.empty.hidden=false;ui.empty.textContent='Aucune présentation pour le moment. Demandez à Jarvis d\'en créer une, ou ouvrez-en une depuis l\'atelier.';
        clearPanels();ui.stage.hidden=true;ui.tabs.hidden=true;return;
      }
      if(S.variant&&!(S.variant.scenes||[]).length){
        ui.empty.hidden=false;ui.empty.textContent='Cette variante n\'a pas encore de scène.';
        clearPanels();ui.stage.hidden=true;ui.tabs.hidden=true;return;
      }
      if(!scene){clearPanels();ui.tabs.hidden=true;return}
      ui.tabs.hidden=false;
      clear(ui.issues);
      if(Array.isArray(scene.problems)&&scene.problems.length){
        const box=el('div','jvi-status');box.setAttribute('data-kind','warn');box.setAttribute('role','alert');
        const text=el('div','jvi-msgtext');text.appendChild(el('strong',null,'Cette scène a des valeurs à corriger'));
        const ul=el('ul','jvi-issues');for(const p of scene.problems.slice(0,6))ul.appendChild(el('li',null,clip(p,200)));
        text.appendChild(ul);box.appendChild(text);ui.issues.appendChild(box);
      }
      const rows=scene.controls||[];
      if(!rows.length){
        ui.empty.hidden=false;
        ui.empty.textContent='Cette scène n\'expose aucun réglage. Demandez à Jarvis de proposer des réglages, ou de modifier sa source.';
      }
      const sig=signature(scene);
      if(sig!==ui.signature||!ui.panels.firstChild){ui.signature=sig;rebuildPanels(rows)}
      else for(const row of rows){const w=widgets.get(row.control_id);if(w)w.update(row)}
      syncPreview();
    }
    function clearPanels(){clear(ui.panels);clear(ui.tabs);widgets.clear();ui.signature=null;unmountPreview()}

    function rebuildPanels(rows){
      clear(ui.panels);clear(ui.tabs);widgets.clear();
      const present=GROUPS.filter((g)=>rows.some((r)=>r.group===g));
      for(const r of rows)if(!GROUPS.includes(r.group)&&!present.includes(r.group))present.push(r.group);
      if(!present.includes(S.tab))S.tab=present[0]||'content';
      const tabs=[];
      for(const group of present){
        const tab=el('button','jvi-tab');
        tab.type='button';tab.id=`jviTab-${group}`;
        attrs(tab,{role:'tab','aria-controls':`jviPanel-${group}`,'aria-selected':group===S.tab,tabindex:group===S.tab?0:-1});
        tab.appendChild(doc.createTextNode(GROUP_LABEL[group]||group));
        tab.appendChild(el('span','jvi-n',String(rows.filter((r)=>r.group===group).length)));
        tab.addEventListener('click',()=>selectTab(group,{focus:false}));
        tab.addEventListener('keydown',(event)=>onTabKey(event,present));
        ui.tabs.appendChild(tab);tabs.push(tab);
        const panel=el('div');
        panel.id=`jviPanel-${group}`;
        attrs(panel,{role:'tabpanel','aria-labelledby':`jviTab-${group}`});
        panel.hidden=group!==S.tab;
        const list=el('ul','jvi-list');
        for(const row of rows.filter((r)=>r.group===group)){
          const w=buildRow(row);widgets.set(row.control_id,w);list.appendChild(w.el);
        }
        panel.appendChild(list);ui.panels.appendChild(panel);
      }
      ui.tabsList=present;
    }
    function selectTab(group,options){
      if(!ui.tabsList||!ui.tabsList.includes(group))return;
      S.tab=group;savePrefs();
      for(const tab of ui.tabs.children){
        const on=tab.id==='jviTab-'+group;
        tab.setAttribute('aria-selected',String(on));tab.setAttribute('tabindex',on?'0':'-1');
        if(on&&options&&options.focus)tab.focus();
      }
      for(const panel of ui.panels.children)panel.hidden=panel.id!=='jviPanel-'+group;
    }
    function onTabKey(event,groups){
      const keys={ArrowRight:1,ArrowLeft:-1,Home:'first',End:'last'};
      if(!(event.key in keys))return;
      event.preventDefault();
      const i=groups.indexOf(S.tab);
      const next=keys[event.key]==='first'?0:keys[event.key]==='last'?groups.length-1:(i+keys[event.key]+groups.length)%groups.length;
      selectTab(groups[next],{focus:true});
    }

    /* -------------------------------------------------------------- widgets générés */
    function buildRow(row0){
      const ctx={row:row0,session:null};
      const inputId=uid('in'),descId=uid('desc'),msgId=uid('msg');
      const li=el('li','jvi-row');li.setAttribute('data-control-id',row0.control_id);
      const head=el('div','jvi-head');
      const label=el('label','jvi-label',row0.label||row0.control_id);label.setAttribute('for',inputId);
      const stateEl=el('span','jvi-state');
      const reset=button('↺','jvi-reset',()=>{resetControl(ctx.row)},{'aria-label':`Rétablir « ${row0.label} » à sa valeur par défaut`});
      head.appendChild(label);head.appendChild(stateEl);head.appendChild(reset);
      const meaning=el('p','jvi-meaning',row0.meaning||'');meaning.id=descId;meaning.hidden=!row0.meaning;
      const slot=el('div','jvi-ctl');
      const defaultEl=el('p','jvi-default');
      const msg=el('p','jvi-msg');msg.id=msgId;msg.hidden=true;
      [head,meaning,slot,defaultEl,msg].forEach((n)=>li.appendChild(n));
      ctx.chrome={li,label,stateEl,reset,msg,defaultEl,inputId,descId,msgId};
      const widget=makeWidget(ctx,slot,inputId);
      ctx.widget=widget;
      const api={el:li,ctx,update(row){
        ctx.row=row;
        label.textContent=row.label||row.control_id;
        label.title=`${row.control_id} · ${row.type}${row.is_set?'':' · par défaut'}`;
        meaning.textContent=row.meaning||'';meaning.hidden=!row.meaning;
        const s=sessions.get(row.control_id);
        const dirty=!!s&&s.dirty;
        if(!dirty)widget.set(row.current,row);
        widget.refresh(row);
        reset.disabled=!row.is_set||!!(s&&s.committing);
        stateEl.textContent=dirty?'aperçu · non enregistré':(row.is_set?'modifié':'par défaut');
        li.classList.toggle('is-dirty',dirty);
        /* Le défaut n'est dit que lorsqu'il diffère de ce qu'on voit : une valeur déjà par défaut le dit dans son état. */
        defaultEl.textContent=`Par défaut : ${formatValue(row,row.default)}`;
        defaultEl.hidden=!row.is_set||row.default===null||row.default===undefined||sameJson(row.default,row.current);
      },focus(){widget.focus()}};
      label.title=`${row0.control_id} · ${row0.type}`;
      api.update(row0);
      return api;
    }
    function setRowMessage(controlId,kind,text,actions){
      const w=widgets.get(controlId);if(!w)return;
      const c=w.ctx.chrome;
      clear(c.msg);
      c.msg.hidden=!text;
      c.msg.setAttribute('data-kind',kind==='bad'?'bad':kind);
      c.msg.setAttribute('role',kind==='bad'?'alert':'status');
      if(text)c.msg.appendChild(doc.createTextNode(text));
      for(const a of actions||[])c.msg.appendChild(button(a.label,'jvi-btn',a.run));
      c.li.classList.toggle('is-bad',kind==='bad'&&!!text);
      const input=w.ctx.widget&&w.ctx.widget.input;
      if(input){if(kind==='bad'&&text){input.setAttribute('aria-invalid','true');input.setAttribute('aria-describedby',c.msgId)}else{input.removeAttribute('aria-invalid');input.removeAttribute('aria-describedby')}}
    }
    function flashSaved(controlId){
      const w=widgets.get(controlId);if(!w)return;
      const c=w.ctx.chrome;
      c.li.classList.add('is-saved');c.stateEl.textContent='enregistré';
      later(()=>{if(widgets.get(controlId)!==w)return;c.li.classList.remove('is-saved');w.update(w.ctx.row)},SAVED_FLASH_MS);
    }

    /* Un widget : {set(value,row), refresh(row), focus(), input}. Les événements disent seulement « aperçu » ou « valeur finale ». */
    function makeWidget(ctx,slot,inputId){
      const row=ctx.row,spec=widgetSpec(row);
      const id=row.control_id;
      const preview=(value)=>onPreview(ctx,value);
      const commit=(value,opts)=>onCommit(ctx,value,opts);
      const idle=(value)=>onIdle(ctx,value);
      switch(spec.kind){
        case 'slider':case 'number':return numberWidget(ctx,slot,inputId,spec,{preview,commit,idle});
        case 'toggle':return toggleWidget(ctx,slot,inputId,{commit});
        case 'color':return colorWidget(ctx,slot,inputId,{preview,commit});
        case 'segmented':return segmentedWidget(ctx,slot,inputId,spec,{commit});
        case 'select':return selectWidget(ctx,slot,inputId,spec,{commit});
        case 'text':case 'url':return textWidget(ctx,slot,inputId,spec,{preview,commit},false);
        case 'textarea':return textWidget(ctx,slot,inputId,spec,{preview,commit},true);
        case 'stops':return stopsWidget(ctx,slot,inputId,spec,{preview,commit});
        case 'json':return jsonWidget(ctx,slot,inputId,spec,{preview,commit});
        default:{
          const pre=el('pre','jvi-readonly');pre.id=inputId;slot.appendChild(pre);
          log('widget_readonly',{control_id:id,type:row.type});
          return {input:null,set(v){pre.textContent=JSON.stringify(v,null,2)},refresh(){},focus(){pre.setAttribute('tabindex','0');pre.focus()}};
        }
      }
    }

    function numberWidget(ctx,slot,inputId,spec,ev){
      const isRange=spec.kind==='slider';
      let range=null;
      const num=el('input','jvi-num');num.type='number';num.id=inputId;num.step=String(spec.integer?1:'any');
      num.setAttribute('inputmode',spec.integer?'numeric':'decimal');
      if(spec.min!==null)num.min=String(spec.min);
      if(spec.max!==null)num.max=String(spec.max);
      const minus=button('−','jvi-step',null,{'aria-label':`Diminuer ${ctx.row.label}`,tabindex:-1});
      const plus=button('+','jvi-step',null,{'aria-label':`Augmenter ${ctx.row.label}`,tabindex:-1});
      if(isRange){
        range=el('input','jvi-range');range.type='range';
        range.min=String(spec.min);range.max=String(spec.max);range.step=String(spec.step);
        range.setAttribute('aria-label',`${ctx.row.label} (curseur)`);
        slot.appendChild(range);
      }
      slot.appendChild(minus);slot.appendChild(num);slot.appendChild(plus);
      const pct=(v)=>{if(!range)return;const p=spec.max>spec.min?Math.max(0,Math.min(100,(v-spec.min)/(spec.max-spec.min)*100)):0;range.style.setProperty('--pct',p+'%')};
      const parse=(text)=>{const t=String(text).trim().replace(',','.');return t===''?NaN:Number(t)};
      const session=()=>sessionFor(ctx);
      const show=(v)=>{
        if(typeof v==='number'&&Number.isFinite(v)){
          if(String(num.value)!==String(v))num.value=String(v);
          if(range){range.value=String(v);pct(v)}
        }
      };
      const nudge=(dir)=>{
        const cur=parse(num.value);
        const from=Number.isFinite(cur)?cur:(typeof ctx.row.current==='number'?ctx.row.current:0);
        let next=roundTo(from+dir*spec.step,spec.step);
        if(spec.min!==null)next=Math.max(spec.min,next);
        if(spec.max!==null)next=Math.min(spec.max,next);
        show(next);ev.idle(next);
      };
      minus.addEventListener('click',()=>nudge(-1));
      plus.addEventListener('click',()=>nudge(1));
      if(range){
        const release=()=>{const s=session();if(s.pointer){s.pointer=false;ev.commit(Number(range.value),{immediate:true})}};
        range.addEventListener('pointerdown',()=>{session().pointer=true;
          const done=()=>{doc.removeEventListener('pointerup',done,true);doc.removeEventListener('pointercancel',done,true);release()};
          doc.addEventListener('pointerup',done,true);doc.addEventListener('pointercancel',done,true)});
        range.addEventListener('input',()=>{
          const v=spec.integer?Math.round(Number(range.value)):roundTo(Number(range.value),spec.step);
          num.value=String(v);pct(v);
          if(session().pointer)ev.preview(v);else ev.idle(v);
        });
        range.addEventListener('change',()=>{if(session().pointer){session().pointer=false;ev.commit(Number(range.value),{immediate:true})}});
        range.addEventListener('blur',()=>{if(session().dirty)ev.commit(Number(range.value),{immediate:true})});
        range.addEventListener('keydown',(event)=>{if(event.key==='Enter'){event.preventDefault();ev.commit(Number(range.value),{immediate:true})}});
      }
      num.addEventListener('input',()=>{
        const v=parse(num.value);
        if(Number.isNaN(v)){setRowMessage(ctx.row.control_id,'bad','Saisissez un nombre.');return}
        if(range)range.value=String(v),pct(v);
        ev.preview(v);
      });
      num.addEventListener('change',()=>{const v=parse(num.value);if(Number.isNaN(v))return;ev.commit(v,{immediate:true})});
      num.addEventListener('blur',()=>{if(session().dirty){const v=parse(num.value);if(!Number.isNaN(v))ev.commit(v,{immediate:true})}});
      num.addEventListener('keydown',(event)=>{if(event.key==='Enter'){event.preventDefault();const v=parse(num.value);if(!Number.isNaN(v))ev.commit(v,{immediate:true})}});
      return {input:range||num,set:show,refresh(row){
        const v=typeof row.current==='number'?row.current:null;
        minus.disabled=plus.disabled=false;
        if(v!==null&&spec.min!==null)minus.disabled=v<=spec.min;
        if(v!==null&&spec.max!==null)plus.disabled=v>=spec.max;
        if(range)range.setAttribute('aria-valuetext',String(num.value));
      },focus(){(range||num).focus()}};
    }

    function toggleWidget(ctx,slot,inputId,ev){
      const sw=el('button','jvi-switch');sw.type='button';sw.id=inputId;
      attrs(sw,{role:'switch','aria-checked':'false'});
      sw.setAttribute('aria-label',ctx.row.label||ctx.row.control_id);
      const txt=el('span',null,'');
      slot.appendChild(sw);slot.appendChild(txt);
      const show=(v)=>{sw.setAttribute('aria-checked',String(v===true));txt.textContent=v===true?'activé':'désactivé'};
      sw.addEventListener('click',()=>{const next=sw.getAttribute('aria-checked')!=='true';show(next);ev.commit(next,{immediate:true})});
      return {input:sw,set:show,refresh(){},focus(){sw.focus()}};
    }

    function colorWidget(ctx,slot,inputId,ev){
      const pick=el('input','jvi-swatchbtn');pick.type='color';
      pick.setAttribute('aria-label',`${ctx.row.label} (sélecteur de couleur)`);
      const hex=el('input','jvi-hex');hex.type='text';hex.id=inputId;hex.maxLength=7;hex.setAttribute('spellcheck','false');
      hex.setAttribute('autocomplete','off');hex.setAttribute('aria-label',`${ctx.row.label} (valeur hexadécimale)`);
      slot.appendChild(pick);slot.appendChild(hex);
      const session=()=>sessionFor(ctx);
      const show=(v)=>{if(typeof v==='string'&&HEX_COLOR.test(v)){pick.value=v.toLowerCase();hex.value=v.toLowerCase()}};
      pick.addEventListener('input',()=>{hex.value=pick.value;session().pointer=true;ev.preview(pick.value)});
      pick.addEventListener('change',()=>{session().pointer=false;ev.commit(pick.value,{immediate:true})});
      hex.addEventListener('input',()=>{
        const t=hex.value.trim();
        if(HEX_COLOR.test(t)){pick.value=t.toLowerCase();ev.preview(t.toLowerCase())}
        else setRowMessage(ctx.row.control_id,'bad','Couleur attendue au format #rrggbb.');
      });
      const finish=()=>{const t=hex.value.trim();if(HEX_COLOR.test(t))ev.commit(t.toLowerCase(),{immediate:true});else if(session().dirty||t!==ctx.row.current)setRowMessage(ctx.row.control_id,'bad','Couleur attendue au format #rrggbb. Rien n\'a été enregistré.')};
      hex.addEventListener('change',finish);
      hex.addEventListener('blur',()=>{if(session().dirty)finish()});
      hex.addEventListener('keydown',(event)=>{if(event.key==='Enter'){event.preventDefault();finish()}});
      return {input:hex,set:show,refresh(){},focus(){hex.focus()}};
    }

    function segmentedWidget(ctx,slot,inputId,spec,ev){
      const group=el('div','jvi-seg');group.id=inputId;
      attrs(group,{role:'radiogroup','aria-label':ctx.row.label||ctx.row.control_id});
      const buttons=spec.choices.map((choice)=>{
        const b=button(String(choice),null,null,{role:'radio','aria-checked':'false',tabindex:-1});
        b.setAttribute('data-value',String(choice));
        group.appendChild(b);return b;
      });
      slot.appendChild(group);
      const show=(v)=>{
        buttons.forEach((b,i)=>{const on=spec.choices[i]===v;b.setAttribute('aria-checked',String(on))});
        const tabbable=buttons.findIndex((b,i)=>spec.choices[i]===v);
        buttons.forEach((b,i)=>b.setAttribute('tabindex',String(i===(tabbable<0?0:tabbable)?0:-1)));
      };
      const choose=(i)=>{show(spec.choices[i]);buttons[i].focus();ev.commit(spec.choices[i],{immediate:true})};
      buttons.forEach((b,i)=>{
        b.addEventListener('click',()=>choose(i));
        b.addEventListener('keydown',(event)=>{
          const move={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1}[event.key];
          if(move){event.preventDefault();choose((i+move+buttons.length)%buttons.length)}
          else if(event.key==='Home'){event.preventDefault();choose(0)}
          else if(event.key==='End'){event.preventDefault();choose(buttons.length-1)}
        });
      });
      return {input:null,set:show,refresh(){},focus(){const t=buttons.find((b)=>b.getAttribute('tabindex')==='0')||buttons[0];if(t)t.focus()}};
    }

    function selectWidget(ctx,slot,inputId,spec,ev){
      const select=el('select');select.id=inputId;
      for(const choice of spec.choices){const o=el('option',null,String(choice));o.value=String(choice);select.appendChild(o)}
      slot.appendChild(select);
      select.addEventListener('change',()=>{
        const index=spec.choices.findIndex((c)=>String(c)===select.value);
        if(index>=0)ev.commit(spec.choices[index],{immediate:true});
      });
      return {input:select,set(v){select.value=String(v)},refresh(){},focus(){select.focus()}};
    }

    function textWidget(ctx,slot,inputId,spec,ev,multi){
      const field=multi?el('textarea'):el('input');
      if(!multi)field.type=spec.kind==='url'?'url':'text';
      field.id=inputId;
      if(spec.maxLength)field.maxLength=spec.maxLength*2;     /* le compteur et la validation disent la limite exacte */
      field.setAttribute('autocomplete','off');
      if(spec.kind==='url'||!multi)field.setAttribute('spellcheck','false');
      const wrap=el('div');wrap.style.flex='1 1 auto';wrap.style.minWidth='0';wrap.appendChild(field);
      const count=el('div','jvi-count');count.hidden=!spec.maxLength;
      wrap.appendChild(count);slot.appendChild(wrap);
      const session=()=>sessionFor(ctx);
      const upd=()=>{if(spec.maxLength)count.textContent=`${field.value.length} / ${spec.maxLength}`};
      field.addEventListener('input',()=>{upd();ev.preview(field.value,{text:true})});
      const finish=()=>{if(session().dirty||field.value!==String(ctx.row.current===null||ctx.row.current===undefined?'':ctx.row.current))ev.commit(field.value,{immediate:true})};
      field.addEventListener('change',finish);
      field.addEventListener('blur',()=>{if(session().dirty)finish()});
      field.addEventListener('keydown',(event)=>{
        if(event.key==='Enter'&&(!multi||event.ctrlKey||event.metaKey)){event.preventDefault();ev.commit(field.value,{immediate:true})}
      });
      return {input:field,set(v){const t=v===null||v===undefined?'':String(v);if(field.value!==t)field.value=t;upd()},refresh(){},focus(){field.focus()}};
    }

    function stopsWidget(ctx,slot,inputId,spec,ev){
      const wrap=el('div');wrap.style.flex='1 1 auto';wrap.style.minWidth='0';wrap.id=inputId;
      wrap.setAttribute('tabindex','-1');
      const bar=el('div','jvi-grad');bar.setAttribute('aria-hidden','true');
      const list=el('ul','jvi-stops');
      const add=button('Ajouter une étape','jvi-btn',null);
      wrap.appendChild(bar);wrap.appendChild(list);wrap.appendChild(add);slot.appendChild(wrap);
      let stops=[];
      const paintBar=()=>{bar.style.background=stops.length>1?`linear-gradient(90deg,${stops.join(',')})`:(stops[0]||'transparent')};
      const publish=(final)=>{paintBar();const copy=stops.slice();if(final)ev.commit(copy,{immediate:true});else ev.preview(copy)};
      const rebuild=()=>{
        clear(list);
        stops.forEach((color,i)=>{
          const li=el('li','jvi-stop');
          const pick=el('input','jvi-swatchbtn');pick.type='color';pick.value=color;pick.setAttribute('aria-label',`${ctx.row.label} : étape ${i+1} sur ${stops.length}`);
          const hex=el('input','jvi-hex');hex.type='text';hex.value=color;hex.maxLength=7;hex.setAttribute('aria-label',`${ctx.row.label} : étape ${i+1}, valeur hexadécimale`);
          pick.addEventListener('input',()=>{stops[i]=pick.value;hex.value=pick.value;publish(false)});
          pick.addEventListener('change',()=>{stops[i]=pick.value;publish(true)});
          const fin=()=>{const t=hex.value.trim();if(HEX_COLOR.test(t)){stops[i]=t.toLowerCase();pick.value=stops[i];publish(true)}else setRowMessage(ctx.row.control_id,'bad','Couleur attendue au format #rrggbb. Rien n\'a été enregistré.')};
          hex.addEventListener('change',fin);
          hex.addEventListener('keydown',(event)=>{if(event.key==='Enter'){event.preventDefault();fin()}});
          const up=button('↑','jvi-step',()=>{if(i>0){[stops[i-1],stops[i]]=[stops[i],stops[i-1]];rebuild();publish(true)}},{'aria-label':`Monter l'étape ${i+1}`});
          const down=button('↓','jvi-step',()=>{if(i<stops.length-1){[stops[i+1],stops[i]]=[stops[i],stops[i+1]];rebuild();publish(true)}},{'aria-label':`Descendre l'étape ${i+1}`});
          const del=button('×','jvi-step',()=>{stops.splice(i,1);rebuild();publish(true)},{'aria-label':`Retirer l'étape ${i+1}`});
          up.disabled=i===0;down.disabled=i===stops.length-1;del.disabled=stops.length<=1;
          [pick,hex,up,down,del].forEach((n)=>li.appendChild(n));list.appendChild(li);
        });
        add.disabled=spec.maxItems!==null&&stops.length>=spec.maxItems;
      };
      add.addEventListener('click',()=>{stops.push(stops[stops.length-1]||'#ffffff');rebuild();publish(true)});
      return {input:wrap,set(v){if(Array.isArray(v)&&v.every((c)=>typeof c==='string'&&HEX_COLOR.test(c))){const next=v.map((c)=>c.toLowerCase());if(sameJson(next,stops)&&list.firstChild)return;stops=next;rebuild();paintBar()}},
        refresh(){},focus(){const first=list.querySelector('input');if(first)first.focus()}};
    }

    function jsonWidget(ctx,slot,inputId,spec,ev){
      const area=el('textarea','jvi-json');area.id=inputId;area.setAttribute('spellcheck','false');
      const wrap=el('div');wrap.style.flex='1 1 auto';wrap.style.minWidth='0';wrap.appendChild(area);
      const note=el('div','jvi-count',`JSON : un tableau${spec.maxItems?`, au plus ${spec.maxItems} éléments`:''}. Vérifié avant envoi, puis par Core.`);
      note.style.textAlign='left';wrap.appendChild(note);slot.appendChild(wrap);
      const session=()=>sessionFor(ctx);
      const parse=()=>{try{return {ok:true,value:JSON.parse(area.value)}}catch(error){return {ok:false,error:describe(error)}}};
      area.addEventListener('input',()=>{
        const p=parse();
        if(!p.ok){setRowMessage(ctx.row.control_id,'bad',`JSON invalide : ${clip(p.error,120)}. Rien n'est envoyé.`);return}
        ev.preview(p.value);
      });
      const finish=()=>{
        const p=parse();
        if(!p.ok){setRowMessage(ctx.row.control_id,'bad',`JSON invalide : ${clip(p.error,120)}. Rien n'a été enregistré.`);return}
        ev.commit(p.value,{immediate:true});
      };
      area.addEventListener('change',finish);
      area.addEventListener('blur',()=>{if(session().dirty)finish()});
      area.addEventListener('keydown',(event)=>{
        if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();finish()}
      });
      return {input:area,set(v){const t=JSON.stringify(v===undefined?null:v,null,2);const p=parse();if(p.ok&&sameJson(p.value,v)&&area.value!=='')return;area.value=t},refresh(){},focus(){area.focus()}};
    }

    /* -------------------------------------------------------------- brouillons : aperçu, enregistrement */
    function sessionFor(ctx){
      const id=ctx.row.control_id;
      let s=sessions.get(id);
      if(!s){
        s={id,dirty:false,draft:undefined,pointer:false,previewTimer:null,idleTimer:null,inflight:false,latest:undefined,hasLatest:false,
          lastSentAt:-Infinity,lastSent:undefined,epoch:0,committing:false,previews:0};
        sessions.set(id,s);
      }
      return s;
    }
    function clearTimers(s){
      if(s.previewTimer!==null){cancelLater(s.previewTimer);s.previewTimer=null}
      if(s.idleTimer!==null){cancelLater(s.idleTimer);s.idleTimer=null}
    }
    function editable(){
      if(!S.available){return false}
      if(!S.variant||!S.scene)return false;
      return true;
    }
    function onPreview(ctx,value,opts){
      if(!editable())return;
      const row=ctx.row,s=sessionFor(ctx);
      const problem=validateValue(row,value);
      if(problem){setRowMessage(row.control_id,'bad',problem);clearTimers(s);return}
      setRowMessage(row.control_id,'info','');
      s.dirty=true;s.draft=value;s.latest=value;s.hasLatest=true;
      const w=widgets.get(row.control_id);if(w){w.ctx.chrome.li.classList.add('is-dirty');w.ctx.chrome.stateEl.textContent='aperçu · non enregistré'}
      syncPreview();          /* aperçu local immédiat : le cadre reçoit la valeur avant que Core réponde ; un refus la reprend */
      schedulePreview(ctx,s,opts&&opts.text?TEXT_PREVIEW_MS:PREVIEW_MIN_MS);
    }
    function schedulePreview(ctx,s,minMs){
      if(s.inflight)return;                      /* la réponse en attente relancera avec la dernière valeur */
      const wait=Math.max(0,s.lastSentAt+minMs-now());
      if(s.previewTimer!==null){stats.previewsCoalesced++;return}
      if(wait===0){sendPreview(ctx,s);return}
      s.previewTimer=later(()=>{s.previewTimer=null;sendPreview(ctx,s)},wait);
    }
    async function sendPreview(ctx,s){
      if(!s.hasLatest||s.inflight||s.committing)return;
      const value=s.latest;s.hasLatest=false;
      if(s.lastSent!==undefined&&sameJson(s.lastSent,value))return;
      s.inflight=true;s.lastSentAt=now();s.lastSent=value;s.previews++;stats.previews++;
      const epoch=s.epoch;
      try{
        const outcome=await postEdit('preview',[{op:'control.set',scene_id:S.sceneId,control_id:ctx.row.control_id,value}]);
        if(epoch!==s.epoch)return;               /* un enregistrement ou un abandon a tourné la page */
        if(outcome.kind==='applied'){setRowMessage(ctx.row.control_id,'info','');return}
        if(outcome.kind==='stale'){handleStale(ctx,s,value,'preview');return}
        if(outcome.kind==='refused'||outcome.kind==='error'){
          showRefusal(ctx,outcome,value);
          syncPreview();                          /* le cadre reprend la dernière valeur valide */
          return;
        }
        if(outcome.kind==='reloading'){setRowMessage(ctx.row.control_id,'warn','Scène en rechargement : l\'aperçu reprendra, l\'enregistrement attendra.')}
      }catch(error){
        if(epoch!==s.epoch)return;
        stats.failures++;
        setRowMessage(ctx.row.control_id,'bad',`Aperçu non validé : ${describe(error)}`);
        log('preview_failed',{control_id:ctx.row.control_id,code:error.code,error:describe(error)},'warn');
      }finally{
        s.inflight=false;
        if(epoch===s.epoch&&s.hasLatest)schedulePreview(ctx,s,PREVIEW_MIN_MS);
      }
    }
    /* Clavier et ± : le dernier appui arme un seul enregistrement après une courte pause. */
    function onIdle(ctx,value){
      onPreview(ctx,value);
      const s=sessionFor(ctx);
      if(s.idleTimer!==null)cancelLater(s.idleTimer);
      s.idleTimer=later(()=>{s.idleTimer=null;if(s.dirty&&s.draft!==undefined)onCommit(ctx,s.draft,{immediate:true})},IDLE_COMMIT_MS);
    }
    function onCommit(ctx,value,opts){
      if(!editable())return Promise.resolve(null);
      const row=ctx.row,s=sessionFor(ctx);
      clearTimers(s);
      s.epoch++;s.hasLatest=false;
      const problem=validateValue(row,value);
      if(problem){
        setRowMessage(row.control_id,'bad',`${problem} Rien n'a été enregistré.`);
        return Promise.resolve(null);
      }
      if(sameJson(value,row.current)){
        s.dirty=false;s.draft=undefined;
        setRowMessage(row.control_id,'info','');
        const w=widgets.get(row.control_id);if(w)w.update(row);
        syncPreview();
        return Promise.resolve(null);
      }
      s.dirty=true;s.draft=value;
      const op={op:'control.set',scene_id:S.sceneId,control_id:row.control_id,value,if_current:row.current};
      return enqueue(row.control_id,(task)=>runCommit(ctx,s,op,value,task),`Enregistrement de « ${row.label} »`);
    }
    function resetControl(row){
      if(!editable())return;
      const ctx={row};
      const w=widgets.get(row.control_id);
      const s=sessionFor(w?w.ctx:ctx);
      clearTimers(s);s.epoch++;s.hasLatest=false;s.dirty=true;s.draft=row.default;
      const op={op:'control.reset',scene_id:S.sceneId,control_id:row.control_id,if_current:row.current};
      enqueue(row.control_id,(task)=>runCommit(w?w.ctx:ctx,s,op,row.default,task,'reset'),`Rétablissement de « ${row.label} »`);
    }
    function revertDraft(ctx){
      const s=sessions.get(ctx.row.control_id);
      if(s){clearTimers(s);s.epoch++;s.dirty=false;s.draft=undefined;s.hasLatest=false}
      const w=widgets.get(ctx.row.control_id);
      if(w){w.ctx.widget.set(ctx.row.current,ctx.row);w.update(ctx.row)}
      setRowMessage(ctx.row.control_id,'info','');
      syncPreview();
      announce(`${ctx.row.label} : modification abandonnée.`);
    }
    function abandonDrafts(reason){
      for(const s of sessions.values()){clearTimers(s);s.epoch++;s.dirty=false;s.draft=undefined;s.hasLatest=false}
      if(sessions.size)log('drafts_abandoned',{count:sessions.size,reason});
      sessions.clear();
      for(const task of queue.pending.values())task.superseded=true;
      queue.pending.clear();
      if(S.reloading){S.reloading=null;renderStatus()}
    }

    /* File d'écritures : UNE à la fois (la base `variant_revision` avance à chaque succès) ; une écriture encore en attente pour le
       même réglage est remplacée par la plus récente. */
    function enqueue(key,run,label){
      const prior=queue.pending.get(key);
      if(prior){prior.superseded=true;stats.writesSuperseded++}
      const task={key,superseded:false,label};
      queue.pending.set(key,task);
      const job=queue.tail.then(()=>{
        if(task.superseded)return null;
        return run(task);
      }).catch((error)=>{log('queue_failed',{key,error:describe(error)},'error');return null})
        .finally(()=>{if(queue.pending.get(key)===task)queue.pending.delete(key)});
      queue.tail=job;
      return job;
    }

    async function postEdit(mode,ops){
      const response=await call(`${variantBase()}/edits`,{method:'POST',timeoutMs:REQUEST_TIMEOUT_MS,
        body:{mode,basis:{variant_revision:S.scene?S.scene.variant_revision:S.variant.revision},ops}});
      return classifyEdit(response);
    }
    function classifyEdit(response){
      const body=response.body;
      if(body&&typeof body.status==='string'&&(body.status==='applied'||body.status==='refused'||body.status==='stale')){
        if(body.status==='applied')return {kind:'applied',result:body};
        if(body.status==='stale')return {kind:'stale',result:body,code:body.code,message:body.message};
        return {kind:'refused',result:body,code:body.code,message:body.message};
      }
      const e=envelopeOf(response);
      if(e.code==='presentation_studio_scene_reloading')return {kind:'reloading',code:e.code,message:e.message};
      return {kind:'error',code:e.code,message:e.message,http:e.http};
    }

    async function runCommit(ctx,s,op,value,task,why){
      const id=ctx.row.control_id;
      s.committing=true;
      const w0=widgets.get(id);if(w0){w0.ctx.chrome.li.classList.add('is-busy');w0.ctx.chrome.reset.disabled=true}
      try{
        let attempt=0;
        for(;;){
          if(task.superseded){return null}
          let outcome;
          try{
            outcome=await postEdit('commit',[op]);
          }catch(error){
            stats.failures++;
            setRowMessage(id,'bad',`Enregistrement impossible : ${describe(error)}`,[{label:'Réessayer',run:()=>retryCommit(ctx,value,why)}]);
            log('commit_failed',{control_id:id,code:error.code,error:describe(error)},'error');
            tell('Enregistrement impossible',describe(error),'bad');
            return null;
          }
          if(outcome.kind==='reloading'){
            if(attempt>=RELOAD_RETRY_MS.length){
              S.reloading=null;renderStatus();
              setRowMessage(id,'bad','La scène est restée en rechargement trop longtemps. Rien n\'a été enregistré.',[{label:'Réessayer',run:()=>retryCommit(ctx,value,why)}]);
              log('reload_gave_up',{control_id:id,attempts:attempt},'error');
              tell('Scène en rechargement','Modification non enregistrée : réessayez dans un instant.','bad');
              return null;
            }
            const delay=RELOAD_RETRY_MS[attempt];attempt++;stats.reloadRetries++;
            S.reloading={attempt,max:RELOAD_RETRY_MS.length,nextAt:now()+delay,cancelled:false,taskKey:id};
            pendingRetry=task;
            renderStatus();
            log('reload_wait',{control_id:id,attempt,delay_ms:delay},'warn');
            announce(`Scène en rechargement, nouvelle tentative ${attempt} sur ${RELOAD_RETRY_MS.length}.`);
            await new Promise((resolve)=>later(resolve,delay));
            if(task.superseded||(S.reloading&&S.reloading.cancelled)){S.reloading=null;renderStatus();
              if(!task.superseded){setRowMessage(id,'warn','Attente arrêtée : rien n\'a été enregistré.',[{label:'Réessayer',run:()=>retryCommit(ctx,value,why)}])}
              return null}
            continue;
          }
          S.reloading=null;renderStatus();
          return await finishCommit(ctx,s,op,value,outcome);
        }
      }finally{
        s.committing=false;
        const w=widgets.get(id);if(w){w.ctx.chrome.li.classList.remove('is-busy');w.ctx.chrome.reset.disabled=!w.ctx.row.is_set}
      }
    }
    function retryCommit(ctx,value,why){
      const w=widgets.get(ctx.row.control_id);
      const row=w?w.ctx.row:ctx.row;
      setRowMessage(row.control_id,'info','');
      if(why==='reset')resetControl(row);else onCommit(w?w.ctx:ctx,value,{immediate:true});
    }
    function giveUpReload(){
      if(!S.reloading)return;
      S.reloading.cancelled=true;
      if(pendingRetry)pendingRetry.superseded=true;
      log('reload_wait_cancelled',{attempt:S.reloading.attempt},'warn');
      S.reloading=null;renderStatus();
    }
    async function finishCommit(ctx,s,op,value,outcome){
      const id=ctx.row.control_id;
      if(outcome.kind==='applied'){
        const result=outcome.result;
        stats.commits++;
        const previews=s.previews;s.previews=0;
        s.dirty=false;s.draft=undefined;s.lastSent=undefined;
        log('commit_applied',{control_id:id,op:op.op,revision:result.revision,changed:!!result.changed,previews});
        setRowMessage(id,'info','');
        await Promise.all([loadScene({quiet:true}),loadHistory()]);
        flashSaved(id);
        announce(`${ctx.row.label} : enregistré.`);
        return result;
      }
      if(outcome.kind==='stale'){return handleStale(ctx,s,value,'commit',op)}
      if(outcome.kind==='refused'||outcome.kind==='error'){
        s.dirty=false;s.draft=undefined;s.lastSent=undefined;
        showRefusal(ctx,outcome,value);
        if(outcome.code==='presentation_studio_unknown_control'||outcome.code==='presentation_studio_unknown_scene'||outcome.code==='presentation_studio_scene_incompatible'){
          await loadScene({quiet:true});
        }else{
          const w=widgets.get(id);if(w){w.ctx.widget.set(w.ctx.row.current,w.ctx.row);w.update(w.ctx.row)}
          syncPreview();
        }
        return null;
      }
      return null;
    }
    function showRefusal(ctx,outcome,value){
      const id=ctx.row.control_id;
      const text=describeRefusal(outcome.code,outcome.message);
      stats.failures++;
      setRowMessage(id,'bad',text);
      log('edit_refused',{control_id:id,code:outcome.code,status:outcome.kind,http:outcome.http||null},'warn');
      announce(`${ctx.row.label} : ${text}`);
      if(outcome.kind==='error'&&(outcome.http>=500||!outcome.http))tell('Modification refusée',text,'bad');
    }
    /* Base périmée (ou valeur modifiée ailleurs) : relire, dire ce qui a changé, ne rien écraser. */
    async function handleStale(ctx,s,value,phase,op){
      const id=ctx.row.control_id;
      stats.staleHandled++;
      clearTimers(s);s.epoch++;s.hasLatest=false;
      const diff=await loadScene({quiet:true});
      await loadHistory();
      const changes=diff?diffControls(diff.before,diff.after):[];
      const mine=changes.find((c)=>c.control_id===id);
      s.dirty=false;s.draft=undefined;s.lastSent=undefined;
      const w=widgets.get(id);
      const now_=w?w.ctx.row:ctx.row;
      const lines=changes.slice(0,5).map((c)=>`${c.label} : ${formatValue(null,c.before)} → ${formatValue(null,c.after)}`);
      const more=changes.length>5?` (+${changes.length-5} autres)`:'';
      const text=phase==='commit'||mine?`La présentation a changé ailleurs avant votre réglage, il n'a pas été appliqué. Valeurs relues${lines.length?' : '+lines.join(' ; ')+more:' (aucune différence sur cette scène)'}.`:
        `La présentation a changé ailleurs : valeurs relues${lines.length?' : '+lines.join(' ; ')+more:''}.`;
      const reapply=(phase==='commit'||mine)&&!sameJson(value,now_.current);
      setRowMessage(id,'warn',text,reapply?[{label:`Réappliquer ma valeur (${formatValue(now_,value)})`,run:()=>{setRowMessage(id,'info','');
        const wx=widgets.get(id);onCommit(wx?wx.ctx:ctx,value,{immediate:true})}}]:[]);
      log('edit_stale',{control_id:id,phase,changed:changes.map((c)=>c.control_id)},'warn');
      tell('Modification périmée',lines[0]||'Les valeurs ont été relues.','warn');
      announce('La présentation a changé ailleurs : valeurs relues.');
      return null;
    }

    /* -------------------------------------------------------------- annuler, rétablir */
    async function runHistory(direction){
      if(!S.variant||!S.available)return;
      const h=S.history,entry=h&&(direction==='undo'?h.next_undo:h.next_redo);
      for(const s of sessions.values()){clearTimers(s);s.epoch++}
      const body={};
      if(entry&&entry.entry_id)body.expected_entry_id=entry.entry_id;
      stats[direction]++;
      ui.undo.disabled=true;ui.redo.disabled=true;
      setStatus('info',direction==='undo'?'Annulation…':'Rétablissement…','');
      let attempt=0;
      try{
        for(;;){
          const response=await call(`${variantBase()}/${direction}`,{method:'POST',body,timeoutMs:REQUEST_TIMEOUT_MS});
          const result=response.body;
          if(result&&typeof result.status==='string'&&(result.status==='applied'||Object.prototype.hasOwnProperty.call(HISTORY_TEXT,result.status))){
            if(result.status==='applied'){
              log('history_applied',{direction,revision:result.revision});
              setStatus(null);
              await Promise.all([loadScene({quiet:true}),loadHistory()]);
              setStatus('ok',direction==='undo'?'Modification annulée':'Modification rétablie','');
              later(()=>{if(S.status&&S.status.kind==='ok')setStatus(null)},4000);
              announce(direction==='undo'?'Modification annulée.':'Modification rétablie.');
              return result;
            }
            const text=`${HISTORY_TEXT[result.status]}.${result.message?' '+clip(result.message,300):''}`;
            log('history_not_applied',{direction,status:result.status,reason:result.reason||null,code:result.code||null},'warn');
            setStatus(result.status==='stale'?'warn':'info',direction==='undo'?'Annulation impossible':'Rétablissement impossible',text);
            announce(text);
            if(result.status==='stale'||result.status==='refused')await Promise.all([loadScene({quiet:true}),loadHistory()]);
            else await loadHistory();
            return result;
          }
          const e=envelopeOf(response);
          if(e.code==='presentation_studio_scene_reloading'&&attempt<RELOAD_RETRY_MS.length){
            const delay=RELOAD_RETRY_MS[attempt];attempt++;stats.reloadRetries++;
            S.reloading={attempt,max:RELOAD_RETRY_MS.length,nextAt:now()+delay,cancelled:false,taskKey:direction};
            renderStatus();log('reload_wait',{direction,attempt,delay_ms:delay},'warn');
            await new Promise((resolve)=>later(resolve,delay));
            if(S.reloading&&S.reloading.cancelled){S.reloading=null;setStatus('warn','Attente arrêtée','Rien n\'a été annulé.');return null}
            continue;
          }
          S.reloading=null;
          setStatus('bad',direction==='undo'?'Annulation impossible':'Rétablissement impossible',describeRefusal(e.code,e.message));
          log('history_failed',{direction,code:e.code,http:e.http},'error');
          return null;
        }
      }catch(error){
        stats.failures++;
        setStatus('bad','Core ne répond pas',describe(error),[{label:'Réessayer',run:()=>{runHistory(direction)}}]);
        log('history_failed',{direction,code:error.code,error:describe(error)},'error');
        tell('Annuler / rétablir impossible',describe(error),'bad');
        return null;
      }finally{
        S.reloading=null;renderStatus();renderHistory();
      }
    }

    /* -------------------------------------------------------------- aperçu local (cadre sandboxé, mode preview) */
    function ensureHost(){
      if(previewHost)return previewHost;
      const api=d.prefabHost||root.JarvisPrefabHost;
      if(!api||typeof api.createPrefabHost!=='function')return null;
      try{
        previewHost=api.createPrefabHost({mode:'preview',document:doc,window:win,
          fetchBundle:api.bundleFetcher((path,options)=>fetchImpl(path,Object.assign({cache:'no-store'},options))),
          onPreviewEvent:()=>{/* intentional: the preview frame writes nothing anywhere; its events are dropped */},
          log:(key,data)=>{if(key!=='scene.prefab_mounted')log('preview_host_'+String(key).replace(/^scene\./,''),data,'warn')}});
      }catch(error){
        log('preview_host_failed',{error:describe(error)},'error');previewHost=null;
      }
      return previewHost;
    }
    function unmountPreview(){
      if(previewHost&&previewMounted){try{previewHost.unmount(PREVIEW_OBJECT_ID)}catch(_error){/* intentional: the frame is gone either way */}}
      previewMounted=null;
      if(ui.slot)clear(ui.slot);
    }
    function syncPreview(){
      if(!ui.stage)return;
      const scene=S.scene;
      ui.stage.hidden=!scene||!storedScene;
      if(!scene||!storedScene||!S.open||!S.available){return}
      ui.stage.open=S.showPreview;
      if(!S.showPreview)return;
      const host=ensureHost();
      if(!host){ui.stageNote.textContent='Aperçu indisponible : le runtime des prefabs n\'est pas chargé dans cette page.';return}
      const live=[];
      for(const s of sessions.values()){
        if(s.dirty&&s.draft!==undefined){const w=widgets.get(s.id);if(w)live.push({path:w.ctx.row.path,value:s.draft})}
      }
      const values=previewValues(storedScene,scene.controls,live);
      const pin=scene.prefab||storedScene.prefab;
      if(!pin)return;
      ui.stageSummary.textContent=`Aperçu local · ${clip(scene.title||storedScene.title||'scène',40)}`;
      try{
        host.mount(ui.slot,{object_id:PREVIEW_OBJECT_ID,prefab:{id:pin.id,version:pin.version},title:scene.title||'',props:values.props,data:values.data});
        previewMounted=pin;
      }catch(error){
        ui.stageNote.textContent=`Aperçu impossible : ${describe(error)}`;
        log('preview_mount_failed',{error:describe(error)},'error');
      }
    }

    /* -------------------------------------------------------------- clavier */
    function inTextField(target){
      if(!target)return false;
      const tag=String(target.tagName||'').toUpperCase();
      if(tag==='TEXTAREA')return true;
      if(tag!=='INPUT')return false;
      return !['range','color','checkbox','radio','button'].includes(String(target.type||'').toLowerCase());
    }
    function onPanelKey(event){
      const key=event.key;
      const mod=event.ctrlKey||event.metaKey;
      if(mod&&!event.altKey&&(key==='z'||key==='Z'||key==='y'||key==='Y')){
        const target=event.target;
        const s=target&&target.closest?target.closest('[data-control-id]'):null;
        const id=s?s.getAttribute('data-control-id'):null;
        const dirty=id&&sessions.get(id)&&sessions.get(id).dirty;
        if(inTextField(target)&&dirty)return;          /* l'annulation du champ est celle du navigateur tant qu'il est modifié */
        event.preventDefault();event.stopPropagation();
        const redo=key==='y'||key==='Y'||event.shiftKey;
        runHistory(redo?'redo':'undo');
        return;
      }
      if(key==='Escape'){
        event.preventDefault();event.stopPropagation();
        const row=event.target&&event.target.closest?event.target.closest('[data-control-id]'):null;
        const id=row?row.getAttribute('data-control-id'):null;
        const s=id?sessions.get(id):null;
        if(s&&s.dirty&&widgets.get(id)){revertDraft(widgets.get(id).ctx);return}     /* d'abord abandonner le brouillon, ensuite fermer */
        close({restoreFocus:true});
        return;
      }
      /* Aucune touche non modifiée ne sort du panneau : ni raccourcis de la page (s, e, t, a…), ni navigation de la scène. Tab reste libre. */
      if(!mod&&!event.altKey&&key!=='Tab'&&!/^F\d{1,2}$/.test(key))event.stopPropagation();
    }

    /* -------------------------------------------------------------- disponibilité (lecture, plein écran) */
    function checkAvailability(){
      let reason=null;
      try{
        if(inFullscreen())reason='fullscreen';
        else if(playing())reason='playback';
      }catch(error){log('availability_failed',{error:describe(error)},'warn')}
      const available=reason===null;
      if(available===S.available&&reason===S.hiddenReason)return;
      S.available=available;S.hiddenReason=reason;
      applyAvailability();
    }
    function applyAvailability(){
      if(ui.dock){
        ui.dock.disabled=!S.available;
        ui.dock.setAttribute('aria-disabled',String(!S.available));
        ui.dock.title=S.available?'Inspecteur · réglages de la présentation':
          (S.hiddenReason==='fullscreen'?'Inspecteur masqué : plein écran':'Inspecteur masqué pendant une présentation');
      }
      if(!ui.root)return;
      if(!S.available){
        stats.hiddenByPlayback++;
        close({});                       /* ferme, abandonne les brouillons, rend le cadre d'aperçu et coupe la relève */
        ui.root.hidden=true;ui.root.inert=true;
        log('hidden',{reason:S.hiddenReason});
      }else{
        ui.root.inert=false;ui.root.hidden=!S.open;
        log('available',{});
      }
    }
    function startPolling(){if(pollTimer===null)pollTimer=every(()=>{pollReloads()},POLL_MS)}
    function stopPolling(){if(pollTimer!==null){stopEvery(pollTimer);pollTimer=null}}

    /* -------------------------------------------------------------- ouverture */
    function open(options){
      if(!S.available){
        log('open_refused',{reason:S.hiddenReason},'warn');
        tell('Inspecteur indisponible',S.hiddenReason==='fullscreen'?'Quittez le plein écran pour régler la présentation.':'Arrêtez la présentation en cours pour la régler.','warn');
        return false;
      }
      build();
      const p=prefs();
      if(typeof p.tab==='string'&&GROUPS.includes(p.tab))S.tab=p.tab;
      S.showPreview=p.preview!==false;
      try{const player=root.JarvisStudioPlayer;if(player&&typeof player.refresh==='function')Promise.resolve(player.refresh()).then(checkAvailability,()=>{})}catch(_error){/* intentional: the periodic check follows */}
      checkAvailability();
      if(!S.available)return false;
      S.open=true;
      ui.root.hidden=false;ui.root.inert=false;
      if(ui.dock){ui.dock.classList.add('active');ui.dock.setAttribute('aria-expanded','true')}
      const closeSidePanel=typeof d.closeSidePanel==='function'?d.closeSidePanel:(typeof root.closePanel==='function'?root.closePanel:null);
      if(closeSidePanel){try{closeSidePanel()}catch(_error){/* intentional: the side panel closing is a courtesy */}}
      ui.stage.open=S.showPreview;
      startPolling();
      log('opened',{});
      loadPresentations().then(()=>{if(!(options&&options.noFocus)&&ui.title)ui.title.focus()});
      return true;
    }
    function close(options){
      if(!S.open&&!(ui.root&&!ui.root.hidden))return;
      abandonDrafts('close');
      S.open=false;
      stopPolling();
      unmountPreview();
      if(ui.root)ui.root.hidden=true;
      if(ui.dock){ui.dock.classList.remove('active');ui.dock.setAttribute('aria-expanded','false')}
      if(options&&options.restoreFocus&&ui.dock&&!ui.dock.disabled)ui.dock.focus();
      log('closed',{});
    }
    function toggle(){S.open?close({restoreFocus:true}):open()}

    function install(){
      ui.dock=doc.getElementById(BUTTON_ID);
      build();
      if(ui.dock){
        ui.dock.addEventListener('click',toggle);
      }
      /* Ouvrir un panneau latéral (ERR, TRC, AGT) occupe le même emplacement : l'inspecteur se range. */
      if(typeof doc.querySelectorAll==='function'){
        for(const b of doc.querySelectorAll('.dock button[data-panel]'))b.addEventListener('click',()=>{if(S.open)close({})},true);
      }
      if(typeof doc.addEventListener==='function'){
        doc.addEventListener('fullscreenchange',checkAvailability);
        doc.addEventListener('visibilitychange',()=>{if(S.open&&!doc.hidden)pollReloads()});
      }
      availTimer=every(checkAvailability,AVAILABILITY_MS);
      checkAvailability();
      log('installed',{dock:!!ui.dock});
    }
    function destroy(){
      close({});
      if(availTimer!==null){stopEvery(availTimer);availTimer=null}
      if(previewHost&&typeof previewHost.destroy==='function')previewHost.destroy();
    }

    const view=()=>({open:S.open,available:S.available,hiddenReason:S.hiddenReason,presentation_id:S.presentationId,
      variant_id:S.variant&&S.variant.variant_id,revision:S.scene?S.scene.variant_revision:(S.variant&&S.variant.revision),scene_id:S.sceneId,
      tab:S.tab,controls:S.scene?(S.scene.controls||[]).map((r)=>({control_id:r.control_id,current:r.current,is_set:r.is_set})):[],
      reloading:S.reloading?{attempt:S.reloading.attempt,max:S.reloading.max}:null,history:S.history?{undo:S.history.undo_count,redo:S.history.redo_count}:null,
      art:{state:S.art.state,revision:S.art.revision},loading:!!S.loading,fatal:S.fatal?S.fatal.code:null,
      pendingDrafts:[...sessions.values()].filter((s)=>s.dirty).map((s)=>s.id)});

    return Object.freeze({install,open,close,toggle,destroy,view,stats:()=>Object.assign({},stats),refresh:()=>loadPresentations(),
      checkAvailability,pollReloads,selectScene:chooseScene,selectTab,runHistory,loadScene,
      widget:(id)=>widgets.get(id)||null,element:()=>ui.root,dockButton:()=>ui.dock,previewHost:()=>previewHost});
  }

  const api={ROUTE,GROUPS,GROUP_LABEL,PANEL_ID,BUTTON_ID,STYLE_ID,STORAGE_KEY,PREVIEW_MIN_MS,TEXT_PREVIEW_MS,IDLE_COMMIT_MS,RELOAD_RETRY_MS,POLL_MS,
    APPLIED_THEME,NOT_APPLIED_THEME,CSS,InspectorError,createStudioInspector,widgetSpec,stepFor,validateValue,setAtPath,previewValues,
    diffControls,contrastRatio,describeRefusal,formatValue,roundTo,sameJson,canonical,instance:null};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(root.document&&typeof root.fetch==='function'&&root.document.getElementById){
    try{
      api.instance=createStudioInspector({});
      api.instance.install();
    }catch(error){
      if(root.console)root.console.error('[studio-inspector] not_installed '+JSON.stringify({error:describe(error)}));
    }
  }
  root.JarvisStudioInspector=api;
})(typeof globalThis!=='undefined'?globalThis:this);
