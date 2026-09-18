/* Scène constellation : logique pure des interactions de l'utilisateur (handoff
   jarvis-constellation-scene-runtime, Slice 08).

   - Géométrie : glisser, redimensionner, flèches du clavier, changement de
     représentation ; toujours bornée à la zone de composition sûre
     (`SAFE_AREA`, x -152..138, y -72..68 : aucune commande de la page ne la
     recouvre), en unités entières.
   - Menu : entrées selon la nature, l'origine et l'état de l'objet. « Arrêter »
     seulement pour une étoile `job` (`work_ref.source = job`) ; jamais pour un
     sous-agent du brain, qui n'a pas d'arrêt individuel (entrée désactivée
     qui le dit).
   - Archivage groupé : même règle que `bulk_archivable`
     (`jarvis/domain/scene.py`, test de parité) ; Core la revalide.
   - Affichage optimiste : une modification envoyée se dessine tout de suite,
     puis disparaît quand l'état tenu atteint la révision rendue par Core, ou
     s'annule sur refus, échec ou délai.
   - Commandes `POST /api/scene/commands` (acteur `user` posé par le Control
     Center) et lecture de leurs réponses.

   Aucune dépendance au DOM, au réseau ni à l'horloge : les tests l'exécutent
   avec node (`tests/unit/test_scene_interaction_logic.py`). Inséré tel quel
   dans la page par `ControlCenter.index` ; n'expose que
   `window.JarvisSceneInteract`. */
