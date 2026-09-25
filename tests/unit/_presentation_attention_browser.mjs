/* Harnais CDP pour `test_presentation_attention_browser.py` (Slice 09).

   Il va plus loin que celui de la Slice 03, et pour une raison precise : ce
   qu'il faut prouver ici est **inter-onglets**. Deux onglets ne partagent un
   `localStorage` que s'ils partagent une origine, et `file://` n'en donne pas
   une utilisable. Ce harnais sert donc la page composee par un petit serveur
   HTTP local, qui repond aussi `/api/status` — la page fait alors son vrai
   sondage a 1 Hz, sur de vraies reponses, et rien n'est simule cote page.

   Il compte les signaux sonores de deux facons independantes :
   - `osc` : les oscillateurs WebAudio reellement crees, instrumentes AVANT le
     chargement du document ;
   - `cues` : les appels a `bgCue`, enveloppe apres chargement.
   `bgCue` en fait deux notes, donc `osc` vaut deux fois `cues` quand le
   contexte audio se construit. Les deux sont rendus : un test qui n'en lirait
   qu'un serait aveugle au cas ou le contexte audio refuse de s'ouvrir.

   Usage : node _presentation_attention_browser.mjs <page.html> <chrome.exe> <planJSON>
   Ecrit sur la sortie standard `{"reads":[...],"requests":[...]}`.

   Un plan est une liste d'actions :
     {"a":"open","tabs":2,"width":1440,"height":900,"reducedMotion":false}
     {"a":"status","value":{...},"waitMs":1400}
     {"a":"mount","tab":0,"palette":true,"toasts":2,"panel":false}
     {"a":"reload","tab":0}
     {"a":"click","tab":0,"selector":".pa-card .pa-head"}
     {"a":"mark","name":"avant-ecart"}
     {"a":"read"}                                  -> pousse une lecture par onglet
     {"a":"eval","tab":0,"expr":"..."}             -> pousse la valeur rendue     */
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {readFileSync, mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN);
const html=readFileSync(PAGE,'utf-8');

/* Le statut servi a cet instant. Une action `status` le remplace ; la page le
   relit d'elle-meme au battement suivant. */
let status={agent:{name:'test',state:'stopped'},agent_cli:'test',error_count:0,
  voice_state:'idle',voice_online:false,background:{seq:0,unread:0,counts:{},attention:[]}};
const requests=[];

const server=createServer((req,res)=>{
  const path=String(req.url||'').split('?')[0];
  requests.push({method:req.method,path:path,at:Date.now()});
  const json=body=>{
    res.writeHead(200,{'content-type':'application/json','cache-control':'no-store'});
    res.end(JSON.stringify(body));
  };
  if(path==='/'||path==='/index.html'){
    res.writeHead(200,{'content-type':'text/html; charset=utf-8','cache-control':'no-store'});
    res.end(html);return;
  }
  if(path==='/api/status'){json(status);return}
  if(req.method==='POST'){json({ok:true});return}
  /* Tout le reste rend une forme vide mais valide : la page sonde plusieurs
     routes au demarrage et un 404 ferait du bruit dans la console sans rien
     apprendre a personne. */
  json(path==='/api/shortcuts'?{}:[]);
});
await new Promise(ok=>server.listen(0,'127.0.0.1',ok));
const base=`http://127.0.0.1:${server.address().port}`;

/* Instrumente AVANT tout script de page : c'est le seul moment ou l'on peut
   voir la creation d'un oscillateur, puisque `bgCue` construit son contexte a
   la volee. */
const PROBE=`window.__probe={osc:0,cues:0,wrapped:false};
(function(){var patch=function(C){if(!C||!C.prototype)return;
  var original=C.prototype.createOscillator;
  C.prototype.createOscillator=function(){window.__probe.osc+=1;
    return original.apply(this,arguments)}};
  patch(window.AudioContext);patch(window.webkitAudioContext)})();`;

/* Enveloppe `bgCue` apres chargement : une declaration de fonction de premier
   niveau est une propriete de l'objet global, donc la remplacer remplace bien
   ce que `renderBackgroundPills` appelle. */
