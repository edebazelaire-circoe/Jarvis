/* Réglages d'affichage de la constellation (handoff
   jarvis-constellation-scene-runtime, Slice 12).

   Ce que l'utilisateur règle de la constellation — taille des étoiles, halo,
   gravitation, fils. Depuis le 2026-09-20 cela se règle dans Réglages →
   Apparence, sous la version Cosmos, et non plus par un bouton flottant en bas
   à droite de la scène ; chaque changement prend effet tout de suite. Ce sont
   des préférences **d'affichage**, propres au navigateur : rien n'est envoyé à
   Core, la scène enregistrée ne bouge pas, le cerveau voit toujours la même
   chose (la capture garde les tailles de référence).

   Deux parties, comme `control_center_scene_settings.js` :
   - ici, la logique pure (`window.JarvisSceneView`) : définition des réglages,
     normalisation de ce qui a été enregistré, variables CSS et classes que la
     page pose, options de la rotation du champ, libellés. Ni DOM, ni stockage :
     les tests l'exécutent avec node (`tests/unit/test_scene_view_prefs.py`) ;
   - la section des réglages et l'enregistrement local vivent dans le bloc
     navigateur de `control_center_scene_page.js`, avec le reste de la scène.

   Inséré tel quel dans la page par `ControlCenter.index`, avant le rendu. */
