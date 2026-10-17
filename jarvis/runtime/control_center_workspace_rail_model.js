/* Rail actif, étape B (Slice 07 du handoff jarvis-board-orbital-ui-workspace-rail, décision D10) : les Artifacts liés au Board actif, en
   `WorkspaceRailItem` (tasks/…/docs/02-architecture.md § 7). Un ADAPTATEUR de vue, pas un registre : chaque élément garde l'identité de son
   Artifact (`artifact_id`), rien n'est stocké ici, rien n'est deviné.

   Source canonique : `GET /api/workspace/artifacts?board_id=<Board actif>` (relais de `/v1/workspace/artifacts`, liens `board_artifact_links`).
   Natures montrées : `upload`, `link`, `screenshot`, `screen_recording`, rendus `presentation_still` / `_video` / `_pdf`. Les snapshots, les
   transcriptions et les preuves dérivées n'en sont pas (ce ne sont pas des documents de travail).

   - Aperçu : une image (capture d'écran, image déposée, rendu image) complète se lit par la route bornée `/api/artifacts/{id}/payload` ; tout
     le reste (vidéo, PDF, bureautique, lien) est une vignette typée, badge choisi par `mime_type` ou par l'hôte du lien
     (`docs.google.com/presentation` -> Google Slides…). Jamais une image inventée, jamais un chemin, jamais une page distante chargée.
   - État : `pending` -> `working`, `complete` -> `ready`, `failed` / `partial` -> `problem`, autre -> `unknown`. Pas de jaune : aucun
     propriétaire canonique de « revu » pour ces Artifacts.
   - Board : `createSource` ne garde que la réponse du Board demandé EN DERNIER ; changer de Board vide la liste aussitôt (aucune fuite d'un
     Board vers l'autre), puis relit.

   Pur (node) + un petit contrôleur à `fetch` injecté. Aucun DOM ici : le rail (`control_center_presentation_rail.js`) dessine. */
