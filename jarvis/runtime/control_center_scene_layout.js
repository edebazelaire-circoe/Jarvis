/* Scène constellation : logique pure du rendu (handoff
   jarvis-constellation-scene-runtime, Slice 05).

   - Repère d'écran : origine (0, 0) au centre de la fenêtre, x vers la droite,
     y vers le bas, unités de scène. Le cadre de référence x ∈ [-160, 160],
     y ∈ [-90, 90] (16:9) est toujours entièrement visible : échelle uniforme
     `min(largeur / 320, hauteur / 180)` pixels par unité, centrée. Un autre
     rapport de fenêtre montre plus de scène sur l'axe long (pas de bandes).
     `geometry {x, y}` est le coin haut gauche de la boîte ; un point est
     dessiné au centre de sa boîte. Hors de la fenêtre, un objet n'est jamais
     déplacé (Décision 10) : il est compté « hors champ ».
   - AutoResolver contraint (Décisions 8–10) : épinglé par l'utilisateur, puis
     placement explicite (cerveau, utilisateur, résolveur déjà validé), puis
     résolveur. Il ne place que les objets sans géométrie et ne déplace rien
     d'autre. Déterministe pour une même entrée, travail borné.
   - Modèle de vue : ce que la page dessine, texte neutralisé (contrôles,
     marques bidi, caractères invisibles) pour un rendu par `textContent`.
   - Registre des validations du résolveur : une commande par objet, jamais de
     boucle.
   - Artefacts (Slice 07) : vue d'inspection d'un résultat groupé, lien
     `explains` vers ce qu'il explique, liens http(s) ouvrables seulement après
     validation par l'analyseur d'URL (`linkOf`).

   Aucune dépendance au DOM, au réseau ni à l'horloge : les tests l'exécutent
   avec node (`tests/unit/test_scene_renderer_logic.py`). Inséré tel quel dans
   la page par `ControlCenter.index` ; n'expose que `window.JarvisSceneLayout`. */
