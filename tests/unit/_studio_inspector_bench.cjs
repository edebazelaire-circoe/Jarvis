/* Banc node de `test_presentation_studio_inspector_js.py` (studio de présentation, Slice 07).

   Deux doubles, rien d'autre : (1) un DOM minimal (éléments, attributs, écouteurs avec capture/bulle, `closest`, `querySelector` simple)
   et une horloge pilotable ; (2) un Core en miniature (`makeCore`) qui rend les MÊMES formes que les routes du relais — introspection,
   édition (aperçu / enregistrement, `applied` / `refused` / `stale`), historique, direction artistique, rechargements, 409
   `scene_reloading` — pour que le module réel, `control_center_presentation_studio_inspector.js`, soit joué de bout en bout.
   La preuve dans un vrai navigateur, avec un vrai Core, est `test_presentation_studio_inspector_browser.py`. */
const MODULE=require(process.env.JARVIS_INSPECTOR_JS);

class Ev{
  constructor(type,init){this.type=type;Object.assign(this,init||{});this.defaultPrevented=false;this.stopped=false}
  preventDefault(){this.defaultPrevented=true}
  stopPropagation(){this.stopped=true}
}
const ROUTE=MODULE.ROUTE;

class El{
  constructor(doc,tag){
    this.doc=doc;this.tagName=String(tag).toUpperCase();this.childNodes=[];this.parentNode=null;this.attrs={};this.listeners={};
    this.className='';this.id='';this.hidden=false;this.disabled=false;this.value='';this.title='';this.type='';this.open=false;this.inert=false;
    this._text='';this.style={setProperty:(k,v)=>{this.style[k]=String(v)},removeProperty:(k)=>{delete this.style[k]}};
    const self=this;
    this.classList={
      add(...n){const s=new Set(self.className.split(/\s+/).filter(Boolean));n.forEach((x)=>s.add(x));self.className=[...s].join(' ')},
      remove(...n){self.className=self.className.split(/\s+/).filter((x)=>x&&!n.includes(x)).join(' ')},
      contains(n){return self.className.split(/\s+/).includes(n)},
      toggle(n,force){const on=force===undefined?!this.contains(n):!!force;on?this.add(n):this.remove(n);return on},
    };
  }
  get children(){return this.childNodes.filter((n)=>n.tagName)}
  get firstChild(){return this.childNodes[0]||null}
  get isConnected(){let n=this;while(n){if(n===this.doc.documentElement)return true;n=n.parentNode}return false}
  appendChild(c){if(c.parentNode)c.parentNode.removeChild(c);c.parentNode=this;this.childNodes.push(c);return c}
  removeChild(c){const i=this.childNodes.indexOf(c);if(i>=0)this.childNodes.splice(i,1);c.parentNode=null;return c}
  contains(o){let n=o;while(n){if(n===this)return true;n=n.parentNode}return false}
  setAttribute(k,v){this.attrs[k]=String(v);if(k==='id')this.id=String(v)}
  getAttribute(k){return k in this.attrs?this.attrs[k]:null}
  hasAttribute(k){return k in this.attrs}
  removeAttribute(k){delete this.attrs[k]}
  get textContent(){return this._text+this.childNodes.map((n)=>n.tagName?n.textContent:n.data).join('')}
  set textContent(v){this.childNodes.forEach((n)=>{n.parentNode=null});this.childNodes=[];this._text=String(v)}
  addEventListener(t,fn,cap){(this.listeners[t]=this.listeners[t]||[]).push({fn,cap:!!cap})}
  removeEventListener(t,fn,cap){this.listeners[t]=(this.listeners[t]||[]).filter((l)=>!(l.fn===fn&&l.cap===!!cap))}
  focus(){this.doc.activeElement=this;this.doc.focusLog.push(this.id||this.tagName)}
  match(sel){
    if(sel.startsWith('.'))return this.className.split(/\s+/).includes(sel.slice(1));
    if(sel.startsWith('#'))return this.id===sel.slice(1);
    const m=/^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(sel);
    if(m)return m[2]===undefined?this.hasAttribute(m[1]):this.getAttribute(m[1])===m[2];
    return this.tagName===sel.toUpperCase();
  }
  closest(sel){let n=this;while(n&&n.tagName){if(n.match(sel))return n;n=n.parentNode}return null}
  querySelector(sel){const w=(n)=>{for(const c of n.children){if(c.match(sel))return c;const r=w(c);if(r)return r}return null};return w(this)}
  querySelectorAll(sel){const out=[];const w=(n)=>{for(const c of n.children){if(c.match(sel))out.push(c);w(c)}};w(this);return out}
  /* capture sur les ancêtres (document compris), cible, bulle ; `stopPropagation` coupe la suite. */
  dispatch(type,init){
    const ev=new Ev(type,init);ev.target=this;
    const path=[];let n=this;while(n){path.unshift(n);n=n.parentNode}
    const nodes=[this.doc,...path];
    for(const node of nodes){
      for(const l of (node.listeners[type]||[]).filter((l)=>l.cap)){l.fn(ev);if(ev.stopped)return ev}
    }
    for(const node of nodes.slice().reverse()){
      for(const l of (node.listeners[type]||[]).filter((l)=>!l.cap)){l.fn(ev);if(ev.stopped)return ev}
    }
    return ev;
  }
  click(){return this.disabled?null:this.dispatch('click')}
}
class Text{constructor(data){this.data=String(data);this.parentNode=null}get textContent(){return this.data}}

