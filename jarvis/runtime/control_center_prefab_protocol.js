/* Protocole des cadres de prefab `jv: 1` (handoff jarvis-scene-window-prefab-foundation,
   Slice 03). Logique PURE : ni DOM, ni réseau, ni minuterie. Exposé en
   `window.JarvisPrefabProtocol` dans la page et en `module.exports` pour node.

   - `SANDBOX` : la seule valeur d'attribut `sandbox` d'un cadre. Jamais
     `allow-same-origin`, `allow-popups`, `allow-forms`, `allow-top-navigation`
     ni `allow-modals` (docs/prefabs.md › *Runtime*).
   - `buildSrcdoc(bundle)` : le document d'un cadre, dans l'ordre du contrat
     (charset, CSP, shell.css, style du prefab, gabarit, shim, comportement
     enveloppé par le chargeur du shim). Le CSP précède tout ce qui peut
     charger quoi que ce soit.
   - `parseFrameMessage(data)` : un message cadre→hôte validé, ou la raison
     du refus. Tout ce qui n'est pas `{jv: 1, type, ...}` exact est refusé.
   - `hostMessage(type, fields)` : un message hôte→cadre (`init`, `update`,
     `teardown`), copie JSON des seules valeurs de l'instance.
   - `isAllowedUrl(url)` : règle des liens de la scène (`JarvisSceneLayout.linkOf` :
     http/https, sans identifiants, ≤ 2048) MOINS les hôtes locaux et privés
     (`isPrivateHost`) : un cadre ne fait pas ouvrir à l'utilisateur une adresse
     de son poste ou de son réseau (Core, Control Center, routeur, métadonnées).
     `linkOf` lui-même ne change pas : la scène garde ses liens locaux.
   - Bornes AVANT travail : un message trop gros est refusé sans sérialisation
     ni expression régulière sur sa taille (`exceedsJsonBytes`, découpe d'un
     message d'erreur avant nettoyage).
   - `markdownBlocksOf(manifest, props, data)` : pour chaque entrée déclarée
     `{"type": "text", "format": "markdown"}`, ses blocs
     (`JarvisSceneLayout.markdownBlocks`, le seul analyseur) par chemin
     (`data.notes`, `data.items.0.note`). Les valeurs elles-mêmes restent du
     texte : ce que le cadre renvoie dans un événement d'état reste exact. */
