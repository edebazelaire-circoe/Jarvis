/* Bare Hands — banc d'essai « Tester » : plan, déroulé, score, comparaison
   (tâche `jarvis-bare-hands-adaptive-calibration-benchmark`, Slice 08,
   `docs/barehands-contracts.md` § 17, décisions 40 et 60 à 64).

   **Ce que ce module mesure : la qualité d'interaction de Bare Hands pour un
   profil donné — jamais l'habileté ni la précision de l'utilisateur.** Aucun
   champ, aucune clé, aucun libellé ici ne dit « skill » ou « précision de
   l'utilisateur ». Ce que la personne apporte (réaction, dépassement,
   tremblement) entre forcément dans des mesures faites en direct : chaque
   métrique est donc définie pour **isoler** le système autant que possible
   (tremblement mesuré une fois la main posée, temps de réaction hors des
   mesures de stabilité), et l'avant/après **du même utilisateur** est la
   seule lecture qui isole un réglage (décision 63).

   Quatre choses, séparées :

   1. **le plan** (`generatePlan`, `layoutPlan`) : une graine → une suite
      d'exercices du contrat et une disposition tirée par un générateur
      déterministe. Deux graines donnent deux dispositions **équivalentes mais
      pas identiques** ; la même graine rejoue exactement la même. Sous la
      fenêtre minimale de la classe, le banc **refuse** de commencer
      (`viewportCheck`) plutôt que de tirer une autre difficulté ;
   2. **le déroulé** (`createBenchmarkRunner`) : des images du **vrai** moteur
      entrent ; le vrai résolveur (`resolverHandOf` + `createTargetResolver`),
      le vrai constat de sélection, le vrai moteur de captures sur le vrai cadre
      d'entraînement et le vrai segmenteur d'épisodes les lisent. Rien de
      l'interaction n'est réécrit ici : le déroulé pose des cibles, écoute et
      compte, et range **par essai** les échantillons scalaires dont chaque
      métrique est la statistique ;
   3. **le score** (`scoreResult`), pur : métriques → dimensions → global,
      plafonné par la dimension la plus faible, `null` dès qu'une dimension
      manque ;
   4. **la comparaison** (`compareResults`), pure : un bootstrap **à graine**
      sur les échantillons des deux runs, un intervalle de confiance par
      métrique, par dimension et pour le global, et un verdict qui ne dit
      « amélioré » ou « régressé » que si l'intervalle exclut zéro au-delà
      d'une marge pratique.

   **Lecture seule, par structure.** Le déroulé ne reçoit que des vues gelées
   et des fabriques de canaux neufs ; toute dépendance hors de sa liste
   blanche est refusée (`barehands_benchmark_read_only`), et toute écriture
   dans une vue lève le même code. Seul `createSummaryStore` écrit — des
   **résumés** de banc (métriques et échantillons scalaires, jamais d'image),
   sur `/api/barehands/benchmarks`, et il n'est jamais donné au déroulé.

   Insertion : après les contrats (il les lit), avant le pointeur. Rien ne le
   lit au chargement ; la page (Slice 09) le branche. */
