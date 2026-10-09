/* Comparaison et composition de l'explorateur de variantes : fonctions pures (handoff jarvis-interactive-presentation-studio, Slice 19, moitié interface).

   Aucun DOM, aucun réseau : le modèle des variantes marquées, la mise en page 2 / 4 / vis-à-vis, l'état d'une fenêtre (origine, synchronisée, sans
   équivalent, indépendante), les touches de navigation, les refus de Core dits en français, le modèle du formulaire de composition (la demande envoyée
   à `compositions/plan` puis `compositions`) et les conflits typés avec leur `fix`. Le contrôleur DOM est `..._explorer_compare.js`, le formulaire
   `..._explorer_compose.js`. Mêmes marqueurs de page que l'explorateur ; ce fichier passe après le noyau de l'explorateur et publie
   `window.JarvisStudioExplorerCompareCore` (et `module.exports` pour node).

   Règles tenues ici :
   - **La comparaison est de l'état d'interface, jamais un contenu.** Rien de ce fichier n'écrit une variante : la vue (`GET .../compare`) est celle de Core,
     recalculée à chaque appel ; l'interface ne devine ni l'équivalence des scènes ni le statut d'une navigation, elle les lit.
   - **Texte d'auteur non fiable** : titres, messages et `fix` des conflits peuvent citer un titre de variante ; tout passe par `cleanLine`, puis `textContent`. */