(function(root){
  'use strict';

  const ROUTE='/api/workspace/artifacts';
  const PAGE_LIMIT=24;
  const KINDS=Object.freeze(['upload','link','screenshot','screen_recording','presentation_still','presentation_video','presentation_pdf']);
  const ID=/^[a-z][a-z0-9]*_[A-Za-z0-9_]{6,80}$/;
  const STATE=Object.freeze({pending:'working',complete:'ready',failed:'problem',partial:'problem'});
  const IMAGE_MIME=/^image\/(png|jpeg|gif|webp|avif|bmp|svg\+xml)$/i;
  /* Badge par type MIME exact, puis par famille. */
  const MIME_TYPES=Object.freeze({
    'application/pdf':{key:'pdf',badge:'PDF'},
    'application/vnd.openxmlformats-officedocument.presentationml.presentation':{key:'powerpoint',badge:'PowerPoint'},
    'application/vnd.ms-powerpoint':{key:'powerpoint',badge:'PowerPoint'},
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document':{key:'word',badge:'Word'},
    'application/msword':{key:'word',badge:'Word'},
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':{key:'excel',badge:'Excel'},
    'application/vnd.ms-excel':{key:'excel',badge:'Excel'},
    'text/csv':{key:'table',badge:'CSV'},
    'text/markdown':{key:'text',badge:'Markdown'},
    'application/json':{key:'text',badge:'JSON'},
    'application/zip':{key:'archive',badge:'Archive'},
  });
  /* Hôte (et début de chemin) d'un lien -> type reconnu. L'URL n'est jamais chargée : seul son texte est lu. */
  const LINK_TYPES=Object.freeze([
    {host:'docs.google.com',path:'/presentation',key:'google_slides',badge:'Google Slides'},
    {host:'docs.google.com',path:'/document',key:'google_docs',badge:'Google Docs'},
    {host:'docs.google.com',path:'/spreadsheets',key:'google_sheets',badge:'Google Sheets'},
    {host:'drive.google.com',path:'',key:'google_drive',badge:'Google Drive'},
    {host:'youtube.com',path:'',key:'youtube',badge:'YouTube'},
    {host:'youtu.be',path:'',key:'youtube',badge:'YouTube'},
    {host:'figma.com',path:'',key:'figma',badge:'Figma'},
    {host:'github.com',path:'',key:'github',badge:'GitHub'},
    {host:'notion.so',path:'',key:'notion',badge:'Notion'},
  ]);
  const KIND_LABEL=Object.freeze({screenshot:'Capture d’écran',screen_recording:'Enregistrement d’écran',presentation_still:'Rendu image',
    presentation_video:'Vidéo de présentation',presentation_pdf:'PDF de présentation',upload:'Fichier',link:'Lien'});

  function clean(value,max){
    const text=String(value==null?'':value).replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]+/g,' ').replace(/\s+/g,' ').trim();
    return max&&text.length>max?text.slice(0,Math.max(1,max-1))+'…':text;
  }
  function parseLink(text){
    try{const u=new URL(String(text||'').trim());return u.protocol==='http:'||u.protocol==='https:'?u:null}
    catch(_error){return null /* intentional: a link whose text is not a URL is shown as a plain link */}
  }
  function linkType(url){
    if(!url)return {key:'link',badge:'Lien'};
    const host=url.hostname.toLowerCase().replace(/^www\./,'').replace(/^m\./,'');
    const hit=LINK_TYPES.find(t=>(host===t.host||host.endsWith('.'+t.host))&&url.pathname.startsWith(t.path));
    return hit?{key:hit.key,badge:hit.badge}:{key:'link',badge:host||'Lien'};
  }
  /* Le type montré (badge) d'un Artifact : par nature, puis `mime_type`, puis hôte du lien. */
  function typeOf(a){
    const kind=a&&a.kind,mime=String(a&&a.mime_type||'').toLowerCase().split(';')[0].trim();
    if(kind==='link')return linkType(parseLink(a.preview));
    if(kind==='screenshot')return {key:'image',badge:'Capture'};
    if(kind==='screen_recording')return {key:'video',badge:'Vidéo'};
    if(kind==='presentation_still')return {key:'image',badge:'Rendu'};
    if(kind==='presentation_video')return {key:'video',badge:'MP4'};
    if(kind==='presentation_pdf')return {key:'pdf',badge:'PDF'};
    if(MIME_TYPES[mime])return MIME_TYPES[mime];
    if(IMAGE_MIME.test(mime))return {key:'image',badge:'Image'};
    if(mime.startsWith('video/'))return {key:'video',badge:'Vidéo'};
    if(mime.startsWith('audio/'))return {key:'audio',badge:'Audio'};
    if(mime.startsWith('text/'))return {key:'text',badge:'Texte'};
    return {key:'file',badge:'Fichier'};
  }
  function isImage(a){
    if(a.kind==='screenshot'||a.kind==='presentation_still')return true;
    return a.kind==='upload'&&IMAGE_MIME.test(String(a.mime_type||'').split(';')[0].trim());
  }
  function titleOf(a,type){
    if(a.kind==='upload'&&a.preview)return clean(a.preview,80);
    if(a.kind==='link'){const u=parseLink(a.preview);return u?clean(u.hostname.replace(/^www\./,'')+(u.pathname!=='/'?u.pathname:''),80):clean(a.preview,80)||'Lien'}
    return KIND_LABEL[a.kind]||type.badge;
  }
  /* `WorkspaceRailItem` (vue, jamais stockée). `null` si l'Artifact n'est pas montrable (nature hors liste, id illisible). */
  function itemOf(a,boardId){
    if(!a||typeof a!=='object'||!KINDS.includes(a.kind)||typeof a.artifact_id!=='string'||!ID.test(a.artifact_id))return null;
    const type=typeOf(a),state=STATE[a.state]||'unknown';
    const image=isImage(a)&&a.state==='complete'&&a.has_payload!==false;
    return Object.freeze({
      id:a.artifact_id,source_kind:'artifact',artifact_kind:a.kind,title:titleOf(a,type),media_type:type.key,type,
      preview:image?{kind:'image',url:`/api/artifacts/${encodeURIComponent(a.artifact_id)}/payload`}:{kind:'placeholder',label:type.badge},
      activity_state:state,updated_at:a.ended_at||a.created_at||null,
      primary_action:image?'lightbox':'detail',context_actions:Object.freeze(['detail']),
      source_scope:Object.freeze({board_id:boardId}),url:a.kind==='link'&&parseLink(a.preview)?parseLink(a.preview).href:null});
  }
  /* Une réponse de la route, pour CE Board : une réponse d'un autre Board (portée différente) ne donne rien. */
  function itemsOf(answer,boardId){
    if(!boardId||!answer||!answer.scope||answer.scope.board_id!==boardId||!Array.isArray(answer.artifacts))return [];
    return answer.artifacts.map(a=>itemOf(a,boardId)).filter(Boolean);
  }
  function urlFor(boardId){
    const q=new URLSearchParams({board_id:boardId,limit:String(PAGE_LIMIT)});
    for(const k of KINDS)q.append('kind',k);
    return `${ROUTE}?${q.toString()}`;
  }

  /* Contrôleur : un Board à la fois, la dernière demande gagne. `fetch` et `onChange` injectés (node les double). */
  function createSource(deps){
    const d=deps||{};
    const fetchImpl=d.fetch||(typeof root.fetch==='function'?root.fetch.bind(root):null);
    const onChange=typeof d.onChange==='function'?d.onChange:()=>{};
    const log=typeof d.log==='function'?d.log:()=>{};
    const S={boardId:null,items:[],status:'idle',error:null,seq:0,loadedAt:0};
    const view=()=>({boardId:S.boardId,items:S.items.slice(),status:S.status,error:S.error});
    async function load(){
      const boardId=S.boardId,seq=++S.seq;
      if(!boardId){S.items=[];S.status='idle';S.error=null;onChange(view());return view()}
      if(!fetchImpl){S.status='failed';S.error='fetch indisponible';onChange(view());return view()}
      S.status=S.items.length?'refreshing':'loading';onChange(view());
      try{
        const response=await fetchImpl(urlFor(boardId),{method:'GET',cache:'no-store'});
        let body=null;try{body=await response.json()}catch(_error){body=null /* intentional: reported by status below */}
        if(seq!==S.seq||boardId!==S.boardId)return view();  // a later Board (or a later read) won: this answer is dropped
        if(!response.ok){const e=body&&body.error||{};throw Object.assign(new Error(e.message||`HTTP ${response.status}`),{code:e.code||`http_${response.status}`})}
        S.items=itemsOf(body,boardId);S.status='ready';S.error=null;S.loadedAt=Date.now();
        log('workspace_items',{board_id:boardId.slice(0,16),count:S.items.length});
      }catch(error){
        if(seq!==S.seq||boardId!==S.boardId)return view();
        S.status='failed';S.error=clean(error&&error.message||error,140);
        log('workspace_items_failed',{board_id:boardId.slice(0,16),code:error&&error.code||'network',message:S.error},'warn');
      }
      onChange(view());
      return view();
    }
    /* Changer de Board vide la liste AVANT de relire : rien de l'ancien Board ne reste affiché sous le nouveau. */
    function setBoard(boardId){
      const next=typeof boardId==='string'&&boardId?boardId:null;
      if(next===S.boardId)return Promise.resolve(view());
      S.boardId=next;S.items=[];S.error=null;S.status=next?'loading':'idle';
      return load();
    }
    return {setBoard,refresh:load,view,get loadedAt(){return S.loadedAt}};
  }

  const API=Object.freeze({ROUTE,PAGE_LIMIT,KINDS,typeOf,itemOf,itemsOf,urlFor,createSource});
  root.JarvisWorkspaceRailModel=API;
  if(typeof module!=='undefined'&&module.exports)module.exports=API;
})(typeof window!=='undefined'?window:globalThis);
