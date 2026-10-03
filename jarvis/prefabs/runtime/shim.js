/* Runtime d'un cadre de prefab : l'API `window.jarvis` et le protocole `jv: 1`
   (handoff jarvis-scene-window-prefab-foundation, Slice 03 ; docs/prefabs.md ›
   *Message protocol*). Injecté par l'hôte dans chaque cadre, avant le
   comportement du prefab, qu'il charge (`window.__jvLoad`).

   `createShim(env)` est la fabrique, testée par node avec un faux DOM :
   `env.post(message)` envoie à l'hôte, `env.listen(fn)` reçoit les messages
   de l'hôte, `env.document`, `env.ResizeObserver` (facultatif). Le
   démarrage en bas de fichier la branche sur le vrai cadre.

   API du comportement (`jarvis`) :
   - `on('init'|'update'|'teardown', fn)` -> fonction de désabonnement ;
   - `emit(name, payload)` : un événement déclaré par le manifeste ;
   - `props`, `data`, `theme`, `instance` : instantanés figés, en lecture seule ;
   - `blocks(path)` : blocs markdown d'une entrée `format: markdown`
     (`data.notes`), calculés par l'hôte avec l'analyseur de la page ;
   - `renderBlocks(el, blocks)` : ces blocs en DOM, par `textContent` seulement ;
   - `openUrl(url)` : l'hôte valide (http/https) et ouvre un nouvel onglet ;
   - liaisons `data-jv-text="props.x"` (texte) et `data-jv-markdown="data.y"`
     (blocs), réappliquées à chaque `init`/`update` ;
   - variables CSS du thème (`--jv-accent`, `--jv-text`, `--jv-muted`,
     `--jv-surface`, `--jv-scale`) et `--jv-prop-<nom>` pour chaque prop de
     premier niveau de forme `#rrggbb` (une entrée `color`, déjà validée par
     Core) ; une prop `accent` couleur remplace `--jv-accent` ;
   - hauteur du contenu envoyée à l'hôte (`resize`) à chaque changement ;
   - `data-jv-more` sur la racine tant qu'il reste du contenu sous le bord du
     cadre (défilement, taille) : la coquille y dessine un fondu ;
   - toute exception du comportement (chargement, gestionnaire, `onerror`,
     `onunhandledrejection`) devient un message `error` (≤ 300 caractères). */
