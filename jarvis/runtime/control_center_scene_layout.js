/* Scène constellation : logique pure du rendu (handoff
   jarvis-constellation-scene-runtime, Slice 05).

   - Repère d'écran : origine (0, 0) au centre de la fenêtre, x vers la droite,
     y vers le bas, unités de scène. Le cadre de référence x ∈ [-160, 160],
     y ∈ [-90, 90] (16:9) est toujours entièrement visible : échelle uniforme
     `min(largeur / 320, hauteur / 180)` pixels par unité, centrée. Un autre
     rapport de fenêtre montre plus de scène sur l'axe long (pas de bandes).
     `geometry {x, y}` est le coin haut gauche de la boîte ; un point est
     dessiné au centre de sa boîte. Hors de la fenêtre, un objet n'est jamais
     déplacé (Décision 10) : il est compté « hors champ ».
   - AutoResolver contraint (Décisions 8–10) : épinglé par l'utilisateur, puis
     placement explicite (cerveau, utilisateur, résolveur déjà validé), puis
     résolveur. Il ne place que les objets sans géométrie et ne déplace rien
     d'autre. Déterministe pour une même entrée, travail borné.
   - Modèle de vue : ce que la page dessine, texte neutralisé (contrôles,
     marques bidi, caractères invisibles) pour un rendu par `textContent`.
   - Registre des validations du résolveur : une commande par objet, jamais de
     boucle.

   Aucune dépendance au DOM, au réseau ni à l'horloge : les tests l'exécutent
   avec node (`tests/unit/test_scene_renderer_logic.py`). Inséré tel quel dans
   la page par `ControlCenter.index` ; n'expose que `window.JarvisSceneLayout`. */
