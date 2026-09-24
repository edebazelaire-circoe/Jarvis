/* Avertissement de vérification — la carte discrète, et l'arbitrage du son.

   Slice 09 de `jarvis-presentation-interaction-mode`. Contrat :
   `docs/presentation-attention.md`. D11 est verrouillée : une contradiction
   vérifiée vaut **un petit signal sonore et un avertissement flottant**, et
   Jarvis n'explique rien à voix haute. Ce module tient la moitié visible.

   Il fait trois choses, et rien d'autre :

   1. il dessine une carte discrète par point d'attention non vu ;
   2. il la laisse s'ouvrir sur ses preuves — des sources, avec leur titre et
      leur lien — et s'écarter d'un clic ;
   3. il arbitre le signal sonore entre onglets, pour que `bgCue` ne sonne
      qu'une fois par événement.

   ## Ce qu'il ne refait pas

   **Le son existe déjà.** `bgCue()` vit dans `control_center.html` depuis le
   registre d'arrière-plan : deux notes sinusoïdales en WebAudio, aucun fichier,
   et il ne sonne que sur une **hausse** du numéro de séquence, jamais au
   premier sondage. En ajouter un second aurait fait deux sons pour un
   événement, ce que D11 interdit en toutes lettres. Ce module ne fabrique donc
   aucun son : il fournit la seule chose qui manquait, `claimCue`, une porte
   que `renderBackgroundPills` consulte avant de sonner.

   **Les pastilles existent déjà.** Un point d'attention est classé `attention`
   par `background_events.py` et compté dans la pastille « points à vérifier ».
   La carte ne remplace pas la pastille : elle montre *ce que* la pastille
   compte, pour le seul cas où D11 demande de le montrer.

   ## Les trois déduplications, et laquelle tient quoi

   Elles sont à trois étages différents et il faut savoir lequel tient quoi,
   sinon on en ajoute un quatrième par précaution :

   - **sondage** (le même onglet relit le statut chaque seconde) — tenu par la
     règle existante de `renderBackgroundPills` : `seq > BG.seq`. Rien ici ;
   - **rechargement** (F5, ou un onglet rouvert) — tenu par `BG.armed`, qui
     refuse le premier sondage où tout est neuf par construction. Ce module
     ajoute une seconde ceinture, `mark`, qui survit au rechargement ;
   - **plusieurs onglets ou fenêtres** — c'est le trou, et c'est ce que ce
     module bouche : un bail de meneur plus une borne haute partagée, tous deux
     dans `localStorage`, donc partagés par origine.

   Et une quatrième, sémantique, qui n'est pas ici du tout : deux fois la même
   contradiction sur la même affirmation sont **coalescées par le magasin** de
   la Slice 04 sur `(catégorie, affirmation, sujet)`, donc la seconde ne pose
   aucune ligne de trace, donc la séquence ne monte pas, donc rien ne sonne.

   ## Ce que l'arbitrage garantit, et ce qu'il ne garantit pas

   `localStorage` n'offre pas de comparaison-et-échange atomique. Le bail rend
   la fenêtre de course minuscule — un onglet qui n'est pas meneur renonce sans
   rien écrire — et la borne haute rattrape le cas ordinaire où deux onglets
   remarquent la hausse à quelques centaines de millisecondes d'écart. Deux
   onglets qui liraient la borne dans le **même** tour de boucle avant que l'un
   n'écrive pourraient sonner tous les deux. C'est une réduction très forte, et
   ce n'est pas une preuve : le dire vaut mieux que de le laisser croire.

   En l'absence de `localStorage` — navigation privée, stockage bloqué — la
   porte s'ouvre. Un son de trop est un défaut mineur ; un silence là où D11
   demande un signal est le défaut que ce module existe pour éviter.

   ## Pourquoi la carte vit dans la pile d'infusions

   Le coin bas-gauche est disputé (`.jh-badge`, `.jh-note`, `.sc-status`, le
   contrôle de mode), et il a déjà deux barreaux : en poser un troisième, la
   Slice 03 l'a écrit, n'appartient à aucun occupant pris isolément. Les quatre
   ancrages ont donc été mesurés dans un vrai navigateur à sept tailles, et
   aucun coin n'est libre à toutes.

   La conclusion n'est pas d'inventer un ancrage de plus, mais de **rejoindre
   la seule surface flottante que cette page possède déjà** : `#toasts`. La
   carte y entre comme un enfant ordinaire, avec `order:1` pour rester la plus
   basse quelle que soit l'infusion qui arrive ensuite. Elle hérite ainsi, sans
   qu'une seule règle partagée soit touchée, de la largeur de la pile, de son
   évitement du panneau ouvert (`#app:has(.panel.open)~.toasts`) et de sa règle
   de mouvement réduit.

   La seule géométrie propre à ce module est une marge basse sous 760 px, qui
   relève toute la pile au-dessus de l'indication vocale centrée — laquelle,
   mesurée, chevauche déjà les infusions à cette largeur.

   ## Insertion

   `control_center.py` / `control_center.html`. Ce module ne dépend d'aucun
   autre module de page : sa seule source est le bloc `background` de
   `GET /api/status`, que `refreshStatus` lui remet une fois par seconde, par
   le motif `gate(bloc)` / `statusLost()` que quatre modules utilisent déjà. Il
   refuse de s'installer sous un nom cherchable si la pile d'infusions manque,
   et **rattrape ce refus** : la page concatène tous ses modules dans un seul
   `<script>`, et une levée qui remonterait emporterait la scène, la
   chronologie et le Test Lab avec elle. */
