# -*- coding: utf-8 -*-
"""Remplace la fenetre flottante par une section de l'onglet Apparence."""
from pathlib import Path

p = Path(r"D:\Projects\CIRCOE\Jarvis\jarvis\runtime\control_center_scene_page.js")
src = p.read_text(encoding="utf-8")

start = src.index("  /* \u00c9toile \u00e0 cinq branches du bouton (rep\u00e8re 12 \u00d7 12 de `svgIcon`). */")
end = src.index("  function ensureRoot(){", start)

NEW = '''  /* ------------------------------------------------------------------
     O\u00f9 ces r\u00e9glages se r\u00e8glent : R\u00e9glages \u2192 Apparence (2026-09-20).

     Ils tenaient jusqu'ici dans une fen\u00eatre ouverte par un bouton en bas \u00e0
     droite de la sc\u00e8ne. L'utilisateur les a voulus l\u00e0 o\u00f9 vivent les autres
     r\u00e9glages, sous la version Cosmos ; le bouton flottant a disparu avec la
     fen\u00eatre. Ce qui ne change pas : ce sont toujours des pr\u00e9f\u00e9rences
     **d'affichage**, propres \u00e0 ce navigateur, appliqu\u00e9es \u00e0 chaud.

     Deux cons\u00e9quences de ce d\u00e9m\u00e9nagement, qui expliquent le code plus bas :
     - la section vit dans le modal, hors de `#sceneLayer` : elle doit donc
       exister **m\u00eame sc\u00e8ne \u00e9teinte**, sans d\u00e9pendre de `root`, et porter son
       propre style (celui de la sc\u00e8ne n'est pos\u00e9 qu'avec la sc\u00e8ne) ;
     - elle a sa propre r\u00e9gion vivante : `announce` \u00e9crit dans la sc\u00e8ne, qui
       peut ne pas \u00eatre l\u00e0. */

  /* Style de la section, pos\u00e9 une fois et ind\u00e9pendamment de la sc\u00e8ne : il
     emprunte les jetons du Control Center (`--line`, `--muted`, `--accent`) et
     non ceux de `.scene`, qui ne sont pas r\u00e9solus dans le modal. */
  const VIEW_SETTINGS_STYLE=`#sceneViewSettings{margin-top:4px}
#sceneViewSettings .sc-view-row{display:grid;grid-template-columns:1fr auto;align-items:center;gap:4px 10px;padding:9px 0;border-top:1px solid var(--line)}
#sceneViewSettings .sc-view-row label{font-size:12px;color:var(--text);cursor:pointer}
#sceneViewSettings .sc-view-val{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-variant-numeric:tabular-nums}
#sceneViewSettings .sc-view-row input[type=range]{grid-column:1 / -1;width:100%;height:14px;margin:0;accent-color:var(--accent);cursor:pointer}
#sceneViewSettings .sc-view-row input[type=checkbox]{width:16px;height:16px;margin:0;accent-color:var(--accent);cursor:pointer}
#sceneViewSettings .sc-view-row input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
/* R\u00e9glage sans effet tant que celui dont il d\u00e9pend est \u00e9teint : gris\u00e9, jamais
   oubli\u00e9 \u2014 il reprend sa valeur au rallumage. */
#sceneViewSettings .sc-view-row.sc-off{opacity:.42}
#sceneViewSettings .sc-view-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}
#sceneViewSettings button.sc-view-reset{border:1px solid var(--line);border-radius:999px;padding:6px 13px;background:rgba(151,191,209,.08);color:var(--text);
  font:inherit;font-size:10px;letter-spacing:.08em;text-transform:uppercase;cursor:pointer}
#sceneViewSettings button.sc-view-reset:hover:not(:disabled){background:rgba(151,191,209,.18)}
#sceneViewSettings button.sc-view-reset:disabled{opacity:.4;cursor:default}
#sceneViewSettings .sc-view-note{font-size:10px;line-height:1.5;color:var(--muted);text-align:right;flex:1 1 auto}
#sceneViewSettings .sc-view-live{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media(max-width:560px){#sceneViewSettings .sc-view-foot{flex-direction:column;align-items:stretch}
  #sceneViewSettings .sc-view-note{text-align:left}}`;

  function ensureViewSettingsStyle(){
    if(document.getElementById('jarvisSceneViewStyle'))return;
    const style=document.createElement('style');
    style.id='jarvisSceneViewStyle';style.textContent=VIEW_SETTINGS_STYLE;
    document.head.appendChild(style);
  }

  /* R\u00e9gion vivante de la section : la sc\u00e8ne peut \u00eatre \u00e9teinte, et sa propre
     r\u00e9gion n'existe alors pas. Tant que la section est \u00e0 l'\u00e9cran, c'est elle
     qui parle ; sinon on retombe sur celle de la sc\u00e8ne. */
  function announceView(text){
    const live=viewSection&&viewSection.isConnected?viewSection.querySelector('.sc-view-live'):null;
    if(!live){announce(text);return}
    if(live.textContent===text)live.textContent='';
    live.textContent=text;
  }

  /* La section telle qu'elle appara\u00eet dans R\u00e9glages \u2192 Apparence. Reconstruite
     \u00e0 chaque rendu de l'onglet : elle ne survit pas \u00e0 la fermeture du modal et
     n'a donc jamais \u00e0 se rattraper toute seule. */
  function buildViewSection(){
    if(!V)return null;
    const section=document.createElement('section');
    section.id='sceneViewSettings';
    section.setAttribute('aria-labelledby','sceneViewTitle');
    const title=element('h3','','\u00c9toiles et orbites');
    title.id='sceneViewTitle';
    const lead=element('div','hint','La constellation que dessine la version Cosmos : taille des \u00e9toiles, halo, gravitation, fils entre les objets. Chaque changement s\\'applique imm\u00e9diatement.');
    lead.style.marginBottom='14px';
    const note=element('div','sc-view-note','Ce navigateur seulement : ni la sc\u00e8ne enregistr\u00e9e ni ce que voit le cerveau ne changent.');
    note.id='sceneViewNote';
    const live=element('div','sc-view-live');
    live.setAttribute('role','status');live.setAttribute('aria-live','polite');
    section.append(title,lead);
    viewRows=V.FIELDS.map(field=>{
      const row=element('div','sc-view-row');
      row.title=field.hint;
      const input=document.createElement('input');
      input.id=`scView_${field.id}`;
      input.setAttribute('aria-describedby','sceneViewNote');
      const label=element('label','',field.label);
      label.htmlFor=input.id;
      const value=element('span','sc-view-val');
      if(field.type==='toggle'){
        input.type='checkbox';
        row.append(label,input);
      }else{
        input.type='range';
        input.min=String(field.min);input.max=String(field.max);input.step=String(field.step);
        row.append(label,value,input);
      }
      /* `input` applique pendant le glissement (le r\u00e9glage se voit tout de
         suite sur la sc\u00e8ne derri\u00e8re le modal) ; `change` seul est journalis\u00e9 et
         annonc\u00e9, une fois pos\u00e9. */
      input.addEventListener('input',()=>setViewField(field,field.type==='toggle'?input.checked:Number(input.value)));
      input.addEventListener('change',()=>{
        announceView(V.changeSentence(field,viewPrefs[field.id]));
        consoleLog('info','scene.view_changed',{field:field.id,value:viewPrefs[field.id]});
      });
      section.append(row);
      return {field,row,input,value};
    });
    const reset=element('button','sc-view-reset','R\u00e9initialiser');
    reset.type='button';
    reset.addEventListener('click',()=>{
      viewPrefs=V.normalize(null);
      saveViewPrefs();applyViewPrefs();syncViewPanel();
      announceView('\u00c9toiles et orbites r\u00e9initialis\u00e9es.');
      consoleLog('info','scene.view_reset',{});
    });
    const foot=element('div','sc-view-foot');
    foot.append(reset,note);
    section.append(foot,live);
    viewSection=section;
    syncViewPanel();
    return section;
  }

  function setViewField(field,value){
    if(!V)return;
    const next=Object.assign({},viewPrefs);
    next[field.id]=value;
    viewPrefs=V.normalize(next);
    saveViewPrefs();applyViewPrefs();syncViewPanel();
  }

  /* Valeurs, gris\u00e9s et bouton \u00ab R\u00e9initialiser \u00bb d'apr\u00e8s les r\u00e9glages courants.
     La section peut avoir \u00e9t\u00e9 jet\u00e9e avec le modal : on ne parle qu'\u00e0 un n\u0153ud
     encore dans la page. */
  function syncViewPanel(){
    if(!viewSection||!viewSection.isConnected||!V)return;
    const model=V.describe(viewPrefs);
    model.rows.forEach((row,index)=>{
      const target=viewRows[index];
      if(!target)return;
      if(target.field.type==='toggle')target.input.checked=!!row.value;
      else{target.input.value=String(row.value);target.value.textContent=row.label}
      target.row.classList.toggle('sc-off',!row.enabled);
      /* Gris\u00e9 mais jamais vid\u00e9 : le r\u00e9glage reprend sa valeur au rallumage. */
      target.input.disabled=!row.enabled;
    });
    const reset=viewSection.querySelector('.sc-view-reset');
    if(reset)reset.disabled=!model.custom;
  }

  /* Installation dans l'onglet Apparence. `control_center_work.js` dessine cet
     onglet en entier et est ins\u00e9r\u00e9 **avant** ce fichier : son `setTimeout(0)`
     passe donc avant le n\u00f4tre, et l'onglet existe d\u00e9j\u00e0 quand on l'enveloppe.
     On attend son rendu, puis on ajoute la section \u00e0 la suite des versions.

     L'\u00e9coute `storage` est pos\u00e9e ici, et non avec la sc\u00e8ne : un autre onglet
     peut r\u00e9gler l'affichage alors que la sc\u00e8ne est \u00e9teinte ici, et la section
     doit quand m\u00eame montrer la bonne valeur. */
  function installViewSettings(){
    if(!V||typeof renderTab!=='function'||typeof TABS==='undefined'||!Array.isArray(TABS))return;
    ensureViewSettingsStyle();
    window.addEventListener('storage',onViewStorage);
    const baseRenderTab=renderTab;
    renderTab=async function(){
      const result=await baseRenderTab.apply(this,arguments);
      if(typeof SET!=='undefined'&&SET.open&&SET.tab==='appearance'){
        const content=document.getElementById('modalContent');
        if(content&&!content.querySelector('#sceneViewSettings')){
          viewPrefs=loadViewPrefs();
          const section=buildViewSection();
          if(section)content.append(section);
        }
      }
      return result;
    };
  }

  setTimeout(installViewSettings,0);

'''

src = src[:start] + NEW + src[end:]
p.write_text(src, encoding="utf-8")
print("bloc remplace")
