/* Galerie des primitives partagées des Réglages (refonte-ui-settings, Slice 01) : une fixture de test, pas du produit.

   Injectée dans la page servie (`eval` du harnais CDP) par `test_settings_visual_foundation_browser.py`, elle monte
   dans l'overlay des Réglages une page `.set-view` composée UNIQUEMENT de primitives `JarvisSettingsUI` et de
   classes `.set-*` : en-tête, onglets, grille de 12 colonnes (3 × span 4, puis 8 + 4), panneaux, lignes, curseurs,
   interrupteurs, zone de texte, choix en cartes, statistiques, tableau dense et panneau flottant. Les textes sont des
   fixtures neutres : aucun composant partagé ne les connaît. Les Slices 02 à 06 peuvent s'en servir comme
   référence visuelle (`JARVIS_BROWSER_SHOTS`). */
(function(){
  'use strict';
  const I={
    wave:'<svg viewBox="0 0 24 24"><path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4"/></svg>',
    brain:'<svg viewBox="0 0 24 24"><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3V4zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3V4z"/></svg>',
    gear:'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/></svg>',
    bulb:'<svg viewBox="0 0 24 24"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/></svg>',
    db:'<svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>',
    bolt:'<svg viewBox="0 0 24 24"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
    play:'<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>',
    nodes:'<svg viewBox="0 0 24 24"><circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M11 7.5 6 15.5M13 7.5l5 8M7.5 18h9"/></svg>',
  };
  window.mountSettingsGallery=function mountSettingsGallery(){
    const UI=window.JarvisSettingsUI,overlay=document.getElementById('overlay');
    const old=document.getElementById('setGallery');if(old)old.remove();
    overlay.classList.add('open','instant');overlay.dataset.view='gallery';
    document.getElementById('settingsShell').style.display='none';
    const voice=UI.panel({id:'galVoice',title:'Voix de démonstration',description:'Liste, bouton et curseurs.',icon:I.wave,variant:'hot',
      body:UI.row({id:'galVoiceRow',label:'Voix',plain:true,control:''})
        +'<div style="display:flex;gap:12px;min-width:0">'+UI.select({id:'galSelect',labelledBy:'galVoiceRow-label',value:'b',
          options:[{value:'a',label:'Option A'},{value:'b',label:'Option B — libellé plus long'},{value:'c',label:'Option C'}]})
        +UI.button({id:'galListen',label:'Écouter',icon:I.play})+'</div>'
        +UI.row({id:'galVol',label:'Volume',plain:true,control:''})
        +UI.range({id:'galRange',labelledBy:'galVol-label',min:0,max:100,step:5,value:80,suffix:' %'})
        +UI.range({id:'galRate',label:'Débit',min:0.5,max:2,step:0.1,value:1,decimals:1,suffix:'x',minLabel:'Lent',maxLabel:'Rapide'})});
    const persona=UI.panel({id:'galPersona',title:'Personnalité',description:'Curseurs à deux bornes, zone de texte.',icon:I.brain,tone:'violet',
      body:'<div class="set-rows">'+UI.row({id:'galToneRow',label:'Ton général',plain:true,wide:true,
          control:UI.range({id:'galTone',labelledBy:'galToneRow-label',min:0,max:10,value:7,minLabel:'Sérieux',maxLabel:'Amical',inlineEnds:true,showValue:false})})
        +UI.row({id:'galHumourRow',label:'Humour',plain:true,wide:true,
          control:UI.range({id:'galHumour',labelledBy:'galHumourRow-label',min:0,max:10,value:3,minLabel:'Minimal',maxLabel:'Expressif',inlineEnds:true,showValue:false,disabled:true})})+'</div>'
        +UI.textarea({id:'galText',label:'Instructions',maxLength:120,placeholder:'Exemple de consigne…'})
        +UI.choices({name:'galChoice',legend:'Profil',value:'mid',items:[{value:'fast',title:'Rapide',description:'Moins de contexte',icon:I.bolt},
          {value:'mid',title:'Équilibré',description:'Compromis'},{value:'deep',title:'Approfondi',description:'Plus riche',disabled:true}]})});
    const toggles=UI.panel({id:'galToggles',title:'Automatisations',description:'Lignes à interrupteur.',icon:I.gear,tone:'cyan',
      aside:UI.toggle({id:'galMaster',label:'Tout activer',checked:true,stateText:{on:'Activé',off:'Désactivé'}}),
      body:'<div class="set-rows">'
        +UI.row({id:'galR1',label:'Suggestions',hint:'Ligne avec aide sur deux lignes au besoin.',icon:I.bulb,control:UI.toggle({id:'galT1',labelledBy:'galR1-label',describedBy:'galR1-hint',checked:true})})
        +UI.row({id:'galR2',label:'Contexte',hint:'Interrupteur éteint.',icon:I.db,control:UI.toggle({id:'galT2',labelledBy:'galR2-label',checked:false})})
        +UI.row({id:'galR3',label:'Indisponible',hint:'Interrupteur désactivé.',icon:I.bolt,control:UI.toggle({id:'galT3',labelledBy:'galR3-label',checked:true,disabled:true})})
        +'</div><div class="set-grid-auto" style="--set-col-min:120px">'
        +UI.stat({value:'5',label:'Éléments',icon:I.nodes})+UI.stat({value:'98 %',label:'Taux',icon:I.wave,tone:'violet'})+'</div>'});
    const rows=[['Alpha','L2','Actif',98],['Bêta','L1','En pause',76],['Gamma','L3','Actif',87],['Delta','L2','Erreur',12]]
      .map(([n,l,s,v],i)=>`<tr${i===0?' aria-selected="true"':''}><td>${n}</td><td>${UI.badge('info',l)}</td><td>${UI.dot(s==='Actif'?'ok':s==='Erreur'?'bad':'warn',s)}</td><td class="set-num">${v} %</td></tr>`).join('');
    const notes=UI.panel({id:'galTable',title:'Tableau dense',description:'Coquille, en-tête collant, pied.',icon:I.db,
      body:UI.table({id:'galTableShell',label:'Éléments de démonstration',columns:[{label:'Nom'},{label:'Niveau'},{label:'État'},{label:'Score',num:true}],
        body:rows,foot:'<span>4 éléments</span>'+UI.actions(UI.button({label:'Précédent',size:'sm',disabled:true})+UI.button({label:'Suivant',size:'sm'}))})});
    const states=UI.panel({id:'galStates',title:'États',description:'Boutons, pastilles, panneau flottant.',icon:I.bolt,tone:'amber',variant:'quiet',
      body:UI.actions(UI.button({id:'galPrimary',label:'Appliquer',variant:'primary'})+UI.button({id:'galBusy',label:'Envoi',variant:'primary',busy:true})
          +UI.button({id:'galDisabled',label:'Indisponible',disabled:true})+UI.button({id:'galGhost',label:'Annuler',variant:'ghost'}))
        +'<p style="display:flex;flex-wrap:wrap;gap:8px 16px;margin:0">'+UI.dot('ok','Actif')+UI.dot('warn','Manuelle')+UI.dot('bad','Désactivé')+UI.dot('off','Inconnu')+'</p>'
        +UI.button({id:'galOpenFloat',label:'Ouvrir la configuration',icon:I.gear})
        +UI.float({id:'galFloat',eyebrow:'Configuration',title:'Panneau flottant',tone:'violet',
          body:UI.select({id:'galFloatSelect',label:'Modèle',options:[{value:'x',label:'Modèle X'}],value:'x'})
            +UI.range({id:'galFloatRange',label:'Tendance',min:0,max:100,value:50,suffix:' %',minLabel:'Moins',maxLabel:'Plus'}),
          actions:UI.button({label:'Annuler',variant:'ghost'})+UI.button({label:'Appliquer',variant:'primary'})})});
    const view=document.createElement('section');
    view.className='set-view';view.id='setGallery';view.setAttribute('role','dialog');view.setAttribute('aria-label','Galerie des primitives');
    view.innerHTML='<div class="set-page" id="setGalleryPage"><header class="set-page-head"><div>'
      +'<p class="set-crumb">Jarvis <span aria-hidden="true">›</span> Paramètres</p><h2 class="set-title">Fondation visuelle</h2>'
      +'<p class="set-lead">Primitives partagées des Réglages, avec des données de démonstration.</p><span class="set-rule" aria-hidden="true"></span></div></header>'
      +UI.tabs({id:'galTabs',label:'Sections de démonstration',selected:'one',fill:false,items:[{id:'one',label:'Architecture',icon:I.nodes},{id:'two',label:'Mémoire',icon:I.brain},{id:'three',label:'Centre',icon:I.db}]})
      +'<div class="set-grid" id="galGrid" style="margin-top:var(--set-gap)">'
      +`<div class="set-span-4">${voice}</div><div class="set-span-4">${persona}</div><div class="set-span-4">${toggles}</div>`
      +`<div class="set-span-8">${notes}</div><div class="set-span-4" style="position:relative">${states}</div></div></div>`;
    overlay.append(view);
    UI.bindAll(view);
    view.querySelectorAll('.set-switch').forEach(b=>UI.bindToggle(b));
    UI.bindTabs(view.querySelector('#galTabs'));
    const trigger=view.querySelector('#galOpenFloat'),panel=view.querySelector('#galFloat');
    Object.assign(panel.style,{right:'0',bottom:'calc(100% + 8px)'});
    trigger.setAttribute('aria-haspopup','dialog');trigger.setAttribute('aria-controls','galFloat');trigger.setAttribute('aria-expanded','false');
    trigger.addEventListener('click',()=>{window.__galClose=UI.openFloat(panel,{trigger})});
    return true;
  };
})();
