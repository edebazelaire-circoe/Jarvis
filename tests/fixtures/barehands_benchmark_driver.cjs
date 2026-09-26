/* Banc d'essai Bare Hands sous node : un **utilisateur synthétique** devant
   le **vrai** contrôleur (tâche adaptative, Slice 08).

   Ce fichier n'est pas du produit : c'est l'appareil de test qui fait passer
   un banc entier par le vrai moteur sans caméra. Il construit une main
   (21 points, comme MediaPipe) à chaque image, la donne à un faux
   `detectForVideo`, et laisse `createController` faire tout le reste — suivi,
   filtre, immobilité, pincement, intention de pointer — puis la couture de
   mesure (`onMeasure`) et les contacts de pincement nourrissent le déroulé
   (`createBenchmarkRunner`), qui lit le vrai résolveur, le vrai constat de
   sélection et le vrai moteur de captures.

   L'utilisateur synthétique est **en boucle fermée**, comme une personne : il
   lit ce qui est à l'écran (`runner.state()`) et y réagit, avec des gestes
   fixés (loi de Fitts, pincement de 90 ms, tenue de 100 ms). Ses choix ne
   dépendent que de l'écran et de sa propre graine : même graine de plan, même
   profil, même utilisateur → même trace, image pour image.

   Deux façons de rejouer :
   - `runSynthetic(opts)` : boucle fermée, et la trace des poses est rendue ;
   - `runSynthetic({...opts, replay: trace})` : boucle **ouverte**, les poses
     d'une trace enregistrée — « même trace synthétique ». */
'use strict';
const path=require('path');
const RT=path.join(__dirname,'..','..','jarvis','runtime');
const C=require(path.join(RT,'control_center_barehands_contracts.js'));
global.JarvisBarehandsContracts=C;
global.JarvisBarehandsRecorder=require(path.join(RT,'control_center_barehands_recorder.js'));
const B=require(path.join(RT,'control_center_barehands.js'));
global.JarvisBarehandsHandArt=require(path.join(RT,'control_center_barehands_hand_art.js'));
const K=require(path.join(RT,'control_center_barehands_calibration.js'));
const T=require(path.join(RT,'control_center_barehands_target.js'));
const G=require(path.join(RT,'control_center_scene_interact.js'));
const BM=require(path.join(RT,'control_center_barehands_benchmark.js'));

const VIEWPORT=Object.freeze({width:1280,height:720});
/* Taille de la main dans l'image : paume de 0,08 (au-dessus de
   `qualityPalmMin` 0,06), pour que le bout de l'index atteigne tout le champ
   sans que le poignet sorte du cadre. */
const HAND_SCALE=.4;

/* La main des tests de posture (`test_barehands_pointing_intent_js`) :
   poignet, base du majeur, index tendu à `reach` paumes, pouce à `gap`
   paumes du bout de l'index ; `aim` replie les trois autres doigts, `flat`
   les déplie. */
function baseHand(gap,posture){
  const reach=1.8;
  const lm=Array.from({length:21},()=>({x:.5,y:.5,z:0}));
  lm[0]={x:.5,y:.8,z:0};lm[9]={x:.5,y:.6,z:0};
  lm[8]={x:.5,y:.8-.2*reach,z:0};
  lm[4]={x:.5+.2*gap,y:lm[8].y,z:0};
  if(posture==='flat'){
    lm[12]={x:.4,y:.8-.2*reach*.98,z:0};lm[16]={x:.34,y:.8-.2*reach*.92,z:0};lm[20]={x:.3,y:.8-.2*reach*.8,z:0};
  }else{
    lm[12]={x:.42,y:.66,z:0};lm[16]={x:.45,y:.68,z:0};lm[20]={x:.55,y:.7,z:0};
  }
  return lm;
}
/* L'écran vers l'image : l'inverse de `toScreen` (miroir, marge). */
function landmarksAt(pose,viewport){
  const o=B.DEFAULTS,span=1-2*o.margin;
  let xi=o.margin+(pose.x/viewport.width)*span;
  if(o.mirror)xi=1-xi;
  const yi=o.margin+(pose.y/viewport.height)*span;
  const base=baseHand(pose.gap,pose.posture);
  const tip=base[8];
  return base.map(p=>({x:xi+(p.x-tip.x)*HAND_SCALE,y:yi+(p.y-tip.y)*HAND_SCALE,z:0}));
}

