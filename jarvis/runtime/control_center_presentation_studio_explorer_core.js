/* Explorateur de variantes du Studio : fonctions pures, messages et CSS (handoff jarvis-interactive-presentation-studio, Slice 18).

   Ce fichier ne touche ni le DOM ni le réseau : il décrit l'arbre (modèle, lignes visibles, navigation clavier ARIA), le temps
   relatif, les refus de Core dits en français, le modèle de la boîte d'archivage et la feuille de style. Le contrôleur
   (`control_center_presentation_studio_explorer.js`) l'assemble. Les deux fichiers ont les mêmes marqueurs de page ; celui-ci passe
   en premier et publie `window.JarvisStudioExplorerCore` (et `module.exports` pour node).

   Règles tenues ici, parce que tout le reste en dépend :

   - **Tout texte d'auteur est non fiable** (titres, raisons : un modèle ou l'utilisateur les a écrits). `cleanLine` retire les
     caractères de contrôle (NUL compris), les marques de direction bidirectionnelle (« Trojan source ») et borne la longueur par
     POINTS DE CODE (jamais au milieu d'un emoji) ; le contrôleur ne l'écrit que par `textContent` et pose `dir="auto"`.
   - **L'arbre est une vue du graphe de Core, pas sa source.** Un parent absent ou un cycle (un graphe que Core refuserait de
     charger, mais qu'un double ou une version future pourrait servir) ne plantent pas : le nœud devient racine, marqué.
   - **Les numéros d'affichage sont ceux de Core**, immuables : on ne les recalcule jamais. */
