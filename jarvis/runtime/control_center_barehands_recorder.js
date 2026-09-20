/* Bare Hands V1 — enregistrement, rejeu et mesures (Slice 10).
   Architecture §12, décision 32.

   **Ce module existe pour rendre Bare Hands réglable par des faits.** Jusqu'ici
   un seuil se changeait à l'estime : on refaisait le geste, on disait « c'est
   mieux », et personne ne pouvait comparer deux réglages autrement qu'en les
   revivant. Une trace enregistrée une fois se rejoue autant qu'on veut, sous
   autant de configurations qu'on veut, et rend des **nombres comparables**.

   ------------------------------------------------------------------
   CE QU'UNE TRACE CONTIENT — ET CE QU'ELLE NE CONTIENT PAS

   **Aucun point de main. Aucune image. Aucune vidéo. Aucun identifiant.**

   La Slice l'écrivait pourtant noir sur blanc : « schéma de trace contenant
   horodatages, **points de main**, latéralité/confiance, points bruts et
   filtrés, vitesse/immobilité, états de geste et de pincement, candidates de
   cible, captures et issues ». Huit de ces neuf éléments sont des **scalaires
   dérivés** que le contrôleur produit déjà. Le neuvième — les vingt et un
   points d'une main — est une **reconstruction de la main de l'utilisateur**,
   et c'est la chose la plus dangereuse que cette tâche ait proposée
   d'enregistrer.

   Il n'est pas enregistré, et voici l'argument, parce qu'un refus sans
   argument est un caprice :

   1. **Aucun rejeu nommé par la Slice n'en a besoin.** Le contrat demande de
      rejouer sous d'autres *filtres*, d'autres *seuils* et d'autres
      *résolveurs de cible*. Le filtre se nourrit de `rawX`/`rawY` et d'un
      horodatage ; l'hystérésis de pincement (`createPinchChannel`) se nourrit
      d'un **ratio** scalaire ; le résolveur se nourrit d'une position et de
      rectangles. Aucun des trois ne reçoit jamais de points, aujourd'hui, dans
      le moteur réel. Les points ne serviraient qu'à dériver des traits qui
      n'existent pas encore — c'est-à-dire à changer l'extracteur, ce que la
      Slice met **hors** de son périmètre.
   2. **La décision 32 dit « seulement des paramètres dérivés et des mesures de
      qualité ».** Un tableau de points n'est ni l'un ni l'autre : c'est la
      donnée d'origine, à peine transformée.
   3. **Et la garantie ne serait pas tenable par intention.** Un enregistreur
      qui *pourrait* recevoir des points n'a besoin que d'une Slice distraite
      pour en écrire.

   Ce n'est donc pas une promesse, ce sont trois mécanismes qui ne se doublent
   pas — les mêmes que la Slice 08, dans le même ordre :

   - **Une couture qui réduit avant que l'enregistreur ne voie quoi que ce
     soit.** L'enregistreur est nourri par la couture `deps.onMeasure` du
     contrôleur (§10, décision 32), qui a déjà réduit l'image à un
     enregistrement de scalaires par main. Il ne reçoit pas de points parce
     qu'il n'en a jamais eu : `createRecorder` n'a **aucun** paramètre qui
     puisse en transporter, et refuse à la construction toute dépendance hors
     de sa liste blanche.
   - **Une liste blanche qui reconstruit clé par clé.** `readFrame`,
     `readHand`, `readEvent` et `readCandidate` ne recopient jamais la source :
     ce que le schéma ne nomme pas n'atteint jamais la trace — pas parce qu'on
     le refuse, parce qu'on ne le recopie pas.
   - **Une garde de forme au chargement du module, pilotée par le schéma.**
     `assertDerivedOnly` présente à **chaque clé** de **chaque forme** une
     suite de points, une image en base64 et un objet libre. Un profil rempli
     de valeurs plausibles ne dirait rien d'une clé ajoutée demain ; le
     balayage est donc piloté par les formes elles-mêmes. Et il porte ses
     **jumelles bien formées** (leçon de la reprise de la Slice 08) : une
     sonde qui peut être refusée en chemin mesure le chemin au lieu de la
     porte.

   **Deux réductions de plus, qui ne sont pas de la prudence décorative.**

   - `handTrackId` devient une **fente** (`slot`, 0 ou 1). Un identifiant est
     une poignée de corrélation ; un numéro de fente n'en est pas une.
   - Une candidate de cible garde sa **géométrie** et son vocabulaire fermé,
     jamais son `objectId` ni son libellé : le résolveur a besoin de
     rectangles, pas de savoir ce qui est écrit dessus. La continuité d'une
     capture est portée par un **rang dans la trace** (`ref`), qui ne veut rien
     dire hors d'elle.

   **Et l'utilisateur le sait.** L'enregistrement est éteint par défaut, ne
   s'allume que par une action explicite, dit à l'écran qu'il tourne, depuis
   combien de temps et combien d'images il a prises, et s'arrête tout seul au
   bout de son échéance. C'est la RÈGLE ZÉRO appliquée à une fonctionnalité qui
   observe : ce qui observe sans le dire est ce que personne n'accepte.

   Insertion : après les contrats (il les lit) et après le tutoriel, **avant**
   `control_center_barehands.js`, qui lit celui-ci pour poser
   `JarvisBarehands.record` sur sa surface gelée. Un test de page vérifie
   l'ordre (constat F3 de la Slice 00). */
