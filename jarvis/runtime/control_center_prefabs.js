/* Bibliothèque des prefabs — vue plein écran du dock `PFB`
   (handoff jarvis-scene-window-prefab-foundation, Slice 08).

   Contrat : `docs/prefabs.md` › *Library UI*, *Control Center routes*,
   *Publication and provenance*. Ce que la vue permet : parcourir, chercher,
   filtrer, inspecter (entrées, événements, versions, provenance), prévisualiser
   avec les données d'exemple, « Placer sur la scène » et « Forker en nouveau
   prefab ». Elle n'édite AUCUNE source et n'offre AUCUNE édition de base.

   Deux parties, comme `control_center_workspace.js` :

   - `JarvisPrefabLibraryCore`, logique pure exécutée telle quelle par node :
     vocabulaire, client HTTP borné, modèle de provenance et de badges, filtre,
     tri, chaîne de provenance, arbre des entrées, candidat de fork, commande
     de scène, et le contrôleur (`createLibrary`) ;
   - un bloc navigateur qui construit la vue en DOM (`createElement` et
     `textContent` seulement : aucun balisage en chaîne dans ce fichier).

   CINQ RÈGLES TIENNENT CE FICHIER.

   1. LE CATALOGUE DE CORE EST LA SEULE VÉRITÉ. Les lignes viennent de
      `GET /api/prefabs`, la provenance de `GET /api/prefabs/{id}` (historique
      de `publication.json`). Aucune liste écrite à la main ; la vue relit à
      chaque ouverture, sur « Actualiser » et après chaque fork : un prefab
      publié par JARVIS apparaît sans changer la page.
   2. ROUTES BORNÉES. Le client refuse avant le réseau toute adresse hors des
      lectures `/api/prefabs*`, de `POST /api/prefabs` (fork, acteur forcé à
      `user` par le Control Center) et de `POST /api/scene/commands` (placer).
      Aucune route d'édition de base n'existe côté Control Center.
   3. L'APERÇU NE PARLE À PERSONNE. Il passe par `JarvisPrefabHost` en mode
      `preview` : les événements du cadre s'affichent dans le journal local de
      la vue et ne sont jamais postés à Core.
   4. FORKER N'EST PAS MODIFIER. Le fork copie la source sans la changer et
      publie un NOUVEL identifiant ; une base ne change que par JARVIS, sur
      demande explicite de l'utilisateur (porte `prefab_edit_base`). La vue
      le dit au lieu d'offrir un bouton. Un id `jarvis.*` saisi dans le
      formulaire part quand même : c'est Core qui le refuse (`base_protected`)
      et la vue affiche son refus.
   5. CE QUI ATTEND SE VOIT. Lecture, publication et placement montrent leur
      libellé et un compteur de secondes, ont une échéance (`DEADLINE_MS`) et
      finissent en erreur codée avec un recours ; rien n'est avalé. */

