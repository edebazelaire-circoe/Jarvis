/* Bare Hands — banc d'essai « Tester » : plan, déroulé, score, comparaison
   (tâche `jarvis-bare-hands-adaptive-calibration-benchmark`, Slice 08,
   `docs/barehands-contracts.md` § 17, décisions 40 et 60 à 64).

   **Ce que ce module mesure : la qualité d'interaction de Bare Hands pour un
   profil donné — jamais l'habileté ni la précision de l'utilisateur.** Aucun
   champ, aucune clé, aucun libellé ici ne dit « skill » ou « précision de
   l'utilisateur » : le même geste synthétique, rejoué sous deux profils, rend
   deux scores différents, et c'est le profil qu'ils jugent.

   Quatre choses, séparées :

   1. **le plan** (`generatePlan`, `layoutPlan`) : une graine → une suite
      d'exercices du contrat (`createBenchmarkPlan`) et une disposition tirée
      par un générateur déterministe. Deux graines donnent deux dispositions
      **équivalentes mais pas identiques** (règles de la classe de plan,
      `BANDS`) ; la même graine rejoue exactement la même ;
   2. **le déroulé** (`createBenchmarkRunner`) : des images du **vrai** moteur
      (couture de mesure + contacts et événements de pincement du contrôleur)
      entrent ; le vrai résolveur de cible (`decideTarget`, via
      `resolverHandOf`), le vrai constat de sélection
      (`createSelectionObserver`), le vrai moteur de captures
      (`createInteractionEngine`) sur le vrai cadre d'entraînement
      (`createPracticeFrame`) et le vrai segmenteur d'épisodes
      (`measurePinchEpisodes`) les lisent. Rien de l'interaction n'est
      réécrit ici : le déroulé pose des cibles, écoute et compte ;
   3. **le score** (`scoreResult`), pur : des métriques brutes aux dimensions,
      puis au score global, sensible à la dimension la plus faible ;
   4. **la comparaison** (`compareResults`), pure : avant/après par dimension,
      avec une bande de bruit.

   **Lecture seule, par structure.** Le déroulé ne reçoit que des vues gelées
   (`profileView`) et des fabriques de canaux neufs ; toute dépendance hors de
   sa liste blanche est refusée (`barehands_benchmark_read_only`), et toute
   écriture dans une vue lève le même code. Il n'a aucun chemin vers les
   réglages, le profil, l'essai ou la persistance. Seul `createSummaryStore`
   écrit — des **résumés** de banc (métriques brutes, jamais d'image), sur
   `/api/barehands/benchmarks`, et il n'est jamais donné au déroulé.

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
     Refus codés. */
  class BareHandsBenchmarkError extends Error{
    constructor(code,message){super(message);this.name='BareHandsBenchmarkError';this.code=code}
  }
  const fail=(code,message)=>{throw new BareHandsBenchmarkError(code,message)};
  const READ_ONLY='barehands_benchmark_read_only';
  const own=(object,key)=>object!==null&&object!==undefined&&Object.prototype.hasOwnProperty.call(object,key);
  const finite=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
  const round=(value,digits)=>{
    if(value===null||value===undefined||!Number.isFinite(value))return null;
    const k=10**digits;return Math.round(value*k)/k;
  };
  const clamp=(v,lo,hi)=>Math.min(Math.max(v,lo),hi);
  const median=list=>{
    const xs=list.filter(v=>Number.isFinite(v)).sort((a,b)=>a-b);
    if(!xs.length)return null;
    const m=xs.length>>1;return xs.length%2?xs[m]:(xs[m-1]+xs[m])/2;
  };

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
     La classe de plan `bh-bench-1` (décision 60) : la suite, et les bandes
     de difficulté. **Règle d'équivalence** : pour chaque exercice, le
     multi-ensemble des classes de difficulté (taille, distance, écart,
     vitesse, décalage) est **le même pour toutes les graines** ; la graine
     ne tire que l'ordre de ces classes, les directions, les positions et un
     écart de ±`distanceJitter` sur les distances (jamais sur les tailles :
     une cible plus petite est une autre difficulté). Une disposition qui ne
     tient pas dans le champ se retire d'une autre direction, jamais d'une
     autre classe. */
  const PLAN_CLASS=BH.BENCHMARK_PLAN_CLASS;
  const SUITE=Object.freeze([
    Object.freeze({kind:'target_acquisition',trials:6}),
    Object.freeze({kind:'nearby_targets',trials:6}),
    Object.freeze({kind:'moving_target',trials:4}),
    Object.freeze({kind:'drag_drop',trials:3}),
    Object.freeze({kind:'chained',trials:3}),
    /* En dernier, comme les négatifs de la calibration (décision 47) : ne
       pas cliquer après avoir cliqué est plus dur que l'inverse. */
    Object.freeze({kind:'no_click_tracking',trials:4}),
  ]);
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
    no_click_tracking:Object.freeze({modes:Object.freeze(['natural','natural','aim','aim']),durationMs:4800,naturalMs:7200,spots:3,
      spotMs:1600,holdMs:600,sizePx:24,spacingPx:140}),
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

  /* Le champ où l'on pose : la fenêtre moins une marge. */
  const fieldOf=viewport=>{
    const w=Number(viewport&&viewport.width),h=Number(viewport&&viewport.height);
    if(!(w>=640&&h>=400))fail('barehands_benchmark_viewport_invalid',
      'Le banc a besoin d’une fenêtre d’au moins 640 × 400 px : en deçà, les distances de la classe ne tiennent pas.');
    const m=BANDS.fieldMarginPx;
    return Object.freeze({x0:m,y0:m,x1:w-m,y1:h-m,width:w,height:h});
  };
  const inside=(field,x,y,inset)=>x>=field.x0+inset&&x<=field.x1-inset&&y>=field.y0+inset&&y<=field.y1-inset;
  const centerOf=field=>({x:(field.x0+field.x1)/2,y:(field.y0+field.y1)/2});
  /* Un point à `distance` de `from`, dans une direction tirée, qui tient dans
     le champ. 48 directions tirées ; à défaut, vers le centre (déterministe). */
  function reach(rng,field,from,distance,inset){
    for(let k=0;k<48;k+=1){
      const a=rng.between(0,Math.PI*2);
      const x=from.x+Math.cos(a)*distance,y=from.y+Math.sin(a)*distance;
      if(inside(field,x,y,inset))return {x,y};
    }
    const c=centerOf(field),a=Math.atan2(c.y-from.y,c.x-from.x);
    return {x:clamp(from.x+Math.cos(a)*distance,field.x0+inset,field.x1-inset),
      y:clamp(from.y+Math.sin(a)*distance,field.y0+inset,field.y1-inset)};
  }
  const jittered=(rng,value)=>value*(1+rng.between(-BANDS.distanceJitter,BANDS.distanceJitter));
  const far=(p,list,gap)=>list.every(q=>Math.hypot(p.x-q.x,p.y-q.y)>=gap);
  function freeSpot(rng,field,inset,avoid,gap){
    for(let k=0;k<64;k+=1){
      const p={x:rng.between(field.x0+inset,field.x1-inset),y:rng.between(field.y0+inset,field.y1-inset)};
      if(far(p,avoid,gap))return p;
    }
    return null;
  }
  const star=(id,p,size,expected)=>Object.freeze({id,x:p.x,y:p.y,size,expected:!!expected});

  const LAYOUT={
    target_acquisition(rng,field,trials,from){
      const B=BANDS.target_acquisition;
      const order=rng.shuffle(Array.from({length:trials},(_,i)=>B.schedule[i%B.schedule.length]));
      let at=from;
      return order.map(([si,di],i)=>{
        const size=B.sizesPx[si],distance=jittered(rng,B.distancesPx[di]);
        const p=reach(rng,field,at,distance,size/2+8);
        const stars=[star(`t${i}`,p,size,true)];
        for(let k=0;k<B.distractors;k+=1){
          const q=freeSpot(rng,field,B.distractorSizePx,[p,at,...stars.slice(1)],B.distractorClearPx);
          if(q)stars.push(star(`t${i}d${k}`,q,B.distractorSizePx,false));
        }
        const trial=Object.freeze({from:Object.freeze({...at}),sizeClass:si,distanceClass:di,
          distancePx:Math.hypot(p.x-at.x,p.y-at.y),stars:Object.freeze(stars)});
        at=p;return trial;
      });
    },
    nearby_targets(rng,field,trials,from){
      const B=BANDS.nearby_targets;
      const order=rng.shuffle(Array.from({length:trials},(_,i)=>B.schedule[i%B.schedule.length]));
      let at=from;
      return order.map((gi,i)=>{
        const gap=B.gapsPx[gi],pitch=B.sizePx+gap;
        const center=reach(rng,field,at,jittered(rng,B.approachPx),pitch*1.5+B.sizePx);
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
        const trial=Object.freeze({from:Object.freeze({...at}),gapClass:gi,gapPx:gap,arrangement:row?'row':'triangle',
          stars:Object.freeze(stars)});
        at={x:target.x,y:target.y};return trial;
      });
    },
    moving_target(rng,field,trials,from){
      const B=BANDS.moving_target;
      const order=rng.shuffle(Array.from({length:trials},(_,i)=>B.speedsPxPerS[i%B.speedsPxPerS.length]));
      let at=from;
      return order.map((speed,i)=>{
        const p=reach(rng,field,at,jittered(rng,B.startDistancePx),B.sizePx);
        const a=rng.between(0,Math.PI*2);
        const trial=Object.freeze({from:Object.freeze({...at}),speedPxPerS:speed,
          start:Object.freeze({x:p.x,y:p.y}),velocity:Object.freeze({x:Math.cos(a)*speed,y:Math.sin(a)*speed}),
          size:B.sizePx,id:`m${i}`});
        at=p;return trial;
      });
    },
    drag_drop(rng,field,trials,from,frame){
      const B=BANDS.drag_drop;
      const order=rng.shuffle(Array.from({length:trials},(_,i)=>B.offsetsPx[i%B.offsetsPx.length]));
      return order.map(offset=>dragLayout(rng,field,frame,jittered(rng,offset)));
    },
    chained(rng,field,trials,from,frame){
      const B=BANDS.chained;
      return Array.from({length:trials},(_,i)=>{
        const drag=dragLayout(rng,field,frame,jittered(rng,B.offsetPx));
        const avoid=[drag.start,drag.destination];
        const a=freeSpot(rng,field,B.sizePx,avoid,B.clearPx)||centerOf(field);
        const b=freeSpot(rng,field,B.sizePx,[...avoid,a],B.clearPx)||centerOf(field);
        return Object.freeze({first:star(`c${i}a`,a,B.sizePx,true),drag,last:star(`c${i}b`,b,B.sizePx,true)});
      });
    },
    no_click_tracking(rng,field,trials){
      const B=BANDS.no_click_tracking;
      const modes=rng.shuffle(Array.from({length:trials},(_,i)=>B.modes[i%B.modes.length]));
      return modes.map((mode,i)=>{
        const stars=[];
        for(let k=0;k<B.spots;k+=1){
          const p=freeSpot(rng,field,B.sizePx*2,stars,B.spacingPx)||centerOf(field);
          stars.push(star(`q${i}s${k}`,p,B.sizePx,false));
        }
        return Object.freeze({mode,stars:Object.freeze(stars),durationMs:mode==='natural'?B.naturalMs:B.durationMs});
      });
    },
  };
  /* Un déplacement de cadre : départ et destination (centres, px), à
     `offset` px, direction presque horizontale (±`maxAngleDeg`), vers le côté
     où elle tient. */
  function dragLayout(rng,field,frame,offset){
    const B=BANDS.drag_drop;
    const inset={x:frame.w/2+8,y:frame.h/2+8};
    const fits=p=>p.x>=field.x0+inset.x&&p.x<=field.x1-inset.x&&p.y>=field.y0+inset.y&&p.y<=field.y1-inset.y;
    for(let k=0;k<64;k+=1){
      const start={x:rng.between(field.x0+inset.x,field.x1-inset.x),y:rng.between(field.y0+inset.y,field.y1-inset.y)};
      const angle=rng.between(-B.maxAngleDeg,B.maxAngleDeg)*Math.PI/180;
      const side=rng.next()<.5?-1:1;
      for(const s of [side,-side]){
        const destination={x:start.x+s*Math.cos(angle)*offset,y:start.y+Math.sin(angle)*offset};
        if(fits(destination))return Object.freeze({start:Object.freeze(start),destination:Object.freeze(destination),
          offsetPx:offset});
      }
    }
    const c=centerOf(field);
    return Object.freeze({start:Object.freeze({x:c.x-offset/2,y:c.y}),destination:Object.freeze({x:c.x+offset/2,y:c.y}),
      offsetPx:offset});
  }

  /* La taille du cadre d'entraînement en px, à l'échelle donnée. */
  const frameSizePx=scale=>({w:BANDS.drag_drop.frameUnits.w*scale,h:BANDS.drag_drop.frameUnits.h*scale});

  /* **La disposition d'un plan**, pure et déterministe : même plan + même
     fenêtre → même disposition, octet pour octet. */
  function layoutPlan(rawPlan,viewport){
    const plan=BH.createBenchmarkPlan(rawPlan);
    if(plan.planClass!==PLAN_CLASS)fail('barehands_benchmark_plan_class_unknown',
      `Classe de plan ${plan.planClass} : ce banc tire la classe ${PLAN_CLASS}.`);
    const field=fieldOf(viewport);
    const scale=Number(viewport&&viewport.scale)>0?Number(viewport.scale):BANDS.frameScale;
    const frame=frameSizePx(scale);
    let from=centerOf(field);
    const exercises=plan.exercises.map((e,index)=>{
      const rng=createRandom(subSeed(plan.seed,index));
      const trials=LAYOUT[e.kind](rng,field,e.trials,from,frame);
      const last=trials[trials.length-1];
      if(last&&last.stars){const t=last.stars.find(s=>s.expected);if(t)from={x:t.x,y:t.y}}
      return Object.freeze({ref:e.ref,kind:e.kind,trials:Object.freeze(trials)});
    });
    return Object.freeze({seed:plan.seed,planClass:plan.planClass,field,scale,exercises:Object.freeze(exercises)});
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
     Vues en lecture seule. Une copie profonde de données, gelée, derrière un
     `Proxy` qui **refuse** toute écriture avec un code nommé — pas un
     `TypeError` muet du mode strict : un appelant qui écrit doit savoir
     pourquoi il ne peut pas. */
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
     16 caractères hexadécimaux. Elle sépare deux profils `saved`
     différents ; elle ne dit rien de la personne. */
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

  /* **La vue de profil** que le déroulé reçoit : ce qu'il lui faut (options
     de cible, assistance, grâce de perte) et l'identité de ce qui est mesuré.
     Construite depuis la composition effective (`composeEffective`,
     décision 48) — la même que le moteur applique. */
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
     (`deps.onMeasure`, des scalaires par main) et les contacts/événements de
     pincement de la même image (`controller.semantics().pinch`). Recopiée
     clé par clé : rien d'autre n'entre, et rien n'est gardé au-delà du run. */
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
     Le déroulé. */
  const RUNNER_DEPS=Object.freeze(['contracts','core','target','geometry','calibration','profile','plan','viewport',
    'pinchChannel','log']);
  const PHASE=Object.freeze({IDLE:'idle',GAP:'gap',LIVE:'live',DONE:'done'});
  /* Seuil de vitesse du retard de pointeur : sous 150 px/s, l'écart brut /
     filtré est du tremblement, pas du retard. */
  const LAG_MIN_SPEED_PX=150;
  const STAR_KIND='scene_object',STAR_REPRESENTATION='point';
  const starCandidate=(s,x,y)=>({objectId:`bench:${s.id}`,key:`o:bench:${s.id}`,kind:STAR_KIND,
    representation:STAR_REPRESENTATION,zoned:false,actionable:true,container:false,
    boundsPx:{x:x-s.size/2,y:y-s.size/2,w:s.size,h:s.size}});

  function createBenchmarkRunner(deps){
    const d=deps&&typeof deps==='object'?deps:fail('barehands_benchmark_invalid','createBenchmarkRunner exige ses dépendances.');
    /* **La porte de la lecture seule.** Une dépendance que la liste ne nomme
       pas — un `save`, un `trials`, un `settings` — est refusée : le banc
       n'a pas de main par où écrire. */
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
    const view=readOnly({width:Number(d.viewport&&d.viewport.width),height:Number(d.viewport&&d.viewport.height),
      scale:Number(d.viewport&&d.viewport.scale)>0?Number(d.viewport.scale):BANDS.frameScale,
      cx:Number.isFinite(Number(d.viewport&&d.viewport.cx))?Number(d.viewport.cx):Number(d.viewport&&d.viewport.width)/2,
      cy:Number.isFinite(Number(d.viewport&&d.viewport.cy))?Number(d.viewport.cy):Number(d.viewport&&d.viewport.height)/2});
    const plan=BH.createBenchmarkPlan(d.plan);
    const layout=layoutPlan(plan,view);
    const field=layout.field;
    const K_OPTIONS=K.options();
    const tolerancePx=K_OPTIONS.dropTolerancePx;
    const attemptsMax=BANDS.attemptsMax;
    const lostGraceMs=Number.isFinite(profile.lostGraceMs)?profile.lostGraceMs
      :(core.DEFAULTS&&core.DEFAULTS.lostGraceMs)||250;
    const assistance=profile.assistance;
    const resolver=core.createTargetResolver({pickRegion:C.pickRegion,...profile.targets});
    const observer=core.createSelectionObserver();

    let phase=PHASE.IDLE,phaseAt=0,exIndex=-1,trialIndex=-1,now=0;
    let trial=null;          // l'essai en cours (état de jugement)
    let practice=null,engine=null;
    let episodeRef=0;
    const accs=layout.exercises.map(e=>({ref:e.ref,kind:e.kind,trials:[],samples:[],
      noClick:{exposureMs:0,naturalMs:0,primaryDowns:0,secondaryDowns:0,falseClicks:0,targets:0,pointers:0,jitter:[]},
      lag:[],ambiguity:[],transitions:[],lastLiveT:null}));

    const exercise=()=>layout.exercises[exIndex]||null;
    const acc=()=>accs[exIndex]||null;

    /* ---- le cadre d'entraînement (vrai `createPracticeFrame`, vrai moteur
       de captures, vraie géométrie de scène). Un neuf par déplacement : sa
       boîte de départ est celle de la disposition. */
    const unitBoxAt=center=>{
      const size=frameSizePx(view.scale);
      return {x:(center.x-view.cx)/view.scale-size.w/view.scale/2,y:(center.y-view.cy)/view.scale-size.h/view.scale/2,
        w:BANDS.drag_drop.frameUnits.w,h:BANDS.drag_drop.frameUnits.h};
    };
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
    const frameCandidate=()=>{
      const px=pxOfBox(practice.box());
      return {objectId:practice.objectId,key:`o:${practice.objectId}`,kind:STAR_KIND,representation:'window',
        zoned:true,actionable:true,container:false,boundsPx:px};
    };
    const dragError=drag=>{
      const px=pxOfBox(practice.box());
      const dx=px.x+px.w/2-drag.destination.x,dy=px.y+px.h/2-drag.destination.y;
      return {dx,dy,error:Math.hypot(dx,dy),inside:Math.abs(dx)<=tolerancePx&&Math.abs(dy)<=tolerancePx};
    };

    /* ---- ce qui est à l'écran pendant l'essai en cours. */
    function visibleStars(){
      if(!trial||phase!==PHASE.LIVE)return [];
      const e=exercise(),spec=e.trials[trialIndex];
      if(e.kind==='moving_target'){
        const p=movingAt(spec,field,now-trial.openedAt);
        return [star(spec.id,p,spec.size,true)];
      }
      if(e.kind==='chained'){
        if(trial.step===0)return [spec.first];
        if(trial.step===2)return [spec.last];
        return [];
      }
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
        entries:0,onExpected:false,step:0,stepDoneAt:null,stepAttempts:0,spotIndex:-1};
      phase=PHASE.LIVE;phaseAt=t;
      acc().lastLiveT=null;
      resolver.reset();
      if(e.kind==='drag_drop')openPractice(spec);
      armObserver();
    }
    function closeTrial(t,outcome){
      const a=acc(),e=exercise(),spec=e.trials[trialIndex];
      const record={outcome,missed:trial.missed,wrong:trial.wrong,premature:trial.premature,
        acquisitionMs:null,reacquisitions:Math.max(0,trial.entries-1),error:null};
      const timeout=timeoutOf(e.kind);
      if(e.kind==='target_acquisition'||e.kind==='nearby_targets'||e.kind==='moving_target'){
        /* Un essai sans sélection réussie est **censuré** à l'échéance : un
           système qui ne prend rien n'a pas une acquisition « non mesurée »,
           il en a une infiniment lente. */
        record.acquisitionMs=trial.success!==null?trial.success-trial.openedAt:timeout;
        if(trial.success===null&&!trial.wrong)record.missed=true;
      }
      if(e.kind==='drag_drop'){
        record.error=practice?dragError(spec).error:null;
      }
      if(e.kind==='chained'){
        if(outcome!=='success'&&trial.step!==1&&!trial.wrong)record.missed=true;
        if(outcome!=='success'&&trial.step===1)record.premature=true;
      }
      a.trials.push(record);
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
      /* Les latences : le **vrai** segmenteur d'épisodes (décision 43) sur
         les rapports de pincement vus pendant l'exercice, et un canal neuf
         aux options que le moteur applique (`pinchChannel`). */
      const measured=K.measurePinchEpisodes(a.samples,BH.PINCH_CHANNEL.PRIMARY,{options:K_OPTIONS,
        detector:handedness=>d.pinchChannel(BH.PINCH_CHANNEL.PRIMARY,handedness),lostGraceMs,
        nextRef:()=>`${BH.SESSION_REF.EPISODE}-${++episodeRef}`});
      a.pressLatency=median(measured.episodes.map(ep=>finite(ep.pressLatencyMs)));
      a.releaseLatency=median(measured.episodes.map(ep=>finite(ep.releaseLatencyMs)));
      a.episodes=measured.episodes.length;
      a.samples=[];   // rien de brut ne survit à l'exercice
      say('info','barehands.benchmark_exercise',{exercise:a.ref,kind:a.kind,trials:a.trials.length,episodes:a.episodes});
      exIndex+=1;trialIndex=0;
      if(exIndex>=layout.exercises.length){
        phase=PHASE.DONE;phaseAt=t;
        say('info','barehands.benchmark_done',{exercises:layout.exercises.length});
      }else{phase=PHASE.GAP;phaseAt=t-BANDS.gapMs+BANDS.exerciseGapMs}
    }
    /* L'échéance d'un essai ; un essai négatif dure ce que dit la
       disposition (il se solde toujours « réussi » à son terme). */
    const timeoutOf=kind=>kind==='no_click_tracking'?Infinity:BANDS[kind].timeoutMs;

    /* ---- le jugement d'une image. */
    function judgeSelection(facts,records,t){
      const e=exercise();
      const expectedKeys=new Set(visibleStars().filter(s=>s.expected).map(s=>`o:bench:${s.id}`));
      /* Reprises : l'aperçu est venu sur la cible attendue, en est reparti,
         et y revient — avant la sélection. */
      const on=records.some(r=>r.channel===BH.PINCH_CHANNEL.PRIMARY&&r.key!==null&&expectedKeys.has(r.key));
      if(on&&!trial.onExpected)trial.entries+=1;
      trial.onExpected=on;
      for(const fact of facts){
        if(fact.type!=='press')continue;
        if(e.kind==='nearby_targets'&&fact.ambiguity!==null)acc().ambiguity.push(fact.ambiguity);
        trial.attempts+=1;
        if(fact.outcome==='expected'){trial.success=fact.t;return 'success'}
        if(fact.outcome==='other')trial.wrong=true;else trial.missed=true;
        if(trial.attempts>=attemptsMax)return 'failed';
      }
      return null;
    }
    function judgeDrag(drag,log){
      for(const entry of log){
        if(entry.type!=='commit'&&entry.type!=='cancel')continue;
        if(entry.type==='commit'&&!entry.moved)continue;   // un clic sur le cadre n'est pas un dépôt
        trial.stepAttempts+=1;
        const at=dragError(drag);
        if(entry.type==='commit'&&at.inside)return 'success';
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
       demande. */
    const shownBefore=new Map(),targetedBefore=new Map();
    function judgeNoClick(f,records,dt){
      const e=exercise(),spec=e.trials[trialIndex],n=acc().noClick;
      const natural=spec.mode==='natural';
      n.exposureMs+=dt;if(natural)n.naturalMs+=dt;
      for(const ev of f.events){
        if(ev.phase!==BH.PINCH_PHASE.DOWN)continue;
        if(ev.channel===BH.PINCH_CHANNEL.PRIMARY)n.primaryDowns+=1;else n.secondaryDowns+=1;
      }
      for(const fact of observer.drain())if(fact.type==='press'&&fact.outcome!=='none')n.falseClicks+=1;
      if(natural){
        for(const h of f.hands){
          const id=String(h.handTrackId);
          if(h.pointerShown&&!shownBefore.get(id))n.pointers+=1;
          shownBefore.set(id,h.pointerShown);
        }
        for(const r of records){
          const lane=`${String(r.handTrackId)}|${r.channel}`;
          const has=r.key!==null;
          if(has&&!targetedBefore.get(lane))n.targets+=1;
          targetedBefore.set(lane,has);
        }
      }else{
        /* Tremblement : la fin (`holdMs`) de chaque point de visée, jeton
           affiché, écart au médian de la fenêtre. */
        const B=BANDS.no_click_tracking;
        const since=f.t-trial.openedAt;
        const spot=Math.floor(since/B.spotMs);
        if(spot!==trial.spotIndex){flushJitter(n);trial.spotIndex=spot;trial.window=[]}
        if(since%B.spotMs>=B.spotMs-B.holdMs)
          for(const h of f.hands)if(h.pointerShown&&h.pointerX!==null&&h.pointerY!==null)
            (trial.window||(trial.window=[])).push({x:h.pointerX,y:h.pointerY});
      }
    }
    function flushJitter(n){
      const w=trial&&trial.window;
      if(!w||w.length<3)return;
      const mx=median(w.map(p=>p.x)),my=median(w.map(p=>p.y));
      for(const p of w)n.jitter.push(Math.hypot(p.x-mx,p.y-my));
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
      /* Les échantillons de l'exercice, pour ses épisodes : le temps de
         l'exercice, trous compris (un relâchement tombe souvent entre deux
         essais). Effacés à la fin de l'exercice. */
      for(const h of hands)a.samples.push({...h,t});
      const {records,targets,tokens}=resolve(clean);
      if(phase!==PHASE.LIVE){observer.drain();return state()}
      const dt=a.lastLiveT===null?0:Math.min(200,Math.max(0,t-a.lastLiveT));
      a.lastLiveT=t;
      observer.update(records,t);
      let verdict=null;
      if(e.kind==='no_click_tracking'){
        judgeNoClick(clean,records,dt);
        if(t-trial.openedAt>=e.trials[trialIndex].durationMs){flushJitter(a.noClick);verdict='success'}
      }else{
        if(e.kind==='moving_target')
          for(const h of hands){
            const speed=h.speedPxPerSec;
            if(speed!==null&&speed>=LAG_MIN_SPEED_PX&&h.rawX!==null&&h.filteredX!==null)
              a.lag.push(Math.hypot(h.rawX-h.filteredX,h.rawY-h.filteredY)/speed*1000);
          }
        const drag=dragOf();
        if(drag&&engine){
          engine.update({now:t,tokens,targets:targets.filter(x=>x.objectId===practice.objectId),
            contacts:clean.contacts,events:clean.events});
          verdict=judgeDrag(drag,practice.drain());
          observer.drain();
        }else{
          verdict=judgeSelection(observer.drain(),records,t);
        }
        if(e.kind==='chained'){
          /* Transition : de la fin d'une étape au premier appui de la
             suivante (événement `down` du vrai moteur de pincement). */
          if(trial.stepDoneAt!==null)
            for(const ev of clean.events)
              if(ev.channel===BH.PINCH_CHANNEL.PRIMARY&&ev.phase===BH.PINCH_PHASE.DOWN&&trial.stepDoneAt!==null){
                a.transitions.push(t-trial.stepDoneAt);trial.stepDoneAt=null;
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

    /* ---- la sortie : métriques brutes, **toutes**, `null` si non mesurée. */
    const perTrial=(a,key)=>a.trials.filter(r=>r[key]).length;
    const rate=(count,ms)=>ms>0?count/(ms/60000):null;
    function metricsOf(a){
      const acquisition=round(median(a.trials.map(r=>r.acquisitionMs)),1);
      const reacq=a.trials.reduce((s,r)=>s+r.reacquisitions,0);
      switch(a.kind){
        case 'target_acquisition':return {acquisition_ms:acquisition,missed_click_count:perTrial(a,'missed'),
          wrong_target_count:perTrial(a,'wrong'),reacquisition_count:reacq,press_latency_ms:round(a.pressLatency,1)};
        case 'nearby_targets':return {acquisition_ms:acquisition,wrong_target_count:perTrial(a,'wrong'),
          target_ambiguity:round(median(a.ambiguity),3),reacquisition_count:reacq};
        case 'moving_target':return {acquisition_ms:acquisition,pointer_lag_ms:round(median(a.lag),1),
          missed_click_count:perTrial(a,'missed'),reacquisition_count:reacq};
        case 'drag_drop':return {drag_success_rate:round(a.trials.filter(r=>r.outcome==='success').length/a.trials.length,3),
          premature_drop_count:perTrial(a,'premature'),placement_error_px:round(median(a.trials.map(r=>r.error)),1),
          release_latency_ms:round(a.releaseLatency,1)};
        case 'chained':return {transition_ms:round(median(a.transitions),1),missed_click_count:perTrial(a,'missed'),
          wrong_target_count:perTrial(a,'wrong'),premature_drop_count:perTrial(a,'premature'),
          release_latency_ms:round(a.releaseLatency,1)};
        case 'no_click_tracking':{
          const n=a.noClick;
          const jitter=n.jitter.length?BH.quantile(n.jitter.slice().sort((x,y)=>x-y),.95):null;
          return {false_click_count:n.falseClicks,false_press_rate:round(rate(n.primaryDowns,n.exposureMs),3),
            false_secondary_press_rate:round(rate(n.secondaryDowns,n.exposureMs),3),
            unintended_target_rate:round(rate(n.targets,n.naturalMs),3),
            unintended_pointer_rate:round(rate(n.pointers,n.naturalMs),3),pointer_jitter_px:round(jitter,2)};
        }
        default:return {};
      }
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
      start(at){
        const t=finite(Number(at));
        if(t===null)fail('barehands_benchmark_invalid','start exige un horodatage.');
        if(phase!==PHASE.IDLE)fail('barehands_benchmark_already_started','Ce banc a déjà commencé : un run, un déroulé.');
        now=t;exIndex=0;trialIndex=0;phase=PHASE.GAP;phaseAt=t;
        say('info','barehands.benchmark_started',{seed:plan.seed,planClass:plan.planClass,profileSource:profile.source,
          exercises:layout.exercises.length});
        return state();
      },
      frame,
      state,
      done:()=>phase===PHASE.DONE,
      /* Le résultat du contrat (`createBenchmarkResult`) : métriques brutes
         par exercice, identité du profil, graine, classe, instant du run. */
      result(meta){
        if(phase!==PHASE.DONE)fail('barehands_benchmark_incomplete','Le banc n’est pas allé au bout : aucun résultat partiel ne se compare.');
        const m=meta||{};
        return C.createBenchmarkResult({schemaVersion:C.SESSION_SCHEMA_VERSION,kind:'benchmark_result',
          ref:m.ref||`${BH.SESSION_REF.BENCHMARK}-1`,seed:plan.seed,planClass:plan.planClass,runAt:m.runAt,
          profileSource:profile.source,trialRef:profile.trialRef,profileFingerprint:profile.fingerprint,
          exercises:accs.map((a,i)=>({ref:a.ref,kind:a.kind,trials:layout.exercises[i].trials.length,metrics:metricsOf(a)}))});
      },
    });
  }

  /* ------------------------------------------------------------------ 7
     Le score (décisions 61 et 62). Pur : un résultat de banc entre, des
     dimensions et un score global sortent — **avec** les métriques brutes.

     Chaque métrique a une rampe linéaire entre deux ancres, dans son unité :
     `good` → 100, `bad` → 0, bornée. `per: 'trial'` divise d'abord un compte
     par le nombre d'essais de l'exercice (6 ratés sur 6 essais et 1 sur 1 ne
     sont pas la même chose). Les ancres et leur justification sont au
     contrat lisible (§ 17, décision 61). */
  const METRIC_SCORING=Object.freeze({
    acquisition_ms:Object.freeze({good:1200,bad:3500}),
    reacquisition_count:Object.freeze({good:0,bad:2,per:'trial'}),
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
    pointer_jitter_px:Object.freeze({good:1.5,bad:10}),
    pointer_lag_ms:Object.freeze({good:40,bad:160}),
    press_latency_ms:Object.freeze({good:60,bad:260}),
    transition_ms:Object.freeze({good:1200,bad:3600}),
  });
  /* **Moyenne géométrique décalée** : exp(moyenne(ln(s + 1))) − 1. Le
     décalage d'un point garde 0 → 0 et 100 → 100, et évite qu'un zéro exact
     annule tout le produit (deux systèmes « nuls » deviendraient
     indiscernables, et un seul zéro effacerait toutes les autres mesures). */
  const SCORE_SHIFT=1;
  /* **Plafond par la plus faible** : le global ne dépasse jamais la dimension
     la plus faible de plus de `WEAK_CAP_MARGIN` points. */
  const WEAK_CAP_MARGIN=25;
  /* Le global n'existe que si au moins 6 des 8 dimensions sont mesurées : un
     score sur deux dimensions se lirait comme un score sur huit. */
  const GLOBAL_MIN_DIMENSIONS=6;

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

  /* **Le score d'un résultat.** Dimension = moyenne géométrique des scores
     de ses métriques (chaque occurrence exercice × métrique compte une fois) ;
     global = min(moyenne géométrique des dimensions, plus faible +
     `WEAK_CAP_MARGIN`). Les métriques brutes voyagent avec : un score sans
     ses faits ne s'explique pas. */
  function scoreResult(raw){
    const result=BH.createBenchmarkResult(raw);
    const dimensions={};
    for(const name of BH.BENCHMARK_DIMENSIONS){
      const metrics=[];
      for(const e of result.exercises)for(const metric of BH.BENCHMARK_DIMENSION_METRICS[name]){
        if(!own(e.metrics,metric))continue;
        const value=e.metrics[metric];
        metrics.push(Object.freeze({exercise:e.ref,kind:e.kind,metric,value,unit:BH.CALIBRATION_METRIC[metric].unit,
          trials:e.trials,score:metricScore(metric,value,e.trials)}));
      }
      const scored=metrics.map(m=>m.score).filter(s=>s!==null);
      dimensions[name]=Object.freeze({score:scored.length?round(geometricMean(scored),1):null,
        metrics:Object.freeze(metrics)});
    }
    const measured=BH.BENCHMARK_DIMENSIONS.filter(n=>dimensions[n].score!==null);
    let global=null,weakest=null,capped=false;
    if(measured.length){
      weakest=measured.reduce((w,n)=>dimensions[n].score<dimensions[w].score?n:w,measured[0]);
    }
    if(measured.length>=GLOBAL_MIN_DIMENSIONS){
      const mean=geometricMean(measured.map(n=>dimensions[n].score));
      const cap=dimensions[weakest].score+WEAK_CAP_MARGIN;
      capped=cap<mean;
      global=round(Math.min(mean,cap),1);
    }
    return Object.freeze({kind:'benchmark_scores',subject:'interaction_quality',planClass:result.planClass,
      seed:result.seed,runAt:result.runAt,profileSource:result.profileSource,trialRef:result.trialRef,
      profileFingerprint:result.profileFingerprint,
      dimensions:Object.freeze(dimensions),
      global:Object.freeze({score:global,weakest,capped,measured:measured.length,
        unmeasured:Object.freeze(BH.BENCHMARK_DIMENSIONS.filter(n=>dimensions[n].score===null))}),
      result});
  }

  /* ------------------------------------------------------------------ 8
     Avant / après (décision 63). Deux résultats **comparables** (même classe
     de plan, même suite ; graines libres). La bande de bruit est en points
     de score : sous elle, « inchangé ». */
  /* **Bandes de bruit par dimension**, en points (décision 63). Mesurées, pas
     choisies : l'écart maximal d'une dimension entre dix dispositions
     équivalentes (graines différentes, même profil, même utilisateur
     synthétique) sous sept profils — défauts, relâchement lent, assistance
     coupée, fermetures parasites, tremblement de 6 px, appui haut, filtre
     lent —, arrondi aux 5 points supérieurs, jamais sous `NOISE_BAND_MIN`.
     Une dimension de comptes rares (faux positifs) ou de temps censurés
     (acquisition sans assistance) varie beaucoup d'une disposition à
     l'autre : sa bande est large, et c'est le vrai prix d'un banc court. */
  const NOISE_BAND_MIN=8;
  const NOISE_BANDS=Object.freeze({
    acquisition:40,selection_accuracy:NOISE_BAND_MIN,false_positive_resistance:25,
    release_reliability:NOISE_BAND_MIN,drag_drop:NOISE_BAND_MIN,pointer_stability:25,
    reactivity:NOISE_BAND_MIN,transitions:NOISE_BAND_MIN,global:25,
  });
  function compareResults(rawA,rawB){
    const a=BH.createBenchmarkResult(rawA),b=BH.createBenchmarkResult(rawB);
    if(!BH.benchmarkComparable(a,b))
      return Object.freeze({comparable:false,code:'barehands_benchmark_not_comparable',
        reason:a.planClass!==b.planClass?'plan_class':'suite'});
    const [before,after]=a.runAt<=b.runAt?[a,b]:[b,a];
    const x=scoreResult(before),y=scoreResult(after);
    const verdict=(p,q,band)=>{
      if(p===null||q===null)return {before:p,after:q,delta:null,noiseBand:band,verdict:'unmeasured'};
      const delta=round(q-p,1);
      return {before:p,after:q,delta,noiseBand:band,
        verdict:delta>=band?'improved':delta<=-band?'regressed':'unchanged'};
    };
    const dimensions={};
    for(const name of BH.BENCHMARK_DIMENSIONS)
      dimensions[name]=Object.freeze(verdict(x.dimensions[name].score,y.dimensions[name].score,NOISE_BANDS[name]));
    return Object.freeze({comparable:true,noiseBands:NOISE_BANDS,
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
      global:Object.freeze(verdict(x.global.score,y.global.score,NOISE_BANDS.global)),
      scores:Object.freeze({before:x,after:y})});
  }

  /* ------------------------------------------------------------------ 9
     Le rangement des résumés (décision 64) : `/api/barehands/benchmarks`.
     Le seul chemin d'écriture du module, et il n'écrit que des résultats du
     contrat (métriques brutes, jamais d'image). Chaque réponse est lue
     (`response.ok`) et une panne remonte avec son code serveur. */
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
    BareHandsBenchmarkError,READ_ONLY,PLAN_CLASS,SUITE,BANDS,PHASE,RUNNER_DEPS,LAG_MIN_SPEED_PX,
    createRandom,generatePlan,layoutPlan,movingAt,profileView,readOnly,canonicalJson,fingerprint,engineFrame,
    createBenchmarkRunner,METRIC_SCORING,SCORE_SHIFT,WEAK_CAP_MARGIN,GLOBAL_MIN_DIMENSIONS,metricScore,scoreResult,
    NOISE_BAND_MIN,NOISE_BANDS,compareResults,SUMMARY_ROUTE,createSummaryStore,
  });
  root.JarvisBarehandsBenchmark=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
