/* Plein écran générique d'une surface de scène (studio de présentation, Slice 03).

   « Plein écran sans bordure » = l'API Fullscreen du navigateur sur un élément
   HÔTE qui contient le cadre du prefab (décision R4, docs/06-resolved-architecture.md).
   Jamais depuis le cadre : son `sandbox="allow-scripts"` n'a pas `allow="fullscreen"`
   (`document.fullscreenEnabled` y vaut false) et ce module n'y touche pas — ni
   `sandbox`, ni CSP, ni protocole `jv:1`.

   Quatre règles tiennent le module :

   - **La vérité est `fullscreenchange`.** L'état « entered » n'existe que quand le
     navigateur le constate ; un recouvrement CSS n'est jamais déclaré plein écran.
   - **Un geste est obligatoire**, donc une demande de la voix ou d'un agent n'entre
     pas : elle ARME. Une invite visible (bouton, compte à rebours, Annuler) attend
     UN clic, et `requestFullscreen()` est appelé dans ce clic, de façon synchrone.
     L'armement a toujours une échéance ; à l'échéance l'invite part et le dit.
   - **Échap sort**, sans code d'application. On apprend la sortie par
     `fullscreenchange`, puis on restaure focus et marqueurs.
   - **Tout échec se voit et se journalise** : toast, ligne d'erreur dans l'invite,
     `console` préfixée `[fullscreen]`, et rapport d'état au serveur
     (`POST /api/fullscreen/state`) qui l'écrit au journal.

   Transport : sibling du canal de commandes Bare Hands (long-poll + reçu),
   `GET/POST /api/fullscreen/commands`. Le vocabulaire et la table de transitions
   sont miroités de `jarvis/domain/surface_fullscreen.py` (test de parité).

   Touches : le cadre ne relaie aucune touche ; pour la navigation (flèches, Page,
   Espace, Début/Fin) ce module écoute l'élément hôte. */
