/* Catalogue partagé du Control Center.

   Le module consomme uniquement le contrat de GET /api/catalog. Il ne décide
   jamais si un modèle est utilisable : `availability.state`, `selectable`,
   provenance et actions viennent du serveur. Les fonctions de projection sont
   pures et exportées pour être exécutées directement par les tests Node. */

(function(root){
  'use strict';

  const FILTER_FIELDS=['providers','roles','capabilities','tags','availability'];
  const COLUMN_LABELS={
    compare:'Comparer',model:'Modèle',provider:'Fournisseur',roles:'Rôles',
    capabilities:'Capacités',tags:'Tags',guidance:'Usage conseillé',price:'Prix',
    availability:'Disponibilité',actions:'Actions'
  };
  const DEFAULT_COLUMNS=['compare','model','provider','capabilities','guidance','price','availability','actions'];
  const AVAILABILITY_LABELS={
    usable:'Utilisable',configured_unverified:'Configuré · non vérifié',
    available_not_configured:'Disponible · non configuré',unavailable:'Indisponible',unknown:'Inconnu'
  };
  const AVAILABILITY_TONES={
    usable:'ok',configured_unverified:'warn',available_not_configured:'warn',
    unavailable:'bad',unknown:'muted'
  };

  function text(value){return typeof value==='string'?value:''}
  function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,char=>({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[char]))}
  function normalized(value){return String(value??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim()}
  function claimValue(claim){return claim&&typeof claim==='object'&&Object.prototype.hasOwnProperty.call(claim,'value')?claim.value:null}
  function asStrings(value){return Array.isArray(value)?value.filter(item=>typeof item==='string'&&item.trim()).map(item=>item.trim()):[]}
  function claimStrings(claim){return asStrings(claimValue(claim))}
  function identity(item){return item&&item.identity&&typeof item.identity==='object'?item.identity:{}}
  function availability(item){return item&&item.availability&&typeof item.availability==='object'?item.availability:{}}
  function compareAllowed(item){return availability(item).selectable===true}

  function searchableText(item){
    const id=identity(item);
    return normalized([
      text(item&&item.label),text(id.model_id),text(id.provider_id),text(id.agent_id),
      text(claimValue(item&&item.description)),...claimStrings(item&&item.roles),
      ...claimStrings(item&&item.capabilities),...claimStrings(item&&item.tags),
      ...claimStrings(item&&item.recommended_uses)
    ].join(' '));
  }

  function selectedValues(filters,field){
    const value=filters&&filters[field];
    if(value instanceof Set)return [...value].map(String);
    return Array.isArray(value)?value.map(String):[];
  }

  function fieldValues(item,field){
    if(field==='providers')return [text(identity(item).provider_id)].filter(Boolean);
    if(field==='roles')return claimStrings(item&&item.roles);
    if(field==='capabilities')return claimStrings(item&&item.capabilities);
    if(field==='tags')return claimStrings(item&&item.tags);
    if(field==='availability')return [text(availability(item).state)].filter(Boolean);
    return [];
  }

  /* OR dans un même filtre, AND entre familles de filtres. */
  function filterItems(items,query,filters){
    const needle=normalized(query);
    return (Array.isArray(items)?items:[]).filter(item=>{
      if(needle&&!searchableText(item).includes(needle))return false;
      return FILTER_FIELDS.every(field=>{
        const selected=selectedValues(filters,field);
        if(!selected.length)return true;
        const values=new Set(fieldValues(item,field));
        return selected.some(value=>values.has(value));
      });
    });
  }

  function finiteNumber(value){return typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null}
  function priceInfo(item){
    const value=claimValue(item&&item.pricing);
    if(!value||typeof value!=='object')return null;
    const currency=text(value.currency),unit=text(value.unit);
    if(!currency||!unit)return null;
    if(unit==='minute'){
      const amount=finiteNumber(value.amount);
      return amount===null?null:{group:`${currency}|${unit}`,amount,label:`${formatNumber(amount)} ${currency} / min`};
    }
    if(unit==='million_tokens'){
      const input=finiteNumber(value.input),output=finiteNumber(value.output);
      if(input===null||output===null)return null;
      return {group:`${currency}|${unit}`,amount:(input+output)/2,
        label:`${formatNumber(input)} / ${formatNumber(output)} ${currency} · 1M tokens E/S`};
    }
    return null;
  }

  function formatNumber(value){return Number(value).toLocaleString('fr-FR',{maximumFractionDigits:6})}
  function compareText(left,right){return String(left).localeCompare(String(right),'fr',{sensitivity:'base',numeric:true})}
  function stableIdentity(item){return `${text(item&&item.label)}\u0000${text(item&&item.key)}`}

  /* Un prix inconnu reste dernier dans les deux directions. Des unités ou
     devises différentes forment des groupes : aucun faux taux de conversion. */
  function sortItems(items,sort){
    const direction=sort==='price-desc'?-1:1;
    return (Array.isArray(items)?items:[]).map((item,index)=>({item,index})).sort((left,right)=>{
      if(sort==='price-asc'||sort==='price-desc'){
        const a=priceInfo(left.item),b=priceInfo(right.item);
        if(!a&&!b)return compareText(stableIdentity(left.item),stableIdentity(right.item))||left.index-right.index;
        if(!a)return 1;
        if(!b)return -1;
        const group=compareText(a.group,b.group);
        if(group)return group;
        const amount=(a.amount-b.amount)*direction;
        if(amount)return amount;
      }
      return compareText(stableIdentity(left.item),stableIdentity(right.item))||left.index-right.index;
    }).map(entry=>entry.item);
  }

  function catalogFacets(items){
    const result={};
    for(const field of FILTER_FIELDS){
      const values=new Set();
      for(const item of Array.isArray(items)?items:[])for(const value of fieldValues(item,field))values.add(value);
      result[field]=[...values].sort(compareText);
    }
    return result;
  }

  function itemMap(items){return new Map((Array.isArray(items)?items:[]).map(item=>[text(item&&item.key),item]))}
  function reconcileComparison(items,selection,limit=3){
    const byKey=itemMap(items),next=[];
    for(const key of selection instanceof Set?selection:Array.isArray(selection)?selection:[]){
      const item=byKey.get(String(key));
      if(item&&compareAllowed(item)&&!next.includes(String(key))&&next.length<limit)next.push(String(key));
    }
    return new Set(next);
  }
  function toggleComparison(items,selection,key,limit=3){
    const next=reconcileComparison(items,selection,limit),target=String(key);
    if(next.has(target)){next.delete(target);return next}
    const item=itemMap(items).get(target);
    if(item&&compareAllowed(item)&&next.size<limit)next.add(target);
    return next;
  }

  function hasMissingMetadata(item){
    return ['description','tags','recommended_uses','pricing'].some(field=>claimValue(item&&item[field])===null);
  }
  function uiState(envelope,options={}){
    if(options.loading)return {kind:'loading',message:'Chargement du catalogue…'};
    if(options.error)return {kind:'error',message:text(options.error)||'Catalogue indisponible.'};
    const items=Array.isArray(envelope&&envelope.items)?envelope.items:[];
    const sources=Array.isArray(envelope&&envelope.sources)?envelope.sources:[];
    const credentialMissing=sources.some(source=>source&&source.status_code==='catalog_no_key');
    if(credentialMissing&&!items.some(compareAllowed))return {kind:'no_credentials',message:'Clé fournisseur absente. Ajoutez-la dans API Keys puis actualisez.'};
    if(!items.length)return {kind:'empty',message:'Aucun modèle publié pour cette vue.'};
    if(items.some(hasMissingMetadata)||sources.some(source=>source&&source.freshness!=='live'&&source.freshness!=='fresh')){
      return {kind:'partial',message:'Métadonnées partielles : les valeurs inconnues restent signalées comme telles.'};
    }
    return {kind:'ready',message:''};
  }

  function projectCatalog(envelope,options={}){
    const all=Array.isArray(envelope&&envelope.items)?envelope.items:[];
    const selection=reconcileComparison(all,options.selection,options.compareLimit||3);
    const items=sortItems(filterItems(all,options.query||'',options.filters||{}),options.sort||'name-asc');
    return {items,selection,facets:catalogFacets(all),state:uiState(envelope,options),total:all.length};
  }

  function provenanceEntryTitle(p){
    if(!p||typeof p!=='object')return '';
    return [text(p.source_id),text(p.freshness),text(p.status_code)].filter(Boolean).join(' · ');
  }
  function provenanceTitle(claim){return provenanceEntryTitle(claim&&claim.provenance)}
  function valueProvenanceTitle(claim,value){
    const byValue=claim&&claim.provenance_by_value;
    const sources=byValue&&typeof byValue==='object'&&Array.isArray(byValue[value])?byValue[value]:[];
    return sources.map(provenanceEntryTitle).filter(Boolean).join(' + ')||provenanceTitle(claim);
  }
  function chipList(claim){
    const values=claimStrings(claim);
    if(!values.length)return '<span class="catalog-unknown">Inconnu</span>';
    return values.map(value=>{
      const source=valueProvenanceTitle(claim,value);
      return `<span class="catalog-chip"${source?` title="${escapeHtml(source)}"`:''}>${escapeHtml(value)}</span>`;
    }).join(' ');
  }
  function guidanceHtml(item){
    const description=text(claimValue(item&&item.description));
    const uses=claimStrings(item&&item.recommended_uses);
    if(!description&&!uses.length)return '<span class="catalog-unknown">Inconnu</span>';
    const source=provenanceTitle((item&&item.recommended_uses)||(item&&item.description));
    return `<span${source?` title="${escapeHtml(source)}"`:''}>${escapeHtml(description||uses.join(' · '))}</span>`;
  }
  function priceHtml(item){
    const price=priceInfo(item),source=provenanceTitle(item&&item.pricing);
    return price?`<span${source?` title="${escapeHtml(source)}"`:''}>${escapeHtml(price.label)}</span>`:'<span class="catalog-unknown">Inconnu</span>';
  }
  function availabilityHtml(item){
    const current=availability(item),state=text(current.state)||'unknown';
    const label=AVAILABILITY_LABELS[state]||state;
    const evidence=Array.isArray(current.evidence)?current.evidence:[];
    const detail=evidence.length?`<details class="catalog-evidence"><summary>Sources</summary><ul>${evidence.map(entry=>
      `<li>${escapeHtml([text(entry.source_id),text(entry.freshness),text(entry.status_code)].filter(Boolean).join(' · '))}</li>`
    ).join('')}</ul></details>`:'';
    return `<span class="catalog-status ${escapeHtml(AVAILABILITY_TONES[state]||'muted')}">${escapeHtml(label)}</span>`+
      `<span class="catalog-reason">${escapeHtml(text(current.reason)||'Raison inconnue')}</span>${detail}`;
  }

  function backendActions(item){
    return (Array.isArray(item&&item.actions)?item.actions:[]).filter(action=>
      action&&typeof action==='object'&&text(action.id)&&text(action.label)
    );
  }
  function actionsHtml(item){
    const actions=backendActions(item);
    if(!actions.length)return '<span class="catalog-unknown">Aucune</span>';
    return actions.map(action=>`<button type="button" class="action small" data-catalog-action="${escapeHtml(action.id)}" data-catalog-key="${escapeHtml(item.key)}"${action.enabled===false?' disabled':''}>${escapeHtml(action.label)}</button>`).join(' ');
  }

  function normalizeColumns(columns){
    const requested=Array.isArray(columns)?columns:DEFAULT_COLUMNS;
    const known=requested.filter((column,index)=>COLUMN_LABELS[column]&&requested.indexOf(column)===index);
    return known.length?known:DEFAULT_COLUMNS.slice();
  }
  function cellHtml(column,item,selection,limit){
    const id=identity(item),key=text(item&&item.key);
    if(column==='compare'){
      const selectable=compareAllowed(item),checked=selection.has(key),full=selection.size>=limit&&!checked;
      return `<input type="checkbox" data-catalog-compare="${escapeHtml(key)}" aria-label="Comparer ${escapeHtml(text(item&&item.label)||text(id.model_id))}"${checked?' checked':''}${(!selectable||full)?' disabled':''}>`;
    }
    if(column==='model')return `<strong>${escapeHtml(text(item&&item.label)||text(id.model_id)||'Modèle inconnu')}</strong><span class="catalog-model-id">${escapeHtml(text(id.model_id))}</span>`;
    if(column==='provider')return escapeHtml(text(id.provider_id)||'Inconnu');
    if(column==='roles')return chipList(item&&item.roles);
    if(column==='capabilities')return chipList(item&&item.capabilities);
    if(column==='tags')return chipList(item&&item.tags);
    if(column==='guidance')return guidanceHtml(item);
    if(column==='price')return priceHtml(item);
    if(column==='availability')return availabilityHtml(item);
    if(column==='actions')return actionsHtml(item);
    return '';
  }

  function filterControls(facets,filters){
    const labels={providers:'Fournisseurs',roles:'Rôles',capabilities:'Capacités',tags:'Tags',availability:'Disponibilité'};
    return FILTER_FIELDS.filter(field=>facets[field]&&facets[field].length).map(field=>{
      const active=new Set(selectedValues(filters,field));
      return `<fieldset class="catalog-filter"><legend>${labels[field]}</legend>${facets[field].map(value=>
        `<label><input type="checkbox" data-catalog-filter="${field}" value="${escapeHtml(value)}"${active.has(value)?' checked':''}> ${escapeHtml(AVAILABILITY_LABELS[value]||value)}</label>`
      ).join('')}</fieldset>`;
    }).join('');
  }

  function noticeHtml(view){
    return view.state.kind==='ready'?'':`<div class="catalog-notice ${escapeHtml(view.state.kind)}" role="status">${escapeHtml(view.state.message)}</div>`;
  }
  function summaryHtml(view,limit){
    return `${view.items.length} / ${view.total} modèle(s) · ${view.selection.size} / ${limit} à comparer`;
  }
  function resultsHtml(envelope,view,columns,limit){
    if(!view.items.length)return '<div class="catalog-empty" role="status">Aucun modèle ne correspond aux filtres.</div>';
    const rows=view.items.map(item=>`<tr>${columns.map(column=>{
      const attributes=`data-label="${escapeHtml(COLUMN_LABELS[column])}" class="catalog-cell-${column}"`;
      const content=cellHtml(column,item,view.selection,limit);
      return column==='model'?`<th scope="row" ${attributes}>${content}</th>`:`<td ${attributes}>${content}</td>`;
    }).join('')}</tr>`).join('');
    return `<div class="catalog-table-wrap"><table class="catalog-table"><caption>Catalogue de modèles ${escapeHtml(text(envelope&&envelope.surface))}</caption><thead><tr>${columns.map(column=>`<th scope="col">${escapeHtml(COLUMN_LABELS[column])}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  function renderCatalog(envelope,options={}){
    const view=projectCatalog(envelope,options),columns=normalizeColumns(options.columns),limit=options.compareLimit||3;
    const notice=noticeHtml(view);
    if(['loading','error'].includes(view.state.kind))return `<section class="catalog-shell" aria-label="Catalogue de modèles">${notice}</section>`;
    const controls=`<div class="catalog-toolbar" role="search" aria-label="Recherche et tri du catalogue"><label class="catalog-search">Rechercher<input type="search" data-catalog-search value="${escapeHtml(options.query||'')}" placeholder="Modèle, fournisseur, capacité…"></label><label class="catalog-sort">Trier<select data-catalog-sort><option value="name-asc"${options.sort==='name-asc'||!options.sort?' selected':''}>Nom A–Z</option><option value="price-desc"${options.sort==='price-desc'?' selected':''}>Prix décroissant</option><option value="price-asc"${options.sort==='price-asc'?' selected':''}>Prix croissant</option></select></label></div>`;
    const filters=`<div class="catalog-filters" role="group" aria-label="Filtres du catalogue">${filterControls(view.facets,options.filters||{})}</div>`;
    const summary=`<div class="catalog-summary" data-catalog-summary aria-live="polite">${summaryHtml(view,limit)}</div>`;
    const results=`<div data-catalog-results>${resultsHtml(envelope,view,columns,limit)}</div>`;
    return `<section class="catalog-shell" aria-label="Catalogue de modèles" data-catalog-surface="${escapeHtml(text(envelope&&envelope.surface))}">${notice}${controls}${filters}${summary}${results}</section>`;
  }

  function catalogUrl(surface,role,refresh){
    const params=new URLSearchParams({surface:String(surface||'')});
    if(role)params.set('role',String(role));
    if(refresh)params.set('refresh','true');
    return `/api/catalog?${params.toString()}`;
  }

  function createCatalogTable(container,options={}){
    if(!container||typeof container.addEventListener!=='function')throw new TypeError('Catalog container is required');
    const fetcher=options.fetcher||(typeof fetch==='function'?fetch.bind(root):null);
    const state={envelope:null,loading:false,error:'',query:'',sort:'name-asc',filters:{},selection:new Set()};
    let destroyed=false,generation=0,pending=null;
    function render(){
      if(destroyed)return;
      container.innerHTML=renderCatalog(state.envelope,{...options,...state});
    }
    /* Input/search nodes remain mounted while results change. This preserves
       focus, selection and IME state across every keystroke. */
    function renderResults(){
      if(destroyed)return;
      const view=projectCatalog(state.envelope,{...options,...state});
      const summary=container.querySelector&&container.querySelector('[data-catalog-summary]');
      const results=container.querySelector&&container.querySelector('[data-catalog-results]');
      if(!summary||!results){render();return}
      summary.textContent=summaryHtml(view,options.compareLimit||3);
      results.innerHTML=resultsHtml(state.envelope,view,normalizeColumns(options.columns),options.compareLimit||3);
    }
    function handleInput(event){
      const target=event.target;
      if(target&&target.matches('[data-catalog-search]')){state.query=target.value;renderResults()}
    }
    function handleChange(event){
      const target=event.target;
      if(!target)return;
      if(target.matches('[data-catalog-sort]')){state.sort=target.value;renderResults();return}
      if(target.matches('[data-catalog-filter]')){
        const field=target.dataset.catalogFilter,current=new Set(selectedValues(state.filters,field));
        target.checked?current.add(target.value):current.delete(target.value);
        state.filters={...state.filters,[field]:[...current]};renderResults();return;
      }
      if(target.matches('[data-catalog-compare]')){
        state.selection=toggleComparison(state.envelope&&state.envelope.items,state.selection,target.dataset.catalogCompare,options.compareLimit||3);
        if(typeof options.onCompare==='function')options.onCompare([...state.selection]);
        renderResults();
      }
    }
    function handleClick(event){
      const button=event.target&&event.target.closest?event.target.closest('[data-catalog-action]'):null;
      if(!button)return;
      const item=itemMap(state.envelope&&state.envelope.items).get(button.dataset.catalogKey);
      const action=backendActions(item).find(entry=>entry.id===button.dataset.catalogAction);
      if(!action||action.enabled===false)return;
      if(typeof options.onAction==='function')options.onAction(action,item);
      else if(typeof container.dispatchEvent==='function'&&typeof root.CustomEvent==='function')container.dispatchEvent(new root.CustomEvent('jarvis:catalog-action',{detail:{action,item}}));
    }
    container.addEventListener('input',handleInput);
    container.addEventListener('change',handleChange);
    container.addEventListener('click',handleClick);
    async function load(refresh=false){
      if(destroyed)return null;
      if(!fetcher)throw new Error('Fetch is unavailable');
      const requestId=++generation;
      if(pending)pending.abort();
      const controller=typeof root.AbortController==='function'?new root.AbortController():null;
      pending=controller;
      state.loading=true;state.error='';render();
      try{
        const response=await fetcher(catalogUrl(options.surface,options.role,refresh),controller?{signal:controller.signal}:{});
        if(destroyed||requestId!==generation)return null;
        const payload=await response.json();
        if(destroyed||requestId!==generation)return null;
        if(!response.ok||payload.ok===false)throw new Error(payload.error||payload.code||`HTTP ${response.status}`);
        state.envelope=payload;state.selection=reconcileComparison(payload.items,state.selection,options.compareLimit||3);
      }catch(error){
        if(destroyed||requestId!==generation)return null;
        state.error=error&&error.message?error.message:String(error);
      }finally{
        if(!destroyed&&requestId===generation){pending=null;state.loading=false;render()}
      }
      return state.envelope;
    }
    function destroy(){
      if(destroyed)return;
      destroyed=true;++generation;
      if(pending){pending.abort();pending=null}
      container.removeEventListener('input',handleInput);
      container.removeEventListener('change',handleChange);
      container.removeEventListener('click',handleClick);
      container.innerHTML='';
    }
    render();
    return {load,refresh:()=>load(true),render,state,destroy};
  }

  const api={FILTER_FIELDS,DEFAULT_COLUMNS,claimValue,searchableText,filterItems,sortItems,priceInfo,
    catalogFacets,reconcileComparison,toggleComparison,uiState,projectCatalog,renderCatalog,catalogUrl,
    createCatalogTable,compareAllowed,backendActions};
  root.JarvisCatalog=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