const JarvisPrefabLibraryCore=(function(){
  'use strict';

  /* Le relais attend Core 10 s en lecture ; publier écrit sur disque. */
  const DEADLINE_MS=Object.freeze({read:15000,write:35000});
  const LIST_LIMIT=50;
  const DETAIL_CONCURRENCY=4;
  const CHAIN_MAX=16;
  const LOG_CAP=50;
  const PREVIEW_OBJECT_ID='pfb-preview';
  /* Grammaire d'id de `jarvis/domain/_checks.py` (`PREFAB_ID`) ; pré-contrôle
     de forme seulement, Core reste l'autorité. */
  const PREFAB_ID=/^[a-z][a-z0-9_-]{0,31}(\.[a-z][a-z0-9_-]{0,31}){1,3}$/;
  const MAX_ID_CHARS=96;
  const BASE_PREFIX='jarvis.';

  /* Les quatre natures d'un prefab, dans l'ordre du filtre. Couleur doublée
     d'un mot et d'une icône, jamais seule. */
  const KINDS=Object.freeze([
    {key:'base',label:'Base',plural:'Base',tone:'base',icon:'lock',
      means:'Livré avec JARVIS, jamais modifié. Protégé : seul JARVIS peut le modifier, à votre demande explicite.'},
    {key:'base_edited',label:'Base modifiée à votre demande',plural:'Base modifiée',tone:'edited',icon:'pen',
      means:'Prefab de base modifié par JARVIS à votre demande ; vos mots sont cités dans son historique.'},
    {key:'fork',label:'Fork',plural:'Forks',tone:'fork',icon:'branch',
      means:'Copie d’un autre prefab sous un nouvel identifiant ; le prefab d’origine est indiqué.'},
    {key:'custom',label:'Custom',plural:'Custom',tone:'custom',icon:'spark',
      means:'Créé de toutes pièces sur ce poste, par vous ou par JARVIS.'},
  ]);
  const KIND_BY_KEY=Object.freeze(Object.fromEntries(KINDS.map(k=>[k.key,k])));

  /* Contrat sémantique du catalogue (Slice 17, `docs/prefabs.md` › Semantic catalog) : MÊMES mots pour tous les moteurs, jamais
     traduits par moteur. Les identifiants sont ceux de Core ; l'étiquette est la seule part de français. */
  const SEMANTIC_TYPES=Object.freeze([
    {key:'component',label:'Composant',means:'Un élément réutilisable (fenêtre, widget).'},
    {key:'composition',label:'Composition',means:'Une scène animée composée de plusieurs éléments.'},
    {key:'page',label:'Page',means:'Une page complète.'},
    {key:'presentation',label:'Présentation',means:'Une présentation entière.'},
    {key:'asset',label:'Ressource',means:'Une ressource (image, média, police…).'},
  ]);
  const TYPE_BY_KEY=Object.freeze(Object.fromEntries(SEMANTIC_TYPES.map(t=>[t.key,t])));
  const ENGINES=Object.freeze([{key:'slidecar',label:'Slidecar'},{key:'remotion',label:'Remotion'}]);
  const SUPPORT=Object.freeze({
    native:{label:'natif',means:'Le moteur le fait lui-même.',icon:'check'},
    adapter:{label:'adaptateur',means:'Possible seulement par une étape d’adaptation explicite, visible dans la source ; jamais appliquée seule. Déclaré, pas encore utilisable dans une présentation : aucune étape d’adaptation n’existe.',icon:'arrow'},
    unsupported:{label:'non pris en charge',means:'Impossible dans ce moteur : signalé, jamais deviné ni aplati en capture.',icon:'ban'},
  });

  /* `publication.json` › `provenance.origin` et `created_by.actor`. */
  const ORIGINS=Object.freeze({base:'Livrée avec JARVIS',custom:'Création',fork:'Fork',revision:'Révision',base_edit:'Édition de base'});
  const ACTORS=Object.freeze({system:'JARVIS (livré)',brain:'JARVIS',user:'vous'});
  const EVENT_CLASSES=Object.freeze({
    state:{label:'État',means:'écrit dans les données de la fenêtre (enregistré par Core)'},
    notify:{label:'Signal',means:'prévient JARVIS à son prochain tour ; n’écrit rien'},
  });
  const VERSION_STATUS=Object.freeze({ok:'',tampered:'altérée (empreinte différente)',unreadable:'illisible',
    conflict:'en conflit avec le paquet livré'});

  const ERRORS=Object.freeze({
    base_protected:{title:'Identifiant réservé aux prefabs de base',
      say:'Core refuse cet identifiant : le préfixe « jarvis. » appartient aux prefabs livrés avec JARVIS.',
      hint:'Le préfixe « jarvis. » est réservé. Forker ne modifie jamais une base : choisissez votre propre préfixe (par exemple « team. »). Seul JARVIS modifie une base, et seulement à votre demande explicite.'},
    id_taken:{title:'Identifiant déjà pris',say:'Un prefab de la bibliothèque porte déjà cet identifiant : rien n’a été publié.',
      hint:'Forker publie toujours un NOUVEL identifiant ; reprendre celui d’un prefab existant le modifierait. Choisissez-en un autre, par exemple en ajoutant « -2 ».'},
    invalid_definition:{title:'Définition refusée par Core',hint:'Corrigez les points listés puis publiez de nouveau ; rien n’a été écrit.'},
    version_exists:{title:'Version déjà publiée',hint:'Une version publiée n’est jamais réécrite. Relisez la bibliothèque.'},
    unknown_prefab:{title:'Prefab introuvable',hint:'Il n’est plus dans la bibliothèque : actualisez.'},
    unknown_version:{title:'Version introuvable',hint:'Actualisez la bibliothèque.'},
    tampered:{title:'Version altérée',hint:'Ses fichiers ne correspondent plus à leur empreinte : Core la refuse. Lisez core.prefab.tampered dans la trace.'},
    storage_io:{title:'Disque en échec',hint:'Core n’a pas pu lire ou écrire la bibliothèque. Lisez la trace de Core.'},
    invalid_request:{title:'Requête refusée',hint:'Paramètre ou corps refusé par l’API.'},
    prefab_invalid:{title:'Instance refusée par Core',hint:'Les données d’exemple ne valident pas ce prefab : rien n’a été placé.'},
    scene_unavailable:{title:'Scène indisponible',hint:'La scène de Core n’accepte pas d’écriture pour l’instant. Réessayez.'},
    core_unavailable:{title:'Core indisponible',hint:'Core démarre ou ne sert pas encore les prefabs. Réessayez dans un instant.'},
    core_unreachable:{title:'Core ne répond pas',hint:'Vérifiez que Core tourne, puis réessayez.'},
    core_unconfigured:{title:'Core non configuré',hint:'Le Control Center ne connaît pas Core.'},
    core_timeout:{title:'Core n’a pas répondu à temps',hint:'L’issue d’une écriture est inconnue : actualisez avant de recommencer.'},
    not_configured:{title:'Scène non reliée à Core',hint:'La scène n’est pas active dans ce Control Center.'},
    forbidden_origin:{title:'Origine refusée',hint:'La bibliothèque n’accepte que la page locale du Control Center.'},
    forbidden_route:{title:'Adresse refusée par la page',hint:'Défaut de la page : rien n’a été envoyé.'},
    missing_id:{title:'Identifiant manquant',hint:'Donnez un identifiant au nouveau prefab, par exemple « team.checklist-red ».'},
    timeout:{title:'Pas de réponse',hint:'Aucune réponse dans le délai. Pour une écriture, l’issue est inconnue : actualisez avant de recommencer.'},
    network:{title:'Control Center injoignable',hint:'La requête n’a pas abouti. Vérifiez que le Control Center tourne, puis réessayez.'},
    bad_response:{title:'Réponse illisible',hint:'La réponse n’est pas le JSON attendu.'},
    preview_unavailable:{title:'Aperçu indisponible',hint:'Rechargez la page du Control Center ; le reste de la bibliothèque fonctionne.'},
    preview_failed:{title:'Aperçu impossible',hint:'« Réinitialiser » remonte l’aperçu ; lisez la console de la page (prefabs.preview_*).'},
  });
  /* Refus de scène (`reason` d'une réponse 200 de `POST /api/scene/commands`). */
  const SCENE_REFUSALS=Object.freeze({prefab_invalid:'prefab_invalid'});

  /* ------------------------------------------------------------- outillage */
  function isObject(v){return !!v&&typeof v==='object'&&!Array.isArray(v)}
  function list(v){return Array.isArray(v)?v:[]}
  function clone(v){return v===undefined?undefined:JSON.parse(JSON.stringify(v))}
  function plural(n,one,many){return `${n} ${n===1?one:many}`}
  function formatSeconds(ms){return `${Math.max(0,Math.floor((Number(ms)||0)/1000))} s`}
  function formatWhen(iso){
    const d=new Date(iso);
    if(!iso||Number.isNaN(d.getTime()))return iso?String(iso):'—';
    const p=n=>String(n).padStart(2,'0');
    return `${p(d.getDate())}/${p(d.getMonth()+1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  function isPrefabId(v){return typeof v==='string'&&v.length<=MAX_ID_CHARS&&PREFAB_ID.test(v)}
  function isBaseId(v){return typeof v==='string'&&v.startsWith(BASE_PREFIX)}
  function ref(raw){
    return isObject(raw)&&typeof raw.id==='string'&&Number.isInteger(raw.version)?{id:raw.id,version:raw.version}:null;
  }
  function refText(r){return r?`${r.id} v${r.version}`:'—'}
  function apiError(code,status,message,extra){
    const error=new Error(message||code);
    error.code=code;error.status=status||0;
    if(extra&&Array.isArray(extra.errors))error.errors=extra.errors.map(String).slice(0,20);
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
    search:q=>`/api/prefabs${query({query:q,limit:LIST_LIMIT,catalog:1})}`,
    detail:id=>`/api/prefabs/${seg(id)}${query({catalog:1})}`,
    version:(id,v,source)=>`/api/prefabs/${seg(id)}/${seg(v)}${query({include_source:source?1:null,catalog:1})}`,
    save:()=>'/api/prefabs',
    scene:()=>'/api/scene/commands',
  });

  /* Adresse permise : GET sous `/api/prefabs` (liste, un id, une version),
     POST sur `/api/prefabs` et `/api/scene/commands` exactement. Une
     adresse absolue de la page, sans segment vide, `.` ou `..` (même encodé). */
  function allowed(method,path){
    if(typeof path!=='string'||/[#\\]/.test(path)||!/^\/[^/]/.test(path))return false;
    const bare=path.split('?')[0];
    const segments=bare.split('/').slice(1);
    if(segments.some(s=>{let plain;try{plain=decodeURIComponent(s)}catch(_){return true}return plain===''||plain==='.'||plain==='..'}))return false;
    if(method==='POST')return (bare==='/api/prefabs'||bare==='/api/scene/commands')&&!path.includes('?');
    if(method!=='GET'||segments[0]!=='api'||segments[1]!=='prefabs')return false;
    if(segments.length===2)return true;
    if(segments.length===3)return segments[2]!=='events'&&segments[2]!=='validate';
    return segments.length===4&&/^[0-9]{1,4}$/.test(segments[3]);
  }

  function createClient({fetchImpl,setTimer=setTimeout,clearTimer=clearTimeout}={}){
    async function call(method,path,body){
      if(!allowed(method,path))throw apiError('forbidden_route',0,`adresse refusée par la page : ${method} ${path}`);
      const deadlineMs=method==='GET'?DEADLINE_MS.read:DEADLINE_MS.write;
      const controller=typeof AbortController==='function'?new AbortController():null;
      let timedOut=false;
      const timer=setTimer(()=>{timedOut=true;if(controller)controller.abort()},deadlineMs);
      const late=`aucune réponse en ${Math.round(deadlineMs/1000)} s`;
      try{
        let response;
        try{
          response=await fetchImpl(path,{method,cache:'no-store',
            headers:body!==undefined?{Accept:'application/json','Content-Type':'application/json'}:{Accept:'application/json'},
            body:body!==undefined?JSON.stringify(body):undefined,signal:controller?controller.signal:undefined});
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
          /* Enveloppe `{error:{code,message,errors?}}` des routes relayées de Core. */
          const envelope=isObject(payload)&&isObject(payload.error)?payload.error:null;
          const code=(envelope&&envelope.code)||(isObject(payload)&&typeof payload.code==='string'?payload.code:'')
            ||(response.ok?'bad_response':`http_${response.status}`);
          const message=(envelope&&envelope.message)||(isObject(payload)&&typeof payload.error==='string'?payload.error:'')
            ||text.slice(0,200)||`HTTP ${response.status}`;
          throw apiError(code,response.status,message,envelope);
        }
        return {status:response.status,body:payload};
      }finally{clearTimer(timer)}
    }
    return {
      get:async path=>(await call('GET',path)).body,
      post:(path,body)=>call('POST',path,body),
    };
  }

  /* Code montré : celui de Core, sauf un id déjà pris, que Core ne signale
     que par `invalid_definition` « <id> already exists… » (aucun code propre,
     `prefab_service.save`) : il devient `id_taken`, le code de Core reste
     dans `coreCode`. */
  function codeOf(error){
    const code=(error&&error.code)||'network';
    if(code==='invalid_definition'&&/\balready exists\b/i.test(String(error&&error.message||'')))return 'id_taken';
    return code;
  }
  /* Vue d'une erreur. Un code dont le texte est écrit ici (`say`) remplace le
     message anglais de Core (resté dans la console, `prefabs.*_failed`). */
  function errorView(error){
    const raw=(error&&error.code)||'network';
    const code=codeOf(error);
    const known=ERRORS[code]||{title:'Erreur de la bibliothèque',hint:'Réessayez ; lisez la trace du Control Center et de Core si cela persiste.'};
    const message=known.say||((error&&error.message)?String(error.message):'échec sans message');
    return {title:known.title,hint:known.hint,code,coreCode:raw,status:(error&&error.status)||0,message,
      errors:known.say?[]:list(error&&error.errors).map(String)};
  }

  /* --------------------------------------------- provenance et badges (purs)

     `lineageOf(detail)` lit l'historique de `GET /api/prefabs/{id}` (une ligne
     par version : `origin`, `derived_from`, `created_by`, `base_edit`,
     `published_at`, `status`). La nature d'un prefab vient de sa PREMIÈRE
     version saine (comment l'identifiant est né), le badge « révision » de la
     dernière. */
  function versionsOf(detail){
    return list(detail&&detail.history).filter(isObject).filter(r=>Number.isInteger(r.version))
      .slice().sort((a,b)=>a.version-b.version)
      .map(r=>{
        const edit=isObject(r.base_edit)?{request:String(r.base_edit.user_request||''),
          witness:String(r.base_edit.witness||''),confirmed:r.base_edit.confirmed_by_user===true}:null;
        return {version:r.version,origin:typeof r.origin==='string'?r.origin:null,
          actor:isObject(r.created_by)&&typeof r.created_by.actor==='string'?r.created_by.actor:null,
          at:typeof r.published_at==='string'?r.published_at:null,derivedFrom:ref(r.derived_from),
          status:typeof r.status==='string'?r.status:'ok',problem:typeof r.problem==='string'?r.problem:'',
          root:typeof r.root==='string'?r.root:null,baseEdit:edit};
      });
  }
  function lineageOf(detail){
    if(!isObject(detail)||typeof detail.id!=='string')return null;
    const versions=versionsOf(detail);
    const healthy=versions.filter(v=>v.status==='ok');
    const first=healthy[0]||null,last=healthy[healthy.length-1]||null;
    const forked=healthy.find(v=>v.origin==='fork');
    return {id:detail.id,born:first?first.origin:null,parent:forked?forked.derivedFrom:null,
      latestOrigin:last?last.origin:null,latestVersion:last?last.version:null,
      versions,baseEdits:versions.filter(v=>v.origin==='base_edit'),
      creator:first?first.actor:null};
  }
  /* `failed` : la lecture de l'historique a échoué (après son échéance) ;
     la nature d'un non-base est alors `unknown`, jamais devinée. */
  function kindOf(row,lineage,failed){
    if(!isObject(row))return null;
    if(row.class==='base')return row.base_edited||(lineage&&lineage.baseEdits.length)?'base_edited':'base';
    if(!lineage)return failed?'unknown':null;
    return lineage.born==='fork'?'fork':'custom';
  }
  /* Badges d'une ligne : UN badge de nature (« Provenance… » tant que la
     provenance d'un custom n'est pas lue), plus « Révision » si la dernière
     version en est une. Une base modifiée n'a que son badge ambre : il dit
     déjà « base ». */
  function badgesOf(row,lineage,failed){
    const out=[];
    const kind=kindOf(row,lineage,failed);
    if(kind==='base'){
      out.push({key:'base',label:'Base',tone:'base',icon:'lock',title:KIND_BY_KEY.base.means});
    }else if(kind==='base_edited'){
      const n=lineage?lineage.baseEdits.length:0;
      out.push({key:'base_edited',label:KIND_BY_KEY.base_edited.label,tone:'edited',icon:'pen',
        title:n?`${plural(n,'édition de base','éditions de base')} faite(s) par JARVIS à votre demande ; vos mots sont cités dans l’historique`
          :KIND_BY_KEY.base_edited.means});
    }else if(kind===null){
      out.push({key:'pending',label:'Provenance…',tone:'muted',icon:null,title:'Lecture de l’historique de ce prefab'});
    }else if(kind==='unknown'){
      out.push({key:'unknown',label:'Provenance inconnue',tone:'bad',icon:null,
        title:'L’historique de ce prefab n’a pas pu être lu : fork ou custom ? Choisissez-le pour réessayer, ou « Actualiser ».'});
    }else{
      const k=KIND_BY_KEY[kind];
      out.push({key:kind,label:k.label,tone:k.tone,icon:k.icon,
        title:kind==='fork'&&lineage.parent?`Fork de ${refText(lineage.parent)}`:k.means});
    }
    if(lineage&&lineage.latestOrigin==='revision')
      out.push({key:'revision',label:`Révision v${lineage.latestVersion}`,tone:'muted',icon:null,
        title:'La dernière version est une révision du même prefab'});
    return out;
  }
  /* Ligne enrichie : la ligne du catalogue, sa provenance (ou `null`), sa nature, ses badges. */
  function entryOf(row,lineage,failed){
    return {row,lineage:lineage||null,kind:kindOf(row,lineage,failed),badges:badgesOf(row,lineage,failed),
      parent:lineage&&lineage.parent?lineage.parent:null};
  }
  /* Contrat sémantique d'une ligne ou d'un détail : lu tel que Core le rend, `null` tant qu'il n'est pas là. Un moteur que
     Core ne liste pas est « non pris en charge », jamais « inconnu » ni « pris en charge ». */
  function catalogOf(source){
    const c=isObject(source)?source.catalog:null;
    return isObject(c)&&typeof c.type==='string'&&isObject(c.compatibility)?c:null;
  }
  function supportOf(catalog,engine){
    const c=catalogOf({catalog});
    const value=c&&typeof c.compatibility[engine]==='string'?c.compatibility[engine]:'unsupported';
    return value in SUPPORT?value:'unsupported';
  }
  function typeLabel(key){return TYPE_BY_KEY[key]?TYPE_BY_KEY[key].label:String(key)}
  function stacksOf(entries){
    return [...new Set(list(entries).flatMap(e=>{const c=catalogOf(e.row);return c?list(c.stack):[]}).filter(t=>typeof t==='string'&&t))].sort();
  }
  function familiesOf(entries){
    return [...new Set(list(entries).map(e=>e.row.family).filter(f=>typeof f==='string'&&f))].sort();
  }
  function countsOf(entries){
    const counts={all:0,base:0,base_edited:0,fork:0,custom:0};
    for(const e of list(entries)){
      counts.all+=1;
      if(e.kind==='unknown'){counts.fork+=1;counts.custom+=1}
      else if(e.kind&&e.kind in counts)counts[e.kind]+=1;
    }
    return counts;
  }
  /* Filtre local : nature (`all` ou une de `KINDS`) et famille. Le texte est
     cherché par Core (`?query=`, alias et étiquettes compris). Une ligne dont
     la provenance est EN COURS de lecture ne passe que le filtre `all` ou
     `base` (une base est connue par sa classe) ; une ligne dont la lecture a
     ÉCHOUÉ (`unknown`) reste sous Fork ET Custom, marquée « Provenance
     inconnue » : un échec ne cache jamais une ligne. */
  function filterEntries(entries,{kind='all',family='',type='',engine='',stack=''}={}){
    return list(entries).filter(e=>{
      if(family&&e.row.family!==family)return false;
      if(type||engine||stack){
        /* Sans contrat lu (réponse d'un Core plus ancien) : une ligne ne passe aucun filtre sémantique, jamais « devinée ». */
        const c=catalogOf(e.row);
        if(!c)return false;
        if(type&&c.type!==type)return false;
        if(engine&&supportOf(c,engine)==='unsupported')return false;
        if(stack&&!list(c.stack).includes(stack))return false;
      }
      if(kind==='all')return true;
      if(e.kind==='unknown')return kind==='fork'||kind==='custom';
      return e.kind===kind;
    });
  }
  /* Ordre : celui de Core quand une recherche classe les lignes, sinon les
     bases d'abord puis les autres, par titre puis par id. */
  function sortEntries(entries,{ranked=false}={}){
    const rows=list(entries).slice();
    if(ranked)return rows;
    const rank=e=>(e.row.class==='base'?0:1);
    return rows.sort((a,b)=>rank(a)-rank(b)
      ||String(a.row.title||'').localeCompare(String(b.row.title||''),'fr',{sensitivity:'base'})
      ||String(a.row.id).localeCompare(String(b.row.id)));
  }
  /* Chaîne de provenance, de l'ancêtre le plus lointain au prefab : on suit
     `derived_from` d'un fork à l'autre. `lookup(id)` rend la provenance
     connue d'un id ou `null` (pas encore lue, ou absente : le maillon est
     marqué `known: false` et la chaîne s'arrête). Cycle et longueur bornés. */
  function provenanceChain(id,lookup){
    const chain=[];const seen=new Set();
    let current={id,version:null};
    while(current&&chain.length<CHAIN_MAX){
      if(seen.has(current.id)){chain.push({id:current.id,version:current.version,known:false,cycle:true});break}
      seen.add(current.id);
      const lin=typeof lookup==='function'?lookup(current.id):null;
      chain.push({id:current.id,version:current.version,known:!!lin,origin:lin?lin.born:null});
      current=lin&&lin.parent?{id:lin.parent.id,version:lin.parent.version}:null;
    }
    return chain.reverse();
  }

  /* --------------------------------------------- manifeste lu (purs) */
  function shortJson(value){
    if(value===undefined)return '';
    let text;
    try{text=JSON.stringify(value)}catch(_){text=String(value)}
    return text.length>60?`${text.slice(0,57)}…`:text;
  }
  /* Charge d'un événement d'aperçu, lisible en entier jusqu'à 400 caractères. */
  function previewPayload(value){
    let text;
    try{text=JSON.stringify(value===undefined?{}:value)}catch(_){text=String(value)}
    return text.length>400?`${text.slice(0,399)}…`:text;
  }
  function boundsOf(s){
    const parts=[];
    if(Number.isInteger(s.max_length))parts.push(`≤ ${s.max_length} car.`);
    if(typeof s.min==='number'&&typeof s.max==='number')parts.push(`${s.min}…${s.max}`);
    else if(typeof s.min==='number')parts.push(`≥ ${s.min}`);
    else if(typeof s.max==='number')parts.push(`≤ ${s.max}`);
    if(Number.isInteger(s.max_items))parts.push(`≤ ${s.max_items} éléments`);
    if(Array.isArray(s.values))parts.push(s.values.join(' | '));
    if(typeof s.format==='string')parts.push(s.format);
    return parts.join(' · ');
  }
  /* Arbre des entrées à plat (`depth`), racines `props` puis `data`. */
  function inputsTree(manifest){
    const out=[];
    function walk(schema,name,path,depth,required){
      if(!isObject(schema)||depth>6)return;
      out.push({name,path,depth,type:typeof schema.type==='string'?schema.type:(schema.$ref?'$ref':'?'),required:!!required,
        default:'default' in schema?shortJson(schema.default):'',description:typeof schema.description==='string'?schema.description:'',
        bounds:boundsOf(schema)});
      if(schema.type==='object'&&isObject(schema.properties)){
        const req=new Set(list(schema.required));
        for(const [key,child] of Object.entries(schema.properties))walk(child,key,`${path}.${key}`,depth+1,req.has(key));
      }else if(schema.type==='array'&&isObject(schema.items)){
        walk(schema.items,'[ ]',`${path}[]`,depth+1,false);
      }
    }
    const inputs=isObject(manifest&&manifest.inputs)?manifest.inputs:{};
    for(const root of ['props','data'])if(isObject(inputs[root]))walk(inputs[root],root,root,0,false);
    return out;
  }
  function eventsOf(manifest){
    const events=isObject(manifest&&manifest.events)?manifest.events:{};
    return Object.entries(events).filter(([,e])=>isObject(e)).map(([name,e])=>({name,cls:typeof e.class==='string'?e.class:'?',
      writes:list(e.writes).map(String),summary:typeof e.summary==='string'?e.summary:'',
      payload:isObject(e.payload)&&isObject(e.payload.properties)?Object.keys(e.payload.properties):[]}));
  }
  /* Réglages simples qu'un fork peut changer : props de premier niveau de
     type `color`, `boolean` ou `enum`. Valeur initiale : l'exemple, sinon le
     défaut. */
  function editableDefaults(manifest){
    const props=isObject(manifest&&manifest.inputs)&&isObject(manifest.inputs.props)&&isObject(manifest.inputs.props.properties)
      ?manifest.inputs.props.properties:{};
    const sample=isObject(manifest&&manifest.sample)&&isObject(manifest.sample.props)?manifest.sample.props:{};
    const out=[];
    for(const [name,s] of Object.entries(props)){
      if(!isObject(s)||!['color','boolean','enum'].includes(s.type))continue;
      const values=s.type==='enum'?list(s.values).map(String):[];
      const fallback=s.type==='boolean'?false:s.type==='color'?'#000000':(values[0]||'');
      const value=name in sample?sample[name]:('default' in s?s.default:fallback);
      out.push({name,type:s.type,values,value,description:typeof s.description==='string'?s.description:''});
    }
    return out;
  }
  /* Candidat de fork : la source copiée TELLE QUELLE (gabarit, style,
     comportement, entrées, événements, exemple), sous un nouvel id, titre et
     description. Les alias ne suivent pas (ce sont les noms de l'original) ;
     les réglages choisis deviennent les défauts ET l'exemple du fork. Core
     valide et attribue la version. Rend `{candidate, derived_from}` ou
     `{error}` (identifiant manquant : rien n'est envoyé). */
  function forkCandidate(source,form){
    const f=isObject(form)?form:{};
    const id=String(f.id||'').trim();
    if(!id)return {error:apiError('missing_id',0,'identifiant manquant')};
    const manifest=clone(source.manifest);
    manifest.id=id;manifest.version=1;
    manifest.title=String(f.title||'').trim();
    manifest.description=String(f.description||'').trim();
    manifest.aliases=[];
    const props=isObject(manifest.inputs)&&isObject(manifest.inputs.props)&&isObject(manifest.inputs.props.properties)
      ?manifest.inputs.props.properties:{};
    if(!isObject(manifest.sample))manifest.sample={props:{},data:{}};
    if(!isObject(manifest.sample.props))manifest.sample.props={};
    for(const [name,value] of Object.entries(isObject(f.defaults)?f.defaults:{})){
      if(!isObject(props[name]))continue;
      props[name].default=value;
      manifest.sample.props[name]=value;
    }
    const files=isObject(source.files)?source.files:{};
    return {candidate:{manifest,template:String(files.template??''),style:String(files.style??''),behavior:String(files.behavior??'')},
      derived_from:{id:source.id,version:source.version}};
  }
  /* « Placer sur la scène » : une fenêtre dépliée qui porte le bloc prefab
     avec les données d'exemple. `category` est exigée par le réducteur pour
     une création (`incomplete_object` sinon) : `prefab`. Sans géométrie : la
     scène la place. L'acteur est posé par le Control Center (`user`). */
  function placeCommand(detail,objectId){
    const m=detail.manifest||{};
    const sample=isObject(m.sample)?m.sample:{};
    return {schema_version:1,op:'upsert_object',object_id:objectId,
      fields:{kind:'window',category:'prefab',representation:'window',
        payload:{title:String(m.title||detail.id).slice(0,200),summary:String(m.description||'').slice(0,200),items:[],
          prefab:{id:detail.id,version:detail.version,props:clone(isObject(sample.props)?sample.props:{}),
            data:clone(isObject(sample.data)?sample.data:{})}}}};
  }

  /* ------------------------------------------------------- contrôleur

     `createLibrary({client, now, log, onChange, newId})` tient l'état de la
     vue et ses actions ; il ne touche pas au DOM. `onChange()` est appelé à
     chaque changement d'état. */
  function slot(){return {status:'idle',data:null,error:null,started:0}}
  function createLibrary({client,now=()=>Date.now(),log=()=>{},onChange=()=>{},
    newId=()=>Math.random().toString(16).slice(2,14).padEnd(12,'0')}={}){
    /* `fork` : le formulaire ouvert (lié au prefab choisi). `publication` :
       le fork en cours d'envoi, qui survit à un changement de prefab ou à la
       fermeture du formulaire ; son issue finit dans `notice`. Un avis
       `sticky` (issue d'une publication finie pendant que l'utilisateur était
       ailleurs) reste jusqu'à « Masquer » ; les autres partent au changement
       de prefab. */
    const S={open:false,query:'',kind:'all',family:'',type:'',engine:'',stack:'',
      list:{status:'idle',rows:[],error:null,started:0,readAt:0,gen:0,ranked:false},
      details:new Map(),selected:null,version:null,versionView:slot(),
      fork:null,publication:null,place:null,notice:null,previewLog:[],previewSeq:0,focusRequest:null};
    let pumping=0;const queue=[];
    const changed=()=>{try{onChange()}catch(error){log('error','prefabs.render_failed',{message:String(error&&error.message)})}};

    function lineage(id){const d=S.details.get(id);return d&&d.data?lineageOf(d.data):null}
    function failed(id){const d=S.details.get(id);return !!d&&d.status==='error'&&!d.data}
    function entries(){return S.list.rows.map(row=>entryOf(row,lineage(row.id),failed(row.id)))}
    function visible(){return sortEntries(filterEntries(entries(),{kind:S.kind,family:S.family,type:S.type,engine:S.engine,stack:S.stack}),{ranked:S.list.ranked})}
    function rowOf(id){return S.list.rows.find(r=>r.id===id)||null}
    function detailKey(row){return `${row.id}@${row.latest_version}#${list(row.versions).join(',')}`}

    /* Provenance de chaque ligne, au plus `DETAIL_CONCURRENCY` lectures à la
       fois. Une version publiée ne change jamais : une provenance est relue
       seulement quand l'ensemble des versions de l'id change. */
    function want(id,key){
      const known=S.details.get(id);
      if(known&&known.key===key&&(known.status==='ready'||known.status==='loading'))return;
      S.details.set(id,{key,status:'queued',data:known&&known.data||null,error:null,started:0});
      queue.push(id);pump();
    }
    function pump(){
      while(pumping<DETAIL_CONCURRENCY&&queue.length){
        const id=queue.shift();
        const d=S.details.get(id);
        if(!d||d.status!=='queued')continue;
        d.status='loading';d.started=now();pumping+=1;
        client.get(PATHS.detail(id)).then(body=>{
          const cur=S.details.get(id);
          if(cur===d){d.status='ready';d.data=body;d.error=null}
        },error=>{
          const cur=S.details.get(id);
          if(cur===d){d.status='error';d.error=error}
          log('warn','prefabs.detail_failed',{prefab_id:id,code:error&&error.code,status:error&&error.status});
        }).finally(()=>{pumping-=1;pump();changed()});
      }
    }
    async function refresh(){
      const gen=S.list.gen+1;
      S.list.gen=gen;S.list.status='loading';S.list.started=now();S.list.error=null;
      changed();
      try{
        const body=await client.get(PATHS.search(S.query.trim()||null));
        if(S.list.gen!==gen)return;
        S.list.rows=list(body.prefabs).filter(r=>isObject(r)&&typeof r.id==='string');
        S.list.status='ready';S.list.readAt=now();S.list.ranked=!!S.query.trim();
        log('info','prefabs.list_read',{rows:S.list.rows.length,query:!!S.query.trim()});
        for(const row of S.list.rows)want(row.id,detailKey(row));
        if(S.selected){const row=rowOf(S.selected);if(row)want(row.id,detailKey(row))}
      }catch(error){
        if(S.list.gen!==gen)return;
        S.list.status='error';S.list.error=error;
        log('warn','prefabs.list_failed',{code:error&&error.code,status:error&&error.status,message:error&&error.message});
      }
      changed();
    }
    function readVersion(id,version){
      const view=S.versionView;
      view.status='loading';view.started=now();view.error=null;view.data=null;view.key=`${id}@${version}`;
      changed();
      return client.get(PATHS.version(id,version)).then(body=>{
        if(view.key!==`${id}@${version}`||S.versionView!==view)return;
        view.status='ready';view.data=body;changed();
      },error=>{
        if(view.key!==`${id}@${version}`||S.versionView!==view)return;
        view.status='error';view.error=error;changed();
        log('warn','prefabs.version_failed',{prefab_id:id,version,code:error&&error.code});
      });
    }
    /* Détail montré : la dernière version (provenance lue) ou la version choisie. */
    function shown(){
      const id=S.selected;
      if(!id)return {status:'idle'};
      const d=S.details.get(id);
      if(S.version!==null&&d&&d.data&&S.version!==d.data.version){
        const v=S.versionView;
        return {status:v.status,data:v.data,error:v.error,started:v.started,latest:d.data};
      }
      if(!d)return {status:'loading',started:now()};
      return {status:d.status==='queued'?'loading':d.status,data:d.data,error:d.error,started:d.started,latest:d.data};
    }

    /* Chaîne de provenance d'un id, chaque maillon avec son état :
       `known`, `pending` (historique pas encore lu : sa lecture est lancée
       ici, bornée par `CHAIN_MAX` et le cache), `absent` (Core ne le connaît
       pas), `error` (lecture en échec), `cycle`. */
    function chain(id){
      return provenanceChain(id,lineage).map(link=>{
        if(link.known)return {...link,state:'known'};
        if(link.cycle)return {...link,state:'cycle'};
        const d=S.details.get(link.id);
        if(!d){want(link.id,`${link.id}@?`);return {...link,state:'pending'}}
        if(d.status==='error')return {...link,state:d.error&&d.error.code==='unknown_prefab'?'absent':'error',code:d.error&&d.error.code};
        return {...link,state:'pending'};
      });
    }

    const api={
      state:S,entries,visible,lineage,shown,chain,
      counts:()=>countsOf(entries()),
      families:()=>familiesOf(entries()),
      waiting:()=>S.list.status==='loading'||!!S.publication||(S.place&&S.place.status==='sending')
        ||[...S.details.values()].some(d=>d.status==='loading'||d.status==='queued')||S.versionView.status==='loading',
      open(){S.open=true;if(S.notice&&!S.notice.sticky)S.notice=null;return refresh()},
      close(){S.open=false;S.fork=null;S.place=null;S.previewLog=[];},
      refresh,
      setQuery(value){
        const next=String(value||'').slice(0,120);
        if(next===S.query&&S.list.status!=='error')return Promise.resolve();
        S.query=next;return refresh();
      },
      setKind(kind){S.kind=kind==='all'||KIND_BY_KEY[kind]?kind:'all';changed()},
      setFamily(family){S.family=String(family||'');changed()},
      setType(type){S.type=TYPE_BY_KEY[type]?type:'';changed()},
      setEngine(engine){S.engine=ENGINES.some(e=>e.key===engine)?engine:'';changed()},
      setStack(stack){S.stack=String(stack||'');changed()},
      stacks(){return stacksOf(entries())},
      clearSemanticFilters(){S.type='';S.engine='';S.stack='';changed()},
      select(id,version){
        if(typeof id!=='string'||!id)return;
        const changedId=S.selected!==id;
        S.selected=id;S.version=Number.isInteger(version)?version:null;
        if(changedId){
          S.fork=null;S.place=null;S.previewLog=[];S.versionView=slot();
          if(S.notice&&!S.notice.sticky)S.notice=null;
        }
        const row=rowOf(id);
        if(row)want(id,detailKey(row));
        else{const d=S.details.get(id);if(!d||d.status==='error')want(id,`${id}@?`)}
        const d=S.details.get(id);
        if(S.version!==null&&d&&d.data&&S.version!==d.data.version)readVersion(id,S.version);
        changed();
      },
      selectVersion(version){
        const d=S.details.get(S.selected);
        if(!d||!d.data)return;
        const v=Number(version);
        S.version=v===d.data.version?null:v;S.previewLog=[];S.fork=null;S.place=null;
        if(S.version!==null)readVersion(S.selected,S.version);else changed();
      },
      retryDetail(){const id=S.selected;if(!id)return;const d=S.details.get(id);if(d)d.key='';want(id,`${id}@retry`);changed()},
      dismissNotice(){S.notice=null;changed()},

      /* --------------------------------------------- aperçu (local) */
      logPreviewEvent(event,manifest){
        const decl=eventsOf(manifest).find(e=>e.name===(event&&event.event));
        S.previewSeq+=1;
        S.previewLog.unshift({seq:S.previewSeq,at:now(),name:String(event&&event.event||'?'),cls:decl?decl.cls:'?',
          payload:previewPayload(event&&event.payload)});
        if(S.previewLog.length>LOG_CAP)S.previewLog.length=LOG_CAP;
        changed();
      },
      clearPreviewLog(){S.previewLog=[];changed()},

      /* --------------------------------------------- placer sur la scène */
      async place(){
        const view=shown();
        if(!view.data||(S.place&&S.place.status==='sending'))return null;
        const detail=view.data;
        const objectId=`user-prefab-${newId()}`;
        S.place={status:'sending',started:now(),error:null,result:null,key:`${detail.id}@${detail.version}`};
        changed();
        const place=S.place;
        try{
          const response=await client.post(PATHS.scene(),placeCommand(detail,objectId));
          const body=response.body;
          if(body.outcome==='applied'||body.outcome==='duplicate'){
            place.status='done';place.result={objectId,revision:body.revision,title:detail.manifest&&detail.manifest.title||detail.id};
            log('info','prefabs.placed',{prefab:`${detail.id}@${detail.version}`,object_id:objectId,revision:body.revision});
          }else{
            const reason=typeof body.reason==='string'?body.reason:String(body.outcome||'refused');
            place.status='error';
            place.error=apiError(SCENE_REFUSALS[reason]||reason||'refused',response.status,
              typeof body.detail==='string'&&body.detail?body.detail:`refusé : ${reason}`);
            log('warn','prefabs.place_refused',{prefab:`${detail.id}@${detail.version}`,outcome:body.outcome,reason});
          }
        }catch(error){
          place.status='error';place.error=error;
          log('warn','prefabs.place_failed',{prefab:`${detail.id}@${detail.version}`,code:error&&error.code,status:error&&error.status});
        }
        changed();
        return place;
      },

      /* --------------------------------------------- fork */
      openFork(){
        const view=shown();
        if(!view.data)return;
        const m=view.data.manifest||{};
        S.fork={gen:(S.fork?S.fork.gen:0)+1,source:{id:view.data.id,version:view.data.version,title:m.title||view.data.id},
          status:'editing',phase:null,started:0,error:null,
          initial:{id:'',title:m.title?`${m.title} (fork)`.slice(0,80):'',description:String(m.description||''),
            defaults:editableDefaults(m)}};
        changed();
      },
      cancelFork(){if(!S.fork||S.fork.status==='saving')return false;S.fork=null;changed();return true},
      /* Un identifiant déjà dans la liste lue est refusé avant le réseau
         (`id_taken`) : celui de la source ferait une RÉVISION de l'original,
         pas un fork. Core reste l'autorité pour le reste (liste bornée). Si
         l'utilisateur quitte le formulaire pendant l'envoi, la publication
         continue ; son issue devient un avis qui reste, et la sélection ne
         bouge pas. */
      async submitFork(fields){
        const fork=S.fork;
        if(!fork||fork.status==='saving'||S.publication)return null;
        fork.status='saving';fork.phase='source';fork.started=now();fork.error=null;
        S.publication=fork;
        changed();
        const from=`${fork.source.id} v${fork.source.version}`;
        try{
          const wanted=String(isObject(fields)&&fields.id||'').trim();
          if(wanted&&(wanted===fork.source.id||S.list.rows.some(r=>r.id===wanted)))
            throw apiError('id_taken',0,`${wanted} est déjà dans la bibliothèque`);
          const source=await client.get(PATHS.version(fork.source.id,fork.source.version,true));
          const built=forkCandidate(source,fields);
          if(built.error)throw built.error;
          fork.phase='publish';changed();
          const response=await client.post(PATHS.save(),{candidate:built.candidate,derived_from:built.derived_from});
          const pub=response.body;
          const id=typeof pub.prefab_id==='string'?pub.prefab_id:built.candidate.manifest.id;
          log('info','prefabs.forked',{prefab_id:id,version:pub.version,from:`${fork.source.id}@${fork.source.version}`,
            origin:isObject(pub.provenance)?pub.provenance.origin:null,on_form:S.fork===fork});
          S.publication=null;
          const notice={tone:'ok',title:`Fork publié : ${id} v${pub.version}`,
            text:`Copie de ${from}, publiée en votre nom ; l’original n’a pas changé.`};
          if(S.fork===fork){
            S.fork=null;
            await refresh();
            S.focusRequest=id;
            api.select(id);
            S.notice={...notice,sticky:false};
          }else{
            S.notice={...notice,sticky:true,goto:id};
            await refresh();
          }
          changed();
          return pub;
        }catch(error){
          S.publication=null;
          const v=errorView(error);
          if(S.fork===fork){fork.status='error';fork.error=error;fork.phase=null}
          else S.notice={tone:'bad',sticky:true,code:v.code,title:`Fork de ${from} refusé : ${v.title}`,text:`${v.message} ${v.hint}`};
          log('warn','prefabs.fork_failed',{from:`${fork.source.id}@${fork.source.version}`,code:error&&error.code,
            status:error&&error.status,message:error&&error.message,errors:list(error&&error.errors).length});
          changed();
          return null;
        }
      },
    };
    return api;
  }

  /* Ligne d'état de l'en-tête : ce qui attend (avec son âge), l'erreur, ou l'heure de lecture. */
  function statusView(lib,t){
    const S=lib.state;
    const at=t||Date.now();
    const pub=S.publication;
    if(pub)return {tone:'busy',label:pub.phase==='source'?'Lecture de la source…':'Publication…',detail:formatSeconds(at-pub.started)};
    if(S.place&&S.place.status==='sending')return {tone:'busy',label:'Envoi à la scène…',detail:formatSeconds(at-S.place.started)};
    if(S.list.status==='loading')return {tone:'busy',label:'Lecture du catalogue…',detail:formatSeconds(at-S.list.started)};
    if(S.list.status==='error'){const v=errorView(S.list.error);return {tone:'bad',label:v.title,detail:v.code}}
    if(S.list.readAt){
      const d=new Date(S.list.readAt),p=n=>String(n).padStart(2,'0');
      return {tone:'live',label:`Lu à ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`,detail:'« Actualiser » relit la bibliothèque'};
    }
    return {tone:'muted',label:'En attente',detail:''};
  }

  return Object.freeze({DEADLINE_MS,LIST_LIMIT,DETAIL_CONCURRENCY,LOG_CAP,PREVIEW_OBJECT_ID,KINDS,KIND_BY_KEY,ORIGINS,ACTORS,
    EVENT_CLASSES,VERSION_STATUS,ERRORS,PATHS,
    isPrefabId,isBaseId,formatSeconds,formatWhen,refText,allowed,createClient,errorView,versionsOf,lineageOf,kindOf,badgesOf,
    entryOf,familiesOf,countsOf,catalogOf,supportOf,typeLabel,stacksOf,SEMANTIC_TYPES,TYPE_BY_KEY,ENGINES,SUPPORT,filterEntries,sortEntries,provenanceChain,inputsTree,eventsOf,editableDefaults,forkCandidate,
    placeCommand,createLibrary,statusView});
})();
if(typeof module!=='undefined'&&module.exports)module.exports=JarvisPrefabLibraryCore;