function makeEnv(){
  const doc={activeElement:null,focusLog:[],listeners:{},hidden:false,fullscreenElement:null};
  doc.createElement=(tag)=>new El(doc,tag);
  doc.createTextNode=(t)=>new Text(t);
  doc.addEventListener=(t,fn,cap)=>{(doc.listeners[t]=doc.listeners[t]||[]).push({fn,cap:!!cap})};
  doc.removeEventListener=(t,fn,cap)=>{doc.listeners[t]=(doc.listeners[t]||[]).filter((l)=>!(l.fn===fn&&l.cap===!!cap))};
  doc.dispatchDoc=(t)=>{(doc.listeners[t]||[]).forEach((l)=>l.fn(new Ev(t)))};
  doc.documentElement=new El(doc,'html');doc.head=new El(doc,'head');doc.body=new El(doc,'body');
  doc.documentElement.appendChild(doc.head);doc.documentElement.appendChild(doc.body);
  doc.getElementById=(id)=>{const w=(n)=>{if(n.id===id)return n;for(const c of n.children){const r=w(c);if(r)return r}return null};return w(doc.documentElement)};
  doc.querySelectorAll=()=>[];
  doc.activeElement=doc.body;
  const win={innerWidth:1280,innerHeight:720,listeners:{},addEventListener(t,fn){(win.listeners[t]=win.listeners[t]||[]).push(fn)},removeEventListener(){},
    dispatchEvent(t){(win.listeners[t]||[]).forEach((fn)=>fn({type:t}))}};
  /* le dock : un bouton dans un .tool d'un nav.dock, dans le conteneur de la page */
  const wrap=new El(doc,'div');wrap.className='stage';doc.body.appendChild(wrap);
  const nav=new El(doc,'nav');nav.className='dock';wrap.appendChild(nav);
  const tool=new El(doc,'div');tool.className='tool';nav.appendChild(tool);
  const dock=new El(doc,'button');dock.id=MODULE.BUTTON_ID;tool.appendChild(dock);
  /* horloge pilotable */
  const clock={now:1_000_000,jobs:[],seq:0};
  const addJob=(fn,ms,every)=>{const id=++clock.seq;clock.jobs.push({id,at:clock.now+ms,fn,every:every?ms:0});return id};
  const timers={now:()=>clock.now,setTimeout:(fn,ms)=>addJob(fn,ms,false),clearTimeout:(id)=>{clock.jobs=clock.jobs.filter((j)=>j.id!==id)},
    setInterval:(fn,ms)=>addJob(fn,ms,true),clearInterval:(id)=>{clock.jobs=clock.jobs.filter((j)=>j.id!==id)}};
  const flush=async(n)=>{for(let i=0;i<(n||6);i++)await new Promise((r)=>setImmediate(r))};
  const advance=async(ms)=>{
    const end=clock.now+ms;
    for(;;){
      const due=clock.jobs.filter((j)=>j.at<=end).sort((a,b)=>a.at-b.at||a.id-b.id)[0];
      if(!due)break;
      clock.now=due.at;
      if(due.every)due.at+=due.every;else clock.jobs=clock.jobs.filter((j)=>j!==due);
      due.fn();await flush(2);
    }
    clock.now=end;await flush();
  };
  const toasts=[],logs=[],stored={};
  const storage={getItem:(k)=>(k in stored?stored[k]:null),setItem:(k,v)=>{stored[k]=String(v);storage.writes.push(k)},writes:[]};
  return {doc,win,wrap,nav,dock,timers,advance,flush,toasts,logs,stored,storage,clock};
}

