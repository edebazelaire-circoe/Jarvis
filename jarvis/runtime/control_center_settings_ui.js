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
     cliqué à la souris, où `:focus-visible` ne s'applique pas. */
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

  const api=Object.freeze({esc,APPLIES_LABELS,BADGE_KINDS,NOTICE_KINDS,intro,section,field,badge,appliesBadge,notice,advanced,actions,keepFocus,landFocus});
  root.JarvisSettingsUI=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
