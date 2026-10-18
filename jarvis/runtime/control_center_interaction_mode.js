/* Mode d'interaction — le bouton d'état du bas-gauche et son détail. **Affichage seul.**

   Slice 03 de `jarvis-presentation-interaction-mode`, rendu inerte par la Slice
   01b de `jarvis-board-ui-wheel-dossier-refactor`. Le contrat vit dans
   `docs/interaction-mode.md` : le mode **suit le type du Board actif** (Assistant
   → SIMPLE, Présentation → PRESENTATION, Réunion → REUNION annoncé, qui se
   comporte en SIMPLE). Il ne se choisit plus ici : ce module **montre** ce que
   `GET /api/status` → `interaction_mode` dit, et la séance que Voice rapporte.
   Le retrait visuel de ce contrôle appartient à la Slice 02.

   **Aucun chemin d'écriture, par construction.** Le module ne reçoit aucune
   porte réseau. Les pastilles restent listées, atteignables au clavier et
   marquées `aria-disabled` : choisir l'une d'elles n'envoie rien et dit, à
   l'endroit du clic, que le mode suit le type du Board et comment présenter
   (ouvrir ou créer un Board Présentation). Le serveur refuserait de toute
   façon (409 `interaction_mode_derived`) ; faire l'appel ferait passer une règle
   assumée pour une panne.

   **Aucun état local du mode.** Une seconde mémoire du mode dans le navigateur
   divergerait le jour où une bascule de Board ou une lecture du Studio le
   change, et l'écran mentirait sans que rien ne tombe. Le mode affiché vient
   **toujours** du dernier `/api/status`, jamais d'un clic. Ce que ce module
   tient est de l'affichage : l'ouverture du détail, le curseur clavier et la
   dernière phrase d'explication.

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
     **repli local** nommé (`source: "local"`, `core_reachable: false`,
     `revision: null`) : le comportement du type du Board quand il est connu,
     et non la vérité vivante. Gris désaturé **et bordure en tirets**, parce qu'une
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
   décide ce qui est dit réservé.

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
   La porte reçoit aussi, en second argument, le relevé `presentation` du même
   statut (Slice 10, P7) : la séance que Voice rapporte, rendue sous le mode.
   Généraliser une couture aurait voulu dire toucher `control_center_barehands.js`
   et inventer un mécanisme que rien d'autre n'utiliserait, pour gagner au mieux
   une seconde de latence sur un réglage que l'on change deux fois par jour.
   Le prix payé est écrit : jusqu'à une seconde entre le changement et son
   affichage. */
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
    /* La ligne de la séance PRESENTATION (`/api/status.presentation`). */
    presenceId:'interactionModePresence',
    presenceAttribute:'data-im-presence',
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
       jamais activable) et/ou désignée par le type du Board actif (qui peut
       différer de ce qui tourne). Deux faits distincts, deux attributs. */
    reservedAttribute:'data-im-reserved',
    boardAttribute:'data-im-board',
  });

  /* Les présentations. Les deux premières sont des modes en vigueur ; les deux
     dernières sont des états que l'on subit et que l'on ne choisit pas.
     `OTHER` existe pour qu'un mode ajouté par un serveur plus récent s'affiche
     sous son propre libellé au lieu d'être peint comme un mode connu. */
  const TONE=Object.freeze({
    ASSISTANT:'assistant',PRESENTATION:'presentation',
    OTHER:'other',UNCONFIRMED:'unconfirmed',UNKNOWN:'unknown'});

  /* Ce qu'un choix dit au lieu de partir : la phrase du refus serveur
     (`INTERACTION_MODE_DERIVED_MESSAGE`, `jarvis/domain/interaction_mode.py`),
     mot pour mot — un test refuse la divergence. `NOTE_DERIVED` est la ligne de
     repos du détail, quand rien de plus urgent n'est à dire. */
  const DERIVED='Le mode d\'interaction suit le type du Board actif : il ne se règle plus à part. '
    +'Pour présenter, ouvrez ou créez un Board Présentation ; pour revenir au mode simple, '
    +'ouvrez un Board Assistant. Rien n\'a été changé.';
  const NOTE_DERIVED='Le mode suit le type du Board actif. Pour présenter, ouvrez ou créez un Board Présentation.';

  /* Ce que les états d'attente disent, en un mot, sous le libellé du mode. */
  const SUB=Object.freeze({
    unknown:'STATUT INDISPONIBLE',
    unconfirmed:'NON CONFIRMÉ',
  });

  /* La séance PRESENTATION **telle que Voice la rapporte** (handoff
     `jarvis-presentation-interaction-mode`, Slice 03 de 2026-10, sur le relevé
     publié par la Slice 10, P7 : `/api/status.presentation`).

     Le mode en vigueur dit ce que Core a décidé ; ce relevé dit ce que Voice en
     a fait. Les deux divergent exactement dans les cas qui comptent : un
     PRESENTATION refusé par l'architecture vocale, une entrée qui n'a pas pu
     prendre le micro, une séance ouverte mais sourde à la salle. Sans cette
     ligne, le bouton disait « PRESENTATION » en ambre pendant que personne
     n'écoutait.

     Cinq états, et `null` quand Voice est hors ligne (le Control Center rend
     alors `presentation: null`) :

     - `listening` — une séance vit (`active`) et la voie ambiante entend ;
     - `deaf` — une séance vit mais `ambient_deaf` : la transcription ambiante
       manque, seule l'adresse explicite est entendue ;
     - `refused` — `event: "refused"` : l'architecture vocale ne porte pas
       PRESENTATION (session continue requise, Duplex exclu) ;
     - `entry_failed` — `event: "entry_failed"` : le micro partagé n'a pas pu
       s'ouvrir ;
     - `inactive` — aucune séance.

     **Refus et échec ne valent que tant que le mode en vigueur est
     PRESENTATION.** Le coordinateur ne republie pas son relevé quand le mode
     quitte PRESENTATION après un refus (il n'y a pas de séance à fermer) : le
     fichier garde `event: "refused"` en SIMPLE. Le croire peindrait un refus
     qui n'est plus vrai.

     Le texte appartient à l'écran ; le code (`last_failure_code`,
     `blocker_code`) est rendu tel quel dans `title`, parce que c'est lui que
     l'on cherche dans la trace. */
  const PRESENCE=Object.freeze({
    LISTENING:'listening',DEAF:'deaf',REFUSED:'refused',
    ENTRY_FAILED:'entry_failed',INACTIVE:'inactive'});
  const PRESENCE_TEXT=Object.freeze({
    listening:Object.freeze({line:'Écoute la salle',tone:'live',
      said:'Séance PRESENTATION : Jarvis écoute la salle.'}),
    deaf:Object.freeze({line:'Sourd à la salle',tone:'warn',
      now:'la séance est sourde à la salle, seul ce qui est adressé à Jarvis est entendu',
      said:'Séance PRESENTATION ouverte mais sourde à la salle : la transcription '
        +'ambiante est indisponible. Jarvis n’entend que ce qui lui est adressé.'}),
    refused:Object.freeze({line:'Refusé par la voix',tone:'bad',
      now:'aucune séance ne tourne, la voix a refusé PRESENTATION',
      said:'PRESENTATION refusé : l’architecture vocale ne le porte pas (une session '
        +'continue est requise, le Duplex est exclu). Changez-la dans l’onglet Mode vocal.'}),
    entry_failed:Object.freeze({line:'Entrée échouée',tone:'bad',
      now:'aucune séance ne tourne, le micro partagé n’a pas pu s’ouvrir',
      said:'PRESENTATION n’a pas pu ouvrir le micro partagé : Jarvis reste adressable, '
        +'mais n’écoute pas la salle.'}),
    inactive:Object.freeze({line:'Séance inactive',tone:'idle',
      said:'Aucune séance PRESENTATION ne tourne encore.'}),
  });

  /* ------------------------------------------------------- vue, sans DOM */

  const isObject=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
  const text=value=>value===undefined||value===null?'':String(value);

  /* Le catalogue des modes, tel que le statut le publie. Aucun mode n'est
     écrit en dur ici : un mode absent de `modes` n'est pas proposé, et un mode
     que le serveur ajoutera apparaîtra sans que cette page change. */
  function optionsOf(block){
    const raw=isObject(block)&&Array.isArray(block.modes)?block.modes:[];
    const board=isObject(block)?text(block.board_mode):'';
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
        /* Le mode que désigne le type du Board actif, qui n'est pas forcément
           ce qui tourne : un Board Réunion garde `REUNION` visible ici alors que
           le mode effectif rapporte SIMPLE (décision 02) ; une lecture du Studio
           tient PRESENTATION sur un Board Assistant. */
        board:!!board&&board===value,
      }));
    }
    return Object.freeze(options);
  }

  /* **Un refus d'avant la bascule n'est pas un refus de cette bascule** (p17).

     Le coordinateur écrit `refused` / `entry_failed` une seule fois, à la
     bascule, et ne le republie pas : le fichier garde donc le refus d'une
     séance précédente jusqu'à ce que Voice réagisse à la nouvelle. Pendant ce
     trou, le croire peindrait un refus qui ne concerne pas ce choix-ci.

     La borne n'est **pas** le battement qui a montré PRESENTATION : Voice
     réagit à l'événement de Core en quelques millisecondes, souvent avant le
     sondage suivant (1 Hz) — un vrai refus serait alors plus ancien que ce
     battement, et il resterait caché pour toujours puisqu'il n'est jamais
     republié. La borne est le **dernier battement qui montrait encore un autre
     mode, confirmé par Core** : Core n'avait pas encore basculé quand ce statut
     a été lu, donc un relevé écrit avant lui est forcément d'avant. Moins
     `STALE_REPORT_MARGIN_S`, pour le temps entre la lecture du mode par le
     serveur et l'arrivée de la réponse dans la page.

     Sans borne connue (page ouverte directement en PRESENTATION) ou sans `ts`,
     rien ne permet de dater : le relevé est cru. `ts` est l'heure murale de
     Voice, la borne celle de la page : même machine (le Control Center est
     servi en local). Pur. */
  const STALE_REPORT_MARGIN_S=2;
  function freshReport(report,otherModeSeenAtS){
    if(!isObject(report))return report;
    if(report.event!=='refused'&&report.event!=='entry_failed')return report;
    if(typeof otherModeSeenAtS!=='number'||!Number.isFinite(otherModeSeenAtS))return report;
    const ts=report.ts;
    if(typeof ts!=='number'||!Number.isFinite(ts))return report;
    if(ts>=otherModeSeenAtS-STALE_REPORT_MARGIN_S)return report;
    return Object.freeze({...report,event:'stale',last_failure_code:null});
  }

  /* Le relevé PRESENTATION, traduit en un état. Pur. `mode` est le mode en
     vigueur que le même statut rapporte. Rend `null` quand il n'y a pas de
     relevé — Voice hors ligne : on ne sait rien, et rien ne s'affiche. */
  function presenceOf(report,mode){
    if(!isObject(report))return null;
    const code=value=>typeof value==='string'&&value?value:'';
    let state=PRESENCE.INACTIVE,why='';
    if(report.active===true){
      state=report.ambient_deaf===true?PRESENCE.DEAF:PRESENCE.LISTENING;
      /* Un blocage nommé (transcription ou préparation indisponible) est le
         code qui explique une séance diminuée. */
      why=code(report.blocker_code);
    }else if(mode===TONE.PRESENTATION&&report.event==='refused'){
      state=PRESENCE.REFUSED;why=code(report.last_failure_code);
    }else if(mode===TONE.PRESENTATION&&report.event==='entry_failed'){
      state=PRESENCE.ENTRY_FAILED;why=code(report.last_failure_code);
    }
    const said=PRESENCE_TEXT[state];
    return Object.freeze({
      state,code:why,line:said.line,said:said.said,tone:said.tone,
      /* `inactive` en SIMPLE est l'état ordinaire : le dire en permanence sur
         le bouton serait un bandeau que plus personne ne lit. Il reste porté
         par `data-im-presence`. En PRESENTATION, il est dit : le mode est en
         vigueur et aucune séance ne tourne encore. */
      shown:!(state===PRESENCE.INACTIVE&&mode!==TONE.PRESENTATION),
    });
  }

  /* Ce que `/api/status` publie, traduit en ce que l'écran doit peindre. Pur :
     aucune lecture de page, aucune horloge, aucun réseau — c'est ce que les
     tests exercent sans navigateur.

     `report` est le relevé `presentation` du **même** statut ; un clic ne
     l'écrit jamais. */
  function viewOf(block,report){
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
    const board=has?text(block.board_mode):'';
    const error=has&&isObject(block.error)?block.error:null;
    return Object.freeze({
      tone,
      mode,
      label:has?text(block.label):'',
      /* La pastille cochée. **Aucune** tant que Core ne confirme pas, et
         **aucune** sur un mode réservé : dans les deux cas, cocher afficherait
         comme autoritaire une valeur que personne ne garantit. */
      selected:live&&known&&!known.reserved?known.value:null,
      live,
      board,
      boardLabel:has?text(block.board_mode_label):'',
      /* Type du Board et mode effectif divergent : c'est un fait à montrer, pas
         à arbitrer. Il arrive pour un Board Réunion (réservé, jamais effectif)
         et pendant une lecture du Studio (mode transitoire, restauré). */
      diverged:!!board&&!!mode&&board!==mode,
      reason:error?text(error.code):'',
      options,
      presence:presenceOf(report,mode),
    });
  }

  /* La séance, quand elle mérite d'être dite. */
  const presenceShown=view=>!!view.presence&&view.presence.shown;

  /* Le libellé du bouton replié : le mode **en vigueur**, jamais la préférence.
     Quand rien n'est connu, il le dit au lieu de retomber sur un défaut
     plausible. */
  function captionOf(view){
    if(view.tone===TONE.UNKNOWN)return 'MODE ?';
    return view.label||view.mode.toUpperCase()||'MODE ?';
  }

  /* La seconde ligne du bouton : ce qu'il faut savoir sans ouvrir le détail. */
  function subOf(view){
    if(view.tone===TONE.UNKNOWN)return SUB.unknown;
    const kind=view.diverged?`BOARD : ${view.boardLabel||view.board.toUpperCase()}`:'';
    /* **Les deux, et non l'un ou l'autre** : un Board Réunion ne disparaît pas
       du bouton quand Core devient injoignable (décision 02). */
    if(!view.live)return kind?`${SUB.unconfirmed} · ${kind}`:SUB.unconfirmed;
    return kind;
  }

  /* L'infobulle du bouton (p20) : **courte**, et jamais la copie du nom
     accessible — une phrase de trois lignes en infobulle double ce que le
     lecteur d'écran dit déjà. Elle garde le code d'échec, que l'on cherche
     dans la trace. */
  function titleOf(view){
    const session=presenceShown(view)?view.presence:null;
    return `Mode : ${captionOf(view)}`
      +(session?` · ${session.line}${session.code?` (${session.code})`:''}`:'');
  }

  /* La phrase lue par les lecteurs d'écran. Elle dit
     l'état, sa cause quand il y en a une, et **comment en sortir**. */
  function labelOf(view){
    /* La séance, quand elle est dite, se place **avant** l'action : un lecteur
       d'écran entend l'état entier, puis ce que le bouton fait. */
    const session=presenceShown(view)?` ${view.presence.said}`:'';
    const action=`${session} Ouvrir le détail du mode.`;
    if(view.tone===TONE.UNKNOWN)
      return `Mode d’interaction inconnu : le statut de Jarvis n’est pas lisible.${action}`;
    if(!view.live)
      return `Mode d’interaction : ${view.label||view.mode} — non confirmé par Core.`
        +`${view.diverged?` ${view.boardLabel||view.board} est le mode du type du Board.`:''}`
        +action;
    /* Le nom commence par ce que le bouton montre (« MODE » puis le libellé) : WCAG 2.5.3, la commande vocale
       « cliquer Mode Assistant » la trouve (orbital-ui Slice 09, relevé par axe-core). */
    if(view.diverged)
      return `Mode ${view.label} : mode d’interaction en vigueur ; `
        +`${view.boardLabel||view.board} est le mode du type du Board.${action}`;
    return `Mode ${view.label} : mode d’interaction en vigueur.${action}`;
  }

  /* Le bandeau du détail. L'ordre est celui de l'urgence : l'explication d'un
     choix que l'on vient de faire passe avant un état durable, et la ligne de
     repos (`NOTE_DERIVED`) ne vient qu'en dernier. */
  function noteOf(view,failure){
    /* L'explication porte **son** ton : une règle assumée ne se peint pas comme
       une panne. */
    if(failure&&failure.text)
      return Object.freeze({tone:failure.tone||'bad',text:failure.text});
    if(view.tone===TONE.UNKNOWN)
      return Object.freeze({tone:'bad',
        text:'Le statut de Jarvis n’est pas lisible : le mode affiché n’est pas connu.'});
    if(!view.live)
      /* Le serveur rend alors le mode qui *s'appliquerait* (le comportement du
         type du Board), pas le mode en vigueur : le bandeau dit ce que la valeur
         est, et nomme le type du Board à côté quand il en diverge. */
      return Object.freeze({tone:'wait',
        text:'Core est injoignable. La valeur affichée est le mode qui '
          +`s’appliquerait, pas le mode en vigueur${view.reason?` (${view.reason})`:''}.`
          +`${view.diverged?` Type du Board : ${view.boardLabel||view.board}.`:''}`
          +' Le mode suivra le type du Board actif dès que Core répondra.'});
    /* Un catalogue vide n'est pas un détail vide sans explication. */
    if(!view.options.length)
      return Object.freeze({tone:'warn',
        text:'Ce serveur n’annonce aucun mode.'});
    /* Une séance refusée, ratée ou sourde est ce qu'il faut savoir d'abord :
       le code suit la phrase, pour qu'on le retrouve dans la trace. */
    const session=view.presence;
    if(session&&session.shown&&(session.tone==='bad'||session.tone==='warn'))
      return Object.freeze({tone:session.tone,
        text:`${session.said}${session.code?` (${session.code})`:''}`});
    if(view.diverged)
      return Object.freeze({tone:'warn',
        text:`Type du Board : ${view.boardLabel||view.board}. En vigueur : ${view.label}.`});
    return Object.freeze({tone:'info',text:NOTE_DERIVED});
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
     s'est déjà décalé. D'où deux barreaux, et jamais un troisième : au-delà,
     c'est le rail lui-même qui est trop chargé, et le répartir n'appartient à
     aucun de ses occupants pris isolément.

     **Le second barreau est engagé dès que Bare Hands est monté, et il y reste.**
     `shell.mount()` crée le mot d'un geste étouffé une fois pour toutes et ne
     fait qu'en basculer le `display` ; `:has()` ne voit pas `display:none`, donc
     `body:has(…jh-note)` est vrai en permanence à partir du montage. Le premier
     barreau est par conséquent inatteignable dans le cas Bare Hands : le
     contrôle passe de 22 à 86 d'un coup, au montage, et ne bouge plus.

     **C'est le bon comportement, et il ne faut pas le rendre réactif.** Un mot
     de geste étouffé apparaît exactement quand l'utilisateur est en train de
     faire un geste ; un contrôle qui sauterait de 34 px à cet instant précis
     serait bien pire qu'un contrôle 34 px trop prudent en permanence. On paie
     34 px de marge pour ne jamais bouger sous la main de quelqu'un. Le premier
     barreau sert donc à la scène seule, qui elle n'a pas de mot transitoire. */
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
    /* Depuis la Slice 06 de l'orbital UI, c'est le centre d'état du bas
       (`--shell-bottom` + `--shell-status-h` : jusqu'à 62 px) qui tient cette
       place ; le relèvement de 42 px passe au-dessus (64 px). Historique —
       l'indication vocale était centrée en bas à **toutes** les largeurs
       (`left:50%; bottom:22px`), et la page ne la déplaçait jamais. Son texte le
       plus long — `F9 · VOICE HORS LIGNE` — fait environ 230 px, donc sous
       plus long — `F9 · VOICE HORS LIGNE` — fait 200 px mesures, et le bord
       droit de ce bouton est a 195 px : ils ne se rencontreraient donc qu'en
       dessous de ~708 px de large. **Le seuil reste a 820 px quand meme**, et
       volontairement : etre en avance ne coute rien, une marge se garde, et un
       nombre serre se casse au premier libelle plus long. Le commentaire disait
       auparavant que la rencontre avait lieu sous 820 px, ce qui etait faux. */
    liftBelow:820,narrowBelow:700,lift:42,
    /* **Sous 700 px, le rail gauche est perdu, et il faut en sortir.**
       A cette largeur la colonne Bare Hands devient relative au centre
       (`top:calc(50% + …)`) et la hauteur de sa palette depend du nombre
       d'outils installes : aucun `body:has()` ne peut calculer ce degagement,
       et le relevement du rail rend meme la chose PIRE, puisqu'il enfonce ce
       bouton plus loin dans la palette. Mesure en navigateur reel a trois
       hauteurs, palette de trois outils : recouvrement de 64x46 a 700x600,
       64x60 a 700x750 et encore 64x24 a 700x900 — donc a toutes les hauteurs,
       et pas seulement sur un ecran court. Le bouton etant au rang 32 et la
       palette au rang 30, c'est l'outil du bas qui devenait incliquable : une
       regression de Bare Hands causee par ce controle.

       La solution n'est pas verticale mais **horizontale** : on passe a droite
       de la colonne, dont la largeur, elle, est fixe. 10 (leur bord) + 64
       (leur bouton) + 10 de marge = 84. Les trois autres ancrages ont ete
       mesures et sont tous disputes : le bas-droite par les infusions a toutes
       les tailles, le haut-gauche par la banniere GPT-Live.

       Le relevement passe a 62 px : les infusions montent depuis le bas et
       mordaient de 12 px sous 520 px de large. Mesure libre a 700x600,
       700x750, 700x900, 500x700, 420x700 et 360x640. */
    narrowLeft:84,narrowLift:62,
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
/* Une note de la scène qui va à la ligne (S06 rework, QA B1) : la page publie sa
   hauteur (\`--sc-status-h\`, \`control_center_scene_page.js\`) et ce contrôle passe
   au-dessus d'elle, jamais plus bas que le barreau. Une ligne = 24 px : 24 + 28 = 52. */
body:has(${GEO.sceneSelector}) #${DOM.hostId}{--im-rail:max(${GEO.railOne}px,calc(var(--sc-status-h,24px) + ${GEO.railOne - 24}px))}
body:has(${GEO.badgeSelector}):has(${GEO.sceneSelector}) #${DOM.hostId}{--im-rail:max(${GEO.railTwo}px,calc(var(--sc-status-h,24px) + ${GEO.railTwo - 24}px))}
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
/* Refus ou entrée ratée (p19) : le mode est en vigueur — l'ambre reste —, mais
   rien n'écoute la salle. Un halo qui respire dirait le contraire. Le sélecteur
   ajoute l'attribut de séance à celui qui anime, donc il gagne la cascade. */
#${DOM.hostId}[${DOM.toneAttribute}=presentation][${DOM.presenceAttribute}=refused] .im-mark::after,
#${DOM.hostId}[${DOM.toneAttribute}=presentation][${DOM.presenceAttribute}=entry_failed] .im-mark::after{
  animation:none;opacity:0}
