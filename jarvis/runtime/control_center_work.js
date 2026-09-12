/* Logique pure du panneau Agents : garde de révision, projection d'un travail
   Core en carte, durées (tâche 13), et cohérence mode / vérification du
   locuteur (tâche 08).

   Ce fichier est inséré tel quel dans la page par `ControlCenter.index` : la
   page reste un document unique, sans ressource externe, donc sans risque de
   servir au navigateur une version que le serveur n'a plus. Les tests
   exécutent ce même fichier avec node — ces fonctions ne touchent ni au DOM
   ni à l'état de la page, elles ne dépendent que de leurs arguments. */

/* Statuts Core non terminaux : le travail n'a pas d'heure de fin. */
const ACTIVE=new Set(['pending','running','blocked']);

/* Révision Core : une réponse plus ancienne que l'instantané tenu pour le même
   magasin ne rembobine rien ; un autre store_id (Core redémarré) remplace
   tout. Même règle que `accept_snapshot` côté serveur. */
function acceptWork(held,next){
  if(!next||!next.store_id||typeof next.revision!=='number')return false;
  if(!held||held.store_id!==next.store_id)return true;
  return next.revision>=held.revision;
}

/* Date ISO de Core en millisecondes, ou null si elle manque ou ne se lit pas. */
function msOf(iso){const v=Date.parse(iso||'');return isFinite(v)?v:null}

/* Décalage « horloge serveur − horloge locale », estimé au milieu de
   l'aller-retour. null : le serveur n'a pas donné d'heure, et le décalage
   tenu ne change pas. */
function clockSkew(serverMs,sentAt,receivedAt){
  if(typeof serverMs!=='number'||!isFinite(serverMs))return null;
  return serverMs-Math.round((sentAt+receivedAt)/2);
}

/* Un travail Core affiché comme une carte. Les champs d'état viennent de Core
   et priment ; `diag` (tâche du tracker de même work_key) n'ajoute que ce
   que Core ne porte pas : prompt, type de sous-agent, tool_use_id, trace. */
function coreTask(item,diag){
  const d=diag||{};
  return {...d,id:item.external_id,provider_id:d.id||'',core:true,diag:!!diag,source:item.source,provider:item.source,
    kind:item.kind||d.kind||'other',status:item.status,description:item.label||'',activity:item.activity||'',
    summary:item.summary||'',model:item.model||'',error_class:item.error_class||'',
    started_ms:msOf(item.started_at),ended_ms:msOf(item.ended_at),background:!!item.background,
    tokens:item.tokens||0,tool_uses:item.tool_uses||0,parent_id:item.parent_external_id||null,
    progress:item.progress_fraction,work_id:item.work_id||'',revision:item.revision};
}

function isRunning(t){return !!t&&ACTIVE.has(t.status)}

/* Durée tirée des seules dates faisant foi (started_at / ended_at de Core) et
   de l'heure serveur (`now` : horloge locale corrigée de `clockSkew`) : aucun
   compteur tenu à part. Terminé : durée figée. En cours : depuis le début.
   Sans date de début, ou terminé sans date de fin : rien à afficher. */
function taskElapsed(t,now){
  const start=Number(t.started_ms);
  if(!start)return null;
  const end=Number(t.ended_ms);
  if(end)return Math.max(0,end-start);
  return isRunning(t)?Math.max(0,now-start):null;
}

/* Vérification du locuteur à retenir quand le mode de conversation change
   (tâche 08). null : ne rien toucher, la valeur tenue reste — un aller-retour
   entre modes ne perd pas une observation enregistrée. '' : revenir au défaut
   du mode, parce que la valeur tenue serait refusée à l'enregistrement
   (solo_owner + shadow, open_room + enforce). Les combinaisons acceptées sont
   celles que le serveur décrit (`verification_modes_by_mode`) : la page ne
   redécide rien. */
function verificationForMode(current,allowed){
  if(!current)return null;
  if(!Array.isArray(allowed)||!allowed.length)return null;
  return allowed.includes(current)?null:'';
}

/* Brouillon d'autorisation après un changement de champ. Seules les clés
   touchées y restent : ce qui n'y figure pas n'est pas envoyé, et la valeur
   enregistrée (`stored`) continue de s'appliquer. Changer de mode relâche donc
   la vérification tenue dans le brouillon, et ne force le défaut du mode que
   si la valeur enregistrée serait refusée par le nouveau mode. */
function authDraftAfterChange(draft,key,value,stored,allowedByMode){
  const next={...draft,[key]:value};
  if(key!=='conversation_mode')return next;
  delete next.speaker_verification;
  const held={...stored,...next}.speaker_verification||'';
  const forced=verificationForMode(held,(allowedByMode||{})[value]);
  if(forced!==null)next.speaker_verification=forced;
  return next;
}

/* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
if(typeof module!=='undefined'&&module.exports)
  module.exports={ACTIVE,acceptWork,msOf,clockSkew,coreTask,isRunning,taskElapsed,verificationForMode,authDraftAfterChange};
