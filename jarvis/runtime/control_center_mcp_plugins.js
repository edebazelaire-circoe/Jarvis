/* Plugins MCP externes du Control Center (generic-mcp-plugin-runtime, Slice 06).

   Contrat : `docs/mcp/plugins.md` §2 (états), §3 (authentification), §8
   (codes), §9 (écran) et `docs/mcp/tool-contract.md` §8 (routes). Onglet
   « Plugins externes » du dialogue MCP `#mcpInspector`, à côté de
   « Exposition interne » (l'inspecteur, inchangé). Deux parties :

   - `JarvisMcpPluginsCore`, logique pure exécutée telle quelle par les tests
     node : vocabulaire des états, client HTTP des plugins, cartes, vue
     « Gérer », formulaires, erreurs codées, attente d'une autorisation ;
   - un bloc navigateur qui branche l'onglet dans le dialogue.

   QUATRE RÈGLES TIENNENT CE FICHIER.

   1. SEUL MODULE QUI ÉCRIT. Toutes les écritures sous `/api/mcp` passent par
      `createClient` d'ici, qui refuse toute adresse hors de
      `/api/mcp/plugins`. Les outils d'un plugin se lisent par le client EN
      LECTURE SEULE de l'inspecteur et se rendent par son rendu de détail
      (`JarvisMcpInspectorCore.toolRowsHtml`) : il n'y a pas de second
      afficheur d'outils, et aucun outil n'est exécuté d'ici.
   2. UN SECRET NE REVIENT JAMAIS. Le jeton ou la clé saisis vont d'un champ
      mot de passe au corps d'un seul `PUT …/credential`, puis le champ est
      vidé ; ils ne sont gardés dans aucun état, ne sont jamais rendus, jamais
      journalisés. Core ne les renvoie pas non plus.
   3. AUCUN NOM ÉCRIT EN DUR. Ni outil, ni serveur, ni fournisseur : l'écran
      affiche ce que Core rend.
   4. CE QUI ATTEND SE VOIT. Chaque action montre ce qu'elle fait, depuis
      combien de temps, et a une échéance ; une autorisation OAuth est
      attendue 5 min au plus, puis l'écran le dit et propose de recommencer.
      Chaque refus s'affiche par son code stable, traduit en français. */

