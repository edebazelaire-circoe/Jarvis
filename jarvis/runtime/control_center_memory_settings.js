/* Réglages mémoire du Control Center (jarvis-memory-intelligence-knowledge, Slice 11 ; rangés en sections par
   jarvis-settings-ui-reorganization, Slice 05 — `docs/settings/memory.md`).

   Rend la section `memory` de la lecture des réglages (`schema`, `values`, `effective`, `downgraded`, `secrets`,
   `loadouts`, `status`) et écrit un correctif `{memory: {...}}` par la même route. Aucune borne, aucune liste
   d'options, aucun libellé de champ, aucune destination n'est copié ici : tout vient du schéma serveur, et chaque
   champ dit lui-même la section de Réglages qui l'édite (`surface.section`). Jamais de secret : seulement `has_secret`.

   Trois vues d'un même état partagé (`createStore`, un par ouverture des Réglages) :
   - `fields` : les champs d'UNE section (`options.section`), avec une ligne d'état courte et le lien vers le diagnostic ;
   - `center` : l'entrée du Memory Center ;
   - `diagnostics` : l'état détaillé des étages et des valeurs coupées (partie « Mémoire » d'Avancé › Diagnostics).
   Le brouillon vit dans l'état partagé : il survit au passage d'une section mémoire à l'autre (une règle de
   compatibilité peut ramener un champ d'une autre section), et « Enregistrer la mémoire » envoie tout le brouillon.
   Une vue détruite (`destroy`) ne dessine plus rien et ignore les réponses tardives. */
