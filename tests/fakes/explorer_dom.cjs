/* Faux DOM de l'explorateur de variantes (studio de présentation, Slice 18).

   Assez de DOM pour que le VRAI contrôleur tourne sous node : éléments, texte, attributs, `dataset`, `classList`, sélecteurs (balise, #id,
   .classe, [attr], [attr=val], :not(), descendant et enfant), événements avec capture et bulle, focus (refusé hors document, sous `inert`
   ou `hidden`), géométrie réglable, défilement, horloge et minuteries pilotées, réseau scripté, stockage. Tout ce qui pourrait fabriquer du
   balisage à partir d'une chaîne (`innerHTML`, `insertAdjacentHTML`, `outerHTML`) ENREGISTRE une violation (`doc.violations`) : un test
   exige qu'elle reste vide. Ce n'est pas un navigateur : la preuve réelle est `test_presentation_studio_explorer_browser.py`. */
'use strict';

class FakeEvent{
  constructor(type,init){
    this.type=type;this.bubbles=true;this.cancelable=true;this.defaultPrevented=false;this._stopped=false;this._immediate=false;
    Object.assign(this,init||{});
  }
  preventDefault(){this.defaultPrevented=true}
  stopPropagation(){this._stopped=true}
  stopImmediatePropagation(){this._stopped=true;this._immediate=true}
}
class FakeText{
  constructor(doc,text){this.nodeType=3;this.ownerDocument=doc;this.data=String(text);this.parentNode=null}
  get textContent(){return this.data}
  set textContent(v){this.data=String(v)}
}
const FOCUSABLE=new Set(['BUTTON','INPUT','SELECT','TEXTAREA','SUMMARY']);