(function(root){
  'use strict';

  /* Clé de stockage local (par navigateur, jamais envoyée). */
  const KEY='jarvis.scene.view';

  /* Un réglage : `range` (curseur, multiplicateur) ou `toggle` (interrupteur).
     `needs` : le réglage n'a d'effet que si cet autre réglage est actif ; la
     fenêtre le grise alors sans l'oublier. */
  const FIELDS=Object.freeze([
    Object.freeze({id:'size',type:'range',label:'Taille des étoiles',min:.6,max:2.4,step:.1,value:1,
      hint:'Le cœur lumineux et sa lueur ; la zone sensible au clic ne change pas.'}),
    Object.freeze({id:'halo',type:'range',label:'Halo',min:0,max:2.4,step:.1,value:1,zero:'éteint',
      hint:'Le voile large autour de l’étoile. À zéro, il n’y en a plus.'}),
    Object.freeze({id:'breathe',type:'toggle',label:'Halo qui respire',value:true,needs:'halo',
      hint:'Sinon le halo reste d’une seule intensité.'}),
    Object.freeze({id:'orbit',type:'toggle',label:'Gravitation',value:true,
      hint:'Chaque étoile tourne lentement autour de JARVIS, dans le sens horaire. Éteinte, la constellation est parfaitement immobile.'}),
    /* Plafond 1.3 : la même valeur que `ORBIT_GAIN_MAX` du rendu, qui la
       calcule (`min(cadre / demi-axe du tour)`) — un test de parité refuse
       qu'elles divergent. Le maximum valait 2.5 tant que le champ se resserrait
       tout seul pour rattraper l'ampleur demandée ; ce resserrement est ce qui
       faisait sauter la constellation entière au moindre changement, et il n'y
       a plus rien pour rattraper une ampleur qui ne tient pas. Même à 1, la
       place enregistrée n'est la place dessinée qu'au départ du tour : le tour
       la déplace ensuite, et un geste passe toujours de l'une à l'autre par la
       tenue (`JarvisSceneLayout.holdStart` / `holdPlace`), qui défait le tour et
       l'ampleur. */
    Object.freeze({id:'spread',type:'range',label:'Ampleur de l’orbite',min:.3,max:1.3,step:.1,value:1,needs:'orbit',
      hint:'L’écartement du champ autour de JARVIS. À 1, chaque étoile tourne sur le cercle qui passe par sa place ; au-delà, le tour s’élargit sans jamais sortir du cadre.'}),
    Object.freeze({id:'speed',type:'range',label:'Vitesse de l’orbite',min:.25,max:4,step:.25,value:1,needs:'orbit',
      hint:'Un tour complet dure environ quatre minutes à vitesse 1.'}),
    Object.freeze({id:'links',type:'toggle',label:'Fils entre les objets',value:true,
      hint:'Les traits qui relient une étoile à son parent, à son signal, à ses résultats.'}),
    /* Tâches éphémères : sous-agents rapides sans compte rendu, que le cerveau
       déclare lui-même. Un réglage de filtre, pas de dessin : ni classe ni
       variable CSS (`classes`, `cssVars` l'ignorent). */
    Object.freeze({id:'showEphemeral',type:'toggle',label:'Afficher les tâches éphémères',value:true,
      hint:'Les sous-agents rapides qui s’effacent d’eux-mêmes à la fin, sans compte rendu. Éteint, ils ne s’affichent pas du tout, dans le panneau Agents comme sur la scène ; un échec reste toujours visible. Ce navigateur seulement : le cerveau voit toujours ces tâches.'}),
  ]);

  const DEFAULTS=Object.freeze(Object.fromEntries(FIELDS.map(f=>[f.id,f.value])));
  const FIELD_BY_ID=new Map(FIELDS.map(f=>[f.id,f]));

  /* Classes que la page pose sur le conteneur de scène ; toutes retirées avant
     de reposer celles qui conviennent. */
  const CLASSES=Object.freeze(['sc-no-halo','sc-still-halo','sc-no-orbit','sc-no-links']);

  /* Arrondi au pas du curseur, borné : une valeur venue d'un stockage modifié à
     la main ne peut pas sortir de la plage. */
  function clampRange(field,value){
    const n=Number(value);
    if(!Number.isFinite(n))return field.value;
    const steps=Math.round((Math.min(field.max,Math.max(field.min,n))-field.min)/field.step);
    return Math.round((field.min+steps*field.step)*100)/100;
  }

  /* Réglages complets à partir de n'importe quoi : les champs inconnus sont
     ignorés, les manquants prennent leur défaut. */
  function normalize(value){
    const source=value&&typeof value==='object'?value:{};
    const out={};
    for(const field of FIELDS){
      const given=source[field.id];
      if(given===undefined||given===null)out[field.id]=field.value;
      else if(field.type==='toggle')out[field.id]=given!==false&&given!=='false'&&given!==0;
      else out[field.id]=clampRange(field,given);
    }
    return out;
  }

  /* Texte enregistré → réglages. Texte absent ou illisible : les défauts. */
  function decode(text){
    if(typeof text!=='string'||!text)return normalize(null);
    let parsed=null;
    try{parsed=JSON.parse(text)}catch(_error){return normalize(null)}
    return normalize(parsed&&typeof parsed==='object'?parsed.view||parsed:null);
  }

  function encode(settings){return JSON.stringify({version:1,view:normalize(settings)})}

  const isDefault=settings=>{
    const value=normalize(settings);
    return FIELDS.every(f=>value[f.id]===f.value);
  };

  /* Un réglage grisé (son `needs` est éteint) garde sa valeur : la page ne
     l'applique simplement pas. */
  function active(settings,field){
    if(!field.needs)return true;
    const value=normalize(settings)[field.needs];
    return typeof value==='boolean'?value:value>0;
  }

  const trim=n=>String(Math.round(n*100)/100).replace('.',',');

  /* Valeur telle que la fenêtre l'écrit à côté du réglage. */
  function valueLabel(field,value){
    if(field.type==='toggle')return value?'activé':'éteint';
    if(field.zero&&value<=0)return field.zero;
    return `${trim(value)} ×`;
  }

  /* Modèle de vue de la fenêtre : un `rows` par réglage, dans l'ordre. */
  function describe(settings){
    const value=normalize(settings);
    return {
      rows:FIELDS.map(field=>({field,value:value[field.id],label:valueLabel(field,value[field.id]),
        enabled:active(value,field)})),
      custom:!isDefault(value),
    };
  }

  /* Variables CSS posées sur le conteneur : des multiplicateurs sans unité, les
     tailles de référence restent dans la feuille de style. */
  function cssVars(settings){
    const value=normalize(settings);
    return {'--sc-star-scale':trim(value.size).replace(',','.'),
      '--sc-halo-scale':trim(Math.max(0,value.halo)).replace(',','.')};
  }

  /* Classes à poser sur le conteneur pour ce réglage. */
  function classes(settings){
    const value=normalize(settings);
    const out=[];
    if(value.halo<=0)out.push('sc-no-halo');
    if(!value.breathe)out.push('sc-still-halo');
    if(!value.orbit)out.push('sc-no-orbit');
    if(!value.links)out.push('sc-no-links');
    return out;
  }

  /* Options de `JarvisSceneLayout.orbitField`, ou `null` quand la gravitation
     est éteinte : la page ne calcule alors aucun tour. */
  function orbitOptions(settings){
    const value=normalize(settings);
    if(!value.orbit)return null;
    return {gain:value.spread,rate:value.speed};
  }

  /* ------------------------------------------------------------------
     Tâches éphémères : quand une page cesse de les montrer.

     Le serveur ne retire rien : ni la base, ni la scène, ni le journal ne
     bougent (Décision 12 : un travail terminé n'est jamais retiré de la scène
     enregistrée). « Disparaît » veut dire « n'est plus affichée par cette
     page ». Le panneau Agents et la scène appliquent la même règle, celle-ci. */

  /* Une éphémère réussie reste affichée ce temps après sa fin — le temps de la
     voir finir — puis s'efface. Bornée : assez courte pour ne pas encombrer,
     assez longue pour être lue. */
  const EPHEMERAL_LINGER_MS=6000;

  /* Seuls statuts qui peuvent être éphémères (miroir de
     `EPHEMERAL_WORK_STATUSES` côté Python). Tout autre — échec, arrêt,
     interruption, blocage — n'est jamais masqué, quoi que dise le drapeau. */
  const EPHEMERAL_STATUSES=Object.freeze(['pending','running','completed']);

  /* `work` : `{ephemeral, status, ended_ms}` (heure locale, voir `indexWork`).
     Rend `{ephemeral, hidden, remainingMs}` : `remainingMs` est le temps avant
     l'effacement d'une éphémère réussie encore affichée, sinon `null`. Sans
     date de fin, on ne peut pas chronométrer : elle reste affichée. */
  function ephemeralVisibility(settings,work,now){
    const none={ephemeral:false,hidden:false,remainingMs:null};
    if(!work||work.ephemeral!==true||!EPHEMERAL_STATUSES.includes(work.status))return none;
    if(normalize(settings).showEphemeral===false)return {ephemeral:true,hidden:true,remainingMs:null};
    if(work.status!=='completed')return {ephemeral:true,hidden:false,remainingMs:null};
    const ended=Number(work.ended_ms);
    if(!Number.isFinite(ended)||ended<=0)return {ephemeral:true,hidden:false,remainingMs:null};
    const left=Math.min(EPHEMERAL_LINGER_MS,ended+EPHEMERAL_LINGER_MS-now);
    return left<=0?{ephemeral:true,hidden:true,remainingMs:null}:{ephemeral:true,hidden:false,remainingMs:left};
  }

  /* Même règle pour une étoile de la scène : le statut de l'étoile (`execState`,
     la scène est à jour) prime sur celui de la table des travaux, relevée à part
     et parfois en retard — un échec ne reste jamais masqué par une table qui
     dit encore « en cours ». Sans statut d'étoile, la table fait foi. */
  function ephemeralVisibilityFor(settings,work,execState,now){
    return ephemeralVisibility(settings,Object.assign({},work,{status:execState||(work&&work.status)}),now);
  }

  /* Travaux Core (`/api/work`, `items`) → table `source|external_id` →
     `{ephemeral, status, ended_ms}`. `skewMs` : « horloge serveur − horloge
     locale » ; la date de fin est ramenée à l'heure locale, celle que la page
     compare à `Date.now()`. Un élément illisible est ignoré. */
  function indexWork(items,skewMs){
    const index=new Map(),skew=Number.isFinite(skewMs)?skewMs:0;
    for(const item of Array.isArray(items)?items:[]){
      if(!item||typeof item!=='object'||!item.source||!item.external_id)continue;
      const ended=Date.parse(item.ended_at||'');
      index.set(`${item.source}|${item.external_id}`,{ephemeral:item.ephemeral===true,status:String(item.status||''),
        ended_ms:Number.isFinite(ended)?ended-skew:null});
    }
    return index;
  }

  /* Phrase annoncée après un changement (région vivante de la scène). */
  function changeSentence(field,value){return `${field.label} : ${valueLabel(field,value)}.`}

  const api=Object.freeze({version:1,KEY,FIELDS,FIELD_BY_ID,DEFAULTS,CLASSES,EPHEMERAL_LINGER_MS,
    normalize,decode,encode,isDefault,active,describe,valueLabel,cssVars,classes,orbitOptions,changeSentence,
    ephemeralVisibility,ephemeralVisibilityFor,indexWork});
  root.JarvisSceneView=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
