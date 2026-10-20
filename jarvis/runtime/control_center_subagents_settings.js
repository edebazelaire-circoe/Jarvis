/* Onglet Réglages « Sous-agents » (jarvis-organic-agent-orchestration, Slice 10).

   Rend le registre des rôles servi par `GET /api/subagent-roles` (`schema_version` 2) : liste des rôles,
   fiche détaillée (mission, capacités, savoirs, Work Methods, ordre de la consigne apposée), et les instances
   en cours lues dans `GET /api/agent/tasks` (champ `role`, le marqueur tel que le hook le lit).

   Une seule écriture : les instructions d'un rôle, par la voie canonique des prompts
   `POST /api/prompts/subagent_role.<id>` (`edit` avec `base_revision` + `expected_effective_revision`,
   ou `reset`). Tout le reste est en lecture seule et le dit : capacités et méthodes suivent le code.

   Identité visuelle : `visual.icon` / `visual.accent` / `visual.badge` sont des JETONS. L'accent devient la
   variable CSS `--role-accent-<jeton>` (définie dans `control_center.html`, partagée avec le graphe), jamais
   une couleur écrite ici ; l'icône et le badge la doublent toujours, l'identité ne repose pas sur la couleur.

   Échecs : chaque refus est affiché dans la zone concernée (texte et code du serveur) et journalisé en console
   (`console.error('<code>', erreur)`), comme le reste du Control Center ; le serveur journalise de son côté
   `prompt.override.rejected`. Chaque attente porte un compteur et une échéance (`timeoutMs`).
   Point de montage : `#subagentSettingsMount` (créé par l'onglet). Contrat : `docs/subagent-roles.md` § 8. */