(function(root){
  'use strict';
  const BH=root.JarvisBarehandsContracts;
  if(!BH){
    /* Même règle que le tutoriel : la cause part dans la console et **ce
       module seul** reste absent. Une levée emporterait la scène, la timeline
       et le Test Lab avec elle, la page servie n'ayant qu'une balise
       `<script>`. */
    console.error('[barehands] barehands.recorder_not_installed '
      +JSON.stringify({error:'les contrats Bare Hands doivent être insérés avant ce module'}));
    return;
  }

  /* ------------------------------------------------------------------ 1
     Le schéma de trace, et sa version.

     La version est **dans le document**, pas dans le nom du fichier : une
     trace qu'on relit dans six mois doit dire elle-même ce qu'elle est. Le
     rejeu refuse une version qu'il ne connaît pas plutôt que de deviner —
     deviner produirait des nombres, et des nombres faux sont pires que pas de
     nombres. */
  const TRACE_SCHEMA='jarvis.barehands.trace';
  const TRACE_SCHEMA_VERSION=1;

  const DEFAULTS=Object.freeze({
    /* Échéance d'un enregistrement. Il s'arrête **tout seul** : un
       enregistrement sans fin est exactement l'état que la RÈGLE ZÉRO
       interdit, et il l'est deux fois quand ce qui dure est une observation. */
    maxDurationMs:120000,
    /* Cadence d'échantillonnage. `0` veut dire « chaque image ». Au-dessus,
       une image sur N : une trace de deux minutes à 60 images par seconde
       pèse sinon 7200 images, ce que personne ne relit. */
    sampleEveryMs:0,
    /* Le plafond dur. Atteint, l'enregistrement **s'arrête et le dit** : une
       trace tronquée en silence se relit comme une séance courte, et on
       conclurait sur ce que l'utilisateur n'a pas fait. */
    maxFrames:9000,
  });

  function options(overrides){
    const o={...DEFAULTS,...(overrides||{})};
    for(const key of ['maxDurationMs','sampleEveryMs','maxFrames']){
      const n=Number(o[key]);
      if(!Number.isFinite(n))throw new RangeError(`createRecorder : « ${key} » doit être un nombre fini`);
      o[key]=n;
    }
    if(!(o.maxDurationMs>0))
      throw new RangeError('maxDurationMs doit être strictement positif : un enregistrement qui ne peut pas durer s’annonce quand même à l’écran');
    if(!(o.sampleEveryMs>=0))
      throw new RangeError('sampleEveryMs doit être positif ou nul (nul = chaque image)');
    /* **Paire dangereuse n° 15.** La cadence d'échantillonnage au-dessus de
       l'échéance : l'enregistrement dit qu'il tourne, s'arrête au bout de son
       temps, et rend **une seule image**. Toutes les mesures du rejeu seraient
       alors nulles ou dégénérées, et le banc d'essai conclurait « cette
       configuration est mauvaise » là où rien n'a été mesuré — la forme exacte
       que cette tâche a déjà vue huit fois : une combinaison qui ne peut pas
       marcher échoue en se lisant « l'utilisateur s'y prend mal ». */
    if(o.sampleEveryMs>0&&!(o.sampleEveryMs<o.maxDurationMs))
      throw new RangeError('sampleEveryMs doit rester sous maxDurationMs : au-dessus, tout l’enregistrement ne retient qu’une image, chaque mesure du rejeu est nulle ou dégénérée, et le banc d’essai accuse une configuration là où rien n’a été mesuré');
    if(!(o.maxFrames>0&&Number.isInteger(o.maxFrames)))
      throw new RangeError('maxFrames doit être un entier strictement positif');
    /* **Paire dangereuse n° 16.** Le plafond d'images en dessous de ce que
       l'échéance annoncée réclame : l'écran promet deux minutes, le plafond
       tombe au bout de vingt secondes, et la trace se relit comme une séance
       courte — on conclut sur ce que l'utilisateur n'a pas fait plutôt que sur
       ce qu'il a fait. Même espèce que `watchdogMs >= stepTimeoutMs` : le
       budget accordé doit couvrir le temps exigé. */
    const needed=o.sampleEveryMs>0?Math.ceil(o.maxDurationMs/o.sampleEveryMs):1;
    if(o.maxFrames<needed)
      throw new RangeError(`maxFrames (${o.maxFrames}) doit couvrir l’échéance annoncée (${needed} images pour ${o.maxDurationMs} ms à une image toutes les ${o.sampleEveryMs} ms) : en dessous, l’enregistrement se coupe avant la fin qu’il affiche et la trace se relit comme une séance courte`);
    return Object.freeze(o);
  }

  /* ------------------------------------------------------------------ 2
     Ce qu'une trace a le droit de porter, et rien d'autre.

     Quatre formes, quatre listes blanches. Chaque `BLANK` est la **seule
     source de vérité** du balayage de `assertDerivedOnly` : une clé ajoutée
     ici y passe sans qu'on y repense, et une clé ajoutée ailleurs ne passe
     nulle part. */
  /* **`Number(null)` vaut zéro, et zéro est une mesure.** C'est la leçon que
     cette tâche a payée deux fois — un profil « calibré au plancher » parce
     qu'une clé était absente — et elle mord ici deux fois plus fort, parce que
     le rejeu **relit** une trace déjà écrite : sans cette garde, une absence
     devenait zéro au second passage, et `stillness:null` se lisait « la main
     bougeait », `quality:null` « la main était mauvaise ». Une absence reste
     une absence, à chaque lecture. Un booléen n'est pas un nombre non plus :
     `Number(true)` vaut 1. */
  const num=value=>{
    if(value===null||value===undefined||value===''||typeof value==='boolean')return null;
    const n=Number(value);
    return Number.isFinite(n)?n:null;
  };
  const count=value=>{const n=num(value);return n!==null&&n>0?Math.floor(n):0};
  const flag=value=>value===true;
  const word=(value,vocabulary)=>vocabulary.includes(value)?value:null;

  /* Une main, réduite à ses scalaires dérivés. C'est **exactement** ce que la
     couture `deps.onMeasure` produit déjà (§10) : l'enregistreur n'élargit
     rien, il recopie moins. */
  const BLANK_HAND=Object.freeze({slot:0,handedness:null,
    primaryRatio:null,secondaryRatio:null,cPose:null,closure:null,
    gapPalms:null,indexReachPalms:null,palmNorm:null,
    rawX:null,rawY:null,filteredX:null,filteredY:null,palmX:null,palmY:null,
    quality:null,stillness:null,speedPxPerSec:null});
  function readHand(raw,index){
    const source=raw&&typeof raw==='object'?raw:{};
    /* **La fente portée, pas le rang dans le tableau.** `handTrackId` est une
       poignée de corrélation et n'entre pas ici ; la **fente** qui l'accompagne
       est dérivée, non identifiante, et c'est tout ce dont le rejeu a besoin —
       savoir que c'est « la même main qu'à l'image d'avant ».

       Le rang, lui, ne le dit pas : le traqueur renumérote ses mains quand
       l'une sort du cadre, et la voie du filtre se retrouvait nourrie par
       l'autre main. La fente vient donc de `createSlotAllocator` en amont
       (`control_center_barehands.js`, `traceFrame`), qui la garde stable tant
       que la main vit.

       Relire une trace déjà normalisée rend la même fente : elle est lue dans
       `source.slot`, où la passe précédente l'a écrite. L'idempotence de
       `readFrame` tient donc toujours. */
    const lane=num(source.slot);
    const carried=lane!==null&&Number.isInteger(lane)&&lane>=0&&lane<BH.MAX_HANDS;
    return {
      /* Sans fente portée — main surnuméraire, identité illisible — le rang
         reste le dernier recours : une fente fausse vaut mieux qu'une image
         perdue, et c'est le cas que le tableau ne distingue de toute façon
         pas. */
      slot:carried?lane:count(index),
      handedness:word(String(source.handedness),BH.HANDEDNESSES),
      primaryRatio:num(source.primaryRatio),secondaryRatio:num(source.secondaryRatio),
      cPose:num(source.cPose),closure:num(source.closure),
      gapPalms:num(source.gapPalms),indexReachPalms:num(source.indexReachPalms),
      palmNorm:num(source.palmNorm),
      rawX:num(source.rawX),rawY:num(source.rawY),
      filteredX:num(source.filteredX),filteredY:num(source.filteredY),
      palmX:num(source.palmX),palmY:num(source.palmY),
      quality:num(source.quality),stillness:num(source.stillness),
      speedPxPerSec:num(source.speedPxPerSec),
    };
  }

  /* **Le vocabulaire de types de cible, à nous et fermé.** Le contrat laisse
     `kind` en texte libre — `String(source.kind||'unknown')` — parce qu'un
     composant le renseigne et que le résolveur n'a pas à juger ce qu'on lui
     dit. Une trace, si : un type libre est la porte par laquelle un libellé,
     un nom de fichier ou une phrase d'utilisateur entrerait. Ce qui n'est pas
     dans cette table devient `other` — pas `null`, parce que « il y avait une
     candidate d'un type que je ne nomme pas » et « il n'y avait pas de
     candidate » ne sont pas la même chose. Un test de parité la compare à
     `JarvisBarehandsTarget.KINDS` : un type ajouté d'un côté seulement tombe. */
  const TRACE_KIND_OTHER='other';
  const TRACE_KINDS=Object.freeze(['scene_object','link','button','tab','field',
    'card','notice','control','unknown',TRACE_KIND_OTHER]);

  /* Une candidate de cible : de la **géométrie** et trois mots de vocabulaires
     fermés. Pas d'`objectId`, pas de libellé, pas de texte — le résolveur a
     besoin de rectangles, pas de savoir ce qui est écrit dessus. `ref` est un
     rang dans la trace : il porte la continuité d'une capture et ne veut rien
     dire hors d'elle. */
  const BLANK_CANDIDATE=Object.freeze({ref:0,kind:null,region:null,representation:null,
    actionable:false,x:null,y:null,w:null,h:null});
  function readCandidate(raw,ref){
    const source=raw&&typeof raw==='object'?raw:{};
    /* **La lecture est idempotente**, et ce n'est pas une élégance.
       La page envoie la géométrie dans `boundsPx` (c'est la forme du contrat
       §6) ; une trace, elle, la porte à plat. Le rejeu relit une trace **déjà
       normalisée** — c'est ce qui fait que la liste blanche protège aussi le
       disque et le réseau — donc une lecture qui ne connaîtrait que `boundsPx`
       rendrait quatre `null` et le résolveur ne verrait plus aucune cible.
       Mesuré : `click.target_success_ratio` tombait à 0 sur la trace d'or,
       c'est-à-dire qu'une mesure disait « aucun clic n'a atteint sa cible »
       d'une séance où tous l'avaient atteinte. Une lecture qui ne peut pas se
       relire elle-même n'est pas une liste blanche, c'est un convertisseur. */
    const box=source.boundsPx&&typeof source.boundsPx==='object'?source.boundsPx:source;
    return {
      ref:count(ref),
      kind:TRACE_KINDS.indexOf(source.kind)>=0?source.kind:TRACE_KIND_OTHER,
      region:word(source.region,BH.REGIONS),
      representation:word(source.representation,BH.ZONED_REPRESENTATIONS),
      actionable:flag(source.actionable),
      x:num(box.x),y:num(box.y),w:num(box.w),h:num(box.h),
    };
  }

  /* Un geste global. Deux vocabulaires fermés et un booléen : `suppressed`
     dit qu'il a été **étouffé** parce qu'une capture était tenue, ce que
     l'architecture §4 exige et ce qui, compté, est exactement le taux de faux
     gestes que la Slice demande de mesurer. */
  const BLANK_GESTURE=Object.freeze({name:null,phase:null,suppressed:false});
  function readGesture(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    return {
      name:word(source.name,BH.GESTURES),
      phase:word(source.phase,BH.GESTURE_PHASES),
      suppressed:flag(source.suppressed),
    };
  }

  /* Une issue d'interaction. Même réduction que le tutoriel : le **type**, le
     **canal**, le fait qu'elle portait un objet (un booléen, jamais
     l'identifiant) et le **nombre** d'axes contraints. */
  const BLANK_EVENT=Object.freeze({type:null,channel:null,onObject:false,axes:0});
  function readEvent(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    /* Idempotent, pour la même raison que `readCandidate` : la page envoie
       `objectId` et une liste d'axes, une trace porte un booléen et un compte.
       Sans les deux lectures, relire une trace ferait dire à chaque issue
       qu'elle ne portait aucun objet — et l'étape « déplacer une étoile » du
       banc d'essai se lirait comme jamais réussie. */
    return {
      type:word(source.type,BH.INTERACTIONS),
      channel:word(source.channel,BH.PINCH_CHANNELS),
      onObject:source.onObject===true
        ||(source.objectId!==null&&source.objectId!==undefined&&String(source.objectId)!==''),
      axes:count(Array.isArray(source.axes)?source.axes.length:source.axes),
    };
  }

  /* Une image de trace. `t` est **relatif au début de l'enregistrement** :
     une heure murale n'apprend rien au rejeu et dit quand quelqu'un était
     devant sa machine. */
  const BLANK_FRAME=Object.freeze({t:0,lifecycle:null,hands:[],candidates:[],
    events:[],gestures:[]});
  const listOf=value=>Array.isArray(value)?value:[];
  function readFrame(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    return {
      t:Math.max(0,num(source.t)||0),
      lifecycle:word(source.lifecycle,BH.LIFECYCLES),
      hands:listOf(source.hands).slice(0,BH.MAX_HANDS).map((hand,index)=>readHand(hand,index)),
      candidates:listOf(source.candidates).map((candidate,index)=>readCandidate(candidate,index)),
      events:listOf(source.events).map(readEvent),
      gestures:listOf(source.gestures).map(readGesture),
    };
  }

  /* ------------------------------------------------------------------ 3
     La garde de forme, au **chargement du module**.

     Même idiome qu'`assertDerivedOnly` (§10) et qu'`assertTeachingOnly` (§13),
     et pilotée par le schéma pour la même raison : une trace remplie à la main
     ne dirait rien d'une clé que personne n'aurait pensé à remplir. */
  const POISON=Object.freeze([
    /* Une suite de points : la main reconstruite. */
    [{x:.1,y:.2,z:.3},{x:.4,y:.5,z:.6}],
    /* Une image. */
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==',
    /* Un objet libre, où tout peut passer. */
    {frame:{width:640,height:480},pixels:[1,2,3],label:'Mot de passe'},
  ]);
  const looksRaw=value=>{
    if(value===null||value===undefined)return false;
    if(typeof value==='object')return true;
    /* Une chaîne longue n'est jamais un mot de vocabulaire fermé : c'est du
       texte libre, et du texte libre est exactement ce qui transporte du
       contenu d'utilisateur. */
    return typeof value==='string'&&value.length>32;
  };
  function offend(where,key,left){
    throw new RangeError(`JarvisBarehandsRecorder : ${where}.${key} laisse passer `
      +`${typeof left==='object'?'une structure':'une chaîne'} au lieu d’un nombre, d’un booléen ou d’un nom du vocabulaire. `
      +'Une trace n’a le droit de porter que des faits dérivés (décision 32) : ni points de main, ni image, ni objet libre. La liste blanche doit réduire cette clé.');
  }
  function sweep(where,shape,read){
    for(const poison of POISON)
      for(const key of Object.keys(shape)){
        const read_=read({...shape,[key]:poison});
        for(const name of Object.keys(read_))
          if(looksRaw(read_[name]))offend(where,name,read_[name]);
      }
  }
  function assertDerivedOnly(){
    sweep('hand',BLANK_HAND,raw=>readHand(raw,0));
    sweep('candidate',BLANK_CANDIDATE,raw=>readCandidate({...raw,boundsPx:raw},0));
    sweep('event',BLANK_EVENT,readEvent);
    sweep('gesture',BLANK_GESTURE,readGesture);
    /* L'image, dont trois clés portent des **listes** : le balayage plat
       ci-dessus les verrait comme des structures. On lit donc chaque élément. */
    for(const poison of POISON)
      for(const key of Object.keys(BLANK_FRAME)){
        const frame=readFrame({...BLANK_FRAME,[key]:poison});
        for(const name of ['t','lifecycle'])
          if(looksRaw(frame[name]))offend('frame',name,frame[name]);
        for(const list of ['hands','candidates','events','gestures'])
          for(const item of frame[list])
            for(const name of Object.keys(item))
              if(looksRaw(item[name]))offend(`frame.${list}[]`,name,item[name]);
      }
    /* **Les jumelles bien formées**, et c'est la leçon de la reprise de la
       Slice 08 : une sonde qui peut être refusée en chemin mesure le chemin
       au lieu de la porte. Les trois formes ci-dessous sont **valides** —
       rien ne peut les rejeter avant la garde — et portent le poison dans la
       seule poche imbriquée du schéma (`boundsPx`) et dans les deux listes
       que l'image transporte. */
    for(const poison of POISON){
      const frame=readFrame({t:12,lifecycle:BH.LIFECYCLE.ACTIVE,
        hands:[{handedness:'left',primaryRatio:.4,quality:.9,leak:poison}],
        candidates:[{kind:'button',region:BH.REGION.BODY,
          boundsPx:{x:1,y:2,w:3,h:4,leak:poison},leak:poison}],
        events:[{type:BH.INTERACTION.CLICK,channel:'primary',axes:[],leak:poison}],
        gestures:[{name:BH.GESTURE.C_POSE,phase:'start',suppressed:true,leak:poison}]});
      for(const list of ['hands','candidates','events','gestures'])
        for(const item of frame[list])
          for(const name of Object.keys(item))
            if(looksRaw(item[name]))offend(`frame.${list}[] (jumelle)`,name,item[name]);
    }
    return true;
  }

  /* ------------------------------------------------------------------ 4
     L'enregistreur.

     Rien ne tourne tant que l'utilisateur ne l'a pas demandé, tout s'arrête
     quand il a fini, et l'écran dit lequel des deux est vrai. */

  /* **Les seules dépendances qu'un enregistreur peut recevoir** — une liste
     blanche, comme le tutoriel depuis la Slice 10, et pour la même raison :
     la question n'est pas « ce nom est-il interdit ? » mais « ce nom est-il au
     contrat ? ». Aucune des six ne peut transporter une image, une vidéo ni un
     point de main. */
  const ALLOWED=Object.freeze(['options','now','log','onStop','setTimeout','clearTimeout']);

  function createRecorder(deps){
    const d=deps&&typeof deps==='object'?deps:{};
    for(const name of Object.keys(d))
      if(d[name]!==undefined&&ALLOWED.indexOf(name)<0){
        const error=new RangeError(`createRecorder refuse la dépendance « ${name} » : elle n’est pas au contrat §14 (${ALLOWED.join(', ')}). Une trace ne porte que des faits dérivés (décision 32), et une couture capable de transporter une image, une vidéo ou une suite de points rendrait cette garantie déclarative au lieu de structurelle`);
        error.code='barehands_trace_cannot_carry_raw_input';
        throw error;
      }
    /* **L'échéance est exigée à la construction**, et c'est la même leçon que
       l'horloge de la calibration : un enregistrement qui ne peut pas
       s'arrêter tout seul dépend de quelqu'un qui pense à l'arrêter. Ce qui
       observe et que personne n'arrête est précisément ce que la décision 32
       interdit d'installer. */
    if(typeof d.setTimeout!=='function'||typeof d.clearTimeout!=='function')
      throw new RangeError('createRecorder exige `setTimeout`/`clearTimeout` : un enregistrement qui ne peut pas s’arrêter tout seul dure tant que personne n’y pense, et ce qui observe sans fin est exactement ce que la décision 32 interdit');
    const o=options(d.options);
    const now=typeof d.now==='function'?d.now:()=>Date.now();
    const say=typeof d.log==='function'?d.log:()=>{};

    let recording=false,startedAt=0,frames=null,lastAt=null,seen=0,dropped=0;
    let viewport=null,deadline=0,timer=null,stopped=null;

    function finish(reason){
      if(!recording)return null;
      recording=false;
      if(timer!==null){d.clearTimeout(timer);timer=null}
      const trace=Object.freeze({
        schema:TRACE_SCHEMA,schemaVersion:TRACE_SCHEMA_VERSION,
        /* **Pas l'heure murale.** `startedAt` est gardé en mémoire pour dater
           les images les unes par rapport aux autres et pour armer l'échéance,
           mais il ne part **pas** dans la trace : c'est exactement l'argument
           qui rend `t` relatif un peu plus bas — une heure murale n'apprend
           rien au rejeu et dit quand quelqu'un était devant sa machine. La clé
           reste, à zéro, parce que le schéma, le contrat et la liste blanche
           du serveur la nomment ; sa valeur, elle, n'a jamais servi au rejeu,
           qui ne lit que `t` et `durationMs`. La trace d'or ne l'avait pas
           montré : elle est synthétique. */
        startedAt:0,durationMs:Math.max(0,(lastAt===null?startedAt:lastAt)-startedAt),
        stoppedBecause:reason,
        viewport:viewport||{width:0,height:0},
        options:{sampleEveryMs:o.sampleEveryMs,maxDurationMs:o.maxDurationMs,maxFrames:o.maxFrames},
        /* `seen` compte les images **présentées**, `frames.length` celles
           retenues, `dropped` celles refusées par le plafond. Les trois, parce
           qu'une trace qui ne dirait que la dernière laisserait « la main n'a
           pas bougé » et « on a arrêté d'enregistrer » s'écrire pareil. */
        observedFrames:seen,droppedFrames:dropped,
        frames:frames.slice(),
      });
      stopped=trace;
      frames=null;
      say('info','[barehands] enregistrement terminé',
        {frames:trace.frames.length,observed:seen,dropped,because:reason});
      if(typeof d.onStop==='function'){
        try{d.onStop(trace)}
        catch(error){
          /* Un lecteur qui lève ne doit pas emporter la trace : elle est déjà
             complète, et la perdre ici perdrait la séance de l'utilisateur.
             Même règle que le dépôt de reçu de la Slice 12. */
          say('warn','[barehands] enregistrement : le lecteur de fin a levé',
            {error:String(error&&error.message||error)});
        }
      }
      return trace;
    }

    const api={
      isRecording(){return recording},
      /* Ce que l'écran doit afficher **pendant** : la RÈGLE ZÉRO demande que
         ça dise que ça tourne, quoi, depuis combien de temps, et comment en
         sortir. Les trois premiers sont ici ; le quatrième est le bouton. */
      state(){
        return {recording,frames:frames?frames.length:(stopped?stopped.frames.length:0),
          observed:seen,dropped,
          elapsedMs:recording?Math.max(0,now()-startedAt):(stopped?stopped.durationMs:0),
          remainingMs:recording?Math.max(0,deadline-now()):0,
          maxFrames:o.maxFrames,maxDurationMs:o.maxDurationMs};
      },
      /* La dernière trace terminée, relisible sans l'avoir attrapée au vol. */
      trace(){return stopped},
      start(spec){
        if(recording)return {ok:true,already:true,startedAt};
        const s=spec&&typeof spec==='object'?spec:{};
        const box=s.viewport&&typeof s.viewport==='object'?s.viewport:{};
        viewport={width:num(box.width)||0,height:num(box.height)||0};
        /* **L'arrêt automatique s'arme d'abord**, et `recording` ne passe à
           vrai qu'ensuite. Dans l'autre ordre, une horloge qui lève laissait
           un enregistrement « en cours » sans échéance — c'est-à-dire une
           observation que plus rien ne peut arrêter, exactement ce que
           l'exigence de `setTimeout` à la construction existe pour empêcher,
           contournée par le seul chemin qu'elle ne couvrait pas. Mesuré : la
           page rendait `{ok:false}` et `state().recording` valait quand même
           vrai. Il ne dépend pas des images : une caméra figée laisserait
           sinon l'enregistrement en cours pour toujours. */
        const at=now();
        const armed=d.setTimeout(()=>{timer=null;finish('deadline')},o.maxDurationMs);
        startedAt=at;lastAt=null;frames=[];seen=0;dropped=0;stopped=null;
        deadline=startedAt+o.maxDurationMs;
        timer=armed;
        recording=true;
        say('info','[barehands] enregistrement démarré',
          {maxDurationMs:o.maxDurationMs,maxFrames:o.maxFrames,sampleEveryMs:o.sampleEveryMs});
        return {ok:true,startedAt,maxDurationMs:o.maxDurationMs,maxFrames:o.maxFrames};
      },
      stop(){return finish('asked')},
      /* Une image. Rend `true` si elle a été retenue — pas si elle a été
         reçue : les deux ne veulent pas dire la même chose au plafond. */
      feed(raw){
        if(!recording)return false;
        seen+=1;
        const at=now();
        if(o.sampleEveryMs>0&&lastAt!==null&&at-lastAt<o.sampleEveryMs)return false;
        if(frames.length>=o.maxFrames){
          dropped+=1;
          /* **Le plafond arrête, il ne tronque pas en silence.** Une trace
             coupée sans le dire se relit comme une séance courte, et on
             conclurait sur ce que l'utilisateur n'a pas fait. */
          say('warn','[barehands] enregistrement : plafond d’images atteint',
            {maxFrames:o.maxFrames});
          finish('max_frames');
          return false;
        }
        lastAt=at;
        const frame=readFrame({...(raw&&typeof raw==='object'?raw:{}),t:at-startedAt});
        frames.push(frame);
        return true;
      },
    };
    return api;
  }

  /* ------------------------------------------------------------------ 5
     Le rejeu.

     **Il ne réimplante rien.** Les moteurs du rejeu sont les **vrais** :
     `createPointerFilter`, `createPinchChannel` et `createTargetResolver` du
     bloc pur, reçus par `deps.core`. Un rejeu qui referait le filtre ou
     l'hystérésis dans son coin mesurerait sa propre copie, et le jour où les
     deux divergeraient c'est le banc d'essai qui aurait raison contre le
     produit — la panne la plus coûteuse possible pour un outil de réglage.

     Le `core` est **reçu** plutôt que lu dans un global parce que ce module
     est chargé avant lui dans la page et séparément sous node : aller le
     chercher marcherait à un endroit et pas à l'autre.

     **Déterminisme.** Le rejeu n'a ni horloge, ni hasard, ni réseau, ni DOM :
     il lit les horodatages de la trace. Deux exécutions de la même trace sous
     la même configuration rendent des nombres identiques au bit près, ce
     qu'un test affirme en les comparant. */
  const REPLAY_AXES=Object.freeze(['filter','thresholds','assistance','resolver']);
  /* Le défaut du contrat §9 : `0,5` rend exactement `targetAssistPx`. */
  const DEFAULT_ASSISTANCE=.5;

  function replay(trace,config,deps){
    const d=deps&&typeof deps==='object'?deps:{};
    const core=d.core;
    if(!core||typeof core.createPointerFilter!=='function'||typeof core.createPinchChannel!=='function')
      throw new RangeError('replay exige `core` (JarvisBarehandsCore) : le rejeu se fait avec les **vrais** moteurs, sinon il mesure une copie qui divergera du produit');
    const doc=trace&&typeof trace==='object'?trace:{};
    if(doc.schema!==TRACE_SCHEMA){
      const error=new RangeError(`replay : ce document n’est pas une trace Bare Hands (schema « ${String(doc.schema)} »)`);
      error.code='barehands_trace_schema_unknown';
      throw error;
    }
    /* **Une version inconnue se refuse, elle ne se devine pas.** Deviner
       produirait des nombres, et des nombres faux sont pires que pas de
       nombres — c'est la règle de ce dépôt (un refus codé plutôt qu'un défaut
       plausible), appliquée à un banc d'essai. */
    if(doc.schemaVersion!==TRACE_SCHEMA_VERSION){
      const error=new RangeError(`replay : trace en version ${String(doc.schemaVersion)}, ce Jarvis lit la version ${TRACE_SCHEMA_VERSION}. Rejouer une version inconnue produirait des nombres sans rapport avec ce qui a été enregistré.`);
      error.code='barehands_trace_version_unsupported';
      throw error;
    }
    const frames=Array.isArray(doc.frames)?doc.frames:[];
    const c=config&&typeof config==='object'?config:{};

    /* **Un réglage mal orthographié se refuse, il ne s'ignore pas.**

       Le refus d'un *axe* inconnu existait déjà, et son propre argument vaut un
       cran plus bas : accepter une clé sans effet « ferait lire deux colonnes
       identiques comme *ce réglage ne change rien* ». Or les moteurs reçoivent
       leurs options par `{...DEFAULTS, ...overrides}` : une clé inconnue y
       était avalée en silence, donc `thresholds.pinchMargnRatio` (faute de
       frappe) était accepté, rejoué, et rendait les nombres du défaut.

       `core.DEFAULTS` est la seule liste de noms qui existe, et c'est celle que
       les moteurs lisent vraiment — la recopier ici en ferait une seconde, qui
       divergerait. */
    /* **L'axe inconnu se refuse ici aussi.** `REPLAY_AXES` était déclaré et
       exporté par ce module, mais n'était lu par personne : seul le miroir
       Python (`barehands_replay._check_config`) refusait un axe. Un appelant
       JS — ou n'importe quel test passant par cette fonction — pouvait donc
       poser `{filtre:{…}}` et lire des nombres qui n'étaient que le défaut.
       Deux miroirs qui ne refusent pas la même chose ne sont pas deux miroirs. */
    const unknownAxes=Object.keys(c).filter(axis=>!REPLAY_AXES.includes(axis));
    if(unknownAxes.length)
      throw new RangeError(`replay : axe de rejeu inconnu : ${unknownAxes.join(', ')}. `
        +`Les axes sont ${REPLAY_AXES.join(', ')} — accepter une clé sans effet ferait lire `
        +'deux colonnes identiques comme « ce réglage ne change rien ».');

    const knobs=(core.DEFAULTS&&typeof core.DEFAULTS==='object')?core.DEFAULTS:null;
    const checkKnobs=(axis,value)=>{
      if(!knobs||!value||typeof value!=='object')return;
      const unknown=Object.keys(value).filter(key=>!(key in knobs));
      if(unknown.length)
        throw new RangeError(`replay : réglage inconnu sur l’axe « ${axis} » : ${unknown.join(', ')}. `
          +'Un nom que le moteur ne lit pas rendrait les nombres du défaut, et deux colonnes '
          +'identiques se liraient « ce réglage ne change rien ».');
    };
    checkKnobs('filter',c.filter);
    checkKnobs('thresholds',c.thresholds);
    checkKnobs('resolver',c.resolver);

    const filterOptions=c.filter&&typeof c.filter==='object'?c.filter:{};
    const thresholds=c.thresholds&&typeof c.thresholds==='object'?c.thresholds:{};
    /* **L'assistance a un défaut, et le résolveur tourne toujours.**
       Tant qu'une assistance absente coupait le résolveur, `targets` retombait
       sur « combien de candidates existaient » — qui n'est pas « combien ont
       été résolues ». `click.target_success_ratio` valait alors 1 gratuitement
       dès qu'on ne configurait pas cet axe : une mesure qui dit « tous les
       clics ont atteint leur cible » parce que personne ne l'a mesurée est
       pire qu'une mesure absente, parce qu'elle est crue. Le défaut est celui
       du moteur (contrat §9) ; qui veut couper l'aide passe `0`, ce qui est un
       réglage et non une absence de mesure. */
    const assistance=c.assistance===undefined||c.assistance===null
      ?DEFAULT_ASSISTANCE:Number(c.assistance);

    /* Une fente, un filtre, deux canaux : le rejeu reconstruit par main ce que
       la page construit par main. */
    const lanes=new Map();
    const laneFor=slot=>{
      let lane=lanes.get(slot);
      if(!lane){
        lane={
          filter:core.createPointerFilter(filterOptions),
          primary:core.createPinchChannel(core.PINCH_CHANNEL.PRIMARY,thresholds),
          secondary:core.createPinchChannel(core.PINCH_CHANNEL.SECONDARY,thresholds),
          lastSeenAt:null,lostFrom:null,
        };
        lanes.set(slot,lane);
      }
      return lane;
    };
    if(typeof core.createTargetResolver!=='function')
      throw new RangeError('replay exige `core.createTargetResolver` : sans résolveur, « combien de candidates existaient » se compterait pour « combien ont été résolues », et le taux de clics visés vaudrait 1 sans que rien ne l’ait mesuré');
    const resolver=core.createTargetResolver({pickRegion:BH.pickRegion,...(c.resolver||{})});

    const out=[];
    for(const raw of frames){
      const frame=readFrame(raw);
      const hands=[];
      for(const hand of frame.hands){
        const lane=laneFor(hand.slot);
        let filtered=null;
        if(hand.rawX!==null&&hand.rawY!==null){
          try{filtered=lane.filter.update({x:hand.rawX,y:hand.rawY},frame.t)}
          catch(_error){
            /* Un point inutilisable dans une trace n'arrête pas un rejeu : il
               vaut « rien vu » pour cette image, et le compte d'images
               mesurées le dira. */
            filtered=null;
          }
        }
        const sampleAt={handTrackId:`slot${hand.slot}`,quality:hand.quality,
          x:filtered?filtered.x:hand.rawX,y:filtered?filtered.y:hand.rawY,
          palmX:hand.palmX,palmY:hand.palmY,
          anchorX:filtered?filtered.x:hand.rawX,anchorY:filtered?filtered.y:hand.rawY,
          /* ⚠️ **`confidence` est ici la qualité de suivi, pas la confiance du
             moteur réel**, qui la dérive de la marge de pincement et de
             l'ouverture de la main. C'est la raison pour laquelle
             `thresholds.pinchMarginRatio` est **structurellement inerte au
             rejeu** : balayé de 0,0 à 0,9 sur la trace d'or, il ne déplace
             aucune mesure. Son nom est pourtant valide (il est dans
             `core.DEFAULTS`), donc la garde de noms ci-dessus ne peut pas le
             signaler — un réglage inerte n'est pas un réglage mal écrit.

             Récupérable sans points de main : la trace porte `closure`, dont
             l'ouverture se dérive. Non fait ici — cela changerait les nombres
             de la trace d'or, donc l'empreinte du verrou du Test Lab et les
             seuils des assertions, au moment de clore la tâche. Tracé.

             Même statut pour `resolver.targetZonePx` et `targetZoneHoldPx` :
             valides, acceptés, sans effet sur aucune mesure de cette trace. */
          stillness:hand.stillness,now:frame.t,confidence:hand.quality};
        const primary=hand.primaryRatio===null?null
          :lane.primary.update({...sampleAt,ratio:hand.primaryRatio,other:hand.secondaryRatio});
        const secondary=hand.secondaryRatio===null?null
          :lane.secondary.update({...sampleAt,ratio:hand.secondaryRatio,other:hand.primaryRatio});
        hands.push({slot:hand.slot,handedness:hand.handedness,
          rawX:hand.rawX,rawY:hand.rawY,
          filteredX:filtered?filtered.x:null,filteredY:filtered?filtered.y:null,
          recordedFilteredX:hand.filteredX,recordedFilteredY:hand.filteredY,
          speedPxPerSec:filtered?filtered.speedPxPerSec:hand.speedPxPerSec,
          stillness:hand.stillness,quality:hand.quality,
          primary:eventsOf(primary),secondary:eventsOf(secondary)});
      }
      /* `null` quand il n'y avait **aucune candidate à résoudre** : c'est une
         absence, pas un échec de visée. Zéro quand il y en avait et qu'aucune
         n'a été atteinte : ça, c'en est un. */
      let targets=null;
      if(frame.candidates.length){
        targets=resolver.update({now:frame.t,
          candidates:frame.candidates.map(candidate=>({objectId:`ref${candidate.ref}`,
            kind:candidate.kind,region:candidate.region,
            representation:candidate.representation,
            actionable:candidate.actionable,
            boundsPx:{x:candidate.x,y:candidate.y,w:candidate.w,h:candidate.h}})),
          hands:hands.filter(hand=>hand.filteredX!==null).map(hand=>({
            handTrackId:`slot${hand.slot}`,channel:core.PINCH_CHANNEL.PRIMARY,
            state:'pinching',x:hand.filteredX,y:hand.filteredY,assistance}))});
      }
      out.push({t:frame.t,lifecycle:frame.lifecycle,hands,
        targets:targets===null?null:targets.length,
        candidates:frame.candidates.length,
        events:frame.events,gestures:frame.gestures});
    }
    return {schemaVersion:TRACE_SCHEMA_VERSION,
      config:{filter:{...filterOptions},thresholds:{...thresholds},assistance},
      viewport:doc.viewport||{width:0,height:0},
      durationMs:num(doc.durationMs)||0,
      frames:out};
  }
  /* `createPinchChannel.feed` rend un tableau d'événements ou rien ; on
     normalise une fois plutôt qu'à chaque lecture. */
  function eventsOf(answer){
    if(!answer)return [];
    if(Array.isArray(answer))return answer;
    return [answer];
  }

  /* ------------------------------------------------------------------ 6
     Les mesures.

     **Un fait n'est pas un score**, et la Slice l'exige explicitement. Tout ce
     qui suit est un compte, un quantile ou un rapport de comptes : rien n'est
     pondéré, rien n'est noté. Une mesure qu'on ne peut pas établir rend
     `null` — jamais zéro, qui se lirait comme « mesuré, et parfait ». C'est la
     leçon `Number(null) === 0` de cette tâche, appliquée à un banc d'essai.

     L'unité des distances est la **fraction de la largeur d'image**, pas le
     pixel : c'est la seule qui survive à un changement de résolution, et c'est
     déjà le choix de `travelSlopNorm` (§10). */
  const METRIC_KEYS=Object.freeze(['replay.frames_count',
    'click.target_success_ratio',
    'pointer.error_p50_norm','pointer.error_p95_norm',
    'pointer.stationary_jitter_p95_norm',
    'pinch.false_primary_hz','pinch.false_secondary_hz','gesture.false_positive_hz',
    'interaction.latency_p50_ms','hand.loss_recovery_p95_ms',
    'drag.continuity_ratio','resize.two_hand_stability_ratio']);

  /* Le quantile **linéaire**, nommé et partagé : deux définitions de « p95 »
     dans un même dépôt rendent deux nombres sous un seul mot. */
  function quantile(values,q){
    const sorted=values.filter(Number.isFinite).slice().sort((a,b)=>a-b);
    if(!sorted.length)return null;
    if(sorted.length===1)return sorted[0];
    const at=(sorted.length-1)*q;
    const low=Math.floor(at),high=Math.ceil(at);
    return low===high?sorted[low]:sorted[low]+(sorted[high]-sorted[low])*(at-low);
  }
  const ratioOf=(part,whole)=>whole>0?part/whole:null;
  const perSecond=(n,ms)=>ms>0?n/(ms/1000):null;

  function metricsOf(replayed,spec){
    const r=replayed&&typeof replayed==='object'?replayed:{};
    const frames=Array.isArray(r.frames)?r.frames:[];
    const s=spec&&typeof spec==='object'?spec:{};
    /* La largeur d'image : l'unité de toutes les distances. Absente, les
       distances ne sont **pas** mesurées — les rendre en pixels sous un nom
       normalisé serait un mensonge d'unité, et c'est de cette espèce d'erreur
       que la Slice 04 a laissé une leçon. */
    const width=num((r.viewport||{}).width);
    const norm=width&&width>0?value=>value/width:()=>null;
    /* Au-dessus de quoi une main est « immobile ». C'est un seuil de lecture,
       pas une mesure : il est donc nommé, réglable et rapporté. */
    const stillAbove=s.stillAbove===undefined?.8:Number(s.stillAbove);
    /* Ce qui compte comme un pincement « faux » : un cycle appuyé-relâché plus
       court que ce temps n'a pas pu être voulu. */
    const spuriousMs=s.spuriousMs===undefined?80:Number(s.spuriousMs);
    /* Un clic « réussi » est un clic qui avait une cible sous la main. */
    let clicks=0,clicksOnTarget=0;
    const errors=[],jitter=[],recoveries=[],latencies=[];
    let falsePrimary=0,falseSecondary=0,falseGesture=0;
    let dragFrames=0,dragBreaks=0,resizeFrames=0,resizeBreaks=0;
    const pressFrom=new Map();
    const lastSeen=new Map();
    let wasDragging=false;

    for(const frame of frames){
      for(const hand of frame.hands){
        /* **Erreur de pointeur** : l'écart entre le point brut et le point
           filtré. C'est ce que le filtre a décidé de corriger, donc ce que
           changer le filtre change. */
        if(hand.rawX!==null&&hand.filteredX!==null){
          const dx=hand.filteredX-hand.rawX,dy=hand.filteredY-hand.rawY;
          const d=norm(Math.hypot(dx,dy));
          if(d!==null){
            errors.push(d);
            /* **Tremblement au repos** : la même distance, mais seulement
               quand la main ne bouge pas. Mélanger les deux ferait passer une
               main rapide pour une main qui tremble. */
            if(hand.stillness!==null&&hand.stillness>=stillAbove)jitter.push(d);
          }
        }
        /* **Reprise après perte de main** : le temps entre la dernière image
           où la fente était vue et celle où elle revient. */
        const previous=lastSeen.get(hand.slot);
        if(previous!==undefined&&frame.t-previous>0)
          if(frame.t-previous>(s.lossAboveMs===undefined?200:Number(s.lossAboveMs)))
            recoveries.push(frame.t-previous);
        lastSeen.set(hand.slot,frame.t);
        for(const channel of ['primary','secondary'])
          for(const event of hand[channel]){
            const key=`${hand.slot}|${channel}`;
            if(event.phase==='down')pressFrom.set(key,frame.t);
            if(event.phase==='up'||event.phase==='cancel'){
              const from=pressFrom.get(key);
              pressFrom.delete(key);
              if(from!==undefined){
                const held=frame.t-from;
                /* **Latence d'interaction** : du contact à l'issue.

                   ⚠️ **Ce n'est pas une latence système.** C'est la durée
                   pendant laquelle l'utilisateur a **tenu** son pincement :
                   un utilisateur qui appuie délibérément plus longtemps se lit
                   comme une latence pire, alors que rien n'a ralenti. Elle est
                   sensible aux seuils — c'est pourquoi elle reste utile comme
                   **proxy comparatif** entre deux configurations sur la même
                   trace, ce pour quoi le Test Lab s'en sert — mais son nom
                   promet ce qu'elle ne mesure pas. Non renommée ici pour la
                   même raison que `drag.continuity_ratio` : le nom voyage dans
                   le manifeste, l'empreinte du verrou et le contrat. Tracé. */
                latencies.push(held);
                /* **Faux pincement** : trop court pour avoir été voulu, ou
                   annulé. */
                if(held<spuriousMs||event.phase==='cancel'){
                  if(channel==='primary')falsePrimary+=1;else falseSecondary+=1;
                }
              }
            }
          }
      }
      /* **Clic visé** : une issue `click` avec au moins une candidate résolue
         sous la main à la même image.

         ⚠️ **Cette mesure ne peut pas récompenser un clic qui touche plus.**
         Les `candidates` d'une trace sont la sortie **déjà résolue** du
         résolveur (`targets(){return resolved}`, vide hors intention), et un
         clic dans le vide revient avant qu'aucune interaction ne soit
         enregistrée. Le dénominateur ne contient donc que des clics qui avaient
         déjà réussi à l'enregistrement : la mesure dit « parmi les clics qui
         réussissaient, combien le résolveur rejoué résout encore », et non
         « combien de clics atteignent leur cible ». Elle peut **baisser** —
         c'est ce qui la rend utile comme garde-fou de non-régression — elle ne
         peut pas monter en récompensant une meilleure visée.

         À savoir en la lisant, parce qu'elle porte une assertion **bloquante**
         à ≥ 0,6 (trace d'or : 0,667) : cette assertion garde une régression du
         résolveur, elle ne mesure pas la qualité de visée du produit. La
         corriger demanderait que la trace porte les candidates **offertes**,
         pas résolues — un changement de schéma, donc de version. Tracé. */
      let dragging=false,resizing=false;
      for(const event of frame.events){
        if(event.type===BH.INTERACTION.CLICK||event.type===BH.INTERACTION.CONTEXT){
          /* Un clic sans **aucune** candidate à l'écran n'est pas un clic
             manqué : il n'y avait rien à viser, et le compter ferait chuter
             une mesure de visée sur une image vide. */
          if(frame.targets===null)continue;
          clicks+=1;
          if(frame.targets>0)clicksOnTarget+=1;
        }
        if(event.type===BH.INTERACTION.DRAG_MOVE||event.type===BH.INTERACTION.DRAG_START)dragging=true;
        if(event.type===BH.INTERACTION.RESIZE)resizing=true;
      }
      /* **Faux geste** : un geste global **étouffé** parce qu'une capture
         était tenue. C'est ce que l'architecture §4 exige d'étouffer, donc
         c'est exactement ce qu'il faut compter : un geste qui, sans la garde,
         aurait volé l'entrée d'une manipulation en cours. */
      for(const gesture of frame.gestures||[])if(gesture.suppressed)falseGesture+=1;
      /* **Continuité d'un glissement** : une image de glissement qui suit une
         image de glissement est continue ; une interruption au milieu ne
         l'est pas. Le rapport est la part continue.

         ⚠️ **Ce que cette mesure compte vraiment, et son biais connu.** Une
         **reprise** compte comme une rupture, qu'elle vienne d'un accroc ou
         d'un second glissement parfaitement propre. Mesuré : un glissement
         continu rend 1.0 ; **deux glissements propres rendent 0.9** ; un seul
         glissement avec un vrai accroc rend 0.889. Une séance où l'utilisateur
         glisse plus souvent se note donc moins bien.

         Elle reste utile **à séance constante** — c'est ainsi que le Test Lab
         s'en sert, en comparant deux configurations sur la **même** trace, où
         le nombre de glissements est identique des deux côtés. Elle n'est pas
         comparable d'une séance à l'autre, et son nom ne le dit pas. Non
         renommée ici : le nom voyage dans le manifeste du diagnostic, dans
         l'empreinte du verrou du Test Lab et dans le contrat, et le
         changer au moment de clore la tâche coûterait plus que le biais
         lui-même. Tracé, à renommer avec la prochaine évolution du schéma. */
      if(dragging){dragFrames+=1;if(!wasDragging&&dragFrames>1)dragBreaks+=1}
      if(resizing){
        resizeFrames+=1;
        /* **Stabilité d'un redimensionnement à deux mains** : il faut deux
           mains vues à l'image pour qu'il soit stable. Une main perdue au
           milieu est la panne que la Slice 06 nomme. */
        if(frame.hands.length<2)resizeBreaks+=1;
      }
      wasDragging=dragging;
    }

    const durationMs=num(r.durationMs)||(frames.length?frames[frames.length-1].t:0);
    return Object.freeze({
      'replay.frames_count':frames.length,
      'click.target_success_ratio':ratioOf(clicksOnTarget,clicks),
      'pointer.error_p50_norm':quantile(errors,.5),
      'pointer.error_p95_norm':quantile(errors,.95),
      'pointer.stationary_jitter_p95_norm':quantile(jitter,.95),
      'pinch.false_primary_hz':perSecond(falsePrimary,durationMs),
      'pinch.false_secondary_hz':perSecond(falseSecondary,durationMs),
      'gesture.false_positive_hz':perSecond(falseGesture,durationMs),
      'interaction.latency_p50_ms':quantile(latencies,.5),
      'hand.loss_recovery_p95_ms':quantile(recoveries,.95),
      'drag.continuity_ratio':dragFrames?ratioOf(dragFrames-dragBreaks,dragFrames):null,
      'resize.two_hand_stability_ratio':resizeFrames?ratioOf(resizeFrames-resizeBreaks,resizeFrames):null,
    });
  }

  /* Rejouer **une** trace sous **plusieurs** configurations, et rendre les
     mesures côte à côte. C'est le critère d'acceptation de la Slice, en une
     fonction : « un développeur peut rejouer la même séance enregistrée sous
     au moins deux configurations et comparer des mesures objectives ». */
  function compare(trace,configs,deps){
    const list=Array.isArray(configs)?configs:[];
    if(list.length<2)
      throw new RangeError('compare exige au moins deux configurations : comparer une configuration à elle-même ne dit rien, et c’est exactement ce que cette Slice existe pour remplacer');
    return list.map(entry=>{
      const name=String((entry&&entry.name)||'sans nom');
      const replayed=replay(trace,entry&&entry.config,deps);
      return {name,config:replayed.config,metrics:metricsOf(replayed,entry&&entry.spec)};
    });
  }

  const api=Object.freeze({
    TRACE_SCHEMA,TRACE_SCHEMA_VERSION,DEFAULTS,options,
    BLANK_HAND,BLANK_CANDIDATE,BLANK_EVENT,BLANK_GESTURE,BLANK_FRAME,
    TRACE_KINDS,TRACE_KIND_OTHER,
    readHand,readCandidate,readEvent,readGesture,readFrame,assertDerivedOnly,
    createRecorder,replay,metricsOf,compare,quantile,METRIC_KEYS,REPLAY_AXES,
  });

  /* **La levée reste, mais elle ne sort pas d'ici** — même raisonnement que le
     tutoriel (§13) : la page servie n'a qu'une balise `<script>`, donc une
     levée non rattrapée au chargement y avorte tout ce qui suit. Rattrapée,
     la panne garde sa portée : **ce module ne s'installe pas**, le reste de
     Bare Hands vit, et la console porte la cause. `recorder()` refuse alors
     avec un code, et l'onglet le dit. */
  try{
    assertDerivedOnly();
    root.JarvisBarehandsRecorder=api;
    if(typeof module!=='undefined'&&module.exports)module.exports=api;
  }catch(error){
    console.error('[barehands] barehands.recorder_not_installed '
      +JSON.stringify({error:String(error&&error.message||error)}));
  }
})(typeof window!=='undefined'?window:globalThis);
