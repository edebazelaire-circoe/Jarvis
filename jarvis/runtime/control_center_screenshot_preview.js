/* Aperçu de capture d'écran et actions rapides du Control Center.

   Handoff `jarvis-board-orbital-ui-workspace-rail`, Slice 05 ; architecture
   résolue §6 (D7, contraignante). Contrat : `docs/capture.md` › *Interface* ›
   *Aperçu de capture d'écran* et `docs/control-center-shell.md` (rangs 38 et 60).

   **Ce qui le déclenche.** Uniquement une capture d'écran **réussie** prise par
   le contrôleur de capture (`JarvisCaptureRail`, `control_center_capture_rail.js`),
   qui publie `shot = {capture, artifact}` dans son modèle de vue. Une capture
   ratée ne change pas `shot` : rien ne s'affiche. La valeur présente à
   l'abonnement (une capture d'avant le chargement de ce module) est vue, jamais
   montrée. Un Artifact qui n'est pas une capture `complete` n'est jamais montré.

   **Aucune vérité ici.** L'aperçu ne tient que ce qui est affiché. Il ne
   modifie jamais la capture ni son Artifact : l'ignorer, le fermer (×, `Esc`,
   délai) ne supprime rien ; une vignette illisible (404, 502, délai) donne un
   emplacement typé (« Capture d'écran · PNG », code), et Ouvrir / Envoyer /
   Supprimer restent offerts. Aucun octet dans le stockage du navigateur.

   - **Vignette** : `<img>` paresseux sur `GET /api/artifacts/{id}/payload`
     (route bornée du relais, même origine), 240×135 au plus par la feuille.
   - **Délai** : 6 s, suspendu tant que le pointeur est dessus, que le focus y
     est, qu'une action est en cours ou que la visionneuse est ouverte ; il
     repart **entier** au relâchement (prévisible).
   - **Non modal** : rang 38, zone `left-low` (au-dessus du contexte bas-gauche,
     jamais au centre bas) ; il ne prend jamais le focus en paraissant, aucun
     voile, rien n'est rendu inerte ; il annonce poliment.
   - **Ouvrir** : visionneuse (motif `.overlay`, rang 60) avec l'image entière
     et « Ouvrir dans un onglet » (même URL de payload). Aussi appelée par le
     rail de l'espace de travail (Slice 07) : `openLightbox({artifact_id, url,
     title})` — l'URL est toujours **reconstruite** depuis l'id validé.
   - **Supprimer** : `confirmDialog` de la page puis `DELETE /api/artifacts/{id}` ;
     un refus s'affiche avec son code, l'aperçu reste.
   - **Envoyer à Jarvis** : `JarvisChat.attachExisting(...)` — une pièce prête,
     sans téléversement ; le panneau Chat s'ouvre, le champ prend le focus, le
     texte reste exigé (aucun envoi automatique). Core admet la capture
     (`attachment_refusal`, `docs/chat.md` étape 5).

   Deux blocs : le **contrôleur pur** (`createPreviewController`, horloge et
   actions injectées, exécuté par node dans `tests/unit/test_screenshot_preview_js.py`)
   et le **bloc navigateur** (DOM, `fetch`), éprouvé dans Chrome par
   `tests/unit/test_screenshot_preview_browser.py`. Journal : console
   `[screenshot_preview] <clé> {json}`, jamais un nom de fichier ni un chemin. */