(function(root){
  'use strict';
  const MOUNT_ID='memorySettingsMount';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const STATUS={ok:['Actif','ok'],disabled:['Désactivé','info'],unavailable:['Indisponible','bad']};
  const LEG_LABEL={lexical:'Recherche par mots',recall:'Rappel dans le tour',semantic:'Recherche sémantique',tencent:'Sidecar Tencent',
    'knowledge:wiki':'Wiki','knowledge:codegraph':'Graphe de code','knowledge:skills':'Skills'};
  const SECRET_HINT={semantic:'Clé du fournisseur',tencent:'Jeton du sidecar'};
  const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);

  /* Étages d'une section du bloc : le sien (`recall`, `semantic`, `tencent`), ou ses `knowledge:*`. */
  function legsOf(legs,sectionId){return Object.keys(legs).filter(k=>k===sectionId||k.startsWith(sectionId+':'))}
  function fields(schema){return (schema.sections||[]).flatMap(s=>s.fields.map(f=>({...f,section:s.id})))}
  /* `views` : le dessin de chaque vue vivante du store. Une lecture ou un enregistrement redessine toutes les vues à sa
     fin : la section qui l'a lancé a pu être quittée entre-temps, celle qui est affichée doit refléter le résultat. */
  function createStore(){return {memory:null,draft:{},busy:false,message:null,restart:false,loading:null,views:new Set()}}

  /* Primitives du shell (`JarvisSettingsUI`) : celles passées par la page, sinon celles de la page. */
  function primitives(opts){
    const ui=opts.ui||root.JarvisSettingsUI;
    if(!ui)throw new Error('JarvisSettingsUI absent : les réglages mémoire se dessinent avec les primitives du shell.');
    return ui;
  }

  function create(host,options){
    const opts=options||{};
    const ui=primitives(opts);
    const mode=opts.mode||'fields';
    const fetchJson=opts.fetch||(async(path,init)=>{
      const r=await root.fetch(path,init),text=await r.text();let body={};try{body=text?JSON.parse(text):{}}catch{body={error:text}}
      if(!r.ok){const e=new Error(body.error||body.message||('HTTP '+r.status));e.code=r.headers.get('X-Settings-Error-Code')||r.headers.get('X-Jarvis-Error-Code')||'';throw e}
      return body;
    });
    const st=opts.store||createStore();
    if(!st.views)st.views=new Set();
    /* Le message et l'avis d'après-enregistrement disent ce qui vient d'arriver : une vue montée plus tard ne les reprend
       pas, sauf si l'enregistrement est encore en cours (elle en recevra l'issue). */
    if(!st.busy){st.message=null;st.restart=false}
    let dead=false;

    const stored=p=>st.memory.values[p];
    const current=p=>own(st.draft,p)?st.draft[p]:stored(p);
    const dirty=()=>Object.keys(st.draft).length>0;
    const field=p=>fields(st.memory.schema).find(f=>f.path===p);
    const restartHit=()=>(st.memory.status.restart_required||[]).filter(p=>own(st.draft,p));
    const inSection=f=>!!f.surface&&f.surface.section===opts.section;

    /* Ce que le brouillon rend impossible : l'interrupteur reste éteint et dit pourquoi. */
    function blocked(f){
      if(f.path==='semantic.enabled'&&current('semantic.provider')==='none')return 'Choisissez d’abord un fournisseur d’embeddings.';
      if(f.path==='tencent.enabled'&&!String(current('tencent.url')||'').trim())return 'Renseignez d’abord l’URL du sidecar.';
      return '';
    }
    function blockedOption(f,opt){
      if(f.path==='consolidation.mode'&&opt.id==='auto'&&!current('semantic.enabled'))return 'exige la recherche sémantique';
      return '';
    }

    function legBadge(leg){const [txt,tone]=STATUS[leg.status]||[leg.status,'info'];return ui.badge(tone,txt)}
    function problems(){
      const legs=st.memory.status.legs||{},down=Object.values(st.memory.status.downgraded||{});
      return Object.keys(legs).filter(k=>legs[k].status==='unavailable'||down.includes(legs[k].reason_code)).length
        +down.filter(c=>!Object.values(legs).some(l=>l.reason_code===c)).length;
    }
    /* Ligne d'état courte de la page ordinaire : le détail vit dans Avancé › Diagnostics. */
    function statusLine(legKeys){
      const legs=st.memory.status.legs||{},n=problems();
      const marks=legKeys.map(k=>`<span class="mem-leg-mark">${esc(LEG_LABEL[k]||k)} ${legBadge(legs[k])}</span>`).join('');
      const text=n?`${n} point${n>1?'s':''} à vérifier dans la mémoire.`:'Aucun problème détecté dans la mémoire.';
      return `<div class="mem-status">${marks}<span class="mem-status-text${n?' bad':''}">${esc(text)}</span>`
        +`<button type="button" class="linkish" data-mem-diagnostics>Voir le diagnostic mémoire</button></div>`;
    }

    function control(f){
      const id='mem_'+f.path.replace(/\./g,'_'),v=current(f.path),eff=(st.memory.effective||{})[f.path]||{},env=eff.source==='env';
      const dis=env||st.busy?' disabled':'';
      const why=blocked(f);
      const hint=`${f.help||''}${env?' Valeur imposée par l’environnement ('+f.env+') : modifiez-la là.':''}${why&&!v?' '+why:''}`;
      const effNote=eff.downgraded&&!env?` <span class="tag">effectif : ${esc(String(eff.value))}</span>`:'';
      const described=` aria-describedby="${id}-hint"`;
      let input;
      if(f.type==='bool'){
        const off=!v&&why?' disabled':'';
        input=`<input type="checkbox" id="${id}" data-mem="${esc(f.path)}"${v?' checked':''}${dis}${off}${described}>${effNote}`;
        return ui.field({id,label:f.label,hint,inline:true,control:input});
      }
      if(f.type==='enum'){
        const opt=f.options.map(o=>{const b=blockedOption(f,o),x=b&&o.id!==v;return `<option value="${esc(o.id)}"${o.id===v?' selected':''}${x?' disabled':''}>${esc(o.label)}${x?' ('+esc(b)+')':''}</option>`}).join('');
        input=`<select id="${id}" data-mem="${esc(f.path)}"${dis}${described}>${opt}</select>${effNote}`;
      }else if(f.type==='int'||f.type==='float'){
        const step=f.type==='float'?'0.05':'1';
        input=`<span class="mem-number"><input id="${id}" type="number" inputmode="decimal" min="${esc(f.min)}" max="${esc(f.max)}" step="${step}" value="${esc(v)}" data-mem="${esc(f.path)}"${dis}${described}><span class="tag">${esc(f.min)} à ${esc(f.max)}</span></span>`;
      }else{
        input=`<input id="${id}" type="${f.type==='text'?'url':'text'}" maxlength="${esc(f.max_length||512)}" value="${esc(v||'')}" autocomplete="off" spellcheck="false" data-mem="${esc(f.path)}"${dis}${described}>`;
      }
      return ui.field({id,label:f.label,hint,control:input});
    }

    function secretLine(sectionId){
      const s=(st.memory.secrets||{})[sectionId];if(!s)return '';
      return `<p class="hint mem-secret">${esc(SECRET_HINT[sectionId]||'Clé')} : <strong>${s.has_secret?'présent':'absent'}</strong>. Il se règle dans `
        +`<button type="button" class="linkish" data-mem-open="providers">Plugins & MCP › Fournisseurs</button>, jamais ici.</p>`;
    }
    /* Moment d'application d'un groupe de champs, lu dans `restart_required` du serveur ; `null` si le groupe mélange. */
    function applies(list){
      const restart=st.memory.status.restart_required||[],hits=list.filter(f=>restart.includes(f.path)).length;
      return hits===0?'next_turn':hits===list.length?'next_core_start':null;
    }
    function loadoutsHtml(){
      const rules=Object.entries(st.memory.loadouts||{});
      const body=rules.length?`<ul class="mem-legs">${rules.map(([k,r])=>`<li><code>${esc(k)}</code><span class="hint">${(r.memory_scopes||[]).length} scope(s)${r.wiki===false?', sans wiki':''}${r.codegraph===false?', sans graphe':''}${r.skills===false?', sans skills':''}</span></li>`).join('')}</ul>`
        :'<p class="hint">Aucune règle : les préréglages par agent s’appliquent.</p>';
      return `<div class="mem-group" data-mem-loadouts><h4>Connaissances par agent</h4>${body}<p class="hint">Lecture seule ici ; les règles se définissent dans le fichier de réglages.</p></div>`;
    }
    function restartHtml(){
      const need=restartHit();
      const after=st.restart?ui.notice({kind:'ok',live:'polite',text:'Enregistré. La recherche sémantique et le sidecar ne s’appliquent qu’au prochain démarrage de Core ; le rappel, les budgets et les connaissances dès le prochain tour.'}):'';
      const pending=need.length?ui.notice({kind:'info',live:'polite',body:`<span class="set-notice-text">Redémarrage de Core nécessaire pour : ${need.map(p=>`<code>${esc((field(p)||{}).label||p)}</code>`).join(', ')}.</span>`}):'';
      return after+pending;
    }
    /* Le brouillon est commun aux sections mémoire : on dit ce qu'il porte ailleurs, puisque l'enregistrement l'envoie. */
    function elsewhereHtml(){
      const other=Object.keys(st.draft).map(field).filter(f=>f&&!inSection(f));
      return other.length?`<p class="hint mem-elsewhere">Enregistre aussi les changements en attente dans d’autres sections : ${other.map(f=>`<code>${esc(f.label)}</code>`).join(', ')}.</p>`:'';
    }
    function messageHtml(){
      if(!st.message)return '';
      return ui.notice({kind:st.message.tone,live:st.message.tone==='bad'?'assertive':'polite',text:st.message.text});
    }
    /* `aria-disabled` plutôt que `disabled` : un bouton désactivé perd le focus, qui tomberait sur `body` pendant et
       après l'enregistrement (finitions avant la Slice 10). Les écoutes refusent le clic tant qu'il ne sert à rien. */
    function actionsHtml(){
      const off=dirty()&&!st.busy?'':' aria-disabled="true"';
      return ui.actions(`<button type="button" class="action primary" data-mem-save${off}>${st.busy?'Enregistrement…':'Enregistrer la mémoire'}</button>`
        +`<button type="button" class="action" data-mem-reset${off}>Annuler les changements</button>`);
    }

    function fieldsHtml(){
      const groups=(st.memory.schema.sections||[]).map(s=>({s,list:s.fields.filter(inSection)})).filter(g=>g.list.length);
      const legs=st.memory.status.legs||{};
      const single=groups.length===1;
      const body=groups.map(({s,list})=>{
        const inner=list.map(control).join('')+secretLine(s.id);
        if(single)return inner;
        const when=applies(list),badge=legs[s.id]?' '+legBadge(legs[s.id]):'';
        return `<div class="mem-group"><h4>${esc(s.label)}${badge}${when?' '+ui.appliesBadge(when):''}</h4>${inner}</div>`;
      }).join('');
      const loadouts=(st.memory.schema.loadouts||{}).surface;
      const when=single?applies(groups[0].list):null;
      return ui.section({id:`memSection_${opts.section}`,title:opts.label||opts.section,description:opts.description||'',
        applies:when||undefined,
        body:statusLine(groups.flatMap(g=>legsOf(legs,g.s.id)))+body+(loadouts&&loadouts.section===opts.section?loadoutsHtml():'')
          +restartHtml()+messageHtml()+elsewhereHtml()+actionsHtml()});
    }
    function centerHtml(){
      const center=!!(root.JarvisMemoryCenter&&typeof root.JarvisMemoryCenter.open==='function');
      return ui.section({id:'memSection_center',title:opts.label||'Memory Center',description:opts.description||'',
        body:statusLine([])+ui.actions(`<button type="button" class="action primary" data-mem-center${center?'':' disabled aria-disabled="true"'}>Ouvrir le Memory Center</button>`)
          +`<p class="hint">${center?'Notes, candidats à décider, santé des index, connaissances et test de rappel. Les Réglages se ferment à l’ouverture.':'Le Memory Center n’est pas encore disponible dans cette version.'}</p>`});
    }
    /* Partie « Mémoire » des diagnostics : chaque étage, ce qui le dégrade et comment le réparer, les combinaisons
       coupées à la lecture, et les valeurs imposées par l'environnement. Lecture seule. */
    function diagnosticsHtml(){
      const legs=st.memory.status.legs||{},down=Object.entries(st.memory.status.downgraded||{});
      const items=Object.keys(legs).map(k=>`<li><span class="mem-leg">${esc(LEG_LABEL[k]||k)}</span>${legBadge(legs[k])}</li>`).join('');
      const notes=Object.keys(legs).filter(k=>legs[k].status==='unavailable'||down.some(([,c])=>c===legs[k].reason_code))
        .map(k=>ui.notice({kind:'bad',title:LEG_LABEL[k]||k,body:`<span class="set-notice-text">${esc(legs[k].reason)} <code>${esc(legs[k].reason_code)}</code></span>${legs[k].how_to_fix?`<span class="hint">${esc(legs[k].how_to_fix)}</span>`:''}`})).join('');
      const rest=down.filter(([,c])=>!Object.keys(legs).some(k=>legs[k].reason_code===c))
        .map(([p,c])=>ui.notice({kind:'bad',body:`<span class="set-notice-text"><code>${esc(p)}</code> : combinaison incohérente dans le fichier, coupée à la lecture (${esc(c)}).</span>`})).join('');
      const env=fields(st.memory.schema).filter(f=>((st.memory.effective||{})[f.path]||{}).source==='env');
      const envHtml=env.length?`<p class="hint">Valeurs imposées par l’environnement : ${env.map(f=>`<code>${esc(f.env)}</code> (${esc(f.label)})`).join(', ')}.</p>`:'';
      return `<ul class="mem-legs" aria-label="État des étages mémoire">${items}</ul>${notes}${rest}${envHtml}
        <p class="hint">État déduit des réglages, sans appel réseau. L’état en direct (sidecar injoignable, index en synchronisation) est dans le Memory Center, onglet Santé des index. La mémoire canonique (notes Markdown) reste utilisable même si tous les étages optionnels sont coupés.</p>`;
    }

    /* Chaque rendu remplace la vue : le contrôle qui avait le focus le reprend (`keepFocus` du shell). */
    function render(){
      if(dead)return;
      if(!st.memory){host.innerHTML='<div class="empty">Chargement…</div>';return}
      const draw=()=>{host.innerHTML=`<div class="mem-settings">${mode==='center'?centerHtml():mode==='diagnostics'?diagnosticsHtml():fieldsHtml()}</div>`;bind()};
      if(typeof ui.keepFocus==='function')ui.keepFocus(host,draw);else draw();
    }
    function coerce(el,f){
      if(f.type==='bool')return el.checked;
      if(f.type==='int'||f.type==='float'){if(el.value.trim()==='')return stored(f.path);const n=Number(el.value);return f.type==='int'?Math.trunc(n):n}
      return f.type==='text'||f.type==='id'?el.value.trim():el.value;
    }
    function set(p,v){if(v===stored(p))delete st.draft[p];else st.draft[p]=v}
    function bind(){
      host.querySelectorAll('[data-mem]').forEach(el=>el.addEventListener('change',()=>{
        const f=field(el.dataset.mem);set(f.path,coerce(el,f));
        st.message=null;st.restart=false;
        /* Un choix qui rend un autre réglage incohérent le ramène à l'état sûr (même dans une autre section). */
        if(current('semantic.provider')==='none'&&current('semantic.enabled'))set('semantic.enabled',false);
        if(!current('semantic.enabled')&&current('consolidation.mode')==='auto')set('consolidation.mode','manual');
        if(!String(current('tencent.url')||'').trim()&&current('tencent.enabled'))set('tencent.enabled',false);
        const id=el.id;render();const again=id&&host.querySelector('#'+id);if(again&&again.focus&&!(again.ownerDocument&&again===again.ownerDocument.activeElement))again.focus();
      }));
      const on=(sel,fn)=>host.querySelectorAll(sel).forEach(el=>el.addEventListener('click',()=>fn(el)));
      on('[data-mem-save]',()=>submit());
      on('[data-mem-reset]',()=>{if(!dirty()||st.busy)return;st.draft={};st.message=null;render()});
      on('[data-mem-center]',()=>{if(root.JarvisMemoryCenter&&root.JarvisMemoryCenter.open)root.JarvisMemoryCenter.open()});
      on('[data-mem-diagnostics]',()=>{if(opts.openDiagnostics)opts.openDiagnostics()});
      on('[data-mem-open]',el=>{if(opts.open)opts.open(el.dataset.memOpen)});
    }

    /* Correctif à plat -> imbriqué : `{recall:{enabled:false}}`. Seuls les champs modifiés partent. */
    function patch(){
      const out={};
      for(const [p,v] of Object.entries(st.draft)){const [s,n]=p.split('.');(out[s]=out[s]||{})[n]=v}
      return out;
    }
    /* Une lecture par état partagé : une vue montée pendant la lecture attend la même réponse. */
    async function load(){
      if(!st.memory){
        if(!st.loading){
          st.loading=fetchJson('/api/settings').then(data=>{st.memory=data.memory;st.draft={};return st.memory})
            .finally(()=>{st.loading=null;renderAll()});
        }
        const pending=st.loading;
        render();
        await pending;
      }
      render();return st.memory;
    }
    async function submit(){
      if(!dirty()||st.busy)return;
      const needed=restartHit().length>0;
      st.busy=true;st.message=null;render();
      try{
        const data=await fetchJson('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({memory:patch()})});
        st.memory=data.memory;st.draft={};st.restart=needed;st.message={tone:'ok',text:'Réglages mémoire enregistrés.'};
      }catch(e){
        st.message={tone:'bad',text:(e.message||'Enregistrement refusé.')+(e.code?' ('+e.code+')':'')+' Rien n’a été écrit.'};
      }finally{st.busy=false;renderAll()}
    }
    function renderAll(){[...st.views].forEach(draw=>draw())}
    function destroy(){dead=true;st.views.delete(render)}
    host.setAttribute('data-memory-settings','1');
    st.views.add(render);
    render();
    return {load,render,state:st,patch,submit,destroy,get destroyed(){return dead}};
  }

  root.JarvisMemorySettings=Object.freeze({mountId:MOUNT_ID,mount:()=>root.document?root.document.getElementById(MOUNT_ID):null,
    create,createStore});
})(typeof window!=='undefined'?window:globalThis);