/* ------------------------------------------------------------------
   L'utilisateur synthétique. */
const OPEN_GAP=.65,CLOSED_GAP=.12;
const minJerk=u=>{const v=Math.min(Math.max(u,0),1);return v*v*v*(10-15*v+6*v*v)};
function createPerformer(o){
  const opts=o||{};
  const rng=BM.createRandom((opts.seed>>>0)^0xA5A5A5A5);
  const tremorPx=Number.isFinite(opts.tremorPx)?opts.tremorPx:.4;
  /* Fermetures parasites pendant « bouger sans cliquer » (défaut injecté
     côté trace) : une par `strayEveryMs`, à `strayGap`. */
  const strayEveryMs=opts.strayEveryMs||0,strayGap=Number.isFinite(opts.strayGap)?opts.strayGap:.15;
  let pos={x:VIEWPORT.width/2,y:VIEWPORT.height/2},gap=OPEN_GAP,posture='aim';
  let task=null;           // la tâche en cours : une suite de segments
  let key=null;            // ce que la tâche vise, pour savoir quand en changer
  let naturalAt=null,lastSeen=null;
  const noise=()=>(rng.next()+rng.next()+rng.next()-1.5)*tremorPx*1.2;
  /* Segments : `move` (vers un point, durée Fitts), `hold` (immobile),
     `pinch` (fermer), `release` (ouvrir), `drag` (déplacer fermé). */
  const fitts=(from,to,size)=>250+150*Math.log2(Math.hypot(to.x-from.x,to.y-from.y)/Math.max(8,size)+1);
  /* Une main encore fermée s'ouvre d'abord : personne ne part vers la cible
     suivante en tenant le pincement d'avant. */
  const opening=()=>gap<OPEN_GAP-.01?[{type:'gap',to:OPEN_GAP,ms:90}]:[];
  function clickTask(target,size){
    return [...opening(),{type:'move',to:target,ms:fitts(pos,target,size)},{type:'hold',ms:150},
      {type:'gap',to:CLOSED_GAP,ms:90},{type:'hold',ms:100},{type:'gap',to:OPEN_GAP,ms:90},{type:'hold',ms:500}];
  }
  function dragTask(frame,destination){
    const grab={x:frame.x+4,y:frame.y+frame.h/2};
    const drop={x:grab.x+(destination.x-(frame.x+frame.w/2)),y:grab.y+(destination.y-(frame.y+frame.h/2))};
    return [...opening(),{type:'move',to:grab,ms:fitts(pos,grab,20)},{type:'hold',ms:200},
      {type:'gap',to:CLOSED_GAP,ms:90},{type:'hold',ms:120},
      {type:'move',to:drop,ms:250+Math.hypot(drop.x-grab.x,drop.y-grab.y)*1.2},{type:'hold',ms:200},
      {type:'gap',to:OPEN_GAP,ms:90},{type:'hold',ms:250}];
  }
  function step(dt){
    if(!task||!task.length)return;
    const seg=task[0];
    if(seg.from===undefined){seg.from={...pos};seg.gapFrom=gap;seg.elapsed=0}
    seg.elapsed+=dt;
    const u=seg.ms>0?seg.elapsed/seg.ms:1;
    if(seg.type==='move'){const k=minJerk(u);pos={x:seg.from.x+(seg.to.x-seg.from.x)*k,y:seg.from.y+(seg.to.y-seg.from.y)*k}}
    if(seg.type==='gap')gap=seg.gapFrom+(seg.to-seg.gapFrom)*Math.min(1,u);
    if(u>=1)task.shift();
  }
  return {
    next(t,dt,s){
      const liveKind=s.phase==='live'?s.kind:null;
      if(s.phase!=='live'){
        /* Entre deux essais : main ouverte, posture du prochain essai. */
        task=null;key=null;gap=Math.min(OPEN_GAP,gap+dt/90*(OPEN_GAP-CLOSED_GAP));
        posture=s.mode==='natural'?'flat':'aim';naturalAt=null;
      }else if(liveKind==='no_click_tracking'&&s.mode==='natural'){
        posture='flat';
        if(naturalAt===null)naturalAt=t;
        const u=(t-naturalAt)/1000;
        pos={x:VIEWPORT.width/2+380*Math.sin(u*1.7),y:VIEWPORT.height/2+170*Math.sin(u*2.3+.7)};
        gap=OPEN_GAP;
        if(strayEveryMs>0){const phase=(t-naturalAt)%strayEveryMs;gap=phase>=strayEveryMs-120?strayGap:OPEN_GAP}
      }else if(liveKind==='no_click_tracking'){
        posture='aim';
        const spot=s.aimSpot;
        const k=spot?`${Math.round(spot.x)}|${Math.round(spot.y)}`:null;
        if(k!==key){key=k;task=spot?[{type:'move',to:spot,ms:fitts(pos,spot,24)},{type:'hold',ms:5000}]:null}
        step(dt);
      }else if(liveKind==='moving_target'){
        posture='aim';
        const target=s.stars[0];
        if(target){
          /* Poursuite : la main estime la vitesse de la cible et vise un peu
             devant (120 ms, le temps de fermer), puis pince en la suivant. */
          const seen=lastSeen&&lastSeen.id===target.id?lastSeen:null;
          const v=seen?{x:(target.x-seen.x)/(dt/1000),y:(target.y-seen.y)/(dt/1000)}:{x:0,y:0};
          lastSeen={id:target.id,x:target.x,y:target.y};
          const aim={x:target.x+v.x*.12,y:target.y+v.y*.12};
          const dx=aim.x-pos.x,dy=aim.y-pos.y,dist=Math.hypot(dx,dy);
          const step1={x:v.x*dt/1000+dx*Math.min(1,8*dt/1000),y:v.y*dt/1000+dy*Math.min(1,8*dt/1000)};
          const cap=1800*dt/1000,len=Math.hypot(step1.x,step1.y);
          const k=len>cap?cap/len:1;
          pos={x:pos.x+step1.x*k,y:pos.y+step1.y*k};
          if(key===null&&dist<target.size/3){key='pinch';task=[{type:'hold',ms:120},{type:'gap',to:CLOSED_GAP,ms:90},
            {type:'hold',ms:100},{type:'gap',to:OPEN_GAP,ms:90},{type:'hold',ms:400}]}
          if(task){const keep={...pos};step(dt);pos=keep;if(!task.length){task=null;key=null}}
        }
      }else if(s.frame&&s.destination){
        posture='aim';
        const k=`drag|${s.trial}|${s.step}`;
        if(k!==key||!task||!task.length){key=k;task=dragTask(s.frame,s.destination)}
        step(dt);
      }else if(s.stars.length){
        posture='aim';
        const target=s.stars.find(x=>x.expected)||s.stars[0];
        const k=`${s.exerciseRef}|${s.trial}|${s.step}|${target.id}`;
        if(k!==key||!task||!task.length){key=k;task=clickTask({x:target.x,y:target.y},target.size)}
        step(dt);
      }
      const x=pos.x+noise(),y=pos.y+noise();
      return {x,y,gap,posture};
    },
  };
}

