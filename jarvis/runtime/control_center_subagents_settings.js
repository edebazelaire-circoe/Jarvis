/* Réglages des sous-agents (jarvis-organic-agent-orchestration, Slice 10 ; sections depuis
   jarvis-settings-ui-reorganization Slice 04).

   Deux vues (`options.view`) : `roles` (défaut, onglet Architecture & Agents › Sous-agents) et
   `work_methods` (section Avancé & diagnostic › Work Methods apprises : approches observées et promotion).

   Rend le registre des rôles servi par `GET /api/subagent-roles` (`schema_version` 2) : liste des rôles,
   fiche détaillée (mission, capacités, savoirs, Work Methods, ordre de la consigne apposée), et les instances
   en cours lues dans `GET /api/agent/tasks` (champ `role`, le marqueur tel que le hook le lit).

   Écritures : les instructions d'un rôle, par la voie canonique des prompts
   `POST /api/prompts/subagent_role.<id>` (`edit` avec `base_revision` + `expected_effective_revision`,
   ou `reset`) ; et, depuis la Slice 12, la promotion explicite d'un candidat de Work Method
   (`GET /api/work-methods/candidates`, `POST /api/work-methods/promotions`, révision optimiste
   `expected_version`). Tout le reste est en lecture seule et le dit : capacités et méthodes suivent le code.

   Identité visuelle : `visual.icon` / `visual.accent` / `visual.badge` sont des JETONS. L'accent devient la
   variable CSS `--role-accent-<jeton>` (définie dans `control_center.html`, partagée avec le graphe), jamais
   une couleur écrite ici ; l'icône et le badge la doublent toujours, l'identité ne repose pas sur la couleur.

   Échecs : chaque refus est affiché dans la zone concernée (texte et code du serveur) et journalisé en console
   (`console.error('<code>', erreur)`), comme le reste du Control Center ; le serveur journalise de son côté
   `prompt.override.rejected`. Chaque attente porte un compteur et une échéance (`timeoutMs`).
   Point de montage : `#subagentSettingsMount` (créé par la section). Contrat : `docs/subagent-roles.md` § 8.

   Modèles du rôle (jarvis-architecture-agents-settings-editor, Slice 06) : quand la page passe un adaptateur
   `options.routing` (`JarvisSubagentRouting.createHttpAdapter()`, monté par la Slice 07), la fiche porte la
   liste ordonnée des candidats harness + modèle du rôle, le repli automatique (`allow_general_fallback`), la
   provenance (hérité du profil / réglé pour ce rôle), la restauration de l'héritage et l'aperçu servi ; la matrice
   de routage du tableau de bord projette le même instantané en lecture seule (refonte-ui-settings, Slice 03 : la vue
   `roles` est un tableau de bord, voir `docs/settings/architecture-agents.md` § 1). Chaque écriture ne vise qu'UN rôle ; l'écran affiche
   l'instantané renvoyé, garde le brouillon sur un refus, relit sur un 409 ou une issue inconnue. Sans adaptateur,
   la vue renvoie vers Avancé › Runtime & CLI (profils hérités). Le style propre à cette composition est
   injecté une fois (`#jarvisSubagentSettingsStyle`), jetons du thème seulement. */
