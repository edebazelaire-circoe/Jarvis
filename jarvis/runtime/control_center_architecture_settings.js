/* Onglet « Architecture » de la page Réglages › Architecture & Agents
   (jarvis-architecture-agents-settings-editor, Slice 04).

   Projection et contrôleur du graphe d'architecture que sert le runtime : le composant ne connaît AUCUNE
   topologie. Il dessine les nœuds, endpoints, pools, ports et liaisons du snapshot (contrat :
   `tasks/jarvis-architecture-agents-settings-editor/docs/11-graph-wire-contract.md`, puis
   `docs/settings/architecture-tab.md`), et n'écrit que par l'adaptateur injecté :

     load()                                         -> snapshot              (lève une erreur `.code` sinon)
     setConnection(id, {base_revision, enabled})    -> résultat d'écriture
     createConnection({base_revision, source, target, channel}) -> résultat d'écriture
     removeConnection(id, {base_revision})          -> résultat d'écriture
     loadLayout()                                   -> {revision, positions}
     saveLayout({base_revision, positions})         -> {ok:true, layout} | {ok:false, status, code, reason, layout?}
     setNodeActivation(id, {base_revision, active}) -> résultat d'écriture   (FACULTATIF, hors contrat 11)

   Résultat d'écriture : `{ok:true, snapshot}` ou `{ok:false, status, code, reason, snapshot?}`. Un échec de
   transport lève une erreur `.code` (`architecture_timeout`, `architecture_unreachable`) : l'issue est alors
   inconnue, et la vue est relue de force. Après CHAQUE écriture, l'écran affiche le snapshot renvoyé par le
   serveur, jamais un état supposé ; un refus sans snapshot déclenche une relecture ; `409` aussi.

   Glisser un nœud ne change que la disposition (`saveLayout`, révisée) ; aucune mutation de topologie.

   Montage : `JarvisArchitectureSettings.mount(host, {adapter, onConfigureBrain, timeoutMs})`, qui rend un
   contrôleur (`destroy()` démonte). « Configurer… » appelle `onConfigureBrain(nodeId, detail)` (fenêtre de la
   Slice 05) ET émet `architecture:configure-brain` (CustomEvent qui bouillonne, `detail = {nodeId, field,
   source}`) sur l'hôte. Le style est injecté une fois (`#jarvisArchitectureSettingsStyle`) et ne contient que
   des jetons du thème (`--accent`, `--role-accent-*`…), jamais une couleur écrite ici. */
