/* Inspecteur MCP du Control Center (Slice 07 de la tâche jarvis-mcp-semantic-batch-inspector).

   Contrat : `docs/mcp/tool-contract.md` §3 (catégories), §4 (classes, atomicité,
   disponibilité), §8 et §10.6 (API du catalogue). Deux parties, comme
   `control_center_testlab.js` :

   - `JarvisMcpInspectorCore`, logique pure exécutée telle quelle par les tests
     node : vocabulaire, client HTTP en lecture seule, recherche, onglets,
     cartes compactes, détail (paramètres, schéma de sortie lisible, schéma
     brut en dernier), états de chargement / erreur / vide, touches ;
   - un bloc navigateur qui branche la vue plein écran dans la page.

   TROIS RÈGLES TIENNENT CE FICHIER.

   1. LECTURE SEULE. Le seul appel réseau du fichier est `createClient().get`,
      qui refuse toute adresse hors de `/api/mcp/tools` et n'envoie que des
      `GET`. Aucun outil n'est exécuté d'ici, aucun corps n'est posté.
   2. AUCUN OUTIL ÉCRIT EN DUR. L'écran affiche ce que l'API rend (source unique :
      `mcp_catalog`, contrat §5.1) ; aucun nom d'outil ni de serveur n'apparaît
      dans ce fichier, pour qu'aucune liste parallèle ne puisse dériver.
   3. CE QUI ATTEND SE VOIT. Chargement du catalogue ou d'un descripteur :
      squelette, libellé, compteur de secondes, délai borné (`DEADLINE_MS`) au
      bout duquel l'erreur le dit et propose « Réessayer ». Chaque refus codé
      de l'API est affiché avec son code et son statut HTTP. */