(function(root){
  'use strict';

  const DOM=Object.freeze({hostId:'screenshotPreview',styleId:'screenshotPreviewStyle',liveId:'screenshotPreviewLive',
    lightboxId:'screenshotLightbox',hintId:'screenshotPreviewHint'});
  const TIMING=Object.freeze({dismissMs:6000,thumbDeadlineMs:8000,probeMs:5000,deleteMs:35000});
  const ID=/^jart_[A-Za-z0-9_]{1,96}$/;
  /* Phrases d'un refus de suppression ; le code est toujours montré à côté. */
  const DELETE_TEXT=Object.freeze({
    artifact_not_found:'elle n’existe plus chez Jarvis Core',
    artifact_has_dependents:'d’autres éléments en dérivent (une annotation, par exemple)',
    artifact_still_pending:'elle est encore en cours d’écriture',
    core_unreachable:'Jarvis Core est injoignable',
    core_timeout:'Jarvis Core n’a pas répondu à temps : relisez avant de réessayer',
    client_timeout:'pas de réponse à temps : relisez avant de réessayer',
    network_error:'le Control Center est injoignable',
  });
  const PAYLOAD_TEXT=Object.freeze({
    artifact_not_found:'capture introuvable',artifact_payload_missing:'fichier absent',artifact_no_payload:'aucun fichier',
    payload_too_large_for_relay:'trop lourde pour l’aperçu',core_unreachable:'Jarvis Core injoignable',
    core_timeout:'Jarvis Core trop lent',payload_timeout:'délai dépassé',payload_unreadable:'image illisible',
  });

  const isObject=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
  const payloadUrl=id=>`/api/artifacts/${encodeURIComponent(id)}/payload`;
  const two=n=>String(n).padStart(2,'0');

  /* Heure locale d'une prise (« 14:32 ») ; le nom joint au Chat en dérive. */
  function clockOf(ms){
    const d=new Date(Number.isFinite(ms)?ms:Date.now());
    return {hm:`${two(d.getHours())}:${two(d.getMinutes())}`,file:`${two(d.getHours())}-${two(d.getMinutes())}-${two(d.getSeconds())}`};
  }
  function sizeText(bytes){
    if(!Number.isFinite(bytes)||bytes<0)return '';
    if(bytes<1024)return `${bytes} o`;
    const ko=bytes/1024;
    return ko<1024?`${ko<10?ko.toFixed(1).replace('.',','):Math.round(ko)} Ko`:`${(ko/1024).toFixed(1).replace('.',',')} Mo`;
  }
  function typeOf(mime){
    const m=/^image\/([a-z0-9.+-]+)$/i.exec(String(mime||''));
    return m?m[1].replace(/^jpeg$/i,'jpg').toUpperCase():'image';
  }

  /* Ce que l'aperçu montre d'un résultat `{capture, artifact}`, ou la raison de ne rien montrer. */
  function shotOf(shot){
    if(!isObject(shot))return {item:null,reason:'no_shot'};
    const a=shot.artifact;
    if(!isObject(a)||typeof a.artifact_id!=='string'||!ID.test(a.artifact_id))return {item:null,reason:'no_artifact'};
    if(a.kind!=='screenshot')return {item:null,reason:'not_a_screenshot'};
    if(a.state!=='complete')return {item:null,reason:'not_complete'};
    const at=Number.isFinite(shot.at)?shot.at:Date.now(),clock=clockOf(at);
    const mime=typeof a.mime_type==='string'&&a.mime_type?a.mime_type:'image/png';
    return {item:Object.freeze({
      artifactId:a.artifact_id,captureId:isObject(shot.capture)&&typeof shot.capture.capture_id==='string'?shot.capture.capture_id:null,
      url:payloadUrl(a.artifact_id),mime,type:typeOf(mime),
      width:Number.isInteger(a.width)&&a.width>0?a.width:null,height:Number.isInteger(a.height)&&a.height>0?a.height:null,
      size:Number.isInteger(a.size_bytes)&&a.size_bytes>=0?a.size_bytes:null,at,
      title:`Capture d’écran · ${clock.hm}`,name:`Capture d’écran ${clock.file}.${typeOf(mime).toLowerCase()}`,
    }),reason:null};
  }
  function deleteText(code,message){
    const known=DELETE_TEXT[code];
    return `Suppression refusée : ${known||String(message||'raison inconnue').slice(0,140)} (${code||'inconnu'}).`;
  }
  function payloadText(code){return `Aperçu indisponible : ${PAYLOAD_TEXT[code]||'erreur'} (${code||'inconnu'}).`}

  /* ------------------------------------------------- le contrôleur pur

     deps : `later(fn, ms)` / `unlater(id)`, `now()`, `log(level, key, data)`,
     `onChange(view)`, et `actions` — `confirm(item)` → booléen,
     `remove(id)` → promesse (rejet `{code, message}`), `attach(spec)` →
     `{ok, code?}`, `openLightbox(item, onClose)`, `say(text)`. */
  function createPreviewController(deps){
    const {later,unlater,now,log,onChange,actions}=deps;
    const dismissMs=Number.isFinite(deps.dismissMs)?deps.dismissMs:TIMING.dismissMs;
    const S={item:null,image:'idle',imageCode:null,holds:new Set(),busy:null,busySince:null,note:null,timer:0,deadline:null,seen:undefined,seq:0};

    function view(){
      return Object.freeze({shown:!!S.item,item:S.item,image:S.image,imageCode:S.imageCode,
        paused:S.holds.size>0||!!S.busy,holds:Object.freeze([...S.holds].sort()),busy:S.busy,busySince:S.busySince,
        note:S.note?Object.freeze({...S.note}):null,deadline:S.deadline,seq:S.seq});
    }
    function changed(){try{onChange(view())}catch(error){log('error','render_failed',{error:String(error&&error.message||error)})}}
    function disarm(){if(S.timer){unlater(S.timer);S.timer=0}S.deadline=null}
    /* Le délai court seulement sans retenue ; il repart toujours entier. */
    function arm(){
      disarm();
      if(!S.item||S.holds.size||S.busy)return;
      S.deadline=now()+dismissMs;
      S.timer=later(()=>{S.timer=0;dismiss('timeout')},dismissMs);
    }
    /* Le modèle de vue du contrôleur de capture, à chaque peinture. */
    function accept(captureView){
      const shot=isObject(captureView)&&isObject(captureView.shot)?captureView.shot:null;
      if(S.seen===undefined){S.seen=shot;return false}
      if(shot===S.seen)return false;
      S.seen=shot;
      if(!shot)return false;
      const {item,reason}=shotOf(shot);
      if(!item){log('warn','preview_skipped',{reason});return false}
      show(item);
      return true;
    }
    function show(item){
      S.item=item;S.image='loading';S.imageCode=null;S.busy=null;S.note=null;S.seq+=1;
      arm();
      log('info','preview_shown',{artifact_id:item.artifactId,capture_id:item.captureId,dismiss_ms:dismissMs});
      changed();
    }
    function hold(reason){
      if(!S.item||S.holds.has(reason))return;
      S.holds.add(reason);disarm();changed();
    }
    function release(reason){
      if(!S.holds.delete(reason))return;
      arm();changed();
    }
    function imageReady(id){
      if(!S.item||S.item.artifactId!==id||S.image==='ready')return;
      S.image='ready';S.imageCode=null;changed();
    }
    /* Une vignette illisible est une erreur de PRÉSENTATION : la capture et ses actions restent. */
    function imageFailed(id,code){
      if(!S.item||S.item.artifactId!==id||S.image==='failed')return;
      S.image='failed';S.imageCode=typeof code==='string'&&code?code:'payload_unreadable';
      log('warn','preview_payload_failed',{artifact_id:id,code:S.imageCode});
      changed();
    }
    function dismiss(reason){
      if(!S.item)return false;
      const id=S.item.artifactId;
      disarm();S.item=null;S.image='idle';S.imageCode=null;S.holds.clear();S.busy=null;S.busySince=null;S.note=null;
      log('info','preview_dismissed',{artifact_id:id,reason:reason||'user'});
      changed();
      return true;
    }
    function open(){
      const item=S.item;if(!item)return false;
      hold('lightbox');
      try{actions.openLightbox(item,()=>release('lightbox'))}
      catch(error){release('lightbox');S.note={tone:'bad',code:'lightbox_failed',text:'Visionneuse indisponible.'};changed();return false}
      log('info','preview_opened',{artifact_id:item.artifactId});
      return true;
    }
    /* Une seule suppression à la fois ; la confirmation d'abord ; un refus reste lisible. */
    async function remove(){
      const item=S.item;
      if(!item)return 'none';
      if(S.busy){log('info','delete_ignored',{artifact_id:item.artifactId,busy:S.busy});return 'busy'}
      S.busy='delete';S.note=null;disarm();changed();
      let confirmed=false;
      try{confirmed=await actions.confirm(item)===true}
      catch(error){log('error','delete_confirm_failed',{error:String(error&&error.message||error)})}
      if(S.item!==item)return 'gone';
      if(!confirmed){S.busy=null;S.busySince=null;arm();changed();log('info','delete_cancelled',{artifact_id:item.artifactId});return 'cancelled'}
      log('info','delete_requested',{artifact_id:item.artifactId});
      /* L'attente se voit (« Suppression… N s ») et a une échéance (`TIMING.deleteMs`, côté navigateur). */
      S.busySince=now();changed();
      try{
        await actions.remove(item.artifactId);
      }catch(error){
        const code=error&&error.code||'unknown';
        log('warn','delete_refused',{artifact_id:item.artifactId,code,status:error&&error.status||null});
        if(S.item===item){S.busy=null;S.busySince=null;S.note={tone:'bad',code,text:deleteText(code,error&&error.message)};arm();changed()}
        actions.say(deleteText(code,error&&error.message));
        return 'refused';
      }
      log('info','deleted',{artifact_id:item.artifactId});
      actions.say('Capture d’écran supprimée.');
      if(S.item===item)dismiss('deleted');
      return 'deleted';
    }
    /* Joindre au Chat : la pièce existe déjà chez Core, rien n'est téléversé. */
    function send(){
      const item=S.item;
      if(!item)return 'none';
      if(S.busy)return 'busy';
      let answer;
      try{answer=actions.attach({artifact_id:item.artifactId,original_name:item.name,mime_type:item.mime,size_bytes:item.size})}
      catch(error){answer={ok:false,code:'chat_failed'};log('error','send_failed',{error:String(error&&error.message||error)})}
      if(!answer||answer.ok!==true){
        const code=answer&&answer.code||'chat_unavailable';
        log('warn','send_refused',{artifact_id:item.artifactId,code});
        S.note={tone:'bad',code,text:`Envoi à Jarvis impossible (${code}).`};arm();changed();
        return 'refused';
      }
      log('info','sent_to_chat',{artifact_id:item.artifactId,pending:!!answer.pending});
      dismiss('sent');
      return 'sent';
    }
    function current(){return S.item}
    return {accept,show,hold,release,imageReady,imageFailed,dismiss,open,remove,send,view,current};
  }

  const MODULE=Object.freeze({DOM,TIMING,ID,DELETE_TEXT,PAYLOAD_TEXT,payloadUrl,shotOf,clockOf,sizeText,typeOf,deleteText,payloadText,
    createPreviewController});
  root.JarvisScreenshotPreviewModule=MODULE;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=MODULE;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  /* ------------------------------------------------- le bloc navigateur

     Aucun `z-index` dans cette feuille : le rang de l'hôte (38) vit dans la
     page et au registre ; la visionneuse prend la classe `.overlay` (60). */
  const H='#'+DOM.hostId,L='#'+DOM.lightboxId;
  const STYLE=`
${H}{width:min(272px,calc(100vw - var(--shell-anchor-w,14px) - 2 * var(--shell-gutter,18px)));font:12px/1.35 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--text,#d8edf7)}
${H} .sp-card{position:relative;margin:0;padding:8px;border:1px solid var(--shell-stroke,rgba(110,231,255,.22));border-radius:var(--shell-radius,12px);
  background:var(--shell-glass-strong,rgba(4,10,15,.86));backdrop-filter:blur(12px);box-shadow:0 18px 44px rgba(0,0,0,.5);
  animation:spIn var(--shell-dur,180ms) var(--shell-ease,ease-out)}
@keyframes spIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
${H} .sp-thumb{position:relative;display:grid;place-items:center;width:100%;aspect-ratio:16/9;max-height:135px;padding:0;overflow:hidden;
  border:1px solid var(--line,#183343);border-radius:8px;background:#03080c;cursor:zoom-in;color:inherit;font:inherit}
${H} .sp-thumb:focus-visible,${H} button:focus-visible{outline:var(--shell-focus-w,2px) solid var(--shell-focus,#6ee7ff);outline-offset:2px}
${H} .sp-thumb img{width:100%;height:100%;object-fit:contain;display:block}
${H} .sp-thumb[data-sp-image=failed] img,${H} .sp-thumb[data-sp-image=loading] img{visibility:hidden}
${H} .sp-ph{position:absolute;inset:0;display:grid;place-content:center;gap:4px;padding:8px;text-align:center;color:var(--muted,#7190a0)}
${H} .sp-ph b{color:var(--text,#d8edf7);font-weight:600;letter-spacing:.04em}
${H} .sp-thumb[data-sp-image=ready] .sp-ph{display:none}
${H} .sp-cap{display:grid;gap:1px;margin:7px 2px 7px;min-width:0}
${H} .sp-title{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
${H} .sp-meta{color:var(--muted,#7190a0);font-size:11px;font-variant-numeric:tabular-nums}
${H} .sp-actions{display:grid;grid-template-columns:1fr 1fr;gap:6px}
${H} .sp-actions button[data-sp-act=send]{grid-column:1/-1}
${H} .sp-actions button{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:32px;padding:0 8px;
  border:1px solid var(--line,#183343);border-radius:7px;background:rgba(3,14,20,.9);color:var(--text,#d8edf7);font:inherit;cursor:pointer;
  transition:border-color var(--shell-dur-fast,120ms) var(--shell-ease,ease),background var(--shell-dur-fast,120ms) var(--shell-ease,ease)}
${H} .sp-actions button:hover{border-color:var(--shell-stroke-active,rgba(110,231,255,.5));background:rgba(110,231,255,.07)}
${H} .sp-actions button[data-sp-act=send]{border-color:color-mix(in srgb,var(--accent,#6ee7ff) 45%,transparent);color:var(--accent,#6ee7ff)}
${H} .sp-actions button[data-sp-act=delete]{color:var(--danger,#ff6577)}
${H} .sp-actions button[data-sp-act=delete]:hover{border-color:color-mix(in srgb,var(--danger,#ff6577) 55%,transparent);background:rgba(255,101,119,.08)}
${H} .sp-actions button[aria-disabled=true]{opacity:.55;cursor:progress}
${H} .sp-actions svg{flex:none;width:14px;height:14px}
${H} .sp-close{position:absolute;top:12px;right:12px;width:32px;height:32px;display:grid;place-items:center;padding:0;border:1px solid var(--line,#183343);
  border-radius:7px;background:rgba(3,10,15,.86);color:var(--muted,#7190a0);font:inherit;font-size:14px;cursor:pointer}
${H} .sp-close:hover{color:var(--text,#d8edf7)}
${H} .sp-note{margin:7px 2px 0;padding:6px 8px;border:1px solid color-mix(in srgb,var(--sem-problem,#ff6a4d) 55%,transparent);border-radius:7px;
  background:rgba(35,7,12,.9);font-size:11.5px;overflow-wrap:anywhere}
${H} .sp-note[hidden]{display:none}
${H} .sp-time{position:absolute;left:10px;right:10px;bottom:3px;height:2px;border-radius:2px;overflow:hidden;background:rgba(110,231,255,.12)}
${H} .sp-time i{position:absolute;inset:0;transform-origin:left;background:var(--accent,#6ee7ff);opacity:.7;
  animation:spTime var(--sp-ms,6000ms) linear forwards}
${H} .sp-card[data-sp-paused] .sp-time i{animation:none;transform:none;opacity:.35}
@keyframes spTime{from{transform:scaleX(1)}to{transform:scaleX(0)}}
.sp-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
${L} .sp-lb{display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:10px;width:fit-content;min-width:min(420px,92vw);max-width:min(92vw,1400px);max-height:92vh;padding:12px;
  background:var(--solid,#070d13);border:1px solid var(--line,#183343);border-radius:12px;box-shadow:0 34px 90px rgba(0,0,0,.65)}
${L} .sp-lb:focus{outline:none}
${L} header{display:flex;align-items:center;justify-content:space-between;gap:12px;min-width:0}
${L} h2{margin:0;font-size:13px;font-weight:600;letter-spacing:.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
${L} .sp-lb-img{display:grid;place-items:center;min-height:120px;overflow:hidden;border-radius:8px;background:#03080c}
${L} .sp-lb-img img{max-width:100%;max-height:calc(92vh - 120px);object-fit:contain;display:block}
${L} .sp-lb-img .sp-ph{padding:24px;color:var(--muted,#7190a0);text-align:center}
${L} footer{display:flex;justify-content:flex-end;gap:8px}
${L} a,${L} button{display:inline-flex;align-items:center;gap:6px;min-height:32px;padding:0 12px;border:1px solid var(--line,#183343);border-radius:7px;
  background:rgba(3,14,20,.9);color:var(--text,#d8edf7);font:inherit;font-size:12.5px;text-decoration:none;cursor:pointer}
${L} a{border-color:color-mix(in srgb,var(--accent,#6ee7ff) 45%,transparent);color:var(--accent,#6ee7ff)}
${L} a:focus-visible,${L} button:focus-visible{outline:2px solid var(--shell-focus,#6ee7ff);outline-offset:2px}
@media(prefers-reduced-motion:reduce){
  ${H} .sp-card{animation:none}
  ${H} .sp-time i{animation:none;transform:none}
  ${H} .sp-actions button{transition:none}
}
@media(forced-colors:active){
  ${H} .sp-card,${H} .sp-actions button,${H} .sp-close,${H} .sp-thumb,${L} .sp-lb,${L} a,${L} button{border:1px solid ButtonText}
  ${H} .sp-time i{forced-color-adjust:none;background:Highlight}
  ${H} .sp-note{border-color:CanvasText}
}`;

  const SVG_NS='http://www.w3.org/2000/svg';
  const ICONS=Object.freeze({
    open:'M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4',
    send:'M2 8l12-6-5 12-2-5z',
    delete:'M3 4h10M6 4V2.5h4V4M4.5 4l.8 9.5h5.4l.8-9.5',
  });
  function icon(name){
    const svg=document.createElementNS(SVG_NS,'svg');
    svg.setAttribute('viewBox','0 0 16 16');svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');
    const path=document.createElementNS(SVG_NS,'path');
    path.setAttribute('d',ICONS[name]);path.setAttribute('fill','none');path.setAttribute('stroke','currentColor');
    path.setAttribute('stroke-width','1.5');path.setAttribute('stroke-linejoin','round');path.setAttribute('stroke-linecap','round');
    svg.appendChild(path);return svg;
  }
  const log=(level,key,data)=>{
    const line=`[screenshot_preview] ${key} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);
    else if(level==='warn')console.warn(line);
    else console.info(line);
  };
  function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n}

  /* Le code d'un payload illisible : une lecture d'UN octet (plage), jamais l'image entière. */
  async function probe(url){
    const ctl=typeof AbortController==='function'?new AbortController():null;
    const timer=setTimeout(()=>{if(ctl)ctl.abort()},TIMING.probeMs);
    try{
      const response=await fetch(url,{headers:{Range:'bytes=0-0'},cache:'no-store',signal:ctl?ctl.signal:undefined});
      if(response.ok)return 'payload_unreadable';
      const body=await response.json().catch(()=>null);
      return body&&body.error&&typeof body.error.code==='string'?body.error.code:`http_${response.status}`;
    }catch(error){return error&&error.name==='AbortError'?'payload_timeout':'network_error'}
    finally{clearTimeout(timer)}
  }
  async function deleteArtifact(id){
    const ctl=typeof AbortController==='function'?new AbortController():null;
    const timer=setTimeout(()=>{if(ctl)ctl.abort()},TIMING.deleteMs);
    let response;
    try{response=await fetch(`/api/artifacts/${encodeURIComponent(id)}`,{method:'DELETE',signal:ctl?ctl.signal:undefined})}
    catch(error){throw {code:error&&error.name==='AbortError'?'client_timeout':'network_error',status:0}}
    finally{clearTimeout(timer)}
    const body=await response.json().catch(()=>null);
    if(!response.ok){
      const err=body&&body.error;
      throw {code:err&&typeof err.code==='string'?err.code:`http_${response.status}`,status:response.status,
        message:err&&typeof err.message==='string'?err.message:''};
    }
    return body;
  }

  /* ------------------------------------------------- la visionneuse (rang 60, motif `.overlay`) */
  function createLightbox(){
    const back=el('div','overlay');back.id=DOM.lightboxId;
    const box=el('div','sp-lb');box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');box.tabIndex=-1;
    const head=el('header'),title=el('h2'),close=el('button','sp-lb-close','Fermer');close.type='button';
    title.id=DOM.lightboxId+'Title';box.setAttribute('aria-labelledby',title.id);
    head.append(title,close);
    const frame=el('div','sp-lb-img'),img=el('img'),ph=el('div','sp-ph');
    img.decoding='async';ph.hidden=true;frame.append(img,ph);
    const foot=el('footer'),tab=el('a','sp-lb-tab','Ouvrir dans un onglet');
    tab.target='_blank';tab.rel='noopener noreferrer';
    foot.append(tab);
    box.append(head,frame,foot);back.appendChild(box);
    document.body.appendChild(back);
    const L={open:false,onClose:null,previous:null,id:null};
    img.addEventListener('error',()=>{
      if(!L.open)return;
      const id=L.id;ph.hidden=false;ph.textContent='Image indisponible…';
      probe(payloadUrl(id)).then(code=>{if(L.open&&L.id===id){ph.textContent=payloadText(code);log('warn','lightbox_payload_failed',{artifact_id:id,code})}});
    });
    img.addEventListener('load',()=>{ph.hidden=true});
    function shut(reason){
      if(!L.open)return;
      L.open=false;back.classList.remove('open');back.hidden=true;img.removeAttribute('src');
      const done=L.onClose,previous=L.previous,id=L.id;L.onClose=null;L.previous=null;L.id=null;
      log('info','lightbox_closed',{artifact_id:id,reason});
      if(previous&&previous.isConnected&&typeof previous.focus==='function')try{previous.focus({preventScroll:true})}catch(_error){/* disparu */}
      if(typeof done==='function')try{done()}catch(error){log('error','lightbox_close_failed',{error:String(error)})}
    }
    function show({id,title:text,onClose}){
      if(L.open)shut('replaced');
      L.open=true;L.id=id;L.onClose=onClose||null;L.previous=document.activeElement;
      title.textContent=text;
      img.alt=text;ph.hidden=true;img.src=payloadUrl(id);tab.href=payloadUrl(id);
      back.hidden=false;back.classList.add('open');
      close.focus({preventScroll:true});
      log('info','lightbox_opened',{artifact_id:id});
    }
    close.addEventListener('click',()=>shut('close'));
    back.addEventListener('mousedown',event=>{if(event.target===back){event.preventDefault();shut('backdrop')}});
    back.addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();shut('escape');return}
      if(event.key==='Tab'){
        const stops=[close,tab];const at=stops.indexOf(document.activeElement);
        event.preventDefault();
        stops[(at+(event.shiftKey?stops.length-1:1))%stops.length].focus();
      }
    });
    back.hidden=true;
    return {show,shut,isOpen:()=>L.open,id:()=>L.id};
  }

  function installScreenshotPreview(){
    const host=document.getElementById(DOM.hostId);
    if(!host)
      throw Object.assign(new Error(`JarvisScreenshotPreview : l’emplacement #${DOM.hostId} manque dans control_center.html`),
        {code:'screenshot_preview_host_missing'});
    if(!document.getElementById(DOM.styleId)){
      const style=document.createElement('style');style.id=DOM.styleId;style.textContent=STYLE;
      document.head.appendChild(style);
    }
    const live=el('span','sp-sr');live.id=DOM.liveId;live.setAttribute('role','status');live.setAttribute('aria-live','polite');
    document.body.appendChild(live);
    const say=text=>{live.textContent='';setTimeout(()=>{live.textContent=text},30)};
    const lightbox=createLightbox();

    host.textContent='';host.hidden=true;
    host.setAttribute('role','region');host.setAttribute('aria-label','Aperçu de la capture d’écran');
    const card=el('figure','sp-card');
    const thumb=el('button','sp-thumb');thumb.type='button';
    const img=el('img');img.decoding='async';img.loading='lazy';
    const ph=el('span','sp-ph');const phType=el('b'),phText=el('span');ph.append(phType,phText);
    thumb.append(img,ph);
    const cap=el('figcaption','sp-cap'),title=el('span','sp-title'),meta=el('span','sp-meta');cap.append(title,meta);
    const actions=el('div','sp-actions');actions.setAttribute('role','group');actions.setAttribute('aria-label','Actions sur la capture');
    const button=(act,label,iconName)=>{const b=el('button');b.type='button';b.dataset.spAct=act;b.append(icon(iconName),document.createTextNode(label));return b};
    const openB=button('open','Ouvrir','open'),sendB=button('send','Envoyer à Jarvis','send'),deleteB=button('delete','Supprimer','delete');
    const deleteLabel=deleteB.lastChild;let busyTick=0;
    actions.append(sendB,openB,deleteB);
    const close=el('button','sp-close','×');close.type='button';
    close.setAttribute('aria-label','Fermer l’aperçu (la capture reste enregistrée)');close.title='Fermer l’aperçu — la capture reste enregistrée';
    const note=el('p','sp-note');note.hidden=true;note.setAttribute('role','status');
    const hint=el('span','sp-sr','Se ferme seul après 6 secondes, sauf au survol ou au focus. Échap le ferme ; la capture reste enregistrée.');
    hint.id=DOM.hintId;
    const time=el('span','sp-time');time.setAttribute('aria-hidden','true');time.appendChild(el('i'));
    card.append(thumb,cap,actions,note,close,time,hint);
    card.setAttribute('aria-describedby',DOM.hintId);
    card.style.setProperty('--sp-ms',`${TIMING.dismissMs}ms`);
    host.appendChild(card);

    let thumbTimer=0,shownSeq=-1,barDeadline=null;
    /* Le minuteur visuel repart quand le délai repart (nouvel aperçu, relâchement), jamais à un autre rendu. */
    function restartBar(){const bar=time.firstChild;bar.style.animation='none';void bar.offsetWidth;bar.style.animation=''}
    const controller=createPreviewController({
      later:(fn,ms)=>setTimeout(fn,ms),unlater:id=>clearTimeout(id),now:()=>Date.now(),log,
      dismissMs:TIMING.dismissMs,
      onChange:render,
      actions:{
        confirm:item=>typeof window.confirmDialog==='function'
          ?window.confirmDialog({title:'Supprimer cette capture d’écran ?',danger:true,confirmLabel:'Supprimer',
            lines:[[item.title,''],'Le fichier est retiré de Jarvis. Cette action est définitive.']})
          :Promise.reject(new Error('confirmDialog absent')),
        remove:id=>deleteArtifact(id).then(answer=>{if(lightbox.isOpen()&&lightbox.id()===id)lightbox.shut('deleted');return answer}),
        attach:spec=>{
          const chat=window.JarvisChat;
          if(!chat||typeof chat.attachExisting!=='function')return {ok:false,code:'chat_unavailable'};
          return chat.attachExisting(spec);
        },
        openLightbox:(item,onClose)=>lightbox.show({id:item.artifactId,title:item.title,onClose}),
        say,
      },
    });

    function render(v){
      if(!v.shown){
        if(busyTick){clearInterval(busyTick);busyTick=0}deleteLabel.textContent='Supprimer';
        if(thumbTimer){clearTimeout(thumbTimer);thumbTimer=0}
        const hadFocus=host.contains(document.activeElement);
        host.hidden=true;img.removeAttribute('src');shownSeq=-1;barDeadline=null;
        /* Jamais de focus laissé sur un élément caché : la roue (l'outil qui a pris la capture) le reprend. */
        if(hadFocus){
          const W=window.JarvisToolWheel;
          if(W&&typeof W.focusAnchor==='function')W.focusAnchor();else document.activeElement.blur();
        }
        return;
      }
      const item=v.item;
      if(v.seq!==shownSeq){
        shownSeq=v.seq;
        title.textContent=item.title;
        meta.textContent=[item.width&&item.height?`${item.width}×${item.height}`:'',sizeText(item.size)].filter(Boolean).join(' · ');
        img.alt=`${item.title}${item.width&&item.height?`, ${item.width} × ${item.height}`:''}`;
        thumb.setAttribute('aria-label',`Ouvrir ${item.title} en grand`);
        phType.textContent=`Capture d’écran · ${item.type}`;phText.textContent='Chargement de l’aperçu…';
        img.src=item.url;
        if(thumbTimer)clearTimeout(thumbTimer);
        thumbTimer=setTimeout(()=>{thumbTimer=0;if(controller.view().image==='loading')controller.imageFailed(item.artifactId,'payload_timeout')},
          TIMING.thumbDeadlineMs);
        host.hidden=false;
        say(`${item.title} enregistrée. Aperçu affiché : Envoyer à Jarvis, Ouvrir ou Supprimer.`);
      }
      thumb.dataset.spImage=v.image;
      if(v.image==='failed')phText.textContent=payloadText(v.imageCode);
      card.toggleAttribute('data-sp-paused',v.paused);
      if(v.deadline!==barDeadline){barDeadline=v.deadline;if(v.deadline!==null)restartBar()}
      deleteB.setAttribute('aria-disabled',String(v.busy==='delete'));
      const waiting=v.busy==='delete'&&v.busySince!==null;
      deleteLabel.textContent=waiting?`Suppression… ${Math.max(0,Math.floor((Date.now()-v.busySince)/1000))} s`:'Supprimer';
      if(waiting&&!busyTick)busyTick=setInterval(()=>render(controller.view()),1000);
      if(!waiting&&busyTick){clearInterval(busyTick);busyTick=0}
      sendB.setAttribute('aria-disabled',String(!!v.busy));
      note.hidden=!v.note;
      note.textContent=v.note?v.note.text:'';
    }

    img.addEventListener('load',()=>{const item=controller.current();if(item&&img.src.endsWith(item.url)){
      if(thumbTimer){clearTimeout(thumbTimer);thumbTimer=0}controller.imageReady(item.artifactId)}});
    img.addEventListener('error',()=>{
      const item=controller.current();if(!item||!img.getAttribute('src'))return;
      if(thumbTimer){clearTimeout(thumbTimer);thumbTimer=0}
      probe(item.url).then(code=>controller.imageFailed(item.artifactId,code));
    });
    thumb.addEventListener('click',()=>controller.open());
    openB.addEventListener('click',()=>controller.open());
    sendB.addEventListener('click',()=>{if(sendB.getAttribute('aria-disabled')!=='true')controller.send()});
    deleteB.addEventListener('click',()=>{controller.remove()});
    close.addEventListener('click',()=>controller.dismiss('close'));
    for(const [on,off] of [['mouseenter','mouseleave'],['pointerenter','pointerleave']]){
      card.addEventListener(on,()=>controller.hold('hover'));
      card.addEventListener(off,()=>controller.release('hover'));
    }
    card.addEventListener('focusin',()=>controller.hold('focus'));
    card.addEventListener('focusout',event=>{if(!card.contains(event.relatedTarget))controller.release('focus')});
    /* Échap ferme l'aperçu quand il est la surface du moment : focus dedans, pointeur dessus, ou rien d'autre
       n'a pris la touche (focus sur la page). La visionneuse, le Chat, les menus la prennent avant. */
    window.addEventListener('keydown',event=>{
      if(event.key!=='Escape'||event.defaultPrevented||!controller.current()||lightbox.isOpen())return;
      const active=document.activeElement;
      const mine=host.contains(active),idle=!active||active===document.body||active===document.documentElement;
      if(!mine&&!idle&&!controller.view().holds.includes('hover'))return;
      event.preventDefault();controller.dismiss('escape');
    });

    const C=window.JarvisCaptureRail;
    if(C&&typeof C.subscribe==='function')C.subscribe(view=>controller.accept(view));
    else log('warn','capture_controller_missing',{});

    window.JarvisScreenshotPreview=Object.freeze({
      /* Rail de l'espace de travail (Slice 07) : `{artifact_id, url, title}` ; l'URL est reconstruite depuis l'id. */
      openLightbox(spec){
        const id=spec&&typeof spec.artifact_id==='string'?spec.artifact_id:'';
        if(!ID.test(id))throw Object.assign(new Error('JarvisScreenshotPreview.openLightbox : artifact_id invalide'),{code:'invalid_artifact_id'});
        if(spec.url&&spec.url!==payloadUrl(id))log('warn','lightbox_url_ignored',{artifact_id:id});
        const text=typeof spec.title==='string'&&spec.title.trim()?spec.title.trim().slice(0,120):'Image';
        const item=controller.current();
        /* La capture de l'aperçu : même chemin que son bouton « Ouvrir » (le délai attend la fermeture). */
        if(item&&item.artifactId===id)return controller.open();
        lightbox.show({id,title:text});
        return true;
      },
      closeLightbox:()=>lightbox.shut('api'),
      view:()=>controller.view(),
      dismiss:()=>controller.dismiss('api'),
    });
    log('info','installed',{host:DOM.hostId,dismiss_ms:TIMING.dismissMs});
  }

  try{installScreenshotPreview()}
  catch(error){
    console.error('[screenshot_preview] install_failed '
      +JSON.stringify({code:(error&&error.code)||null,error:String((error&&error.message)||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
