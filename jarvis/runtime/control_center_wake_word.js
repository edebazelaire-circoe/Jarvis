/* Réglages du mot d'éveil : onglet « Mot d'éveil » des Réglages du Control Center
   (handoff jarvis-wake-word, Slice 07).

   Deux parties, comme `control_center_scene_settings.js` :
   - `JarvisWakeWordSettings`, logique pure : le formulaire, la charge utile,
     l'état que l'écran dit, la traduction des codes de refus de la route
     `/api/wake-word` (Slice 03) et la lecture du dernier événement du détecteur
     dans le journal. Les tests l'exécutent avec node
     (`tests/unit/test_wake_word_settings_ui.py`) ;
   - un bloc navigateur : l'onglet, ses contrôles, l'appel de la route.

   Ce que cet écran sait, et ce qu'il ne sait pas.
   - Il sait ce que la route décrit (`describe()` côté serveur) : le réglage lu,
     son état, ses diagnostics. Voice ne relit les réglages qu'à son démarrage :
     aucune API n'expose si Voice a redémarré depuis, donc l'écran ne dit JAMAIS
     « en écoute » à partir du réglage.
   - Il lit, sur demande, le DERNIER événement du détecteur dans le journal
     (`/api/trace`, route existante : `wake.shared_pcm.*`, `wake.own_stream.*`).
     C'est un événement passé, daté, pas une mesure en direct ; il est présenté
     comme tel. Aucune nouvelle route.
   - Il ne stocke rien (aucun stockage du navigateur, aucun second magasin) : la seule écriture
     est le POST de `/api/wake-word`, et le serveur reste le seul validateur. */
