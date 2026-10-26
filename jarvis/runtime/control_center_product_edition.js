/* Édition produit, côté page (jarvis-presentation-edition-v1, Slice 08).

   Contrat : `docs/control-center-shell.md` › *Product edition UI* ; données : `docs/product-edition.md`
   › *Availability*. Ce module ne décide rien : il LIT la seule table de disponibilité, `GET /api/boards/edition`
   (relais de Core, `ProductEditionPolicy.to_payload()`), et la rend aux autres modules de la page.

   Deux faits, deux sources :

   - **Types de Board** (`board_kinds`, `default_board_kind`) : Core seulement. Tant que Core n'a pas répondu,
     aucun type n'est dit disponible (`kindView` → `unknown`) : la création attend, jamais d'optimisme.
   - **Surfaces de développement** (`developer_surfaces` : `visible` | `hidden`) : posées dès le premier octet
     sur `<html data-developer-surfaces>` par le Control Center, qui lit la MÊME politique
     (`product_edition_env.page_edition_markup`) ; Core la confirme ensuite (Core gagne s'ils divergent, et
     c'est journalisé). Ainsi une édition produit ne montre jamais un outil de développement, même un instant,
     même Core arrêté ; une page servie sans marquage (fixture, extrait) reste `visible`, comme avant.

   Une surface se déclare développeur là où elle est déclarée (attribut `data-surface="developer"` dans le
   balisage, `surface:'developer'` d'une catégorie ou d'une section des Réglages) : aucune liste de surfaces
   ici. La feuille de la page cache `[data-surface="developer"]` sous `html[data-developer-surfaces="hidden"]`.

   Lecture : À LA DEMANDE (`ensure()`), quand une surface en a besoin — ouverture du panneau des Boards, choix du
   type, accueil vide d'un Board Présentation — jamais au démarrage : les surfaces de développement viennent déjà du
   marquage, et un Control Center sans Core ne reçoit aucune requête. Bornée (`DEADLINE_MS`), reprise avec un recul
   croissant (`RETRY_MS`) tant que le battement de la page dit que Core sert ses Boards (`gate(status.boards)`) ;
   `refresh()` relit sur demande (« Réessayer »). Journal `[edition] edition.<clé> {json}`. */