#${DOM.hostId}[${DOM.toneAttribute}=presentation][${DOM.presenceAttribute}=refused],
#${DOM.hostId}[${DOM.toneAttribute}=presentation][${DOM.presenceAttribute}=entry_failed]{--im-glow:none}
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
/* La séance PRESENTATION, telle que Voice la rapporte. Une marque **et** un
   mot : la forme distingue les états sans la couleur — disque plein qui
   respire (écoute), anneau (sourd), carré (refus, échec), anneau en tirets
   (inactive). Le code d'échec est dans \`title\`. */
#${DOM.hostId} .im-pres{display:flex;align-items:center;gap:6px;min-width:0;
  font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:${MUTED}}
#${DOM.hostId} .im-pres[hidden]{display:none}
#${DOM.hostId} .im-pres-text{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#${DOM.hostId} .im-pres-dot{flex:none;width:6px;height:6px;border-radius:50%;box-sizing:border-box;
  border:1.5px solid currentColor}
#${DOM.hostId} .im-pres[data-im-presence=listening]{color:${WARN}}
#${DOM.hostId} .im-pres[data-im-presence=listening] .im-pres-dot{background:currentColor;
  animation:imListen 2.4s ease-in-out infinite}
#${DOM.hostId} .im-pres[data-im-presence=deaf]{color:${WARN}}
#${DOM.hostId} .im-pres[data-im-presence=refused],
#${DOM.hostId} .im-pres[data-im-presence=entry_failed]{color:${DANGER}}
#${DOM.hostId} .im-pres[data-im-presence=refused] .im-pres-dot,
#${DOM.hostId} .im-pres[data-im-presence=entry_failed] .im-pres-dot{border-radius:1px;background:currentColor}
#${DOM.hostId} .im-pres[data-im-presence=inactive] .im-pres-dot{border-style:dashed}
@keyframes imListen{0%,100%{opacity:1}50%{opacity:.35}}
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
/* Aucune pastille ne se choisit (le mode suit le type du Board) : toutes portent
   \`aria-disabled\` et **pas** \`disabled\`, pour rester atteignables au clavier,
   donc capables de dire pourquoi. Un bouton que l'on ne peut pas atteindre ne
   peut rien expliquer. Le mode réservé garde en plus sa marque en tirets. */
