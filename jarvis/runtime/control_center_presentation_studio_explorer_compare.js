/* Comparaison côte à côte de l'explorateur de variantes (handoff jarvis-interactive-presentation-studio, Slice 19, moitié interface).

   Ce module DOM tient l'ensemble des variantes MARQUÉES dans l'arbre, la vue de comparaison (2 fenêtres, 4 fenêtres, ou 2 en vis-à-vis 50/50), la navigation
   synchronisée entre scènes équivalentes (statuts origine / synchronisée / sans équivalent / indépendante), le mode indépendant, les liens manuels et la
   porte vers la composition (`..._explorer_compose.js`). Les fonctions pures sont dans `..._explorer_compare_core.js`.

   Ce qu'il n'est PAS :
   - une source de vérité. L'état de comparaison est celui de Core (`/compare`, en mémoire côté Core) ; l'équivalence des scènes et le statut d'une
     navigation sont LUS dans sa réponse, jamais devinés. Un geste refusé ou périmé (`stale_revision`, variante archivée) est dit à l'écran, la vue relue ;
   - un chemin d'écriture. Les fenêtres LISENT le document de chaque variante (`GET .../variants/{id}`) et le montent dans un cadre de prefab en mode
     `preview` de l'hôte de l'aperçu simple : aucun événement ne part du cadre, aucune variante n'est modifiée (la composition, seule écriture, est un
     enfant NEUF créé par le formulaire de composition).
   Tout texte d'auteur passe par `textContent` après `cleanLine`. */
