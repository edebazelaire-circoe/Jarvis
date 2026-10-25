/* Page « Personnalisation » des Réglages (refonte page par page du 2026-10-23 ; composition de la maquette
   `01-personnalisation.png` et primitives partagées `.set-*` depuis la Slice 02 de refonte-ui-settings, 2026-10-24).

   Contrat : `docs/settings/personalization-page.md`. La carte Personnalisation du hub (`voice_audio`) ouvre cette page
   plutôt que le shell : un en-tête (fil d'Ariane, titre, profil actif en haut à droite, panneau flottant des profils)
   et trois colonnes de panneaux verre (`JarvisSettingsUI.panel`) dont l'enveloppe reste un rectangle :
   Voix + Réglages détaillés | Personnalité + Préférences rapides | Proactivité & rappels.

   Rien n'est affiché qui ne soit réellement appliqué :
   - Voix : la voix et la langue de transcription de la pile vocale en service (`voice.stacks`, catalogue du
     serveur), écrites par `/api/settings` (`voice.settings.<pile>`) ; lues au prochain démarrage de Voice.
   - Personnalité : longueur et ton des réponses (`cli.behavior.fields`, choix fermés du serveur) présentés en
     curseurs à crans (un cran = une option du serveur, dans son ordre ; « Hériter » est un bouton à part) et
     instructions personnalisées (`cli.behavior.custom_instructions`), à chaud.
   - Préférences rapides : raccourcis qui écrivent ces deux mêmes choix, jamais une autre valeur.
   - Proactivité : les rappels de rendez-vous (`agenda_reminders`), à chaud.
   - Réglages détaillés : les autres sections de la catégorie, lues au registre, ouvertes dans le shell.
   Profils (`/api/personalization/profiles`) : le profil actif, ce sont les réglages en vigueur ; en choisir un autre
   recopie son instantané (préférences de réponse et voix). Chaque contrôle s'enregistre dès qu'il change ; un refus
   remet la valeur enregistrée et se dit dans sa carte. Toute attente a une échéance (`DEADLINE_MS`).

   Utilise `api`, `esc`, `overlay`, `settingsOverlayView`, `settingsFocusOut`, `openSettingsHub`, `openSettingsTab`,
   `SET`, déclarations remontées du `<script>` de la page, et `window.JarvisSettingsUI` (primitives partagées). */
