/* Banc node de `test_fullscreen_js.py` : un DOM minimal qui sait faire du plein écran, une horloge pilotable.

   Le DOM n'est qu'un double : il modélise ce que l'API Fullscreen promet (geste requis, `fullscreenchange` avant la
   résolution de la promesse, `fullscreenElement`), pas le rendu. La preuve dans un vrai navigateur est
   `test_fullscreen_browser.py`. Les modules testés sont les vrais. */
const path=require('path');
const SRC=process.env.JARVIS_FULLSCREEN_JS;
const FS=require(SRC);

class Ev{constructor(type,init){this.type=type;Object.assign(this,init||{});this.defaultPrevented=false;this.stopped=false}
  preventDefault(){this.defaultPrevented=true}stopPropagation(){this.stopped=true}}

class El{
  constructor(doc,tag){
    this.doc=doc;this.tagName=tag.toUpperCase();this.children=[];this.parentNode=null;this.attrs={};this.dataset={};
    this.style={};this.listeners={};this.className='';this.textContent='';this.hidden=false;this.id='';
  }
  get isConnected(){let n=this;while(n){if(n===this.doc.documentElement)return true;n=n.parentNode}return false}
  appendChild(c){if(c.parentNode)c.parentNode.removeChild(c);c.parentNode=this;this.children.push(c);return c}
  removeChild(c){const i=this.children.indexOf(c);if(i>=0)this.children.splice(i,1);c.parentNode=null;return c}
  contains(o){let n=o;while(n){if(n===this)return true;n=n.parentNode}return false}
  setAttribute(k,v){this.attrs[k]=String(v)}getAttribute(k){return k in this.attrs?this.attrs[k]:null}
  hasAttribute(k){return k in this.attrs}removeAttribute(k){delete this.attrs[k]}
  addEventListener(t,fn,cap){(this.listeners[t]=this.listeners[t]||[]).push({fn,cap:!!cap})}
  removeEventListener(t,fn,cap){this.listeners[t]=(this.listeners[t]||[]).filter(l=>!(l.fn===fn&&l.cap===!!cap))}
  /* sélecteurs utilisés par le module : liste de `[data-x]`, `.classe`, `tag` ; premier descendant qui convient */
  querySelector(sel){
    const parts=sel.split(',').map(x=>x.trim());
    const hit=n=>parts.some(p=>p.startsWith('.')?(n.className||'').split(' ').includes(p.slice(1)):p.startsWith('[')?false:n.tagName===p.toUpperCase());
    const walk=n=>{for(const c of n.children){if(hit(c))return c;const r=walk(c);if(r)return r}return null};
    return walk(this);
  }
  focus(){this.doc.activeElement=this;this.doc.focusLog.push(this.id||this.tagName)}
  /* capture sur les ancêtres (haut vers bas), cible, puis bulle ; `stopPropagation` coupe la suite. */
  dispatch(type,init){
    const ev=new Ev(type,init);ev.target=this;
    const path=[];let n=this;while(n){path.unshift(n);n=n.parentNode}
    for(const node of path){
      for(const l of (node.listeners[type]||[]).filter(l=>l.cap)){l.fn(ev);if(ev.stopped)return ev}
    }
    for(const node of path.slice().reverse()){
      for(const l of (node.listeners[type]||[]).filter(l=>!l.cap)){l.fn(ev);if(ev.stopped)return ev}
    }
    return ev;
  }
  click(){this.doc.activation=true;const ev=this.dispatch('click');return ev}
  async requestFullscreen(options){
    const f=this.doc.fs;f.calls.push({el:this,options});
    if(f.mode==='deny')throw Object.assign(new TypeError(f.message||'denied by the user agent'),{});
    if(f.mode==='error')throw Object.assign(new Error('boom'),{name:'InvalidStateError'});
    if(!this.doc.activation)throw new TypeError('Permissions check failed');
    this.doc.activation=false;                       /* l'activation est consommée */
    this.doc.fullscreenElement=this;
    this.doc.dispatchDoc('fullscreenchange');         /* avant la résolution de la promesse, comme les navigateurs */
  }
}

