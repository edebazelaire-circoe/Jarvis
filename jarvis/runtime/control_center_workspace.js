/* Sessions & Boards — gestionnaire profond du Control Center
   (handoff jarvis-board-memory-workspace-inspector, Slice 07).

   Contrat : `docs/boards.md` › *Workspace inspection API*, *Board memory
   mutations*, *Control Center Sessions & Boards manager* ; `docs/artifacts.md`.
   Vue plein écran ouverte par le bouton `WSP` du dock : vue d'ensemble (Session,
   Board, Context et liaison au premier plan), historique des Sessions, tous les
   Boards (archivés compris), relations, mémoire d'un Board (arborescence,
   lecture, écriture, déplacement, suppression), Artefacts et provenance.

   Deux parties, comme `control_center_mcp_inspector.js` :

   - `JarvisWorkspaceCore`, logique pure exécutée telle quelle par les tests
     node : vocabulaire, client HTTP borné, état et actions du gestionnaire
     (`createManager`), rendu HTML de chaque vue ;
   - un bloc navigateur qui branche la vue dans la page.

   QUATRE RÈGLES TIENNENT CE FICHIER.

   1. LE SERVEUR EST LA VÉRITÉ. Rien n'est peint d'avance : la Session, le Board
      actif, le Context et la liaison au premier plan viennent d'une lecture ;
      après chaque écriture, l'arborescence (et le fichier) sont RELUS. La
      bascule de Board n'est pas la nôtre : c'est celle du contrôle Boards du
      haut (`JarvisBoardsControl.switchTo`, `POST /api/boards/switch`), puis on
      relit.
   2. ROUTES BORNÉES. Le client refuse avant le réseau toute adresse hors de
      `/api/workspace/*` (lectures et mutations de mémoire), `/api/boards`,
      `/api/sessions/current` et `/api/artifacts/{id}` (lectures).
   3. CE QUI ATTEND SE VOIT. Chaque lecture et chaque écriture montre son
      libellé et un compteur de secondes, a une échéance (`DEADLINE_MS`) au bout
      de laquelle l'erreur le dit et propose « Réessayer ». Chaque refus codé
      est affiché avec son code et son statut HTTP, jamais avalé.
   4. LE DESTRUCTIF SE DISTINGUE. Supprimer passe par une confirmation DANS le
      panneau (jamais `window.confirm`), en rouge, qui nomme le chemin, le Board
      et, pour un dossier, le nombre d'éléments emportés. Un Board archivé n'a
      aucune commande d'écriture : sa mémoire est en lecture seule. */