/* ---- Core en miniature : les mêmes formes de réponse que le relais ---- */
const DEFS=[
  {control_id:'title',label:'Titre',group:'content',meaning:'Le titre affiché en grand.',path:'props.title',type:'string',widget:'text_line',required:false,bounds:{max_length:40},default:'Titre'},
  {control_id:'body',label:'Texte',group:'content',meaning:'Le texte courant.',path:'data.body',type:'text',widget:'text_area',required:false,bounds:{max_length:300},default:''},
  {control_id:'link',label:'Lien',group:'content',meaning:'Une adresse.',path:'data.link',type:'url',widget:'url',required:false,bounds:{},default:null},
  {control_id:'tags',label:'Mots-clés',group:'content',meaning:'Des mots-clés.',path:'data.tags',type:'array',widget:'list',required:false,bounds:{max_items:6},default:[]},
  {control_id:'code',label:'Code',group:'content',meaning:'Trois majuscules.',path:'props.code',type:'string',widget:'text_line',required:false,bounds:{max_length:3},default:'ABC',pattern:/^[A-Z]{3}$/},
  {control_id:'accent',label:'Couleur d\'accent',group:'visual',meaning:'La couleur qui porte l\'attention.',path:'props.accent',type:'color',widget:'color',required:false,bounds:{},default:'#6ee7ff'},
  {control_id:'palette',label:'Dégradé',group:'visual',meaning:'Les étapes.',path:'props.palette',type:'array',widget:'list',required:false,bounds:{max_items:5},default:['#6ee7ff','#a78bfa']},
  {control_id:'glow',label:'Halo',group:'visual',meaning:'Un halo.',path:'props.glow',type:'boolean',widget:'toggle',required:false,bounds:{},default:false},
  {control_id:'layout',label:'Alignement',group:'layout',meaning:'Où se place le contenu.',path:'props.layout',type:'enum',widget:'choice',required:false,bounds:{choices:['center','left','right']},default:'center'},
  {control_id:'size',label:'Taille',group:'layout',meaning:'La taille de l\'orbe.',path:'props.size',type:'number',widget:'slider',required:false,bounds:{min:0.6,max:1.8},default:1},
  {control_id:'tilt',label:'Inclinaison',group:'layout',meaning:'En degrés.',path:'props.tilt',type:'integer',widget:'slider',required:false,bounds:{min:-15,max:15},default:0},
  {control_id:'speed',label:'Durée',group:'motion',meaning:'En millisecondes.',path:'props.speed',type:'integer',widget:'slider',required:false,bounds:{min:100,max:2000},default:600},
  {control_id:'delay',label:'Délai',group:'motion',meaning:'En secondes.',path:'props.delay',type:'number',widget:'number',required:false,bounds:{min:0},default:0},
  {control_id:'easing',label:'Courbe',group:'motion',meaning:'La courbe.',path:'props.easing',type:'enum',widget:'choice',required:false,bounds:{choices:['linear','ease','ease-in','ease-out','ease-in-out','spring']},default:'ease'},
];

