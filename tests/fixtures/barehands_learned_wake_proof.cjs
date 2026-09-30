/* Preuve « posture de réveil apprise » (30/09/2026), rejouable contre
   n'importe quelle version des modules : `node <ce fichier> <racine>`.

   La main de l'utilisateur est reconstruite depuis une **vraie** main
   photographiée passée au vrai MediaPipe (`open_palm_01`, jeu
   `barehands_real_hands.v1.json`) : on n'y touche qu'à l'index, ramené vers
   le pouce, jusqu'à retrouver les trois nombres mesurés pendant sa
   calibration — écart pouce-index ≈ 0,51 paume, index « pas assez déplié »
   (< 1,485), trois autres doigts à 1,817 paume. La main au repos est la même
   photographie, intacte : c'est le cas le plus dur (même main, mêmes trois
   doigts), pas un repos commode.

   Sort un JSON : ce que le code **d'usine** fait de cette main (l'échec vécu),
   puis, si le code sait relever une posture, ce que la calibration en fait et
   ce que la veille réveille ensuite. */
'use strict';
const path=require('path');
const root=path.resolve(process.argv[2]||path.join(__dirname,'..','..'));
const RT=path.join(root,'jarvis','runtime');
global.JarvisBarehandsContracts=require(path.join(RT,'control_center_barehands_adaptive.js'));
const B=require(path.join(RT,'control_center_barehands.js'));
const K=require(path.join(RT,'control_center_barehands_calibration.js'));
const doc=require(path.join(__dirname,'barehands_real_hands.v1.json'));

const clone=v=>JSON.parse(JSON.stringify(v));
const base=doc.hands.find(h=>h.photo==='open_palm_01.jpg');
function userHand(){
  const h=clone(base),L=h.landmarks;
  for(const [i,t] of [[8,.40],[7,.30],[6,.14]]){
    L[i].x+=(L[4].x-L[i].x)*t;L[i].y+=(L[4].y-L[i].y)*t;
  }
  return h;
}
/* Bruit du traqueur, déterministe : ±0,003 de l'image sur chaque point. */
let seed=7;
const rnd=()=>{seed=(seed*1103515245+12345)%2147483648;return seed/2147483648-.5};
const jitter=h=>{const c=clone(h);for(const p of c.landmarks){p.x+=rnd()*.006;p.y+=rnd()*.006}return c};
const d=(a,b,k)=>Math.hypot((a.x-b.x)*k,a.y-b.y);
function measure(h){
  const L=h.landmarks,k=h.aspect,p=d(L[0],L[9],k);
  return {gap:d(L[4],L[8],k)/p,index:d(L[0],L[8],k)/p,
    fold:Math.max(d(L[0],L[12],k),d(L[0],L[16],k),d(L[0],L[20],k))/p};
}
/* Ce que la couture du contrôleur publie pour une image (scalaires seuls). */
function published(h,options){
  const k=h.aspect,lm=h.landmarks;
  const out={handedness:'right',quality:.9,stillness:.9,
    gapPalms:measure(h).gap,indexReachPalms:measure(h).index,foldPalms:measure(h).fold,
    secondaryRatio:B.pinchRatioFor(lm,k,B.PINCH_CHANNEL.SECONDARY),
    primaryRatio:B.pinchRatioFor(lm,k,B.PINCH_CHANNEL.PRIMARY),
    cPose:B.cPoseScore?B.cPoseScore(lm,k,options):null,
    wakePose:B.wakePostureScore(lm,k,options)};
  if(typeof B.wakeSignatureFields==='function')Object.assign(out,B.wakeSignatureFields(lm,k));
  return out;
}
/* La veille : une image toutes les `wakeIntervalMs`, pendant `ms`. */
function wakes(h,options,ms){
  const det=B.createWakeDetector(options);
  let t=0,fired=false;
  for(;t<=ms;t+=B.DEFAULTS.wakeIntervalMs){
    const f=jitter(h);
    if(det.update(B.wakePostureScore(f.landmarks,f.aspect,options),t).wake)fired=true;
  }
  return fired;
}

const user=userHand();
const frames=Array.from({length:40},()=>jitter(user));
const rest=Array.from({length:40},()=>jitter(base));
const band=K.wakeBandOf(B.DEFAULTS);
const o=K.options({});
const factory={
  measured:measure(user),
  wakePose:B.wakePostureScore(user.landmarks,user.aspect,{}),
  pointing:B.pointingPostureScore(user.landmarks,user.aspect,{}),
  wakesAfter3s:wakes(user,{},3000),
  step:(()=>{const c=K.checkCPose(frames.map(f=>published(f,{})),band,o);
    return {ok:c.ok,cause:c.cause||null,reason:c.reason||null}})(),
};
const report={root,factory,learned:null};
if(typeof K.deriveWakePosture==='function'){
  const captured=K.deriveWakePosture(frames.map(f=>published(f,{})),rest.map(f=>published(f,{})),band,o);
  const learned={ok:captured.ok,cause:captured.cause||null,tolerance:captured.tolerance||null,
    restShare:captured.restShare===undefined?null:captured.restShare};
  if(captured.ok){
    const opts={wakeTemplate:captured.template};
    learned.userWakesWithin=(()=>{
      const det=B.createWakeDetector(opts);
      for(let t=0;t<=3000;t+=B.DEFAULTS.wakeIntervalMs){
        const f=jitter(user);
        if(det.update(B.wakePostureScore(f.landmarks,f.aspect,opts),t).wake)return t;
      }
      return null;
    })();
    learned.userPointing=B.pointingPostureScore(user.landmarks,user.aspect,opts);
    learned.restWakes=wakes(base,opts,5000);
    learned.others=doc.hands.map(h=>({photo:h.photo,posture:h.posture,
      wakes:wakes(h,opts,3000),pointing:+B.pointingPostureScore(h.landmarks,h.aspect,opts).toFixed(3)}));
    /* Et sa main qui pince : aucun réveil sur un clic. */
    const pinch=clone(user);const L=pinch.landmarks;
    for(const i of [8,7]){L[i].x+=(L[4].x-L[i].x)*.85;L[i].y+=(L[4].y-L[i].y)*.85}
    learned.pinchGap=measure(pinch).gap;
    learned.pinchWakes=wakes(pinch,opts,3000);
  }
  report.learned=learned;
}
process.stdout.write(JSON.stringify(report,null,1));
