/* Profil Chrome jetable des harnais navigateur (`_*_browser.mjs`) : il doit disparaître à CHAQUE passage.
   Un profil pèse ~12 Mo ; 1 100 profils oubliés dans %TEMP% ont rempli le disque C:. Sous Windows, `chrome.kill()`
   ne tue que le processus principal : ses enfants gardent le dossier ouvert et le `rmSync` du `finally` échoue en
   silence. `disposeChromeOnExit` garantit le nettoyage au tout dernier moment du processus Node (après le `finally`,
   et aussi après un `process.exit()` qui l'aurait sauté) : arbre Chrome tué, puis suppression avec reprises brèves.
   Échec final ignoré : un nettoyage raté ne doit pas faire échouer un test. */
import {execFileSync} from 'node:child_process';
import {rmSync} from 'node:fs';

export function disposeChromeOnExit(chrome, profile){
  process.once('exit', ()=>{
    killTree(chrome);
    try{rmSync(profile,{recursive:true,force:true,maxRetries:15,retryDelay:200})}
    catch(_){/* dernier recours : Windows tient encore un fichier ; rien de plus à faire à la sortie */}
  });
}

function killTree(child){
  if(!child)return;
  if(process.platform==='win32'&&child.pid){
    try{execFileSync('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore'});return}
    catch(_){/* déjà sorti : taskkill ne trouve plus le processus */}
  }
  try{child.kill()}catch(_){/* déjà sorti */}
}
