/* Logique pure du panneau Agents : garde de révision, projection d'un travail
   Core en carte, durées (tâche 13), et cohérence mode / vérification du
   locuteur (tâche 08).

   Ce fichier est inséré tel quel dans la page par `ControlCenter.index` : la
   page reste un document unique, sans ressource externe, donc sans risque de
   servir au navigateur une version que le serveur n'a plus. Les tests
   exécutent ce même fichier avec node — ces fonctions ne touchent ni au DOM
   ni à l'état de la page, elles ne dépendent que de leurs arguments. */

/* Statuts Core non terminaux : le travail n'a pas d'heure de fin. */
const ACTIVE=new Set(['pending','running','blocked']);

/* Révision Core : une réponse plus ancienne que l'instantané tenu pour le même
   magasin ne rembobine rien ; un autre store_id (Core redémarré) remplace
   tout. Même règle que `accept_snapshot` côté serveur. */
function acceptWork(held,next){
  if(!next||!next.store_id||typeof next.revision!=='number')return false;
  if(!held||held.store_id!==next.store_id)return true;
  return next.revision>=held.revision;
}

/* Date ISO de Core en millisecondes, ou null si elle manque ou ne se lit pas. */
function msOf(iso){const v=Date.parse(iso||'');return isFinite(v)?v:null}

/* Décalage « horloge serveur − horloge locale », estimé au milieu de
   l'aller-retour. null : le serveur n'a pas donné d'heure, et le décalage
   tenu ne change pas. */
function clockSkew(serverMs,sentAt,receivedAt){
  if(typeof serverMs!=='number'||!isFinite(serverMs))return null;
  return serverMs-Math.round((sentAt+receivedAt)/2);
}

/* Un travail Core affiché comme une carte. Les champs d'état viennent de Core
   et priment ; `diag` (tâche du tracker de même work_key) n'ajoute que ce
   que Core ne porte pas : prompt, type de sous-agent, tool_use_id, trace. */
function coreTask(item,diag){
  const d=diag||{};
  return {...d,id:item.external_id,provider_id:d.id||'',core:true,diag:!!diag,source:item.source,provider:item.source,
    kind:item.kind||d.kind||'other',status:item.status,description:item.label||'',activity:item.activity||'',
    summary:item.summary||'',model:item.model||'',error_class:item.error_class||'',
    started_ms:msOf(item.started_at),ended_ms:msOf(item.ended_at),background:!!item.background,
    tokens:item.tokens||0,tool_uses:item.tool_uses||0,parent_id:item.parent_external_id||null,
    progress:item.progress_fraction,work_id:item.work_id||'',revision:item.revision};
}

function isRunning(t){return !!t&&ACTIVE.has(t.status)}

/* Durée tirée des seules dates faisant foi (started_at / ended_at de Core) et
   de l'heure serveur (`now` : horloge locale corrigée de `clockSkew`) : aucun
   compteur tenu à part. Terminé : durée figée. En cours : depuis le début.
   Sans date de début, ou terminé sans date de fin : rien à afficher. */
function taskElapsed(t,now){
  const start=Number(t.started_ms);
  if(!start)return null;
  const end=Number(t.ended_ms);
  if(end)return Math.max(0,end-start);
  return isRunning(t)?Math.max(0,now-start):null;
}

/* Vérification du locuteur à retenir quand le mode de conversation change
   (tâche 08). null : ne rien toucher, la valeur tenue reste — un aller-retour
   entre modes ne perd pas une observation enregistrée. '' : revenir au défaut
   du mode, parce que la valeur tenue serait refusée à l'enregistrement
   (solo_owner + shadow, open_room + enforce). Les combinaisons acceptées sont
   celles que le serveur décrit (`verification_modes_by_mode`) : la page ne
   redécide rien. */
function verificationForMode(current,allowed){
  if(!current)return null;
  if(!Array.isArray(allowed)||!allowed.length)return null;
  return allowed.includes(current)?null:'';
}

/* Brouillon d'autorisation après un changement de champ. Seules les clés
   touchées y restent : ce qui n'y figure pas n'est pas envoyé, et la valeur
   enregistrée (`stored`) continue de s'appliquer. Changer de mode relâche donc
   la vérification tenue dans le brouillon, et ne force le défaut du mode que
   si la valeur enregistrée serait refusée par le nouveau mode. */
function authDraftAfterChange(draft,key,value,stored,allowedByMode){
  const next={...draft,[key]:value};
  if(key!=='conversation_mode')return next;
  delete next.speaker_verification;
  const held={...stored,...next}.speaker_verification||'';
  const forced=verificationForMode(held,(allowedByMode||{})[value]);
  if(forced!==null)next.speaker_verification=forced;
  return next;
}

/* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
if(typeof module!=='undefined'&&module.exports)
  module.exports={ACTIVE,acceptWork,msOf,clockSkew,coreTask,isRunning,taskElapsed,verificationForMode,authDraftAfterChange};

/* --------------------------------------------------------------------------
   Jarvis Theme API (browser only) + Omega test theme.
   This block lives in the injected Control Center script so the theme layer can
   reuse the existing feature handlers without duplicating Agents/Trace/Settings.
   The Node unit tests that import this file never execute it.
   -------------------------------------------------------------------------- */
