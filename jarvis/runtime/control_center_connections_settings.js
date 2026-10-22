/* Connexions › Fournisseurs (jarvis-settings-ui-reorganization, Slice 07 — `docs/settings/connections.md`).

   Une carte par fournisseur décrit par le serveur (`credentials_state` de `jarvis/runtime/credentials.py`) :
   identité, configuré ou non, clé active, clés rangées (ajouter, remplacer la valeur, supprimer, choisir l'active),
   retombée sur une variable d'environnement. La note d'usage est le `hint` du fournisseur servi par le serveur ;
   aucune liste de fournisseurs, de variables ni de libellés n'est copiée ici.

   Jamais de secret : le serveur ne renvoie qu'un indice (`…abcd`), la page n'affiche que lui. Une valeur saisie est
   lue puis effacée de son champ AVANT l'envoi ; elle ne va dans aucun message, journal ni attribut.

   Requêtes (routes et charges du magasin de clés inchangées) :
   - ajout     : POST de `{provider, name, value}` vers la route des clés ;
   - remplacer : même route, `{id, provider, name, value}` (le serveur garde le nom, remplace la valeur) ;
   - supprimer : POST de `{id}` vers la route de suppression, après une confirmation sur place ;
   - liaison   : POST de `{provider, id}` vers la route de liaison.
   Chaque réponse porte l'état complet, rendu tel quel. Une vue détruite (`destroy`) ne dessine plus rien, ignore
   les réponses tardives et arrête son minuteur d'attente ; l'état reçu est quand même transmis (`onState`), car il
   est vrai côté serveur. */
