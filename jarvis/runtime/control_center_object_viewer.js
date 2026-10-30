/* Object viewer — transient in-app modal, never browser Fullscreen API state.
   Visual direction: extend Jarvis' dark Operate surface; content leads inside
   a quiet comparison desk, compact controls above, generous reading area below.
   Native dialog owns modality/focus, existing providers own document rendering.
   No scene writes, transport, frame construction, unsandboxed HTML or document store.
   See docs/object-viewer.md for entry/provider and navigation contracts. */
(function(root){
  'use strict';
  const MAX_ENTRIES=512,MAX_HISTORY=8,LOAD_MS=20000,STYLE_ID='jv-object-viewer-style';
  const ID=/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
  const LAYOUTS=Object.freeze({single:'Un document',horizontal:'Deux côte à côte',vertical:'Deux superposés',quad:'Quatre documents',
    row:'Ligne',column:'Colonne',auto:'Grille automatique',custom:'Grille personnalisée',largeLeft:'Grand à gauche',largeTop:'Grand en haut'});
  const payloadUrl=id=>typeof id==='string'&&ID.test(id)?'/api/artifacts/'+encodeURIComponent(id)+'/payload':null;
  const clean=(value,max=160)=>String(value==null?'':value).slice(0,max);
  const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
  function gridSize(rows,cols){
    if(!Number.isInteger(rows)||!Number.isInteger(cols)||rows<1||cols<1||rows>64||cols>64||rows*cols>MAX_ENTRIES)
      throw new RangeError('Choisissez de 1 à 64 lignes et colonnes, pour 512 cases au plus.');
    return {rows,cols};
  }
  function layoutPlan(count,name='auto',options={}){
    if(!Number.isInteger(count)||count<1||count>MAX_ENTRIES)throw new RangeError('Le viewer accepte de 1 à 512 documents.');
    if(!Object.prototype.hasOwnProperty.call(LAYOUTS,name))throw new RangeError('Disposition inconnue.');
    let cols=1,rows=1,capacity=count;
    if(name==='single')capacity=1;
    else if(['horizontal','largeLeft'].includes(name)){cols=2;capacity=2}
    else if(['vertical','largeTop'].includes(name)){rows=2;capacity=2}
    else if(name==='quad'){cols=2;rows=2;capacity=4}
    else if(name==='row')cols=count;
    else if(name==='column')rows=count;
    else if(name==='custom'){({rows,cols}=gridSize(options.rows,options.cols));capacity=rows*cols}
    else if(name==='auto'){
      cols=Math.max(1,Math.min(count,Math.floor((options.width||1000)/230),Math.ceil(Math.sqrt(count*1.25))));
      rows=Math.ceil(count/cols);
    }
    return {name,cols,rows,capacity,pages:Math.ceil(count/capacity)};
  }
  const STYLE=`
.jvov{position:fixed;inset:0;margin:0;width:100vw;max-width:none;height:100dvh;max-height:none;border:0;
  padding:24px 28px;box-sizing:border-box;background:rgba(3,7,11,.96);color:var(--text,#d8edf7);font:14px/1.5 system-ui,Segoe UI,sans-serif;overflow:hidden}
.jvov[open]{display:flex;flex-direction:column;gap:16px}
.jvov::backdrop{background:rgba(0,0,0,.72);backdrop-filter:blur(12px)}
.jvov *{box-sizing:border-box}
.jvov [hidden]{display:none!important}
.jvov-head{display:flex;align-items:center;gap:16px;flex:none}
.jvov-title{font-size:20px;font-weight:650;line-height:1.3;margin:0;overflow-wrap:anywhere}
.jvov-caption{margin:3px 0 0;color:var(--muted,#9bb0bd);font-size:13px}
.jvov-heading{min-width:0;flex:1}
.jvov button,.jvov select,.jvov input{font:inherit;color:inherit;background:var(--solid,#0d1720);border:1px solid var(--line,#29404f);border-radius:7px;min-height:36px;padding:6px 11px}
.jvov button{cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:7px;white-space:nowrap}
.jvov button:hover:not(:disabled){border-color:var(--accent,#6ee7ff);background:#152532}
.jvov button:disabled{opacity:.45;cursor:default}
.jvov :focus-visible{outline:2px solid var(--accent,#6ee7ff);outline-offset:3px}
.jvov button svg{width:16px;height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.jvov-tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap;flex:none}
.jvov-tools label,.jvov-custom label{display:flex;gap:8px;align-items:center;font-size:13px}
.jvov-layout-preview{display:grid;gap:3px;width:54px;height:34px;padding:4px;border:1px solid var(--line,#29404f);border-radius:4px;flex:none;color:var(--muted,#9bb0bd);pointer-events:none}
.jvov-layout-preview i{display:block;min-width:0;min-height:0;background:currentColor;border-radius:1px}
.jvov-pages{display:flex;gap:8px;align-items:center;margin-left:auto;font-size:13px}
.jvov-custom{display:flex;align-items:flex-start;gap:16px;flex-wrap:wrap;flex:none}
.jvov-fields{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding-top:3px}
.jvov-fields input{width:70px}
.jvov-picker{display:grid;grid-template-columns:repeat(6,24px);gap:3px}
.jvov-picker button{min-height:24px;width:24px;padding:0;border-radius:3px;background:#111f29}
.jvov-picker button[data-chosen]{border-color:var(--accent,#6ee7ff);background:#214050}
.jvov-notice{margin:0;color:var(--warn,#ffbf75);font-size:13px;flex:none;overflow-wrap:anywhere}
.jvov-body{flex:1;min-height:0;overflow:hidden;display:flex}
.jvov-screen{width:100%;min-width:0;min-height:0;flex:1;overflow:auto;overscroll-behavior:contain}
.jvov-grid{display:grid;gap:16px;min-width:100%;min-height:100%;height:100%}
.jvov-tile{min-width:0;min-height:0;display:flex;flex-direction:column;border:1px solid var(--line,#263c4b);border-radius:9px;background:rgba(12,21,28,.82);overflow:hidden}
.jvov-tile-head{font-size:13px;font-weight:600;padding:10px 13px;margin:0;flex:none;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;border-bottom:1px solid var(--line,#263c4b)}
.jvov-content{flex:1;min-height:0;min-width:0;position:relative;display:flex;flex-direction:column;overflow:hidden}
.jvov-slot{flex:1;min-height:0;min-width:0;overflow:auto;overscroll-behavior:contain}
.jvov-slot:has(> .sc-prefab-frame){display:flex;flex-direction:column}
.jvov-slot>.sc-prefab-frame{flex:1;min-height:0;height:100%;width:100%;border:0}
.jvov-text{margin:0;padding:22px 26px;white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.65 system-ui,Segoe UI,sans-serif;max-width:78ch}
.jvov-image{flex:1;min-height:0;display:grid;place-items:center;overflow:hidden;touch-action:none;position:relative;background:#030609}
.jvov-image img{position:absolute;inset:0;display:block;width:100%;height:100%;object-fit:contain;transform-origin:center;user-select:none;pointer-events:none}
.jvov-image[data-zoomed]{cursor:grab}
.jvov-image[data-dragging]{cursor:grabbing}
.jvov-image-tools{padding:8px;display:flex;flex-wrap:wrap;justify-content:center;gap:6px;align-items:center;flex:none;border-top:1px solid var(--line,#263c4b);font-size:12px}
.jvov-image-tools button{min-height:30px;padding:3px 9px;font-size:12px}
.jvov-state{padding:24px;display:flex;flex-direction:column;gap:12px;align-items:flex-start;overflow:auto}
.jvov-state p{margin:0;max-width:65ch;overflow-wrap:anywhere}
.jvov-state a{color:var(--accent,#6ee7ff)}
.jvov-busy{display:flex;align-items:center;gap:10px}
.jvov-busy svg{height:18px;width:18px;flex:none;animation:jvov-turn 1s linear infinite;stroke:var(--accent,#6ee7ff);fill:none;stroke-width:2}
@keyframes jvov-turn{to{transform:rotate(360deg)}}
@media(max-width:700px){.jvov{padding:14px 12px}.jvov[open]{gap:12px}.jvov-title{font-size:17px}.jvov-head{gap:9px}.jvov-tools{gap:8px}.jvov-pages{margin-left:0}.jvov-grid{gap:10px}.jvov-text{padding:16px}}
@media(prefers-reduced-motion:reduce){.jvov *{animation:none!important;transition:none!important}.jvov-busy svg{stroke-dasharray:3 2}}
@media(forced-colors:active){.jvov,.jvov-tile,.jvov button,.jvov select,.jvov input{background:Canvas;color:CanvasText;border-color:CanvasText}}
`;
  function create(deps={}){
    const doc=deps.document||root.document,win=deps.window||root;
    if(!doc||!win)throw new TypeError('Le viewer requiert un document et une fenêtre.');
    const log=(level,event,data={})=>{
      if(deps.log)deps.log(level,'viewer.'+event,data);
      else if(typeof root.obsClientLog==='function')root.obsClientLog(level,'UI','viewer.'+event+' '+JSON.stringify(data));
      else if(win.console)win.console[level==='error'?'error':'info']('[viewer] '+event,data);
    };
    const element=(tag,className,text)=>{const el=doc.createElement(tag);if(className)el.className=className;if(text!=null)el.textContent=text;return el};
    const icon=path=>{const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 20 20');svg.setAttribute('aria-hidden','true');const p=doc.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',path);svg.appendChild(p);return svg};
    const button=(text,path,action)=>{const el=element('button','',text);el.type='button';if(path)el.prepend(icon(path));if(action)el.addEventListener('click',action);return el};
    if(!doc.getElementById(STYLE_ID)){const style=element('style');style.id=STYLE_ID;style.textContent=STYLE;doc.head.appendChild(style)}
    const dialog=element('dialog','jvov');dialog.id='jvObjectViewer';dialog.setAttribute('aria-labelledby','jvObjectViewerTitle');dialog.setAttribute('aria-modal','true');
    const head=element('header','jvov-head'),backButton=button('Retour','M12 4l-6 6 6 6',()=>back());
    const heading=element('div','jvov-heading'),title=element('h1','jvov-title'),caption=element('p','jvov-caption');title.id='jvObjectViewerTitle';
    heading.append(title,caption);const closeButton=button('Fermer','M5 5l10 10M15 5L5 15',()=>close());closeButton.dataset.action='close';
    head.append(backButton,heading,closeButton);
    const tools=element('div','jvov-tools'),label=element('label','', 'Disposition'),select=element('select');select.setAttribute('aria-label','Disposition des documents');
    for(const [value,text] of Object.entries(LAYOUTS)){const option=element('option','',text);option.value=value;select.appendChild(option)}
    const schematic=element('span','jvov-layout-preview');schematic.setAttribute('aria-hidden','true');
    label.appendChild(select);tools.append(label,schematic);
    const pages=element('div','jvov-pages'),previous=button('Précédent','M12 4l-6 6 6 6',()=>page(-1)),pageText=element('span'),next=button('Suivant','M8 4l6 6-6 6',()=>page(1));
    pages.append(previous,pageText,next);tools.append(pages);
    const custom=element('div','jvov-custom'),picker=element('div','jvov-picker');picker.setAttribute('role','group');picker.setAttribute('aria-label','Choisir une grille, jusqu’à 6 lignes et 6 colonnes');
    const fields=element('div','jvov-fields'),rowInput=element('input'),colInput=element('input');
    for(const [input,name] of [[rowInput,'Lignes'],[colInput,'Colonnes']]){input.type='number';input.min='1';input.max='64';input.value='2';const l=element('label','',name);l.appendChild(input);fields.appendChild(l)}
    const applyGrid=button('Appliquer',null,()=>setLayout('custom',{rows:Number(rowInput.value),cols:Number(colInput.value)}));fields.appendChild(applyGrid);
    for(let row=1;row<=6;row++)for(let col=1;col<=6;col++){
      const pick=button('',null,()=>setLayout('custom',{rows:row,cols:col}));pick.setAttribute('aria-label',row+' lignes × '+col+' colonnes');pick.title=row+' × '+col;pick.tabIndex=row===1&&col===1?0:-1;
      pick.dataset.rows=String(row);pick.dataset.cols=String(col);picker.appendChild(pick);
    }
    picker.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
      const items=Array.from(picker.children),index=items.indexOf(event.target);if(index<0)return;
      event.preventDefault();const shift={ArrowLeft:-1,ArrowRight:1,ArrowUp:-6,ArrowDown:6}[event.key],at=clamp(index+shift,0,35);
      items.forEach((el,i)=>el.tabIndex=i===at?0:-1);items[at].focus();
    });
    custom.append(picker,fields);const notice=element('p','jvov-notice');notice.setAttribute('role','status');notice.setAttribute('aria-live','polite');
    const body=element('div','jvov-body');dialog.append(head,tools,custom,notice,body);doc.body.appendChild(dialog);
    const screens=[];let returnFocus=null,onClose=null,clock=0,destroyed=false;
    const current=()=>screens[screens.length-1]||null;
    const now=()=>deps.now?deps.now():Date.now();
    function announce(message){notice.textContent=message||'';notice.hidden=!message}
    function failure(action,error){
      const message=clean(error&&error.message||error,300);
      if(!dialog.open){ensureOpen({});title.textContent='Ouverture impossible';caption.textContent='Vérifiez les documents sélectionnés.';tools.hidden=true;custom.hidden=true;backButton.hidden=true;closeButton.focus()}
      announce(message);log('error',action+'_failed',{message});return {ok:false,code:'viewer_'+action+'_failed',message};
    }
    function disposeRecord(record){
      if(record.observer)record.observer.disconnect();
      if(record.abort)record.abort.abort();
      if(record.controller&&record.controller.dispose){try{record.controller.dispose()}catch(error){log('error','dispose_failed',{id:record.id,message:clean(error.message,300)})}}
      record.controller=null;record.paused=false;record.generation++;
    }
    function disposeScreen(screen){screen.records.forEach(disposeRecord);screen.el.remove()}
    function syncRecord(record){
      if(!record.controller)return;const screen=record.tile.closest('.jvov-screen');
      const paused=!dialog.open||!screen||screen.hidden||record.tile.hidden;if(paused===record.paused)return;
      record.paused=paused;const fn=paused?record.controller.pause:record.controller.resume;
      if(fn)try{fn()}catch(error){log('error','provider_lifecycle_failed',{id:record.id,message:clean(error.message,300)})}
    }
    function hideScreen(screen,hidden){
      screen.el.hidden=hidden;
      screen.records.forEach(syncRecord);
    }
    function updateClock(){for(const screen of screens)if(!screen.el.hidden)for(const record of screen.records)if(record.state==='loading'){
      const elapsed=Math.max(0,Math.floor((now()-record.started)/1000));record.stateText.textContent='Chargement de '+record.title+'… '+elapsed+' s';
      if(now()-record.started>=LOAD_MS)record.fail(new Error('Le chargement a dépassé 20 s. Réessayez ou fermez le viewer.'));
    }}
    function ensureOpen(options){
      if(destroyed)throw new Error('Ce viewer a été fermé définitivement.');
      if(!dialog.open){
        returnFocus=options.returnFocus||doc.activeElement;onClose=options.onClose||null;
        dialog.showModal();clock=win.setInterval(updateClock,500);log('info','opened');
      }else if(!options.push){while(screens.length)disposeScreen(screens.pop())}
      if(options.push&&screens.length>=MAX_HISTORY)throw new RangeError('Revenez au document précédent avant d’en ouvrir un autre.');
      const previous=current();if(previous)hideScreen(previous,true);
    }
    function normalizeEntries(entries){
      if(!Array.isArray(entries)||!entries.length||entries.length>MAX_ENTRIES)throw new RangeError('Sélectionnez de 1 à 512 documents à ouvrir.');
      const seen=new Set();return entries.map((entry,index)=>{
        if(!entry||typeof entry!=='object')throw new TypeError('Document invalide.');
        const id=clean(entry.id||entry.artifactId||'entry-'+index,128);if(seen.has(id))throw new Error('Deux documents ont le même identifiant.');seen.add(id);
        return {...entry,id,title:clean(entry.title||'Document '+(index+1)),kind:entry.kind||'unsupported'};
      });
    }
    function safeController(value){return typeof value==='function'?{dispose:value}:value&&typeof value==='object'?value:{}}
    function createRecord(entry){
      const tile=element('section','jvov-tile');tile.dataset.entryId=entry.id;
      const tileTitle=element('h2','jvov-tile-head',entry.title);tileTitle.title=entry.title;
      const content=element('div','jvov-content'),slot=element('div','jvov-slot'),stateBox=element('div','jvov-state'),busy=element('div','jvov-busy');
      busy.appendChild(icon('M10 2a8 8 0 1 1-8 8'));const stateText=element('p');busy.appendChild(stateText);
      const retry=button('Réessayer',null,()=>mount(record));retry.hidden=true;stateBox.setAttribute('role','status');stateBox.append(busy,retry);content.append(slot,stateBox);tile.append(tileTitle,content);
      const record={id:entry.id,title:entry.title,entry,tile,slot,stateBox,stateText,busy,retry,state:'idle',controller:null,generation:0,started:0,abort:null};
      record.ready=()=>{if(record.state!=='loading')return;record.state='ready';stateBox.hidden=true;slot.hidden=false;log('info','entry_ready',{id:record.id,kind:entry.kind})};
      record.fail=error=>{
        if(record.state!=='loading')return;record.state='failed';const message=clean(error&&error.message||error,300);
        stateText.textContent=message;busy.querySelector('svg').setAttribute('hidden','');retry.hidden=false;slot.hidden=true;
        stateBox.setAttribute('role','alert');disposeRecord(record);log('error','entry_failed',{id:record.id,kind:entry.kind,message});
      };
      return record;
    }
    function mount(record){
      disposeRecord(record);record.slot.replaceChildren();record.slot.hidden=true;record.stateBox.hidden=false;record.retry.hidden=true;
      record.busy.querySelector('svg').removeAttribute('hidden');record.stateBox.setAttribute('role','status');record.state='loading';record.started=now();record.abort=new win.AbortController();
      record.stateText.textContent='Chargement de '+record.title+'… 0 s';const generation=record.generation;
      const valid=()=>record.generation===generation&&!record.abort.signal.aborted;
      const context={signal:record.abort.signal,ready:()=>{if(valid())record.ready()},fail:error=>{if(valid())record.fail(error)},
        viewer:api,document:doc,window:win,log};
      log('info','entry_loading',{id:record.id,kind:record.entry.kind});
      try{
        const result=render(record,context);
        Promise.resolve(result).then(controller=>{
          const instance=safeController(controller);
          if(!valid()){if(instance.dispose)instance.dispose();return}
          record.controller=instance;if(!instance.pending)record.ready();
          syncRecord(record);
        }).catch(error=>{if(valid())record.fail(error);else if(error&&error.name!=='AbortError')log('error','provider_late_failure',{id:record.id,message:clean(error.message,300)})});
      }catch(error){record.fail(error)}
    }
    function unsupported(record,message,url){
      const note=element('div','jvov-state'),p=element('p','',message);note.appendChild(p);
      if(url){const link=element('a','',record.entry.kind==='pdf'?'Ouvrir le PDF dans un nouvel onglet':'Ouvrir le fichier dans un nouvel onglet');link.href=url;link.target='_blank';link.rel='noopener noreferrer';note.appendChild(link)}
      record.slot.appendChild(note);record.code=record.entry.kind==='pdf'?'provider_missing':'unsupported_content';
    }
    function render(record,context){
      const entry=record.entry,url=payloadUrl(entry.artifactId);
      if(typeof entry.mount==='function')return entry.mount(record.slot,context);
      if(typeof deps.renderEntry==='function'&&['provider','pdf'].includes(entry.kind))return deps.renderEntry(entry,record.slot,context);
      if(entry.kind==='text'){
        const text=clean(entry.text,500000);record.slot.appendChild(element(text?'pre':'p',text?'jvov-text':'jvov-state',text||'Ce document ne contient pas de texte.'));
        if(!text)record.code='empty_content';return {};
      }
      if(entry.kind==='image'){
        if(!url)throw new Error('Cette image ne possède pas de référence Artifact valide.');
        return image(record,url,context);
      }
      unsupported(record,entry.kind==='pdf'?'Aperçu PDF indisponible ici. Vous pouvez ouvrir le fichier dans un nouvel onglet.':clean(entry.message||'Ce contenu ne possède pas encore d’aperçu dans le viewer.',300),url);
      return {};
    }
    function image(record,url,context){
      record.slot.style.display='flex';record.slot.style.flexDirection='column';record.slot.style.overflow='hidden';
      const viewport=element('div','jvov-image'),img=element('img'),bar=element('div','jvov-image-tools'),zoomText=element('span');
      viewport.tabIndex=0;viewport.setAttribute('role','group');viewport.setAttribute('aria-label',record.title+' : zoom avec + et −, 0 pour ajuster, flèches pour déplacer l’image.');
      img.alt=clean(record.entry.alt||record.title,300);img.draggable=false;img.decoding='async';
      let scale=1,x=0,y=0,drag=null;
      function apply(){
        const bx=viewport.clientWidth*(scale-1)/2,by=viewport.clientHeight*(scale-1)/2;x=clamp(x,-bx,bx);y=clamp(y,-by,by);
        img.style.transform='translate('+x+'px,'+y+'px) scale('+scale+')';zoomText.textContent=Math.round(scale*100)+' %';
        viewport.toggleAttribute('data-zoomed',scale>1);minus.disabled=scale<=1;plus.disabled=scale>=8;
        record.image={scale,x,y};
      }
      function zoom(next){scale=clamp(next,1,8);if(scale===1){x=0;y=0}apply()}
      const minus=button('Réduire','M4 10h12',()=>zoom(scale/1.25)),plus=button('Agrandir','M4 10h12M10 4v12',()=>zoom(scale*1.25)),fit=button('Ajuster',null,()=>zoom(1));
      for(const [control,text,path] of [[minus,'Réduire l’image','M4 10h12'],[plus,'Agrandir l’image','M4 10h12M10 4v12']]){
        control.replaceChildren(icon(path));control.setAttribute('aria-label',text);control.title=text;
      }
      zoomText.style.whiteSpace='nowrap';bar.append(minus,zoomText,plus,fit);viewport.appendChild(img);record.slot.append(viewport,bar);
      img.addEventListener('load',context.ready,{once:true});img.addEventListener('error',()=>context.fail(new Error('L’image ne peut pas être lue. Réessayez ou vérifiez le fichier source.')),{once:true});
      viewport.addEventListener('wheel',event=>{event.preventDefault();zoom(scale*Math.exp(-event.deltaY*.002))},{passive:false});
      viewport.addEventListener('pointerdown',event=>{if(event.button!==0||scale<=1)return;drag={id:event.pointerId,x:event.clientX,y:event.clientY,startX:x,startY:y};viewport.setPointerCapture(event.pointerId);viewport.toggleAttribute('data-dragging',true);event.preventDefault()});
      viewport.addEventListener('pointermove',event=>{if(!drag||drag.id!==event.pointerId)return;x=drag.startX+event.clientX-drag.x;y=drag.startY+event.clientY-drag.y;apply()});
      const end=()=>{drag=null;viewport.removeAttribute('data-dragging')};viewport.addEventListener('pointerup',end);viewport.addEventListener('pointercancel',end);viewport.addEventListener('lostpointercapture',end);
      viewport.addEventListener('keydown',event=>{
        if(event.ctrlKey||event.metaKey||event.altKey)return;
        if(['+','=','-','0'].includes(event.key)){event.preventDefault();zoom(event.key==='0'?1:event.key==='-'?scale/1.25:scale*1.25)}
        else if(scale>1&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();x+=event.key==='ArrowLeft'?30:event.key==='ArrowRight'?-30:0;y+=event.key==='ArrowUp'?30:event.key==='ArrowDown'?-30:0;apply()}
      });
      img.src=url;apply();return {pending:true,dispose:()=>{img.removeAttribute('src')}};
    }
    function startWhenVisible(record,screen){
      if(record.state!=='idle')return;
      if(typeof win.IntersectionObserver!=='function'){mount(record);return}
      if(record.observer)return;
      record.observer=new win.IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)){
        record.observer.disconnect();record.observer=null;if(!screen.el.hidden&&!record.tile.hidden)mount(record);
      }},{root:screen.el,rootMargin:'100px'});record.observer.observe(record.tile);
    }
    function refresh(){
      const screen=current();if(!screen)return;backButton.hidden=screens.length<2;title.textContent=screen.title;tools.hidden=screen.kind!=='objects';custom.hidden=screen.kind!=='objects'||screen.layout!=='custom';
      announce(screen.notice);caption.textContent=screen.kind==='objects'?screen.records.length+' document'+(screen.records.length>1?'s':'')+' · Échap pour fermer':'Échap pour fermer';
      if(screen.kind!=='objects')return;
      select.value=screen.layout;const plan=layoutPlan(screen.records.length,screen.layout,{...screen.grid,width:body.clientWidth});screen.page=clamp(screen.page,0,plan.pages-1);screen.plan=plan;
      const paged=plan.pages>1,start=screen.page*plan.capacity,end=Math.min(screen.records.length,start+plan.capacity);
      pages.hidden=!paged;previous.disabled=screen.page===0;next.disabled=screen.page===plan.pages-1;pageText.textContent=(start+1)+'–'+end+' / '+screen.records.length;
      const multi=screen.layout==='row'||screen.layout==='column'||(screen.layout==='auto'&&plan.rows>2);
      screen.gridEl.style.gridTemplateColumns=screen.layout==='largeLeft'?'minmax(0,2fr) minmax(0,1fr)':
        'repeat('+plan.cols+',minmax('+(screen.layout==='row'?'220px':'0')+',1fr))';
      screen.gridEl.style.gridTemplateRows=screen.layout==='largeTop'?'minmax(0,2fr) minmax(0,1fr)':
        'repeat('+plan.rows+',minmax('+(multi?'180px':'0')+',1fr))';
      screen.gridEl.style.height=multi?'max(100%, '+(plan.rows*180+(plan.rows-1)*16)+'px)':'100%';
      const sampleRows=Math.min(4,plan.rows),sampleCols=Math.min(6,plan.cols);
      schematic.dataset.layout=screen.layout;schematic.title=LAYOUTS[screen.layout]+' · '+plan.rows+' × '+plan.cols;
      schematic.style.gridTemplateColumns=screen.layout==='largeLeft'?'2fr 1fr':'repeat('+sampleCols+',minmax(0,1fr))';
      schematic.style.gridTemplateRows=screen.layout==='largeTop'?'2fr 1fr':'repeat('+sampleRows+',minmax(0,1fr))';
      schematic.replaceChildren(...Array.from({length:Math.min(screen.records.length,plan.capacity,sampleRows*sampleCols)},()=>element('i')));
      screen.records.forEach((record,index)=>{const visible=index>=start&&index<end;record.tile.hidden=!visible;syncRecord(record);if(visible)startWhenVisible(record,screen)});
      rowInput.value=String(screen.grid.rows);colInput.value=String(screen.grid.cols);
      for(const item of picker.children)item.toggleAttribute('data-chosen',Number(item.dataset.rows)<=screen.grid.rows&&Number(item.dataset.cols)<=screen.grid.cols);
    }
    function openObjects(entries,options={}){
      try{
        const normalized=normalizeEntries(entries),gridSizeValue=options.grid?gridSize(options.grid.rows,options.grid.cols):{rows:2,cols:2};
        layoutPlan(normalized.length,options.layout||'auto',gridSizeValue);ensureOpen(options);
        const el=element('div','jvov-screen'),grid=element('div','jvov-grid');el.appendChild(grid);
        const screen={kind:'objects',el,gridEl:grid,title:clean(options.title||'Documents'),notice:clean(options.notice||'',500),
          layout:options.layout||'auto',grid:gridSizeValue,page:0,records:normalized.map(createRecord)};
        layoutPlan(normalized.length,screen.layout,screen.grid);screen.records.forEach(record=>grid.appendChild(record.tile));body.appendChild(el);screens.push(screen);refresh();
        closeButton.focus();log('info','objects_opened',{count:normalized.length,layout:screen.layout});return {ok:true};
      }catch(error){return failure('open',error)}
    }
    function openCustom(spec,options={}){
      try{
        if(!spec||typeof spec.mount!=='function')throw new TypeError('Fournisseur de détail indisponible.');
        ensureOpen(options);const el=element('div','jvov-screen'),record=createRecord({id:clean(spec.id||'detail',128),title:clean(spec.title||'Détail'),kind:'provider',mount:spec.mount});
        record.tile.style.height='100%';record.tile.querySelector('.jvov-tile-head').hidden=true;el.appendChild(record.tile);
        const screen={kind:'custom',el,title:record.title,notice:clean(options.notice||'',500),records:[record]};body.appendChild(el);screens.push(screen);refresh();mount(record);closeButton.focus();log('info','detail_opened',{id:record.id});return {ok:true};
      }catch(error){return failure('open',error)}
    }
    function setLayout(name,options={}){
      const screen=current();if(!screen||screen.kind!=='objects')return {ok:false,code:'viewer_no_documents'};
      try{const size=name==='custom'?gridSize(options.rows??screen.grid.rows,options.cols??screen.grid.cols):screen.grid;layoutPlan(screen.records.length,name,size);screen.layout=name;screen.grid=size;screen.page=0;refresh();log('info','layout_changed',{layout:name,rows:size.rows,cols:size.cols});return {ok:true}}
      catch(error){return failure('layout',error)}
    }
    function page(delta){const screen=current();if(!screen||screen.kind!=='objects')return;screen.page+=delta;refresh();log('info','page_changed',{page:screen.page})}
    function back(){if(screens.length<2)return false;disposeScreen(screens.pop());hideScreen(current(),false);refresh();backButton.hidden=screens.length<2;closeButton.focus();log('info','back');return true}
    function close(){
      if(!dialog.open&&!screens.length&&!clock)return;while(screens.length)disposeScreen(screens.pop());win.clearInterval(clock);clock=0;if(dialog.open)dialog.close();
      const target=returnFocus,callback=onClose;returnFocus=null;onClose=null;if(target&&target.isConnected&&typeof target.focus==='function')target.focus({preventScroll:true});
      log('info','closed');if(callback)try{callback()}catch(error){log('error','close_callback_failed',{message:clean(error.message,300)})}
    }
    function snapshot(){const screen=current();return {open:dialog.open,depth:screens.length,kind:screen&&screen.kind,layout:screen&&screen.layout,page:screen&&screen.page,
      entries:screen?screen.records.map(record=>({id:record.id,state:record.state,code:record.code||null,visible:!record.tile.hidden,paused:!!record.paused,image:record.image||null})):[]}}
    function destroy(){close();destroyed=true;win.removeEventListener('resize',refresh);dialog.remove()}
    select.addEventListener('change',()=>setLayout(select.value));dialog.addEventListener('cancel',event=>{event.preventDefault();close()});
    dialog.addEventListener('close',close);
    win.addEventListener('resize',refresh);const api={openObjects,openCustom,back,close,isOpen:()=>dialog.open,setLayout,snapshot,destroy,element:dialog};return api;
  }
  const api=Object.freeze({MAX_ENTRIES,MAX_HISTORY,LOAD_MS,LAYOUTS,payloadUrl,gridSize,layoutPlan,create});
  root.JarvisObjectViewer=api;if(typeof module==='object'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