const JarvisWorkspaceCore=(function(){
  'use strict';

  /* Échéances client. Le relais attend Core 30 s pour la mémoire et
     l'inspection d'un Board, 10 s pour le reste (`docs/boards.md`) : le client
     attend un peu plus, pour que ce soit la réponse du relais qui parle. */
  const DEADLINE_MS=Object.freeze({read:15000,memory:35000});
  const PRES_PAGE=50;
  const PAGE=20,ACTIVITY_PAGE=50,ARTIFACT_TEXT=2000,READ_BYTES=65536;
  const TREE=Object.freeze({depth:8,max_entries:500});

  const VIEWS=Object.freeze([
    ['overview','Vue d’ensemble'],['sessions','Sessions'],['boards','Boards'],
    ['relations','Relations'],['memory','Mémoire'],['artifacts','Artefacts'],
  ]);

  /* ----------------------------------------------------------- vocabulaire
     Miroir des énumérations du domaine. Une valeur inconnue s'affiche telle
     quelle, jamais maquillée en une valeur connue. */
  const BOARD_KINDS=Object.freeze({empty:'Générique',meeting:'Réunion',presentation:'Présentation'});
  const LIFECYCLES=Object.freeze({
    foreground:{label:'Premier plan',tone:'on',means:'CLI vivant : reçoit les tours, seule autorité de parole.'},
    background_running:{label:'En fond',tone:'warn',means:'CLI vivant gardé pour ses sous-agents : aucun tour, aucune parole.'},
    suspended:{label:'Suspendu',tone:'',means:'CLI arrêté ; agent_session_id permet de le reprendre.'},
  });
  const END_REASONS=Object.freeze({new_session:'nouvelle Session demandée',core_restart:'redémarrage de Core (historique)'});
  const ARTIFACT_KINDS=Object.freeze({
    audio_recording:'Enregistrement audio',transcript_segment:'Segment de transcription',transcript:'Transcription',
    screenshot:'Capture d’écran',screen_recording:'Enregistrement d’écran',description:'Description',derived:'Dérivé',
    presentation_snapshot:'Présentation figée',presentation_video:'Présentation (vidéo)',presentation_still:'Présentation (image)',
    presentation_pdf:'Présentation (PDF)',
  });
  /* Présentations (Remotion Slice 08, `docs/presentation-artifacts.md`) : moteur de la source et format d'un rendu. */
  const ENGINES=Object.freeze({slidecar:'Slidecar (HTML)',remotion:'Remotion'});
  const RENDER_FORMATS=Object.freeze({mp4:'MP4',still:'Image',pdf:'PDF'});
  const LINK_ORIGINS=Object.freeze({active_board:'Board actif à la création',explicit:'Lien explicite'});
  /* Valeurs brutes traduites ; la valeur brute reste dans l'infobulle
     (`title`) pour l'ingénieur. `docs/artifacts.md` › États, Provenance. */
  const ARTIFACT_STATES=Object.freeze({pending:['En cours','warn'],complete:['Complet',''],partial:['Partiel','warn'],failed:['Échoué','bad']});
  const CONTEXT_STATUS=Object.freeze({active:['Actif','on'],dormant:['En sommeil','']});
  const BINDING_STATUS=Object.freeze({open:'ouverte',closed:'close (Session close)'});
  const ENTRY_KINDS=Object.freeze({link:'lien'});
  /* Provenance, dans les deux sens. `origins` : CET artefact <relation>
     l'origine ; `dependents` : l'autre artefact <relation> celui-ci. */
  const RELATIONS_FROM=Object.freeze({transcribed_from:'transcrit de',segment_of:'segment de',frame_from:'image extraite de',
    described_from:'décrit d’après',derived_from:'dérivé de',rendered_from:'rendu de'});
  const RELATIONS_TO=Object.freeze({transcribed_from:'a été transcrit en',segment_of:'contient le segment',frame_from:'a fourni l’image',
    described_from:'a été décrit par',derived_from:'a produit',rendered_from:'a été rendu en'});

  const ERRORS=Object.freeze({
    board_not_found:{title:'Board introuvable',hint:'Il a peut-être été supprimé du stockage : actualisez la liste des Boards.'},
    board_archived:{title:'Board archivé : mémoire en lecture seule',hint:'Les lectures et la recherche restent possibles ; aucune écriture n’est acceptée.'},
    session_not_found:{title:'Session introuvable',hint:'Actualisez l’historique des Sessions.'},
    context_not_found:{title:'Context introuvable',hint:'Choisissez un autre Context de la Session.'},
    artifact_not_found:{title:'Artefact introuvable',hint:'Il a peut-être été supprimé : actualisez la liste.'},
    memory_not_found:{title:'Chemin absent de la mémoire',hint:'Le fichier ou le dossier n’existe plus : l’arborescence est relue.'},
    memory_exists:{title:'Un élément porte déjà ce nom',hint:'Choisissez un autre chemin ; rien n’a été écrasé.'},
    memory_conflict:{title:'Conflit : le fichier a changé ou le chemin ne convient pas',hint:'Relisez le fichier puis recommencez. Un dossier non vide se supprime en cochant « avec son contenu ».'},
    memory_too_large:{title:'Trop volumineux',hint:'256 Kio au plus par lecture ou écriture.'},
    memory_not_text:{title:'Fichier non textuel',hint:'Seul le texte UTF-8 se lit ou s’écrit ici ; le fichier reste listé avec sa taille.'},
    memory_path_invalid:{title:'Chemin refusé',hint:'Chemin relatif POSIX dans memory/, 240 caractères au plus, sans nom réservé Windows.'},
    memory_path_escape:{title:'Chemin hors de la mémoire',hint:'Ni chemin absolu, ni lecteur, ni segment « .. ».'},
    invalid_request:{title:'Requête refusée',hint:'Paramètre, borne ou curseur refusé par l’API.'},
    invalid_board:{title:'Identifiant de Board refusé',hint:'L’identifiant ne suit pas le format attendu.'},
    board_memory_unsafe:{title:'Mémoire non sûre',hint:'Un lien ou une jonction a été vu dans la chaîne de dossiers. Lisez core.workspace.* dans la trace.'},
    board_memory_failed:{title:'Disque en échec',hint:'Le stockage de la mémoire a échoué. Lisez la trace de Core.'},
    workspace_ledger_failed:{title:'Fait, mais non inscrit au journal',hint:'Le changement a eu lieu ; seule la ligne du journal manque. Ne recommencez pas : relisez l’arborescence.'},
    workspace_failed:{title:'Erreur du workspace',hint:'Lisez core.workspace.read_failed dans la trace de Core.'},
    core_unavailable:{title:'Core indisponible',hint:'Core ne sert pas encore le workspace. Réessayez dans un instant.'},
    core_unreachable:{title:'Core ne répond pas',hint:'Vérifiez que Core tourne, puis réessayez.'},
    core_unconfigured:{title:'Core non configuré',hint:'Le Control Center ne connaît pas Core.'},
    core_timeout:{title:'Core n’a pas répondu à temps',hint:'L’issue d’une écriture est inconnue : relisez avant de recommencer.'},
    forbidden_origin:{title:'Origine refusée',hint:'Le workspace n’accepte que la page locale du Control Center.'},
    forbidden_route:{title:'Adresse refusée par la page',hint:'Défaut de la page : rien n’a été envoyé.'},
    timeout:{title:'Pas de réponse',hint:'Aucune réponse dans le délai. Réessayez ; vérifiez que le Control Center tourne.'},
    network:{title:'Control Center injoignable',hint:'La requête n’a pas abouti. Vérifiez que le Control Center tourne, puis réessayez.'},
    bad_response:{title:'Réponse illisible',hint:'La réponse n’est pas le JSON attendu.'},
  });

  /* ------------------------------------------------------------- outillage */
  function esc(value){
    return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function isObject(v){return !!v&&typeof v==='object'&&!Array.isArray(v)}
  function list(v){return Array.isArray(v)?v:[]}
  function plural(n,one,many){return `${n} ${n===1?one:many}`}
  function formatBytes(value){
    const n=Number(value);
    if(!Number.isFinite(n))return '—';
    if(n<1024)return `${n} o`;
    if(n<1024*1024)return `${(n/1024).toFixed(n<10240?1:0)} Kio`;
    return `${(n/1024/1024).toFixed(1)} Mio`;
  }
  function formatSeconds(ms){return `${Math.max(0,Math.floor((Number(ms)||0)/1000))} s`}
  const MONTHS=['janv.','févr.','mars','avr.','mai','juin','juil.','août','sept.','oct.','nov.','déc.'];
  function formatWhen(iso){
    const at=Date.parse(String(iso||''));
    if(!Number.isFinite(at))return '—';
    const d=new Date(at),p=n=>String(n).padStart(2,'0');
    return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  function when(iso){return iso?`<time datetime="${esc(iso)}" title="${esc(iso)}">${esc(formatWhen(iso))}</time>`:'<span class="wsp-none">—</span>'}
  function code(value){return value===null||value===undefined||value===''?'<span class="wsp-none">—</span>':`<code>${esc(value)}</code>`}
  function chip(label,tone,title){
    return `<span class="chip${tone?' '+tone:''}"${title?` title="${esc(title)}"`:''}>${esc(label)}</span>`;
  }
  function kindChip(kind){
    const k=String(kind||'empty');
    return chip(BOARD_KINDS[k]||k,k==='empty'?'':'on',`board_kind : ${k}`);
  }
  function lifecycleChip(value){
    const known=LIFECYCLES[value];
    return known?chip(known.label,known.tone,`${value} — ${known.means}`):chip(String(value||'inconnu'),'warn');
  }
  function artifactKindLabel(kind){return ARTIFACT_KINDS[kind]||String(kind||'?')}
  /* Une valeur d'énumération : libellé français, valeur brute en infobulle ;
     une valeur inconnue s'affiche telle quelle, en avertissement. */
  function enumChip(map,value,field){
    const known=map[value],raw=String(value??'');
    if(!known)return chip(raw||'inconnu','warn',`${field} : ${raw||'(vide)'} (valeur inconnue de la page)`);
    const [label,tone]=Array.isArray(known)?known:[known,''];
    return chip(label,tone,`${field} : ${raw}`);
  }
  function stateChip(state){return enumChip(ARTIFACT_STATES,state,'state')}
  function contextChip(status){return enumChip(CONTEXT_STATUS,status,'status')}
  function relationChip(relation,direction){
    const map=direction==='to'?RELATIONS_TO:RELATIONS_FROM;
    const raw=String(relation||'');
    return chip(map[raw]||raw||'relation inconnue',map[raw]?'':'warn',
      `relation : ${raw} — ${direction==='to'?'l’autre artefact est issu de celui-ci':'cet artefact est issu de l’autre'}`);
  }
  function clockHtml(started){return `<span class="wsp-clock" data-wsp-since="${Number(started)||0}"></span>`}
  function apiError(errorCode,status,message,detail){
    const error=new Error(message||errorCode);
    error.code=errorCode;error.status=status;
    if(detail)error.detail=detail;
    return error;
  }
  function seg(value){return encodeURIComponent(String(value))}
  function query(params){
    const parts=Object.entries(params).filter(([,v])=>v!==null&&v!==undefined&&v!=='')
      .map(([k,v])=>`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
    return parts.length?`?${parts.join('&')}`:'';
  }

  /* ------------------------------------------------------------- routes */
  const PATHS=Object.freeze({
    boards:()=>'/api/boards?include_archived=true',
    currentSession:()=>'/api/sessions/current',
    sessions:cursor=>`/api/workspace/sessions${query({limit:PAGE,cursor})}`,
    session:id=>`/api/workspace/sessions/${seg(id)}`,
    activity:(id,cursor)=>`/api/workspace/sessions/${seg(id)}/activity${query({limit:ACTIVITY_PAGE,cursor})}`,
    board:id=>`/api/workspace/boards/${seg(id)}`,
    relations:id=>`/api/workspace/relations${query({session_id:id})}`,
    tree:id=>`/api/workspace/boards/${seg(id)}/memory/tree${query(TREE)}`,
    read:(id,path,offset)=>`/api/workspace/boards/${seg(id)}/memory/read${query({path,offset:offset||null,max_bytes:READ_BYTES})}`,
    search:(id,q,path)=>`/api/workspace/boards/${seg(id)}/memory/search${query({q,path})}`,
    mutate:(id,op)=>`/api/workspace/boards/${seg(id)}/memory/${op}`,
    artifacts:(scope,filters,cursor)=>`/api/workspace/artifacts${query({...scope,...filters,limit:PAGE,cursor})}`,
    artifact:id=>`/api/artifacts/${seg(id)}${query({text_chars:ARTIFACT_TEXT})}`,
    artifactRelations:id=>`/api/workspace/artifacts/${seg(id)}/relations`,
    boardPresentations:id=>`/api/workspace/boards/${seg(id)}/presentation-sources`,
  });
  const MUTATIONS=new Set(['write','mkdir','move','delete']);

  /* Adresse permise : lecture GET sur les quatre familles, POST sur les seules
     mutations de mémoire. Une adresse absolue de la page (commence par UN
     `/`, jamais `//`, ni `\`), préfixes exacts ; aucun segment vide, `.`
     ou `..` (même encodé). */
  function allowed(method,path){
    if(typeof path!=='string'||/[#\\]/.test(path)||!/^\/[^/]/.test(path))return false;
    const bare=path.split('?')[0];
    const segments=bare.split('/').slice(1);
    if(segments.some(s=>{let plain;try{plain=decodeURIComponent(s)}catch(_){return true}return plain===''||plain==='.'||plain==='..'}))return false;
    if(method==='POST')return segments.length===6&&segments[0]==='api'&&segments[1]==='workspace'&&segments[2]==='boards'
      &&segments[4]==='memory'&&MUTATIONS.has(segments[5])&&!path.includes('?');
    if(method!=='GET')return false;
    if(bare==='/api/boards'||bare==='/api/sessions/current')return true;
    if(bare.startsWith('/api/workspace/'))return true;
    return segments.length===3&&segments[0]==='api'&&segments[1]==='artifacts';
  }
  function isMemoryPath(path){return /\/memory\//.test(path)||/^\/api\/workspace\/boards\/[^/?]+$/.test(path.split('?')[0])}

  function createClient({fetchImpl,setTimer=setTimeout,clearTimer=clearTimeout}={}){
    async function call(method,path,body){
      if(!allowed(method,path))throw apiError('forbidden_route',0,`adresse refusée par la page : ${method} ${path}`);
      const deadlineMs=isMemoryPath(path)?DEADLINE_MS.memory:DEADLINE_MS.read;
      const controller=typeof AbortController==='function'?new AbortController():null;
      let timedOut=false;
      const timer=setTimer(()=>{timedOut=true;if(controller)controller.abort()},deadlineMs);
      const late=`aucune réponse en ${Math.round(deadlineMs/1000)} s`;
      try{
        let response;
        try{
          response=await fetchImpl(path,{method,headers:body?{Accept:'application/json','Content-Type':'application/json'}:{Accept:'application/json'},
            body:body?JSON.stringify(body):undefined,signal:controller?controller.signal:undefined});
        }catch(error){
          if(timedOut)throw apiError('timeout',0,late);
          throw apiError('network',0,(error&&error.message)||'requête interrompue');
        }
        let text='';
        try{text=await response.text()}catch(error){
          if(timedOut)throw apiError('timeout',0,late);
          throw apiError('network',response.status,(error&&error.message)||'réponse interrompue');
        }
        let payload=null;
        try{payload=text?JSON.parse(text):null}catch(_){payload=null}
        if(!response.ok||!isObject(payload)){
          /* Enveloppe `{error:{code,message,…}}` des routes relayées de Core. */
          const envelope=isObject(payload)&&isObject(payload.error)?payload.error:null;
          const errorCode=(envelope&&envelope.code)||(response.ok?'bad_response':`http_${response.status}`);
          const message=(envelope&&envelope.message)||(isObject(payload)&&typeof payload.error==='string'?payload.error:'')
            ||text.slice(0,200)||`HTTP ${response.status}`;
          throw apiError(errorCode,response.status,message,envelope);
        }
        return {status:response.status,body:payload};
      }finally{clearTimer(timer)}
    }
    return {
      get:async path=>(await call('GET',path)).body,
      post:(path,body)=>call('POST',path,body),
    };
  }

  /* Vue d'une erreur : titre humain, message du serveur, code et statut, recours. */
  function errorView(error){
    const errorCode=(error&&error.code)||'network';
    const known=ERRORS[errorCode]||{title:'Erreur du workspace',hint:'Réessayez ; lisez la trace du Control Center et de Core si cela persiste.'};
    return {title:known.title,hint:known.hint,code:errorCode,status:(error&&error.status)||0,
      message:(error&&error.message)?String(error.message):'échec sans message'};
  }
  function errorHtml(error,{retry='',lead='',args=''}={}){
    const view=errorView(error);
    const where=[view.code,view.status?`HTTP ${view.status}`:''].filter(Boolean).join(' · ');
    return `<div class="notice bad wsp-error" role="alert"><strong>${esc(lead)}${esc(view.title)}</strong>`
      +`<div class="wsp-emsg">${esc(view.message)} <code>${esc(where)}</code></div>`
      +`<div class="hint">${esc(view.hint)}</div>`
      +(retry?`<button type="button" class="action small" data-act="retry" data-slot="${esc(retry)}"${args}>Réessayer</button>`:'')
      +`</div>`;
  }
  function loadingHtml(label,started){
    return `<div class="wsp-loading" role="status"><span class="wsp-spin" aria-hidden="true"></span>${esc(label)} ${clockHtml(started)}</div>`;
  }

  /* --------------------------------------------------------------- état */
  /* `readAt` : heure de la dernière lecture réussie de CET emplacement ; le
     bandeau dit l'âge des données montrées, pas celui de la dernière requête. */
  function slot(){return {status:'idle',data:null,error:null,started:0,gen:0,key:null,readAt:0}}
  function pager(){return {items:[],next:null,status:'idle',error:null,started:0,gen:0,key:null,readAt:0}}
  function initialState(){
    return {
      open:false,view:'overview',notice:null,busy:null,switching:null,
      boards:slot(),overview:slot(),
      sessions:pager(),session:{id:null,detail:slot(),activity:pager()},sessionCache:{},
      boardFilter:'all',board:{id:null,detail:slot()},
      relations:{scope:'session',id:null,data:slot(),artifacts:pager()},
      memory:{boardId:null,tree:slot(),file:{path:null,...slot()},search:{q:'',path:'',...slot()},
        form:null,confirm:null,formGen:0,archived:false},
      artifacts:{scope:'board',id:null,session:null,context:null,kind:'',since:'',until:'',list:pager(),detail:{id:null,...slot()},presentations:slot(),presShown:PRES_PAGE},
    };
  }

  /* Le Board d'après la liste lue (titre, nature, archivage). */
  function boardsOf(S){return list(S.boards.data&&S.boards.data.boards)}
  function boardById(S,id){return boardsOf(S).find(b=>b.board_id===id)||null}
  function titleOf(S,id,fallback){const b=boardById(S,id);return (b&&b.title)||fallback||id||'—'}
  function activeBoardId(S){
    const detail=S.overview.data&&S.overview.data.detail;
    const row=detail&&list(detail.boards).find(b=>b.active);
    return row?row.board_id:(S.boards.data&&S.boards.data.active_board_id)||null;
  }
  function memoryArchived(S){
    const b=boardById(S,S.memory.boardId);
    return S.memory.archived||(b?b.status==='archived':false);
  }
  /* Ce qu'un dossier emporte : les entrées de l'arborescence lue sous lui. */
  function childrenOf(S,path){
    const entries=list(S.memory.tree.data&&S.memory.tree.data.entries);
    return entries.filter(e=>String(e.path).startsWith(path+'/')).length;
  }

  /* ----------------------------------------------------------- gestionnaire
     Toutes les actions, sans DOM. `onChange` re-rend ; `log(level, event, data)`
     écrit la ligne de console ; `switchBoard(id, title)` est la bascule du
     contrôle Boards (rend `{ok, message}`). */
  function createManager({client,now=()=>Date.now(),log=()=>{},onChange=()=>{},switchBoard=null,openStudioSource=null}={}){
    const S=initialState();
    const changed=()=>onChange(S);

    /* Une lecture dans un emplacement : attente montrée, génération pour
       ignorer une réponse tardive, erreur gardée et dite. */
    async function load(target,key,fn,{event}={}){
      const gen=++target.gen;
      target.status='loading';target.error=null;target.started=now();target.key=key;
      changed();
      try{
        const data=await fn();
        if(gen!==target.gen)return null;
        target.data=data;target.status='ok';target.readAt=now();
        log('info',`workspace.${event||'read'}`,{key,ms:now()-target.started});
        return data;
      }catch(error){
        if(gen!==target.gen)return null;
        target.status='error';target.error=error;
        log('warn',`workspace.${event||'read'}_failed`,{key,code:error&&error.code,status:error&&error.status,message:error&&error.message});
        return null;
      }finally{if(gen===target.gen)changed()}
    }
    /* Une page de liste : `more` ajoute la page suivante au curseur rendu.
       Une relecture de la MÊME liste (Actualiser) garde les lignes montrées
       jusqu'à la réponse, qui les remplace ; une autre liste repart de zéro. */
    async function page(target,key,url,pick,{more=false,event}={}){
      if(!more&&target.key!==key){target.items=[];target.next=null}
      const gen=++target.gen;
      target.status='loading';target.error=null;target.started=now();target.key=key;
      changed();
      try{
        const body=await client.get(url(more?target.next:null));
        if(gen!==target.gen)return;
        target.items=(more?target.items:[]).concat(list(pick(body)));
        target.next=body.next_cursor||null;target.status='ok';target.readAt=now();
        log('info',`workspace.${event}`,{key,count:target.items.length,more:!!target.next});
      }catch(error){
        if(gen!==target.gen)return;
        target.status='error';target.error=error;
        if(!more){target.items=[];target.next=null}
        log('warn',`workspace.${event}_failed`,{key,code:error&&error.code,status:error&&error.status,message:error&&error.message});
      }finally{if(gen===target.gen)changed()}
    }

    /* Le Board actif se connaît par ces deux lectures : quand l'une arrive,
       la vue montrée choisit ce qu'elle attendait (mémoire et artefacts du
       Board actif, relations de la Session) au lieu de rester sur
       « Choisissez » si on l'a ouverte avant la réponse. */
    const known=data=>{if(data)ensureView();return data};
    const loadBoards=()=>load(S.boards,'boards',()=>client.get(PATHS.boards()),{event:'boards_read'}).then(known);
    async function loadOverview(){
      return known(await load(S.overview,'overview',async()=>{
        const current=await client.get(PATHS.currentSession());
        const id=current&&current.session&&current.session.jarvis_session_id;
        if(!id)throw apiError('bad_response',200,'aucune Session courante dans la réponse');
        const detail=await client.get(PATHS.session(id));
        S.sessionCache[id]=detail;
        const active=list(detail.boards).find(b=>b.active);
        const board=active&&!active.missing?await client.get(PATHS.board(active.board_id)):null;
        return {current,detail,board};
      },{event:'overview_read'}));
    }
    const loadSessions=(more=false)=>page(S.sessions,'sessions',PATHS.sessions,b=>b.sessions,{more,event:'sessions_read'});

    async function openSession(id){
      if(S.session.id===id){S.session.id=null;changed();return}
      S.session.id=id;
      await Promise.all([
        load(S.session.detail,id,async()=>{const d=await client.get(PATHS.session(id));S.sessionCache[id]=d;return d},{event:'session_read'}),
        page(S.session.activity,id,cursor=>PATHS.activity(id,cursor),b=>b.events,{event:'activity_read'}),
      ]);
    }
    async function openBoard(id){
      if(S.board.id===id){S.board.id=null;changed();return}
      S.board.id=id;
      await load(S.board.detail,id,()=>client.get(PATHS.board(id)),{event:'board_read'});
    }
    /* Slice 08 : « Inspecter » depuis le contrôle Boards du haut. Vue Boards,
       filtre « Tous » (un archivé reste visible), ce Board déplié — jamais
       replié s'il l'était déjà, contrairement au clic sur sa ligne. */
    function inspectBoard(id){
      if(!id)return null;
      S.view='boards';S.boardFilter='all';S.notice=null;
      S.board={id:null,detail:slot()};
      log('info','workspace.inspect_board',{board_id:id});
      return openBoard(String(id));
    }
    async function pickRelations(scope,id){
      S.relations.scope=scope==='board'?'board':'session';S.relations.id=id||null;
      S.relations.data=slot();S.relations.artifacts=pager();
      if(!id){changed();return}
      if(S.relations.scope==='session'){
        await load(S.relations.data,`session:${id}`,()=>client.get(PATHS.relations(id)),{event:'relations_read'});
        return;
      }
      await Promise.all([
        load(S.relations.data,`board:${id}`,()=>client.get(PATHS.board(id)),{event:'relations_read'}),
        page(S.relations.artifacts,`board:${id}`,cursor=>PATHS.artifacts({board_id:id},{},cursor),b=>b.artifacts,{event:'relations_artifacts_read'}),
      ]);
    }

    /* ------------------------------------------------------------ mémoire */
    async function memoryBoard(id){
      const m=S.memory;
      if(m.boardId!==id){
        m.boardId=id||null;m.file={path:null,...slot()};m.search={q:'',path:'',...slot()};
        m.form=null;m.confirm=null;m.archived=false;m.tree=slot();
      }
      if(!id){changed();return}
      await load(m.tree,id,()=>client.get(PATHS.tree(id)),{event:'memory_tree_read'});
    }
    async function openFile(path,{more=false}={}){
      const m=S.memory,id=m.boardId;
      if(!id||!path)return;
      const previous=more&&m.file.path===path&&m.file.data?m.file.data:null;
      m.file.path=path;m.confirm=null;
      if(!more&&m.form&&m.form.kind!=='create'&&m.form.kind!=='mkdir')m.form=null;
      await load(m.file,`${id}:${path}`,async()=>{
        const body=await client.get(PATHS.read(id,path,previous?previous.next_offset:0));
        return previous?{...body,text:previous.text+body.text,offset:0}:body;
      },{event:'memory_file_read'});
    }
    /* Relit le fichier ouvert (Actualiser) sans toucher au formulaire : une
       saisie en cours n'est jamais jetée. Un « Remplacer » ouvert garde
       l'empreinte de SA lecture : si le fichier a changé, le serveur refuse. */
    function reloadFile(){
      const m=S.memory,id=m.boardId,path=m.file.path;
      if(!id||!path)return Promise.resolve(null);
      return load(m.file,`${id}:${path}`,()=>client.get(PATHS.read(id,path,0)),{event:'memory_file_read'});
    }
    async function search(q,path){
      const m=S.memory,id=m.boardId;
      m.search.q=String(q||'').trim();m.search.path=String(path||'').trim();
      if(!id||!m.search.q){m.search.status='idle';m.search.data=null;changed();return}
      await load(m.search,`${id}:${m.search.q}`,()=>client.get(PATHS.search(id,m.search.q,m.search.path||null)),{event:'memory_search'});
    }
    function openForm(kind,path){
      const m=S.memory;
      if(memoryArchived(S)||S.busy)return;
      const file=m.file.data;
      m.confirm=null;m.formGen+=1;
      m.form={kind,path:path||'',gen:m.formGen,error:null,
        content:kind==='replace'&&file&&file.path===path?file.text:'',
        sha256:kind==='replace'&&file?file.sha256||null:null};
      changed();
    }
    /* `from` : où le geste a été fait (`tree` ou `file`) ; la confirmation
       s'affiche à côté de cette ligne. */
    function askDelete(path,entryKind,from){
      if(memoryArchived(S)||S.busy||!path)return;
      S.memory.form=null;
      S.memory.confirm={path,kind:entryKind==='directory'?'directory':'file',children:entryKind==='directory'?childrenOf(S,path):0,
        from:from==='file'?'file':'tree'};
      changed();
    }
    function cancel(){
      if(S.memory.confirm){S.memory.confirm=null;changed();return true}
      if(S.memory.form){S.memory.form=null;changed();return true}
      return false;
    }

    /* Une mutation : une à la fois, compteur, échéance du client ; après
       réussite OU échec, l'arborescence est relue (vérité du serveur). */
    async function mutate(op,body,{label,after}){
      const m=S.memory,id=m.boardId;
      if(!id||S.busy)return false;
      S.busy={op,label,started:now()};S.notice=null;
      changed();
      log('info','workspace.memory_mutation_requested',{board_id:id,op});
      let answer=null,failure=null;
      try{
        answer=await client.post(PATHS.mutate(id,op),{...body,origin:'user'});
        log('info','workspace.memory_mutated',{board_id:id,op,status:answer.status,seq:answer.body.activity_seq??null});
      }catch(error){
        failure=error;
        log('error','workspace.memory_mutation_failed',{board_id:id,op,code:error&&error.code,status:error&&error.status,message:error&&error.message});
      }finally{
        S.busy=null;
      }
      if(failure){
        const view=errorView(failure);
        if(view.code==='board_archived'){m.archived=true;m.form=null}
        const unknown=view.code==='timeout'||view.code==='core_timeout';
        /* Un refus d'un formulaire ouvert se dit DANS le formulaire (saisie
           gardée) ; le reste (suppression, issue inconnue, journal) en tête. */
        if(m.form&&!unknown&&view.code!=='workspace_ledger_failed'){m.form.error=failure;S.notice=null}
        else{
          m.form=null;
          S.notice={tone:view.code==='workspace_ledger_failed'?'warn':'bad',error:failure,
            lead:unknown?'Issue inconnue : ':`${label} impossible : `};
        }
        m.confirm=null;
      }else{
        S.notice={tone:'ok',text:after(answer.body,answer.status)};
        m.form=null;m.confirm=null;
        /* Les autres vues ont pu changer (journal, résumé de mémoire) : relues à la visite. */
        S.overview.status='idle';S.board.detail.status='idle';S.session.detail.status='idle';S.session.activity.status='idle';
        S.relations.data.status='idle';
      }
      changed();
      await load(m.tree,id,()=>client.get(PATHS.tree(id)),{event:'memory_tree_read'});
      return !failure&&answer?answer.body:null;
    }
    function journal(body){
      return body&&body.activity_seq!=null?` · journal n° ${body.activity_seq}`:' · rien inscrit au journal (aucun changement)';
    }
    async function save(fields){
      const m=S.memory,form=m.form;
      if(!form||S.busy||memoryArchived(S))return;
      const path=String(fields.path??form.path).trim();
      form.path=path;
      if(form.kind==='create'||form.kind==='replace'||form.kind==='append'){
        const content=String(fields.content??'');
        form.content=content;
        const body={path,content,mode:form.kind};
        if(form.kind==='replace'&&form.sha256)body.expected_sha256=form.sha256;
        const label=form.kind==='create'?'Création':form.kind==='append'?'Ajout':'Remplacement';
        const done=await mutate('write',body,{label,after:(b,status)=>
          `« ${b.path} » ${status===201?'créé':form.kind==='append'?'complété':'remplacé'} · ${formatBytes(b.bytes)} écrits, ${formatBytes(b.size)} au total${journal(b)}`});
        if(done)await openFile(done.path);
        return;
      }
      if(form.kind==='mkdir'){
        await mutate('mkdir',{path},{label:'Création du dossier',after:(b,status)=>
          status===201?`Dossier « ${b.path||path} » créé${journal(b)}`:`Le dossier « ${path} » existait déjà · rien inscrit au journal`});
        return;
      }
      if(form.kind==='move'){
        const to=String(fields.to||'').trim();
        form.to=to;
        const done=await mutate('move',{from:path,to},{label:'Déplacement',after:b=>`« ${b.from} » → « ${b.to} »${journal(b)}`});
        if(done&&m.file.path===path)await openFile(done.to);
      }
    }
    async function confirmDelete(recursive){
      const m=S.memory,c=m.confirm;
      if(!c||S.busy)return;
      const done=await mutate('delete',{path:c.path,recursive:!!recursive},{label:'Suppression',after:b=>
        `« ${c.path} » supprimé définitivement · ${plural(Number(b.removed)||1,'élément retiré','éléments retirés')}${journal(b)}`});
      if(done&&m.file.path&&(m.file.path===c.path||m.file.path.startsWith(c.path+'/')))m.file={path:null,...slot()};
      changed();
    }

    /* ---------------------------------------------------------- artefacts */
    function artifactScope(){
      const a=S.artifacts;
      if(a.scope==='session')return a.id?{session_id:a.id}:null;
      if(a.scope==='context')return a.context?{context_id:a.context}:null;
      return a.id?{board_id:a.id}:null;
    }
    function artifactFilters(){
      const a=S.artifacts,filters={};
      if(a.kind)filters.kind=a.kind;
      if(a.since)filters.since=`${a.since}T00:00:00Z`;
      if(a.until)filters.until=`${a.until}T23:59:59Z`;
      return filters;
    }
    async function artifactsFilter(fields){
      const a=S.artifacts;
      for(const k of ['scope','id','session','context','kind','since','until'])if(fields[k]!==undefined)a[k]=String(fields[k]||'')||(k==='scope'?'board':'');
      if(a.scope==='context'&&a.session&&!S.sessionCache[a.session]){
        const cached=await load(slot(),a.session,()=>client.get(PATHS.session(a.session)),{event:'session_read'});
        if(cached)S.sessionCache[a.session]=cached;
      }
      const scope=artifactScope();
      a.detail={id:null,...slot()};
      if(!scope){a.list=pager();a.presentations=slot();changed();return}
      /* Les présentations se relisent à chaque choix de Board : rien n'est gardé dans la page d'une lecture à l'autre. */
      await Promise.all([artifactsPage(false),presentationsRead()]);
    }
    function presentationsRead(){
      const a=S.artifacts;
      if(a.scope!=='board'||!a.id){a.presentations=slot();a.presShown=PRES_PAGE;changed();return Promise.resolve(null)}
      /* Un autre Board : les groupes du précédent disparaissent AVANT la lecture (jamais ses boutons sous un autre titre). */
      if(a.presentations.key!==a.id){a.presentations=slot();a.presShown=PRES_PAGE}
      return load(a.presentations,a.id,()=>client.get(PATHS.boardPresentations(a.id)),{event:'presentations_read'});
    }
    /* « Ouvrir la source » : le Studio possède la présentation ; la page ne fait que demander son ouverture par identifiant. */
    async function openSource(d){
      const id=d.presentation;
      if(!id)return;
      let refusal=null;
      if(!openStudioSource)refusal='Le Studio de présentation n’est pas disponible dans cette page.';
      else{
        try{
          const outcome=await openStudioSource(id,d.variant||null);
          if(outcome&&outcome.state==='refused')refusal=outcome.reason||outcome.code||'ouverture refusée';
        }catch(error){refusal=(error&&error.message)||'erreur inattendue à l’ouverture du Studio'}
      }
      log(refusal?'warn':'info','workspace.source_open',{presentation_id:id,variant_id:d.variant||null,refused:!!refusal});
      S.notice=refusal?{tone:'bad',text:`La source n’a pas pu être ouverte : ${refusal}`}:null;
      changed();
    }
    function artifactsPage(more){
      const scope=artifactScope();
      if(!scope)return Promise.resolve();
      const filters=artifactFilters();
      return page(S.artifacts.list,JSON.stringify([scope,filters]),cursor=>PATHS.artifacts(scope,filters,cursor),b=>b.artifacts,{more,event:'artifacts_read'});
    }
    /* Le détail d'un artefact se lit par son identifiant, qu'il soit ou non
       dans la liste montrée (lien de provenance, relations d'un Board) : hors
       de la liste, il s'épingle en tête de la vue. `toggle` referme un détail
       déjà ouvert (clic sur sa ligne). */
    async function openArtifact(id,{toggle=true}={}){
      const d=S.artifacts.detail;
      if(!id)return;
      if(toggle&&d.id===id&&d.status!=='error'){S.artifacts.detail={id:null,...slot()};changed();return}
      /* Un autre artefact : jamais les données du précédent sous son nom. */
      if(d.id!==id)S.artifacts.detail={id,...slot()};
      await readArtifact();
    }
    function readArtifact(){
      const d=S.artifacts.detail,id=d.id;
      if(!id)return Promise.resolve(null);
      return load(d,id,async()=>{
        const [meta,relations]=await Promise.all([client.get(PATHS.artifact(id)),client.get(PATHS.artifactRelations(id))]);
        return {meta,relations};
      },{event:'artifact_read'});
    }

    /* -------------------------------------------------- bascule de Board */
    async function switchTo(id){
      const b=boardById(S,id);
      if(!id||S.switching||!switchBoard)return;
      const title=(b&&b.title)||id;
      S.switching={board_id:id,title,started:now()};S.notice=null;
      changed();
      log('info','workspace.switch_requested',{board_id:id});
      let outcome=null;
      try{outcome=await switchBoard(id,title)}
      catch(error){outcome={ok:false,message:(error&&error.message)||'erreur inattendue du contrôle Boards'}}
      finally{S.switching=null}
      /* La vérité : on relit, et c'est la relecture qui dit quel Board est actif. */
      await Promise.all([loadOverview(),loadBoards()]);
      const nowActive=activeBoardId(S);
      if(outcome&&outcome.ok&&nowActive===id){
        S.notice={tone:'ok',text:`« ${title} » est le Board actif (confirmé par le serveur).`};
        log('info','workspace.switch_confirmed',{board_id:id});
      }else{
        const here=titleOf(S,nowActive,nowActive||'inconnu');
        S.notice={tone:'bad',text:`Bascule vers « ${title} » non confirmée : « ${here} » reste actif.${outcome&&outcome.message?` ${outcome.message}`:''}`};
        log('warn','workspace.switch_refused',{board_id:id,active:nowActive,message:outcome&&outcome.message||null});
      }
      changed();
    }

    /* ---------------------------------------------------------- vues
       `ensureView` relit tout emplacement de la vue montrée marqué `idle`
       (jamais lu, ou à relire après une écriture ou « Actualiser »). Un
       emplacement `idle` garde ses données : elles restent à l'écran, sous
       l'indicateur de lecture, jusqu'à la réponse. */
    function ensureView(){
      const v=S.view;
      if(S.boards.status==='idle')loadBoards();
      if(v==='overview'&&S.overview.status==='idle')loadOverview();
      if(v==='sessions'){
        if(S.sessions.status==='idle')loadSessions();
        if(S.session.id&&S.session.detail.status==='idle'){const id=S.session.id;S.session.id=null;openSession(id)}
      }
      if(v==='boards'&&S.board.id&&S.board.detail.status==='idle'){const id=S.board.id;S.board.id=null;openBoard(id)}
      if(v==='relations'){
        if(S.sessions.status==='idle')loadSessions();
        if(!S.relations.id){
          const current=S.overview.data&&S.overview.data.detail&&S.overview.data.detail.session;
          if(current)pickRelations('session',current.jarvis_session_id);
          else if(S.overview.status==='idle')loadOverview();
        }else if(S.relations.data.status==='idle')pickRelations(S.relations.scope,S.relations.id);
      }
      if(v==='memory'){
        const m=S.memory;
        if(!m.boardId){const id=activeBoardId(S);if(id)memoryBoard(id)}
        else{
          if(m.tree.status==='idle')memoryBoard(m.boardId);
          if(m.file.path&&m.file.status==='idle')reloadFile();
          if(m.search.q&&m.search.status==='idle')search(m.search.q,m.search.path);
        }
      }
      if(v==='artifacts'){
        const a=S.artifacts;
        if(S.sessions.status==='idle')loadSessions();
        if(!a.id&&!a.context){
          const id=activeBoardId(S);
          if(id)artifactsFilter({scope:'board',id});
        }else if(a.list.status==='idle'&&artifactScope())artifactsPage(false);
        if(a.scope==='board'&&a.id&&a.presentations.status==='idle')presentationsRead();
        if(a.detail.id&&a.detail.status==='idle')readArtifact();
      }
    }
    function setView(view){
      if(!VIEWS.some(([k])=>k===view))return;
      S.view=view;S.notice=null;
      changed();ensureView();
    }
    function open(){
      S.open=true;
      log('info','workspace.opened',{view:S.view});
      S.overview.status='idle';S.boards.status='idle';
      changed();ensureView();
    }
    /* « Actualiser » : TOUT ce qui a été lu est marqué à relire ; la vue
       montrée est relue tout de suite, chacune de ses parties (liste, détail
       ouvert, arborescence, fichier ouvert, recherche, artefact ouvert), les
       autres vues à leur prochaine visite. Un formulaire ouvert est gardé tel
       quel, avec un avertissement : sa saisie n'est jamais jetée. */
    function refresh(){
      const m=S.memory,a=S.artifacts;
      const slots=[S.boards,S.overview,S.sessions,S.session.detail,S.session.activity,S.board.detail,S.relations.data,
        S.relations.artifacts,m.tree,m.file,m.search,a.list,a.detail,a.presentations];
      for(const target of slots)if(target.status!=='loading')target.status='idle';
      S.sessionCache={};
      S.notice=S.view==='memory'&&m.form?{tone:'warn',text:m.form.kind==='replace'
        ?'Actualisé. Votre saisie en cours est gardée telle quelle. Si le fichier a changé depuis votre lecture, « Remplacer » sera refusé (empreinte sha256) : copiez votre texte, puis relisez.'
        :'Actualisé. Votre saisie en cours est gardée telle quelle : elle n’a pas été relue.'}:null;
      log('info','workspace.refresh',{view:S.view,form:!!m.form});
      changed();
      ensureView();
    }
    function retry(slotName){
      if(slotName==='boards')return loadBoards();
      if(slotName==='overview')return loadOverview();
      if(slotName==='sessions')return loadSessions(S.sessions.items.length>0);
      if(slotName==='session'){const id=S.session.id;S.session.id=null;return openSession(id)}
      if(slotName==='board'){const id=S.board.id;S.board.id=null;return openBoard(id)}
      if(slotName==='relations')return pickRelations(S.relations.scope,S.relations.id);
      if(slotName==='tree')return memoryBoard(S.memory.boardId);
      if(slotName==='file')return reloadFile();
      if(slotName==='search')return search(S.memory.search.q,S.memory.search.path);
      if(slotName==='artifacts')return artifactsPage(S.artifacts.list.items.length>0);
      if(slotName==='artifact')return readArtifact();
      if(slotName==='presentations')return presentationsRead();
      return null;
    }
    function goto(view,args){
      S.view=view;S.notice=null;
      if(view==='memory'&&args.board)return memoryBoard(args.board).then(()=>{changed()});
      if(view==='relations'&&args.id){changed();return pickRelations(args.scope,args.id)}
      if(view==='artifacts'&&(args.id||args.context)){changed();return artifactsFilter({scope:args.scope||'board',id:args.id||'',session:args.session||'',context:args.context||''})}
      changed();ensureView();
      return null;
    }
    /* Ouvre la vue Artefacts sur le détail d'un artefact (depuis les
       relations) : la liste courante est gardée, le détail s'épingle. */
    function showArtifact(id){
      S.view='artifacts';S.notice=null;
      changed();ensureView();
      return openArtifact(id,{toggle:false});
    }

    /* Le seul point d'entrée des événements de la page. */
    function act(name,data){
      const d=data||{};
      switch(name){
        case 'view':return setView(d.view);
        case 'refresh':return refresh();
        case 'retry':return retry(d.slot);
        case 'sessions-more':return loadSessions(true);
        case 'session-toggle':return openSession(d.id);
        case 'activity-more':return S.session.id?page(S.session.activity,S.session.id,c=>PATHS.activity(S.session.id,c),b=>b.events,{more:true,event:'activity_read'}):null;
        case 'board-filter':S.boardFilter=['all','active','archived'].includes(d.filter)?d.filter:'all';changed();return null;
        case 'board-toggle':return openBoard(d.id);
        case 'inspect-board':return inspectBoard(d.id);
        case 'goto':return goto(d.view,d);
        case 'relations-pick':return pickRelations(d.scope,d.id);
        case 'relations-more':return S.relations.scope==='board'&&S.relations.id
          ?page(S.relations.artifacts,`board:${S.relations.id}`,c=>PATHS.artifacts({board_id:S.relations.id},{},c),b=>b.artifacts,{more:true,event:'relations_artifacts_read'}):null;
        case 'memory-board':return memoryBoard(d.board);
        case 'memory-open':return openFile(d.path);
        case 'memory-more':return openFile(S.memory.file.path,{more:true});
        case 'memory-search':return search(d.q,d.path);
        case 'memory-search-clear':return search('','');
        case 'memory-form':return openForm(d.kind,d.path);
        case 'memory-cancel':return cancel();
        case 'memory-save':return save(d);
        case 'memory-delete-ask':return askDelete(d.path,d.kind,d.from);
        case 'memory-delete-confirm':return confirmDelete(d.recursive===true||d.recursive==='true'||d.recursive==='on');
        case 'artifacts-filter':return artifactsFilter(d);
        case 'artifacts-more':return artifactsPage(true);
        case 'artifact-toggle':return openArtifact(d.id);
        case 'artifact-show':return S.view==='artifacts'?openArtifact(d.id,{toggle:false}):showArtifact(d.id);
        case 'source-open':return openSource(d);
        case 'presentations-more':S.artifacts.presShown+=PRES_PAGE;changed();return null;
        case 'artifact-close':S.artifacts.detail={id:null,...slot()};changed();return null;
        case 'switch':return switchTo(d.board);
        case 'notice-close':S.notice=null;changed();return null;
        default:log('warn','workspace.unknown_action',{name});return null;
      }
    }
    function waiting(){
      const slots=[S.boards,S.overview,S.sessions,S.session.detail,S.session.activity,S.board.detail,S.relations.data,
        S.relations.artifacts,S.memory.tree,S.memory.file,S.memory.search,S.artifacts.list,S.artifacts.detail,S.artifacts.presentations];
      return !!(S.busy||S.switching||slots.some(s=>s.status==='loading'));
    }
    return {state:S,act,open,close:()=>{S.open=false;log('info','workspace.closed',{})},cancel,waiting,ensureView};
  }

  /* ================================================================ rendu */

  function tabsHtml(S){
    return VIEWS.map(([key,label])=>{
      const on=S.view===key;
      return `<button type="button" role="tab" id="wsp-tab-${key}" data-act="view" data-view="${key}" aria-selected="${on}" aria-controls="wspPanel" tabindex="${on?0:-1}">${esc(label)}</button>`;
    }).join('');
  }
  /* Les emplacements de la vue montrée : l'état du bandeau parle d'elle, pas
     d'une erreur restée dans un autre onglet. */
  function ownSlots(S){
    const by={overview:[S.overview],sessions:[S.sessions,S.session.detail,S.session.activity],boards:[S.boards,S.board.detail],
      relations:[S.relations.data,S.relations.artifacts],memory:[S.memory.tree,S.memory.file,S.memory.search],
      artifacts:[S.artifacts.list,S.artifacts.detail,S.artifacts.presentations]};
    return by[S.view]||[];
  }
  /* La liste des Boards sert partout (titres, sélecteurs) : son attente et
     son erreur se disent dans chaque vue ; l'âge affiché est celui des
     parties propres à la vue. */
  function viewSlots(S){return [S.boards,...ownSlots(S)]}
  function statusView(S,now){
    const t=now||Date.now();
    if(S.switching)return {tone:'busy',label:'Bascule…',detail:`vers « ${S.switching.title} » · ${formatSeconds(t-S.switching.started)}`};
    if(S.busy)return {tone:'busy',label:`${S.busy.label}…`,detail:formatSeconds(t-S.busy.started)};
    const slots=viewSlots(S);
    const loading=slots.filter(s=>s.status==='loading');
    if(loading.length){
      const since=Math.min(...loading.map(s=>s.started));
      return {tone:'busy',label:'Lecture…',detail:formatSeconds(t-since)};
    }
    const failed=slots.find(s=>s.status==='error');
    if(failed){const v=errorView(failed.error);return {tone:'bad',label:v.title,detail:v.code}}
    /* L'âge des données MONTRÉES : la plus ancienne lecture parmi les parties
       de cette vue. Jamais « à jour » : la page ne sait pas ce qui a changé
       depuis sur le disque ; elle dit quand elle a lu. */
    const read=ownSlots(S).filter(s=>s.readAt).map(s=>s.readAt);
    if(read.length){
      const d=new Date(Math.min(...read)),p=n=>String(n).padStart(2,'0');
      return {tone:'live',label:`Lu à ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`,
        detail:'« Actualiser » relit cette vue'};
    }
    return {tone:'muted',label:'En attente',detail:''};
  }
  function noticeHtml(S){
    const n=S.notice;
    if(!n)return '';
    const close='<button type="button" class="wsp-nx" data-act="notice-close" aria-label="Masquer ce message">×</button>';
    if(n.error)return `<div class="wsp-notice">${errorHtml(n.error,{lead:n.lead||''})}${close}</div>`;
    return `<div class="wsp-notice"><div class="notice ${n.tone==='ok'?'ok':n.tone==='bad'?'bad':''}" role="${n.tone==='bad'?'alert':'status'}">${esc(n.text)}</div>${close}</div>`;
  }
  function slotHtml(target,{label,retry},render){
    if(target.status==='loading'&&!target.data)return loadingHtml(label,target.started);
    if(target.status==='error')return errorHtml(target.error,{retry});
    if(!target.data)return target.status==='loading'?loadingHtml(label,target.started):'';
    return (target.status==='loading'?loadingHtml(label,target.started):'')+render(target.data);
  }
  function problemsHtml(problems){
    const rows=list(problems);
    if(!rows.length)return '';
    return `<div class="notice bad wsp-problems" role="alert"><strong>${plural(rows.length,'problème de données','problèmes de données')}</strong><ul>`
      +rows.map(p=>`<li><code>${esc(p.code)}</code> · ${esc(p.field||'')} ${code(p.board_id)} — ${esc(p.message||'')}</li>`).join('')+'</ul></div>';
  }
  function bindingKv(binding){
    if(!isObject(binding))return '<p class="wsp-none">Aucune liaison : ce Board n’a pas d’agent dans cette Session.</p>';
    return `<dl class="kv wsp-kv"><dt>Cycle de vie</dt><dd>${lifecycleChip(binding.lifecycle)}</dd>`
      +`<dt>Conversation</dt><dd>${code(binding.conversation_id)}</dd>`
      +`<dt>CLI d’agent</dt><dd>${code(binding.agent_cli)}</dd>`
      +`<dt>Session d’agent</dt><dd>${code(binding.agent_session_id)}</dd>`
      +`<dt>Statut</dt><dd>${binding.status?`<span title="${esc(`status : ${binding.status}`)}">${esc(BINDING_STATUS[binding.status]||binding.status)}</span>`:'<span class="wsp-none">—</span>'}</dd>`
      +`<dt>Dernière activité</dt><dd>${when(binding.last_active_at)}</dd></dl>`;
  }
  function btn(name,attrs,label,{tone='',disabled=false,title=''}={}){
    const extra=Object.entries(attrs||{}).map(([k,v])=>` data-${k}="${esc(v)}"`).join('');
    return `<button type="button" class="action small${tone?' '+tone:''}" data-act="${esc(name)}"${extra}${disabled?' disabled':''}${title?` title="${esc(title)}"`:''}>${label}</button>`;
  }
  function switchButtonHtml(S,board){
    if(!board||board.status==='archived'||board.missing)return '';
    if(activeBoardId(S)===board.board_id)return '';
    if(S.switching&&S.switching.board_id===board.board_id)
      return `<button type="button" class="action small" disabled aria-busy="true">Bascule… ${clockHtml(S.switching.started)}</button>`;
    return btn('switch',{board:board.board_id},'Basculer sur ce Board',{disabled:!!S.switching,
      title:'Même bascule que le contrôle Boards du haut : le Board devient actif et son agent passe au premier plan.'});
  }

  /* ---------------------------------------------------- vue d'ensemble */
  function overviewHtml(S){
    return slotHtml(S.overview,{label:'Lecture de l’état courant…',retry:'overview'},data=>{
      const detail=data.detail||{},session=detail.session||{};
      const boards=list(detail.boards);
      const active=boards.find(b=>b.active)||null;
      const foreground=boards.find(b=>b.binding&&b.binding.lifecycle==='foreground')||null;
      const contexts=detail.contexts||{};
      const ctx=list(contexts.items).find(c=>c.context_id===contexts.active_context_id)||null;
      const authority=detail.speech_authority||null;
      const memory=data.board&&data.board.memory;
      const fact=(title,body,cls='')=>`<section class="wsp-fact${cls}"><h3>${title}</h3>${body}</section>`;
      const sessionBody=`<p class="wsp-big">${session.status==='open'?chip('Ouverte','on'):chip('Close','')} ${code(session.jarvis_session_id)}</p>`
        +`<dl class="kv wsp-kv"><dt>Depuis</dt><dd>${when(session.started_at)}</dd><dt>Boards visités</dt><dd>${list(session.visited_board_ids).length}</dd>`
        +`<dt>Contexts</dt><dd>${Number(contexts.total)||0}${contexts.truncated?' (100 plus récents)':''}</dd></dl>`
        +btn('goto',{view:'relations',scope:'session',id:session.jarvis_session_id||''},'Relations de la Session');
      const boardBody=active
        ?`<p class="wsp-big"><strong>${esc(active.title||active.board_id)}</strong> ${kindChip(active.board_kind)}</p>`
          +`<dl class="kv wsp-kv"><dt>Identifiant</dt><dd>${code(active.board_id)}</dd>`
          +(memory?`<dt>Mémoire</dt><dd>${code(memory.locator)}</dd><dt>Contenu</dt><dd>${memory.exists?`${plural(Number(memory.files)||0,'fichier','fichiers')}, ${plural(Number(memory.directories)||0,'dossier','dossiers')}, ${formatBytes(memory.bytes)}${memory.truncated?' (comptage borné)':''}`:'pas encore de mémoire'}</dd>`
            +`<dt>summary.md</dt><dd>${memory.summary&&memory.summary.present?`présent, ${formatBytes(memory.summary.size)}`:'absent'}</dd>`:'')
          +`</dl><div class="wsp-actions">${btn('goto',{view:'memory',board:active.board_id},'Ouvrir la mémoire')}${btn('goto',{view:'artifacts',scope:'board',id:active.board_id},'Artefacts du Board')}</div>`
        :'<p class="wsp-none">Aucun Board actif lu dans cette Session.</p>';
      const contextBody=ctx
        ?`<p class="wsp-big">${esc(ctx.title||'Sans titre')}</p><dl class="kv wsp-kv"><dt>Identifiant</dt><dd>${code(ctx.context_id)}</dd><dt>Dossier</dt><dd>${code(ctx.workspace_ref)}</dd><dt>Actif depuis</dt><dd>${when(ctx.activated_at)}</dd></dl>`
          +'<p class="hint">Le Context appartient à la Session, pas au Board : basculer de Board ne le change pas.</p>'
        :'<p class="wsp-none">Aucun Context actif.</p>';
      const bindingBody=foreground
        ?`<p class="wsp-big">${esc(foreground.title||foreground.board_id)}</p>${bindingKv(foreground.binding)}`
          +(authority?`<p class="hint">Autorité de parole : ${authority.board_id===foreground.board_id&&authority.conversation_id===foreground.binding.conversation_id?'cette liaison':`<strong class="wsp-warn">autre liaison</strong> ${code(authority.conversation_id)}`}.</p>`:'')
        :'<p class="wsp-none">Aucune liaison au premier plan dans cette Session.</p>';
      const rows=boards.map(b=>`<tr${b.active?' class="is-current"':''}><th scope="row">${esc(b.title||b.board_id)}${b.missing?' '+chip('Absent','bad'):''}<span class="wsp-sub">${esc(b.board_id)}</span></th>`
        +`<td>${b.missing?'—':kindChip(b.board_kind)}</td><td>${b.active?chip('Actif','on'):b.visited?chip('Visité',''):chip('Lié','')}</td>`
        +`<td>${b.binding?lifecycleChip(b.binding.lifecycle):'<span class="wsp-none">—</span>'}</td><td>${code(b.binding&&b.binding.conversation_id)}</td></tr>`).join('');
      return problemsHtml(detail.problems)
        +`<div class="wsp-facts">${fact('Session courante',sessionBody)}${fact('Board actif',boardBody,' is-current')}${fact('Context actif',contextBody)}${fact('Liaison au premier plan',bindingBody)}</div>`
        +`<section class="wsp-sect"><h4>Boards de cette Session</h4>${rows?`<div class="wsp-scroll"><table class="catalog-table wsp-table"><thead><tr><th>Board</th><th>Nature</th><th>Rôle</th><th>Agent</th><th>Conversation</th></tr></thead><tbody>${rows}</tbody></table></div>`:'<p class="wsp-none">Aucun Board.</p>'}</section>`
        +'<p class="hint">Tout ici est lu sur le serveur, jamais supposé. « Actualiser » relit tout.</p>';
    });
  }

  /* ------------------------------------------------------------- Sessions */
  function activitySummary(S,e){
    const d=isObject(e.data)?e.data:{};
    if(/^board\.memory\./.test(e.kind)){
      const board=d.board_id?`« ${titleOf(S,d.board_id)} » `:'';
      if(e.kind==='board.memory.moved')return `${board}${d.from} → ${d.to}`;
      if(e.kind==='board.memory.deleted')return `${board}${d.path}${d.recursive?' (avec contenu)':''} · ${d.removed??''} retiré(s)`;
      return `${board}${d.path} · ${d.mode||''}${d.size!=null?` · ${formatBytes(d.size)}`:''}`;
    }
    if(/^board\.artifact\./.test(e.kind))return `« ${titleOf(S,d.board_id)} » · ${list(e.artifact_ids).join(', ')}`;
    const parts=Object.entries(d).slice(0,4).map(([k,v])=>`${k}=${typeof v==='object'?JSON.stringify(v):v}`);
    const ids=list(e.artifact_ids).length?` · ${list(e.artifact_ids).join(', ')}`:'';
    return (parts.join(' · ')+ids).slice(0,200);
  }
  function activityHtml(S){
    const a=S.session.activity;
    if(a.status==='error'&&!a.items.length)return errorHtml(a.error,{retry:'session'});
    const rows=a.items.map(e=>`<tr${/^board\./.test(e.kind)?' class="is-board"':''}><td class="wsp-num">${esc(e.seq)}</td><td>${when(e.occurred_at)}</td><td><code>${esc(e.kind)}</code></td><td class="wsp-wrap">${esc(activitySummary(S,e))}</td></tr>`).join('');
    return `<section class="wsp-sect"><h4>Journal de la Session <span class="wsp-n">${a.items.length}</span></h4>`
      +(rows?`<div class="wsp-scroll"><table class="catalog-table wsp-table wsp-ledger"><thead><tr><th>N°</th><th>Quand</th><th>Événement</th><th>Détail</th></tr></thead><tbody>${rows}</tbody></table></div>`
        :a.status==='loading'?'':'<p class="wsp-none">Journal vide.</p>')
      +pagerFoot(a,'activity-more','Lecture du journal…','session')+'</section>';
  }
  function pagerFoot(p,action,label,retry){
    if(p.status==='loading')return loadingHtml(label,p.started);
    if(p.status==='error'&&p.items.length)return errorHtml(p.error,{retry,lead:'Page suivante : '});
    return p.next?`<div class="wsp-more">${btn(action,{},'Charger la suite')}<span class="hint">${p.items.length} affichés · d’autres restent sur le serveur</span></div>`
      :(p.items.length?`<p class="hint wsp-end">${p.items.length} affichés · fin de la liste.</p>`:'');
  }
  function sessionDetailHtml(S){
    return slotHtml(S.session.detail,{label:'Lecture de la Session…',retry:'session'},d=>{
      const boards=list(d.boards).map(b=>`<li class="wsp-rel-board${b.active?' is-current':''}"><div class="wsp-rel-head"><strong>${esc(b.title||b.board_id)}</strong> ${b.missing?chip('Absent','bad'):kindChip(b.board_kind)} ${b.active?chip('Actif dans la Session','on'):chip('Visité','')}${b.status==='archived'?' '+chip('Archivé','warn'):''}<span class="wsp-sub">${esc(b.board_id)}</span></div>${bindingKv(b.binding)}</li>`).join('');
      const ctx=d.contexts||{};
      const contexts=list(ctx.items).map(c=>`<li>${c.context_id===ctx.active_context_id?chip('Actif','on',`status : ${c.status||'?'}`):contextChip(c.status)} ${esc(c.title||'Sans titre')} ${code(c.context_id)} <span class="wsp-sub">${esc(c.workspace_ref||'')}</span></li>`).join('');
      return problemsHtml(d.problems)
        +`<div class="wsp-two"><section class="wsp-sect"><h4>Boards et liaisons</h4>${boards?`<ul class="wsp-rel">${boards}</ul>`:'<p class="wsp-none">Aucun Board.</p>'}</section>`
        +`<section class="wsp-sect"><h4>Contexts <span class="wsp-n">${Number(ctx.total)||0}</span></h4>${contexts?`<ul class="wsp-plain">${contexts}</ul>`:'<p class="wsp-none">Aucun Context.</p>'}${ctx.truncated?'<p class="hint">Seuls les 100 plus récents sont montrés.</p>':''}</section></div>`
        +activityHtml(S);
    });
  }
  function sessionsHtml(S){
    const p=S.sessions;
    if(p.status==='error'&&!p.items.length)return errorHtml(p.error,{retry:'sessions'});
    if(p.status==='loading'&&!p.items.length)return loadingHtml('Lecture de l’historique…',p.started);
    if(p.status==='ok'&&!p.items.length)return '<p class="wsp-empty">Aucune Session enregistrée.</p>';
    const rows=p.items.map(s=>{
      const openRow=S.session.id===s.jarvis_session_id;
      const board=s.active_board_id?titleOf(S,s.active_board_id):'—';
      return `<li class="wsp-row${openRow?' is-open':''}${s.open?' is-current':''}"><button type="button" class="wsp-toggle" data-act="session-toggle" data-id="${esc(s.jarvis_session_id)}" aria-expanded="${openRow}">`
        +`<span class="wsp-line">${s.open?chip('Ouverte','on'):chip('Close','')}<span class="wsp-label">${when(s.started_at)} → ${s.ended_at?when(s.ended_at):'<em>en cours</em>'}</span></span>`
        +`<span class="wsp-meta">Dernier Board actif : <strong>${esc(board)}</strong> · ${plural(list(s.visited_board_ids).length,'Board visité','Boards visités')}${s.end_reason?` · close : ${esc(END_REASONS[s.end_reason]||s.end_reason)}`:''}</span>`
        +`<span class="wsp-sub">${esc(s.jarvis_session_id)}</span></button>`
        +(openRow?`<div class="wsp-detail">${sessionDetailHtml(S)}</div>`:'')+'</li>';
    }).join('');
    return `<p class="hint wsp-lead">Toutes les Sessions, la plus récente d’abord. Une seule est ouverte ; les autres sont l’historique.</p><ol class="wsp-list">${rows}</ol>`+pagerFoot(p,'sessions-more','Lecture de l’historique…','sessions');
  }

  /* --------------------------------------------------------------- Boards */
  function boardDetailHtml(S,board){
    return slotHtml(S.board.detail,{label:'Lecture du Board…',retry:'board'},d=>{
      const m=d.memory||{},b=d.board||board||{};
      const bindings=list(d.sessions&&d.sessions.items).map(x=>`<tr><td>${code(x.jarvis_session_id)}</td><td>${x.session_status==='open'?chip('Ouverte','on'):chip('Close','')}</td>`
        +`<td>${lifecycleChip(x.lifecycle)}</td><td>${code(x.conversation_id)}</td><td>${code(x.agent_cli)}</td><td>${code(x.agent_session_id)}</td><td>${x.active_in_session?'oui':'non'}</td></tr>`).join('');
      const legacy=list(d.legacy_artifact_refs&&d.legacy_artifact_refs.items);
      return `<dl class="kv wsp-kv"><dt>Mémoire</dt><dd>${code(m.locator)}</dd>`
        +`<dt>Contenu</dt><dd>${m.error?`<span class="wsp-bad">${esc(m.message||m.error)}</span>`:m.exists?`${plural(Number(m.files)||0,'fichier','fichiers')}, ${plural(Number(m.directories)||0,'dossier','dossiers')}, ${formatBytes(m.bytes)}${m.truncated?' (comptage borné)':''}`:'pas encore de mémoire'}</dd>`
        +`<dt>summary.md</dt><dd>${m.summary&&m.summary.present?`présent, ${formatBytes(m.summary.size)}, modifié ${formatWhen(m.summary.modified_at)}`:'absent'}</dd>`
        +`<dt>Artefacts liés</dt><dd>${Number(d.artifacts&&d.artifacts.linked)||0}</dd>`
        +`<dt>Créé</dt><dd>${when(b.created_at)}</dd><dt>Modifié</dt><dd>${when(b.updated_at)}</dd><dt>Mode</dt><dd>${code(b.interaction_mode)}</dd></dl>`
        +`<div class="wsp-actions">${btn('goto',{view:'memory',board:b.board_id},'Ouvrir la mémoire')}${btn('goto',{view:'artifacts',scope:'board',id:b.board_id},'Artefacts liés')}${btn('goto',{view:'relations',scope:'board',id:b.board_id},'Relations')}${switchButtonHtml(S,b)}</div>`
        +`<section class="wsp-sect"><h4>Liaisons dans les Sessions <span class="wsp-n">${list(d.sessions&&d.sessions.items).length}</span></h4>`
        +(bindings?`<div class="wsp-scroll"><table class="catalog-table wsp-table"><thead><tr><th>Session</th><th>État</th><th>Agent</th><th>Conversation</th><th>CLI</th><th>Session d’agent</th><th>Actif dans la Session</th></tr></thead><tbody>${bindings}</tbody></table></div>`:'<p class="wsp-none">Jamais lié à une Session.</p>')
        +(d.sessions&&d.sessions.truncated?'<p class="hint">100 liaisons les plus récentes.</p>':'')+'</section>'
        +`<section class="wsp-sect"><h4>Références héritées (legacy) <span class="wsp-n">${legacy.length}</span></h4>`
        +(legacy.length?`<ul class="wsp-plain">${legacy.map(r=>`<li>${chip('legacy','warn')} ${code(r)}</li>`).join('')}</ul>`:'<p class="wsp-none">Aucune.</p>')
        +'<p class="hint">Board.artifact_refs : chaînes opaques d’avant le registre, pas des liens vers des Artefacts.</p></section>';
    });
  }
  function boardsHtml(S){
    const t=S.boards;
    if(t.status==='error')return errorHtml(t.error,{retry:'boards'});
    if(!t.data)return loadingHtml('Lecture des Boards…',t.started);
    const all=boardsOf(S),active=activeBoardId(S);
    const shown=all.filter(b=>S.boardFilter==='all'||(S.boardFilter==='archived'?b.status==='archived':b.status!=='archived'));
    const count=k=>all.filter(b=>k==='all'||(k==='archived'?b.status==='archived':b.status!=='archived')).length;
    const filter=[['all','Tous'],['active','En service'],['archived','Archivés']].map(([k,l])=>
      `<button type="button" data-act="board-filter" data-filter="${k}" aria-pressed="${S.boardFilter===k}">${l} <span class="wsp-n">${count(k)}</span></button>`).join('');
    const rows=shown.map(b=>{
      const openRow=S.board.id===b.board_id,archived=b.status==='archived',current=b.board_id===active;
      return `<li class="wsp-row${openRow?' is-open':''}${current?' is-current':''}${archived?' is-archived':''}"><button type="button" class="wsp-toggle" data-act="board-toggle" data-id="${esc(b.board_id)}" aria-expanded="${openRow}">`
        +`<span class="wsp-line"><span class="wsp-label">${esc(b.title||b.board_id)}</span>${kindChip(b.board_kind)}${current?chip('Actif maintenant','on'):''}${archived?chip('Archivé','warn','Archivé : lisible, mémoire en lecture seule'):''}</span>`
        +`<span class="wsp-meta">Dernière ouverture : ${b.last_opened_at?esc(formatWhen(b.last_opened_at)):'jamais'} · modifié ${esc(formatWhen(b.updated_at))}</span>`
        +`<span class="wsp-sub">${esc(b.board_id)}</span></button>${openRow?`<div class="wsp-detail">${boardDetailHtml(S,b)}</div>`:''}</li>`;
    }).join('');
    return `<div class="wsp-bar"><div class="wsp-seg" role="group" aria-label="Filtrer les Boards">${filter}</div><span class="hint">Le Board actif vient du serveur ; les archivés restent lisibles.</span></div>`
      +(t.status==='loading'?loadingHtml('Relecture des Boards…',t.started):'')
      +(rows?`<ul class="wsp-list">${rows}</ul>`:'<p class="wsp-empty">Aucun Board dans ce filtre.</p>');
  }

  /* ------------------------------------------------------------ Relations */
  function optionsHtml(items,selected,{value,label,empty}){
    return (empty?`<option value="">${esc(empty)}</option>`:'')+items.map(x=>`<option value="${esc(value(x))}"${value(x)===selected?' selected':''}>${esc(label(x))}</option>`).join('');
  }
  function sessionLabel(s){return `${s.open?'● ':''}${formatWhen(s.started_at)} · ${s.jarvis_session_id}`}
  function boardLabel(b){return `${b.title||b.board_id}${b.status==='archived'?' (archivé)':''}`}
  function relationsHtml(S){
    const r=S.relations;
    const sessions=S.sessions.items,boards=boardsOf(S);
    const picker=`<form class="wsp-bar wsp-form-inline" data-form="relations-pick"><label class="wsp-field"><span>Partir de</span><select name="scope" id="wspRelScope">`
      +`<option value="session"${r.scope==='session'?' selected':''}>une Session</option><option value="board"${r.scope==='board'?' selected':''}>un Board</option></select></label>`
      +`<label class="wsp-field wsp-grow"><span>${r.scope==='board'?'Board':'Session'}</span><select name="id" id="wspRelId">`
      +(r.scope==='board'?optionsHtml(boards,r.id,{value:b=>b.board_id,label:boardLabel,empty:'Choisir un Board'})
        :optionsHtml(sessions,r.id,{value:s=>s.jarvis_session_id,label:sessionLabel,empty:'Choisir une Session'})+(r.id&&!sessions.some(s=>s.jarvis_session_id===r.id)?`<option value="${esc(r.id)}" selected>${esc(r.id)}</option>`:''))
      +`</select></label><button type="submit" class="action small">Afficher</button></form>`;
    if(!r.id)return picker+'<p class="wsp-empty">Choisissez une Session ou un Board.</p>';
    const body=slotHtml(r.data,{label:'Lecture des relations…',retry:'relations'},d=>r.scope==='session'?sessionRelationsHtml(S,d):boardRelationsHtml(S,d));
    return picker+body;
  }
  function sessionRelationsHtml(S,d){
    const s=d.session||{};
    const boards=list(d.boards).map(b=>`<li class="${b.active?'is-current':''}"><span class="wsp-node">Board</span> <strong>${esc(b.title||b.board_id)}</strong> ${b.missing?chip('Absent','bad'):kindChip(b.board_kind)} ${b.active?chip('Actif','on'):chip('Visité','')} ${b.status==='archived'?chip('Archivé','warn'):''} ${code(b.board_id)}`
      +`<ul class="wsp-tree"><li><span class="wsp-node">Liaison</span>${bindingKv(b.binding)}</li>`
      +(b.missing?'':`<li><span class="wsp-node">Mémoire</span> ${btn('goto',{view:'memory',board:b.board_id},'Ouvrir')}</li><li><span class="wsp-node">Artefacts</span> ${btn('goto',{view:'artifacts',scope:'board',id:b.board_id},'Liste')}</li>`)
      +'</ul></li>').join('');
    const ctx=d.contexts||{};
    const contexts=list(ctx.items).map(c=>`<li><span class="wsp-node">Context</span> ${esc(c.title||'Sans titre')} ${contextChip(c.status)} ${code(c.context_id)} `
      +`${btn('goto',{view:'artifacts',scope:'context',session:s.jarvis_session_id||'',context:c.context_id},'Artefacts du Context')}<span class="wsp-sub">${esc(c.workspace_ref||'')}</span></li>`).join('');
    const artifacts=s.jarvis_session_id?`<li><span class="wsp-node">Artefacts</span> tous ceux de la Session ${btn('goto',{view:'artifacts',scope:'session',id:s.jarvis_session_id},'Artefacts de la Session')}</li>`:'';
    return problemsHtml(d.problems)
      +`<div class="wsp-root"><span class="wsp-node">Session</span> ${s.status==='open'?chip('Ouverte','on'):chip('Close','')} ${code(s.jarvis_session_id)}</div>`
      +`<ul class="wsp-tree wsp-top">${boards||'<li class="wsp-none">Aucun Board.</li>'}${contexts}${artifacts}</ul>`
      +(ctx.truncated?'<p class="hint">Seuls les 100 Contexts les plus récents sont montrés.</p>':'');
  }
  function boardRelationsHtml(S,d){
    const b=d.board||{},m=d.memory||{};
    const sessions=list(d.sessions&&d.sessions.items).map(x=>`<li><span class="wsp-node">Session</span> ${code(x.jarvis_session_id)} ${x.session_status==='open'?chip('Ouverte','on'):chip('Close','')}${x.active_in_session?' '+chip('Actif dans la Session',''):''}<ul class="wsp-tree"><li><span class="wsp-node">Liaison</span>${bindingKv(x)}</li></ul></li>`).join('');
    const a=S.relations.artifacts;
    const arts=a.items.map(x=>`<li><span class="wsp-node">Artefact</span> ${chip(artifactKindLabel(x.kind),'',`kind : ${x.kind}`)}${x.state&&x.state!=='complete'?stateChip(x.state):''} `
      +`<button type="button" class="wsp-link" data-act="artifact-show" data-id="${esc(x.artifact_id)}" title="Ouvrir le détail et la provenance">${esc(x.artifact_id)}</button> <span class="wsp-sub">${esc(x.preview||'')}</span></li>`).join('');
    const legacy=list(d.legacy_artifact_refs&&d.legacy_artifact_refs.items);
    return `<div class="wsp-root"><span class="wsp-node">Board</span> <strong>${esc(b.title||b.board_id)}</strong> ${kindChip(b.board_kind)} ${d.active?chip('Actif maintenant','on'):''} ${b.status==='archived'?chip('Archivé','warn'):''} ${code(b.board_id)}</div>`
      +`<ul class="wsp-tree wsp-top"><li><span class="wsp-node">Mémoire</span> ${code(m.locator)} · ${m.exists?`${plural(Number(m.files)||0,'fichier','fichiers')}, ${formatBytes(m.bytes)}`:'vide'} ${btn('goto',{view:'memory',board:b.board_id},'Ouvrir')}</li>`
      +`<li><span class="wsp-node">Artefacts liés</span> ${Number(d.artifacts&&d.artifacts.linked)||0}<ul class="wsp-tree">${arts}</ul>${pagerFoot(a,'relations-more','Lecture des artefacts…','relations')}</li>`
      +`<li><span class="wsp-node">Références legacy</span> ${legacy.length?legacy.map(r=>`${chip('legacy','warn')} ${code(r)}`).join(' '):'aucune'}</li>`
      +(sessions||'<li class="wsp-none">Jamais lié à une Session.</li>')+'</ul>';
  }

  /* --------------------------------------------------------------- Mémoire */
  const ICON_FILE='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H6v18h12V7Z"/><path d="M14 3v4h4"/></svg>';
  const ICON_DIR='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h7l2 2h9v11H3Z"/></svg>';
  function memoryFormHtml(S){
    const f=S.memory.form;
    if(!f)return '';
    const busy=!!S.busy,g=f.gen;
    const titles={create:'Nouveau fichier',replace:'Remplacer le contenu',append:'Ajouter à la fin',mkdir:'Nouveau dossier',move:'Renommer ou déplacer'};
    const pathField=(f.kind==='create'||f.kind==='mkdir')
      ?`<label class="wsp-field"><span>Chemin dans memory/</span><input name="path" id="wspFormPath-${g}" value="${esc(f.path)}" required maxlength="240" autocomplete="off" spellcheck="false" placeholder="${f.kind==='mkdir'?'notes/2026':'notes/decisions.md'}"></label>`
      :`<p class="wsp-formpath">${code(f.path)}<input type="hidden" name="path" value="${esc(f.path)}"></p>`;
    const content=(f.kind==='create'||f.kind==='replace'||f.kind==='append')
      ?`<label class="wsp-field"><span>${f.kind==='append'?'Texte ajouté à la fin':'Contenu (texte UTF-8, 256 Kio au plus)'}</span><textarea name="content" id="wspFormContent-${g}" rows="10" spellcheck="false">${esc(f.content||'')}</textarea></label>`:'';
    const to=f.kind==='move'?`<label class="wsp-field"><span>Nouveau chemin</span><input name="to" id="wspFormTo-${g}" value="${esc(f.to||f.path)}" required maxlength="240" autocomplete="off" spellcheck="false"></label>`:'';
    const guard=f.kind==='replace'?`<p class="hint">${f.sha256?`Protégé : refusé si le fichier a changé depuis sa lecture (sha256 ${esc(String(f.sha256).slice(0,12))}…).`:'Fichier de plus de 1 Mio : pas d’empreinte, le remplacement n’est pas protégé contre une écriture concurrente.'}</p>`:'';
    const submit={create:'Créer',replace:'Remplacer',append:'Ajouter',mkdir:'Créer le dossier',move:'Déplacer'}[f.kind];
    return `<form class="wsp-form" data-form="memory-save" aria-labelledby="wspFormTitle-${g}"><h4 id="wspFormTitle-${g}">${titles[f.kind]}</h4>${pathField}${to}${content}${guard}`
      +(f.error?errorHtml(f.error,{lead:'Refusé : '}):'')
      +`<div class="wsp-actions"><button type="submit" class="action small primary"${busy?' disabled':''}>${busy?`${esc(S.busy.label)}… ${clockHtml(S.busy.started)}`:submit}</button>`
      +`<button type="button" class="action small" data-act="memory-cancel"${busy?' disabled':''}>Annuler</button></div></form>`;
  }
  /* Où se montre la confirmation : à côté de la ligne cliquée (arborescence
     ou fichier ouvert) quand cette ligne est rendue, sinon en tête. */
  function confirmPlace(S){
    const c=S.memory.confirm;
    if(!c)return null;
    const f=S.memory.file,t=S.memory.tree.data;
    if(c.from==='file'&&f.path===c.path&&f.data&&f.status!=='error')return 'file';
    if(c.from==='tree'&&t&&S.memory.tree.status!=='error'&&t.exists&&list(t.entries).some(e=>e.path===c.path))return 'tree';
    return 'top';
  }
  function confirmHtml(S){
    const c=S.memory.confirm;
    if(!c)return '';
    const board=titleOf(S,S.memory.boardId);
    const busy=!!S.busy;
    const folder=c.kind==='directory';
    return `<div class="wsp-confirm" role="alertdialog" aria-modal="false" aria-labelledby="wspConfirmTitle" aria-describedby="wspConfirmBody">`
      +`<h4 id="wspConfirmTitle">Supprimer définitivement ${folder?'le dossier':'le fichier'} ?</h4>`
      +`<p id="wspConfirmBody">${code(c.path)} sera retiré de la mémoire du Board « ${esc(board)} ». Il n’y a pas de corbeille : ce qui est supprimé ne revient pas.</p>`
      +(folder&&c.children?`<label class="wsp-check"><input type="checkbox" id="wspConfirmRecursive" name="recursive"> Supprimer aussi ses ${plural(c.children,'élément','éléments')} (dossier non vide)</label>`
        :folder?'<p class="hint">Dossier vide d’après l’arborescence lue.</p>':'')
      +`<div class="wsp-actions"><button type="button" class="action small" id="wspConfirmCancel" data-act="memory-cancel"${busy?' disabled':''}>Annuler</button>`
      +`<button type="button" class="action small wsp-danger" id="wspConfirmGo" data-act="memory-delete-confirm"${busy?' disabled':''}>${busy?`Suppression… ${clockHtml(S.busy.started)}`:'Supprimer définitivement'}</button></div></div>`;
  }
  function treeHtml(S,readOnly){
    const t=S.memory.tree;
    return slotHtml(t,{label:'Lecture de l’arborescence…',retry:'tree'},d=>{
      const entries=list(d.entries);
      const busy=!!S.busy;
      const head=`<p class="wsp-locator">${code(d.locator)}</p>`
        +(d.truncated?`<div class="notice" role="status">Arborescence incomplète : ${entries.length} entrées montrées, la limite de ${TREE.max_entries} est atteinte. D’autres fichiers existent.</div>`:'')
        +(d.skipped?`<p class="hint">${plural(Number(d.skipped),'entrée ignorée','entrées ignorées')} (temporaires d’écriture ou noms inadressables).</p>`:'');
      if(!d.exists)return head+'<p class="wsp-empty">Ce Board n’a pas encore de mémoire. Le dossier est créé à la première écriture.</p>';
      if(!entries.length)return head+'<p class="wsp-empty">Mémoire vide.</p>';
      const rows=entries.map(e=>{
        const name=String(e.path).split('/').pop();
        const dir=e.kind==='directory',current=S.memory.file.path===e.path;
        const open=dir?`<span class="wsp-ename">${ICON_DIR}${esc(name)}/</span>`
          :e.kind==='file'?`<button type="button" class="wsp-ename" data-act="memory-open" data-path="${esc(e.path)}"${current?' aria-current="true"':''}>${ICON_FILE}${esc(name)}</button>`
          :`<span class="wsp-ename">${esc(name)} ${chip(ENTRY_KINDS[e.kind]||String(e.kind||'?'),'warn',`kind : ${e.kind} — listé, jamais suivi`)}</span>`;
        const tools=readOnly?'':`<span class="wsp-etools">${btn('memory-form',{kind:'move',path:e.path},'Renommer',{disabled:busy,title:`Renommer ou déplacer ${e.path}`})}`
          +`<button type="button" class="action small wsp-danger-quiet" data-act="memory-delete-ask" data-path="${esc(e.path)}" data-kind="${esc(e.kind)}" data-from="tree"${busy?' disabled':''} title="Supprimer ${esc(e.path)}" aria-label="Supprimer ${esc(e.path)}">Supprimer</button></span>`;
        const asked=S.memory.confirm&&confirmPlace(S)==='tree'&&S.memory.confirm.path===e.path;
        return `<li class="wsp-entry${current?' is-open':''}" style="--depth:${Math.max(0,(Number(e.depth)||1)-1)}">${open}<span class="wsp-esize">${dir?'':esc(formatBytes(e.size))}</span>${tools}</li>`
          +(asked?`<li class="wsp-entry-confirm">${confirmHtml(S)}</li>`:'');
      }).join('');
      return head+`<ul class="wsp-entries" aria-label="Arborescence de la mémoire">${rows}</ul>`;
    });
  }
  function fileHtml(S,readOnly){
    const f=S.memory.file;
    if(!f.path)return '<p class="wsp-empty">Choisissez un fichier pour le lire.</p>';
    const owner=S.memory.boardId;
    return `<div class="wsp-filehead"><h4>${code(f.path)}</h4><span class="wsp-sub">dans la mémoire du Board « ${esc(titleOf(S,owner))} » · ${esc(owner)}</span></div>`
      +slotHtml(f,{label:'Lecture du fichier…',retry:'file'},d=>{
      const busy=!!S.busy;
      const whole=d.eof&&(Number(d.offset)||0)===0;
      const tools=readOnly?'':`<div class="wsp-actions">${btn('memory-form',{kind:'replace',path:d.path},'Remplacer',{disabled:busy||!whole,title:whole?'':'Lisez tout le fichier avant de le remplacer'})}`
        +`${btn('memory-form',{kind:'append',path:d.path},'Ajouter à la fin',{disabled:busy})}${btn('memory-form',{kind:'move',path:d.path},'Renommer',{disabled:busy})}`
        +`<button type="button" class="action small wsp-danger-quiet" data-act="memory-delete-ask" data-path="${esc(d.path)}" data-kind="file" data-from="file"${busy?' disabled':''}>Supprimer</button></div>`;
      const asked=S.memory.confirm&&confirmPlace(S)==='file'?confirmHtml(S):'';
      return `<dl class="kv wsp-kv"><dt>Taille</dt><dd>${formatBytes(d.size)}</dd><dt>sha256</dt><dd>${d.sha256?code(d.sha256):'non calculé (fichier de plus de 1 Mio)'}</dd></dl>`
        +tools+asked+`<pre class="wsp-text" tabindex="0">${esc(d.text)}</pre>`
        +(d.eof?'':`<div class="wsp-more">${btn('memory-more',{},'Lire la suite')}<span class="hint">${formatBytes(d.next_offset)} lus sur ${formatBytes(d.size)}</span></div>`);
    });
  }
  function searchHtml(S){
    const s=S.memory.search;
    const form=`<form class="wsp-bar wsp-form-inline" data-form="memory-search" role="search"><label class="wsp-field wsp-grow"><span>Chercher dans la mémoire</span><input type="search" name="q" id="wspSearchQ" value="${esc(s.q)}" maxlength="200" autocomplete="off" spellcheck="false" placeholder="texte littéral"></label>`
      +`<label class="wsp-field"><span>Dans le dossier</span><input name="path" id="wspSearchPath" value="${esc(s.path)}" maxlength="240" autocomplete="off" spellcheck="false" placeholder="(toute la mémoire)"></label>`
      +`<button type="submit" class="action small">Chercher</button>${s.q?btn('memory-search-clear',{},'Effacer'):''}</form>`;
    if(!s.q)return form;
    return form+slotHtml(s,{label:'Recherche…',retry:'search'},d=>{
      const matches=list(d.matches);
      /* `truncated` n'est jamais « rien trouvé » : la recherche s'est arrêtée à une borne. */
      const partial=d.truncated?`<div class="notice" role="status"><strong>Recherche incomplète</strong> — une limite a arrêté la recherche (${plural(Number(d.files_scanned)||0,'fichier lu','fichiers lus')}, ${Number(d.files_skipped)||0} ignoré(s)). D’autres correspondances peuvent exister : précisez le dossier.</div>`:'';
      const rows=matches.map(x=>`<li><button type="button" class="wsp-ename" data-act="memory-open" data-path="${esc(x.path)}">${ICON_FILE}${esc(x.path)}</button><span class="wsp-num">l. ${esc(x.line)}</span><span class="wsp-preview">${esc(x.preview)}</span></li>`).join('');
      if(!matches.length)return partial||`<p class="wsp-empty">Aucune correspondance pour « ${esc(d.query)} » (${plural(Number(d.files_scanned)||0,'fichier lu','fichiers lus')}, ${Number(d.files_skipped)||0} ignoré(s) : binaires ou trop gros).</p>`;
      return partial+`<ul class="wsp-matches">${rows}</ul><p class="hint">${plural(matches.length,'correspondance','correspondances')} · ${plural(Number(d.files_scanned)||0,'fichier lu','fichiers lus')}, ${Number(d.files_skipped)||0} ignoré(s).</p>`;
    });
  }
  function memoryHtml(S){
    const m=S.memory,boards=boardsOf(S);
    const picker=`<form class="wsp-bar wsp-form-inline" data-form="memory-board"><label class="wsp-field wsp-grow"><span>Board</span><select name="board" id="wspMemBoard" data-change="memory-board">`
      +optionsHtml(boards,m.boardId,{value:b=>b.board_id,label:b=>`${boardLabel(b)}${b.board_id===activeBoardId(S)?' · actif':''}`,empty:'Choisir un Board'})+`</select></label></form>`;
    if(!m.boardId)return picker+(S.boards.status==='error'?errorHtml(S.boards.error,{retry:'boards'}):'<p class="wsp-empty">Choisissez un Board pour voir sa mémoire.</p>');
    const readOnly=memoryArchived(S);
    const banner=readOnly?'<div class="notice wsp-readonly" role="note"><strong>Board archivé : mémoire en lecture seule.</strong> Lire et chercher restent possibles ; aucune écriture, aucun déplacement, aucune suppression.</div>':'';
    const busy=!!S.busy;
    const tools=readOnly?'':`<div class="wsp-actions">${btn('memory-form',{kind:'create',path:''},'Nouveau fichier',{disabled:busy,tone:'primary'})}${btn('memory-form',{kind:'mkdir',path:''},'Nouveau dossier',{disabled:busy})}</div>`;
    return picker+banner+(confirmPlace(S)==='top'?confirmHtml(S):'')
      +`<div class="wsp-mem"><section class="wsp-memtree" aria-label="Fichiers"><div class="wsp-memhead"><h4>Fichiers</h4>${tools}</div>${(m.form&&(m.form.kind==='create'||m.form.kind==='mkdir'))?memoryFormHtml(S):''}${treeHtml(S,readOnly)}</section>`
      +`<section class="wsp-memfile" aria-label="Fichier ouvert">${(m.form&&m.form.kind!=='create'&&m.form.kind!=='mkdir')?memoryFormHtml(S):''}${fileHtml(S,readOnly)}</section></div>`
      +`<section class="wsp-sect">${searchHtml(S)}</section>`
      +'<p class="hint">Chaque écriture passe par l’API du workspace (origine « user ») et ajoute une ligne au journal de la Session ouverte (onglet Sessions).</p>';
  }

  /* ------------------------------------------------------------- Artefacts */
  function artifactDetailHtml(S){
    return slotHtml(S.artifacts.detail,{label:'Lecture de l’artefact…',retry:'artifact'},d=>{
      const a=(d.meta&&d.meta.artifact)||{},r=d.relations||{};
      /* Un lien de provenance ouvre l'autre artefact par son identifiant,
         dans la liste ou épinglé hors d'elle. Sens explicite : « cet artefact
         est dérivé de X », « cet artefact a produit Y ». */
      const link=id=>`<button type="button" class="wsp-link" data-act="artifact-show" data-id="${esc(id)}" title="Ouvrir cet artefact">${esc(id)}</button>`;
      const origins=list(r.origins).map(o=>`<li><span class="wsp-node">Origine</span> Cet artefact est ${relationChip(o.relation,'from')} ${link(o.origin_artifact_id)}</li>`).join('');
      const dependents=list(r.dependents).map(o=>`<li><span class="wsp-node">Issu de lui</span> Cet artefact ${relationChip(o.relation,'to')} ${link(o.artifact_id)}</li>`).join('');
      const boards=list(r.boards&&r.boards.items).map(l=>`<li><strong>${esc(titleOf(S,l.board_id))}</strong> ${chip(LINK_ORIGINS[l.origin]||l.origin,l.origin==='explicit'?'on':'')} ${code(l.board_id)} · ${when(l.linked_at)}</li>`).join('');
      return `<dl class="kv wsp-kv"><dt>Nature</dt><dd>${esc(artifactKindLabel(a.kind))} ${code(a.kind)}</dd><dt>État</dt><dd>${a.state?stateChip(a.state):'<span class="wsp-none">—</span>'}</dd>`
        +`<dt>Source</dt><dd>${code(a.source)}</dd><dt>Session</dt><dd>${code(a.jarvis_session_id)}</dd><dt>Context</dt><dd>${code(a.context_id)}</dd>`
        +`<dt>Créé</dt><dd>${when(a.created_at)}</dd><dt>Payload</dt><dd>${a.payload_ref?`${code(a.payload_ref)} ${esc(a.mime_type||'')} ${a.size_bytes!=null?formatBytes(a.size_bytes):''}`:'aucun'}</dd></dl>`
        +(a.text?`<pre class="wsp-text">${esc(a.text)}</pre>${a.text_truncated?`<p class="hint">Texte coupé à ${ARTIFACT_TEXT} caractères sur ${a.text_chars}.</p>`:''}`:'')
        +`<div class="wsp-two"><section class="wsp-sect"><h4>Provenance</h4>${origins||dependents?`<ul class="wsp-plain">${origins}${dependents}</ul>`:'<p class="wsp-none">Aucune relation.</p>'}</section>`
        +`<section class="wsp-sect"><h4>Boards liés</h4>${boards?`<ul class="wsp-plain">${boards}</ul>`:'<p class="wsp-none">Lié à aucun Board (artefact d’avant les liens, ou capturé sans Board actif).</p>'}</section></div>`;
    });
  }
  /* Présentations d'un Board (Remotion Slice 08, `docs/presentation-artifacts.md`) : « source -> copie figée -> rendus »,
     lu du serveur à chaque choix de Board (rien n'est gardé ici). Une source n'est jamais un artefact : elle s'ouvre
     dans le Studio par son identifiant ; ce que le Board porte, ce sont les copies figées et leurs rendus. */
  function engineChip(engine){
    return chip(ENGINES[engine]||String(engine||'moteur inconnu'),ENGINES[engine]?'':'warn',`moteur : ${engine||'(vide)'}`);
  }
  function freshnessChip(snapshot,source){
    if(source&&source.exists===false)return chip('Source supprimée','bad','La copie figée reste lisible ; sa source n’existe plus.');
    if(source&&source.exists===null)return chip('Source illisible','warn',`Core n’a pas pu lire la source (${source.unreadable||'raison inconnue'}).`);
    if(snapshot.stale===true)return chip('Source modifiée depuis','warn','La source a changé après cette copie. La copie reste valide telle quelle.');
    if(snapshot.stale===false)return chip('À jour','on','Révisions de la copie = révisions vivantes de la source.');
    return chip('Fraîcheur inconnue','warn');
  }
  function renderRowHtml(render,boardId){
    const here=list(render.board_ids).includes(boardId);
    return `<li><span class="wsp-node">Rendu</span> ${chip(RENDER_FORMATS[render.format]||artifactKindLabel(render.kind),'',`kind : ${render.kind}`)}`
      +`${render.state&&render.state!=='complete'?stateChip(render.state):''}${here?'':chip('Non lié à ce Board','warn','Ce rendu n’est lié qu’à d’autres Boards.')}`
      +`<button type="button" class="wsp-link" data-act="artifact-show" data-id="${esc(render.artifact_id)}" title="Ouvrir le détail et la provenance">${esc(render.artifact_id)}</button>`
      +`${render.size_bytes!=null?` <span class="wsp-sub">${esc(formatBytes(render.size_bytes))}</span>`:''}`
      +`${render.error_code&&render.state!=='complete'?` <span class="wsp-sub">${esc(render.error_code)}</span>`:''}</li>`;
  }
  /* Un bouton « Ouvrir » désactivé dit POURQUOI, en texte visible relié par aria-describedby (pas seulement en infobulle). */
  function openButtonHtml(attrs,label,source,key){
    if(source&&source.exists)return btn('source-open',attrs,label,{title:'Ouvre dans le Studio (version actuelle de la source)'});
    const why=source&&source.exists===null?'Source illisible : impossible de l’ouvrir.':'Source supprimée : rien à ouvrir.';
    const id=`wspWhy-${String(key).replace(/[^A-Za-z0-9_-]/g,'')}`;
    return btn('source-open',attrs,label,{disabled:true,title:why}).replace('<button ',`<button aria-describedby="${esc(id)}" `)
      +`<span class="wsp-sub" id="${esc(id)}">${esc(why)}</span>`;
  }
  function snapshotRowHtml(snap,source,boardId,presentationId){
    const renders=list(snap.renders).map(r=>renderRowHtml(r,boardId)).join('');
    const failed=snap.state==='failed'||snap.state==='partial';
    return `<li><span class="wsp-node">Copie figée</span> ${stateChip(snap.state)}${engineChip(snap.engine)}${freshnessChip(snap,source)}`
      +`${snap.linked_here?'':chip('Lié par un rendu seulement','warn','Ce Board montre un rendu de cette copie, pas la copie elle-même.')}`
      +`<span class="wsp-sub">variante ${esc(snap.variant_id)} · révision ${esc(snap.source_presentation_revision)}/${esc(snap.source_variant_revision)} · ${esc(formatWhen(snap.created_at))}`
      +`${failed&&snap.error_code?` · ${esc(snap.error_code)}`:''}</span> `
      +`<button type="button" class="wsp-link" data-act="artifact-show" data-id="${esc(snap.artifact_id)}" title="Ouvrir le détail et la provenance">${esc(snap.artifact_id)}</button> `
      +`${openButtonHtml({presentation:presentationId,variant:snap.variant_id},'Ouvrir la variante',source,snap.artifact_id)}`
      +`<ul class="wsp-tree">${renders||'<li class="wsp-none">Aucun rendu.</li>'}</ul></li>`;
  }
  function presentationsHtml(S){
    const a=S.artifacts;
    if(a.scope!=='board'||!a.id)return '';
    return slotHtml(a.presentations,{label:`Lecture des présentations de « ${titleOf(S,a.id)} »…`,retry:'presentations'},d=>{
      const sources=list(d.sources),unreadable=list(d.unreadable);
      const shown=Math.max(PRES_PAGE,Number(a.presShown)||PRES_PAGE);
      const groups=sources.slice(0,shown).map(src=>{
        const live=src.source||{};
        const others=[...new Set(list(src.snapshots).flatMap(x=>[...list(x.board_ids)]))].filter(id=>id!==d.board_id);
        const title=live.exists?esc(live.title||'Sans titre'):live.exists===false?'<span class="wsp-bad">Source supprimée</span>':'<span class="wsp-warn">Source illisible</span>';
        return `<div class="wsp-psrc"><div class="wsp-line"><span class="wsp-node">Source</span><span class="wsp-label">${title}</span>`
          +`${live.exists?engineChip(live.engine)+chip(`révision ${live.revision}`,''):''}`
          +`${openButtonHtml({presentation:src.presentation_id},'Ouvrir la source',live,src.presentation_id)}</div>`
          +`<span class="wsp-sub">${esc(src.source_ref)}</span>`
          +(others.length?`<p class="wsp-sub">Aussi sur : ${others.map(id=>`<button type="button" class="wsp-link" data-act="goto" data-view="artifacts" data-scope="board" data-id="${esc(id)}">${esc(titleOf(S,id))}</button>`).join(' · ')}</p>`:'')
          +`<ul class="wsp-tree">${list(src.snapshots).map(x=>snapshotRowHtml(x,live,d.board_id,src.presentation_id)).join('')||'<li class="wsp-none">Aucune copie figée lisible.</li>'}</ul></div>`;
      }).join('');
      const bad=unreadable.length?`<p class="wsp-warn">${plural(unreadable.length,'artefact de présentation illisible','artefacts de présentation illisibles')} (provenance absente ou incohérente) : `
        +`${unreadable.map(u=>`<button type="button" class="wsp-link" data-act="artifact-show" data-id="${esc(u.artifact_id)}" title="${esc(u.code)}">${esc(u.artifact_id)}</button>`).join(' ')}</p>`:'';
      const more=sources.length>shown?`<p class="wsp-end">${shown} sources affichées sur ${sources.length} ${btn('presentations-more',{},'Afficher la suite')}</p>`:'';
      return `<section class="wsp-sect" aria-labelledby="wspPresTitle"><h4 id="wspPresTitle">Présentations de « ${esc(titleOf(S,d.board_id))} » <span class="wsp-n">${sources.length}</span></h4>`
        +(groups||(unreadable.length?'':'<p class="wsp-none">Aucune présentation figée sur ce Board. Figer une présentation crée la copie que le Board montre ; une source jamais figée n’est sur aucun Board.</p>'))
        +more+bad+(d.truncated?'<p class="hint">Lecture bornée : des copies, rendus ou liens au-delà des plafonds ne sont pas montrés.</p>':'')+'</section>';
    });
  }
  function artifactsHtml(S){
    const a=S.artifacts,boards=boardsOf(S),sessions=S.sessions.items;
    const ctxs=a.session&&S.sessionCache[a.session]?list(S.sessionCache[a.session].contexts&&S.sessionCache[a.session].contexts.items):[];
    const target=a.scope==='board'
      ?`<label class="wsp-field wsp-grow"><span>Board</span><select name="id" id="wspArtId">${optionsHtml(boards,a.id,{value:b=>b.board_id,label:boardLabel,empty:'Choisir un Board'})}</select></label>`
      :`<label class="wsp-field wsp-grow"><span>Session</span><select name="${a.scope==='session'?'id':'session'}" id="wspArtSession">${optionsHtml(sessions,a.scope==='session'?a.id:a.session,{value:s=>s.jarvis_session_id,label:sessionLabel,empty:'Choisir une Session'})}</select></label>`
        +(a.scope==='context'?`<label class="wsp-field wsp-grow"><span>Context</span><select name="context" id="wspArtContext">${optionsHtml(ctxs,a.context,{value:c=>c.context_id,label:c=>`${c.title||'Sans titre'} · ${c.context_id}`,empty:a.session?'Choisir un Context':'Choisissez d’abord une Session'})}</select></label>`:'');
    const kinds=Object.entries(ARTIFACT_KINDS).map(([k,l])=>({k,l}));
    const form=`<form class="wsp-bar wsp-form-inline wsp-filters" data-form="artifacts-filter">`
      +`<label class="wsp-field"><span>Par</span><select name="scope" id="wspArtScope" data-change="artifacts-scope"><option value="board"${a.scope==='board'?' selected':''}>Board</option><option value="session"${a.scope==='session'?' selected':''}>Session</option><option value="context"${a.scope==='context'?' selected':''}>Context</option></select></label>`
      +target
      +`<label class="wsp-field"><span>Nature</span><select name="kind" id="wspArtKind">${optionsHtml(kinds,a.kind,{value:x=>x.k,label:x=>x.l,empty:'Toutes'})}</select></label>`
      +`<label class="wsp-field"><span>Depuis (UTC)</span><input type="date" name="since" id="wspArtSince" value="${esc(a.since)}"></label>`
      +`<label class="wsp-field"><span>Jusqu’au (UTC)</span><input type="date" name="until" id="wspArtUntil" value="${esc(a.until)}"></label>`
      +`<button type="submit" class="action small">Afficher</button></form>`;
    const p=a.list;
    /* Un artefact ouvert par son identifiant (provenance, relations) qui
       n'est pas dans la liste montrée s'épingle au-dessus d'elle. */
    const pinned=a.detail.id&&!p.items.some(x=>x.artifact_id===a.detail.id)
      ?`<section class="wsp-sect" aria-labelledby="wspPinnedTitle"><h4 id="wspPinnedTitle">Artefact hors de la liste courante ${btn('artifact-close',{},'Fermer')}</h4>`
        +`<div class="wsp-list"><div class="wsp-row is-open is-current" id="wspArtifactOpen" tabindex="-1"><div class="wsp-detail"><p class="wsp-big">${code(a.detail.id)}</p>${artifactDetailHtml(S)}</div></div></div></section>`:'';
    const head=form+presentationsHtml(S)+pinned;
    if(p.status==='idle'&&!p.items.length)return head+'<p class="wsp-empty">Choisissez un Board, une Session ou un Context.</p>';
    if(p.status==='error'&&!p.items.length)return head+errorHtml(p.error,{retry:'artifacts'});
    if(p.status==='loading'&&!p.items.length)return head+loadingHtml('Lecture des artefacts…',p.started);
    if(!p.items.length)return head+'<p class="wsp-empty">Aucun artefact pour ce choix et ces filtres.</p>';
    const rows=p.items.map(x=>{
      const openRow=a.detail.id===x.artifact_id;
      return `<li class="wsp-row${openRow?' is-open':''}"${openRow?' id="wspArtifactOpen" tabindex="-1"':''}><button type="button" class="wsp-toggle" data-act="artifact-toggle" data-id="${esc(x.artifact_id)}" aria-expanded="${openRow}">`
        +`<span class="wsp-line">${chip(artifactKindLabel(x.kind),'',`kind : ${x.kind}`)}<span class="wsp-label">${esc(x.preview||x.artifact_id)}</span>${x.state&&x.state!=='complete'?stateChip(x.state):''}</span>`
        +`<span class="wsp-meta">${esc(formatWhen(x.created_at))} · Session ${esc(x.jarvis_session_id||'—')}${x.context_id?` · Context ${esc(x.context_id)}`:''}${x.size_bytes!=null?` · ${esc(formatBytes(x.size_bytes))}`:''}</span>`
        +`<span class="wsp-sub">${esc(x.artifact_id)}</span></button>${openRow?`<div class="wsp-detail">${artifactDetailHtml(S)}</div>`:''}</li>`;
    }).join('');
    return head+`<ul class="wsp-list">${rows}</ul>`+pagerFoot(p,'artifacts-more','Lecture des artefacts…','artifacts');
  }

  function panelHtml(S){
    const view={overview:overviewHtml,sessions:sessionsHtml,boards:boardsHtml,relations:relationsHtml,memory:memoryHtml,artifacts:artifactsHtml}[S.view]||overviewHtml;
    return noticeHtml(S)+view(S);
  }

  /* Touches des onglets : flèches gauche/droite, Début, Fin. */
  function tabKey(key,index,count){
    if(!count)return null;
    if(key==='ArrowRight')return (index+1)%count;
    if(key==='ArrowLeft')return (index-1+count)%count;
    if(key==='Home')return 0;
    if(key==='End')return count-1;
    return null;
  }

  /* « Inspecter » (Slice 08) : que faire du focus à ce rendu, pour la ligne du
     Board demandé. `pending` : `{id, painted}` ou `null` ; `row` : la ligne est
     peinte ; `held` : le focus était sur elle juste avant ce rendu (le rendu
     remplace le nœud, le focus tombe : on le lui rend) ; `loading` : son
     détail se lit encore. La ligne est focalisée UNE fois, à sa première
     peinture ; ensuite seulement rendue si elle l'avait encore — un
     utilisateur parti ailleurs n'est jamais rattrapé. Le suivi s'arrête quand
     le détail est lu ou que l'utilisateur est parti. */
  function boardFocusStep(pending,{row,held,loading}){
    if(!pending)return {focus:false,scroll:false,next:null};
    if(!row)return {focus:false,scroll:false,next:pending.painted&&!loading?null:pending};
    const first=!pending.painted,focus=first||!!held;
    return {focus,scroll:first,next:focus&&loading?{id:pending.id,painted:true}:null};
  }

  return Object.freeze({DEADLINE_MS,PAGE,TREE,VIEWS,BOARD_KINDS,LIFECYCLES,ARTIFACT_KINDS,ERRORS,PATHS,
    esc,formatBytes,formatSeconds,allowed,createClient,errorView,errorHtml,createManager,initialState,
    tabsHtml,statusView,panelHtml,tabKey,activeBoardId,boardFocusStep});
})();
if(typeof module!=='undefined'&&module.exports)module.exports=JarvisWorkspaceCore;

/* --------------------------------------------------------------------------
   Bloc navigateur : vue plein écran, délégation des événements, compteurs.

   LE FOCUS ET LA SAISIE SURVIVENT AUX RE-RENDUS. Avant chaque remplacement,
   l'identifiant de l'élément focalisé est noté puis le focus y revient ; les
   champs d'un formulaire portent la génération du formulaire dans leur id,
   et leur valeur saisie est reportée sur le nouveau nœud de même id. Une
   liste déroulante changée mais pas encore envoyée (« Afficher ») est
   marquée `data-dirty` : une réponse qui arrive entre-temps ne la remet pas
   sur l'ancienne valeur. Quand une confirmation ou un formulaire se ferme,
   le focus revient sur la commande qui l'a ouvert.
   Les compteurs (`data-wsp-since`) avancent par `textContent`, sans re-rendu.
   -------------------------------------------------------------------------- */
(function installJarvisWorkspace(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const W=JarvisWorkspaceCore;
  const root=document.getElementById('workspaceManager');
  if(!root){console.error('[workspace] workspace.install_failed {"code":"workspace_host_missing"}');return}
  const q=s=>root.querySelector(s);
  const el={open:document.getElementById('openWorkspace'),close:q('#wspClose'),refresh:q('#wspRefresh'),
    tabs:q('#wspTabs'),panel:q('#wspPanel'),status:q('#wspStatus'),statusLabel:q('#wspStatusLabel'),
    statusDetail:q('#wspStatusDetail'),announce:q('#wspAnnounce')};
  const TICK_MS=500;
  const V={inerted:[],tick:null,focusBoard:null,opener:null,returnTo:null};
  const log=(level,event,data)=>{
    const line=`[workspace] ${event} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line);
  };
  /* La bascule est celle du contrôle Boards du haut (même requête, mêmes
     échéances, même vérification d'issue inconnue) : `goToBoardFromAlert`
     pilote `JarvisBoardsControl.switchTo`. Le bouton qu'il anime est un nœud
     hors page : l'attente visible est celle de ce gestionnaire, re-rendue. */
  async function switchBoard(boardId,title){
    const B=window.JarvisBoards,control=window.JarvisBoardsControl;
    if(!B||typeof B.goToBoardFromAlert!=='function'||!control)
      return {ok:false,message:'Le contrôle Boards du haut n’est pas installé : basculez depuis le bouton Board.'};
    const button=document.createElement('button'),note=document.createElement('p');
    const ok=await B.goToBoardFromAlert({control,button,note,boardId,title,now:()=>Date.now(),
      setTimeout:(fn,ms)=>setTimeout(fn,ms),clearTimeout:id=>clearTimeout(id),
      setInterval:(fn,ms)=>setInterval(fn,ms),clearInterval:id=>clearInterval(id),
      log:(level,event,data)=>log(level==='warn'?'warn':level==='error'?'error':'info',event,data)});
    return {ok:!!ok,message:ok?'':note.textContent};
  }
  /* « Ouvrir la source » : le Studio possède la présentation (Explorateur de variantes). On referme ce panneau plein
     écran, puis on demande l'ouverture par identifiant ; un refus de l'Explorateur (lecture en cours, formulaire
     ouvert...) revient tel quel au gestionnaire, qui le dit. Rien n'est caché ici. */
  async function openStudioSource(presentationId,variantId){
    const explorer=window.JarvisStudioExplorer;
    if(!explorer||typeof explorer.open!=='function')return {state:'refused',code:'explorer_missing',reason:'l’Explorateur de variantes n’est pas installé dans cette page.'};
    const outcome=await explorer.open({presentation_id:presentationId,variant_id:variantId||undefined,opener:el.open||undefined});
    if(!outcome||outcome.state!=='refused'){V.studioTakesFocus=true;try{closeView()}finally{V.studioTakesFocus=false}}
    return outcome;
  }
  const client=W.createClient({fetchImpl:(path,options)=>window.fetch(path,options)});
  const manager=W.createManager({client,log,switchBoard,openStudioSource,onChange:()=>{if(!root.hidden)render()}});
  const S=manager.state;

  function withFocusAndInput(fn){
    const active=document.activeElement;
    const id=active&&active!==document.body&&root.contains(active)&&active.id?active.id:null;
    const kept={};
    for(const field of el.panel.querySelectorAll('input[id],textarea[id],select[id]')){
      if(field.type==='checkbox')kept[field.id]={checked:field.checked};
      else if(field.tagName==='SELECT'){if(field.dataset.dirty==='1')kept[field.id]={value:field.value,select:true}}
      else kept[field.id]={value:field.value,start:field.selectionStart,end:field.selectionEnd};
    }
    fn();
    for(const [fid,v] of Object.entries(kept)){
      const field=document.getElementById(fid);
      if(!field||!el.panel.contains(field))continue;
      if('checked' in v)field.checked=v.checked;
      else if(v.select){
        /* Seulement si l'option existe encore : jamais une valeur inventée. */
        if([...field.options].some(o=>o.value===v.value)){field.value=v.value;field.dataset.dirty='1'}
      }
      else if(field.value!==v.value)field.value=v.value;
    }
    if(!id)return;
    const back=document.getElementById(id);
    if(back&&document.activeElement!==back&&typeof back.focus==='function')back.focus({preventScroll:true});
  }
  function renderStatus(){
    const v=W.statusView(S,Date.now());
    el.status.dataset.tone=v.tone;
    el.statusLabel.textContent=v.label;
    el.statusDetail.textContent=v.detail?` · ${v.detail}`:'';
  }
  function tickClocks(){
    const now=Date.now();
    for(const node of root.querySelectorAll('[data-wsp-since]')){
      const since=Number(node.getAttribute('data-wsp-since'))||now;
      node.textContent=W.formatSeconds(now-since);
    }
  }
  let lastConfirm=null,lastOverlay=null,lastNotice=null;
  /* La commande qui a ouvert la confirmation ou le formulaire, décrite par
     ses attributs (le nœud est remplacé à chaque rendu). */
  const OPENERS=new Set(['memory-delete-ask','memory-form']);
  function describe(node){
    const d=node.dataset;
    return {act:d.act,path:d.path??null,kind:d.kind??null,from:d.from??null,inFile:!!node.closest('.wsp-memfile')};
  }
  function findOpener(o){
    const sel=`[data-act="${o.act}"]`+(o.kind!=null?`[data-kind="${CSS.escape(o.kind)}"]`:'');
    const all=[...el.panel.querySelectorAll(sel)].filter(n=>!n.disabled&&(o.path==null||n.dataset.path===o.path));
    return all.find(n=>!!n.closest('.wsp-memfile')===o.inFile)||all[0]||null;
  }
  /* Le focus revient sur la commande d'origine ; si elle a disparu (fichier
     supprimé ou renommé), sur « Nouveau fichier », sinon sur le panneau. */
  function returnFocus(){
    const o=V.opener;V.opener=null;
    const back=(o&&findOpener(o))||el.panel.querySelector('[data-act="memory-form"][data-kind="create"]:not([disabled])')||el.panel;
    if(back===el.panel&&!el.panel.hasAttribute('tabindex'))el.panel.setAttribute('tabindex','-1');
    back.focus({preventScroll:false});
  }
  function render(){
    const boardRow=()=>V.focusBoard&&q(`#wspPanel [data-act="board-toggle"][data-id="${CSS.escape(V.focusBoard.id)}"]`);
    const held=!!V.focusBoard&&V.focusBoard.painted&&document.activeElement===boardRow();
    withFocusAndInput(()=>{
      el.tabs.innerHTML=W.tabsHtml(S);
      el.panel.innerHTML=W.panelHtml(S);
    });
    renderStatus();tickClocks();
    /* Un avis nouveau (refus d'ouvrir la source, erreur) est amené à l'écran : il n'est jamais dit hors de vue. */
    if(S.notice&&S.notice!==lastNotice){
      const note=q('.wsp-notice');
      if(note&&typeof note.scrollIntoView==='function')note.scrollIntoView({block:'nearest'});
    }
    lastNotice=S.notice;
    /* « Inspecter » (Slice 08) : le focus rejoint la ligne du Board à sa
       première peinture (la liste arrive après l'ouverture). Chaque rendu
       refait la liste et la ligne n'a pas d'id que `withFocusAndInput` saurait
       rendre : tant que son détail se lit, le focus lui est rendu seulement
       s'il était encore sur elle (`boardFocusStep`, QA S08 point 5). */
    if(V.focusBoard){
      const row=boardRow();
      const step=W.boardFocusStep(V.focusBoard,{row:!!row,held,
        loading:S.board.id===V.focusBoard.id&&S.board.detail.status==='loading'});
      if(step.focus)row.focus({preventScroll:true});
      if(step.scroll)row.scrollIntoView({block:'nearest'});
      V.focusBoard=step.next;
    }
    /* Confirmation ouverte : le focus va sur « Annuler », jamais sur le geste
       destructif, et la boîte est amenée à l'écran près de la ligne cliquée. */
    const confirmKey=S.memory.confirm?S.memory.confirm.path:null;
    if(confirmKey&&confirmKey!==lastConfirm){
      const box=q('.wsp-confirm'),c=q('#wspConfirmCancel');
      if(box&&typeof box.scrollIntoView==='function')box.scrollIntoView({block:'nearest'});
      if(c)c.focus({preventScroll:true});
    }
    lastConfirm=confirmKey;
    const overlay=S.memory.confirm?'confirm':S.memory.form?`form:${S.memory.form.gen}`:null;
    /* Seulement si le focus est perdu (il était dans la boîte fermée) : un
       focus resté sur une commande vivante (liste des Boards) n'est pas volé. */
    const lost=!document.activeElement||document.activeElement===document.body||!root.contains(document.activeElement);
    if(lastOverlay&&!overlay&&!S.busy){
      if(V.opener&&S.view==='memory'&&lost)returnFocus();
      else V.opener=null;
    }
    lastOverlay=overlay;
    if(S.memory.form){
      const g=S.memory.form.gen,first=document.getElementById(`wspFormPath-${g}`)||document.getElementById(`wspFormTo-${g}`)||document.getElementById(`wspFormContent-${g}`);
      if(first&&first.dataset.focused!=='1'){first.dataset.focused='1';first.focus()}
    }
    armTick();
  }
  function armTick(){
    if(manager.waiting()&&!V.tick)V.tick=setInterval(()=>{
      tickClocks();renderStatus();
      if(!manager.waiting()){clearInterval(V.tick);V.tick=null}
    },TICK_MS);
  }

  function openView(){
    if(!root.hidden)return;
    root.hidden=false;V.returnTo=null;
    V.inerted=[...document.body.children].filter(n=>n!==root&&!n.inert&&n.tagName!=='SCRIPT'&&!n.classList.contains('toasts'));
    for(const node of V.inerted)node.inert=true;
    if(el.open){el.open.classList.add('active');el.open.setAttribute('aria-expanded','true')}
    manager.open();
    render();
    requestAnimationFrame(()=>{if(el.panel.contains(document.activeElement))return;const tab=q('[role="tab"][aria-selected="true"]');if(tab)tab.focus({preventScroll:true})});
  }
  function closeView(){
    if(root.hidden)return;
    root.hidden=true;manager.close();V.focusBoard=null;
    clearInterval(V.tick);V.tick=null;
    for(const node of V.inerted)node.inert=false;
    V.inerted=[];
    /* Le focus revient d'où l'utilisateur est parti : la commande qui a
       ouvert la vue (« Inspecter » rend `#boardsButton`), sinon le bouton du dock. */
    const back=V.returnTo&&V.returnTo.isConnected&&!V.returnTo.disabled?V.returnTo:null;V.returnTo=null;
    if(el.open){el.open.classList.remove('active');el.open.setAttribute('aria-expanded','false')}
    const target=back||el.open;
    if(!V.studioTakesFocus&&target)target.focus({preventScroll:true});
  }
  function fieldsOf(form){
    const out={};
    for(const field of form.querySelectorAll('input[name],textarea[name],select[name]'))
      out[field.name]=field.type==='checkbox'?field.checked:field.value;
    return out;
  }

  if(el.open)el.open.addEventListener('click',()=>{root.hidden?openView():closeView()});
  el.close.addEventListener('click',closeView);
  el.refresh.addEventListener('click',()=>manager.act('refresh'));
  root.addEventListener('click',event=>{
    const target=event.target.closest&&event.target.closest('[data-act]');
    if(!target||!root.contains(target)||target.disabled)return;
    const data={...target.dataset};
    if(data.act==='memory-delete-confirm'){const box=q('#wspConfirmRecursive');data.recursive=!!(box&&box.checked)}
    if(OPENERS.has(data.act))V.opener=describe(target);
    const done=manager.act(data.act,data);
    if(data.act==='view'){const tab=document.getElementById(`wsp-tab-${data.view}`);if(tab)tab.focus()}
    /* Artefact ouvert depuis un lien : amené à l'écran, le focus y va. */
    if(data.act==='artifact-show')Promise.resolve(done).then(()=>{
      const node=q('#wspArtifactOpen');
      if(node){node.scrollIntoView({block:'start'});node.focus({preventScroll:true})}
    }).catch(error=>log('error','workspace.artifact_show_failed',{message:error&&error.message}));
  });
  root.addEventListener('submit',event=>{
    const form=event.target.closest('form[data-form]');
    if(!form)return;
    event.preventDefault();
    /* Envoyé : les listes changées sont maintenant l'état du gestionnaire. */
    for(const field of form.querySelectorAll('select[data-dirty]'))delete field.dataset.dirty;
    manager.act(form.dataset.form,fieldsOf(form));
  });
  root.addEventListener('change',event=>{
    const t=event.target;
    if(t.dataset&&t.dataset.change==='memory-board'){manager.act('memory-board',{board:t.value});return}
    if(t.dataset&&t.dataset.change==='artifacts-scope'){
      S.artifacts.scope=t.value;S.artifacts.id=null;S.artifacts.context=null;S.artifacts.session=null;render();return;
    }
    if(t.id==='wspRelScope'){S.relations.scope=t.value==='board'?'board':'session';S.relations.id=null;render();return}
    if(t.id==='wspArtSession'&&S.artifacts.scope==='context'){manager.act('artifacts-filter',{session:t.value,context:''});return}
    /* Les autres listes attendent « Afficher » : choix gardé d'ici là. */
    if(t.tagName==='SELECT')t.dataset.dirty='1';
  });
  el.tabs.addEventListener('keydown',event=>{
    const tabs=[...el.tabs.querySelectorAll('[role="tab"]')];
    const index=tabs.findIndex(t=>t.getAttribute('aria-selected')==='true');
    const next=W.tabKey(event.key,index,tabs.length);
    if(next===null)return;
    event.preventDefault();
    manager.act('view',{view:tabs[next].dataset.view});
    const tab=document.getElementById(tabs[next].id);if(tab)tab.focus();
  });
  /* Échap : d'abord la confirmation ou le formulaire, ensuite la vue. */
  document.addEventListener('keydown',event=>{
    if(root.hidden||event.key!=='Escape')return;
    event.preventDefault();event.stopPropagation();
    if(manager.cancel())return;
    closeView();
  },true);
  root.addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const focusable=[...root.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea,[tabindex="0"]')]
      .filter(node=>node.offsetParent!==null);
    if(!focusable.length)return;
    const first=focusable[0],last=focusable[focusable.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
  });

  /* Point d'entrée du contrôle Boards (Slice 08) : ouvrir la vue sur un
     Board. Rend la promesse de sa lecture ; un refus du serveur s'affiche
     dans la vue, comme pour un clic. `options.opener` : la commande où le
     focus revient à la fermeture (le bouton Boards du haut). */
  function openBoard(id,options){
    if(!id)throw Object.assign(new Error('identifiant de Board manquant'),{code:'invalid_board'});
    V.focusBoard={id:String(id),painted:false};
    const reading=manager.act('inspect-board',{id:String(id)});
    if(root.hidden)openView();else render();
    const opener=options&&options.opener;
    V.returnTo=opener&&typeof opener.focus==='function'?opener:null;
    return reading;
  }
  window.JarvisWorkspace={open:openView,close:closeView,openBoard,state:S,act:manager.act};
  console.info('[workspace] workspace.installed {}');
})();
