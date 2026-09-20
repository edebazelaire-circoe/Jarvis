/* Bare Hands — le vocabulaire de dessin des mains schématiques.

   Décision 20 : les mains virtuelles sont du **trait schématique, presque
   robotique**, et surtout pas de l'anatomie. Moins précises qu'une photo, et
   délibérément : ce qu'un dessin de ce contrat doit faire comprendre, c'est
   *quels doigts bougent et où ils se touchent*, pas à quoi ressemble une main.

   **Ce module est la seule implantation de ce vocabulaire dans la page.** La
   Slice 01 avait tracé la première main — un châssis de paume, cinq os droits,
   des points pleins aux articulations — pour l'icône du contrôle de cycle de
   vie ; la Slice 03 a keyé les icônes d'outils dessus. Ce module la reprend
   **telle quelle** sous le nom `rest` et l'ouvre à des postures : le bouton du
   haut-gauche, la carte d'aide (Slice 04) et la calibration (Slices 05 et 06)
   dessinent désormais la même main. Deux jeux de mains auraient dérivé au
   premier ajustement, et le symptôme aurait été un utilisateur qui ne
   reconnaît pas, dans la calibration, la main qu'il a apprise dans l'aide.

   **Les postures sont des données, pas des SVG dessinés à la main.** Une
   posture est une table de doigts, chaque doigt une polyligne de deux ou trois
   points sur la grille de 24, plus un point d'articulation et, quand deux
   doigts se touchent, une marque de contact. Un seul traceur les sérialise
   toutes : ajouter une posture, c'est ajouter une ligne de table, jamais un
   second traceur.

   **Ce module ne connaît pas les gestes.** Il ne lit pas les contrats, il ne
   nomme aucun `GESTURE` et il ne dit à personne ce qu'une posture *déclenche* :
   c'est un alphabet de formes. Lier une posture à un geste lié est le travail
   de qui affiche — la carte d'aide le fait depuis `GESTURE` / `INTERACTION`,
   la calibration depuis ses étapes. Cette frontière est le point : si le
   dessin connaissait les gestes, l'aide aurait un second contrat de gestes,
   exactement ce que la Slice 04 interdit.

   Insertion : APRÈS les contrats (pure convention de rangement — il n'en lit
   rien) et **AVANT la calibration**, qui le lira à la Slice 06. Il ne dépend
   d'aucun global : un `document` lui est passé quand il faut du DOM, et
   `handMarkup` n'en demande même pas. */
