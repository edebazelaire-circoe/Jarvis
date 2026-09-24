/* Scène constellation : logique pure des interactions de l'utilisateur (handoff
   jarvis-constellation-scene-runtime, Slice 08).

   - Géométrie : glisser, redimensionner, flèches du clavier, changement de
     représentation ; toujours bornée à la zone de composition sûre
     (`SAFE_AREA`, x -152..138, y -72..68 : aucune commande de la page ne la
     recouvre), en unités entières.
   - Menu : entrées selon la nature, l'origine et l'état de l'objet. « Arrêter »
     seulement pour une étoile `job` (`work_ref.source = job`) ; jamais pour un
     sous-agent du brain, qui n'a pas d'arrêt individuel (entrée désactivée
     qui le dit).
   - Archivage groupé : même règle que `bulk_archivable`
     (`jarvis/domain/scene.py`, test de parité) ; Core la revalide.
   - Affichage optimiste : une modification envoyée se dessine tout de suite,
     puis disparaît quand l'état tenu atteint la révision rendue par Core, ou
     s'annule sur refus, échec ou délai.
   - Commandes `POST /api/scene/commands` (acteur `user` posé par le Control
     Center) et lecture de leurs réponses.

   Aucune dépendance au DOM, au réseau ni à l'horloge : les tests l'exécutent
   avec node (`tests/unit/test_scene_interaction_logic.py`). Inséré tel quel
   dans la page par `ControlCenter.index` ; n'expose que
   `window.JarvisSceneInteract`. */
