/* Dossier plein écran — logique pure (handoff jarvis-board-ui-wheel-dossier-refactor, Slice 07).

   Contrat : `docs/dossier.md` › *Full-screen Dossier (UI)* ; registre de la
   coque : `docs/control-center-shell.md`. Ce fichier n'a ni DOM ni réseau :
   node l'exécute tel quel (`tests/unit/test_dossier_core_js.py`). La vue
   (`control_center_dossier.js`) le lit sous `JarvisDossierCore`.

   QUATRE RÈGLES.

   1. LE SERVICE DOSSIER EST LA SOURCE. La liste, une entrée, Afficher sur le
      Board passent par `/api/workspace/boards/{id}/dossier*` ; le texte, son
      édition, le déplacement et la suppression par les propriétaires
      (`…/memory/read|write|move|delete`, `/api/artifacts/{id}`). Aucune autre
      adresse : `allowed` refuse avant le réseau.
   2. LE TITRE ET LE CONTENU VIENNENT DE LA MÊME LECTURE. Le Board affiché en
      tête est celui de la réponse de la liste ; une génération (`gen`) écarte
      toute réponse d'un Board quitté.
   3. RIEN N'EST CONFIRMÉ D'AVANCE. Une écriture n'est « enregistrée » que sur
      la réponse du serveur ; un conflit (409 `memory_conflict`) et une issue
      inconnue (échéance) se disent et gardent le texte saisi.
   4. JARVIS N'OUVRE QUE CE QUE LA PAGE PEUT MONTRER. Un ordre `open_entry`
      est refusé avec un code stable (`board_not_displayed`, `entry_not_found`,
      `dossier_unavailable`) plutôt que d'ouvrir autre chose. */