(function(root){
  'use strict';
  const Core=root.JarvisStudioExplorerCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_core.js'):null);
  const {cleanLine,checkTitle,describeRefusal}=Core;

  const ALLOWED_SIZES=Object.freeze([2,4]);
  const MAX_MARKS=4;
  const MAX_RATIONALE=400;
  const MAX_LINKS=64;
  const MAX_CONFLICTS=20;
  const NARROW_PX=560;
  const PANE_OBJECT_PREFIX='studio-explorer-cmp-';

  /* Les quatre dimensions sémantiques de Core, dans cet ordre, et rien d'autre. */
  const DIMENSIONS=Object.freeze([
    {key:'scenes',label:'Scènes',hint:"La liste des scènes : structure, prefab épinglé, valeurs et contrôles, telles que la variante les garde."},
    {key:'narrative',label:'Narration',hint:"Ce qui est dit : libellé, texte et note de chaque élément de la partition."},
    {key:'motion',label:'Mouvement',hint:"Le reste de la partition : actions, minutage, repères, séquences verrouillées."},
    {key:'art_direction',label:'Direction artistique',hint:"Le document de direction artistique entier (palette, typographie, thème)."},
  ]);
  const DIMENSION_LABEL=Object.freeze(Object.fromEntries(DIMENSIONS.map(d=>[d.key,d.label])));

  /* Ce que dit une fenêtre après une navigation. `tone` : la couleur de la puce. */
  const STATUS=Object.freeze({
    origin:{label:'Choisie',tone:'accent',line:"Vous avez choisi cette scène."},
    synced:{label:'Synchronisée',tone:'ok',line:"Suit la scène choisie (scène équivalente)."},
    unmapped:{label:'Sans équivalent',tone:'warn',line:"Aucune scène équivalente : cette fenêtre garde sa scène. Liez-la à la main, ou passez en mode indépendant."},
    held:{label:'Indépendante',tone:'',line:"Mode indépendant : seule la fenêtre choisie a bougé."},
  });
  const MAPPING_LINE=Object.freeze({
    identity:"Même scène logique (identifiant commun).",
    manual:"Scène liée à la main.",
    none:"Sans équivalent dans les autres variantes.",
  });

  /* ------------------------------------------------------------------ variantes marquées pour la comparaison */
  /* `marks` : tableau ordonné d'identifiants (l'ordre de marquage devient l'ordre des fenêtres). 2 ou 4 pour comparer, jamais plus de 4. */
  function toggleMark(marks,id,isLive){
    const list=Array.isArray(marks)?marks.slice():[];
    const at=list.indexOf(id);
    if(at>=0){list.splice(at,1);return {marks:list,change:'removed'}}
    if(!isLive)return {marks:list,change:'refused',reason:"Une variante archivée ne se compare pas : restaurez-la d'abord."};
    if(list.length>=MAX_MARKS)return {marks:list,change:'refused',reason:`${MAX_MARKS} variantes au plus dans une comparaison : retirez-en une d'abord.`};
    list.push(id);
    return {marks:list,change:'added'};
  }
  function markState(marks){
    const n=Array.isArray(marks)?marks.length:0;
    if(ALLOWED_SIZES.includes(n))return {count:n,ok:true,reason:'',text:`${n} variantes marquées : prêtes à comparer.`};
    const reason=n===0?"Marquez 2 ou 4 variantes (touche C sur une ligne, ou Ctrl + clic) pour les comparer."
      :n===1?"Marquez-en au moins une autre : une comparaison porte sur 2 ou 4 variantes."
      :"Une comparaison porte sur 2 ou 4 variantes : marquez-en une de plus, ou retirez-en une.";
    return {count:n,ok:false,reason,text:n===0?'':`${n} variante${n>1?'s':''} marquée${n>1?'s':''}.`};
  }
  /* Les marques qui survivent à une relecture du graphe : les variantes vivantes seulement. */
  function pruneMarks(marks,isLive){return (Array.isArray(marks)?marks:[]).filter(id=>isLive(id))}

  /* ------------------------------------------------------------------ mise en page */
  /* `view` : la réponse de Core. Rend les fenêtres à montrer (la paire en vis-à-vis, sinon tout l'ensemble) et la grille. */
  function layoutOf(view,widthPx){
    const ids=Array.isArray(view&&view.variant_ids)?view.variant_ids:[];
    const shown=Array.isArray(view&&view.shown)&&view.shown.length?view.shown.filter(id=>ids.includes(id)):ids;
    const kind=view&&view.layout==='focus'?'focus':shown.length===4?'four_up':shown.length===2?'two_up':'empty';
    const narrow=Number.isFinite(widthPx)&&widthPx>0&&widthPx<NARROW_PX;
    const columns=narrow||shown.length<2?1:2;
    return {kind,shown,columns,narrow,hidden:ids.filter(id=>!shown.includes(id))};
  }
  function variantOf(view,id){return (view&&Array.isArray(view.variants)?view.variants:[]).find(v=>v.variant_id===id)||null}
  function sceneOf(variant,sceneId){return variant&&Array.isArray(variant.scenes)?variant.scenes.find(s=>s.scene_id===sceneId)||null:null}

  /* Le modèle d'une fenêtre : ce que Core sait de la variante et de la scène montrée, plus le statut de la dernière navigation. */
  function paneModel(view,id,navigation){
    const variant=variantOf(view,id);
    if(!variant)return {variantId:id,missing:true,number:null,title:'',scenes:[],sceneId:null,index:-1,count:0,status:null};
    const scenes=Array.isArray(variant.scenes)?variant.scenes:[];
    const anchors=view.anchors||{};
    const sceneId=typeof anchors[id]==='string'?anchors[id]:(scenes[0]&&scenes[0].scene_id)||null;
    const scene=sceneOf(variant,sceneId);
    const index=scene?scenes.indexOf(scene):-1;
    let status=null;
    if(navigation&&navigation.origin&&navigation.origin.variant_id===id)status='origin';
    else if(navigation&&navigation.results&&navigation.results[id]&&navigation.results[id].status)status=navigation.results[id].status;
    return {variantId:id,missing:false,number:variant.variant_number,title:cleanLine(variant.title,80)||'(sans titre)',revision:variant.revision,active:!!variant.active,
      scenes,sceneId,scene,index,count:scenes.length,mapping:scene?scene.mapping:'none',equivalents:scene&&scene.equivalents||{},
      suggestions:scene&&Array.isArray(scene.suggestions)?scene.suggestions:[],status:STATUS[status]?status:null};
  }
  function sceneLabel(scene,index){return `${String(index+1).padStart(2,'0')} · ${cleanLine(scene&&scene.title,60)||'(sans titre)'}`}

  /* La phrase sous une fenêtre : le statut de la dernière navigation, sinon l'équivalence de la scène montrée. */
  function paneLine(pane){
    if(pane.missing)return "Cette variante n'est plus disponible : choisissez-en d'autres.";
    if(pane.status&&STATUS[pane.status])return STATUS[pane.status].line;
    return MAPPING_LINE[pane.mapping]||MAPPING_LINE.none;
  }
  function paneAriaLabel(pane,total){
    if(pane.missing)return 'Variante indisponible';
    const bits=[`Variante ${pane.number}`,pane.title];
    if(pane.active)bits.push('active');
    if(pane.index>=0)bits.push(`scène ${pane.index+1} sur ${pane.count}${pane.scene?' : '+cleanLine(pane.scene.title,60):''}`);
    if(pane.status)bits.push(STATUS[pane.status].label.toLowerCase());
    return bits.join(', ');
  }

  /* ------------------------------------------------------------------ structure divergente */
  const RELATION_TEXT=Object.freeze({
    identical:null,
    reordered:"Les mêmes scènes, dans un autre ordre : la navigation synchronisée suit les équivalents, pas la position.",
    divergent:"Structures différentes : certaines scènes n'ont pas d'équivalent dans l'autre variante.",
  });
  function structureOf(view){
    const relation=view&&view.structure&&view.structure.relation||'identical';
    const unmapped=view&&view.unmapped&&typeof view.unmapped==='object'?view.unmapped:{};
    let total=0;
    for(const key of Object.keys(unmapped))total+=Array.isArray(unmapped[key])?unmapped[key].length:0;
    const text=relation==='divergent'&&total>0?`Structures différentes : ${total} scène${total>1?'s':''} sans équivalent. Liez-les à la main, ou passez en mode indépendant.`
      :RELATION_TEXT[relation]||null;
    return {relation,unmappedTotal:total,unmapped,text,diverged:relation!=='identical'};
  }

  /* Les liens manuels, prêts à afficher : les deux extrémités avec leur variante, leur scène et leur titre ; un lien périmé est dit, jamais appliqué. */
  function linkRows(view){
    const rows=[];
    for(const link of Array.isArray(view&&view.links)?view.links:[]){
      const side=end=>{
        const variant=variantOf(view,end&&end.variant_id);
        const scene=sceneOf(variant,end&&end.scene_id);
        return {variantId:end&&end.variant_id,sceneId:end&&end.scene_id,number:variant?variant.variant_number:null,
          sceneTitle:scene?cleanLine(scene.title,60):'',index:scene?variant.scenes.indexOf(scene)+1:null};
      };
      rows.push({a:side(link.a),b:side(link.b),stale:!!link.stale});
    }
    return rows;
  }
  function describeSide(side){
    if(!side||side.number===null||side.number===undefined)return 'scène disparue';
    if(!side.index)return `#${side.number} · scène disparue`;
    return `#${side.number} · scène ${side.index}${side.sceneTitle?' « '+side.sceneTitle+' »':''}`;
  }

  /* ------------------------------------------------------------------ touches */
  /* Les mêmes touches que l'aperçu simple : flèches et pages parcourent, Début et Fin vont aux extrémités. Core clampe aux bords. */
  function keyToStep(key,mods){
    const m=mods||{};
    if(m.ctrl||m.alt||m.meta)return null;
    if(key==='ArrowRight'||key==='ArrowDown'||key==='PageDown')return 'next';
    if(key==='ArrowLeft'||key==='ArrowUp'||key==='PageUp')return 'previous';
    if(key==='Home')return 'first';
    if(key==='End')return 'last';
    return null;
  }

  /* ------------------------------------------------------------------ refus (français) */
  const REFUSALS=Object.freeze({
    presentation_studio_stale_revision:{kind:'stale',text:"La comparaison a changé ailleurs (une autre page, ou la voix). Elle vient d'être relue : vérifiez, puis refaites le geste."},
    presentation_studio_compare_mapping_conflict:{kind:'refused',text:"Ce lien mettrait deux scènes d'une même variante en face l'une de l'autre. Retirez d'abord le lien qui en joint déjà une, puis recommencez."},
    presentation_studio_unknown_scene:{kind:'stale',text:"Cette scène (ou ce lien) n'existe pas ou plus. La comparaison vient d'être relue."},
    presentation_studio_unknown_variant:{kind:'stale',text:"Une variante comparée n'existe plus, ou elle est archivée. Choisissez-en d'autres pour comparer."},
    presentation_studio_invalid:{kind:'refused',text:"Core refuse cette demande : une comparaison porte sur 2 ou 4 variantes vivantes, toutes différentes."},
    presentation_studio_composition_refused:{kind:'refused',text:"Core refuse cette composition : lisez chaque conflit et son remède ci-dessous. Rien n'a été créé."},
    presentation_studio_unknown_composition:{kind:'refused',text:"Cette variante ne vient pas d'une composition."},
  });
  function limitText(op){
    if(op==='link')return `Un maximum de ${MAX_LINKS} liens manuels est atteint : retirez-en avant d'en ajouter.`;
    return "Limite atteinte : Core refuse cette demande.";
  }
  function describe(error,ctx){
    const e=error||{};
    const code=typeof e.code==='string'?e.code:'';
    if(code==='presentation_studio_limit_reached'&&ctx&&(ctx.op==='link'||ctx.op==='compare'))return {kind:'refused',code,text:limitText(ctx.op)};
    if(REFUSALS[code])return Object.assign({code},REFUSALS[code]);
    return describeRefusal(e,ctx);
  }

  /* ------------------------------------------------------------------ composition */
  function emptyForm(view,presetBase){
    const ids=Array.isArray(view&&view.variant_ids)?view.variant_ids:[];
    return {title:'',base:ids.includes(presetBase)?presetBase:ids[0]||'',scenes:'',narrative:'',motion:'',art_direction:'',rationale:'',on_unmapped:'refuse',activate:false};
  }
  /* Proposition de titre : les numéros des sources, pas un titre inventé. */
  function suggestTitle(view,form){
    const base=variantOf(view,form.base);
    return base?cleanLine(`Composition sur ${cleanLine(base.title,50)}`,80):'';
  }
  /* La demande de Core. Une dimension laissée « comme la base » est omise (Core la dit héritée dans la provenance). `revisions` : les révisions lues dans la vue. */
  function buildRequest(form,view,options){
    const opts=options||{};
    const errors=[];
    const ids=Array.isArray(view&&view.variant_ids)?view.variant_ids:[];
    const request={};
    const title=checkTitle(form.title);
    if(!title.ok)errors.push({field:'title',message:title.message});
    else request.title=title.value;
    if(!form.base||!ids.includes(form.base))errors.push({field:'base',message:"Choisissez la variante de départ parmi les variantes comparées."});
    else request.base=form.base;
    const used=new Set(form.base?[form.base]:[]);
    for(const dim of DIMENSIONS){
      const source=form[dim.key];
      if(!source)continue;
      if(!ids.includes(source)){errors.push({field:dim.key,message:`${dim.label} : choisissez une variante comparée.`});continue}
      request[dim.key]=source;
      used.add(source);
    }
    const why=cleanLine(form.rationale,MAX_RATIONALE+1);
    if(Array.from(why).length>MAX_RATIONALE)errors.push({field:'rationale',message:`La raison dépasse ${MAX_RATIONALE} caractères.`});
    else if(why)request.rationale=why;
    request.on_unmapped=form.on_unmapped==='keep_motion'?'keep_motion':'refuse';
    const revisions={};
    for(const id of used){
      const variant=variantOf(view,id);
      if(!variant){errors.push({field:'base',message:"Une variante choisie n'est plus dans la comparaison : relisez-la."});continue}
      revisions[id]=variant.revision;
    }
    if(Object.keys(revisions).length)request.source_revisions=revisions;
    if(form.activate===true)request.activate=true;
    if(Number.isInteger(opts.expectedRevision))request.expected_revision=opts.expectedRevision;
    return {ok:errors.length===0,errors,request,signature:JSON.stringify(request)};
  }
  /* Les conflits de Core, bornés et nettoyés : code, dimension (avec son nom), message et remède (`fix`). */
  function conflictRows(conflicts){
    const rows=[];
    for(const item of (Array.isArray(conflicts)?conflicts:[]).slice(0,MAX_CONFLICTS)){
      if(!item||typeof item!=='object')continue;
      rows.push({code:cleanLine(item.code,60),dimension:cleanLine(item.dimension,30),dimensionLabel:DIMENSION_LABEL[item.dimension]||cleanLine(item.dimension,30),
        message:cleanLine(item.message,300),fix:cleanLine(item.fix,300)});
    }
    return rows;
  }
  /* Ce qu'un plan accepté promet, en lignes lisibles (jamais le contenu de la narration). */
  function planSummary(answer){
    const composition=answer&&answer.composition||{};
    const result=composition.result||{};
    const lines=[];
    if(Number.isFinite(result.scene_count))lines.push(`${result.scene_count} scène${result.scene_count>1?'s':''}`);
    if(Number.isFinite(result.item_count))lines.push(`${result.item_count} élément${result.item_count>1?'s':''} de partition`);
    if(result.has_score===false)lines.push('sans partition');
    if(result.has_art_direction===false)lines.push('sans direction artistique');
    const dims=Array.isArray(composition.dimensions)?composition.dimensions:[];
    const provenance=dims.map(d=>({dimension:d.dimension,label:DIMENSION_LABEL[d.dimension]||cleanLine(d.dimension,30),inherited:!!d.inherited,
      from:(Array.isArray(d.sources)?d.sources:[]).map(s=>s.variant_number).filter(n=>Number.isFinite(n))}));
    const warnings=(Array.isArray(composition.warnings)?composition.warnings:[]).slice(0,10).map(w=>cleanLine(typeof w==='string'?w:w&&w.message||'',300)).filter(Boolean);
    return {lines,provenance,warnings,summary:cleanLine(result.summary,200)};
  }

  const api=Object.freeze({ALLOWED_SIZES,MAX_MARKS,MAX_RATIONALE,MAX_LINKS,NARROW_PX,PANE_OBJECT_PREFIX,DIMENSIONS,DIMENSION_LABEL,STATUS,MAPPING_LINE,RELATION_TEXT,REFUSALS,
    toggleMark,markState,pruneMarks,layoutOf,variantOf,sceneOf,paneModel,sceneLabel,paneLine,paneAriaLabel,structureOf,linkRows,describeSide,keyToStep,describe,
    emptyForm,suggestTitle,buildRequest,conflictRows,planSummary});
  root.JarvisStudioExplorerCompareCore=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