const WRAP=`(function(){
  if(window.__probe.wrapped)return 'deja';
  if(typeof window.bgCue!=='function')return 'absent';
  var original=window.bgCue;
  window.bgCue=function(){window.__probe.cues+=1;return original.apply(this,arguments)};
  window.__probe.wrapped=true;return 'ok'})()`;

const MOUNT_PALETTE=`(function(){
  var H=window.JarvisBarehandsHud;
  if(!H||!H.STYLE)return 'pas de module hud';
  var style=document.createElement('style');style.textContent=H.STYLE;
  document.head.appendChild(style);
  var host=document.getElementById(H.DOM.paletteId);
  if(!host)return 'pas d emplacement';
  var strip=document.createElement('div');strip.className='bh-tools';
  for(var i=0;i<5;i+=1){var b=document.createElement('button');
    b.className='bh-tool';b.type='button';strip.appendChild(b)}
  host.appendChild(strip);return 'ok'})()`;

const READ=`(function(){
  var seen={probe:{osc:window.__probe.osc,cues:window.__probe.cues}};
  var box=function(name,selector){
    var el=document.querySelector(selector);
    if(!el){seen[name]=null;return}
    var r=el.getBoundingClientRect();
    if(!r.width&&!r.height){seen[name]=null;return}
    var cs=getComputedStyle(el);
    seen[name]={l:Math.round(r.left),t:Math.round(r.top),r:Math.round(r.right),
      b:Math.round(r.bottom),w:Math.round(r.width),h:Math.round(r.height),
      z:cs.zIndex,animation:cs.animation,order:cs.order,pointerEvents:cs.pointerEvents};
  };
  box('card','.pa-card');
  box('palette','#barehandsPalette');
  box('modeBtn','#interactionModeButton');
  box('hint','.voicehint');
  box('dock','.dock');
  box('pills','.bgpills');
  box('toast','.toasts .toast');
  box('toasts','.toasts');
  var cards=document.querySelectorAll('.pa-card');
  seen.cards=[];
  for(var i=0;i<cards.length;i+=1){
    var card=cards[i];
    var head=card.querySelector('.pa-head');
    var body=card.querySelector('.pa-body');
    var links=card.querySelectorAll('.pa-src');
    var hrefs=[];
    for(var j=0;j<links.length;j+=1)
      hrefs.push({tag:links[j].tagName.toLowerCase(),text:links[j].textContent,
        href:links[j].getAttribute('href')||'',rel:links[j].getAttribute('rel')||''});
    seen.cards.push({
      id:card.getAttribute('data-pa-id'),
      tone:card.getAttribute('data-pa-tone'),
      open:card.getAttribute('data-pa-open'),
      role:card.getAttribute('role'),
      live:card.getAttribute('aria-live'),
      expanded:head?head.getAttribute('aria-expanded'):null,
      title:card.querySelector('.pa-title').textContent,
      sub:card.querySelector('.pa-sub').textContent,
      bodyHidden:body?!!body.hidden:null,
      bodyText:body&&!body.hidden?body.textContent:'',
      sources:hrefs,
      html:card.innerHTML,
    });
  }
  seen.viewport={w:innerWidth,h:innerHeight};
  seen.installed=!!window.JarvisPresentationAttentionControl;
  return seen})()`;

const profile=mkdtempSync(join(tmpdir(),'jarvis-pa-cdp-'));
const port=9300+Math.floor(Math.random()*300);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions',
  '--hide-scrollbars','--autoplay-policy=no-user-gesture-required','--mute-audio',
  'about:blank',
],{stdio:'ignore'});

const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const reads=[];
const tabs=[];
const claimed=new Set();

