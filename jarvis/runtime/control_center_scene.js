/* Client pur de la scène constellation (handoff jarvis-constellation-scene-runtime,
   Slice 03). Décision 20 : un instantané complet, puis des patchs de révision
   appliqués strictement dans l'ordre ; tout doute se règle en relisant
   l'instantané.

   Aucune dépendance au DOM, au réseau ni à l'horloge : chaque fonction ne lit
   que ses arguments et rend un nouvel état, sans modifier l'ancien (un patch
   refusé à mi-chemin ne laisse rien de moitié appliqué). Le rendu et la boucle
   de long-poll viennent en Slice 05.

   Même sémantique que `apply_scene_patch` (`jarvis/domain/scene.py`) :
   - put_object      remplace l'objet à sa place, ou l'ajoute à la fin ;
                     refusé sur un identifiant archivé ;
   - archive_object  retire l'objet actif et ajoute sa pierre tombale à la fin ;
                     refusé sur un objet inconnu ;
   - put_relation    remplace à sa place, ou ajoute à la fin ;
   - delete_relation refusé sur une relation inconnue ;
   - au-delà de 4 096 pierres tombales, les plus anciennes tombent.
   Le parcours de test (`tests/unit/test_scene_transport_client.py`) compare
   l'état final à l'instantané calculé par le réducteur Python.

   Inséré tel quel dans la page par `ControlCenter.index` ; n'expose que
   `window.JarvisSceneClient`. */
