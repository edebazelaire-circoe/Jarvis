/* Primitives visuelles des Réglages (jarvis-settings-ui-reorganization, Slice 02).

   Contrat : `docs/settings/settings-shell.md`. Module pur (`window.JarvisSettingsUI`,
   `module.exports` pour node) : il fabrique des fragments HTML aux classes du shell
   (`.set-*`, styles dans `control_center.html`). Aucun DOM, réseau ni stockage ; il ne
   lit ni n'écrit aucun réglage, et ne porte aucune valeur de réglage.

   Règle d'échappement : tout paramètre TEXTE (titres, descriptions, libellés, aides)
   est échappé ici. Les paramètres nommés `body`, `control` et `items` sont du HTML que
   l'appelant a déjà construit (et échappé) : ils sont insérés tels quels.

   - `intro`    : tête d'une catégorie ou d'une page (titre + description) ;
   - `section`  : un groupe de réglages titré, badges éventuels (avancé, application) ;
   - `field`    : une ligne de champ (libellé lié au contrôle, aide liée par `aria-describedby`) ;
   - `badge`    : un état court, toujours avec un mot (jamais la couleur seule) ;
   - `notice`   : un message (info, ok, warn, bad), région vivante au besoin ;
   - `advanced` : une divulgation « avancé » (`<details>` natif) ;
   - `actions`  : une rangée de boutons, alignée sur la colonne des contrôles.

   Deux aides de focus (passe de finitions avant la Slice 10), les seules qui touchent au DOM, et seulement aux
   éléments qu'on leur donne :
   - `keepFocus(host, draw)` : `draw()` remplace le contenu de `host` ; l'élément qui avait le focus dans `host` est
     retrouvé dans le nouveau rendu (même `id`, sinon même premier attribut `data-*` et même valeur) et le reprend,
     sinon le focus tomberait sur `body`. Un élément retrouvé mais désactivé ne le reprend pas ;
   - `landFocus(el)` : porte le focus sur `el` après un saut (lien interne, élément créé par une action) et marque
     l'arrivée (`data-settings-landed`, retiré quand le focus repart) : le contour se voit aussi quand le saut a été
     cliqué à la souris, où `:focus-visible` ne s'applique pas.

   Fondation visuelle (refonte-ui-settings, Slice 01 ; contrat `docs/settings/visual-foundation.md`) : fragments
   des primitives partagées (`medallion`, `panel`, `stat`, `row`, `dot`, `button`, `select`, `range`, `toggle`,
   `textarea`, `tabs`, `choices`, `table`, `float`) et liaisons DOM qui ne touchent qu'aux éléments donnés et
   rendent leur détachement (`bindRange`, `bindCounter`, `bindToggle`, `wireTabs`, `openFloat`, `bindAll`). Ni
   valeur, ni plage, ni catalogue de réglage : tout vient de l'appelant. */