(function(root){
  'use strict';
  const MOUNT_ID='subagentSettingsMount';
  const ROLES_PATH='/api/subagent-roles';
  const TASKS_PATH='/api/agent/tasks';
  const PROMPT_PATH=id=>'/api/prompts/'+encodeURIComponent(id);
  const DEFAULT_TIMEOUT_MS=15000;
  const CONFLICT_CODES=new Set(['prompt_override_concurrent','prompt_override_stale']);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const TOKEN=/^[a-z][a-z0-9-]{0,31}$/;

  /* Pictogrammes dessinés (trait 1,7, grille 24) pour les jetons `visual.icon` du registre. Un jeton inconnu
     prend la silhouette générique : le badge reste lisible à côté. */
  const ICONS={
    question:'<circle cx="12" cy="12" r="9.5"/><path d="M9.2 9.2a2.9 2.9 0 0 1 5.6 1c0 1.9-2.8 2.6-2.8 4.3"/><path d="M12 17.6h.01"/>',
    book:'<path d="M5 19.2A2.2 2.2 0 0 1 7.2 17H19"/><path d="M7.2 3H19v18H7.2A2.2 2.2 0 0 1 5 18.8V5.2A2.2 2.2 0 0 1 7.2 3z"/>',
    globe:'<circle cx="12" cy="12" r="9.5"/><path d="M2.5 12h19"/><path d="M12 2.5a14.5 14.5 0 0 1 3.8 9.5 14.5 14.5 0 0 1-3.8 9.5 14.5 14.5 0 0 1-3.8-9.5A14.5 14.5 0 0 1 12 2.5z"/>',
    code:'<path d="M15.5 17.5 21 12l-5.5-5.5"/><path d="M8.5 6.5 3 12l5.5 5.5"/>',
    lightbulb:'<path d="M9 18h6"/><path d="M10 21.5h4"/><path d="M15 14.5c.2-1 .7-1.7 1.4-2.4A5.5 5.5 0 1 0 6.5 8c0 1.2.4 2.5 1.6 3.8.7.8 1.2 1.6 1.4 2.7"/>',
    compass:'<circle cx="12" cy="12" r="9.5"/><path d="m15.8 8.2-2.1 5.5-5.5 2.1 2.1-5.5z"/>',
    'shield-check':'<path d="M12 21.5s7.5-3.6 7.5-9.4V5.4L12 2.5 4.5 5.4v6.7c0 5.8 7.5 9.4 7.5 9.4z"/><path d="m8.8 12 2.2 2.2 4.2-4.4"/>',
    agent:'<circle cx="12" cy="8" r="3.8"/><path d="M4.5 20.5v-.8a6 6 0 0 1 6-6h3a6 6 0 0 1 6 6v.8"/>',
    unknown:'<circle cx="12" cy="12" r="9.5" stroke-dasharray="3 2.4"/><path d="M12 7.6v5.2"/><path d="M12 16.4h.01"/>',
  };
  function icon(name){
    const body=ICONS[name]||ICONS.agent;
    return `<svg class="sar-glyph" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
  }

  function logError(code,error,context){try{root.console&&root.console.error(code,error,context||{})}catch(_e){/* intentionnel : la console absente (test node sans console) ne doit pas masquer l'erreur déjà affichée */}}
  function logInfo(code,data){try{root.console&&root.console.info(code,data||{})}catch(_e){/* intentionnel : même argument que logError */}}

  function create(host,options){
    const opts=options||{};
    const timeoutMs=Number(opts.timeoutMs)>0?Number(opts.timeoutMs):DEFAULT_TIMEOUT_MS;
    const now=typeof opts.now==='function'?opts.now:()=>Date.now();
    const setTimer=opts.setInterval||((fn,ms)=>root.setInterval?root.setInterval(fn,ms):null);
    const clearTimer=opts.clearInterval||(id=>{if(id!=null&&root.clearInterval)root.clearInterval(id)});
    const fetchJson=opts.fetch||(async(path,init)=>{
      const controller=typeof root.AbortController==='function'?new root.AbortController():null;
      const timer=controller&&root.setTimeout?root.setTimeout(()=>controller.abort(),timeoutMs):null;
      let r;
      try{r=await root.fetch(path,{...(init||{}),signal:controller?controller.signal:undefined})}
      catch(e){
        if(e&&e.name==='AbortError'){const t=new Error(`Pas de réponse du Control Center après ${Math.round(timeoutMs/1000)} s.`);t.code='subagent_settings_timeout';throw t}
        const t=new Error('Control Center injoignable : '+(e&&e.message||e));t.code='subagent_settings_unreachable';throw t;
      }finally{if(timer!=null&&root.clearTimeout)root.clearTimeout(timer)}
      const text=await r.text();let body={};try{body=text?JSON.parse(text):{}}catch{body={error:text}}
      if(!r.ok||body.ok===false){
        const envelope=body&&typeof body.error==='object'&&body.error?body.error:null;
        const e=new Error((envelope&&envelope.message)||(typeof body.error==='string'&&body.error)||body.message||('HTTP '+r.status));
        e.status=r.status;e.code=(r.headers&&r.headers.get&&r.headers.get('X-Jarvis-Error-Code'))||(envelope&&envelope.code)||body.code||'';throw e;
      }
      return body;
    });

    const st={
      phase:'loading',error:null,payload:null,selected:null,
      /* Brouillons partageables avec la page (`options.drafts`) : changer d'onglet ne perd pas un texte non enregistré. */
      drafts:opts.drafts&&typeof opts.drafts==='object'?opts.drafts:{},openEditor:{},confirmReset:null,
      save:null,                 // {id, action, startedAt}
      notice:{},                 // id -> {tone,text,code}
      tasks:{phase:'loading',error:null,items:[]},
      startedAt:now(),destroyed:false,
    };
    let ticker=null;
    const warnedAccent=new Set();

    /* --- lecture du registre ------------------------------------------- */
    const roles=()=>(st.payload&&st.payload.roles)||[];
    const roleById=id=>roles().find(r=>r.id===id)||null;
    const methodById=id=>((st.payload&&st.payload.work_methods)||[]).find(m=>m.method_id===id)||null;
    const relationLabel=k=>((st.payload&&st.payload.relation_labels)||{})[k]||k;
    function accentOf(role){
      const token=role&&role.visual&&role.visual.accent;
      const known=(st.payload&&st.payload.accents)||[];
      if(TOKEN.test(String(token||''))&&known.includes(token))return token;
      if(role&&!warnedAccent.has(role.id)){warnedAccent.add(role.id);logError('subagent_settings_unknown_accent',new Error(`jeton d'accent inconnu : ${token}`),{role_id:role.id})}
      return 'slate';
    }
    const accentStyle=token=>`--sar-accent:var(--role-accent-${token})`;
    const draftOf=role=>Object.prototype.hasOwnProperty.call(st.drafts,role.id)?st.drafts[role.id]:role.instructions;
    const isDirty=role=>Object.prototype.hasOwnProperty.call(st.drafts,role.id)&&st.drafts[role.id]!==role.instructions;

    /* Le marqueur d'une instance (`role` de `/api/agent/tasks`) résolu comme `subagent_roles.resolve_role`. */
    function resolveMarker(marker){
      const m=String(marker??'').trim().toLowerCase();
      if(!m)return {status:'undeclared',role:null,marker:''};
      const aliases=(st.payload&&st.payload.aliases)||{};
      const direct=roles().find(r=>(r.marker||r.id)===m);
      if(direct)return {status:direct.enabled?'declared':'disabled',role:direct,marker:m};
      if(aliases[m]){const target=roleById(aliases[m]);if(target)return {status:'alias',role:target,marker:m}}
      return {status:'unknown',role:null,marker:m.slice(0,24)};
    }

    /* --- rendu ----------------------------------------------------------- */
    function elapsed(since){return Math.max(0,Math.floor((now()-since)/1000))}
    function waitingHtml(label,since){
      return `<div class="sar-wait" role="status"><span class="sar-spin" aria-hidden="true"></span><span>${esc(label)}</span>
        <span class="sar-elapsed" data-sar-since="${since}">${elapsed(since)} s</span><span class="hint">abandon après ${Math.round(timeoutMs/1000)} s</span></div>`;
    }
    function codeLine(code){return code?`<div class="hint sar-code">Code : <code>${esc(code)}</code></div>`:''}
    function chip(text,tone,title){return `<span class="tag${tone?' '+tone:''}"${title?` title="${esc(title)}"`:''}>${esc(text)}</span>`}
    function identity(role,size){
      const token=accentOf(role),v=role.visual||{};
      return `<span class="sar-ident sar-${size}" style="${accentStyle(token)}"><span class="sar-tile">${icon(v.icon)}</span><span class="sar-badge">${esc(v.badge||'?')}</span></span>`;
    }
    function availability(role){
      if(!role.enabled)return chip('Désactivé','bad','Le hook ne reconnaît pas ce rôle : son marqueur reste dans le libellé.');
      return '';
    }
    function listItem(role){
      const sel=role.id===st.selected;
      const tags=[availability(role),role.modified?chip('modifié','warn'):'',isDirty(role)?chip('non enregistré','warn'):'',role.conflict?chip('surcharge écartée','bad'):''].join('');
      return `<li><button type="button" class="sar-item${sel?' selected':''}${role.enabled?'':' off'}" data-sar-role="${esc(role.id)}" aria-current="${sel?'true':'false'}" tabindex="${sel?'0':'-1'}">
        ${identity(role,'sm')}<span class="sar-item-text"><span class="sar-item-name">${esc(role.name)}</span><span class="sar-item-meta"><code>[${esc(role.marker||role.id)}]</code>${tags}</span></span></button></li>`;
    }
    function yesNo(value,yes,no){return `<span class="sar-yn ${value?'yes':'no'}">${esc(value?yes:no)}</span>`}
    function facts(rows){return `<dl class="sar-facts">${rows.filter(Boolean).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`}

    function methodHtml(id,isDefault){
      const m=methodById(id);
      if(!m)return `<li class="sar-method missing"><span class="tag bad">méthode introuvable</span> <code>${esc(id)}</code></li>`;
      const list=(title,items)=>items&&items.length?`<div class="sar-mlist"><span class="sar-mlabel">${esc(title)}</span><ul>${items.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></div>`:'';
      const rel=(m.useful_relations||[]).length?`<div class="sar-mlist"><span class="sar-mlabel">Relations à envisager</span><p>${(m.useful_relations||[]).map(k=>esc(relationLabel(k))).join(', ')}</p></div>`:'';
      return `<li class="sar-method${isDefault?' default':''}"><details><summary><span class="sar-mname">${esc(m.name)}</span>${isDefault?chip('par défaut, apposée','ok'):chip('suggestion')}<code class="sar-mkey">${esc(m.method_id)}@${esc(m.version)}</code></summary>
        <p class="sar-msummary">${esc(m.summary)}</p>${list('Principes',m.principles)}${list('Critères de qualité',m.quality_checks)}${rel}
        <p class="hint">Des réflexes, pas des étapes : l'agent organise son travail selon ce qu'il découvre.</p></details></li>`;
    }

    function compositionHtml(role){
      const m=role.default_work_method?methodById(role.default_work_method):null;
      return `<ol class="sar-compose" aria-label="Ordre de la consigne apposée par JARVIS">
        <li><span class="sar-step">Vos instructions</span>${chip('modifiable','ok')}<span class="hint">Le texte ci-dessous, ou le défaut du code s'il n'est pas modifié.</span></li>
        <li><span class="sar-step">Capacités du rôle</span>${chip('générées')}<span class="hint">${role.can_spawn?'Peut lancer des agents, avec la liste des rôles qu’il peut demander.':'« Vous ne lancez aucun autre agent », prioritaire sur la charte du chantier.'}</span></li>
        <li><span class="sar-step">Work Method par défaut</span>${m?chip('non modifiable'):chip('aucune')}<span class="hint">${m?`« ${esc(m.name)} » s’ajoute <strong>après</strong> vos instructions et suit le code : la modifier ici est impossible.`:'Ce rôle n’a pas de méthode par défaut : ses instructions sont sa méthode.'}</span></li></ol>`;
    }

    function editorHtml(role){
      const id=role.id,saving=st.save&&st.save.id===id,dirty=isDirty(role),text=draftOf(role);
      const n=st.notice[id];
      const notice=n?`<div class="notice ${n.tone==='bad'?'bad':n.tone==='ok'?'ok':''}" role="${n.tone==='bad'?'alert':'status'}" data-sar-notice>${esc(n.text)}${n.hint?`<div class="hint">${esc(n.hint)}</div>`:''}${codeLine(n.code)}</div>`:'';
      const conflict=role.conflict?`<div class="notice bad" role="status">Votre surcharge enregistrée est écartée (<code>${esc(role.conflict)}</code>) : le défaut du code s'applique. Enregistrez à nouveau pour la reprendre sur le nouveau défaut.</div>`:'';
      const confirming=st.confirmReset===id;
      const busy=!!st.save;
      const area=`textarea-${id}`;
      return `<section class="sar-block" aria-labelledby="sar-instr-${esc(id)}"><h4 id="sar-instr-${esc(id)}">Instructions ${role.modified?chip('modifiées','warn'):chip('défaut du code')}</h4>
        ${conflict}
        <details class="rd sar-editor" data-sar-editor="${esc(id)}"${st.openEditor[id]||dirty||n?' open':''}>
          <summary>Afficher et modifier les instructions <span class="hint" data-sar-count>(${text.length} caractères${dirty?', non enregistré':''})</span></summary>
          <label class="sar-label" for="${esc(area)}">Instructions du rôle ${esc(role.name)}</label>
          <textarea id="${esc(area)}" data-sar-text="${esc(id)}" spellcheck="true" rows="14" aria-describedby="${esc(area)}-h"${saving?' readonly':''}>${esc(text)}</textarea>
          <div class="hint" id="${esc(area)}-h">Enregistré dans la couche de prompt <code>${esc(role.prompt_id||'subagent_role.'+id)}</code>. S'applique au prochain sous-agent lancé avec ce rôle ; aucun agent en cours n'est modifié.</div>
          ${saving?waitingHtml(st.save.action==='reset'?'Retour au défaut…':'Enregistrement des instructions…',st.save.startedAt):''}
          ${notice}
          <div class="sar-actions">
            <button type="button" class="action primary" data-sar-save="${esc(id)}"${dirty&&!busy?'':' disabled'}>${saving&&st.save.action==='edit'?'Enregistrement…':'Enregistrer les instructions'}</button>
            <button type="button" class="action" data-sar-discard="${esc(id)}"${dirty&&!busy?'':' disabled'}>Annuler mes changements</button>
            <button type="button" class="action danger" data-sar-reset="${esc(id)}"${role.modified&&!busy?'':' disabled'}${confirming?' aria-describedby="sar-reset-h"':''}>${confirming?'Confirmer le retour au défaut':'Revenir au défaut'}</button>
            ${confirming?'<span class="hint" id="sar-reset-h">Votre texte enregistré sera remplacé par le défaut du code.</span>':''}
          </div>
        </details></section>`;
    }

    function detailHtml(role){
      if(!role)return '<div class="empty">Choisissez un rôle dans la liste.</div>';
      const token=accentOf(role);
      const marker=`[${role.default_profile||'general'}] [${role.marker||role.id}]`;
      const aliases=(role.aliases||[]).length?(role.aliases||[]).map(a=>`<code>[${esc(a)}]</code>`).join(' ')+' <span class="hint">alias historique, lu comme ce rôle</span>':'<span class="hint">aucun</span>';
      const tools=(role.tools||[]).length?(role.tools||[]).map(t=>`<code class="sar-tool">${esc(t)}</code>`).join(' '):'<span class="hint">aucun outil déclaré</span>';
      const skills=(role.skills||[]).length?(role.skills||[]).map(s=>`<code>${esc(s)}</code>`).join(' '):'<span class="hint">aucun skill propre</span>';
      const loadout=role.loadout_role?`loadout <code>${esc(role.loadout_role)}</code>`:'<span class="hint">celui du profil</span>';
      const methods=(role.work_methods||[]);
      const ordered=[...methods].sort((a,b)=>(b===role.default_work_method)-(a===role.default_work_method));
      const state=!role.enabled
        ?`<div class="notice bad" role="status"><strong>Rôle désactivé.</strong> Le hook ne le reconnaît pas : un sous-agent qui l'annonce garde le marqueur dans son libellé et suit seulement sa consigne.</div>`
        :(!role.offered_to_brain?`<div class="notice info" role="status">Actif pour le hook, mais <strong>pas encore proposé au cerveau</strong> : seul un agent qui lance des agents peut le demander.</div>`:'');
      return `<article class="sar-detail" style="${accentStyle(token)}" aria-labelledby="sar-title">
        <header class="sar-head">${identity(role,'lg')}<div><h3 id="sar-title" class="sar-title">${esc(role.name)}</h3>
          <p class="sar-desc">${esc(role.description||'')}</p>
          <div class="sar-tags">${role.enabled?chip('Actif','ok'):chip('Désactivé','bad')}${role.offered_to_brain?chip('Proposé au cerveau','ok'):chip('Pas proposé au cerveau')}${role.offered_to_subagents?chip('Proposé aux agents','ok'):chip('Pas proposé aux agents')}</div></div></header>
        ${state}
        <section class="sar-block" aria-labelledby="sar-mission"><h4 id="sar-mission">Mission</h4><p class="sar-prose">${esc(role.mission||'')}</p>
          ${role.when_relevant?`<p class="hint"><strong>Quand l'employer :</strong> ${esc(role.when_relevant)}</p>`:''}
          ${facts([['Marqueur',`<code>${esc(marker)}</code>`],['Alias',aliases],['Identifiant',`<code>${esc(role.id)}</code>`]])}</section>
        <section class="sar-block" aria-labelledby="sar-caps"><h4 id="sar-caps">Capacités ${chip('lecture seule')}</h4>
          ${facts([
            ['Lance des agents',yesNo(role.can_spawn,'Oui','Non')],
            ['Mission Owner',yesNo(role.can_own_mission,'Peut porter une mission','Ne porte pas de mission')],
            ['Réponse',role.constrained_output?'<span class="sar-yn yes">Forme imposée par ses instructions</span>':'<span class="sar-yn no">Libre</span>'],
            ['Outils',tools],['Savoirs',loadout],['Skills',skills],['Profil par défaut',`<code>${esc(role.default_profile||'general')}</code>`],
          ])}
          <p class="hint">Ces capacités suivent le code du registre ; aucun réglage ne les modifie.</p></section>
        <section class="sar-block" aria-labelledby="sar-methods"><h4 id="sar-methods">Work Methods ${chip('lecture seule')}</h4>
          ${methods.length?`<ul class="sar-methods">${ordered.map(id=>methodHtml(id,id===role.default_work_method)).join('')}</ul>`:'<p class="hint">Aucune Work Method : les instructions du rôle tiennent lieu de méthode.</p>'}
          ${methods.length&&!role.default_work_method?'<p class="hint">Aucune n’est apposée par défaut ; un Mission Owner pourra en choisir une.</p>':''}</section>
        <section class="sar-block" aria-labelledby="sar-compose"><h4 id="sar-compose">Consigne transmise au sous-agent</h4>${compositionHtml(role)}</section>
        ${editorHtml(role)}
      </article>`;
    }

    function instanceRow(task){
      const res=resolveMarker(task.role);
      const title=String(task.description||'').replace(/^(\s*\[[^\]]{1,40}\]\s*)+/,'')||'(sans libellé)';
      let ident,label;
      if(res.role){ident=identity(res.role,'sm');label=esc(res.role.name)+(res.status==='alias'?` <span class="hint">via l'alias <code>[${esc(res.marker)}]</code></span>`:'')+(res.status==='disabled'?' '+chip('désactivé','bad'):'')}
      else if(res.status==='unknown'){ident=`<span class="sar-ident sar-sm" style="${accentStyle('slate')}"><span class="sar-tile">${icon('unknown')}</span><span class="sar-badge">?</span></span>`;label=`Marqueur hors registre <code>[${esc(res.marker)}]</code>`}
      else{ident=`<span class="sar-ident sar-sm" style="${accentStyle('slate')}"><span class="sar-tile">${icon('agent')}</span><span class="sar-badge">GEN</span></span>`;label='Général <span class="hint">aucun rôle déclaré</span>'}
      return `<li class="sar-inst">${ident}<span class="sar-item-text"><span class="sar-item-name">${esc(title)}</span><span class="sar-item-meta">${label}${task.ephemeral?chip('éphémère'):''}</span></span></li>`;
    }
    function instancesHtml(){
      const t=st.tasks;
      let body;
      if(t.phase==='loading')body=waitingHtml('Lecture des instances…',t.startedAt||st.startedAt);
      else if(t.phase==='error')body=`<div class="notice bad" role="alert">Instances illisibles : ${esc(t.error.message)}${codeLine(t.error.code)}</div>`;
      else{
        const running=t.items.filter(x=>x&&x.status==='running'&&x.kind!=='shell');
        body=running.length?`<ul class="sar-list" aria-label="Instances en cours">${running.map(instanceRow).join('')}</ul>`:'<p class="hint">Aucun sous-agent en cours.</p>';
      }
      return `<section class="sar-instances" aria-labelledby="sar-inst-h"><div class="sar-inst-head"><h4 id="sar-inst-h">Instances en cours</h4>
        <button type="button" class="action" data-sar-tasks-refresh${t.phase==='loading'?' disabled':''}>Actualiser</button></div>${body}</section>`;
    }

    function summaryHtml(){
      const all=roles(),active=all.filter(r=>r.enabled).length,brain=all.filter(r=>r.enabled&&r.offered_to_brain).length,mod=all.filter(r=>r.modified).length;
      const schema=st.payload.schema_version!==2?`<div class="notice" role="status">Version de registre inattendue (<code>${esc(st.payload.schema_version)}</code>, attendu 2) : les champs absents s'affichent vides.</div>`:'';
      return `${schema}<p class="sar-summary">${all.length} rôles · ${active} actifs · ${brain} proposés au cerveau${mod?` · ${mod} aux instructions modifiées`:''}</p>`;
    }

    function render(){
      if(st.destroyed)return;
      if(st.phase==='loading'){host.innerHTML=`<div class="sar-state">${waitingHtml('Lecture du registre des rôles…',st.startedAt)}</div>`;tick();return}
      if(st.phase==='error'){
        host.innerHTML=`<div class="sar-state"><div class="notice bad" role="alert"><strong>Registre des rôles illisible.</strong> ${esc(st.error.message)}
          <div class="hint">Rien n'a été modifié. Vérifiez que le Control Center répond, puis réessayez.</div>${codeLine(st.error.code)}</div>
          <button type="button" class="action primary" data-sar-retry>Réessayer</button></div>`;
        bind();tick();return;
      }
      if(!roles().length){
        host.innerHTML=`<div class="sar-state">${summaryHtml()}<div class="notice bad" role="status"><strong>Aucun rôle dans le registre.</strong> Les sous-agents s'exécutent alors sans rôle, comme agents généraux.</div></div>`;
        tick();return;
      }
      if(!roleById(st.selected))st.selected=roles()[0].id;
      const scrollEl=host.querySelector('.sar-detail-pane'),scroll=scrollEl?scrollEl.scrollTop:0;
      host.innerHTML=`<div class="sar" data-subagent-settings="1">
        <div class="sar-side">${summaryHtml()}
          <ul class="sar-list" role="list" aria-label="Rôles de sous-agent" data-sar-list>${roles().map(listItem).join('')}</ul>
          <p class="hint">Flèches haut et bas pour parcourir les rôles.</p>
          ${instancesHtml()}</div>
        <div class="sar-detail-pane" role="region" aria-live="polite" aria-label="Fiche du rôle">${detailHtml(roleById(st.selected))}</div></div>`;
      const pane=host.querySelector('.sar-detail-pane');if(pane&&scroll)pane.scrollTop=scroll;
      bind();tick();
    }

    /* Compteur vivant des attentes : un seul minuteur, arrêté dès qu'aucune attente n'est affichée. */
    function tick(){
      const waiting=!st.destroyed&&(st.phase==='loading'||st.tasks.phase==='loading'||!!st.save);
      if(waiting&&ticker==null)ticker=setTimer(()=>{
        if(!host.querySelectorAll)return;
        host.querySelectorAll('[data-sar-since]').forEach(el=>{el.textContent=elapsed(Number(el.dataset.sarSince))+' s'});
      },1000);
      if(!waiting&&ticker!=null){clearTimer(ticker);ticker=null}
    }

    function select(id,focus){
      if(!roleById(id))return;
      st.selected=id;st.confirmReset=null;render();
      if(focus){const b=host.querySelector(`[data-sar-role="${id}"]`);if(b&&b.focus)b.focus()}
    }

    function bind(){
      if(!host.querySelectorAll)return;
      const retry=host.querySelector('[data-sar-retry]');if(retry)retry.addEventListener('click',()=>load());
      host.querySelectorAll('[data-sar-role]').forEach(b=>{
        b.addEventListener('click',()=>select(b.dataset.sarRole,true));
        b.addEventListener('keydown',ev=>{
          const ids=roles().map(r=>r.id),i=ids.indexOf(b.dataset.sarRole);
          const next={ArrowDown:i+1,ArrowUp:i-1,Home:0,End:ids.length-1}[ev.key];
          if(next===undefined)return;
          ev.preventDefault();select(ids[(next+ids.length)%ids.length],true);
        });
      });
      host.querySelectorAll('[data-sar-editor]').forEach(d=>d.addEventListener('toggle',()=>{st.openEditor[d.dataset.sarEditor]=d.open}));
      host.querySelectorAll('[data-sar-text]').forEach(area=>area.addEventListener('input',()=>{
        const role=roleById(area.dataset.sarText);if(!role)return;
        st.drafts[role.id]=area.value;
        const dirty=isDirty(role),busy=!!st.save;
        const count=host.querySelector('[data-sar-count]');if(count)count.textContent=`(${area.value.length} caractères${dirty?', non enregistré':''})`;
        const save=host.querySelector(`[data-sar-save="${role.id}"]`),discard=host.querySelector(`[data-sar-discard="${role.id}"]`);
        if(save)save.disabled=!dirty||busy;if(discard)discard.disabled=!dirty||busy;
      }));
      host.querySelectorAll('[data-sar-save]').forEach(b=>b.addEventListener('click',()=>save(b.dataset.sarSave)));
      host.querySelectorAll('[data-sar-discard]').forEach(b=>b.addEventListener('click',()=>{delete st.drafts[b.dataset.sarDiscard];delete st.notice[b.dataset.sarDiscard];render()}));
      host.querySelectorAll('[data-sar-reset]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarReset;
        if(st.confirmReset!==id){st.confirmReset=id;render();const again=host.querySelector(`[data-sar-reset="${id}"]`);if(again&&again.focus)again.focus();return}
        reset(id);
      }));
      const refresh=host.querySelector('[data-sar-tasks-refresh]');if(refresh)refresh.addEventListener('click',()=>loadTasks());
    }

    /* --- E/S ------------------------------------------------------------- */
    async function load(){
      st.phase='loading';st.error=null;st.startedAt=now();render();
      try{
        const data=await fetchJson(ROLES_PATH);
        if(!data||!Array.isArray(data.roles)){const e=new Error('réponse sans liste de rôles');e.code='subagent_settings_payload_invalid';throw e}
        if(st.destroyed)return data;
        st.payload=data;st.phase='ready';
        logInfo('subagent_settings.loaded',{roles:data.roles.length,schema_version:data.schema_version});
      }catch(e){
        if(st.destroyed)return null;
        st.phase='error';st.error=e;logError('subagent_settings_load_failed',e,{path:ROLES_PATH});
      }finally{render()}
      if(st.phase==='ready')loadTasks();
      return st.payload;
    }
    async function loadTasks(){
      st.tasks={phase:'loading',error:null,items:st.tasks.items,startedAt:now()};render();
      try{
        const data=await fetchJson(TASKS_PATH);
        if(st.destroyed)return;
        st.tasks={phase:'ready',error:null,items:Array.isArray(data&&data.tasks)?data.tasks:[]};
      }catch(e){
        if(st.destroyed)return;
        st.tasks={phase:'error',error:e,items:[]};logError('subagent_settings_tasks_failed',e,{path:TASKS_PATH});
      }finally{render()}
    }
    async function refreshRoles(){
      const data=await fetchJson(ROLES_PATH);
      if(data&&Array.isArray(data.roles))st.payload=data;
    }
    function snapshotNote(body){
      const snap=body&&body.subagent_roles_snapshot;
      if(snap&&snap.written===false)return {tone:'bad',text:'Enregistré, mais pas encore transmis aux sous-agents : le prochain lancé suivra l’ancienne version.',code:snap.code||'',hint:snap.error||''};
      return null;
    }
    async function mutate(id,action){
      const role=roleById(id);if(!role||st.save)return;
      const text=draftOf(role);
      st.save={id,action,startedAt:now()};st.confirmReset=null;delete st.notice[id];render();
      try{
        const body=action==='reset'?{action:'reset'}
          :{action:'edit',text,base_revision:role.default_revision,expected_effective_revision:role.revision};
        const result=await fetchJson(PROMPT_PATH(role.prompt_id||'subagent_role.'+id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        await refreshRoles();
        delete st.drafts[id];
        st.notice[id]=snapshotNote(result)||{tone:'ok',text:action==='reset'?'Instructions revenues au défaut du code.':'Instructions enregistrées. Elles s’appliquent au prochain sous-agent lancé avec ce rôle.'};
        logInfo('subagent_settings.instructions_'+action,{role_id:id,changed:!!(result&&result.mutation&&result.mutation.changed)});
      }catch(e){
        if(CONFLICT_CODES.has(e.code)){
          /* Conflit de révision : la version enregistrée a changé ailleurs. Le texte de l'utilisateur reste dans le
             champ ; les révisions sont relues pour qu'un second enregistrement, voulu, réussisse. */
          try{await refreshRoles()}catch(again){logError('subagent_settings_refresh_failed',again,{role_id:id})}
          if(action==='edit')st.drafts[id]=text;
          st.notice[id]={tone:'bad',code:e.code,text:e.code==='prompt_override_stale'
            ?'Le défaut de ce rôle a changé depuis l’ouverture de l’écran. Votre texte est conservé dans le champ.'
            :'Ces instructions ont été modifiées ailleurs depuis l’ouverture de l’écran. Votre texte est conservé dans le champ.',
            hint:'La version enregistrée a été relue. Relisez votre texte, puis enregistrez à nouveau pour la remplacer, ou annulez vos changements pour la garder.'};
        }else{
          if(action==='edit')st.drafts[id]=text;
          st.notice[id]={tone:'bad',code:e.code||'',text:(action==='reset'?'Retour au défaut refusé : ':'Enregistrement refusé : ')+(e.message||'erreur sans message')+' Rien n’a été écrit.'};
        }
        logError(action==='reset'?'subagent_settings_reset_failed':'subagent_settings_save_failed',e,{role_id:id,code:e.code||null});
      }finally{
        st.save=null;st.openEditor[id]=true;render();
        const n=host.querySelector&&host.querySelector('[data-sar-notice]');if(n&&n.focus){n.tabIndex=-1;n.focus()}
      }
    }
    const save=id=>mutate(id,'edit');
    const reset=id=>mutate(id,'reset');

    function destroy(){st.destroyed=true;if(ticker!=null){clearTimer(ticker);ticker=null}}
    function hasUnsaved(){return roles().some(isDirty)}

    host.setAttribute&&host.setAttribute('data-subagent-settings-host','1');
    render();
    return {load,loadTasks,render,save,reset,select,destroy,hasUnsaved,resolveMarker,state:st};
  }

  root.JarvisSubagentSettings=Object.freeze({mountId:MOUNT_ID,ICONS:Object.freeze(Object.keys(ICONS)),create,
    mount:()=>root.document?root.document.getElementById(MOUNT_ID):null,
    async show(host,options){const view=create(host,options);await view.load();return view}});
})(typeof window!=='undefined'?window:globalThis);
