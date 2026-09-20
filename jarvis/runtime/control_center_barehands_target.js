/* Bare Hands V1 — cible sémantique : collecte et aperçu (Slice 05).
   Architecture §6, décisions 3, 8, 9, 16, 23, 24.

   Ce module est la moitié **navigateur** de la résolution de cible. L'autre,
   la géométrie et l'hystérésis, est pure et vit dans
   `JarvisBarehandsCore.createTargetResolver` (`control_center_barehands.js`),
   où node la teste sans DOM. Ici : lire l'arbre pour savoir ce qui existe, et
   dessiner ce qui a été choisi.

   Deux raisons d'exister séparément plutôt que dans le pointeur :

   - il **lit la page entière** (nœuds de scène, boutons, onglets, champs),
     c'est-à-dire une responsabilité que le suivi des mains n'a pas ;
   - il ne s'exécute que sous **intention** (décision 3), donc son coût — un
     `querySelectorAll` et un rectangle par candidate — n'est jamais payé par
     une session au repos. C'est la décision produit qui paie la performance.

   Insertion : `control_center.py` / `control_center.html`, APRÈS les contrats
   (il les lit) et AVANT `control_center_barehands.js` (qui lit celui-ci).
   Un test de page vérifie l'ordre (constat F3 de la Slice 00).

   Unités : **pixels de la fenêtre** de bout en bout, comme `boundsPx` et
   `distancePx` du contrat. `getBoundingClientRect` fait la conversion une
   seule fois ; les unités de scène (±160 × ±90) n'entrent jamais ici. */