(function(root){
  'use strict';

  const ROUTE='/api/wake-word';
  const TRACE_LIMIT=500;
  const TRACE_ROUTE=`/api/trace?limit=${TRACE_LIMIT}`;
  const STATUS_ROUTE='/api/status';

  const PROVIDER_PORCUPINE='porcupine';
  const PROVIDER_OPENWAKEWORD='openwakeword';
  const PROVIDER_LABEL=Object.freeze({[PROVIDER_PORCUPINE]:'Porcupine (Picovoice)',[PROVIDER_OPENWAKEWORD]:'openWakeWord'});
  /* Même forme que `wake_word_settings._PORCUPINE_TOKEN` (un test fige l'égalité).
     Conseil de saisie seulement : le serveur reste l'arbitre. */
  const PORCUPINE_PATTERN='^[a-z]+( [a-z]+){0,3}$';
  const PORCUPINE_MAX_LENGTH=32;
  const FIELDS=Object.freeze(['enabled','provider','keyword','sensitivity','cooldown_ms']);

  /* Les codes de la route, en français. Les treize refus d'écriture, puis les
     deux diagnostics de lecture (`problems`) qui n'en sont pas. Une table
     fermée : un test la compare aux codes du module serveur. */
  const ERROR_TEXT=Object.freeze({
    wake_word_bad_payload:'La demande n’avait pas la forme attendue (un objet JSON). Rechargez la page et recommencez.',
    wake_word_unknown_field:'La demande portait un réglage que ce serveur ne connaît pas. Rechargez la page : elle est peut-être plus ancienne que le serveur.',
    wake_word_schema_version_unsupported:'Cette page et le serveur ne parlent pas la même version du réglage. Rechargez la page.',
    wake_word_foreign_version:'Le réglage déjà enregistré vient d’une autre version de JARVIS (plus récente) : il est gardé tel quel et rien n’a été écrit. Mettez JARVIS à jour, ou faites une copie du fichier de réglages avant de retirer le bloc « wake_word » à la main.',
    wake_word_enabled_invalid:'« Activer » attend oui ou non.',
    wake_word_provider_invalid:'Le fournisseur doit être un texte.',
    wake_word_provider_unknown:'Ce fournisseur n’existe pas : choisissez Porcupine ou openWakeWord.',
    wake_word_keyword_invalid:'Le mot d’éveil doit être un texte.',
    wake_word_keyword_unknown:'Ce mot d’éveil n’est pas accepté pour ce fournisseur : openWakeWord n’en connaît que ceux de la liste ; Porcupine veut des minuscules sans accent, mots séparés par une espace.',
    wake_word_sensitivity_invalid:'La sensibilité doit être un nombre.',
    wake_word_sensitivity_out_of_range:'La sensibilité doit être comprise entre 0 et 1.',
    wake_word_cooldown_invalid:'Le délai anti-rebond doit être un nombre entier de millisecondes.',
    wake_word_cooldown_out_of_range:'Le délai anti-rebond doit être compris entre 80 et 30 000 ms.',
    wake_word_block_malformed:'Le bloc « wake_word » du fichier de réglages n’est pas un objet : les valeurs par défaut sont appliquées.',
    wake_word_stored_version_unreadable:'Le bloc « wake_word » du fichier de réglages est d’une autre version de JARVIS : les valeurs par défaut sont appliquées et le bloc est gardé tel quel.',
  });
  /* Refus d'écriture : les treize codes stables de `apply()`. */
  const WRITE_REFUSALS=Object.freeze(Object.keys(ERROR_TEXT).slice(0,13));

  /* Pannes et états du détecteur, tels que le journal les nomme (`data.code`,
     `data.cause_code`). Vocabulaire des Slices 02, 04 et 05. */
  const DETECTOR_TEXT=Object.freeze({
    wake_engine_unavailable:'le moteur ne se construit pas',
    wake_engine_failed:'le moteur est tombé en cours d’écoute',
    wake_package_missing:'l’extra Python « wakeword » n’est pas installé',
    wake_package_failed:'l’extra Python « wakeword » ne se charge pas',
    wake_model_missing:'le modèle n’est pas installé',
    wake_model_mismatch:'le modèle installé ne correspond pas à l’empreinte attendue',
    wake_model_load_failed:'le modèle ne se charge pas',
    wake_config_invalid:'la configuration du moteur est refusée (mot inconnu ?)',
    wake_inference_failed:'l’analyse du son a échoué',
    wake_input_unavailable:'le micro a refusé de s’ouvrir',
    wake_backend_closed:'le détecteur était déjà fermé',
    wake_subscription_refused:'la capture partagée a refusé l’abonnement',
    wake_consume_failed:'la lecture du son a échoué',
  });

  const SAFE_CODE=/^[a-z0-9_.]{1,64}$/;

  function explainError(code,detail){
    const known=typeof code==='string'&&Object.prototype.hasOwnProperty.call(ERROR_TEXT,code);
    return {
      code:typeof code==='string'&&SAFE_CODE.test(code)?code:null,
      known,
      text:known?ERROR_TEXT[code]
        :'Le serveur a refusé ce réglage pour une raison que cette page ne sait pas traduire.',
      detail:typeof detail==='string'&&detail&&detail!==ERROR_TEXT[code]?detail:'',
      field:known?fieldOfCode(code):null,
    };
  }

  /* Le champ que le code accuse (aria-invalid), s'il y en a un. */
  function fieldOfCode(code){
    const match=/^wake_word_(enabled|provider|keyword|sensitivity|cooldown)_/.exec(String(code||''));
    if(!match)return null;
    return match[1]==='cooldown'?'cooldown_ms':match[1];
  }

  /* --- le formulaire ---------------------------------------------------- */

  function defaultKeyword(state,provider){
    const info=state&&state.providers&&state.providers[provider];
    return info&&typeof info.default_keyword==='string'?info.default_keyword:'';
  }

  function keywordChoices(state){
    const info=state&&state.providers&&state.providers[PROVIDER_OPENWAKEWORD];
    return info&&Array.isArray(info.keywords)?info.keywords.slice():[];
  }

  /* Le formulaire est fait de TEXTES (ce que les champs contiennent), pas de
     nombres : « 1,5 » ou « » doivent pouvoir être tapés, envoyés et refusés. */
  function formFromState(state){
    const s=state||{};
    return {
      enabled:s.enabled===true,
      provider:typeof s.provider==='string'?s.provider:PROVIDER_PORCUPINE,
      keyword:typeof s.keyword==='string'?s.keyword:'',
      sensitivity:s.sensitivity===undefined||s.sensitivity===null?'':String(s.sensitivity),
      cooldown_ms:s.cooldown_ms===undefined||s.cooldown_ms===null?'':String(s.cooldown_ms),
    };
  }

  /* Changer de fournisseur change de jeton de mot : le défaut du nouveau
     fournisseur remplace un mot qui n'est pas le sien, comme le serveur. */
  function changeProvider(form,provider,state){
    const next={...form,provider};
    if(provider===PROVIDER_OPENWAKEWORD){
      if(!keywordChoices(state).includes(next.keyword))next.keyword=defaultKeyword(state,provider);
    }else if(keywordAdvice(provider,next.keyword)||form.provider!==provider){
      next.keyword=defaultKeyword(state,provider)||next.keyword;
    }
    return next;
  }

  function parseNumber(text){
    const raw=String(text===undefined||text===null?'':text).trim().replace(',','.');
    if(raw==='')return null;
    const value=Number(raw);
    return Number.isFinite(value)?value:raw;
  }

  /* La charge utile : toutes les valeurs, jamais devinées ni corrigées. Un
     champ vide part en `null` (le serveur dit « attend un nombre »), un texte
     non numérique part tel quel. Rien n'est borné ici. */
  function buildPayload(form){
    return {
      enabled:form.enabled===true,
      provider:form.provider,
      keyword:form.keyword,
      sensitivity:parseNumber(form.sensitivity),
      cooldown_ms:parseNumber(form.cooldown_ms),
    };
  }

  function isDirty(form,state){
    const base=formFromState(state);
    return FIELDS.some(key=>String(form[key])!==String(base[key]));
  }

  /* Conseil de saisie pour Porcupine (jamais bloquant). `null` = rien à dire. */
  function keywordAdvice(provider,value){
    if(provider!==PROVIDER_PORCUPINE)return null;
    const text=String(value===undefined||value===null?'':value);
    if(text===''||text.length>PORCUPINE_MAX_LENGTH||!new RegExp(PORCUPINE_PATTERN).test(text))
      return {code:'wake_word_keyword_unknown',text:'Attendu : minuscules sans accent, mots séparés par une espace (quatre mots au plus, 32 caractères). Exemple : jarvis.'};
    return null;
  }

  /* --- ce que chaque fournisseur exige ---------------------------------- */

  function providerInfo(provider){
    if(provider===PROVIDER_OPENWAKEWORD)return {
      label:PROVIDER_LABEL[provider],
      requires:[
        'L’extra Python « wakeword » (pip install -e ".[wakeword]").',
        'Le modèle « hey_jarvis », installé à la demande hors du dépôt, vérifié par empreinte.',
      ],
      license:'Licence : le modèle openWakeWord « hey_jarvis » est non commercial (CC BY-NC-SA 4.0) : réservé aux tests privés.',
    };
    return {
      label:PROVIDER_LABEL[PROVIDER_PORCUPINE],
      requires:['Une clé d’accès Picovoice (onglet API Keys).','Un mot intégré à la bibliothèque, par exemple « jarvis ».'],
      license:null,
    };
  }

  /* --- l'état que l'écran dit -------------------------------------------- */

  function isForeign(state){
    if(!state||typeof state!=='object')return false;
    if(Array.isArray(state.problems)&&state.problems.some(p=>p&&p.code==='wake_word_stored_version_unreadable'))return true;
    return state.stored_schema_version!==null&&state.stored_schema_version!==undefined
      &&state.schema_version!==undefined&&state.stored_schema_version!==state.schema_version;
  }

  /* `state` : la réponse de `GET`/`POST /api/wake-word`. Honnête : jamais
     « en écoute » ; le réglage est lu, et appliqué au prochain démarrage de Voice. */
  function describe(state){
    if(!state||typeof state!=='object')
      return {kind:'unknown',tone:'warn',pill:'Inconnu',title:'Réglage illisible',detail:'La page n’a pas pu lire le réglage.',
        canSave:false,foreign:false,problems:[],ignored:[],serverState:''};
    const foreign=isForeign(state);
    const problems=(Array.isArray(state.problems)?state.problems:[]).map(p=>{
      const why=explainError(p&&p.code,'');
      return {field:p&&p.field||null,code:why.code,text:why.text,known:why.known};
    });
    const ignored=(Array.isArray(state.ignored_fields)?state.ignored_fields:[]).filter(name=>typeof name==='string');
    const serverState=typeof state.state==='string'?state.state:'';
    const base={foreign,problems,ignored,serverState,canSave:!foreign};
    if(foreign)return {...base,kind:'foreign',tone:'bad',pill:'Version étrangère',
      title:'Le réglage enregistré vient d’une autre version de JARVIS',
      detail:ERROR_TEXT.wake_word_foreign_version+' Enregistrer est désactivé.'};
    if(state.unreadable||problems.length)return {...base,kind:'unreadable',tone:'bad',pill:'Bloc illisible',
      title:'Le réglage enregistré est illisible',
      detail:'Les valeurs par défaut sont affichées et appliquées, mot d’éveil du bloc inactif. Enregistrer remplace le bloc par les valeurs ci-dessous.'};
    if(state.enabled)return {...base,kind:'enabled',tone:'warn',pill:'Activé dans le réglage',
      title:'Activé dans le réglage',
      detail:'Il s’applique au prochain démarrage de Voice. Cette page ne sait pas si Voice a redémarré depuis : elle ne dit pas que le détecteur écoute.'};
    return {...base,kind:'disabled',tone:'',pill:'Désactivé',
      title:'Désactivé',
      detail:'Aucun micro de plus n’est ouvert au repos : le comportement d’avant cette fonction est inchangé.'};
  }

  /* --- le dernier événement du détecteur, d'après le journal --------------- */

  const DETECTOR_KINDS=Object.freeze({
    'wake.shared_pcm.started':'started','wake.own_stream.started':'started',
    'wake.shared_pcm.failed':'failed','wake.own_stream.failed':'failed',
    'wake.shared_pcm.closed_restart_refused':'failed',
    'wake.shared_pcm.closed':'stopped','wake.own_stream.stopped':'stopped',
  });

  function detectorCodeText(data){
    const d=data&&typeof data==='object'?data:{};
    const parts=[];
    for(const key of ['cause_code','code']){
      const code=d[key];
      if(typeof code!=='string'||!SAFE_CODE.test(code))continue;
      const said=Object.prototype.hasOwnProperty.call(DETECTOR_TEXT,code)?DETECTOR_TEXT[code]:'code inconnu de cette page';
      if(!parts.some(p=>p.code===code))parts.push({code,said});
    }
    return parts;
  }

  /* `lines` : la fin du journal, du plus ancien au plus récent. On cherche le
     dernier démarrage du détecteur, puis ce qui l'a suivi. Aucun texte libre
     du journal n'est repris (les messages de panne citent des exceptions) :
     seulement le genre, l'heure, le fournisseur et les codes stables. */
  function detectorFromTrace(lines,options){
    const opts=options||{};
    const format=typeof opts.formatTime==='function'?opts.formatTime:defaultFormatTime;
    const events=[];
    for(const line of Array.isArray(lines)?lines:[]){
      if(!line||typeof line!=='object')continue;
      const state=Object.prototype.hasOwnProperty.call(DETECTOR_KINDS,line.kind)?DETECTOR_KINDS[line.kind]:null;
      if(state)events.push({state,ts:line.ts,data:line.data});
    }
    const offline=opts.voiceOnline===false
      ?' Voice est hors ligne : cet événement date d’une exécution passée.':'';
    if(!events.length)return {kind:'none',tone:'',title:'Aucun événement du détecteur dans le journal lu',
      detail:`Les ${TRACE_LIMIT} dernières lignes du journal ne contiennent aucun démarrage, arrêt ou panne du détecteur. Soit il n’a rien journalisé récemment, soit le journal a avancé depuis.${offline}`,codes:[]};
    let start=-1;
    for(let i=events.length-1;i>=0;i-=1)if(events[i].state==='started'){start=i;break}
    /* Une panne après le dernier démarrage (ou, sans démarrage vu, la plus
       récente) l'emporte sur l'arrêt qui la suit : l'arrêt de fin de séance
       ne doit pas effacer la raison pour laquelle il n'a rien détecté. */
    const failures=events.slice(start+1).filter(e=>e.state==='failed');
    const last=events[events.length-1];
    const failed=failures.length?failures[failures.length-1]:null;
    const provider=(e=>e&&e.data&&typeof e.data.provider==='string'&&SAFE_CODE.test(e.data.provider)?e.data.provider:'')(failed||events[start>=0?start:events.length-1]);
    const when=e=>{try{return format(e&&e.ts)}catch(_error){return ''}};
    const via=provider?` (${provider})`:'';
    if(failed){
      const codes=detectorCodeText(failed.data);
      const said=codes.length?` : ${codes.map(c=>`${c.said} (${c.code})`).join(' ; ')}`:'';
      return {kind:'failed',tone:'bad',title:`Dernier événement : détecteur en panne${via}`,
        detail:`Journalisé à ${when(failed)}${said}. La touche manuelle reste utilisable.${offline}`,codes:codes.map(c=>c.code)};
    }
    if(last.state==='stopped')return {kind:'stopped',tone:'',title:`Dernier événement : détecteur arrêté${via}`,
      detail:`Journalisé à ${when(last)}. D’après le journal, pas une mesure en direct.${offline}`,codes:[]};
    return {kind:'started',tone:'warn',title:`Dernier événement : détecteur démarré${via}`,
      detail:`Journalisé à ${when(events[start])}. C’est le dernier événement du journal, pas une mesure en direct : il ne prouve pas que le détecteur écoute à cet instant.${offline}`,codes:[]};
  }

  function defaultFormatTime(ts){
    const date=new Date(ts);
    if(!ts||Number.isNaN(date.getTime()))return 'une heure inconnue';
    return date.toLocaleString('fr-FR',{dateStyle:'short',timeStyle:'medium'});
  }

  const api=Object.freeze({
    ROUTE,TRACE_ROUTE,TRACE_LIMIT,STATUS_ROUTE,FIELDS,
    PROVIDER_PORCUPINE,PROVIDER_OPENWAKEWORD,PROVIDER_LABEL,PORCUPINE_PATTERN,PORCUPINE_MAX_LENGTH,
    ERROR_TEXT,WRITE_REFUSALS,DETECTOR_TEXT,
    explainError,fieldOfCode,formFromState,changeProvider,buildPayload,isDirty,keywordAdvice,keywordChoices,
    providerInfo,describe,isForeign,detectorFromTrace,
  });
  root.JarvisWakeWordSettings=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);

/* --------------------------------------------------------------------------
   Bloc navigateur : l'onglet « Mot d'éveil ». Les tests node ne l'exécutent pas.
   -------------------------------------------------------------------------- */
(function installJarvisWakeWordSettings(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const Logic=window.JarvisWakeWordSettings;
  const TAB_ID='wakeword';
  const SECTION_ID='wakeWordSettings';
  /* `state` : la dernière réponse de la route. `form` : ce qui est tapé (survit
     à un refus). `saved` : un enregistrement a réussi depuis le chargement de la
     page (en mémoire seulement : le bandeau ne dit pas que Voice a redémarré). */
  const view={state:null,form:null,loading:false,loadError:null,busy:false,error:null,saved:null,
    detector:null,detectorBusy:false,generation:0};

  const log=(level,event,data)=>{try{console[level==='error'?'error':level==='warn'?'warn':'info']('[mot d’éveil] '+event,data||{})}catch(_error){/* console absente */}};
  const tabOpen=()=>typeof SET!=='undefined'&&SET.open&&SET.tab===TAB_ID;

  function node(tag,attrs,children){
    const el=document.createElement(tag);
    for(const [key,value] of Object.entries(attrs||{})){
      if(value===null||value===undefined||value===false)continue;
      if(key==='text')el.textContent=value;
      else if(key==='className')el.className=value;
      else el.setAttribute(key,value===true?'':String(value));
    }
    for(const child of children||[])if(child)el.append(child);
    return el;
  }

  /* Région vivante stable, hors de la section redessinée. */
  let liveEl=null;
  function announce(sentence){
    const text=String(sentence||'');
    if(!text)return;
    if(!liveEl||!liveEl.isConnected){
      liveEl=document.createElement('div');
      liveEl.id='wakeWordLive';liveEl.className='ww-sr';
      liveEl.setAttribute('role','status');liveEl.setAttribute('aria-live','polite');
      document.body.appendChild(liveEl);
    }
    liveEl.textContent='';
    setTimeout(()=>{if(liveEl)liveEl.textContent=text},30);
  }

  const bounds=()=>{
    const b=view.state&&view.state.bounds||{};
    return {
      sMin:b.sensitivity&&Number.isFinite(b.sensitivity.min)?b.sensitivity.min:0,
      sMax:b.sensitivity&&Number.isFinite(b.sensitivity.max)?b.sensitivity.max:1,
      cMin:b.cooldown_ms&&Number.isFinite(b.cooldown_ms.min)?b.cooldown_ms.min:80,
      cMax:b.cooldown_ms&&Number.isFinite(b.cooldown_ms.max)?b.cooldown_ms.max:30000,
    };
  };

  function sectionNode(){
    const section=node('section',{id:SECTION_ID,'aria-labelledby':'wwTitle','data-wake-word':''});
    section.append(
      node('h3',{id:'wwTitle',text:'Mot d’éveil'}),
      node('div',{className:'hint',style:'margin-bottom:14px',
        text:'Réveiller JARVIS en prononçant son nom, sans toucher le clavier. La touche manuelle reste toujours disponible.'}),
    );
    if(view.loading&&!view.state){
      section.append(node('div',{className:'empty',role:'status',text:'Chargement…'}));
      return section;
    }
    if(view.loadError){
      const retry=node('button',{type:'button',className:'action small','data-ww-retry':'',text:'Réessayer'});
      retry.addEventListener('click',()=>load());
      section.append(node('div',{className:'notice bad',role:'alert','data-ww-load-error':''},[
        node('strong',{text:'Réglage du mot d’éveil illisible'}),
        node('div',{className:'hint',text:view.loadError}),
        node('div',{className:'row',style:'margin-top:10px'},[retry]),
      ]));
      return section;
    }
    if(!view.state)return section;
    const model=Logic.describe(view.state);
    const form=view.form;
    const frozen=model.foreign;
    const field=view.error&&view.error.field;
    const invalid=name=>field===name?'true':null;
    /* L'erreur n'est citée que par le champ qu'elle accuse (`name`). */
    const describedWith=(name,...ids)=>ids.concat(field&&field===name?['wwError']:[]).filter(Boolean).join(' ');

    /* État effectif, lu du serveur. */
    section.append(node('div',{className:`notice ${model.tone==='bad'?'bad':model.tone==='warn'?'':'info'}`,id:'wwState','data-ww-state':model.kind},[
      node('div',{className:'row',style:'gap:8px;align-items:center;flex-wrap:wrap'},[
        node('strong',{text:'État effectif'}),
        node('span',{className:`tag ${model.tone}`,id:'wwPill','data-ww-pill':model.kind,text:model.pill}),
      ]),
      node('div',{className:'hint',text:model.detail}),
      model.serverState?node('div',{className:'hint','data-ww-server-state':'',text:'Selon le serveur : '+model.serverState}):null,
    ]));
    if(model.problems.length){
      const list=node('ul',{className:'ww-list','data-ww-problems':''});
      for(const problem of model.problems)
        list.append(node('li',{},[node('span',{className:'tag bad',text:problem.code||'code illisible'}),
          document.createTextNode(` ${problem.field?problem.field+' : ':''}${problem.text}`)]));
      section.append(node('div',{className:'notice bad'},[node('strong',{text:'Diagnostic du fichier de réglages'}),list]));
    }
    if(model.ignored.length)
      section.append(node('div',{className:'notice info','data-ww-ignored':''},[
        node('strong',{text:'Clés ignorées'}),
        node('div',{className:'hint',text:`Le bloc contient des clés que ce serveur ne connaît pas : ${model.ignored.join(', ')}. Elles sont ignorées, sans effet.`}),
      ]));

    /* Interrupteur. */
    const enabled=node('input',{type:'checkbox',id:'ww_enabled','data-ww-field':'enabled',
      'aria-describedby':describedWith('enabled','wwEnabledHint'),'aria-invalid':invalid('enabled'),disabled:frozen});
    enabled.checked=form.enabled;
    enabled.addEventListener('change',()=>{view.form.enabled=enabled.checked;noteEdited()});
    /* La case est DANS son libellé : toute la ligne (>= 24 px) est la cible. */
    section.append(node('div',{className:'field'},[
      node('label',{for:'ww_enabled',className:'ww-check'},[enabled,node('span',{text:'Activer le mot d’éveil'})]),
      node('div',{className:'hint',id:'wwEnabledHint',text:'Désactivé par défaut. Activé, cela ouvre un micro au repos : JARVIS écoute en permanence tant que Voice tourne, pour détecter le mot d’éveil. L’analyse se fait sur cet ordinateur et le son n’est pas enregistré.'}),
    ]));

    /* Fournisseur. */
    const info=Logic.providerInfo(form.provider);
    const provider=node('select',{id:'ww_provider','data-ww-field':'provider','aria-describedby':describedWith('provider','wwProviderHint'),
      'aria-invalid':invalid('provider'),disabled:frozen});
    for(const id of [Logic.PROVIDER_PORCUPINE,Logic.PROVIDER_OPENWAKEWORD])
      provider.append(node('option',{value:id,text:Logic.PROVIDER_LABEL[id],selected:form.provider===id}));
    provider.value=form.provider;
    provider.addEventListener('change',()=>{
      view.form=Logic.changeProvider(view.form,provider.value,view.state);
      noteEdited();refresh('#ww_provider');
    });
    const requires=node('ul',{className:'ww-list'});
    for(const line of info.requires)requires.append(node('li',{text:line}));
    const hintChildren=[node('div',{text:'Ce que ce fournisseur exige :'}),requires];
    if(info.license)hintChildren.push(node('div',{className:'notice','data-ww-license':'',style:'margin:8px 0 0'},[node('strong',{text:info.license})]));
    section.append(node('div',{className:'field'},[
      node('label',{for:'ww_provider',text:'Fournisseur'}),provider,
      node('div',{className:'hint',id:'wwProviderHint'},hintChildren),
    ]));

    /* Mot d'éveil : liste fermée pour openWakeWord, champ validé pour Porcupine. */
    const advice=Logic.keywordAdvice(form.provider,form.keyword);
    let keyword;
    if(form.provider===Logic.PROVIDER_OPENWAKEWORD){
      keyword=node('select',{id:'ww_keyword','data-ww-field':'keyword','aria-describedby':describedWith('keyword','wwKeywordHint'),
        'aria-invalid':invalid('keyword'),disabled:frozen});
      const choices=Logic.keywordChoices(view.state);
      const all=choices.includes(form.keyword)?choices:[form.keyword].concat(choices);
      for(const word of all)keyword.append(node('option',{value:word,text:word,selected:word===form.keyword}));
      keyword.value=form.keyword;
      keyword.addEventListener('change',()=>{view.form.keyword=keyword.value;noteEdited()});
    }else{
      keyword=node('input',{type:'text',id:'ww_keyword','data-ww-field':'keyword',autocomplete:'off',spellcheck:'false',
        maxlength:String(Logic.PORCUPINE_MAX_LENGTH+8),'aria-describedby':describedWith('keyword','wwKeywordHint'),
        'aria-invalid':invalid('keyword')||(advice?'true':null),disabled:frozen});
      keyword.value=form.keyword;
      keyword.addEventListener('input',()=>{
        view.form.keyword=keyword.value;noteEdited();
        const now=Logic.keywordAdvice(Logic.PROVIDER_PORCUPINE,keyword.value);
        const hint=document.getElementById('wwKeywordHint');
        if(hint)hint.textContent=keywordHintText(now);
        if(now)keyword.setAttribute('aria-invalid','true');else keyword.removeAttribute('aria-invalid');
      });
    }
    section.append(node('div',{className:'field'},[
      node('label',{for:'ww_keyword',text:'Mot d’éveil'}),keyword,
      node('div',{className:'hint',id:'wwKeywordHint',text:keywordHintText(advice)}),
    ]));

    /* Sensibilité : curseur + saisie, qui disent la même valeur. */
    const b=bounds();
    const range=node('input',{type:'range',id:'ww_sensitivity','data-ww-field':'sensitivity',min:String(b.sMin),max:String(b.sMax),step:'0.05',
      'aria-describedby':describedWith('sensitivity','wwSensitivityHint'),'aria-valuetext':'','aria-invalid':invalid('sensitivity'),disabled:frozen});
    const sensNumber=node('input',{type:'number',id:'ww_sensitivity_value','data-ww-field':'sensitivity_value',step:'0.05',inputmode:'decimal',
      'aria-label':'Sensibilité, valeur exacte','aria-describedby':describedWith('sensitivity','wwSensitivityHint'),'aria-invalid':invalid('sensitivity'),disabled:frozen,style:'max-width:110px'});
    const showRange=()=>{
      const n=Number(String(view.form.sensitivity).replace(',','.'));
      range.value=Number.isFinite(n)?String(Math.min(b.sMax,Math.max(b.sMin,n))):String(b.sMin);
      range.setAttribute('aria-valuetext',sensitivityWord(view.form.sensitivity));
    };
    sensNumber.value=form.sensitivity;showRange();
    range.addEventListener('input',()=>{view.form.sensitivity=range.value;sensNumber.value=range.value;range.setAttribute('aria-valuetext',sensitivityWord(range.value));noteEdited()});
    sensNumber.addEventListener('input',()=>{view.form.sensitivity=sensNumber.value;showRange();noteEdited()});
    section.append(node('div',{className:'field'},[
      node('label',{for:'ww_sensitivity',text:'Sensibilité'}),
      node('div',{className:'ww-pair'},[range,sensNumber]),
      node('div',{className:'hint',id:'wwSensitivityHint',
        text:`De ${b.sMin} à ${b.sMax}, 0,5 par défaut. Plus haut, JARVIS se réveille plus facilement mais peut se réveiller à tort (faux positifs : une conversation, la télévision). Plus bas, il se réveille moins à tort mais peut ne pas vous entendre (faux négatifs).`}),
    ]));

    /* Délai anti-rebond. */
    const cooldown=node('input',{type:'number',id:'ww_cooldown','data-ww-field':'cooldown_ms',step:'10',inputmode:'numeric',
      'aria-describedby':describedWith('cooldown_ms','wwCooldownHint'),'aria-invalid':invalid('cooldown_ms'),disabled:frozen});
    cooldown.value=form.cooldown_ms;
    cooldown.addEventListener('input',()=>{view.form.cooldown_ms=cooldown.value;noteEdited()});
    section.append(node('div',{className:'field'},[
      node('label',{for:'ww_cooldown',text:'Délai anti-rebond (ms)'}),cooldown,
      node('div',{className:'hint',id:'wwCooldownHint',
        text:`De ${b.cMin} à ${b.cMax} ms, 2000 par défaut. Après un réveil, le détecteur ignore les détections suivantes pendant ce délai. Trop court : réveils en double. Trop long : JARVIS semble sourd.`}),
    ]));

    /* Refus du serveur : le code, dit en français, et la saisie reste. */
    if(view.error){
      section.append(node('div',{className:'notice bad',role:'alert',id:'wwError',tabindex:'-1','data-ww-error':view.error.code||'unknown'},[
        node('div',{className:'row',style:'gap:8px;align-items:center;flex-wrap:wrap'},[
          node('strong',{text:'Réglage non enregistré'}),
          view.error.code?node('span',{className:'tag bad','data-ww-error-code':'',text:view.error.code}):null,
        ]),
        node('div',{text:view.error.text}),
        view.error.detail?node('div',{className:'hint',text:'Détail du serveur : '+view.error.detail}):null,
        node('div',{className:'hint',text:'Rien n’a été modifié. Votre saisie est conservée : corrigez-la puis réenregistrez.'}),
      ]));
    }

    /* Enregistrer. `disabled` si version étrangère ; occupé = `aria-disabled`
       (garde le focus clavier pendant l'écriture). */
    const save=node('button',{type:'button',className:'action primary',id:'ww_save','data-ww-save':'',disabled:frozen,
      'aria-describedby':'wwSaveHint','aria-disabled':view.busy?'true':null,'aria-busy':view.busy?'true':null,
      text:view.busy?'Enregistrement…':'Enregistrer le mot d’éveil'});
    save.addEventListener('click',()=>{if(!view.busy)save_();});
    section.append(node('div',{className:'row',style:'gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:6px'},[
      save,
      node('span',{className:'hint',id:'wwDirty',text:Logic.isDirty(view.form,view.state)?'Modifications non enregistrées.':''}),
    ]));
    /* Les cinq réglages partent ensemble, sans verrou : la route reste « dernier écrit gagne ». */
    section.append(node('div',{className:'hint',id:'wwSaveHint',style:'margin-bottom:18px',
      text:'Enregistre les cinq réglages à la fois ; si un autre onglet est ouvert, le dernier enregistrement l’emporte.'}));

    if(view.saved)
      section.append(node('div',{className:'notice ww-restart',id:'wwRestart','data-ww-restart':''},[
        node('strong',{text:'Redémarrage de Voice requis'}),
        node('div',{className:'hint',text:view.saved.message}),
        node('div',{className:'hint',text:'Redémarrez Voice pour appliquer. Cette page ne peut pas le faire ni savoir quand c’est fait.'}),
      ]));

    section.append(detectorNode());
    return section;
  }

  function keywordHintText(advice){
    return advice?advice.text
      :(view.form&&view.form.provider===Logic.PROVIDER_OPENWAKEWORD
        ?'Liste fermée : openWakeWord n’accepte que les modèles du catalogue.'
        :'Un mot intégré à Porcupine : minuscules sans accent, mots séparés par une espace. Un mot inconnu de la bibliothèque est refusé au démarrage de Voice.');
  }

  function sensitivityWord(text){
    const n=Number(String(text).replace(',','.'));
    if(!Number.isFinite(n))return 'valeur illisible';
    const word=n<0.34?'peu sensible':n>0.66?'très sensible':'moyenne';
    return `${String(n).replace('.',',')} sur 1, ${word}`;
  }

  function detectorNode(){
    const result=view.detector;
    const button=node('button',{type:'button',className:'action small',id:'ww_detector_read','data-ww-detector':'',
      'aria-disabled':view.detectorBusy?'true':null,'aria-busy':view.detectorBusy?'true':null,
      text:view.detectorBusy?'Lecture du journal…':'Relire le dernier événement'});
    button.addEventListener('click',()=>{if(!view.detectorBusy)readDetector()});
    const box=node('div',{className:`notice ${result?(result.tone==='bad'?'bad':result.tone==='warn'?'':'info'):'info'}`,id:'wwDetector',
      'data-ww-detector-kind':result?result.kind:'unread'},[
      result?node('strong',{text:result.title}):node('strong',{text:'Pas encore lu'}),
      node('div',{className:'hint',text:result?result.detail:'Aucune API n’expose l’état du détecteur en direct. Cette page peut seulement relire son dernier événement dans le journal (démarré, arrêté, en panne) : la Slice de validation avec un vrai micro le confirmera.'}),
    ]);
    return node('div',{id:'wwHealth','aria-labelledby':'wwHealthTitle',style:'margin-top:6px'},[
      node('h4',{id:'wwHealthTitle',text:'Détecteur : dernier événement connu'}),
      box,node('div',{className:'row',style:'margin-top:8px'},[button]),
    ]);
  }

  /* Redessine la section en gardant le focus sur le contrôle qui l'avait. */
  function refresh(focusSelector){
    if(!tabOpen())return;
    const content=document.getElementById('modalContent');
    const previous=document.getElementById(SECTION_ID);
    if(!content||!previous)return;
    const active=document.activeElement;
    const key=focusSelector||(previous.contains(active)&&active.id?'#'+active.id:null);
    /* Champ texte actif : le curseur (ou la sélection) est rendu où il était. */
    let caret=null;
    try{
      if(key&&active&&previous.contains(active)&&'#'+active.id===key&&typeof active.selectionStart==='number')
        caret=[active.selectionStart,active.selectionEnd,active.selectionDirection||'none'];
    }catch(_error){/* type sans sélection */}
    const next=sectionNode();
    previous.replaceWith(next);
    if(key){
      const target=next.querySelector(key);
      if(target&&!target.disabled)try{
        target.focus({preventScroll:true});
        if(caret&&typeof target.setSelectionRange==='function')target.setSelectionRange(caret[0],caret[1],caret[2]);
      }catch(_error){/* retiré entre-temps, ou type sans sélection */}
    }
  }

  /* Ne redessine que le bloc du détecteur : les champs, leur focus et leur
     curseur ne sont pas touchés (lire le journal n'a rien à voir avec la saisie). */
  function refreshDetector(){
    if(!tabOpen())return;
    const previous=document.getElementById('wwHealth');
    if(!previous){refresh();return}
    const active=document.activeElement;
    const key=previous.contains(active)&&active.id?'#'+active.id:null;
    const next=detectorNode();
    previous.replaceWith(next);
    if(key){
      const target=next.querySelector(key);
      if(target&&!target.disabled)try{target.focus({preventScroll:true})}catch(_error){/* retiré entre-temps */}
    }
  }

  function noteEdited(){
    const dirty=document.getElementById('wwDirty');
    if(dirty)dirty.textContent=Logic.isDirty(view.form,view.state)?'Modifications non enregistrées.':'';
  }

  /* Lit la route. Le dernier appel gagne : chaque lecture porte un numéro, une
     réponse qui arrive après une lecture plus récente est ignorée (deux rendus
     coup sur coup, ou une relecture après un refus).
     `keep` : relecture sur place, sans effacer l'écran ni la saisie en cours ;
     `keepError` garde le refus affiché ; `resetForm` rend la main au serveur. */
  async function load(options){
    const opts=options||{};
    const keep=Boolean(opts.keep&&view.state);
    const generation=++view.generation;
    view.loading=true;
    if(!keep){view.loadError=null;refresh()}
    try{
      const state=await api(Logic.ROUTE);
      if(generation!==view.generation)return;
      const editing=keep&&!opts.resetForm&&view.form&&Logic.isDirty(view.form,view.state);
      view.state=state;
      if(!editing)view.form=Logic.formFromState(state);
      if(!opts.keepError)view.error=null;
      view.loadError=null;
      log('info','wake_word.settings_loaded',{enabled:state.enabled,provider:state.provider});
    }catch(error){
      if(generation!==view.generation)return;
      const message=String(error&&error.message||error);
      log('error','wake_word.settings_load_failed',{error:message,status:error&&error.status});
      if(!keep)view.loadError=message;
      if(typeof toast==='function')toast({title:'Mot d’éveil : réglage illisible',sub:message,kind:'bad',ms:7000});
    }finally{
      if(generation===view.generation){
        view.loading=false;refresh();
        if(!keep||!view.detector)readDetector();
      }
    }
  }

  async function save_(){
    if(view.busy||!view.state||Logic.describe(view.state).foreign)return;
    view.busy=true;view.error=null;refresh('#ww_save');
    const payload=Logic.buildPayload(view.form);
    log('info','wake_word.save_requested',{enabled:payload.enabled,provider:payload.provider});
    try{
      const state=await api(Logic.ROUTE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      view.state=state;view.form=Logic.formFromState(state);
      view.saved={message:String(state.restart_message||'Réglage enregistré ; il ne s’applique qu’au prochain démarrage de Voice.')};
      if(typeof SET!=='undefined'&&SET.restartNotice!==undefined)SET.restartNotice=true;
      log('info','wake_word.saved',{enabled:state.enabled,provider:state.provider});
      announce('Réglage du mot d’éveil enregistré. Redémarrage de Voice requis.');
      if(typeof toast==='function')toast({title:'Mot d’éveil enregistré',sub:'Redémarrage de Voice requis pour l’appliquer.',kind:'ok',ms:4500});
    }catch(error){
      /* La saisie (`view.form`) n'est pas touchée : seul le refus s'affiche. */
      const why=Logic.explainError(error&&error.code,error&&error.message);
      view.error=error&&error.code?why:{...why,text:`Le Control Center n’a pas répondu comme prévu : ${String(error&&error.message||error)}`,detail:''};
      log('error','wake_word.save_failed',{code:error&&error.code,status:error&&error.status});
      /* Une seule voie pour l'erreur : la boîte `role=alert` (pas de région polie en plus). */
      if(typeof toast==='function')toast({title:'Mot d’éveil non enregistré',sub:(why.code?why.code+' : ':'')+view.error.text,kind:'bad',ms:8000});
      /* Un refus qui révèle un état périmé (un JARVIS plus récent a écrit le bloc
         depuis le chargement) : relire la route, pour que la page redise la vérité
         (champs et bouton figés), en gardant le message d'erreur. */
      if(error&&error.code==='wake_word_foreign_version')await load({keep:true,keepError:true,resetForm:true});
    }finally{
      view.busy=false;
      refresh('#ww_save');
      if(view.error){
        const alertBox=document.getElementById('wwError'),saveButton=document.getElementById('ww_save');
        if(alertBox){
          alertBox.scrollIntoView({block:'nearest'});
          /* Bouton figé : le focus irait dans le vide, il passe à l'erreur. */
          if(saveButton&&saveButton.disabled)try{alertBox.focus({preventScroll:true})}catch(_error){/* retiré */}
        }
      }
    }
  }

  async function readDetector(){
    if(view.detectorBusy||!tabOpen())return;
    view.detectorBusy=true;refreshDetector();
    try{
      const [lines,status]=await Promise.all([
        api(Logic.TRACE_ROUTE),
        api(Logic.STATUS_ROUTE).catch(()=>null),
      ]);
      view.detector=Logic.detectorFromTrace(Array.isArray(lines)?lines:[],{voiceOnline:status&&typeof status.voice_online==='boolean'?status.voice_online:undefined});
    }catch(error){
      view.detector={kind:'unavailable',tone:'bad',title:'Journal illisible',
        detail:`Le dernier événement du détecteur n’a pas pu être lu : ${String(error&&error.message||error)}`,codes:[]};
      log('error','wake_word.detector_read_failed',{status:error&&error.status});
    }finally{
      view.detectorBusy=false;refreshDetector();
    }
  }

  const STYLE=`#wakeWordSettings .ww-list{margin:6px 0 0;padding-left:18px}
#wakeWordSettings .ww-pair{display:flex;gap:12px;align-items:center}
#wakeWordSettings .ww-pair input[type=range]{flex:1;width:auto;height:28px;min-height:28px;padding:0;accent-color:var(--accent)}
#wakeWordSettings input[aria-invalid=true],#wakeWordSettings select[aria-invalid=true]{border-color:var(--danger)}
#wakeWordSettings input:focus-visible,#wakeWordSettings select:focus-visible,#wakeWordSettings button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
#wakeWordSettings [aria-disabled=true]{opacity:.6;cursor:wait}
#wakeWordSettings :disabled{opacity:.6;cursor:not-allowed}
#wakeWordSettings input:disabled,#wakeWordSettings select:disabled{border-style:dashed;background-image:repeating-linear-gradient(135deg,transparent 0 6px,rgba(255,255,255,.07) 6px 12px)}
#wakeWordSettings .ww-check{display:flex;align-items:center;gap:10px;min-height:32px;width:fit-content;max-width:100%;cursor:pointer;color:var(--text);font-size:13px}
#wakeWordSettings .ww-check input[type=checkbox]{width:20px;height:20px;padding:0;margin:0;flex:none}
#wakeWordSettings input[type=checkbox]:disabled+span{text-decoration:underline dotted}
#wakeWordSettings #wwHealthTitle{margin:18px 0 8px;font-size:11px;font-weight:normal;letter-spacing:.06em;color:var(--muted)}
#wakeWordSettings #wwError:focus{outline:2px solid var(--accent);outline-offset:2px}
#wakeWordSettings .ww-restart{animation:wwIn .25s ease-out}
@keyframes wwIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){#wakeWordSettings .ww-restart{animation:none}}
.ww-sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}`;

  function ensureStyle(){
    if(document.getElementById('jarvisWakeWordStyle'))return;
    const style=document.createElement('style');
    style.id='jarvisWakeWordStyle';style.textContent=STYLE;
    document.head.appendChild(style);
  }

  /* L'onglet se glisse juste après « Voix » (même famille) et dessine sa
     section dans le contenu de la fenêtre de réglages. */
  function installTab(){
    if(typeof TABS==='undefined'||!Array.isArray(TABS)||typeof renderTab!=='function'||TABS.some(tab=>tab.id===TAB_ID))return;
    ensureStyle();
    const after=TABS.findIndex(tab=>tab.id==='voice');
    TABS.splice(after>=0?after+1:TABS.length,0,{id:TAB_ID,label:'Mot d’éveil',save:false});
    const baseRenderTab=renderTab;
    renderTab=async function(){
      if(SET.tab!==TAB_ID)return baseRenderTab.apply(this,arguments);
      if(typeof cleanupSettingsSurface==='function')cleanupSettingsSurface();
      SET.renderRevision=(SET.renderRevision||0)+1;
      modalSave.style.display='none';
      modalSub.textContent='Le mot d’éveil est enregistré tout de suite et appliqué au prochain démarrage de Voice.';
      /* Déjà dessiné et lu (par exemple `openSettings` rappelle `renderTab` quand
         `/api/settings` arrive après un clic sur l'onglet) : relire sur place,
         sans effacer l'écran. */
      const shown=document.getElementById(SECTION_ID);
      if(shown&&modalContent.contains(shown)&&view.state){load({keep:true});return}
      modalContent.innerHTML='';
      modalContent.append(sectionNode());
      say('','');
      view.error=null;view.state=null;view.form=null;view.loadError=null;
      load();
    };
  }

  setTimeout(installTab,0);
  window.JarvisWakeWordSettingsView=Object.freeze({
    inspect:()=>({state:view.state,form:view.form?{...view.form}:null,busy:view.busy,error:view.error,saved:view.saved,detector:view.detector}),
  });
})();