(function(){
  'use strict';
  const UI=window.JarvisSettingsUI;
  const PAGE_ID='voice_audio';
  /* Sections de la catégorie que cette page remplace : pas de ligne « Réglages détaillés » vers elles. */
  const ABSORBED=new Set(['agent_behavior']);
  const INHERIT='inherit';
  /* Au-delà, une lecture ou un enregistrement sans réponse est dit en échec (jamais « Enregistrement… » sans fin). */
  const DEADLINE_MS=15000;
  /* Préférences rapides : des couples de choix fermés existants (identifiants du serveur). */
  const PRESETS=[
    {id:'concise',label:'Concis',hint:'Réponses courtes',tone:'blue',icon:'doc',values:{response_verbosity:'concise',politeness_formality:'direct'}},
    {id:'detailed',label:'Détaillé',hint:'Réponses complètes',tone:'violet',icon:'docs',values:{response_verbosity:'detailed',politeness_formality:'courteous'}},
    {id:'balanced',label:'Équilibré',hint:'Ni trop, ni trop peu',tone:'teal',icon:'balance',values:{response_verbosity:'balanced',politeness_formality:'courteous'}},
    {id:'formal',label:'Formel',hint:'Ton professionnel',tone:'amber',icon:'tie',values:{response_verbosity:'balanced',politeness_formality:'formal'}},
  ];
  /* Curseurs à crans de la carte Personnalité : un champ `cli.behavior.fields` chacun, libellé de la page. */
  const TRAITS=[{id:'response_verbosity',label:'Longueur des réponses'},{id:'politeness_formality',label:'Ton et formalité'}];
  const ACCENT_TONE={blue:'blue',violet:'violet',amber:'amber',teal:'teal',rose:'magenta'};
  /* Langues proposées pour la transcription (code ISO) ; une valeur enregistrée hors liste reste proposée. */
  const LANGUAGES=[['fr','Français'],['en','Anglais'],['es','Espagnol'],['de','Allemand'],['it','Italien'],['pt','Portugais'],['','Détection automatique']];
  const ICON={
    voice:'<path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4"/>',
    globe:'<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.6 3.5 5.4 3.5 8.5s-1.1 5.9-3.5 8.5c-2.4-2.6-3.5-5.4-3.5-8.5s1.1-5.9 3.5-8.5z"/>',
    persona:'<path d="M9.5 4.5a2.5 2.5 0 0 0-4.6 1.4A3 3 0 0 0 3.5 11a3 3 0 0 0 1.3 4.6 2.8 2.8 0 0 0 4.7 2.9V4.5z"/><path d="M14.5 4.5a2.5 2.5 0 0 1 4.6 1.4 3 3 0 0 1 1.4 5.1 3 3 0 0 1-1.3 4.6 2.8 2.8 0 0 1-4.7 2.9V4.5z"/>',
    presets:'<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
    proactive:'<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/>',
    details:'<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    bell:'<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    clock:'<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    sun:'<circle cx="12" cy="12" r="3.5"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>',
    moon:'<path d="M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5z"/>',
    late:'<circle cx="12" cy="13" r="7.5"/><path d="M12 9.5V13M12 16.2v.3M9 2.5h6"/>',
    refresh:'<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v3.5H16"/>',
    reset:'<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4.5v3.5H8"/>',
    doc:'<path d="M7 3.5h7l4 4v13H7z"/><path d="M14 3.5v4h4M9.5 12h6M9.5 15.5h4"/>',
    docs:'<path d="M7 3.5h7l4 4v13H7z"/><path d="M14 3.5v4h4M9.5 11h6M9.5 14h6M9.5 17h6"/>',
    balance:'<path d="M12 4v16M6 20h12M5 8h14M5 8l-2.5 6a3 3 0 0 0 5 0zM19 8l-2.5 6a3 3 0 0 0 5 0z"/>',
    tie:'<path d="M9.5 3.5h5l-1.2 3 2.2 10-3.5 4-3.5-4 2.2-10z"/>',
    chevron:'<path d="M9 6l6 6-6 6"/>',caret:'<path d="M6 9l6 6 6-6"/>',check:'<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',trash:'<path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12"/>',
  };
  const AGENDA_ICON={enabled:'bell',lead_minutes:'clock',morning_time:'sun',evening_time:'moon',late_minutes:'late',refresh_minutes:'refresh'};
  const svg=(name,cls='')=>`<svg${cls?` class="${cls}"`:''} viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICON[name]||ICON.details}</svg>`;
  const AVATAR='<svg viewBox="0 0 40 40" aria-hidden="true" focusable="false"><circle cx="20" cy="15" r="7"/><path d="M7 36c1.5-7.5 6.6-11 13-11s11.5 3.5 13 11"/></svg>';

  const P={open:false,data:null,profiles:null,error:'',menu:false,creating:false,busy:false,textTimer:null,textSaving:0,generation:0,closeMenu:null,unbind:null};
  const root=()=>document.getElementById('settingsPerso');
  const grid=()=>document.getElementById('persoGrid');
  const isOpen=()=>P.open&&overlay.classList.contains('open')&&(overlay.dataset||{}).view==='perso';

  /* Une promesse qui échoue après `DEADLINE_MS` : une attente a toujours une fin, dite dans les mots de l'utilisateur. */
  function withDeadline(promise,what){
    let timer;
    const late=new Promise((_,reject)=>{timer=setTimeout(()=>{
      const e=new Error(`${what} : pas de réponse du Control Center après ${DEADLINE_MS/1000} s.`);e.code='personalization_timeout';reject(e)},DEADLINE_MS)});
    return Promise.race([promise,late]).finally(()=>clearTimeout(timer));
  }

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
  /* Les crans d'un curseur : les options du serveur, dans son ordre, sans « Hériter » (bouton à part). */
  const steps=field=>(field.options||[]).filter(o=>o.id!==INHERIT);
  function presetActive(preset){
    const values=behavior().values||{};
    return Object.entries(preset.values).every(([k,v])=>values[k]===v);
  }
  const usablePresets=()=>PRESETS.filter(p=>Object.entries(p.values).every(([k,v])=>(behaviorField(k)?.options||[]).some(o=>o.id===v)));
  function profileSummary(profile){
    const b=profile.values&&profile.values.behavior||{},parts=[];
    if(b.response_verbosity&&b.response_verbosity!==INHERIT)parts.push(optionLabel(behaviorField('response_verbosity'),b.response_verbosity));
    if(b.politeness_formality&&b.politeness_formality!==INHERIT)parts.push(optionLabel(behaviorField('politeness_formality'),b.politeness_formality));
    const stack=voiceStack(),voice=stack&&profile.values&&profile.values.voices?profile.values.voices[stack.id]:'';
    if(voice)parts.push(`voix ${voice}`);
    return parts.join(' · ')||'Réglages par défaut';
  }

  /* --- rendu ---------------------------------------------------------------------------------------------------- */
  const statusLine=id=>`<p class="perso-status" data-card-status="${id}" role="status" aria-live="polite"></p>`;
  function voiceCard(){
    const stack=voiceStack(),voiceField=stackField(stack,'voice'),langField=stackField(stack,'transcription_language');
    let body;
    if(!stack||!voiceField)body=UI.notice({kind:'info',text:'Aucune pile vocale en service ne propose de choix de voix.'});
    else{
      const voice=String(stackValue(stack,'voice')||'');
      const voices=(voiceField.options||[]).map(v=>({value:v,label:v.charAt(0).toUpperCase()+v.slice(1)}));
      let rows=UI.row({id:'persoVoiceRow',label:'Voix',icon:svg('voice'),wide:true,
        control:UI.select({id:'persoVoice',options:voices,value:voice,labelledBy:'persoVoiceRow-label',data:{'perso-voice':'voice'}})});
      if(langField){
        const lang=String(stackValue(stack,'transcription_language')??'');
        const langs=(LANGUAGES.some(([v])=>v===lang)?LANGUAGES:[[lang,lang],...LANGUAGES]).map(([value,label])=>({value,label}));
        rows+=UI.row({id:'persoLanguageRow',label:'Langue',icon:svg('globe'),wide:true,
          control:UI.select({id:'persoLanguage',options:langs,value:lang,labelledBy:'persoLanguageRow-label',describedBy:'persoLanguageHint',data:{'perso-voice':'transcription_language'}})});
      }
      body=`<div class="set-rows perso-voice-rows">${rows}</div>`
        +(langField?'<p class="perso-hint" id="persoLanguageHint">Fixée, la langue évite qu’un bruit soit transcrit dans une autre.</p>':'')
        +`<p class="perso-meta"><span>Pile en service : <strong>${esc(stack.label)}</strong></span>${UI.appliesBadge('next_voice_start')}</p>`;
    }
    return UI.panel({id:'persoCard_voice',title:'Voix',description:'Le timbre de JARVIS et la langue de vos échanges.',icon:svg('voice'),tone:'blue',
      body:body+statusLine('voice')});
  }
  /* Texte d'un cran : le libellé du serveur ; en « Hériter », le cran médian affiché dit « Hériter : aucune consigne ». */
  function traitText(field,index){
    const opts=steps(field),value=(behavior().values||{})[field.id]||INHERIT;
    if(value===INHERIT&&Number(index)===Math.floor((opts.length-1)/2))return optionLabel(field,INHERIT);
    return (opts[Number(index)]||{}).label||'';
  }
  function trait(field,label){
    const values=behavior().values||{},value=values[field.id]||INHERIT,opts=steps(field);
    if(!opts.length)return '';
    const inherit=value===INHERIT,index=inherit?Math.floor((opts.length-1)/2):Math.max(0,opts.findIndex(o=>o.id===value));
    const id=`persoTrait_${field.id}`,text=traitText(field,index);
    return `<div class="perso-trait"${inherit?' data-inherit':''}>`
      +`<span class="perso-trait-label" id="${id}-label">${esc(label)}</span><span class="perso-trait-value" id="${id}-hint">${esc(text)}</span>`
      +UI.range({id,min:0,max:opts.length-1,step:1,value:index,labelledBy:`${id}-label`,describedBy:`${id}-hint`,
        minLabel:opts[0].label,maxLabel:opts[opts.length-1].label,inlineEnds:true,showValue:false,format:()=>text,data:{'perso-trait':field.id}})
      +UI.button({label:`${optionLabel(field,INHERIT)} : aucune consigne de ${label.toLowerCase()}`,variant:'ghost',size:'sm',iconOnly:true,icon:svg('reset'),
        disabled:inherit,data:{'perso-inherit':field.id}})
      +'</div>';
  }
  function personaCard(){
    const traits=TRAITS.map(t=>{const f=behaviorField(t.id);return f?trait(f,t.label):''}).join('');
    const custom=behavior().custom_instructions||{value:'',max_length:1000};
    const max=Number(custom.max_length)||1000;
    const body=`<div class="perso-persona">${traits||UI.notice({kind:'info',text:'Le serveur ne propose aucun choix de style.'})}</div>`
      +`<div class="perso-instructions"><span class="perso-label" id="persoInstructions-label">${esc(custom.label||'Instructions personnalisées')}</span>`
      +UI.textarea({id:'persoInstructions',value:String(custom.value||''),maxLength:max,rows:3,labelledBy:'persoInstructions-label',describedBy:'persoInstructionsHint',
        placeholder:'Ex. : adoptez un style plus technique quand je parle de développement. Donnez des exemples concrets. Évitez les réponses trop longues.'})
      +`<p class="perso-hint" id="persoInstructionsHint">Appliquées sans redémarrage. « Hériter » n’ajoute aucune consigne.</p></div>`;
    return UI.panel({id:'persoCard_persona',title:'Personnalité',description:'Le style de communication de JARVIS.',icon:svg('persona'),tone:'violet',
      body:body+statusLine('persona')});
  }
  function presetsCard(){
    const presets=usablePresets();
    const body=presets.length?`<fieldset class="set-choices perso-presets"><legend class="sr-only">Préférences rapides</legend>${presets.map(p=>{
      const detail=Object.entries(p.values).map(([k,v])=>optionLabel(behaviorField(k),v)).join(' · ');
      return `<label class="set-choice set-tone-${p.tone}" title="${esc(detail)}"><input type="radio" name="perso_preset" value="${esc(p.id)}" data-perso-preset="${esc(p.id)}"${presetActive(p)?' checked':''} aria-describedby="persoPresetDetail_${esc(p.id)}">`
        +`<span class="set-choice-icon" aria-hidden="true">${svg(p.icon)}</span><span class="set-choice-text"><span class="set-choice-title">${esc(p.label)}</span>`
        +`<span class="set-choice-desc">${esc(p.hint)}</span><span class="sr-only" id="persoPresetDetail_${esc(p.id)}">${esc(detail)}</span></span></label>`}).join('')}</fieldset>`
      :UI.notice({kind:'info',text:'Aucun préréglage ne correspond aux choix proposés par le serveur.'});
    return UI.panel({id:'persoCard_presets',title:'Préférences rapides',description:'Règlent en un clic la longueur et le ton ci-dessus.',icon:svg('presets'),tone:'blue',
      body:body+statusLine('presets')});
  }
  function agendaRow(f,value,disabled){
    const id=`persoAgenda_${f.key}`,time=/_time$/.test(f.key),aria=`aria-labelledby="${id}Row-label" aria-describedby="${id}Row-hint"${disabled?' disabled':''}`;
    const input=f.type==='number'
      ?`<input type="number" class="set-input" id="${id}" data-perso-agenda="${esc(f.key)}" value="${esc(value)}" min="${esc(f.minimum)}" max="${esc(f.maximum)}" step="${esc(f.step||1)}" ${aria}>`
      :`<input type="${time?'time':'text'}" class="set-input" id="${id}" data-perso-agenda="${esc(f.key)}" value="${esc(value)}" ${time?'':'inputmode="numeric" placeholder="vide = aucun" '}${aria}>`;
    return UI.row({id:`${id}Row`,label:f.label,hint:f.help,icon:svg(AGENDA_ICON[f.key]),control:input});
  }
  function proactiveCard(){
    const block=P.data.agenda_reminders||{fields:[]},enabled=!!block.enabled,fields=block.fields||[];
    const master=fields.find(f=>f.key==='enabled');
    const body=(master?`<div class="set-rows perso-master">${UI.row({id:'persoAgendaEnabled',label:master.label,hint:master.help,icon:svg('bell'),
        control:UI.toggle({id:'persoAgendaSwitch',checked:enabled,labelledBy:'persoAgendaEnabled-label',describedBy:'persoAgendaEnabled-hint',stateText:{on:'Activés',off:'Coupés'},data:{'perso-agenda-switch':'1'}})})}</div>`:'')
      +`<div class="set-rows perso-agenda"${enabled?'':' data-off'}>${fields.filter(f=>f.type!=='boolean').map(f=>agendaRow(f,block[f.key],!enabled)).join('')}</div>`;
    return UI.panel({id:'persoCard_proactive',title:'Proactivité & rappels',description:'Ce que JARVIS vous dit de lui-même.',icon:svg('proactive'),tone:'blue',
      body:body+statusLine('proactive')});
  }
  function detailSections(){
    const R=window.JarvisSettingsRegistry;
    return R?R.page.sections(PAGE_ID).filter(s=>!ABSORBED.has(s.id)):[];
  }
  function detailsCard(){
    const rows=detailSections().map(s=>`<li><button type="button" class="set-row perso-detail" data-perso-open="${esc(s.id)}"${s.description?` title="${esc(s.description)}"`:''}>`
      +`<span class="set-row-text"><span class="set-row-label">${esc(s.label)}</span>`
      +`</span>${svg('chevron','perso-detail-go')}</button></li>`).join('');
    return UI.panel({id:'persoCard_details',title:'Réglages détaillés',description:'Apparence, conversation, micro, tours de parole et mot d’éveil.',icon:svg('details'),tone:'cyan',
      body:rows?`<ul class="set-rows perso-detail-list">${rows}</ul>`:UI.notice({kind:'info',text:'Aucune autre section.'})});
  }
  /* Liaisons des curseurs et du compteur d'un rendu neuf (le texte d'un cran est un libellé, pas l'indice). */
  function bindControls(host){
    if(P.unbind)P.unbind();
    const off=[...host.querySelectorAll('input[data-perso-trait]')].map(input=>{
      const field=behaviorField(input.dataset.persoTrait);
      return UI.bindRange(input,{format:v=>traitText(field,v),onInput:(_v,text)=>{const hint=document.getElementById(`${input.id}-hint`);if(hint)hint.textContent=text}});
    });
    const area=document.getElementById('persoInstructions');if(area)off.push(UI.bindCounter(area));
    /* Les aides des rappels sont coupées à deux lignes : le texte entier en info-bulle (les lecteurs d'écran le lisent
       déjà en entier par `aria-describedby`). */
    host.querySelectorAll('.perso-agenda .set-row-hint,.perso-master .set-row-hint').forEach(h=>{h.title=h.textContent.trim()});
    P.unbind=()=>{off.forEach(fn=>fn());P.unbind=null};
  }
  function render(){
    const host=grid();if(!host)return;
    renderProfile();
    /* Un texte en cours de frappe ou en cours d'envoi survit au rendu d'une autre carte (sinon l'ancienne valeur revenait
       dans le champ pendant l'envoi, puis repartait au serveur à la sortie du champ). Un refus, lui, remet la valeur
       enregistrée : `save` décompte `textSaving` (un compteur : plusieurs envois du texte peuvent se chevaucher) avant de redessiner. */
    const typing=document.getElementById('persoInstructions'),draft=typing&&(P.textTimer||P.textSaving>0)?typing.value:null;
    UI.keepFocus(root(),()=>{
      if(P.unbind)P.unbind();
      if(P.error){
        host.setAttribute('aria-busy','false');
        host.innerHTML=`<div class="perso-state" data-perso-state="error">${UI.notice({kind:'bad',live:'assertive',title:'Réglages illisibles',text:P.error})}`
          +UI.button({label:'Réessayer',variant:'primary',data:{'perso-retry':'1'}})+'</div>';
        return;
      }
      if(!P.data){
        host.setAttribute('aria-busy','true');
        host.innerHTML=`<div class="perso-state" data-perso-state="loading">${UI.notice({kind:'info',live:'polite',text:`Chargement des réglages… (au plus ${DEADLINE_MS/1000} s)`})}</div>`;
        return;
      }
      host.setAttribute('aria-busy','false');
      host.innerHTML=`<div class="set-stack set-span-4 perso-col perso-col-left">${voiceCard()}${detailsCard()}</div>`
        +`<div class="set-stack set-span-4 perso-col perso-col-center">${personaCard()}${presetsCard()}</div>`
        +`<div class="set-stack set-span-4 perso-col perso-col-right">${proactiveCard()}</div>`;
      if(draft!==null){const area=document.getElementById('persoInstructions');if(area)area.value=draft}
      bindControls(host);
    });
  }
  function status(id,text,kind){
    const el=root()&&root().querySelector(`[data-card-status="${id}"]`);if(!el)return;
    el.textContent=text||'';el.dataset.kind=kind||'';el.setAttribute('role',kind==='error'?'alert':'status');
    clearTimeout(el._t);if(kind==='ok')el._t=setTimeout(()=>{el.textContent='';el.dataset.kind=''},2400);
  }

  /* --- profils : bouton en haut à droite et panneau flottant (`JarvisSettingsUI.float` + `openFloat`) -------------- */
  function profileMenuBody(){
    const state=P.profiles;
    const items=state.profiles.map(p=>`<li class="perso-profile-item set-tone-${ACCENT_TONE[p.accent]||'blue'}"><button type="button" class="perso-profile-pick" data-perso-profile="${esc(p.id)}" aria-current="${p.active?'true':'false'}">`
      +`${UI.medallion({icon:AVATAR,size:'sm'})}<span class="perso-profile-text"><strong>${esc(p.name)}</strong><span>${esc(profileSummary(p))}</span></span>`
      +(p.active?`<span class="perso-profile-check">${svg('check')}<span class="sr-only">(actif)</span></span>`:'')+'</button>'
      +(p.active?'':UI.button({label:`Supprimer le profil ${p.name}`,variant:'ghost',size:'sm',iconOnly:true,tone:'bad',icon:svg('trash'),data:{'perso-delete':p.id}}))+'</li>').join('');
    const full=state.profiles.length>=state.max_profiles;
    const create=P.creating
      ?`<form class="perso-profile-create" id="persoProfileForm"><label class="sr-only" for="persoProfileName">Nom du nouveau profil</label>`
        +`<input class="set-input" id="persoProfileName" maxlength="${Number(state.max_name_chars)||40}" placeholder="Nom du profil" autocomplete="off" required aria-describedby="persoProfileCreateHint">`
        +UI.button({label:'Créer',variant:'primary',size:'sm',type:'submit'})+UI.button({label:'Annuler',size:'sm',data:{'perso-create-cancel':'1'}})
        +'<p class="perso-hint" id="persoProfileCreateHint">Le nouveau profil part de vos réglages actuels.</p></form>'
      :`<button type="button" class="perso-profile-new" data-perso-create${full?' disabled':''}>${svg('plus')}<span>${full?`${state.max_profiles} profils au plus`:'Créer un profil'}</span></button>`;
    return `<ul class="perso-profile-list" aria-label="Profils de personnalisation">${items}</ul>${create}${statusLine('profile')}`;
  }
  /* Le bouton et le panneau flottant sont créés une fois puis mis à jour en place : `openFloat` garde ses écouteurs. */
  function renderProfile(){
    const host=document.getElementById('persoProfile');if(!host)return;
    const list=P.profiles?P.profiles.profiles:[],active=list.find(p=>p.active)||list[0];
    if(!active){if(P.closeMenu)P.closeMenu('api',{focus:false});host.innerHTML='';return}
    let btn=document.getElementById('persoProfileBtn');
    if(!btn){
      host.innerHTML=`<button type="button" class="perso-profile-btn" id="persoProfileBtn" aria-haspopup="dialog" aria-expanded="false" aria-controls="persoProfileMenu"></button>`
        +UI.float({id:'persoProfileMenu',title:'Profils',eyebrow:'Préférences de réponse et voix',body:'<div class="perso-profile-body" id="persoProfileBody"></div>',closeLabel:'Fermer la liste des profils'});
      btn=document.getElementById('persoProfileBtn');
    }
    btn.className=`perso-profile-btn set-tone-${ACCENT_TONE[active.accent]||'blue'}`;
    btn.innerHTML=`${UI.medallion({icon:AVATAR})}<span class="perso-profile-text"><span class="sr-only">Profil actif : </span><strong>${esc(active.name)}</strong></span>${svg('caret','perso-caret')}`;
    const body=document.getElementById('persoProfileBody');
    if(body)UI.keepFocus(body,()=>{body.innerHTML=profileMenuBody()});
  }
  function setMenu(openMenu,{focus=true}={}){
    const panel=document.getElementById('persoProfileMenu'),btn=document.getElementById('persoProfileBtn');
    if(!panel||!btn)return;
    if(openMenu&&!P.menu){
      P.menu=true;P.creating=false;renderProfile();
      const first=panel.querySelector('.perso-profile-pick[aria-current="true"]')||panel.querySelector('.perso-profile-pick');
      P.closeMenu=UI.openFloat(panel,{trigger:btn,initialFocus:first,onClose:reason=>{
        P.menu=false;P.creating=false;P.closeMenu=null;renderProfile();
        console.info('[settings] personalization.profiles_closed',{reason});
      }});
    }else if(!openMenu&&P.menu&&P.closeMenu)P.closeMenu('api',{focus});
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
    const generation=P.generation,text=!!(payload.cli&&payload.cli.behavior&&'custom_instructions' in payload.cli.behavior);
    status(cardId,'Enregistrement…','busy');
    if(text)P.textSaving++;
    try{
      const data=await withDeadline(api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),'Enregistrement').finally(()=>{if(text)P.textSaving--});
      if(generation!==P.generation)return;
      P.data=data;patchShellDraft(data);
      if(P.profiles)await refreshProfiles(generation);
      if(rerender)render();else{syncPresets();renderProfile()}
      status(cardId,'Enregistré.','ok');
      console.info('[settings] personalization.saved',{card:cardId,keys:Object.keys(payload)});
    }catch(e){
      if(generation!==P.generation)return;
      console.warn('[settings] personalization.save_failed',{card:cardId,code:e.code||null,error:e.message});
      if(e.code==='personalization_timeout'){reload(cardId,e.message);return}
      render();  // la valeur enregistrée revient dans le contrôle
      status(cardId,e.message||'Enregistrement impossible.','error');
    }
  }
  /* Échéance dépassée : l'écriture a peut-être eu lieu. On relit plutôt que de supposer, et on le dit. */
  async function reload(cardId,message){
    const generation=P.generation;
    status(cardId,`${message} Relecture…`,'error');
    try{
      const data=await withDeadline(api('/api/settings'),'Relecture');
      if(generation!==P.generation)return;
      P.data=data;render();status(cardId,`${message} Valeurs relues.`,'error');
    }catch(e){
      if(generation!==P.generation)return;
      console.warn('[settings] personalization.reload_failed',{code:e.code||null,error:e.message});
      P.error=e.message;render();
    }
  }
  async function refreshProfiles(generation){
    try{const state=await withDeadline(api('/api/personalization/profiles'),'Profils');if(generation===P.generation)P.profiles=state}
    catch(e){console.warn('[settings] personalization.profiles_failed',{code:e.code||null,error:e.message})}
  }
  function syncPresets(){
    for(const p of PRESETS){
      const input=root().querySelector(`[data-perso-preset="${p.id}"]`);
      if(input)input.checked=presetActive(p);
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
  function saveTrait(fieldId,index){
    const field=behaviorField(fieldId),opt=field&&steps(field)[Number(index)];
    if(!opt)return Promise.resolve();
    return saveBehavior('persona',{[fieldId]:opt.id},{rerender:true});
  }
  async function profileAction(body,okText){
    if(P.busy)return;
    P.busy=true;const generation=P.generation;status('profile','Enregistrement…','busy');
    try{
      await saveInstructions();
      const result=await withDeadline(api('/api/personalization/profiles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),'Profils');
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
      const [data,profiles]=await withDeadline(Promise.all([api('/api/settings'),api('/api/personalization/profiles')]),'Lecture des réglages');
      if(generation!==P.generation)return;
      P.data=data;P.profiles=profiles;
      console.info('[settings] personalization.loaded',{profiles:(profiles.profiles||[]).length});
    }catch(e){
      if(generation!==P.generation)return;
      P.error=e.message;
      console.warn('[settings] personalization.load_failed',{code:e.code||null,error:e.message});
    }
    render();
  }
  function open(){
    if(P.closeMenu)P.closeMenu('api',{focus:false});
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
    saveInstructions().catch(()=>{});  // un échec est déjà dit dans la carte et journalisé par `save`
    if(P.closeMenu)P.closeMenu('api',{focus:false});
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

  /* --- événements --------------------------------------------------------------------------------------------- */
  function bind(){
    const page=root();if(!page||page.dataset.bound)return;page.dataset.bound='1';
    document.getElementById('persoClose').addEventListener('click',close);
    document.getElementById('persoCrumbHub').addEventListener('click',backToHub);
    page.addEventListener('click',event=>{
      /* En « Hériter », cliquer le cran médian ne change pas la valeur (pas de `change`) : le clic choisit ce cran. */
      const range=event.target.closest('input[data-perso-trait]');
      if(range){if(range.closest('[data-inherit]')&&range.value===range.defaultValue)saveTrait(range.dataset.persoTrait,range.value);return}
      const t=event.target.closest('button');if(!t||!page.contains(t))return;
      if(t.id==='persoProfileBtn'){setMenu(!P.menu);return}
      if(t.dataset.persoProfile){const p=P.profiles.profiles.find(x=>x.id===t.dataset.persoProfile);
        if(p&&!p.active)profileAction({action:'select',id:p.id},`Profil « ${p.name} » actif.`).then(r=>{if(r)setMenu(false)});else setMenu(false);return}
      if(t.dataset.persoDelete){const p=P.profiles.profiles.find(x=>x.id===t.dataset.persoDelete);
        if(p)profileAction({action:'delete',id:p.id},`Profil « ${p.name} » supprimé.`).then(()=>{if(P.menu){const b=page.querySelector('[data-perso-create]')||page.querySelector('.perso-profile-pick');if(b)b.focus()}});return}
      if(t.hasAttribute('data-perso-create')){P.creating=true;renderProfile();const i=document.getElementById('persoProfileName');if(i)i.focus();return}
      if(t.hasAttribute('data-perso-create-cancel')){P.creating=false;renderProfile();const b=page.querySelector('[data-perso-create]');if(b)b.focus();return}
      if(t.dataset.persoInherit){const id=t.dataset.persoInherit;
        saveBehavior('persona',{[id]:INHERIT},{rerender:true}).then(()=>{const r=document.getElementById(`persoTrait_${id}`);if(r&&!root().contains(document.activeElement))r.focus()});return}
      if(t.dataset.persoOpen){openDetail(t.dataset.persoOpen);return}
      if(t.hasAttribute('data-perso-agenda-switch')){
        const next=t.getAttribute('aria-checked')!=='true';
        UI.setToggle(t,next);
        save('proactive',{agenda_reminders:{enabled:next}},{rerender:true});return}
      if(t.hasAttribute('data-perso-retry')){load();return}
    });
    page.addEventListener('submit',event=>{
      if(event.target.id!=='persoProfileForm')return;
      event.preventDefault();
      const name=document.getElementById('persoProfileName').value;
      profileAction({action:'create',name},`Profil « ${name.trim()} » créé et actif.`).then(r=>{if(r){const b=page.querySelector('[data-perso-create]');if(b)b.focus()}});
    });
    page.addEventListener('change',event=>{
      const t=event.target;
      if(t.dataset.persoVoice){
        const stack=voiceStack();if(!stack)return;
        save('voice',{voice:{settings:{[stack.id]:{[t.dataset.persoVoice]:t.value}}}});return}
      if(t.dataset.persoTrait){saveTrait(t.dataset.persoTrait,t.value);return}
      if(t.dataset.persoPreset){const p=PRESETS.find(x=>x.id===t.dataset.persoPreset);if(p)saveBehavior('presets',{...p.values},{rerender:true});return}
      if(t.dataset.persoAgenda){const v=t.type==='number'?Number(t.value):t.value;save('proactive',{agenda_reminders:{[t.dataset.persoAgenda]:v}});return}
    });
    page.addEventListener('input',event=>{
      if(event.target.id!=='persoInstructions')return;
      clearTimeout(P.textTimer);P.textTimer=setTimeout(()=>saveInstructions(),1200);
    });
    page.addEventListener('focusout',event=>{if(event.target.id==='persoInstructions')saveInstructions()});
    page.addEventListener('keydown',event=>{
      /* Échap dans le panneau des profils est consommé par `openFloat` (repli, focus rendu au bouton du profil). */
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

  window.JarvisPersonalization=Object.freeze({PAGE_ID,PRESETS,TRAITS,DEADLINE_MS,open:()=>{bind();return open()},close,backToHub,isOpen});
})();