(function(root){
  'use strict';

  /* Les identifiants que la page, les tests et les Slices suivantes cherchent. */
  const DOM=Object.freeze({
    hostId:'toasts',
    styleId:'presentationAttentionStyle',
    cardClass:'pa-card',
    idAttribute:'data-pa-id',
    toneAttribute:'data-pa-tone',
    openAttribute:'data-pa-open',
    bodyPrefix:'presentationAttentionBody-',
  });

  /* Les clés de `localStorage`. Préfixées `jarvis.` comme tout ce que cette
     page y range, et nommées d'après ce qu'elles tiennent et non d'après le
     module, parce que le bail arbitre `bgCue` qui appartient à la page. */
  const CUE=Object.freeze({
    leaderKey:'jarvis.bg.cue.leader',
    markKey:'jarvis.bg.cue.mark',
    dismissKey:'jarvis.pa.dismissed',
    /* Durée du bail. Trois fois le battement : un onglet meneur qui s'endort
       ou se ferme laisse la main au tour suivant, et un onglet vivant ne perd
       jamais la sienne entre deux sondages. */
    leaseMs:3000,
    /* Écartés gardés. Assez pour une séance, trop peu pour devenir une
       mémoire : le registre ne garde lui-même que soixante entrées. */
    maxDismissed:32,
  });

  /* La présentation d'une catégorie. Table close, lue et jamais devinée : une
     catégorie qu'un serveur plus récent enverrait tombe sur `unknown`, qui est
     neutre — peindre en rouge une chose dont cette page ignore la nature
     serait une affirmation que personne ne peut soutenir. */
  const CATEGORY=Object.freeze({
    contradiction:{label:'Contradiction',tone:'warn',glyph:'⚠'},
    mismatch:{label:'Écart',tone:'warn',glyph:'≠'},
    missing_source:{label:'Sans source',tone:'info',glyph:'?'},
    stale_resource:{label:'Ressource périmée',tone:'info',glyph:'⌛'},
    unknown:{label:'À vérifier',tone:'info',glyph:'•'},
  });

  /* Les bandes de confiance, en mots. **Jamais un nombre** : les confiances de
     la voie ambiante sont codées en dur et non étalonnées
     (`docs/presentation-ambient-lane.md` §11), et afficher « 0,72 » donnerait
     à un chiffre arbitraire l'autorité d'une mesure. */
  const BAND=Object.freeze({high:'confiance élevée',moderate:'confiance moyenne'});

  /* Schémas qu'un navigateur sait ouvrir. Les autres — `doc:`, `chart:`,
     `scene:`, `dataset:`, `note:` — sont des références internes : on les
     montre en clair plutôt que d'offrir un lien mort. */
  const OPENABLE=Object.freeze(['http:','https:','file:']);

  function categoryOf(name){
    return Object.prototype.hasOwnProperty.call(CATEGORY,String(name||''))
      ?CATEGORY[String(name)]:CATEGORY.unknown;
  }

  function bandWord(band){
    return Object.prototype.hasOwnProperty.call(BAND,String(band||''))
      ?BAND[String(band)]:BAND.moderate;
  }

  function openable(locator){
    const text=String(locator||'');
    for(let i=0;i<OPENABLE.length;i+=1)if(text.lastIndexOf(OPENABLE[i],0)===0)return true;
    return false;
  }

  /* -------------------------------------------------------------------
     Le modèle de vue. Pur : ni DOM, ni horloge, ni réseau.
     ------------------------------------------------------------------- */

  /* Ce que la page doit dessiner, à partir du bloc `background` du statut.

     Tolérant à tout : ce bloc traverse le réseau et peut venir d'un serveur
     plus ancien qui ne connaît pas `attention`. Un bloc absent, une liste
     absente, une entrée malformée rendent une liste vide — jamais une levée,
     puisque `refreshStatus` est la seule boucle de cette page. */
  function viewOf(background,dismissed){
    const block=background&&typeof background==='object'?background:null;
    const raw=block&&Array.isArray(block.attention)?block.attention:[];
    const skip=Array.isArray(dismissed)?dismissed:[];
    const seen=[],out=[];
    for(let i=0;i<raw.length;i+=1){
      const entry=raw[i];
      if(!entry||typeof entry!=='object')continue;
      const item=entry.attention&&typeof entry.attention==='object'?entry.attention:null;
      if(!item)continue;
      const id=String(item.attention_id||'');
      /* Deux fois le même point d'attention est un seul avertissement — et un
         seul son. Le magasin coalesce déjà côté Core ; ceci est la ceinture
         qui tient si jamais deux lignes portaient la même identité. */
      if(!id||seen.indexOf(id)>=0||skip.indexOf(id)>=0)continue;
      seen.push(id);
      const cat=categoryOf(item.category);
      out.push({
        seq:Number(entry.seq)||0,
        id:id,
        category:String(item.category||''),
        title:cat.label,
        tone:cat.tone,
        glyph:cat.glyph,
        /* La phrase fixe écrite par le domaine. Aucune parole de la salle n'y
           entre : le Core ne la fait pas descendre dans la trace. */
        headline:String(entry.label||''),
        detail:String(entry.detail||''),
        band:String(item.band||''),
        bandWord:bandWord(item.band),
        claimId:String(item.claim_id||''),
        topicId:String(item.topic_id||''),
        sources:sourcesOf(item.evidence),
        ts:String(entry.ts||''),
      });
    }
    return out;
  }

  function sourcesOf(evidence){
    const raw=Array.isArray(evidence)?evidence:[],out=[];
    for(let i=0;i<raw.length;i+=1){
      const piece=raw[i];
      if(!piece||typeof piece!=='object')continue;
      const locator=String(piece.locator||'');
      if(!locator)continue;
      out.push({
        sourceId:String(piece.source_id||''),
        locator:locator,
        title:String(piece.title||'')||locator,
        resourceId:String(piece.resource_id||''),
        openable:openable(locator),
      });
    }
    return out;
  }

  /* -------------------------------------------------------------------
     L'arbitrage du son. Pur aussi : le stockage et l'horloge sont injectés.
     ------------------------------------------------------------------- */

  function readJson(storage,key){
    try{
      const raw=storage.getItem(key);
      return raw?JSON.parse(raw):null;
    }catch(error){return null}
  }

  function writeJson(storage,key,value){
    try{storage.setItem(key,JSON.stringify(value));return true}
    catch(error){return false}
  }

  /* Cet onglet a-t-il le droit de sonner pour ce numéro de séquence ?

     `true` ouvre la porte **et consomme** le numéro : appeler deux fois pour le
     même `seq` rend `false` la seconde fois. C'est voulu — la fonction est la
     porte, pas une question.

     Sans stockage, on sonne : voir l'en-tête du module. */
  function claimCue(seq,options){
    const opts=options||{};
    const storage=opts.storage;
    const wanted=Number(seq)||0;
    if(!storage||wanted<=0)return true;
    const now=Number(opts.now)||0;
    const tabId=String(opts.tabId||'');
    const leader=readJson(storage,CUE.leaderKey);
    const held=leader&&typeof leader==='object'&&typeof leader.at==='number'
      &&(now-leader.at)<CUE.leaseMs;
    if(held&&String(leader.id)!==tabId)return false;
    if(!writeJson(storage,CUE.leaderKey,{id:tabId,at:now}))return true;
    const mark=Number(readJson(storage,CUE.markKey))||0;
    /* La borne haute partagée : elle tient le second onglet **et** le
       rechargement, puisqu'elle survit à la page. */
    if(wanted<=mark)return false;
    writeJson(storage,CUE.markKey,wanted);
    return true;
  }

  function dismissedFrom(storage){
    const raw=storage?readJson(storage,CUE.dismissKey):null;
    if(!Array.isArray(raw))return [];
    const out=[];
    for(let i=0;i<raw.length&&out.length<CUE.maxDismissed;i+=1){
      const id=String(raw[i]||'');
      if(id&&out.indexOf(id)<0)out.push(id);
    }
    return out;
  }

  function rememberDismissed(storage,ids){
    if(!storage)return;
    writeJson(storage,CUE.dismissKey,ids.slice(-CUE.maxDismissed));
  }

  /* -------------------------------------------------------------------
     La feuille de style
     ------------------------------------------------------------------- */

  const WARN='var(--warn,#ffcc66)';
  const ACCENT='var(--accent,#6ee7ff)';
  const MUTED='var(--muted,#7fa3b5)';

  const STYLE=`
/* La carte est un enfant ordinaire de la pile d'infusions : elle hérite de sa
   largeur, de son rang (70), de son évitement du panneau ouvert et de sa règle
   de mouvement réduit. \`order:1\` la garde la plus basse — donc la plus proche
   du coin, donc toujours visible — quelle que soit l'infusion qui arrive
   ensuite, puisque \`toast()\` fait un \`appendChild\`. */
.${DOM.cardClass}{order:1;pointer-events:auto;position:relative;
  display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;align-items:start;
  padding:9px 8px 9px 11px;
  background:rgba(6,13,19,.97);border:1px solid var(--line,#183343);
  border-left:2px solid ${ACCENT};border-radius:8px;
  box-shadow:0 14px 40px rgba(0,0,0,.55);
  font:12px/1.35 ui-monospace,SFMono-Regular,Consolas,monospace;
  color:var(--text,#d8edf7);
  animation:paIn .2s ease-out}
.${DOM.cardClass}[${DOM.toneAttribute}=warn]{border-left-color:${WARN}}
@keyframes paIn{from{opacity:0;transform:translateY(8px)}}
/* Même discipline que les infusions : sous mouvement réduit, rien n'entre en
   glissant. La règle vise la carte elle-même, pas un pseudo-élément — la
   Slice 03 a perdu trois défauts dans cette cascade-là. */
@media(prefers-reduced-motion:reduce){.${DOM.cardClass}{animation:none}
  .${DOM.cardClass} .pa-head,.${DOM.cardClass} .pa-chev{transition:none}}
/* Sous 760 px l'indication vocale est centrée en bas à 22 px et chevauche déjà
   la pile d'infusions — mesuré. Une marge sous la carte la plus basse relève
   toute la pile, sans toucher une seule règle partagée. */
@media(max-width:760px){.${DOM.cardClass}{margin-bottom:44px}}
/* Sous 700 px le contrôle de mode quitte le rail gauche et vient se poser à
   \`left:84px\`, où il occupe la bande 84→144 au-dessus du bas — exactement la
   bande que la carte relevée occupe. Mesuré : recouvrement de 119×31 à
   500×700, et la carte étant au rang 70 contre 32, c'est le bouton de mode qui
   devenait incliquable. La Slice 03 a été reprise pour ce défaut-là, dans
   l'autre sens ; le reproduire ici aurait été impardonnable.

   La sortie est horizontale, comme la sienne : la carte se rétrécit et
   s'aligne à droite, de sorte que son bord gauche passe à droite de cette
   colonne. Le plancher de 156 px garde un titre lisible ; en dessous de ~420 px
   de large le bas de cette page est de toute façon disputé bien avant cette
   Slice — les infusions y recouvrent déjà l'indication vocale, les pastilles et
   la barre d'outils. */
@media(max-width:700px){.${DOM.cardClass}{justify-self:end;
  width:max(156px,calc(100vw - 348px))}}
.${DOM.cardClass} .pa-head{grid-column:1;display:grid;
  grid-template-columns:auto minmax(0,1fr) auto;gap:8px;align-items:center;
  width:100%;margin:0;padding:0;border:0;background:none;color:inherit;
  font:inherit;text-align:left;cursor:pointer;transition:color .15s}
.${DOM.cardClass} .pa-head:hover{color:${ACCENT}}
.${DOM.cardClass} .pa-glyph{font-size:13px;line-height:1;color:${WARN}}
.${DOM.cardClass}[${DOM.toneAttribute}=info] .pa-glyph{color:${ACCENT}}
.${DOM.cardClass} .pa-txt{min-width:0}
.${DOM.cardClass} .pa-title{display:block;font-size:12px;letter-spacing:.1em;
  text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.${DOM.cardClass} .pa-sub{display:block;font-size:11px;color:${MUTED};margin-top:2px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.${DOM.cardClass} .pa-chev{font-size:10px;color:${MUTED};transition:transform .15s}
.${DOM.cardClass}[${DOM.openAttribute}=true] .pa-chev{transform:rotate(180deg)}
.${DOM.cardClass} .pa-close{grid-column:2;grid-row:1;background:none;border:0;
  color:${MUTED};font-size:15px;line-height:1;cursor:pointer;padding:0 2px}
.${DOM.cardClass} .pa-close:hover{color:var(--text,#d8edf7)}
.${DOM.cardClass} .pa-body{grid-column:1/-1;margin-top:8px;padding-top:8px;
  border-top:1px solid var(--line,#183343);display:grid;gap:7px}
.${DOM.cardClass} .pa-headline{margin:0;font-size:11.5px;line-height:1.4;
  color:var(--text,#d8edf7)}
.${DOM.cardClass} .pa-sources{margin:0;padding:0;list-style:none;display:grid;gap:5px}
.${DOM.cardClass} .pa-src{display:block;font-size:11px;min-width:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.${DOM.cardClass} a.pa-src{color:${ACCENT};text-decoration:none;border-bottom:1px dotted currentColor}
.${DOM.cardClass} a.pa-src:hover{color:var(--text,#d8edf7)}
.${DOM.cardClass} span.pa-src{color:${MUTED}}
.${DOM.cardClass} .pa-note{margin:0;font-size:10.5px;line-height:1.4;color:${MUTED}}
.${DOM.cardClass} :focus-visible{outline:1px solid ${ACCENT};outline-offset:2px}`;

  function installStyle(doc){
    if(!doc||typeof doc.getElementById!=='function')return null;
    const existing=doc.getElementById(DOM.styleId);
    if(existing)return existing;
    const style=doc.createElement('style');
    style.id=DOM.styleId;
    style.textContent=STYLE;
    (doc.head||doc.documentElement).appendChild(style);
    return style;
  }

  /* -------------------------------------------------------------------
     Le contrôle
     ------------------------------------------------------------------- */

  /* `deps` : `{document, host, storage, now, tabId, log}`. Tout est injecté —
     c'est ce qui rend ce contrôle exécutable sous node sans navigateur, et
     c'est le motif du contrôle de mode de la Slice 03. */
  function createAttentionWarning(deps){
    const doc=deps.document;
    const host=deps.host;
    const storage=deps.storage||null;
    const now=typeof deps.now==='function'?deps.now:function(){return 0};
    const tabId=String(deps.tabId||'tab');
    const log=typeof deps.log==='function'?deps.log:function(){};
    const cards=Object.create(null);
    let dismissed=dismissedFrom(storage);
    let armed=false;
    let signature='';

    installStyle(doc);

    /* Le bloc `background` du statut, une fois par seconde. Ne lève jamais :
       la seule boucle de cette page ne doit pas pouvoir tomber sur un
       avertissement. */
    function gate(background){
      let items;
      try{items=viewOf(background,dismissed)}
      catch(error){log('presentation_attention.view_failed',error);return}
      const next=items.map(function(item){return item.id}).join('|');
      if(next!==signature){
        signature=next;
        try{render(items)}
        catch(error){log('presentation_attention.render_failed',error)}
      }
      armed=true;
    }

    /* Le sondage est tombé : on ne sait plus rien. Les cartes restent — elles
       décrivent un fait déjà constaté, pas un état vivant — mais plus rien n'y
       est ajouté. La distinction est celle du contrôle de mode : un état que
       l'on subit ne s'affiche pas comme une vérité. */
    function statusLost(){
      armed=false;
    }

    function render(items){
      const wanted=Object.create(null);
      for(let i=0;i<items.length;i+=1){
        const item=items[i];
        wanted[item.id]=true;
        if(!cards[item.id])cards[item.id]=build(item);
        else update(cards[item.id],item);
      }
      for(const id in cards){
        if(wanted[id])continue;
        const card=cards[id];
        if(card.element&&card.element.parentNode)card.element.parentNode.removeChild(card.element);
        delete cards[id];
      }
    }

    function build(item){
      const element=doc.createElement('div');
      element.className=DOM.cardClass;
      element.setAttribute(DOM.idAttribute,item.id);
      element.setAttribute(DOM.toneAttribute,item.tone);
      element.setAttribute(DOM.openAttribute,'false');
      /* `polite` et jamais `assertive` : l'équivalent lu du signal discret ne
         doit pas plus couper la parole que le signal lui-même. */
      element.setAttribute('role','status');
      element.setAttribute('aria-live','polite');

      const head=doc.createElement('button');
      head.type='button';
      head.className='pa-head';
      const bodyId=DOM.bodyPrefix+item.id;
      head.setAttribute('aria-expanded','false');
      head.setAttribute('aria-controls',bodyId);

      const glyph=doc.createElement('span');
      glyph.className='pa-glyph';
      glyph.textContent=item.glyph;
      glyph.setAttribute('aria-hidden','true');

      const text=doc.createElement('span');
      text.className='pa-txt';
      const title=doc.createElement('strong');
      title.className='pa-title';
      const sub=doc.createElement('span');
      sub.className='pa-sub';
      text.appendChild(title);
      text.appendChild(sub);

      const chevron=doc.createElement('span');
      chevron.className='pa-chev';
      chevron.textContent='▾';
      chevron.setAttribute('aria-hidden','true');

      head.appendChild(glyph);
      head.appendChild(text);
      head.appendChild(chevron);

      const close=doc.createElement('button');
      close.type='button';
      close.className='pa-close';
      close.setAttribute('aria-label','Écarter cet avertissement');
      close.textContent='×';

      const body=doc.createElement('div');
      body.className='pa-body';
      body.id=bodyId;
      body.hidden=true;

      element.appendChild(head);
      element.appendChild(close);
      element.appendChild(body);

      const card={element:element,head:head,title:title,sub:sub,body:body,item:null,open:false};
      head.addEventListener('click',function(){toggle(card)});
      close.addEventListener('click',function(){dismiss(item.id)});
      update(card,item);
      host.appendChild(element);
      return card;
    }

    function update(card,item){
      card.item=item;
      card.element.setAttribute(DOM.toneAttribute,item.tone);
      /* `textContent` partout. Le domaine ne nettoie délibérément pas ses
         textes — « la marge < 10 % » est une phrase française ordinaire — donc
         c'est ici que l'échappement se fait, et il se fait par construction
         plutôt que par une fonction qu'on peut oublier d'appeler. */
      card.title.textContent=item.title;
      card.sub.textContent=item.detail||item.bandWord;
      if(card.open)fill(card);
    }

    function toggle(card){
      card.open=!card.open;
      card.element.setAttribute(DOM.openAttribute,card.open?'true':'false');
      card.head.setAttribute('aria-expanded',card.open?'true':'false');
      card.body.hidden=!card.open;
      if(card.open)fill(card);
      else while(card.body.firstChild)card.body.removeChild(card.body.firstChild);
    }

    /* Les preuves. Des références, jamais une phrase venue de la salle : le
       Core ne fait pas descendre `reason` dans la trace, et c'est délibéré.
       Ce que l'avertissement montre, c'est la nature du doute et **où** est la
       preuve ; ce que Jarvis a compris se demande — D11 dit qu'il ne
       l'explique pas de lui-même. */
    function fill(card){
      const item=card.item;
      while(card.body.firstChild)card.body.removeChild(card.body.firstChild);
      const headline=doc.createElement('p');
      headline.className='pa-headline';
      headline.textContent=item.headline;
      card.body.appendChild(headline);
      if(item.sources.length){
        const list=doc.createElement('ul');
        list.className='pa-sources';
        for(let i=0;i<item.sources.length;i+=1){
          const source=item.sources[i];
          const row=doc.createElement('li');
          const node=doc.createElement(source.openable?'a':'span');
          node.className='pa-src';
          node.textContent=source.title;
          node.title=source.locator;
          if(source.openable){
            node.href=source.locator;
            node.target='_blank';
            node.rel='noreferrer noopener';
          }
          row.appendChild(node);
          list.appendChild(row);
        }
        card.body.appendChild(list);
      }
      const note=doc.createElement('p');
      note.className='pa-note';
      note.textContent='Jarvis ne le dira pas de lui-même : demandez-lui ce qu’il a trouvé.';
      card.body.appendChild(note);
    }

    /* Écarter **ne touche aucun fait**. Aucun appel réseau, aucun
       acquittement : l'ensemble de travail vit dans un autre processus et cette
       page n'a aucun chemin vers lui. Le point reste compté dans la pastille
       « points à vérifier », où il s'acquitte par la porte existante. */
    function dismiss(id){
      if(dismissed.indexOf(id)<0)dismissed=dismissed.concat([id]).slice(-CUE.maxDismissed);
      rememberDismissed(storage,dismissed);
      signature='';
      const card=cards[id];
      if(card&&card.element&&card.element.parentNode)
        card.element.parentNode.removeChild(card.element);
      delete cards[id];
      log('presentation_attention.dismissed',{attention_id:id});
    }

    function mayCue(seq){
      return claimCue(seq,{storage:storage,now:now(),tabId:tabId});
    }

    return {
      gate:gate,
      statusLost:statusLost,
      dismiss:dismiss,
      mayCue:mayCue,
      shown:function(){const out=[];for(const id in cards)out.push(id);return out},
      dismissedIds:function(){return dismissed.slice()},
      isOpen:function(id){return !!(cards[id]&&cards[id].open)},
      armed:function(){return armed},
    };
  }

  const API=Object.freeze({
    DOM:DOM,CUE:CUE,CATEGORY:CATEGORY,BAND:BAND,OPENABLE:OPENABLE,STYLE:STYLE,
    categoryOf:categoryOf,bandWord:bandWord,openable:openable,
    viewOf:viewOf,sourcesOf:sourcesOf,claimCue:claimCue,
    dismissedFrom:dismissedFrom,installStyle:installStyle,
    createAttentionWarning:createAttentionWarning,
  });

  root.JarvisPresentationAttention=API;
  if(typeof module!=='undefined'&&module.exports)module.exports=API;
  if(typeof window==='undefined'||typeof document==='undefined')return;

  function safeStorage(){
    /* Un accès à `localStorage` peut lever avant même d'être lu — stockage
       bloqué, fenêtre privée, origine opaque. On le touche une fois, ici, et
       on retombe sur `null` : la porte du son s'ouvre alors, et les cartes
       cessent seulement de se souvenir de ce qu'on a écarté. */
    try{
      const store=window.localStorage;
      store.setItem('jarvis.pa.probe','1');
      store.removeItem('jarvis.pa.probe');
      return store;
    }catch(error){return null}
  }

  function installJarvisPresentationAttention(){
    const host=document.getElementById(DOM.hostId);
    if(!host)
      throw Object.assign(new Error('pile d’infusions absente : #'+DOM.hostId),
        {code:'presentation_attention_host_missing'});
    const control=createAttentionWarning({
      document:document,
      host:host,
      storage:safeStorage(),
      now:function(){return Date.now()},
      /* Un identifiant d'onglet, refait à chaque chargement : le bail doit
         distinguer deux onglets, pas deux visites. */
      tabId:'t'+Math.random().toString(36).slice(2)+Date.now().toString(36),
      log:function(event,data){
        if(event==='presentation_attention.dismissed')console.info('[attention] '+event,data);
        else console.error('[attention] '+event,data);
      },
    });
    window.JarvisPresentationAttentionControl=Object.freeze({
      gate:control.gate,
      statusLost:control.statusLost,
      mayCue:control.mayCue,
      dismiss:control.dismiss,
      shown:control.shown,
    });
    console.info('[attention] presentation_attention.installed '
      +JSON.stringify({host:DOM.hostId,storage:!!safeStorage()}));
  }

  try{installJarvisPresentationAttention()}
  catch(error){
    console.error('[attention] presentation_attention.install_failed '
      +JSON.stringify({code:(error&&error.code)||'unknown',
        message:(error&&error.message)||String(error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