(function(root){
  'use strict';

  const ROUTE='/api/boards/edition';
  const DEADLINE_MS=8000;
  const RETRY_MS=Object.freeze([2000,4000,8000,16000,30000]);
  const SURFACES=Object.freeze(['visible','hidden']);
  const KIND_STATES=Object.freeze({available:'available',soon:'soon',unknown:'unknown'});
  /* Ce que dit un type indisponible : une capacité à venir, jamais une erreur (D01). */
  const SOON_TAG='Bientôt disponible';
  const SOON_SAID=label=>`${label} : bientôt disponible. Cette édition de Jarvis crée des Boards Présentation.`;

  const isObject=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
  const text=value=>value===undefined||value===null?'':String(value);

  /* ------------------------------------------------ logique pure (testée sous node) */

  /* La charge de Core → modèle. Illisible : `{ok:false, code}` ; jamais un modèle deviné. */
  function parse(payload){
    if(!isObject(payload)||typeof payload.edition!=='string'||!payload.edition||!Array.isArray(payload.board_kinds))
      return {ok:false,code:'edition_payload_invalid'};
    const kinds={},order=[];
    for(const row of payload.board_kinds){
      if(!isObject(row)||typeof row.board_kind!=='string'||!row.board_kind)return {ok:false,code:'edition_payload_invalid'};
      kinds[row.board_kind]=Object.freeze({available:row.available===true,behavior_status:text(row.behavior_status)});
      order.push(row.board_kind);
    }
    const available=order.filter(k=>kinds[k].available);
    const fallback=available[0]||null;
    const defaultKind=typeof payload.default_board_kind==='string'&&kinds[payload.default_board_kind]&&kinds[payload.default_board_kind].available
      ?payload.default_board_kind:fallback;
    /* Absent (Core d'avant la Slice 08) : rien n'est caché, comme avant. */
    const developerSurfaces=SURFACES.includes(payload.developer_surfaces)?payload.developer_surfaces:'visible';
    return {ok:true,model:Object.freeze({edition:payload.edition,defaultKind,developerSurfaces,
      kinds:Object.freeze(kinds),order:Object.freeze(order),available:Object.freeze(available),
      restricts:available.length<order.length})};
  }

  /* Un type, lu dans le modèle : `available` (se crée), `soon` (connu, indisponible : « Bientôt disponible »),
     `unknown` (Core n'a pas encore répondu, ou le type n'est pas dans sa table : rien ne se crée). */
  function kindView(model,kind){
    if(!model||!model.kinds||!Object.prototype.hasOwnProperty.call(model.kinds,kind))return {state:KIND_STATES.unknown,available:false};
    return model.kinds[kind].available?{state:KIND_STATES.available,available:true}:{state:KIND_STATES.soon,available:false};
  }

  /* Valeur du marquage serveur (`<html data-developer-surfaces>`) : `visible` | `hidden`, sinon `null` (non marqué). */
  function pageSurfaces(value){return SURFACES.includes(value)?value:null}

  /* Une surface (`product` | `developer`, absent = produit) est-elle montrée ? Inconnu : montrée (page non marquée). */
  function surfaceShown(surface,developerSurfaces){return surface!=='developer'||developerSurfaces!=='hidden'}

  /* Recul de la n-ième reprise (1, 2, …), plafonné au dernier palier. */
  function retryDelay(attempt){return RETRY_MS[Math.min(RETRY_MS.length,Math.max(1,attempt))-1]}

  const pure={ROUTE,DEADLINE_MS,RETRY_MS,KIND_STATES,SOON_TAG,SOON_SAID,parse,kindView,pageSurfaces,surfaceShown,retryDelay};

  /* ------------------------------------------------ page */

  function createStore(deps){
    const d=deps||{};
    const doc=d.document||null,html=doc&&doc.documentElement;
    const fetchImpl=d.fetch||null;
    const later=d.setTimeout||((fn,ms)=>setTimeout(fn,ms)),cancel=d.clearTimeout||(id=>clearTimeout(id));
    const now=d.now||(()=>Date.now());
    const sink=d.console||null;
    const listeners=new Set();
    const marked=pageSurfaces(html&&html.getAttribute?html.getAttribute('data-developer-surfaces'):null);
    const S={status:'idle',model:null,error:null,attempt:0,since:0,surfaces:marked||'visible',source:marked?'page':'default',
      inFlight:null,retry:0,coreBoards:false};

    function log(level,key,data){
      const line=`[edition] edition.${key} ${JSON.stringify(data||{})}`;
      try{if(!sink)return;if(level==='error')sink.error(line);else if(level==='warn')sink.warn(line);else sink.info(line)}
      catch(_e){/* intentional: a broken console must not break the page */}
    }
    function snapshot(){
      return Object.freeze({status:S.status,model:S.model,error:S.error,attempt:S.attempt,since:S.since,
        developerSurfaces:S.surfaces,source:S.source});
    }
    function emit(){
      const view=snapshot();
      for(const fn of [...listeners]){try{fn(view)}catch(error){log('error','listener_failed',{error:text(error&&error.message)})}}
      if(doc&&typeof doc.dispatchEvent==='function'&&typeof root.CustomEvent==='function'){
        try{doc.dispatchEvent(new root.CustomEvent('jarvis:product-edition',{detail:view}))}catch(_e){/* intentional: event optional */}
      }
    }
    function applySurfaces(value,source){
      const changed=value!==S.surfaces;
      if(changed&&S.source==='page'&&source==='core')
        log('warn','surfaces_disagree',{page:S.surfaces,core:value,kept:'core'});
      S.surfaces=value;S.source=source;
      if(html&&html.setAttribute)html.setAttribute('data-developer-surfaces',value);
      return changed;
    }
    function schedule(){
      /* Core ne sert pas ses Boards : pas de reprise ; le battement qui les dit revenus relira (`gate`). */
      if(S.retry||!S.coreBoards)return;
      const wait=retryDelay(S.attempt);
      S.retry=later(()=>{S.retry=0;load()},wait);
    }
    async function load(){
      if(S.inFlight)return S.inFlight;
      if(S.retry){cancel(S.retry);S.retry=0}
      S.attempt+=1;S.status=S.model?'ready':'loading';S.since=now();emit();
      S.inFlight=(async()=>{
        let timer=0;
        const controller=typeof root.AbortController==='function'?new root.AbortController():null;
        try{
          if(!fetchImpl)throw Object.assign(new Error('la porte réseau de la page manque'),{code:'network'});
          const deadline=new Promise((_,reject)=>{timer=later(()=>{if(controller)controller.abort();
            reject(Object.assign(new Error(`pas de réponse après ${DEADLINE_MS/1000} s`),{code:'timeout'}))},DEADLINE_MS)});
          const response=await Promise.race([fetchImpl(ROUTE,{cache:'no-store',signal:controller?controller.signal:undefined}),deadline]);
          let body=null;try{body=await response.json()}catch(_e){body=null /* intentional: reported below as unreadable */}
          if(!response.ok){
            const e=isObject(body)&&isObject(body.error)?body.error:{};
            throw Object.assign(new Error(text(e.message)||`HTTP ${response.status}`),{code:text(e.code)||`http_${response.status}`,status:response.status});
          }
          const parsed=parse(body);
          if(!parsed.ok)throw Object.assign(new Error('réponse illisible'),{code:parsed.code});
          S.model=parsed.model;S.error=null;S.status='ready';S.attempt=0;
          applySurfaces(parsed.model.developerSurfaces,'core');
          log('info','loaded',{edition:parsed.model.edition,available:parsed.model.available,developer_surfaces:parsed.model.developerSurfaces});
        }catch(error){
          const code=text(error&&error.code)||'network';
          S.error=Object.freeze({code,status:error&&typeof error.status==='number'?error.status:null,message:text(error&&error.message)});
          S.status=S.model?'ready':'error';
          log('warn','load_failed',{code,status:S.error.status,message:S.error.message,attempt:S.attempt,retry_ms:retryDelay(S.attempt)});
          schedule();
        }finally{
          if(timer)cancel(timer);
          S.inFlight=null;
          emit();
        }
      })();
      return S.inFlight;
    }
    if(marked&&html&&html.setAttribute)html.setAttribute('data-developer-surfaces',marked);
    return {
      /* Le bloc `boards` de `/api/status` (1 Hz) : tant que Core sert ses Boards, une lecture tombée est reprise ; quand
         il revient après une panne, elle repart aussitôt. */
      gate(boards){
        const up=!!(boards&&typeof boards==='object'&&boards.available===true);
        const was=S.coreBoards;S.coreBoards=up;
        if(up&&!was&&S.status==='error'&&!S.model&&!S.inFlight&&!S.retry)load();
      },
      /* Première lecture, une seule fois (appel sans effet ensuite). Une lecture tombée n'est PAS relancée ici : le
         rail appelle `ensure` à chaque rendu et se rend à chaque `emit` — relire ici ferait une boucle de requêtes
         quand Core ne sert pas ses Boards. Elle repart par la reprise (`schedule`), le retour de Core (`gate`) ou
         « Réessayer » (`refresh`), que l'écran du type montre avec la cause. */
      ensure(){if(S.status==='idle'&&!S.inFlight)load()},
      refresh(){return load()},
      state:snapshot,
      subscribe(fn){if(typeof fn==='function'){listeners.add(fn);try{fn(snapshot())}catch(error){log('error','listener_failed',{error:text(error&&error.message)})}}
        return ()=>listeners.delete(fn)},
      developerSurfacesShown(){return S.surfaces!=='hidden'},
      /* Un élément de la page est-il une surface cachée par l'édition ? (lui ou un parent marqué `developer`). */
      hides(element){return S.surfaces==='hidden'&&!!(element&&element.closest&&element.closest('[data-surface="developer"]'))},
    };
  }

  const api=Object.assign({createStore,instance:null},pure);
  /* Raccourcis pour les autres modules : sans instance (extrait node, page sans réseau), le marquage de `<html>`. */
  api.developerSurfacesShown=()=>{
    if(api.instance)return api.instance.developerSurfacesShown();
    const html=root&&root.document&&root.document.documentElement;
    return surfaceShown('developer',pageSurfaces(html&&html.getAttribute?html.getAttribute('data-developer-surfaces'):null));
  };
  api.state=()=>api.instance?api.instance.state():null;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(root&&root.document&&typeof root.fetch==='function'){
    try{
      api.instance=createStore({document:root.document,fetch:(path,init)=>root.fetch(path,init),console:root.console});
      /* La lecture attend le battement de statut (`gate`, appelé par `refreshStatus` de la page). */
    }catch(error){
      try{root.console.error('[edition] edition.install_failed '+JSON.stringify({error:text(error&&error.message)}))}catch(_e){/* intentional */}
    }
  }
  if(root)root.JarvisProductEdition=api;
})(typeof window!=='undefined'?window:globalThis);