(function(root){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  /* Identifiants servis par le serveur (`openai`, `cred_1a2b3c4d`) : réduits à un attribut `id` sûr. */
  const slug=v=>String(v??'').replace(/[^A-Za-z0-9_-]/g,'_');
  const ROUTES=Object.freeze({read:'/api/credentials',save:'/api/credentials',remove:'/api/credentials/delete',bind:'/api/credentials/bind'});
  /* Au-delà, l'attente se dit et la carte rend la main (RULE ZERO : aucune attente sans fin). */
  const WAIT_MS=15000;
  const cardId=provider=>`connection_${slug(provider)}`;

  /* Ce que dit la tête d'une carte : clé enregistrée, retombée sur l'environnement, rien. */
  function providerStatus(state,provider){
    const keys=(state.credentials||[]).filter(c=>c.provider===provider.id);
    const env=((state.environment||{})[provider.id]||[]);
    const active=keys.find(c=>c.bound)||null;
    if(keys.length)return {kind:'ok',label:'Clé enregistrée',keys,env,active};
    if(env.length)return {kind:'warn',label:'Variable d’environnement',keys,env,active};
    return {kind:'info',label:'Non configuré',keys,env,active};
  }

  function envLine(provider,status){
    if(!status.env.length)return status.keys.length?'':`<p class="conn-env">Aucune clé enregistrée ni variable d’environnement détectée.</p>`;
    const names=status.env.map(n=>`<code>${esc(n)}</code>`).join(', ');
    const plural=status.env.length>1;
    if(status.keys.length)return `<p class="conn-env">${plural?'Variables':'Variable'} d’environnement ${names} ${plural?'présentes':'présente'} : en réserve, la clé enregistrée passe avant.</p>`;
    return `<p class="conn-env">Utilise ${plural?'les variables':'la variable'} d’environnement ${names} tant qu’aucune clé n’est enregistrée ici.</p>`;
  }

  function keyRow(provider,key,view){
    const id=slug(key.id),radio=`conn_bind_${id}`,busy=view.busy?' disabled':'';
    const confirming=view.confirm===key.id;
    const actions=confirming
      ?`<span class="conn-confirm" role="group" aria-label="Confirmer la suppression de ${esc(key.name)}">
          <span>Supprimer « ${esc(key.name)} » ?</span>
          <button type="button" class="action small conn-danger" data-conn-delete-confirm="${esc(key.id)}"${busy}>Supprimer</button>
          <button type="button" class="action small" data-conn-delete-cancel${busy}>Annuler</button></span>`
      :`<details class="conn-replace"${view.replace===key.id?' open':''}><summary>Remplacer la valeur</summary>
          <form class="conn-form conn-form-one" data-conn-replace="${esc(key.id)}" data-provider="${esc(provider.id)}">
            <div class="conn-field"><label for="conn_replace_${id}">Nouvelle valeur pour « ${esc(key.name)} »</label>
              <input id="conn_replace_${id}" name="value" type="password" autocomplete="off" spellcheck="false" placeholder="${esc(provider.placeholder||'')}"${busy}></div>
            <button class="action small primary" type="submit"${busy}>Remplacer</button>
          </form></details>
        <button type="button" class="action small" data-conn-delete="${esc(key.id)}"${busy}>Supprimer</button>`;
    return `<li class="conn-key${key.bound?' is-active':''}" data-conn-key="${esc(key.id)}">
      <input type="radio" id="${radio}" name="conn_bind_${slug(provider.id)}" data-bind-provider="${esc(provider.id)}" data-bind-id="${esc(key.id)}"${key.bound?' checked':''}${busy}>
      <label for="${radio}"><span class="conn-key-name">${esc(key.name)}</span> <samp class="conn-hint" aria-label="se termine par ${esc(String(key.hint||'').replace(/^…/,''))}">${esc(key.hint)}</samp>${key.bound?' <span class="set-badge set-badge-ok">Active</span>':''}</label>
      <span class="conn-key-actions">${actions}</span></li>`;
  }

  function card(state,provider,view){
    const status=providerStatus(state,provider),id=slug(provider.id),busy=view.busy?' disabled':'';
    const keys=status.keys.length
      ?`<fieldset class="conn-keys"><legend>${status.keys.length>1?'Clé utilisée par JARVIS — choisissez-en une':'Clé enregistrée'}</legend>
          <ul class="conn-key-list">${status.keys.map(k=>keyRow(provider,k,view)).join('')}</ul></fieldset>`
      :'';
    return `<article class="conn-card" id="${cardId(provider.id)}" data-conn-provider="${esc(provider.id)}" aria-labelledby="${cardId(provider.id)}_title">
      <header class="conn-head"><h4 id="${cardId(provider.id)}_title" tabindex="-1">${esc(provider.label)}</h4><span class="set-badge set-badge-${status.kind}">${esc(status.label)}</span></header>
      ${provider.hint?`<p class="conn-use">${esc(provider.hint)}</p>`:''}
      ${keys}${envLine(provider,status)}
      <details class="conn-add"${view.add===provider.id?' open':''}><summary>${status.keys.length?'Ajouter une autre clé':'Ajouter une clé'}</summary>
        <form class="conn-form" data-conn-add="${esc(provider.id)}">
          <div class="conn-field"><label for="conn_${id}_name">Nom</label><input id="conn_${id}_name" name="name" maxlength="60" placeholder="Perso, Travail…" autocomplete="off"${busy}></div>
          <div class="conn-field"><label for="conn_${id}_value">Valeur</label><input id="conn_${id}_value" name="value" type="password" autocomplete="off" spellcheck="false" placeholder="${esc(provider.placeholder||'')}"${busy}></div>
          <button class="action small primary" type="submit"${busy}>Ajouter</button>
        </form></details>
    </article>`;
  }

  /* La section entière ; `view` : `{busy, confirm, add, replace, status, error}`. Pure (testée par node). */
  function html(state,view){
    const v=view||{};
    const providers=(state&&state.providers)||[];
    const status=v.status?esc(v.status):'',error=v.error?esc(v.error):'';
    return `<div class="conn">
      <p class="conn-lead">Les valeurs ne reviennent jamais à cette page : seuls les quatre derniers caractères d’une clé sont montrés. Chaque action est enregistrée tout de suite.</p>
      <div class="conn-live" id="connectionsStatus" role="status" aria-live="polite">${status}</div>
      <div class="conn-live conn-error" id="connectionsError" role="alert">${error}</div>
      <div class="conn-list">${providers.map(p=>card(state,p,v)).join('')}</div>
    </div>`;
  }

  /* `opts` : `request(path, init)` (l'`api` de la page : lève avec le message du serveur), `state` (état déjà lu,
     sinon lu ici), `isCurrent()` (faux dès que la section est quittée), `onState(state)` (la page garde l'état et vide
     ses catalogues), `log` (console par défaut), `waitMs` (délai d'attente, `WAIT_MS` par défaut). Renvoie
     `{destroy, destroyed, load}`. */
  function create(host,options){
    const opts=options||{};
    const request=opts.request;
    const log=opts.log||root.console;
    const waitMs=opts.waitMs||WAIT_MS;
    const alive=()=>!dead&&(!opts.isCurrent||opts.isCurrent());
    let dead=false,state=opts.state||null,timer=null,ticket=0;
    const view={busy:false,confirm:null,add:null,replace:null,status:'',error:''};

    function render(focus){
      if(!alive())return;
      if(!state){host.innerHTML='<div class="conn"><p class="conn-lead" role="status">Chargement des fournisseurs…</p></div>';return}
      host.innerHTML=html(state,view);
      bind();
      if(focus){const el=host.querySelector(focus);if(el)el.focus({preventScroll:false})}
    }
    function bind(){
      host.querySelectorAll('form[data-conn-add]').forEach(f=>f.addEventListener('submit',e=>{e.preventDefault();add(f)}));
      host.querySelectorAll('form[data-conn-replace]').forEach(f=>f.addEventListener('submit',e=>{e.preventDefault();replace(f)}));
      host.querySelectorAll('[data-bind-provider]').forEach(r=>r.addEventListener('change',()=>{if(r.checked)bindKey(r)}));
      host.querySelectorAll('[data-conn-delete]').forEach(b=>b.addEventListener('click',()=>{
        view.confirm=b.dataset.connDelete;view.error='';render(`[data-conn-delete-confirm="${CSS.escape(view.confirm)}"]`)}));
      host.querySelectorAll('[data-conn-delete-cancel]').forEach(b=>b.addEventListener('click',()=>{
        const id=view.confirm;view.confirm=null;render(id?`[data-conn-delete="${CSS.escape(id)}"]`:null)}));
      host.querySelectorAll('[data-conn-delete-confirm]').forEach(b=>b.addEventListener('click',()=>remove(b.dataset.connDeleteConfirm)));
      /* Une divulgation ouverte reste ouverte au prochain rendu. */
      host.querySelectorAll('details.conn-add').forEach(d=>d.addEventListener('toggle',()=>{
        const p=d.closest('[data-conn-provider]').dataset.connProvider;
        if(d.open)view.add=p;else if(view.add===p)view.add=null}));
      host.querySelectorAll('details.conn-replace').forEach(d=>d.addEventListener('toggle',()=>{
        const k=d.closest('[data-conn-key]').dataset.connKey;
        if(d.open)view.replace=k;else if(view.replace===k)view.replace=null}));
    }
    function labelOf(provider){const p=((state&&state.providers)||[]).find(x=>x.id===provider);return p?p.label:provider}

    /* Une écriture : la carte se fige, l'attente se dit, l'issue se dit ; jamais la valeur. */
    async function write(action,path,payload,messages){
      const mine=++ticket;
      view.busy=true;view.error='';view.status=messages.pending;render();
      clearTimeout(timer);
      timer=setTimeout(()=>{
        if(mine!==ticket)return;
        log.warn('connections_credential_slow',{action,waited_ms:waitMs});
        view.busy=false;view.status='';
        view.error=`Pas de réponse du Control Center après ${Math.round(waitMs/1000)} s : l’action n’est peut-être pas enregistrée. Rouvrez la section pour relire l’état.`;
        render();
      },waitMs);
      try{
        const result=await request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const next={providers:result.providers,credentials:result.credentials,bindings:result.bindings,environment:result.environment};
        if(opts.onState)opts.onState(next);
        log.info('connections_credential_written',{action,provider:payload.provider||null});
        if(dead||mine!==ticket)return;
        clearTimeout(timer);timer=null;
        state=next;view.busy=false;view.confirm=null;view.status=messages.done(next);
        return next;
      }catch(e){
        log.error('connections_credential_failed',{action,code:e&&e.code||'',status:e&&e.status||0});
        if(dead||mine!==ticket)return;
        clearTimeout(timer);timer=null;
        view.busy=false;view.status='';view.error=`${messages.failed} ${e&&e.message||String(e)}`;
        render();
        return null;
      }
    }

    /* La valeur est lue puis effacée du champ avant tout envoi : elle ne reste dans aucun DOM. */
    function takeSecret(form){const input=form.elements.value,value=input.value;input.value='';return value}

    async function add(form){
      const provider=form.dataset.connAdd,name=form.elements.name.value,value=takeSecret(form);
      const label=labelOf(provider);
      const next=await write('add',ROUTES.save,{provider,name,value},{pending:`Enregistrement de la clé ${label}…`,
        done:()=>`Clé « ${name.trim()} » ajoutée pour ${label}.`,failed:`Clé ${label} non enregistrée :`});
      if(!next){const again=host.querySelector(`form[data-conn-add="${CSS.escape(provider)}"] [name=name]`);if(again&&alive()){again.value=name;again.focus()}return}
      if(!alive())return;
      view.add=null;
      const fresh=next.credentials.find(c=>c.provider===provider&&c.name===name.trim());
      render(fresh?`[data-bind-id="${CSS.escape(fresh.id)}"]`:`#${cardId(provider)}_title`);
    }
    async function replace(form){
      const id=form.dataset.connReplace,provider=form.dataset.provider,value=takeSecret(form);
      const key=(state.credentials||[]).find(c=>c.id===id);
      if(!key){view.error='Cette clé n’existe plus.';render();return}
      if(!value.trim()){view.error='Collez la nouvelle valeur avant de remplacer.';render(`#conn_replace_${slug(id)}`);return}
      const label=labelOf(provider);
      const next=await write('replace',ROUTES.save,{id,provider,name:key.name,value},{pending:`Remplacement de la clé « ${key.name} »…`,
        done:()=>`Valeur de « ${key.name} » remplacée pour ${label}.`,failed:`Valeur de « ${key.name} » non remplacée :`});
      if(!next||!alive())return;
      view.replace=null;
      render(`[data-bind-id="${CSS.escape(id)}"]`);
    }
    async function remove(id){
      const key=(state.credentials||[]).find(c=>c.id===id);
      const provider=key?key.provider:'',name=key?key.name:id;
      const next=await write('delete',ROUTES.remove,{id},{pending:`Suppression de « ${name} »…`,
        done:()=>`Clé « ${name} » supprimée.`,failed:`Clé « ${name} » non supprimée :`});
      if(!next||!alive())return;
      render(`#${cardId(provider)}_title`);
    }
    async function bindKey(radio){
      const provider=radio.dataset.bindProvider,id=radio.dataset.bindId;
      const key=(state.credentials||[]).find(c=>c.id===id);
      const next=await write('bind',ROUTES.bind,{provider,id},{pending:`Activation de « ${key?key.name:id} »…`,
        done:()=>`« ${key?key.name:id} » est maintenant la clé ${labelOf(provider)} utilisée par JARVIS.`,failed:'Clé active inchangée :'});
      if(!next||!alive())return;
      render(`[data-bind-id="${CSS.escape(id)}"]`);
    }

    async function load(){
      if(state){render();return}
      render();
      try{
        const value=await request(ROUTES.read);
        if(opts.onState)opts.onState(value);
        state=value;render();
      }catch(e){
        log.error('connections_read_failed',{code:e&&e.code||'',status:e&&e.status||0});
        if(alive())host.innerHTML=`<div class="conn"><div class="conn-live conn-error" role="alert">Fournisseurs illisibles : ${esc(e&&e.message||String(e))}</div></div>`;
      }
    }

    const api={destroy(){dead=true;clearTimeout(timer);timer=null},get destroyed(){return dead},load};
    return api;
  }

  const exported=Object.freeze({html,create,providerStatus,ROUTES,WAIT_MS,cardId});
  root.JarvisConnectionsSettings=exported;
  if(typeof module!=='undefined'&&module.exports)module.exports=exported;
})(typeof window!=='undefined'?window:globalThis);