(function(root){
  'use strict';

  /* ------------------------------------------------------------------ repère */

  const FRAME=Object.freeze({halfWidth:160,halfHeight:90});
  /* Zone de composition sûre : la partie du cadre qu'aucune commande de la page
     ne recouvre à la plus petite taille 16:9 prise en charge (1280 × 720, 4 px
     par unité), dans les deux thèmes — barre du haut et dock Cosmos en haut,
     dock du thème circuit à droite, indication vocale et indicateurs de scène
     en bas. Plus grande fenêtre : les commandes y occupent encore moins
     d'unités. Le résolveur ne pose qu'ici ; le cerveau en reçoit les bornes.
     Même valeur dans `jarvis/domain/scene.py` (test de parité). */
  const SAFE_AREA=Object.freeze({x0:-152,x1:138,y0:-72,y1:68});
  /* Le visage (iframe ou canevas Cosmos) occupe le centre : le résolveur
     l'évite de préférence, sans l'interdire. */
  const FACE_ZONE=Object.freeze({x0:-34,x1:34,y0:-34,y1:34});
  const OBJECT_LIMIT=512;
  /* Taille par défaut d'un objet posé par le résolveur, en unités. */
  const DEFAULT_SIZE=Object.freeze({
    point:Object.freeze({w:6,h:6}),
    signal:Object.freeze({w:4,h:4}),
    capsule:Object.freeze({w:40,h:7}),
    window:Object.freeze({w:64,h:40}),
  });
  /* Travail maximal d'une passe (comparaisons de boîtes) : au-delà, les objets
     restants prennent leur premier emplacement admissible sans comparaison. */
  const WORK_BUDGET=400000;
  const MAX_ROOT_CANDIDATES=1200;

  /* Correspondance fenêtre ↔ scène pour une fenêtre de `width` × `height` px. */
  function viewport(width,height){
    const w=Math.max(1,Number(width)||0),h=Math.max(1,Number(height)||0);
    const scale=Math.min(w/(2*FRAME.halfWidth),h/(2*FRAME.halfHeight));
    return {width:w,height:h,scale,cx:w/2,cy:h/2,
      visible:{x0:-w/2/scale,x1:w/2/scale,y0:-h/2/scale,y1:h/2/scale}};
  }

  const round1=v=>Math.round(v*10)/10;

  /* Boîte en unités de scène → boîte en pixels de la fenêtre. */
  function toScreen(vp,box){
    return {left:round1(vp.cx+box.x*vp.scale),top:round1(vp.cy+box.y*vp.scale),
      width:round1(box.w*vp.scale),height:round1(box.h*vp.scale)};
  }

  /* ----------------------------------------------------------- texte affiché */

  /* Marques et isolats bidirectionnels : ils peuvent retourner l'ordre
     d'affichage d'un résumé (« usurpation » de contenu). */
  const BIDI=/[\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/g;
  /* Caractères invisibles : largeur nulle, joncteurs, BOM, césure molle. */
  const INVISIBLE=/[\u00AD\u180E\u200B-\u200D\u2060-\u2064\uFEFF]/g;
  const SEPARATORS=/[\u2028\u2029]/g;
  const CONTROLS_LINE=/[\u0000-\u001F\u007F-\u009F]/g;
  const CONTROLS_MULTI=/[\u0000-\u0008\u000B-\u001F\u007F-\u009F]/g;

  function clip(text,max){
    const chars=Array.from(text);
    return chars.length>max?chars.slice(0,Math.max(0,max-1)).join('')+'…':text;
  }

  /* Une ligne affichable : contrôles et séparateurs → espace, marques bidi et
     invisibles retirées, espaces resserrés, bornée à `max` caractères. */
  function cleanLine(value,max=160){
    if(typeof value!=='string')return '';
    const text=value.replace(SEPARATORS,' ').replace(CONTROLS_LINE,' ').replace(BIDI,'').replace(INVISIBLE,'')
      .replace(/\s+/g,' ').trim();
    return clip(text,max);
  }

  /* Un texte sur plusieurs lignes (résumé) : `\n` gardé, tabulation → espace,
     séparateurs Unicode → `\n`, autres contrôles, bidi et invisibles retirés. */
  function cleanText(value,max=2000){
    if(typeof value!=='string')return '';
    const text=value.replace(/\r\n?/g,'\n').replace(SEPARATORS,'\n').replace(/\t/g,' ').replace(CONTROLS_MULTI,'')
      .replace(BIDI,'').replace(INVISIBLE,'').replace(/\n{3,}/g,'\n\n').trim();
    return clip(text,max);
  }

  /* ----------------------------------------------------------------- markdown */

  /* Le cerveau écrit ses titres et ses résumés en markdown : la scène les
     interprète au lieu d'en montrer la ponctuation (demande de l'utilisateur,
     21/09/2026). Sous-ensemble délibérément petit et hors ligne — titres,
     paragraphes, listes (imbriquées), citations, filets, blocs et fragments de
     code, gras, italique, barré, liens. Ni tableau, ni HTML : ce qui n'est pas
     reconnu reste le texte qu'il était.

     Le texte d'un objet est une **donnée** d'affichage, jamais un fragment de
     page : ces fonctions ne rendent qu'une structure, et la page la dessine
     nœud par nœud, chaque texte par `textContent`, jamais par une chaîne de
     balisage. Un
     lien n'est un lien que si `linkOf` l'accepte (http/https, sans
     identifiants) ; sinon son libellé reste du texte.

     Formes rendues :
       span   {text, bold?, italic?, strike?, code?, href?, host?}
       blocs  {kind:'p', spans} · {kind:'h', level, spans} · {kind:'hr'}
              {kind:'code', text} · {kind:'quote', blocks}
              {kind:'list', ordered, start, items:[{blocks}]} */

  /* Caractères qu'une barre oblique inverse protège. */
  const MD_ESCAPABLE='\\`*_~[]()#+-.!>';
  /* Imbrication bornée : au-delà, le reste devient un paragraphe. Un résumé
     tient en 2 000 caractères, mais rien n'oblige le cerveau à être sobre. */
  const MD_MAX_DEPTH=6;
  const MD_FENCE=/^ {0,3}(```|~~~)\s*(.*)$/;
  const MD_HEADING=/^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
  const MD_HR=/^ {0,3}(?:\*[ \t]*){3,}$|^ {0,3}(?:-[ \t]*){3,}$|^ {0,3}(?:_[ \t]*){3,}$/;
  const MD_QUOTE=/^ {0,3}>[ \t]?(.*)$/;
  const MD_ITEM=/^( *)([-*+]|\d{1,9}[.)])[ \t]+(.*)$/;
  const MD_CODE_SPAN=/^(`+)([^`][\s\S]*?)\1(?!`)/;
  const MD_LINK=/^!?\[([^\]\n]*)\]\([ \t]*([^\s()]*)[ \t]*\)/;
  /* Du plus long délimiteur au plus court : `***a***` est gras et italique, pas
     un italique qui commence par une étoile. */
  const MD_EMPHASIS=Object.freeze([
    {re:/^(\*\*\*|___)(?=\S)([\s\S]*?\S)\1/,style:{bold:true,italic:true}},
    {re:/^(\*\*|__)(?=\S)([\s\S]*?\S)\1/,style:{bold:true}},
    {re:/^(~~)(?=\S)([\s\S]*?\S)\1/,style:{strike:true}},
    {re:/^(\*|_)(?=\S)([\s\S]*?\S)\1/,style:{italic:true}},
  ]);

  /* Texte en ligne d'une seule ligne logique. `style` porte les marques
     héritées : la récursion entre dans le contenu d'un délimiteur, donc un
     fragment de code écrit dans du gras garde les deux. Chaque appel travaille
     sur un texte strictement plus court, la récursion se termine d'elle-même. */
  function markdownSpans(value,style){
    const src=typeof value==='string'?value:'';
    const base=style||{};
    const out=[];
    let buf='',i=0;
    const flush=()=>{if(buf){out.push(Object.assign({text:buf},base));buf=''}};
    while(i<src.length){
      const ch=src[i];
      if(ch==='\\'&&i+1<src.length&&MD_ESCAPABLE.indexOf(src[i+1])>=0){buf+=src[i+1];i+=2;continue}
      const rest=src.slice(i);
      let hit=null;
      if(ch==='`'&&(hit=MD_CODE_SPAN.exec(rest))){
        flush();
        /* Une espace de chaque côté sert à écrire un accent grave : elle borde
           le fragment, elle n'en fait pas partie. */
        out.push(Object.assign({text:hit[2].replace(/^ ([\s\S]*) $/,'$1')},base,{code:true}));
        i+=hit[0].length;continue;
      }
      if((ch==='['||(ch==='!'&&src[i+1]==='['))&&(hit=MD_LINK.exec(rest))){
        flush();
        const link=linkOf(hit[2]);
        const label=hit[1]||(link?link.host:hit[2]);
        for(const span of markdownSpans(label,base))
          out.push(link?Object.assign({},span,{href:link.href,host:link.host}):span);
        i+=hit[0].length;continue;
      }
      if(ch==='*'||ch==='_'||ch==='~'){
        /* Un tiret bas au milieu d'un mot (`nom_de_variable`) n'ouvre pas
           d'italique. L'étoile, elle, sépare toujours. */
        const inWord=i>0&&/[\w]/.test(src[i-1]);
        let taken=false;
        for(const rule of MD_EMPHASIS){
          const found=rule.re.exec(rest);
          if(!found||(found[1][0]==='_'&&inWord))continue;
          flush();
          for(const span of markdownSpans(found[2],Object.assign({},base,rule.style)))out.push(span);
          i+=found[0].length;taken=true;break;
        }
        if(taken)continue;
      }
      buf+=ch;i++;
    }
    flush();
    return out;
  }

  /* Le même texte sans sa ponctuation markdown : ce que lisent un nom
     accessible, une infobulle ou un libellé d'objet, où le gras n'existe pas. */
  function markdownText(value){
    return markdownSpans(value).map(span=>span.text).join('');
  }

  /* Indentation d'une ligne, en espaces (les tabulations sont déjà devenues des
     espaces dans `cleanText`). */
  function mdIndent(line){return line.length-line.replace(/^ +/,'').length}

  /* Entrée de liste : `null` si la ligne n'en est pas une. `lead` est la
     colonne où commence son contenu, celle qui définit son imbrication. */
  function mdItem(line){
    const m=MD_ITEM.exec(line);
    if(!m)return null;
    return {indent:m[1].length,ordered:!/^[-*+]$/.test(m[2]),
      start:parseInt(m[2],10)||1,text:m[3],lead:m[0].length-m[3].length};
  }

  /* Liste ouverte en `from`. Rend le bloc et la première ligne qui ne lui
     appartient plus. Avance toujours d'au moins une ligne. */
  function mdList(lines,from,depth){
    const first=mdItem(lines[from]);
    const items=[];
    let i=from;
    while(i<lines.length){
      if(!lines[i].trim()){
        /* Ligne vide : la liste continue si une entrée de même famille suit. */
        let j=i;while(j<lines.length&&!lines[j].trim())j++;
        const next=j<lines.length?mdItem(lines[j]):null;
        if(next&&next.ordered===first.ordered&&next.indent>=first.indent&&next.indent<=first.indent+3){i=j;continue}
        break;
      }
      const mark=mdItem(lines[i]);
      if(!mark||mark.ordered!==first.ordered||mark.indent<first.indent||mark.indent>first.indent+3)break;
      const body=[mark.text];
      const column=mark.lead;
      i++;
      while(i<lines.length){
        if(!lines[i].trim()){
          let j=i;while(j<lines.length&&!lines[j].trim())j++;
          if(j<lines.length&&mdIndent(lines[j])>=column){body.push('');i=j;continue}
          break;
        }
        if(mdIndent(lines[i])>=column){body.push(lines[i].slice(column));i++;continue}
        /* Suite paresseuse : une ligne de texte simple, moins indentée, achève
           la phrase de l'entrée au lieu d'ouvrir un bloc. */
        const line=lines[i];
        if(!mdItem(line)&&!MD_HR.test(line)&&!MD_HEADING.test(line)&&!MD_QUOTE.test(line)&&!MD_FENCE.test(line)){
          body.push(line.trim());i++;continue;
        }
        break;
      }
      items.push({blocks:markdownBlocks(body.join('\n'),depth+1)});
    }
    return {next:i,block:{kind:'list',ordered:first.ordered,start:first.start,items}};
  }

  /* Blocs d'un texte markdown. `depth` borne l'imbrication. */
  function markdownBlocks(value,depth){
    const level=Number.isInteger(depth)?depth:0;
    const lines=(typeof value==='string'?value:'').split('\n');
    const out=[];
    let para=[],i=0;
    const flush=()=>{
      const text=para.join('\n').trim();
      para=[];
      if(text)out.push({kind:'p',spans:markdownSpans(text)});
    };
    if(level>=MD_MAX_DEPTH){
      const text=lines.join(' ').trim();
      return text?[{kind:'p',spans:markdownSpans(text)}]:[];
    }
    while(i<lines.length){
      const line=lines[i];
      if(!line.trim()){flush();i++;continue}
      let m=MD_FENCE.exec(line);
      if(m){
        flush();
        const close=new RegExp('^ {0,3}'+m[1][0]+'{3,} *$'),body=[];
        i++;
        while(i<lines.length&&!close.test(lines[i])){body.push(lines[i]);i++}
        if(i<lines.length)i++;
        out.push({kind:'code',text:body.join('\n')});
        continue;
      }
      m=MD_HEADING.exec(line);
      if(m){flush();out.push({kind:'h',level:m[1].length,spans:markdownSpans(m[2])});i++;continue}
      if(MD_HR.test(line)){flush();out.push({kind:'hr'});i++;continue}
      if(MD_QUOTE.test(line)){
        flush();
        const body=[];
        while(i<lines.length){
          const quoted=MD_QUOTE.exec(lines[i]);
          if(quoted){body.push(quoted[1]);i++;continue}
          /* Suite paresseuse d'une citation : du texte simple, sans chevron. */
          if(lines[i].trim()&&!mdItem(lines[i])&&!MD_HR.test(lines[i])&&!MD_HEADING.test(lines[i])&&!MD_FENCE.test(lines[i])){
            body.push(lines[i]);i++;continue;
          }
          break;
        }
        out.push({kind:'quote',blocks:markdownBlocks(body.join('\n'),level+1)});
        continue;
      }
      if(mdItem(line)){
        flush();
        const read=mdList(lines,i,level);
        out.push(read.block);i=read.next;
        continue;
      }
      para.push(line);i++;
    }
    flush();
    return out;
  }

  /* Le même markdown à plat, une ligne à la fois : ce que la capture sait
     dessiner (un seul texte par ligne, pas de marque riche). Rend
     `[{text, indent, bold}]` — `indent` en crans de citation ou de liste. La
     capture doit montrer ce que l'utilisateur voit, donc elle ne montre pas
     d'astérisques là où la page dessine du gras. */
  function markdownLines(value){
    const out=[];
    const spansText=spans=>(spans||[]).map(span=>span.text).join('');
    const push=(text,indent,bold)=>{out.push({text,indent,bold:!!bold})};
    const walk=(blocks,indent)=>{
      for(const block of blocks){
        if(block.kind==='hr'){push('—————',indent,false);continue}
        if(block.kind==='code'){for(const line of block.text.split('\n'))push(line,indent,false);continue}
        if(block.kind==='h'){push(spansText(block.spans),indent,true);continue}
        if(block.kind==='quote'){walk(block.blocks,indent+1);continue}
        if(block.kind==='list'){
          let rank=block.start;
          for(const item of block.items){
            const marker=block.ordered?`${rank++}. `:'• ';
            const at=out.length;
            walk(item.blocks,indent+1);
            /* La puce rejoint la première ligne de l'entrée, au cran du parent. */
            if(out.length>at)out[at]={text:marker+out[at].text,indent,bold:out[at].bold};
            else push(marker,indent,false);
          }
          continue;
        }
        for(const line of spansText(block.spans).split('\n'))push(line,indent,false);
      }
    };
    walk(markdownBlocks(value),0);
    return out;
  }

  /* --------------------------------------------------------------- sémantique */

  /* Couleur = catégorie (Décision 7). Familles connues, puis teinte stable
     tirée du nom pour toute autre catégorie. */
  const CATEGORY_TONES=Object.freeze({
    agent:'agent',job:'job',
    note:'doc',notes:'doc',doc:'doc',docs:'doc',documentation:'doc',artifact:'doc',summary:'doc',report:'doc',document:'doc',
    research:'research',web:'research',search:'research',history:'research',source:'research',sources:'research',
    code:'code',diff:'code',files:'code',file:'code',fichiers:'code',fichier:'code',git:'code',test:'code',tests:'code',api:'code',build:'code',
    email:'comms',mail:'comms',message:'comms',messages:'comms',trello:'comms',roadmap:'comms',calendar:'comms',meeting:'comms',
    /* « autre » : artefact sans famille, couleur des documents (Slice 07). */
    autre:'doc',other:'doc',
    error:'error',errors:'error',failed:'error',failure:'error',alert:'error',
    interrupted:'interrupted',cancelled:'interrupted',
    blocked:'blocked',attention:'blocked',question:'blocked',
  });
  const HASHED_TONES=Object.freeze(['x0','x1','x2','x3','x4','x5']);

  function toneOf(category){
    const key=String(category||'').toLowerCase();
    if(Object.prototype.hasOwnProperty.call(CATEGORY_TONES,key))return CATEGORY_TONES[key];
    let hash=2166136261;
    for(let i=0;i<key.length;i++){hash^=key.charCodeAt(i);hash=Math.imul(hash,16777619)>>>0}
    return HASHED_TONES[hash%HASHED_TONES.length];
  }

  /* Même règle que `is_live_signal` (jarvis/domain/scene.py) : un signal est
     vivant exactement tant que son lien `explains` (identifiant = celui du
     signal) existe. Sa catégorie ne dit rien de sa vie. */
  function isLiveSignal(state,objectId){
    const item=state.objects.get(objectId);
    if(!item||item.kind!=='attention')return false;
    const rel=state.relations.get(objectId);
    return !!rel&&rel.kind==='explains'&&rel.relation_id===rel.from_id;
  }

  /* Interruptions dues au cycle de vie de l'hôte, pas au travail : l'arrêt du
     CLI du cerveau pose un signal par sous-agent en cours. Le projecteur de
     Core (Slice 04) écrit un signal runtime dont la catégorie et
     l'`exec_state` sont le statut du travail et dont `payload.title` est la
     classe d'erreur (seul champ où elle voyage). */
  const LOW_URGENCY_ERRORS=new Set(['process_stopped']);

  /* Classe d'erreur portée par un signal du runtime, ou ''. */
  function signalErrorClass(item){
    if(item.kind!=='attention'||item.origin!=='runtime')return '';
    return String(item.payload&&item.payload.title||'');
  }

  /* Urgence d'un signal : `none` (retiré), `low`, `medium`, `high`. Basse :
     signal du runtime de catégorie `interrupted` et de classe
     `process_stopped`. */
  function signalUrgency(state,item){
    if(!isLiveSignal(state,item.object_id))return 'none';
    if(item.category==='interrupted'&&LOW_URGENCY_ERRORS.has(signalErrorClass(item)))return 'low';
    if(item.exec_state==='failed'||toneOf(item.category)==='error')return 'high';
    return 'medium';
  }

  const EXEC_LABELS=Object.freeze({unknown:'',pending:'en attente',running:'en cours',blocked:'bloqué',
    completed:'terminé',failed:'échec',cancelled:'annulé',interrupted:'interrompu'});
  const KIND_LABELS=Object.freeze({agent:'sous-agent',job:'tâche',artifact:'résultat',attention:'signal',window:'fenêtre',group:'groupe'});
  /* Slice 10 : une étoile d'exécution `unknown` est une étoile d'une vie
     précédente de Core que personne n'a encore redite. Indice secondaire
     (ni « en cours », ni alarme) jusqu'à la fin de la grâce, où Core la dit
     interrompue avec son signal. Un artefact ou une fenêtre `unknown` n'a
     simplement pas de travail : aucun libellé. */
  const RESTART_UNKNOWN_LABEL='état inconnu depuis le redémarrage';
  function restartUnknown(item){
    return (item.kind==='agent'||item.kind==='job')&&item.exec_state==='unknown';
  }
  function execLabelOf(item,exec){
    return restartUnknown(item)?RESTART_UNKNOWN_LABEL:EXEC_LABELS[exec];
  }

  /* Titre affiché d'un signal du runtime : sa classe d'erreur dans les mots de
     la page (`errorLabels` = `ERROR_CLASSES` du Control Center), un statut
     brut dans sa forme française, sinon le titre tel quel. */
  function displayTitle(item,title,errorLabels){
    const code=signalErrorClass(item);
    if(!code)return title;
    if(errorLabels&&Object.prototype.hasOwnProperty.call(errorLabels,code))return cleanLine(String(errorLabels[code]),160);
    if(EXEC_LABELS[code])return EXEC_LABELS[code];
    return title;
  }

  /* ------------------------------------------------------------ artefacts */

  /* Catégories d'artefact conseillées au cerveau (Slice 07,
     `RECOMMENDED_ARTIFACT_CATEGORIES` de `display_mcp.py`, test de parité) :
     chacune a une famille de couleur connue. Liste ouverte : une autre
     catégorie prend une teinte stable tirée de son nom. */
  const ARTIFACT_CATEGORIES=Object.freeze(['research','fichiers','tests','api','roadmap','email','document','autre']);

  /* Blancs, contrôles C0/C1 et DEL, espace insécable, marques bidi, caractères
     invisibles, séparateurs, points pleine chasse et idéographiques, barre
     oblique inverse : même classe que `_UNSAFE` de `jarvis/domain/scene_links.py`. */
  const UNSAFE_URL=/[\u0000-\u0020\u007F-\u00A0\u00AD\u061C\u180E\u200B-\u200F\u2028-\u202F\u205F-\u206F\u3000\u3002\uFEFF\uFF0E\uFF61\\]/;
  const MAX_LINK_CHARS=2048;
  const NAME_HOST=/^([A-Za-z0-9.-]+)(?::([0-9]{1,5}))?$/;
  const IPV6_HOST=/^\[([0-9A-Fa-f:]+)\](?::([0-9]{1,5}))?$/;
  const HOST_LABEL=/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
  const NUMERIC_LABEL=/^(?:[0-9]+|0x[0-9a-f]*)$/;
  const OCTET=/^(?:0|[1-9][0-9]{0,2})$/;
  const URL_ASCII=/^[A-Za-z0-9\-._~:\/?#\[\]@!$&()*+,;=%]$/;

  /* Longueur de l'URL percent-encodée, majorée : même calcul que `link_length`
     (`jarvis/domain/scene_links.py`), par point de code. ASCII sûr 1, autre
     ASCII 3, non-ASCII 3 × octets UTF-8, substitut isolé 9 ; + 1 quand le
     navigateur ajoute `/` après l'autorité. Jamais inférieure à `href.length`. */
  function linkLength(value){
    let total=0;
    for(const char of value){
      const code=char.codePointAt(0);
      if(code<0x80)total+=URL_ASCII.test(char)?1:3;
      else if(code>=0xD800&&code<=0xDFFF)total+=9;
      else total+=3*(code<0x800?2:code<0x10000?3:4);
    }
    const index=value.indexOf('://');
    const rest=index<0?'':value.slice(index+3);
    const authority=rest.split(/[/?#]/,1)[0];
    if(!rest.slice(authority.length).startsWith('/'))total+=1;
    return total;
  }

  /* IPv6 compressée comme le navigateur (RFC 5952), entre crochets, ou `null`. */
  function ipv6Host(text){
    if(text.split('::').length>2)return null;
    let groups;
    if(text.includes('::')){
      const [head,tail]=text.split('::');
      const left=head?head.split(':'):[],right=tail?tail.split(':'):[];
      if(left.length+right.length>7)return null;
      groups=[...left,...Array(8-left.length-right.length).fill('0'),...right];
    }else{
      groups=text.split(':');
      if(groups.length!==8)return null;
    }
    if(groups.some(group=>!/^[0-9A-Fa-f]{1,4}$/.test(group)))return null;
    const values=groups.map(group=>parseInt(group,16).toString(16));
    let bestStart=-1,bestLength=0,start=-1;
    [...values,'end'].forEach((value,index)=>{
      if(value==='0'){if(start<0)start=index;return}
      if(start>=0&&index-start>bestLength){bestStart=start;bestLength=index-start}
      start=-1;
    });
    if(bestLength<2)return `[${values.join(':')}]`;
    return `[${values.slice(0,bestStart).join(':')}::${values.slice(bestStart+bestLength).join(':')}]`;
  }

  /* Hôte d'une URL qui peut être un lien, ou `null` : règle unique partagée
     avec `link_host` (`jarvis/domain/scene_links.py`, corpus commun
     `tests/fixtures/scene_link_corpus.json`). http(s) exact, aucune barre
     oblique inverse, aucun blanc/contrôle/bidi/invisible/point pleine chasse,
     autorité sans `@` ni `%`, hôte ASCII à étiquettes standard (pas de `xn--`)
     ou IPv4 pointée stricte ou IPv6 entre crochets, port 0–65535. */
  function linkHost(value){
    /* `length` (UTF-16) ≤ `linkLength` : le premier test borne le calcul sans changer la règle. */
    if(typeof value!=='string'||!value||value.length>MAX_LINK_CHARS||UNSAFE_URL.test(value))return null;
    if(linkLength(value)>MAX_LINK_CHARS)return null;
    let rest;
    if(value.startsWith('https://'))rest=value.slice(8);
    else if(value.startsWith('http://'))rest=value.slice(7);
    else return null;
    const authority=rest.split(/[/?#]/,1)[0];
    if(authority.includes('@')||authority.includes('%'))return null;
    let host,port;
    const v6=IPV6_HOST.exec(authority);
    if(v6){host=ipv6Host(v6[1]);port=v6[2]}
    else{
      const name=NAME_HOST.exec(authority);
      if(!name)return null;
      host=name[1].toLowerCase();port=name[2];
      const labels=host.split('.');
      if(host.length>253||labels.some(label=>!HOST_LABEL.test(label)||label.startsWith('xn--')))return null;
      if(NUMERIC_LABEL.test(labels[labels.length-1])&&!(labels.length===4&&labels.every(label=>OCTET.test(label)&&Number(label)<=255)))return null;
    }
    if(host===null||(port!==undefined&&Number(port)>65535))return null;
    return host;
  }

  /* Lien ouvrable d'une entrée d'artefact : `{href, host}` ou `null`.

     `linkHost` décide (même règle que l'hôte rendu au cerveau par
     `scene_get`) ; l'analyseur d'URL du navigateur doit ensuite lire le même
     hôte, sans identifiants, sinon pas de lien (défense de plus). `href` est
     la forme normalisée par l'analyseur ; `host` est affiché avant le libellé
     pour que la destination se lise. Tout le reste reste du texte. */
  function linkOf(value){
    const host=linkHost(value);
    if(host===null)return null;
    let parsed;
    try{parsed=new URL(value)}catch(_error){return null}
    if((parsed.protocol!=='https:'&&parsed.protocol!=='http:')||parsed.username||parsed.password||parsed.hostname!==host)return null;
    const href=parsed.href;
    if(!/^https?:\/\//.test(href)||href.length>MAX_LINK_CHARS)return null;
    return {href,host};
  }

  /* Première cible active de chaque source par `explains` (hors lien de
     signal), en une passe sur les relations : `source → objet cible`. */
  function explainsIndex(state){
    const index=new Map();
    for(const rel of state.relations.values()){
      if(rel.kind!=='explains'||rel.relation_id===rel.from_id||index.has(rel.from_id))continue;
      const target=state.objects.get(rel.to_id);
      if(target)index.set(rel.from_id,target);
    }
    return index;
  }

  /* Ce qu'un artefact explique : première relation `explains` (hors lien de
     signal) vers un objet actif. Rend `{id, title, kind, execLabel, tone,
     hidden}` ou `null`. `index` (`explainsIndex`) évite de relire toutes les
     relations pour chaque artefact d'un même rendu. */
  function explainedTarget(state,objectId,errorLabels,index){
    const target=(index||explainsIndex(state)).get(objectId);
    if(!target)return null;
    const exec=EXEC_LABELS[target.exec_state]!==undefined?target.exec_state:'unknown';
    const title=markdownText(displayTitle(target,cleanLine(target.payload&&target.payload.title,160),errorLabels));
    return {id:target.object_id,title:title||KIND_LABELS[target.kind]||target.kind,kind:target.kind,
      kindLabel:KIND_LABELS[target.kind]||target.kind,execLabel:execLabelOf(target,exec),tone:toneOf(target.category),
      hidden:target.visibility!=='visible'};
  }

  /* Artefact orphelin : aucun lien `explains` vers un objet actif (son étoile a
     été archivée, ou il n'a jamais été relié). Même règle que
     `is_orphan_artifact` (jarvis/domain/scene.py, test de parité) : seul
     l'archivage groupé « artefacts orphelins » de l'utilisateur le prend. */
  function isOrphanArtifact(state,objectId){
    const item=state.objects.get(objectId);
    if(!item||item.kind!=='artifact')return false;
    for(const rel of state.relations.values())if(rel.kind==='explains'&&rel.from_id===objectId)return false;
    return true;
  }

  /* Artefacts orphelins de la scène, dans l'ordre de Core. */
  function orphanArtifacts(state){
    const out=[];
    for(const item of state.objects.values())if(isOrphanArtifact(state,item.object_id))out.push(item.object_id);
    return out;
  }

  /* Artefacts qu'un archivage de `ids` laisserait orphelins : reliés par
     `explains`, mais seulement à des objets de `ids`. */
  function artifactsLeftOrphan(state,ids){
    const gone=new Set(ids),links=new Map();
    for(const rel of state.relations.values()){
      if(rel.kind!=='explains')continue;
      const source=state.objects.get(rel.from_id);
      if(!source||source.kind!=='artifact'||gone.has(rel.from_id))continue;
      const entry=links.get(rel.from_id)||{kept:false};
      if(!gone.has(rel.to_id))entry.kept=true;
      links.set(rel.from_id,entry);
    }
    return [...links].filter(([,entry])=>!entry.kept).map(([id])=>id);
  }

  /* Fin d'hôte affichable en `maxChars` caractères : l'hôte entier s'il tient,
     sinon `…` suivi de la **plus longue fin** qui tient (`maxChars − 1`
     caractères) : le domaine enregistrable, là où une usurpation ne peut pas se
     cacher, reste lisible autant que la place le permet
     (`secure.barclays.co.uk.login-check.co.uk` en 17 → `…gin-check.co.uk`,
     jamais `…co.uk` ni `secure.barclays…`). Couper sur une frontière de label
     laissait parfois voir bien moins que la place (reprise QA N1). Un point en
     tête de la fin est retiré. Jamais coupé à droite. */
  function hostTail(host,maxChars){
    const text=String(host||'');
    const max=Math.max(8,Math.floor(Number(maxChars)||0));
    if(text.length<=max)return text;
    let tail=text.slice(text.length-(max-1));
    if(tail.startsWith('.'))tail=tail.slice(1);
    return `…${tail}`;
  }

  /* Artefacts actifs qui expliquent `objectId` (lien `explains`, hors signal),
     dans l'ordre de Core. L'archivage d'une étoile ne les emporte pas
     (Slice 08) : la page le dit avant de confirmer. */
  function artifactsExplaining(state,objectId){
    const out=[];
    for(const rel of state.relations.values()){
      if(rel.kind!=='explains'||rel.to_id!==objectId||rel.relation_id===rel.from_id)continue;
      const source=state.objects.get(rel.from_id);
      if(source&&source.kind==='artifact'&&!out.includes(source.object_id))out.push(source.object_id);
    }
    return out;
  }

  /* Entrées affichées d'une charge : texte neutralisé ; `href`/`host` pour
     une URL ouvrable, sinon l'URL reste un texte (`url`). */
  function itemsOf(payload){
    const list=Array.isArray(payload.items)?payload.items.slice(0,32):[];
    return list.map(entry=>{
      const raw=entry&&typeof entry.url==='string'?entry.url:'';
      const link=linkOf(raw);
      /* L'hôte n'est jamais coupé ici : entier dans le nom accessible et
         l'infobulle, raccourci par la gauche seulement au dessin (`hostTail`). */
      return {label:cleanLine(entry&&entry.label,160),ref:cleanLine(entry&&entry.ref,256),
        url:link?'':cleanLine(raw,256),href:link?link.href:'',host:link?cleanLine(link.host,MAX_LINK_CHARS):''};
    });
  }

  /* Seuils de lisibilité (px) : sous eux, une fenêtre se dessine en capsule
     et une capsule en point, dans la page seulement (jamais validé, la
     représentation de la scène ne change pas). */
  const READABLE=Object.freeze({windowWidth:180,windowHeight:96,capsuleWidth:72});
  /* Capsule dessinée au plus à cette taille (unités, reprise QA Slice 08) :
     une boîte plus haute (fenêtre passée en capsule par le cerveau, objet
     épinglé qui garde sa boîte de fenêtre) est dessinée à la hauteur naturelle
     d'une capsule et au plus à cette largeur, centrée dans la boîte stockée.
     Rendu seulement : la géométrie de la scène ne change pas. Un point est
     déjà dessiné à sa taille, au centre de sa boîte. */
  const CAPSULE_MAX=Object.freeze({w:160,h:10});

  /* Zone dessinée d'un point (px, carrée, centrée) et hauteur minimale d'une
     capsule (px) : lues par la page (`position`) et par la capture. */
  const POINT_HIT_PX=26,CAPSULE_MIN_HEIGHT_PX=24;

  /* Rectangle dessiné d'un nœud du modèle de vue, en pixels de la fenêtre :
     seule source du placement des nœuds du DOM et de la capture (Slice 09,
     reprise QA M2). Point : zone `POINT_HIT_PX` centrée. Capsule : sa boîte, au
     moins `CAPSULE_MIN_HEIGHT_PX` de haut, centrée verticalement ; fenêtre
     dessinée en capsule faute de place (`compact`) : pilule de 28 px collée en
     haut de sa boîte. Fenêtre : sa boîte. */
  function drawnRect(node){
    if(node.shape==='point')return {left:node.cx-POINT_HIT_PX/2,top:node.cy-POINT_HIT_PX/2,width:POINT_HIT_PX,height:POINT_HIT_PX};
    if(node.shape==='capsule'){
      const height=node.compact?CAPSULE_MIN_HEIGHT_PX+4:Math.max(node.box.height,CAPSULE_MIN_HEIGHT_PX);
      return {left:node.box.left,top:node.compact?node.box.top:node.cy-height/2,width:node.box.width,height};
    }
    return {left:node.box.left,top:node.box.top,width:node.box.width,height:node.box.height};
  }

  /* Boîte dessinée d'une représentation dans sa boîte stockée (unités). */
  function drawnBox(representation,box){
    if(representation!=='capsule'||(box.w<=CAPSULE_MAX.w&&box.h<=CAPSULE_MAX.h))return box;
    const w=Math.min(box.w,CAPSULE_MAX.w),h=box.h>CAPSULE_MAX.h?DEFAULT_SIZE.capsule.h:box.h;
    return {x:box.x+(box.w-w)/2,y:box.y+(box.h-h)/2,w,h};
  }

  /* ---------------------------------------------------------- gravitation */

  /* La constellation tourne autour du centre de la fenêtre — le soleil JARVIS,
     dessiné par le visage, auquel la scène ne touche pas.

     **Une vraie rotation** : chaque objet parcourt le cercle centré sur ce
     point qui passe par sa place, dans le sens horaire, à vitesse angulaire
     constante — un tour par période, sans jamais s'arrêter ni repartir en
     arrière. Une étoile à gauche du visage se retrouve à sa droite au bout
     d'une demi-période ; c'est à cela qu'on voit que le champ tourne.

     Ce que faisaient les deux versions précédentes, et pourquoi c'était faux :
     la première échantillonnait l'angle sur `sin` du temps — un pendule, qui
     repart en arrière à chaque demi-période (« ça oscille »). La seconde a
     rendu l'angle monotone mais l'a appliqué à une *translation* : tous les
     objets recevaient le même décalage, donc aucune position relative ne
     changeait et rien ne tournait autour de rien (« ça ne bouge pas du tout »).
     Elle s'était imposé qu'aucun objet ne s'éloigne de sa place de plus d'un
     rayon — contrainte que personne n'avait demandée, et qui interdit la
     rotation par construction.

     Ce qui restait vrai de son raisonnement : les fils. Une rotation, comme
     une translation, envoie le segment qui joint deux objets sur le segment
     qui joint leurs deux nouvelles places. Les fils restent donc noués de
     centre à centre sans rattrapage — le calque des fils tourne d'un bloc, du
     même angle, autour du même centre.

     Ce qui borne le mouvement : une rotation garde chaque objet à distance
     constante du centre. Il suffit donc que le disque qu'il balaie tienne dans
     la zone sûre. Quand un objet est trop loin pour cela, tout le champ est
     rapproché du centre d'un même facteur (`scale`), une fois, sans animation :
     la composition se resserre sans se déformer, et le tour reste entier.

     Rendu seulement : rien n'est écrit dans la scène, la place de référence ne
     bouge pas d'un pixel, la capture ne voit que les places. Un objet épinglé
     tourne comme les autres — l'épingle protège la géométrie, pas le dessin ;
     qui veut une scène figée éteint la gravitation dans « Affichage des
     étoiles ». */

  /* Un tour complet à vitesse 1. Quatre minutes : le mouvement se voit sur une
     étoile qu'on suit, et ne tire pas l'œil pendant qu'on lit. */
  const ORBIT_PERIOD_MS=240000;
  /* En deçà de ce rayon, un objet est au centre : il ne tourne pas. Le visage y
     est, et un objet posé dessus doit y rester. */
  const ORBIT_CENTER_PX=3;
  /* Allongement maximal de l'ellipse. Le cadre est deux fois plus large que
     haut ; suivre ce format à la lettre ferait passer une étoile du haut de
     l'écran à son bord gauche, et la constellation se lirait comme un champ
     qu'on étire plutôt que comme un champ qui tourne. Une ellipse une fois et
     demie plus large que haute écarte le champ sans déformer ce qu'on voit. */
  const ORBIT_ASPECT_MAX=1.6;
  /* Formes qui ne tournent pas. Une fenêtre est un panneau qu'on lit, pas une
     étoile : la voir dériver sous les yeux pendant sa lecture est un défaut,
     pas une décoration (retour du 19/09/2026). */
  const ORBIT_STILL_SHAPES=Object.freeze(['window']);

  /* **L'ellipse du tour, en unités de scène** — une constante, et c'est tout
     l'enjeu du contrat géométrique (21/09/2026).

     `orbitField` la calculait en pixels, puis *resserrait* le champ d'un facteur
     `room` lu sur l'objet le plus excentré pour que son tour tienne dans la
     zone sûre. Ce facteur s'appliquait à **tous** les objets : déplacer une
     étoile, en archiver une, ou simplement en voir apparaître une au loin
     changeait la place dessinée de la constellation entière — jusqu'à 120 px de
     saut, sans transition, pour des objets que personne n'avait touchés. Et
     comme `placeOf` inverse le tour avec le champ d'*avant* le lâcher, l'objet
     lâché atterrissait lui-même à côté du curseur (293 px mesurés en 1080p) :
     l'identité `orbitTurnPoint(orbitUnturn(P, A), A) = P`, que les tests
     prouvaient, ne dit rien quand le champ passe de A à B entre les deux.

     La règle est désormais l'inverse : **c'est la place qui est bornée, pas le
     champ**. L'ellipse ne dépend que de la zone sûre et du format du cadre —
     en pixels ses demi-axes valent `unités × échelle`, donc en unités c'est une
     constante —, le facteur d'échelle ne dépend que du réglage de
     l'utilisateur, et une géométrie qui tourne est bornée à l'ellipse
     (`orbitFits`, repris par `clampBox` et par le résolveur). Aucun objet ne
     dépend plus de la place des autres. */
  const ORBIT_AXES=(()=>{
    const ay=Math.min(-SAFE_AREA.y0,SAFE_AREA.y1);
    return Object.freeze({ax:Math.min(-SAFE_AREA.x0,SAFE_AREA.x1,ay*ORBIT_ASPECT_MAX),ay});
  })();

  /* Ampleur et vitesse réglables par l'utilisateur (fenêtre « Affichage des
     étoiles », `JarvisSceneView`) : bornes du multiplicateur, le défaut étant 1.
     L'ampleur écarte ou resserre le champ autour du centre.

     Le plafond n'est plus arbitraire : à l'ampleur 1, une place admissible
     (`orbitFits`) tourne exactement dans la zone sûre ; au-delà, le tour déborde
     de la zone mais doit rester dans le **cadre**, qui est plus large. D'où
     `ORBIT_GAIN_MAX`, calculé et non choisi. Le réglage garde donc sa promesse :
     jamais un objet qui sort de l'écran en tournant. */
  const ORBIT_GAIN_MIN=.25;
  const ORBIT_GAIN_MAX=Math.round(Math.min(FRAME.halfWidth/ORBIT_AXES.ax,FRAME.halfHeight/ORBIT_AXES.ay)*10)/10;
  /* La vitesse, elle, n'a rien de géométrique : elle divise la période et ne
     peut faire sortir personne. Ses bornes restent celles du réglage. */
  const ORBIT_RATE_MIN=.25,ORBIT_RATE_MAX=4;

  /* Absent, nul ou illisible : la valeur de référence (1), jamais une orbite
     figée par accident. */
  function orbitFactor(value,lo,hi){
    const n=Number(value);
    return Number.isFinite(n)&&n>0?Math.min(hi,Math.max(lo,n)):1;
  }

  /* Étapes du tour, dont la page fait ses images-clés : `ORBIT_STEPS` points
     d'un cercle unité, de la droite vers le bas, puis la gauche, puis le haut —
     l'ordre horaire à l'écran, où `y` descend. `at` est la fraction de la
     période (en %), `angle` l'angle atteint (en degrés, de 0 à 360, strictement
     croissant), `x`/`y` le vecteur unité à multiplier par les deux rayons.

     Un tour en segments droits plutôt qu'en arcs : entre deux étapes le
     navigateur interpole linéairement, la corde raccourcit le rayon de
     `1 − cos(π/ORBIT_STEPS)`, soit un demi-pixel pour une étoile à 400 px du
     centre. Le pas est le même partout : la vitesse ne varie pas, et elle ne
     s'annule jamais — ce que faisait le pendule à chacun de ses deux extrêmes. */
  const ORBIT_STEPS=64;
  function orbitSteps(){
    const steps=[];
    for(let k=0;k<=ORBIT_STEPS;k++){
      const angle=2*Math.PI*k/ORBIT_STEPS;
      steps.push({at:Math.round(k/ORBIT_STEPS*1e4)/100,
        angle:Math.round(k/ORBIT_STEPS*36000)/100,
        x:Math.round(Math.cos(angle)*1e4)/1e4||0,
        y:Math.round(Math.sin(angle)*1e4)/1e4||0});
    }
    return steps;
  }

  /* Un nœud tourne-t-il ? Sa forme le permet, et son tour tient à l'écran
     (`node.still`, posé par `viewModel` avec `orbitOnScreen`). C'est l'unique
     prédicat : le champ, la piste, les fils et `placeOf` le lisent tous, donc un
     nœud immobilisé l'est partout à la fois (fils renoués, place lâchée gardée). */
  function orbitTurns(node){
    return !!node&&ORBIT_STILL_SHAPES.indexOf(node.shape)<0&&!node.still;
  }

  /* Une représentation tourne-t-elle ? La même règle que `orbitTurns`, lue sur
     la représentation **enregistrée** et non sur la forme dessinée : c'est
     elle que borne `orbitFits`, et une fenêtre rétrécie que la page dessine en
     capsule (`compactShape`) reste une fenêtre pour la scène. */
  function orbitTurnsRepresentation(representation){
    return ORBIT_STILL_SHAPES.indexOf(representation)<0;
  }

  /* **La place tient-elle sur son tour ?** Vrai quand la boîte `box` (unités),
     dessinée dans la représentation `representation`, reste entièrement dans la
     zone sûre tout au long de sa rotation à l'ampleur de référence.

     C'est la borne qui remplace le resserrement global : le résolveur ne
     propose que des places admissibles, `clampBox` y ramène celles de
     l'utilisateur, et le champ n'a donc plus rien à rattraper. Une forme qui ne
     tourne pas (fenêtre) n'est pas concernée : elle garde toute la zone sûre. */
  function orbitFits(box,representation){
    if(!orbitTurnsRepresentation(representation))return true;
    return orbitReach(box)<=orbitInset(box)+1e-9;
  }

  /* Rayon de la boîte dans le repère de l'ellipse (1 = son bord), et marge qui
     doit rester devant elle pour que sa **boîte entière** tienne où qu'elle
     arrive sur son tour. Deux fonctions séparées : `clampBox` a besoin de la
     seconde pour savoir jusqu'où ramener un centre. */
  function orbitReach(box){
    return Math.hypot((box.x+box.w/2)/ORBIT_AXES.ax,(box.y+box.h/2)/ORBIT_AXES.ay);
  }
  function orbitInset(box){
    return Math.max(0,Math.min(1-box.w/(2*ORBIT_AXES.ax),1-box.h/(2*ORBIT_AXES.ay)));
  }

  /* Le tour du champ pour ce rendu, ou `null` (rien à faire tourner).

     `cx`/`cy` : le centre, `ms` : la durée d'un tour, `ax`/`ay` : les demi-axes
     de la plus grande ellipse centrée qui tienne dans la zone sûre, `scale` :
     l'écartement voulu par l'utilisateur — et **rien d'autre**. Aucun de ces
     champs ne dépend de la place des objets : deux scènes différentes dans la
     même fenêtre, avec les mêmes réglages, ont exactement le même champ.

     Pourquoi une ellipse et non un cercle : l'écran est deux fois plus large
     que haut. Sur un cercle, le tour entier d'une étoile est borné par la
     hauteur — la moitié de la largeur reste vide, et le champ doit être
     resserré autour du visage pour que personne ne sorte par le haut. Sur une
     ellipse au format du cadre, chaque objet garde sa position relative dans le
     cadre tout au long du tour : le champ occupe l'écran, et rien n'en sort.
     C'est aussi ce à quoi ressemble un système en orbite vu de biais.

     `options` (facultatif) : `{gain, rate}`, l'ampleur et la vitesse voulues,
     1 par défaut. */
  /* Demi-axes de l'ellipse du champ en pixels pour la fenêtre `vp` : la plus
     grande ellipse centrée qui tienne dans la zone sûre. Ne dépend que de `vp`. */
  function orbitAxesPx(vp){
    const area=toScreen(vp,{x:SAFE_AREA.x0,y:SAFE_AREA.y0,w:SAFE_AREA.x1-SAFE_AREA.x0,h:SAFE_AREA.y1-SAFE_AREA.y0});
    const ay=Math.min(vp.cy-area.top,area.top+area.height-vp.cy);
    const ax=Math.min(vp.cx-area.left,area.left+area.width-vp.cx,ay*ORBIT_ASPECT_MAX);
    return ax>0&&ay>0?{ax,ay}:null;
  }

  /* **Le tour de ce nœud reste-t-il à l'écran ?** (reprise Slice 05, défaut
     D-S5-1). `orbitFits` borne les places que la page et le résolveur
     choisissent ; une place posée par un autre acteur (le cerveau par
     `scene_move` ou `scene_update_object`, un lot de Core borné à la seule zone
     sûre) peut ne pas la respecter, et son tour sortait alors de l'écran de
     quelques pixels. L'invariant « aucun objet ne sort de l'écran en tournant »
     tient donc **au rendu**, pour toute place : on mesure en pixels, avec la
     boîte dessinée `node.box` et l'ampleur `gain`, si l'ellipse de son centre
     plus sa demi-boîte tient dans la fenêtre. Sinon le nœud ne tourne pas — il
     reste dessiné à sa place, que Core garde dans la zone sûre, donc à l'écran.
     Immobiliser plutôt que resserrer son tour : un tour resserré ne passerait
     plus par sa place, et les fils du calque tournant se décrocheraient. */
  function orbitOnScreen(node,vp,gain){
    const axes=orbitAxesPx(vp);
    if(!axes||!node||!node.box)return true;
    const g=orbitFactor(gain,ORBIT_GAIN_MIN,ORBIT_GAIN_MAX);
    const reach=Math.hypot((node.cx-vp.cx)/axes.ax,(node.cy-vp.cy)/axes.ay);
    const rx=g*reach*axes.ax,ry=g*reach*axes.ay;
    /* Le rectangle **dessiné** (`drawnRect` : cible d'un point, hauteur d'une
       capsule), pris de part et d'autre du centre : il n'y est pas toujours
       centré (capsule compacte). */
    const rect=drawnRect(node);
    const slack=.5;
    return vp.cx-rx-(node.cx-rect.left)>=-slack&&vp.cx+rx+(rect.left+rect.width-node.cx)<=vp.width+slack
      &&vp.cy-ry-(node.cy-rect.top)>=-slack&&vp.cy+ry+(rect.top+rect.height-node.cy)<=vp.height+slack;
  }

  function orbitField(nodes,vp,options){
    const gain=orbitFactor(options&&options.gain,ORBIT_GAIN_MIN,ORBIT_GAIN_MAX);
    const rate=orbitFactor(options&&options.rate,ORBIT_RATE_MIN,ORBIT_RATE_MAX);
    const axes=orbitAxesPx(vp);
    if(!axes)return null;
    const {ax,ay}=axes;
    /* Reste à savoir s'il y a **quelque chose** à faire tourner : un champ posé
       sur une scène de fenêtres ferait tourner le calque des fils pour rien.
       C'est la seule lecture des nœuds, et elle ne produit qu'un booléen —
       aucune de leurs coordonnées n'entre dans le champ rendu. */
    let turning=false;
    for(const node of nodes||[]){
      if(!orbitTurns(node))continue;
      if(Math.hypot(node.cx-vp.cx,node.cy-vp.cy)>ORBIT_CENTER_PX){turning=true;break}
    }
    if(!turning)return null;
    return {cx:round1(vp.cx),cy:round1(vp.cy),ax:round1(ax),ay:round1(ay),
      ms:Math.round(ORBIT_PERIOD_MS/rate),scale:Math.round(gain*1000)/1000};
  }

  /* L'orbite d'un objet dans ce champ, ou `null` s'il n'en a pas (au centre, ou
     forme qui ne tourne pas) : les deux rayons de son ellipse, l'écart à sa
     place (que l'animation retranche, la place restant dans `transform`), et le
     décalage de phase qui le pose sur son propre point de l'ellipse. Même
     vitesse angulaire pour tous, une phase par objet : c'est exactement ce qui
     fait une rotation, et non un champ qui glisse d'un bloc. */
  function orbitTrack(node,field){
    if(!field||!orbitTurns(node))return null;
    const dx=node.cx-field.cx,dy=node.cy-field.cy;
    if(!(Math.hypot(dx,dy)>ORBIT_CENTER_PX))return null;
    const ux=dx/field.ax,uy=dy/field.ay,reach=Math.hypot(ux,uy);
    const turn=((Math.atan2(uy,ux)/(2*Math.PI))%1+1)%1;
    return {rx:round1(field.scale*reach*field.ax),ry:round1(field.scale*reach*field.ay),
      dx:round1(dx),dy:round1(dy),delayMs:-Math.round(turn*field.ms)};
  }

  /* Où le tour dessine la place `point`, à la fraction `turn` de la période :
     la carte que l'animation applique, en une fonction, pour que la page puisse
     la calculer sans relire le style. */
  function orbitTurnPoint(point,field,turn){
    if(!field)return {x:point.x,y:point.y};
    const ux=(point.x-field.cx)/field.ax,uy=(point.y-field.cy)/field.ay;
    const reach=Math.hypot(ux,uy);
    const angle=Math.atan2(uy,ux)+2*Math.PI*(((Number(turn)||0)%1+1)%1);
    return {x:round1(field.cx+field.scale*reach*field.ax*Math.cos(angle)),
      y:round1(field.cy+field.scale*reach*field.ay*Math.sin(angle))};
  }

  /* La place d'un point dessiné : l'inverse du tour, à la fraction `turn` de la
     période. C'est ce qui garde un objet lâché exactement sous le curseur —
     sans cela, il sauterait d'un demi-tour au relâchement, la place enregistrée
     étant relue par le tour au moment où il repart. */
  function orbitUnturn(point,field,turn){
    if(!field)return {x:point.x,y:point.y};
    const angle=-2*Math.PI*(((Number(turn)||0)%1+1)%1);
    const ux=(point.x-field.cx)/field.ax,uy=(point.y-field.cy)/field.ay;
    const cos=Math.cos(angle),sin=Math.sin(angle);
    return {x:round1(field.cx+(ux*cos-uy*sin)/field.scale*field.ax),
      y:round1(field.cy+(ux*sin+uy*cos)/field.scale*field.ay)};
  }

  /* Anneaux animés au plus (coût de style) : signaux vivants urgents d'abord,
     puis étoiles en cours, dans l'ordre de Core ; les autres restent fixes.
     La page ne propose que les nœuds dont l'état vient de changer
     (`options.animatable`) : au repos, aucune animation ne tourne. */
  const MAX_ANIMATED=24;

  /* ----------------------------------------------------------- AutoResolver */

  function sizeFor(item){
    if(item.representation==='window')return DEFAULT_SIZE.window;
    if(item.representation==='capsule')return DEFAULT_SIZE.capsule;
    return item.kind==='attention'?DEFAULT_SIZE.signal:DEFAULT_SIZE.point;
  }

  function workKey(ref){return ref&&typeof ref.source==='string'?`${ref.source}\n${ref.external_id}`:null}

  /* Ancre de chaque objet (`identifiant → {to, kind}`) : le signal près de son
     étoile (lien vivant, sinon même travail Core), l'enfant près de son parent
     (`parent_of`), un résultat près de ce qu'il explique. Première relation
     dans l'ordre de Core. */
  function anchorsOf(state){
    const anchors=new Map();
    const set=(from,to,kind)=>{if(from!==to&&!anchors.has(from))anchors.set(from,{to,kind})};
    const relations=[...state.relations.values()];
    for(const rel of relations)if(rel.kind==='explains'&&rel.relation_id===rel.from_id)set(rel.from_id,rel.to_id,'signal');
    const stars=new Map();
    for(const item of state.objects.values()){
      const key=(item.kind==='agent'||item.kind==='job')?workKey(item.work_ref):null;
      if(key&&!stars.has(key))stars.set(key,item.object_id);
    }
    for(const item of state.objects.values()){
      if(item.kind!=='attention')continue;
      const star=stars.get(workKey(item.work_ref));
      if(star!==undefined)set(item.object_id,star,'signal');
    }
    for(const rel of relations)if(rel.kind==='parent_of')set(rel.to_id,rel.from_id,'child');
    for(const rel of relations)if(rel.kind==='explains')set(rel.from_id,rel.to_id,'explains');
    return anchors;
  }

  /* Profondeur dans la chaîne d'ancres, cycles tolérés (`parent_of` n'est pas
     validé : une boucle s'arrête au premier identifiant déjà vu). */
  function depthOf(anchors,objectId){
    let depth=0,current=objectId;
    const seen=new Set([objectId]);
    while(depth<64){
      const next=anchors.get(current);
      if(next===undefined||seen.has(next.to))break;
      seen.add(next.to);depth++;current=next.to;
    }
    return depth;
  }

  const CELL=16;

  /* Grille spatiale : les requêtes de chevauchement ne lisent que les cellules
     touchées. */
  function createGrid(){
    const cells=new Map();let stamp=0;
    const keys=(b,visit)=>{
      const cx0=Math.floor(b.x/CELL),cx1=Math.floor((b.x+b.w)/CELL),cy0=Math.floor(b.y/CELL),cy1=Math.floor((b.y+b.h)/CELL);
      if((cx1-cx0+1)*(cy1-cy0+1)>4096)return visit('*');
      for(let cx=cx0;cx<=cx1;cx++)for(let cy=cy0;cy<=cy1;cy++)visit(`${cx},${cy}`);
    };
    return {
      add(box,layer){
        const entry={box,layer,mark:0};
        keys(box,key=>{let list=cells.get(key);if(!list){list=[];cells.set(key,list)}list.push(entry)});
      },
      /* Rend [aire même couche, aire autres couches, comparaisons]. */
      overlap(box,layer){
        stamp++;let same=0,other=0,work=0;
        const visit=key=>{
          const list=cells.get(key);if(!list)return;
          for(const entry of list){
            if(entry.mark===stamp)continue;
            entry.mark=stamp;work++;
            const area=overlapArea(box,entry.box);
            if(area>0){if(entry.layer===layer)same+=area;else other+=area}
          }
        };
        keys(box,visit);visit('*');
        return [same,other,work];
      },
    };
  }

  function overlapArea(a,b){
    const w=Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x),h=Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y);
    return w>0&&h>0?w*h:0;
  }

  const inSafeArea=b=>b.x>=SAFE_AREA.x0&&b.y>=SAFE_AREA.y0&&b.x+b.w<=SAFE_AREA.x1&&b.y+b.h<=SAFE_AREA.y1;
  const faceBox={x:FACE_ZONE.x0,y:FACE_ZONE.y0,w:FACE_ZONE.x1-FACE_ZONE.x0,h:FACE_ZONE.y1-FACE_ZONE.y0};

  /* Angles préférés (degrés) autour d'une ancre. */
  const SIGNAL_ANGLES=[-45,-90,0,-135,45,180,135,90];
  const CHILD_ANGLES=[90,60,120,30,150,0,180,-30,-150,-60,-120,-90];
  const EXPLAIN_ANGLES=[0,-30,30,180,-60,60,150,-150,90,-90];

  function ringCandidates(anchorBox,size,kind){
    const acx=anchorBox.x+anchorBox.w/2,acy=anchorBox.y+anchorBox.h/2;
    const reach=Math.max(anchorBox.w,anchorBox.h)/2+Math.max(size.w,size.h)/2;
    const angles=kind==='signal'?SIGNAL_ANGLES:kind==='child'?CHILD_ANGLES:EXPLAIN_ANGLES;
    /* Un signal se pose contre son étoile, comme une marque (autre couche). */
    const gap=kind==='signal'?-1:6;
    const out=[];
    for(let ring=0;ring<5;ring++){
      const radius=reach+gap+ring*(Math.max(size.w,size.h)+4);
      for(const deg of angles){
        const a=deg*Math.PI/180;
        out.push({x:Math.round(acx+Math.cos(a)*radius-size.w/2),y:Math.round(acy+Math.sin(a)*radius-size.h/2),w:size.w,h:size.h});
      }
    }
    return out;
  }

  /* Points d'origine des objets sans ancre : les étoiles **autour du visage**
     (origine au centre, comme le soleil qu'elles entourent : les candidats
     s'ouvrent en couronne, haut, droite, bas, gauche, et non plus en tas d'un
     seul côté), les résultats et fenêtres à droite, les groupes au centre.
     Les premiers anneaux tombent tous sur le visage : ils ne sont jamais
     libres, et la première étoile se pose donc juste au-dehors. */
  function homeOf(item){
    if(item.kind==='agent'||item.kind==='job'||item.kind==='attention')return {x:0,y:0};
    if(item.kind==='group')return {x:0,y:0};
    return {x:72,y:0};
  }

  /* Spirale carrée sur un réseau, anneau par anneau du plus proche au plus
     loin de l'origine, dans la zone sûre, au plus `MAX_ROOT_CANDIDATES` boîtes
     par réseau. Les étoiles essaient d'abord un réseau espacé (constellation
     lisible, place pour enfants et signaux), puis un réseau serré quand la
     scène se remplit ; les formes plus grandes n'ont que le réseau serré. */
  /* Écartement du réseau des étoiles. Il vaut **l'écartement de la
     constellation** : depuis que le champ ne resserre ni n'écarte plus rien au
     rendu (`orbitField`), ce qui est enregistré est ce qui se voit. Le réseau
     large répond donc directement au retour du 19/09/2026 (« les points sont
     trop proches du centre ») — l'écart est dans la place, pas dans une
     correction d'affichage qui déplaçait toute la scène au moindre changement.
     Le réseau serré reste la réserve quand la scène se remplit. */
  const STAR_LATTICE_GAPS=Object.freeze([18,2]);

  function rootCandidates(home,size){
    const gaps=size.w<=8?STAR_LATTICE_GAPS:[2];
    const out=[];
    for(const gap of gaps){
      const stepX=size.w+gap,stepY=size.h+gap;let count=0;
      const maxRing=Math.ceil(Math.max((SAFE_AREA.x1-SAFE_AREA.x0)/stepX,(SAFE_AREA.y1-SAFE_AREA.y0)/stepY));
      for(let ring=0;ring<=maxRing&&count<MAX_ROOT_CANDIDATES;ring++){
        const cells=[];
        const push=(i,j)=>{
          const box={x:Math.round(home.x+i*stepX-size.w/2),y:Math.round(home.y+j*stepY-size.h/2),w:size.w,h:size.h};
          /* `j === 0` ramené au zéro positif : `atan2(-0, -3)` vaut -π et
             mettrait la gauche avant le haut à distance égale. La couronne
             commence donc en haut, puis tourne (droite, bas, gauche). */
          if(inSafeArea(box))cells.push({box,d:Math.hypot(i*stepX,j*stepY),a:Math.atan2(j===0?0:j,i)});
        };
        if(ring===0)push(0,0);
        for(let k=-ring;k<ring;k++){push(k,-ring);push(ring,k);push(-k,ring);push(-ring,-k)}
        cells.sort((p,q)=>p.d-q.d||p.a-q.a);
        for(const cell of cells){if(count>=MAX_ROOT_CANDIDATES)break;out.push(cell.box);count++}
      }
    }
    return out;
  }

  /* Placer tout ce qui n'a pas de géométrie. Rend `{placements, resolved,
     work}` : `placements` (identifiant → boîte en unités) couvre tous les
     objets visibles, `resolved` liste dans l'ordre les objets posés par cette
     passe (à valider auprès de Core), `work` le nombre de comparaisons. Un
     objet caché n'est ni placé ni obstacle : il le sera quand il reparaîtra.

     Travail borné : les candidats d'une même origine et d'une même taille sont
     calculés une fois, et un curseur par (origine, taille, couche) saute ceux
     déjà reconnus non libres (l'occupation ne fait que croître pendant la
     passe), sauf quand plus rien n'est libre : tout est relu au moindre coût ;
     au-delà de `WORK_BUDGET` comparaisons, chaque objet restant prend son
     premier candidat admissible. */
  function resolveLayout(state){
    const placements=new Map(),resolved=[];
    const grid=createGrid();
    const order=new Map();let index=0;
    for(const item of state.objects.values()){
      order.set(item.object_id,index++);
      if(item.visibility!=='visible'||!item.geometry)continue;
      const g=item.geometry,box={x:g.x,y:g.y,w:g.w,h:g.h};
      placements.set(item.object_id,box);grid.add(box,item.layer);
    }
    const anchors=anchorsOf(state);
    const pending=[...state.objects.values()].filter(item=>item.visibility==='visible'&&!item.geometry);
    const depth=new Map(pending.map(item=>[item.object_id,depthOf(anchors,item.object_id)]));
    pending.sort((a,b)=>depth.get(a.object_id)-depth.get(b.object_id)||order.get(a.object_id)-order.get(b.object_id));
    const roots=new Map(),cursors=new Map(),turnFull=new Set();
    let work=0;
    /* Premier candidat libre (aucun chevauchement, hors visage), sinon le moins
       coûteux ; `sameLayerOnly` : refuser tout chevauchement de même couche ;
       `firstFit` : prendre le premier sans chevauchement de même couche (un
       signal peut recouvrir une étoile voisine, pas un autre signal).
       Rend {box, index, free} ou null. */
    const pick=(candidates,start,layer,sameLayerOnly,firstFit,fits)=>{
      let best=null;
      for(let i=start;i<candidates.length;i++){
        const box=candidates[i];
        if(!fits(box))continue;
        if(work>WORK_BUDGET)return {box,index:i,free:false,cost:Infinity};
        const [same,other,count]=grid.overlap({x:box.x-1,y:box.y-1,w:box.w+2,h:box.h+2},layer);
        work+=count+1;
        const face=overlapArea(box,faceBox);
        if(same===0&&other===0&&face===0)return {box,index:i,free:true};
        if(firstFit&&same===0)return {box,index:i,free:false,cost:0};
        const cost=same*1000+other*4+face*8;
        if((!sameLayerOnly||same===0)&&(!best||cost<best.cost))best={box,index:i,free:false,cost};
      }
      return best;
    };
    for(const item of pending){
      const size=sizeFor(item);
      const anchor=anchors.get(item.object_id);
      const anchorBox=anchor===undefined?undefined:placements.get(anchor.to);
      /* Une place **préférée** tient dans la zone sûre et sur son tour ; une
         place simplement admissible tient dans la zone sûre. La borne du tour
         se préfère, elle ne s'impose pas — exactement comme le visage, que le
         résolveur évite sans se l'interdire.

         En faire un filtre dur serait pire que le mal qu'elle corrige :
         l'ellipse du tour couvre la moitié de la zone sûre, et une scène pleine
         (512 objets) n'y tient pas. Le résolveur empilerait les étoiles dedans
         au lieu de les étaler dehors. Une étoile posée hors de l'ellipse
         balaiera les bords de la zone sûre en tournant — c'est cosmétique, et
         sans commune mesure avec un tas d'étoiles superposées. Ce qui compte
         est que **plus rien ne resserre le champ** : le débordement reste le
         problème de cet objet-là, et de lui seul. */
      const turnFits=box=>inSafeArea(box)&&orbitFits(box,item.representation);
      /* Une place libre sur son tour d'abord ; sinon le choix d'avant, dans
         toute la zone sûre — libre si possible, au moindre coût sinon. Une
         superposition coûte plus qu'un tour qui déborde. */
      const best=(candidates,start,sameLayerOnly,firstFit,fullKey)=>{
        /* Même raisonnement que le curseur : l'occupation ne fait que croître
           pendant la passe, donc une ellipse trouvée pleine pour ces candidats
           le reste. Sans cette mémoire, chaque objet d'une scène pleine
           relisait toute l'ellipse pour rien, et la passe épuisait
           `WORK_BUDGET` — au-delà duquel les objets restants prennent leur
           premier candidat, superpositions comprises. */
        if(!fullKey||!turnFull.has(fullKey)){
          const tight=pick(candidates,start,item.layer,sameLayerOnly,firstFit,turnFits);
          if(tight&&tight.free)return tight;
          if(fullKey)turnFull.add(fullKey);
        }
        return pick(candidates,start,item.layer,sameLayerOnly,firstFit,inSafeArea);
      };
      let chosen=null;
      if(anchorBox){
        const near=best(ringCandidates(anchorBox,size,anchor.kind),0,true,anchor.kind==='signal');
        if(near)chosen=near.box;
      }
      if(!chosen){
        const home=homeOf(item),key=`${home.x},${home.y},${size.w},${size.h}`,cursorKey=`${key},${item.layer}`;
        if(!roots.has(key))roots.set(key,rootCandidates(home,size));
        const candidates=roots.get(key),start=cursors.get(cursorKey)||0;
        const fullKey=`${cursorKey},${item.representation}`;
        let far=best(candidates,start,false,false,fullKey);
        if(far&&far.free)cursors.set(cursorKey,far.index+1);
        /* Plus de place libre après le curseur : les candidats sautés (visage,
           autre couche) redeviennent des choix, au moindre coût. */
        else if(start>0){const again=best(candidates,0,false,false,fullKey);if(again&&(!far||again.cost<far.cost))far=again}
        chosen=far?far.box:{x:Math.round(home.x-size.w/2),y:Math.round(home.y-size.h/2),w:size.w,h:size.h};
      }
      placements.set(item.object_id,chosen);grid.add(chosen,item.layer);resolved.push(item.object_id);
    }
    return {placements,resolved,work};
  }

  /* ---------------------------------------------------------- modèle de vue */

  const MAX_Z_LAYER=1000,ORDER_SPAN=1000000;

  /* Ordre d'empilement dans le conteneur de scène uniquement : couche, puis
     ordre, puis ordre de Core (ordre du DOM). Toujours > 0, < 2^31. */
  function stackOf(layer,order){
    const l=Math.max(0,Math.min(MAX_Z_LAYER,Number(layer)||0)),o=Math.max(-ORDER_SPAN,Math.min(ORDER_SPAN,Number(order)||0));
    return l*(2*ORDER_SPAN+1)+(o+ORDER_SPAN)+1;
  }

  /* Ce que la page dessine pour `state` dans la fenêtre `vp`. Rend
     `{nodes, edges, capacity, offscreen, hidden}` ; `nodes` dans l'ordre de
     Core, sans objet caché. */
  function viewModel(state,layout,vp,options){
    const limit=options&&Number.isInteger(options.objectLimit)?options.objectLimit:OBJECT_LIMIT;
    const errorLabels=options&&options.errorLabels||null;
    const animatable=options&&typeof options.animatable==='function'?options.animatable:()=>true;
    const nodes=[],centers=new Map();let offscreen=0,hidden=0;
    const explains=explainsIndex(state);
    for(const item of state.objects.values()){
      if(item.visibility!=='visible'){hidden++;continue}
      const stored=layout.placements.get(item.object_id);
      if(!stored)continue;
      const representation=['point','capsule','window'].includes(item.representation)?item.representation:'point';
      const screen=toScreen(vp,drawnBox(representation,stored));
      const payload=item.payload||{};
      const title=displayTitle(item,cleanLine(payload.title,160),errorLabels);
      /* Un titre écrit en markdown (`**Rapport**`) se dessine, il ne s'épelle
         pas : `titleSpans` porte les marques, `title` reste le texte nu que
         lisent le nom accessible, l'infobulle et `label`. */
      const titleSpans=markdownSpans(title||KIND_LABELS[item.kind]||item.kind);
      const exec=EXEC_LABELS[item.exec_state]!==undefined?item.exec_state:'unknown';
      const signal=item.kind==='attention';
      const urgency=signal?signalUrgency(state,item):'none';
      const shape=compactShape(representation,screen);
      const artifact=item.kind==='artifact';
      const count=Array.isArray(payload.items)?Math.min(payload.items.length,32):0;
      const node={
        id:item.object_id,kind:item.kind,representation,shape,compact:shape!==representation,
        category:cleanLine(item.category,32),tone:toneOf(item.category),
        exec,execLabel:execLabelOf(item,exec),restartUnknown:restartUnknown(item),signal,live:signal&&urgency!=='none',urgency,animate:false,
        alerted:false,
        pinned:!!(item.constraints&&item.constraints.pinned_by_user),
        placedBy:item.geometry?String(item.constraints&&item.constraints.placed_by||''):'resolver',
        committed:!!item.geometry,
        stack:stackOf(item.layer,item.order),
        box:screen,cx:round1(screen.left+screen.width/2),cy:round1(screen.top+screen.height/2),
        title:titleSpans.map(span=>span.text).join(''),titleSpans,
        summary:shape==='window'?cleanText(payload.summary,2000):'',
        items:shape==='window'?itemsOf(payload):[],
        itemCount:count,
        explains:artifact?explainedTarget(state,item.object_id,errorLabels,explains):null,
      };
      node.label=artifact
        ?[node.title,KIND_LABELS.artifact,node.category,count?`${count} ${count>1?'entrées':'entrée'}`:'',
          node.explains?`explique « ${node.explains.title} »`:'',node.pinned?'épinglé':''].filter(Boolean).join(' · ')
        :[node.title,KIND_LABELS[item.kind]||item.kind,node.execLabel,signal&&!node.live?'retiré':'',node.pinned?'épinglé':''].filter(Boolean).join(' · ');
      /* Une forme qui tourne mais dont le tour sortirait de l'écran reste immobile
         (`orbitOnScreen`) ; l'ampleur voulue arrive par `options.orbitGain`. */
      if(ORBIT_STILL_SHAPES.indexOf(shape)<0&&!orbitOnScreen(node,vp,options&&options.orbitGain))node.still=true;
      const outside=screen.left+screen.width<0||screen.top+screen.height<0||screen.left>vp.width||screen.top>vp.height;
      if(outside)offscreen++;
      nodes.push(node);centers.set(node.id,node);
    }
    /* Un signal du runtime s'empile avec son étoile (juste au-dessus d'elle) :
       une fenêtre qui recouvre l'étoile recouvre aussi son signal. Les objets
       `attention` du cerveau ou de l'utilisateur gardent leur couche
       (Décision 8). */
    const anchors=anchorsOf(state);
    for(const node of nodes){
      if(!node.signal)continue;
      const anchor=anchors.get(node.id);
      const star=anchor&&anchor.kind==='signal'?centers.get(anchor.to):null;
      if(!star)continue;
      /* Signal vivant (de qui que ce soit) : son étoile le sait. La page en
         retire d'un cran la marque de fin, qui ne se bat pas avec l'alerte. */
      if(node.live)star.alerted=true;
      if(state.objects.get(node.id).origin==='runtime')node.stack=star.stack+1;
    }
    /* Signaux vivants urgents recouverts par une fenêtre dessinée au-dessus
       d'eux : comptés pour l'indicateur (test de rectangles, à chaque rendu). */
    const coveredSignals={high:0,medium:0};
    const windows=nodes.filter(n=>n.shape==='window');
    for(const node of nodes){
      if(node.urgency!=='high'&&node.urgency!=='medium')continue;
      if(state.objects.get(node.id).origin!=='runtime')continue;
      const covered=windows.some(w=>w.stack>node.stack&&node.cx>=w.box.left&&node.cx<=w.box.left+w.box.width&&node.cy>=w.box.top&&node.cy<=w.box.top+w.box.height);
      if(covered)coveredSignals[node.urgency]++;
    }
    /* Borne des animations : urgence haute, moyenne, puis exécution en cours. */
    let budget=MAX_ANIMATED;
    for(const pass of [n=>n.urgency==='high',n=>n.urgency==='medium',n=>!n.signal&&n.exec==='running']){
      for(const node of nodes){if(budget<=0)break;if(!node.animate&&pass(node)&&animatable(node)){node.animate=true;budget--}}
    }
    const edges=[];
    for(const rel of state.relations.values()){
      const a=centers.get(rel.from_id),b=centers.get(rel.to_id);
      if(!a||!b)continue;
      const signalEdge=rel.kind==='explains'&&rel.relation_id===rel.from_id;
      edges.push({id:rel.relation_id,kind:rel.kind,layer:Number(rel.layer)||0,
        signal:signalEdge,artifact:!signalEdge&&rel.kind==='explains'&&a.kind==='artifact',tone:a.tone,
        /* Extrémités nommées : la page y noue le fil pendant un geste, et les
           retrouve pour lire l'ancre vivante des deux nœuds qu'il joint. */
        from:a.id,to:b.id,x1:a.cx,y1:a.cy,x2:b.cx,y2:b.cy,
        /* **Qui tourne à chaque bout** (21/09/2026). Le calque des fils tourne
           d'un bloc : une rotation envoie le segment qui joint deux étoiles sur
           celui qui joint leurs nouvelles places — mais seulement si les deux
           bouts tournent. Un fil qui touche une fenêtre, elle immobile, ne peut
           pas être porté par ce calque : une seule transformation ne peut pas
           suivre un bout mobile et laisser l'autre en place. La page lit donc
           ces deux drapeaux pour ranger le fil dans le calque qui tourne (les
           deux bouts tournent), dans le calque immobile (aucun), ou dans ceux
           qu'elle renoue elle-même image par image (un seul). */
        fromTurns:orbitTurns(a),toTurns:orbitTurns(b)});
    }
    edges.sort((p,q)=>p.layer-q.layer);
    const objects=state.objects.size;
    return {nodes,edges,hidden,offscreen,coveredSignals,capacity:{objects,limit,saturated:objects>=limit}};
  }

  /* Place d'un objet que la page agrandit (menu « Afficher en fenêtre / en
     capsule », Slice 07 reprise QA) : la recherche d'espace libre de
     l'AutoResolver, ancrée près de ce que l'objet explique (ou de son parent,
     de son étoile), dans la zone sûre, en évitant le visage. Tous les autres
     objets gardent leur boîte dessinée (`layout`) comme obstacles. Rend une
     boîte en unités ou `null`. Un glissement ou une géométrie du cerveau
     restent autoritaires : cette aide ne sert qu'au changement de forme. */
  /* Pas de la recherche d'espace libre de `placeFor` (unités de scène). */
  const PLACE_STEP=2;

  /* Boîte libre de taille `size` la plus proche de (acx, acy), ou null.
     Occupation de la zone sûre en cellules de `PLACE_STEP` : chaque obstacle
     (boîte dessinée, élargie d'une unité) et le visage marquent les cellules
     qu'ils touchent (marquage prudent : jamais un faux « libre ») ; une somme
     cumulée 2D rend chaque test de boîte en temps constant. Candidats alignés
     sur la grille, du plus proche au plus lointain (distance, y, x) : ordre
     total, résultat déterministe ; travail borné par la taille de la zone sûre
     (≈ 10 000 cellules), quel que soit le nombre d'objets. */
  function freeBoxNearest(layout,objectId,size,acx,acy){
    const cols=Math.floor((SAFE_AREA.x1-SAFE_AREA.x0)/PLACE_STEP),rows=Math.floor((SAFE_AREA.y1-SAFE_AREA.y0)/PLACE_STEP);
    const occupied=new Uint8Array(cols*rows);
    const mark=(bx,by,bw,bh)=>{
      const c0=Math.max(0,Math.floor((bx-SAFE_AREA.x0)/PLACE_STEP)),c1=Math.min(cols,Math.ceil((bx+bw-SAFE_AREA.x0)/PLACE_STEP));
      const r0=Math.max(0,Math.floor((by-SAFE_AREA.y0)/PLACE_STEP)),r1=Math.min(rows,Math.ceil((by+bh-SAFE_AREA.y0)/PLACE_STEP));
      for(let r=r0;r<r1;r++)occupied.fill(1,r*cols+c0,r*cols+Math.max(c0,c1));
    };
    for(const [id,box] of layout.placements)if(id!==objectId)mark(box.x-1,box.y-1,box.w+2,box.h+2);
    mark(faceBox.x,faceBox.y,faceBox.w,faceBox.h);
    const sums=new Int32Array((cols+1)*(rows+1));
    for(let r=0;r<rows;r++){
      let line=0;
      for(let c=0;c<cols;c++){line+=occupied[r*cols+c];sums[(r+1)*(cols+1)+c+1]=sums[r*(cols+1)+c+1]+line}
    }
    const wc=Math.ceil(size.w/PLACE_STEP),hc=Math.ceil(size.h/PLACE_STEP);
    let best=null;
    for(let r=0;r+hc<=rows;r++){
      for(let c=0;c+wc<=cols;c++){
        const x=SAFE_AREA.x0+c*PLACE_STEP,y=SAFE_AREA.y0+r*PLACE_STEP;
        const dx=x+size.w/2-acx,dy=y+size.h/2-acy,d=dx*dx+dy*dy;
        if(best&&(d>best[0]||(d===best[0]&&(y>best[1]||(y===best[1]&&x>=best[2])))))continue;
        const used=sums[(r+hc)*(cols+1)+c+wc]-sums[r*(cols+1)+c+wc]-sums[(r+hc)*(cols+1)+c]+sums[r*(cols+1)+c];
        if(used===0)best=[d,y,x];
      }
    }
    return best?{x:best[2],y:best[1],w:size.w,h:size.h}:null;
  }

  function placeFor(state,layout,objectId,representation){
    const current=state.objects.get(objectId);
    if(!current)return null;
    /* Balayage de toute la zone sûre au pas de 2 unités (≈ 5 700 boîtes pour
       une fenêtre, grille spatiale des obstacles) : la boîte **libre** (aucun
       objet visible à 1 unité près, pas le visage) dont le centre est le plus
       proche de l'ancre (ce que l'objet explique, son parent ou son étoile ;
       sans ancre, sa place actuelle). Égalité : plus haut, puis plus à gauche.
       Déterministe et borné ; seulement si aucune boîte n'est libre, la
       recherche du résolveur au moindre recouvrement (reprise QA N2 : un
       anneau fini d'angles pouvait rater 525 places libres). */
    const anchor=anchorsOf(state).get(objectId);
    const anchorBox=(anchor&&layout?layout.placements.get(anchor.to):null)||(layout?layout.placements.get(objectId):null);
    if(anchorBox){
      const size=sizeFor({kind:current.kind,representation});
      const free=freeBoxNearest(layout,objectId,size,anchorBox.x+anchorBox.w/2,anchorBox.y+anchorBox.h/2);
      if(free)return free;
    }
    const objects=new Map();
    for(const [id,item] of state.objects){
      if(id===objectId){objects.set(id,Object.assign({},item,{representation,geometry:null,visibility:'visible'}));continue}
      const box=layout&&layout.placements.get(id);
      objects.set(id,box?Object.assign({},item,{geometry:{x:box.x,y:box.y,w:box.w,h:box.h}}):item);
    }
    const probe=resolveLayout(Object.assign({},state,{objects}));
    const box=probe.placements.get(objectId);
    return box?{x:box.x,y:box.y,w:box.w,h:box.h}:null;
  }

  /* Forme dessinée pour une boîte à l'écran : la représentation, ou plus
     compacte quand son texte n'y serait pas lisible. */
  function compactShape(representation,screen){
    let shape=representation;
    if(shape==='window'&&(screen.width<READABLE.windowWidth||screen.height<READABLE.windowHeight))shape='capsule';
    if(shape==='capsule'&&screen.width<READABLE.capsuleWidth)shape='point';
    return shape;
  }

  /* ------------------------------------------------ navigation au clavier */

  /* Ordre de lecture spatial (bandes de 24 px de haut en bas, puis de gauche
     à droite) : premier arrêt de tabulation, Début et Fin. */
  function spatialOrder(nodes){
    return [...nodes].sort((a,b)=>Math.floor(a.cy/24)-Math.floor(b.cy/24)||a.cx-b.cx||(a.id<b.id?-1:a.id>b.id?1:0));
  }

  /* Nœud suivant pour une touche : une flèche mène au plus proche dans sa
     direction (écart transversal pénalisé), Début / Fin au premier / dernier
     de l'ordre spatial. Rend un identifiant (`currentId` s'il n'y a rien). */
  function nextFocus(nodes,currentId,key){
    if(!nodes.length)return null;
    const ordered=spatialOrder(nodes);
    if(key==='Home')return ordered[0].id;
    if(key==='End')return ordered[ordered.length-1].id;
    const current=nodes.find(n=>n.id===currentId);
    if(!current)return ordered[0].id;
    const dirs={ArrowRight:[1,0],ArrowLeft:[-1,0],ArrowDown:[0,1],ArrowUp:[0,-1]};
    const dir=dirs[key];
    if(!dir)return currentId;
    let best=null,bestScore=Infinity;
    for(const node of nodes){
      if(node.id===current.id)continue;
      const dx=node.cx-current.cx,dy=node.cy-current.cy;
      const along=dx*dir[0]+dy*dir[1],across=Math.abs(dx*dir[1])+Math.abs(dy*dir[0]);
      if(along<=0)continue;
      const score=along+2*across;
      if(score<bestScore||(score===bestScore&&node.id<best.id)){best=node;bestScore=score}
    }
    return best?best.id:currentId;
  }

  /* ------------------------------------------- validation des placements */

  const COMMIT_MAX_ATTEMPTS=3;

  const commitKey=(state,objectId)=>`${state.scene_id}\n${objectId}`;

  /* Commande `set_geometry` (`placed_by = resolver`) pour une boîte posée. */
  function commitCommand(objectId,box){
    return {schema_version:1,op:'set_geometry',object_id:objectId,
      geometry:{x:box.x,y:box.y,w:box.w,h:box.h},placed_by:'resolver'};
  }

  /* Prochains objets à valider, dans l'ordre de la passe : toujours sans
     géométrie dans l'état tenu, visibles, jamais validés ni en cours, et dont
     le délai de nouvel essai est passé. */
  function commitCandidates(state,layout,ledger,now){
    const out=[];
    for(const objectId of layout.resolved){
      const item=state.objects.get(objectId);
      if(!item||item.geometry||item.visibility!=='visible')continue;
      const entry=ledger.get(commitKey(state,objectId));
      if(entry&&(entry.status!=='retry'||entry.retryAt>now))continue;
      const box=layout.placements.get(objectId);
      if(box)out.push({objectId,key:commitKey(state,objectId),command:commitCommand(objectId,box)});
    }
    return out;
  }

  /* Plus proche délai de nouvel essai encore à venir (> `now`), ou null. Un
     délai passé dont l'objet n'est plus candidat n'est jamais replanifié. */
  function nextRetryAt(ledger,now){
    let next=null;
    for(const entry of ledger.values())
      if(entry.status==='retry'&&entry.retryAt>now&&(next===null||entry.retryAt<next))next=entry.retryAt;
    return next;
  }

  /* Lire la réponse de `POST /api/scene/commands`. `done` : ne plus jamais
     renvoyer (appliqué, doublon, refus du domaine, erreur de forme) ; `retry` :
     rien n'a été appliqué ou l'issue est inconnue, renvoyer la même boîte est
     sûr (même géométrie → `duplicate`, objet placé entre-temps →
     `explicit_placement`). */
  function classifyCommit(status,body){
    if(status===200&&body&&typeof body.outcome==='string')
      return {settle:'done',outcome:body.outcome,reason:body.reason||''};
    const code=body&&body.error&&typeof body.error.code==='string'?body.error.code:`http_${status}`;
    if(status===503||status===504||status===0)return {settle:'retry',outcome:'not_confirmed',reason:code};
    return {settle:'done',outcome:'failed',reason:code};
  }

  /* Noter l'issue d'une validation. Rend l'entrée. Un nouvel essai attend
     2 s, 8 s puis abandonne après `COMMIT_MAX_ATTEMPTS` envois. */
  function settleCommit(ledger,key,verdict,now){
    const previous=ledger.get(key)||{attempts:0};
    const attempts=previous.attempts+1;
    const retry=verdict.settle==='retry'&&attempts<COMMIT_MAX_ATTEMPTS;
    const entry={status:retry?'retry':'done',attempts,outcome:retry?verdict.outcome:(verdict.settle==='retry'?'gave_up':verdict.outcome),
      reason:verdict.reason||'',retryAt:retry?now+2000*Math.pow(4,attempts-1):null};
    ledger.set(key,entry);
    if(ledger.size>2048){for(const k of ledger.keys()){if(ledger.size<=2048)break;if(k!==key)ledger.delete(k)}}
    return entry;
  }

  const api=Object.freeze({FRAME,SAFE_AREA,FACE_ZONE,OBJECT_LIMIT,DEFAULT_SIZE,WORK_BUDGET,COMMIT_MAX_ATTEMPTS,READABLE,MAX_ANIMATED,CAPSULE_MAX,drawnBox,
    RESTART_UNKNOWN_LABEL,restartUnknown,ARTIFACT_CATEGORIES,linkOf,explainedTarget,explainsIndex,artifactsExplaining,itemsOf,hostTail,isOrphanArtifact,orphanArtifacts,
    artifactsLeftOrphan,placeFor,linkHost,linkLength,POINT_HIT_PX,CAPSULE_MIN_HEIGHT_PX,drawnRect,ORBIT_STEPS,orbitSteps,orbitField,orbitTrack,orbitTurnPoint,orbitUnturn,orbitTurns,
    ORBIT_AXES,ORBIT_GAIN_MIN,ORBIT_GAIN_MAX,ORBIT_RATE_MIN,ORBIT_RATE_MAX,orbitFits,orbitReach,orbitInset,orbitTurnsRepresentation,orbitOnScreen,
    viewport,toScreen,cleanLine,cleanText,markdownSpans,markdownText,markdownBlocks,markdownLines,toneOf,isLiveSignal,signalUrgency,signalErrorClass,anchorsOf,depthOf,resolveLayout,
    stackOf,viewModel,compactShape,spatialOrder,nextFocus,commitKey,commitCommand,commitCandidates,nextRetryAt,classifyCommit,settleCommit});
  root.JarvisSceneLayout=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
