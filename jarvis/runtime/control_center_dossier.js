/* Dossier plein écran — la vue (handoff jarvis-board-ui-wheel-dossier-refactor, Slice 07).

   Contrat : `docs/dossier.md` › *Full-screen Dossier (UI)*. Logique pure :
   `JarvisDossierCore` (`control_center_dossier_core.js`, inséré avant).

   L'espace documentaire du Board affiché : à gauche l'organisation (vue
   d'ensemble, collections, dossiers de la mémoire, filtre), au centre la
   lecture (un onglet « Parcourir » puis un onglet par document, deux côte à
   côte quand l'écran le permet), à droite le contexte (repliable, détails
   techniques derrière une divulgation). Rang 55, comme les autres vues plein
   écran du lanceur ; Variantes (9000) reste au-dessus.

   Trois entrées : la roue (catégorie Dossier), `JarvisDossier.open|openBoard`
   (toast de Ranger, carte Board d'un Board archivé), et Jarvis par le canal
   `/api/dossier/navigation/commands` (long-poll, reçu signé du jeton de page).
   Chaque attente se voit (libellé, compteur, échéance) ; chaque refus se dit
   avec son code ; une écriture n'est confirmée que par le serveur. */
(function(root){
  'use strict';
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const C=root.JarvisDossierCore;
  const host=document.getElementById('dossierView');
  if(!C||!host){console.error('[dossier] dossier.install_failed '+JSON.stringify({code:!C?'dossier_core_missing':'dossier_host_missing'}));return}

  const PAGE_TOKEN='__JARVIS_DOSSIER_PAGE_TOKEN__';
  /* Relevé court d'une commande de Jarvis (Slice 08) : jamais une attente longue. */
  const PULL_TIMEOUT_MS=4000;
  const TICK_MS=500;
  const log=(level,event,data)=>{
    const line=`[dossier] ${event} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line);
  };
  const short=id=>String(id||'').slice(0,8);
  const client=C.createClient({fetchImpl:(path,init)=>window.fetch(path,init)});

  /* ------------------------------------------------------------ état */
  const S={
    open:false,follow:true,boardId:null,board:null,gen:0,
    displayed:null,coreLost:false,
    list:{status:'idle',entries:[],total:0,truncated:false,sources:null,error:null,since:0,at:0},
    section:'home',filter:'',collapsed:new Set(),
    search:{status:'idle',q:'',matches:[],error:null,since:0},
    tabs:[],active:'browse',split:null,
    docs:new Map(),   // entryId -> {entry, status, blocks, meta, text, sha, size, eof, next, error, since, artifact}
    ctxOpen:null,orgOpen:false,advanced:false,adv:new Map(),
    menu:null,      // {kind:'present'|'more', entryId}
    form:null,      // {kind:'move', entryId, value, status, error}
    confirm:null,   // {kind:'delete', entryId, status, error}
    notice:null,    // {tone, text}
    busy:null,      // {label, since}
    opener:null,inerted:[],
  };
  const docOf=id=>S.docs.get(id)||null;
  /* Le titre `#` d'une note lue l'emporte sur le nom de fichier (lisible, accents compris) ; sinon celui du service. */
  const titleOf=id=>{const d=docOf(id),e=entryOf(id);return (d&&d.heading)||(e&&e.title)||'Sans titre'};
  const entryOf=id=>(S.list.entries.find(e=>e.entry_id===id))||(docOf(id)&&docOf(id).entry)||null;
  const now=()=>Date.now();
  const layout=()=>C.layoutFor(window.innerWidth,{ctxOpen:ctxOpen()});
  function ctxOpen(){return S.ctxOpen===null?C.layoutFor(window.innerWidth).ctxDefaultOpen:S.ctxOpen}
  function running(){return document.documentElement.classList.contains('jvx-run')}
  /* Ce qui empêche le Dossier d'être vu : Variantes (9000) couvre la page. */
  function covered(){
    try{
      const x=root.JarvisStudioExplorer;
      if(running())return 'une présentation est en cours dans Variantes, qui couvre l’écran';
      if(x&&typeof x.isOpen==='function'&&x.isOpen())return 'Variantes est ouvert et couvre l’écran : fermez-le d’abord';
    }catch(error){log('warn','dossier.cover_unreadable',{error:String(error&&error.message||error)})}
    return null;
  }

  /* ------------------------------------------------------------ squelette */
  const el=(tag,cls,txt)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(txt!==undefined&&txt!==null)n.textContent=String(txt);return n};
  const btn=(cls,label,attrs)=>{const b=el('button',cls,label);b.type='button';for(const [k,v] of Object.entries(attrs||{}))if(v!==undefined&&v!==null&&v!==false)b.setAttribute(k,v===true?'':String(v));return b};
  const SVG_NS='http://www.w3.org/2000/svg';
  const ICONS={
    dossier:['M3.8 7.2a1.6 1.6 0 0 1 1.6-1.6h3.9l1.9 2.1h7.4a1.6 1.6 0 0 1 1.6 1.6v8.3a1.6 1.6 0 0 1-1.6 1.6H5.4a1.6 1.6 0 0 1-1.6-1.6z','M3.8 10.4h16.4'],
    note:['M6 3.8h8.4l3.6 3.6V20.2H6z','M14.4 3.8v3.6H18','M8.6 11.2h6.8','M8.6 14.4h6.8','M8.6 17.6h4'],
    image:['M4.2 5.2h15.6v13.6H4.2z','M4.2 15.4l4.4-4.4 3.6 3.6 2.4-2.4 5.2 5.2','M15.4 8.6a1.2 1.2 0 1 1 0 .1z'],
    media:['M4.2 5.2h15.6v13.6H4.2z','M10.2 9.2l4.6 2.8-4.6 2.8z'],
    link:['M10.4 13.6a3.6 3.6 0 0 0 5.1 0l2.6-2.6a3.6 3.6 0 0 0-5.1-5.1l-1 1','M13.6 10.4a3.6 3.6 0 0 0-5.1 0l-2.6 2.6a3.6 3.6 0 0 0 5.1 5.1l1-1'],
    transcript:['M5 6.2h14','M5 10h10','M5 13.8h14','M5 17.6h7'],
    summary:['M12 3.8l2.4 5 5.4.6-4 3.7 1.1 5.3L12 15.7l-4.9 2.7 1.1-5.3-4-3.7 5.4-.6z'],
    folder:['M3.8 7.2a1.6 1.6 0 0 1 1.6-1.6h3.9l1.9 2.1h7.4a1.6 1.6 0 0 1 1.6 1.6v8.3a1.6 1.6 0 0 1-1.6 1.6H5.4a1.6 1.6 0 0 1-1.6-1.6z'],
    home:['M4 11.2l8-6.4 8 6.4','M6.4 9.6v9.6h11.2V9.6'],
    close:['M6.6 6.6l10.8 10.8','M17.4 6.6L6.6 17.4'],
    board:['M4 5h16v11H4z','M9 20h6','M12 16v4'],
    context:['M4 5h16v14H4z','M14.6 5v14'],
    org:['M4 6.4h16','M4 12h16','M4 17.6h16'],
    chevron:['M9.6 6.4l5.4 5.6-5.4 5.6'],
    split:['M4 5h16v14H4z','M12 5v14'],
    search:['M10.6 4.6a6 6 0 1 1 0 12a6 6 0 1 1 0-12z','M15 15l5 5'],
  };
  function icon(name,size){
    const s=document.createElementNS(SVG_NS,'svg');
    s.setAttribute('viewBox','0 0 24 24');s.setAttribute('width',String(size||16));s.setAttribute('height',String(size||16));
    s.setAttribute('fill','none');s.setAttribute('stroke','currentColor');s.setAttribute('stroke-width','1.6');
    s.setAttribute('stroke-linecap','round');s.setAttribute('stroke-linejoin','round');s.setAttribute('aria-hidden','true');
    for(const d of ICONS[name]||ICONS.note){const p=document.createElementNS(SVG_NS,'path');p.setAttribute('d',d);s.appendChild(p)}
    return s;
  }
  const kindIcon=kind=>({memory_summary:'summary',report:'summary',image:'image',media:'media',link:'link',transcript:'transcript'})[kind]||'note';

  installStyle();
  host.textContent='';
  const head=el('header','dsr-head');
  const orgToggle=btn('dsr-btn dsr-org-toggle','',{id:'dsrOrgToggle','aria-controls':'dsrOrg','aria-expanded':'false',title:'Organisation du Dossier'});
  orgToggle.appendChild(icon('org',16));orgToggle.appendChild(el('span','dsr-btn-label','Organisation'));
  const title=el('h2','dsr-title');title.id='dsrTitle';
  const searchBox=el('div','dsr-search');
  const searchIcon=icon('search',15);searchIcon.classList.add('dsr-search-icon');
  const search=el('input','dsr-search-input');search.type='search';search.id='dsrSearch';search.autocomplete='off';
  search.placeholder='Filtrer le Dossier';search.setAttribute('aria-label','Filtrer les entrées du Dossier (Entrée : chercher dans le texte)');
  searchBox.appendChild(searchIcon);searchBox.appendChild(search);
  const ctxToggle=btn('dsr-btn','',{id:'dsrCtxToggle','aria-controls':'dsrCtx','aria-pressed':'false',title:'Afficher ou replier le contexte'});
  ctxToggle.appendChild(icon('context',16));ctxToggle.appendChild(el('span','dsr-btn-label','Contexte'));
  const closeBtn=btn('dsr-close','',{id:'dsrClose','aria-label':'Fermer le Dossier et revenir au Board (Échap)'});
  closeBtn.appendChild(icon('board',16));closeBtn.appendChild(el('span','dsr-btn-label','Retour au Board'));
  const kbd=el('kbd','dsr-kbd','Échap');kbd.setAttribute('aria-hidden','true');closeBtn.appendChild(kbd);
  head.append(orgToggle,title,searchBox,ctxToggle,closeBtn);
  const notice=el('div','dsr-notice');notice.id='dsrNotice';notice.setAttribute('role','status');notice.hidden=true;
  const body=el('div','dsr-body');
  const org=el('nav','dsr-org');org.id='dsrOrg';org.setAttribute('aria-label','Organisation du Dossier');
  const work=el('main','dsr-work');work.id='dsrWork';
  const ctx=el('aside','dsr-ctx');ctx.id='dsrCtx';ctx.setAttribute('aria-label','Contexte du document');
  body.append(org,work,ctx);
  const foot=el('footer','dsr-foot');
  const status=el('span','dsr-status');status.id='dsrStatus';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const hint=el('span','dsr-hint','Demandez aussi à Jarvis : « ouvre le compte rendu dans le Dossier ».');
  foot.append(status,hint);
  const announce=el('div','sr');announce.id='dsrAnnounce';announce.setAttribute('aria-live','polite');
  host.append(head,notice,body,foot,announce);
  host.setAttribute('aria-describedby','dsrHelp');
  const help=el('p','sr','Dossier du Board en plein écran. Échap ferme le menu, le formulaire ou la confirmation ouverte, puis revient au Board. Ctrl+S enregistre une modification.');
  help.id='dsrHelp';host.appendChild(help);

  /* ------------------------------------------------------------ rendu */
  let tick=null;
  function say(text){if(!text)return;if(announce.textContent===text)announce.textContent='';announce.textContent=text}
  function waiting(){
    if(S.busy)return true;
    if(S.list.status==='loading'||S.search.status==='loading')return true;
    for(const d of S.docs.values())if(d.status==='loading'||(d.edit&&d.edit.status==='saving'))return true;
    return !!(S.form&&S.form.status==='busy')||!!(S.confirm&&S.confirm.status==='busy');
  }
  const secs=since=>`${Math.max(0,Math.floor((now()-since)/1000))} s`;
  function renderStatus(){
    let line='';
    if(S.busy)line=`${S.busy.label}… ${secs(S.busy.since)}`;
    else if(S.list.status==='loading')line=`Lecture du Dossier… ${secs(S.list.since)}`;
    else if(S.list.status==='error')line=`${S.list.error.title} — ${S.list.error.hint}`;
    else if(S.list.status==='ok'){
      const n=S.list.entries.length;
      line=`${n} entrée${n>1?'s':''}${S.list.truncated?` sur ${S.list.total} (les plus récentes)`:''} · lu ${C.relativeTime(new Date(S.list.at).toISOString(),now())}`;
    }
    status.textContent=line;
    for(const node of host.querySelectorAll('[data-since]'))node.textContent=secs(Number(node.dataset.since));
  }
  function armTick(){
    if(tick||!S.open)return;
    tick=setInterval(()=>{renderStatus();if(!waiting()&&!(S.list.status==='ok')){clearInterval(tick);tick=null}},TICK_MS);
  }
  function renderHead(){
    title.textContent='';
    const word=el('span','dsr-word','Dossier');
    title.appendChild(icon('dossier',18));title.appendChild(word);
    if(S.board){
      const kind=el('span','dsr-kind',C.BOARD_KINDS[S.board.board_kind]||S.board.board_kind||'Board');
      kind.dataset.kind=S.board.board_kind||'';
      const name=el('span','dsr-board',S.board.title||'Sans titre');name.title=S.board.title||'';
      title.append(kind,name);
      if(S.board.status==='archived')title.appendChild(el('span','dsr-chip','Archivé · lecture seule'));
    }else title.appendChild(el('span','dsr-board dsr-muted',S.list.status==='error'?'indisponible':'chargement…'));
    const l=layout();
    host.dataset.narrow=l.narrow?'1':'0';
    host.dataset.ctx=ctxOpen()?'open':'closed';
    host.dataset.ctxDrawer=l.ctxDrawer?'1':'0';
    host.dataset.org=S.orgOpen?'open':'closed';
    orgToggle.setAttribute('aria-expanded',S.orgOpen?'true':'false');
    ctxToggle.setAttribute('aria-pressed',ctxOpen()?'true':'false');
    if(search.value!==S.filter)search.value=S.filter;
  }
  function renderNotice(){
    let n=S.notice;
    if(S.coreLost)n={tone:'warn',text:'Core ne répond pas : ce qui est affiché peut être ancien, et rien ne s’écrit tant que l’état n’est pas relu.'};
    else if(S.board&&S.board.status==='archived'&&!n)n={tone:'info',text:'Ce Board est archivé : son Dossier se lit ; aucune écriture, aucun affichage sur le Board.'};
    else if(S.board&&S.displayed&&S.board.board_id!==S.displayed&&!n)n={tone:'info',text:'Ce Dossier n’est pas celui du Board affiché : il se lit, sans Afficher sur le Board.'};
    notice.hidden=!n;
    notice.dataset.tone=n?n.tone:'';
    notice.textContent=n?n.text:'';
  }

  function renderOrg(){
    org.textContent='';
    const list=S.list.entries;
    const o=C.organize(list);
    const item=(section,label,count,iconName,depth,extra)=>{
      const b=btn('dsr-nav','',{'data-section':section,'data-fk':`nav:${section}`,'aria-current':S.section===section&&S.active==='browse'?'page':null});
      if(depth)b.style.paddingLeft=`${12+depth*14}px`;
      if(extra)b.appendChild(extra);
      b.appendChild(icon(iconName,15));
      b.appendChild(el('span','dsr-nav-label',label));
      if(count!==null)b.appendChild(el('span','dsr-count',count));
      return b;
    };
    org.appendChild(item('home','Vue d’ensemble',o.total,'home',0));
    if(o.collections.length){
      org.appendChild(el('h3','dsr-org-h','Collections'));
      for(const c of o.collections)org.appendChild(item(`c:${c.id}`,c.label,c.ids.length,c.id==='media'?'image':c.id==='links'?'link':c.id==='transcripts'?'transcript':c.id==='syntheses'?'summary':'note',0));
    }
    if(o.folders.length){
      org.appendChild(el('h3','dsr-org-h','Dossiers'));
      const walk=(folders,depth)=>{
        for(const f of folders){
          const twisty=f.folders.length?btn('dsr-twisty','',{'data-twisty':f.path,'aria-label':`${S.collapsed.has(f.path)?'Déplier':'Replier'} ${f.name}`,'aria-expanded':S.collapsed.has(f.path)?'false':'true','data-fk':`tw:${f.path}`}):el('span','dsr-twisty-gap');
          if(f.folders.length)twisty.appendChild(icon('chevron',12));
          const row=el('div','dsr-folder');row.append(twisty,item(`f:${f.path}`,f.name,f.count,'folder',depth));
          org.appendChild(row);
          if(f.folders.length&&!S.collapsed.has(f.path))walk(f.folders,depth+1);
        }
      };
      walk(o.folders,0);
    }
    if(S.list.status==='loading'&&!list.length)org.appendChild(el('p','dsr-quiet','Lecture…'));
  }

  function renderTabs(){
    const bar=el('div','dsr-tabs');bar.setAttribute('role','tablist');bar.setAttribute('aria-label','Documents ouverts');
    const tab=(id,label,iconName,closable,jarvis)=>{
      const wrap=el('div','dsr-tab');
      const shown=S.active===id||(S.split&&layout().split&&S.split.includes(id));
      wrap.dataset.selected=S.active===id?'1':shown?'2':'0';
      const b=btn('dsr-tab-btn','',{role:'tab','aria-selected':S.active===id?'true':'false','data-tab':id,'data-fk':`tab:${id}`,
        tabindex:S.active===id?'0':'-1',title:label});
      b.appendChild(icon(iconName,14));b.appendChild(el('span','dsr-tab-label',label));
      if(jarvis){const j=el('span','dsr-by','Jarvis');j.title='Ouvert à la demande de Jarvis';b.appendChild(j)}
      wrap.appendChild(b);
      if(closable){const x=btn('dsr-tab-x','',{'data-close':id,'aria-label':`Fermer ${label}`,'data-fk':`x:${id}`});x.appendChild(icon('close',12));wrap.appendChild(x)}
      return wrap;
    };
    const sectionLabel=sectionName(S.section);
    bar.appendChild(tab('browse',sectionLabel,'dossier',false,false));
    for(const t of S.tabs){const e=entryOf(t.entryId);bar.appendChild(tab(t.entryId,titleOf(t.entryId),kindIcon(e&&e.kind),true,t.opener==='jarvis'))}
    return bar;
  }
  function sectionName(section){
    if(!section||section==='home')return 'Vue d’ensemble';
    if(section.startsWith('c:')){const c=C.COLLECTIONS.find(x=>x.id===section.slice(2));return c?c.label:'Collection'}
    if(section.startsWith('f:'))return section.slice(2).split('/').pop();
    return 'Parcourir';
  }

  function renderWork(){
    work.textContent='';
    work.appendChild(renderTabs());
    const panes=el('div','dsr-panes');
    const l=layout();
    const pair=S.split&&l.split&&S.split.every(id=>S.tabs.some(t=>t.entryId===id))?S.split:null;
    panes.dataset.split=pair?'2':'1';
    if(S.active==='browse'&&!pair)panes.appendChild(renderBrowse());
    else if(pair)for(const id of pair)panes.appendChild(renderDoc(id,true));
    else panes.appendChild(renderDoc(S.active,false));
    work.appendChild(panes);
  }

  /* Une entrée = une tuile (retour utilisateur du 2026-10-29 : « des grandes icônes, un grid d'images ») : une image se voit
     en grande vignette, son titre seulement au survol ; un document a une grande icône et son titre. Nature, dossier, date
     et taille passent dans l'infobulle et le nom accessible. Une vignette qui ne se charge pas redevient une icône. */
  function entryTile(e){
    const title=titleOf(e.entry_id),url=C.imageUrlOf(e,S.boardId);
    const research=C.researchLine(e);
    const meta=[research?'Recherche':C.KIND_LABELS[e.kind]||e.kind];
    if(research)meta.push(research);else if(e.folder)meta.push(e.folder);
    const when=C.relativeTime(e.modified_at,now());if(when)meta.push(when);
    if(e.size!=null&&e.source==='memory')meta.push(C.formatBytes(e.size));
    const b=btn('dsr-tile','',{'data-open':e.entry_id,'data-fk':`row:${e.entry_id}`,title:`${title}\n${meta.join(' · ')}`,
      'aria-label':`${title}, ${meta.join(', ')}`});
    const face=el('span','dsr-tile-face');face.dataset.kind=e.kind;
    const name=el('span','dsr-row-title',title);
    const iconFace=()=>{face.textContent='';face.appendChild(icon(kindIcon(e.kind),52));delete b.dataset.image;b.append(name)};
    if(url){
      b.dataset.image='1';
      const img=el('img');img.alt='';img.loading='lazy';img.decoding='async';img.draggable=false;
      img.addEventListener('error',()=>{log('warn','dossier.thumb_failed',{entry:short(e.entry_id)});iconFace()},{once:true});
      img.src=url;face.append(img,name);b.appendChild(face);
    }else{b.appendChild(face);iconFace()}
    return b;
  }
  function renderBrowse(){
    const pane=el('section','dsr-browse');pane.setAttribute('role','tabpanel');pane.setAttribute('aria-label',sectionName(S.section));
    const l=S.list;
    if(l.status==='loading'&&!l.entries.length){
      const w=el('p','dsr-wait');w.append('Lecture du Dossier… ');const c=el('span','dsr-clock');c.dataset.since=String(l.since);c.textContent=secs(l.since);w.appendChild(c);
      pane.appendChild(w);return pane;
    }
    if(l.status==='error'&&!l.entries.length){pane.appendChild(errorBox(l.error,'reload'));return pane}
    const filtered=C.filterEntries(C.entriesOfSection(l.entries,S.section),S.filter);
    if(S.section==='home'&&!S.filter){
      pane.appendChild(el('h3','dsr-h','Vue d’ensemble'));
      const summary=l.entries.find(e=>e.kind==='memory_summary');
      const lead=el('div','dsr-lead');
      if(summary){
        const d=docOf(summary.entry_id);
        lead.appendChild(el('h4','dsr-h4','Résumé du Board'));
        if(d&&d.status==='ok'){if(d.heading)lead.appendChild(el('p','dsr-lead-title',d.heading));const r=el('div','dsr-prose dsr-excerpt');renderBlocks(r,d.blocks.filter(b=>!b.fm).slice(0,6));lead.appendChild(r)}
        else if(!d||d.status==='loading')lead.appendChild(el('p','dsr-quiet','Lecture du résumé…'));
        else lead.appendChild(el('p','dsr-quiet',d.error?`${d.error.title}.`:''));
        lead.appendChild(btn('dsr-link','Lire le résumé complet',{'data-open':summary.entry_id}));
        ensureDoc(summary);
      }else lead.appendChild(el('p','dsr-quiet','Pas encore de résumé du Board (summary.md). Jarvis l’écrit quand le travail avance ; vous pouvez aussi le lui demander.'));
      pane.appendChild(lead);
      if(!l.entries.length){
        pane.appendChild(el('p','dsr-empty','Ce Dossier est vide. Rangez un objet du Board (roue › Sélection › Ranger dans le Dossier), ou demandez à Jarvis d’y écrire une note.'));
        return pane;
      }
      pane.appendChild(el('h4','dsr-h4','Modifié récemment'));
    }else{
      const h=el('h3','dsr-h',S.filter?`« ${S.filter} »`:sectionName(S.section));
      h.appendChild(el('span','dsr-count',filtered.length));pane.appendChild(h);
    }
    const shown=S.section==='home'&&!S.filter?l.entries.slice(0,10):filtered;
    /* Les images d'abord, en grille de vignettes ; les documents ensuite, en grille d'icônes. Un titre de groupe seulement
       quand les deux sont là. */
    const images=shown.filter(e=>C.imageUrlOf(e,S.boardId)),others=shown.filter(e=>!C.imageUrlOf(e,S.boardId));
    const grid=(list,label)=>{
      const g=el('div','dsr-grid');g.setAttribute('role','list');if(label)g.setAttribute('aria-label',label);
      for(const e of list){const li=el('div','dsr-li');li.setAttribute('role','listitem');li.appendChild(entryTile(e));g.appendChild(li)}
      return g;
    };
    const both=images.length&&others.length;
    if(images.length){if(both)pane.appendChild(el('h4','dsr-h4','Images'));pane.appendChild(grid(images,'Images'))}
    if(others.length){if(both)pane.appendChild(el('h4','dsr-h4','Documents'));pane.appendChild(grid(others,'Documents'))}
    if(!shown.length)pane.appendChild(el('p','dsr-quiet',S.filter?'Aucun titre ne correspond. Entrée : chercher ces mots dans le texte des notes.':'Rien dans cette collection.'));
    if(S.filter)pane.appendChild(renderSearch());
    if(l.truncated)pane.appendChild(el('p','dsr-quiet',`Le Dossier compte ${l.total} entrées ; les ${l.entries.length} plus récentes sont listées. Filtrez, ou cherchez dans le texte.`));
    return pane;
  }
  function renderSearch(){
    const box=el('div','dsr-searchres');
    const s=S.search;
    if(s.q!==S.filter||s.status==='idle'){
      box.appendChild(btn('dsr-link',`Chercher « ${S.filter} » dans le texte des notes`,{'data-act':'search','data-fk':'search-go'}));
      return box;
    }
    if(s.status==='loading'){const w=el('p','dsr-wait','Recherche dans la mémoire du Board… ');const c=el('span','dsr-clock');c.dataset.since=String(s.since);w.appendChild(c);box.appendChild(w);return box}
    if(s.status==='error'){box.appendChild(errorBox(s.error,'search'));return box}
    box.appendChild(el('h4','dsr-h4',`Dans le texte : ${s.matches.length} passage${s.matches.length>1?'s':''}`));
    for(const m of s.matches){
      const b=btn('dsr-row','',{'data-open':`memory:${m.path}`});
      const main=el('span','dsr-row-main');
      main.appendChild(el('span','dsr-row-title',m.path));
      main.appendChild(el('span','dsr-row-preview',m.snippet||m.text||''));
      b.appendChild(main);box.appendChild(b);
    }
    return box;
  }
  function errorBox(error,retry){
    const box=el('div','dsr-error');box.setAttribute('role','alert');
    box.appendChild(el('strong','',error.title));
    box.appendChild(el('p','',`${error.hint}${error.code?` (${error.code}${error.status?`, HTTP ${error.status}`:''})`:''}`));
    if(retry)box.appendChild(btn('dsr-btn','Réessayer',{'data-act':retry,'data-fk':`retry:${retry}`}));
    return box;
  }

  /* --- Markdown -> DOM (textContent seulement : jamais de HTML d'auteur) */
  function renderInline(parent,tokens){
    for(const t of tokens){
      if(t.t==='text')parent.appendChild(document.createTextNode(t.v));
      else if(t.t==='strong')parent.appendChild(el('strong','',t.v));
      else if(t.t==='em')parent.appendChild(el('em','',t.v));
      else if(t.t==='code')parent.appendChild(el('code','',t.v));
      else if(t.t==='link'){const a=el('a','',t.v);a.href=t.href;a.target='_blank';a.rel='noopener noreferrer';a.title=`${t.href} — s’ouvre dans un onglet ; Jarvis ne l’a pas visité`;parent.appendChild(a)}
    }
  }
  function renderBlocks(parent,blocks){
    for(const b of blocks){
      if(b.t==='h'){const h=el(`h${Math.min(6,b.level+1)}`,'dsr-mh');renderInline(h,b.inline);parent.appendChild(h)}
      else if(b.t==='p'){const p=el('p');renderInline(p,b.inline);parent.appendChild(p)}
      else if(b.t==='ul'||b.t==='ol'){const list=el(b.t);for(const it of b.items){const li=el('li');renderInline(li,it);list.appendChild(li)}parent.appendChild(list)}
      else if(b.t==='quote'){const q=el('blockquote');renderInline(q,b.inline);parent.appendChild(q)}
      else if(b.t==='code'){const pre=el('pre',b.fm?'dsr-research-head':'');pre.appendChild(el('code','',b.v));parent.appendChild(pre)}
      else if(b.t==='hr')parent.appendChild(el('hr'));
    }
  }

  function renderDoc(entryId,paired){
    const e=entryOf(entryId);
    const d=docOf(entryId);
    const art=el('article','dsr-doc');art.dataset.entry=entryId;art.setAttribute('role','tabpanel');
    if(!e){art.appendChild(errorBox(C.errorOf('dossier_entry_not_found',404,''),null));return art}
    art.setAttribute('aria-label',titleOf(e.entry_id));
    const caps=C.capabilities(e,{board:S.board,displayedBoardId:S.displayed,running:running(),coreLost:S.coreLost});
    const dh=el('header','dsr-doc-head');
    const h=el('h3','dsr-doc-title',titleOf(entryId));h.tabIndex=-1;h.dataset.fk=`title:${entryId}`;h.setAttribute('dir','auto');
    dh.appendChild(h);
    const meta=[C.researchLine(e)?'Recherche':C.KIND_LABELS[e.kind]||e.kind];
    if(C.researchLine(e))meta.push(C.researchLine(e));
    const when=C.relativeTime(e.modified_at,now());if(when)meta.push(`modifié ${when}`);
    meta.push(e.source==='memory'?'mémoire du Board':'registre');
    const m=el('p','dsr-doc-meta',meta.join(' · '));
    const tab=S.tabs.find(t=>t.entryId===entryId);
    if(tab&&tab.opener==='jarvis'){const j=el('span','dsr-by','Ouvert par Jarvis');m.appendChild(document.createTextNode(' '));m.appendChild(j)}
    dh.appendChild(m);
    const bar=el('div','dsr-actions');bar.setAttribute('role','toolbar');bar.setAttribute('aria-label',`Actions sur ${titleOf(e.entry_id)}`);
    const action=(act,label,cap,extra)=>{
      const b=btn('dsr-btn',label,{'data-act':act,'data-entry':entryId,'data-fk':`${act}:${entryId}`,'aria-disabled':cap&&!cap.ok?'true':null,
        title:cap&&!cap.ok?cap.reason:null,...(extra||{})});
      return b;
    };
    const editing=d&&d.edit;
    if(!editing){
      bar.appendChild(action('present-menu','Afficher sur le Board',caps.present,{'aria-haspopup':'menu','aria-expanded':S.menu&&S.menu.kind==='present'&&S.menu.entryId===entryId?'true':'false'}));
      if(e.source==='memory')bar.appendChild(action('edit','Modifier',caps.edit));
      if(e.source==='memory')bar.appendChild(action('more-menu','Plus…',null,{'aria-haspopup':'menu','aria-expanded':S.menu&&S.menu.kind==='more'&&S.menu.entryId===entryId?'true':'false','aria-label':`Plus d’actions sur ${titleOf(e.entry_id)}`}));
      const others=S.tabs.filter(t=>t.entryId!==entryId);
      if(paired)bar.appendChild(action('unsplit','Lire seul',null));
      else if(others.length&&layout().split)bar.appendChild(action('compare-menu','Comparer…',null,{'aria-haspopup':'menu'}));
    }
    dh.appendChild(bar);
    if(S.menu&&S.menu.entryId===entryId)dh.appendChild(renderMenu(e));
    const reason=[caps.present,caps.edit].find(c=>!c.ok&&c.reason);
    if(!editing&&reason&&S.board&&(S.board.status==='archived'||S.coreLost))dh.appendChild(el('p','dsr-why',reason.reason));
    if(S.form&&S.form.entryId===entryId)dh.appendChild(renderMoveForm(e));
    if(S.confirm&&S.confirm.entryId===entryId)dh.appendChild(renderDeleteConfirm(e));
    /* Pendant une modification ou un conflit, un ancien message (« Déjà sur le Board… ») ne reste pas affiché
       (Slice 08, QA S07 4) : l'éditeur dit son propre état. */
    if(d&&d.flash&&!editing)dh.appendChild(el('p',`dsr-flash dsr-${d.flash.tone}`,d.flash.text));
    art.appendChild(dh);
    const bodyEl=el('div','dsr-doc-body');
    if(editing)bodyEl.appendChild(renderEditor(e,d));
    else bodyEl.appendChild(renderContent(e,d));
    art.appendChild(bodyEl);
    return art;
  }
  function renderMenu(e){
    const menu=el('div','dsr-menu');menu.setAttribute('role','menu');menu.id='dsrMenu';
    const k=S.menu.kind;
    const item=(act,label,note,extra)=>{const b=btn('dsr-menu-item','',{role:'menuitem','data-act':act,'data-entry':e.entry_id,'data-fk':`menu:${act}:${extra||''}`,'data-value':extra||null});
      b.appendChild(el('span','dsr-menu-label',label));if(note)b.appendChild(el('span','dsr-menu-note',note));return b};
    if(k==='present'){
      const caps=C.capabilities(e,{board:S.board,displayedBoardId:S.displayed,running:running(),coreLost:S.coreLost});
      if(!caps.present.ok){menu.appendChild(el('p','dsr-menu-why',caps.present.reason));return menu}
      menu.setAttribute('aria-label','Afficher sur le Board, sous la forme');
      for(const [rep,label,note] of C.REPRESENTATIONS)menu.appendChild(item('present',label,note,rep));
    }else if(k==='more'){
      menu.setAttribute('aria-label','Plus d’actions');
      const caps=C.capabilities(e,{board:S.board,displayedBoardId:S.displayed,running:running(),coreLost:S.coreLost});
      const a=item('move-form','Renommer ou déplacer…',caps.move.ok?'dans la mémoire du Board':caps.move.reason);if(!caps.move.ok)a.setAttribute('aria-disabled','true');menu.appendChild(a);
      const b=item('delete-ask','Supprimer du Dossier…',caps.delete.ok?'définitif, demande confirmation':caps.delete.reason);b.classList.add('dsr-danger');if(!caps.delete.ok)b.setAttribute('aria-disabled','true');menu.appendChild(b);
    }else if(k==='compare'){
      menu.setAttribute('aria-label','Comparer avec');
      for(const t of S.tabs)if(t.entryId!==e.entry_id){const o=entryOf(t.entryId);menu.appendChild(item('compare',o?o.title:t.entryId,'côte à côte',t.entryId))}
    }
    return menu;
  }
  function renderMoveForm(e){
    const f=S.form;
    const form=el('form','dsr-form');form.dataset.form='move';
    const id=`dsrMoveTo`;
    const lab=el('label','dsr-form-label','Nouveau chemin dans la mémoire du Board');lab.htmlFor=id;
    const input=el('input','dsr-input');input.id=id;input.name='to';input.value=f.value;input.dataset.fk='move-input';input.autocomplete='off';input.spellcheck=false;
    const row=el('div','dsr-form-row');
    const go=btn('dsr-btn dsr-primary',f.status==='busy'?'Déplacement…':'Renommer',{'data-act':'move','data-entry':e.entry_id,'aria-disabled':f.status==='busy'?'true':null});go.type='submit';
    row.append(go,btn('dsr-btn','Annuler',{'data-act':'form-cancel'}));
    form.append(lab,input,row);
    if(f.status==='busy'){const w=el('p','dsr-wait','Déplacement en cours… ');const c=el('span','dsr-clock');c.dataset.since=String(f.since);w.appendChild(c);form.appendChild(w)}
    if(f.error)form.appendChild(errorBox(f.error,null));
    return form;
  }
  function renderDeleteConfirm(e){
    const c=S.confirm;
    const box=el('div','dsr-confirm');box.setAttribute('role','alertdialog');box.setAttribute('aria-labelledby','dsrDelTitle');
    const t=el('strong','',`Supprimer « ${titleOf(e.entry_id)} » du Dossier ?`);t.id='dsrDelTitle';box.appendChild(t);
    box.appendChild(el('p','',`Le fichier ${e.path} est retiré définitivement de la mémoire du Board. Ni Masquer ni Retirer du Board ne font cela : c’est la seule suppression durable.`));
    const row=el('div','dsr-form-row');
    row.append(btn('dsr-btn','Annuler',{'data-act':'delete-cancel','data-fk':'delete-cancel'}),
      btn('dsr-btn dsr-danger-btn',c.status==='busy'?'Suppression…':'Supprimer définitivement',{'data-act':'delete','data-entry':e.entry_id,'aria-disabled':c.status==='busy'?'true':null}));
    box.appendChild(row);
    if(c.error)box.appendChild(errorBox(c.error,null));
    return box;
  }
  function renderContent(e,d){
    const box=el('div','dsr-content');
    if(!d||!d.status||d.status==='idle'||d.status==='loading'){
      const w=el('p','dsr-wait','Lecture… ');const c=el('span','dsr-clock');c.dataset.since=String(d&&d.since||now());w.appendChild(c);box.appendChild(w);
      return box;
    }
    if(d.status==='error'){box.appendChild(errorBox(d.error,`reload-doc:${e.entry_id}`));return box}
    if(d.mode==='image'){
      const fig=el('figure','dsr-figure');fig.dataset.zoom=d.zoom?'1':'0';
      const img=el('img');img.alt=e.title||'Image';img.src=d.imageUrl||C.PATHS.payload(d.artifactId);img.decoding='async';
      img.addEventListener('error',()=>{d.status='error';d.error=C.errorOf('artifact_payload_unreadable',0,'image illisible');log('warn','dossier.image_failed',{entry:short(e.entry_id)});render()},{once:true});
      fig.appendChild(img);
      const z=btn('dsr-btn dsr-zoom',d.zoom?'Ajuster à la fenêtre':'Taille réelle',{'data-act':'zoom','data-entry':e.entry_id});
      fig.appendChild(z);
      box.appendChild(fig);
      return box;
    }
    if(d.mode==='media'){
      const mime=String(d.mime||'');
      const media=el(mime.startsWith('video/')?'video':'audio');media.controls=true;media.preload='metadata';media.src=C.PATHS.payload(d.artifactId);
      media.setAttribute('aria-label',e.title||'Média');
      box.appendChild(media);return box;
    }
    if(d.mode==='pdf'){
      box.appendChild(el('p','dsr-quiet','Ce PDF ne s’affiche pas dans la page.'));
      const a=el('a','dsr-btn','Ouvrir le PDF dans un onglet');a.href=C.PATHS.payload(d.artifactId);a.target='_blank';a.rel='noopener';box.appendChild(a);return box;
    }
    if(d.mode==='link'){
      box.appendChild(el('p','dsr-quiet','Lien déposé sur le Board ; Jarvis ne l’a pas visité.'));
      /* Seul un lien http(s) devient cliquable ; un autre schéma s'affiche en texte (Slice 08, QA S07 3). */
      const href=C.safeLinkUrl(d.url);
      if(!href){box.appendChild(el('p','dsr-url',d.url));box.appendChild(el('p','dsr-quiet','Adresse non http(s) : elle n’est pas ouverte d’ici.'));
        log('warn','dossier.link_refused',{scheme:String(d.url||'').split(':')[0].slice(0,16)});return box}
      const a=el('a','dsr-url',d.url);a.href=href;a.target='_blank';a.rel='noopener noreferrer';box.appendChild(a);return box;
    }
    if(d.mode==='none'){
      box.appendChild(el('p','dsr-quiet',`Ce fichier n’est pas du texte (${C.formatBytes(e.size)||'taille inconnue'}) : il est listé dans le Dossier, il ne se lit pas ici.`));return box;
    }
    const prose=el('div','dsr-prose');prose.setAttribute('dir','auto');
    renderBlocks(prose,d.blocks);
    box.appendChild(prose);
    if(d.truncated)box.appendChild(el('p','dsr-quiet',d.truncated));
    if(!d.eof&&d.mode==='text'&&d.source==='memory')box.appendChild(btn('dsr-btn','Lire la suite',{'data-act':'more-text','data-entry':e.entry_id,'data-fk':`more:${e.entry_id}`}));
    return box;
  }
  function renderEditor(e,d){
    const ed=d.edit;
    const box=el('div','dsr-editor');
    const id=`dsrEdit-${C.PATHS.payload(e.entry_id).length}-${S.tabs.findIndex(t=>t.entryId===e.entry_id)}`;
    const lab=el('label','sr',`Texte de ${titleOf(e.entry_id)}`);lab.htmlFor=id;box.appendChild(lab);
    if(ed.conflict){
      const c=el('div','dsr-conflict');c.setAttribute('role','alert');
      c.appendChild(el('strong','','Le fichier a changé depuis votre lecture : rien n’a été écrit.'));
      c.appendChild(el('p','','Votre texte est gardé ci-dessous. La version actuelle sur le disque est montrée à côté ; enregistrez de nouveau pour la remplacer par la vôtre, en connaissance de cause.'));
      box.appendChild(c);
    }
    if(ed.unknown){const u=el('div','dsr-conflict');u.setAttribute('role','alert');u.appendChild(el('strong','','Issue inconnue : la réponse n’est pas arrivée.'));
      u.appendChild(el('p','','Le fichier a peut-être été écrit. Relisez avant de recommencer ; votre texte reste ici.'));
      u.appendChild(btn('dsr-btn','Relire la version actuelle',{'data-act':'reread','data-entry':e.entry_id}));box.appendChild(u)}
    if(ed.error)box.appendChild(errorBox(ed.error,null));
    const panes=el('div','dsr-edit-panes');panes.dataset.split=ed.theirs!==null&&ed.theirs!==undefined?'2':'1';
    const ta=el('textarea','dsr-textarea');ta.id=id;ta.value=ed.draft;ta.dataset.fk=`edit:${e.entry_id}`;ta.dataset.entry=e.entry_id;ta.spellcheck=true;
    if(ed.status==='saving')ta.readOnly=true;
    panes.appendChild(ta);
    if(ed.theirs!==null&&ed.theirs!==undefined){
      const theirs=el('div','dsr-theirs');theirs.appendChild(el('h4','dsr-h4','Version actuelle sur le disque'));
      const pr=el('div','dsr-prose');renderBlocks(pr,C.markdownBlocks(ed.theirs).blocks);theirs.appendChild(pr);panes.appendChild(theirs);
    }
    box.appendChild(panes);
    const row=el('div','dsr-form-row');
    const save=btn('dsr-btn dsr-primary',ed.status==='saving'?'Enregistrement…':ed.conflict?'Enregistrer par-dessus la version actuelle':'Enregistrer',{'data-act':'save','data-entry':e.entry_id,'aria-disabled':ed.status==='saving'?'true':null,'data-fk':`save:${e.entry_id}`});
    row.append(save,btn('dsr-btn','Annuler',{'data-act':'edit-cancel','data-entry':e.entry_id,'data-fk':`edit-cancel:${e.entry_id}`}));
    if(ed.status==='saving'){const c=el('span','dsr-clock');c.dataset.since=String(ed.since);row.appendChild(c)}
    row.appendChild(el('span','dsr-quiet','Ctrl+S'));
    box.appendChild(row);
    if(ed.askDiscard){
      const q=el('div','dsr-confirm');q.setAttribute('role','alertdialog');q.setAttribute('aria-label','Abandonner vos modifications ?');
      q.appendChild(el('strong','','Abandonner vos modifications ?'));
      const r=el('div','dsr-form-row');
      r.append(btn('dsr-btn','Continuer à modifier',{'data-act':'discard-no','data-entry':e.entry_id,'data-fk':'discard-no'}),btn('dsr-btn dsr-danger-btn','Abandonner',{'data-act':'discard-yes','data-entry':e.entry_id}));
      q.appendChild(r);box.appendChild(q);
    }
    return box;
  }

  function renderCtx(){
    ctx.textContent='';
    const open=ctxOpen();
    ctx.hidden=!open;
    if(!open)return;
    const headRow=el('div','dsr-ctx-head');headRow.appendChild(el('h3','dsr-org-h','Contexte'));
    const x=btn('dsr-tab-x','',{'data-act':'ctx-close','aria-label':'Replier le contexte'});x.appendChild(icon('close',12));headRow.appendChild(x);
    ctx.appendChild(headRow);
    const id=S.active!=='browse'?S.active:null;
    const e=id&&entryOf(id);
    if(!e){
      ctx.appendChild(el('p','dsr-quiet','Ouvrez un document pour voir sa source, sa date et sa provenance.'));
      if(S.list.sources&&S.list.sources.memory&&S.list.sources.memory.error)
        ctx.appendChild(errorBox(C.errorOf(S.list.sources.memory.error,0,S.list.sources.memory.message),'reload'));
      return;
    }
    const d=docOf(id);
    const summary=e.preview||(d&&d.blocks?firstParagraph(d.blocks):'');
    if(summary){ctx.appendChild(el('h4','dsr-h4','En bref'));ctx.appendChild(el('p','dsr-ctx-summary',summary))}
    const dl=el('dl','dsr-facts');
    const add=(k,v,t)=>{if(!v)return;dl.appendChild(el('dt','',k));const dd=el('dd','',v);if(t)dd.title=t;dl.appendChild(dd)};
    add('Nature',C.researchLine(e)?'Document de recherche':C.KIND_LABELS[e.kind]||e.kind);
    add('Recherche',C.researchLine(e));
    add('Source',C.sourceLine(e));
    add('Modifié',C.absoluteTime(e.modified_at));
    if(e.source==='memory')add('Taille',C.formatBytes(e.size));
    if(e.source==='artifact'){add('Ajouté',C.absoluteTime(e.added_at));add('Provenance',e.provenance)}
    ctx.appendChild(dl);
    ctx.appendChild(el('p','dsr-quiet','Jarvis peut lire ce document à la demande. L’interface ne sait pas s’il l’a lu pendant ce tour : elle ne le prétend pas.'));
    const det=el('details','dsr-adv');det.open=S.advanced;
    const sum=el('summary','','Détails techniques');sum.dataset.fk='adv';det.appendChild(sum);
    if(S.advanced){
      const a=S.adv.get(id);
      const dl2=el('dl','dsr-facts dsr-mono');
      const add2=(k,v)=>{if(v===null||v===undefined||v==='')return;dl2.appendChild(el('dt','',k));dl2.appendChild(el('dd','',String(v)))};
      add2('entry_id',e.entry_id);
      if(!a||a.status==='loading')det.appendChild(el('p','dsr-quiet','Lecture des détails…'));
      else if(a.status==='error')det.appendChild(errorBox(a.error,null));
      else for(const [k,v] of Object.entries(a.advanced||{}))add2(k,v);
      if(d&&d.meta&&d.meta.length)for(const m of d.meta)add2('Ranger',m);
      det.appendChild(dl2);
    }
    ctx.appendChild(det);
  }
  const firstParagraph=blocks=>{const p=blocks.find(b=>b.t==='p');return p?p.inline.map(t=>t.v).join('').slice(0,320):''};

  function render(){
    if(!S.open)return;
    markDirty();
    const active=document.activeElement;
    const fk=active&&host.contains(active)?active.dataset&&active.dataset.fk:null;
    const sel=active&&active.tagName==='TEXTAREA'?[active.selectionStart,active.selectionEnd,active.scrollTop]:null;
    renderHead();renderNotice();renderOrg();renderWork();renderCtx();renderStatus();
    if(fk){
      const back=host.querySelector(`[data-fk="${CSS.escape(fk)}"]`);
      if(back&&back!==document.activeElement){back.focus({preventScroll:true});if(sel&&back.tagName==='TEXTAREA'){back.selectionStart=sel[0];back.selectionEnd=sel[1];back.scrollTop=sel[2]}}
    }else if(!host.contains(document.activeElement)){
      const t=host.querySelector('[role="tab"][aria-selected="true"]');if(t)t.focus({preventScroll:true});
    }
    if(S.menu){const first=host.querySelector('#dsrMenu [role="menuitem"]:not([aria-disabled])');if(first&&!host.querySelector('#dsrMenu').contains(document.activeElement))first.focus({preventScroll:true})}
    armTick();
  }

  /* ------------------------------------------------------------ lectures */
  /* Une réponse arrivée après un changement de Board du Dossier (`S.gen`) ne touche plus rien : elle visait l'ancien
     Board (Slice 08, QA S07 2 — `openById`, `loadAdvanced`, `move`, `remove`, `present`, `save`, `reread`). */
  function stale(gen,what){
    if(gen===S.gen)return false;
    log('info','dossier.stale_answer_dropped',{what});
    return true;
  }
  async function loadList(){
    const gen=S.gen,board=S.boardId;
    if(!board)return;
    S.list={...S.list,status:'loading',since:now(),error:null};
    render();
    const answer=await client.get(C.PATHS.list(board,false));
    if(gen!==S.gen||board!==S.boardId){log('info','dossier.stale_list_dropped',{board});return}
    if(!answer.ok){
      S.list={...S.list,status:'error',error:answer.error};
      if(answer.error.code==='board_not_found')S.board=null;
      log('warn','dossier.list_failed',{board,code:answer.error.code,status:answer.status});
      render();return;
    }
    const b=answer.body;
    S.board=b.board||null;
    S.list={status:'ok',entries:Array.isArray(b.entries)?b.entries:[],total:b.total||0,truncated:!!b.truncated,sources:b.sources||null,error:null,since:0,at:now()};
    log('info','dossier.list_read',{board,count:S.list.entries.length,total:S.list.total,ms:answer.ms});
    render();
  }
  function setDoc(id,patch){const d=docOf(id)||{};S.docs.set(id,Object.assign(d,patch));return S.docs.get(id)}
  function ensureDoc(entry,force){
    const d=docOf(entry.entry_id);
    if(d&&d.status&&!force&&d.status!=='error')return;
    loadDoc(entry).catch(error=>{log('error','dossier.doc_failed',{error:String(error&&error.message||error)})});
  }
  async function loadDoc(entry){
    const gen=S.gen,board=S.boardId,id=entry.entry_id;
    setDoc(id,{entry,status:'loading',since:now(),error:null,source:entry.source,flash:null});
    if(S.open)render();
    let patch;
    if(entry.source==='memory'){
      const imageUrl=C.imageUrlOf(entry,board);
      if(imageUrl)patch={status:'ok',mode:'image',imageUrl};
      else if(entry.open!=='text')patch={status:'ok',mode:'none',blocks:[]};
      else{
        const answer=await client.get(C.PATHS.read(board,entry.path,0));
        if(gen!==S.gen)return;
        if(!answer.ok)patch={status:'error',error:answer.error};
        else{
          const parts=C.markdownBlocks(answer.body.text||'');
          const lead=C.leadHeading(parts.blocks);
          patch={status:'ok',mode:'text',text:answer.body.text||'',blocks:lead.blocks,heading:lead.heading,meta:parts.meta,sha:answer.body.sha256||null,
            size:answer.body.size,eof:!!answer.body.eof,next:answer.body.next_offset};
        }
      }
    }else{
      const artId=entry.entry_id.slice('artifact:'.length);
      const answer=await client.get(C.PATHS.artifact(artId));
      if(gen!==S.gen)return;
      if(!answer.ok)patch={status:'error',error:answer.error};
      else{
        const a=answer.body.artifact||{};
        const mime=String(a.mime_type||'');
        let mode='text';
        if(entry.open==='link'||entry.kind==='link')mode='link';
        else if(entry.open==='media'&&(entry.kind==='image'||mime.startsWith('image/')))mode='image';
        else if(entry.open==='media'&&mime==='application/pdf')mode='pdf';
        else if(entry.open==='media')mode='media';
        else if(entry.open==='none')mode='none';
        const parts=C.markdownBlocks(a.text||'');
        patch={status:'ok',mode,artifactId:artId,mime,url:String(a.text||entry.preview||'').trim(),text:a.text||'',blocks:parts.blocks,meta:parts.meta,eof:true,
          truncated:a.text_truncated?`Lecture limitée aux 16 000 premiers caractères${typeof a.text_chars==='number'?` sur ${a.text_chars.toLocaleString('fr-FR')}`:''}.`:''};
        if(mode==='text'&&!a.text)patch.blocks=[{t:'p',inline:[{t:'text',v:'Cet élément n’a pas de texte lisible.'}]}];
      }
    }
    setDoc(id,patch);
    log(patch.status==='ok'?'info':'warn','dossier.doc_read',{entry:id.split(':')[0],mode:patch.mode||null,code:patch.error&&patch.error.code||null});
    if(S.open)render();
  }
  async function moreText(id){
    const d=docOf(id),e=entryOf(id);
    if(!d||!e||d.eof)return;
    const gen=S.gen;
    S.busy={label:'Lecture de la suite',since:now()};render();
    const answer=await client.get(C.PATHS.read(S.boardId,e.path,d.next));
    S.busy=null;
    if(gen!==S.gen)return;
    if(!answer.ok){d.flash={tone:'bad',text:`${answer.error.title}. ${answer.error.hint}`};render();return}
    d.text+=answer.body.text||'';d.eof=!!answer.body.eof;d.next=answer.body.next_offset;
    const parts=C.markdownBlocks(d.text);const lead=C.leadHeading(parts.blocks);d.blocks=lead.blocks;d.heading=lead.heading;d.meta=parts.meta;
    render();
  }
  async function loadAdvanced(id){
    const gen=S.gen;
    S.adv.set(id,{status:'loading'});render();
    const answer=await client.get(C.PATHS.entry(S.boardId,id,true));
    if(stale(gen,'advanced'))return;
    S.adv.set(id,answer.ok?{status:'ok',advanced:answer.body.entry&&answer.body.entry.advanced||{}}:{status:'error',error:answer.error});
    render();
  }

  /* ------------------------------------------------------------ gestes */
  function openEntry(entry,{opener='user',focus=true}={}){
    const at=now();
    markDirty();
    const r=C.openTab(S.tabs,entry.entry_id,{opener,at,active:S.active==='browse'?null:S.active});
    if(r.full){
      const guard=C.editGuard({dirtyCount:S.tabs.length,tabsFull:true});
      S.notice={tone:'warn',text:`${opener==='jarvis'?'Jarvis voulait ouvrir':'Impossible d’ouvrir'} « ${entry.title||'ce document'} » : ${guard.reason}. Enregistrez ou abandonnez une modification, puis réessayez.`};
      log('warn','dossier.open_refused',{code:guard.code,opener,tabs:S.tabs.length});
      render();say(S.notice.text);
      return {ok:false,code:guard.code,reason:guard.reason};
    }
    S.tabs=r.tabs;S.active=r.active;
    if(r.dropped){S.docs.delete(r.dropped);if(S.split&&S.split.includes(r.dropped))S.split=null}
    if(opener==='jarvis'){const pair=C.pairFor(S.tabs,entry.entry_id,at);if(pair&&layout().split)S.split=pair}
    else if(S.split&&!S.split.includes(entry.entry_id))S.split=null;
    if(!S.list.entries.some(e=>e.entry_id===entry.entry_id))setDoc(entry.entry_id,{entry});
    S.menu=null;S.orgOpen=false;
    ensureDoc(entry);
    render();
    if(focus){const t=host.querySelector(`[data-fk="title:${CSS.escape(entry.entry_id)}"]`);if(t)t.focus({preventScroll:true})}
    say(`${entry.title||'Document'} ouvert${opener==='jarvis'?' à la demande de Jarvis':''}.`);
    return {ok:true};
  }
  function openById(id){
    const e=entryOf(id);
    if(e)return openEntry(e);
    /* Un résultat de recherche hors des 100 listées : l'entrée est résolue par le service. */
    const mine=S.busy={label:'Ouverture',since:now()};render();
    const gen=S.gen;
    client.get(C.PATHS.entry(S.boardId,id,false)).then(answer=>{
      if(S.busy===mine)S.busy=null;  // avant le test : une réponse périmée n'affiche plus son attente (QA S08 B2)
      if(stale(gen,'open_by_id')){render();return}
      if(answer.ok&&answer.body.entry)openEntry(answer.body.entry);
      else{S.notice={tone:'bad',text:`${answer.error.title}. ${answer.error.hint}`};render()}
    });
  }
  async function present(id,representation){
    const e=entryOf(id);if(!e)return;
    const caps=C.capabilities(e,{board:S.board,displayedBoardId:S.displayed,running:running(),coreLost:S.coreLost});
    S.menu=null;
    if(!caps.present.ok){setDoc(id,{flash:{tone:'bad',text:caps.present.reason}});render();return}
    const mine=S.busy={label:'Affichage sur le Board',since:now()};render();
    const gen=S.gen;
    const answer=await client.post(C.PATHS.present(S.boardId),{entry_id:id,representation});
    if(S.busy===mine)S.busy=null;  // avant le test : une réponse périmée n'affiche plus son attente (QA S08 B2)
    if(stale(gen,'present')){render();return}
    const out=C.presentOutcome(answer,representation);
    log(out.kind==='ok'?'info':'warn','dossier.present',{entry:id.split(':')[0],representation,status:answer.status,created:out.created||false,code:out.error&&out.error.code||null});
    setDoc(id,{flash:{tone:out.kind==='ok'?'ok':out.kind==='unknown'?'warn':'bad',text:out.message}});
    say(out.message);
    render();
  }
  function startEdit(id){
    const e=entryOf(id),d=docOf(id);
    const caps=C.capabilities(e,{board:S.board,displayedBoardId:S.displayed,running:running(),coreLost:S.coreLost});
    if(!caps.edit.ok){setDoc(id,{flash:{tone:'bad',text:caps.edit.reason}});render();return}
    if(!d||d.status!=='ok'){ensureDoc(e,true);return}
    readAll(id).then(ok=>{
      if(!ok)return;
      const doc=docOf(id);
      doc.edit={draft:doc.text,base:doc.text,sha:doc.sha,status:'idle',conflict:false,unknown:false,theirs:null,error:null};
      doc.flash=null;
      render();
      const ta=host.querySelector(`[data-fk="edit:${CSS.escape(id)}"]`);if(ta)ta.focus();
      log('info','dossier.edit_started',{entry:'memory',bytes:doc.text.length});
    });
  }
  /* L'édition porte sur le fichier entier : la suite est lue avant (256 Kio au plus). */
  async function readAll(id){
    const d=docOf(id);
    while(d&&!d.eof){
      const before=d.next;await moreText(id);
      if(!docOf(id)||docOf(id).next===before){return false}
    }
    return !!d;
  }
  async function save(id){
    const d=docOf(id),e=entryOf(id);
    if(!d||!d.edit||d.edit.status==='saving'||!e)return;
    const ed=d.edit;
    if(S.coreLost){ed.error=C.errorOf('core_unreachable',0,'');render();return}
    ed.status='saving';ed.since=now();ed.error=null;render();
    const body={path:e.path,content:ed.draft,mode:'replace'};
    if(ed.sha)body.expected_sha256=ed.sha;
    const gen=S.gen;
    const answer=await client.post(C.PATHS.mutate(S.boardId,'write'),body);
    if(stale(gen,'save'))return;
    const out=C.writeOutcome(answer);
    log(out.kind==='saved'?'info':'warn','dossier.save',{outcome:out.kind,status:answer.status,code:out.error&&out.error.code||null,ms:answer.ms});
    if(out.kind==='saved'){
      d.edit=null;
      await loadDoc(e);
      setDoc(id,{flash:{tone:out.ledgerFailed?'warn':'ok',text:out.ledgerFailed?'Enregistré, mais non inscrit au journal d’activité.':'Enregistré. Jarvis lira cette version.'}});
      loadList();
      say('Enregistré.');return;
    }
    ed.status='idle';
    if(out.kind==='conflict'){
      ed.conflict=true;ed.unknown=false;
      const cur=await client.get(C.PATHS.read(S.boardId,e.path,0));
      if(cur.ok){ed.theirs=cur.body.text||'';ed.sha=cur.body.sha256||null}
      else ed.error=cur.error;
      say('Conflit : le fichier a changé depuis votre lecture.');
    }else if(out.kind==='unknown'){ed.unknown=true;say('Issue inconnue de l’enregistrement.')}
    else ed.error=out.error;
    render();
  }
  async function reread(id){
    const d=docOf(id),e=entryOf(id);if(!d||!d.edit||!e)return;
    const gen=S.gen;
    const cur=await client.get(C.PATHS.read(S.boardId,e.path,0));
    if(stale(gen,'reread')||!d.edit)return;
    if(cur.ok){d.edit.theirs=cur.body.text||'';d.edit.sha=cur.body.sha256||null;d.edit.unknown=false;d.edit.conflict=(cur.body.text||'')!==d.edit.draft}
    else d.edit.error=cur.error;
    render();
  }
  async function move(id,to){
    const e=entryOf(id);const f=S.form;if(!e||!f)return;
    const target=String(to||'').trim();
    if(!target||target===e.path){f.error=C.errorOf('memory_path_invalid',0,'même chemin');render();return}
    f.status='busy';f.since=now();f.error=null;render();
    const gen=S.gen;
    const answer=await client.post(C.PATHS.mutate(S.boardId,'move'),{from:e.path,to:target});
    log(answer.ok?'info':'warn','dossier.move',{status:answer.status,code:answer.ok?null:answer.error.code});
    if(stale(gen,'move'))return;
    if(!answer.ok){f.status='idle';f.error=answer.error;render();return}
    S.form=null;
    const newId=`memory:${answer.body.to||target}`;
    S.tabs=S.tabs.map(t=>t.entryId===id?{...t,entryId:newId}:t);
    if(S.active===id)S.active=newId;
    S.docs.delete(id);
    await loadList();
    const ne=entryOf(newId);
    if(ne){await loadDoc(ne);setDoc(newId,{flash:{tone:'ok',text:`Renommé : ${answer.body.to||target}.`}})}
    render();
  }
  async function remove(id){
    const e=entryOf(id);const c=S.confirm;if(!e||!c)return;
    const caps=C.capabilities(e,{board:S.board,displayedBoardId:S.displayed,running:running(),coreLost:S.coreLost});
    if(!caps.delete.ok){c.error=C.errorOf('refused',0,caps.delete.reason);render();return}
    c.status='busy';render();
    const gen=S.gen;
    const answer=await client.post(C.PATHS.mutate(S.boardId,'delete'),{path:e.path});
    log(answer.ok?'info':'warn','dossier.delete',{status:answer.status,code:answer.ok?null:answer.error.code});
    if(stale(gen,'delete'))return;
    if(!answer.ok){c.status='idle';c.error=answer.error;render();return}
    S.confirm=null;
    const r=C.closeTab(S.tabs,id,S.active);S.tabs=r.tabs;S.active=r.active||'browse';S.docs.delete(id);
    if(S.split&&S.split.includes(id))S.split=null;
    S.notice={tone:'ok',text:`« ${e.title} » est supprimé du Dossier.`};
    await loadList();say(S.notice.text);
  }
  async function runSearch(){
    const q=S.filter.trim();if(!q)return;
    S.search={status:'loading',q,matches:[],error:null,since:now()};render();
    const answer=await client.get(C.PATHS.search(S.boardId,q));
    if(S.search.q!==q)return;
    S.search=answer.ok?{status:'ok',q,matches:Array.isArray(answer.body.matches)?answer.body.matches:[],error:null}:{status:'error',q,matches:[],error:answer.error};
    log(answer.ok?'info':'warn','dossier.search',{matches:S.search.matches.length,code:answer.ok?null:answer.error.code});
    render();
  }

  /* ------------------------------------------------------------ ouverture, fermeture, bascule */
  function inertOthers(){
    const keep=new Set(['dossierView','toasts','jvStudioExplorer','confirmBack','jarvisHands','jvFullscreenPrompt']);
    S.inerted=[...document.body.children].filter(n=>!keep.has(n.id)&&!n.classList.contains('toasts')&&!n.inert&&n.tagName!=='SCRIPT'&&n.tagName!=='STYLE');
    for(const n of S.inerted)n.inert=true;
  }
  function show(boardId,{follow,opener}){
    const reason=covered();
    if(reason){
      if(typeof toast==='function')toast({title:'Dossier indisponible',sub:reason,kind:'warn'});
      log('warn','dossier.open_refused',{code:'dossier_unavailable',reason});
      return {ok:false,code:'dossier_unavailable',reason};
    }
    if(!boardId){
      if(typeof toast==='function')toast({title:'Dossier indisponible',sub:'Le Board affiché n’est pas confirmé (Core ne répond pas).',kind:'warn'});
      return {ok:false,code:'dossier_unavailable',reason:'Board inconnu'};
    }
    const rebinding=S.boardId!==boardId;
    if(rebinding&&hasDirtyEdit()){
      /* Relier le Dossier à un autre Board fermerait l'éditeur : refusé, le brouillon reste (QA S07, B1). */
      const guard=C.editGuard({dirtyCount:1,boardId:S.boardId,targetBoardId:boardId});
      log('warn','dossier.open_refused',{code:guard.code,from:S.boardId,to:boardId});
      return {ok:false,code:guard.code,reason:guard.reason};
    }
    if(rebinding)resetForBoard(boardId);
    S.follow=follow;
    if(!S.open){
      S.open=true;host.hidden=false;
      const a=document.activeElement;
      S.opener=opener||(a&&a!==document.body&&!host.contains(a)?a:null);
      inertOthers();
      document.documentElement.classList.add('dsr-open');
      try{if(root.JarvisToolWheel&&root.JarvisToolWheel.isOpen())root.JarvisToolWheel.close()}catch(_e){/* intentional: the wheel closes itself on activation anyway */}
      log('info','dossier.opened',{board:boardId,follow});
    }
    if(rebinding||S.list.status==='idle'||S.list.status==='error')loadList();else render();
    return {ok:true};
  }
  function resetForBoard(boardId){
    S.gen+=1;S.boardId=boardId;S.board=null;S.busy=null;
    S.list={status:'idle',entries:[],total:0,truncated:false,sources:null,error:null,since:0,at:0};
    S.tabs=[];S.active='browse';S.split=null;S.docs=new Map();S.adv=new Map();S.menu=null;S.form=null;S.confirm=null;
    S.section='home';S.filter='';S.search={status:'idle',q:'',matches:[],error:null,since:0};S.notice=null;
  }
  function hasDirtyEdit(){for(const d of S.docs.values())if(d.edit&&d.edit.draft!==d.edit.base)return d;return null}
  /* `dirty` sur chaque onglet : posé dès qu'un éditeur diffère du texte chargé, retiré après un enregistrement
     confirmé ou un abandon (l'éditeur disparaît). L'éviction et les refus le lisent (QA S07, B2). */
  function markDirty(){
    let n=0;
    for(const t of S.tabs){const d=docOf(t.entryId);t.dirty=!!(d&&d.edit&&d.edit.draft!==d.edit.base);if(t.dirty)n+=1}
    return n;
  }
  function tabsWouldBeFull(entryId){
    if(S.tabs.some(t=>t.entryId===entryId)||S.tabs.length<C.MAX_TABS)return false;
    markDirty();
    return S.tabs.every(t=>t.dirty);
  }
  function close(options){
    if(!S.open)return true;
    const dirty=hasDirtyEdit();
    if(dirty&&!(options&&options.force)){
      dirty.edit.askDiscard=true;
      const id=[...S.docs.entries()].find(([,v])=>v===dirty)[0];
      if(S.active!==id&&!(S.split&&S.split.includes(id)))S.active=id;
      render();
      const k=host.querySelector('[data-fk="discard-no"]');if(k)k.focus();
      return false;
    }
    S.open=false;host.hidden=true;S.menu=null;S.form=null;S.confirm=null;S.orgOpen=false;
    for(const d of S.docs.values())d.edit=null;
    for(const n of S.inerted)n.inert=false;S.inerted=[];
    document.documentElement.classList.remove('dsr-open');
    clearInterval(tick);tick=null;
    const back=S.opener&&S.opener.isConnected&&!S.opener.disabled&&S.opener.offsetParent!==null?S.opener:null;
    S.opener=null;
    if(back)back.focus({preventScroll:true});
    else try{if(root.JarvisToolWheel)root.JarvisToolWheel.focusAnchor()}catch(_e){/* intentional: no wheel, focus stays on the page */}
    log('info','dossier.closed',{board:S.boardId});
    return true;
  }
  /* Échap : d'abord ce qui est ouvert dans le Dossier, puis le Dossier. */
  function escapeStep(){
    if(S.menu){const k=S.menu;S.menu=null;render();const b=host.querySelector(`[data-fk="${k.kind}-menu:${CSS.escape(k.entryId)}"]`);if(b)b.focus();return}
    if(S.confirm){const id=S.confirm.entryId;S.confirm=null;render();focusTitle(id);return}
    if(S.form){const id=S.form.entryId;S.form=null;render();focusTitle(id);return}
    for(const [id,d] of S.docs){
      if(!d.edit||(S.active!==id&&!(S.split&&S.split.includes(id))))continue;
      if(d.edit.askDiscard){d.edit.askDiscard=false;render();const t=host.querySelector(`[data-fk="edit:${CSS.escape(id)}"]`);if(t)t.focus();return}
      if(d.edit.draft!==d.edit.base){d.edit.askDiscard=true;render();const k=host.querySelector('[data-fk="discard-no"]');if(k)k.focus();return}
      d.edit=null;render();focusTitle(id);return;
    }
    if(S.orgOpen){S.orgOpen=false;render();orgToggle.focus();return}
    if(ctxOpen()&&layout().ctxDrawer){S.ctxOpen=false;render();ctxToggle.focus();return}
    close();
  }
  function focusTitle(id){const t=host.querySelector(`[data-fk="title:${CSS.escape(id)}"]`);if(t)t.focus({preventScroll:true})}

  /* ------------------------------------------------------------ événements */
  host.addEventListener('click',event=>{
    const t=event.target.closest&&event.target.closest('button,[data-section],[data-open]');
    if(!t||!host.contains(t))return;
    if(t.getAttribute('aria-disabled')==='true'){
      const why=t.title||(t.querySelector('.dsr-menu-note')||{}).textContent;
      if(why){S.notice={tone:'info',text:why};render()}
      return;
    }
    if(t===closeBtn)return void close();
    if(t===orgToggle){S.orgOpen=!S.orgOpen;render();return}
    if(t===ctxToggle){S.ctxOpen=!ctxOpen();render();return}
    if(t.dataset.twisty!==undefined){const p=t.dataset.twisty;S.collapsed.has(p)?S.collapsed.delete(p):S.collapsed.add(p);render();return}
    if(t.dataset.section){S.section=t.dataset.section;S.active='browse';S.split=null;S.orgOpen=false;render();return}
    if(t.dataset.open)return void openById(t.dataset.open);
    if(t.dataset.tab){S.active=t.dataset.tab;if(S.split&&!S.split.includes(S.active))S.split=null;S.menu=null;render();return}
    if(t.dataset.close){const r=C.closeTab(S.tabs,t.dataset.close,S.active);const d=docOf(t.dataset.close);
      if(d&&d.edit&&d.edit.draft!==d.edit.base){S.active=t.dataset.close;d.edit.askDiscard=true;render();return}
      S.tabs=r.tabs;S.active=r.active||'browse';S.docs.delete(t.dataset.close);if(S.split&&S.split.includes(t.dataset.close))S.split=null;render();return}
    const act=t.dataset.act,id=t.dataset.entry;
    if(!act)return;
    if(act==='reload')return void loadList();
    if(act.startsWith('reload-doc:')){const e=entryOf(act.slice(11));if(e)ensureDoc(e,true);return}
    if(act==='search')return void runSearch();
    if(act==='ctx-close'){S.ctxOpen=false;render();ctxToggle.focus();return}
    if(act==='present-menu'||act==='more-menu'||act==='compare-menu'){const kind=act.split('-')[0];S.menu=S.menu&&S.menu.kind===kind&&S.menu.entryId===id?null:{kind,entryId:id};render();return}
    if(act==='present')return void present(id,t.dataset.value||'window');
    if(act==='compare'){S.split=[id,t.dataset.value];S.active=id;S.menu=null;render();return}
    if(act==='unsplit'){S.split=null;S.active=id;render();return}
    if(act==='edit')return void startEdit(id);
    if(act==='save')return void save(id);
    if(act==='reread')return void reread(id);
    if(act==='edit-cancel'){const d=docOf(id);if(d&&d.edit){if(d.edit.draft!==d.edit.base){d.edit.askDiscard=true;render();const k=host.querySelector('[data-fk="discard-no"]');if(k)k.focus()}else{d.edit=null;render();focusTitle(id)}}return}
    if(act==='discard-no'){const d=docOf(id);if(d&&d.edit){d.edit.askDiscard=false;render();const ta=host.querySelector(`[data-fk="edit:${CSS.escape(id)}"]`);if(ta)ta.focus()}return}
    if(act==='discard-yes'){const d=docOf(id);if(d)d.edit=null;render();focusTitle(id);return}
    if(act==='more-text')return void moreText(id);
    if(act==='zoom'){const d=docOf(id);if(d){d.zoom=!d.zoom;render()}return}
    if(act==='move-form'){const e=entryOf(id);S.menu=null;S.form={kind:'move',entryId:id,value:e.path,status:'idle',error:null};render();const i=host.querySelector('[data-fk="move-input"]');if(i){i.focus();i.select()}return}
    if(act==='form-cancel'){const fid=S.form&&S.form.entryId;S.form=null;render();focusTitle(fid);return}
    if(act==='delete-ask'){S.menu=null;S.confirm={kind:'delete',entryId:id,status:'idle',error:null};render();const k=host.querySelector('[data-fk="delete-cancel"]');if(k)k.focus();return}
    if(act==='delete-cancel'){const cid=S.confirm&&S.confirm.entryId;S.confirm=null;render();focusTitle(cid);return}
    if(act==='delete')return void remove(id);
  });
  host.addEventListener('submit',event=>{
    const form=event.target.closest('form[data-form="move"]');if(!form)return;
    event.preventDefault();
    if(S.form&&S.form.status!=='busy')move(S.form.entryId,form.querySelector('input[name="to"]').value);
  });
  host.addEventListener('input',event=>{
    const t=event.target;
    if(t===search){S.filter=search.value;if(S.active!=='browse'){S.active='browse';S.split=null}render();return}
    if(t.dataset&&t.dataset.fk==='move-input'&&S.form){S.form.value=t.value;return}
    if(t.tagName==='TEXTAREA'&&t.dataset.entry){const d=docOf(t.dataset.entry);if(d&&d.edit){d.edit.draft=t.value;markDirty()}}
  });
  host.addEventListener('toggle',event=>{
    if(!event.target.classList||!event.target.classList.contains('dsr-adv'))return;
    const open=event.target.open;if(open===S.advanced)return;
    S.advanced=open;
    if(open&&S.active!=='browse'&&!S.adv.has(S.active))loadAdvanced(S.active);else render();
  },true);
  search.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();runSearch()}});
  host.addEventListener('keydown',event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){
      const ta=event.target.closest&&event.target.closest('textarea[data-entry]');
      if(ta){event.preventDefault();save(ta.dataset.entry)}return;
    }
    if(event.target.getAttribute&&event.target.getAttribute('role')==='tab'&&(event.key==='ArrowRight'||event.key==='ArrowLeft'||event.key==='Home'||event.key==='End')){
      const tabs=[...host.querySelectorAll('[role="tab"]')];const i=tabs.indexOf(event.target);
      const n=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
      event.preventDefault();tabs[n].click();const again=host.querySelector(`[data-fk="${CSS.escape(tabs[n].dataset.fk)}"]`);if(again)again.focus();return;
    }
    if(S.menu&&(event.key==='ArrowDown'||event.key==='ArrowUp')){
      const items=[...host.querySelectorAll('#dsrMenu [role="menuitem"]')];if(!items.length)return;
      const i=items.indexOf(document.activeElement);event.preventDefault();
      items[(i+(event.key==='ArrowDown'?1:-1)+items.length)%items.length].focus();return;
    }
    if(event.key!=='Tab')return;
    const focusable=[...host.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),textarea,summary,[tabindex="0"]')].filter(n=>n.offsetParent!==null&&!n.closest('[hidden]'));
    if(!focusable.length)return;
    const first=focusable[0],last=focusable[focusable.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
  });
  document.addEventListener('keydown',event=>{
    if(!S.open||event.key!=='Escape')return;
    /* La confirmation de la page (rang 85) et Variantes (9000), ouverts par-dessus, gardent leur Échap. */
    const cd=document.getElementById('confirmBack');
    if(cd&&!cd.hidden)return;
    if(covered())return;
    event.preventDefault();event.stopPropagation();
    escapeStep();
  },true);
  window.addEventListener('resize',()=>{if(S.open)render()});

  /* ------------------------------------------------------------ couture du statut et de la roue */
  function gate(block,navigation){
    /* La commande de Jarvis en attente, relevée au battement (Slice 08) ; `channel` est posé plus bas, avant tout battement. */
    if(navigation)channel.beat(navigation);
    const active=block&&block.active&&block.active.board_id?String(block.active.board_id):null;
    /* Core arrêté alors que le Control Center répond (Slice 08, QA S07 1) : le statut arrive, mais sans Board actif
       et avec son erreur. C'est « Core ne répond pas », pas « ce Board n'est pas le Board affiché ». */
    if(block&&!active&&(block.available===false||block.error)){
      if(!S.coreLost)log('warn','dossier.core_lost',{code:block&&block.error&&block.error.code||null});
      statusLost();return;
    }
    const was=S.displayed;
    S.coreLost=false;
    S.displayed=active;
    if(S.open&&active!==was){
      const decision=C.rebindOnSwitch({follow:S.follow,boardId:S.boardId,displayedBoardId:active});
      if(decision==='rebind'){
        const dirty=hasDirtyEdit();
        if(dirty){
          /* Une modification en cours n'est jamais jetée en silence : le Dossier reste sur l'ancien Board (non affiché),
             l'avis le dit, et Afficher sur le Board s'éteint (il viserait le mauvais Board). */
          S.follow=false;
          S.notice={tone:'warn',text:'Le Board affiché a changé. Votre modification est gardée ici ; ce Dossier reste celui de l’ancien Board jusqu’à ce que vous fermiez.'};
          log('info','dossier.rebind_held',{reason:'dirty_edit'});
          render();
        }else{
          log('info','dossier.rebound',{from:S.boardId,to:active});
          resetForBoard(active);
          S.notice={tone:'info',text:'Le Board affiché a changé : ce Dossier est maintenant le sien.'};
          loadList();say(S.notice.text);
        }
      }else render();
    }else if(S.open&&was===active)renderNotice();
  }
  function statusLost(){
    const was=S.coreLost;S.coreLost=true;
    if(S.open&&!was)render();
  }
  function wheelAnchor(){return document.querySelector('#toolWheel .tw-anchor')}
  /* Dossier dans la roue : un clic ouvre directement le Dossier du Board affiché, sans sous-menu — le même
     chemin que « Ouvrir le Dossier » ; `show` dit lui-même pourquoi il refuse (Variantes, Board inconnu). */
  function registerWheel(){
    const W=root.JarvisToolWheel;
    if(!W||typeof W.register!=='function'){log('warn','dossier.wheel_missing',{});return}
    W.register({id:'dossier',
      onActivate:ctx=>{log('info','dossier.wheel_open',{source:ctx&&ctx.source||null});open({opener:wheelAnchor()})}});
  }

  /* ------------------------------------------------------------ entrées publiques */
  function open(options){
    const o=options||{};
    return show(S.displayed,{follow:true,opener:o.opener||null});
  }
  function openBoard(boardId,options){
    const o=options||{};
    const follow=String(boardId)===S.displayed;
    return show(String(boardId),{follow,opener:o.opener||null});
  }
  /* Ouvrir sur une entrée (toast de Ranger, roue) : l'entrée est résolue par le service, jamais supposée. */
  async function openFromOutside({entry_id,board_id,opener}){
    const r=show(board_id||S.displayed,{follow:!board_id||board_id===S.displayed,opener:opener||null});
    if(!r.ok){if(r.code===C.EDIT_IN_PROGRESS){S.notice={tone:'warn',text:`Rien n’a été ouvert : ${r.reason}. Votre modification est gardée.`};render()}return r}
    const answer=await client.get(C.PATHS.entry(S.boardId,entry_id,false));
    if(!answer.ok){S.notice={tone:'bad',text:`${answer.error.title}. ${answer.error.hint}`};render();return {ok:false,code:answer.error.code}}
    return openEntry(answer.body.entry);
  }

  /* ------------------------------------------------------------ canal Jarvis -> page */
  const channel=(function(){
    const pageId='dsr'+Math.random().toString(36).slice(2,12);
    let visible=document.visibilityState!=='hidden',running=false,failures=0,controller=null;
    const stats={polls:0,received:0,opened:0,refused:0,receiptFailed:0};
    async function request(url,options){
      const ctl=typeof AbortController==='function'?new AbortController():null;
      if(options.poll)controller=ctl;
      const timer=setTimeout(()=>{if(ctl)ctl.abort()},options.timeoutMs);
      try{
        const init={method:options.method||'GET',cache:'no-store'};
        if(ctl)init.signal=ctl.signal;
        if(options.body){init.body=options.body;init.headers={'Content-Type':'application/json',[C.PAGE_TOKEN_HEADER]:PAGE_TOKEN}}
        const response=await window.fetch(url,init);
        let b=null;try{b=await response.json()}catch(_e){b=null /* intentional: reported by status */}
        return {status:response.status,body:b};
      }finally{clearTimeout(timer);if(controller===ctl)controller=null}
    }
    async function handle(command){
      stats.received+=1;
      const started=now();
      let receipt;
      try{receipt=await decide(command)}
      catch(error){log('error','dossier.navigation_failed',{id:short(command.id),error:String(error&&error.message||error)});
        receipt={state:'refused',code:'dossier_unavailable',reason:'erreur de la page'}}
      const body=receipt.state==='opened'?{state:'opened'}:{state:'refused',code:receipt.code,...(receipt.reason?{reason:String(receipt.reason).slice(0,200)}:{})};
      if(receipt.state==='opened')stats.opened+=1;else stats.refused+=1;
      try{
        const answer=await request(`${C.COMMAND_ROUTE}/${encodeURIComponent(command.id)}`,{method:'POST',body:JSON.stringify(body),timeoutMs:4000});
        if(answer.status!==200)throw new Error(`HTTP ${answer.status}`);
        log(receipt.state==='opened'?'info':'warn','dossier.navigation_answered',{id:short(command.id),state:receipt.state,code:body.code||null,ms:now()-started});
      }catch(error){stats.receiptFailed+=1;log('error','dossier.navigation_receipt_failed',{id:short(command.id),error:String(error&&error.message||error)})}
    }
    async function decide(command){
      const d=C.openDecision(command,{displayedBoardId:S.displayed,covered:covered()});
      if(!d.ok)return {state:'refused',code:d.code,reason:d.reason};
      const answer=await client.get(C.PATHS.entry(command.board_id,command.entry_id,false),C.DEADLINE_MS.nav);
      if(!answer.ok){
        if(answer.error.code==='dossier_entry_not_found'||answer.status===404)return {state:'refused',code:'entry_not_found',reason:'cette entrée n’est pas dans le Dossier de ce Board'};
        return {state:'refused',code:'dossier_unavailable',reason:`${answer.error.title} (${answer.error.code})`};
      }
      const wanted=answer.body.entry;
      const guard=C.editGuard({dirtyCount:hasDirtyEdit()?1:0,boardId:S.open?S.boardId:null,targetBoardId:command.board_id,
        tabsFull:S.open&&S.boardId===command.board_id&&tabsWouldBeFull(wanted.entry_id)});
      if(!guard.ok){
        S.notice={tone:'warn',text:`Jarvis voulait ouvrir « ${wanted.title||'une entrée'} » : ${guard.reason}. Votre modification est gardée.`};
        render();say(S.notice.text);
        return {state:'refused',code:guard.code,reason:guard.reason};
      }
      const r=show(command.board_id,{follow:true,opener:null});
      if(!r.ok)return {state:'refused',code:r.code,reason:r.reason};
      const o=openEntry(wanted,{opener:'jarvis'});
      if(!o.ok)return {state:'refused',code:o.code,reason:o.reason};
      /* « opened » = le Dossier est visible, sur cette entrée : vérifié dans le DOM, pas supposé. */
      const shown=!host.hidden&&!!host.querySelector(`article[data-entry="${CSS.escape(answer.body.entry.entry_id)}"]`);
      return shown?{state:'opened'}:{state:'refused',code:'dossier_unavailable',reason:'la page n’a pas pu montrer l’entrée'};
    }
    /* Aucune connexion longue (Slice 08, QA B1) : chaque page visible tient déjà les long-polls du plein écran et
       de l'explorateur ; avec deux pages, celui du Dossier saturait les six connexions par origine de Chrome et
       affamait `/api/status`. La page relève donc la commande au battement de statut à 1 Hz : quand
       `/api/status.dossier_navigation.pending` est vrai, un `GET …/commands?wait_s=0` court. La remise du Control
       Center est exclusive : un seul onglet reçoit la commande et l'exécute. */
    async function pull(){
      if(!visible||running)return;
      running=true;
      try{
        stats.polls+=1;
        const answer=await request(`${C.COMMAND_ROUTE}?wait_s=0&page=${pageId}&visible=1`,{poll:true,timeoutMs:PULL_TIMEOUT_MS});
        if(answer.status!==200)throw new Error(`HTTP ${answer.status}`);
        const command=answer.body&&answer.body.command;
        if(command)await handle(command);
        failures=0;
      }catch(error){
        failures+=1;
        if(failures===1||failures%10===0)log('warn','dossier.navigation_poll_failed',{error:String(error&&error.message||error),failures});
      }finally{running=false}
    }
    function beat(block){
      if(block&&block.pending===true)pull().catch(error=>log('error','dossier.navigation_pull_failed',{error:String(error&&error.message||error)}));
    }
    function start(){/* plus de boucle : le battement de statut appelle `beat` */}
    document.addEventListener('visibilitychange',()=>{
      const next=document.visibilityState!=='hidden';if(next===visible)return;visible=next;
      if(!visible){
        if(controller)try{controller.abort()}catch(_e){/* intentional: dropped either way */}
        request(`${C.COMMAND_ROUTE}?wait_s=0&page=${pageId}&visible=0`,{timeoutMs:4000}).catch(error=>log('warn','dossier.hidden_notice_failed',{error:String(error&&error.message||error)}));
      }
    });
    return {start,beat,stats:()=>({...stats}),pageId:()=>pageId,state:()=>({visible,running,failures})};
  })();

  registerWheel();
  channel.start();
  root.JarvisDossier=Object.freeze({
    open,openBoard,close:()=>close(),openEntry:openFromOutside,gate,statusLost,
    isOpen:()=>S.open,
    /* Relevé des tests et des preuves. */
    state:()=>({open:S.open,boardId:S.boardId,follow:S.follow,displayed:S.displayed,board:S.board,coreLost:S.coreLost,
      list:{status:S.list.status,count:S.list.entries.length,total:S.list.total,truncated:S.list.truncated},
      tabs:S.tabs.map(t=>({entryId:t.entryId,opener:t.opener,...(t.dirty?{dirty:true}:{})})),active:S.active,split:S.split,section:S.section,
      ctxOpen:ctxOpen(),advanced:S.advanced,layout:layout()}),
    channel:Object.freeze({stats:channel.stats,pageId:channel.pageId,state:channel.state}),
  });
  log('info','dossier.installed',{page:channel.pageId()});

  /* ------------------------------------------------------------ feuille (internes de `.dsr`, rang 55 posé par la page) */
  function installStyle(){
    if(document.getElementById('dsrStyle'))return;
    const css=`
#dossierView{--dsr-bg:#060b10;--dsr-pane:#08121a;--dsr-rule:rgba(110,231,255,.13);--dsr-rule-strong:rgba(110,231,255,.28);
  --dsr-ink:#e4f1f7;--dsr-soft:#9fb8c6;--dsr-faint:#6f8a99;--dsr-sans:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif;
  --dsr-read:Charter,"Bitstream Charter","Iowan Old Style",Cambria,Georgia,serif;--dsr-k-assistant:var(--accent);--dsr-k-presentation:#e19bff;--dsr-k-meeting:#ffc46b;
  color:var(--dsr-ink);font-family:var(--dsr-sans);font-size:14px}
#dossierView .dsr-head{display:flex;align-items:center;gap:12px;min-height:56px;padding:8px 18px;border-bottom:1px solid var(--dsr-rule);background:linear-gradient(180deg,rgba(110,231,255,.05),transparent)}
#dossierView .dsr-title{display:flex;align-items:center;gap:10px;min-width:0;flex:1 1 auto;margin:0;font-size:17px;font-weight:600;letter-spacing:0}
#dossierView .dsr-title>svg{flex:none;color:var(--accent)}
#dossierView .dsr-word{flex:none;font:600 11px/1 ui-monospace,Consolas,monospace;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
#dossierView .dsr-kind{flex:none;padding:3px 8px;border:1px solid currentColor;border-radius:999px;font:600 10.5px/1.2 ui-monospace,Consolas,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--dsr-k-assistant)}
#dossierView .dsr-kind[data-kind=presentation]{color:var(--dsr-k-presentation)}
#dossierView .dsr-kind[data-kind=meeting]{color:var(--dsr-k-meeting)}
#dossierView .dsr-board{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#dossierView .dsr-muted,#dossierView .dsr-quiet{color:var(--dsr-faint)}
#dossierView .dsr-chip{flex:none;padding:2px 8px;border-radius:6px;background:rgba(255,184,92,.12);color:var(--warn);font-size:11.5px;font-weight:500}
#dossierView .dsr-search{position:relative;flex:0 1 300px;min-width:140px}
#dossierView .dsr-search-icon{position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--dsr-faint);pointer-events:none}
#dossierView .dsr-search-input{width:100%;height:34px;padding:0 10px 0 32px;border:1px solid var(--dsr-rule-strong);border-radius:8px;background:#03080c;color:var(--dsr-ink);font:inherit}
#dossierView .dsr-search-input::placeholder{color:var(--dsr-faint)}
#dossierView button{font:inherit;color:inherit}
#dossierView .dsr-btn,#dossierView .dsr-close,#dossierView a.dsr-btn{display:inline-flex;align-items:center;gap:7px;min-height:32px;padding:0 12px;border:1px solid var(--dsr-rule-strong);border-radius:8px;background:rgba(3,8,12,.7);color:var(--dsr-ink);cursor:pointer;text-decoration:none;white-space:nowrap;transition:border-color var(--shell-dur-fast,120ms),background var(--shell-dur-fast,120ms)}
#dossierView .dsr-btn:hover,#dossierView .dsr-close:hover{border-color:var(--accent);background:rgba(110,231,255,.07)}
#dossierView .dsr-btn[aria-pressed=true]{border-color:var(--accent);color:var(--accent)}
#dossierView .dsr-btn[aria-disabled=true]{opacity:.5;cursor:not-allowed}
#dossierView .dsr-primary{border-color:var(--accent);background:rgba(110,231,255,.14);color:#dffaff}
#dossierView .dsr-danger-btn{border-color:var(--danger);color:#ffd5da;background:rgba(255,101,119,.12)}
#dossierView .dsr-kbd{padding:1px 5px;border:1px solid var(--dsr-rule-strong);border-radius:4px;font:10.5px ui-monospace,Consolas,monospace;color:var(--dsr-soft)}
#dossierView .dsr-org-toggle{display:none}
#dossierView :is(button,a,input,textarea,summary,[tabindex]):focus-visible{outline:2px solid var(--accent);outline-offset:2px}
#dossierView .dsr-notice{padding:8px 18px;border-bottom:1px solid var(--dsr-rule);font-size:13px;color:var(--dsr-soft);background:rgba(110,231,255,.05)}
#dossierView .dsr-notice[data-tone=warn]{color:#ffd9a6;background:rgba(255,184,92,.09)}
#dossierView .dsr-notice[data-tone=bad]{color:#ffd0d6;background:rgba(255,101,119,.1)}
#dossierView .dsr-notice[data-tone=ok]{color:#c9f5dd;background:rgba(104,224,160,.08)}
#dossierView .dsr-body{display:grid;grid-template-columns:var(--dsr-org-w,264px) minmax(0,1fr) auto;min-height:0;overflow:hidden}
#dossierView .dsr-org{overflow:auto;padding:12px 8px 24px;border-right:1px solid var(--dsr-rule);background:var(--dsr-pane)}
#dossierView .dsr-org-h{margin:18px 10px 6px;font:600 10.5px/1 ui-monospace,Consolas,monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--dsr-faint)}
#dossierView .dsr-nav{display:flex;align-items:center;gap:9px;width:100%;min-height:32px;padding:4px 10px;border:0;border-radius:7px;background:none;color:var(--dsr-soft);text-align:left;cursor:pointer}
#dossierView .dsr-nav:hover{background:rgba(110,231,255,.06);color:var(--dsr-ink)}
#dossierView .dsr-nav[aria-current=page]{background:rgba(110,231,255,.11);color:var(--dsr-ink);box-shadow:inset 0 0 0 1px rgba(110,231,255,.22)}
#dossierView .dsr-nav-label{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#dossierView .dsr-count{flex:none;margin-left:6px;font:11px ui-monospace,Consolas,monospace;color:var(--dsr-faint);font-variant-numeric:tabular-nums}
#dossierView .dsr-folder{display:flex;align-items:center}
#dossierView .dsr-folder .dsr-nav{flex:1;min-width:0}
#dossierView .dsr-twisty,#dossierView .dsr-twisty-gap{flex:none;width:18px;height:24px;display:inline-flex;align-items:center;justify-content:center;border:0;background:none;color:var(--dsr-faint);cursor:pointer;padding:0}
#dossierView .dsr-twisty[aria-expanded=true] svg{transform:rotate(90deg)}
#dossierView .dsr-work{display:flex;flex-direction:column;min-width:0;min-height:0}
#dossierView .dsr-tabs{display:flex;gap:2px;padding:6px 12px 0;border-bottom:1px solid var(--dsr-rule);overflow-x:auto;scrollbar-width:thin;flex:none}
#dossierView .dsr-tab{display:flex;align-items:center;flex:none;max-width:260px;border:1px solid transparent;border-bottom:0;border-radius:8px 8px 0 0}
#dossierView .dsr-tab[data-selected="1"]{border-color:var(--dsr-rule-strong);background:var(--dsr-bg);margin-bottom:-1px}
#dossierView .dsr-tab[data-selected="2"]{border-color:var(--dsr-rule)}
#dossierView .dsr-tab-btn{display:flex;align-items:center;gap:7px;min-width:0;min-height:36px;padding:0 6px 0 12px;border:0;background:none;color:var(--dsr-soft);cursor:pointer}
#dossierView .dsr-tab[data-selected="1"] .dsr-tab-btn{color:var(--dsr-ink)}
#dossierView :is(.dsr-tab-btn,.dsr-nav,.dsr-btn,.dsr-close,.dsr-title)>svg{flex:none}
#dossierView .dsr-tab-label{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#dossierView .dsr-tab-x{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;margin-right:4px;border:0;border-radius:6px;background:none;color:var(--dsr-faint);cursor:pointer}
#dossierView .dsr-tab-x:hover{background:rgba(255,255,255,.06);color:var(--dsr-ink)}
#dossierView .dsr-by{flex:none;padding:1px 6px;border-radius:999px;background:rgba(110,231,255,.14);color:var(--accent);font:600 10px/1.4 ui-monospace,Consolas,monospace;letter-spacing:.04em}
#dossierView .dsr-panes{flex:1;min-height:0;display:grid;grid-template-columns:minmax(0,1fr)}
#dossierView .dsr-panes[data-split="2"]{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
#dossierView .dsr-panes[data-split="2"]>.dsr-doc+.dsr-doc{border-left:1px solid var(--dsr-rule)}
#dossierView .dsr-browse,#dossierView .dsr-doc{overflow:auto;min-height:0;padding:22px clamp(18px,3vw,44px) 48px}
#dossierView .dsr-browse>*{max-width:860px;margin-left:auto!important;margin-right:auto!important}
#dossierView .dsr-h{display:flex;align-items:baseline;gap:8px;margin:0 auto 14px;font-size:22px;font-weight:600;letter-spacing:-.01em}
#dossierView .dsr-h4{margin:22px 0 8px;font-size:12.5px;font-weight:600;color:var(--dsr-soft);letter-spacing:.02em}
#dossierView .dsr-lead{padding:16px 20px 14px;border:1px solid var(--dsr-rule);border-radius:10px;background:var(--dsr-pane)}
#dossierView .dsr-lead>.dsr-h4:first-child{margin-top:0}
#dossierView .dsr-lead-title{margin:0 0 6px;font-size:19px;font-weight:600;color:var(--dsr-ink)}
#dossierView .dsr-rows{display:flex;flex-direction:column}
/* Grille de tuiles (2026-10-29) : grandes vignettes pour les images, grandes icônes et titre pour les documents. */
#dossierView .dsr-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(176px,1fr));gap:16px 14px;margin:6px 0 20px}
#dossierView .dsr-grid .dsr-li{min-width:0}
#dossierView .dsr-tile{display:flex;flex-direction:column;gap:8px;width:100%;padding:0;border:0;background:none;color:inherit;font:inherit;text-align:left;cursor:pointer;border-radius:12px}
#dossierView .dsr-tile-face{position:relative;display:grid;place-items:center;aspect-ratio:4/3;border-radius:12px;overflow:hidden;color:var(--dsr-soft);
  background:rgba(110,231,255,.05);border:1px solid rgba(110,231,255,.12);transition:border-color .12s,transform .12s}
#dossierView .dsr-tile:hover .dsr-tile-face,#dossierView .dsr-tile:focus-visible .dsr-tile-face{border-color:var(--accent);transform:translateY(-1px)}
#dossierView .dsr-tile-face img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;background:#05090d}
#dossierView .dsr-tile-face[data-kind=image],#dossierView .dsr-tile-face[data-kind=media]{color:#9fd0ff}
#dossierView .dsr-tile-face[data-kind=memory_summary],#dossierView .dsr-tile-face[data-kind=report]{color:var(--dsr-k-meeting)}
#dossierView .dsr-tile-face[data-kind=presentation]{color:var(--dsr-k-presentation)}
#dossierView .dsr-tile .dsr-row-title{font-size:13.5px;font-weight:500;line-height:1.3;color:var(--dsr-ink);overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
/* Une image : rien que l'image ; son titre monte au survol, sur un dégradé. */
#dossierView .dsr-tile[data-image] .dsr-row-title{position:absolute;left:0;right:0;bottom:0;padding:22px 10px 8px;color:#fff;
  background:linear-gradient(transparent,rgba(2,6,9,.88));opacity:0;transition:opacity .12s}
#dossierView .dsr-tile[data-image]:is(:hover,:focus-visible) .dsr-row-title{opacity:1}
#dossierView .dsr-row{display:flex;align-items:flex-start;gap:12px;width:100%;padding:10px 10px;border:0;border-bottom:1px solid rgba(110,231,255,.07);background:none;text-align:left;cursor:pointer;border-radius:6px}
#dossierView .dsr-row:hover{background:rgba(110,231,255,.05)}
#dossierView .dsr-row-ic{flex:none;display:inline-flex;width:32px;height:32px;align-items:center;justify-content:center;border-radius:8px;background:rgba(110,231,255,.07);color:var(--accent)}
#dossierView .dsr-row-ic[data-kind=image],#dossierView .dsr-row-ic[data-kind=media]{color:#9fd0ff}
#dossierView .dsr-row-ic[data-kind=memory_summary],#dossierView .dsr-row-ic[data-kind=report]{color:var(--dsr-k-meeting)}
#dossierView .dsr-row-main{display:flex;flex-direction:column;gap:2px;min-width:0}
#dossierView .dsr-row-title{font-size:15px;font-weight:500;color:var(--dsr-ink);overflow-wrap:anywhere}
#dossierView .dsr-row-meta{font-size:12px;color:var(--dsr-faint)}
#dossierView .dsr-row-preview{font-size:12.5px;color:var(--dsr-soft);overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
#dossierView .dsr-empty{margin:28px 0;color:var(--dsr-soft);font-size:14px;line-height:1.6}
#dossierView .dsr-link{border:0;background:none;padding:6px 0;color:var(--accent);cursor:pointer;text-decoration:underline;text-underline-offset:3px}
#dossierView .dsr-doc-head{max-width:72ch;margin:0 auto 18px;position:relative}
#dossierView .dsr-doc-title{margin:0 0 6px;font-size:26px;line-height:1.25;font-weight:600;letter-spacing:-.012em;outline:none;overflow-wrap:anywhere}
#dossierView .dsr-doc-meta{margin:0 0 12px;font-size:12.5px;color:var(--dsr-faint)}
#dossierView .dsr-actions{display:flex;flex-wrap:wrap;gap:8px}
#dossierView .dsr-why{margin:10px 0 0;font-size:12.5px;color:var(--warn)}
#dossierView .dsr-flash{margin:10px 0 0;padding:7px 10px;border-radius:7px;font-size:13px}
#dossierView .dsr-ok{background:rgba(104,224,160,.1);color:#c9f5dd}
#dossierView .dsr-warn{background:rgba(255,184,92,.1);color:#ffd9a6}
#dossierView .dsr-bad{background:rgba(255,101,119,.1);color:#ffd0d6}
#dossierView .dsr-menu{position:absolute;left:0;top:calc(100% - 4px);min-width:250px;max-width:340px;padding:6px;border:1px solid var(--dsr-rule-strong);border-radius:10px;background:#071018;box-shadow:0 18px 40px -12px rgba(0,0,0,.7)}
#dossierView .dsr-menu-item{display:flex;flex-direction:column;align-items:flex-start;gap:1px;width:100%;padding:8px 10px;border:0;border-radius:7px;background:none;text-align:left;cursor:pointer}
#dossierView .dsr-menu-item:hover,#dossierView .dsr-menu-item:focus-visible{background:rgba(110,231,255,.09)}
#dossierView .dsr-menu-item[aria-disabled=true]{opacity:.55;cursor:not-allowed}
#dossierView .dsr-menu-note,#dossierView .dsr-menu-why{font-size:11.5px;color:var(--dsr-faint)}
#dossierView .dsr-menu-why{margin:6px 8px;max-width:300px}
#dossierView .dsr-danger .dsr-menu-label{color:#ffb3bd}
#dossierView .dsr-doc-body{max-width:72ch;margin:0 auto}
#dossierView .dsr-panes[data-split="2"] .dsr-doc-head,#dossierView .dsr-panes[data-split="2"] .dsr-doc-body{max-width:none}
#dossierView .dsr-prose{font-family:var(--dsr-read);font-size:17px;line-height:1.68;color:#dbe8ef}
#dossierView .dsr-prose p,#dossierView .dsr-prose ul,#dossierView .dsr-prose ol,#dossierView .dsr-prose blockquote{margin:0 0 .9em}
#dossierView .dsr-prose .dsr-mh{font-family:var(--dsr-sans);margin:1.5em 0 .5em;line-height:1.3;font-weight:600;color:var(--dsr-ink)}
#dossierView .dsr-prose h2.dsr-mh{font-size:21px}#dossierView .dsr-prose h3.dsr-mh{font-size:18px}#dossierView .dsr-prose h4.dsr-mh,#dossierView .dsr-prose h5.dsr-mh,#dossierView .dsr-prose h6.dsr-mh{font-size:15.5px}
#dossierView .dsr-prose>.dsr-mh:first-child{margin-top:0}
#dossierView .dsr-prose code{padding:1px 5px;border-radius:4px;background:rgba(110,231,255,.08);font:14px ui-monospace,Consolas,monospace}
#dossierView .dsr-prose pre{padding:12px 14px;border-radius:8px;background:#03080c;overflow:auto}
/* I-004 M3 (V1.2 Slice 06) : l'en-tête d'un document de recherche (sources, longues URL) passe à la ligne au lieu de
   déborder à droite ; le code d'une note garde son défilement. */
#dossierView .dsr-prose pre.dsr-research-head{white-space:pre-wrap;word-break:break-all;line-height:1.55}
#dossierView .dsr-prose pre.dsr-research-head code{line-height:inherit}
#dossierView .dsr-prose pre code{padding:0;background:none}
#dossierView .dsr-prose blockquote{padding-left:14px;border-left:1px solid var(--dsr-rule-strong);color:var(--dsr-soft)}
#dossierView .dsr-prose hr{border:0;border-top:1px solid var(--dsr-rule);margin:1.6em 0}
#dossierView .dsr-prose a,#dossierView .dsr-url{color:var(--accent);text-underline-offset:3px;overflow-wrap:anywhere}
#dossierView .dsr-excerpt{font-size:15.5px;max-height:15em;overflow:hidden;mask-image:linear-gradient(180deg,#000 70%,transparent)}
#dossierView .dsr-figure{margin:0;display:flex;flex-direction:column;align-items:center;gap:10px}
#dossierView .dsr-figure img{max-width:100%;max-height:calc(100vh - 290px);object-fit:contain;border-radius:8px;border:1px solid var(--dsr-rule);background:#02060a}
#dossierView .dsr-figure[data-zoom="1"] img{max-width:none;max-height:none}
#dossierView .dsr-doc-body:has(.dsr-figure){max-width:none}
#dossierView .dsr-doc-body:has(.dsr-edit-panes[data-split="2"]){max-width:1280px}
#dossierView .dsr-content video,#dossierView .dsr-content audio{width:100%;max-height:70vh}
#dossierView .dsr-wait{color:var(--dsr-soft)}
#dossierView .dsr-clock{font:12px ui-monospace,Consolas,monospace;color:var(--dsr-faint);font-variant-numeric:tabular-nums}
#dossierView .dsr-error{margin:12px 0;padding:12px 14px;border:1px solid rgba(255,101,119,.4);border-radius:9px;background:rgba(255,101,119,.07)}
#dossierView .dsr-error p{margin:4px 0 8px;color:var(--dsr-soft);font-size:13px}
#dossierView .dsr-confirm,#dossierView .dsr-conflict{margin:12px 0;padding:12px 14px;border:1px solid rgba(255,184,92,.45);border-radius:9px;background:rgba(255,184,92,.07)}
#dossierView .dsr-confirm p,#dossierView .dsr-conflict p{margin:6px 0 10px;color:var(--dsr-soft);font-size:13px;line-height:1.5}
#dossierView .dsr-form{margin:12px 0;display:flex;flex-direction:column;gap:8px}
#dossierView .dsr-form-label{font-size:12.5px;color:var(--dsr-soft)}
#dossierView .dsr-input{height:34px;padding:0 10px;border:1px solid var(--dsr-rule-strong);border-radius:8px;background:#03080c;color:var(--dsr-ink);font:13px ui-monospace,Consolas,monospace}
#dossierView .dsr-form-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:10px}
#dossierView .dsr-editor{display:flex;flex-direction:column}
#dossierView .dsr-edit-panes{display:grid;grid-template-columns:minmax(0,1fr);gap:16px}
#dossierView .dsr-edit-panes[data-split="2"]{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
#dossierView .dsr-textarea{width:100%;min-height:min(62vh,640px);padding:14px 16px;border:1px solid var(--dsr-rule-strong);border-radius:10px;background:#03080c;color:var(--dsr-ink);font:14px/1.6 ui-monospace,Consolas,monospace;resize:vertical}
#dossierView .dsr-theirs{padding:12px 14px;border:1px dashed var(--dsr-rule-strong);border-radius:10px;max-height:min(62vh,640px);overflow:auto}
#dossierView .dsr-theirs .dsr-h4{margin-top:0}
#dossierView .dsr-ctx{width:300px;overflow:auto;padding:12px 16px 24px;border-left:1px solid var(--dsr-rule);background:var(--dsr-pane)}
#dossierView .dsr-ctx[hidden]{display:none}
#dossierView .dsr-ctx-head{display:flex;align-items:center;justify-content:space-between}
#dossierView .dsr-ctx-head .dsr-org-h{margin:6px 0}
#dossierView .dsr-ctx-summary{margin:0;font-family:var(--dsr-read);font-size:14.5px;line-height:1.55;color:var(--dsr-soft)}
#dossierView .dsr-ctx .dsr-quiet{font-size:12.5px;line-height:1.5}
#dossierView .dsr-facts{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 12px;margin:16px 0;font-size:12.5px}
#dossierView .dsr-facts dt{color:var(--dsr-faint)}
#dossierView .dsr-facts dd{margin:0;color:var(--dsr-ink);overflow-wrap:anywhere}
#dossierView .dsr-mono dd{font:11.5px ui-monospace,Consolas,monospace;color:#bfe9f5}
#dossierView .dsr-adv{margin-top:10px;border-top:1px solid var(--dsr-rule);padding-top:10px}
#dossierView .dsr-adv summary{cursor:pointer;font-size:12.5px;color:var(--dsr-soft)}
#dossierView .dsr-foot{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:34px;padding:6px 18px;border-top:1px solid var(--dsr-rule);font-size:12px;color:var(--dsr-faint)}
#dossierView .dsr-status{font-variant-numeric:tabular-nums;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#dossierView .dsr-hint{flex:none}
#dossierView[data-ctx-drawer="1"] .dsr-ctx{position:absolute;right:0;top:0;bottom:0;z-index:2;box-shadow:-24px 0 48px -24px rgba(0,0,0,.8)}
#dossierView[data-ctx-drawer="1"] .dsr-body{position:relative;grid-template-columns:var(--dsr-org-w,232px) minmax(0,1fr)}
@media(max-width:1279px){#dossierView{--dsr-org-w:232px}#dossierView .dsr-hint{display:none}}
@media(max-width:899px){
  #dossierView .dsr-head{flex-wrap:wrap;gap:8px;padding:8px 10px}
  #dossierView .dsr-title{order:1;flex:1 1 0;min-width:0;font-size:15px;gap:8px}
  #dossierView .dsr-word{display:none}
  #dossierView .dsr-textarea{min-height:40vh}
  #dossierView .dsr-org-toggle{display:inline-flex;order:0}
  #dossierView .dsr-search{order:3;flex:1 1 100%}
  #dossierView .dsr-close{order:2;padding:0 10px}
  #dossierView .dsr-btn,#dossierView .dsr-close{min-height:36px;min-width:36px;justify-content:center}
  #dossierView .dsr-close .dsr-btn-label,#dossierView .dsr-close .dsr-kbd,#dossierView .dsr-btn .dsr-btn-label{display:none}
  #dossierView #dsrCtxToggle{order:2}
  #dossierView .dsr-body,#dossierView[data-ctx-drawer="1"] .dsr-body{position:relative;grid-template-columns:minmax(0,1fr)}
  #dossierView .dsr-org{display:none;position:absolute;left:0;top:0;bottom:0;z-index:2;width:min(300px,86vw);box-shadow:24px 0 48px -24px rgba(0,0,0,.8)}
  #dossierView[data-org=open] .dsr-org{display:block}
  #dossierView .dsr-ctx{width:min(320px,90vw)}
  #dossierView .dsr-browse,#dossierView .dsr-doc{padding:16px 14px 40px}
  #dossierView .dsr-doc-title{font-size:21px}
  #dossierView .dsr-prose{font-size:16px}
  #dossierView .dsr-edit-panes[data-split="2"]{grid-template-columns:minmax(0,1fr)}
  #dossierView .dsr-foot{padding:6px 10px}
}
@media(prefers-reduced-motion:reduce){#dossierView *{transition:none!important}}
@media(forced-colors:active){#dossierView .dsr-btn,#dossierView .dsr-close,#dossierView .dsr-tab{border-color:CanvasText}}`;
    const style=document.createElement('style');style.id='dsrStyle';style.textContent=css;document.head.appendChild(style);
  }
})(typeof globalThis!=='undefined'?globalThis:this);
