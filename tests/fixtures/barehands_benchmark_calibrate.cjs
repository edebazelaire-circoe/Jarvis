/* Calibration reproductible du banc d'essai Bare Hands (Slice 08, reprise QA).

   Ce script n'est pas un test : il produit les nombres que le contrat lisible
   cite (§ 17, décisions 62 et 63) — distribution des dimensions par
   utilisateur synthétique, taux de faux verdicts de la comparaison, puissance
   de détection — sur le **vrai** moteur, avec l'utilisateur réaliste de
   `barehands_benchmark_driver.cjs`. Tout est à graine : relancé, il rend les
   mêmes nombres.

     node tests/fixtures/barehands_benchmark_calibrate.cjs users [runs]
     node tests/fixtures/barehands_benchmark_calibrate.cjs false [pairs] [user]
     node tests/fixtures/barehands_benchmark_calibrate.cjs coverage [sims]
     node tests/fixtures/barehands_benchmark_calibrate.cjs power [pairs]
     node tests/fixtures/barehands_benchmark_calibrate.cjs reaction [runs]

   Sortie : un objet JSON sur stdout. */
'use strict';
const D=require('./barehands_benchmark_driver.cjs');
const {BM,C}=D;

const seedOf=i=>(1000+i*7919)>>>0;
const trialOpts=patch=>({trial:patch,source:'trial',trialRef:'tr-1'});
const run=o=>D.runSynthetic(o).then(r=>r.result);
const stats=xs=>{
  const v=xs.filter(x=>x!==null);
  if(!v.length)return {n:0};
  const m=v.reduce((a,b)=>a+b,0)/v.length;
  const sd=Math.sqrt(v.reduce((a,b)=>a+(b-m)**2,0)/Math.max(1,v.length-1));
  return {n:v.length,mean:+m.toFixed(1),sd:+sd.toFixed(1),min:Math.min(...v),max:Math.max(...v),nulls:xs.length-v.length};
};
const tally=()=>Object.fromEntries([...C.BENCHMARK_DIMENSIONS,'global'].map(k=>[k,{improved:0,regressed:0,unchanged:0,
  inconclusive:0,unmeasured:0}]));
const count=(t,cmp)=>{
  for(const k of C.BENCHMARK_DIMENSIONS)t[k][cmp.dimensions[k].verdict]+=1;
  t.global[cmp.global.verdict]+=1;
};

async function users(runs){
  const out={};
  for(const user of ['perfect','typical','tired','clumsy']){
    const dims={},globals=[];let simulated=0;
    for(let i=0;i<runs;i+=1){
      const r=await D.runSynthetic({seed:seedOf(i),performerSeed:i+1,user:user==='perfect'?undefined:user});
      simulated=Math.max(simulated,r.simulatedMs);
      const s=BM.scoreResult(r.result);
      for(const [k,v] of Object.entries(s.dimensions))(dims[k]||(dims[k]=[])).push(v.score);
      globals.push(s.global.score);
    }
    out[user]={global:stats(globals),maxSimulatedMs:simulated,
      dimensions:Object.fromEntries(Object.entries(dims).map(([k,v])=>[k,stats(v)]))};
  }
  return out;
}

/* Même utilisateur (réaliste), même profil, dispositions différentes : tout
   « amélioré » ou « régressé » est un faux verdict. */
async function falseVerdicts(pairs,user){
  const t=tally();
  for(let i=0;i<pairs;i+=1){
    const a=await run({seed:seedOf(2*i),performerSeed:2*i+1,user,runAt:1});
    const b=await run({seed:seedOf(2*i+1),performerSeed:2*i+2,user,runAt:2});
    count(t,BM.compareResults(a,b));
  }
  const rates=Object.fromEntries(Object.entries(t).map(([k,v])=>[k,+((v.improved+v.regressed)/pairs).toFixed(3)]));
  return {pairs,user,verdicts:t,falseRate:rates};
}

/* **Couverture des intervalles, par simulation** (reprise QA, round 3) :
   un résultat réel dont on remplace, dans chaque exercice qui la mesure, la
   latence de relâchement par n valeurs tirées d'une même loi log-normale
   (150 ms, σ = 0,35) des deux côtés. Pour n = 1 à 10 : la part des paires où
   l'intervalle de la métrique exclut zéro, la part de faux verdicts de la
   dimension (attendu : ≤ 5 %), et la puissance pour un relâchement 22 %
   plus court. */