(function(root){
  'use strict';
  const BH=root.JarvisBarehandsContracts;
  if(!BH){
    console.error('[barehands] barehands.benchmark_not_installed '
      +JSON.stringify({error:'les contrats Bare Hands doivent être insérés avant ce module'}));
    return;
  }

  /* ------------------------------------------------------------------ 1
     Refus codés et petits outils. */
  class BareHandsBenchmarkError extends Error{
    constructor(code,message,reason){
      super(message);this.name='BareHandsBenchmarkError';this.code=code;
      /* La phrase à montrer à l'utilisateur, quand il y en a une (Slice 09). */
      this.reason=reason||null;
    }
  }
  const fail=(code,message,reason)=>{throw new BareHandsBenchmarkError(code,message,reason)};
  const READ_ONLY='barehands_benchmark_read_only';
  const own=(object,key)=>object!==null&&object!==undefined&&Object.prototype.hasOwnProperty.call(object,key);
  const finite=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
  const round=(value,digits)=>{
    if(value===null||value===undefined||!Number.isFinite(value))return null;
    const k=10**digits;return Math.round(value*k)/k;
  };
  /* Les coordonnées tirées sont arrondies au centième de pixel : un écart
     d'un ulp entre deux moteurs JS ne doit pas changer une disposition. */
  const r2=value=>Math.round(value*100)/100;
  const clamp=(v,lo,hi)=>Math.min(Math.max(v,lo),hi);
  const sorted=list=>list.filter(v=>Number.isFinite(v)).sort((a,b)=>a-b);
  const median=list=>{
    const xs=sorted(list);
    if(!xs.length)return null;
    const m=xs.length>>1;return xs.length%2?xs[m]:(xs[m-1]+xs[m])/2;
  };
  const mean=list=>{const xs=list.filter(v=>Number.isFinite(v));return xs.length?xs.reduce((a,b)=>a+b,0)/xs.length:null};
  const sum=list=>list.filter(v=>Number.isFinite(v)).reduce((a,b)=>a+b,0);

  /* ------------------------------------------------------------------ 2
     Hasard déterministe : mulberry32. Une graine 32 bits, aucune horloge,
     aucun `Math.random` — la même graine rend la même suite partout. */
  function createRandom(seed){
    let a=seed>>>0;
    const next=()=>{
      a=(a+0x6D2B79F5)>>>0;
      let t=a;
      t=Math.imul(t^(t>>>15),t|1);
      t^=t+Math.imul(t^(t>>>7),t|61);
      return ((t^(t>>>14))>>>0)/4294967296;
    };
    return {
      next,
      between:(lo,hi)=>lo+(hi-lo)*next(),
      int:n=>Math.floor(next()*n),
      shuffle(list){
        const out=list.slice();
        for(let i=out.length-1;i>0;i-=1){const j=Math.floor(next()*(i+1));const x=out[i];out[i]=out[j];out[j]=x}
        return out;
      },
    };
  }
  /* Une sous-graine par exercice : changer un exercice ne décale pas le
     tirage des autres. */
  const subSeed=(seed,index)=>(Math.imul((seed>>>0)^0x9E3779B9,index+1)^(index*0x85EBCA6B))>>>0;

  /* ------------------------------------------------------------------ 3
     La classe de plan `bh-bench-1` (décision 60) : la suite, les bandes de
     difficulté, la fenêtre minimale.

     **Règle d'équivalence** : pour chaque exercice, le multi-ensemble des
     classes de difficulté (taille, distance, écart, vitesse, décalage) est
     **le même pour toutes les graines** ; la graine ne tire que l'ordre de
     ces classes, les directions, les positions et un écart de
     ±`distanceJitter` sur les distances (jamais sur les tailles). Une
     disposition qui ne tient pas se retire d'une autre direction. Si aucun
     tirage ne tient, un repli existe (vers le centre) et il est **compté**
     (`layout.fallbacks`) : au-dessus de la fenêtre minimale, aucun repli
     n'a lieu (tenu par test sur 200 graines) ; en dessous, le banc refuse de
     commencer. */
  const PLAN_CLASS=BH.BENCHMARK_PLAN_CLASS;
  const SUITE=Object.freeze([
    Object.freeze({kind:'target_acquisition',trials:6}),
    Object.freeze({kind:'nearby_targets',trials:6}),
    Object.freeze({kind:'moving_target',trials:4}),
    /* Cinq et quatre (et non trois) : la latence de relâchement est une
       médiane d'épisodes, et trois épisodes la rendaient trop incertaine
       pour qu'un avant/après y voie 40 ms (reprise QA). */
    Object.freeze({kind:'drag_drop',trials:5}),
    Object.freeze({kind:'chained',trials:4}),
    /* En dernier, comme les négatifs de la calibration (décision 47). */
    Object.freeze({kind:'no_click_tracking',trials:4}),
  ]);
  /* **Les classes de fenêtre** viennent du contrat
     (`BENCHMARK_VIEWPORT_CLASSES`) : `vp100` (≥ 1280 × 700), `vp90`
     (≥ 1152 × 630), `vp80` (≥ 1024 × 560). Chaque minimum est la plus petite
     fenêtre où la plus grande distance de la classe (540 px × échelle + 8 %)
     tient depuis n'importe quel point du champ — le centre est le pire cas. La
     plus petite fenêtre acceptée est celle de `vp80`. */
  const VIEWPORT_CLASSES=BH.BENCHMARK_VIEWPORT_CLASSES;
  const SMALLEST=VIEWPORT_CLASSES[VIEWPORT_CLASSES.length-1];
  const MIN_VIEWPORT=Object.freeze({width:SMALLEST.minWidth,height:SMALLEST.minHeight});
  /* Plancher d'une cible : aucune étoile sous 12 px, quelle que soit la
     classe (à 0,8, la plus petite vaut 12,8 px : le plancher ne mord pas). */
  const MIN_TARGET_PX=12;
  /* Les bandes ci-dessous sont celles de l'échelle 1 (`vp100`) ; les autres
     classes les multiplient par `planScale` (`bandsFor`). */
  const BANDS=Object.freeze({
    fieldMarginPx:80,
    distanceJitter:.08,
    gapMs:500,
    exerciseGapMs:900,
    attemptsMax:3,
    target_acquisition:Object.freeze({
      sizesPx:Object.freeze([16,24,36]),distancesPx:Object.freeze([220,380,540]),
      /* Six couples (taille, distance) : chaque taille deux fois, chaque
         distance deux fois — un carré latin coupé. */
      schedule:Object.freeze([[0,1],[1,0],[2,2],[0,2],[1,1],[2,0]]),
      distractors:2,distractorSizePx:24,distractorClearPx:120,timeoutMs:4000}),
    nearby_targets:Object.freeze({sizePx:20,gapsPx:Object.freeze([8,14,22]),schedule:Object.freeze([0,1,2,0,1,2]),
      group:3,approachPx:300,timeoutMs:4000}),
    moving_target:Object.freeze({sizePx:28,speedsPxPerS:Object.freeze([120,200,280,200]),startDistancePx:260,
      timeoutMs:5000}),
    drag_drop:Object.freeze({offsetsPx:Object.freeze([300,420,520]),maxAngleDeg:25,frameUnits:Object.freeze({w:64,h:40}),
      timeoutMs:7000}),
    chained:Object.freeze({sizePx:24,offsetPx:360,clearPx:150,timeoutMs:10000}),
    /* Viser : trois points de 2,4 s chacun ; le tremblement ne se mesure
       qu'une fois le jeton posé (décision 61), ce qui laisse à une personne
       le temps de réagir, d'arriver et de se stabiliser. `graceMs` : au début
       d'un essai sans clic, rien ne compte (la main quitte la visée d'avant). */
    no_click_tracking:Object.freeze({modes:Object.freeze(['natural','natural','aim','aim']),naturalMs:7200,spots:3,
      spotMs:2400,graceMs:800,sizePx:24,spacingPx:140}),
    /* L'échelle du cadre d'entraînement (px par unité de scène) quand la page
       n'en donne pas : celle d'une fenêtre de 1280 px (scène § 5). */
    frameScale:4,
  });

  /* Le plan du contrat pour une graine : la suite de la classe courante. */
  function generatePlan(seed){
    if(!Number.isInteger(seed)||seed<0||seed>4294967295)
      fail('barehands_benchmark_seed_invalid','seed : entier non signé 32 bits attendu.');
    return BH.createBenchmarkPlan({seed,planClass:PLAN_CLASS,
      exercises:SUITE.map((e,i)=>({ref:`${BH.SESSION_REF.EXERCISE}-${i+1}`,kind:e.kind,trials:e.trials}))});
  }

  /* **Les bandes d'une classe de fenêtre** : longueurs et vitesses de
     l'échelle 1 multipliées par `planScale` — un indice de difficulté de Fitts
     log2(D/W + 1) est invariant par ce changement d'échelle —, tailles de
     cible jamais sous `MIN_TARGET_PX`. Les durées ne changent pas. */
  function bandsFor(planScale){
    const k=planScale,px=v=>r2(v*k),size=v=>Math.max(MIN_TARGET_PX,r2(v*k));
    const T=BANDS.target_acquisition,N=BANDS.nearby_targets,M=BANDS.moving_target,
      Dd=BANDS.drag_drop,Ch=BANDS.chained,Nc=BANDS.no_click_tracking;
    return Object.freeze({planScale:k,fieldMarginPx:px(BANDS.fieldMarginPx),
      target_acquisition:Object.freeze({...T,sizesPx:T.sizesPx.map(size),distancesPx:T.distancesPx.map(px),
        distractorSizePx:size(T.distractorSizePx),distractorClearPx:px(T.distractorClearPx)}),
      nearby_targets:Object.freeze({...N,sizePx:size(N.sizePx),gapsPx:N.gapsPx.map(px),approachPx:px(N.approachPx)}),
      moving_target:Object.freeze({...M,sizePx:size(M.sizePx),speedsPxPerS:M.speedsPxPerS.map(px),
        startDistancePx:px(M.startDistancePx)}),
      drag_drop:Object.freeze({...Dd,offsetsPx:Dd.offsetsPx.map(px)}),
      chained:Object.freeze({...Ch,sizePx:size(Ch.sizePx),offsetPx:px(Ch.offsetPx),clearPx:px(Ch.clearPx)}),
      no_click_tracking:Object.freeze({...Nc,sizePx:size(Nc.sizePx),spacingPx:px(Nc.spacingPx)})});
  }
  /* **La fenêtre peut-elle porter le banc ?** Rend `{ok, code, reason,
     viewportClass, planScale}` ; `reason` est la phrase que la Slice 09
     montre. */
  function viewportCheck(viewport){
    const w=Number(viewport&&viewport.width),h=Number(viewport&&viewport.height);
    const name=BH.benchmarkViewportClass({width:w,height:h});
    if(name){
      const c=VIEWPORT_CLASSES.find(x=>x.name===name);
      return Object.freeze({ok:true,code:null,reason:null,viewportClass:name,planScale:c.planScale});
    }
    return Object.freeze({ok:false,code:'barehands_benchmark_viewport_too_small',viewportClass:null,planScale:null,
      reason:`Agrandissez la fenêtre à au moins ${MIN_VIEWPORT.width} × ${MIN_VIEWPORT.height} pixels pour lancer le test`
        +` (elle fait ${Number.isFinite(w)?Math.round(w):'?'} × ${Number.isFinite(h)?Math.round(h):'?'}) : `
        +'plus petite, les exercices ne garderaient pas la même difficulté d’un test à l’autre.'});
  }
  /* Le champ où l'on pose : la fenêtre moins une marge (à l'échelle). */
  const fieldOf=(viewport,bands)=>{
    const w=Number(viewport.width),h=Number(viewport.height),m=bands.fieldMarginPx;
    return Object.freeze({x0:m,y0:m,x1:w-m,y1:h-m,width:w,height:h});
  };
  const inside=(field,x,y,inset)=>x>=field.x0+inset&&x<=field.x1-inset&&y>=field.y0+inset&&y<=field.y1-inset;
  const centerOf=field=>({x:(field.x0+field.x1)/2,y:(field.y0+field.y1)/2});
  const point=p=>Object.freeze({x:r2(p.x),y:r2(p.y)});
  const star=(id,p,size,expected)=>Object.freeze({id,x:r2(p.x),y:r2(p.y),size,expected:!!expected});

  /* Tirages permis avant un repli : assez pour qu'au-dessus de la fenêtre
     minimale aucun repli n’arrive (tenu par test sur 200 graines). */
  const REACH_TRIES=256,SPOT_TRIES=256;
  function layoutTools(rng,field,bands){
    let fallbacks=0;
    const where={reach:0,spot:0,drag:0};
    const jittered=value=>value*(1+rng.between(-BANDS.distanceJitter,BANDS.distanceJitter));
    const far=(p,list,gap)=>list.every(q=>Math.hypot(p.x-q.x,p.y-q.y)>=gap);
    return {
      bands,
      jittered,
      fallbacks:()=>fallbacks,
      where:()=>({...where}),
      /* Un point à `distance` de `from`, direction tirée, dans le champ. */
      reach(from,distance,inset){
        for(let k=0;k<REACH_TRIES;k+=1){
          const a=rng.between(0,Math.PI*2);
          const x=from.x+Math.cos(a)*distance,y=from.y+Math.sin(a)*distance;
          if(inside(field,x,y,inset))return {x,y};
        }
        /* Une fenêtre étroite de directions que le hasard a manquée : un
           balayage déterministe au demi-degré, avant tout repli. */
        const a0=rng.between(0,Math.PI*2);
        for(let k=0;k<720;k+=1){
          const a=a0+k*Math.PI/360;
          const x=from.x+Math.cos(a)*distance,y=from.y+Math.sin(a)*distance;
          if(inside(field,x,y,inset))return {x,y};
        }
        fallbacks+=1;where.reach+=1;
        const c=centerOf(field),a=Math.atan2(c.y-from.y,c.x-from.x);
        return {x:clamp(from.x+Math.cos(a)*distance,field.x0+inset,field.x1-inset),
          y:clamp(from.y+Math.sin(a)*distance,field.y0+inset,field.y1-inset)};
      },
      freeSpot(inset,avoid,gap){
        for(let k=0;k<SPOT_TRIES;k+=1){
          const p={x:rng.between(field.x0+inset,field.x1-inset),y:rng.between(field.y0+inset,field.y1-inset)};
          if(far(p,avoid,gap))return p;
        }
        fallbacks+=1;where.spot+=1;
        return null;
      },
      /* Un déplacement de cadre : départ et destination (centres, px), à
         `offset` px, presque horizontal (±`maxAngleDeg`), vers le côté où il
         tient. */
      drag(frame,offset){
        const B=bands.drag_drop;
        const inset={x:frame.w/2+8,y:frame.h/2+8};
        const fits=p=>p.x>=field.x0+inset.x&&p.x<=field.x1-inset.x&&p.y>=field.y0+inset.y&&p.y<=field.y1-inset.y;
        for(let k=0;k<SPOT_TRIES;k+=1){
          const start={x:rng.between(field.x0+inset.x,field.x1-inset.x),y:rng.between(field.y0+inset.y,field.y1-inset.y)};
          const angle=rng.between(-B.maxAngleDeg,B.maxAngleDeg)*Math.PI/180;
          const side=rng.next()<.5?-1:1;
          for(const s of [side,-side]){
            const destination={x:start.x+s*Math.cos(angle)*offset,y:start.y+Math.sin(angle)*offset};
            if(fits(destination))return Object.freeze({start:point(start),destination:point(destination),offsetPx:offset});
          }
        }
        fallbacks+=1;where.drag+=1;
        const c=centerOf(field);
        return Object.freeze({start:point({x:c.x-offset/2,y:c.y}),destination:point({x:c.x+offset/2,y:c.y}),offsetPx:offset});
      },
    };
  }

  const LAYOUT={
    target_acquisition(L,rng,field,trials,from){
      const B=L.bands.target_acquisition;
      const order=rng.shuffle(Array.from({length:trials},(_,i)=>B.schedule[i%B.schedule.length]));
      let at=from;
      return order.map(([si,di],i)=>{
        const size=B.sizesPx[si],distance=L.jittered(B.distancesPx[di]);
        const p=L.reach(at,distance,size/2+8);
        const stars=[star(`t${i}`,p,size,true)];
        for(let k=0;k<B.distractors;k+=1){
          const q=L.freeSpot(B.distractorSizePx,[p,at,...stars.slice(1)],B.distractorClearPx);
          if(q)stars.push(star(`t${i}d${k}`,q,B.distractorSizePx,false));
        }
        const trial=Object.freeze({from:point(at),sizeClass:si,distanceClass:di,
          distancePx:Math.hypot(stars[0].x-at.x,stars[0].y-at.y),stars:Object.freeze(stars)});
        at={x:stars[0].x,y:stars[0].y};return trial;
      });
    },
    nearby_targets(L,rng,field,trials,from){
      const B=L.bands.nearby_targets;
      const order=rng.shuffle(Array.from({length:trials},(_,i)=>B.schedule[i%B.schedule.length]));
      let at=from;
      return order.map((gi,i)=>{
        const gap=B.gapsPx[gi],pitch=B.sizePx+gap;
        const center=L.reach(at,L.jittered(B.approachPx),pitch*1.5+B.sizePx);
        const angle=rng.between(0,Math.PI*2);
        const row=rng.next()<.5;
        const offsets=row?[-1,0,1].map(k=>({x:k*pitch,y:0}))
          :[0,1,2].map(k=>({x:Math.cos(k*2*Math.PI/3)*pitch/Math.sqrt(3),y:Math.sin(k*2*Math.PI/3)*pitch/Math.sqrt(3)}));
        const expected=rng.int(B.group);
        const stars=offsets.map((o,k)=>{
          const x=center.x+o.x*Math.cos(angle)-o.y*Math.sin(angle),y=center.y+o.x*Math.sin(angle)+o.y*Math.cos(angle);
          return star(`n${i}s${k}`,{x,y},B.sizePx,k===expected);
        });
        const target=stars[expected];
        const trial=Object.freeze({from:point(at),gapClass:gi,gapPx:gap,arrangement:row?'row':'triangle',
          stars:Object.freeze(stars)});
        at={x:target.x,y:target.y};return trial;
      });
    },
    moving_target(L,rng,field,trials,from){
      const B=L.bands.moving_target;
      const order=rng.shuffle(Array.from({length:trials},(_,i)=>B.speedsPxPerS[i%B.speedsPxPerS.length]));
      let at=from;
      return order.map((speed,i)=>{
        const p=L.reach(at,L.jittered(B.startDistancePx),B.sizePx);
        const a=rng.between(0,Math.PI*2);
        const trial=Object.freeze({from:point(at),speedPxPerS:speed,start:point(p),
          velocity:point({x:Math.cos(a)*speed,y:Math.sin(a)*speed}),size:B.sizePx,id:`m${i}`});
        at=p;return trial;
      });
    },
    drag_drop(L,rng,field,trials,from,frame){
      const B=L.bands.drag_drop;
      const order=rng.shuffle(Array.from({length:trials},(_,i)=>B.offsetsPx[i%B.offsetsPx.length]));
      return order.map(offset=>L.drag(frame,L.jittered(offset)));
    },
    chained(L,rng,field,trials,from,frame){
      const B=L.bands.chained;
      return Array.from({length:trials},(_,i)=>{
        const drag=L.drag(frame,L.jittered(B.offsetPx));
        const avoid=[drag.start,drag.destination];
        const a=L.freeSpot(B.sizePx,avoid,B.clearPx)||centerOf(field);
        const b=L.freeSpot(B.sizePx,[...avoid,a],B.clearPx)||centerOf(field);
        return Object.freeze({first:star(`c${i}a`,a,B.sizePx,true),drag,last:star(`c${i}b`,b,B.sizePx,true)});
      });
    },
    no_click_tracking(L,rng,field,trials){
      const B=L.bands.no_click_tracking;
      const modes=rng.shuffle(Array.from({length:trials},(_,i)=>B.modes[i%B.modes.length]));
      return modes.map((mode,i)=>{
        const stars=[];
        for(let k=0;k<B.spots;k+=1){
          const p=L.freeSpot(B.sizePx*2,stars,B.spacingPx)||centerOf(field);
          stars.push(star(`q${i}s${k}`,p,B.sizePx,false));
        }
        return Object.freeze({mode,stars:Object.freeze(stars),durationMs:mode==='natural'?B.naturalMs:B.spots*B.spotMs});
      });
    },
  };

  /* La taille du cadre d'entraînement en px, à l'échelle donnée. */
  const frameSizePx=scale=>({w:BANDS.drag_drop.frameUnits.w*scale,h:BANDS.drag_drop.frameUnits.h*scale});
  const scaleOf=viewport=>Number(viewport&&viewport.scale)>0?Number(viewport.scale):BANDS.frameScale;

  /* **La disposition d'un plan**, pure et déterministe : même plan + même
     fenêtre → même disposition, octet pour octet. */
  function layoutPlan(rawPlan,viewport){
    const plan=BH.createBenchmarkPlan(rawPlan);
    if(plan.planClass!==PLAN_CLASS)fail('barehands_benchmark_plan_class_unknown',
      `Classe de plan ${plan.planClass} : ce banc tire la classe ${PLAN_CLASS}.`);
    const check=viewportCheck(viewport);
    if(!check.ok)fail(check.code,`Fenêtre trop petite pour le banc ${PLAN_CLASS}.`,check.reason);
    const bands=bandsFor(check.planScale);
    const field=fieldOf(viewport,bands);
    const scale=scaleOf(viewport);
    const frame=frameSizePx(scale);
    let from=centerOf(field),fallbacks=0;
    const fallbackKinds={};
    const exercises=plan.exercises.map((e,index)=>{
      const rng=createRandom(subSeed(plan.seed,index));
      const L=layoutTools(rng,field,bands);
      const trials=LAYOUT[e.kind](L,rng,field,e.trials,from,frame);
      fallbacks+=L.fallbacks();
      if(L.fallbacks())fallbackKinds[e.kind]={...L.where()};
      const last=trials[trials.length-1];
      if(last&&last.stars){const t=last.stars.find(s=>s.expected);if(t)from={x:t.x,y:t.y}}
      return Object.freeze({ref:e.ref,kind:e.kind,trials:Object.freeze(trials)});
    });
    return Object.freeze({seed:plan.seed,planClass:plan.planClass,viewportClass:check.viewportClass,
      planScale:check.planScale,bands,field,scale,fallbacks,
      fallbackKinds:Object.freeze(fallbackKinds),
      exercises:Object.freeze(exercises)});
  }

  /* Où est une cible mobile `ms` après l'ouverture de l'essai : un
     mouvement rectiligne, réfléchi sur les bords du champ. */
  const reflect=(p,lo,hi)=>{
    const span=hi-lo;if(!(span>0))return lo;
    let q=(p-lo)%(2*span);if(q<0)q+=2*span;
    return lo+(q<=span?q:2*span-q);
  };
  function movingAt(trial,field,ms){
    const s=Math.max(0,ms)/1000,inset=trial.size/2;
    return {x:reflect(trial.start.x+trial.velocity.x*s,field.x0+inset,field.x1-inset),
      y:reflect(trial.start.y+trial.velocity.y*s,field.y0+inset,field.y1-inset)};
  }

  /* ------------------------------------------------------------------ 4
     Vues en lecture seule. Une copie profonde de **données** (les fonctions
     ne sont pas recopiées : une vue ne transporte pas de porte), gelée,
     derrière un `Proxy` qui **refuse** toute écriture avec un code nommé. */
  const deny=()=>fail(READ_ONLY,'Le banc ne modifie jamais un réglage, un profil ni un essai : cette vue est en lecture seule.');
  function readOnly(value){
    if(value===null||typeof value!=='object')return value;
    const copy=Array.isArray(value)?value.map(readOnly):{};
    if(!Array.isArray(value))for(const key of Object.keys(value)){
      const v=value[key];
      if(typeof v==='function')continue;
      copy[key]=readOnly(v);
    }
    Object.freeze(copy);
    return new Proxy(copy,{set:deny,defineProperty:deny,deleteProperty:deny,setPrototypeOf:deny});
  }

  /* Empreinte d'un profil effectif : FNV-1a 32 bits deux fois (graines
     distinctes) sur le JSON canonique des valeurs que le moteur applique →
     16 caractères hexadécimaux. */
  function canonicalJson(value){
    if(value===null||typeof value!=='object')return JSON.stringify(value===undefined?null:value);
    if(Array.isArray(value))return `[${value.map(canonicalJson).join(',')}]`;
    return `{${Object.keys(value).filter(k=>value[k]!==undefined&&typeof value[k]!=='function').sort()
      .map(k=>`${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(',')}}`;
  }
  const fnv1a=(text,seed)=>{
    let h=seed>>>0;
    for(let i=0;i<text.length;i+=1){h^=text.charCodeAt(i);h=Math.imul(h,0x01000193)>>>0}
    return h.toString(16).padStart(8,'0');
  };
  const fingerprint=value=>{const text=canonicalJson(value);return fnv1a(text,0x811C9DC5)+fnv1a(text,0x3243F6A8)};

  /* **La vue de profil** que le déroulé reçoit, depuis la composition
     effective (`composeEffective`, décision 48). */
  const TARGET_KEYS=Object.freeze(['targetAssistPx','targetZonePx','targetZoneHoldPx','targetSwitchPx',
    'targetAmbiguityMax','targetHoldRatio']);
  function profileView(input){
    const i=input||{};
    const composition=i.composition;
    if(!composition||!composition.engine||!composition.interaction)
      fail('barehands_benchmark_invalid','profileView exige `composition` (composeEffective) : le banc mesure le profil que le moteur applique.');
    const source=BH.BENCHMARK_PROFILE_SOURCES.includes(i.source)?i.source
      :fail('barehands_benchmark_invalid',`profileView : source « ${String(i.source)} » inconnue.`);
    const trialRef=i.trialRef===undefined?null:i.trialRef;
    if((source===BH.BENCHMARK_PROFILE_SOURCE.TRIAL)!==(trialRef!==null))
      fail('barehands_benchmark_profile_invalid','trialRef est exigé pour un profil « trial », et seulement pour lui.');
    const targets={};
    for(const key of TARGET_KEYS){
      const v=own(composition.interaction,key)?composition.interaction[key]:composition.engine[key];
      if(Number.isFinite(v))targets[key]=v;
    }
    const assistance=Number(composition.interaction.assistance);
    return readOnly({source,trialRef,
      fingerprint:fingerprint({engine:composition.engine,hands:composition.hands,interaction:composition.interaction}),
      targets,assistance:Number.isFinite(assistance)?assistance:.5,
      lostGraceMs:Number.isFinite(composition.engine.lostGraceMs)?composition.engine.lostGraceMs:null});
  }

  /* ------------------------------------------------------------------ 5
     L'image que le déroulé lit : la couture de mesure du contrôleur
     (`deps.onMeasure`) et les contacts/événements de pincement de la même
     image (`controller.semantics().pinch`), recopiés clé par clé. */
  const HAND_NUMBERS=Object.freeze(['t','primaryRatio','secondaryRatio','primaryConfidence','secondaryConfidence',
    'primaryWorldRatio','secondaryWorldRatio','rawX','rawY','filteredX','filteredY','pointerX','pointerY',
    'palmX','palmY','quality','stillness','speedPxPerSec','pointingScore']);
  function engineFrame(measure,semantics){
    const m=measure||{};
    const pinch=(semantics&&semantics.pinch)||{};
    const t=finite(Number(m.now));
    return {
      t,
      hands:(Array.isArray(m.hands)?m.hands:[]).map(h=>{
        const out={handTrackId:h.handTrackId,handedness:String(h.handedness||'unknown'),
          pinchHandedness:String(h.pinchHandedness||'unknown'),
          pointing:h.pointing===true,pointerShown:h.pointerShown===true};
        for(const key of HAND_NUMBERS)out[key]=finite(h[key]);
        return out;
      }),
      contacts:(Array.isArray(pinch.contacts)?pinch.contacts:[]).map(c=>({handTrackId:c.handTrackId,
        channel:String(c.channel),state:String(c.state),intent:c.intent===undefined?null:c.intent,
        releasing:c.releasing===true,ratio:finite(c.ratio),confidence:finite(c.confidence)})),
      events:(Array.isArray(pinch.events)?pinch.events:[]).map(e=>({handTrackId:e.handTrackId,
        channel:String(e.channel),phase:String(e.phase),t:finite(e.t),x:finite(e.x),y:finite(e.y),
        intent:e.intent===undefined?null:e.intent})),
    };
  }

  /* ------------------------------------------------------------------ 6
     Les métriques : chacune est **une statistique de ses échantillons**
     (`METRIC_STAT`), et c'est la même fonction qui la calcule au déroulé et
     qui la recalcule dans le bootstrap de la comparaison. `sum` : un compte
     par essai (0/1 ou petit entier) ; `mean` : un taux ou une proportion par
     essai ; `median` : une durée, une distance, un rapport. */
  const METRIC_STAT=BH.BENCHMARK_METRIC_STAT;
  const statOf=(name,samples)=>BH.benchmarkStat(name,samples);
  const SAMPLES_MAX=BH.BENCHMARK_SAMPLES_MAX;
  /* Un échantillon de plus, s'il est fini, jusqu'à `SAMPLES_MAX` : au-delà,
     les premiers suffisent (un exercice ne produit normalement pas autant
     d'épisodes ; la borne tient le résultat dans le contrat). */
  const appendSample=(list,value)=>{
    if(typeof value==='number'&&Number.isFinite(value)&&list.length<SAMPLES_MAX)list.push(value);
    return list;
  };

  /* ------------------------------------------------------------------ 7
     Le déroulé. */
  const RUNNER_DEPS=Object.freeze(['contracts','core','target','geometry','calibration','profile','plan','viewport',
    'pinchChannel','log']);
  const PHASE=Object.freeze({IDLE:'idle',GAP:'gap',LIVE:'live',DONE:'done'});
  /* Retard de pointeur : sous 150 px/s, l'écart brut / filtré est du
     tremblement, pas du retard. */
  const LAG_MIN_SPEED_PX=150;
  /* **Jeton posé** (décision 61) : la vitesse du jeton lissé (moyenne
     centrée sur `SETTLE_WINDOW` images) reste sous `SETTLE_SPEED_PX` depuis
     `SETTLE_MS`. Seul ce qui suit compte pour le tremblement : l'arrivée,
     le dépassement et le temps de réaction de la personne n'y entrent pas. */
  const SETTLE_SPEED_PX=60,SETTLE_MS=300,SETTLE_WINDOW=5,JITTER_MIN_SAMPLES=5;
  const STAR_KIND='scene_object',STAR_REPRESENTATION='point';
  const starCandidate=(s,x,y)=>({objectId:`bench:${s.id}`,key:`o:bench:${s.id}`,kind:STAR_KIND,
    representation:STAR_REPRESENTATION,zoned:false,actionable:true,container:false,
    boundsPx:{x:x-s.size/2,y:y-s.size/2,w:s.size,h:s.size}});

  /* **Le tremblement d'un point visé**, pur : des positions du jeton affiché
     (`{t,x,y}`, une par image) au p95 du résidu **passe-haut** (écart à la
     moyenne centrée de `SETTLE_WINDOW` images), sur les seules images où le
     jeton est posé. `null` si le jeton ne s'est jamais posé assez longtemps. */
  /* **Un jeton qui ne se pose jamais** (reprise QA, round 3) n'est pas « non
     mesuré » : c'est le pire. Un point visé où le jeton était affiché au
     moins `JITTER_MIN_SAMPLES` images sans jamais se poser compte le p95 de
     son résidu passe-haut sur tout le point, et au moins
     `UNSETTLED_JITTER_PX` (6 px, l'ancre « inutilisable » du score) : un
     profil qui empire régresse au lieu de disparaître de la mesure. */
  const UNSETTLED_JITTER_PX=6;
  function spotJitter(points){
    const n=points.length,half=SETTLE_WINDOW>>1;
    if(n<SETTLE_WINDOW+JITTER_MIN_SAMPLES-1)return {value:null,settled:false};
    const smooth=[];
    for(let i=half;i<n-half;i+=1){
      let sx=0,sy=0;
      for(let k=-half;k<=half;k+=1){sx+=points[i+k].x;sy+=points[i+k].y}
      smooth.push({i,t:points[i].t,x:sx/SETTLE_WINDOW,y:sy/SETTLE_WINDOW});
    }
    const residuals=[],all=[];
    let calmSince=null;
    for(let k=1;k<smooth.length;k+=1){
      const a=smooth[k-1],b=smooth[k],dt=(b.t-a.t)/1000;
      const speed=dt>0?Math.hypot(b.x-a.x,b.y-a.y)/dt:Infinity;
      if(speed<SETTLE_SPEED_PX){if(calmSince===null)calmSince=a.t}else calmSince=null;
      const p=points[b.i],r=Math.hypot(p.x-b.x,p.y-b.y);
      all.push(r);
      if(calmSince!==null&&b.t-calmSince>=SETTLE_MS)residuals.push(r);
    }
    if(residuals.length>=JITTER_MIN_SAMPLES)return {value:BH.quantile(residuals,.95),settled:true};
    return {value:Math.max(UNSETTLED_JITTER_PX,BH.quantile(all,.95)),settled:false};
  }
  const settledJitter=points=>{const j=spotJitter(points);return j.settled?j.value:null};

  function createBenchmarkRunner(deps){
    const d=deps&&typeof deps==='object'?deps:fail('barehands_benchmark_invalid','createBenchmarkRunner exige ses dépendances.');
    /* **La porte de la lecture seule.** Une dépendance que la liste ne nomme
       pas — un `save`, un `trials`, un `settings` — est refusée. */
    for(const key of Object.keys(d))if(!RUNNER_DEPS.includes(key))
      fail(READ_ONLY,`createBenchmarkRunner refuse la dépendance « ${key} » : le banc ne reçoit que des vues en lecture seule (${RUNNER_DEPS.join(', ')}).`);
    const C=d.contracts,core=d.core,TARGET=d.target,G=d.geometry,K=d.calibration;
    if(!C||typeof C.createBenchmarkResult!=='function'||typeof C.pickRegion!=='function')
      fail('barehands_benchmark_invalid','createBenchmarkRunner exige `contracts` (JarvisBarehandsContracts).');
    for(const need of ['createTargetResolver','createSelectionObserver','createInteractionEngine','createPracticeFrame','resolverHandOf'])
      if(!core||typeof core[need]!=='function')
        fail('barehands_benchmark_invalid',`createBenchmarkRunner exige \`core.${need}\` : le banc lit le vrai moteur, pas une copie.`);
    if(!TARGET||typeof TARGET.near!=='function')fail('barehands_benchmark_invalid','createBenchmarkRunner exige `target.near`.');
    if(!G||typeof G.clampBox!=='function')fail('barehands_benchmark_invalid','createBenchmarkRunner exige `geometry` (JarvisSceneInteract).');
    if(!K||typeof K.measurePinchEpisodes!=='function'||typeof K.options!=='function')
      fail('barehands_benchmark_invalid','createBenchmarkRunner exige `calibration.measurePinchEpisodes` : une latence de banc a la définition de celle d’un épisode (décision 35).');
    if(typeof d.pinchChannel!=='function')
      fail('barehands_benchmark_invalid','createBenchmarkRunner exige `pinchChannel(channel, handedness)` : un canal neuf aux options du moteur, pour chronométrer les épisodes.');
    const profile=d.profile;
    if(!profile||!BH.BENCHMARK_PROFILE_SOURCES.includes(profile.source))
      fail('barehands_benchmark_invalid','createBenchmarkRunner exige `profile` (profileView).');
    const log=typeof d.log==='function'?d.log:()=>{};
    const say=(level,event,data)=>{try{log(level,event,data)}catch(_error){/* un journal qui lève ne coupe pas le banc */}};
    const vp=d.viewport||{};
    const view=readOnly({width:Number(vp.width),height:Number(vp.height),scale:scaleOf(vp),
      cx:Number.isFinite(Number(vp.cx))?Number(vp.cx):Number(vp.width)/2,
      cy:Number.isFinite(Number(vp.cy))?Number(vp.cy):Number(vp.height)/2});
    const plan=BH.createBenchmarkPlan(d.plan);
    const layout=layoutPlan(plan,view);     // refuse une fenêtre trop petite, avec sa phrase
    const field=layout.field;
    const K_OPTIONS=K.options();
    /* La tolérance de dépôt suit l'échelle de la classe, comme les distances. */
    const tolerancePx=r2(K_OPTIONS.dropTolerancePx*layout.planScale);
    const attemptsMax=BANDS.attemptsMax;
    const lostGraceMs=Number.isFinite(profile.lostGraceMs)?profile.lostGraceMs
      :(core.DEFAULTS&&core.DEFAULTS.lostGraceMs)||250;
    const assistance=profile.assistance;
    const resolver=core.createTargetResolver({pickRegion:C.pickRegion,...profile.targets});
    const observer=core.createSelectionObserver();

    let phase=PHASE.IDLE,phaseAt=0,exIndex=-1,trialIndex=-1,now=0;
    let trial=null;
    let practice=null,engine=null;
    let episodeRef=0;
    const accs=layout.exercises.map(e=>({ref:e.ref,kind:e.kind,trials:[],frames:[],
      samples:Object.fromEntries(BH.BENCHMARK_EXERCISE_METRICS[e.kind].map(m=>[m,[]])),lastLiveT:null}));
    const exercise=()=>layout.exercises[exIndex]||null;
    const acc=()=>accs[exIndex]||null;
    const push=(name,value)=>{
      const a=acc();
      if(a&&own(a.samples,name))appendSample(a.samples[name],value);
    };

    /* ---- le cadre d'entraînement (vrai `createPracticeFrame`, vrai moteur
       de captures, vraie géométrie de scène), un neuf par déplacement. */
    const unitBoxAt=center=>({x:(center.x-view.cx)/view.scale-BANDS.drag_drop.frameUnits.w/2,
      y:(center.y-view.cy)/view.scale-BANDS.drag_drop.frameUnits.h/2,
      w:BANDS.drag_drop.frameUnits.w,h:BANDS.drag_drop.frameUnits.h});
    const pxOfBox=box=>({x:view.cx+box.x*view.scale,y:view.cy+box.y*view.scale,w:box.w*view.scale,h:box.h*view.scale});
    function openPractice(drag){
      practice=core.createPracticeFrame({geometry:G,viewport:()=>({scale:view.scale,width:view.width,height:view.height,
        cx:view.cx,cy:view.cy}),box:unitBoxAt(drag.start),objectId:'bench:practice-frame'});
      engine=core.createInteractionEngine({contracts:C,geometry:G,world:practice.world,
        onRelease:(handTrackId,channel)=>resolver.release(handTrackId,channel)});
    }
    function closePractice(){
      if(practice&&typeof practice.close==='function'){try{practice.close()}catch(_error){}}
      practice=null;engine=null;
    }
    const frameCandidate=()=>({objectId:practice.objectId,key:`o:${practice.objectId}`,kind:STAR_KIND,
      representation:'window',zoned:true,actionable:true,container:false,boundsPx:pxOfBox(practice.box())});
    const dragError=drag=>{
      const px=pxOfBox(practice.box());
      const dx=px.x+px.w/2-drag.destination.x,dy=px.y+px.h/2-drag.destination.y;
      return {error:Math.hypot(dx,dy),inside:Math.abs(dx)<=tolerancePx&&Math.abs(dy)<=tolerancePx};
    };

    /* ---- ce qui est à l'écran pendant l'essai en cours. */
    function visibleStars(){
      if(!trial||phase!==PHASE.LIVE)return [];
      const e=exercise(),spec=e.trials[trialIndex];
      if(e.kind==='moving_target')return [star(spec.id,movingAt(spec,field,now-trial.openedAt),spec.size,true)];
      if(e.kind==='chained')return trial.step===0?[spec.first]:trial.step===2?[spec.last]:[];
      return spec.stars||[];
    }
    const dragOf=()=>{
      const e=exercise();if(!e||!trial||phase!==PHASE.LIVE)return null;
      const spec=e.trials[trialIndex];
      if(e.kind==='drag_drop')return spec;
      if(e.kind==='chained'&&trial.step===1)return spec.drag;
      return null;
    };
    function armObserver(){
      const keys={};
      for(const s of visibleStars())keys[`o:bench:${s.id}`]=s.expected===true;
      observer.arm(keys);
    }

    /* ---- ouverture et fermeture des essais. */
    function openTrial(t){
      const e=exercise(),spec=e.trials[trialIndex];
      trial={openedAt:t,attempts:0,missed:false,wrong:false,premature:false,success:null,
        entries:0,onExpected:false,step:0,stepDoneAt:null,stepAttempts:0,
        /* sans clic : compteurs de l'essai, bords montants remis à zéro */
        n:{exposureMs:0,downs:0,secondaryDowns:0,falseClicks:0,targets:0,pointers:0,shown:new Map(),targeted:new Map()},
        spotIndex:-1,spot:[],lag:[]};
      phase=PHASE.LIVE;phaseAt=t;
      acc().lastLiveT=null;
      resolver.reset();
      if(e.kind==='drag_drop')openPractice(spec);
      armObserver();
    }
    function closeTrial(t,outcome){
      const a=acc(),e=exercise(),spec=e.trials[trialIndex];
      const timeout=outcome==='timeout';
      const selection=e.kind==='target_acquisition'||e.kind==='nearby_targets'||e.kind==='moving_target';
      if(selection){
        /* L'acquisition ne se mesure que sur les sélections réussies ; une
           échéance sans sélection est un **délai dépassé** (`timeout_count`),
           pas un clic manqué — rien n'a été appuyé dans le vide. */
        if(trial.success!==null)push('acquisition_ms',trial.success-trial.openedAt);
        push('reacquisition_count',Math.max(0,trial.entries-1));
        if(own(a.samples,'missed_click_count'))push('missed_click_count',trial.missed?1:0);
        if(own(a.samples,'wrong_target_count'))push('wrong_target_count',trial.wrong?1:0);
        push('timeout_count',timeout?1:0);
        if(e.kind==='moving_target'&&trial.lag.length)push('pointer_lag_ms',median(trial.lag));
      }
      if(e.kind==='drag_drop'){
        const at=practice?dragError(spec):null;
        push('drag_success_rate',outcome==='success'?1:0);
        push('premature_drop_count',trial.premature?1:0);
        if(at)push('placement_error_px',at.error);
      }
      if(e.kind==='chained'){
        push('missed_click_count',trial.missed?1:0);
        push('wrong_target_count',trial.wrong?1:0);
        push('premature_drop_count',trial.premature?1:0);
        push('timeout_count',timeout?1:0);
      }
      if(e.kind==='no_click_tracking'){
        const n=trial.n;
        flushSpot();
        const minutes=n.exposureMs/60000;
        if(minutes>0){
          push('false_press_rate',n.downs/minutes);
          push('false_secondary_press_rate',n.secondaryDowns/minutes);
          if(spec.mode==='natural'){
            push('unintended_target_rate',n.targets/minutes);
            push('unintended_pointer_rate',n.pointers/minutes);
          }
        }
        push('false_click_count',n.falseClicks);
      }
      a.trials.push(outcome);
      closePractice();
      resolver.reset();
      observer.reset();
      say('info','barehands.benchmark_trial',{exercise:e.ref,kind:e.kind,trial:trialIndex+1,outcome,
        ms:Math.round(t-trial.openedAt)});
      trial=null;
      trialIndex+=1;
      if(trialIndex>=e.trials.length)closeExercise(t);
      else{phase=PHASE.GAP;phaseAt=t}
    }
    function closeExercise(t){
      const a=acc();
      /* Les latences : le **vrai** segmenteur d'épisodes (décision 43) sur les
         rapports vus pendant l'exercice, et un canal neuf aux options que le
         moteur applique (`pinchChannel`). Un échantillon par épisode. */
      const measured=K.measurePinchEpisodes(a.frames,BH.PINCH_CHANNEL.PRIMARY,{options:K_OPTIONS,
        detector:handedness=>d.pinchChannel(BH.PINCH_CHANNEL.PRIMARY,handedness),lostGraceMs,
        nextRef:()=>`${BH.SESSION_REF.EPISODE}-${++episodeRef}`});
      for(const ep of measured.episodes){
        push('press_latency_ms',finite(ep.pressLatencyMs));
        push('release_latency_ms',finite(ep.releaseLatencyMs));
      }
      a.episodes=measured.episodes.length;
      a.frames=[];   // rien de brut ne survit à l'exercice
      say('info','barehands.benchmark_exercise',{exercise:a.ref,kind:a.kind,trials:a.trials.length,episodes:a.episodes});
      exIndex+=1;trialIndex=0;
      if(exIndex>=layout.exercises.length){
        phase=PHASE.DONE;phaseAt=t;
        say('info','barehands.benchmark_done',{exercises:layout.exercises.length});
      }else{phase=PHASE.GAP;phaseAt=t-BANDS.gapMs+BANDS.exerciseGapMs}
    }
    /* L'échéance d'un essai ; un essai sans clic dure ce que dit la
       disposition et se solde toujours « réussi » à son terme. */
    const timeoutOf=kind=>kind==='no_click_tracking'?Infinity:BANDS[kind].timeoutMs;

    /* ---- le jugement d'une image. */
    function judgeSelection(facts,records){
      const e=exercise();
      const expectedKeys=new Set(visibleStars().filter(s=>s.expected).map(s=>`o:bench:${s.id}`));
      /* Reprises : l'aperçu est venu sur la cible attendue, en est reparti,
         et y revient — avant la sélection. */
      const on=records.some(r=>r.channel===BH.PINCH_CHANNEL.PRIMARY&&r.key!==null&&expectedKeys.has(r.key));
      if(on&&!trial.onExpected)trial.entries+=1;
      trial.onExpected=on;
      for(const fact of facts){
        if(fact.type!=='press')continue;
        if(e.kind==='nearby_targets'&&fact.ambiguity!==null)push('target_ambiguity',fact.ambiguity);
        trial.attempts+=1;
        if(fact.outcome==='expected'){trial.success=fact.t;return 'success'}
        if(fact.outcome==='other')trial.wrong=true;else trial.missed=true;
        if(trial.attempts>=attemptsMax)return 'failed';
      }
      return null;
    }
    function judgeDrag(drag,entries){
      for(const entry of entries){
        if(entry.type!=='commit'&&entry.type!=='cancel')continue;
        if(entry.type==='commit'&&!entry.moved)continue;   // un clic sur le cadre n'est pas un dépôt
        trial.stepAttempts+=1;
        if(entry.type==='commit'&&dragError(drag).inside)return 'success';
        trial.premature=true;
        if(trial.stepAttempts>=attemptsMax)return 'failed';
      }
      return null;
    }

    /* ---- la résolution de cible d'une image : la règle de la page
       (`resolverHandOf`), le vrai résolveur, sur ce qui est à l'écran. */
    function resolve(f){
      const stars=visibleStars().map(s=>starCandidate(s,s.x,s.y));
      const list=practice?[...stars,frameCandidate()]:stars;
      const byId=new Map(f.hands.map(h=>[String(h.handTrackId),{id:h.handTrackId,x:h.pointerX,y:h.pointerY,
        palmX:h.palmX,palmY:h.palmY,pointing:h.pointing}]));
      const records=[],targets=[];
      for(const contact of f.contacts){
        const token=byId.get(String(contact.handTrackId));
        if(!token||token.x===null||token.y===null)continue;
        const {intent,hover,hand}=core.resolverHandOf(contact,token,assistance);
        const at={x:token.x,y:token.y};
        const candidates=intent||hover?TARGET.near(list,at,resolver.searchRadius(assistance)):[];
        const decided=resolver.update({now:f.t,candidates,hands:[hand]});
        records.push(...resolver.decisions());
        for(const target of decided)if(!target.hover)targets.push(target);
      }
      return {records,targets,tokens:[...byId.values()]};
    }

    /* ---- les exemples négatifs : ce que le moteur a fait sans qu'on le lui
       demande. Rien ne compte pendant `graceMs` après l'ouverture (la main
       quitte la visée d'avant, l'intention de pointer a le temps de finir) ;
       les bords montants partent de zéro à chaque essai — jamais d'une valeur
       laissée par l'essai précédent. Un curseur **encore** affiché à la fin
       de la grâce compte : il a eu le temps de disparaître. */
    function flushSpot(){
      if(!trial||!trial.spot.length)return;
      push('pointer_jitter_px',spotJitter(trial.spot).value);
      trial.spot=[];
    }
    function judgeNoClick(f,records,dt){
      const e=exercise(),spec=e.trials[trialIndex],n=trial.n;
      const natural=spec.mode==='natural';
      const since=f.t-trial.openedAt;
      if(!natural){
        /* Viser : un point à la fois ; le jeton affiché de la première main
           visible, pour le tremblement une fois posé. */
        const B=BANDS.no_click_tracking;
        const spot=Math.min(B.spots-1,Math.floor(since/B.spotMs));
        if(spot!==trial.spotIndex){flushSpot();trial.spotIndex=spot}
        const h=f.hands.find(x=>x.pointerShown&&x.pointerX!==null&&x.pointerY!==null);
        if(h)trial.spot.push({t:f.t,x:h.pointerX,y:h.pointerY});
      }
      const facts=observer.drain();
      if(since<BANDS.no_click_tracking.graceMs)return;
      n.exposureMs+=dt;
      for(const ev of f.events){
        if(ev.phase!==BH.PINCH_PHASE.DOWN)continue;
        if(ev.channel===BH.PINCH_CHANNEL.PRIMARY)n.downs+=1;
        else if(ev.channel===BH.PINCH_CHANNEL.SECONDARY)n.secondaryDowns+=1;
      }
      for(const fact of facts)if(fact.type==='press'&&fact.outcome!=='none')n.falseClicks+=1;
      if(natural){
        for(const h of f.hands){
          const id=String(h.handTrackId);
          if(h.pointerShown&&n.shown.get(id)!==true)n.pointers+=1;
          n.shown.set(id,h.pointerShown);
        }
        for(const r of records){
          const lane=`${String(r.handTrackId)}|${r.channel}`;
          const has=r.key!==null;
          if(has&&n.targeted.get(lane)!==true)n.targets+=1;
          n.targeted.set(lane,has);
        }
      }
    }

    function frame(input){
      const f=input&&typeof input==='object'?input:{};
      const t=finite(Number(f.t));
      if(t===null)fail('barehands_benchmark_invalid','Image de banc sans horodatage.');
      if(phase===PHASE.IDLE||phase===PHASE.DONE)return state();
      const hands=Array.isArray(f.hands)?f.hands:[];
      const clean={t,hands,contacts:Array.isArray(f.contacts)?f.contacts:[],events:Array.isArray(f.events)?f.events:[]};
      now=t;
      if(phase===PHASE.GAP&&t-phaseAt>=BANDS.gapMs)openTrial(t);
      const a=acc(),e=exercise();
      /* Les images de l'exercice, pour ses épisodes (trous compris : un
         relâchement tombe souvent entre deux essais). Effacées à sa fin. */
      for(const h of hands)a.frames.push({...h,t});
      const {records,targets,tokens}=resolve(clean);
      if(phase!==PHASE.LIVE){observer.drain();return state()}
      const dt=a.lastLiveT===null?0:Math.min(200,Math.max(0,t-a.lastLiveT));
      a.lastLiveT=t;
      observer.update(records,t);
      let verdict=null;
      if(e.kind==='no_click_tracking'){
        judgeNoClick(clean,records,dt);
        if(t-trial.openedAt>=e.trials[trialIndex].durationMs)verdict='success';
      }else{
        if(e.kind==='moving_target')
          for(const h of hands){
            const speed=h.speedPxPerSec;
            if(speed!==null&&speed>=LAG_MIN_SPEED_PX&&h.rawX!==null&&h.filteredX!==null)
              trial.lag.push(Math.hypot(h.rawX-h.filteredX,h.rawY-h.filteredY)/speed*1000);
          }
        const drag=dragOf();
        if(drag&&engine){
          engine.update({now:t,tokens,targets:targets.filter(x=>x.objectId===practice.objectId),
            contacts:clean.contacts,events:clean.events});
          verdict=judgeDrag(drag,practice.drain());
          observer.drain();
        }else{
          verdict=judgeSelection(observer.drain(),records);
        }
        if(e.kind==='chained'){
          /* Transition : de la fin d'une étape au premier appui de la
             suivante (événement `down` du vrai moteur de pincement). */
          if(trial.stepDoneAt!==null)
            for(const ev of clean.events)
              if(ev.channel===BH.PINCH_CHANNEL.PRIMARY&&ev.phase===BH.PINCH_PHASE.DOWN&&trial.stepDoneAt!==null){
                push('transition_ms',t-trial.stepDoneAt);trial.stepDoneAt=null;
              }
          if(verdict==='success'&&trial.step<2){
            trial.step+=1;trial.stepDoneAt=t;trial.stepAttempts=0;trial.attempts=0;trial.onExpected=false;
            closePractice();resolver.reset();
            if(trial.step===1)openPractice(e.trials[trialIndex].drag);
            armObserver();
            verdict=null;
          }
        }
      }
      if(verdict===null&&t-trial.openedAt>=timeoutOf(e.kind))verdict='timeout';
      if(verdict!==null)closeTrial(t,verdict);
      return state();
    }

    function state(){
      const e=exercise();
      const upcoming=phase===PHASE.GAP&&e?e.trials[trialIndex]:null;
      const drag=dragOf();
      const spec=e&&phase===PHASE.LIVE?e.trials[trialIndex]:null;
      let aimSpot=null;
      if(e&&e.kind==='no_click_tracking'&&spec&&spec.mode==='aim'&&trial){
        const k=Math.min(spec.stars.length-1,Math.floor((now-trial.openedAt)/BANDS.no_click_tracking.spotMs));
        aimSpot={x:spec.stars[k].x,y:spec.stars[k].y};
      }
      return Object.freeze({phase,t:now,
        exerciseRef:e?e.ref:null,kind:e?e.kind:null,trial:e?trialIndex+1:0,trials:e?e.trials.length:0,
        mode:spec&&spec.mode?spec.mode:(upcoming&&upcoming.mode?upcoming.mode:null),
        step:e&&e.kind==='chained'&&trial?trial.step:null,
        stars:Object.freeze(visibleStars().map(s=>Object.freeze({...s}))),
        frame:drag&&practice?Object.freeze(pxOfBox(practice.box())):null,
        destination:drag?Object.freeze({x:drag.destination.x,y:drag.destination.y,...frameSizePx(view.scale)}):null,
        aimSpot:aimSpot?Object.freeze(aimSpot):null,
        exercises:layout.exercises.length,exerciseIndex:exIndex});
    }

    return Object.freeze({
      layout:()=>layout,
      /* La tolérance de dépôt de la classe (px par axe) : la Slice 09 dessine
         la destination avec elle. */
      dropTolerancePx:()=>tolerancePx,
      start(at){
        const t=finite(Number(at));
        if(t===null)fail('barehands_benchmark_invalid','start exige un horodatage.');
        if(phase!==PHASE.IDLE)fail('barehands_benchmark_already_started','Ce banc a déjà commencé : un run, un déroulé.');
        now=t;exIndex=0;trialIndex=0;phase=PHASE.GAP;phaseAt=t;
        say('info','barehands.benchmark_started',{seed:plan.seed,planClass:plan.planClass,profileSource:profile.source,
          exercises:layout.exercises.length,viewport:BH.benchmarkViewportClass(view)});
        return state();
      },
      frame,
      state,
      done:()=>phase===PHASE.DONE,
      /* Combien d'images brutes le déroulé garde en ce moment : celles de
         l'exercice en cours, pour ses épisodes ; zéro une fois le banc fini. */
      retained:()=>accs.reduce((n,a)=>n+a.frames.length,0),
      /* Le résultat du contrat : métriques (statistiques de leurs
         échantillons), échantillons, identité du profil, graine, classe,
         fenêtre, instant du run. */
      result(meta){
        if(phase!==PHASE.DONE)fail('barehands_benchmark_incomplete','Le banc n’est pas allé au bout : aucun résultat partiel ne se compare.');
        const m=meta||{};
        return C.createBenchmarkResult({schemaVersion:C.SESSION_SCHEMA_VERSION,kind:'benchmark_result',
          ref:m.ref||`${BH.SESSION_REF.BENCHMARK}-1`,seed:plan.seed,planClass:plan.planClass,runAt:m.runAt,
          profileSource:profile.source,trialRef:profile.trialRef,profileFingerprint:profile.fingerprint,
          viewport:{width:view.width,height:view.height,scale:view.scale},
          exercises:accs.map((a,i)=>{
            /* Les échantillons, arrondis au millième, **puis** la métrique
               calculée sur eux : relus du disque, ils rendent la même valeur. */
            const samples=Object.fromEntries(Object.keys(a.samples).map(name=>[name,a.samples[name].map(v=>round(v,3))]));
            return {ref:a.ref,kind:a.kind,trials:layout.exercises[i].trials.length,
              metrics:Object.fromEntries(Object.keys(samples).map(name=>[name,statOf(name,samples[name])])),samples};
          })});
      },
    });
  }

  /* ------------------------------------------------------------------ 8
     Le score (décision 62). Pur. Rampe linéaire par métrique entre deux
     ancres, dans son unité ; `per: 'trial'` divise d'abord un compte par le
     nombre d'essais. Les ancres sont calées sur l'**utilisateur de
     référence** (réaliste, `tests/fixtures/barehands_benchmark_calibrate.cjs`)
     et justifiées au contrat lisible. */
  const METRIC_SCORING=Object.freeze({
    acquisition_ms:Object.freeze({good:1400,bad:3500}),
    reacquisition_count:Object.freeze({good:0,bad:2,per:'trial'}),
    timeout_count:Object.freeze({good:0,bad:.5,per:'trial'}),
    wrong_target_count:Object.freeze({good:0,bad:.5,per:'trial'}),
    missed_click_count:Object.freeze({good:0,bad:.5,per:'trial'}),
    target_ambiguity:Object.freeze({good:.5,bad:.95}),
    false_click_count:Object.freeze({good:0,bad:1,per:'trial'}),
    false_press_rate:Object.freeze({good:0,bad:10}),
    false_secondary_press_rate:Object.freeze({good:0,bad:10}),
    unintended_target_rate:Object.freeze({good:0,bad:10}),
    unintended_pointer_rate:Object.freeze({good:0,bad:10}),
    release_latency_ms:Object.freeze({good:80,bad:350}),
    premature_drop_count:Object.freeze({good:0,bad:.5,per:'trial'}),
    drag_success_rate:Object.freeze({good:1,bad:.4}),
    placement_error_px:Object.freeze({good:16,bad:72}),
    pointer_jitter_px:Object.freeze({good:1,bad:6}),
    pointer_lag_ms:Object.freeze({good:40,bad:160}),
    press_latency_ms:Object.freeze({good:60,bad:260}),
    transition_ms:Object.freeze({good:1400,bad:3600}),
  });
  /* **Moyenne géométrique décalée** : exp(moyenne(ln(s + 1))) − 1 ; 0 → 0,
     100 → 100, un zéro pèse sans annuler le reste. */
  const SCORE_SHIFT=1;
  /* **Plafond par la plus faible** : le global ne dépasse jamais la
     dimension la plus faible de plus de `WEAK_CAP_MARGIN` points. */
  const WEAK_CAP_MARGIN=25;

  function metricScore(name,value,trials){
    const spec=METRIC_SCORING[name];
    if(!spec||value===null||value===undefined||!Number.isFinite(value))return null;
    const v=spec.per==='trial'?value/Math.max(1,trials):value;
    const s=(spec.bad-v)/(spec.bad-spec.good);
    return round(100*clamp(s,0,1),1);
  }
  const geometricMean=scores=>{
    if(!scores.length)return null;
    const logs=scores.map(s=>Math.log(Math.max(0,s)+SCORE_SHIFT));
    return Math.exp(logs.reduce((a,b)=>a+b,0)/logs.length)-SCORE_SHIFT;
  };
  /* Le calcul, sans validation : `exercises` = `[{ref,kind,trials,metrics}]`.
     Le bootstrap l'appelle mille fois ; `scoreResult` l'enveloppe. */
  function scoreExercises(exercises){
    const dimensions={};
    for(const name of BH.BENCHMARK_DIMENSIONS){
      const metrics=[];
      for(const e of exercises)for(const metric of BH.BENCHMARK_DIMENSION_METRICS[name]){
        if(!own(e.metrics,metric))continue;
        const value=e.metrics[metric];
        metrics.push({exercise:e.ref,kind:e.kind,metric,value,trials:e.trials,score:metricScore(metric,value,e.trials)});
      }
      const scored=metrics.map(m=>m.score).filter(s=>s!==null);
      dimensions[name]={score:scored.length?round(geometricMean(scored),1):null,metrics};
    }
    const measured=BH.BENCHMARK_DIMENSIONS.filter(n=>dimensions[n].score!==null);
    const unmeasured=BH.BENCHMARK_DIMENSIONS.filter(n=>dimensions[n].score===null);
    let global=null,weakest=null,capped=false;
    if(measured.length)weakest=measured.reduce((w,n)=>dimensions[n].score<dimensions[w].score?n:w,measured[0]);
    /* **Toutes les dimensions ou pas de global** (reprise QA) : une dimension
       non mesurée n'est ni bonne ni mauvaise, et l'écarter laisserait le
       plafond de la plus faible s'appliquer à ce qui reste. */
    if(!unmeasured.length){
      const avg=geometricMean(measured.map(n=>dimensions[n].score));
      const cap=dimensions[weakest].score+WEAK_CAP_MARGIN;
      capped=cap<avg;
      global=round(Math.min(avg,cap),1);
    }
    return {dimensions,global:{score:global,weakest,capped,measured:measured.length,unmeasured}};
  }
  /* **Le score d'un résultat**, avec ses métriques brutes. */
  function scoreResult(raw){
    const result=BH.createBenchmarkResult(raw);
    const s=scoreExercises(result.exercises);
    const dimensions={};
    for(const name of BH.BENCHMARK_DIMENSIONS)
      dimensions[name]=Object.freeze({score:s.dimensions[name].score,
        metrics:Object.freeze(s.dimensions[name].metrics.map(m=>Object.freeze({...m,unit:BH.CALIBRATION_METRIC[m.metric].unit})))});
    return Object.freeze({kind:'benchmark_scores',subject:'interaction_quality',planClass:result.planClass,
      seed:result.seed,runAt:result.runAt,profileSource:result.profileSource,trialRef:result.trialRef,
      profileFingerprint:result.profileFingerprint,viewport:result.viewport,
      dimensions:Object.freeze(dimensions),
      global:Object.freeze({...s.global,unmeasured:Object.freeze(s.global.unmeasured)}),
      result});
  }

  /* ------------------------------------------------------------------ 9
     Avant / après (décision 63) : un rééchantillonnage à graine.

     Pour chaque réplique, chaque métrique de chaque exercice de chaque run
     est retirée selon son modèle (`METRIC_MODEL` : bootstrap d'une médiane,
     loi d'un compte) ; les scores suivent. Les deux runs sont tirés
     indépendamment (deux échantillons : les essais ne s'apparient pas, les
     dispositions diffèrent). La graine est l'empreinte des deux résultats :
     même paire → mêmes intervalles, mêmes verdicts.

     **Le verdict d'une dimension vient de ses métriques** : pour chaque nom
     de métrique de la dimension, l'écart de score moyen sur ses exercices
     (« après − avant »), son intervalle au niveau 1 − 5 %/m (Bonferroni sur
     les m métriques de la dimension) ; `improved` si la borne basse atteint
     `PRACTICAL_MARGIN`, `regressed` si la borne haute descend à
     −`PRACTICAL_MARGIN`. La dimension est `improved` (ou `regressed`) si au
     moins une métrique l'est et aucune ne dit l'inverse ; les deux à la fois
     → `inconclusive`. Sinon `unchanged` si l'écart de la dimension reste
     sous `EQUIVALENCE_BAND`, `inconclusive` au-delà (un grand mouvement sans
     preuve). Le global a son propre intervalle (95 %). */
  const BOOTSTRAP_REPLICATES=1000;
  const PRACTICAL_MARGIN=2;
  const EQUIVALENCE_BAND=10;
  const CI_LEVEL=.95;

  /* **Le modèle de rééchantillonnage d'une métrique.** Une médiane de
     durées ou de distances se rééchantillonne par bootstrap (tirage avec
     remise). Un compte d'événements rares ne le peut pas : quatre essais sans
     un seul faux appui rendraient un taux « exactement nul » à chaque tirage,
     et un seul faux appui de l'autre côté passerait pour une preuve. Les
     comptes suivent donc leur loi, avec l'a priori de Jeffreys (½) qui donne
     une incertitude à zéro événement :

       binomial  un drapeau par essai (raté, mauvaise cible, lâcher trop tôt,
                 délai) : p ~ Bêta(k + ½, n − k + ½), compte = n·p ;
       beta      une proportion par essai (dépôt réussi) : p ~ Bêta(…) ;
       poisson   un compte par essai (reprises, faux clics) :
                 λ ~ Gamma(K + ½) ;
       rate      un taux par minute (faux appuis, cibles, curseurs) : les
                 comptes se relisent par l'exposition nominale de la classe
                 (`NO_CLICK_EXPOSURE_MS`), λ ~ Gamma(K + ½) / exposition. */
  const NO_CLICK_EXPOSURE_MS=BANDS.no_click_tracking.naturalMs-BANDS.no_click_tracking.graceMs;
  const modelOf=name=>{
    const how=METRIC_STAT[name],spec=BH.CALIBRATION_METRIC[name];
    if(how==='median')return 'bootstrap';
    if(how==='mean')return spec.unit==='per_min'?'rate':'beta';
    return spec.perTrial?'binomial':'poisson';
  };
  const METRIC_MODEL=Object.freeze(Object.fromEntries(Object.keys(METRIC_STAT).map(n=>[n,modelOf(n)])));
  function normal(rng){
    const u=Math.max(1e-12,rng.next()),v=rng.next();
    return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);
  }
  /* Gamma(shape, 1) : Marsaglia–Tsang ; sous 1, par le relèvement usuel. */
  function gamma(shape,rng){
    if(shape<1)return gamma(shape+1,rng)*Math.pow(Math.max(1e-12,rng.next()),1/shape);
    const dd=shape-1/3,c=1/Math.sqrt(9*dd);
    for(;;){
      let x,v;
      do{x=normal(rng);v=1+c*x}while(v<=0);
      v=v*v*v;
      const u=rng.next();
      if(u<1-.0331*x*x*x*x||Math.log(Math.max(1e-300,u))<.5*x*x+dd*(1-v+Math.log(v)))return dd*v;
    }
  }
  const beta=(a,b,rng)=>{const x=gamma(a,rng),y=gamma(b,rng);return x/(x+y)};
  /* **Bootstrap lissé, avec un plancher de dispersion** (reprise QA, round
     3). Le bootstrap brut d'une médiane de 3 à 5 valeurs ne connaît que ces
     valeurs : deux runs identiques y paraissaient différents. Chaque tirage
     reçoit un bruit gaussien de largeur h = 1,06·σ·n^(−1/5) (règle de
     Silverman), où σ est l'écart type des échantillons, jamais sous
     `SPREAD_FLOOR` : 10 % de la médiane, plus un plancher absolu par unité
     (`SPREAD_ABS`). Une métrique n'est jamais connue plus finement que cela
     sur si peu de valeurs. */
  const SPREAD_FLOOR=.1;
  const SPREAD_ABS=Object.freeze({ms:5,px:.5,ratio:.02,unit:.02,per_min:.5,count:.5});
  function spreadOf(name,list){
    const n=list.length,m=mean(list);
    let v=0;for(const x of list)v+=(x-m)*(x-m);
    const sd=n>1?Math.sqrt(v/(n-1)):0;
    const floor=SPREAD_FLOOR*Math.abs(median(list))+SPREAD_ABS[BH.CALIBRATION_METRIC[name].unit];
    return Math.max(sd,floor);
  }
  function redraw(name,list,rng){
    const n=list.length,model=METRIC_MODEL[name];
    if(model==='bootstrap'){
      const h=1.06*spreadOf(name,list)*Math.pow(n,-.2);
      const spec=BH.CALIBRATION_METRIC[name];
      const draw=new Array(n);
      for(let i=0;i<n;i+=1){
        const x=list[Math.floor(rng.next()*n)]+h*normal(rng);
        draw[i]=clamp(x,spec.min,spec.max===null?Infinity:spec.max);
      }
      return statOf(name,draw);
    }
    if(model==='binomial'||model==='beta'){
      const k=clamp(sum(list),0,n);
      const p=beta(k+.5,n-k+.5,rng);
      return model==='beta'?p:n*p;
    }
    if(model==='poisson')return gamma(sum(list)+.5,rng);
    const minutes=NO_CLICK_EXPOSURE_MS/60000;
    const events=list.reduce((acc,rate)=>acc+Math.round(rate*minutes),0);
    return gamma(events+.5,rng)/(n*minutes);
  }
  function resampleExercises(exercises,rng){
    return exercises.map(e=>{
      const metrics={};
      for(const name of Object.keys(e.metrics)){
        const list=e.samples&&own(e.samples,name)?e.samples[name]:null;
        metrics[name]=!list||!list.length?e.metrics[name]:redraw(name,list,rng);
      }
      return {ref:e.ref,kind:e.kind,trials:e.trials,metrics};
    });
  }
  const interval=(deltas,level)=>{
    const xs=sorted(deltas);
    if(!xs.length)return null;
    const lo=(1-level)/2;
    return [round(BH.quantile(xs,lo),1),round(BH.quantile(xs,1-lo),1)];
  };
  /* Le score moyen d'un nom de métrique sur les exercices de la dimension. */
  /* Au-dessous de `MIN_CI_SAMPLES` échantillons d'un côté ou de l'autre, une
     occurrence de métrique n'entre dans aucun intervalle : sur une ou deux
     valeurs, un rééchantillonnage « prouve » n'importe quoi (mesuré à la
     reprise : n = 1 → l'intervalle excluait zéro sur 60 paires identiques
     sur 60). Trois est le plus petit n où une médiane a une dispersion
     (voir le mode `coverage` du script de calibration). */
  const MIN_CI_SAMPLES=3;
  const metricMeans=(dimension,keys)=>{
    const by={};
    for(const m of dimension.metrics)if(m.score!==null&&(!keys||keys.has(`${m.exercise}.${m.metric}`)))
      (by[m.metric]||(by[m.metric]=[])).push(m.score);
    return Object.fromEntries(Object.entries(by).map(([k,v])=>[k,mean(v)]));
  };
  const signedVerdict=(ci,delta)=>{
    if(ci===null||delta===null)return 'unmeasured';
    if(ci[0]>=PRACTICAL_MARGIN)return 'improved';
    if(ci[1]<=-PRACTICAL_MARGIN)return 'regressed';
    return Math.abs(delta)<EQUIVALENCE_BAND?'unchanged':'inconclusive';
  };
  const combined=(verdicts,delta)=>{
    const up=verdicts.includes('improved'),down=verdicts.includes('regressed');
    if(up&&down)return 'inconclusive';
    if(up)return 'improved';
    if(down)return 'regressed';
    if(delta===null)return 'unmeasured';
    return Math.abs(delta)<EQUIVALENCE_BAND?'unchanged':'inconclusive';
  };

  function compareResults(rawA,rawB,options){
    const a=BH.createBenchmarkResult(rawA),b=BH.createBenchmarkResult(rawB);
    if(!BH.benchmarkComparable(a,b))
      return Object.freeze({comparable:false,code:'barehands_benchmark_not_comparable',
        reason:a.planClass!==b.planClass?'plan_class'
          :BH.benchmarkViewportClass(a.viewport)!==BH.benchmarkViewportClass(b.viewport)?'viewport':'suite'});
    const [before,after]=a.runAt<=b.runAt?[a,b]:[b,a];
    const replicates=options&&Number.isInteger(options.replicates)&&options.replicates>=100?options.replicates
      :BOOTSTRAP_REPLICATES;
    const x=scoreExercises(before.exercises),y=scoreExercises(after.exercises);
    const unsampled=[];
    for(const r of [before,after])for(const e of r.exercises)for(const name of Object.keys(e.metrics))
      if(e.metrics[name]!==null&&!(e.samples&&own(e.samples,name)&&e.samples[name].length))unsampled.push(`${e.ref}.${name}`);
    const rng=createRandom(parseInt(fingerprint({before,after}).slice(0,8),16));
    const enough=(e,name)=>!!(e.samples&&own(e.samples,name)&&e.samples[name].length>=MIN_CI_SAMPLES);
    const testable=new Set();
    before.exercises.forEach((e,i)=>{for(const name of Object.keys(e.metrics))
      if(enough(e,name)&&enough(after.exercises[i],name))testable.add(`${e.ref}.${name}`)});
    const dims={},names={},globals=[];
    for(const name of BH.BENCHMARK_DIMENSIONS){dims[name]=[];names[name]={}}
    for(let r=0;r<replicates;r+=1){
      const p=scoreExercises(resampleExercises(before.exercises,rng));
      const q=scoreExercises(resampleExercises(after.exercises,rng));
      for(const name of BH.BENCHMARK_DIMENSIONS){
        const u=p.dimensions[name].score,v=q.dimensions[name].score;
        if(u!==null&&v!==null)dims[name].push(v-u);
        const mp=metricMeans(p.dimensions[name],testable),mq=metricMeans(q.dimensions[name],testable);
        for(const metric of Object.keys(mq))if(own(mp,metric))
          (names[name][metric]||(names[name][metric]=[])).push(mq[metric]-mp[metric]);
      }
      if(p.global.score!==null&&q.global.score!==null)globals.push(q.global.score-p.global.score);
    }
    const dimensions={};
    for(const name of BH.BENCHMARK_DIMENSIONS){
      const p=x.dimensions[name].score,q=y.dimensions[name].score;
      const delta=p===null||q===null?null:round(q-p,1);
      const mp=metricMeans(x.dimensions[name],testable),mq=metricMeans(y.dimensions[name],testable);
      const ap=metricMeans(x.dimensions[name]),aq=metricMeans(y.dimensions[name]);
      const tested=Object.keys(mq).filter(metric=>own(mp,metric));
      const level=1-(1-CI_LEVEL)/Math.max(1,tested.length);
      const metrics=BH.BENCHMARK_DIMENSION_METRICS[name].map(metric=>{
        const has=tested.includes(metric);
        const measuredBoth=own(ap,metric)&&own(aq,metric);
        const d=has?round(mq[metric]-mp[metric],1):null;
        const ci=has&&names[name][metric]?interval(names[name][metric],level):null;
        /* Mesurée des deux côtés mais trop peu d'échantillons : pas de verdict. */
        const verdict=has?signedVerdict(ci,d):measuredBoth?'inconclusive':'unmeasured';
        return Object.freeze({metric,unit:BH.CALIBRATION_METRIC[metric].unit,level:round(level,4),
          scoreBefore:measuredBoth?round(ap[metric],1):null,scoreAfter:measuredBoth?round(aq[metric],1):null,scoreDelta:d,ci,
          reason:!has&&measuredBoth?'too_few_samples':null,verdict,
          values:Object.freeze(y.dimensions[name].metrics.filter(m=>m.metric===metric).map(m=>{
            const o=x.dimensions[name].metrics.find(k=>k.metric===metric&&k.exercise===m.exercise);
            return Object.freeze({exercise:m.exercise,before:o?o.value:null,after:m.value,
              delta:o&&o.value!==null&&m.value!==null?round(m.value-o.value,3):null});
          }))});
      });
      const ci=p===null||q===null?null:interval(dims[name],CI_LEVEL);
      dimensions[name]=Object.freeze({before:p,after:q,delta,ci,
        verdict:p===null||q===null?'unmeasured':combined(metrics.map(m=>m.verdict),delta),
        metrics:Object.freeze(metrics)});
    }
    const gp=x.global.score,gq=y.global.score;
    const gdelta=gp===null||gq===null?null:round(gq-gp,1);
    const gci=gdelta===null?null:interval(globals,CI_LEVEL);
    return Object.freeze({comparable:true,method:'resampling',replicates,level:CI_LEVEL,
      practicalMargin:PRACTICAL_MARGIN,equivalenceBand:EQUIVALENCE_BAND,unsampled:Object.freeze(unsampled),
      before:Object.freeze({runAt:before.runAt,seed:before.seed,profileSource:before.profileSource,
        trialRef:before.trialRef,profileFingerprint:before.profileFingerprint}),
      after:Object.freeze({runAt:after.runAt,seed:after.seed,profileSource:after.profileSource,
        trialRef:after.trialRef,profileFingerprint:after.profileFingerprint}),
      sameProfile:before.profileFingerprint!==null&&before.profileFingerprint===after.profileFingerprint,
      layoutsDiffer:before.seed!==after.seed,
      note:before.seed!==after.seed
        ?'Dispositions différentes, de même difficulté : l’apprentissage de la disposition est atténué, pas éliminé.'
        :'Même disposition rejouée : une amélioration peut venir de la mémoire de la disposition autant que du réglage.',
      dimensions:Object.freeze(dimensions),
      global:Object.freeze({before:gp,after:gq,delta:gdelta,ci:gci,verdict:signedVerdict(gci,gdelta)})});
  }

  /* ------------------------------------------------------------------ 10
     Le rangement des résumés (décision 64) : `/api/barehands/benchmarks`.
     Le seul chemin d'écriture du module ; il n'écrit que des résultats du
     contrat. Chaque réponse est lue (`response.ok`) et une panne remonte avec
     son code serveur. */
  const SUMMARY_ROUTE='/api/barehands/benchmarks';
  function createSummaryStore(deps){
    const d=deps||{};
    const doFetch=typeof d.fetch==='function'?d.fetch:(typeof fetch==='function'?fetch:null);
    if(!doFetch)fail('barehands_benchmark_invalid','createSummaryStore exige `fetch`.');
    const url=d.url||SUMMARY_ROUTE;
    async function call(method,body){
      const response=await doFetch(url,{method,headers:{'Content-Type':'application/json'},
        body:body===undefined?undefined:JSON.stringify(body)});
      if(!response.ok){
        const code=(response.headers&&typeof response.headers.get==='function'&&response.headers.get('X-Jarvis-Error-Code'))
          ||'barehands_benchmark_store_failed';
        let text='';try{text=await response.text()}catch(_error){text=''}
        fail(code,`Résumé de banc : ${method} ${url} → ${response.status}${text?` : ${text.slice(0,200)}`:''}`);
      }
      return response.json();
    }
    return Object.freeze({
      list:()=>call('GET'),
      save:result=>call('POST',BH.createBenchmarkResult(result)),
      clear:()=>call('DELETE'),
    });
  }

  const api=Object.freeze({
    BareHandsBenchmarkError,READ_ONLY,PLAN_CLASS,SUITE,BANDS,MIN_VIEWPORT,PHASE,RUNNER_DEPS,LAG_MIN_SPEED_PX,
    SETTLE_SPEED_PX,SETTLE_MS,SETTLE_WINDOW,
    createRandom,layoutTools,generatePlan,viewportCheck,layoutPlan,movingAt,profileView,readOnly,canonicalJson,fingerprint,
    engineFrame,METRIC_STAT,statOf,appendSample,settledJitter,spotJitter,UNSETTLED_JITTER_PX,MIN_TARGET_PX,bandsFor,
    createBenchmarkRunner,METRIC_SCORING,SCORE_SHIFT,WEAK_CAP_MARGIN,metricScore,geometricMean,scoreResult,
    METRIC_MODEL,NO_CLICK_EXPOSURE_MS,MIN_CI_SAMPLES,SPREAD_FLOOR,SPREAD_ABS,BOOTSTRAP_REPLICATES,PRACTICAL_MARGIN,EQUIVALENCE_BAND,CI_LEVEL,compareResults,
    SUMMARY_ROUTE,createSummaryStore,
  });
  root.JarvisBarehandsBenchmark=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
