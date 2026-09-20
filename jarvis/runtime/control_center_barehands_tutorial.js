/* Bare Hands V1 — parcours de tutoriel (Slice 09).
   Architecture §13, décisions 6 et 26.

   **Décision 26 : deux parcours, une coque.** La coque de surimpression vit
   dans `control_center_barehands_calibration.js` (§11) et ne sait rien de ce
   qu'elle affiche — elle montre des étapes. Ce module la reprend **telle
   quelle**, sans en changer une ligne : il la reçoit construite
   (`deps.overlay`), exactement comme `createCalibration` la reçoit. Si le
   tutoriel avait eu besoin de la modifier, « deux parcours, une coque » aurait
   été une ressemblance et non un choix de produit.

   **Ce que ce module ne peut pas faire, et c'est structurel.**

   - Il ne peut pas écrire un paramètre de calibration : il n'a **aucune**
     dépendance d'écriture, et `createTutorial` *refuse à la construction*
     toute dépendance nommée `save`, `profile`, `saveProfile`, `measure` ou
     `onMeasure` (`barehands_tutorial_cannot_write_profile`). Une Slice
     ultérieure qui brancherait un écrivain de profil ici casse à la
     construction, pas trois écrans plus loin. C'est la même espèce de garde
     qu'`assertDerivedOnly` (§10) : une promesse sur ce que du code ne fera pas
     est plus faible qu'une couture qui ne peut pas le transporter.
   - Il ne peut pas conserver une image, une vidéo ni un point : ce qu'il
     reçoit n'est **pas** l'enregistrement de scalaires du contrôleur
     (décision 32, couture `deps.onMeasure`), c'est une **observation** encore
     plus pauvre — des booléens, des comptes et des noms d'un vocabulaire
     fermé. `readObservation` est une liste blanche, et `assertTeachingOnly`
     vérifie au chargement du module, clé par clé et pilotée par le schéma,
     qu'une suite de points, une image en base64 ou un objet libre n'en
     ressortent pas.

   Insertion : après les contrats (il les lit) et après
   `control_center_barehands_calibration.js` (il reprend sa coque), **avant**
   `control_center_barehands.js`, qui lit celui-ci pour poser
   `JarvisBarehands.tutorial()` et `.exitOverlay()` sur sa surface gelée. Un
   test de page vérifie l'ordre (constat F3 de la Slice 00). */
