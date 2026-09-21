/* Scène constellation : logique pure des interactions de l'utilisateur (handoff
   jarvis-constellation-scene-runtime, Slice 08).

   - Géométrie : glisser, redimensionner, flèches du clavier, changement de
     représentation. Les gestes passent tous par la **tenue** (`createHold`) :
     bornés à l'écran réellement visible moins les commandes de la page, et
     enregistrés à la place dont le dessin est ce que l'utilisateur a lâché.
     Les actions du menu restent bornées à la zone de composition sûre
     (`SAFE_AREA`, x -152..138, y -72..68), comme le résolveur. Au dixième
     d'unité.
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
     du domaine et `SAFE_AREA` du rendu (tests de parité). Elle borne ce que la
     page **propose** (changement de forme, place du résolveur) ; un geste de
     l'utilisateur, lui, va partout où l'objet reste visible (22/09/2026 : la
     zone, calibrée pour 1280 × 720, laissait de 132 à 452 px interdits aux
     bords d'un grand écran, sans rien dessus). */
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
     Le dixième d'unité fait ~0,6 px : `scene_inspect` reste lisible, et un geste
     d'un pixel ne fabrique toujours pas de révision. Depuis le 22/09/2026, seule
     la place **enregistrée** passe sur cette grille, au lâcher
     (`JarvisSceneLayout.holdPlace`, même valeur, test de parité) : l'aperçu
     suit la main sans marches. */
  const QUANTUM=10,quantize=v=>Math.round(v*QUANTUM)/QUANTUM;

  /* Boîte bornée à la zone sûre : taille ≥ minimum et ≤ maximum de la forme (et
     ≤ zone), coin haut gauche gardé pour que la boîte entière tienne dans la
     zone. Ne sert plus qu'aux actions du menu (changement de forme, épingler un
     objet sans place) : une place que Core n'a jamais vue y est proposée comme
     le résolveur la proposerait. **Les gestes ne passent pas par ici** : ils
     sont bornés à l'écran réellement visible (`createHold`). */
  function clampBox(box,representation){
    return boundPlace(boundSize(box,representation));
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

  /* Seuil de glissement pour un pointeur. */
  function dragThreshold(pointerType,barehands){
    return pointerType==='mouse'&&!barehands?DRAG_THRESHOLD_PX:COARSE_DRAG_THRESHOLD_PX;
  }

  /* Écart en pixels → écart en unités pour la fenêtre `vp` (`JarvisSceneLayout.viewport`). */
  function pxToUnits(vp,dx,dy){
    const s=vp&&vp.scale>0?vp.scale:1;
    return {dx:dx/s,dy:dy/s};
  }

  /* Déplacer : la boîte suit la main, à l'identique, taille comprise — la
     seule chose qu'un déplacement ne touche jamais. **Aucune borne ici**
     (22/09/2026) : où la main peut emmener un objet est une question d'écran,
     pas de boîte, et c'est la tenue qui y répond (`createHold`). La borne
     d'avant, appliquée ici, était l'ellipse du tour, dans le repère de la place
     non tournée : un mur au milieu de l'écran. */
  function dragBox(start,dx,dy){
    return {x:start.x+(Number(dx)||0),y:start.y+(Number(dy)||0),w:start.w,h:start.h};
  }

  /* Redimensionner par le coin bas droit : le coin haut gauche ne bouge pas, la
     taille ne passe ni sous le minimum ni au-dessus du maximum de la forme. Les
     bords de l'écran et les commandes, eux, sont ceux de la tenue. */
  function resizeBox(start,dw,dh,representation){
    return boundSize({x:start.x,y:start.y,w:start.w+(Number(dw)||0),h:start.h+(Number(dh)||0)},representation);
  }

  const resizable=representation=>representation==='capsule'||representation==='window';

  /* ------------------------------------------------ tenue d'un objet (gestes)

     **Une seule chaîne pour tous les gestes** (22/09/2026) : souris
     (déplacement d'un objet ou d'une sélection, poignée), Bare Hands
     (`JarvisScene.frames`) et clavier. Chacun ne produit qu'une **boîte
     voulue**, dans le repère du dessin — là où l'utilisateur voit l'objet et
     pose son pointeur ; la tenue la borne, la montre, puis rend la place à
     enregistrer.

     Ce qui l'a imposée : sept défauts d'un même contrat, chacun dans un chemin
     différent. La souris, seule, défaisait le tour au lâcher (`placeOf`) ; Bare
     Hands et le clavier enregistraient la boîte dessinée telle quelle, et
     l'objet sautait de 300 à 400 px au lâcher, en miroir du geste. Les bornes
     s'appliquaient à la place enregistrée, pas à ce que l'utilisateur voit :
     l'ellipse du tour devenait un mur au milieu de l'écran, et la zone sûre
     calibrée pour 1280 × 720 laissait de 132 à 452 px interdits aux bords d'un
     grand écran.

     Les passages entre les deux repères sont ceux du rendu
     (`JarvisSceneLayout.holdStart` et `holdPlace`), reçus en `layout` : ce
     module s'installe sans le rendu (il est inséré avant lui), il ne le lit
     qu'à l'appel. */

  /* Où une main peut emmener un objet : **l'écran réellement visible**
     (`vp.visible`), moins les commandes de la page réellement présentes,
     mesurées (`controlsPx` : rectangles en pixels de la scène). Rien d'autre —
     ni zone sûre, ni ellipse. En unités, repère du dessin. */
  function holdArea(vp,controlsPx){
    const s=vp&&vp.scale>0?vp.scale:1;
    const visible=vp&&vp.visible||{x0:-FRAME.halfWidth,x1:FRAME.halfWidth,y0:-FRAME.halfHeight,y1:FRAME.halfHeight};
    const cx=vp&&Number.isFinite(vp.cx)?vp.cx:0,cy=vp&&Number.isFinite(vp.cy)?vp.cy:0;
    const obstacles=[];
    for(const rect of controlsPx||[]){
      const left=Number(rect&&rect.left),top=Number(rect&&rect.top);
      const width=Number(rect&&rect.width),height=Number(rect&&rect.height);
      if(![left,top,width,height].every(Number.isFinite)||!(width>0&&height>0))continue;
      obstacles.push({x0:(left-cx)/s,x1:(left+width-cx)/s,y0:(top-cy)/s,y1:(top+height-cy)/s});
    }
    return {x0:visible.x0,x1:visible.x1,y0:visible.y0,y1:visible.y1,obstacles};
  }

  const SWEEP_EPS=1e-6;
  const AXIS_KEYS=Object.freeze({x:Object.freeze(['x0','x1','y0','y1']),y:Object.freeze(['y0','y1','x0','x1'])});

  /* De combien l'étendue `extent` peut avancer de `step` (signé) le long de
     `axis` : jusqu'au bord visible, ou jusqu'à la première commande qu'elle
     croiserait. Une borne qu'elle a déjà franchie (objet posé sous une
     commande, ou hors de l'écran par le cerveau) ne la retient pas en arrière
     et ne l'arrête pas en y revenant : elle ne l'empêche que d'aller plus loin.
     Sans cela, la première image d'une prise rabattait l'objet d'un coup. */
  function sweepAxis(extent,step,area,axis){
    if(!step)return 0;
    const [lo,hi,crossLo,crossHi]=AXIS_KEYS[axis];
    const forward=step>0;
    let room=forward?Math.max(area[hi],extent[hi])-extent[hi]:extent[lo]-Math.min(area[lo],extent[lo]);
    for(const o of area.obstacles||[]){
      if(!(o[crossLo]<extent[crossHi]-SWEEP_EPS&&o[crossHi]>extent[crossLo]+SWEEP_EPS))continue;
      if(forward){if(o[lo]>=extent[hi]-SWEEP_EPS)room=Math.min(room,o[lo]-extent[hi])}
      else if(o[hi]<=extent[lo]+SWEEP_EPS)room=Math.min(room,extent[lo]-o[hi]);
    }
    room=Math.max(0,room);
    return forward?Math.min(step,room):Math.max(step,-room);
  }

  /* Un pas commun à plusieurs étendues : la sélection avance d'un bloc, et
     s'arrête ensemble dès que l'un de ses objets touche un bord — chacun
     s'arrêtant sur son propre bord, la sélection se déformait. Un axe après
     l'autre : un objet arrêté en x glisse encore en y le long du bord. */
  function sweepMove(extents,step,area){
    let dx=Number(step&&step.dx)||0,dy=Number(step&&step.dy)||0;
    for(const e of extents){const a=sweepAxis(e,dx,area,'x');if(Math.abs(a)<Math.abs(dx))dx=a}
    for(const e of extents){
      const moved={x0:e.x0+dx,x1:e.x1+dx,y0:e.y0,y1:e.y1};
      const a=sweepAxis(moved,dy,area,'y');if(Math.abs(a)<Math.abs(dy))dy=a;
    }
    return {dx,dy};
  }

  /* Un redimensionnement : chaque côté qui s'écarte avance jusqu'au bord ou à
     la commande qu'il croiserait ; un côté qui rentre n'est jamais retenu. */
  function sweepResize(from,to,area){
    const extent={x0:from.x,x1:from.x+from.w,y0:from.y,y1:from.y+from.h};
    const side=(key,axis,wanted)=>{
      const step=wanted-extent[key];
      const outward=key.endsWith('1')?step>0:step<0;
      return outward?extent[key]+sweepAxis(extent,step,area,axis):wanted;
    };
    extent.x0=side('x0','x',to.x);extent.x1=side('x1','x',to.x+to.w);
    extent.y0=side('y0','y',to.y);extent.y1=side('y1','y',to.y+to.h);
    return {x:extent.x0,y:extent.y0,w:extent.x1-extent.x0,h:extent.y1-extent.y0};
  }

  /* **La tenue.** `options` :
     - `layout` — `JarvisSceneLayout` (`nodeGeometry`, `drawnRect`, `holdStart`,
       `holdPlace`) ;
     - `vp` — la fenêtre de la scène ; `field`, `turn` — le champ **qui tourne
       vraiment** (null sinon) et où il en est à la prise ;
     - `area` — `holdArea`, ou rien pour ne pas borner ;
     - `members` — `[{id, representation, box}]`, les places enregistrées ; le
       premier est l'objet pris.

     Rend un objet dont les boîtes sont toutes dans le repère du dessin :
     `start(id)` (la boîte dessinée à la prise), `drawn(id)` (où elle est),
     `moveBy(du)` (le déplacement de la main depuis la prise, en unités, pour
     toute la sélection), `resizeTo(id, box)`, `to(id, box, mode)` (une boîte
     voulue quelconque : Bare Hands), `offset(id)` (le décalage dessin − place,
     en pixels, que le nœud garde, figé, pendant la tenue), `preview(id)` (la
     boîte à poser dans `transform`), `place(id, turn)` (la place à enregistrer
     pour que l'objet soit dessiné là **au tour `turn`**, celui du lâcher),
     `origin(id)` (la place enregistrée à la prise), `signature()` et
     `rebase({vp, field, turn, area})`.

     **Le champ continue de tourner pendant la tenue** (22/09/2026) : seul
     l'objet tenu est figé, par son propre décalage (`offset`). Arrêter tout le
     champ le décalait de la durée du geste par rapport à l'horloge murale, et
     ce décalage passait d'un onglet à l'autre, et au rechargement. L'objet
     tenu, lui, ne dérive pas d'un pixel sous la main ; c'est au lâcher que sa
     place est calculée, pour le tour de cet instant-là. */
  function createHold(options){
    const o=options||{};
    const L=o.layout;
    for(const name of ['nodeGeometry','drawnRect','holdStart','holdPlace'])
      if(!L||typeof L[name]!=='function')throw new TypeError(`createHold exige layout.${name} (JarvisSceneLayout)`);
    let vp=o.vp,field=o.field||null,turn=Number(o.turn)||0,area=o.area||null;
    if(!vp||!(vp.scale>0))throw new RangeError('createHold exige une fenêtre de scène mesurée (vp.scale)');
    /* Ce que l'œil voit, en unités, par rapport à la boîte : le rectangle que
       la page dessine vraiment (`drawnRect` — 26 px pour une étoile dont la
       boîte en fait 36 en 1080p, bande centrée d'une capsule trop haute,
       pilule d'une fenêtre compacte). C'est lui qui s'arrête aux bords. */
    const insetOf=(representation,box)=>{
      const rect=L.drawnRect(L.nodeGeometry(vp,representation,box)),s=vp.scale;
      const x0=(rect.left-vp.cx)/s,y0=(rect.top-vp.cy)/s;
      return {left:x0-box.x,top:y0-box.y,right:box.x+box.w-x0-rect.width/s,bottom:box.y+box.h-y0-rect.height/s};
    };
    const members=new Map();
    for(const m of o.members||[]){
      const box={x:m.box.x,y:m.box.y,w:m.box.w,h:m.box.h};
      const begun=L.holdStart(vp,m.representation,box,field,turn);
      members.set(m.id,{id:m.id,representation:m.representation,box,offset:begun.offset,
        start:{...begun.held},last:{...begun.held},inset:insetOf(m.representation,box)});
    }
    if(!members.size)throw new RangeError('createHold : aucun objet à tenir');
    const primary=members.values().next().value;
    const member=id=>{const m=members.get(id);if(!m)throw new RangeError(`createHold : objet non tenu ${String(id)}`);return m};
    const extentOf=m=>({x0:m.last.x+m.inset.left,x1:m.last.x+m.last.w-m.inset.right,
      y0:m.last.y+m.inset.top,y1:m.last.y+m.last.h-m.inset.bottom});
    function moveBy(du){
      const want={dx:primary.start.x+(Number(du&&du.dx)||0)-primary.last.x,dy:primary.start.y+(Number(du&&du.dy)||0)-primary.last.y};
      const step=area?sweepMove([...members.values()].map(extentOf),want,area):want;
      for(const m of members.values())m.last={...m.last,x:m.last.x+step.dx,y:m.last.y+step.dy};
    }
    function resizeTo(id,box){
      const m=member(id);
      m.last=area?sweepResize(m.last,box,area):{x:box.x,y:box.y,w:box.w,h:box.h};
    }
    return Object.freeze({
      ids:()=>[...members.keys()],
      origin:id=>({...member(id).box}),
      offset:id=>({...member(id).offset}),
      start:id=>({...member(id).start}),
      drawn:id=>({...member(id).last}),
      moveBy,resizeTo,
      /* Une boîte voulue (Bare Hands), dans le repère du dessin, avec son
         mode : un déplacement va à toute la tenue ; un redimensionnement à cet
         objet. Sans mode, une boîte de la taille de la prise est un
         déplacement. */
      to(id,box,mode){
        const m=member(id);
        const move=mode?mode!=='resize':box.w===m.start.w&&box.h===m.start.h;
        if(move)moveBy({dx:box.x-m.start.x,dy:box.y-m.start.y});
        else resizeTo(id,box);
      },
      preview(id){
        const m=member(id);
        return {x:m.last.x-m.offset.x/vp.scale,y:m.last.y-m.offset.y/vp.scale,w:m.last.w,h:m.last.h};
      },
      place(id,at){
        const m=member(id);
        return L.holdPlace(vp,m.representation,m.last,field,at===undefined?turn:Number(at)||0,m.box);
      },
      signature:()=>holdSignature(vp,field),
      /* Les commandes de la page ont pu apparaître ou bouger pendant le geste
         (bandeau, panneau) : les bords suivent, sans refonder la tenue. */
      setArea(next){area=next||null},
      /* **Refonder la tenue** quand ce qui la définit change sous la main —
         fenêtre redimensionnée, ampleur ou vitesse réglée depuis un autre
         onglet, gravitation coupée, scène devenue calme. Chaque objet garde le
         point de l'écran où il est dessiné (donc reste sous la main) et sa
         taille ; sa boîte tenue, son décalage et sa prise sont recalculés dans
         le nouveau repère. L'appelant repart de la main **là où elle est** :
         le pas suivant vaut zéro, comme la décision 19 de Bare Hands. */
      rebase(next){
        const n=next||{};
        const was=vp;
        vp=n.vp||vp;field=n.field||null;turn=Number(n.turn)||0;area=n.area||area;
        for(const m of members.values()){
          const cx=was.cx+(m.last.x+m.last.w/2)*was.scale,cy=was.cy+(m.last.y+m.last.h/2)*was.scale;
          const held={x:(cx-vp.cx)/vp.scale-m.last.w/2,y:(cy-vp.cy)/vp.scale-m.last.h/2,w:m.last.w,h:m.last.h};
          /* **Re-bornée dans la nouvelle zone** : une fenêtre qui rétrécit sous
             la main ne laisse pas l'objet hors de l'écran (ni sa place hors du
             cadre). Seul le bord visible compte ici ; les commandes, elles,
             bornent le geste qui suit. */
          if(area){
            const inset=insetOf(m.representation,held);
            const fit=(lo,size,a0,a1,i0,i1)=>{
              const x0=lo+i0,x1=lo+size-i1;
              if(x1-x0>=a1-a0)return a0-i0;
              return x0<a0?a0-i0:x1>a1?a1-size+i1:lo;
            };
            held.x=fit(held.x,held.w,area.x0,area.x1,inset.left,inset.right);
            held.y=fit(held.y,held.h,area.y0,area.y1,inset.top,inset.bottom);
          }
          const stored=L.holdPlace(vp,m.representation,held,field,turn,m.box);
          const begun=L.holdStart(vp,m.representation,stored,field,turn);
          m.offset=begun.offset;m.start={...begun.held};m.last={...begun.held};
          m.inset=insetOf(m.representation,stored);
        }
      },
    });
  }

  /* Les objets à figer pendant une tenue, et comment : l'animation du tour
     s'arrête pour eux seuls (classe `sc-held`), et `translate` porte l'écart
     dessin − place que la tenue a calculé à la prise. */
  function freezeStyles(hold){
    return hold.ids().map(id=>{const off=hold.offset(id);return {id,translate:`${off.x}px ${off.y}px`}});
  }

  /* **Dégeler sans enregistrer** (clic, Échap, annulation) : l'objet figé
     rejoint son tour à l'heure murale par un court glissement, jamais d'un
     saut d'une image. `frozen` : l'écart figé (px), `live` : celui que le tour
     lui donne maintenant, `rect` : son rectangle posé (`transform`). Rend
     `null` quand il n'y a rien à rattraper, sinon les deux images-clés d'une
     animation de `transform` (le tour, lui, continue dans `translate`) et sa
     durée : 400 ms pour un clic, jusqu’à 600 ms pour un long appui à vitesse
     4 — assez pour qu'aucune image ne dépasse le pixel dans le cas courant.
     Ne sert **jamais** au lâcher d'un glissement, qui se pose à l'endroit
     exact (`commitHold`). */
  const THAW_MIN_MS=400,THAW_MAX_MS=600,THAW_MS_PER_PX=40;
  function thawAnimation(frozen,live,rect){
    const dx=(Number(frozen&&frozen.x)||0)-(Number(live&&live.x)||0);
    const dy=(Number(frozen&&frozen.y)||0)-(Number(live&&live.y)||0);
    const distance=Math.hypot(dx,dy);
    if(!(distance>.5))return null;
    return {keyframes:[{transform:`translate(${rect.left+dx}px,${rect.top+dy}px)`},{transform:`translate(${rect.left}px,${rect.top}px)`}],
      duration:Math.round(Math.min(THAW_MAX_MS,Math.max(THAW_MIN_MS,distance*THAW_MS_PER_PX))),easing:'ease-in-out',distance};
  }

  /* **Le relais des boîtes du moteur Bare Hands** vers une tenue. Le moteur
     calcule depuis sa propre boîte de départ ; après une refonte de la tenue
     (`rebase`), cette boîte est dans l'ancien repère : la première boîte qui
     suit devient la référence, et seuls ses écarts à elle comptent — le cadre
     ne saute pas. `rebased(drawn)` : la tenue vient d'être refondue, `drawn`
     est la boîte tenue qu'elle montre ; `map(box)` : la boîte voulue. */
  function createRelay(){
    let pending=null,base=null,anchor=null;
    return Object.freeze({
      rebased(drawn){pending={...drawn}},
      map(box){
        if(pending){base={...box};anchor=pending;pending=null}
        if(!base)return box;
        return {x:anchor.x+box.x-base.x,y:anchor.y+box.y-base.y,w:anchor.w+box.w-base.w,h:anchor.h+box.h-base.h};
      },
    });
  }

  /* Ce qui définit une tenue : la fenêtre et le champ. Quand elle change sous
     la main, la tenue se refonde (`rebase`). */
  function holdSignature(vp,field){
    return `${vp?vp.width:0}x${vp?vp.height:0}|`+(field?`${field.cx},${field.cy},${field.ax},${field.ay},${field.scale},${field.ms}`:'still');
  }

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
  function resizeAxis(lo,size,dLo,dHi,minSize,maxSize){
    const movesLo=Number.isFinite(dLo),movesHi=Number.isFinite(dHi);
    let a=lo+(movesLo?dLo:0);
    let b=lo+size+(movesHi?dHi:0);
    const wanted=b-a,target=clamp(wanted,minSize,maxSize);
    if(target!==wanted){
      const deficit=target-wanted;
      const wLo=movesLo?Math.abs(dLo):0,wHi=movesHi?Math.abs(dHi):0,sum=wLo+wHi;
      if(!movesLo)b=a+target;
      else if(!movesHi)a=b-target;
      else if(sum>0){a-=deficit*(wLo/sum);b+=deficit*(wHi/sum)}
      else{a-=deficit/2;b+=deficit/2}
    }
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
    /* Pas de bord ici (22/09/2026) : ceux de l'écran et des commandes sont ceux
       de la tenue (`createHold`), les mêmes que pour la souris. */
    const x=resizeAxis(start.x,start.w,held.left,held.right,min.w,Math.min(max.w,areaW));
    const y=resizeAxis(start.y,start.h,held.top,held.bottom,min.h,Math.min(max.h,areaH));
    return {x:quantize(x.lo),y:quantize(y.lo),w:quantize(x.size),h:quantize(y.size)};
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
    return dragBox(start,axes.includes('x')?moved.dx:0,axes.includes('y')?moved.dy:0);
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
    if(intent.type==='move')return dragBox(box,intent.dx,intent.dy);
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
     attache rend `[objectId]`. */
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
    QUANTUM,clampBox,dragThreshold,pxToUnits,dragBox,resizeBox,resizable,keyIntent,applyKey,representationBox,sameBox,
    holdArea,sweepMove,sweepResize,createHold,holdSignature,freezeStyles,createRelay,thawAnimation,
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