function makeEnv(opts={}){
  const doc={fullscreenEnabled:opts.fullscreenEnabled!==false,fullscreenElement:null,activation:false,activeElement:null,
    focusLog:[],docListeners:{},fs:{mode:'grant',calls:[]},toasts:[],
    createElement(tag){return new El(doc,tag)},
    getElementById(id){const walk=n=>{if(n.id===id)return n;for(const c of n.children){const r=walk(c);if(r)return r}return null};return walk(doc.documentElement)},
    querySelectorAll(sel){
      const out=[];const walk=n=>{if(sel==='[data-object-id]'&&n.dataset.objectId!==undefined)out.push(n);n.children.forEach(walk)};walk(doc.documentElement);return out},
    addEventListener(t,fn){(doc.docListeners[t]=doc.docListeners[t]||[]).push(fn)},
    dispatchDoc(t){(doc.docListeners[t]||[]).forEach(fn=>fn(new Ev(t)))},
    async exitFullscreen(){
      if(doc.exitError)throw new Error(doc.exitError);
      if(doc.stickyFullscreen)return;
      doc.fullscreenElement=null;doc.dispatchDoc('fullscreenchange');
    },
  };
  doc.documentElement=new El(doc,'html');doc.body=new El(doc,'body');doc.documentElement.appendChild(doc.body);
  doc.activeElement=doc.body;
  const win={listeners:{},navigator:{userActivation:{isActive:true},permissions:{query:async()=>({state:'granted'})}},
    addEventListener(t,fn){(win.listeners[t]=win.listeners[t]||[]).push(fn)},
    removeEventListener(t,fn){win.listeners[t]=(win.listeners[t]||[]).filter(f=>f!==fn)},
    fire(t){(win.listeners[t]||[]).forEach(fn=>fn({type:t}))}};
  /* horloge pilotable */
  const clock={now:1_000_000,jobs:[],seq:0};
  const addJob=(fn,ms,every)=>{const id=++clock.seq;clock.jobs.push({id,at:clock.now+ms,fn,every:every?ms:0});return id};
  const timers={now:()=>clock.now,setTimeout:(fn,ms)=>addJob(fn,ms,false),clearTimeout:id=>{clock.jobs=clock.jobs.filter(j=>j.id!==id)},
    setInterval:(fn,ms)=>addJob(fn,ms,true),clearInterval:id=>{clock.jobs=clock.jobs.filter(j=>j.id!==id)}};
  const advance=async ms=>{
    const end=clock.now+ms;
    for(;;){
      const due=clock.jobs.filter(j=>j.at<=end).sort((a,b)=>a.at-b.at||a.id-b.id)[0];
      if(!due)break;
      clock.now=due.at;
      if(due.every)due.at+=due.every;else clock.jobs=clock.jobs.filter(j=>j!==due);
      due.fn();await Promise.resolve();
    }
    clock.now=end;await tick();
  };
  const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve()};
  const posts=[],logs=[];
  const request=async(url,options)=>{
    const record={url,method:options&&options.method||'GET',body:options&&options.body?JSON.parse(options.body):null};
    posts.push(record);
    if(env.requestHook)return env.requestHook(record);
    return {status:200,body:{}};
  };
  const toast=t=>{doc.toasts.push(t)};
  const scene=new El(doc,'div');scene.id='sceneLayer';doc.body.appendChild(scene);
  const addWindow=(id,title)=>{
    const w=new El(doc,'div');w.dataset.objectId=id;w.setAttribute('tabindex','-1');w.id='win-'+id;
    const head=new El(doc,'div');head.className='sc-title';head.textContent=title||id;
    const slot=new El(doc,'div');slot.className='sc-prefab-slot';
    const frame=new El(doc,'iframe');frame.className='sc-prefab-frame';frame.id='frame-'+id;frame.setAttribute('sandbox','allow-scripts');
    slot.appendChild(frame);w.appendChild(head);w.appendChild(slot);scene.appendChild(w);
    return w;
  };
  const env={doc,win,timers,advance,tick,posts,logs,toast,request,addWindow,scene,FS,
    controller(extra){
      return FS.createFullscreenController(Object.assign({document:doc,window:win,request,toast,
        log:(level,event,data)=>logs.push({level,event,data}),...timers},extra||{}));
    },
    wire(controller){doc.addEventListener('fullscreenchange',controller.onChange);doc.addEventListener('fullscreenerror',controller.onError)},
    reports:()=>posts.filter(p=>p.url===FS.STATE_ROUTE).map(p=>p.body),
    prompt:()=>doc.getElementById(FS.PROMPT_ID),
    byClass:(root,cls)=>{const out=[];const walk=n=>{if((n.className||'').split(' ').includes(cls))out.push(n);n.children.forEach(walk)};walk(root);return out[0]||null},
  };
  return env;
}
module.exports={makeEnv,Ev,El,FS};