(function(root){
  'use strict';
  const MOUNT_ID='subagentSettingsMount';
  const ROLES_PATH='/api/subagent-roles';
  const TASKS_PATH='/api/agent/tasks';
  const PROMPT_PATH=id=>'/api/prompts/'+encodeURIComponent(id);
  const CANDIDATES_PATH='/api/work-methods/candidates';
  const PROMOTIONS_PATH='/api/work-methods/promotions';
  /* Refus après lesquels les candidats sont relus : la vue de l'écran n'est plus celle du serveur. */
  const STALE_CANDIDATE_CODES=new Set(['work_method_revision_conflict','work_method_version_conflict',
    'work_method_candidate_not_eligible','work_method_candidate_unknown']);
  const CANDIDATE_STATUS={candidate:['Candidate','ok'],observing:['En observation',''],
    insufficient_quality:['Issues insuffisantes','bad'],matches_method:['Déjà décrite par la méthode',''],promoted:['Promue','ok']};
  const DEFAULT_TIMEOUT_MS=15000;
  /* Borne d'une surcharge de prompt : lue sur la route (`instructions_max_chars`), sinon cette valeur, qui est
     `prompt_registry.MAX_OVERRIDE_TEXT`. */
  const DEFAULT_MAX_CHARS=8192;
  const UNKNOWN_OUTCOME=new Set(['subagent_settings_timeout','subagent_settings_unreachable']);
  const fmt=n=>String(n).replace(/\B(?=(\d{3})+(?!\d))/g,' ');
  /* Conseil adapté à l'erreur réelle de lecture du registre. */
  function loadAdvice(code){
    if(/^prompt_/.test(code||''))return 'Le document des surcharges de prompts (clé prompt_overrides des réglages) est illisible : corrigez-le ou retirez-le du fichier de réglages, puis réessayez.';
    if(code==='subagent_settings_payload_invalid')return 'La réponse du Control Center n’a pas la forme attendue : la page et le serveur ne sont peut-être pas de la même version. Rechargez la page, puis réessayez.';
    if(code==='subagent_settings_render_failed')return 'L’écran n’a pas pu afficher cette réponse. Rechargez la page ; si l’erreur revient, signalez-la avec le code ci-dessous.';
    return 'Vérifiez que le Control Center répond, puis réessayez.';
  }
  const CONFLICT_CODES=new Set(['prompt_override_concurrent','prompt_override_stale']);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const TOKEN=/^[a-z][a-z0-9-]{0,31}$/;

  /* Pictogrammes dessinés des jetons `visual.icon` : la table partagée avec le graphe des tâches
     (`control_center_role_identity.js`, `window.JarvisRoleIdentity`, Slice 09), jamais une copie. Un jeton inconnu
     prend la silhouette générique : le badge reste lisible à côté. */
  const Identity=root.JarvisRoleIdentity||(typeof require==='function'?require('./control_center_role_identity.js'):null);
  const ICONS=Identity.ICONS;
  const icon=name=>Identity.iconSvg(name,'sar-glyph');
  /* Transport et lecture de la politique par rôle (Slice 06). Absent de la page : la fiche n'a pas de section
     Modèles, rien d'autre ne change. */
  const Routing=root.JarvisSubagentRouting||(typeof require==='function'?require('./control_center_subagent_routing.js'):null);
  const STYLE_ID='jarvisSubagentSettingsStyle';
  /* Pictogrammes des commandes (trait 1,8, grille 24), dessinés ici : ce ne sont pas des identités de rôle. */
  const OPS={
    up:'<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>',down:'<path d="M12 5v14"/><path d="m6 13 6 6 6-6"/>',
    remove:'<path d="M6 6l12 12M18 6 6 18"/>',add:'<path d="M12 5v14M5 12h14"/>',
    ok:'<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.2 2.4 2.4 4.6-5"/>',
    warn:'<path d="M12 3.5 21.5 20h-19z"/><path d="M12 10v4.2M12 17h.01"/>',
    lock:'<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7.8a4 4 0 0 1 8 0v2.7"/>',
    route:'<circle cx="6" cy="6" r="2.4"/><circle cx="18" cy="18" r="2.4"/><path d="M8.4 6H15a3 3 0 0 1 0 6H9a3 3 0 0 0 0 6h6.6"/>',
    inherit:'<path d="M6 4v9a4 4 0 0 0 4 4h8"/><path d="m14 13 4 4-4 4"/>',pin:'<path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
    grid:'<rect x="4" y="4" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.2"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.2"/>',
    /* Tableau de bord (refonte-ui-settings, Slice 03) : médaillons des panneaux et tuiles de synthèse. */
    team:'<circle cx="12" cy="7.5" r="2.8"/><circle cx="5.5" cy="10" r="2.2"/><circle cx="18.5" cy="10" r="2.2"/><path d="M7.5 19.5a4.5 4.5 0 0 1 9 0"/><path d="M2.8 18a3.2 3.2 0 0 1 4.6-2.6M21.2 18a3.2 3.2 0 0 0-4.6-2.6"/>',
    layers:'<path d="m12 3.5 8.5 4.5-8.5 4.5L3.5 8z"/><path d="m3.5 12 8.5 4.5 8.5-4.5"/><path d="m3.5 16 8.5 4.5 8.5-4.5"/>',
    cloud:'<path d="M7 18.5h10.5a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.6 9.2 4.7 4.7 0 0 0 7 18.5z"/>',
    tool:'<path d="M14.7 6.3a4 4 0 0 0-5.2 5.2L4 17l3 3 5.5-5.5a4 4 0 0 0 5.2-5.2l-2.6 2.6-2.4-.6-.6-2.4z"/>',
    pulse:'<path d="M3 12h4l2.5-6 5 12 2.5-6H21"/>',
    target:'<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/>',
    rules:'<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>',
    matrix:'<circle cx="12" cy="5" r="2.2"/><circle cx="5" cy="19" r="2.2"/><circle cx="19" cy="19" r="2.2"/><path d="M12 7.2v4.3M12 11.5 5.9 17.2M12 11.5l6.1 5.7"/>',
    more:'<circle cx="5.5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18.5" cy="12" r="1.3"/>',
    cpu:'<rect x="6.5" y="6.5" width="11" height="11" rx="2"/><path d="M9.5 3v3.5M14.5 3v3.5M9.5 17.5V21M14.5 17.5V21M3 9.5h3.5M3 14.5h3.5M17.5 9.5H21M17.5 14.5H21"/>',
    open:'<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    edit:'<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  };
  const op=(name,cls)=>`<svg class="sar-op-g${cls?' '+cls:''}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${OPS[name]||''}</svg>`;
  const PREVIEW_REASON={preferred:'premier choix de la liste',fallback:'repli dans la liste du rôle',general_fallback:'repli sur la liste générale'};

  function logError(code,error,context){try{root.console&&root.console.error(code,error,context||{})}catch(_e){/* intentionnel : la console absente (test node sans console) ne doit pas masquer l'erreur déjà affichée */}}
  function logInfo(code,data){try{root.console&&root.console.info(code,data||{})}catch(_e){/* intentionnel : même argument que logError */}}

  function create(host,options){
    const opts=options||{};
    /* La promotion d'une approche observée est un outil d'opérateur (Avancé), pas une configuration de rôle. */
    const view=opts.view==='work_methods'?'work_methods':'roles';
    /* Adaptateur de la politique par rôle (`JarvisSubagentRouting`) ; la vue Work Methods n'en a pas l'usage. */
    const routing=view==='roles'&&Routing&&opts.routing&&typeof opts.routing.load==='function'?opts.routing:null;
    const timeoutMs=Number(opts.timeoutMs)>0?Number(opts.timeoutMs):DEFAULT_TIMEOUT_MS;
    const now=typeof opts.now==='function'?opts.now:()=>Date.now();
    const setTimer=opts.setInterval||((fn,ms)=>root.setInterval?root.setInterval(fn,ms):null);
    const clearTimer=opts.clearInterval||(id=>{if(id!=null&&root.clearInterval)root.clearInterval(id)});
    const fetchJson=opts.fetch||(async(path,init)=>{
      const controller=typeof root.AbortController==='function'?new root.AbortController():null;
      const timer=controller&&root.setTimeout?root.setTimeout(()=>controller.abort(),timeoutMs):null;
      let r;
      try{r=await root.fetch(path,{...(init||{}),signal:controller?controller.signal:undefined})}
      catch(e){
        if(e&&e.name==='AbortError'){const t=new Error(`Pas de réponse du Control Center après ${Math.round(timeoutMs/1000)} s.`);t.code='subagent_settings_timeout';throw t}
        const t=new Error('Control Center injoignable : '+(e&&e.message||e));t.code='subagent_settings_unreachable';throw t;
      }finally{if(timer!=null&&root.clearTimeout)root.clearTimeout(timer)}
      const text=await r.text();let body={};try{body=text?JSON.parse(text):{}}catch{body={error:text}}
      if(!r.ok||body.ok===false){
        const envelope=body&&typeof body.error==='object'&&body.error?body.error:null;
        const e=new Error((envelope&&envelope.message)||(typeof body.error==='string'&&body.error)||body.message||('HTTP '+r.status));
        e.status=r.status;e.code=(r.headers&&r.headers.get&&r.headers.get('X-Jarvis-Error-Code'))||(envelope&&envelope.code)||body.code||'';throw e;
      }
      return body;
    });

    const st={
      phase:'loading',error:null,payload:null,selected:null,
      /* Brouillons partageables avec la page (`options.drafts`) : changer d'onglet ne perd pas un texte non enregistré. */
      drafts:opts.drafts&&typeof opts.drafts==='object'?opts.drafts:{},openEditor:{},confirmReset:null,
      save:null,                 // {id, action, startedAt}
      notice:{},                 // id -> {tone,text,code}
      tasks:{phase:'loading',error:null,items:[]},instancesOpen:false,
      /* Slice 12 : candidats de Work Method (lecture indépendante) et promotion en cours / à confirmer. */
      learned:{phase:'loading',error:null,items:[],thresholds:{},startedAt:now()},
      promote:null,confirmPromote:null,promoteNotice:null,
      /* Slice 06 : politique de routage par rôle (lecture indépendante du registre). `routeDrafts` : brouillon
         par rôle `{candidates:[{agent,model}], allow_general_fallback}`, partageable avec la page comme `drafts`. */
      route:{phase:routing?'loading':'off',error:null,snap:null,stale:null,startedAt:now()},
      routeDrafts:opts.routeDrafts&&typeof opts.routeDrafts==='object'?opts.routeDrafts:{},
      routeSave:null,routeNotice:{},routeConfirmRestore:null,routeAdd:{},
      /* Slice 03 (refonte) : rôle dont les actions « … » sont dépliées, au plus un. */
      menu:null,
      startedAt:now(),destroyed:false,
    };
    let ticker=null,routePromise=null;
    const warnedAccent=new Set();

    /* --- lecture du registre ------------------------------------------- */
    /* Une charge utile partielle (autre version, champ retiré) ne doit jamais figer l'écran : chaque rôle est
       ramené à une forme sûre, les champs absents s'affichent vides et la fiche dit lesquels manquent. */
    const EXPECTED=['name','marker','description','mission','instructions','default_instructions','default_revision',
      'revision','visual','tools','work_methods','enabled','can_spawn','can_own_mission','offered_to_brain','offered_to_subagents'];
    function normalizeRole(r){
      const str=v=>v==null?'':String(v),list=v=>Array.isArray(v)?v.map(str):[];
      const visual=r.visual&&typeof r.visual==='object'?r.visual:{};
      return {...r,id:str(r.id),name:str(r.name)||str(r.id),marker:str(r.marker)||str(r.id),description:str(r.description),
        mission:str(r.mission),when_relevant:str(r.when_relevant),instructions:str(r.instructions),
        default_profile:str(r.default_profile)||'general',prompt_id:str(r.prompt_id)||'subagent_role.'+str(r.id),
        visual:{icon:str(visual.icon),accent:str(visual.accent),badge:str(visual.badge)},
        tools:list(r.tools),skills:list(r.skills),aliases:list(r.aliases),work_methods:list(r.work_methods),
        default_work_method:r.default_work_method?str(r.default_work_method):null,loadout_role:r.loadout_role?str(r.loadout_role):null,
        enabled:r.enabled!==false,can_spawn:r.can_spawn===true,can_own_mission:r.can_own_mission===true,
        offered_to_brain:r.offered_to_brain===true,offered_to_subagents:r.offered_to_subagents===true,
        constrained_output:r.constrained_output===true,modified:r.modified===true,conflict:r.conflict?str(r.conflict):null,
        /* V1.2 Slice 06 : rôle que l'édition n'offre pas (`coder` en presentation), même code que le refus du hook. */
        edition_unavailable:r.edition_unavailable&&typeof r.edition_unavailable==='object'
          ?{code:str(r.edition_unavailable.code),message:str(r.edition_unavailable.message)}:null,
        missing:EXPECTED.filter(k=>!Object.prototype.hasOwnProperty.call(r,k))};
    }
    function normalizePayload(data){
      const raw=data.roles.filter(r=>r&&typeof r==='object'&&typeof r.id==='string'&&r.id.trim());
      const obj=v=>v&&typeof v==='object'&&!Array.isArray(v)?v:{};
      return {...data,roles:raw.map(normalizeRole),dropped:data.roles.length-raw.length,
        work_methods:Array.isArray(data.work_methods)?data.work_methods.filter(m=>m&&typeof m==='object'):[],
        aliases:obj(data.aliases),relation_labels:obj(data.relation_labels),accents:Array.isArray(data.accents)?data.accents:[],
        instructions_max_chars:Number(data.instructions_max_chars)>0?Number(data.instructions_max_chars):DEFAULT_MAX_CHARS};
    }
    const roles=()=>(st.payload&&st.payload.roles)||[];
    const maxChars=()=>(st.payload&&st.payload.instructions_max_chars)||DEFAULT_MAX_CHARS;
    const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);
    const roleById=id=>roles().find(r=>r.id===id)||null;
    const methodById=id=>((st.payload&&st.payload.work_methods)||[]).find(m=>m.method_id===id)||null;
    const relationLabel=k=>((st.payload&&st.payload.relation_labels)||{})[k]||k;
    function accentOf(role){
      const token=role&&role.visual&&role.visual.accent;
      const known=(st.payload&&st.payload.accents)||[];
      if(TOKEN.test(String(token||''))&&known.includes(token))return token;
      if(role&&!warnedAccent.has(role.id)){warnedAccent.add(role.id);logError('subagent_settings_unknown_accent',new Error(`jeton d'accent inconnu : ${token}`),{role_id:role.id})}
      return 'slate';
    }
    const accentStyle=token=>`--sar-accent:var(--role-accent-${token})`;
    const draftOf=role=>Object.prototype.hasOwnProperty.call(st.drafts,role.id)?st.drafts[role.id]:role.instructions;
    const isDirty=role=>Object.prototype.hasOwnProperty.call(st.drafts,role.id)&&st.drafts[role.id]!==role.instructions;

    /* Le marqueur d'une instance (`role` de `/api/agent/tasks`) résolu comme `subagent_roles.resolve_role`. */
    function resolveMarker(marker){
      const m=String(marker??'').trim().toLowerCase();
      if(!m)return {status:'undeclared',role:null,marker:''};
      const aliases=(st.payload&&st.payload.aliases)||{};
      const direct=roles().find(r=>(r.marker||r.id)===m);
      if(direct)return {status:direct.enabled?'declared':'disabled',role:direct,roleId:direct.id,marker:m};
      /* Comme `resolve_role` : un alias reste `alias` même si sa cible manque à la liste servie (la cible fait foi).
         Clé propre seulement : `constructor` n'est pas un alias. */
      if(own(aliases,m)&&typeof aliases[m]==='string')return {status:'alias',role:roleById(aliases[m]),roleId:aliases[m],marker:m};
      return {status:'unknown',role:null,roleId:'unknown',marker:m.slice(0,24)};
    }

    /* --- rendu ----------------------------------------------------------- */
    function elapsed(since){return Math.max(0,Math.floor((now()-since)/1000))}
    function waitingHtml(label,since){
      return `<div class="sar-wait" role="status"><span class="sar-spin" aria-hidden="true"></span><span>${esc(label)}</span>
        <span class="sar-elapsed" data-sar-since="${since}">${elapsed(since)} s</span><span class="hint">abandon après ${Math.round(timeoutMs/1000)} s</span></div>`;
    }
    function codeLine(code){return code?`<div class="hint sar-code">Code : <code>${esc(code)}</code></div>`:''}
    function chip(text,tone,title){return `<span class="tag${tone?' '+tone:''}"${title?` title="${esc(title)}"`:''}>${esc(text)}</span>`}
    function identity(role,size){
      const token=accentOf(role),v=role.visual||{};
      return `<span class="sar-ident sar-${size}" style="${accentStyle(token)}"><span class="sar-tile">${icon(v.icon)}</span><span class="sar-badge">${esc(v.badge||'?')}</span></span>`;
    }
    function availability(role){
      if(!role.enabled)return chip('Désactivé','bad','Le hook ne reconnaît pas ce rôle : son marqueur reste dans le libellé.');
      if(role.edition_unavailable)return chip('Indisponible dans cette édition','bad',role.edition_unavailable.message);
      return '';
    }
    /* --- Tableau de bord (refonte-ui-settings, Slice 03) ------------------------------------------------------
       Une seule page : synthèse et politique de délégation, lignes des rôles, matrice de routage et règles globales,
       puis la fiche du rôle choisi (où vivent les écritures). Chaque chiffre, ligne et case se lit dans le registre
       (`/api/subagent-roles`) ou dans l'instantané de routage ; ce que le serveur ne mesure pas n'est pas affiché
       (aucun « taux de bonne délégation », aucune priorité inventée, aucun ajout de rôle : le registre est du code).
       Composition sur les primitives `.set-*` (Slice 01), écrites ici en classes : la vue tourne aussi sans
       `JarvisSettingsUI` (tests node, page de démonstration). */
    const routed=()=>st.route.phase!=='off';
    /* Une projection du routage qui lève (instantané inattendu) reste locale : la cellule ou le panneau le dit, le
       reste du tableau de bord et la fiche restent utilisables. Même code que la section Modèles de la fiche. */
    function guarded(where,fn,roleId){
      try{return fn()}
      catch(e){
        logError('subagent_settings_routing_render_failed',e,{where,role_id:roleId||null});
        /* Le code stable se lit avec la raison (Slice 07) : celui de l'erreur s'il en porte un, sinon celui du journal. */
        return `<span class="sar-item-route bad" role="note">${op('warn')}<span class="sar-item-route-l">Affichage impossible : ${esc(e&&e.message||e)} <code>${esc(e&&e.code||'subagent_settings_routing_render_failed')}</code></span></span>`;
      }
    }
    /* Libellé d'un candidat dans une cellule : jamais la couleur seule (pictogramme et mot « indisponible »). La
       balise reste ouverte : l'appelant ajoute ce qui suit puis la ferme. */
    function refCell(cls,v,glyph){
      return `<span class="${cls}${v.available?'':' bad'}" title="${esc(v.label)}${v.available?'':' : '+esc(v.unavailable_reason||'indisponible')}">${v.available?op(glyph):op('warn')}<span class="sar-item-route-l">${esc(v.label)}</span>${v.available?'':'<span class="sar-item-flag">indisponible</span>'}`;
    }
    /* Cellule « modèle préféré » : le premier candidat (brouillon compris), sinon ce que dit l'aperçu servi. */
    function preferredLine(role){
      if(!routed())return '';
      if(!snap())return st.route.phase==='error'?`<span class="sar-item-route bad">${op('warn')}<span class="sar-item-route-l">Politique illisible</span></span>`
        :'<span class="sar-item-route muted"><span class="sar-item-route-l">Lecture…</span></span>';
      const r=routeOf(role.id);if(!r)return '<span class="sar-item-route muted"><span class="sar-item-route-l">Non routé</span></span>';
      const d=routeEffective(role.id),first=d.candidates[0];
      if(!first)return r.preview&&r.preview.outcome==='cli_default'&&!routeDirty(role.id)
        ?`<span class="sar-item-route muted" title="${esc(r.preview.detail||'')}">${op('cpu')}<span class="sar-item-route-l">Modèle du CLI</span></span>`
        :`<span class="sar-item-route bad">${op('warn')}<span class="sar-item-route-l">Liste vide</span></span>`;
      const more=d.candidates.length-1;
      return refCell('sar-item-route',candView(role.id,first),'route')+(more>0?`<span class="sar-item-more" title="${more} autre(s) candidat(s) dans la liste">+${more}</span>`:'')+'</span>';
    }
    /* Cellule « repli » : le deuxième candidat, sinon la liste générale si le repli s'applique, sinon rien. */
    function fallbackLine(role){
      if(!routed()||!snap())return '';
      const r=routeOf(role.id);if(!r)return '';
      const d=routeEffective(role.id),second=d.candidates[1];
      if(second)return refCell('sar-item-fb',candView(role.id,second),'inherit')+'</span>';
      const moot=!r.explicit&&r.inherited_profile===r.fallback.profile&&!routeDirty(role.id);
      return d.allow_general_fallback&&!moot
        ?`<span class="sar-item-fb muted">${op('inherit')}<span class="sar-item-route-l">Liste « ${esc(r.fallback.profile)} »</span></span>`
        :'<span class="sar-item-fb muted"><span class="sar-item-route-l">Aucun repli</span></span>';
    }
    function sourceChip(role){
      if(!routed()||!snap())return '';
      const r=routeOf(role.id);if(!r)return '';
      return r.explicit?`<span class="sar-src explicit">${op('pin')}Réglé</span>`
        :`<span class="sar-src inherited" title="Hérité du profil « ${esc(r.inherited_profile)} »">${op('inherit')}Hérité<span class="sar-sr"> du profil ${esc(r.inherited_profile)}</span></span>`;
    }
    const TOOLS_SHOWN=3;
    function toolsCell(role){
      const t=role.tools||[];
      if(!t.length)return '<span class="sar-quiet">aucun</span>';
      const rest=t.slice(TOOLS_SHOWN);
      return `<ul class="sar-tools" aria-label="Outils de ${esc(role.name)}">${t.slice(0,TOOLS_SHOWN).map(x=>`<li class="sar-tool-chip">${esc(x)}</li>`).join('')}`
        +(rest.length?`<li class="sar-tool-chip more" title="${esc(rest.join(', '))}"><span aria-hidden="true">+${rest.length}</span><span class="sar-sr">et ${esc(rest.join(', '))}</span></li>`:'')+'</ul>';
    }
    function cell(key,label,body){return `<div class="sar-cell sar-c-${key}"><span class="sar-cell-k">${esc(label)}</span>${body}</div>`}
    /* Actions secondaires d'un rôle (« … ») : une divulgation, pas un menu ARIA ; chaque action mène à la fiche. */
    function moreMenu(role){
      const id=esc(role.id),open=st.menu===role.id,sel=role.id===st.selected;
      const items=[['fiche','open','Ouvrir la fiche'],routed()&&routeOf(role.id)?['models','route','Régler les modèles']:null,['instructions','edit','Modifier les instructions']].filter(Boolean);
      return `<button type="button" class="sar-more" data-sar-more="${id}" aria-expanded="${open?'true':'false'}" aria-controls="sar-menu-${id}" aria-label="Actions du rôle ${esc(role.name)}" title="Actions du rôle"${sel||open?'':' tabindex="-1"'}>${op('more')}</button>`
        +(open?`<ul class="sar-menu" id="sar-menu-${id}" aria-label="Actions du rôle ${esc(role.name)}" data-sar-menu="${id}">${items.map(([act,glyph,label])=>
          `<li><button type="button" class="sar-menu-item" data-sar-menu-act="${act}" data-sar-menu-role="${id}">${op(glyph)}<span>${esc(label)}</span></button></li>`).join('')}</ul>`:'');
    }
    function listItem(role){
      const sel=role.id===st.selected,id=esc(role.id);
      const tags=[availability(role),role.modified?chip('modifié','warn'):'',isDirty(role)?chip('non enregistré','warn'):'',routeDirty(role.id)?chip('routage non enregistré','warn'):'',role.conflict?chip('surcharge écartée','bad'):''].join('');
      const route=routed()?cell('model','Modèle préféré',guarded('preferred',()=>preferredLine(role),role.id))+cell('source','Source',guarded('source',()=>sourceChip(role),role.id))
        +cell('fallback','Repli',guarded('fallback',()=>fallbackLine(role),role.id)):'';
      return `<li class="sar-row${sel?' selected':''}${role.enabled?'':' off'}${st.menu===role.id?' menu-open':''}" style="${accentStyle(accentOf(role))}" data-sar-row="${id}">
        <div class="sar-cell sar-c-role"><button type="button" class="sar-item${sel?' selected':''}${role.enabled?'':' off'}" data-sar-role="${id}" aria-current="${sel?'true':'false'}" tabindex="${sel?'0':'-1'}"${role.when_relevant?` aria-describedby="sar-when-${id}"`:''}>
          ${identity(role,'sm')}<span class="sar-item-text"><span class="sar-item-name">${esc(role.name)}</span><span class="sar-item-desc">${esc(role.description)}</span>${tags?`<span class="sar-item-meta">${tags}</span>`:''}</span></button></div>
        ${route}${cell('tools','Outils',toolsCell(role))}
        ${cell('when','Conditions d’usage',role.when_relevant?`<span class="sar-when" id="sar-when-${id}" title="${esc(role.when_relevant)}">${esc(role.when_relevant)}</span>`:'<span class="sar-quiet">non précisées</span>')}
        <div class="sar-cell sar-c-more">${moreMenu(role)}</div></li>`;
    }
    function rolesHeadHtml(){
      const h=(key,label)=>`<span class="sar-h sar-c-${key}">${esc(label)}</span>`;
      return `<div class="sar-rows-head${routed()?'':' noroute'}" aria-hidden="true">${h('role','Rôle')}${routed()?h('model','Modèle préféré')+h('source','Source')+h('fallback','Repli'):''}${h('tools','Outils')}${h('when','Conditions d’usage')}<span class="sar-h sar-c-more"></span></div>`;
    }

    /* Panneau verre (`.set-panel`, Slice 01) écrit en classes, médaillon et teinte compris. */
    function panelHtml({id,title,desc,glyph,tone,aside='',body='',cls=''}){
      return `<section class="set-panel sar-panel${tone?' set-tone-'+tone:''}${cls?' '+cls:''}" id="${id}" aria-labelledby="${id}-title">
        <header class="set-panel-head"><span class="set-medallion" aria-hidden="true">${op(glyph)}</span><div class="set-panel-titles"><h3 class="set-panel-title" id="${id}-title">${esc(title)}</h3>${desc?`<p class="set-panel-desc">${esc(desc)}</p>`:''}</div>${aside?`<div class="set-panel-aside">${aside}</div>`:''}</header>
        <div class="set-panel-body">${body}</div></section>`;
    }
    /* Tuile `.set-stat` ; `sub` : une ligne de détail mesurée (jamais un texte de maquette). */
    function statHtml({value,label,glyph,tone,sub,key}){
      return `<div class="set-stat sar-stat${tone?' set-tone-'+tone:''}" data-sar-stat="${key}"><span class="set-stat-icon" aria-hidden="true">${op(glyph)}</span><span class="set-stat-text"><strong class="set-stat-value">${esc(value)}</strong><span class="set-stat-label">${esc(label)}</span>${sub?`<span class="sar-stat-sub">${esc(sub)}</span>`:''}</span></div>`;
    }
    function dotHtml(kind,text){return `<span class="set-dot set-dot-${kind}">${esc(text)}</span>`}
    /* `hintHtml` : aide déjà composée (un chemin en `<code>`), sinon `hint` est échappé. */
    function ruleRow(key,glyph,label,hint,control,hintHtml){
      const help=hintHtml||(hint?esc(hint):'');
      return `<div class="set-row sar-rule" data-sar-rule="${key}"><span class="set-row-icon" aria-hidden="true">${op(glyph)}</span><div class="set-row-text"><span class="set-row-label" id="sar-rule-${key}-label">${esc(label)}</span>${help?`<p class="set-row-hint">${help}</p>`:''}</div>${control?`<div class="set-row-control">${control}</div>`:''}</div>`;
    }
    function linkBtn(target,label,glyph){
      return opts.openTab?`<button type="button" class="set-btn set-btn-ghost set-btn-sm" data-settings-open="${esc(target)}">${glyph?op(glyph):''}<span>${esc(label)}</span></button>`:'';
    }
    /* Chiffres de synthèse, tous mesurés : registre (rôles, outils) et instantané de routage (fournisseurs, modèles du
       catalogue, rôles lançables d'après l'aperçu servi). Sans instantané, la tuile le dit au lieu d'inventer un chiffre. */
    function metricsHtml(){
      /* QA S06 m1 : un rôle que l'édition n'offre pas n'est ni actif ni lançable ici (`full` : aucun n'est concerné). */
      const all=roles(),active=all.filter(r=>r.enabled&&!r.edition_unavailable),uses=new Map();
      active.forEach(r=>new Set(r.tools||[]).forEach(t=>uses.set(t,(uses.get(t)||0)+1)));
      const top=[...uses].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))[0];
      const s=snap(),none=routed()?(st.route.phase==='error'&&!s?'politique illisible':'lecture de la politique…'):'routage non servi ici';
      let prov={value:'—',label:'Fournisseurs IA',sub:none},ready={value:'—',label:'Rôles lançables',sub:none};
      if(s){
        const by=new Map();s.harnesses.forEach(h=>{const k=h.provider||h.id;by.set(k,by.get(k)===true||h.available)});
        const on=[...by.values()].filter(Boolean).length,models=s.harnesses.filter(h=>h.available).reduce((n,h)=>n+h.models.filter(m=>m.available).length,0);
        prov={value:`${on}/${by.size}`,label:'Fournisseurs IA disponibles',tone:on<by.size?'warn':'',sub:`${models} modèle(s) disponible(s) au catalogue`};
        const rs=s.roles.filter(r=>roleById(r.role_id)&&!roleById(r.role_id).edition_unavailable),out=k=>rs.filter(r=>r.preview&&r.preview.outcome===k).length;
        const ok=out('selected')+out('cli_default'),refused=out('refused');
        ready={value:`${ok}/${rs.length}`,label:'Rôles lançables',tone:ok<rs.length?'warn':'ok',
          sub:[out('selected')?`${out('selected')} par leur liste`:'',out('cli_default')?`${out('cli_default')} par le modèle du CLI`:'',refused?`${refused} refusé(s)`:''].filter(Boolean).join(' · ')||'aperçu vide'};
      }
      return `<div class="sar-stats">${[
        statHtml({key:'roles',value:String(active.length),label:'Sous-agents actifs',glyph:'team',tone:'violet',sub:`sur ${all.length} rôle(s) du registre${all.some(r=>r.edition_unavailable)?` · ${all.filter(r=>r.edition_unavailable).length} indisponible(s) dans cette édition`:''}`}),
        statHtml({key:'providers',glyph:'cloud',...prov,tone:prov.tone||'blue'}),
        statHtml({key:'tools',value:String(uses.size),label:'Outils déclarés',glyph:'tool',tone:'teal',sub:top?`le plus partagé : ${top[0]} (${top[1]} rôle(s))`:'aucun outil déclaré'}),
        statHtml({key:'ready',glyph:'pulse',...ready,tone:ready.tone||'cyan'}),
      ].join('')}</div>`;
    }
    function policyHtml(){
      if(!routed())return `<p class="hint">Le routage par rôle n’est pas servi sur cette page. ${linkBtn('runtime_cli','Avancé › Runtime & CLI','open')}</p>`;
      const s=snap();
      if(!s)return st.route.phase==='error'
        ?`<div class="notice bad">Politique des rôles illisible : ${esc(st.route.error&&st.route.error.message)}${codeLine(st.route.error&&st.route.error.code)}</div><div class="sar-actions"><button type="button" class="action" data-sar-route-retry>Réessayer</button></div>`
        :waitingHtml('Lecture de la politique des rôles…',st.route.startedAt||st.startedAt);
      const rs=s.roles.filter(r=>roleById(r.role_id)),explicit=rs.filter(r=>r.explicit).length;
      const fb=rs.filter(r=>routeEffective(r.role_id).allow_general_fallback).length,auto=s.compatibility.profiles_enabled;
      return `<div class="set-rows">
        ${ruleRow('profiles','layers','Routage par profil',auto?'Auto : un rôle qui hérite suit la politique de son profil.':'Dupliqué : un rôle qui hérite garde le modèle de son CLI.',dotHtml(auto?'ok':'off',auto?'Auto':'Dupliqué')+linkBtn('runtime_cli','Changer'))}
        ${ruleRow('explicit','pin','Politique propre à un rôle','Réglée dans la fiche du rôle, elle s’applique quel que soit le mode.',`<span class="sar-count"><strong>${explicit}</strong> réglé(s) · <strong>${rs.length-explicit}</strong> hérité(s)</span>`)}
        ${ruleRow('fallback','inherit','Repli automatique','Liste du rôle épuisée : JARVIS tente la liste générale.',dotHtml(fb?'ok':'off',`${fb} rôle(s) sur ${rs.length}`))}
        ${ruleRow('core','route','Quand Core délègue','Tendance de délégation réglée dans la fenêtre du cerveau Core.',linkBtn('architecture','Architecture','open')||'<span class="sar-quiet">onglet Architecture</span>')}
      </div>`;
    }
    function rulesHtml(){
      const p=st.payload||{},rows=[];
      if(p.application)rows.push(ruleRow('applies','pulse','Prise d’effet',p.application==='next_invocation'?'Au prochain sous-agent lancé ; aucun agent en cours n’est modifié.':'',dotHtml('info',p.application==='next_invocation'?'Prochain lancement':String(p.application))));
      if(p.execution_gate)rows.push(ruleRow('gate','ok','Passage à l’exécution',p.execution_gate,'<span class="set-badge set-badge-accent">Consigne du cerveau</span>'));
      if(p.mission_path)rows.push(ruleRow('mission','layers','Dossier d’une mission','','',`<code class="sar-path">${esc(p.mission_path)}</code>, sous la Mémoire du Board du contexte de tour.`));
      rows.push(ruleRow('max','edit','Instructions d’un rôle','Taille maximale d’une surcharge, vérifiée par le serveur.',`<span class="sar-count"><strong>${fmt(maxChars())}</strong> caractères</span>`));
      const s=snap();
      if(s){
        const bad=s.store.status!=='ok',partial=s.catalog.status!=='ok';
        rows.push(ruleRow('state','rules','Politique de routage',bad?`Fichier illisible : ${s.store.reason||s.store.status}`:partial?`Catalogue incomplet : ${s.catalog.reason||s.catalog.status}`:`Révision ${s.revision||'?'} ; s’applique ${s.applies==='live'?'au prochain lancement':s.applies||''}.`,
          dotHtml(bad?'bad':partial?'warn':'ok',bad?'Illisible':partial?'Incomplète':'Lisible')));
      }
      return `<div class="set-rows">${rows.join('')}</div>`;
    }
    /* Matrice de routage : quel modèle sert quel rôle, et à quel rang. Lignes = candidats harness + modèle des listes
       servies (brouillons compris) ; colonnes = rôles routés du registre ; une ligne de plus pour les rôles laissés au
       modèle du CLI. Lecture seule : l'en-tête d'une colonne mène aux modèles du rôle. */
    function matrixHtml(){
      if(!routed())return '<p class="hint">Routage par rôle non servi sur cette page.</p>';
      const s=snap();
      if(!s)return st.route.phase==='error'?'<p class="hint">Politique des rôles illisible : la matrice ne peut pas être dressée.</p>':waitingHtml('Lecture de la politique des rôles…',st.route.startedAt||st.startedAt);
      const cols=roles().filter(role=>routeOf(role.id));
      if(!cols.length)return '<p class="hint">Aucun rôle routé.</p>';
      const refs=[],seen=new Set(),key=c=>c.agent+'\u0000'+c.model;
      const cliDefault=role=>{const r=routeOf(role.id);return !routeEffective(role.id).candidates.length&&!!r.preview&&r.preview.outcome==='cli_default'};
      /* Le catalogue servi d'abord (un modèle que personne n'emploie reste une ligne vide, c'est une information),
         puis tout candidat hors catalogue encore inscrit dans une liste. */
      const served=new Map();cols.forEach(role=>routeOf(role.id).candidates.forEach(c=>{if(!served.has(key(c)))served.set(key(c),candView(role.id,c))}));
      s.harnesses.forEach(h=>h.models.forEach(m=>{const ref={agent:h.id,model:m.model};if(!seen.has(key(ref))){seen.add(key(ref));
        const d=Routing.describeRef(s,ref),known=served.get(key(ref));
        refs.push({...ref,v:known||{label:d.label,available:d.available,unavailable_reason:d.unavailable_reason}})}}));
      cols.forEach(role=>routeEffective(role.id).candidates.forEach(c=>{if(!seen.has(key(c))){seen.add(key(c));refs.push({agent:c.agent,model:c.model,v:candView(role.id,c)})}}));
      const cliRow=cols.some(cliDefault);
      if(!refs.length&&!cliRow)return '<p class="hint">Aucune liste de candidats : chaque rôle attend qu’on règle ses modèles.</p>';
      const off='<td class="sar-mx-off"><span class="sar-mx-dot" aria-hidden="true"></span><span class="sar-sr">non</span></td>';
      const head=cols.map(role=>`<th scope="col" style="${accentStyle(accentOf(role))}"><button type="button" class="sar-mx-role" data-sar-route-goto="${esc(role.id)}" title="Régler les modèles : ${esc(role.name)}">${identity(role,'xs')}<span class="sar-sr">${esc(role.name)}</span></button></th>`).join('');
      const mark=(role,ref)=>{
        const d=routeEffective(role.id),i=d.candidates.findIndex(c=>Routing.sameRef(c,ref));
        if(i<0)return off;
        const v=candView(role.id,ref),what=`rang ${i+1} sur ${d.candidates.length}${v.available?'':', indisponible'}`;
        return `<td class="sar-mx-on${i===0?' first':''}${v.available?'':' unavailable'}" style="${accentStyle(accentOf(role))}"><span class="sar-mx-pos" title="${esc(what)}" aria-hidden="true">${i+1}</span><span class="sar-sr">${esc(what)}</span></td>`;
      };
      const body=refs.map(ref=>`<tr${ref.v.available?'':' class="unavailable"'}><th scope="row"><span class="sar-mx-label">${ref.v.available?'':op('warn')}<span>${esc(ref.v.label)}</span>${ref.v.available?'':'<span class="sar-item-flag">indisponible</span>'}</span></th>${cols.map(role=>mark(role,ref)).join('')}</tr>`).join('')
        +(cliRow?`<tr class="sar-mx-cli"><th scope="row"><span class="sar-mx-label">${op('cpu')}<span>Sans liste : modèle du CLI</span></span></th>${cols.map(role=>cliDefault(role)
          ?`<td class="sar-mx-on first" style="${accentStyle(accentOf(role))}"><span class="sar-mx-pos cli" title="Le CLI garde son propre modèle" aria-hidden="true"></span><span class="sar-sr">oui</span></td>`:off).join('')}</tr>`:'');
      return `<div class="set-table-shell sar-matrix-shell"><div class="set-table-scroll" role="region" tabindex="0" aria-label="Matrice de routage : modèles par rôle">
        <table class="set-table sar-matrix"><thead><tr><th scope="col">Modèle</th>${head}</tr></thead><tbody>${body}</tbody></table></div></div>
        <p class="hint sar-mx-legend"><span class="sar-mx-pos sample" aria-hidden="true">1</span>rang dans la liste du rôle (1 = préféré) ; cercle pointillé : candidat indisponible.</p>`;
    }
    function boardHtml(){
      const all=roles(),sel=roleById(st.selected);
      const rolesAside=`<span class="set-badge set-badge-accent">${all.length} rôle(s) · registre du code</span>`;
      return `<div class="sar sar-board set-page" data-subagent-settings="1"><div class="set-grid sar-grid">
        ${panelHtml({id:'sar-p-overview',title:'Vue d’ensemble',desc:'JARVIS confie chaque tâche déléguée au rôle adapté ; un rôle lance le premier candidat lançable de sa liste.',glyph:'matrix',tone:'blue',cls:'set-span-7',body:summaryHtml()+guarded('metrics',metricsHtml)})}
        ${panelHtml({id:'sar-p-policy',title:'Politique de délégation',desc:'Comment un rôle trouve son modèle. Chaque réglage vit à un seul endroit, indiqué en bout de ligne.',glyph:'target',tone:'cyan',cls:'set-span-5',body:guarded('policy',policyHtml)})}
        ${panelHtml({id:'sar-p-roles',title:'Sous-agents',desc:'Rôle, modèle préféré, repli, outils et conditions d’usage de chaque sous-agent. Choisissez un rôle pour ouvrir sa fiche.',glyph:'team',tone:'violet',cls:'set-span-12 sar-roles',aside:rolesAside,
          body:`${rolesHeadHtml()}<ul class="sar-list sar-rows${routed()?'':' noroute'}" role="list" aria-label="Rôles de sous-agent" data-sar-list>${all.map(listItem).join('')}</ul>
            <p class="hint sar-rows-help">Flèches haut et bas pour parcourir les rôles, Entrée ouvre la fiche, Tab atteint les actions « … ».</p>${instancesHtml()}
            ${!routed()?`<p class="hint sar-models">Les modèles des sous-agents se règlent dans ${opts.openTab?'<button type="button" class="sar-link" data-sar-open-models>Avancé &amp; diagnostic › Runtime &amp; CLI</button>':'Avancé &amp; diagnostic › Runtime &amp; CLI'}.</p>`:''}`})}
        ${panelHtml({id:'sar-p-matrix',title:'Matrice de routage',desc:'Quel modèle sert quel rôle, et à quel rang. Un rôle en tête de colonne ouvre ses modèles.',glyph:'route',tone:'teal',cls:'set-span-7',body:guarded('matrix',matrixHtml)})}
        ${panelHtml({id:'sar-p-rules',title:'Règles globales',desc:'Ce qui vaut pour tous les sous-agents, lu dans le registre et la politique.',glyph:'rules',tone:'amber',cls:'set-span-5',body:guarded('rules',rulesHtml)})}
        <div class="sar-detail-pane set-span-12" role="region" aria-label="Fiche du rôle${sel?' '+esc(sel.name):''}">${detailHtml(sel)}</div>
      </div></div>`;
    }
    function yesNo(value,yes,no){return `<span class="sar-yn ${value?'yes':'no'}">${esc(value?yes:no)}</span>`}
    function facts(rows){return `<dl class="sar-facts">${rows.filter(Boolean).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`}

    function methodHtml(id,isDefault){
      const m=methodById(id);
      if(!m)return `<li class="sar-method missing"><span class="tag bad">méthode introuvable</span> <code>${esc(id)}</code></li>`;
      const list=(title,items)=>Array.isArray(items)&&items.length?`<div class="sar-mlist"><span class="sar-mlabel">${esc(title)}</span><ul>${items.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></div>`:'';
      const rels=Array.isArray(m.useful_relations)?m.useful_relations:[];
      const rel=rels.length?`<div class="sar-mlist"><span class="sar-mlabel">Relations à envisager</span><p>${rels.map(k=>esc(relationLabel(k))).join(', ')}</p></div>`:'';
      return `<li class="sar-method${isDefault?' default':''}"><details><summary><span class="sar-mname">${esc(m.name)}</span>${isDefault?chip('par défaut, apposée','ok'):chip('suggestion')}${m.provenance&&m.provenance.origin==='promoted'?chip('version promue','ok','Promue par une personne depuis un candidat ; c’est la version que JARVIS appose.'):''}<code class="sar-mkey">${esc(m.method_id)}@${esc(m.version)}</code></summary>
        <p class="sar-msummary">${esc(m.summary)}</p>${list('Principes',m.principles)}${list('Critères de qualité',m.quality_checks)}${rel}
        <p class="hint">Des réflexes, pas des étapes : l'agent organise son travail selon ce qu'il découvre.</p></details></li>`;
    }

    /* --- candidats de Work Method (Slice 12) ------------------------------ */
    function candidateReason(c,t){
      const n=v=>Number(v)||0;
      switch(c.reason){
        case 'not_enough_uses':return `Revenue ${n(c.uses)} fois sur ${n(t.min_uses)||3} requises.`;
        case 'not_enough_quality_evidence':return `${n(c.positive)} bonne(s) issue(s) prouvée(s) sur ${n(t.min_positive)||2} requises ; une mission terminée sans verdict QA ne compte pas.`;
        case 'positive_share_below_threshold':return `Trop d’issues mauvaises : ${n(c.positive)} bonne(s) pour ${n(c.negative)} mauvaise(s). Elle ne sera pas proposée.`;
        case 'nothing_beyond_the_method':return 'Elle n’ajoute rien à la méthode apposée : rien à apprendre.';
        case 'thresholds_met':return 'Seuils atteints : la promotion est possible, par vous seulement.';
        case 'already_promoted':return 'Déjà promue : '+(Array.isArray(c.promoted_keys)?c.promoted_keys.join(', '):'');
        default:return String(c.reason||'');
      }
    }
    function candidateHtml(c,t){
      const [label,tone]=CANDIDATE_STATUS[c.status]||[String(c.status||'?'),''];
      const kinds=Array.isArray(c.relation_kinds)&&c.relation_kinds.length?c.relation_kinds.map(k=>esc(relationLabel(k))).join(', '):'aucune relation';
      const draft=c.draft&&typeof c.draft==='object'?c.draft:null;
      const key=draft?`${draft.method_id}@${draft.version}`:'';
      const busy=!!st.promote,mine=st.promote&&st.promote.candidateId===c.candidate_id,confirming=st.confirmPromote===c.candidate_id;
      let action='';
      if(c.status==='candidate'&&draft){
        action=`<div class="sar-actions"><button type="button" class="action${confirming?' primary':''}" data-sar-promote="${esc(c.candidate_id)}"${busy?' disabled':''}>${confirming?'Confirmer la promotion':'Promouvoir en '+esc(key)}</button>
          ${confirming?`<button type="button" class="action" data-sar-promote-cancel>Annuler</button>`:''}</div>
          ${confirming?`<div class="sar-mlist" data-sar-promote-preview><p class="hint">La version <code>${esc(key)}</code> sera publiée telle quelle ; <code>${esc(c.base_method_key||'')}</code> reste, rien n’est réécrit. Elle sera apposée aux prochains sous-agents des rôles qui citent cette méthode.</p>
            <span class="sar-mlabel">Principes publiés</span><ul>${(draft.principles||[]).map(t=>`<li>${esc(t)}</li>`).join('')}</ul>
            ${(draft.quality_checks||[]).length?`<span class="sar-mlabel">Critères de qualité publiés</span><ul>${draft.quality_checks.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`:''}
            <span class="sar-mlabel">Relations à envisager publiées</span><p>${esc((draft.useful_relations||[]).map(relationLabel).join(', ')||'aucune')}</p></div>`:''}`;
      }else if(c.status==='candidate'){
        action='<p class="hint">Aucune méthode de base : la promotion demande d’écrire un nom, un résumé et des principes, ce que cet écran ne fait pas encore.</p>';
      }
      return `<li class="sar-method" data-sar-candidate="${esc(c.candidate_id)}"><div><span class="sar-mname">${c.method_id?`Avec <code>${esc(c.method_id)}</code>`:'Sans méthode'} · relations : ${kinds}</span> ${chip(label,tone)}</div>
        <p class="hint">${esc(candidateReason(c,t))}</p>
        <p class="hint">${Number(c.uses)||0} mission(s) close(s) · ${Number(c.positive)||0} bonne(s) · ${Number(c.negative)||0} mauvaise(s) · ${Number(c.unrated)||0} non notée(s) · ${(c.evidence_refs||[]).length} preuve(s)</p>
        ${mine?waitingHtml('Promotion en cours…',st.promote.startedAt):''}${action}</li>`;
    }
    /* Vue `work_methods` : une seule lecture des candidats, un bloc par rôle qui peut porter une mission. */
    function learnedRoleHtml(role){
      const t=st.learned.thresholds||{},mine=st.learned.items.filter(c=>c&&c.role_id===role.id);
      return `<section class="sar-block" style="${accentStyle(accentOf(role))}" aria-labelledby="sar-learned-${esc(role.id)}" data-sar-learned-role="${esc(role.id)}">
        <h4 id="sar-learned-${esc(role.id)}">${identity(role,'sm')}<span>${esc(role.name)}</span></h4>
        ${mine.length?`<ul class="sar-methods">${mine.map(c=>candidateHtml(c,t)).join('')}</ul>`:'<p class="hint">Aucune mission close de ce rôle dans l’historique récent.</p>'}</section>`;
    }
    function learnedHtml(){
      const l=st.learned,t=l.thresholds||{},owners=roles().filter(r=>r.can_own_mission);
      let body;
      if(l.phase==='loading')body=waitingHtml('Lecture des approches observées…',l.startedAt||st.startedAt);
      else if(l.phase==='error')body=`<div class="notice bad">Approches observées illisibles : ${esc(l.error&&l.error.message)}${codeLine(l.error&&l.error.code)}</div><div class="sar-actions"><button type="button" class="action" data-sar-learned-retry>Réessayer</button></div>`;
      else{
        const partial=l.scan&&l.scan.partial?'<div class="notice">Lecture partielle : une partie de l’historique est illisible et a été écartée (voir le journal des erreurs).</div>':'';
        body=partial+(owners.length?owners.map(learnedRoleHtml).join(''):'<p class="hint">Aucun rôle ne peut porter de mission : rien à apprendre.</p>');
      }
      const n=st.promoteNotice;
      const notice=n?`<div class="notice ${n.tone==='bad'?'bad':'ok'}" data-sar-promote-notice>${esc(n.text)}${n.hint?`<div class="hint">${esc(n.hint)}</div>`:''}${codeLine(n.code)}</div>`:'';
      return `<div class="sar sar-wm" data-subagent-work-methods="1">
        <p class="hint">Approches observées ${chip('apprentissage explicite')} : tirées des missions closes, une approche qui revient (${Number(t.min_uses)||3} fois) avec de bonnes issues prouvées par un verdict QA devient candidate. Rien n’est promu sans vous.</p>
        ${notice}${body}</div>`;
    }

    function compositionHtml(role){
      const m=role.default_work_method?methodById(role.default_work_method):null;
      return `<ol class="sar-compose" aria-label="Ordre de la consigne apposée par JARVIS">
        <li><span class="sar-step">Vos instructions</span>${chip('modifiable','ok')}<span class="hint">Le texte ci-dessous, ou le défaut du code s'il n'est pas modifié.</span></li>
        <li><span class="sar-step">Capacités du rôle</span>${chip('générées')}<span class="hint">${role.can_spawn?'Peut lancer des agents, avec la liste des rôles qu’il peut demander.':'« Vous ne lancez aucun autre agent », prioritaire sur la charte du chantier.'}</span></li>
        <li><span class="sar-step">Work Method par défaut</span>${m?chip('non modifiable'):chip('aucune')}<span class="hint">${m?`« ${esc(m.name)} » s’ajoute <strong>après</strong> vos instructions et suit le code : la modifier ici est impossible.`:'Ce rôle n’a pas de méthode par défaut : ses instructions sont sa méthode.'}</span></li></ol>`;
    }

    function countText(role,text,dirty){
      const n=text.length,max=maxChars();
      return `(${fmt(n)} / ${fmt(max)} caractères${n>max?', au-delà de la limite':''}${dirty?', non enregistré':''})`;
    }
    function canSave(role,text){return !!(role.default_revision&&role.revision)&&text.length<=maxChars()}
    function noticeHtml(id){
      const n=st.notice[id];if(!n)return '';
      const reread=n.reread?`<div class="sar-actions"><button type="button" class="action" data-sar-reread="${esc(id)}"${st.save?' disabled':''}>Réessayer la relecture</button></div>`:'';
      return `<div class="notice ${n.tone==='bad'?'bad':n.tone==='ok'?'ok':''}" data-sar-notice>${esc(n.text)}${n.hint?`<div class="hint">${esc(n.hint)}</div>`:''}${codeLine(n.code)}${reread}</div>`;
    }
    function editorHtml(role){
      const id=role.id,saving=st.save&&st.save.id===id,dirty=isDirty(role),text=String(draftOf(role)??'');
      const conflict=role.conflict?`<div class="notice bad">Votre surcharge enregistrée est écartée (<code>${esc(role.conflict)}</code>) : le défaut du code s'applique. Enregistrez à nouveau pour la reprendre sur le nouveau défaut.</div>`:'';
      const noRevision=!(role.default_revision&&role.revision)?'<div class="notice">Révisions absentes de la réponse : l’enregistrement est désactivé pour ne rien écraser à l’aveugle.</div>':'';
      const confirming=st.confirmReset===id;
      const busy=!!st.save;
      const area=`textarea-${id}`;
      return `<section class="sar-block" aria-labelledby="sar-instr-${esc(id)}"><h4 id="sar-instr-${esc(id)}">Instructions ${role.modified?chip('modifiées','warn'):chip('défaut du code')}</h4>
        ${conflict}
        <details class="rd sar-editor" data-sar-editor="${esc(id)}"${st.openEditor[id]||dirty||st.notice[id]?' open':''}>
          <summary>Afficher et modifier les instructions <span class="hint" data-sar-count>${countText(role,text,dirty)}</span></summary>
          <label class="sar-label" for="${esc(area)}">Instructions du rôle ${esc(role.name)}</label>
          <textarea id="${esc(area)}" data-sar-text="${esc(id)}" spellcheck="true" rows="14" aria-describedby="${esc(area)}-h"${saving?' readonly':''}>${esc(text)}</textarea>
          <div class="hint" id="${esc(area)}-h">Au plus ${fmt(maxChars())} caractères. Enregistré dans la couche de prompt <code>${esc(role.prompt_id)}</code>. S'applique au prochain sous-agent lancé avec ce rôle ; aucun agent en cours n'est modifié.</div>
          ${noRevision}
          ${saving?waitingHtml(st.save.action==='reset'?'Retour au défaut…':st.save.action==='reread'?'Relecture de la version enregistrée…':'Enregistrement des instructions…',st.save.startedAt):''}
          ${noticeHtml(id)}
          <div class="sar-actions">
            <button type="button" class="action primary" data-sar-save="${esc(id)}"${dirty&&!busy&&canSave(role,text)?'':' disabled'}>${saving&&st.save.action==='edit'?'Enregistrement…':'Enregistrer les instructions'}</button>
            <button type="button" class="action" data-sar-discard="${esc(id)}"${dirty&&!busy?'':' disabled'}>Annuler mes changements</button>
            <button type="button" class="action danger" data-sar-reset="${esc(id)}"${role.modified&&!busy?'':' disabled'}${confirming?' aria-describedby="sar-reset-h"':''}>${confirming?'Confirmer le retour au défaut':'Revenir au défaut'}</button>
            ${confirming?'<span class="hint" id="sar-reset-h">Votre texte enregistré sera remplacé par le défaut du code.</span>':''}
          </div>
        </details></section>`;
    }

    /* --- Modèles du rôle (Slice 06) ------------------------------------------------------------------------
       Tout vient de l'instantané servi : harnesses, modèles, libellés, disponibilité, « lançable », aperçu. Le
       brouillon n'est qu'une liste ordonnée de couples {agent, model} et le repli ; rien d'autre n'est supposé. */
    const snap=()=>st.route.snap;
    const routeOf=id=>(snap()&&snap().roles.find(r=>r.role_id===id))||null;
    const refsOf=list=>list.map(c=>({agent:c.agent,model:c.model}));
    function routeEffective(id){
      if(own(st.routeDrafts,id))return st.routeDrafts[id];
      const r=routeOf(id);return r?{candidates:refsOf(r.candidates),allow_general_fallback:r.allow_general_fallback}:null;
    }
    function routeDirty(id){
      const r=routeOf(id);if(!r||!own(st.routeDrafts,id))return false;
      const d=st.routeDrafts[id];return !Routing.sameList(d.candidates,r.candidates)||d.allow_general_fallback!==r.allow_general_fallback;
    }
    /* Vue d'un candidat du brouillon : celle du serveur quand il la connaît, sinon le catalogue servi (un ajout
       pas encore enregistré : « lançable » sera dit par le serveur à l'enregistrement). */
    function candView(id,ref){
      const r=routeOf(id),known=r&&r.candidates.find(c=>Routing.sameRef(c,ref));
      if(known)return {...known,label:known.label||Routing.describeRef(snap(),ref).label};
      const d=Routing.describeRef(snap(),ref);return {...ref,label:d.label,available:d.available,unavailable_reason:d.unavailable_reason,selectable:null,selectable_reason:''};
    }
    const refLabel=ref=>Routing.describeRef(snap(),ref).label;
    function routeWritable(){
      const s=snap();
      if(!s||st.route.phase!=='ready'||st.routeSave)return false;
      return !st.route.stale&&s.store.status==='ok';
    }
    function availabilityHtml(v){
      if(!v.available)return `<span class="sar-av bad">${op('warn')}Indisponible : ${esc(v.unavailable_reason||'raison non donnée')}</span>`;
      if(v.selectable===false)return `<span class="sar-av ok">${op('ok')}Disponible</span><span class="sar-av muted">${op('lock')}Non lançable comme sous-agent : ${esc(v.selectable_reason||'raison non donnée')}</span>`;
      if(v.selectable===null)return `<span class="sar-av ok">${op('ok')}Disponible</span><span class="sar-av muted">Lançable : vérifié par le serveur à l’enregistrement</span>`;
      return `<span class="sar-av ok">${op('ok')}Disponible</span>`;
    }
    /* Un ancien réglage par identifiant complet est servi par sa famille : l'écran dit d'où il vient,
       sans le réécrire (HV-ARCH-007 : la famille tourne dans sa version courante du CLI). */
    function savedModelHtml(v){
      return v.saved_model?`<span class="sar-av muted" data-sar-saved-model>Enregistré sous <code>${esc(v.saved_model)}</code> : le CLI lance la version courante de cette famille ; il sera enregistré par famille à la prochaine modification de ce rôle.</span>`:'';
    }
    function provenanceChip(r){
      if(!r)return '';
      return r.explicit?`<span class="sar-prov explicit">${op('pin')}Réglé pour ce rôle</span>`
        :`<span class="sar-prov inherited">${op('inherit')}Hérité du profil « ${esc(r.inherited_profile||r.default_profile||'?')} »</span>`;
    }
    function previewHtml(r,dirty){
      const p=r.preview;
      /* Le libellé servi pour ce candidat quand il est dans la liste du rôle ; sinon celui du catalogue. */
      const refLabel=ref=>{const known=r.candidates.concat(r.fallback.candidates).find(c=>Routing.sameRef(c,ref));return known&&known.label||Routing.describeRef(snap(),ref).label};
      let body;
      if(!p)body='<span class="hint">Aucun aperçu servi.</span>';
      else if(p.outcome==='selected'){
        const skipped=(Array.isArray(p.considered)?p.considered:[]).filter(c=>c&&c.eligible===false);
        body=`<strong>${esc(refLabel({agent:String(p.agent||''),model:String(p.model||'')}))}</strong> <span class="hint">(${esc(PREVIEW_REASON[p.reason]||p.reason||'raison non donnée')})</span>`
          +(skipped.length?`<ul class="sar-skip">${skipped.map(c=>`<li>Écarté : ${esc(refLabel({agent:String(c.agent||''),model:String(c.model||'')}))} — ${esc(c.detail||c.code||'')}</li>`).join('')}</ul>`:'');
      }else if(p.outcome==='cli_default')body=`Le CLI garde son propre modèle. <span class="hint">${esc(p.detail||'')}</span>`;
      else if(p.outcome==='refused')body=`<span class="sar-av bad">${op('warn')}Lancement refusé</span> <span class="hint">${esc(p.detail||p.reason||'')}</span>`;
      else body=`<code>${esc(p.outcome)}</code> <span class="hint">${esc(p.detail||'')}</span>`;
      return `<div class="sar-preview" data-sar-preview><span class="sar-preview-k">Prochain lancement</span><div>${body}</div>
        ${dirty?'<p class="hint">Aperçu de la politique enregistrée : vos changements seront évalués par le serveur à l’enregistrement.</p>':''}</div>`;
    }
    function compatHtml(){
      const c=snap()&&snap().compatibility;
      if(!c||!c.note)return '';
      const link=opts.openTab?'<button type="button" class="sar-link" data-settings-open="runtime_cli">Avancé &amp; diagnostic › Runtime &amp; CLI</button>':'Avancé &amp; diagnostic › Runtime &amp; CLI';
      return `<p class="hint sar-compat" data-sar-compat>Compatibilité : ${esc(c.note)} Réglage historique : ${link}.</p>`;
    }
    function routeNoticeHtml(id){
      const n=st.routeNotice[id];if(!n)return '';
      const again=n.reread?`<div class="sar-actions"><button type="button" class="action" data-sar-route-reread="${esc(id)}"${st.routeSave?' disabled':''}>Relire la politique</button></div>`:'';
      return `<div class="notice ${n.tone==='bad'?'bad':n.tone==='ok'?'ok':''}" data-sar-route-notice>${esc(n.text)}${n.hint?`<div class="hint">${esc(n.hint)}</div>`:''}${codeLine(n.code)}${again}</div>`;
    }
    function snapshotStateHtml(){
      const s=snap();if(!s)return '';
      const parts=[];
      if(st.route.phase==='loading')parts.push(waitingHtml('Relecture de la politique des rôles…',st.route.startedAt||st.startedAt));
      if(st.route.phase==='error')parts.push(`<div class="notice bad">Dernière lecture de la politique en échec : ${esc(st.route.error&&st.route.error.message)} L’écran montre la version lue avant.${codeLine(st.route.error&&st.route.error.code)}<div class="sar-actions"><button type="button" class="action" data-sar-route-retry>Réessayer</button></div></div>`);
      if(s.store.status!=='ok')parts.push(`<div class="notice bad">Fichier de la politique des rôles illisible : ${esc(s.store.reason||s.store.status)} Aucune écriture n’est possible tant qu’il n’est pas corrigé ; tous les rôles héritent de leur profil.${codeLine(s.store.code)}</div>`);
      if(s.catalog.status!=='ok')parts.push(`<div class="notice">Catalogue des modèles incomplet : ${esc(s.catalog.reason||s.catalog.status)}</div>`);
      if(st.route.stale)parts.push(`<div class="notice bad">L’écran ne montre peut-être plus la politique enregistrée : ${esc(st.route.stale.reason||'')} Relisez-la avant toute autre modification.${codeLine(st.route.stale.code)}<div class="sar-actions"><button type="button" class="action" data-sar-route-reread="*"${st.routeSave?' disabled':''}>Relire la politique</button></div></div>`);
      return parts.join('');
    }
    function candidateRow(id,ref,i,count,writable){
      const v=candView(id,ref),name=v.label||refLabel(ref),off=writable?'':' disabled';
      const btn=(kind,glyph,label,dis)=>`<button type="button" class="sar-op" data-sar-cand-op="${kind}" data-sar-cand-role="${esc(id)}" data-sar-cand-i="${i}" aria-label="${esc(label)}" title="${esc(label)}"${dis||!writable?' disabled':''}>${op(glyph)}</button>`;
      return `<li class="sar-cand${v.available?'':' unavailable'}${v.selectable===false?' blocked':''}" data-sar-cand="${i}">
        <span class="sar-cand-pos" aria-hidden="true">${i+1}</span>
        <span class="sar-cand-main"><span class="sar-cand-name"><span class="sar-sr">Position ${i+1} sur ${count} : </span>${esc(name)}</span><span class="sar-cand-state">${availabilityHtml(v)}${savedModelHtml(v)}</span></span>
        <span class="sar-cand-ops" role="group" aria-label="Déplacer ou retirer ${esc(name)}"${off?' aria-disabled="true"':''}>
          ${btn('up','up',`Monter ${name}`,i===0)}${btn('down','down',`Descendre ${name}`,i===count-1)}${btn('remove','remove',`Retirer ${name}`,false)}</span></li>`;
    }
    function addRowHtml(id,draft,writable){
      const s=snap(),harnesses=s.harnesses;
      if(!harnesses.length)return '<p class="hint">Aucun harness servi par le catalogue : rien à ajouter.</p>';
      const inList=ref=>draft.candidates.some(c=>Routing.sameRef(c,ref));
      const pickFor=h=>(h.models.find(m=>m.available&&!inList({agent:h.id,model:m.model}))||null);
      let sel=st.routeAdd[id]||null;
      if(!sel||!harnesses.some(h=>h.id===sel.agent)){const h=harnesses.find(x=>pickFor(x))||harnesses[0],m=pickFor(h);sel={agent:h.id,model:m?m.model:null}}
      const h=harnesses.find(x=>x.id===sel.agent);
      if(sel.model==null||!h.models.some(m=>m.model===sel.model&&m.available&&!inList({agent:h.id,model:m.model}))){const m=pickFor(h);sel={agent:h.id,model:m?m.model:null}}
      st.routeAdd[id]=sel;
      const hOpts=harnesses.map(x=>`<option value="${esc(x.id)}"${x.id===sel.agent?' selected':''}>${esc(x.label)}${x.available?'':' (indisponible)'}</option>`).join('');
      const mOpts=h.models.map(m=>{const dup=inList({agent:h.id,model:m.model}),dis=!m.available||dup;
        const why=dup?' — déjà dans la liste':!m.available?` — indisponible : ${m.unavailable_reason||'raison non donnée'}`:'';
        return `<option value="${esc(m.model)}"${m.model===sel.model?' selected':''}${dis?' disabled':''}>${esc(m.label)}${esc(why)}</option>`}).join('');
      const none=sel.model==null;
      return `<div class="sar-add" data-sar-add-row="${esc(id)}">
        <label class="sar-field"><span>Harness</span><select data-sar-add-agent="${esc(id)}"${writable?'':' disabled'}>${hOpts}</select></label>
        <label class="sar-field"><span>Modèle</span><select data-sar-add-model="${esc(id)}"${writable&&!none?'':' disabled'}>${none?'<option value="__none__" selected disabled>Aucun modèle disponible à ajouter</option>':''}${mOpts}</select></label>
        <button type="button" class="action sar-add-btn" data-sar-add="${esc(id)}"${writable&&!none?'':' disabled'}>${op('add')}Ajouter en dernier</button>
        ${!h.available?`<p class="hint sar-add-why">${esc(h.label)} est indisponible : ${esc(h.unavailable_reason||'raison non donnée')}</p>`:''}</div>`;
    }
    /* Une erreur de rendu de la section Modèles reste dans la section : la fiche et l'éditeur d'instructions restent. */
    function safeModelsHtml(role){
      try{return modelsHtml(role)}
      catch(e){
        logError('subagent_settings_routing_render_failed',e,{role_id:role.id});
        return `<section class="sar-block sar-route" aria-labelledby="sar-models-${esc(role.id)}"><h4 id="sar-models-${esc(role.id)}" tabindex="-1">${op('route','sar-h-g')}Modèles du rôle</h4>
          <div class="notice bad" role="alert">Cette section n’a pas pu afficher la politique servie : ${esc(e&&e.message||e)}<div class="hint">Le reste de la fiche et les instructions restent utilisables. Relisez la politique ; si l’erreur revient, signalez-la avec le code ci-dessous.</div>${codeLine('subagent_settings_routing_render_failed')}</div>
          <div class="sar-actions"><button type="button" class="action" data-sar-route-retry>Relire la politique</button></div></section>`;
      }
    }
    function modelsHtml(role){
      const id=role.id,head=`<h4 id="sar-models-${esc(id)}" tabindex="-1">${op('route','sar-h-g')}Modèles du rôle`;
      if(st.route.phase==='off')return '';
      if(st.route.phase==='loading'&&!snap())return `<section class="sar-block sar-route" aria-labelledby="sar-models-${esc(id)}">${head}</h4>${waitingHtml('Lecture de la politique des rôles…',st.route.startedAt||st.startedAt)}</section>`;
      if(st.route.phase==='error'&&!snap())return `<section class="sar-block sar-route" aria-labelledby="sar-models-${esc(id)}">${head}</h4>
        <div class="notice bad">Politique des rôles illisible : ${esc(st.route.error&&st.route.error.message)}<div class="hint">La fiche et les instructions restent utilisables.</div>${codeLine(st.route.error&&st.route.error.code)}</div>
        <div class="sar-actions"><button type="button" class="action" data-sar-route-retry>Réessayer</button></div></section>`;
      const r=routeOf(id);
      if(!r)return `<section class="sar-block sar-route" aria-labelledby="sar-models-${esc(id)}">${head}</h4><p class="hint">Aucune politique servie pour ce rôle : seuls les rôles actifs sont routés.</p></section>`;
      const draft=routeEffective(id),dirty=routeDirty(id),writable=routeWritable(),saving=st.routeSave&&st.routeSave.id===id;
      const count=draft.candidates.length;
      const fb=r.fallback,fbInapplicable=!r.explicit&&r.inherited_profile===fb.profile&&!dirty;
      const fbList=fb.candidates.length?fb.candidates.map(c=>esc(c.label||refLabel(c))).join(', '):'liste générale vide';
      const confirming=st.routeConfirmRestore===id;
      const missing=r.missing.length?`<div class="notice">Politique incomplète : la réponse ne donne pas ${r.missing.map(k=>`<code>${esc(k)}</code>`).join(', ')}.</div>`:'';
      const waitLabel=saving?(st.routeSave.action==='restore'?'Restauration de l’héritage…':st.routeSave.action==='reread'?'Relecture de la politique…':'Enregistrement de la politique du rôle…'):'';
      return `<section class="sar-block sar-route" aria-labelledby="sar-models-${esc(id)}" data-sar-route="${esc(id)}">
        ${head} ${provenanceChip(r)}${dirty?chip('non enregistré','warn'):''}</h4>
        <p class="sar-route-why">${esc(r.binding_reason||'')}${r.explicit?'':' Modifier cette liste la règle pour ce rôle seul ; les autres rôles et le profil ne changent pas.'}</p>
        ${snapshotStateHtml()}${missing}
        <ol class="sar-cands" aria-label="Candidats de ${esc(role.name)}, par ordre de préférence" data-sar-cands="${esc(id)}">
          ${count?draft.candidates.map((c,i)=>candidateRow(id,c,i,count,writable)).join(''):'<li class="sar-cand empty"><span class="hint">Liste vide : le serveur la refuserait. Ajoutez un candidat, ou restaurez l’héritage.</span></li>'}
        </ol>
        <p class="hint sar-cand-help">L’ordre est la préférence : le premier candidat lançable sert le rôle. Boutons ou Alt + flèches haut et bas pour réordonner.</p>
        ${addRowHtml(id,draft,writable)}
        <div class="sar-fallback">
          <label class="sar-switch"><input type="checkbox" role="switch" data-sar-fallback="${esc(id)}"${draft.allow_general_fallback?' checked':''}${writable?'':' disabled'} aria-describedby="sar-fb-${esc(id)}">
            <span class="sar-switch-track" aria-hidden="true"><span class="sar-switch-knob"></span></span><span>Repli automatique sur la liste générale</span></label>
          <p class="hint" id="sar-fb-${esc(id)}">${fbInapplicable?'Ce rôle hérite déjà de la liste générale : le repli n’ajoute rien tant qu’il n’est pas réglé pour lui.'
            :draft.allow_general_fallback?`Activé : liste épuisée, JARVIS tente la liste du profil « ${esc(fb.profile)} » (${fbList}).`:'Désactivé : liste épuisée, rien d’autre n’est tenté.'}</p></div>
        ${previewHtml(r,dirty)}
        ${saving?waitingHtml(waitLabel,st.routeSave.startedAt):''}
        ${routeNoticeHtml(id)}
        <div class="sar-actions">
          <button type="button" class="action primary" data-sar-route-save="${esc(id)}"${dirty&&count&&writable?'':' disabled'}>${saving&&st.routeSave.action==='put'?'Enregistrement…':'Enregistrer pour ce rôle'}</button>
          <button type="button" class="action" data-sar-route-discard="${esc(id)}"${dirty&&!st.routeSave?'':' disabled'}>Annuler mes changements</button>
          <button type="button" class="action danger" data-sar-route-restore="${esc(id)}"${r.restorable&&writable?'':' disabled'}${confirming?` aria-describedby="sar-restore-h-${esc(id)}"`:''}>${confirming?'Confirmer la restauration':'Restaurer l’héritage'}</button>
          ${confirming?`<span class="hint" id="sar-restore-h-${esc(id)}">La liste réglée pour ce rôle sera retirée : il suivra de nouveau le profil « ${esc(r.inherited_profile||r.default_profile)} ».</span>`:''}
        </div>
        <p class="hint">${r.explicit||dirty?'S’applique au prochain sous-agent lancé avec ce rôle ; aucun agent en cours n’est modifié.':''}</p>
        ${compatHtml()}</section>`;
    }
    /* Fiche du rôle choisi, sous le tableau de bord : deux colonnes quand la place le permet (mission, capacités,
       méthodes, consigne et instructions à gauche ; modèles du rôle à droite), une seule sinon, dans l'ordre du DOM. */
    function detailHtml(role){
      if(!role)return '<div class="empty">Choisissez un rôle dans la liste.</div>';
      const token=accentOf(role);
      const marker=`[${role.default_profile||'general'}] [${role.marker||role.id}]`;
      const aliases=(role.aliases||[]).length?(role.aliases||[]).map(a=>`<code>[${esc(a)}]</code>`).join(' ')+' <span class="hint">alias historique, lu comme ce rôle</span>':'<span class="hint">aucun</span>';
      const tools=(role.tools||[]).length?(role.tools||[]).map(t=>`<code class="sar-tool">${esc(t)}</code>`).join(' '):'<span class="hint">aucun outil déclaré</span>';
      const skills=(role.skills||[]).length?(role.skills||[]).map(s=>`<code>${esc(s)}</code>`).join(' '):'<span class="hint">aucun skill propre</span>';
      const loadout=role.loadout_role?`loadout <code>${esc(role.loadout_role)}</code>`:'<span class="hint">celui du profil</span>';
      const methods=(role.work_methods||[]);
      const ordered=[...methods].sort((a,b)=>(b===role.default_work_method)-(a===role.default_work_method));
      const state=role.edition_unavailable
        ?`<div class="notice bad" data-sar-edition-unavailable><strong>Indisponible dans cette édition.</strong> ${esc(role.edition_unavailable.message)} <code>${esc(role.edition_unavailable.code)}</code></div>`
        :!role.enabled
        ?`<div class="notice bad"><strong>Rôle désactivé.</strong> Le hook ne le reconnaît pas : un sous-agent qui l'annonce garde le marqueur dans son libellé et suit seulement sa consigne.</div>`
        :(!role.offered_to_brain?`<div class="notice info">Actif pour le hook, mais <strong>pas encore proposé au cerveau</strong> : seul un agent qui lance des agents peut le demander.</div>`:'');
      const missing=role.missing&&role.missing.length?`<div class="notice">Fiche incomplète : la réponse du serveur ne donne pas ${role.missing.map(k=>`<code>${esc(k)}</code>`).join(', ')}. Ces champs s'affichent vides.</div>`:'';
      const models=safeModelsHtml(role);
      return `<article class="sar-detail" style="${accentStyle(token)}" aria-labelledby="sar-title">
        <button type="button" class="action sar-back" data-sar-back>Revenir à la liste des rôles</button>
        <header class="sar-head">${identity(role,'lg')}<div><p class="sar-eyebrow">Fiche du rôle</p><h3 id="sar-title" class="sar-title" tabindex="-1">${esc(role.name)}</h3>
          <p class="sar-desc">${esc(role.description||'')}</p>
          <div class="sar-tags">${role.edition_unavailable?chip('Indisponible dans cette édition','bad'):role.enabled?chip('Actif','ok'):chip('Désactivé','bad')}
${role.edition_unavailable?'':(role.offered_to_brain?chip('Proposé au cerveau','ok'):chip('Pas proposé au cerveau'))+(role.offered_to_subagents?chip('Proposé aux agents','ok'):chip('Pas proposé aux agents'))}</div></div></header>
        ${state}${missing}
        <div class="sar-detail-cols${models?'':' single'}">
        <div class="sar-col-a"><section class="sar-block" aria-labelledby="sar-mission"><h4 id="sar-mission">Mission</h4><p class="sar-prose">${esc(role.mission||'')}</p>
          ${role.when_relevant?`<p class="hint"><strong>Quand l'employer :</strong> ${esc(role.when_relevant)}</p>`:''}
          ${facts([['Marqueur',`<code>${esc(marker)}</code>`],['Alias',aliases],['Identifiant',`<code>${esc(role.id)}</code>`]])}</section></div>
        ${models?`<div class="sar-col-s">${models}</div>`:''}
        <div class="sar-col-b"><section class="sar-block" aria-labelledby="sar-caps"><h4 id="sar-caps">Capacités ${chip('lecture seule')}</h4>
          ${facts([
            ['Lance des agents',yesNo(role.can_spawn,'Oui','Non')],
            ['Mission Owner',yesNo(role.can_own_mission,'Peut porter une mission','Ne porte pas de mission')],
            ['Réponse',role.constrained_output?'<span class="sar-yn yes">Forme imposée par ses instructions</span>':'<span class="sar-yn no">Libre</span>'],
            ['Outils',tools],['Savoirs',loadout],['Skills',skills],['Profil par défaut',`<code>${esc(role.default_profile||'general')}</code>`],
          ])}
          <p class="hint">Ces capacités suivent le code du registre ; aucun réglage ne les modifie.</p></section>
        <section class="sar-block" aria-labelledby="sar-methods"><h4 id="sar-methods">Work Methods ${chip('lecture seule')}</h4>
          ${methods.length?`<ul class="sar-methods">${ordered.map(id=>methodHtml(id,id===role.default_work_method)).join('')}</ul>`:'<p class="hint">Aucune Work Method : les instructions du rôle tiennent lieu de méthode.</p>'}
          ${methods.length&&!role.default_work_method?'<p class="hint">Aucune n’est apposée par défaut ; un Mission Owner pourra en choisir une.</p>':''}</section>
        ${role.can_own_mission?`<p class="hint" data-sar-learned-link>Approches observées de ce rôle et promotion en Work Method : ${opts.openTab?'<button type="button" class="sar-link" data-sar-open-learned>Avancé &amp; diagnostic › Work Methods apprises</button>':'Avancé &amp; diagnostic › Work Methods apprises'}.</p>`:''}
        <section class="sar-block" aria-labelledby="sar-compose"><h4 id="sar-compose">Consigne transmise au sous-agent</h4>${compositionHtml(role)}</section>
        ${editorHtml(role)}</div>
        </div>
      </article>`;
    }

    function instanceRow(task){
      const res=resolveMarker(task.role);
      const title=String(task.description||'').replace(/^(\s*\[[^\]]{1,40}\]\s*)+/,'')||'(sans libellé)';
      let ident,label;
      const generic=(glyph,badge)=>`<span class="sar-ident sar-sm" style="${accentStyle('slate')}"><span class="sar-tile">${icon(glyph)}</span><span class="sar-badge">${badge}</span></span>`;
      if(res.role){ident=identity(res.role,'sm');label=esc(res.role.name)+(res.status==='alias'?` <span class="hint">via l'alias <code>[${esc(res.marker)}]</code></span>`:'')+(res.status==='disabled'?' '+chip('désactivé','bad'):'')}
      else if(res.status==='alias'){ident=generic('agent','?');label=`Alias <code>[${esc(res.marker)}]</code> du rôle <code>${esc(res.roleId)}</code> <span class="hint">absent de la liste servie</span>`}
      else if(res.status==='unknown'){ident=generic('unknown','?');label=`Marqueur hors registre <code>[${esc(res.marker)}]</code>`}
      else{ident=generic('agent','GEN');label='Général, <span class="hint">aucun rôle déclaré</span>'}
      return `<li class="sar-inst">${ident}<span class="sar-item-text"><span class="sar-item-name">${esc(title)}</span><span class="sar-item-meta">${label}${task.ephemeral?chip('éphémère'):''}</span></span></li>`;
    }
    function instancesHtml(){
      const t=st.tasks;
      const running=t.phase==='ready'?t.items.filter(x=>x&&x.status==='running'&&x.kind!=='shell'):[];
      let body,count;
      if(t.phase==='loading'){body=waitingHtml('Lecture des instances…',t.startedAt||st.startedAt);count='lecture…'}
      else if(t.phase==='error'){body=`<div class="notice bad">Instances illisibles : ${esc(t.error.message)}${codeLine(t.error.code)}</div>`;count='illisibles'}
      else{
        count=String(running.length);
        body=running.length?`<ul class="sar-list" aria-label="Instances en cours">${running.map(instanceRow).join('')}</ul>`:'<p class="hint">Aucun sous-agent en cours.</p>';
      }
      return `<details class="sar-instances" data-sar-instances${st.instancesOpen?' open':''}><summary>Instances en cours <span class="tag${t.phase==='error'?' bad':''}">${esc(count)}</span></summary>
        ${body}<div class="sar-actions"><button type="button" class="action" data-sar-tasks-refresh${t.phase==='loading'?' disabled':''}>Actualiser</button></div></details>`;
    }
    function summaryHtml(){
      const all=roles(),active=all.filter(r=>r.enabled&&!r.edition_unavailable).length,brain=all.filter(r=>r.enabled&&r.offered_to_brain&&!r.edition_unavailable).length,mod=all.filter(r=>r.modified).length;
      const schema=st.payload.schema_version!==2?`<div class="notice">Version du registre inattendue (<code>${esc(st.payload.schema_version??'absente')}</code>, cet écran lit la version 2) : les champs absents s'affichent vides.</div>`:'';
      const dropped=st.payload.dropped?`<div class="notice">${st.payload.dropped} entrée(s) sans identifiant ignorée(s).</div>`:'';
      return `${schema}${dropped}<p class="sar-summary">${all.length} rôles · ${active} actifs · ${brain} proposés au cerveau${mod?` · ${mod} aux instructions modifiées`:''}</p>`;
    }

    /* Chaque rendu remplace l'hôte (lecture des instances, compteur, enregistrement) : le contrôle qui avait le focus
       le reprend (`keepFocus` du shell), sinon il tomberait sur `body` — par exemple le lien vers Modèles des
       sous-agents, redessiné quand les instances arrivent (finitions avant la Slice 10). */
    function render(){
      const UI=root.JarvisSettingsUI;
      if(UI&&typeof UI.keepFocus==='function'&&host.ownerDocument)UI.keepFocus(host,draw);else draw();
    }
    function draw(){
      if(st.destroyed)return;
      if(st.phase==='loading'){host.innerHTML=`<div class="sar-state">${waitingHtml('Lecture du registre des rôles…',st.startedAt)}</div>`;tick();return}
      if(st.phase==='error'){
        host.innerHTML=`<div class="sar-state"><div class="notice bad" role="alert"><strong>Registre des rôles illisible.</strong> Réponse : « ${esc(st.error.message)} ».
          <div class="hint">Rien n'a été modifié. ${esc(loadAdvice(st.error.code))}</div>${codeLine(st.error.code)}</div>
          <button type="button" class="action primary" data-sar-retry>Réessayer</button></div>`;
        bind();tick();return;
      }
      try{renderReady()}
      catch(e){
        /* Une réponse que l'écran ne sait pas afficher devient une erreur visible, jamais un écran figé. */
        const err=new Error('affichage impossible : '+(e&&e.message||e));err.code='subagent_settings_render_failed';
        logError('subagent_settings_render_failed',e,{schema_version:st.payload&&st.payload.schema_version});
        st.phase='error';st.error=err;render();
      }
    }
    function renderReady(){
      if(view==='work_methods'){host.innerHTML=learnedHtml();bind();tick();return}
      if(!roles().length){
        host.innerHTML=`<div class="sar-state">${summaryHtml()}<div class="notice bad" role="status"><strong>Aucun rôle dans le registre.</strong> Les sous-agents s'exécutent alors sans rôle, comme agents généraux.</div></div>`;
        tick();return;
      }
      if(!roleById(st.selected))st.selected=roles()[0].id;
      if(st.menu&&!roleById(st.menu))st.menu=null;
      host.innerHTML=boardHtml();
      bind();tick();
    }

    /* Compteur vivant des attentes : un seul minuteur, arrêté dès qu'aucune attente n'est affichée. */
    function tick(){
      const waiting=!st.destroyed&&(st.phase==='loading'||(view==='roles'?st.tasks.phase==='loading'||!!st.save||st.route.phase==='loading'||!!st.routeSave:st.learned.phase==='loading'||!!st.promote));
      if(waiting&&ticker==null)ticker=setTimer(()=>{
        if(!host.querySelectorAll)return;
        host.querySelectorAll('[data-sar-since]').forEach(el=>{el.textContent=elapsed(Number(el.dataset.sarSince))+' s'});
      },1000);
      if(!waiting&&ticker!=null){clearTimer(ticker);ticker=null}
    }

    function select(id,focus){
      if(!roleById(id))return;
      st.selected=id;st.menu=null;st.confirmReset=null;st.confirmPromote=null;st.routeConfirmRestore=null;render();
      /* La fiche est sous le tableau de bord : l'ouvrir la fait venir à l'écran et lui donne le focus. */
      if(focus==='detail'){
        const title=host.querySelector('#sar-title'),card=host.querySelector('.sar-detail');
        if(card&&card.scrollIntoView)card.scrollIntoView({block:'start'});
        if(title&&title.focus)title.focus({preventScroll:true});
        return;
      }
      if(focus){const b=host.querySelector(`[data-sar-role="${cssId(id)}"]`);if(b&&b.focus)b.focus()}
    }
    /* Région live courte, hors du rendu : seules les notices y sont annoncées, jamais la fiche entière. */
    const live=(()=>{
      const doc=host.ownerDocument;
      if(!doc||!host.insertAdjacentElement)return null;
      const el=doc.createElement('div');el.className='sar-live';el.setAttribute('aria-live','polite');el.setAttribute('data-sar-live','');
      host.insertAdjacentElement('beforebegin',el);return el;
    })();
    function announce(text){if(live){live.textContent='';live.textContent=text||''}}

    function bind(){
      if(!host.querySelectorAll)return;
      const retry=host.querySelector('[data-sar-retry]');if(retry)retry.addEventListener('click',()=>load());
      host.querySelectorAll('[data-sar-role]').forEach(b=>{
        b.addEventListener('click',()=>select(b.dataset.sarRole,'detail'));
        b.addEventListener('keydown',ev=>{
          const ids=roles().map(r=>r.id),i=ids.indexOf(b.dataset.sarRole);
          const next={ArrowDown:i+1,ArrowUp:i-1,Home:0,End:ids.length-1}[ev.key];
          if(next===undefined)return;
          ev.preventDefault();select(ids[(next+ids.length)%ids.length],true);
        });
      });
      host.querySelectorAll('[data-sar-editor]').forEach(d=>d.addEventListener('toggle',()=>{st.openEditor[d.dataset.sarEditor]=d.open}));
      host.querySelectorAll('[data-sar-text]').forEach(area=>area.addEventListener('input',()=>{
        const role=roleById(area.dataset.sarText);if(!role)return;
        st.drafts[role.id]=area.value;
        const dirty=isDirty(role),busy=!!st.save;
        const count=host.querySelector('[data-sar-count]');if(count)count.textContent=countText(role,area.value,dirty);
        const save=host.querySelector(`[data-sar-save="${cssId(role.id)}"]`),discard=host.querySelector(`[data-sar-discard="${cssId(role.id)}"]`);
        if(save)save.disabled=!dirty||busy||!canSave(role,area.value);if(discard)discard.disabled=!dirty||busy;
      }));
      host.querySelectorAll('[data-sar-save]').forEach(b=>b.addEventListener('click',()=>save(b.dataset.sarSave)));
      host.querySelectorAll('[data-sar-discard]').forEach(b=>b.addEventListener('click',()=>{delete st.drafts[b.dataset.sarDiscard];delete st.notice[b.dataset.sarDiscard];render()}));
      host.querySelectorAll('[data-sar-reset]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarReset;
        if(st.confirmReset!==id){st.confirmReset=id;render();const again=host.querySelector(`[data-sar-reset="${cssId(id)}"]`);if(again&&again.focus)again.focus();return}
        reset(id);
      }));
      const refresh=host.querySelector('[data-sar-tasks-refresh]');if(refresh)refresh.addEventListener('click',()=>loadTasks());
      const inst=host.querySelector('[data-sar-instances]');if(inst)inst.addEventListener('toggle',()=>{st.instancesOpen=inst.open});
      host.querySelectorAll('[data-sar-reread]').forEach(b=>b.addEventListener('click',()=>reread(b.dataset.sarReread)));
      bindRouting();
      bindBoard();
      const back=host.querySelector('[data-sar-back]');if(back)back.addEventListener('click',()=>{const b=host.querySelector(`[data-sar-role="${cssId(st.selected)}"]`);if(b){if(b.scrollIntoView)b.scrollIntoView({block:'center'});b.focus()}});
      const models=host.querySelector('[data-sar-open-models]');if(models)models.addEventListener('click',()=>opts.openTab('runtime_cli'));
      const learned=host.querySelector('[data-sar-open-learned]');if(learned)learned.addEventListener('click',()=>opts.openTab('work_methods'));
      const learnedRetry=host.querySelector('[data-sar-learned-retry]');if(learnedRetry)learnedRetry.addEventListener('click',()=>loadCandidates());
      host.querySelectorAll('[data-sar-promote]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarPromote;
        if(st.confirmPromote!==id){st.confirmPromote=id;st.promoteNotice=null;render();const again=host.querySelector(`[data-sar-promote="${cssId(id)}"]`);if(again&&again.focus)again.focus();return}
        promote(id);
      }));
      const cancel=host.querySelector('[data-sar-promote-cancel]');if(cancel)cancel.addEventListener('click',()=>{
        const id=st.confirmPromote;st.confirmPromote=null;render();
        /* Le focus revient au bouton de promotion, jamais perdu en haut de page. */
        const back=id&&host.querySelector(`[data-sar-promote="${cssId(id)}"]`);if(back&&back.focus)back.focus();
      });
    }


    /* --- Modèles du rôle : liaisons ------------------------------------------------------------------------ */
    /* Un id de rôle vient du serveur : échappé avant d'entrer dans un sélecteur. */
    const cssId=v=>root.CSS&&typeof root.CSS.escape==='function'?root.CSS.escape(String(v)):String(v).replace(/[^a-zA-Z0-9_-]/g,c=>'\\'+c);
    function focusSel(sel){const el=host.querySelector&&host.querySelector(sel);if(el&&el.focus){el.focus();return true}return false}

    /* --- Tableau de bord : actions « … » d'un rôle et renvois vers la fiche (Slice 03) ------------------------- */
    /* Ouvre la fiche du rôle sur sa section Modèles (en-tête de matrice, action « Régler les modèles »). */
    function gotoModels(id){
      if(!roleById(id))return false;
      select(id);
      const h=host.querySelector&&host.querySelector(`#sar-models-${cssId(id)}`);
      if(!h)return false;
      if(h.scrollIntoView)h.scrollIntoView({block:'start'});if(h.focus)h.focus({preventScroll:true});
      return true;
    }
    function gotoInstructions(id){
      if(!roleById(id))return false;
      st.openEditor[id]=true;select(id);
      const area=host.querySelector&&host.querySelector(`[data-sar-text="${cssId(id)}"]`);
      if(!area)return false;
      if(area.scrollIntoView)area.scrollIntoView({block:'center'});if(area.focus)area.focus({preventScroll:true});
      return true;
    }
    /* Une seule divulgation ouverte ; la fermer rend le focus à son bouton « … ». */
    function openMenu(id,on,focus){
      if(id!=null&&!roleById(id))return false;
      st.menu=on===false||id==null?null:id;render();
      if(focus&&st.menu)focusSel(`[data-sar-menu="${cssId(st.menu)}"] [data-sar-menu-act]`);
      else if(focus&&id!=null)focusSel(`[data-sar-more="${cssId(id)}"]`);
      return true;
    }
    function menuAct(act,id){
      st.menu=null;
      logInfo('subagent_settings.role_action',{role_id:id,action:act});
      if(act==='models'&&gotoModels(id))return;
      if(act==='instructions'&&gotoInstructions(id))return;
      select(id,'detail');
    }
    /* Clic hors de la divulgation ouverte : elle se ferme, sans voler le focus de ce qui a été cliqué. Pas de nouveau
       rendu ici : remplacer le DOM entre `pointerdown` et `click` avalerait le clic visé (une autre ligne, un bouton). */
    const doc0=host.ownerDocument;
    const outside=ev=>{
      if(!st.menu||st.destroyed||!host.querySelector)return;
      const t=ev.target,inMenu=t&&t.closest&&t.closest('[data-sar-menu],[data-sar-more]');
      if(inMenu)return;
      const id=st.menu;st.menu=null;
      const menu=host.querySelector(`[data-sar-menu="${cssId(id)}"]`),more=host.querySelector(`[data-sar-more="${cssId(id)}"]`);
      if(menu)menu.remove();if(more)more.setAttribute('aria-expanded','false');
      const row=more&&more.closest&&more.closest('.sar-row');if(row)row.classList.remove('menu-open');
    };
    if(doc0&&doc0.addEventListener)doc0.addEventListener('pointerdown',outside,true);
    function bindBoard(){
      if(!host.querySelectorAll)return;
      host.querySelectorAll('[data-sar-more]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarMore;openMenu(id,st.menu!==id,true);
      }));
      host.querySelectorAll('[data-sar-menu]').forEach(menu=>menu.addEventListener('keydown',ev=>{
        const items=[...menu.querySelectorAll('[data-sar-menu-act]')],i=items.indexOf(ev.target&&ev.target.closest?ev.target.closest('[data-sar-menu-act]'):null);
        /* Échap consommée : la divulgation se ferme, les Réglages restent ouverts. */
        if(ev.key==='Escape'){ev.preventDefault();ev.stopPropagation();openMenu(menu.dataset.sarMenu,false,true);return}
        const next={ArrowDown:i+1,ArrowUp:i-1,Home:0,End:items.length-1}[ev.key];
        if(next===undefined||!items.length)return;
        ev.preventDefault();items[(next+items.length)%items.length].focus();
      }));
      host.querySelectorAll('[data-sar-menu-act]').forEach(b=>b.addEventListener('click',()=>menuAct(b.dataset.sarMenuAct,b.dataset.sarMenuRole)));
    }
    /* Après un déplacement, le focus suit le candidat déplacé (même commande, sinon une autre de sa ligne). */
    function focusCandidate(id,i,prefer){
      const at=k=>`[data-sar-cand-role="${cssId(id)}"][data-sar-cand-i="${i}"][data-sar-cand-op="${k}"]:not(:disabled)`;
      for(const k of [prefer,'up','down','remove'])if(k&&focusSel(at(k)))return;
      focusSel(`[data-sar-add-agent="${cssId(id)}"]`);
    }
    function bindRouting(){
      if(!host.querySelectorAll)return;
      host.querySelectorAll('[data-sar-cand-op]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarCandRole,i=Number(b.dataset.sarCandI),kind=b.dataset.sarCandOp;
        if(kind==='remove')removeCandidate(id,i,true);else moveCandidate(id,i,kind==='up'?-1:1,true);
      }));
      /* Réordonner au clavier sans viser un bouton : Alt + flèche sur n'importe quelle commande de la ligne. */
      host.querySelectorAll('.sar-cand[data-sar-cand]').forEach(li=>li.addEventListener('keydown',ev=>{
        if(!ev.altKey||(ev.key!=='ArrowUp'&&ev.key!=='ArrowDown'))return;
        const b=li.querySelector('[data-sar-cand-op]');if(!b)return;
        ev.preventDefault();moveCandidate(b.dataset.sarCandRole,Number(b.dataset.sarCandI),ev.key==='ArrowUp'?-1:1,true);
      }));
      host.querySelectorAll('[data-sar-add-agent]').forEach(el=>el.addEventListener('change',()=>{
        const id=el.dataset.sarAddAgent;st.routeAdd[id]={agent:el.value,model:null};render();focusSel(`[data-sar-add-agent="${cssId(id)}"]`);
      }));
      host.querySelectorAll('[data-sar-add-model]').forEach(el=>el.addEventListener('change',()=>{
        const id=el.dataset.sarAddModel;if(el.value==='__none__')return;st.routeAdd[id]={...(st.routeAdd[id]||{}),model:el.value};
      }));
      host.querySelectorAll('[data-sar-add]').forEach(b=>b.addEventListener('click',()=>addCandidate(b.dataset.sarAdd,null,true)));
      host.querySelectorAll('[data-sar-fallback]').forEach(el=>el.addEventListener('change',()=>{
        const id=el.dataset.sarFallback;setFallback(id,el.checked);focusSel(`[data-sar-fallback="${cssId(id)}"]`);
      }));
      host.querySelectorAll('[data-sar-route-save]').forEach(b=>b.addEventListener('click',()=>saveRoute(b.dataset.sarRouteSave)));
      host.querySelectorAll('[data-sar-route-discard]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarRouteDiscard;discardRoute(id);focusSel(`#sar-models-${cssId(id)}`);
      }));
      host.querySelectorAll('[data-sar-route-restore]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarRouteRestore;
        if(st.routeConfirmRestore!==id){st.routeConfirmRestore=id;render();focusSel(`[data-sar-route-restore="${cssId(id)}"]`);return}
        restoreRoute(id);
      }));
      host.querySelectorAll('[data-sar-route-reread]').forEach(b=>b.addEventListener('click',()=>rereadRouting(b.dataset.sarRouteReread==='*'?st.selected:b.dataset.sarRouteReread)));
      host.querySelectorAll('[data-sar-route-retry]').forEach(b=>b.addEventListener('click',()=>{routePromise=loadRouting()}));
      host.querySelectorAll('[data-sar-route-goto]').forEach(b=>b.addEventListener('click',()=>gotoModels(b.dataset.sarRouteGoto)));
      host.querySelectorAll('[data-settings-open]').forEach(b=>b.addEventListener('click',()=>{if(opts.openTab)opts.openTab(b.dataset.settingsOpen)}));
    }

    /* --- E/S ------------------------------------------------------------- */
    async function load(){
      st.phase='loading';st.error=null;st.startedAt=now();render();
      try{
        const data=await fetchJson(ROLES_PATH);
        if(!data||!Array.isArray(data.roles)){const e=new Error('réponse sans liste de rôles');e.code='subagent_settings_payload_invalid';throw e}
        if(st.destroyed)return data;
        st.payload=normalizePayload(data);st.phase='ready';
        logInfo('subagent_settings.loaded',{roles:data.roles.length,schema_version:data.schema_version});
      }catch(e){
        if(st.destroyed)return null;
        st.phase='error';st.error=e;logError('subagent_settings_load_failed',e,{path:ROLES_PATH});
      }finally{render()}
      /* Chaque vue ne lit que ce qu'elle montre : les instances pour les rôles, les candidats pour les Work Methods. */
      if(st.phase==='ready'){if(view==='work_methods')loadCandidates();else{loadTasks();if(routing&&!snap())routePromise=loadRouting()}}
      return st.payload;
    }
    async function loadTasks(){
      st.tasks={phase:'loading',error:null,items:st.tasks.items,startedAt:now()};render();
      /* `render` ne lève pas (il passe en état d'erreur) ; la lecture des instances reste indépendante. */
      try{
        const data=await fetchJson(TASKS_PATH);
        if(st.destroyed)return;
        st.tasks={phase:'ready',error:null,items:Array.isArray(data&&data.tasks)?data.tasks:[]};
      }catch(e){
        if(st.destroyed)return;
        st.tasks={phase:'error',error:e,items:[]};logError('subagent_settings_tasks_failed',e,{path:TASKS_PATH});
      }finally{render()}
    }
    async function loadCandidates(){
      st.learned={...st.learned,phase:'loading',error:null,startedAt:now()};render();
      try{
        const data=await fetchJson(CANDIDATES_PATH);
        if(st.destroyed)return;
        if(!data||!Array.isArray(data.candidates)){const e=new Error('réponse sans liste de candidats');e.code='subagent_settings_payload_invalid';throw e}
        st.learned={phase:'ready',error:null,items:data.candidates.filter(c=>c&&typeof c==='object'),
          scan:data.scan&&typeof data.scan==='object'?data.scan:{},
          thresholds:data.thresholds&&typeof data.thresholds==='object'?data.thresholds:{}};
        logInfo('subagent_settings.candidates_loaded',{candidates:data.candidates.length});
      }catch(e){
        if(st.destroyed)return;
        st.learned={phase:'error',error:e,items:[],thresholds:{}};logError('subagent_settings_candidates_failed',e,{path:CANDIDATES_PATH});
      }finally{render()}
    }
    /* Promotion d'un candidat, confirmée en deux temps : le brouillon tel que servi, la révision qu'il suit. */
    async function promote(candidateId){
      if(st.promote)return;
      const c=st.learned.items.find(x=>x&&x.candidate_id===candidateId);
      const draft=c&&c.draft&&typeof c.draft==='object'?c.draft:null;
      if(!c||c.status!=='candidate'||!draft){
        /* Jamais un bouton muet : l'écran dit pourquoi rien ne part, et relit. */
        const e=new Error('candidat introuvable ou plus éligible dans la vue de l’écran');e.code='subagent_settings_candidate_stale';
        logError('subagent_settings_promotion_failed',e,{candidate_id:candidateId});
        st.promoteNotice={tone:'bad',code:e.code,text:'Promotion impossible : cette approche n’est plus candidate dans la vue de l’écran. Rien n’a été écrit.',hint:'Les approches sont relues.'};
        st.confirmPromote=null;announce(st.promoteNotice.text);await loadCandidates();return;
      }
      const key=`${draft.method_id}@${draft.version}`;
      st.promote={candidateId,startedAt:now()};st.confirmPromote=null;st.promoteNotice=null;render();
      try{
        const result=await fetchJson(PROMOTIONS_PATH,{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({candidate_id:candidateId,expected_version:Number(draft.version)-1,method:draft})});
        logInfo('subagent_settings.method_promoted',{candidate_id:candidateId,method:key});
        const snap=result&&result.snapshot;
        st.promoteNotice=snap&&snap.written===false
          ?{tone:'bad',code:snap.code||'',text:`Méthode ${key} publiée, mais pas encore transmise aux sous-agents.`,hint:'Le prochain sous-agent recevra encore l’ancienne version ; la transmission est retentée à la prochaine lecture des Work Methods ou au redémarrage du Control Center.'}
          :{tone:'ok',text:`Méthode ${key} publiée.`,hint:'Elle s’applique au prochain sous-agent lancé avec un rôle qui cite cette méthode.'};
        try{await refreshRoles()}catch(again){logError('subagent_settings_refresh_failed',again,{candidate_id:candidateId})}
      }catch(e){
        logError('subagent_settings_promotion_failed',e,{candidate_id:candidateId,code:e.code||null});
        st.promoteNotice=UNKNOWN_OUTCOME.has(e.code)
          ?{tone:'bad',code:e.code,text:`Résultat inconnu : ${String(e.message||'').replace(/\.?$/,'.')}`,hint:'Les approches sont relues : si elle apparaît « Promue », la promotion a bien été enregistrée.'}
          :{tone:'bad',code:e.code||'',text:`Promotion refusée. Refus du serveur : « ${e.message||'erreur sans message'} ».`,
            hint:STALE_CANDIDATE_CODES.has(e.code)?'Les approches ont changé depuis l’ouverture de l’écran : elles sont relues.':'Rien n’a été écrit.'};
      }finally{
        st.promote=null;announce(st.promoteNotice&&st.promoteNotice.text);
        await loadCandidates();
        /* Le focus va sur la notice qui dit ce qui s'est passé. */
        const n=host.querySelector&&host.querySelector('[data-sar-promote-notice]');if(n&&n.focus){n.tabIndex=-1;n.focus()}
      }
    }
    async function refreshRoles(){
      const data=await fetchJson(ROLES_PATH);
      if(!data||!Array.isArray(data.roles)){const e=new Error('réponse sans liste de rôles');e.code='subagent_settings_payload_invalid';throw e}
      st.payload=normalizePayload(data);
    }
    function snapshotNote(body){
      const snap=body&&body.subagent_roles_snapshot;
      if(snap&&snap.written===false)return {tone:'bad',text:'Enregistré, mais pas encore transmis aux sous-agents : le prochain lancé suivra l’ancienne version.',code:snap.code||'',hint:snap.error||''};
      return null;
    }
    function setNotice(id,notice){st.notice[id]=notice;announce(notice.text)}
    /* Relecture après une écriture : son échec ne dit jamais « rien n'a été écrit ». */
    async function rereadAfter(id,ok,failure){
      try{await refreshRoles();setNotice(id,ok());return true}
      catch(e){
        logError('subagent_settings_refresh_failed',e,{role_id:id,code:e.code||null});
        setNotice(id,{tone:'bad',reread:true,code:e.code||'',text:`${failure||'Enregistré'} ; la relecture a échoué : « ${e.message||'erreur sans message'} ».`,
          hint:'La fiche montre peut-être encore l’ancienne version. Réessayez la relecture avant toute autre modification.'});
        return false;
      }
    }
    async function mutate(id,action){
      const role=roleById(id);if(!role||st.save)return;
      const text=String(draftOf(role)??'');
      st.save={id,action,startedAt:now()};st.confirmReset=null;delete st.notice[id];render();
      try{
        const body=action==='reset'?{action:'reset'}
          :{action:'edit',text,base_revision:role.default_revision,expected_effective_revision:role.revision};
        let result;
        try{
          result=await fetchJson(PROMPT_PATH(role.prompt_id||'subagent_role.'+id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        }catch(e){
          logError(action==='reset'?'subagent_settings_reset_failed':'subagent_settings_save_failed',e,{role_id:id,code:e.code||null});
          if(action==='edit')st.drafts[id]=text;
          if(UNKNOWN_OUTCOME.has(e.code)){
            /* Pas de réponse : le serveur a peut-être écrit. On relit, puis on dit ce que montre la relecture. */
            st.save={id,action:'reread',startedAt:now()};render();
            await rereadAfter(id,()=>{
              const saved=roleById(id),same=saved&&(action==='reset'?!saved.modified:saved.instructions===text);
              if(same&&action==='edit')delete st.drafts[id];
              return {tone:'bad',code:e.code,text:`Résultat inconnu : ${String(e.message||'').replace(/\.?$/,'.')} Relisez avant de réenregistrer.`,
                hint:same?'La relecture montre que la modification a bien été enregistrée.':'La relecture montre la version précédente : la modification n’a pas été enregistrée. Votre texte reste dans le champ.'};
            },'Résultat inconnu');
          }else if(CONFLICT_CODES.has(e.code)){
            /* Conflit de révision : la version enregistrée a changé ailleurs. Le texte reste dans le champ ; les
               révisions sont relues pour qu'un second enregistrement, voulu, réussisse. */
            try{await refreshRoles()}catch(again){logError('subagent_settings_refresh_failed',again,{role_id:id})}
            setNotice(id,{tone:'bad',code:e.code,text:e.code==='prompt_override_stale'
              ?'Le défaut de ce rôle a changé depuis l’ouverture de l’écran. Votre texte est conservé dans le champ.'
              :'Ces instructions ont été modifiées ailleurs depuis l’ouverture de l’écran. Votre texte est conservé dans le champ.',
              hint:'La version enregistrée a été relue. Relisez votre texte, puis enregistrez à nouveau pour la remplacer, ou annulez vos changements pour la garder.'});
          }else{
            setNotice(id,{tone:'bad',code:e.code||'',text:`${action==='reset'?'Retour au défaut refusé':'Enregistrement refusé'}. Refus du serveur : « ${e.message||'erreur sans message'} ». Rien n’a été écrit.`});
          }
          return;
        }
        delete st.drafts[id];
        logInfo('subagent_settings.instructions_'+action,{role_id:id,changed:!!(result&&result.mutation&&result.mutation.changed)});
        await rereadAfter(id,()=>snapshotNote(result)||{tone:'ok',text:action==='reset'?'Instructions revenues au défaut du code.':'Instructions enregistrées. Elles s’appliquent au prochain sous-agent lancé avec ce rôle.'});
      }finally{
        st.save=null;st.openEditor[id]=true;render();
        const n=host.querySelector&&host.querySelector('[data-sar-notice]');if(n&&n.focus){n.tabIndex=-1;n.focus()}
      }
    }
    async function reread(id){
      if(st.save)return;
      st.save={id,action:'reread',startedAt:now()};render();
      try{await rereadAfter(id,()=>({tone:'ok',text:'Version enregistrée relue.'}))}
      finally{st.save=null;render()}
    }
    const save=id=>mutate(id,'edit');
    const reset=id=>mutate(id,'reset');


    /* --- Modèles du rôle : brouillon et écritures ------------------------------------------------------------
       Le brouillon d'un rôle ne touche que ce rôle ; une écriture n'envoie que lui (PUT ou DELETE de son id). */
    function editRoute(id,fn){
      const base=routeEffective(id);if(!base||!routeWritable())return false;
      const d={candidates:base.candidates.map(c=>({...c})),allow_general_fallback:base.allow_general_fallback};
      if(fn(d)===false)return false;
      st.routeDrafts[id]=d;if(!routeDirty(id))delete st.routeDrafts[id];
      delete st.routeNotice[id];st.routeConfirmRestore=null;render();return true;
    }
    function moveCandidate(id,i,delta,focus){
      const to=i+delta;let name='';
      const ok=editRoute(id,d=>{if(i<0||to<0||to>=d.candidates.length)return false;const [c]=d.candidates.splice(i,1);d.candidates.splice(to,0,c);name=refLabel(c)});
      if(!ok)return false;
      announce(`${name} : position ${to+1} sur ${routeEffective(id).candidates.length}.`);
      if(focus)focusCandidate(id,to,delta<0?'up':'down');
      return true;
    }
    function removeCandidate(id,i,focus){
      let name='';
      const ok=editRoute(id,d=>{if(i<0||i>=d.candidates.length)return false;name=refLabel(d.candidates.splice(i,1)[0])});
      if(!ok)return false;
      const n=routeEffective(id).candidates.length;announce(`${name} retiré de la liste${n?'':' : la liste est vide'}.`);
      if(focus){if(n)focusCandidate(id,Math.min(i,n-1),'remove');else focusSel(`[data-sar-add-agent="${cssId(id)}"]`)}
      return true;
    }
    function addCandidate(id,ref,focus){
      const pick=ref||st.routeAdd[id];
      if(!pick||pick.model==null)return false;
      const r={agent:String(pick.agent),model:String(pick.model)};
      const ok=editRoute(id,d=>{if(d.candidates.some(c=>Routing.sameRef(c,r)))return false;d.candidates.push(r)});
      if(!ok)return false;
      delete st.routeAdd[id];render();
      const n=routeEffective(id).candidates.length;announce(`${refLabel(r)} ajouté en position ${n} sur ${n}.`);
      if(focus)focusSel(`[data-sar-add="${cssId(id)}"]:not(:disabled)`)||focusCandidate(id,n-1,'up');
      return true;
    }
    function setFallback(id,on){return editRoute(id,d=>{d.allow_general_fallback=!!on})}
    function discardRoute(id){delete st.routeDrafts[id];delete st.routeNotice[id];st.routeConfirmRestore=null;render()}
    function setRouteNotice(id,n){st.routeNotice[id]=n;announce(n.text)}
    /* Seul un instantané complet remplace l'écran ; un instantané dégradé ou vide ne l'efface jamais. */
    function applySnapshot(raw){
      if(!raw||typeof raw!=='object'||raw.degraded||!Array.isArray(raw.roles)||!raw.roles.length)return false;
      try{st.route.snap=Routing.normalizeSnapshot(raw);st.route.stale=null;return true}
      catch(e){logError('subagent_settings_routing_payload_invalid',e,{});return false}
    }
    async function loadRouting(){
      if(!routing)return null;
      st.route={...st.route,phase:'loading',error:null,startedAt:now()};render();
      try{
        const data=await routing.load();
        if(st.destroyed)return null;
        const next=Routing.normalizeSnapshot(data);
        st.route={...st.route,phase:'ready',error:null,snap:next,stale:null};
        logInfo('subagent_settings.routing_loaded',{revision:next.revision,roles:next.roles.length,explicit:next.roles.filter(r=>r.explicit).map(r=>r.role_id)});
      }catch(e){
        if(st.destroyed)return null;
        st.route={...st.route,phase:'error',error:e};logError('subagent_settings_routing_failed',e,{code:e&&e.code||null});
      }finally{render()}
      return st.route.snap;
    }
    const sameWrite=(r,action,draft)=>action==='restore'?!!r&&!r.explicit
      :!!r&&r.explicit&&Routing.sameList(r.candidates,draft.candidates)&&r.allow_general_fallback===draft.allow_general_fallback;
    async function refreshRouting(){st.route.snap=Routing.normalizeSnapshot(await routing.load());st.route.stale=null;st.route.phase='ready';st.route.error=null}
    async function writeRoute(id,action){
      const r=routeOf(id);if(!r||!routeWritable())return;
      const draft=routeEffective(id),base=snap().revision;
      const body={base_revision:base,candidates:refsOf(draft.candidates),allow_general_fallback:draft.allow_general_fallback};
      st.routeSave={id,action,startedAt:now()};st.routeConfirmRestore=null;delete st.routeNotice[id];render();
      const failCode=action==='restore'?'subagent_settings_routing_restore_failed':'subagent_settings_routing_save_failed';
      try{
        let res;
        try{res=action==='restore'?await routing.restore(id,{base_revision:base}):await routing.put(id,body)}
        catch(e){
          logError(failCode,e,{role_id:id,code:e&&e.code||null});
          if(!Routing.UNKNOWN_OUTCOME.has(e&&e.code)){
            setRouteNotice(id,{tone:'bad',code:e&&e.code||'',text:`${action==='restore'?'Restauration':'Enregistrement'} impossible : « ${e&&e.message||e} ». Rien n’a été écrit par cet écran.`});return;
          }
          /* Pas de réponse : le serveur a peut-être écrit. Relecture forcée, puis on dit ce qu'elle montre. */
          st.routeSave={id,action:'reread',startedAt:now()};render();
          try{await refreshRouting()}
          catch(again){
            logError('subagent_settings_routing_refresh_failed',again,{role_id:id,code:again&&again.code||null});
            st.route.stale={code:again&&again.code||'',reason:'la relecture après une écriture sans réponse a échoué.'};
            setRouteNotice(id,{tone:'bad',code:e.code,reread:true,text:`Résultat inconnu : ${String(e.message||'').replace(/\.?$/,'.')} La relecture a échoué aussi : « ${again&&again.message||again} ».`,
              hint:'Votre liste reste à l’écran. Relisez la politique avant de réenregistrer.'});
            return;
          }
          const written=sameWrite(routeOf(id),action,draft);
          if(written)delete st.routeDrafts[id];
          setRouteNotice(id,{tone:'bad',code:e.code,text:`Résultat inconnu : ${String(e.message||'').replace(/\.?$/,'.')} La politique a été relue.`,
            hint:written?'La relecture montre que la modification a bien été enregistrée.':'La relecture montre la version précédente : la modification n’a pas été enregistrée. Votre liste reste à l’écran.'});
          return;
        }
        if(res&&res.ok){
          delete st.routeDrafts[id];
          logInfo('subagent_settings.routing_'+(action==='restore'?'restored':'saved'),{role_id:id,base_revision:base});
          if(applySnapshot(res.snapshot)){
            const after=routeOf(id);
            setRouteNotice(id,{tone:'ok',text:action==='restore'?`Héritage restauré : le rôle suit de nouveau le profil « ${after?after.inherited_profile:''} ».`
              :'Politique enregistrée pour ce rôle seul. Elle s’applique au prochain sous-agent lancé avec ce rôle.'});
          }else{
            const d=res.snapshot&&res.snapshot.degraded;
            st.route.stale={code:d&&d.code||'subagent_settings_routing_snapshot_missing',reason:d&&d.reason||'la réponse ne porte pas d’instantané lisible.'};
            logError('subagent_settings_routing_degraded',new Error(st.route.stale.reason),{role_id:id,code:st.route.stale.code});
            setRouteNotice(id,{tone:'bad',reread:true,code:st.route.stale.code,text:`${action==='restore'?'Restauré':'Enregistré'}, mais la relecture de la politique a échoué : « ${st.route.stale.reason} »`,
              hint:'L’écran montre peut-être l’ancienne politique. Relisez-la avant toute autre modification.'});
          }
          return;
        }
        const code=res&&res.code||'subagent_routing_refused',status=res&&res.status||0,reason=res&&res.reason||'refus sans raison';
        const err=new Error(reason);err.code=code;err.status=status;
        logError(failCode,err,{role_id:id,code,status});
        /* L'instantané renvoyé avec le refus fait foi ; sans lui, un 409 relit de force. */
        if(!applySnapshot(res&&res.snapshot)&&status===409){try{await refreshRouting()}catch(again){logError('subagent_settings_routing_refresh_failed',again,{role_id:id})}}
        if(code==='role_routing_revision_stale'){
          setRouteNotice(id,{tone:'bad',code,text:'La politique des rôles a changé ailleurs depuis l’ouverture de l’écran. Votre liste est conservée.',
            hint:`Refus du serveur : « ${reason} ». La version enregistrée a été relue : relisez votre liste, puis enregistrez à nouveau pour la remplacer, ou annulez vos changements.`});
        }else{
          setRouteNotice(id,{tone:'bad',code,text:`${action==='restore'?'Restauration refusée':'Enregistrement refusé'}. Refus du serveur : « ${reason} ». Rien n’a été écrit.`,
            hint:action==='restore'?'':'Votre liste reste à l’écran : corrigez-la, puis enregistrez à nouveau.'});
        }
      }finally{
        st.routeSave=null;render();
        const n=host.querySelector&&host.querySelector('[data-sar-route-notice]');if(n&&n.focus){n.tabIndex=-1;n.focus()}
      }
    }
    async function rereadRouting(id){
      if(!routing||st.routeSave)return;
      st.routeSave={id,action:'reread',startedAt:now()};render();
      try{await refreshRouting();setRouteNotice(id,{tone:'ok',text:'Politique des rôles relue.'})}
      catch(e){logError('subagent_settings_routing_refresh_failed',e,{role_id:id,code:e&&e.code||null});
        setRouteNotice(id,{tone:'bad',reread:true,code:e&&e.code||'',text:`Relecture impossible : « ${e&&e.message||e} ».`})}
      finally{st.routeSave=null;render()}
    }
    const saveRoute=id=>writeRoute(id,'put');
    const restoreRoute=id=>writeRoute(id,'restore');
    function ensureStyle(){
      const doc=host.ownerDocument;
      if(!doc||!doc.head||!doc.getElementById||doc.getElementById(STYLE_ID))return;
      const el=doc.createElement('style');el.id=STYLE_ID;el.textContent=STYLE;doc.head.appendChild(el);
    }

    function destroy(){
      st.destroyed=true;if(ticker!=null){clearTimer(ticker);ticker=null}
      if(doc0&&doc0.removeEventListener)doc0.removeEventListener('pointerdown',outside,true);
    }
    function hasUnsaved(){return roles().some(isDirty)||roles().some(r=>routeDirty(r.id))}

    host.setAttribute&&host.setAttribute('data-subagent-settings-host','1');
    render();
    ensureStyle();
    return {view,load,loadTasks,loadCandidates,promote,render,save,reset,reread,select,destroy,hasUnsaved,resolveMarker,
      loadRouting,moveCandidate,removeCandidate,addCandidate,setFallback,discardRoute,saveRoute,restoreRoute,rereadRouting,gotoModels,openMenu,routeReady:()=>routePromise||Promise.resolve(),state:st};
  }


  /* Composition néon/verre, posée par-dessus les règles `.sar-*` de `control_center.html` (base de la fiche et de
     l'éditeur). Slice 06 : fiche, candidats, interrupteur, aperçu. Slice 03 de `refonte-ui-settings` : tableau de bord
     (panneaux `.set-panel`, tuiles `.set-stat`, lignes `.set-row` de la fondation visuelle), lignes des rôles, matrice,
     divulgation « … ». Jetons du thème seulement (`--set-*`, `--shell-*`, `--accent`, `--ok`, `--warn`, `--danger`,
     `--role-accent-*`) : aucune couleur écrite ici (test). */
  const STYLE=`
.sar{--sar-ink:var(--set-ink,var(--text));--sar-ink-2:var(--set-ink-2,var(--muted));--sar-ink-3:var(--set-ink-3,var(--muted));--sar-hair:var(--set-hair-2,var(--line));
  --sar-glass:var(--shell-glass-strong,var(--solid));--sar-r:12px}
.sar *{box-sizing:border-box}
.sar-sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap}
.sar-op-g{width:15px;height:15px;flex:none;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.sar-glyph.sar-op-g{width:26px;height:26px}
.sar-h-g{width:15px;height:15px;color:var(--sar-accent)}
.sar-quiet{color:var(--sar-ink-3);font-size:12px}
/* --- Tableau de bord --------------------------------------------------------------------------------------- */
.sar.sar-board{display:block;height:auto;min-height:0}
.sar-grid{align-items:stretch}
/* Sous 1080 px de page, les paires (synthèse | politique, matrice | règles) passent chacune sur toute la rangée :
   une demi-colonne vide à côté d'un panneau ne sert à rien ici. */
@container set-page (max-width:1080px){.sar-grid>.set-panel{grid-column:1/-1}}
.sar-board .set-panel-desc{max-width:72ch}
.sar-board .set-panel-body{gap:var(--set-sp-3)}
/* Résumé du registre (tableau de bord et état « aucun rôle ») : les règles .sar-side et .sar-summary de la page sont retirées (Slice 07). */
.sar-summary{margin:0;font-size:var(--set-fs-micro);color:var(--sar-ink-3,var(--set-ink-3))}
#sar-p-overview .set-panel-body{flex:1}
.sar-panel{container:sarpanel/inline-size}
.sar-stats{flex:1;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:1fr;gap:var(--set-sp-3)}
.sar-stats .set-stat{align-items:center;padding:16px}
.sar-stats .set-stat-icon{width:30px;height:30px}
.sar-stat-sub{margin-top:6px;font-size:var(--set-fs-micro,11.5px);line-height:1.35;color:var(--sar-ink-3)}
.sar-board .set-rows{display:flex;flex-direction:column;gap:var(--set-sp-2)}
.sar-rule{padding:9px 12px;gap:12px}
.sar-rule .set-row-icon{width:32px;height:32px}
.sar-rule .set-row-label{font-size:13.5px}
.sar-rule[data-sar-rule="gate"] .set-row-hint{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.sar-rule .set-row-control{max-width:55%;flex-wrap:wrap;justify-content:flex-end}
.sar-count{font-size:12.5px;color:var(--sar-ink-2);white-space:nowrap}.sar-count strong{color:var(--sar-ink);font-weight:600;font-variant-numeric:tabular-nums}
.sar-path{font-size:11.5px;overflow-wrap:anywhere;color:var(--sar-ink-2)}
/* Lignes des rôles : même gabarit de colonnes pour l'en-tête et chaque ligne. */
.sar-roles{container:sarroles sarpanel/inline-size}
.sar-rows-head,.sar-row{--sar-cols:minmax(210px,1.6fr) minmax(170px,1.35fr) minmax(88px,.5fr) minmax(130px,1fr) minmax(140px,1fr) minmax(160px,1.3fr) 36px;
  display:grid;grid-template-columns:var(--sar-cols);align-items:center;column-gap:14px}
.sar-rows-head.noroute,.sar-rows.noroute .sar-row{--sar-cols:minmax(220px,1.6fr) minmax(150px,1fr) minmax(200px,1.6fr) 36px}
.sar-rows-head{padding:0 14px 2px;font-size:var(--set-fs-micro);font-weight:600;color:var(--sar-ink-3)}
.sar-rows{gap:8px}
.sar-row{position:relative;padding:10px 12px 10px 10px;border:1px solid color-mix(in srgb,var(--sar-accent) 26%,var(--sar-hair));border-radius:var(--set-r-lg,14px);
  background:linear-gradient(100deg,color-mix(in srgb,var(--sar-accent) 11%,transparent),transparent 46%),var(--set-glass-sunken,var(--sar-glass));
  transition:border-color var(--shell-dur-fast,.15s),box-shadow var(--shell-dur-fast,.15s)}
.sar-row:hover{border-color:color-mix(in srgb,var(--sar-accent) 48%,var(--sar-hair))}
.sar-row.selected{border-color:color-mix(in srgb,var(--sar-accent) 72%,transparent);
  box-shadow:0 0 0 1px color-mix(in srgb,var(--sar-accent) 30%,transparent),0 0 24px -8px var(--sar-accent),inset 0 1px 0 color-mix(in srgb,var(--sar-accent) 22%,transparent)}
.sar-row.menu-open{z-index:var(--set-z-popover,30)}
.sar-row.off{border-style:dashed}
.sar-cell{min-width:0;display:flex;flex-direction:column;gap:4px;font-size:12.5px}
.sar-cell-k{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.sar-board .sar-item{display:flex;align-items:center;gap:12px;width:100%;padding:4px 6px 4px 2px;border:0;border-radius:var(--set-r-sm,10px);background:none;box-shadow:none;color:var(--sar-ink)}
.sar-board .sar-item:hover,.sar-board .sar-item.selected{background:none;border-color:transparent;box-shadow:none}
.sar-board .sar-item .sar-sm .sar-tile{width:40px;height:40px;border-radius:50%;box-shadow:0 0 14px -4px var(--sar-accent)}
.sar-board .sar-item .sar-sm .sar-glyph{width:20px;height:20px}
.sar-board .sar-item-name{font-size:14px;font-weight:600}
.sar-item-desc{font-size:12px;line-height:1.35;color:var(--sar-ink-2);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.sar-board .sar-item-meta{margin-top:2px}
.sar-item-route,.sar-item-fb{display:flex;align-items:center;gap:7px;min-width:0;min-height:34px;padding:6px 10px;border-radius:var(--set-r-md,12px);
  border:1px solid var(--set-hair-3,var(--sar-hair));background:var(--set-field-bg,transparent);font-size:12.5px;color:var(--sar-ink)}
.sar-item-route .sar-op-g,.sar-item-fb .sar-op-g{width:14px;height:14px;color:var(--sar-accent)}
.sar-item-route.muted,.sar-item-fb.muted{border-style:dashed;background:none;color:var(--sar-ink-2)}
.sar-item-route.muted .sar-op-g,.sar-item-fb.muted .sar-op-g{color:var(--sar-ink-2)}
.sar-item-route.bad,.sar-item-fb.bad{border-style:dashed;border-color:color-mix(in srgb,var(--warn) 60%,transparent);color:var(--warn)}
.sar-item-route.bad .sar-op-g,.sar-item-fb.bad .sar-op-g{color:var(--warn)}
.sar-item-route-l{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sar-item-flag{flex:none;font-size:10.5px;letter-spacing:.02em}
.sar-item-more{flex:none;margin-left:auto;font-size:11px;font-variant-numeric:tabular-nums;color:var(--sar-ink-2);border:1px solid var(--sar-hair);border-radius:999px;padding:0 7px}
.sar-src{display:inline-flex;align-items:center;gap:6px;align-self:flex-start;max-width:100%;padding:5px 10px;border-radius:var(--set-r-sm,10px);border:1px solid var(--sar-hair);font-size:12px;white-space:nowrap}
.sar-src .sar-op-g{width:13px;height:13px}
.sar-src.explicit{color:var(--sar-ink);border-color:color-mix(in srgb,var(--sar-accent) 64%,transparent);background:color-mix(in srgb,var(--sar-accent) 14%,transparent)}
.sar-src.explicit .sar-op-g{color:var(--sar-accent)}
.sar-src.inherited{border-style:dashed;color:var(--sar-ink-2)}
.sar-tools{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:4px}
.sar-tool-chip{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:3px 7px;border-radius:var(--set-r-xs,6px);border:1px solid var(--sar-hair);
  background:var(--set-glass-sunken,transparent);font:11px/1.3 var(--set-mono,ui-monospace,monospace);color:var(--sar-ink)}
.sar-tool-chip.more{font-family:inherit;color:var(--sar-accent);border-color:color-mix(in srgb,var(--sar-accent) 45%,transparent)}
.sar-when{font-size:12px;line-height:1.4;color:var(--sar-ink-2);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.sar-c-more{position:relative;align-items:flex-end}
.sar-more{display:grid;place-items:center;width:34px;height:34px;padding:0;border-radius:var(--set-r-md,12px);border:1px solid var(--sar-hair);background:none;color:var(--sar-ink-2);cursor:pointer;
  transition:border-color var(--shell-dur-fast,.15s),color var(--shell-dur-fast,.15s),background-color var(--shell-dur-fast,.15s)}
.sar-more .sar-op-g{width:18px;height:18px}
.sar-more:hover,.sar-more[aria-expanded="true"]{color:var(--sar-ink);border-color:color-mix(in srgb,var(--sar-accent) 60%,transparent);background:color-mix(in srgb,var(--sar-accent) 12%,transparent)}
.sar-menu{position:absolute;right:0;top:calc(100% + 6px);z-index:var(--set-z-popover,30);min-width:230px;margin:0;padding:6px;list-style:none;border-radius:var(--set-r-md,12px);
  border:1px solid color-mix(in srgb,var(--sar-accent) 40%,var(--sar-hair));background:var(--set-glass-float,var(--solid));
  box-shadow:0 18px 42px -16px color-mix(in srgb,var(--bg,black) 90%,transparent),0 0 22px -12px var(--sar-accent)}
.sar-menu-item{display:flex;align-items:center;gap:10px;width:100%;padding:8px 10px;border:0;border-radius:var(--set-r-sm,10px);background:none;color:var(--sar-ink);font:inherit;font-size:13px;text-align:left;cursor:pointer}
.sar-menu-item .sar-op-g{color:var(--sar-accent)}
.sar-menu-item:hover,.sar-menu-item:focus-visible{background:color-mix(in srgb,var(--sar-accent) 14%,transparent)}
.sar-rows-help{margin:2px 0 0}
.sar-board .sar-instances{margin-top:2px}
@container sarpanel (max-width:400px){
  .sar-stats{grid-template-columns:minmax(0,1fr)}
  .sar-rule{flex-wrap:wrap}
  .sar-rule .set-row-control{max-width:none;width:100%;justify-content:flex-start;padding-left:44px}
  .sar-matrix tbody th{max-width:150px}
}
@container sarroles (max-width:1000px){
  .sar-rows-head{display:none}
  /* Carte compacte : identité sur toute la largeur, puis modèle | source | repli, puis outils | conditions. */
  .sar-row{grid-template-columns:minmax(0,1.25fr) minmax(0,.6fr) minmax(0,1fr);row-gap:10px;align-items:start}
  .sar-rows.noroute .sar-row{grid-template-columns:minmax(0,1fr) minmax(0,1.6fr)}
  .sar-c-role{grid-column:1/-1;padding-right:44px}.sar-c-when{grid-column:span 2}
  .sar-rows.noroute .sar-c-when{grid-column:auto}
  .sar-c-more{position:absolute;top:10px;right:10px}
  .sar-cell-k{position:static;width:auto;height:auto;clip-path:none;font-size:11px;font-weight:600;color:var(--sar-ink-3)}
}
@container sarroles (max-width:640px){
  .sar-row{grid-template-columns:repeat(2,minmax(0,1fr))}
  .sar-c-when{grid-column:1/-1}
}
@container sarroles (max-width:520px){
  .sar-row,.sar-rows.noroute .sar-row{grid-template-columns:minmax(0,1fr)}
}
/* Matrice de routage : défile seule en largeur, nom du modèle collé à gauche. */
.sar-matrix th,.sar-matrix td{text-align:center}
.sar-matrix thead th{padding:8px 6px}
.sar-matrix thead th:first-child,.sar-matrix tbody th{position:sticky;left:0;text-align:left}
.sar-matrix thead th:first-child{z-index:calc(var(--set-z-sticky,2) + 1)}
.sar-matrix tbody th{top:auto;z-index:var(--set-z-raised,1);padding:8px 12px;font-size:12.5px;font-weight:500;color:var(--sar-ink);background:var(--set-glass-float,var(--solid));max-width:230px}
.sar-matrix tbody td{padding:7px 6px}
.sar-mx-label{display:inline-flex;align-items:center;gap:6px;min-width:0;max-width:100%}
.sar-mx-label>span:not(.sar-item-flag){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sar-mx-label .sar-op-g{width:13px;height:13px;color:var(--sar-ink-2)}
.sar-matrix tr.unavailable th{color:var(--warn)}.sar-matrix tr.unavailable .sar-mx-label .sar-op-g{color:var(--warn)}
.sar-mx-role{display:inline-grid;place-items:center;padding:3px;border:1px solid transparent;border-radius:var(--set-r-sm,10px);background:none;cursor:pointer;color:inherit}
.sar-mx-role:hover{border-color:color-mix(in srgb,var(--sar-accent) 55%,transparent);background:color-mix(in srgb,var(--sar-accent) 10%,transparent)}
.sar-xs{gap:3px}.sar-xs .sar-tile{width:28px;height:28px;border-radius:50%}.sar-xs .sar-glyph{width:16px;height:16px}.sar-xs .sar-badge{font-size:8.5px}
.sar-mx-pos{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;font-size:11px;font-weight:600;font-variant-numeric:tabular-nums;
  color:var(--sar-accent);border:1.5px solid var(--sar-accent);background:color-mix(in srgb,var(--sar-accent) 12%,transparent)}
.sar-mx-on.first .sar-mx-pos{color:var(--set-ink);background:color-mix(in srgb,var(--sar-accent) 55%,transparent);box-shadow:0 0 12px -2px var(--sar-accent)}
.sar-mx-on.unavailable .sar-mx-pos{border-style:dashed;background:none;box-shadow:none;color:var(--warn);border-color:var(--warn)}
.sar-mx-pos.cli{width:14px;height:14px}
.sar-mx-dot{display:inline-block;width:9px;height:9px;border-radius:50%;border:1px solid var(--sar-hair)}
.sar-mx-legend{display:flex;align-items:center;gap:8px;margin:0}
.sar-mx-pos.sample{--sar-accent:var(--set-cyan,var(--accent));width:18px;height:18px;font-size:10px;flex:none}
/* Fiche du rôle choisi. */
.sar-board .sar-detail-pane{overflow:visible;padding:0;border:0}
.sar-board .sar-detail{max-width:none;padding:var(--set-panel-pad,20px);border-radius:var(--set-r-xl,18px);
  border:1px solid color-mix(in srgb,var(--sar-accent) 36%,var(--set-hair,var(--sar-hair)));
  background:linear-gradient(160deg,color-mix(in srgb,var(--sar-accent) 8%,var(--set-glass,var(--sar-glass))),var(--set-glass-2,var(--sar-glass)) 55%)}
.sar-board .sar-back{display:inline-flex;margin-bottom:12px}
.sar-eyebrow{margin:0 0 2px;font-size:var(--set-fs-micro,11.5px);font-weight:600;color:var(--sar-accent)}
.sar-board .sar-head h3.sar-title{margin:0 0 6px;font-size:22px;font-weight:600;letter-spacing:0;text-transform:none;color:var(--sar-ink)}
.sar-detail-cols{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);grid-template-areas:"a s" "b s";grid-template-rows:auto 1fr;column-gap:28px}
.sar-detail-cols.single{grid-template-columns:minmax(0,1fr);grid-template-areas:"a" "b"}
.sar-col-a{grid-area:a;min-width:0}.sar-col-b{grid-area:b;min-width:0}.sar-col-s{grid-area:s;min-width:0}
@container sarpane (max-width:900px){
  .sar-detail-cols{grid-template-columns:minmax(0,1fr);grid-template-areas:"a" "s" "b";grid-template-rows:auto}
}
.sar-head{padding:16px 18px;margin-bottom:4px;border:1px solid color-mix(in srgb,var(--sar-accent) 32%,var(--sar-hair));border-radius:calc(var(--sar-r) + 2px);
  background:radial-gradient(120% 140% at 0% 0%,color-mix(in srgb,var(--sar-accent) 16%,transparent),transparent 58%),var(--sar-glass);
  box-shadow:0 18px 40px -28px color-mix(in srgb,var(--sar-accent) 60%,transparent)}
.sar-lg .sar-tile{box-shadow:0 0 0 4px color-mix(in srgb,var(--sar-accent) 7%,transparent)}
.sar-block{padding:20px 2px 4px;border-bottom:1px solid color-mix(in srgb,var(--sar-hair) 70%,transparent)}
.sar-block:last-of-type{border-bottom:0}
.sar-block h4{flex-wrap:wrap}
.sar-route{margin:16px 0 4px;padding:16px 18px 14px;border:1px solid color-mix(in srgb,var(--sar-accent) 28%,var(--sar-hair));border-radius:calc(var(--sar-r) + 2px);
  background:linear-gradient(180deg,color-mix(in srgb,var(--sar-accent) 6%,transparent),transparent 40%),var(--sar-glass)}
.sar-route h4{font-size:12px;color:var(--sar-ink);letter-spacing:.12em}
.sar-route h4:focus{outline:none}.sar-route h4:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.sar-route-why{margin:0 0 12px;font-size:12.5px;line-height:1.55;color:var(--sar-ink-2);max-width:72ch}
.sar-prov{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:999px;font-size:11px;letter-spacing:0;text-transform:none;border:1px solid var(--sar-hair);color:var(--sar-ink)}
.sar-prov .sar-op-g{width:13px;height:13px}
.sar-prov.explicit{border-color:color-mix(in srgb,var(--sar-accent) 60%,transparent);background:color-mix(in srgb,var(--sar-accent) 12%,transparent)}
.sar-prov.explicit .sar-op-g{color:var(--sar-accent)}
.sar-prov.inherited{border-style:dashed;color:var(--sar-ink-2)}
.sar-cands{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.sar-cand{display:grid;grid-template-columns:28px minmax(0,1fr) auto;align-items:center;gap:10px;padding:8px 8px 8px 10px;border:1px solid var(--sar-hair);border-radius:10px;
  background:color-mix(in srgb,var(--sar-ink) 3%,transparent)}
.sar-cand:first-child:not(.empty){border-color:color-mix(in srgb,var(--sar-accent) 45%,var(--sar-hair))}
.sar-cand.unavailable{border-style:dashed}
.sar-cand.empty{display:block;padding:12px}
.sar-cand-pos{display:grid;place-items:center;width:24px;height:24px;border-radius:50%;font-size:11px;font-variant-numeric:tabular-nums;border:1px solid var(--sar-hair);color:var(--sar-ink-2)}
.sar-cand:first-child .sar-cand-pos{color:var(--sar-accent);border-color:color-mix(in srgb,var(--sar-accent) 60%,transparent);background:color-mix(in srgb,var(--sar-accent) 10%,transparent)}
.sar-cand-main{display:grid;gap:3px;min-width:0}
.sar-cand-name{font-size:13px;font-weight:600;overflow-wrap:anywhere}
.sar-cand-state{display:flex;flex-wrap:wrap;gap:4px 12px}
.sar-av{display:inline-flex;align-items:flex-start;gap:5px;font-size:11.5px;line-height:1.4;color:var(--sar-ink-2)}
.sar-av .sar-op-g{width:13px;height:13px;margin-top:1px}
.sar-av.ok .sar-op-g{color:var(--ok)}
.sar-av.bad{color:var(--warn)}
.sar-av.muted .sar-op-g{color:var(--sar-ink-2)}
.sar-cand-ops{display:flex;gap:4px}
.sar-op{display:grid;place-items:center;width:32px;height:32px;padding:0;border-radius:8px;border:1px solid var(--sar-hair);background:transparent;color:var(--sar-ink-2);cursor:pointer;transition:color .15s,border-color .15s,background-color .15s}
.sar-op:hover:not(:disabled){color:var(--sar-ink);border-color:color-mix(in srgb,var(--accent) 55%,transparent);background:color-mix(in srgb,var(--accent) 8%,transparent)}
.sar-op[data-sar-cand-op="remove"]:hover:not(:disabled){color:var(--danger);border-color:color-mix(in srgb,var(--danger) 55%,transparent);background:color-mix(in srgb,var(--danger) 8%,transparent)}
.sar .sar-op:disabled{opacity:1;cursor:not-allowed;color:color-mix(in srgb,var(--sar-ink-2) 55%,transparent);border-style:dashed;border-color:color-mix(in srgb,var(--sar-hair) 80%,transparent);background:transparent}
.sar-cand-help{margin:8px 0 0}
.sar-add{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.4fr) auto;align-items:end;gap:10px;margin-top:12px;padding-top:12px;border-top:1px dashed var(--sar-hair)}
.sar-field{display:grid;gap:4px;min-width:0;font-size:11.5px;color:var(--sar-ink-2)}
.sar-field select{width:100%;min-width:0;min-height:34px;padding:6px 8px;border-radius:8px;border:1px solid var(--sar-hair);background:var(--solid);color:var(--sar-ink);font:inherit;font-size:12.5px}
.sar-add-btn{display:inline-flex;align-items:center;gap:6px;min-height:34px;white-space:nowrap}
.sar-add-why{grid-column:1/-1;margin:0}
.sar-fallback{margin-top:14px;padding-top:12px;border-top:1px dashed var(--sar-hair)}
.sar-fallback .hint{margin:6px 0 0 52px}
.sar-switch{display:inline-flex;align-items:center;gap:12px;cursor:pointer;font-size:13px;color:var(--sar-ink)}
.sar-switch input{position:absolute;opacity:0;width:1px;height:1px}
.sar-switch-track{position:relative;width:40px;height:22px;flex:none;border-radius:11px;border:1.5px solid var(--sar-ink-2);transition:background-color .18s,border-color .18s}
.sar-switch-knob{position:absolute;top:3px;left:3px;width:13px;height:13px;border-radius:50%;background:var(--sar-ink-2);transition:transform .18s,background-color .18s}
.sar-switch input:checked+.sar-switch-track{background:color-mix(in srgb,var(--accent) 32%,transparent);border-color:var(--accent)}
.sar-switch input:checked+.sar-switch-track .sar-switch-knob{transform:translateX(18px);background:var(--accent)}
.sar-switch input:focus-visible+.sar-switch-track{outline:2px solid var(--accent);outline-offset:3px}
.sar-switch input:disabled+.sar-switch-track{opacity:.45}
.sar-switch:has(input:disabled){cursor:not-allowed}
.sar-preview{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 14px;align-items:baseline;margin-top:14px;padding:10px 12px;border-radius:10px;
  background:color-mix(in srgb,var(--accent) 6%,transparent);border:1px solid color-mix(in srgb,var(--accent) 22%,transparent);font-size:12.5px}
.sar-preview-k{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--sar-ink-2)}
.sar-preview .hint{grid-column:1/-1;margin:2px 0 0}
.sar-skip{margin:4px 0 0;padding-left:16px;font-size:11.5px;color:var(--sar-ink-2)}
.sar-compat{margin:14px 0 0;padding-top:10px;border-top:1px dashed var(--sar-hair)}
@container sarpane (max-width:620px){
  .sar-add{grid-template-columns:minmax(0,1fr)}
  .sar-cand{grid-template-columns:24px minmax(0,1fr)}
  .sar-cand-ops{grid-column:2;justify-content:flex-start}
  .sar-fallback .hint{margin-left:0}
}
.sar-detail-pane{container:sarpane/inline-size}
@media(prefers-reduced-motion:reduce){.sar *{transition:none!important}}
@media(forced-colors:active){
  .sar-switch-track,.sar-switch-knob{forced-color-adjust:none;border-color:CanvasText}.sar-switch-knob{background:CanvasText}
  .sar-switch input:checked+.sar-switch-track{background:Highlight;border-color:Highlight}
  .sar-row{border-color:CanvasText}.sar-row.selected{outline:3px solid Highlight}
  .sar-mx-pos{forced-color-adjust:none;border-color:CanvasText;color:CanvasText;background:Canvas}
}
`;

  root.JarvisSubagentSettings=Object.freeze({mountId:MOUNT_ID,STYLE_ID,ICONS:Object.freeze(Object.keys(ICONS)),create,
    createRoutingHttpAdapter:o=>Routing.createHttpAdapter(o),createRoutingFixtureAdapter:(s,o)=>Routing.createFixtureAdapter(s,o),
    mount:()=>root.document?root.document.getElementById(MOUNT_ID):null,
    async show(host,options){const view=create(host,options);await view.load();return view}});
})(typeof window!=='undefined'?window:globalThis);