const JarvisMcpPluginsCore=(function(){
  'use strict';

  const ROUTE='/api/mcp/plugins';
  const DEADLINE_MS=15000;
  /* Connexion (≤ 20 s côté Core), déconnexion (arrêt + révocation), suppression :
     le relais attend 35 s, l'écran un peu plus. */
  const LONG_DEADLINE_MS=45000;
  const POLL_MS=2000;
  const POLL_MAX_MS=300000;
  const PLUGIN_ID=/^[a-z0-9][a-z0-9-]{0,31}$/;
  const ACTIONS=Object.freeze(['connect','disconnect','refresh','credential']);
  const LONG_ACTIONS=new Set(['connect','disconnect','refresh','remove']);

  /* ----------------------------------------------------------- vocabulaire
     Miroir des états de `plugins.md` §2.1. Une valeur inconnue s'affiche
     telle quelle, jamais maquillée en une valeur connue. */
  const CONNECTION=Object.freeze({
    connected:{label:'Connecté',tone:'ok'},
    connecting:{label:'Connexion…',tone:'on'},
    disconnected:{label:'Déconnecté',tone:''},
    error:{label:'En erreur',tone:'bad'},
  });
  const AUTH=Object.freeze({
    unknown:{label:'Accès non vérifié',tone:''},
    not_required:{label:'Sans authentification',tone:''},
    required:{label:'Authentification requise',tone:'warn'},
    authorizing:{label:'Autorisation en cours',tone:'on'},
    authorized:{label:'Autorisé',tone:'ok'},
    expired:{label:'Autorisation expirée',tone:'warn'},
    failed:{label:'Accès refusé',tone:'bad'},
  });
  const STRATEGY=Object.freeze({none:'aucune',oauth:'OAuth',bearer:'jeton Bearer',header:'en-tête personnalisé'});

  /* Codes stables (`plugins.md` §8.2, relais `mcp_plugin_routes.py`, client).
     Titre court (carte, toast) + recours. */
  const ERRORS=Object.freeze({
    core_unreachable:{title:'Cœur de JARVIS injoignable',hint:'Le Control Center ne joint pas Core. Vérifiez qu’il tourne, puis réessayez. L’onglet Exposition interne reste utilisable.'},
    core_unconfigured:{title:'Core non configuré',hint:'Ce Control Center a démarré sans connaître Core : les plugins ne sont pas gérables d’ici.'},
    core_timeout:{title:'Core n’a pas répondu à temps',hint:'L’issue de l’action est inconnue : la liste est relue. Réessayez si rien n’a changé.'},
    forbidden_origin:{title:'Requête refusée par la garde locale',hint:'Seule la page locale du Control Center peut gérer les plugins.'},
    forbidden_route:{title:'Adresse refusée',hint:'Cet écran ne parle qu’aux routes des plugins.'},
    method_not_allowed:{title:'Méthode refusée',hint:'Cette route n’accepte pas cette action.'},
    not_found:{title:'Route inconnue',hint:'Le Control Center ne connaît pas cette route de plugin.'},
    mcp_plugin_unknown:{title:'Plugin inconnu',hint:'Il a peut-être été supprimé ailleurs : la liste est relue.'},
    mcp_plugin_duplicate:{title:'Plugin déjà ajouté',hint:'Cette adresse est déjà dans la liste : ouvrez-le avec « Gérer ».'},
    mcp_plugin_invalid:{title:'Valeur refusée',hint:'Un champ est invalide : nom trop long, en-tête interdit, valeur vide, trop longue ou sur plusieurs lignes.'},
    mcp_plugin_store_unreadable:{title:'Registre des plugins illisible',hint:'Une ligne du registre est endommagée. Lisez mcp.plugin.store_failed dans runtime/trace.jsonl.'},
    mcp_plugin_store_failed:{title:'Registre des plugins indisponible',hint:'SQLite a refusé l’opération. Lisez la trace de Core, puis réessayez.'},
    mcp_plugin_internal_error:{title:'Erreur interne de JARVIS',hint:'La connexion a échoué sur un défaut local, pas sur le serveur distant. Lisez mcp.plugin.owner_crashed dans la trace, puis réessayez.'},
    mcp_endpoint_invalid:{title:'Adresse invalide',hint:'Donnez une URL https complète, sans identifiants ni fragment, par exemple https://exemple.com/mcp.'},
    mcp_endpoint_forbidden:{title:'Adresse interdite',hint:'Elle vise le réseau local ou une adresse privée : JARVIS ne s’y connecte pas.'},
    mcp_vault_unavailable:{title:'Coffre de secrets indisponible',hint:'Ce poste n’a pas de coffre local : ni jeton ni autorisation OAuth ne peuvent y être conservés.'},
    mcp_connector_unavailable:{title:'Connexion aux plugins indisponible',hint:'Core a démarré sans connecteur MCP distant. Redémarrez Core.'},
    mcp_plugin_disabled:{title:'Plugin désactivé',hint:'Activez-le avant de le connecter.'},
    mcp_plugin_disconnected:{title:'Connexion fermée',hint:'La connexion a été remplacée ou fermée : reconnectez le plugin.'},
    mcp_plugin_reauthorization_required:{title:'Nouvelle autorisation nécessaire',hint:'Le serveur refuse l’accès actuel. Reconnectez-le ; s’il ne propose pas OAuth, saisissez un jeton ou une clé.'},
    mcp_oauth_state_invalid:{title:'Retour d’autorisation inconnu ou expiré',hint:'Relancez la connexion : chaque autorisation ne sert qu’une fois et expire après 5 min.'},
    mcp_oauth_issuer_mismatch:{title:'Serveur d’autorisation inattendu',hint:'Le code reçu n’a pas été utilisé. Vérifiez l’adresse du plugin.'},
    mcp_oauth_denied:{title:'Autorisation refusée',hint:'Elle a été refusée sur la page du service. Reconnectez si c’était une erreur.'},
    mcp_oauth_timeout:{title:'Autorisation non reçue',hint:'Le service n’a rien renvoyé en 5 min. Relancez l’autorisation.'},
    mcp_transport_unsupported:{title:'Transport non pris en charge',hint:'Ce serveur ne parle pas MCP en Streamable HTTP ; l’ancien SSE n’est pas pris en charge.'},
    mcp_remote_unreachable:{title:'Serveur injoignable',hint:'Vérifiez l’adresse et le réseau. JARVIS réessaie seul tant que le plugin est activé.'},
    mcp_remote_tls:{title:'Certificat refusé',hint:'Le certificat TLS du serveur n’est pas valide.'},
    mcp_remote_protocol:{title:'Réponse MCP illisible',hint:'Le serveur répond, mais pas en MCP valide.'},
    mcp_response_too_large:{title:'Réponse trop volumineuse',hint:'Le serveur a dépassé la taille de réponse permise.'},
    mcp_remote_timeout:{title:'Le serveur ne répond pas',hint:'Il n’a pas répondu à temps. Réessayez.'},
    oauth_timeout:{title:'Autorisation non reçue',hint:'Aucun retour du service après 5 min. Relancez la connexion.'},
    timeout:{title:'Pas de réponse',hint:'Le Control Center n’a pas répondu à temps. Réessayez ; vérifiez qu’il tourne si cela persiste.'},
    network:{title:'Control Center injoignable',hint:'La requête n’a pas abouti. Vérifiez que le Control Center tourne, puis réessayez.'},
    bad_response:{title:'Réponse illisible',hint:'La réponse n’est pas le JSON attendu. Réessayez ; lisez la trace si cela persiste.'},
    http_error:{title:'Réponse inattendue',hint:'Core a répondu sans code d’erreur lisible. Lisez la trace.'},
  });
  /* Codes pour lesquels la saisie manuelle d'un jeton est la suite logique. */
  const AUTH_CODES=new Set(['mcp_plugin_reauthorization_required','mcp_oauth_denied','mcp_oauth_issuer_mismatch']);

  /* ------------------------------------------------------------- outillage */
  function esc(value){
    return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function plural(n,one,many){return `${n} ${n===1?one:many}`}
  function formatSeconds(ms){return (Math.max(0,ms)/1000).toFixed(1).replace('.',',')+' s'}
  /* « 1 min 05 s » pour l'attente d'une autorisation, bornée à 5 min. */
  function formatClock(ms){
    const s=Math.max(0,Math.floor(ms/1000)),m=Math.floor(s/60),r=s%60;
    return m?`${m} min ${String(r).padStart(2,'0')} s`:`${r} s`;
  }
  function hostOf(plugin){
    const origin=String((plugin&&(plugin.endpoint_origin||plugin.endpoint))||'');
    const m=/^[a-z][a-z0-9+.-]*:\/\/(\[[^\]]+\]|[^/:?#]+)(?::(\d+))?/i.exec(origin);
    return m?(m[1]+(m[2]?`:${m[2]}`:'')):origin;
  }
  function initialOf(plugin){
    const text=String((plugin&&plugin.display_name)||hostOf(plugin)||'?');
    const m=/[\p{L}\p{N}]/u.exec(text);
    return (m?m[0]:'?').toUpperCase();
  }
  function iconUrlOf(plugin){
    const url=plugin&&plugin.icon_url;
    return typeof url==='string'&&/^https:\/\/[^\s"'<>]+$/i.test(url)&&url.length<=512?url:null;
  }
  function chip(label,tone,title){
    return `<span class="chip${tone?' '+tone:''}"${title?` title="${esc(title)}"`:''}>${esc(label)}</span>`;
  }

  /* ------------------------------------------------------------- client HTTP
     Seules les routes des plugins : une adresse ou une méthode hors du
     contrat est refusée AVANT le réseau. Chaque requête a un délai ; les
     deux formes d'erreur de l'API (`{error:{code,message}}` de Core et du
     relais, `{ok:false,code,error}` de la garde locale) deviennent une erreur
     qui garde son code et son statut. */
  function apiError(code,status,message){
    const error=new Error(message||code);
    error.code=code;error.status=status;
    return error;
  }
  function pluginPath(id,action){
    if(typeof id!=='string'||!PLUGIN_ID.test(id))throw apiError('forbidden_route',0,'identifiant de plugin invalide');
    if(action===undefined)return `${ROUTE}/${id}`;
    if(!ACTIONS.includes(action))throw apiError('forbidden_route',0,`action inconnue : ${action}`);
    return `${ROUTE}/${id}/${action}`;
  }
  function pluginRoute(path){
    if(path===ROUTE)return true;
    const m=/^\/api\/mcp\/plugins\/([^/?#]+)(?:\/([a-z]+))?$/.exec(String(path));
    return !!m&&PLUGIN_ID.test(m[1])&&(m[2]===undefined||ACTIONS.includes(m[2]));
  }
  function errorOf(body,response,text){
    const envelope=body&&typeof body.error==='object'&&body.error?body.error:null;
    const code=(envelope&&envelope.code)||(body&&typeof body.code==='string'&&body.code)
      ||(response.ok?'bad_response':(body?'http_error':`http_${response.status}`));
    const message=(envelope&&envelope.message)||(body&&typeof body.error==='string'&&body.error)
      ||String(text||'').slice(0,200)||`HTTP ${response.status}`;
    return apiError(code,response.status,message);
  }
  function createClient({fetchImpl,deadlineMs=DEADLINE_MS,longDeadlineMs=LONG_DEADLINE_MS,
    setTimer=setTimeout,clearTimer=clearTimeout}={}){
    async function request(method,path,body,{long=false}={}){
      if(!pluginRoute(path))throw apiError('forbidden_route',0,`adresse hors des plugins MCP : ${path}`);
      if(!['GET','POST','PATCH','PUT','DELETE'].includes(method))throw apiError('forbidden_route',0,`méthode refusée : ${method}`);
      const limit=long?longDeadlineMs:deadlineMs;
      const controller=typeof AbortController==='function'?new AbortController():null;
      let timedOut=false;
      const timer=setTimer(()=>{timedOut=true;if(controller)controller.abort()},limit);
      const init={method,headers:{Accept:'application/json'},signal:controller?controller.signal:undefined};
      if(body!==undefined){init.headers['Content-Type']='application/json';init.body=JSON.stringify(body)}
      try{
        let response;
        try{response=await fetchImpl(path,init)}
        catch(error){
          if(timedOut)throw apiError('timeout',0,`aucune réponse en ${Math.round(limit/1000)} s`);
          throw apiError('network',0,(error&&error.message)||'requête interrompue');
        }
        let text='';
        try{text=await response.text()}catch(error){
          if(timedOut)throw apiError('timeout',0,`aucune réponse en ${Math.round(limit/1000)} s`);
          throw apiError('network',response.status,(error&&error.message)||'réponse interrompue');
        }
        let parsed=null;
        try{parsed=text?JSON.parse(text):null}catch(_){parsed=null}
        if(!response.ok||!parsed||typeof parsed!=='object'||parsed.ok===false)throw errorOf(parsed,response,text);
        return {status:response.status,body:parsed};
      }finally{clearTimer(timer)}
    }
    /* Toutes asynchrones : un identifiant refusé devient une promesse rejetée, jamais une exception levée. */
    return {
      list:async()=>(await request('GET',ROUTE)).body,
      create:async(endpoint,displayName)=>(await request('POST',ROUTE,displayName?{endpoint,display_name:displayName}:{endpoint})).body,
      update:async(id,patch)=>(await request('PATCH',pluginPath(id),patch)).body,
      connect:async id=>request('POST',pluginPath(id,'connect'),{},{long:true}),
      disconnect:async id=>(await request('POST',pluginPath(id,'disconnect'),undefined,{long:true})).body,
      refresh:async id=>(await request('POST',pluginPath(id,'refresh'),undefined,{long:true})).body,
      remove:async id=>(await request('DELETE',pluginPath(id),undefined,{long:true})).body,
      /* Le secret ne fait que traverser : il n'est ni gardé ni rendu. */
      setCredential:async(id,{strategy,headerName,value})=>(await request('PUT',pluginPath(id,'credential'),
        strategy==='header'?{strategy,header_name:headerName,value}:{strategy,value})).body,
    };
  }

  /* Vue d'une erreur : titre humain, message du serveur, code et statut, recours. */
  function errorView(error){
    const code=(error&&error.code)||'network';
    const known=ERRORS[code]||{title:'Échec de l’opération',hint:'Réessayez ; lisez la trace du Control Center et de Core si cela persiste.'};
    return {title:known.title,hint:known.hint,code,status:(error&&error.status)||0,
      message:(error&&error.message)?String(error.message):'échec sans message'};
  }
  function errorHtml(error,{id='mcpp-retry',act='retry',lead='',retryLabel='Réessayer',dataId=''}={}){
    const view=errorView(error);
    const where=[view.code,view.status?`HTTP ${view.status}`:''].filter(Boolean).join(' · ');
    /* Le message du serveur, sauf s'il ne fait que répéter le titre. */
    const message=view.message&&view.message!==view.title?`${esc(view.message)} `:'';
    return `<div class="notice bad mcpp-error" role="alert"><strong>${esc(lead)}${esc(view.title)}</strong>`
      +`<div class="mcpp-emsg">${message}<code>${esc(where)}</code></div>`
      +`<div class="hint">${esc(view.hint)}</div>`
      +(act?`<button type="button" class="action small" id="${esc(id)}" data-act="${esc(act)}"${dataId?` data-id="${esc(dataId)}"`:''}>${esc(retryLabel)}</button>`:'')
      +'</div>';
  }
  /* La dernière erreur d'un plugin (code stable seulement, jamais un texte distant). */
  function lastErrorOf(plugin){
    const code=plugin&&plugin.last_error_code;
    if(!code)return null;
    const known=ERRORS[code];
    return {code,title:known?known.title:code,hint:known?known.hint:''};
  }

  /* ------------------------------------------------------------ états d'un plugin */
  function connectionOf(plugin){return CONNECTION[plugin.connection_status]||{label:String(plugin.connection_status||'inconnu'),tone:'warn'}}
  function authOf(plugin){return AUTH[plugin.auth_status]||{label:String(plugin.auth_status||'inconnu'),tone:'warn'}}
  function toolCountOf(plugin){return Array.isArray(plugin.tools)?plugin.tools.length:0}
  /* L'action principale proposée sur la carte, ou `null` quand tout va bien. */
  function primaryAction(plugin){
    if(!plugin.enabled)return null;
    if(plugin.connection_status==='connected')return null;
    /* Core attend encore un retour que cet écran n'attend plus (délai passé,
       page rechargée) : relancer ouvre une autorisation neuve. */
    if(plugin.auth_status==='authorizing'||plugin.last_error_code==='mcp_oauth_timeout')
      return {act:'connect',label:'Relancer l’autorisation'};
    if(plugin.connection_status==='connecting')return null;
    const again=plugin.last_discovered_at||plugin.auth_status==='expired'||plugin.connection_status==='error';
    return {act:'connect',label:again?'Reconnecter':'Connecter'};
  }
  /* Faut-il proposer la saisie d'un jeton ? Le serveur veut une authentification
     que la voie OAuth n'a pas su fournir (`plugins.md` §3.1, repli manuel). */
  function wantsManualCredential(plugin,error){
    /* Un consentement resté sans réponse n'est pas un refus : on relance l'autorisation, pas un jeton. */
    if((error&&error.code==='mcp_oauth_timeout')||(plugin&&plugin.last_error_code==='mcp_oauth_timeout'))return false;
    if(error&&AUTH_CODES.has(error.code))return true;
    return !!plugin&&(plugin.auth_status==='required'||(plugin.auth_status==='failed'&&plugin.auth_strategy!=='oauth'));
  }
  /* Attente d'une autorisation : que faire du plugin relu ? */
  function pollDecision(plugin,startedAt,now){
    if(!plugin)return 'gone';
    if(plugin.connection_status==='connected')return 'done';
    if(plugin.auth_status==='authorizing'||plugin.connection_status==='connecting')
      return now-startedAt>=POLL_MAX_MS?'timeout':'continue';
    return 'failed';
  }
  function summaryOf(list){
    const plugins=(list&&list.plugins)||[];
    const connected=plugins.filter(p=>p.connection_status==='connected').length;
    const enabled=plugins.filter(p=>p.enabled).length;
    return {total:plugins.length,connected,enabled};
  }
  function statusView({loading,error,list,elapsedMs=0}){
    if(loading)return {tone:'busy',label:'Lecture des plugins…',detail:'',clock:formatSeconds(elapsedMs)};
    if(error&&!list){const v=errorView(error);return {tone:'bad',label:v.title,detail:v.code,clock:''}}
    if(!list)return {tone:'muted',label:'En attente',detail:'',clock:''};
    const s=summaryOf(list);
    const detail=s.total?`${plural(s.total,'plugin','plugins')} · ${plural(s.connected,'connecté','connectés')}`:'aucun plugin';
    if(error)return {tone:'bad',label:'Actualisation impossible',detail:`${detail} (dernière lecture)`,clock:''};
    return {tone:'live',label:'Plugins lus',detail,clock:''};
  }

  /* ------------------------------------------------------------ rendu
     Chaque bouton porte un identifiant STABLE dérivé du plugin : le bloc
     navigateur y ramène le focus après un re-rendu. */
  function avatarHtml(plugin,{failed=false,size=''}={}){
    const url=failed?null:iconUrlOf(plugin);
    return `<span class="mcpp-avatar${size?' '+size:''}" aria-hidden="true"><span class="mcpp-letter">${esc(initialOf(plugin))}</span>`
      +(url?`<img src="${esc(url)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" data-icon-for="${esc(plugin.plugin_id)}">`:'')
      +'</span>';
  }
  function badgesHtml(plugin){
    const conn=connectionOf(plugin),auth=authOf(plugin);
    return `<span class="mcpp-badges">${chip(conn.label,conn.tone,'état de la connexion')}${chip(auth.label,auth.tone,'état de l’accès')}</span>`;
  }
  function switchHtml(plugin,{busy=false,idPrefix='mcpp-sw'}={}){
    const on=!!plugin.enabled,name=plugin.display_name||plugin.plugin_id;
    return `<button type="button" role="switch" class="mcpp-switch" id="${idPrefix}-${esc(plugin.plugin_id)}" data-act="toggle" data-id="${esc(plugin.plugin_id)}" `
      +`aria-checked="${on}" aria-label="${esc(`Plugin ${name} activé`)}"${busy?' disabled':''}>`
      +`<span class="mcpp-track" aria-hidden="true"><span class="mcpp-knob"></span></span><span class="mcpp-swl" aria-hidden="true">${on?'Activé':'Désactivé'}</span></button>`;
  }
  /* Ce qui se passe maintenant sur ce plugin : une action en cours, une
     autorisation attendue. Les secondes vivent hors des régions annoncées. */
  function activityHtml(plugin,{busy=null,authorizing=null,now=0}={}){
    if(busy){
      return `<p class="mcpp-activity" data-id="${esc(plugin.plugin_id)}"><span class="mcpp-spin" aria-hidden="true"></span>`
        +`<span role="status">${esc(busy.label)}</span> <span class="mcpp-clock" data-since="${busy.started}" aria-hidden="true">${esc(formatSeconds(now-busy.started))}</span></p>`;
    }
    if(authorizing){
      const left=Math.max(0,POLL_MAX_MS-(now-authorizing.started));
      return `<div class="mcpp-activity mcpp-authwait" data-id="${esc(plugin.plugin_id)}"><span class="mcpp-spin" aria-hidden="true"></span>`
        +`<span role="status">Autorisation attendue dans l’onglet du service</span> <span class="mcpp-clock" data-since="${authorizing.started}" data-left="1" aria-hidden="true">${esc(formatClock(now-authorizing.started))} · reste ${esc(formatClock(left))}</span>`
        +(authorizing.url?` <a class="mcpp-link" id="mcpp-authlink-${esc(plugin.plugin_id)}" href="${esc(authorizing.url)}" target="_blank" rel="noopener noreferrer">Ouvrir la page d’autorisation</a>`:'')
        +` <button type="button" class="action small" id="mcpp-authstop-${esc(plugin.plugin_id)}" data-act="stopwait" data-id="${esc(plugin.plugin_id)}">Ne plus attendre</button></div>`;
    }
    return '';
  }
  function cardHtml(plugin,{busy=null,authorizing=null,now=0,iconFailed=false}={}){
    const id=plugin.plugin_id,name=plugin.display_name||id;
    const tools=toolCountOf(plugin);
    const error=lastErrorOf(plugin);
    const primary=busy||authorizing?null:primaryAction(plugin);
    const state=plugin.enabled?plugin.connection_status:'off';
    return `<li class="mcpp-card" data-id="${esc(id)}" data-state="${esc(state)}">`
      +`<div class="mcpp-top">${avatarHtml(plugin,{failed:iconFailed})}`
      +`<div class="mcpp-ident"><h3 class="mcpp-name" id="mcpp-name-${esc(id)}">${esc(name)}</h3><span class="mcpp-host">${esc(hostOf(plugin))}</span></div>`
      +`${switchHtml(plugin,{busy:!!busy})}</div>`
      +badgesHtml(plugin)
      +(error&&!busy&&!authorizing?`<p class="mcpp-lasterr"><span class="mcpp-dot" aria-hidden="true"></span>${esc(error.title)} <code>${esc(error.code)}</code></p>`:'')
      +activityHtml(plugin,{busy,authorizing,now})
      +`<div class="mcpp-foot"><span class="mcpp-count">${plugin.enabled?esc(plural(tools,'outil','outils')):'désactivé : outils retirés'}</span>`
      +(primary?`<button type="button" class="action small primary" id="mcpp-${primary.act}-${esc(id)}" data-act="${primary.act}" data-id="${esc(id)}" aria-describedby="mcpp-name-${esc(id)}"${busy?' disabled':''}>${esc(primary.label)}</button>`:'')
      +`<button type="button" class="action small" id="mcpp-manage-${esc(id)}" data-act="manage" data-id="${esc(id)}" aria-label="${esc(`Gérer ${name}`)}">Gérer</button></div></li>`;
  }
  /* `adding` : le formulaire d'ajout est ouvert au-dessus ; le vide ne répète pas son appel. */
  function listHtml(list,{busy={},authorizing={},now=0,iconFailed={},adding=false}={}){
    const plugins=(list&&list.plugins)||[];
    let html='';
    if(list&&list.vault_available===false){
      html+='<div class="notice mcpp-vault" role="note"><strong>Aucun coffre de secrets local.</strong> '
        +'Seuls les plugins sans authentification peuvent se connecter : un jeton ou une autorisation OAuth ne seraient conservés nulle part.</div>';
    }
    if(!plugins.length&&adding)return html+'<p class="hint">Aucun plugin pour l’instant.</p>';
    if(!plugins.length){
      return html+'<div class="mcpp-empty"><p class="mcpp-empty-t">Aucun plugin externe pour l’instant.</p>'
        +'<p>Un plugin est un serveur MCP distant ajouté par son adresse. Une fois connecté et activé, ses outils rejoignent ceux que le brain découvre ; JARVIS garde son autorisation, jamais le modèle.</p>'
        +'<button type="button" class="action primary" id="mcpp-add-empty" data-act="add">Ajouter un plugin</button></div>';
    }
    return html+`<ul class="mcpp-grid" aria-label="Plugins externes">${plugins.map(p=>cardHtml(p,{busy:busy[p.plugin_id]||null,
      authorizing:authorizing[p.plugin_id]||null,now,iconFailed:!!iconFailed[p.plugin_id]})).join('')}</ul>`;
  }

  /* Formulaire d'ajout. L'adresse tapée reste (elle n'est pas secrète) ; une
     erreur codée s'affiche sous les champs, reliée par `aria-describedby`. */
  function addFormHtml({endpoint='',displayName='',busy=null,error=null,now=0}={}){
    const disabled=busy?' disabled':'';
    return '<form class="mcpp-add" id="mcppAddForm" novalidate aria-labelledby="mcppAddTitle">'
      +'<h3 class="mcpp-h3" id="mcppAddTitle" tabindex="-1">Ajouter un plugin</h3>'
      +'<p class="hint">L’adresse du serveur MCP (Streamable HTTP). JARVIS l’enregistre, s’y connecte, puis suit ce qu’il demande : rien, une autorisation OAuth dans un nouvel onglet, ou un jeton.</p>'
      +'<div class="mcpp-fields"><div class="field"><label for="mcppEndpoint">Adresse du serveur</label>'
      +`<input type="url" id="mcppEndpoint" name="endpoint" required inputmode="url" autocomplete="url" spellcheck="false" placeholder="https://exemple.com/mcp" value="${esc(endpoint)}"${error?' aria-invalid="true" aria-describedby="mcppAddError"':''}${disabled}></div>`
      +'<div class="field"><label for="mcppName">Nom affiché <span class="mcpp-opt">facultatif</span></label>'
      +`<input type="text" id="mcppName" name="display_name" maxlength="64" autocomplete="off" spellcheck="false" placeholder="nom annoncé par le serveur" value="${esc(displayName)}"${disabled}></div></div>`
      +(busy?`<p class="mcpp-activity"><span class="mcpp-spin" aria-hidden="true"></span><span role="status">${esc(busy.label)}</span> <span class="mcpp-clock" data-since="${busy.started}" aria-hidden="true">${esc(formatSeconds(now-busy.started))}</span></p>`:'')
      +(error?`<div id="mcppAddError">${errorHtml(error,{act:''})}</div>`:'')
      +`<div class="mcpp-row"><button type="submit" class="action primary" id="mcppAddSubmit"${disabled}>Ajouter et connecter</button>`
      +`<button type="button" class="action" id="mcppAddCancel" data-act="cancel-add"${disabled}>Annuler</button></div></form>`;
  }
  /* Accès manuel : Bearer ou en-tête personnalisé. Le champ secret est un mot
     de passe SANS attribut `value` : rien de saisi n'est jamais re-rendu. */
  function credentialFormHtml(plugin,{strategy='bearer',headerName='',busy=null,error=null,now=0,vault=true}={}){
    const id=plugin.plugin_id,disabled=busy||!vault?' disabled':'';
    const header=strategy==='header';
    return `<form class="mcpp-cred" id="mcppCredForm" data-id="${esc(id)}" novalidate aria-labelledby="mcppCredTitle">`
      +'<h4 class="mcpp-h4" id="mcppCredTitle" tabindex="-1">Jeton ou clé d’API</h4>'
      +'<p class="hint">Pour un serveur qui ne propose pas OAuth. La valeur est scellée par Core dans le coffre local, n’est jamais réaffichée, et n’est envoyée qu’à l’origine du plugin.</p>'
      +(vault?'':'<div class="notice bad" role="note">Aucun coffre de secrets sur ce poste : un jeton ne peut pas être conservé.</div>')
      +'<fieldset class="tl-seg mcpp-seg"><legend>Forme de l’accès</legend>'
      +`<label><input type="radio" name="strategy" value="bearer" id="mcppCredBearer"${header?'':' checked'}${disabled}><span>Bearer</span></label>`
      +`<label><input type="radio" name="strategy" value="header" id="mcppCredHeader"${header?' checked':''}${disabled}><span>En-tête personnalisé</span></label></fieldset>`
      +`<div class="field" id="mcppHeaderField"${header?'':' hidden'}><label for="mcppHeaderName">Nom de l’en-tête</label>`
      +`<input type="text" id="mcppHeaderName" name="header_name" maxlength="64" autocomplete="off" spellcheck="false" placeholder="X-Api-Key" value="${esc(headerName)}"${disabled}></div>`
      +`<div class="field"><label for="mcppSecret" id="mcppSecretLabel">${header?'Valeur de l’en-tête':'Jeton'}</label>`
      +`<input type="password" id="mcppSecret" name="value" autocomplete="off" spellcheck="false" maxlength="4096"${error?' aria-invalid="true" aria-describedby="mcppCredError"':''}${disabled}></div>`
      +(busy?`<p class="mcpp-activity"><span class="mcpp-spin" aria-hidden="true"></span><span role="status">${esc(busy.label)}</span> <span class="mcpp-clock" data-since="${busy.started}" aria-hidden="true">${esc(formatSeconds(now-busy.started))}</span></p>`:'')
      +(error?`<div id="mcppCredError">${errorHtml(error,{act:''})}</div>`:'')
      +`<div class="mcpp-row"><button type="submit" class="action primary" id="mcppCredSubmit"${disabled}>Enregistrer et connecter</button>`
      +`<button type="button" class="action" id="mcppCredCancel" data-act="cancel-cred"${busy?' disabled':''}>Annuler</button></div></form>`;
  }
  function dateText(value){
    if(!value)return '—';
    const d=new Date(value);
    if(Number.isNaN(d.getTime()))return String(value);
    const pad=n=>String(n).padStart(2,'0');
    return `${pad(d.getDate())}/${pad(d.getMonth()+1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  /* Vue « Gérer » : identité, actions, accès manuel, outils. Les outils sont
     les lignes de l'inspecteur, rendues par SON code (`rows`, déjà HTML). */
  function manageParts(plugin,{busy=null,authorizing=null,now=0,iconFailed=false,cred=null,actionError=null,tools=null,vault=true}={}){
    const id=plugin.plugin_id,name=plugin.display_name||id;
    const identity=plugin.server_identity||null;
    const error=lastErrorOf(plugin);
    const locked=busy?' disabled':'';
    const connected=plugin.connection_status==='connected';
    const facts=[
      ['Adresse',`<code>${esc(plugin.endpoint)}</code>`],
      ['Identifiant',`<code>${esc(id)}</code>`],
      ['Serveur',identity&&identity.name?`${esc(identity.name)}${identity.version?` ${esc(identity.version)}`:''}${identity.protocol_version?` <span class="hint">· MCP ${esc(identity.protocol_version)}</span>`:''}`:'<span class="mcpp-none">pas encore connu</span>'],
      ['Accès',esc(STRATEGY[plugin.auth_strategy]||plugin.auth_strategy||'—')],
      ['Outils découverts',`${esc(String(toolCountOf(plugin)))}${plugin.last_discovered_at?` <span class="hint">· ${esc(dateText(plugin.last_discovered_at))}</span>`:''}`],
    ];
    const rejected=Array.isArray(plugin.rejected_tools)?plugin.rejected_tools:[];
    if(rejected.length)facts.push(['Outils refusés',rejected.map(r=>`<code>${esc(r.name)}</code> <span class="hint">${esc(r.code)}</span>`).join(', ')]);
    const primary=primaryAction(plugin);
    const actions=[
      connected?`<button type="button" class="action" id="mcpp-m-refresh" data-act="refresh" data-id="${esc(id)}"${locked}>Actualiser les outils</button>`:'',
      plugin.enabled?`<button type="button" class="action${primary?' primary':''}" id="mcpp-m-connect" data-act="connect" data-id="${esc(id)}"${locked}>${connected||plugin.last_discovered_at||plugin.connection_status==='error'||plugin.auth_status==='expired'?'Reconnecter':'Connecter'}</button>`:'',
      `<button type="button" class="action" id="mcpp-m-cred" data-act="cred" data-id="${esc(id)}" aria-expanded="${!!cred}" aria-controls="mcppCredSlot"${locked}>Saisir un jeton</button>`,
      plugin.connection_status!=='disconnected'||plugin.auth_strategy!=='none'?`<button type="button" class="action" id="mcpp-m-disconnect" data-act="disconnect" data-id="${esc(id)}"${locked}>Déconnecter</button>`:'',
      `<button type="button" class="action danger" id="mcpp-m-remove" data-act="remove" data-id="${esc(id)}"${locked}>Supprimer</button>`,
    ].filter(Boolean).join('');
    let toolsBody='';
    if(!plugin.enabled)toolsBody='<p class="hint">Plugin désactivé : ses outils sont retirés de toutes les vues et du brain. Réactivez-le pour les voir ici.</p>';
    else if(!connected)toolsBody=`<p class="hint">${toolCountOf(plugin)?`${esc(plural(toolCountOf(plugin),'outil découvert','outils découverts'))} lors de la dernière connexion ; ils`:'Ses outils'} s’affichent ici une fois le plugin connecté.</p>`;
    else if(!tools||tools.state==='loading')toolsBody=`<p class="tl-loading"><span role="status">Lecture des outils…</span> <span class="mcpp-clock" data-since="${tools?tools.started:now}" aria-hidden="true">${esc(formatSeconds(tools?now-tools.started:0))}</span></p>`;
    else if(tools.state==='error')toolsBody=errorHtml(tools.error,{id:'mcpp-tools-retry',act:'tools-retry',dataId:id});
    else if(!tools.count)toolsBody='<p class="hint">Le serveur n’annonce aucun outil utilisable.</p>';
    else toolsBody=tools.html;
    const head='<button type="button" class="mcpp-back" id="mcpp-back" data-act="back"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 6-6 6 6 6"/></svg>Tous les plugins</button>'
      +`<header class="mcpp-mhead">${avatarHtml(plugin,{failed:iconFailed,size:'lg'})}`
      +`<div class="mcpp-ident"><h3 class="mcpp-mtitle" id="mcpp-m-title" tabindex="-1">${esc(name)}</h3><span class="mcpp-host">${esc(hostOf(plugin))}</span>${badgesHtml(plugin)}</div>`
      +`${switchHtml(plugin,{busy:!!busy,idPrefix:'mcpp-msw'})}</header>`
      +activityHtml(plugin,{busy,authorizing,now})
      +(actionError?`<div class="mcpp-slot">${errorHtml(actionError,{act:wantsManualCredential(plugin,actionError)&&!cred?'cred':'',id:'mcpp-err-cred',retryLabel:'Saisir un jeton',dataId:id})}</div>`
        :error&&!busy&&!authorizing?`<div class="notice ${error.code==='mcp_plugin_reauthorization_required'?'':'bad '}mcpp-slot" role="note"><strong>${esc(error.title)}</strong> <code>${esc(error.code)}</code>${error.hint?`<div class="hint">${esc(error.hint)}</div>`:''}</div>`:'')
      +`<div class="mcpp-actions" role="group" aria-label="Actions sur ${esc(name)}">${actions}</div>`;
    const form=cred?credentialFormHtml(plugin,{...cred,busy,now,vault}):'';
    const body=`<section class="mcpi-sect"><h4>Fiche</h4><dl class="kv mcpp-facts">${facts.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl></section>`
      +`<section class="mcpi-sect mcpp-tools" aria-labelledby="mcpp-tools-h"><h4 id="mcpp-tools-h">Outils</h4>${toolsBody}</section>`;
    return {head,cred:form,body};
  }
  /* La vue entière (tests, premier rendu) ; le navigateur remplit les trois
     emplacements séparément, pour qu'un rendu d'arrière-plan ne touche jamais
     un formulaire en cours de saisie. */
  function manageHtml(plugin,options={}){
    const parts=manageParts(plugin,options);
    return `<article class="mcpp-manage" data-id="${esc(plugin.plugin_id)}" aria-labelledby="mcpp-m-title">`
      +`<div id="mcppMHead">${parts.head}</div><div id="mcppCredSlot">${parts.cred}</div><div id="mcppMBody">${parts.body}</div></article>`;
  }

  /* Outils du plugin dans le catalogue fusionné : `server === plugin_id`. */
  function pluginTools(catalog,pluginId){
    return ((catalog&&catalog.tools)||[]).filter(t=>t.server===pluginId);
  }

  return {ROUTE,DEADLINE_MS,LONG_DEADLINE_MS,POLL_MS,POLL_MAX_MS,PLUGIN_ID,CONNECTION,AUTH,STRATEGY,ERRORS,AUTH_CODES,LONG_ACTIONS,
    esc,formatSeconds,formatClock,hostOf,initialOf,iconUrlOf,pluginPath,pluginRoute,createClient,errorView,errorHtml,lastErrorOf,
    connectionOf,authOf,toolCountOf,primaryAction,wantsManualCredential,pollDecision,summaryOf,statusView,
    avatarHtml,badgesHtml,switchHtml,activityHtml,cardHtml,listHtml,addFormHtml,credentialFormHtml,manageParts,manageHtml,pluginTools};
})();

/* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
if(typeof module!=='undefined'&&module.exports)module.exports=JarvisMcpPluginsCore;

/* --------------------------------------------------------------------------
   Bloc navigateur : onglets du dialogue MCP, cartes, formulaires, attente
   d'une autorisation, vue « Gérer ». Les tests node le font tourner sur un
   DOM simulé.

   LE FOCUS SURVIT AUX RE-RENDUS, comme dans l'inspecteur : l'identifiant de
   l'élément focalisé est noté avant le remplacement du HTML, puis rendu.
   UNE SAISIE SURVIT AUX RE-RENDUS : le corps est fait d'emplacements
   (formulaire, liste ; en-tête, accès, fiche) et un emplacement n'est
   remplacé que si son HTML change. L'attente d'une autorisation relit la
   liste toutes les 2 s ; elle ne touche jamais un formulaire en cours.
   -------------------------------------------------------------------------- */
(function installJarvisMcpPlugins(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const P=JarvisMcpPluginsCore;
  const I=typeof JarvisMcpInspectorCore!=='undefined'?JarvisMcpInspectorCore:null;
  const root=document.getElementById('mcpInspector');
  const panel=document.getElementById('mcpPlugins');
  if(!root||!panel||!I)return;
  const el={
    open:document.getElementById('openMcpInspector'),
    tabs:document.getElementById('mcpViewTabs'),
    tabInternal:document.getElementById('mcpViewInternal'),tabPlugins:document.getElementById('mcpViewPlugins'),
    count:document.getElementById('mcpViewCount'),
    status:document.getElementById('mcppStatus'),statusLabel:document.getElementById('mcppStatusLabel'),
    statusDetail:document.getElementById('mcppStatusDetail'),statusClock:document.getElementById('mcppStatusClock'),
    add:document.getElementById('mcppAdd'),refresh:document.getElementById('mcppRefresh'),
    body:document.getElementById('mcppBody'),announce:document.getElementById('mcppAnnounce'),
  };
  const TICK_MS=250;
  /* Erreurs passagères de relecture pendant une attente : on continue d'attendre. */
  const TRANSIENT=new Set(['core_timeout','timeout','network','core_unreachable']);
  const S={view:'internal',list:null,listError:null,loading:false,loadStarted:0,listGen:0,
    busy:{},authorizing:{},iconFailed:{},lastFailure:{},add:null,manage:null,cred:null,actionError:null,
    tools:null,toolsGen:0,expanded:new Set(),details:{},rawOpen:new Set(),tick:null,layout:null,pendingFocus:null};
  const client=P.createClient({fetchImpl:(path,options)=>window.fetch(path,options)});
  /* Lecture des outils : le client EN LECTURE SEULE de l'inspecteur. */
  const catalog=I.createClient({fetchImpl:(path,options)=>window.fetch(path,options)});
  const queue=I.createQueue(I.PARALLEL);

  /* Journal de la page : codes et identifiants seulement, jamais une valeur saisie. */
  function log(level,event,data){
    const line=`[mcp-plugins] ${event} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line);
  }
  function notify(spec){if(typeof toast==='function')toast(spec)}
  function announce(text){if(el.announce)el.announce.textContent=text}
  function pluginById(id){return ((S.list&&S.list.plugins)||[]).find(p=>p.plugin_id===id)||null}
  function nameOf(id){const p=pluginById(id);return (p&&p.display_name)||id}
  function coded(code,message){return Object.assign(new Error(message),{code,status:0})}
  function failed(action,error,context){
    const view=P.errorView(error);
    log('error','mcp.plugins.action_failed',{action,code:view.code,status:view.status,...context});
    return view;
  }

  /* ------------------------------------------------------------ rendu */
  /* Un contrôle rendu `disabled` pendant son action (interrupteur, bouton de la
     fiche) ne peut pas reprendre le focus : l'intention est gardée
     (`S.pendingFocus`) et rendue au premier rendu où il est de nouveau actif,
     tant que le focus n'est allé nulle part ailleurs. */
  function withFocus(fn){
    const active=document.activeElement;
    const idle=!active||active===document.body;
    const id=!idle&&root.contains(active)&&active.id?active.id:idle?S.pendingFocus:null;
    fn();
    if(!id)return;
    const back=document.getElementById(id);
    if(!back){S.pendingFocus=null;return}
    if(back.disabled){S.pendingFocus=id;return}
    S.pendingFocus=null;
    if(document.activeElement!==back&&typeof back.focus==='function')back.focus({preventScroll:true});
  }
  function focusId(id){
    const node=document.getElementById(id);
    if(node&&typeof node.focus==='function')node.focus({preventScroll:true});
  }
  /* Un emplacement n'est réécrit que si son contenu change. */
  function setSlot(id,html){
    const node=document.getElementById(id);
    if(node&&node.innerHTML!==html)node.innerHTML=html;
  }
  function renderStatus(){
    const view=P.statusView({loading:S.loading,error:S.listError,list:S.list,elapsedMs:Date.now()-S.loadStarted});
    el.status.dataset.tone=view.tone;
    el.statusLabel.textContent=view.label;
    el.statusDetail.textContent=view.detail;
    el.statusClock.textContent=view.clock;
    if(el.count){
      const n=S.list?(S.list.plugins||[]).length:null;
      el.count.textContent=n===null?'':String(n);el.count.hidden=n===null;
    }
  }
  function toolsView(plugin){
    if(!S.tools||S.tools.id!==plugin.plugin_id)return null;
    if(S.tools.state!=='ok')return S.tools;
    return {state:'ok',count:S.tools.rows.length,html:I.toolRowsHtml(S.tools.rows,{idPrefix:'mcpp-t',expanded:S.expanded,
      details:S.details,now:Date.now(),rawOpen:S.rawOpen})};
  }
  function layout(kind){
    if(S.layout===kind)return;
    S.layout=kind;
    el.body.innerHTML=kind==='list'
      ?'<div id="mcppAddSlot"></div><div id="mcppListSlot"></div>'
      :`<article class="mcpp-manage" aria-labelledby="mcpp-m-title"><div id="mcppMHead"></div><div id="mcppCredSlot"></div><div id="mcppMBody"></div></article>`;
  }
  function renderBody(){
    const now=Date.now();
    const plugin=S.manage?pluginById(S.manage):null;
    if(S.manage&&!plugin&&S.list){S.manage=null;S.cred=null;S.actionError=null}
    if(plugin){
      layout('manage');
      const parts=P.manageParts(plugin,{busy:S.busy[plugin.plugin_id]||null,authorizing:S.authorizing[plugin.plugin_id]||null,
        now,iconFailed:!!S.iconFailed[plugin.plugin_id],cred:S.cred,actionError:S.actionError,tools:toolsView(plugin),
        vault:!S.list||S.list.vault_available!==false});
      setSlot('mcppMHead',parts.head);setSlot('mcppCredSlot',parts.cred);setSlot('mcppMBody',parts.body);
      return;
    }
    layout('list');
    setSlot('mcppAddSlot',S.add?P.addFormHtml({...S.add,now}):'');
    let html='';
    if(S.loading&&!S.list)html='<div class="mcpi-skel mcpi-skel-list" aria-hidden="true"><span></span><span></span><span></span></div>'
      +`<p class="tl-loading"><span role="status">Lecture des plugins…</span> <span class="mcpp-clock" data-since="${S.loadStarted}" aria-hidden="true">${P.formatSeconds(now-S.loadStarted)}</span></p>`;
    else if(S.listError&&!S.list)html=P.errorHtml(S.listError,{id:'mcpp-retry-list',act:'retry'});
    else if(S.list){
      if(S.listError)html=P.errorHtml(S.listError,{id:'mcpp-retry-list',act:'retry',lead:'Actualisation impossible — '});
      html+=P.listHtml(S.list,{busy:S.busy,authorizing:S.authorizing,now,iconFailed:S.iconFailed,adding:!!S.add});
    }
    setSlot('mcppListSlot',html);
  }
  function render(){withFocus(()=>{renderStatus();renderBody()})}
  /* Un seul minuteur, actif pendant une attente : il fait avancer les secondes
     affichées (éléments `aria-hidden`), sans re-rendu. */
  function waiting(){
    return S.loading||Object.keys(S.busy).length>0||Object.keys(S.authorizing).length>0||!!(S.add&&S.add.busy)
      ||!!(S.tools&&S.tools.state==='loading')||Object.values(S.details).some(d=>d.state==='loading');
  }
  function tick(){
    if(!waiting()){clearInterval(S.tick);S.tick=null;return}
    const now=Date.now();
    if(S.loading)el.statusClock.textContent=P.formatSeconds(now-S.loadStarted);
    for(const clock of el.body.querySelectorAll('.mcpp-clock[data-since]')){
      const since=Number(clock.dataset.since);
      clock.textContent=clock.dataset.left?`${P.formatClock(now-since)} · reste ${P.formatClock(P.POLL_MAX_MS-(now-since))}`:P.formatSeconds(now-since);
    }
  }
  function armTick(){if(!S.tick)S.tick=setInterval(tick,TICK_MS)}

  /* ------------------------------------------------------------ onglets du dialogue */
  function selectView(view,{focus=false}={}){
    S.view=view==='plugins'?'plugins':'internal';
    root.dataset.view=S.view;
    const plugins=S.view==='plugins';
    el.tabPlugins.setAttribute('aria-selected',String(plugins));el.tabPlugins.tabIndex=plugins?0:-1;
    el.tabInternal.setAttribute('aria-selected',String(!plugins));el.tabInternal.tabIndex=plugins?-1:0;
    panel.hidden=!plugins;
    if(plugins)loadList();
    if(focus)(plugins?el.tabPlugins:el.tabInternal).focus();
  }

  /* ------------------------------------------------------------ lecture */
  async function loadList({quiet=false}={}){
    const generation=++S.listGen;
    if(!quiet){S.loading=true;S.loadStarted=Date.now();armTick();render()}
    try{
      const list=await client.list();
      if(generation!==S.listGen)return;
      S.list=list;S.listError=null;
      const n=(list.plugins||[]).length;
      if(!quiet)announce(`${n} plugin${n===1?'':'s'} externe${n===1?'':'s'}.`);
    }catch(error){
      if(generation!==S.listGen)return;
      S.listError=error;failed('list',error,{});
      if(!quiet)announce(`Plugins indisponibles : ${P.errorView(error).title}.`);
    }finally{
      if(generation===S.listGen){S.loading=false;render()}
    }
    if(S.manage)loadTools(S.manage);
  }
  /* Outils d'un plugin connecté : lignes du catalogue fusionné, via le client
     en lecture seule de l'inspecteur ; relues quand sa liste d'outils change. */
  async function loadTools(id,{force=false}={}){
    const plugin=pluginById(id);
    if(!plugin||!plugin.enabled||plugin.connection_status!=='connected'){
      if(S.tools){S.tools=null;S.toolsGen++;withFocus(renderBody)}
      return;
    }
    if(!force&&S.tools&&S.tools.id===id&&S.tools.state!=='error'&&S.tools.sig===plugin.capability_revision)return;
    const generation=++S.toolsGen;
    S.tools={id,state:'loading',started:Date.now(),sig:plugin.capability_revision};
    armTick();withFocus(renderBody);
    try{
      const listing=await catalog.list();
      if(generation!==S.toolsGen)return;
      S.tools={id,state:'ok',rows:P.pluginTools(listing,id),sig:plugin.capability_revision};
      S.details={};
      S.expanded=new Set([...S.expanded].filter(k=>S.tools.rows.some(t=>I.toolKey(t)===k)));
      for(const key of S.expanded)loadDetail(key);
    }catch(error){
      if(generation!==S.toolsGen)return;
      S.tools={id,state:'error',error,sig:plugin.capability_revision};failed('tools',error,{plugin_id:id});
    }
    if(S.manage===id)withFocus(renderBody);
  }
  function loadDetail(key,{force=false}={}){
    const current=S.details[key];
    if(current&&(current.state==='ok'||current.state==='loading'))return;
    if(current&&current.state==='error'&&!force)return;
    const tool=S.tools&&S.tools.state==='ok'?S.tools.rows.find(t=>I.toolKey(t)===key):null;
    if(!tool)return;
    const generation=S.toolsGen;
    S.details[key]={state:'loading',started:Date.now()};
    armTick();
    queue.push(`${generation}:${key}`,async()=>{
      let entry;
      try{entry={state:'ok',tool:(await catalog.detail(tool.server,tool.name)).tool}}
      catch(error){entry={state:'error',error};failed('tool_detail',error,{plugin_id:tool.server})}
      if(generation!==S.toolsGen)return;
      S.details[key]=entry;
      if(S.manage)withFocus(renderBody);
    });
  }

  /* ------------------------------------------------------------ actions
     Chaque action : occupé visible (libellé + secondes), échec à l'écran ET
     au journal, libération dans `finally`, puis relecture de l'état de Core.
     Rend la réponse, ou `null` en échec (l'erreur est dans `S.lastFailure`). */
  async function run(id,label,action,work,{surface=true}={}){
    if(S.busy[id])return null;
    S.busy[id]={label,started:Date.now(),action};S.actionError=null;delete S.lastFailure[id];
    armTick();render();
    try{return await work()}
    catch(error){
      const view=failed(action,error,{plugin_id:id});
      S.lastFailure[id]=error;
      if(surface){
        if(S.manage===id)S.actionError=error;
        notify({title:`${nameOf(id)} : ${view.title}`,sub:view.hint,kind:'bad',ms:7000});
      }
      announce(`${view.title}.`);
      return null;
    }finally{
      delete S.busy[id];
      await loadList({quiet:true});
    }
  }
  async function connect(id){
    endWait(id);
    const answer=await run(id,'Connexion…','connect',()=>client.connect(id));
    if(!answer)return false;
    const body=answer.body||{};
    if(answer.status===202&&body.status==='authorizing'&&typeof body.authorization_url==='string'){
      beginAuthorization(id,body.authorization_url);
      return true;
    }
    log('info','mcp.plugins.connected',{plugin_id:id});
    const tools=P.toolCountOf(body.plugin||pluginById(id)||{});
    notify({title:`${nameOf(id)} connecté`,sub:`${tools} outil${tools===1?'':'s'} disponible${tools===1?'':'s'}.`,kind:'info',ms:3500});
    announce(`${nameOf(id)} connecté.`);
    return true;
  }
  /* OAuth : l'URL s'ouvre dans un nouvel onglet (`noopener,noreferrer` : ni
     accès à cette page, ni son adresse envoyée au serveur d'autorisation) ; l'état est relu
     toutes les 2 s, 5 min au plus. Si le navigateur a bloqué l'ouverture (la
     réponse arrive après le geste), le lien reste à l'écran. */
  function beginAuthorization(id,url){
    S.authorizing[id]={url,started:Date.now(),timer:null};
    armTick();
    try{window.open(url,'_blank','noopener,noreferrer')}
    catch(error){log('warn','mcp.plugins.window_open_failed',{plugin_id:id,error:String(error&&error.name)})}
    log('info','mcp.plugins.authorizing',{plugin_id:id});
    announce(`Autorisation de ${nameOf(id)} ouverte dans un nouvel onglet. JARVIS attend le retour, 5 minutes au plus.`);
    render();
    schedulePoll(id);
  }
  function schedulePoll(id){
    const wait=S.authorizing[id];
    if(!wait)return;
    clearTimeout(wait.timer);
    wait.timer=setTimeout(()=>pollOnce(id),P.POLL_MS);
  }
  async function pollOnce(id){
    const wait=S.authorizing[id];
    if(!wait)return;
    await loadList({quiet:true});
    if(S.authorizing[id]!==wait)return;
    const expired=Date.now()-wait.started>=P.POLL_MAX_MS;
    const transient=S.listError&&TRANSIENT.has(S.listError.code);
    const decision=S.listError?(transient&&!expired?'continue':transient?'timeout':'error')
      :P.pollDecision(pluginById(id),wait.started,Date.now());
    if(decision==='continue'){schedulePoll(id);return}
    endWait(id);
    if(decision==='done'){
      log('info','mcp.plugins.authorized',{plugin_id:id});
      notify({title:`${nameOf(id)} connecté`,sub:'Autorisation reçue.',kind:'info',ms:3500});
      announce(`${nameOf(id)} autorisé et connecté.`);
    }else if(decision==='timeout'){
      const error=coded('oauth_timeout','aucun retour d’autorisation en 5 min');
      failed('authorize',error,{plugin_id:id});
      if(S.manage===id)S.actionError=error;
      notify({title:`${nameOf(id)} : ${P.ERRORS.oauth_timeout.title}`,sub:P.ERRORS.oauth_timeout.hint,kind:'bad',ms:7000});
      announce(`${P.ERRORS.oauth_timeout.title}.`);
    }else if(decision==='failed'||decision==='error'){
      const plugin=pluginById(id);
      const error=decision==='error'?S.listError
        :plugin&&plugin.last_error_code?coded(plugin.last_error_code,P.lastErrorOf(plugin).title):null;
      log('warn','mcp.plugins.authorize_failed',{plugin_id:id,code:error&&error.code});
      notify({title:`${nameOf(id)} : autorisation non aboutie`,sub:error?P.errorView(error).title:'',kind:'bad',ms:7000});
      announce('Autorisation non aboutie.');
      /* Le serveur a refusé ce qu'OAuth a obtenu : le repli manuel, tout de
         suite, sauf si l'utilisateur est parti ailleurs entre-temps. */
      if(decision==='failed'&&P.wantsManualCredential(plugin,error)&&!S.add&&(S.manage===null||S.manage===id)){
        openManage(id,{cred:true});
        S.actionError=error;withFocus(renderBody);
        return;
      }
      if(error&&S.manage===id)S.actionError=error;
    }
    render();
  }
  function endWait(id){
    const wait=S.authorizing[id];
    if(wait)clearTimeout(wait.timer);
    delete S.authorizing[id];
  }
  async function toggle(id){
    const plugin=pluginById(id);
    if(!plugin)return;
    const next=!plugin.enabled;
    const answer=await run(id,next?'Activation…':'Désactivation…','toggle',()=>client.update(id,{enabled:next}));
    if(!answer)return;
    log('info','mcp.plugins.toggled',{plugin_id:id,enabled:next});
    announce(`${nameOf(id)} ${next?'activé : ses outils rejoignent le brain une fois connecté':'désactivé : ses outils sont retirés'}.`);
  }
  async function disconnect(id){
    const plugin=pluginById(id);
    if(!plugin)return;
    if(plugin.auth_strategy!=='none'&&typeof confirmDialog==='function'&&!await confirmDialog({
      title:`Déconnecter ${nameOf(id)} ?`,
      lines:['La connexion est fermée et son accès (jeton, autorisation) est oublié par JARVIS.',
        'Le plugin reste dans la liste ; il faudra l’autoriser de nouveau pour le reconnecter.'],
      confirmLabel:'Déconnecter'}))return;
    endWait(id);
    const answer=await run(id,'Déconnexion…','disconnect',()=>client.disconnect(id));
    if(!answer)return;
    log('info','mcp.plugins.disconnected',{plugin_id:id});
    notify({title:`${nameOf(id)} déconnecté`,sub:'Son accès a été oublié.',kind:'info',ms:3500});
    announce(`${nameOf(id)} déconnecté.`);
  }
  async function rereadPluginTools(id){
    const answer=await run(id,'Relecture des outils…','refresh',()=>client.refresh(id));
    if(!answer)return;
    log('info','mcp.plugins.refreshed',{plugin_id:id});
    announce('Outils relus.');
    loadTools(id,{force:true});
  }
  async function remove(id){
    const name=nameOf(id);
    const ok=typeof confirmDialog==='function'?await confirmDialog({
      title:`Supprimer ${name} ?`,
      lines:['Le plugin, sa connexion et son accès sont effacés de JARVIS.','Ses outils disparaissent du brain. Pour le retrouver, il faudra l’ajouter de nouveau.'],
      confirmLabel:'Supprimer',danger:true}):false;
    if(!ok)return;
    endWait(id);
    const managing=S.manage===id;
    const answer=await run(id,'Suppression…','remove',()=>client.remove(id));
    if(!answer)return;
    log('info','mcp.plugins.removed',{plugin_id:id});
    notify({title:`${name} supprimé`,kind:'info',ms:3500});
    announce(`${name} supprimé.`);
    if(managing){S.manage=null;closeManage()}
    else if(!document.getElementById(`mcpp-manage-${id}`))focusId('mcppAdd');
  }
  async function submitCredential(form){
    const id=form.dataset.id;
    if(!S.cred||S.busy[id])return;
    const secretInput=form.querySelector('#mcppSecret');
    const strategy=S.cred.strategy;
    const headerInput=form.querySelector('#mcppHeaderName');
    const headerName=strategy==='header'?String((headerInput&&headerInput.value)||'').trim():'';
    /* Lue une fois, puis le champ est vidé AVANT le réseau : la valeur ne vit
       que dans cette fonction et dans le corps de la requête. */
    let value=secretInput?String(secretInput.value||''):'';
    if(secretInput)secretInput.value='';
    if(!value.trim()||(strategy==='header'&&!headerName)){
      value='';
      S.cred={strategy,headerName,error:coded('mcp_plugin_invalid',strategy==='header'?'nom d’en-tête et valeur requis':'jeton requis')};
      withFocus(renderBody);focusId(strategy==='header'&&!headerName?'mcppHeaderName':'mcppSecret');
      return;
    }
    S.cred={strategy,headerName,error:null};
    const request=client.setCredential(id,{strategy,headerName,value});
    value='';
    const saved=await run(id,'Enregistrement de l’accès…','credential',()=>request,{surface:false});
    if(!saved){
      if(S.cred)S.cred={...S.cred,error:S.lastFailure[id]||null};
      withFocus(renderBody);focusId('mcppSecret');
      return;
    }
    log('info','mcp.plugins.credential_saved',{plugin_id:id,strategy});
    S.cred=null;
    withFocus(renderBody);
    focusId('mcpp-m-title');
    await connect(id);
  }
  async function submitAdd(form){
    if(S.add&&S.add.busy)return;
    const endpoint=String(form.querySelector('#mcppEndpoint').value||'').trim();
    const displayName=String(form.querySelector('#mcppName').value||'').trim();
    if(!endpoint){
      S.add={endpoint,displayName,busy:null,error:coded('mcp_endpoint_invalid','adresse requise')};
      withFocus(renderBody);focusId('mcppEndpoint');return;
    }
    S.add={endpoint,displayName,busy:{label:'Enregistrement du plugin…',started:Date.now()},error:null};
    armTick();withFocus(renderBody);
    let plugin=null;
    try{
      plugin=(await client.create(endpoint,displayName||undefined)).plugin;
      log('info','mcp.plugins.created',{plugin_id:plugin&&plugin.plugin_id});
    }catch(error){
      failed('create',error,{});
      S.add={endpoint,displayName,busy:null,error};
      withFocus(renderBody);focusId('mcppEndpoint');
      announce(`${P.errorView(error).title}.`);
      return;
    }
    S.add=null;
    await loadList({quiet:true});
    const id=plugin.plugin_id;
    focusId(`mcpp-manage-${id}`);
    announce(`${nameOf(id)} ajouté. Connexion…`);
    await connect(id);
    const after=pluginById(id);
    const error=S.lastFailure[id]||null;
    if(after&&!S.authorizing[id]&&after.connection_status!=='connected'&&P.wantsManualCredential(after,error)){
      /* Le serveur veut un accès qu'OAuth n'a pas fourni : la saisie manuelle, directement. */
      openManage(id,{cred:true});
      S.actionError=error;withFocus(renderBody);
    }else focusId(`mcpp-manage-${id}`);
  }
  function openAdd(){
    S.manage=null;S.cred=null;S.actionError=null;
    S.add=S.add||{endpoint:'',displayName:'',busy:null,error:null};
    render();focusId('mcppEndpoint');
  }
  function closeAdd(){if(!S.add||S.add.busy)return;S.add=null;render();focusId('mcppAdd')}
  function openManage(id,{cred=false}={}){
    S.add=null;S.manage=id;S.actionError=null;S.cred=cred?{strategy:'bearer',headerName:'',error:null}:null;
    S.expanded=new Set();S.details={};S.tools=null;S.toolsGen++;
    render();
    focusId(cred?'mcppSecret':'mcpp-m-title');
    loadTools(id);
  }
  function closeManage(){
    const id=S.manage;
    S.manage=null;S.cred=null;S.actionError=null;S.tools=null;S.toolsGen++;
    render();
    if(id&&document.getElementById(`mcpp-manage-${id}`))focusId(`mcpp-manage-${id}`);else focusId('mcppAdd');
  }
  function openCred(){
    S.cred={strategy:'bearer',headerName:'',error:null};S.actionError=null;
    withFocus(renderBody);focusId('mcppSecret');
  }
  function closeCred(){S.cred=null;withFocus(renderBody);focusId('mcpp-m-cred')}
  /* Échap : revient d'un cran (accès, fiche, ajout) avant de fermer le dialogue. */
  function stepBack(){
    if(S.cred&&!(S.manage&&S.busy[S.manage])){closeCred();return true}
    if(S.manage){closeManage();return true}
    if(S.add&&!S.add.busy){closeAdd();return true}
    return false;
  }
  function toggleTool(key){
    if(S.expanded.has(key))S.expanded.delete(key);
    else{S.expanded.add(key);loadDetail(key)}
    withFocus(renderBody);
  }

  /* ------------------------------------------------------------ branchement */
  el.tabInternal.addEventListener('click',()=>selectView('internal'));
  el.tabPlugins.addEventListener('click',()=>selectView('plugins'));
  el.tabs.addEventListener('keydown',event=>{
    const next=I.tabKey(event.key,S.view==='plugins'?1:0,2);
    if(next===null)return;
    event.preventDefault();
    selectView(next===1?'plugins':'internal',{focus:true});
  });
  el.add.addEventListener('click',openAdd);
  el.refresh.addEventListener('click',()=>{S.tools=null;S.toolsGen++;loadList()});
  /* Réouverture du dialogue : la vue choisie est gardée pour la session. Le
     focus que l'inspecteur donne à sa recherche (masquée ici) est repris deux
     images plus tard. */
  if(el.open)el.open.addEventListener('click',()=>{
    if(root.hidden)return;
    selectView(S.view);
    if(S.view==='plugins')requestAnimationFrame(()=>requestAnimationFrame(()=>el.tabPlugins.focus({preventScroll:true})));
  });
  el.body.addEventListener('click',event=>{
    const target=event.target.closest('button');
    if(!target||target.disabled)return;
    const id=target.dataset.id;
    if(target.classList.contains('mcpi-toggle')){toggleTool(target.dataset.key);return}
    /* « Réessayer » d'un descripteur : bouton rendu par l'inspecteur. */
    if(target.dataset.retry==='detail'){loadDetail(target.dataset.key,{force:true});withFocus(renderBody);return}
    switch(target.dataset.act){
      case 'add':openAdd();break;
      case 'cancel-add':closeAdd();break;
      case 'retry':loadList();break;
      case 'manage':openManage(id);break;
      case 'back':closeManage();break;
      case 'toggle':toggle(id);break;
      case 'connect':connect(id);break;
      case 'disconnect':disconnect(id);break;
      case 'refresh':rereadPluginTools(id);break;
      case 'remove':remove(id);break;
      case 'cred':openCred();break;
      case 'cancel-cred':closeCred();break;
      case 'stopwait':
        endWait(id);log('info','mcp.plugins.wait_abandoned',{plugin_id:id});render();
        focusId(S.manage?'mcpp-m-connect':`mcpp-manage-${id}`);break;
      case 'tools-retry':loadTools(id,{force:true});break;
      default:break;
    }
  });
  el.body.addEventListener('submit',event=>{
    event.preventDefault();
    const form=event.target;
    if(form.id==='mcppAddForm')submitAdd(form);
    else if(form.id==='mcppCredForm')submitCredential(form);
  });
  /* Bearer ↔ en-tête : on montre ou cache le champ du nom, sans re-rendu (la
     saisie en cours reste dans son champ, et nulle part ailleurs). */
  el.body.addEventListener('change',event=>{
    const t=event.target;
    if(!t||t.name!=='strategy'||!S.cred)return;
    const header=t.value==='header';
    S.cred={...S.cred,strategy:header?'header':'bearer',error:null};
    const field=document.getElementById('mcppHeaderField'),label=document.getElementById('mcppSecretLabel');
    if(field)field.hidden=!header;
    if(label)label.textContent=header?'Valeur de l’en-tête':'Jeton';
  });
  el.body.addEventListener('keydown',event=>{
    const current=event.target.closest&&event.target.closest('.mcpi-toggle');
    if(!current)return;
    const toggles=[...el.body.querySelectorAll('.mcpi-toggle')];
    const next=I.cardKey(event.key,toggles.indexOf(current),toggles.length);
    if(next===null)return;
    event.preventDefault();
    toggles[next].focus();
  });
  el.body.addEventListener('toggle',event=>{
    const raw=event.target;
    if(!raw||!raw.classList||!raw.classList.contains('mcpi-raw'))return;
    if(raw.open)S.rawOpen.add(raw.dataset.key);else S.rawOpen.delete(raw.dataset.key);
  },true);
  /* Icône distante illisible : la lettre reste, l'image n'est plus redemandée. */
  el.body.addEventListener('error',event=>{
    const img=event.target;
    if(!img||img.tagName!=='IMG'||!img.dataset||!img.dataset.iconFor)return;
    S.iconFailed[img.dataset.iconFor]=true;
    img.remove();
  },true);
  /* Capture sur la fenêtre : passe avant la fermeture du dialogue (capture du
     document, inspecteur). La confirmation de la page, ouverte, garde la sienne. */
  window.addEventListener('keydown',event=>{
    if(event.key!=='Escape'||root.hidden||S.view!=='plugins')return;
    const confirmBack=document.getElementById('confirmBack');
    if(confirmBack&&!confirmBack.hidden)return;
    if(stepBack()){event.preventDefault();event.stopPropagation()}
  },true);

  root.dataset.view=S.view;
  window.JarvisMcpPlugins={select:selectView,state:S};
})();