function makeCore(options){
  const o=options||{};
  const st={revision:3,values:Object.assign({title:'Ouverture',size:1,accent:'#6ee7ff'},o.values||{}),calls:[],commits:0,previews:0,
    undo:[],redo:[],reloadingFor:0,down:false,art:o.art===undefined?{revision:1,profile:{name:'Fallback - Technical dark',provenance:{origin:'generated',fallback:true},
      palette:{background:'#0b0f14',surface:'#10161d',text:'#e8f0f6',muted:'#9fb0bd',accent:'#6ee7ff'}}}:o.art,
    reloads:[],pending:[],sceneIds:['pss_1','pss_2'],historyUnavailable:!!o.historyUnavailable,delayMs:0};
  const defs=(o.defs||DEFS).map((d)=>Object.assign({},d));
  const nameOf=(path)=>path.split('.').slice(1).join('.');
  const rows=()=>defs.map((d)=>{const k=nameOf(d.path);const set=Object.prototype.hasOwnProperty.call(st.values,k);
    const row={control_id:d.control_id,label:d.label,group:d.group,meaning:d.meaning,path:d.path,type:d.type,widget:d.widget,required:d.required,
      bounds:d.bounds,default:d.default,current:set?st.values[k]:d.default,is_set:set};return row});
  const variantDoc=()=>({variant_id:'psv_1',revision:st.revision,title:'Version A',scenes:st.sceneIds.map((id,i)=>({scene_id:id,title:i?'Chiffres':'Ouverture',section:i?'':'Début',
    prefab:{id:'lab.dial',version:1},props:Object.assign({},st.values),data:{body:'Bonjour'}}))});
  const problem=(d,v)=>{
    const b=d.bounds||{};
    if(d.type==='number'||d.type==='integer'){if(typeof v!=='number')return 'expected a number';if(b.min!==undefined&&v<b.min)return `must be at least ${b.min}`;if(b.max!==undefined&&v>b.max)return `must be at most ${b.max}`}
    if(d.pattern&&!d.pattern.test(v))return `does not match ${d.pattern.source}`;
    return null;
  };
  const refused=(code,message,index)=>({status:403,body:{status:'refused',mode:'commit',code,message,failed_index:index||0,error:{code,message}}});
  const external=(mutate)=>{mutate(st.values);st.revision++};
  function edits(body){
    st.calls.push({kind:'edit',mode:body.mode,body:JSON.parse(JSON.stringify(body))});
    if(st.reloadingFor>0&&body.mode==='commit'){st.reloadingFor--;return {status:409,body:{error:{code:'presentation_studio_scene_reloading',message:'the source of the scene is being reloaded'}}}}
    if(body.basis.variant_revision!==st.revision)return {status:409,body:{status:'stale',mode:body.mode,revision:st.revision,committed:false,code:'presentation_studio_stale_revision',message:'the variant moved on',error:{code:'presentation_studio_stale_revision',message:'the variant moved on'}}};
    const results=[];
    const next=Object.assign({},st.values);
    for(const [index,op] of body.ops.entries()){
      const d=defs.find((x)=>x.control_id===op.control_id);
      if(!d)return {status:404,body:{status:'refused',code:'presentation_studio_unknown_control',message:`no declared control ${op.control_id}`,failed_index:index,error:{code:'presentation_studio_unknown_control',message:`no declared control ${op.control_id}`}}};
      const k=nameOf(d.path);
      const cur=Object.prototype.hasOwnProperty.call(next,k)?next[k]:d.default;
      if(op.if_current!==undefined&&JSON.stringify(op.if_current)!==JSON.stringify(cur))return {status:409,body:{status:'stale',mode:body.mode,revision:st.revision,committed:false,code:'presentation_studio_stale_revision',message:`control ${op.control_id} is no longer what the edit expected`,error:{code:'presentation_studio_stale_revision',message:'no longer what the edit expected'}}};
      if(op.op==='control.set'){
        const p=problem(d,op.value);
        if(p)return {status:400,body:{status:'refused',mode:body.mode,code:'presentation_studio_value_refused',message:`control ${op.control_id}: ${op.path||d.path}: ${p}`,failed_index:index,error:{code:'presentation_studio_value_refused',message:p}}};
        results.push({control_id:op.control_id,before:cur,after:op.value,was_set:Object.prototype.hasOwnProperty.call(next,k),is_set:true});
        next[k]=op.value;
      }else if(op.op==='control.reset'){results.push({control_id:op.control_id,before:cur,after:null,is_set:false});delete next[k]}
    }
    const changed=JSON.stringify(next)!==JSON.stringify(st.values);
    if(body.mode==='commit'&&changed){
      st.undo.push({entry_id:'psh_'+(st.undo.length+1),actor:body.actor||'user',before:st.values});st.redo=[];
      st.values=next;st.revision++;st.commits++;
    }else if(body.mode==='preview')st.previews++;
    return {status:200,body:{status:'applied',mode:body.mode,revision:st.revision,committed:body.mode==='commit'&&changed,changed,ops:results,tier:'control'}};
  }
  function history(){
    const h={revision:st.revision,tracked:st.undo.length>0||st.redo.length>0,undo_count:st.undo.length,redo_count:st.redo.length,
      next_undo:st.undo.length?{entry_id:st.undo[st.undo.length-1].entry_id,actor:st.undo[st.undo.length-1].actor}:null,
      next_redo:st.redo.length?{entry_id:st.redo[st.redo.length-1].entry_id,actor:'user'}:null};
    if(!h.tracked){h.reason='not_recorded_since_start';h.message='history is kept in memory only: nothing was recorded for this variant since Core started'}
    return h;
  }
  function undo(direction,body){
    st.calls.push({kind:direction,body});
    if(st.historyUnavailable){
      return {status:409,body:{status:'history_unavailable',reason:'not_recorded_since_start',message:'history is kept in memory only: nothing was recorded since Core started',code:'presentation_studio_history_unavailable',error:{code:'presentation_studio_history_unavailable',message:'unavailable'}}};
    }
    const from=direction==='undo'?st.undo:st.redo,to=direction==='undo'?st.redo:st.undo;
    if(!from.length)return {status:409,body:{status:direction==='undo'?'nothing_to_undo':'nothing_to_redo',message:'nothing to do',code:'presentation_studio_history_empty',error:{code:'presentation_studio_history_empty',message:'nothing'}}};
    const entry=from[from.length-1];
    if(body&&body.expected_entry_id&&body.expected_entry_id!==entry.entry_id)return {status:409,body:{status:'stale',message:'head changed',code:'presentation_studio_history_stale',error:{code:'presentation_studio_history_stale',message:'head'}}};
    from.pop();const now=st.values;st.values=entry.before;entry.before=now;to.push(entry);st.revision++;
    return {status:200,body:{status:'applied',revision:st.revision,entry:{entry_id:entry.entry_id}}};
  }
  function handle(method,url,body){
    const path=url.startsWith(ROUTE)?url.slice(ROUTE.length):url;
    st.calls.push({kind:'http',method,path});
    if(st.down)throw new Error('connection refused');
    if(method==='GET'&&path==='')return {status:200,body:{presentations:o.presentations||[{presentation_id:'pst_1',title:'Atelier'}],problems:[]}};
    if(method==='GET'&&path==='/pst_1')return {status:200,body:{presentation:{presentation_id:'pst_1',active_variant_id:'psv_1'},variants:[variantDoc()]}};
    if(method==='GET'&&path==='/pst_1/variants/psv_1')return {status:200,body:variantDoc()};
    let m=/^\/pst_1\/variants\/psv_1\/scenes\/(pss_\d)\/controls$/.exec(path);
    if(method==='GET'&&m){
      if(!st.sceneIds.includes(m[1]))return {status:404,body:{error:{code:'presentation_studio_unknown_scene',message:'unknown scene'}}};
      return {status:200,body:{presentation_id:'pst_1',variant_id:'psv_1',variant_revision:st.revision,scene_id:m[1],order:1,title:'Ouverture',section:'',
        prefab:{id:'lab.dial',version:1},preview:{caption:'',alt:''},controls:m[1]==='pss_2'?rows().filter((r)=>['title','accent','size'].includes(r.control_id)):rows(),anchors:[],payload:{bytes:200,limit:16384,remaining:16000},
        stage:{mode:'patch_stable_window',prefab_key:'lab.dial@1'},problems:o.problems||[]}};
    }
    if(method==='GET'&&path==='/pst_1/variants/psv_1/history')return {status:200,body:history()};
    if(method==='GET'&&path==='/pst_1/variants/psv_1/art-direction'){
      if(!st.art)return {status:404,body:{error:{code:'presentation_studio_unknown_art_direction',message:'none'}}};
      return {status:200,body:{art_direction:st.art}};
    }
    if(method==='GET'&&path==='/pst_1/reloads')return {status:200,body:{reloads:st.reloads,pending:st.pending,stats:{}}};
    if(method==='POST'&&path==='/pst_1/variants/psv_1/edits')return edits(body);
    if(method==='POST'&&path==='/pst_1/variants/psv_1/undo')return undo('undo',body);
    if(method==='POST'&&path==='/pst_1/variants/psv_1/redo')return undo('redo',body);
    return {status:404,body:{error:{code:'not_found',message:path}}};
  }
  return {st,defs,handle,rows,external,variantDoc};
}