(function(root){
  'use strict';

  const ACTIONS=Object.freeze(['enter','exit']);
  const STATES=Object.freeze(['entered','exited','needs_gesture','unsupported','refused','expired']);
  const EVENTS=Object.freeze(['request_enter','unsupported','browser_entered','browser_exited','browser_denied','deadline','cancel']);
  const TRANSITIONS=Object.freeze((()=>{
    const t={
      'exited|request_enter':'needs_gesture','exited|unsupported':'unsupported','exited|browser_entered':'entered',
      'exited|browser_exited':'exited','exited|browser_denied':'refused',
      'needs_gesture|request_enter':'needs_gesture','needs_gesture|unsupported':'unsupported',
      'needs_gesture|browser_entered':'entered','needs_gesture|browser_exited':'exited',
      'needs_gesture|browser_denied':'refused','needs_gesture|deadline':'expired','needs_gesture|cancel':'exited',
      'entered|request_enter':'entered','entered|browser_entered':'entered','entered|browser_exited':'exited',
      'entered|browser_denied':'entered',
    };
    for(const rest of ['refused','expired','unsupported']){
      t[rest+'|request_enter']='needs_gesture';t[rest+'|unsupported']='unsupported';
      t[rest+'|browser_entered']='entered';t[rest+'|browser_exited']='exited';t[rest+'|browser_denied']='refused';
    }
    return t;
  })());
  const DISPLAY_SELECTIONS=Object.freeze(['not_requested','unavailable','denied','granted','missing']);
  const PAGE_CODES=Object.freeze({
    UNSUPPORTED:'fullscreen_unsupported',DENIED:'fullscreen_denied',TARGET_MISSING:'fullscreen_target_missing',
    CANCELLED:'fullscreen_cancelled',ARM_EXPIRED:'fullscreen_arm_expired',NEEDS_GESTURE:'fullscreen_needs_gesture',
    OTHER_ENTERED:'fullscreen_other_surface_entered',EXIT_FAILED:'fullscreen_exit_failed',PAGE_ERROR:'fullscreen_page_error',
  });
  const ROUTE='/api/fullscreen/commands';
  const STATE_ROUTE='/api/fullscreen/state';
  const POLL_WAIT_S=25;
  const POLL_TIMEOUT_MS=30000;
  const RECEIPT_TIMEOUT_MS=4000;
  const BACKOFF_BASE_MS=500;
  const BACKOFF_MAX_MS=15000;
  const DEFAULT_ARM_S=30;
  const REASON_MAX=200;
  const STYLE_ID='jv-fullscreen-style';
  const PROMPT_ID='jvFullscreenPrompt';
  const SCENE_ROOT_ID='sceneLayer';
  /* Touches de navigation lues sur l'hôte. Pas d'Échap (navigateur), pas de combinaison avec Ctrl/Alt/Méta. */
  const NAV_KEYS=Object.freeze({
    ArrowRight:'next',ArrowDown:'next',PageDown:'next',' ':'next',
    ArrowLeft:'previous',ArrowUp:'previous',PageUp:'previous',Backspace:'previous',
    Home:'first',End:'last',
  });

  /* Styles : l'élément plein écran remplit l'écran sur fond noir et ne montre que le cadre (le titre, les
     poignées et la chrome de fenêtre sont masqués) ; l'invite est une carte flottante sobre. Aucun mouvement
     n'est géré par CSS sauf la barre d'échéance, et seulement hors « mouvement réduit ». */
  const STYLE=`
:fullscreen:has(> .sc-prefab-slot){display:flex!important;flex-direction:column!important;background:#000!important;
  border:0!important;border-radius:0!important;box-shadow:none!important;padding:0!important;overflow:hidden!important;
  filter:none!important;backdrop-filter:none!important;animation:none!important;opacity:1!important}
:fullscreen:has(> .sc-prefab-slot)>:not(.sc-prefab-slot){display:none!important}
:fullscreen>.sc-prefab-slot{flex:1 1 auto!important;min-height:0!important;height:100%!important;overflow:hidden!important}
:fullscreen .sc-prefab-frame{flex:1 1 auto!important;height:100%!important;max-height:none!important;background:#000!important}
:fullscreen:has(> .sc-prefab-slot)::backdrop{background:#000}
#${PROMPT_ID}{position:fixed;left:50%;top:18px;transform:translateX(-50%);z-index:9500;box-sizing:border-box;
  width:min(520px,calc(100vw - 32px));display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px 14px;align-items:center;
  padding:14px 16px;border-radius:10px;border:1px solid var(--line,#183343);background:var(--panel,rgba(6,12,18,.96));
  color:var(--text,#d8edf7);font:13px/1.45 system-ui,Segoe UI,sans-serif;box-shadow:0 12px 40px rgba(0,0,0,.55)}
#${PROMPT_ID} .jvfs-title{display:block;font-weight:650;font-size:14px}
#${PROMPT_ID} .jvfs-desc{display:block;color:var(--muted,#7190a0);overflow-wrap:anywhere}
#${PROMPT_ID} .jvfs-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
#${PROMPT_ID} button{font:inherit;min-height:36px;padding:0 14px;border-radius:8px;cursor:pointer;
  border:1px solid var(--line,#183343);background:transparent;color:inherit}
#${PROMPT_ID} button.jvfs-go{background:var(--accent,#6ee7ff);color:#04131a;border-color:transparent;font-weight:650}
#${PROMPT_ID} button:focus-visible{outline:2px solid var(--accent,#6ee7ff);outline-offset:2px}
#${PROMPT_ID} .jvfs-meter{grid-column:1/-1;display:flex;align-items:center;gap:10px;color:var(--muted,#7190a0);
  font-variant-numeric:tabular-nums}
#${PROMPT_ID} .jvfs-bar{flex:1 1 auto;height:3px;border-radius:2px;background:rgba(113,144,160,.25);overflow:hidden}
#${PROMPT_ID} .jvfs-bar>i{display:block;height:100%;width:100%;background:var(--accent,#6ee7ff);transform-origin:left center}
@media (prefers-reduced-motion:no-preference){#${PROMPT_ID} .jvfs-bar>i{transition:transform .25s linear}}
#${PROMPT_ID} .jvfs-error{grid-column:1/-1;margin:0;color:var(--warn,#ffb85c)}
#${PROMPT_ID} .jvfs-error[hidden]{display:none}
@media (forced-colors:active){#${PROMPT_ID}{border-color:CanvasText}#${PROMPT_ID} button.jvfs-go{border-color:ButtonText}}
`;

  function messageOf(error){return String(error&&error.message||error||'erreur inconnue')}
  function nextState(state,event){
    const key=state+'|'+event;
    return Object.prototype.hasOwnProperty.call(TRANSITIONS,key)?TRANSITIONS[key]:null;
  }
  function backoffDelay(failures,random){
    const ceiling=Math.min(BACKOFF_MAX_MS,BACKOFF_BASE_MS*Math.pow(2,Math.max(0,failures-1)));
    return Math.round(ceiling/2+(random?random():Math.random())*ceiling/2);
  }

  /* ---------------------------------------------------------------- contrôleur */
  function createFullscreenController(deps){
    const doc=deps.document;
    const win=deps.window||root;
    const now=deps.now||(()=>Date.now());
    const setT=deps.setTimeout||((fn,ms)=>setTimeout(fn,ms));
    const clearT=deps.clearTimeout||(id=>clearTimeout(id));
    const setI=deps.setInterval||((fn,ms)=>setInterval(fn,ms));
    const clearI=deps.clearInterval||(id=>clearInterval(id));
    const log=deps.log||(()=>{});
    const notify=deps.toast||(()=>{});
    const stats={commands:0,armed:0,entered:0,exited:0,refused:0,expired:0,cancelled:0,unsupported:0,reportFailed:0,keys:0};
    let state='exited';
    let armed=null;        /* {id,objectId,display,keys,deadlineAt,ticker,timer,ui,restoreFocus} */
    let active=null;       /* {el,objectId,keys,prevFocus,prevTab,keyHandler,blurHandler,displaySelection} */
    const navListeners=new Set();
    let lastDisplaySelection='not_requested';
    let pendingLocal=null; /* entrée locale en cours : {objectId,keys}, lue par fullscreenchange */

    function transition(event){
      const next=nextState(state,event);
      if(next===null){
        log('warn','fullscreen.transition_invalid',{from:state,event});
        return state;
      }
      if(next!==state)log('info','fullscreen.state_changed',{from:state,to:next,event});
      state=next;
      return state;
    }

    /* ---- support, cible, écran */
    function unsupportedReason(){
      if(!doc||typeof doc.fullscreenEnabled==='undefined')return "L'API Fullscreen est absente de ce navigateur.";
      if(doc.fullscreenEnabled!==true)return "Le navigateur ou la politique de la page interdit le plein écran.";
      return null;
    }
    function sceneRoot(){return doc.getElementById(SCENE_ROOT_ID)}
    function resolveTarget(objectId){
      if(objectId===null||objectId===undefined)return sceneRoot();
      for(const el of Array.from(doc.querySelectorAll('[data-object-id]'))){
        if(el.dataset&&el.dataset.objectId===objectId)return el.isConnected===false?null:el;
      }
      return null;
    }
    function titleOf(el,objectId){
      if(!el)return 'la scène';
      if(objectId===null||objectId===undefined)return 'la scène';
      const head=el.querySelector&&el.querySelector('[data-title],.sc-title,h1,h2,h3');
      return (head&&head.textContent||el.getAttribute&&el.getAttribute('aria-label')||objectId).trim().slice(0,80)||objectId;
    }
    async function resolveDisplay(display){
      if(display==='current'||display===undefined||display===null)return {selection:'not_requested',screen:null};
      if(typeof win.getScreenDetails!=='function')return {selection:'unavailable',screen:null};
      let details;
      try{details=await win.getScreenDetails()}
      catch(error){
        const denied=error&&(error.name==='NotAllowedError'||error.name==='SecurityError');
        log('warn','fullscreen.display_unavailable',{name:error&&error.name||'',denied});
        return {selection:denied?'denied':'unavailable',screen:null};
      }
      const screens=Array.from(details&&details.screens||[]);
      let chosen=null;
      if(display==='primary')chosen=screens.find(s=>s.isPrimary)||null;
      else if(display==='other')chosen=screens.find(s=>s!==details.currentScreen&&!(s.left===details.currentScreen.left&&s.top===details.currentScreen.top))||null;
      else if(Number.isInteger(display))chosen=screens[display]||null;
      if(!chosen){
        log('warn','fullscreen.display_missing',{display,screens:screens.length});
        return {selection:'missing',screen:null};
      }
      return {selection:'granted',screen:chosen};
    }

    /* ---- rapport au serveur (la page est la vérité ; le serveur tient l'état lisible par l'agent) */
    async function report(body){
      if(typeof deps.request!=='function')return;
      try{
        const answer=await deps.request(STATE_ROUTE,{method:'POST',body:JSON.stringify(body),timeoutMs:RECEIPT_TIMEOUT_MS});
        if(answer.status!==200){
          const error=answer.body&&answer.body.error||{};
          throw new Error(String(error.message||`HTTP ${answer.status}`)+(error.code?` (${error.code})`:''));
        }
      }catch(error){
        stats.reportFailed++;
        log('warn','fullscreen.report_failed',{state:body.state,error:messageOf(error)});
      }
    }
    function reportState(next,extra){
      const body=Object.assign({state:next,display_selection:lastDisplaySelection},extra||{});
      for(const key of Object.keys(body))if(body[key]===null||body[key]===undefined)delete body[key];   /* le serveur n'attend que des champs présents */
      if(body.reason)body.reason=String(body.reason).slice(0,REASON_MAX);
      return report(body);
    }

    /* ---- invite d'armement */
    function removePrompt(restoreFocus){
      if(!armed)return;
      const was=armed;armed=null;
      if(was.ticker)clearI(was.ticker);
      if(was.timer)clearT(was.timer);
      if(was.ui&&was.ui.root&&was.ui.root.parentNode)was.ui.root.parentNode.removeChild(was.ui.root);
      if(restoreFocus&&was.restoreFocus&&was.restoreFocus.isConnected!==false&&typeof was.restoreFocus.focus==='function'){
        try{was.restoreFocus.focus({preventScroll:true})}catch(error){log('warn','fullscreen.focus_restore_failed',{error:messageOf(error)})}
      }
    }
    function el(tag,className,text){
      const node=doc.createElement(tag);
      if(className)node.className=className;
      if(text!==undefined)node.textContent=text;
      return node;
    }
    function buildPrompt(spec,target){
      const box=el('div');box.id=PROMPT_ID;
      box.setAttribute('role','alertdialog');
      box.setAttribute('aria-labelledby',PROMPT_ID+'Title');
      box.setAttribute('aria-describedby',PROMPT_ID+'Desc');
      box.setAttribute('data-state','needs_gesture');
      const text=el('div');
      const title=el('span','jvfs-title','Plein écran demandé');title.id=PROMPT_ID+'Title';
      const desc=el('span','jvfs-desc',`JARVIS veut afficher ${titleOf(target,spec.object_id)} en plein écran. `
        +"Le navigateur exige un clic de votre part : Échap permet de quitter à tout moment.");
      desc.id=PROMPT_ID+'Desc';
      text.appendChild(title);text.appendChild(desc);
      const actions=el('div','jvfs-actions');
      const go=el('button','jvfs-go','Passer en plein écran');go.type='button';
      const cancel=el('button','jvfs-cancel','Annuler');cancel.type='button';
      actions.appendChild(go);actions.appendChild(cancel);
      const meter=el('div','jvfs-meter');
      const count=el('span','jvfs-count','');
      const bar=el('span','jvfs-bar');const fill=el('i');bar.appendChild(fill);
      meter.appendChild(count);meter.appendChild(bar);
      const error=el('p','jvfs-error');error.hidden=true;error.setAttribute('role','alert');
      box.appendChild(text);box.appendChild(actions);box.appendChild(meter);box.appendChild(error);
      return {root:box,go,cancel,count,fill,error};
    }
    function paintCountdown(){
      if(!armed)return;
      const left=Math.max(0,armed.deadlineAt-now());
      const total=Math.max(1,armed.totalMs);
      armed.ui.count.textContent=`${Math.ceil(left/1000)} s`;
      armed.ui.fill.style.transform=`scaleX(${Math.max(0,Math.min(1,left/total))})`;
    }
    function showPromptError(message){
      if(!armed)return;
      armed.ui.error.textContent=message;armed.ui.error.hidden=false;
    }

    /* Arme la demande : l'invite est dessinée tout de suite (reçu synchrone en `needs_gesture`). */
    function arm(spec,target,id){
      removePrompt(false);
      const restoreFocus=doc.activeElement&&doc.activeElement!==doc.body?doc.activeElement:null;
      const totalMs=Math.round((Number(spec.arm_s)||DEFAULT_ARM_S)*1000);
      const ui=buildPrompt(spec,target);
      armed={id:id||null,objectId:spec.object_id===undefined?null:spec.object_id,display:spec.display||'current',
        keys:spec.keys||'host',totalMs,deadlineAt:now()+totalMs,ticker:null,timer:null,ui,restoreFocus,permissionAsked:false};
      doc.body.appendChild(ui.root);
      paintCountdown();
      armed.ticker=setI(paintCountdown,250);
      armed.timer=setT(()=>expireArm(),totalMs);
      ui.go.addEventListener('click',()=>{onPromptClick().catch(error=>failUnexpected('click',error))});
      ui.cancel.addEventListener('click',()=>cancelArm('Annulé par l\'utilisateur.'));
      ui.root.addEventListener('keydown',event=>{
        if(event.key==='Escape'){event.preventDefault();cancelArm('Annulé par l\'utilisateur (Échap).')}
      });
      try{ui.go.focus({preventScroll:true})}catch(error){log('warn','fullscreen.prompt_focus_failed',{error:messageOf(error)})}
      stats.armed++;
      transition('request_enter');
      log('info','fullscreen.armed',{id:armed.id,object_id:armed.objectId,display:armed.display,arm_s:totalMs/1000});
    }
    function expireArm(){
      if(!armed)return;
      const id=armed.id,waited=Math.round(armed.totalMs/1000);
      removePrompt(true);
      transition('deadline');stats.expired++;
      const reason=`Personne n'a cliqué dans les ${waited} s : l'invite a été retirée, rien n'a changé.`;
      log('warn','fullscreen.arm_expired',{id,waited_s:waited});
      notify({title:'Plein écran non activé',sub:reason,kind:'warn'});
      reportState('expired',{id,code:PAGE_CODES.ARM_EXPIRED,reason});
    }
    function cancelArm(reason){
      if(!armed)return false;
      const id=armed.id;
      removePrompt(true);
      transition('cancel');stats.cancelled++;
      log('info','fullscreen.arm_cancelled',{id,reason});
      reportState('exited',{id,code:PAGE_CODES.CANCELLED,reason});
      return true;
    }
    function failUnexpected(where,error){
      const reason=`Plein écran : erreur inattendue (${where}) : ${messageOf(error)}`;
      log('error','fullscreen.page_error',{where,error:messageOf(error)});
      notify({title:'Plein écran impossible',sub:reason,kind:'bad'});
      const id=armed&&armed.id;
      removePrompt(true);
      transition('browser_denied');stats.refused++;
      reportState('refused',{id,code:PAGE_CODES.PAGE_ERROR,reason});
    }

    /* Clic sur l'invite : `requestFullscreen()` DANS le geste. Sans écran à choisir, l'appel est synchrone ;
       avec un écran à choisir, getScreenDetails() précède (l'activation vit ~5 s). */
    async function onPromptClick(){
      const current=armed;
      if(!current)return;
      const target=resolveTarget(current.objectId);
      if(!target){
        removePrompt(true);
        const reason="La surface demandée n'est plus à l'écran.";
        transition('browser_denied');stats.refused++;
        log('warn','fullscreen.target_missing',{id:current.id,object_id:current.objectId});
        notify({title:'Plein écran impossible',sub:reason,kind:'warn'});
        reportState('refused',{id:current.id,code:PAGE_CODES.TARGET_MISSING,reason});
        return;
      }
      const outcome=await requestOn(target,current.display,{via:'prompt'});
      if(!armed||armed!==current)return;   /* fullscreenchange a déjà tranché (entrée) ou l'armement est parti */
      if(outcome.kind==='entered')return;
      if(outcome.kind==='retry'){
        showPromptError(outcome.message);
        try{current.ui.go.focus({preventScroll:true})}catch(error){log('warn','fullscreen.prompt_focus_failed',{error:messageOf(error)})}
        return;
      }
      /* refus : le navigateur a dit non, avec ses mots */
      const id=current.id;
      removePrompt(true);
      transition('browser_denied');stats.refused++;
      log('warn','fullscreen.denied',{id,error:outcome.message});
      notify({title:'Plein écran refusé par le navigateur',sub:outcome.message,kind:'bad'});
      reportState('refused',{id,code:PAGE_CODES.DENIED,reason:outcome.message});
    }

    /* Un seul endroit appelle `requestFullscreen` : le clic de l'invite ou l'entrée locale (geste réel). */
    async function requestOn(target,display,context){
      let options={navigationUI:'hide'};
      let selection='not_requested';
      const wantsDisplay=display&&display!=='current';
      let askedPermission=false;
      if(wantsDisplay){
        let perm=null;
        try{perm=await (win.navigator&&win.navigator.permissions&&win.navigator.permissions.query({name:'window-management'}))}
        catch(error){perm=null}   /* intentional: the permission name is Chromium-only; absence = ask via getScreenDetails below */
        askedPermission=!perm||perm.state!=='granted';
        const resolved=await resolveDisplay(display);
        selection=resolved.selection;
        if(resolved.screen)options=Object.assign(options,{screen:resolved.screen});
      }
      lastDisplaySelection=selection;
      try{
        await target.requestFullscreen(options);
        return {kind:'entered',selection};
      }catch(error){
        const text=messageOf(error);
        const lacksGesture=error&&error.name==='TypeError'&&/permissions check failed|user gesture|activation/i.test(text);
        if(lacksGesture||(askedPermission&&wantsDisplay)){
          const message=askedPermission&&wantsDisplay&&!lacksGesture
            ?"Autorisation d'écran traitée : cliquez de nouveau pour passer en plein écran."
            :"Le navigateur n'a pas reçu votre clic à temps : cliquez de nouveau.";
          log('warn','fullscreen.needs_gesture',{via:context&&context.via,error:text,selection});
          return {kind:'retry',message,selection};
        }
        return {kind:'denied',message:text,selection};
      }
    }

    /* ---- fullscreenchange : la vérité */
    function isOurs(element){return !!element&&(element.id===SCENE_ROOT_ID||(element.dataset&&element.dataset.objectId!==undefined))}
    function onChange(){
      const fs=doc.fullscreenElement||null;
      if(fs&&(!active||active.el!==fs)){
        if(!isOurs(fs)){log('info','fullscreen.foreign_element',{tag:fs.tagName||''});return}
        enteredEvent(fs);
      }else if(!fs&&active){
        exitedEvent();
      }
    }
    function enteredEvent(element){
      const spec=armed||pendingLocal||{id:null,objectId:element.dataset&&element.dataset.objectId!==undefined?element.dataset.objectId:null,keys:'host'};
      pendingLocal=null;
      const id=spec.id,objectId=spec.objectId;
      const prevFocus=armed&&armed.restoreFocus||(doc.activeElement!==doc.body?doc.activeElement:null);
      removePrompt(false);
      active={el:element,objectId,keys:spec.keys||'host',prevFocus,addedTab:false,keyHandler:null,blurHandler:null,
        displaySelection:lastDisplaySelection};
      element.setAttribute('data-jv-fullscreen','1');
      if(active.keys==='host')bindKeys(element);
      transition('browser_entered');stats.entered++;
      log('info','fullscreen.entered',{id,object_id:objectId,keys:active.keys,display_selection:lastDisplaySelection});
      reportState('entered',{id,object_id:objectId});
    }
    function exitedEvent(){
      const was=active;active=null;
      unbindKeys(was);
      was.el.removeAttribute('data-jv-fullscreen');
      const wasArmed=armed;
      removePrompt(false);
      transition('browser_exited');stats.exited++;
      if(was.prevFocus&&was.prevFocus.isConnected!==false&&typeof was.prevFocus.focus==='function'){
        try{was.prevFocus.focus({preventScroll:true})}catch(error){log('warn','fullscreen.focus_restore_failed',{error:messageOf(error)})}
      }
      log('info','fullscreen.exited',{object_id:was.objectId});
      reportState('exited',{object_id:was.objectId,id:wasArmed&&wasArmed.id||undefined});
    }
    function onError(){
      log('warn','fullscreen.browser_error_event',{});
    }

    /* ---- clavier : lu sur l'hôte, le cadre n'en relaie aucune */
    function bindKeys(element){
      if(!element.hasAttribute('tabindex')){
        active.addedTab=true;
        element.setAttribute('tabindex','-1');
      }
      active.keyHandler=event=>{
        if(event.ctrlKey||event.altKey||event.metaKey)return;
        const action=NAV_KEYS[event.key];
        if(!action)return;
        event.preventDefault();event.stopPropagation();
        stats.keys++;
        for(const listener of Array.from(navListeners)){
          try{listener({action,key:event.key,objectId:active&&active.objectId||null})}
          catch(error){log('error','fullscreen.nav_listener_failed',{error:messageOf(error)})}
        }
      };
      element.addEventListener('keydown',active.keyHandler,true);
      /* Un clic dans le cadre y met le focus et les touches se perdent : on reprend l'hôte. */
      active.blurHandler=()=>{
        setT(()=>{
          const focused=doc.activeElement;
          if(active&&focused&&focused.tagName==='IFRAME'&&active.el.contains(focused))focusHost();
        },0);
      };
      win.addEventListener('blur',active.blurHandler);
      focusHost();
    }
    function focusHost(){
      if(!active)return;
      try{active.el.focus({preventScroll:true})}catch(error){log('warn','fullscreen.focus_failed',{error:messageOf(error)})}
    }
    function unbindKeys(was){
      if(!was)return;
      if(was.keyHandler)was.el.removeEventListener('keydown',was.keyHandler,true);
      if(was.blurHandler)win.removeEventListener('blur',was.blurHandler);
      if(was.addedTab)was.el.removeAttribute('tabindex');
    }

    /* ---- sortie */
    async function exit(){
      if(armed&&!active){cancelArm('Retiré par la commande exit.');return {state:'exited',code:PAGE_CODES.CANCELLED}}
      if(!doc.fullscreenElement)return {state:'exited'};
      try{await doc.exitFullscreen()}
      catch(error){
        const reason=`exitFullscreen() a échoué : ${messageOf(error)}`;
        log('error','fullscreen.exit_failed',{error:messageOf(error)});
        notify({title:'Sortie du plein écran impossible',sub:reason+' Échap quitte toujours.',kind:'bad'});
        return {state:'refused',code:PAGE_CODES.EXIT_FAILED,reason};
      }
      /* `fullscreenchange` a déjà traité la sortie (événement avant résolution) ; sinon on relit. */
      if(doc.fullscreenElement)return {state:'refused',code:PAGE_CODES.EXIT_FAILED,reason:'Le navigateur est resté en plein écran.'};
      return {state:'exited'};
    }

    /* ---- entrée locale : doit être appelée dans un geste ; sinon elle ARME au lieu d'échouer en silence */
    async function enter(spec){
      const wanted=Object.assign({object_id:null,display:'current',keys:'host',arm_s:DEFAULT_ARM_S},spec||{});
      const why=unsupportedReason();
      if(why){
        transition('unsupported');stats.unsupported++;
        log('warn','fullscreen.unsupported',{reason:why});
        notify({title:'Plein écran indisponible',sub:why,kind:'warn'});
        reportState('unsupported',{code:PAGE_CODES.UNSUPPORTED,reason:why});
        return {state:'unsupported',code:PAGE_CODES.UNSUPPORTED,reason:why};
      }
      const target=resolveTarget(wanted.object_id);
      if(!target){
        const reason="La surface demandée n'est pas à l'écran.";
        log('warn','fullscreen.target_missing',{object_id:wanted.object_id});
        return {state:'refused',code:PAGE_CODES.TARGET_MISSING,reason};
      }
      if(doc.fullscreenElement===target)return {state:'entered',object_id:wanted.object_id};
      if(doc.fullscreenElement){
        return {state:'refused',code:PAGE_CODES.OTHER_ENTERED,reason:"Une autre surface est déjà en plein écran : quittez-la d'abord."};
      }
      const activation=win.navigator&&win.navigator.userActivation;
      if(activation&&activation.isActive===false){
        arm(wanted,target,null);
        return {state:'needs_gesture',code:PAGE_CODES.NEEDS_GESTURE,object_id:wanted.object_id};
      }
      pendingLocal={objectId:wanted.object_id,keys:wanted.keys,id:null};
      const outcome=await requestOn(target,wanted.display,{via:'local'});
      if(outcome.kind==='entered')return {state:'entered',object_id:wanted.object_id,display_selection:outcome.selection};
      pendingLocal=null;
      if(outcome.kind==='retry'){arm(wanted,target,null);showPromptError(outcome.message);
        return {state:'needs_gesture',code:PAGE_CODES.NEEDS_GESTURE,reason:outcome.message}}
      transition('browser_denied');stats.refused++;
      notify({title:'Plein écran refusé par le navigateur',sub:outcome.message,kind:'bad'});
      reportState('refused',{code:PAGE_CODES.DENIED,reason:outcome.message});
      return {state:'refused',code:PAGE_CODES.DENIED,reason:outcome.message};
    }
    /* ---- commande de l'agent : un reçu synchrone, jamais d'« entered » sans que le navigateur l'ait constaté */
    async function handle(command){
      stats.commands++;
      if(command.action==='exit'){
        const outcome=await exit();
        return Object.assign({display_selection:lastDisplaySelection},outcome);
      }
      const why=unsupportedReason();
      if(why){
        transition('unsupported');stats.unsupported++;
        log('warn','fullscreen.unsupported',{reason:why,id:command.id&&command.id.slice(0,8)});
        notify({title:'Plein écran indisponible',sub:why,kind:'warn'});
        return {state:'unsupported',code:PAGE_CODES.UNSUPPORTED,reason:why};
      }
      const objectId=command.object_id===undefined?null:command.object_id;
      const target=resolveTarget(objectId);
      if(!target){
        const reason="La surface demandée n'est pas à l'écran.";
        log('warn','fullscreen.target_missing',{object_id:objectId});
        notify({title:'Plein écran impossible',sub:reason,kind:'warn'});
        return {state:'refused',code:PAGE_CODES.TARGET_MISSING,reason,object_id:objectId};
      }
      if(doc.fullscreenElement===target)return {state:'entered',object_id:objectId,display_selection:lastDisplaySelection};
      if(doc.fullscreenElement){
        return {state:'refused',code:PAGE_CODES.OTHER_ENTERED,object_id:objectId,
          reason:"Une autre surface est déjà en plein écran : demandez d'abord la sortie."};
      }
      arm(command,target,command.id?command.id.slice(0,8):null);
      return {state:'needs_gesture',object_id:objectId,display_selection:'not_requested'};
    }

    const api={
      handle,enter,exit,
      onNavigate(listener){navListeners.add(listener);return ()=>navListeners.delete(listener)},
      cancel:()=>cancelArm('Annulé.'),
      state:()=>({state,objectId:active?active.objectId:(armed?armed.objectId:null),
        armed:armed?{id:armed.id,remainingMs:Math.max(0,armed.deadlineAt-now())}:null,
        displaySelection:lastDisplaySelection,supported:unsupportedReason()===null}),
      stats:()=>Object.assign({},stats),
      onChange,onError,
      _prompt:()=>armed&&armed.ui,
    };
    return api;
  }

  /* ---------------------------------------------------------------- canal de commandes (long-poll) */
  function createCommandChannel(deps){
    const stats={polls:0,received:0,answered:0,receiptFailed:0};
    const log=deps.log||(()=>{});
    let visible=true,running=false,failures=0;
    const SHORT=id=>String(id).slice(0,8);
    async function apply(command){
      stats.received++;
      let receipt;
      try{receipt=await deps.controller.handle(command)}
      catch(error){
        log('error','fullscreen.command_failed',{id:SHORT(command.id),error:messageOf(error)});
        receipt={state:'refused',code:PAGE_CODES.PAGE_ERROR,reason:messageOf(error).slice(0,REASON_MAX)};
      }
      const body={state:receipt.state};
      for(const key of ['code','reason','display_selection','object_id'])if(receipt[key]!==undefined&&receipt[key]!==null)body[key]=receipt[key];
      if(body.reason)body.reason=String(body.reason).slice(0,REASON_MAX);
      try{
        const answer=await deps.request(`${ROUTE}/${encodeURIComponent(command.id)}`,
          {method:'POST',body:JSON.stringify(body),timeoutMs:RECEIPT_TIMEOUT_MS});
        if(answer.status!==200){
          const error=answer.body&&answer.body.error||{};
          throw new Error(String(error.message||`HTTP ${answer.status}`)+(error.code?` (${error.code})`:''));
        }
        stats.answered++;
      }catch(error){
        stats.receiptFailed++;
        log('error','fullscreen.receipt_failed',{id:SHORT(command.id),error:messageOf(error)});
      }
      return body.state;
    }
    async function once(){
      stats.polls++;
      const answer=await deps.request(`${ROUTE}?wait_s=${POLL_WAIT_S}`,{timeoutMs:POLL_TIMEOUT_MS,poll:true});
      if(answer.status!==200){
        const error=answer.body&&answer.body.error||{};
        throw new Error(String(error.message||`HTTP ${answer.status}`));
      }
      const command=answer.body&&answer.body.command;
      if(command)await apply(command);
    }
    async function loop(){
      running=true;
      try{
        while(visible){
          try{await once();failures=0}
          catch(error){
            failures++;
            log('warn','fullscreen.command_poll_failed',{error:messageOf(error),failures});
            await deps.sleep(backoffDelay(failures,deps.random));
          }
        }
      }finally{running=false}
    }
    function evaluate(){
      if(!visible||running)return;
      loop().catch(error=>log('error','fullscreen.command_loop_failed',{error:messageOf(error)}));
    }
    return {
      setVisible(value){const next=!!value;if(next===visible)return;visible=next;evaluate()},
      start(){evaluate()},apply,
      state:()=>({visible,running,failures}),stats:()=>Object.assign({},stats),
    };
  }

  const api=Object.freeze({ACTIONS,STATES,EVENTS,TRANSITIONS,DISPLAY_SELECTIONS,PAGE_CODES,NAV_KEYS,ROUTE,STATE_ROUTE,
    POLL_WAIT_S,POLL_TIMEOUT_MS,RECEIPT_TIMEOUT_MS,DEFAULT_ARM_S,STYLE,STYLE_ID,PROMPT_ID,
    nextState,backoffDelay,createFullscreenController,createCommandChannel});
  root.JarvisFullscreenCore=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  /* ---------------------------------------------------------------- installation dans la page */
  function installJarvisFullscreen(){
    if(!document.getElementById(STYLE_ID)){
      const style=document.createElement('style');
      style.id=STYLE_ID;style.textContent=STYLE;
      document.head.appendChild(style);
    }
    async function request(url,options){
      const init=Object.assign({cache:'no-store'},options||{});
      const controller=new AbortController();
      delete init.poll;
      const timer=window.setTimeout(()=>controller.abort(),init.timeoutMs||POLL_TIMEOUT_MS);
      delete init.timeoutMs;
      init.signal=controller.signal;
      if(init.body)init.headers=Object.assign({'Content-Type':'application/json'},init.headers||{});
      try{
        const response=await fetch(url,init);
        const text=await response.text();
        let body=null;
        try{body=text?JSON.parse(text):null}catch(_error){body=null}
        return {status:response.status,body};
      }finally{window.clearTimeout(timer)}
    }
    const log=(level,event,data)=>{
      const line=`[fullscreen] ${event} ${JSON.stringify(data)}`;
      if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line);
    };
    const controller=createFullscreenController({
      document,window,request,log,
      toast:typeof toast==='function'?toast:null,
    });
    document.addEventListener('fullscreenchange',controller.onChange);
    document.addEventListener('fullscreenerror',controller.onError);
    const channel=createCommandChannel({
      controller,request,log,
      sleep:ms=>new Promise(resolve=>window.setTimeout(resolve,ms)),random:Math.random,
    });
    document.addEventListener('visibilitychange',()=>channel.setVisible(document.visibilityState!=='hidden'));
    channel.setVisible(document.visibilityState!=='hidden');
    window.JarvisFullscreen=Object.freeze({
      enter:controller.enter,exit:controller.exit,cancel:controller.cancel,onNavigate:controller.onNavigate,
      state:controller.state,stats:controller.stats,channel:Object.freeze({state:channel.state,stats:channel.stats}),
    });
    channel.start();
  }
  /* Rattrapé ici : la page servie n'a qu'une balise <script> ; une levée emporterait la scène avec elle. */
  try{installJarvisFullscreen()}
  catch(error){console.error('[fullscreen] fullscreen.not_installed '+JSON.stringify({error:String(error&&error.message||error)}))}
})(typeof window!=='undefined'?window:globalThis);
