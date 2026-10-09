/* Protocole hôte <-> bac à sable d'une scène Remotion, `rs: 1` (handoff jarvis-remotion-presentation-integration,
   Slice 06 ; contrat `docs/remotion-isolation.md`). Logique PURE : ni DOM, ni réseau, ni minuterie. Exposé en
   `window.RemotionSandboxProtocol` (page de l'hôte ET page du bac à sable, même fichier) et en `module.exports` pour node.

   Le cadre est HOSTILE : tout ce qu'il envoie est une donnée à valider, jamais une instruction.
   - `parseChildMessage(event, expectedSource)` : un message cadre->hôte accepté ou la raison du refus. La SOURCE
     (`event.source === iframe.contentWindow`) est le contrôle ; l'origine d'un cadre `sandbox` sans `allow-same-origin`
     est toujours la chaîne "null", donc elle ne distingue personne et n'est qu'un second contrôle.
   - `parseHostMessage(event, expectedSource, expectedOrigin)` : côté cadre, un message n'est accepté que du parent
     (`window.parent`) et de l'origine de l'hôte (un cadre frère ne peut pas lui parler).
   - Types hôte->cadre : `init {composition, props}`, `props {props}`, `control {action, frame?}`, `cue {name, frame}`,
     `ping {n}`, `teardown {}`. Cadre->hôte : `ready {}`, `pong {n, frame, dropped}`, `violation {directive, blocked}`,
     `error {message}`. Champs EXACTS : une clé de plus est un refus.
   - Bornes AVANT travail : taille estimée (`jsonBudget` s'arrête dès que la borne est dépassée), profondeur, nombre de
     nœuds, types JSON seulement, jamais une clé `__proto__`. Une chaîne géante est refusée sans être parcourue.
   - `createSupervisor(options)` : le chien de garde de l'hôte. Il compte les refus (`maxViolations` => retrait du cadre),
     limite le débit, envoie un `ping {n}` avec un jeton neuf et exige son `pong` : un cadre figé (boucle infinie, mémoire
     saturée) ne répond pas et est retiré (`kill`) sans que la page de l'hôte ne bloque (le cadre est un autre processus). */
