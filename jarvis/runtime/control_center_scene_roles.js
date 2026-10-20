/* Rôles et relations d'agent dans la scène constellation (jarvis-organic-agent-orchestration, Slice 09).

   Ce que `control_center_scene_page.js` dessine pour la Slice 08, sans y ajouter de logique d'exécution :
   - la **pastille de rôle** d'une étoile `agent` (icône + badge + accent du registre, D02 ; drapeau du
     responsable de mission, D03 ; origine de la mission et « état inconnu », lus dans `GET /api/missions/{id}`) ;
   - la **grammaire des fils** des cinq relations (D09) : délégation (trait plein, flèche pleine), contrôle qualité
     (tirets, chevron ouvert, du relecteur vers le relu, D11), relais (perles, double chevron, du prédécesseur vers
     le successeur, D14), confrontation (double rail sans flèche entre pairs, D10), échange entre agents (trait fin,
     pastille bulle, D13) — jamais la couleur seule : trait, flèche, forme et pictogramme de la pastille, libellé ;
   - la **pastille de relation**, un vrai bouton posé sur ses fils, qui ouvre le tableau de la relation
     (`control_center_relation_board.js`) ;
   - le cache des missions lues (`createMissionCache`) : origine, statut, `live_unknown` (jamais « en cours »).

   Lecture seule : aucune écriture, aucune route nouvelle. Tout texte entre par `textContent` ; les seuls
   fragments SVG posés en markup sont les pictogrammes constants de `JarvisRoleIdentity`.
   Contrat : `docs/scene-model.md` › *Interface: roles and relations*. */