function parseCompound(text){
  const out={tag:null,id:null,classes:[],attrs:[],nots:[]};
  let s=text;
  const tag=/^[a-zA-Z][a-zA-Z0-9-]*/.exec(s);
  if(tag){out.tag=tag[0].toUpperCase();s=s.slice(tag[0].length)}
  while(s.length){
    let m;
    if((m=/^#([^.#[:\s]+)/.exec(s))){out.id=m[1]}
    else if((m=/^\.([^.#[:\s]+)/.exec(s))){out.classes.push(m[1])}
    else if((m=/^\[([^\]=^~$*]+)(?:([~^$*]?=)"?([^\]"]*)"?)?\]/.exec(s))){out.attrs.push({name:m[1],op:m[2]||null,value:m[3]})}
    else if((m=/^:not\((.+?)\)/.exec(s))){out.nots.push(parseCompound(m[1]))}
    else throw new Error('selecteur non gere : '+text);
    s=s.slice(m[0].length);
  }
  return out;
}
function tokenize(part){
  /* Découpe sur les espaces HORS crochets et guillemets : `[aria-label="Scène précédente"]` reste un seul jeton. */
  const tokens=[];let cur='',depth=0,quote=false;
  for(const ch of part.trim().replace(/\s*>\s*/g,' > ')){
    if(ch==='"')quote=!quote;
    if(!quote&&ch==='[')depth++;
    if(!quote&&ch===']')depth--;
    if(!quote&&depth===0&&/\s/.test(ch)){if(cur)tokens.push(cur);cur='';continue}
    cur+=ch;
  }
  if(cur)tokens.push(cur);
  return tokens;
}
function parseSelector(text){
  return text.split(',').map(part=>{
    const chain=[];let combinator=' ';
    for(const token of tokenize(part)){
      if(token==='>'){combinator='>';continue}
      chain.push({combinator,compound:parseCompound(token)});combinator=' ';
    }
    return chain;
  });
}
function matchCompound(el,c){
  if(el.nodeType!==1)return false;
  if(c.tag&&el.tagName!==c.tag)return false;
  if(c.id&&el.id!==c.id)return false;
  const classes=(el.className||'').split(/\s+/).filter(Boolean);
  if(!c.classes.every(x=>classes.includes(x)))return false;
  for(const a of c.attrs){
    const v=el.getAttribute(a.name);
    if(a.op===null||a.op===undefined){if(v===null)return false}
    else if(v===null)return false;
    else if(a.op==='='&&v!==a.value)return false;
    else if(a.op==='^='&&!v.startsWith(a.value))return false;
    else if(a.op==='$='&&!v.endsWith(a.value))return false;
    else if(a.op==='*='&&!v.includes(a.value))return false;
    else if(a.op==='~='&&!v.split(/\s+/).includes(a.value))return false;
  }
  return !c.nots.some(n=>matchCompound(el,n));
}
function matchChain(el,chain,index){
  const link=chain[index];
  if(!matchCompound(el,link.compound))return false;
  if(index===0)return true;
  if(link.combinator==='>'){return !!el.parentNode&&matchChain(el.parentNode,chain,index-1)}
  for(let p=el.parentNode;p;p=p.parentNode)if(matchChain(p,chain,index-1))return true;
  return false;
}

class El{
  constructor(doc,tag,ns){
    this.nodeType=1;this.ownerDocument=doc;this.tagName=String(tag).toUpperCase();this.namespaceURI=ns||null;
    this.parentNode=null;this.childNodes=[];this._attrs=new Map();this._listeners={};
    this.scrollTop=0;this.scrollLeft=0;this._clientHeight=0;this._clientWidth=0;this.rect=null;this.inert=false;
    this.checked=false;this.disabled=false;this.type=this.tagName==='INPUT'?'text':(this.tagName==='BUTTON'?'submit':'');
    const self=this;
    this.style={_v:{},setProperty(k,v){this._v[k]=String(v)},getPropertyValue(k){return this._v[k]||''},removeProperty(k){delete this._v[k]}};
    this.classList={
      add(...n){const s=new Set(self.className.split(/\s+/).filter(Boolean));n.forEach(x=>s.add(x));self.className=[...s].join(' ')},
      remove(...n){self.className=self.className.split(/\s+/).filter(x=>x&&!n.includes(x)).join(' ')},
      contains(n){return self.className.split(/\s+/).includes(n)},
      toggle(n,force){const has=this.contains(n);const want=force===undefined?!has:!!force;if(want)this.add(n);else this.remove(n);return want},
    };
    this.dataset=new Proxy({},{
      get:(_,k)=>{const v=self.getAttribute('data-'+String(k).replace(/[A-Z]/g,m=>'-'+m.toLowerCase()));return v===null?undefined:v},
      set:(_,k,v)=>{self.setAttribute('data-'+String(k).replace(/[A-Z]/g,m=>'-'+m.toLowerCase()),v);return true},
      has:(_,k)=>self.hasAttribute('data-'+String(k).replace(/[A-Z]/g,m=>'-'+m.toLowerCase())),
    });
  }
  get value(){return this._value!==undefined?this._value:(this.getAttribute('value')||'')}
  set value(v){this._value=String(v)}
  get id(){return this.getAttribute('id')||''}
  set id(v){this.setAttribute('id',v)}
  get className(){return this.getAttribute('class')||''}
  set className(v){this.setAttribute('class',v)}
  get hidden(){return this.hasAttribute('hidden')}
  set hidden(v){if(v)this.setAttribute('hidden','');else this.removeAttribute('hidden')}
  get tabIndex(){const v=this.getAttribute('tabindex');return v===null?(FOCUSABLE.has(this.tagName)?0:-1):Number(v)}
  set tabIndex(v){this.setAttribute('tabindex',v)}
  get children(){return this.childNodes.filter(n=>n.nodeType===1)}
  get firstChild(){return this.childNodes[0]||null}
  get lastChild(){return this.childNodes[this.childNodes.length-1]||null}
  get firstElementChild(){return this.children[0]||null}
  get nextSibling(){const p=this.parentNode;if(!p)return null;const i=p.childNodes.indexOf(this);return p.childNodes[i+1]||null}
  get isConnected(){for(let n=this;n;n=n.parentNode){if(n===this.ownerDocument.documentElement)return true}return false}
  get offsetParent(){return this.isConnected&&!this._hiddenChain()?this.parentNode:null}
  _hiddenChain(){for(let n=this;n&&n.nodeType===1;n=n.parentNode)if(n.hidden||n.style._v.display==='none')return true;return false}
  get textContent(){return this.childNodes.map(n=>n.textContent).join('')}
  set textContent(v){for(const c of this.childNodes)c.parentNode=null;this.childNodes=[];if(String(v)!=='')this.appendChild(new FakeText(this.ownerDocument,v))}
  get innerHTML(){return ''}
  set innerHTML(v){this.ownerDocument.violations.push('innerHTML:'+this.tagName)}
  get outerHTML(){return ''}
  set outerHTML(v){this.ownerDocument.violations.push('outerHTML:'+this.tagName)}
  insertAdjacentHTML(){this.ownerDocument.violations.push('insertAdjacentHTML:'+this.tagName)}
  get clientHeight(){return this._clientHeight||(this.rect?this.rect.height:0)}
  set clientHeight(v){this._clientHeight=v}
  get clientWidth(){return this._clientWidth||(this.rect?this.rect.width:0)}
  set clientWidth(v){this._clientWidth=v}
  get scrollHeight(){return this._scrollHeight||this.clientHeight}
  set scrollHeight(v){this._scrollHeight=v}
  getBoundingClientRect(){
    const r=this.rect||{left:0,top:0,width:100,height:30};
    return {left:r.left,top:r.top,width:r.width,height:r.height,right:r.left+r.width,bottom:r.top+r.height,x:r.left,y:r.top};
  }
  scrollIntoView(opts){this.ownerDocument.scrolled.push({el:this,opts});}
  setAttribute(k,v){this._attrs.set(String(k),String(v))}
  getAttribute(k){return this._attrs.has(k)?this._attrs.get(k):null}
  hasAttribute(k){return this._attrs.has(k)}
  removeAttribute(k){this._attrs.delete(k)}
  setAttributeNS(_ns,k,v){this.setAttribute(k,v)}
  toggleAttribute(k,force){const want=force===undefined?!this.hasAttribute(k):!!force;if(want)this.setAttribute(k,'');else this.removeAttribute(k);return want}
  appendChild(c){return this.insertBefore(c,null)}
  insertBefore(c,ref){
    if(c.parentNode)c.parentNode.removeChild(c);
    c.parentNode=this;
    const i=ref?this.childNodes.indexOf(ref):-1;
    if(i<0)this.childNodes.push(c);else this.childNodes.splice(i,0,c);
    return c;
  }
  append(...items){for(const it of items)this.appendChild(typeof it==='string'?new FakeText(this.ownerDocument,it):it)}
  replaceChildren(...items){for(const c of [...this.childNodes])this.removeChild(c);this.append(...items)}
  removeChild(c){
    const i=this.childNodes.indexOf(c);
    if(i>=0)this.childNodes.splice(i,1);
    c.parentNode=null;
    if(this.ownerDocument.activeElement===c||(c.contains&&c.contains(this.ownerDocument.activeElement)))this.ownerDocument.activeElement=this.ownerDocument.body;
    return c;
  }
  remove(){if(this.parentNode)this.parentNode.removeChild(this)}
  contains(other){for(let n=other;n;n=n.parentNode)if(n===this)return true;return false}
  matches(sel){return parseSelector(sel).some(chain=>matchChain(this,chain,chain.length-1))}
  closest(sel){for(let n=this;n&&n.nodeType===1;n=n.parentNode)if(n.matches(sel))return n;return null}
  querySelectorAll(sel){
    const chains=parseSelector(sel),out=[];
    const walk=n=>{for(const c of n.children){if(chains.some(ch=>matchChain(c,ch,ch.length-1)))out.push(c);walk(c)}};
    walk(this);
    return out;
  }
  querySelector(sel){return this.querySelectorAll(sel)[0]||null}
  getElementsByClassName(name){return this.querySelectorAll('.'+name)}
  addEventListener(type,fn,opts){
    const capture=typeof opts==='boolean'?opts:!!(opts&&opts.capture);
    (this._listeners[type]=this._listeners[type]||[]).push({fn,capture,once:!!(opts&&opts.once)});
  }
  removeEventListener(type,fn,opts){
    const capture=typeof opts==='boolean'?opts:!!(opts&&opts.capture);
    this._listeners[type]=(this._listeners[type]||[]).filter(l=>!(l.fn===fn&&l.capture===capture));
  }
  dispatchEvent(ev){
    ev.target=ev.target||this;
    const path=[];for(let n=this;n;n=n.parentNode)path.unshift(n);
    const ancestors=path.slice(0,-1);
    const fire=(node,phase)=>{
      ev.currentTarget=node;
      for(const l of [...((node._listeners&&node._listeners[ev.type])||[])]){
        if(phase==='capture'&&!l.capture)continue;
        if(phase==='bubble'&&l.capture)continue;
        if(l.once)node.removeEventListener(ev.type,l.fn,l.capture);
        l.fn.call(node,ev);
        if(ev._immediate)return;
      }
    };
    for(const node of ancestors){fire(node,'capture');if(ev._stopped)return !ev.defaultPrevented}
    fire(this,'target');
    if(ev._stopped)return !ev.defaultPrevented;
    if(ev.bubbles){
      for(const node of ancestors.slice().reverse()){fire(node,'bubble');if(ev._stopped)break}
    }
    return !ev.defaultPrevented;
  }
  focus(){
    const doc=this.ownerDocument;
    if(!this.isConnected||this._hiddenChain()||this.disabled)return;
    for(let n=this;n&&n.nodeType===1;n=n.parentNode)if(n.inert)return;
    if(!(FOCUSABLE.has(this.tagName)||this.hasAttribute('tabindex')||this.isContentEditable))return;
    const before=doc.activeElement;
    if(before===this)return;
    doc.activeElement=this;
    doc.focusLog.push(this.id||this.getAttribute('data-id')||this.tagName);
    if(before&&before.dispatchEvent)before.dispatchEvent(new FakeEvent('blur',{bubbles:false,relatedTarget:this}));
    this.dispatchEvent(new FakeEvent('focus',{bubbles:false,relatedTarget:before}));
    this.dispatchEvent(new FakeEvent('focusin',{relatedTarget:before}));
  }
  blur(){if(this.ownerDocument.activeElement===this)this.ownerDocument.activeElement=this.ownerDocument.body}
  select(){this.selected=true}
  setSelectionRange(){}
  click(){
    if(this.disabled)return;
    if(this.tagName==='INPUT'&&(this.type==='checkbox'))this.checked=!this.checked;
    this.dispatchEvent(new FakeEvent('click',{detail:1,button:0}));
  }
  async requestFullscreen(){
    const doc=this.ownerDocument;
    doc.fsRequests.push(this);
    doc.fullscreenElement=this;doc.dispatchEvent(new FakeEvent('fullscreenchange',{bubbles:false}));
  }
}

function makeEnv(opts){
  const o=opts||{};
  const doc=new El(null,'#document');
  doc.nodeType=9;
  doc.ownerDocument=doc;
  Object.assign(doc,{violations:[],scrolled:[],focusLog:[],fsRequests:[],fullscreenEnabled:true,fullscreenElement:null,visibilityState:'visible'});
  doc.documentElement=new El(doc,'html');doc.head=new El(doc,'head');doc.body=new El(doc,'body');
  doc.documentElement.appendChild(doc.head);doc.documentElement.appendChild(doc.body);
  doc.appendChild(doc.documentElement);
  doc.activeElement=doc.body;
  doc.createElement=tag=>new El(doc,tag);
  doc.createElementNS=(ns,tag)=>new El(doc,tag,ns);
  doc.createTextNode=text=>new FakeText(doc,text);
  doc.getElementById=id=>{const walk=n=>{for(const c of n.children){if(c.id===id)return c;const r=walk(c);if(r)return r}return null};return walk(doc.documentElement)};
  doc.exitFullscreen=async()=>{doc.fullscreenElement=null;doc.dispatchEvent(new FakeEvent('fullscreenchange',{bubbles:false}))};
  Object.defineProperty(doc,'isConnected',{get:()=>true});

  /* horloge pilotable */
  const clock={now:Date.UTC(2026,9,8,12,0,0),jobs:[],seq:0};
  const addJob=(fn,ms,every)=>{const id=++clock.seq;clock.jobs.push({id,at:clock.now+Math.max(0,ms),fn,every:every?Math.max(1,ms):0});return id};
  const timers={now:()=>clock.now,setTimeout:(fn,ms)=>addJob(fn,ms,false),clearTimeout:id=>{clock.jobs=clock.jobs.filter(j=>j.id!==id)},
    setInterval:(fn,ms)=>addJob(fn,ms,true),clearInterval:id=>{clock.jobs=clock.jobs.filter(j=>j.id!==id)},
    requestAnimationFrame:fn=>addJob(()=>fn(clock.now),16,false),cancelAnimationFrame:id=>{clock.jobs=clock.jobs.filter(j=>j.id!==id)}};
  const tick=async()=>{for(let i=0;i<12;i++)await Promise.resolve();await new Promise(r=>setImmediate(r));for(let i=0;i<12;i++)await Promise.resolve()};
  const advance=async ms=>{
    const end=clock.now+ms;
    for(let guard=0;guard<100000;guard++){
      const due=clock.jobs.filter(j=>j.at<=end).sort((a,b)=>a.at-b.at||a.id-b.id)[0];
      if(!due)break;
      clock.now=due.at;
      if(due.every)due.at+=due.every;else clock.jobs=clock.jobs.filter(j=>j!==due);
      try{due.fn()}catch(error){env.errors.push(String(error&&error.stack||error))}
      await tick();
    }
    clock.now=end;await tick();
  };

  /* fenêtre */
  const store=new Map();
  const win=new El(doc,'#window');
  Object.assign(win,{innerWidth:o.width||1280,innerHeight:o.height||720,document:doc,
    navigator:{userActivation:{isActive:true},permissions:{query:async()=>({state:'granted'})}},
    localStorage:{getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>{if(win.storageBlocked)throw new Error('blocked');store.set(k,String(v))},removeItem:k=>store.delete(k)},
    matchMedia:q=>({matches:!!(win.media&&win.media[q]),addEventListener(){},removeEventListener(){}}),
    setTimeout:timers.setTimeout,clearTimeout:timers.clearTimeout,setInterval:timers.setInterval,clearInterval:timers.clearInterval,
    requestAnimationFrame:timers.requestAnimationFrame,cancelAnimationFrame:timers.cancelAnimationFrame,
    getComputedStyle:()=>({getPropertyValue:()=>''}),performance:{now:()=>clock.now}});
  win.ownerDocument=doc;

  /* réseau scripté : `env.routes` = [{match:(url,init)=>bool, reply:(url,init,body)=>({status,body,delay?})}] ; le premier qui convient répond */
  const requests=[];
  const routes=[];
  const fetch=async(url,init)=>{
    const options=init||{};
    const record={url:String(url),method:options.method||'GET',body:options.body?JSON.parse(options.body):null,headers:options.headers||{},t:clock.now};
    requests.push(record);
    if(options.signal&&options.signal.aborted)throw Object.assign(new Error('aborted'),{name:'AbortError'});
    const route=routes.find(r=>r.match(record.url,record));
    let reply=route?route.reply(record.url,record,record.body):{status:404,body:{error:{code:'no_route',message:'aucune route scriptée '+record.url}}};
    if(reply&&typeof reply.then==='function')reply=await reply;
    if(reply&&reply.hang){
      await new Promise((_,reject)=>{if(options.signal)options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})))});
    }
    if(reply&&reply.reject)throw new Error(reply.reject);
    if(reply&&reply.delay)await new Promise(r=>timers.setTimeout(r,reply.delay));
    if(options.signal&&options.signal.aborted)throw Object.assign(new Error('aborted'),{name:'AbortError'});
    const status=reply.status===undefined?200:reply.status;
    const text=reply.text!==undefined?reply.text:JSON.stringify(reply.body===undefined?{}:reply.body);
    return {ok:status>=200&&status<300,status,statusText:'',headers:{get:k=>(reply.headers||{})[k]||null},
      json:async()=>JSON.parse(text),text:async()=>text};
  };
  const env={doc,win,timers,tick,advance,fetch,requests,routes,pendingTimers:()=>clock.jobs.length,jobs:()=>clock.jobs.map(j=>({id:j.id,at:j.at-clock.now,every:j.every})),errors:[],logs:[],toasts:[],store,
    toast:t=>{env.toasts.push(t)},
    console:{info:(...a)=>env.logs.push(['info',a.join(' ')]),warn:(...a)=>env.logs.push(['warn',a.join(' ')]),error:(...a)=>env.logs.push(['error',a.join(' ')]),log:(...a)=>env.logs.push(['log',a.join(' ')])},
    route(match,reply){const r={match:typeof match==='string'?(u=>u.startsWith(match)):match instanceof RegExp?(u=>match.test(u)):match,reply:typeof reply==='function'?reply:(()=>reply)};routes.unshift(r);return r},
    key(target,key,mods){
      const ev=new FakeEvent('keydown',Object.assign({key,code:key,ctrlKey:false,shiftKey:false,altKey:false,metaKey:false},mods||{}));
      target.dispatchEvent(ev);return ev;
    },
    click(target){target.click();return target},
    pointer(target,type,init){const ev=new FakeEvent(type,Object.assign({button:0,pointerType:'mouse',clientX:10,clientY:10,pointerId:1},init||{}));target.dispatchEvent(ev);return ev},
    enterFullscreen(el){doc.fullscreenElement=el;doc.dispatchEvent(new FakeEvent('fullscreenchange',{bubbles:false}))},
    leaveFullscreen(){doc.fullscreenElement=null;doc.dispatchEvent(new FakeEvent('fullscreenchange',{bubbles:false}))},
    hide(){doc.visibilityState='hidden';doc.dispatchEvent(new FakeEvent('visibilitychange',{bubbles:false}))},
    show(){doc.visibilityState='visible';doc.dispatchEvent(new FakeEvent('visibilitychange',{bubbles:false}))},
    walk(node,fn){fn(node);for(const c of node.children||[])env.walk(c,fn)},
    textOf(node){return node.textContent},
  };
  return env;
}
module.exports={makeEnv,FakeEvent,El,FakeText};
