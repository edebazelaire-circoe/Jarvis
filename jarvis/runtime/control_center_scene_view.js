/* Réglages d'affichage de la constellation (handoff
   jarvis-constellation-scene-runtime, Slice 12).

   Ce que l'utilisateur règle depuis la page elle-même — taille des étoiles,
   halo, gravitation, fils — et non depuis les réglages : un petit bouton en bas
   à droite de la scène ouvre la fenêtre, chaque changement prend effet tout de
   suite. Ce sont des préférences **d'affichage**, propres au navigateur : rien
   n'est envoyé à Core, la scène enregistrée ne bouge pas, le cerveau voit
   toujours la même chose (la capture garde les tailles de référence).

   Deux parties, comme `control_center_scene_settings.js` :
   - ici, la logique pure (`window.JarvisSceneView`) : définition des réglages,
     normalisation de ce qui a été enregistré, variables CSS et classes que la
     page pose, options de la rotation du champ, libellés. Ni DOM, ni stockage :
     les tests l'exécutent avec node (`tests/unit/test_scene_view_prefs.py`) ;
   - le bouton, la fenêtre et l'enregistrement local vivent dans le bloc
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
      hint:'La constellation tourne lentement autour de JARVIS, d’un bloc. Éteinte, elle est parfaitement immobile.'}),
    Object.freeze({id:'spread',type:'range',label:'Ampleur de l’orbite',min:.3,max:2.5,step:.1,value:1,needs:'orbit',
      hint:'L’angle de la rotation. Il reste borné par la place libre autour des objets les plus au bord.'}),
    Object.freeze({id:'speed',type:'range',label:'Vitesse de l’orbite',min:.25,max:4,step:.25,value:1,needs:'orbit',
      hint:'Un aller-retour dure environ trente secondes à vitesse 1.'}),
    Object.freeze({id:'links',type:'toggle',label:'Fils entre les objets',value:true,
      hint:'Les traits qui relient une étoile à son parent, à son signal, à ses résultats.'}),
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

  /* Options de `JarvisSceneLayout.orbitDrift`, ou `null` quand la gravitation
     est éteinte : la page ne calcule alors aucun angle. */
  function orbitOptions(settings){
    const value=normalize(settings);
    if(!value.orbit)return null;
    return {gain:value.spread,rate:value.speed};
  }

  /* Phrase annoncée après un changement (région vivante de la scène). */
  function changeSentence(field,value){return `${field.label} : ${valueLabel(field,value)}.`}

  const api=Object.freeze({version:1,KEY,FIELDS,FIELD_BY_ID,DEFAULTS,CLASSES,
    normalize,decode,encode,isDefault,active,describe,valueLabel,cssVars,classes,orbitOptions,changeSentence});
  root.JarvisSceneView=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
