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
  /* Zone où le résolveur pose : le cadre moins les marges des commandes de la
     page (barre du haut, dock à droite, indication vocale en bas). */
  const SAFE_AREA=Object.freeze({x0:-154,x1:144,y0:-80,y1:80});
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

  /* Titres posés par Core pour une interruption due à l'arrêt du CLI du
     cerveau : un signal par sous-agent à chaque arrêt, peu urgent. */
  const LOW_URGENCY_TITLES=new Set(['process_stopped']);

  /* Urgence d'un signal : `none` (retiré), `low`, `medium`, `high`. */
  function signalUrgency(state,item){
    if(!isLiveSignal(state,item.object_id))return 'none';
    const title=String(item.payload&&item.payload.title||'');
    if(LOW_URGENCY_TITLES.has(title))return 'low';
    if(item.exec_state==='failed'||toneOf(item.category)==='error')return 'high';
    return 'medium';
  }

  const EXEC_LABELS=Object.freeze({unknown:'',pending:'en attente',running:'en cours',blocked:'bloqué',
    completed:'terminé',failed:'échec',cancelled:'annulé',interrupted:'interrompu'});
  const KIND_LABELS=Object.freeze({agent:'sous-agent',job:'tâche',artifact:'résultat',attention:'signal',window:'fenêtre',group:'groupe'});

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
    const nodes=[],centers=new Map();let offscreen=0,hidden=0;
    for(const item of state.objects.values()){
      if(item.visibility!=='visible'){hidden++;continue}
      const box=layout.placements.get(item.object_id);
      if(!box)continue;
      const screen=toScreen(vp,box);
      const representation=['point','capsule','window'].includes(item.representation)?item.representation:'point';
      const payload=item.payload||{};
      const title=cleanLine(payload.title,160);
      const exec=EXEC_LABELS[item.exec_state]!==undefined?item.exec_state:'unknown';
      const signal=item.kind==='attention';
      const urgency=signal?signalUrgency(state,item):'none';
      const node={
        id:item.object_id,kind:item.kind,representation,
        category:cleanLine(item.category,32),tone:toneOf(item.category),
        exec,execLabel:EXEC_LABELS[exec],signal,live:signal&&urgency!=='none',urgency,
        pinned:!!(item.constraints&&item.constraints.pinned_by_user),
        placedBy:item.geometry?String(item.constraints&&item.constraints.placed_by||''):'resolver',
        committed:!!item.geometry,
        stack:stackOf(item.layer,item.order),
        box:screen,cx:round1(screen.left+screen.width/2),cy:round1(screen.top+screen.height/2),
        title:title||KIND_LABELS[item.kind]||item.kind,
        summary:representation==='window'?cleanText(payload.summary,2000):'',
        items:representation==='window'&&Array.isArray(payload.items)
          ?payload.items.slice(0,32).map(entry=>({label:cleanLine(entry&&entry.label,160),ref:cleanLine(entry&&entry.ref,256),url:cleanLine(entry&&entry.url,256)}))
          :[],
      };
      node.label=[node.title,KIND_LABELS[item.kind]||item.kind,node.execLabel,signal&&!node.live?'retiré':'',node.pinned?'épinglé':''].filter(Boolean).join(' · ');
      const outside=screen.left+screen.width<0||screen.top+screen.height<0||screen.left>vp.width||screen.top>vp.height;
      if(outside)offscreen++;
      nodes.push(node);centers.set(node.id,node);
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
    return {nodes,edges,hidden,offscreen,capacity:{objects,limit,saturated:objects>=limit}};
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

  const api=Object.freeze({FRAME,SAFE_AREA,FACE_ZONE,OBJECT_LIMIT,DEFAULT_SIZE,WORK_BUDGET,COMMIT_MAX_ATTEMPTS,
    viewport,toScreen,cleanLine,cleanText,toneOf,isLiveSignal,signalUrgency,anchorsOf,depthOf,resolveLayout,
    stackOf,viewModel,commitKey,commitCommand,commitCandidates,nextRetryAt,classifyCommit,settleCommit});
  root.JarvisSceneLayout=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
