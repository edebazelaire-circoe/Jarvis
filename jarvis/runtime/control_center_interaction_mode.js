/* Mode d'interaction — le bouton d'état du bas-gauche et son sélecteur.

   Slice 03 de `jarvis-presentation-interaction-mode`. Le contrat vit dans
   `docs/interaction-mode.md` ; la Slice 01 a posé le vocabulaire
   (`SIMPLE` / `PRESENTATION` / `REUNION`) et la Slice 02 le plan de contrôle
   (`GET /api/status` → `interaction_mode`, `POST /api/interaction-mode`).
   Ce module ne fait qu'une chose : **montrer ce que ces deux-là disent**, et
   proposer de changer de mode par la porte qu'elles ont ouverte.

   **Aucun état local du mode, par construction.** C'est la règle que ce module
   partage avec le contrôle de cycle de vie Bare Hands, et pour la même raison :
   une seconde mémoire du mode dans le navigateur diverge le jour où quelqu'un
   change le mode depuis un autre onglet, depuis le protocole, ou depuis un
   rattrapage de démarrage — et l'écran mentirait sans que rien ne tombe. Le
   mode affiché vient **toujours** du dernier `/api/status`, jamais d'un clic.

   Ce que ce module tient est de l'affichage et rien d'autre : l'ouverture du
   sélecteur, le curseur de navigation au clavier, le compteur de la demande en
   vol (RÈGLE ZÉRO — une attente sans borne doit dire depuis combien de temps
   elle dure) et la dernière phrase de refus.

   **Aucune peinture optimiste.** Un clic n'écrit pas la pastille cochée : il
   part en `POST`, attend la réponse, puis redemande le statut canonique et
   laisse celui-ci peindre. Un échec laisse donc le mode canonique précédent
   coché sans qu'il y ait quoi que ce soit à défaire — c'est le critère
   d'acceptation de la Slice, rendu structurel plutôt que surveillé.

   Les quatre présentations, et pourquoi elles sont quatre alors qu'il n'y a que
   trois modes :

   - `assistant` — SIMPLE, le défaut et la frontière de régression (décision
     14). Bleu Jarvis ordinaire, sans emphase : c'est l'état dans lequel rien
     n'a été changé ;
   - `presentation` — un mode non par défaut **en vigueur**. Ambre et halo : il
     faut qu'on voie d'un coup d'œil que Jarvis ne se comporte pas comme
     d'habitude. Pas rouge — ce n'est pas une panne ; pas vert — ce n'est pas
     une réussite ;
   - `unconfirmed` — Core est injoignable. La valeur affichée est alors le
     **repli local** que la Slice 02 nomme (`source: "settings"`,
     `core_reachable: false`, `revision: null`) : une préférence enregistrée, et
     non la vérité vivante. Gris désaturé **et bordure en tirets**, parce qu'une
     différence qui ne tient qu'à la couleur n'en est pas une pour tout le
     monde ;
   - `unknown` — le sondage de statut lui-même est tombé. On ne sait rien, et
     c'est ce qui s'affiche.

   Dans les deux derniers, **aucune pastille n'est cochée**. C'est la règle du
   contrôle Bare Hands appliquée telle quelle : un état que l'on subit ne se
   coche pas, parce que cocher reviendrait à présenter une valeur locale comme
   autoritaire. `REUNION` appartient à la même famille par l'autre bout : il est
   présenté, annoncé, expliqué — et jamais coché, parce qu'il n'est jamais en
   vigueur (décision 02 : il ne doit pas non plus disparaître de l'écran).

   **`REUNION` est piloté par la donnée, pas par son nom.** La liste `modes` du
   statut porte `implemented` et `status` pour chaque mode ; c'est elle qui
   décide ce qui est choisissable. Un mode réservé refuse **ici**, sans
   aller-retour : le serveur répondrait 409, et faire un appel dont on connaît
   déjà le refus ferait passer une réserve assumée pour une panne. Le 409 reste
   traité sur le chemin d'écriture, parce que le catalogue que cette page tient
   est une photo vieille d'une seconde et qu'un Core plus ancien peut refuser un
   mode que cette photo annonce comme implémenté.

   Insertion : `control_center.py` / `control_center.html`. Ce module ne dépend
   d'**aucun** autre module de page — ni Bare Hands, ni la scène : il lit le
   statut que la page sonde déjà. Il refuse de s'installer si son emplacement
   manque, sous un nom cherchable, et ce refus est **rattrapé ici** : la page
   servie concatène tous ses modules dans une seule balise `<script>`, et une
   levée qui remonterait emporterait la scène, la chronologie et le Test Lab
   avec elle.

   **La couture, et pourquoi c'est le sondage à 1 Hz.** Il n'existe dans cette
   page ni cadre applicatif, ni magasin d'état, ni couture générique : la seule
   diffusion poussée est `openLifecycleSeam`, et elle est propre à Bare Hands.
   Le mode d'interaction n'a pas de flux poussé côté navigateur — sa vérité
   vivante est un champ de `GET /api/status`, que la page relit déjà chaque
   seconde. Ce module s'y branche par le motif que trois modules utilisent déjà
   (`JarvisScene.gate` / `statusLost`, `JarvisBarehandsCommandChannel.gate`,
   `JarvisBarehands.gate`) : une porte `gate(block)` appelée par
   `refreshStatus`, et une porte `statusLost()` appelée quand le sondage tombe.
   Généraliser une couture aurait voulu dire toucher `control_center_barehands.js`
   et inventer un mécanisme que rien d'autre n'utiliserait, pour gagner au mieux
   une seconde de latence sur un réglage que l'on change deux fois par jour.
   Le prix payé est écrit : jusqu'à une seconde entre le changement et son
   affichage — sauf juste après un clic, où le module redemande le statut
   lui-même au lieu d'attendre le battement suivant. */