/* Une page + son inspecteur réel branché sur le Core en miniature. `playing` : booléen mutable. */
async function boot(options){
  const o=options||{};
  const env=makeEnv();
  const core=makeCore(o.core);
  const hook={playing:false,fullscreen:false,hang:false,gate:null};
  const fetch=async(url,init)=>{
    const method=(init&&init.method)||'GET';
    const body=init&&init.body?JSON.parse(init.body):null;
    if(init&&init.signal&&init.signal.aborted)throw Object.assign(new Error('aborted'),{name:'AbortError'});
    if(hook.gate&&method==='POST'&&body&&body.mode==='commit')await hook.gate;
    if(hook.hang)return new Promise((res,rej)=>{init.signal.addEventListener('abort',()=>rej(Object.assign(new Error('aborted'),{name:'AbortError'})))});
    const answer=core.handle(method,url,body);
    return {status:answer.status,ok:answer.status<400,text:async()=>JSON.stringify(answer.body)};
  };
  const hostCalls=[];
  const prefabHost=o.noHost?null:{createPrefabHost(opts){
    const frames=new Map();
    return {mount(slot,instance){frames.set(instance.object_id,instance);hostCalls.push({mount:JSON.parse(JSON.stringify(instance))});return true},
      unmount(id){frames.delete(id);hostCalls.push({unmount:id});return true},has:(id)=>frames.has(id),destroy(){}};
  },bundleFetcher:()=>async()=>({})};
  const inspector=MODULE.createStudioInspector({document:env.doc,window:env.win,fetch,toast:(t)=>env.toasts.push(t),
    now:env.timers.now,setTimeout:env.timers.setTimeout,clearTimeout:env.timers.clearTimeout,setInterval:env.timers.setInterval,
    clearInterval:env.timers.clearInterval,storage:()=>env.storage,...(o.defaultPlaying?{}:{playing:()=>hook.playing}),fullscreen:()=>hook.fullscreen,
    prefabHost,console:{info:(l)=>env.logs.push(['info',l]),warn:(l)=>env.logs.push(['warn',l]),error:(l)=>env.logs.push(['error',l])},
    obsClientLog:o.obs?(...a)=>o.obs.push(a):undefined});
  inspector.install();
  const panel=()=>env.doc.getElementById(MODULE.PANEL_ID);
  const row=(id)=>panel().querySelector(`[data-control-id="${id}"]`);
  const find=(root,pred)=>{const out=[];const w=(n)=>{for(const c of n.children||[]){if(pred(c))out.push(c);w(c)}};w(root);return out};
  const open=async()=>{inspector.open({noFocus:true});await env.flush(10)};
  return {env,core,inspector,hook,panel,row,find,open,hostCalls,MODULE,Ev,El};
}

module.exports={makeEnv,makeCore,boot,DEFS,MODULE,Ev,El};
