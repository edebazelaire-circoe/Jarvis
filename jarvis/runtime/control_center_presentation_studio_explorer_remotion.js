/* « Remotion Studio » dans Variantes (handoff jarvis-remotion-native-studio-playback-fix, Slice 11 ; contrat `docs/presentation-studio.md` ›
   *Remotion Studio from Variants (Level 3, Slice 11)*, § 1, § 6 #22, PX-1, PX-2).

   Module DOM exposé en `window.JarvisVariantsRemotionStudio` dans la page et en `module.exports` pour node. Variantes lui prête la scène à l'écran
   (présentation, variante, scène, son pin EXACT `{id, version}`), sa boîte de dialogue, sa pause et son journal ; il ne garde AUCUN état de
   présentation. Le processus natif `remotion studio`, son état et ses codes sont ceux de Core (`docs/remotion-studio.md`), lus par le relais
   `/api/local-capabilities/remotion/studio*` avec le client, la confirmation et les phrases de la carte du dialogue MCP
   (`JarvisRemotionStudioCore`, `control_center_remotion_studio.js`) : une porte de plus, pas un second client.

   Règles tenues ici :
   - **Deux espaces voisins, une identité.** Le bouton « Remotion Studio » de la ligne de scène ouvre LA scène à l'écran, à son pin exact (jamais
     « la dernière version »), dans l'onglet de Remotion Studio, l'interface native intacte : rien de Remotion Studio n'est dessiné ici, aucune
     ligne de temps n'est recopiée (SLICE 11 étape 4). Variantes reste ouvert, tel quel : variante, scène, image et arbre ne bougent pas ; la
     vidéo est mise en pause (une seule lecture à la fois). Le retour est l'onglet de Jarvis : au retour (`focus`, `visibilitychange`), l'état
     de Remotion Studio est relu et dit.
   - **Une seule autorité de source.** Ce que Remotion Studio modifie n'atteint la variante QUE par « Publier dans la variante… » (Slice 12) :
     une confirmation qui nomme la base et les fichiers, puis Core publie une NOUVELLE version par la porte d'édition de source (compilation,
     conflit si la scène a changé, version précédente intacte) ; « Revenir à … » republie l'ancienne (`restore_version`). Avant, les
     fichiers modifiés sont comptés et dits « pas encore publiés », jamais « enregistrés ». Un pin différent (autre scène, autre version de
     la même source) est dit, jamais corrigé en silence ; changer de scène avec des fichiers non publiés le dit dans la confirmation (ils
     sont mis de côté, `discard_unpublished`).
   - **Rien sans clic ni confirmation.** La confirmation « hors du bac à sable » (risque, version, provenance de CETTE version) précède tout
     lancement ; « Annuler » ne lance rien. Le cerveau n'a pas de chemin ici (aucune commande, aucun outil).
   - **Ce qui attend se voit, un échec se dit.** Démarrage : compteur de secondes et échéance (2 min) ; échec : la phrase du code, le code, le
     journal de Remotion Studio, « Réessayer » ; environnement absent ou pas prêt : le bouton dit pourquoi au clic. Chaque échec est
     journalisé (`[studio-explorer] remotion_studio_*`, `obsClientLog` au niveau `warn` / `error`).
   - **Permission du navigateur.** Un onglet ne s'ouvre seul que tant que le clic de confirmation est récent (activation utilisateur) ; après
     un démarrage long, le navigateur le bloquerait : la ligne d'état offre alors « Ouvrir l'onglet Remotion Studio » (un vrai lien, un clic). */
