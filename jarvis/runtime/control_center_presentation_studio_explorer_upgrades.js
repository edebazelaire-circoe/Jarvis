/* Nouvelle version d'un prefab épinglé : avis et essai dans l'explorateur de variantes (handoff jarvis-remotion-presentation-integration, Slice 19, interface).

   Module DOM exposé en `window.JarvisStudioExplorerUpgrades` dans la page et en `module.exports` pour node. Le contrôleur de l'explorateur ne lui prête que des
   aides (réseau, occupation, relecture du graphe) ; il ne garde AUCUN état de présentation : tout vient de `GET .../variants/{id}/upgrades` et y retourne.

   Règles tenues ici :
   - **Rien ne se met à jour tout seul.** La zone dit qu'une version plus récente existe (scène, v épinglée -> v la plus récente, nombre de versions) et ce que Core
     sait : la version tient-elle la scène (`fits`), le moteur la prend-il (`engine_ok`, natif seulement). Le seul geste est « Essayer dans une nouvelle variante » :
     Core crée une variante ENFANT, la variante d'origine n'est ni modifiée ni activée. Comparer et activer sont les gestes habituels de l'explorateur (explicites).
   - **Visible.** Chargement avec compteur de secondes et sortie (« Réessayer »), échec dit avec les mots de Core, essai en cours annoncé par la barre d'occupation de
     l'explorateur (compteur), résultat dit dans la zone de message ; un bouton inactif dit POURQUOI (titre et texte).
   - Le relais force l'acteur `user` : ce module n'envoie jamais d'acteur. Tout texte d'auteur (titre de scène) passe par `textContent` après `cleanLine`. */
