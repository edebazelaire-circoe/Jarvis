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
import {existsSync, readFileSync, realpathSync, rmSync} from 'node:fs';
import {homedir, hostname} from 'node:os';
import {basename, dirname, join, resolve, sep} from 'node:path';

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

/* Ports et dossiers du JARVIS vivant : un harnais de test ne les touche jamais (CLAUDE.md du dépôt).

   Valeurs par défaut (17653/17654, `~/.jarvis/instances`, `runtime/` de la checkout principale), PLUS celles que ce
   poste configure vraiment et qui sont lisibles : variables `JARVIS_CORE_PORT`, `JARVIS_UI_PORT`,
   `JARVIS_RUNTIME_DIR`, `JARVIS_DATA_ROOT` de l'environnement du harnais, et les mêmes clés lues EN LECTURE SEULE
   dans `.env` et `config/jarvis.toml` (`runtime_dir`) de la checkout principale — seules ces clés sont lues, aucune
   autre valeur n'est retenue ni affichée.

   Tout chemin est comparé sous sa forme réelle (`canonicalPath`) : préfixe `\\?\` et `\\?\UNC\` retirés, partage
   administratif local (`\\localhost\c$\...`, `\\127.0.0.1\c$`, `\\<ce poste>\c$`) ramené à son lecteur, puis le
   plus proche parent existant déplié par `realpathSync.native` (noms courts 8.3, jonctions, liens). */
const LIVE_CHECKOUT=resolve('C:/Projects/jarvis/jarvis');
const DEFAULT_PORTS=['17653','17654'];
const PORT_KEYS=['JARVIS_CORE_PORT','JARVIS_UI_PORT'];
const DIR_KEYS=['JARVIS_RUNTIME_DIR','JARVIS_DATA_ROOT'];
const LOCAL_HOSTS=new Set(['localhost','127.0.0.1','::1','.',hostname().toLowerCase()]);

/* `KEY=valeur` de `.env` pour les seules clés demandées. */
function readEnvFile(path,keys){
  const out={};
  let text='';
  try{text=readFileSync(path,'utf8')}catch(_){return out}  // intentionnel : pas de .env sur ce poste, rien à ajouter
  for(const line of text.split(/\r?\n/)){
    const m=line.match(/^\s*(?:export\s+)?([A-Z_]+)\s*=\s*(.*)$/);
    if(m&&keys.includes(m[1]))out[m[1]]=m[2].replace(/\s+#.*$/,'').trim().replace(/^(['"])(.*)\1$/,'$2');
  }
  return out;
}
function readTomlRuntimeDir(path){
  try{const m=readFileSync(path,'utf8').match(/^\s*runtime_dir\s*=\s*["']([^"']+)["']/m);return m?m[1]:''}
  catch(_){return ''}  // intentionnel : configuration absente, la valeur par défaut est déjà refusée
}

export function canonicalPath(p){
  let s=String(p||'');
  if(process.platform==='win32'){
    s=s.replace(/\//g,'\\').replace(/^\\\\\?\\UNC\\/i,'\\\\').replace(/^\\\\\?\\/,'').replace(/^\\\\\.\\(?=[a-z]:)/i,'');
    const share=s.match(/^\\\\([^\\]+)\\([a-z])\$(\\.*)?$/i);
    if(share&&LOCAL_HOSTS.has(share[1].toLowerCase()))s=`${share[2]}:${share[3]||'\\'}`;
  }
  s=resolve(s);
  let head=s;const tail=[];
  while(!existsSync(head)){const up=dirname(head);if(up===head)break;tail.unshift(basename(head));head=up}
  try{head=realpathSync.native(head)}catch(_){/* intentionnel : parent illisible, on compare la forme résolue */}
  if(process.platform==='win32')head=head.replace(/^\\\\\?\\UNC\\/i,'\\\\').replace(/^\\\\\?\\/,'');
  const full=tail.length?join(head,...tail):head;
  return process.platform==='win32'?full.toLowerCase():full;
}
const within=(child,parent)=>{const c=canonicalPath(child),p=canonicalPath(parent);return c===p||c.startsWith(p.endsWith(sep)?p:p+sep)};

/* Ce que ce poste désigne comme le JARVIS vivant, relu à chaque appel (l'environnement peut changer en test). */
export function liveTargets(env=process.env){
  const file=readEnvFile(join(LIVE_CHECKOUT,'.env'),[...PORT_KEYS,...DIR_KEYS]);
  const ports=new Set(DEFAULT_PORTS);
  for(const key of PORT_KEYS)for(const v of [env[key],file[key]])if(v&&/^\d{2,5}$/.test(String(v).trim()))ports.add(String(v).trim());
  const dirs=[{path:resolve(homedir(),'.jarvis','instances'),why:"la racine d'instance du JARVIS vivant"},
    {path:join(LIVE_CHECKOUT,'runtime'),why:'le dossier runtime/ de la checkout principale'}];
  const toml=readTomlRuntimeDir(join(LIVE_CHECKOUT,'config','jarvis.toml'));
  if(toml)dirs.push({path:resolve(LIVE_CHECKOUT,toml),why:'le runtime_dir configuré du JARVIS vivant'});
  for(const key of DIR_KEYS)for(const [v,from] of [[env[key],'environnement'],[file[key],'.env']])
    if(v)dirs.push({path:resolve(LIVE_CHECKOUT,v),why:`le ${key} configuré (${from})`});
  return {ports,dirs};
}

export function unsafeTargetReason(page, runtimeRoot, env=process.env){
  const live=liveTargets(env);
  if(/^https?:\/\//i.test(String(page||''))){
    let url=null;
    try{url=new URL(page)}catch(_){return `refus : URL illisible : ${page}`}
    const port=url.port||(url.protocol==='https:'?'443':'80');
    if(live.ports.has(port))return `refus : ${page} vise le port ${port} du JARVIS vivant (${[...live.ports].join('/')}) ; utilisez un bac à sable sur d'autres ports.`;
  }
  if(runtimeRoot){
    for(const dir of live.dirs)
      if(within(runtimeRoot,dir.path))return `refus : ${runtimeRoot} est sous ${dir.why} (${dir.path}) ; donnez le dossier d'exécution d'un bac à sable.`;
  }
  return '';
}

/* À appeler avant tout lancement de Chrome : un refus sort en code 2 avec son message sur stderr. */
export function assertSafeTarget(page, runtimeRoot){
  const reason=unsafeTargetReason(page, runtimeRoot);
  if(reason){process.stderr.write(reason+'\n');process.exit(2)}
}
