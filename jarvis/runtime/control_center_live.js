(function(root){
  'use strict';
  const LABELS={starting:'DÉMARRAGE',active:'ACTIF',idle_candidate:'FERMETURE AUTO',stopping:'ARRÊT EN COURS',unknown_reap_required:'CLÔTURE INCERTAINE',status_unavailable:'ÉTAT INCONNU'};
  function duration(seconds){
    const n=Math.max(0,Math.floor(Number(seconds)||0)),h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;
    return h?`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`:`${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }
  function project(live){
    if(!live||live.visible!==true)return {visible:false};
    const state=String(live.state||'unknown_reap_required');
    const pending=live.stop&&live.stop.pending===true,retry=live.stop&&live.stop.can_retry===true,available=!live.stop||live.stop.available!==false;
    const details=[];
    if(live.usage)details.push(`usage fournisseur ${duration(live.usage.seconds)}${live.usage.final?' final':''}`);
    if(live.idle)details.push(live.idle.waiting_for_safe_point?'inactivité atteinte · attente d’un point sûr':`veille auto dans ${duration(live.idle.remaining_seconds)}`);
    if(live.cost_estimate){const c=live.cost_estimate;details.push(`estimation ${Number(c.amount).toFixed(4)} ${c.currency} · ${c.source}`)}
    if(!live.cost_estimate&&!live.usage)details.push('coût indisponible · aucun tarif courant configuré');
    return {visible:true,state,label:LABELS[state]||state.toUpperCase(),
      uncertain:live.uncertain===true||live.core_reachable===false,
      elapsed:Number(live.elapsed_seconds)||0,details,warning:live.warning||null,
      disabled:!available||(pending&&!retry)||state==='stopping',
      action:!available?'CORE INDISPONIBLE':retry?'RÉESSAYER L’ARRÊT':pending||state==='stopping'?'ARRÊT DEMANDÉ':'ARRÊTER'};
  }
  const api={duration,project};
  root.JarvisLiveView=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
