/* Amorce du bac à sable d'une scène Remotion (handoff jarvis-remotion-presentation-integration, Slice 06 ;
   `docs/remotion-isolation.md`). Script EN LIGNE (nonce) de la page du cadre, placé après `host.js` et AVANT `scene.js` :
   il prend ses références (parent, écouteurs, protocole) avant que le code de la scène puisse les remplacer. Le protocole
   (`remotion_sandbox_protocol.js`) le précède dans le même script.

   Rôle : poser `remotion_staticBase`, écouter l'hôte (source = `window.parent`, origine = celle de l'hôte, champs exacts),
   monter le Player de Remotion à `init`, appliquer `props` / `control` / `cue`, répondre à `ping` par `pong`, remonter les
   violations de CSP et les erreurs (bornées). N'envoie JAMAIS qu'à l'origine de l'hôte (`targetOrigin` explicite).
   Ne lit aucun stockage, aucun jeton, n'ouvre aucune connexion. */
(function(){
  'use strict';
  const P=window.RemotionSandboxProtocol;
  const CFG=window.__JARVIS_SANDBOX_CONFIG__;
  const parentWindow=window.parent;
  const post=Function.prototype.call.bind(parentWindow.postMessage,parentWindow);
  const listen=window.addEventListener.bind(window);
  const stringify=JSON.stringify;
  let dropped=0,root=null,playerRef=null,mounted=null,reportsThisSecond=0,reportWindow=Date.now();
  /* Ordres reçus avant que le Player existe (`init` puis `control` arrivent dans le même instant, le rendu de React est asynchrone) :
     gardés, appliqués au montage (Slice 10). */
  const pending={playing:null,seek:null};
  let loaded=document.readyState==='complete';

  window.remotion_staticBase=CFG.staticBase;

  /*HARDEN:begin*/
  /* Best-effort, in-realm. The CSP has no WebRTC directive, so an RTCPeerConnection with an attacker stun:/turn: URL still sends UDP
     (QA B2). host.js (which runs before this script) does not use WebRTC, so the constructors are removed before any scene code
     can capture them, and the properties are locked. A scene that obtains a constructor by another route is not stopped by this. */
  ['RTCPeerConnection','webkitRTCPeerConnection','RTCDataChannel','RTCSessionDescription','RTCIceCandidate','RTCRtpSender','RTCRtpReceiver',
   'RTCRtpTransceiver','RTCDtlsTransport','RTCIceTransport','RTCSctpTransport'].forEach(function(name){
    try{Object.defineProperty(window,name,{value:undefined,writable:false,configurable:false})}catch(_e){/* already locked */}
  });
  /*HARDEN:end*/

  function send(type,fields){
    try{post(P.childMessage(type,fields),CFG.embedder)}catch(_e){/* l'hôte n'écoute plus : rien à faire */}
  }
  function report(type,fields){
    const t=Date.now();
    if(t-reportWindow>=1000){reportWindow=t;reportsThisSecond=0}
    if(++reportsThisSecond>P.LIMITS.maxReportsPerSecond)return;
    send(type,fields);
  }
  function heapMb(){
    try{const m=performance.memory;return m&&typeof m.usedJSHeapSize==='number'?Math.min(Math.round(m.usedJSHeapSize/1048576),1000000):-1}catch(_e){return -1}
  }
  /* Autoplay (Slice 10, politique d'autoplay du navigateur) : le Player démarre MUET, donc la lecture des images ne dépend jamais d'un
     AudioContext qui, sans geste dans CE cadre, ne se reprend pas (la lecture resterait figée à l'image 0). Le son s'active par un
     vrai clic ou une vraie touche DANS le cadre (le geste de l'utilisateur est le seul que le navigateur reconnaît ici ; le cadre n'a
     pas `allow="autoplay"`). Un message de l'hôte ne peut pas le faire à sa place : un `postMessage` n'est pas un geste. */
  function isMuted(){
    try{return playerRef&&playerRef.current?playerRef.current.isMuted():true}catch(_e){return true}
  }
  function unmuteOnGesture(event){
    if(!event.isTrusted)return;
    try{if(playerRef&&playerRef.current&&playerRef.current.isMuted())playerRef.current.unmute()}catch(error){report('error',{message:String(error&&error.message||error)})}
  }

  function currentFrame(){
    try{return playerRef&&playerRef.current?playerRef.current.getCurrentFrame():-1}catch(_e){return -1}
  }

  function render(){
    const H=globalThis.__JARVIS_HOST__;
    const scene=globalThis.JarvisScene;
    if(!H||!scene||typeof scene.component!=='function'&&typeof scene.component!=='object'){
      report('error',{message:'scene did not load (host or JarvisScene missing)'});return;
    }
    const React=H.react,Player=H['@remotion/player'].Player;
    if(root===null){
      root=H['react-dom/client'].createRoot(document.getElementById('root'));
      playerRef={current:null};
    }
    root.render(React.createElement(Player,{
      ref:function(instance){playerRef.current=instance;if(instance)applyPending()},component:scene.component,durationInFrames:mounted.composition.durationInFrames,fps:mounted.composition.fps,
      compositionWidth:mounted.composition.width,compositionHeight:mounted.composition.height,inputProps:mounted.props,
      initiallyMuted:true,controls:false,clickToPlay:false,doubleClickToFullscreen:false,spaceKeyToPlayOrPause:false,loop:true,
      style:{width:'100%',height:'100%'},
      onError:function(error){report('error',{message:String(error&&error.message||error)})}
    }));
  }

  function applyPending(){
    const player=playerRef&&playerRef.current;
    if(!player)return;
    try{
      if(pending.seek!==null){const frame=pending.seek;pending.seek=null;player.seekTo(frame)}
      if(pending.playing!==null){const wanted=pending.playing;pending.playing=null;if(wanted)player.play();else player.pause()}
    }catch(error){report('error',{message:String(error&&error.message||error)})}
  }

  function safeRender(){
    try{render()}catch(error){report('error',{message:String(error&&error.message||error)})}
  }

  function handle(message){
    switch(message.type){
      case 'init':
        mounted={composition:message.composition,props:message.props};
        if(loaded)safeRender();   // otherwise `load` renders: scene.js runs after this script, and `init` can arrive first
        break;
      case 'props':
        if(mounted){mounted.props=message.props;if(loaded)safeRender()}
        break;
      case 'control':
        try{
          const player=playerRef&&playerRef.current;
          if(player){
            if(message.action==='play')player.play();
            else if(message.action==='pause')player.pause();
            else player.seekTo(message.frame);
          }else if(message.action==='seek')pending.seek=message.frame;
          else pending.playing=message.action==='play';
        }catch(error){report('error',{message:String(error&&error.message||error)})}
        break;
      case 'cue':
        try{if(playerRef&&playerRef.current)playerRef.current.seekTo(message.frame);else pending.seek=message.frame}catch(error){report('error',{message:String(error&&error.message||error)})}
        break;
      case 'ping':
        send('pong',{n:message.n,frame:currentFrame(),dropped,heap:heapMb(),muted:isMuted()});
        break;
      case 'teardown':
        try{if(root)root.unmount()}catch(_e){}
        root=null;playerRef=null;mounted=null;pending.playing=null;pending.seek=null;
        break;
      default:break;
    }
  }

  listen('pointerdown',unmuteOnGesture,true);
  listen('keydown',unmuteOnGesture,true);
  listen('load',function(){loaded=true;if(mounted)safeRender()});
  listen('message',function(event){
    const parsed=P.parseHostMessage(event,parentWindow,CFG.embedder);
    if(!parsed.ok){dropped+=1;return}
    handle(parsed.message);
  });
  listen('securitypolicyviolation',function(event){
    report('violation',{directive:String(event.effectiveDirective||event.violatedDirective||'unknown').replace(/[^a-z-]/g,'').slice(0,40)||'unknown',
      blocked:String(event.blockedURI||'')});
  });
  listen('error',function(event){report('error',{message:String(event&&event.message||'script error')})});
  listen('unhandledrejection',function(event){report('error',{message:'unhandled rejection: '+String(event&&event.reason&&event.reason.message||event&&event.reason||'')})});

  send('ready',{});
})();
