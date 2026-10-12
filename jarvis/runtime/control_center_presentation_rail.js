/* Rail permanent des présentations (refonte du display du mode présentation).

   Une colonne discrète, à DROITE de la palette d'outils du bord gauche (`#barehandsPalette`, 64 px à 18 px du bord), qui liste TOUTES les
   présentations : une vignette (monogramme coloré), un titre court et une pastille d'état. Plusieurs présentations vivent en parallèle ;
   un agent peut en corriger une pendant que l'utilisateur en regarde une autre.

   Pastille : bleu = un agent travaille dessus, vert = terminé (aussi : personne n'y a touché), orange = un problème est survenu
   (reste jusqu'à l'acquittement ou au prochain travail). L'état de travail est tenu par Core en mémoire (`work`), jamais ici.

   Ce que ce module est :
   - une VUE de `GET /api/presentation-studio/rail` (relais de Core), sondée par le module lui-même (2 s quand un agent travaille, 4 s au
     repos, 20 s onglet caché). Aucune présentation n'est gardée ici : un geste (masquer, archiver, renommer) est une écriture de Core
     (`POST .../presentations/{id}/rail`, acteur `user` imposé par le relais) puis une relecture ; un échec est dit à l'écran ;
   - le lieu des gestes : clic = ouvrir Variantes sur la présentation (fenêtré, `JarvisStudioExplorer`), clic droit (ou touche Menu,
     Maj+F10) = menu Ouvrir les variantes / Remotion Studio… / Éditer / Présenter / Masquer ou Afficher / Renommer / Supprimer (archiver, restaurable, avec
     confirmation) ; une archivée ne propose que Restaurer. La fenêtre de présentation flottante (`JarvisPresentationWindow`) est
     RETIRÉE (native-studio-playback-fix Slice 09) : Variantes est la seule surface, et une présentation lancée d'ici s'y montre ;
   - le récepteur des demandes d'écran du cerveau (`ui.request` : montrer ou masquer le rail), et le rapporteur de ce que la page
     constate (`POST .../rail/display-state` : rail visible, Variantes ouvert et sur quelle présentation), pour que
     `presentation_inspect target rail` ne devine rien.

   Quand il est visible : dans un Board de nature « présentation », en mode d'interaction PRESENTATION, dès qu'un agent travaille ou qu'un
   problème attend, quand Variantes est ouvert, ou si l'utilisateur l'a épinglé (Alt+Maj+P : automatique, toujours visible, masqué). Épinglé « masqué », il
   ne se montre que sur demande du cerveau. Pendant le Studio (explorateur de variantes, fenêtré) il se range en colonne à gauche de
   l'explorateur, hors de la zone rendue inerte : la voix et le rail restent utilisables.

   Rien ne s'ouvre tout seul : la pastille bleue dit qu'un agent travaille (la « concentration » qui ouvrait la fenêtre retirée est retirée
   avec elle, Slice 09 ; décision d'agent 0 : un indicateur du rail seulement).

   Tout texte d'auteur (titre) passe par `textContent`. Chaque échec est journalisé (`[presentation-rail] <clé> {json}`) et dit à l'écran. */
