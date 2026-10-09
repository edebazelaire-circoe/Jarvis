/* Réglages mémoire du Control Center (jarvis-memory-intelligence-knowledge, Slice 11).

   Rend la section `memory` de `GET /api/settings` (`schema`, `values`, `effective`, `downgraded`, `secrets`,
   `loadouts`, `status`) et écrit un correctif `{memory: {...}}` via `POST /api/settings`. Aucune borne, aucune
   liste d'options, aucun libellé de champ n'est copié ici : tout vient du schéma serveur. Jamais de secret :
   seulement `has_secret`. Point de montage : `#memorySettingsMount` (créé par l'onglet Mémoire). */
(function(root){
  'use strict';
  const MOUNT_ID='memorySettingsMount';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const STATUS={ok:['Actif','ok'],disabled:['Désactivé','off'],unavailable:['Indisponible','bad']};
  const LEG_LABEL={lexical:'Recherche par mots',recall:'Rappel dans le tour',semantic:'Recherche sémantique',tencent:'Sidecar Tencent',
    'knowledge:wiki':'Wiki','knowledge:codegraph':'Graphe de code','knowledge:skills':'Skills'};
  const SECTION_LEG={recall:'recall',semantic:'semantic',tencent:'tencent'};
  const SECRET_HINT={semantic:'clé du fournisseur',tencent:'jeton du sidecar'};

  function fields(schema){return (schema.sections||[]).flatMap(s=>s.fields.map(f=>({...f,section:s.id})))}

  function create(host,options){
    const opts=options||{};
    const fetchJson=opts.fetch||(async(path,init)=>{
      const r=await root.fetch(path,init),text=await r.text();let body={};try{body=text?JSON.parse(text):{}}catch{body={error:text}}
      if(!r.ok){const e=new Error(body.error||body.message||('HTTP '+r.status));e.code=r.headers.get('X-Settings-Error-Code')||r.headers.get('X-Jarvis-Error-Code')||'';throw e}
      return body;
    });
    const st={memory:null,draft:{},busy:false,message:null,restart:false};

    const stored=p=>st.memory.values[p];
    const current=p=>Object.prototype.hasOwnProperty.call(st.draft,p)?st.draft[p]:stored(p);
    const dirty=()=>Object.keys(st.draft).length>0;
    const field=p=>fields(st.memory.schema).find(f=>f.path===p);
    const restartHit=()=>(st.memory.status.restart_required||[]).filter(p=>Object.prototype.hasOwnProperty.call(st.draft,p));

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

    function legBadge(leg){
      const [txt,tone]=STATUS[leg.status]||[leg.status,'off'];
      return `<span class="mem-badge ${tone}">${esc(txt)}</span>`;
    }
    function summary(){
      const legs=st.memory.status.legs||{};
      const down=Object.entries(st.memory.status.downgraded||{});
      const items=Object.keys(legs).map(k=>`<li><span class="mem-leg">${esc(LEG_LABEL[k]||k)}</span>${legBadge(legs[k])}</li>`).join('');
      const notes=Object.keys(legs).filter(k=>legs[k].status==='unavailable'||down.some(([,c])=>c===legs[k].reason_code))
        .map(k=>`<div class="notice bad" role="status"><strong>${esc(LEG_LABEL[k]||k)}</strong> : ${esc(legs[k].reason)}${legs[k].how_to_fix?`<div class="hint">${esc(legs[k].how_to_fix)}</div>`:''}</div>`).join('');
      const rest=down.filter(([,c])=>!Object.keys(legs).some(k=>legs[k].reason_code===c))
        .map(([p,c])=>`<div class="notice bad" role="status"><code>${esc(p)}</code> : combinaison incohérente dans le fichier, coupée à la lecture (${esc(c)}).</div>`).join('');
      return `<h3>État actuel</h3><ul class="mem-legs" aria-label="État des étages mémoire">${items}</ul>${notes}${rest}
        <div class="hint">La mémoire canonique (notes Markdown) reste utilisable même si tous les étages optionnels sont coupés.</div>`;
    }

    function control(f){
      const id='mem_'+f.path.replace(/\./g,'_'),v=current(f.path),eff=(st.memory.effective||{})[f.path]||{},env=eff.source==='env';
      const dis=env||st.busy?' disabled':'';
      const why=blocked(f);
      const help=`<span class="hint" id="${id}_h">${esc(f.help||'')}${env?' Valeur imposée par l’environnement ('+esc(f.env)+') : modifiez-la là.':''}${why&&!v?' '+esc(why):''}</span>`;
      const effNote=eff.downgraded&&!env?` <span class="tag">effectif : ${esc(String(eff.value))}</span>`:'';
      if(f.type==='bool'){
        const off=!v&&why?' disabled':'';
        return `<div class="field inline mem-field"><input type="checkbox" id="${id}" data-mem="${esc(f.path)}"${v?' checked':''}${dis}${off} aria-describedby="${id}_h"><label for="${id}">${esc(f.label)}${effNote}</label>${help}</div>`;
      }
      if(f.type==='enum'){
        const opt=f.options.map(o=>{const b=blockedOption(f,o),x=b&&o.id!==v;return `<option value="${esc(o.id)}"${o.id===v?' selected':''}${x?' disabled':''}>${esc(o.label)}${x?' ('+esc(b)+')':''}</option>`}).join('');
        return `<div class="field mem-field"><label for="${id}">${esc(f.label)}${effNote}</label><select id="${id}" data-mem="${esc(f.path)}"${dis} aria-describedby="${id}_h">${opt}</select>${help}</div>`;
      }
      if(f.type==='int'||f.type==='float'){
        const step=f.type==='float'?'0.05':'1';
        return `<div class="field mem-field"><label for="${id}">${esc(f.label)} <span class="tag">${esc(f.min)} à ${esc(f.max)}</span></label><input id="${id}" type="number" inputmode="decimal" min="${esc(f.min)}" max="${esc(f.max)}" step="${step}" value="${esc(v)}" data-mem="${esc(f.path)}"${dis} aria-describedby="${id}_h">${help}</div>`;
      }
      return `<div class="field mem-field"><label for="${id}">${esc(f.label)}</label><input id="${id}" type="${f.type==='text'?'url':'text'}" maxlength="${esc(f.max_length||512)}" value="${esc(v||'')}" autocomplete="off" spellcheck="false" data-mem="${esc(f.path)}"${dis} aria-describedby="${id}_h">${help}</div>`;
    }

    function secretLine(section){
      const s=(st.memory.secrets||{})[section];if(!s)return '';
      return `<div class="hint mem-secret">${esc(SECRET_HINT[section]||'clé')} : <strong>${s.has_secret?'présent':'absent'}</strong>. Il se règle dans l’onglet API Keys, jamais ici.</div>`;
    }
    function sectionHtml(sec){
      const leg=(st.memory.status.legs||{})[SECTION_LEG[sec.id]];
      return `<section class="mem-section" aria-label="${esc(sec.label)}"><h3>${esc(sec.label)}${leg?' '+legBadge(leg):''}</h3>${sec.fields.map(control).join('')}${secretLine(sec.id)}</section>`;
    }
    function restartHtml(){
      const need=restartHit();
      const after=st.restart?'<div class="notice" role="status">Enregistré. La recherche sémantique et le sidecar ne s’appliquent qu’au prochain démarrage de Core ; le rappel, les budgets et les connaissances dès le prochain tour.</div>':'';
      const pending=need.length?`<div class="notice info" role="status">Redémarrage de Core nécessaire pour : ${need.map(p=>`<code>${esc((field(p)||{}).label||p)}</code>`).join(', ')}.</div>`:'';
      return after+pending;
    }
    function loadoutsHtml(){
      const rules=Object.entries(st.memory.loadouts||{});
      const body=rules.length?`<ul class="mem-legs">${rules.map(([k,r])=>`<li><code>${esc(k)}</code><span class="hint">${(r.memory_scopes||[]).length} scope(s)${r.wiki===false?', sans wiki':''}${r.codegraph===false?', sans graphe':''}${r.skills===false?', sans skills':''}</span></li>`).join('')}</ul>`
        :'<div class="hint">Aucune règle : les préréglages par agent s’appliquent.</div>';
      return `<section class="mem-section"><h3>Connaissances par agent</h3>${body}<div class="hint">Lecture seule ici ; les règles se définissent dans le fichier de réglages.</div></section>`;
    }
    function messageHtml(){
      if(!st.message)return '';
      return `<div class="notice ${st.message.tone}" role="${st.message.tone==='bad'?'alert':'status'}">${esc(st.message.text)}</div>`;
    }
    function render(){
      if(!st.memory){host.innerHTML='<div class="empty">Chargement…</div>';return}
      const center=!!(root.JarvisMemoryCenter&&typeof root.JarvisMemoryCenter.open==='function');
      host.innerHTML=`<div class="mem-settings">
        ${summary()}
        <p><button type="button" class="action" data-mem-center${center?'':' disabled aria-disabled="true"'}>Ouvrir le Memory Center</button>
        <span class="hint">${center?'Explorer les notes, les rappels et les candidats.':'Le Memory Center n’est pas encore disponible dans cette version.'}</span></p>
        ${(st.memory.schema.sections||[]).map(sectionHtml).join('')}
        ${loadoutsHtml()}
        ${restartHtml()}${messageHtml()}
        <div class="mem-actions"><button type="button" class="action primary" data-mem-save${dirty()&&!st.busy?'':' disabled'}>${st.busy?'Enregistrement…':'Enregistrer la mémoire'}</button>
        <button type="button" class="action" data-mem-reset${dirty()&&!st.busy?'':' disabled'}>Annuler les changements</button></div></div>`;
      bind();
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
        /* Un choix qui rend un autre réglage incohérent le ramène à l'état sûr. */
        if(current('semantic.provider')==='none'&&current('semantic.enabled'))set('semantic.enabled',false);
        if(!current('semantic.enabled')&&current('consolidation.mode')==='auto')set('consolidation.mode','manual');
        if(!String(current('tencent.url')||'').trim()&&current('tencent.enabled'))set('tencent.enabled',false);
        const id=el.id;render();const again=id&&host.querySelector('#'+id);if(again&&again.focus)again.focus();
      }));
      const save=host.querySelector('[data-mem-save]'),reset=host.querySelector('[data-mem-reset]'),center=host.querySelector('[data-mem-center]');
      if(save)save.addEventListener('click',()=>submit());
      if(reset)reset.addEventListener('click',()=>{st.draft={};st.message=null;render()});
      if(center)center.addEventListener('click',()=>{if(root.JarvisMemoryCenter&&root.JarvisMemoryCenter.open)root.JarvisMemoryCenter.open()});
    }

    /* Correctif à plat -> imbriqué : `{recall:{enabled:false}}`. Seuls les champs modifiés partent. */
    function patch(){
      const out={};
      for(const [p,v] of Object.entries(st.draft)){const [s,n]=p.split('.');(out[s]=out[s]||{})[n]=v}
      return out;
    }
    async function load(){
      const data=await fetchJson('/api/settings');
      st.memory=data.memory;st.draft={};render();return st.memory;
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
      }finally{st.busy=false;render()}
    }
    host.setAttribute('data-memory-settings','1');
    render();
    return {load,render,state:st,patch,submit};
  }

  root.JarvisMemorySettings=Object.freeze({mountId:MOUNT_ID,mount:()=>root.document?root.document.getElementById(MOUNT_ID):null,create,
    async show(host,options){const view=create(host,options);try{await view.load()}catch(e){host.innerHTML=`<div class="notice bad" role="alert">${esc(e.message)}</div>`}return view}});
})(typeof window!=='undefined'?window:globalThis);
