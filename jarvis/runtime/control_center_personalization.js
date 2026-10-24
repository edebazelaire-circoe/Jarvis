/* Page « Personnalisation » des Réglages (refonte page par page du 2026-10-23).

   La carte Personnalisation du hub (`voice_audio`) ouvre cette page plutôt que le shell : un en-tête (fil d'Ariane,
   titre, profil actif en haut à droite) et une grille modulaire de cinq cartes de tailles différentes dont
   l'enveloppe reste un rectangle (`.perso-grid`, 12 colonnes, spans entiers).

   Rien n'est affiché qui ne soit réellement appliqué :
   - Voix : la voix et la langue de transcription de la pile vocale en service (`voice.stacks`, catalogue du
     serveur), écrites par `/api/settings` (`voice.settings.<pile>`) ; lues au prochain démarrage de Voice.
   - Personnalité : longueur et ton des réponses (`cli.behavior.fields`, choix fermés du serveur) et instructions
     personnalisées (`cli.behavior.custom_instructions`), à chaud.
   - Préférences rapides : raccourcis qui écrivent ces deux mêmes choix, jamais une autre valeur.
   - Proactivité : les rappels de rendez-vous (`agenda_reminders`), à chaud.
   - Réglages détaillés : les autres sections de la catégorie, lues au registre, ouvertes dans le shell.
   Profils (`/api/personalization/profiles`) : le profil actif, ce sont les réglages en vigueur ; en choisir un autre
   recopie son instantané (préférences de réponse et voix). Chaque contrôle s'enregistre dès qu'il change ; un refus
   remet la valeur enregistrée et se dit dans sa carte.

   Utilise `api`, `esc`, `overlay`, `settingsOverlayView`, `settingsFocusOut`, `openSettingsHub`, `openSettingsTab`,
   `settingsIcon`, `SET`, déclarations remontées du `<script>` de la page. */