(function(root){
  'use strict';

  const DOM=Object.freeze({hostId:'presentationRail',styleId:'presentationRailStyle'});
  const ROUTE='/api/presentation-studio/rail';
  const STATE_ROUTE=ROUTE+'/display-state';
  const act=pid=>`/api/presentation-studio/presentations/${encodeURIComponent(pid)}/rail`;
  const ID_PRESENTATION=/^pst_[0-9a-f]{32}$/;
  const STORAGE_KEY='jarvis.presentationRail.v1';
  const STATE_LABEL=Object.freeze({working:'Un agent travaille dessus',done:'Terminé',problem:'Un problème est survenu'});
  const STATE_COLOR=Object.freeze({working:'#4aa3ff',done:'#43d68c',problem:'#ffa23a'});
  const POLL_BUSY_MS=2000,POLL_IDLE_MS=4000,POLL_HIDDEN_MS=20000,REPORT_EVERY_MS=15000,REQUEST_TIMEOUT_MS=8000,NOTICE_MS=6000;
  const TITLE_SHORT=22;
  const STUDIO_WIDTH_PX=188;
  const SLIM_BELOW_PX=1100;
  /* Sous cette largeur le Studio garde tout l'écran : le rail se retire le temps du Studio (il revient à sa fermeture). */
  const HIDE_IN_STUDIO_BELOW_PX=900;
  const RAIL_LEFT_PX=94;

  function cleanLine(value,max){
    const text=String(value==null?'':value).replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]+/g,' ').replace(/\s+/g,' ').trim();
    return max&&text.length>max?text.slice(0,Math.max(1,max-1))+'…':text;
  }
  function monogram(title){
    const words=cleanLine(title,80).split(' ').filter(Boolean);
    const letters=words.length>1?words[0][0]+words[1][0]:(words[0]||'?').slice(0,2);
    return letters.toUpperCase();
  }
  function hueOf(id){let h=0;const s=String(id||'');for(let i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))>>>0;return h%360}
  function stateOf(row){const s=row&&row.work&&row.work.state;return s==='working'||s==='problem'?s:'done'}

  /* Le modèle pur : trois groupes (visibles, masquées, archivées), l'état le plus pressant du rail, ce qui travaille. */
  function modelOf(rows,pref){
    const list=Array.isArray(rows)?rows.filter(r=>r&&typeof r.presentation_id==='string'&&ID_PRESENTATION.test(r.presentation_id)):[];
    const visible=list.filter(r=>!r.hidden&&!r.archived),hidden=list.filter(r=>r.hidden&&!r.archived),archived=list.filter(r=>r.archived);
    const live=list.filter(r=>!r.archived);
    const working=live.filter(r=>stateOf(r)==='working'),problems=live.filter(r=>stateOf(r)==='problem');
    return {visible,hidden,archived,working,problems,total:list.length,pref:pref||'auto'};
  }
  /* Visible ? (pur) */
  function shouldShow(model,ctx){
    const c=ctx||{};
    if(c.pref==='hidden')return false;
    if(c.pref==='shown')return true;
    if(!model.total)return false;
    return !!(c.boardKind==='presentation'||c.mode==='presentation'||model.working.length||model.problems.length||c.studioOpen);
  }
  function menuModel(row,ctx){
    const c=ctx||{};
    if(row.archived)return [{act:'restore',label:'Restaurer'}];
    const items=[
      {act:'open',label:'Ouvrir les variantes',note:c.playing&&!c.playingThis?'Une autre présentation est en cours : Variantes la montre.':null},
      /* native-studio-playback-fix Slice 11 (§ 1): Variants on the active variant, then Remotion Studio on the scene on screen, after the confirmation. */
      {act:'studio',label:'Remotion Studio…',note:c.playing?'Une présentation est en cours : Remotion Studio s’ouvre à son arrêt.':null},
      {act:'edit',label:'Éditer',note:c.playing?'Une présentation est en cours : l’inspecteur est indisponible.':null},
      {act:'play',label:'Présenter',note:c.playing?'Une présentation est déjà en cours.':null},
      '-',
      {act:row.hidden?'show':'hide',label:row.hidden?'Afficher dans le rail':'Masquer dans le rail'},
      {act:'rename',label:'Renommer…'}];
    if(stateOf(row)==='problem')items.push({act:'ack',label:'Acquitter le problème'});
    items.push('-',{act:'archive',label:'Supprimer…',danger:true,note:c.playingThis?'Cette présentation est jouée : arrêtez la lecture d’abord.':null});
    return items;
  }

  const CSS=`
#${DOM.hostId}{--jvr-ink:#d8edf7;--jvr-mute:#7190a0;--jvr-line:rgba(110,231,255,.18);--jvr-bg:rgba(3,8,12,.78);position:fixed;z-index:30;top:76px;left:${RAIL_LEFT_PX}px;width:158px;max-height:calc(100vh - 150px);display:flex;flex-direction:column;
  gap:2px;padding:6px;background:var(--jvr-bg);border:1px solid var(--jvr-line);border-radius:10px;backdrop-filter:blur(10px);color:var(--jvr-ink);font:12px ui-monospace,SFMono-Regular,Consolas,monospace;
  box-shadow:0 8px 30px rgba(0,0,0,.35);user-select:none}
#${DOM.hostId}[hidden]{display:none}
#${DOM.hostId} *{box-sizing:border-box}
#${DOM.hostId} button{font:inherit;color:inherit;cursor:pointer;background:none;border:0;padding:0}
#${DOM.hostId} .jvr-head{display:flex;align-items:center;gap:6px;padding:2px 4px 6px;color:var(--jvr-mute);letter-spacing:.14em;font-size:10px}
#${DOM.hostId} .jvr-title{flex:1;text-transform:uppercase;white-space:nowrap}
#${DOM.hostId} .jvr-voice{flex:none;width:9px;height:9px;border-radius:50%;border:1px solid #5b7686;background:transparent}
#${DOM.hostId} .jvr-voice[data-v=listening]{background:#6ee7ff;border-color:#6ee7ff;box-shadow:0 0 6px #6ee7ff}#${DOM.hostId} .jvr-voice[data-v=speaking],#${DOM.hostId} .jvr-voice[data-v=thinking]{background:#a78bfa;border-color:#a78bfa;box-shadow:0 0 6px #a78bfa}
#${DOM.hostId} .jvr-voice[data-v="hors ligne"]{border-style:dashed;opacity:.6}
#${DOM.hostId} .jvr-tool{width:20px;height:20px;border-radius:5px;color:var(--jvr-mute);display:grid;place-items:center;font-size:12px}
#${DOM.hostId} .jvr-tool:hover,#${DOM.hostId} .jvr-tool[aria-pressed=true]{color:var(--jvr-ink);background:rgba(110,231,255,.12)}
#${DOM.hostId} .jvr-list{list-style:none;margin:0;padding:0;overflow:auto;display:flex;flex-direction:column;gap:2px;min-height:0}
#${DOM.hostId} .jvr-item{display:flex;align-items:center;gap:8px;width:100%;padding:4px 6px 4px 4px;border-radius:7px;text-align:left;position:relative;border:1px solid transparent}
#${DOM.hostId} .jvr-item:hover{background:rgba(110,231,255,.08)}
#${DOM.hostId} .jvr-item:focus-visible{outline:2px solid #6ee7ff;outline-offset:1px}
#${DOM.hostId} .jvr-item[data-open=true]{border-color:rgba(110,231,255,.35);background:rgba(110,231,255,.1)}
#${DOM.hostId} .jvr-item[data-dim=true]{opacity:.55}
#${DOM.hostId} .jvr-thumb{flex:0 0 auto;width:28px;height:28px;border-radius:7px;display:grid;place-items:center;font-weight:700;font-size:11px;color:#fff;letter-spacing:.02em;
  background:linear-gradient(135deg,hsl(var(--h) 60% 38%),hsl(calc(var(--h) + 40) 55% 24%));border:1px solid rgba(255,255,255,.12)}
#${DOM.hostId} .jvr-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${DOM.hostId} .jvr-dot{flex:0 0 auto;width:9px;height:9px;border-radius:50%;background:var(--c);box-shadow:0 0 0 2px rgba(0,0,0,.35)}
#${DOM.hostId} .jvr-item[data-state=working] .jvr-dot{animation:jvr-pulse 1.3s ease-in-out infinite;box-shadow:0 0 8px var(--c)}
#${DOM.hostId} .jvr-item[data-state=problem] .jvr-dot{box-shadow:0 0 8px var(--c)}
@keyframes jvr-pulse{50%{opacity:.35;transform:scale(.8)}}
@media (prefers-reduced-motion:reduce){#${DOM.hostId} .jvr-item[data-state=working] .jvr-dot{animation:none}}
#${DOM.hostId} .jvr-fold{display:flex;align-items:center;gap:6px;padding:4px 6px;color:var(--jvr-mute);font-size:10px;letter-spacing:.08em;text-transform:uppercase;text-align:left;width:100%;border-top:1px solid var(--jvr-line);margin-top:3px}
#${DOM.hostId} .jvr-fold:hover{color:var(--jvr-ink)}
#${DOM.hostId} .jvr-empty,#${DOM.hostId} .jvr-note{padding:6px;color:var(--jvr-mute);font-size:11px;line-height:1.35}
#${DOM.hostId} .jvr-note[data-kind=failed]{color:#ffa23a}
#${DOM.hostId}[data-collapsed=true]{width:44px}
#${DOM.hostId}[data-collapsed=true] .jvr-name,#${DOM.hostId}[data-collapsed=true] .jvr-title,#${DOM.hostId}[data-collapsed=true] .jvr-voice,#${DOM.hostId}[data-collapsed=true] .jvr-fold span,#${DOM.hostId}[data-collapsed=true] .jvr-tool[data-role=focus]{display:none}
#${DOM.hostId}[data-collapsed=true] .jvr-item{padding:4px}
#${DOM.hostId}[data-collapsed=true] .jvr-thumb{position:relative}
#${DOM.hostId}[data-collapsed=true] .jvr-dot{position:absolute;right:3px;top:3px;width:8px;height:8px}
html.jvr-studio #${DOM.hostId}{z-index:9100;top:8px;left:8px;bottom:8px;max-height:none;width:${STUDIO_WIDTH_PX-16}px;background:rgba(3,8,12,.92)}
html.jvr-studio #${DOM.hostId} .jvr-list{flex:1 1 auto}
html.jvr-studio #jvStudioExplorer:not(:fullscreen){left:${STUDIO_WIDTH_PX}px}
html.jvr-studio.jvr-slim #jvStudioExplorer:not(:fullscreen){left:60px}
html.jvr-studio.jvr-slim #${DOM.hostId}{width:44px}
.jvr-menu{position:fixed;z-index:9300;min-width:190px;padding:5px;background:rgba(6,12,18,.97);border:1px solid rgba(110,231,255,.28);border-radius:9px;box-shadow:0 14px 40px rgba(0,0,0,.55);
  color:#d8edf7;font:12px ui-monospace,SFMono-Regular,Consolas,monospace}
.jvr-menu[hidden]{display:none}
.jvr-menu .jvr-mhead{padding:4px 8px 6px;color:#7190a0;font-size:10px;letter-spacing:.12em;text-transform:uppercase;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.jvr-menu button{display:block;width:100%;text-align:left;padding:6px 8px;border-radius:6px;background:none;border:0;color:inherit;font:inherit;cursor:pointer}
.jvr-menu button:hover,.jvr-menu button:focus-visible{background:rgba(110,231,255,.14);outline:0}
.jvr-menu button[data-danger]{color:#ff8a98}.jvr-menu button[aria-disabled=true]{opacity:.45;cursor:default}
.jvr-menu .jvr-sep{height:1px;margin:4px 2px;background:rgba(110,231,255,.16)}
.jvr-dialog-back{position:fixed;inset:0;z-index:9400;background:rgba(0,0,0,.5);display:grid;place-items:center}
.jvr-dialog-back[hidden]{display:none}
.jvr-dialog{width:min(420px,calc(100vw - 32px));padding:16px;background:#070d13;border:1px solid rgba(110,231,255,.3);border-radius:12px;color:#d8edf7;font:13px ui-monospace,SFMono-Regular,Consolas,monospace;box-shadow:0 20px 60px rgba(0,0,0,.6)}
.jvr-dialog h2{margin:0 0 8px;font-size:14px;font-weight:700}.jvr-dialog p{margin:0 0 12px;color:#9db6c4;line-height:1.45}
.jvr-dialog input{width:100%;padding:8px 10px;margin-bottom:12px;background:#04080c;border:1px solid rgba(110,231,255,.28);border-radius:7px;color:inherit;font:inherit}
.jvr-dialog .jvr-row{display:flex;gap:8px;justify-content:flex-end}
.jvr-dialog button{padding:7px 12px;border-radius:7px;background:rgba(110,231,255,.1);border:1px solid rgba(110,231,255,.3);color:inherit;font:inherit;cursor:pointer}
.jvr-dialog button[data-danger]{background:rgba(255,101,119,.14);border-color:rgba(255,101,119,.5);color:#ff9aa6}
`;

  function createRail(deps){
    const d=deps||{};
    const doc=d.document||root.document;
    const win=d.window||root;
    const fetchImpl=d.fetch||(typeof root.fetch==='function'?root.fetch.bind(root):null);
    const later=d.setTimeout||((fn,ms)=>setTimeout(fn,ms));
    const cancelLater=d.clearTimeout||(id=>clearTimeout(id));
    const now=d.now||(()=>Date.now());
    const sink=d.console||root.console;
    const S={coreOk:false,rows:[],loaded:false,lost:false,pref:'auto',collapsed:false,boardKind:null,mode:null,voice:'idle',foldHidden:false,foldArchived:false,
      lastSeq:null,firstPoll:true,studioOpen:false,notice:null,busy:new Set(),playing:null,selected:null,menuRow:null,dialog:null,lastReport:'',lastReportAt:0};
    const ui={};
    let pollTimer=null,reportTimer=null,noticeTimer=null,polling=false,destroyed=false,failures=0;

    function storage(){try{return d.storage||root.localStorage||null}catch(_e){return null /* intentional: blocked storage only costs the remembered layout */}}
    function load(){
      try{const raw=storage()&&storage().getItem(STORAGE_KEY);if(!raw)return;const v=JSON.parse(raw);
        if(v&&(v.pref==='auto'||v.pref==='shown'||v.pref==='hidden'))S.pref=v.pref;
        if(v&&typeof v.collapsed==='boolean')S.collapsed=v.collapsed;
        if(v&&typeof v.foldHidden==='boolean')S.foldHidden=v.foldHidden;if(v&&typeof v.foldArchived==='boolean')S.foldArchived=v.foldArchived}
      catch(_e){/* intentional: corrupt remembered layout -> defaults */}
    }
    function save(){try{if(storage())storage().setItem(STORAGE_KEY,JSON.stringify({pref:S.pref,collapsed:S.collapsed,foldHidden:S.foldHidden,foldArchived:S.foldArchived}))}catch(_e){/* intentional */}}
    function log(key,data,level){
      const line=`[presentation-rail] ${key} ${JSON.stringify(data||{})}`;
      try{if(sink){if(level==='error')sink.error(line);else if(level==='warn')sink.warn(line);else sink.info(line)}}catch(_e){/* intentional */}
    }
    function el(tag,cls,text){const n=doc.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n}
    function clear(n){while(n.firstChild)n.removeChild(n.firstChild)}

    async function call(method,path,body,timeoutMs){
      if(!fetchImpl)throw Object.assign(new Error('fetch indisponible'),{code:'network'});
      const controller=typeof AbortController==='function'?new AbortController():null;
      let timedOut=false;const timer=later(()=>{timedOut=true;if(controller)controller.abort()},timeoutMs||REQUEST_TIMEOUT_MS);
      try{
        const init={method,cache:'no-store'};if(controller)init.signal=controller.signal;
        if(body!==undefined){init.body=JSON.stringify(body);init.headers={'Content-Type':'application/json'}}
        const response=await fetchImpl(path,init);
        let payload=null;try{payload=await response.json()}catch(_e){payload=null /* intentional: reported by status below */}
        if(!response.ok){const e=payload&&payload.error||{};throw Object.assign(new Error(e.message||(payload&&typeof payload.error==='string'?payload.error:`HTTP ${response.status}`)),{status:response.status,code:e.code||`http_${response.status}`})}
        return payload;
      }catch(error){
        if(error&&error.code)throw error;
        throw Object.assign(new Error(timedOut?'aucune réponse à temps':String(error&&error.message||error)),{code:timedOut?'timeout':'network'});
      }finally{cancelLater(timer)}
    }

    /* ------------------------------------------------------------ Variantes, lecture, inspecteur : les voisins, lus à la demande */
    const explorerApi=()=>d.explorer||root.JarvisStudioExplorer||null;
    const playerApi=()=>d.player||root.JarvisStudioPlayer||null;
    const inspectorApi=()=>d.inspector||(root.JarvisStudioInspector&&root.JarvisStudioInspector.instance)||null;
    /* The presentation Variants shows, when it is open (the retired window host's `pid`, Slice 09). */
    function variantsPid(){
      const ex=explorerApi();
      try{return ex&&typeof ex.isOpen==='function'&&ex.isOpen()&&typeof ex.state==='function'?ex.state().presentation_id||null:null}
      catch(_error){return null /* intentional: an explorer that cannot answer shows nothing to the rail */}
    }
    function runActive(){
      const p=playerApi(),v=p&&typeof p.view==='function'?p.view():null;
      return !!v&&v.running===true&&v.phase!=='stopped'&&v.phase!=='idle';
    }
    function playingId(){const v=playerApi()&&typeof playerApi().view==='function'?playerApi().view():null;return v&&v.running===true&&v.presentation_id?v.presentation_id:null}

    /* ------------------------------------------------------------ rendu */
    function model(){return modelOf(S.rows,S.pref)}
    function shown(){
      if(S.studioOpen&&(Number(win.innerWidth)||1280)<HIDE_IN_STUDIO_BELOW_PX&&S.pref!=='shown')return false;
      return shouldShow(model(),{pref:S.pref,boardKind:S.boardKind,mode:S.mode,studioOpen:S.studioOpen})}
    function build(){
      if(ui.host)return ui.host;
      if(!doc.getElementById(DOM.styleId)){const style=el('style');style.id=DOM.styleId;style.textContent=CSS;(doc.head||doc.documentElement).appendChild(style)}
      const host=doc.getElementById(DOM.hostId)||(()=>{const n=el('div');n.id=DOM.hostId;doc.body.appendChild(n);return n})();
      host.hidden=true;host.setAttribute('role','navigation');host.setAttribute('aria-label','Présentations');host.setAttribute('data-keep-live','true');
      const head=el('div','jvr-head');
      ui.title=el('span','jvr-title','Présentations');
      ui.voice=el('span','jvr-voice');ui.voice.setAttribute('role','status');
      ui.collapseBtn=el('button','jvr-tool','‹');ui.collapseBtn.type='button';
      ui.collapseBtn.addEventListener('click',()=>{S.collapsed=!S.collapsed;save();render()});
      head.append(ui.title,ui.voice,ui.collapseBtn);
      ui.list=el('ul','jvr-list');ui.list.setAttribute('role','listbox');ui.list.setAttribute('aria-label','Présentations');
      ui.hiddenFold=el('div');ui.archivedFold=el('div');
      ui.note=el('div','jvr-note');ui.note.setAttribute('role','status');ui.note.setAttribute('aria-live','polite');
      ui.note.addEventListener('click',()=>{if(S.notice){S.notice=null;render()}});
      host.append(head,ui.list,ui.hiddenFold,ui.archivedFold,ui.note);
      ui.menu=el('div','jvr-menu');ui.menu.hidden=true;ui.menu.setAttribute('role','menu');ui.menu.setAttribute('data-keep-live','true');
      ui.back=el('div','jvr-dialog-back');ui.back.hidden=true;ui.back.setAttribute('data-keep-live','true');
      doc.body.append(ui.menu,ui.back);
      host.addEventListener('keydown',onKey);
      ui.menu.addEventListener('keydown',onMenuKey);
      ui.menu.addEventListener('mousedown',e=>e.preventDefault());
      doc.addEventListener('mousedown',e=>{if(S.menuRow&&!ui.menu.contains(e.target))closeMenu(false)},true);
      ui.host=host;
      return host;
    }
    function itemFor(row,opts){
      const li=el('li');li.setAttribute('role','none');
      const b=el('button','jvr-item');b.type='button';b.setAttribute('role','option');b.dataset.id=row.presentation_id;
      const st=stateOf(row);
      b.dataset.state=st;
      const open=variantsPid()===row.presentation_id;
      b.dataset.open=String(open);b.setAttribute('aria-selected',String(open));
      if(opts&&opts.dim)b.dataset.dim='true';
      const thumb=el('span','jvr-thumb',monogram(row.title));thumb.style.setProperty('--h',String(hueOf(row.presentation_id)));thumb.setAttribute('aria-hidden','true');
      const name=el('span','jvr-name',cleanLine(row.title,TITLE_SHORT));name.setAttribute('dir','auto');
      const dot=el('span','jvr-dot');dot.style.setProperty('--c',STATE_COLOR[st]);dot.setAttribute('aria-hidden','true');
      b.append(thumb,name,dot);
      const detail=st==='problem'&&row.work&&row.work.message?` — ${cleanLine(row.work.message,120)}`:'';
      b.title=`${cleanLine(row.title,80)}\n${STATE_LABEL[st]}${detail}${row.hidden?'\nMasquée du rail':''}${row.archived?'\nArchivée (restaurable)':''}`;
      b.setAttribute('aria-label',`${cleanLine(row.title,80)} : ${STATE_LABEL[st].toLowerCase()}${row.hidden?', masquée':''}${row.archived?', archivée':''}`);
      b.addEventListener('click',()=>{if(row.archived){openMenuFor(row,b);return}openRow(row.presentation_id,'click')});
      b.addEventListener('contextmenu',e=>{e.preventDefault();openMenuFor(row,b,e.clientX,e.clientY)});
      li.appendChild(b);return li;
    }
    function foldButton(label,count,open,onToggle){
      const b=el('button','jvr-fold');b.type='button';b.setAttribute('aria-expanded',String(open));
      b.append(el('span','',open?'▾':'▸'),el('span','',`${label} (${count})`));
      b.addEventListener('click',onToggle);return b;
    }
    function render(){
      if(destroyed)return;
      build();
      const m=model(),visible=shown();
      ui.host.hidden=!visible;
      /* Studio sur un écran étroit : le rail se range en bande de vignettes (le Studio garde de quoi lire son aperçu). */
      const slim=S.collapsed||(S.studioOpen&&(Number(win.innerWidth)||1280)<SLIM_BELOW_PX);
      ui.host.dataset.collapsed=String(slim);
      ui.collapseBtn.textContent=S.collapsed?'›':'‹';ui.collapseBtn.setAttribute('aria-label',S.collapsed?'Déplier le rail':'Replier le rail');
      ui.voice.dataset.v=S.voice||'idle';ui.voice.setAttribute('aria-label',`Voix : ${S.voice||'idle'}`);ui.voice.title=`Voix de Jarvis : ${S.voice||'idle'} (elle reste utilisable pendant l’affichage)`;
      clear(ui.list);
      if(!S.loaded&&!S.lost)ui.list.appendChild(el('li','jvr-empty','Chargement…'));
      else if(!m.visible.length)ui.list.appendChild(el('li','jvr-empty',m.total?'Toutes sont masquées ou archivées.':'Aucune présentation.'));
      for(const row of m.visible)ui.list.appendChild(itemFor(row));
      clear(ui.hiddenFold);clear(ui.archivedFold);
      if(m.hidden.length){
        ui.hiddenFold.appendChild(foldButton('Masquées',m.hidden.length,S.foldHidden,()=>{S.foldHidden=!S.foldHidden;save();render()}));
        if(S.foldHidden){const ul=el('ul','jvr-list');for(const row of m.hidden)ul.appendChild(itemFor(row,{dim:true}));ui.hiddenFold.appendChild(ul)}
      }
      if(m.archived.length){
        ui.archivedFold.appendChild(foldButton('Archivées',m.archived.length,S.foldArchived,()=>{S.foldArchived=!S.foldArchived;save();render()}));
        if(S.foldArchived){const ul=el('ul','jvr-list');for(const row of m.archived)ul.appendChild(itemFor(row,{dim:true}));ui.archivedFold.appendChild(ul)}
      }
      const note=S.lost?{kind:'failed',text:'Rail injoignable : l’état affiché n’est plus confirmé.'}:S.notice;
      ui.note.hidden=!note;ui.note.textContent=note?note.text:'';ui.note.dataset.kind=note?note.kind:'';
      ui.note.title=note&&!S.lost?'Cliquer pour masquer ce message':'';
      doc.documentElement.classList.toggle('jvr-studio',!!(S.studioOpen&&visible));
      doc.documentElement.classList.toggle('jvr-slim',!!(S.studioOpen&&visible&&slim));
      syncStudioInset(visible);
      reportSoon();
    }
    function syncStudioInset(visible){
      const html=doc.documentElement;
      if(html&&html.style)html.style.setProperty('--jvr-width',visible&&S.studioOpen?`${S.collapsed?60:STUDIO_WIDTH_PX}px`:'0px');
    }
    function say(kind,text){
      S.notice={kind,text};
      if(noticeTimer)cancelLater(noticeTimer);
      noticeTimer=kind==='failed'?null:later(()=>{S.notice=null;render()},NOTICE_MS);
      render();
    }

    /* ------------------------------------------------------------ données */
    async function refresh(){
      if(polling||destroyed)return;
      polling=true;
      try{
        const answer=await call('GET',ROUTE);
        failures=0;S.lost=false;
        S.rows=Array.isArray(answer&&answer.presentations)?answer.presentations:[];
        S.playing=answer&&answer.playing||null;
        S.loaded=true;
        S.reportWanted=!!(answer&&answer.ui&&(answer.ui.request||answer.ui.reported));
        applyUiRequest(answer&&answer.ui);
        S.firstPoll=false;
        render();
      }catch(error){
        failures+=1;
        if(failures===1||failures%10===0)log('poll_failed',{code:error.code,message:cleanLine(error.message,120),failures},'warn');
        if(failures>=2&&!S.lost){S.lost=true;render()}
      }finally{polling=false}
    }
    function applyUiRequest(uiBlock){
      const request=uiBlock&&uiBlock.request;
      if(!request)return;
      if(S.lastSeq!==null&&request.seq<=S.lastSeq)return;
      const apply=request.fresh===true;
      S.lastSeq=request.seq;
      if(!apply)return;
      log('ui_request',{seq:request.seq,action:request.action});
      if(request.action==='show_rail'){S.pref='shown';save()}
      else if(request.action==='hide_rail'){S.pref='hidden';save()}
      reportSoon(true);
    }
    function reportSoon(immediate){
      if(destroyed)return;
      if(!S.coreOk)return;
      const body=reportBody(),key=JSON.stringify(body);
      /* Seul un CHANGEMENT part (le constat de départ est la ligne de base, jamais envoyé), puis un battement toutes les 15 s tant qu'un agent a déjà demandé ou lu l'écran. */
      if(S.lastReport===''){S.lastReport=key;S.lastReportAt=now();if(!immediate)return}
      if(!immediate&&key===S.lastReport&&!(S.reportWanted&&now()-S.lastReportAt>=REPORT_EVERY_MS))return;
      if(reportTimer)cancelLater(reportTimer);
      reportTimer=later(()=>{reportTimer=null;reportNow()},immediate?0:400);
    }
    function reportBody(){
      const shown=variantsPid();
      return {rail_visible:!!(ui.host&&!ui.host.hidden),variants_open:!!shown,presentation_id:shown||null,applied_seq:S.lastSeq};
    }
    async function reportNow(){
      const body=reportBody();
      try{await call('POST',STATE_ROUTE,body,4000);S.lastReport=JSON.stringify(body);S.lastReportAt=now()}
      catch(error){log('report_failed',{code:error.code})}
    }

    /* ------------------------------------------------------------ gestes */
    const rowOf=id=>S.rows.find(r=>r.presentation_id===id)||null;
    /* A row's click, « Ouvrir les variantes », « Éditer »: Variants, windowed (the rail and the voice stay usable), on the active variant. */
    function openRow(id,via){
      const row=rowOf(id);
      if(row&&row.archived){say('failed','Archivée : restaurez-la d’abord.');return false}
      const ex=explorerApi();
      if(!ex||typeof ex.open!=='function'){say('failed','Variantes n’est pas chargé dans cette page.');return false}
      Promise.resolve(ex.open({presentation_id:id,fullscreen:false,via:'rail'})).then(result=>{
        if(result&&result.state==='refused')say('failed',result.reason||result.code||'Variantes refusé.');
        render();reportSoon(true);
      }).catch(error=>{log('variants_open_failed',{via,error:cleanLine(error&&error.message,120)},'error');say('failed',`Ouverture impossible : ${cleanLine(error&&error.message,100)}`)});
      return true;
    }
    /* « Remotion Studio… » (§ 1, Slice 11): Variants opens on the presentation, then its « Remotion Studio » door on the scene on screen (the
       confirmation names the scene; « Annuler » launches nothing). Remotion Studio's state and failures are said in Variants. */
    async function remotionStudio(id){
      const row=rowOf(id);
      if(row&&row.archived){say('failed','Archivée : restaurez-la d’abord.');return null}
      const ex=explorerApi();
      if(!ex||typeof ex.open!=='function'||!ex.remotionStudio||typeof ex.remotionStudio.open!=='function'){say('failed','Variantes n’est pas chargé dans cette page.');return null}
      try{
        const opened=await ex.open({presentation_id:id,fullscreen:false,via:'rail'});
        render();reportSoon(true);
        if(opened&&opened.state==='refused'){say('failed',opened.reason||opened.code||'Variantes refusé.');return opened}
        const result=await ex.remotionStudio.open({via:'rail'});
        log('remotion_studio_from_rail',{state:result&&result.state});
        return result;
      }catch(error){
        log('remotion_studio_from_rail_failed',{error:cleanLine(error&&error.message,120)},'error');
        say('failed',`Remotion Studio : ${cleanLine(error&&error.message,100)}`);
        return null;
      }
    }
    async function edit(id){
      const ins=inspectorApi();
      openRow(id,'edit');
      if(!ins||typeof ins.open!=='function'){say('failed','L’inspecteur n’est pas chargé dans cette page.');return}
      try{
        if(typeof ins.refresh==='function')await ins.refresh();
        if(typeof ins.selectPresentation==='function')await ins.selectPresentation(id,{});
        const opened=ins.open();
        if(opened===false)say('info','L’inspecteur est indisponible (lecture en cours ou plein écran).');
      }catch(error){log('edit_failed',{error:cleanLine(error&&error.message,120)},'error');say('failed',`Inspecteur : ${cleanLine(error&&error.message,100)}`)}
    }
    /* « Présenter » (§ 1, § 5): a `user_presenter` run, by the page's playback client; Variants opens on it and shows it. */
    async function play(id){
      const p=playerApi();
      const result=p&&typeof p.startRun==='function'?await p.startRun(id,'user_presenter'):null;
      if(!result)say('failed','Le client de lecture n’est pas chargé dans cette page.');
      else if(result.status==='applied')say('ok','Présentation lancée dans Variantes.');
      else say('failed',`Présentation impossible : ${cleanLine(result.message||result.reason||'refusée',140)}`);
      return result;
    }
    async function write(id,body,label){
      const key=id+':'+body.action;
      if(S.busy.has(key))return null;
      S.busy.add(key);
      try{
        const answer=await call('POST',act(id),body);
        log('rail_action',{action:body.action,presentation_id:id.slice(0,12),changed:answer&&answer.changed});
        if(S.notice&&S.notice.kind==='failed')S.notice=null;
        await refresh();
        return answer;
      }catch(error){
        log('rail_action_failed',{action:body.action,code:error.code,status:error.status},'error');
        say('failed',`${label||body.action} impossible : ${cleanLine(error.message,140)}${error.code?` (${error.code})`:''}`);
        return null;
      }finally{S.busy.delete(key)}
    }
    async function run(action,id){
      const row=rowOf(id);if(!row)return;
      if(action==='open')return openRow(id,'menu');
      if(action==='edit')return edit(id);
      if(action==='studio')return remotionStudio(id);
      if(action==='play')return play(id);
      if(action==='hide'||action==='show'){const a=await write(id,{action},action==='hide'?'Masquer':'Afficher');if(a)say('ok',action==='hide'?'Masquée du rail (menu Masquées pour la réafficher).':'Réaffichée dans le rail.');return}
      if(action==='ack')return write(id,{action:'acknowledge'},'Acquitter');
      if(action==='restore'){const a=await write(id,{action:'restore'},'Restaurer');if(a)say('ok','Restaurée.');return}
      if(action==='rename'){
        const value=await askText({title:'Renommer la présentation',value:row.title,confirmLabel:'Renommer'});
        if(value===null||cleanLine(value,80)===row.title)return;
        const a=await write(id,{action:'rename',title:cleanLine(value,80)},'Renommer');if(a)say('ok','Renommée.');
        return;
      }
      if(action==='archive'){
        const ok=await askConfirm({title:`Supprimer « ${cleanLine(row.title,40)} » ?`,
          body:'Elle quitte le rail et ne se lit plus. Rien n’est effacé : elle se restaure à tout moment (Archivées, en bas du rail).',confirmLabel:'Supprimer',danger:true});
        if(!ok)return;
        const ex=explorerApi();if(variantsPid()===id&&ex&&typeof ex.close==='function')ex.close({reason:'archived',quiet:true});
        const a=await write(id,{action:'archive'},'Supprimer');if(a)say('ok','Archivée : restaurable depuis « Archivées ».');
      }
    }

    /* ------------------------------------------------------------ menu contextuel et boîtes (propres au rail : elles doivent passer AU-DESSUS du Studio) */
    function openMenuFor(row,origin,x,y){
      closeMenu(false);
      const rect=origin.getBoundingClientRect();
      const items=menuModel(row,{playing:runActive(),playingThis:playingId()===row.presentation_id});
      S.menuRow={row,origin};
      clear(ui.menu);
      const head=el('div','jvr-mhead',cleanLine(row.title,40));ui.menu.appendChild(head);
      for(const it of items){
        if(it==='-'){ui.menu.appendChild(el('div','jvr-sep'));continue}
        const b=el('button','',it.label);b.type='button';b.setAttribute('role','menuitem');b.dataset.act=it.act;
        if(it.danger)b.setAttribute('data-danger','');
        if(it.note){b.setAttribute('aria-disabled','true');b.title=it.note}
        b.addEventListener('click',()=>{
          if(it.note){say('info',it.note);return}
          const target=S.menuRow&&S.menuRow.row;closeMenu(true);if(target)run(it.act,target.presentation_id);
        });
        ui.menu.appendChild(b);
      }
      ui.menu.hidden=false;
      const w=ui.menu.offsetWidth||200,h=ui.menu.offsetHeight||240,W=Number(win.innerWidth)||1280,H=Number(win.innerHeight)||800;
      const px=x!=null?x:rect.right-6,py=y!=null?y:rect.top;
      ui.menu.style.left=Math.max(8,Math.min(px,W-w-8))+'px';ui.menu.style.top=Math.max(8,Math.min(py,H-h-8))+'px';
      const first=ui.menu.querySelector('button:not([aria-disabled=true])');if(first)first.focus({preventScroll:true});
      log('menu_opened',{items:items.length});
    }
    function closeMenu(restore){
      const was=S.menuRow;S.menuRow=null;if(ui.menu){ui.menu.hidden=true;clear(ui.menu)}
      if(restore&&was&&was.origin&&was.origin.isConnected)was.origin.focus({preventScroll:true});
    }
    function onMenuKey(event){
      const buttons=Array.from(ui.menu.querySelectorAll('button'));const i=buttons.indexOf(doc.activeElement);
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeMenu(true)}
      else if(event.key==='ArrowDown'){event.preventDefault();buttons[(i+1)%buttons.length].focus()}
      else if(event.key==='ArrowUp'){event.preventDefault();buttons[(i-1+buttons.length)%buttons.length].focus()}
      else if(event.key==='Home'){event.preventDefault();buttons[0].focus()}
      else if(event.key==='End'){event.preventDefault();buttons[buttons.length-1].focus()}
      else if(event.key==='Tab'){closeMenu(false)}
    }
    function onKey(event){
      const item=event.target&&event.target.closest&&event.target.closest('.jvr-item');
      if(!item)return;
      const all=Array.from(ui.host.querySelectorAll('.jvr-item')),i=all.indexOf(item),row=rowOf(item.dataset.id);
      if(event.key==='ArrowDown'&&i<all.length-1){event.preventDefault();all[i+1].focus()}
      else if(event.key==='ArrowUp'&&i>0){event.preventDefault();all[i-1].focus()}
      else if(event.key==='ContextMenu'||(event.key==='F10'&&event.shiftKey)){event.preventDefault();if(row)openMenuFor(row,item)}
      else if(event.key==='F2'&&row&&!row.archived){event.preventDefault();run('rename',row.presentation_id)}
      else if(event.key==='Delete'&&row&&!row.archived){event.preventDefault();run('archive',row.presentation_id)}
    }
    function dialogShell(title,bodyText){
      const box=el('div','jvr-dialog');box.setAttribute('role','alertdialog');box.setAttribute('aria-modal','true');
      const h=el('h2','',title);h.id='jvrDialogTitle';box.setAttribute('aria-labelledby',h.id);box.appendChild(h);
      if(bodyText)box.appendChild(el('p','',bodyText));
      return box;
    }
    function showDialog(box,focusEl){
      clear(ui.back);ui.back.appendChild(box);ui.back.hidden=false;
      const previous=doc.activeElement;
      return new Promise(resolve=>{
        const finish=value=>{ui.back.hidden=true;clear(ui.back);ui.back.onkeydown=null;S.dialog=null;if(previous&&previous.isConnected&&previous.focus)previous.focus({preventScroll:true});resolve(value)};
        S.dialog={finish};
        ui.back.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();finish(null)}};
        ui.back.onmousedown=e=>{if(e.target===ui.back)finish(null)};
        box.__finish=finish;
        if(focusEl)focusEl.focus({preventScroll:true});
      });
    }
    function askText(spec){
      const box=dialogShell(spec.title,spec.body);
      const input=el('input');input.type='text';input.value=cleanLine(spec.value,80);input.maxLength=80;input.setAttribute('aria-label',spec.title);
      const row=el('div','jvr-row');const cancel=el('button','',spec.cancelLabel||'Annuler');cancel.type='button';
      const ok=el('button','',spec.confirmLabel||'Valider');ok.type='button';
      row.append(cancel,ok);box.append(input,row);
      const p=showDialog(box,input);
      cancel.addEventListener('click',()=>box.__finish(null));
      const submit=()=>{const v=cleanLine(input.value,80);if(!v){input.focus();return}box.__finish(v)};
      ok.addEventListener('click',submit);
      input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();submit()}});
      try{input.select()}catch(_e){/* intentional */}
      return p;
    }
    function askConfirm(spec){
      const box=dialogShell(spec.title,spec.body);
      const row=el('div','jvr-row');const cancel=el('button','',spec.cancelLabel||'Annuler');cancel.type='button';
      const ok=el('button','',spec.confirmLabel||'Confirmer');ok.type='button';if(spec.danger)ok.setAttribute('data-danger','');
      row.append(cancel,ok);box.appendChild(row);
      const p=showDialog(box,cancel);
      cancel.addEventListener('click',()=>box.__finish(false));
      ok.addEventListener('click',()=>box.__finish(true));
      return p.then(v=>v===true);
    }

    /* ------------------------------------------------------------ cycle de vie */
    function interval(){
      if(doc.hidden)return POLL_HIDDEN_MS;
      const m=model();return m.working.length||S.firstPoll?POLL_BUSY_MS:POLL_IDLE_MS;
    }
    /* Le rail ne sonde Core que lorsque le statut 1 Hz de la page dit que Core répond (`boards.available`) : une page sans Core (démarrage, panne, banc
       d'essai) n'envoie aucune requête vouée à l'échec et n'écrit rien dans la console. `S.coreOk` vient de `gate`. */
    function schedule(){
      if(destroyed)return;
      if(pollTimer)cancelLater(pollTimer);
      pollTimer=later(async()=>{pollTimer=null;if(S.coreOk)await refresh();schedule()},interval());
    }
    function start(){
      load();build();render();
      schedule();
      if(d.assumeCore){S.coreOk=true;refresh().then(()=>{render()})}
      doc.addEventListener('visibilitychange',()=>{if(!doc.hidden&&S.coreOk)refresh()});
      win.addEventListener&&win.addEventListener('resize',()=>{if(S.studioOpen)render()});
      win.addEventListener&&win.addEventListener('jarvis:studio-explorer-opened',()=>{S.studioOpen=true;render();reportSoon(true)});
      win.addEventListener&&win.addEventListener('jarvis:studio-explorer-closed',()=>{S.studioOpen=false;render();reportSoon(true)});
      log('installed',{});
    }
    function stop(){destroyed=true;for(const t of [pollTimer,reportTimer,noticeTimer])if(t)cancelLater(t);pollTimer=reportTimer=noticeTimer=null}

    /* Le statut 1 Hz de la page : Board actif (nature), mode d'interaction, état de la voix. Aucune autre vérité n'y est lue. */
    function gate(status){
      const s=status||{};
      const kind=s.boards&&s.boards.active&&s.boards.active.board_kind||null;
      const mode=s.interaction_mode&&s.interaction_mode.mode||null;
      const voice=s.voice_online===false?'hors ligne':String(s.voice_state||'idle');
      const coreOk=!!(s.boards&&s.boards.available===true);
      const wasOk=S.coreOk;
      S.coreOk=coreOk;
      if(coreOk&&!wasOk)refresh().then(()=>render());
      if(!coreOk&&wasOk&&S.loaded){S.lost=true}
      if(kind===S.boardKind&&mode===S.mode&&voice===S.voice&&coreOk===wasOk)return;
      S.boardKind=kind;S.mode=mode;S.voice=voice;render();
    }
    function setPref(value){if(value==='auto'||value==='shown'||value==='hidden'){S.pref=value;save();render();return true}return false}
    function cyclePref(){const order=['auto','shown','hidden'];setPref(order[(order.indexOf(S.pref)+1)%order.length]);return S.pref}

    return {start,stop,refresh,render,gate,setPref,cyclePref,run,openMenuFor,closeMenu,
      state:()=>({pref:S.pref,collapsed:S.collapsed,loaded:S.loaded,lost:S.lost,visible:!!(ui.host&&!ui.host.hidden),rows:S.rows.length,
        studioOpen:S.studioOpen,menuOpen:!!S.menuRow,dialogOpen:!!S.dialog,notice:S.notice}),
      model,host:()=>ui.host,rows:()=>S.rows.slice(),setStudio:on=>{S.studioOpen=!!on;render()}};
  }

  const API=Object.freeze({DOM,ROUTE,STATE_ROUTE,STATE_LABEL,STATE_COLOR,CSS,cleanLine,monogram,hueOf,stateOf,modelOf,shouldShow,menuModel,createRail});
  root.JarvisPresentationRailCore=API;
  if(typeof module!=='undefined'&&module.exports)module.exports=API;

  if(typeof window==='undefined'||typeof document==='undefined')return;
  function installRail(){
    const rail=createRail({document,window,toast:typeof toast==='function'?toast:null});
    root.JarvisPresentationRail=Object.freeze({gate:rail.gate,refresh:rail.refresh,state:rail.state,setPref:rail.setPref,cyclePref:rail.cyclePref,run:rail.run,
      model:rail.model,render:rail.render});
    /* Pas de bouton au dock (sa géométrie est comptée pour dix outils, y compris celle du thème Cosmos) : Alt+Maj+P fait tourner automatique / toujours visible / masqué. */
    document.addEventListener('keydown',event=>{
      if(!(event.altKey&&event.shiftKey&&!event.ctrlKey&&!event.metaKey&&(event.key==='P'||event.key==='p')))return;
      event.preventDefault();
      const pref=rail.cyclePref();
      if(typeof toast==='function')toast({title:'Rail des présentations',sub:pref==='auto'?'Automatique : visible dans un Board de présentation ou quand un agent travaille.':pref==='shown'?'Toujours visible.':'Masqué (le cerveau peut le rouvrir).',kind:'info'});
    });
    rail.start();
  }
  /* Rattrapé ici : la page servie n'a qu'une balise <script> ; une levée emporterait la scène avec elle. */
  try{installRail()}
  catch(error){console.error('[presentation-rail] install_failed '+JSON.stringify({error:String(error&&error.message||error)}))}
})(typeof window!=='undefined'?window:globalThis);