(function(root){
  'use strict';
  const Core=root.JarvisStudioExplorerCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_core.js'):null);
  const {cleanLine,HOST_ID}=Core;
  /* Le noyau de la carte : chargé après Variantes dans la page (lu à l'usage), requis par node. */
  const Studio=()=>root.JarvisRemotionStudioCore||(typeof require==='function'?require('./control_center_remotion_studio.js'):null);
  const TAB_NAME='jarvis-remotion-studio';
  const POLL_FAST_MS=2000;
  const POLL_READY_MS=15000;
  /* Core's view of Remotion Studio unreadable (Core stopped, network): re-read every 5 s so the true state comes back as soon as Core does. */
  const POLL_LOST_MS=5000;
  /* Sans `navigator.userActivation` : un clic de moins de 4 s est encore une permission d'ouvrir un onglet (Chrome en accorde 5). */
  const ACTIVATION_MS=4000;
  const DIAG_LINES=8;
  /* Publication (Slice 12) : Core répond en 135 s au plus (compilation réelle comprise). */
  const PUBLISH_LIMIT_S=150;
  const RESTORE_DEADLINE_MS=90000;

  const CSS=`
#${HOST_ID} .jvx-stage-note>[data-act="remotion_studio"]{margin-left:auto;min-height:30px;padding:0 12px;font-size:12px;flex:none}
#${HOST_ID} .jvx-stage-note>[data-act="remotion_studio"]+[data-act="present"]{margin-left:0}
#${HOST_ID} .jvx-stage-note>[data-act="remotion_studio"][aria-disabled="true"]{opacity:.55;cursor:default}
#${HOST_ID} .jvx-stage-note>[data-act="remotion_studio"][data-state="loading"]{opacity:.75;cursor:progress}
#${HOST_ID} .jvx-stage-note>[data-act="remotion_studio"][data-state="here"]{border-color:var(--jvx-ok);color:var(--jvx-ok)}
#${HOST_ID} .jvx-stage-note>[data-act="remotion_studio"][data-state="here"]::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
#${HOST_ID} .jvx-rms{flex:1 1 100%;display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;min-width:0;margin:0;font-size:12.5px;color:var(--jvx-mute)}
#${HOST_ID} .jvx-rms[hidden]{display:none}
#${HOST_ID} .jvx-rms[data-tone="ok"] .jvx-rms-text{color:var(--jvx-ok)}
#${HOST_ID} .jvx-rms[data-tone="warn"] .jvx-rms-text{color:var(--jvx-warn)}
#${HOST_ID} .jvx-rms[data-tone="danger"] .jvx-rms-text{color:var(--jvx-danger)}
#${HOST_ID} .jvx-rms-text{min-width:0;flex:1 1 18em}
#${HOST_ID} .jvx-rms[data-spin="true"] .jvx-rms-text::before{content:"";display:inline-block;width:8px;height:8px;margin-right:7px;border-radius:50%;background:var(--jvx-accent);vertical-align:1px}
@media (prefers-reduced-motion:no-preference){#${HOST_ID} .jvx-rms[data-spin="true"] .jvx-rms-text::before{animation:jvxPulse 1.1s ease-in-out infinite}}
#${HOST_ID} .jvx-rms-link{color:var(--jvx-accent);font-weight:600;text-underline-offset:3px;white-space:nowrap}
#${HOST_ID} .jvx-rms .jvx-btn{min-height:28px;padding:0 10px;font-size:12px}
#${HOST_ID} .jvx-rms-log{flex:1 1 100%;min-width:0}
#${HOST_ID} .jvx-rms-files{margin:4px 0 0;padding:6px 8px 6px 22px;max-height:12em;overflow:auto;border:1px solid var(--jvx-line-strong);border-radius:6px;font:12px/1.4 ui-monospace,Consolas,monospace}
#${HOST_ID} .jvx-rms-log pre{margin:4px 0 0;max-height:7.5em;overflow:auto;white-space:pre-wrap;font:11.5px/1.35 ui-monospace,Consolas,monospace;color:var(--jvx-mute)}
#${HOST_ID} .jvx-theater:fullscreen .jvx-stage-note>[data-act="remotion_studio"],#${HOST_ID} .jvx-theater:fullscreen .jvx-rms{display:none}
#${HOST_ID} .jvx-rms-master{flex:1 1 100%;display:flex;flex-wrap:wrap;align-items:center;gap:4px 12px;min-width:0;min-height:26px}
#${HOST_ID} .jvx-rms-master[hidden]{display:none}
#${HOST_ID} .jvx-rms-master-text{min-width:0;flex:0 1 auto}
#${HOST_ID} .jvx-rms[data-master-tone="warn"] .jvx-rms-master-text{color:var(--jvx-warn)}
/* The secondary door stays quieter than the primary « Remotion Studio » (§ 13): the line's muted ink (--jvx-mute, about 8:1 on the stage), normal
   weight, no underline at rest; the accent and the underline come on hover or keyboard focus (the focus ring is the host's :focus-visible). */
#${HOST_ID} .jvx-rms .jvx-rms-scene{min-height:26px;padding:0 4px;border-color:transparent;background:none;color:var(--jvx-mute);font-weight:400;text-decoration:none;text-underline-offset:3px;white-space:normal;text-align:left}
#${HOST_ID} .jvx-rms .jvx-rms-scene[aria-disabled="true"]{opacity:.55;cursor:default}
/* The open confirmations (scene and whole video): the heading and the action row stay put, the body between them scrolls (12 scenes at
   800×600 must never push « Annuler » out of view). */
#${HOST_ID} .jvx-dialog[data-kind="remotion_studio"]{display:flex;flex-direction:column;overflow:hidden}
#${HOST_ID} .jvx-dialog[data-kind="remotion_studio"]>h2,#${HOST_ID} .jvx-dialog[data-kind="remotion_studio"]>.jvx-dialog-actions{flex:none}
#${HOST_ID} .jvx-dialog[data-kind="remotion_studio"]>.jvx-dialog-actions{padding-top:12px;border-top:1px solid var(--jvx-line)}
#${HOST_ID} .jvx-confirm-body{flex:0 1 auto;min-height:0;overflow:auto;overscroll-behavior:contain;display:grid;gap:14px;align-content:start;padding-right:4px}
#${HOST_ID} .jvx-confirm-body>ul{margin:0;padding-left:20px;display:grid;gap:4px}
#${HOST_ID} .jvx-rms .jvx-rms-scene:hover:not([aria-disabled="true"]),#${HOST_ID} .jvx-rms .jvx-rms-scene:focus-visible{border-color:transparent;background:none;color:var(--jvx-accent);text-decoration:underline}
`;

  /* Remotion ou HTML : la règle de `jarvis/domain/prefab.py` › `is_remotion_manifest` (v2 toujours ; v3 quand elle porte `source`), lue
     dans le manifeste brut que rend `GET /api/prefabs/{id}/{version}`. */
  function isRemotionManifest(manifest){
    if(!manifest||typeof manifest!=='object')return false;
    const v=manifest.schema_version;
    return v===2||(v===3&&Object.prototype.hasOwnProperty.call(manifest,'source'));
  }
  const RUNNABLE=new Set(['ready','running']);
  const plural=(n,one,many)=>`${n} ${n>1?many:one}`;

  /* Le modèle (pur) de la porte : le bouton et la ligne d'état, depuis la scène à l'écran et la vue de Core. `i` :
     {scene:{id,title,number,of,prefab}|null, scenes:[{id,title,prefab}], detail:{state,remotion}|null, studio, capability, readError,
      busy:{label,at}|null, actionError:{code,text}|null, run, needsClick, explain, lastTarget:'master'|'scene'|'auto' (ce que « Réessayer » relance), now,
      publishing:{at,label}|null, published:{published,previous,status,sceneId}|null, publishError:{code,text,diagnostics}|null}. */
  /* L'espace de travail de Remotion Studio (Slice 12) face à la scène à l'écran : 'here' (sa base est le pin de la scène : publiable ici),
     'other' (une autre version ou une autre scène), 'none' (aucune base connue). Vrai que Remotion Studio soit ouvert ou arrêté. */
  function workspaceOf(st,mine){
    const wc=st&&st.work_copy||{};
    const files=Array.isArray(wc.modified_files)?wc.modified_files:[];
    const count=typeof wc.unpublished==='number'?wc.unpublished:files.length;
    const base=wc.base||(st&&st.pin)||null;
    /* Slice 08 (master-project-studio-export): a workspace of the whole video (a master target) has no scene base: 'master', never publishable. */
    const master=!!(st&&st.target&&st.target.kind==='variant_master');
    const relation=master?'master':!base||!mine?'none':base.prefab_id===mine.id&&Number(base.version)===Number(mine.version)?'here':'other';
    /* `digest` : l'empreinte de CETTE liste, renvoyée avec `publish` (Core refuse si l'espace a changé depuis : QA Slice 12, I1).
       `setAside` : ce que le dernier lancement a mis de côté parce que ce n'était pas la forme de l'espace (B1). */
    const setAside=Array.isArray(wc.set_aside)?wc.set_aside:[];
    return {count,files,base,relation,master,saved:wc.edits_saved||0,digest:typeof wc.digest==='string'?wc.digest:null,setAside};
  }

  /* -------------------------------------------------------------- la vidéo entière (master-project-studio-export Slice 08)
     `docs/remotion-master-project.md` § 9, § 11, § 13. La préparation est lue UNE fois par révision de la variante sur la route vivante de Core
     (`GET .../variants/{id}/master-project`) : la page ne calcule aucune compatibilité, elle dit la vue. Prête : « Remotion Studio » ouvre la
     vidéo entière (cible maître, confirmation qui nomme le nombre de scènes) et la scène seule reste offerte en second (« Cette scène seule
     dans Remotion Studio »). Pas prête : le bouton garde la porte de la scène et la ligne dit la phrase du § 3. Illisible : la porte de la
     scène, et la ligne le dit. */
  const SCENE_DOOR_LABEL='Cette scène seule dans Remotion Studio';
  const fmtSeconds=seconds=>`${String(Math.round(seconds*10)/10).replace('.',',')} s`;
  function masterFacts(plan){
    const c=plan&&plan.composition||{};
    const n=Array.isArray(plan&&plan.scenes)?plan.scenes.length:0;
    const seconds=c.fps>0&&Number.isInteger(c.duration_in_frames)?fmtSeconds(c.duration_in_frames/c.fps):null;
    return {count:n,scenes:plural(n,'scène','scènes'),seconds,spec:c.width&&c.height?`${c.width}×${c.height}, ${c.fps} i/s`:null};
  }
  /* « Atelier », variante 2 : the identity the state line and the confirmation name (§ 13). */
  function projectName(i){
    const title=cleanLine(i.presentationTitle,60);
    return `${title?`« ${title} »`:'cette présentation'}${i.variantNumber?`, variante ${i.variantNumber}`:''}`;
  }
  /* The master line of the door (pure): `{tone, text, scene}` (`scene`: the secondary door is offered) or null. */
  function masterLine(i){
    const m=i.master||null;
    if(!m||!i.scene)return null;
    const plan=m.plan;
    /* Slice 09 rework: the line is on screen while the whole video is read, at the height the scene door will take, so nothing under the
       pointer moves when the answer comes (a click aimed at « Remotion Studio » once landed on « Cette scène seule… », which took its place). */
    if(!plan&&m.state==='loading')return {tone:'',scene:false,loading:true,text:'Vidéo entière : lecture en cours…'};
    if(plan&&plan.status==='ready'){
      const f=masterFacts(plan);
      return {tone:'',scene:true,text:`Vidéo entière : ${projectName(i)}, ${f.scenes}${f.seconds?` (${f.seconds})`:''}.`};
    }
    if(plan&&plan.status==='incompatible'){
      /* One sentence per state (QA Slice 08 polish): the § 3 sentence says why, the tail says what the button does instead. */
      return {tone:'',scene:false,text:`${Studio().masterReasonSentence(plan.reason,plan.detail)} « Remotion Studio » ouvre donc la scène à l’écran.`};
    }
    if(m.state==='error')return {tone:'warn',scene:false,
      text:`La vidéo entière n’a pas pu être lue (${m.error&&m.error.code||'erreur'}) : « Remotion Studio » ouvre la scène à l’écran.`};
    return null;
  }
  /* How Remotion Studio stands against the whole video on screen: 'here' (this variant, this key), 'stale' (this variant, an older key),
     'other' (another variant's whole video), 'none'. Core's `stale` (live key) and the page's own read both count. */
  function masterRelationOf(st,plan,i){
    const t=st&&st.target;
    if(!plan||plan.status!=='ready'||!st||st.status!=='ready'||!t||t.kind!=='variant_master')return 'none';
    if(t.presentation_id!==i.presentationId||t.variant_id!==i.variantId)return 'other';
    return t.project_key===plan.project_key&&t.stale!==true?'here':'stale';
  }

  /* A failed read of Core's view (anything but « no Remotion Studio here »): the last view is no longer confirmed (Slice 09 polish, R1). Core's
     stop closes Remotion Studio, so the page never keeps saying « ouvert » on a view it can no longer read; the rail's « Rail injoignable :
     l'état affiché n'est plus confirmé. » is the model. */
  const UNREACHABLE=new Set(['core_unreachable','core_timeout','network','timeout']);
  function lostRead(readError){return !!readError&&readError.code!=='remotion_studio_unavailable'}
  function lostSentence(readError){
    const code=readError&&readError.code||'network';
    return UNREACHABLE.has(code)||/^http_5\d\d$/.test(code)?'Core injoignable : l’état de Remotion Studio n’est plus confirmé.'
      :`Remotion Studio illisible (${cleanLine(code,60)}) : l’état affiché n’est plus confirmé.`;
  }

  function doorModel(i){
    const C=Studio();
    const lost=lostRead(i.readError);
    /* Unconfirmed: the last view says nothing (no « ouvert », no link, no publish), the line says why, the click re-reads first. */
    const scene=i.scene||null,st=lost?null:i.studio||null,cap=i.capability||null,mine=scene&&scene.prefab;
    let blocked=null;
    if(i.run)blocked='Une présentation est en cours : Remotion Studio s’ouvre à son arrêt (« Arrêter »).';
    else if(!scene)blocked='Aucune scène à l’écran : choisissez une variante et une scène.';
    else if(!mine)blocked='Cette scène ne désigne aucune source : rien à ouvrir dans Remotion Studio.';
    else if(i.detail&&i.detail.state==='ready'&&!i.detail.remotion)blocked='Cette scène n’est pas une scène Remotion : Remotion Studio n’ouvre que les scènes Remotion.';
    else if(i.readError&&i.readError.code==='remotion_studio_unavailable')blocked='Ce Jarvis n’a pas de Remotion Studio (Core sans environnement Remotion).';
    else if(lost)blocked=`${lostSentence(i.readError)} Réessayez dans un instant.`;
    else if(cap&&cap.status&&!RUNNABLE.has(cap.status)){
      const label=(C.CAPABILITY[cap.status]||{label:String(cap.status)}).label;
      blocked=`L’environnement Remotion n’est pas prêt (${label.toLowerCase()}) : installez-le ou réparez-le (carte « Présentations · moteur », onglet « Plugins externes » du dialogue MCP), puis réessayez.`;
    }
    const pin=st&&st.pin||null;
    const relation=!st||st.status!=='ready'||!pin||!mine?'none':pin.prefab_id===mine.id?(Number(pin.version)===Number(mine.version)?'here':'version'):'other';
    /* Slice 08: a ready whole video makes « Remotion Studio » the door of the VARIANT (master target); the scene stays the secondary door. */
    const plan=i.master&&i.master.plan;
    const masterMode=!!(scene&&plan&&plan.status==='ready');
    const masterRelation=masterMode?masterRelationOf(st,plan,i):'none';
    const master=masterLine(i);
    const button={label:'Remotion Studio',state:relation==='here'?'here':'idle',blocked,ariaLabel:'Remotion Studio',
      title:blocked||'Ouvrir la scène à l’écran dans Remotion Studio (un onglet à part, après confirmation)'};
    /* Slice 09 rework: the whole video's readiness not known yet, the button never silently means « this scene »: it says it is reading, and a
       click waits for the answer before choosing (whole video if ready, the scene otherwise). */
    const masterUnknown=!!(scene&&i.master&&i.master.state==='loading'&&!plan);
    if(masterUnknown&&!blocked){
      button.state='loading';button.ariaLabel='Remotion Studio, lecture de la vidéo entière';
      button.title='Lecture de la vidéo entière en cours : un clic ouvre la vidéo entière si elle est prête, sinon la scène à l’écran (après confirmation)';
    }
    /* The tab is opened `noopener` (security): a browser cannot bring back a tab opened that way, so a click here opens ANOTHER tab; the words
       say so (Slice 11 QA polish, decided by agent 0: keep `noopener`). */
    if(masterMode){
      const f=masterFacts(plan);
      button.state=masterRelation==='here'?'here':'idle';
      button.ariaLabel=masterRelation==='here'?'Remotion Studio, ouvert sur la vidéo entière':'Remotion Studio, vidéo entière';
      button.title=blocked||(masterRelation==='here'?'Ouvrir un autre onglet Remotion Studio sur la vidéo entière (celui déjà ouvert reste où il est)'
        :`Ouvrir la vidéo entière (${f.scenes}) dans Remotion Studio (un onglet à part, après confirmation)`);
    }else if(relation==='here'){button.ariaLabel='Remotion Studio, ouvert sur cette scène';button.title='Ouvrir un autre onglet Remotion Studio sur cette scène (celui déjà ouvert reste où il est)'}
    const sceneDoor=masterMode?{label:SCENE_DOOR_LABEL,blocked,title:blocked||(relation==='here'
      ?'Ouvrir un autre onglet Remotion Studio sur cette scène seule (celui déjà ouvert reste où il est)'
      :'Ouvrir seulement la scène à l’écran dans Remotion Studio, à sa version exacte : pour la modifier et la publier dans la variante (après confirmation)')}:null;
    const done=out=>Object.assign(out,{master,masterMode,masterRelation,sceneDoor});
    /* « Réessayer » retries the target that failed (Slice 09 rework): a whole video no longer ready has nothing to retry (its line says why). */
    const retryable=!(i.lastTarget==='master'&&!masterMode);
    let status=null;
    const elapsed=since=>C.fmtDuration(Math.max(0,since));
    const ws=workspaceOf(st,mine);
    const publish={offered:false,count:ws.count,files:ws.files,base:ws.base,relation:ws.relation};
    if(i.publishing){
      button.state='busy';
      status={tone:'',spin:true,text:`${i.publishing.label} ${elapsed((i.now-i.publishing.at)/1000)} (${Math.round(PUBLISH_LIMIT_S/60*10)/10} min au plus).`};
      return done({button,status,relation,publish});
    }
    /* A refused or finished publication of THIS scene is said first; the files still unpublished (a retouch after a failed build, new
       edits after a publication) are said with it, and « Publier dans la variante… » stays offered. */
    const here=scene&&((i.publishError&&i.publishError.sceneId===scene.id)||(i.published&&i.published.sceneId===scene.id));
    if(here){
      const work=workspaceText(ws,i.scenes,blocked);
      publish.offered=!!(work&&work.offered);
      if(i.publishError&&i.publishError.sceneId===scene.id){
        const e=i.publishError;
        status={tone:'danger',text:`Publication refusée : ${e.text} (${e.code})`,diagnostics:e.diagnostics||[],publish:publish.offered};
      }else{
        const p=i.published,prev=p.previous;
        /* Variants re-reads the variant after a publication (`ctx.reload`): the new version is on screen, nothing to wait for. A first publication
           forks the scene's own source id, so its « v1 » and the base's « v1 » are two different versions: then they are not numbered. */
        const sameSource=prev&&prev.prefab_id===p.published.prefab_id;
        const before=prev?(sameSource?`la v${prev.version}`:'la version d’avant'):'';
        const done=p.status==='already_published'?`Déjà publié : la scène utilise déjà cette version (v${p.published.version}).`
          :p.restored?`Revenu au contenu d’avant : publié comme nouvelle version (v${p.published.version}).`
          :`Publié dans la variante : nouvelle version de la scène (v${p.published.version})${prev?` ; ${before} reste disponible`:''}.`;
        status={tone:work?'warn':'ok',text:work?`${done} ${work.text}`:done,publish:publish.offered,
          revert:prev&&!p.restored&&p.status!=='already_published'?{label:`Revenir à ${before}`,target:prev}:null};
      }
    }
    if(status){/* intentional: said above; the usual lines below are for a scene without a publication outcome */}
    else if(i.busy){
      button.state='busy';
      status={tone:'',spin:true,text:`${i.busy.label} ${elapsed((i.now-i.busy.at)/1000)} (${C.START_LIMIT_S/60} min au plus).`};
    }else if(i.actionError){
      status={tone:'danger',text:`Remotion Studio : ${i.actionError.text} (${i.actionError.code})`,retry:retryable};
    }else if(lost){
      status={tone:'warn',text:lostSentence(i.readError)};
    }else if(st&&st.status==='starting'){
      button.state='busy';
      status={tone:'',spin:true,text:`Remotion Studio démarre… ${elapsed(st.started_at?i.now/1000-st.started_at:0)} (${C.START_LIMIT_S/60} min au plus).`};
    }else if(st&&st.status==='stopping'){
      status={tone:'',spin:true,text:'Remotion Studio s’arrête…'};
    }else if(st&&st.status==='failed'){
      const code=st.last_error_code||'remotion_studio_failed';
      status={tone:'danger',text:`Remotion Studio est en échec : ${C.errorText(code)||cleanLine(st.last_error_detail,160)||'raison inconnue'} (${code})`,
        retry:!blocked&&retryable,diagnostics:(st.diagnostics||[]).slice(-DIAG_LINES)};
    }else if(masterRelation!=='none'){
      const f=masterFacts(plan);
      let tone='ok',link=null,refresh=false;const parts=[];
      if(masterRelation==='here'){
        parts.push(i.needsClick?'Remotion Studio est prêt sur la vidéo entière. Le navigateur n’ouvre un onglet qu’après un clic :'
          :`Remotion Studio est ouvert sur la vidéo entière (${f.scenes}), dans un autre onglet.`);
        link={url:st.url,label:i.needsClick||!(st.viewers>0)?'Ouvrir l’onglet Remotion Studio':'Ouvrir un autre onglet Remotion Studio'};
      }else if(masterRelation==='stale'){
        tone='warn';refresh=!blocked;
        parts.push(`La vidéo a changé depuis son ouverture dans Remotion Studio (maintenant ${f.scenes}) : « Actualiser » l’y recharge, après confirmation.`);
      }else{
        tone='';
        parts.push('Remotion Studio est ouvert sur la vidéo entière d’une autre variante. « Remotion Studio » y affiche celle-ci, après confirmation.');
      }
      const work=masterWorkText(ws);
      if(work){tone='warn';parts.push(work)}
      status={tone,text:parts.join(' '),link,refresh,publish:false};
    }else if(relation!=='none'){
      const parts=[];let tone='ok',link=null;
      if(relation==='here'){
        parts.push(i.needsClick?'Remotion Studio est prêt sur cette scène. Le navigateur n’ouvre un onglet qu’après un clic :'
          :masterMode?`Remotion Studio est ouvert sur cette scène seule (source v${mine.version}), dans un autre onglet. « Remotion Studio » y affiche la vidéo entière, après confirmation.`
          :`Remotion Studio est ouvert sur cette scène (source v${mine.version}), dans un autre onglet.`);
        link={url:st.url,label:i.needsClick||!(st.viewers>0)?'Ouvrir l’onglet Remotion Studio':'Ouvrir un autre onglet Remotion Studio'};
      }else if(relation==='version'){
        tone='warn';
        parts.push(`Remotion Studio montre la version ${pin.version} de cette scène ; la variante utilise la version ${mine.version}. « ${masterMode?SCENE_DOOR_LABEL:'Remotion Studio'} » y affiche la version de la variante, après confirmation.`);
      }else{
        tone='';
        const other=(i.scenes||[]).findIndex(s=>s.prefab&&s.prefab.id===pin.prefab_id&&Number(s.prefab.version)===Number(pin.version));
        const name=other>=0?`la scène ${other+1} (« ${cleanLine(i.scenes[other].title,50)} »)`:`une autre source (${cleanLine(pin.prefab_id,60)} v${pin.version})`;
        parts.push(masterMode?`Remotion Studio est ouvert sur ${name}, seule. « Remotion Studio » y affiche la vidéo entière ; « ${SCENE_DOOR_LABEL} », celle-ci (après confirmation).`
          :`Remotion Studio est ouvert sur ${name}. « Remotion Studio » y affiche cette scène, après confirmation.`);
      }
      const work=workspaceText(ws,i.scenes,blocked);
      if(work){tone='warn';parts.push(work.text);publish.offered=work.offered}
      else if(ws.saved)parts.push(`${plural(ws.saved,'fichier mis','fichiers mis')} de côté (studio-edits) à votre demande : pas ${ws.saved>1?'publiés':'publié'}.`);
      status={tone,text:parts.join(' '),link,publish:publish.offered};
    }else if(ws.count&&ws.master){
      /* Remotion Studio stopped on a whole video: its edits are still in the workspace, never publishable (§ 9, § 15). */
      status={tone:'warn',text:masterWorkText(ws),publish:false};
    }else if(ws.count&&workspaceText(ws,i.scenes,blocked)){
      /* Remotion Studio arrêté (fermé, arrêt automatique, Jarvis relancé) : ses fichiers non publiés sont toujours là, publiables ici. */
      const work=workspaceText(ws,i.scenes,blocked);
      publish.offered=work.offered;
      status={tone:'warn',text:work.text,publish:publish.offered};
    }else if(i.explain){
      status={tone:'warn',text:i.explain};
    }
    if(ws.setAside.length&&ws.relation==='here'){
      const n=ws.setAside.length,named=ws.setAside.slice(0,6).map(f=>cleanLine(f,60)).join(', ')+(n>6?'…':'');
      const said=`Au dernier lancement, ${plural(n,'élément étranger','éléments étrangers')} à l’espace de travail (${named}) ${n>1?'ont été mis':'a été mis'} de côté dans studio-edits : jamais ${n>1?'exécutés':'exécuté'} ni ${n>1?'publiés':'publié'}.`;
      status=status?{...status,tone:status.tone==='danger'?'danger':'warn',text:`${status.text} ${said}`}:{tone:'warn',text:said};
    }
    return done({button,status,relation,publish});
  }

  /* Edits made in a whole-video workspace (§ 9): said « pas publiés », with the only way out (the scene alone; they are set aside, confirmed). */
  function masterWorkText(ws){
    if(!ws||!ws.count||!ws.master)return null;
    const n=plural(ws.count,'fichier modifié','fichiers modifiés'),pub=ws.count>1?'publiés':'publié';
    return `${n} dans Remotion Studio (vidéo entière), pas ${pub} : la vidéo entière ne se publie pas dans la variante. Pour publier une scène, ouvrez-la seule (« ${SCENE_DOOR_LABEL} ») ; ${ws.count>1?'ces fichiers seront mis':'ce fichier sera mis'} de côté (studio-edits), après confirmation.`;
  }

  function workspaceText(ws,scenes,blocked){
    if(!ws.count||ws.master)return null;
    const n=plural(ws.count,'fichier modifié','fichiers modifiés'),pub=ws.count>1?'publiés':'publié';
    if(ws.relation==='here')return {offered:!blocked,
      text:`${n} dans Remotion Studio, pas encore ${pub} : la variante n’a pas changé.`};
    const at=(scenes||[]).findIndex(s=>s.prefab&&ws.base&&s.prefab.id===ws.base.prefab_id&&Number(s.prefab.version)===Number(ws.base.version));
    if(at>=0)return {offered:false,text:`${n} dans Remotion Studio sur la scène ${at+1}, pas ${pub} : à publier depuis cette scène-là ; ouvrir celle-ci dans Remotion Studio les mettra de côté (après confirmation).`};
    /* A base that no scene on screen pins: an earlier version of this scene (a publication whose end was interrupted, a « Revenir »), or a
       library version opened from the MCP card. Publishing is offered: Core alone decides (already published -> rebased, else conflict). */
    const where=ws.base?`la version ${ws.base.version} de ${cleanLine(ws.base.prefab_id,60)}`:'une autre version';
    return {offered:!blocked&&!!ws.base,text:`${n} dans Remotion Studio sur ${where}, pas ${pub} ; la scène utilise une autre version : Jarvis vérifiera avant de publier (conflit si elle a changé).`};
  }

  /* `ctx` : {doc,win,el,attrs,clear,button,later,cancelLater,now,log,announce,fetch,dialog:{open,close,current},
     scene()->{presentationId,variantId,variantNumber,revision,presentationTitle,scene,index,scenes}|null, running()->bool, pause()->void, isOpen()->bool,
     reload()->Promise (Slice 12 : relit la variante après une publication ou un retour, pour que Variantes montre la nouvelle version),
     onMaster()->void (Slice 08 du master : la préparation de la vidéo entière a changé ; l'export de Variantes la relit)} */
  const MASTER_ASKS=3;   // a stale key re-asks the confirmation; three variants changing under the dialog in a row: say so and stop
  function createRemotionDoor(ctx){
    const {doc,win,el,attrs,clear,later,cancelLater,now,log,announce}=ctx;
    const S={studio:null,capability:null,readError:null,busy:null,actionError:null,needsClick:false,explain:null,
      details:new Map(),started:false,asked:false,poll:null,ticker:null,reading:null,generation:0,lastOk:null,
      publishing:null,published:null,publishError:null,lastTarget:'auto',
      master:{key:'',state:'idle',plan:null,error:null,reading:null}};
    const ui={};
    let client=null;
    const C=()=>Studio();
    function api(){
      if(client)return client;
      const core=C();
      if(!core||!ctx.fetch)return null;
      client=core.createClient({fetchImpl:(path,options)=>ctx.fetch(path,options),setTimeoutImpl:later,clearTimeoutImpl:cancelLater});
      return client;
    }
    const keyOf=prefab=>prefab?`${prefab.id}@${prefab.version}`:'';
    /* The master read belongs to ONE variant revision: another variant or revision on screen is another read (§ 11, Slice 08). */
    const masterKeyOf=at=>at?`${at.presentationId}/${at.variantId}@${at.revision}`:'';
    function masterNow(at){return S.master.key&&S.master.key===masterKeyOf(at)?S.master:null}
    function view(){
      const at=ctx.scene();
      const scene=at&&at.scene?{id:at.scene.id,title:at.scene.title,number:at.index+1,of:at.scenes.length,prefab:at.scene.prefab}:null;
      return {at,scene,input:{scene,scenes:at?at.scenes:[],detail:scene?S.details.get(keyOf(scene.prefab))||null:null,studio:S.studio,capability:S.capability,
        readError:S.readError,busy:S.busy,actionError:S.actionError,run:ctx.running(),needsClick:S.needsClick,explain:S.explain,lastTarget:S.lastTarget,now:now(),
        publishing:S.publishing,published:S.published,publishError:S.publishError,
        master:masterNow(at),presentationId:at&&at.presentationId,variantId:at&&at.variantId,variantNumber:at&&at.variantNumber,
        presentationTitle:at&&at.presentationTitle||''}};
    }
    function model(){return doorModel(view().input)}

    /* -------------------------------------------------------------- DOM */
    function buildButton(){
      ui.button=ctx.button('Remotion Studio','jvx-btn',()=>{request({via:'button'})},{attrs:{'data-act':'remotion_studio',
        title:'Ouvrir la scène à l’écran dans Remotion Studio (un onglet à part, après confirmation)'}});
      return ui.button;
    }
    function buildStatus(){
      ui.status=el('div','jvx-rms');ui.status.hidden=true;
      ui.text=el('span','jvx-rms-text');attrs(ui.text,{role:'status','aria-live':'polite'});
      ui.link=el('a','jvx-rms-link');attrs(ui.link,{target:'_blank',rel:'noopener noreferrer'});ui.link.hidden=true;
      ui.link.addEventListener('click',()=>{S.needsClick=false;log('remotion_studio_tab_opened',{via:'link'});later(render,0)});
      ui.retry=ctx.button('Réessayer','jvx-btn',()=>{S.actionError=null;request({via:'retry'})},{attrs:{'data-act':'remotion_studio_retry'}});ui.retry.hidden=true;
      ui.publish=ctx.button('Publier dans la variante…','jvx-btn',()=>{publish({via:'button'})},{attrs:{'data-act':'remotion_studio_publish',
        title:'Publier les fichiers modifiés dans Remotion Studio comme nouvelle version de cette scène (après confirmation)'}});ui.publish.hidden=true;
      ui.revert=ctx.button('Revenir','jvx-btn',()=>{revert({via:'button'})},{attrs:{'data-act':'remotion_studio_revert'}});ui.revert.hidden=true;
      /* Slice 08 (master): « Actualiser » when the whole video changed since Remotion Studio opened it (the same confirmation, then `open`). */
      ui.refresh=ctx.button('Actualiser','jvx-btn',()=>{request({via:'refresh'})},{attrs:{'data-act':'remotion_studio_master_refresh',
        title:'Recharger la vidéo entière de la variante dans Remotion Studio (après confirmation)'}});ui.refresh.hidden=true;
      ui.log=el('details','jvx-rms-log');ui.log.hidden=true;
      ui.log.appendChild(el('summary','','Journal de Remotion Studio'));ui.logText=el('pre');ui.log.appendChild(ui.logText);
      /* The master line: the whole video's identity (or why it is unavailable) and the secondary door, the scene alone (§ 13). */
      ui.master=el('div','jvx-rms-master');ui.master.hidden=true;
      /* A live region of its own (ready -> incompatible is announced); the scene door beside it stays out of it, so nothing is said twice. */
      ui.masterText=el('span','jvx-rms-master-text');attrs(ui.masterText,{role:'status','aria-live':'polite'});
      ui.sceneDoor=ctx.button(SCENE_DOOR_LABEL,'jvx-btn jvx-rms-scene',()=>{request({via:'scene_door',target:'scene',returnFocus:ui.sceneDoor})},
        {attrs:{'data-act':'remotion_studio_scene'}});ui.sceneDoor.hidden=true;
      ui.master.appendChild(ui.masterText);ui.master.appendChild(ui.sceneDoor);
      for(const node of [ui.master,ui.text,ui.link,ui.publish,ui.refresh,ui.revert,ui.retry,ui.log])ui.status.appendChild(node);
      return ui.status;
    }
    function render(){
      if(!ui.button)return;
      const m=model();
      const b=m.button;
      attrs(ui.button,{'aria-disabled':b.blocked||b.state==='busy'?'true':'false','aria-busy':b.state==='loading'?'true':'false','aria-label':b.ariaLabel,title:b.title,'data-state':b.state,
        'data-target':m.masterMode?'master':'scene'});
      const ml=m.master;
      ui.master.hidden=!ml;
      if(ml){
        if(ui.masterText.textContent!==ml.text)ui.masterText.textContent=ml.text;
        ui.status.setAttribute('data-master-tone',ml.tone||'');
      }
      ui.sceneDoor.hidden=!(ml&&ml.scene&&m.sceneDoor);
      if(m.sceneDoor)attrs(ui.sceneDoor,{'aria-disabled':m.sceneDoor.blocked||m.button.state==='busy'?'true':'false',title:m.sceneDoor.title});
      const s=m.status;
      ui.status.hidden=!s&&!ml;
      ui.text.hidden=!s;
      if(!s){for(const node of [ui.link,ui.retry,ui.publish,ui.refresh,ui.revert,ui.log])node.hidden=true;ui.status.setAttribute('data-spin','false');return}
      ui.status.setAttribute('data-tone',s.tone||'');ui.status.setAttribute('data-spin',s.spin?'true':'false');
      if(ui.text.textContent!==s.text)ui.text.textContent=s.text;
      ui.link.hidden=!s.link;
      if(s.link){ui.link.textContent=s.link.label;ui.link.setAttribute('href',s.link.url)}
      ui.retry.hidden=!s.retry;
      ui.refresh.hidden=!s.refresh;
      ui.publish.hidden=!s.publish;
      ui.revert.hidden=!s.revert;
      if(s.revert&&ui.revert.textContent!==s.revert.label)ui.revert.textContent=s.revert.label;
      ui.log.hidden=!(s.diagnostics&&s.diagnostics.length);
      if(s.diagnostics&&s.diagnostics.length)ui.logText.textContent=s.diagnostics.map(line=>cleanLine(line,200)).join('\n');
    }

    /* -------------------------------------------------------------- lecture de l'état (Core) */
    async function refresh(reason){
      const c=api();
      if(!c||!ctx.isOpen())return;
      S.asked=true;
      if(S.reading)return S.reading;
      const generation=S.generation;
      S.reading=(async()=>{
        try{
          const [studio,capability]=await Promise.all([c.studio(),c.capability().catch(error=>{
            /* intentional: without the capability view the button stays usable; Core's own refusal says why at the click */
            log('remotion_capability_read_failed',{code:error.code,status:error.status});return null})]);
          if(generation!==S.generation)return;
          S.studio=studio;S.capability=capability;S.readError=null;
          /* Core back: what a click said against the unconfirmed view (« Réessayez dans un instant ») is no longer true. */
          if(S.lastOk===false){log('remotion_studio_read_restored',{status:studio&&studio.status});S.explain=null}
          S.lastOk=true;
        }catch(error){
          if(generation!==S.generation)return;
          const core=C();
          S.readError={code:error.code||'network',text:core&&core.errorText(error.code)||cleanLine(error.message,140)||'aucune réponse'};
          /* The first failed read of a page whose Core has no Remotion Studio is a normal state (said at the click); a read that WORKED
             and then fails is a fault, logged at `warn`. */
          log('remotion_studio_read_failed',{code:S.readError.code,status:error.status,reason},S.lastOk===true?'warn':undefined);
          S.lastOk=false;
        }finally{S.reading=null}
        render();schedule();
      })();
      return S.reading;
    }
    function hidden(){return !!doc&&doc.visibilityState==='hidden'}
    function schedule(){
      if(S.poll){cancelLater(S.poll);S.poll=null}
      if(!S.started||!ctx.isOpen()||hidden())return;
      const st=S.studio&&S.studio.status;
      const ms=S.busy||st==='starting'||st==='stopping'?POLL_FAST_MS:lostRead(S.readError)?POLL_LOST_MS:st==='ready'||(S.studio&&S.studio.work_copy&&S.studio.work_copy.unpublished)?POLL_READY_MS:0;
      if(ms)S.poll=later(()=>{S.poll=null;refresh('poll')},ms);
    }
    function tick(on){
      if(on&&!S.ticker){const step=()=>{S.ticker=later(()=>{S.ticker=null;render();if(S.busy||S.publishing||(S.studio&&S.studio.status==='starting'))step()},1000)};step()}
      if(!on&&S.ticker){cancelLater(S.ticker);S.ticker=null}
    }
    /* The return path: coming back to Jarvis's tab (or window) re-reads Remotion Studio and says what changed there. */
    function onBack(){if(S.started&&!hidden()&&S.asked)refresh('return')}
    function start(){
      if(S.started)return;
      S.started=true;S.generation+=1;
      if(win&&typeof win.addEventListener==='function')win.addEventListener('focus',onBack);
      if(doc&&typeof doc.addEventListener==='function')doc.addEventListener('visibilitychange',onBack);
      render();   // Core's Remotion Studio is read once a Remotion scene is on screen (`loadDetail`): an HTML deck never asks
    }
    function stop(){
      if(!S.started)return;
      S.started=false;S.generation+=1;
      if(S.poll){cancelLater(S.poll);S.poll=null}
      tick(false);
      if(win&&typeof win.removeEventListener==='function')win.removeEventListener('focus',onBack);
      if(doc&&typeof doc.removeEventListener==='function')doc.removeEventListener('visibilitychange',onBack);
      S.explain=null;S.actionError=null;S.needsClick=false;S.details.clear();S.asked=false;S.published=null;S.publishError=null;
      S.master={key:'',state:'idle',plan:null,error:null,reading:null};S.lastTarget='auto';
    }

    /* -------------------------------------------------------------- la vidéo entière : lue une fois par révision (Slice 08) */
    function loadMaster(at,reason){
      const c=api(),core=C();
      if(!c||!at||typeof c.masterProject!=='function')return Promise.resolve(null);
      const key=masterKeyOf(at);
      if(S.master.key===key&&S.master.reading)return S.master.reading;
      /* The same variant keeps its previous plan on screen while the new revision is read (no flicker); another variant starts empty. */
      const sameVariant=S.master.key.split('@')[0]===key.split('@')[0];
      const m={key,state:'loading',plan:sameVariant?S.master.plan:null,error:null,reading:null};
      S.master=m;
      m.reading=(async()=>{
        try{
          const plan=await c.masterProject(at.presentationId,at.variantId);
          if(S.master!==m)return null;
          m.plan=plan&&typeof plan==='object'?plan:null;
          m.state=m.plan&&m.plan.status==='ready'?'ready':m.plan?'incompatible':'error';
          if(!m.plan)m.error={code:'master_view_empty',text:'Core n’a rendu aucune vue de la vidéo entière.'};
          log('remotion_master_read',{why:reason,status:m.plan&&m.plan.status,reason:m.plan&&m.plan.reason||null,
            scenes:m.plan&&Array.isArray(m.plan.scenes)?m.plan.scenes.length:null,variant_revision:m.plan&&m.plan.variant_revision});
        }catch(error){
          if(S.master!==m)return null;
          m.state='error';m.plan=null;
          m.error={code:error.code||'network',text:core&&core.errorText(error.code)||cleanLine(error.message,140)||'aucune réponse'};
          /* A Core without the route (older) or a variant gone is said on the master line; the scene door stays: `warn`, not `error`. */
          log('remotion_master_read_failed',{why:reason,code:m.error.code,status:error.status},'warn');
        }finally{
          if(S.master===m)m.reading=null;
          render();
          if(typeof ctx.onMaster==='function')ctx.onMaster();
        }
        return m;
      })();
      return m.reading;
    }
    /* Read when a Remotion scene is on screen (like Remotion Studio's own state: an HTML deck never asks) and its revision is not read yet. */
    function maybeMaster(reason){
      const v=view();
      if(!v.at||!v.scene||!ctx.isOpen())return null;
      const d=S.details.get(keyOf(v.scene.prefab));
      if(!(d&&d.state==='ready'&&d.remotion))return null;
      if(S.master.key===masterKeyOf(v.at))return S.master.reading||null;
      return loadMaster(v.at,reason);
    }
    /* What the export of Variants reads (the same view, never a second read). */
    function masterState(){
      const at=ctx.scene(),m=masterNow(at);
      return m?{state:m.state,plan:m.plan,error:m.error,loading:!!m.reading}:{state:'idle',plan:null,error:null,loading:false};
    }

    /* -------------------------------------------------------------- la scène : Remotion ? provenance ? (lu une fois par pin) */
    function sync(){
      const v=view();
      if(S.explain&&!(v.scene&&model().button.blocked===S.explain))S.explain=null;
      const prefab=v.scene&&v.scene.prefab;
      const key=keyOf(prefab);
      if(prefab&&ctx.isOpen()&&!S.details.has(key))loadDetail(prefab);
      else maybeMaster('revision');   // a new revision of the variant on screen (hot reload, voice edit, publication) is read again
      render();
    }
    function loadDetail(prefab){
      const key=keyOf(prefab);
      const known=S.details.get(key);
      if(known&&known.state==='loading'&&known.promise)return known.promise;   // one read per pin at a time (the rail's click may race it)
      const record={state:'loading',remotion:null,provenance:null,promise:null};
      S.details.set(key,record);
      record.promise=readDetail(prefab,record);
      return record.promise;
    }
    async function readDetail(prefab,record){
      const key=keyOf(prefab);
      const c=api();
      if(!c){record.state='error';return record}
      try{
        const payload=await ctx.fetch(`/api/prefabs/${encodeURIComponent(prefab.id)}/${Number(prefab.version)}`,{method:'GET',cache:'no-store'});
        let body=null;
        try{body=await payload.json()}catch(_error){body=null /* intentional: a non-JSON answer is reported by its HTTP status below */}
        if(!payload.ok)throw Object.assign(new Error(body&&body.error&&body.error.message||`HTTP ${payload.status}`),{code:body&&body.error&&body.error.code||`http_${payload.status}`});
        record.state='ready';record.remotion=isRemotionManifest(body&&body.manifest);
        record.provenance=body&&body.publication&&body.publication.provenance||null;
        if(record.remotion&&!S.asked)refresh('scene');   // the first Remotion scene on screen: what is Remotion Studio doing?
        if(record.remotion)maybeMaster('scene');
      }catch(error){
        /* Unknown is not « not Remotion »: the button stays usable, the click re-reads, Core refuses a wrong pin by its own code. */
        record.state='error';record.code=error.code||'network';
        log('remotion_scene_read_failed',{prefab:key,code:record.code});
      }
      render();
      return record;
    }

    /* -------------------------------------------------------------- la confirmation (dans la couche de Variantes) */
    /* The discard line, for a scene base or for a whole-video workspace (Slice 08). */
    function discardText(discard){
      const n=plural(discard.count,'fichier modifié','fichiers modifiés');
      const where=discard.master?' (vidéo entière)':discard.base?` (sur v${discard.base.version})`:'';
      return `${n} dans Remotion Studio${where} ${discard.count>1?'seront mis de côté (studio-edits), pas publiés':'sera mis de côté (studio-edits), pas publié'}.`;
    }
    /* The scrolling body of an open confirmation (its heading and action row stay pinned, CSS above). */
    function confirmBody(dlg){const body=el('div','jvx-confirm-body');dlg.box.appendChild(body);return body}
    function confirmOpen(sceneView,detail,kind,returnFocus,discard){
      const core=C();
      const label=`Scène ${sceneView.number} sur ${sceneView.of} « ${cleanLine(sceneView.title,60)} » · source v${sceneView.prefab.version}`;
      const spec=core.confirmSpec({id:sceneView.prefab.id,version:sceneView.prefab.version,label},detail&&detail.state==='ready'?detail.provenance:null,kind);
      return new Promise(resolve=>{
        let settled=false;
        const finish=value=>{if(settled)return;settled=true;resolve(value)};
        const dlg=ctx.dialog.open({kind:'remotion_studio',titleId:'jvxDialogTitle',returnFocus,onClose:()=>finish(false)});
        dlg.box.setAttribute('data-kind','remotion_studio');
        const h=el('h2','',spec.title);h.id='jvxDialogTitle';dlg.box.appendChild(h);
        const body=confirmBody(dlg);
        const list=el('ul','jvx-confirm-lines');
        for(const [head,text] of spec.lines){const li=el('li');li.appendChild(el('strong','',head));li.appendChild(doc.createTextNode(text));list.appendChild(li)}
        if(discard){const li=el('li');li.setAttribute('data-line','discard');li.appendChild(el('strong','','Fichiers non publiés : '));
          li.appendChild(doc.createTextNode(discardText(discard)));list.appendChild(li)}
        body.appendChild(list);
        body.appendChild(el('p','','Variantes reste ouvert ici, sur cette scène. Ce que vous changez dans Remotion Studio n’atteint la variante que par « Publier dans la variante… ».'));
        const actions=el('div','jvx-dialog-actions');
        const cancel=ctx.dialogButton(spec.cancelLabel,()=>{ctx.dialog.close(true);finish(false)});
        const go=ctx.dialogButton(spec.confirmLabel,()=>{finish(true);ctx.dialog.close(true)},{primary:true,danger:spec.danger});
        go.setAttribute('data-act','remotion_studio_confirm');
        actions.appendChild(cancel);actions.appendChild(go);dlg.box.appendChild(actions);
        (spec.danger?cancel:go).focus({preventScroll:true});
      });
    }

    /* The whole video's confirmation (§ 9): the presentation, the variant, the scene count, the risk, each mounted version and its provenance. */
    function confirmMaster(at,plan,provenances,kind,returnFocus,discard,note){
      const core=C(),f=masterFacts(plan);
      const titles=new Map((at.scenes||[]).map(s=>[s.id,s.title]));
      const rows=(plan.scenes||[]).map((s,n)=>`${n+1}. « ${cleanLine(titles.get(s.scene_id)||s.scene_id,40)} » v${s.version}`);
      const versions=rows.slice(0,8).join(' · ')+(rows.length>8?` · … (+${rows.length-8})`:'');
      const label=`${projectName({presentationTitle:at.presentationTitle,variantNumber:at.variantNumber})} · ${f.scenes}${f.seconds?` · ${f.seconds}`:''}${f.spec?` (${f.spec})`:''}`;
      const spec=core.masterConfirmSpec({label,sceneCount:f.count,versions},provenances,kind);
      return new Promise(resolve=>{
        let settled=false;
        const finish=value=>{if(settled)return;settled=true;resolve(value)};
        const dlg=ctx.dialog.open({kind:'remotion_studio',titleId:'jvxDialogTitle',returnFocus,onClose:()=>finish(false)});
        dlg.box.setAttribute('data-kind','remotion_studio');dlg.box.setAttribute('data-target','master');
        const h=el('h2','',spec.title);h.id='jvxDialogTitle';dlg.box.appendChild(h);
        const body=confirmBody(dlg);
        if(note){const p=el('p','jvx-confirm-note',note);p.setAttribute('data-line','stale');body.appendChild(p)}
        const list=el('ul','jvx-confirm-lines');
        for(const [head,text] of spec.lines){const li=el('li');li.appendChild(el('strong','',head));li.appendChild(doc.createTextNode(text));list.appendChild(li)}
        if(discard){const li=el('li');li.setAttribute('data-line','discard');li.appendChild(el('strong','','Fichiers non publiés : '));
          li.appendChild(doc.createTextNode(discardText(discard)));list.appendChild(li)}
        body.appendChild(list);
        body.appendChild(el('p','',`Variantes reste ouvert ici. La vidéo entière ne se publie pas dans la variante : pour modifier puis publier une scène, ouvrez-la seule (« ${SCENE_DOOR_LABEL} »).`));
        const actions=el('div','jvx-dialog-actions');
        const cancel=ctx.dialogButton(spec.cancelLabel,()=>{ctx.dialog.close(true);finish(false)});
        const go=ctx.dialogButton(spec.confirmLabel,()=>{finish(true);ctx.dialog.close(true)},{primary:true,danger:spec.danger});
        go.setAttribute('data-act','remotion_studio_confirm');
        actions.appendChild(cancel);actions.appendChild(go);dlg.box.appendChild(actions);
        (spec.danger?cancel:go).focus({preventScroll:true});
      });
    }
    /* Each mounted version's provenance, read once per pin (the same read as a scene's); unreadable = null (the reinforced warning). */
    async function masterProvenances(plan){
      const rows=Array.isArray(plan&&plan.scenes)?plan.scenes:[];
      return Promise.all(rows.map(async s=>{
        const prefab={id:s.prefab_id,version:s.version};
        let d=S.details.get(keyOf(prefab));
        if(!d||d.state==='loading'||d.state==='error')d=await loadDetail(prefab);
        return d&&d.state==='ready'?d.provenance:null;
      }));
    }
    /* Edits of the workspace that opening THIS whole video would set aside (another target, or this variant's older key). */
    function masterDiscard(st,plan){
      const ws=workspaceOf(st,null);
      if(!ws.count)return null;
      const t=st&&st.target;
      if(t&&t.kind==='variant_master'&&t.project_key===plan.project_key)return null;
      return {count:ws.count,base:ws.base,master:ws.master};
    }
    async function requestMaster(o,v,m){
      const core=C(),c=api();
      const st=S.studio;
      if(m.masterRelation==='here'&&st&&st.url){S.needsClick=!openTab(st.url,'button');render();return {state:'shown',url:st.url}}
      const at=v.at;
      let plan=masterNow(at).plan,note=null,discard=masterDiscard(st,plan);
      for(let ask=0;ask<MASTER_ASKS;ask++){
        const provenances=await masterProvenances(plan);
        const live=S.studio&&S.studio.status==='ready';
        const kind=m.masterRelation==='stale'&&ask===0?'refresh':live?'switch':'open';
        const ok=await confirmMaster(at,plan,provenances,kind,o.returnFocus||ui.button,discard,note);
        if(!ok){log('remotion_studio_cancelled',{via:o.via,target:'master'});announce('Remotion Studio : rien n’a été lancé.');return {state:'cancelled'}}
        const now2=ctx.scene();
        if(!now2||now2.presentationId!==at.presentationId||now2.variantId!==at.variantId){
          S.explain='La variante a changé pendant la confirmation : rien n’a été lancé.';render();return {state:'cancelled'}}
        ctx.pause();
        const f=masterFacts(plan);
        S.busy={label:live?'Remotion Studio charge la vidéo entière…':'Remotion Studio démarre sur la vidéo entière…',at:now()};
        S.actionError=null;S.explain=null;S.needsClick=false;S.generation+=1;S.lastTarget='master';
        render();tick(true);schedule();
        log('remotion_studio_open_requested',{via:o.via,kind,target:'master',variant_id:at.variantId,project_key:plan.project_key,scenes:f.count,discard:!!discard});
        let result=null,again=null;
        try{
          const body={kind:core.MASTER_KIND,presentation_id:at.presentationId,variant_id:at.variantId,project_key:plan.project_key};
          if(discard)body[core.DISCARD_FIELD]=true;   // the user read the discard line: their unpublished files are set aside, never silently
          const studio=await c.write('open',body);
          S.studio=studio;S.readError=null;S.lastOk=true;
          if(studio.status==='failed'){
            log('remotion_studio_open_failed',{code:studio.last_error_code,target:'master'},'error');
            result={state:'failed',code:studio.last_error_code};
          }else if(studio.status==='ready'&&studio.url){
            const liveClick=activationLive();
            S.needsClick=!liveClick||!openTab(studio.url,'auto');
            if(S.needsClick)announce('Remotion Studio est prêt : cliquez « Ouvrir l’onglet Remotion Studio ».');
            log('remotion_studio_ready',{seconds:Math.round((now()-S.busy.at)/1000),tab:S.needsClick?'needs_click':'opened',target:'master'});
            result={state:'ready',url:studio.url,tab:S.needsClick?'needs_click':'opened',target:'master'};
          }else result={state:studio.status,target:'master'};
        }catch(error){
          const info=error.info||{};
          if(error.code==='remotion_studio_master_stale'){
            /* The variant changed since the dialog (§ 9): re-read the whole video, re-ask with its new scene count. */
            log('remotion_studio_master_stale',{via:o.via,asked:plan.project_key,current:info.project_key||null,scenes:info.scene_count||null},'info');
            again='stale';
          }else if(error.code==='remotion_studio_unpublished_edits'&&!discard){
            const count=Number(info.count)||(Array.isArray(info.files)?info.files.length:0);
            log('remotion_studio_unpublished_kept',{via:o.via,target:'master',count},'info');
            discard={count:count||1,base:info.base||null,master:!!(info.target&&info.target.kind==='variant_master')};
            note='Remotion Studio garde des fichiers modifiés, pas publiés : les mettre de côté est nécessaire pour ouvrir la vidéo entière.';
            again='discard';
          }else{
            let text=core.errorText(error.code)||cleanLine(error.message,160)||'l’action a échoué';
            if(error.code==='remotion_studio_master_incompatible'&&info.reason)text=core.masterReasonSentence(info.reason,info.detail);
            S.actionError={code:error.code||'network',text};
            log('remotion_studio_open_failed',{code:S.actionError.code,status:error.status,target:'master'},'error');
            result={state:'failed',code:S.actionError.code};
            if(error.code==='remotion_studio_master_incompatible')loadMaster(at,'incompatible');   // the line and the button follow Core's view
          }
        }finally{
          S.busy=null;tick(false);render();
        }
        if(again==='stale'){
          const read=await loadMaster(at,'stale');
          const fresh=read&&read.plan;
          if(!fresh||fresh.status!=='ready'){
            S.actionError={code:'remotion_studio_master_stale',text:fresh?`La variante a changé : ${core.masterReasonSentence(fresh.reason,fresh.detail)}`
              :'La variante a changé et sa vidéo entière n’a pas pu être relue.'};
            render();refresh('after_open');return {state:'failed',code:'remotion_studio_master_stale'};
          }
          plan=fresh;discard=masterDiscard(S.studio,plan);
          note=`La variante a changé depuis votre confirmation : la vidéo entière compte maintenant ${masterFacts(plan).scenes}. Confirmez de nouveau.`;
          continue;
        }
        if(again==='discard')continue;
        refresh('after_open');
        return result;
      }
      S.actionError={code:'remotion_studio_master_stale',text:'La variante change sans cesse pendant la confirmation : rien n’a été lancé. Réessayez dans un instant.'};
      log('remotion_studio_master_gave_up',{via:o.via,asks:MASTER_ASKS},'warn');render();
      return {state:'failed',code:'remotion_studio_master_stale'};
    }

    /* -------------------------------------------------------------- ouvrir */
    function activationLive(){
      const ua=win&&win.navigator&&win.navigator.userActivation;
      if(ua&&typeof ua.isActive==='boolean')return ua.isActive;
      return !!S.busy&&now()-S.busy.at<ACTIVATION_MS;
    }
    function openTab(url,via){
      try{win.open(url,TAB_NAME,'noopener,noreferrer')}
      catch(error){log('remotion_studio_tab_failed',{via,error:cleanLine(error&&error.message,120)},'warn');S.needsClick=true;return false}
      log('remotion_studio_tab_opened',{via});
      return true;
    }
    async function request(options){
      const o=options||{};
      if(!ctx.isOpen())return {state:'refused',reason:'Variantes est fermé.'};
      if(S.busy||S.publishing){announce(S.busy?'Remotion Studio démarre déjà.':'Une publication est en cours.');return {state:'busy'}}
      S.publishError=null;
      /* The whole video's readiness first (the rail opens Variants then this door at once: the scene's and the video's reads may still be on
         the way). Unknown stays unknown: a failed read leaves the scene door. */
      const first=view().scene;
      const known=first&&first.prefab?S.details.get(keyOf(first.prefab)):null;
      if(first&&first.prefab&&(!known||known.state==='loading'))await loadDetail(first.prefab);
      /* A newer revision may take over the read on the way: wait for the read that answers for what is on screen (never the scene by default). */
      for(let n=0,pending=maybeMaster('request');pending&&n<4;n++,pending=maybeMaster('request'))await pending;
      /* Core's view unconfirmed (R1): a click reads it again before deciding; still unreadable, the button says so and nothing opens. */
      if(lostRead(S.readError))await refresh('request');
      const v=view(),m=doorModel(v.input);
      if(m.button.blocked){
        S.explain=m.button.blocked;render();
        log('remotion_studio_blocked',{via:o.via,why:m.button.blocked.slice(0,60)});
        return {state:'refused',reason:m.button.blocked};
      }
      const core=C(),c=api();
      if(!core||!c){
        S.actionError={code:'remotion_studio_page_error',text:'le module de Remotion Studio n’est pas chargé dans cette page.'};render();
        log('remotion_studio_module_missing',{},'error');
        return {state:'failed',code:'remotion_studio_page_error'};
      }
      /* « Remotion Studio » opens the whole video when it is ready; the scene door (« Cette scène seule… ») keeps the scene. « Réessayer »
         retries exactly the target that failed, never re-decides (Slice 09 rework). `target`: 'scene' | 'master' | undefined (the primary meaning). */
      const target=o.target||(o.via==='retry'&&S.lastTarget!=='auto'?S.lastTarget:undefined);
      if(target==='master'&&!m.masterMode){
        S.lastTarget='auto';S.explain='La vidéo entière n’est plus prête (voir la ligne ci-dessus) : rien n’a été relancé. « Remotion Studio » ouvre maintenant la scène à l’écran.';
        announce(S.explain);render();log('remotion_studio_blocked',{via:o.via,why:'master_not_ready',target:'master'});
        return {state:'refused',reason:S.explain};
      }
      if(m.masterMode&&target!=='scene')return requestMaster(o,v,m);
      const sc=v.scene,st=S.studio;
      if(m.relation==='here'&&st.url){S.needsClick=!openTab(st.url,'button');render();return {state:'shown',url:st.url}}
      let detail=S.details.get(keyOf(sc.prefab));
      if(!detail||detail.state!=='ready')detail=await loadDetail(sc.prefab);
      if(detail.state==='ready'&&!detail.remotion){const again=doorModel(view().input);S.explain=again.button.blocked;render();return {state:'refused',reason:S.explain}}
      const kind=st&&st.status==='ready'?'switch':'open';
      const ws=workspaceOf(st,sc.prefab);
      const discard=ws.count&&(ws.relation==='other'||ws.relation==='master')?{count:ws.count,base:ws.base,master:ws.master}:null;
      const ok=await confirmOpen(sc,detail,kind,o.returnFocus||ui.button,discard);
      if(!ok){log('remotion_studio_cancelled',{via:o.via});announce('Remotion Studio : rien n’a été lancé.');return {state:'cancelled'}}
      /* Still the scene that was confirmed? (a poll, a hot reload or the user may have moved while the dialog was open) */
      const now2=view().scene;
      if(!now2||keyOf(now2.prefab)!==keyOf(sc.prefab)){S.explain='La scène a changé pendant la confirmation : rien n’a été lancé.';render();return {state:'cancelled'}}
      ctx.pause();
      S.busy={label:kind==='switch'?'Remotion Studio change de scène…':'Remotion Studio démarre…',at:now()};
      S.actionError=null;S.explain=null;S.needsClick=false;S.generation+=1;S.lastTarget='scene';
      render();tick(true);schedule();
      log('remotion_studio_open_requested',{via:o.via,kind,prefab:keyOf(sc.prefab),scene_id:sc.id});
      let result;
      try{
        const body={prefab_id:sc.prefab.id,version:Number(sc.prefab.version)};
        if(discard)body[core.DISCARD_FIELD]=true;   // the user read the line above: their unpublished files are set aside, never silently
        const studio=await c.write('open',body);
        S.studio=studio;S.readError=null;S.lastOk=true;
        if(studio.status==='failed'){
          log('remotion_studio_open_failed',{code:studio.last_error_code,prefab:keyOf(sc.prefab)},'error');
          result={state:'failed',code:studio.last_error_code};
        }else if(studio.status==='ready'&&studio.url){
          const live=activationLive();
          S.needsClick=!live||!openTab(studio.url,'auto');
          if(S.needsClick)announce('Remotion Studio est prêt : cliquez « Ouvrir l’onglet Remotion Studio ».');
          log('remotion_studio_ready',{seconds:Math.round((now()-S.busy.at)/1000),tab:S.needsClick?'needs_click':'opened'});
          result={state:'ready',url:studio.url,tab:S.needsClick?'needs_click':'opened'};
        }else result={state:studio.status};
      }catch(error){
        S.actionError={code:error.code||'network',text:core.errorText(error.code)||cleanLine(error.message,160)||'l’action a échoué'};
        log('remotion_studio_open_failed',{code:S.actionError.code,status:error.status,prefab:keyOf(sc.prefab)},'error');
        result={state:'failed',code:S.actionError.code};
      }finally{
        S.busy=null;tick(false);render();
      }
      refresh('after_open');
      return result;
    }

    /* -------------------------------------------------------------- publier (Slice 12) */
    function confirmPublish(sc,ws,returnFocus){
      return new Promise(resolve=>{
        let settled=false;
        const finish=value=>{if(settled)return;settled=true;resolve(value)};
        const dlg=ctx.dialog.open({kind:'remotion_studio_publish',titleId:'jvxDialogTitle',returnFocus,onClose:()=>finish(false)});
        dlg.box.setAttribute('data-kind','remotion_studio_publish');
        const h=el('h2','','Publier dans la variante ?');h.id='jvxDialogTitle';dlg.box.appendChild(h);
        const list=el('ul','jvx-confirm-lines');
        const line=(head,text,key)=>{const li=el('li');if(key)li.setAttribute('data-line',key);li.appendChild(el('strong','',head));li.appendChild(doc.createTextNode(text));list.appendChild(li)};
        line('Scène : ',`Scène ${sc.number} sur ${sc.of} « ${cleanLine(sc.title,60)} »`,'scene');
        line('Fichiers : ',`${plural(ws.count,'fichier modifié','fichiers modifiés')} dans Remotion Studio, tous publiés tels quels :`,'files');
        /* Chaque fichier, sans troncature (liste défilante) : ce que Core publiera est exactement cette liste (son empreinte part avec
           la confirmation ; un fichier changé depuis fait refuser la publication). */
        const files=el('ul','jvx-rms-files');files.setAttribute('data-line','files-list');attrs(files,{tabindex:'0','aria-label':`${ws.count} fichiers à publier`});
        for(const f of ws.files)files.appendChild(el('li','',cleanLine(f,160)));
        list.lastChild.appendChild(files);
        line('Ce qui se passe : ',`Jarvis compile la scène puis la publie comme NOUVELLE version ; la v${sc.prefab.version} n’est pas modifiée et reste disponible (« Revenir »).`,'what');
        line('Refusé si : ','la scène a changé depuis l’ouverture dans Remotion Studio, elle ne compile pas, ou elle importe autre chose que react et remotion.','refused');
        dlg.box.appendChild(list);
        const actions=el('div','jvx-dialog-actions');
        const cancel=ctx.dialogButton('Annuler',()=>{ctx.dialog.close(true);finish(false)});
        const go=ctx.dialogButton('Publier',()=>{finish(true);ctx.dialog.close(true)},{primary:true});
        go.setAttribute('data-act','remotion_studio_publish_confirm');
        actions.appendChild(cancel);actions.appendChild(go);dlg.box.appendChild(actions);
        cancel.focus({preventScroll:true});   // publier écrit une nouvelle version : une touche Entrée égarée ne publie rien (QA Slice 12, P-a)
      });
    }
    async function publish(options){
      const o=options||{};
      if(S.publishing||S.busy){announce('Une opération sur Remotion Studio est en cours.');return {state:'busy'}}
      const v=view(),m=doorModel(v.input);
      if(!m.publish.offered||!v.scene){return {state:'refused',reason:'Rien à publier dans cette scène.'}}
      const core=C(),c=api();
      if(!core||!c){S.publishError={code:'remotion_studio_page_error',text:'le module de Remotion Studio n’est pas chargé dans cette page.',sceneId:v.scene.id};
        log('remotion_studio_module_missing',{},'error');render();return {state:'failed'}}
      const sc=v.scene,at=v.at,ws=workspaceOf(S.studio,sc.prefab);
      if(!ws.digest){S.publishError={code:'remotion_studio_page_error',text:'la liste des fichiers n’a pas encore été lue : réessayez dans un instant.',sceneId:sc.id};
        log('remotion_studio_publish_no_listing',{via:o.via},'warn');render();refresh('no_listing');return {state:'refused'}}
      const ok=await confirmPublish(sc,ws,o.returnFocus||ui.publish);
      if(!ok){log('remotion_studio_publish_cancelled',{via:o.via});announce('Rien n’a été publié.');return {state:'cancelled'}}
      const now2=view().scene;
      if(!now2||keyOf(now2.prefab)!==keyOf(sc.prefab)){S.explain='La scène a changé pendant la confirmation : rien n’a été publié.';render();return {state:'cancelled'}}
      S.publishing={at:now(),label:'Publication dans la variante…'};S.publishError=null;S.published=null;S.explain=null;
      render();tick(true);
      log('remotion_studio_publish_requested',{via:o.via,prefab:keyOf(sc.prefab),scene_id:sc.id,files:ws.count,digest:ws.digest.slice(0,12)});
      let result;
      try{
        const answer=await c.write('publish',{presentation_id:at.presentationId,variant_id:at.variantId,scene_id:sc.id,
          base:{prefab_id:ws.base.prefab_id,version:Number(ws.base.version)},   // the workspace base the user saw, checked by Core
          digest:ws.digest});   // the listing the user confirmed: Core refuses (listing_changed) if the workspace no longer gives it
        if(answer&&answer.studio)S.studio=answer.studio;
        const p=answer&&answer.publish||{};
        S.published={published:p.published,previous:p.previous,status:p.status,sceneId:sc.id,presentationId:at.presentationId,variantId:at.variantId};
        log('remotion_studio_published',{status:p.status,published:p.published&&`${p.published.prefab_id}@${p.published.version}`,
          seconds:Math.round((now()-S.publishing.at)/1000)});
        announce(`Publié : source v${p.published&&p.published.version}.`);
        result={state:'published',published:p.published,previous:p.previous,status:p.status};
      }catch(error){
        const info=error.info||{};
        const diagnostics=(info.diagnostics||[]).slice(0,DIAG_LINES).map(d=>d&&typeof d==='object'?`${d.file}:${d.line}:${d.column} ${d.text}`:String(d));
        let text=core.errorText(error.code)||cleanLine(error.message,200)||'la publication a échoué';
        if(error.code==='remotion_studio_publish_conflict'&&info.current)text+=` La variante utilise la v${info.current.version} ; Remotion Studio a été ouvert sur la v${info.base&&info.base.version}.`;
        if(error.code==='remotion_studio_publish_import_refused'&&info.imports)text+=` (${info.imports.slice(0,4).join(', ')})`;
        if(error.code==='remotion_studio_publish_refused'&&info.publish_code)text+=` ${cleanLine(error.message,220)} [${info.publish_code}]`;
        if(error.code==='remotion_studio_publish_invalid_file')text+=` ${cleanLine(error.message,220)}`;
        if(error.code==='remotion_studio_publish_listing_changed'&&typeof info.count==='number')text+=` (${plural(info.count,'fichier modifié','fichiers modifiés')} maintenant)`;
        S.publishError={code:error.code||'network',text,diagnostics,sceneId:sc.id};
        log('remotion_studio_publish_failed',{code:S.publishError.code,publish_code:info.publish_code,status:error.status},
          error.status>=500||!error.status?'error':'warn');
        result={state:'refused',code:S.publishError.code};
      }finally{
        S.publishing=null;tick(false);render();
      }
      if(result.state==='published'&&ctx.reload)await Promise.resolve(ctx.reload()).catch(error=>log('remotion_studio_reload_failed',{error:cleanLine(error&&error.message,120)},'warn'));
      refresh('after_publish');
      return result;
    }
    /* « Revenir à … » : la porte d'édition de source republie l'ancien contenu comme NOUVELLE version (`restore_version`). */
    async function revert(options){
      const o=options||{};
      const p=S.published,at=ctx.scene();
      if(!p||!p.previous||S.publishing)return {state:'refused'};
      if(!at||at.presentationId!==p.presentationId||at.variantId!==p.variantId||!at.scene||at.scene.id!==p.sceneId){
        S.explain='La scène publiée n’est plus à l’écran : rien n’a été changé.';render();return {state:'refused'};
      }
      S.publishing={at:now(),label:'Retour à la version d’avant…'};S.publishError=null;render();tick(true);
      log('remotion_studio_revert_requested',{via:o.via,target:`${p.previous.prefab_id}@${p.previous.version}`});
      let result;
      try{
        const path=`/api/presentation-studio/presentations/${encodeURIComponent(p.presentationId)}/variants/${encodeURIComponent(p.variantId)}/source-edits`;
        const response=await ctx.fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},cache:'no-store',
          body:JSON.stringify({actor:'user',basis:{variant_revision:Number(at.revision)},scene_id:p.sceneId,
            files:{restore_version:{id:p.previous.prefab_id,version:Number(p.previous.version)}}})});
        let body=null;
        try{body=await response.json()}catch(_error){body=null /* intentional: a non-JSON answer is reported by its HTTP status below */}
        const status=body&&body.status;
        if(!response.ok||!['reloaded','reloaded_state_reset','repinned','pending_mount'].includes(status)){
          const e=body&&body.error||{};
          throw Object.assign(new Error(e.message||body&&body.message||`HTTP ${response.status}`),{code:e.code||body&&body.code||status||`http_${response.status}`,status:response.status});
        }
        S.published={...p,published:{prefab_id:body.published.id,version:body.published.version},restored:true,status};
        log('remotion_studio_reverted',{status,published:`${body.published.id}@${body.published.version}`});
        result={state:'reverted',published:S.published.published};
      }catch(error){
        S.publishError={code:error.code||'network',text:`le retour à la version d’avant a échoué : ${cleanLine(error.message,200)}`,diagnostics:[],sceneId:p.sceneId};
        log('remotion_studio_revert_failed',{code:S.publishError.code,status:error.status},'error');
        result={state:'failed',code:S.publishError.code};
      }finally{S.publishing=null;tick(false);render()}
      if(result.state==='reverted'&&ctx.reload)await Promise.resolve(ctx.reload()).catch(error=>log('remotion_studio_reload_failed',{error:cleanLine(error&&error.message,120)},'warn'));
      refresh('after_revert');
      return result;
    }

    return Object.freeze({buildButton,buildStatus,render,sync,start,stop,refresh:()=>refresh('api'),request,model,publish,revert,
      master:masterState,rereadMaster:()=>{const at=ctx.scene();return at?loadMaster(at,'reread'):Promise.resolve(null)},
      state:()=>({studio:S.studio&&{status:S.studio.status,pin:S.studio.pin,target:S.studio.target||null,url:S.studio.url,work_copy:S.studio.work_copy||null},busy:!!S.busy,
        needsClick:S.needsClick,error:S.actionError,readError:S.readError,explain:S.explain,publishing:!!S.publishing,published:S.published,
        publishError:S.publishError,master:masterState()})});
  }

  const api=Object.freeze({createRemotionDoor,doorModel,workspaceOf,isRemotionManifest,masterLine,masterRelationOf,CSS,TAB_NAME,PUBLISH_LIMIT_S,SCENE_DOOR_LABEL});
  root.JarvisVariantsRemotionStudio=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
