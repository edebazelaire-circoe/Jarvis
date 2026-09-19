/* Test Lab dans le Control Center (Slice 11 de la tâche jarvis-category2-test-lab).

   Contrat : `docs/testlab.md`, sections « Native API, CLI and HTTP » et
   « Control Center panel ». Deux parties, comme `control_center_timeline.js` :

   - `JarvisTestLabCore`, logique pure exécutée telle quelle par les tests node :
     vocabulaire, mises en forme, lecture d'un profil, gabarits du verdict, des
     métriques, des assertions, des artefacts, de la comparaison, vue d'une
     invite guidée et le portillon d'acquittement ;
   - un bloc navigateur qui branche la vue plein écran dans la page.

   TROIS RÈGLES TIENNENT CE FICHIER.

   1. AUCUNE INTELLIGENCE ICI. Le verdict d'une exécution est
      `RunOutcomeSummary` (dérivé par le domaine), la comparaison est
      `compare_runs`, le résumé d'un balayage est le document stocké. Cet écran
      les AFFICHE ; il n'en redérive aucun. La seule dérivation du fichier est
      `profileGate`, qui rejoue l'arithmétique exacte de
      `check_profile_permission` (jarvis/testlab/profiles.py) sur deux documents
      du serveur pour dire AVANT le lancement ce qui manque — et qui répète que
      le superviseur reste l'autorité.

   2. AUCUN ACQUITTEMENT SANS CLIC. `createPromptGate` est le seul chemin du
      fichier vers un POST sur `/prompt`, et il exige un événement de confiance
      (`event.isTrusted`), l'invite réellement ouverte, et une clé
      `run|prompt_id|sequence` jamais déjà répondue. La lecture du serveur
      (`observe`) ne peut pas poster : elle ne rend qu'un modèle de vue. Un
      sondage qui renvoie deux fois la même invite, un re-rendu, une reconnexion
      ou un minuteur ne peuvent donc rien envoyer au nom de la personne. Le
      portillon reste enfermé dans sa portée : `window.JarvisTestLab` n'en
      expose que la lecture (`gateView`), parce qu'`isTrusted` ne veut rien dire
      sur un objet fabriqué à la console.

      La règle s'arrête là, et c'est délibéré : `submit()` et `cancelRun()` NE
      sont PAS conditionnés à `isTrusted`. Mettre une exécution en file ou
      l'arrêter n'affirme rien sur la présence d'un humain — seule l'étape
      guidée porte cette affirmation, et c'est la seule que le laboratoire
      mesure. Les quatre identifiants créés dynamiquement (`tlabElapsed`,
      `tlabGauge`, `tlabRemaining`, `tlabStepNote`) ne sont pas dans la page :
      ils sont couverts par le test de démarrage sur DOM simulé, pas par
      l'épinglage statique des identifiants.

   3. LE DÉLAI APPARTIENT À L'EXÉCUTION. Le compte à rebours part du
      `remaining_s` du serveur (calculé depuis le `shown_at` du worker) et
      descend localement entre deux sondages pour que la ligne bouge ; à zéro il
      s'arrête, dit que la décision revient à l'exécution, et NE DÉSACTIVE PAS
      les boutons. Deux délais concurrents finiraient par se contredire. */