(function(root){
  'use strict';
  const SCHEMA_VERSION=1;
  const MAX_ARCHIVED_IDS=4096;

  const isText=v=>typeof v==='string'&&v.length>0;
  const isRevision=v=>Number.isSafeInteger(v)&&v>=0;
  const fail=reason=>({ok:false,reason});

  /* État tenu à partir d'une réponse de `GET /api/scene` réussie.
     `objects`/`relations` : Map par identifiant, dans l'ordre de Core ;
     `archived_ids` : Set dans l'ordre d'archivage. */
  function fromSnapshot(response){
    if(!response||response.error||!response.snapshot)return fail('no_snapshot');
    const snap=response.snapshot;
    if(snap.schema_version!==SCHEMA_VERSION)return fail('schema_version');
    if(!isText(response.scene_id)||!isText(response.epoch)||!isRevision(response.revision))return fail('invalid_snapshot');
    if(snap.scene_id!==response.scene_id||snap.revision!==response.revision)return fail('invalid_snapshot');
    if(!Array.isArray(snap.objects)||!Array.isArray(snap.relations)||!Array.isArray(snap.archived_ids))return fail('invalid_snapshot');
    const objects=new Map(),relations=new Map();
    for(const item of snap.objects){if(!item||!isText(item.object_id))return fail('invalid_snapshot');objects.set(item.object_id,item)}
    for(const item of snap.relations){if(!item||!isText(item.relation_id))return fail('invalid_snapshot');relations.set(item.relation_id,item)}
    return {ok:true,state:{scene_id:response.scene_id,epoch:response.epoch,revision:response.revision,
      objects,relations,archived_ids:new Set(snap.archived_ids)}};
  }

  /* Une réponse d'instantané peut-elle remplacer l'état tenu ? Autre scène ou
     autre époque (Core redémarré, sauvegarde restaurée) : oui, quelle que soit
     la révision. Même scène et même époque : jamais de retour en arrière. */
  function acceptSnapshot(held,response){
    if(!response||response.error||!isText(response.scene_id)||!isText(response.epoch)||!isRevision(response.revision))return false;
    if(!held||held.scene_id!==response.scene_id||held.epoch!==response.epoch)return true;
    return response.revision>=held.revision;
  }

  /* Appliquer un patch à l'état de la révision précédente. Rend
     {ok:true,state} (nouvel état) ou {ok:false,reason} (état inchangé). */
  function applyPatch(state,patch){
    if(!state)return fail('no_state');
    if(!patch||patch.schema_version!==SCHEMA_VERSION||!isRevision(patch.revision)||!Array.isArray(patch.ops))return fail('invalid_patch');
    if(patch.revision!==state.revision+1)return fail('gap');
    const objects=new Map(state.objects),relations=new Map(state.relations),archived=new Set(state.archived_ids);
    for(const op of patch.ops){
      const kind=op&&op.op;
      if(kind==='put_object'||kind==='archive_object'){
        const id=op.object&&op.object.object_id;
        if(!isText(id))return fail('invalid_patch');
        if(kind==='archive_object'){
          if(!objects.delete(id))return fail('archive_unknown_object');
          archived.add(id);
        }else{
          if(archived.has(id))return fail('rewrite_archived_object');
          objects.set(id,op.object);
        }
      }else if(kind==='put_relation'){
        const id=op.relation&&op.relation.relation_id;
        if(!isText(id))return fail('invalid_patch');
        relations.set(id,op.relation);
      }else if(kind==='delete_relation'){
        if(!isText(op.relation_id))return fail('invalid_patch');
        if(!relations.delete(op.relation_id))return fail('delete_unknown_relation');
      }else{
        return fail('invalid_patch');
      }
    }
    let archived_ids=archived;
    if(archived.size>MAX_ARCHIVED_IDS)archived_ids=new Set([...archived].slice(-MAX_ARCHIVED_IDS));
    return {ok:true,state:{scene_id:state.scene_id,epoch:state.epoch,revision:patch.revision,objects,relations,archived_ids}};
  }

  /* Appliquer une réponse de `GET /api/scene/patches`. Rend {state,action,reason} :
     - 'unavailable' : Core ou la scène ne répond pas (`error`) ; état gardé,
       réessayer plus tard ;
     - 'resync'      : relire `/api/scene` (pas d'état, autre scène, autre
       époque, `resync_required`, saut, patch refusé) ; `state` est le dernier
       état cohérent atteint ;
     - 'more'        : patchs appliqués, la réponse était bornée : redemander
       aussitôt ;
     - 'applied' / 'unchanged' : à jour, reprendre le long-poll.
     Un patch déjà appliqué (révision ≤ état tenu, réponse en retard) est ignoré. */
  function applyPatchResponse(state,response){
    if(!response)return {state,action:'unavailable',reason:'no_response'};
    if(response.error)return {state,action:'unavailable',reason:String(response.error.code||'error')};
    if(!state)return {state,action:'resync',reason:'no_state'};
    if(response.scene_id!==state.scene_id)return {state,action:'resync',reason:'scene_changed'};
    if(response.epoch!==state.epoch)return {state,action:'resync',reason:'epoch_changed'};
    if(response.resync_required===true)return {state,action:'resync',reason:'resync_required'};
    if(!Array.isArray(response.patches)||!isRevision(response.revision))return {state,action:'resync',reason:'invalid_response'};
    let next=state,applied=0;
    for(const patch of response.patches){
      if(patch&&isRevision(patch.revision)&&patch.revision<=next.revision)continue;
      const result=applyPatch(next,patch);
      if(!result.ok)return {state:next,action:'resync',reason:result.reason};
      next=result.state;applied++;
    }
    if(response.revision>next.revision)return {state:next,action:'resync',reason:'gap'};
    if(response.more===true)return {state:next,action:'more',reason:''};
    return {state:next,action:applied?'applied':'unchanged',reason:''};
  }

  /* Paramètres du prochain long-poll pour l'état tenu. */
  function patchQuery(state,waitS){
    if(!state)return null;
    return {scene_id:state.scene_id,epoch:state.epoch,after:state.revision,wait_s:Math.max(0,Number(waitS)||0)};
  }

  /* Forme de l'instantané Core (`SceneSnapshot.to_payload()`) de l'état tenu :
     comparaison et diagnostic. */
  function toSnapshot(state){
    return {schema_version:SCHEMA_VERSION,scene_id:state.scene_id,revision:state.revision,
      objects:[...state.objects.values()],relations:[...state.relations.values()],archived_ids:[...state.archived_ids]};
  }

  const api=Object.freeze({SCHEMA_VERSION,MAX_ARCHIVED_IDS,fromSnapshot,acceptSnapshot,applyPatch,applyPatchResponse,patchQuery,toSnapshot});
  root.JarvisSceneClient=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
