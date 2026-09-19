/* Bare Hands V1 — canal de commandes du cerveau vers la page (Slice 12).
   Décision 6 : le bouton d'interface **et la voix** activent/désactivent Bare
   Hands.

   Ce module est le dernier tronçon d'un chemin que le constat F1 de la Slice 00
   a établi : parole → cerveau (CLI Claude) → outil MCP → Control Center → page.
   Il ne comprend aucune parole et ne reconnaît aucune intention ; il reçoit un
   **nom de commande** déjà décidé et le remet à un point d'entrée.

   Trois règles le tiennent entier :

   - **Le même point d'entrée que le bouton.** `ENTRY_POINTS` ne nomme que des
     méthodes de `window.JarvisBarehands`, et `activate`/`sleep` sont exactement
     ce que `#barehandsWake` appelle (`setAwake`). Rien n'est réimplanté ici :
     une seconde implantation de « réveiller » diverge le jour où l'une des deux
     change, et personne ne voit laquelle la voix a prise. Effet de bord
     mesurable du choix : le panneau Expérimental se redessine après une
     commande vocale, parce que `setAwake` finit par `refreshPanel()`.
   - **On rapporte ce que la page constate, jamais ce qu'on a demandé.**
     Après l'appel, le cycle de vie est **relu** (`surface.lifecycle()`). Un
     `activate` qui n'aboutit pas à `active` est un refus, pas un succès :
     `setAwake` avale ses erreurs dans `view.error` et ne rejette jamais, donc
     l'état relu est la seule vérité disponible.
   - **Rien ne tourne quand Bare Hands est éteint.** La boucle n'existe que
     pendant que l'interrupteur est vrai *et* que l'onglet est visible. Elle
     n'a pas de minuterie : c'est un long-poll qui se rappelle lui-même, comme
     celui de la scène (`createSceneLoop.poll`). L'interrupteur arrive par
     `/api/status`, le seul battement déjà permanent de la page — la même
     couture que `JarvisScene.gate`.

   Insertion : `control_center.py` / `control_center.html`, APRÈS
   `control_center_barehands.js`, qui pose `window.JarvisBarehands`. Le bloc
   navigateur le lit au chargement et **refuse de s'installer** sans lui : servi
   trop tôt, le canal ne s'installe pas et la console dit pourquoi, à
   l'insertion et non trois clics plus tard. Le refus est **rattrapé ici**
   (`installJarvisBarehandsCommands`) parce que la page servie concatène tous
   ses modules dans une seule balise `<script>` : une levée qui remonterait
   emporterait la scène, la timeline et le Test Lab avec elle. Un test de page
   vérifie l'ordre (constat F3 de la Slice 00). */