(function(root){
  'use strict';

  /* ------------------------------------------------------------------ repère */

  const FRAME=Object.freeze({halfWidth:160,halfHeight:90});
  /* Zone de composition sûre : la partie du cadre qu'aucune commande de la page
     ne recouvre à la plus petite taille 16:9 prise en charge (1280 × 720, 4 px
     par unité), dans les deux thèmes — barre du haut et dock Omega en haut,
     dock du thème circuit à droite, indication vocale et indicateurs de scène
     en bas. Plus grande fenêtre : les commandes y occupent encore moins
     d'unités. Le résolveur ne pose qu'ici ; le cerveau en reçoit les bornes.
     Même valeur dans `jarvis/domain/scene.py` (test de parité). */
  const SAFE_AREA=Object.freeze({x0:-152,x1:138,y0:-72,y1:68});
  /* Le visage (iframe ou canevas Omega) occupe le centre : le résolveur
     l'évite de préférence, sans l'interdire. */
  const FACE_ZONE=Object.freeze({x0:-34,x1:34,y0:-34,y1:34});
  const OBJECT_LIMIT=512;
  /* Taille par défaut d'un objet posé par le résolveur, en unités. */
  const DEFAULT_SIZE=Object.freeze({
    point:Object.freeze({w:6,h:6}),
    signal:Object.freeze({w:4,h:4}),
    capsule:Object.freeze({w:40,h:7}),
    window:Object.freeze({w:64,h:40}),
  });
  /* Travail maximal d'une passe (comparaisons de boîtes) : au-delà, les objets
     restants prennent leur premier emplacement admissible sans comparaison. */
  const WORK_BUDGET=400000;
  const MAX_ROOT_CANDIDATES=1200;

  /* Correspondance fenêtre ↔ scène pour une fenêtre de `width` × `height` px. */
  function viewport(width,height){
    const w=Math.max(1,Number(width)||0),h=Math.max(1,Number(height)||0);
    const scale=Math.min(w/(2*FRAME.halfWidth),h/(2*FRAME.halfHeight));
    return {width:w,height:h,scale,cx:w/2,cy:h/2,
      visible:{x0:-w/2/scale,x1:w/2/scale,y0:-h/2/scale,y1:h/2/scale}};
  }

  const round1=v=>Math.round(v*10)/10;

  /* Boîte en unités de scène → boîte en pixels de la fenêtre. */
  function toScreen(vp,box){
    return {left:round1(vp.cx+box.x*vp.scale),top:round1(vp.cy+box.y*vp.scale),
      width:round1(box.w*vp.scale),height:round1(box.h*vp.scale)};
  }

  /* ----------------------------------------------------------- texte affiché */

  /* Marques et isolats bidirectionnels : ils peuvent retourner l'ordre
     d'affichage d'un résumé (« usurpation » de contenu). */
  const BIDI=/[\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/g;
  /* Caractères invisibles : largeur nulle, joncteurs, BOM, césure molle. */
  const INVISIBLE=/[\u00AD\u180E\u200B-\u200D\u2060-\u2064\uFEFF]/g;
  const SEPARATORS=/[\u2028\u2029]/g;
  const CONTROLS_LINE=/[\u0000-\u001F\u007F-\u009F]/g;
  const CONTROLS_MULTI=/[\u0000-\u0008\u000B-\u001F\u007F-\u009F]/g;

  function clip(text,max){
    const chars=Array.from(text);
    return chars.length>max?chars.slice(0,Math.max(0,max-1)).join('')+'…':text;
  }

  /* Une ligne affichable : contrôles et séparateurs → espace, marques bidi et
     invisibles retirées, espaces resserrés, bornée à `max` caractères. */
  function cleanLine(value,max=160){
    if(typeof value!=='string')return '';
    const text=value.replace(SEPARATORS,' ').replace(CONTROLS_LINE,' ').replace(BIDI,'').replace(INVISIBLE,'')
      .replace(/\s+/g,' ').trim();
    return clip(text,max);
  }

  /* Un texte sur plusieurs lignes (résumé) : `\n` gardé, tabulation → espace,
     séparateurs Unicode → `\n`, autres contrôles, bidi et invisibles retirés. */
  function cleanText(value,max=2000){
    if(typeof value!=='string')return '';
    const text=value.replace(/\r\n?/g,'\n').replace(SEPARATORS,'\n').replace(/\t/g,' ').replace(CONTROLS_MULTI,'')
      .replace(BIDI,'').replace(INVISIBLE,'').replace(/\n{3,}/g,'\n\n').trim();
    return clip(text,max);
  }

  /* --------------------------------------------------------------- sémantique */

  /* Couleur = catégorie (Décision 7). Familles connues, puis teinte stable
     tirée du nom pour toute autre catégorie. */
  const CATEGORY_TONES=Object.freeze({
    agent:'agent',job:'job',
    note:'doc',notes:'doc',doc:'doc',docs:'doc',documentation:'doc',artifact:'doc',summary:'doc',report:'doc',document:'doc',
    research:'research',web:'research',search:'research',history:'research',source:'research',sources:'research',
    code:'code',diff:'code',files:'code',file:'code',git:'code',test:'code',tests:'code',api:'code',build:'code',
    email:'comms',mail:'comms',message:'comms',messages:'comms',trello:'comms',roadmap:'comms',calendar:'comms',meeting:'comms',
    error:'error',errors:'error',failed:'error',failure:'error',alert:'error',
    interrupted:'interrupted',cancelled:'interrupted',
    blocked:'blocked',attention:'blocked',question:'blocked',
  });
  const HASHED_TONES=Object.freeze(['x0','x1','x2','x3','x4','x5']);

  function toneOf(category){
    const key=String(category||'').toLowerCase();
    if(Object.prototype.hasOwnProperty.call(CATEGORY_TONES,key))return CATEGORY_TONES[key];
    let hash=2166136261;
    for(let i=0;i<key.length;i++){hash^=key.charCodeAt(i);hash=Math.imul(hash,16777619)>>>0}
    return HASHED_TONES[hash%HASHED_TONES.length];
  }

  /* Même règle que `is_live_signal` (jarvis/domain/scene.py) : un signal est
     vivant exactement tant que son lien `explains` (identifiant = celui du
     signal) existe. Sa catégorie ne dit rien de sa vie. */
  function isLiveSignal(state,objectId){
    const item=state.objects.get(objectId);
    if(!item||item.kind!=='attention')return false;
    const rel=state.relations.get(objectId);
    return !!rel&&rel.kind==='explains'&&rel.relation_id===rel.from_id;
  }

  /* Interruptions dues au cycle de vie de l'hôte, pas au travail : l'arrêt du
     CLI du cerveau pose un signal par sous-agent en cours. Le projecteur de
     Core (Slice 04) écrit un signal runtime dont la catégorie et
     l'`exec_state` sont le statut du travail et dont `payload.title` est la
     classe d'erreur (seul champ où elle voyage). */
  const LOW_URGENCY_ERRORS=new Set(['process_stopped']);

  /* Classe d'erreur portée par un signal du runtime, ou ''. */
  function signalErrorClass(item){
    if(item.kind!=='attention'||item.origin!=='runtime')return '';
    return String(item.payload&&item.payload.title||'');
  }

  /* Urgence d'un signal : `none` (retiré), `low`, `medium`, `high`. Basse :
     signal du runtime de catégorie `interrupted` et de classe
     `process_stopped`. */
  function signalUrgency(state,item){
    if(!isLiveSignal(state,item.object_id))return 'none';
    if(item.category==='interrupted'&&LOW_URGENCY_ERRORS.has(signalErrorClass(item)))return 'low';
    if(item.exec_state==='failed'||toneOf(item.category)==='error')return 'high';
    return 'medium';
  }

  const EXEC_LABELS=Object.freeze({unknown:'',pending:'en attente',running:'en cours',blocked:'bloqué',
    completed:'terminé',failed:'échec',cancelled:'annulé',interrupted:'interrompu'});
  const KIND_LABELS=Object.freeze({agent:'sous-agent',job:'tâche',artifact:'résultat',attention:'signal',window:'fenêtre',group:'groupe'});

  /* Titre affiché d'un signal du runtime : sa classe d'erreur dans les mots de
     la page (`errorLabels` = `ERROR_CLASSES` du Control Center), un statut
     brut dans sa forme française, sinon le titre tel quel. */
  function displayTitle(item,title,errorLabels){
    const code=signalErrorClass(item);
    if(!code)return title;
    if(errorLabels&&Object.prototype.hasOwnProperty.call(errorLabels,code))return cleanLine(String(errorLabels[code]),160);
    if(EXEC_LABELS[code])return EXEC_LABELS[code];
    return title;
  }

  /* Seuils de lisibilité (px) : sous eux, une fenêtre se dessine en capsule
     et une capsule en point, dans la page seulement (jamais validé, la
     représentation de la scène ne change pas). */
  const READABLE=Object.freeze({windowWidth:180,windowHeight:96,capsuleWidth:72});
  /* Capsule dessinée au plus à cette taille (unités, reprise QA Slice 08) :
     une boîte plus haute (fenêtre passée en capsule par le cerveau, objet
     épinglé qui garde sa boîte de fenêtre) est dessinée à la hauteur naturelle
     d'une capsule et au plus à cette largeur, centrée dans la boîte stockée.
     Rendu seulement : la géométrie de la scène ne change pas. Un point est
     déjà dessiné à sa taille, au centre de sa boîte. */
  const CAPSULE_MAX=Object.freeze({w:160,h:10});

  /* Boîte dessinée d'une représentation dans sa boîte stockée (unités). */
  function drawnBox(representation,box){
    if(representation!=='capsule'||(box.w<=CAPSULE_MAX.w&&box.h<=CAPSULE_MAX.h))return box;
    const w=Math.min(box.w,CAPSULE_MAX.w),h=box.h>CAPSULE_MAX.h?DEFAULT_SIZE.capsule.h:box.h;
    return {x:box.x+(box.w-w)/2,y:box.y+(box.h-h)/2,w,h};
  }
  /* Anneaux animés au plus (coût de style) : signaux vivants urgents d'abord,
     puis étoiles en cours, dans l'ordre de Core ; les autres restent fixes.
     La page ne propose que les nœuds dont l'état vient de changer
     (`options.animatable`) : au repos, aucune animation ne tourne. */
  const MAX_ANIMATED=24;

  /* ----------------------------------------------------------- AutoResolver */

  function sizeFor(item){
    if(item.representation==='window')return DEFAULT_SIZE.window;
    if(item.representation==='capsule')return DEFAULT_SIZE.capsule;
    return item.kind==='attention'?DEFAULT_SIZE.signal:DEFAULT_SIZE.point;
  }

  function workKey(ref){return ref&&typeof ref.source==='string'?`${ref.source}\n${ref.external_id}`:null}

  /* Ancre de chaque objet (`identifiant → {to, kind}`) : le signal près de son
     étoile (lien vivant, sinon même travail Core), l'enfant près de son parent
     (`parent_of`), un résultat près de ce qu'il explique. Première relation
     dans l'ordre de Core. */
  function anchorsOf(state){
    const anchors=new Map();
    const set=(from,to,kind)=>{if(from!==to&&!anchors.has(from))anchors.set(from,{to,kind})};
    const relations=[...state.relations.values()];
    for(const rel of relations)if(rel.kind==='explains'&&rel.relation_id===rel.from_id)set(rel.from_id,rel.to_id,'signal');
    const stars=new Map();
    for(const item of state.objects.values()){
      const key=(item.kind==='agent'||item.kind==='job')?workKey(item.work_ref):null;
      if(key&&!stars.has(key))stars.set(key,item.object_id);
    }
    for(const item of state.objects.values()){
      if(item.kind!=='attention')continue;
      const star=stars.get(workKey(item.work_ref));
      if(star!==undefined)set(item.object_id,star,'signal');
    }
    for(const rel of relations)if(rel.kind==='parent_of')set(rel.to_id,rel.from_id,'child');
    for(const rel of relations)if(rel.kind==='explains')set(rel.from_id,rel.to_id,'explains');
    return anchors;
  }

  /* Profondeur dans la chaîne d'ancres, cycles tolérés (`parent_of` n'est pas
     validé : une boucle s'arrête au premier identifiant déjà vu). */
  function depthOf(anchors,objectId){
    let depth=0,current=objectId;
    const seen=new Set([objectId]);
    while(depth<64){
      const next=anchors.get(current);
      if(next===undefined||seen.has(next.to))break;
      seen.add(next.to);depth++;current=next.to;
    }
    return depth;
  }

  const CELL=16;

  /* Grille spatiale : les requêtes de chevauchement ne lisent que les cellules
     touchées. */
  function createGrid(){
    const cells=new Map();let stamp=0;
    const keys=(b,visit)=>{
      const cx0=Math.floor(b.x/CELL),cx1=Math.floor((b.x+b.w)/CELL),cy0=Math.floor(b.y/CELL),cy1=Math.floor((b.y+b.h)/CELL);
      if((cx1-cx0+1)*(cy1-cy0+1)>4096)return visit('*');
      for(let cx=cx0;cx<=cx1;cx++)for(let cy=cy0;cy<=cy1;cy++)visit(`${cx},${cy}`);
    };
    return {
      add(box,layer){
        const entry={box,layer,mark:0};
        keys(box,key=>{let list=cells.get(key);if(!list){list=[];cells.set(key,list)}list.push(entry)});
      },
      /* Rend [aire même couche, aire autres couches, comparaisons]. */
      overlap(box,layer){
        stamp++;let same=0,other=0,work=0;
        const visit=key=>{
          const list=cells.get(key);if(!list)return;
          for(const entry of list){
            if(entry.mark===stamp)continue;
            entry.mark=stamp;work++;
            const area=overlapArea(box,entry.box);
            if(area>0){if(entry.layer===layer)same+=area;else other+=area}
          }
        };
        keys(box,visit);visit('*');
        return [same,other,work];
      },
    };
  }

  function overlapArea(a,b){
    const w=Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x),h=Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y);
    return w>0&&h>0?w*h:0;
  }

  const inSafeArea=b=>b.x>=SAFE_AREA.x0&&b.y>=SAFE_AREA.y0&&b.x+b.w<=SAFE_AREA.x1&&b.y+b.h<=SAFE_AREA.y1;
  const faceBox={x:FACE_ZONE.x0,y:FACE_ZONE.y0,w:FACE_ZONE.x1-FACE_ZONE.x0,h:FACE_ZONE.y1-FACE_ZONE.y0};

  /* Angles préférés (degrés) autour d'une ancre. */
  const SIGNAL_ANGLES=[-45,-90,0,-135,45,180,135,90];
  const CHILD_ANGLES=[90,60,120,30,150,0,180,-30,-150,-60,-120,-90];
  const EXPLAIN_ANGLES=[0,-30,30,180,-60,60,150,-150,90,-90];

  function ringCandidates(anchorBox,size,kind){
    const acx=anchorBox.x+anchorBox.w/2,acy=anchorBox.y+anchorBox.h/2;
    const reach=Math.max(anchorBox.w,anchorBox.h)/2+Math.max(size.w,size.h)/2;
    const angles=kind==='signal'?SIGNAL_ANGLES:kind==='child'?CHILD_ANGLES:EXPLAIN_ANGLES;
    /* Un signal se pose contre son étoile, comme une marque (autre couche). */
    const gap=kind==='signal'?-1:6;
    const out=[];
    for(let ring=0;ring<5;ring++){
      const radius=reach+gap+ring*(Math.max(size.w,size.h)+4);
      for(const deg of angles){
        const a=deg*Math.PI/180;
        out.push({x:Math.round(acx+Math.cos(a)*radius-size.w/2),y:Math.round(acy+Math.sin(a)*radius-size.h/2),w:size.w,h:size.h});
      }
    }
    return out;
  }

  /* Points d'origine des objets sans ancre : les étoiles à gauche du visage,
     les résultats et fenêtres à droite, les groupes au centre. */
  function homeOf(item){
    if(item.kind==='agent'||item.kind==='job'||item.kind==='attention')return {x:-62,y:0};
    if(item.kind==='group')return {x:0,y:0};
    return {x:72,y:0};
  }

  /* Spirale carrée sur un réseau, anneau par anneau du plus proche au plus
     loin de l'origine, dans la zone sûre, au plus `MAX_ROOT_CANDIDATES` boîtes
     par réseau. Les étoiles essaient d'abord un réseau espacé (constellation
     lisible, place pour enfants et signaux), puis un réseau serré quand la
     scène se remplit ; les formes plus grandes n'ont que le réseau serré. */
  function rootCandidates(home,size){
    const gaps=size.w<=8?[10,2]:[2];
    const out=[];
    for(const gap of gaps){
      const stepX=size.w+gap,stepY=size.h+gap;let count=0;
      const maxRing=Math.ceil(Math.max((SAFE_AREA.x1-SAFE_AREA.x0)/stepX,(SAFE_AREA.y1-SAFE_AREA.y0)/stepY));
      for(let ring=0;ring<=maxRing&&count<MAX_ROOT_CANDIDATES;ring++){
        const cells=[];
        const push=(i,j)=>{
          const box={x:Math.round(home.x+i*stepX-size.w/2),y:Math.round(home.y+j*stepY-size.h/2),w:size.w,h:size.h};
          if(inSafeArea(box))cells.push({box,d:Math.hypot(i*stepX,j*stepY),a:Math.atan2(j,i)});
        };
        if(ring===0)push(0,0);
        for(let k=-ring;k<ring;k++){push(k,-ring);push(ring,k);push(-k,ring);push(-ring,-k)}
        cells.sort((p,q)=>p.d-q.d||p.a-q.a);
        for(const cell of cells){if(count>=MAX_ROOT_CANDIDATES)break;out.push(cell.box);count++}
      }
    }
    return out;
  }

  /* Placer tout ce qui n'a pas de géométrie. Rend `{placements, resolved,
     work}` : `placements` (identifiant → boîte en unités) couvre tous les
     objets visibles, `resolved` liste dans l'ordre les objets posés par cette
     passe (à valider auprès de Core), `work` le nombre de comparaisons. Un
     objet caché n'est ni placé ni obstacle : il le sera quand il reparaîtra.

     Travail borné : les candidats d'une même origine et d'une même taille sont
     calculés une fois, et un curseur par (origine, taille, couche) saute ceux
     déjà reconnus non libres (l'occupation ne fait que croître pendant la
     passe), sauf quand plus rien n'est libre : tout est relu au moindre coût ;
     au-delà de `WORK_BUDGET` comparaisons, chaque objet restant prend son
     premier candidat admissible. */
  function resolveLayout(state){
    const placements=new Map(),resolved=[];
    const grid=createGrid();
    const order=new Map();let index=0;
    for(const item of state.objects.values()){
      order.set(item.object_id,index++);
      if(item.visibility!=='visible'||!item.geometry)continue;
      const g=item.geometry,box={x:g.x,y:g.y,w:g.w,h:g.h};
      placements.set(item.object_id,box);grid.add(box,item.layer);
    }
    const anchors=anchorsOf(state);
    const pending=[...state.objects.values()].filter(item=>item.visibility==='visible'&&!item.geometry);
    const depth=new Map(pending.map(item=>[item.object_id,depthOf(anchors,item.object_id)]));
    pending.sort((a,b)=>depth.get(a.object_id)-depth.get(b.object_id)||order.get(a.object_id)-order.get(b.object_id));
    const roots=new Map(),cursors=new Map();
    let work=0;
    /* Premier candidat libre (aucun chevauchement, hors visage), sinon le moins
       coûteux ; `sameLayerOnly` : refuser tout chevauchement de même couche ;
       `firstFit` : prendre le premier sans chevauchement de même couche (un
       signal peut recouvrir une étoile voisine, pas un autre signal).
       Rend {box, index, free} ou null. */
    const pick=(candidates,start,layer,sameLayerOnly,firstFit)=>{
      let best=null;
      for(let i=start;i<candidates.length;i++){
        const box=candidates[i];
        if(!inSafeArea(box))continue;
        if(work>WORK_BUDGET)return {box,index:i,free:false,cost:Infinity};
        const [same,other,count]=grid.overlap({x:box.x-1,y:box.y-1,w:box.w+2,h:box.h+2},layer);
        work+=count+1;
        const face=overlapArea(box,faceBox);
        if(same===0&&other===0&&face===0)return {box,index:i,free:true};
        if(firstFit&&same===0)return {box,index:i,free:false,cost:0};
        const cost=same*1000+other*4+face*8;
        if((!sameLayerOnly||same===0)&&(!best||cost<best.cost))best={box,index:i,free:false,cost};
      }
      return best;
    };
    for(const item of pending){
      const size=sizeFor(item);
      const anchor=anchors.get(item.object_id);
      const anchorBox=anchor===undefined?undefined:placements.get(anchor.to);
      let chosen=null;
      if(anchorBox){
        const near=pick(ringCandidates(anchorBox,size,anchor.kind),0,item.layer,true,anchor.kind==='signal');
        if(near)chosen=near.box;
      }
      if(!chosen){
        const home=homeOf(item),key=`${home.x},${home.y},${size.w},${size.h}`,cursorKey=`${key},${item.layer}`;
        if(!roots.has(key))roots.set(key,rootCandidates(home,size));
        const candidates=roots.get(key),start=cursors.get(cursorKey)||0;
        let far=pick(candidates,start,item.layer,false,false);
        if(far&&far.free)cursors.set(cursorKey,far.index+1);
        /* Plus de place libre après le curseur : les candidats sautés (visage,
           autre couche) redeviennent des choix, au moindre coût. */
        else if(start>0){const again=pick(candidates,0,item.layer,false,false);if(again&&(!far||again.cost<far.cost))far=again}
        chosen=far?far.box:{x:Math.round(home.x-size.w/2),y:Math.round(home.y-size.h/2),w:size.w,h:size.h};
      }
      placements.set(item.object_id,chosen);grid.add(chosen,item.layer);resolved.push(item.object_id);
    }
    return {placements,resolved,work};
  }

  /* ---------------------------------------------------------- modèle de vue */

  const MAX_Z_LAYER=1000,ORDER_SPAN=1000000;

  /* Ordre d'empilement dans le conteneur de scène uniquement : couche, puis
     ordre, puis ordre de Core (ordre du DOM). Toujours > 0, < 2^31. */
  function stackOf(layer,order){
    const l=Math.max(0,Math.min(MAX_Z_LAYER,Number(layer)||0)),o=Math.max(-ORDER_SPAN,Math.min(ORDER_SPAN,Number(order)||0));
    return l*(2*ORDER_SPAN+1)+(o+ORDER_SPAN)+1;
  }

  /* Ce que la page dessine pour `state` dans la fenêtre `vp`. Rend
     `{nodes, edges, capacity, offscreen, hidden}` ; `nodes` dans l'ordre de
     Core, sans objet caché. */
  function viewModel(state,layout,vp,options){
    const limit=options&&Number.isInteger(options.objectLimit)?options.objectLimit:OBJECT_LIMIT;
    const errorLabels=options&&options.errorLabels||null;
    const animatable=options&&typeof options.animatable==='function'?options.animatable:()=>true;
    const nodes=[],centers=new Map();let offscreen=0,hidden=0;
    for(const item of state.objects.values()){
      if(item.visibility!=='visible'){hidden++;continue}
      const stored=layout.placements.get(item.object_id);
      if(!stored)continue;
      const representation=['point','capsule','window'].includes(item.representation)?item.representation:'point';
      const screen=toScreen(vp,drawnBox(representation,stored));
      const payload=item.payload||{};
      const title=displayTitle(item,cleanLine(payload.title,160),errorLabels);
      const exec=EXEC_LABELS[item.exec_state]!==undefined?item.exec_state:'unknown';
      const signal=item.kind==='attention';
      const urgency=signal?signalUrgency(state,item):'none';
      const shape=compactShape(representation,screen);
      const node={
        id:item.object_id,kind:item.kind,representation,shape,compact:shape!==representation,
        category:cleanLine(item.category,32),tone:toneOf(item.category),
        exec,execLabel:EXEC_LABELS[exec],signal,live:signal&&urgency!=='none',urgency,animate:false,
        pinned:!!(item.constraints&&item.constraints.pinned_by_user),
        placedBy:item.geometry?String(item.constraints&&item.constraints.placed_by||''):'resolver',
        committed:!!item.geometry,
        stack:stackOf(item.layer,item.order),
        box:screen,cx:round1(screen.left+screen.width/2),cy:round1(screen.top+screen.height/2),
        title:title||KIND_LABELS[item.kind]||item.kind,
        summary:shape==='window'?cleanText(payload.summary,2000):'',
        items:shape==='window'&&Array.isArray(payload.items)
          ?payload.items.slice(0,32).map(entry=>({label:cleanLine(entry&&entry.label,160),ref:cleanLine(entry&&entry.ref,256),url:cleanLine(entry&&entry.url,256)}))
          :[],
      };
      node.label=[node.title,KIND_LABELS[item.kind]||item.kind,node.execLabel,signal&&!node.live?'retiré':'',node.pinned?'épinglé':''].filter(Boolean).join(' · ');
      const outside=screen.left+screen.width<0||screen.top+screen.height<0||screen.left>vp.width||screen.top>vp.height;
      if(outside)offscreen++;
      nodes.push(node);centers.set(node.id,node);
    }
    /* Un signal du runtime s'empile avec son étoile (juste au-dessus d'elle) :
       une fenêtre qui recouvre l'étoile recouvre aussi son signal. Les objets
       `attention` du cerveau ou de l'utilisateur gardent leur couche
       (Décision 8). */
    const anchors=anchorsOf(state);
    for(const node of nodes){
      if(!node.signal||state.objects.get(node.id).origin!=='runtime')continue;
      const anchor=anchors.get(node.id);
      const star=anchor&&anchor.kind==='signal'?centers.get(anchor.to):null;
      if(star)node.stack=star.stack+1;
    }
    /* Signaux vivants urgents recouverts par une fenêtre dessinée au-dessus
       d'eux : comptés pour l'indicateur (test de rectangles, à chaque rendu). */
    const coveredSignals={high:0,medium:0};
    const windows=nodes.filter(n=>n.shape==='window');
    for(const node of nodes){
      if(node.urgency!=='high'&&node.urgency!=='medium')continue;
      if(state.objects.get(node.id).origin!=='runtime')continue;
      const covered=windows.some(w=>w.stack>node.stack&&node.cx>=w.box.left&&node.cx<=w.box.left+w.box.width&&node.cy>=w.box.top&&node.cy<=w.box.top+w.box.height);
      if(covered)coveredSignals[node.urgency]++;
    }
    /* Borne des animations : urgence haute, moyenne, puis exécution en cours. */
    let budget=MAX_ANIMATED;
    for(const pass of [n=>n.urgency==='high',n=>n.urgency==='medium',n=>!n.signal&&n.exec==='running']){
      for(const node of nodes){if(budget<=0)break;if(!node.animate&&pass(node)&&animatable(node)){node.animate=true;budget--}}
    }
    const edges=[];
    for(const rel of state.relations.values()){
      const a=centers.get(rel.from_id),b=centers.get(rel.to_id);
      if(!a||!b)continue;
      edges.push({id:rel.relation_id,kind:rel.kind,layer:Number(rel.layer)||0,
        signal:rel.kind==='explains'&&rel.relation_id===rel.from_id,tone:a.tone,
        x1:a.cx,y1:a.cy,x2:b.cx,y2:b.cy});
    }
    edges.sort((p,q)=>p.layer-q.layer);
    const objects=state.objects.size;
    return {nodes,edges,hidden,offscreen,coveredSignals,capacity:{objects,limit,saturated:objects>=limit}};
  }

  /* Forme dessinée pour une boîte à l'écran : la représentation, ou plus
     compacte quand son texte n'y serait pas lisible. */
  function compactShape(representation,screen){
    let shape=representation;
    if(shape==='window'&&(screen.width<READABLE.windowWidth||screen.height<READABLE.windowHeight))shape='capsule';
    if(shape==='capsule'&&screen.width<READABLE.capsuleWidth)shape='point';
    return shape;
  }

  /* ------------------------------------------------ navigation au clavier */

  /* Ordre de lecture spatial (bandes de 24 px de haut en bas, puis de gauche
     à droite) : premier arrêt de tabulation, Début et Fin. */
  function spatialOrder(nodes){
    return [...nodes].sort((a,b)=>Math.floor(a.cy/24)-Math.floor(b.cy/24)||a.cx-b.cx||(a.id<b.id?-1:a.id>b.id?1:0));
  }

  /* Nœud suivant pour une touche : une flèche mène au plus proche dans sa
     direction (écart transversal pénalisé), Début / Fin au premier / dernier
     de l'ordre spatial. Rend un identifiant (`currentId` s'il n'y a rien). */
  function nextFocus(nodes,currentId,key){
    if(!nodes.length)return null;
    const ordered=spatialOrder(nodes);
    if(key==='Home')return ordered[0].id;
    if(key==='End')return ordered[ordered.length-1].id;
    const current=nodes.find(n=>n.id===currentId);
    if(!current)return ordered[0].id;
    const dirs={ArrowRight:[1,0],ArrowLeft:[-1,0],ArrowDown:[0,1],ArrowUp:[0,-1]};
    const dir=dirs[key];
    if(!dir)return currentId;
    let best=null,bestScore=Infinity;
    for(const node of nodes){
      if(node.id===current.id)continue;
      const dx=node.cx-current.cx,dy=node.cy-current.cy;
      const along=dx*dir[0]+dy*dir[1],across=Math.abs(dx*dir[1])+Math.abs(dy*dir[0]);
      if(along<=0)continue;
      const score=along+2*across;
      if(score<bestScore||(score===bestScore&&node.id<best.id)){best=node;bestScore=score}
    }
    return best?best.id:currentId;
  }

  /* ------------------------------------------- validation des placements */

  const COMMIT_MAX_ATTEMPTS=3;

  const commitKey=(state,objectId)=>`${state.scene_id}\n${objectId}`;

  /* Commande `set_geometry` (`placed_by = resolver`) pour une boîte posée. */
  function commitCommand(objectId,box){
    return {schema_version:1,op:'set_geometry',object_id:objectId,
      geometry:{x:box.x,y:box.y,w:box.w,h:box.h},placed_by:'resolver'};
  }

  /* Prochains objets à valider, dans l'ordre de la passe : toujours sans
     géométrie dans l'état tenu, visibles, jamais validés ni en cours, et dont
     le délai de nouvel essai est passé. */
  function commitCandidates(state,layout,ledger,now){
    const out=[];
    for(const objectId of layout.resolved){
      const item=state.objects.get(objectId);
      if(!item||item.geometry||item.visibility!=='visible')continue;
      const entry=ledger.get(commitKey(state,objectId));
      if(entry&&(entry.status!=='retry'||entry.retryAt>now))continue;
      const box=layout.placements.get(objectId);
      if(box)out.push({objectId,key:commitKey(state,objectId),command:commitCommand(objectId,box)});
    }
    return out;
  }

  /* Plus proche délai de nouvel essai encore à venir (> `now`), ou null. Un
     délai passé dont l'objet n'est plus candidat n'est jamais replanifié. */
  function nextRetryAt(ledger,now){
    let next=null;
    for(const entry of ledger.values())
      if(entry.status==='retry'&&entry.retryAt>now&&(next===null||entry.retryAt<next))next=entry.retryAt;
    return next;
  }

  /* Lire la réponse de `POST /api/scene/commands`. `done` : ne plus jamais
     renvoyer (appliqué, doublon, refus du domaine, erreur de forme) ; `retry` :
     rien n'a été appliqué ou l'issue est inconnue, renvoyer la même boîte est
     sûr (même géométrie → `duplicate`, objet placé entre-temps →
     `explicit_placement`). */
  function classifyCommit(status,body){
    if(status===200&&body&&typeof body.outcome==='string')
      return {settle:'done',outcome:body.outcome,reason:body.reason||''};
    const code=body&&body.error&&typeof body.error.code==='string'?body.error.code:`http_${status}`;
    if(status===503||status===504||status===0)return {settle:'retry',outcome:'not_confirmed',reason:code};
    return {settle:'done',outcome:'failed',reason:code};
  }

  /* Noter l'issue d'une validation. Rend l'entrée. Un nouvel essai attend
     2 s, 8 s puis abandonne après `COMMIT_MAX_ATTEMPTS` envois. */
  function settleCommit(ledger,key,verdict,now){
    const previous=ledger.get(key)||{attempts:0};
    const attempts=previous.attempts+1;
    const retry=verdict.settle==='retry'&&attempts<COMMIT_MAX_ATTEMPTS;
    const entry={status:retry?'retry':'done',attempts,outcome:retry?verdict.outcome:(verdict.settle==='retry'?'gave_up':verdict.outcome),
      reason:verdict.reason||'',retryAt:retry?now+2000*Math.pow(4,attempts-1):null};
    ledger.set(key,entry);
    if(ledger.size>2048){for(const k of ledger.keys()){if(ledger.size<=2048)break;if(k!==key)ledger.delete(k)}}
    return entry;
  }

  const api=Object.freeze({FRAME,SAFE_AREA,FACE_ZONE,OBJECT_LIMIT,DEFAULT_SIZE,WORK_BUDGET,COMMIT_MAX_ATTEMPTS,READABLE,MAX_ANIMATED,CAPSULE_MAX,drawnBox,
    viewport,toScreen,cleanLine,cleanText,toneOf,isLiveSignal,signalUrgency,signalErrorClass,anchorsOf,depthOf,resolveLayout,
    stackOf,viewModel,compactShape,spatialOrder,nextFocus,commitKey,commitCommand,commitCandidates,nextRetryAt,classifyCommit,settleCommit});
  root.JarvisSceneLayout=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