(function(root){
  'use strict';
  var JV=1;
  var HOOKS=['init','update','teardown'];
  var EVENT_NAME=/^[a-z][a-z0-9_]{0,39}$/;
  var COLOR=/^#[0-9a-fA-F]{6}$/;
  var PROP_NAME=/^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
  var MAX_ERROR_CHARS=300;
  var MAX_ERRORS=20;
  var MAX_EVENT_BYTES=8*1024;
  var THEME_VARS={accent:'--jv-accent',text:'--jv-text',muted:'--jv-muted',surface:'--jv-surface',scale:'--jv-scale'};

  function isPlainObject(value){
    return value!==null&&typeof value==='object'&&!Array.isArray(value);
  }

  function deepFreeze(value){
    if(value&&typeof value==='object'){
      Object.freeze(value);
      Object.keys(value).forEach(function(key){deepFreeze(value[key])});
    }
    return value;
  }

  function snapshot(value){
    return deepFreeze(JSON.parse(JSON.stringify(value===undefined?{}:value)));
  }

  function utf8Bytes(text){
    var bytes=0;
    for(var i=0;i<text.length;i++){
      var code=text.charCodeAt(i);
      if(code<0x80)bytes+=1;else if(code<0x800)bytes+=2;else if(code>=0xd800&&code<=0xdbff){bytes+=4;i++}else bytes+=3;
    }
    return bytes;
  }

  function describe(error){
    if(error&&typeof error==='object'&&typeof error.message==='string'){
      return (error.name&&error.name!=='Error'?error.name+': ':'')+error.message;
    }
    return String(error);
  }

  function lookup(state,path){
    var parts=String(path||'').split('.');
    var value=state[parts[0]];
    if(parts[0]!=='props'&&parts[0]!=='data')return undefined;
    for(var i=1;i<parts.length;i++){
      if(value===null||typeof value!=='object')return undefined;
      value=value[parts[i]];
    }
    return value;
  }

  function textOf(value){
    if(value===undefined||value===null)return '';
    if(typeof value==='object')return JSON.stringify(value);
    return String(value);
  }

  function createShim(env){
    var doc=env.document;
    var state={props:snapshot({}),data:snapshot({}),theme:snapshot({}),instance:null,blocks:{}};
    var seen={props:'{}',data:'{}',theme:'{}',blocks:'{}'};
    var handlers={init:[],update:[],teardown:[]};
    var loaded=false,started=false,closed=false;
    var errors=0,lastHeight=-1,observer=null;

    function post(message){
      if(closed&&message.type!=='error')return;
      try{env.post(message)}catch(_error){/* intentional: the host is gone (frame being removed); nothing to tell */}
    }

    function reportError(error){
      if(errors>=MAX_ERRORS)return;
      errors+=1;
      var text=describe(error).replace(/[\u0000-\u001f\u007f]+/g,' ').trim()||'unknown error';
      if(text.length>MAX_ERROR_CHARS)text=text.slice(0,MAX_ERROR_CHARS-1)+'…';
      post({jv:JV,type:'error',message:text});
    }

    function call(hook,arg){
      handlers[hook].slice().forEach(function(fn){
        try{
          var result=fn(arg);
          if(result&&typeof result.then==='function')result.then(null,reportError);
        }catch(error){reportError(error)}
      });
    }

    /* ---------------------------------------------------------- DOM */

    function element(tag,className,text){
      var el=doc.createElement(tag);
      if(className)el.className=className;
      if(text!==undefined)el.textContent=text;
      return el;
    }

    function spanNode(span){
      var node=doc.createTextNode(span.text);
      function wrap(tag,className){var el=element(tag,className);el.appendChild(node);node=el}
      if(span.code)wrap('code','jv-md-code');
      if(span.italic)wrap('em');
      if(span.bold)wrap('strong');
      if(span.strike)wrap('s');
      if(span.href){
        /* Pas d'attribut `href` : un cadre ne navigue jamais. Le lien demande à l'hôte de l'ouvrir. */
        wrap('a','jv-md-link');
        var href=span.href;
        node.setAttribute('role','link');
        node.setAttribute('tabindex','0');
        node.setAttribute('title',span.host||href);
        node.addEventListener('click',function(event){event.preventDefault();api.openUrl(href)});
        node.addEventListener('keydown',function(event){if(event.key==='Enter'){event.preventDefault();api.openUrl(href)}});
      }
      return node;
    }

    function appendSpans(el,spans){
      (spans||[]).forEach(function(span){el.appendChild(spanNode(span))});
      return el;
    }

    /* Miroir de `appendBlocks` de la page (control_center_scene_page.js), classes `jv-md-*`. */
    function appendBlocks(parent,blocks){
      (blocks||[]).forEach(function(block){
        if(block.kind==='hr'){parent.appendChild(element('hr','jv-md-hr'));return}
        if(block.kind==='code'){
          var pre=element('pre','jv-md-pre');
          pre.appendChild(element('code',null,block.text));
          parent.appendChild(pre);return;
        }
        if(block.kind==='h'){
          parent.appendChild(appendSpans(element('div','jv-md-h jv-md-h'+Math.min(3,block.level)),block.spans));
          return;
        }
        if(block.kind==='quote'){
          var quote=element('blockquote','jv-md-quote');
          appendBlocks(quote,block.blocks);
          parent.appendChild(quote);return;
        }
        if(block.kind==='list'){
          var list=element(block.ordered?'ol':'ul','jv-md-list');
          if(block.ordered&&block.start>1)list.setAttribute('start',String(block.start));
          (block.items||[]).forEach(function(item){
            var li=element('li');
            appendBlocks(li,item.blocks);
            list.appendChild(li);
          });
          parent.appendChild(list);return;
        }
        parent.appendChild(appendSpans(element('p','jv-md-p'),block.spans));
      });
      return parent;
    }

    function renderBlocks(el,blocks){
      if(!el||typeof el.replaceChildren!=='function')throw new TypeError('renderBlocks needs an element');
      el.replaceChildren();
      el.classList&&el.classList.add('jv-md');
      return appendBlocks(el,Array.isArray(blocks)?blocks:[]);
    }

    function applyBindings(){
      if(!doc||typeof doc.querySelectorAll!=='function')return;
      var texts=doc.querySelectorAll('[data-jv-text]');
      for(var i=0;i<texts.length;i++){
        texts[i].textContent=textOf(lookup(state,texts[i].getAttribute('data-jv-text')));
      }
      var marks=doc.querySelectorAll('[data-jv-markdown]');
      for(var j=0;j<marks.length;j++){
        var path=marks[j].getAttribute('data-jv-markdown');
        renderBlocks(marks[j],state.blocks[path]||[]);
      }
    }

    function applyVariables(){
      var style=doc&&doc.documentElement&&doc.documentElement.style;
      if(!style||typeof style.setProperty!=='function')return;
      Object.keys(THEME_VARS).forEach(function(key){
        var value=state.theme[key];
        if(typeof value==='string'||typeof value==='number')style.setProperty(THEME_VARS[key],String(value));
        else style.removeProperty(THEME_VARS[key]);
      });
      Object.keys(state.props).forEach(function(name){
        var value=state.props[name];
        if(PROP_NAME.test(name)&&typeof value==='string'&&COLOR.test(value)){
          style.setProperty('--jv-prop-'+name,value);
          if(name==='accent')style.setProperty('--jv-accent',value);
        }
      });
    }

    /* Encore du contenu sous le bord du cadre : `data-jv-more` sur la racine, et
       la coquille fond la dernière ligne comme le résumé d'une fenêtre. */
    function edge(){
      var html=doc&&doc.documentElement;
      var view=doc&&(doc.scrollingElement||html);
      if(!html||!view||typeof html.setAttribute!=='function')return;
      var more=(view.scrollHeight||0)-(view.clientHeight||0)-(view.scrollTop||0)>2;
      if(more)html.setAttribute('data-jv-more','');
      else if(typeof html.removeAttribute==='function')html.removeAttribute('data-jv-more');
    }

    function measure(){
      edge();
      var body=doc&&doc.body;
      if(!body||typeof body.getBoundingClientRect!=='function')return;
      var height=Math.ceil(body.getBoundingClientRect().height);
      if(!(height>=0)||height===lastHeight)return;
      lastHeight=height;
      post({jv:JV,type:'resize',height:height});
    }

    function observe(){
      if(observer||!doc||!doc.body)return;
      var Observer=env.ResizeObserver;
      if(typeof Observer==='function'){
        observer=new Observer(measure);
        observer.observe(doc.body);
      }
      measure();
    }

    /* ---------------------------------------------------------- messages */

    function context(changed){
      return {props:state.props,data:state.data,theme:state.theme,instance:state.instance,changed:changed||null};
    }

    function take(message){
      var changed={};
      ['props','data','theme'].forEach(function(key){
        var text=JSON.stringify(isPlainObject(message[key])?message[key]:{});
        changed[key]=text!==seen[key];
        if(changed[key]){seen[key]=text;state[key]=snapshot(JSON.parse(text))}
      });
      var blocks=isPlainObject(message.blocks)?message.blocks:{};
      var blocksText=JSON.stringify(blocks);
      changed.blocks=blocksText!==seen.blocks;
      if(changed.blocks){seen.blocks=blocksText;state.blocks=snapshot(blocks)}
      return changed;
    }

    function receive(message){
      if(!isPlainObject(message)||message.jv!==JV||closed)return false;
      if(message.type==='init'){
        state.instance=snapshot(message.instance||{});
        take(message);
        started=true;
        applyVariables();applyBindings();
        call('init',context(null));
        observe();
        measure();
        return true;
      }
      if(message.type==='update'){
        var changed=take(message);
        if(!changed.props&&!changed.data&&!changed.theme&&!changed.blocks)return true;
        applyVariables();applyBindings();
        if(started)call('update',context(changed));
        measure();
        return true;
      }
      if(message.type==='teardown'){
        call('teardown',context(null));
        closed=true;
        if(observer&&typeof observer.disconnect==='function')observer.disconnect();
        return true;
      }
      return false;
    }

    /* ---------------------------------------------------------- API */

    var api={
      on:function(hook,fn){
        if(HOOKS.indexOf(hook)<0)throw new TypeError('jarvis.on: unknown hook '+String(hook));
        if(typeof fn!=='function')throw new TypeError('jarvis.on: handler must be a function');
        handlers[hook].push(fn);
        return function(){var at=handlers[hook].indexOf(fn);if(at>=0)handlers[hook].splice(at,1)};
      },
      emit:function(name,payload){
        if(typeof name!=='string'||!EVENT_NAME.test(name))throw new TypeError('jarvis.emit: invalid event name');
        var body=payload===undefined?{}:payload;
        if(!isPlainObject(body))throw new TypeError('jarvis.emit: payload must be an object');
        var text=JSON.stringify(body);
        if(utf8Bytes(text)>MAX_EVENT_BYTES)throw new RangeError('jarvis.emit: payload above 8 KiB');
        post({jv:JV,type:'event',name:name,payload:JSON.parse(text)});
      },
      blocks:function(path){return state.blocks[path]||[]},
      renderBlocks:renderBlocks,
      openUrl:function(url){
        if(typeof url!=='string'||!/^https?:\/\//i.test(url))throw new TypeError('jarvis.openUrl: http(s) only');
        post({jv:JV,type:'open_url',url:url});
      }
    };
    ['props','data','theme','instance'].forEach(function(key){
      Object.defineProperty(api,key,{enumerable:true,get:function(){return state[key]}});
    });
    Object.freeze(api);

    /* Charge le comportement une fois, puis annonce `ready` : l'hôte répond par `init`. */
    function load(behavior){
      if(loaded)return;
      loaded=true;
      try{if(typeof behavior==='function')behavior(api)}catch(error){reportError(error)}
      post({jv:JV,type:'ready'});
    }

    if(typeof env.listen==='function')env.listen(receive);
    return {api:api,load:load,receive:receive,reportError:reportError,renderBlocks:renderBlocks,measure:measure,edge:edge};
  }

  if(typeof module!=='undefined'&&module.exports){
    module.exports={createShim:createShim};
    return;
  }

  /* ------------------------------------------------------------ démarrage dans un cadre */
  if(!root||!root.document||!root.parent||root.parent===root)return;
  var parentWindow=root.parent;
  var shim=createShim({
    post:function(message){parentWindow.postMessage(message,'*')},
    listen:function(fn){
      root.addEventListener('message',function(event){if(event.source===parentWindow)fn(event.data)});
    },
    document:root.document,
    ResizeObserver:root.ResizeObserver
  });
  root.addEventListener('scroll',shim.edge,{passive:true});
  root.addEventListener('resize',shim.edge);
  root.addEventListener('error',function(event){shim.reportError(event.error||event.message)});
  root.addEventListener('unhandledrejection',function(event){shim.reportError(event.reason)});
  /* Un cadre ne navigue jamais : tout lien suit la règle de `openUrl` (nouvel onglet par l'hôte). */
  root.document.addEventListener('click',function(event){
    var target=event.target&&event.target.closest?event.target.closest('a[href]'):null;
    if(!target)return;
    event.preventDefault();
    var href=target.getAttribute('href')||'';
    if(/^https?:\/\//i.test(href))shim.api.openUrl(href);
  },true);
  Object.defineProperty(root,'jarvis',{value:shim.api,enumerable:true});
  Object.defineProperty(root,'__jvLoad',{value:shim.load});
})(typeof window!=='undefined'?window:this);