(function(root){
  'use strict';
  const BH=root.JarvisBarehandsContracts;
  if(!BH){
    /* Même règle que le tutoriel (§13) et l'enregistreur (§12) : la cause part
       dans la console et **ce module seul** reste absent. La page servie n'a
       qu'une seule balise `<script>` — les huit modules Bare Hands, la scène,
       la timeline, le Test Lab et ~2500 lignes de logique de page y sont
       concaténés — donc une levée au chargement avorte tout ce qui suit.
       L'intention (casser à l'insertion, pas trois clics plus tard) reste
       tenue : `control_center_barehands.js` lit ce global **directement**, et
       son bloc navigateur est rattrapé au même titre. Ce qui change est le
       rayon, pas le refus. */
    console.error('[barehands] barehands.target_not_installed '
      +JSON.stringify({error:'les contrats Bare Hands doivent être insérés avant ce module'}));
    return;
  }

  /* Ce qu'une main peut vouloir saisir, et **sous quel nom**. La table est
     ordonnée : le premier motif qui répond donne son type, qui est ce que le
     contrat appelle `kind` — « c'est lui, et non `elementFromPoint` seul, qui
     décide l'action possible ».

     Les étoiles de la scène viennent en tête, et c'est le constat F4 de la
     Slice 00 : `.sc-node` est **absent** du sélecteur de survol historique du
     pointeur (`INTERACTIVE`), donc une étoile est cliquable aujourd'hui sans
     n'avoir jamais été surlignée. Elle est ici la candidate la plus
     intéressante de toutes — c'est la seule qui ait des zones. */
  const KINDS=Object.freeze([
    Object.freeze({selector:'.sc-node[data-object-id]',kind:'scene_object'}),
    Object.freeze({selector:'a[href]',kind:'link'}),
    Object.freeze({selector:'button,summary,[role="button"]',kind:'button'}),
    Object.freeze({selector:'[role="tab"]',kind:'tab'}),
    Object.freeze({selector:'input,select,textarea,label',kind:'field'}),
    Object.freeze({selector:'.choice,.acard',kind:'card'}),
    Object.freeze({selector:'.toast',kind:'notice'}),
    Object.freeze({selector:'[tabindex]:not([tabindex="-1"])',kind:'control'}),
  ]);
  const SELECTOR=KINDS.map(entry=>entry.selector).join(',');
  const kindOf=el=>{
    for(const entry of KINDS)if(el.matches(entry.selector))return entry.kind;
    return 'unknown';
  };

  /* Arrondi de l'aperçu, par représentation. Lu d'une table plutôt que du
     style calculé de l'élément : `getComputedStyle` par candidate et par image
     coûterait un recalcul de mise en page pour une valeur décorative. */
  const RADIUS=Object.freeze({capsule:999,window:12,point:999,signal:999});
  const DEFAULT_RADIUS=10;

  /* Une candidate **actionnable** (décision 3 : une candidate qui ne l'est pas
     n'appelle aucun retour visuel). Trois refus, et aucun n'est décoratif :
     un contrôle désactivé ment sur ce qui va se passer, un sous-arbre `inert`
     ne reçoit rien, et un rectangle vide n'est pas à l'écran. */
  const actionableEl=el=>{
    if(el.disabled===true)return false;
    if(el.getAttribute&&el.getAttribute('aria-disabled')==='true')return false;
    if(typeof el.closest==='function'&&el.closest('[inert]'))return false;
    return true;
  };

  /* Nom de ce qui va être saisi. `aria-label` d'abord : les nœuds de scène le
     portent déjà, et c'est le nom que l'utilisateur lit ailleurs. Sans nom
     court, aucun — une étiquette vide vaut mieux qu'un fragment de contenu. */
  const nameOf=el=>{
    const label=(el.getAttribute&&(el.getAttribute('aria-label')||el.getAttribute('title')))||'';
    const text=label||String(el.textContent||'').trim().replace(/\s+/g,' ');
    return text.length>0&&text.length<=48?text:'';
  };

  /* Représentation de scène, lue de la métadonnée que la page de scène pose
     sur le nœud (`data-representation`). Elle n'est **pas** déduite des
     classes : `sc-capsule` est la forme *dessinée*, qui retombe sur une
     capsule quand une fenêtre manque de place — une fenêtre compacte perdrait
     alors ses zones, et une capsule dessinée en point aussi. Absente, la
     candidate n'a pas de zones : refuser des zones qu'on n'a pas su lire est
     l'erreur qui échoue du bon côté (décision 8 reste vraie, la 9 attend). */
  const representationOf=el=>{
    const value=el.dataset&&el.dataset.representation;
    return value?String(value):null;
  };

  const rectOf=el=>{
    const r=typeof el.getBoundingClientRect==='function'?el.getBoundingClientRect():null;
    if(!r)return null;
    const w=Number(r.width),h=Number(r.height);
    if(!(w>0&&h>0))return null;
    return {x:Number(r.left),y:Number(r.top),w,h};
  };
  const distanceTo=(rect,point)=>Math.hypot(
    Math.max(rect.x-point.x,0,point.x-(rect.x+rect.w)),
    Math.max(rect.y-point.y,0,point.y-(rect.y+rect.h)));

  /* **Le balayage**, sans point de vue : tout ce que la page offre, avec son
     cadre. C'est la moitié *chère* de la collecte — un `querySelectorAll` et un
     rectangle par candidate — et c'est la seule qui lise l'arbre.

     Elle est séparée du filtrage parce que les deux ne vieillissent pas à la
     même vitesse : les cadres d'une page ne changent qu'à un rendu, la main,
     elle, bouge à chaque image. Un appelant qui dessine un survol (aucune
     intention, donc aucune manipulation en cours, donc aucun cadre qui bouge)
     peut donc garder un balayage quelques dizaines de millisecondes et refaire
     le filtrage — qui n'est que de l'arithmétique — à chaque image. C'est ce
     qui permet au retour de survol de la décision 3 bis d'exister sans payer
     une lecture d'arbre par main et par image. */
  function survey(){
    if(typeof document==='undefined'||!document.querySelectorAll)return [];
    const overlay=BH.DOM.rootSelector;
    const out=[];
    for(const el of document.querySelectorAll(SELECTOR)){
      if(typeof el.closest==='function'&&el.closest(overlay))continue;
      const rect=rectOf(el);
      if(!rect)continue;
      const representation=representationOf(el);
      out.push({
        element:el,
        /* Renvoi opaque, posé une fois la liste dans son ordre final : le
           résolveur le rend tel quel, et c'est ainsi que l'appelant retrouve le
           nom et l'arrondi d'une cible **figée** dont la main s'est éloignée.
           Réapparier sur des coordonnées aurait échoué exactement là. */
        ref:-1,
        objectId:(el.dataset&&el.dataset.objectId)||null,
        kind:kindOf(el),
        representation,
        /* Seules `capsule` et `window` ont des zones (décision D3 de la
           Slice 00) : un `point` et un `signal` ne sont pas redimensionnables,
           et aucun contrôle du DOM ne l'est. */
        zoned:BH.hasManipulationZones(representation),
        actionable:actionableEl(el),
        name:nameOf(el),
        radiusPx:RADIUS[String(representation)]||DEFAULT_RADIUS,
        boundsPx:rect,
      });
    }
    return out;
  }

  /* Les candidates d'un balayage qui sont à `reach` pixels d'un point, dans
     l'ordre où le résolveur doit les lire. **Aucune lecture d'arbre** hors
     `elementFromPoint`, qui est une question par point et non par candidate.

     `document.elementFromPoint` **participe** sans décider : il dit seulement
     laquelle est au-dessus des autres, et cette candidate-là est citée en tête
     pour que le résolveur la préfère à distance égale. Deux objets qui se
     recouvrent rendent sinon la même distance (zéro), et c'est l'ordre du
     document qui trancherait — c'est-à-dire l'ordre de création, pas ce que
     l'utilisateur voit. */
  function near(list,point,reach){
    const x=Number(point&&point.x),y=Number(point&&point.y);
    if(!Number.isFinite(x)||!Number.isFinite(y))return [];
    const at={x,y};
    const span=Math.max(0,Number(reach)||0);
    const overlay=BH.DOM.rootSelector;
    let topmost=null;
    if(typeof document!=='undefined'&&typeof document.elementFromPoint==='function'){
      const hit=document.elementFromPoint(x,y);
      /* La surimpression des mains est à nous : elle ne se vise pas. */
      if(hit&&typeof hit.closest==='function'&&!hit.closest(overlay))topmost=hit.closest(SELECTOR);
    }
    const out=[];
    let front=null;
    for(const candidate of Array.isArray(list)?list:[]){
      if(!candidate||!candidate.boundsPx)continue;
      if(distanceTo(candidate.boundsPx,at)>span)continue;
      out.push(candidate);
      if(candidate.element===topmost)front=candidate;
    }
    if(front){
      const index=out.indexOf(front);
      if(index>0){out.splice(index,1);out.unshift(front)}
    }
    /* Le renvoi est celui de **cette** liste-ci : il indexe ce que l'appelant
       passera au résolveur, et deux filtrages du même balayage n'ont pas le
       même ordre. Écrit sur la candidate partagée, il serait juste pour la
       dernière main servie et faux pour l'autre — d'où la copie. */
    return out.map((candidate,index)=>({...candidate,ref:index}));
  }

  /* La collecte d'un seul point : balayer puis filtrer. C'est ce qu'appelle un
     chemin sous intention, où la fraîcheur des cadres compte plus que leur
     coût — une main qui pince est une main dont on sait qu'elle vise. */
  const collect=(point,reach)=>near(survey(),point,reach);

  /* ------------------------------------------------------------------ aperçu

     Décision 23 : le corps est bleu, une zone de manipulation jaune, le clic
     droit rouge. Les trois valeurs vivent dans le thème (`FEEDBACK_TOKENS`) ;
     cette feuille ne fait que les nommer, avec leur repli.

     Décision 3 : il n'y a **aucun élément d'aperçu dans l'arbre** tant
     qu'aucune main n'a d'intention. Pas « caché », pas « transparent » :
     absent. C'est ce qu'un test peut vérifier, et c'est ce qui distingue une
     règle tenue d'une règle écrite.

     **Le surlignage est un enfant de ce qu'il surligne** (décision 3 ter), pas
     un second objet qui le poursuit. C'est la correction d'une erreur de
     structure, et elle ne se rattrape pas par du code : tant que le cadre est
     un élément séparé que l'on repositionne d'après un `getBoundingClientRect`,
     il est mesuré **avant** que l'objet ne bouge et dessiné **après** — une
     image de retard, toujours, quelle que soit la finesse du suivi. Pire, il
     ne sait rien des transitions CSS (`.sc-node` glisse en 420 ms) ni de
     l'animation d'orbite : il les verrait comme une suite de sauts.

     Imbriqué, il n'y a plus rien à suivre. Le nœud bouge, son enfant bouge dans
     la même peinture, exactement comme le titre d'une fenêtre suit la fenêtre —
     parce que c'est son enfant, pas parce que quelqu'un le repositionne.
     Visuellement l'aperçu reste au-dessus de l'objet ; hiérarchiquement il est
     dedans.

     Tout ne peut pas en porter un : un `input`, un `select`, une image n'ont
     pas d'enfants, et un élément `position:static` ferait résoudre `inset:0`
     contre un tout autre ancêtre. Ceux-là gardent le dessin dans la
     surimpression — et c'est sans conséquence, parce que ce sont exactement
     les cibles qui **ne bougent pas** sous la main : on ne déplace pas un
     bouton, on le clique. Ce qu'une main nue déplace ou étire est un nœud de
     scène, et un nœud de scène est `position:absolute`. Le cas où le retard se
     verrait est donc précisément celui qui est imbriqué — et si cela cessait
     d'être vrai, ce module le **dit** (voir `hostFor`).

     La feuille n'est donc plus portée par `#jarvisHands` : un cadre imbriqué
     vit sous la scène, hors de la surimpression, et un sélecteur qui commence
     par la racine ne l'atteindrait plus. Les classes suffisent — elles sont à
     nous, préfixe compris. */
  const COLOR=Object.freeze({
    body:`var(${BH.FEEDBACK_TOKENS.body.cssVar},${BH.FEEDBACK_TOKENS.body.fallback})`,
    zone:`var(${BH.FEEDBACK_TOKENS.zone.cssVar},${BH.FEEDBACK_TOKENS.zone.fallback})`,
    secondary:`var(${BH.FEEDBACK_TOKENS.secondary.cssVar},${BH.FEEDBACK_TOKENS.secondary.fallback})`,
  });
  const STYLE_ID='jarvisHandsTargetStyle';
  const STYLE=`
.jh-target{position:absolute;left:0;top:0;box-sizing:border-box;pointer-events:none;
  color:${COLOR.body};border:2px solid color-mix(in srgb,currentColor 78%,transparent);
  background:color-mix(in srgb,currentColor 9%,transparent);
  box-shadow:0 0 0 1px color-mix(in srgb,currentColor 22%,transparent),0 0 22px color-mix(in srgb,currentColor 30%,transparent);
  animation:jhTargetIn .14s cubic-bezier(.16,1,.3,1) both}
/* **Imbriqué** (decision 3 ter) : le cadre recouvre la boite de son parent et
   n'est plus positionne par personne. Aucune coordonnee n'est ecrite ici ni en
   ligne : c'est le parent qui porte la position, la taille, sa transition et
   son orbite, et l'enfant les recoit. Le rayon se prend au parent pour la meme
   raison — une fenetre arrondie ne merite pas un cadre carre, et sa valeur
   vient de son theme, pas d'une table ici. Le z-index eleve n'ordonne que les
   enfants du parent : le surlignage passe devant le contenu de l'objet, jamais
   devant les autres objets, ce qui est exactement ce que « il est dedans »
   veut dire. */
.jh-target[data-nested="1"]{left:0;top:0;right:0;bottom:0;width:auto;height:auto;
  border-radius:inherit;z-index:2147483000}
/* Ce qui est **vise** passe devant ses freres le temps de la visee : un objet
   dont un voisin recouvre le bord ne repondrait pas a la question qu'on lui
   pose. Un objet seulement **survole**, lui, ne bouge pas d'un cran — une main
   qui traverse la scene ferait sinon passer devant tout ce qu'elle croise, ce
   qui est du bruit et non une reponse. La regle vit ici parce que c'est notre
   effet, pas celui de la scene ; !important parce que le placement de la scene
   ecrit z-index en ligne a chaque rendu. */
.sc-node:has(>.jh-target:not([data-hover="1"])){z-index:2147482900!important}
/* Une zone retenue : le cadre s'efface pour que **le seul** bord ou coin
   choisi porte la couleur (critère d'acceptation de la Slice 05). */
.jh-target[data-region="edge"],.jh-target[data-region="corner"]{
  border-color:color-mix(in srgb,currentColor 28%,transparent);background:color-mix(in srgb,currentColor 5%,transparent)}
.jh-target[data-feedback="zone"]{color:${COLOR.zone}}
/* **Survol** (décision 3 bis) : la même géométrie, dite à voix basse. Le cadre
   et la barre de zone sont ceux de la visée — sinon le retour de survol
   promettrait une prise différente de celle qu'on obtiendrait — mais ils sont
   assez effacés pour qu'une main qui traverse la scène ne clignote pas, et
   assez lisibles pour répondre à « suis-je sur le bord ? » avant d'avoir
   pincé. La barre, elle, garde presque toute sa couleur : c'est elle qui porte
   la réponse. */
.jh-target[data-hover="1"]{opacity:.62;box-shadow:none;
  border-color:color-mix(in srgb,currentColor 34%,transparent);
  background:color-mix(in srgb,currentColor 5%,transparent)}
.jh-target[data-hover="1"] .jh-target-zone{opacity:.88}
.jh-target[data-hover="1"] .jh-target-name{opacity:.8}
.jh-target[data-feedback="secondary"]{color:${COLOR.secondary};animation:jhTargetIn .14s cubic-bezier(.16,1,.3,1) both,jhTargetPulse 1.1s ease-in-out .14s infinite}
/* La barre d'une zone est posee par **insets**, jamais par un left calcule :
   collee aux bords de son cadre, elle suit un etirement sans qu'on la mesure.
   Seule son epaisseur est un nombre, et c'est la bande que le resolveur a
   mesuree. */
.jh-target-zone{position:absolute;box-sizing:border-box;border-radius:3px;
  background:color-mix(in srgb,currentColor 82%,transparent);
  box-shadow:0 0 14px color-mix(in srgb,currentColor 55%,transparent)}
.jh-target-zone.jh-corner{background:none;border:3px solid currentColor;border-radius:4px}
/* L'étiquette se pose au-dessus du cadre, sauf s'il n'y a pas la place : la
   surimpression coupe ce qui dépasse (overflow hidden), donc une cible collée
   en haut de la fenêtre aurait un nom invisible — c'est-à-dire, pour
   l'utilisateur, une cible sans nom. Pas d'accent grave ici : ce commentaire
   vit dans un littéral gabarit. */
.jh-target-name{position:absolute;left:50%;bottom:100%;transform:translate(-50%,-7px);
  max-width:34ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  padding:3px 8px;border-radius:999px;font:10px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.08em;
  color:currentColor;background:rgba(3,8,12,.72);border:1px solid color-mix(in srgb,currentColor 34%,transparent);
  backdrop-filter:blur(10px)}
.jh-target[data-name-below="1"] .jh-target-name{bottom:auto;top:100%;transform:translate(-50%,7px)}
/* Imbriquee, l'etiquette se pose **dedans** : une fenetre et une capsule
   coupent ce qui depasse (overflow hidden), donc un nom pose au-dessus du cadre
   serait simplement invisible — et un nom invisible, pour l'utilisateur, est
   une cible sans nom (REGLE ZERO). Au-dessus de la barre de zone, pour qu'un
   bord tenu ne le recouvre pas. */
.jh-target[data-nested="1"] .jh-target-name{left:50%;top:0;bottom:auto;
  transform:translate(-50%,5px);max-width:calc(100% - 10px);z-index:1}
@keyframes jhTargetIn{from{opacity:0;transform:scale(.97)}to{opacity:1;transform:scale(1)}}
@keyframes jhTargetPulse{0%,100%{opacity:1}50%{opacity:.46}}
@media(prefers-reduced-motion:reduce){.jh-target,.jh-target[data-feedback="secondary"]{animation:none}}`;

  function ensureStyle(){
    if(typeof document==='undefined'||document.getElementById(STYLE_ID))return;
    const style=document.createElement('style');
    style.id=STYLE_ID;style.textContent=STYLE;
    (document.head||document.body).appendChild(style);
  }

  /* Où poser la barre d'une zone dans le cadre de l'objet — en **insets**, pas
     en coordonnées. La différence est celle que la décision 3 ter fait partout
     ici : `{left:0, right:0, top:0, height: bande}` dit « collée en haut, sur
     toute la largeur », et cette phrase-là reste vraie pendant qu'on étire le
     cadre. `{left:0, top:0, width: largeur mesurée, height: bande}` disait la
     même chose pour **une** taille, et redevenait fausse à l'image suivante.

     Ne reste un nombre que l'épaisseur : la bande calculée par le résolveur
     (`bandPx`), pour que ce qui est montré soit exactement ce qui a été mesuré
     et non une épaisseur décorative qui mentirait sur la prise. Le cadre ne
     sert plus qu'à la borner — une bande ne prend jamais plus de la moitié du
     petit côté — ce qui est une tolérance, pas une position : la voir vieillir
     d'une image ne déplace rien. */
  function zoneRect(target){
    const bounds=target.boundsPx;
    const band=Math.max(3,Math.min(Number(target.bandPx)||0,Math.min(bounds.w,bounds.h)/2));
    const sides=BH.zoneSides(target.zone);
    if(target.region===BH.REGION.CORNER){
      const size=Math.max(band,Math.min(band*1.8,Math.min(bounds.w,bounds.h)/2));
      const out={corner:true,width:size,height:size,
        hide:[sides.includes('top')?'bottom':'top',sides.includes('left')?'right':'left']};
      out[sides.includes('left')?'left':'right']=0;
      out[sides.includes('top')?'top':'bottom']=0;
      return out;
    }
    const side=sides[0];
    if(side==='top')return {left:0,right:0,top:0,height:band};
    if(side==='bottom')return {left:0,right:0,bottom:0,height:band};
    if(side==='left')return {top:0,bottom:0,left:0,width:band};
    if(side==='right')return {top:0,bottom:0,right:0,width:band};
    /* Une zone qu'on ne sait pas lire ne se dessine pas. Le dernier `return`
       était inconditionnel : un côté inconnu — ou absent — ressortait en
       « bord droit », c'est-à-dire une réponse **assurée et fausse** là où le
       module se donne pour règle de refuser. Le seul appel vivant est gardé en
       amont, donc c'était latent ; mais une fonction exportée qui ment est un
       défaut qui attend son second appelant. */
    return null;
  }

  /* Les quatre côtés d'une boîte, dans l'ordre où on les écrit et où on les
     efface : une barre qui passe d'un bord à l'autre doit **rendre** l'inset
     qu'elle ne tient plus, sinon « collée en haut » et « collée en bas » se
     cumuleraient en « étirée du haut au bas ». */
  const INSETS=Object.freeze(['left','right','top','bottom']);

  /* Un élément **peut porter son propre surlignage** quand un enfant
     absolument positionné y recouvre exactement sa boîte. Deux refus, et ni
     l'un ni l'autre n'est un détail :

     - un élément **remplacé ou vide** (`input`, `select`, `textarea`, une
       image) n'a pas d'enfants : lui en donner un ne fait rien, ou casse le
       contrôle ;
     - un élément `position:static` ferait résoudre `inset:0` contre le
       **premier ancêtre positionné**, c'est-à-dire contre une tout autre
       boîte. Le cadre serait alors non pas en retard, mais ailleurs.

     Le style calculé se lit une fois par cible, à la prise ou au changement
     d'élément, jamais par image : c'est un recalcul de mise en page, et la
     boucle d'images n'en paie pas un par main. */
  const UNHOSTABLE=Object.freeze(['INPUT','SELECT','TEXTAREA','IMG','VIDEO','CANVAS',
    'IFRAME','EMBED','OBJECT','BR','HR','PROGRESS','METER']);
  function canHost(el){
    if(!el||el.nodeType!==1||typeof el.appendChild!=='function')return false;
    if(UNHOSTABLE.includes(String(el.tagName||'').toUpperCase()))return false;
    if(typeof getComputedStyle!=='function')return false;
    let position='';
    try{position=String((getComputedStyle(el)||{}).position||'')}
    catch(_error){return false}
    return position!==''&&position!=='static';
  }

  const px=value=>`${Math.round(Number(value)*10)/10}px`;

  /* Le rôle de couleur d'une cible, **demandé au contrat** plutôt que lu d'un
     champ facultatif. `target.feedback||FEEDBACK.BODY` retombait en bleu dès
     que le champ manquait : une visée au clic droit se dessinait alors
     « corps normal », c'est-à-dire qu'elle annonçait autre chose que ce qui
     allait se passer. La candidate du contrat ne porte plus de couleur (elle
     ne connaît pas le canal) ; `feedbackRole(région, canal)` la connaît, et il
     **refuse** une région ou un canal inconnus. Un refus ne se dessine pas :
     `null` ici veut dire « rien à montrer », pas « bleu par défaut ». */
  const feedbackOf=target=>{
    if(target.feedback)return {role:String(target.feedback)};
    try{return {role:BH.feedbackRole(target.region,target.channel)}}
    catch(error){return {error}}
  };

  function createTargetPreview(){
    const drawn=new Map();
    let warned=false,warnedFeedback=false,warnedZone=false,warnedHost=false;
    const host=()=>(typeof document!=='undefined'&&document.getElementById
      ?document.getElementById(BH.DOM.rootId):null);
    const drop=key=>{
      const entry=drawn.get(key);
      if(entry)entry.box.remove();
      drawn.delete(key);
    };
    return {
      /* `list` : ce que rend `createTargetResolver.update()`, enrichi de
         `feedback` (rôle de couleur) et `name` par l'appelant. Une liste vide
         **retire** tout : décision 3 tenue par la structure de l'arbre.

         `elementOf` : où **vit** chaque cible, par sa clé `main|canal`. C'est
         une fonction et non un champ de la cible, et c'est volontaire : un
         nœud du DOM n'a rien à faire dans ce que le résolveur publie ni dans ce
         que le moteur de captures reçoit (contrat § 6, « aucun élément du DOM
         ne traverse ce module »). Le dessin, lui, a le droit de le demander —
         c'est son métier. Absente, tout retombe dans la surimpression, ce qui
         est exactement le comportement d'avant la décision 3 ter. */
      render(list,elementOf){
        const targets=Array.isArray(list)?list:[];
        const parent=host();
        if(!parent){
          /* La surimpression n'est pas montée : Bare Hands ne tourne pas, donc
             il n'y a rien à montrer. Ce n'est un défaut que si on nous demande
             quand même de dessiner — et alors il se dit. */
          if(targets.length&&!warned){warned=true;
            console.warn('[barehands] aperçu de cible sans surimpression montée : rien ne sera dessiné')}
          this.clear();
          return;
        }
        ensureStyle();
        const live=new Set();
        for(const target of targets){
          if(!target||!target.boundsPx)continue;
          /* **Décision 3.** Une candidate non actionnable n'appelle aucun
             retour visuel, et le contrat nomme l'aperçu comme le consommateur
             qui le doit (`createTargetCandidate`, champ `actionable`). Le
             résolveur ne lui en envoie plus — c'est là que la porte principale
             est tenue — mais l'obligation est écrite ici, donc elle est tenue
             ici aussi : ce module se dessine à la demande de qui l'appelle, et
             un bouton désactivé entouré de bleu promet une action qui
             n'arrivera pas. */
          if(target.actionable===false)continue;
          /* Une couleur qu'on ne sait pas nommer ne se dessine pas : elle
             dirait à l'utilisateur qu'il va faire autre chose que ce qu'il
             fait. Le refus se dit — une fois, la boucle d'images n'est pas un
             journal — avec la raison telle que le contrat l'a donnée. */
          const role=feedbackOf(target);
          if(!role.role){
            if(!warnedFeedback){warnedFeedback=true;
              console.warn('[barehands] aperçu de cible sans rôle de couleur lisible : rien ne sera dessiné pour elle',
                (role.error&&role.error.message)||role.error)}
            continue;
          }
          const key=`${target.handTrackId}|${target.channel}`;
          live.add(key);
          let entry=drawn.get(key);
          if(!entry){
            const box=document.createElement('div');
            box.className=BH.DOM.targetClass;
            const zone=document.createElement('div');
            zone.className=BH.DOM.targetZoneClass;
            const name=document.createElement('span');
            name.className=`${BH.DOM.targetClass}-name`;
            box.appendChild(zone);box.appendChild(name);
            entry={box,zone,name,element:undefined,nested:false};drawn.set(key,entry);
          }
          /* **Ou ce cadre vit** (decision 3 ter). L'element et sa capacite a
             porter un enfant ne se relisent qu'au changement : `canHost` lit un
             style calcule, et une boucle d'images n'en paie pas un par main.

             Le re-attachement, lui, se verifie a chaque image, et pour une
             raison precise : la scene reecrit le contenu d'un noeud
             (`el.replaceChildren()` dans son `fill`) des que ce contenu change
             — un titre, un etat d'execution — et emporte notre enfant avec.
             C'est un `parentNode !==` par image, et c'est ce qui rend
             l'imbrication reparable au lieu de fragile : le cadre revient tout
             seul a l'image suivante. */
          const element=typeof elementOf==='function'?(elementOf(key)||null):null;
          if(element!==entry.element){
            entry.element=element;
            entry.nested=canHost(element);
            /* Ce qui **bouge** sous la main et ne peut pas porter son cadre est
               le seul cas ou le retard reviendrait. Il n'en existe aucun
               aujourd'hui — un noeud de scene est `position:absolute` — donc
               c'est une sentinelle, pas une normale, et elle se dit. */
            if(!entry.nested&&element&&target.objectId&&!warnedHost){warnedHost=true;
              console.warn('[barehands] cet objet ne peut pas porter son surlignage : le cadre le suivra avec une image de retard',
                String(target.objectId))}
          }
          const wanted=entry.nested?entry.element:parent;
          if(entry.box.parentNode!==wanted)wanted.appendChild(entry.box);
          entry.box.setAttribute('data-nested',entry.nested?'1':'0');
          const bounds=target.boundsPx;
          if(entry.nested){
            /* **Aucune coordonnee.** C'est tout l'objet de la decision 3 ter :
               la feuille colle le cadre aux quatre bords de son parent, et le
               parent porte la position, la taille, sa transition et son orbite.
               Les valeurs d'un passage en surimpression sont rendues, sinon
               elles gagneraient contre la feuille — un style en ligne bat une
               regle d'auteur. */
            for(const prop of ['left','top','width','height','borderRadius'])
              entry.box.style[prop]='';
          }else{
            /* `left`/`top` et non `translate3d` : l'animation d'apparition et le
               battement du clic droit possedent `transform`, et une position qui
               s'y superposerait serait ecrasee le temps de l'animation — l'apercu
               sauterait au coin superieur gauche a chaque apparition. */
            entry.box.style.left=px(bounds.x);
            entry.box.style.top=px(bounds.y);
            entry.box.style.width=px(bounds.w);
            entry.box.style.height=px(bounds.h);
            entry.box.style.borderRadius=px(Math.min(Number(target.radiusPx)||0,Math.min(bounds.w,bounds.h)/2));
          }
          entry.box.setAttribute('data-feedback',role.role);
          entry.box.setAttribute('data-region',String(target.region||BH.REGION.BODY));
          entry.box.setAttribute('data-locked',target.locked?'1':'0');
          /* Ce qui est **survolé** et ce qui est **visé** ne se dessinent pas
             pareil : l'un répond à « où suis-je ? », l'autre annonce ce qui va
             être pris. Même arbre, même géométrie, deux intensités — la
             distinction est un attribut et non une seconde classe, pour qu'un
             test la lise là où il lit déjà la région et la couleur. */
          entry.box.setAttribute('data-hover',target.hover?'1':'0');
          const zoned=target.region!==BH.REGION.BODY&&BH.zoneSides(target.zone).length>0;
          /* `zoneRect` refuse une zone qu'il ne sait pas lire : la barre reste
             alors cachée, et le cadre seul dit ce qui est visé. Un refus dans
             une boucle d'images se dit une fois — c'est un défaut, pas une
             normale : le résolveur a retenu une zone que le dessin ne sait pas
             placer. */
          const rect=zoned?zoneRect(target):null;
          if(zoned&&!rect&&!warnedZone){warnedZone=true;
            console.warn('[barehands] zone de cible illisible au dessin : barre masquée',String(target.zone))}
          entry.zone.style.display=rect?'block':'none';
          if(rect){
            /* Les quatre insets d'abord, **tous les quatre** : celui qu'une
               barre ne tient plus doit etre rendu, sinon « collee a gauche » et
               « collee a droite » se cumulent en « etiree d'un bord a
               l'autre ». */
            for(const side of INSETS)
              entry.zone.style[side]=rect[side]===undefined?'':px(rect[side]);
            entry.zone.style.width=rect.width===undefined?'':px(rect.width);
            entry.zone.style.height=rect.height===undefined?'':px(rect.height);
            entry.zone.classList.toggle('jh-corner',!!rect.corner);
            /* Un coin est une équerre : deux bords portants, deux effacés. */
            for(const side of ['top','right','bottom','left'])
              entry.zone.style[`border${side[0].toUpperCase()}${side.slice(1)}Color`]=
                rect.corner&&rect.hide.includes(side)?'transparent':'';
          }
          const name=String(target.name||'');
          /* Imbriquee, l'etiquette se pose **dans** le cadre (une fenetre coupe
             ce qui depasse) — donc il faut la place de la poser : sous 22 px de
             haut, elle recouvrirait la cible au lieu de la nommer. Le cadre ne
             sert ici qu'a decider si le nom tient, pas a le placer. */
          const room=!entry.nested||bounds.h>=22;
          entry.name.textContent=room?name:'';
          entry.name.style.display=name&&room?'block':'none';
          /* 26 px : la hauteur de l'étiquette plus son décalage. En dessous,
             elle passe sous le cadre au lieu d'être coupée. Sans objet quand
             elle est deja dedans. */
          entry.box.setAttribute('data-name-below',!entry.nested&&bounds.y<26?'1':'0');
        }
        for(const key of [...drawn.keys()])if(!live.has(key))drop(key);
      },
      /* Rien de tenu, rien de dessiné : c'est la même phrase. */
      clear(){for(const key of [...drawn.keys()])drop(key)},
      size(){return drawn.size},
    };
  }

  const api=Object.freeze({KINDS,SELECTOR,kindOf,survey,near,collect,createTargetPreview,
    /* La feuille est exposée pour être **lue par un test** : elle est composée
       à partir de `FEEDBACK_TOKENS`, donc la relire dans la source ne
       montrerait que les interpolations. C'est le texte produit qui doit
       nommer les trois variables de la décision 23, avec leur repli. */
    zoneRect,STYLE,STYLE_ID,RADIUS});
  root.JarvisBarehandsTarget=api;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