(function(root){
  'use strict';

  const FRAME=Object.freeze({halfWidth:160,halfHeight:90});
  /* Zone de composition sûre (Slice 05) : même valeur que `SCENE_SAFE_AREA`
     du domaine et `SAFE_AREA` du rendu (tests de parité). Décision PM (reprise
     QA) : toute géométrie de l'utilisateur y reste. */
  const SAFE_AREA=Object.freeze({x0:-152,x1:138,y0:-72,y1:68});
  /* Pas du clavier, en unités de scène : Maj+flèche (2), Ctrl+Maj+flèche (10),
     Ctrl+flèche redimensionne de 2. */
  const KEY_STEP=2,KEY_STEP_LARGE=10;
  /* Tailles minimales et par défaut, en unités (défauts = `DEFAULT_SIZE` du
     rendu : une forme changée prend la taille que le résolveur lui donnerait). */
  const MIN_SIZE=Object.freeze({capsule:Object.freeze({w:16,h:5}),window:Object.freeze({w:40,h:24})});
  /* Taille maximale d'une capsule (même valeur que `CAPSULE_MAX` du rendu) :
     au-delà, le rendu la dessine à sa hauteur naturelle, centrée. */
  const MAX_SIZE=Object.freeze({capsule:Object.freeze({w:160,h:10})});
  const DEFAULT_SIZE=Object.freeze({point:Object.freeze({w:6,h:6}),signal:Object.freeze({w:4,h:4}),
    capsule:Object.freeze({w:40,h:7}),window:Object.freeze({w:64,h:40})});
  /* Seuil (px) au-delà duquel un appui devient un glissement : 4 px à la
     souris, 10 px pour un pointeur grossier (tactile, stylet) ou la main de
     Barehands, pour qu'un appui long qui tremble n'épingle rien ; appui long
     (ms) qui ouvre le menu. */
  const DRAG_THRESHOLD_PX=4,COARSE_DRAG_THRESHOLD_PX=10,LONG_PRESS_MS=550;
  /* Un affichage optimiste jamais confirmé par l'état tenu s'efface au plus
     tard après ce délai (lecture en panne, patch perdu). */
  const PENDING_MAX_MS=30000;
  /* Archivage groupé : au plus 512 identifiants par commande (borne du
     domaine) et un corps sous 64 Kio (borne du transport). */
  const MAX_ARCHIVE_IDS=512,MAX_COMMAND_BYTES=48000;
  const EXECUTION_KINDS=new Set(['agent','job']);
  const TERMINAL=Object.freeze(['completed','failed','cancelled','interrupted']);
  const ACTIVE_WORK=new Set(['running','pending','blocked']);

  const clamp=(v,lo,hi)=>Math.min(hi,Math.max(lo,v));

  /* ----------------------------------------------------------- géométrie */

  /* **Une seule quantification, au dixième d'unité** (21/09/2026).

     Les boîtes étaient arrondies à l'unité entière ici, et au dixième dans
     `placeOf` (page) au moment du lâcher. Deux grilles pour une même géométrie :
     prendre un objet enregistré en `x.4` le décalait de 0,4 unité — soit ~2,5 px
     en 1080p — dès le premier mouvement, avant même d'avoir bougé la main ; et
     une unité valant ~6 px, le glissement se faisait par marches de six pixels.
     Le dixième d'unité fait ~0,6 px : le geste redevient continu, `scene_inspect`
     reste lisible, et un geste d'un pixel ne fabrique toujours pas de révision. */
  const QUANTUM=10,quantize=v=>Math.round(v*QUANTUM)/QUANTUM;

  /* Demi-axes de l'ellipse du tour, en unités de scène : **même valeur que
     `ORBIT_AXES` du rendu** (`control_center_scene_layout.js`), qui les calcule
     de la même façon — un test de parité refuse qu'elles divergent, comme pour
     `SAFE_AREA`. Ce module ne lit pas le rendu : il est inséré avant lui, et
     `JarvisSceneInteract` doit s'installer même si le rendu échoue. */
  const ORBIT_ASPECT_MAX=1.6;
  const ORBIT_AXES=(()=>{
    const ay=Math.min(-SAFE_AREA.y0,SAFE_AREA.y1);
    return Object.freeze({ax:Math.min(-SAFE_AREA.x0,SAFE_AREA.x1,ay*ORBIT_ASPECT_MAX),ay});
  })();
  /* Formes qui tournent : toutes sauf la fenêtre, qu'on lit et qui ne dérive
     donc jamais (même règle que `ORBIT_STILL_SHAPES` du rendu). */
  const orbitTurns=representation=>representation!=='window';
  const orbitReach=b=>Math.hypot((b.x+b.w/2)/ORBIT_AXES.ax,(b.y+b.h/2)/ORBIT_AXES.ay);
  const orbitInset=b=>Math.max(0,Math.min(1-b.w/(2*ORBIT_AXES.ax),1-b.h/(2*ORBIT_AXES.ay)));

  /* Boîte bornée à la zone sûre : taille ≥ minimum et ≤ maximum de la forme (et
     ≤ zone), coin haut gauche gardé pour que la boîte entière tienne dans la
     zone — puis, pour une forme qui tourne, **bornée à son tour**.

     Cette seconde borne est le cœur du contrat géométrique (21/09/2026). Le
     rendu resserrait le champ entier pour faire tenir le tour de l'objet le plus
     excentré : déplacer une étoile déplaçait donc toutes les autres, de plus de
     cent pixels, sans que personne les ait touchées. C'est l'inverse qui est
     juste — la place se borne, le champ ne bouge pas. Une étoile vit dans
     l'ellipse où son tour tient dans la zone sûre ; une fenêtre, qui ne tourne
     pas, garde toute la zone. Une capsule très large a une ellipse d'autant plus
     petite : un cadre presque aussi large que l'écran ne peut pas tourner loin
     du centre sans en sortir, et le lui laisser croire serait le mensonge
     qu'on vient d'enlever. */
  function clampBox(box,representation){
    return orbitClamp(boundPlace(boundSize(box,representation)),representation);
  }

  /* Taille bornée au minimum et au maximum de la forme (et à la zone). */
  function boundSize(box,representation){
    const min=MIN_SIZE[representation]||{w:1,h:1};
    const areaW=SAFE_AREA.x1-SAFE_AREA.x0,areaH=SAFE_AREA.y1-SAFE_AREA.y0;
    const max=MAX_SIZE[representation]||{w:areaW,h:areaH};
    return {x:box.x,y:box.y,
      w:quantize(clamp(Number(box.w)||min.w,min.w,Math.min(max.w,areaW))),
      h:quantize(clamp(Number(box.h)||min.h,min.h,Math.min(max.h,areaH)))};
  }

  /* Place bornée à la zone sûre, la taille passant telle quelle. */
  function boundPlace(box){
    const w=Number(box.w)||1,h=Number(box.h)||1;
    return {x:quantize(clamp(Number(box.x)||0,SAFE_AREA.x0,SAFE_AREA.x1-w)),
      y:quantize(clamp(Number(box.y)||0,SAFE_AREA.y0,SAFE_AREA.y1-h)),w:quantize(w),h:quantize(h)};
  }

  /* Borner **la place seule** : la taille passe telle quelle, quelle qu'elle
     soit. C'est le chemin du déplacement, et l'invariant « déplacer ne touche
     jamais à la taille » se tient ici plutôt que dans une promesse.

     Il ne se tenait pas : `clampBox` ramenait aussi la taille au maximum de la
     forme, si bien que **déplacer** une capsule plus haute que `MAX_SIZE`
     — une fenêtre passée en capsule par le cerveau, un objet épinglé qui a
     gardé sa boîte de fenêtre, cas que `CAPSULE_MAX` prévoit explicitement au
     rendu — la rabotait au passage, sans que personne ait tiré sur une
     poignée. */
  function placeClamp(box,representation){
    return orbitClamp(boundPlace(box),representation);
  }

  /* **Redimensionner par un coin : c'est la taille qui cède, jamais la place.**

     Borner un redimensionnement comme un déplacement (`orbitClamp`) aurait
     ramené le coin haut gauche vers le centre dès qu'une capsule élargie ne
     tenait plus sur son tour — l'objet aurait glissé sous la poignée, ce qui
     est exactement le genre de saut que ce contrat supprime. La croissance est
     donc freinée, le coin reste où il est : la plus grande taille entre la
     taille de départ et la taille demandée qui tienne encore sur son tour.

     Une boîte de départ qui ne tenait déjà pas (géométrie posée avant ce
     contrat, place du résolveur dans une scène pleine) n'est pas corrigée par
     un redimensionnement : ce n'est pas au coin bas droit de déplacer un
     objet. Le prochain déplacement la ramènera. */
  function orbitShrink(box,start,representation){
    if(!orbitTurns(representation)||orbitFits(box,representation))return box;
    /* Le seul point dont on sait qu'il tient : la taille de départ, au même
       coin. Pas le plus petit des deux — réduire une boîte ancrée en haut à
       gauche déplace son centre, et peut l'éloigner du centre du tour. */
    const from={x:box.x,y:box.y,w:quantize(start.w),h:quantize(start.h)};
    if(!orbitFits(from,representation))return box;
    const at=t=>({x:box.x,y:box.y,w:from.w+(box.w-from.w)*t,h:from.h+(box.h-from.h)*t});
    let lo=0,hi=1;
    for(let i=0;i<24;i++){const t=(lo+hi)/2;if(orbitFits(at(t),representation))lo=t;else hi=t}
    /* Sur la grille du dixième, **du côté de la taille de départ** : un
       dixième de trop dans l'autre sens repasserait la borne. */
    const toward=(v,target)=>v>target?Math.floor(v*QUANTUM+1e-9)/QUANTUM:Math.ceil(v*QUANTUM-1e-9)/QUANTUM;
    const found=at(lo);
    const out={x:box.x,y:box.y,w:toward(found.w,from.w),h:toward(found.h,from.h)};
    return orbitFits(out,representation)?out:from;
  }

  /* Ramener le centre sur son ellipse, le long du rayon : la direction voulue
     est gardée, seule la distance cède. La place retombe sur la grille du
     dixième **du côté du centre** : l'arrondi au plus proche pouvait la
     repasser juste au-dessus de la borne, et chaque reprise retombait alors
     sur la même boîte. Vers le centre, le rayon ne peut que baisser — une
     passe suffit, la seconde n'est qu'une garde. */
  function orbitClamp(box,representation){
    if(!orbitTurns(representation))return box;
    const inset=orbitInset(box);
    const inward=(v,c)=>c>0?Math.floor(v*QUANTUM+1e-9)/QUANTUM:Math.ceil(v*QUANTUM-1e-9)/QUANTUM;
    let out=box;
    for(let guard=0;guard<2;guard++){
      const reach=orbitReach(out);
      if(reach<=inset+1e-9||!(reach>0))return out;
      const k=inset/reach;
      const cx=(out.x+out.w/2)*k,cy=(out.y+out.h/2)*k;
      out={x:inward(cx-out.w/2,cx),y:inward(cy-out.h/2,cy),w:out.w,h:out.h};
    }
    return out;
  }

  /* La place tient-elle sur son tour ? Même règle que `orbitFits` du rendu. */
  function orbitFits(box,representation){
    return !orbitTurns(representation)||orbitReach(box)<=orbitInset(box)+1e-9;
  }

  /* Seuil de glissement pour un pointeur. */
  function dragThreshold(pointerType,barehands){
    return pointerType==='mouse'&&!barehands?DRAG_THRESHOLD_PX:COARSE_DRAG_THRESHOLD_PX;
  }

  /* Écart en pixels → écart en unités pour la fenêtre `vp` (`JarvisSceneLayout.viewport`). */
  function pxToUnits(vp,dx,dy){
    const s=vp&&vp.scale>0?vp.scale:1;
    return {dx:dx/s,dy:dy/s};
  }

  /* Déplacer : la taille est celle de départ, à l'identique (`placeClamp`). */
  function dragBox(start,dx,dy,representation){
    return placeClamp({x:start.x+dx,y:start.y+dy,w:start.w,h:start.h},representation);
  }

  /* Redimensionner par le coin bas droit : le coin haut gauche ne bouge pas
     (sauf s'il était hors de la zone sûre), la taille ne dépasse ni le minimum,
     ni le maximum de la forme, ni le bord de la zone. */
  function resizeBox(start,dw,dh,representation){
    const min=MIN_SIZE[representation]||{w:1,h:1};
    const x=clamp(start.x,SAFE_AREA.x0,SAFE_AREA.x1-min.w),y=clamp(start.y,SAFE_AREA.y0,SAFE_AREA.y1-min.h);
    const w=clamp(start.w+dw,min.w,SAFE_AREA.x1-x);
    const h=clamp(start.h+dh,min.h,SAFE_AREA.y1-y);
    return orbitShrink(boundPlace(boundSize({x,y,w,h},representation)),start,representation);
  }

  const resizable=representation=>representation==='capsule'||representation==='window';

  /* ------------------------------------ manipulation à mains nues (Slice 06)

     Décisions 10, 11, 16, 17, 18 et 19 du handoff `jarvis-bare-hands-v1`. Ce
     bloc est le **seul endroit** où des pixels de fenêtre deviennent des unités
     de scène : le moteur Bare Hands mesure tout en pixels (`boundsPx`,
     `palmX`/`palmY`, comme `clientX`), la scène vit en unités (±160 × ±90). Une
     conversion faite ailleurs se déboguerait comme un défaut de géométrie dans
     le mauvais module.

     Ce bloc ne décide **jamais** quelle main tient quels côtés : cette règle
     est celle de `combineCaptures`
     (`control_center_barehands_contracts.js`, décisions 12 et 14-17) et arrive
     ici sous forme de données — un côté, un déplacement. Deux tables des côtés
     auraient divergé en silence. */

  /* Invariant de paire des constantes de forme, posé au chargement plutôt que
     découvert sur un cadre qui rétrécit sous son minimum. `clamp(v,lo,hi)` rend
     `hi` quand `lo > hi` : un maximum passé sous le minimum ferait donc gagner
     le **maximum**, et la décision 18 (« borner à la taille minimale ») serait
     silencieusement inversée — aucune exception, aucun test rouge, juste une
     capsule qu'on peut réduire à rien. Il n'y a pas de constructeur ici, donc
     le refus se pose là où les constantes se lisent — dans une fonction
     appelée à l'installation du module, en bas de ce fichier, pour que la
     levée **ne sorte pas d'ici** : la page servie n'a qu'une seule balise
     `<script>` et ce module est le **premier** qui y lève, donc une levée non
     rattrapée y blanchit le Control Center entier — la scène, la timeline, le
     Test Lab et Bare Hands. Confinée, la panne garde sa portée :
     `window.JarvisSceneInteract` reste absent, la console porte la cause, et
     `control_center_barehands.js`, qui lit ce global directement, est rattrapé
     au même titre. */
  function assertSizeBounds(){
    for(const representation of Object.keys(MIN_SIZE)){
      const max=MAX_SIZE[representation];
      if(!max)continue;
      if(max.w<MIN_SIZE[representation].w||max.h<MIN_SIZE[representation].h)
        throw new RangeError(`MAX_SIZE.${representation} ne peut pas passer sous MIN_SIZE.${representation} : le bornage rendrait le maximum et la taille minimale ne tiendrait plus`);
    }
  }

  /* Un axe d'un redimensionnement par les côtés. `dLo`/`dHi` sont les
     déplacements des deux côtés de cet axe, en unités ; `undefined` veut dire
     « ce côté n'est tenu par personne », donc il ne bouge pas — c'est lui
     l'ancre, et c'est ce qui fait qu'un redimensionnement par le bord droit ne
     déplace pas le bord gauche.

     Décision 18, les deux moitiés : la taille finale est bornée à
     `[minSize, maxSize]`, donc **jamais négative** — deux mains qui se croisent
     s'arrêtent à la taille minimale au lieu de retourner le cadre. Quand les
     deux côtés bougent, le manque se répartit **au prorata de ce que chaque
     main a demandé** : une seule règle pour « une main pousse » et « deux mains
     poussent », au lieu d'un cas particulier par situation. */
  function resizeAxis(lo,size,dLo,dHi,minSize,maxSize,bound0,bound1){
    const movesLo=Number.isFinite(dLo),movesHi=Number.isFinite(dHi);
    let a=clamp(lo+(movesLo?dLo:0),bound0,bound1);
    let b=clamp(lo+size+(movesHi?dHi:0),bound0,bound1);
    const wanted=b-a,target=clamp(wanted,minSize,maxSize);
    if(target!==wanted){
      const deficit=target-wanted;
      const wLo=movesLo?Math.abs(dLo):0,wHi=movesHi?Math.abs(dHi):0,sum=wLo+wHi;
      if(!movesLo)b=a+target;
      else if(!movesHi)a=b-target;
      else if(sum>0){a-=deficit*(wLo/sum);b+=deficit*(wHi/sum)}
      else{a-=deficit/2;b+=deficit/2}
    }
    /* Ramener dans la zone sûre **sans changer la taille** : un cadre poussé
       contre le bord s'arrête, il ne maigrit pas. */
    const span=b-a;
    if(a<bound0){a=bound0;b=a+span}
    if(b>bound1){b=bound1;a=b-span}
    return {lo:a,size:b-a};
  }

  /* Redimensionner en tirant sur des **côtés** nommés : `sides` est
     `{left?, right?, top?, bottom?}`, chaque valeur étant le déplacement de ce
     côté le long de son axe, **en unités**. Un côté absent est une ancre.

     C'est la généralisation de `resizeBox` (poignée bas-droite, coin haut
     gauche épinglé), qui reste le chemin de la souris et ne bouge pas. */
  function resizeBySides(start,sides,representation){
    const held=sides&&typeof sides==='object'?sides:{};
    const min=MIN_SIZE[representation]||{w:1,h:1};
    const areaW=SAFE_AREA.x1-SAFE_AREA.x0,areaH=SAFE_AREA.y1-SAFE_AREA.y0;
    const max=MAX_SIZE[representation]||{w:areaW,h:areaH};
    const x=resizeAxis(start.x,start.w,held.left,held.right,min.w,Math.min(max.w,areaW),SAFE_AREA.x0,SAFE_AREA.x1);
    const y=resizeAxis(start.y,start.h,held.top,held.bottom,min.h,Math.min(max.h,areaH),SAFE_AREA.y0,SAFE_AREA.y1);
    return clampBox({x:x.lo,y:y.lo,w:x.size,h:y.size},representation);
  }

  /* Axe de chaque côté. Ce n'est pas la règle du contrat (qui décide **quelle
     main garde quel côté**) mais le sens des mots : « haut » et « bas » bornent
     la hauteur. Le moteur passe donc des côtés déjà attribués, et cette table
     ne fait que les lire. */
  const MANIPULATION_SIDES=Object.freeze({top:'y',bottom:'y',left:'x',right:'x'});

  /* Une image de manipulation, et la **conversion d'unités de la Slice 06**.

     `plan` :
       - `start` — la boîte de référence, en unités (voir `rebaseManipulation`) ;
       - `representation` — la forme, qui porte ses tailles minimale et maximale ;
       - `mode` — `move` (décision 10) ou `resize` (décision 11) ;
       - `axes` — `combineCaptures().axes`, repris tel quel : un axe neutralisé
         par la décision 17 n'y est pas, donc il ne bouge pas ;
       - `sidesPx` — pour un redimensionnement, le déplacement **en pixels de la
         fenêtre** de chaque côté tenu, déjà attribué par `combineCaptures` ;
       - `deltaPx` — pour un déplacement, le déplacement de la main ;
       - `vp` — la fenêtre de la scène (`JarvisSceneLayout.viewport`), d'où vient
         l'échelle (~6 px/unité en 1080p).

     Le seul endroit du dépôt où `pxToUnits` sert au chemin Bare Hands. */
  function manipulateBox(plan){
    const p=plan||{};
    const vp=p.vp,start=p.start,representation=p.representation;
    const axes=Array.isArray(p.axes)?p.axes:['x','y'];
    if(p.mode==='resize'){
      const sidesPx=p.sidesPx&&typeof p.sidesPx==='object'?p.sidesPx:{};
      const units={};
      for(const side of Object.keys(sidesPx)){
        const axis=MANIPULATION_SIDES[side];
        if(!axis)throw new RangeError(`Côté de cadre inconnu : ${String(side)}`);
        if(!axes.includes(axis))continue;   // axe neutralisé (décision 17)
        const value=Number(sidesPx[side]);
        if(!Number.isFinite(value))continue;
        units[side]=axis==='x'?pxToUnits(vp,value,0).dx:pxToUnits(vp,0,value).dy;
      }
      return resizeBySides(start,units,representation);
    }
    const delta=p.deltaPx&&typeof p.deltaPx==='object'?p.deltaPx:{};
    const moved=pxToUnits(vp,Number(delta.dx)||0,Number(delta.dy)||0);
    return dragBox(start,axes.includes('x')?moved.dx:0,axes.includes('y')?moved.dy:0,representation);
  }

  /* **Décision 19**, et elle sert à chaque changement de plan, pas seulement à
     `RESIZE → MOVE` : la nouvelle référence est le cadre **tel qu'il est** et
     les mains **là où elles sont**. Le déplacement suivant vaut donc zéro, et
     le cadre ne saute pas — ni quand une main se retire d'un redimensionnement,
     ni quand une seconde main entre, ni quand un déplacement s'arme.

     Rebaser sur la boîte d'origine et laisser courir les anciennes ancres
     ferait exactement l'inverse : le cadre rattraperait d'un coup tout ce que
     l'autre main avait fait. */
  function rebaseManipulation(box,pointsPx){
    const anchorsPx={};
    const source=pointsPx&&typeof pointsPx==='object'?pointsPx:{};
    for(const key of Object.keys(source)){
      const point=source[key];
      const x=Number(point&&point.x),y=Number(point&&point.y);
      if(Number.isFinite(x)&&Number.isFinite(y))anchorsPx[key]={x,y};
    }
    return {start:{x:box.x,y:box.y,w:box.w,h:box.h},anchorsPx};
  }

  /* Touche → intention. `{type:'move'|'resize', dx, dy}`, `{type:'menu'}`,
     `{type:'nav'}` (flèches seules, Début, Fin) ou null. */
  function keyIntent(event){
    const key=event&&event.key;
    if(key==='ContextMenu'||(key==='F10'&&event.shiftKey&&!event.ctrlKey&&!event.altKey))return {type:'menu'};
    const dirs={ArrowRight:[1,0],ArrowLeft:[-1,0],ArrowDown:[0,1],ArrowUp:[0,-1]};
    if(key==='Home'||key==='End')return event.shiftKey||event.ctrlKey||event.altKey||event.metaKey?null:{type:'nav'};
    const dir=dirs[key];
    if(!dir||event.altKey||event.metaKey)return null;
    if(!event.shiftKey&&!event.ctrlKey)return {type:'nav'};
    if(event.ctrlKey&&!event.shiftKey)return {type:'resize',dx:dir[0]*KEY_STEP,dy:dir[1]*KEY_STEP};
    const step=event.ctrlKey?KEY_STEP_LARGE:KEY_STEP;
    return {type:'move',dx:dir[0]*step,dy:dir[1]*step};
  }

  /* Appliquer une intention clavier à une boîte. Un redimensionnement d'une
     forme qui ne se redimensionne pas (point) ne change rien. */
  function applyKey(box,intent,representation){
    if(!intent)return box;
    if(intent.type==='move')return dragBox(box,intent.dx,intent.dy,representation);
    if(intent.type==='resize'&&resizable(representation))return resizeBox(box,intent.dx,intent.dy,representation);
    return box;
  }

  /* Boîte d'une nouvelle représentation : taille par défaut de la forme,
     même centre, bornée. */
  function representationBox(box,representation,kind){
    const size=representation==='point'?(kind==='attention'?DEFAULT_SIZE.signal:DEFAULT_SIZE.point):DEFAULT_SIZE[representation];
    const cx=box.x+box.w/2,cy=box.y+box.h/2;
    return clampBox({x:cx-size.w/2,y:cy-size.h/2,w:size.w,h:size.h},representation);
  }

  const sameBox=(a,b)=>!!a&&!!b&&a.x===b.x&&a.y===b.y&&a.w===b.w&&a.h===b.h;

  /* -------------------------------------------------- signaux et archivage */

  const workKey=ref=>ref&&typeof ref.source==='string'&&typeof ref.external_id==='string'?`${ref.source}\n${ref.external_id}`:null;

  /* Étoile de chaque signal runtime (`attention` d'origine `runtime`), ou
     null (orphelin). Même règle que `signal_owners` : cible du lien de
     signal vivant si c'est un nœud d'exécution, sinon première étoile du même
     travail Core. */
  function signalOwners(state){
    const stars=new Map();
    for(const item of state.objects.values()){
      const key=EXECUTION_KINDS.has(item.kind)?workKey(item.work_ref):null;
      if(key&&!stars.has(key))stars.set(key,item.object_id);
    }
    const owners=new Map();
    for(const item of state.objects.values()){
      if(item.kind!=='attention'||item.origin!=='runtime')continue;
      const rel=state.relations.get(item.object_id);
      const target=rel&&rel.kind==='explains'&&rel.relation_id===rel.from_id?state.objects.get(rel.to_id):null;
      if(target&&EXECUTION_KINDS.has(target.kind))owners.set(item.object_id,target.object_id);
      else{const key=workKey(item.work_ref);owners.set(item.object_id,key&&stars.has(key)?stars.get(key):null)}
    }
    return owners;
  }

  /* Signaux runtime qu'emporte l'archivage de `objectId` (cascade). */
  function cascadeOf(state,objectId,owners){
    const map=owners||signalOwners(state);
    const out=[];
    for(const [signal,owner] of map)if(owner===objectId)out.push(signal);
    return out;
  }

  /* La constellation d'un objet : lui, et tout ce qui lui tient de proche en
     proche. Les liens comptent **sans leur sens** : à l'œil, un parent, un
     enfant, un artefact qui explique et un signal forment une seule figure, et
     c'est cette figure entière que l'utilisateur veut prendre d'un bloc — la
     remonter par `parent_of` seulement laisserait les frères derrière.
     Un signal sans lien vivant est rattaché par son travail (`signalOwners`),
     la même règle qu'à l'archivage : sans elle il resterait seul en arrière
     quand sa constellation s'en va. Les objets archivés n'en sont pas : on ne
     garde que ce que `state.objects` porte encore.
     Rend un tableau, l'objet demandé en tête (il reste l'ancre du menu et du
     clavier), puis les autres dans l'ordre de découverte ; un objet sans
     attache rend `[objectId]`.
     Copie locale de `constellation_of` (`jarvis/domain/scene_selection.py`,
     source de vérité, docs/scene-selection-batch.md §2) pour la sélection
     instantanée : même graphe, même ordre, objets masqués compris ; sans
     profondeur (composante entière). Parité tenue par les fixtures partagées
     `tests/fixtures/scene_constellation_cases.json`. */
  function constellationOf(state,objectId){
    if(!state||!state.objects||!state.objects.has(objectId))return [];
    const near=new Map();
    const tie=(a,b)=>{
      if(!a||!b||a===b)return;
      if(!state.objects.has(a)||!state.objects.has(b))return;
      if(!near.has(a))near.set(a,[]);
      if(!near.has(b))near.set(b,[]);
      near.get(a).push(b);near.get(b).push(a);
    };
    for(const relation of state.relations.values())if(relation)tie(relation.from_id,relation.to_id);
    for(const [signal,owner] of signalOwners(state))tie(signal,owner);
    const out=[objectId],seen=new Set([objectId]);
    for(let at=0;at<out.length;at++)
      for(const next of near.get(out[at])||[])
        if(!seen.has(next)){seen.add(next);out.push(next)}
    return out;
  }

  /* Rectangle de sélection tiré dans le vide, en pixels de fenêtre : la boîte
     normalisée entre le point d'appui et le point courant. Tirer vers le haut
     ou vers la gauche donne le même rectangle que vers le bas et la droite. */
  function bandBox(start, current) {
    const left = Math.min(start.x, current.x), top = Math.min(start.y, current.y);
    return {left, top, width: Math.abs(current.x - start.x), height: Math.abs(current.y - start.y)};
  }

  /* Un rectangle de sélection compte à partir de ce côté (px). En deçà, l'appui
     reste un clic dans le vide — qui, lui, désélectionne. */
  const BAND_MIN_PX = 6;

  function bandStarted(band) {
    return !!band && Math.max(band.width, band.height) >= BAND_MIN_PX;
  }

  /* Objets pris par le rectangle : ceux dont la boîte **dessinée** le touche.
     Dessinée, et non rangée : le champ tourne, et c'est ce que l'utilisateur
     voit qu'il encercle. Toucher suffit — exiger l'objet entier obligerait à
     englober les fenêtres pour les prendre. */
  function bandHits(band, boxes) {
    if (!bandStarted(band)) return [];
    const right = band.left + band.width, bottom = band.top + band.height;
    const out = [];
    for (const box of boxes || []) {
      if (!box || typeof box.id !== 'string') continue;
      if (box.left <= right && box.left + box.width >= band.left
          && box.top <= bottom && box.top + box.height >= band.top) out.push(box.id);
    }
    return out;
  }

  /* La sélection après un geste : `mode` vaut « replace » (la sélection devient
     celle du rectangle), « add » (Ctrl ou Maj tenu : on ajoute) ou « toggle »
     (Ctrl-clic sur un objet : présent, il sort ; absent, il entre). Rend un
     tableau, dans l'ordre d'entrée : le dernier entré sert d'ancre au menu et
     aux touches. */
  function nextSelection(current, ids, mode) {
    const chosen = Array.isArray(ids) ? ids.filter(id => typeof id === 'string' && id) : [];
    const kept = Array.isArray(current) ? current.filter(id => typeof id === 'string' && id) : [];
    if (mode === 'toggle') {
      const out = kept.slice();
      for (const id of chosen) {
        const at = out.indexOf(id);
        if (at < 0) out.push(id); else out.splice(at, 1);
      }
      return out;
    }
    if (mode === 'add') {
      const out = kept.slice();
      for (const id of chosen) if (out.indexOf(id) < 0) out.push(id);
      return out;
    }
    const out = [];
    for (const id of chosen) if (out.indexOf(id) < 0) out.push(id);
    return out;
  }

  /* Sélection « Archiver les travaux terminés » : étoiles terminées, et
     signaux runtime orphelins. Les signaux d'une étoile sélectionnée partent
     par la cascade : comptés, pas envoyés. Jamais un travail en cours, en
     attente, bloqué ou d'état inconnu ; jamais un objet du cerveau ou de
     l'utilisateur. */
  function bulkSelection(state){
    const owners=signalOwners(state);
    const ids=[],stars=[],byState={completed:0,failed:0,cancelled:0,interrupted:0};
    for(const item of state.objects.values()){
      if(EXECUTION_KINDS.has(item.kind)&&TERMINAL.includes(item.exec_state)){
        ids.push(item.object_id);stars.push(item.object_id);byState[item.exec_state]++;
      }
    }
    const chosen=new Set(stars);
    let cascaded=0,orphans=0;
    for(const [signal,owner] of owners){
      if(owner===null){ids.push(signal);orphans++}
      else if(chosen.has(owner))cascaded++;
    }
    return {ids,stars:stars.length,byState,cascaded,orphans,objects:stars.length+cascaded+orphans};
  }

  /* Découper une sélection en commandes `archive_many` dans les bornes du
     domaine et du transport. Une seule commande dans le cas courant. */
  function chunkIds(ids,maxIds=MAX_ARCHIVE_IDS,maxBytes=MAX_COMMAND_BYTES){
    const chunks=[];let current=[],bytes=0;
    const size=id=>utf8Length(JSON.stringify(id))+1;
    for(const id of ids){
      const cost=size(id);
      if(current.length&&(current.length>=maxIds||bytes+cost>maxBytes)){chunks.push(current);current=[];bytes=0}
      current.push(id);bytes+=cost;
    }
    if(current.length)chunks.push(current);
    return chunks;
  }

  function utf8Length(text){
    let n=0;
    for(const ch of text){const c=ch.codePointAt(0);n+=c<0x80?1:c<0x800?2:c<0x10000?3:4}
    return n;
  }

  /* ------------------------------------------------------------------ menu */

  const REPRESENTATION_LABELS=Object.freeze({point:'Afficher en point',capsule:'Afficher en capsule',window:'Afficher en fenêtre'});

  /* Entrées du menu d'un objet (`state` : état dessiné, affichage optimiste
     compris). Rend `{title, items}` ; `items` : `'-'` ou
     `{act, label, danger?, disabled?, note?}`. Actions : `rep:<forme>`, `pin`,
     `unpin`, `hide`, `stop`, `archive`, `archive-finished`, `archive-orphans`. */
  function menuModel(state,objectId,ctx){
    const item=state.objects.get(objectId);
    if(!item)return null;
    const context=ctx||{};
    const execution=EXECUTION_KINDS.has(item.kind);
    const runtimeSignal=item.kind==='attention'&&item.origin==='runtime';
    const title=String(context.title||item.payload&&item.payload.title||objectId);
    const items=[];
    for(const representation of ['point','capsule','window'])
      if(representation!==item.representation)items.push({act:`rep:${representation}`,label:REPRESENTATION_LABELS[representation]});
    items.push('-');
    if(item.constraints&&item.constraints.pinned_by_user)items.push({act:'unpin',label:'Désépingler'});
    else items.push({act:'pin',label:'Épingler ici'});
    items.push({act:'hide',label:'Masquer'});
    /* Prendre la figure entière plutôt que l'étoile seule : le clic droit vient
       de remplacer la sélection par ce seul objet, et d'ici l'utilisateur la
       rouvre à tout ce qui lui tient — pour déplacer l'ensemble d'un bloc, ce
       que le geste sait déjà faire d'une sélection multiple. L'entrée ne paraît
       que s'il y a effectivement de quoi élargir : sur une étoile sans attache,
       elle ne ferait que répéter la sélection courante. */
    const constellation=constellationOf(state,objectId);
    if(constellation.length>1)
      items.push({act:'select-constellation',
        label:`Sélectionner toute la constellation (${constellation.length} objets)`});
    items.push('-');
    /* Slice 10 : état inconnu depuis le redémarrage de Core. Aucun arrêt
       (rien ne tourne dans ce Core qui puisse être visé) : une note le dit. */
    if(execution&&item.exec_state==='unknown')
      items.push({act:'state-unknown',label:'État inconnu depuis le redémarrage de Core',note:true});
    if(execution&&ACTIVE_WORK.has(item.exec_state)){
      if(item.kind==='job'&&item.work_ref&&item.work_ref.source==='job')items.push({act:'stop',label:'Arrêter la tâche…',danger:true});
      /* Note annoncée (focalisable, `aria-disabled`), pas un bouton désactivé
         que le clavier et le lecteur d'écran sautent. */
      else items.push({act:'stop-unavailable',label:'Arrêt impossible : sous-agent du brain',note:true});
    }
    const signals=execution?cascadeOf(state,objectId).length:0;
    items.push({act:'archive',label:signals?(signals>1?'Archiver avec ses signaux…':'Archiver avec son signal…'):'Archiver…',danger:true});
    const finished=Number(context.finished)||0;
    if((execution||runtimeSignal)&&finished>0)
      items.push({act:'archive-finished',label:`Archiver les travaux terminés (${finished} ${finished>1?'objets':'objet'})…`,danger:true});
    /* Slice 07 (reprise QA) : artefacts qui n'expliquent plus rien, depuis le menu d'un artefact ou d'une étoile. */
    const orphans=Number(context.orphans)||0;
    if((item.kind==='artifact'||execution)&&orphans>0)
      items.push({act:'archive-orphans',label:`Archiver les artefacts orphelins (${orphans})…`,danger:true});
    return {title,items};
  }

  /* ------------------------------------------------------------ commandes */

  const commands=Object.freeze({
    setGeometry:(id,box)=>({schema_version:1,op:'set_geometry',object_id:id,geometry:{x:box.x,y:box.y,w:box.w,h:box.h}}),
    pin:id=>({schema_version:1,op:'pin',object_id:id}),
    unpin:id=>({schema_version:1,op:'unpin',object_id:id}),
    setRepresentation:(id,representation,box)=>({schema_version:1,op:'set_representation',object_id:id,representation,
      ...(box?{geometry:{x:box.x,y:box.y,w:box.w,h:box.h}}:{})}),
    setVisibility:(id,visibility)=>({schema_version:1,op:'set_visibility',object_id:id,visibility}),
    archive:id=>({schema_version:1,op:'archive',object_id:id}),
    archiveMany:ids=>({schema_version:1,op:'archive_many',object_ids:[...ids]}),
  });

  /* Refus du domaine dans les mots de l'utilisateur. */
  const REFUSALS=Object.freeze({
    unknown_object:"l'objet n'est plus dans la scène",
    object_archived:"l'objet est déjà archivé",
    pinned_by_user:"l'objet est épinglé",
    unplaced:"l'objet n'a pas encore de place",
    scene_full:'la scène est pleine',
    not_bulk_archivable:'la scène a changé : un objet choisi n’est plus un travail terminé',
    op_not_allowed:'action non permise',
    revision_exhausted:'la scène ne peut plus changer',
  });

  /* Échecs de transport dans les mots de l'utilisateur, comme le classement
     de Slice 03 (`classify_scene_call_failure`) : `unknown` vrai quand la
     demande a pu partir (issue inconnue, l'état relu dira ce qui s'est
     passé), faux quand rien n'a été appliqué. Le texte brut (anglais,
     adresses) ne va qu'à la console. */
  const TRANSPORT=Object.freeze({
    command_not_sent:['Core ne répond pas : rien n’a été envoyé, réessayer est sûr.',false],
    core_timeout:['Core n’a pas répondu à temps : issue inconnue, la scène se relit.',true],
    scene_unavailable:['Scène indisponible dans Core : rien n’a été appliqué.',false],
    scene_persist_failed:['Core n’a pas pu enregistrer : rien n’a été appliqué.',false],
    invalid_scene_response:['Réponse de Core illisible : issue inconnue, la scène se relit.',true],
    core_refused:['Core a refusé la demande.',false],
    invalid_request:['Demande refusée : forme invalide.',false],
    payload_too_large:['Demande trop grosse : rien n’a été envoyé.',false],
    scene_actor_forbidden:['Demande refusée : acteur non permis.',false],
    not_configured:['Scène non reliée à Core dans ce Control Center.',false],
    not_found:['Core ne connaît pas ce job (déjà oublié, ou Core redémarré).',false],
    not_cancellable:['Ce travail n’a pas d’arrêt individuel.',false],
    timeout:['Pas de réponse du Control Center : issue inconnue, la scène se relit.',true],
    network_error:['Control Center injoignable : issue inconnue, la scène se relit.',true],
  });

  function transportFailure(status,body){
    const payload=body&&typeof body==='object'?body:{};
    const error=payload.error&&typeof payload.error==='object'?payload.error:{};
    const code=typeof error.code==='string'?error.code:(status?`http_${status}`:'network_error');
    const detail=typeof error.message==='string'?error.message:'';
    let words=TRANSPORT[code];
    if(code==='core_unreachable')
      words=/non envoy/i.test(detail)?['Core injoignable : rien n’a été envoyé.',false]:['Liaison à Core perdue : issue inconnue, la scène se relit.',true];
    if(!words)words=[status?`Erreur ${status} du Control Center.`:'Control Center injoignable : issue inconnue, la scène se relit.',status===0||status>=500];
    return {code,message:words[0],unknown:words[1],detail};
  }

  /* Échec d'un `fetch` (aucune réponse HTTP) : délai de la page, ou réseau. La
     page ne sait pas si la demande est partie : issue inconnue. */
  function networkFailure(error){
    return transportFailure(0,{error:{code:error&&error.code==='timeout'?'timeout':'network_error',message:String(error&&error.message||'')}});
  }

  /* Réponse de `POST /api/scene/commands` → `{ok, outcome, reason, code,
     message, revision, unknown, detail}`. `ok` : appliquée ou sans effet. */
  function classifyResponse(status,body){
    const payload=body&&typeof body==='object'?body:{};
    if(status===200&&typeof payload.outcome==='string'){
      const ok=payload.outcome==='applied'||payload.outcome==='duplicate';
      const reason=typeof payload.reason==='string'?payload.reason:'';
      return {ok,outcome:payload.outcome,reason,code:'',revision:Number.isSafeInteger(payload.revision)?payload.revision:null,unknown:false,
        message:ok?'':`refusé : ${REFUSALS[reason]||reason||payload.outcome}`,detail:''};
    }
    const failure=transportFailure(status,payload);
    return {ok:false,outcome:'failed',reason:'',revision:null,...failure};
  }

  /* Issue d'un arrêt de job (`POST /api/jobs/cancel`) : titre, précision,
     ton, et si l'étoile doit encore attendre sa fin (`terminal` faux). */
  function stopOutcome(outcome,status){
    /* Le worker avait déjà rendu son issue : elle gagne, dite telle quelle. */
    if(outcome==='already_terminal'){
      const words={completed:'Elle a fini normalement.',failed:'Elle a fini en échec.',cancelled:'Elle était déjà annulée.',interrupted:'Elle avait été interrompue.'};
      return {title:'La tâche s’était déjà terminée',sub:words[status]||'Rien à arrêter.',kind:'info',terminal:true};
    }
    return ({
      cancelled:{title:'Tâche arrêtée',sub:'Le job est annulé.',kind:'ok',terminal:true},
      already_terminal:{title:'Tâche déjà terminée',sub:'Rien à arrêter.',kind:'info',terminal:true},
      cancel_requested:{title:'Arrêt demandé',sub:'Core n’a pas encore confirmé la fin du job.',kind:'info',terminal:false},
      cleanup_unknown:{title:'Arrêt demandé, nettoyage non confirmé',sub:'Le job reste en cours tant que son exécution n’est pas nettoyée.',kind:'warn',terminal:false},
    })[outcome]||{title:'Arrêt : issue inattendue',sub:String(outcome||''),kind:'warn',terminal:false};
  }

  /* Objet à sélectionner quand `removed` quitte le dessin : le suivant dans
     l'ordre de lecture (`orderedIds`, ordre spatial), sinon le précédent. */
  function focusAfterRemoval(orderedIds,removed,currentId){
    const gone=new Set(removed);
    const index=orderedIds.indexOf(currentId);
    const start=index<0?0:index;
    for(let i=start+1;i<orderedIds.length;i++)if(!gone.has(orderedIds[i]))return orderedIds[i];
    for(let i=Math.min(start,orderedIds.length)-1;i>=0;i--)if(!gone.has(orderedIds[i]))return orderedIds[i];
    if(index<0)for(const id of orderedIds)if(!gone.has(id))return id;
    return null;
  }

  /* ---------------------------------------------------- affichage optimiste */

  /* Modifications envoyées, dessinées avant que Core ne les confirme. Une
     **couche** par opération (`geometry`, `representation`, `visibility`,
     `pinned`, `archived`), dans l'ordre d'envoi : `begin` ajoute une couche et
     rend son jeton ; `confirm` note la révision rendue pour cette couche ;
     `drop` retire un champ d'une couche ; `rollback` retire **cette couche
     seulement** (une opération plus récente refusée ne défait jamais une plus
     ancienne acceptée mais pas encore reçue) ; `prune(state, now)` retire les
     couches que l'état tenu montre déjà (révision atteinte) ou qui ont trop
     attendu ; `overlay(state)` applique les couches dans l'ordre. `version`
     change à chaque modification (mémoïsation). */
  function createPending(maxAgeMs=PENDING_MAX_MS){
    const layers=new Map();let seq=0,version=0;
    const find=(id,token)=>{const list=layers.get(id);return list?list.find(layer=>layer.token===token)||null:null};
    const remove=(id,layer)=>{
      const list=layers.get(id);
      const at=list?list.indexOf(layer):-1;
      if(at<0)return false;
      list.splice(at,1);if(!list.length)layers.delete(id);version++;
      return true;
    };
    return {
      begin(id,fields,now){
        const layer={fields:{...fields},token:++seq,revision:null,at:now};
        if(!layers.has(id))layers.set(id,[]);
        layers.get(id).push(layer);version++;
        return layer.token;
      },
      confirm(id,token,revision){
        const layer=find(id,token);
        if(!layer)return false;
        if(Number.isSafeInteger(revision))layer.revision=Math.max(layer.revision||0,revision);
        return true;
      },
      drop(id,token,field){
        const layer=find(id,token);
        if(!layer||!(field in layer.fields))return false;
        delete layer.fields[field];version++;
        if(!Object.keys(layer.fields).length)remove(id,layer);
        return true;
      },
      rollback(id,token){
        if(token===undefined){if(!layers.delete(id))return false;version++;return true}
        const layer=find(id,token);
        return layer?remove(id,layer):false;
      },
      prune(state,now){
        const removed=[];
        for(const [id,list] of [...layers]){
          for(const layer of [...list]){
            const reached=layer.revision!==null&&!!state&&state.revision>=layer.revision;
            const expired=now-layer.at>maxAgeMs;
            if(reached||expired){remove(id,layer);removed.push({id,token:layer.token,reason:reached?'reached':'expired'})}
          }
        }
        return removed;
      },
      overlay(state){
        if(!state||!layers.size)return state;
        let objects=null;
        for(const [id,list] of layers){
          const item=state.objects.get(id);
          if(!item)continue;
          if(!objects)objects=new Map(state.objects);
          const fields=Object.assign({},...list.map(layer=>layer.fields));
          if(fields.archived){objects.delete(id);continue}
          const next={...item};
          if(fields.geometry)next.geometry={...fields.geometry};
          if(fields.representation)next.representation=fields.representation;
          if(fields.visibility)next.visibility=fields.visibility;
          if(typeof fields.pinned==='boolean')next.constraints={...item.constraints,pinned_by_user:fields.pinned};
          objects.set(id,next);
        }
        return objects?{...state,objects}:state;
      },
      has:id=>layers.has(id),
      size:()=>layers.size,
      version:()=>version,
    };
  }

  /* Étapes d'une géométrie de l'utilisateur (toute géométrie épingle) :
     l'épingle d'abord, puis la position ; un objet sans géométrie ne
     s'épingle pas : position, épingle, position de nouveau. */
  function geometrySteps(wasPinned,placed){
    if(wasPinned)return ['geometry'];
    return placed?['pin','geometry']:['geometry','pin','geometry'];
  }

  /* Envoyer les étapes d'une géométrie de l'utilisateur sur la couche
     optimiste `token`. La couche n'est confirmée qu'après la **dernière**
     étape, à la plus grande révision rendue : confirmer après une étape
     intermédiaire laisserait l'élagage retirer l'aperçu avant que la position
     n'arrive (retour visuel à l'origine). Échec : désépinglage compensatoire
     si l'épingle venait de cette opération, puis retrait de la couche.
     `send(command)` rend la réponse classée (`classifyResponse`). */
  async function commitGeometry({id,box,wasPinned,placed,send,pending,token}){
    const steps=geometrySteps(wasPinned,placed);
    let pinnedNow=false,revision=null;
    for(const step of steps){
      const result=await send(step==='pin'?commands.pin(id):commands.setGeometry(id,box));
      if(!result.ok){
        const undo=pinnedNow&&!wasPinned?await send(commands.unpin(id)):null;
        const rolledBack=pending.rollback(id,token);
        return {ok:false,step,result,undo,rolledBack,steps,pinned:pinnedNow};
      }
      if(step==='pin')pinnedNow=true;
      if(Number.isSafeInteger(result.revision))revision=Math.max(revision||0,result.revision);
    }
    pending.confirm(id,token,revision);
    return {ok:true,steps,revision,pinned:pinnedNow};
  }

  /* Disposition sur laquelle le résolveur valide ses placements : celle de
     l'état tenu (`held`), jamais celle de l'état dessiné avec les
     modifications optimistes (`drawn`), qui peuvent encore être refusées.
     Sans modification en attente (`drawn === held`), la disposition dessinée
     sert telle quelle. `resolve` : `JarvisSceneLayout.resolveLayout`. */
  function commitLayout(held,drawn,drawnLayout,resolve){
    if(!held)return null;
    return drawn===held&&drawnLayout?drawnLayout:resolve(held);
  }

  /* Objets masqués, dans l'ordre de Core. */
  function hiddenObjects(state){
    const out=[];
    for(const item of state.objects.values())
      if(item.visibility==='hidden')out.push({id:item.object_id,kind:item.kind,title:String(item.payload&&item.payload.title||'')});
    return out;
  }

  const api=Object.freeze({FRAME,SAFE_AREA,KEY_STEP,KEY_STEP_LARGE,MIN_SIZE,MAX_SIZE,DEFAULT_SIZE,DRAG_THRESHOLD_PX,COARSE_DRAG_THRESHOLD_PX,
    LONG_PRESS_MS,PENDING_MAX_MS,MAX_ARCHIVE_IDS,MAX_COMMAND_BYTES,TERMINAL,REFUSALS,TRANSPORT,
    ORBIT_AXES,QUANTUM,clampBox,orbitFits,dragThreshold,pxToUnits,dragBox,resizeBox,resizable,keyIntent,applyKey,representationBox,sameBox,
    MANIPULATION_SIDES,resizeBySides,manipulateBox,rebaseManipulation,
    signalOwners,cascadeOf,constellationOf,bulkSelection,chunkIds,menuModel,commands,BAND_MIN_PX,bandBox,bandStarted,bandHits,nextSelection,transportFailure,networkFailure,classifyResponse,stopOutcome,
    focusAfterRemoval,commitLayout,geometrySteps,commitGeometry,createPending,hiddenObjects});
  /* **La levée reste, mais elle ne sort pas d'ici** — même forme que
     l'enregistreur Bare Hands (§12) et le canal de commandes. Rattrapée, la
     panne de l'invariant de paire garde sa portée : ce module ne s'installe
     pas, la console porte la cause sous un nom cherchable, et le reste de la
     page vit. Non rattrapée, elle blanchissait le Control Center entier, ce
     module étant le premier du `<script>` unique de la page servie. */
  try{
    assertSizeBounds();
    root.JarvisSceneInteract=api;
    if(typeof module!=='undefined'&&module.exports)module.exports=api;
  }catch(error){
    console.error('[scene] scene.interact_not_installed '
      +JSON.stringify({error:String(error&&error.message||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