(function(root){
  'use strict';

  const ROUTE='/api/presentation-studio/presentations';
  const PLAYBACK_ROUTE='/api/presentation-studio/playback';
  const COMMAND_ROUTE='/api/presentation-studio/explorer/commands';
  const STATE_ROUTE='/api/presentation-studio/explorer/state';
  const HOST_ID='jvStudioExplorer';
  const OBJECT_ID='studio-explorer';
  const PREVIEW_OBJECT_ID='studio-explorer-preview';
  const STYLE_ID='jv-studio-explorer-style';
  const STORAGE_KEY='jarvis.studio_explorer.ui';
  const ROW_H=48;
  const OVERSCAN=6;
  const MAX_LIVE=64;
  const MAX_ARCHIVED=128;
  const MAX_TITLE=80;
  const MAX_RATIONALE=600;
  const MAX_RATIONALE_BYTES=800;
  const MAX_DEPTH_SHOWN=10;          /* au-delà, l'indentation s'arrête et un repère de profondeur la remplace */
  const INDENT_PX=14;
  const REQUEST_TIMEOUT_MS=15000;
  const READ_TIMEOUT_MS=10000;
  const PLAYBACK_CHECK_MS=2000;
  const LONG_PRESS_MS=550;
  const PREVIEW_SETTLE_MS=120;
  const NOTICE_MS=9000;
  const PREFS_MAX_COLLAPSED=256;
  const STUDIO_STAGE_PREFIX='studio-stage-';

  /* ------------------------------------------------------------------ texte non fiable */
  const CONTROL_CHARS=/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/g;
  /* Marques de direction : un titre ne doit pas pouvoir réordonner le texte voisin (« Trojan source »). `dir="auto"` fait le reste. */
  const BIDI_CONTROLS=/[\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c]/g;
  function clip(text,max){
    const limit=Math.max(1,max|0);
    /* Borne d'abord en unités UTF-16 : un titre hostile de 10 millions de caractères ne doit pas coûter une copie de points de code. */
    const head=text.length>limit*2+2?text.slice(0,limit*2+2):text;
    const points=Array.from(head);
    if(points.length<=limit&&head.length===text.length)return text;
    return points.slice(0,Math.max(1,limit-1)).join('')+'…';
  }
  function cleanLine(value,max){
    let text=typeof value==='string'?value:(value===null||value===undefined?'':String(value));
    if(text.length>(max||200)*4+16)text=text.slice(0,(max||200)*4+16);
    text=text.replace(CONTROL_CHARS,' ').replace(BIDI_CONTROLS,'').replace(/\s+/g,' ').trim();
    return clip(text,max||200);
  }
  function utf8Length(text){
    let n=0;
    for(const ch of text){const c=ch.codePointAt(0);n+=c<0x80?1:c<0x800?2:c<0x10000?3:4}
    return n;
  }
  /* Même règle que Core pour la raison d'une branche : <= 600 caractères ET <= 800 octets en JSON (guillemets et antislashs comptés 2). */
  function rationaleBytes(text){return utf8Length(JSON.stringify(text).slice(1,-1))}
  function checkTitle(value){
    const text=cleanLine(value,MAX_TITLE+1);
    if(!text)return {ok:false,message:'Donnez un titre à la variante.'};
    if(Array.from(text).length>MAX_TITLE)return {ok:false,message:`Le titre dépasse ${MAX_TITLE} caractères.`};
    return {ok:true,value:text};
  }
  function checkRationale(value){
    const text=cleanLine(value,MAX_RATIONALE+1);
    if(Array.from(text).length>MAX_RATIONALE)return {ok:false,message:`La raison dépasse ${MAX_RATIONALE} caractères.`};
    if(rationaleBytes(text)>MAX_RATIONALE_BYTES)return {ok:false,message:`La raison est trop longue (${MAX_RATIONALE_BYTES} octets au plus, accents et émojis comptent plus qu'un caractère).`};
    return {ok:true,value:text};
  }

  /* ------------------------------------------------------------------ temps relatif (français) */
  function pad2(n){return n<10?'0'+n:String(n)}
  function absoluteTime(iso){
    const t=Date.parse(iso);
    if(!Number.isFinite(t))return '';
    const d=new Date(t);
    return `${pad2(d.getDate())}/${pad2(d.getMonth()+1)}/${d.getFullYear()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  }
  const MONTHS=['janv.','févr.','mars','avr.','mai','juin','juil.','août','sept.','oct.','nov.','déc.'];
  function relativeTime(iso,nowMs){
    const t=Date.parse(iso);
    if(!Number.isFinite(t))return '';
    const now=Number.isFinite(nowMs)?nowMs:Date.now();
    const diff=now-t;
    if(diff<-60000)return absoluteTime(iso);          /* horloge qui diverge : dire la date plutôt qu'un futur absurde */
    const s=Math.max(0,diff)/1000;
    if(s<45)return "à l'instant";
    if(s<5400)return `il y a ${Math.max(1,Math.round(s/60))} min`;
    const nowDate=new Date(now),date=new Date(t);
    const startOf=d=>new Date(d.getFullYear(),d.getMonth(),d.getDate()).getTime();
    const days=Math.round((startOf(nowDate)-startOf(date))/86400000);
    if(days===0)return `il y a ${Math.max(1,Math.round(s/3600))} h`;
    if(days===1)return 'hier';
    if(days<7)return `il y a ${days} j`;
    return `${date.getDate()} ${MONTHS[date.getMonth()]}`+(date.getFullYear()!==nowDate.getFullYear()?` ${date.getFullYear()}`:'');
  }
  function creatorLabel(value){
    return value==='brain'?'Jarvis':value==='user'?'vous':value==='system'?'système':'';
  }
  function shortId(id){return typeof id==='string'?id.replace(/^psv_/,'').slice(0,6):''}

  /* ------------------------------------------------------------------ l'arbre */
  /* `nodes` : les nœuds du graphe de Core (`variant_id`, `variant_number`, `parent_variant_id`, `state`...). Le sous-ensemble
     `state` est mis en forêt ; un parent hors du sous-ensemble (une racine archivée dont le parent est vivant) fait une racine
     marquée `outside`. Pas de récursion : 64 niveaux ou 10 000, la pile ne grandit pas. */
  function buildForest(nodes,state){
    const byId=new Map();
    for(const node of Array.isArray(nodes)?nodes:[]){
      if(!node||typeof node.variant_id!=='string'||node.state!==state||byId.has(node.variant_id))continue;
      byId.set(node.variant_id,node);
    }
    const byNumber=(a,b)=>(Number(a.variant_number)||0)-(Number(b.variant_number)||0)||(a.variant_id<b.variant_id?-1:1);
    const kids=new Map();
    const roots=[];
    const outside=new Set();
    for(const node of Array.from(byId.values()).sort(byNumber)){
      const parent=node.parent_variant_id;
      if(typeof parent==='string'&&parent!==node.variant_id&&byId.has(parent)){
        if(!kids.has(parent))kids.set(parent,[]);
        kids.get(parent).push(node.variant_id);
      }else{
        roots.push(node.variant_id);
        if(typeof parent==='string'&&parent!==node.variant_id)outside.add(node.variant_id);
      }
    }
    const depth=new Map();
    const parentOf=new Map();
    const descendants=new Map();
    const reached=new Set();
    const order=[];
    const walk=starts=>{
      const stack=[];
      for(let i=starts.length-1;i>=0;i--)stack.push([starts[i],0,null]);
      while(stack.length){
        const [id,d,parent]=stack.pop();
        if(reached.has(id))continue;
        reached.add(id);depth.set(id,d);parentOf.set(id,parent);order.push(id);
        const list=kids.get(id)||[];
        for(let i=list.length-1;i>=0;i--)stack.push([list[i],d+1,id]);
      }
    };
    walk(roots);
    /* Un cycle (A -> B -> A) n'est joignable d'aucune racine : ses nœuds deviennent des racines marquées, jamais perdus. */
    const cyclic=new Set();
    for(const node of Array.from(byId.values()).sort(byNumber)){
      if(!reached.has(node.variant_id)){roots.push(node.variant_id);cyclic.add(node.variant_id);walk([node.variant_id])}
    }
    for(let i=order.length-1;i>=0;i--){
      const id=order[i];
      let count=0;
      for(const child of kids.get(id)||[])if(parentOf.get(child)===id)count+=1+(descendants.get(child)||0);
      descendants.set(id,count);
    }
    for(const [parent,list] of kids)kids.set(parent,list.filter(child=>parentOf.get(child)===parent));
    return {byId,roots,kids,depth,parentOf,descendants,order,outside,cyclic,size:byId.size};
  }
  function childrenOf(forest,id){return forest.kids.get(id)||[]}
  function ancestorsOf(forest,id){
    const out=[];
    for(let cur=forest.parentOf.get(id),guard=0;cur&&guard<10000;cur=forest.parentOf.get(cur),guard++)out.push(cur);
    return out;
  }
  function subtreeIds(forest,id){
    const out=[],stack=[id];
    while(stack.length){const cur=stack.pop();out.push(cur);for(const child of childrenOf(forest,cur))stack.push(child)}
    return out;
  }
  /* Lignes visibles : un nœud dont un ancêtre est replié n'y est pas. `collapsed` : ensemble d'ids repliés. */
  function flatten(forest,collapsed){
    const rows=[];
    const folded=collapsed instanceof Set?collapsed:new Set(collapsed||[]);
    const stack=[];
    const setSizeOf=id=>{const parent=forest.parentOf.get(id);return parent?childrenOf(forest,parent).length:forest.roots.length};
    const position=new Map();
    for(const list of [forest.roots,...Array.from(forest.kids.values())])list.forEach((id,index)=>position.set(id,index+1));
    for(let i=forest.roots.length-1;i>=0;i--)stack.push([forest.roots[i],[]]);
    while(stack.length){
      const [id,trail]=stack.pop();
      const kidsHere=childrenOf(forest,id);
      const expanded=kidsHere.length>0&&!folded.has(id);
      const depth=forest.depth.get(id)||0;
      const setSize=setSizeOf(id),posInSet=position.get(id)||1;
      /* `trail[c]` : la ligne de la colonne c traverse cette ligne (l'ancêtre de profondeur c+1 a encore un frère à venir). `last` : dernier de sa fratrie
         (son coude ferme la ligne). Le contrôleur n'en fait que du dessin : rien ici ne dépend du rendu. */
      rows.push({id,node:forest.byId.get(id),depth,hasChildren:kidsHere.length>0,expanded,
        setSize,posInSet,last:posInSet>=setSize,trail,parentId:forest.parentOf.get(id)||null,
        descendants:forest.descendants.get(id)||0,outside:forest.outside.has(id),cyclic:forest.cyclic.has(id)});
      if(expanded){
        const childTrail=depth>=1?trail.concat(!(posInSet>=setSize)):[];
        for(let i=kidsHere.length-1;i>=0;i--)stack.push([kidsHere[i],childTrail]);
      }
    }
    return rows;
  }
  /* Fenêtre de rendu : les lignes à dessiner pour un défilement donné (virtualisation à hauteur fixe). */
  function windowOf(total,scrollTop,viewport,rowHeight,overscan){
    const h=rowHeight||ROW_H,extra=overscan===undefined?OVERSCAN:overscan;
    if(total<=0)return {start:0,end:0};
    const first=Math.floor(Math.max(0,scrollTop)/h);
    const visible=Math.ceil(Math.max(h,viewport)/h);
    return {start:Math.max(0,first-extra),end:Math.min(total,first+visible+extra)};
  }

  /* Navigation clavier d'un arbre ARIA (WAI-ARIA Authoring Practices, « Tree View »). Pure : rend l'action, le contrôleur l'exécute.
     `rows` : lignes visibles ; `index` : ligne focalisée. Actions : {type:'focus',id} {type:'expand',id} {type:'collapse',id}
     {type:'select',id} {type:'rename'|'archive'|'branch'|'activate'|'menu',id} ou null (touche non gérée : on ne la prend pas). */
  const PAGE_STEP=10;
  function treeKey(rows,index,key,mods){
    if(!rows.length||index<0||index>=rows.length)return null;
    const m=mods||{};
    if(m.ctrl||m.meta||m.alt)return null;
    const row=rows[index];
    const focus=i=>({type:'focus',id:rows[Math.max(0,Math.min(rows.length-1,i))].id});
    switch(key){
      case 'ArrowDown':return focus(index+1);
      case 'ArrowUp':return focus(index-1);
      case 'Home':return focus(0);
      case 'End':return focus(rows.length-1);
      case 'PageDown':return focus(index+PAGE_STEP);
      case 'PageUp':return focus(index-PAGE_STEP);
      case 'ArrowRight':
        if(row.hasChildren&&!row.expanded)return {type:'expand',id:row.id};
        if(row.hasChildren&&row.expanded&&rows[index+1])return {type:'focus',id:rows[index+1].id};
        return null;
      case 'ArrowLeft':
        if(row.hasChildren&&row.expanded)return {type:'collapse',id:row.id};
        if(row.parentId&&rows.some(r=>r.id===row.parentId))return {type:'focus',id:row.parentId};
        return null;
      case 'Enter':case ' ':return {type:'select',id:row.id};
      case 'F2':return {type:'rename',id:row.id};
      case 'Delete':return {type:'archive',id:row.id};
      case 'ContextMenu':return {type:'menu',id:row.id};
      case 'F10':return m.shift?{type:'menu',id:row.id}:null;
      case 'n':case 'N':return {type:'branch',id:row.id};
      case 'a':case 'A':return {type:'activate',id:row.id};
      case 'r':case 'R':return {type:'restore',id:row.id};
      case '*':return {type:'expand_siblings',id:row.id};
      default:return null;
    }
  }

  /* ------------------------------------------------------------------ messages (français) */
  /* Chaque refus de Core a une phrase qui dit la cause ET la suite. `kind` : `stale` (relire puis refaire), `refused`, `failed`. */
  const REFUSALS=Object.freeze({
    presentation_studio_stale_revision:{kind:'stale',text:"Le graphe a changé depuis votre dernière lecture (une autre action, ou la voix, est passée avant vous). Il vient d'être relu : vérifiez, puis refaites l'action si elle a encore un sens."},
    presentation_studio_confirmation_stale:{kind:'stale',text:"Ce qui serait archivé a changé depuis le calcul de la liste (l'ensemble, un titre, la révision ou la nouvelle variante active). Rien n'a été archivé : relisez la nouvelle liste ci-dessous avant de confirmer."},
    presentation_studio_confirmation_required:{kind:'refused',text:"L'archivage exige la confirmation d'un plan : recalculez la liste, puis confirmez."},
    presentation_studio_variant_in_playback:{kind:'refused',text:"Cette variante, ou une de ses sous-branches, est en cours de lecture : arrêtez la lecture avant de l'archiver. Rien n'a été déplacé."},
    presentation_studio_active_variant_protected:{kind:'refused',text:"La variante active ne s'archive pas telle quelle : choisissez la variante qui deviendra active. Une présentation garde toujours au moins une variante vivante."},
    presentation_studio_not_archived:{kind:'refused',text:"Cette variante n'est pas archivée : il n'y a rien à restaurer."},
    presentation_studio_unknown_variant:{kind:'stale',text:"Cette variante n'existe plus (ou elle est archivée). La liste vient d'être relue."},
    presentation_studio_unknown_presentation:{kind:'refused',text:"Cette présentation n'existe pas (ou plus)."},
    presentation_studio_linked_document_unsupported:{kind:'refused',text:"Cette variante cite un document lié que le branchement ne sait pas copier : rien n'a été créé."},
    presentation_studio_scene_reloading:{kind:'refused',text:"Une scène de la variante est en cours de rechargement à chaud : réessayez dans un instant."},
    presentation_studio_already_exists:{kind:'refused',text:"Cela existe déjà."},
    presentation_studio_corrupt_document:{kind:'failed',text:"Un document de la présentation est illisible ou incohérent : Core refuse d'y toucher. Le détail est dans le journal des erreurs."},
    presentation_studio_unsupported_schema_version:{kind:'failed',text:"Un document de la présentation vient d'une version plus récente de JARVIS : Core refuse d'y toucher."},
    presentation_studio_storage_io:{kind:'failed',text:"Core n'a pas pu lire ou écrire les fichiers de la présentation. Rien n'a été modifié."},
    presentation_studio_invalid:{kind:'refused',text:"Core a refusé cette valeur."},
  });
  function limitText(op){
    if(op==='restore')return `Impossible de restaurer : ${MAX_LIVE} variantes vivantes au plus. Archivez des branches abandonnées d'abord.`;
    if(op==='plan'||op==='archive')return `L'archive est pleine (${MAX_ARCHIVED} variantes au plus) : ces branches ne peuvent pas y entrer. Restaurez ou laissez de côté des branches archivées d'abord ; Core ne supprime jamais rien tout seul.`;
    return `Impossible de créer la branche : ${MAX_LIVE} variantes vivantes au plus. Archivez des branches abandonnées d'abord.`;
  }
  /* `error` : {status, code, message} d'une réponse de Core ou {code:'timeout'|'network'|...}. `ctx.op` précise `limit_reached`. */
  function describeRefusal(error,ctx){
    const e=error||{};
    const code=typeof e.code==='string'?e.code:'';
    if(code==='presentation_studio_limit_reached')return {kind:'refused',text:limitText(ctx&&ctx.op),code};
    if(REFUSALS[code])return Object.assign({code},REFUSALS[code]);
    if(code==='timeout')return {kind:'failed',code,text:`Core ne répond pas depuis ${Math.round((e.after||REQUEST_TIMEOUT_MS)/1000)} s : l'action a peut-être été prise en compte. Relisez la liste avant de recommencer.`};
    if(code==='network'||e.status===503||e.status===504||e.status===502)return {kind:'failed',code:code||'unreachable',text:`Core est injoignable (${cleanLine(e.message||'réseau',100)}). Rien n'est affirmé : réessayez dans un instant.`};
    if(e.status===403||code==='forbidden_origin')return {kind:'failed',code:code||'forbidden',text:"Le Control Center a refusé cette requête (origine non autorisée)."};
    const detail=cleanLine(e.message||'',200);
    return {kind:e.status>=500?'failed':'refused',code:code||`http_${e.status||'?'}`,
      text:`Core a refusé : ${code||('HTTP '+(e.status||'?'))}${detail?' — '+detail:''}.`};
  }
  const COMMAND_REFUSALS=Object.freeze({
    explorer_run_in_progress:"Une lecture est en cours : l'explorateur est un outil d'édition, il ne s'ouvre pas pendant une présentation. Arrêtez la lecture d'abord.",
    explorer_unknown_presentation:"Cette présentation n'existe pas.",
    explorer_unavailable:"L'explorateur de variantes n'est pas disponible dans cette page.",
    explorer_load_failed:"Core n'a pas pu rendre le graphe des variantes.",
    explorer_page_error:"L'explorateur a rencontré une erreur inattendue.",
  });

  /* ------------------------------------------------------------------ boîte d'archivage */
  /* La réponse de `archive-plan` rendue en modèle d'écran. Les titres viennent de Core (texte d'utilisateur : `cleanLine` ici, `textContent` ensuite). */
  function planModel(answer,forest){
    const plan=answer&&answer.plan||{};
    const live=forest?Array.from(forest.byId.values()):[];
    const inside=new Set((plan.affected||[]).map(row=>row.variant_id));
    const rows=(plan.affected||[]).map(row=>({id:row.variant_id,number:row.variant_number,title:cleanLine(row.title,MAX_TITLE),short:shortId(row.variant_id)}));
    const choices=live.filter(node=>!inside.has(node.variant_id)).sort((a,b)=>(a.variant_number||0)-(b.variant_number||0))
      .map(node=>({id:node.variant_id,number:node.variant_number,title:cleanLine(node.title,MAX_TITLE)}));
    return {rows,count:plan.count||rows.length,root:plan.root_variant_id||null,includesActive:!!plan.includes_active,
      requiresNewActive:!!plan.requires_new_active,suggestedActive:plan.suggested_active||null,activateId:plan.activate_variant_id||null,
      blocked:plan.blocked||null,blockedReason:blockedText(plan.blocked),
      token:typeof answer.confirmation==='string'?answer.confirmation:null,
      expiresInS:Number.isFinite(answer.expires_in_s)?answer.expires_in_s:null,revision:plan.revision,choices};
  }
  function blockedText(code){
    if(!code)return '';
    if(code==='presentation_studio_active_variant_protected')return "Cette liste contient la variante active : choisissez celle qui la remplace. Si rien ne reste en dehors de la liste, l'archivage est impossible (une présentation garde au moins une variante vivante).";
    return REFUSALS[code]?REFUSALS[code].text:`Archivage impossible (${cleanLine(code,80)}).`;
  }
  function sameSet(a,b){
    if(a.length!==b.length)return false;
    const ids=new Set(a.map(r=>r.id+'|'+r.number+'|'+r.title));
    return b.every(r=>ids.has(r.id+'|'+r.number+'|'+r.title));
  }

  /* ------------------------------------------------------------------ préférences d'affichage (jamais l'état d'une présentation) */
  function readPrefs(store){
    try{
      const raw=store&&store.getItem(STORAGE_KEY);
      const parsed=raw?JSON.parse(raw):null;
      if(!parsed||typeof parsed!=='object')return {collapsed:{},last:{},archivedOpen:false};
      return {collapsed:parsed.collapsed&&typeof parsed.collapsed==='object'?parsed.collapsed:{},
        last:parsed.last&&typeof parsed.last==='object'?parsed.last:{},archivedOpen:parsed.archivedOpen===true};
    }catch(_error){return {collapsed:{},last:{},archivedOpen:false} /* intentional: unreadable preferences = defaults */}
  }
  function writePrefs(store,prefs){
    try{
      if(!store)return;
      const slim={collapsed:{},last:{},archivedOpen:prefs.archivedOpen===true};
      for(const key of Object.keys(prefs.collapsed).slice(-16))slim.collapsed[key]=(prefs.collapsed[key]||[]).slice(0,PREFS_MAX_COLLAPSED);
      for(const key of Object.keys(prefs.last).slice(-16))slim.last[key]=prefs.last[key];
      store.setItem(STORAGE_KEY,JSON.stringify(slim));
    }catch(_error){/* intentional: a preference that cannot be stored is only forgotten */}
  }

  /* ------------------------------------------------------------------ icônes (dessinées, un seul trait) */
  const ICONS=Object.freeze({
    close:['M6 6l12 12','M18 6L6 18'],
    expand:['M4 9V4h5','M20 9V4h-5','M4 15v5h5','M20 15v5h-5'],
    contract:['M9 4v5H4','M15 4v5h5','M9 20v-5H4','M15 20v-5h5'],
    fork:['M7 4v9','M17 4v3a3 3 0 0 1-3 3H10a3 3 0 0 0-3 3','M7 20v-3'],
    pencil:['M4 20l1-4L16 5l3 3L8 19z','M14 7l3 3'],
    box:['M4 7h16v4H4z','M6 11v8h12v-8','M10 15h4'],
    restore:['M5 12a7 7 0 1 1 2 5','M5 18v-5h5'],
    power:['M12 4v8','M7 7a7 7 0 1 0 10 0'],
    chevron:['M9 6l6 6-6 6'],
    prev:['M15 6l-6 6 6 6'],
    next:['M9 6l6 6-6 6'],
    alert:['M12 5l8 14H4z','M12 10v4','M12 17v.01'],
  });

  /* ------------------------------------------------------------------ feuille de style */
  /* Un seul parti pris : l'explorateur est un atelier sombre dont la lueur prend la palette de la variante regardée. Le flou est celui
     de la page derrière lui (fenêtré) ; en plein écran il n'y a plus de page derrière, la lueur le remplace. Aucun mouvement hors
     « mouvement réduit non demandé » ; aucun flou animé. */
  const CSS=`
@property --jvx-glow-a{syntax:'<color>';inherits:true;initial-value:#6ee7ff}
@property --jvx-glow-b{syntax:'<color>';inherits:true;initial-value:#a78bfa}
#${HOST_ID}{--jvx-bg:#04080c;--jvx-ink:#e6f2f8;--jvx-mute:#95aebb;--jvx-line:rgba(130,200,226,.16);--jvx-line-strong:rgba(130,200,226,.34);
  --jvx-accent:#6ee7ff;--jvx-warn:#ffb85c;--jvx-danger:#ff7a8a;--jvx-ok:#68e0a0;--jvx-surface:rgba(9,18,26,.62);--jvx-surface-2:rgba(14,27,38,.78);
  --jvx-glow-a:#6ee7ff;--jvx-glow-b:#a78bfa;
  position:fixed;inset:0;z-index:9000;box-sizing:border-box;display:grid;grid-template-rows:auto minmax(0,1fr);
  color:var(--jvx-ink);font:14px/1.45 system-ui,"Segoe UI",sans-serif;overflow:hidden;isolation:isolate;
  background:
    radial-gradient(70% 55% at 88% 6%,color-mix(in srgb,var(--jvx-glow-a) 24%,transparent),transparent 72%),
    radial-gradient(60% 60% at 4% 100%,color-mix(in srgb,var(--jvx-glow-b) 18%,transparent),transparent 74%),
    rgba(3,7,11,.80);
  -webkit-backdrop-filter:blur(26px) saturate(.75);backdrop-filter:blur(26px) saturate(.75)}
#${HOST_ID}[hidden],#${HOST_ID} [hidden]{display:none!important}
#${HOST_ID}:fullscreen{background:
    radial-gradient(70% 55% at 88% 6%,color-mix(in srgb,var(--jvx-glow-a) 26%,transparent),transparent 72%),
    radial-gradient(60% 60% at 4% 100%,color-mix(in srgb,var(--jvx-glow-b) 20%,transparent),transparent 74%),var(--jvx-bg)}
@media (prefers-reduced-transparency:reduce){#${HOST_ID}{-webkit-backdrop-filter:none;backdrop-filter:none;background:var(--jvx-bg)}}
@media (prefers-reduced-motion:no-preference){#${HOST_ID}{transition:--jvx-glow-a .7s ease,--jvx-glow-b .7s ease}}
#${HOST_ID} *{box-sizing:border-box}
#${HOST_ID} button{font:inherit;color:inherit;cursor:pointer}
#${HOST_ID} button:disabled,#${HOST_ID} button[aria-disabled="true"]{opacity:.5;cursor:default}
#${HOST_ID} :focus-visible{outline:2px solid var(--jvx-accent);outline-offset:2px}
#${HOST_ID} svg{width:1.15em;height:1.15em;flex:none;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
#${HOST_ID} .jvx-bidi{unicode-bidi:plaintext}
#${HOST_ID} .jvx-top{grid-row:1;display:flex;align-items:center;gap:14px;padding:12px 20px;border-bottom:1px solid var(--jvx-line);min-width:0}
#${HOST_ID} .jvx-heading{display:flex;flex-direction:column;min-width:0;flex:1 1 auto}
#${HOST_ID} .jvx-title{margin:0;font-size:17px;font-weight:650;letter-spacing:.01em;line-height:1.2}
#${HOST_ID} .jvx-subtitle{margin:2px 0 0;color:var(--jvx-mute);font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${HOST_ID} .jvx-top-actions{display:flex;gap:8px;align-items:center;flex:none}
#${HOST_ID} .jvx-chip{display:inline-flex;align-items:center;gap:6px;min-height:26px;padding:2px 10px;border-radius:999px;border:1px solid var(--jvx-line);
  background:var(--jvx-surface);font-size:12px;color:var(--jvx-mute);white-space:nowrap}
#${HOST_ID} .jvx-chip[data-tone="ok"]{color:var(--jvx-ok);border-color:color-mix(in srgb,var(--jvx-ok) 40%,transparent)}
#${HOST_ID} .jvx-chip[data-tone="warn"]{color:var(--jvx-warn);border-color:color-mix(in srgb,var(--jvx-warn) 45%,transparent)}
#${HOST_ID} .jvx-chip[data-tone="accent"]{color:var(--jvx-accent);border-color:color-mix(in srgb,var(--jvx-accent) 45%,transparent)}
#${HOST_ID} .jvx-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:36px;padding:0 14px;border-radius:9px;border:1px solid var(--jvx-line-strong);
  background:rgba(255,255,255,.035)}
#${HOST_ID} .jvx-btn:hover:not(:disabled):not([aria-disabled="true"]){border-color:var(--jvx-accent);background:color-mix(in srgb,var(--jvx-accent) 10%,transparent)}
#${HOST_ID} .jvx-btn[data-primary]{background:var(--jvx-accent);color:#031218;border-color:transparent;font-weight:650}
#${HOST_ID} .jvx-btn[data-primary]:hover:not(:disabled){background:color-mix(in srgb,var(--jvx-accent) 86%,#fff)}
#${HOST_ID} .jvx-btn[data-danger]{color:var(--jvx-danger);border-color:color-mix(in srgb,var(--jvx-danger) 50%,transparent)}
#${HOST_ID} .jvx-btn[data-danger][data-primary]{background:var(--jvx-danger);color:#1a0509}
#${HOST_ID} .jvx-btn-icon{width:36px;padding:0}
/* Le message d'état flotte (il ne décale jamais la mise en page) ; un échec reste jusqu'à ce qu'on le masque. */
#${HOST_ID} .jvx-notice{position:absolute;z-index:4;top:76px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:10px;
  width:max-content;max-width:min(780px,calc(100% - 32px));min-height:38px;padding:6px 8px 6px 16px;border-radius:12px;font-size:13px;
  border:1px solid var(--jvx-line-strong);color:var(--jvx-ink);background:var(--jvx-surface-2);-webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px);
  box-shadow:0 14px 40px rgba(0,0,0,.5)}
#${HOST_ID} .jvx-notice[data-kind="ok"]{border-color:color-mix(in srgb,var(--jvx-ok) 55%,transparent)}
#${HOST_ID} .jvx-notice[data-kind="ok"] .jvx-notice-text{color:var(--jvx-ok)}
#${HOST_ID} .jvx-notice[data-kind="stale"],#${HOST_ID} .jvx-notice[data-kind="refused"]{border-color:color-mix(in srgb,var(--jvx-warn) 55%,transparent)}
#${HOST_ID} .jvx-notice[data-kind="stale"] .jvx-notice-text,#${HOST_ID} .jvx-notice[data-kind="refused"] .jvx-notice-text{color:var(--jvx-warn)}
#${HOST_ID} .jvx-notice[data-kind="failed"]{border-color:color-mix(in srgb,var(--jvx-danger) 60%,transparent)}
#${HOST_ID} .jvx-notice[data-kind="failed"] .jvx-notice-text{color:var(--jvx-danger)}
#${HOST_ID} .jvx-notice-text{flex:1 1 auto;min-width:0;overflow-wrap:anywhere}
#${HOST_ID} .jvx-notice .jvx-btn{min-height:28px;padding:0 10px;font-size:12px}
#${HOST_ID} .jvx-notice .jvx-btn-icon{width:28px;padding:0}
#${HOST_ID} .jvx-body{grid-row:2;display:grid;grid-template-columns:clamp(280px,29vw,420px) minmax(0,1fr);min-height:0}
#${HOST_ID} .jvx-treepane{display:flex;flex-direction:column;min-height:0;min-width:0;border-right:1px solid var(--jvx-line);background:rgba(0,0,0,.14)}
#${HOST_ID} .jvx-panehead{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 16px 8px}
#${HOST_ID} .jvx-panetitle{margin:0;font-size:12px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:var(--jvx-mute)}
#${HOST_ID} .jvx-tree{position:relative;flex:1 1 auto;min-height:0;overflow:auto;outline-offset:-2px;scrollbar-width:thin;scrollbar-color:var(--jvx-line-strong) transparent}
#${HOST_ID} .jvx-spacer{position:relative;width:100%}
#${HOST_ID} .jvx-row{position:absolute;left:0;right:0;height:${ROW_H}px;display:flex;align-items:center;gap:6px;padding:0 12px 0 8px;cursor:pointer;user-select:none}
#${HOST_ID} .jvx-row:hover{background:rgba(255,255,255,.04)}
#${HOST_ID} .jvx-row[aria-selected="true"]{background:color-mix(in srgb,var(--jvx-accent) 13%,transparent);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--jvx-accent) 38%,transparent)}
#${HOST_ID} .jvx-row:focus-visible{outline-offset:-2px}
#${HOST_ID} .jvx-rail{flex:none;height:100%;background-repeat:no-repeat}
#${HOST_ID} .jvx-depth{flex:none;font:600 10px/1 ui-monospace,Consolas,monospace;color:var(--jvx-mute);border:1px solid var(--jvx-line);border-radius:5px;padding:2px 4px}
#${HOST_ID} .jvx-twist{flex:none;display:grid;place-items:center;width:24px;height:24px;padding:0;border:0;background:transparent;border-radius:6px;color:var(--jvx-mute)}
#${HOST_ID} .jvx-twist:hover{color:var(--jvx-ink);background:rgba(255,255,255,.07)}
#${HOST_ID} .jvx-twist svg{width:14px;height:14px}
#${HOST_ID} .jvx-twist[aria-expanded="true"] svg{transform:rotate(90deg)}
#${HOST_ID} .jvx-twist-gap{flex:none;width:24px}
#${HOST_ID} .jvx-num{flex:none;font:700 12.5px/1 ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums;min-width:3.1em;text-align:center;padding:4px 6px;
  border-radius:7px;background:rgba(255,255,255,.06);border:1px solid var(--jvx-line);color:var(--jvx-ink)}
#${HOST_ID} .jvx-row[data-active="true"] .jvx-num{background:var(--jvx-accent);color:#031218;border-color:transparent}
#${HOST_ID} .jvx-rowtext{display:flex;flex-direction:column;min-width:0;flex:1 1 auto}
#${HOST_ID} .jvx-rowtitle{font-weight:560;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${HOST_ID} .jvx-rowmeta{color:var(--jvx-mute);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${HOST_ID} .jvx-flag{flex:none;font-size:11px;font-weight:650;letter-spacing:.04em;text-transform:uppercase;padding:2px 7px;border-radius:999px;border:1px solid currentColor}
#${HOST_ID} .jvx-flag[data-flag="active"]{color:var(--jvx-accent)}
#${HOST_ID} .jvx-flag[data-flag="playing"]{color:var(--jvx-warn)}
#${HOST_ID} .jvx-flag[data-flag="issue"]{color:var(--jvx-danger)}
#${HOST_ID} .jvx-hint-keys{margin:0;padding:6px 16px 8px;font-size:11.5px;line-height:1.4;color:var(--jvx-mute)}
#${HOST_ID} .jvx-archive{border-top:1px solid var(--jvx-line);display:flex;flex-direction:column;min-height:0;max-height:42%}
#${HOST_ID} .jvx-archive[data-open="false"]{flex:none}
#${HOST_ID} .jvx-archive-toggle{display:flex;align-items:center;gap:8px;width:100%;min-height:42px;padding:0 16px;border:0;background:transparent;text-align:left;color:var(--jvx-mute)}
#${HOST_ID} .jvx-archive-toggle:hover{color:var(--jvx-ink)}
#${HOST_ID} .jvx-archive-toggle svg{width:14px;height:14px}
#${HOST_ID} .jvx-archive-toggle[aria-expanded="true"] svg{transform:rotate(90deg)}
#${HOST_ID} .jvx-archive .jvx-tree{flex:1 1 auto;min-height:96px}
#${HOST_ID} .jvx-archive[data-open="false"] .jvx-tree{display:none}
#${HOST_ID} .jvx-empty{padding:20px 16px;color:var(--jvx-mute)}
#${HOST_ID} .jvx-preview{display:flex;flex-direction:column;gap:12px;min-height:0;min-width:0;padding:16px 20px 16px;overflow:auto}
#${HOST_ID} .jvx-stagewrap{position:relative;flex:1 1 0;min-height:160px;display:grid;place-items:center;container-type:size}
#${HOST_ID} .jvx-stage{position:relative;width:min(100cqw,calc(100cqh * 16 / 9));aspect-ratio:16/9;border-radius:14px;overflow:hidden;background:#02060a;
  border:1px solid var(--jvx-line-strong);box-shadow:0 18px 50px rgba(0,0,0,.55),0 1px 0 rgba(255,255,255,.04) inset}
#${HOST_ID} .jvx-stage .sc-prefab-slot{position:absolute;inset:0;display:flex;flex-direction:column}
#${HOST_ID} .jvx-stage .sc-prefab-frame{flex:1 1 auto!important;height:100%!important;max-height:none!important;background:transparent}
#${HOST_ID} .jvx-stage-veil{position:absolute;inset:0;display:grid;place-content:center;gap:8px;padding:24px;text-align:center;color:var(--jvx-mute);
  background:rgba(2,6,10,.72);overflow-wrap:anywhere}
#${HOST_ID} .jvx-stage-veil[hidden]{display:none}
#${HOST_ID} .jvx-stage-veil strong{color:var(--jvx-ink);font-size:15px}
#${HOST_ID} .jvx-stage-veil[data-tone="warn"] strong{color:var(--jvx-warn)}
#${HOST_ID} .jvx-stage-veil[data-tone="danger"] strong{color:var(--jvx-danger)}
#${HOST_ID} .jvx-stage-note{display:flex;align-items:center;justify-content:space-between;gap:12px;color:var(--jvx-mute);font-size:13px;min-width:0}
#${HOST_ID} .jvx-scene-line{display:flex;align-items:center;gap:10px;min-width:0;flex:1 1 auto}
#${HOST_ID} .jvx-scene-title{color:var(--jvx-ink);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${HOST_ID} .jvx-strip{display:flex;gap:8px;overflow-x:auto;padding:2px 2px 6px;scrollbar-width:thin;scrollbar-color:var(--jvx-line-strong) transparent}
#${HOST_ID} .jvx-scene{flex:none;display:flex;flex-direction:column;gap:2px;width:150px;padding:8px 10px;text-align:left;border-radius:9px;border:1px solid var(--jvx-line);
  background:var(--jvx-surface)}
#${HOST_ID} .jvx-scene[aria-selected="true"]{border-color:var(--jvx-accent);background:color-mix(in srgb,var(--jvx-accent) 12%,transparent)}
#${HOST_ID} .jvx-scene-n{font:700 11px/1 ui-monospace,Consolas,monospace;color:var(--jvx-mute)}
#${HOST_ID} .jvx-scene-t{font-size:13px;font-weight:560;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--jvx-ink)}
#${HOST_ID} .jvx-scene-r{font-size:11.5px;color:var(--jvx-mute);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-height:1.4em}
#${HOST_ID} .jvx-scene-b{align-self:flex-start;font-size:11px;color:var(--jvx-accent);border:1px solid color-mix(in srgb,var(--jvx-accent) 40%,transparent);border-radius:999px;padding:0 7px}
#${HOST_ID} .jvx-bottom{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:start;padding-top:12px;border-top:1px solid var(--jvx-line)}
#${HOST_ID} .jvx-meta{display:flex;flex-direction:column;gap:6px;min-width:0}
#${HOST_ID} .jvx-meta-title{display:flex;align-items:baseline;gap:10px;min-width:0;margin:0;font-size:17px;font-weight:650}
#${HOST_ID} .jvx-meta-title .jvx-num{font-size:12px}
#${HOST_ID} .jvx-meta-title span.jvx-bidi{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${HOST_ID} .jvx-facts{display:flex;flex-wrap:wrap;gap:6px 14px;margin:0;color:var(--jvx-mute);font-size:13px}
#${HOST_ID} .jvx-facts dt{display:none}
#${HOST_ID} .jvx-facts dd{margin:0}
#${HOST_ID} .jvx-rationale{margin:0;max-height:3.9em;overflow:auto;color:var(--jvx-ink);font-size:13.5px;overflow-wrap:anywhere}
#${HOST_ID} .jvx-rationale:empty{display:none}
#${HOST_ID} .jvx-chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
#${HOST_ID} .jvx-swatches{display:inline-flex;gap:3px;margin-left:2px}
#${HOST_ID} .jvx-swatch{width:11px;height:11px;border-radius:3px;border:1px solid rgba(255,255,255,.28)}
#${HOST_ID} .jvx-actions{display:grid;grid-template-columns:repeat(2,minmax(0,auto));gap:8px;justify-content:end}
#${HOST_ID} .jvx-actions .jvx-btn{justify-content:flex-start}
#${HOST_ID} .jvx-layer{position:absolute;inset:0;z-index:5;pointer-events:none}
#${HOST_ID} .jvx-layer>*{pointer-events:auto}
#${HOST_ID} .jvx-scrim{position:absolute;inset:0;display:grid;place-items:center;padding:20px;background:rgba(2,5,8,.62)}
#${HOST_ID} .jvx-dialog{width:min(560px,100%);max-height:100%;overflow:auto;padding:20px;border-radius:14px;border:1px solid var(--jvx-line-strong);background:var(--jvx-surface-2);
  -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);box-shadow:0 24px 70px rgba(0,0,0,.6);display:grid;gap:14px}
#${HOST_ID} .jvx-dialog h2{margin:0;font-size:17px;font-weight:650}
#${HOST_ID} .jvx-dialog p{margin:0;color:var(--jvx-mute)}
#${HOST_ID} .jvx-dialog form{display:grid;gap:14px}
#${HOST_ID} .jvx-field{display:grid;gap:5px}
#${HOST_ID} .jvx-field label{font-size:13px;color:var(--jvx-mute)}
#${HOST_ID} .jvx-field input[type=text],#${HOST_ID} .jvx-field textarea{width:100%;min-height:38px;padding:8px 10px;border-radius:8px;border:1px solid var(--jvx-line-strong);
  background:rgba(0,0,0,.35);color:var(--jvx-ink);font:inherit}
#${HOST_ID} .jvx-field textarea{min-height:76px;resize:vertical}
#${HOST_ID} .jvx-field .jvx-hint{font-size:12px;color:var(--jvx-mute)}
#${HOST_ID} .jvx-field .jvx-error{font-size:12.5px;color:var(--jvx-danger)}
#${HOST_ID} .jvx-field .jvx-error:empty{display:none}
#${HOST_ID} .jvx-check{display:flex;align-items:center;gap:8px;color:var(--jvx-ink)}
#${HOST_ID} .jvx-check input{width:18px;height:18px;accent-color:var(--jvx-accent)}
#${HOST_ID} .jvx-dialog-actions{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}
#${HOST_ID} .jvx-set{margin:0;padding:0;list-style:none;display:grid;gap:4px;max-height:34vh;overflow:auto;border:1px solid var(--jvx-line);border-radius:10px;padding:6px}
#${HOST_ID} .jvx-set li{display:flex;align-items:center;gap:10px;padding:5px 8px;border-radius:7px;background:rgba(255,255,255,.03);min-width:0}
#${HOST_ID} .jvx-set li .jvx-rowtitle{flex:1 1 auto}
#${HOST_ID} .jvx-set .jvx-sid{font:11px/1 ui-monospace,Consolas,monospace;color:var(--jvx-mute)}
#${HOST_ID} .jvx-choice{display:grid;gap:6px;border:0;margin:0;padding:0}
#${HOST_ID} .jvx-choice legend{padding:0 0 4px;color:var(--jvx-warn);font-size:13px}
#${HOST_ID} .jvx-choice label{display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:7px;border:1px solid var(--jvx-line);color:var(--jvx-ink)}
#${HOST_ID} .jvx-choice input{accent-color:var(--jvx-accent)}
#${HOST_ID} .jvx-token{font-size:12.5px;color:var(--jvx-mute);font-variant-numeric:tabular-nums}
#${HOST_ID} .jvx-token[data-state="expired"]{color:var(--jvx-danger)}
#${HOST_ID} .jvx-warnbox{padding:10px 12px;border-radius:9px;border:1px solid color-mix(in srgb,var(--jvx-warn) 50%,transparent);color:var(--jvx-warn);background:color-mix(in srgb,var(--jvx-warn) 8%,transparent)}
#${HOST_ID} .jvx-menu{position:absolute;min-width:240px;max-width:min(360px,calc(100% - 16px));padding:6px;border-radius:12px;border:1px solid var(--jvx-line-strong);
  background:var(--jvx-surface-2);-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);box-shadow:0 18px 50px rgba(0,0,0,.6);display:grid;gap:2px}
#${HOST_ID} .jvx-menu [role="menuitem"]{display:flex;align-items:center;gap:10px;min-height:36px;padding:0 10px;border-radius:8px;border:0;background:transparent;text-align:left;width:100%}
#${HOST_ID} .jvx-menu [role="menuitem"]:hover:not([aria-disabled="true"]),#${HOST_ID} .jvx-menu [role="menuitem"]:focus-visible{background:color-mix(in srgb,var(--jvx-accent) 14%,transparent)}
#${HOST_ID} .jvx-menu [role="menuitem"][data-danger]{color:var(--jvx-danger)}
#${HOST_ID} .jvx-menu [role="menuitem"] small{margin-left:auto;color:var(--jvx-mute);font-size:11.5px}
#${HOST_ID} .jvx-menu-title{padding:6px 10px 4px;font-size:12px;color:var(--jvx-mute);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${HOST_ID} .jvx-busy{display:inline-flex;align-items:center;gap:8px;color:var(--jvx-accent);font-size:13px;font-variant-numeric:tabular-nums}
#${HOST_ID} .jvx-busy::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor}
@media (prefers-reduced-motion:no-preference){#${HOST_ID} .jvx-busy::before{animation:jvxPulse 1.1s ease-in-out infinite}}
@keyframes jvxPulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(1.5)}}
#${HOST_ID} .jvx-sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
@media (max-width:1100px){
  #${HOST_ID} .jvx-body{grid-template-columns:clamp(240px,31vw,340px) minmax(0,1fr)}
  #${HOST_ID} .jvx-bottom{grid-template-columns:minmax(0,1fr)}
  #${HOST_ID} .jvx-actions{grid-template-columns:repeat(3,minmax(0,auto));justify-content:start}
  #${HOST_ID} .jvx-top{padding:10px 14px}
}
@media (max-width:820px){
  #${HOST_ID} .jvx-body{grid-template-columns:minmax(210px,36vw) minmax(0,1fr)}
  #${HOST_ID} .jvx-preview{padding:12px 12px}
  #${HOST_ID} .jvx-btn{padding:0 10px}
  #${HOST_ID} .jvx-btn .jvx-btn-label-long{display:none}
  #${HOST_ID} .jvx-rowmeta{display:none}
  #${HOST_ID} .jvx-row{--row-pad:6px}
}
@media (max-height:640px){
  #${HOST_ID} .jvx-hint-keys{display:none}
  #${HOST_ID} .jvx-rationale{display:none}
  #${HOST_ID} .jvx-scene{flex-direction:row;align-items:center;width:auto;gap:8px;padding:4px 12px}
  #${HOST_ID} .jvx-scene-r,#${HOST_ID} .jvx-scene-b{display:none}
  #${HOST_ID} .jvx-stagewrap{min-height:120px}
}
@media (forced-colors:active){
  #${HOST_ID}{background:Canvas;color:CanvasText;-webkit-backdrop-filter:none;backdrop-filter:none}
  #${HOST_ID} .jvx-row[aria-selected="true"]{outline:2px solid Highlight}
  #${HOST_ID} .jvx-btn,#${HOST_ID} .jvx-dialog,#${HOST_ID} .jvx-menu{border-color:CanvasText}
}
`;

  const api=Object.freeze({
    ROUTE,PLAYBACK_ROUTE,COMMAND_ROUTE,STATE_ROUTE,HOST_ID,OBJECT_ID,PREVIEW_OBJECT_ID,STYLE_ID,STORAGE_KEY,ROW_H,OVERSCAN,MAX_LIVE,MAX_ARCHIVED,
    MAX_TITLE,MAX_RATIONALE,MAX_RATIONALE_BYTES,MAX_DEPTH_SHOWN,INDENT_PX,REQUEST_TIMEOUT_MS,READ_TIMEOUT_MS,PLAYBACK_CHECK_MS,LONG_PRESS_MS,
    PREVIEW_SETTLE_MS,NOTICE_MS,PREFS_MAX_COLLAPSED,STUDIO_STAGE_PREFIX,REFUSALS,COMMAND_REFUSALS,ICONS,CSS,
    clip,cleanLine,utf8Length,rationaleBytes,checkTitle,checkRationale,absoluteTime,relativeTime,creatorLabel,shortId,
    buildForest,childrenOf,ancestorsOf,subtreeIds,flatten,windowOf,treeKey,describeRefusal,planModel,blockedText,sameSet,readPrefs,writePrefs,
  });
  root.JarvisStudioExplorerCore=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
