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
   - `actions`  : une rangée de boutons, alignée sur la colonne des contrôles. */
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

  const api=Object.freeze({esc,APPLIES_LABELS,BADGE_KINDS,NOTICE_KINDS,intro,section,field,badge,appliesBadge,notice,advanced,actions});
  root.JarvisSettingsUI=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