/* --------------------------------------------------------------------------
   Bloc navigateur : vue plein écran, rendu DOM par régions, clavier.

   RÉGIONS. La liste, l'en-tête du détail, ses sections et le journal de
   l'aperçu sont refaits quand leur clé change ; le conteneur du cadre
   d'aperçu, lui, n'est JAMAIS détaché (un cadre détaché recharge son
   document) : il ne change qu'avec `id@version`. Le formulaire de fork est
   construit à son ouverture et n'est plus refait pendant la saisie : seules
   sa zone d'état et sa zone d'erreur changent.
   Le focus d'une ligne survit au re-rendu de la liste (même `id`).
   -------------------------------------------------------------------------- */
(function installJarvisPrefabLibrary(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const C=JarvisPrefabLibraryCore;
  const root=document.getElementById('prefabLibrary');
  if(!root){console.error('[prefabs] prefabs.install_failed {"code":"prefabs_host_missing"}');return}
  const q=s=>root.querySelector(s);
  const el={open:document.getElementById('openPrefabs'),close:q('#pfbClose'),refresh:q('#pfbRefresh'),
    status:q('#pfbStatus'),statusLabel:q('#pfbStatusLabel'),statusDetail:q('#pfbStatusDetail'),
    search:q('#pfbSearch'),family:q('#pfbFamily'),type:q('#pfbType'),engine:q('#pfbEngine'),stack:q('#pfbStack'),kinds:q('#pfbKinds'),count:q('#pfbCount'),
    list:q('#pfbList'),listState:q('#pfbListState'),detail:q('#pfbDetail'),announce:q('#pfbAnnounce')};
  if(Object.values(el).some(node=>!node)){
    console.error('[prefabs] prefabs.install_failed {"code":"prefabs_view_incomplete"}');return;
  }
  const isRecord=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
  const TICK_MS=500,SEARCH_DEBOUNCE_MS=220;
  const V={inerted:[],tick:null,keys:{},previewKey:null,host:null,searchTimer:null,forkGen:null,pendingFocus:null,raf:0};
  const log=(level,event,data)=>{
    const line=`[prefabs] ${event} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line);
  };
  const client=C.createClient({fetchImpl:(path,options)=>window.fetch(path,options)});
  const lib=C.createLibrary({client,log,onChange:()=>{if(!root.hidden)schedule()},
    newId:()=>{const b=new Uint8Array(6);crypto.getRandomValues(b);return [...b].map(x=>x.toString(16).padStart(2,'0')).join('')}});
  const S=lib.state;

  /* ------------------------------------------------------------- DOM */
  const SVGNS='http://www.w3.org/2000/svg';
  const ICONS={
    lock:['M7 11V8a5 5 0 0 1 10 0v3','M5 11h14v10H5Z','M12 15v2'],
    pen:['M4 20h4L19 9l-4-4L4 16Z','M13.5 6.5l4 4'],
    branch:['M6 3v12','M6 15a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z','M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z','M18 9c0 4-4 5-12 6'],
    spark:['M12 3v4M12 17v4M3 12h4M17 12h4','M6.3 6.3l2.5 2.5M15.2 15.2l2.5 2.5M6.3 17.7l2.5-2.5M15.2 8.8l2.5-2.5'],
    place:['M3 5h18v12H3Z','M8 21h8','M12 17v4','M9 11h6M12 8v6'],
    fork:['M6 3v12','M6 15a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z','M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z','M18 9c0 4-4 5-12 6'],
    reset:['M4 12a8 8 0 1 0 3-6.2','M4 4v5h5'],
    library:['M4 4h4v16H4Z','M10 4h4v16h-4Z','M16 5l3.5-1 3 15.5-3.5.9Z'],
    arrow:['M5 12h14','M13 6l6 6-6 6'],
    quote:['M7 7h4v4c0 3-1.5 5-4 6','M14 7h4v4c0 3-1.5 5-4 6'],
    check:['M5 12.5l4.5 4.5L19 7.5'],
    ban:['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z','M5.6 5.6l12.8 12.8'],
  };
  function icon(name,className){
    const s=document.createElementNS(SVGNS,'svg');
    s.setAttribute('viewBox','0 0 24 24');s.setAttribute('fill','none');s.setAttribute('stroke','currentColor');
    s.setAttribute('stroke-width','1.8');s.setAttribute('stroke-linecap','round');s.setAttribute('stroke-linejoin','round');
    s.setAttribute('aria-hidden','true');s.setAttribute('focusable','false');
    if(className)s.setAttribute('class',className);
    for(const d of ICONS[name]||[]){const p=document.createElementNS(SVGNS,'path');p.setAttribute('d',d);s.appendChild(p)}
    return s;
  }
  /* `h(tag, attrs, ...enfants)` : attributs posés par `setAttribute`, texte
     par `textContent` ; `value`/`checked` en propriétés ; `on*` en écouteurs. */
  function h(tag,attrs,...children){
    const node=document.createElement(tag);
    for(const [k,v] of Object.entries(attrs||{})){
      if(v===null||v===undefined||v===false)continue;
      if(k==='text')node.textContent=String(v);
      else if(k==='class')node.className=v;
      else if(k==='value'||k==='checked')node[k]=v;
      else if(k==='dataset')Object.assign(node.dataset,v);
      else if(k.startsWith('on')&&typeof v==='function')node.addEventListener(k.slice(2),v);
      else node.setAttribute(k,v===true?'':String(v));
    }
    append(node,children);
    return node;
  }
  function append(node,children){
    for(const child of children.flat(Infinity)){
      if(child===null||child===undefined||child===false)continue;
      node.appendChild(typeof child==='string'||typeof child==='number'?document.createTextNode(String(child)):child);
    }
    return node;
  }
  function replace(node,...children){node.replaceChildren();append(node,children);return node}
  function clock(started){return h('span',{class:'pfb-clock','data-pfb-since':String(Number(started)||Date.now())})}
  function chip(b){
    return h('span',{class:`pfb-badge is-${b.tone}`,title:b.title||null},b.icon?icon(b.icon):null,h('span',{text:b.label}));
  }
  function loading(label,started){
    return h('div',{class:'pfb-loading',role:'status'},h('span',{class:'pfb-spin','aria-hidden':'true'}),`${label} `,clock(started));
  }
  /* Texte venu d'un agent ou de l'utilisateur (titre, demande citée, recherche)
     inséré dans une phrase : isolé (`<bdi>`), pour qu'un texte de droite à
     gauche ne réordonne pas la phrase autour de lui. Un élément qui ne porte
     QUE ce texte prend `dir: 'auto'` à la place. */
  function iso(text){return h('bdi',{text:String(text??'')})}
  function errorBox(error,{lead='',retry=null,retryLabel='Réessayer'}={}){
    const v=C.errorView(error);
    const where=[v.coreCode,v.status?`HTTP ${v.status}`:''].filter(Boolean).join(' · ');
    return h('div',{class:'pfb-error',role:'alert'},
      h('strong',{text:`${lead}${v.title}`}),
      h('p',{class:'pfb-emsg'},iso(v.message),' ',h('code',{text:where})),
      v.errors.length?h('ul',{class:'pfb-errlist'},v.errors.map(text=>h('li',{text}))):null,
      h('p',{class:'pfb-hint',text:v.hint}),
      retry?h('button',{type:'button',class:'action small',onclick:retry,text:retryLabel}):null);
  }
  function announce(text){el.announce.textContent='';el.announce.textContent=text}

  /* ------------------------------------------------------------- rendu */
  function schedule(){
    if(V.raf)return;
    V.raf=requestAnimationFrame(()=>{V.raf=0;render()});
  }
  /* Une région n'est refaite que si sa clé change. */
  function region(name,key,build){
    if(V.keys[name]===key)return false;
    V.keys[name]=key;build();return true;
  }
  function renderStatus(){
    const v=C.statusView(lib,Date.now());
    el.status.dataset.tone=v.tone;
    el.statusLabel.textContent=v.label;
    el.statusDetail.textContent=v.detail?` · ${v.detail}`:'';
  }
  function tickClocks(){
    const t=Date.now();
    for(const node of root.querySelectorAll('[data-pfb-since]'))node.textContent=C.formatSeconds(t-(Number(node.getAttribute('data-pfb-since'))||t));
  }
  function armTick(){
    if(lib.waiting()&&!V.tick)V.tick=setInterval(()=>{
      tickClocks();renderStatus();
      if(!lib.waiting()){clearInterval(V.tick);V.tick=null}
    },TICK_MS);
  }

  function renderFilters(){
    const counts=lib.counts();
    const families=lib.families();
    const stacks=lib.stacks();
    region('kinds',JSON.stringify([S.kind,counts]),()=>{
      const kinds=[{key:'all',label:'Tous',tone:'all',icon:null,means:'Tous les prefabs de la bibliothèque'},...C.KINDS];
      replace(el.kinds,kinds.map(k=>h('button',{type:'button',class:`pfb-kind is-${k.tone}`,'aria-pressed':String(S.kind===k.key),
        dataset:{kind:k.key},title:k.means,'aria-label':`${k.key==='all'?'Tous':k.plural} : ${counts[k.key]||0}`,onclick:()=>lib.setKind(k.key)},
        k.icon?icon(k.icon):null,h('span',{class:'pfb-kind-label',text:k.key==='all'?k.label:k.plural}),
        h('span',{class:'pfb-kind-n',text:String(counts[k.key]||0)}))));
    });
    region('families',JSON.stringify([families,S.family]),()=>{
      const options=[h('option',{value:'',text:'Toutes'}),...families.map(f=>h('option',{value:f,text:f}))];
      replace(el.family,options);
      el.family.value=families.includes(S.family)?S.family:'';
    });
    region('semantic',JSON.stringify([stacks,S.type,S.engine,S.stack]),()=>{
      replace(el.type,[h('option',{value:'',text:'Tous'}),...C.SEMANTIC_TYPES.map(t=>h('option',{value:t.key,text:t.label,title:t.means}))]);
      el.type.value=S.type;
      replace(el.engine,[h('option',{value:'',text:'Tous'}),...C.ENGINES.map(e=>h('option',{value:e.key,text:e.label,title:`Compatible ${e.label} : natif, ou par adaptateur (déclaré : pas encore utilisable dans une présentation)`}))]);
      el.engine.value=S.engine;
      replace(el.stack,[h('option',{value:'',text:'Toutes'}),...stacks.map(t=>h('option',{value:t,text:t}))]);
      el.stack.value=stacks.includes(S.stack)?S.stack:'';
    });
  }

  /* Liste à tabulation itinérante : UN arrêt de Tab (la ligne choisie, sinon
     la première), ↑ ↓ Début Fin déplacent le focus d'une ligne à l'autre. */
  /* Type + compatibilité de chaque moteur, en mots (jamais la couleur seule). Sans contrat lu : rien d'affirmé. */
  function catalogLine(source){
    const c=C.catalogOf(source);
    if(!c)return null;
    return h('span',{class:'pfb-cat'},
      h('span',{class:'pfb-badge is-type',title:(C.TYPE_BY_KEY[c.type]||{}).means||c.type,text:C.typeLabel(c.type)}),
      C.ENGINES.map(e=>supportChip(e,C.supportOf(c,e.key))));
  }
  function supportChip(engine,value){
    const sp=C.SUPPORT[value];
    return h('span',{class:`pfb-badge is-sup-${value}`,title:`${engine.label} : ${sp.label}. ${sp.means}`},icon(sp.icon),h('span',{text:`${engine.label} ${sp.label}`}));
  }
  function rowNode(entry,tabStop){
    const r=entry.row;
    const selected=S.selected===r.id;
    /* Nom accessible dit en phrase : les badges sont en capitales par le CSS,
       que Chrome reporterait dans le nom. */
    const name=[r.title||r.id,r.id,`version ${r.latest_version}`,...entry.badges.map(b=>b.label.toLowerCase()),
      entry.parent?`fork de ${C.refText(entry.parent)}`:null,
      ...(C.catalogOf(r)?[C.typeLabel(r.catalog.type),...C.ENGINES.map(e=>`${e.label} ${C.SUPPORT[C.supportOf(r.catalog,e.key)].label}`)].map(t=>t.toLowerCase()):[])].filter(Boolean).join(', ');
    return h('li',{},h('button',{type:'button',class:`pfb-row${selected?' is-selected':''}`,id:`pfb-row-${r.id}`,
      dataset:{id:r.id},'aria-current':selected?'true':null,'aria-label':name,tabindex:tabStop?'0':'-1'},
      h('span',{class:'pfb-row-top'},h('span',{class:'pfb-name',dir:'auto',text:r.title||r.id}),h('span',{class:'pfb-ver',text:`v${r.latest_version}`})),
      h('code',{class:'pfb-id',text:r.id}),
      h('span',{class:'pfb-badges'},entry.badges.map(chip)),
      catalogLine(r),
      entry.parent?h('span',{class:'pfb-parent'},icon('branch'),'de ',h('code',{text:C.refText(entry.parent)})):null));
  }
  function renderList(){
    const shownEntries=lib.visible();
    const keyRows=shownEntries.map(e=>[e.row.id,e.row.latest_version,e.row.title,e.badges.map(b=>b.key+b.label).join(','),
      e.parent?C.refText(e.parent):'',e.row.catalog||null]);
    if(S.focusRequest){V.pendingFocus=S.focusRequest;S.focusRequest=null}
    region('list',JSON.stringify([S.list.status,S.list.error&&S.list.error.code,keyRows,S.selected,S.query,S.kind,S.family,S.type,S.engine,S.stack]),()=>{
      const focusedId=document.activeElement&&document.activeElement.classList&&document.activeElement.classList.contains('pfb-row')
        ?document.activeElement.dataset.id:null;
      const tabId=shownEntries.some(e=>e.row.id===S.selected)?S.selected:(shownEntries[0]&&shownEntries[0].row.id);
      replace(el.list,shownEntries.map(e=>rowNode(e,e.row.id===tabId)));
      if(focusedId){const back=document.getElementById(`pfb-row-${focusedId}`);if(back)back.focus({preventScroll:true})}
      if(V.pendingFocus){const t=document.getElementById(`pfb-row-${V.pendingFocus}`);if(t){t.focus({preventScroll:false});t.scrollIntoView({block:'nearest'});V.pendingFocus=null}}
      /* État de la liste : lecture, erreur, vide (qui explique), borne. */
      const total=S.list.rows.length;
      let state=null;
      if(S.list.status==='loading'&&!total)state=loading('Lecture du catalogue…',S.list.started);
      else if(S.list.status==='error')state=errorBox(S.list.error,{lead:'Liste : ',retry:()=>lib.refresh()});
      else if(S.list.status==='ready'&&!total)state=S.query
        ?h('p',{class:'pfb-empty'},'Aucun prefab ne répond à « ',iso(S.query),
          ' ». La recherche porte sur l’identifiant, le titre, les alias, les étiquettes et la description.')
        :h('p',{class:'pfb-empty',text:'La bibliothèque est vide.'});
      else if(total&&!shownEntries.length)state=h('p',{class:'pfb-empty'},'Aucun prefab de cette nature avec ces filtres. ',
        S.type||S.engine||S.stack?h('button',{type:'button',class:'pfb-link',id:'pfbClearSemantic',onclick:()=>lib.clearSemanticFilters(),text:'Retirer type, moteur et pile'}):null);
      replace(el.listState,state);
      const shownCount=shownEntries.length;
      el.count.textContent=S.list.status==='ready'||total
        ?`${shownCount} sur ${total} prefab${total>1?'s':''}${total>=C.LIST_LIMIT?` · ${C.LIST_LIMIT} premiers : précisez la recherche`:''}`:'';
    });
  }

  /* ------------------------------------------------------------- détail */
  const D={};
  function buildDetailShell(){
    D.empty=h('div',{class:'pfb-intro'});
    D.head=h('header',{class:'pfb-head'});
    D.notice=h('div',{class:'pfb-noticezone'});
    D.guard=h('div',{class:'pfb-guardzone'});
    D.actions=h('div',{class:'pfb-actions'});
    D.fork=h('div',{class:'pfb-forkzone'});
    D.previewSlot=h('div',{class:'pfb-slot'});
    D.previewTitle=h('span',{class:'pfb-stage-title',dir:'auto'});
    D.previewState=h('div',{class:'pfb-stage-state'});
    D.log=h('div',{class:'pfb-log'});
    D.preview=h('section',{class:'pfb-preview','aria-labelledby':'pfbPreviewTitle'},
      h('div',{class:'pfb-sechead'},h('h4',{id:'pfbPreviewTitle',text:'Aperçu'}),
        h('span',{class:'pfb-sechint',text:'Données d’exemple du prefab · ses événements restent ici, jamais envoyés à Core'}),
        h('button',{type:'button',class:'action small pfb-reset',onclick:()=>remountPreview(true)},icon('reset'),'Réinitialiser')),
      h('div',{class:'pfb-previewgrid'},
        h('div',{class:'pfb-stage'},h('div',{class:'pfb-stagebar'},D.previewTitle,h('span',{class:'pfb-stage-tag',text:'aperçu'})),D.previewState,D.previewSlot),
        D.log),
      /* Le cadre est sandboxé (origine opaque) : ses touches ne remontent pas à
         la page, Échap et `/` y restent. Tab sort du cadre ; « × » en haut
         ferme la vue. Aucune touche n'est relayée par le protocole du cadre. */
      h('p',{class:'pfb-stagehint',id:'pfbStageHint'},'Dans l’aperçu, Échap et / restent au prefab : ',
        h('kbd',{text:'Tab'}),' ou ',h('kbd',{text:'Maj+Tab'}),' pour en sortir. ',
        h('button',{type:'button',class:'pfb-link',id:'pfbStageClose',onclick:()=>closeView(),text:'Fermer la bibliothèque'})));
    D.sections=h('div',{class:'pfb-sections'});
    D.body=h('div',{class:'pfb-body'},D.head,D.notice,D.guard,D.actions,D.fork,D.preview,D.sections);
    replace(el.detail,D.empty,D.body);
  }

  function renderIntro(){
    region('intro',S.selected?'hidden':'shown',()=>{
      D.empty.hidden=!!S.selected;D.body.hidden=!S.selected;
      if(S.selected)return;
      replace(D.empty,
        h('h3',{text:'Bibliothèque partagée de ce poste'}),
        h('p',{text:'Chaque prefab est une fenêtre réutilisable que JARVIS et vous placez sur la scène. Choisissez-en un pour l’inspecter, le prévisualiser avec ses données d’exemple, le placer sur la scène ou le forker.'}),
        h('dl',{class:'pfb-legend'},C.KINDS.map(k=>[h('dt',{},chip({label:k.label,tone:k.tone,icon:k.icon})),h('dd',{text:k.means})])),
        guardNode(null));
    });
  }
  /* La règle des bases, dite au même endroit pour chaque prefab de base et dans l'intro. */
  function guardNode(entryKind,edits){
    return h('aside',{class:'pfb-guard','aria-label':'Protection des prefabs de base'},icon('lock','pfb-guard-icon'),
      h('div',{},
        h('strong',{text:entryKind?'Prefab de base · protégé':'Les prefabs de base sont protégés'}),
        h('p',{text:'Cette bibliothèque ne modifie jamais un prefab de base. Seul JARVIS peut le faire, et seulement quand vous le lui demandez explicitement : vos mots sont alors cités dans l’historique, avec la date.'}),
        h('p',{text:entryKind?'Pour une variante (couleur, libellés, réglages), utilisez « Forker en nouveau prefab » : la copie porte un nouvel identifiant et l’original ne change pas.'
          :'Pour une variante, forkez : la copie porte un nouvel identifiant et l’original ne change pas.'}),
        edits?h('p',{class:'pfb-guard-edits',text:`Ce prefab a été modifié à votre demande ${edits===1?'une fois':`${edits} fois`} : voir « Versions et provenance ».`}):null));
  }

  function currentKind(){const row=S.list.rows.find(r=>r.id===S.selected);return row?C.kindOf(row,lib.lineage(S.selected)):null}

  function renderHead(view){
    /* Un autre prefab : la lecture repart du haut (sinon l'avis d'un fork publié resterait hors de vue). */
    if(V.lastSelected!==S.selected){V.lastSelected=S.selected;el.detail.scrollTop=0}
    const detail=view.data;
    const lineage=lib.lineage(S.selected);
    const row=S.list.rows.find(r=>r.id===S.selected)||(view.latest?{id:view.latest.id,class:view.latest.class,
      latest_version:view.latest.latest_version,base_edited:false,family:view.latest.manifest&&view.latest.manifest.family}:null);
    const badges=row?C.badgesOf(row,lineage):[];
    const chain=lineage&&lineage.parent?lib.chain(S.selected):[];
    const key=JSON.stringify([S.selected,view.status,detail&&detail.version,detail&&detail.latest_version,badges.map(b=>b.label),
      chain.map(c=>[c.id,c.version,c.state]),view.error&&view.error.code]);
    const linkTitle=link=>({known:`Ouvrir ${link.id}`,pending:`${link.id} : historique pas encore lu`,
      absent:`${link.id} n’est pas (ou plus) dans la bibliothèque`,cycle:`${link.id} : boucle de provenance, la chaîne s’arrête ici`,
      error:`${link.id} : historique illisible (${link.code||'erreur'}) ; « Actualiser » le relit`})[link.state]||link.id;
    region('head',key,()=>{
      if(view.status==='loading'&&!detail){replace(D.head,loading('Lecture du prefab…',view.started));return}
      if(view.status==='error'&&!detail){replace(D.head,errorBox(view.error,{retry:()=>lib.retryDetail()}));return}
      if(!detail){replace(D.head);return}
      const m=detail.manifest||{};
      const versions=lineage?lineage.versions.filter(v=>v.status==='ok').map(v=>v.version):[detail.version];
      const pick=versions.length>1?h('label',{class:'pfb-vpick'},h('span',{text:'Version'}),
        h('select',{id:'pfbVersion','aria-label':'Version affichée',onchange:e=>lib.selectVersion(e.target.value)},
          versions.slice().reverse().map(v=>h('option',{value:String(v),text:`v${v}${v===detail.latest_version?' (dernière)':''}`}))))
        :h('span',{class:'pfb-vone',text:`v${detail.version}`});
      if(pick.tagName==='LABEL')pick.querySelector('select').value=String(detail.version);
      const first=lineage&&lineage.versions[0];
      const owner=row&&row.class==='base'?'Livré avec JARVIS'
        :first?`Créé par ${C.ACTORS[first.actor]||first.actor||'?'} le ${C.formatWhen(first.at)}`:'';
      replace(D.head,
        h('div',{class:'pfb-titleline'},h('h3',{id:'pfbDetailTitle',tabindex:'-1',dir:'auto',text:m.title||detail.id}),h('span',{class:'pfb-badges'},badges.map(chip))),
        h('p',{class:'pfb-idline'},h('code',{text:detail.id}),pick,h('span',{class:'pfb-dot','aria-hidden':'true'}),
          h('span',{text:`famille ${m.family||'—'}`}),owner?h('span',{class:'pfb-dot','aria-hidden':'true'}):null,owner?h('span',{text:owner}):null),
        m.description?h('p',{class:'pfb-desc',dir:'auto',text:m.description}):null,
        chain.length>1?h('nav',{class:'pfb-chain','aria-label':'Chaîne de provenance'},icon('branch','pfb-chain-icon'),
          h('span',{class:'pfb-chain-lead',text:'Fork de'}),
          h('ol',{},chain.slice(0,-1).reverse().map((link,i)=>h('li',{},i?h('span',{class:'pfb-chain-sep',text:'fork de'}):null,
            h('button',{type:'button',class:`pfb-link is-${link.state}`,dataset:{goto:link.id},title:linkTitle(link),
              text:link.version?`${link.id} v${link.version}`:link.id})))))
          :null,
        view.status==='loading'?loading('Lecture de la version…',view.started):null,
        view.status==='error'?errorBox(view.error,{retry:()=>lib.selectVersion(S.version)}):null);
    });
  }

  function renderNotice(){
    region('notice',JSON.stringify(S.notice),()=>{
      const n=S.notice;
      /* Un avis `sticky` dit l'issue d'une publication finie pendant que
         l'utilisateur regardait ailleurs : il reste jusqu'à « Masquer ». */
      replace(D.notice,n?h('div',{class:`pfb-notice is-${n.tone}`,role:n.tone==='bad'?'alert':'status'},
        h('div',{},h('strong',{text:n.title}),n.text?h('p',{text:n.text}):null,
          n.code?h('p',{class:'pfb-noticecode'},h('code',{text:n.code})):null,
          n.goto?h('button',{type:'button',class:'pfb-link',dataset:{goto:n.goto},text:`Ouvrir ${n.goto}`}):null),
        h('button',{type:'button',class:'pfb-x','aria-label':'Masquer ce message',onclick:()=>lib.dismissNotice()},'×')):null);
    });
  }
  function renderGuard(){
    const kind=currentKind();
    const lineage=lib.lineage(S.selected);
    const edits=lineage?lineage.baseEdits.length:0;
    region('guard',JSON.stringify([S.selected,kind,edits]),()=>{
      replace(D.guard,kind==='base'||kind==='base_edited'?guardNode(kind,edits):null);
    });
  }
  function renderActions(view){
    const p=S.place;
    const remotionSource=!!view.data&&isRecord(view.data.manifest)&&isRecord(view.data.manifest.source);
    const ready=!!view.data&&!remotionSource;
    const forkOpen=!!S.fork;
    region('actions',JSON.stringify([S.selected,ready,remotionSource,p&&p.status,p&&p.result,p&&p.error&&p.error.code,forkOpen,view.data&&view.data.version]),()=>{
      const placeState=!p?null:p.status==='sending'?loading('Envoi à la scène…',p.started)
        :p.status==='done'?h('p',{class:'pfb-placed',role:'status'},'Placé sur la scène : « ',iso(p.result.title),' » ',h('code',{text:p.result.objectId}),' ',
          h('button',{type:'button',class:'pfb-link',onclick:()=>closeView(),text:'Fermer et voir la scène'}))
        :errorBox(p.error,{lead:'Placer : ',retry:()=>lib.place()});
      replace(D.actions,
        h('div',{class:'pfb-actrow'},
          h('button',{type:'button',class:'action pfb-primary',id:'pfbPlace','aria-describedby':'pfbActHint',disabled:!ready||(p&&p.status==='sending'),
            onclick:()=>lib.place()},icon('place'),'Placer sur la scène'),
          h('button',{type:'button',class:'action',id:'pfbForkOpen','aria-describedby':'pfbActHint','aria-expanded':String(forkOpen),'aria-controls':'pfbForkForm',
            disabled:!ready,onclick:()=>{if(S.fork)lib.cancelFork();else lib.openFork()}},icon('fork'),'Forker en nouveau prefab'),
          h('span',{class:'pfb-acthint',id:'pfbActHint',text:remotionSource?'Source Remotion : ni placement ni fork depuis cette vue (le Player et l’import arrivent avec les Slices suivantes).'
          :'Placer : une fenêtre avec les données d’exemple. Forker : une copie sous un autre identifiant.'})),
        placeState);
    });
  }

  function forkForm(f){
    const g=f.gen;
    const idField=h('input',{id:`pfbForkId-${g}`,name:'id',autocomplete:'off',spellcheck:'false',required:true,maxlength:'96',
      placeholder:'team.checklist-red','aria-describedby':`pfbForkIdHint-${g} pfbForkIdWarn-${g}`,value:f.initial.id});
    const warn=h('p',{class:'pfb-fieldwarn',id:`pfbForkIdWarn-${g}`,'aria-live':'polite'});
    const checkId=()=>{
      const v=idField.value.trim();
      warn.textContent=C.isBaseId(v)?'« jarvis. » est réservé aux prefabs de base : Core refusera cet identifiant.'
        :v&&!C.isPrefabId(v)?'Forme attendue : deux à quatre segments en minuscules séparés par des points.'
        :v===f.source.id||S.list.rows.some(r=>r.id===v)?`Identifiant déjà pris : ${v} existe dans la bibliothèque. Un fork publie un nouvel identifiant.`:'';
    };
    idField.addEventListener('input',()=>{idField.removeAttribute('aria-invalid');checkId()});
    const defaults=f.initial.defaults.map(d=>{
      const id=`pfbForkDef-${g}-${d.name}`;
      let control;
      if(d.type==='boolean')control=h('input',{type:'checkbox',id,dataset:{def:d.name,type:'boolean'},checked:!!d.value});
      else if(d.type==='enum'){control=h('select',{id,dataset:{def:d.name,type:'enum'}},d.values.map(v=>h('option',{value:v,text:v})));control.value=String(d.value)}
      else{
        const text=h('input',{id,dataset:{def:d.name,type:'color'},value:String(d.value),maxlength:'7',spellcheck:'false',
          pattern:'#[0-9a-fA-F]{6}',class:'pfb-colortext'});
        const swatch=h('input',{type:'color',value:/^#[0-9a-f]{6}$/i.test(String(d.value))?String(d.value):'#000000',
          'aria-label':`${d.name} : nuancier`,tabindex:'-1'});
        swatch.addEventListener('input',()=>{text.value=swatch.value});
        text.addEventListener('input',()=>{if(/^#[0-9a-f]{6}$/i.test(text.value))swatch.value=text.value});
        control=h('span',{class:'pfb-color'},swatch,text);
      }
      return h('div',{class:`pfb-def is-${d.type}`},h('label',{for:id},h('code',{text:d.name}),d.description?h('span',{class:'pfb-defdesc',text:d.description}):null),control);
    });
    const statusZone=h('div',{class:'pfb-formstate',id:`pfbForkState-${g}`});
    const form=h('form',{class:'pfb-form',id:'pfbForkForm','aria-labelledby':`pfbForkTitle-${g}`,novalidate:true,dataset:{gen:String(g)}},
      h('h4',{id:`pfbForkTitle-${g}`},icon('fork'),h('span',{},'Forker « ',iso(f.source.title),` » v${f.source.version} en nouveau prefab`)),
      h('p',{class:'pfb-hint',text:`Le gabarit, le style, le comportement, les entrées, les événements et les données d’exemple sont copiés tels quels. ${f.source.id} ne change pas. Core valide la copie puis la publie en version 1 de son nouvel identifiant, en votre nom.`}),
      h('div',{class:'pfb-fields'},
        h('div',{class:'pfb-field is-id'},h('label',{for:`pfbForkId-${g}`,text:'Identifiant du nouveau prefab'}),idField,
          h('p',{class:'pfb-fieldhint',id:`pfbForkIdHint-${g}`,text:'Votre préfixe puis un nom, en minuscules : team.checklist-red'}),warn),
        h('div',{class:'pfb-field'},h('label',{for:`pfbForkTitleIn-${g}`,text:'Titre'}),
          h('input',{id:`pfbForkTitleIn-${g}`,name:'title',maxlength:'80',dir:'auto',value:f.initial.title})),
        h('div',{class:'pfb-field is-wide'},h('label',{for:`pfbForkDesc-${g}`,text:'Description'}),
          h('textarea',{id:`pfbForkDesc-${g}`,name:'description',maxlength:'600',rows:'3',dir:'auto',value:f.initial.description}))),
      defaults.length?h('fieldset',{class:'pfb-defs'},h('legend',{text:'Réglages par défaut du fork'}),
        h('p',{class:'pfb-fieldhint',text:'Deviennent les valeurs par défaut et l’exemple de la copie.'}),defaults):null,
      statusZone,
      h('div',{class:'pfb-formacts'},
        h('button',{type:'submit',class:'action pfb-primary',id:`pfbForkSubmit-${g}`},'Publier le fork'),
        h('button',{type:'button',class:'action',onclick:()=>{if(lib.cancelFork())focusLater('#pfbForkOpen')}},'Annuler')));
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const values={id:idField.value,title:form.querySelector('[name="title"]').value,
        description:form.querySelector('[name="description"]').value,defaults:{}};
      for(const node of form.querySelectorAll('[data-def]')){
        const t=node.dataset.type;
        values.defaults[node.dataset.def]=t==='boolean'?node.checked:node.value.trim();
      }
      lib.submitFork(values);
    });
    checkId();
    return form;
  }
  function renderFork(){
    const f=S.fork;
    if(!f){if(V.forkGen!==null){V.forkGen=null;replace(D.fork)}return}
    if(V.forkGen!==f.gen){
      V.forkGen=f.gen;replace(D.fork,forkForm(f));
      const first=document.getElementById(`pfbForkId-${f.gen}`);
      if(first)requestAnimationFrame(()=>{first.focus();first.scrollIntoView({block:'nearest'})});
    }
    region('forkstate',JSON.stringify([f.gen,f.status,f.phase,f.error&&[f.error.code,f.error.message,f.error.errors]]),()=>{
      const zone=document.getElementById(`pfbForkState-${f.gen}`);
      const idField=document.getElementById(`pfbForkId-${f.gen}`);
      const submit=document.getElementById(`pfbForkSubmit-${f.gen}`);
      if(!zone)return;
      if(submit)submit.disabled=f.status==='saving';
      const shownCode=f.error?C.errorView(f.error).code:null;
      const idProblem=f.status==='error'&&['base_protected','missing_id','id_taken','invalid_definition'].includes(shownCode)
        &&(shownCode!=='invalid_definition'||/\bid\b/i.test(`${f.error.message} ${(f.error.errors||[]).join(' ')}`));
      if(idField){if(idProblem)idField.setAttribute('aria-invalid','true');else idField.removeAttribute('aria-invalid')}
      replace(zone,f.status==='saving'?loading(f.phase==='source'?'Lecture de la source…':'Publication par Core…',f.started)
        :f.status==='error'?errorBox(f.error,{lead:'Fork refusé : '}):null);
      if(f.status==='error'&&idProblem&&idField)idField.focus();
    });
  }

  function previewManifest(){const v=lib.shown();return v.data?v.data.manifest:null}
  function ensureHost(){
    if(V.host)return V.host;
    const api=window.JarvisPrefabHost;
    if(!api||typeof api.createPrefabHost!=='function')return null;
    try{
      V.host=api.createPrefabHost({mode:'preview',document,window,
        fetchBundle:api.bundleFetcher((path,options)=>window.fetch(path,{...options,cache:'no-store'})),
        onPreviewEvent:event=>lib.logPreviewEvent(event,previewManifest()),
        log:(key,data)=>log(key==='scene.prefab_mounted'?'info':'warn',key.replace(/^scene\./,'prefabs.preview.'),data)});
    }catch(error){
      log('error','prefabs.preview_host_failed',{message:String(error&&error.message)});
      V.host=null;
    }
    return V.host;
  }
  function remountPreview(reset){
    const view=lib.shown();
    const detail=view.data;
    const key=detail?`${detail.id}@${detail.version}`:null;
    if(!reset&&key===V.previewKey)return;
    V.previewKey=key;
    const host=ensureHost();
    if(host&&host.has(C.PREVIEW_OBJECT_ID))host.unmount(C.PREVIEW_OBJECT_ID);
    if(reset)lib.clearPreviewLog();
    if(!detail){replace(D.previewState);D.previewTitle.textContent='';return}
    const m=detail.manifest||{};
    D.previewTitle.textContent=m.title||detail.id;
    if(!host){
      replace(D.previewState,errorBox({code:'preview_unavailable',message:'le runtime des prefabs (JarvisPrefabHost) n’est pas chargé dans cette page'}));
      return;
    }
    if(isRecord(m.source)){
      /* Source Remotion : pas de cadre HTML à monter. Le Player Remotion arrive avec la Slice 10 ; le dire, ne rien simuler. */
      replace(D.previewState,h('p',{class:'pfb-none',id:'pfbNoPreview',
        text:'Aperçu indisponible : c’est une source Remotion (React), qu’un cadre HTML ne peut pas jouer. Son contrat est dans « Contrat du catalogue » ci-dessous.'}));
      return;
    }
    replace(D.previewState);
    const sample=m.sample&&typeof m.sample==='object'?m.sample:{};
    try{
      host.mount(D.previewSlot,{object_id:C.PREVIEW_OBJECT_ID,prefab:{id:detail.id,version:detail.version},title:m.title||detail.id,
        props:sample.props||{},data:sample.data||{}});
    }catch(error){
      log('error','prefabs.preview_mount_failed',{prefab:key,message:String(error&&error.message)});
      replace(D.previewState,errorBox({code:'preview_failed',message:String(error&&error.message)}));
    }
  }
  function renderLog(){
    region('log',JSON.stringify([S.selected,S.previewLog.map(e=>e.seq)]),()=>{
      const entries=S.previewLog;
      replace(D.log,
        h('div',{class:'pfb-loghead'},h('h5',{id:'pfbLogTitle',text:'Événements de l’aperçu'}),
          entries.length?h('button',{type:'button',class:'pfb-link',onclick:()=>lib.clearPreviewLog(),text:'Effacer'}):null),
        entries.length?h('ol',{class:'pfb-logs','aria-labelledby':'pfbLogTitle','aria-live':'polite'},entries.map(e=>{
          const d=new Date(e.at),p=n=>String(n).padStart(2,'0');
          const cls=C.EVENT_CLASSES[e.cls];
          return h('li',{},h('span',{class:'pfb-logtime',text:`${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`}),
            h('code',{class:'pfb-logname',text:e.name}),
            h('span',{class:`pfb-evclass is-${e.cls}`,title:cls?cls.means:null,text:cls?cls.label:e.cls}),
            h('code',{class:'pfb-logpayload',text:e.payload}));
        }))
        :h('p',{class:'pfb-logempty',text:'Interagissez avec l’aperçu : chaque événement émis s’affiche ici. Rien n’est envoyé à Core ni à JARVIS.'}));
    });
  }

  function renderSections(view){
    const detail=view.data;
    const lineage=lib.lineage(S.selected);
    region('sections',JSON.stringify([S.selected,detail&&detail.version,detail&&detail.catalog||null,lineage&&lineage.versions.length,
      lineage&&lineage.versions.map(v=>[v.version,v.status])]),()=>{
      if(!detail){replace(D.sections);return}
      const m=detail.manifest||{};
      const tree=C.inputsTree(m);
      const events=C.eventsOf(m);
      const inputs=h('section',{class:'pfb-sect','aria-labelledby':'pfbInputsTitle'},
        h('h4',{id:'pfbInputsTitle',text:'Entrées'}),
        h('p',{class:'pfb-sechint',text:'props : réglages de présentation · data : contenu enregistré dans la scène'}),
        h('ul',{class:'pfb-tree'},tree.map(n=>h('li',{style:`--depth:${n.depth}`,class:n.depth===0?'is-root':null},
          h('span',{class:'pfb-tline'},h('code',{class:'pfb-tname',text:n.name}),h('span',{class:'pfb-ttype',text:n.type}),
            n.required?h('span',{class:'pfb-treq',title:'obligatoire',text:'requis'}):null,
            n.default?h('span',{class:'pfb-tdef'},'défaut ',h('code',{text:n.default})):null,
            n.bounds?h('span',{class:'pfb-tbound',text:n.bounds}):null),
          n.description?h('span',{class:'pfb-tdesc',dir:'auto',text:n.description}):null))));
      const evs=h('section',{class:'pfb-sect','aria-labelledby':'pfbEventsTitle'},
        h('h4',{id:'pfbEventsTitle',text:'Événements'}),
        events.length?h('ul',{class:'pfb-events'},events.map(e=>{
          const cls=C.EVENT_CLASSES[e.cls];
          return h('li',{},h('span',{class:'pfb-evline'},h('code',{text:e.name}),h('span',{class:`pfb-evclass is-${e.cls}`,text:cls?cls.label:e.cls})),
            h('span',{class:'pfb-evmeans',text:cls?cls.means:`classe inconnue : ${e.cls}`}),
            e.writes.length?h('span',{class:'pfb-evmeta'},'écrit ',e.writes.map((w,i)=>[i?', ':'',h('code',{text:`data.${w}`})])):null,
            e.summary?h('span',{class:'pfb-evsum',dir:'auto',text:e.summary}):null);
        })):h('p',{class:'pfb-none',text:'Aucun événement : ce prefab affiche, il ne réagit pas.'}));
      replace(D.sections,catalogSection(detail),h('div',{class:'pfb-two'},inputs,evs),versionsSection(detail,lineage));
    });
  }
  /* Contrat du catalogue d'UNE version : type, compatibilité par moteur, pile, dépendances, licence, amont ; les paramètres
     éditables ne s'ouvrent qu'à la demande (<details>). Un contrat « déduit » (version publiée avant le bloc `catalog`) le dit. */
  function catalogSection(detail){
    const c=C.catalogOf(detail);
    const head=h('h4',{id:'pfbCatalogTitle',text:'Contrat du catalogue'});
    if(!c)return h('section',{class:'pfb-sect pfb-catalog','aria-labelledby':'pfbCatalogTitle'},head,
      h('p',{class:'pfb-none',text:'Contrat indisponible : Core n’a pas rendu le bloc « catalog » pour cette version. Rien n’est supposé.'}));
    const row=(label,...value)=>[h('dt',{text:label}),h('dd',{},...value)];
    const typeMeans=(C.TYPE_BY_KEY[c.type]||{}).means||'';
    const params=Array.isArray(c.parameters)?c.parameters:[];
    const deps=Array.isArray(c.dependencies)?c.dependencies:[];
    const stack=Array.isArray(c.stack)?c.stack:[];
    const up=c.upstream&&typeof c.upstream==='object'?c.upstream:null;
    return h('section',{class:'pfb-sect pfb-catalog','aria-labelledby':'pfbCatalogTitle'},head,
      h('p',{class:'pfb-sechint',text:c.declared?'Déclaré par le manifeste de cette version.'
        :'Version publiée avant le bloc « catalog » : contrat déduit à la lecture, rien n’a été réécrit.'}),
      h('dl',{class:'pfb-cdl'},
        row('Type',h('strong',{text:C.typeLabel(c.type)}),' ',h('code',{text:c.type}),typeMeans?h('span',{class:'pfb-cmeans',text:` ${typeMeans}`}):null),
        row('Moteurs',h('ul',{class:'pfb-csup'},C.ENGINES.map(e=>{
          const v=C.supportOf(c,e.key);
          return h('li',{class:`is-sup-${v}`},icon(C.SUPPORT[v].icon),h('strong',{text:e.label}),h('span',{text:` ${C.SUPPORT[v].label}`}),
            h('span',{class:'pfb-cmeans',text:` — ${C.SUPPORT[v].means}`}));
        }))),
        row('Pile technique',stack.length?h('span',{class:'pfb-badges'},stack.map(t=>h('span',{class:'pfb-badge is-type'},h('span',{text:t})))):h('span',{class:'pfb-none',text:'non déclarée'})),
        row('Dépendances',deps.length?h('ul',{class:'pfb-cdeps'},deps.map(d=>h('li',{},h('code',{text:d.name}),' ',h('span',{class:'pfb-ver',text:d.version})))):h('span',{class:'pfb-none',text:'aucune déclarée'})),
        row('Licence',c.license?h('span',{text:c.license}):h('span',{class:'pfb-none',text:'non déclarée'})),
        row('Amont',up?h('span',{class:'pfb-up'},h('strong',{text:up.name}),up.ref?h('span',{text:` @ ${up.ref}`}):null,
            h('code',{class:'pfb-upurl',text:up.url}),up.license?h('span',{text:` · licence ${up.license}`}):null,up.author?h('span',{text:` · ${up.author}`}):null,
            h('span',{class:'pfb-cmeans',text:' Déclaré par l’auteur de la version ; Core ne l’a pas vérifié.'}))
          :h('span',{class:'pfb-none',text:'aucun (créé sur ce poste)'}))),
      h('details',{class:'pfb-params',id:'pfbParams'},
        h('summary',{text:`Paramètres éditables (${params.length})`}),
        params.length?h('ul',{class:'pfb-tree'},params.map(pm=>h('li',{style:'--depth:0'},
          h('span',{class:'pfb-tline'},h('code',{class:'pfb-tname',text:pm.name}),h('span',{class:'pfb-ttype',text:pm.type}),
            pm.required?h('span',{class:'pfb-treq',text:'requis'}):null,
            Object.prototype.hasOwnProperty.call(pm,'default')?h('span',{class:'pfb-tdef'},'défaut ',h('code',{text:JSON.stringify(pm.default)})):null,
            Array.isArray(pm.values)&&pm.values.length?h('span',{class:'pfb-tbound',text:`valeurs : ${pm.values.join(', ')}`}):null,
            Array.isArray(pm.range)&&pm.range.some(x=>x!==null)?h('span',{class:'pfb-tbound',text:`bornes : ${pm.range.map(x=>x===null?'…':x).join(' à ')}`}):null),
          pm.description?h('span',{class:'pfb-tdesc',dir:'auto',text:pm.description}):null)))
          :h('p',{class:'pfb-none',text:'Ce prefab ne déclare aucun paramètre éditable : il se règle par ses données.'})));
  }
  function versionsSection(detail,lineage){
    const versions=lineage?lineage.versions.slice().reverse():[];
    return h('section',{class:'pfb-sect pfb-versions','aria-labelledby':'pfbVersionsTitle'},
      h('h4',{id:'pfbVersionsTitle',text:'Versions et provenance'}),
      !lineage?h('p',{class:'pfb-none',text:'Historique en cours de lecture…'})
      :h('ol',{class:'pfb-vlist'},versions.map(v=>{
        const isShown=v.version===detail.version;
        const origin=C.ORIGINS[v.origin]||v.origin||'?';
        const tone=v.origin==='base_edit'?'edited':v.origin==='fork'?'fork':v.origin==='base'?'base':'muted';
        return h('li',{class:`pfb-v${isShown?' is-shown':''}${v.origin==='base_edit'?' is-edit':''}`},
          h('div',{class:'pfb-vline'},
            h('span',{class:'pfb-vnum',text:`v${v.version}`}),
            h('span',{class:`pfb-badge is-${tone}`},v.origin==='base_edit'?icon('pen'):v.origin==='fork'?icon('branch'):v.origin==='base'?icon('lock'):null,h('span',{text:origin})),
            h('span',{class:'pfb-vmeta',text:`par ${C.ACTORS[v.actor]||v.actor||'?'} · ${C.formatWhen(v.at)}`}),
            v.derivedFrom?h('span',{class:'pfb-vmeta'},v.derivedFrom.id===detail.id?`depuis v${v.derivedFrom.version}`:'depuis ',
              v.derivedFrom.id===detail.id?null:h('button',{type:'button',class:'pfb-link',dataset:{goto:v.derivedFrom.id},text:C.refText(v.derivedFrom)})):null,
            v.status!=='ok'?h('span',{class:'pfb-badge is-bad',title:v.problem||null,text:C.VERSION_STATUS[v.status]||v.status}):null,
            isShown?h('span',{class:'pfb-vshown',text:'affichée'})
              :v.status==='ok'?h('button',{type:'button',class:'pfb-link',dataset:{version:String(v.version)},text:'Afficher'}):null),
          v.baseEdit?h('figure',{class:'pfb-quote'},
            h('figcaption',{class:'pfb-quote-cap'},h('strong',{text:'Votre demande, citée telle quelle'}),
              ` · modification faite par JARVIS le ${C.formatWhen(v.at)}`),
            h('blockquote',{},icon('quote','pfb-quote-mark'),h('p',{},'« ',iso(v.baseEdit.request),' »')),
            v.baseEdit.confirmed?h('p',{class:'pfb-confirmed',text:'Confirmée par vous'}):null,
            /* L'identifiant brut du témoin sert au diagnostic, pas à la lecture : replié. */
            h('details',{class:'pfb-witness'},h('summary',{text:'Témoin'}),
              h('p',{},'Événement de conversation qui porte vos mots : ',h('code',{text:v.baseEdit.witness||'—'})))):null);
      })));
  }

  function renderDetail(){
    renderIntro();
    if(!S.selected){remountPreview(false);return}
    const view=lib.shown();
    renderHead(view);renderNotice();renderGuard();renderActions(view);renderFork();
    remountPreview(false);renderLog();renderSections(view);
  }
  function render(){
    renderStatus();renderFilters();renderList();renderDetail();tickClocks();armTick();
  }

  /* ------------------------------------------------------------- ouverture */
  function focusLater(selector){requestAnimationFrame(()=>{const n=q(selector);if(n)n.focus()})}
  function openView(){
    if(!root.hidden)return;
    root.hidden=false;
    V.inerted=[...document.body.children].filter(n=>n!==root&&!n.inert&&n.tagName!=='SCRIPT'&&!n.classList.contains('toasts'));
    for(const node of V.inerted)node.inert=true;
    el.open.classList.add('active');el.open.setAttribute('aria-expanded','true');
    V.keys={};V.previewKey=null;
    lib.open();
    render();
    requestAnimationFrame(()=>el.search.focus({preventScroll:true}));
  }
  function closeView(){
    if(root.hidden)return;
    root.hidden=true;
    if(V.host&&V.host.has(C.PREVIEW_OBJECT_ID))V.host.unmount(C.PREVIEW_OBJECT_ID);
    V.previewKey=null;
    lib.close();
    clearInterval(V.tick);V.tick=null;
    for(const node of V.inerted)node.inert=false;
    V.inerted=[];
    el.open.classList.remove('active');el.open.setAttribute('aria-expanded','false');
    el.open.focus({preventScroll:true});
  }
  function selectRow(id){
    lib.select(id);
    const row=S.list.rows.find(r=>r.id===id);
    announce(`${row&&row.title||id} sélectionné`);
  }

  buildDetailShell();
  el.open.addEventListener('click',()=>{root.hidden?openView():closeView()});
  el.close.addEventListener('click',closeView);
  el.refresh.addEventListener('click',()=>lib.refresh());
  el.search.addEventListener('input',()=>{
    clearTimeout(V.searchTimer);
    V.searchTimer=setTimeout(()=>lib.setQuery(el.search.value),SEARCH_DEBOUNCE_MS);
  });
  el.search.addEventListener('keydown',event=>{
    if(event.key==='Enter'){event.preventDefault();clearTimeout(V.searchTimer);lib.setQuery(el.search.value)}
    if(event.key==='ArrowDown'){const first=el.list.querySelector('.pfb-row');if(first){event.preventDefault();first.focus()}}
  });
  el.family.addEventListener('change',()=>lib.setFamily(el.family.value));
  el.type.addEventListener('change',()=>lib.setType(el.type.value));
  el.engine.addEventListener('change',()=>lib.setEngine(el.engine.value));
  el.stack.addEventListener('change',()=>lib.setStack(el.stack.value));
  el.list.addEventListener('click',event=>{
    const row=event.target.closest&&event.target.closest('.pfb-row');
    if(row)selectRow(row.dataset.id);
  });
  /* Liste : ↑ ↓ Début Fin déplacent le focus ET la sélection. */
  el.list.addEventListener('keydown',event=>{
    const rows=[...el.list.querySelectorAll('.pfb-row')];
    const index=rows.indexOf(document.activeElement);
    if(index<0)return;
    const next={ArrowDown:index+1,ArrowUp:index-1,Home:0,End:rows.length-1}[event.key];
    if(next===undefined)return;
    event.preventDefault();
    const target=rows[Math.max(0,Math.min(rows.length-1,next))];
    target.focus();selectRow(target.dataset.id);
  });
  /* Liens de provenance (`data-goto`) et versions (`data-version`) du détail. */
  el.detail.addEventListener('click',event=>{
    const go=event.target.closest&&event.target.closest('[data-goto]');
    if(go){
      V.pendingFocus=go.dataset.goto;
      selectRow(go.dataset.goto);
      const title=q('#pfbDetailTitle');if(title)requestAnimationFrame(()=>{const t=q('#pfbDetailTitle');if(t)t.focus()});
      return;
    }
    const ver=event.target.closest&&event.target.closest('[data-version]');
    if(ver){lib.selectVersion(Number(ver.dataset.version));focusLater('#pfbDetailTitle')}
  });
  /* Échap : d'abord le formulaire de fork, ensuite la vue. `/` : la recherche. */
  document.addEventListener('keydown',event=>{
    if(root.hidden)return;
    if(event.key==='Escape'){
      event.preventDefault();event.stopPropagation();
      if(S.fork){if(lib.cancelFork())focusLater('#pfbForkOpen');return}
      closeView();return;
    }
    const t=event.target;
    const typing=t&&(t.isContentEditable||['INPUT','TEXTAREA','SELECT'].includes(t.tagName));
    if(event.key==='/'&&!typing&&!event.ctrlKey&&!event.metaKey&&!event.altKey){event.preventDefault();el.search.focus();el.search.select()}
  },true);
  root.addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const focusable=[...root.querySelectorAll('a[href],button:not([disabled]):not([tabindex="-1"]),input:not([disabled]):not([type=hidden]):not([tabindex="-1"]),select:not([disabled]),textarea,summary,iframe,[tabindex="0"]')]
      .filter(node=>node.offsetParent!==null);
    if(!focusable.length)return;
    const first=focusable[0],last=focusable[focusable.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
  });

  window.JarvisPrefabLibrary=Object.freeze({open:openView,close:closeView,select:selectRow,state:S,library:lib});
  console.info('[prefabs] prefabs.installed {}');
})();