(function(root){
  'use strict';
  const RS=1;
  const HOST_TYPES=Object.freeze(['init','props','control','cue','ping','teardown']);
  const CHILD_TYPES=Object.freeze(['ready','pong','violation','error']);
  const CONTROL_ACTIONS=Object.freeze(['play','pause','seek']);
  const LIMITS=Object.freeze({
    maxPropsBytes:64*1024, maxChildBytes:2048, maxDepth:8, maxNodes:2000, maxErrorChars:300, maxBlockedChars:120,
    maxFrame:108000, maxCompositionPx:7680, minCompositionPx:16, maxFps:120,
    maxChildMessagesPerSecond:200, maxViolations:20, pingEveryMs:1000, silentMs:3000, readyMs:10000,
    maxReportsPerSecond:20
  });
  const NAME=/^[a-z][a-z0-9_]{0,39}$/;
  const TOKEN=/^[a-z0-9]{8,32}$/;
  const DIRECTIVE=/^[a-z][a-z-]{0,39}$/;
  const COMPOSITION_ID=/^[A-Za-z][A-Za-z0-9-]{0,63}$/;
  const FIELDS=Object.freeze({
    init:['composition','props'], props:['props'], control:['action','frame'], cue:['name','frame'], ping:['n'], teardown:[],
    ready:[], pong:['n','frame','dropped'], violation:['directive','blocked'], error:['message']
  });

  function isPlainObject(value){
    return value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.getPrototypeOf(value)===Object.prototype;
  }
  function isInt(value,low,high){return typeof value==='number'&&Number.isInteger(value)&&value>=low&&value<=high}

  /* Estimation bornée du JSON d'une valeur : `true` si elle tient dans `limit` octets, `maxDepth` niveaux et `maxNodes`
     nœuds, et n'est faite que de JSON simple. S'arrête dès le dépassement (jamais de sérialisation complète). */
  function jsonBudget(value,limit){
    let bytes=0,nodes=0;
    function walk(item,depth){
      if(depth>LIMITS.maxDepth||++nodes>LIMITS.maxNodes||bytes>limit)return false;
      if(item===null){bytes+=4;return true}
      switch(typeof item){
        case 'string':bytes+=item.length+2;return bytes<=limit;
        case 'boolean':bytes+=5;return true;
        case 'number':bytes+=8;return Number.isFinite(item);
        case 'object':
          if(Array.isArray(item)){
            if(item.length>LIMITS.maxNodes)return false;
            for(let i=0;i<item.length;i++){if(!walk(item[i],depth+1))return false}
            return bytes<=limit;
          }
          if(!isPlainObject(item))return false;
          for(const key of Object.keys(item)){
            if(key==='__proto__'||key.length>200)return false;
            bytes+=key.length+3;
            if(!walk(item[key],depth+1))return false;
          }
          return bytes<=limit;
        default:return false;
      }
    }
    return walk(value,0)&&bytes<=limit;
  }

  function clean(text,limit){
    if(typeof text!=='string')return '';
    return text.slice(0,limit).replace(/[\u0000-\u001f\u007f]/g,' ');
  }

  function checkComposition(c){
    return isPlainObject(c)&&Object.keys(c).sort().join()==='durationInFrames,fps,height,id,width'
      &&typeof c.id==='string'&&COMPOSITION_ID.test(c.id)
      &&isInt(c.width,LIMITS.minCompositionPx,LIMITS.maxCompositionPx)&&isInt(c.height,LIMITS.minCompositionPx,LIMITS.maxCompositionPx)
      &&isInt(c.fps,1,LIMITS.maxFps)&&isInt(c.durationInFrames,1,LIMITS.maxFrame);
  }

  /* Valide `type` + champs exacts ; rend {ok:true,message} (copie fraîche, bornée) ou {ok:false,reason}. */
  function validate(data,types,direction){
    if(!isPlainObject(data))return refuse('not_object');
    if(data.rs!==RS)return refuse('bad_version');
    const type=data.type;
    if(typeof type!=='string'||!types.includes(type))return refuse('bad_type');
    const allowed=FIELDS[type];
    for(const key of Object.keys(data)){
      if(key!=='rs'&&key!=='type'&&!allowed.includes(key))return refuse('extra_field');
    }
    const out={rs:RS,type};
    switch(type){
      case 'init':
        if(!checkComposition(data.composition))return refuse('bad_composition');
        if(!isPlainObject(data.props)||!jsonBudget(data.props,LIMITS.maxPropsBytes))return refuse('bad_props');
        out.composition={id:data.composition.id,width:data.composition.width,height:data.composition.height,fps:data.composition.fps,durationInFrames:data.composition.durationInFrames};
        out.props=JSON.parse(JSON.stringify(data.props));break;
      case 'props':
        if(!isPlainObject(data.props)||!jsonBudget(data.props,LIMITS.maxPropsBytes))return refuse('bad_props');
        out.props=JSON.parse(JSON.stringify(data.props));break;
      case 'control':
        if(!CONTROL_ACTIONS.includes(data.action))return refuse('bad_action');
        out.action=data.action;
        if(data.action==='seek'){if(!isInt(data.frame,0,LIMITS.maxFrame))return refuse('bad_frame');out.frame=data.frame}
        else if('frame' in data)return refuse('extra_field');
        break;
      case 'cue':
        if(typeof data.name!=='string'||!NAME.test(data.name)||!isInt(data.frame,0,LIMITS.maxFrame))return refuse('bad_cue');
        out.name=data.name;out.frame=data.frame;break;
      case 'ping':
        if(typeof data.n!=='string'||!TOKEN.test(data.n))return refuse('bad_token');
        out.n=data.n;break;
      case 'pong':
        if(typeof data.n!=='string'||!TOKEN.test(data.n)||!isInt(data.frame,-1,LIMITS.maxFrame)||!isInt(data.dropped,0,1e9))return refuse('bad_pong');
        out.n=data.n;out.frame=data.frame;out.dropped=data.dropped;break;
      case 'violation':
        if(typeof data.directive!=='string'||!DIRECTIVE.test(data.directive)||typeof data.blocked!=='string')return refuse('bad_violation');
        out.directive=data.directive;out.blocked=clean(data.blocked,LIMITS.maxBlockedChars);break;
      case 'error':
        if(typeof data.message!=='string')return refuse('bad_error');
        out.message=clean(data.message,LIMITS.maxErrorChars);break;
      default:break; // ready, teardown : aucun champ
    }
    return {ok:true,message:out,direction};
  }
  function refuse(reason){return {ok:false,reason}}

  /* Taille du message cadre->hôte AVANT validation : une chaîne ou un objet énorme est refusé sans parcours complet. */
  function parseChildMessage(event,expectedSource){
    if(!event||event.source!==expectedSource||expectedSource==null)return refuse('foreign_source');
    if(event.origin!=='null')return refuse('bad_origin');
    if(!isPlainObject(event.data))return refuse('not_object');
    if(!jsonBudget(event.data,LIMITS.maxChildBytes))return refuse('too_large');
    return validate(event.data,CHILD_TYPES,'child');
  }

  function parseHostMessage(event,expectedSource,expectedOrigin){
    if(!event||expectedSource==null||event.source!==expectedSource)return refuse('foreign_source');
    if(typeof expectedOrigin!=='string'||event.origin!==expectedOrigin)return refuse('bad_origin');
    if(!isPlainObject(event.data))return refuse('not_object');
    if(!jsonBudget(event.data,LIMITS.maxPropsBytes+4096))return refuse('too_large');
    return validate(event.data,HOST_TYPES,'host');
  }

  function build(types,type,fields){
    const result=validate(Object.assign({rs:RS,type},fields||{}),types,'build');
    if(!result.ok)throw new Error('rs message refused: '+result.reason);
    return result.message;
  }
  const hostMessage=(type,fields)=>build(HOST_TYPES,type,fields);
  const childMessage=(type,fields)=>build(CHILD_TYPES,type,fields);

  /* Chien de garde. options : now() ms, send(message) vers le cadre, kill(reason, detail), token() chaîne [a-z0-9]{8,32},
     limits (surcharge de LIMITS pour les tests). Rend {accept(event, source), tick(), state()}. */
  function createSupervisor(options){
    const limits=Object.assign({},LIMITS,options.limits||{});
    const now=options.now;
    const state={ready:false,killed:false,reason:null,startedAt:now(),pending:null,pendingSince:0,lastPingAt:-1e9,lastFrame:-1,violations:0,
      accepted:0,refused:{},foreign:0,reports:[],windowStart:now(),windowCount:0,pongs:0,childDropped:0,violationsReported:0,errorsReported:0};
    function kill(reason,detail){
      if(state.killed)return;
      state.killed=true;state.reason=reason;
      options.kill(reason,detail||null);
    }
    function violation(reason){
      state.refused[reason]=(state.refused[reason]||0)+1;
      state.violations+=1;
      if(state.violations>=limits.maxViolations)kill('protocol_abuse',reason);
    }
    function accept(event,source){
      if(state.killed)return {ok:false,reason:'killed'};
      const t=now();
      if(t-state.windowStart>=1000){state.windowStart=t;state.windowCount=0}
      state.windowCount+=1;
      if(state.windowCount>limits.maxChildMessagesPerSecond){
        if(state.windowCount===limits.maxChildMessagesPerSecond+1)violation('flood');
        else if(state.windowCount>limits.maxChildMessagesPerSecond*50)kill('protocol_abuse','flood');
        return {ok:false,reason:'flood'};
      }
      const result=parseChildMessage(event,source);
      if(!result.ok){
        if(result.reason==='foreign_source'){state.foreign+=1}  // une autre fenêtre : ce n'est pas la faute du cadre
        else violation(result.reason);
        return result;
      }
      const message=result.message;
      switch(message.type){
        case 'ready':
          if(state.ready){violation('duplicate_ready');return refuse('duplicate_ready')}
          state.ready=true;break;
        case 'pong':
          if(state.pending===null||message.n!==state.pending){violation('unexpected_pong');return refuse('unexpected_pong')}
          state.pending=null;state.pongs+=1;state.lastFrame=message.frame;state.childDropped=message.dropped;break;
        case 'violation':case 'error':
          state.reports=state.reports.filter(x=>t-x<1000);
          if(state.reports.length>=limits.maxReportsPerSecond){violation('report_flood');return refuse('report_flood')}
          state.reports.push(t);
          if(message.type==='violation')state.violationsReported+=1;else state.errorsReported+=1;
          break;
        default:break;
      }
      state.accepted+=1;
      return result;
    }
    function tick(){
      if(state.killed)return;
      const t=now();
      if(!state.ready&&t-state.startedAt>limits.readyMs){kill('no_ready',null);return}
      if(state.pending!==null){
        if(t-state.pendingSince>limits.silentMs)kill('unresponsive',String(t-state.pendingSince));
        return;
      }
      if(t-state.lastPingAt>=limits.pingEveryMs&&(state.ready||t-state.startedAt>=limits.pingEveryMs)){
        const n=options.token();
        state.pending=n;state.pendingSince=t;state.lastPingAt=t;
        options.send(hostMessage('ping',{n}));
      }
    }
    return {accept,tick,state:()=>JSON.parse(JSON.stringify(state))};
  }

  const api={RS,HOST_TYPES,CHILD_TYPES,CONTROL_ACTIONS,LIMITS,FIELDS,jsonBudget,parseChildMessage,parseHostMessage,hostMessage,childMessage,createSupervisor};
  if(typeof module==='object'&&module&&module.exports)module.exports=api;
  root.RemotionSandboxProtocol=api;
})(typeof window!=='undefined'?window:globalThis);