/* ------------------------------------------------------------------
   Le monde du contrôleur : horloge, vidéo et modèle sont des doubles ; le
   reste est le produit. */
async function runSynthetic(o){
  const opts=o||{};
  const fps=opts.fps||30,dt=1000/fps;
  const composition=opts.composition||B.composeEffective({contracts:C,settings:opts.settings||C.SETTINGS_DEFAULTS,
    profile:opts.profile||null,trial:opts.trial||{},session:{},viewportWidth:VIEWPORT.width});
  const state={now:0,videoTime:0,result:{landmarks:[]}};
  const frames=new Map();let frameId=0;
  const statuses=[];
  let runner=null,driverError=null,controller=null,measured=0;
  const deps={
    options:{...composition.engine},
    handOverrides:(handedness,channel)=>{
      const by=composition.hands[handedness]||composition.hands.unknown;
      return by&&by[channel]?{...by[channel]}:null;
    },
    getUserMedia:async()=>({getTracks:()=>[],getVideoTracks:()=>[]}),
    createLandmarker:async()=>({detectForVideo:()=>state.result,close(){}}),
    attachVideo:async()=>({element:{},width:480,height:480,currentTime:()=>state.videoTime,dispose(){}}),
    overlay:{mount(){},unmount(){},render(){},watch(){},showDiagnostics(){}},
    interaction:{hover(){},click(){},clear(){},takeClicks:()=>[]},
    requestFrame:fn=>{const id=++frameId;frames.set(id,fn);return id},
    cancelFrame:id=>{frames.delete(id)},
    now:()=>state.now,viewport:()=>({...VIEWPORT}),
    keepAwake:()=>true,
    onStatus:s=>statuses.push(`${s.state}:${s.code}`),
    onMeasure:m=>{
      measured+=1;
      if(!runner||driverError)return;
      try{runner.frame(BM.engineFrame(m,controller.semantics()))}
      catch(error){driverError=error}
    },
  };
  controller=B.createController(deps);
  await controller.activate();
  const tick=()=>{state.now+=dt;state.videoTime+=1;const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn())};
  const performer=createPerformer({seed:opts.performerSeed||1,tremorPx:opts.tremorPx,
    strayEveryMs:opts.strayEveryMs,strayGap:opts.strayGap});
  const plan=BM.generatePlan(opts.seed===undefined?1:opts.seed);
  const view=BM.profileView({composition,source:opts.source||'defaults',trialRef:opts.trialRef===undefined?null:opts.trialRef});
  const log=[];
  runner=BM.createBenchmarkRunner({contracts:C,core:B,target:T,geometry:G,calibration:K,profile:view,plan,
    viewport:{...VIEWPORT,scale:4,cx:VIEWPORT.width/2,cy:VIEWPORT.height/2},
    pinchChannel:(channel,handedness)=>B.createPinchChannel(channel,controller.pinchChannelOptions(handedness,channel)),
    log:(level,event,data)=>log.push([level,event,data])});
  const trace=[];
  const replay=Array.isArray(opts.replay)?opts.replay:null;
  let index=0;
  const pose=t=>{
    if(replay){const p=replay[Math.min(index,replay.length-1)];index+=1;return p}
    const p=performer.next(t,dt,runner.state());
    trace.push([Math.round(p.x*1000)/1000,Math.round(p.y*1000)/1000,Math.round(p.gap*1e4)/1e4,p.posture]);
    return {x:p.x,y:p.y,gap:p.gap,posture:p.posture};
  };
  const show=p=>{
    const q=Array.isArray(p)?{x:p[0],y:p[1],gap:p[2],posture:p[3]}:p;
    state.result={landmarks:[landmarksAt(q,VIEWPORT)]};
  };
  /* Échauffement : la main se pose, le suivi s'installe, l'intention de
     pointer s'établit — avant le premier essai, comme une personne. */
  for(let i=0;i<Math.round(900/dt);i+=1){show(pose(state.now));tick()}
  runner.start(state.now);
  const maxFrames=Math.round((opts.maxMs||240000)/dt);
  let n=0;
  while(!runner.done()&&n<maxFrames&&!driverError){show(pose(state.now));tick();n+=1}
  if(driverError)throw driverError;
  if(!runner.done())throw new Error(`banc inachevé après ${n} images : ${JSON.stringify(runner.state())} ${statuses.join(',')}`);
  const result=runner.result({ref:'bm-1',runAt:opts.runAt===undefined?1:opts.runAt});
  return {result,trace,log,frames:n,measured,statuses,composition,view};
}

module.exports={C,B,K,T,G,BM,VIEWPORT,landmarksAt,createPerformer,runSynthetic};