(function installJarvisThemeLayer(){
  if(typeof window==='undefined'||typeof document==='undefined')return;

  const STORAGE_KEY='jarvis.ui.theme';
  const TAU=Math.PI*2;
  const VALID_STATES=new Set(['idle','listening','thinking','speaking']);
  const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
  const lerp=(a,b,t)=>a+(b-a)*t;
  const rgba=(rgb,a)=>`rgba(${Math.round(rgb[0])},${Math.round(rgb[1])},${Math.round(rgb[2])},${a})`;
  const STATE_COLORS={
    idle:[67,170,255],
    listening:[70,247,164],
    speaking:[255,151,61],
    thinking:[175,88,255],
  };
  const STATE_LABELS={idle:'IDLE',listening:'LISTENING',speaking:'TALKING',thinking:'THINKING'};

  const STYLE=`
#omegaFace{position:absolute;inset:0;width:100%;height:100%;display:none;pointer-events:none;z-index:0}
html[data-jarvis-theme="omega"] #omegaFace{display:block}
html[data-jarvis-theme="omega"] .face{display:none!important}
html[data-jarvis-theme="omega"] #app{background:
  radial-gradient(circle at 50% 48%,rgba(27,50,72,.18),transparent 34%),
  linear-gradient(180deg,#05090d 0%,#030609 100%)}
html[data-jarvis-theme="omega"] .topbar{left:18px;right:auto;top:18px;z-index:45}
html[data-jarvis-theme="omega"] .brand{display:none}
html[data-jarvis-theme="omega"] .state{
  border:1px solid color-mix(in srgb,var(--omega-accent,#6ee7ff) 24%,transparent);
  border-radius:999px;background:rgba(3,8,12,.46);backdrop-filter:blur(16px);
  font-size:10px;padding:7px 10px;letter-spacing:.1em;color:#6f8591;
  box-shadow:0 8px 30px rgba(0,0,0,.2)}
html[data-jarvis-theme="omega"] .state strong{color:var(--omega-accent,#6ee7ff)}
html[data-jarvis-theme="omega"] .voicehint{
  bottom:18px;border:0;border-radius:999px;background:rgba(3,8,12,.42);
  color:rgba(210,229,238,.58);font-size:10px;padding:7px 11px;
  letter-spacing:.11em;backdrop-filter:blur(14px);box-shadow:none}
html[data-jarvis-theme="omega"] .dock{
  right:18px;top:18px;transform:none;display:flex;gap:6px;z-index:50}
html[data-jarvis-theme="omega"] .dock .tool{display:block}
html[data-jarvis-theme="omega"] .dock button{
  width:34px;height:34px;border-radius:10px;padding:0;display:grid;place-items:center;
  border:1px solid rgba(174,205,220,.12);background:rgba(5,11,16,.46);
  color:rgba(213,231,239,.65);backdrop-filter:blur(16px);
  box-shadow:0 8px 24px rgba(0,0,0,.18);transition:.18s ease}
html[data-jarvis-theme="omega"] .dock button svg{width:15px;height:15px;display:block}
html[data-jarvis-theme="omega"] .dock button:hover,
html[data-jarvis-theme="omega"] .dock button.active{
  color:var(--omega-accent,#6ee7ff);border-color:color-mix(in srgb,var(--omega-accent,#6ee7ff) 46%,transparent);
  background:rgba(10,19,26,.72);transform:translateY(-1px)}
html[data-jarvis-theme="omega"] .dock .badge{right:-4px;top:-4px;transform:scale(.82)}
/* Pastilles d'arrière-plan : en ligne, juste à gauche du bouton Agents (premier
   des 5 outils : 5×34 + 4×6 = 194 px depuis right:18px). */
html[data-jarvis-theme="omega"] .bgpills{top:22px;right:222px;flex-direction:row-reverse;gap:6px;z-index:50}
html[data-jarvis-theme="omega"] .bgpill{width:26px;height:26px;font-size:10px;background:rgba(5,11,16,.56);backdrop-filter:blur(16px)}
html[data-jarvis-theme="omega"] .bgpop{border-radius:14px;background:rgba(4,10,15,.92);backdrop-filter:blur(26px)}
html[data-jarvis-theme="omega"] .panel{
  top:64px;right:18px;bottom:18px;width:min(500px,calc(100% - 36px));
  border:1px solid rgba(151,191,209,.14);border-radius:16px;
  background:rgba(4,10,15,.80);backdrop-filter:blur(26px);
  box-shadow:0 24px 80px rgba(0,0,0,.50);overflow:hidden;z-index:42}
html[data-jarvis-theme="omega"] .panel header{border-bottom-color:rgba(151,191,209,.12)}
html[data-jarvis-theme="omega"] .panel header h2{font-size:12px;letter-spacing:.1em}
html[data-jarvis-theme="omega"] .live-banner{
  top:66px;width:min(680px,calc(100vw - 44px));border-width:1px;border-radius:14px;
  backdrop-filter:blur(18px);z-index:48}
html[data-jarvis-theme="omega"] .overlay{backdrop-filter:blur(9px)}
html[data-jarvis-theme="omega"] .modal{
  border:1px solid rgba(151,191,209,.15);border-radius:18px;
  background:rgba(5,11,16,.94);box-shadow:0 30px 110px rgba(0,0,0,.58);overflow:hidden}
html[data-jarvis-theme="omega"] .choice.theme-choice{grid-template-columns:auto 1fr;border-radius:12px}
html[data-jarvis-theme="omega"] .choice.theme-choice.selected{
  border-color:color-mix(in srgb,var(--omega-accent,#6ee7ff) 54%,transparent);
  background:color-mix(in srgb,var(--omega-accent,#6ee7ff) 8%,#060d12)}
.theme-choice .theme-meta{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.theme-choice .theme-preview{margin-top:10px;height:48px;border:1px solid rgba(113,144,160,.12);
  border-radius:9px;position:relative;overflow:hidden;background:#05090d}
.theme-preview.circuit::before{content:'';position:absolute;inset:0;
  background:linear-gradient(90deg,transparent 24%,rgba(110,231,255,.16) 25% 26%,transparent 27% 54%,rgba(110,231,255,.13) 55% 56%,transparent 57%),
             linear-gradient(0deg,transparent 37%,rgba(110,231,255,.13) 38% 40%,transparent 41% 70%,rgba(110,231,255,.12) 71% 73%,transparent 74%)}
.theme-preview.circuit::after{content:'';position:absolute;width:30px;height:30px;border:1px solid #6ee7ff;border-radius:50%;
  left:50%;top:50%;transform:translate(-50%,-50%);box-shadow:0 0 16px rgba(110,231,255,.35)}
.theme-preview.omega::before{content:'';position:absolute;width:28px;height:28px;border:1px solid rgba(67,170,255,.78);
  border-radius:50%;left:50%;top:50%;transform:translate(-50%,-50%);box-shadow:0 0 18px rgba(67,170,255,.28)}
.theme-preview.omega::after{content:'';position:absolute;width:12px;height:12px;border-radius:50%;
  left:50%;top:50%;transform:translate(-50%,-50%);background:#43aaff;box-shadow:0 0 16px #43aaff}
@media(max-width:700px){
  html[data-jarvis-theme="omega"] .dock{right:10px;top:10px}
  /* Étroit : les pastilles passent sous la barre d'outils, l'état vocal reste lisible. */
  html[data-jarvis-theme="omega"] .bgpills{right:10px;top:52px}
  html[data-jarvis-theme="omega"] .topbar{left:10px;top:10px}
  html[data-jarvis-theme="omega"] .state{max-width:calc(100vw - 230px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  html[data-jarvis-theme="omega"] .panel{left:10px;right:10px;top:88px;bottom:10px;width:auto}
  html[data-jarvis-theme="omega"] .live-banner{top:88px;left:10px;right:10px;width:auto;transform:none}
}
@media(prefers-reduced-motion:reduce){
  html[data-jarvis-theme="omega"] .dock button{transition:none}
}`;

  function ensureStyle(){
    if(document.getElementById('jarvisThemeApiStyle'))return;
    const style=document.createElement('style');
    style.id='jarvisThemeApiStyle';
    style.textContent=STYLE;
    document.head.appendChild(style);
  }

  function toolIcon(name){
    const common='viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
    const icons={
      agents:`<svg ${common}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
      settings:`<svg ${common}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.1A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3v-4h.1A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.1A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 .6 1 1.7 1.7 0 0 0 1.1.4h.1v4h-.1a1.7 1.7 0 0 0-1.7.6Z"/></svg>`,
      trace:`<svg ${common}><path d="M3 12h4l2.2-6 4.1 12 2.2-6H21"/></svg>`,
      errors:`<svg ${common}><path d="M12 3 2.6 20h18.8L12 3Z"/><path d="M12 9v4M12 17h.01"/></svg>`,
      timeline:`<svg ${common}><path d="M4 4v16M10 4v7M10 15v5M16 4v3M16 11v9M20 4v16"/></svg>`,
    };
    return icons[name]||icons.trace;
  }

  function setOmegaTools(enabled){
    const specs=[
      ['agentsButton','agents',1],
      ['openTimeline','timeline',2],
      [null,'trace',3],
      ['openSettings','settings',4],
      [null,'errors',5],
    ];
    for(const [id,name,order] of specs){
      const button=id?document.getElementById(id):document.querySelector(`.dock button[data-panel="${name}"]`);
      if(!button)continue;
      if(!button.dataset.jarvisOriginalHtml)button.dataset.jarvisOriginalHtml=button.innerHTML;
      if(enabled){
        button.innerHTML=toolIcon(name);
        button.parentElement.style.order=String(order);
        button.setAttribute('aria-label',button.title||name);
      }else{
        button.innerHTML=button.dataset.jarvisOriginalHtml;
        button.parentElement.style.order='';
      }
    }
  }

  function ensureOmegaCanvas(){
    let canvas=document.getElementById('omegaFace');
    if(canvas)return canvas;
    canvas=document.createElement('canvas');
    canvas.id='omegaFace';
    canvas.setAttribute('aria-hidden','true');
    const root=document.getElementById('app');
    if(root)root.insertBefore(canvas,root.firstChild);
    return canvas;
  }

  function pointOnPolyline(points,progress){
    if(points.length<2)return points[0]||[0,0];
    let total=0;
    const lengths=[];
    for(let i=1;i<points.length;i++){
      const dx=points[i][0]-points[i-1][0],dy=points[i][1]-points[i-1][1];
      const len=Math.hypot(dx,dy);lengths.push(len);total+=len;
    }
    let remain=clamp(progress,0,1)*total;
    for(let i=0;i<lengths.length;i++){
      if(remain<=lengths[i]){
        const t=lengths[i]?remain/lengths[i]:0;
        return [lerp(points[i][0],points[i+1][0],t),lerp(points[i][1],points[i+1][1],t)];
      }
      remain-=lengths[i];
    }
    return points[points.length-1];
  }

  function stopMediaStream(stream){
    if(!stream)return;
    try{stream.getTracks().forEach(track=>{try{track.stop()}catch(_error){}})}catch(_error){}
  }

  function closeAudioContext(context){
    if(!context)return;
    try{const closed=context.close();if(closed&&typeof closed.catch==='function')closed.catch(()=>{})}catch(_error){}
  }

  class OmegaRenderer{
    constructor(){
      this.canvas=null;this.ctx=null;this.raf=0;this.last=0;this.rotation=0;
      this.state='idle';this.online=false;this.micStatus='idle';this.micLevel=0;
      this.micStream=null;this.audioContext=null;this.analyser=null;this.micData=null;this.micGeneration=0;this.mounted=false;
      this.circuits=[];this.resizeBound=()=>this.resize();this.frameBound=t=>this.frame(t);
      this.current={speed:.10,pulseHz:.24,pulseAmp:.07,glow:.56,listening:0,talking:0,circuit:0};
      this.color=[...STATE_COLORS.idle];this.snapshot={state:'idle',online:false};
      this.reduced=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }
    mount(){
      this.canvas=ensureOmegaCanvas();
      if(!this.canvas)return;
      this.mounted=true;
      this.ctx=this.canvas.getContext('2d');
      window.addEventListener('resize',this.resizeBound);
      this.resize();this.last=performance.now();
      if(!this.raf)this.raf=requestAnimationFrame(this.frameBound);
      this.setSnapshot(this.snapshot);
    }
    unmount(){
      this.mounted=false;
      if(this.raf)cancelAnimationFrame(this.raf);
      this.raf=0;
      window.removeEventListener('resize',this.resizeBound);
      this.stopMic();
      if(this.ctx&&this.canvas)this.ctx.clearRect(0,0,this.canvas.width,this.canvas.height);
      this.canvas=null;this.ctx=null;
    }
    setSnapshot(snapshot){
      const state=VALID_STATES.has(snapshot&&snapshot.state)?snapshot.state:'idle';
      this.snapshot={state,online:!!(snapshot&&snapshot.online)};
      this.state=state;this.online=this.snapshot.online;
      const c=STATE_COLORS[state]||STATE_COLORS.idle;
      document.documentElement.style.setProperty('--omega-accent',`rgb(${c.join(',')})`);
      if(state==='listening'&&this.online)this.ensureMic();
      else if(this.micStream||this.audioContext||this.micStatus==='requesting'||this.micStatus==='active')this.stopMic();
      const label=document.getElementById('voiceState');
      if(label&&document.documentElement.dataset.jarvisTheme==='omega'&&this.online)label.textContent=STATE_LABELS[state]||state.toUpperCase();
      if(!this.online&&this.micStream)this.stopMic();
    }
    async ensureMic(){
      if(this.micStatus==='active'||this.micStatus==='requesting')return;
      if(!this.mounted||this.state!=='listening'||!this.online||document.documentElement.dataset.jarvisTheme!=='omega')return;
      if(!navigator.mediaDevices||typeof navigator.mediaDevices.getUserMedia!=='function'){
        this.micStatus='unavailable';return;
      }
      const generation=++this.micGeneration;let stream=null,context=null;
      this.micStatus='requesting';
      try{
        stream=await navigator.mediaDevices.getUserMedia({
          audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false
        });
        if(generation!==this.micGeneration||!this.mounted||this.state!=='listening'||!this.online||document.documentElement.dataset.jarvisTheme!=='omega'){
          stopMediaStream(stream);if(generation===this.micGeneration)this.micStatus='idle';return;
        }
        const AudioCtx=window.AudioContext||window.webkitAudioContext;
        if(!AudioCtx){
          stopMediaStream(stream);this.micStatus='unavailable';return;
        }
        context=new AudioCtx();
        const source=context.createMediaStreamSource(stream);
        const analyser=context.createAnalyser();
        analyser.fftSize=512;analyser.smoothingTimeConstant=.2;
        source.connect(analyser);
        if(generation!==this.micGeneration||!this.mounted||this.state!=='listening'||!this.online||document.documentElement.dataset.jarvisTheme!=='omega'){
          stopMediaStream(stream);closeAudioContext(context);if(generation===this.micGeneration)this.micStatus='idle';return;
        }
        this.micStream=stream;this.audioContext=context;this.analyser=analyser;
        this.micData=new Uint8Array(analyser.fftSize);this.micStatus='active';
      }catch(_error){
        if(stream&&this.micStream!==stream)stopMediaStream(stream);
        if(context&&this.audioContext!==context)closeAudioContext(context);
        if(generation===this.micGeneration&&this.mounted&&this.state==='listening'&&this.online)this.micStatus='denied';
      }
    }
    stopMic(){
      ++this.micGeneration;
      const stream=this.micStream,context=this.audioContext;
      this.micStream=null;this.audioContext=null;this.analyser=null;this.micData=null;this.micLevel=0;
      stopMediaStream(stream);closeAudioContext(context);
      if(this.micStatus==='active'||this.micStatus==='requesting')this.micStatus='idle';
    }
    resize(){
      if(!this.canvas||!this.ctx)return;
      const dpr=Math.min(window.devicePixelRatio||1,2);
      const w=Math.max(1,window.innerWidth),h=Math.max(1,window.innerHeight);
      this.canvas.width=Math.round(w*dpr);this.canvas.height=Math.round(h*dpr);
      this.canvas.style.width=w+'px';this.canvas.style.height=h+'px';
      this.ctx.setTransform(dpr,0,0,dpr,0,0);
      this.buildCircuits(w,h);
    }
    radius(w,h){return clamp(Math.min(w,h)*.165,92,178)}
    buildCircuits(w,h){
      const cx=w/2,cy=h/2,r=this.radius(w,h);
      this.circuits=[];
      const count=26;
      for(let i=0;i<count;i++){
        const a=TAU*i/count+Math.sin(i*2.17)*.045;
        const radial=[Math.cos(a),Math.sin(a)],tangent=[-radial[1],radial[0]];
        const side=i%2?1:-1;
        const p0=[cx+radial[0]*r*1.04,cy+radial[1]*r*1.04];
        const p1=[cx+radial[0]*r*(1.20+(i%4)*.035),cy+radial[1]*r*(1.20+(i%4)*.035)];
        const turn=r*(.12+(i%5)*.025)*side;
        const p2=[p1[0]+tangent[0]*turn,p1[1]+tangent[1]*turn];
        const reach=r*(.18+(i%6)*.035);
        const p3=[p2[0]+radial[0]*reach,p2[1]+radial[1]*reach];
        const finish=turn*(.38+((i*7)%5)*.08);
        const p4=[p3[0]+tangent[0]*finish,p3[1]+tangent[1]*finish];
        this.circuits.push({points:[p0,p1,p2,p3,p4],phase:(i*.173)%1,node:i%3===0});
      }
    }
    micWave(){
      if(!this.analyser||!this.micData)return null;
      this.analyser.getByteTimeDomainData(this.micData);
      let sum=0;
      for(const value of this.micData){const n=(value-128)/128;sum+=n*n}
      const rms=Math.sqrt(sum/this.micData.length);
      this.micLevel=lerp(this.micLevel,clamp(rms*3.2,0,1),.28);
      return this.micData;
    }
    targets(){
      if(!this.online)return {speed:.035,pulseHz:.14,pulseAmp:.025,glow:.18,listening:0,talking:0,circuit:0};
      if(this.state==='listening')return {speed:.22,pulseHz:.65,pulseAmp:.08,glow:.82,listening:1,talking:0,circuit:0};
      if(this.state==='speaking')return {speed:.32,pulseHz:1.05,pulseAmp:.16,glow:1.0,listening:0,talking:1,circuit:0};
      if(this.state==='thinking')return {speed:1.05,pulseHz:1.85,pulseAmp:.24,glow:1.28,listening:0,talking:0,circuit:1};
      return {speed:.10,pulseHz:.24,pulseAmp:.07,glow:.58,listening:0,talking:0,circuit:0};
    }
    frame(now){
      if(!this.ctx||!this.canvas)return;
      const dt=Math.min(.05,Math.max(.001,(now-this.last)/1000));this.last=now;
      const target=this.targets(),ease=1-Math.exp(-dt*5.5);
      for(const key of Object.keys(this.current))this.current[key]=lerp(this.current[key],target[key],ease);
      const targetColor=this.online?(STATE_COLORS[this.state]||STATE_COLORS.idle):STATE_COLORS.idle;
      for(let i=0;i<3;i++)this.color[i]=lerp(this.color[i],targetColor[i],ease);
      this.rotation+=this.current.speed*dt*(this.reduced?.22:1);
      this.draw(now/1000);
      this.raf=requestAnimationFrame(this.frameBound);
    }
    draw(t){
      const ctx=this.ctx,w=this.canvas.clientWidth,h=this.canvas.clientHeight;
      if(!w||!h)return;
      const cx=w/2,cy=h/2,r=this.radius(w,h),master=this.online?1:.45;
      const pulse=(1+Math.sin(t*TAU*this.current.pulseHz-Math.PI/2))/2;
      const coreScale=1+(pulse-.5)*2*this.current.pulseAmp;
      ctx.clearRect(0,0,w,h);

      const halo=ctx.createRadialGradient(cx,cy,0,cx,cy,r*2.4);
      halo.addColorStop(0,rgba(this.color,.10*this.current.glow*master));
      halo.addColorStop(.38,rgba(this.color,.035*this.current.glow*master));
      halo.addColorStop(1,'rgba(0,0,0,0)');
      ctx.fillStyle=halo;ctx.fillRect(0,0,w,h);

      if(this.current.circuit>.01)this.drawCircuits(ctx,t,this.current.circuit*master);

      ctx.save();ctx.translate(cx,cy);ctx.rotate(this.rotation);
      ctx.strokeStyle=rgba(this.color,.11*master);ctx.lineWidth=1;
      ctx.beginPath();ctx.arc(0,0,r*1.18,0,TAU);ctx.stroke();
      for(let i=0;i<12;i++){
        const start=i*TAU/12+.06;
        const span=(i%3===0?.24:.13)+(this.current.circuit*.07);
        ctx.beginPath();ctx.lineWidth=i%3===0?1.6:1;
        ctx.strokeStyle=rgba(this.color,(i%3===0?.48:.23)*master);
        ctx.arc(0,0,r*(1+(i%2)*.07),start,start+span);ctx.stroke();
      }
      const ticks=this.state==='thinking'?64:40;
      for(let i=0;i<ticks;i++){
        const a=i*TAU/ticks,major=i%8===0;
        const inner=r*(1.105+(major?0:.008)),outer=inner+r*(major?.06:.026);
        ctx.beginPath();ctx.strokeStyle=rgba(this.color,(major?.45:.14)*master);ctx.lineWidth=major?1.3:.8;
        ctx.moveTo(Math.cos(a)*inner,Math.sin(a)*inner);ctx.lineTo(Math.cos(a)*outer,Math.sin(a)*outer);ctx.stroke();
      }
      ctx.restore();

      if(this.current.talking>.01)this.drawTalkingWave(ctx,cx,cy,r,t,this.current.talking*master);

      ctx.save();ctx.translate(cx,cy);
      const coreR=r*.46*coreScale;
      const coreGlow=ctx.createRadialGradient(0,0,0,0,0,coreR*1.65);
      coreGlow.addColorStop(0,rgba(this.color,(.90+.08*pulse)*master));
      coreGlow.addColorStop(.22,rgba(this.color,.46*this.current.glow*master));
      coreGlow.addColorStop(.58,rgba(this.color,.12*this.current.glow*master));
      coreGlow.addColorStop(1,'rgba(0,0,0,0)');
      ctx.fillStyle=coreGlow;ctx.beginPath();ctx.arc(0,0,coreR*1.65,0,TAU);ctx.fill();
      const disc=ctx.createRadialGradient(-coreR*.18,-coreR*.20,coreR*.04,0,0,coreR);
      disc.addColorStop(0,rgba([255,255,255],.78*master));
      disc.addColorStop(.15,rgba(this.color,.92*master));
      disc.addColorStop(.62,rgba(this.color,.20*master));
      disc.addColorStop(1,rgba(this.color,.025*master));
      ctx.fillStyle=disc;ctx.beginPath();ctx.arc(0,0,coreR,0,TAU);ctx.fill();
      ctx.strokeStyle=rgba(this.color,.56*master);ctx.lineWidth=1.2;ctx.beginPath();ctx.arc(0,0,coreR*1.08,0,TAU);ctx.stroke();
      ctx.strokeStyle=rgba(this.color,.16*master);ctx.beginPath();ctx.arc(0,0,r*.72,0,TAU);ctx.stroke();
      ctx.restore();

      if(this.current.listening>.01)this.drawListeningWave(ctx,cx,cy,r,this.current.listening*master);
      if(this.current.circuit>.01)this.drawThinkingParticles(ctx,cx,cy,r,t,this.current.circuit*master);

      if(this.state==='listening'&&this.online&&this.micStatus!=='active'){
        const text=this.micStatus==='requesting'?'MIC VISUEL - AUTORISATION...':
          this.micStatus==='denied'?'MIC VISUEL REFUSE':
          this.micStatus==='unavailable'?'MIC VISUEL INDISPONIBLE':'MIC VISUEL...';
        ctx.save();ctx.font='10px ui-monospace, SFMono-Regular, Consolas, monospace';
        ctx.textAlign='center';ctx.fillStyle=rgba(STATE_COLORS.listening,.48);
        ctx.fillText(text,cx,cy+r*1.62);ctx.restore();
      }
    }
    drawListeningWave(ctx,cx,cy,r,alpha){
      const data=this.micWave();
      const coreR=r*.43;
      ctx.save();ctx.beginPath();ctx.arc(cx,cy,coreR*.92,0,TAU);ctx.clip();
      ctx.beginPath();
      const count=128;
      for(let i=0;i<count;i++){
        const u=i/(count-1),x=(u*2-1)*coreR*.78;
        const envelope=Math.sqrt(Math.max(0,1-Math.pow(x/(coreR*.82),2)));
        const sample=data?((data[Math.floor(u*(data.length-1))]-128)/128):0;
        const y=sample*coreR*.82*envelope;
        if(i===0)ctx.moveTo(cx+x,cy+y);else ctx.lineTo(cx+x,cy+y);
      }
      ctx.strokeStyle=rgba(STATE_COLORS.listening,.92*alpha);ctx.lineWidth=2.2;
      ctx.shadowColor=rgba(STATE_COLORS.listening,.9);ctx.shadowBlur=12+this.micLevel*18;ctx.stroke();
      ctx.shadowBlur=0;
      ctx.strokeStyle=rgba(STATE_COLORS.listening,.14*alpha);ctx.lineWidth=7;ctx.stroke();
      ctx.restore();
    }
    drawTalkingWave(ctx,cx,cy,r,t,alpha){
      const blue=[72,181,255],points=220;
      ctx.save();ctx.beginPath();
      for(let i=0;i<=points;i++){
        const a=i/points*TAU;
        const wave=.56*Math.sin(a*14-t*8.4)+.27*Math.sin(a*23+t*5.1)+.17*Math.sin(a*7-t*3.0);
        const breath=.72+.28*Math.sin(t*5.6+a*2.0);
        const rr=r*(1.12+wave*breath*.044*alpha);
        const x=cx+Math.cos(a)*rr,y=cy+Math.sin(a)*rr;
        if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
      }
      ctx.closePath();ctx.strokeStyle=rgba(blue,.82*alpha);ctx.lineWidth=1.8;
      ctx.shadowColor=rgba(blue,.9);ctx.shadowBlur=14;ctx.stroke();
      ctx.shadowBlur=0;ctx.strokeStyle=rgba(blue,.16*alpha);ctx.lineWidth=7;ctx.stroke();ctx.restore();
    }
    drawCircuits(ctx,t,alpha){
      ctx.save();ctx.globalCompositeOperation='lighter';
      const color=STATE_COLORS.thinking;
      for(let i=0;i<this.circuits.length;i++){
        const path=this.circuits[i],points=path.points;
        ctx.beginPath();ctx.moveTo(points[0][0],points[0][1]);
        for(let j=1;j<points.length;j++)ctx.lineTo(points[j][0],points[j][1]);
        ctx.strokeStyle=rgba(color,(.055+(i%4)*.012)*alpha);ctx.lineWidth=i%5===0?1.4:.9;ctx.stroke();
        for(let j=1;j<points.length;j++){
          const p=points[j];ctx.fillStyle=rgba(color,(j===points.length-1?.24:.10)*alpha);
          ctx.beginPath();ctx.arc(p[0],p[1],j===points.length-1?1.7:1.1,0,TAU);ctx.fill();
        }
        const speed=.18+(i%5)*.025;
        const p=pointOnPolyline(points,(t*speed+path.phase)%1);
        const g=ctx.createRadialGradient(p[0],p[1],0,p[0],p[1],8);
        g.addColorStop(0,rgba([230,194,255],.92*alpha));g.addColorStop(.35,rgba(color,.55*alpha));g.addColorStop(1,'rgba(0,0,0,0)');
        ctx.fillStyle=g;ctx.beginPath();ctx.arc(p[0],p[1],8,0,TAU);ctx.fill();
      }
      ctx.restore();
    }
    drawThinkingParticles(ctx,cx,cy,r,t,alpha){
      ctx.save();ctx.globalCompositeOperation='lighter';
      const color=STATE_COLORS.thinking;
      for(let i=0;i<22;i++){
        const a=t*(.7+(i%4)*.14)*(i%2?1:-1)+i*2.399;
        const rr=r*(.74+(i%5)*.085);
        const x=cx+Math.cos(a)*rr,y=cy+Math.sin(a)*rr;
        ctx.fillStyle=rgba(color,(.18+(i%3)*.08)*alpha);
        ctx.beginPath();ctx.arc(x,y,1+(i%4)*.35,0,TAU);ctx.fill();
      }
      ctx.restore();
    }
  }

  const omegaRenderer=new OmegaRenderer();
  let snapshot={state:'idle',online:false};

  const context={
    root:()=>document.getElementById('app'),
    features:Object.freeze([
      {id:'agents',label:'Agents'},
      {id:'settings',label:'Settings'},
      {id:'trace',label:'Trace'},
      {id:'errors',label:'Errors'},
    ]),
  };

  const apiObject={
    version:1,
    registry:new Map(),
    activeId:null,
    snapshot,
    register(theme){
      if(!theme||typeof theme.id!=='string'||!theme.id.trim()||typeof theme.name!=='string')
        throw new TypeError('Invalid Jarvis theme');
      this.registry.set(theme.id,theme);return theme;
    },
    list(){return [...this.registry.values()].map(theme=>({
      id:theme.id,name:theme.name,status:theme.status||'stable',description:theme.description||'',preview:theme.preview||theme.id
    }))},
    current(){return this.activeId},
    setState(next){
      const state=VALID_STATES.has(next&&next.state)?next.state:'idle';
      snapshot={state,online:!!(next&&next.online)};this.snapshot=snapshot;
      const active=this.registry.get(this.activeId);
      if(active&&typeof active.setState==='function')active.setState(snapshot,context);
    },
    activate(id,{persist=true}={}){
      const next=this.registry.get(id);
      if(!next)throw new Error(`Unknown Jarvis theme: ${id}`);
      if(this.activeId===id){
        if(typeof next.setState==='function')next.setState(snapshot,context);
        return id;
      }
      const previous=this.registry.get(this.activeId);
      if(previous&&typeof previous.unmount==='function')previous.unmount(context);
      this.activeId=id;
      document.documentElement.dataset.jarvisTheme=id;
      if(typeof next.mount==='function')next.mount(context);
      if(typeof next.setState==='function')next.setState(snapshot,context);
      if(persist){try{localStorage.setItem(STORAGE_KEY,id)}catch(_error){}}
      const state=document.getElementById('voiceState');
      if(state&&snapshot.online)state.textContent=id==='omega'?(STATE_LABELS[snapshot.state]||snapshot.state.toUpperCase()):snapshot.state.toUpperCase();
      document.dispatchEvent(new CustomEvent('jarvis-theme-changed',{detail:{id}}));
      return id;
    },
  };

  apiObject.register({
    id:'circuit-board',name:'Circuit imprimé',status:'experimental',preview:'circuit',
    description:'Interface HUD historique et visualiseur en circuit imprimé.',
    mount(){setOmegaTools(false);document.documentElement.style.removeProperty('--omega-accent')},
    unmount(){},
    setState(){},
  });
  apiObject.register({
    id:'omega',name:'Omega',status:'experimental',preview:'omega',
    description:'Interface épurée et incarnation réactive aux états de JARVIS.',
    mount(){setOmegaTools(true);omegaRenderer.mount()},
    unmount(){omegaRenderer.unmount();setOmegaTools(false)},
    setState(next){omegaRenderer.setSnapshot(next)},
  });

  window.JarvisThemeAPI=apiObject;

  function appearanceHtml(){
    const active=apiObject.current();
    const cards=apiObject.list().map(theme=>`
      <label class="choice theme-choice ${theme.id===active?'selected':''}">
        <input type="radio" name="jarvisTheme" value="${esc(theme.id)}" ${theme.id===active?'checked':''}>
        <div>
          <div class="theme-meta"><strong>${esc(theme.name)}</strong>${theme.status==='experimental'?'<span class="tag warn">TEST</span>':''}</div>
          <div class="hint" style="margin-top:5px">${esc(theme.description)}</div>
          <div class="theme-preview ${theme.preview==='circuit'?'circuit':'omega'}" aria-hidden="true"></div>
        </div>
      </label>`).join('');
    return `<section>
      <h3>Apparence de JARVIS</h3>
      <div class="hint" style="margin-bottom:14px">Le thème change le renderer et la présentation des outils, jamais leur comportement. Le choix s'applique immédiatement.</div>
      <div class="choices">${cards}</div>
      <div class="notice info"><strong>Omega</strong> lit uniquement l'état sémantique de Voice. En mode Listening, sa waveform centrale utilise le microphone du navigateur pour suivre le volume réel ; si l'autorisation est refusée, elle reste plate au lieu de simuler une voix.</div>
    </section>`;
  }

  function bindAppearance(){
    modalContent.querySelectorAll('input[name=jarvisTheme]').forEach(input=>input.addEventListener('change',()=>{
      if(!input.checked)return;
      apiObject.activate(input.value);
      renderTab();
    }));
  }

  function installSettingsTab(){
    if(!Array.isArray(TABS)||TABS.some(tab=>tab.id==='appearance'))return;
    const before=TABS.findIndex(tab=>tab.id==='config');
    TABS.splice(before>=0?before:TABS.length,0,{id:'appearance',label:'Apparence',save:false});
    const baseRenderTab=renderTab;
    renderTab=async function(){
      if(SET.tab!=='appearance')return baseRenderTab();
      cleanupSettingsSurface();
      SET.renderRevision=(SET.renderRevision||0)+1;
      modalSave.style.display='none';
      modalSub.textContent='Le thème est appliqué immédiatement et peut être changé à chaud.';
      modalContent.innerHTML=appearanceHtml();
      bindAppearance();
      say('','');
    };
  }

  function bridgeStatusApi(){
    const baseApi=api;
    api=async function(path,opts){
      const value=await baseApi(path,opts);
      if(typeof path==='string'&&path.split('?')[0]==='/api/status'&&value&&typeof value==='object'){
        apiObject.setState({state:value.voice_state||'idle',online:value.voice_online===true});
      }
      return value;
    };
    baseApi('/api/status').then(value=>{
      apiObject.setState({state:value.voice_state||'idle',online:value.voice_online===true});
    }).catch(()=>apiObject.setState({state:'idle',online:false}));
  }

  function translateStateLabel(){
    const label=document.getElementById('voiceState');
    if(!label)return;
    const observer=new MutationObserver(()=>{
      if(apiObject.current()!=='omega'||!snapshot.online)return;
      const wanted=STATE_LABELS[snapshot.state]||snapshot.state.toUpperCase();
      if(label.textContent!==wanted)label.textContent=wanted;
    });
    observer.observe(label,{childList:true,characterData:true,subtree:true});
  }

  setTimeout(()=>{
    ensureStyle();
    installSettingsTab();
    bridgeStatusApi();
    translateStateLabel();
    let initial='circuit-board';
    try{const stored=localStorage.getItem(STORAGE_KEY);if(apiObject.registry.has(stored))initial=stored}catch(_error){}
    apiObject.activate(initial,{persist:false});
  },0);
})();
