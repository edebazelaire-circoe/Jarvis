/* Modèle du fil de Chat (handoff jarvis-unified-chat-and-board-drop, Slice 02).

   Contrat : `docs/chat.md`, section « Projection ». Mêmes règles que
   `project_chat` (`jarvis/domain/chat_projection.py`), l'implémentation de
   référence ; le fixture partagé `tests/fixtures/chat_projection/cases.json`
   est joué par pytest et par node et doit donner les mêmes bulles.

   Module PUR : aucun DOM, aucune horloge, aucun stockage. Le modèle garde les
   lignes stockées reçues (une par `event_id`, la première copie gagne) et
   recalcule les bulles à la demande : une promotion `uncertain` qui arrive
   dans une page plus tardive s'applique donc sans état intermédiaire, et une
   page rejouée après une reconnexion ne change rien. Seules les lignes de la
   conversation du modèle entrent ; `reset` change de conversation et vide
   tout (jamais de fusion de deux Boards).

   Slice 07b ajoute l'état pur des pièces jointes du composer (plus bas). */
(function(root){
  'use strict';
  const USER='user.transcript.accepted',PUBLISHED='brain.message.published',FAILED='brain.turn.failed';
  const CHAT_PROJECTION='chat';
  const CHAT_EVENT_TYPES=Object.freeze([USER,PUBLISHED,FAILED]);
  /* `failure_code` d'un `brain.turn.failed` sans `attributes.code` (même valeur que le domaine Python). */
  const UNKNOWN_FAILURE_CODE='brain_turn_failed';
  const ITEM_FIELDS=Object.freeze(['role','event_id','sequence','correlation_id','text','kind','status','failure_code','collapsed_event_ids']);

  const attrs=event=>event.attributes&&typeof event.attributes==='object'?event.attributes:{};
  const orNull=value=>value===undefined?null:value;

  /* Filtre sans état, miroir de `is_chat_event` : `addressing` absent, `addressed`
     ou `uncertain` pour un tour utilisateur ; toute autre valeur est écartée. */
  function isChatEvent(event){
    if(!event||typeof event!=='object')return false;
    if(event.event_type===USER){
      const addressing=attrs(event).addressing;
      return addressing===undefined||addressing===null||addressing==='addressed'||addressing==='uncertain';
    }
    return event.event_type===PUBLISHED||event.event_type===FAILED;
  }
  function failureCode(event){
    const code=attrs(event).code;
    return typeof code==='string'&&code?code:UNKNOWN_FAILURE_CODE;
  }

  function createChatModel(conversationId){
    return {conversationId:typeof conversationId==='string'&&conversationId?conversationId:null,
      rows:new Map(),pending:new Set(),cache:null};
  }
  /* Change de conversation (ou la remet à zéro) : lignes et attentes vidées. */
  function reset(model,conversationId){
    model.conversationId=typeof conversationId==='string'&&conversationId?conversationId:null;
    model.rows.clear();
    model.pending.clear();
    model.cache=null;
    return model;
  }
  /* Une page de `GET .../conversation-events` (`{events:[...]}`) ou directement
     ses lignes. Rejouable et idempotente par `event_id`. Une ligne d'une autre
     conversation, sans événement ou sans séquence entière est ignorée. Rend le
     nombre de lignes nouvelles. */
  function applyPage(model,page){
    const rows=Array.isArray(page)?page:(page&&Array.isArray(page.events)?page.events:[]);
    let added=0;
    for(const row of rows){
      const event=row&&row.event;
      if(!event||typeof event.event_id!=='string'||!Number.isSafeInteger(row.sequence))continue;
      if(model.conversationId===null||event.conversation_id!==model.conversationId||!isChatEvent(event))continue;
      if(model.rows.has(event.event_id))continue;
      model.rows.set(event.event_id,row);
      added++;
    }
    if(added)model.cache=null;
    return added;
  }
  /* Un tour texte envoyé dont la réponse est attendue (bulle « en cours » côté vue). */
  function markPending(model,correlationId){
    if(typeof correlationId==='string'&&correlationId)model.pending.add(correlationId);
    return model;
  }
  /* Vrai tant qu'un tour marqué n'a ni réponse du Brain ni échec dans cette conversation. */
  function isPending(model,correlationId){
    if(!model.pending.has(correlationId))return false;
    for(const row of model.rows.values()){
      const event=row.event;
      if(event.correlation_id===correlationId&&(event.event_type===PUBLISHED||event.event_type===FAILED))return false;
    }
    return true;
  }

  /* Repli des republications : règle de `collapseMessages`
     (`control_center_timeline.js`) et de `collapse_published_messages`
     (Python) — une publication égale à la précédente de sa corrélation est
     fusionnée dans celle-ci ; A, B, A reste trois bulles. Copie VOULUE de
     `collapseMessages` (plus bas, dans `project`) : `control_center_timeline.js`
     est hors périmètre et n'exporte rien de réutilisable ici ; la parité est
     tenue par le fixture partagé joué par pytest et par node. */
  function project(model){
    const rows=[...model.rows.values()].sort((a,b)=>a.sequence-b.sequence||(a.event.event_id<b.event.event_id?-1:a.event.event_id>b.event.event_id?1:0));
    const published=new Set(),failures=new Map();
    for(const {event} of rows){
      if(event.event_type===PUBLISHED&&event.correlation_id!=null)published.add(event.correlation_id);
      /* Le dernier échec d'une corrélation est son statut. */
      if(event.event_type===FAILED)failures.set(orNull(event.correlation_id),failureCode(event));
    }
    /* Statut d'échec seulement tant que le Brain n'a rien publié pour la corrélation : un message du
       Brain (tout statut, avant ou après l'échec) est la réponse, ses propres mots l'emportent. */
    const failureOf=correlation=>correlation!==null&&failures.has(correlation)&&!published.has(correlation)
      ?failures.get(correlation):null;
    const out=[],last=new Map();
    for(const row of rows){
      const event=row.event,correlation=orNull(event.correlation_id);
      if(event.event_type===USER){
        /* Un tour incertain n'apparaît, à sa propre séquence, qu'une fois que le Brain a répondu à sa corrélation. */
        if(attrs(event).addressing==='uncertain'&&!published.has(correlation))continue;
        out.push({role:'user',event_id:event.event_id,sequence:row.sequence,correlation_id:correlation,
          text:orNull(event.content),kind:null,status:null,failure_code:failureOf(correlation),collapsed_event_ids:[]});
      }else if(event.event_type===PUBLISHED){
        const text=orNull(event.content);
        if(correlation!==null){
          const at=last.get(correlation);
          if(at!==undefined&&out[at].text===text){out[at].collapsed_event_ids.push(event.event_id);continue}
          last.set(correlation,out.length);
        }
        out.push({role:'brain',event_id:event.event_id,sequence:row.sequence,correlation_id:correlation,text,
          kind:orNull(attrs(event).kind),status:orNull(attrs(event).status),failure_code:null,collapsed_event_ids:[]});
      }
    }
    return out;
  }
  /* Les bulles, dans l'ordre des séquences (copie : la vue ne modifie pas le modèle). */
  function items(model){
    if(model.cache===null)model.cache=project(model);
    return model.cache.map(item=>({...item,collapsed_event_ids:[...item.collapsed_event_ids]}));
  }

  /* `attributes.attachment_count` du tour utilisateur `eventId` (Slice 07b) : 0 sans pièce.
     Lu sur la ligne stockée, hors `ITEM_FIELDS` (la parité avec `project_chat` reste intacte). */
  function attachmentCount(model,eventId){
    const row=model.rows.get(eventId),count=row&&attrs(row.event).attachment_count;
    return Number.isSafeInteger(count)&&count>0?count:0;
  }
  /* Toutes les lignes gardées, dans l'ordre des séquences : ce qu'un meneur rend à un `hello`.
     Une par `event_id` : la mémoire suit la conversation, pas le nombre de `hello`. */
  function storedRows(model){
    return [...model.rows.values()].sort((a,b)=>a.sequence-b.sequence);
  }

  /* ---------- Pièces jointes du composer (Slice 07b, `docs/chat.md` › *Attachments* › UI) ----------
     État PUR des pièces d'un brouillon : aucun octet, aucun `File`, aucune requête.
     Une pièce appartient à la conversation où elle a été jointe (`cid`) ; vue
     depuis une autre conversation, elle est « à renvoyer » et n'est jamais
     envoyée. États : `uploading` (en cours), `ready` (prête ; `readable=false`
     = prête, non lisible par le Brain), `failed` (échec), `removed` (retirée).

     **Identité de téléversement** (`client_upload_id`, UUID v4) :
     - issue INCONNUE (délai, réseau, `core_timeout`, `upload_in_progress`) → la
       reprise garde le MÊME id : si Core a fini, il rejoue (200, aucun doublon) ;
     - échec CONNU (refus, `upload_incomplete`, `upload_conflict`…) → la reprise
       tire un NOUVEL id : Core garde la ligne `failed` et répondrait 409
       `upload_conflict` à l'ancien ;
     - une reprise au même id qui reçoit `upload_conflict` (l'essai inconnu
       avait échoué côté Core) repart aussitôt, une fois, avec un nouvel id. */
  const ATTACHMENT_STATES=Object.freeze(['uploading','ready','failed','removed']);
  const UNKNOWN_UPLOAD_CODES=Object.freeze(['core_timeout','client_timeout','network_error','upload_in_progress']);
  /* Échecs dont la reprise n'a pas de sens : le même fichier serait refusé pareil. */
  const FINAL_UPLOAD_CODES=Object.freeze(['upload_too_large','upload_empty','upload_name_invalid','upload_interrupted_reload']);

  function createAttachments(){return {items:[],seq:0}}
  function findAttachment(list,key){return list.items.find(item=>item.key===key)||null}
  function addAttachment(list,{name,size,mime,cid,clientUploadId}){
    const item={key:'att-'+(++list.seq),name:String(name==null?'':name),size:Number.isFinite(size)?size:0,
      mime:typeof mime==='string'?mime:'',cid:typeof cid==='string'&&cid?cid:null,clientUploadId:String(clientUploadId),
      state:'uploading',phase:'sending',loaded:0,total:Number.isFinite(size)?size:0,attempts:1,replay:false,
      artifactId:null,readable:null,error:null};
    list.items.push(item);
    return item;
  }
  function attachmentProgress(list,key,loaded,total){
    const item=findAttachment(list,key);if(!item||item.state!=='uploading')return null;
    if(Number.isFinite(total)&&total>0)item.total=total;
    if(Number.isFinite(loaded))item.loaded=Math.max(item.loaded,Math.min(loaded,item.total||loaded));
    return item;
  }
  /* Corps entièrement parti : Core borne, renifle et range ; on attend sa réponse. */
  function attachmentSent(list,key){
    const item=findAttachment(list,key);if(!item||item.state!=='uploading')return null;
    item.phase='checking';item.loaded=item.total;return item;
  }
  /* Réponse 200/201 du relais. Une pièce retirée entre-temps le reste. */
  function attachmentReady(list,key,answer){
    const item=findAttachment(list,key);if(!item||item.state!=='uploading')return null;
    if(!answer||typeof answer.artifact_id!=='string'||!answer.artifact_id)
      return attachmentFailed(list,key,{code:'invalid_response'}).item;
    item.state='ready';item.phase=null;item.artifactId=answer.artifact_id;item.readable=answer.brain_readable===true;
    if(typeof answer.mime_type==='string')item.mime=answer.mime_type;
    if(Number.isFinite(answer.size_bytes))item.size=answer.size_bytes;
    item.error=null;return item;
  }
  /* Rend `{item, autoRetry}` : `autoRetry` = reprise immédiate avec un nouvel id (voir plus haut). */
  function attachmentFailed(list,key,{code,status=null,limitBytes=null}={}){
    const item=findAttachment(list,key);if(!item||item.state!=='uploading')return {item:null,autoRetry:false};
    const failure=typeof code==='string'&&code?code:'unknown';
    const autoRetry=failure==='upload_conflict'&&item.replay;
    item.state='failed';item.phase=null;
    item.error={code:failure,status,limitBytes:Number.isFinite(limitBytes)?limitBytes:null,
      sameId:UNKNOWN_UPLOAD_CODES.includes(failure),retryable:!FINAL_UPLOAD_CODES.includes(failure)};
    return {item,autoRetry};
  }
  /* Reprise : même id après une issue inconnue, sinon `freshId`. Rend la pièce (ou null). */
  function retryAttachment(list,key,freshId){
    const item=findAttachment(list,key);if(!item||item.state!=='failed'||!item.error||!item.error.retryable)return null;
    const same=item.error.sameId;
    item.replay=same;if(!same)item.clientUploadId=String(freshId);
    item.state='uploading';item.phase='sending';item.loaded=0;item.attempts++;item.error=null;
    return item;
  }
  /* « Renvoyer ici » : une pièce d'une autre conversation repart vers `cid`, comme une nouvelle pièce. */
  function rebindAttachment(list,key,cid,freshId){
    const item=findAttachment(list,key);if(!item||item.state==='removed'||item.cid===cid)return null;
    Object.assign(item,{cid,clientUploadId:String(freshId),state:'uploading',phase:'sending',loaded:0,attempts:1,replay:false,
      artifactId:null,readable:null,error:null});
    return item;
  }
  /* Retirée : rend l'état d'avant (`uploading` → l'appelant annule la requête). */
  function removeAttachment(list,key){
    const item=findAttachment(list,key);if(!item||item.state==='removed')return null;
    const before=item.state;item.state='removed';item.phase=null;
    list.items=list.items.filter(other=>other!==item);
    return before;
  }
  /* Ce que la conversation `cid` montre et peut envoyer. */
  function attachmentView(list,cid){
    const items=list.items.filter(item=>item.state!=='removed').map(item=>({...item,
      status:item.cid!==cid?'stale':item.state==='ready'?(item.readable?'ready':'unreadable'):item.state,
      error:item.error?{...item.error}:null}));
    const mine=items.filter(item=>item.status!=='stale');
    const ids=mine.filter(item=>item.state==='ready').map(item=>item.artifactId);
    const uploading=mine.filter(item=>item.state==='uploading').length,failed=mine.filter(item=>item.state==='failed').length;
    return {items,ids,uploading,failed,stale:items.length-mine.length,
      blocked:uploading?'uploading':failed?'failed':null};
  }
  /* Message admis : ses pièces quittent le composer. Rend les pièces envoyées (noms : état local de la vue). */
  function takeSent(list,cid,ids){
    const sent=list.items.filter(item=>item.cid===cid&&item.state==='ready'&&ids.includes(item.artifactId));
    list.items=list.items.filter(item=>!sent.includes(item));
    return sent.map(item=>({key:item.key,artifactId:item.artifactId,name:item.name,size:item.size,mime:item.mime,readable:item.readable}));
  }
  /* Pièce relue d'un brouillon gardé (rechargement) : prête si elle avait son Artifact, sinon interrompue.
     Une pièce déjà présente (même `client_upload_id`, ou même Artifact) n'est jamais doublée : la pièce
     vivante l'emporte sur l'enregistrement de reprise (QA S7b, ligne fantôme après un aller-retour de Board). */
  function restoreAttachment(list,saved){
    if(!saved||typeof saved.name!=='string')return null;
    if(typeof saved.artifactId==='string'&&list.items.some(item=>item.artifactId===saved.artifactId))return null;
    if(typeof saved.clientUploadId==='string'&&saved.clientUploadId&&list.items.some(item=>item.clientUploadId===saved.clientUploadId))return null;
    const item=addAttachment(list,{name:saved.name,size:saved.size,mime:saved.mime,cid:saved.cid,
      clientUploadId:typeof saved.clientUploadId==='string'?saved.clientUploadId:''});
    if(typeof saved.artifactId==='string'&&saved.artifactId)
      return attachmentReady(list,item.key,{artifact_id:saved.artifactId,brain_readable:saved.readable===true});
    return attachmentFailed(list,item.key,{code:'upload_interrupted_reload'}).item;
  }
  /* Signature des pièces prêtes d'une conversation : un autre jeu de pièces est un autre message (nouvel id). */
  function attachmentSignature(list,cid){
    return attachmentView(list,cid).ids.slice().sort().join(',');
  }
  /* Taille lisible (octets → « 12 o », « 3,4 Ko », « 64 Mo »), unités binaires comme la borne de Core. */
  function formatBytes(bytes){
    if(!Number.isFinite(bytes)||bytes<0)return '';
    if(bytes<1024)return `${bytes} o`;
    const units=['Ko','Mo','Go'];let value=bytes/1024,unit=0;
    while(value>=1024&&unit<units.length-1){value/=1024;unit++}
    const text=value>=10?String(Math.round(value)):value.toFixed(1).replace(/\.0$/,'').replace('.',',');
    return `${text} ${units[unit]}`;
  }
  /* Borne de Core dans son message (« the file exceeds the N-byte upload bound ») : le relais ne la porte pas à part. */
  function uploadLimitFrom(message){
    const match=/(\d+)-byte/.exec(String(message||''));
    return match?Number(match[1]):null;
  }

  const api=Object.freeze({CHAT_PROJECTION,CHAT_EVENT_TYPES,UNKNOWN_FAILURE_CODE,ITEM_FIELDS,
    isChatEvent,createChatModel,applyPage,items,markPending,isPending,reset,attachmentCount,storedRows,
    ATTACHMENT_STATES,UNKNOWN_UPLOAD_CODES,FINAL_UPLOAD_CODES,createAttachments,addAttachment,attachmentProgress,
    attachmentSent,attachmentReady,attachmentFailed,retryAttachment,rebindAttachment,removeAttachment,attachmentView,
    takeSent,restoreAttachment,attachmentSignature,formatBytes,uploadLimitFrom});
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.JarvisChatModel=api;
})(typeof window!=='undefined'?window:(typeof globalThis!=='undefined'?globalThis:null));