(function(root){
  'use strict';

  const FRAME=Object.freeze({halfWidth:160,halfHeight:90});
  /* Zone de composition sûre (Slice 05) : même valeur que `SCENE_SAFE_AREA`
     du domaine et `SAFE_AREA` du rendu (tests de parité). Décision PM (reprise
     QA) : toute géométrie de l'utilisateur y reste. */
  const SAFE_AREA=Object.freeze({x0:-152,x1:138,y0:-72,y1:68});
  /* Pas du clavier, en unités de scène : Maj+flèche (2), Ctrl+Maj+flèche (10),
     Ctrl+flèche redimensionne de 2. */
  const KEY_STEP=2,KEY_STEP_LARGE=10;
  /* Tailles minimales et par défaut, en unités (défauts = `DEFAULT_SIZE` du
     rendu : une forme changée prend la taille que le résolveur lui donnerait). */
  const MIN_SIZE=Object.freeze({capsule:Object.freeze({w:16,h:5}),window:Object.freeze({w:40,h:24})});
  /* Taille maximale d'une capsule (même valeur que `CAPSULE_MAX` du rendu) :
     au-delà, le rendu la dessine à sa hauteur naturelle, centrée. */
  const MAX_SIZE=Object.freeze({capsule:Object.freeze({w:160,h:10})});
  const DEFAULT_SIZE=Object.freeze({point:Object.freeze({w:6,h:6}),signal:Object.freeze({w:4,h:4}),
    capsule:Object.freeze({w:40,h:7}),window:Object.freeze({w:64,h:40})});
  /* Seuil (px) au-delà duquel un appui devient un glissement : 4 px à la
     souris, 10 px pour un pointeur grossier (tactile, stylet) ou la main de
     Barehands, pour qu'un appui long qui tremble n'épingle rien ; appui long
     (ms) qui ouvre le menu. */
  const DRAG_THRESHOLD_PX=4,COARSE_DRAG_THRESHOLD_PX=10,LONG_PRESS_MS=550;
  /* Un affichage optimiste jamais confirmé par l'état tenu s'efface au plus
     tard après ce délai (lecture en panne, patch perdu). */
  const PENDING_MAX_MS=30000;
  /* Archivage groupé : au plus 512 identifiants par commande (borne du
     domaine) et un corps sous 64 Kio (borne du transport). */
  const MAX_ARCHIVE_IDS=512,MAX_COMMAND_BYTES=48000;
  const EXECUTION_KINDS=new Set(['agent','job']);
  const TERMINAL=Object.freeze(['completed','failed','cancelled','interrupted']);
  const ACTIVE_WORK=new Set(['running','pending','blocked']);

  const clamp=(v,lo,hi)=>Math.min(hi,Math.max(lo,v));

  /* ----------------------------------------------------------- géométrie */

  /* Boîte bornée à la zone sûre, en unités entières : taille ≥ minimum et ≤
     maximum de la forme (et ≤ zone), coin haut gauche gardé pour que la boîte
     entière tienne dans la zone. Des entiers : ce que le cerveau relit
     (`scene_inspect`) reste lisible, et un geste d'un pixel ne fabrique pas
     une nouvelle révision. */
  function clampBox(box,representation){
    const min=MIN_SIZE[representation]||{w:1,h:1};
    const areaW=SAFE_AREA.x1-SAFE_AREA.x0,areaH=SAFE_AREA.y1-SAFE_AREA.y0;
    const max=MAX_SIZE[representation]||{w:areaW,h:areaH};
    const w=Math.round(clamp(Number(box.w)||min.w,min.w,Math.min(max.w,areaW)));
    const h=Math.round(clamp(Number(box.h)||min.h,min.h,Math.min(max.h,areaH)));
    const x=Math.round(clamp(Number(box.x)||0,SAFE_AREA.x0,SAFE_AREA.x1-w));
    const y=Math.round(clamp(Number(box.y)||0,SAFE_AREA.y0,SAFE_AREA.y1-h));
    return {x,y,w,h};
  }

  /* Seuil de glissement pour un pointeur. */
  function dragThreshold(pointerType,barehands){
    return pointerType==='mouse'&&!barehands?DRAG_THRESHOLD_PX:COARSE_DRAG_THRESHOLD_PX;
  }

  /* Écart en pixels → écart en unités pour la fenêtre `vp` (`JarvisSceneLayout.viewport`). */
  function pxToUnits(vp,dx,dy){
    const s=vp&&vp.scale>0?vp.scale:1;
    return {dx:dx/s,dy:dy/s};
  }

  function dragBox(start,dx,dy,representation){
    return clampBox({x:start.x+dx,y:start.y+dy,w:start.w,h:start.h},representation);
  }

  /* Redimensionner par le coin bas droit : le coin haut gauche ne bouge pas
     (sauf s'il était hors de la zone sûre), la taille ne dépasse ni le minimum,
     ni le maximum de la forme, ni le bord de la zone. */
  function resizeBox(start,dw,dh,representation){
    const min=MIN_SIZE[representation]||{w:1,h:1};
    const x=clamp(start.x,SAFE_AREA.x0,SAFE_AREA.x1-min.w),y=clamp(start.y,SAFE_AREA.y0,SAFE_AREA.y1-min.h);
    const w=clamp(start.w+dw,min.w,SAFE_AREA.x1-x);
    const h=clamp(start.h+dh,min.h,SAFE_AREA.y1-y);
    return clampBox({x,y,w,h},representation);
  }

  const resizable=representation=>representation==='capsule'||representation==='window';

  /* Touche → intention. `{type:'move'|'resize', dx, dy}`, `{type:'menu'}`,
     `{type:'nav'}` (flèches seules, Début, Fin) ou null. */
  function keyIntent(event){
    const key=event&&event.key;
    if(key==='ContextMenu'||(key==='F10'&&event.shiftKey&&!event.ctrlKey&&!event.altKey))return {type:'menu'};
    const dirs={ArrowRight:[1,0],ArrowLeft:[-1,0],ArrowDown:[0,1],ArrowUp:[0,-1]};
    if(key==='Home'||key==='End')return event.shiftKey||event.ctrlKey||event.altKey||event.metaKey?null:{type:'nav'};
    const dir=dirs[key];
    if(!dir||event.altKey||event.metaKey)return null;
    if(!event.shiftKey&&!event.ctrlKey)return {type:'nav'};
    if(event.ctrlKey&&!event.shiftKey)return {type:'resize',dx:dir[0]*KEY_STEP,dy:dir[1]*KEY_STEP};
    const step=event.ctrlKey?KEY_STEP_LARGE:KEY_STEP;
    return {type:'move',dx:dir[0]*step,dy:dir[1]*step};
  }

  /* Appliquer une intention clavier à une boîte. Un redimensionnement d'une
     forme qui ne se redimensionne pas (point) ne change rien. */
  function applyKey(box,intent,representation){
    if(!intent)return box;
    if(intent.type==='move')return dragBox(box,intent.dx,intent.dy,representation);
    if(intent.type==='resize'&&resizable(representation))return resizeBox(box,intent.dx,intent.dy,representation);
    return box;
  }

  /* Boîte d'une nouvelle représentation : taille par défaut de la forme,
     même centre, bornée. */
  function representationBox(box,representation,kind){
    const size=representation==='point'?(kind==='attention'?DEFAULT_SIZE.signal:DEFAULT_SIZE.point):DEFAULT_SIZE[representation];
    const cx=box.x+box.w/2,cy=box.y+box.h/2;
    return clampBox({x:cx-size.w/2,y:cy-size.h/2,w:size.w,h:size.h},representation);
  }

  const sameBox=(a,b)=>!!a&&!!b&&a.x===b.x&&a.y===b.y&&a.w===b.w&&a.h===b.h;

  /* -------------------------------------------------- signaux et archivage */

  const workKey=ref=>ref&&typeof ref.source==='string'&&typeof ref.external_id==='string'?`${ref.source}\n${ref.external_id}`:null;

  /* Étoile de chaque signal runtime (`attention` d'origine `runtime`), ou
     null (orphelin). Même règle que `signal_owners` : cible du lien de
     signal vivant si c'est un nœud d'exécution, sinon première étoile du même
     travail Core. */
  function signalOwners(state){
    const stars=new Map();
    for(const item of state.objects.values()){
      const key=EXECUTION_KINDS.has(item.kind)?workKey(item.work_ref):null;
      if(key&&!stars.has(key))stars.set(key,item.object_id);
    }
    const owners=new Map();
    for(const item of state.objects.values()){
      if(item.kind!=='attention'||item.origin!=='runtime')continue;
      const rel=state.relations.get(item.object_id);
      const target=rel&&rel.kind==='explains'&&rel.relation_id===rel.from_id?state.objects.get(rel.to_id):null;
      if(target&&EXECUTION_KINDS.has(target.kind))owners.set(item.object_id,target.object_id);
      else{const key=workKey(item.work_ref);owners.set(item.object_id,key&&stars.has(key)?stars.get(key):null)}
    }
    return owners;
  }

  /* Signaux runtime qu'emporte l'archivage de `objectId` (cascade). */
  function cascadeOf(state,objectId,owners){
    const map=owners||signalOwners(state);
    const out=[];
    for(const [signal,owner] of map)if(owner===objectId)out.push(signal);
    return out;
  }

  /* Sélection « Archiver les travaux terminés » : étoiles terminées, et
     signaux runtime orphelins. Les signaux d'une étoile sélectionnée partent
     par la cascade : comptés, pas envoyés. Jamais un travail en cours, en
     attente, bloqué ou d'état inconnu ; jamais un objet du cerveau ou de
     l'utilisateur. */
  function bulkSelection(state){
    const owners=signalOwners(state);
    const ids=[],stars=[],byState={completed:0,failed:0,cancelled:0,interrupted:0};
    for(const item of state.objects.values()){
      if(EXECUTION_KINDS.has(item.kind)&&TERMINAL.includes(item.exec_state)){
        ids.push(item.object_id);stars.push(item.object_id);byState[item.exec_state]++;
      }
    }
    const chosen=new Set(stars);
    let cascaded=0,orphans=0;
    for(const [signal,owner] of owners){
      if(owner===null){ids.push(signal);orphans++}
      else if(chosen.has(owner))cascaded++;
    }
    return {ids,stars:stars.length,byState,cascaded,orphans,objects:stars.length+cascaded+orphans};
  }

  /* Découper une sélection en commandes `archive_many` dans les bornes du
     domaine et du transport. Une seule commande dans le cas courant. */
  function chunkIds(ids,maxIds=MAX_ARCHIVE_IDS,maxBytes=MAX_COMMAND_BYTES){
    const chunks=[];let current=[],bytes=0;
    const size=id=>utf8Length(JSON.stringify(id))+1;
    for(const id of ids){
      const cost=size(id);
      if(current.length&&(current.length>=maxIds||bytes+cost>maxBytes)){chunks.push(current);current=[];bytes=0}
      current.push(id);bytes+=cost;
    }
    if(current.length)chunks.push(current);
    return chunks;
  }

  function utf8Length(text){
    let n=0;
    for(const ch of text){const c=ch.codePointAt(0);n+=c<0x80?1:c<0x800?2:c<0x10000?3:4}
    return n;
  }

  /* ------------------------------------------------------------------ menu */

  const REPRESENTATION_LABELS=Object.freeze({point:'Afficher en point',capsule:'Afficher en capsule',window:'Afficher en fenêtre'});

  /* Entrées du menu d'un objet (`state` : état dessiné, affichage optimiste
     compris). Rend `{title, items}` ; `items` : `'-'` ou
     `{act, label, danger?, disabled?, note?}`. Actions : `rep:<forme>`, `pin`,
     `unpin`, `hide`, `stop`, `archive`, `archive-finished`, `archive-orphans`. */
  function menuModel(state,objectId,ctx){
    const item=state.objects.get(objectId);
    if(!item)return null;
    const context=ctx||{};
    const execution=EXECUTION_KINDS.has(item.kind);
    const runtimeSignal=item.kind==='attention'&&item.origin==='runtime';
    const title=String(context.title||item.payload&&item.payload.title||objectId);
    const items=[];
    for(const representation of ['point','capsule','window'])
      if(representation!==item.representation)items.push({act:`rep:${representation}`,label:REPRESENTATION_LABELS[representation]});
    items.push('-');
    if(item.constraints&&item.constraints.pinned_by_user)items.push({act:'unpin',label:'Désépingler'});
    else items.push({act:'pin',label:'Épingler ici'});
    items.push({act:'hide',label:'Masquer'});
    items.push('-');
    /* Slice 10 : état inconnu depuis le redémarrage de Core. Aucun arrêt
       (rien ne tourne dans ce Core qui puisse être visé) : une note le dit. */
    if(execution&&item.exec_state==='unknown')
      items.push({act:'state-unknown',label:'État inconnu depuis le redémarrage de Core',note:true});
    if(execution&&ACTIVE_WORK.has(item.exec_state)){
      if(item.kind==='job'&&item.work_ref&&item.work_ref.source==='job')items.push({act:'stop',label:'Arrêter la tâche…',danger:true});
      /* Note annoncée (focalisable, `aria-disabled`), pas un bouton désactivé
         que le clavier et le lecteur d'écran sautent. */
      else items.push({act:'stop-unavailable',label:'Arrêt impossible : sous-agent du brain',note:true});
    }
    const signals=execution?cascadeOf(state,objectId).length:0;
    items.push({act:'archive',label:signals?(signals>1?'Archiver avec ses signaux…':'Archiver avec son signal…'):'Archiver…',danger:true});
    const finished=Number(context.finished)||0;
    if((execution||runtimeSignal)&&finished>0)
      items.push({act:'archive-finished',label:`Archiver les travaux terminés (${finished} ${finished>1?'objets':'objet'})…`,danger:true});
    /* Slice 07 (reprise QA) : artefacts qui n'expliquent plus rien, depuis le menu d'un artefact ou d'une étoile. */
    const orphans=Number(context.orphans)||0;
    if((item.kind==='artifact'||execution)&&orphans>0)
      items.push({act:'archive-orphans',label:`Archiver les artefacts orphelins (${orphans})…`,danger:true});
    return {title,items};
  }

  /* ------------------------------------------------------------ commandes */

  const commands=Object.freeze({
    setGeometry:(id,box)=>({schema_version:1,op:'set_geometry',object_id:id,geometry:{x:box.x,y:box.y,w:box.w,h:box.h}}),
    pin:id=>({schema_version:1,op:'pin',object_id:id}),
    unpin:id=>({schema_version:1,op:'unpin',object_id:id}),
    setRepresentation:(id,representation,box)=>({schema_version:1,op:'set_representation',object_id:id,representation,
      ...(box?{geometry:{x:box.x,y:box.y,w:box.w,h:box.h}}:{})}),
    setVisibility:(id,visibility)=>({schema_version:1,op:'set_visibility',object_id:id,visibility}),
    archive:id=>({schema_version:1,op:'archive',object_id:id}),
    archiveMany:ids=>({schema_version:1,op:'archive_many',object_ids:[...ids]}),
  });

  /* Refus du domaine dans les mots de l'utilisateur. */
  const REFUSALS=Object.freeze({
    unknown_object:"l'objet n'est plus dans la scène",
    object_archived:"l'objet est déjà archivé",
    pinned_by_user:"l'objet est épinglé",
    unplaced:"l'objet n'a pas encore de place",
    scene_full:'la scène est pleine',
    not_bulk_archivable:'la scène a changé : un objet choisi n’est plus un travail terminé',
    op_not_allowed:'action non permise',
    revision_exhausted:'la scène ne peut plus changer',
  });

  /* Échecs de transport dans les mots de l'utilisateur, comme le classement
     de Slice 03 (`classify_scene_call_failure`) : `unknown` vrai quand la
     demande a pu partir (issue inconnue, l'état relu dira ce qui s'est
     passé), faux quand rien n'a été appliqué. Le texte brut (anglais,
     adresses) ne va qu'à la console. */
  const TRANSPORT=Object.freeze({
    command_not_sent:['Core ne répond pas : rien n’a été envoyé, réessayer est sûr.',false],
    core_timeout:['Core n’a pas répondu à temps : issue inconnue, la scène se relit.',true],
    scene_unavailable:['Scène indisponible dans Core : rien n’a été appliqué.',false],
    scene_persist_failed:['Core n’a pas pu enregistrer : rien n’a été appliqué.',false],
    invalid_scene_response:['Réponse de Core illisible : issue inconnue, la scène se relit.',true],
    core_refused:['Core a refusé la demande.',false],
    invalid_request:['Demande refusée : forme invalide.',false],
    payload_too_large:['Demande trop grosse : rien n’a été envoyé.',false],
    scene_actor_forbidden:['Demande refusée : acteur non permis.',false],
    not_configured:['Scène non reliée à Core dans ce Control Center.',false],
    not_found:['Core ne connaît pas ce job (déjà oublié, ou Core redémarré).',false],
    not_cancellable:['Ce travail n’a pas d’arrêt individuel.',false],
    timeout:['Pas de réponse du Control Center : issue inconnue, la scène se relit.',true],
    network_error:['Control Center injoignable : issue inconnue, la scène se relit.',true],
  });

  function transportFailure(status,body){
    const payload=body&&typeof body==='object'?body:{};
    const error=payload.error&&typeof payload.error==='object'?payload.error:{};
    const code=typeof error.code==='string'?error.code:(status?`http_${status}`:'network_error');
    const detail=typeof error.message==='string'?error.message:'';
    let words=TRANSPORT[code];
    if(code==='core_unreachable')
      words=/non envoy/i.test(detail)?['Core injoignable : rien n’a été envoyé.',false]:['Liaison à Core perdue : issue inconnue, la scène se relit.',true];
    if(!words)words=[status?`Erreur ${status} du Control Center.`:'Control Center injoignable : issue inconnue, la scène se relit.',status===0||status>=500];
    return {code,message:words[0],unknown:words[1],detail};
  }

  /* Échec d'un `fetch` (aucune réponse HTTP) : délai de la page, ou réseau. La
     page ne sait pas si la demande est partie : issue inconnue. */
  function networkFailure(error){
    return transportFailure(0,{error:{code:error&&error.code==='timeout'?'timeout':'network_error',message:String(error&&error.message||'')}});
  }

  /* Réponse de `POST /api/scene/commands` → `{ok, outcome, reason, code,
     message, revision, unknown, detail}`. `ok` : appliquée ou sans effet. */
  function classifyResponse(status,body){
    const payload=body&&typeof body==='object'?body:{};
    if(status===200&&typeof payload.outcome==='string'){
      const ok=payload.outcome==='applied'||payload.outcome==='duplicate';
      const reason=typeof payload.reason==='string'?payload.reason:'';
      return {ok,outcome:payload.outcome,reason,code:'',revision:Number.isSafeInteger(payload.revision)?payload.revision:null,unknown:false,
        message:ok?'':`refusé : ${REFUSALS[reason]||reason||payload.outcome}`,detail:''};
    }
    const failure=transportFailure(status,payload);
    return {ok:false,outcome:'failed',reason:'',revision:null,...failure};
  }

  /* Issue d'un arrêt de job (`POST /api/jobs/cancel`) : titre, précision,
     ton, et si l'étoile doit encore attendre sa fin (`terminal` faux). */
  function stopOutcome(outcome,status){
    /* Le worker avait déjà rendu son issue : elle gagne, dite telle quelle. */
    if(outcome==='already_terminal'){
      const words={completed:'Elle a fini normalement.',failed:'Elle a fini en échec.',cancelled:'Elle était déjà annulée.',interrupted:'Elle avait été interrompue.'};
      return {title:'La tâche s’était déjà terminée',sub:words[status]||'Rien à arrêter.',kind:'info',terminal:true};
    }
    return ({
      cancelled:{title:'Tâche arrêtée',sub:'Le job est annulé.',kind:'ok',terminal:true},
      already_terminal:{title:'Tâche déjà terminée',sub:'Rien à arrêter.',kind:'info',terminal:true},
      cancel_requested:{title:'Arrêt demandé',sub:'Core n’a pas encore confirmé la fin du job.',kind:'info',terminal:false},
      cleanup_unknown:{title:'Arrêt demandé, nettoyage non confirmé',sub:'Le job reste en cours tant que son exécution n’est pas nettoyée.',kind:'warn',terminal:false},
    })[outcome]||{title:'Arrêt : issue inattendue',sub:String(outcome||''),kind:'warn',terminal:false};
  }

  /* Objet à sélectionner quand `removed` quitte le dessin : le suivant dans
     l'ordre de lecture (`orderedIds`, ordre spatial), sinon le précédent. */
  function focusAfterRemoval(orderedIds,removed,currentId){
    const gone=new Set(removed);
    const index=orderedIds.indexOf(currentId);
    const start=index<0?0:index;
    for(let i=start+1;i<orderedIds.length;i++)if(!gone.has(orderedIds[i]))return orderedIds[i];
    for(let i=Math.min(start,orderedIds.length)-1;i>=0;i--)if(!gone.has(orderedIds[i]))return orderedIds[i];
    if(index<0)for(const id of orderedIds)if(!gone.has(id))return id;
    return null;
  }

  /* ---------------------------------------------------- affichage optimiste */

  /* Modifications envoyées, dessinées avant que Core ne les confirme. Une
     **couche** par opération (`geometry`, `representation`, `visibility`,
     `pinned`, `archived`), dans l'ordre d'envoi : `begin` ajoute une couche et
     rend son jeton ; `confirm` note la révision rendue pour cette couche ;
     `drop` retire un champ d'une couche ; `rollback` retire **cette couche
     seulement** (une opération plus récente refusée ne défait jamais une plus
     ancienne acceptée mais pas encore reçue) ; `prune(state, now)` retire les
     couches que l'état tenu montre déjà (révision atteinte) ou qui ont trop
     attendu ; `overlay(state)` applique les couches dans l'ordre. `version`
     change à chaque modification (mémoïsation). */
  function createPending(maxAgeMs=PENDING_MAX_MS){
    const layers=new Map();let seq=0,version=0;
    const find=(id,token)=>{const list=layers.get(id);return list?list.find(layer=>layer.token===token)||null:null};
    const remove=(id,layer)=>{
      const list=layers.get(id);
      const at=list?list.indexOf(layer):-1;
      if(at<0)return false;
      list.splice(at,1);if(!list.length)layers.delete(id);version++;
      return true;
    };
    return {
      begin(id,fields,now){
        const layer={fields:{...fields},token:++seq,revision:null,at:now};
        if(!layers.has(id))layers.set(id,[]);
        layers.get(id).push(layer);version++;
        return layer.token;
      },
      confirm(id,token,revision){
        const layer=find(id,token);
        if(!layer)return false;
        if(Number.isSafeInteger(revision))layer.revision=Math.max(layer.revision||0,revision);
        return true;
      },
      drop(id,token,field){
        const layer=find(id,token);
        if(!layer||!(field in layer.fields))return false;
        delete layer.fields[field];version++;
        if(!Object.keys(layer.fields).length)remove(id,layer);
        return true;
      },
      rollback(id,token){
        if(token===undefined){if(!layers.delete(id))return false;version++;return true}
        const layer=find(id,token);
        return layer?remove(id,layer):false;
      },
      prune(state,now){
        const removed=[];
        for(const [id,list] of [...layers]){
          for(const layer of [...list]){
            const reached=layer.revision!==null&&!!state&&state.revision>=layer.revision;
            const expired=now-layer.at>maxAgeMs;
            if(reached||expired){remove(id,layer);removed.push({id,token:layer.token,reason:reached?'reached':'expired'})}
          }
        }
        return removed;
      },
      overlay(state){
        if(!state||!layers.size)return state;
        let objects=null;
        for(const [id,list] of layers){
          const item=state.objects.get(id);
          if(!item)continue;
          if(!objects)objects=new Map(state.objects);
          const fields=Object.assign({},...list.map(layer=>layer.fields));
          if(fields.archived){objects.delete(id);continue}
          const next={...item};
          if(fields.geometry)next.geometry={...fields.geometry};
          if(fields.representation)next.representation=fields.representation;
          if(fields.visibility)next.visibility=fields.visibility;
          if(typeof fields.pinned==='boolean')next.constraints={...item.constraints,pinned_by_user:fields.pinned};
          objects.set(id,next);
        }
        return objects?{...state,objects}:state;
      },
      has:id=>layers.has(id),
      size:()=>layers.size,
      version:()=>version,
    };
  }

  /* Étapes d'une géométrie de l'utilisateur (toute géométrie épingle) :
     l'épingle d'abord, puis la position ; un objet sans géométrie ne
     s'épingle pas : position, épingle, position de nouveau. */
  function geometrySteps(wasPinned,placed){
    if(wasPinned)return ['geometry'];
    return placed?['pin','geometry']:['geometry','pin','geometry'];
  }

  /* Envoyer les étapes d'une géométrie de l'utilisateur sur la couche
     optimiste `token`. La couche n'est confirmée qu'après la **dernière**
     étape, à la plus grande révision rendue : confirmer après une étape
     intermédiaire laisserait l'élagage retirer l'aperçu avant que la position
     n'arrive (retour visuel à l'origine). Échec : désépinglage compensatoire
     si l'épingle venait de cette opération, puis retrait de la couche.
     `send(command)` rend la réponse classée (`classifyResponse`). */
  async function commitGeometry({id,box,wasPinned,placed,send,pending,token}){
    const steps=geometrySteps(wasPinned,placed);
    let pinnedNow=false,revision=null;
    for(const step of steps){
      const result=await send(step==='pin'?commands.pin(id):commands.setGeometry(id,box));
      if(!result.ok){
        const undo=pinnedNow&&!wasPinned?await send(commands.unpin(id)):null;
        const rolledBack=pending.rollback(id,token);
        return {ok:false,step,result,undo,rolledBack,steps,pinned:pinnedNow};
      }
      if(step==='pin')pinnedNow=true;
      if(Number.isSafeInteger(result.revision))revision=Math.max(revision||0,result.revision);
    }
    pending.confirm(id,token,revision);
    return {ok:true,steps,revision,pinned:pinnedNow};
  }

  /* Disposition sur laquelle le résolveur valide ses placements : celle de
     l'état tenu (`held`), jamais celle de l'état dessiné avec les
     modifications optimistes (`drawn`), qui peuvent encore être refusées.
     Sans modification en attente (`drawn === held`), la disposition dessinée
     sert telle quelle. `resolve` : `JarvisSceneLayout.resolveLayout`. */
  function commitLayout(held,drawn,drawnLayout,resolve){
    if(!held)return null;
    return drawn===held&&drawnLayout?drawnLayout:resolve(held);
  }

  /* Objets masqués, dans l'ordre de Core. */
  function hiddenObjects(state){
    const out=[];
    for(const item of state.objects.values())
      if(item.visibility==='hidden')out.push({id:item.object_id,kind:item.kind,title:String(item.payload&&item.payload.title||'')});
    return out;
  }

  const api=Object.freeze({FRAME,SAFE_AREA,KEY_STEP,KEY_STEP_LARGE,MIN_SIZE,MAX_SIZE,DEFAULT_SIZE,DRAG_THRESHOLD_PX,COARSE_DRAG_THRESHOLD_PX,
    LONG_PRESS_MS,PENDING_MAX_MS,MAX_ARCHIVE_IDS,MAX_COMMAND_BYTES,TERMINAL,REFUSALS,TRANSPORT,
    clampBox,dragThreshold,pxToUnits,dragBox,resizeBox,resizable,keyIntent,applyKey,representationBox,sameBox,
    signalOwners,cascadeOf,bulkSelection,chunkIds,menuModel,commands,transportFailure,networkFailure,classifyResponse,stopOutcome,
    focusAfterRemoval,commitLayout,geometrySteps,commitGeometry,createPending,hiddenObjects});
  root.JarvisSceneInteract=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
