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
   tout (jamais de fusion de deux Boards). */
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
    /* Dernière publication et dernier échec de chaque corrélation (lignes croissantes : la dernière gagne). */
    const published=new Map(),failures=new Map();
    for(const {event,sequence} of rows){
      if(event.event_type===PUBLISHED&&event.correlation_id!=null)published.set(event.correlation_id,sequence);
      if(event.event_type===FAILED)failures.set(orNull(event.correlation_id),{sequence,code:failureCode(event)});
    }
    /* Statut d'échec, miroir de `_failure_status` : le dernier échec, sauf si le Brain a publié après lui. */
    const failureOf=correlation=>{
      const failure=correlation!==null?failures.get(correlation):undefined;
      return failure!==undefined&&(published.get(correlation)??0)<failure.sequence?failure.code:null;
    };
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

  const api=Object.freeze({CHAT_PROJECTION,CHAT_EVENT_TYPES,UNKNOWN_FAILURE_CODE,ITEM_FIELDS,
    isChatEvent,createChatModel,applyPage,items,markPending,isPending,reset});
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.JarvisChatModel=api;
})(typeof window!=='undefined'?window:(typeof globalThis!=='undefined'?globalThis:null));