const JarvisMcpInspectorCore=(function(){
  'use strict';

  const ROUTE='/api/mcp/tools';
  const DEADLINE_MS=15000;
  /* Descripteurs chargés en même temps au plus (tout déplier, index de la recherche). */
  const PARALLEL=4;

  /* ----------------------------------------------------------- vocabulaire
     Miroir des énumérations du contrat (§4). Une valeur inconnue de cet écran
     s'affiche telle quelle, jamais maquillée en une valeur connue. */
  const SIDE_EFFECTS=Object.freeze({
    read:{label:'Lecture',tone:'',means:'ne change aucun état de Jarvis, de Core ni externe.'},
    write:{label:'Écriture',tone:'on',means:'change un état que la même surface sait remettre (masquer ↔ réafficher, réglage ↔ réglage).'},
    destructive:{label:'Destructif',tone:'bad',means:'retire ou écrase un état que la surface ne sait pas restaurer.'},
  });
  const ATOMICITY=Object.freeze({
    none:{label:'Sans effet',means:'outil de lecture.'},
    single_command:{label:'Une commande',means:'une commande de scène Core : tout ou rien, une révision au plus.'},
    atomic_batch:{label:'Lot atomique',means:'une commande de sélection sur un ensemble : tout ou rien, une révision au plus.'},
    single_request:{label:'Une requête',means:'une requête au Control Center (réglage relu après écriture, commande Bare Hands répondue par la page).'},
    external:{label:'Externe',means:'aucune garantie de Jarvis.'},
  });
  const STATES=Object.freeze({
    advertised:{label:'Annoncé',tone:'ok',means:'annoncé au brain en cours'},
    configured:{label:'Configuré',tone:'on',means:'déclaré au prochain lancement du brain'},
    disabled:{label:'Désactivé',tone:'off',means:'ne sera pas déclaré au prochain lancement'},
    known:{label:'Connu',tone:'off',means:'défini dans le code ; sa déclaration n’est pas prouvable par Jarvis'},
  });
  const FORMATS=Object.freeze({
    structured:'Résultat structuré (structuredContent), décrit par le schéma ci-dessous.',
    json_text:'Texte JSON compact ; le schéma ci-dessous décrit le texte une fois lu.',
    text_lines:'Texte ligne à ligne ; la grammaire est dans les notes.',
    'json_text+image':'Un bloc texte JSON (schéma ci-dessous) puis une image PNG.',
    untyped:'Non typé : le serveur n’annonce qu’une forme générique, montrée telle quelle.',
  });
  const PENDING='À prendre en compte au prochain (re)démarrage du brain';

  const ERRORS=Object.freeze({
    mcp_catalog_unavailable:{title:'Catalogue MCP indisponible',
      hint:'Le Control Center n’a pas pu construire le catalogue. Lisez mcp.catalog_failed dans runtime/trace.jsonl, puis réessayez.'},
    mcp_server_unavailable:{title:'Serveur MCP non descriptible',
      hint:'Son module ne s’importe pas (dépendance absente ?). Installez-la puis redémarrez le Control Center.'},
    mcp_tool_unknown:{title:'Outil inconnu du catalogue',
      hint:'Le catalogue a changé depuis l’ouverture : actualisez la liste.'},
    method_not_allowed:{title:'Méthode refusée',hint:'L’API du catalogue n’accepte que GET.'},
    timeout:{title:'Pas de réponse',hint:'Le Control Center n’a pas répondu à temps. Réessayez ; s’il ne répond toujours pas, vérifiez qu’il tourne.'},
    network:{title:'Control Center injoignable',hint:'La requête n’a pas abouti. Vérifiez que le Control Center tourne, puis réessayez.'},
    bad_response:{title:'Réponse illisible',hint:'La réponse n’est pas le JSON attendu. Réessayez ; lisez la trace si cela persiste.'},
  });

  /* ------------------------------------------------------------- outillage */
  function esc(value){
    return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  /* Octets avec espace fine insécable, comme la documentation (« 31 864 o »). */
  function formatBytes(value){
    const n=Math.max(0,Math.round(Number(value)||0));
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g,'\u202f')+'\u202fo';
  }
  function formatSeconds(ms){
    return (Math.max(0,ms)/1000).toFixed(1).replace('.',',')+'\u202fs';
  }
  function plural(n,one,many){return `${n} ${n===1?one:many}`}
  function toolKey(tool){return `${tool.server}/${tool.name}`}
  /* Deux segments, chacun encodé : jamais un chemin composé d'autre chose. */
  function detailUrl(server,name){
    return `${ROUTE}/${encodeURIComponent(String(server))}/${encodeURIComponent(String(name))}`;
  }
  /* Le marquage léger des descriptions (**gras**, `code`), après échappement. */
  function inline(text){
    return esc(text).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>');
  }
  function plainSummary(text){return String(text??'').replace(/\*\*([^*]+)\*\*/g,'$1')}
  function chip(label,tone,title){
    return `<span class="chip${tone?' '+tone:''}"${title?` title="${esc(title)}"`:''}>${esc(label)}</span>`;
  }
  function json(value){
    try{return JSON.stringify(value)}catch(_){return String(value)}
  }

  /* ------------------------------------------------------------- client HTTP
     Lecture seule par construction : une adresse hors du catalogue ou une
     méthode autre que GET est refusée AVANT le réseau. Chaque requête a un
     délai ; un refus codé de l'API devient une erreur qui garde code et statut. */
  function apiError(code,status,message){
    const error=new Error(message||code);
    error.code=code;error.status=status;
    return error;
  }
  function createClient({fetchImpl,deadlineMs=DEADLINE_MS,setTimer=setTimeout,clearTimer=clearTimeout}={}){
    async function get(path){
      if(typeof path!=='string'||!(path===ROUTE||path.startsWith(ROUTE+'/')))
        throw apiError('forbidden_route',0,`adresse hors du catalogue MCP : ${path}`);
      const controller=typeof AbortController==='function'?new AbortController():null;
      let timedOut=false;
      const timer=setTimer(()=>{timedOut=true;if(controller)controller.abort()},deadlineMs);
      try{
        let response;
        try{
          response=await fetchImpl(path,{method:'GET',headers:{Accept:'application/json'},
            signal:controller?controller.signal:undefined});
        }catch(error){
          if(timedOut)throw apiError('timeout',0,`aucune réponse en ${Math.round(deadlineMs/1000)} s`);
          throw apiError('network',0,(error&&error.message)||'requête interrompue');
        }
        let text='';
        try{text=await response.text()}catch(error){
          if(timedOut)throw apiError('timeout',0,`aucune réponse en ${Math.round(deadlineMs/1000)} s`);
          throw apiError('network',response.status,(error&&error.message)||'réponse interrompue');
        }
        let body=null;
        try{body=text?JSON.parse(text):null}catch(_){body=null}
        if(!response.ok||!body||body.ok===false){
          const code=(body&&body.code)||(response.ok?'bad_response':`http_${response.status}`);
          throw apiError(code,response.status,(body&&body.error)||text.slice(0,200)||`HTTP ${response.status}`);
        }
        return body;
      }finally{clearTimer(timer)}
    }
    return {get,list:()=>get(ROUTE),detail:(server,name)=>get(detailUrl(server,name))};
  }

  /* Vue d'une erreur : titre humain, message du serveur, code et statut, recours. */
  function errorView(error){
    const code=(error&&error.code)||'network';
    const known=ERRORS[code]||{title:'Erreur du catalogue MCP',hint:'Réessayez ; lisez la trace du Control Center si cela persiste.'};
    return {title:known.title,hint:known.hint,code,status:(error&&error.status)||0,
      message:(error&&error.message)?String(error.message):'échec sans message'};
  }
  function errorHtml(error,{retry='list',key=''}={}){
    const view=errorView(error);
    const where=[view.code,view.status?`HTTP ${view.status}`:''].filter(Boolean).join(' · ');
    return `<div class="notice bad mcpi-error" role="alert"><strong>${esc(view.title)}</strong>`
      +`<div class="mcpi-emsg">${esc(view.message)} <code>${esc(where)}</code></div>`
      +`<div class="hint">${esc(view.hint)}</div>`
      +`<button type="button" class="action small" data-act="retry" data-retry="${esc(retry)}"${key?` data-key="${esc(key)}"`:''}>Réessayer</button></div>`;
  }

  /* ------------------------------------------------------ disponibilité (§4.3) */
  function stateOf(value){
    return STATES[value]||{label:String(value||'inconnu'),tone:'off',means:'état inconnu de cet écran'};
  }
  function conditionText(server){
    const facts=server.availability||{};
    if(server.registration==='operator')return 'enregistré par l’opérateur, hors de Jarvis';
    if(!server.condition)return 'toujours déclaré (aucun interrupteur)';
    const value=facts.condition_value===true?'activé':facts.condition_value===false?'désactivé':'inconnu';
    return `${server.condition} : ${value}`;
  }
  function pendingServers(list){
    return ((list&&list.servers)||[]).filter(s=>s.availability&&s.availability.pending_restart===true);
  }

  /* ----------------------------------------------------- recherche, onglets
     La recherche porte sur le nom, le libellé, le résumé et les noms de
     paramètres. Les cartes de la liste ne portent pas ces noms : ils viennent
     des descripteurs déjà chargés (`details`), et le bloc navigateur les charge
     tous dès la première recherche. `why` dit ce qui a correspondu. */
  function normalize(text){
    return String(text??'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');
  }
  /* Noms de paramètres, clés imbriquées comprises (`select.near.radius` se
     trouve par « radius ») : lus dans `constraints.keys` que l'API dérive. */
  function parameterNames(parameters){
    const out=[];
    const walk=(keys,prefix)=>{
      for(const [name,info] of Object.entries(keys||{})){
        out.push(prefix+name);
        const c=info||{};
        walk(c.keys||(c.items&&c.items.keys),`${prefix}${name}.`);
      }
    };
    for(const p of parameters){
      out.push(p.name);
      const c=p.constraints||{};
      walk(c.keys||(c.items&&c.items.keys),`${p.name}.`);
    }
    return out;
  }
  function matchOf(tool,query,detail){
    const q=normalize(query).trim();
    if(!q)return {hit:true,why:null};
    const terms=q.split(/\s+/);
    const own=normalize([tool.name,tool.label,plainSummary(tool.summary),tool.server].join(' '));
    /* `detail` : l'entrée du cache (`{state, tool}`) ; seul un descripteur lu compte. */
    const descriptor=detail&&detail.state==='ok'?detail.tool:null;
    const params=descriptor&&Array.isArray(descriptor.parameters)?parameterNames(descriptor.parameters):[];
    const paramText=normalize(params.join(' '));
    const hit=terms.every(t=>own.includes(t)||paramText.includes(t));
    if(!hit)return {hit:false,why:null};
    const byParam=params.filter(name=>terms.some(t=>normalize(name.split('.').pop()).includes(t)&&!own.includes(t))).slice(0,4);
    return {hit:true,why:byParam.length?byParam:null};
  }
  function tabsOf(list,query,details){
    const tools=(list&&list.tools)||[];
    return ((list&&list.categories)||[]).map(category=>{
      const mine=tools.filter(t=>t.category===category.category);
      const hits=mine.filter(t=>matchOf(t,query,details&&details[toolKey(t)]).hit);
      return {category:category.category,label:category.label,total:mine.length,count:hits.length};
    });
  }
  function visibleTools(list,tab,query,details){
    return ((list&&list.tools)||[]).map((tool,index)=>({tool,index}))
      .filter(({tool})=>tool.category===tab)
      .map(entry=>({...entry,match:matchOf(entry.tool,query,details&&details[toolKey(entry.tool)])}))
      .filter(entry=>entry.match.hit);
  }
  /* Index de la recherche sur les paramètres : combien de descripteurs sont lus. */
  function indexProgress(list,details){
    const tools=(list&&list.tools)||[];
    const done=tools.filter(t=>{const d=details&&details[toolKey(t)];return d&&d.state==='ok'}).length;
    return {done,total:tools.length};
  }

  /* -------------------------------------------------------------- touches
     Onglets : flèches gauche/droite (en boucle), Début, Fin. Liste des outils :
     flèches haut/bas d'un titre à l'autre, Début, Fin. `null` : touche ignorée. */
  function tabKey(key,index,count){
    if(!count)return null;
    if(key==='ArrowRight')return (index+1)%count;
    if(key==='ArrowLeft')return (index-1+count)%count;
    if(key==='Home')return 0;
    if(key==='End')return count-1;
    return null;
  }
  function cardKey(key,index,count){
    if(!count)return null;
    if(key==='ArrowDown')return Math.min(index+1,count-1);
    if(key==='ArrowUp')return Math.max(index-1,0);
    if(key==='Home')return 0;
    if(key==='End')return count-1;
    return null;
  }

  /* ----------------------------------------------------- schéma lisible
     Un JSON Schema devient un arbre : objets (clés requises ou facultatives),
     listes, tuples positionnels, variantes, énumérations, dictionnaires,
     « ou null ». `$ref` est résolu dans `$defs` ; un cycle ou une profondeur
     excessive s'arrête sur une mention, jamais sur une boucle. */
  const MAX_DEPTH=8;
  function resolveRef(schema,defs){
    if(schema&&typeof schema.$ref==='string'&&schema.$ref.startsWith('#/$defs/')){
      const name=schema.$ref.slice('#/$defs/'.length);
      return {schema:defs&&defs[name]?defs[name]:null,ref:name};
    }
    return {schema,ref:null};
  }
  function constraintsOf(schema){
    const out=[];
    const has=k=>schema[k]!==undefined;
    if(has('const'))out.push(`vaut ${json(schema.const)}`);
    if(has('minimum')&&has('maximum'))out.push(`${schema.minimum} à ${schema.maximum}`);
    else if(has('minimum'))out.push(`≥ ${schema.minimum}`);
    else if(has('maximum'))out.push(`≤ ${schema.maximum}`);
    if(has('exclusiveMinimum'))out.push(`> ${schema.exclusiveMinimum}`);
    if(has('exclusiveMaximum'))out.push(`< ${schema.exclusiveMaximum}`);
    if(has('minLength')&&has('maxLength'))out.push(`${schema.minLength} à ${schema.maxLength} caractères`);
    else if(has('maxLength'))out.push(`≤ ${schema.maxLength} caractères`);
    else if(has('minLength'))out.push(`≥ ${schema.minLength} caractères`);
    if(has('minItems')&&has('maxItems'))out.push(schema.minItems===schema.maxItems?`exactement ${schema.minItems} éléments`:`${schema.minItems} à ${schema.maxItems} éléments`);
    else if(has('maxItems'))out.push(`≤ ${schema.maxItems} éléments`);
    else if(has('minItems'))out.push(`au moins ${schema.minItems} élément${schema.minItems>1?'s':''}`);
    if(has('pattern'))out.push(`motif ${schema.pattern}`);
    if(has('format'))out.push(`format ${schema.format}`);
    return out;
  }
  function schemaModel(input,defs,depth=0,seen=[]){
    const {schema,ref}=resolveRef(input,defs);
    if(ref&&!schema)return {type:'référence inconnue',ref,constraints:[]};
    if(ref&&seen.includes(ref))return {type:'object',ref,recursive:true,constraints:[]};
    const trail=ref?[...seen,ref]:seen;
    if(schema===true||schema===undefined||schema===null)return {type:'toute valeur',constraints:[]};
    if(schema===false)return {type:'rien',constraints:[]};
    const node={type:'toute valeur',ref,description:schema.description||'',constraints:constraintsOf(schema)};
    if(depth>=MAX_DEPTH){node.type='…';node.truncated=true;return node}
    const variants=schema.anyOf||schema.oneOf;
    if(Array.isArray(variants)){
      const isNull=v=>{const r=resolveRef(v,defs).schema;return r&&r.type==='null'};
      const real=variants.filter(v=>!isNull(v));
      const nullable=real.length<variants.length;
      if(real.length===1){
        const inner=schemaModel(real[0],defs,depth,trail);
        return {...inner,nullable:nullable||inner.nullable,description:node.description||inner.description,
          constraints:[...node.constraints,...inner.constraints]};
      }
      node.type=schema.oneOf?'une des formes':'l’une de';
      node.nullable=nullable;
      node.variants=real.map(v=>schemaModel(v,defs,depth+1,trail));
      return node;
    }
    if(Array.isArray(schema.enum)){node.type='enum';node.enum=schema.enum.slice();return node}
    let type=schema.type;
    if(Array.isArray(type)){
      node.nullable=type.includes('null');
      type=type.filter(t=>t!=='null');
      if(type.length!==1){node.type=type.join(' | ')||'null';return node}
      type=type[0];
    }
    if(type===undefined&&schema.properties)type='object';
    if(type===undefined&&(schema.items!==undefined||schema.prefixItems))type='array';
    if(type===undefined)return node;
    node.type=type;
    if(type==='object'){
      const props=schema.properties||{};
      const required=new Set(schema.required||[]);
      node.fields=Object.keys(props).map(name=>({name,required:required.has(name),
        node:schemaModel(props[name],defs,depth+1,trail)}));
      if(schema.additionalProperties===false)node.closed=true;
      else if(schema.additionalProperties&&typeof schema.additionalProperties==='object')
        node.map=schemaModel(schema.additionalProperties,defs,depth+1,trail);
      else if(schema.additionalProperties===true||!node.fields.length)node.open=true;
    }
    if(type==='array'){
      if(Array.isArray(schema.prefixItems)){
        node.tuple=schema.prefixItems.map((item,i)=>({index:i+1,title:(item&&item.title)||'',
          node:schemaModel(item,defs,depth+1,trail)}));
      }else if(schema.items&&typeof schema.items==='object'){
        node.items=schemaModel(schema.items,defs,depth+1,trail);
      }
    }
    return node;
  }
  function typeLabel(node){
    let label=node.type;
    if(node.type==='array'&&node.items)label=`liste de ${typeLabel(node.items)}`;
    else if(node.type==='array'&&node.tuple)label=`ligne de ${node.tuple.length} colonnes`;
    else if(node.type==='array')label='liste';
    else if(node.type==='object'&&node.map)label=`dictionnaire → ${typeLabel(node.map)}`;
    else if(node.type==='object'&&node.open&&!(node.fields&&node.fields.length))label='objet libre';
    else if(node.type==='object')label='objet';
    if(node.ref&&node.type==='object')label+=` ${node.ref}`;
    if(node.nullable)label+=' ou null';
    return label;
  }
  function enumHtml(values){
    return `<span class="mcpi-enum">${values.map(v=>`<code>${esc(typeof v==='string'?v:json(v))}</code>`).join('')}</span>`;
  }
  /* Ligne d'un nœud (type, contraintes, énumération, description) puis ses enfants. */
  function nodeBody(node){
    const bits=[`<span class="mcpi-t">${esc(typeLabel(node))}</span>`];
    if(node.enum)bits.push(enumHtml(node.enum));
    for(const c of node.constraints||[])bits.push(`<span class="mcpi-c">${esc(c)}</span>`);
    if(node.closed)bits.push('<span class="mcpi-c" title="additionalProperties: false">clés fermées</span>');
    if(node.recursive)bits.push('<span class="mcpi-c">récursif</span>');
    let html=bits.join(' ');
    if(node.description)html+=`<span class="mcpi-d">${inline(node.description)}</span>`;
    return html+childrenHtml(node);
  }
  function childrenHtml(node){
    if(node.fields&&node.fields.length){
      return `<ul class="mcpi-tree">${node.fields.map(f=>`<li><code class="mcpi-k">${esc(f.name)}</code> `
        +`<span class="${f.required?'mcpi-req':'mcpi-opt'}">${f.required?'requis':'facultatif'}</span> ${nodeBody(f.node)}</li>`).join('')}</ul>`;
    }
    if(node.tuple){
      return `<ol class="mcpi-tree mcpi-tuple">${node.tuple.map(c=>`<li><span class="mcpi-pos">${c.index}</span>`
        +`${c.title?`<code class="mcpi-k">${esc(c.title)}</code> `:''}${nodeBody(c.node)}</li>`).join('')}</ol>`;
    }
    if(node.items&&(node.items.fields||node.items.tuple||node.items.variants||node.items.map))return childrenHtml(node.items);
    if(node.map&&(node.map.fields||node.map.tuple))return childrenHtml(node.map);
    if(node.variants){
      return `<ul class="mcpi-tree mcpi-variants">${node.variants.map((v,i)=>`<li><span class="mcpi-pos">${i+1}</span>${nodeBody(v)}</li>`).join('')}</ul>`;
    }
    return '';
  }
  function schemaHtml(schema){
    if(schema===null||schema===undefined)return '<p class="hint">Aucun schéma de résultat.</p>';
    const node=schemaModel(schema,schema.$defs||{});
    return `<div class="mcpi-schema">${nodeBody(node)}</div>`;
  }

  /* ------------------------------------------------------------ paramètres
     Les champs viennent de `parameters[]` (§10.1) : `default` n'existe que si
     le schéma en a un (absent ≠ null). Un paramètre objet ou liste d'objets
     déplie sa structure sous sa ligne, avec le même arbre que le résultat. */
  function constraintSummary(constraints){
    const c=constraints||{};
    const out=constraintsOf(c);
    if(Array.isArray(c.enum))out.unshift(`un de : ${c.enum.map(v=>typeof v==='string'?v:json(v)).join(', ')}`);
    if(c.items&&Array.isArray(c.items.enum))out.push(`éléments parmi : ${c.items.enum.join(', ')}`);
    if(c.items&&(c.items.minLength!==undefined||c.items.maxLength!==undefined))
      out.push(...constraintsOf(c.items).map(t=>`chaque élément ${t}`));
    const keys=c.keys||(c.items&&c.items.keys);
    if(keys){
      const n=Object.keys(keys).length,req=Object.values(keys).filter(k=>k&&k.required).length;
      const closed=c.closed||(c.items&&c.items.closed);
      out.push(`${plural(n,'clé','clés')}${req?`, dont ${req} requise${req>1?'s':''}`:''}${closed?', fermé':''} (détail ci-dessous)`);
    }
    return out;
  }
  function defaultHtml(parameter){
    if(!parameter.has_default)return '<span class="mcpi-none" title="aucune valeur par défaut">—</span>';
    return `<code>${esc(json(parameter.default))}</code>`;
  }
  function nestedSchemaOf(parameter,inputSchema){
    const c=parameter.constraints||{};
    if(!(c.keys||(c.items&&c.items.keys)))return null;
    const props=inputSchema&&inputSchema.properties;
    return props&&props[parameter.name]?props[parameter.name]:null;
  }
  function parametersHtml(tool){
    const params=Array.isArray(tool.parameters)?tool.parameters:[];
    if(!params.length)return '<p class="hint mcpi-noparam">Aucun paramètre : l’outil s’appelle sans argument.</p>';
    const defs=(tool.input_schema&&tool.input_schema.$defs)||{};
    const rows=params.map(p=>{
      const constraints=constraintSummary(p.constraints);
      const nested=nestedSchemaOf(p,tool.input_schema);
      const row=`<tr><th scope="row" data-label="Paramètre"><code>${esc(p.name)}</code></th>`
        +`<td data-label="Type"><code class="mcpi-type">${esc(p.type)}</code></td>`
        +`<td data-label="Requis">${p.required?'<span class="chip on">requis</span>':'<span class="mcpi-opt">facultatif</span>'}</td>`
        +`<td data-label="Défaut">${defaultHtml(p)}</td>`
        +`<td data-label="Contraintes">${constraints.length?constraints.map(t=>`<span class="mcpi-cons">${esc(t)}</span>`).join(''):'<span class="mcpi-none">—</span>'}</td>`
        +`<td data-label="Description">${p.description?inline(p.description):'<span class="mcpi-none">—</span>'}</td></tr>`;
      if(!nested)return row;
      const node=schemaModel(nested,defs);
      return row+`<tr class="mcpi-nest"><td colspan="6"><div class="mcpi-nesthead">Structure de <code>${esc(p.name)}</code></div>`
        +`<div class="mcpi-schema">${childrenHtml(node.items&&!node.fields?node.items:node)||nodeBody(node)}</div></td></tr>`;
    }).join('');
    const required=params.filter(p=>p.required).length;
    return `<table class="mcpi-params"><caption>Paramètres de ${esc(tool.name)} : ${plural(params.length,'paramètre','paramètres')}, ${required?plural(required,'requis','requis'):'aucun requis'}</caption>`
      +'<thead><tr><th scope="col">Paramètre</th><th scope="col">Type</th><th scope="col">Requis</th><th scope="col">Défaut</th><th scope="col">Contraintes</th><th scope="col">Description</th></tr></thead>'
      +`<tbody>${rows}</tbody></table>`;
  }

  /* ---------------------------------------------------------------- cartes */
  function badgesHtml(tool){
    const side=SIDE_EFFECTS[tool.side_effect]||{label:String(tool.side_effect),tone:'warn',means:'classe inconnue de cet écran'};
    const out=[chip(side.label,side.tone,side.means)];
    if(tool.atomicity==='atomic_batch')out.push(chip(ATOMICITY.atomic_batch.label,'',ATOMICITY.atomic_batch.means));
    if(tool.idempotent)out.push(chip('Idempotent','','le même appel deux fois : le second ne change rien'));
    if(tool.deprecated)out.push(chip('Déprécié','warn','outil gardé pour compatibilité : voir son remplaçant'));
    /* État du serveur répété sur la carte seulement quand il n'est pas « annoncé » :
       dans une recherche, un outil indisponible doit se voir sans remonter au serveur. */
    if(tool.availability&&tool.availability!=='advertised'){
      const st=stateOf(tool.availability);
      out.push(chip(st.label,st.tone==='on'?'on':'',st.means));
    }
    return out.join('');
  }
  function paragraphs(text){
    return String(text||'').trim().split(/\n\s*\n/).map(block=>{
      const lines=block.split('\n').map(l=>l.trim()).filter(Boolean);
      if(lines.length&&lines.every(l=>/^[-*•] /.test(l)))
        return `<ul>${lines.map(l=>`<li>${inline(l.slice(2))}</li>`).join('')}</ul>`;
      return `<p>${inline(lines.join(' '))}</p>`;
    }).join('');
  }
  /* La description sans son premier paragraphe quand c'est le résumé déjà
     affiché en tête de la ligne : le détail ne répète pas ce qu'on vient de lire. */
  function bodyOf(tool){
    const text=String(tool.description||'').trim();
    const [first,...rest]=text.split(/\n\s*\n/);
    const flat=s=>String(s||'').replace(/\s+/g,' ').trim();
    return rest.length&&flat(first)===flat(tool.summary)?rest.join('\n\n'):text;
  }
  function deprecationHtml(dep){
    if(!dep)return '';
    const facts=[
      dep.replacement?`Remplacé par <code>${esc(dep.replacement)}</code>.`:'',
      dep.removal_condition?`Retrait : ${esc(dep.removal_condition)}.`:'',
      dep.since?`Depuis : ${esc(dep.since)}.`:'',
      dep.legacy_doc?`Note : <code>${esc(dep.legacy_doc)}</code>.`:'',
    ].filter(Boolean).join(' ');
    return `<div class="notice mcpi-dep" role="note"><strong>Outil déprécié.</strong> ${facts}</div>`;
  }
  function detailHtml(tool){
    const side=SIDE_EFFECTS[tool.side_effect];
    const atom=ATOMICITY[tool.atomicity];
    const output=tool.output||{};
    const notes=Array.isArray(output.notes)?output.notes:[];
    const rules=Array.isArray(tool.parameter_rules)?tool.parameter_rules:[];
    const facts=[
      ['Nom complet',`<code>${esc(tool.qualified_name)}</code>`],
      ['Effet',side?`${esc(side.label)} — ${esc(side.means)}`:esc(tool.side_effect)],
      ['Atomicité',atom?`${esc(atom.label)} — ${esc(atom.means)}`:esc(tool.atomicity)],
      ['Idempotent',tool.idempotent?'oui — le même appel deux fois : le second ne change rien':'non'],
      ['Contexte modèle',`${esc(formatBytes(tool.context_bytes))} <span class="hint">(nom + description + schéma d’entrée)</span>`],
    ];
    const format=FORMATS[output.format]||`Format ${esc(output.format||'inconnu')}.`;
    return deprecationHtml(tool.deprecation)
      +`<div class="mcpi-desc">${paragraphs(bodyOf(tool))}</div>`
      +`<dl class="kv mcpi-facts">${facts.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`
      +`<section class="mcpi-sect"><h4>Paramètres</h4>${parametersHtml(tool)}</section>`
      +(rules.length?`<section class="mcpi-sect"><h4>Règles entre paramètres</h4><ul class="mcpi-rules">${rules.map(r=>`<li>${inline(r)}</li>`).join('')}</ul></section>`:'')
      +`<section class="mcpi-sect"><h4>Résultat</h4><p class="mcpi-format">${esc(format)}${output.advertised_schema===false&&output.format!=='text_lines'?' <span class="hint">Schéma tenu par le catalogue, non annoncé au modèle.</span>':''}</p>`
      +(notes.length?`<ul class="mcpi-notes">${notes.map(n=>`<li>${inline(n)}</li>`).join('')}</ul>`:'')
      +`${schemaHtml(output.schema)}</section>`
      +`<details class="mcpi-raw"><summary>Schéma brut (JSON)</summary>`
      +`<h5>Entrée</h5><pre>${esc(JSON.stringify(tool.input_schema,null,2))}</pre>`
      +`<h5>Résultat</h5><pre>${esc(JSON.stringify(output.schema??null,null,2))}</pre></details>`;
  }
  function detailLoadingHtml(elapsedMs){
    return '<div class="mcpi-skel" aria-hidden="true"><span></span><span></span><span></span></div>'
      +`<p class="tl-loading" role="status">Chargement du descripteur… <span>${esc(formatSeconds(elapsedMs))}</span></p>`;
  }
  function cardHtml(tool,index,{expanded=false,detail=null,why=null,now=0}={}){
    const id=`mcpi-${index}`;
    const key=toolKey(tool);
    let body='';
    if(expanded){
      if(!detail||detail.state==='loading')body=detailLoadingHtml(detail?now-detail.started:0);
      else if(detail.state==='error')body=errorHtml(detail.error,{retry:'detail',key});
      else body=detailHtml(detail.tool);
    }
    const params=tool.parameter_count
      ?`${plural(tool.parameter_count,'paramètre','paramètres')}${tool.required_count?` · ${tool.required_count} requis`:''}`
      :'sans paramètre';
    return `<li class="mcpi-row${expanded?' is-open':''}${tool.deprecated?' is-dep':''}" data-key="${esc(key)}">`
      +`<h3 class="mcpi-h"><button type="button" class="mcpi-toggle" id="${id}-t" data-key="${esc(key)}" aria-expanded="${expanded}" aria-controls="${id}-d">`
      +'<svg class="mcpi-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>'
      +`<span class="mcpi-cmain"><span class="mcpi-line"><span class="mcpi-label">${esc(tool.label)}</span><code class="mcpi-wire">${esc(tool.name)}</code></span>`
      +`<span class="mcpi-sum">${inline(tool.summary)}</span>`
      +`<span class="mcpi-meta">${esc(params)}${why?` · correspond au paramètre ${why.map(n=>`<code>${esc(n)}</code>`).join(', ')}`:''}</span></span>`
      +`<span class="mcpi-badges">${badgesHtml(tool)}</span></button></h3>`
      +`<div class="mcpi-detail" id="${id}-d" role="region" aria-labelledby="${id}-t"${expanded?'':' hidden'}>${body}</div></li>`;
  }

  /* ----------------------------------------------------- serveurs, onglets */
  function serverChipHtml(server){
    const st=stateOf(server.availability&&server.availability.state);
    const pending=server.availability&&server.availability.pending_restart===true;
    const tone=!server.described?'bad':pending?'warn':st.tone;
    const status=!server.described?`Non descriptible (${server.error||'erreur'})`:st.label;
    const title=[`${server.server} : ${server.described?st.means:'le module ne s’importe pas'}`,conditionText(server),
      pending?PENDING:'',`contexte modèle ${formatBytes(server.context_bytes)}`].filter(Boolean).join(' — ');
    return `<button type="button" class="mcpi-srv" data-tab="${esc(server.category)}" data-tone="${tone}" title="${esc(title)}">`
      +'<span class="mcpi-led" aria-hidden="true"></span>'
      +`<span class="mcpi-sname">${esc(server.server)}</span><span class="mcpi-sstate">${esc(status)}${pending?' · redémarrage':''}</span>`
      +`<span class="mcpi-bytes">${esc(plural(server.tool_count||0,'outil','outils'))} · ${esc(formatBytes(server.context_bytes))}</span></button>`;
  }
  function serversHtml(list){
    const servers=(list&&list.servers)||[];
    if(!servers.length)return '';
    return servers.map(serverChipHtml).join('');
  }
  function pendingNotice(list){
    const pending=pendingServers(list);
    if(!pending.length)return '';
    return `${PENDING} : ${pending.map(s=>s.server).join(', ')} — le brain en cours n’a pas la configuration du prochain lancement.`;
  }
  function tabsHtml(tabs,active,query){
    return tabs.map(t=>{
      const selected=t.category===active;
      const showCount=t.total>0;
      const count=showCount?`<span class="mcpi-n" aria-hidden="true">${query?`${t.count}/${t.total}`:t.total}</span>`:'';
      const spoken=query?`, ${t.count} sur ${t.total}`:t.total?`, ${plural(t.total,'outil','outils')}`:', vue d’ensemble';
      return `<button type="button" role="tab" id="mcpi-tab-${esc(t.category)}" data-tab="${esc(t.category)}" aria-selected="${selected}" `
        +`aria-controls="mcpiPanel" tabindex="${selected?0:-1}" aria-label="${esc(t.label+spoken)}">${esc(t.label)}${count}</button>`;
    }).join('');
  }

  /* L'onglet Général (§3) : vue d'ensemble, et l'endroit où vivront les outils
     transversaux — aucun aujourd'hui, ce que l'écran dit au lieu de le taire. */
  function generalHtml(list){
    const servers=(list&&list.servers)||[];
    const rows=servers.map(s=>{
      const st=stateOf(s.availability&&s.availability.state);
      const pending=s.availability&&s.availability.pending_restart===true;
      const category=((list.categories||[]).find(c=>c.category===s.category)||{}).label||s.category_label||s.category;
      return `<tr><th scope="row" data-label="Serveur"><code>${esc(s.server)}</code></th>`
        +`<td data-label="État">${s.described?chip(st.label,st.tone==='ok'?'on':'',st.means):chip('Non descriptible','bad',s.error||'')}`
        +`${pending?` <span class="mcpi-pend">${esc(PENDING)}</span>`:''}<div class="hint">${esc(s.described?st.means:`le module ne s’importe pas (${s.error||'erreur'}) : aucun outil n’est deviné`)}</div></td>`
        +`<td data-label="Déclaration">${esc(conditionText(s))}</td>`
        +`<td data-label="Outils" class="mcpi-num">${esc(String(s.tool_count||0))}</td>`
        +`<td data-label="Contexte" class="mcpi-num">${esc(formatBytes(s.context_bytes))}</td>`
        +`<td data-label="Onglet"><button type="button" class="action small" data-tab="${esc(s.category)}">${esc(category)}</button></td></tr>`;
    }).join('');
    const legend=[
      ...Object.values(SIDE_EFFECTS).map(v=>[chip(v.label,v.tone),v.means]),
      [chip(ATOMICITY.atomic_batch.label),ATOMICITY.atomic_batch.means],
      [chip('Idempotent'),'le même appel deux fois : le second ne change rien.'],
      [chip('Déprécié','warn'),'gardé pour compatibilité ; le détail nomme son remplaçant.'],
    ];
    return '<section class="mcpi-sect mcpi-first"><h4>Serveurs</h4>'
      +'<table class="mcpi-params mcpi-servtable"><caption>Serveurs MCP, état et coût de contexte</caption>'
      +'<thead><tr><th scope="col">Serveur</th><th scope="col">État</th><th scope="col">Déclaration</th><th scope="col">Outils</th><th scope="col">Contexte</th><th scope="col">Onglet</th></tr></thead>'
      +`<tbody>${rows}</tbody></table>`
      +'<p class="hint">Contexte : octets du nom, de la description et du schéma d’entrée de chaque outil, ce que le modèle lit à chaque tour.</p></section>'
      +'<section class="mcpi-sect"><h4>Outils transversaux</h4>'
      +'<p class="mcpi-empty-general">Aucun aujourd’hui : chaque outil natif appartient à un domaine (Étoiles / Scène, Réglages, Bare Hands) ou est externe. Cet onglet accueillera les outils qui servent plusieurs domaines.</p></section>'
      +`<section class="mcpi-sect"><h4>Lire une carte</h4><dl class="mcpi-legend">${legend.map(([k,v])=>`<dt>${k}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`
      +'<p class="hint">Inspection seulement : cet écran n’exécute aucun outil. Aucun outil de catalogue n’est annoncé au modèle.</p></section>';
  }

  /* Le corps de l'onglet actif : vue d'ensemble (Général), cartes, ou un vide
     qui dit pourquoi et où chercher. */
  function panelHtml({list,tab,query='',expanded,details,now=0,generalCategory='general'}){
    const open=expanded instanceof Set?expanded:new Set(expanded||[]);
    const entries=visibleTools(list,tab,query,details);
    const servers=((list&&list.servers)||[]).filter(s=>s.category===tab);
    let html=tab===generalCategory?generalHtml(list):'';
    for(const s of servers.filter(s=>!s.described)){
      html+=`<div class="notice bad" role="note"><strong>Descripteur indisponible</strong> : <code>${esc(s.server)}</code> ne s’importe pas (${esc(s.error||'erreur')}). Aucun outil n’est deviné.</div>`;
    }
    if(tab!==generalCategory&&servers.length){
      html+=`<p class="mcpi-srvline">${servers.filter(s=>s.described).map(s=>{
        const st=stateOf(s.availability&&s.availability.state);
        return `<code>${esc(s.server)}</code> · ${esc(st.means)} · ${esc(conditionText(s))}`
          +(s.availability&&s.availability.pending_restart?` · <span class="mcpi-pend">${esc(PENDING)}</span>`:'');
      }).join('<br>')}</p>`;
    }
    if(entries.length){
      html+=`<ul class="mcpi-list" aria-label="Outils">${entries.map(({tool,index,match})=>cardHtml(tool,index,{
        expanded:open.has(toolKey(tool)),detail:details&&details[toolKey(tool)],why:match.why,now})).join('')}</ul>`;
      return html;
    }
    const total=((list&&list.tools)||[]).filter(t=>t.category===tab).length;
    if(query){
      const elsewhere=tabsOf(list,query,details).filter(t=>t.category!==tab&&t.count>0);
      html+=`<div class="mcpi-empty" role="status"><p>Aucun outil de cet onglet ne correspond à « ${esc(query)} ».</p>`
        +(elsewhere.length
          ?`<p class="mcpi-jump">Ailleurs : ${elsewhere.map(t=>`<button type="button" class="action small" data-tab="${esc(t.category)}">${esc(t.label)} · ${t.count}</button>`).join(' ')}</p>`
          :`<p class="hint">Aucun autre onglet non plus. La recherche porte sur le nom, le libellé, le résumé et les noms de paramètres${indexing(list,details)}.</p>`)
        +'<button type="button" class="action small" data-act="clear">Effacer la recherche</button></div>';
    }else if(tab!==generalCategory&&!total&&!servers.some(s=>!s.described)){
      html+='<div class="mcpi-empty" role="status"><p>Aucun outil dans cette catégorie.</p></div>';
    }
    return html;
  }

  function indexing(list,details){
    const p=indexProgress(list,details);
    return p.done<p.total?` (descripteurs encore en lecture : ${p.done}/${p.total}, les paramètres des autres ne sont pas encore cherchables)`:'';
  }
  function listLoadingHtml(elapsedMs){
    return `<div class="mcpi-skel mcpi-skel-list" aria-hidden="true">${'<span></span>'.repeat(6)}</div>`
      +`<p class="tl-loading" role="status">Chargement du catalogue MCP… <span>${esc(formatSeconds(elapsedMs))}</span></p>`;
  }
  function statusView({loading,error,list,elapsedMs=0}){
    if(loading)return {tone:'busy',label:'Chargement…',detail:formatSeconds(elapsedMs)};
    if(error){const v=errorView(error);return {tone:'bad',label:v.title,detail:v.code}}
    if(!list)return {tone:'muted',label:'En attente',detail:''};
    const pending=pendingServers(list).length;
    const servers=(list.servers||[]).length,tools=(list.tools||[]).length;
    return {tone:pending?'warn':'live',label:pending?'Redémarrage en attente':'Catalogue lu',
      detail:`${plural(tools,'outil','outils')} · ${plural(servers,'serveur','serveurs')}`};
  }

  /* Petite file de chargement : au plus `limit` descripteurs en vol, jamais deux fois le même. */
  function createQueue(limit=PARALLEL){
    const waiting=[],queued=new Set();let running=0;
    function pump(){
      while(running<limit&&waiting.length){
        const {key,task}=waiting.shift();running++;
        Promise.resolve().then(task).catch(()=>{}).finally(()=>{running--;queued.delete(key);pump()});
      }
    }
    return {push(key,task){if(queued.has(key))return false;queued.add(key);waiting.push({key,task});pump();return true},
      size:()=>waiting.length+running};
  }

  return {ROUTE,DEADLINE_MS,PARALLEL,SIDE_EFFECTS,ATOMICITY,STATES,FORMATS,PENDING,ERRORS,
    esc,formatBytes,formatSeconds,toolKey,detailUrl,inline,plainSummary,createClient,errorView,errorHtml,
    stateOf,conditionText,pendingServers,normalize,parameterNames,matchOf,tabsOf,visibleTools,indexProgress,tabKey,cardKey,
    schemaModel,typeLabel,schemaHtml,constraintSummary,parametersHtml,badgesHtml,detailHtml,cardHtml,
    serversHtml,pendingNotice,tabsHtml,generalHtml,panelHtml,listLoadingHtml,statusView,createQueue};
})();

/* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
if(typeof module!=='undefined'&&module.exports)module.exports=JarvisMcpInspectorCore;

/* --------------------------------------------------------------------------
   Bloc navigateur : vue plein écran, chargement paresseux des descripteurs,
   clavier. Les tests node le font tourner sur un DOM simulé.
   -------------------------------------------------------------------------- */
(function installJarvisMcpInspector(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const M=JarvisMcpInspectorCore;
  const root=document.getElementById('mcpInspector');
  if(!root)return;
  const q=s=>root.querySelector(s);
  const el={
    open:document.getElementById('openMcpInspector'),close:q('#mcpiClose'),refresh:q('#mcpiRefresh'),
    expandAll:q('#mcpiExpandAll'),search:q('#mcpiSearch'),status:q('#mcpiStatus'),
    statusLabel:q('#mcpiStatusLabel'),statusDetail:q('#mcpiStatusDetail'),notice:q('#mcpiNotice'),
    servers:q('#mcpiServers'),tabs:q('#mcpiTabs'),panel:q('#mcpiPanel'),announce:q('#mcpiAnnounce'),
  };
  const TICK_MS=250;
  const S={open:false,inerted:[],returnFocus:null,generation:0,tick:null,
    list:null,listError:null,loading:false,loadStarted:0,
    tab:'general',query:'',expanded:new Set(),details:{}};
  const client=M.createClient({fetchImpl:(path,options)=>window.fetch(path,options)});
  const queue=M.createQueue(M.PARALLEL);

  function failed(what,error){
    const view=M.errorView(error);
    if(typeof console!=='undefined'&&console.warn)console.warn('mcp.inspector.failed',what,view.code,view.status,view.message);
  }
  function announce(text){el.announce.textContent=text}
  function toolByKey(key){return ((S.list&&S.list.tools)||[]).find(t=>M.toolKey(t)===key)||null}

  /* ------------------------------------------------------------ rendu */
  function renderStatus(){
    const view=M.statusView({loading:S.loading,error:S.listError,list:S.list,elapsedMs:Date.now()-S.loadStarted});
    el.status.dataset.tone=view.tone;
    el.statusLabel.textContent=view.label;
    let detail=view.detail;
    if(S.query&&S.list){
      const p=M.indexProgress(S.list,S.details);
      if(p.done<p.total)detail+=` · paramètres indexés ${p.done}/${p.total}`;
    }
    el.statusDetail.textContent=detail;
  }
  function renderHead(){
    el.servers.innerHTML=S.list?M.serversHtml(S.list):'';
    el.servers.hidden=!S.list;
    const pending=S.list?M.pendingNotice(S.list):'';
    el.notice.hidden=!pending;el.notice.textContent=pending;
  }
  function renderTabs(){
    if(!S.list){el.tabs.innerHTML='';el.tabs.hidden=true;return}
    el.tabs.hidden=false;
    el.tabs.innerHTML=M.tabsHtml(M.tabsOf(S.list,S.query,S.details),S.tab,S.query);
    el.panel.setAttribute('aria-labelledby',`mcpi-tab-${S.tab}`);
  }
  /* Le rendu remplace le HTML du panneau : l'élément qui avait le focus est
     retrouvé par son identifiant, pour que déplier au clavier ne le perde pas. */
  function renderPanel(){
    const active=document.activeElement;
    const focusId=active&&root.contains&&root.contains(active)&&active.id?active.id:null;
    if(S.loading&&!S.list)el.panel.innerHTML=M.listLoadingHtml(Date.now()-S.loadStarted);
    else if(S.listError&&!S.list)el.panel.innerHTML=M.errorHtml(S.listError,{retry:'list'});
    else if(S.list)el.panel.innerHTML=M.panelHtml({list:S.list,tab:S.tab,query:S.query,expanded:S.expanded,details:S.details,now:Date.now()});
    else el.panel.innerHTML='';
    const allOpen=visibleKeys().length>0&&visibleKeys().every(k=>S.expanded.has(k));
    el.expandAll.textContent=allOpen?'Tout replier':'Tout déplier';
    el.expandAll.disabled=!visibleKeys().length;
    if(focusId){const back=document.getElementById(focusId);if(back&&back!==active&&typeof back.focus==='function')back.focus({preventScroll:true})}
  }
  function render(){renderStatus();renderHead();renderTabs();renderPanel()}
  function visibleKeys(){
    if(!S.list)return [];
    return M.visibleTools(S.list,S.tab,S.query,S.details).map(e=>M.toolKey(e.tool));
  }
  /* Un seul minuteur, actif seulement pendant une attente : il fait avancer les secondes affichées. */
  function waiting(){return S.loading||Object.values(S.details).some(d=>d.state==='loading')}
  function tick(){
    if(!S.open||!waiting()){clearInterval(S.tick);S.tick=null;return}
    renderStatus();
    if(S.loading&&!S.list){renderPanel();return}
    for(const key of S.expanded){
      const d=S.details[key];
      if(d&&d.state==='loading'){
        const node=el.panel.querySelector(`.mcpi-row[data-key="${key.replace(/["\\]/g,'\\$&')}"] .tl-loading span`);
        if(node)node.textContent=M.formatSeconds(Date.now()-d.started);
      }
    }
  }
  function armTick(){if(!S.tick&&S.open)S.tick=setInterval(tick,TICK_MS)}

  /* ------------------------------------------------------------ lecture */
  async function loadList(){
    const generation=++S.generation;
    S.loading=true;S.listError=null;S.loadStarted=Date.now();
    armTick();render();
    try{
      const list=await client.list();
      if(generation!==S.generation)return;
      S.list=list;S.listError=null;
      if(!(list.categories||[]).some(c=>c.category===S.tab))S.tab=((list.categories||[])[0]||{}).category||'general';
      announce(`Catalogue MCP : ${(list.tools||[]).length} outils.`);
    }catch(error){
      if(generation!==S.generation)return;
      S.listError=error;failed('liste',error);
      announce(`Catalogue MCP indisponible : ${M.errorView(error).title}.`);
    }finally{
      if(generation===S.generation){S.loading=false;render();if(S.query)indexAll()}
    }
  }
  function loadDetail(key){
    const current=S.details[key];
    if(current&&(current.state==='ok'||current.state==='loading'))return;
    const tool=toolByKey(key);
    if(!tool)return;
    S.details[key]={state:'loading',started:Date.now()};
    armTick();
    queue.push(key,async()=>{
      S.details[key]={state:'loading',started:Date.now()};
      try{
        const body=await client.detail(tool.server,tool.name);
        S.details[key]={state:'ok',tool:body.tool};
      }catch(error){
        S.details[key]={state:'error',error};failed(`détail ${key}`,error);
      }finally{if(S.open){renderStatus();renderTabs();renderPanel()}}
    });
  }
  /* Première recherche : on lit tous les descripteurs (file bornée) pour que
     les noms de paramètres soient cherchables ; l'état dit où en est l'index. */
  function indexAll(){
    if(!S.list)return;
    for(const tool of S.list.tools||[])loadDetail(M.toolKey(tool));
  }

  /* ------------------------------------------------------------ actions */
  function toggle(key){
    if(S.expanded.has(key))S.expanded.delete(key);
    else{S.expanded.add(key);loadDetail(key)}
    renderPanel();
  }
  function toggleAll(){
    const keys=visibleKeys();
    const allOpen=keys.length&&keys.every(k=>S.expanded.has(k));
    for(const key of keys){
      if(allOpen)S.expanded.delete(key);
      else{S.expanded.add(key);loadDetail(key)}
    }
    renderPanel();
    announce(allOpen?`${keys.length} outils repliés.`:`${keys.length} outils dépliés.`);
  }
  function selectTab(category,{focus=false}={}){
    if(!S.list||!(S.list.categories||[]).some(c=>c.category===category))return;
    S.tab=category;renderTabs();renderPanel();
    if(focus){const tab=document.getElementById(`mcpi-tab-${category}`);if(tab)tab.focus()}
  }
  function setQuery(value){
    S.query=String(value||'');
    renderStatus();renderTabs();renderPanel();
    if(S.query)indexAll();
    if(S.list&&S.query){
      const n=M.tabsOf(S.list,S.query,S.details).reduce((sum,t)=>sum+t.count,0);
      announce(`${n} outil${n===1?'':'s'} correspond${n===1?'':'ent'} à « ${S.query} ».`);
    }
  }

  /* ------------------------------------------------------------ ouverture */
  function openView(){
    if(S.open)return;
    S.open=true;S.returnFocus=document.activeElement;
    root.hidden=false;
    S.inerted=[...document.body.children].filter(n=>n!==root&&!n.inert&&n.tagName!=='SCRIPT');
    for(const node of S.inerted)node.inert=true;
    if(el.open){el.open.classList.add('active');el.open.setAttribute('aria-expanded','true')}
    if(!S.list||S.listError)loadList();else{render();armTick()}
    requestAnimationFrame(()=>el.search.focus({preventScroll:true}));
  }
  function closeView(){
    if(!S.open)return;
    S.open=false;
    clearInterval(S.tick);S.tick=null;
    for(const node of S.inerted)node.inert=false;
    S.inerted=[];
    root.hidden=true;
    if(el.open){el.open.classList.remove('active');el.open.setAttribute('aria-expanded','false')}
    const back=el.open||S.returnFocus;S.returnFocus=null;
    if(back&&back.isConnected!==false&&typeof back.focus==='function')back.focus({preventScroll:true});
  }
  function refresh(){S.details={};loadList();for(const key of S.expanded)loadDetail(key)}

  /* ------------------------------------------------------------ branchement */
  if(el.open)el.open.addEventListener('click',()=>{root.hidden?openView():closeView()});
  el.close.addEventListener('click',closeView);
  el.refresh.addEventListener('click',refresh);
  el.expandAll.addEventListener('click',toggleAll);
  el.search.addEventListener('input',()=>setQuery(el.search.value));
  el.servers.addEventListener('click',event=>{
    const chipButton=event.target.closest('[data-tab]');
    if(chipButton)selectTab(chipButton.dataset.tab,{focus:true});
  });
  el.tabs.addEventListener('click',event=>{
    const tab=event.target.closest('[role="tab"]');
    if(tab)selectTab(tab.dataset.tab);
  });
  el.tabs.addEventListener('keydown',event=>{
    const tabs=[...el.tabs.querySelectorAll('[role="tab"]')];
    const index=tabs.findIndex(t=>t.dataset.tab===S.tab);
    const next=M.tabKey(event.key,index,tabs.length);
    if(next===null)return;
    event.preventDefault();
    selectTab(tabs[next].dataset.tab,{focus:true});
  });
  el.panel.addEventListener('click',event=>{
    const target=event.target.closest('button');
    if(!target)return;
    if(target.classList.contains('mcpi-toggle')){toggle(target.dataset.key);return}
    if(target.dataset.act==='retry'){
      if(target.dataset.retry==='detail'){delete S.details[target.dataset.key];loadDetail(target.dataset.key);renderPanel()}
      else loadList();
      return;
    }
    if(target.dataset.act==='clear'){el.search.value='';setQuery('');el.search.focus();return}
    if(target.dataset.tab)selectTab(target.dataset.tab,{focus:true});
  });
  el.panel.addEventListener('keydown',event=>{
    const current=event.target.closest&&event.target.closest('.mcpi-toggle');
    if(!current)return;
    const toggles=[...el.panel.querySelectorAll('.mcpi-toggle')];
    const next=M.cardKey(event.key,toggles.indexOf(current),toggles.length);
    if(next===null)return;
    event.preventDefault();
    toggles[next].focus();
  });
  root.addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeView();return}
    if(event.key==='/'&&event.target!==el.search&&!(event.target&&/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName||''))){
      event.preventDefault();el.search.focus();return;
    }
    if(event.key!=='Tab')return;
    const focusable=[...root.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea,summary,[tabindex]')]
      .filter(node=>node.offsetParent!==null&&node.tabIndex>=0);
    if(!focusable.length)return;
    const first=focusable[0],last=focusable[focusable.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
  });

  window.JarvisMcpInspector={open:openView,close:closeView,state:S};
})();
