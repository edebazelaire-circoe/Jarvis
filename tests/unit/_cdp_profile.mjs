/* Profil Chrome jetable des harnais navigateur (`_*_browser.mjs`) : il doit disparaître à CHAQUE passage, et seul le
   Chrome de CE harnais peut être tué.

   Un profil pèse ~12 Mo ; 1 100 profils oubliés dans %TEMP% ont rempli le disque C:. Sous Windows, `chrome.kill()`
   ne tue que le processus principal : ses enfants gardent le dossier ouvert et le `rmSync` du `finally` échoue en
   silence. Il faut donc tuer aussi les enfants — mais **jamais par `taskkill /PID <pid> /T`** : après `chrome.kill()`
   le PID mémorisé est mort, Windows le réemploie, et `/T` tuait l'arbre d'un processus étranger (QA S09 de
   jarvis-organic-agent-orchestration : Core et Control Center d'un bac à sable tués deux fois).

   `killChrome(child, profile)` arrête d'abord le processus principal par son handle (`child.kill()`, qui ne peut
   viser aucun autre processus), puis seulement des processus VIVANTS dont la ligne de commande porte
   `--user-data-dir=<profile>`, le dossier jetable unique de ce harnais (`mkdtemp`) : c'est leur identité, vérifiée au
   moment même de l'arrêt, sans `/T`. `disposeChromeOnExit` le fait au tout dernier moment du processus Node (après
   le `finally`, et aussi après un `process.exit()` qui l'aurait sauté), puis supprime le profil avec reprises
   brèves. Échec final ignoré : un nettoyage raté ne doit pas faire échouer un test.

   `assertSafeTarget(page, runtimeRoot)` refuse qu'un harnais pilote le JARVIS vivant de ce poste (ports 17653 et
   17654) ou écrive dans son dossier d'exécution (`~/.jarvis/instances/...`, `runtime/` de la checkout principale). */
import {execFileSync} from 'node:child_process';
import {rmSync} from 'node:fs';
import {homedir} from 'node:os';
import {resolve, sep} from 'node:path';

const KILL_BY_PROFILE=[
  "$p=$env:JARVIS_CDP_PROFILE",
  "if(-not $p -or $p.Length -lt 12){exit 0}",
  "$mark='--user-data-dir='+$p",
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($mark) } |",
  "  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
].join('\n');

export function killChrome(child, profile){
  try{if(child&&child.exitCode===null&&child.signalCode===null)child.kill()}catch(_){/* déjà sorti */}
  if(process.platform!=='win32'||!profile)return;
  try{
    execFileSync('powershell',['-NoProfile','-NonInteractive','-Command',KILL_BY_PROFILE],
      {stdio:'ignore',timeout:15000,env:{...process.env,JARVIS_CDP_PROFILE:String(profile)}});
  }catch(_){/* intentionnel : rien à arrêter, ou PowerShell indisponible ; le profil restera, rien d'étranger n'est touché */}
}

export function disposeChromeOnExit(chrome, profile){
  process.once('exit', ()=>{
    killChrome(chrome, profile);
    try{rmSync(profile,{recursive:true,force:true,maxRetries:15,retryDelay:200})}
    catch(_){/* dernier recours : Windows tient encore un fichier ; rien de plus à faire à la sortie */}
  });
}

/* Ports et dossiers du JARVIS vivant : un harnais de test ne les touche jamais (CLAUDE.md du dépôt). */
const LIVE_PORTS=new Set(['17653','17654']);
const LIVE_CHECKOUT_RUNTIME=resolve('C:/Projects/jarvis/jarvis/runtime');
const LIVE_INSTANCES=resolve(homedir(),'.jarvis','instances');

const norm=p=>resolve(p).toLowerCase();
const within=(child,parent)=>{const c=norm(child),p=norm(parent);return c===p||c.startsWith(p.endsWith(sep)?p:p+sep)};

export function unsafeTargetReason(page, runtimeRoot){
  if(/^https?:\/\//i.test(String(page||''))){
    let url=null;
    try{url=new URL(page)}catch(_){return `refus : URL illisible : ${page}`}
    const port=url.port||(url.protocol==='https:'?'443':'80');
    if(LIVE_PORTS.has(port))return `refus : ${page} vise le port ${port} du JARVIS vivant (17653/17654) ; utilisez un bac à sable sur d'autres ports.`;
  }
  if(runtimeRoot){
    if(within(runtimeRoot,LIVE_INSTANCES))return `refus : ${runtimeRoot} est sous la racine d'instance du JARVIS vivant (${LIVE_INSTANCES}) ; donnez le dossier d'exécution d'un bac à sable.`;
    if(within(runtimeRoot,LIVE_CHECKOUT_RUNTIME))return `refus : ${runtimeRoot} est le dossier runtime/ de la checkout principale ; donnez le dossier d'exécution d'un bac à sable.`;
  }
  return '';
}

/* À appeler avant tout lancement de Chrome : un refus sort en code 2 avec son message sur stderr. */
export function assertSafeTarget(page, runtimeRoot){
  const reason=unsafeTargetReason(page, runtimeRoot);
  if(reason){process.stderr.write(reason+'\n');process.exit(2)}
}