(function(root){
  'use strict';

  const DEADLINE_MS=Object.freeze({read:15000,write:35000,nav:4500});
  const LIST_LIMIT=100;
  const READ_BYTES=65536;
  /* Le propriétaire écrit 256 Kio au plus par appel (`memory_too_large`). */
  const MAX_EDIT_BYTES=262144;
  /* La borne de `GET /api/artifacts/{id}?text_chars=` (0..16000, refus 400 au-delà). */
  const ARTIFACT_TEXT_CHARS=16000;
  const MAX_TABS=8;
  /* Deux ouvertures de Jarvis à moins de 30 s : « montre-moi les deux notes », côte à côte si l'écran le permet. */
  const PAIR_WINDOW_MS=30000;
  /* Largeur du centre au-dessous de laquelle deux documents ne tiennent plus côte à côte (2 × ~60 caractères). */
  const SPLIT_MIN_PX=960;
  const NARROW_PX=900;
  const WIDE_PX=1500;
  const COMMAND_ROUTE='/api/dossier/navigation/commands';
  const PAGE_TOKEN_HEADER='X-Jarvis-Page-Token';

  const isObject=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
  const text=v=>v===null||v===undefined?'':String(v);

  /* ------------------------------------------------------------ vocabulaire */

  const BOARD_KINDS=Object.freeze({assistant:'Assistant',presentation:'Présentation',meeting:'Réunion'});
  /* Collections de la colonne de gauche, dans cet ordre ; chaque nature d'entrée en a une. */
  const COLLECTIONS=Object.freeze([
    Object.freeze({id:'syntheses',label:'Synthèses',kinds:Object.freeze(['memory_summary','report'])}),
    /* Documents de recherche (`documents/research/`, V1.2 Slice 04) : reconnus à leur champ `research`, pas à leur nature. */
    Object.freeze({id:'research',label:'Recherches',kinds:Object.freeze([])}),
    Object.freeze({id:'notes',label:'Notes',kinds:Object.freeze(['note'])}),
    Object.freeze({id:'documents',label:'Documents',kinds:Object.freeze(['document','presentation','file'])}),
    Object.freeze({id:'transcripts',label:'Transcriptions',kinds:Object.freeze(['transcript'])}),
    Object.freeze({id:'media',label:'Images et médias',kinds:Object.freeze(['image','media'])}),
    Object.freeze({id:'links',label:'Liens',kinds:Object.freeze(['link'])}),
  ]);
  const KIND_LABELS=Object.freeze({memory_summary:'Résumé',note:'Note',document:'Document',image:'Image',media:'Média',
    transcript:'Transcription',report:'Synthèse',presentation:'Présentation',link:'Lien',file:'Fichier'});

  /* Refus et pannes, dits à l'humain. Une valeur inconnue garde son code, jamais maquillée. */
  const ERRORS=Object.freeze({
    board_not_found:{title:'Board introuvable',hint:'Il n’existe plus dans le stockage.'},
    board_archived:{title:'Board archivé : lecture seule',hint:'Son Dossier se lit ; rien ne s’y écrit.'},
    dossier_entry_not_found:{title:'Entrée absente de ce Dossier',hint:'Elle a peut-être été déplacée ou supprimée : la liste est relue.'},
    dossier_entry_invalid:{title:'Identifiant d’entrée refusé',hint:'Défaut de la page : rien n’a été envoyé.'},
    dossier_board_not_active:{title:'Ce Board n’est pas le Board affiché',hint:'Afficher sur le Board agit seulement sur le Board actif.'},
    scene_unavailable:{title:'Scène indisponible',hint:'Le Board n’est pas servi en ce moment : rien n’a été affiché.'},
    memory_conflict:{title:'Le fichier a changé depuis votre lecture',hint:'Votre texte est gardé. Relisez la version actuelle, puis enregistrez de nouveau.'},
    memory_exists:{title:'Un fichier porte déjà ce nom',hint:'Rien n’a été écrasé : choisissez un autre nom.'},
    memory_not_found:{title:'Fichier absent',hint:'Il a disparu de la mémoire du Board : la liste est relue.'},
    memory_too_large:{title:'Trop volumineux',hint:'256 Kio au plus par écriture.'},
    memory_not_text:{title:'Fichier non textuel',hint:'Seul le texte UTF-8 se lit et s’édite ici.'},
    memory_path_invalid:{title:'Nom refusé',hint:'Chemin relatif dans la mémoire, 240 caractères au plus, sans nom réservé Windows.'},
    memory_path_escape:{title:'Chemin hors de la mémoire',hint:'Ni chemin absolu, ni lecteur, ni « .. ».'},
    artifact_not_found:{title:'Élément du registre introuvable',hint:'Il a peut-être été supprimé.'},
    workspace_ledger_failed:{title:'Fait, mais non inscrit au journal',hint:'Le changement a eu lieu : ne recommencez pas, relisez.'},
    core_unavailable:{title:'Core indisponible',hint:'Core ne sert pas encore le Dossier. Réessayez dans un instant.'},
    core_unreachable:{title:'Core ne répond pas',hint:'Vérifiez que Core tourne, puis réessayez.'},
    core_timeout:{title:'Core n’a pas répondu à temps',hint:'L’issue d’une écriture est inconnue : relisez avant de recommencer.'},
    timeout:{title:'Pas de réponse',hint:'Aucune réponse dans le délai. Réessayez.'},
    network:{title:'Control Center injoignable',hint:'La page ne joint plus le Control Center. Réessayez.'},
    forbidden_route:{title:'Adresse refusée par la page',hint:'Défaut de la page : rien n’a été envoyé.'},
  });
  function errorOf(code,status,detail){
    const known=ERRORS[code];
    return Object.freeze({code:code||'unknown',status:status||0,detail:text(detail).slice(0,300),
      title:known?known.title:`Refus du serveur (${code||'inconnu'}${status?`, HTTP ${status}`:''})`,
      hint:known?known.hint:(text(detail).slice(0,200)||'Lisez la trace du Control Center.')});
  }

  /* ------------------------------------------------------------ routes bornées */

  const seg=v=>encodeURIComponent(String(v));
  function query(params){
    const parts=Object.entries(params).filter(([,v])=>v!==null&&v!==undefined&&v!=='')
      .map(([k,v])=>`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
    return parts.length?`?${parts.join('&')}`:'';
  }
  const PATHS=Object.freeze({
    list:(board,advanced)=>`/api/workspace/boards/${seg(board)}/dossier${query({limit:LIST_LIMIT,advanced:advanced?'true':null})}`,
    entry:(board,id,advanced)=>`/api/workspace/boards/${seg(board)}/dossier/entry${query({id,advanced:advanced?'true':null})}`,
    present:board=>`/api/workspace/boards/${seg(board)}/dossier/present`,
    read:(board,path,offset)=>`/api/workspace/boards/${seg(board)}/memory/read${query({path,offset:offset||null,max_bytes:READ_BYTES})}`,
    search:(board,q)=>`/api/workspace/boards/${seg(board)}/memory/search${query({q})}`,
    mutate:(board,op)=>`/api/workspace/boards/${seg(board)}/memory/${op}`,
    artifact:id=>`/api/artifacts/${seg(id)}${query({text_chars:ARTIFACT_TEXT_CHARS})}`,
    payload:id=>`/api/artifacts/${seg(id)}/payload`,
  });
  const MUTATIONS=Object.freeze(['write','move','delete']);
  /* GET : la liste, une entrée, la lecture et la recherche de la mémoire, un Artifact ; POST : Afficher sur le
     Board et les trois mutations de mémoire. Une adresse absolue de la page, aucun segment vide, `.` ou `..`. */
  function allowed(method,path){
    if(typeof path!=='string'||/[#\\]/.test(path)||!/^\/[^/]/.test(path))return false;
    const bare=path.split('?')[0];
    const s=bare.split('/').slice(1);
    if(s.some(part=>{let plain;try{plain=decodeURIComponent(part)}catch(_){return true}return plain===''||plain==='.'||plain==='..'}))return false;
    const board=s[0]==='api'&&s[1]==='workspace'&&s[2]==='boards'&&s.length>=5;
    if(method==='POST'){
      if(path.includes('?')||!board)return false;
      if(s.length===6&&s[4]==='dossier'&&s[5]==='present')return true;
      return s.length===6&&s[4]==='memory'&&MUTATIONS.includes(s[5]);
    }
    if(method!=='GET')return false;
    if(board&&s.length===5&&s[4]==='dossier')return true;
    if(board&&s.length===6&&s[4]==='dossier'&&s[5]==='entry')return true;
    if(board&&s.length===6&&s[4]==='memory'&&(s[5]==='read'||s[5]==='search'))return true;
    return s.length===3&&s[0]==='api'&&s[1]==='artifacts';
  }

  /* Client borné : échéance, refus codés, panne réseau nommée ; jamais un succès supposé. */
  function createClient({fetchImpl,now=()=>Date.now(),setTimer=(fn,ms)=>setTimeout(fn,ms),clearTimer=id=>clearTimeout(id)}){
    async function call(method,path,body,deadline){
      if(!allowed(method,path))return {ok:false,error:errorOf('forbidden_route',0,path)};
      const ctl=typeof AbortController==='function'?new AbortController():null;
      let timedOut=false;
      const timer=setTimer(()=>{timedOut=true;if(ctl)ctl.abort()},deadline||DEADLINE_MS.read);
      const started=now();
      try{
        const init={method,cache:'no-store',headers:{Accept:'application/json'}};
        if(ctl)init.signal=ctl.signal;
        if(body!==undefined){init.body=JSON.stringify(body);init.headers['Content-Type']='application/json'}
        const response=await fetchImpl(path,init);
        let payload=null;
        try{payload=await response.json()}catch(_error){payload=null /* intentional: a non-JSON answer is reported by its status */}
        const ms=now()-started;
        if(response.status>=200&&response.status<300)return {ok:true,status:response.status,body:payload||{},ms};
        const e=isObject(payload)&&isObject(payload.error)?payload.error:{};
        return {ok:false,status:response.status,ms,body:payload,error:errorOf(text(e.code)||`http_${response.status}`,response.status,e.message)};
      }catch(error){
        return {ok:false,status:0,ms:now()-started,error:errorOf(timedOut?'timeout':'network',0,error&&error.message)};
      }finally{clearTimer(timer)}
    }
    return Object.freeze({
      get:(path,deadline)=>call('GET',path,undefined,deadline),
      post:(path,body,deadline)=>call('POST',path,body,deadline||DEADLINE_MS.write),
    });
  }

  /* ------------------------------------------------------------ organisation */

  function collectionOf(kind){
    const found=COLLECTIONS.find(c=>c.kinds.includes(kind));
    return found?found.id:'documents';
  }
  /* La collection d'une entrée : un document de recherche va sous « Recherches », le reste selon sa nature. */
  function collectionOfEntry(e){
    return isObject(e)&&isObject(e.research)?'research':collectionOf(isObject(e)?e.kind:'');
  }
  /* Colonne de gauche : collections non vides, puis l'arbre des dossiers de la mémoire (racine comprise). */
  function organize(entries){
    const list=Array.isArray(entries)?entries.filter(isObject):[];
    const collections=COLLECTIONS.map(c=>({id:c.id,label:c.label,ids:list.filter(e=>collectionOfEntry(e)===c.id).map(e=>e.entry_id)}))
      .filter(c=>c.ids.length);
    const tree={name:'',path:'',folders:new Map(),ids:[]};
    for(const e of list){
      if(e.source!=='memory'||typeof e.folder!=='string'||!e.folder)continue;
      let node=tree,acc='';
      for(const part of e.folder.split('/')){
        acc=acc?`${acc}/${part}`:part;
        if(!node.folders.has(part))node.folders.set(part,{name:part,path:acc,folders:new Map(),ids:[]});
        node=node.folders.get(part);
      }
      node.ids.push(e.entry_id);
    }
    const flat=node=>({name:node.name,path:node.path,ids:node.ids.slice(),
      count:node.ids.length+[...node.folders.values()].reduce((n,f)=>n+flat(f).count,0),
      folders:[...node.folders.values()].sort((a,b)=>a.name.localeCompare(b.name,'fr')).map(flat)});
    return {collections,folders:flat(tree).folders,total:list.length};
  }
  const fold=s=>text(s).normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
  /* Filtre local : titre, dossier, nature et aperçu, accents ignorés ; tous les mots doivent y être. */
  function filterEntries(entries,q){
    const words=fold(q).split(/\s+/).filter(Boolean);
    const list=Array.isArray(entries)?entries:[];
    if(!words.length)return list.slice();
    return list.filter(e=>{
      const hay=fold([e.title,e.folder,KIND_LABELS[e.kind]||e.kind,e.preview].join(' '));
      return words.every(w=>hay.includes(w));
    });
  }
  function entriesOfSection(entries,section){
    const list=Array.isArray(entries)?entries:[];
    if(!section||section==='home')return list;
    if(section.startsWith('c:'))return list.filter(e=>collectionOfEntry(e)===section.slice(2));
    if(section.startsWith('f:')){const p=section.slice(2);return list.filter(e=>e.source==='memory'&&(e.folder===p||text(e.folder).startsWith(p+'/')))}
    return list;
  }

  /* ------------------------------------------------------------ Markdown sûr (données, jamais du HTML) */

  const MACHINE_COMMENT=/<!--\s*jarvis:dossier([^>]*)-->/g;
  /* Le commentaire machine de Ranger (provenance) quitte la lecture et rejoint les détails techniques. */
  function splitMachine(raw){
    const meta=[];
    const body=text(raw).replace(MACHINE_COMMENT,(_m,inner)=>{meta.push(inner.trim());return ''});
    return {body,meta};
  }
  function inline(s){
    const out=[];
    const re=/(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*|_[^_\n]+_)|(\[[^\]\n]+\]\((https?:\/\/[^)\s]+)\))|(https?:\/\/[^\s)]+)/g;
    let last=0,m;
    while((m=re.exec(s))){
      if(m.index>last)out.push({t:'text',v:s.slice(last,m.index)});
      if(m[1])out.push({t:'code',v:m[1].slice(1,-1)});
      else if(m[2])out.push({t:'strong',v:m[2].slice(2,-2)});
      else if(m[3])out.push({t:'em',v:m[3].slice(1,-1)});
      else if(m[4])out.push({t:'link',v:m[4].slice(1,m[4].indexOf('](')),href:m[5]});
      else if(m[6])out.push({t:'link',v:m[6],href:m[6]});
      last=re.lastIndex;
    }
    if(last<s.length)out.push({t:'text',v:s.slice(last)});
    return out;
  }
  function markdownBlocks(raw){
    const {body,meta}=splitMachine(raw);
    const lines=body.replace(/\r\n?/g,'\n').split('\n');
    const blocks=[];
    let para=[],list=null,quote=null,code=null;
    /* En-tête de métadonnées en tête (`---` … `---`, document de recherche) : gardé tel quel, en bloc à chasse fixe,
       jamais lu comme une ligne de séparation suivie d'un paragraphe (V1.2 Slice 04). */
    if(lines.length&&lines[0].trim()==='---'){
      const end=lines.findIndex((l,i)=>i>0&&l.trim()==='---');
      if(end>0){blocks.push({t:'code',v:lines.slice(1,end).join('\n'),fm:true});lines.splice(0,end+1)}
    }
    const flush=()=>{
      if(para.length){blocks.push({t:'p',inline:inline(para.join(' '))});para=[]}
      if(list){blocks.push(list);list=null}
      if(quote){blocks.push({t:'quote',inline:inline(quote.join(' '))});quote=null}
    };
    for(const line of lines){
      if(code){
        if(/^```/.test(line)){blocks.push({t:'code',v:code.join('\n')});code=null}else code.push(line);
        continue;
      }
      if(/^```/.test(line)){flush();code=[];continue}
      const h=line.match(/^(#{1,6})\s+(.*)$/);
      if(h){flush();blocks.push({t:'h',level:h[1].length,inline:inline(h[2].trim())});continue}
      if(/^\s*(---+|\*\*\*+)\s*$/.test(line)){flush();blocks.push({t:'hr'});continue}
      const li=line.match(/^\s*([-*+]|\d+[.)])\s+(.*)$/);
      if(li){
        const ordered=/\d/.test(li[1]);
        if(para.length||quote||(list&&list.t!==(ordered?'ol':'ul')))flush();
        if(!list)list={t:ordered?'ol':'ul',items:[]};
        list.items.push(inline(li[2]));continue;
      }
      const q=line.match(/^>\s?(.*)$/);
      if(q){if(para.length||list)flush();(quote||(quote=[])).push(q[1]);continue}
      if(!line.trim()){flush();continue}
      if(list&&/^\s{2,}\S/.test(line)){const last=list.items[list.items.length-1];last.push({t:'text',v:' '},...inline(line.trim()));continue}
      if(list||quote)flush();
      para.push(line.trim());
    }
    if(code)blocks.push({t:'code',v:code.join('\n')});
    flush();
    return {blocks,meta};
  }

  /* Le premier titre `#` d'un document devient son titre affiché (et quitte le corps, pour ne pas se lire deux fois). */
  function leadHeading(blocks){
    const list=Array.isArray(blocks)?blocks:[];
    const at=list[0]&&list[0].fm?1:0;  // un en-tête de métadonnées précède le titre : il reste en tête du corps
    const first=list[at];
    if(!first||first.t!=='h'||first.level!==1)return {heading:null,blocks:list};
    const heading=first.inline.map(t=>t.v).join('').trim();
    return heading?{heading,blocks:list.slice(0,at).concat(list.slice(at+1))}:{heading:null,blocks:list};
  }

  /* ------------------------------------------------------------ onglets et disposition */

  /* Ouvrir une entrée : un onglet existant est repris (jamais deux fois le même document), sinon un nouveau
     après l'actif ; au-delà de MAX_TABS, le plus ancien onglet non modifié part. Un onglet `dirty` (modification
     non enregistrée) ne part **jamais** : si tous le sont, l'ouverture est refusée (`full: true`, onglets
     inchangés). Rend {tabs, active, dropped, full}. */
  function openTab(tabs,entryId,{opener='user',at=0,active=null}={}){
    const list=(Array.isArray(tabs)?tabs:[]).slice();
    const found=list.find(t=>t.entryId===entryId);
    if(found){found.opener=opener;found.openedAt=at;return {tabs:list,active:entryId,dropped:null,full:false}}
    const index=active?list.findIndex(t=>t.entryId===active):-1;
    const tab={entryId,opener,openedAt:at};
    list.splice(index<0?list.length:index+1,0,tab);
    let dropped=null;
    if(list.length>MAX_TABS){
      const victim=list.filter(t=>t!==tab&&!t.dirty).sort((a,b)=>a.openedAt-b.openedAt)[0];
      if(!victim)return {tabs:(Array.isArray(tabs)?tabs:[]).slice(),active,dropped:null,full:true};
      list.splice(list.indexOf(victim),1);dropped=victim.entryId;
    }
    return {tabs:list,active:entryId,dropped,full:false};
  }
  function closeTab(tabs,entryId,active){
    const list=(Array.isArray(tabs)?tabs:[]).slice();
    const index=list.findIndex(t=>t.entryId===entryId);
    if(index<0)return {tabs:list,active};
    list.splice(index,1);
    const next=active!==entryId?active:(list[index]||list[index-1]||null);
    return {tabs:list,active:next&&typeof next==='object'?next.entryId:next};
  }
  /* Disposition à une largeur donnée : étroit = organisation et contexte en tiroirs ; le côte à côte n'existe
     que si le centre garde SPLIT_MIN_PX, sinon il retombe en onglets (le second document reste un onglet). */
  function layoutFor(width,{ctxOpen=false}={}){
    const w=Number(width)||0;
    const narrow=w<NARROW_PX;
    const org=narrow?0:(w<1280?232:264);
    const ctxDocked=w>=1280;
    const ctx=ctxOpen&&ctxDocked?300:0;
    const centre=w-org-ctx;
    return {narrow,orgDrawer:narrow,ctxDrawer:!ctxDocked,ctxDefaultOpen:w>=WIDE_PX,split:centre>=SPLIT_MIN_PX,centre};
  }
  /* Deux ouvertures de Jarvis rapprochées : la seconde se pose à côté de la première (si la place le permet). */
  function pairFor(tabs,entryId,now){
    const other=(Array.isArray(tabs)?tabs:[]).filter(t=>t.entryId!==entryId&&t.opener==='jarvis'&&now-t.openedAt<=PAIR_WINDOW_MS)
      .sort((a,b)=>b.openedAt-a.openedAt)[0];
    return other?[other.entryId,entryId]:null;
  }

  /* ------------------------------------------------------------ issues des écritures */

  function writeOutcome(answer){
    if(answer&&answer.ok)return {kind:'saved',status:answer.status,sha:text(answer.body&&answer.body.sha256)||null,
      ledgerFailed:!!(answer.body&&answer.body.ledger_failed)};
    const e=answer&&answer.error||errorOf('network',0,'');
    if(e.code==='memory_conflict')return {kind:'conflict',error:e};
    if(e.code==='timeout'||e.code==='core_timeout'||e.code==='network')return {kind:'unknown',error:e};
    return {kind:'refused',error:e};
  }
  const REPRESENTATIONS=Object.freeze([['window','Fenêtre','le document lisible sur le Board'],
    ['capsule','Capsule','le titre seul'],['point','Étoile','réduite à un point']]);
  function presentOutcome(answer,representation){
    const label=(REPRESENTATIONS.find(r=>r[0]===representation)||REPRESENTATIONS[0])[1].toLowerCase();
    if(answer&&answer.ok){
      const created=answer.status===201||answer.body&&answer.body.created===true;
      return {kind:'ok',created,objectId:text(answer.body&&answer.body.object_id),
        message:created?`Affiché sur le Board (${label}).`:`Déjà sur le Board : la représentation existante est reprise (${label}).`};
    }
    const e=answer&&answer.error||errorOf('network',0,'');
    return {kind:e.code==='timeout'||e.code==='network'?'unknown':'refused',error:e,
      message:e.code==='timeout'||e.code==='network'?'Issue inconnue : regardez le Board avant de recommencer.':`${e.title}. ${e.hint}`};
  }

  /* ------------------------------------------------------------ capacités d'une entrée */

  /* Ce que l'humain peut faire d'une entrée, avec la raison quand il ne le peut pas (jamais un bouton mort). */
  /* Un lien déposé ne devient un `href` que s'il est http(s) absolu (défense en profondeur, Slice 08, QA S07 3 :
     `check_link_url` le vérifie déjà en amont). Rend l'URL normalisée, ou `null`. */
  function safeLinkUrl(raw){
    const text=String(raw==null?'':raw).trim();
    if(!text||text.length>2048||/\s/.test(text)||[...text].some(c=>c.charCodeAt(0)<32))return null;
    let url;
    try{url=new URL(text)}catch(_){return null}
    return url.protocol==='http:'||url.protocol==='https:'?url.href:null;
  }

  function capabilities(entry,{board,displayedBoardId,running,coreLost}){
    const writable=!!(board&&board.writable);
    const displayed=!!(board&&displayedBoardId&&board.board_id===displayedBoardId);
    const memory=entry&&entry.source==='memory';
    const textual=entry&&entry.open==='text';
    const lost=coreLost?'Core ne répond pas : rien ne s’écrit tant que l’état n’est pas relu.':null;
    const archived=board&&board.status==='archived'?'Board archivé : son Dossier se lit, rien ne s’y écrit.':null;
    const reasonPresent=lost||archived||(!displayed?'Ce Board n’est pas le Board affiché : Afficher sur le Board agit seulement sur le Board actif.':null);
    const reasonEdit=lost||archived||(!memory?'Un élément du registre ne se modifie pas : il se lit, et s’affiche sur le Board.':null)
      ||(!textual?'Ce fichier n’est pas du texte : il se liste, il ne s’édite pas ici.':null)
      ||(entry&&entry.size>MAX_EDIT_BYTES?'Fichier de plus de 256 Kio : il se lit, il ne s’édite pas en une fois.':null);
    const reasonMove=lost||archived||(!memory?'Seuls les fichiers de la mémoire du Board se renomment.':null);
    const reasonDelete=reasonMove||(running?'Indisponible pendant une lecture dans Variantes : la confirmation serait cachée sous le Studio.':null);
    return {present:{ok:!reasonPresent,reason:reasonPresent},edit:{ok:!reasonEdit&&writable,reason:reasonEdit},
      move:{ok:!reasonMove&&writable,reason:reasonMove},delete:{ok:!reasonDelete&&writable,reason:reasonDelete}};
  }

  /* ------------------------------------------------------------ canal Jarvis -> page */

  /* Décision d'ouverture d'un ordre de Jarvis, avant toute lecture : {ok} ou {code, reason}. */
  function openDecision(command,{displayedBoardId,covered}){
    if(!isObject(command)||command.action!=='open_entry'||typeof command.entry_id!=='string'||typeof command.board_id!=='string')
      return {ok:false,code:'dossier_unavailable',reason:'ordre illisible pour la page'};
    if(covered)return {ok:false,code:'dossier_unavailable',reason:covered};
    if(!displayedBoardId)return {ok:false,code:'dossier_unavailable',reason:'le Board affiché est inconnu (Core ne répond pas)'};
    if(command.board_id!==displayedBoardId)return {ok:false,code:'board_not_displayed',reason:'un autre Board est affiché'};
    return {ok:true};
  }
  /* Une modification en cours ne se perd jamais en silence (QA S07, B1/B2) : un ordre de Jarvis qui changerait
     le Board du Dossier, ou qui n'aurait plus d'onglet à libérer, est refusé `edit_in_progress`. */
  const EDIT_IN_PROGRESS='edit_in_progress';
  function editGuard({dirtyCount,boardId,targetBoardId,tabsFull}){
    if(!dirtyCount)return {ok:true};
    if(targetBoardId&&boardId&&targetBoardId!==boardId)
      return {ok:false,code:EDIT_IN_PROGRESS,reason:'une modification est en cours dans le Dossier (un autre Board) : rien n’a été ouvert'};
    if(tabsFull)return {ok:false,code:EDIT_IN_PROGRESS,reason:`une modification est en cours dans les ${MAX_TABS} onglets ouverts : aucun ne peut être fermé`};
    return {ok:true};
  }
  /* Bascule de Board, Dossier ouvert : il suit le Board affiché (`follow`) et se relie au nouveau ; un Dossier
     ouvert sur un Board précis (archivé) ne bouge pas. Jamais le titre de A sur le contenu de B. */
  function rebindOnSwitch({follow,boardId,displayedBoardId}){
    if(!follow||!displayedBoardId||displayedBoardId===boardId)return 'keep';
    return 'rebind';
  }

  /* ------------------------------------------------------------ mots */

  function relativeTime(iso,now){
    const t=Date.parse(text(iso));
    if(!Number.isFinite(t))return '';
    const s=Math.max(0,Math.round(((now||Date.now())-t)/1000));
    if(s<45)return 'à l’instant';
    if(s<3600)return `il y a ${Math.round(s/60)} min`;
    if(s<86400)return `il y a ${Math.round(s/3600)} h`;
    const d=Math.round(s/86400);
    if(d<30)return `il y a ${d} j`;
    return new Date(t).toLocaleDateString('fr-FR',{day:'numeric',month:'short',year:'numeric'});
  }
  function absoluteTime(iso){
    const t=Date.parse(text(iso));
    return Number.isFinite(t)?new Date(t).toLocaleString('fr-FR',{dateStyle:'long',timeStyle:'short'}):'';
  }
  function formatBytes(n){
    if(typeof n!=='number'||!Number.isFinite(n))return '';
    if(n<1024)return `${n} o`;
    if(n<1048576)return `${(n/1024).toFixed(n<10240?1:0).replace('.',',')} Kio`;
    return `${(n/1048576).toFixed(1).replace('.',',')} Mio`;
  }
  /* Vérification d'un document de recherche, dite à l'humain : « vérifiée le 27 octobre 2026 · 4 sources (1 non lue) ». */
  function researchLine(entry){
    const r=isObject(entry)&&isObject(entry.research)?entry.research:null;
    if(!r)return '';
    if(r.problem==='unreadable')return 'en-tête de recherche illisible';
    const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(text(r.checked_at));
    const parts=[m?`vérifiée le ${new Date(+m[1],+m[2]-1,+m[3]).toLocaleDateString('fr-FR',{day:'numeric',month:'long',year:'numeric'})}`
      :'date de vérification inconnue'];
    if(typeof r.sources==='number'&&r.sources>0){
      const failed=typeof r.failed_sources==='number'&&r.failed_sources>0?` (${r.failed_sources} non lue${r.failed_sources>1?'s':''})`:'';
      parts.push(`${r.sources} source${r.sources>1?'s':''}${failed}`);
    }
    if(r.problem)parts.push('en-tête à réécrire');
    return parts.join(' · ');
  }
  function sourceLine(entry){
    if(!entry)return '';
    if(entry.source==='memory')return `Mémoire du Board · ${text(entry.path)}`;
    return `Registre des Artifacts${entry.provenance?` · ${entry.provenance}`:''}`;
  }
  const api=Object.freeze({
    DEADLINE_MS,LIST_LIMIT,READ_BYTES,MAX_EDIT_BYTES,MAX_TABS,PAIR_WINDOW_MS,SPLIT_MIN_PX,NARROW_PX,WIDE_PX,
    COMMAND_ROUTE,PAGE_TOKEN_HEADER,BOARD_KINDS,COLLECTIONS,KIND_LABELS,ERRORS,REPRESENTATIONS,PATHS,
    errorOf,allowed,createClient,collectionOf,collectionOfEntry,organize,filterEntries,entriesOfSection,splitMachine,inline,markdownBlocks,leadHeading,
    openTab,closeTab,layoutFor,pairFor,editGuard,EDIT_IN_PROGRESS,writeOutcome,presentOutcome,capabilities,safeLinkUrl,openDecision,rebindOnSwitch,
    relativeTime,absoluteTime,formatBytes,sourceLine,researchLine,
  });
  root.JarvisDossierCore=api;
  if(typeof module==='object'&&module&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