(function(root){
  'use strict';
  const Identity=root.JarvisRoleIdentity||(typeof require==='function'?require('./control_center_role_identity.js'):null);
  const SVG_NS='http://www.w3.org/2000/svg';
  const KINDS=Identity.RELATION_KINDS;
  const MARKED=Object.freeze({delegation:'sc-mk-delegation',qa:'sc-mk-qa',handoff:'sc-mk-handoff'});
  const MISSION_REFRESH_MS=15000;
  const MISSION_RETRY_MS=30000;
  const MISSION_LIMIT=32;
  /* Origine d'une mission (`origin_kind`, le profil `[code]`/`[general]`… du Mission Owner) en mots. */
  const ORIGIN_LABELS=Object.freeze({code:'code',general:'général',desktop:'poste de travail',fast:'tâche rapide'});

  /* Feuille de style : jetons de relation, pastilles, fils, marqueurs, couleurs forcées. Aucun rang de page ici
     (le calque des pastilles a le sien dans `control_center_scene_page.js`, rang contenu `.sc-`). */
  const STYLE=`
.scene{--sc-rel-delegation:#a9c3d4;--sc-rel-communication:#5fd6e8;--sc-rel-adversary:#ff7f63;--sc-rel-qa:#c8ea6e;--sc-rel-handoff:#c9a6ff;--sc-rel-gap:#050c12}
.scene .sc-node.sc-has-role{--tone:var(--sc-role,#a3b6c4)}
.sc-role{position:absolute;right:calc(50% + 10px);top:calc(50% - 8px);display:flex;align-items:center;gap:3px;height:16px;padding:0 5px 0 3px;
  border-radius:4px;background:#061017;color:var(--sc-role,#a3b6c4);font-size:9.5px;font-weight:700;line-height:1;letter-spacing:.06em;
  white-space:nowrap;pointer-events:none;box-shadow:0 0 0 1px color-mix(in srgb,var(--sc-role,#a3b6c4) 72%,transparent),0 2px 8px rgba(0,0,0,.5)}
.sc-role svg{flex:none;width:11px;height:11px}
.sc-role b{font-weight:700}
.sc-role i{font-style:normal;font-weight:500;letter-spacing:.02em;color:var(--sc-ink);max-width:14ch;overflow:hidden;text-overflow:ellipsis}
.sc-role-owner{background:color-mix(in srgb,var(--sc-role,#a3b6c4) 26%,#061017);box-shadow:0 0 0 1.5px var(--sc-role,#a3b6c4),0 2px 8px rgba(0,0,0,.5)}
.sc-role-owner .sc-role-flag{color:#f4fbfe}
.sc-role-unknown{box-shadow:0 0 0 1px rgba(163,182,196,.7),0 2px 8px rgba(0,0,0,.5);border:1px dashed rgba(163,182,196,.9);padding:0 4px 0 2px}
.sc-role-lost .sc-role-state{color:var(--sc-warn);max-width:none}
.sc-capsule .sc-role{position:relative;right:auto;top:auto;flex:none}
.scene.sc-roles-compact .sc-role{gap:2px;padding:0 4px 0 2px}
.scene.sc-roles-compact .sc-role-origin{display:none}
.sc-link.sc-link-delegation{stroke:var(--sc-rel-delegation);stroke-width:1.5;stroke-dasharray:none;marker-end:url(#sc-mk-delegation)}
.sc-link.sc-link-qa{stroke:var(--sc-rel-qa);stroke-width:1.6;stroke-dasharray:7 4;marker-end:url(#sc-mk-qa)}
.sc-link.sc-link-handoff{stroke:var(--sc-rel-handoff);stroke-width:3.2;stroke-dasharray:.1 6.5;stroke-linecap:round;marker-end:url(#sc-mk-handoff)}
.sc-link.sc-link-adversary{stroke:var(--sc-rel-adversary);stroke-width:6.4;stroke-dasharray:none}
.sc-link.sc-link-adversary-gap{stroke:var(--sc-rel-gap);stroke-width:2.4;stroke-dasharray:none}
.sc-link.sc-link-communication{stroke:var(--sc-rel-communication);stroke-width:1.4;stroke-dasharray:none}
.sc-link.sc-rel-closed{opacity:.55}
.sc-mk{stroke-linecap:round;stroke-linejoin:round}
.sc-mk-delegation{fill:var(--sc-rel-delegation)}
.sc-mk-qa{fill:none;stroke:var(--sc-rel-qa);stroke-width:1.9}
.sc-mk-handoff{fill:none;stroke:var(--sc-rel-handoff);stroke-width:1.9}
.sc-relmark{--sc-rel:var(--sc-muted);position:absolute;left:0;top:0;width:24px;height:24px;margin:-12px 0 0 -12px;padding:0;
  display:grid;place-items:center;border:1.5px solid var(--sc-rel);border-radius:50%;background:#061017;color:var(--sc-rel);
  cursor:pointer;pointer-events:auto;box-shadow:0 2px 10px rgba(0,0,0,.6);font:inherit}
.sc-relmark svg{width:14px;height:14px;pointer-events:none}
.sc-relmark:hover{background:color-mix(in srgb,var(--sc-rel) 26%,#061017)}
.sc-relmark:focus-visible{outline:2px solid var(--sc-ink);outline-offset:2px}
.sc-relmark[aria-expanded="true"]{outline:2px solid var(--sc-rel);outline-offset:3px}
.sc-relmark-delegation{--sc-rel:var(--sc-rel-delegation)}
.sc-relmark-qa{--sc-rel:var(--sc-rel-qa);border-radius:6px}
.sc-relmark-handoff{--sc-rel:var(--sc-rel-handoff);width:30px;margin-left:-15px;border-radius:12px}
.sc-relmark-adversary{--sc-rel:var(--sc-rel-adversary);border-width:2.5px;border-style:double;border-radius:5px;transform-origin:center}
.sc-relmark-communication{--sc-rel:var(--sc-rel-communication);width:30px;margin-left:-15px;border-radius:13px 13px 13px 3px;
  background:color-mix(in srgb,var(--sc-rel) 18%,#061017)}
.sc-relmark.sc-rel-closed{border-style:dashed;opacity:.86}
.sc-relmark.sc-rel-closed.sc-relmark-adversary{border-style:dashed}
.scene.sc-ready .sc-relmark{transition:transform .42s cubic-bezier(.16,1,.3,1)}
.sc-relmark.sc-relmark-following{visibility:hidden}
/* Graphe dense ou fenêtre étroite : pastilles de 18 px (la page le décide, \`sc-relmarks-compact\`). */
.sc-relmarks-compact .sc-relmark{width:18px;height:18px;margin:-9px 0 0 -9px;border-width:1.25px}
.sc-relmarks-compact .sc-relmark svg{width:11px;height:11px}
.sc-relmarks-compact .sc-relmark-handoff,.sc-relmarks-compact .sc-relmark-communication{width:24px;margin-left:-12px}
.sc-relmarks-compact .sc-relmark-adversary{border-width:2.5px}
@media (prefers-reduced-motion:reduce){.scene .sc-relmark{transition:none}}
@media (forced-colors:active){
  .sc-link.sc-link-delegation,.sc-link.sc-link-qa,.sc-link.sc-link-handoff,.sc-link.sc-link-adversary,.sc-link.sc-link-communication{stroke:CanvasText}
  .sc-link.sc-link-adversary-gap{stroke:Canvas}
  .sc-mk-delegation{fill:CanvasText}
  .sc-mk-qa,.sc-mk-handoff{stroke:CanvasText}
  .sc-relmark{forced-color-adjust:none;background:Canvas;color:CanvasText;border-color:CanvasText;box-shadow:none}
  .sc-relmark:hover{background:Canvas;color:Highlight;border-color:Highlight}
  .sc-relmark:focus-visible,.sc-relmark[aria-expanded="true"]{outline:3px solid Highlight}
  .sc-role,.sc-role-owner{forced-color-adjust:none;background:Canvas;color:CanvasText;box-shadow:none;border:1px solid CanvasText}
  .sc-role-owner{border-width:2px}
  .sc-role i,.sc-role-owner .sc-role-flag{color:CanvasText}
}`;

  /* Les marqueurs de bout des relations dirigées, posés une fois dans le SVG des fils. Unités de l'espace
     utilisateur : la pointe s'arrête 14 px avant le centre de l'étoile visée, hors de sa marque. */
  function markerDefs(doc){
    const defs=doc.createElementNS(SVG_NS,'defs');
    const marker=(id,d,cls)=>{
      const m=doc.createElementNS(SVG_NS,'marker');
      for(const [k,v] of Object.entries({id,viewBox:'0 0 12 12',refX:'25',refY:'6',markerWidth:'12',markerHeight:'12',
        markerUnits:'userSpaceOnUse',orient:'auto'}))m.setAttribute(k,v);
      const path=doc.createElementNS(SVG_NS,'path');
      path.setAttribute('d',d);path.setAttribute('class',`sc-mk ${cls}`);
      m.appendChild(path);
      return m;
    };
    defs.append(marker(MARKED.delegation,'M1 1.5 11.2 6 1 10.5z','sc-mk-delegation'),
      marker(MARKED.qa,'M2.5 1.8 10.8 6 2.5 10.2','sc-mk-qa'),
      marker(MARKED.handoff,'M1 2.2 5.6 6 1 9.8M6 2.2 10.6 6 6 9.8','sc-mk-handoff'));
    return defs;
  }

  /* Les éléments d'un fil : un seul, sauf la confrontation (double rail : le rail, puis son creux). */
  function linkParts(edge){
    if(edge.kind==='adversary')return ['sc-link-adversary','sc-link-adversary-gap'];
    return [null];
  }
  function relationClass(edge){
    return edge.relationId?` sc-rel sc-rel-${edge.state==='closed'?'closed':'open'}`:'';
  }

  const el=(doc,tag,cls,text)=>{const e=doc.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e};
  function svgFragment(doc,markup){
    const holder=doc.createElement('span');
    holder.innerHTML=markup;  // pictogrammes constants de JarvisRoleIdentity, jamais un texte reçu
    return holder.firstChild;
  }

  /* Pastille de rôle d'un nœud (`node.role` de `JarvisSceneLayout.viewModel`). Décorative : le rôle, la
     responsabilité, l'origine et l'état inconnu sont dits dans le nom accessible du nœud. `accentOf(token)`
     valide le jeton d'accent ; la couleur est la variable `--role-accent-<jeton>` de la page. */
  function rolePill(doc,role,accentOf){
    const pill=el(doc,'span','sc-role'+(role.owner?' sc-role-owner':'')+(role.known?'':' sc-role-unknown')+(role.liveUnknown?' sc-role-lost':''));
    pill.setAttribute('aria-hidden','true');
    const token=typeof accentOf==='function'?accentOf(role.accent):(Identity.TOKEN.test(role.accent)?role.accent:'slate');
    pill.style.setProperty('--sc-role',`var(--role-accent-${token})`);
    if(role.owner){const flag=svgFragment(doc,Identity.iconSvg('flag','sc-role-flag'));pill.appendChild(flag)}
    pill.appendChild(svgFragment(doc,Identity.iconSvg(role.icon,'sc-role-glyph')));
    pill.appendChild(el(doc,'b','',role.badge));
    if(role.owner&&role.origin)pill.appendChild(el(doc,'i','sc-role-origin',`· ${originLabel(role.origin)}`));
    if(role.liveUnknown)pill.appendChild(el(doc,'i','sc-role-state','· état inconnu'));
    return pill;
  }
  /* Boîte (estimée, en pixels de scène) de la pastille de rôle d'une étoile dessinée en point : à gauche de
     l'étoile, 16 px de haut. Sert aux pastilles de relation pour l'éviter. */
  function rolePillBox(node){
    const role=node.role,extra=[role.owner&&role.origin?originLabel(role.origin):'',role.liveUnknown?'état inconnu':''].filter(Boolean).join(' · ');
    const width=22+6.4*String(role.badge||'').length+(role.owner?14:0)+(extra?Math.min(14,extra.length+2)*5.6:0);
    return {left:node.cx-10-width,top:node.cy-8,width,height:16};
  }
  const accentVar=(role,accentOf)=>`var(--role-accent-${typeof accentOf==='function'?accentOf(role.accent):'slate'})`;
  function originLabel(origin){return Object.prototype.hasOwnProperty.call(ORIGIN_LABELS,origin)?ORIGIN_LABELS[origin]:origin}

  /* Pastille d'une relation : un vrai bouton (clavier, lecteur d'écran), sa nature dans sa forme et son
     pictogramme, son état dans son trait (tirets : close). `label` : nom accessible complet. */
  function fillMark(doc,button,mark,label){
    button.type='button';
    button.className=`sc-relmark sc-relmark-${Object.prototype.hasOwnProperty.call(KINDS,mark.kind)?mark.kind:'other'} sc-rel-${mark.state==='closed'?'closed':'open'}`;
    button.dataset.relationId=mark.id;
    button.dataset.relationKind=mark.kind;
    if(mark.missionId)button.dataset.missionId=mark.missionId;else delete button.dataset.missionId;
    button.setAttribute('aria-label',label);
    button.setAttribute('aria-haspopup','dialog');
    if(!button.hasAttribute('aria-expanded'))button.setAttribute('aria-expanded','false');
    button.title=label;
    button.replaceChildren(svgFragment(doc,Identity.relationGlyphSvg(mark.kind,'sc-relmark-glyph')));
  }

  /* Les mots d'une pastille pour `JarvisSceneLayout.relationMarkLabel`. `relationLabel(kind)` : le libellé servi
     par le registre quand il est lu. */
  function markWords(relationLabel){
    return {kind:kind=>typeof relationLabel==='function'?relationLabel(kind):Identity.label(KINDS,kind,{label:kind}).label,
      verb:kind=>Object.prototype.hasOwnProperty.call(KINDS,kind)?KINDS[kind].verb:'avec',
      state:state=>Identity.label(Identity.STATE_LABELS,state,''),
      outcome:outcome=>Identity.label(Identity.OUTCOME_LABELS,outcome)};
  }

  /* Missions lues pour les étoiles dessinées : `GET /api/missions/{id}` rend l'arbre entier (toutes ses missions
     sont retenues). `info(id)` rend `{origin, status, liveUnknown, objective}` ou `null`, et lance une lecture si
     besoin : jamais plus d'une en vol par mission, relue toutes les 15 s tant qu'elle est ouverte, 30 s après un
     échec (consigné une fois par mission). `onChange()` quand une valeur affichée change. */
  function createMissionCache(options){
    const opts=options||{};
    const now=typeof opts.now==='function'?opts.now:()=>Date.now();
    const log=typeof opts.log==='function'?opts.log:()=>{};
    const setTimer=opts.setInterval||((fn,ms)=>root.setInterval?root.setInterval(fn,ms):null);
    const clearTimer=opts.clearInterval||(id=>{if(id!=null&&root.clearInterval)root.clearInterval(id)});
    const entries=new Map();
    let ticker=null;
    function entry(id){
      let e=entries.get(id);
      if(!e){
        if(entries.size>=MISSION_LIMIT){const oldest=entries.keys().next().value;entries.delete(oldest)}
        e={info:null,at:0,failedAt:0,inflight:false,warned:false};entries.set(id,e);
      }
      return e;
    }
    function accept(body,at){
      const missions=body&&Array.isArray(body.missions)?body.missions:null;
      if(!missions){const e=new Error('Réponse de mission hors contrat (missions absent).');e.code='mission_payload_invalid';throw e}
      let changed=false;
      for(const m of missions){
        if(!m||typeof m.mission_id!=='string')continue;
        const info={origin:typeof m.origin_kind==='string'?m.origin_kind:'',status:typeof m.status==='string'?m.status:'',
          liveUnknown:m.live_unknown===true,objective:typeof m.objective==='string'?m.objective:''};
        const e=entry(m.mission_id);
        if(JSON.stringify(e.info)!==JSON.stringify(info)){e.info=info;changed=true}
        e.at=at;e.failedAt=0;e.warned=false;
      }
      return changed;
    }
    function read(id,e){
      if(typeof opts.fetchJson!=='function')return;
      e.inflight=true;
      Promise.resolve().then(()=>opts.fetchJson('/api/missions/'+encodeURIComponent(id))).then(body=>{
        const changed=accept(body,now());
        if(changed&&typeof opts.onChange==='function')opts.onChange();
        arm();
      },error=>{
        e.failedAt=now();
        if(!e.warned){e.warned=true;log('warn','scene.mission_unreadable',{mission_id:id,code:error&&error.code||'',error:String(error&&error.message||error)})}
      }).finally(()=>{e.inflight=false});
    }
    function due(e,t){
      if(e.inflight)return false;
      if(!e.info)return !e.failedAt||t-e.failedAt>=MISSION_RETRY_MS;
      return e.info.status==='open'&&t-e.at>=MISSION_REFRESH_MS;
    }
    function info(id){
      if(!id)return null;
      const e=entry(id);
      if(due(e,now()))read(id,e);
      return e.info;
    }
    /* Une mission ouverte suivie : relue sans attendre un rendu (un `live_unknown` apparaît sans événement). */
    function arm(){
      if(ticker!=null)return;
      if(![...entries.values()].some(e=>e.info&&e.info.status==='open'))return;
      ticker=setTimer(()=>{
        const t=now();let open=false;
        for(const [id,e] of entries){if(e.info&&e.info.status==='open'){open=true;if(due(e,t))read(id,e)}}
        if(!open){clearTimer(ticker);ticker=null}
      },MISSION_REFRESH_MS);
    }
    /* La scène s'éteint : plus de relecture ni de mémoire ; une lecture en vol rendra sans effet visible. */
    function stop(){if(ticker!=null){clearTimer(ticker);ticker=null}entries.clear()}
    return {info,stop,entries};
  }

  const api=Object.freeze({STYLE,MARKED,ORIGIN_LABELS,markerDefs,linkParts,relationClass,rolePill,rolePillBox,accentVar,originLabel,
    fillMark,markWords,createMissionCache});
  root.JarvisSceneRoles=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