#${DOM.hostId} .im-opt[aria-disabled=true]{cursor:default}
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
#${DOM.hostId} .im-opt[${DOM.boardAttribute}=true] .im-opt-tag{color:${WARN};
  border-color:color-mix(in srgb,${WARN} 40%,transparent)}
/* **Un ton par règle.** \`info\` (la ligne de repos) garde le gris de la base ;
   une règle assumée (\`warn\`) ne se peint pas comme une panne (\`bad\`). */
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

/* Le centre d'état (orbital-ui Slice 06, qui remplace l'indication vocale) est
   centré en bas à toutes les largeurs, de \`--shell-bottom\` (18) sur
   \`--shell-status-h\` (44), donc jusqu'à 62 px. Au-dessus de 820 px il garde la
   largeur de ce bouton de chaque côté ; en dessous il ne réserve plus que
   l'onglet Chat, et ce contrôle se hisse au-dessus de la rangée (22 + 42 = 64)
   — **avant** le resserrement de 700 px, la fenêtre 701→820 étant celle où les
   deux ne tiennent plus chacun leur moitié. */
@media(max-width:${GEO.liftBelow}px){
  #${DOM.hostId}{--im-lift:${GEO.lift}px}
}
@media(max-width:${GEO.narrowBelow}px){
  /* Le rail gauche se resserre avec le reste de la page. Le sélecteur s'ouvre
     toujours vers le haut, et sa largeur suit celle de l'écran. */
  #${DOM.hostId}{left:${GEO.narrowLeft}px;--im-lift:${GEO.narrowLift}px}
  #${DOM.hostId} .im-btn{min-width:150px;max-width:calc(100vw - ${GEO.narrowLeft + 18}px)}
  #${DOM.hostId} .im-pop{width:min(298px,calc(100vw - ${GEO.narrowLeft + 18}px));max-width:none}
}
@media(prefers-reduced-motion:reduce){
  #${DOM.hostId} .im-btn,#${DOM.hostId} .im-opt{transition:none}
  /* Le halo s'anime sous \`#hote[data-im-tone=presentation] .im-mark::after\`,
     de specificite (1,2,1). Une regle d'arret ecrite \`#hote .im-mark::after\`
     ne vaut que (1,1,1) : elle PERD, et le halo continuait de respirer sous
     \`prefers-reduced-motion\`. Le selecteur d'arret est donc le meme que celui
     qui anime. La regle etait bien presente, nommant \`.im-mark::after\` — et
     c'est pourquoi un test qui lit la feuille comme du texte passait pendant
     que la cascade faisait le contraire. */
  #${DOM.hostId}[${DOM.toneAttribute}=presentation] .im-mark::after{animation:none}
  #${DOM.hostId} .im-pop{animation:none}
  /* Même spécificité que la règle qui anime, pour la même raison que le halo. */
  #${DOM.hostId} .im-pres[data-im-presence=listening] .im-pres-dot{animation:none}
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
    const later=deps.setTimeout;
    const log=typeof deps.log==='function'?deps.log:function(){};

    /* **L'instantané, et rien d'autre.** `block` est le dernier
       `interaction_mode` reçu ; il n'est jamais écrit par un clic. */
    let block=null,report=null,view=viewOf(null,null);
    /* Heure murale (s) du dernier battement montrant un autre mode que
       PRESENTATION, confirmé par Core. Voir `freshReport`. */
    let otherModeSeenAtS=null;
    let opened=false,cursor=0,failure='';
    let spoken='';

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
    /* L'espace final sépare « Mode » du libellé dans le texte du bouton (sans lui : « ModeASSISTANT », hors du nom accessible
       pour axe, WCAG 2.5.3 ; orbital-ui Slice 09) ; en fin de bloc, il ne se voit pas. */
    eyebrow.className='im-eyebrow';eyebrow.textContent='Mode ';
    textBox.appendChild(eyebrow);
    const label=doc.createElement('span');
    label.id=DOM.labelId;label.className='im-label';
    textBox.appendChild(label);
    const sub=doc.createElement('span');
    sub.id=DOM.subId;sub.className='im-sub';
    textBox.appendChild(sub);
    /* La séance, sous le mode. **Dans** le bouton, et non à côté : c'est l'état
       de ce que le bouton commande, et un lecteur d'écran l'entend dans le nom
       du bouton (voir `labelOf`). */
    const presence=doc.createElement('span');
    presence.id=DOM.presenceId;presence.className='im-pres';presence.hidden=true;
    const presenceDot=doc.createElement('span');
    presenceDot.className='im-pres-dot';presenceDot.setAttribute('aria-hidden','true');
    presence.appendChild(presenceDot);
    const presenceText=doc.createElement('span');
    presenceText.className='im-pres-text';
    presence.appendChild(presenceText);
    textBox.appendChild(presence);
    trigger.appendChild(textBox);

    const alert=doc.createElement('span');
    alert.className='im-alert';alert.setAttribute('aria-hidden','true');
    trigger.appendChild(alert);
    host.appendChild(trigger);

    const pop=doc.createElement('div');
    pop.id=DOM.chooserId;pop.className='im-pop';
    /* `role="menu"` + `role="menuitemradio"` : les flèches déplacent le focus,
       la pastille cochée dit le mode en vigueur, et chaque entrée, inerte
       (`aria-disabled`), reste atteignable pour dire pourquoi. */
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
    /* Un menu ne contient que des entrées (axe-core, `aria-required-children` ; orbital-ui Slice 09) : le titre, la note
       et l'aide sont de simples textes dans l'arbre d'accessibilité ; le menu est nommé par `aria-label` et décrit par
       la note et l'aide, que le lecteur d'écran dit à l'ouverture. */
    for(const part of [popTitle,note,hint])part.setAttribute('role','none');
    pop.setAttribute('aria-describedby',`${DOM.noteId} ${DOM.hintId}`);
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

    function optionOf(value){
      for(const option of view.options)if(option.value===value)return option;
      return null;
    }

    /* Ce que chaque mode **fait**, sous le détail. Le texte vient du serveur
       (`summary`), pas d'une table recopiée ici : deux descriptions du même
       mode finiraient par se contredire. */
    function hintFor(value){
      const option=optionOf(value);
      if(!option)return '';
      const reserved=option.reserved
        ?' Ce mode est annoncé et réservé : il n’a pas encore de comportement.'
        :'';
      /* Le pied ne contredit pas le bandeau (p18). Le résumé du serveur dit ce
         que PRESENTATION fait **quand sa séance tourne** ; une séance sourde,
         refusée ou ratée ne le fait pas, et le pied le dit d'abord. */
      const session=view.presence;
      const current=session&&session.shown&&(session.tone==='bad'||session.tone==='warn')
        ?(PRESENCE_TEXT[session.state]||{}).now:'';
      if(value===view.mode&&current)
        return `En ce moment : ${current}. `
          +`Quand sa séance tourne : ${option.summary||option.label}${reserved}`;
      return `${option.summary||option.label}${reserved}`;
    }

    function paintHint(value){hint.textContent=hintFor(value)}

    function paintCaption(){
      label.textContent=captionOf(view);
      sub.textContent=subOf(view);
      trigger.setAttribute('aria-label',labelOf(view));
      trigger.setAttribute('title',titleOf(view));
    }

    /* La ligne de la séance. Rien ici ne vient d'un clic : elle ne change que
       lorsque le statut canonique apporte un autre relevé. */
    function paintPresence(){
      const session=view.presence;
      host.setAttribute(DOM.presenceAttribute,session?session.state:'none');
      const shown=presenceShown(view);
      presence.hidden=!shown;
      presenceText.textContent=shown?session.line:'';
      if(session)presence.setAttribute(DOM.presenceAttribute,session.state);
      else presence.removeAttribute(DOM.presenceAttribute);
      /* Le code d'échec, tel que la trace le porte. Sans code, la phrase. */
      if(shown)presence.setAttribute('title',session.code||session.said);
      else presence.removeAttribute('title');
    }

    function paintNote(){
      const said=noteOf(view,failure);
      note.hidden=!said;
      note.textContent=said?said.text:'';
      if(said)note.setAttribute('data-im-note',said.tone);
      else note.removeAttribute('data-im-note');
    }

    function paint(){
      /* **La projection est refaite ici, et nulle part ailleurs.** */
      view=viewOf(block,report);
      buildOptions();
      host.setAttribute(DOM.toneAttribute,view.tone);
      host.setAttribute('data-im-mode',view.mode);
      host.setAttribute('data-im-live',view.live?'true':'false');
      host.setAttribute('data-im-diverged',view.diverged?'true':'false');
      paintPresence();
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
      paintCaption();
      for(let i=0;i<options.length;i+=1){
        const option=options[i];
        const model=optionOf(option.value)||{};
        const on=option.value===view.selected;
        option.el.setAttribute('aria-checked',on?'true':'false');
        option.el.setAttribute(DOM.reservedAttribute,model.reserved?'true':'false');
        option.el.setAttribute(DOM.boardAttribute,model.board?'true':'false');
        /* Inerte, pour toutes : le mode suit le type du Board (Slice 01b).
           `aria-disabled` et non `disabled`, pour rester atteignable et dire pourquoi. */
        option.el.setAttribute('aria-disabled','true');
        option.name.textContent=model.label||option.value;
        option.desc.textContent=hintFor(option.value);
        option.state.textContent=model.reserved
          ?`Réservé · ${model.status||'prévu'}`
          :on?'En vigueur':'';
        option.tag.textContent=model.board&&!on?'Board':'';
        option.el.setAttribute('aria-label',
          `${model.label||option.value}${model.reserved?' — réservé, sans comportement'
            :on?' — mode en vigueur':''}${model.board&&!on?' — mode du type du Board':''}`);
        option.el.setAttribute('tabindex',i===cursor?'0':'-1');
      }
      /* Le curseur vaut le mode courant tant que personne n'a déplacé le focus. */
      if(!opened){
        const at=options.findIndex(option=>option.value===view.selected);
        cursor=at<0?0:at;
        for(let i=0;i<options.length;i+=1)
          options[i].el.setAttribute('tabindex',i===cursor?'0':'-1');
      }
      paintNote();
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
        :view.tone===TONE.UNKNOWN?'Mode d’interaction inconnu : statut illisible.'
        :!view.live?`Mode d’interaction ${view.label} — non confirmé par Core.`
        :view.diverged?`Mode d’interaction ${view.label} en vigueur, ${view.boardLabel} par le type du Board.`
        :`Mode d’interaction ${view.label}.`;
      /* La séance est dite **avec** le mode, et seulement quand elle change :
         une entrée refusée doit être entendue, pas seulement vue. */
      const session=!(failure&&failure.text)&&presenceShown(view)?` ${view.presence.said}`:'';
      const said=`${line}${session}`;
      if(said===spoken)return;
      spoken=said;announce.textContent=said;
    }

    /* --------------------------------------------------------- ouverture */

    function open(){
      if(opened)return false;
      opened=true;
      pop.hidden=false;
      trigger.setAttribute('aria-expanded','true');
      paintNote();
      if(options.length){paintHint(options[cursor].value);focusAt(cursor)}
      return true;
    }

    function close(options_){
      if(!opened)return false;
      /* L'explication a été lue, ou l'utilisateur est parti : dans les deux cas
         elle cesse d'être ce qu'il y a de plus important à dire, et un Core
         devenu injoignable ensuite ne reste pas masqué derrière elle. */
      failure='';
      opened=false;
      pop.hidden=true;
      trigger.setAttribute('aria-expanded','false');
      /* Le bandeau gardait le résumé de la dernière option survolée : rouvert,
         le détail décrivait un autre mode que celui en vigueur. */
      if(options.length)paintHint(view.selected||options[0].value);
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

    /* L'explication se voit **là où l'on vient de cliquer** : le détail se
       rouvre sur la phrase, la région vivante la dit, et la console la garde. */
    function explain(said,event,data){
      failure=Object.freeze({text:said.text,tone:said.tone||'warn'});
      log(said.level||'info',event,data);
      announce.textContent=said.text;spoken=said.text;
      open();
      paintNote();
    }

    /* Choisir **n'envoie rien** (Slice 01b) : le mode suit le type du Board
       actif. Le choix est expliqué et journalisé, le mode affiché reste celui
       que le statut confirme. Un mode inconnu du catalogue reste un défaut de
       la page, qui lève. */
    function choose(value){
      const option=optionOf(value);
      if(!option)
        throw Object.assign(new Error(`mode d’interaction inconnu : ${value}`),
          {code:'interaction_mode_hud_unknown'});
      close({focus:true});
      const reserved=option.reserved
        ?`${option.label} est réservé : il n’a pas encore de comportement. `:'';
      explain({text:`${reserved}${DERIVED}`,tone:'warn',level:'info'},
        'interaction_mode.choice_derived',
        {code:'interaction_mode_derived',mode:value,board_mode:view.board||null});
      paint();
      return null;
    }

    /* ----------------------------------------------------------- couture */

    /* La porte que `refreshStatus` appelle chaque seconde, avec le bloc
       `interaction_mode` du statut. C'est le **seul** chemin par lequel le mode
       affiché change. */
    function gate(next,nextReport){
      const before=view.mode;
      block=isObject(next)?next:null;
      /* Le relevé PRESENTATION du **même** battement. Absent, il vaut `null` :
         un relevé d'une seconde plus tôt ne survit pas à un statut qui ne le
         porte plus (Voice hors ligne). */
      if(block&&block.core_reachable===true&&text(block.mode)&&text(block.mode)!==TONE.PRESENTATION)
        otherModeSeenAtS=now()/1000;
      /* Un refus d'avant la bascule est écarté (`freshReport`). */
      report=isObject(nextReport)?freshReport(nextReport,otherModeSeenAtS):null;
      paint();
      /* Une explication cesse d'être ce qu'il faut dire dès que le mode en
         vigueur bouge : le statut montre alors autre chose. */
      if(failure&&view.mode&&view.mode!==before){failure='';paint()}
      return view;
    }

    /* Le sondage lui-même est tombé : on ne sait plus rien, et c'est ce qui
       s'affiche. Garder la dernière valeur connue serait la présenter comme
       vivante alors que plus rien ne la confirme. */
    function statusLost(){
      block=null;report=null;
      paint();
      return view;
    }

    gate(null);

    return {
      element:host,trigger,chooser:pop,
      gate,statusLost,choose,open,close,
      isOpen:()=>opened,
      /* Ce que l'écran **peint**, par opposition à ce que le serveur dit : les
         deux doivent coïncider, et c'est la seule façon de le vérifier sans
         lire des pixels. */
      presentation:()=>view,
      failure:()=>failure,
    };
  }

  /* Le nom de cet export n'est **pas** `api` : la page sert tous ses modules
     dans une seule balise `<script>`, et `api` y est déjà sa porte réseau
     (`control_center.html`). Un `const api` ici l'aurait masquée. */
  const MODE_API=Object.freeze({
    DOM,TONE,GEO,STYLE,DERIVED,NOTE_DERIVED,SUB,GLYPH,
    PRESENCE,PRESENCE_TEXT,presenceOf,freshReport,STALE_REPORT_MARGIN_S,titleOf,
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
      setTimeout:(fn,ms)=>window.setTimeout(fn,ms),
      /* Aucune porte réseau : ce contrôle n'écrit rien (Slice 01b). */
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
