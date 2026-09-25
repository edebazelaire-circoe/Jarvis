(()=>{ if(window.__s8)return 'already';
window.__s8={samples:[],reqs:[],logs:[]};
setInterval(()=>{const t=Date.now();const vw=innerWidth,vh=innerHeight;
 const nodes=[...document.querySelectorAll('.sc-node[data-object-id]')].map(e=>{const b=e.getBoundingClientRect();
  return [e.dataset.objectId,Math.round(b.x),Math.round(b.y),Math.round(b.width),Math.round(b.height),e.classList.contains('sc-orbit')?1:0]});
 window.__s8.samples.push({t,rev:(window.JarvisScene&&JarvisScene.inspect().revision),vw,vh,nodes});
 if(window.__s8.samples.length>6000)window.__s8.samples.shift();},200);
const of=window.fetch;
window.fetch=async function(input,init){const url=typeof input==='string'?input:input.url;
 if(/scene\/commands/.test(url))window.__s8.reqs.push({t:Date.now(),url,method:(init&&init.method)||'GET',body:init&&init.body?String(init.body).slice(0,2000):null});
 return of.apply(this,arguments)};
for(const k of ['warn','error']){const o=console[k];console[k]=function(...a){window.__s8.logs.push(k+' '+a.map(x=>typeof x==='string'?x:JSON.stringify(x)).join(' ').slice(0,500));return o.apply(this,a)}}
addEventListener('error',e=>window.__s8.logs.push('onerror '+e.message));
return 'installed'})()