(function(root){
  'use strict';
  const Layout=root.JarvisSceneLayout||(typeof require==='function'?require('./control_center_scene_layout.js'):null);
  const JV=1;
  const SANDBOX='allow-scripts';
  const CSP="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'";
  const HOST_TYPES=Object.freeze(['init','update','teardown']);
  const FRAME_TYPES=Object.freeze(['ready','event','resize','open_url','error']);
  const MODES=Object.freeze(['scene','preview']);
  const MAX_ERROR_CHARS=300;
  const MAX_EVENT_PAYLOAD_BYTES=8*1024;
  const MAX_URL_CHARS=2048;
  const RESIZE_MIN=24;
  const RESIZE_MAX=4000;
  const EVENT_NAME=/^[a-z][a-z0-9_]{0,39}$/;
  const EVENT_NAME_MAX=40;
  /* Champs exacts de chaque message du cadre, en plus de `jv` et `type`. */
  const FRAME_FIELDS=Object.freeze({ready:[],event:['name','payload'],resize:['height'],open_url:['url'],error:['message']});
  /* Fermetures qui sortiraient d'un bloc de style ou de script du document : neutralisées.
     Ce fichier est inséré dans le bloc de script de la page : il n'écrit jamais en
     clair une balise de script ni une ouverture de commentaire HTML (test statique). */
  const STYLE_CLOSE=/<\/(style)/gi;
  const SCRIPT_CLOSE=/<\/(script)/gi;
  const COMMENT_OPEN=/<!\-\-/g;

  function isPlainObject(value){
    return value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.getPrototypeOf(value)===Object.prototype;
  }

  /* Taille UTF-8 d'une valeur JSON, ou -1 si elle n'en est pas une. */
  function jsonBytes(value){
    let text;
    try{text=JSON.stringify(value)}catch(_error){return -1}
    if(typeof text!=='string')return -1;
    let bytes=0;
    for(let i=0;i<text.length;i++){
      const code=text.charCodeAt(i);
      if(code<0x80)bytes+=1;
      else if(code<0x800)bytes+=2;
      else if(code>=0xd800&&code<=0xdbff){bytes+=4;i++}
      else bytes+=3;
    }
    return bytes;
  }

  /* Vrai si le JSON de `value` dépasse À COUP SÛR `limit` octets, sans le
     produire : parcours itératif qui compte une borne basse (longueur des
     chaînes et des clés, ponctuation) et s'arrête dès qu'elle dépasse. Coût
     O(limit) quelle que soit la taille du message ; un cycle fait grossir la
     borne à chaque passage, donc s'arrête aussi. */
  function exceedsJsonBytes(value,limit){
    let total=0;
    const stack=[value];
    while(stack.length){
      const item=stack.pop();
      if(typeof item==='string')total+=item.length+2;
      else if(item!==null&&typeof item==='object'){
        total+=2;
        if(Array.isArray(item)){
          total+=Math.max(0,item.length-1);  // les virgules
          if(total>limit)return true;
          for(let i=0;i<item.length;i++)stack.push(item[i]);
        }else{
          for(const key in item){
            /* `undefined` n'est pas écrit par JSON : la borne reste une borne basse. */
            if(!Object.prototype.hasOwnProperty.call(item,key)||item[key]===undefined)continue;
            total+=key.length+3;
            if(total>limit)return true;
            stack.push(item[key]);
          }
        }
      }else total+=1;
      if(total>limit)return true;
    }
    return false;
  }

  function cloneJson(value){
    return value===undefined?undefined:JSON.parse(JSON.stringify(value));
  }

  function bounded(text,limit){
    const value=String(text);
    return value.length<=limit?value:value.slice(0,limit-1)+'…';
  }

  /* Hôte (forme normalisée de `URL.hostname`) local, privé, lien-local ou non
     spécifié : 127/8, 0/8, 10/8, 172.16/12, 192.168/16, 169.254/16,
     `localhost` et `*.localhost`, ::, ::1, fc00::/7, fe80::/10 et les IPv4
     privées écrites en IPv6 (`::ffff:a.b.c.d`). Le parseur URL a déjà ramené
     `2130706433`, `0x7f.1` ou `127.1` à `127.0.0.1`. */
  function isPrivateHost(hostname){
    const host=String(hostname||'').toLowerCase().replace(/\.$/,'');
    if(host==='localhost'||host.endsWith('.localhost'))return true;
    const v4=/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
    if(v4)return privateV4(Number(v4[1]),Number(v4[2]));
    if(!host.startsWith('['))return false;
    const v6=host.slice(1,-1);
    if(v6==='::'||v6==='::1')return true;
    if(/^f[cd][0-9a-f]{0,2}:/.test(v6)||/^fe[89ab][0-9a-f]?:/.test(v6))return true;
    const mapped=/^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(v6);
    if(mapped){const high=parseInt(mapped[1],16);return privateV4(high>>8,high&255)}
    return false;
  }

  function privateV4(a,b){
    return a===127||a===0||a===10||(a===172&&b>=16&&b<=31)||(a===192&&b===168)||(a===169&&b===254);
  }

  function isAllowedUrl(url){
    if(typeof url!=='string'||url.length>MAX_URL_CHARS||!Layout)return false;
    const link=Layout.linkOf(url);
    return link!==null&&!isPrivateHost(link.host);
  }

  /* Le texte d'un bloc de style ou de script ne peut pas fermer son bloc. Le
     lint du domaine refuse déjà une balise de fin de script dans un comportement ; ceci tient
     aussi pour le style et le shim, sans dépendre du lint (qui n'est pas la
     frontière de sécurité : le bac à sable l'est). */
  function styleText(text){return String(text||'').replace(STYLE_CLOSE,'<\\/$1')}
  function scriptText(text){return String(text||'').replace(SCRIPT_CLOSE,'<\\/$1').replace(COMMENT_OPEN,'<\\!--')}

  /* Paquet de version (`GET /api/prefabs/{id}/{version}/bundle`) -> document du cadre.
     Lève une `Error` nommée si le paquet est incomplet : l'hôte l'affiche. */
  function buildSrcdoc(bundle){
    const files=bundle&&bundle.files,runtime=bundle&&bundle.runtime;
    if(!isPlainObject(files)||typeof files.template!=='string'||typeof files.style!=='string'||typeof files.behavior!=='string'){
      throw new Error('bundle has no template, style and behavior');
    }
    if(!isPlainObject(runtime)||typeof runtime.shim!=='string'||typeof runtime.shell_css!=='string'){
      throw new Error('bundle has no runtime (shim, shell.css)');
    }
    const close='<'+'/script>';
    return '<!doctype html><html><head>'
      +'<meta charset="utf-8">'
      +'<meta http-equiv="Content-Security-Policy" content="'+CSP+'">'
      +'<style data-jv="shell">'+styleText(runtime.shell_css)+'</style>'
      +'<style data-jv="prefab">'+styleText(files.style)+'</style>'
      +'</head><body class="jv-body">'+files.template
      +'<'+'script data-jv="shim">'+scriptText(runtime.shim)+close
      +'<'+'script data-jv="behavior">__jvLoad(function(jarvis){\n'+scriptText(files.behavior)+'\n});'+close
      +'</body></html>';
  }

  function refuse(reason){return {ok:false,reason}}

  /* Message reçu d'un cadre -> `{ok: true, message}` normalisé, ou `{ok: false, reason}`. */
  function parseFrameMessage(data){
    if(!isPlainObject(data))return refuse('not an object');
    if(data.jv!==JV)return refuse('not jv:1');
    if(!FRAME_TYPES.includes(data.type))return refuse('unknown type');
    const allowed=FRAME_FIELDS[data.type];
    for(const key of Object.keys(data)){
      if(key!=='jv'&&key!=='type'&&!allowed.includes(key))return refuse(`unexpected field ${bounded(key,40)}`);
    }
    switch(data.type){
      case 'ready':return {ok:true,message:{type:'ready'}};
      case 'event':{
        if(typeof data.name!=='string'||data.name.length>EVENT_NAME_MAX||!EVENT_NAME.test(data.name))return refuse('event name');
        if(!isPlainObject(data.payload))return refuse('event payload must be an object');
        if(exceedsJsonBytes(data.payload,MAX_EVENT_PAYLOAD_BYTES))return refuse('event payload too large');
        const bytes=jsonBytes(data.payload);
        if(bytes<0)return refuse('event payload is not JSON');
        if(bytes>MAX_EVENT_PAYLOAD_BYTES)return refuse('event payload too large');
        return {ok:true,message:{type:'event',name:data.name,payload:cloneJson(data.payload)}};
      }
      case 'resize':{
        if(typeof data.height!=='number'||!Number.isFinite(data.height))return refuse('resize height');
        return {ok:true,message:{type:'resize',height:Math.round(Math.min(RESIZE_MAX,Math.max(RESIZE_MIN,data.height)))}};
      }
      case 'open_url':
        if(!isAllowedUrl(data.url))return refuse('url refused');
        return {ok:true,message:{type:'open_url',url:Layout.linkOf(data.url).href}};
      case 'error':{
        /* Découpé AVANT le nettoyage : le coût ne dépend pas de la taille envoyée. */
        const raw=typeof data.message==='string'?data.message.slice(0,MAX_ERROR_CHARS*2):'';
        const text=raw?raw.replace(/[\u0000-\u001f\u007f]+/g,' ').trim():'';
        return {ok:true,message:{type:'error',message:bounded(text||'unknown error',MAX_ERROR_CHARS)}};
      }
    }
    return refuse('unknown type');
  }

  /* Message hôte -> cadre. Seuls les champs du contrat ; valeurs copiées en JSON. */
  function hostMessage(type,fields){
    if(!HOST_TYPES.includes(type))throw new Error(`unknown host message ${type}`);
    const f=fields||{};
    if(type==='teardown')return {jv:JV,type};
    const message={jv:JV,type,props:cloneJson(f.props||{}),data:cloneJson(f.data||{}),theme:cloneJson(f.theme||{}),
      blocks:cloneJson(f.blocks||{})};
    if(type==='init'){
      const instance=f.instance||{},prefab=instance.prefab||{};
      if(!MODES.includes(instance.mode))throw new Error('instance mode must be scene or preview');
      message.instance={object_id:String(instance.object_id||''),prefab:{id:String(prefab.id||''),version:prefab.version|0},
        mode:instance.mode};
    }
    return message;
  }

  /* Chemins des entrées markdown d'un schéma objet (`inputs.props`/`inputs.data`),
     `*` pour un élément de tableau. */
  function markdownPaths(schema,prefix,out){
    if(!isPlainObject(schema))return out;
    if(schema.type==='text'&&schema.format==='markdown'){out.push(prefix);return out}
    if(schema.type==='object'&&isPlainObject(schema.properties)){
      for(const [name,child] of Object.entries(schema.properties))markdownPaths(child,`${prefix}.${name}`,out);
    }else if(schema.type==='array'&&isPlainObject(schema.items)){
      markdownPaths(schema.items,`${prefix}.*`,out);
    }
    return out;
  }

  function collect(value,parts,path,out){
    if(!parts.length){
      if(typeof value==='string')out[path]=Layout.markdownBlocks(value);
      return;
    }
    const [head,...rest]=parts;
    if(head==='*'){
      if(Array.isArray(value))value.forEach((item,index)=>collect(item,rest,`${path}.${index}`,out));
    }else if(isPlainObject(value)&&Object.prototype.hasOwnProperty.call(value,head)){
      collect(value[head],rest,`${path}.${head}`,out);
    }
  }

  function markdownBlocksOf(manifest,props,data){
    const out={};
    const inputs=manifest&&manifest.inputs;
    if(!isPlainObject(inputs)||!Layout)return out;
    const roots={props,data};
    for(const name of ['props','data']){
      for(const path of markdownPaths(inputs[name],name,[])){
        collect(roots[name],path.split('.').slice(1),name,out);
      }
    }
    return out;
  }

  /* Événements déclarés d'un manifeste : nom -> {class, writes}. */
  function declaredEvents(manifest){
    const out=new Map();
    const events=manifest&&manifest.events;
    if(!isPlainObject(events))return out;
    for(const [name,decl] of Object.entries(events)){
      if(isPlainObject(decl))out.set(name,{class:decl.class,writes:Array.isArray(decl.writes)?decl.writes.slice():[]});
    }
    return out;
  }

  const api=Object.freeze({JV,SANDBOX,CSP,HOST_TYPES,FRAME_TYPES,MODES,MAX_ERROR_CHARS,MAX_EVENT_PAYLOAD_BYTES,RESIZE_MIN,RESIZE_MAX,
    EVENT_NAME,isPlainObject,jsonBytes,exceedsJsonBytes,cloneJson,isPrivateHost,isAllowedUrl,buildSrcdoc,parseFrameMessage,hostMessage,markdownPaths,
    markdownBlocksOf,declaredEvents});
  root.JarvisPrefabProtocol=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
