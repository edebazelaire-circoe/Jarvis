/* Memory Center du Control Center (jarvis-memory-intelligence-knowledge, Slice 12).

   Vue « Sessions & Boards » étendue : elle occupe le point de montage `#memoryCenterMount` de la fenêtre
   `#workspaceManager` et masque, tant qu'elle est ouverte, les onglets du workspace. Elle ne lit que `/api/memory/*`
   (relais de `/v1/memory/*`) et la section `memory` de `/api/settings` (règles de loadout) ; sa seule écriture est la
   décision d'un candidat (`POST /api/memory/candidates/{id}/decision`), après confirmation.

   Règle d'affichage : ce qui est canonique (notes Markdown) et ce qui est dérivé (index, résultats de recherche,
   aperçu du rappel, état des étages) ne se confondent jamais. Les trois dimensions d'une note (abstraction L0-L3,
   rétention, type) sont affichées séparément. Aucun libellé de réglage n'est recopié : tout vient du serveur. */
(function(root){
  'use strict';
  const MOUNT_ID='memoryCenterMount';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const TABS=Object.freeze([['notes','Notes'],['candidates','Candidats'],['health','Santé des index'],['knowledge','Connaissances'],['recall','Test de rappel']]);
  const LEVELS=Object.freeze({L0:'Preuve brute',L1:'Fait atomique',L2:'Scénario',L3:'Profil stable'});
  const RETENTIONS=Object.freeze({short_term_memory:'Court terme',long_term_memory:'Long terme',traumatic_memory:'Traumatique',eternal_memory:'Éternelle',plastic_memory:'Plastique'});
  const KINDS=Object.freeze({fact:'Fait',preference:'Préférence',scenario:'Scénario',profile:'Profil',episode:'Épisode'});
  const SOURCES=Object.freeze({turn:'Tour',session:'Session',artifact:'Artefact',agent:'Agent',user:'Utilisateur',import:'Import',note:'Note'});
  const CAND_STATES=Object.freeze({proposed:'À décider',accepted:'Accepté',rejected:'Rejeté',superseded_by_newer:'Remplacé par un plus récent'});
  const LEG_LABEL=Object.freeze({store:'Mémoire canonique (Markdown)',lexical:'Index par mots (FTS5)',semantic:'Index sémantique',tencent:'Sidecar Tencent',
    'knowledge:wiki':'Wiki','knowledge:codegraph':'Graphe de code','knowledge:skills':'Skills'});
  const LEG_EFFECT=Object.freeze({store:'Les notes ne peuvent pas être lues : rien n’est rappelé.',
    lexical:'Le rappel par mots est coupé ; les notes restent lisibles ici.',
    semantic:'Le rappel continue par les mots seuls ; les notes ne changent pas.',
    tencent:'Le miroir est ignoré ; les notes canoniques ne changent pas.',
    knowledge:'Ce savoir n’est pas proposé au cerveau ; la mémoire canonique ne change pas.'});
  const STATUS=Object.freeze({ok:['Actif','ok'],disabled:['Désactivé','off'],unavailable:['Indisponible','bad']});
  const DEGRADED=Object.freeze({index_syncing:'Index en synchronisation',recall_timeout:'Délai de rappel dépassé',semantic_unavailable:'Étage sémantique indisponible'});

  const label=(map,key)=>map[key]||String(key??'—');
  const date=v=>v?esc(String(v).replace('T',' ').slice(0,16)):'—';
  const effectOf=name=>LEG_EFFECT[name]||(name.startsWith('knowledge:')?LEG_EFFECT.knowledge:'');
  const q=obj=>Object.entries(obj).filter(([,v])=>v!==''&&v!==false&&v!=null).map(([k,v])=>`${encodeURIComponent(k)}=${encodeURIComponent(v===true?'1':v)}`).join('&');

  /* Les trois dimensions d'une note, chacune sur sa ligne : jamais fondues en une seule étiquette. */
  function dimensions(n){
    return `<dl class="kv mc-dims" aria-label="Dimensions de la mémoire">
      <dt>Abstraction</dt><dd><span class="chip">${esc(n.level)}</span>${esc(label(LEVELS,n.level))}</dd>
      <dt>Rétention</dt><dd>${esc(label(RETENTIONS,n.retention))}</dd>
      <dt>Type</dt><dd>${esc(label(KINDS,n.kind))}</dd>
      <dt>Portée</dt><dd><code>${esc(n.scope)}</code></dd></dl>`;
  }
  function sourcesHtml(list){
    if(!list||!list.length)return '<p class="wsp-none">Aucune source enregistrée.</p>';
    return `<ul class="mc-list">${list.map(s=>`<li><span class="chip">${esc(label(SOURCES,s.type))}</span><code>${esc(s.ref)}</code> <span class="hint">${date(s.at)}</span></li>`).join('')}</ul>`;
  }

  function create(host,options){
    const opts=options||{};
    const fetchJson=opts.fetch||(async(path,init)=>{
      const r=await root.fetch(path,init),text=await r.text();let body={};try{body=text?JSON.parse(text):{}}catch{body={error:{message:text}}}
      if(!r.ok){const err=body.error||{};const e=new Error(typeof err==='string'?err:(err.message||'HTTP '+r.status));e.code=err.code||'';e.status=r.status;throw e}
      return body;
    });
    const fail=e=>({status:'error',error:(e&&e.message||'Erreur inconnue')+(e&&e.code?' ('+e.code+')':'')});
    const st={tab:'notes',focus:null,announce:'',
      notes:{status:'idle',items:[],q:'',hits:null,level:'',retention:'',kind:'',superseded:false,error:'',sel:{id:null,status:'idle',data:null,error:''}},
      cands:{status:'idle',items:[],available:true,filter:'proposed',error:'',sel:{id:null,status:'idle',data:null,error:''},confirm:null,busy:false,msg:null},
      health:{status:'idle',data:null,error:''},
      know:{status:'idle',legs:null,loadouts:null,error:''},
      recall:{q:'',max:6,status:'idle',data:null,error:''}};
    const say=t=>{st.announce=t};

    /* ------------------------------------------------------------ chargements */
    async function loadNotes(){
      const n=st.notes;n.status='loading';n.error='';render();
      try{
        if(n.q.trim()){
          const d=await fetchJson('/api/memory/search?'+q({q:n.q.trim(),level:n.level,retention:n.retention,limit:30}));
          n.hits=d.hits||[];n.items=[];
        }else{
          const d=await fetchJson('/api/memory/notes?'+q({limit:30,level:n.level,retention:n.retention,kind:n.kind,include_superseded:n.superseded}));
          n.items=d.notes||[];n.hits=null;
        }
        n.status='ready';say(`${(n.hits||n.items).length} résultat(s).`);
      }catch(e){Object.assign(n,fail(e));n.hits=null}
      render();
    }
    async function openNote(id,switchTab){
      if(switchTab)st.tab='notes';
      const s=st.notes.sel;s.id=id;s.status='loading';s.error='';s.data=null;st.focus='#mcDetail';render();
      try{const d=await fetchJson('/api/memory/notes/'+encodeURIComponent(id));s.data=d.note;s.status='ready'}catch(e){Object.assign(s,fail(e))}
      st.focus='#mcDetail';render();
    }
    async function loadCands(){
      const c=st.cands;c.status='loading';c.error='';render();
      try{
        const d=await fetchJson('/api/memory/candidates?'+q({state:c.filter,limit:100}));
        c.items=d.candidates||[];c.available=d.available!==false;c.status='ready';
      }catch(e){Object.assign(c,fail(e))}
      render();
    }
    async function openCand(id){
      const s=st.cands.sel;s.id=id;s.status='loading';s.error='';s.data=null;st.cands.confirm=null;st.focus='#mcDetail';render();
      try{const d=await fetchJson('/api/memory/candidates/'+encodeURIComponent(id));s.data=d.candidate;s.status='ready'}catch(e){Object.assign(s,fail(e))}
      st.focus='#mcDetail';render();
    }
    function askDecision(id,decision){st.cands.confirm={id,decision};st.cands.msg=null;st.focus='#mcConfirmCancel';render()}
    function cancelDecision(){const c=st.cands.confirm;st.cands.confirm=null;st.focus=c?`[data-act="cand-${c.decision}"]`:null;render()}
    async function decide(){
      const c=st.cands,k=c.confirm;if(!k||c.busy)return;
      c.busy=true;render();
      try{
        const d=await fetchJson(`/api/memory/candidates/${encodeURIComponent(k.id)}/decision`,
          {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:k.decision})});
        const done=d.candidate||{};
        c.msg={tone:'ok',text:k.decision==='accept'?`Accepté : note canonique ${done.committed_memory_id||''} créée.`:'Candidat rejeté ; aucune note créée.'};
        c.sel.data=done;c.sel.status='ready';
      }catch(e){c.msg={tone:'bad',text:`Décision refusée : ${e.message||'erreur'}${e.code?' ('+e.code+')':''}. Rien n’a été modifié ; relisez la liste.`}}
      c.confirm=null;c.busy=false;say(c.msg.text);st.focus='#mcDetail';render();
      if(c.msg.tone==='ok'){try{const d=await fetchJson('/api/memory/candidates?'+q({state:c.filter,limit:100}));c.items=d.candidates||[]}catch{}render()}
    }
    async function loadHealth(){
      const h=st.health;h.status='loading';h.error='';render();
      try{h.data=await fetchJson('/api/memory/status');h.status='ready'}catch(e){Object.assign(h,fail(e))}
      render();
    }
    async function loadKnowledge(){
      const k=st.know;k.status='loading';k.error='';render();
      const [s,c]=await Promise.allSettled([fetchJson('/api/memory/status'),fetchJson('/api/settings')]);
      if(s.status==='fulfilled'){k.legs=s.value.legs||{};k.available=s.value.available!==false;k.status='ready'}else Object.assign(k,fail(s.reason));
      k.loadouts=c.status==='fulfilled'&&c.value.memory?c.value.memory.loadouts||{}:null;
      render();
    }
    async function runRecall(){
      const r=st.recall;if(!r.q.trim()){r.status='error';r.error='Saisissez une phrase à tester.';render();return}
      r.status='loading';r.error='';r.data=null;render();
      try{r.data=await fetchJson('/api/memory/recall-explain?'+q({q:r.q.trim(),max_items:r.max}));r.status='ready';say(`${(r.data.items||[]).length} élément(s) rappelé(s).`)}
      catch(e){Object.assign(r,fail(e))}
      st.focus='#mcRecallResult';render();
    }
    function load(tab){
      const t=tab||st.tab;
      if(t==='notes')return loadNotes();
      if(t==='candidates')return loadCands();
      if(t==='health')return loadHealth();
      if(t==='knowledge')return loadKnowledge();
      render();return Promise.resolve();
    }
    function setTab(tab){
      if(!TABS.some(([k])=>k===tab))return Promise.resolve();
      st.tab=tab;st.focus=`#mc-tab-${tab}`;
      const idle={notes:st.notes,candidates:st.cands,health:st.health,knowledge:st.know}[tab];
      return idle&&idle.status==='idle'?load(tab):(render(),Promise.resolve());
    }

    /* ------------------------------------------------------------ rendu */
    const busy=()=>'<div class="wsp-loading" role="status"><span class="wsp-spin" aria-hidden="true"></span>Chargement…</div>';
    const errBox=(msg,retry)=>`<div class="notice bad" role="alert">${esc(msg)}${retry?`<div><button type="button" class="action small" data-act="${retry}">Réessayer</button></div>`:''}</div>`;
    const filterSelect=(id,name,value,options,all)=>`<label class="wsp-field"><span>${name}</span><select id="${id}" data-f="${id}">
      <option value="">${all}</option>${Object.entries(options).map(([k,v])=>`<option value="${esc(k)}"${value===k?' selected':''}>${esc(v)}</option>`).join('')}</select></label>`;

    function noteRow(n,derived){
      const on=st.notes.sel.id===n.id;
      return `<li><button type="button" class="mc-row${on?' on':''}" data-act="note" data-id="${esc(n.id)}" aria-current="${on}">
        <strong>${esc(n.title||n.id)}</strong>
        <span class="mc-meta"><span class="chip">${esc(n.level)}</span>${esc(label(RETENTIONS,n.retention))} · ${esc(label(KINDS,n.kind))}${n.superseded_by?' · <span class="wsp-warn">remplacée</span>':''}</span>
        <span class="hint">${esc(derived?n.snippet:n.excerpt)}</span></button></li>`;
    }
    function noteDetail(){
      const s=st.notes.sel;
      if(!s.id)return '<p class="wsp-empty" id="mcDetail" tabindex="-1">Choisissez une note pour voir son contenu canonique, sa provenance et sa version.</p>';
      if(s.status==='loading')return busy();
      if(s.status==='error')return `<div id="mcDetail" tabindex="-1">${errBox(s.error)}</div>`;
      const n=s.data;if(!n)return '';
      const link=id=>`<button type="button" class="action small" data-act="note" data-id="${esc(id)}">${esc(id)}</button>`;
      const rel=(title,ids)=>ids&&ids.length?`<dt>${title}</dt><dd>${ids.map(link).join(' ')}</dd>`:'';
      const conflicts=(n.contradicts&&n.contradicts.length)||n.superseded_by||(n.supersedes&&n.supersedes.length);
      return `<article id="mcDetail" tabindex="-1" aria-label="Note ${esc(n.title)}">
        <h3>${esc(n.title)}</h3>
        <p><span class="chip on">Canonique</span><span class="chip">Révision ${esc(n.revision)}</span>${n.superseded_by?'<span class="chip warn">Remplacée</span>':''}</p>
        ${dimensions(n)}
        <h4>Provenance</h4>${sourcesHtml(n.sources)}
        <h4>Version</h4><dl class="kv"><dt>Créée</dt><dd>${date(n.created_at)}</dd><dt>Modifiée</dt><dd>${date(n.updated_at)}</dd>
          <dt>Valide</dt><dd>${n.valid_from||n.valid_to?`${date(n.valid_from)} → ${n.valid_to?date(n.valid_to):'sans fin'}`:'sans limite'}</dd>
          <dt>Confiance</dt><dd>${n.confidence==null?'—':esc(n.confidence)}</dd><dt>Auteur</dt><dd>${esc(n.agent||'—')}</dd></dl>
        <h4>Conflits et liens</h4>${conflicts?`<dl class="kv">${rel('Contredit',n.contradicts)}${rel('Remplace',n.supersedes)}${n.superseded_by?rel('Remplacée par',[n.superseded_by]):''}</dl>`:'<p class="wsp-none">Aucun conflit ni remplacement.</p>'}
        <h4>Contenu canonique</h4><pre class="mc-body">${esc(n.body)}</pre></article>`;
    }
    function notesView(){
      const n=st.notes,rows=n.hits?n.hits.map(h=>noteRow(h,true)):n.items.map(i=>noteRow(i,false));
      const list=n.status==='loading'?busy():n.status==='error'?errBox(n.error,'reload'):
        rows.length?`<ul class="mc-rows">${rows.join('')}</ul>`:
        `<p class="wsp-empty">${n.q.trim()?'Aucune note ne correspond à cette recherche.':'Aucune note en mémoire pour l’instant. Elles apparaissent quand Jarvis retient quelque chose ou qu’un candidat est accepté.'}</p>`;
      return `<form class="wsp-bar" data-form="notes" role="search">
        <label class="wsp-field wsp-grow"><span>Rechercher</span><input id="mcQuery" type="search" value="${esc(n.q)}" placeholder="un mot, un nom, un sujet" autocomplete="off"></label>
        ${filterSelect('mcLevel','Abstraction',n.level,LEVELS,'Toutes')}${filterSelect('mcRetention','Rétention',n.retention,RETENTIONS,'Toutes')}
        ${n.hits?'':filterSelect('mcKind','Type',n.kind,KINDS,'Tous')}
        ${n.hits?'':`<label class="wsp-check"><input id="mcSuper" type="checkbox"${n.superseded?' checked':''}> Notes remplacées</label>`}
        <button type="submit" class="action">Afficher</button></form>
        ${n.hits?'<p class="hint"><span class="chip">Dérivé</span>Résultats de l’index par mots, classés par pertinence. Ouvrir une note affiche son contenu canonique.</p>'
          :'<p class="hint"><span class="chip on">Canonique</span>Notes lues dans la mémoire Markdown, les plus récentes d’abord.</p>'}
      <div class="mc-split"><div class="mc-col">${list}</div><div class="mc-col mc-detail">${noteDetail()}</div></div>`;
    }

    function candRow(c){
      const on=st.cands.sel.id===c.id;
      return `<li><button type="button" class="mc-row${on?' on':''}" data-act="cand" data-id="${esc(c.id)}" aria-current="${on}">
        <strong>${esc(c.title||c.id)}</strong>
        <span class="mc-meta"><span class="chip ${c.state==='proposed'?'warn':''}">${esc(label(CAND_STATES,c.state))}</span><span class="chip">${esc(c.level)}</span>${esc(label(RETENTIONS,c.retention))}${c.conflicts&&c.conflicts.length?` · <span class="wsp-warn">${c.conflicts.length} conflit(s)</span>`:''}</span>
        <span class="hint">${esc(c.excerpt)}</span></button></li>`;
    }
    function confirmBox(c){
      const k=c.confirm,d=c.sel.data;if(!k||!d||d.id!==k.id)return '';
      const accept=k.decision==='accept';
      return `<div class="notice ${accept?'info':'warn'} mc-confirm" role="alertdialog" aria-labelledby="mcConfirmTitle" aria-describedby="mcConfirmText">
        <strong id="mcConfirmTitle">${accept?'Accepter ce candidat ?':'Rejeter ce candidat ?'}</strong>
        <p id="mcConfirmText">${accept?`Une note canonique « ${esc(d.title)} » (${esc(d.level)}, ${esc(label(RETENTIONS,d.retention))}) sera créée dans la mémoire, avec la provenance ci-dessous. Elle pourra être rappelée par le cerveau.`
          :'Le candidat est marqué rejeté et ne sera pas rappelé. Aucune note n’est créée.'} La décision est enregistrée au nom du propriétaire.</p>
        <button type="button" class="action ${accept?'primary':''}" data-act="decide"${c.busy?' disabled':''}>${c.busy?'Envoi…':accept?'Confirmer l’acceptation':'Confirmer le rejet'}</button>
        <button type="button" class="action" id="mcConfirmCancel" data-act="cancel"${c.busy?' disabled':''}>Annuler</button></div>`;
    }
    function candDetail(){
      const c=st.cands,s=c.sel;
      if(!s.id)return '<p class="wsp-empty" id="mcDetail" tabindex="-1">Choisissez un candidat pour lire sa proposition et décider.</p>';
      if(s.status==='loading')return busy();
      if(s.status==='error')return `<div id="mcDetail" tabindex="-1">${errBox(s.error)}</div>`;
      const d=s.data;if(!d)return '';
      const msg=c.msg?`<div class="notice ${c.msg.tone}" role="${c.msg.tone==='bad'?'alert':'status'}">${esc(c.msg.text)}</div>`:'';
      const actions=d.state==='proposed'
        ?`<p class="mc-actions"><button type="button" class="action primary" data-act="cand-accept">Accepter…</button> <button type="button" class="action" data-act="cand-reject">Rejeter…</button></p>`
        :`<p class="hint">${esc(label(CAND_STATES,d.state))}${d.decided_by?` par ${esc(d.decided_by)} le ${date(d.decided_at)}`:''}${d.committed_memory_id?` · note <button type="button" class="action small" data-act="note-tab" data-id="${esc(d.committed_memory_id)}">${esc(d.committed_memory_id)}</button>`:''}</p>`;
      return `<article id="mcDetail" tabindex="-1" aria-label="Candidat ${esc(d.title)}">
        <h3>${esc(d.title)}</h3>
        <p><span class="chip warn">Proposition</span>${d.state==='proposed'?'Pas encore en mémoire : elle n’est pas rappelée.':esc(label(CAND_STATES,d.state))}<span class="chip">Confiance ${esc(d.confidence)}</span></p>
        ${msg}${dimensions(d)}
        <h4>Conflits détectés</h4>${d.conflicts&&d.conflicts.length?`<ul class="mc-list">${d.conflicts.map(x=>`<li><code>${esc(x)}</code></li>`).join('')}</ul><p class="hint">Rien n’est écrasé : accepter crée une nouvelle révision ou une nouvelle note.</p>`:'<p class="wsp-none">Aucun conflit détecté.</p>'}
        <h4>Provenance</h4>${sourcesHtml(d.sources)}
        <h4>Contenu proposé</h4><pre class="mc-body">${esc(d.body)}</pre>
        ${confirmBox(c)}${actions}</article>`;
    }
    function candsView(){
      const c=st.cands;
      const list=c.status==='loading'?busy():c.status==='error'?errBox(c.error,'reload'):!c.available
        ?'<div class="notice info">La consolidation n’est pas branchée dans cette installation : aucune proposition à relire.</div>'
        :c.items.length?`<ul class="mc-rows">${c.items.map(candRow).join('')}</ul>`
        :`<p class="wsp-empty">${c.filter==='proposed'?'Aucun candidat à décider. La consolidation en propose quand elle repère un souvenir durable.':'Aucun candidat dans cet état.'}</p>`;
      return `<div class="wsp-bar"><label class="wsp-field"><span>État</span><select id="mcCandState" data-f="mcCandState">
        ${Object.entries(CAND_STATES).map(([k,v])=>`<option value="${k}"${c.filter===k?' selected':''}>${esc(v)}</option>`).join('')}</select></label>
        <button type="button" class="action" data-act="reload">Actualiser</button></div>
        <p class="hint">Les candidats sont des propositions, pas de la mémoire : seule une acceptation crée une note canonique.</p>
        <div class="mc-split"><div class="mc-col">${list}</div><div class="mc-col mc-detail">${candDetail()}</div></div>`;
    }

    function legCard(name,leg){
      const [txt,tone]=STATUS[leg.status]||[leg.status,'off'];
      const explain=leg.status==='ok'?'':leg.status==='disabled'
        ?`<div class="hint">Coupé dans les réglages. ${esc(effectOf(name))}</div>`
        :`<div class="hint"><strong>Dégradé</strong> : ${esc(leg.reason||leg.reason_code||'raison inconnue')}${leg.reason_code?` (<code>${esc(leg.reason_code)}</code>)`:''}. ${esc(effectOf(name))}</div>`;
      return `<li><span class="mem-leg">${esc(label(LEG_LABEL,name))}</span><span class="mem-badge ${tone}">${esc(txt)}</span>${explain}</li>`;
    }
    const settingsLink='<button type="button" class="action small" data-act="settings">Ouvrir les réglages mémoire</button>';
    function healthView(){
      const h=st.health;
      if(h.status==='loading')return busy();
      if(h.status==='error')return errBox(h.error,'reload');
      const d=h.data;if(!d)return '';
      if(d.available===false)return `<div class="notice bad" role="status">La mémoire n’est pas disponible côté Core${d.reason_code?` (<code>${esc(d.reason_code)}</code>)`:''}. ${settingsLink}</div>`;
      const sync=d.index_ready===false?'<div class="notice warn mc-warn" role="status"><strong>Index en synchronisation.</strong> Les tours se passent de rappel (<code>index_syncing</code>) jusqu’à la fin ; les notes canoniques sont intactes.</div>':'';
      const recall=d.recall_enabled===false?'<div class="notice info" role="status">Le rappel dans les tours est coupé dans les réglages.</div>':'';
      const legs=Object.entries(d.legs||{});
      return `<p class="hint"><span class="chip">Dérivé</span>Ces index sont jetables : ils se reconstruisent depuis les notes Markdown, seules canoniques. Un index dégradé ne perd aucun souvenir.</p>
        ${sync}${recall}<ul class="mc-legs" aria-label="État des étages">${legs.map(([k,v])=>legCard(k,v)).join('')}</ul>
        <p>${settingsLink} <button type="button" class="action small" data-act="reload">Actualiser</button></p>`;
    }

    function knowledgeView(){
      const k=st.know;
      if(k.status==='loading')return busy();
      if(k.status==='error')return errBox(k.error,'reload');
      if(!k.legs)return '';
      const legs=Object.entries(k.legs).filter(([n])=>n.startsWith('knowledge:'));
      const loads=k.loadouts==null?'<p class="wsp-none">Règles de loadout illisibles pour le moment.</p>'
        :Object.keys(k.loadouts).length?`<ul class="mc-list">${Object.entries(k.loadouts).map(([a,r])=>`<li><code>${esc(a)}</code> <span class="hint">${(r.memory_scopes||[]).length} portée(s) mémoire${r.wiki===false?', sans wiki':''}${r.codegraph===false?', sans graphe':''}${r.skills===false?', sans skills':''}</span></li>`).join('')}</ul>`
        :'<p class="wsp-none">Aucune règle personnalisée : les préréglages par agent s’appliquent.</p>';
      return `<p class="hint"><span class="chip">Importé ou dérivé</span>Wiki, graphe de code et Skills enrichissent le cerveau mais ne sont jamais de la mémoire canonique. Lecture seule ici.</p>
        <ul class="mc-legs">${legs.length?legs.map(([n,l])=>legCard(n,l)).join(''):'<li class="wsp-none">Aucune source de connaissance déclarée par Core.</li>'}</ul>
        <h4>Loadouts par agent</h4>${loads}
        <p class="hint">Un loadout dit quelles portées de mémoire et quelles connaissances voit chaque agent. Il se règle dans le fichier de réglages.</p>
        <p>${settingsLink}</p>`;
    }

    function recallView(){
      const r=st.recall;
      let out='';
      if(r.status==='loading')out=busy();
      else if(r.status==='error')out=errBox(r.error);
      else if(r.data){
        const d=r.data,deg=(d.degraded||[]).map(c=>`<span class="chip warn" title="${esc(c)}">${esc(label(DEGRADED,c))}</span>`).join('');
        const t=Object.entries(d.timings_ms||{}).map(([k,v])=>`${esc(k)} ${esc(Math.round(v))} ms`).join(' · ');
        out=`<div id="mcRecallResult" tabindex="-1"><p class="hint"><span class="chip">Aperçu dérivé</span>Ce que le cerveau recevrait pour cette phrase, avec les mêmes budgets (${esc(d.budget.max_items)} éléments, ${esc(d.budget.item_chars)} caractères chacun). Rien n’est écrit ni injecté.</p>
          ${deg?`<p>${deg}</p>`:''}${t?`<p class="hint">Durées : ${t}</p>`:''}
          ${(d.items||[]).length?`<ol class="mc-rows">${d.items.map(i=>`<li class="mc-hit"><strong>${esc(i.title||i.id)}</strong>
            <span class="mc-meta"><span class="chip">${esc(i.level)}</span>${esc(label(RETENTIONS,i.retention))} · score ${esc(Number(i.score).toFixed(3))} · rév. ${esc(i.revision)}</span>
            <span class="mc-why"><strong>Pourquoi rappelée :</strong> ${esc(i.why||'—')}${i.rank_sources&&Object.keys(i.rank_sources).length?` · rang par étage ${Object.entries(i.rank_sources).map(([k,v])=>`<code>${esc(k)} ${esc(v)}</code>`).join(' ')}`:''}</span>
            <span class="hint">${esc(i.snippet)}</span><span class="hint">Source : <code>${esc(i.source)}</code></span>
            <button type="button" class="action small" data-act="note-tab" data-id="${esc(i.id)}">Voir la note canonique</button></li>`).join('')}</ol>`
            :'<p class="wsp-empty">Rien ne serait rappelé pour cette phrase.'+(deg?' Un étage dégradé peut l’expliquer (ci-dessus).':'')+'</p>'}</div>`;
      }
      return `<form class="wsp-bar" data-form="recall"><label class="wsp-field wsp-grow"><span>Phrase à tester</span><input id="mcRecallQ" type="text" value="${esc(r.q)}" placeholder="ce que vous diriez à Jarvis" autocomplete="off"></label>
        <label class="wsp-field"><span>Éléments</span><input id="mcRecallMax" type="number" min="1" max="10" value="${esc(r.max)}"></label>
        <button type="submit" class="action primary"${r.status==='loading'?' disabled':''}>Tester le rappel</button></form>${out}`;
    }

    function tabsHtml(){
      return TABS.map(([k,l])=>`<button type="button" role="tab" id="mc-tab-${k}" data-act="tab" data-tab="${k}" aria-selected="${st.tab===k}" aria-controls="mcPanel" tabindex="${st.tab===k?0:-1}">${esc(l)}</button>`).join('');
    }
    function panelHtml(){
      return {notes:notesView,candidates:candsView,health:healthView,knowledge:knowledgeView,recall:recallView}[st.tab]();
    }
    function render(){
      const active=host.ownerDocument&&host.ownerDocument.activeElement;
      host.innerHTML=`<div class="wsp-tabs" id="mcTabs" role="tablist" aria-label="Vues du Memory Center">${tabsHtml()}</div>
        <div class="wsp-panel mc-panel" id="mcPanel" role="tabpanel" aria-labelledby="mc-tab-${st.tab}" tabindex="-1">
        <p class="mc-bar"><button type="button" class="action small" data-act="back">← Sessions &amp; Boards</button></p>${panelHtml()}</div>
        <div class="sr" role="status" aria-live="polite">${esc(st.announce)}</div>`;
      host.setAttribute('data-memory-center','1');
      const target=st.focus&&host.querySelector&&host.querySelector(st.focus);st.focus=null;
      if(target&&target.focus)target.focus({preventScroll:false});else if(active&&active.id&&host.querySelector){const again=host.querySelector('#'+active.id);if(again&&again.focus)again.focus()}
    }

    /* ------------------------------------------------------------ événements */
    function act(name,data){
      data=data||{};
      switch(name){
        case 'tab':return setTab(data.tab);
        case 'reload':return load();
        case 'note':return openNote(data.id,false);
        case 'note-tab':return openNote(data.id,true).then(()=>{if(!st.notes.items.length&&st.notes.status==='idle')return loadNotes()});
        case 'cand':return openCand(data.id);
        case 'cand-accept':case 'cand-reject':return askDecision(st.cands.sel.id,name.slice(5));
        case 'cancel':return cancelDecision();
        case 'decide':return decide();
        case 'back':return opts.onBack&&opts.onBack();
        case 'settings':return opts.onSettings&&opts.onSettings();
        default:return undefined;
      }
    }
    function submit(form,fields){
      if(form==='notes'){
        const n=st.notes;n.q=fields.mcQuery||'';n.level=fields.mcLevel||'';n.retention=fields.mcRetention||'';n.kind=fields.mcKind||'';n.superseded=!!fields.mcSuper;
        return loadNotes();
      }
      if(form==='recall'){st.recall.q=fields.mcRecallQ||'';st.recall.max=Math.min(10,Math.max(1,parseInt(fields.mcRecallMax,10)||6));return runRecall()}
      return undefined;
    }
    function tabKey(key,index){
      if(key==='ArrowRight')return (index+1)%TABS.length;
      if(key==='ArrowLeft')return (index-1+TABS.length)%TABS.length;
      if(key==='Home')return 0;
      if(key==='End')return TABS.length-1;
      return null;
    }
    function bind(){
      host.addEventListener('click',ev=>{
        const t=ev.target.closest&&ev.target.closest('[data-act]');
        if(!t||t.disabled)return;
        act(t.dataset.act,{...t.dataset});
      });
      host.addEventListener('submit',ev=>{
        const f=ev.target.closest&&ev.target.closest('form[data-form]');if(!f)return;
        ev.preventDefault();
        const out={};for(const x of f.querySelectorAll('input[id],select[id]'))out[x.id]=x.type==='checkbox'?x.checked:x.value;
        submit(f.dataset.form,out);
      });
      host.addEventListener('change',ev=>{
        const t=ev.target;
        if(t.id==='mcCandState'){st.cands.filter=t.value;st.cands.sel={id:null,status:'idle',data:null,error:''};st.cands.confirm=null;loadCands()}
      });
      host.addEventListener('keydown',ev=>{
        const t=ev.target.closest&&ev.target.closest('[role="tab"]');if(!t)return;
        const tabs=[...host.querySelectorAll('[role="tab"]')],next=tabKey(ev.key,tabs.indexOf(t));
        if(next===null)return;
        ev.preventDefault();act('tab',{tab:tabs[next].dataset.tab});
      });
    }
    if(host.addEventListener)bind();
    render();
    /* Échap ferme d'abord la confirmation ouverte (vrai si elle l'était), la vue ensuite. */
    const dismiss=()=>{if(!st.cands.confirm||st.cands.busy)return false;cancelDecision();return true};
    return {load,render,state:st,act,submit,setTab,tabKey,openNote,decide,runRecall,dismiss};
  }

  /* ------------------------------------------------------------ montage dans « Sessions & Boards » */
  const view={instance:null,observer:null};
  function workspaceRoot(){return root.document?root.document.getElementById('workspaceManager'):null}
  function leave(){
    const ws=workspaceRoot(),mount=root.document&&root.document.getElementById(MOUNT_ID);
    if(ws){ws.classList.remove('mc-on');const t=ws.querySelector('.tl-tt');if(t&&view.title)t.textContent=view.title}
    if(mount)mount.hidden=true;
  }
  function open(){
    const doc=root.document,ws=workspaceRoot(),mount=doc&&doc.getElementById(MOUNT_ID);
    if(!ws||!mount||!root.JarvisWorkspace)return false;
    if(typeof root.closeSettings==='function'){try{root.closeSettings()}catch{}}
    if(ws.hidden)root.JarvisWorkspace.open();
    const title=ws.querySelector('.tl-tt');
    if(title){if(!view.title)view.title=title.textContent;title.textContent='Memory Center'}
    ws.classList.add('mc-on');mount.hidden=false;
    if(!view.instance){
      view.instance=create(mount,{
        onBack(){leave();const tab=doc.getElementById('wsp-tab-overview')||doc.querySelector('#wspTabs [role="tab"]');if(tab)tab.focus()},
        onSettings(){
          root.JarvisWorkspace.close();
          Promise.resolve(typeof root.openSettings==='function'?root.openSettings():null).then(()=>{if(typeof root.selectTab==='function')root.selectTab('memory')});
        }});
    }
    if(!view.esc){
      view.esc=ev=>{if(ev.key==='Escape'&&!ws.hidden&&ws.classList.contains('mc-on')&&view.instance&&view.instance.dismiss()){ev.preventDefault();ev.stopImmediatePropagation()}};
      root.addEventListener('keydown',view.esc,true);
    }
    if(!view.observer&&root.MutationObserver){
      view.observer=new root.MutationObserver(()=>{if(ws.hidden)leave()});
      view.observer.observe(ws,{attributes:true,attributeFilter:['hidden']});
    }
    view.instance.load();
    const tab=doc.getElementById('mc-tab-'+view.instance.state.tab);if(tab)tab.focus();
    return true;
  }

  const entry=root.document&&root.document.getElementById('wspMemoryCenter');
  if(entry)entry.addEventListener('click',open);

  root.JarvisMemoryCenter=Object.freeze({mountId:MOUNT_ID,mount:()=>root.document?root.document.getElementById(MOUNT_ID):null,
    create,open,close:leave,LEVELS,RETENTIONS,KINDS,TABS});
})(typeof window!=='undefined'?window:globalThis);
