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

  window.remotion_staticBase=CFG.staticBase;

  function send(type,fields){
    try{post(P.childMessage(type,fields),CFG.embedder)}catch(_e){/* l'hôte n'écoute plus : rien à faire */}
  }
  function report(type,fields){
    const t=Date.now();
    if(t-reportWindow>=1000){reportWindow=t;reportsThisSecond=0}
    if(++reportsThisSecond>P.LIMITS.maxReportsPerSecond)return;
    send(type,fields);
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
      playerRef=React.createRef();
    }
    root.render(React.createElement(Player,{
      ref:playerRef,component:scene.component,durationInFrames:mounted.composition.durationInFrames,fps:mounted.composition.fps,
      compositionWidth:mounted.composition.width,compositionHeight:mounted.composition.height,inputProps:mounted.props,
      controls:false,clickToPlay:false,doubleClickToFullscreen:false,spaceKeyToPlayOrPause:false,loop:true,
      style:{width:'100%',height:'100%'},
      onError:function(error){report('error',{message:String(error&&error.message||error)})}
    }));
  }

  function handle(message){
    switch(message.type){
      case 'init':
        mounted={composition:message.composition,props:message.props};
        try{render()}catch(error){report('error',{message:String(error&&error.message||error)})}
        break;
      case 'props':
        if(mounted){mounted.props=message.props;try{render()}catch(error){report('error',{message:String(error&&error.message||error)})}}
        break;
      case 'control':
        try{
          const player=playerRef&&playerRef.current;
          if(player){
            if(message.action==='play')player.play();
            else if(message.action==='pause')player.pause();
            else player.seekTo(message.frame);
          }
        }catch(error){report('error',{message:String(error&&error.message||error)})}
        break;
      case 'cue':
        try{if(playerRef&&playerRef.current)playerRef.current.seekTo(message.frame)}catch(error){report('error',{message:String(error&&error.message||error)})}
        break;
      case 'ping':
        send('pong',{n:message.n,frame:currentFrame(),dropped});
        break;
      case 'teardown':
        try{if(root)root.unmount()}catch(_e){}
        root=null;playerRef=null;mounted=null;
        break;
      default:break;
    }
  }

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
