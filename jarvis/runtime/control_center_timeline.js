/* Chronologie de conversation en direct (Slice 05 de la tâche
   jarvis-conversation-observability-timeline).

   Contrat : `docs/conversation-events.md`, sections « Query and live API » et
   « Timeline UI ». Deux parties, comme `control_center_barehands.js` :

   - `JarvisTimelineCore`, logique pure exécutée telle quelle par les tests
     node : appariement des spans (port exact de `reconstruct_conversation`),
     lanes, fusion des messages dupliqués, géométrie temporelle et empilement
     des chevauchements, fenêtre virtualisée, machine d'état hydratation +
     long-poll, modèles du statut, du panneau de détail et de la trace ;
   - un bloc navigateur qui branche la vue plein écran dans la page.

   La vue ne lit que les routes canoniques `/api/conversations...` : jamais
   `/api/trace`, jamais une ligne de trace brute. Aucune pensée cachée n'existe
   dans les événements (contrat), rien n'en est reconstitué ici. */

const JarvisTimelineCore=(function(){
  'use strict';

  /* ------------------------------------------------------------ vocabulaire */
  const I='instant',O='open',C='close',P='public',D='diagnostic';
  /* Miroir de `_SPECS` (jarvis/domain/conversation_events.py) : acteur, forme,
     visibilité. Un test compare ce tableau au domaine Python. */
  const SPECS=Object.freeze({
    'user.transcript.accepted':['user',I,P],
    'brain.turn.accepted':['brain',I,D],
    'brain.turn.failed':['brain',I,D],
    'brain.message.published':['brain',I,P],
    'brain.speech.requested':['brain',I,D],
    'brain.work.started':['brain',O,D],
    'brain.work.completed':['brain',C,D],
    'brain.work.failed':['brain',C,D],
    'brain.work.cancelled':['brain',C,D],
    'mouth.speech.queued':['mouth',I,D],
    'mouth.speech.started':['mouth',O,P],
    'mouth.speech.completed':['mouth',C,P],
    'mouth.speech.interrupted':['mouth',C,P],
    'mouth.speech.superseded':['mouth',C,D],
    'mouth.speech.expired':['mouth',C,D],
    'mouth.speech.failed':['mouth',C,D],
    'mouth.reflex.started':['mouth',I,P],
    'subagent.started':['subagent',O,D],
    'subagent.finished':['subagent',C,D],
    'subagent.failed':['subagent',C,D],
    'subagent.stopped':['subagent',C,D],
    'tool.call.started':['tool',O,D],
    'tool.call.finished':['tool',C,D],
    'system.failure':['system',I,D],
  });
  const SPAN_OPENER=Object.freeze({
    'brain.work.completed':'brain.work.started','brain.work.failed':'brain.work.started','brain.work.cancelled':'brain.work.started',
    'mouth.speech.completed':'mouth.speech.started','mouth.speech.interrupted':'mouth.speech.started',
    'mouth.speech.superseded':'mouth.speech.started','mouth.speech.expired':'mouth.speech.started','mouth.speech.failed':'mouth.speech.started',
    'subagent.finished':'subagent.started','subagent.failed':'subagent.started','subagent.stopped':'subagent.started',
    'tool.call.finished':'tool.call.started',
  });
  const ANOMALY=Object.freeze({DUPLICATE_OPEN:'duplicate_span_open',DUPLICATE_CLOSE:'duplicate_span_close',
    CLOSE_BEFORE_OPEN:'close_before_open',CONFLICT:'conflicting_duplicate'});
  const ID_FIELDS=['conversation_id','session_id','turn_id','correlation_id','task_id','work_id','speech_id','outcome_id','span_id','parent_event_id'];

  /* Type inconnu (contrat plus récent que la page) : montré comme un instant,
     jamais écarté. Le codec de Core refuse de tels types aujourd'hui. */
  function spec(event){return SPECS[event.event_type]||[String(event.actor||'system'),I,event.visibility===P?P:D]}
  function shapeOf(event){return spec(event)[1]}
  function timeMs(value){
    if(value===null||value===undefined)return null;
    const t=Date.parse(value);
    return Number.isFinite(t)?t:null;
  }
  function iso(ms){return ms===null||ms===undefined?null:new Date(ms).toISOString()}
  function statusOf(type){const i=String(type).lastIndexOf('.');return i<0?String(type):String(type).slice(i+1)}
  function cmpStr(a,b){return a<b?-1:a>b?1:0}
  /* JSON à clés triées : égalité de contenu de deux copies d'un même event_id. */
  function canonical(value){
    if(Array.isArray(value))return `[${value.map(canonical).join(',')}]`;
    if(value&&typeof value==='object')return `{${Object.keys(value).sort().map(k=>`${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
    return JSON.stringify(value===undefined?null:value);
  }

  /* ---------------------------------------------------------- reconstruction */
  function makeItem(primary,close,status,start,end,text,eventIds,anomalies,extra){
    const [actor,shape,visibility]=spec(primary);
    const pick=field=>{for(const e of [primary,close])if(e&&e[field]!==null&&e[field]!==undefined)return e[field];return null};
    const events=[primary];
    if(close&&close!==primary)events.push(close);
    events.push(...extra);
    const item={item_id:primary.event_id,actor,event_type:primary.event_type,status,visibility,
      started_at:start,ended_at:end,text:text===undefined?null:text,span_id:primary.span_id===undefined?null:primary.span_id,
      event_ids:eventIds,anomalies,open:shape===O?primary:null,close:close||null,events,producer:primary.producer||'',
      attributes:Object.assign({},primary.attributes||{},close&&close!==primary?close.attributes||{}:{}),collapsed:[]};
    for(const field of ID_FIELDS)if(field!=='span_id')item[field]=pick(field);
    return item;
  }

  /* Port exact de `reconstruct_conversation` (Python) : mêmes statuts, mêmes
     anomalies, même ordre. Ne lève jamais sur des données incohérentes ; lève
     seulement pour une entrée qui n'est pas un événement ou des événements de
     plusieurs conversations. `started_at` / `ended_at` en millisecondes. */
  /* Un événement dont l'heure ne se lit pas n'est jamais placé à l'époque 0 :
     il est écarté et compté (Core refuse de tels événements ; défense en
     profondeur pour la page). */
  function readableEvents(events){
    const readable=[],unreadable=[];
    for(const event of events||[]){
      if(event&&typeof event==='object'&&timeMs(event.occurred_at)===null)unreadable.push(event.event_id);
      else readable.push(event);
    }
    return {events:readable,unreadable};
  }
  function reconstruct(events){
    const unique=new Map(),conflicts=new Map();
    let conversation=null;
    for(const event of events||[]){
      if(!event||typeof event!=='object'||typeof event.event_id!=='string')throw new TypeError('reconstruction accepts canonical event objects only');
      if(timeMs(event.occurred_at)===null)continue;
      if(conversation===null)conversation=event.conversation_id;
      else if(event.conversation_id!==conversation)throw new Error('reconstruction received events from several conversations');
      const known=unique.get(event.event_id);
      if(!known){unique.set(event.event_id,{event,t:timeMs(event.occurred_at),sig:null});continue}
      if(known.sig===null)known.sig=canonical(known.event);
      if(canonical(event)!==known.sig)conflicts.set(event.event_id,true);
    }
    const ordered=[...unique.values()].sort((a,b)=>a.t-b.t||cmpStr(a.event.event_id,b.event.event_id));
    const key=(type,span)=>`${type}|${span}`;
    const opens=new Map(),closes=new Map();
    const push=(map,k,r)=>{const list=map.get(k);if(list)list.push(r);else map.set(k,[r])};
    for(const r of ordered){
      const shape=shapeOf(r.event);
      if(shape===O)push(opens,key(r.event.event_type,r.event.span_id),r);
      else if(shape===C)push(closes,key(SPAN_OPENER[r.event.event_type],r.event.span_id),r);
    }
    const items=[],owner=new Map();
    const extras=(code,list,anomalies,extra)=>{
      for(const x of list.slice(1)){anomalies.push(`${code}:${x.event.event_id}`);owner.set(x.event.event_id,items.length);extra.push(x.event)}
    };
    for(const r of ordered){
      const e=r.event,shape=shapeOf(e),anomalies=[],extra=[];
      if(shape===I){
        owner.set(e.event_id,items.length);
        items.push(makeItem(e,null,statusOf(e.event_type),r.t,r.t,e.content,[e.event_id],anomalies,extra));
      }else if(shape===O){
        const k=key(e.event_type,e.span_id),list=opens.get(k);
        if(list[0]!==r)continue;
        extras(ANOMALY.DUPLICATE_OPEN,list,anomalies,extra);
        owner.set(e.event_id,items.length);
        const closeList=closes.get(k);
        if(!closeList||!closeList.length){
          items.push(makeItem(e,null,'open',r.t,null,e.content,[e.event_id],anomalies,extra));
          continue;
        }
        const close=closeList[0].event;
        extras(ANOMALY.DUPLICATE_CLOSE,closeList,anomalies,extra);
        owner.set(close.event_id,items.length);
        let end=timeMs(close.ended_at);
        if(end===null)end=closeList[0].t;
        if(end<r.t){anomalies.push(`${ANOMALY.CLOSE_BEFORE_OPEN}:${close.event_id}`);end=r.t}
        const text=close.content!==null&&close.content!==undefined?close.content:e.content;
        items.push(makeItem(e,close,statusOf(close.event_type),r.t,end,text,[e.event_id,close.event_id],anomalies,extra));
      }else{
        const k=key(SPAN_OPENER[e.event_type],e.span_id);
        if(opens.has(k)||closes.get(k)[0]!==r)continue;
        extras(ANOMALY.DUPLICATE_CLOSE,closes.get(k),anomalies,extra);
        owner.set(e.event_id,items.length);
        const started=e.started_at!==null&&e.started_at!==undefined?timeMs(e.started_at):r.t;
        items.push(makeItem(e,e,statusOf(e.event_type),started,r.t,e.content,[e.event_id],anomalies,extra));
      }
    }
    for(const id of conflicts.keys())items[owner.get(id)].anomalies.push(`${ANOMALY.CONFLICT}:${id}`);
    items.sort((a,b)=>a.started_at-b.started_at||cmpStr(a.item_id,b.item_id));
    return items;
  }

  /* Ligne comparable à `as_rows` des tests Python (heures en temps « wire »). */
  function toRow(item){
    return {actor:item.actor,event_type:item.event_type,status:item.status,started_at:iso(item.started_at),
      ended_at:iso(item.ended_at),text:item.text,anomalies:[...item.anomalies]};
  }

  /* Obligation de projection (docs/conversation-events.md, « duplicate text ») :
     un tour qui dit son résultat puis se termine avec le même résumé publie deux
     `brain.message.published` identiques. Un message dont le texte égale le
     message publié précédent de la même corrélation est fusionné dans celui-ci
     (`collapsed` garde les éléments absorbés, `events` toutes leurs preuves). */
  function collapseMessages(items){
    const out=[],last=new Map();
    for(const item of items){
      if(item.event_type==='brain.message.published'&&item.correlation_id!==null){
        const at=last.get(item.correlation_id);
        if(at!==undefined&&out[at].text===item.text){
          const kept=out[at];
          out[at]={...kept,collapsed:[...kept.collapsed,item],events:[...kept.events,...item.events]};
          continue;
        }
        last.set(item.correlation_id,out.length);
      }
      out.push(item);
    }
    return out;
  }

  function filterItems(items,mode){return mode==='public'?items.filter(i=>i.visibility===P):items.slice()}

  /* ------------------------------------------------------------------ lanes */
  const LANES=Object.freeze([
    Object.freeze({id:'user',label:'Utilisateur',empty:'Aucune parole utilisateur admise.'}),
    Object.freeze({id:'mouth',label:'Jarvis · voix',empty:'Aucune parole de Jarvis enregistrée. Architectures directes (simple, front_brain, duplex) : pas encore de lane voix.'}),
    Object.freeze({id:'brain',label:'Brain',empty:'Aucune activité du Brain.'}),
    Object.freeze({id:'subagent',label:'Sous-agents',empty:'Aucun sous-agent attribué à cette conversation (ceux lancés depuis le panneau ou un tour spontané ne sont pas enregistrés).'}),
  ]);
  const LANE_INDEX=Object.freeze(Object.fromEntries(LANES.map((l,i)=>[l.id,i])));
  /* Outils et échecs système : lane de leur producteur. Les outils `voice.*`
     sont les appels du modèle temps réel qui porte la voix de Jarvis, pas du
     Brain ; tout autre producteur (Core, Control Center) est côté Brain. */
  function laneOf(item){
    if(item.actor==='user'||item.actor==='mouth'||item.actor==='brain'||item.actor==='subagent')return item.actor;
    return String(item.producer||'').startsWith('voice.')?'mouth':'brain';
  }
  function isSpan(item){const s=spec({event_type:item.event_type,actor:item.actor});return s[1]!==I}
  const DOT_TYPES=new Set(['brain.turn.accepted','brain.speech.requested','mouth.speech.queued']);
  const FAILURE_TYPES=new Set(['brain.turn.failed','system.failure']);
  /* Forme d'une entrée :
     - card : texte public (parole utilisateur, parole de Jarvis, réflexe, message
       du Brain), jamais coupé ; la carte grandit, la durée exacte est une barre ;
     - failure : échec (tour, système), carte rouge au libellé toujours visible ;
     - dot : repère diagnostique instantané, point sur le rail gauche de sa lane,
       libellé au survol ou au focus ;
     - bar : travail du Brain ou outil, barre étroite sur le rail droit ;
     - block : sous-agent, bloc rouge de durée exacte, texte à l'intérieur. */
  function entryKind(item){
    if(item.actor==='subagent')return 'block';
    if(FAILURE_TYPES.has(item.event_type))return 'failure';
    if(item.actor==='tool'||String(item.event_type).startsWith('brain.work.'))return 'bar';
    /* Repère diagnostique : point. Un réflexe (public) est du texte de transcription : carte. */
    if(item.visibility!==P&&(DOT_TYPES.has(item.event_type)||!SPECS[item.event_type]))return 'dot';
    return 'card';
  }

  /* -------------------------------------------------------------- libellés */
  const GENERIC_TYPES=new Set(['','general-purpose','general','fork','default','agent','task','subagent']);
  const TYPE_LABELS=Object.freeze({
    'user.transcript.accepted':'Parole utilisateur','brain.turn.accepted':'Tour accepté','brain.turn.failed':'Tour en échec',
    'brain.message.published':'Message du Brain','brain.speech.requested':'Parole demandée','brain.work.started':'Travail du Brain',
    'mouth.speech.queued':'Parole en file','mouth.speech.started':'Parole de Jarvis','mouth.reflex.started':'Réflexe',
    'subagent.started':'Sous-agent','tool.call.started':'Appel d’outil','system.failure':'Échec système',
  });
  const STATUS_LABELS=Object.freeze({open:'en cours',completed:'terminé',interrupted:'interrompu',superseded:'remplacé',
    expired:'expiré',failed:'échec',finished:'terminé',stopped:'arrêté',cancelled:'annulé',accepted:'accepté',
    published:'publié',requested:'demandé',queued:'en file',started:'démarré',failure:'échec'});
  const WARN=new Set(['interrupted','superseded','expired','stopped','cancelled']);
  function typeLabel(item){
    const opener=SPAN_OPENER[item.event_type]||item.event_type;
    return TYPE_LABELS[opener]||item.event_type;
  }
  function statusLabel(status){return STATUS_LABELS[status]||String(status)}
  function toneOf(item){
    if(item.status==='open')return 'live';
    if(item.status==='failed'||item.event_type==='system.failure'||item.event_type==='brain.turn.failed')return 'bad';
    if(WARN.has(item.status))return 'warn';
    return 'ok';
  }
  function prettyType(type){
    return String(type).split(/[-_\s]+/).filter(Boolean).map(w=>/^[A-Z0-9]+$/.test(w)?w:w.charAt(0).toUpperCase()+w.slice(1)).join(' ');
  }
  function subagentName(item){
    const type=String(item.attributes.subagent_type||'').trim();
    if(type&&!GENERIC_TYPES.has(type.toLowerCase()))return prettyType(type);
    /* Nom : la description portée par l'ouverture (le texte d'une clôture est
       un compte rendu, pas un nom). */
    const described=item.open&&item.open.content?item.open.content:item.text;
    return String(described||'').trim()||'Sous-agent';
  }
  function subagentDescription(item){
    const name=subagentName(item),desc=String(item.open&&item.open.content||'').trim();
    return desc&&desc!==name?desc:'';
  }
  /* Texte affiché dans la chronologie (jamais autre chose que le contenu
     public de l'événement, ses attributs autorisés ou un libellé fixe). */
  function displayText(item){
    const a=item.attributes||{};
    switch(entryKind(item)){
      case 'dot':{
        const base=typeLabel(item);
        return item.text&&item.event_type==='brain.speech.requested'?`${base} : ${item.text}`:base;
      }
      case 'failure':{
        const code=a.code||a.reason||a.error_class;
        return code?`${typeLabel(item)} · ${code}`:typeLabel(item);
      }
      case 'block':{
        const desc=subagentDescription(item);
        return desc?`${subagentName(item)} · ${desc}`:subagentName(item);
      }
      case 'bar':
        if(item.actor==='tool')return `Outil ${a.tool_name||'inconnu'}`;
        return (item.open&&item.open.content)||item.text||`Travail ${item.work_id||item.span_id||''}`.trim();
      default:
        if(item.event_type==='mouth.reflex.started')return item.text||'Réflexe';
        if(item.actor==='mouth')return item.text||'Texte non enregistré';
        return item.text||typeLabel(item);
    }
  }
  function fmtDuration(ms){
    if(ms===null||ms===undefined||!Number.isFinite(ms))return '—';
    const v=Math.max(0,ms);
    if(v<1000)return `${Math.round(v)} ms`;
    if(v<60000)return `${(v/1000).toFixed(v<10000?2:1).replace('.',',')} s`;
    const s=Math.round(v/1000),m=Math.floor(s/60);
    if(m<60)return `${m} min ${String(s%60).padStart(2,'0')} s`;
    return `${Math.floor(m/60)} h ${String(m%60).padStart(2,'0')} min`;
  }
  function fmtClock(ms,{millis=true,utc=false}={}){
    if(ms===null||ms===undefined||!Number.isFinite(ms))return '—';
    const d=new Date(ms),g=utc?['getUTCHours','getUTCMinutes','getUTCSeconds']:['getHours','getMinutes','getSeconds'];
    const p=n=>String(n).padStart(2,'0');
    const base=`${p(d[g[0]]())}:${p(d[g[1]]())}:${p(d[g[2]]())}`;
    return millis?`${base}.${String(d[utc?'getUTCMilliseconds':'getMilliseconds']()).padStart(3,'0')}`:base;
  }
  function durationOf(item,now){
    if(item.ended_at!==null)return item.ended_at-item.started_at;
    return now===null||now===undefined?null:Math.max(0,now-item.started_at);
  }
  /* Parole interrompue : le contenu est le texte envoyé à la lecture, pas le
     texte entendu (contrat, note 5). La vue le dit, toujours. */
  function playbackNote(item){
    if(item.actor!=='mouth'||item.event_type==='mouth.reflex.started'||!isSpan(item))return null;
    const played=item.attributes&&item.attributes.played_ms;
    if(item.status==='interrupted')return Number.isFinite(played)?`Texte envoyé à la lecture · coupé après ${fmtDuration(played)} entendues`:'Texte envoyé à la lecture · coupé, durée entendue inconnue';
    if(item.status==='open')return 'Texte envoyé à la lecture · en cours';
    if(item.status!=='completed')return 'Texte envoyé à la lecture, non prononcé en entier';
    return null;
  }
  function escapeHtml(value){
    return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  /* -------------------------------------------------------------- géométrie */
  /* 60 px/s : deux repères diagnostiques à 0,5 s d'écart restent distincts. */
  const DEFAULT_PPS=60;
  /* Constantes du rendu, alignées sur le CSS `.tl-*` de la page (une carte :
     bordure 1 + marge 5 + ligne d'en-tête 14 + 2 + n × 16 + marge 6 + bordure 1). */
  const GEOMETRY=Object.freeze({
    charPx:7.2,            // largeur d'un caractère du texte (12,5 px, monospace) ; la page mesure la vraie
    headCharRatio:.84,     // en-tête en 10,5 px
    linePx:16,headLinePx:14,cardChromePx:29,cardPadXPx:22,
    minTextChars:28,       // largeur minimale d'une colonne de texte
    railDotPx:18,barPx:14,barGapPx:3,laneEdgePx:5,dotPx:18,
    blockPadYPx:12,blockMinPx:46,blockPadXPx:18,blockMinChars:18,
    packGapPx:4,rulerPx:76,gapMs:6000,gapPx:44,padTop:18,padBottom:56,emptyLanePx:150,maxNeedCols:4,
  });
  /* Nombre de lignes d'un texte mis en forme comme `white-space:pre-wrap;
     overflow-wrap:anywhere` sur `cpl` caractères (retour à la ligne par mot,
     mot trop long coupé). La page corrige ensuite par la hauteur réellement
     rendue (`heightFix`), donc une estimation courte ne coupe jamais le texte. */
  function wrapLines(text,cpl){
    const width=Math.max(1,Math.floor(cpl));
    let lines=0;
    for(const paragraph of String(text??'').split('\n')){
      let cur=0;lines++;
      for(const word of paragraph.split(' ')){
        let length=word.length;
        const need=cur===0?length:cur+1+length;
        if(need<=width){cur=need;continue}
        if(cur>0){lines++;cur=0}
        while(length>width){lines++;length-=width}
        cur=length;
      }
    }
    return lines;
  }
  function headText(item,now){
    const parts=[fmtClock(item.started_at)];
    if(isSpan(item))parts.push(fmtDuration(durationOf(item,now)));
    if(isSpan(item)||toneOf(item)!=='ok')parts.push(`[${statusLabel(item.status)}]`);
    if(item.event_type==='mouth.reflex.started')parts.push('[réflexe]');
    if(item.collapsed&&item.collapsed.length)parts.push(`×${item.collapsed.length+1}`);
    return parts.join(' ');
  }
  /* Hauteur d'une carte à la largeur où elle sera dessinée : jamais de coupe. */
  function cardHeight(item,width,o=GEOMETRY,now=null){
    const textWidth=Math.max(o.charPx,width-o.cardPadXPx);
    const lines=wrapLines(displayText(item),textWidth/o.charPx);
    const headLines=wrapLines(headText(item,now),textWidth/(o.charPx*o.headCharRatio));
    return o.cardChromePx+(headLines-1)*o.headLinePx+lines*o.linePx;
  }
  /* Colonnes d'agenda : une entrée va dans la première colonne libre ; une
     grappe d'entrées qui se chevauchent partage le nombre de colonnes. */
  function packColumns(list,gap){
    let columns=[],cluster=[],clusterBottom=-Infinity;
    const finish=()=>{for(const r of cluster)r.cols=columns.length};
    for(const r of list){
      if(cluster.length&&r.y0>=clusterBottom+gap){finish();columns=[];cluster=[];clusterBottom=-Infinity}
      let c=columns.findIndex(b=>b+gap<=r.y0);
      if(c<0){c=columns.length;columns.push(r.bottom)}else columns[c]=r.bottom;
      r.col=c;cluster.push(r);clusterBottom=Math.max(clusterBottom,r.bottom);
    }
    finish();
  }
  /* Barres (travaux, outils) : colonnes par recouvrement dans le temps seul. */
  function packBars(list){
    const ends=[];
    for(const r of list.sort((a,b)=>a.start-b.start||cmpStr(a.item.item_id,b.item.item_id))){
      let c=ends.findIndex(e=>e<r.start);
      const end=Math.max(r.end,r.start+1);
      if(c<0){c=ends.length;ends.push(end)}else ends[c]=end;
      r.col=c;
    }
    return ends.length;
  }

  function buildScale(rows,o,pps){
    const points=[...new Set(rows.flatMap(r=>r.end!==r.start?[r.start,r.end]:[r.start]))].sort((a,b)=>a-b);
    const ts=[],ys=[],breaks=[];
    const byStart=rows.map((r,i)=>i).sort((a,b)=>rows[a].start-rows[b].start);
    let k=0,maxBottom=o.padTop,y=o.padTop;
    for(let i=0;i<points.length;i++){
      const p=points[i];
      if(i>0){
        const prev=points[i-1],last=ys[ys.length-1],d=p-prev;
        if(d>o.gapMs){
          const top=Math.max(last,maxBottom)+6;
          breaks.push({from:prev,to:p,durationMs:d,y0:top,y1:top+o.gapPx});
          y=top+o.gapPx+6;
        }else y=last+d/1000*pps;
      }
      ts.push(p);ys.push(y);
      while(k<byStart.length&&rows[byStart[k]].start<=p){maxBottom=Math.max(maxBottom,y+rows[byStart[k]].reach);k++}
    }
    const toY=t=>{
      if(!ts.length)return o.padTop;
      if(t<=ts[0])return ys[0];
      if(t>=ts[ts.length-1])return ys[ys.length-1];
      let lo=0,hi=ts.length-1;
      while(hi-lo>1){const m=(lo+hi)>>1;if(ts[m]<=t)lo=m;else hi=m}
      return ys[lo]+(ys[hi]-ys[lo])*(t-ts[lo])/(ts[hi]-ts[lo]);
    };
    const timeAt=yv=>{
      if(!ts.length)return null;
      if(yv<=ys[0])return ts[0];
      if(yv>=ys[ys.length-1])return ts[ts.length-1];
      let lo=0,hi=ys.length-1;
      while(hi-lo>1){const m=(lo+hi)>>1;if(ys[m]<=yv)lo=m;else hi=m}
      return ys[hi]===ys[lo]?ts[lo]:ts[lo]+(ts[hi]-ts[lo])*(yv-ys[lo])/(ys[hi]-ys[lo]);
    };
    return {ts,ys,breaks,toY,timeAt,maxBottom};
  }

  /* Axe temporel partagé par les quatre lanes : linéaire (`pxPerSecond`) tant
     que les instants se suivent ; chaque silence plus long que `gapMs` est
     replié en une bande fixe (`breaks`) placée sous les cartes déjà posées. La
     fonction reste strictement croissante : départs, durées et chevauchements
     entre lanes sont conservés.

     Largeur des lanes pondérée par le besoin (colonnes de texte simultanées,
     rails, blocs parallèles ; 28 caractères au moins par colonne de texte), le
     surplus de `width` réparti au prorata. Les hauteurs des cartes sont
     mesurées à la largeur finale de leur colonne (itération jusqu'à stabilité),
     jamais avant le rangement en colonnes. */
  function layout(items,options={}){
    const o={...GEOMETRY,width:1200,pxPerSecond:DEFAULT_PPS,now:null,heightFix:null,...options};
    const pps=Math.max(1,Number(o.pxPerSecond)||DEFAULT_PPS);
    const rows=items.map(item=>{
      const span=isSpan(item),open=span&&item.ended_at===null,lane=laneOf(item),kind=entryKind(item);
      const end=item.ended_at!==null?item.ended_at:open&&Number.isFinite(o.now)?Math.max(item.started_at,o.now):item.started_at;
      return {item,lane,kind,span,open,start:item.started_at,end,ty:0,y0:0,yEnd:0,h:0,bottom:0,reach:0,col:0,cols:1,x:0,w:0};
    });
    const byLane=Object.fromEntries(LANES.map(l=>[l.id,rows.filter(r=>r.lane===l.id)]));
    const minText=o.minTextChars*o.charPx+o.cardPadXPx+4,minBlock=o.blockMinChars*o.charPx+o.blockPadXPx;
    const barCols={};
    for(const lane of LANES)barCols[lane.id]=packBars(byLane[lane.id].filter(r=>r.kind==='bar'));
    const railLeft=id=>byLane[id].some(r=>r.kind==='dot')?o.railDotPx:o.laneEdgePx;
    const railRight=id=>barCols[id]?barCols[id]*(o.barPx+o.barGapPx)+o.laneEdgePx:o.laneEdgePx;

    function geometry(widths){
      let x=0;
      return LANES.map((lane,i)=>{
        const g={id:lane.id,x,width:widths[i],textLeft:railLeft(lane.id),textRight:widths[i]-railRight(lane.id)};
        x+=widths[i];
        return g;
      });
    }
    function pass(lanes){
      const geo=Object.fromEntries(lanes.map(g=>[g.id,g]));
      const measure=(r,width)=>{
        const fixed=o.heightFix?o.heightFix(r.item,Math.round(width)):undefined;
        const estimate=cardHeight(r.item,width,o,o.now);
        return Number.isFinite(fixed)?Math.max(fixed,estimate):estimate;
      };
      for(const r of rows){
        r.cols=1;r.col=r.kind==='bar'?r.col:0;
        if(r.kind==='card'||r.kind==='failure'){const g=geo[r.lane];r.h=measure(r,g.textRight-g.textLeft-4)}
      }
      let scale;
      for(let round=0;round<5;round++){
        for(const r of rows){
          r.reach=r.kind==='card'||r.kind==='failure'?r.h:r.kind==='block'?o.blockMinPx:r.kind==='dot'?o.dotPx/2:6;
        }
        scale=buildScale(rows,o,pps);
        for(const r of rows){
          r.ty=scale.toY(r.start);r.yEnd=scale.toY(r.end);
          if(r.kind==='dot'){r.y0=r.ty-o.dotPx/2;r.h=o.dotPx;r.bottom=r.ty+o.dotPx/2}
          else if(r.kind==='bar'){r.y0=r.ty;r.h=Math.max(6,r.yEnd-r.ty);r.bottom=r.y0+r.h}
          else if(r.kind==='block'){r.y0=r.ty;r.h=Math.max(o.blockMinPx,r.yEnd-r.ty);r.bottom=r.y0+r.h}
          else{r.y0=r.ty;r.bottom=Math.max(r.yEnd,r.y0+r.h)}
        }
        let changed=false;
        for(const lane of LANES){
          const g=geo[lane.id],order=(a,b)=>a.y0-b.y0||cmpStr(a.item.item_id,b.item.item_id);
          const text=byLane[lane.id].filter(r=>r.kind==='card'||r.kind==='failure').sort(order);
          packColumns(text,o.packGapPx);
          for(const r of text){
            const colW=(g.textRight-g.textLeft)/r.cols,h=measure(r,colW-4);
            if(h!==r.h){r.h=h;changed=true}
          }
          packColumns(byLane[lane.id].filter(r=>r.kind==='block').sort(order),o.packGapPx);
        }
        if(!changed)break;
      }
      for(const r of rows){
        const g=geo[r.lane];
        if(r.kind==='dot'){r.x=g.x+Math.max(0,(o.railDotPx-o.dotPx)/2);r.w=o.dotPx}
        else if(r.kind==='bar'){r.x=g.x+g.width-o.laneEdgePx-(r.col+1)*(o.barPx+o.barGapPx)+o.barGapPx;r.w=o.barPx}
        else if(r.kind==='block'){const colW=(g.width-2*o.laneEdgePx)/r.cols;r.x=g.x+o.laneEdgePx+r.col*colW+2;r.w=colW-4}
        else{const colW=(g.textRight-g.textLeft)/r.cols;r.x=g.x+g.textLeft+r.col*colW+2;r.w=colW-4}
      }
      return scale;
    }

    // 1. Besoin de chaque lane, mesuré sur un premier rangement à largeurs égales.
    const available=Math.max(LANES.length*o.emptyLanePx,Number(o.width)||0);
    pass(geometry(LANES.map(()=>available/LANES.length)));
    const need=LANES.map(lane=>{
      const list=byLane[lane.id];
      if(!list.length)return o.emptyLanePx;
      const textCols=Math.min(o.maxNeedCols,Math.max(0,...list.filter(r=>r.kind==='card'||r.kind==='failure').map(r=>r.cols)));
      const blockCols=Math.min(o.maxNeedCols,Math.max(0,...list.filter(r=>r.kind==='block').map(r=>r.cols)));
      const inner=textCols*minText+blockCols*minBlock;
      return Math.max(o.emptyLanePx,railLeft(lane.id)+inner+railRight(lane.id)+(inner?0:o.barPx));
    });
    const total=need.reduce((a,b)=>a+b,0);
    const widths=total>=available?need:need.map(n=>n+(available-total)*n/total);
    // 2. Rangement définitif à ces largeurs.
    const lanes=geometry(widths.map(w=>Math.floor(w)));
    const scale=pass(lanes);
    const entries=rows.sort((a,b)=>a.y0-b.y0||LANE_INDEX[a.lane]-LANE_INDEX[b.lane]||a.col-b.col||cmpStr(a.item.item_id,b.item.item_id));
    const prefixBottom=[],index=new Map();
    let running=-Infinity;
    entries.forEach((e,i)=>{running=Math.max(running,e.bottom);prefixBottom.push(running);index.set(e.item.item_id,i)});
    /* Ordre clavier : le temps (un point est centré sur son instant, pas sur son haut). */
    const order=[...entries].sort((a,b)=>a.ty-b.ty||LANE_INDEX[a.lane]-LANE_INDEX[b.lane]||a.col-b.col||cmpStr(a.item.item_id,b.item.item_id));
    const orderIndex=new Map(order.map((e,i)=>[e.item.item_id,i]));
    const laneCounts=Object.fromEntries(LANES.map(l=>[l.id,byLane[l.id].length]));
    const height=Math.max(scale.ys.length?scale.ys[scale.ys.length-1]:o.padTop,scale.maxBottom,running===-Infinity?0:running)+o.padBottom;
    return {entries,breaks:scale.breaks,height,toY:scale.toY,timeAt:scale.timeAt,anchors:{ts:scale.ts,ys:scale.ys},prefixBottom,index,order,orderIndex,
      laneCounts,lanes,width:lanes.reduce((a,g)=>a+g.width,0),pxPerSecond:pps,openCount:rows.filter(r=>r.open).length};
  }

  /* Entrées qui recoupent [top, bottom] (px du canevas) : recherche binaire sur
     le maximum courant des bas (une longue span commencée plus haut reste
     visible) puis sur les hauts. */
  function visibleRange(model,top,bottom){
    const {entries,prefixBottom}=model;
    let lo=0,hi=entries.length;
    while(lo<hi){const m=(lo+hi)>>1;if(prefixBottom[m]>=top)hi=m;else lo=m+1}
    const first=lo;
    hi=entries.length;
    while(lo<hi){const m=(lo+hi)>>1;if(entries[m].y0<=bottom)lo=m+1;else hi=m}
    const out=[];
    for(let i=first;i<lo;i++)if(entries[i].bottom>=top)out.push(entries[i]);
    return out;
  }

  const TICK_STEPS=[250,500,1000,2000,5000,10000,15000,30000,60000,120000,300000,600000];
  function tickStep(pxPerSecond,minPx=64){
    for(const step of TICK_STEPS)if(step/1000*pxPerSecond>=minPx)return step;
    return TICK_STEPS[TICK_STEPS.length-1];
  }
  /* Graduations visibles : pas régulier dans les segments linéaires, plus un
     repère au début de l'axe et à la reprise après chaque silence replié. */
  function ticks(model,top,bottom,limit=400,minGapPx=26){
    const {ts,ys}=model.anchors,step=tickStep(model.pxPerSecond),gaps=new Set(model.breaks.map(b=>b.from));
    const out=[],seen=new Set();
    const add=(t,y,major)=>{if(y<top||y>bottom||seen.has(t)||out.length>=limit)return;seen.add(t);out.push({t,y,major})};
    if(ts.length)add(ts[0],ys[0],true);
    for(let i=1;i<ts.length&&out.length<limit;i++){
      if(ys[i]<top)continue;
      if(ys[i-1]>bottom)break;
      if(gaps.has(ts[i-1])){add(ts[i],ys[i],true);continue}
      for(let t=Math.ceil(ts[i-1]/step)*step;t<=ts[i]&&out.length<limit;t+=step)add(t,model.toY(t),false);
    }
    /* Une graduation régulière trop proche d'un repère (début, reprise après un
       silence replié) est retirée : les libellés ne se chevauchent jamais. */
    const sorted=out.sort((a,b)=>a.y-b.y||(b.major-a.major)),kept=[];
    for(const t of sorted){
      const clash=kept.length&&t.y-kept[kept.length-1].y<minGapPx;
      if(!clash)kept.push(t);
      else if(t.major&&!kept[kept.length-1].major)kept[kept.length-1]=t;
    }
    return kept;
  }

  /* Navigation clavier : ordre chronologique (haut/bas), lane voisine la plus
     proche dans le temps (gauche/droite). */
  function neighbor(model,id,direction){
    const E=model.order;
    if(!E.length)return null;
    const i=model.orderIndex.has(id)?model.orderIndex.get(id):-1;
    if(direction==='first')return E[0];
    if(direction==='last')return E[E.length-1];
    if(i<0)return E[0];
    if(direction==='next')return E[i+1]||null;
    if(direction==='prev')return E[i-1]||null;
    const cur=E[i],step=direction==='left'?-1:1;
    for(let lane=LANE_INDEX[cur.lane]+step;lane>=0&&lane<LANES.length;lane+=step){
      let best=null;
      for(const e of E)if(e.lane===LANES[lane].id&&(!best||Math.abs(e.ty-cur.ty)<Math.abs(best.ty-cur.ty)))best=e;
      if(best)return best;
    }
    return null;
  }

  /* ------------------------------------------------------ rendu d'une entrée */
  const ICONS=Object.freeze({
    failure:'<path d="M12 3.5 2.8 20h18.4L12 3.5Z"/><path d="M12 10v4M12 17h.01"/>',
  });
  function iconSvg(name){
    return `<svg class="tl-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]||''}</svg>`;
  }
  function laneLabel(id){return (LANES[LANE_INDEX[id]]||{label:id}).label}
  /* Description complète lue par les lecteurs d'écran : la couleur n'est
     jamais le seul porteur de sens. */
  function ariaLabel(entry,now){
    const item=entry.item,parts=[laneLabel(entry.lane),typeLabel(item)];
    if(entry.span||item.status!==statusOf(item.event_type))parts.push(statusLabel(item.status));
    parts.push(`à ${fmtClock(item.started_at)}`);
    if(entry.span)parts.push(`durée ${fmtDuration(durationOf(item,now))}`);
    const note=playbackNote(item);
    if(note)parts.push(note);
    if(item.collapsed.length)parts.push(`${item.collapsed.length+1} publications identiques fusionnées`);
    parts.push(displayText(item));
    if(item.actor!=='user')parts.push('Entrée pour le détail');
    return parts.join(', ');
  }
  const DOT_SHAPES=Object.freeze({'brain.speech.requested':'diamond'});
  const TIP_CHARS=240;
  function entryHtml(entry,{rulerPx=GEOMETRY.rulerPx,now=null,selected=false,found=false,tabindex=-1,blockLinePx=GEOMETRY.linePx,charPx=GEOMETRY.charPx}={}){
    const item=entry.item,tone=toneOf(item),user=item.actor==='user',kind=entry.kind;
    const left=Math.round(rulerPx+entry.x),width=Math.max(8,Math.round(entry.w)),top=Math.round(entry.y0);
    const classes=['tl-e',`tl-${entry.lane}`,`tl-${kind==='bar'?'railbar':kind}`,`is-${tone}`,`st-${item.status}`];
    if(item.actor==='tool')classes.push('tl-tool');
    if(item.visibility===D)classes.push('is-diag');
    if(selected)classes.push('is-selected');
    if(found)classes.push('is-found');
    const note=playbackNote(item);
    if(note&&item.status!=='open')classes.push('is-unheard');
    const tag=user?'div':'button';
    const attrs=user?'role="article"':`type="button" aria-controls="tlDrawer" aria-expanded="${selected}"`;
    const durPx=Math.max(3,Math.round(entry.yEnd-entry.ty));
    const time=escapeHtml(fmtClock(item.started_at)),duration=escapeHtml(fmtDuration(durationOf(item,now)));
    const status=`<span class="tl-st">${escapeHtml(statusLabel(item.status))}</span>`;
    let style,body;
    if(kind==='dot'){
      if(DOT_SHAPES[item.event_type])classes.push(`dot-${DOT_SHAPES[item.event_type]}`);
      style=`top:${top}px;left:${left}px;width:${width}px;height:${Math.round(entry.h)}px`;
      /* Libellé court au survol (au plus TIP_CHARS caractères) ; le texte entier reste dans l'aria-label et le détail. */
      const label=displayText(item),short=label.length>TIP_CHARS?`${label.slice(0,TIP_CHARS)}…`:label;
      body=`<span class="tl-d" aria-hidden="true"></span><span class="tl-tip" aria-hidden="true">${escapeHtml(short)} · ${time}</span>`;
    }else if(kind==='bar'){
      const height=Math.round(entry.h);
      style=`top:${top}px;left:${left}px;width:${width}px;height:${height}px`;
      body=height>40?`<span class="tl-vl" aria-hidden="true">${escapeHtml(displayText(item))} · ${duration}</span>`:'';
    }else if(kind==='block'){
      const height=Math.round(entry.h),cpl=Math.max(4,(width-GEOMETRY.blockPadXPx)/charPx);
      if(durPx<height)classes.push('is-short');
      const name=subagentName(item),desc=subagentDescription(item);
      /* Lignes disponibles d'après la hauteur du bloc : le nom d'abord, puis la
         ligne d'heure et de durée, puis la description dans ce qui reste. */
      const avail=Math.max(1,Math.floor((height-GEOMETRY.blockPadYPx)/blockLinePx));
      const nameLines=Math.min(wrapLines(name,cpl),avail>=2?avail-1:1);
      const meta=avail>=2;
      const descLines=desc?Math.min(wrapLines(desc,cpl),Math.max(0,avail-nameLines-(meta?1:0))):0;
      style=`top:${top}px;left:${left}px;width:${width}px;height:${height}px`;
      body=`<span class="tl-fill" style="height:${Math.min(durPx,height)}px" aria-hidden="true"></span>`
        +`<span class="tl-bn" style="-webkit-line-clamp:${nameLines}">${escapeHtml(name)}</span>`
        +(descLines?`<span class="tl-bd" style="-webkit-line-clamp:${descLines}">${escapeHtml(desc)}</span>`:'')
        +(meta?`<span class="tl-bm"><time>${time}</time> · ${duration} ${status}</span>`:'');
    }else{
      style=`top:${top}px;left:${left}px;width:${width}px;min-height:${Math.round(entry.h)}px`;
      const merged=item.collapsed.length?`<span class="tl-st">×${item.collapsed.length+1}</span>`:'';
      const head=kind==='failure'
        ?`${iconSvg('failure')}<time>${time}</time>`
        :`<time>${time}</time>${entry.span?`<span class="tl-dl">${duration}</span>${status}`:tone!=='ok'?status:''}${item.event_type==='mouth.reflex.started'?'<span class="tl-st tl-kind">réflexe</span>':''}${merged}`;
      const bar=entry.span?`<span class="tl-durbar" style="height:${durPx}px" aria-hidden="true"></span>`:'';
      body=`${bar}<span class="tl-h">${head}</span><span class="tl-t">${escapeHtml(displayText(item))}</span>`;
    }
    return `<${tag} ${attrs} class="${classes.join(' ')}" data-id="${escapeHtml(item.item_id)}" tabindex="${tabindex}" style="${style}" aria-label="${escapeHtml(ariaLabel(entry,now))}">${body}</${tag}>`;
  }

  /* -------------------------------------------------------- erreurs réseau */
  const ERROR_TEXT=Object.freeze({
    core_unreachable:{title:'Core injoignable',hint:'Core est arrêté ou redémarre. Reprise automatique au dernier curseur reçu.'},
    conversation_events_unavailable:{title:'Journal de conversation indisponible',hint:'Stockage de Core en échec, ou Core en cours d’arrêt. Reprise automatique.'},
    control_center_stopping:{title:'Control Center en arrêt',hint:'Relancez le Control Center puis rouvrez la vue.'},
    core_unauthorized:{title:'Jeton de session refusé par Core',hint:'Core vient sans doute de redémarrer ; nouvelle tentative automatique.'},
    core_refused:{title:'Lecture refusée par Core',hint:'Nouvelle tentative automatique.'},
    invalid_core_response:{title:'Réponse de Core hors contrat',hint:'Versions de Core et du Control Center à vérifier. Nouvelle tentative automatique.'},
    invalid_page:{title:'Page reçue hors contrat',hint:'Nouvelle tentative automatique.'},
    network:{title:'Control Center injoignable',hint:'Le serveur de cette page ne répond plus. Nouvelle tentative automatique.'},
    timeout:{title:'Délai dépassé',hint:'Aucune réponse dans le délai. Nouvelle tentative automatique.'},
    http_error:{title:'Erreur du serveur',hint:'Nouvelle tentative automatique.'},
    not_configured:{title:'Vue non reliée à Core',hint:'Ce Control Center n’a pas de lecteur de conversation configuré.'},
    invalid_request:{title:'Requête refusée',hint:'Paramètres refusés par le Control Center.'},
    forbidden_origin:{title:'Origine refusée',hint:'Ouvrez la page depuis http://127.0.0.1 (garde d’origine).'},
    missing_route:{title:'Route de conversation absente',hint:'Ce Control Center ne connaît pas /api/conversations : redémarrez-le après la mise à jour.'},
    trace_busy:{title:'Lectures de trace déjà en cours',hint:'Deux lectures occupent le Control Center ; réessayez dans quelques secondes.'},
    trace_unreadable:{title:'Trace illisible',hint:'Le fichier runtime/trace.jsonl ne se lit pas (voir les erreurs du Control Center).'},
    trace_drill_down_failed:{title:'Lecture de trace en échec',hint:'Erreur inattendue journalisée par le Control Center.'},
    trace_not_applicable:{title:'Pas de trace pour un événement utilisateur',hint:''},
    conversation_event_not_found:{title:'Événement introuvable dans Core',hint:'Absent ou illisible dans le journal de conversation.'},
    transcript_too_large:{title:'Conversation trop longue pour la transcription',hint:'Utilisez « Exporter JSONL » : l’export n’a pas de limite de taille.'},
    export_incomplete:{title:'Export incomplet',hint:'Le flux s’est interrompu avant la ligne finale : rien n’a été enregistré, relancez l’export.'},
    search_busy:{title:'Recherche déjà en cours',hint:'Core n’exécute qu’une recherche à la fois (un autre onglet ?). Réessayez dans un instant.'},
    projection_busy:{title:'Core est occupé',hint:'Deux transcriptions ou exports sont déjà en cours. Réessayez dans un instant.'},
  });
  const RETRYABLE=new Set(['core_unreachable','conversation_events_unavailable','control_center_stopping','core_unauthorized',
    'core_refused','invalid_core_response','invalid_page','network','timeout','http_error','trace_busy']);
  const BLOCKING=new Set(['invalid_request','forbidden_origin','not_configured','missing_route','trace_not_applicable',
    'conversation_event_not_found','trace_unreadable','trace_drill_down_failed','transcript_too_large','export_incomplete',
    'search_busy','projection_busy']);
  function classifyError(error){
    const err=error||{};
    if(err.name==='AbortError'&&!err.timeout)return {aborted:true};
    const status=Number.isInteger(err.status)?err.status:null;
    let code=err.code?String(err.code):'';
    if(!code){
      if(err.timeout||err.name==='TimeoutError')code='timeout';
      else if(status===null)code='network';
      else if(status===404)code='missing_route';
      else if(status===403)code='forbidden_origin';
      else if(status===400)code='invalid_request';
      else code='http_error';
    }
    const text=ERROR_TEXT[code]||{title:`Erreur ${code}${status?` (HTTP ${status})`:''}`,hint:''};
    const retryable=!BLOCKING.has(code)&&(RETRYABLE.has(code)||status===null||status>=500||status===408||status===429);
    return {aborted:false,code,status,retryable,title:text.title,hint:text.hint,message:err.message?String(err.message):''};
  }
  function backoffMs(attempt,maxMs=30000){return Math.min(maxMs,1000*2**Math.max(0,attempt-1))}

  /* Lecture JSON avec délai : un 4xx/5xx n'est jamais une donnée, il lève une
     erreur portant `status`, `code` et le message du serveur. */
  function createFetchJson(fetchImpl,timers={setTimeout:(f,ms)=>setTimeout(f,ms),clearTimeout:id=>clearTimeout(id)}){
    return async function fetchJson(path,{signal=null,timeoutMs=15000}={}){
      const controller=new AbortController();
      let timedOut=false;
      const relay=()=>controller.abort();
      if(signal){if(signal.aborted)controller.abort();else signal.addEventListener('abort',relay,{once:true})}
      const timer=timeoutMs?timers.setTimeout(()=>{timedOut=true;controller.abort()},timeoutMs):null;
      try{
        const response=await fetchImpl(path,{signal:controller.signal,headers:{Accept:'application/json'},cache:'no-store'});
        const raw=await response.text();
        let body=null;
        try{body=raw?JSON.parse(raw):null}catch(parseError){body=null}
        if(!response.ok||!body||typeof body!=='object'||body.ok===false){
          const failure=new Error((body&&body.error)||(raw&&raw.slice(0,200))||`HTTP ${response.status}`);
          failure.status=response.status;
          failure.code=(body&&body.code)||(response.ok?'invalid_page':'');
          throw failure;
        }
        return body;
      }catch(error){
        if(timedOut){
          const late=new Error(`Aucune réponse en ${Math.round(timeoutMs/1000)} s`);
          late.name='TimeoutError';late.timeout=true;late.code='timeout';
          throw late;
        }
        throw error;
      }finally{
        if(timer!==null)timers.clearTimeout(timer);
        if(signal)signal.removeEventListener('abort',relay);
      }
    };
  }

  /* Texte brut (transcription) : même contrat d'erreur que `fetchJson` (un
     4xx/5xx lève avec le code et le message JSON du serveur). */
  function createFetchText(fetchImpl,timers={setTimeout:(f,ms)=>setTimeout(f,ms),clearTimeout:id=>clearTimeout(id)}){
    return async function fetchText(path,{signal=null,timeoutMs=70000}={}){
      const controller=new AbortController();
      let timedOut=false;
      const relay=()=>controller.abort();
      if(signal){if(signal.aborted)controller.abort();else signal.addEventListener('abort',relay,{once:true})}
      const timer=timeoutMs?timers.setTimeout(()=>{timedOut=true;controller.abort()},timeoutMs):null;
      try{
        const response=await fetchImpl(path,{signal:controller.signal,headers:{Accept:'text/plain, application/json'},cache:'no-store'});
        const raw=await response.text();
        if(!response.ok){
          let body=null;
          try{body=raw?JSON.parse(raw):null}catch(parseError){body=null /* argued: a non-JSON error body keeps its raw text as the message */}
          const failure=new Error((body&&body.error)||(raw&&raw.slice(0,200))||`HTTP ${response.status}`);
          failure.status=response.status;failure.code=(body&&body.code)||'';
          throw failure;
        }
        return raw;
      }catch(error){
        if(timedOut){const late=new Error(`Aucune réponse en ${Math.round(timeoutMs/1000)} s`);late.name='TimeoutError';late.timeout=true;late.code='timeout';throw late}
        throw error;
      }finally{
        if(timer!==null)timers.clearTimeout(timer);
        if(signal)signal.removeEventListener('abort',relay);
      }
    };
  }

  /* Flux long (export JSONL) : la réponse n'est rendue que si elle est 2xx ;
     sinon lève comme `fetchJson` (statut, code et message du serveur). */
  function createOpenStream(fetchImpl){
    return async function openStream(path,{signal=null}={}){
      const response=await fetchImpl(path,{signal,cache:'no-store'});
      if(response.ok)return response;
      const raw=await response.text();
      let body=null;
      try{body=raw?JSON.parse(raw):null}catch(parseError){body=null /* argued: a non-JSON error body keeps its raw text as the message */}
      const failure=new Error((body&&body.error)||(raw&&raw.slice(0,200))||`HTTP ${response.status}`);
      failure.status=response.status;failure.code=(body&&body.code)||'';
      throw failure;
    };
  }

  /* ------------------------------------------------ hydratation + long-poll */
  /* Une seule requête en vol par flux (donc une connexion) :
     1. hydratation : pages `wait_ms=0` de `after_sequence=0` tant que `has_more` ;
     2. direct : long-poll `wait_ms` depuis le dernier `next_cursor` reçu ; une
        page `has_more` repasse en rattrapage sans attente ;
     3. erreur réessayable : `reconnecting`, attente exponentielle (1 s → 30 s),
        reprise au dernier `next_cursor` reçu ; erreur bloquante : `blocked`
        jusqu'à `retryNow()`.
     Les lignes sont indexées par `event_id` : une page rejouée n'ajoute rien.
     Une page filtrée vide avec `has_more` est normale : on continue. */
  function createFeed({request,schedule=(fn,ms)=>{const t=setTimeout(fn,ms);return()=>clearTimeout(t)},now=()=>Date.now(),
    pageLimit=500,waitMs=25000,pageTimeoutMs=15000,pollGraceMs=10000,onChange=()=>{}}={}){
    const feed={conversationId:null,phase:'idle',cursor:0,rows:new Map(),version:0,attempt:0,retryAt:null,error:null,
      skippedRows:0,requests:0,hydrated:false,startedAt:null,hydratedAt:null,lastContactAt:null,lastEventAt:null,
      disconnectedAt:null,lastWaitMs:0,listenerError:null,
      /* Partage entre onglets : qui tient le long-poll, et ce que le meneur
         dit de sa lecture. Un suiveur n'a aucune requête longue à montrer —
         mais il doit montrer l'état réel du flux, pas un « en direct » de
         façade pendant que le meneur, lui, se reconnecte. */
      sharedRole:'solo',leaderPhase:null,leaderError:null,leaderAt:null,shortReads:0};
    let generation=0,controller=null,wake=null;
    const emit=(reason,detail)=>{
      try{onChange(feed,reason,detail)}
      catch(error){feed.listenerError=error;if(typeof console!=='undefined')console.error('timeline listener failed',error)}
    };
    const abort=()=>{if(controller){try{controller.abort()}catch(e){/* argued: aborting an already settled request is a no-op */}controller=null}};
    const pause=delay=>new Promise(resolve=>{
      let cancel=null;
      const done=()=>{if(cancel)cancel();if(wake===done)wake=null;resolve()};
      wake=done;
      if(delay!==null)cancel=schedule(done,delay);
    });
    const url=wait=>`/api/conversations/events?conversation_id=${encodeURIComponent(feed.conversationId)}&after_sequence=${feed.cursor}&limit=${pageLimit}${wait?`&wait_ms=${wait}`:''}`;
    function checkPage(page){
      if(!page||!Array.isArray(page.events)||!Number.isInteger(page.next_cursor)||page.next_cursor<feed.cursor||typeof page.has_more!=='boolean'){
        const invalid=new Error('page d’événements hors contrat');invalid.code='invalid_page';throw invalid;
      }
    }
    function merge(page){
      let added=0;
      for(const row of page.events){
        const event=row&&row.event;
        if(!event||typeof event.event_id!=='string'||event.conversation_id!==feed.conversationId||feed.rows.has(event.event_id))continue;
        feed.rows.set(event.event_id,row);added++;
      }
      return added;
    }
    /* `short` : lecture courte et bornée d'un suiveur (jamais de `wait_ms`),
       qui s'arrête dès que le serveur n'a plus rien en réserve. C'est la seule
       requête qu'un suiveur émet — au premier chargement, sur un trou, ou
       quand le meneur se tait. */
    async function loop(mine,{short=false}={}){
      let catchUp=true;
      while(mine===generation){
        const live=!short&&feed.phase==='live'&&!catchUp,wait=live?waitMs:0;
        controller=typeof AbortController!=='undefined'?new AbortController():null;
        feed.requests++;feed.lastWaitMs=wait;
        if(short)feed.shortReads++;
        let page;
        try{
          page=await request(url(wait),{signal:controller?controller.signal:null,timeoutMs:wait+(live?pollGraceMs:pageTimeoutMs)});
          if(mine!==generation)return;
          checkPage(page);
        }catch(error){
          if(mine!==generation)return;
          const info=classifyError(error);
          if(info.aborted)return;
          feed.error={...info,at:now()};
          if(feed.disconnectedAt===null)feed.disconnectedAt=now();
          if(!info.retryable){
            feed.phase='blocked';feed.retryAt=null;emit('blocked');
            await pause(null);
            if(mine!==generation)return;
            feed.phase=feed.hydrated?'catching_up':'hydrating';feed.attempt=0;catchUp=true;emit('retry');
            continue;
          }
          feed.attempt++;
          const delay=backoffMs(feed.attempt);
          feed.retryAt=now()+delay;feed.phase='reconnecting';emit('error');
          await pause(delay);
          if(mine!==generation)return;
          feed.retryAt=null;emit('retrying');
          catchUp=true;
          continue;
        }
        const from=feed.cursor;
        const added=merge(page),recovered=feed.error!==null;
        feed.cursor=page.next_cursor;
        feed.skippedRows+=Number(page.skipped_rows)||0;
        feed.lastContactAt=now();feed.attempt=0;feed.retryAt=null;feed.error=null;feed.disconnectedAt=null;
        if(added){feed.version++;feed.lastEventAt=now()}
        catchUp=page.has_more;
        if(page.has_more)feed.phase=feed.hydrated?'catching_up':'hydrating';
        else{if(!feed.hydrated){feed.hydrated=true;feed.hydratedAt=now()}feed.phase=short?'following':'live'}
        emit(added?'events':recovered?'recovered':'page',{page,added,from,short});
        if(short&&!page.has_more)return;
      }
    }
    /* Repartir sur une conversation. `resume` garde les lignes et le curseur
       déjà tenus : c'est exactement ce dont a besoin un suiveur promu meneur —
       il reprend au dernier `next_cursor` reçu, sans retélécharger la
       conversation et sans trou possible, puisque le serveur rend tout ce qui
       suit cette séquence. */
    function reset(conversationId,{resume=false,phase='hydrating'}={}){
      generation++;abort();if(wake)wake();
      const keep=resume&&feed.conversationId===conversationId;
      Object.assign(feed,{conversationId,phase,cursor:keep?feed.cursor:0,rows:keep?feed.rows:new Map(),
        version:feed.version+1,attempt:0,retryAt:null,error:null,skippedRows:keep?feed.skippedRows:0,
        hydrated:keep?feed.hydrated:false,startedAt:now(),hydratedAt:keep?feed.hydratedAt:null,
        lastContactAt:keep?feed.lastContactAt:null,lastEventAt:keep?feed.lastEventAt:null,disconnectedAt:null});
      return generation;
    }
    return {
      state:feed,
      /* Meneur (ou onglet seul) : hydratation puis long-poll. */
      start(conversationId,{resume=false}={}){
        const mine=reset(conversationId,{resume,phase:resume&&feed.hydrated?'catching_up':'hydrating'});
        emit('start');
        return loop(mine);
      },
      /* Suiveur : une lecture courte et bornée, puis plus rien — les
         événements suivants arrivent par le meneur. */
      follow(conversationId,{resume=false}={}){
        const mine=reset(conversationId,{resume,phase:resume&&feed.hydrated?'catching_up':'hydrating'});
        emit('start');
        return loop(mine,{short:true});
      },
      /* Rattraper maintenant : trou dans le relais, meneur muet, ou retour
         d'un onglet caché. Une seule lecture courte, bornée. */
      resync(){
        if(feed.conversationId===null)return null;
        const mine=reset(feed.conversationId,{resume:true,phase:'catching_up'});
        emit('resync');
        return loop(mine,{short:true});
      },
      /* Une page relayée par le meneur. Rend `applied`, `gap` (des séquences
         manquent entre ce qu'on tient et ce qui arrive : il faut lire),
         `stale` (déjà vu) ou `other` (une autre conversation). */
      ingest(message){
        if(!message||message.conversation_id!==feed.conversationId)return 'other';
        feed.leaderAt=now();
        const incoming=Number(message.cursor);
        if(Number(message.from)>feed.cursor)return 'gap';
        const events=Array.isArray(message.events)?message.events:[];
        if(!events.length&&!(incoming>feed.cursor))return 'stale';
        const from=feed.cursor;
        const added=merge({events});
        if(incoming>feed.cursor)feed.cursor=incoming;
        feed.skippedRows+=Number(message.skipped_rows)||0;
        feed.lastContactAt=now();
        if(added){feed.version++;feed.lastEventAt=now()}
        if(feed.hydrated&&feed.phase!=='paused')feed.phase=message.has_more?'catching_up':'following';
        emit(added?'events':'page',{added,from,shared:true});
        return 'applied';
      },
      /* Onglet caché : la requête en vol est abandonnée et plus rien n'est
         demandé. Au retour, `resync()` rattrape. */
      pause(){generation++;abort();if(wake)wake();feed.phase='paused';emit('pause')},
      setRole(role){if(feed.sharedRole===role)return;feed.sharedRole=role;emit('role')},
      /* Ce que le meneur dit de sa propre lecture : un suiveur affiche l'état
         réel du flux, jamais un « en direct » de façade pendant que le meneur
         se reconnecte. */
      noteLeader(report){
        feed.leaderAt=now();
        feed.leaderPhase=report&&report.phase||null;
        feed.leaderError=report&&report.error||null;
        emit('leader');
      },
      stop(){generation++;abort();if(wake)wake();feed.phase='stopped';feed.leaderPhase=null;feed.leaderError=null;emit('stop')},
      retryNow(){if(wake){wake();return true}return false},
    };
  }

  /* --------------------------------------------- un seul long-poll par profil */
  /* Le problème mesuré : chaque chronologie ouverte tenait son propre
     long-poll. Un navigateur n'accorde qu'environ six connexions par hôte, si
     bien qu'à six chronologies ouvertes `/api/status` passait de 3-7 ms à
     5-14 s et qu'un événement mettait 14 s à atteindre toutes les fenêtres.

     La forme retenue est celle de la scène (Slice 05 de la constellation,
     `control_center_scene_page.js`, approuvée) : un meneur élu par Web Locks,
     et un `BroadcastChannel` pour le relais. Adaptée, pas recopiée — ce flux a
     son propre transport, son propre curseur et ses propres filtres.

     Ce qui est partagé, et pourquoi : `/api/conversations/events` ne prend que
     `conversation_id`, `after_sequence`, `limit` et `wait_ms`. Aucun filtre de
     la page (public/tout, recherche, lanes, zoom, sélection) ne voyage dans la
     requête : ils s'appliquent après, sur `feed.rows`. Deux onglets qui
     regardent la même conversation veulent donc exactement le même flux
     d'octets. On partage le flux brut et chaque onglet en dérive sa vue : le
     canal ne transporte aucun filtre, et un onglet peut filtrer autrement sans
     rien coûter au réseau.

     Le verrou est nommé par conversation : deux onglets sur deux conversations
     différentes gardent chacun leur meneur — c'est irréductible, le serveur ne
     sait pas servir deux conversations en une requête. Le cas courant (tous
     les onglets sur la conversation vivante) ne tient qu'un seul long-poll. */
  const SHARED_CHANNEL='jarvis.timeline';
  const SHARED_MESSAGE_VERSION=1;
  const LOCK_PREFIX='jarvis.timeline.';
  const LEADER_TICK_MS=10000;      // battement du meneur : son silence se voit
  const FOLLOWER_CHECK_MS=5000;    // granularité de la surveillance du suiveur
  const FOLLOWER_SILENCE_MS=35000; // silence toléré ; borne réelle ≈ 40 s
  const RESYNC_MIN_MS=1000;        // deux trous coup sur coup ne font qu'une lecture

  /* Élection du meneur du profil par Web Locks. `decide()` rend une promesse
     résolue quand le rôle est connu : meneur si le verrou est libre, sinon
     suiveur mis en file — le navigateur passe le verrou dès qu'il est rendu,
     y compris quand l'onglet qui le tenait est fermé ou navigue ailleurs.
     Un verrou accordé à un onglet devenu caché ou arrêté est rendu aussitôt. */
  function createLeadership({locks,name,createAbort,onRole,wanted=()=>true,log=()=>{}}){
    const state={held:false,release:null,abort:null};
    function hold(){
      if(!wanted()){state.abort=null;onRole('follower');return Promise.resolve()}
      return new Promise(release=>{state.abort=null;state.held=true;state.release=release;onRole('leader')});
    }
    function queue(){
      const controller=createAbort();
      state.abort=controller;
      locks.request(name,{signal:controller.signal},()=>hold()).catch(error=>{
        if(error&&error.name==='AbortError')return;
        if(state.abort===controller)state.abort=null;
        log('warn','timeline.leader_lock_failed',{error:String(error&&error.message||error)});
      });
    }
    return {
      decide(){
        if(state.held||state.abort)return Promise.resolve();
        return new Promise(resolve=>{
          locks.request(name,{ifAvailable:true},lock=>{
            if(lock){const held=hold();resolve();return held}
            onRole('follower');queue();resolve();
            return undefined;
          }).catch(error=>{log('warn','timeline.leader_lock_failed',{error:String(error&&error.message||error)});resolve()});
        });
      },
      release(){
        if(state.abort){const pending=state.abort;state.abort=null;pending.abort()}
        if(state.release){const release=state.release;state.release=null;release()}
        state.held=false;
      },
      held:()=>state.held,
      queued:()=>!!state.abort,
    };
  }

  /* La machine à états qui relie le flux, le verrou et le canal.
     - `leader`  : tient le seul long-poll et relaie chaque page acceptée, plus
                   un battement portant son curseur et l'état de sa lecture ;
     - `follower`: aucune requête longue ; applique les pages relayées, et ne
                   lit le serveur qu'en lectures courtes bornées — premier
                   chargement, trou, curseur du meneur en avance, meneur muet ;
     - `solo`    : sans Web Locks ni BroadcastChannel (navigateur ancien), le
                   comportement d'avant, un long-poll par onglet.
     Un seul onglet ouvert : `solo` de fait côté réseau — le meneur est seul,
     il tient son long-poll exactement comme avant. */
  function createSharedFeed({feed,locks=null,channel=null,createAbort=()=>new AbortController(),
    now=()=>Date.now(),schedule=(fn,ms)=>{const t=setTimeout(fn,ms);return()=>clearTimeout(t)},log=()=>{}}={}){
    const shared=!!locks&&!!channel&&typeof locks.request==='function';
    const stats={broadcasts:0,received:0,resyncs:0,gaps:0,promotions:0,watchdogReads:0};
    let role=shared?'follower':'solo',conversationId=null,leadership=null;
    let visible=true,stopped=false,heartbeat=null,watchdog=null,lastResyncAt=-Infinity,resyncing=false,followerSince=0;

    const post=message=>{
      if(!channel)return;
      try{channel.postMessage({v:SHARED_MESSAGE_VERSION,...message});stats.broadcasts++}
      catch(error){log('warn','timeline.broadcast_failed',{error:String(error&&error.message||error)})}
    };
    const report=()=>({phase:feed.state.phase,error:feed.state.error,cursor:feed.state.cursor});
    const tick=()=>{if(role==='leader'&&conversationId)post({type:'tick',conversation_id:conversationId,...report()})};

    function stopTimers(){
      if(heartbeat){heartbeat();heartbeat=null}
      if(watchdog){watchdog();watchdog=null}
    }
    function armHeartbeat(){
      if(heartbeat||role!=='leader'||stopped)return;
      heartbeat=schedule(()=>{heartbeat=null;if(role!=='leader'||stopped)return;tick();armHeartbeat()},LEADER_TICK_MS);
    }
    /* Surveillance du suiveur, indépendante de ses propres lectures : un
       meneur muet depuis 35 s vaut une lecture courte, et pas plus d'une par
       tranche de 35 s. Un meneur qui bat ne déclenche jamais rien. */
    function armWatchdog(){
      if(watchdog||role!=='follower'||!visible||stopped||!conversationId)return;
      watchdog=schedule(()=>{
        watchdog=null;
        if(role!=='follower'||!visible||stopped||!conversationId)return;
        /* Le silence se compte depuis le dernier signe du meneur, ou depuis
           l'instant où l'on est devenu suiveur si l'on n'a rien entendu. */
        const silence=now()-Math.max(feed.state.leaderAt||0,followerSince);
        if(silence>=FOLLOWER_SILENCE_MS&&now()-lastResyncAt>=FOLLOWER_SILENCE_MS){
          stats.watchdogReads++;
          log('info','timeline.follower_watchdog',{silent_ms:silence,cursor:feed.state.cursor});
          resync('watchdog');
        }
        armWatchdog();
      },FOLLOWER_CHECK_MS);
    }

    function resync(reason){
      if(stopped||!conversationId||!visible||resyncing||!feed.state.conversationId)return null;
      /* Une lecture est déjà en vol : elle part du curseur tenu, donc elle
         couvre le trou. En lancer une seconde ne ferait que doubler la
         requête qu'on cherche justement à économiser. */
      if(['hydrating','catching_up'].includes(feed.state.phase))return null;
      if(now()-lastResyncAt<RESYNC_MIN_MS)return null;
      lastResyncAt=now();resyncing=true;stats.resyncs++;
      log('info','timeline.resync',{reason,cursor:feed.state.cursor});
      const done=()=>{resyncing=false;armWatchdog()};
      const running=feed.resync();
      if(running&&typeof running.then==='function')running.then(done,done);else done();
      return running;
    }

    function becomeLeader(){
      if(role==='leader')return;
      role='leader';stats.promotions++;stopTimers();
      feed.setRole('leader');
      log('info','timeline.leader',{conversation_id:conversationId});
      if(conversationId)feed.start(conversationId,{resume:true});
      tick();armHeartbeat();
    }
    function becomeFollower(){
      const was=role;
      role='follower';stopTimers();followerSince=now();
      feed.setRole('follower');
      if(!conversationId||!visible)return;
      if(was==='leader')post({type:'bye',conversation_id:conversationId});
      /* La lecture de rattrapage part d'abord : le « bonjour » ci-dessous fait
         répondre le meneur tout de suite, et il ne doit pas trouver un flux
         encore à l'arrêt — il déclencherait une seconde lecture pour rien. */
      feed.follow(conversationId,{resume:true});
      /* Un suiveur qui arrive demande au meneur où il en est : sans cela il
         attendrait le prochain battement pour le savoir. */
      post({type:'hello',conversation_id:conversationId});
      armWatchdog();
    }

    function elect(){
      if(!shared||stopped||!conversationId)return Promise.resolve();
      if(leadership)leadership.release();
      leadership=createLeadership({locks,name:LOCK_PREFIX+conversationId,createAbort,log,
        wanted:()=>!stopped&&visible&&!!conversationId,
        onRole:next=>{if(next==='leader')becomeLeader();else becomeFollower()}});
      return leadership.decide();
    }

    return {
      mode:shared?'shared':'solo',
      stats,
      view(){return {mode:shared?'shared':'solo',role,conversationId,visible,
        leader:!!(leadership&&leadership.held()),queued:!!(leadership&&leadership.queued()),stats:{...stats}}},
      /* Suivre une conversation : c'est ici qu'on décide qui tient le
         long-poll. Sans partage possible, le comportement d'avant. */
      watch(id){
        conversationId=id;stopped=false;
        if(!shared){role='solo';feed.setRole('solo');feed.start(id);return Promise.resolve()}
        if(!visible){feed.setRole('follower');feed.pause();return Promise.resolve()}
        return elect();
      },
      /* Onglet caché : la conduite est rendue tout de suite — un autre onglet
         visible prend le relais — et plus rien n'est demandé ici. */
      setVisible(next){
        if(next===visible)return Promise.resolve();
        visible=next;
        if(!shared||!conversationId)return Promise.resolve();
        if(!visible){
          if(role==='leader')post({type:'bye',conversation_id:conversationId});
          if(leadership)leadership.release();
          role='follower';stopTimers();feed.setRole('follower');feed.pause();
          return Promise.resolve();
        }
        return elect();
      },
      /* Un message du canal. Rien de ce qui arrive n'est cru sur parole : une
         page dont le début dépasse notre curseur est un trou, pas une page. */
      handleMessage(message){
        if(stopped||!shared||!message||message.v!==SHARED_MESSAGE_VERSION)return 'ignored';
        if(message.conversation_id!==conversationId)return 'other';
        stats.received++;
        if(message.type==='hello'){if(role==='leader')tick();return 'hello'}
        /* Le meneur s'en va. Un suiveur est déjà en file sur le verrou : le
           navigateur le lui passe tout seul, il n'y a rien à redemander. On ne
           relance une élection que si, pour une raison quelconque, cet onglet
           n'est pas en file — sinon on paierait une lecture pour rien. */
        if(message.type==='bye'){
          if(role!=='leader'&&!(leadership&&leadership.queued()))elect();
          armWatchdog();
          return 'bye';
        }
        if(role==='leader')return 'ignored';
        if(message.type==='tick'){
          feed.noteLeader(message);
          if(Number(message.cursor)>feed.state.cursor)resync('tick-ahead');
          armWatchdog();
          return 'tick';
        }
        if(message.type!=='page')return 'ignored';
        const verdict=feed.ingest(message);
        if(verdict==='gap'){stats.gaps++;resync('gap')}
        armWatchdog();
        return verdict;
      },
      /* Appelé par la page à chaque changement du flux : le meneur relaie. */
      observe(state,reason,detail){
        if(role!=='leader'||!conversationId)return;
        if((reason==='events'||reason==='page'||reason==='recovered')&&detail&&detail.page){
          post({type:'page',conversation_id:conversationId,from:detail.from,cursor:state.cursor,
            events:detail.page.events||[],has_more:!!detail.page.has_more,
            skipped_rows:Number(detail.page.skipped_rows)||0});
          return;
        }
        if(['start','error','retry','retrying','blocked','stop','resync'].includes(reason))tick();
      },
      /* « Réessayer » : le meneur relance sa lecture, un suiveur rattrape. */
      retryNow(){
        if(role==='follower'&&shared){lastResyncAt=-Infinity;resync('manual');return true}
        return feed.retryNow();
      },
      stop(){
        stopped=true;stopTimers();
        if(shared&&role==='leader'&&conversationId)post({type:'bye',conversation_id:conversationId});
        if(leadership)leadership.release();
        leadership=null;conversationId=null;role=shared?'follower':'solo';
        feed.stop();
      },
    };
  }

  /* ----------------------------------------------------------------- statut */
  function ago(ms){return ms===null||ms===undefined?'':fmtDuration(Math.max(0,ms)).replace(/,\d+ s$/,' s').replace(/^\d+ ms$/,'0 s')}
  function plural(n,one,many){return `${n.toLocaleString('fr-FR')} ${n>1?many:one}`}
  /* Ce que dit la pastille d'état, à chaque seconde : qu'il se passe quelque
     chose, quoi, depuis combien de temps, et comment en sortir. */
  function statusView(feed,conversations,now){
    const c=conversations||{};
    if(!feed.conversationId){
      if(c.loading)return {tone:'busy',label:'Chargement des conversations',detail:ago(now-(c.startedAt||now)),retry:false};
      if(c.error)return {tone:'bad',label:c.error.title,detail:[c.error.message,c.error.hint].filter(Boolean).join(' · '),retry:true};
      return {tone:'muted',label:'Aucune conversation',detail:'',retry:false};
    }
    const n=plural(feed.rows.size,'événement','événements');
    /* Suiveur : le flux vit dans un autre onglet du même profil. On dit d'où
       vient la fraîcheur, et on n'invente pas « en direct » quand le meneur
       annonce qu'il se reconnecte ou qu'il est bloqué. */
    if(feed.sharedRole==='follower'&&['following','live','catching_up'].includes(feed.phase)){
      const trouble=feed.leaderError||null;
      if(feed.leaderPhase==='blocked'&&trouble)return {tone:'bad',label:trouble.title||'Bloqué',
        detail:[trouble.message,'relayé par un autre onglet'].filter(Boolean).join(' · '),hint:trouble.hint||'',retry:true};
      if(feed.leaderPhase==='reconnecting'&&trouble)return {tone:'warn',label:trouble.title||'Reconnexion',
        detail:[trouble.message,'relayé par un autre onglet'].filter(Boolean).join(' · '),hint:trouble.hint||'',retry:true};
      const freshness=feed.lastEventAt?`dernier reçu il y a ${ago(now-feed.lastEventAt)}`:'en attente';
      return {tone:'live',label:'En direct',detail:`${n} · ${freshness} · relayé par un autre onglet`,retry:false};
    }
    switch(feed.phase){
      case 'following':return {tone:'live',label:'En direct',detail:`${n} · relayé par un autre onglet`,retry:false};
      case 'paused':return {tone:'muted',label:'En pause',detail:`${n} · onglet en arrière-plan`,retry:false};
      case 'hydrating':return {tone:'busy',label:'Chargement',detail:`${n} · ${ago(now-(feed.startedAt||now))}`,retry:false};
      case 'catching_up':return {tone:'busy',label:'Rattrapage',detail:n,retry:false};
      case 'live':return {tone:'live',label:'En direct',detail:feed.lastEventAt?`${n} · dernier reçu il y a ${ago(now-feed.lastEventAt)}`:`${n} · en attente`,retry:false};
      case 'reconnecting':{
        const e=feed.error||{},left=Math.max(0,Math.ceil(((feed.retryAt||now)-now)/1000));
        const next=feed.retryAt===null?`nouvelle tentative en cours (essai ${feed.attempt+1})`:`nouvelle tentative dans ${left} s (essai ${feed.attempt})`;
        return {tone:'warn',label:e.title||'Reconnexion',detail:[e.message,next,
          feed.disconnectedAt?`coupé depuis ${ago(now-feed.disconnectedAt)}`:''].filter(Boolean).join(' · '),hint:e.hint||'',retry:true};
      }
      case 'blocked':{const e=feed.error||{};return {tone:'bad',label:e.title||'Bloqué',detail:[e.message,e.hint].filter(Boolean).join(' · '),retry:true}}
      case 'stopped':return {tone:'muted',label:'Arrêté',detail:'',retry:false};
      default:return {tone:'muted',label:'En attente',detail:'',retry:false};
    }
  }
  /* État vide ou partiel du canevas ; null quand il y a quelque chose à montrer. */
  function emptyView({feed,conversations,total,visible,mode}){
    const c=conversations||{};
    if(!feed.conversationId){
      if(c.error)return {tone:'bad',title:c.error.title,body:[c.error.message,c.error.hint].filter(Boolean).join(' · ')};
      if(c.loading||!c.loadedAt)return {tone:'busy',title:'Chargement des conversations…',body:''};
      return {tone:'muted',title:'Aucune conversation enregistrée',body:'Parlez à Jarvis : chaque tour, parole, travail du Brain et sous-agent apparaît ici en direct, sur un même axe de temps.'};
    }
    if(total===0){
      if(!feed.hydrated){
        if(feed.phase==='blocked'||feed.phase==='reconnecting')return {tone:feed.phase==='blocked'?'bad':'warn',title:(feed.error&&feed.error.title)||'Lecture impossible',body:(feed.error&&feed.error.hint)||''};
        return {tone:'busy',title:'Chargement de la conversation…',body:''};
      }
      return {tone:'muted',title:'Cette conversation n’a encore aucun événement',body:'Les nouveaux événements s’ajouteront ici sans recharger la page.'};
    }
    if(visible===0&&mode==='public')return {tone:'muted',title:'Aucun événement public',body:`${plural(total,'élément diagnostique est masqué','éléments diagnostiques sont masqués')} par le filtre « Public ».`,action:'all'};
    return null;
  }

  /* ------------------------------------------------------------ détail/trace */
  const ATTRIBUTE_LABELS=Object.freeze({status:'Statut fournisseur',reason:'Raison',code:'Code',error_class:'Classe d’erreur',
    played_ms:'Entendu',duration_ms:'Durée mesurée',model:'Modèle',subagent_type:'Type de sous-agent',tokens:'Jetons',
    tool_uses:'Outils utilisés',tool_name:'Outil',provider:'Fournisseur',background:'Arrière-plan',depth:'Profondeur',
    kind:'Nature',priority:'Priorité',output_id:'Sortie audio',delivery:'Livraison',source:'Source',addressing:'Adresse',
    duplicate:'Doublon',revision:'Révision',interrupted_speech_id:'Parole interrompue',job_id:'Job',arguments_redacted:'Arguments masqués'});
  function attributeValue(key,value){
    if(key==='played_ms'||key==='duration_ms')return Number.isFinite(value)?fmtDuration(value):String(value);
    if(typeof value==='boolean')return value?'oui':'non';
    if(Array.isArray(value))return value.join(', ');
    return String(value);
  }
  function eventRole(item,event){
    if(item.collapsed.some(c=>c.events.includes(event)))return 'publication fusionnée';
    if(event===item.open)return 'ouverture';
    if(event===item.close)return item.open?'clôture':'clôture sans ouverture';
    if(event.event_id===item.item_id)return 'instant';
    return 'doublon écarté';
  }
  const ANOMALY_LABELS=Object.freeze({duplicate_span_open:'Ouverture en double (la plus ancienne gardée)',
    duplicate_span_close:'Clôture en double (la plus ancienne gardée)',close_before_open:'Clôture antérieure à l’ouverture (ramenée au début)',
    conflicting_duplicate:'Deux copies différentes du même événement (la première gardée)'});
  /* Contexte de navigation : événement → élément, premier tour utilisateur par
     corrélation, enfants par `parent_event_id`. */
  function indexItems(items){
    const byEvent=new Map(),byItem=new Map(),userByCorrelation=new Map(),children=new Map();
    for(const item of items){
      byItem.set(item.item_id,item);
      for(const e of item.events)byEvent.set(e.event_id,item);
      if(item.actor==='user'&&item.correlation_id!==null&&!userByCorrelation.has(item.correlation_id))userByCorrelation.set(item.correlation_id,item);
    }
    for(const item of items)for(const e of item.events){
      if(!e.parent_event_id)continue;
      const list=children.get(e.parent_event_id)||[];
      if(!list.includes(item))list.push(item);
      children.set(e.parent_event_id,list);
    }
    return {byEvent,byItem,userByCorrelation,children};
  }
  function detailModel(item,context,{now=null,sequences=null}={}){
    const ctx=context||indexItems([item]);
    const duration=durationOf(item,now);
    const timing=[['Début',fmtClock(item.started_at)]];
    if(isSpan(item)){timing.push(['Fin',item.ended_at===null?'en cours':fmtClock(item.ended_at)]);timing.push(['Durée',item.ended_at===null?'en cours':fmtDuration(duration)])}
    const user=item.actor!=='user'&&item.correlation_id!==null?ctx.userByCorrelation.get(item.correlation_id):null;
    if(user)timing.push(['Depuis la parole utilisateur',`+${fmtDuration(item.started_at-user.started_at)}`]);
    const parentId=item.parent_event_id,parentItem=parentId?ctx.byEvent.get(parentId)||null:null;
    if(parentItem&&parentItem.item_id!==item.item_id)timing.push([`Depuis « ${typeLabel(parentItem)} »`,`+${fmtDuration(item.started_at-parentItem.started_at)}`]);
    const outcome=Object.keys(ATTRIBUTE_LABELS).filter(k=>item.attributes[k]!==undefined&&item.attributes[k]!==null)
      .map(k=>[ATTRIBUTE_LABELS[k],attributeValue(k,item.attributes[k])]);
    const kids=new Map();
    for(const e of item.events)for(const child of ctx.children.get(e.event_id)||[])if(child.item_id!==item.item_id)kids.set(child.item_id,child);
    return {
      item_id:item.item_id,lane:laneOf(item),who:laneLabel(laneOf(item)),what:typeLabel(item),
      title:item.actor==='subagent'?subagentName(item):typeLabel(item),
      status:{raw:item.status,label:statusLabel(item.status),tone:toneOf(item)},
      text:item.actor==='subagent'?item.text:displayText(item),note:playbackNote(item),
      visibility:item.visibility,timing,outcome,
      anomalies:item.anomalies.map(a=>{const i=a.indexOf(':');const code=a.slice(0,i);return {code,event_id:a.slice(i+1),label:ANOMALY_LABELS[code]||code}}),
      collapsed:item.collapsed.length,
      parent:parentId?{event_id:parentId,item_id:parentItem?parentItem.item_id:null,label:parentItem?`${laneLabel(laneOf(parentItem))} · ${typeLabel(parentItem)}`:null}:null,
      children:[...kids.values()].map(c=>({item_id:c.item_id,label:`${laneLabel(laneOf(c))} · ${typeLabel(c)} · ${fmtClock(c.started_at)}`})),
      agent_task:item.actor==='subagent'&&item.task_id?item.task_id:null,
      events:item.events.map(e=>({event_id:e.event_id,event_type:e.event_type,role:eventRole(item,e),producer:e.producer,
        visibility:e.visibility,occurred_at:e.occurred_at,started_at:e.started_at,ended_at:e.ended_at,
        sequence:sequences&&sequences.has(e.event_id)?sequences.get(e.event_id):null,
        ids:ID_FIELDS.filter(f=>e[f]!==null&&e[f]!==undefined).map(f=>[f,e[f]]),
        attributes:Object.entries(e.attributes||{}),trace_ref:e.trace_ref||null,drillable:e.actor!=='user'})),
    };
  }
  const STOPPED_BY=Object.freeze({file_start:'début du fichier atteint',window_start:'fenêtre de ±15 min autour de l’événement parcourue',
    max_bytes:'budget d’octets épuisé (lecture tronquée)',max_lines:'budget de lignes épuisé (lecture tronquée)',
    max_matches:'nombre maximal de correspondances atteint',missing_file:'fichier de trace absent'});
  function traceModel(payload,error){
    if(error){
      const info=error.code!==undefined&&error.retryable!==undefined?error:classifyError(error);
      if(info.code==='trace_not_applicable')return {state:'none',title:info.title,detail:''};
      return {state:'error',title:info.title,detail:[info.message,info.hint].filter(Boolean).join(' · '),retry:true,code:info.code};
    }
    const p=payload||{},scan=p.scan||null;
    const stats=scan?[`${plural(Number(scan.scanned_lines)||0,'ligne lue','lignes lues')}`,STOPPED_BY[scan.stopped_by]||scan.stopped_by,
      scan.corrupt_lines?`${scan.corrupt_lines} illisible(s)`:'',scan.oversized_lines?`${scan.oversized_lines} trop longue(s)`:''].filter(Boolean).join(' · '):'';
    const agentTask=p.agent_task&&p.agent_task.task_id?{task_id:p.agent_task.task_id,trace_url:p.agent_task.trace_url}:null;
    const base={agent_task:agentTask,journal_kind:p.trace_ref?p.trace_ref.journal_kind:null,truncated:!!(scan&&scan.truncated),stats};
    switch(p.status){
      case 'found':return {...base,state:'found',title:plural(scan.entries.length,'ligne de trace jointe','lignes de trace jointes'),
        entries:scan.entries.map(e=>({ts:e.ts,kind:e.kind,level:e.level,message:e.message,message_redacted:!!e.message_redacted,
          data:Object.entries(e.data||{}),redacted:Number(e.redacted_key_count)||0}))};
      case 'not_found':return {...base,state:'empty',title:'Aucune ligne de trace jointe',entries:[]};
      case 'no_trace_ref':return {...base,state:agentTask?'agent_task':'none',title:'Le producteur n’écrit pas de ligne de trace pour ce fait',entries:[]};
      case 'agent_task':return {...base,state:'agent_task',title:'Trace de la tâche dans le panneau Agents',entries:[]};
      default:return {...base,state:'error',title:'Réponse de trace inattendue',detail:String(p.status||''),retry:true,entries:[]};
    }
  }

  /* ------------------------------ transcription, export, recherche (Slice 06) */
  /* Un seul moteur de rendu : la transcription et l'export sont produits par Core
     (Python, `conversation_transcript.py` / `conversation_event_export.py`). La
     page les demande, les montre et les télécharge ; elle ne réécrit rien. */
  const EXPORT_FORMAT='jarvis.conversation-events.export';
  const SEARCH_LIMIT=20,SEARCH_MAX_CHARS=200;
  /* Décalage local du navigateur, en minutes (UTC+02:00 → 120) : Core écrit les heures
     de la transcription dans ce fuseau et le dit dans l'en-tête. */
  function localOffsetMinutes(date=new Date()){return -date.getTimezoneOffset()}
  function offsetLabel(minutes){
    if(!minutes)return 'UTC';
    const a=Math.abs(minutes),p=n=>String(n).padStart(2,'0');
    return `UTC${minutes>0?'+':'-'}${p(Math.floor(a/60))}:${p(a%60)}`;
  }
  function transcriptUrl(conversationId,mode,utcOffsetMinutes=0){
    const offset=Number.isInteger(utcOffsetMinutes)?utcOffsetMinutes:0;
    return `/api/conversations/transcript?conversation_id=${encodeURIComponent(conversationId)}&mode=${mode==='detailed'?'detailed':'plain'}&utc_offset_minutes=${offset}`;
  }
  function exportUrl(conversationId){return `/api/conversations/export?conversation_id=${encodeURIComponent(conversationId)}`}
  function searchUrl({q,conversationId=null,beforeSequence=null,limit=SEARCH_LIMIT}){
    const params=[`q=${encodeURIComponent(q)}`,`limit=${limit}`];
    if(conversationId)params.push(`conversation_id=${encodeURIComponent(conversationId)}`);
    if(Number.isInteger(beforeSequence))params.push(`before_sequence=${beforeSequence}`);
    return `/api/conversations/search?${params.join('&')}`;
  }
  /* Même règle que `export_filename` (Python), testée à l'identique. */
  /* FNV-1a 32 bits des octets UTF-8, en 8 chiffres hexadécimaux (même calcul que Python). */
  function fnv1a(text){
    let h=0x811c9dc5;
    for(const byte of new TextEncoder().encode(String(text))){h^=byte;h=Math.imul(h,0x01000193)>>>0}
    return h.toString(16).padStart(8,'0');
  }
  function fileStem(conversationId){
    const id=String(conversationId);
    const mapped=Array.from(id).map(c=>/^[A-Za-z0-9._-]$/.test(c)?c:'_').join('');
    const stem=mapped.slice(0,80).replace(/^[._]+|[._]+$/g,'');
    /* Deux ids qui ne diffèrent que par des caractères remplacés gardent des noms distincts. */
    return `conversation-${stem||'sans-id'}${mapped===id?'':`-${fnv1a(id)}`}`;
  }
  function exportFilename(conversationId){return `${fileStem(conversationId)}.events.jsonl`}
  function transcriptFilename(conversationId,mode){return `${fileStem(conversationId)}.transcription${mode==='detailed'?'-detaillee':''}.txt`}
  function fmtBytes(n){
    const v=Math.max(0,Number(n)||0);
    if(v<1024)return `${v} o`;
    if(v<1048576)return `${(v/1024).toFixed(1).replace('.',',')} Ko`;
    return `${(v/1048576).toFixed(1).replace('.',',')} Mo`;
  }
  /* Dernière ligne d'un export : la ligne finale prouve qu'il est complet. */
  function exportSummary(tailText){
    const lines=String(tailText||'').split('\n').filter(l=>l.trim());
    const last=lines.length?lines[lines.length-1]:'';
    let record=null;
    try{record=JSON.parse(last)}catch(e){record=null /* argued: a torn last line is exactly an incomplete export */}
    const counts=record&&record.counts;
    if(record&&record.format===EXPORT_FORMAT&&record.complete===true&&counts&&Number.isInteger(counts.events)&&Number.isInteger(counts.skipped_rows))
      return {complete:true,events:counts.events,skippedRows:counts.skipped_rows};
    return {complete:false,events:null,skippedRows:null};
  }
  function searchQueryProblem(q){
    const text=String(q??'');
    if(!text.trim())return 'Saisissez au moins un mot.';
    if(Array.from(text).length>SEARCH_MAX_CHARS)return `${SEARCH_MAX_CHARS} caractères au plus.`;
    return null;
  }
  const ACTOR_LABELS=Object.freeze({user:'Utilisateur',mouth:'Jarvis · voix',brain:'Brain',subagent:'Sous-agent',tool:'Outil',system:'Système'});
  const MATCHED_LABELS=Object.freeze({content:'texte',event_type:'type',actor:'acteur'});
  /* Extrait surligné : `marks` sont des positions en points de code (Python),
     donc découpées sur `Array.from`, jamais sur les unités UTF-16. */
  function snippetHtml(snippet,marks){
    const chars=Array.from(String(snippet||'')),out=[];
    let at=0;
    for(const [start,end] of (Array.isArray(marks)?marks:[])){
      if(!Number.isInteger(start)||!Number.isInteger(end)||start<at||end<=start||end>chars.length)continue;
      out.push(escapeHtml(chars.slice(at,start).join('')),`<mark>${escapeHtml(chars.slice(start,end).join(''))}</mark>`);
      at=end;
    }
    out.push(escapeHtml(chars.slice(at).join('')));
    return out.join('');
  }
  /* Jour local (comme fmtClock), jamais le jour UTC : 00:30 à Paris reste le bon jour. */
  function localDay(ms){
    const d=new Date(ms),p=n=>String(n).padStart(2,'0');
    return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`;
  }
  function hitView(hit,{currentConversationId=null}={}){
    const at=timeMs(hit.occurred_at);
    const matched=(hit.matched||[]).map(f=>MATCHED_LABELS[f]||String(f).replace(/^attributes\./,''));
    return {event_id:hit.event_id,conversation_id:hit.conversation_id,visibility:hit.visibility,
      who:ACTOR_LABELS[hit.actor]||hit.actor,what:typeLabel({event_type:hit.event_type}),
      when:at===null?'—':fmtClock(at,{millis:false}),day:at===null?'':localDay(at),
      elsewhere:!!currentConversationId&&hit.conversation_id!==currentConversationId,
      conversation:String(hit.conversation_id),matched:matched.join(', '),snippet:snippetHtml(hit.snippet,hit.marks)};
  }
  /* Ce que dit la zone de recherche : ce qui se passe, depuis quand, comment en sortir. */
  /* Les panneaux ne relancent rien d'eux-mêmes : une indication qui promet une
     « reprise automatique » (écrite pour le flux direct) est remplacée. */
  function panelHint(error){
    const hint=String((error&&error.hint)||'');
    const kept=hint.split(/(?<=\.)\s+/).filter(sentence=>sentence&&!/automatique/i.test(sentence)).join(' ');
    return /automatique/i.test(hint)?[kept,'Rien ne se relance tout seul ici : utilisez « Réessayer ».'].filter(Boolean).join(' '):hint;
  }
  function searchStateView(search,now){
    const s=search||{};
    if(s.loading)return {tone:'busy',text:`Recherche en cours · ${ago(now-(s.startedAt||now))}`,cancel:true};
    if(s.error)return {tone:'bad',text:s.error.title,detail:[s.error.message,panelHint(s.error)].filter(Boolean).join(' · '),retry:true};
    if(!s.done)return {tone:'muted',text:'Texte dit ou montré, identifiants, types et codes d’état. Jamais la trace ni le diagnostic privé.'};
    const n=(s.hits||[]).length,parts=[n?plural(n,'résultat','résultats'):'Aucun résultat'];
    if(s.scanLimited)parts.push(`recherche arrêtée après ${plural(s.scanned||0,'événement parcouru','événements parcourus')}`);
    if(s.skippedRows)parts.push(`${plural(s.skippedRows,'ligne illisible ignorée','lignes illisibles ignorées')}`);
    return {tone:n?'ok':'muted',text:parts.join(' · '),more:!!s.hasMore};
  }
  /* État d'une transcription ou d'un export : en cours (quoi, depuis quand,
     combien reçu, Annuler), échec (cause réelle, Réessayer) ou résultat. */
  function jobStateView(kind,job,now){
    const j=job||{},since=ago(now-(j.startedAt||now));
    if(j.loading){
      const text=kind==='export'?`Export en cours · ${fmtBytes(j.received||0)} reçus · ${since}`:`Transcription rendue par Core… · ${since}`;
      return {tone:'busy',text,cancel:true};
    }
    if(j.error)return {tone:'bad',text:j.error.title,detail:[j.error.message,panelHint(j.error)].filter(Boolean).join(' · '),retry:true};
    if(!j.done)return {tone:'muted',text:kind==='export'?'Aucun export lancé.':'Aucune transcription chargée.'};
    if(kind==='export'){
      if(j.events===0)return {tone:'muted',text:'Aucun événement dans cette conversation : aucun fichier enregistré.',retry:true};
      const skipped=j.skippedRows?` · ${plural(j.skippedRows,'ligne illisible ignorée','lignes illisibles ignorées')} par Core`:'';
      return {tone:'ok',text:`Export complet : ${plural(j.events||0,'événement','événements')}${skipped} · ${fmtBytes(j.received||0)} · ${j.filename}`,retry:true};
    }
    const lines=String(j.text||'').split('\n').filter(Boolean).length;
    return {tone:'ok',text:`${plural(lines,'ligne','lignes')} · ${fmtBytes(j.bytes||0)} · rendue en ${fmtDuration(j.elapsedMs||0)}`,retry:true};
  }
  /* Échec d'un export : une fois des octets reçus, toute coupure (réseau, délai,
     ligne finale absente) est un export incomplet, rien n'est enregistré ; avant,
     l'erreur du serveur est montrée telle quelle. */
  function exportFailure(error,{received=0,timedOut=false}={}){
    const base=timedOut?Object.assign(new Error('Aucune donnée reçue depuis 30 s'),{code:'timeout',timeout:true}):error;
    const info=classifyError(base);
    if(info.aborted)return {aborted:true,title:'Export annulé',message:'',hint:''};
    if(received>0&&info.code!=='export_incomplete'){
      return {...classifyError({code:'export_incomplete'}),
        message:`Flux interrompu après ${fmtBytes(received)} reçus (${info.message||info.title}). Aucun fichier enregistré.`};
    }
    return info;
  }
  /* « ↓ N nouveaux » : ne compte que des entrées arrivées après une hydratation déjà
     vue pour la même conversation (la dernière page d'un changement ou d'un saut
     n'est pas « nouvelle ») ; suivre le bas remet le compteur à zéro. */
  function trackNewEntries(memo,{conversationId,hydrated,follow,visibleCount,previousCount}){
    const liveBefore=memo.liveConversation===conversationId;
    let pending=memo.pending||0;
    if(!follow&&liveBefore&&visibleCount>previousCount&&previousCount>0)pending+=visibleCount-previousCount;
    if(follow)pending=0;
    return {pending,liveConversation:hydrated?conversationId:null};
  }
  /* Élément de la chronologie qui porte un événement (fusionné compris), ou null. */
  function itemForEvent(ctx,eventId){return ctx&&ctx.byEvent?ctx.byEvent.get(eventId)||null:null}

  return {SPECS,SPAN_OPENER,ANOMALY,LANES,LANE_INDEX,GEOMETRY,DEFAULT_PPS,ERROR_TEXT,readableEvents,reconstruct,toRow,collapseMessages,filterItems,
    laneOf,isSpan,entryKind,displayText,typeLabel,statusLabel,toneOf,playbackNote,fmtDuration,fmtClock,durationOf,
    wrapLines,cardHeight,subagentName,layout,visibleRange,tickStep,ticks,neighbor,entryHtml,ariaLabel,iconSvg,escapeHtml,classifyError,backoffMs,
    createFetchJson,createFetchText,createOpenStream,createFeed,createLeadership,createSharedFeed,statusView,emptyView,indexItems,detailModel,traceModel,
    SHARED_CHANNEL,SHARED_MESSAGE_VERSION,LOCK_PREFIX,LEADER_TICK_MS,FOLLOWER_CHECK_MS,FOLLOWER_SILENCE_MS,
    EXPORT_FORMAT,SEARCH_LIMIT,SEARCH_MAX_CHARS,transcriptUrl,exportUrl,searchUrl,exportFilename,transcriptFilename,fmtBytes,
    exportSummary,searchQueryProblem,snippetHtml,hitView,searchStateView,jobStateView,itemForEvent,
    localOffsetMinutes,offsetLabel,localDay,fnv1a,exportFailure,trackNewEntries,panelHint};
})();

/* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
if(typeof module!=='undefined'&&module.exports)module.exports=JarvisTimelineCore;

/* --------------------------------------------------------------------------
   Bloc navigateur : vue plein écran, flux direct, panneau de détail.
   Les tests node ne l'exécutent pas.
   -------------------------------------------------------------------------- */
(function installJarvisTimeline(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const T=JarvisTimelineCore;
  const root=document.getElementById('timeline');
  if(!root)return;
  const q=s=>root.querySelector(s);
  const el={
    open:document.getElementById('openTimeline'),close:q('#tlClose'),conv:q('#tlConversation'),session:q('#tlSession'),
    sessionWrap:q('#tlSessionWrap'),zoom:q('#tlZoom'),status:q('#tlStatus'),statusLabel:q('#tlStatusLabel'),
    statusDetail:q('#tlStatusDetail'),retry:q('#tlRetry'),notice:q('#tlNotice'),main:q('#tlMain'),scroll:q('#tlScroll'),
    heads:q('#tlHeads'),canvas:q('#tlCanvas'),grid:q('#tlGrid'),ruler:q('#tlRuler'),breaks:q('#tlBreaks'),items:q('#tlItems'),
    empty:q('#tlEmpty'),newPill:q('#tlNew'),drawer:q('#tlDrawer'),drawerTitle:q('#tlDrawerTitle'),
    drawerBody:q('#tlDrawerBody'),drawerClose:q('#tlDrawerClose'),announce:q('#tlAnnounce'),
    searchOpen:q('#tlSearchOpen'),transcriptOpen:q('#tlTranscriptOpen'),exportOpen:q('#tlExportOpen'),
  };
  const fetchJson=T.createFetchJson(window.fetch.bind(window));
  const fetchText=T.createFetchText(window.fetch.bind(window));
  const openStream=T.createOpenStream(window.fetch.bind(window));
  const OVERSCAN=700,CONVERSATIONS_EVERY_MS=15000,CONVERSATIONS_RETRY_MS=5000,SWITCH_SETTLE_MS=350;
  const S={open:false,pinned:false,selectedId:null,rulerPx:T.GEOMETRY.rulerPx,charPx:T.GEOMETRY.charPx,heightFix:new Map(),inerted:[],unreadable:0,returnFocus:null,conversations:[],conv:{loading:false,error:null,loadedAt:0,startedAt:0},
    sessions:[],mode:'all',pps:T.DEFAULT_PPS,items:[],ctx:null,version:-1,model:null,visibleCount:0,pool:new Map(),
    raf:0,tick:null,switchTimer:null,selected:null,focusId:null,pendingNew:0,traces:new Map(),parents:new Map(),
    lastPhase:'',lastAnnounceAt:0,announcedCount:0,sessionReq:0,
    /* Slice 06 : panneau du tiroir (recherche, transcription, export), saut vers un résultat. */
    panel:null,panelReturn:null,search:{q:'',all:true},transcript:{mode:'plain'},exportJob:{},jump:null,foundId:null};

  const feed=T.createFeed({request:fetchJson,onChange:onFeed});
  /* Un seul long-poll par profil : le meneur du profil tient la lecture et la
     relaie aux autres onglets. Sans Web Locks ou sans BroadcastChannel, le
     partage n'a pas lieu et chaque onglet lit pour lui — c'est le repli
     `solo`, exactement le comportement d'avant. */
  const tlChannel=typeof BroadcastChannel==='function'?new BroadcastChannel(T.SHARED_CHANNEL):null;
  const tlLocks=navigator.locks&&typeof navigator.locks.request==='function'?navigator.locks:null;
  const shared=T.createSharedFeed({feed,locks:tlLocks,channel:tlChannel,
    createAbort:()=>new AbortController(),
    log:(level,event,data)=>{if(typeof console!=='undefined'&&console[level==='warn'?'warn':'info'])console[level==='warn'?'warn':'info'](event,data)}});
  if(tlChannel)tlChannel.onmessage=event=>shared.handleMessage(event.data);

  /* Largeur réelle d'un caractère du texte des cartes (police monospace de la machine). */
  function measureText(){
    const probe=document.createElement('span');
    probe.className='tl-measure';probe.textContent='0'.repeat(100);
    el.items.appendChild(probe);
    const width=probe.getBoundingClientRect().width/100;
    probe.remove();
    if(width>3&&Math.abs(width-S.charPx)>.01){S.charPx=width;S.heightFix.clear()}
  }

  /* ------------------------------------------------------------ ouverture */
  function openView(){
    if(S.open)return;
    S.open=true;S.returnFocus=document.activeElement;
    root.hidden=false;
    /* Boîte de dialogue modale : tout le reste de la page devient inerte (ni
       focus, ni clic, ni lecteur d'écran) jusqu'à la fermeture. */
    S.inerted=[...document.body.children].filter(n=>n!==root&&!n.inert&&n.tagName!=='SCRIPT');
    for(const node of S.inerted)node.inert=true;
    measureText();
    if(el.open){el.open.classList.add('active');el.open.setAttribute('aria-expanded','true')}
    S.tick=setInterval(tick,1000);
    loadConversations();
    /* Rouverte : la conversation choisie, même si l'échange était encore en attente. */
    const wanted=S.selectedId||feed.state.conversationId;
    if(wanted&&(feed.state.phase==='stopped'||feed.state.conversationId!==wanted))shared.watch(wanted);
    requestAnimationFrame(()=>{el.conv.focus({preventScroll:true});scheduleRebuild(true)});
  }
  function closeView(){
    if(!S.open)return;
    S.open=false;
    shared.stop();
    clearInterval(S.tick);S.tick=null;clearTimeout(S.switchTimer);
    S.switchTimer=null;
    closePanel(false);
    closeDrawer(false);
    for(const node of S.inerted)node.inert=false;
    S.inerted=[];
    root.hidden=true;
    if(el.open){el.open.classList.remove('active');el.open.setAttribute('aria-expanded','false')}
    const back=S.returnFocus;S.returnFocus=null;
    if(back&&back.isConnected&&typeof back.focus==='function')back.focus({preventScroll:true});
  }

  /* -------------------------------------------------------- conversations */
  async function loadConversations(){
    if(S.conv.loading)return;
    S.conv.loading=true;S.conv.startedAt=Date.now();
    renderStatus();
    try{
      const page=await fetchJson('/api/conversations?limit=100',{timeoutMs:10000});
      S.conversations=Array.isArray(page.summaries)?page.summaries:[];
      S.conv.error=null;
      const latest=S.conversations[0]&&S.conversations[0].conversation_id;
      if(latest&&(!feed.state.conversationId||(!S.pinned&&latest!==feed.state.conversationId)))selectConversation(latest,false);
    }catch(error){
      S.conv.error=T.classifyError(error);
    }finally{
      S.conv.loading=false;S.conv.loadedAt=Date.now();
      renderConversationSelect();renderStatus();scheduleRebuild();
    }
  }
  function shortId(id){const s=String(id);return s.length>28?`${s.slice(0,12)}…${s.slice(-10)}`:s}
  function renderConversationSelect(){
    const current=S.selectedId||feed.state.conversationId,list=S.conversations.slice();
    if(current&&!list.some(c=>c.conversation_id===current))list.push({conversation_id:current,event_count:null});
    const options=[`<option value="__latest"${S.pinned?'':' selected'}>Plus récente (suit la conversation active)</option>`];
    for(const c of list){
      const range=c.first_occurred_at?`${T.fmtClock(Date.parse(c.first_occurred_at),{millis:false})} → ${T.fmtClock(Date.parse(c.last_occurred_at),{millis:false})}`:'';
      const count=c.event_count===null||c.event_count===undefined?'':` · ${T.escapeHtml(String(c.event_count))} évén.`;
      options.push(`<option value="${T.escapeHtml(c.conversation_id)}"${S.pinned&&c.conversation_id===current?' selected':''} title="${T.escapeHtml(c.conversation_id)}">${T.escapeHtml(shortId(c.conversation_id))}${range?` · ${range}`:''}${count}</option>`);
    }
    const html=options.join('');
    if(el.conv.dataset.html!==html){el.conv.innerHTML=html;el.conv.dataset.html=html}
    el.conv.disabled=!list.length&&!S.conv.error;
  }
  function selectConversation(id,pinned){
    S.pinned=pinned;S.selectedId=id;
    if(id===feed.state.conversationId&&feed.state.phase!=='stopped'){
      /* Retour à la conversation en cours avant la fin du délai : l'échange prévu est annulé. */
      clearTimeout(S.switchTimer);S.switchTimer=null;
      renderConversationSelect();scheduleRebuild(true);return;
    }
    closeDrawer(false);
    if(!S.jump||S.jump.conversationId!==id)S.foundId=null;
    S.selected=null;S.focusId=null;S.traces.clear();S.parents.clear();S.pendingNew=0;S.version=-1;
    for(const node of S.pool.values())node.remove();
    S.pool.clear();
    loadSessions(id);
    /* Une seule requête en vol par onglet : le long-poll en cours n'est
       abandonné qu'une fois la sélection stable (flèches dans la liste). */
    clearTimeout(S.switchTimer);
    const begin=()=>{S.switchTimer=null;if(S.open){shared.watch(id);el.scroll.scrollTop=0}};
    if(feed.state.conversationId)S.switchTimer=setTimeout(begin,SWITCH_SETTLE_MS);else begin();
    renderConversationSelect();scheduleRebuild(true);
  }
  async function loadSessions(id){
    const req=++S.sessionReq;
    S.sessions=[];el.sessionWrap.hidden=true;
    try{
      const page=await fetchJson(`/api/conversations/sessions?conversation_id=${encodeURIComponent(id)}&limit=100`,{timeoutMs:10000});
      if(req!==S.sessionReq)return;
      S.sessions=(page.summaries||[]).filter(s=>s.session_id);
      el.session.innerHTML='<option value="">Aller à une session…</option>'+S.sessions.map(s=>`<option value="${T.escapeHtml(s.session_id)}">${T.escapeHtml(shortId(s.session_id))} · ${T.escapeHtml(T.fmtClock(Date.parse(s.first_occurred_at),{millis:false}))} · ${T.escapeHtml(String(s.event_count))} évén.</option>`).join('');
      el.sessionWrap.hidden=!S.sessions.length;
    }catch(error){
      /* argued: the session jump is a convenience; its failure is shown in place and the timeline itself keeps working */
      if(req!==S.sessionReq)return;
      const info=T.classifyError(error);
      el.session.innerHTML=`<option value="">Sessions indisponibles : ${T.escapeHtml(info.title)}</option>`;
      el.sessionWrap.hidden=false;
    }
  }

  /* ----------------------------------------------------------------- flux */
  function onFeed(state,reason,detail){
    shared.observe(state,reason,detail);
    if(!S.open)return;
    if(reason==='start'&&S.panel==='search')renderPanel();  // "autre conversation" follows the shown one
    if(reason==='events'||reason==='start'){
      if(state.hydrated&&reason==='events'){
        const fresh=state.rows.size-S.announcedCount;
        if(fresh>0&&Date.now()-S.lastAnnounceAt>15000){announce(`${fresh} nouvel${fresh>1?'s':''} événement${fresh>1?'s':''}`);S.lastAnnounceAt=Date.now();S.announcedCount=state.rows.size}
      }else S.announcedCount=state.rows.size;
      scheduleRebuild();
    }
    if(state.phase!==S.lastPhase){
      S.lastPhase=state.phase;
      const view=T.statusView(state,S.conv,Date.now());
      if(['live','reconnecting','blocked'].includes(state.phase))announce(`${view.label}${state.phase==='live'?'':` · ${view.detail}`}`);
      scheduleRebuild();
    }
    renderStatus();
  }
  function announce(text){el.announce.textContent='';setTimeout(()=>{el.announce.textContent=text},30)}
  function renderStatus(){
    const view=T.statusView(feed.state,S.conv,Date.now());
    el.status.dataset.tone=view.tone;
    el.statusLabel.textContent=view.label;
    el.statusDetail.textContent=view.detail;
    el.status.title=[view.label,view.detail,view.hint].filter(Boolean).join(' · ');
    el.retry.hidden=!view.retry;
    const skipped=feed.state.skippedRows,unreadable=S.unreadable,notes=[];
    if(skipped)notes.push(`${skipped} ligne${skipped>1?'s':''} illisible${skipped>1?'s':''} ignorée${skipped>1?'s':''} par Core (diagnostic core.conversation_events.row_unreadable)`);
    if(unreadable)notes.push(`${unreadable} événement${unreadable>1?'s':''} à l’heure illisible écarté${unreadable>1?'s':''}`);
    el.notice.hidden=!notes.length;
    if(notes.length)el.notice.textContent=`${notes.join(' · ')} : chronologie partielle.`;
  }
  function tick(){
    if(!S.open)return;
    renderStatus();
    const c=S.conv;
    if(!c.loading&&Date.now()-c.loadedAt>(c.error?CONVERSATIONS_RETRY_MS:CONVERSATIONS_EVERY_MS))loadConversations();
    if(S.model&&S.model.openCount>0)scheduleRebuild();
    root.querySelectorAll('[data-since]').forEach(node=>{node.textContent=T.fmtDuration(Date.now()-Number(node.dataset.since))});
    if(S.panel&&(S.search.loading||S.transcript.loading||S.exportJob.loading))renderPanel();
  }

  /* ------------------------------------------------------------- rendu */
  function scheduleRebuild(force){
    if(force)S.version=-1;
    if(S.raf)return;
    S.raf=requestAnimationFrame(rebuild);
  }
  function nearBottom(){const s=el.scroll;return s.scrollHeight-s.scrollTop-s.clientHeight<64}
  function canvasTop(){return el.canvas.offsetTop}
  function rebuild(){
    S.raf=0;
    if(!S.open)return;
    const state=feed.state;
    if(state.version!==S.version){
      S.version=state.version;
      const readable=T.readableEvents([...state.rows.values()].map(r=>r.event));
      S.unreadable=readable.unreadable.length;
      if(S.heightFix.size>4000)S.heightFix.clear();
      try{S.items=T.collapseMessages(T.reconstruct(readable.events))}
      catch(error){S.items=[];renderEmpty({tone:'bad',title:'Chronologie impossible à reconstruire',body:String(error&&error.message||error)});return}
      S.ctx=T.indexItems(S.items);
      S.sequences=new Map([...state.rows.values()].map(r=>[r.event.event_id,r.sequence]));
    }
    /* Sélection pas encore chargée : jamais les lignes de la conversation précédente sous le nouveau nom. */
    const pending=!!S.selectedId&&S.selectedId!==state.conversationId;
    const visible=pending?[]:T.filterItems(S.items,S.mode);
    S.rulerPx=parseFloat(getComputedStyle(root).getPropertyValue('--tl-ruler'))||T.GEOMETRY.rulerPx;
    const follow=nearBottom();
    const anchorTime=!follow&&S.model?S.model.timeAt(el.scroll.scrollTop-canvasTop()+el.scroll.clientHeight/2):null;
    const previous=S.visibleCount;
    S.model=T.layout(visible,{width:el.scroll.clientWidth-S.rulerPx,pxPerSecond:S.pps,now:Date.now(),charPx:S.charPx,
      heightFix:(item,width)=>S.heightFix.get(`${item.item_id}|${width}`)});
    const columns=`${S.rulerPx}px ${S.model.lanes.map(l=>`${l.width}px`).join(' ')}`;
    for(const node of [el.heads,el.canvas]){node.style.gridTemplateColumns=columns;node.style.width=`${S.rulerPx+S.model.width}px`}
    S.visibleCount=visible.length;
    /* Le canevas remplit au moins la zone visible : lanes et états vides restent lisibles. */
    el.canvas.style.height=`${Math.ceil(Math.max(S.model.height,el.scroll.clientHeight-el.heads.offsetHeight))}px`;
    renderHeads(visible);
    if(follow&&visible.length)el.scroll.scrollTop=el.scroll.scrollHeight;
    else if(anchorTime!==null&&S.zoomChanged)el.scroll.scrollTop=S.model.toY(anchorTime)+canvasTop()-el.scroll.clientHeight/2;
    S.zoomChanged=false;
    const counted=T.trackNewEntries({pending:S.pendingNew,liveConversation:S.liveConversation},
      {conversationId:state.conversationId,hydrated:state.hydrated,follow,visibleCount:visible.length,previousCount:previous});
    S.pendingNew=counted.pending;S.liveConversation=counted.liveConversation;
    el.newPill.hidden=!S.pendingNew;
    el.newPill.textContent=`↓ ${S.pendingNew} nouveau${S.pendingNew>1?'x':''}`;
    renderEmpty(pending?{tone:'busy',title:'Chargement de la conversation…',body:''}
      :T.emptyView({feed:state,conversations:S.conv,total:S.items.length,visible:visible.length,mode:S.mode}));
    renderWindow();
    if(S.selected)refreshDrawer();
    if(S.jump)tryJump();
  }
  function renderHeads(visible){
    const counts=Object.fromEntries(T.LANES.map(l=>[l.id,0]));
    for(const item of visible)counts[T.laneOf(item)]++;
    for(const lane of T.LANES){
      const count=el.heads.querySelector(`[data-count="${lane.id}"]`),hint=el.canvas.querySelector(`[data-empty="${lane.id}"]`);
      if(count)count.textContent=String(counts[lane.id]);
      if(hint)hint.hidden=counts[lane.id]>0||!visible.length;
    }
  }
  function renderEmpty(view){
    el.empty.hidden=!view;
    if(!view)return;
    el.empty.dataset.tone=view.tone;
    el.empty.innerHTML=`<strong>${T.escapeHtml(view.title)}</strong>${view.body?`<span>${T.escapeHtml(view.body)}</span>`:''}${view.action==='all'?'<button type="button" class="action small" data-tl-all>Tout afficher</button>':''}`;
  }
  function renderWindow(){
    const m=S.model;
    if(!m)return;
    const base=el.scroll.scrollTop-canvasTop(),top=base-OVERSCAN,bottom=base+el.scroll.clientHeight+OVERSCAN,now=Date.now();
    const visible=T.visibleRange(m,top,bottom),keep=new Set();
    if(!S.focusId||!m.index.has(S.focusId))S.focusId=visible.length?visible[0].item.item_id:(m.entries[0]&&m.entries[0].item.item_id)||null;
    for(const entry of visible){
      const id=entry.item.item_id;keep.add(id);
      const html=T.entryHtml(entry,{rulerPx:S.rulerPx,charPx:S.charPx,now,selected:S.selected===id,found:S.foundId===id,tabindex:S.focusId===id?0:-1});
      let node=S.pool.get(id);
      if(node&&node._html===html)continue;
      const holder=document.createElement('div');holder.innerHTML=html;
      const fresh=holder.firstElementChild;fresh._html=html;
      if(node){const focused=document.activeElement===node;node.replaceWith(fresh);if(focused)fresh.focus({preventScroll:true})}
      else el.items.appendChild(fresh);
      S.pool.set(id,fresh);
    }
    /* Texte jamais coupé : une carte rendue plus haute que son estimation corrige
       la géométrie (hauteur réelle retenue pour cette largeur) et relance le rangement. */
    let corrected=false;
    for(const entry of visible){
      if(entry.kind!=='card'&&entry.kind!=='failure')continue;
      const node=S.pool.get(entry.item.item_id),real=node?node.offsetHeight:0,key=`${entry.item.item_id}|${Math.round(entry.w)}`;
      if(real>entry.h+1&&S.heightFix.get(key)!==real){S.heightFix.set(key,real);corrected=true}
    }
    if(corrected)scheduleRebuild();
    placeTips();
    for(const [id,node] of S.pool){
      if(keep.has(id))continue;
      /* Une entrée focalisée hors de la fenêtre reste dans le DOM (le focus clavier
         ne saute pas) tant qu'elle existe encore ; filtrée ou disparue, le focus
         revient à la zone de défilement. */
      const focused=document.activeElement===node;
      if(focused&&m.index.has(id))continue;
      node.remove();S.pool.delete(id);
      if(focused)el.scroll.focus({preventScroll:true});
    }
    el.ruler.innerHTML=T.ticks(m,top,bottom).map(t=>`<div class="tl-tick${t.major?' major':''}" style="top:${Math.round(t.y)}px"><span>${T.escapeHtml(T.fmtClock(t.t,{millis:m.pxPerSecond>=80}))}</span></div>`).join('');
    el.grid.innerHTML=T.ticks(m,top,bottom).map(t=>`<div class="tl-gl${t.major?' major':''}" style="top:${Math.round(t.y)}px"></div>`).join('');
    el.breaks.innerHTML=m.breaks.filter(b=>b.y1>=top&&b.y0<=bottom).map(b=>`<div class="tl-break" style="top:${Math.round(b.y0)}px;height:${Math.round(b.y1-b.y0)}px"><span>${T.escapeHtml(T.fmtDuration(b.durationMs))} sans événement · axe replié</span></div>`).join('');
  }

  /* -------------------------------------------------------------- focus */
  function entryNode(id){return S.pool.get(id)||null}
  function focusEntry(id,{open=false}={}){
    const m=S.model;
    if(!m||!m.index.has(id))return false;
    const entry=m.entries[m.index.get(id)],base=el.scroll.scrollTop-canvasTop(),view=el.scroll.clientHeight;
    if(entry.y0<base+40||entry.y0>base+view-80)el.scroll.scrollTop=entry.y0+canvasTop()-view/3;
    const left=entry.x+S.rulerPx,sx=el.scroll.scrollLeft,sw=el.scroll.clientWidth;
    if(left<sx+S.rulerPx||left+entry.w>sx+sw)el.scroll.scrollLeft=Math.max(0,left-S.rulerPx-8);
    const previous=S.focusId;S.focusId=id;
    renderWindow();
    if(previous&&previous!==id){const old=entryNode(previous);if(old)old.tabIndex=-1}
    const node=entryNode(id);
    if(node){node.tabIndex=0;node.focus({preventScroll:true})}
    if(open)openDetail(id);
    return true;
  }
  const KEYS={ArrowDown:'next',ArrowUp:'prev',ArrowLeft:'left',ArrowRight:'right',Home:'first',End:'last'};
  el.items.addEventListener('keydown',event=>{
    const direction=KEYS[event.key],node=event.target.closest('.tl-e');
    if(!direction||!node||!S.model)return;
    event.preventDefault();
    const next=T.neighbor(S.model,node.dataset.id,direction);
    if(next)focusEntry(next.item.item_id);
  });
  el.items.addEventListener('click',event=>{
    const node=event.target.closest('.tl-e');
    if(!node)return;
    const id=node.dataset.id,item=S.ctx&&S.ctx.byItem.get(id);
    focusEntry(id);
    if(item&&item.actor!=='user')openDetail(id);
  });
  el.items.addEventListener('focusin',event=>{const node=event.target.closest('.tl-e');if(node){S.focusId=node.dataset.id;placeTips()}});
  el.items.addEventListener('pointerover',event=>{const node=event.target.closest('.tl-dot');if(node&&node!==S.hoverDot){S.hoverDot=node;placeTips()}});
  el.items.addEventListener('pointerout',event=>{if(S.hoverDot&&!S.hoverDot.contains(event.relatedTarget))S.hoverDot=null});
  /* Libellé d'un point : boîte bornée (largeur maximale, texte replié), placée
     en position fixe dans la zone visible de la chronologie ; elle ne change
     jamais la largeur de défilement. */
  function placeTips(){
    const area=el.scroll.getBoundingClientRect(),margin=8;
    const dots=new Set([S.hoverDot,document.activeElement&&document.activeElement.closest&&document.activeElement.closest('.tl-dot'),
      S.selected&&S.pool.get(S.selected)].filter(n=>n&&n.isConnected&&n.classList.contains('tl-dot')));
    for(const dot of dots){
      const tip=dot.querySelector('.tl-tip');
      if(!tip)continue;
      tip.style.maxHeight=`${Math.max(40,Math.floor(area.height-2*margin))}px`;
      const d=dot.getBoundingClientRect(),w=tip.offsetWidth,h=tip.offsetHeight;
      let left=d.right+4;
      if(left+w>area.right-margin)left=d.left-4-w;
      left=Math.max(area.left+margin,Math.min(left,area.right-margin-w));
      const top=Math.max(area.top+margin,Math.min(d.top+d.height/2-h/2,area.bottom-margin-h));
      tip.style.left=`${Math.round(left)}px`;tip.style.top=`${Math.round(top)}px`;
    }
  }

  /* ------------------------------------------------------------- détail */
  function openDetail(id){
    const item=S.ctx&&S.ctx.byItem.get(id);
    if(!item||item.actor==='user')return;
    if(S.panel)closePanel(false);
    const previous=S.selected;
    S.selected=id;
    el.drawer.hidden=false;
    root.classList.add('has-drawer');
    for(const other of [previous,id]){const node=other&&entryNode(other);if(node){node._html='';}}
    renderWindow();
    refreshDrawer();
    loadTraces(item);
    scheduleRebuild();
  }
  function closeDrawer(restore){
    if(!S.selected){if(!S.panel){el.drawer.hidden=true;root.classList.remove('has-drawer')}return}
    const id=S.selected;S.selected=null;
    el.drawer.hidden=true;el.drawerBody.innerHTML='';el.drawerBody._html='';
    root.classList.remove('has-drawer');
    const node=entryNode(id);if(node)node._html='';
    if(S.open)scheduleRebuild();
    if(restore)requestAnimationFrame(()=>focusEntry(id));
  }
  function kv(rows){return rows.length?`<dl class="kv">${rows.map(([k,v])=>`<dt>${T.escapeHtml(k)}</dt><dd>${T.escapeHtml(v)}</dd>`).join('')}</dl>`:''}
  function traceHtml(eventId){
    const t=S.traces.get(eventId);
    if(!t)return '<p class="hint">Trace non demandée.</p>';
    if(t.loading)return `<p class="tl-loading" role="status"><span class="adot running" aria-hidden="true"></span>Lecture bornée de la trace… <span data-since="${t.startedAt}">${T.escapeHtml(T.fmtDuration(Date.now()-t.startedAt))}</span> (délai 20 s)</p>`;
    const m=t.model,parts=[];
    const tone=m.state==='error'?'bad':m.state==='found'?'ok':'muted';
    parts.push(`<p class="tl-trace-head" data-tone="${tone}"><strong>${T.escapeHtml(m.title)}</strong>${m.journal_kind?` <code>${T.escapeHtml(m.journal_kind)}</code>`:''}${m.detail?`<span class="hint">${T.escapeHtml(m.detail)}</span>`:''}</p>`);
    if(m.stats)parts.push(`<p class="hint">${T.escapeHtml(m.stats)}${m.truncated?' · <b class="bad">tronqué</b>':''}</p>`);
    for(const entry of m.entries||[]){
      const msg=entry.message?T.escapeHtml(entry.message):entry.message_redacted?'<span class="dim">message masqué (texte libre non autorisé)</span>':'';
      parts.push(`<div class="tl-trace-line"><div class="emeta">${T.escapeHtml(entry.ts||'—')} · ${T.escapeHtml(entry.kind||'?')} · ${T.escapeHtml(entry.level||'')}</div>${msg?`<div>${msg}</div>`:''}${kv(entry.data.map(([k,v])=>[k,typeof v==='string'?v:JSON.stringify(v)]))}${entry.redacted?`<div class="hint">${entry.redacted} champ(s) masqué(s) par la liste d’autorisation</div>`:''}</div>`);
    }
    if(m.agent_task)parts.push(`<p><button type="button" class="action small" data-tl-agent="${T.escapeHtml(m.agent_task.task_id)}">Ouvrir la trace de la tâche dans Agents</button></p>`);
    if(m.retry)parts.push(`<p><button type="button" class="action small" data-tl-retry-trace="${T.escapeHtml(eventId)}">Réessayer</button></p>`);
    return parts.join('');
  }
  function refreshDrawer(){
    const item=S.selected&&S.ctx&&S.ctx.byItem.get(S.selected);
    if(!item){closeDrawer(false);return}
    const d=T.detailModel(item,S.ctx,{now:Date.now(),sequences:S.sequences});
    const scroll=el.drawerBody.scrollTop;
    el.drawer.dataset.lane=d.lane;
    el.drawerTitle.textContent=`${d.who} · ${d.title}`;el.drawerTitle.title=el.drawerTitle.textContent;
    const sections=[];
    sections.push(`<div class="tl-dhead"><span class="chip ${d.status.tone==='bad'?'bad':d.status.tone==='warn'?'warn':d.status.tone==='live'?'on':''}">${T.escapeHtml(d.status.label)}</span><span class="chip">${d.visibility==='public'?'public':'diagnostic'}</span>${d.collapsed?`<span class="chip">${d.collapsed+1} publications fusionnées</span>`:''}</div>`);
    if(d.text)sections.push(`<p class="tl-dtext">${T.escapeHtml(d.text)}</p>`);
    if(d.note)sections.push(`<p class="notice">${T.escapeHtml(d.note)}</p>`);
    sections.push(`<section class="dsec"><h4>Temps</h4>${kv(d.timing)}${item.ended_at===null&&T.isSpan(item)?`<p class="tl-loading"><span class="adot running" aria-hidden="true"></span>En cours depuis <span data-since="${item.started_at}">${T.escapeHtml(T.fmtDuration(Date.now()-item.started_at))}</span></p>`:''}</section>`);
    if(d.outcome.length)sections.push(`<section class="dsec"><h4>Issue et métadonnées</h4>${kv(d.outcome)}</section>`);
    if(d.anomalies.length)sections.push(`<section class="dsec"><h4>Anomalies</h4><ul class="tl-list">${d.anomalies.map(a=>`<li>${T.escapeHtml(a.label)} <code>${T.escapeHtml(a.event_id)}</code></li>`).join('')}</ul></section>`);
    const links=[];
    if(d.parent){
      if(d.parent.item_id)links.push(`<button type="button" class="action small" data-tl-goto="${T.escapeHtml(d.parent.item_id)}">↑ Parent : ${T.escapeHtml(d.parent.label)}</button>`);
      else{
        const loaded=S.parents.get(d.parent.event_id);
        links.push(loaded?`<div class="hint">Parent hors de cette vue : ${T.escapeHtml(loaded)}</div>`:`<button type="button" class="action small" data-tl-parent="${T.escapeHtml(d.parent.event_id)}">Charger le parent <code>${T.escapeHtml(d.parent.event_id.slice(0,16))}…</code></button>`);
      }
    }
    for(const child of d.children)links.push(`<button type="button" class="action small" data-tl-goto="${T.escapeHtml(child.item_id)}">↓ ${T.escapeHtml(child.label)}</button>`);
    if(d.agent_task)links.push(`<button type="button" class="action small" data-tl-agent="${T.escapeHtml(d.agent_task)}">Trace de la tâche (Agents)</button>`);
    if(links.length)sections.push(`<section class="dsec"><h4>Navigation</h4><div class="tl-links">${links.join('')}</div></section>`);
    for(const e of d.events){
      sections.push(`<section class="dsec tl-ev"><h4>${T.escapeHtml(e.role)} · <code>${T.escapeHtml(e.event_type)}</code></h4>${kv([
        ['event_id',e.event_id],['séquence',e.sequence===null?'—':String(e.sequence)],['producteur',e.producer],['visibilité',e.visibility],
        ['occurred_at',e.occurred_at],...(e.started_at?[['started_at',e.started_at]]:[]),...(e.ended_at?[['ended_at',e.ended_at]]:[]),
        ...e.ids,...e.attributes.map(([k,v])=>[`attributes.${k}`,Array.isArray(v)?v.join(', '):String(v)]),
        ['trace_ref',e.trace_ref?`${e.trace_ref.source}${e.trace_ref.journal_kind?` · ${e.trace_ref.journal_kind}`:''}${e.trace_ref.join_keys&&e.trace_ref.join_keys.length?` · [${e.trace_ref.join_keys.join(', ')}]`:''}`:'aucune']])}
        <div class="tl-trace" aria-live="polite">${traceHtml(e.event_id)}</div></section>`);
    }
    const html=sections.join('');
    /* Rendu identique : rien n'est réécrit, le focus clavier reste en place
       (les compteurs vivants sont mis à jour par `tick` via data-since). */
    if(el.drawerBody._html===html)return;
    const active=document.activeElement,key=active&&el.drawerBody.contains(active)?[...active.attributes].filter(a=>a.name.startsWith('data-tl-')).map(a=>`[${a.name}="${CSS.escape(a.value)}"]`).join(''):'';
    el.drawerBody._html=html;
    el.drawerBody.innerHTML=html;
    el.drawerBody.scrollTop=scroll;
    if(key){const again=el.drawerBody.querySelector(key);if(again)again.focus({preventScroll:true})}
  }
  async function loadTrace(eventId){
    const selected=S.selected;
    S.traces.set(eventId,{loading:true,startedAt:Date.now()});
    refreshDrawer();
    let model;
    try{
      const payload=await fetchJson(`/api/conversations/events/${encodeURIComponent(eventId)}/trace`,{timeoutMs:20000});
      model=T.traceModel(payload,null);
    }catch(error){
      model=T.traceModel(null,T.classifyError(error));
    }
    S.traces.set(eventId,{loading:false,model});
    if(S.selected===selected)refreshDrawer();
  }
  async function loadTraces(item){
    const ids=[...new Set(item.events.map(e=>e.event_id))];
    for(const id of ids){
      if(S.selected!==item.item_id)return;
      const known=S.traces.get(id);
      if(known&&(known.loading||known.model.state!=='error'))continue;
      await loadTrace(id);
    }
  }
  async function loadParent(eventId){
    S.parents.set(eventId,'chargement…');refreshDrawer();
    try{
      const body=await fetchJson(`/api/conversations/events/${encodeURIComponent(eventId)}`,{timeoutMs:10000});
      const e=body.event||{};
      S.parents.set(eventId,`${e.event_type||'?'} · ${e.occurred_at||''} · séquence ${body.sequence}`);
    }catch(error){
      const info=T.classifyError(error);
      S.parents.set(eventId,`${info.title}${info.message?` : ${info.message}`:''}`);
    }
    refreshDrawer();
  }
  el.drawerBody.addEventListener('click',event=>{
    const target=event.target.closest('button');
    if(!target)return;
    if(target.dataset.tlGoto){focusEntry(target.dataset.tlGoto,{open:true});return}
    if(target.dataset.tlParent){loadParent(target.dataset.tlParent);return}
    if(target.dataset.tlRetryTrace){loadTrace(target.dataset.tlRetryTrace);return}
    if(target.dataset.tlAgent){
      const task=target.dataset.tlAgent;
      closeView();
      if(typeof openAgentsAt==='function')openAgentsAt('trace',task);
    }
  });
  el.drawerClose.addEventListener('click',()=>{if(S.panel)closePanel(true);else closeDrawer(true)});


  /* --------------------------------------- recherche, transcription, export */
  /* Trois panneaux dans le tiroir de détail (un à la fois, comme le détail).
     Le texte et l'export sont produits par Core ; chaque attente montre ce qui
     se passe, depuis quand, avec Annuler, et se termine par le résultat ou la
     cause réelle de l'échec avec Réessayer. */
  const PANEL_TITLES={search:'Recherche',transcript:'Transcription',export:'Export JSONL'};
  const PANEL_BUTTONS={search:el.searchOpen,transcript:el.transcriptOpen,export:el.exportOpen};
  function currentConversation(){return S.selectedId||feed.state.conversationId||null}
  function stateHtml(view){
    const busy=view.tone==='busy';
    return `<p class="tl-pstate" data-tone="${view.tone}">${busy?'<span class="adot running" aria-hidden="true"></span>':''}<span><strong>${T.escapeHtml(view.text)}</strong>${view.detail?` <span class="hint">${T.escapeHtml(view.detail)}</span>`:''}</span>`
      +`${view.cancel?'<button type="button" class="action small" data-tl-cancel>Annuler</button>':''}${view.retry&&view.tone==='bad'?'<button type="button" class="action small" data-tl-retry-job>Réessayer</button>':''}</p>`;
  }
  function openPanel(kind){
    if(S.panel===kind){renderPanel();return}
    if(S.selected)closeDrawer(false);
    if(S.panel)closePanel(false);
    S.panel=kind;S.panelReturn=PANEL_BUTTONS[kind]||null;
    for(const [name,button] of Object.entries(PANEL_BUTTONS))if(button)button.setAttribute('aria-expanded',String(name===kind));
    el.drawer.hidden=false;root.classList.add('has-drawer');
    el.drawer.dataset.lane='';
    el.drawerTitle.textContent=PANEL_TITLES[kind];el.drawerTitle.title=PANEL_TITLES[kind];
    el.drawerBody._html='';
    const conv=currentConversation();
    if(kind==='search'){
      el.drawerBody.innerHTML=`<form class="tl-sform" id="tlSearchForm" role="search" novalidate>
        <label class="tl-sfield"><span class="sr">Texte à chercher</span><input id="tlSearchInput" type="search" autocomplete="off" spellcheck="false" placeholder="Mot, phrase, identifiant, code…" value="${T.escapeHtml(S.search.q||'')}"></label>
        <button type="submit" class="action small">Chercher</button>
        <label class="tl-check"><input type="checkbox" id="tlSearchAll"${S.search.all!==false?' checked':''}><span>Toutes les conversations</span></label>
      </form><div id="tlPanelState"></div><ol class="tl-hits" id="tlHits" aria-label="Résultats de recherche"></ol><div id="tlPanelMore"></div>`;
    }else if(kind==='transcript'){
      el.drawerBody.innerHTML=`<div class="tl-prow"><fieldset class="tl-seg"><legend>Mode de transcription</legend><label><input type="radio" name="tlTxMode" value="plain"${S.transcript.mode!=='detailed'?' checked':''}><span>Simple</span></label><label><input type="radio" name="tlTxMode" value="detailed"${S.transcript.mode==='detailed'?' checked':''}><span>Détaillé</span></label></fieldset>
        <button type="button" class="action small" data-tl-tx-download>Télécharger .txt</button></div>
        <p class="hint">Rendue par Core à partir des seuls Conversation Events : la même que celle d’un export ré-importé avec le même fuseau. Heures locales (${T.escapeHtml(T.offsetLabel(T.localOffsetMinutes()))}), comme la chronologie. Parole de Jarvis = texte envoyé à la lecture.</p>
        <div id="tlPanelState"></div><pre class="tl-tx" id="tlTxText" tabindex="0" aria-label="Texte de la transcription" hidden></pre>`;
    }else{
      el.drawerBody.innerHTML=`<p class="hint">Événements canoniques tels que stockés dans Core, une ligne JSON chacun, entre une ligne d’en-tête et une ligne finale de contrôle. Ré-importables hors ligne (<code>read_export</code>).</p>
        <p class="tl-pconv">Conversation <code>${T.escapeHtml(conv||'—')}</code></p><div id="tlPanelState"></div>`;
    }
    renderPanel();
    requestAnimationFrame(()=>{
      const target=kind==='search'?q('#tlSearchInput'):kind==='transcript'?q('input[name="tlTxMode"]:checked'):el.drawerClose;
      if(target)target.focus({preventScroll:true});
    });
    if(kind==='transcript'&&(!S.transcript.done||S.transcript.conversationId!==conv||S.transcript.loadedMode!==S.transcript.mode))loadTranscript();
    if(kind==='export'&&!S.exportJob.loading)runExport();
  }
  function closePanel(restore){
    if(!S.panel)return;
    const kind=S.panel,back=S.panelReturn;
    if(kind==='search'&&S.search.controller)S.search.controller.abort();
    if(kind==='transcript'&&S.transcript.controller)S.transcript.controller.abort();
    if(kind==='export'&&S.exportJob.controller)S.exportJob.controller.abort();
    S.panel=null;S.panelReturn=null;
    for(const button of Object.values(PANEL_BUTTONS))if(button)button.setAttribute('aria-expanded','false');
    if(!S.selected){el.drawer.hidden=true;root.classList.remove('has-drawer');el.drawerBody.innerHTML='';el.drawerBody._html=''}
    if(restore&&back&&back.isConnected)back.focus({preventScroll:true});
  }
  function renderPanel(){
    if(!S.panel)return;
    const now=Date.now(),state=q('#tlPanelState');
    if(S.panel==='search'){
      const view=T.searchStateView(S.search,now);
      if(state)state.innerHTML=stateHtml(view);
      const list=q('#tlHits'),more=q('#tlPanelMore');
      if(list){
        const current=feed.state.conversationId;
        const html=(S.search.hits||[]).map((hit,i)=>{
          const v=T.hitView(hit,{currentConversationId:current});
          return `<li><button type="button" class="tl-hit" data-tl-hit="${i}" aria-label="${T.escapeHtml(`${v.who}, ${v.what}, ${v.day} ${v.when}${v.elsewhere?', autre conversation':''} : ${hit.snippet}`)}">`
            +`<span class="tl-hmeta"><span class="tl-hwho">${T.escapeHtml(v.who)}</span> · ${T.escapeHtml(v.what)} · <time>${T.escapeHtml(v.day)} ${T.escapeHtml(v.when)}</time>${v.elsewhere?` · <span class="tl-hconv" title="${T.escapeHtml(v.conversation)}">autre conversation</span>`:''}</span>`
            +`<span class="tl-hsnip">${v.snippet}</span>${v.matched?`<span class="tl-hfield">trouvé dans : ${T.escapeHtml(v.matched)}</span>`:''}</button></li>`;
        }).join('');
        if(list._html!==html){list.innerHTML=html;list._html=html}
      }
      if(more)more.innerHTML=view.more&&!S.search.loading?`<button type="button" class="action small" data-tl-more>${S.search.scanLimited?'Continuer la recherche':'Plus de résultats'}</button>`:'';
    }else if(S.panel==='transcript'){
      const job=S.transcript;
      if(state)state.innerHTML=stateHtml(T.jobStateView('transcript',job,now));
      const pre=q('#tlTxText'),download=q('[data-tl-tx-download]');
      if(pre){
        const text=job.done&&!job.loading?job.text:'';
        if(pre._text!==text){pre.textContent=text;pre._text=text}
        pre.hidden=!text;
      }
      if(download)download.disabled=!(job.done&&!job.loading&&job.text);
    }else if(state){
      state.innerHTML=stateHtml(T.jobStateView('export',S.exportJob,now));
    }
  }

  async function runSearch(more){
    const input=q('#tlSearchInput'),all=q('#tlSearchAll');
    const text=more?S.search.q:(input?input.value:'');
    const problem=T.searchQueryProblem(text);
    if(problem){S.search={...S.search,q:text,error:{title:'Recherche impossible',message:problem,hint:''},done:false,loading:false};renderPanel();if(input)input.focus();return}
    if(S.search.controller)S.search.controller.abort();
    const controller=new AbortController();
    const scope=more?S.search.scope:(all&&!all.checked?currentConversation():null);
    const previous=more?S.search.hits||[]:[];
    S.search={q:text,all:!scope,scope,loading:true,startedAt:Date.now(),controller,hits:previous,
      cursor:more?S.search.cursor:null,done:more,scanLimited:false,scanned:0,skippedRows:more?S.search.skippedRows:0,error:null};
    renderPanel();
    try{
      const page=await fetchJson(T.searchUrl({q:text,conversationId:scope,beforeSequence:more?S.search.cursor:null}),{signal:controller.signal,timeoutMs:40000});
      if(S.search.controller!==controller)return;
      if(!Array.isArray(page.hits))throw Object.assign(new Error('page de recherche hors contrat'),{code:'invalid_page'});
      S.search={...S.search,loading:false,done:true,hits:[...previous,...page.hits],cursor:page.next_cursor,hasMore:!!page.has_more,
        scanLimited:!!page.scan_limited,scanned:Number(page.scanned_rows)||0,skippedRows:(S.search.skippedRows||0)+(Number(page.skipped_rows)||0),controller:null};
      const n=S.search.hits.length;
      announce(n?`${n} résultat${n>1?'s':''}`:'Aucun résultat');
    }catch(error){
      if(S.search.controller!==controller)return;
      const info=T.classifyError(error);
      S.search={...S.search,loading:false,controller:null,error:info.aborted?{title:'Recherche annulée',message:'',hint:''}:info};
      if(!info.aborted&&typeof console!=='undefined')console.error('timeline search failed',info.code,info.message);
    }finally{
      if(S.search.controller===controller)S.search.controller=null;
      renderPanel();
    }
  }
  function jumpTo(index){
    const hit=(S.search.hits||[])[index];
    if(!hit)return;
    if(S.mode==='public'&&hit.visibility!=='public'){
      const all=root.querySelector('input[name="tlFilter"][value="all"]');
      all.checked=true;S.mode='all';
    }
    S.jump={eventId:hit.event_id,conversationId:hit.conversation_id,startedAt:Date.now()};
    S.foundId=null;
    if(S.selectedId!==hit.conversation_id||feed.state.conversationId!==hit.conversation_id)selectConversation(hit.conversation_id,true);
    scheduleRebuild(true);
  }
  /* Appelé après chaque reconstruction : l'événement est-il déjà chargé ? */
  function tryJump(){
    const jump=S.jump,state=feed.state;
    if(!jump||state.conversationId!==jump.conversationId||S.selectedId!==jump.conversationId)return;
    const item=T.itemForEvent(S.ctx,jump.eventId);
    if(item&&S.model&&S.model.index.has(item.item_id)){
      S.jump=null;S.foundId=item.item_id;
      /* Écran où le tiroir recouvre la chronologie : il se referme pour montrer
         l'entrée trouvée (les résultats restent, « Rechercher » les rouvre). */
      if(S.panel&&window.matchMedia&&window.matchMedia('(max-width:1099px)').matches)closePanel(false);
      focusEntry(item.item_id);
      announce('Événement trouvé dans la chronologie');
      return;
    }
    if(state.hydrated&&state.phase==='live'){
      S.jump=null;
      S.search={...S.search,error:{title:'Événement absent de la chronologie',message:'Il n’est plus lisible dans cette conversation (ligne illisible ou retirée par la rétention).',hint:''}};
      renderPanel();
    }
  }

  async function loadTranscript(){
    const conv=currentConversation();
    if(S.transcript.controller)S.transcript.controller.abort();
    if(!conv){S.transcript={mode:S.transcript.mode,error:{title:'Aucune conversation',message:'Choisissez une conversation.',hint:''}};renderPanel();return}
    const controller=new AbortController(),mode=S.transcript.mode;
    S.transcript={mode,loading:true,startedAt:Date.now(),controller,conversationId:conv};
    renderPanel();
    try{
      const offset=T.localOffsetMinutes();
      const text=await fetchText(T.transcriptUrl(conv,mode,offset),{signal:controller.signal,timeoutMs:70000});
      if(S.transcript.controller!==controller)return;
      S.transcript={mode,done:true,text,bytes:new Blob([text]).size,elapsedMs:Date.now()-S.transcript.startedAt,conversationId:conv,loadedMode:mode,offset};
      announce('Transcription chargée');
    }catch(error){
      if(S.transcript.controller!==controller)return;
      const info=T.classifyError(error);
      S.transcript={mode,conversationId:conv,error:info.aborted?{title:'Transcription annulée',message:'',hint:''}:info};
      if(!info.aborted&&typeof console!=='undefined')console.error('timeline transcript failed',info.code,info.message);
    }finally{
      renderPanel();
    }
  }
  function saveBlob(blob,filename){
    const url=URL.createObjectURL(blob),link=document.createElement('a');
    link.href=url;link.download=filename;link.hidden=true;
    root.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
  }
  async function runExport(){
    const conv=currentConversation();
    if(S.exportJob.controller)S.exportJob.controller.abort();
    if(!conv){S.exportJob={error:{title:'Aucune conversation',message:'Choisissez une conversation à exporter.',hint:''}};renderPanel();return}
    const controller=new AbortController(),filename=T.exportFilename(conv);
    const job={loading:true,startedAt:Date.now(),controller,received:0,filename,conversationId:conv};
    S.exportJob=job;renderPanel();
    let idle=null;
    const arm=()=>{clearTimeout(idle);idle=setTimeout(()=>{job.timedOut=true;controller.abort()},30000)};
    try{
      arm();
      const response=await openStream(T.exportUrl(conv),{signal:controller.signal});
      const reader=response.body.getReader(),parts=[];
      for(;;){
        const {done,value}=await reader.read();
        if(done)break;
        parts.push(value);job.received+=value.byteLength;arm();
        if(S.panel==='export'&&S.exportJob===job)renderPanel();
      }
      const blob=new Blob(parts,{type:'application/x-ndjson'});
      const summary=T.exportSummary(await blob.slice(Math.max(0,blob.size-4096)).text());
      if(!summary.complete)throw Object.assign(new Error('Ligne finale de contrôle absente.'),{code:'export_incomplete'});
      if(S.exportJob!==job)return;
      S.exportJob={done:true,received:blob.size,events:summary.events,skippedRows:summary.skippedRows,filename,conversationId:conv,saved:summary.events>0};
      if(summary.events>0){saveBlob(blob,filename);announce('Export JSONL téléchargé')}
      else announce('Aucun événement à exporter');
    }catch(error){
      if(S.exportJob!==job)return;
      const info=T.exportFailure(error,{received:job.received,timedOut:!!job.timedOut});
      S.exportJob={conversationId:conv,filename,received:job.received,error:info};
      if(!info.aborted&&typeof console!=='undefined')console.error('timeline export failed',info.code,info.message);
    }finally{
      clearTimeout(idle);
      renderPanel();
    }
  }

  el.drawerBody.addEventListener('submit',event=>{
    if(event.target.id!=='tlSearchForm')return;
    event.preventDefault();runSearch(false);
  });
  el.drawerBody.addEventListener('change',event=>{
    if(event.target.name==='tlTxMode'&&event.target.checked){S.transcript={...S.transcript,mode:event.target.value};loadTranscript()}
    if(event.target.id==='tlSearchAll')S.search.all=event.target.checked;
  });
  el.drawerBody.addEventListener('click',event=>{
    const target=event.target.closest('button');
    if(!target||!S.panel)return;
    if(target.dataset.tlHit!==undefined){jumpTo(Number(target.dataset.tlHit));return}
    if(target.hasAttribute('data-tl-more')){runSearch(true);return}
    if(target.hasAttribute('data-tl-cancel')){
      const job=S.panel==='search'?S.search:S.panel==='transcript'?S.transcript:S.exportJob;
      if(job&&job.controller)job.controller.abort();
      return;
    }
    if(target.hasAttribute('data-tl-retry-job')){
      if(S.panel==='search')runSearch(false);else if(S.panel==='transcript')loadTranscript();else runExport();
      return;
    }
    if(target.hasAttribute('data-tl-tx-download')&&S.transcript.done&&S.transcript.text){
      saveBlob(new Blob([S.transcript.text],{type:'text/plain;charset=utf-8'}),T.transcriptFilename(S.transcript.conversationId,S.transcript.loadedMode));
    }
  });
  for(const [kind,button] of Object.entries(PANEL_BUTTONS)){
    if(!button)continue;
    button.addEventListener('click',()=>{
      if(S.panel===kind&&kind!=='export'){closePanel(true);return}
      openPanel(kind);
    });
  }

  /* ---------------------------------------------------------- commandes */
  if(el.open)el.open.addEventListener('click',()=>{if(S.open)closeView();else openView()});
  el.close.addEventListener('click',closeView);
  el.conv.addEventListener('change',()=>{
    const value=el.conv.value;
    if(value==='__latest'){S.pinned=false;const latest=S.conversations[0];if(latest)selectConversation(latest.conversation_id,false);return}
    selectConversation(value,true);
  });
  el.session.addEventListener('change',()=>{
    const s=S.sessions.find(x=>x.session_id===el.session.value);
    el.session.value='';
    if(!s||!S.model)return;
    el.scroll.scrollTop=S.model.toY(Date.parse(s.first_occurred_at))+canvasTop()-24;
    renderWindow();
  });
  root.querySelectorAll('input[name="tlFilter"]').forEach(input=>input.addEventListener('change',()=>{
    if(!input.checked)return;
    S.mode=input.value;
    if(S.selected&&S.mode==='public'){const item=S.ctx.byItem.get(S.selected);if(item&&item.visibility!=='public')closeDrawer(false)}
    scheduleRebuild();
  }));
  el.empty.addEventListener('click',event=>{
    if(!event.target.closest('[data-tl-all]'))return;
    const all=root.querySelector('input[name="tlFilter"][value="all"]');
    all.checked=true;all.dispatchEvent(new Event('change'));
  });
  el.zoom.addEventListener('change',()=>{S.pps=Number(el.zoom.value)||T.DEFAULT_PPS;S.zoomChanged=true;scheduleRebuild()});
  el.retry.addEventListener('click',()=>{
    if(!feed.state.conversationId){loadConversations();return}
    if(!shared.retryNow())shared.watch(feed.state.conversationId);
  });
  el.newPill.addEventListener('click',()=>{el.scroll.scrollTop=el.scroll.scrollHeight;S.pendingNew=0;el.newPill.hidden=true});
  el.scroll.addEventListener('scroll',()=>{
    if(S.scrollRaf)return;
    S.scrollRaf=requestAnimationFrame(()=>{S.scrollRaf=0;renderWindow();placeTips();if(nearBottom()&&S.pendingNew){S.pendingNew=0;el.newPill.hidden=true}});
  },{passive:true});
  if(typeof ResizeObserver==='function')new ResizeObserver(()=>{if(S.open){measureText();scheduleRebuild()}}).observe(el.scroll);
  /* Un clic dans le vide du canevas garde le focus dans la vue (sinon il part sur
     le corps de la page, hors de la boîte de dialogue). */
  el.scroll.addEventListener('mousedown',event=>{if(!event.target.closest('button,select,input,.tl-e'))el.scroll.focus({preventScroll:true})});

  /* Échap : ferme le détail, puis la vue. Capture au niveau du document pour
     passer avant les raccourcis de la page (fermeture du panneau). */
  document.addEventListener('keydown',event=>{
    if(!S.open||event.key!=='Escape')return;
    event.preventDefault();event.stopPropagation();
    if(S.selected)closeDrawer(true);else if(S.panel)closePanel(true);else closeView();
  },true);
  /* Les autres raccourcis de la page (panneaux, réglages) ne traversent pas la
     vue plein écran ; Tab reste dans la boîte de dialogue. */
  root.addEventListener('keydown',event=>{
    if(event.key==='Tab'){
      /* Seuls les éléments réellement atteignables au clavier (tabIndex >= 0, visibles). */
      const focusable=[...root.querySelectorAll('button,select,input,[tabindex]')].filter(n=>n.tabIndex>=0&&!n.disabled&&n.offsetParent!==null&&!n.closest('[hidden]'));
      if(focusable.length){
        const first=focusable[0],last=focusable[focusable.length-1];
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
      }
    }
    event.stopPropagation();
  });

  /* Passation. Fermer, cacher, naviguer ou geler l'onglet meneur rend le
     verrou : un autre onglet visible du même profil le reçoit aussitôt et
     reprend la lecture à son propre curseur — aucun événement ne se perd,
     puisque le serveur rend tout ce qui suit cette séquence.
     Un onglet caché ne lit plus rien et rattrape en redevenant visible. */
  document.addEventListener('visibilitychange',()=>{
    if(!S.open)return;
    shared.setVisible(document.visibilityState!=='hidden');
    renderStatus();
  });
  const handOver=()=>{if(S.open)shared.setVisible(false)};
  window.addEventListener('pagehide',handOver);
  window.addEventListener('freeze',handOver);

  window.JarvisTimeline={open:openView,close:closeView,state:S,feed,shared,
    /* Ce que la recette regarde : le mode réel, le rôle de cet onglet, et
       s'il tient une requête longue. */
    sharing(){
      const f=feed.state;
      const holding=(f.sharedRole==='leader'||f.sharedRole==='solo')&&['live','hydrating','catching_up'].includes(f.phase);
      return {...shared.view(),phase:f.phase,cursor:f.cursor,rows:f.rows.size,
        longPolls:holding&&f.lastWaitMs>0?1:0,requests:f.requests,shortReads:f.shortReads};
    },
  };
})();
