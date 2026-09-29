/* Boards — le contrôle du haut-droit (handoff jarvis-board-session-context-runtime, Slice 06).

   Contrat : `docs/boards.md`. Un Board est l'espace de travail durable ; une
   Session est la conversation en cours avec Jarvis. Ce module montre **en
   permanence** le titre du Board actif et ouvre un panneau simple : liste des
   Boards (l'actif marqué), bascule au clic, création, renommage, archivage, et
   « Nouvelle session ». Pas de carte, pas de minimap (hors périmètre V1).

   **Routes.** Uniquement celles du Control Center (`/api/boards*`,
   `/api/sessions*`, `jarvis/runtime/board_routes.py`), jamais MCP ni Core en
   direct. Ce sont les mêmes que les outils `jarvis-console` (parité UI/MCP).

   **Aucune peinture optimiste.** Le Board actif affiché vient **toujours** du
   bloc `boards` de `GET /api/status` (sondé chaque seconde par la page, porte
   `gate`) ou de la liste relue après une action. Un clic ne marque rien comme
   actif : il part en requête, montre son attente, puis relit le serveur. Un
   échec n'a donc rien à défaire — « revenir à la vérité du serveur » est
   structurel : on relit, et c'est la relecture qui peint.

   **RÈGLE ZÉRO.** Une bascule peut durer plusieurs secondes (Core active
   l'agent du Board cible, jusqu'à 60 s côté hôte). Pendant toute attente : le
   bouton et la ligne disent ce qui se passe, avec un compteur vivant et une
   barre qui bouge ; toute autre action est bloquée (pas de double envoi) ; et
   l'attente a une **échéance** au-delà de laquelle le contrôle rend la main,
   dit combien de temps il a attendu, et relit le serveur.

   **Emplacements.** Deux, déclarés dans `control_center.html` pour que leurs
   rangs vivent au registre d'empilement : `#boardsHud` (le bouton, dans
   `.topbar`, qui coupe les événements de pointeur — l'emplacement les rend) et
   `#boardsPanel` (le panneau, hors de la barre : la barre est un contexte
   d'empilement au rang 31, le panneau y serait enfermé sous le dock). Ce
   module refuse de s'installer si l'un manque, sous un nom cherchable, et ce
   refus est rattrapé : la page concatène tous ses modules dans un seul
   `<script>`. */
