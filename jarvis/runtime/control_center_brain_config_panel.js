/* Fenêtre flottante de configuration d'un cerveau (Réglages › Architecture & Agents › Architecture)
   (jarvis-architecture-agents-settings-editor, Slice 05). Doc : `docs/settings/brain-config-panel.md`.

   Ouverte depuis le canevas (`onConfigureBrain(nodeId, detail)` de `control_center_architecture_settings.js`),
   elle flotte au-dessus du graphe, qui reste visible ; sous 720 px elle devient un panneau en bas d'écran.
   Il n'y a JAMAIS d'onglet « Cerveau » : c'est la seule surface de configuration d'un cerveau.

   Le composant est une projection du descripteur servi par le runtime (contrat `docs/brain-config.md`) :

     load(brainId)          -> descripteur        (lève une erreur `.code` sinon, `.config` éventuel)
     patch(brainId, body)   -> {ok:true, changed, applies, config} | {ok:false, status, code, reason, field, config}

   Il n'affiche que les champs que le descripteur expose, avec leurs choix, leur `editable`, leur `reason` et leur
   `applies` ; aucun nom de modèle, aucune topologie, aucun identifiant de cerveau n'est écrit ici. Une écriture
   = un PATCH d'un champ (seul le couple CLI + modèle de Core va ensemble) ; « Appliquer » envoie le brouillon en
   PATCH successifs, chacun avec la révision renvoyée par le précédent, et s'arrête au premier refus. Après chaque
   réponse, la fenêtre montre la `config` renvoyée ; un refus sans `config`, ou une issue inconnue (transport),
   force une relecture. Le brouillon non envoyé n'est jamais perdu en silence.

   Montage : `JarvisBrainConfigPanel.open(host, {adapter, brainId, field, onFocusConnection, ...})` rend le
   contrôleur de LA fenêtre (une seule à la fois ; rouvrir sur un autre cerveau la remplace, avec confirmation
   si un brouillon est en cours). `close()` ferme (garde du brouillon), `destroy()` démonte sans condition. Le style
   est injecté une fois (`#jarvisBrainConfigPanelStyle`) et ne contient que des jetons du thème. */