const JarvisTestLabCore=(function(){
  'use strict';

  const ROUTE='/api/testlab';

  /* ----------------------------------------------------------- vocabulaire
     Miroir des énumérations du domaine. Chaque valeur du serveur a un libellé
     lisible ET reste affichée telle quelle là où elle sert d'identifiant. */

  /* `RunOutcomeClass` (jarvis/testlab/outcomes.py), avec la phrase du tableau
     de ce module : « non mesurable » est le résultat le plus probable de ce
     laboratoire, il doit se lire sans connaître le vocabulaire. */
  const OUTCOMES=Object.freeze({
    passed:{label:'Réussi',tone:'ok',means:'le produit a fait ce que le diagnostic déclare.'},
    failed:{label:'Échoué',tone:'bad',means:'le produit n’a pas fait ce que le diagnostic déclare.'},
    inconclusive:{label:'Non mesurable',tone:'warn',means:'rien n’a pu être mesuré : aucun verdict n’est disponible. C’est un constat sur la situation, pas sur le produit.'},
    refused:{label:'Refusé',tone:'warn',means:'le Test Lab a décliné l’exécution : rien n’a été appris sur le produit.'},
    crashed:{label:'Panne du labo',tone:'bad',means:'le Test Lab lui-même a cassé autour de l’exécution : c’est un défaut de l’outil.'},
    cancelled:{label:'Annulé',tone:'muted',means:'quelqu’un a arrêté l’exécution.'},
    pending:{label:'En cours',tone:'busy',means:'l’exécution n’est pas terminée.'},
  });
  /* Un résultat que CETTE version du panneau ne connaît pas. Repli dans la
     direction alarmante, comme `outcome_of` côté Python (un code de panne non
     répertorié se lit `crashed`) : une exécution qu'on ne sait pas expliquer ne
     doit jamais se lire « en cours », ce qui la ferait attendre indéfiniment. */
  const UNKNOWN_OUTCOME=Object.freeze({label:'Résultat inconnu de cet écran',tone:'warn',
    means:'cette version du panneau ne connaît pas ce résultat : lisez le statut et le code de panne.'});
  /* Le seul lecteur de `outcome.outcome`. Absent (il n'y a pas encore de
     document de résultat) : « en cours ». Présent mais inconnu : le repli
     alarmant ci-dessus, jamais `pending`. */
  function readOutcome(value){
    if(value===null||value===undefined||value==='')return OUTCOMES.pending;
    return OUTCOMES[String(value)]||UNKNOWN_OUTCOME;
  }
  /* `RunStatus`. Le statut est ce que la machine à états enregistre ; le
     résultat ci-dessus est la façon de le lire. Les deux sont montrés. */
  const STATUSES=Object.freeze({queued:'En file',running:'En cours',passed:'Réussie',failed:'Échouée',
    errored:'En erreur',cancelled:'Annulée',timed_out:'Délai dépassé'});
  const TERMINAL=Object.freeze(['passed','failed','errored','cancelled','timed_out']);

  /* `ProfileName`, avec la phrase de sa docstring. */
  const PROFILES=Object.freeze({
    virtual:{label:'virtual',means:'chemin de production en mémoire avec des doublures contrôlées. Gratuit, sans appareil ni fournisseur.'},
    audio:{label:'audio',means:'chaîne audio réelle, sans acoustique physique ni fournisseur.'},
    live:{label:'live',means:'session(s) de fournisseur réelles : réseau et argent.'},
    'hardware:auto':{label:'hardware:auto',means:'appareils réels de ce poste, sans action humaine.'},
    'hardware:guided':{label:'hardware:guided',means:'appareils réels de ce poste, avec vous comme acteur du scénario.'},
  });
  /* `Capability`, et l'interrupteur d'environnement qui l'accorde
     (docs/testlab.md, « Where a capability grant comes from »). */
  const CAPABILITIES=Object.freeze({
    realtime_provider:'fournisseur Realtime réel (réseau, facturé)',
    llm_provider:'fournisseur LLM réel (réseau, facturé)',
    audio_input_device:'microphone de ce poste',
    audio_output_device:'haut-parleurs de ce poste',
    human_presence:'une personne présente devant le poste',
  });
  const OPT_INS=Object.freeze({realtime_provider:'JARVIS_TESTLAB_LIVE=1',llm_provider:'JARVIS_TESTLAB_LIVE=1',
    audio_input_device:'JARVIS_TESTLAB_HARDWARE=1',audio_output_device:'JARVIS_TESTLAB_HARDWARE=1',
    human_presence:'JARVIS_TESTLAB_GUIDED=1'});
  const DEVICE_CAPABILITIES=Object.freeze(['audio_input_device','audio_output_device']);

  /* `MetricUnit`, `MetricDirection`, `Comparator`, `AssertionOutcome`. */
  const UNITS=Object.freeze({ms:'ms',s:'s',count:'',ratio:'',percent:'%',boolean:'',db:'dB',hz:'Hz',usd:'USD',chars:'car.'});
  const DIRECTIONS=Object.freeze({higher_better:'plus haut = mieux',lower_better:'plus bas = mieux',neutral:'indicatif'});
  const COMPARATORS=Object.freeze({lt:'<',le:'≤',gt:'>',ge:'≥',eq:'=',ne:'≠'});
  const ASSERTION_OUTCOMES=Object.freeze({
    passed:{label:'Vérifiée',tone:'ok'},
    failed:{label:'En défaut',tone:'bad'},
    missing:{label:'Non mesurée',tone:'warn'},
  });
  /* `MetricChange` / `AssertionChange` / `IncomparableReason` (compare.py). */
  const CHANGES=Object.freeze({
    better:{label:'Mieux',tone:'ok',sign:'▲'},
    worse:{label:'Moins bien',tone:'bad',sign:'▼'},
    unchanged:{label:'Inchangé',tone:'muted',sign:'='},
    changed:{label:'Changé',tone:'busy',sign:'≠'},
  });
  const ASSERTION_CHANGES=Object.freeze({unchanged:{label:'Inchangée',tone:'muted'},fixed:{label:'Corrigée',tone:'ok'},
    regressed:{label:'Régression',tone:'bad'},appeared:{label:'Nouvelle',tone:'busy'},
    disappeared:{label:'Disparue',tone:'warn'},changed:{label:'Changée',tone:'warn'}});
  const INCOMPARABLE=Object.freeze({
    different_diagnostic:'les deux exécutions n’ont pas exécuté le même diagnostic',
    different_version:'les deux exécutions n’ont pas la même version du diagnostic',
    different_declaration:'la déclaration a été modifiée entre les deux exécutions',
    different_profile:'les deux exécutions n’ont pas le même profil',
    metric_missing_in_baseline:'la référence n’a pas mesuré cette métrique',
    metric_missing_in_candidate:'la candidate n’a pas mesuré cette métrique',
    different_value_type:'un côté a mesuré un booléen, l’autre un nombre',
    different_unit:'les deux déclarations donnent à cette métrique des unités différentes',
    run_not_terminal:'une exécution encore en file ou en cours n’a pas encore de preuve',
  });
  /* `ArtifactKind` (runs.py). */
  const ARTIFACTS=Object.freeze({config_snapshot:'Réglages appliqués',scenario:'Scénario joué',
    event_log:'Journal d’événements',trace_excerpt:'Extrait de trace',worker_log:'Journal du worker',
    metrics:'Métriques',report:'Rapport',audio_clip:'Extrait audio'});
  /* `GuidedAction`, avec exactement les consignes de `_ACTION_HINTS`
     (jarvis/testlab/presenter.py) : le terminal et l'écran disent la même chose. */
  const GUIDED_ACTIONS=Object.freeze({
    remain_silent:{label:'Rester silencieux',hint:'Ne dites rien jusqu’à la fin de l’étape, puis confirmez.'},
    say_phrase:{label:'Dire la phrase',hint:'Dites la phrase à voix haute, puis confirmez.'},
    interrupt:{label:'Interrompre',hint:'Attendez que Jarvis parle, dites la phrase par-dessus, puis confirmez.'},
    acknowledge:{label:'Confirmer',hint:'Confirmez quand vous l’avez fait.'},
  });

  /* ------------------------------------------------------------- mise en forme */

  function escapeHtml(value){
    return String(value===null||value===undefined?'':value)
      .replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function isNumber(value){return typeof value==='number'&&Number.isFinite(value)}
  /* Un nombre lisible : au plus trois décimales, jamais de notation
     scientifique, jamais `1.2000000000000002`. */
  function fmtNumber(value){
    if(!isNumber(value))return '—';
    if(Number.isInteger(value))return String(value);
    const rounded=Math.round(value*1000)/1000;
    return String(rounded);
  }
  function fmtValue(value,unit){
    if(value===null||value===undefined)return '—';
    if(typeof value==='boolean')return value?'oui':'non';
    if(unit==='boolean')return value?'oui':'non';
    const suffix=UNITS[unit];
    return fmtNumber(value)+(suffix?' '+suffix:'');
  }
  function fmtDuration(seconds){
    if(!isNumber(seconds)||seconds<0)return '—';
    if(seconds<60)return `${Math.round(seconds*10)/10} s`;
    const minutes=Math.floor(seconds/60),rest=Math.round(seconds-minutes*60);
    return `${minutes} min ${String(rest).padStart(2,'0')} s`;
  }
  /* Un montant, toujours chiffré : ce qui se compare à un budget. */
  function fmtUsd(usd){return isNumber(usd)?`${usd.toFixed(2)} USD`:'—'}
  /* Le même montant seul, sur une pastille : « gratuit » se lit mieux que 0.00. */
  function fmtCost(usd){
    if(!isNumber(usd))return '—';
    return usd===0?'gratuit':fmtUsd(usd);
  }
  /* Le même montant dans une phrase « ce que ça coûte » : « au plus gratuit »
     ne se dit pas. */
  function costPhrase(usd){
    if(!isNumber(usd))return 'coût non déclaré';
    return usd===0?'aucun coût en argent':`au plus ${fmtUsd(usd)}`;
  }
  function fmtBytes(bytes){
    if(!isNumber(bytes))return '—';
    if(bytes<1024)return `${bytes} o`;
    if(bytes<1024*1024)return `${Math.round(bytes/102.4)/10} kio`;
    return `${Math.round(bytes/104857.6)/10} Mio`;
  }
  function fmtClock(iso){
    const text=String(iso||'');
    return text.length>19?text.slice(11,19):text;
  }
  function shortRunId(runId){
    const text=String(runId||'');
    return text.length>22?`${text.slice(0,10)}…${text.slice(-8)}`:text;
  }
  function msOf(iso){
    if(!iso)return null;
    const value=Date.parse(iso);
    return Number.isFinite(value)?value:null;
  }

  /* -------------------------------------------------------------- catalogue */

  /* Les diagnostics du catalogue, filtrés sur le texte saisi. Le filtre ne
     touche qu'à l'affichage : il ne classe rien et n'écarte aucune version. */
  function catalogueRows(diagnostics,filter){
    const needle=String(filter||'').trim().toLowerCase();
    const rows=(Array.isArray(diagnostics)?diagnostics:[]).map(entry=>({
      diagnostic_id:entry.diagnostic_id,version:entry.version,title:entry.title,
      domain:entry.domain,description:entry.description,
      profiles:(entry.profiles||[]).map(item=>item.profile),
    }));
    if(!needle)return rows;
    return rows.filter(row=>[row.diagnostic_id,row.title,row.domain,row.description]
      .some(field=>String(field||'').toLowerCase().includes(needle)));
  }

  /* --------------------------------------------------------------- profils */

  /* Ce qu'un profil EXIGE, ce qu'il COÛTE, et ce qui l'empêche de tourner ici.
     Rejoue `check_profile_permission` (jarvis/testlab/profiles.py) : capacités
     manquantes dans l'ordre du vocabulaire, puis budget d'argent, puis budget
     de durée — mêmes comparaisons, sur `GET /diagnostics/{id}` et
     `GET /status`. Rien n'est deviné : un « bloquant » est un refus que le
     superviseur prononcera avant d'exécuter quoi que ce soit. La contention des
     appareils est un AVERTISSEMENT et jamais un bloquant : elle est re-sondée
     au moment de la réservation et peut se libérer d'ici là. */
  function profileGate(profile,status){
    const blockers=[],warnings=[];
    if(!profile)return {allowed:false,blockers:[{code:'unknown_profile',label:'Profil inconnu',
      detail:'ce profil n’est pas déclaré par cette version du diagnostic.',fix:null}],warnings};
    const requires=Array.isArray(profile.requires)?profile.requires:[];
    const cost=profile.cost||{};
    if(profile.availability&&profile.availability!=='available'){
      blockers.push({code:profile.unavailable_reason||'unavailable',
        label:'Aucune implémentation disponible',
        detail:`le nom d’implémentation « ${profile.implementation||'?'} » n’a pas de fabrique enregistrée (${profile.unavailable_reason||'unavailable'}).`,
        quote:profile.detail||null,fix:null});
    }
    const config=(status&&status.config)||null;
    const grant=(config&&config.grant)||null;
    if(grant){
      const granted=Array.isArray(grant.capabilities)?grant.capabilities:[];
      for(const capability of Object.keys(CAPABILITIES)){
        if(requires.includes(capability)&&!granted.includes(capability)){
          blockers.push({code:'capability_missing',
            label:`Capacité non accordée : ${capability}`,
            detail:`ce profil a besoin de ${CAPABILITIES[capability]}, et l’autorisation de ce processus ne l’accorde pas.`,
            fix:OPT_INS[capability]?`Démarrez le Control Center avec ${OPT_INS[capability]} dans son environnement.`:null});
        }
      }
      if(isNumber(cost.max_cost_usd)&&isNumber(grant.max_cost_usd)&&cost.max_cost_usd>grant.max_cost_usd){
        blockers.push({code:'cost_budget_exceeded',label:'Budget d’argent dépassé',
          detail:`le profil déclare au plus ${fmtUsd(cost.max_cost_usd)} et l’autorisation de ce processus s’arrête à ${fmtUsd(grant.max_cost_usd)}.`,
          fix:'Démarrez le Control Center avec JARVIS_TESTLAB_MAX_COST_USD au montant que vous acceptez de dépenser.'});
      }
      if(isNumber(grant.max_duration_s)&&isNumber(cost.max_duration_s)&&cost.max_duration_s>grant.max_duration_s){
        blockers.push({code:'duration_budget_exceeded',label:'Budget de durée dépassé',
          detail:`le profil déclare au plus ${fmtDuration(cost.max_duration_s)} et l’autorisation de ce processus s’arrête à ${fmtDuration(grant.max_duration_s)}.`,
          fix:null});
      }
      if(config.grant_refusal){
        warnings.push({code:'grant_refusal',label:'Autorisation réduite au démarrage',
          detail:null,quote:String(config.grant_refusal),fix:null});
      }
    }
    const contention=(status&&status.contention)||null;
    if(requires.some(item=>DEVICE_CAPABILITIES.includes(item))&&contention&&contention.available===false){
      warnings.push({code:'device_contention',label:'Appareils audio occupés',
        detail:`ce profil prend le microphone ou les haut-parleurs, et le détecteur ne les voit pas libres (état : ${contention.state||'inconnu'}).`,
        quote:contention.reason?String(contention.reason):null,
        fix:'Arrêtez la session vocale de Jarvis (ou l’application qui tient le microphone), puis actualisez.'});
    }
    return {allowed:blockers.length===0,blockers,warnings};
  }

  /* ------------------------------------------------------------ paramètres */

  /* Une valeur saisie, ramenée au type déclaré. Ne juge PAS les bornes : le
     serveur les applique et sa phrase de refus est ce qui s'affiche alors. Les
     bornes déclarées sont quand même posées sur le champ (`min`/`max`), qui est
     l'aide du navigateur, pas un second validateur. */
  function parameterCoerce(spec,raw){
    const type=spec&&spec.type;
    if(type==='bool')return {ok:true,value:raw===true||raw==='true'||raw==='on'};
    const text=raw===null||raw===undefined?'':String(raw).trim();
    if(text==='')return {ok:true,value:null};
    if(type==='int'){
      if(!/^[+-]?\d+$/.test(text))return {ok:false,error:`${spec.name} attend un entier.`};
      return {ok:true,value:Number.parseInt(text,10)};
    }
    if(type==='float'){
      const value=Number(text.replace(',','.'));
      if(!Number.isFinite(value))return {ok:false,error:`${spec.name} attend un nombre.`};
      return {ok:true,value};
    }
    return {ok:true,value:text};
  }

  /* Le corps de `POST /runs`. Seuls les paramètres que la personne a changés
     partent : un paramètre absent prend sa valeur par défaut déclarée, et
     réémettre la valeur par défaut la transformerait en choix explicite. */
  function runRequest(entry,profileName,raw){
    const specs=(entry&&entry.parameters)||[],parameters={},errors=[];
    for(const spec of specs){
      if(!Object.prototype.hasOwnProperty.call(raw||{},spec.name))continue;
      const coerced=parameterCoerce(spec,raw[spec.name]);
      if(!coerced.ok){errors.push(coerced.error);continue}
      if(coerced.value===null)continue;
      if(coerced.value===spec.default)continue;
      parameters[spec.name]=coerced.value;
    }
    const body={diagnostic_id:entry&&entry.diagnostic_id,profile:profileName,version:entry&&entry.version};
    if(Object.keys(parameters).length)body.parameters=parameters;
    return {body,errors};
  }

  /* --------------------------------------------------- exécution en cours */

  function isTerminal(status){return TERMINAL.includes(String(status||''))}

  /* Où en est une exécution : statut, temps écoulé et étape. Le temps écoulé
     d'une exécution terminée vient des horodatages du dossier (exact) ; celui
     d'une exécution en cours est compté depuis `started_at` avec l'horloge de
     cette page — les deux tournent sur la même machine. */
  function runProgress(view,nowMs,prompt){
    const run=(view&&view.run)||null;
    const outcome=(view&&view.outcome)||null;
    if(!run)return null;
    const started=msOf(run.started_at),created=msOf(run.created_at),finished=msOf(run.finished_at);
    const terminal=isTerminal(run.status);
    let elapsedS=null,shape='écoulées';
    if(started!==null&&finished!==null){elapsedS=Math.max(0,(finished-started)/1000);shape='de durée'}
    else if(started!==null&&isNumber(nowMs))elapsedS=Math.max(0,(nowMs-started)/1000);
    else if(created!==null&&isNumber(nowMs)){elapsedS=Math.max(0,(nowMs-created)/1000);shape='en file'}
    let step;
    if(run.status==='queued')step='en attente d’un worker libre';
    else if(prompt&&prompt.prompt)step=`étape guidée ${prompt.prompt.prompt_id} · ${prompt.prompt.action}`;
    else if(run.status==='running')step='le worker exécute le scénario';
    else step='terminée';
    const key=outcome&&outcome.outcome?String(outcome.outcome):'pending';
    const read=readOutcome(outcome&&outcome.outcome);
    const label=fmtDuration(elapsedS);
    return {run_id:run.run_id,status:run.status,statusLabel:STATUSES[run.status]||run.status,
      outcome:key,outcomeLabel:read.label,tone:terminal?read.tone:'busy',terminal,
      elapsed_s:elapsedS,elapsedLabel:label,shape,
      elapsedText:shape==='en file'?`en file depuis ${label}`:`${label} ${shape}`,step,
      profile:run.profile,guided:run.profile==='hardware:guided'};
  }

  /* -------------------------------------------------------- invite guidée */

  /* Le modèle de vue d'une invite, avec le compte à rebours ramené à
     maintenant. `remaining_s` vient du serveur (compté depuis le `shown_at` du
     worker) ; `sinceMs` est le temps écoulé sur cette page depuis ce sondage,
     pour que la ligne bouge entre deux lectures. Le reste est borné aux deux
     bouts : au-dessus du délai on promettrait du temps que l'exécution
     n'attendra pas, en dessous de zéro on afficherait un défaut. À zéro, rien
     n'est envoyé et rien n'est désactivé : le délai appartient à l'exécution. */
  function promptView(document_,sinceMs){
    const prompt=(document_&&document_.prompt)||null;
    if(!prompt)return {open:false};
    const deadline=isNumber(prompt.deadline_s)&&prompt.deadline_s>0?prompt.deadline_s:0.001;
    const served=isNumber(document_.remaining_s)?document_.remaining_s:deadline;
    const drift=isNumber(sinceMs)?Math.max(0,sinceMs)/1000:0;
    const remaining=Math.min(Math.max(0,served-drift),deadline);
    const action=GUIDED_ACTIONS[prompt.action]||{label:prompt.action,hint:'Confirmez quand vous l’avez fait.'};
    return {open:true,prompt_id:prompt.prompt_id,sequence:document_.sequence,
      action:prompt.action,actionLabel:action.label,hint:action.hint,text:prompt.text,
      phrase:prompt.phrase||null,expects_voice:prompt.expects_voice===true,
      strict_timing:prompt.strict_timing===true,
      deadline_s:prompt.deadline_s,remaining_s:Math.round(remaining*10)/10,
      ratio:Math.round((remaining/deadline)*1000)/1000,
      expired:remaining<=0,
      /* Exactement ce que dit `render_expired` du présentateur en terminal. */
      note:remaining<=0?'Le délai affiché est écoulé : l’exécution décide de cette étape (elle se termine en « non mesurable »). Rien n’a été envoyé — vous pouvez encore répondre tant que l’invite est ouverte.':null};
  }

  /* LE SEUL CHEMIN DU FICHIER VERS UN ACQUITTEMENT.

     `observe` lit le serveur et ne rend qu'un modèle de vue : il n'a aucun
     accès à `post`, donc aucun sondage, aucun re-rendu et aucun minuteur ne
     peut acquitter. `answer` exige les trois à la fois : un événement de
     confiance (un `element.click()` scripté porte `isTrusted:false`), une
     invite réellement ouverte, et une clé jamais déjà répondue. */
  function createPromptGate(options){
    const post=options&&options.post;
    if(typeof post!=='function')throw new TypeError('createPromptGate a besoin de post(path, body)');
    let open=null,sending=false;
    const answered=new Set();
    const keyOf=value=>`${value.run_id}|${value.prompt_id}|${value.sequence}`;
    return {
      /* Lecture pure. Ne poste jamais, quoi qu'elle reçoive et combien de fois. */
      observe(runId,document_,sinceMs){
        const view=promptView(document_,sinceMs);
        open=view.open?{run_id:runId,prompt_id:view.prompt_id,sequence:view.sequence}:null;
        return view;
      },
      openKey(){return open?keyOf(open):null},
      answeredKeys(){return [...answered]},
      busy(){return sending},
      async answer(kind,event){
        if(kind!=='ack'&&kind!=='refuse')return {sent:false,reason:'unknown_answer'};
        if(!event||event.isTrusted!==true)return {sent:false,reason:'not_a_click'};
        if(!open)return {sent:false,reason:'no_prompt'};
        const key=keyOf(open);
        if(answered.has(key))return {sent:false,reason:'already_answered'};
        if(sending)return {sent:false,reason:'busy'};
        answered.add(key);sending=true;
        const target=open;
        try{
          await post(`${ROUTE}/runs/${encodeURIComponent(target.run_id)}/prompt`,
            {prompt_id:target.prompt_id,sequence:target.sequence,refused:kind==='refuse'});
          return {sent:true,refused:kind==='refuse',key};
        }catch(error){
          /* Capturé, argumenté : l'envoi a échoué, donc le worker n'a rien reçu
             et la personne doit pouvoir réessayer. Rejouer le même
             (prompt_id, sequence) réécrit le même fichier d'acquittement, donc
             le réarmement ne peut pas produire deux réponses différentes.
             L'erreur remonte : l'appelant l'affiche et la journalise. */
          answered.delete(key);
          throw error;
        }finally{sending=false}
      },
    };
  }

  /* ------------------------------------------------------------- gabarits */

  function chip(text,tone){
    return `<span class="chip${tone&&tone!=='muted'?' '+tone:''}">${escapeHtml(text)}</span>`;
  }
  /* `quote` est la phrase que le SERVEUR a écrite (en anglais, comme le reste
     de ses codes) : elle est citée, jamais fondue dans la phrase française qui
     l'introduit — c'est la preuve, elle doit se voir comme telle. */
  function noticeHtml(kind,title,detail,hint,quote){
    return `<p class="notice ${escapeHtml(kind)}"><strong>${escapeHtml(title)}</strong>`
      +(detail?`<br>${escapeHtml(detail)}`:'')
      +(quote?`<span class="tlab-quote">«&nbsp;${escapeHtml(quote)}&nbsp;»</span>`:'')
      +(hint?`<span class="hint">${escapeHtml(hint)}</span>`:'')+'</p>';
  }
  function gateHtml(gate){
    const items=[...gate.blockers.map(item=>({item,kind:'bad'})),...gate.warnings.map(item=>({item,kind:''}))];
    if(!items.length)return '';
    return items.map(({item,kind})=>noticeHtml(kind,item.label,item.detail,item.fix,item.quote)).join('');
  }

  /* Une carte de profil : ce qu'il exige, ce qu'il coûte, et ce qui l'empêche
     de tourner ici — AVANT le bouton de lancement, pas après l'échec. */
  function profileCardHtml(profile,status,options){
    const settings=options||{};
    const gate=profileGate(profile,status);
    const name=profile.profile;
    const known=PROFILES[name]||{label:name,means:''};
    const cost=profile.cost||{};
    const requires=(profile.requires||[]);
    const id=`tlabProfile_${String(name).replace(/[^a-z0-9]+/gi,'_')}`;
    const requiresHtml=requires.length
      ? requires.map(item=>`<li>${escapeHtml(CAPABILITIES[item]||item)} <code>${escapeHtml(item)}</code></li>`).join('')
      : '<li>aucune ressource : ni appareil, ni fournisseur, ni personne</li>';
    return `<label class="choice tlab-profile${settings.selected?' selected':''}${gate.allowed?'':' tlab-blocked'}" for="${id}">
      <input type="radio" id="${id}" name="tlabProfile" value="${escapeHtml(name)}"${settings.selected?' checked':''}${gate.allowed?'':' disabled'}>
      <div>
        <div class="title"><strong>${escapeHtml(known.label)}</strong>
          ${gate.allowed?'<span class="tag ok">exécutable ici</span>':'<span class="tag bad">non exécutable ici</span>'}
          ${requires.includes('human_presence')?'<span class="tag warn">vous êtes acteur</span>':''}</div>
        <div class="hint">${escapeHtml(known.means)}</div>
        <div class="tlab-req">
          <div><span class="tlab-k">Exige</span><ul>${requiresHtml}</ul></div>
          <div><span class="tlab-k">Coûte</span><ul>
            <li>au plus ${escapeHtml(fmtDuration(cost.max_duration_s))} d’exécution</li>
            <li>${escapeHtml(costPhrase(cost.max_cost_usd))}</li>
            <li>implémentation <code>${escapeHtml(profile.implementation||'—')}</code></li>
          </ul></div>
        </div>
        ${gateHtml(gate)}
      </div>
    </label>`;
  }

  function parameterFieldHtml(spec){
    const id=`tlabParam_${String(spec.name).replace(/[^a-z0-9]+/gi,'_')}`;
    const label=`<label for="${id}">${escapeHtml(spec.name)}`
      +`<span class="hint">${escapeHtml(spec.description||'')} `
      +`Par défaut : <code>${escapeHtml(String(spec.default))}</code>.</span></label>`;
    let control;
    if(spec.type==='bool'){
      control=`<input type="checkbox" id="${id}" data-param="${escapeHtml(spec.name)}"${spec.default?' checked':''}>`;
      return `<div class="field inline tlab-param">${control}${label}</div>`;
    }
    if(spec.type==='enum'){
      control=`<select id="${id}" data-param="${escapeHtml(spec.name)}">`
        +(spec.choices||[]).map(choice=>`<option value="${escapeHtml(choice)}"${choice===spec.default?' selected':''}>${escapeHtml(choice)}</option>`).join('')
        +'</select>';
    }else if(spec.type==='int'||spec.type==='float'){
      const bounds=(spec.minimum===null||spec.minimum===undefined?'':` min="${escapeHtml(spec.minimum)}"`)
        +(spec.maximum===null||spec.maximum===undefined?'':` max="${escapeHtml(spec.maximum)}"`)
        +(spec.type==='float'?' step="any"':' step="1"');
      control=`<input type="number" id="${id}" data-param="${escapeHtml(spec.name)}" value="${escapeHtml(spec.default)}"${bounds}>`;
    }else{
      control=`<input type="text" id="${id}" data-param="${escapeHtml(spec.name)}" value="${escapeHtml(spec.default)}"`
        +(spec.max_length?` maxlength="${escapeHtml(spec.max_length)}"`:'')+'>';
    }
    return `<div class="field tlab-param">${label}${control}</div>`;
  }

  /* ------------------------------------------------------------- verdict */

  /* Le verdict vient de `outcome` (RunOutcomeSummary), jamais d'une relecture
     du statut ou des assertions. Quand rien n'a pu être mesuré, la raison est
     dite en clair : le code de panne stable, la phrase que le worker a écrite,
     et les assertions bloquantes restées sans mesure. */
  function outcomeHtml(view){
    const run=(view&&view.run)||{},outcome=(view&&view.outcome)||{};
    const key=String(outcome.outcome||'pending');
    const read=readOutcome(outcome.outcome);
    const failure=run.failure||null;
    const parts=[`<div class="tlab-verdict" data-tone="${escapeHtml(read.tone)}">
      <strong>${escapeHtml(read.label)}</strong>
      <span>${escapeHtml(read.means)}</span>
      <div class="tlab-vmeta">${chip(`statut ${STATUSES[run.status]||run.status||'?'}`,'')}${chip(`résultat ${key}`,read.tone)}
        ${isNumber(run.score)?chip(`score ${fmtNumber(run.score)}`,''):''}
        ${outcome.measured===false?chip('aucune métrique enregistrée','warn'):''}</div>
    </div>`];
    if(failure){
      parts.push(noticeHtml(read.tone==='bad'?'bad':'','Pourquoi',
        failure.detail?null:'aucun détail n’a été enregistré.',
        `Code de panne : ${failure.code}`,failure.detail||null));
    }
    const failed=outcome.failed_assertions||[],missing=outcome.missing_assertions||[];
    if(failed.length)parts.push(noticeHtml('bad','Assertions bloquantes en défaut',failed.join(', '),null));
    if(missing.length)parts.push(noticeHtml('','Assertions bloquantes non mesurées',missing.join(', '),
      'Une assertion que personne n’a pu évaluer n’est pas une réussite : l’exécution se lit « non mesurable ».'));
    return parts.join('');
  }

  /* Les métriques déclarées, avec leur unité et leur sens, et celles que
     l'exécution n'a pas mesurées — nommées, pas omises. */
  function metricsHtml(view){
    const run=(view&&view.run)||{},declaration=(view&&view.declaration)||null;
    const measured=run.metrics||{};
    const declared=(declaration&&declaration.metrics)||[];
    const names=declared.map(item=>item.name);
    const extra=Object.keys(measured).filter(name=>!names.includes(name)).sort();
    if(!declared.length&&!extra.length)return '<p class="empty">Aucune métrique déclarée ni mesurée.</p>';
    const row=(name,unit,direction,description)=>{
      const has=Object.prototype.hasOwnProperty.call(measured,name);
      return `<tr><th scope="row" data-label="Métrique">${escapeHtml(name)}${description?`<span class="tlab-sub">${escapeHtml(description)}</span>`:''}</th>
        <td data-label="Valeur" class="tlab-num">${has?escapeHtml(fmtValue(measured[name],unit)):'<span class="tlab-none">non mesurée</span>'}</td>
        <td data-label="Sens">${escapeHtml(DIRECTIONS[direction]||direction||'—')}</td></tr>`;
    };
    const rows=declared.map(item=>row(item.name,item.unit,item.direction,item.description))
      .concat(extra.map(name=>row(name,null,null,'mesurée hors déclaration')));
    return `<div class="catalog-table-wrap"><table class="catalog-table"><caption>Métriques</caption><thead><tr>
      <th scope="col">Métrique</th><th scope="col">Valeur</th><th scope="col">Sens</th></tr></thead>
      <tbody>${rows.join('')}</tbody></table></div>`;
  }

  /* Chaque assertion avec sa métrique, son seuil et ce qui a été observé. */
  function assertionsHtml(view){
    const run=(view&&view.run)||{},declaration=(view&&view.declaration)||null;
    const results=new Map((run.assertion_results||[]).map(item=>[item.assertion_id,item]));
    const declared=(declaration&&declaration.assertions)||[];
    const units=new Map((((declaration||{}).metrics)||[]).map(item=>[item.name,item.unit]));
    const seen=new Set();
    const rows=[];
    for(const spec of declared){
      seen.add(spec.assertion_id);
      const result=results.get(spec.assertion_id)||null;
      const outcome=result?(ASSERTION_OUTCOMES[result.outcome]||{label:result.outcome,tone:''}):{label:'Non évaluée',tone:'warn'};
      const unit=units.get(spec.metric);
      rows.push(`<tr><th scope="row" data-label="Assertion">${escapeHtml(spec.assertion_id)}
          ${spec.blocking?'<span class="chip">bloquante</span>':'<span class="chip">indicative</span>'}
          ${spec.description?`<span class="tlab-sub">${escapeHtml(spec.description)}</span>`:''}</th>
        <td data-label="Attendu"><code>${escapeHtml(spec.metric)} ${escapeHtml(COMPARATORS[spec.comparator]||spec.comparator)} ${escapeHtml(fmtValue(spec.threshold,unit))}</code></td>
        <td data-label="Observé" class="tlab-num">${result&&result.observed!==null&&result.observed!==undefined?escapeHtml(fmtValue(result.observed,unit)):'<span class="tlab-none">rien</span>'}</td>
        <td data-label="Verdict">${chip(outcome.label,outcome.tone)}</td></tr>`);
    }
    for(const result of (run.assertion_results||[])){
      if(seen.has(result.assertion_id))continue;
      const outcome=ASSERTION_OUTCOMES[result.outcome]||{label:result.outcome,tone:''};
      rows.push(`<tr><th scope="row" data-label="Assertion">${escapeHtml(result.assertion_id)}
          <span class="tlab-sub">hors déclaration courante</span></th>
        <td data-label="Attendu">—</td>
        <td data-label="Observé" class="tlab-num">${result.observed===null||result.observed===undefined?'<span class="tlab-none">rien</span>':escapeHtml(fmtValue(result.observed,null))}</td>
        <td data-label="Verdict">${chip(outcome.label,outcome.tone)}</td></tr>`);
    }
    if(!rows.length)return '<p class="empty">Ce diagnostic ne déclare aucune assertion.</p>';
    return `<div class="catalog-table-wrap"><table class="catalog-table"><caption>Assertions</caption><thead><tr>
      <th scope="col">Assertion</th><th scope="col">Attendu</th><th scope="col">Observé</th><th scope="col">Verdict</th>
      </tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
  }

  function artifactUrl(runId,path){
    return `${ROUTE}/runs/${encodeURIComponent(runId)}/artifacts/`
      +String(path).split('/').map(encodeURIComponent).join('/');
  }
  function artifactsHtml(view){
    const run=(view&&view.run)||{};
    const artifacts=(view&&view.artifacts)||run.artifacts||[];
    if(!artifacts.length)return '<p class="empty">Cette exécution n’a conservé aucun artefact.</p>';
    return `<ul class="tlab-artifacts">${artifacts.map(item=>
      `<li><a href="${escapeHtml(artifactUrl(run.run_id,item.path))}" download>${escapeHtml(item.path)}</a>
        <span class="tlab-sub">${escapeHtml(ARTIFACTS[item.kind]||item.kind)} · ${escapeHtml(fmtBytes(item.size_bytes))} · ${escapeHtml(item.media_type)}</span></li>`
    ).join('')}</ul>`;
  }

  /* Toute la preuve d'une exécution : verdict, assertions, métriques,
     artefacts, et ce qui a été exécuté (paramètres, code, empreintes). */
  function evidenceHtml(view){
    const run=(view&&view.run)||null;
    if(!run)return '<p class="empty">Aucune exécution sélectionnée.</p>';
    const declaration=(view&&view.declaration)||null;
    const started=run.started_at?fmtClock(run.started_at):'—';
    const parameters=Object.keys(run.parameters||{});
    const overrides=Object.keys(run.overrides||{});
    return `<div class="tlab-evidence">
      <header class="tlab-ehead"><h3>${escapeHtml(shortRunId(run.run_id))}</h3>
        <span class="tlab-sub">${escapeHtml(run.diagnostic_id)} v${escapeHtml(run.diagnostic_version)} · profil ${escapeHtml(run.profile)} · démarrée à ${escapeHtml(started)}</span></header>
      ${declaration?'':noticeHtml('','Déclaration absente du catalogue',
        'cette version du diagnostic n’est plus publiée : les seuils et les unités ne peuvent pas être affichés.',null)}
      ${outcomeHtml(view)}
      <section class="tlab-sect"><h4>Assertions</h4>${assertionsHtml(view)}</section>
      <section class="tlab-sect"><h4>Métriques</h4>${metricsHtml(view)}</section>
      <section class="tlab-sect"><h4>Artefacts</h4>${artifactsHtml(view)}</section>
      <details class="rd tlab-inputs"><summary>Ce qui a été exécuté</summary>
        <dl class="kv">
          <dt>Identifiant</dt><dd><code>${escapeHtml(run.run_id)}</code></dd>
          <dt>Code</dt><dd><code>${escapeHtml((run.code&&run.code.git_revision)||'—')}</code>${run.code&&run.code.dirty?' <span class="tag warn">dépôt modifié</span>':''}</dd>
          <dt>Empreinte déclaration</dt><dd><code>${escapeHtml(run.diagnostic_fingerprint||'—')}</code></dd>
          <dt>Empreinte réglages</dt><dd><code>${escapeHtml(run.config_fingerprint||'—')}</code></dd>
          <dt>Paramètres</dt><dd>${parameters.length?escapeHtml(parameters.map(name=>`${name}=${run.parameters[name]}`).join(' · ')):'ceux de la déclaration'}</dd>
          <dt>Surcharges</dt><dd>${overrides.length?escapeHtml(overrides.map(name=>`${name}=${run.overrides[name]}`).join(' · ')):'aucune'}</dd>
        </dl>
      </details>
    </div>`;
  }

  /* ---------------------------------------------------------- comparaison */

  /* Le document `RunComparison` tel quel : écarts par métrique avec leur sens,
     changements d'assertion, et ce qui n'est PAS comparable, avec la raison.
     Le même gabarit rend `points[].comparison_to_baseline` d'un résumé de
     balayage, qui est le même document. */
  function comparisonHtml(comparison){
    if(!comparison)return '<p class="empty">Aucune comparaison.</p>';
    const head=`<div class="tlab-verdict" data-tone="${comparison.comparable?'muted':'warn'}">
      <strong>${comparison.comparable?'Comparables':'Partiellement comparables'}</strong>
      <span>${escapeHtml(shortRunId(comparison.baseline_run_id))} (${escapeHtml(readOutcome(comparison.baseline_outcome).label)})
        → ${escapeHtml(shortRunId(comparison.candidate_run_id))} (${escapeHtml(readOutcome(comparison.candidate_outcome).label)})</span>
      ${Array.isArray(comparison.score_delta)&&comparison.score_delta.length===3
        ? `<div class="tlab-vmeta">${chip(`score ${fmtNumber(comparison.score_delta[0])} → ${fmtNumber(comparison.score_delta[1])} (${comparison.score_delta[2]>=0?'+':''}${fmtNumber(comparison.score_delta[2])})`,'')}</div>`:''}
    </div>`;
    const incomparable=(comparison.incomparable||[]).length
      ? (comparison.incomparable||[]).map(item=>noticeHtml('','Non comparable : '+item.subject,
          INCOMPARABLE[item.reason]||item.reason,null,item.detail||null)).join('')
      : '';
    const metrics=(comparison.metrics||[]).length
      ? `<div class="catalog-table-wrap"><table class="catalog-table"><caption>Écarts par métrique</caption><thead><tr>
          <th scope="col">Métrique</th><th scope="col">Référence</th><th scope="col">Candidate</th>
          <th scope="col">Écart</th><th scope="col">Sens</th></tr></thead><tbody>${
        (comparison.metrics||[]).map(item=>{
          const change=CHANGES[item.change]||{label:item.change,tone:'',sign:''};
          const delta=item.delta===null||item.delta===undefined?'—'
            :`${item.delta>=0?'+':''}${fmtNumber(item.delta)}${UNITS[item.unit]?' '+UNITS[item.unit]:''}`
              +(isNumber(item.percent_change)?` (${item.percent_change>=0?'+':''}${fmtNumber(item.percent_change)} %)`:'');
          return `<tr><th scope="row" data-label="Métrique">${escapeHtml(item.metric)}
              <span class="tlab-sub">${escapeHtml(DIRECTIONS[item.direction]||'sens non déclaré')}</span></th>
            <td data-label="Référence" class="tlab-num">${escapeHtml(fmtValue(item.baseline,item.unit))}</td>
            <td data-label="Candidate" class="tlab-num">${escapeHtml(fmtValue(item.candidate,item.unit))}</td>
            <td data-label="Écart" class="tlab-num">${escapeHtml(delta)}</td>
            <td data-label="Sens">${chip(`${change.sign} ${change.label}`,change.tone)}</td></tr>`;
        }).join('')}</tbody></table></div>`
      : '<p class="empty">Aucune métrique commune aux deux exécutions.</p>';
    const assertions=(comparison.assertions||[]).length
      ? `<div class="catalog-table-wrap"><table class="catalog-table"><caption>Changements d’assertion</caption><thead><tr>
          <th scope="col">Assertion</th><th scope="col">Référence</th><th scope="col">Candidate</th>
          <th scope="col">Changement</th></tr></thead><tbody>${
        (comparison.assertions||[]).map(item=>{
          const change=ASSERTION_CHANGES[item.change]||{label:item.change,tone:''};
          const read=value=>value?((ASSERTION_OUTCOMES[value]||{}).label||value):'—';
          return `<tr><th scope="row" data-label="Assertion">${escapeHtml(item.assertion_id)}
              ${item.blocking?'<span class="chip">bloquante</span>':''}</th>
            <td data-label="Référence">${escapeHtml(read(item.baseline))}</td>
            <td data-label="Candidate">${escapeHtml(read(item.candidate))}</td>
            <td data-label="Changement">${chip(change.label,change.tone)}</td></tr>`;
        }).join('')}</tbody></table></div>`
      : '<p class="empty">Aucune assertion des deux côtés.</p>';
    const differences=(comparison.differences||[]).length
      ? `<details class="rd"><summary>Ce qui différait à l’entrée (${(comparison.differences||[]).length})</summary><dl class="kv">${
        (comparison.differences||[]).map(item=>`<dt>${escapeHtml(item.field)}</dt><dd>${escapeHtml(JSON.stringify(item.baseline))} → ${escapeHtml(JSON.stringify(item.candidate))}</dd>`).join('')
        }</dl></details>`
      : '';
    return head+incomparable
      +`<section class="tlab-sect"><h4>Métriques</h4>${metrics}</section>`
      +`<section class="tlab-sect"><h4>Assertions</h4>${assertions}</section>`
      +differences;
  }

  /* --------------------------------------------------------------- statut */

  /* L'état du laboratoire lui-même : ce que ce processus a le droit de faire,
     si le microphone est libre, ce qui tourne, ce qui est stocké. */
  function statusHtml(status){
    if(!status)return '<span class="tlab-sub">état du Test Lab indisponible</span>';
    const config=status.config||{},grant=config.grant||{};
    const capabilities=(grant.capabilities||[]);
    const contention=status.contention||{};
    const storage=status.storage||{};
    const active=(status.active_runs||[]).length+(status.pending_runs||[]).length;
    const chips=[
      chip(capabilities.length?`accordé : ${capabilities.join(', ')}`:'accordé : rien (profil virtual seulement)',
        capabilities.length?'on':''),
      chip(`budget ${fmtCost(grant.max_cost_usd)}`,''),
      chip(contention.available===true?'appareils audio libres'
        :contention.available===false?'appareils audio occupés':'appareils audio : état inconnu',
        contention.available===true?'on':'warn'),
      chip(`${storage.runs||0} exécutions · ${fmtBytes(storage.total_bytes)}`,''),
      active?chip(`${active} en cours`,'on'):'',
    ];
    return chips.join('')
      +(config.grant_refusal?`<span class="tlab-sub">${escapeHtml(config.grant_refusal)}</span>`:'')
      +(contention.available===false&&contention.reason?`<span class="tlab-sub">${escapeHtml(contention.reason)}</span>`:'');
  }

  /* Une ligne de la liste des exécutions. */
  function runRowHtml(view,options){
    const settings=options||{};
    const run=view.run||{},outcome=view.outcome||{};
    const read=readOutcome(outcome.outcome);
    return `<button type="button" class="tlab-run-row${settings.selected?' is-selected':''}" data-run="${escapeHtml(run.run_id)}">
      <span class="dot ${escapeHtml(read.tone==='muted'?'':read.tone)}"></span>
      <span class="tlab-rmain"><span class="tlab-rid">${escapeHtml(shortRunId(run.run_id))}</span>
        <span class="tlab-sub">${escapeHtml(run.profile)} · ${escapeHtml(fmtClock(run.created_at))}${isNumber(run.score)?' · score '+escapeHtml(fmtNumber(run.score)):''}</span></span>
      <span class="tlab-rout">${escapeHtml(read.label)}</span></button>`;
  }

  return {ROUTE,OUTCOMES,STATUSES,TERMINAL,PROFILES,CAPABILITIES,OPT_INS,DEVICE_CAPABILITIES,UNITS,DIRECTIONS,
    COMPARATORS,ASSERTION_OUTCOMES,CHANGES,ASSERTION_CHANGES,INCOMPARABLE,ARTIFACTS,GUIDED_ACTIONS,
    UNKNOWN_OUTCOME,readOutcome,
    escapeHtml,isNumber,fmtNumber,fmtValue,fmtDuration,fmtUsd,fmtCost,costPhrase,fmtBytes,fmtClock,shortRunId,msOf,
    catalogueRows,profileGate,parameterCoerce,runRequest,isTerminal,runProgress,promptView,createPromptGate,
    chip,noticeHtml,gateHtml,profileCardHtml,parameterFieldHtml,outcomeHtml,metricsHtml,assertionsHtml,
    artifactUrl,artifactsHtml,evidenceHtml,comparisonHtml,statusHtml,runRowHtml};
})();

/* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
if(typeof module!=='undefined'&&module.exports)module.exports=JarvisTestLabCore;

/* --------------------------------------------------------------------------
   Bloc navigateur : vue plein écran, sondage d'une exécution, invite guidée.
   Les tests node ne l'exécutent pas.
   -------------------------------------------------------------------------- */
(function installJarvisTestLab(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const T=JarvisTestLabCore;
  const root=document.getElementById('testlab');
  if(!root)return;
  const q=s=>root.querySelector(s);
  const el={
    open:document.getElementById('openTestLab'),close:q('#tlabClose'),refresh:q('#tlabRefresh'),
    env:q('#tlabEnv'),notice:q('#tlabNotice'),filter:q('#tlabFilter'),list:q('#tlabList'),
    live:q('#tlabLive'),run:q('#tlabRun'),prompt:q('#tlabPrompt'),head:q('#tlabHead'),
    tabs:q('#tlabTabs'),pane:q('#tlabPane'),announce:q('#tlabAnnounce'),
  };
  const POLL_WAIT_S=10,PROMPT_EVERY_MS=1000,TICK_MS=500,RETRY_MS=4000,RUN_LIMIT=25;

  const S={open:false,inerted:[],returnFocus:null,tick:null,generation:0,
    status:null,statusError:null,diagnostics:[],catalogError:null,filter:'',
    selected:null,entry:null,entryError:null,profile:null,params:{},
    tab:'prepare',submitting:false,prepareError:null,
    runs:[],runsError:null,runsLoading:false,detail:null,detailError:null,
    baseline:'',candidate:'',comparison:null,compareError:null,comparing:false,
    followed:null,view:null,viewError:null,prompt:null,promptAt:0,promptKey:null,
    promptError:null,promptSent:null,cancelling:false};

  /* Le client HTTP de la page (`api`) : il vérifie `response.ok` et relève le
     refus du serveur — sa phrase EST le message affiché, jamais un générique. */
  function request(path,options){return api(path,options)}
  function post(path,body){
    return request(path,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body||{})});
  }
  function describe(error){
    return (error&&error.message)?String(error.message):'échec sans message';
  }
  /* Toute défaillance vue par cet écran : à l'écran (bandeau + pastille), et
     journalisée — côté serveur chaque refus de `/api/testlab` écrit déjà
     `testlab.http.failed` dans le journal local, et la console garde la trace
     de ce que le navigateur seul a vu (réseau coupé, page arrêtée). */
  function failed(what,error){
    const message=describe(error);
    if(typeof console!=='undefined'&&console.warn)console.warn('testlab.ui.failed',what,error);
    if(typeof toast==='function')toast({title:what,sub:message,kind:'bad'});
    return message;
  }
  function notice(text,tone){
    if(!text){el.notice.hidden=true;el.notice.textContent='';return}
    el.notice.hidden=false;el.notice.className='tl-notice'+(tone==='bad'?' tlab-notice-bad':'');
    el.notice.textContent=text;
  }
  function announce(text){el.announce.textContent=text}

  const gate=T.createPromptGate({post});

  /* ------------------------------------------------------------ ouverture */
  function openView(){
    if(S.open)return;
    S.open=true;S.returnFocus=document.activeElement;
    root.hidden=false;
    S.inerted=[...document.body.children].filter(n=>n!==root&&!n.inert&&n.tagName!=='SCRIPT');
    for(const node of S.inerted)node.inert=true;
    if(el.open){el.open.classList.add('active');el.open.setAttribute('aria-expanded','true')}
    S.tick=setInterval(tick,TICK_MS);
    notice(null);
    loadStatus();loadCatalogue();
    /* Une exécution lancée puis quittée continue côté serveur : on la reprend
       plutôt que de laisser croire qu'elle s'est arrêtée avec la vue. */
    if(S.followed&&!(S.view&&S.view.run&&T.isTerminal(S.view.run.status)))follow(S.followed);
    requestAnimationFrame(()=>el.filter.focus({preventScroll:true}));
  }
  function closeView(){
    if(!S.open)return;
    S.open=false;S.generation++;
    clearInterval(S.tick);S.tick=null;
    for(const node of S.inerted)node.inert=false;
    S.inerted=[];
    root.hidden=true;
    if(el.open){el.open.classList.remove('active');el.open.setAttribute('aria-expanded','false')}
    const back=S.returnFocus;S.returnFocus=null;
    if(back&&back.isConnected&&typeof back.focus==='function')back.focus({preventScroll:true});
  }

  /* --------------------------------------------------------------- lecture */
  async function loadStatus(){
    try{
      S.status=await request(`${T.ROUTE}/status`);S.statusError=null;
    }catch(error){
      S.status=null;S.statusError=failed('Test Lab : état indisponible',error);
    }finally{
      /* L'état arrive souvent APRÈS la déclaration (les deux lectures partent
         ensemble) : le profil retenu est rechoisi avec l'autorisation réelle,
         sinon l'écran proposerait de lancer un profil qui sera refusé. */
      pickProfile();renderEnv();renderPane();
    }
  }
  /* Le premier profil réellement exécutable ici, à défaut le premier déclaré. */
  function pickProfile(){
    const profiles=(S.entry&&S.entry.profiles)||[];
    if(!profiles.length){S.profile=null;return}
    const current=profiles.find(item=>item.profile===S.profile);
    if(current&&T.profileGate(current,S.status).allowed)return;
    const runnable=profiles.find(item=>T.profileGate(item,S.status).allowed);
    S.profile=(runnable||current||profiles[0]).profile;
  }
  async function loadCatalogue(){
    el.list.innerHTML='<p class="tlab-loading">Lecture du catalogue…</p>';
    try{
      const page=await request(`${T.ROUTE}/diagnostics`);
      S.diagnostics=page.diagnostics||[];S.catalogError=null;
      if(!S.selected&&S.diagnostics.length)select(S.diagnostics[0].diagnostic_id);
    }catch(error){
      S.diagnostics=[];S.catalogError=failed('Test Lab : catalogue illisible',error);
    }finally{renderList()}
  }
  async function loadEntry(diagnosticId){
    S.entry=null;S.entryError=null;S.profile=null;S.params={};renderHead();renderPane();
    try{
      const answer=await request(`${T.ROUTE}/diagnostics/${encodeURIComponent(diagnosticId)}`);
      if(S.selected!==diagnosticId)return;
      S.entry=answer.diagnostic;
      pickProfile();
    }catch(error){
      S.entryError=failed('Test Lab : diagnostic illisible',error);
    }finally{renderHead();renderPane()}
  }
  async function loadRuns(){
    if(!S.selected)return;
    S.runsLoading=true;renderPane();
    try{
      const page=await request(`${T.ROUTE}/runs?diagnostic_id=${encodeURIComponent(S.selected)}&limit=${RUN_LIMIT}`);
      S.runs=page.runs||[];S.runsError=null;
    }catch(error){
      S.runs=[];S.runsError=failed('Test Lab : exécutions illisibles',error);
    }finally{S.runsLoading=false;renderPane()}
  }

  function select(diagnosticId){
    if(S.selected===diagnosticId)return;
    S.selected=diagnosticId;S.runs=[];S.detail=null;S.comparison=null;
    S.baseline='';S.candidate='';S.compareError=null;S.prepareError=null;
    renderList();loadEntry(diagnosticId);
    if(S.tab!=='prepare')loadRuns();
  }

  /* ------------------------------------------------------------ lancement */
  async function submit(){
    if(S.submitting||!S.entry||!S.profile)return;
    const raw={};
    for(const field of el.pane.querySelectorAll('[data-param]')){
      raw[field.dataset.param]=field.type==='checkbox'?field.checked:field.value;
    }
    const {body,errors}=T.runRequest(S.entry,S.profile,raw);
    if(errors.length){S.prepareError=errors.join(' ');renderPane();return}
    S.submitting=true;S.prepareError=null;renderPane();
    try{
      const answer=await post(`${T.ROUTE}/runs`,body);
      announce(`Exécution ${answer.run_id} lancée.`);
      follow(answer.run_id);
      S.tab='runs';renderHead();loadRuns();
    }catch(error){
      S.prepareError=failed('Test Lab : lancement refusé',error);
    }finally{S.submitting=false;renderPane()}
  }

  async function cancelRun(){
    if(!S.followed||S.cancelling)return;
    S.cancelling=true;renderRun();
    try{
      await post(`${T.ROUTE}/runs/${encodeURIComponent(S.followed)}/cancel`,{reason:'demandé depuis le Control Center'});
      announce('Arrêt demandé.');notice(null);
    }catch(error){
      notice(failed('Test Lab : arrêt impossible',error),'bad');
    }finally{S.cancelling=false;renderRun()}
  }

  /* Suivre une exécution : un long-poll pour le dossier, et — pour un profil
     guidé seulement — une lecture régulière de l'invite ouverte. Les deux
     boucles s'arrêtent dès que l'exécution est terminale, que la vue se ferme
     ou qu'une autre exécution est suivie. */
  function follow(runId){
    S.followed=runId;S.view=null;S.viewError=null;S.prompt=null;S.promptKey=null;
    S.promptError=null;S.promptSent=null;
    const generation=++S.generation;
    el.live.hidden=false;renderRun();
    followRecord(runId,generation);
  }
  function stillFollowing(runId,generation){
    return S.open&&S.followed===runId&&S.generation===generation;
  }
  async function followRecord(runId,generation){
    while(stillFollowing(runId,generation)){
      try{
        const view=await request(`${T.ROUTE}/runs/${encodeURIComponent(runId)}?wait_s=${POLL_WAIT_S}`);
        if(!stillFollowing(runId,generation))return;
        S.view=view;S.viewError=null;
        if(view.run&&view.run.profile==='hardware:guided'&&!T.isTerminal(view.run.status))followPrompt(runId,generation);
        renderRun();
        if(view.run&&T.isTerminal(view.run.status)){
          announce(`Exécution ${runId} terminée : ${T.readOutcome(view.outcome&&view.outcome.outcome).label}.`);
          S.detail=view;S.prompt=null;renderPrompt();renderPane();loadRuns();
          return;
        }
      }catch(error){
        if(!stillFollowing(runId,generation))return;
        S.viewError=failed('Test Lab : suivi interrompu',error);
        renderRun();
        await sleep(RETRY_MS);
      }
    }
  }
  let promptLoop=null;
  async function followPrompt(runId,generation){
    if(promptLoop===`${runId}|${generation}`)return;
    promptLoop=`${runId}|${generation}`;
    while(stillFollowing(runId,generation)&&S.view&&S.view.run&&!T.isTerminal(S.view.run.status)){
      try{
        const answer=await request(`${T.ROUTE}/runs/${encodeURIComponent(runId)}/prompt`);
        if(!stillFollowing(runId,generation))break;
        S.prompt=answer;S.promptAt=Date.now();S.promptError=null;
        /* Lecture seule : `observe` ne peut pas acquitter, quel que soit le
           nombre de fois où la même invite revient. */
        gate.observe(runId,answer,0);
        renderPrompt();
      }catch(error){
        if(!stillFollowing(runId,generation))break;
        S.promptError=failed('Test Lab : invite illisible',error);
        renderPrompt();
      }
      await sleep(PROMPT_EVERY_MS);
    }
    promptLoop=null;
  }
  function sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms))}

  /* --------------------------------------------------------------- rendu */
  function renderEnv(){
    el.env.innerHTML=S.statusError
      ? `<span class="tlab-sub tlab-bad">${T.escapeHtml(S.statusError)}</span>`
      : T.statusHtml(S.status);
  }
  function renderList(){
    if(S.catalogError){el.list.innerHTML=T.noticeHtml('bad','Catalogue illisible',S.catalogError,null);return}
    const rows=T.catalogueRows(S.diagnostics,S.filter);
    if(!rows.length){
      el.list.innerHTML=S.diagnostics.length
        ? '<p class="empty">Aucun diagnostic ne correspond.</p>'
        : '<p class="empty">Aucun diagnostic officiel publié.</p>';
      return;
    }
    el.list.innerHTML=rows.map(row=>`<button type="button" role="option" class="tlab-item${row.diagnostic_id===S.selected?' is-selected':''}"
      aria-selected="${row.diagnostic_id===S.selected?'true':'false'}" data-diagnostic="${T.escapeHtml(row.diagnostic_id)}">
      <span class="tlab-iname">${T.escapeHtml(row.title||row.diagnostic_id)}</span>
      <span class="tlab-sub">${T.escapeHtml(row.diagnostic_id)} · v${T.escapeHtml(row.version)} · ${T.escapeHtml(row.domain||'')}</span>
      <span class="tlab-iprof">${row.profiles.map(name=>T.chip(name,'')).join('')}</span></button>`).join('');
  }
  function renderHead(){
    if(!S.selected){el.head.innerHTML='';el.tabs.hidden=true;return}
    el.tabs.hidden=false;
    const entry=S.entry;
    el.head.innerHTML=entry
      ? `<h2>${T.escapeHtml(entry.title||entry.diagnostic_id)}</h2>
         <p class="hint">${T.escapeHtml(entry.description||'')}</p>
         <p class="tlab-sub"><code>${T.escapeHtml(entry.diagnostic_id)}</code> · version ${T.escapeHtml(entry.version)} · domaine ${T.escapeHtml(entry.domain||'—')}</p>`
      : S.entryError
        ? T.noticeHtml('bad','Diagnostic illisible',S.entryError,null)
        : '<p class="tlab-loading">Lecture de la déclaration…</p>';
    for(const button of el.tabs.querySelectorAll('button')){
      const on=button.dataset.tab===S.tab;
      button.setAttribute('aria-selected',on?'true':'false');
      if(on)el.pane.setAttribute('aria-labelledby',button.id);
    }
  }
  function renderRun(){
    if(!S.followed){el.live.hidden=true;el.run.innerHTML='';return}
    el.live.hidden=false;
    const progress=T.runProgress(S.view,Date.now(),S.prompt);
    if(!progress){
      el.run.innerHTML=`<div class="tlab-progress" data-tone="busy"><strong>Exécution ${T.escapeHtml(T.shortRunId(S.followed))}</strong>
        <span id="tlabElapsed">mise en file…</span></div>`;
      return;
    }
    el.run.innerHTML=`<div class="tlab-progress" data-tone="${T.escapeHtml(progress.tone)}">
      <span class="tlab-led" aria-hidden="true"></span>
      <div class="tlab-pmain"><strong>${T.escapeHtml(progress.statusLabel)} · ${T.escapeHtml(T.shortRunId(progress.run_id))}</strong>
        <span class="tlab-sub">${T.escapeHtml(progress.step)}</span></div>
      <span class="tlab-elapsed" id="tlabElapsed">${T.escapeHtml(progress.elapsedText)}</span>
      ${progress.terminal
        ? '<button type="button" class="action small" data-act="forget">Fermer le suivi</button>'
        : `<button type="button" class="action small danger" data-act="cancel"${S.cancelling?' disabled':''}>${S.cancelling?'Arrêt demandé…':'Arrêter'}</button>`}
    </div>${S.viewError?T.noticeHtml('bad','Suivi interrompu',S.viewError,'Nouvelle tentative dans quelques secondes ; l’exécution, elle, continue.'):''}`;
  }
  /* L'invite n'est reconstruite qu'au CHANGEMENT d'étape : entre deux étapes
     seuls le compte à rebours et la barre bougent, pour qu'un focus clavier
     posé sur « J'ai fait l'étape » survive au rafraîchissement. */
  function renderPrompt(){
    const view=T.promptView(S.prompt,Date.now()-S.promptAt);
    if(!view.open){
      el.prompt.hidden=true;el.prompt.innerHTML='';S.promptKey=null;
      return;
    }
    const key=`${S.followed}|${view.prompt_id}|${view.sequence}`;
    el.prompt.hidden=false;
    if(S.promptKey!==key){
      S.promptKey=key;S.promptSent=null;
      el.prompt.innerHTML=`<div class="tlab-step">
        <div class="tlab-shead"><span class="chip warn">étape guidée</span>
          <strong>${T.escapeHtml(view.actionLabel)}</strong>
          <code>${T.escapeHtml(view.prompt_id)}</code>
          ${view.strict_timing?'<span class="tag warn">chronométrée : répondre tard annule la mesure</span>':''}</div>
        <p class="tlab-stext">${T.escapeHtml(view.text)}</p>
        ${view.phrase?`<p class="tlab-phrase">«&nbsp;${T.escapeHtml(view.phrase)}&nbsp;»</p>`:''}
        <p class="hint">${T.escapeHtml(view.hint)}</p>
        <div class="tlab-count"><div class="tlab-gauge"><span id="tlabGauge" style="transform:scaleX(${view.ratio})"></span></div>
          <span id="tlabRemaining">${T.escapeHtml(T.fmtDuration(view.remaining_s))} sur ${T.escapeHtml(T.fmtDuration(view.deadline_s))}</span></div>
        <p class="tlab-snote" id="tlabStepNote"></p>
        <div class="row"><button type="button" class="action primary" data-answer="ack">J’ai fait l’étape</button>
          <button type="button" class="action" data-answer="refuse">Je refuse cette étape</button></div>
      </div>`;
      announce(`Étape guidée : ${view.text}`);
    }
    const gauge=el.prompt.querySelector('#tlabGauge'),remaining=el.prompt.querySelector('#tlabRemaining'),
      note=el.prompt.querySelector('#tlabStepNote');
    if(gauge)gauge.style.transform=`scaleX(${view.ratio})`;
    if(remaining)remaining.textContent=`${T.fmtDuration(view.remaining_s)} sur ${T.fmtDuration(view.deadline_s)}`;
    if(note)note.textContent=S.promptError?S.promptError:(S.promptSent||view.note||'');
  }
  function renderPane(){
    if(!S.selected){el.pane.innerHTML='<p class="empty">Choisissez un diagnostic à gauche.</p>';return}
    if(S.tab==='prepare')el.pane.innerHTML=prepareHtml();
    else if(S.tab==='runs')el.pane.innerHTML=runsHtml();
    else el.pane.innerHTML=compareHtml();
  }
  function prepareHtml(){
    if(!S.entry)return S.entryError?'':'<p class="tlab-loading">Lecture de la déclaration…</p>';
    const profiles=S.entry.profiles||[];
    const chosen=profiles.find(item=>item.profile===S.profile)||null;
    const gate_=chosen?T.profileGate(chosen,S.status):{allowed:false,blockers:[],warnings:[]};
    const parameters=S.entry.parameters||[];
    return `${S.status?'':T.noticeHtml('bad','État du Test Lab illisible',
        'l’autorisation de ce processus et l’état des appareils n’ont pas pu être lus : « exécutable ici » ne peut pas être jugé avant le lancement.',
        S.statusError||'Utilisez « Actualiser ».')}
      <section class="tlab-sect"><h4>Profils : ce que chacun exige et coûte</h4>
        <p class="hint">Le superviseur reste l’autorité : il re-sonde les appareils et applique l’autorisation au moment de réserver. Ce qui est marqué « non exécutable ici » est un refus qu’il prononcera avant d’exécuter quoi que ce soit.</p>
        <div class="choices">${profiles.map(item=>T.profileCardHtml(item,S.status,{selected:item.profile===S.profile})).join('')}</div>
      </section>
      ${parameters.length?`<section class="tlab-sect"><h4>Paramètres</h4>
        <p class="hint">Un champ laissé à sa valeur par défaut n’est pas envoyé : la déclaration décide.</p>
        ${parameters.map(T.parameterFieldHtml).join('')}</section>`:''}
      <section class="tlab-sect"><h4>Ce qui sera mesuré</h4>
        ${T.metricsHtml({run:{metrics:{}},declaration:S.entry})}
        ${T.assertionsHtml({run:{assertion_results:[]},declaration:S.entry})}</section>
      ${S.prepareError?T.noticeHtml('bad','Lancement refusé',S.prepareError,null):''}
      <div class="tlab-launch">
        <button type="button" class="action primary" data-act="run"${gate_.allowed&&!S.submitting?'':' disabled'}>
          ${S.submitting?'Mise en file…':`Lancer sur ${T.escapeHtml(S.profile||'—')}`}</button>
        <span class="hint">${gate_.allowed
          ? `Au plus ${T.escapeHtml(T.fmtDuration((chosen.cost||{}).max_duration_s))} d’exécution, ${T.escapeHtml(T.costPhrase((chosen.cost||{}).max_cost_usd))}.`
          : 'Ce profil ne peut pas s’exécuter ici : la raison est dans sa carte ci-dessus.'}</span>
      </div>`;
  }
  function runsHtml(){
    const list=S.runsError?T.noticeHtml('bad','Exécutions illisibles',S.runsError,null)
      :S.runsLoading?'<p class="tlab-loading">Lecture des exécutions…</p>'
      :!S.runs.length?'<p class="empty">Aucune exécution enregistrée pour ce diagnostic.</p>'
      :`<div class="tlab-runs">${S.runs.map(view=>T.runRowHtml(view,
          {selected:S.detail&&S.detail.run&&S.detail.run.run_id===view.run.run_id})).join('')}</div>`;
    const detail=S.detailError?T.noticeHtml('bad','Exécution illisible',S.detailError,null)
      :S.detail?T.evidenceHtml(S.detail)
      :'<p class="empty">Choisissez une exécution pour voir sa preuve.</p>';
    return `<div class="tlab-two"><section class="tlab-sect"><h4>Exécutions</h4>${list}</section>
      <section class="tlab-sect">${detail}</section></div>`;
  }
  function compareHtml(){
    const options=(current)=>['<option value="">—</option>'].concat(S.runs.map(view=>{
      const run=view.run,read=T.readOutcome((view.outcome||{}).outcome);
      return `<option value="${T.escapeHtml(run.run_id)}"${run.run_id===current?' selected':''}>`
        +`${T.escapeHtml(T.shortRunId(run.run_id))} · ${T.escapeHtml(run.profile)} · ${T.escapeHtml(T.fmtClock(run.created_at))} · ${T.escapeHtml(read.label||'')}</option>`;
    })).join('');
    return `<section class="tlab-sect"><h4>Comparer deux exécutions</h4>
      <p class="hint">Les écarts, les changements d’assertion et ce qui n’est pas comparable viennent du serveur (<code>compare_runs</code>) : cet écran ne calcule aucun verdict.</p>
      <div class="tlab-compare-form">
        <label class="field"><span>Référence</span><select data-compare="baseline">${options(S.baseline)}</select></label>
        <label class="field"><span>Candidate</span><select data-compare="candidate">${options(S.candidate)}</select></label>
        <button type="button" class="action primary" data-act="compare"${S.baseline&&S.candidate&&!S.comparing?'':' disabled'}>${S.comparing?'Comparaison…':'Comparer'}</button>
      </div>
      ${S.compareError?T.noticeHtml('bad','Comparaison impossible',S.compareError,null):''}
      ${S.comparison?T.comparisonHtml(S.comparison):'<p class="empty">Choisissez deux exécutions du même diagnostic.</p>'}
    </section>`;
  }

  /* Battement d'une demi-seconde : le temps écoulé et le compte à rebours
     doivent BOUGER, sinon une exécution lente est indiscernable d'un blocage. */
  function tick(){
    if(!S.open)return;
    if(S.followed&&S.view){
      const progress=T.runProgress(S.view,Date.now(),S.prompt);
      const slot=el.run.querySelector('#tlabElapsed');
      if(progress&&slot)slot.textContent=progress.elapsedText;
    }
    if(S.prompt&&S.prompt.prompt)renderPrompt();
  }

  /* ----------------------------------------------------------- événements */
  if(el.open)el.open.addEventListener('click',()=>{root.hidden?openView():closeView()});
  el.close.addEventListener('click',closeView);
  el.refresh.addEventListener('click',()=>{loadStatus();loadCatalogue();if(S.selected)loadEntry(S.selected)});
  el.filter.addEventListener('input',()=>{S.filter=el.filter.value;renderList()});
  el.list.addEventListener('click',event=>{
    const button=event.target.closest('[data-diagnostic]');
    if(button)select(button.dataset.diagnostic);
  });
  el.tabs.addEventListener('click',event=>{
    const button=event.target.closest('[data-tab]');
    if(!button)return;
    S.tab=button.dataset.tab;
    renderHead();renderPane();
    if((S.tab==='runs'||S.tab==='compare')&&!S.runs.length&&!S.runsLoading)loadRuns();
  });
  el.pane.addEventListener('click',async event=>{
    const act=event.target.closest('[data-act]');
    if(act&&act.dataset.act==='run'){submit();return}
    if(act&&act.dataset.act==='compare'){compare();return}
    const row=event.target.closest('[data-run]');
    if(row)openRun(row.dataset.run);
  });
  el.pane.addEventListener('change',event=>{
    const profile=event.target.closest('input[name="tlabProfile"]');
    if(profile){
      /* Changer de profil change ce que coûte l'exécution et le bouton qui la
         lance : le volet est reconstruit, puis le focus rendu au bouton radio
         reconstruit — sans quoi le choix au clavier se perdrait à chaque
         flèche. Recherche par valeur : `hardware:guided` n'est pas un sélecteur. */
      S.profile=profile.value;renderPane();
      const again=[...el.pane.querySelectorAll('input[name="tlabProfile"]')]
        .find(item=>item.value===S.profile);
      if(again)again.focus();
      return;
    }
    const side=event.target.closest('[data-compare]');
    if(side){
      /* Les deux listes ne reconstruisent RIEN : seul le bouton change d'état,
         donc le focus reste là où la personne l'a mis. */
      S[side.dataset.compare]=side.value;
      const go=el.pane.querySelector('[data-act="compare"]');
      if(go)go.disabled=!(S.baseline&&S.candidate)||S.comparing;
    }
  });
  /* LE SEUL ENDROIT DU FICHIER QUI PEUT ACQUITTER. Le portillon exige en plus
     `event.isTrusted`, donc même un `click()` scripté ne passe pas. */
  el.prompt.addEventListener('click',async event=>{
    const button=event.target.closest('[data-answer]');
    if(!button)return;
    try{
      const result=await gate.answer(button.dataset.answer,event);
      if(result.sent){
        S.promptSent=result.refused
          ? 'Refus envoyé. L’exécution l’enregistre et cesse de mesurer cette affirmation.'
          : 'Réponse envoyée.';
        announce(S.promptSent);
      }else if(result.reason==='already_answered'){
        S.promptSent='Cette étape a déjà reçu votre réponse.';
      }
      S.promptError=null;
    }catch(error){
      S.promptError=failed('Test Lab : réponse non transmise',error);
    }finally{renderPrompt()}
  });
  el.run.addEventListener('click',event=>{
    const act=event.target.closest('[data-act]');
    if(!act)return;
    if(act.dataset.act==='cancel')cancelRun();
    if(act.dataset.act==='forget'){S.followed=null;S.view=null;S.prompt=null;renderRun();renderPrompt()}
  });
  root.addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.stopPropagation();closeView();return}
    if(event.key!=='Tab')return;
    const focusable=[...root.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea,[tabindex]')]
      .filter(node=>node.offsetParent!==null&&node.tabIndex>=0);
    if(!focusable.length)return;
    const first=focusable[0],last=focusable[focusable.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
  });

  async function openRun(runId){
    S.detail=null;S.detailError=null;renderPane();
    try{
      S.detail=await request(`${T.ROUTE}/runs/${encodeURIComponent(runId)}`);
    }catch(error){
      S.detailError=failed('Test Lab : exécution illisible',error);
    }finally{renderPane()}
  }
  async function compare(){
    if(!S.baseline||!S.candidate||S.comparing)return;
    S.comparing=true;S.compareError=null;S.comparison=null;renderPane();
    try{
      S.comparison=await request(`${T.ROUTE}/compare?baseline=${encodeURIComponent(S.baseline)}&candidate=${encodeURIComponent(S.candidate)}`);
    }catch(error){
      S.compareError=failed('Test Lab : comparaison impossible',error);
    }finally{S.comparing=false;renderPane()}
  }

  /* La poignée de la page. `gate` N'EST PAS exposé, et c'est le point :
     `isTrusted` ne veut dire quelque chose que sur un vrai événement, donc un
     `JarvisTestLab.gate.answer('ack',{isTrusted:true})` tapé dans la console —
     ou par n'importe quel script tournant dans la page — acquitterait une étape
     au nom d'une personne qui n'a rien fait. Seul le portillon, fermé dans sa
     portée, peut poster ; ce qui sort ici n'en est que la lecture. */
  window.JarvisTestLab={open:openView,close:closeView,state:S,
    gateView:()=>({openKey:gate.openKey(),answeredKeys:gate.answeredKeys(),busy:gate.busy()})};
})();