(function(root){
  'use strict';

  const DOM=Object.freeze({
    hostId:'boardsHud',
    panelId:'boardsPanel',
    styleId:'boardsStyle',
    triggerId:'boardsButton',
    titleId:'boardsTitle',
    subId:'boardsSub',
    headingId:'boardsHeading',
    closeId:'boardsClose',
    noteId:'boardsNote',
    listId:'boardsList',
    createInputId:'boardsCreateTitle',
    createButtonId:'boardsCreate',
    createErrorId:'boardsCreateError',
    sessionLineId:'boardsSessionLine',
    newSessionId:'boardsNewSession',
    announceId:'boardsAnnounce',
    boardAttribute:'data-board-id',
    actionAttribute:'data-bd-action',
    toneAttribute:'data-bd-tone',
    busyAttribute:'data-bd-busy',
  });

  /* Borne du titre : celle du contrat (`docs/boards.md` › Values › Board). */
  const TITLE_MAX=120;
  /* Séparateurs de ligne Unicode, refusés comme les sauts de ligne. */
  const LINE_BREAKS=[String.fromCharCode(0x2028),String.fromCharCode(0x2029)];

  /* Échéances client, par action. Une bascule et une nouvelle Session
     attendent l'activation d'un agent par Core (60 s côté hôte, puis sa
     restauration éventuelle) : 75 s. Le reste est une écriture SQLite. */
  const DEADLINE_MS=Object.freeze({
    switch:75000,new_session:75000,create:15000,rename:15000,archive:15000,list:15000});

  const PATH=Object.freeze({
    list:'/api/boards',
    create:'/api/boards',
    switch:'/api/boards/switch',
    session:'/api/sessions/current',
    newSession:'/api/sessions/new',
    board:id=>`/api/boards/${encodeURIComponent(id)}`,
    archive:id=>`/api/boards/${encodeURIComponent(id)}/archive`,
  });

  /* Les codes stables (`BoardErrorCode`, et ceux du relais du Control
     Center) traduits pour l'écran. Le message de Core reste visible à côté,
     en détail : on ne remplace jamais la vraie cause par une phrase générique. */
  const REFUSAL=Object.freeze({
    board_not_found:'Ce Board n’existe plus : il a été archivé ou retiré ailleurs.',
    board_archived:'Ce Board est archivé : il ne peut plus être ouvert ni modifié.',
    board_is_active:'Le Board actif ne peut pas être archivé. Basculez d’abord sur un autre Board.',
    session_closed:'La session a changé entre-temps (autre onglet, voix ou redémarrage). Rien n’a été fait ; l’affichage a été relu.',
    session_not_found:'Aucune session ouverte : Core n’a pas encore démarré sa session.',
    binding_conflict:'Une autre bascule est en cours. Réessayez dans un instant.',
    binding_not_found:'La liaison du Board actif est introuvable côté Core.',
    brain_not_foreground:'Ce Board n’a pas la parole.',
    invalid_title:'Titre refusé : 1 à 120 caractères, sur une seule ligne.',
    context_summary_too_long:'Le résumé du Board dépasse 1 500 caractères.',
    invalid_board:'Demande refusée par Core : Board invalide.',
    invalid_session:'Demande refusée par Core : session invalide.',
    invalid_binding:'Demande refusée par Core : liaison invalide.',
    invalid_request:'Demande mal formée, refusée par le Control Center.',
    board_activation_failed:'L’agent du Board n’a pas pu démarrer. Rien n’a changé : le Board précédent reste actif.',
    board_switch_rolled_back:'La bascule a échoué en cours de route et a été annulée. Le Board précédent reste actif.',
    board_store_unreadable:'Le stockage des Boards est illisible.',
    board_store_failed:'Le stockage des Boards est indisponible.',
    core_unreachable:'Core ne répond pas. Rien n’a changé.',
    core_unavailable:'Core n’est pas prêt. Rien n’a changé.',
    core_unconfigured:'Ce Control Center ne connaît pas Core : les Boards sont indisponibles.',
    core_boards_unsupported:'Ce Core ne gère pas encore les Boards.',
    network:'Le Control Center ne répond pas.',
  });

  /* Ce que chaque action dit pendant son attente. */
  const WAITING=Object.freeze({
    switch:'Activation de l’agent…',
    new_session:'Nouvelle session…',
    create:'Création…',
    rename:'Enregistrement…',
    archive:'Archivage…',
  });

  const ROW_WAITING=Object.freeze({switch:'Activation',rename:'Enregistrement',archive:'Archivage'});

  const ARCHIVE_ACTIVE_REASON='Le Board actif ne peut pas être archivé : basculez d’abord sur un autre Board.';
  const NEW_SESSION_HINT='Nouvelle conversation avec Jarvis sur ce Board. Le Board, ses tâches et le travail en cours sont conservés.';

  const isObject=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
  const text=value=>value===undefined||value===null?'':String(value);

  /* ------------------------------------------------ logique pure (testée) */

  /* Un titre tel que le contrat l'accepte : non vide une fois rogné, 120
     caractères au plus (comptés en points de code, comme Python), une seule
     ligne imprimable. Les espaces autour sont rognés **avant** l'envoi : Core
     les refuserait, et l'utilisateur ne les voit pas. */
  function validateTitle(raw){
    const value=text(raw).trim();
    if(!value)return {ok:false,value,error:'Donnez un titre au Board.'};
    const length=[...value].length;
    if(length>TITLE_MAX)return {ok:false,value,error:`Titre trop long : ${length} caractères sur ${TITLE_MAX}.`};
    // eslint-disable-next-line no-control-regex
    if(/[\u0000-\u001f\u007f-\u009f]/.test(value)||LINE_BREAKS.some(c=>value.includes(c)))
      return {ok:false,value,error:'Le titre doit tenir sur une seule ligne, sans caractère de contrôle.'};
    return {ok:true,value,error:''};
  }

  /* Le refus d'une requête, lu dans l'erreur que lève la porte réseau `api`
     de la page (`status`, `code`, `message` — l'enveloppe `{error:{code,
     message}}` des routes Boards y est dépliée). */
  function refusalOf(error){
    const status=error&&typeof error.status==='number'?error.status:null;
    const detail=text(error&&error.message);
    let code=text(error&&error.code);
    if(!code)code=status?`http_${status}`:'network';
    const known=REFUSAL[code];
    return Object.freeze({code,status,detail,
      text:known||(detail?`Échec : ${detail}`:`Échec (${code}).`)});
  }

  /* Le Board actif : le bloc de statut d'abord (1 Hz, le plus frais), la liste
     relue ensuite. */
  function activeIdOf(block,listing){
    if(isObject(block)&&isObject(block.active)&&block.active.board_id)return String(block.active.board_id);
    if(isObject(listing)&&listing.active_board_id)return String(listing.active_board_id);
    return null;
  }

  /* Boards dont un agent travaille encore en arrière-plan. */
  function workingIdsOf(block){
    const ids=new Set();
    if(!isObject(block)||!Array.isArray(block.bindings))return ids;
    for(const row of block.bindings)
      if(isObject(row)&&row.lifecycle==='background_running'&&row.board_id)ids.add(String(row.board_id));
    return ids;
  }

  /* Ce que le bouton du haut montre. Quatre tons :
     - `ready` : le Board actif, confirmé par le dernier statut ;
     - `pending` : une bascule ou une nouvelle Session est en vol ;
     - `unavailable` : Core n'a pas de Boards, ou ne répond pas ;
     - `unknown` : le sondage de statut lui-même est tombé. */
  function triggerViewOf(block,pending,seconds){
    const secs=Math.max(0,Math.floor(seconds||0));
    if(pending&&pending.kind==='switch')
      return {tone:'pending',title:text(pending.title),sub:`Bascule · ${secs} s`};
    if(block===null||block===undefined)
      return {tone:'unknown',title:'Inconnu',sub:'Statut perdu'};
    const active=isObject(block.active)?block.active:null;
    if(pending&&pending.kind==='new_session')
      return {tone:'pending',title:text(active&&active.title)||'Board',sub:`Nouvelle session · ${secs} s`};
    if(!block.available||!active){
      const code=isObject(block.error)?text(block.error.code):'';
      return {tone:'unavailable',title:'Indisponible',sub:code||'Core'};
    }
    const working=[...workingIdsOf(block)].filter(id=>id!==String(active.board_id)).length;
    return {tone:'ready',title:text(active.title)||text(active.board_id),
      sub:working?`${working} en arrière-plan`:''};
  }

  /* Les lignes du panneau, dans l'ordre de Core. */
  function rowsOf(listing,block,pending){
    const boards=isObject(listing)&&Array.isArray(listing.boards)?listing.boards:[];
    const activeId=activeIdOf(block,listing),working=workingIdsOf(block);
    return boards.filter(isObject).filter(b=>b.status!=='archived').map(b=>{
      const id=String(b.board_id),active=id===activeId;
      return {
        board_id:id,title:text(b.title)||id,active,
        working:!active&&working.has(id),
        pending:!!(pending&&pending.boardId===id)?pending.kind:null,
        canArchive:!active,
        archiveReason:active?ARCHIVE_ACTIVE_REASON:'',
      };
    });
  }

  /* ------------------------------------------------- alertes (Slice 07)

     Les alertes d'arrière-plan (`#bgPills`, `#bgPop` de la page) sont
     **globales** : visibles depuis n'importe quel Board, chacune nommant son
     Board source. « Aller au Board » passe par la bascule normale de ce
     module (`switchTo` -> `POST /api/boards/switch {board_id}`), avec son
     attente, son échéance et ses refus. Rien de l'alerte n'est envoyé : la
     requête ne porte que `board_id`, jamais de contexte à fusionner. */

  /* Ce que l'alerte dit de son Board. `null` quand la trace n'en nommait
     aucun (événement d'avant les Boards, processus voix).
     - `here` : c'est le Board actif (étiquette discrète, pas d'action) ;
     - sinon l'étiquette est mise en avant et l'action « Aller » est offerte. */
  function alertBoardOf(event,activeId){
    if(!isObject(event)||!event.board_id)return null;
    const id=String(event.board_id),title=text(event.board_title)||id;
    const here=activeId!==null&&activeId!==undefined&&id===String(activeId);
    return Object.freeze({board_id:id,title,here,
      label:here?`Ce Board · ${title}`:`Board « ${title} »`,
      action:here?'':`Aller au Board « ${title} »`});
  }

  /* Par catégorie, les non-vus venus d'un **autre** Board que l'actif, lus
     dans `background.sources` de `/api/status` : `{failed:[{board_id,title,
     count}],...}`. Les pastilles en tirent leur marque et leur libellé. */
  function elsewhereOf(sources,activeId){
    const out={};
    /* Board actif inconnu (Core sans Boards, statut lu sans bloc) : on ne
       prétend pas savoir ce qui vient « d'ailleurs ». */
    if(!Array.isArray(sources)||activeId===null||activeId===undefined)return out;
    for(const row of sources){
      if(!isObject(row)||!row.board_id||String(row.board_id)===String(activeId))continue;
      const counts=isObject(row.counts)?row.counts:{};
      for(const category of Object.keys(counts)){
        const n=Number(counts[category])||0;
        if(n<=0)continue;
        (out[category]=out[category]||[]).push({board_id:String(row.board_id),
          title:text(row.title)||String(row.board_id),count:n});
      }
    }
    return out;
  }

  /* Libellé d'une pastille : son compte, et d'où viennent ceux d'ailleurs. */
  function pillLabelOf(base,elsewhere){
    if(!Array.isArray(elsewhere)||!elsewhere.length)return base;
    return `${base} · dont ${elsewhere.map(r=>`${r.count} sur « ${r.title} »`).join(', ')}`;
  }

  /* « Aller au Board » depuis une alerte. Même transaction que le panneau
     (`control.switchTo`), avec l'attente montrée **sur le bouton cliqué** :
     compteur vivant, bouton inerte, puis le refus dit à côté (`note`) ou la
     réussite rendue (`true`). Une autre action Boards en vol : rien n'est
     envoyé, et c'est dit.

     **Échéance propre.** Le contrôle rend la main à 75 s, mais la promesse
     d'une requête qui ne répond jamais ne se règle jamais : sans seconde
     borne, ce bouton resterait « Bascule… » pour toujours. Il se libère donc
     lui-même juste après l'échéance du contrôle (`opts.setTimeout`), et dit
     ce que le contrôle a constaté. */
  async function goToBoardFromAlert(opts){
    const control=opts.control,button=opts.button,note=opts.note||null;
    const now=typeof opts.now==='function'?opts.now:()=>Date.now();
    const log=typeof opts.log==='function'?opts.log:function(){};
    const say=value=>{if(note){note.textContent=value;note.hidden=!value}};
    const id=text(opts.boardId),title=text(opts.title)||id;
    if(!control||typeof control.switchTo!=='function'){
      say('Le contrôle Boards n’est pas installé : ouvrez le Board depuis le haut de l’écran.');
      log('error','boards.alert_jump_failed',{board_id:id,code:'boards_control_missing'});
      return false;
    }
    if(button.getAttribute('aria-busy')==='true')return false;
    if(typeof control.pending==='function'&&control.pending()){
      say('Une autre action Boards est en cours. Réessayez quand elle est terminée.');
      log('info','boards.alert_jump_busy',{board_id:id});
      return false;
    }
    const idle=button.textContent,since=now();
    const paintWait=()=>{button.textContent=`Bascule… ${Math.max(0,Math.floor((now()-since)/1000))} s`};
    say('');
    button.setAttribute('aria-busy','true');button.setAttribute('aria-disabled','true');
    paintWait();
    const ticker=typeof opts.setInterval==='function'?opts.setInterval(paintWait,1000):0;
    log('info','boards.alert_jump_requested',{board_id:id});
    let answer=null,deadline=0;
    const EXPIRED={};
    const expiry=new Promise(resolve=>{
      if(typeof opts.setTimeout==='function')deadline=opts.setTimeout(()=>resolve(EXPIRED),DEADLINE_MS.switch+250);
    });
    try{
      answer=await Promise.race([control.switchTo(id,{title}),expiry]);
      if(answer===EXPIRED){answer=null;log('warn','boards.alert_jump_expired',{board_id:id,waited_ms:now()-since})}
    }catch(error){
      /* `switchTo` ne lève pas (il dit ses refus) ; une exception ici est un
         défaut du contrôle lui-même, dit comme tel. */
      say(`Bascule impossible : ${text(error&&error.message)||'erreur inattendue du contrôle Boards'}`);
      log('error','boards.alert_jump_failed',{board_id:id,code:'boards_control_threw',error:text(error&&error.message)});
      return false;
    }finally{
      if(deadline&&typeof opts.clearTimeout==='function')opts.clearTimeout(deadline);
      if(ticker&&typeof opts.clearInterval==='function')opts.clearInterval(ticker);
      button.removeAttribute('aria-busy');button.removeAttribute('aria-disabled');
      button.textContent=idle;
    }
    if(answer){log('info','boards.alert_jump_done',{board_id:id});return true}
    const failure=typeof control.failure==='function'?control.failure():null;
    say(failure&&failure.text?`${failure.text}${failure.detail?` (${failure.detail})`:''}`
      :'Bascule non confirmée : le Board affiché en haut est celui que le serveur confirme.');
    log('warn','boards.alert_jump_refused',{board_id:id,detail:failure?failure.detail||null:null});
    return false;
  }

  function sessionLineOf(session,visitedCount){
    if(!isObject(session))return '';
    const at=Date.parse(text(session.started_at));
    let since='';
    if(Number.isFinite(at)){
      const d=new Date(at);
      since=` · depuis ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
    }
    const visited=Array.isArray(session.visited_board_ids)?session.visited_board_ids.length:visitedCount||0;
    return `Session en cours${since}${visited>1?` · ${visited} Boards visités`:''}`;
  }

  /* ------------------------------------------------------------ icônes */

  const ICON=Object.freeze({
    chevron:'M6 9l6 6 6-6',
    rename:'M4 20h4L19 9l-4-4L4 16v4ZM13.5 6.5l4 4',
    archive:'M4 5h16v4H4ZM6 9v10h12V9M10 13h4',
    close:'M6 6l12 12M18 6 6 18',
    plus:'M12 5v14M5 12h14',
    session:'M4 5h16v11H9l-5 4V5ZM12 8v5M9.5 10.5h5',
  });

  function icon(doc,name,size){
    const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 24 24');
    svg.setAttribute('width',String(size||16));svg.setAttribute('height',String(size||16));
    svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');
    svg.setAttribute('stroke-width','1.8');svg.setAttribute('stroke-linecap','round');
    svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');
    svg.setAttribute('focusable','false');
    const path=doc.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d',ICON[name]||ICON.plus);
    svg.appendChild(path);
    return svg;
  }

  /* ------------------------------------------------------------ style */

  const ACCENT='var(--accent,#6ee7ff)',WARN='var(--warn,#ffb85c)',DANGER='var(--danger,#ff6577)';
  const OK='var(--ok,#68e0a0)',MUTED='var(--muted,#7190a0)',LINE='var(--line,#183343)',INK='var(--text,#d8edf7)';
  const H=`#${DOM.hostId}`,P=`#${DOM.panelId}`;

  /* Le positionnement et les rangs des deux emplacements vivent dans
     `control_center.html` (registre d'empilement) ; ici, l'apparence. */
  const STYLE=`
${H} .bd-btn{display:inline-flex;align-items:center;gap:9px;min-width:0;max-width:100%;
  padding:7px 10px 7px 12px;border:1px solid rgba(110,231,255,.18);background:rgba(3,8,12,.72);
  color:${INK};font:12px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;cursor:pointer;position:relative;
  -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
  transition:border-color .16s ease,color .16s ease,background .16s ease}
${H} .bd-btn:hover{border-color:color-mix(in srgb,${ACCENT} 60%,transparent)}
${H} .bd-btn:focus-visible{outline:2px solid ${ACCENT};outline-offset:3px}
${H} .bd-btn[aria-expanded=true]{border-color:color-mix(in srgb,${ACCENT} 70%,transparent);background:rgba(6,20,27,.86)}
${H} .bd-eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:${MUTED}}
${H} .bd-title{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  color:${ACCENT};font-weight:600;letter-spacing:.03em}
${H} .bd-sub{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:${MUTED};white-space:nowrap}
${H} .bd-sub:empty{display:none}
${H} .bd-chev{flex:0 0 auto;color:${MUTED};transition:transform .16s ease}
${H} .bd-btn[aria-expanded=true] .bd-chev{transform:rotate(180deg)}
${H}[${DOM.toneAttribute}=pending] .bd-sub{color:${ACCENT}}
${H}[${DOM.toneAttribute}=unknown] .bd-btn,${H}[${DOM.toneAttribute}=unavailable] .bd-btn{border-style:dashed}
${H}[${DOM.toneAttribute}=unknown] .bd-title,${H}[${DOM.toneAttribute}=unavailable] .bd-title{color:${MUTED};font-weight:400}
${H}[${DOM.toneAttribute}=unknown] .bd-sub,${H}[${DOM.toneAttribute}=unavailable] .bd-sub{color:${WARN}}
/* RÈGLE ZÉRO : l'attente se voit bouger ; le compteur monte même sans animation. */
${H} .bd-wait,${P} .bd-wait{position:absolute;left:8px;right:8px;bottom:3px;height:2px;border-radius:2px;overflow:hidden;
  display:none;background:color-mix(in srgb,${ACCENT} 20%,transparent)}
${H}[${DOM.busyAttribute}=true] .bd-wait{display:block}
${H} .bd-wait::after,${P} .bd-wait::after{content:'';position:absolute;top:0;bottom:0;left:0;width:40%;
  border-radius:2px;background:${ACCENT};animation:bdSweep 1.25s ease-in-out infinite}
@keyframes bdSweep{from{transform:translateX(-115%)}to{transform:translateX(260%)}}

${P}{width:min(372px,calc(100vw - 24px));max-height:calc(100vh - 90px);display:flex;flex-direction:column;
  border:1px solid ${LINE};border-radius:12px;background:var(--panel,rgba(6,12,18,.94));color:${INK};
  font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;
  box-shadow:0 18px 44px rgba(0,0,0,.52);-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);
  animation:bdPop .16s cubic-bezier(.16,1,.3,1)}
@keyframes bdPop{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
${P}:focus{outline:none}
${P} .bd-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 12px 8px 14px}
${P} h2{margin:0;font-size:11px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:${INK}}
${P} .bd-x{display:grid;place-items:center;width:28px;height:28px;border:1px solid transparent;border-radius:7px;
  background:none;color:${MUTED};cursor:pointer}
${P} .bd-x:hover{color:${INK};border-color:${LINE}}
${P} button:focus-visible,${P} input:focus-visible{outline:2px solid ${ACCENT};outline-offset:2px}
${P} .bd-note{margin:0 12px 8px;padding:7px 9px;border-radius:8px;font-size:11px;line-height:1.5;
  border:1px solid ${LINE};color:${MUTED};background:rgba(6,12,18,.5);overflow-wrap:anywhere}
${P} .bd-note[data-tone=bad]{color:#ffb3bd;border-color:color-mix(in srgb,${DANGER} 38%,transparent);background:rgba(35,7,12,.5)}
${P} .bd-note[data-tone=wait]{color:${ACCENT};border-color:color-mix(in srgb,${ACCENT} 32%,transparent);background:rgba(6,26,33,.5)}
${P} .bd-note[data-tone=warn]{color:${WARN};border-color:color-mix(in srgb,${WARN} 34%,transparent);background:rgba(38,23,5,.45)}
${P} .bd-note small{display:block;margin-top:3px;font-size:10px;color:${MUTED}}
${P} .bd-list{list-style:none;margin:0;padding:2px 8px 8px;display:grid;gap:4px;overflow-y:auto;overscroll-behavior:contain;min-height:0}
${P} .bd-empty{padding:14px 6px;color:${MUTED};font-size:11px;text-align:center}
${P} .bd-row{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:2px;align-items:center;
  border:1px solid transparent;border-radius:9px;transition:background .14s ease,border-color .14s ease}
${P} .bd-row:hover{background:rgba(110,231,255,.045)}
${P} .bd-row[data-active=true]{border-color:color-mix(in srgb,${ACCENT} 42%,transparent);background:rgba(110,231,255,.07)}
${P} .bd-row[${DOM.busyAttribute}=true] .bd-wait{display:block}
${P} .bd-pick{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:10px;align-items:center;min-width:0;
  padding:9px 8px 9px 10px;border:0;background:none;color:inherit;font:inherit;text-align:left;cursor:pointer;border-radius:8px}
${P} .bd-dot{width:10px;height:10px;border-radius:50%;border:1.5px solid color-mix(in srgb,${MUTED} 80%,transparent)}
${P} .bd-row[data-active=true] .bd-dot{border-color:${ACCENT};background:${ACCENT};
  box-shadow:0 0 0 3px color-mix(in srgb,${ACCENT} 18%,transparent)}
${P} .bd-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px}
${P} .bd-row[data-active=true] .bd-name{color:${ACCENT};font-weight:600}
${P} .bd-state{font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:${MUTED};white-space:nowrap}
${P} .bd-state:empty{display:none}
${P} .bd-row[data-active=true] .bd-state{color:${ACCENT}}
${P} .bd-state[data-tone=working]{color:${OK}}
${P} .bd-state[data-tone=wait]{color:${ACCENT}}
${P} .bd-icon{display:grid;place-items:center;width:30px;height:30px;border:1px solid transparent;border-radius:7px;
  background:none;color:${MUTED};cursor:pointer}
${P} .bd-icon:hover:not([aria-disabled=true]){color:${ACCENT};border-color:${LINE}}
${P} .bd-icon[${DOM.actionAttribute}=archive]:hover:not([aria-disabled=true]){color:${DANGER}}
${P} [aria-disabled=true]{opacity:.42;cursor:not-allowed}
${P} .bd-pick[aria-disabled=true]{opacity:.6;cursor:progress}
${P} .bd-edit{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:6px;padding:6px}
${P} .bd-rowerr{grid-column:1/-1;margin:0 8px 6px;font-size:10.5px;color:#ffb3bd}
${P} .bd-rowerr:empty{display:none}
${P} .bd-field{min-width:0;width:100%;padding:7px 9px;border:1px solid ${LINE};border-radius:7px;background:#071015;
  color:${INK};font:inherit;font-size:12.5px}
${P} .bd-field:focus{border-color:color-mix(in srgb,${ACCENT} 60%,transparent)}
${P} .bd-field[aria-invalid=true]{border-color:color-mix(in srgb,${DANGER} 60%,transparent)}
${P} .bd-act{padding:7px 11px;border:1px solid ${LINE};border-radius:7px;background:#0b141a;color:${INK};
  font:inherit;font-size:11.5px;cursor:pointer;white-space:nowrap}
${P} .bd-act:hover:not([aria-disabled=true]){border-color:${ACCENT}}
${P} .bd-act.primary{border-color:color-mix(in srgb,${ACCENT} 55%,transparent);color:${ACCENT}}
${P} .bd-create{padding:10px 14px 12px;border-top:1px solid ${LINE}}
${P} .bd-label{display:block;margin-bottom:6px;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:${MUTED}}
${P} .bd-create-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px}
${P} .bd-fielderr{margin:6px 0 0;font-size:10.5px;color:#ffb3bd}
${P} .bd-fielderr:empty{display:none}
${P} .bd-foot{padding:10px 14px 13px;border-top:1px solid ${LINE};display:grid;gap:7px}
${P} .bd-session{font-size:10px;letter-spacing:.06em;color:${MUTED}}
${P} .bd-session:empty{display:none}
${P} .bd-foot .bd-act{display:inline-flex;align-items:center;gap:8px;justify-self:start}
${P} .bd-foot p{margin:0;font-size:10.5px;line-height:1.5;color:${MUTED}}
${P} .bd-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:700px){
  ${H} .bd-eyebrow{display:none}
}
@media(prefers-reduced-motion:reduce){
  ${H} .bd-wait::after,${P} .bd-wait::after{animation:none;width:100%;opacity:.6}
  ${P}{animation:none}
  ${H} .bd-btn,${H} .bd-chev,${P} .bd-row{transition:none}
}`;

  function installStyle(doc){
    if(doc.getElementById(DOM.styleId))return;
    const style=doc.createElement('style');
    style.id=DOM.styleId;style.textContent=STYLE;
    doc.head.appendChild(style);
  }

  /* ------------------------------------------------------------ contrôle */

  function createBoardsControl(deps){
    const doc=deps.document,host=deps.host,panel=deps.panel;
    const now=typeof deps.now==='function'?deps.now:()=>Date.now();
    const arm=deps.setInterval,disarm=deps.clearInterval;
    const later=deps.setTimeout,unlater=deps.clearTimeout;
    const log=typeof deps.log==='function'?deps.log:function(){};
    /* Les portes de la page, **passées plutôt que prises** : prises dans un
       global, ce contrôle serait inexerçable sous node. */
    const request=typeof deps.request==='function'?deps.request:null;
    const refresh=typeof deps.refresh==='function'?deps.refresh:null;
    const toast=typeof deps.toast==='function'?deps.toast:null;
    const askConfirm=typeof deps.confirm==='function'?deps.confirm:null;
    const place=typeof deps.place==='function'?deps.place:null;

    let block=null,listing=null,session=null,listError=null,loading=false,loadSeq=0;
    let pending=null,failure=null,editing=null,editError='',editDraft=null,opened=false,ticker=0,listSignature='';
    const waits=new Set();

    installStyle(doc);
    const clear=el=>{while(el.firstChild)el.removeChild(el.firstChild)};
    const el=(tag,cls,content)=>{const n=doc.createElement(tag);if(cls)n.className=cls;if(content!==undefined)n.textContent=content;return n};
    const waitSeconds=()=>pending?Math.max(0,(now()-pending.since)/1000):0;
    const disable=(node,on)=>{if(on)node.setAttribute('aria-disabled','true');else node.removeAttribute('aria-disabled')};

    /* ---- le bouton du haut */
    const trigger=el('button','bd-btn');
    trigger.id=DOM.triggerId;trigger.setAttribute('type','button');
    trigger.setAttribute('aria-haspopup','dialog');trigger.setAttribute('aria-expanded','false');
    trigger.setAttribute('aria-controls',DOM.panelId);
    const eyebrow=el('span','bd-eyebrow','Board');
    const title=el('span','bd-title');title.id=DOM.titleId;
    const sub=el('span','bd-sub');sub.id=DOM.subId;
    const chev=el('span','bd-chev');chev.appendChild(icon(doc,'chevron',14));
    const triggerWait=el('span','bd-wait');triggerWait.setAttribute('aria-hidden','true');
    trigger.appendChild(eyebrow);trigger.appendChild(title);trigger.appendChild(sub);
    trigger.appendChild(chev);trigger.appendChild(triggerWait);
    host.appendChild(trigger);

    /* ---- le panneau */
    panel.hidden=true;
    panel.setAttribute('role','dialog');
    panel.setAttribute('aria-labelledby',DOM.headingId);
    panel.setAttribute('tabindex','-1');
    const head=el('div','bd-head');
    const heading=el('h2','','Boards');heading.id=DOM.headingId;
    const closer=el('button','bd-x');closer.id=DOM.closeId;closer.setAttribute('type','button');
    closer.setAttribute('aria-label','Fermer les Boards (Échap)');closer.appendChild(icon(doc,'close',15));
    head.appendChild(heading);head.appendChild(closer);
    const note=el('p','bd-note');note.id=DOM.noteId;note.hidden=true;note.setAttribute('role','status');
    const noteText=el('span','');const noteDetail=el('small','');
    note.appendChild(noteText);note.appendChild(noteDetail);
    const list=el('ul','bd-list');list.id=DOM.listId;list.setAttribute('aria-label','Boards');

    const create=el('div','bd-create');
    const createLabel=el('label','bd-label','Nouveau Board');createLabel.setAttribute('for',DOM.createInputId);
    const createRow=el('div','bd-create-row');
    const createInput=el('input','bd-field');createInput.id=DOM.createInputId;
    createInput.setAttribute('type','text');createInput.setAttribute('autocomplete','off');
    createInput.setAttribute('placeholder','Titre du Board');createInput.setAttribute('maxlength',String(TITLE_MAX*2));
    createInput.setAttribute('aria-describedby',DOM.createErrorId);
    const createButton=el('button','bd-act primary','Créer');createButton.id=DOM.createButtonId;
    createButton.setAttribute('type','button');
    createRow.appendChild(createInput);createRow.appendChild(createButton);
    const createError=el('p','bd-fielderr');createError.id=DOM.createErrorId;createError.setAttribute('role','alert');
    create.appendChild(createLabel);create.appendChild(createRow);create.appendChild(createError);

    const foot=el('div','bd-foot');
    const sessionLine=el('div','bd-session');sessionLine.id=DOM.sessionLineId;
    const newSession=el('button','bd-act');newSession.id=DOM.newSessionId;newSession.setAttribute('type','button');
    newSession.appendChild(icon(doc,'session',15));newSession.appendChild(el('span','','Nouvelle session'));
    const newSessionHint=el('p','',NEW_SESSION_HINT);newSessionHint.id=`${DOM.newSessionId}Hint`;
    newSession.setAttribute('aria-describedby',newSessionHint.id);
    foot.appendChild(sessionLine);foot.appendChild(newSession);foot.appendChild(newSessionHint);

    const announce=el('span','bd-sr');announce.id=DOM.announceId;announce.setAttribute('aria-live','polite');

    panel.appendChild(head);panel.appendChild(note);panel.appendChild(list);
    panel.appendChild(create);panel.appendChild(foot);panel.appendChild(announce);

    /* ---------------------------------------------------------- peinture */

    function paintTrigger(){
      const view=triggerViewOf(block,pending,waitSeconds());
      host.setAttribute(DOM.toneAttribute,view.tone);
      host.setAttribute(DOM.busyAttribute,pending&&(pending.kind==='switch'||pending.kind==='new_session')?'true':'false');
      if(title.textContent!==view.title)title.textContent=view.title;
      if(sub.textContent!==view.sub)sub.textContent=view.sub;
      const label=view.tone==='ready'?`Board actif : ${view.title}. Ouvrir la liste des Boards`
        :view.tone==='pending'?`${view.title} — ${view.sub}. Ouvrir la liste des Boards`
        :`Boards ${view.title.toLowerCase()} (${view.sub}). Ouvrir la liste des Boards`;
      trigger.setAttribute('aria-label',label);
      trigger.setAttribute('title',view.tone==='ready'?`Board actif : ${view.title}`:label);
      return view;
    }

    function paintNote(){
      let tone='',said='',detail='';
      if(pending&&WAITING[pending.kind]){
        tone='wait';
        said=`${WAITING[pending.kind]} ${Math.floor(waitSeconds())} s`;
        if(pending.kind==='switch')detail=`Vers « ${pending.title} ». Les autres actions attendent la fin.`;
      }else if(failure){tone=failure.tone||'bad';said=failure.text;detail=failure.detail||''}
      else if(listError){tone='bad';said=`Liste des Boards illisible : ${listError.text}`;detail=listError.detail||''}
      note.hidden=!said;
      note.setAttribute('data-tone',tone);
      note.setAttribute('role',tone==='bad'?'alert':'status');
      if(noteText.textContent!==said)noteText.textContent=said;
      if(noteDetail.textContent!==detail)noteDetail.textContent=detail;
    }

    function signatureOfRows(rows){
      return JSON.stringify([rows,editing,editError,!!pending,loading,listing===null]);
    }

    function focusKey(){
      const at=doc.activeElement;
      if(!at||!at.getAttribute)return null;
      const id=at.getAttribute(DOM.boardAttribute);
      return id?{id,action:at.getAttribute(DOM.actionAttribute)}:null;
    }

    function findRowControl(id,action){
      for(const row of list.children)
        if(row.getAttribute(DOM.boardAttribute)===id)
          for(const node of walk(row))
            if(node.getAttribute&&node.getAttribute(DOM.actionAttribute)===action)return node;
      return null;
    }

    function paintList(force){
      const rows=rowsOf(listing,block,pending);
      const signature=signatureOfRows(rows);
      if(!force&&signature===listSignature){paintRowWaits(rows);return rows}
      listSignature=signature;
      const kept=focusKey();
      clear(list);
      if(listing===null){
        list.appendChild(el('li','bd-empty',loading?'Chargement des Boards…':'Liste non chargée.'));
      }else if(!rows.length){
        list.appendChild(el('li','bd-empty','Aucun Board.'));
      }
      for(const row of rows)list.appendChild(row.board_id===editing?editRow(row):pickRow(row));
      if(kept){const again=findRowControl(kept.id,kept.action);if(again)again.focus()}
      paintRowWaits(rows);
      return rows;
    }

    function pickRow(row){
      const li=el('li','bd-row');
      li.setAttribute(DOM.boardAttribute,row.board_id);
      li.setAttribute('data-active',row.active?'true':'false');
      li.setAttribute(DOM.busyAttribute,row.pending?'true':'false');
      const pick=el('button','bd-pick');pick.setAttribute('type','button');
      pick.setAttribute(DOM.boardAttribute,row.board_id);pick.setAttribute(DOM.actionAttribute,'switch');
      if(row.active)pick.setAttribute('aria-current','true');
      pick.setAttribute('aria-label',row.active?`${row.title} — Board actif`
        :`Basculer sur ${row.title}${row.working?' (travail en arrière-plan)':''}`);
      disable(pick,!!pending&&!row.active);
      const dot=el('span','bd-dot');dot.setAttribute('aria-hidden','true');
      const name=el('span','bd-name',row.title);name.setAttribute('title',row.title);
      const state=el('span','bd-state');state.setAttribute('data-role','state');
      pick.appendChild(dot);pick.appendChild(name);pick.appendChild(state);
      pick.addEventListener('click',()=>{switchTo(row.board_id)});
      li.appendChild(pick);

      const rename=el('button','bd-icon');rename.setAttribute('type','button');
      rename.setAttribute(DOM.boardAttribute,row.board_id);rename.setAttribute(DOM.actionAttribute,'rename');
      rename.setAttribute('aria-label',`Renommer ${row.title}`);rename.setAttribute('title','Renommer');
      rename.appendChild(icon(doc,'rename',15));disable(rename,!!pending);
      rename.addEventListener('click',()=>{startEdit(row.board_id)});
      li.appendChild(rename);

      const archive=el('button','bd-icon');archive.setAttribute('type','button');
      archive.setAttribute(DOM.boardAttribute,row.board_id);archive.setAttribute(DOM.actionAttribute,'archive');
      archive.setAttribute('aria-label',row.canArchive?`Archiver ${row.title}`:`Archiver ${row.title} — impossible : ${row.archiveReason}`);
      archive.setAttribute('title',row.canArchive?'Archiver':row.archiveReason);
      archive.appendChild(icon(doc,'archive',15));disable(archive,!row.canArchive||!!pending);
      archive.addEventListener('click',()=>{archiveBoard(row.board_id)});
      li.appendChild(archive);
      const wait=el('span','bd-wait');wait.setAttribute('aria-hidden','true');li.appendChild(wait);
      return li;
    }

    function editRow(row){
      const li=el('li','bd-row');
      li.setAttribute(DOM.boardAttribute,row.board_id);
      li.setAttribute('data-active',row.active?'true':'false');
      li.setAttribute(DOM.busyAttribute,row.pending?'true':'false');
      const box=el('div','bd-edit');
      const field=el('input','bd-field');field.setAttribute('type','text');field.setAttribute('autocomplete','off');
      field.setAttribute(DOM.boardAttribute,row.board_id);field.setAttribute(DOM.actionAttribute,'title');
      field.setAttribute('aria-label',`Nouveau titre de ${row.title}`);
      field.value=editing===row.board_id&&editDraft!==null?editDraft:row.title;
      field.setAttribute('aria-invalid',editError?'true':'false');
      field.addEventListener('input',()=>{editDraft=field.value});
      field.addEventListener('keydown',event=>{
        if(event.key==='Enter'){event.preventDefault();saveEdit(row.board_id)}
        else if(event.key==='Escape'){event.preventDefault();event.stopPropagation&&event.stopPropagation();cancelEdit()}
      });
      const save=el('button','bd-act primary','Renommer');save.setAttribute('type','button');
      save.setAttribute(DOM.boardAttribute,row.board_id);save.setAttribute(DOM.actionAttribute,'save');
      disable(save,!!pending);
      save.addEventListener('click',()=>{saveEdit(row.board_id)});
      const cancel=el('button','bd-act','Annuler');cancel.setAttribute('type','button');
      cancel.setAttribute(DOM.boardAttribute,row.board_id);cancel.setAttribute(DOM.actionAttribute,'cancel');
      cancel.addEventListener('click',()=>{cancelEdit()});
      box.appendChild(field);box.appendChild(save);box.appendChild(cancel);
      li.appendChild(box);
      const error=el('p','bd-rowerr',editError);error.setAttribute('role','alert');li.appendChild(error);
      const wait=el('span','bd-wait');wait.setAttribute('aria-hidden','true');li.appendChild(wait);
      return li;
    }

    /* Le texte d'état de chaque ligne, repeint à chaque seconde sans refaire
       la liste (le compteur monte, le focus ne bouge pas). */
    function paintRowWaits(rows){
      const byId=new Map(rows.map(r=>[r.board_id,r]));
      for(const li of list.children){
        const row=byId.get(li.getAttribute(DOM.boardAttribute));
        if(!row)continue;
        li.setAttribute(DOM.busyAttribute,row.pending?'true':'false');
        const state=walk(li).find(n=>n.getAttribute&&n.getAttribute('data-role')==='state');
        if(!state)continue;
        let said='',tone='';
        /* Court dans la ligne, pour ne pas manger le titre ; la phrase
           complète est dans le bandeau du panneau. */
        if(row.pending){said=`${ROW_WAITING[row.pending]||'…'} · ${Math.floor(waitSeconds())} s`;tone='wait'}
        else if(row.active)said='Actif';
        else if(row.working){said='En fond';tone='working'}
        if(state.textContent!==said)state.textContent=said;
        state.setAttribute('data-tone',tone);
      }
    }

    function paintControls(){
      const busy=!!pending;
      disable(createButton,busy);disable(newSession,busy||!(block&&block.available));
      createInput.setAttribute('aria-invalid',createError.textContent?'true':'false');
      const line=sessionLineOf(session);
      if(sessionLine.textContent!==line)sessionLine.textContent=line;
    }

    function paint(force){
      paintTrigger();
      if(!opened)return;
      paintNote();paintList(force);paintControls();
    }

    /* ---------------------------------------------------------- ouverture */

    function open(){
      if(opened)return;
      opened=true;failure=null;
      panel.hidden=false;
      trigger.setAttribute('aria-expanded','true');
      if(place)place(panel,trigger);
      paint(true);
      /* Liste déjà connue (réouverture) : le focus va au Board actif tout de
         suite. Sinon il attend sur le panneau et rejoint le Board actif dès que
         la liste arrive — à moins que l'utilisateur ne soit déjà ailleurs. */
      if(listing)focusActive();else panel.focus();
      log('info','boards.panel_opened',{active_board_id:activeIdOf(block,listing)});
      load().then(()=>{if(opened&&(doc.activeElement===panel||!doc.activeElement))focusActive()});
    }

    function close(options){
      if(!opened)return;
      opened=false;editing=null;editError='';editDraft=null;
      panel.hidden=true;
      trigger.setAttribute('aria-expanded','false');
      if(options&&options.focus)trigger.focus();
    }

    function focusActive(){
      const picks=walk(list).filter(n=>n.getAttribute&&n.getAttribute(DOM.actionAttribute)==='switch');
      const target=picks.find(n=>n.getAttribute('aria-current')==='true')||picks[0];
      if(target)target.focus();else createInput.focus();
    }

    /* ---------------------------------------------------------- lecture */

    /* Relire la liste et la Session. Jamais d'exception vers l'appelant : un
       échec se dit dans le panneau. Une réponse dépassée par une plus récente
       est ignorée. */
    async function load(){
      if(!request){listError={text:'la porte réseau de la page manque',detail:''};paint(true);return false}
      const mine=++loadSeq;
      loading=true;paint(true);
      let deadline=0;
      const expired=new Promise(resolve=>{deadline=later(()=>resolve('timeout'),DEADLINE_MS.list)});
      waits.add(deadline);
      try{
        const [boards,current]=await Promise.race([
          Promise.all([request(PATH.list),request(PATH.session).catch(error=>({__error:error}))]),
          expired.then(()=>{throw Object.assign(new Error(`pas de réponse après ${DEADLINE_MS.list/1000} s`),{code:'timeout'})}),
        ]);
        if(mine!==loadSeq)return false;
        listing=isObject(boards)?boards:{boards:[]};
        session=current&&current.__error?null:(isObject(current)?current.session:null);
        listError=null;
        return true;
      }catch(error){
        if(mine!==loadSeq)return false;
        const said=refusalOf(error);
        listError={text:said.code==='timeout'?`pas de réponse après ${DEADLINE_MS.list/1000} s`:said.text,
          detail:said.detail&&said.detail!==said.text?`${said.code} · ${said.detail}`:said.code};
        log('error','boards.list_failed',{code:said.code,status:said.status,error:said.detail});
        return false;
      }finally{
        if(waits.delete(deadline))unlater(deadline);
        if(mine===loadSeq){loading=false;paint(true)}
      }
    }

    /* Revenir à la vérité du serveur : statut canonique (bouton du haut) et
       liste. Ne lève pas. */
    async function resync(){
      const jobs=[load()];
      if(refresh)jobs.push(Promise.resolve().then(()=>refresh()).catch(error=>{
        log('warn','boards.refresh_failed',{error:text(error&&error.message)||text(error)});
      }));
      await Promise.all(jobs);
    }

    /* ---------------------------------------------------------- actions */

    function startTicker(){
      if(ticker||typeof arm!=='function')return;
      ticker=arm(()=>{paint(false)},1000);
    }
    function stopTicker(){
      if(ticker&&typeof disarm==='function')disarm(ticker);
      ticker=0;
    }

    function fail(said,kind,data,options){
      /* `inline` : le refus est déjà dit à côté du champ (création,
         renommage) ; le bandeau le répéterait. */
      if(!(options&&options.inline))
        failure=Object.freeze({text:said.text,tone:said.tone||'bad',
          detail:said.detail&&said.detail!==said.text?`${said.code} · ${said.detail}`:(said.code||'')});
      announce.textContent=said.text;
      log(said.level||'error',`boards.${kind}_failed`,Object.assign({code:said.code,status:said.status||null,
        error:said.detail||''},data||{}));
      /* Le panneau fermé (ou l'utilisateur ailleurs) : l'infusion le dit. */
      if(toast&&(!opened||(options&&options.toast)))
        toast({title:TOAST_TITLE[kind]||'Boards',sub:said.text,kind:said.tone==='warn'?'warn':'bad'});
      paint(true);
    }
    const TOAST_TITLE=Object.freeze({switch:'Bascule de Board impossible',new_session:'Nouvelle session impossible',
      create:'Création de Board impossible',rename:'Renommage impossible',archive:'Archivage impossible'});

    /* Une action : une seule à la fois, bornée dans le temps, et suivie d'une
       relecture du serveur quel que soit son sort. `call` rend la réponse. */
    async function run(kind,meta,call,onDone,options){
      if(pending)return null;
      if(!request){
        fail({code:'request_gate_missing',text:'La page ne peut pas écrire : la porte réseau manque.'},kind,meta);
        return null;
      }
      pending=Object.assign({kind,since:now()},meta||{});
      failure=null;
      startTicker();
      paint(true);
      log('info',`boards.${kind}_requested`,meta||{});
      let expired=false;
      const ticket=later(()=>{
        waits.delete(ticket);
        if(!pending)return;
        expired=true;
        const waited=Math.round(waitSeconds());
        pending=null;stopTicker();
        fail({code:'timeout',status:null,detail:`${waited} s`,
          text:`Pas de réponse au bout de ${waited} s. L’affichage suit ce que le serveur confirme ; réessayez si rien n’a changé.`},
          kind,Object.assign({waited_s:waited},meta||{}),{toast:true});
        resync();
      },DEADLINE_MS[kind]||15000);
      waits.add(ticket);
      try{
        const answer=await call();
        if(expired)return null;
        if(waits.delete(ticket))unlater(ticket);
        pending=null;stopTicker();
        log('info',`boards.${kind}_done`,meta||{});
        await resync();
        if(onDone)onDone(answer);
        return answer||{};
      }catch(error){
        if(expired)return null;
        if(waits.delete(ticket))unlater(ticket);
        pending=null;stopTicker();
        const said=refusalOf(error);
        /* Dire l'échec **tout de suite**, puis relire le serveur : la relecture
           peut prendre des secondes (Core arrêté : connexion refusée après ses
           essais), et un écran muet pendant ce temps ne dit rien de ce qui
           vient d'arriver. La relecture ne touche pas à la phrase affichée. */
        fail(said,kind,meta,{toast:kind==='switch'||kind==='new_session',inline:!!(options&&options.inline)});
        await resync();
        return null;
      }finally{
        if(!expired){pending=null;stopTicker();paint(true)}
      }
    }

    const titleOf=id=>{const row=rowsOf(listing,block,null).find(r=>r.board_id===id);return row?row.title:id};
    const post=(path,body,method)=>request(path,{method:method||'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});

    /* `hint.title` : le titre connu de l'appelant (une alerte), quand la liste
       n'a pas encore été lue. */
    async function switchTo(boardId,hint){
      if(pending)return null;
      const id=String(boardId);
      if(id===activeIdOf(block,listing)){close({focus:true});return null}
      const listed=titleOf(id);
      const target=listed!==id?listed:(isObject(hint)&&text(hint.title))||id;
      return run('switch',{boardId:id,title:target},()=>post(PATH.switch,{board_id:id}),answer=>{
        const said=`Board « ${target} » actif.`;
        announce.textContent=said;
        if(toast)toast({title:said,sub:'La voix et la conversation suivent ce Board. Le Board quitté garde son travail en cours.',kind:'ok'});
        if(answer&&answer.changed===false)log('info','boards.switch_noop',{board_id:id});
        close({focus:true});
      });
    }

    async function createBoard(){
      if(pending)return null;
      const check=validateTitle(createInput.value);
      if(!check.ok){
        createError.textContent=check.error;paintControls();
        log('info','boards.create_invalid',{reason:check.error});
        createInput.focus();
        return null;
      }
      createError.textContent='';
      let createdId=null;
      const result=await run('create',{title:check.value},async()=>{
        try{return await post(PATH.create,{title:check.value})}
        catch(error){createError.textContent=refusalOf(error).text;throw error}
      },answer=>{
        createdId=answer&&isObject(answer.board)?String(answer.board.board_id):null;
        createInput.value='';createError.textContent='';
        const said=`Board « ${check.value} » créé.`;
        announce.textContent=said;
        if(toast)toast({title:said,sub:'Il n’est pas encore ouvert : choisissez-le dans la liste pour y basculer.',kind:'ok'});
      },{inline:true});
      if(createdId){paint(true);const pick=findRowControl(createdId,'switch');if(pick)pick.focus()}
      else if(!result)createInput.focus();
      return result;
    }

    function startEdit(boardId){
      if(pending)return;
      editing=String(boardId);editError='';editDraft=null;
      paint(true);
      const field=findRowControl(editing,'title');
      if(field){field.focus();if(typeof field.select==='function')field.select()}
    }

    function cancelEdit(){
      const id=editing;
      editing=null;editError='';editDraft=null;
      paint(true);
      const back=id&&findRowControl(id,'rename');
      if(back)back.focus();
    }

    async function saveEdit(boardId){
      if(pending||editing!==String(boardId))return null;
      const id=editing,field=findRowControl(id,'title');
      const check=validateTitle(field?field.value:editDraft);
      if(!check.ok){editError=check.error;editDraft=field?field.value:editDraft;paint(true);
        const again=findRowControl(id,'title');if(again)again.focus();return null}
      if(check.value===titleOf(id)){cancelEdit();return null}
      editDraft=check.value;
      const result=await run('rename',{boardId:id,title:check.value},async()=>{
        try{return await post(PATH.board(id),{title:check.value},'PATCH')}
        catch(error){editError=refusalOf(error).text;throw error}
      },()=>{
        editing=null;editError='';editDraft=null;
        announce.textContent=`Board renommé en « ${check.value} ».`;
      },{inline:true});
      if(result){paint(true);const back=findRowControl(id,'rename');if(back)back.focus()}
      else if(editing){const again=findRowControl(id,'title');if(again)again.focus()}
      return result;
    }

    async function archiveBoard(boardId){
      if(pending)return null;
      const id=String(boardId),name=titleOf(id);
      if(id===activeIdOf(block,listing)){
        /* Refusé **ici**, sans aller-retour : le serveur répondrait 409
           `board_is_active`. Le bouton reste atteignable pour pouvoir le dire. */
        failure=Object.freeze({text:ARCHIVE_ACTIVE_REASON,tone:'warn',detail:'board_is_active'});
        announce.textContent=ARCHIVE_ACTIVE_REASON;
        log('info','boards.archive_refused_active',{board_id:id});
        paint(true);
        return null;
      }
      if(!askConfirm){
        fail({code:'confirm_missing',text:'Archivage non confirmé : la boîte de confirmation manque.'},'archive',{boardId:id});
        return null;
      }
      const yes=await askConfirm({title:`Archiver « ${name} » ?`,danger:true,confirmLabel:'Archiver',
        lines:['Le Board disparaît de la liste. Son contexte et ses références sont conservés.',
          'Le travail déjà lancé sur ce Board continue.',
          'Irréversible dans cette version : un Board archivé ne peut plus être rouvert.']});
      if(!yes){log('info','boards.archive_cancelled',{board_id:id});return null}
      return run('archive',{boardId:id,title:name},()=>post(PATH.archive(id),{}),()=>{
        const said=`Board « ${name} » archivé.`;
        announce.textContent=said;
        if(toast)toast({title:said,kind:'ok'});
        /* Sa ligne a disparu, et le focus avec elle : il revient au Board actif,
           sinon Échap et les flèches ne répondraient plus. */
        focusActive();
      });
    }

    async function startNewSession(){
      if(pending)return null;
      if(!(block&&block.available)){
        failure=Object.freeze({text:REFUSAL.core_unavailable,tone:'warn',detail:''});paint(true);return null}
      const boardTitle=text(block.active&&block.active.title);
      if(askConfirm){
        const yes=await askConfirm({title:'Démarrer une nouvelle session ?',confirmLabel:'Nouvelle session',
          lines:[`Nouvelle conversation avec Jarvis, sur le Board « ${boardTitle} ».`,
            'Le Board, ses tâches et le travail en arrière-plan sont conservés.',
            'La conversation actuelle est close ; elle reste dans l’historique.']});
        if(!yes){log('info','boards.new_session_cancelled',{});return null}
      }
      /* `expected_session_id` : la Session que cet écran a lue. Si elle a déjà
         été close (autre onglet, voix), Core refuse `session_closed` au lieu
         d'en ouvrir une seconde. */
      const expected=isObject(session)&&session.jarvis_session_id?String(session.jarvis_session_id):null;
      return run('new_session',{title:boardTitle,expected},
        ()=>post(PATH.newSession,expected?{expected_session_id:expected}:{}),()=>{
          const said='Nouvelle session ouverte.';
          announce.textContent=said;
          if(toast)toast({title:said,sub:`Conversation neuve sur « ${boardTitle} ». Board et tâches conservés.`,kind:'ok'});
          close({focus:true});
        });
    }

    /* ---------------------------------------------------------- clavier */

    trigger.addEventListener('click',()=>{if(opened)close({focus:true});else open()});
    trigger.addEventListener('keydown',event=>{
      if(event.key==='ArrowDown'&&!opened){event.preventDefault();open()}
    });
    closer.addEventListener('click',()=>close({focus:true}));
    createButton.addEventListener('click',()=>{createBoard()});
    createInput.addEventListener('keydown',event=>{
      if(event.key==='Enter'){event.preventDefault();createBoard()}
    });
    createInput.addEventListener('input',()=>{if(createError.textContent){createError.textContent='';paintControls()}});
    newSession.addEventListener('click',()=>{startNewSession()});
    panel.addEventListener('keydown',event=>{
      if(event.key==='Escape'){
        if(event.defaultPrevented)return;
        event.preventDefault();
        if(editing)cancelEdit();else close({focus:true});
        return;
      }
      const at=doc.activeElement;
      if(!at||!at.getAttribute||at.getAttribute(DOM.actionAttribute)!=='switch')return;
      const picks=walk(list).filter(n=>n.getAttribute&&n.getAttribute(DOM.actionAttribute)==='switch');
      const i=picks.indexOf(at);
      let next=-1;
      if(event.key==='ArrowDown')next=Math.min(picks.length-1,i+1);
      else if(event.key==='ArrowUp')next=Math.max(0,i-1);
      else if(event.key==='Home')next=0;
      else if(event.key==='End')next=picks.length-1;
      if(next>=0){event.preventDefault();picks[next].focus()}
    });

    /* ---------------------------------------------------------- couture */

    /* La porte que `refreshStatus` appelle chaque seconde avec le bloc
       `boards` de `/api/status`. Un changement de Board actif ou de Session
       venu d'ailleurs (voix, MCP, autre onglet) relit la liste si le panneau
       est ouvert. */
    function gate(next){
      const before=block?`${activeIdOf(block,null)}|${text(block.jarvis_session_id)}`:'';
      block=isObject(next)?next:null;
      const after=block?`${activeIdOf(block,null)}|${text(block.jarvis_session_id)}`:'';
      paint(false);
      if(opened&&!pending&&block&&after!==before&&before)load();
      return triggerViewOf(block,pending,waitSeconds());
    }

    function statusLost(){
      block=null;
      paint(false);
      return triggerViewOf(block,pending,waitSeconds());
    }

    paint(true);

    return {
      element:host,panel,trigger,
      gate,statusLost,open,close,load,
      switchTo,createBoard,startEdit,saveEdit,cancelEdit,archiveBoard,startNewSession,
      isOpen:()=>opened,
      pending:()=>pending,
      failure:()=>failure,
      rows:()=>rowsOf(listing,block,pending),
      presentation:()=>triggerViewOf(block,pending,waitSeconds()),
      waits:()=>waits.size,
      block:()=>block,
    };
  }

  /* Parcours d'un sous-arbre, sans `querySelector` : le double de DOM des
     tests n'en a pas, et le module n'en a pas besoin. */
  function walk(node,seen){
    const out=seen||[];
    out.push(node);
    for(const child of (node.children||[]))walk(child,out);
    return out;
  }

  /* Nom distinct de `api` : la page sert tous ses modules dans un seul
     `<script>`, où `api` est déjà sa porte réseau. */
  const BOARDS_API=Object.freeze({
    DOM,TITLE_MAX,DEADLINE_MS,PATH,REFUSAL,WAITING,ARCHIVE_ACTIVE_REASON,NEW_SESSION_HINT,STYLE,
    validateTitle,refusalOf,activeIdOf,workingIdsOf,triggerViewOf,rowsOf,sessionLineOf,
    alertBoardOf,elsewhereOf,pillLabelOf,goToBoardFromAlert,
    installStyle,createBoardsControl});
  root.JarvisBoards=BOARDS_API;
  if(typeof module!=='undefined'&&module.exports)module.exports=BOARDS_API;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  function installJarvisBoards(){
    const host=document.getElementById(DOM.hostId),panel=document.getElementById(DOM.panelId);
    if(!host||!panel)
      throw Object.assign(
        new Error(`JarvisBoards : l’emplacement #${!host?DOM.hostId:DOM.panelId} manque dans control_center.html`),
        {code:'boards_host_missing'});
    /* Le panneau s'ancre sous le bouton, où qu'il soit (haut-droit par
       défaut, haut-gauche dans le thème Cosmos), sans sortir de l'écran. */
    const place=(pane,button)=>{
      const r=button.getBoundingClientRect(),gutter=12;
      const width=Math.min(372,window.innerWidth-gutter*2);
      const left=Math.max(gutter,Math.min(r.right-width,window.innerWidth-width-gutter));
      pane.style.left=`${Math.round(left)}px`;
      pane.style.top=`${Math.round(r.bottom+8)}px`;
      pane.style.maxHeight=`${Math.max(180,Math.round(window.innerHeight-r.bottom-26))}px`;
    };
    const control=createBoardsControl({
      document,host,panel,
      now:()=>Date.now(),
      setInterval:(fn,ms)=>window.setInterval(fn,ms),
      clearInterval:id=>window.clearInterval(id),
      setTimeout:(fn,ms)=>window.setTimeout(fn,ms),
      clearTimeout:id=>window.clearTimeout(id),
      request:typeof api==='function'?(path,init)=>api(path,init):undefined,
      refresh:typeof refreshStatus==='function'?()=>refreshStatus():undefined,
      toast:typeof toast==='function'?spec=>toast(spec):undefined,
      confirm:typeof confirmDialog==='function'?spec=>confirmDialog(spec):undefined,
      place,
      log:(level,event,data)=>{
        const line=`[boards] ${event} ${JSON.stringify(data||{})}`;
        if(level==='error')console.error(line);
        else if(level==='warn')console.warn(line);
        else console.info(line);
      },
    });
    /* Clic hors du contrôle : il se ferme. La boîte de confirmation de la
       page (archivage, nouvelle session) n'est pas « dehors ». */
    document.addEventListener('mousedown',event=>{
      if(!control.isOpen())return;
      const t=event.target,confirmBack=document.getElementById('confirmBack');
      if(host.contains(t)||panel.contains(t)||(confirmBack&&confirmBack.contains(t)))return;
      control.close();
    },true);
    window.addEventListener('resize',()=>{if(control.isOpen())place(panel,control.trigger)});
    /* Échap ferme aussi quand le focus a quitté le panneau (ligne retirée,
       clic sur un fond inerte). La confirmation de la page garde le sien. */
    document.addEventListener('keydown',event=>{
      if(event.key!=='Escape'||!control.isOpen()||event.defaultPrevented)return;
      const confirmBack=document.getElementById('confirmBack');
      if(panel.contains(event.target)||(confirmBack&&!confirmBack.hidden))return;
      control.close({focus:true});
    });
    window.JarvisBoardsControl=Object.freeze({
      gate:control.gate,statusLost:control.statusLost,
      open:control.open,close:control.close,isOpen:control.isOpen,
      presentation:control.presentation,failure:control.failure,pending:control.pending,rows:control.rows,
      /* Slice 07 : la bascule normale, pour « Aller au Board » des alertes. */
      switchTo:control.switchTo,
      activeId:()=>activeIdOf(control.block(),null),
    });
    console.info('[boards] boards.hud_installed '+JSON.stringify({host:DOM.hostId,panel:DOM.panelId}));
  }

  try{installJarvisBoards()}
  catch(error){
    console.error('[boards] boards.install_failed '
      +JSON.stringify({code:(error&&error.code)||null,error:String((error&&error.message)||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