try{
  const first=await poll(`http://127.0.0.1:${port}/json/list`);
  claimed.add(first.id);
  for(const step of plan){
    if(step.a==='open'){
      const count=Math.max(1,Number(step.tabs)||1);
      for(let i=0;i<count;i+=1){
        const target=i===0?first:await newTab();
        const tab=await connect(target.webSocketDebuggerUrl);
        await tab.send('Page.enable');
        await tab.send('Runtime.enable');
        await tab.send('Emulation.setEmulatedMedia',{features:step.reducedMotion
          ?[{name:'prefers-reduced-motion',value:'reduce'}]:[]});
        await tab.send('Page.addScriptToEvaluateOnNewDocument',{source:PROBE});
        await tab.send('Page.navigate',{url:base+'/'});
        await sleep(step.settleMs||1100);
        await tab.send('Emulation.setDeviceMetricsOverride',{width:step.width||1440,
          height:step.height||900,deviceScaleFactor:1,mobile:false});
        await sleep(200);
        const said=await tab.eval(WRAP);
        if(said!=='ok')throw new Error('bgCue non enveloppe : '+said);
        tabs.push(tab);
      }
      continue;
    }
    if(step.a==='status'){
      status=step.value;
      await sleep(step.waitMs||1400);
      continue;
    }
    if(step.a==='mount'){
      const tab=tabs[step.tab||0];
      if(step.palette){
        const said=await tab.eval(MOUNT_PALETTE);
        if(said!=='ok')throw new Error('palette : '+said);
      }
      for(let i=0;i<(Number(step.toasts)||0);i+=1)
        await tab.eval(`toast({title:'Test',sub:'Une notification ordinaire sur deux lignes au moins',ms:600000})`);
      if(step.panel)await tab.eval(`document.getElementById('panel').classList.add('open')`);
      await sleep(250);
      continue;
    }
    if(step.a==='reload'){
      const tab=tabs[step.tab||0];
      await tab.send('Page.navigate',{url:base+'/'});
      await sleep(step.settleMs||1200);
      const said=await tab.eval(WRAP);
      if(said!=='ok')throw new Error('bgCue non enveloppe apres rechargement : '+said);
      continue;
    }
    if(step.a==='click'){
      const tab=tabs[step.tab||0];
      const said=await tab.eval(`(function(){
        var el=document.querySelector(${JSON.stringify(step.selector)});
        if(!el)return 'absent';el.click();return 'ok'})()`);
      if(said!=='ok'&&!step.optional)throw new Error('clic : '+step.selector+' '+said);
      await sleep(step.waitMs||250);
      continue;
    }
    if(step.a==='mark'){requests.push({method:'MARK',path:step.name,at:Date.now()});continue}
    if(step.a==='read'){
      const out=[];
      for(const tab of tabs)out.push(await tab.eval(READ));
      reads.push(out);
      continue;
    }
    if(step.a==='eval'){
      reads.push(await tabs[step.tab||0].eval(step.expr));
      continue;
    }
    throw new Error('action inconnue : '+step.a);
  }
  process.stdout.write(JSON.stringify({reads,requests}));
}finally{
  chrome.kill();
  server.close();
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Windows tient le dossier */}
}

async function connect(url){
  const ws=new WebSocket(url);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{
    const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify({id:mine,method,params}));
  });
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)
      throw new Error(r.exceptionDetails.exception?.description
        ||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  return {ws,send,eval:evaluate};
}

/* Un onglet de plus, par la porte HTTP de Chrome : `PUT /json/new`. Passer par
   le point d'entree navigateur du protocole aurait demande une seconde
   connexion dont rien d'autre ici n'a besoin. L'onglet nait sur `about:blank`
   pour que la sonde soit installee AVANT le premier document. */
async function newTab(){
  const made=await fetch(`http://127.0.0.1:${port}/json/new?about:blank`,{method:'PUT'});
  if(!made.ok)throw new Error('creation d onglet refusee : HTTP '+made.status);
  for(let i=0;i<60;i+=1){
    const list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const fresh=list.find(t=>t.type==='page'&&!claimed.has(t.id)&&t.webSocketDebuggerUrl);
    if(fresh){claimed.add(fresh.id);return fresh}
    await sleep(120);
  }
  throw new Error('onglet supplementaire jamais apparu');
}

async function poll(url){
  for(let i=0;i<100;i+=1){
    try{
      const list=await (await fetch(url)).json();
      const page=list.find(t=>t.type==='page');
      if(page&&page.webSocketDebuggerUrl)return page;
    }catch(_){/* Chrome n ecoute pas encore */}
    await sleep(150);
  }
  throw new Error('Chrome n a pas ouvert son port de debogage');
}