(function(root){
  'use strict';
  const STYLE_ID='jarvisBrainConfigPanelStyle';
  const DEFAULT_TIMEOUT_MS=15000;
  const MOVE_STEP=16,EDGE=8,WIN_W=460;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const own=(o,k)=>!!o&&Object.prototype.hasOwnProperty.call(o,k);
  const clone=v=>v==null?v:JSON.parse(JSON.stringify(v));

  /* Vocabulaire d'affichage des valeurs stables du contrat ; une valeur inconnue s'affiche telle quelle. */
  const APPLIES={live:'immédiatement',next_turn:'au prochain tour',core_restart:'au prochain démarrage de Core',voice_restart:'au prochain démarrage de la voix'};
  const appliesText=a=>APPLIES[a]||(a?'selon « '+a+' »':'');
  const STATE={active:['Actif','ok'],inactive:['Inactif','off'],shadow:['Observation','shadow'],unavailable:['Indisponible','bad']};
  const CHANNEL={audio:'audio',request:'requête',response:'réponse',tool_call:'appel d’outil',event:'événement',speech:'parole'};
  const MUTABILITY={required_locked:['Obligatoire','lock'],toggleable:['Modifiable sur le graphe','toggle'],
    creatable_removable:['Supprimable sur le graphe','plug'],governed:['Suit un réglage du cerveau','governed']};
  const FIELD_LABEL={delegation:'Tendance de délégation',provider:'CLI du cerveau',model:'Modèle',activation:'Activation',instructions:'Instructions'};
  const UNKNOWN_OUTCOME=new Set(['brain_config_timeout','brain_config_unreachable']);
  const PROMPT_CONFLICT=new Set(['prompt_override_stale','prompt_override_concurrent']);
  /* Conflits de révision (par code, pas par statut : `brain_config_brain_absent` est aussi un 409). */
  const CONFLICT=new Set(['brain_config_revision_stale',...PROMPT_CONFLICT]);
  /* Ordre d'envoi du brouillon : un PATCH par étape. Les instructions passent en dernier : c'est le champ dont
     la révision propre (`effective_revision`) est la plus susceptible d'être périmée. */
  const STEPS=[{id:'delegation',fields:['delegation']},{id:'model',fields:['provider','model']},{id:'activation',fields:['activation']},{id:'instructions',fields:['instructions']}];
  const SUBAGENTS_TAB='subagents';
  const ACCENTS=['violet','sky','lime','teal','amber','rose','indigo','orange','cyan'];

  const G={
    brain:'<path d="M9.5 4.5a2.8 2.8 0 0 0-2.8 2.8v.4A2.9 2.9 0 0 0 4.5 10.5a2.9 2.9 0 0 0 1.1 4.4 2.9 2.9 0 0 0 3.9 4 2 2 0 0 0 2.5-1.6V6.2a2 2 0 0 0-2.5-1.7Z"/><path d="M14.5 4.5a2.8 2.8 0 0 1 2.8 2.8v.4a2.9 2.9 0 0 1 2.2 2.8 2.9 2.9 0 0 1-1.1 4.4 2.9 2.9 0 0 1-3.9 4A2 2 0 0 1 12 17.3"/><path d="M8.5 10.5h1.8M13.7 13.5h1.8"/>',
    lock:'<rect x="5.5" y="10.5" width="13" height="9" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    close:'<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    grip:'<circle cx="9" cy="6.5" r="1.2" fill="currentColor"/><circle cx="15" cy="6.5" r="1.2" fill="currentColor"/><circle cx="9" cy="12" r="1.2" fill="currentColor"/><circle cx="15" cy="12" r="1.2" fill="currentColor"/><circle cx="9" cy="17.5" r="1.2" fill="currentColor"/><circle cx="15" cy="17.5" r="1.2" fill="currentColor"/>',
    target:'<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="2.5"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3"/>',
    in:'<path d="M20 12H6M11 7l-5 5 5 5"/>',
    out:'<path d="M4 12h14M13 7l5 5-5 5"/>',
    toggle:'<rect x="3" y="7.5" width="18" height="9" rx="4.5"/><circle cx="16.5" cy="12" r="2.4" fill="currentColor"/>',
    plug:'<path d="M9 3.5V8M15 3.5V8M7 8h10v2.8a5 5 0 0 1-10 0ZM12 15.8v4.7"/>',
    governed:'<path d="M14 4.5h5.5V10M19.5 4.5 12 12"/><path d="M18 14v4.5a1 1 0 0 1-1 1H5.5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1H10"/>',
    clock:'<circle cx="12" cy="12" r="8"/><path d="M12 8v4.2l2.8 1.8"/>',
    check:'<path d="M5 12.5l4.2 4.2L19 7"/>',
    warn:'<path d="M12 4 2.8 19.5h18.4Z"/><path d="M12 10v4.2M12 17v.2"/>',
    info:'<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.2"/>',
    arrow:'<path d="M5 12h14M14 7l5 5-5 5"/>',
  };
  const glyph=(name,cls)=>`<svg class="${cls||'bcp-g'}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${G[name]||G.info}</svg>`;

  function logError(code,error,context){
    try{root.console&&root.console.error(code,error,context||{})}catch(_e){/* intentionnel : console absente, l'erreur est déjà à l'écran */}
    try{if(typeof root.obsClientLog==='function')root.obsClientLog('error','ERROR',code,{message:String(error&&error.message||error),...(context||{})})}
    catch(_e){/* intentionnel : le journal ne doit pas casser la fenêtre */}
  }
  function logInfo(code,data){try{root.console&&root.console.info(code,data||{})}catch(_e){/* intentionnel : idem */}}
  function codedError(code,message,extra){const e=new Error(message);e.code=code;return Object.assign(e,extra||{})}
  function withDeadline(promise,ms,what){
    let timer=null;
    const guard=new Promise((_ok,ko)=>{timer=setTimeout(()=>ko(codedError('brain_config_timeout',`Pas de réponse pour « ${what} » après ${Math.round(ms/1000)} s.`)),ms)});
    return Promise.race([Promise.resolve().then(()=>promise),guard]).finally(()=>clearTimeout(timer));
  }
  /* Même teinte que le nœud du canevas : `visual.accent` sinon dérivée de `brain_type` (même formule). */
  function accentFor(config,token){
    if(token&&ACCENTS.includes(token))return token;
    const key=String(config&&(config.brain_type||config.brain_id)||'');let h=0;for(const ch of key)h=(h*31+ch.charCodeAt(0))>>>0;
    return ACCENTS[h%3];
  }
  /* Valeur canonique d'un champ, comparable à un brouillon. */
  function serverValue(config,field){
    const f=config&&config.fields&&config.fields[field];
    if(!f)return undefined;
    return field==='instructions'?String(f.value??''):f.value;
  }

  /* La fenêtre en cours : une seule à la fois, toutes sources confondues. */
  let current=null;

  function open(host,options){
    const opts=options||{};
    if(!opts.adapter||typeof opts.adapter.load!=='function'||typeof opts.adapter.patch!=='function')
      throw codedError('brain_config_adapter_missing','Adaptateur de configuration du cerveau absent ou incomplet.');
    if(!opts.brainId)throw codedError('brain_config_brain_missing','Aucun cerveau à configurer.');
    if(current&&current.host!==host){current.destroy()}
    if(!current||current.state.destroyed)current=createWindow(host,opts);
    current.show(opts.brainId,opts);
    return current;
  }

  function createWindow(hostArg,firstOpts){
    if(!hostArg)throw codedError('brain_config_mount_missing','Aucun hôte pour la fenêtre du cerveau.');
    /* Le canevas réécrit son hôte à chaque rendu : la fenêtre ne s'y monte jamais, elle se pose à côté. */
    const host=hostArg.hasAttribute&&hostArg.hasAttribute('data-architecture-settings-host')&&hostArg.parentNode?hostArg.parentNode:hostArg;
    const doc=host.ownerDocument||root.document||null;
    const now=typeof firstOpts.now==='function'?firstOpts.now:()=>Date.now();
    const setTimer=firstOpts.setInterval||((fn,ms)=>root.setInterval?root.setInterval(fn,ms):null);
    const clearTimer=firstOpts.clearInterval||(id=>{if(id!=null&&root.clearInterval)root.clearInterval(id)});
    const uid='bcp'+Math.random().toString(36).slice(2,8);
    let opts=firstOpts;
    const st={
      brainId:null,field:null,config:null,phase:'loading',loadError:null,since:now(),
      saving:null,              // {what, since}
      error:null,               // {code, reason, field, status, title}
      draft:{},                 // champ -> valeur non envoyée
      saved:{},                 // étape -> {applies, changed}
      conflict:null,            // {text} : texte relu du serveur après un conflit d'instructions
      confirm:null,             // {kind:'close'|'replace', next}
      notice:null,              // {tone, text}
      live:'',pos:null,destroyed:false,
    };
    let ticker=null,origin=null,drag=null,generation=0;
    const layer=doc&&doc.createElement?doc.createElement('div'):null;
    if(!layer)throw codedError('brain_config_mount_missing','Document indisponible pour la fenêtre du cerveau.');
    layer.className='bcp-layer';
    layer.setAttribute('data-brain-config-layer','1');
    ensureStyle();
    host.appendChild(layer);

    const adapter=()=>opts.adapter;
    const timeoutMs=()=>Number(opts.timeoutMs)>0?Number(opts.timeoutMs):DEFAULT_TIMEOUT_MS;
    const fields=()=>(st.config&&st.config.fields)||{};
    const dirty=()=>Object.keys(st.draft).length>0;
    const labelOf=id=>{try{return typeof opts.nodeLabel==='function'&&opts.nodeLabel(id)||id}catch(_e){return id}};
    const elapsed=since=>Math.max(0,Math.floor((now()-since)/1000));

    /* --- brouillon ------------------------------------------------------------- */
    function pruneDraft(){
      for(const k of Object.keys(st.draft))if(st.draft[k]===serverValue(st.config,k))delete st.draft[k];
      if(!own(st.draft,'instructions'))st.conflict=null;
    }
    function setDraft(field,value){
      const f=fields()[field];
      if(!f||!f.editable||st.saving)return false;
      if(field==='instructions')value=String(value??'');
      st.draft[field]=value;
      /* Les modèles du nouveau CLI ne sont connus qu'après relecture : un modèle choisi est retiré, et on le dit. */
      if(field==='provider'){if(own(st.draft,'model'))st.droppedModel=st.draft.model;delete st.draft.model}
      if(field==='model')st.droppedModel=null;
      delete st.saved[stepOf(field)];st.notice=null;
      pruneDraft();
      if(!own(st.draft,'provider'))st.droppedModel=null;
      return true;
    }
    const stepOf=field=>(STEPS.find(s=>s.fields.includes(field))||{id:field}).id;
    function invalid(){
      const f=fields().instructions;
      if(own(st.draft,'instructions')&&f&&Number(f.max_length)>0&&st.draft.instructions.length>Number(f.max_length))
        return `Les instructions dépassent ${f.max_length} caractères.`;
      return '';
    }
    function discard(){st.draft={};st.droppedModel=null;st.conflict=null;st.error=null;st.notice=null;render();announce('Modifications annulées.')}

    /* --- rendu ----------------------------------------------------------------- */
    function chip(text,tone,icon){return `<span class="bcp-chip ${tone||''}">${icon?glyph(icon,'bcp-g bcp-g-sm'):''}${esc(text)}</span>`}
    function appliesChip(applies,step){
      const s=st.saved[step];
      if(s)return `<span class="bcp-chip ok" data-bcp-saved="${esc(step)}">${glyph('check','bcp-g bcp-g-sm')}${s.changed===false?'Inchangé':'Enregistré'}${s.applies?' · effectif '+esc(appliesText(s.applies)):''}</span>`;
      return applies?chip('Effectif '+appliesText(applies),'','clock'):'';
    }
    function sectionHead(title,applies,step,extra){
      const mark=step&&STEPS.find(s=>s.id===step).fields.some(f=>own(st.draft,f))?'<span class="bcp-dirty" title="Modifié, non appliqué">Modifié</span>':'';
      return `<div class="bcp-sec-head"><h3>${esc(title)}</h3>${mark}${extra||''}${appliesChip(applies,step)}</div>`;
    }
    function reasonLine(f){return f&&f.reason?`<p class="bcp-hint">${esc(f.reason)}</p>`:''}
    function noticeHtml(n,attrs){
      const icon=n.tone==='ok'?'check':n.tone==='info'?'info':'warn';
      return `<div class="bcp-notice ${n.tone||''}" ${attrs||''}>${glyph(icon,'bcp-g bcp-notice-g')}<div>${n.title?`<p class="bcp-notice-t">${esc(n.title)}</p>`:''}<p>${esc(n.text)}</p>${n.code?`<code class="bcp-code">${esc(n.code)}${n.status?' · HTTP '+esc(n.status):''}</code>`:''}</div></div>`;
    }
    function waitHtml(what,since){return `<span class="bcp-wait"><span class="bcp-spin" aria-hidden="true"></span>${esc(what)} <span class="bcp-elapsed" data-bcp-since="${since}">${elapsed(since)} s</span></span>`}

    function headHtml(){
      const c=st.config||{},label=c.label||st.brainId;
      const meta=st.config?[`<code>${esc(c.brain_id)}</code>`,c.brain_type?esc(c.brain_type):'',c.process?'processus '+esc(c.process):''].filter(Boolean).join(' · '):'Lecture…';
      return `<header class="bcp-head" data-bcp-drag>
        <span class="bcp-tile">${glyph('brain','bcp-g bcp-g-lg')}</span>
        <div class="bcp-titles"><h2 id="${uid}-title" tabindex="-1" data-bcp-key="title">${esc(label)}</h2><p class="bcp-sub" id="${uid}-sub">${meta}</p></div>
        <button type="button" class="bcp-icon bcp-grip" data-bcp-act="grip" data-bcp-key="grip" aria-label="Déplacer la fenêtre (flèches)" title="Glisser ou flèches pour déplacer">${glyph('grip')}</button>
        <button type="button" class="bcp-icon" data-bcp-act="close" data-bcp-key="close" aria-label="Fermer la configuration">${glyph('close')}</button>
      </header>`;
    }
    function badgesHtml(){
      const c=st.config;if(!c)return '';
      const s=c.state||{},[text,tone]=STATE[s.state]||[s.state||'État inconnu','off'];
      const out=[`<span class="bcp-state ${tone}" title="${esc(s.reason||'')}"><span class="bcp-dot" aria-hidden="true"></span>${esc(text)}</span>`];
      if(c.system)out.push(`<span class="bcp-chip lock" title="Cerveau système : il ne peut pas être supprimé.">${glyph('lock','bcp-g bcp-g-sm')}Système</span>`);
      if(c.voice_architecture&&c.voice_architecture.label)out.push(chip('Architecture vocale : '+c.voice_architecture.label));
      return `<div class="bcp-badges">${out.join('')}${s.reason?`<p class="bcp-hint bcp-state-reason">${esc(s.reason)}</p>`:''}</div>`;
    }
    function missionHtml(){
      const f=fields().mission;if(!f)return '';
      return `<section class="bcp-sec" data-bcp-field="mission">${sectionHead('Mission',null,null,chip('Lecture seule','','lock'))}
        <p class="bcp-mission">${esc(f.value||'—')}</p>${reasonLine(f)}</section>`;
    }
    function choiceOption(ch,selected){
      const off=ch.available===false;
      return `<option value="${esc(ch.value)}"${selected?' selected':''}${off?' disabled':''}>${esc(ch.label||ch.value||'Défaut')}${off?' — indisponible':''}</option>`;
    }
    function selectHtml(field,f,value,disabled,label){
      const choices=Array.isArray(f.choices)?f.choices:[];
      const known=choices.some(ch=>ch.value===value);
      /* Une valeur absente des choix reste visible et sélectionnée : rien n'est réécrit en silence. */
      const extra=known?'':`<option value="${esc(value)}" selected disabled>${esc(value||'Défaut')} — hors des choix servis</option>`;
      return `<label class="bcp-label" for="${uid}-${field}">${esc(label)}</label>
        <select id="${uid}-${field}" class="bcp-select" data-bcp-input="${field}" data-bcp-key="${field}"${disabled?' disabled':''}>${extra}${choices.map(ch=>choiceOption(ch,ch.value===value)).join('')}</select>`;
    }
    function choiceState(f,value){
      const ch=(f.choices||[]).find(c=>c.value===value);
      if(!ch)return '';
      if(ch.available===false)return `<p class="bcp-hint bad">${glyph('warn','bcp-g bcp-g-sm')}${esc(ch.state==='unlisted'?'Valeur enregistrée absente du catalogue : ':'Indisponible : ')}${esc(ch.reason||'raison non fournie')}</p>`;
      return '';
    }
    function unavailableList(f){
      const off=(f.choices||[]).filter(c=>c.available===false);
      if(!off.length)return '';
      return `<details class="bcp-unavail"><summary data-bcp-key="unavail-${esc(f.owner||'')}">${off.length} choix indisponible${off.length>1?'s':''}</summary><ul>${off.map(c=>`<li><span>${esc(c.label||c.value)}</span><span class="bcp-hint">${esc(c.reason||'raison non fournie')}${c.reason_code?` <code>${esc(c.reason_code)}</code>`:''}</span></li>`).join('')}</ul></details>`;
    }
    function modelHtml(){
      const F=fields(),f=F.model;if(!f)return '';
      const cat=(st.config&&st.config.catalog)||{};
      const parts=[];
      if(cat.status&&cat.status!=='ok')parts.push(noticeHtml({tone:'warn',title:'Catalogue des modèles indisponible',text:(cat.reason||'Le serveur ne peut pas vérifier les modèles.')+' Seul le choix par défaut reste permis.'}));
      const p=F.provider;
      if(p){
        const pv=own(st.draft,'provider')?st.draft.provider:p.value;
        parts.push(`<div class="bcp-row">${selectHtml('provider',p,pv,!p.editable||!!st.saving,FIELD_LABEL.provider)}${choiceState(p,pv)}${reasonLine(p)}${unavailableList(p)}</div>`);
      }else if(f.provider)parts.push(`<p class="bcp-fact"><span>Fournisseur</span><strong>${esc(f.provider)}</strong></p>`);
      const providerChanged=p&&own(st.draft,'provider');
      const mv=own(st.draft,'model')?st.draft.model:f.value;
      const dropped=providerChanged&&st.droppedModel!=null?`<p class="bcp-hint bad" data-bcp-dropped-model>${glyph('warn','bcp-g bcp-g-sm')}Votre choix « ${esc(st.droppedModel||'Défaut')} » est retiré : il appartient à l’autre CLI.</p>`:'';
      parts.push(`<div class="bcp-row">${selectHtml('model',f,mv,!f.editable||providerChanged||!!st.saving,FIELD_LABEL.model)}${dropped}${providerChanged
        ?`<p class="bcp-hint">${glyph('info','bcp-g bcp-g-sm')}Les modèles de ce CLI s’affichent après l’application du changement de CLI ; il garde le modèle qui lui est déjà enregistré.</p>`
        :choiceState(f,mv)}${reasonLine(f)}${unavailableList(f)}</div>`);
      return `<section class="bcp-sec" data-bcp-field="model">${sectionHead('Modèle',f.applies,'model')}${parts.join('')}</section>`;
    }
    function instructionsHtml(){
      const f=fields().instructions;if(!f)return '';
      if(!f.editable)return `<section class="bcp-sec" data-bcp-field="instructions">${sectionHead('Instructions du cerveau',null,null,chip('Non modifiable','','lock'))}${reasonLine(f)||'<p class="bcp-hint">Ce cerveau n’a pas d’instructions modifiables.</p>'}</section>`;
      const text=own(st.draft,'instructions')?st.draft.instructions:String(f.value??''),max=Number(f.max_length)||0;
      const over=max&&text.length>max;
      const conflict=st.conflict?`<div class="bcp-conflict">${noticeHtml({tone:'warn',title:'Modifiées ailleurs',text:'Votre brouillon est conservé ci-dessous. Voici le texte actuel du serveur : comparez, puis appliquez à nouveau pour le remplacer, ou annulez vos modifications.'})}
        <details open><summary data-bcp-key="conflict-sum">Texte actuel du serveur</summary><pre class="bcp-pre">${esc(st.conflict.text||'(vide : aucune instruction ajoutée)')}</pre></details></div>`:'';
      return `<section class="bcp-sec" data-bcp-field="instructions">${sectionHead('Instructions du cerveau',f.applies,'instructions')}
        ${conflict}
        <label class="bcp-label" for="${uid}-instructions">Ajout au prompt de ce cerveau${f.prompt_id?` <code>${esc(f.prompt_id)}</code>`:''}</label>
        <textarea id="${uid}-instructions" class="bcp-text${over?' bad':''}" rows="5" data-bcp-input="instructions" data-bcp-key="instructions" aria-describedby="${uid}-count"${st.saving?' disabled':''} placeholder="Aucune instruction ajoutée : le prompt par défaut s’applique.">${esc(text)}</textarea>
        <div class="bcp-text-foot"><span id="${uid}-count" class="bcp-count${over?' bad':''}" data-bcp-count>${text.length}${max?' / '+max:''} caractères${over?' — trop long':''}</span>
        ${text?`<button type="button" class="bcp-link" data-bcp-act="clear-instructions" data-bcp-key="clear-instructions">Vider (revenir au prompt par défaut)</button>`:''}</div>
        ${reasonLine(f)}</section>`;
    }
    function radiogroup(field,choices,value,disabled,label,cls){
      const sel=choices.some(c=>c.value===value)?value:null;
      return `<div class="${cls}" role="radiogroup" aria-label="${esc(label)}"${disabled?' aria-disabled="true"':''}>${choices.map((c,i)=>{
        const on=c.value===sel,tab=on||(sel==null&&i===0)?0:-1;
        return `<button type="button" role="radio" class="bcp-seg" aria-checked="${on}" tabindex="${tab}" data-bcp-radio="${field}" data-bcp-value="${esc(c.value)}" data-bcp-key="${field}:${esc(c.value)}"${disabled?' aria-disabled="true"':''}${c.description?` title="${esc(c.description)}"`:''}>${esc(c.label||c.value)}</button>`}).join('')}</div>`;
    }
    function activationHtml(){
      const f=fields().activation;if(!f)return '';
      const choices=Array.isArray(f.choices)?f.choices:[];
      if(!f.editable||!choices.length){
        const [text]=STATE[f.value]||[f.value];
        return `<section class="bcp-sec bcp-sec-compact" data-bcp-field="activation">${sectionHead('Activation',null,null,chip('Non réglable ici','','lock'))}
          <p class="bcp-fact"><span>État</span><strong>${esc(text||'—')}</strong></p>${reasonLine(f)}</section>`;
      }
      const v=own(st.draft,'activation')?st.draft.activation:f.value;
      const live=f.live&&f.live!==f.value?`<p class="bcp-hint">En ce moment : <strong>${esc(f.live)}</strong> (le réglage enregistré vaut au prochain démarrage).</p>`:'';
      return `<section class="bcp-sec" data-bcp-field="activation">${sectionHead('Activation',f.applies,'activation')}
        ${radiogroup('activation',choices,v,!!st.saving,'Activation du cerveau','bcp-segs bcp-segs-wrap')}${live}${reasonLine(f)}</section>`;
    }
    function delegationHtml(){
      const f=fields().delegation;
      const reminder=`<p class="bcp-reminder">${glyph('info','bcp-g bcp-g-sm')}<span>Le choix du modèle de chaque rôle se fait dans l’onglet Sous-agents.</span>
        <button type="button" class="bcp-link" data-settings-open="${SUBAGENTS_TAB}" data-bcp-key="open-subagents">Ouvrir Sous-agents ${glyph('arrow','bcp-g bcp-g-sm')}</button></p>`;
      if(!f)return '';
      if(f.value==='not_applicable')return `<section class="bcp-sec bcp-sec-compact" data-bcp-field="delegation">${sectionHead(FIELD_LABEL.delegation,null,null,chip('Sans objet','','info'))}
        <p class="bcp-hint">${esc(f.reason||'Ce cerveau ne lance pas de sous-agents.')}</p>${reminder}</section>`;
      const choices=Array.isArray(f.choices)?f.choices:[];
      const v=own(st.draft,'delegation')?st.draft.delegation:f.value;
      const cur=choices.find(c=>c.value===v);
      const warn=[];
      if(f.stored_invalid)warn.push(noticeHtml({tone:'warn',text:f.reason||`Valeur enregistrée inconnue « ${f.stored_invalid} ».`}));
      const store=st.config&&st.config.store;
      if(store&&store.status&&store.status!=='ok')warn.push(noticeHtml({tone:'bad',title:'Réglage illisible',text:store.reason||'Le fichier de ce réglage ne peut pas être lu.',code:store.code}));
      /* `launched` : ce qu'a reçu le CLI cerveau vivant ; `pending_relaunch` : la valeur enregistrée attend sa relance
         (outil et consigne), même si le hook applique déjà `never`. Dit tel quel, jamais présenté comme effectif. */
      const lbl=val=>{const c=choices.find(x=>x.value===val);return c?c.label:val};
      const brainName=st.config&&st.config.label||st.brainId;
      const launched=f.pending_relaunch
        ?`<p class="bcp-pending" data-bcp-pending-relaunch>${glyph('clock','bcp-g bcp-g-sm')}<span>« ${esc(lbl(f.value))} » est enregistré : effectif à la relance de ${esc(brainName)}.${f.launched?` Le cerveau en cours d’exécution a reçu « ${esc(lbl(f.launched))} ».`:''}</span></p>`
        :f.launched?`<p class="bcp-hint">Reçue par le cerveau en cours d’exécution : « ${esc(lbl(f.launched))} ».</p>`:'';
      const enforcement=Array.isArray(f.enforcement)&&f.enforcement.length?`<details class="bcp-enf"><summary data-bcp-key="enforcement">Comment c’est appliqué</summary><ul>${f.enforcement.map(e=>`<li><span class="bcp-chip">${esc(appliesText(e.applies)||'—')}</span><span>${esc(e.detail||e.mechanism)}</span></li>`).join('')}</ul></details>`:'';
      return `<section class="bcp-sec" data-bcp-field="delegation">${sectionHead(FIELD_LABEL.delegation,f.applies,'delegation')}
        <p class="bcp-hint">À quel point ce cerveau confie son travail à des sous-agents.</p>
        ${warn.join('')}
        ${radiogroup('delegation',choices,v,!f.editable||!!st.saving,FIELD_LABEL.delegation,'bcp-segs bcp-segs-5')}
        <div class="bcp-scale" aria-hidden="true"><span>Moins</span><span>Plus</span></div>
        ${launched}
        <p class="bcp-level" data-bcp-level aria-live="polite">${cur?`<strong>${esc(cur.label)}</strong> — ${esc(cur.description||'')}`:'Aucun niveau choisi.'}</p>
        ${reasonLine(f)}${enforcement}${reminder}</section>`;
    }
    function connectionItem(c,dir){
      const [mut,icon]=MUTABILITY[c.mutability]||[c.mutability||'?','info'];
      const on=c.enabled!==false;
      const pending=c.pending?` · ${glyph('clock','bcp-g bcp-g-sm')}${c.pending.enabled?'activée':'coupée'} ${esc(appliesText(c.pending.applies))}`:'';
      const gov=c.governed_by&&c.governed_by.field?`<span class="bcp-hint">Suit « ${esc(FIELD_LABEL[c.governed_by.field]||c.governed_by.field)} »${c.governed_by.node&&c.governed_by.node!==st.brainId?' de '+esc(labelOf(c.governed_by.node)):''}.</span>`:'';
      const focusBtn=typeof opts.onFocusConnection==='function'?`<button type="button" class="bcp-btn ghost sm" data-bcp-conn="${esc(c.id)}" data-bcp-key="conn:${esc(c.id)}">${glyph('target','bcp-g bcp-g-sm')}Voir sur le graphe</button>`:'';
      return `<li class="bcp-conn${on?'':' off'}">
        <div class="bcp-conn-main">${glyph(dir==='in'?'in':'out','bcp-g bcp-g-sm bcp-dir')}<strong>${dir==='in'?'depuis':'vers'} ${esc(labelOf(c.peer))}</strong>
          <span class="bcp-chip">${esc(CHANNEL[c.channel]||c.channel||'canal ?')}</span>
          <span class="bcp-chip ${on?'ok':''}">${on?'Active':'Coupée'}</span>
          <span class="bcp-chip m-${esc(c.mutability||'')}">${glyph(icon,'bcp-g bcp-g-sm')}${esc(mut)}</span></div>
        ${c.purpose?`<p class="bcp-conn-purpose">${esc(c.purpose)}${pending}</p>`:pending?`<p class="bcp-conn-purpose">${pending}</p>`:''}
        ${c.locked_reason?`<span class="bcp-hint">${esc(c.locked_reason)}</span>`:''}${gov}
        ${focusBtn}</li>`;
    }
    function connectionsHtml(){
      const cn=st.config&&st.config.connections;
      if(!cn)return `<section class="bcp-sec" data-bcp-field="connections">${sectionHead('Connexions')}<p class="bcp-hint">Résumé des connexions indisponible.</p></section>`;
      const list=(arr,dir,title)=>`<div class="bcp-conns"><h4>${esc(title)} <span class="bcp-count">${(arr||[]).length}</span></h4>${(arr||[]).length?`<ul>${arr.map(c=>connectionItem(c,dir)).join('')}</ul>`:'<p class="bcp-hint">Aucune.</p>'}</div>`;
      return `<section class="bcp-sec" data-bcp-field="connections">${sectionHead('Connexions',null,null,chip('Lecture seule','','lock'))}
        ${list(cn.incoming,'in','Entrantes')}${list(cn.outgoing,'out','Sortantes')}
        <p class="bcp-hint">Les liaisons se modifient sur le graphe${cn.edit_on&&cn.edit_on!=='graph'?' ('+esc(cn.edit_on)+')':''}, pas ici.</p></section>`;
    }
    function elsewhereHtml(){
      const o=st.config&&st.config.out_of_scope;if(!o)return '';
      const items=['personality','cli_technical'].filter(k=>o[k]).map(k=>`<li>${esc(o[k])}</li>`);
      return items.length?`<section class="bcp-sec bcp-elsewhere"><h4>Ailleurs dans les Réglages</h4><ul>${items.join('')}</ul></section>`:'';
    }
    function errorHtml(){
      if(!st.error)return '';
      const e=st.error;
      const main=noticeHtml({tone:e.tone||'bad',title:e.title,text:e.reason,code:e.code,status:e.status},'role="alert" data-bcp-error');
      return e.reread?main+noticeHtml({tone:'bad',title:'Relecture impossible',text:e.reread.reason,code:e.reread.code,status:e.reread.status},'data-bcp-reread-error'):main;
    }
    function confirmHtml(){
      const c=st.confirm;if(!c)return '';
      const n=Object.keys(st.draft).map(k=>FIELD_LABEL[k]||k);
      const text=c.kind==='replace'?`Ouvrir ${esc(c.nextLabel||c.next.brainId)} abandonne vos modifications non appliquées (${esc(n.join(', '))}).`
        :`Fermer abandonne vos modifications non appliquées (${esc(n.join(', '))}).`;
      return `<div class="bcp-confirm" role="alertdialog" aria-labelledby="${uid}-confirm" data-bcp-confirm="${c.kind}"><p id="${uid}-confirm">${text}</p>
        <div class="bcp-actions"><button type="button" class="bcp-btn" data-bcp-act="confirm-keep" data-bcp-key="confirm-keep">Continuer l’édition</button>
        <button type="button" class="bcp-btn danger" data-bcp-act="confirm-discard" data-bcp-key="confirm-discard">${c.kind==='replace'?'Abandonner et ouvrir':'Fermer sans appliquer'}</button></div></div>`;
    }
    function footHtml(){
      const bad=invalid(),n=Object.keys(st.draft).length;
      const status=st.saving?waitHtml(st.saving.what,st.saving.since)
        :bad?`<span class="bcp-foot-s bad">${esc(bad)}</span>`
        :n?`<span class="bcp-foot-s">${n} modification${n>1?'s':''} non appliquée${n>1?'s':''}</span>`
        :st.notice?`<span class="bcp-foot-s ${st.notice.tone||''}">${esc(st.notice.text)}</span>`:'<span class="bcp-foot-s">Aucune modification en cours.</span>';
      return `<footer class="bcp-foot"><div class="bcp-foot-status" data-bcp-foot>${status}</div><div class="bcp-actions">
        <button type="button" class="bcp-btn ghost" data-bcp-act="discard" data-bcp-key="discard"${!n||st.saving?' disabled':''}>Annuler</button>
        <button type="button" class="bcp-btn primary" data-bcp-act="apply" data-bcp-key="apply"${!n||bad||st.saving?' disabled':''}>Appliquer</button></div></footer>`;
    }
    function bodyHtml(){
      if(st.phase==='loading')return `<div class="bcp-body bcp-centered">${waitHtml('Lecture de la configuration…',st.since)}<span class="bcp-skel"></span><span class="bcp-skel w2"></span><span class="bcp-skel"></span>
        <p class="bcp-hint">Échéance : ${Math.round(timeoutMs()/1000)} s. Vous pouvez fermer la fenêtre.</p></div>`;
      if(st.phase==='error'){const e=st.loadError||{};
        return `<div class="bcp-body">${noticeHtml({tone:'bad',title:'Configuration illisible',text:e.reason||'La configuration de ce cerveau n’a pas pu être lue.',code:e.code,status:e.status},'role="alert"')}
          <div class="bcp-actions"><button type="button" class="bcp-btn" data-bcp-act="reload" data-bcp-key="reload">Relire</button></div></div>`}
      const version=st.config&&st.config.schema_version!==1?noticeHtml({tone:'warn',text:`Version de contrat inattendue (${st.config.schema_version}) : l’affichage peut être incomplet.`}):'';
      return `<div class="bcp-body">${errorHtml()}${version}${missionHtml()}${modelHtml()}${delegationHtml()}${instructionsHtml()}${activationHtml()}${connectionsHtml()}${elsewhereHtml()}</div>`;
    }
    function html(){
      const accent=accentFor(st.config||{brain_type:st.brainId},opts.accent);
      const pos=st.pos?`left:${st.pos.x}px;top:${st.pos.y}px;`:'';
      return `<div class="bcp-scrim" data-bcp-act="scrim" aria-hidden="true"></div>
        <div class="bcp-win${st.reveal?' reveal':''}" role="dialog" aria-modal="false" aria-labelledby="${uid}-title" aria-describedby="${uid}-sub" data-brain-config-panel="${esc(st.brainId)}" style="${pos}--bcp-accent:var(--role-accent-${accent})">
        ${headHtml()}${st.phase==='ready'?badgesHtml():''}${bodyHtml()}${st.phase==='ready'?footHtml():`<footer class="bcp-foot"><div class="bcp-foot-status"></div><div class="bcp-actions"><button type="button" class="bcp-btn ghost" data-bcp-act="close" data-bcp-key="close-foot">Fermer</button></div></footer>`}
        ${confirmHtml()}<div class="bcp-sr" aria-live="polite" data-bcp-live>${esc(st.live)}</div></div>`;
    }
    const win=()=>layer.querySelector?layer.querySelector('.bcp-win'):null;
    const cssEsc=v=>String(v).replace(/["\\]/g,'\\$&');
    function render(){
      if(st.destroyed)return;
      const a=doc&&doc.activeElement;let key=null,sel=null,inside=false;
      if(a&&layer.contains&&layer.contains(a)){inside=true;key=a.getAttribute&&a.getAttribute('data-bcp-key');if(a.tagName==='TEXTAREA')sel=[a.selectionStart,a.selectionEnd]}
      const body=layer.querySelector&&layer.querySelector('.bcp-body'),scroll=body?body.scrollTop:0;
      try{layer.innerHTML=html()}
      catch(e){logError('brain_config_render_failed',e,{brainId:st.brainId});st.phase='error';st.loadError={code:'brain_config_render_failed',reason:'La fenêtre n’a pas pu afficher cette réponse : '+(e&&e.message||e)};layer.innerHTML=html()}
      st.reveal=false;
      const nb=layer.querySelector&&layer.querySelector('.bcp-body');if(nb)nb.scrollTop=scroll;
      if(inside){if(!(key&&focusKey(key,sel)))focusKey(st.confirm?'confirm-keep':'title')}
      clampWindow();syncTicker();
    }
    function focusKey(key,sel){
      if(!layer.querySelector)return false;
      const el=layer.querySelector(`[data-bcp-key="${cssEsc(key)}"]`);
      if(!el||!el.focus||el.disabled)return false;
      el.focus({preventScroll:true});
      if(sel&&el.setSelectionRange)try{el.setSelectionRange(sel[0],sel[1])}catch(_e){/* intentionnel : sélection perdue, le texte reste */}
      return true;
    }
    function announce(text){st.live=text;const el=layer.querySelector&&layer.querySelector('[data-bcp-live]');if(el)el.textContent=text}
    /* Saisie : seuls le compteur, la marque « Modifié » et le pied changent ; le texte et son curseur restent. */
    function syncInput(){
      if(!layer.querySelector)return;
      const f=fields().instructions,text=own(st.draft,'instructions')?st.draft.instructions:String(f&&f.value||''),max=Number(f&&f.max_length)||0,over=max&&text.length>max;
      const count=layer.querySelector('[data-bcp-count]');
      if(count){count.textContent=`${text.length}${max?' / '+max:''} caractères${over?' — trop long':''}`;count.classList&&count.classList.toggle('bad',!!over)}
      const ta=layer.querySelector('[data-bcp-input="instructions"]');if(ta&&ta.classList)ta.classList.toggle('bad',!!over);
      const foot=layer.querySelector('.bcp-foot');if(foot){const tmp=doc.createElement('div');tmp.innerHTML=footHtml();foot.replaceWith(tmp.firstElementChild)}
      const head=layer.querySelector('[data-bcp-field="instructions"] .bcp-sec-head');
      if(head){const has=!!head.querySelector('.bcp-dirty'),want=own(st.draft,'instructions');
        if(want&&!has){const s=doc.createElement('span');s.className='bcp-dirty';s.title='Modifié, non appliqué';s.textContent='Modifié';head.querySelector('h3').after(s)}
        if(!want&&has)head.querySelector('.bcp-dirty').remove();
        const saved=head.querySelector('[data-bcp-saved]');if(saved&&!st.saved.instructions)saved.remove()}
    }
    function syncTicker(){
      const waiting=st.phase==='loading'||st.saving;
      if(waiting&&ticker==null)ticker=setTimer(tick,1000);
      if(!waiting&&ticker!=null){clearTimer(ticker);ticker=null}
    }
    function tick(){
      if(st.destroyed||!layer.querySelectorAll)return;
      for(const el of layer.querySelectorAll('[data-bcp-since]'))el.textContent=elapsed(Number(el.getAttribute('data-bcp-since')))+' s';
    }

    /* --- position ---------------------------------------------------------------- */
    const narrow=()=>{try{return !!(root.matchMedia&&root.matchMedia('(max-width:720px)').matches)}catch(_e){return false}};
    function viewport(){return {w:root.innerWidth||1280,h:root.innerHeight||800}}
    function rectOf(x){try{const el=typeof x==='function'?x():x;return el&&el.getBoundingClientRect?el.getBoundingClientRect():(x&&Number.isFinite(x.left)?x:null)}catch(_e){return null}}
    /* Première position : à côté de l'ancre (le nœud), sinon contre le bord droit de l'hôte ; jamais hors écran. */
    function initialPos(){
      /* Contre le bord droit de l'hôte, sur la colonne de l'inspecteur du canevas plutôt que sur les nœuds, à la
         hauteur de l'ancre : le graphe reste lisible (la fenêtre se déplace ensuite au gré de l'utilisateur). */
      const v=viewport(),w=Math.min(WIN_W,v.w-2*EDGE),a=rectOf(opts.anchor),h=rectOf(host);
      const hostRight=Math.min(h&&h.width?h.right:v.w,v.w);
      const right=hostRight-w-16,left=EDGE+8;
      /* Slice 07 : dans le shell des Réglages, le canevas est plus étroit que la page de démonstration et le nœud peut
         tomber sous la colonne de droite. La fenêtre ne doit pas couvrir le cerveau qu'elle configure : bord droit de
         l'hôte si le nœud reste libre, sinon bord gauche de l'écran (sur le rail des catégories, le graphe reste
         visible), sinon le côté qui a le plus de place, collé au nœud. */
      let x=right;
      if(a&&a.width&&a.right>right){
        if(left+w<=a.left)x=left;
        else x=a.left>(v.w-a.right)?Math.max(left,a.left-w-16):a.right+16;
      }
      const y=a?a.top-24:(h&&h.width?Math.max(h.top,0)+16:24);
      return clampPos({x,y});
    }
    function clampPos(p){
      const v=viewport(),el=win(),r=el&&el.getBoundingClientRect?el.getBoundingClientRect():{width:Math.min(WIN_W,v.w),height:200};
      return {x:Math.round(Math.max(EDGE,Math.min(p.x,v.w-r.width-EDGE))),y:Math.round(Math.max(EDGE,Math.min(p.y,v.h-Math.min(r.height,v.h-2*EDGE)-EDGE)))};
    }
    function clampWindow(){
      const el=win();if(!el||!el.style||narrow())return;
      if(!st.pos)st.pos=initialPos();
      st.pos=clampPos(st.pos);el.style.left=st.pos.x+'px';el.style.top=st.pos.y+'px';
    }
    function moveBy(dx,dy){if(narrow()||!st.pos)return;st.pos=clampPos({x:st.pos.x+dx,y:st.pos.y+dy});const el=win();if(el){el.style.left=st.pos.x+'px';el.style.top=st.pos.y+'px'}}

    /* --- lecture / écriture -------------------------------------------------------- */
    async function load(){
      const gen=generation,id=st.brainId;
      if(!st.config){st.phase='loading';st.since=now();render()}
      try{
        const config=await withDeadline(adapter().load(id),timeoutMs(),'lecture de la configuration');
        if(st.destroyed||gen!==generation)return null;
        if(!config||typeof config!=='object'||!config.fields)throw codedError('brain_config_payload_invalid','Réponse sans champs de configuration.');
        st.config=config;st.phase='ready';st.loadError=null;pruneDraft();
        logInfo('brain_config_panel.loaded',{brainId:id,revision:config.revision});
        render();return config;
      }catch(e){
        if(st.destroyed||gen!==generation)return null;
        logError(e&&e.code||'brain_config_load_failed',e,{brainId:id});
        if(e&&e.config&&e.config.fields){st.config=e.config;st.phase='ready'}
        const reread={code:e&&e.code||'brain_config_load_failed',status:e&&e.status,reason:(e&&e.message||String(e))+' La fenêtre montre la dernière configuration lue.'};
        /* Un refus ou une « Issue inconnue » déjà affiché reste la cause d'origine : la relecture ratée s'y ajoute. */
        if(st.config){st.error=st.error?{...st.error,reread}:{...reread,title:'Relecture impossible'}}
        else{st.phase='error';st.loadError={code:e&&e.code||'brain_config_load_failed',status:e&&e.status,reason:e&&e.message||String(e)}}
        render();return null;
      }
    }
    function bodyFor(step){
      const F=fields(),d=st.draft,body={base_revision:st.config.revision};
      if(step.id==='model'){
        if(own(d,'provider'))body.provider=d.provider;
        if(own(d,'model'))body.model=d.model;
      }else if(step.id==='instructions'){
        body.instructions={text:d.instructions,effective_revision:F.instructions.effective_revision};
      }else body[step.id]=d[step.id];
      return body;
    }
    async function apply(){
      if(st.saving||!dirty()||invalid()||!st.config)return {ok:false,code:'brain_config_nothing_to_apply'};
      const gen=generation,id=st.brainId;
      st.error=null;st.notice=null;
      const done=[];
      for(const step of STEPS){
        if(!step.fields.some(f=>own(st.draft,f)))continue;
        const body=bodyFor(step),what=`Enregistrement : ${FIELD_LABEL[step.id]||step.id}…`;
        st.saving={what,since:now()};render();
        let res;
        try{res=await withDeadline(adapter().patch(id,body),timeoutMs(),FIELD_LABEL[step.id]||step.id)}
        catch(e){
          if(st.destroyed||gen!==generation)return {ok:false,code:'brain_config_closed'};
          const code=e&&e.code||'brain_config_unreachable';
          logError(code,e,{brainId:id,step:step.id});
          st.saving=null;
          st.error={code,title:'Issue inconnue',reason:`${e&&e.message||e} On ne sait pas si « ${FIELD_LABEL[step.id]} » a été enregistré : la fenêtre relit la configuration ; ce qui reste marqué « Modifié » n’est pas appliqué.`};
          const reread=await load();
          /* I-002 point 2 : l'écriture a pu passer ; ce qui a été relu est la vérité du serveur, l'hôte s'y aligne. */
          if(reread&&!st.destroyed&&gen===generation)notify('reread',{brainId:id,field:step.id,config:reread});
          return {ok:false,code,unknown:true,done};
        }
        if(st.destroyed||gen!==generation)return {ok:false,code:'brain_config_closed'};
        if(res&&res.ok){
          if(res.config&&res.config.fields)st.config=res.config;
          for(const f of step.fields)delete st.draft[f];
          st.saved[step.id]={applies:res.applies||null,changed:res.changed};
          done.push(step.id);
          /* Réponse sans descripteur : relire AVANT de prévenir l'hôte, qui reçoit sinon l'ancienne configuration
             (I-002 point 2). Relecture ratée : l'hôte n'a rien de neuf à recevoir. */
          if(!res.config){st.saving=null;await load();if(st.destroyed||gen!==generation)return {ok:false,code:'brain_config_closed'}}
          logInfo('brain_config_panel.saved',{brainId:id,field:step.id,changed:res.changed,applies:res.applies,revision:st.config.revision});
          notify('saved',{brainId:id,field:step.id,applies:res.applies||null,changed:res.changed,config:st.config});
          pruneDraft();
          continue;
        }
        const r=res||{};
        const code=r.code||'brain_config_write_refused';
        logError(code,new Error(r.reason||code),{brainId:id,field:r.field||step.id,status:r.status});
        st.saving=null;
        const conflict=CONFLICT.has(code),absent=code==='brain_config_brain_absent',label=FIELD_LABEL[r.field||step.id]||step.id;
        st.error={code,status:r.status,tone:conflict?'warn':'bad',
          title:conflict?`Modifié ailleurs : ${label}`:absent?'Cerveau absent':`Refusé : ${label}`,
          reason:absent?'Ce cerveau n’existe pas dans l’architecture vocale actuelle : rien n’a été écrit.'+(r.reason?' ('+r.reason+')':'')
            :(r.reason||'Refus du serveur sans raison.')+(conflict?' La configuration a été relue ; votre brouillon est conservé : vérifiez-le, puis appliquez à nouveau.':' Rien n’a été écrit pour ce champ ; votre brouillon est conservé.')};
        if(r.config&&r.config.fields){st.config=r.config;st.phase='ready'}
        else await load();
        if(PROMPT_CONFLICT.has(code)||(conflict&&step.id==='instructions'))st.conflict={text:serverValue(st.config,'instructions')||''};
        pruneDraft();render();
        announce(st.error.title+' : '+(r.reason||''));
        return {ok:false,code,status:r.status,field:r.field||step.id,done};
      }
      st.saving=null;
      const last=done.map(s=>st.saved[s]).filter(Boolean);
      st.notice={tone:'ok',text:done.length===1?`${FIELD_LABEL[done[0]]} : ${last[0].changed===false?'inchangé':'enregistré'}${last[0].applies?', effectif '+appliesText(last[0].applies):''}.`:`${done.length} réglages enregistrés.`};
      render();announce(st.notice.text);
      return {ok:true,done};
    }
    function notify(kind,detail){
      try{if(kind==='saved'&&typeof opts.onSaved==='function')opts.onSaved(detail)}catch(e){logError('brain_config_on_saved_failed',e,{brainId:detail.brainId})}
      try{if(kind==='reread'&&typeof opts.onReread==='function')opts.onReread(detail)}catch(e){logError('brain_config_on_reread_failed',e,{brainId:detail.brainId})}
      try{const Ev=root.CustomEvent;if(typeof Ev==='function'&&host.dispatchEvent)host.dispatchEvent(new Ev('brain-config:'+kind,{bubbles:true,detail}))}
      catch(e){logError('brain_config_event_failed',e,{kind})}
    }

    /* --- ouverture / fermeture --------------------------------------------------- */
    function show(brainId,nextOpts){
      if(st.destroyed)return controller;
      const o=nextOpts||opts;
      if(st.brainId===brainId&&st.phase!=='error'){
        opts={...opts,...o};if(o.returnFocus)origin=o.returnFocus;
        if(o.field)revealField(o.field);else focusKey('title');
        return controller;
      }
      if(st.saving){st.notice={tone:'warn',text:'Un enregistrement est en cours : attendez sa fin avant d’ouvrir un autre cerveau.'};render();return controller}
      if(st.brainId&&dirty()){
        st.confirm={kind:'replace',next:{...o,brainId},nextLabel:o.label||(typeof o.nodeLabel==='function'?labelOf(brainId):brainId)};
        render();focusKey('confirm-keep');announce('Modifications non appliquées : confirmez avant d’ouvrir un autre cerveau.');
        return controller;
      }
      switchTo(brainId,o);
      return controller;
    }
    function switchTo(brainId,o){
      generation+=1;
      const first=!st.brainId;
      opts={...opts,...o};
      const active=doc&&doc.activeElement;
      const outside=active&&active!==doc.body&&!(layer.contains&&layer.contains(active))?active:null;
      origin=o.returnFocus||outside||(first?null:origin);
      Object.assign(st,{brainId,field:o.field||null,config:null,droppedModel:null,phase:'loading',loadError:null,since:now(),saving:null,error:null,draft:{},saved:{},conflict:null,confirm:null,notice:null,reveal:first});
      logInfo('brain_config_panel.opened',{brainId,field:st.field});
      render();focusKey('title');
      return load().then(config=>{if(config&&st.field)revealField(st.field);else if(config)focusKey('title');return config});
    }
    function revealField(field){
      const sec=layer.querySelector&&layer.querySelector(`[data-bcp-field="${cssEsc(field)}"]`);
      if(!sec)return focusKey('title');
      if(sec.scrollIntoView)sec.scrollIntoView({block:'nearest'});
      /* Dans l'ordre de préférence (un sélecteur à la fois : une liste rendrait le premier élément du document). */
      const target=['[role="radio"][tabindex="0"]:not([aria-disabled="true"])','select:not(:disabled)','textarea:not(:disabled)','button:not(:disabled)']
        .map(q=>sec.querySelector(q)).find(Boolean);
      if(target&&target.focus)target.focus();else focusKey('title');
    }
    function close(o){
      if(st.destroyed)return true;
      if(!(o&&o.force)&&dirty()){st.confirm={kind:'close'};render();focusKey('confirm-keep');announce('Modifications non appliquées : confirmez la fermeture.');return false}
      const back=origin;
      logInfo('brain_config_panel.closed',{brainId:st.brainId,discarded:Object.keys(st.draft)});
      teardown();
      /* Le focus revient à ce qui a ouvert la fenêtre (le nœud ou son bouton « … »), relu à la fermeture :
         le canevas a pu se redessiner entre-temps. */
      try{const el=typeof back==='function'?back():back;if(el&&el.focus&&(el.isConnected!==false))el.focus()}
      catch(e){logError('brain_config_focus_return_failed',e,{brainId:st.brainId})}
      try{if(typeof opts.onClose==='function')opts.onClose({brainId:st.brainId})}catch(e){logError('brain_config_on_close_failed',e,{brainId:st.brainId})}
      return true;
    }
    function teardown(){
      st.destroyed=true;generation+=1;
      if(ticker!=null){clearTimer(ticker);ticker=null}
      while(offs.length)offs.pop()();
      try{layer.remove?layer.remove():host.removeChild&&host.removeChild(layer)}catch(_e){/* intentionnel : déjà retirée */}
      if(current===controller)current=null;
    }
    function destroy(){if(!st.destroyed){logInfo('brain_config_panel.destroyed',{brainId:st.brainId});teardown()}}
    function confirmAction(discardIt){
      const c=st.confirm;st.confirm=null;
      if(!c)return;
      if(!discardIt){render();focusKey(own(st.draft,'instructions')?'instructions':'apply');return}
      st.draft={};
      if(c.kind==='close')return close({force:true});
      switchTo(c.next.brainId,c.next);
    }

    /* --- événements (délégués sur la couche) ----------------------------------- */
    const offs=[];
    const on=(type,fn,target)=>{const t=target||layer;if(t.addEventListener)t.addEventListener(type,fn);return ()=>t.removeEventListener&&t.removeEventListener(type,fn)};
    const closest=(t,sel)=>t&&t.closest?t.closest(sel):null;
    function selectRadio(el){
      if(!el||el.getAttribute('aria-disabled')==='true')return;
      const field=el.getAttribute('data-bcp-radio'),value=el.getAttribute('data-bcp-value');
      if(setDraft(field,value)){render();focusKey(`${field}:${value}`)}
    }
    function onClick(ev){
      const t=ev.target;let el;
      if((el=closest(t,'[data-bcp-radio]')))return selectRadio(el);
      if((el=closest(t,'[data-bcp-conn]'))){
        const id=el.getAttribute('data-bcp-conn');
        logInfo('brain_config_panel.focus_connection',{brainId:st.brainId,connection:id});
        try{opts.onFocusConnection(id,{brainId:st.brainId});announce('Liaison mise en évidence sur le graphe.')}
        catch(e){logError('brain_config_focus_connection_failed',e,{connection:id});st.notice={tone:'bad',text:'La liaison n’a pas pu être montrée : '+(e&&e.message||e)};render()}
        return;
      }
      if((el=closest(t,'[data-bcp-act]'))){
        const act=el.getAttribute('data-bcp-act');
        if(act==='close'||act==='scrim')return close();
        if(act==='apply')return apply();
        if(act==='discard')return discard();
        if(act==='reload'){st.config=null;return load()}
        if(act==='clear-instructions'){setDraft('instructions','');render();focusKey('instructions');return}
        if(act==='confirm-keep')return confirmAction(false);
        if(act==='confirm-discard')return confirmAction(true);
      }
    }
    function onInput(ev){
      const el=closest(ev.target,'[data-bcp-input]');if(!el)return;
      const field=el.getAttribute('data-bcp-input');
      if(field==='instructions'){setDraft('instructions',el.value);syncInput();return}
    }
    function onChange(ev){
      const el=closest(ev.target,'select[data-bcp-input]');if(!el)return;
      if(setDraft(el.getAttribute('data-bcp-input'),el.value))render();
    }
    function focusables(){
      const w=win();if(!w||!w.querySelectorAll)return [];
      return [...w.querySelectorAll('button:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex="0"],[href]')]
        .filter(e=>e.getAttribute('tabindex')!=='-1'&&!(e.getClientRects&&e.getClientRects().length===0));
    }
    function onKeyDown(ev){
      const k=ev.key;
      if(k==='Escape'){
        ev.preventDefault&&ev.preventDefault();ev.stopPropagation&&ev.stopPropagation();
        if(st.confirm)return confirmAction(false);
        return close();
      }
      if(k==='Tab'){
        /* Piège de Tab : le focus tourne dans la fenêtre (ou dans la confirmation quand elle est ouverte). */
        const box=st.confirm&&layer.querySelector?[...layer.querySelectorAll('.bcp-confirm button')]:focusables();
        if(!box.length)return;
        const i=box.indexOf(doc.activeElement);
        if(ev.shiftKey&&(i<=0)){ev.preventDefault();box[box.length-1].focus()}
        else if(!ev.shiftKey&&(i===-1||i===box.length-1)){ev.preventDefault();box[0].focus()}
        return;
      }
      const radio=closest(ev.target,'[data-bcp-radio]');
      if(radio&&['ArrowRight','ArrowDown','ArrowLeft','ArrowUp','Home','End'].includes(k)){
        ev.preventDefault();
        const group=[...radio.parentNode.querySelectorAll('[data-bcp-radio]')];
        if(radio.getAttribute('aria-disabled')==='true')return;
        let i=group.indexOf(radio);
        i=k==='Home'?0:k==='End'?group.length-1:(i+(k==='ArrowRight'||k==='ArrowDown'?1:-1)+group.length)%group.length;
        return selectRadio(group[i]);
      }
      if(closest(ev.target,'[data-bcp-act="grip"]')&&k.startsWith('Arrow')){
        ev.preventDefault();
        moveBy(k==='ArrowLeft'?-MOVE_STEP:k==='ArrowRight'?MOVE_STEP:0,k==='ArrowUp'?-MOVE_STEP:k==='ArrowDown'?MOVE_STEP:0);
      }
    }
    function onPointerDown(ev){
      if(ev.button!==0||narrow()||!closest(ev.target,'[data-bcp-drag]'))return;
      if(closest(ev.target,'button:not([data-bcp-act="grip"]),select,textarea,a'))return;
      if(!st.pos)return;
      drag={sx:ev.clientX,sy:ev.clientY,x:st.pos.x,y:st.pos.y,id:ev.pointerId};
      try{ev.target.setPointerCapture&&ev.target.setPointerCapture(ev.pointerId)}catch(_e){/* intentionnel : la capture est un confort */}
      const w=win();w&&w.classList&&w.classList.add('dragging');
      ev.preventDefault&&ev.preventDefault();
    }
    function onPointerMove(ev){
      if(!drag)return;
      st.pos=clampPos({x:drag.x+ev.clientX-drag.sx,y:drag.y+ev.clientY-drag.sy});
      const w=win();if(w){w.style.left=st.pos.x+'px';w.style.top=st.pos.y+'px'}
    }
    function onPointerUp(){if(!drag)return;drag=null;const w=win();w&&w.classList&&w.classList.remove('dragging')}

    offs.push(on('click',onClick),on('input',onInput),on('change',onChange),on('keydown',onKeyDown),on('pointerdown',onPointerDown),on('pointermove',onPointerMove),on('pointerup',onPointerUp),on('pointercancel',onPointerUp));
    if(root.addEventListener){const r=()=>clampWindow();root.addEventListener('resize',r);offs.push(()=>root.removeEventListener('resize',r))}

    function ensureStyle(){
      if(!doc||!doc.head||!doc.getElementById||doc.getElementById(STYLE_ID))return;
      const s=doc.createElement('style');s.id=STYLE_ID;s.textContent=STYLE;doc.head.appendChild(s);
    }

    const controller={host:hostArg,element:layer,show,close,destroy,apply,discard,setDraft:(f,v)=>{const ok=setDraft(f,v);render();return ok},
      reload:()=>load(),confirm:confirmAction,moveBy,state:st,get brainId(){return st.brainId},get dirty(){return dirty()}};
    return controller;
  }

  /* Retour du focus vers l'élément du canevas qui a ouvert la fenêtre, résolu à la fermeture : le bouton « … »
     (`detail.opener === 'button'`), le bouton « Configurer… » de l'inspecteur, sinon le nœud. */
  function canvasReturnFocus(canvasHost,nodeId,detail){
    const d=detail||{},q=v=>String(v).replace(/["\\]/g,'\\$&');
    return ()=>{
      if(!canvasHost||!canvasHost.querySelector)return null;
      const sels=[];
      if(d.opener==='button')sels.push(`[data-arch-menu-btn="${q(nodeId)}"]`);
      if(d.source==='inspector')sels.push(`[data-arch-act="configure"][data-arch-id="${q(nodeId)}"]`);
      sels.push(`[data-arch-node="${q(nodeId)}"]`);
      for(const s of sels){const el=canvasHost.querySelector(s);if(el)return el}
      return null;
    };
  }

  /* --- adaptateurs --------------------------------------------------------------- */

  /* Transport HTTP de `docs/brain-config.md` (routes montées par la Slice 07). Les refus du serveur deviennent des
     résultats `{ok:false,…}` ; seuls les échecs de transport lèvent (issue inconnue). */
  function createHttpAdapter(options){
    const o=options||{},base=o.base||'/api/brains',timeoutMs=Number(o.timeoutMs)>0?Number(o.timeoutMs):DEFAULT_TIMEOUT_MS;
    const fetchImpl=o.fetch||(root.fetch&&root.fetch.bind(root));
    const url=id=>`${base}/${encodeURIComponent(id)}/config`;
    async function call(path,init){
      const ctl=typeof root.AbortController==='function'?new root.AbortController():null;
      const timer=ctl?setTimeout(()=>ctl.abort(),timeoutMs):null;
      let r;
      try{r=await fetchImpl(path,{...(init||{}),headers:{'Content-Type':'application/json',...(init&&init.headers||{})},signal:ctl?ctl.signal:undefined})}
      catch(e){
        if(e&&e.name==='AbortError')throw codedError('brain_config_timeout',`Pas de réponse du Control Center après ${Math.round(timeoutMs/1000)} s.`);
        throw codedError('brain_config_unreachable','Control Center injoignable : '+(e&&e.message||e));
      }finally{if(timer!=null)clearTimeout(timer)}
      const text=await r.text();let body={};
      try{body=text?JSON.parse(text):{}}catch(_e){body={ok:false,code:'brain_config_payload_invalid',reason:'Réponse non JSON : '+text.slice(0,160)}}
      const envelope=body&&typeof body.error==='object'&&body.error?body.error:null;
      const code=body.code||(envelope&&envelope.code)||(r.headers&&r.headers.get&&r.headers.get('X-Jarvis-Error-Code'))||'';
      const reason=body.reason||(envelope&&envelope.message)||(typeof body.error==='string'?body.error:'')||('HTTP '+r.status);
      return {status:r.status,ok:r.ok&&body.ok!==false,body,code,reason};
    }
    return {
      async load(id){
        const x=await call(url(id),{method:'GET'});
        if(!x.ok)throw codedError(x.code||'brain_config_load_failed',x.reason,{status:x.status,config:x.body&&x.body.config||null});
        return x.body;
      },
      async patch(id,body){
        const x=await call(url(id),{method:'PATCH',body:JSON.stringify(body)});
        if(x.ok)return {ok:true,changed:x.body.changed,applies:x.body.applies??null,config:x.body.config||null};
        return {ok:false,status:x.status,code:x.code||'brain_config_write_refused',reason:x.reason,field:x.body&&x.body.field||null,config:x.body&&x.body.config||null};
      },
    };
  }

  /* Adaptateur de fixture : simule le serveur de `docs/brain-config.md` (révision, verrou, choix disponibles,
     catalogue, révision des instructions) pour les tests et la démonstration SEULEMENT. `script(r)` impose la
     prochaine réponse (`{result}` ou `{error}`) ; `tamper(id, fn)` simule une écriture faite ailleurs. */
  function createFixtureAdapter(configs,options){
    const o=options||{},latency=Number(o.latencyMs)||0;
    const data={};for(const k of Object.keys(configs||{}))data[k]=clone(configs[k]);
    const calls=[],queue=[];let n=1;
    const delay=()=>new Promise(r=>setTimeout(r,latency));
    const bump=cfg=>{cfg.revision='c-fx-'+(n++)};
    const refuse=(status,code,reason,field,cfg)=>({ok:false,status,code,reason,field:field||null,config:cfg?clone(cfg):null});
    async function scripted(){const s=queue.shift();if(!s)return null;if(s.error)throw s.error;return {value:clone(s.result)}}
    return {
      calls,
      script(entry){queue.push(entry)},
      tamper(id,fn){const cfg=data[id];fn(cfg);bump(cfg);return clone(cfg)},
      current(id){return clone(data[id])},
      async load(id){
        calls.push(['load',id]);await delay();
        const s=await scripted();if(s)return s.value;
        if(!data[id])throw codedError('brain_config_unknown_brain',`Cerveau inconnu : ${id}.`,{status:404});
        return clone(data[id]);
      },
      async patch(id,body){
        calls.push(['patch',id,clone(body)]);await delay();
        const s=await scripted();if(s)return s.value;
        const cfg=data[id];
        if(!cfg)return refuse(404,'brain_config_unknown_brain',`Cerveau inconnu : ${id}.`);
        if(!body||body.base_revision!==cfg.revision)return refuse(409,'brain_config_revision_stale','Configuration modifiée depuis votre lecture.',null,cfg);
        const keys=Object.keys(body).filter(k=>k!=='base_revision').sort().join(',');
        const legal=['delegation','model','provider','activation','instructions'].concat(id==='core'?['model,provider']:[]);
        if(!legal.includes(keys))return refuse(400,'brain_config_request_invalid','Un seul champ par écriture.',null,cfg);
        const F=cfg.fields;
        for(const k of keys.split(',')){
          const f=F[k];
          if(!f||f.value==='not_applicable')return refuse(422,'brain_config_field_unsupported',`Ce cerveau ne règle pas « ${k} ».`,k,cfg);
          if(!f.editable)return refuse(423,'brain_config_field_locked',f.reason||'Champ verrouillé.',k,cfg);
          if(k==='instructions'){
            const v=body.instructions||{};
            if(v.effective_revision!==f.effective_revision)return refuse(409,'prompt_override_concurrent','Ces instructions ont été modifiées ailleurs depuis votre lecture ; relisez-les.',k,cfg);
            if(typeof v.text!=='string'||(f.max_length&&v.text.length>f.max_length))return refuse(400,'brain_config_request_invalid','Texte invalide ou trop long.',k,cfg);
            continue;
          }
          const ch=(f.choices||[]).find(c=>c.value===body[k]);
          if(k==='model'&&body[k]!==''&&cfg.catalog&&cfg.catalog.status!=='ok')return refuse(503,'brain_config_catalog_unavailable',cfg.catalog.reason||'Catalogue indisponible.',k,cfg);
          if(!ch)return refuse(422,k==='delegation'?'brain_config_delegation_invalid':k==='activation'?'brain_config_activation_invalid':'brain_config_model_unavailable',`Valeur refusée : ${body[k]}.`,k,cfg);
          if(ch.available===false)return refuse(422,'brain_config_model_unavailable',ch.reason||'Choix indisponible.',k,cfg);
        }
        let changed=false,applies=null;
        for(const k of keys.split(',')){
          const f=F[k],v=k==='instructions'?body.instructions.text:body[k];
          applies=f.applies||applies;
          if(String(f.value??'')!==String(v)){changed=true;f.value=v}
          if(k==='instructions'&&changed)f.effective_revision='e-fx-'+(n++);
          if(k==='delegation'&&own(f,'launched'))f.pending_relaunch=f.launched!=null&&f.launched!==f.value;
        }
        if(changed)bump(cfg);
        return {ok:true,changed,applies,config:clone(cfg)};
      },
    };
  }

  const STYLE=`
.bcp-layer{position:fixed;inset:0;z-index:60;pointer-events:none}
.bcp-layer *{box-sizing:border-box}
.bcp-scrim{display:none}
.bcp-win{--bcp-ink:var(--set-ink,var(--text));--bcp-ink-2:var(--set-ink-2,var(--muted));--bcp-hair:var(--set-hair-2,var(--line));--bcp-u:8px;
  position:fixed;left:24px;top:24px;pointer-events:auto;width:min(${WIN_W}px,calc(100vw - 16px));max-height:calc(100vh - 16px);
  display:grid;grid-template-rows:auto auto minmax(0,1fr) auto;color:var(--bcp-ink);font-size:13px;line-height:1.5;
  border-radius:14px;border:1px solid color-mix(in srgb,var(--bcp-accent) 50%,transparent);
  background:linear-gradient(172deg,color-mix(in srgb,var(--bcp-accent) 11%,transparent),transparent 34%),color-mix(in srgb,var(--solid,var(--panel)) 93%,transparent);
  backdrop-filter:blur(16px);
  box-shadow:0 28px 64px -24px rgba(0,0,0,.9),0 2px 10px -4px rgba(0,0,0,.6),0 0 48px -18px color-mix(in srgb,var(--bcp-accent) 45%,transparent)}
.bcp-win.reveal{animation:bcpIn .2s cubic-bezier(.16,1,.3,1)}
.bcp-win.dragging{box-shadow:0 36px 80px -24px rgba(0,0,0,.95),0 0 0 1px var(--bcp-accent)}
@keyframes bcpIn{from{opacity:0;transform:translateY(6px) scale(.985)}}
.bcp-g{width:16px;height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.bcp-g-sm{width:13px;height:13px}.bcp-g-lg{width:22px;height:22px}
.bcp-win :focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.bcp-head{display:flex;align-items:center;gap:12px;padding:14px 12px 10px 16px;cursor:grab;user-select:none;touch-action:none}
.bcp-win.dragging .bcp-head{cursor:grabbing}
.bcp-tile{display:grid;place-items:center;width:42px;height:42px;flex:none;border-radius:50%;color:var(--bcp-accent);
  border:1px solid color-mix(in srgb,var(--bcp-accent) 60%,transparent);background:color-mix(in srgb,var(--bcp-accent) 13%,transparent)}
.bcp-titles{min-width:0;flex:1}
.bcp-titles h2{margin:0;font-size:18px;font-weight:600;line-height:1.25;letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bcp-titles h2:focus{outline:none}
.bcp-sub{margin:2px 0 0;font-size:12px;color:var(--bcp-ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bcp-sub code,.bcp-win code{font-size:11.5px;color:var(--bcp-ink-2)}
.bcp-icon{display:grid;place-items:center;width:32px;height:32px;flex:none;border-radius:8px;border:1px solid transparent;background:none;color:var(--bcp-ink-2);cursor:pointer}
.bcp-icon:hover{border-color:var(--bcp-hair);color:var(--bcp-ink)}
.bcp-grip{cursor:grab}
.bcp-badges{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;padding:0 16px 12px;border-bottom:1px solid var(--bcp-hair)}
.bcp-state-reason{flex-basis:100%;margin:0}
.bcp-state{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600}
.bcp-dot{width:8px;height:8px;border-radius:50%;flex:none}
.bcp-state.ok .bcp-dot{background:var(--ok);box-shadow:0 0 6px var(--ok)}
.bcp-state.off{color:var(--bcp-ink-2)}.bcp-state.off .bcp-dot{border:1.5px solid var(--bcp-ink-2)}
.bcp-state.shadow .bcp-dot{background:linear-gradient(90deg,var(--warn) 50%,transparent 50%);border:1.5px solid var(--warn)}
.bcp-state.bad{color:var(--danger)}.bcp-state.bad .bcp-dot{background:var(--danger);border-radius:1px;transform:rotate(45deg)}
.bcp-chip{display:inline-flex;align-items:center;gap:4px;padding:1px 8px;border:1px solid var(--bcp-hair);border-radius:999px;font-size:11px;color:var(--bcp-ink-2);white-space:nowrap}
.bcp-chip.ok{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 45%,transparent)}
.bcp-chip.lock{color:var(--bcp-ink)}
.bcp-body{overflow:auto;overscroll-behavior:contain;padding:4px 16px 12px;display:grid;gap:0;align-content:start}
.bcp-centered{gap:10px;padding:24px 16px}
.bcp-skel{display:block;height:12px;width:80%;border-radius:6px;background:color-mix(in srgb,var(--bcp-ink-2) 18%,transparent)}.bcp-skel.w2{width:55%}
.bcp-sec{display:grid;gap:8px;padding:14px 0;border-bottom:1px solid color-mix(in srgb,var(--bcp-hair) 70%,transparent)}
.bcp-sec:last-child{border-bottom:0}
.bcp-sec-head{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px}
.bcp-sec-head h3{margin:0;font-size:13px;font-weight:600;margin-right:auto}
.bcp-dirty{font-size:11px;font-weight:600;color:var(--warn)}
.bcp-mission{margin:0;max-width:62ch;color:var(--bcp-ink)}
.bcp-hint{margin:0;color:var(--bcp-ink-2);font-size:12px;display:inline-flex;gap:6px;align-items:flex-start}
p.bcp-hint{display:flex}
.bcp-hint.bad{color:var(--danger)}
.bcp-row{display:grid;gap:6px}
.bcp-label{font-size:12px;color:var(--bcp-ink-2)}
.bcp-select,.bcp-text{width:100%;min-height:36px;padding:7px 10px;border-radius:10px;border:1px solid var(--bcp-hair);
  background:color-mix(in srgb,var(--bcp-ink-2) 6%,transparent);color:var(--bcp-ink);font:inherit}
.bcp-select:disabled,.bcp-text:disabled{opacity:.6;cursor:not-allowed}
.bcp-select option{background:var(--solid,#070d13);color:var(--bcp-ink)}
.bcp-text{resize:vertical;min-height:96px;line-height:1.5}
.bcp-text.bad{border-color:var(--danger)}
.bcp-text-foot{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px}
.bcp-count{font-size:11.5px;color:var(--bcp-ink-2);font-variant-numeric:tabular-nums}.bcp-count.bad{color:var(--danger)}
.bcp-fact{margin:0;display:flex;gap:10px;align-items:baseline}.bcp-fact span{color:var(--bcp-ink-2);font-size:12px}
.bcp-unavail summary,.bcp-enf summary,.bcp-conflict summary{cursor:pointer;font-size:12px;color:var(--bcp-ink-2)}
.bcp-unavail ul,.bcp-enf ul{margin:6px 0 0;padding:0;list-style:none;display:grid;gap:6px}
.bcp-unavail li{display:grid;gap:1px}
.bcp-enf li{display:flex;gap:8px;align-items:baseline;font-size:12px}
.bcp-pre{margin:6px 0 0;padding:8px 10px;max-height:140px;overflow:auto;white-space:pre-wrap;border-radius:8px;border:1px dashed var(--bcp-hair);font:12px/1.5 inherit;color:var(--bcp-ink)}
.bcp-conflict{display:grid;gap:6px}
.bcp-segs{display:grid;gap:3px;padding:3px;border-radius:12px;border:1px solid var(--bcp-hair);background:color-mix(in srgb,var(--bcp-ink-2) 6%,transparent)}
.bcp-segs-5{grid-template-columns:repeat(5,minmax(0,1fr))}
.bcp-segs-wrap{grid-template-columns:repeat(auto-fit,minmax(110px,1fr))}
.bcp-seg{min-height:34px;padding:4px 3px;border:1px solid transparent;border-radius:9px;background:none;color:var(--bcp-ink-2);font:inherit;font-size:12px;cursor:pointer;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:background .15s,color .15s,border-color .15s}
.bcp-seg:hover:not([aria-disabled="true"]){color:var(--bcp-ink);background:color-mix(in srgb,var(--accent) 8%,transparent)}
.bcp-seg[aria-checked="true"]{color:var(--bcp-ink);font-weight:600;border-color:color-mix(in srgb,var(--accent) 60%,transparent);
  background:color-mix(in srgb,var(--accent) 18%,transparent);box-shadow:0 2px 10px -4px color-mix(in srgb,var(--accent) 60%,transparent)}
.bcp-seg[aria-disabled="true"]{cursor:not-allowed;opacity:.55}
.bcp-scale{display:flex;justify-content:space-between;font-size:11px;color:var(--bcp-ink-2);padding:0 4px;margin-top:-4px}
.bcp-pending{margin:0;display:flex;gap:6px;align-items:flex-start;padding:6px 10px;border-radius:9px;font-size:12px;color:var(--warn);
  border:1px dashed color-mix(in srgb,var(--warn) 50%,transparent);background:color-mix(in srgb,var(--warn) 6%,transparent)}
.bcp-pending span{color:var(--bcp-ink)}
.bcp-level{margin:0;font-size:12.5px;color:var(--bcp-ink-2);min-height:3em}.bcp-level strong{color:var(--bcp-ink)}
.bcp-reminder{margin:2px 0 0;display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;padding:8px 10px;border-radius:10px;border:1px solid var(--bcp-hair);font-size:12px;color:var(--bcp-ink-2)}
.bcp-reminder span{flex:1;min-width:180px}
.bcp-link{display:inline-flex;align-items:center;gap:4px;background:none;border:0;padding:0;color:var(--accent);font:inherit;font-size:12px;cursor:pointer;text-decoration:underline;text-underline-offset:3px}
.bcp-conns{display:grid;gap:6px}
.bcp-conns h4,.bcp-elsewhere h4{margin:0;font-size:12px;font-weight:600;color:var(--bcp-ink-2)}
.bcp-conns ul,.bcp-elsewhere ul{margin:0;padding:0;list-style:none;display:grid;gap:6px}
.bcp-conn{display:grid;gap:4px;padding:8px 10px;border-radius:10px;border:1px solid var(--bcp-hair);justify-items:start}
.bcp-conn.off{border-style:dashed}
.bcp-conn-main{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.bcp-dir{color:var(--accent)}
.bcp-conn-purpose{margin:0;font-size:12px}
.bcp-elsewhere ul{gap:2px}.bcp-elsewhere li{font-size:12px;color:var(--bcp-ink-2)}
.bcp-notice{display:flex;gap:10px;align-items:flex-start;margin:10px 0 0;padding:10px 12px;border-radius:10px;border:1px solid var(--bcp-hair);font-size:12.5px}
.bcp-notice p{margin:0}.bcp-notice-t{font-weight:600}
.bcp-notice.bad{border-color:color-mix(in srgb,var(--danger) 55%,transparent);background:color-mix(in srgb,var(--danger) 9%,transparent)}.bcp-notice.bad .bcp-notice-g{color:var(--danger)}
.bcp-notice.warn{border-color:color-mix(in srgb,var(--warn) 50%,transparent);background:color-mix(in srgb,var(--warn) 7%,transparent)}.bcp-notice.warn .bcp-notice-g{color:var(--warn)}
.bcp-notice.ok .bcp-notice-g{color:var(--ok)}
.bcp-code{display:block;margin-top:4px}
.bcp-foot{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 12px;padding:12px 16px;border-top:1px solid var(--bcp-hair)}
.bcp-foot-status{min-width:0;flex:1}
.bcp-foot-s{font-size:12px;color:var(--bcp-ink-2)}.bcp-foot-s.bad{color:var(--danger)}.bcp-foot-s.ok{color:var(--ok)}.bcp-foot-s.warn{color:var(--warn)}
.bcp-actions{display:flex;flex-wrap:wrap;gap:8px}
.bcp-btn{display:inline-flex;align-items:center;gap:7px;min-height:34px;padding:6px 16px;border-radius:10px;border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);
  background:color-mix(in srgb,var(--accent) 10%,transparent);color:var(--bcp-ink);font:inherit;cursor:pointer;transition:background .15s,border-color .15s}
.bcp-btn:hover:not(:disabled){background:color-mix(in srgb,var(--accent) 18%,transparent)}
.bcp-btn.primary{background:color-mix(in srgb,var(--accent) 26%,transparent);border-color:var(--accent);font-weight:600}
.bcp-btn.ghost{border-color:var(--bcp-hair);background:transparent;color:var(--bcp-ink-2)}
.bcp-btn.danger{border-color:color-mix(in srgb,var(--danger) 60%,transparent);background:color-mix(in srgb,var(--danger) 12%,transparent)}
.bcp-btn.sm{min-height:28px;padding:3px 10px;font-size:12px}
.bcp-btn:disabled{opacity:.45;cursor:not-allowed}
.bcp-confirm{position:absolute;left:12px;right:12px;bottom:12px;display:grid;gap:10px;padding:14px;border-radius:12px;border:1px solid color-mix(in srgb,var(--warn) 55%,transparent);
  background:var(--solid,var(--panel));box-shadow:0 18px 40px -12px rgba(0,0,0,.9)}
.bcp-confirm p{margin:0}
.bcp-wait{display:inline-flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:12px}
.bcp-spin{width:12px;height:12px;border-radius:50%;border:2px solid color-mix(in srgb,var(--accent) 25%,transparent);border-top-color:var(--accent);animation:bcpSpin .9s linear infinite}
.bcp-elapsed{font-variant-numeric:tabular-nums;color:var(--bcp-ink)}
@keyframes bcpSpin{to{transform:rotate(360deg)}}
.bcp-sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media (max-width:720px){
  .bcp-scrim{display:block;position:fixed;inset:0;pointer-events:auto;background:rgba(0,0,0,.5)}
  .bcp-win{left:8px!important;right:8px;top:auto!important;bottom:8px;width:auto;max-height:min(88vh,calc(100vh - 16px));border-radius:16px}
  .bcp-head{cursor:default}.bcp-grip{display:none}
  .bcp-segs-5{grid-template-columns:repeat(auto-fit,minmax(88px,1fr))}
}
@media (prefers-reduced-motion:reduce){.bcp-win,.bcp-win *{transition:none!important}.bcp-win.reveal{animation:none}.bcp-spin{animation-duration:2.4s}}
`;

  root.JarvisBrainConfigPanel=Object.freeze({open,createHttpAdapter,createFixtureAdapter,canvasReturnFocus,STYLE_ID,
    get current(){return current}});
  if(typeof module==='object'&&module&&module.exports)module.exports=root.JarvisBrainConfigPanel;
})(typeof window!=='undefined'?window:globalThis);