(function(root){
  'use strict';

  const SVG_NS='http://www.w3.org/2000/svg';
  /* La grille, le trait et les bouts ronds de la Slice 01. Écrits ici une
     seule fois : c'est ce qui fait que deux dessins de deux Slices sont du
     même illustrateur et non de deux. */
  const VIEWBOX='0 0 24 24';
  const STROKE_WIDTH=1.5;
  const SIZE_DEFAULT=24;
  /* Rayon du point plein d'articulation, et rayon de l'anneau de contact. Le
     premier dit « ça plie ici », le second « ces deux doigts se touchent ».
     Deux formes différentes pour deux faits différents : un point plus gros
     aurait voulu dire les deux et n'aurait plus rien dit. */
  const JOINT_R=0.95;
  const CONTACT_R=1.5;
  /* Le pointillé des formes « annoncées », repris tel quel de l'icône d'outil
     absente de la palette (Slice 03) : un seul motif discontinu dans la page. */
  const DASH='2.5 2.5';

  const DIGIT=Object.freeze({THUMB:'thumb',INDEX:'index',MIDDLE:'middle',
    RING:'ring',PINKY:'pinky'});
  /* L'ordre de tracé, et il est porteur : c'est **exactement** celui que la
     Slice 01 a servi (index, majeur, annulaire, auriculaire, pouce), donc la
     posture `rest` produit le même document SVG que l'icône déjà en place. */
  const DIGIT_ORDER=Object.freeze([DIGIT.INDEX,DIGIT.MIDDLE,DIGIT.RING,
    DIGIT.PINKY,DIGIT.THUMB]);

  /* Le châssis de la paume et la ligne des jointures : communs à toutes les
     postures de V1, parce que toutes montrent la même main de face. Une
     posture peut les remplacer (un poing fermé le voudra) ; aucune ne le fait
     encore, et rien ici ne le devine. */
  const PALM='M6.5 12.6v4.2a3.8 3.8 0 0 0 3.8 3.8h3.9a3.9 3.9 0 0 0 3.9-3.9v-4.1';
  const KNUCKLES='M6.5 12.6h11.6';

  /* --------------------------------------------------------- les postures

     Chaque doigt est une polyligne : deux points pour un os droit, trois pour
     un doigt qui plie une fois. `joints` porte **un** point par doigt — au
     milieu d'un os droit, au pli d'un doigt plié — et ces valeurs sont
     explicites plutôt que calculées : sur un doigt replié, le milieu de la
     première moitié n'est pas le pli, et une règle automatique aurait posé le
     point au mauvais endroit dans exactement les postures qui comptent.

     `marks` porte ce qui n'est pas de la main : l'anneau de contact d'un
     pincement fermé, la cible d'un pincement visé. */

  /* Les trois doigts repliés dans la paume, partagés par toutes les postures
     qui ne s'en servent pas. Une seule définition : « replié » ne peut pas
     vouloir dire deux choses selon la posture. */
  const FOLD=Object.freeze({
    [DIGIT.INDEX]:Object.freeze([[9,12.4],[9.2,9.8],[10.6,11.2]]),
    [DIGIT.MIDDLE]:Object.freeze([[12,12.1],[12.2,9.6],[10.9,11.2]]),
    [DIGIT.RING]:Object.freeze([[15,12.4],[15,10.3],[13.8,11.5]]),
    [DIGIT.PINKY]:Object.freeze([[17.7,12.6],[17.5,10.8],[16.5,11.8]]),
  });
  const FOLD_JOINT=Object.freeze({
    [DIGIT.INDEX]:Object.freeze([9.2,9.8]),
    [DIGIT.MIDDLE]:Object.freeze([12.2,9.6]),
    [DIGIT.RING]:Object.freeze([15,10.3]),
    [DIGIT.PINKY]:Object.freeze([17.5,10.8]),
  });
  /* Les doigts tendus de `rest`, repris nommément par les postures où un doigt
     « ne participe pas » : tendu droit, il est visiblement hors du geste. */
  const STRAIGHT=Object.freeze({
    [DIGIT.INDEX]:Object.freeze([[9,12.4],[9,6.7]]),
    [DIGIT.MIDDLE]:Object.freeze([[12,12.1],[12,5.2]]),
    [DIGIT.RING]:Object.freeze([[15,12.4],[15,6.7]]),
    [DIGIT.PINKY]:Object.freeze([[17.7,12.6],[17.7,8.7]]),
    [DIGIT.THUMB]:Object.freeze([[7,13.5],[4.7,10.8]]),
  });
  const STRAIGHT_JOINT=Object.freeze({
    [DIGIT.INDEX]:Object.freeze([9,9.4]),
    [DIGIT.MIDDLE]:Object.freeze([12,8.5]),
    [DIGIT.RING]:Object.freeze([15,9.4]),
    [DIGIT.PINKY]:Object.freeze([17.7,10.5]),
    [DIGIT.THUMB]:Object.freeze([5.85,11.95]),
  });

  /* Le pouce levé, prêt à pincer. **Une seule forme pour les deux pincements**
     à l'ouverture : ce qui distingue le primaire du secondaire est le doigt qui
     descend, pas le pouce, et deux pouces différents auraient brouillé
     exactement la lecture que les décisions 26 à 28 demandent. */
  const THUMB_READY=Object.freeze([[7,13.5],[5.4,11],[5.9,8.2]]);
  const THUMB_READY_JOINT=Object.freeze([5.4,11]);
  /* Le pouce fermé : il vient à la rencontre du doigt, au même endroit dans
     les deux pincements. Le **point de contact** est donc commun ; c'est le
     chemin pour y arriver qui change, et c'est ce qui doit se voir. */
  const THUMB_PINCH=Object.freeze([[7,13.5],[5.6,10.9],[7.35,8.55]]);
  const THUMB_PINCH_JOINT=Object.freeze([5.6,10.9]);
  const CONTACT=Object.freeze([7.5,8.5]);

  const POSE=Object.freeze({
    REST:'rest',
    WAKE_C:'wake_c',
    PINCH_PRIMARY_OPEN:'pinch_primary_open',
    PINCH_PRIMARY_CLOSED:'pinch_primary_closed',
    PINCH_SECONDARY_OPEN:'pinch_secondary_open',
    PINCH_SECONDARY_CLOSED:'pinch_secondary_closed',
    PINCH_TARGET:'pinch_target',
  });
  const POSE_ORDER=Object.freeze([POSE.REST,POSE.WAKE_C,
    POSE.PINCH_PRIMARY_OPEN,POSE.PINCH_PRIMARY_CLOSED,
    POSE.PINCH_SECONDARY_OPEN,POSE.PINCH_SECONDARY_CLOSED,
    POSE.PINCH_TARGET]);

  /* Une marque : soit un anneau (cercle au trait), soit un trait. Les deux se
     sérialisent par les mêmes deux primitives que la main, donc une marque ne
     peut pas apporter un troisième style de trait par la bande. */
  const ring=(at,r,dashed)=>Object.freeze({shape:'ring',at:Object.freeze(at),
    r,dashed:!!dashed});

  /* La mire du pincement visé : un second anneau, **en pointillés**, autour de
     l'anneau de contact. Le trait plein dit un fait constaté (« ces deux
     doigts se touchent »), le pointillé dit une région visée — c'est déjà la
     distinction que la palette d'outils emploie pour l'icône absente, et la
     réemployer évite d'inventer un troisième langage de trait.

     Ce fut d'abord une mire à quatre branches. Elle a été retirée : la branche
     du bas arrivait sur la ligne des jointures, et deux traits qui se touchent
     sans se vouloir se lisent comme un seul dessin raté. */
  const TARGET_R=3;

  /* La table. Chaque ligne est une posture complète et se lit sans sortir
     d'ici : c'est le contrat que les Slices 05 et 06 héritent, et un test
     l'épingle pose par pose. */
  const POSES=Object.freeze({

    /* La main ouverte au repos. **Identique au trait de la Slice 01** : c'est
       l'icône déjà servie du contrôle de cycle de vie et des trois pastilles du
       sélecteur, et ce module la reprend au lieu d'en proposer une variante. */
    [POSE.REST]:Object.freeze({
      id:POSE.REST,
      label:'Main ouverte, au repos',
      summary:'Les cinq doigts tendus, paume vers l’écran. Aucun geste en cours.',
      digits:Object.freeze({
        [DIGIT.INDEX]:STRAIGHT[DIGIT.INDEX],[DIGIT.MIDDLE]:STRAIGHT[DIGIT.MIDDLE],
        [DIGIT.RING]:STRAIGHT[DIGIT.RING],[DIGIT.PINKY]:STRAIGHT[DIGIT.PINKY],
        [DIGIT.THUMB]:STRAIGHT[DIGIT.THUMB],
      }),
      joints:STRAIGHT_JOINT,
      marks:Object.freeze([]),
    }),

    /* La posture en C (décision 27) : **le pouce et l'index**, et eux seuls,
       dessinent le C. Les trois autres doigts sont repliés pour qu'aucune autre
       forme ne se dispute la lecture — un C tracé au milieu d'une main ouverte
       se lit « main ouverte ».

       Le C s'ouvre **vers la gauche**, comme la lettre, et son ouverture est
       large : 4,6 unités de grille entre les deux bouts, contre 0,25 pour un
       pincement fermé et 3,0 pour un pincement ouvert. C'est ce qui empêche de
       le lire comme un pincement, et un test épingle l'écart.

       Premier tracé : deux chaînes qui se rejoignaient presque en haut. Il se
       lisait « pince », pas « C ». L'index passe donc maintenant par-dessus en
       trois segments et le pouce ferme le bas : ce qui doit se voir est la
       **surface enfermée**, pas les deux bouts. */
    [POSE.WAKE_C]:Object.freeze({
      id:POSE.WAKE_C,
      label:'Posture en C',
      summary:'Pouce et index dessinent un C largement ouvert, les trois autres doigts repliés.',
      digits:Object.freeze({
        [DIGIT.INDEX]:Object.freeze([[9,12.4],[8.7,9],[6.6,6.6],[4,6.4]]),
        [DIGIT.MIDDLE]:FOLD[DIGIT.MIDDLE],
        [DIGIT.RING]:FOLD[DIGIT.RING],
        [DIGIT.PINKY]:FOLD[DIGIT.PINKY],
        [DIGIT.THUMB]:Object.freeze([[7,13.5],[4.9,12.4],[3.4,11]]),
      }),
      joints:Object.freeze({
        [DIGIT.INDEX]:Object.freeze([8.7,9]),
        [DIGIT.MIDDLE]:FOLD_JOINT[DIGIT.MIDDLE],
        [DIGIT.RING]:FOLD_JOINT[DIGIT.RING],
        [DIGIT.PINKY]:FOLD_JOINT[DIGIT.PINKY],
        [DIGIT.THUMB]:Object.freeze([4.9,12.4]),
      }),
      marks:Object.freeze([]),
    }),

    /* Le pincement **primaire**, pouce + index. Ouvert puis fermé : les deux
       postures ne diffèrent **que** par ces deux doigts-là, et c'est un
       invariant épinglé — sans lui, passer de l'une à l'autre ferait bouger
       toute la main et le regard perdrait ce qu'il doit suivre.

       Le majeur reste **tendu**, bien au-dessus du geste : c'est lui qui rend
       ce pincement-ci reconnaissable du secondaire d'un seul coup d'œil. */
    [POSE.PINCH_PRIMARY_OPEN]:Object.freeze({
      id:POSE.PINCH_PRIMARY_OPEN,
      label:'Pincement pouce-index, ouvert',
      summary:'Le pouce et l’index se font face, écartés : le pincement n’est pas encore pris.',
      digits:Object.freeze({
        [DIGIT.INDEX]:Object.freeze([[9,12.4],[9,9.4],[8.4,6.6]]),
        [DIGIT.MIDDLE]:STRAIGHT[DIGIT.MIDDLE],
        [DIGIT.RING]:FOLD[DIGIT.RING],
        [DIGIT.PINKY]:FOLD[DIGIT.PINKY],
        [DIGIT.THUMB]:THUMB_READY,
      }),
      joints:Object.freeze({
        [DIGIT.INDEX]:Object.freeze([9,9.4]),
        [DIGIT.MIDDLE]:STRAIGHT_JOINT[DIGIT.MIDDLE],
        [DIGIT.RING]:FOLD_JOINT[DIGIT.RING],
        [DIGIT.PINKY]:FOLD_JOINT[DIGIT.PINKY],
        [DIGIT.THUMB]:THUMB_READY_JOINT,
      }),
      marks:Object.freeze([]),
    }),
    [POSE.PINCH_PRIMARY_CLOSED]:Object.freeze({
      id:POSE.PINCH_PRIMARY_CLOSED,
      label:'Pincement pouce-index, fermé',
      summary:'Le pouce et l’index se touchent : le pincement est pris.',
      digits:Object.freeze({
        [DIGIT.INDEX]:Object.freeze([[9,12.4],[9.1,9.9],[7.65,8.45]]),
        [DIGIT.MIDDLE]:STRAIGHT[DIGIT.MIDDLE],
        [DIGIT.RING]:FOLD[DIGIT.RING],
        [DIGIT.PINKY]:FOLD[DIGIT.PINKY],
        [DIGIT.THUMB]:THUMB_PINCH,
      }),
      joints:Object.freeze({
        [DIGIT.INDEX]:Object.freeze([9.1,9.9]),
        [DIGIT.MIDDLE]:STRAIGHT_JOINT[DIGIT.MIDDLE],
        [DIGIT.RING]:FOLD_JOINT[DIGIT.RING],
        [DIGIT.PINKY]:FOLD_JOINT[DIGIT.PINKY],
        [DIGIT.THUMB]:THUMB_PINCH_JOINT,
      }),
      marks:Object.freeze([ring(CONTACT,CONTACT_R)]),
    }),

    /* Le pincement **secondaire**, pouce + majeur — même grammaire, silhouette
       franchement différente. Ici l'index est **replié** et c'est le majeur qui
       descend : la main n'a plus de doigt dressé, et le long trait qui balaie
       depuis la droite est la signature de ce pincement-ci. Le point de contact
       est le même que pour le primaire ; ce qui change est le chemin, donc le
       doigt, donc le sens. */
    [POSE.PINCH_SECONDARY_OPEN]:Object.freeze({
      id:POSE.PINCH_SECONDARY_OPEN,
      label:'Pincement pouce-majeur, ouvert',
      summary:'Le pouce et le majeur se font face, écartés, l’index replié.',
      digits:Object.freeze({
        [DIGIT.INDEX]:FOLD[DIGIT.INDEX],
        [DIGIT.MIDDLE]:Object.freeze([[12,12.1],[11.4,8.6],[9.2,7.2]]),
        [DIGIT.RING]:FOLD[DIGIT.RING],
        [DIGIT.PINKY]:FOLD[DIGIT.PINKY],
        [DIGIT.THUMB]:THUMB_READY,
      }),
      joints:Object.freeze({
        [DIGIT.INDEX]:FOLD_JOINT[DIGIT.INDEX],
        [DIGIT.MIDDLE]:Object.freeze([11.4,8.6]),
        [DIGIT.RING]:FOLD_JOINT[DIGIT.RING],
        [DIGIT.PINKY]:FOLD_JOINT[DIGIT.PINKY],
        [DIGIT.THUMB]:THUMB_READY_JOINT,
      }),
      marks:Object.freeze([]),
    }),
    [POSE.PINCH_SECONDARY_CLOSED]:Object.freeze({
      id:POSE.PINCH_SECONDARY_CLOSED,
      label:'Pincement pouce-majeur, fermé',
      summary:'Le pouce et le majeur se touchent : le pincement secondaire est pris.',
      digits:Object.freeze({
        [DIGIT.INDEX]:FOLD[DIGIT.INDEX],
        [DIGIT.MIDDLE]:Object.freeze([[12,12.1],[11.2,9.2],[7.65,8.55]]),
        [DIGIT.RING]:FOLD[DIGIT.RING],
        [DIGIT.PINKY]:FOLD[DIGIT.PINKY],
        [DIGIT.THUMB]:THUMB_PINCH,
      }),
      joints:Object.freeze({
        [DIGIT.INDEX]:FOLD_JOINT[DIGIT.INDEX],
        [DIGIT.MIDDLE]:Object.freeze([11.2,9.2]),
        [DIGIT.RING]:FOLD_JOINT[DIGIT.RING],
        [DIGIT.PINKY]:FOLD_JOINT[DIGIT.PINKY],
        [DIGIT.THUMB]:THUMB_PINCH_JOINT,
      }),
      marks:Object.freeze([ring(CONTACT,CONTACT_R)]),
    }),

    /* Le pincement **visé** (décision 28) : la main qui pince quelque chose, et
       ce quelque chose est une mire, pas un doigt tendu. Les doigts sont
       exactement ceux du primaire fermé — pincer une cible est pincer, la cible
       ne change pas la main — et la mire **s'ajoute** à l'anneau de contact au
       lieu de le remplacer : le contact reste un fait, la mire dit en plus où
       il atterrit. La composition est littérale, et un test l'épingle : cette
       posture est le primaire fermé, plus un anneau. */
    [POSE.PINCH_TARGET]:Object.freeze({
      id:POSE.PINCH_TARGET,
      label:'Pincement sur une cible',
      summary:'Le pincement pouce-index se ferme sur une cible désignée.',
      digits:Object.freeze({
        [DIGIT.INDEX]:Object.freeze([[9,12.4],[9.1,9.9],[7.65,8.45]]),
        [DIGIT.MIDDLE]:STRAIGHT[DIGIT.MIDDLE],
        [DIGIT.RING]:FOLD[DIGIT.RING],
        [DIGIT.PINKY]:FOLD[DIGIT.PINKY],
        [DIGIT.THUMB]:THUMB_PINCH,
      }),
      joints:Object.freeze({
        [DIGIT.INDEX]:Object.freeze([9.1,9.9]),
        [DIGIT.MIDDLE]:STRAIGHT_JOINT[DIGIT.MIDDLE],
        [DIGIT.RING]:FOLD_JOINT[DIGIT.RING],
        [DIGIT.PINKY]:FOLD_JOINT[DIGIT.PINKY],
        [DIGIT.THUMB]:THUMB_PINCH_JOINT,
      }),
      marks:Object.freeze([ring(CONTACT,CONTACT_R),ring(CONTACT,TARGET_R,true)]),
    }),
  });

  /* ---------------------------------------------------------- le traceur */

  /* **Un refus codé plutôt qu'un défaut plausible.** Une posture inconnue ne
     retombe pas sur `rest` : un écran qui montre une main ouverte là où on
     attendait un pincement enseigne le mauvais geste, et rien ne le signale. */
  function reject(code,message){
    throw Object.assign(new Error(message),{code});
  }

  function pose(id){
    const found=POSES[String(id)];
    if(!found)reject('barehands_hand_pose_unknown',
      `Posture de main inconnue : ${String(id)}. Connues : ${POSE_ORDER.join(', ')}.`);
    return found;
  }
  const poses=()=>POSE_ORDER.map(pose);

  /* Nombres courts : `12` et non `12.0`, `8.55` et non `8.550000000000001`.
     Un `d` qui traîne seize décimales est illisible en revue et grossit la page
     servie pour rien. */
  const num=value=>{
    const rounded=Math.round(Number(value)*1000)/1000;
    return String(rounded);
  };
  const escapeText=value=>String(value)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
  const polyline=points=>points.map((point,index)=>
    `${index?'L':'M'}${num(point[0])} ${num(point[1])}`).join('');

  /* Ce qu'il y a à dessiner, **sans DOM ni chaîne** : c'est la seule source des
     deux sérialiseurs ci-dessous, donc `handSvg` et `handMarkup` ne peuvent
     pas diverger. Un test le vérifie en les comparant l'un à l'autre. */
  function handShapes(spec){
    const options=spec&&typeof spec==='object'?spec:{};
    const record=pose(options.pose===undefined?POSE.REST:options.pose);
    const paths=[PALM,KNUCKLES];
    const dots=[];
    const rings=[];
    for(const digit of DIGIT_ORDER){
      const points=record.digits[digit];
      if(!points)reject('barehands_hand_digit_missing',
        `La posture ${record.id} ne déclare pas le doigt ${digit}.`);
      paths.push(polyline(points));
    }
    for(const digit of DIGIT_ORDER){
      const at=record.joints[digit];
      if(!at)reject('barehands_hand_joint_missing',
        `La posture ${record.id} ne déclare pas l’articulation du doigt ${digit}.`);
      dots.push(Object.freeze({cx:at[0],cy:at[1],r:JOINT_R}));
    }
    for(const mark of record.marks){
      if(mark.shape==='ring')
        rings.push(Object.freeze({cx:mark.at[0],cy:mark.at[1],r:mark.r,dashed:!!mark.dashed}));
      else reject('barehands_hand_mark_unknown',
        `Marque inconnue dans la posture ${record.id} : ${String(mark.shape)}.`);
    }
    return Object.freeze({
      id:record.id,label:record.label,summary:record.summary,
      viewBox:VIEWBOX,strokeWidth:STROKE_WIDTH,
      size:Number(options.size)>0?Number(options.size):SIZE_DEFAULT,
      /* La main gauche est la même main retournée, et le retournement vit dans
         un `<g>` interne : posé sur la racine, il déplacerait aussi le
         `<title>` des lecteurs d'écran, qui n'a pas de géométrie. */
      mirror:!!options.mirror,
      className:options.className===undefined?'bh-hand':String(options.className),
      /* Décoratif par défaut — c'est ce qu'est une icône à côté de son
         libellé. Un `title` fourni la rend au contraire annoncée, et alors
         elle cesse d'être `aria-hidden` : les deux ne peuvent pas être vrais. */
      title:options.title===undefined||options.title===null?null:String(options.title),
      paths:Object.freeze(paths),dots:Object.freeze(dots),rings:Object.freeze(rings),
    });
  }

  const MIRROR_TRANSFORM='translate(24,0) scale(-1,1)';

  function handSvg(doc,spec){
    if(!doc||typeof doc.createElementNS!=='function')
      reject('barehands_hand_document_missing',
        'handSvg() attend un document capable de créer des éléments SVG.');
    const shapes=handShapes(spec);
    const svg=doc.createElementNS(SVG_NS,'svg');
    svg.setAttribute('viewBox',shapes.viewBox);
    svg.setAttribute('class',shapes.className);
    svg.setAttribute('width',String(shapes.size));
    svg.setAttribute('height',String(shapes.size));
    svg.setAttribute('fill','none');
    svg.setAttribute('stroke','currentColor');
    svg.setAttribute('stroke-width',String(shapes.strokeWidth));
    svg.setAttribute('stroke-linecap','round');
    svg.setAttribute('stroke-linejoin','round');
    svg.setAttribute('data-bh-pose',shapes.id);
    if(shapes.title){
      svg.setAttribute('role','img');
      const label=doc.createElementNS(SVG_NS,'title');
      label.textContent=shapes.title;
      svg.appendChild(label);
    }else{
      svg.setAttribute('aria-hidden','true');
      svg.setAttribute('focusable','false');
    }
    let into=svg;
    if(shapes.mirror){
      into=doc.createElementNS(SVG_NS,'g');
      into.setAttribute('transform',MIRROR_TRANSFORM);
      svg.appendChild(into);
    }
    for(const d of shapes.paths){
      const path=doc.createElementNS(SVG_NS,'path');
      path.setAttribute('d',d);
      into.appendChild(path);
    }
    for(const dot of shapes.dots){
      const mark=doc.createElementNS(SVG_NS,'circle');
      mark.setAttribute('cx',num(dot.cx));mark.setAttribute('cy',num(dot.cy));
      mark.setAttribute('r',num(dot.r));
      mark.setAttribute('fill','currentColor');mark.setAttribute('stroke','none');
      into.appendChild(mark);
    }
    for(const circle of shapes.rings){
      const mark=doc.createElementNS(SVG_NS,'circle');
      mark.setAttribute('cx',num(circle.cx));mark.setAttribute('cy',num(circle.cy));
      mark.setAttribute('r',num(circle.r));
      /* Le pointillé de la mire, écrit dans le même vocabulaire que l'icône
         d'outil absente de la palette : une forme au trait discontinu est une
         région annoncée, jamais un fait constaté. */
      if(circle.dashed)mark.setAttribute('stroke-dasharray',DASH);
      into.appendChild(mark);
    }
    return svg;
  }

  /* La même chose en chaîne, pour qui construit son écran en `innerHTML`
     plutôt qu'en nœuds. **Pas un second dessin** : les deux lisent
     `handShapes`, et un test compare leur contenu élément par élément. */
  function handMarkup(spec){
    const shapes=handShapes(spec);
    const body=shapes.paths.map(d=>`<path d="${d}"/>`)
      .concat(shapes.dots.map(dot=>
        `<circle cx="${num(dot.cx)}" cy="${num(dot.cy)}" r="${num(dot.r)}" fill="currentColor" stroke="none"/>`))
      .concat(shapes.rings.map(circle=>
        `<circle cx="${num(circle.cx)}" cy="${num(circle.cy)}" r="${num(circle.r)}"`
        +`${circle.dashed?` stroke-dasharray="${DASH}"`:''}/>`))
      .join('');
    const inner=shapes.mirror?`<g transform="${MIRROR_TRANSFORM}">${body}</g>`:body;
    const head=shapes.title
      ?` role="img"><title>${escapeText(shapes.title)}</title>`
      :' aria-hidden="true" focusable="false">';
    return `<svg viewBox="${shapes.viewBox}" class="${escapeText(shapes.className)}"`
      +` width="${shapes.size}" height="${shapes.size}" fill="none" stroke="currentColor"`
      +` stroke-width="${shapes.strokeWidth}" stroke-linecap="round" stroke-linejoin="round"`
      +` data-bh-pose="${shapes.id}"${head}${inner}</svg>`;
  }

  const api=Object.freeze({
    VERSION:1,VIEWBOX,STROKE_WIDTH,SIZE_DEFAULT,JOINT_R,CONTACT_R,
    PALM,KNUCKLES,
    DIGIT,DIGIT_ORDER,POSE,POSE_ORDER,POSES,
    pose,poses,handShapes,handSvg,handMarkup,
  });
  root.JarvisBarehandsHandArt=api;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