(function(root){
  'use strict';

  /* Le vocabulaire, et **le seul endroit** qui sait ce qu'une commande
     déclenche. Le miroir Python (`jarvis/domain/barehands_command.py`) n'en
     tient que les noms : un test de parité compare les deux tables, si bien
     qu'une commande ajoutée d'un côté seulement tombe tout de suite.

     `targets` : les états que le cycle de vie a le droit de montrer **après**
     l'appel. C'est un **ensemble**, pas un état unique, et la QA de la Slice 12
     a payé la différence : `sleep()` ne fait rien hors d'`ACTIVE`, donc
     `deactivate` depuis `off` — l'état de **tout onglet fraîchement ouvert** —
     laissait `off`, ce qui ne valait pas `sleep` et devenait un refus
     `barehands_lifecycle_refused`, dont la phrase accuse la caméra. Personne
     n'avait touché la caméra : la main ne tournait simplement pas. « Ne pilote
     plus » est vrai en `sleep` **et** en `off` ; les deux sont donc des fins
     acceptables, et rien à faire se dit `duplicate`. `error` n'en est pas une :
     là, quelque chose est cassé, et c'est le seul cas où la phrase sur la
     caméra dit la vérité.

     Les parcours (Slices 08 et 09) n'ont pas de `targets` : leur critère de
     succès est une décision produit que personne n'a encore prise, et inventer
     « ouvert » ici serait exactement le faux succès que cette Slice existe pour
     empêcher — d'où `confirmed()` plus bas.

     **Quatre portes de `JarvisBarehands` sont délibérément absentes de cette
     table**, et leur absence est une décision, pas un oubli :
     `enable`/`disable` (l'interrupteur appartient à l'utilisateur ; l'éteindre
     par la voix retirerait au cerveau l'outil qui vient de servir), `settings`
     et `tool`. La QA de la Slice 07 a mesuré que `tool('scissors')` normalise
     vers `pointer`, enregistre, n'affiche rien et **rend un succès** : router
     « prends le surligneur » par cette porte ferait dire à JARVIS que c'est
     fait pendant que la main change d'outil pour un autre. La commande d'outil
     n'entrera dans cette table que quand elle pourra être vérifiée — soit en
     relisant l'outil effectivement appliqué, soit derrière une porte qui
     refuse un nom inconnu. */
  const ENTRY_POINTS=Object.freeze({
    activate:Object.freeze({method:'activate',targets:Object.freeze(['active'])}),
    deactivate:Object.freeze({method:'sleep',targets:Object.freeze(['sleep','off'])}),
    calibrate:Object.freeze({method:'calibrate',targets:null}),
    tutorial:Object.freeze({method:'tutorial',targets:null}),
    exit_overlay:Object.freeze({method:'exitOverlay',targets:null}),
  });
  const COMMANDS=Object.freeze(Object.keys(ENTRY_POINTS));

  /* Codes de refus que la page a le droit d'émettre. Liste fermée, et le
     serveur refuse tout autre code (`barehands_bad_receipt`) : un canal qui
     recopierait n'importe quelle chaîne rendrait la trace aussi fiable que la
     page qui l'a inventée. */
  const FLOW_ABSENT='barehands_flow_absent';
  const FLOW_UNCONFIRMED='barehands_flow_unconfirmed';
  const LIFECYCLE_REFUSED='barehands_lifecycle_refused';
  const COMMAND_UNKNOWN='barehands_command_unknown';
  const PAGE_CODES=Object.freeze([FLOW_ABSENT,FLOW_UNCONFIRMED,LIFECYCLE_REFUSED,COMMAND_UNKNOWN]);

  /* **Un appel qui ne lève pas n'est pas une preuve.** Mesuré ailleurs dans ce
     sous-système (QA de la Slice 07) : `JarvisBarehands.tool('scissors')`
     normalise silencieusement vers `pointer`, enregistre, n'affiche rien et
     rend un succès. Un canal qui lirait « pas d'exception = fait » relaierait
     ce mensonge à la voix.

     D'où la règle, valable pour tout point d'entrée sans état observable : le
     parcours doit **confirmer**, en résolvant `true` ou `{ok:true}`. Tout le
     reste — `undefined`, `null`, `false`, un objet muet — est un refus
     `barehands_flow_unconfirmed`. Les Slices 08 et 09 héritent de ce contrat :
     c'est le prix d'entrée pour être annoncé à l'utilisateur. */
  function confirmed(answer){return answer===true||!!(answer&&answer.ok===true)}

  const ROUTE='/api/barehands/commands';
  /* Même attente que le long-poll de la scène, pour la même raison : sous les
     délais d'inactivité des proxys locaux, et assez long pour qu'une fenêtre
     ouverte soit presque toujours **déjà** en attente quand une commande naît. */
  const POLL_WAIT_S=25;
  const POLL_TIMEOUT_MS=(POLL_WAIT_S+15)*1000;
  /* Le reçu ne doit pas survivre à l'échéance de la commande (3 s côté
     serveur) : au-delà, le serveur a déjà rendu `barehands_no_visible_page` et
     le reçu ne ferait que remplir la trace. */
  const RECEIPT_TIMEOUT_MS=5000;
  const BACKOFF_BASE_MS=1000;
  const BACKOFF_MAX_MS=30000;
  const COMMAND_ID=/^[A-Za-z0-9_-]{32,64}$/;

  function backoffDelay(failures,random){
    const step=Math.min(BACKOFF_MAX_MS,BACKOFF_BASE_MS*Math.pow(2,Math.max(0,failures-1)));
    return Math.round(step*(0.75+0.5*random()));
  }

  /* Une commande reçue est-elle utilisable telle quelle ? Même forme que
     `validRequest` du répondeur de capture : un identifiant hors forme est un
     bug de serveur, pas une commande à tenter. */
  function validCommand(command){
    return !!command&&typeof command==='object'&&typeof command.id==='string'&&COMMAND_ID.test(command.id)
      &&typeof command.name==='string'&&Number.isInteger(command.remaining_ms)&&command.remaining_ms>=0;
  }

  function messageOf(error){return String(error&&error.message||error||'')}

  /* Le canal : une boucle de long-poll, une remise, un reçu.

     `deps` : `request(url,{method,body,timeoutMs})` → `{status,body}` (ne rejette
     que sur une panne réseau) ; `surface()` → l'objet `window.JarvisBarehands`
     ou rien ; `now()` ; `sleep(ms)` ; `random()` ; `log(level,event,data)`. */
  function createCommandChannel(deps){
    const stats={polls:0,received:0,applied:0,duplicate:0,refused:0,failed:0,invalid:0,receiptFailed:0};
    let enabled=false,visible=true,running=false,failures=0,last='';

    const active=()=>enabled&&visible;
    const log=(level,event,data)=>{if(deps.log)deps.log(level,event,data||{})};

    /* Ce que la page fait vraiment d'une commande. Rend le reçu, **toujours** :
       cette fonction ne rejette pas, parce qu'un reçu manquant laisse le
       cerveau attendre son échéance pour apprendre « personne », alors que la
       page savait déjà quoi répondre. */
    async function dispatch(name){
      const surface=deps.surface&&deps.surface();
      const spec=Object.prototype.hasOwnProperty.call(ENTRY_POINTS,name)?ENTRY_POINTS[name]:null;
      const lifecycleOf=()=>{
        try{
          const value=surface&&typeof surface.lifecycle==='function'?surface.lifecycle():null;
          return typeof value==='string'?value:'error';
        }catch(error){
          /* Relire l'état ne doit pas transformer un refus en panne muette :
             on rend `error`, qui est un état légal du contrat. */
          log('warn','barehands.command_lifecycle_unreadable',{error:messageOf(error)});
          return 'error';
        }
      };
      if(!spec)return {outcome:'refused',lifecycle:lifecycleOf(),code:COMMAND_UNKNOWN,
        reason:`la page ne connaît pas la commande ${name}`};
      if(!surface||typeof surface[spec.method]!=='function'){
        /* Les parcours de calibration et de tutoriel (Slices 08 et 09)
           n'existent pas encore : leur point d'entrée est absent, et c'est
           **exactement** ce que le cerveau doit entendre. Le jour où la Slice
           08 pose `JarvisBarehands.calibrate`, ce transport la trouve sans
           qu'une ligne change ici. */
        return {outcome:'refused',lifecycle:lifecycleOf(),code:FLOW_ABSENT,
          reason:`JarvisBarehands.${spec.method} n'existe pas dans cette version`};
      }
      const before=lifecycleOf();
      let answer;
      try{
        answer=await surface[spec.method]();
      }catch(error){
        return {outcome:'refused',lifecycle:lifecycleOf(),code:LIFECYCLE_REFUSED,reason:messageOf(error)};
      }
      const after=lifecycleOf();
      if(!spec.targets){
        /* Pas d'état observable à relire : la seule preuve possible est une
           confirmation explicite du parcours. Sans elle, refus. */
        if(!confirmed(answer))
          return {outcome:'refused',lifecycle:after,code:FLOW_UNCONFIRMED,
            reason:`JarvisBarehands.${spec.method} n'a pas confirmé le démarrage`};
        return {outcome:'applied',lifecycle:after,code:null,reason:null};
      }
      if(spec.targets.indexOf(after)<0)
        return {outcome:'refused',lifecycle:after,code:LIFECYCLE_REFUSED,
          reason:`état ${after} au lieu de ${spec.targets.join(' ou ')}`};
      /* L'état est acceptable. Reste à dire si quelque chose a **changé** :
         c'est la seule différence entre « c'est fait » et « rien à faire », et
         l'utilisateur n'entend pas la même phrase. */
      return {outcome:before===after?'duplicate':'applied',lifecycle:after,code:null,reason:null};
    }

    async function sendReceipt(id,receipt){
      const answer=await deps.request(`${ROUTE}/${encodeURIComponent(id)}`,
        {method:'POST',body:JSON.stringify(receipt),timeoutMs:RECEIPT_TIMEOUT_MS});
      if(answer.status!==200){
        stats.receiptFailed++;
        const error=answer.body&&answer.body.error||{};
        /* Le reçu refusé n'est pas rattrapable (l'identifiant est à usage
           unique) : il est journalisé avec le code du serveur, et la boucle
           continue. Le cerveau, lui, apprendra l'échéance par son propre appel. */
        log('warn','barehands.receipt_refused',{command:id.slice(0,8),status:answer.status,
          code:String(error.code||''),message:String(error.message||'')});
      }
    }

    async function apply(command){
      if(!validCommand(command)){stats.invalid++;log('warn','barehands.command_invalid',{});return 'invalid'}
      const short=command.id.slice(0,8);
      stats.received++;
      log('info','barehands.command_received',{command:command.name,id:short,remaining_ms:command.remaining_ms});
      const started=deps.now();
      let receipt;
      try{
        receipt=await dispatch(command.name);
      }catch(error){
        /* `dispatch` est écrit pour ne pas rejeter ; s'il rejetait quand même,
           le cerveau doit l'apprendre comme un refus décrit, pas comme un
           silence de trois secondes. */
        stats.failed++;
        receipt={outcome:'refused',lifecycle:'error',code:LIFECYCLE_REFUSED,reason:messageOf(error)};
      }
      stats[receipt.outcome==='refused'?'refused':receipt.outcome]++;
      last=`${command.name}:${receipt.outcome}`;
      log(receipt.outcome==='refused'?'warn':'info',
        receipt.outcome==='refused'?'barehands.command_refused':'barehands.command_applied',
        {command:command.name,id:short,outcome:receipt.outcome,lifecycle:receipt.lifecycle,
          code:receipt.code||'',ms:deps.now()-started});
      try{
        await sendReceipt(command.id,receipt);
      }catch(error){
        stats.receiptFailed++;
        log('error','barehands.receipt_failed',{command:command.name,id:short,error:messageOf(error)});
      }
      return receipt.outcome;
    }

    async function once(){
      stats.polls++;
      const answer=await deps.request(`${ROUTE}?wait_s=${POLL_WAIT_S}`,{timeoutMs:POLL_TIMEOUT_MS});
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
        while(active()){
          try{
            await once();
            failures=0;
          }catch(error){
            failures++;
            log('warn','barehands.command_poll_failed',{error:messageOf(error),failures});
            const delay=backoffDelay(failures,deps.random||Math.random);
            await deps.sleep(delay);
          }
        }
      }finally{
        /* Relâché quoi qu'il arrive : sans ça, un `setEnabled(true)` après une
           sortie par exception ne relancerait jamais la boucle, et Bare Hands
           serait allumé avec un canal muet — la panne exacte qu'aucun écran ne
           montre. */
        running=false;
      }
    }

    /* **Une seule boucle, et une seule condition d'arrêt : la porte elle-même.**

       Une première version comptait les générations pour faire sortir la
       boucle à la fermeture. C'était à la fois redondant — `while(active())`
       suffit — et faux : fermer puis rouvrir la porte pendant que la boucle
       est garée sur un long-poll incrémentait deux fois le compteur, si bien
       que la boucle sortait à sa reprise **alors que la porte était rouverte**,
       et que `running` valait encore vrai au moment de rouvrir, donc personne
       ne la relançait. Bare Hands allumé, canal muet, rien à l'écran pour le
       dire : exactement la panne que cette Slice doit rendre impossible.

       `running` seul empêche deux boucles ; `active()` seul les arrête. Une
       boucle garée sort au plus tard à la fin de son long-poll (25 s côté
       serveur), ce qui est la même latence qu'un onglet qui se recharge. */
    function evaluate(){
      if(!active()||running)return;
      /* Volontairement non attendu : la boucle vit aussi longtemps que la
         porte est ouverte, et `evaluate` est appelé depuis `/api/status`. */
      loop().catch(error=>log('error','barehands.command_loop_failed',{error:messageOf(error)}));
    }

    return {
      setEnabled(value){const next=!!value;if(next===enabled)return;enabled=next;evaluate()},
      setVisible(value){const next=!!value;if(next===visible)return;visible=next;evaluate()},
      /* Exposés pour les tests et pour `JarvisBarehands.adapters` : ce que le
         canal a vraiment fait, jamais ce qu'on lui a demandé. */
      apply,dispatch,
      state(){return {enabled,visible,running,failures,last}},
      stats(){return {...stats}},
    };
  }

  const api=Object.freeze({ENTRY_POINTS,COMMANDS,PAGE_CODES,confirmed,ROUTE,POLL_WAIT_S,POLL_TIMEOUT_MS,
    RECEIPT_TIMEOUT_MS,BACKOFF_BASE_MS,BACKOFF_MAX_MS,backoffDelay,validCommand,createCommandChannel});
  root.JarvisBarehandsCommands=api;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=api;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  function installJarvisBarehandsCommands(){
    if(!window.JarvisBarehands)
      throw new Error('JarvisBarehandsCommands : control_center_barehands.js doit être inséré avant ce module');

    async function request(url,options){
      const init=Object.assign({cache:'no-store'},options||{});
      const controller=new AbortController();
      const deadline=window.setTimeout(()=>controller.abort(),init.timeoutMs||POLL_TIMEOUT_MS);
      delete init.timeoutMs;
      init.signal=controller.signal;
      if(init.body)init.headers=Object.assign({'Content-Type':'application/json'},init.headers||{});
      try{
        const response=await fetch(url,init);
        const text=await response.text();
        let body=null;
        try{body=text?JSON.parse(text):null}catch(_error){body=null}
        return {status:response.status,body};
      }finally{
        window.clearTimeout(deadline);
      }
    }

    const channel=createCommandChannel({
      request,
      surface:()=>window.JarvisBarehands,
      now:()=>Date.now(),
      sleep:ms=>new Promise(resolve=>window.setTimeout(resolve,ms)),
      random:Math.random,
      log:(level,event,data)=>{
        const line=`[barehands] ${event} ${JSON.stringify(data)}`;
        if(level==='error')console.error(line);
        else if(level==='warn')console.warn(line);
        else console.info(line);
      },
    });
    document.addEventListener('visibilitychange',()=>channel.setVisible(document.visibilityState!=='hidden'));
    channel.setVisible(document.visibilityState!=='hidden');
    /* L'interrupteur arrive par `/api/status`, appelé par `refreshStatus` de
       la page : aucune minuterie de plus, et le canal suit l'interrupteur à la
       seconde, comme le rendu de la scène. */
    window.JarvisBarehandsCommandChannel=Object.freeze({
      gate(barehands){channel.setEnabled(!!(barehands&&barehands.enabled===true))},
      /* Statut perdu : on ne **suppose pas** que Bare Hands est resté allumé.
         Fermer le canal est le choix sûr ; il rouvre au premier statut lu. */
      statusLost(){channel.setEnabled(false)},
      state:channel.state,stats:channel.stats,
    });
  }

  /* **La levée reste, mais elle ne sort pas d'ici.** La page servie n'a qu'**une
     seule** balise `<script>` : les cinq modules Bare Hands, la scène, la
     timeline, le Test Lab et ~2500 lignes de logique de page y sont concaténés.
     Une levée non rattrapée au chargement d'un module y avorte donc tout ce qui
     suit — la QA de la Slice 12 l'a relevé — alors que sous node, où chaque
     module est un `require()` séparé, elle ne tuait que le module. L'intention
     (casser à l'insertion, pas trois clics plus tard) est juste ; son rayon ne
     l'était pas. Rattrapée ici, la panne garde sa portée : ce canal ne
     s'installe pas, le reste de la page vit, et la console porte la cause. */
  try{
    installJarvisBarehandsCommands();
  }catch(error){
    console.error('[barehands] barehands.command_channel_not_installed '
      +JSON.stringify({error:String(error&&error.message||error)}));
  }
})(typeof window!=='undefined'?window:globalThis);