(function(root){
  'use strict';
  const BH=root.JarvisBarehandsContracts;
  if(!BH)throw new Error('JarvisBarehandsTutorial : les contrats Bare Hands doivent être insérés avant ce module');

  /* ------------------------------------------------------------------ 1
     Réglages du parcours, et les deux paires dangereuses qu'ils forment.

     Même règle que partout sur cette tâche (douzième et treizième de la
     tâche) : une combinaison qui ne peut pas marcher se refuse **à la
     construction**, pas au premier utilisateur qui la rencontre. Les deux
     d'ici échouent de la façon qui se lit « l'utilisateur s'y prend mal ». */
  const DEFAULTS=Object.freeze({
    /* Échéance d'une étape. Au-delà, l'étape est **manquée et le dit** : une
       étape qui attend pour toujours est la panne que la RÈGLE ZÉRO interdit. */
    stepTimeoutMs:45000,
    /* Le temps qu'on laisse à l'utilisateur pour **lire** la consigne avant que
       l'étape se mette à écouter. Sans lui, un geste encore en cours au moment
       où l'étape précédente se solde valide la suivante à l'image d'après, et
       la consigne défile sans jamais avoir été lue — c'est la leçon de la
       Slice 08 (« une phrase affichée juste avant un changement d'écran n'est
       pas affichée »), vue depuis l'autre bout. */
    readMs:1200,
    /* Cadence du chien de garde **de la page**. Le parcours est nourri par la
       boucle d'images, qui ne tourne qu'en ACTIVE et avec une main visible :
       sans second mécanisme, une étape quittée par l'utilisateur n'expirerait
       jamais et le compteur à l'écran resterait figé sur « 0 s restantes ».
       Publiée ici et non dans la page pour que la paire dangereuse ci-dessous
       ait ses deux nombres au même endroit. */
    watchdogMs:500,
  });

  function options(overrides){
    const o={...DEFAULTS,...(overrides||{})};
    /* **Paire dangereuse n° 12.** Le temps de lecture au-dessus de l'échéance :
       l'étape expire avant d'avoir commencé à écouter. **Toutes** les étapes
       seraient manquées, le récapitulatif dirait « rien n'a été fait » à
       quelqu'un qui a tout fait, et rien à l'écran ne pourrait le contredire.
       Même espèce que `stageTimeoutMs <= stageHoldMs` (Slice 08) et que
       `sleepTimeoutMs <= wakeHoldMs` (Slice 07) : le temps qu'on accorde doit
       dépasser le temps qu'on exige. */
    if(!(o.readMs>=0&&o.readMs<o.stepTimeoutMs))
      throw new RangeError('readMs doit rester positif et sous stepTimeoutMs : au-dessus, chaque étape expire avant d’avoir commencé à écouter, toutes les étapes sont manquées, et le récapitulatif accuse un utilisateur qui a tout fait correctement');
    /* **Paire dangereuse n° 13.** Le chien de garde plus lent que l'échéance
       qu'il surveille : une étape que personne ne nourrit (main sortie du
       cadre, utilisateur parti) n'est déclarée manquée qu'au tour suivant du
       chien de garde. L'écran affiche donc « 0 s restantes » pendant une
       échéance entière, et « ça attend » redevient indiscernable de « c'est
       bloqué » — exactement ce que le compteur existe pour empêcher. */
    if(!(o.watchdogMs>0&&o.watchdogMs<o.stepTimeoutMs))
      throw new RangeError('watchdogMs doit être positif et sous stepTimeoutMs : plus lent que l’échéance qu’il surveille, il laisse l’écran afficher « 0 s restantes » pendant toute une échéance de plus, et « ça attend » redevient indiscernable de « c’est bloqué »');
    return Object.freeze(o);
  }

  /* ------------------------------------------------------------------ 2
     Ce qu'une étape peut **constater**, et rien d'autre.

     C'est ici que se tient la promesse du haut de fichier. L'observation est
     reconstruite clé par clé : ce que le schéma ne nomme pas n'atteint jamais
     une étape — pas parce qu'on le refuse, parce qu'on ne le recopie pas
     (même idiome que la liste blanche du profil, §10). Une interaction y est réduite à
     son **type**, son **canal**, le fait qu'elle portait un objet (un booléen,
     jamais l'identifiant) et le **nombre** d'axes contraints. */
  const count=value=>{const n=Number(value);return Number.isFinite(n)&&n>0?Math.floor(n):0};
  const flag=value=>value===true;

  function readInteraction(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    return {
      type:BH.INTERACTIONS.includes(source.type)?source.type:null,
      channel:BH.PINCH_CHANNELS.includes(source.channel)?source.channel:null,
      /* Un **booléen**, jamais l'identifiant : le parcours n'a pas besoin de
         savoir *quel* objet, seulement qu'il y en avait un. */
      onObject:source.objectId!==null&&source.objectId!==undefined&&String(source.objectId)!=='',
      axes:count(Array.isArray(source.axes)?source.axes.length:0),
    };
  }
  /* La forme complète d'une observation, et la seule source de vérité du
     balayage de `assertTeachingOnly` : une clé ajoutée ici y passe sans qu'on
     y repense. */
  const BLANK=Object.freeze({now:0,lifecycle:null,tool:null,targetPreview:false,
    targets:0,hands:0,interactions:[]});
  function readObservation(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    const time=Number(source.now);
    return {
      now:Number.isFinite(time)?time:0,
      lifecycle:BH.LIFECYCLES.includes(source.lifecycle)?source.lifecycle:null,
      tool:BH.TOOLS.includes(source.tool)?source.tool:null,
      targetPreview:flag(source.targetPreview),
      targets:count(source.targets),
      hands:count(source.hands),
      interactions:(Array.isArray(source.interactions)?source.interactions:[]).map(readInteraction),
    };
  }

  /* La garde de forme, au **chargement du module** — même idiome que
     `assertDerivedOnly` (§10), et pilotée par le schéma pour la même raison :
     une observation remplie à la main ne dirait rien d'une clé que personne
     n'aurait pensé à remplir. On présente à chaque clé, et à chaque champ
     d'interaction, ce qu'un tutoriel ne doit jamais pouvoir transporter. */
  const POISON=Object.freeze([
    [{x:.1,y:.2,z:.3},{x:.4,y:.5,z:.6}],
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==',
    {frame:{width:640,height:480},pixels:[1,2,3]},
  ]);
  function assertTeachingOnly(){
    const looksRaw=value=>{
      if(value===null||value===undefined)return false;
      if(typeof value==='object')return true;
      return typeof value==='string'&&value.length>32;
    };
    const offend=(where,key,left)=>{
      throw new RangeError(`JarvisBarehandsTutorial : ${where}.${key} laisse passer `
        +`${typeof left==='object'?'une structure':'une chaîne'} au lieu d’un nombre, d’un booléen ou d’un nom du vocabulaire. `
        +'Un parcours de tutoriel n’a le droit de constater que des faits dérivés (décision 32) : la liste blanche doit réduire cette clé.');
    };
    for(const poison of POISON){
      for(const key of Object.keys(BLANK)){
        const read=readObservation({...BLANK,[key]:poison});
        if(key==='interactions'){
          for(const item of read.interactions)
            for(const field of Object.keys(item))
              if(looksRaw(item[field]))offend('interactions[]',field,item[field]);
          continue;
        }
        if(looksRaw(read[key]))offend('observation',key,read[key]);
      }
      for(const field of ['type','channel','objectId','axes']){
        const item=readInteraction({type:BH.INTERACTION.CLICK,[field]:poison});
        for(const name of Object.keys(item))
          if(looksRaw(item[name]))offend('interactions[]',name,item[name]);
      }
    }
    return true;
  }

  /* ------------------------------------------------------------------ 3
     Les étapes : le vocabulaire V1, dans l'ordre où il s'apprend.

     Chacune porte ce qu'on demande, et **comment on constate que c'est fait**.
     `verify(observation, state)` ne lit que l'observation ci-dessus : une
     étape ne peut pas vérifier autre chose que ce que la liste blanche laisse
     passer. `manual` marque les deux étapes qui **expliquent** au lieu de
     mesurer — elles se soldent sur un bouton, et le récapitulatif le dit
     plutôt que de prétendre une mesure. */
  const STATUS=Object.freeze({DONE:'done',SKIPPED:'skipped',MISSED:'missed'});
  const STATUSES=Object.freeze(Object.keys(STATUS).map(key=>STATUS[key]));
  /* Motifs fermés — distincts de `STAGE_REASON` (§10) **exprès** : une étape
     de tutoriel manquée n'est pas une mesure ratée, et les confondre ferait
     entrer le vocabulaire du profil dans un parcours qui n'a pas le droit d'y
     toucher. */
  const REASON=Object.freeze({TIMEOUT:'timeout',NO_HAND:'no_hand',
    NOT_ACTIVE:'not_active',CANCELLED:'cancelled'});
  const REASONS=Object.freeze(Object.keys(REASON).map(key=>REASON[key]));

  const I=BH.INTERACTION;
  const saw=(observation,test)=>observation.interactions.some(test);

  const STEP=Object.freeze({
    WAKE:'wake',TARGET:'target',CLICK_PRIMARY:'click_primary',CLICK_SECONDARY:'click_secondary',
    CONTENT:'content',OBJECT_DRAG:'object_drag',FRAME_MOVE:'frame_move',FRAME_RESIZE:'frame_resize',
    TOOLS:'tools',EXIT:'exit',
  });

  const STEPS=Object.freeze([
    Object.freeze({id:STEP.WAKE,title:'Réveiller les mains',
      instruction:'Formez un C : pouce et index écartés sans se toucher, index déplié. Tenez une seconde — l’anneau se remplit autour de votre main.',
      hint:'Le bouton « Activer l’interaction » de l’onglet Expérimental fait la même chose, et la voix aussi : « Jarvis, active les mains ».',
      /* Décision 4 : c'est le seul état qui compte, et il se relit. */
      verify:observation=>observation.lifecycle===BH.LIFECYCLE.ACTIVE}),
    Object.freeze({id:STEP.TARGET,title:'Ce que la main vise',
      instruction:'Approchez la main d’un bouton et commencez à rapprocher pouce et index : le cadre de ce qui est visé apparaît.',
      hint:'Décision 3 : il n’y a pas de pointeur permanent. L’aperçu n’existe que pendant qu’une intention est détectée, et il se règle dans « Aperçu de la cible ».',
      verify:observation=>observation.targets>0}),
    Object.freeze({id:STEP.CLICK_PRIMARY,title:'Le clic',
      instruction:'Pincez franchement pouce et index sur ce que vous visez, puis rouvrez les doigts.',
      hint:'Décision 20 : le clic principal est pouce + index.',
      verify:observation=>saw(observation,event=>event.type===I.CLICK)}),
    Object.freeze({id:STEP.CLICK_SECONDARY,title:'Le clic droit',
      instruction:'Même geste avec le **majeur** : pincez pouce et majeur, puis rouvrez.',
      hint:'Décisions 21 et 22 : le clic droit est un doigt, jamais un appui long. Le repère devient rouge.',
      verify:observation=>saw(observation,event=>event.type===I.CONTEXT)}),
    Object.freeze({id:STEP.CONTENT,title:'Faire défiler et glisser du contenu',
      instruction:'Pincez **dans** le contenu d’une zone — pas sur son bord — et déplacez la main : le contenu suit ou défile.',
      hint:'Décision 8 : le corps d’un cadre est de l’interaction de contenu, jamais une poignée pour déplacer le cadre. Le repère est bleu.',
      verify:observation=>saw(observation,event=>event.type===I.SCROLL
        ||((event.type===I.DRAG_MOVE||event.type===I.DRAG_START)&&!event.onObject))}),
    Object.freeze({id:STEP.OBJECT_DRAG,title:'Déplacer une étoile',
      instruction:'Pincez une étoile de la scène et emportez-la. Relâchez pour la poser.',
      hint:'Décision 13 : une capture est tenue jusqu’au relâchement — vous pouvez passer sur autre chose sans la perdre.',
      verify:observation=>saw(observation,event=>event.onObject
        &&(event.type===I.DRAG_MOVE||event.type===I.DRAG_START||event.type===I.DRAG_END))}),
    Object.freeze({id:STEP.FRAME_MOVE,title:'Déplacer un cadre par son bord',
      instruction:'Pincez le **bord** ou un **coin** d’un cadre et déplacez la main : le cadre entier suit.',
      hint:'Décisions 9 et 10 : les bords et les coins sont des zones de manipulation, et une seule zone tenue déplace tout le cadre. Le repère est jaune.',
      verify:observation=>saw(observation,event=>event.type===I.MOVE)}),
    Object.freeze({id:STEP.FRAME_RESIZE,title:'Redimensionner à deux mains',
      instruction:'Tenez deux bords ou coins **différents** du même cadre, une main sur chacun, et écartez-les.',
      hint:'Décisions 11 et 15 à 18 : deux zones compatibles redimensionnent, la même zone deux fois est refusée, et croiser les mains n’inverse jamais la géométrie.',
      needs:2,
      verify:observation=>saw(observation,event=>event.type===I.RESIZE)}),
    /* Les deux dernières **expliquent** : ce qu'elles enseignent n'a pas de
       geste à constater. Le dire est plus honnête que de fabriquer une mesure
       — et l'étape des outils sait quand même reconnaître un vrai changement
       d'outil, qui vaut mieux qu'un acquiescement. */
    Object.freeze({id:STEP.TOOLS,title:'Les outils',
      instruction:'Un outil dit ce que la main **veut dire** ; les réglages disent comment Bare Hands se comporte. Changez d’outil dans l’onglet Expérimental si vous voulez essayer.',
      hint:'Décision 25 : Outils et Réglages sont deux concepts, et deux sections. Le pointeur est contextuel : il choisit selon ce qu’il y a sous la main.',
      manual:true,
      verify:(observation,state)=>observation.tool!==null&&state.toolAtEntry!==null
        &&observation.tool!==state.toolAtEntry}),
    Object.freeze({id:STEP.EXIT,title:'Sortir, toujours',
      instruction:'Trois sorties, et elles marchent depuis n’importe quelle étape : le bouton « Quitter », la touche Échap, ou « Jarvis, ferme la surimpression ».',
      hint:'Sans main sûre pendant le délai de veille, l’interaction retourne d’elle-même en veille ; seul l’interrupteur libère la caméra.',
      manual:true,
      verify:()=>false}),
  ]);

  /* **Traduction vers le vocabulaire de présentation de la coque.** La coque
     sait dessiner trois mots (`FLOW_STATUS` de
     `control_center_barehands_calibration.js`) et **refuse** tout autre depuis
     la Slice 09 — un mot inconnu fabriquait une classe CSS absente, donc une
     ligne sans couleur où « réussi » se lisait comme « passé ».

     Le tutoriel garde malgré tout ses propres mots (`done`/`skipped`/`missed`)
     : une étape de tutoriel manquée n'est pas une mesure ratée, et emprunter
     les statuts d'étape du profil (§10) ferait entrer son vocabulaire dans un
     parcours qui n'a pas le droit d'y toucher. La table ci-dessous est la seule jointure,
     et un test de parité la compare à ce que la coque publie. */
  const PRESENTED=Object.freeze({
    [STATUS.DONE]:'ok',[STATUS.SKIPPED]:'skipped',[STATUS.MISSED]:'failed'});

  /* Les sorties que la coque sait produire, dans les mots du journal. Elle en
     a deux (la touche et la croix permanente) ; la troisième est la voix, qui
     passe par `exit()` et apporte le sien. */
  const EXIT_WORD=Object.freeze({escape:'échap',fermeture:'croix'});

  const LABEL=Object.freeze({
    [REASON.TIMEOUT]:'temps écoulé',
    [REASON.NO_HAND]:'aucune main vue',
    [REASON.NOT_ACTIVE]:'Bare Hands n’était plus actif',
    [REASON.CANCELLED]:'interrompue',
  });

  /* ------------------------------------------------------------------ 4
     Le parcours.

     Une machine à états dirigée par les observations : rien ne tourne tant que
     l'utilisateur ne l'a pas lancé, et tout s'arrête quand il a fini. Aucune
     écriture, nulle part — le seul effet durable est ce que l'appelant décide
     de faire de `onDone` (la page y enregistre `tutorialSeen`, un **réglage**,
     jamais un paramètre de calibration). */

  /* Les dépendances qu'un tutoriel ne doit **jamais** recevoir. Refusées par
     leur nom, à la construction : c'est ce qui rend « le tutoriel n'écrit
     jamais de paramètre de calibration » vérifiable plutôt que promis. */
  const FORBIDDEN=Object.freeze(['save','profile','saveProfile','saveSettings',
    'measure','onMeasure','calibration']);

  function createTutorial(deps){
    const d=deps&&typeof deps==='object'?deps:{};
    const overlay=d.overlay;
    if(!overlay||typeof overlay.open!=='function')
      throw new RangeError('createTutorial exige `overlay` (createFlowOverlay) : la coque est partagée avec la calibration (décision 26), elle ne se recrée pas ici');
    for(const name of FORBIDDEN)
      if(d[name]!==undefined){
        const error=new RangeError(`createTutorial refuse la dépendance « ${name} » : le tutoriel n’écrit jamais de paramètre de calibration (contrat §13), et une couture qui pourrait le faire rendrait cette garantie déclarative au lieu de structurelle`);
        error.code='barehands_tutorial_cannot_write_profile';
        throw error;
      }
    const o=options(d.options);
    const now=typeof d.now==='function'?d.now:()=>Date.now();
    const say=typeof d.log==='function'?d.log:()=>{};

    let running=false,at=-1,reports=null,enteredAt=0,toolAtEntry=null,carry=null,concluded=false;
    /* Combien d'observations le parcours a reçues depuis son démarrage. Ce
       n'est pas une statistique de confort : sans elle, « le tutoriel est
       nourri à la cadence des images » et « le tutoriel n'est nourri que par
       la minuterie » s'écrivent exactement pareil, à l'écran comme à la
       console — et la seconde rate la quasi-totalité des clics, puisque les
       interactions d'une image sont vidées à la suivante. Même règle que
       `engine()` à la Slice 07 : une couture qu'on ne peut pas relire est une
       couture qu'on ne peut pas dire branchée. */
    let observed=0;

    const stepAt=index=>STEPS[index]||null;

    /* Une étape se solde une fois, et une seule. `skipped` n'est pas `missed` :
       ce que l'utilisateur a choisi de passer ne lui reproche rien, et ce qu'il
       a essayé sans y arriver demande une autre phrase.

       **Le motif survit au changement d'étape** — la leçon de la Slice 08 :
       une phrase écrite puis effacée par `overlay.step()` à l'image suivante
       est affichée zéro milliseconde. Elle est donc portée dans l'étape
       suivante. */
    function settle(status,reason,message){
      const step=stepAt(at);
      if(!step)return;
      reports[step.id]={status,reason:reason||null};
      say('info',`[barehands] tutoriel ${step.id} : ${status}`,{reason:reason||null});
      carry=status===STATUS.DONE
        ?{text:`${step.title} : c’est fait.`,kind:'ok'}
        :status===STATUS.SKIPPED
          ?{text:`${step.title} : passée. Vous pourrez y revenir en relançant le tutoriel.`,kind:''}
          :{text:`${step.title} : ${message||LABEL[reason]||'pas fait'}. On continue — rien n’est enregistré, rien n’est cassé.`,kind:'bad'};
      advance();
    }

    function advance(){
      at+=1;
      const step=stepAt(at);
      if(!step){conclude();return}
      enteredAt=now();
      toolAtEntry=null;
      overlay.target(null);
      overlay.step({index:at+1,total:STEPS.length,title:step.title,
        instruction:step.instruction,deadlineMs:step.manual?null:o.stepTimeoutMs});
      overlay.progress(0);
      paint(step,null);
      buttons(step);
      if(carry){overlay.note(carry.text,carry.kind);carry=null}
    }

    /* Les boutons de l'étape. Trois sorties **à toutes les étapes**, c'est
       l'exigence de la Slice : « Quitter » ici, Échap tenu par la coque, et la
       voix par `exitOverlay()`. « Passer » existe parce qu'une étape qu'on ne
       peut pas réussir sans pouvoir la passer est un cul-de-sac — la scène
       peut n'avoir ni étoile ni cadre à manipuler, et le tutoriel doit y
       survivre. */
    function buttons(step){
      const list=[];
      if(step.manual)
        list.push({id:'understood',label:at+1===STEPS.length?'Terminer le tutoriel':'J’ai compris',
          primary:true,run:()=>settle(STATUS.DONE,null)});
      list.push({id:'skip',label:'Passer cette étape',run:()=>settle(STATUS.SKIPPED,null)});
      list.push({id:'exit',label:'Quitter',run:()=>cancel('bouton')});
      overlay.buttons(list);
    }

    /* Ce que l'étape dit pendant qu'elle attend. Il y a **toujours** une
       phrase : « rien à l'écran » et « ça marche mais je ne le montre pas »
       sont la même image. */
    function paint(step,observation){
      const reading=now()-enteredAt<o.readMs;
      if(reading){overlay.note(step.hint||'','');return}
      if(!observation){overlay.note(step.hint||'','');return}
      /* **Les quatre états du cycle de vie ont chacun leur phrase**, et c'est
         ce qui remplace un refus au lancement : l'utilisateur a demandé le
         tutoriel, il l'a à l'écran, et l'écran lui dit ce qui manque. Une
         seule phrase pour les quatre aurait accusé la caméra dans les trois
         cas où elle n'y est pour rien. */
      if(step.id===STEP.WAKE){
        if(observation.lifecycle===BH.LIFECYCLE.ERROR)
          overlay.note('Bare Hands s’est interrompu : regardez le motif dans l’onglet Expérimental, puis reprenez le tutoriel.','bad');
        else if(observation.lifecycle===BH.LIFECYCLE.OFF)
          overlay.note('La caméra n’est pas encore ouverte. Laissez-la démarrer — le compteur ci-dessus dit depuis combien de temps.','');
        else if(observation.lifecycle===BH.LIFECYCLE.ACTIVE)
          overlay.note('Bare Hands est déjà actif : c’est exactement l’état que ce geste produit.','ok');
        else overlay.note(step.hint||'','');
        return;
      }
      if(observation.lifecycle!==BH.LIFECYCLE.ACTIVE){
        overlay.note('Bare Hands est retourné en veille : refaites le C pour reprendre.','bad');
        return;
      }
      if(!step.manual&&!observation.hands){
        overlay.note('Aucune main n’est vue. Ramenez la main dans le champ de la caméra.','bad');
        return;
      }
      if(step.needs>1&&observation.hands<2){
        overlay.note('Montrez vos deux mains : cette étape en demande deux.','');
        return;
      }
      if(step.id===STEP.TARGET&&!observation.targetPreview){
        overlay.note('« Aperçu de la cible » est décoché dans les réglages : la cible est toujours résolue, seul le dessin manque.','');
        return;
      }
      overlay.note(step.hint||'','');
    }

    function conclude(){
      concluded=true;
      overlay.target(null);
      overlay.progress(1);
      const rows=STEPS.map(step=>{
        const report=reports[step.id];
        return {label:step.title,status:PRESENTED[report.status],
          detail:report.status===STATUS.DONE?(step.manual?'lu':'fait')
            :report.status===STATUS.SKIPPED?'passée'
            :`pas fait — ${LABEL[report.reason]||report.reason||'inconnu'}`};
      });
      const done=STEPS.filter(step=>reports[step.id].status===STATUS.DONE).length;
      overlay.step({index:STEPS.length,total:STEPS.length,title:'Vous avez fait le tour',
        instruction:'Voici ce que vous avez essayé. Rien n’a été mesuré et aucun réglage de calibration n’a été touché — le tutoriel n’écrit pas de profil.',
        deadlineMs:null});
      overlay.report(rows);
      overlay.note(done===STEPS.length
        ?'Toutes les étapes ont été faites.'
        :`${done} étape(s) sur ${STEPS.length}. Vous pouvez relancer le tutoriel quand vous voulez.`,
        done===STEPS.length?'ok':'');
      overlay.buttons([
        {id:'close',label:'Fermer',primary:true,run:()=>finish('terminé')},
        {id:'again',label:'Recommencer',run:()=>restart()},
      ]);
      /* **`tutorialSeen` s'écrit ici**, à l'arrivée sur le récapitulatif, et
         non sur le bouton « Fermer » : l'utilisateur a traversé tout le
         parcours, et faire dépendre l'enregistrement d'un dernier clic ferait
         re-proposer le tutoriel à qui vient de le finir puis a appuyé sur
         Échap. Passer des étapes reste « vu » : le drapeau dit qu'on est venu,
         pas qu'on a réussi. */
      const result={steps:rows,done,total:STEPS.length,
        reports:JSON.parse(JSON.stringify(reports))};
      say('info','[barehands] tutoriel terminé',{done,total:STEPS.length});
      if(typeof d.onDone==='function')d.onDone(result);
    }

    function restart(){
      say('info','[barehands] tutoriel relancé depuis le récapitulatif');
      begin();
    }
    function begin(){
      reports={};
      for(const step of STEPS)reports[step.id]={status:STATUS.SKIPPED,reason:null};
      running=true;at=-1;carry=null;concluded=false;observed=0;
      advance();
    }
    function finish(why){
      say('info',`[barehands] tutoriel fermé (${why})`);
      stop();
      if(typeof d.onExit==='function')d.onExit(String(why||''));
    }
    function cancel(why){
      /* Quitter en cours de route : l'étape courante est **interrompue**, pas
         manquée, et le récapitulatif n'est pas atteint — donc `tutorialSeen`
         n'est pas écrit. Qui part au milieu n'a pas vu le tutoriel. */
      if(running&&!concluded){
        const step=stepAt(at);
        if(step&&reports[step.id].status===STATUS.SKIPPED)
          reports[step.id]={status:STATUS.MISSED,reason:REASON.CANCELLED};
      }
      finish(why);
    }
    function stop(){
      running=false;at=-1;reports=null;carry=null;concluded=false;
      overlay.close();
    }

    return {
      isRunning(){return running},
      stepId(){const step=stepAt(at);return step?step.id:null},
      /* Ce que le parcours a **constaté**, pas ce qu'on lui a promis. */
      observations(){return observed},
      /* **Le point d'entrée**, et il confirme (contrat §12). Il rend
         `{ok:true}` dès que la coque est à l'écran et que la première étape
         tourne — le **démarrage**, pas la fin : l'échéance du canal de
         commandes est de trois secondes, un tutoriel en prend plusieurs
         minutes. */
      start(){
        if(running)
          /* Déjà ouvert : c'est l'état que l'appelant demandait. Répondre
             « non » ferait dire à JARVIS que ça n'a pas démarré devant une
             coque ouverte à l'écran. */
          return {ok:true,flow:'tutorial',already:true,step:this.stepId()};
        /* La coque dit **laquelle** de ses sorties a servi ; le journal doit
           le répéter, sans quoi une fermeture par la croix se lirait « échap »
           et personne ne saurait quelle sortie les gens utilisent vraiment. */
        overlay.open({title:'Tutoriel Bare Hands',
          exit:why=>cancel(EXIT_WORD[why]||String(why||'demandé'))});
        begin();
        say('info','[barehands] tutoriel démarré',{steps:STEPS.length});
        return {ok:true,flow:'tutorial',step:this.stepId(),steps:STEPS.length};
      },
      exit(reason){if(!running)return false;cancel(reason||'demandé');return true},
      /* Une observation. Rend l'étape courante, pour que l'appelant puisse la
         lire sans connaître la machine. */
      feed(raw){
        if(!running||concluded)return null;
        const step=stepAt(at);
        if(!step)return null;
        observed+=1;
        const observation=readObservation(raw);
        if(toolAtEntry===null&&observation.tool!==null)toolAtEntry=observation.tool;
        const since=now()-enteredAt;
        if(!step.manual){
          overlay.progress(since/o.stepTimeoutMs);
          /* L'échéance d'abord : une étape expirée ne doit pas pouvoir avaler
             une observation de plus, sinon « temps écoulé » dépend de la
             cadence de la caméra. Le motif le plus **utile**, pas le plus
             littéral : une étape qui n'a jamais vu de main et une étape jouée
             sans succès ne demandent pas la même chose à l'utilisateur. */
          if(overlay.expired()){
            const reason=observation.lifecycle!==BH.LIFECYCLE.ACTIVE?REASON.NOT_ACTIVE
              :!observation.hands?REASON.NO_HAND:REASON.TIMEOUT;
            settle(STATUS.MISSED,reason);
            return this.stepId();
          }
        }
        paint(step,observation);
        // Le temps de lire la consigne : l'étape n'écoute pas encore.
        if(since<o.readMs)return this.stepId();
        let done=false;
        try{done=step.verify(observation,{toolAtEntry})===true}
        catch(error){
          /* Un refus codé dans une boucle d'images vaut la fin de la session
             (leçon des Slices 02 et 04) : une vérification qui lève se dit et
             se saute, elle n'arrête pas le tutoriel. */
          say('warn','[barehands] tutoriel : vérification impossible',
            {step:step.id,error:String(error&&error.message||error)});
          return this.stepId();
        }
        if(done)settle(STATUS.DONE,null);
        return this.stepId();
      },
      /* Ce que le récapitulatif dira, lisible avant qu'il n'arrive : c'est ce
         que l'écran de l'onglet affiche pendant qu'un tutoriel tourne. */
      report(){return reports?JSON.parse(JSON.stringify(reports)):null},
    };
  }

  /* La garde tourne au chargement, comme `assertDerivedOnly` : une liste
     blanche qu'on n'exerce jamais est un souhait. */
  assertTeachingOnly();

  const api=Object.freeze({
    DEFAULTS,options,STEP,STEPS,STATUS,STATUSES,REASON,REASONS,LABEL,PRESENTED,
    readObservation,readInteraction,assertTeachingOnly,createTutorial,
  });
  root.JarvisBarehandsTutorial=api;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