(function(root){
  'use strict';
  const Core=root.JarvisStudioExplorerCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_core.js'):null);
  const CC=root.JarvisStudioExplorerCompareCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_compare_core.js'):null);
  const {HOST_ID,cleanLine}=Core;

  function describeError(error){return cleanLine(error&&error.message||String(error||'erreur inconnue'),200)}

  function createCompare(ctx){
    const {doc,el,attrs,clear,button,icon,later,cancelLater,log,say,announce}=ctx;
    const C={active:false,marks:[],view:null,nav:null,docs:new Map(),panes:new Map(),pairPick:[],opener:null,generation:0,mounted:new Map(),busy:null};
    const ui={};
    let chain=Promise.resolve();
    const serial=fn=>{const p=chain.then(fn,fn);chain=p.catch(()=>{/* intentional: each caller sees its own result; the chain only orders */});return p};
    const comparePath=tail=>`${ctx.base()}/compare${tail||''}`;
    const expected=()=>C.view&&C.view.active&&Number.isInteger(C.view.revision)?{expected_revision:C.view.revision}:{};

    /* -------------------------------------------------------------- marques */
    function markSet(){return new Set(C.marks)}
    function toggleMark(id,options){
      const node=ctx.nodeOf(id);
      if(!node)return {change:'refused',reason:'Variante inconnue.'};
      const out=CC.toggleMark(C.marks,id,node.state==='live');
      if(out.change==='refused'){say('refused',out.reason);return out}
      C.marks=out.marks;
      announce(out.change==='added'?`Variante ${node.variant_number} marquée pour la comparaison. ${CC.markState(C.marks).text}`:`Variante ${node.variant_number} retirée de la comparaison.`);
      renderBar();ctx.repaintTrees();
      if(!(options&&options.quiet))log('mark',{variant_id:id,change:out.change,count:C.marks.length});
      return out;
    }
    function clearMarks(){C.marks=[];renderBar();ctx.repaintTrees()}
    function renderBar(){
      if(!ui.bar)return;
      const st=CC.markState(C.marks);
      ui.bar.hidden=!(C.marks.length||C.active);
      ui.barText.textContent=C.active?`Comparaison ouverte (${C.view?C.view.variant_ids.length:C.marks.length} variantes)`:st.text;
      const go=ui.barGo;
      go.textContent=C.active?'Revenir à la comparaison':'Comparer';
      if(!C.active&&!st.ok){go.setAttribute('aria-disabled','true');go.title=st.reason}
      else{go.removeAttribute('aria-disabled');go.title=C.active?'Afficher la comparaison (Maj+C depuis une ligne : démarrer)':'Comparer les variantes marquées (Maj+C)'}
      ui.barClear.hidden=!C.marks.length;
    }
    function buildBar(){
      ui.bar=el('div','jvx-cmp-bar');
      attrs(ui.bar,{role:'group','aria-label':'Comparaison de variantes'});
      ui.barText=el('span','jvx-cmp-bar-text');ui.barText.setAttribute('aria-live','polite');
      ui.barGo=button('Comparer','jvx-btn',()=>{
        if(ui.barGo.getAttribute('aria-disabled')==='true'){say('info',CC.markState(C.marks).reason);return}
        if(C.active){showRoot(true);return}
        start({variant_ids:C.marks.slice()});
      });
      ui.barClear=button('Vider','jvx-btn',()=>clearMarks(),{attrs:{title:'Retirer toutes les marques'}});
      ui.bar.appendChild(ui.barText);ui.bar.appendChild(ui.barGo);ui.bar.appendChild(ui.barClear);
      ui.bar.hidden=true;
      return ui.bar;
    }

    /* -------------------------------------------------------------- construction */
    function buildRoot(){
      if(ui.root)return ui.root;
      const rootEl=el('section','jvx-compare');
      attrs(rootEl,{'aria-label':'Comparaison des variantes'});
      rootEl.hidden=true;
      const bar=el('div','jvx-cmp-toolbar');
      attrs(bar,{role:'toolbar','aria-label':'Outils de comparaison'});
      ui.title=el('h2','jvx-cmp-title','Comparaison');ui.title.setAttribute('tabindex','-1');
      ui.modeBtn=button('','jvx-btn',()=>setMode(C.view&&C.view.mode==='independent'?'sync':'independent'),{attrs:{'aria-keyshortcuts':'M'}});
      ui.structChip=el('span','jvx-chip');
      ui.linksBtn=button('Liens…','jvx-btn',()=>openLinks({}),{attrs:{'aria-keyshortcuts':'L',title:'Lier à la main des scènes qui se correspondent (L)'}});
      ui.composeBtn=button('Composer…','jvx-btn',()=>openCompose({}),{attrs:{'aria-keyshortcuts':'Shift+C',title:'Créer une nouvelle variante en combinant les dimensions des variantes comparées (Maj+C)'}});
      ui.allBtn=button('Tout afficher','jvx-btn',()=>setPair(null),{attrs:{title:'Quitter le vis-à-vis'}});
      ui.closeBtn=button('Fermer la comparaison','jvx-btn',()=>close({}),{icon:'close',attrs:{title:'Fermer la comparaison (Échap)'}});
      for(const n of [ui.title,ui.modeBtn,ui.structChip,ui.linksBtn,ui.composeBtn,ui.allBtn,ui.closeBtn])bar.appendChild(n);
      ui.banner=el('div','jvx-cmp-banner');attrs(ui.banner,{role:'status','aria-live':'polite'});ui.banner.hidden=true;
      ui.bannerText=el('span','jvx-cmp-banner-text');
      ui.bannerIndep=button('Passer en mode indépendant','jvx-btn',()=>setMode('independent'));
      ui.bannerLinks=button('Gérer les liens','jvx-btn',()=>openLinks({}));
      ui.banner.appendChild(ui.bannerText);ui.banner.appendChild(ui.bannerIndep);ui.banner.appendChild(ui.bannerLinks);
      ui.grid=el('div','jvx-cmp-grid');attrs(ui.grid,{role:'group','aria-label':'Fenêtres de comparaison'});
      ui.hint=el('p','jvx-hint-keys');
      ui.hint.textContent='↑ ↓ ← → Début Fin parcourir les scènes · M mode · F vis-à-vis · L lier · Maj+C composer · Échap fermer';
      for(const n of [bar,ui.banner,ui.grid,ui.hint])rootEl.appendChild(n);
      rootEl.addEventListener('keydown',onKey);
      ui.root=rootEl;
      return rootEl;
    }
    function buildPane(id){
      const pane={id,root:el('article','jvx-cmp-pane')};
      attrs(pane.root,{role:'group',tabindex:'0','data-pane':id});
      const head=el('div','jvx-cmp-panehead');
      pane.num=el('span','jvx-num');
      pane.name=el('span','jvx-cmp-name jvx-bidi');pane.name.setAttribute('dir','auto');
      pane.active=el('span','jvx-flag','Actif');pane.active.setAttribute('data-flag','active');
      pane.status=el('span','jvx-chip jvx-cmp-status');
      for(const n of [pane.num,pane.name,pane.active,pane.status])head.appendChild(n);
      const wrap=el('div','jvx-stagewrap jvx-cmp-stagewrap');
      pane.stage=el('div','jvx-stage jvx-cmp-stage');
      pane.slot=el('div','jvx-slot');
      pane.veil=el('div','jvx-stage-veil jvx-cmp-veil');pane.veilTitle=el('strong');pane.veilText=el('span');
      pane.veil.appendChild(pane.veilTitle);pane.veil.appendChild(pane.veilText);
      pane.stage.appendChild(pane.slot);pane.stage.appendChild(pane.veil);wrap.appendChild(pane.stage);
      const nav=el('div','jvx-cmp-nav');
      pane.prev=button(null,'jvx-btn jvx-btn-icon',()=>navigate({variant_id:id,step:'previous'}),{icon:'prev',attrs:{title:'Scène précédente'}});
      pane.next=button(null,'jvx-btn jvx-btn-icon',()=>navigate({variant_id:id,step:'next'}),{icon:'next',attrs:{title:'Scène suivante'}});
      pane.select=el('select','jvx-cmp-select');
      pane.select.addEventListener('change',()=>{if(pane.select.value)navigate({variant_id:id,scene_id:pane.select.value})});
      pane.count=el('span','jvx-cmp-count');
      for(const n of [pane.prev,pane.next,pane.select,pane.count])nav.appendChild(n);
      pane.line=el('p','jvx-cmp-line');
      const tools=el('div','jvx-cmp-tools');
      pane.focusBtn=button('Vis-à-vis','jvx-btn',()=>toggleFocus(id),{attrs:{'aria-pressed':'false','aria-keyshortcuts':'F'}});
      pane.linkBtn=button('Lier cette scène…','jvx-btn',()=>openLinks({scene:{variant_id:id}}),{attrs:{'aria-keyshortcuts':'L'}});
      tools.appendChild(pane.focusBtn);tools.appendChild(pane.linkBtn);
      for(const n of [head,wrap,nav,pane.line,tools])pane.root.appendChild(n);
      return pane;
    }

    /* -------------------------------------------------------------- rendu */
    function showRoot(on){
      if(!ui.root)return;
      ui.root.hidden=!on;
      if(ctx.setCompareVisible)ctx.setCompareVisible(!!on);
    }
    function objectIdOf(id){const ids=C.view?C.view.variant_ids:[];return CC.PANE_OBJECT_PREFIX+Math.max(0,ids.indexOf(id))}
    function render(){
      if(!ui.root)return;
      const view=C.view;
      if(!view||!view.active){return}
      const layout=CC.layoutOf(view);
      ui.title.textContent=`Comparaison · ${view.variant_ids.length} variantes${layout.kind==='focus'?' · vis-à-vis':''}`;
      const indep=view.mode==='independent';
      ui.modeBtn.textContent=indep?'Navigation indépendante':'Navigation synchronisée';
      ui.modeBtn.setAttribute('aria-pressed',indep?'false':'true');
      ui.modeBtn.title=indep?'Chaque fenêtre navigue seule. Cliquer pour resynchroniser (M)':'Les scènes équivalentes suivent. Cliquer pour rendre les fenêtres indépendantes (M)';
      const st=CC.structureOf(view);
      ui.structChip.textContent=st.relation==='identical'?'Structures identiques':st.relation==='reordered'?'Ordre différent':'Structures différentes';
      ui.structChip.setAttribute('data-tone',st.diverged?'warn':'ok');
      const nLinks=(view.links||[]).length;
      ui.linksBtn.textContent=nLinks?`Liens… (${nLinks})`:'Liens…';
      ui.allBtn.hidden=layout.kind!=='focus';
      renderBanner(st);
      ui.grid.setAttribute('data-layout',layout.kind);
      ui.grid.setAttribute('data-count',String(layout.shown.length));
      const wanted=view.variant_ids;
      for(const [id,pane] of Array.from(C.panes)){
        if(!wanted.includes(id)){unmountPane(id);pane.root.remove();C.panes.delete(id)}
      }
      let previous=null;
      for(const id of wanted){
        let pane=C.panes.get(id);
        if(!pane){pane=buildPane(id);C.panes.set(id,pane)}
        if(pane.root.parentNode!==ui.grid||(previous&&previous.nextSibling!==pane.root))ui.grid.insertBefore(pane.root,previous?previous.nextSibling:ui.grid.firstChild);
        previous=pane.root;
        const shown=layout.shown.includes(id);
        pane.root.hidden=!shown;
        if(!shown){unmountPane(id);continue}
        renderPane(pane,view,layout);
      }
      ensureDocs();
    }
    function renderBanner(st){
      const view=C.view;
      const problems=(view.problems||[]);
      const texts=[];
      if(problems.length)texts.push(`${problems.length} variante${problems.length>1?'s':''} de la comparaison ne ${problems.length>1?'sont':'est'} plus disponible${problems.length>1?'s':''} (archivée ou retirée) : fermez la comparaison et choisissez-en d'autres.`);
      if(st.text&&st.diverged)texts.push(st.text);
      const unmappedPanes=C.nav?Object.keys(C.nav.results||{}).filter(id=>C.nav.results[id].status==='unmapped').length:0;
      if(unmappedPanes&&!(st.text&&st.diverged))texts.push(`${unmappedPanes} fenêtre${unmappedPanes>1?'s':''} sans scène équivalente : elle${unmappedPanes>1?'s gardent':' garde'} sa scène.`);
      ui.banner.hidden=!texts.length;
      ui.bannerText.textContent=texts.join(' ');
      ui.bannerIndep.hidden=!(texts.length&&view.mode==='sync'&&st.diverged);
      ui.bannerLinks.hidden=!(texts.length&&st.diverged);
    }
    function renderPane(pane,view,layout){
      const model=CC.paneModel(view,pane.id,C.nav);
      pane.root.setAttribute('aria-label',CC.paneAriaLabel(model));
      pane.num.textContent=model.missing?'#?':`#${model.number}`;
      pane.name.textContent=model.title;
      pane.active.hidden=!model.active;
      const status=model.status?CC.STATUS[model.status]:null;
      pane.status.hidden=!status;
      if(status){pane.status.textContent=status.label;pane.status.setAttribute('data-tone',status.tone||'');pane.status.setAttribute('data-status',model.status)}
      else pane.status.removeAttribute('data-status');
      /* Les options de la liste ne sont refaites que si les scènes ont changé : le focus d'une liste ouverte ne saute pas. */
      const signature=model.scenes.map(s=>s.scene_id+'|'+s.title).join('\n');
      if(pane.signature!==signature){
        clear(pane.select);
        model.scenes.forEach((s,i)=>{const o=el('option','',CC.sceneLabel(s,i));o.value=s.scene_id;pane.select.appendChild(o)});
        pane.signature=signature;
      }
      if(model.sceneId)pane.select.value=model.sceneId;
      pane.select.setAttribute('aria-label',`Scène de la variante ${model.number}`);
      pane.count.textContent=model.index>=0?`${model.index+1} / ${model.count}`:'';
      pane.prev.setAttribute('aria-label',`Scène précédente de la variante ${model.number}`);
      pane.next.setAttribute('aria-label',`Scène suivante de la variante ${model.number}`);
      pane.prev.setAttribute('aria-disabled',model.index>0?'false':'true');
      pane.next.setAttribute('aria-disabled',model.index>=0&&model.index<model.count-1?'false':'true');
      pane.line.textContent=CC.paneLine(model);
      pane.line.setAttribute('data-status',model.status||model.mapping||'');
      const focused=layout.kind==='focus';
      pane.focusBtn.hidden=view.variant_ids.length<4;
      const picked=C.pairPick.includes(pane.id);
      pane.focusBtn.textContent=focused?'Tout afficher':picked?'Choisi pour le vis-à-vis':'Vis-à-vis';
      pane.focusBtn.setAttribute('aria-pressed',focused||picked?'true':'false');
      pane.focusBtn.title=focused?'Quitter le vis-à-vis (F)':picked?'Choisissez une seconde variante pour le vis-à-vis (F)':'Mettre cette variante en vis-à-vis 50/50 avec une autre (F)';
      pane.linkBtn.setAttribute('aria-label',`Lier la scène de la variante ${model.number} à une autre`);
      pane.linkBtn.setAttribute('data-emphasis',model.status==='unmapped'||model.mapping==='none'?'true':'false');
    }

    /* -------------------------------------------------------------- documents et aperçus (lecture seule) */
    function ensureDocs(){
      if(!C.view)return;
      const layout=CC.layoutOf(C.view);
      for(const id of layout.shown){
        const model=CC.paneModel(C.view,id,C.nav);
        if(model.missing){paintVeil(id);continue}
        const entry=C.docs.get(id);
        if(entry&&(entry.status==='loading'||(entry.status==='ready'&&entry.rev>=model.revision))){mountPane(id);continue}
        if(entry&&entry.status==='error'&&entry.rev===model.revision){mountPane(id);continue}
        loadDoc(id,model.revision);
      }
    }
    async function loadDoc(id,revision){
      const generation=C.generation;
      C.docs.set(id,{status:'loading',rev:revision,scenes:[],error:null});
      paintVeil(id);
      try{
        const variantDoc=await ctx.call('GET',`${ctx.base()}/variants/${encodeURIComponent(id)}`,undefined,{timeoutMs:ctx.readTimeout});
        if(generation!==C.generation||!C.active)return;
        C.docs.set(id,{status:'ready',rev:Number.isFinite(variantDoc.revision)?variantDoc.revision:revision,scenes:ctx.scenesOf(variantDoc),error:null});
        log('compare_doc_loaded',{variant_id:id,scenes:C.docs.get(id).scenes.length});
      }catch(error){
        if(generation!==C.generation||!C.active)return;
        const info=CC.describe(error.info||error,{op:'preview'});
        C.docs.set(id,{status:'error',rev:revision,scenes:[],error:info.text});
        log('compare_doc_failed',{variant_id:id,code:info.code},'warn');
      }
      mountPane(id);
    }
    function paneVeil(pane,tone,title,text){
      pane.veil.hidden=!title;
      pane.veil.setAttribute('data-tone',tone||'');
      pane.veilTitle.textContent=title||'';pane.veilText.textContent=text||'';
    }
    function paintVeil(id){
      const pane=C.panes.get(id);
      if(!pane)return;
      const model=C.view?CC.paneModel(C.view,id,C.nav):{missing:true};
      const entry=C.docs.get(id);
      if(model.missing)paneVeil(pane,'danger','Variante indisponible',"Elle est archivée ou retirée : fermez la comparaison.");
      else if(!entry||entry.status==='loading')paneVeil(pane,'',"Chargement de l'aperçu…",`Variante #${model.number}`);
      else if(entry.status==='error')paneVeil(pane,'danger','Aperçu impossible',entry.error||'');
    }
    function mountPane(id){
      const pane=C.panes.get(id);
      if(!pane||!C.view)return;
      paintVeil(id);
      const entry=C.docs.get(id);
      const model=CC.paneModel(C.view,id,C.nav);
      if(model.missing||!entry||entry.status!=='ready')return;
      const scene=entry.scenes.find(s=>s.id===model.sceneId);
      if(!scene){paneVeil(pane,'warn','Scène introuvable',"La variante a changé : la comparaison est relue.");return}
      if(!scene.prefab){paneVeil(pane,'danger','Scène sans prefab','Cette scène ne désigne aucun prefab.');return}
      const key=`${scene.id}|${entry.rev}`;
      if(C.mounted.get(id)===key){pane.veil.hidden=true;return}
      const host=ctx.ensureHost();
      if(!host){paneVeil(pane,'danger','Aperçu indisponible',"Le runtime des prefabs n'est pas chargé dans cette page.");return}
      try{
        host.mount(pane.slot,{object_id:objectIdOf(id),prefab:{id:scene.prefab.id,version:scene.prefab.version},title:scene.title,props:scene.props,data:scene.data});
        C.mounted.set(id,key);pane.veil.hidden=true;
      }catch(error){paneVeil(pane,'danger','Aperçu impossible',describeError(error));log('compare_mount_failed',{error:describeError(error)},'error')}
    }
    function unmountPane(id){
      if(!C.mounted.has(id))return;
      C.mounted.delete(id);
      const host=ctx.peekHost();
      const index=C.view?C.view.variant_ids.indexOf(id):-1;
      if(host&&index>=0){try{host.unmount(CC.PANE_OBJECT_PREFIX+index)}catch(_error){/* intentional: the frame is gone either way */}}
    }
    function unmountAll(){
      const host=ctx.peekHost();
      if(host){for(let i=0;i<4;i+=1){try{host.unmount(CC.PANE_OBJECT_PREFIX+i)}catch(_error){/* intentional: nothing mounted under that id */}}}
      C.mounted.clear();
    }

    /* -------------------------------------------------------------- vue de Core */
    function applyView(view,navigation){
      if(!view||typeof view!=='object')return;
      const same=C.view&&view.revision===C.view.revision&&navigation===undefined;
      C.view=view;
      if(navigation!==undefined)C.nav=navigation||null;
      else if(!same)C.nav=null;
      if(!view.active){C.active=false;showRoot(false)}
      else{
        C.active=true;showRoot(true);
        const ids=view.variant_ids||[];
        for(const id of Array.from(C.docs.keys()))if(!ids.includes(id))C.docs.delete(id);
        for(const id of Array.from(C.mounted.keys()))if(!ids.includes(id))C.mounted.delete(id);
      }
      render();renderBar();
    }
    /* Un geste d'écriture sur l'état de comparaison : en file, refus dits à l'écran, vue relue quand elle est périmée. */
    function run(op,fn){
      return serial(async()=>{
        try{return await fn()}
        catch(error){
          const info=CC.describe(error.info||error,{op});
          log('compare_op_failed',{op,code:info.code,kind:info.kind,status:error.status},info.kind==='failed'?'error':'warn');
          say(info.kind==='failed'?'failed':info.kind==='stale'?'stale':'refused',info.text);
          if(info.kind==='stale'||info.code==='presentation_studio_unknown_variant'){
            try{const view=await ctx.call('GET',comparePath(),undefined,{timeoutMs:ctx.readTimeout});applyView(view)}
            catch(reload){log('compare_reload_failed',{code:reload.code},'warn')}
          }
          return {error:info};
        }
      });
    }
    async function refreshView(){
      return run('compare',async()=>{const view=await ctx.call('GET',comparePath(),undefined,{timeoutMs:ctx.readTimeout});applyView(view);return view});
    }
    async function start(options){
      const opts=options||{};
      const ids=Array.isArray(opts.variant_ids)?opts.variant_ids.slice():C.marks.slice();
      if(!CC.ALLOWED_SIZES.includes(ids.length)){const text=CC.markState(ids).reason;say('refused',text);return {error:{code:'presentation_studio_invalid',text}}}
      for(const id of ids){const n=ctx.nodeOf(id);if(!n||n.state!=='live'){const text="Une variante archivée ou inconnue ne se compare pas.";say('refused',text);return {error:{code:'presentation_studio_unknown_variant',text}}}}
      buildRoot();
      const body=Object.assign({variant_ids:ids},expected());
      if(opts.pair)body.pair=opts.pair;
      if(opts.mode)body.mode=opts.mode;
      const wasActive=C.active;
      if(!wasActive){C.opener=doc.activeElement;C.generation+=1}
      const out=await run('compare',async()=>{
        const view=await ctx.call('POST',comparePath('/select'),body);
        C.marks=ids.slice();
        C.pairPick=[];
        applyView(view,null);
        return view;
      });
      if(out&&!out.error){
        announce(`Comparaison de ${ids.length} variantes ouverte.`);
        const first=C.panes.get(ids[0]);
        if(first)first.root.focus({preventScroll:true});
        log('compare_started',{count:ids.length});
        ctx.onActive(true);
      }
      return out;
    }
    async function close(options){
      const opts=options||{};
      if(!C.active&&!(C.view&&C.view.active))return {state:'closed',was_active:false};
      C.active=false;C.generation+=1;
      unmountAll();
      C.docs.clear();C.nav=null;C.pairPick=[];
      showRoot(false);
      renderBar();
      ctx.onActive(false);
      let remote=null;
      if(opts.remote!==false){
        remote=serial(async()=>{try{const a=await ctx.call('POST',comparePath('/clear'),{});if(C.view)C.view=Object.assign({},C.view,{active:false,revision:a&&a.revision||0})}catch(error){log('compare_clear_failed',{code:error.code},'warn')}});
      }
      if(!opts.quiet){
        const target=C.opener&&C.opener.isConnected!==false?C.opener:ui.barGo;
        if(target&&typeof target.focus==='function')target.focus({preventScroll:true});
        announce('Comparaison fermée.');
      }
      C.opener=null;
      log('compare_closed',{});
      if(remote&&opts.wait)await remote;
      return {state:'closed',was_active:true};
    }
    function setPair(pair){
      return run('compare',async()=>{
        const view=await ctx.call('POST',comparePath('/pair'),Object.assign({pair:pair||null},expected()));
        C.pairPick=[];applyView(view,null);
        announce(pair?'Vis-à-vis : deux variantes côte à côte.':'Toutes les variantes sont affichées.');
        return view;
      });
    }
    function toggleFocus(id){
      if(!C.view||C.view.variant_ids.length<4)return Promise.resolve(null);
      if(C.view.layout==='focus')return setPair(null);
      const at=C.pairPick.indexOf(id);
      if(at>=0){C.pairPick.splice(at,1);render();return Promise.resolve(null)}
      C.pairPick.push(id);
      if(C.pairPick.length<2){announce('Choisissez une seconde variante pour le vis-à-vis.');render();return Promise.resolve(null)}
      return setPair(C.pairPick.slice(0,2));
    }
    function setMode(mode){
      return run('compare',async()=>{
        const view=await ctx.call('POST',comparePath('/mode'),Object.assign({mode},expected()));
        applyView(view,null);
        announce(mode==='independent'?'Navigation indépendante.':'Navigation synchronisée.');
        return view;
      });
    }
    function navigate(spec){
      return run('compare',async()=>{
        /* Navigation = état d'interface, dernière écriture gagnante : pas de révision attendue (des flèches répétées ne se périment pas entre elles). */
        const body={variant_id:spec.variant_id};
        if(spec.scene_id)body.scene_id=spec.scene_id;else body.step=spec.step;
        const view=await ctx.call('POST',comparePath('/navigate'),body);
        applyView(view,view.navigation||null);
        const nav=view.navigation;
        if(nav){
          const counts={synced:0,unmapped:0,held:0};
          for(const k of Object.keys(nav.results||{})){const s=nav.results[k].status;if(counts[s]!==undefined)counts[s]+=1}
          const bits=[];
          if(counts.synced)bits.push(`${counts.synced} synchronisée${counts.synced>1?'s':''}`);
          if(counts.unmapped)bits.push(`${counts.unmapped} sans équivalent`);
          if(counts.held)bits.push(`${counts.held} indépendante${counts.held>1?'s':''}`);
          announce(bits.length?`Scène changée. ${bits.join(', ')}.`:'Scène changée.');
        }
        return view;
      });
    }
    function link(a,b){
      return run('link',async()=>{
        const view=await ctx.call('POST',comparePath('/links'),Object.assign({a,b},expected()));
        applyView(view,null);announce('Lien ajouté.');return view;
      });
    }
    function unlink(a,b){
      return run('link',async()=>{
        const view=await ctx.call('POST',comparePath('/links/remove'),Object.assign({a,b},expected()));
        applyView(view,null);announce('Lien retiré.');return view;
      });
    }

    /* -------------------------------------------------------------- clavier */
    function onKey(event){
      const tag=String(event.target&&event.target.tagName||'').toUpperCase();
      if(tag==='SELECT'||tag==='INPUT'||tag==='TEXTAREA')return;
      if(event.ctrlKey||event.altKey||event.metaKey)return;
      const paneEl=event.target&&event.target.closest?event.target.closest('[data-pane]'):null;
      const id=paneEl?paneEl.getAttribute('data-pane'):(C.view&&C.view.variant_ids[0]);
      const step=CC.keyToStep(event.key);
      let handled=false;
      if(step&&id&&tag!=='BUTTON'){navigate({variant_id:id,step});handled=true}
      else if(event.key==='m'||event.key==='M'){setMode(C.view&&C.view.mode==='independent'?'sync':'independent');handled=true}
      else if((event.key==='f'||event.key==='F')&&id){toggleFocus(id);handled=true}
      else if((event.key==='l'||event.key==='L')&&id){openLinks({scene:{variant_id:id}});handled=true}
      else if(event.key==='C'&&event.shiftKey){openCompose({});handled=true}
      if(handled){event.preventDefault();event.stopPropagation()}
    }

    /* -------------------------------------------------------------- dialogue des liens */
    function openLinks(preset){
      if(!C.view||!C.view.active)return null;
      const dlg=ctx.dialog.open({kind:'compare-links',titleId:'jvxDialogTitle',returnFocus:doc.activeElement});
      const box=dlg.box;
      const draft={a:{variant_id:null,scene_id:null},b:{variant_id:null,scene_id:null}};
      const ids=C.view.variant_ids;
      const pick=preset&&preset.scene&&ids.includes(preset.scene.variant_id)?preset.scene.variant_id:ids[0];
      draft.a.variant_id=pick;
      draft.a.scene_id=preset&&preset.scene&&preset.scene.scene_id||(C.view.anchors||{})[pick]||null;
      draft.b.variant_id=ids.find(i=>i!==pick)||null;
      draft.b.scene_id=(C.view.anchors||{})[draft.b.variant_id]||null;
      let error='';
      const paint=()=>{
        clear(box);
        const view=C.view;
        const title=el('h2','','Liens entre scènes');title.id='jvxDialogTitle';box.appendChild(title);
        box.appendChild(el('p','',"Deux scènes liées comptent comme la même scène logique : la navigation synchronisée les suit ensemble. Un lien ne modifie aucune variante."));
        const rows=CC.linkRows(view);
        const list=el('ul','jvx-set');list.setAttribute('aria-label','Liens manuels');
        if(!rows.length)list.appendChild(el('li','jvx-bidi','Aucun lien manuel.'));
        rows.forEach(r=>{
          const li=el('li');
          li.appendChild(el('span','jvx-rowtitle jvx-bidi',`${CC.describeSide(r.a)}  ↔  ${CC.describeSide(r.b)}`));
          if(r.stale)li.appendChild(el('span','jvx-chip','périmé'));
          const rm=button('Retirer','jvx-btn',async()=>{
            const out=await unlink({variant_id:r.a.variantId,scene_id:r.a.sceneId},{variant_id:r.b.variantId,scene_id:r.b.sceneId});
            error=out&&out.error?out.error.text:'';if(ctx.dialog.current()===dlg)paint();
          },{attrs:{'aria-label':`Retirer le lien ${CC.describeSide(r.a)} avec ${CC.describeSide(r.b)}`}});
          li.appendChild(rm);list.appendChild(li);
        });
        box.appendChild(list);
        const form=el('form');
        form.addEventListener('submit',event=>{event.preventDefault();add()});
        const side=(label,key)=>{
          const f=el('div','jvx-field');
          const lv=el('label','',`${label} : variante`);
          const sv=el('select');sv.id=`jvxLink${key}V`;lv.setAttribute('for',sv.id);
          ids.forEach(i=>{const v=CC.variantOf(view,i);if(!v)return;const o=el('option','',`#${v.variant_number} ${cleanLine(v.title,40)}`);o.value=i;sv.appendChild(o)});
          sv.value=draft[key].variant_id||'';
          const ls=el('label','',`${label} : scène`);
          const ss=el('select');ss.id=`jvxLink${key}S`;ls.setAttribute('for',ss.id);
          const v=CC.variantOf(view,draft[key].variant_id);
          (v&&v.scenes||[]).forEach((s,i)=>{const o=el('option','',CC.sceneLabel(s,i));o.value=s.scene_id;ss.appendChild(o)});
          if(!(v&&v.scenes||[]).some(s=>s.scene_id===draft[key].scene_id))draft[key].scene_id=v&&v.scenes[0]&&v.scenes[0].scene_id||null;
          ss.value=draft[key].scene_id||'';
          sv.addEventListener('change',()=>{draft[key].variant_id=sv.value;draft[key].scene_id=null;paint();});
          ss.addEventListener('change',()=>{draft[key].scene_id=ss.value});
          for(const n of [lv,sv,ls,ss])f.appendChild(n);
          return f;
        };
        form.appendChild(side('Scène A','a'));form.appendChild(side('Scène B','b'));
        const err=el('div','jvx-error',error);err.setAttribute('role','alert');form.appendChild(err);
        const actions=el('div','jvx-dialog-actions');
        actions.appendChild(button('Fermer','jvx-btn',()=>ctx.dialog.cancel()));
        const ok=button('Lier ces deux scènes','jvx-btn',null,{});ok.setAttribute('data-primary','');ok.setAttribute('type','submit');
        actions.appendChild(ok);form.appendChild(actions);box.appendChild(form);
        dlg.firstField=form.querySelector('select');
      };
      const add=async()=>{
        if(!draft.a.variant_id||!draft.b.variant_id||!draft.a.scene_id||!draft.b.scene_id){error='Choisissez une scène de chaque côté.';paint();return}
        if(draft.a.variant_id===draft.b.variant_id){error='Un lien relie deux variantes différentes.';paint();return}
        const out=await link({variant_id:draft.a.variant_id,scene_id:draft.a.scene_id},{variant_id:draft.b.variant_id,scene_id:draft.b.scene_id});
        error=out&&out.error?out.error.text:'';
        if(ctx.dialog.current()===dlg){paint();if(!error&&dlg.firstField)dlg.firstField.focus()}
      };
      paint();
      if(dlg.firstField)dlg.firstField.focus();
      return dlg;
    }
    function openCompose(preset){
      if(!C.view||!C.view.active)return null;
      return ctx.compose.openDialog(Object.assign({returnFocus:doc.activeElement},preset||{}));
    }

    /* -------------------------------------------------------------- relecture après une relecture du graphe */
    function onGraph(){
      const live=id=>{const n=ctx.nodeOf(id);return !!n&&n.state==='live'};
      const before=C.marks.length;
      C.marks=CC.pruneMarks(C.marks,live);
      if(C.marks.length!==before)ctx.repaintTrees();
      renderBar();
      if(C.active)refreshView();
    }

    /* -------------------------------------------------------------- commandes (voix / agent) */
    function requireActive(){return C.active&&C.view?null:{state:'refused',code:'explorer_page_error',reason:"Aucune comparaison n'est ouverte."}}
    function fromOut(out,extra){
      if(out&&out.error)return {state:'refused',code:'explorer_page_error',reason:cleanLine(out.error.text,200)};
      return Object.assign({state:'done',view:summary()},extra||{});
    }
    function summary(){
      const v=C.view;
      if(!v||!v.active)return {active:false};
      return {active:true,revision:v.revision,variant_ids:v.variant_ids.slice(),layout:v.layout,pair:v.pair,mode:v.mode,anchors:Object.assign({},v.anchors||{}),
        relation:v.structure&&v.structure.relation||null,links:(v.links||[]).length,
        statuses:C.nav?Object.fromEntries(Object.keys(C.nav.results||{}).map(k=>[k,C.nav.results[k].status]).concat([[C.nav.origin.variant_id,'origin']])):{}};
    }
    async function handleCommand(command){
      const op=command&&command.op;
      if(command.action==='compare'){
        if(op==='open')return fromOut(await start({variant_ids:command.variant_ids,pair:command.pair,mode:command.mode}));
        if(op==='close'){const r=await close({wait:true});return {state:'done',view:{active:false},was_active:r.was_active}}
        const bad=requireActive();if(bad)return bad;
        if(op==='focus')return fromOut(await setPair(command.pair||null));
        if(op==='mode')return fromOut(await setMode(command.mode));
        if(op==='navigate')return fromOut(await navigate({variant_id:command.variant_id,scene_id:command.scene_id,step:command.step}));
        if(op==='link')return fromOut(await link(command.a,command.b));
        if(op==='unlink')return fromOut(await unlink(command.a,command.b));
        return {state:'refused',code:'explorer_page_error',reason:'opération de comparaison inconnue'};
      }
      if(command.action==='compose'){
        const bad=requireActive();if(bad)return bad;
        if(op==='plan'){const r=await ctx.compose.plan(command.request||{});return r.error?{state:'refused',code:'explorer_page_error',reason:r.error.text,conflicts:r.conflicts||[]}:Object.assign({state:'done'},r)}
        if(op==='create'){const r=await ctx.compose.commit(command.request||{});return r.error||r.ok===false?{state:'refused',code:'explorer_page_error',reason:r.error&&r.error.text||'Composition refusée.',conflicts:r.conflicts||[]}:Object.assign({state:'done'},r)}
        if(op==='dialog'){openCompose(command.request?{preset:command.request}:{});return {state:'done'}}
      }
      return {state:'refused',code:'explorer_page_error',reason:'action inconnue'};
    }

    const api={
      marks:()=>C.marks.slice(),markSet,mark:id=>toggleMark(id),clearMarks,isActive:()=>C.active,view:()=>C.view,summary,
      start,close,setPair,setMode,navigate,link,unlink,refresh:refreshView,openLinks,openCompose,handleCommand,onGraph,renderBar,
      buildBar,buildRoot,toggleMark,
      state:()=>({active:C.active,marks:C.marks.slice(),summary:summary(),docs:Array.from(C.docs.entries()).map(([id,e])=>({id,status:e.status,rev:e.rev})),mounted:Array.from(C.mounted.keys())}),
      shutdown(){C.marks=[];if(C.active)close({quiet:true});else{showRoot(false);renderBar()}},
    };
    return api;
  }

  /* ------------------------------------------------------------------ feuille de style (ajoutée à celle de l'explorateur) */
  const CSS=`
#${HOST_ID} .jvx-cmp-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px 16px 8px}
#${HOST_ID} .jvx-cmp-bar[hidden]{display:none}
#${HOST_ID} .jvx-cmp-bar-text{flex:1 1 auto;min-width:0;font-size:13px;color:var(--jvx-ink)}
#${HOST_ID} .jvx-cmp-bar .jvx-btn{min-height:30px;padding:0 10px;font-size:13px}
#${HOST_ID} .jvx-mark{flex:none;width:1.2em;text-align:center;font-weight:700;color:var(--jvx-accent)}
#${HOST_ID} .jvx-row[data-marked="true"]{box-shadow:inset 3px 0 0 var(--jvx-accent)}
#${HOST_ID} .jvx-body>.jvx-compare{grid-column:2;grid-row:1}
#${HOST_ID} .jvx-compare{display:flex;flex-direction:column;gap:10px;min-height:0;min-width:0;padding:12px 16px;overflow:auto;container-type:inline-size;container-name:jvxcmp}
#${HOST_ID} .jvx-compare[hidden]{display:none}
#${HOST_ID} .jvx-cmp-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
#${HOST_ID} .jvx-cmp-title{margin:0 auto 0 0;font-size:15px;font-weight:650}
#${HOST_ID} .jvx-cmp-toolbar .jvx-btn{min-height:32px;padding:0 10px;font-size:13px}
#${HOST_ID} .jvx-cmp-toolbar .jvx-btn[aria-pressed="true"]{border-color:var(--jvx-accent)}
#${HOST_ID} .jvx-cmp-banner{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:8px 12px;border-radius:9px;border:1px solid color-mix(in srgb,var(--jvx-warn) 50%,transparent);
  color:var(--jvx-warn);background:color-mix(in srgb,var(--jvx-warn) 8%,transparent);font-size:13px}
#${HOST_ID} .jvx-cmp-banner[hidden]{display:none}
#${HOST_ID} .jvx-cmp-banner-text{flex:1 1 240px;min-width:0}
#${HOST_ID} .jvx-cmp-banner .jvx-btn{min-height:28px;padding:0 10px;font-size:12px}
#${HOST_ID} .jvx-cmp-grid{flex:1 1 auto;min-height:0;display:grid;gap:12px;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:minmax(0,1fr);align-content:stretch}
#${HOST_ID} .jvx-cmp-grid[data-count="2"]{grid-auto-rows:minmax(220px,auto)}
#${HOST_ID} .jvx-cmp-pane{display:flex;flex-direction:column;gap:6px;min-height:0;min-width:0;padding:8px;border-radius:12px;border:1px solid var(--jvx-line);background:var(--jvx-surface)}
#${HOST_ID} .jvx-cmp-pane[hidden]{display:none}
#${HOST_ID} .jvx-cmp-pane:focus-visible{outline:2px solid var(--jvx-accent);outline-offset:2px}
#${HOST_ID} .jvx-cmp-panehead{display:flex;align-items:center;gap:8px;min-width:0}
#${HOST_ID} .jvx-cmp-name{flex:1 1 auto;min-width:0;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${HOST_ID} .jvx-cmp-status[data-status="synced"]{color:var(--jvx-ok)}
#${HOST_ID} .jvx-cmp-status[data-status="unmapped"]{color:var(--jvx-warn)}
#${HOST_ID} .jvx-cmp-status[data-status="origin"]{color:var(--jvx-accent)}
#${HOST_ID} .jvx-cmp-stagewrap{min-height:90px}
#${HOST_ID} .jvx-cmp-nav{display:flex;align-items:center;gap:6px;min-width:0}
#${HOST_ID} .jvx-cmp-nav .jvx-btn{min-height:30px;width:30px}
#${HOST_ID} .jvx-cmp-select{flex:1 1 auto;min-width:0;min-height:30px;border-radius:8px;border:1px solid var(--jvx-line-strong);background:rgba(0,0,0,.35);color:var(--jvx-ink);font:inherit;padding:0 6px}
#${HOST_ID} .jvx-field select{width:100%;min-height:36px;border-radius:8px;border:1px solid var(--jvx-line-strong);background:rgba(0,0,0,.35);color:var(--jvx-ink);font:inherit;padding:0 8px}
#${HOST_ID} .jvx-cmp-count{flex:none;font-size:12px;color:var(--jvx-mute);font-variant-numeric:tabular-nums}
#${HOST_ID} .jvx-cmp-line{margin:0;font-size:12.5px;color:var(--jvx-mute);min-height:1.4em}
#${HOST_ID} .jvx-cmp-line[data-status="unmapped"]{color:var(--jvx-warn)}
#${HOST_ID} .jvx-cmp-tools{display:flex;gap:6px;flex-wrap:wrap}
#${HOST_ID} .jvx-cmp-tools .jvx-btn{min-height:28px;padding:0 10px;font-size:12px}
#${HOST_ID} .jvx-cmp-tools .jvx-btn[data-emphasis="true"]{border-color:color-mix(in srgb,var(--jvx-warn) 55%,transparent)}
#${HOST_ID} .jvx-cmp-tools .jvx-btn[aria-pressed="true"]{border-color:var(--jvx-accent)}
@container jvxcmp (max-width:${CC.NARROW_PX}px){
  #${HOST_ID} .jvx-cmp-grid{grid-template-columns:minmax(0,1fr);grid-auto-rows:minmax(260px,auto)}
}
#${HOST_ID} .jvx-conflicts{margin:0;padding:0;list-style:none;display:grid;gap:8px}
#${HOST_ID} .jvx-conflicts li{padding:8px 10px;border-radius:9px;border:1px solid color-mix(in srgb,var(--jvx-danger) 45%,transparent);background:color-mix(in srgb,var(--jvx-danger) 7%,transparent)}
#${HOST_ID} .jvx-conflicts .jvx-fix{display:block;margin-top:4px;color:var(--jvx-ink)}
#${HOST_ID} .jvx-plan-ok{padding:8px 10px;border-radius:9px;border:1px solid color-mix(in srgb,var(--jvx-ok) 45%,transparent);color:var(--jvx-ok)}
@media (forced-colors:active){#${HOST_ID} .jvx-cmp-pane{border-color:CanvasText}}
`;

  const api=Object.freeze({createCompare,CSS});
  root.JarvisStudioExplorerCompare=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