(function(){
  'use strict';
  const PAGE_ID='voice_audio';
  /* Sections de la catégorie que cette page remplace : pas de ligne « Réglages détaillés » vers elles. */
  const ABSORBED=new Set(['agent_behavior']);
  /* Préférences rapides : des couples de choix fermés existants (identifiants du serveur). */
  const PRESETS=[
    {id:'concise',label:'Concis',hint:'Réponses courtes',hue:'#5aa8ff',values:{response_verbosity:'concise',politeness_formality:'direct'}},
    {id:'detailed',label:'Détaillé',hint:'Réponses complètes',hue:'#a78bfa',values:{response_verbosity:'detailed',politeness_formality:'courteous'}},
    {id:'balanced',label:'Équilibré',hint:'Ni trop, ni trop peu',hue:'#2dd4bf',values:{response_verbosity:'balanced',politeness_formality:'courteous'}},
    {id:'formal',label:'Formel',hint:'Ton professionnel',hue:'#f5b547',values:{response_verbosity:'balanced',politeness_formality:'formal'}},
  ];
  const ACCENT_HUE={blue:'#5aa8ff',violet:'#a78bfa',amber:'#f5b547',teal:'#2dd4bf',rose:'#fb7185'};
  /* Langues proposées pour la transcription (code ISO) ; une valeur enregistrée hors liste reste proposée. */
  const LANGUAGES=[['fr','Français'],['en','Anglais'],['es','Espagnol'],['de','Allemand'],['it','Italien'],['pt','Portugais'],['','Détection automatique']];
  const ICON={
    voice:'<path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4"/>',
    persona:'<path d="M9.5 4.5a2.5 2.5 0 0 0-4.6 1.4A3 3 0 0 0 3.5 11a3 3 0 0 0 1.3 4.6 2.8 2.8 0 0 0 4.7 2.9V4.5z"/><path d="M14.5 4.5a2.5 2.5 0 0 1 4.6 1.4 3 3 0 0 1 1.4 5.1 3 3 0 0 1-1.3 4.6 2.8 2.8 0 0 1-4.7 2.9V4.5z"/>',
    presets:'<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
    proactive:'<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4M8.5 14h3"/>',
    details:'<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    chevron:'<path d="M9 6l6 6-6 6"/>',caret:'<path d="M6 9l6 6 6-6"/>',check:'<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',trash:'<path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12"/>',close:'<path d="M6 6l12 12M18 6 6 18"/>',
  };
  const svg=(name,cls='')=>`<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICON[name]}</svg>`;
  const AVATAR='<svg viewBox="0 0 40 40" aria-hidden="true" focusable="false"><circle cx="20" cy="15" r="7"/><path d="M7 36c1.5-7.5 6.6-11 13-11s11.5 3.5 13 11"/></svg>';

  const P={open:false,data:null,profiles:null,error:'',menu:false,creating:false,busy:false,textTimer:null,generation:0};
  const root=()=>document.getElementById('settingsPerso');
  const grid=()=>document.getElementById('persoGrid');
  const isOpen=()=>P.open&&overlay.classList.contains('open')&&(overlay.dataset||{}).view==='perso';

  /* --- lecture des données ------------------------------------------------------------------------------------ */
  function voiceStack(){
    const voice=P.data&&P.data.voice;if(!voice)return null;
    const id=voice.effective_stack||voice.stack;
    return (voice.stacks||[]).find(s=>s.id===id)||null;
  }
  const stackField=(stack,key)=>stack?(stack.fields||[]).find(f=>f.key===key)||null:null;
  const stackValue=(stack,key)=>{const v=((P.data.voice.settings||{})[stack.id]||{})[key];return v==null?(stackField(stack,key)||{}).default:v};
  const behavior=()=>P.data.cli.behavior;
  const behaviorField=id=>(behavior().fields||[]).find(f=>f.id===id)||null;
  const optionLabel=(field,id)=>{const o=field&&(field.options||[]).find(x=>x.id===id);return o?o.label:id};
  function presetActive(preset){
    const values=behavior().values||{};
    return Object.entries(preset.values).every(([k,v])=>values[k]===v);
  }
  const usablePresets=()=>PRESETS.filter(p=>Object.entries(p.values).every(([k,v])=>(behaviorField(k)?.options||[]).some(o=>o.id===v)));
  function profileSummary(profile){
    const b=profile.values&&profile.values.behavior||{},parts=[];
    if(b.response_verbosity&&b.response_verbosity!=='inherit')parts.push(optionLabel(behaviorField('response_verbosity'),b.response_verbosity));
    if(b.politeness_formality&&b.politeness_formality!=='inherit')parts.push(optionLabel(behaviorField('politeness_formality'),b.politeness_formality));
    const stack=voiceStack(),voice=stack&&profile.values&&profile.values.voices?profile.values.voices[stack.id]:'';
    if(voice)parts.push(`voix ${voice}`);
    return parts.join(' · ')||'Réglages par défaut';
  }

  /* --- rendu ---------------------------------------------------------------------------------------------------- */
  function card({id,cls,icon,hue,title,sub,body,badge}){
    return `<section class="perso-card ${cls}" id="persoCard_${id}" aria-labelledby="persoCardTitle_${id}" style="--hue:${hue}">
      <header class="perso-card-head"><span class="perso-card-icon" aria-hidden="true">${svg(icon)}</span>
        <div class="perso-card-titles"><h3 id="persoCardTitle_${id}">${esc(title)}</h3>${sub?`<p>${esc(sub)}</p>`:''}</div>${badge||''}</header>
      <div class="perso-card-body">${body}</div>
      <p class="perso-card-status" data-card-status="${id}" role="status" aria-live="polite"></p></section>`;
  }
  function selectHtml(id,label,options,value,attrs){
    return `<label class="perso-field" for="${id}"><span class="perso-label">${esc(label)}</span>
      <span class="perso-select"><select id="${id}" ${attrs}>${options.map(([v,l])=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(l)}</option>`).join('')}</select>${svg('caret','perso-caret')}</span></label>`;
  }
  function voiceCard(){
    const stack=voiceStack(),voiceField=stackField(stack,'voice'),langField=stackField(stack,'transcription_language');
    let body;
    if(!stack||!voiceField)body='<p class="perso-empty">Aucune pile vocale en service ne propose de choix de voix.</p>';
    else{
      const voice=String(stackValue(stack,'voice')||'');
      const voices=(voiceField.options||[]).map(v=>[v,v.charAt(0).toUpperCase()+v.slice(1)]);
      body=selectHtml('persoVoice','Voix',voices,voice,`data-perso-voice="voice"`);
      if(langField){
        const lang=String(stackValue(stack,'transcription_language')??'');
        const langs=LANGUAGES.some(([v])=>v===lang)?LANGUAGES:[[lang,lang],...LANGUAGES];
        body+=selectHtml('persoLanguage','Langue de transcription',langs,lang,`data-perso-voice="transcription_language" aria-describedby="persoLanguageHint"`)
          +`<p class="perso-hint" id="persoLanguageHint">Fixée, elle évite qu’un bruit soit transcrit dans une autre langue.</p>`;
      }
      body+=`<p class="perso-meta">Pile en service : <strong>${esc(stack.label)}</strong></p>`;
    }
    return card({id:'voice',cls:'perso-voice',icon:'voice',hue:'#5aa8ff',title:'Voix',sub:'Le timbre de JARVIS et la langue de vos échanges.',body,
      badge:'<span class="perso-badge" title="Voice lit ces réglages à son démarrage">Au prochain démarrage de Voice</span>'});
  }
  function segmented(field,label){
    const values=behavior().values||{},value=values[field.id];
    return `<fieldset class="perso-seg-field"><legend class="perso-label">${esc(label)}</legend><div class="perso-seg" role="radiogroup" aria-label="${esc(label)}">`
      +(field.options||[]).map(o=>`<label class="perso-seg-opt"><input type="radio" name="perso_${esc(field.id)}" value="${esc(o.id)}" data-perso-behavior="${esc(field.id)}" ${o.id===value?'checked':''}><span>${esc(o.label)}</span></label>`).join('')
      +`</div></fieldset>`;
  }
  function personaCard(){
    const verbosity=behaviorField('response_verbosity'),formality=behaviorField('politeness_formality');
    const custom=behavior().custom_instructions||{value:'',max_length:1000};
    const value=String(custom.value||'');
    const body=(verbosity?segmented(verbosity,'Longueur des réponses'):'')+(formality?segmented(formality,'Ton et formalité'):'')
      +`<label class="perso-field perso-instructions" for="persoInstructions"><span class="perso-label">${esc(custom.label||'Instructions personnalisées')}</span>
        <textarea id="persoInstructions" maxlength="${Number(custom.max_length)||1000}" rows="4" aria-describedby="persoInstructionsHint persoInstructionsCount"
          placeholder="Ex. : adoptez un style plus technique quand je parle de développement. Donnez des exemples concrets. Évitez les réponses trop longues.">${esc(value)}</textarea>
        <span class="perso-count" id="persoInstructionsCount" aria-live="off">${value.length}/${Number(custom.max_length)||1000}</span></label>
        <p class="perso-hint" id="persoInstructionsHint">« Hériter » n’ajoute aucune consigne. Ces préférences accompagnent chaque demande à l’agent, sans redémarrage.</p>`;
    return card({id:'persona',cls:'perso-persona',icon:'persona',hue:'#a78bfa',title:'Personnalité',sub:'Le style de communication de JARVIS.',body});
  }
  function presetsCard(){
    const presets=usablePresets();
    const body=presets.length?`<div class="perso-presets">${presets.map(p=>{
      const detail=Object.entries(p.values).map(([k,v])=>optionLabel(behaviorField(k),v)).join(' · ');
      return `<button type="button" class="perso-preset" data-perso-preset="${esc(p.id)}" aria-pressed="${presetActive(p)}" aria-describedby="persoPresetDetail_${esc(p.id)}" style="--hue:${p.hue}">
        <strong>${esc(p.label)}</strong><span>${esc(p.hint)}</span><span class="perso-preset-detail" id="persoPresetDetail_${esc(p.id)}">${esc(detail)}</span></button>`}).join('')}</div>`
      :'<p class="perso-empty">Aucun préréglage ne correspond aux choix proposés par le serveur.</p>';
    return card({id:'presets',cls:'perso-presets-card',icon:'presets',hue:'#2dd4bf',title:'Préférences rapides',sub:'Règle en un clic la longueur et le ton.',body});
  }
  function agendaField(f,value,disabled){
    const id=`persoAgenda_${f.key}`,dis=disabled?'disabled':'';
    if(f.type==='boolean')return '';
    const time=/_time$/.test(f.key);
    const input=f.type==='number'
      ?`<input type="number" id="${id}" data-perso-agenda="${esc(f.key)}" value="${esc(value)}" min="${esc(f.minimum)}" max="${esc(f.maximum)}" step="${esc(f.step||1)}" ${dis}>`
      :`<input type="${time?'time':'text'}" id="${id}" data-perso-agenda="${esc(f.key)}" value="${esc(value)}" ${time?'':'inputmode="numeric" placeholder="vide = aucun"'} ${dis}>`;
    return `<div class="perso-agenda-row"><label for="${id}" title="${esc(f.help)}">${esc(f.label)}</label>${input}</div>`;
  }
  function proactiveCard(){
    const block=P.data.agenda_reminders||{fields:[]},enabled=!!block.enabled;
    const master=(block.fields||[]).find(f=>f.key==='enabled');
    const body=(master?`<div class="perso-switch-row"><div><strong id="persoAgendaLabel">${esc(master.label)}</strong><p id="persoAgendaHelp">${esc(master.help)}</p></div>
        <button type="button" class="perso-switch" role="switch" aria-checked="${enabled}" aria-labelledby="persoAgendaLabel" aria-describedby="persoAgendaHelp" data-perso-agenda-switch><span></span></button></div>`:'')
      +`<div class="perso-agenda" ${enabled?'':'data-off'}>${(block.fields||[]).map(f=>agendaField(f,block[f.key],!enabled)).join('')}</div>`;
    return card({id:'proactive',cls:'perso-proactive',icon:'proactive',hue:'#f5b547',title:'Proactivité & rappels',sub:'Ce que JARVIS vous dit de lui-même.',body,
      badge:'<span class="perso-badge live">À chaud</span>'});
  }
  function detailSections(){
    const R=window.JarvisSettingsRegistry;
    return R?R.page.sections(PAGE_ID).filter(s=>!ABSORBED.has(s.id)):[];
  }
  function detailsCard(){
    const rows=detailSections().map(s=>`<li><button type="button" class="perso-detail" data-perso-open="${esc(s.id)}">
      <span class="perso-detail-text"><strong>${esc(s.label)}</strong>${s.description?`<span>${esc(s.description)}</span>`:''}</span>${svg('chevron','perso-detail-go')}</button></li>`).join('');
    return card({id:'details',cls:'perso-details',icon:'details',hue:'#5aa8ff',title:'Réglages détaillés',sub:'Apparence, conversation, micro, tours de parole et mot d’éveil.',
      body:rows?`<ul class="perso-detail-list">${rows}</ul>`:'<p class="perso-empty">Aucune autre section.</p>'});
  }
  function profileButton(){
    const list=P.profiles?P.profiles.profiles:[],active=list.find(p=>p.active)||list[0];
    if(!active)return '';
    const hue=ACCENT_HUE[active.accent]||ACCENT_HUE.blue;
    return `<button type="button" class="perso-profile-btn" id="persoProfileBtn" aria-haspopup="true" aria-expanded="${P.menu}" aria-controls="persoProfileMenu" style="--hue:${hue}">
      <span class="perso-avatar" aria-hidden="true">${AVATAR}</span><span class="perso-profile-text"><span class="sr-only">Profil actif : </span><strong>${esc(active.name)}</strong></span>${svg('caret','perso-caret')}</button>`;
  }
  function profileMenu(){
    const state=P.profiles;if(!state)return '';
    const items=state.profiles.map(p=>{
      const hue=ACCENT_HUE[p.accent]||ACCENT_HUE.blue;
      return `<li class="perso-profile-item" style="--hue:${hue}"><button type="button" class="perso-profile-pick" data-perso-profile="${esc(p.id)}" aria-current="${p.active?'true':'false'}">
        <span class="perso-avatar small" aria-hidden="true">${AVATAR}</span><span class="perso-profile-text"><strong>${esc(p.name)}</strong><span>${esc(profileSummary(p))}</span></span>
        ${p.active?`<span class="perso-profile-check">${svg('check')}<span class="sr-only">(actif)</span></span>`:''}</button>
        ${p.active?'':`<button type="button" class="perso-profile-del" data-perso-delete="${esc(p.id)}" aria-label="Supprimer le profil ${esc(p.name)}">${svg('trash')}</button>`}</li>`;
    }).join('');
    const full=state.profiles.length>=state.max_profiles;
    const create=P.creating
      ?`<form class="perso-profile-create" id="persoProfileForm"><label class="sr-only" for="persoProfileName">Nom du nouveau profil</label>
          <input id="persoProfileName" maxlength="${state.max_name_chars}" placeholder="Nom du profil" autocomplete="off" required>
          <button type="submit" class="perso-mini primary">Créer</button><button type="button" class="perso-mini" data-perso-create-cancel>Annuler</button>
          <p class="perso-hint">Le nouveau profil part de vos réglages actuels.</p></form>`
      :`<button type="button" class="perso-profile-new" data-perso-create ${full?'disabled':''}>${svg('plus')}<span>${full?`${state.max_profiles} profils au plus`:'Créer un profil'}</span></button>`;
    return `<div class="perso-profile-menu" id="persoProfileMenu" ${P.menu?'':'hidden'}>
      <p class="perso-profile-menu-head">Profils</p><ul class="perso-profile-list" aria-label="Profils de personnalisation">${items}</ul>
      ${create}<p class="perso-card-status" data-card-status="profile" role="status" aria-live="polite"></p></div>`;
  }
  function renderProfile(){
    const host=document.getElementById('persoProfile');if(!host)return;
    host.innerHTML=profileButton()+profileMenu();
  }
  function render(){
    const host=grid();if(!host)return;
    const focusKey=focusKeyOf(document.activeElement);
    renderProfile();
    if(P.error){host.innerHTML=`<div class="perso-load-error" role="alert"><p>${esc(P.error)}</p><button type="button" class="perso-mini primary" data-perso-retry>Réessayer</button></div>`;return}
    if(!P.data){host.innerHTML='<p class="perso-loading">Chargement…</p>';return}
    host.innerHTML=voiceCard()+personaCard()+presetsCard()+detailsCard()+proactiveCard();
    restoreFocus(focusKey);
  }
  function focusKeyOf(el){
    if(!el||!root()||!root().contains(el))return null;
    if(el.id)return '#'+el.id;
    for(const attr of ['data-perso-preset','data-perso-open','data-perso-profile','data-perso-delete']){
      if(el.hasAttribute(attr))return `[${attr}="${el.getAttribute(attr)}"]`;
    }
    if(el.name&&el.value!=null)return `input[name="${el.name}"][value="${el.value}"]`;
    return null;
  }
  function restoreFocus(key){
    if(!key)return;
    const el=root().querySelector(key);
    if(el&&el.focus)el.focus({preventScroll:true});
  }
  function status(id,text,kind){
    const el=root()&&root().querySelector(`[data-card-status="${id}"]`);if(!el)return;
    el.textContent=text||'';el.dataset.kind=kind||'';el.setAttribute('role',kind==='error'?'alert':'status');
    clearTimeout(el._t);if(kind==='ok')el._t=setTimeout(()=>{el.textContent='';el.dataset.kind=''},2400);
  }

  /* --- enregistrement ------------------------------------------------------------------------------------------- */
  /* Le brouillon du shell (Réglages détaillés), s'il porte des modifications non enregistrées, reçoit les valeurs
     qui viennent d'être écrites : son « Enregistrer » ne les remettrait pas en arrière. Sans modification, le shell
     relit les réglages à son ouverture. */
  function patchShellDraft(data){
    if(typeof SET==='undefined'||!SET.draft||!SET.dirty)return;
    SET.draft.cli.behavior=JSON.parse(JSON.stringify(data.cli.behavior.values));
    SET.draft.voice.settings=JSON.parse(JSON.stringify(data.voice.settings));
    for(const f of (data.agenda_reminders&&data.agenda_reminders.fields)||[])SET.draft.agenda_reminders[f.key]=data.agenda_reminders[f.key];
  }
  async function save(cardId,payload,{rerender=false}={}){
    const generation=P.generation;
    status(cardId,'Enregistrement…','busy');
    try{
      const data=await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if(generation!==P.generation)return;
      P.data=data;patchShellDraft(data);
      if(P.profiles)await refreshProfiles(generation);
      if(rerender)render();else{syncPresets();renderProfile()}
      status(cardId,'Enregistré.','ok');
      console.info('[settings] personalization.saved',{card:cardId,keys:Object.keys(payload)});
    }catch(e){
      if(generation!==P.generation)return;
      console.warn('[settings] personalization.save_failed',{card:cardId,code:e.code||null,error:e.message});
      render();  // la valeur enregistrée revient dans le contrôle
      status(cardId,e.message||'Enregistrement impossible.','error');
    }
  }
  async function refreshProfiles(generation){
    try{const state=await api('/api/personalization/profiles');if(generation===P.generation)P.profiles=state}
    catch(e){console.warn('[settings] personalization.profiles_failed',{error:e.message})}
  }
  function syncPresets(){
    for(const p of PRESETS){
      const btn=root().querySelector(`[data-perso-preset="${p.id}"]`);
      if(btn)btn.setAttribute('aria-pressed',String(presetActive(p)));
    }
  }
  function saveBehavior(cardId,values,options){return save(cardId,{cli:{behavior:values}},options)}
  function saveInstructions(){
    clearTimeout(P.textTimer);P.textTimer=null;
    const area=document.getElementById('persoInstructions');if(!area||!P.data)return Promise.resolve();
    const value=area.value.trim();
    if(value===String((behavior().custom_instructions||{}).value||''))return Promise.resolve();
    return saveBehavior('persona',{custom_instructions:value});
  }
  async function profileAction(body,okText){
    if(P.busy)return;
    P.busy=true;const generation=P.generation;status('profile','…','busy');
    try{
      await saveInstructions();
      const result=await api('/api/personalization/profiles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(generation!==P.generation)return;
      P.profiles=result.profiles;P.data=result.settings;patchShellDraft(result.settings);P.creating=false;
      render();
      status('profile',okText+(result.voice_restart?' La nouvelle voix s’entendra au prochain démarrage de Voice.':''),'ok');
      console.info('[settings] personalization.profile',{action:body.action,active:result.profiles.active});
      return result;
    }catch(e){
      if(generation!==P.generation)return;
      console.warn('[settings] personalization.profile_failed',{action:body.action,code:e.code||null,error:e.message});
      status('profile',e.message||'Action impossible.','error');
    }finally{P.busy=false}
  }

  /* --- ouverture / fermeture --------------------------------------------------------------------------------------- */
  async function load(){
    const generation=++P.generation;P.error='';
    if(!P.data)render();
    try{
      const [data,profiles]=await Promise.all([api('/api/settings'),api('/api/personalization/profiles')]);
      if(generation!==P.generation)return;
      P.data=data;P.profiles=profiles;
    }catch(e){
      if(generation!==P.generation)return;
      P.error=`Réglages illisibles : ${e.message}`;
      console.warn('[settings] personalization.load_failed',{error:e.message});
    }
    render();
  }
  function open(){
    P.open=true;P.menu=false;P.creating=false;P.data=null;P.profiles=null;
    overlay.classList.add('instant');settingsOverlayView('perso');overlay.classList.add('open');
    const page=root();if(page)page.scrollTop=0;
    console.info('[settings] personalization.opened',{});
    const loading=load();
    const crumb=document.getElementById('persoCrumbHub');if(crumb)crumb.focus({preventScroll:true});
    return loading;
  }
  function leave(){
    if(!P.open)return;
    saveInstructions().catch(()=>{});
    P.open=false;P.menu=false;++P.generation;
  }
  function close(){
    if(!isOpen())return;
    leave();overlay.classList.remove('open','instant');settingsOverlayView(null);settingsFocusOut();
  }
  function backToHub(){
    if(!isOpen())return;
    leave();openSettingsHub({instant:true});
  }
  function openDetail(section){
    leave();
    const opener=SET.opener;SET.opener=null;
    settingsOverlayView('shell');
    console.info('[settings] personalization.detail',{section});
    return openSettingsTab(section,{returnFocus:opener});
  }
  function setMenu(openMenu,{focus=true}={}){
    P.menu=openMenu;if(!openMenu)P.creating=false;
    renderProfile();
    const btn=document.getElementById('persoProfileBtn');
    if(openMenu){const first=root().querySelector('.perso-profile-pick[aria-current="true"]')||root().querySelector('.perso-profile-pick');if(focus&&first)first.focus()}
    else if(focus&&btn)btn.focus();
  }

  /* --- événements --------------------------------------------------------------------------------------------- */
  function bind(){
    const page=root();if(!page||page.dataset.bound)return;page.dataset.bound='1';
    document.getElementById('persoClose').addEventListener('click',close);
    document.getElementById('persoCrumbHub').addEventListener('click',backToHub);
    page.addEventListener('click',event=>{
      const t=event.target.closest('button');if(!t||!page.contains(t))return;
      if(t.id==='persoProfileBtn'){setMenu(!P.menu);return}
      if(t.dataset.persoProfile){const p=P.profiles.profiles.find(x=>x.id===t.dataset.persoProfile);
        if(p&&!p.active)profileAction({action:'select',id:p.id},`Profil « ${p.name} » actif.`).then(()=>setMenu(false));else setMenu(false);return}
      if(t.dataset.persoDelete){const p=P.profiles.profiles.find(x=>x.id===t.dataset.persoDelete);
        if(p)profileAction({action:'delete',id:p.id},`Profil « ${p.name} » supprimé.`).then(()=>{if(P.menu){const b=root().querySelector('[data-perso-create]')||document.getElementById('persoProfileBtn');if(b)b.focus()}});return}
      if(t.hasAttribute('data-perso-create')){P.creating=true;renderProfile();const i=document.getElementById('persoProfileName');if(i)i.focus();return}
      if(t.hasAttribute('data-perso-create-cancel')){P.creating=false;renderProfile();const b=root().querySelector('[data-perso-create]');if(b)b.focus();return}
      if(t.dataset.persoPreset){const p=PRESETS.find(x=>x.id===t.dataset.persoPreset);if(p)saveBehavior('presets',{...p.values},{rerender:true});return}
      if(t.dataset.persoOpen){openDetail(t.dataset.persoOpen);return}
      if(t.hasAttribute('data-perso-agenda-switch')){
        const next=t.getAttribute('aria-checked')!=='true';
        save('proactive',{agenda_reminders:{enabled:next}},{rerender:true});return}
      if(t.hasAttribute('data-perso-retry')){load();return}
    });
    page.addEventListener('submit',event=>{
      if(event.target.id!=='persoProfileForm')return;
      event.preventDefault();
      const name=document.getElementById('persoProfileName').value;
      profileAction({action:'create',name},`Profil « ${name.trim()} » créé et actif.`).then(r=>{if(r){P.menu=true;renderProfile();const b=document.getElementById('persoProfileBtn');if(b)b.focus()}});
    });
    page.addEventListener('change',event=>{
      const t=event.target;
      if(t.dataset.persoVoice){
        const stack=voiceStack();if(!stack)return;
        save('voice',{voice:{settings:{[stack.id]:{[t.dataset.persoVoice]:t.value}}}});return}
      if(t.dataset.persoBehavior){saveBehavior('persona',{[t.dataset.persoBehavior]:t.value});return}
      if(t.dataset.persoAgenda){const v=t.type==='number'?Number(t.value):t.value;save('proactive',{agenda_reminders:{[t.dataset.persoAgenda]:v}});return}
    });
    page.addEventListener('input',event=>{
      if(event.target.id!=='persoInstructions')return;
      const area=event.target,count=document.getElementById('persoInstructionsCount');
      if(count)count.textContent=`${area.value.length}/${area.maxLength}`;
      clearTimeout(P.textTimer);P.textTimer=setTimeout(()=>saveInstructions(),1200);
    });
    page.addEventListener('focusout',event=>{if(event.target.id==='persoInstructions')saveInstructions()});
    /* Clic hors du panneau des profils : il se replie sans voler le focus. */
    page.addEventListener('pointerdown',event=>{
      if(P.menu&&!event.target.closest('#persoProfile'))setMenu(false,{focus:false});
    });
    page.addEventListener('keydown',event=>{
      if(event.key==='Escape'){
        event.preventDefault();event.stopPropagation();
        if(P.menu){setMenu(false);return}
        close();return;
      }
      if(P.menu&&(event.key==='ArrowDown'||event.key==='ArrowUp')&&event.target.closest('.perso-profile-list')){
        const picks=[...page.querySelectorAll('.perso-profile-pick')],at=picks.indexOf(event.target);
        if(at>=0){event.preventDefault();picks[(at+(event.key==='ArrowDown'?1:-1)+picks.length)%picks.length].focus()}
        return;
      }
      if(event.key!=='Tab')return;
      /* aria-modal : Tab et Maj+Tab bouclent dans la page. */
      const items=[...page.querySelectorAll('button,select,textarea,input,[tabindex]:not([tabindex="-1"])')]
        .filter(el=>!el.disabled&&el.offsetParent!==null&&!(el.type==='radio'&&!el.checked&&page.querySelector(`input[name="${el.name}"]:checked`)));
      if(!items.length)return;
      const first=items[0],last=items[items.length-1];
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
    });
  }

  window.JarvisPersonalization=Object.freeze({PAGE_ID,PRESETS,open:()=>{bind();return open()},close,backToHub,isOpen});
})();