(function(root){
  'use strict';
  const Core=root.JarvisStudioExplorerCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_core.js'):null);
  const {cleanLine,HOST_ID}=Core;
  const REFRESH_MS=30000;
  const MAX_ROWS=64;

  const CSS=`
#${HOST_ID} .jvx-upg{display:grid;gap:8px;margin-top:12px;padding:12px 14px;border-radius:12px;border:1px solid color-mix(in srgb,var(--jvx-accent) 32%,transparent);background:var(--jvx-surface)}
#${HOST_ID} .jvx-upg[hidden]{display:none}
#${HOST_ID} .jvx-upg-head{display:flex;align-items:center;gap:10px;min-width:0;flex-wrap:wrap}
#${HOST_ID} .jvx-upg-toggle{display:inline-flex;align-items:center;gap:8px;min-height:36px;padding:0 6px;border:0;border-radius:8px;background:transparent;color:var(--jvx-ink);text-align:left}
#${HOST_ID} .jvx-upg-toggle:hover{background:color-mix(in srgb,var(--jvx-accent) 10%,transparent)}
#${HOST_ID} .jvx-upg-toggle svg{width:14px;height:14px;flex:none}
#${HOST_ID} .jvx-upg-toggle[aria-expanded="true"] svg{transform:rotate(90deg)}
#${HOST_ID} .jvx-upg-body{display:grid;gap:8px}
#${HOST_ID} .jvx-upg-body[hidden]{display:none}
#${HOST_ID} .jvx-upg-title{margin:0;font-size:14px;font-weight:650}
#${HOST_ID} .jvx-upg-note{margin:0;color:var(--jvx-mute);font-size:12.5px}
#${HOST_ID} .jvx-upg-status{margin:0;color:var(--jvx-mute);font-size:13px;font-variant-numeric:tabular-nums}
#${HOST_ID} .jvx-upg-status[data-tone="warn"]{color:var(--jvx-warn)}
#${HOST_ID} .jvx-upg-list{margin:0;padding:0;list-style:none;display:grid;gap:8px;max-height:30vh;overflow:auto}
#${HOST_ID} .jvx-upg-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 14px;align-items:center;padding:8px 10px;border-radius:9px;border:1px solid var(--jvx-line);background:rgba(255,255,255,.03)}
#${HOST_ID} .jvx-upg-what{display:grid;gap:3px;min-width:0}
#${HOST_ID} .jvx-upg-scene{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${HOST_ID} .jvx-upg-ver{font:12px/1.3 ui-monospace,Consolas,monospace;color:var(--jvx-mute);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${HOST_ID} .jvx-upg-chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
#${HOST_ID} .jvx-upg-act{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
@media (max-width:720px){#${HOST_ID} .jvx-upg-row{grid-template-columns:minmax(0,1fr)}#${HOST_ID} .jvx-upg-act{justify-content:flex-start}}
`;

  /* Les raisons de Core (`problem`) en mots : jamais un code seul. */
  const PROBLEM_TEXT=Object.freeze({
    presentation_studio_scene_incompatible:"les valeurs ou les réglages de la scène ne tiennent pas dans cette version",
    presentation_studio_engine_unsupported:"cette version n'est pas native pour le moteur de la présentation (déclarée, non utilisable)",
    presentation_studio_prefab_unavailable:"cette version est introuvable ou altérée",
    presentation_studio_score_incompatible:"la partition perdrait des références",
  });
  function problemText(code){return PROBLEM_TEXT[code]||`Core refuse cette version (${cleanLine(code||'raison inconnue',80)})`}

  /* Le modèle d'une ligne d'avis (pur) : `titles` = {scene_id: titre}. */
  function rowModel(notice,titles){
    const n=notice||{};
    const shortPrefab=cleanLine(String(n.prefab_id||'').replace(/^presentation-studio\./,'source '),48);
    const more=Number.isInteger(n.newer_count)&&n.newer_count>1?` (${n.newer_count} versions plus récentes)`:'';
    let blocked=null;
    if(n.reloading)blocked="Cette scène attend la confirmation de son rechargement à chaud : réessayez dans un instant.";
    else if(n.engine_ok===false)blocked=`Essai impossible : ${problemText(n.problem||'presentation_studio_engine_unsupported')}.`;
    else if(n.fits===false)blocked=`Essai impossible : ${problemText(n.problem)}. Rien n'est adapté à votre place.`;
    /* QA B3 : une licence qui change ou qui demande une décision n'est jamais cachée derrière un « Compatible » vert. */
    const ackName=typeof n.licence_ack_required==='string'&&n.licence_ack_required?cleanLine(n.licence_ack_required,120):null;
    const shown=v=>cleanLine(v||'non déclarée',40);
    const licenceChip=n.licence_changed===true?{text:`Licence modifiée : ${shown(n.pinned_licence)} → ${shown(n.latest_licence)}`,tone:'warn'}
      :ackName?{text:`Licence à reconnaître : ${ackName}`,tone:'warn'}:null;
    return {sceneId:n.scene_id,ackName,title:cleanLine((titles&&titles[n.scene_id])||'',80)||'(scène sans titre)',
      version:`${shortPrefab} · v${n.pinned_version} → v${n.latest_version}${more}`,latest:n.latest_version,blocked,
      chips:[
        n.reloading?{text:'Rechargement en cours',tone:'warn'}:n.engine_ok===false?{text:'Moteur : non utilisable',tone:'warn'}:n.fits===false?{text:'Incompatible',tone:'warn'}:{text:'Compatible',tone:'ok'},
        ...(licenceChip?[licenceChip]:[]),
        ...(n.latest_catalog&&n.latest_catalog.upstream&&n.latest_catalog.upstream.verified_intact===true?[{text:'Import vérifié intact',tone:'ok'}]:[]),
      ],
      trials:Array.isArray(n.trials)?n.trials.map(t=>({variantId:t.variant_id,number:t.variant_number,version:t.version})):[]};
  }

  function createUpgrades(ctx){
    const {doc,el,attrs,clear,button,log,announce,call,now,later,cancelLater}=ctx;
    const st={variantId:null,signature:'',status:'idle',data:null,error:null,since:0,generation:0,loadedAt:0,open:false,acked:new Set()};
    const ackKey=(notice,m)=>`${notice.scene_id}|${notice.latest_version}|${m.ackName}`;
    let section=null,count=null,statusLine=null,list=null,retry=null,tick=null,toggle=null,body=null,deferred=null;

    function buildSection(){
      if(section)return section;
      section=el('section','jvx-upg');
      section.hidden=true;
      attrs(section,{'aria-label':'Versions plus récentes des scènes de la variante choisie'});
      const head=el('div','jvx-upg-head');
      const bodyId=ctx.uid('upg');
      toggle=button(null,'jvx-upg-toggle',()=>{st.open=!st.open;render()},{attrs:{'aria-expanded':'false','aria-controls':bodyId,title:'Afficher ou masquer les scènes dont une version plus récente existe'}});
      toggle.appendChild(ctx.icon('chevron'));
      toggle.appendChild(el('h3','jvx-upg-title','Versions plus récentes'));
      count=el('span','jvx-chip');
      toggle.appendChild(count);
      head.appendChild(toggle);
      statusLine=el('span','jvx-upg-status');
      attrs(statusLine,{role:'status','aria-live':'polite'});
      head.appendChild(statusLine);
      retry=button('Relire',null,()=>{reload(true)},{attrs:{title:'Relire les versions disponibles (rien n\'est modifié)'}});
      head.appendChild(retry);
      body=el('div','jvx-upg-body');body.id=bodyId;
      list=el('ul','jvx-upg-list');
      body.appendChild(el('p','jvx-upg-note',"Rien n'est mis à jour tout seul. Essayez une version dans une nouvelle variante, comparez-la, puis activez-la si elle vous convient : la variante d'origine ne change pas."));
      body.appendChild(list);
      section.appendChild(head);
      section.appendChild(body);
      return section;
    }

    function hide(){if(section)section.hidden=true}
    function seconds(){return Math.max(0,Math.round((now()-st.since)/1000))}
    function render(){
      if(!section)return;
      const data=st.data;
      const focused=list.contains(doc.activeElement)&&doc.activeElement.dataset?`${doc.activeElement.dataset.kind}|${doc.activeElement.dataset.scene}`:null;   /* un rendu ne vole pas le focus */
      clear(list);
      if(st.status==='idle'){hide();return}
      if(st.status==='loading'){
        section.hidden=false;count.textContent='…';body.hidden=true;toggle.setAttribute('aria-expanded','false');
        statusLine.textContent=`Recherche des versions plus récentes… ${seconds()} s`;statusLine.removeAttribute('data-tone');
        retry.hidden=true;return;
      }
      if(st.status==='error'){
        section.hidden=false;count.textContent='!';retry.hidden=false;body.hidden=true;toggle.setAttribute('aria-expanded','false');
        statusLine.textContent=`${st.error} — rien n'a été modifié.`;statusLine.setAttribute('data-tone','warn');return;
      }
      retry.hidden=false;
      const notices=data&&Array.isArray(data.notices)?data.notices.slice(0,MAX_ROWS):[];
      if(!notices.length){hide();return}    /* rien de plus récent : la zone n'existe pas (aucun bruit) */
      section.hidden=false;
      count.textContent=`${notices.length} scène${notices.length>1?'s':''}`;
      body.hidden=!st.open;toggle.setAttribute('aria-expanded',st.open?'true':'false');
      statusLine.textContent=st.open?'':"Une version plus récente existe ; rien n'a été changé.";statusLine.removeAttribute('data-tone');
      const titles={};
      for(const s of ctx.scenes())titles[s.id]=s.title;
      for(const notice of notices){
        const m=rowModel(notice,titles);
        const row=el('li','jvx-upg-row');
        const what=el('div','jvx-upg-what');
        const t=el('span','jvx-upg-scene jvx-bidi',m.title);t.setAttribute('dir','auto');
        what.appendChild(t);
        what.appendChild(el('span','jvx-upg-ver',m.version));
        const chips=el('div','jvx-upg-chips');
        for(const c of m.chips){const chip=el('span','jvx-chip',c.text);if(c.tone)chip.setAttribute('data-tone',c.tone);chips.appendChild(chip)}
        what.appendChild(chips);
        if(m.blocked)what.appendChild(el('span','jvx-upg-ver',m.blocked));
        const acked=!m.ackName||st.acked.has(ackKey(notice,m));
        if(m.ackName&&!m.blocked){
          const label=el('label','jvx-check');
          const box=doc.createElement('input');
          box.type='checkbox';box.checked=acked;box.dataset.scene=m.sceneId;box.dataset.kind='ack';
          box.addEventListener('change',()=>{if(box.checked)st.acked.add(ackKey(notice,m));else st.acked.delete(ackKey(notice,m));render()});
          label.appendChild(box);
          label.appendChild(el('span','',`Je reconnais la licence « ${m.ackName} » de cette version`));
          what.appendChild(label);
          if(focused===`ack|${m.sceneId}`)later(()=>box.focus({preventScroll:true}),0);
        }
        const act=el('div','jvx-upg-act');
        const go=button('Essayer dans une nouvelle variante',null,()=>{
          if(ctx.busy()){ctx.say('info','Une opération est déjà en cours.');return}
          if(m.blocked){ctx.say('refused',m.blocked);return}
          if(!acked){ctx.say('refused',`La licence de cette version (« ${m.ackName} ») change ou demande une décision : cochez que vous la reconnaissez, rien n'est créé sans cela.`);return}
          tryVersion(notice,m);
        },{icon:'fork'});
        go.dataset.scene=m.sceneId;go.dataset.kind='try';
        if(m.blocked){go.setAttribute('aria-disabled','true');go.title=m.blocked}
        else if(!acked){go.setAttribute('aria-disabled','true');go.title=`Cochez d'abord la licence « ${m.ackName} » : elle change ou demande une décision.`}
        else go.title=`Crée une variante d'essai avec la version ${m.latest} de cette scène ; la variante choisie ne change pas.`;
        act.appendChild(go);
        if(focused===`try|${m.sceneId}`)later(()=>go.focus({preventScroll:true}),0);
        for(const trial of m.trials){
          const open=button(`Essai #${trial.number} (v${trial.version})`,null,()=>ctx.select(trial.variantId),{attrs:{title:'Aller à la variante d\'essai pour la comparer ou l\'activer'}});
          act.appendChild(open);
        }
        row.appendChild(what);row.appendChild(act);list.appendChild(row);
      }
    }

    function stopTick(){if(tick){ctx.stopEvery(tick);tick=null}}
    function startTick(){
      if(tick)return;
      tick=ctx.every(()=>{if(st.status==='loading')render();else stopTick()},1000);
    }

    async function reload(force){
      if(!st.variantId)return;
      const generation=st.generation+=1;
      const variantId=st.variantId;
      st.status='loading';st.since=now();st.error=null;
      render();startTick();
      try{
        const data=await call('GET',ctx.variantPath(variantId,'/upgrades'),undefined,{timeoutMs:ctx.readTimeout});
        if(generation!==st.generation)return;
        st.data=data;st.status='ready';st.loadedAt=now();
        log('upgrades_loaded',{variant_id:variantId,newer:data&&data.count,unavailable:data&&data.unavailable&&data.unavailable.length||0,forced:!!force});
        if(data&&data.count)announce(`${data.count} scène${data.count>1?'s ont':' a'} une version plus récente.`);
      }catch(error){
        if(generation!==st.generation)return;
        const info=ctx.describe(error);
        st.status='error';st.error=`Les versions plus récentes n'ont pas pu être lues : ${info.text}`;
        log('upgrades_failed',{variant_id:variantId,code:info.code},'warn');
      }finally{stopTick()}
      render();
    }

    /* Appelé par le contrôleur à chaque rendu des métadonnées : relit seulement quand la variante choisie ou sa révision ont changé. */
    function sync(node,graphRevision){
      /* Comme l'aperçu : aucune lecture d'une variante pendant qu'une écriture est en vol (elle peut l'archiver) ; le graphe relu fait foi, on revient ensuite. */
      if(node&&node.state==='live'&&ctx.blocked()){
        if(!deferred)deferred=later(()=>{deferred=null;if(ctx.isOpen())sync(ctx.node(),ctx.revision())},250);
        return;
      }
      if(!node||node.state!=='live'){st.variantId=null;st.signature='';st.status='idle';st.generation+=1;render();return}
      const signature=`${node.variant_id}:${node.revision}:${graphRevision}`;
      if(signature===st.signature){if(st.status==='ready')render();return}   /* les titres des scènes arrivent avec l'aperçu, après l'avis */
      st.signature=signature;st.variantId=node.variant_id;
      reload(false);
    }
    /* Appelé à chaque relecture périodique du graphe : une nouvelle version peut apparaître sans que la variante bouge. */
    function onPoll(){if(st.variantId&&st.status!=='loading'&&now()-st.loadedAt>=REFRESH_MS)reload(false)}

    async function tryVersion(notice,model){
      const node=ctx.node();
      if(!node||node.variant_id!==st.variantId)return;
      let created=null;
      const done=await ctx.perform('upgrade_try',`Essai de la version ${model.latest}`,async()=>{
        created=await call('POST',ctx.variantPath(node.variant_id,'/upgrades/try'),
          Object.assign({scene_id:notice.scene_id,version:notice.latest_version,expected_variant_revision:st.data&&st.data.variant_revision},
            model.ackName?{licence_ack:[model.ackName]}:{}));
        return true;
      });
      if(done&&!done.error){
        const n=created&&created.node?created.node:{};
        log('upgrade_try_created',{variant_id:n.variant_id,from:notice.pinned_version,to:notice.latest_version});
        st.signature='';
        await ctx.after(n.variant_id||null,`Variante d'essai #${n.variant_number||'?'} créée avec la version ${model.latest} : la variante #${node.variant_number} n'a pas changé. Comparez-les (Ctrl+clic pour en marquer deux), puis activez l'essai si elle vous convient.`);
      }
    }

    return Object.freeze({buildSection,sync,onPoll,reload:()=>reload(true),state:()=>({status:st.status,variant_id:st.variantId,count:st.data&&st.data.count||0,error:st.error}),element:()=>section});
  }

  const api=Object.freeze({createUpgrades,rowModel,problemText,CSS});
  root.JarvisStudioExplorerUpgrades=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
