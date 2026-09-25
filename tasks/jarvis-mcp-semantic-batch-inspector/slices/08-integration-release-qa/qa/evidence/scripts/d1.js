(()=>{const t0=window.__d1t0+2000;const S=__s8.samples.filter(s=>s.t>t0);const off={},orb={},ext={};
for(const s of S)for(const n of s.nodes){if(!n[0].startsWith('orion'))continue;(orb[n[0]]=orb[n[0]]||new Set()).add(n[5]);
const e=ext[n[0]]=ext[n[0]]||[1e9,1e9,-1e9,-1e9];e[0]=Math.min(e[0],n[1]);e[1]=Math.min(e[1],n[2]);e[2]=Math.max(e[2],n[1]+n[3]);e[3]=Math.max(e[3],n[2]+n[4]);
if(n[1]<0||n[2]<0||n[1]+n[3]>s.vw||n[2]+n[4]>s.vh)off[n[0]]=(off[n[0]]||0)+1}
return JSON.stringify({samples:S.length,secs:(S.at(-1).t-S[0].t)/1000,revs:[...new Set(S.map(s=>s.rev))],offscreen:off,orbiting:Object.fromEntries(Object.entries(orb).map(([k,v])=>[k,[...v]])),extent:ext,logs:__s8.logs})})()