async function coverage(sims){
  const base=(await D.runSynthetic({seed:9})).result;
  const rng=BM.createRandom(12345);
  const gauss=()=>{const u=Math.max(1e-12,rng.next()),v=rng.next();return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v)};
  const make=(n,runAt,shift)=>({...base,runAt,seed:runAt,exercises:base.exercises.map(e=>{
    if(!('release_latency_ms' in e.metrics))return e;
    const xs=Array.from({length:n},()=>Math.round(150*Math.exp(.35*gauss())*(1-shift)*1000)/1000);
    return {...e,samples:{...e.samples,release_latency_ms:xs},metrics:{...e.metrics,release_latency_ms:BM.statOf('release_latency_ms',xs)}};
  })});
  const rows=[];
  for(const n of [1,2,3,4,5,6,8,10]){
    let excluded=0,tested=0,falseDim=0,power=0;
    for(let i=0;i<sims;i+=1){
      const c=BM.compareResults(make(n,1+2*i,0),make(n,2+2*i,0),{replicates:400});
      const m=c.dimensions.release_reliability.metrics.find(x=>x.metric==='release_latency_ms');
      if(m.ci){tested+=1;if(m.ci[0]>0||m.ci[1]<0)excluded+=1}
      const v=c.dimensions.release_reliability.verdict;if(v==='improved'||v==='regressed')falseDim+=1;
      const d=BM.compareResults(make(n,1+2*i,0),make(n,2+2*i,.22),{replicates:400});
      if(d.dimensions.release_reliability.verdict==='improved')power+=1;
    }
    rows.push({n,sims,tested,ciExcludesZero:+(excluded/sims).toFixed(3),falseDimensionVerdict:+(falseDim/sims).toFixed(3),
      powerMinus22pct:+(power/sims).toFixed(3)});
  }
  return rows;
}

/* Un vrai changement de profil, même utilisateur : la part des paires où la
   dimension visée est vue « améliorée » (puissance), et les faux verdicts
   ailleurs. */
async function power(pairs){
  const cases={
    release_150_to_110:{before:trialOpts({releaseMs:150}),after:trialOpts({releaseMs:110}),target:'release_reliability'},
    assistance_0_to_05:{before:trialOpts({assistance:0}),after:{},target:'selection_accuracy'},
  };
  const out={};
  for(const [name,c] of Object.entries(cases)){
    const t=tally();
    for(let i=0;i<pairs;i+=1){
      const a=await run({seed:seedOf(4*i),performerSeed:4*i+1,user:'typical',runAt:1,...c.before});
      const b=await run({seed:seedOf(4*i+1),performerSeed:4*i+2,user:'typical',runAt:2,...c.after});
      count(t,BM.compareResults(a,b));
    }
    out[name]={pairs,target:c.target,detected:+(t[c.target].improved/pairs).toFixed(3),verdicts:t};
  }
  return out;
}

/* Le temps de réaction seul ne doit pas bouger la stabilité du pointeur. */
async function reaction(runs){
  const rows=[];
  for(const ms of [[0,0],[150,150],[300,300]]){
    const scores=[],jitter=[];
    for(let i=0;i<runs;i+=1){
      const r=await run({seed:seedOf(i),performerSeed:i+1,user:'typical',userOverrides:{reactionMs:ms}});
      scores.push(BM.scoreResult(r).dimensions.pointer_stability.score);
      jitter.push(r.exercises.find(e=>e.kind==='no_click_tracking').metrics.pointer_jitter_px);
    }
    rows.push({reactionMs:ms[0],pointer_stability:stats(scores),pointer_jitter_px:stats(jitter)});
  }
  return rows;
}

(async()=>{
  const mode=process.argv[2]||'users',n=Number(process.argv[3]||10);
  const t0=Date.now();
  /* `user` : un nom de `USERS`, ou des paramètres JSON (ex. le profil
     « fatigué » de la QA : réaction 320 ms, fatigue 2,5/min…). */
  const who=process.argv[4]||'typical';
  const user=who.startsWith('{')?JSON.parse(who):who;
  const body=mode==='users'?await users(n):mode==='false'?await falseVerdicts(n,user)
    :mode==='power'?await power(n):mode==='reaction'?await reaction(n):mode==='coverage'?await coverage(n):null;
  if(body===null)throw new Error(`mode inconnu : ${mode}`);
  process.stdout.write(JSON.stringify({mode,n,elapsedMs:Date.now()-t0,body},null,1)+'\n');
})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});
