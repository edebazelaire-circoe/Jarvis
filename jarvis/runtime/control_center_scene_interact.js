/* Scène constellation : logique pure des interactions de l'utilisateur (handoff
   jarvis-constellation-scene-runtime, Slice 08).

   - Géométrie : glisser, redimensionner, flèches du clavier, changement de
     représentation ; toujours bornée au cadre de référence (x ±160, y ±90).
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
  /* Pas du clavier, en unités de scène : Maj+flèche (2), Ctrl+Maj+flèche (10),
     Ctrl+flèche redimensionne de 2. */
  const KEY_STEP=2,KEY_STEP_LARGE=10;
  /* Tailles minimales et par défaut, en unités (défauts = `DEFAULT_SIZE` du
     rendu : une forme changée prend la taille que le résolveur lui donnerait). */
  const MIN_SIZE=Object.freeze({capsule:Object.freeze({w:16,h:5}),window:Object.freeze({w:40,h:24})});
  const DEFAULT_SIZE=Object.freeze({point:Object.freeze({w:6,h:6}),signal:Object.freeze({w:4,h:4}),
    capsule:Object.freeze({w:40,h:7}),window:Object.freeze({w:64,h:40})});
  /* Seuil (px) au-delà duquel un appui devient un glissement ; appui long
     (ms) qui ouvre le menu (Barehands, écran tactile). */
  const DRAG_THRESHOLD_PX=4,LONG_PRESS_MS=550;
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

  /* Boîte bornée au cadre, en unités entières : taille ≥ minimum de la forme
     et ≤ cadre, coin haut gauche gardé dans le cadre. Des entiers : ce que le
     cerveau relit (`scene_inspect`) reste lisible, et un geste d'un pixel ne
     fabrique pas une nouvelle révision. */
  function clampBox(box,representation){
    const min=MIN_SIZE[representation]||{w:1,h:1};
    const w=Math.round(clamp(Number(box.w)||min.w,min.w,2*FRAME.halfWidth));
    const h=Math.round(clamp(Number(box.h)||min.h,min.h,2*FRAME.halfHeight));
    const x=Math.round(clamp(Number(box.x)||0,-FRAME.halfWidth,FRAME.halfWidth-w));
    const y=Math.round(clamp(Number(box.y)||0,-FRAME.halfHeight,FRAME.halfHeight-h));
    return {x,y,w,h};
  }

  /* Écart en pixels → écart en unités pour la fenêtre `vp` (`JarvisSceneLayout.viewport`). */
  function pxToUnits(vp,dx,dy){
    const s=vp&&vp.scale>0?vp.scale:1;
    return {dx:dx/s,dy:dy/s};
  }

  function dragBox(start,dx,dy,representation){
    return clampBox({x:start.x+dx,y:start.y+dy,w:start.w,h:start.h},representation);
  }

  /* Redimensionner par le coin bas droit : le coin haut gauche ne bouge pas,
     la taille ne dépasse ni le minimum ni le bord du cadre. */
  function resizeBox(start,dw,dh,representation){
    const min=MIN_SIZE[representation]||{w:1,h:1};
    const w=clamp(start.w+dw,min.w,FRAME.halfWidth-start.x);
    const h=clamp(start.h+dh,min.h,FRAME.halfHeight-start.y);
    return clampBox({x:start.x,y:start.y,w,h},representation);
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
     `{act, label, danger?, disabled?}`. Actions : `rep:<forme>`, `pin`,
     `unpin`, `hide`, `stop`, `archive`, `archive-finished`. */
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
    if(execution&&ACTIVE_WORK.has(item.exec_state)){
      if(item.kind==='job'&&item.work_ref&&item.work_ref.source==='job')items.push({act:'stop',label:'Arrêter la tâche…',danger:true});
      else items.push({act:'stop-unavailable',label:'Arrêt impossible : sous-agent du brain',disabled:true});
    }
    const signals=execution?cascadeOf(state,objectId).length:0;
    items.push({act:'archive',label:signals?(signals>1?'Archiver avec ses signaux…':'Archiver avec son signal…'):'Archiver…',danger:true});
    const finished=Number(context.finished)||0;
    if((execution||runtimeSignal)&&finished>0)
      items.push({act:'archive-finished',label:`Archiver les travaux terminés (${finished})…`,danger:true});
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

  /* Réponse de `POST /api/scene/commands` → `{ok, outcome, reason, code,
     message, revision, unknown}`. `ok` : appliquée ou sans effet ; `unknown` :
     issue inconnue (504), l'état relu dira ce qui s'est passé. */
  function classifyResponse(status,body){
    const payload=body&&typeof body==='object'?body:{};
    if(status===200&&typeof payload.outcome==='string'){
      const ok=payload.outcome==='applied'||payload.outcome==='duplicate';
      const reason=typeof payload.reason==='string'?payload.reason:'';
      return {ok,outcome:payload.outcome,reason,code:'',revision:Number.isSafeInteger(payload.revision)?payload.revision:null,unknown:false,
        message:ok?'':`refusé : ${REFUSALS[reason]||reason||payload.outcome}`};
    }
    const error=payload.error&&typeof payload.error==='object'?payload.error:{};
    const code=typeof error.code==='string'?error.code:(status?`http_${status}`:'network_error');
    const message=typeof error.message==='string'&&error.message?error.message:(status?`HTTP ${status}`:'Control Center injoignable');
    return {ok:false,outcome:'failed',reason:'',code,message,revision:null,unknown:status===504||code==='core_timeout'};
  }

  /* ---------------------------------------------------- affichage optimiste */

  /* Modifications envoyées, dessinées avant que Core ne les confirme.
     `begin` fusionne les champs d'un objet (`geometry`, `representation`,
     `visibility`, `pinned`, `archived`) et rend un jeton ; `confirm` note la
     révision rendue ; `rollback` retire l'entrée (si le jeton est le dernier) ;
     `prune(state, now)` efface ce que l'état tenu montre déjà (révision
     atteinte) ou ce qui a trop attendu ; `overlay(state)` rend l'état à
     dessiner. `version` change à chaque modification (mémoïsation). */
  function createPending(maxAgeMs=PENDING_MAX_MS){
    const entries=new Map();let seq=0,version=0;
    return {
      begin(id,fields,now){
        const previous=entries.get(id);
        const entry={fields:{...(previous?previous.fields:{}),...fields},token:++seq,revision:null,at:now};
        entries.set(id,entry);version++;
        return entry.token;
      },
      confirm(id,token,revision){
        const entry=entries.get(id);
        if(!entry||entry.token!==token)return false;
        if(Number.isSafeInteger(revision))entry.revision=Math.max(entry.revision||0,revision);
        return true;
      },
      /* Retirer un seul champ (épinglage refusé après un déplacement accepté). */
      drop(id,token,field){
        const entry=entries.get(id);
        if(!entry||entry.token!==token||!(field in entry.fields))return false;
        delete entry.fields[field];version++;
        return true;
      },
      rollback(id,token){
        const entry=entries.get(id);
        if(!entry||(token!==undefined&&entry.token!==token))return false;
        entries.delete(id);version++;
        return true;
      },
      prune(state,now){
        const removed=[];
        for(const [id,entry] of entries){
          const reached=entry.revision!==null&&state&&state.revision>=entry.revision;
          const expired=now-entry.at>maxAgeMs;
          if(reached||expired){entries.delete(id);removed.push({id,reason:reached?'reached':'expired'})}
        }
        if(removed.length)version++;
        return removed;
      },
      overlay(state){
        if(!state||!entries.size)return state;
        let objects=null;
        for(const [id,entry] of entries){
          const item=state.objects.get(id);
          if(!item)continue;
          if(!objects)objects=new Map(state.objects);
          if(entry.fields.archived){objects.delete(id);continue}
          const next={...item};
          if(entry.fields.geometry)next.geometry={...entry.fields.geometry};
          if(entry.fields.representation)next.representation=entry.fields.representation;
          if(entry.fields.visibility)next.visibility=entry.fields.visibility;
          if(typeof entry.fields.pinned==='boolean')next.constraints={...item.constraints,pinned_by_user:entry.fields.pinned};
          objects.set(id,next);
        }
        return objects?{...state,objects}:state;
      },
      has:id=>entries.has(id),
      size:()=>entries.size,
      version:()=>version,
      oldestAt(){let at=null;for(const entry of entries.values())if(at===null||entry.at<at)at=entry.at;return at},
    };
  }

  /* Objets masqués, dans l'ordre de Core. */
  function hiddenObjects(state){
    const out=[];
    for(const item of state.objects.values())
      if(item.visibility==='hidden')out.push({id:item.object_id,kind:item.kind,title:String(item.payload&&item.payload.title||'')});
    return out;
  }

  const api=Object.freeze({FRAME,KEY_STEP,KEY_STEP_LARGE,MIN_SIZE,DEFAULT_SIZE,DRAG_THRESHOLD_PX,LONG_PRESS_MS,PENDING_MAX_MS,
    MAX_ARCHIVE_IDS,MAX_COMMAND_BYTES,TERMINAL,REFUSALS,
    clampBox,pxToUnits,dragBox,resizeBox,resizable,keyIntent,applyKey,representationBox,sameBox,
    signalOwners,cascadeOf,bulkSelection,chunkIds,menuModel,commands,classifyResponse,createPending,hiddenObjects});
  root.JarvisSceneInteract=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