(function(root){
  'use strict';

  /* Les identifiants que la page, les tests et les Slices suivantes cherchent. */
  const DOM=Object.freeze({
    hostId:'interactionModeHud',
    styleId:'interactionModeStyle',
    triggerId:'interactionModeButton',
    chooserId:'interactionModeChooser',
    labelId:'interactionModeLabel',
    subId:'interactionModeSub',
    noteId:'interactionModeNote',
    hintId:'interactionModeHint',
    announceId:'interactionModeAnnounce',
    /* Le préfixe de la description d'une pastille, une par mode. Ce que le mode
       fait n'atteignait que les yeux : le bandeau `.im-hint` n'est cible
       d'aucun `aria-describedby`, donc un lecteur d'écran annonçait le libellé
       et la réserve, jamais la conséquence. */
    descPrefix:'interactionModeDesc-',
    /* Le mode que chaque pastille porte, sur le modèle de
       `data-barehands-mode` du contrôle de cycle de vie. */
    modeAttribute:'data-im-mode',
    /* La présentation, écrite par une seule fonction : le bouton, sa pastille
       de tête et son étiquette ne peuvent pas diverger. */
    toneAttribute:'data-im-tone',
    /* Ce qu'une pastille est, au-delà de « cochée » : réservée (annoncée,
       jamais activable) et/ou enregistrée (ce que l'utilisateur a choisi, qui
       peut différer de ce qui tourne). Deux faits distincts, deux attributs. */
    reservedAttribute:'data-im-reserved',
    storedAttribute:'data-im-stored',
  });

  /* Les présentations. Les deux premières sont des modes en vigueur ; les deux
     dernières sont des états que l'on subit et que l'on ne choisit pas.
     `OTHER` existe pour qu'un mode ajouté par un serveur plus récent s'affiche
     sous son propre libellé au lieu d'être peint comme un mode connu. */
  const TONE=Object.freeze({
    ASSISTANT:'assistant',PRESENTATION:'presentation',
    OTHER:'other',UNCONFIRMED:'unconfirmed',UNKNOWN:'unknown'});

  /* La borne de l'attente d'écriture. RÈGLE ZÉRO : aucun état d'attente ne dure
     pour toujours. `fetch` n'a pas de délai par lui-même ; passé ce temps le
     contrôle redit ce qu'il a attendu, rend la main, et laisse le statut
     canonique peindre ce qui a réellement eu lieu — la réponse tardive, si elle
     arrive, ne peut donc rien écrire à l'écran. */
  const WRITE_DEADLINE_MS=12000;

  /* La route d'écriture, écrite une seule fois. */
  const WRITE_PATH='/api/interaction-mode';

  /* Ce que chaque famille de refus veut dire pour l'utilisateur. Les codes sont
     ceux que la Slice 02 a stabilisés et que le serveur pose dans l'en-tête
     `X-Jarvis-Error-Code` ; le texte, lui, appartient à l'écran.

     `interaction_mode_not_implemented` (409) est un **conflit** et non une
     panne, et `503` n'est pas un échec d'enregistrement : la préférence est
     écrite sur le disque, seule son application est différée. Dire « échec »
     là-dessus ferait recommencer l'utilisateur pour rien. */
  const REFUSAL=Object.freeze({
    interaction_mode_not_implemented:
      'Ce mode est annoncé mais n’a pas encore de comportement : rien n’a été changé.',
    interaction_mode_unknown:'Ce mode n’existe pas pour ce serveur.',
    interaction_mode_missing:'La demande est partie sans mode.',
    interaction_mode_bad_payload:'La demande n’avait pas la forme attendue.',
    interaction_mode_unknown_field:'La demande portait un champ que ce serveur ne connaît pas.',
    interaction_mode_schema_version_unsupported:
      'Cette page écrit une version de réglage que le serveur ne prend pas.',
  });

  /* Ce que les états d'attente disent, en un mot, sous le libellé du mode. */
  const SUB=Object.freeze({
    unknown:'STATUT INDISPONIBLE',
    unconfirmed:'NON CONFIRMÉ',
  });

  /* ------------------------------------------------------- vue, sans DOM */

  const isObject=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
  const text=value=>value===undefined||value===null?'':String(value);

  /* Le catalogue des modes, tel que le statut le publie. Aucun mode n'est
     écrit en dur ici : un mode absent de `modes` n'est pas proposé, et un mode
     que le serveur ajoutera apparaîtra sans que cette page change. */
  function optionsOf(block){
    const raw=isObject(block)&&Array.isArray(block.modes)?block.modes:[];
    const stored=isObject(block)?text(block.stored):'';
    const options=[];
    for(const entry of raw){
      if(!isObject(entry))continue;
      const value=text(entry.value);
      if(!value)continue;
      options.push(Object.freeze({
        value,
        label:text(entry.label)||value.toUpperCase(),
        status:text(entry.status),
        summary:text(entry.summary),
        /* **Un seul bit, un seul nom.** `implemented`, `selectable` et
           `reserved` disaient tous les trois la même chose, ce qui invite à en
           lire un et à en écrire un autre. Reste `reserved`, qui est le mot de
           l'écran. `implemented` doit valoir **vrai**, pas « être vrai-ish » :
           un serveur qui omettrait le champ verrait ses modes présentés comme
           réservés, ce qui est le sens sûr des deux. */
        reserved:entry.implemented!==true,
        /* Ce que l'utilisateur a choisi, qui n'est pas forcément ce qui tourne :
           un `REUNION` enregistré reste visible ici alors que le mode effectif
           rapporte SIMPLE (décision 02). */
        stored:!!stored&&stored===value,
      }));
    }
    return Object.freeze(options);
  }

  /* Ce que `/api/status` publie, traduit en ce que l'écran doit peindre. Pur :
     aucune lecture de page, aucune horloge, aucun réseau — c'est ce que les
     tests exercent sans navigateur.

     `pending` est la demande en vol, quand il y en a une. Elle est passée
     **à côté** de l'instantané plutôt que fondue dedans, parce qu'elle n'en
     fait pas partie : c'est de l'affichage local, et le mode coché reste celui
     que le serveur confirme pendant toute sa durée. */
  function viewOf(block,pending){
    const has=isObject(block);
    const options=optionsOf(block);
    const mode=has?text(block.mode):'';
    const known=options.find(option=>option.value===mode)||null;
    /* Un mode effectif que le catalogue dit réservé ne doit pas être cru. La
       Slice 02 refuse déjà cette réponse côté serveur ; si elle arrivait quand
       même, la croire serait exactement le mensonge que cette Slice existe
       pour empêcher. */
    const believable=!!mode&&(!known||!known.reserved);
    const live=has&&block.core_reachable===true&&believable;
    const tone=!has||!mode?TONE.UNKNOWN
      :!live?TONE.UNCONFIRMED
      :mode===TONE.ASSISTANT||mode===TONE.PRESENTATION?mode
      :TONE.OTHER;
    const stored=has?text(block.stored):'';
    const error=has&&isObject(block.error)?block.error:null;
    const waiting=isObject(pending)&&!!text(pending.mode);
    const wanted=waiting?text(pending.mode):'';
    const wantedOption=waiting?options.find(option=>option.value===wanted)||null:null;
    return Object.freeze({
      tone,
      mode,
      label:has?text(block.label):'',
      /* La pastille cochée. **Aucune** tant que Core ne confirme pas, et
         **aucune** sur un mode réservé : dans les deux cas, cocher afficherait
         comme autoritaire une valeur que personne ne garantit. */
      selected:live&&known&&!known.reserved?known.value:null,
      live,
      stored,
      storedLabel:has?text(block.stored_label):'',
      /* Enregistré et effectif divergent : c'est un fait à montrer, pas à
         arbitrer. Il arrive pour `REUNION` (réservé, jamais effectif) et après
         un 503 (préférence écrite, application différée). */
      diverged:!!stored&&!!mode&&stored!==mode,
      reason:error?text(error.code):'',
      options,
      busy:waiting,
      pendingLabel:wantedOption?wantedOption.label:wanted.toUpperCase(),
    });
  }

  /* Le libellé du bouton replié : le mode **en vigueur**, jamais la préférence.
     Quand rien n'est connu, il le dit au lieu de retomber sur un défaut
     plausible. */
  function captionOf(view){
    if(view.tone===TONE.UNKNOWN)return 'MODE ?';
    return view.label||view.mode.toUpperCase()||'MODE ?';
  }

  /* La seconde ligne du bouton : ce qu'il faut savoir sans ouvrir le sélecteur.
     Elle porte le **compteur** de la demande en vol : c'est la seule chose qui
     distingue une attente qui avance d'une page figée. */
  function subOf(view,seconds){
    if(view.busy)return `${view.pendingLabel} · ${Math.max(0,Math.round(seconds||0))} S`;
    if(view.tone===TONE.UNKNOWN)return SUB.unknown;
    const chosen=view.diverged?`CHOISI : ${view.storedLabel||view.stored.toUpperCase()}`:'';
    /* **Les deux, et non l'un ou l'autre.** « non confirmé » sortait avant
       « choisi », si bien qu'un REUNION enregistré disparaissait du bouton dès
       que Core devenait injoignable — c'est-à-dire exactement quand le choix de
       l'utilisateur est la seule chose que l'on sache encore (décision 02). */
    if(!view.live)return chosen?`${SUB.unconfirmed} · ${chosen}`:SUB.unconfirmed;
    return chosen;
  }

  /* La phrase lue par les lecteurs d'écran et affichée au survol. Elle dit
     l'état, sa cause quand il y en a une, et **comment en sortir**. */
  function labelOf(view,seconds){
    if(view.busy)
      return `Passage en ${view.pendingLabel} demandé depuis `
        +`${Math.max(0,Math.round(seconds||0))} secondes. Le mode affiché reste `
        +'celui que le serveur confirme. Ouvrir le choix du mode.';
    if(view.tone===TONE.UNKNOWN)
      return 'Mode d’interaction inconnu : le statut de Jarvis n’est pas lisible. '
        +'Ouvrir le choix du mode.';
    if(!view.live)
      return `Mode d’interaction : ${view.label||view.mode} — non confirmé par Core.`
        +`${view.diverged?` ${view.storedLabel||view.stored} est le mode choisi.`:''}`
        +' Ouvrir le choix du mode.';
    if(view.diverged)
      return `Mode d’interaction : ${view.label} en vigueur ; `
        +`${view.storedLabel||view.stored} est le mode choisi. Ouvrir le choix du mode.`;
    return `Mode d’interaction : ${view.label}. Ouvrir le choix du mode.`;
  }

  /* Le bandeau du sélecteur : ce qu'il faut savoir avant de choisir. Vide quand
     il n'y a rien à dire — un bandeau permanent cesse d'être lu. L'ordre est
     celui de l'urgence : un refus que l'on vient de provoquer passe avant un
     état durable. */
  function noteOf(view,seconds,failure){
    /* Le refus porte **son** ton. Il arrivait ici comme une simple chaîne, et le
       bandeau le peignait en rouge quoi qu'il dise : un 503 « enregistré, mais
       pas encore appliqué » et une réserve annoncée se lisaient comme une
       panne. Le ton voyage donc avec le texte, depuis `refusalOf`. */
    if(failure&&failure.text)
      return Object.freeze({tone:failure.tone||'bad',text:failure.text});
    if(view.busy)
      return Object.freeze({tone:'wait',
        text:`Demande de ${view.pendingLabel} en cours depuis `
          +`${Math.max(0,Math.round(seconds||0))} s. Le mode ne changera à l’écran `
          +'que lorsque le serveur l’aura confirmé.'});
    if(view.tone===TONE.UNKNOWN)
      return Object.freeze({tone:'bad',
        text:'Le statut de Jarvis n’est pas lisible : le mode affiché n’est pas connu. '
          +'Un changement demandé maintenant peut ne pas aboutir.'});
    if(!view.live)
      /* **Pas « ceci est la préférence enregistrée ».** C'était littéralement
         faux quand la préférence est réservée : le serveur rend alors le mode
         qui *s'appliquerait* (`behaving(stored)`), pas ce qui est rangé sur le
         disque — et les deux diffèrent précisément sur REUNION, le cas que la
         décision 02 protège. Le bandeau dit donc ce que la valeur est, et nomme
         le choix à côté quand il en diverge. */
      return Object.freeze({tone:'wait',
        text:'Core est injoignable. La valeur affichée est le mode qui '
          +`s’appliquerait, pas le mode en vigueur${view.reason?` (${view.reason})`:''}.`
          +`${view.diverged?` Choisi : ${view.storedLabel||view.stored}.`:''}`
          +' Un choix sera conservé et appliqué dès que Core répondra.'});
    /* Un catalogue vide n'est pas un sélecteur vide sans explication : sans ce
       mot, le menu s'ouvrirait sur rien et rien ne dirait pourquoi. */
    if(!view.options.length)
      return Object.freeze({tone:'warn',
        text:'Ce serveur n’annonce aucun mode : il n’y a rien à choisir ici pour le moment.'});
    if(view.diverged)
      return Object.freeze({tone:'warn',
        text:`Choisi : ${view.storedLabel||view.stored}. En vigueur : ${view.label}.`});
    return null;
  }

  /* ------------------------------------------------------------- dessin */

  /* Trois motifs, un par mode, tracés et non écrits : une pastille de couleur
     seule ne distingue rien pour qui ne voit pas les couleurs, et un libellé
     seul ne se repère pas du coin de l'œil. */
  const GLYPH=Object.freeze({
    /* SIMPLE : une bulle de parole. Jarvis répond et parle. */
    assistant:'M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H10l-4 3.5v-3.5H6.5A2.5 2.5 0 0 1 4 13.5Z',
    /* PRESENTATION : un écran sur pied. Jarvis montre et se tait. */
    presentation:'M3 5h18v10H3ZM12 15v4M8.5 21h7',
    /* REUNION : trois présences autour d'une table. */
    meeting:'M7 8.5a2 2 0 1 1 4 0 2 2 0 0 1-4 0ZM14 9.5a1.6 1.6 0 1 1 3.2 0 1.6 1.6 0 0 1-3.2 0ZM3.5 19c0-2.5 2.2-4.2 5.5-4.2s5.5 1.7 5.5 4.2M15.5 14.9c3 .2 5 1.8 5 4.1',
  });
  /* Le motif de repli : un mode que cette page ne connaît pas garde un icône
     neutre plutôt que rien du tout. */
  const GLYPH_FALLBACK='M12 3.5 20.5 12 12 20.5 3.5 12Z';

  function glyph(doc,mode,size){
    const svg=doc.createElementNS
      ?doc.createElementNS('http://www.w3.org/2000/svg','svg')
      :doc.createElement('svg');
    svg.setAttribute('viewBox','0 0 24 24');
    svg.setAttribute('width',String(size));
    svg.setAttribute('height',String(size));
    svg.setAttribute('fill','none');
    svg.setAttribute('stroke','currentColor');
    svg.setAttribute('stroke-width','1.6');
    svg.setAttribute('stroke-linecap','round');
    svg.setAttribute('stroke-linejoin','round');
    svg.setAttribute('aria-hidden','true');
    svg.setAttribute('focusable','false');
    svg.setAttribute('class','im-glyph');
    const path=doc.createElementNS
      ?doc.createElementNS('http://www.w3.org/2000/svg','path')
      :doc.createElement('path');
    path.setAttribute('d',GLYPH[mode]||GLYPH_FALLBACK);
    svg.appendChild(path);
    return svg;
  }

  /* -------------------------------------------------------- la feuille */

  const ACCENT='var(--accent,#6ee7ff)';
  const WARN='var(--warn,#ffb85c)';
  const DANGER='var(--danger,#ff6577)';
  const MUTED='var(--muted,#7190a0)';
  const LINE='var(--line,#183343)';

  /* La géométrie du coin bas-gauche, et **le rail qu'il faut partager**.

     Le haut du bord gauche appartient au contrôle de cycle de vie Bare Hands
     (76 px du haut) et à sa palette d'outils, dont la hauteur dépend du nombre
     d'outils installés : s'y ranger aurait voulu dire dépendre d'une longueur
     variable qui n'appartient pas à cette Slice.

     **Le bas-gauche n'est pas libre pour autant** — une première version de ce
     module l'a écrit, et c'était faux. Trois éléments y vivent déjà, tous posés
     par des feuilles injectées depuis du JS, donc invisibles à qui ne lit que
     `control_center.html` :

     - `#jarvisHands .jh-badge` (`control_center_barehands.js`), `left:18px;
       bottom:18px`, sur un hôte au rang 2147483000 — il peint **par-dessus**
       tout le reste ;
     - `#jarvisHands .jh-note`, `left:18px; bottom:46px`, le mot d'un geste
       étouffé, qui atterrissait au milieu de ce bouton ;
     - `.sc-status` (`control_center_scene_page.js`), `left:18px; bottom:18px`,
       et `bottom:52px` quand la pastille des mains est là.

     Le dépôt a donc déjà une **convention d'évitement pour ce rail**, et c'est
     celle-ci que ce module rejoint plutôt que d'inventer un second décalage :
     `body:has(<sélecteur du contrat>)`, avec le sélecteur du badge écrit tel
     quel — une feuille de style ne peut pas lire
     `JarvisBarehandsContracts.DOM.badgeSelector` — et un test qui refuse la
     divergence (`tests/unit/test_barehands_contracts_js.py`), auquel ce module
     s'est ajouté.

     L'échelle, de bas en haut : la pastille des mains occupe 18→42, le mot d'un
     geste étouffé 46→72, l'indicateur de scène 18→42 seul ou 52→76 quand il
     s'est déjà décalé. D'où deux barreaux, `RAIL_ONE` et `RAIL_TWO`, et jamais
     un troisième : au-delà, c'est le rail lui-même qui est trop chargé, et le
     répartir n'appartient à aucun de ses occupants pris isolément. */
  const GEO=Object.freeze({
    left:18,bottom:22,minWidth:168,maxWidth:236,
    /* Au-dessus d'un seul occupant du rail (la pastille des mains, ou
       l'indicateur de scène non décalé). */
    railOne:52,
    /* Au-dessus des deux, ou au-dessus du mot d'un geste étouffé. */
    railTwo:86,
    /* Le sélecteur du contrat Bare Hands, écrit tel quel comme la scène le fait,
       et gardé par le même test qu'elle. */
    badgeSelector:'#jarvisHands .jh-badge',
    noteSelector:'#jarvisHands .jh-note',
    sceneSelector:'.sc-status:not([hidden])',
    /* L'indication vocale est centrée en bas à **toutes** les largeurs
       (`left:50%; bottom:22px`), et la page ne la déplace jamais. Son texte le
       plus long — `F9 · VOICE HORS LIGNE` — fait environ 230 px, donc sous
       ~820 px de large elle et ce bouton se rencontrent. Le contrôle se hisse
       alors au-dessus d'elle. Le rail gauche, lui, ne se resserre qu'à 700 px,
       là où la page resserre tout le reste. */
    liftBelow:820,narrowBelow:700,narrowLeft:10,lift:42,
  });

  const STYLE=`
/* **Aucun \`z-index\` sur l'emplacement, et c'est délibéré**, pour la raison que
   le contrôle Bare Hands documente déjà : un rang posé ici ouvrirait un
   contexte d'empilement, et le sélecteur (36) s'y retrouverait enfermé sous les
   32 du bouton, donc derrière le panneau (33) et la bannière (35) qu'il doit
   recouvrir. Les rangs vivent sur les deux éléments positionnés eux-mêmes. */
#${DOM.hostId}{position:absolute;left:${GEO.left}px;
  /* Le barreau du rail (voir \`GEO\`) plus la hauteur dont il faut se hisser
     au-dessus de l'indication vocale. Deux variables et non deux règles
     concurrentes : chaque condition n'écrit que le fait qu'elle constate. */
  --im-rail:${GEO.bottom}px;--im-lift:0px;
  bottom:calc(var(--im-rail) + var(--im-lift));
  display:flex;flex-direction:column;align-items:flex-start;gap:0;
  font:12px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;
  /* Rangé un jour sous un parent aux événements coupés, le contrôle resterait
     cliquable — même précaution que la colonne Bare Hands. */
  pointer-events:auto;
  --im-ink:${ACCENT};
  --im-line:color-mix(in srgb,${ACCENT} 38%,transparent);
  --im-face:rgba(6,12,18,.88);
  --im-glow:none;
  --im-dash:solid}
/* ---- l'évitement du rail bas-gauche, partagé avec Bare Hands et la scène ----
   Même mécanique que \`body:has(${GEO.badgeSelector}) .sc-status\` : la page
   constate la présence de l'occupant et le voisin se décale. L'ordre des règles
   est celui de l'échelle — la plus haute gagne, par spécificité pour les
   combinaisons et par ordre de source à spécificité égale. */
body:has(${GEO.badgeSelector}) #${DOM.hostId}{--im-rail:${GEO.railOne}px}
body:has(${GEO.sceneSelector}) #${DOM.hostId}{--im-rail:${GEO.railOne}px}
/* Les deux : l'indicateur de scène s'est lui-même décalé à 52, donc il monte
   jusqu'à 76 et ce contrôle doit passer au-dessus. */
body:has(${GEO.badgeSelector}):has(${GEO.sceneSelector}) #${DOM.hostId}{--im-rail:${GEO.railTwo}px}
/* Le mot d'un geste étouffé s'insère à 46→72 : il implique la pastille, donc il
   vaut d'emblée le second barreau. */
body:has(${GEO.noteSelector}) #${DOM.hostId}{--im-rail:${GEO.railTwo}px}
#${DOM.hostId}[${DOM.toneAttribute}=presentation]{
  --im-ink:${WARN};
  --im-line:color-mix(in srgb,${WARN} 52%,transparent);
  --im-face:rgba(24,16,4,.88);
  --im-glow:0 0 22px color-mix(in srgb,${WARN} 22%,transparent)}
/* Un mode que ce serveur annonce et que cette page ne connaît pas : il est bien
   en vigueur, donc il n'est pas désaturé, mais il ne porte ni la couleur ni le
   halo d'un mode dont cette page saurait ce qu'il fait. Sans cette règle il se
   peignait à l'identique de SIMPLE, ce qui est une affirmation que personne ne
   peut soutenir. */
#${DOM.hostId}[${DOM.toneAttribute}=other]{
  --im-ink:var(--text,#d8edf7);
  --im-line:color-mix(in srgb,var(--text,#d8edf7) 30%,transparent);
  --im-glow:none}
/* Les deux états que l'on subit : désaturés **et** en tirets. Une différence
   qui ne tient qu'à la couleur n'en est pas une pour tout le monde, et celle-ci
   porte la seule chose qui compte ici — « cette valeur n'est pas confirmée ». */
#${DOM.hostId}[${DOM.toneAttribute}=unconfirmed],
#${DOM.hostId}[${DOM.toneAttribute}=unknown]{
  --im-ink:${MUTED};
  --im-line:color-mix(in srgb,${MUTED} 55%,transparent);
  --im-face:rgba(6,10,14,.86);
  --im-glow:none;
  --im-dash:dashed}
#${DOM.hostId} .im-btn{position:relative;z-index:32;
  min-width:${GEO.minWidth}px;max-width:${GEO.maxWidth}px;
  display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px;align-items:center;
  padding:9px 13px 9px 11px;
  border:1px ${'var(--im-dash)'} var(--im-line);border-radius:11px;background:var(--im-face);
  color:var(--im-ink);box-shadow:var(--im-glow);cursor:pointer;text-align:left;
  font:inherit;
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);
  transition:color .18s ease,border-color .18s ease,box-shadow .26s ease,background .18s ease,transform .12s ease}
#${DOM.hostId} .im-btn:hover{border-color:color-mix(in srgb,var(--im-ink) 72%,transparent)}
#${DOM.hostId} .im-btn:active{transform:scale(.985)}
#${DOM.hostId} .im-btn:focus-visible{outline:2px solid ${ACCENT};outline-offset:3px}
#${DOM.hostId} .im-glyph{display:block;color:inherit}
#${DOM.hostId} .im-mark{display:grid;place-items:center;width:30px;height:30px;border-radius:8px;
  border:1px solid var(--im-line);background:rgba(0,0,0,.25);color:var(--im-ink)}
/* Le halo qui respire : seul PRESENTATION l'a, parce que c'est le seul état où
   Jarvis ne se comporte pas comme d'habitude. Le défaut ne clignote pas. */
#${DOM.hostId}[${DOM.toneAttribute}=presentation] .im-mark::after{content:'';position:absolute;
  inset:-6px;border-radius:15px;pointer-events:none;
  background:radial-gradient(closest-side,color-mix(in srgb,${WARN} 22%,transparent),transparent 78%);
  animation:imBreathe 3.6s ease-in-out infinite}
#${DOM.hostId} .im-mark{position:relative}
@keyframes imBreathe{0%,100%{opacity:.45}50%{opacity:1}}
#${DOM.hostId} .im-text{display:grid;gap:2px;min-width:0}
#${DOM.hostId} .im-eyebrow{font-size:8.5px;letter-spacing:.2em;text-transform:uppercase;color:${MUTED}}
#${DOM.hostId} .im-label{font-size:12.5px;letter-spacing:.13em;text-transform:uppercase;
  color:var(--im-ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#${DOM.hostId} .im-sub{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:${MUTED};
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#${DOM.hostId} .im-sub:empty{display:none}
#${DOM.hostId}[${DOM.toneAttribute}=unconfirmed] .im-sub,
#${DOM.hostId}[${DOM.toneAttribute}=unknown] .im-sub{color:${WARN}}
#${DOM.hostId}[data-im-busy=true] .im-sub{color:${ACCENT}}
/* RÈGLE ZÉRO : une attente se voit bouger. Le compteur de la ligne du dessous
   monte même quand les animations sont coupées ; cette barre est le signal de
   loin, pas le seul. */
#${DOM.hostId} .im-wait{position:absolute;left:10px;right:10px;bottom:5px;height:2px;border-radius:2px;
  overflow:hidden;display:none;background:color-mix(in srgb,var(--im-ink) 22%,transparent)}
#${DOM.hostId}[data-im-busy=true] .im-wait{display:block}
#${DOM.hostId} .im-wait::after{content:'';position:absolute;top:0;bottom:0;left:0;width:42%;
  border-radius:2px;background:currentColor;animation:imSweep 1.25s ease-in-out infinite}
@keyframes imSweep{from{transform:translateX(-115%)}to{transform:translateX(255%)}}
/* Une valeur non confirmée porte une marque qu'aucun mode en vigueur ne porte. */
#${DOM.hostId} .im-alert{position:absolute;right:-4px;top:-4px;width:11px;height:11px;border-radius:50%;
  display:none;background:${WARN};box-shadow:0 0 10px color-mix(in srgb,${WARN} 60%,transparent)}
#${DOM.hostId}[${DOM.toneAttribute}=unconfirmed] .im-alert,
#${DOM.hostId}[${DOM.toneAttribute}=unknown] .im-alert{display:block}

/* Le sélecteur. Il s'ouvre **vers le haut** : le contrôle est ancré en bas
   d'écran, et un menu qui sortirait par le bas serait coupé. */
#${DOM.hostId} .im-pop{position:absolute;z-index:36;bottom:100%;left:0;margin-bottom:12px;
  width:298px;max-width:calc(100vw - ${GEO.left * 2}px);padding:13px 14px 12px;
  /* Il s'ouvre **vers le haut** : sur un écran court, son sommet sortirait de
     l'écran et rien ne permettrait d'y revenir. Même mesure que \`.bgpop\`, qui
     est l'autre surimpression de cette page à hauteur variable. */
  max-height:calc(100vh - var(--im-rail) - var(--im-lift) - 96px);
  overflow-y:auto;overscroll-behavior:contain;
  border:1px solid ${LINE};border-radius:12px;background:var(--panel,rgba(6,12,18,.94));
  box-shadow:0 -18px 44px rgba(0,0,0,.5);
  -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);
  animation:imPop .16s ease-out}
#${DOM.hostId} .im-pop[hidden]{display:none}
@keyframes imPop{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
#${DOM.hostId} .im-pop h3{margin:0 0 10px;font-size:9px;font-weight:400;letter-spacing:.18em;
  text-transform:uppercase;color:${MUTED}}
#${DOM.hostId} .im-opts{display:grid;gap:6px}
#${DOM.hostId} .im-opt{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:11px;
  align-items:center;padding:9px 10px;border:1px solid transparent;border-radius:9px;
  background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;
  transition:background .14s ease,border-color .14s ease}
#${DOM.hostId} .im-opt:hover:not([disabled]){background:rgba(110,231,255,.05);border-color:${LINE}}
#${DOM.hostId} .im-opt:focus-visible{outline:2px solid ${ACCENT};outline-offset:2px}
#${DOM.hostId} .im-opt[disabled]{opacity:.45;cursor:not-allowed}
#${DOM.hostId} .im-opt[aria-checked=true]{border-color:color-mix(in srgb,${ACCENT} 45%,transparent);
  background:rgba(110,231,255,.07)}
/* Le mode réservé. \`aria-disabled\` et **pas** \`disabled\` : il reste atteignable
   au clavier, donc capable de dire pourquoi il ne se choisit pas. Un bouton
   que l'on ne peut pas atteindre ne peut rien expliquer. */
#${DOM.hostId} .im-opt[${DOM.reservedAttribute}=true]{cursor:not-allowed}
#${DOM.hostId} .im-opt[${DOM.reservedAttribute}=true] .im-opt-name{color:${MUTED}}
#${DOM.hostId} .im-opt[${DOM.reservedAttribute}=true] .im-opt-mark{border-style:dashed;color:${MUTED}}
#${DOM.hostId} .im-opt-mark{display:grid;place-items:center;width:30px;height:30px;border-radius:8px;
  border:1px solid ${LINE};color:${ACCENT}}
#${DOM.hostId} .im-opt[aria-checked=true] .im-opt-mark{border-color:color-mix(in srgb,${ACCENT} 55%,transparent);
  box-shadow:0 0 12px color-mix(in srgb,${ACCENT} 24%,transparent)}
#${DOM.hostId} .im-opt[${DOM.modeAttribute}=presentation][aria-checked=true] .im-opt-mark{
  color:${WARN};border-color:color-mix(in srgb,${WARN} 55%,transparent);
  box-shadow:0 0 12px color-mix(in srgb,${WARN} 26%,transparent)}
#${DOM.hostId} .im-opt-text{display:grid;gap:2px;min-width:0}
#${DOM.hostId} .im-opt-name{font-size:11.5px;letter-spacing:.13em;text-transform:uppercase}
#${DOM.hostId} .im-opt-state{font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:${MUTED}}
#${DOM.hostId} .im-opt-state:empty{display:none}
#${DOM.hostId} .im-opt-tag{font-size:8.5px;letter-spacing:.14em;text-transform:uppercase;
  padding:3px 6px;border-radius:5px;border:1px solid ${LINE};color:${MUTED};white-space:nowrap}
#${DOM.hostId} .im-opt-tag:empty{display:none;border:0;padding:0}
#${DOM.hostId} .im-opt[${DOM.storedAttribute}=true] .im-opt-tag{color:${WARN};
  border-color:color-mix(in srgb,${WARN} 40%,transparent)}
/* **Trois tons, et chacun a sa règle.** Le bandeau portait \`data-im-note\` sans
   qu'aucun sélecteur ne le lise pour \`bad\`, si bien que tout retombait sur le
   rouge de la base : « enregistré, mais pas encore appliqué » (503) et « ce mode
   est réservé » (409) se peignaient exactement comme « le changement a échoué ».
   L'argument était tenu dans le texte et démenti par la couleur, qui est ce que
   l'on lit en premier. */
#${DOM.hostId} .im-note{margin:0 0 10px;padding:7px 9px;border-radius:8px;font-size:10px;line-height:1.5;
  color:${MUTED};border:1px solid ${LINE};background:rgba(6,12,18,.5)}
#${DOM.hostId} .im-note[data-im-note=bad]{color:${DANGER};
  border-color:color-mix(in srgb,${DANGER} 34%,transparent);background:rgba(35,7,12,.45)}
#${DOM.hostId} .im-note[data-im-note=wait]{color:${ACCENT};
  border-color:color-mix(in srgb,${ACCENT} 32%,transparent);background:rgba(6,26,33,.5)}
#${DOM.hostId} .im-note[data-im-note=warn]{color:${WARN};
  border-color:color-mix(in srgb,${WARN} 34%,transparent);background:rgba(38,23,5,.45)}
#${DOM.hostId} .im-note[hidden]{display:none}
#${DOM.hostId} .im-hint{margin:11px 0 0;font-size:10px;line-height:1.55;color:${MUTED};min-height:3.1em}
#${DOM.hostId} .im-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}

/* L'indication vocale est centrée en bas à toutes les largeurs et la page ne la
   déplace jamais : sous ~820 px, elle et ce bouton se rencontrent. Le contrôle
   se hisse au-dessus d'elle — et il le fait **avant** le resserrement de 700 px,
   parce que la fenêtre 701→820 est précisément celle où les deux tenaient
   encore chacun leur moitié et ne la tiennent plus. */
@media(max-width:${GEO.liftBelow}px){
  #${DOM.hostId}{--im-lift:${GEO.lift}px}
}
@media(max-width:${GEO.narrowBelow}px){
  /* Le rail gauche se resserre avec le reste de la page. Le sélecteur s'ouvre
     toujours vers le haut, et sa largeur suit celle de l'écran. */
  #${DOM.hostId}{left:${GEO.narrowLeft}px}
  #${DOM.hostId} .im-btn{min-width:150px;max-width:calc(100vw - ${GEO.narrowLeft * 2 + 74}px)}
  #${DOM.hostId} .im-pop{width:min(298px,calc(100vw - ${GEO.narrowLeft * 2}px));max-width:none}
}
/* Écran court **et** étroit : sous 700 px de large, la colonne Bare Hands
   devient relative au centre (\`top:calc(50% + …)\` pour sa palette, dont la
   hauteur dépend du nombre d'outils installés), donc le partage « eux le haut,
   moi le bas » cesse d'être garanti. Ce module ne peut pas connaître cette
   hauteur ; ce qu'il peut faire est réduire son propre encombrement là où
   l'écran est le plus court. La limite résiduelle est écrite dans
   \`docs/interaction-mode.md\` et dans la liste de vérification manuelle. */
@media(max-width:${GEO.narrowBelow}px) and (max-height:640px){
  #${DOM.hostId} .im-btn{min-width:0;padding:7px 10px}
  #${DOM.hostId} .im-eyebrow{display:none}
}
@media(prefers-reduced-motion:reduce){
  /* Le compteur, lui, continue de monter : c'est le signal qui ne dépend
     d'aucune animation. */
  #${DOM.hostId} .im-btn,#${DOM.hostId} .im-opt{transition:none}
  #${DOM.hostId} .im-mark::after,#${DOM.hostId} .im-wait::after,#${DOM.hostId} .im-pop{animation:none}
}`;

  function installStyle(doc){
    if(!doc||typeof doc.getElementById!=='function')return null;
    const seen=doc.getElementById(DOM.styleId);
    if(seen)return seen;
    const style=doc.createElement('style');
    style.id=DOM.styleId;
    style.textContent=STYLE;
    (doc.head||doc.body||doc.documentElement).appendChild(style);
    return style;
  }

  /* ------------------------------------------------- le contrôle, en DOM

     Toutes les dépendances sont **injectées** — document, horloge, minuteries,
     porte réseau, relecture du statut, journal. C'est la seule façon d'exercer
     ceci sous node, et c'est ce que la Slice 03 de Bare Hands a déjà fait pour
     les mêmes raisons. */
  function createModeControl(deps){
    const doc=deps.document,host=deps.host;
    const now=typeof deps.now==='function'?deps.now:()=>Date.now();
    const arm=deps.setInterval,disarm=deps.clearInterval;
    const later=deps.setTimeout,unlater=deps.clearTimeout;
    const log=typeof deps.log==='function'?deps.log:function(){};
    /* La porte d'écriture de la page (`api`), passée plutôt que prise : prise
       dans un global, ce contrôle serait inexerçable sous node. */
    const request=typeof deps.request==='function'?deps.request:null;
    /* L'infusion de la page, pour dire un refus **sans** reprendre le focus.
       Absente — une page servie à moitié —, le contrôle fonctionne quand même :
       perdre une infusion est moins grave que perdre le mode. */
    const toast=typeof deps.toast==='function'?deps.toast:null;
    /* La relecture du statut canonique. Après une écriture, on ne peint pas ce
       qu'on a demandé : on redemande ce qui est. */
    const refresh=typeof deps.refresh==='function'?deps.refresh:null;

    /* **L'instantané, et rien d'autre.** `block` est le dernier
       `interaction_mode` reçu ; il n'est jamais écrit par un clic. */
    let block=null,pending=null,view=viewOf(null,null);
    let opened=false,cursor=0,failure='',choosing=false;
    let waitTimer=0,spoken='';
    /* **Une minuterie d'echeance par appel.** Elle vivait dans une variable
       unique, alors que deux `choose()` peuvent se chevaucher : passe le delai,
       le premier appel rendait la main, un second partait et posait SA minuterie
       dans la meme variable -- puis le premier, en se terminant enfin, annulait
       ce qu'il y trouvait, c'est-a-dire l'echeance du second. Le second devenait
       illimite, et le controle restait desarme pour la vie de la page : exactement
       ce que `WRITE_DEADLINE_MS` existe pour empecher. Chaque appel tient donc son
       billet dans sa fermeture. */
    const waits=new Set();

    installStyle(doc);

    const trigger=doc.createElement('button');
    trigger.id=DOM.triggerId;trigger.className='im-btn';
    trigger.setAttribute('type','button');
    trigger.setAttribute('aria-haspopup','menu');
    trigger.setAttribute('aria-expanded','false');
    trigger.setAttribute('aria-controls',DOM.chooserId);

    const mark=doc.createElement('span');
    mark.className='im-mark';
    let markMode='',markGlyph=glyph(doc,'',22);
    mark.appendChild(markGlyph);
    trigger.appendChild(mark);

    const textBox=doc.createElement('span');
    textBox.className='im-text';
    const eyebrow=doc.createElement('span');
    eyebrow.className='im-eyebrow';eyebrow.textContent='Mode';
    textBox.appendChild(eyebrow);
    const label=doc.createElement('span');
    label.id=DOM.labelId;label.className='im-label';
    textBox.appendChild(label);
    const sub=doc.createElement('span');
    sub.id=DOM.subId;sub.className='im-sub';
    textBox.appendChild(sub);
    trigger.appendChild(textBox);

    const wait=doc.createElement('span');
    wait.className='im-wait';wait.setAttribute('aria-hidden','true');
    trigger.appendChild(wait);
    const alert=doc.createElement('span');
    alert.className='im-alert';alert.setAttribute('aria-hidden','true');
    trigger.appendChild(alert);
    host.appendChild(trigger);

    const pop=doc.createElement('div');
    pop.id=DOM.chooserId;pop.className='im-pop';
    /* `role="menu"` + `role="menuitemradio"`, et **pas** `radiogroup` : dans un
       menu, les flèches déplacent le focus **sans choisir**. Dans un groupe de
       radios, traverser les options au clavier changerait le mode de Jarvis à
       chaque touche — un aller-retour serveur et un changement de comportement
       par flèche, que personne n'a demandé. Le contrôle Bare Hands a tranché
       ainsi pour la caméra ; la raison vaut mot pour mot ici. */
    pop.setAttribute('role','menu');
    pop.setAttribute('aria-label','Mode d’interaction de Jarvis');
    pop.hidden=true;
    const popTitle=doc.createElement('h3');
    popTitle.textContent='Mode d’interaction';
    pop.appendChild(popTitle);
    const note=doc.createElement('p');
    note.id=DOM.noteId;note.className='im-note';note.hidden=true;
    pop.appendChild(note);
    const opts=doc.createElement('div');
    opts.className='im-opts';
    pop.appendChild(opts);
    const hint=doc.createElement('p');
    hint.id=DOM.hintId;hint.className='im-hint';
    pop.appendChild(hint);
    host.appendChild(pop);

    const announce=doc.createElement('div');
    announce.id=DOM.announceId;announce.className='im-sr';
    announce.setAttribute('role','status');
    announce.setAttribute('aria-live','polite');
    host.appendChild(announce);

    /* Les pastilles sont **reconstruites depuis `modes`**, jamais écrites en
       dur : la liste des modes appartient au serveur, et une liste tenue ici
       finirait par ne plus être la sienne. Elles ne sont refaites que lorsque
       la signature du catalogue change, pour qu'une repeinture par seconde ne
       vole pas le focus de quelqu'un qui navigue au clavier. */
    let options=[],signature='';

    function buildOptions(){
      const next=view.options;
      const stamp=next.map(option=>`${option.value}:${option.reserved?1:0}`).join('|');
      if(stamp===signature)return;
      signature=stamp;
      while(opts.firstChild)opts.removeChild(opts.firstChild);
      options=next.map((option,index)=>{
        const el=doc.createElement('button');
        el.setAttribute('type','button');
        el.setAttribute('role','menuitemradio');
        el.setAttribute(DOM.modeAttribute,option.value);
        el.className='im-opt';
        el.setAttribute('aria-checked','false');
        el.setAttribute('tabindex','-1');
        const badge=doc.createElement('span');
        badge.className='im-opt-mark';
        badge.setAttribute('aria-hidden','true');
        badge.appendChild(glyph(doc,option.value,20));
        el.appendChild(badge);
        const box=doc.createElement('span');
        box.className='im-opt-text';
        const name=doc.createElement('span');
        /* Le texte est écrit par `paint`, pas ici : gravé une seule fois à la
           construction, un libellé changé côté serveur laissait le nom visible et
           le nom lu par un lecteur d'écran — celui-là refait à chaque peinture —
           se contredire. C'est la même faute que la projection périmée. */
        name.className='im-opt-name';
        box.appendChild(name);
        const state=doc.createElement('span');
        state.className='im-opt-state';
        box.appendChild(state);
        el.appendChild(box);
        const tag=doc.createElement('span');
        tag.className='im-opt-tag';
        el.appendChild(tag);
        const desc=doc.createElement('span');
        desc.className='im-sr';desc.id=`${DOM.descPrefix}${option.value}`;
        el.appendChild(desc);
        el.setAttribute('aria-describedby',desc.id);
        el.addEventListener('click',()=>{choose(option.value)});
        el.addEventListener('keydown',event=>onOptionKey(event,index));
        el.addEventListener('focus',()=>{cursor=index;paintHint(option.value)});
        el.addEventListener('mouseenter',()=>paintHint(option.value));
        el.addEventListener('focusout',scheduleOutsideClose);
        opts.appendChild(el);
        return {value:option.value,el,name,state,tag,desc};
      });
      if(cursor>=options.length)cursor=0;
    }

    trigger.addEventListener('click',()=>{opened?close({focus:true}):open()});
    trigger.addEventListener('keydown',onTriggerKey);
    trigger.addEventListener('focusout',scheduleOutsideClose);

    /* ------------------------------------------------------------ peinture */

    const waitSeconds=()=>pending?Math.max(0,(now()-pending.since)/1000):0;

    function optionOf(value){
      for(const option of view.options)if(option.value===value)return option;
      return null;
    }

    /* Ce que chaque mode **fait**, sous le sélecteur. Le texte vient du serveur
       (`summary`), pas d'une table recopiée ici : deux descriptions du même
       mode finiraient par se contredire. */
    function hintFor(value){
      const option=optionOf(value);
      if(!option)return '';
      const reserved=option.reserved
        ?' Ce mode est annoncé et réservé : il n’a pas encore de comportement, et le choisir ne change rien.'
        :'';
      return `${option.summary||option.label}${reserved}`;
    }

    function paintHint(value){hint.textContent=hintFor(value)}

    /* Le compteur de la demande en vol. Armé **par l'état**, comme le compteur
       de démarrage du contrôle Bare Hands, et désarmé dès que l'attente cesse.
       Il monte même quand les animations sont coupées. */
    function paintWaitClock(){
      if(!pending){
        if(waitTimer){disarm(waitTimer);waitTimer=0}
        return;
      }
      if(waitTimer)return;
      waitTimer=arm(()=>{
        if(!pending){disarm(waitTimer);waitTimer=0;return}
        paintClockText();
      },1000);
    }

    function paintClockText(){
      const seconds=waitSeconds();
      label.textContent=captionOf(view);
      sub.textContent=subOf(view,seconds);
      const said=labelOf(view,seconds);
      trigger.setAttribute('aria-label',said);
      trigger.setAttribute('title',said);
      if(opened)paintNote(seconds);
    }

    function paintNote(seconds){
      const said=noteOf(view,seconds,failure);
      note.hidden=!said;
      note.textContent=said?said.text:'';
      if(said)note.setAttribute('data-im-note',said.tone);
      else note.removeAttribute('data-im-note');
    }

    function paint(){
      /* **La projection est refaite ici, et nulle part ailleurs.** Elle dépend
         de deux choses — l'instantané canonique et la demande en vol — qui
         changent à des moments différents. La calculer seulement à l'arrivée
         d'un statut laissait le début d'une écriture peindre une vue d'avant
         la demande : le bouton restait immobile, sans compteur ni barre, et
         « ça travaille » redevenait indiscernable de « c'est figé ». Trouvé
         par `test_le_compteur_de_l_attente_monte_vraiment`. */
      view=viewOf(block,pending);
      buildOptions();
      host.setAttribute(DOM.toneAttribute,view.tone);
      host.setAttribute('data-im-mode',view.mode);
      host.setAttribute('data-im-live',view.live?'true':'false');
      host.setAttribute('data-im-busy',view.busy?'true':'false');
      host.setAttribute('data-im-diverged',view.diverged?'true':'false');
      trigger.setAttribute('aria-busy',view.busy?'true':'false');
      /* Le motif du bouton replié suit le mode **en vigueur**, et n'est refait
         que lorsque celui-ci change : le sondage repeint une fois par seconde,
         et reconstruire un SVG à chaque battement pour le même mode serait du
         travail pur perte. */
      if(markMode!==view.mode){
        markMode=view.mode;
        if(markGlyph&&typeof markGlyph.remove==='function')markGlyph.remove();
        markGlyph=glyph(doc,view.mode,22);
        mark.appendChild(markGlyph);
      }
      paintWaitClock();
      paintClockText();
      for(let i=0;i<options.length;i+=1){
        const option=options[i];
        const model=optionOf(option.value)||{};
        const on=option.value===view.selected;
        option.el.setAttribute('aria-checked',on?'true':'false');
        option.el.setAttribute(DOM.reservedAttribute,model.reserved?'true':'false');
        option.el.setAttribute(DOM.storedAttribute,model.stored?'true':'false');
        /* `aria-disabled` et non `disabled` pour un mode réservé : il reste
           atteignable, donc capable de dire pourquoi. `disabled`, en revanche,
           est juste pendant une écriture en vol : il n'y a alors rien à
           expliquer qui ne soit déjà dans le bandeau et le compteur, et un
           second clic partirait une seconde demande. */
        option.el.disabled=view.busy;
        option.el.setAttribute('aria-disabled',model.reserved||view.busy?'true':'false');
        option.name.textContent=model.label||option.value;
        option.desc.textContent=hintFor(option.value);
        option.state.textContent=model.reserved
          ?`Réservé · ${model.status||'prévu'}`
          :on?'En vigueur':'';
        option.tag.textContent=model.stored&&!on?'Choisi':'';
        option.el.setAttribute('aria-label',
          `${model.label||option.value}${model.reserved?' — réservé, sans comportement'
            :on?' — mode en vigueur':''}${model.stored&&!on?' — mode enregistré':''}`);
        option.el.setAttribute('tabindex',i===cursor?'0':'-1');
      }
      /* Le curseur vaut le mode courant tant que personne n'a déplacé le focus. */
      if(!opened){
        const at=options.findIndex(option=>option.value===view.selected);
        cursor=at<0?0:at;
        for(let i=0;i<options.length;i+=1)
          options[i].el.setAttribute('tabindex',i===cursor?'0':'-1');
      }
      paintNote(waitSeconds());
      if(!hint.textContent&&options.length)
        paintHint(view.selected||options[Math.min(cursor,options.length-1)].value);
      speak();
    }

    /* Ce que le lecteur d'écran entend, et **seulement quand ça change** : une
       région vivante qui répète le même mot à chaque repeinture cesse d'être
       écoutée. */
    function speak(){
      /* Un refus en cours **est** ce qu'il y a à dire, et il le reste jusqu'à
         ce que quelque chose change vraiment. Sans cette priorité, la
         repeinture qui suit immédiatement un refus réécrivait la région vivante
         avec la phrase ordinaire : l'utilisateur d'un lecteur d'écran
         n'entendait jamais pourquoi son choix n'avait pas été pris. */
      const line=failure&&failure.text?failure.text
        :view.busy?`Changement vers ${view.pendingLabel} demandé.`
        :view.tone===TONE.UNKNOWN?'Mode d’interaction inconnu : statut illisible.'
        :!view.live?`Mode d’interaction ${view.label} — non confirmé par Core.`
        :view.diverged?`Mode d’interaction ${view.label} en vigueur, ${view.storedLabel} choisi.`
        :`Mode d’interaction ${view.label}.`;
      if(line===spoken)return;
      spoken=line;announce.textContent=line;
    }

    /* --------------------------------------------------------- ouverture */

    function open(){
      if(opened)return false;
      opened=true;
      pop.hidden=false;
      trigger.setAttribute('aria-expanded','true');
      paintNote(waitSeconds());
      if(options.length){paintHint(options[cursor].value);focusAt(cursor)}
      return true;
    }

    function close(options_){
      if(!opened)return false;
      /* Le refus a été lu, ou l'utilisateur est parti : dans les deux cas il
         cesse d'être ce qu'il y a de plus important à dire. Rien ne l'effaçait
         tant que le mode en vigueur ne bougeait pas — et après un REUNION refusé
         sur place le mode ne bouge jamais, si bien qu'un Core devenu injoignable
         ensuite restait masqué derrière une phrase périmée. */
      failure='';
      opened=false;
      pop.hidden=true;
      trigger.setAttribute('aria-expanded','false');
      if(options_&&options_.focus&&typeof trigger.focus==='function')
        try{trigger.focus()}catch(_error){/* retiré entre-temps */}
      return true;
    }

    function focusAt(index){
      if(!options.length)return;
      cursor=(index+options.length)%options.length;
      for(let i=0;i<options.length;i+=1)
        options[i].el.setAttribute('tabindex',i===cursor?'0':'-1');
      const target=options[cursor].el;
      if(typeof target.focus==='function')try{target.focus()}catch(_error){/* retiré entre-temps */}
      paintHint(options[cursor].value);
    }

    function onTriggerKey(event){
      const key=event&&event.key;
      if(key==='Escape'&&opened){event.preventDefault();close({focus:true});return}
      if(key!=='ArrowDown'&&key!=='ArrowUp')return;
      event.preventDefault();
      if(!opened)open();
      else focusAt(key==='ArrowDown'?cursor+1:cursor-1);
    }

    function onOptionKey(event,index){
      const key=event&&event.key;
      if(key==='Escape'){event.preventDefault();close({focus:true});return}
      if(key==='Home'||key==='End'){event.preventDefault();focusAt(key==='Home'?0:options.length-1);return}
      const step=key==='ArrowRight'||key==='ArrowDown'?1
        :key==='ArrowLeft'||key==='ArrowUp'?-1:0;
      if(!step)return;
      event.preventDefault();
      focusAt(index+step);
    }

    /* Le focus a quitté le contrôle : le sélecteur se ferme. Vérifié **après**
       que le focus a atterri — `focusout` part avant que `activeElement` ne soit
       à jour, et refermer trop tôt volerait le clic en cours. */
    function scheduleOutsideClose(){
      later(()=>{
        if(!opened)return;
        const at=doc.activeElement;
        if(at===trigger)return;
        for(const option of options)if(option.el===at)return;
        close({focus:false});
      },0);
    }

    /* ------------------------------------------------------------- choix */

    /* Ce qu'un refus veut dire, sous sa cause réelle. Le code stable vient de
       l'en-tête `X-Jarvis-Error-Code` ; le message du serveur est conservé tel
       quel derrière, parce qu'il dit des choses que cette page ne sait pas. */
    function refusalOf(error){
      const code=error&&error.code?String(error.code):'';
      const status=error&&typeof error.status==='number'?error.status:0;
      const said=(error&&error.message)||String(error||'');
      if(status===503)
        /* **Enregistré, pas appliqué.** Le disque a la préférence ; seul Core ne
           l'a pas encore. Dire « échec » ferait recommencer pour rien. */
        /* Le texte du serveur dit déjà « Mode X enregistré, mais pas encore
           appliqué : … » ; le préfixer une seconde fois faisait un bandeau qui
           se répétait mot pour mot. */
        return {tone:'warn',text:said,
          level:'warn',code:code||'interaction_mode_not_applied'};
      if(status===409)
        return {tone:'warn',
          text:REFUSAL[code]||said||'Ce mode n’a pas encore de comportement.',
          level:'warn',code:code||'interaction_mode_not_implemented'};
      if(REFUSAL[code])
        return {tone:'bad',text:`${REFUSAL[code]} (${code})`,level:'error',code};
      return {tone:'bad',
        text:`Le changement de mode a échoué : ${said}`,
        level:'error',code:code||`http_${status||0}`};
    }

    function refuse(said,event,data,options_){
      failure=Object.freeze({text:said.text,tone:said.tone||'bad'});
      log(said.level||'error',event,data);
      announce.textContent=said.text;spoken=said.text;
      /* **Le refus se voit.** Le sélecteur s'était refermé sur le choix ; il se
         rouvre sur la phrase qui dit pourquoi, là où l'utilisateur vient de
         cliquer. Une région vivante seule ne parle qu'aux lecteurs d'écran.

         Sauf quand le refus arrive **longtemps** après le geste : au bout des
         douze secondes de l'échéance, l'utilisateur est ailleurs, et lui reprendre
         le focus serait lui arracher ce qu'il est en train de faire. La page a une
         infusion pour exactement cela, que quatre autres modules utilisent. */
      if(options_&&options_.quiet===true){
        if(toast)toast({title:'Mode d’interaction',sub:said.text,
          kind:said.tone==='bad'?'bad':'warn'});
      }else open();
      paintNote(waitSeconds());
    }

    /* Choisir. Rien n'est peint d'avance : on demande, on attend la réponse,
       puis on **redemande le statut canonique** et on laisse celui-ci peindre.
       Un échec laisse donc le mode canonique précédent coché sans qu'il y ait
       quoi que ce soit à défaire. */
    async function choose(value){
      if(choosing)return null;
      const option=optionOf(value);
      if(!option)
        throw Object.assign(new Error(`mode d’interaction inconnu : ${value}`),
          {code:'interaction_mode_hud_unknown'});
      failure='';
      if(option.reserved){
        /* Réservé : refusé **ici**, sans aller-retour. Le serveur répondrait 409
           avec le même sens ; faire l'appel ferait passer une réserve assumée
           pour une panne, et le chemin d'écriture garde de toute façon sa
           branche 409 pour le cas où ce catalogue vieux d'une seconde se
           tromperait. */
        close({focus:true});
        refuse({text:`${option.label} : ${REFUSAL.interaction_mode_not_implemented}`,
          tone:'warn',level:'info'},'interaction_mode.reserved_refused',
          {mode:value,status:option.status||null});
        paint();
        return null;
      }
      if(!request){
        close({focus:true});
        refuse({text:'La page ne peut pas écrire le mode : la porte réseau manque.',
          tone:'bad',level:'error'},'interaction_mode.request_gate_missing',{mode:value});
        paint();
        return null;
      }
      choosing=true;
      pending={mode:value,since:now()};
      close({focus:true});
      paint();
      /* RÈGLE ZÉRO, seconde mesure : l'attente a une borne. `fetch` n'en a pas,
         et un transport « qui finit toujours par répondre » ne suffit pas — un
         écran sans issue est le défaut. Passé le délai, on rend la main et le
         statut canonique dira ce qui a réellement eu lieu. */
      let expired=false;
      const ticket=later(()=>{
        waits.delete(ticket);
        if(!pending)return;
        expired=true;
        const waited=Math.round(waitSeconds());
        pending=null;choosing=false;
        refuse({text:`La demande de ${option.label} n’a pas répondu au bout de ${waited} s. `
          +'Le mode affiché reste celui que le serveur confirme ; réessayez.',
          tone:'bad',level:'error'},'interaction_mode.request_timeout',
          {mode:value,waited_s:waited},{quiet:true});
        paint();
      },WRITE_DEADLINE_MS);
      waits.add(ticket);
      try{
        await request(WRITE_PATH,{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({mode:value}),
        });
        if(expired)return null;
        log('info','interaction_mode.requested',{mode:value});
        /* On ne peint pas la réponse : on redemande le statut, qui est la seule
           source de cette page. Une écriture réussie dont le statut suivant
           dirait autre chose doit afficher ce que dit le statut. */
        await reread();
        return value;
      }catch(error){
        if(expired)return null;
        const said=refusalOf(error);
        /* Le statut est relu **aussi** après un refus : un 503 a écrit la
           préférence sur le disque, et la divergence « choisi / en vigueur »
           doit apparaître tout de suite plutôt qu'à la seconde suivante. */
        pending=null;
        await reread();
        refuse(said,'interaction_mode.refused',
          {mode:value,code:said.code,status:(error&&error.status)||null,
           error:String((error&&error.message)||error)});
        return null;
      }finally{
        if(waits.delete(ticket))unlater(ticket);
        if(!expired){
          pending=null;choosing=false;
          paint();
        }
      }
    }

    /* Redemander le statut canonique, sans jamais faire tomber le contrôle si
       la page n'a pas de relecture à offrir : le sondage à 1 Hz repassera. */
    async function reread(){
      if(!refresh)return false;
      try{await refresh();return true}
      catch(error){
        log('warn','interaction_mode.refresh_failed',
          {error:String((error&&error.message)||error)});
        return false;
      }
    }

    /* ----------------------------------------------------------- couture */

    /* La porte que `refreshStatus` appelle chaque seconde, avec le bloc
       `interaction_mode` du statut. C'est le **seul** chemin par lequel le mode
       affiché change. */
    function gate(next){
      const before=view.mode;
      block=isObject(next)?next:null;
      paint();
      /* Un refus cesse d'être vrai dès que le mode en vigueur bouge : « ce mode
         n'a pas été pris » n'a plus de sens quand le statut montre autre chose.
         Il survit en revanche à un 503, où le mode **ne bouge pas** et où la
         phrase « enregistré, pas encore appliqué » reste exacte. */
      if(failure&&view.mode&&view.mode!==before){failure='';paint()}
      return view;
    }

    /* Le sondage lui-même est tombé : on ne sait plus rien, et c'est ce qui
       s'affiche. Garder la dernière valeur connue serait la présenter comme
       vivante alors que plus rien ne la confirme. */
    function statusLost(){
      block=null;
      paint();
      return view;
    }

    gate(null);

    return {
      element:host,trigger,chooser:pop,
      gate,statusLost,choose,open,close,
      isOpen:()=>opened,
      waits:()=>waits.size,
      /* Ce que l'écran **peint**, par opposition à ce que le serveur dit : les
         deux doivent coïncider, et c'est la seule façon de le vérifier sans
         lire des pixels. */
      presentation:()=>view,
      failure:()=>failure,
      waitSeconds,
    };
  }

  /* Le nom de cet export n'est **pas** `api` : la page sert tous ses modules
     dans une seule balise `<script>`, et `api` y est déjà sa porte réseau
     (`control_center.html`). Un `const api` ici l'aurait masquée pour ce
     module — et le bloc d'installation, qui la cherche par ce nom, aurait
     trouvé cet objet à la place et conclu qu'aucune écriture n'était possible.
     C'est arrivé à l'écriture de ce fichier ; le nom distinct est la
     correction. */
  const MODE_API=Object.freeze({
    DOM,TONE,GEO,STYLE,REFUSAL,SUB,GLYPH,WRITE_PATH,WRITE_DEADLINE_MS,
    viewOf,optionsOf,captionOf,subOf,labelOf,noteOf,glyph,installStyle,createModeControl});
  root.JarvisInteractionMode=MODE_API;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=MODE_API;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  function installJarvisInteractionMode(){
    /* L'emplacement est **déclaré dans la page**, pas fabriqué ici : c'est lui
       qui porte le rang d'empilement du registre de `control_center.html`, et un
       contrôle qui se poserait tout seul au bout du `body` en sortirait sans que
       rien ne le dise. Absent, on refuse sous un nom cherchable. */
    const host=document.getElementById(DOM.hostId);
    if(!host)
      throw Object.assign(
        new Error(`JarvisInteractionMode : l’emplacement #${DOM.hostId} manque dans control_center.html`),
        {code:'interaction_mode_host_missing'});
    const control=createModeControl({
      document,host,
      now:()=>Date.now(),
      setInterval:(fn,ms)=>window.setInterval(fn,ms),
      clearInterval:id=>window.clearInterval(id),
      setTimeout:(fn,ms)=>window.setTimeout(fn,ms),
      clearTimeout:id=>window.clearTimeout(id),
      /* Les deux portes de la page, **passées plutôt que prises**. Ce sont des
         déclarations de fonction du même `<script>`, donc remontées ; elles sont
         enveloppées pour que l'appel parte au clic et non à l'insertion. */
      request:typeof api==='function'?(path,init)=>api(path,init):undefined,
      refresh:typeof refreshStatus==='function'?()=>refreshStatus():undefined,
      toast:typeof toast==='function'?spec=>toast(spec):undefined,
      log:(level,event,data)=>{
        const line=`[mode] ${event} ${JSON.stringify(data)}`;
        if(level==='error')console.error(line);
        else if(level==='warn')console.warn(line);
        else console.info(line);
      },
    });
    window.JarvisInteractionModeControl=Object.freeze({
      /* Les deux portes du sondage à 1 Hz, du même nom que celles de la scène et
         du canal de commandes : la page n'apprend pas un second vocabulaire. */
      gate:control.gate,statusLost:control.statusLost,
      presentation:control.presentation,
      isOpen:control.isOpen,open:control.open,close:control.close,
      choose:control.choose,failure:control.failure,
    });
    console.info('[mode] interaction_mode.hud_installed '
      +JSON.stringify({host:DOM.hostId}));
  }

  /* Le refus est **rattrapé ici** : la page servie concatène tous ses modules
     dans une seule balise `<script>`, et une levée qui remonterait emporterait
     la scène, la chronologie et le Test Lab avec elle. */
  try{installJarvisInteractionMode()}
  catch(error){
    console.error('[mode] interaction_mode.install_failed '
      +JSON.stringify({code:(error&&error.code)||null,
        error:String((error&&error.message)||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