(function(root){
  'use strict';
  const STYLE_ID='jarvisArchitectureSettingsStyle';
  const DEFAULT_TIMEOUT_MS=15000;
  /* ROW laisse ~100 px entre deux rangs : deux libellés de liaisons opposées et leurs pointes y tiennent. */
  const NODE_W=208,NODE_H=136,COL=340,ROW=236,PAD=28,LAYOUT_STEP=16,BEND_STEP=60,LABEL_H=26;
  const UNKNOWN_OUTCOME=new Set(['architecture_timeout','architecture_unreachable']);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const own=(o,k)=>!!o&&Object.prototype.hasOwnProperty.call(o,k);
  const clone=v=>JSON.parse(JSON.stringify(v));

  /* Vocabulaire d'affichage des valeurs énumérées du contrat (chaînes stables). Une valeur inconnue s'affiche
     telle quelle : la page ne la réinterprète pas. */
  const CHANNEL={audio:'audio',request:'requête',response:'réponse',tool_call:'appel d’outil',event:'événement',speech:'parole'};
  const MUTABILITY={
    required_locked:['Obligatoire, verrouillée','Le runtime en a besoin : elle ne peut être ni désactivée ni supprimée.'],
    toggleable:['Modifiable','Vous pouvez l’activer ou la désactiver ici.'],
    creatable_removable:['Ajoutée, supprimable','Liaison facultative : vous pouvez la supprimer, et la recréer depuis un port compatible.'],
    governed:['Gouvernée','Elle suit un réglage du cerveau : lecture seule sur le graphe.'],
  };
  const STATE={active:['Actif','ok'],inactive:['Inactif','off'],shadow:['Ombre : observe sans agir','shadow'],unavailable:['Indisponible','bad']};
  const APPLIES={live:'immédiatement',next_turn:'au prochain tour de parole',core_restart:'au prochain démarrage de Core',voice_restart:'au prochain démarrage de la voix'};
  /* Valeurs d'`applies` qui attendent un redémarrage : aucun agent ne redémarre JARVIS (CLAUDE.md), la page le dit. */
  const RESTART_WHO={core_restart:'Core',voice_restart:'la voix'};
  const appliesText=a=>APPLIES[a]||(a?'selon « '+a+' »':'');
  const KIND={brain:'Cerveau',endpoint:'Endpoint',pool:'Pool'};
  const ENDPOINT={audio_input:'Entrée audio',audio_output:'Sortie audio'};
  const ACCENTS=['violet','sky','lime','teal','amber','rose','indigo','orange','cyan'];
  const ACCENT_TOKEN=/^[a-z][a-z0-9-]{0,31}$/;

  /* Pictogrammes dessinés (même trait partout) ; choisis par `kind` / `endpoint_type`, jamais par identifiant. */
  const G={
    brain:'<path d="M9.5 4.5a2.8 2.8 0 0 0-2.8 2.8v.4A2.9 2.9 0 0 0 4.5 10.5a2.9 2.9 0 0 0 1.1 4.4 2.9 2.9 0 0 0 3.9 4 2 2 0 0 0 2.5-1.6V6.2a2 2 0 0 0-2.5-1.7Z"/><path d="M14.5 4.5a2.8 2.8 0 0 1 2.8 2.8v.4a2.9 2.9 0 0 1 2.2 2.8 2.9 2.9 0 0 1-1.1 4.4 2.9 2.9 0 0 1-3.9 4A2 2 0 0 1 12 17.3"/><path d="M8.5 10.5h1.8M13.7 13.5h1.8"/>',
    microphone:'<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/>',
    speaker:'<path d="M4 9.5h3.5L12.5 5.5v13l-5-4H4Z"/><path d="M16 9a4.2 4.2 0 0 1 0 6M18.6 6.5a8 8 0 0 1 0 11"/>',
    pool:'<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19.5a5.5 5.5 0 0 1 11 0"/><circle cx="16.8" cy="9.5" r="2.4"/><path d="M15.6 14.3a4.8 4.8 0 0 1 5 5.2"/>',
    node:'<rect x="4.5" y="4.5" width="15" height="15" rx="3"/><path d="M9 12h6"/>',
    lock:'<rect x="5.5" y="10.5" width="13" height="9" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    on:'<rect x="3" y="7.5" width="18" height="9" rx="4.5"/><circle cx="16.5" cy="12" r="2.4" fill="currentColor"/>',
    off:'<rect x="3" y="7.5" width="18" height="9" rx="4.5"/><circle cx="7.5" cy="12" r="2.4"/>',
    plug:'<path d="M9 3.5V8M15 3.5V8M7 8h10v2.8a5 5 0 0 1-10 0ZM12 15.8v4.7"/>',
    governed:'<path d="M14 4.5h5.5V10M19.5 4.5 12 12"/><path d="M18 14v4.5a1 1 0 0 1-1 1H5.5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1H10"/>',
    clock:'<circle cx="12" cy="12" r="8"/><path d="M12 8v4.2l2.8 1.8"/>',
    more:'<circle cx="6" cy="12" r="1.5" fill="currentColor"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/><circle cx="18" cy="12" r="1.5" fill="currentColor"/>',
    sliders:'<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    refresh:'<path d="M19 12a7 7 0 1 1-2.1-5"/><path d="M19.5 4.5V9H15"/>',
    close:'<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    voice:'<path d="M4 12h1.5M7.5 8.5v7M11 5.5v13M14.5 8v8M18 10.5v3M20 12h.5"/>',
  };
  const glyph=(name,cls)=>`<svg class="${cls||'arch-g'}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${G[name]||G.node}</svg>`;
  const MUT_GLYPH={required_locked:'lock',toggleable:'on',creatable_removable:'plug',governed:'governed'};

  function logError(code,error,context){
    try{root.console&&root.console.error(code,error,context||{})}catch(_e){/* intentionnel : console absente, l'erreur est déjà à l'écran */}
    try{if(typeof root.obsClientLog==='function')root.obsClientLog('error','ERROR',code,{message:String(error&&error.message||error),...(context||{})})}
    catch(_e){/* intentionnel : le journal ne doit pas casser la page */}
  }
  function logInfo(code,data){try{root.console&&root.console.info(code,data||{})}catch(_e){/* intentionnel : idem */}}
  function codedError(code,message,extra){const e=new Error(message);e.code=code;return Object.assign(e,extra||{})}

  /* Échéance propre au composant : un adaptateur qui ne répond jamais ne fige pas l'écran. */
  function withDeadline(promise,ms,what){
    let timer=null;
    const guard=new Promise((_ok,ko)=>{timer=setTimeout(()=>ko(codedError('architecture_timeout',`Pas de réponse pour « ${what} » après ${Math.round(ms/1000)} s.`)),ms)});
    return Promise.race([Promise.resolve().then(()=>promise),guard]).finally(()=>clearTimeout(timer));
  }

  /* --- normalisation du snapshot ------------------------------------------ */
  function normalizeSnapshot(data){
    if(!data||typeof data!=='object'||!Array.isArray(data.nodes)||!Array.isArray(data.connections))
      throw codedError('architecture_payload_invalid','La réponse ne contient pas de liste de nœuds et de liaisons.');
    const str=v=>v==null?'':String(v);
    const nodes=data.nodes.filter(n=>n&&typeof n==='object'&&str(n.id).trim()).map(n=>({...n,id:str(n.id),label:str(n.label)||str(n.id),
      kind:str(n.kind)||'brain',state:str(n.state)||'unavailable',state_reason:str(n.state_reason),
      activation:n.activation&&typeof n.activation==='object'?{mutable:n.activation.mutable===true,reason:str(n.activation.reason)}:{mutable:false,reason:''},
      configurable:n.configurable===true,system:n.system===true,
      ports:Array.isArray(n.ports)?n.ports.filter(p=>p&&typeof p==='object'&&str(p.id)).map(p=>({...p,id:str(p.id),direction:p.direction==='in'?'in':'out',channel:str(p.channel),family:str(p.family)})):[]}));
    const ids=new Set(nodes.map(n=>n.id));
    const all=data.connections.filter(c=>c&&typeof c==='object'&&str(c.id)&&c.source&&c.target).map(c=>({...c,id:str(c.id),
      source:{node:str(c.source.node),port:str(c.source.port)},target:{node:str(c.target.node),port:str(c.target.port)},
      channel:str(c.channel),purpose:str(c.purpose),enabled:c.enabled===true,mutability:str(c.mutability)||'required_locked',
      locked_reason:str(c.locked_reason),impact_when_disabled:str(c.impact_when_disabled),applies:str(c.applies),
      pending:c.pending&&typeof c.pending==='object'?{enabled:c.pending.enabled===true,applies:str(c.pending.applies)}:null,
      governed_by:c.governed_by&&typeof c.governed_by==='object'?c.governed_by:null,binding:str(c.binding)}));
    const connections=all.filter(c=>ids.has(c.source.node)&&ids.has(c.target.node)&&c.source.node!==c.target.node);
    const creatable=Array.isArray(data.creatable)?data.creatable.filter(o=>o&&o.source&&o.target&&ids.has(str(o.source.node))&&ids.has(str(o.target.node))):[];
    const va=data.voice_architecture&&typeof data.voice_architecture==='object'?data.voice_architecture:null;
    return {...data,revision:data.revision==null?null:str(data.revision),nodes,connections,creatable,
      voice_architecture:va?{id:str(va.id),label:str(va.label)||str(va.id),settings_target:str(va.settings_target)||'architecture_compat'}:null,
      dropped:(data.nodes.length-nodes.length)+(data.connections.length-connections.length),
      versionMismatch:data.schema_version!==1};
  }

  /* Disposition automatique, générique : endpoints à gauche (entrées puis sorties), puis rangs par distance
     depuis eux en suivant les liaisons, une colonne par rang. Au-delà de `maxCols` colonnes, un nœud se place
     dans la case libre la plus proche sous son parent (grille repliée : pas de graphe hors cadre). Sert tant
     qu'aucune position n'est enregistrée pour un nœud. */
  function autoLayout(snapshot,maxCols){
    const limit=Math.max(1,Math.floor(Number(maxCols))||3);
    const rank=new Map(),out=new Map();
    for(const c of snapshot.connections){if(!out.has(c.source.node))out.set(c.source.node,[]);out.get(c.source.node).push(c.target.node)}
    const endpoints=snapshot.nodes.filter(n=>n.kind==='endpoint');
    const queue=[];
    for(const n of endpoints){rank.set(n.id,0);queue.push(n.id)}
    if(!queue.length&&snapshot.nodes[0]){rank.set(snapshot.nodes[0].id,0);queue.push(snapshot.nodes[0].id)}
    while(queue.length){
      const id=queue.shift();
      for(const t of out.get(id)||[])if(!rank.has(t)){rank.set(t,rank.get(id)+1);queue.push(t)}
    }
    let spare=Math.max(0,...rank.values())+1;
    for(const n of snapshot.nodes)if(!rank.has(n.id))rank.set(n.id,spare);
    const order=[...snapshot.nodes].sort((a,b)=>rank.get(a.id)-rank.get(b.id)||((a.kind==='endpoint'&&b.kind==='endpoint')?
      ((a.endpoint_type==='audio_output')-(b.endpoint_type==='audio_output')):0));
    const parent=new Map();
    for(const c of snapshot.connections)if(rank.get(c.target.node)===rank.get(c.source.node)+1&&!parent.has(c.target.node))parent.set(c.target.node,c.source.node);
    const cell=new Map(),taken=new Set(),free=(c,r)=>!taken.has(c+':'+r);
    const put=(id,c,r)=>{cell.set(id,[c,r]);taken.add(c+':'+r)};
    for(const n of order){
      const r=rank.get(n.id);
      if(r<limit){let row=0;while(!free(r,row))row+=1;put(n.id,r,row);continue}
      const [pc,pr]=cell.get(parent.get(n.id))||[limit-1,0];
      let done=false;
      for(let row=pr+1;!done;row+=1)for(let d=0;d<limit&&!done;d+=1)for(const c of d?[pc-d,pc+d]:[pc])
        if(!done&&c>=0&&c<limit&&free(c,row)){put(n.id,c,row);done=true}
    }
    const pos={};
    for(const [id,[c,r]] of cell)pos[id]={x:PAD+c*COL,y:PAD+r*ROW+(c%2?ROW/3:0)};
    return pos;
  }

  /* --- géométrie des liaisons ---------------------------------------------- */
  function border(cx,cy,dx,dy,grow){
    const hw=NODE_W/2+grow,hh=NODE_H/2+grow;
    const t=Math.min(dx?hw/Math.abs(dx):Infinity,dy?hh/Math.abs(dy):Infinity);
    return [cx+dx*t,cy+dy*t];
  }
  /* Une liaison est une courbe quadratique : droite quand rien ne gêne, arquée pour séparer deux liaisons entre
     les mêmes nœuds (sens opposés compris) et pour contourner un nœud qui serait sur son chemin. */
  function quad(g,t){const u=1-t;return [u*u*g.x1+2*u*t*g.cx+t*t*g.x2,u*u*g.y1+2*u*t*g.cy+t*t*g.y2]}
  const unit=(x,y)=>{const l=Math.hypot(x,y)||1;return [x/l,y/l]};
  function curve(a,b,off){
    const ax=a.x+NODE_W/2,ay=a.y+NODE_H/2,bx=b.x+NODE_W/2,by=b.y+NODE_H/2;
    const [dx,dy]=unit(bx-ax,by-ay);
    /* Contrôle à 2×off du milieu : le sommet de l'arc est à `off` de la droite des centres. */
    const cx=(ax+bx)/2-dy*off*2,cy=(ay+by)/2+dx*off*2;
    const [sx,sy]=off?unit(cx-ax,cy-ay):[dx,dy],[ex,ey]=off?unit(cx-bx,cy-by):[-dx,-dy];
    const [x1,y1]=border(ax,ay,sx,sy,4),[x2,y2]=border(bx,by,ex,ey,8);
    return {x1,y1,cx:off?cx:(x1+x2)/2,cy:off?cy:(y1+y2)/2,x2,y2};
  }
  function rectOf(p,grow){return {l:p.x-grow,t:p.y-grow,r:p.x+NODE_W+grow,b:p.y+NODE_H+grow}}
  function crossings(g,rects){
    let n=0;
    /* Un point hors du monde (x ou y négatif) compte comme un obstacle : le canevas ne défile pas vers la gauche. */
    for(let i=1;i<20;i+=1){const [x,y]=quad(g,i/20);if(x<PAD/2||y<PAD/2)n+=3;for(const r of rects)if(x>r.l&&x<r.r&&y>r.t&&y<r.b)n+=1}
    return n;
  }
  function routeEdges(connections,nodeIds,posOf){
    const groups=new Map();
    for(const c of connections){const k=JSON.stringify([c.source.node,c.target.node].sort());if(!groups.has(k))groups.set(k,[]);groups.get(k).push(c.id)}
    const lane=new Map();
    for(const ids of groups.values())ids.forEach((id,i)=>lane.set(id,i-(ids.length-1)/2));
    const out=new Map();
    for(const c of connections){
      const a=posOf(c.source.node),b=posOf(c.target.node);
      const [,dy]=unit(b.x-a.x,b.y-a.y);
      /* Même sens de « gauche » pour les deux liaisons d'une paire ; l'écart suit la taille du libellé à loger
         côte à côte : large quand la liaison est verticale, une hauteur de libellé quand elle est horizontale. */
      const flip=c.source.node<c.target.node?1:-1,l=lane.get(c.id)||0;
      const base=l*flip*2*(LABEL_H+48*Math.abs(dy));
      const others=nodeIds.filter(id=>id!==c.source.node&&id!==c.target.node).map(id=>rectOf(posOf(id),10));
      const sign=Math.sign(base)||1;let best=null;
      for(const k of [0,1,-1,2,-2,3,-3,4,-4]){
        const g=curve(a,b,base+sign*k*BEND_STEP),n=crossings(g,others);
        if(!best||n<best.n)best={g,n};
        if(!n)break;
      }
      out.set(c.id,best.g);
    }
    return out;
  }

  function mount(host,options){
    if(!host)throw codedError('architecture_mount_missing','Aucun hôte pour l’onglet Architecture.');
    const opts=options||{};
    const adapter=opts.adapter;
    if(!adapter||typeof adapter.load!=='function')throw codedError('architecture_adapter_missing','Adaptateur d’architecture absent ou incomplet.');
    const timeoutMs=Number(opts.timeoutMs)>0?Number(opts.timeoutMs):DEFAULT_TIMEOUT_MS;
    const now=typeof opts.now==='function'?opts.now:()=>Date.now();
    const setTimer=opts.setInterval||((fn,ms)=>root.setInterval?root.setInterval(fn,ms):null);
    const clearTimer=opts.clearInterval||(id=>{if(id!=null&&root.clearInterval)root.clearInterval(id)});
    const doc=host.ownerDocument||root.document||null;
    const uid='a'+Math.random().toString(36).slice(2,8);

    const st={
      phase:'loading',error:null,snapshot:null,startedAt:now(),reloading:null,
      layout:{phase:'loading',revision:null,positions:{},error:null},moved:{},layoutSave:null,layoutNotice:null,
      selected:null,            // {type:'connection'|'node', id}
      write:null,               // {id, label, startedAt}
      notice:null,              // {tone, text, hint, code, target}
      menu:null,                // {nodeId, x, y}
      linking:null,             // {node, port}
      confirmRemove:null,destroyed:false,
    };
    let ticker=null,layoutTimer=null,drag=null,suppressClickUntil=0;

    const nodes=()=>(st.snapshot&&st.snapshot.nodes)||[];
    const connections=()=>(st.snapshot&&st.snapshot.connections)||[];
    const nodeById=id=>nodes().find(n=>n.id===id)||null;
    const connById=id=>connections().find(c=>c.id===id)||null;
    let auto={};
    /* Colonnes qui tiennent dans le canevas (l'inspecteur occupe ~352 px au-delà de 860 px de large). */
    function columnsFit(){
      const w=Number(host.clientWidth)||0;if(!w)return 3;
      const avail=w>=860?w-352:w;
      return Math.max(1,Math.floor((avail-2*PAD-NODE_W)/COL)+1);
    }
    function posOf(id){return st.moved[id]||st.layout.positions[id]||auto[id]||{x:PAD,y:PAD}}
    const nodeLabel=id=>(nodeById(id)||{label:id}).label;
    const channelLabel=c=>CHANNEL[c]||c||'canal inconnu';
    const effectiveEnabled=c=>c.pending?c.pending.enabled:c.enabled;
    function accentOf(n){
      const v=n.visual&&n.visual.accent;
      if(ACCENT_TOKEN.test(String(v||''))&&ACCENTS.includes(v))return v;
      if(n.kind==='endpoint')return 'cyan';
      if(n.kind==='pool')return 'amber';
      /* Stable par type de cerveau, sans table d'identifiants : un nouveau type reçoit une teinte sans code. */
      const key=String(n.brain_type||n.id);let h=0;for(const ch of key)h=(h*31+ch.charCodeAt(0))>>>0;
      return ACCENTS[h%3];
    }
    function nodeGlyph(n){
      if(n.kind==='endpoint')return n.endpoint_type==='audio_output'?'speaker':n.endpoint_type==='audio_input'?'microphone':'node';
      return n.kind==='pool'?'pool':n.kind==='brain'?'brain':'node';
    }
    function kindLabel(n){
      if(n.kind==='endpoint')return ENDPOINT[n.endpoint_type]||('Endpoint '+(n.endpoint_type||''));
      return KIND[n.kind]||n.kind;
    }

    /* --- rendu ------------------------------------------------------------- */
    const elapsed=since=>Math.max(0,Math.floor((now()-since)/1000));
    function waitingHtml(label,since){
      return `<span class="arch-wait" role="status"><span class="arch-spin" aria-hidden="true"></span><span>${esc(label)}</span>
        <span class="arch-elapsed" data-arch-since="${since}">${elapsed(since)} s</span><span class="arch-hint">abandon après ${Math.round(timeoutMs/1000)} s</span></span>`;
    }
    const codeLine=code=>code?`<span class="arch-code">Code : <code>${esc(code)}</code></span>`:'';
    function noticeHtml(n){
      if(!n)return '';
      const f=n.followup?`<p data-arch-followup>${esc(n.followup.text)}</p>${n.followup.hint?`<p class="arch-hint">${esc(n.followup.hint)}</p>`:''}${codeLine(n.followup.code)}`:'';
      return `<div class="arch-notice ${esc(n.tone||'')}" role="${n.tone==='bad'?'alert':'status'}" data-arch-notice>${glyph(n.tone==='bad'?'close':n.tone==='ok'?'on':'clock','arch-g arch-notice-g')}<div><p>${esc(n.text)}</p>${n.hint?`<p class="arch-hint">${esc(n.hint)}</p>`:''}${codeLine(n.code)}${f}</div></div>`;
    }
    function voiceBanner(){
      const va=st.snapshot&&st.snapshot.voice_architecture;
      if(!va)return '<div class="arch-voice" data-arch-voice><span class="arch-voice-k">Architecture vocale</span><span class="arch-hint">non indiquée par le runtime</span></div>';
      return `<div class="arch-voice" data-arch-voice>${glyph('voice','arch-g')}<span class="arch-voice-k">Architecture vocale effective</span>
        <strong class="arch-voice-v">${esc(va.label)}</strong><span class="arch-tag">${glyph('lock','arch-g arch-g-sm')}lecture seule</span>
        <button type="button" class="arch-linkbtn" data-settings-open="${esc(va.settings_target)}">Changer dans Avancé › Architecture vocale</button></div>`;
    }
    function statusLine(){
      const bits=[];
      if(st.reloading)bits.push(waitingHtml('Relecture de l’architecture…',st.reloading));
      if(st.write&&!(st.selected&&st.selected.id===st.write.id))bits.push(waitingHtml(st.write.label,st.write.startedAt));
      if(st.layoutSave)bits.push(waitingHtml('Enregistrement de la disposition…',st.layoutSave));
      else if(st.layoutNotice)bits.push(`<span class="arch-layout-note ${esc(st.layoutNotice.tone)}" data-arch-layout-note>${esc(st.layoutNotice.text)}${st.layoutNotice.code?` <code>${esc(st.layoutNotice.code)}</code>`:''}</span>`);
      if(st.layout.phase==='error')bits.push(`<span class="arch-layout-note bad" data-arch-layout-note>Disposition enregistrée illisible : disposition automatique, déplacements non enregistrés. <button type="button" class="arch-linkbtn" data-arch-act="layout-retry">Relire</button></span>`);
      return `<div class="arch-status">${bits.join('')}<button type="button" class="arch-btn ghost" data-arch-act="reload"${st.reloading||st.write?' disabled':''}>${glyph('refresh','arch-g')}Relire</button></div>`;
    }
    function legendHtml(){
      const item=(cls,g,label,hint)=>`<li><svg class="arch-legend-line" viewBox="0 0 44 10" aria-hidden="true"><line x1="2" y1="5" x2="40" y2="5" class="arch-edge ${cls}"/></svg>${glyph(g,'arch-g arch-g-sm')}<span><strong>${esc(label)}</strong> ${esc(hint)}</span></li>`;
      return `<section class="arch-legend" aria-labelledby="${uid}-legend"><h4 id="${uid}-legend">Légende des liaisons</h4><ul>
        ${item('m-required_locked on','lock','Obligatoire','trait plein épais, cadenas : non modifiable')}
        ${item('m-toggleable on','on','Modifiable, active','trait plein, interrupteur allumé')}
        ${item('m-toggleable off','off','Modifiable, désactivée','pointillé atténué, interrupteur éteint')}
        ${item('m-creatable_removable on','plug','Supprimable','tirets mixtes, prise')}
        ${item('m-governed on','governed','Gouvernée','points, réglée dans la fenêtre du cerveau')}
        <li>${glyph('clock','arch-g arch-g-sm')}<span><strong>En attente</strong> enregistrée, effective au prochain démarrage de Core ou de la voix</span></li>
      </ul><p class="arch-hint">Flèche = sens du flux ; le libellé donne le canal.</p></section>`;
    }
    function stateChip(n){
      const [text,tone]=STATE[n.state]||[n.state,'off'];
      return `<span class="arch-state ${tone}" title="${esc(n.state_reason||text)}"><span class="arch-dot" aria-hidden="true"></span>${esc(text)}</span>`;
    }
    function portHtml(n,p){
      /* Clé encodée composant par composant : un identifiant peut contenir « : » ou « > ». */
      const L=st.linking,key=encodeURIComponent(n.id)+'/'+encodeURIComponent(p.id);
      const creatable=(st.snapshot&&st.snapshot.creatable)||[];
      const asSource=p.direction==='out'&&creatable.some(o=>o.source.node===n.id&&o.source.port===p.id);
      const asTarget=L&&p.direction==='in'&&creatable.some(o=>o.source.node===L.node&&o.source.port===L.port&&o.target.node===n.id&&o.target.port===p.id);
      const text=`<span class="arch-port-dir" aria-hidden="true"></span>${esc(p.id)}`;
      const title=`${p.direction==='in'?'Port d’entrée':'Port de sortie'} ${p.id} · canal ${channelLabel(p.channel)}`;
      if(asTarget)return `<button type="button" class="arch-port target" data-dir="in" data-arch-port-target="${esc(key)}" title="${esc(title)}" aria-label="Relier à ${esc(n.label)}, port ${esc(p.id)}">${text}</button>`;
      if(asSource&&!L)return `<button type="button" class="arch-port source" data-dir="out" data-arch-port-source="${esc(key)}" title="${esc(title)} : créer une liaison" aria-label="Créer une liaison depuis ${esc(n.label)}, port ${esc(p.id)}">${text}</button>`;
      const active=L&&L.node===n.id&&L.port===p.id;
      return `<span class="arch-port${active?' linking':''}" data-dir="${p.direction}" title="${esc(title)}">${text}</span>`;
    }
    function nodeHtml(n){
      const p=posOf(n.id),sel=st.selected&&st.selected.type==='node'&&st.selected.id===n.id;
      const hasMenu=n.kind==='brain';
      const ports=n.ports.slice(0,5).map(port=>portHtml(n,port)).join('')+(n.ports.length>5?`<span class="arch-port more" title="${esc(n.ports.slice(5).map(x=>x.id).join(', '))}">+${n.ports.length-5}</span>`:'');
      const sub=[kindLabel(n),n.process||''].filter(Boolean).join(' · ');
      const name=`${n.label}, ${kindLabel(n)}, ${(STATE[n.state]||[n.state])[0]}${n.system?', système':''}. Entrée : inspecter${hasMenu?' ; Maj+F10 : actions':''} ; Maj+flèches : déplacer`;
      return `<div class="arch-node k-${esc(n.kind)} s-${esc(n.state)}${sel?' sel':''}" style="left:${Math.round(p.x)}px;top:${Math.round(p.y)}px;--arch-accent:var(--role-accent-${accentOf(n)})"
          data-arch-node="${esc(n.id)}" tabindex="0" role="group" aria-roledescription="module" aria-label="${esc(name+(sel?' (sélectionné)':''))}">
        <div class="arch-node-head"><span class="arch-tile">${glyph(nodeGlyph(n),'arch-g arch-g-lg')}</span>
          <span class="arch-node-text"><span class="arch-node-name">${esc(n.label)}</span><span class="arch-node-sub">${esc(sub)}</span></span>
          ${hasMenu?`<button type="button" class="arch-more" data-arch-menu-btn="${esc(n.id)}" aria-haspopup="menu" aria-expanded="${st.menu&&st.menu.nodeId===n.id?'true':'false'}" aria-label="Actions de ${esc(n.label)}" title="Actions">${glyph('more','arch-g')}</button>`:''}</div>
        <div class="arch-node-meta">${stateChip(n)}${n.system?`<span class="arch-tag" title="${esc(n.activation.reason||'Module système')}">${glyph('lock','arch-g arch-g-sm')}système</span>`:''}</div>
        <div class="arch-ports">${ports}</div></div>`;
    }
    function edgesHtml(){
      const ids=nodes().map(n=>n.id),geo=routeEdges(connections(),ids,posOf);
      let w=0,h=0;
      for(const n of nodes()){const p=posOf(n.id);w=Math.max(w,p.x+NODE_W+PAD);h=Math.max(h,p.y+NODE_H+PAD)}
      const markers=Object.keys(CHANNEL).concat(['other']).map(ch=>`<marker id="${uid}-arrow-${ch}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="arch-mk ch-${ch}"/></marker>`).join('');
      /* Obstacles d'un libellé : les nœuds, toutes les pointes de flèche, les libellés déjà posés. */
      const nodeRects=ids.map(id=>rectOf(posOf(id),6));
      const tips=[...geo.values()].map(g=>{const [tx,ty]=unit(g.x2-g.cx,g.y2-g.cy);const x=g.x2-tx*4,y=g.y2-ty*4;return {l:x-10,t:y-10,r:x+10,b:y+10}});
      const placed=[];
      const area=(a,b)=>Math.max(0,Math.min(a.r,b.r)-Math.max(a.l,b.l))*Math.max(0,Math.min(a.b,b.b)-Math.max(a.t,b.t));
      /* Libellé au milieu de la courbe ; sinon glissé le long d'elle et/ou décalé de côté, au moindre recouvrement. */
      const place=(g,text,pending)=>{
        const lw=42+text.length*6.8+(pending?18:0);let best=null;
        const [nx,ny]=(()=>{const [dx,dy]=unit(g.x2-g.x1,g.y2-g.y1);return [-dy,dx]})();
        search:for(const t of [.5,.42,.58,.34,.66,.26,.74])for(const o of [0,18,-18,36,-36,54,-54]){
          const [qx,qy]=quad(g,t),x=qx+nx*o,y=qy+ny*o;
          const box={l:x-lw/2-3,t:y-LABEL_H/2-3,r:x+lw/2+3,b:y+LABEL_H/2+3};
          const out=Math.max(0,4-box.l)+Math.max(0,4-box.t);
          const cost=out*1e4+[...placed,...nodeRects,...tips].reduce((sum,r)=>sum+area(box,r),0);
          if(!best||cost<best.cost)best={x,y,box,cost};
          if(!cost)break search;
        }
        placed.push(best.box);w=Math.max(w,best.box.r+PAD);h=Math.max(h,best.box.b+PAD);return best;
      };
      const paths=[],labels=[];
      for(const c of connections()){
        const g=geo.get(c.id),ch=CHANNEL[c.channel]?c.channel:'other';
        const sel=st.selected&&st.selected.type==='connection'&&st.selected.id===c.id;
        const cls=`arch-edge m-${esc(c.mutability)} ch-${ch} ${c.enabled?'on':'off'}${sel?' sel':''}${c.pending?' pending':''}`;
        const f=v=>v.toFixed(1);
        const d=`M${f(g.x1)} ${f(g.y1)}Q${f(g.cx)} ${f(g.cy)} ${f(g.x2)} ${f(g.y2)}`;
        w=Math.max(w,g.cx+PAD,g.x2+PAD);h=Math.max(h,g.cy+PAD,g.y2+PAD);
        paths.push(`<g data-arch-edge="${esc(c.id)}">${c.mutability==='required_locked'?`<path d="${d}" class="arch-casing ch-${ch}"/>`:''}<path d="${d}" class="${cls}" marker-end="url(#${uid}-arrow-${ch})"/><path d="${d}" class="arch-hit" data-arch-conn="${esc(c.id)}"/></g>`);
        const mg=c.mutability==='toggleable'?(c.enabled?'on':'off'):(MUT_GLYPH[c.mutability]||'lock');
        const state=c.enabled?'active':'désactivée';
        const mut=(MUTABILITY[c.mutability]||[c.mutability])[0];
        const lp=place(g,channelLabel(c.channel),!!c.pending);
        const aria=`Liaison ${nodeLabel(c.source.node)} vers ${nodeLabel(c.target.node)}, ${channelLabel(c.channel)}, ${state}, ${mut}${c.pending?', changement en attente '+(appliesText(c.pending.applies)):''}. Entrée pour inspecter.`;
        labels.push(`<button type="button" class="arch-label m-${esc(c.mutability)} ch-${ch} ${c.enabled?'on':'off'}${sel?' sel':''}" style="left:${lp.x.toFixed(1)}px;top:${lp.y.toFixed(1)}px" data-arch-conn="${esc(c.id)}" aria-label="${esc(aria)}" aria-pressed="${sel?'true':'false'}">${glyph(mg,'arch-g arch-g-sm')}<span>${esc(channelLabel(c.channel))}</span>${c.pending?glyph('clock','arch-g arch-g-sm arch-pending-g'):''}</button>`);
      }
      w=Math.ceil(w);h=Math.ceil(h);
      return {w,h,svg:`<svg class="arch-edges" width="${w}" height="${h}" aria-hidden="true"><defs>${markers}</defs>${paths.join('')}</svg>`,labels:labels.join('')};
    }
    function menuHtml(){
      const m=st.menu,n=m&&nodeById(m.nodeId);
      if(!n)return '';
      const items=[`<button type="button" role="menuitem" class="arch-menu-item" data-arch-menu="inspect" tabindex="-1">${glyph('node','arch-g')}Inspecter</button>`];
      if(n.configurable)items.unshift(`<button type="button" role="menuitem" class="arch-menu-item" data-arch-menu="configure" tabindex="-1">${glyph('sliders','arch-g')}Configurer…</button>`);
      if(n.activation.mutable&&typeof adapter.setNodeActivation==='function'){
        const on=n.state==='active'||n.state==='shadow';
        items.push(`<button type="button" role="menuitem" class="arch-menu-item" data-arch-menu="${on?'deactivate':'activate'}" tabindex="-1">${glyph(on?'off':'on','arch-g')}${on?'Désactiver':'Activer'}</button>`);
      }else{
        items.push(`<p class="arch-menu-note" role="none">${glyph('lock','arch-g arch-g-sm')}${esc(n.activation.reason||'Activation non modifiable ici.')}</p>`);
      }
      return `<div class="arch-menu" role="menu" aria-label="Actions de ${esc(n.label)}" data-arch-menu-for="${esc(n.id)}" style="left:${Math.round(m.x)}px;top:${Math.round(m.y)}px">${items.join('')}</div>`;
    }
    function factRows(rows){return `<dl class="arch-facts">${rows.filter(Boolean).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`}
    function connectionInspector(c){
      const [mutLabel,mutHint]=MUTABILITY[c.mutability]||[c.mutability,'Mutabilité inconnue de cette page : lecture seule.'];
      const busy=!!st.write,mine=st.write&&st.write.id===c.id;
      const want=!effectiveEnabled(c);
      let action='';
      if(c.mutability==='toggleable'){
        action=`<button type="button" class="arch-switch" role="switch" aria-checked="${effectiveEnabled(c)?'true':'false'}" data-arch-act="toggle" data-arch-id="${esc(c.id)}"${busy?' disabled':''}>
          <span class="arch-switch-track" aria-hidden="true"><span class="arch-switch-knob"></span></span><span>${effectiveEnabled(c)?'Active':'Désactivée'}</span><span class="arch-hint">${want?'Activer':'Désactiver'} cette liaison</span></button>`;
      }else if(c.mutability==='creatable_removable'){
        const confirming=st.confirmRemove===c.id;
        action=`<div class="arch-actions"><button type="button" class="arch-btn${confirming?' danger':''}" data-arch-act="remove" data-arch-id="${esc(c.id)}"${busy?' disabled':''}>${glyph('close','arch-g')}${confirming?'Confirmer la suppression':'Supprimer la liaison'}</button>
          ${confirming?'<button type="button" class="arch-btn ghost" data-arch-act="remove-cancel">Annuler</button>':''}</div>`;
      }else if(c.mutability==='governed'){
        const gb=c.governed_by||{};
        action=gb.kind==='brain_config'&&gb.node?`<button type="button" class="arch-btn" data-arch-act="governed" data-arch-id="${esc(c.id)}">${glyph('governed','arch-g')}Réglé dans la fenêtre du cerveau ${esc(nodeLabel(gb.node))}</button>`
          :'<p class="arch-hint">Gouvernée par un réglage que cette page ne sait pas ouvrir.</p>';
      }
      const pending=c.pending?`<div class="arch-notice warn" data-arch-pending>${glyph('clock','arch-g arch-notice-g')}<div><p>Changement enregistré : ${c.pending.enabled?'activée':'désactivée'} ${esc(appliesText(c.pending.applies))}.</p><p class="arch-hint">Le graphe montre l’état vivant (${c.enabled?'active':'désactivée'}) jusque-là.${RESTART_WHO[c.pending.applies]?` Effectif au prochain démarrage de ${esc(RESTART_WHO[c.pending.applies])} : redémarrez JARVIS quand vous le souhaitez.`:''}</p></div></div>`:'';
      return `<header class="arch-insp-head"><h3 id="${uid}-insp" tabindex="-1">${esc(nodeLabel(c.source.node))} <span class="arch-arrow" aria-label="vers">→</span> ${esc(nodeLabel(c.target.node))}</h3>
        <button type="button" class="arch-icon-btn" data-arch-act="close" aria-label="Fermer l’inspecteur">${glyph('close','arch-g')}</button></header>
        <p class="arch-purpose">${esc(c.purpose||'But non décrit par le runtime.')}</p>
        <div class="arch-insp-tags"><span class="arch-tag ch">${esc(channelLabel(c.channel))}</span><span class="arch-tag">${glyph(MUT_GLYPH[c.mutability]||'lock','arch-g arch-g-sm')}${esc(mutLabel)}</span><span class="arch-tag ${c.enabled?'ok':''}">${c.enabled?'active':'désactivée'}</span></div>
        ${pending}
        ${factRows([
          ['Source',`${esc(nodeLabel(c.source.node))} · port <code>${esc(c.source.port)}</code>`],
          ['Cible',`${esc(nodeLabel(c.target.node))} · port <code>${esc(c.target.port)}</code>`],
          ['Mutabilité',esc(mutHint)],
          c.locked_reason?['Raison du verrou',esc(c.locked_reason)]:null,
          c.impact_when_disabled?['Si désactivée',esc(c.impact_when_disabled)]:null,
          c.applies?['Prise d’effet',esc(appliesText(c.applies))]:null,
          c.binding?['Réglage porteur',`<code>${esc(c.binding)}</code>`]:null,
        ])}
        ${mine?waitingHtml(st.write.label,st.write.startedAt):''}
        ${st.notice&&st.notice.target===c.id?noticeHtml(st.notice):''}
        ${action}`;
    }
    function nodeInspector(n){
      const ins=connections().filter(c=>c.target.node===n.id),outs=connections().filter(c=>c.source.node===n.id);
      const list=(title,items,other)=>`<div class="arch-insp-list"><h4>${esc(title)}</h4>${items.length?`<ul>${items.map(c=>`<li><button type="button" class="arch-linkbtn" data-arch-focus-conn="${esc(c.id)}">${esc(nodeLabel(other(c)))} · ${esc(channelLabel(c.channel))}</button> <span class="arch-hint">${esc((MUTABILITY[c.mutability]||[c.mutability])[0])}${c.enabled?'':', désactivée'}</span></li>`).join('')}</ul>`:'<p class="arch-hint">aucune</p>'}</div>`;
      const creatable=((st.snapshot&&st.snapshot.creatable)||[]).map((o,i)=>({...o,index:i})).filter(o=>o.source.node===n.id);
      const create=creatable.length?`<div class="arch-insp-list"><h4>Liaisons possibles</h4><ul>${creatable.map(o=>`<li><button type="button" class="arch-linkbtn" data-arch-create="${o.index}"${st.write?' disabled':''}>Créer ${esc(o.source.port)} → ${esc(nodeLabel(o.target.node))}</button> <span class="arch-hint">${esc(channelLabel(o.channel))}${o.purpose?' · '+esc(o.purpose):''}</span></li>`).join('')}</ul></div>`:'';
      return `<header class="arch-insp-head"><h3 id="${uid}-insp" tabindex="-1">${esc(n.label)}</h3>
        <button type="button" class="arch-icon-btn" data-arch-act="close" aria-label="Fermer l’inspecteur">${glyph('close','arch-g')}</button></header>
        <div class="arch-insp-tags">${stateChip(n)}<span class="arch-tag">${esc(kindLabel(n))}</span>${n.system?`<span class="arch-tag">${glyph('lock','arch-g arch-g-sm')}système</span>`:''}</div>
        ${n.state_reason?`<p class="arch-purpose">${esc(n.state_reason)}</p>`:''}
        ${factRows([['Identifiant',`<code>${esc(n.id)}</code>`],n.brain_type?['Type',`<code>${esc(n.brain_type)}</code>`]:null,n.process?['Processus',esc(n.process)]:null,
          ['Activation',n.activation.mutable?'modifiable':`verrouillée${n.activation.reason?' : '+esc(n.activation.reason):''}`],
          ['Ports',n.ports.map(p=>`<code>${esc(p.direction==='in'?'← ':'→ ')}${esc(p.id)}</code>`).join(' ')||'aucun']])}
        ${list('Entrantes',ins,c=>c.source.node)}${list('Sortantes',outs,c=>c.target.node)}${create}
        ${st.notice&&st.notice.target===n.id?noticeHtml(st.notice):''}
        ${n.kind==='brain'&&n.configurable?`<div class="arch-actions"><button type="button" class="arch-btn" data-arch-act="configure" data-arch-id="${esc(n.id)}">${glyph('sliders','arch-g')}Configurer…</button></div>`:''}`;
    }
    function inspectorHtml(){
      const s=st.selected;
      const c=s&&s.type==='connection'?connById(s.id):null,n=s&&s.type==='node'?nodeById(s.id):null;
      /* Une notice liée à un élément qui n'est pas affiché ici reste visible en tête : jamais de refus caché. */
      const shown=st.notice&&st.notice.target&&s&&st.notice.target===s.id&&(c||n);
      const general=st.notice&&!shown?noticeHtml(st.notice):'';
      if(c)return general+connectionInspector(c);
      if(n)return general+nodeInspector(n);
      return `${general}<div class="arch-insp-empty"><h3 id="${uid}-insp" tabindex="-1">Inspecteur</h3><p>Choisissez une liaison (son libellé) pour voir son but, sa mutabilité et l’impact d’un changement, ou un module pour ses ports et ses liaisons.</p>
        <p class="arch-hint">Clavier : Tab parcourt modules puis liaisons, Entrée inspecte, Maj+F10 ouvre les actions d’un cerveau, Maj+flèches déplace un module.</p></div>`;
    }
    function frame(body){return `<div class="arch" data-architecture-settings="1">${body}<div class="arch-sr" aria-live="polite" data-arch-live>${esc(st.live||'')}</div></div>`}

    function html(){
      if(st.phase==='loading')return frame(`<div class="arch-bar"><div class="arch-voice"><span class="arch-skel w1"></span></div></div>
        <div class="arch-main"><div class="arch-canvas arch-canvas-skel" aria-busy="true"><div class="arch-centered">${waitingHtml('Lecture de l’architecture du runtime…',st.startedAt)}</div></div></div>`);
      if(st.phase==='error'){
        const e=st.error||{},unreachable=e.code==='architecture_unreachable'||e.code==='architecture_timeout';
        return frame(`<div class="arch-main"><div class="arch-canvas arch-canvas-skel"><div class="arch-centered arch-error" role="alert">
          <h3>${unreachable?'Control Center injoignable':'Architecture illisible'}</h3><p>${esc(e.message||'Erreur inconnue.')}</p>
          <p class="arch-hint">${unreachable?'Vérifiez que le Control Center répond, puis réessayez. Rien n’a été modifié.':e.code==='architecture_payload_invalid'?'La page et le serveur ne sont peut-être pas de la même version : rechargez la page.':'Réessayez ; si l’erreur revient, signalez-la avec le code ci-dessous.'}</p>
          ${codeLine(e.code)}<div class="arch-actions"><button type="button" class="arch-btn" data-arch-act="reload">${glyph('refresh','arch-g')}Réessayer</button></div></div></div></div>`);
      }
      const snap=st.snapshot;
      const warn=[snap.versionMismatch?`Version de contrat inattendue (${esc(String(snap.schema_version))}) : affichage au mieux, vérifiez que la page et le serveur sont à jour.`:'',
        snap.dropped?`${snap.dropped} élément(s) du snapshot écarté(s) : nœud sans identifiant ou liaison vers un module absent.`:''].filter(Boolean);
      const top=`<div class="arch-bar">${voiceBanner()}${statusLine()}</div>${warn.map(t=>`<div class="arch-notice warn">${glyph('clock','arch-g arch-notice-g')}<div><p>${t}</p></div></div>`).join('')}`;
      if(!nodes().length)return frame(top+`<div class="arch-main"><div class="arch-canvas arch-canvas-skel"><div class="arch-centered"><h3>Aucun module dans l’architecture</h3><p class="arch-hint">Le runtime n’a déclaré aucun nœud. Rien n’est inventé ici : relisez quand Core sera démarré.</p>
        <div class="arch-actions"><button type="button" class="arch-btn" data-arch-act="reload">${glyph('refresh','arch-g')}Relire</button></div></div></div></div>`);
      const e=edgesHtml();
      const linking=st.linking?`<div class="arch-linking" role="status">${glyph('plug','arch-g')}Choisissez un port d’arrivée en surbrillance pour ${esc(nodeLabel(st.linking.node))} · ${esc(st.linking.port)}. <button type="button" class="arch-linkbtn" data-arch-act="link-cancel">Annuler (Échap)</button></div>`:'';
      return frame(top+`<div class="arch-main">
        <div class="arch-canvas" data-arch-canvas role="group" aria-label="Graphe d’architecture : ${nodes().length} modules, ${connections().length} liaisons">${linking}
          <div class="arch-world" data-arch-world style="width:${e.w}px;height:${e.h}px">
            <div data-arch-edges>${e.svg}</div>${nodes().map(nodeHtml).join('')}<div class="arch-labels" data-arch-labels>${e.labels}</div>${menuHtml()}</div></div>
        <aside class="arch-inspector" aria-labelledby="${uid}-insp" data-arch-inspector>${inspectorHtml()}</aside></div>${legendHtml()}`);
    }

    /* Le focus survit au rendu : même élément (nœud, libellé, action) retrouvé par ses attributs. */
    function focusKey(){
      const a=doc&&doc.activeElement;
      if(!a||!host.contains||!host.contains(a)||!a.getAttribute)return null;
      for(const k of ['data-arch-node','data-arch-conn','data-arch-menu-btn','data-arch-port-source','data-arch-port-target'])if(a.hasAttribute(k))return `[${k}="${cssEsc(a.getAttribute(k))}"]`;
      if(a.hasAttribute('data-arch-act'))return `[data-arch-act="${cssEsc(a.getAttribute('data-arch-act'))}"]`;
      return null;
    }
    const cssEsc=v=>String(v).replace(/["\\]/g,'\\$&');
    function render(){
      if(st.destroyed)return;
      const key=focusKey();
      try{host.innerHTML=html()}
      catch(e){logError('architecture_settings_render_failed',e);st.phase='error';st.error={code:'architecture_settings_render_failed',message:'L’écran n’a pas pu afficher cette réponse : '+(e&&e.message||e)};host.innerHTML=html()}
      if(key&&host.querySelector){const el=host.querySelector(key);if(el&&el.focus)el.focus({preventScroll:true})}
      syncTicker();
    }
    function focus(sel){if(!host.querySelector)return;const el=host.querySelector(sel);if(el&&el.focus)el.focus()}
    function announce(text){st.live=text;const el=host.querySelector&&host.querySelector('[data-arch-live]');if(el)el.textContent=text}
    function syncTicker(){
      const waiting=st.phase==='loading'||st.reloading||st.write||st.layoutSave;
      if(waiting&&ticker==null)ticker=setTimer(tick,1000);
      if(!waiting&&ticker!=null){clearTimer(ticker);ticker=null}
    }
    function tick(){
      if(st.destroyed||!host.querySelectorAll)return;
      for(const el of host.querySelectorAll('[data-arch-since]'))el.textContent=elapsed(Number(el.getAttribute('data-arch-since')))+' s';
    }
    /* Pendant un glisser : seuls le nœud et les liaisons bougent, le reste du DOM (et le focus) reste. */
    function renderEdgesOnly(){
      if(!host.querySelector)return render();
      const e=edgesHtml(),edges=host.querySelector('[data-arch-edges]'),labels=host.querySelector('[data-arch-labels]'),world=host.querySelector('[data-arch-world]');
      if(!edges||!labels||!world)return render();
      edges.innerHTML=e.svg;labels.innerHTML=e.labels;world.style.width=e.w+'px';world.style.height=e.h+'px';
    }

    /* --- lecture ----------------------------------------------------------- */
    async function load(){
      if(st.destroyed)return;
      const first=!st.snapshot;
      if(first){st.phase='loading';st.startedAt=now()}else st.reloading=now();
      render();
      const started=now();
      try{
        const snap=normalizeSnapshot(await withDeadline(adapter.load(),timeoutMs,'lecture de l’architecture'));
        if(st.destroyed)return;
        applySnapshot(snap);st.phase='ready';st.error=null;
        logInfo('architecture_settings.loaded',{revision:snap.revision,nodes:snap.nodes.length,connections:snap.connections.length,ms:now()-started});
        if(first)await loadLayout(true);
      }catch(e){
        if(st.destroyed)return;
        const code=e&&e.code||'architecture_load_failed';
        logError(code,e,{phase:first?'first_load':'reload'});
        if(first){st.phase='error';st.error={code,message:String(e&&e.message||e)}}
        else{
          const followup={text:'Relecture impossible : '+String(e&&e.message||e),code,hint:'L’écran montre la dernière version lue, qui peut être dépassée.'};
          /* Un message déjà affiché (issue inconnue, refus) reste : la relecture ratée s'ajoute dessous. */
          if(st.notice)st.notice={...st.notice,tone:'bad',followup};
          else st.notice={tone:'bad',...followup};
        }
      }finally{st.reloading=null;render()}
    }
    function applySnapshot(snap){
      st.snapshot=snap;auto=autoLayout(snap,columnsFit());
      if(st.selected&&!(st.selected.type==='node'?nodeById(st.selected.id):connById(st.selected.id)))st.selected=null;
      if(st.menu&&!nodeById(st.menu.nodeId))st.menu=null;
      st.confirmRemove=null;
    }
    async function loadLayout(silent){
      if(typeof adapter.loadLayout!=='function'){st.layout={phase:'none',revision:null,positions:{},error:null};return}
      if(!silent){st.layout.phase='loading';render()}
      try{
        const l=await withDeadline(adapter.loadLayout(),timeoutMs,'lecture de la disposition');
        const positions={};
        for(const [id,p] of Object.entries(l&&l.positions||{}))if(p&&Number.isFinite(+p.x)&&Number.isFinite(+p.y))positions[id]={x:Math.max(0,+p.x),y:Math.max(0,+p.y)};
        st.layout={phase:'ok',revision:l&&l.revision!=null?String(l.revision):null,positions,error:null};st.moved={};
      }catch(e){
        const code=e&&e.code||'layout_load_failed';logError(code,e,{phase:'layout'});
        st.layout={phase:'error',revision:null,positions:{},error:{code,message:String(e&&e.message||e)}};
      }finally{if(!silent)render()}
    }

    /* --- écritures de topologie -------------------------------------------- */
    function refuseLocally(c,code,text){
      st.notice={tone:'bad',text,code,target:c.id};logInfo('architecture_settings.refused_locally',{id:c.id,code});render();
    }
    async function write(target,label,run,describeOk){
      if(st.write||st.destroyed)return null;
      st.write={id:target,label,startedAt:now()};st.notice=null;render();
      const base=st.snapshot&&st.snapshot.revision;
      let result=null;
      try{
        result=await withDeadline(run(base),timeoutMs,label);
        if(st.destroyed)return result;
        if(result&&result.ok===true&&result.snapshot){
          applySnapshot(normalizeSnapshot(result.snapshot));
          const text=describeOk();st.notice={tone:'ok',text,target};announce(text);
          logInfo('architecture_settings.write_ok',{target,revision:st.snapshot.revision});
          return result;
        }
        const r=result||{};
        if(r.ok===true){
          /* Accepté sans snapshot : l'écriture a eu lieu, seul l'état affiché manque ; on le relit. */
          logInfo('architecture_settings.write_ok_without_snapshot',{target});
          st.notice={tone:'ok',target,code:'architecture_snapshot_missing',text:'Enregistré, relecture de l’architecture…',
            hint:'Le serveur n’a pas renvoyé l’architecture : l’écran est relu pour montrer l’état réel.'};
          announce(st.notice.text);st.write=null;await load();
          return result;
        }
        const code=r.code||'architecture_write_refused';
        const reason=r.reason||'Refus sans raison donnée.';
        logError(code,new Error(reason),{target,status:r.status||null});
        if(r.snapshot)try{applySnapshot(normalizeSnapshot(r.snapshot))}catch(e){logError('architecture_payload_invalid',e,{target})}
        const stale=r.status===409||code==='architecture_revision_stale';
        st.notice={tone:'bad',target,code,
          text:stale?'L’architecture a changé ailleurs ; rien n’a été appliqué.':`Refusé : ${reason}`,
          hint:stale?'La vue est relue depuis le serveur : vérifiez puis recommencez.':(r.snapshot?'L’écran montre l’état renvoyé par le serveur.':'L’écran est relu depuis le serveur.')};
        announce(st.notice.text);
        if(stale||!r.snapshot){st.write=null;await load()}
        return result;
      }catch(e){
        const code=e&&e.code||'architecture_write_failed';
        logError(code,e,{target});
        st.notice={tone:'bad',target,code,text:(UNKNOWN_OUTCOME.has(code)?'Issue inconnue : ':'Échec : ')+String(e&&e.message||e),
          hint:'L’architecture est relue de force pour ne montrer que l’état réel.'};
        announce(st.notice.text);
        st.write=null;await load();
        return null;
      }finally{st.write=null;render()}
    }
    function toggle(id){
      const c=connById(id);
      if(!c)return Promise.resolve(null);
      if(c.mutability!=='toggleable'){
        if(c.mutability==='governed')return Promise.resolve(refuseLocally(c,'connection_governed','Cette liaison suit un réglage du cerveau : changez-la dans sa fenêtre de configuration.'));
        return Promise.resolve(refuseLocally(c,'connection_locked','Liaison verrouillée : '+(c.locked_reason||'le runtime en a besoin.')));
      }
      const enabled=!effectiveEnabled(c);
      return write(id,enabled?'Activation de la liaison…':'Désactivation de la liaison…',
        base=>adapter.setConnection(id,{base_revision:base,enabled}),
        ()=>{const n=connById(id);const applies=n&&n.pending?n.pending.applies:(n&&n.applies);
          return `Liaison ${enabled?'activée':'désactivée'}${RESTART_WHO[applies]?' : enregistrée, effective '+APPLIES[applies]+'.':applies?', effective '+appliesText(applies)+'.':'.'}`});
    }
    function remove(id){
      const c=connById(id);
      if(!c)return Promise.resolve(null);
      if(c.mutability!=='creatable_removable')return Promise.resolve(refuseLocally(c,c.mutability==='governed'?'connection_governed':'connection_locked','Cette liaison ne peut pas être supprimée : '+(c.locked_reason||(MUTABILITY[c.mutability]||['',''])[1])));
      if(typeof adapter.removeConnection!=='function')return Promise.resolve(refuseLocally(c,'architecture_adapter_missing','Suppression indisponible : l’adaptateur ne la propose pas.'));
      st.confirmRemove=null;
      return write(id,'Suppression de la liaison…',base=>adapter.removeConnection(id,{base_revision:base}),()=>'Liaison supprimée.');
    }
    function create(option){
      const ok=((st.snapshot&&st.snapshot.creatable)||[]).find(o=>o.source.node===option.source.node&&o.source.port===option.source.port&&o.target.node===option.target.node&&o.target.port===option.target.port);
      st.linking=null;
      if(!ok){st.notice={tone:'bad',code:'connection_incompatible',text:'Ces deux ports ne sont pas compatibles selon le runtime : aucune liaison créée.'};render();return Promise.resolve(null)}
      if(typeof adapter.createConnection!=='function'){st.notice={tone:'bad',code:'architecture_adapter_missing',text:'Création indisponible : l’adaptateur ne la propose pas.'};render();return Promise.resolve(null)}
      return write(null,'Création de la liaison…',base=>adapter.createConnection({base_revision:base,source:ok.source,target:ok.target,channel:ok.channel}),()=>'Liaison créée.');
    }
    function setActivation(nodeId,active){
      const n=nodeById(nodeId);
      if(!n||!n.activation.mutable||typeof adapter.setNodeActivation!=='function')return Promise.resolve(null);
      return write(nodeId,active?'Activation du module…':'Désactivation du module…',base=>adapter.setNodeActivation(nodeId,{base_revision:base,active}),()=>`${n.label} ${active?'activé':'désactivé'}.`);
    }

    /* --- disposition (UI seule) ---------------------------------------------- */
    function moveNode(id,x,y){
      if(!nodeById(id))return;
      st.moved[id]={x:Math.max(0,Math.round(x)),y:Math.max(0,Math.round(y))};
      if(host.querySelector){const el=host.querySelector(`[data-arch-node="${cssEsc(id)}"]`);if(el){el.style.left=st.moved[id].x+'px';el.style.top=st.moved[id].y+'px'}}
      renderEdgesOnly();
    }
    async function saveLayout(){
      if(layoutTimer!=null){clearTimeout(layoutTimer);layoutTimer=null}
      if(!Object.keys(st.moved).length||st.layoutSave||st.destroyed)return null;
      if(typeof adapter.saveLayout!=='function'||st.layout.phase==='error'||st.layout.phase==='none'){
        st.layoutNotice={tone:'bad',text:'Disposition non enregistrée : '+(st.layout.phase==='error'?'disposition enregistrée illisible.':'aucun stockage de disposition.')};render();return null;
      }
      const positions={...st.layout.positions,...st.moved};
      st.layoutSave=now();st.layoutNotice=null;render();
      try{
        const r=await withDeadline(adapter.saveLayout({base_revision:st.layout.revision,positions}),timeoutMs,'enregistrement de la disposition');
        if(st.destroyed)return r;
        if(r&&r.ok===true){
          const l=r.layout||{};
          st.layout={phase:'ok',revision:l.revision!=null?String(l.revision):st.layout.revision,positions:l.positions||positions,error:null};st.moved={};
          st.layoutNotice={tone:'ok',text:'Disposition enregistrée (affichage seulement, l’architecture est inchangée).'};
          logInfo('architecture_settings.layout_saved',{revision:st.layout.revision});
        }else{
          const code=r&&r.code||'layout_save_refused';logError(code,new Error(r&&r.reason||'refus'),{status:r&&r.status||null});
          const stale=(r&&r.status===409)||code==='layout_revision_stale';
          st.layoutSave=null;
          if(stale){await loadLayout(true);st.layoutNotice={tone:'bad',code,text:'Disposition modifiée ailleurs : relue, votre déplacement n’est pas enregistré.'}}
          else st.layoutNotice={tone:'bad',code,text:'Disposition non enregistrée : '+(r&&r.reason||'refus du serveur')};
        }
        return r;
      }catch(e){
        const code=e&&e.code||'layout_save_failed';logError(code,e,{phase:'layout_save'});
        st.layoutNotice={tone:'bad',code,text:'Disposition non enregistrée : '+String(e&&e.message||e)};return null;
      }finally{st.layoutSave=null;render()}
    }
    function scheduleLayoutSave(){if(layoutTimer!=null)clearTimeout(layoutTimer);layoutTimer=setTimeout(()=>{layoutTimer=null;saveLayout()},650)}

    /* --- sélection, menu, configuration -------------------------------------- */
    function select(type,id,{focusInspector}={}){
      st.selected=type&&id?{type,id}:null;st.confirmRemove=null;
      if(st.notice&&st.notice.target&&st.notice.target!==id)st.notice=null;
      render();
      if(focusInspector)focus(`#${uid}-insp`);
    }
    function openMenu(nodeId,at,opener){
      const n=nodeById(nodeId);if(!n||n.kind!=='brain')return;
      const p=posOf(nodeId);
      st.menu={nodeId,opener:opener==='button'?'button':'node',x:at&&Number.isFinite(at.x)?at.x:p.x+NODE_W-28,y:at&&Number.isFinite(at.y)?at.y:p.y+40};
      render();focus('.arch-menu [role="menuitem"]');
    }
    function closeMenu(returnFocus){
      const id=st.menu&&st.menu.nodeId,opener=st.menu&&st.menu.opener;st.menu=null;render();
      /* Le focus revient à ce qui a ouvert le menu : le bouton « … » ou le nœud. */
      if(returnFocus&&id)focus(opener==='button'?`[data-arch-menu-btn="${cssEsc(id)}"]`:`[data-arch-node="${cssEsc(id)}"]`);
    }
    function configure(nodeId,detail){
      /* `opener` (`node` | `button`, menu seulement) : la fenêtre du cerveau y rend le focus à sa fermeture. */
      const d={nodeId,field:detail&&detail.field||null,source:detail&&detail.source||'menu',opener:detail&&detail.opener||null};
      logInfo('architecture_settings.configure_brain',d);
      try{if(typeof opts.onConfigureBrain==='function')opts.onConfigureBrain(nodeId,d)}
      catch(e){logError('architecture_configure_failed',e,d);st.notice={tone:'bad',code:'architecture_configure_failed',text:'La fenêtre du cerveau n’a pas pu s’ouvrir : '+String(e&&e.message||e)};render()}
      try{
        const Ev=root.CustomEvent;
        if(typeof Ev==='function'&&host.dispatchEvent)host.dispatchEvent(new Ev('architecture:configure-brain',{bubbles:true,detail:d}));
      }catch(e){logError('architecture_configure_event_failed',e,d)}
      return d;
    }
    function menuAction(action){
      const id=st.menu&&st.menu.nodeId,opener=st.menu&&st.menu.opener;if(!id)return;
      st.menu=null;
      if(action==='configure'){render();configure(id,{source:'menu',opener})}
      else if(action==='inspect')select('node',id,{focusInspector:true});
      else if(action==='activate'||action==='deactivate')setActivation(id,action==='activate');
    }

    /* --- événements (délégués sur l'hôte) -------------------------------------- */
    const on=(type,fn)=>{if(host.addEventListener)host.addEventListener(type,fn);return ()=>host.removeEventListener&&host.removeEventListener(type,fn)};
    const portKey=v=>String(v||'').split('/').map(decodeURIComponent);
    const closest=(t,sel)=>t&&t.closest?t.closest(sel):null;
    const offs=[];
    function onClick(ev){
      /* Le clic qui suit un glisser n'est pas une sélection. */
      if(Date.now()<suppressClickUntil){suppressClickUntil=0;ev.preventDefault&&ev.preventDefault();return}
      const t=ev.target;let el;
      if((el=closest(t,'[data-arch-menu]')))return menuAction(el.getAttribute('data-arch-menu'));
      if(st.menu&&!closest(t,'.arch-menu'))closeMenu(false);
      if((el=closest(t,'[data-arch-menu-btn]'))){ev.stopPropagation&&ev.stopPropagation();return openMenu(el.getAttribute('data-arch-menu-btn'),null,'button')}
      if((el=closest(t,'[data-arch-port-source]'))){const [node,port]=portKey(el.getAttribute('data-arch-port-source'));st.linking={node,port};render();focus('[data-arch-port-target]');return}
      if((el=closest(t,'[data-arch-port-target]'))){const [node,port]=portKey(el.getAttribute('data-arch-port-target'));const L=st.linking;
        return create({source:{node:L.node,port:L.port},target:{node,port}})}
      if((el=closest(t,'[data-arch-create]'))){const o=((st.snapshot&&st.snapshot.creatable)||[])[Number(el.getAttribute('data-arch-create'))];if(o)return create({source:o.source,target:o.target});return}
      if((el=closest(t,'[data-arch-focus-conn]'))){const id=el.getAttribute('data-arch-focus-conn');select('connection',id);focus(`.arch-label[data-arch-conn="${cssEsc(id)}"]`);return}
      if((el=closest(t,'[data-arch-act]'))){
        const act=el.getAttribute('data-arch-act'),id=el.getAttribute('data-arch-id');
        if(act==='reload')return load();
        if(act==='layout-retry')return loadLayout(false);
        if(act==='toggle')return toggle(id);
        if(act==='remove'){if(st.confirmRemove===id)return remove(id);st.confirmRemove=id;render();return}
        if(act==='remove-cancel'){st.confirmRemove=null;render();return}
        if(act==='close'){const s=st.selected;select(null);if(s)focus(s.type==='node'?`[data-arch-node="${cssEsc(s.id)}"]`:`.arch-label[data-arch-conn="${cssEsc(s.id)}"]`);return}
        if(act==='configure')return configure(id,{source:'inspector'});
        if(act==='governed'){const c=connById(id),gb=c&&c.governed_by||{};return configure(gb.node,{field:gb.field||null,source:'governed'})}
        if(act==='link-cancel'){st.linking=null;render();return}
        return;
      }
      /* `detail === 0` : clic produit par Entrée/Espace, le focus suit dans l'inspecteur. */
      if((el=closest(t,'[data-arch-conn]')))return select('connection',el.getAttribute('data-arch-conn'),{focusInspector:ev.detail===0&&!!closest(t,'.arch-label')});
      if((el=closest(t,'[data-arch-node]')))return select('node',el.getAttribute('data-arch-node'));
    }
    function onContextMenu(ev){
      if(closest(ev.target,'.arch-menu')){ev.preventDefault&&ev.preventDefault();return}
      const el=closest(ev.target,'[data-arch-node]');
      const n=el&&nodeById(el.getAttribute('data-arch-node'));
      if(!n||n.kind!=='brain'){if(st.menu)closeMenu(false);return}
      ev.preventDefault&&ev.preventDefault();
      const world=host.querySelector&&host.querySelector('[data-arch-world]');
      const r=world&&world.getBoundingClientRect?world.getBoundingClientRect():null;
      openMenu(n.id,r?{x:ev.clientX-r.left,y:ev.clientY-r.top}:null);
    }
    function onKeyDown(ev){
      const t=ev.target,k=ev.key;
      const menu=closest(t,'.arch-menu');
      if(menu){
        const items=[...menu.querySelectorAll('[role="menuitem"]')],i=items.indexOf(t);
        if(k==='ArrowDown'||k==='ArrowUp'){ev.preventDefault();const n=items.length;if(n)items[(i+(k==='ArrowDown'?1:-1)+n)%n].focus();return}
        if(k==='Home'||k==='End'){ev.preventDefault();if(items.length)items[k==='Home'?0:items.length-1].focus();return}
        if(k==='Escape'){ev.preventDefault();closeMenu(true);return}
        if(k==='Tab'){closeMenu(true);ev.preventDefault();return}
        return;
      }
      if(k==='Escape'){
        if(st.menu){ev.preventDefault();closeMenu(true);return}
        if(st.linking){ev.preventDefault();const L=st.linking;st.linking=null;render();focus(`[data-arch-node="${cssEsc(L.node)}"]`);return}
        if(st.selected){ev.preventDefault();const s=st.selected;select(null);focus(s.type==='node'?`[data-arch-node="${cssEsc(s.id)}"]`:`.arch-label[data-arch-conn="${cssEsc(s.id)}"]`);return}
        return;
      }
      const nodeEl=t&&t.getAttribute&&t.hasAttribute('data-arch-node')?t:null;
      if(!nodeEl)return;
      const id=nodeEl.getAttribute('data-arch-node');
      if(k==='ContextMenu'||(k==='F10'&&ev.shiftKey)){ev.preventDefault();openMenu(id);return}
      if(k==='Enter'||k===' '){ev.preventDefault();select('node',id,{focusInspector:true});return}
      const dir={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[k];
      if(dir&&ev.shiftKey){ev.preventDefault();const p=posOf(id);moveNode(id,p.x+dir[0]*LAYOUT_STEP,p.y+dir[1]*LAYOUT_STEP);announce(`${nodeLabel(id)} déplacé`);scheduleLayoutSave()}
    }
    function onPointerDown(ev){
      if(ev.button!==0)return;
      const el=closest(ev.target,'[data-arch-node]');
      if(!el||closest(ev.target,'button'))return;
      const id=el.getAttribute('data-arch-node'),p=posOf(id);
      drag={id,el,startX:ev.clientX,startY:ev.clientY,x:p.x,y:p.y,moved:false,pointer:ev.pointerId};
    }
    function onPointerMove(ev){
      if(!drag||ev.pointerId!==drag.pointer)return;
      const dx=ev.clientX-drag.startX,dy=ev.clientY-drag.startY;
      if(!drag.moved&&Math.hypot(dx,dy)<4)return;
      if(!drag.moved){drag.moved=true;try{drag.el.setPointerCapture&&drag.el.setPointerCapture(ev.pointerId)}catch(_e){/* intentionnel : capture refusée, le glisser marche tant que le pointeur reste sur la page */}
        drag.el.classList&&drag.el.classList.add('dragging')}
      ev.preventDefault&&ev.preventDefault();
      moveNode(drag.id,drag.x+dx,drag.y+dy);
    }
    function onPointerUp(ev){
      if(!drag||ev.pointerId!==drag.pointer)return;
      const d=drag;drag=null;
      if(d.moved){d.el.classList&&d.el.classList.remove('dragging');suppressClickUntil=Date.now()+400;announce(`${nodeLabel(d.id)} déplacé`);saveLayout()}
    }

    function ensureStyle(){
      if(!doc||!doc.head||doc.getElementById(STYLE_ID))return;
      const s=doc.createElement('style');s.id=STYLE_ID;s.textContent=STYLE;doc.head.appendChild(s);
    }
    function destroy(){
      st.destroyed=true;
      if(ticker!=null){clearTimer(ticker);ticker=null}
      if(layoutTimer!=null){clearTimeout(layoutTimer);layoutTimer=null}
      while(offs.length)offs.pop()();
      host.innerHTML='';
    }

    ensureStyle();
    /* Redimensionnement : la disposition automatique suit le nombre de colonnes qui tiennent (les positions
       enregistrées ne bougent pas). Rien pendant un glisser. */
    let fitCols=null;
    if(typeof root.ResizeObserver==='function'){
      const ro=new root.ResizeObserver(()=>{
        if(st.destroyed||drag||!st.snapshot)return;
        const cols=columnsFit();if(cols===fitCols)return;
        fitCols=cols;auto=autoLayout(st.snapshot,cols);render();
      });
      ro.observe(host);offs.push(()=>ro.disconnect());
    }
    /* Un clic hors de l'onglet ferme le menu contextuel. */
    if(doc&&doc.addEventListener){
      const outside=ev=>{if(st.menu&&host.contains&&!host.contains(ev.target))closeMenu(false)};
      doc.addEventListener('pointerdown',outside,true);offs.push(()=>doc.removeEventListener('pointerdown',outside,true));
    }
    offs.push(on('click',onClick),on('contextmenu',onContextMenu),on('keydown',onKeyDown),on('pointerdown',onPointerDown),on('pointermove',onPointerMove),on('pointerup',onPointerUp),on('pointercancel',onPointerUp));
    host.setAttribute&&host.setAttribute('data-architecture-settings-host','1');
    const ready=load();
    return {ready,load,loadLayout,render,select,toggle,remove,create,setActivation,moveNode,saveLayout,openMenu,closeMenu,menuAction,configure,destroy,state:st};
  }

  /* --- adaptateurs ----------------------------------------------------------- */

  /* Adaptateur de démonstration et de test : simule le serveur du contrat 11 sur une copie du snapshot
     (révision, verrous, gouvernance, application différée, création depuis `creatable`, disposition révisée).
     Il ne sert JAMAIS en production : la Slice 07 monte `createHttpAdapter`. */
  function createFixtureAdapter(snapshot,options){
    const o=options||{};
    let snap=clone(snapshot),n=1,layout={revision:o.layout&&o.layout.revision||null,positions:clone(o.layout&&o.layout.positions||{})},ln=1;
    const calls=[];
    const delay=()=>o.latencyMs>0?new Promise(r=>setTimeout(r,o.latencyMs)):Promise.resolve();
    const bump=()=>{snap.revision='f-'+(n++)};
    const fail=(status,code,reason)=>({ok:false,status,code,reason,snapshot:clone(snap)});
    const stale=base=>base!==snap.revision?fail(409,'architecture_revision_stale','La révision '+base+' est dépassée.'):null;
    return {
      calls,
      get snapshot(){return clone(snap)},
      async load(){calls.push(['load']);await delay();return clone(snap)},
      async setConnection(id,{base_revision,enabled}){
        calls.push(['setConnection',id,{base_revision,enabled}]);await delay();
        const c=snap.connections.find(x=>x.id===id);
        if(!c)return fail(422,'connection_unknown','Liaison inconnue.');
        const s=stale(base_revision);if(s)return s;
        if(c.mutability==='required_locked')return fail(423,'connection_locked',c.locked_reason||'Liaison verrouillée.');
        if(c.mutability==='governed')return fail(422,'connection_governed','Réglée dans la fenêtre du cerveau.');
        if(c.applies==='core_restart'||c.applies==='voice_restart')c.pending=enabled===c.enabled?null:{enabled:!!enabled,applies:c.applies};
        else{c.enabled=!!enabled;c.pending=null}
        bump();return {ok:true,snapshot:clone(snap)};
      },
      async createConnection({base_revision,source,target,channel}){
        calls.push(['createConnection',{base_revision,source,target,channel}]);await delay();
        const s=stale(base_revision);if(s)return s;
        const list=snap.creatable||[];
        const i=list.findIndex(x=>x.source.node===source.node&&x.source.port===source.port&&x.target.node===target.node&&x.target.port===target.port&&x.channel===channel);
        if(i<0)return fail(422,'connection_incompatible','Ports incompatibles.');
        const opt=list.splice(i,1)[0];
        snap.connections.push({id:`${source.node}.${source.port}->${target.node}.${target.port}`,source,target,channel,purpose:opt.purpose||'',enabled:true,
          mutability:'creatable_removable',locked_reason:'',impact_when_disabled:opt.impact_when_disabled||'',applies:opt.applies||'next_turn',pending:null,governed_by:null,binding:opt.binding||''});
        bump();return {ok:true,snapshot:clone(snap)};
      },
      async removeConnection(id,{base_revision}){
        calls.push(['removeConnection',id,{base_revision}]);await delay();
        const c=snap.connections.find(x=>x.id===id);
        if(!c)return fail(422,'connection_unknown','Liaison inconnue.');
        const s=stale(base_revision);if(s)return s;
        if(c.mutability!=='creatable_removable')return fail(423,'connection_locked',c.locked_reason||'Liaison non supprimable.');
        snap.connections=snap.connections.filter(x=>x.id!==id);
        (snap.creatable=snap.creatable||[]).push({source:c.source,target:c.target,channel:c.channel,purpose:c.purpose});
        bump();return {ok:true,snapshot:clone(snap)};
      },
      async loadLayout(){calls.push(['loadLayout']);await delay();return clone(layout)},
      async saveLayout({base_revision,positions}){
        calls.push(['saveLayout',{base_revision,positions:clone(positions)}]);await delay();
        if(base_revision!==layout.revision)return {ok:false,status:409,code:'layout_revision_stale',reason:'Disposition modifiée ailleurs.',layout:clone(layout)};
        layout={revision:'l-'+(ln++),positions:clone(positions)};return {ok:true,layout:clone(layout)};
      },
    };
  }

  /* Transport HTTP des routes du contrat 11 (montées par la Slice 07). Les refus du serveur deviennent des
     résultats `{ok:false,…}` ; seuls les échecs de transport lèvent (issue inconnue). */
  function createHttpAdapter(options){
    const o=options||{},base=o.base||'/api/architecture',timeoutMs=Number(o.timeoutMs)>0?Number(o.timeoutMs):DEFAULT_TIMEOUT_MS;
    const fetchImpl=o.fetch||(root.fetch&&root.fetch.bind(root));
    async function call(path,init){
      const ctl=typeof root.AbortController==='function'?new root.AbortController():null;
      const timer=ctl?setTimeout(()=>ctl.abort(),timeoutMs):null;
      let r;
      try{r=await fetchImpl(base+path,{...(init||{}),headers:{'Content-Type':'application/json',...(init&&init.headers||{})},signal:ctl?ctl.signal:undefined})}
      catch(e){
        if(e&&e.name==='AbortError')throw codedError('architecture_timeout',`Pas de réponse du Control Center après ${Math.round(timeoutMs/1000)} s.`);
        throw codedError('architecture_unreachable','Control Center injoignable : '+(e&&e.message||e));
      }finally{if(timer!=null)clearTimeout(timer)}
      const text=await r.text();let body={};
      try{body=text?JSON.parse(text):{}}catch(_e){body={ok:false,code:'architecture_payload_invalid',reason:'Réponse non JSON : '+text.slice(0,160)}}
      const envelope=body&&typeof body.error==='object'&&body.error?body.error:null;
      const code=body.code||(envelope&&envelope.code)||(r.headers&&r.headers.get&&r.headers.get('X-Jarvis-Error-Code'))||'';
      const reason=body.reason||(envelope&&envelope.message)||(typeof body.error==='string'?body.error:'')||('HTTP '+r.status);
      return {status:r.status,ok:r.ok&&body.ok!==false,body,code,reason};
    }
    const result=x=>x.ok?{ok:true,snapshot:x.body.snapshot||null}:{ok:false,status:x.status,code:x.code||'architecture_write_refused',reason:x.reason,snapshot:x.body&&x.body.snapshot||null};
    const json=v=>JSON.stringify(v);
    return {
      async load(){const x=await call('',{method:'GET'});if(!x.ok)throw codedError(x.code||'architecture_load_failed',x.reason,{status:x.status});return x.body.snapshot||x.body},
      async setConnection(id,b){return result(await call('/connections/'+encodeURIComponent(id),{method:'POST',body:json(b)}))},
      async createConnection(b){return result(await call('/connections',{method:'POST',body:json(b)}))},
      async removeConnection(id,{base_revision}){return result(await call('/connections/'+encodeURIComponent(id)+'?base_revision='+encodeURIComponent(base_revision??''),{method:'DELETE'}))},
      async loadLayout(){const x=await call('/layout',{method:'GET'});if(!x.ok)throw codedError(x.code||'layout_load_failed',x.reason,{status:x.status});return x.body.layout||x.body},
      async saveLayout(b){const x=await call('/layout',{method:'PUT',body:json(b)});
        return x.ok?{ok:true,layout:x.body.layout||x.body}:{ok:false,status:x.status,code:x.code||'layout_save_refused',reason:x.reason,layout:x.body&&x.body.layout||null}},
    };
  }

  const STYLE=`
.arch{--arch-ink:var(--set-ink,var(--text));--arch-ink-2:var(--set-ink-2,var(--muted));--arch-ink-3:var(--muted);--arch-hair:var(--set-hair-2,var(--line));
  --arch-glass:var(--shell-glass-strong,var(--panel));--arch-r:12px;--arch-u:8px;
  --ch-audio:var(--role-accent-cyan);--ch-request:var(--accent);--ch-response:var(--role-accent-rose);--ch-speech:var(--role-accent-rose);
  --ch-tool_call:var(--role-accent-teal);--ch-event:var(--role-accent-violet);--ch-other:var(--role-accent-slate);
  container-type:inline-size;display:grid;gap:calc(var(--arch-u)*1.5);color:var(--arch-ink);font-size:13px;line-height:1.5}
.arch *{box-sizing:border-box}
.arch code{font-size:11.5px;color:var(--arch-ink-2)}
.arch-g{width:16px;height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.arch-g-sm{width:13px;height:13px}.arch-g-lg{width:22px;height:22px}
.arch-hint{color:var(--arch-ink-2);font-size:12px}
.arch-sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.arch-bar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:var(--arch-u) calc(var(--arch-u)*2)}
.arch-voice{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;padding:8px 14px;border:1px solid var(--arch-hair);border-radius:999px;background:var(--arch-glass)}
.arch-voice-k{color:var(--arch-ink-2);font-size:12px}.arch-voice-v{font-weight:600}
.arch-status{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px}
.arch-layout-note{font-size:12px;color:var(--arch-ink-2)}.arch-layout-note.bad{color:var(--danger)}.arch-layout-note.ok{color:var(--ok)}
.arch-tag{display:inline-flex;align-items:center;gap:4px;padding:1px 8px;border:1px solid var(--arch-hair);border-radius:999px;font-size:11px;color:var(--arch-ink-2);white-space:nowrap}
.arch-tag.ok{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 45%,transparent)}
.arch-tag.ch{color:var(--arch-ink)}
.arch-btn{display:inline-flex;align-items:center;gap:7px;min-height:34px;padding:6px 14px;border-radius:10px;border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);
  background:color-mix(in srgb,var(--accent) 10%,transparent);color:var(--arch-ink);font:inherit;cursor:pointer;transition:background .15s,border-color .15s}
.arch-btn:hover:not(:disabled){background:color-mix(in srgb,var(--accent) 18%,transparent)}
.arch-btn.ghost{border-color:var(--arch-hair);background:transparent;color:var(--arch-ink-2)}
.arch-btn.danger{border-color:color-mix(in srgb,var(--danger) 60%,transparent);background:color-mix(in srgb,var(--danger) 12%,transparent)}
.arch-btn:disabled,.arch-switch:disabled{opacity:.5;cursor:not-allowed}
.arch-linkbtn{background:none;border:0;padding:0;color:var(--accent);font:inherit;font-size:12px;cursor:pointer;text-decoration:underline;text-underline-offset:3px}
.arch-icon-btn{display:grid;place-items:center;width:32px;height:32px;border-radius:8px;border:1px solid transparent;background:none;color:var(--arch-ink-2);cursor:pointer}
.arch-icon-btn:hover{border-color:var(--arch-hair);color:var(--arch-ink)}
.arch :focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.arch-main{display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,340px);gap:calc(var(--arch-u)*1.5);align-items:start}
@container (max-width:860px){.arch-main{grid-template-columns:minmax(0,1fr)}}
.arch-canvas{position:relative;min-height:480px;max-height:min(72vh,720px);overflow:auto;border:1px solid var(--arch-hair);border-radius:var(--arch-r);
  background:radial-gradient(circle at 1px 1px,color-mix(in srgb,var(--arch-ink-3) 22%,transparent) 1px,transparent 1.4px) 0 0/24px 24px,
    linear-gradient(180deg,color-mix(in srgb,var(--accent) 4%,transparent),transparent 60%),var(--arch-glass);overscroll-behavior:contain}
.arch-canvas-skel{display:grid;place-items:center}
.arch-centered{display:grid;justify-items:center;gap:8px;max-width:52ch;padding:32px;text-align:center}
.arch-centered h3{margin:0;font-size:16px}
.arch-error h3{color:var(--danger)}
.arch-skel{display:block;height:14px;border-radius:7px;background:color-mix(in srgb,var(--arch-ink-3) 18%,transparent)}.arch-skel.w1{width:260px}
.arch-world{position:relative;min-width:100%;min-height:100%}
.arch-edges{position:absolute;inset:0 auto auto 0;overflow:visible;pointer-events:none}
.arch-edge{fill:none;stroke-width:2;stroke-linecap:round}
.arch-edge.ch-audio,.arch-casing.ch-audio,.arch-mk.ch-audio{stroke:var(--ch-audio);fill:var(--ch-audio)}
.arch-edge.ch-request,.arch-casing.ch-request,.arch-mk.ch-request{stroke:var(--ch-request);fill:var(--ch-request)}
.arch-edge.ch-response,.arch-casing.ch-response,.arch-mk.ch-response{stroke:var(--ch-response);fill:var(--ch-response)}
.arch-edge.ch-speech,.arch-casing.ch-speech,.arch-mk.ch-speech{stroke:var(--ch-speech);fill:var(--ch-speech)}
.arch-edge.ch-tool_call,.arch-casing.ch-tool_call,.arch-mk.ch-tool_call{stroke:var(--ch-tool_call);fill:var(--ch-tool_call)}
.arch-edge.ch-event,.arch-casing.ch-event,.arch-mk.ch-event{stroke:var(--ch-event);fill:var(--ch-event)}
.arch-edge.ch-other,.arch-casing.ch-other,.arch-mk.ch-other{stroke:var(--ch-other);fill:var(--ch-other)}
.arch-edge{fill:none!important}.arch-mk{stroke:none!important}
.arch-casing{fill:none!important;stroke-width:8;opacity:.16;stroke-linecap:round}
.arch-edge.m-required_locked{stroke-width:3}
.arch-edge.m-toggleable.on{stroke-dasharray:none}
.arch-edge.off{stroke-dasharray:6 6;opacity:.45}
.arch-edge.m-creatable_removable{stroke-dasharray:12 4 2 4}
.arch-edge.m-creatable_removable.off{stroke-dasharray:12 4 2 4;opacity:.45}
.arch-edge.m-governed{stroke-dasharray:.5 6;stroke-width:2.6}
.arch-edge.sel{stroke-width:4.2}
.arch-hit{fill:none;stroke:transparent;stroke-width:16;pointer-events:stroke;cursor:pointer}
.arch-node{position:absolute;width:${NODE_W}px;height:${NODE_H}px;display:grid;grid-template-rows:auto auto 1fr;gap:6px;padding:12px 12px 10px;
  border-radius:var(--arch-r);border:1px solid color-mix(in srgb,var(--arch-accent) 55%,transparent);
  background:linear-gradient(160deg,color-mix(in srgb,var(--arch-accent) 13%,transparent),transparent 70%),var(--arch-glass);
  box-shadow:0 10px 28px -12px rgba(0,0,0,.7),inset 0 1px 0 color-mix(in srgb,var(--arch-accent) 20%,transparent);
  backdrop-filter:blur(10px);cursor:grab;touch-action:none;user-select:none;transition:box-shadow .18s,border-color .18s}
.arch-node:hover{border-color:color-mix(in srgb,var(--arch-accent) 80%,transparent)}
.arch-node.sel{border-color:var(--arch-accent);box-shadow:0 0 0 1px var(--arch-accent),0 14px 34px -12px color-mix(in srgb,var(--arch-accent) 55%,transparent)}
.arch-node.dragging{cursor:grabbing;box-shadow:0 22px 40px -14px rgba(0,0,0,.85),0 0 0 1px var(--arch-accent);z-index:3}
.arch-node.s-inactive,.arch-node.s-unavailable{border-style:dashed}
.arch-node.s-inactive .arch-tile,.arch-node.s-unavailable .arch-tile{opacity:.55}
.arch-node-head{display:flex;align-items:center;gap:10px;min-width:0}
.arch-tile{display:grid;place-items:center;width:38px;height:38px;flex:none;border-radius:50%;color:var(--arch-accent);
  border:1px solid color-mix(in srgb,var(--arch-accent) 60%,transparent);background:color-mix(in srgb,var(--arch-accent) 12%,transparent)}
.arch-node-text{display:grid;min-width:0;flex:1}
.arch-node-name{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.arch-node-sub{font-size:11.5px;color:var(--arch-ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.arch-more{display:grid;place-items:center;width:30px;height:30px;flex:none;border-radius:8px;border:1px solid var(--arch-hair);background:transparent;color:var(--arch-ink-2);cursor:pointer}
.arch-more:hover,.arch-more[aria-expanded="true"]{color:var(--arch-ink);border-color:var(--arch-accent)}
.arch-node-meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.arch-state{display:inline-flex;align-items:center;gap:6px;font-size:12px}
.arch-dot{width:8px;height:8px;border-radius:50%;flex:none}
.arch-state.ok .arch-dot{background:var(--ok);box-shadow:0 0 6px var(--ok)}
.arch-state.off .arch-dot{border:1.5px solid var(--arch-ink-2)}
.arch-state.shadow .arch-dot{background:linear-gradient(90deg,var(--warn) 50%,transparent 50%);border:1.5px solid var(--warn)}
.arch-state.bad{color:var(--danger)}.arch-state.bad .arch-dot{background:var(--danger);border-radius:1px;transform:rotate(45deg)}
.arch-ports{display:flex;flex-wrap:wrap;gap:4px;align-content:end;overflow:hidden;max-height:44px}
.arch-port{display:inline-flex;align-items:center;gap:3px;padding:0 6px;height:20px;border-radius:5px;border:1px solid var(--arch-hair);font-size:10.5px;color:var(--arch-ink-2);white-space:nowrap;background:transparent;font-family:inherit}
.arch-port-dir{width:0;height:0;border:4px solid transparent}
.arch-port[data-dir="in"] .arch-port-dir{border-right-color:currentColor;margin-left:-4px}
.arch-port[data-dir="out"] .arch-port-dir{border-left-color:currentColor;margin-right:-4px;order:2}
.arch-port.source,.arch-port.target{cursor:pointer;color:var(--arch-ink);border-color:var(--accent)}
.arch-port.target{background:color-mix(in srgb,var(--accent) 22%,transparent);animation:archPulse 1.6s ease-in-out infinite}
.arch-port.linking{border-style:dashed;color:var(--accent)}
@keyframes archPulse{50%{box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 25%,transparent)}}
.arch-labels{position:absolute;inset:0;pointer-events:none}
.arch-label{position:absolute;transform:translate(-50%,-50%);pointer-events:auto;display:inline-flex;align-items:center;gap:5px;height:24px;padding:0 9px;border-radius:999px;
  border:1px solid var(--arch-hair);background:var(--arch-glass);color:var(--arch-ink);font:inherit;font-size:11.5px;cursor:pointer;white-space:nowrap;backdrop-filter:blur(6px);z-index:2}
.arch-label.ch-audio{border-color:color-mix(in srgb,var(--ch-audio) 55%,transparent)}
.arch-label.ch-request{border-color:color-mix(in srgb,var(--ch-request) 55%,transparent)}
.arch-label.ch-speech,.arch-label.ch-response{border-color:color-mix(in srgb,var(--ch-speech) 55%,transparent)}
.arch-label.ch-tool_call{border-color:color-mix(in srgb,var(--ch-tool_call) 55%,transparent)}
.arch-label.ch-event{border-color:color-mix(in srgb,var(--ch-event) 55%,transparent)}
.arch-label.off{color:var(--arch-ink-2);border-style:dashed}
.arch-label.m-governed{border-style:dotted}
.arch-label.sel{box-shadow:0 0 0 2px var(--accent)}
.arch-pending-g{color:var(--warn)}
.arch-menu{position:absolute;z-index:5;min-width:200px;display:grid;padding:6px;border-radius:10px;border:1px solid var(--arch-hair);background:var(--solid,var(--arch-glass));
  box-shadow:0 18px 40px -12px rgba(0,0,0,.85)}
.arch-menu-item{display:flex;align-items:center;gap:9px;min-height:34px;padding:6px 10px;border:0;border-radius:7px;background:none;color:var(--arch-ink);font:inherit;text-align:left;cursor:pointer}
.arch-menu-item:hover,.arch-menu-item:focus-visible{background:color-mix(in srgb,var(--accent) 14%,transparent);outline:none}
.arch-menu-note{display:flex;gap:6px;align-items:flex-start;margin:4px 0 0;padding:6px 10px 4px;border-top:1px solid var(--arch-hair);font-size:11.5px;color:var(--arch-ink-2);max-width:260px}
.arch-linking{position:sticky;top:8px;left:8px;z-index:4;display:inline-flex;flex-wrap:wrap;align-items:center;gap:8px;margin:8px;padding:6px 12px;border-radius:999px;
  border:1px solid var(--accent);background:var(--solid,var(--arch-glass));font-size:12px}
.arch-inspector{display:grid;gap:10px;align-content:start;min-height:200px;padding:16px;border:1px solid var(--arch-hair);border-radius:var(--arch-r);background:var(--arch-glass);backdrop-filter:blur(10px)}
.arch-insp-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
.arch-inspector h3{margin:0;font-size:15px;line-height:1.35}
.arch-inspector h3:focus{outline:none}
.arch-arrow{color:var(--accent)}
.arch-purpose{margin:0;color:var(--arch-ink);max-width:60ch}
.arch-insp-tags{display:flex;flex-wrap:wrap;gap:6px}
.arch-facts{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;margin:0;font-size:12.5px}
.arch-facts dt{color:var(--arch-ink-2)}.arch-facts dd{margin:0;min-width:0;overflow-wrap:anywhere}
.arch-insp-list h4{margin:4px 0;font-size:12px;font-weight:600;color:var(--arch-ink-2)}
.arch-insp-list ul{margin:0;padding:0;list-style:none;display:grid;gap:4px}
.arch-insp-empty p{margin:6px 0 0}
.arch-actions{display:flex;flex-wrap:wrap;gap:8px}
.arch-switch{display:inline-flex;align-items:center;gap:10px;min-height:38px;padding:6px 12px 6px 8px;border-radius:10px;border:1px solid var(--arch-hair);background:transparent;color:var(--arch-ink);font:inherit;cursor:pointer;text-align:left}
.arch-switch .arch-hint{margin-left:4px}
.arch-switch-track{position:relative;width:40px;height:22px;border-radius:11px;border:1.5px solid var(--arch-ink-2);flex:none;transition:background .18s,border-color .18s}
.arch-switch-knob{position:absolute;top:3px;left:3px;width:13px;height:13px;border-radius:50%;background:var(--arch-ink-2);transition:transform .18s}
.arch-switch[aria-checked="true"] .arch-switch-track{background:color-mix(in srgb,var(--accent) 35%,transparent);border-color:var(--accent)}
.arch-switch[aria-checked="true"] .arch-switch-knob{transform:translateX(18px);background:var(--accent)}
.arch-notice{display:flex;gap:10px;align-items:flex-start;padding:10px 12px;border-radius:10px;border:1px solid var(--arch-hair);background:color-mix(in srgb,var(--arch-ink-3) 8%,transparent);font-size:12.5px}
.arch-notice p{margin:0}.arch-notice .arch-hint{margin-top:3px}
.arch-notice.bad{border-color:color-mix(in srgb,var(--danger) 55%,transparent);background:color-mix(in srgb,var(--danger) 9%,transparent)}
.arch-notice.bad .arch-notice-g{color:var(--danger)}
.arch-notice.ok{border-color:color-mix(in srgb,var(--ok) 45%,transparent);background:color-mix(in srgb,var(--ok) 7%,transparent)}
.arch-notice.ok .arch-notice-g{color:var(--ok)}
.arch-notice.warn{border-color:color-mix(in srgb,var(--warn) 50%,transparent);background:color-mix(in srgb,var(--warn) 7%,transparent)}
.arch-notice.warn .arch-notice-g{color:var(--warn)}
.arch-code{display:block;margin-top:4px;font-size:11.5px;color:var(--arch-ink-2)}
.arch-wait{display:inline-flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:12px}
.arch-spin{width:12px;height:12px;border-radius:50%;border:2px solid color-mix(in srgb,var(--accent) 25%,transparent);border-top-color:var(--accent);animation:archSpin .9s linear infinite}
.arch-elapsed{font-variant-numeric:tabular-nums;color:var(--arch-ink)}
@keyframes archSpin{to{transform:rotate(360deg)}}
.arch-legend{padding:12px 16px;border:1px solid var(--arch-hair);border-radius:var(--arch-r);background:var(--arch-glass)}
.arch-legend h4{margin:0 0 8px;font-size:12px;font-weight:600;color:var(--arch-ink-2)}
.arch-legend ul{margin:0;padding:0;list-style:none;display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:6px 18px}
.arch-legend li{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--arch-ink-2)}
.arch-legend strong{color:var(--arch-ink);font-weight:600}
.arch-legend .arch-hint{margin:8px 0 0}
.arch-legend-line{width:44px;height:10px;flex:none;overflow:visible}
.arch-legend-line .arch-edge{stroke:var(--accent)}
@media(prefers-reduced-motion:reduce){.arch *{transition:none!important}.arch-port.target{animation:none}.arch-spin{animation-duration:2.4s}}
`;

  root.JarvisArchitectureSettings=Object.freeze({mount,createFixtureAdapter,createHttpAdapter,normalizeSnapshot,autoLayout,STYLE_ID});
  if(typeof module==='object'&&module&&module.exports)module.exports=root.JarvisArchitectureSettings;
})(typeof window!=='undefined'?window:globalThis);