(function(root){
  'use strict';

  const esc=value=>String(value===undefined||value===null?'':value)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  const ID=/^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
  const idAttr=id=>{if(id===undefined||id===null||id==='')return '';if(!ID.test(String(id)))throw new Error(`JarvisSettingsUI : identifiant invalide « ${id} ».`);return String(id)};

  /* Le moment où un réglage prend effet, dans les mots de l'utilisateur. Les clés
     sont celles de `JarvisSettingsRegistry.APPLIES`. */
  const APPLIES_LABELS=Object.freeze({
    immediate:'Appliqué tout de suite',
    next_turn:'Au prochain tour',
    next_core_start:'Au prochain démarrage de Core',
    next_voice_start:'Au prochain démarrage de Voice',
  });
  const BADGE_KINDS=Object.freeze(['info','ok','warn','bad','advanced','restart']);
  const NOTICE_KINDS=Object.freeze(['info','ok','warn','bad']);

  function badge(kind,text){
    const k=BADGE_KINDS.includes(kind)?kind:'info';
    if(!String(text||'').trim())throw new Error('JarvisSettingsUI.badge : un badge porte toujours un mot.');
    return `<span class="set-badge set-badge-${k}">${esc(text)}</span>`;
  }
  function appliesBadge(applies){return APPLIES_LABELS[applies]?badge(applies==='immediate'?'info':'restart',APPLIES_LABELS[applies]):''}

  function intro({id,title,description,level=2}={}){
    const h=level===3?'h3':'h2',key=idAttr(id);
    return `<header class="set-intro"><${h} class="set-intro-title"${key?` id="${key}"`:''}>${esc(title)}</${h}>`
      +(description?`<p class="set-intro-desc">${esc(description)}</p>`:'')+'</header>';
  }

  function section({id,title,description,body='',advanced=false,applies,badges=''}={}){
    const key=idAttr(id),head=key?`${key}-title`:'';
    const marks=(advanced?badge('advanced','Avancé'):'')+appliesBadge(applies)+badges;
    return `<section class="set-section"${key?` id="${key}" aria-labelledby="${head}"`:''}>`
      +`<header class="set-section-head"><h3${head?` id="${head}"`:''}>${esc(title)}</h3>${marks?`<span class="set-section-marks">${marks}</span>`:''}</header>`
      +(description?`<p class="set-section-desc">${esc(description)}</p>`:'')
      +`<div class="set-section-body">${body}</div></section>`;
  }

  /* `control` doit porter `id="<id>"` et `aria-describedby="<id>-hint"` quand `hint` est donné. */
  function field({id,label,hint,control='',inline=false}={}){
    const key=idAttr(id);
    if(!key)throw new Error('JarvisSettingsUI.field : identifiant requis (libellé lié au contrôle).');
    return `<div class="set-field${inline?' set-field-inline':''}"><label class="set-field-label" for="${key}">${esc(label)}</label>`
      +`<div class="set-field-control">${control}</div>`
      +(hint?`<p class="set-field-hint" id="${key}-hint">${esc(hint)}</p>`:'')+'</div>';
  }

  /* `live` : 'polite' (role=status) ou 'assertive' (role=alert) ; omis = message statique. */
  function notice({kind='info',title,body='',text,live}={}){
    const k=NOTICE_KINDS.includes(kind)?kind:'info';
    const role=live==='assertive'?' role="alert"':live==='polite'?' role="status"':'';
    return `<div class="set-notice set-notice-${k}"${role}>`+(title?`<strong class="set-notice-title">${esc(title)}</strong>`:'')
      +(text?`<span class="set-notice-text">${esc(text)}</span>`:'')+body+'</div>';
  }

  function advanced({id,summary='Réglages avancés',body='',open=false}={}){
    const key=idAttr(id);
    return `<details class="set-advanced"${key?` id="${key}"`:''}${open?' open':''}><summary>${esc(summary)}</summary><div class="set-advanced-body">${body}</div></details>`;
  }

  function actions(items=''){return `<div class="set-actions">${items}</div>`}

  /* Sélecteur qui retrouve l'élément focalisé dans un rendu neuf de `host`, ou `null` (focus ailleurs, rien de
     stable pour le reconnaître). Les valeurs passent par `JSON.stringify` : une chaîne CSS valide, guillemets
     et barres obliques échappés. */
  function focusKey(host){
    const doc=host&&host.ownerDocument,active=doc&&doc.activeElement;
    if(!active||active===host||typeof host.contains!=='function'||!host.contains(active))return null;
    if(active.id)return `[id=${JSON.stringify(active.id)}]`;
    const attr=[...(active.attributes||[])].find(a=>a.name.startsWith('data-'));
    return attr?`[${attr.name}${attr.value?`=${JSON.stringify(attr.value)}`:''}]`:null;
  }
  function keepFocus(host,draw){
    const key=focusKey(host);
    const result=draw();
    if(key){
      const again=host.querySelector(key),doc=host.ownerDocument;
      if(again&&again!==doc.activeElement&&!again.disabled&&typeof again.focus==='function')again.focus({preventScroll:true});
    }
    return result;
  }
  function landFocus(el,options){
    if(!el||typeof el.focus!=='function')return false;
    el.setAttribute('data-settings-landed','');
    el.addEventListener('blur',()=>el.removeAttribute('data-settings-landed'),{once:true});
    el.focus({preventScroll:!(options&&options.scroll)});
    return true;
  }

  /* ------------------------------------------------------------------ fondation visuelle (refonte-ui-settings S01)
     Fragments des primitives partagées (`docs/settings/visual-foundation.md`). Même règle d'échappement : texte
     échappé ; `icon` (un SVG), `body`, `control`, `aside`, `actions` et `items` sont du HTML déjà construit. Aucune
     valeur de réglage n'est inventée ici : la valeur, le désactivé et l'« en cours » viennent de l'appelant. */
  const TONES=Object.freeze(['blue','cyan','violet','magenta','teal','amber','ok','warn','bad','off']);
  const DOT_KINDS=Object.freeze(['ok','warn','bad','info','off']);
  const toneClass=tone=>TONES.includes(tone)?` set-tone-${tone}`:'';
  const describedBy=ids=>{const list=[].concat(ids||[]).filter(Boolean).map(idAttr);return list.length?` aria-describedby="${list.join(' ')}"`:''};
  const pct=(value,min,max)=>{const lo=Number(min),hi=Number(max),v=Number(value);
    if(!Number.isFinite(lo)||!Number.isFinite(hi)||hi<=lo||!Number.isFinite(v))return 0;
    return Math.round(Math.min(1,Math.max(0,(v-lo)/(hi-lo)))*1000)/10};

  function medallion({icon='',tone,size}={}){
    const sz=size==='sm'||size==='lg'?` set-medallion-${size}`:'';
    return `<span class="set-medallion${sz}${toneClass(tone)}" aria-hidden="true">${icon}</span>`;
  }

  /* Panneau verre titré. `variant` : 'hot' (actif, appel principal) ou 'quiet' (secondaire). */
  function panel({id,title,description,icon,tone,aside='',body='',variant,level=3}={}){
    const key=idAttr(id),head=key?`${key}-title`:'',h=level===2?'h2':'h3';
    const v=variant==='hot'||variant==='quiet'?` set-panel-${variant}`:'';
    return `<section class="set-panel${v}${toneClass(tone)}"${key?` id="${key}" aria-labelledby="${head}"`:''}>`
      +`<header class="set-panel-head">${icon?medallion({icon}):''}<div class="set-panel-titles">`
      +`<${h} class="set-panel-title"${head?` id="${head}"`:''}>${esc(title)}</${h}>`
      +(description?`<p class="set-panel-desc">${esc(description)}</p>`:'')+'</div>'
      +(aside?`<div class="set-panel-aside">${aside}</div>`:'')+'</header>'
      +`<div class="set-panel-body">${body}</div></section>`;
  }

  function stat({value,label,icon,tone,stack=false}={}){
    if(!String(label||'').trim())throw new Error('JarvisSettingsUI.stat : une statistique porte toujours un libellé.');
    return `<div class="set-stat${stack?' set-stat-stack':''}${toneClass(tone)}">`
      +(icon?`<span class="set-stat-icon" aria-hidden="true">${icon}</span>`:'')
      +`<span class="set-stat-text"><strong class="set-stat-value">${esc(value)}</strong><span class="set-stat-label">${esc(label)}</span></span></div>`;
  }

  /* Ligne libellé + contrôle (`wide` : le contrôle prend la place restante, ex. un curseur). Le libellé porte `<id>-label`, l'aide `<id>-hint` : `control` les référence
     (`aria-labelledby`, `aria-describedby`) — c'est ce que font `toggle` et `select` quand on leur passe `labelledBy`. */
  function row({id,label,hint,icon,tone,control='',plain=false,wide=false}={}){
    const key=idAttr(id);
    if(!key)throw new Error('JarvisSettingsUI.row : identifiant requis (libellé lié au contrôle).');
    return `<div class="set-row${plain?' set-row-plain':''}${wide?' set-row-wide':''}${toneClass(tone)}">`
      +(icon?`<span class="set-row-icon" aria-hidden="true">${icon}</span>`:'')
      +`<div class="set-row-text"><span class="set-row-label" id="${key}-label">${esc(label)}</span>`
      +(hint?`<p class="set-row-hint" id="${key}-hint">${esc(hint)}</p>`:'')+'</div>'
      +`<div class="set-row-control">${control}</div></div>`;
  }

  /* `className` : classe d'accroche ajoutée devant `set-dot` (ex. `mem-pill`, que lisent les tests Mémoire). */
  function dot(kind,text,{className}={}){
    const k=DOT_KINDS.includes(kind)?kind:'info';
    if(!String(text||'').trim())throw new Error('JarvisSettingsUI.dot : une pastille porte toujours un mot.');
    const extra=String(className||'').trim().split(/\s+/).filter(c=>/^[\w-]+$/.test(c)).join(' ');
    return `<span class="${extra?extra+' ':''}set-dot set-dot-${k}">${esc(text)}</span>`;
  }

  /* Bouton. `variant` : 'primary' | 'ghost' | 'danger' ; `size` : 'sm' ; `iconOnly` : `label` devient `aria-label`.
     `data` : attributs `data-*` (clés `[a-z0-9-]`), valeurs échappées. `busy` pose `aria-busy` et désactive. */
  const DATA_KEY=/^[a-z][a-z0-9-]{0,40}$/;
  function dataAttrs(data){
    return Object.entries(data||{}).map(([k,v])=>{if(!DATA_KEY.test(k))throw new Error(`JarvisSettingsUI : attribut data-${k} invalide.`);
      return ` data-${k}="${esc(v)}"`}).join('');
  }
  function button({id,label,variant,size,icon='',iconOnly=false,tone,disabled=false,busy=false,type='button',data,describedBy:hint}={}){
    if(!String(label||'').trim())throw new Error('JarvisSettingsUI.button : un bouton porte toujours un nom.');
    const key=idAttr(id);
    const cls='set-btn'+(['primary','ghost','danger'].includes(variant)?` set-btn-${variant}`:'')+(size==='sm'?' set-btn-sm':'')+(iconOnly?' set-btn-icon':'')+toneClass(tone);
    return `<button type="${type==='submit'?'submit':'button'}" class="${cls}"${key?` id="${key}"`:''}${dataAttrs(data)}`
      +`${iconOnly?` aria-label="${esc(label)}"`:''}${describedBy(hint)}${disabled||busy?' disabled':''}${busy?' aria-busy="true"':''}>`
      +`${icon}${iconOnly?'':`<span>${esc(label)}</span>`}</button>`;
  }

  /* Liste déroulante native habillée. `options` : [{value,label,disabled}]. Nom accessible : `label` (aria-label) ou
     `labelledBy` (id d'un libellé visible). */
  function select({id,options=[],value,label,labelledBy,describedBy:hint,disabled=false,data}={}){
    const key=idAttr(id);
    if(!key)throw new Error('JarvisSettingsUI.select : identifiant requis.');
    const name=labelledBy?` aria-labelledby="${idAttr(labelledBy)}"`:label?` aria-label="${esc(label)}"`:'';
    const opts=options.map(o=>`<option value="${esc(o.value)}"${String(o.value)===String(value)?' selected':''}${o.disabled?' disabled':''}>${esc(o.label===undefined?o.value:o.label)}</option>`).join('');
    return `<span class="set-select"><select id="${key}"${name}${describedBy(hint)}${dataAttrs(data)}${disabled?' disabled':''}>${opts}</select></span>`;
  }

  /* Curseur avec valeur lue et bornes nommées. Le texte affiché (et `aria-valuetext`) : `format(value)`, ou, déclaratif
     et repris par `bindRange`/`bindAll` sans fonction, `decimals` et `suffix` (« 80 % », « 1.0x »). La plage vient de
     l'appelant (schéma servi), jamais d'ici. */
  const DECIMALS=/^[0-3]$/;
  function declaredFormat(decimals,suffix){
    const d=DECIMALS.test(String(decimals))?Number(decimals):null,tail=suffix===undefined||suffix===null?'':String(suffix);
    return value=>(d===null?String(value):Number(value).toFixed(d))+tail;
  }
  function range({id,min=0,max=100,step=1,value,label,labelledBy,describedBy:hint,minLabel,maxLabel,inlineEnds=false,showValue=true,format,decimals,suffix,disabled=false,data}={}){
    const key=idAttr(id);
    if(!key)throw new Error('JarvisSettingsUI.range : identifiant requis.');
    const declared=(decimals!==undefined?` data-set-decimals="${esc(decimals)}"`:'')+(suffix!==undefined?` data-set-suffix="${esc(suffix)}"`:'');
    const text=(typeof format==='function'?format:declaredFormat(decimals,suffix))(value===undefined?'':value);
    const name=labelledBy?` aria-labelledby="${idAttr(labelledBy)}"`:label?` aria-label="${esc(label)}"`:'';
    const input=`<input type="range" class="set-range" id="${key}" min="${esc(min)}" max="${esc(max)}" step="${esc(step)}" value="${esc(value)}"`
      +`${name}${describedBy(hint)} aria-valuetext="${esc(text)}" style="--set-range-fill:${pct(value,min,max)}%"${declared}${dataAttrs(data)}${disabled?' disabled':''}>`;
    const out=showValue?`<output class="set-range-value" for="${key}" id="${key}-value">${esc(text)}</output>`:'';
    if(inlineEnds)return `<div class="set-range-field set-range-inline${showValue?' set-range-valued':''}"><span class="set-range-end" aria-hidden="true">${esc(minLabel)}</span>`
      +`${input}<span class="set-range-end" aria-hidden="true">${esc(maxLabel)}</span>${out}</div>`;
    return `<div class="set-range-field${showValue?'':' set-range-bare'}">${input}${out}`
      +(minLabel||maxLabel?`<span class="set-range-ends" aria-hidden="true"><span>${esc(minLabel)}</span><span>${esc(maxLabel)}</span></span>`:'')+'</div>';
  }

  /* Interrupteur `button[role=switch]`. `stateText` : {on,off} affiché à côté (« Activé » / « Désactivé »). */
  function toggle({id,checked=false,label,labelledBy,describedBy:hint,stateText,tone,disabled=false,busy=false,data}={}){
    const key=idAttr(id);
    if(!label&&!labelledBy)throw new Error('JarvisSettingsUI.toggle : un interrupteur porte toujours un nom.');
    const name=labelledBy?` aria-labelledby="${idAttr(labelledBy)}"`:` aria-label="${esc(label)}"`;
    const words=stateText&&stateText.on&&stateText.off?` data-on="${esc(stateText.on)}" data-off="${esc(stateText.off)}"`:'';
    return `<button type="button" role="switch" class="set-switch${toneClass(tone)}"${key?` id="${key}"`:''} aria-checked="${checked?'true':'false'}"`
      +`${name}${describedBy(hint)}${words}${dataAttrs(data)}${disabled||busy?' disabled':''}${busy?' aria-busy="true"':''}>`
      +`<span class="set-switch-track" aria-hidden="true"></span>`
      +(words?`<span class="set-switch-text" aria-hidden="true">${esc(checked?stateText.on:stateText.off)}</span>`:'')+'</button>';
  }

  /* Zone de texte avec compteur `n/max` (le compteur suit la saisie par `bindCounter`). */
  function textarea({id,value='',maxLength,placeholder,label,labelledBy,describedBy:hint,rows=4,disabled=false,data}={}){
    const key=idAttr(id);
    if(!key)throw new Error('JarvisSettingsUI.textarea : identifiant requis.');
    const max=Number.isInteger(maxLength)&&maxLength>0?maxLength:null,text=String(value===undefined||value===null?'':value);
    const name=labelledBy?` aria-labelledby="${idAttr(labelledBy)}"`:label?` aria-label="${esc(label)}"`:'';
    return `<div class="set-textarea"><textarea id="${key}" rows="${Number(rows)||4}"${name}${describedBy([].concat(hint||[],max?`${key}-count`:[]))}`
      +`${max?` maxlength="${max}"`:''}${placeholder?` placeholder="${esc(placeholder)}"`:''}${dataAttrs(data)}${disabled?' disabled':''}>${esc(text)}</textarea>`
      +(max?`<span class="set-textarea-count" id="${key}-count" data-max="${max}">${text.length}/${max}</span>`:'')+'</div>';
  }

  /* Onglets internes : `role=tablist`, tabulation itinérante (un seul onglet focalisable) ; `wireTabs` gère les
     flèches, Début, Fin et le clic. `items` : [{id,label,icon,controls,disabled}]. */
  function tabs({id,label,items=[],selected,fill=false,scroll=false}={}){
    const key=idAttr(id);
    if(!String(label||'').trim())throw new Error('JarvisSettingsUI.tabs : une liste d\'onglets porte un nom.');
    const current=items.some(t=>t.id===selected)?selected:(items[0]||{}).id;
    return `<div class="set-tabs${fill?' set-tabs-fill':''}${scroll?' set-tabs-scroll':''}" role="tablist" aria-label="${esc(label)}"${key?` id="${key}"`:''}>`
      +items.map(t=>{const tid=idAttr(t.id),on=t.id===current;
        return `<button type="button" role="tab" class="set-tab" id="${key?`${key}-`:''}${tid}" data-set-tab="${tid}" aria-selected="${on}" tabindex="${on?0:-1}"`
          +`${t.controls?` aria-controls="${idAttr(t.controls)}"`:''}${t.disabled?' disabled':''}>${t.icon||''}<span>${esc(t.label)}</span></button>`}).join('')+'</div>';
  }

  /* Choix en cartes : un groupe radio (`fieldset` + `legend`). `items` : [{value,title,description,icon,disabled}]. */
  function choices({name,legend,items=[],value,disabled=false,tone}={}){
    if(!ID.test(String(name||'')))throw new Error('JarvisSettingsUI.choices : nom de groupe invalide.');
    return `<fieldset class="set-choices${toneClass(tone)}"${disabled?' disabled':''}>`+(legend?`<legend class="sr-only">${esc(legend)}</legend>`:'')
      +items.map(c=>`<label class="set-choice"><input type="radio" name="${name}" value="${esc(c.value)}"${String(c.value)===String(value)?' checked':''}${c.disabled?' disabled':''}>`
        +(c.icon?`<span class="set-choice-icon" aria-hidden="true">${c.icon}</span>`:'')
        +`<span class="set-choice-text"><span class="set-choice-title">${esc(c.title)}</span>`
        +(c.description?`<span class="set-choice-desc">${esc(c.description)}</span>`:'')+'</span></label>').join('')+'</fieldset>';
  }

  /* Coquille de tableau dense. `columns` : [{label,num}] ; `body` : les `<tr>` de la page ; `foot` : HTML du pied. */
  function table({id,label,columns=[],body='',foot=''}={}){
    if(!String(label||'').trim())throw new Error('JarvisSettingsUI.table : un tableau porte un nom.');
    const key=idAttr(id);
    return `<div class="set-table-shell"${key?` id="${key}"`:''}><div class="set-table-scroll" role="region" tabindex="0" aria-label="${esc(label)}">`
      +`<table class="set-table"><thead><tr>${columns.map(c=>`<th scope="col"${c.num?' class="set-num"':''}>${esc(c.label)}</th>`).join('')}</tr></thead>`
      +`<tbody>${body}</tbody></table></div>`+(foot?`<div class="set-table-foot">${foot}</div>`:'')+'</div>';
  }

  /* Panneau flottant, fermé (`hidden`) : `openFloat` l'ouvre. `role=dialog` nommé par son titre. */
  function float({id,title,eyebrow,body='',actions:buttons='',tone,popover=false,closeLabel='Fermer'}={}){
    const key=idAttr(id);
    if(!key)throw new Error('JarvisSettingsUI.float : identifiant requis.');
    return `<div class="set-float${popover?' set-float-popover':''}${toneClass(tone)}" id="${key}" role="dialog" aria-labelledby="${key}-title" hidden>`
      +`<header class="set-float-head"><div class="set-float-titles">${eyebrow?`<p class="set-float-eyebrow">${esc(eyebrow)}</p>`:''}`
      +`<h3 class="set-float-title" id="${key}-title">${esc(title)}</h3></div>`
      +`<button type="button" class="set-btn set-btn-ghost set-btn-icon set-btn-sm" data-set-float-close aria-label="${esc(closeLabel)}">`
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></header>'
      +body+(buttons?`<div class="set-float-actions">${buttons}</div>`:'')+'</div>';
  }

  /* -------- liaisons DOM : chacune ne touche qu'aux éléments qu'on lui donne et rend sa fonction de détachement. */
  function syncRange(input,format){
    const fill=pct(input.value,input.min||0,input.max||100);
    input.style.setProperty('--set-range-fill',`${fill}%`);
    const text=(typeof format==='function'?format:declaredFormat(input.dataset.setDecimals,input.dataset.setSuffix))(input.value);
    input.setAttribute('aria-valuetext',text);
    const out=input.id&&input.ownerDocument.getElementById(`${input.id}-value`);
    if(out)out.textContent=text;
    return text;
  }
  function bindRange(input,{format,onInput}={}){
    const handler=()=>{const text=syncRange(input,format);if(onInput)onInput(input.value,text)};
    input.addEventListener('input',handler);
    return ()=>input.removeEventListener('input',handler);
  }
  function syncCounter(area){
    const doc=area.ownerDocument,count=area.id&&doc.getElementById(`${area.id}-count`);
    if(!count)return;
    const max=Number(count.dataset.max)||0,n=area.value.length;
    count.textContent=`${n}/${max}`;
    const box=area.closest('.set-textarea');
    if(box)box.toggleAttribute('data-over',max>0&&n>=max);
  }
  function bindCounter(area){
    const handler=()=>syncCounter(area);
    area.addEventListener('input',handler);syncCounter(area);
    return ()=>area.removeEventListener('input',handler);
  }
  /* Affichage seulement : le contrôleur décide de l'état réel et le repose par `setToggle` (échec, refus). */
  function setToggle(button,checked){
    button.setAttribute('aria-checked',checked?'true':'false');
    const text=button.querySelector('.set-switch-text');
    if(text&&button.dataset.on&&button.dataset.off)text.textContent=checked?button.dataset.on:button.dataset.off;
  }
  function bindToggle(button,onChange){
    const handler=()=>{if(button.disabled||button.getAttribute('aria-disabled')==='true')return;
      const next=button.getAttribute('aria-checked')!=='true';setToggle(button,next);if(onChange)onChange(next)};
    button.addEventListener('click',handler);
    return ()=>button.removeEventListener('click',handler);
  }
  function setTab(list,tabId,{focus=false}={}){
    const all=[...list.querySelectorAll('[role=tab]')],tab=all.find(t=>t.dataset.setTab===tabId);
    if(!tab||tab.disabled)return false;
    for(const t of all){const on=t===tab;t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1}
    if(focus)tab.focus();
    return true;
  }
  function wireTabs(list,onSelect){
    const pick=(tab,focus)=>{if(tab&&setTab(list,tab.dataset.setTab,{focus})&&onSelect)onSelect(tab.dataset.setTab)};
    const click=event=>{const tab=event.target.closest('[role=tab]');if(tab&&list.contains(tab))pick(tab,false)};
    const keydown=event=>{
      const all=[...list.querySelectorAll('[role=tab]:not(:disabled)')],at=all.indexOf(event.target);
      if(at<0)return;
      const to={ArrowRight:at+1,ArrowDown:at+1,ArrowLeft:at-1,ArrowUp:at-1,Home:0,End:all.length-1}[event.key];
      if(to===undefined)return;
      event.preventDefault();pick(all[(to+all.length)%all.length],true);
    };
    list.addEventListener('click',click);list.addEventListener('keydown',keydown);
    return ()=>{list.removeEventListener('click',click);list.removeEventListener('keydown',keydown)};
  }
  /* Ouvre `panel` (un `.set-float`) : focus sur `initialFocus` ou le premier contrôle, `aria-expanded` sur le
     déclencheur ; Échap (consommé : le shell ne se ferme pas), le bouton `[data-set-float-close]` ou un clic hors du
     panneau et du déclencheur le referment et rendent le focus au déclencheur. Rend `close(reason)` ; idempotent :
     un panneau déjà ouvert rend le même `close` sans doubler ses écouteurs. */
  const OPEN_FLOATS=new WeakMap();
  function openFloat(panel,{trigger,initialFocus,onClose}={}){
    if(OPEN_FLOATS.has(panel))return OPEN_FLOATS.get(panel);
    const doc=panel.ownerDocument;
    let open=true;
    const close=(reason='api',{focus=true}={})=>{
      if(!open)return false;open=false;OPEN_FLOATS.delete(panel);
      panel.hidden=true;panel.removeEventListener('keydown',keydown);panel.removeEventListener('click',click);
      doc.removeEventListener('pointerdown',outside,true);
      if(trigger){trigger.setAttribute('aria-expanded','false');if(focus&&typeof trigger.focus==='function')trigger.focus({preventScroll:true})}
      if(onClose)onClose(reason);
      return true;
    };
    const keydown=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close('escape')}};
    const click=event=>{if(event.target.closest('[data-set-float-close]'))close('button')};
    const outside=event=>{if(!panel.contains(event.target)&&!(trigger&&trigger.contains(event.target)))close('outside',{focus:false})};
    OPEN_FLOATS.set(panel,close);
    panel.hidden=false;
    if(trigger)trigger.setAttribute('aria-expanded','true');
    panel.addEventListener('keydown',keydown);panel.addEventListener('click',click);
    doc.addEventListener('pointerdown',outside,true);
    const first=initialFocus||panel.querySelector('button:not([data-set-float-close]):not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')
      ||panel.querySelector('[data-set-float-close]');
    if(first&&typeof first.focus==='function')first.focus({preventScroll:true});
    return close;
  }
  /* Lie d'un coup les curseurs et compteurs d'un rendu neuf de `host` ; rend un détachement unique. */
  function bindAll(host){
    const off=[...host.querySelectorAll('input.set-range')].map(el=>bindRange(el))
      .concat([...host.querySelectorAll('.set-textarea>textarea')].map(el=>bindCounter(el)));
    return ()=>off.forEach(fn=>fn());
  }

  const api=Object.freeze({esc,APPLIES_LABELS,BADGE_KINDS,NOTICE_KINDS,TONES,DOT_KINDS,intro,section,field,badge,appliesBadge,notice,advanced,actions,keepFocus,landFocus,
    medallion,panel,stat,row,dot,button,select,range,toggle,textarea,tabs,choices,table,float,
    syncRange,bindRange,syncCounter,bindCounter,setToggle,bindToggle,setTab,wireTabs,openFloat,bindAll});
  root.JarvisSettingsUI=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
