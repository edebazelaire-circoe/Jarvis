/* Rail permanent des présentations — rail actif de l'espace de travail, zone `right` de la coque (Slice 07 du handoff
   jarvis-board-orbital-ui-workspace-rail, décision D10 ; docs/control-center-shell.md › Zones, docs/presentation-studio.md › Rail).

   Une colonne au bord DROIT (`--shell-rail-w` : 300 px, 72 px sous 1100 px, un onglet sous 700 px), sous le lanceur et au-dessus de
   l'onglet Chat, qui liste TOUTES les présentations en cartes : un aperçu réel (le dernier rendu `presentation_still` complet, lu par la
   route bornée `/api/artifacts/{id}/payload`) ou une vignette typée « Présentation · Remotion / Slidecar » quand aucun rendu n'existe
   (jamais une fausse diapositive), un badge de type, le titre, une métadonnée légère (variantes, modifiée il y a…), et l'état (pastille
   ET libellé). Plusieurs présentations vivent en parallèle ; un agent peut en corriger une pendant que l'utilisateur en regarde une autre.

   État, par priorité : bleu `working` (un agent travaille) > orange `problem` (forme propre, triangle ; reste jusqu'à l'acquittement ou au
   prochain travail) > jaune `unreviewed` (travail du cerveau terminé que vous n'avez pas revu ; tenu par Core dans `rail.json`, effacé par
   l'action `review` quand vous ouvrez la présentation depuis le rail ou « Marquer comme vu ») > vert `done`. Ligne sans état lisible :
   `unknown`, anneau pointillé, jamais vert. L'état de travail est tenu par Core (`work`, `unreviewed`), jamais ici.

   Ce que ce module est :
   - une VUE de `GET /api/presentation-studio/rail` (relais de Core), sondée par le module lui-même (2 s quand un agent travaille, 4 s au
     repos, 20 s onglet caché). Aucune présentation n'est gardée ici : un geste (masquer, archiver, renommer, marquer comme vu) est une
     écriture de Core (`POST .../presentations/{id}/rail`, acteur `user` imposé par le relais) puis une relecture ; un échec est dit à l'écran ;
   - le lieu des gestes : clic = ouvrir Variantes sur la présentation (fenêtré, `JarvisStudioExplorer`), clic droit (ou touche Menu,
     Maj+F10, ou le bouton « ⋯ » de la carte) = menu Ouvrir les variantes / Remotion Studio… / Éditer / Présenter / Masquer ou Afficher /
     Renommer / Acquitter (orange) / Marquer comme vu (jaune) / Supprimer (archiver, restaurable, avec confirmation) ; une archivée ne
     propose que Restaurer ;
   - le récepteur des demandes d'écran du cerveau (`ui.request` : montrer ou masquer le rail), et le rapporteur de ce que la page
     constate (`POST .../rail/display-state` : rail visible, Variantes ouvert et sur quelle présentation), pour que
     `presentation_inspect target rail` ne devine rien.

   Quand il est visible : dans un Board de nature « présentation », en mode d'interaction PRESENTATION, dès qu'un agent travaille ou qu'un
   problème attend, quand Variantes est ouvert, ou si l'utilisateur l'a épinglé (Alt+Maj+P : automatique, toujours visible, masqué). Épinglé
   « masqué », il ne se montre que sur demande du cerveau. Pendant le Studio (Variantes, fenêtré) il se range en colonne à DROITE de
   l'explorateur (miroir de l'ancien rangement à gauche), hors de la zone rendue inerte : la voix et le rail restent utilisables.

   Étape B (adaptateur pur `control_center_workspace_rail_model.js`, séparable) : sous les présentations, une section « Sur ce Board » montre les
   Artifacts liés au Board actif (fichiers déposés, liens, captures, enregistrements, rendus) en cartes du même dessin, état sans jaune ; le
   clic ouvre l'image dans l'aperçu des captures quand il existe (Slice 05), sinon le détail de l'Artifact dans l'inspecteur (`JarvisWorkspace`).

   Édition produit (jarvis-presentation-edition-v1, Slice 08 ; `docs/presentation-studio.md` › *Presentation home*). Quand l'édition
   est une édition produit (`JarvisProductEdition`, lue sur Core : `edition` ≠ `full`), le rail est l'ACCUEIL des présentations d'un Board
   Présentation : visible même vide, avec le parcours en quatre étapes (sources du Dossier → créer → faire écrire les scènes → relire,
   présenter, exporter) et un bouton « Nouvelle présentation » en tête (`POST /api/presentation-studio/presentations`, le défaut de Core :
   aucun moteur nommé). Quand l'édition cache les surfaces de développement, aucun nom de moteur ni « Remotion Studio… » n'apparaît. En
   `full`, rien ne change.

   Tout texte d'auteur (titre) passe par `textContent`. Chaque échec est journalisé (`[presentation-rail] <clé> {json}`) et dit à l'écran. */
(function(root){
  'use strict';

  const DOM=Object.freeze({hostId:'presentationRail',styleId:'presentationRailStyle'});
  const ROUTE='/api/presentation-studio/rail';
  const STATE_ROUTE=ROUTE+'/display-state';
  const act=pid=>`/api/presentation-studio/presentations/${encodeURIComponent(pid)}/rail`;
  const payloadUrl=id=>`/api/artifacts/${encodeURIComponent(id)}/payload`;
  const ID_PRESENTATION=/^pst_[0-9a-f]{32}$/;
  const ID_ARTIFACT=/^[a-z][a-z0-9]*_[A-Za-z0-9_]{6,80}$/;
  const STORAGE_KEY='jarvis.presentationRail.v1';
  /* Le libellé accompagne TOUJOURS la pastille (la couleur ne porte jamais l'état seule) : long pour l'infobulle et l'ARIA, court à l'écran. */
  const STATE_LABEL=Object.freeze({working:'Un agent travaille dessus',problem:'Un problème est survenu',unreviewed:'Modifiée par Jarvis — à revoir',
    done:'Terminé',unknown:'État inconnu'});
  const STATE_SHORT=Object.freeze({working:'En cours',problem:'Problème',unreviewed:'À revoir',done:'Prête',unknown:'État inconnu'});
  /* Étape B : état d'un Artifact du Board (pas de jaune : aucun propriétaire canonique de « revu »). */
  const ITEM_STATE=Object.freeze({working:{state:'working',short:'En cours',label:'En cours d’acquisition'},ready:{state:'done',short:'Prêt',label:'Prêt'},
    problem:{state:'problem',short:'Problème',label:'Acquisition en échec ou partielle'},unknown:{state:'unknown',short:'État inconnu',label:'État inconnu'}});
  const WORKSPACE_REFRESH_MS=10000;
  const STATE_COLOR=Object.freeze({working:'var(--sem-working,#4da3ff)',problem:'var(--sem-problem,#ff6a4d)',unreviewed:'var(--sem-review,#ffd166)',
    done:'var(--sem-done,#68e0a0)',unknown:'transparent'});
  const ENGINE_LABEL=Object.freeze({remotion:'Remotion',slidecar:'Slidecar'});
  /* Slice 08 : création depuis l'accueil (route de Core relayée, la même que la carte « Présentations · moteur »). */
  const CREATE_ROUTE='/api/presentation-studio/presentations';
  const CREATE_TIMEOUT_MS=30000;
  const CREATE_ERRORS=Object.freeze({
    presentation_studio_limit_reached:'Le nombre maximal de présentations est atteint : archivez-en une, puis réessayez.',
    presentation_studio_storage_io:'Le disque a refusé l’écriture : rien n’a été créé.',
    presentation_studio_invalid:'Titre refusé : ',
    core_unreachable:'Jarvis ne répond pas : rien n’a été créé.',core_unconfigured:'Ce Control Center ne connaît pas Jarvis : rien n’a été créé.',
    network:'La connexion avec le Control Center a échoué : rien n’a été créé.',
  });
  /* Le parcours de l'accueil, dans l'ordre du travail (D13 : la retouche fine des scènes est l'affaire de Variantes et de l'inspecteur). */
  const JOURNEY=Object.freeze([
    Object.freeze({step:'sources',title:'Rassemblez vos sources',text:'Déposez fichiers, liens et notes dans le Dossier de ce Board.',action:'dossier',label:'Ouvrir le Dossier'}),
    Object.freeze({step:'create',title:'Créez la présentation',text:'Donnez-lui un titre : elle apparaît ici.',action:'create',label:'Nouvelle présentation'}),
    Object.freeze({step:'scenes',title:'Faites écrire les scènes',text:'Demandez à Jarvis, à la voix ou dans le chat, de les rédiger à partir de vos sources.',action:'chat',label:'Ouvrir le chat'}),
    Object.freeze({step:'review',title:'Relisez, présentez, exportez',text:'Ouvrez la présentation pour relire ses scènes, la présenter, puis en enregistrer une copie dans Documents.',action:null,label:null}),
  ]);
  const POLL_BUSY_MS=2000,POLL_IDLE_MS=4000,POLL_HIDDEN_MS=20000,REPORT_EVERY_MS=15000,REQUEST_TIMEOUT_MS=8000,NOTICE_MS=6000;
  const TITLE_SHORT=40;
  const STUDIO_WIDTH_PX=188;
  const SLIM_WIDTH_PX=72;
  const SLIM_BELOW_PX=1100;
  /* Sous cette largeur le rail devient un onglet (`--shell-rail-w` vaut 0) : un geste l'ouvre par-dessus la scène. */
  const DRAWER_BELOW_PX=701;
  /* Sous cette largeur le Studio garde tout l'écran : le rail se retire le temps du Studio (il revient à sa fermeture). */
  const HIDE_IN_STUDIO_BELOW_PX=900;

  function cleanLine(value,max){
    const text=String(value==null?'':value).replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]+/g,' ').replace(/\s+/g,' ').trim();
    return max&&text.length>max?text.slice(0,Math.max(1,max-1))+'…':text;
  }
  function monogram(title){
    const words=cleanLine(title,80).split(' ').filter(Boolean);
    const letters=words.length>1?words[0][0]+words[1][0]:(words[0]||'?').slice(0,2);
    return letters.toUpperCase();
  }
  function hueOf(id){let h=0;const s=String(id||'');for(let i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))>>>0;return h%360}
  /* L'état de TRAVAIL (Core, mémoire) : il décide de la visibilité automatique et de l'alarme. Absent ou illisible : `unknown`. */
  function stateOf(row){const s=row&&row.work&&row.work.state;return s==='working'||s==='problem'||s==='done'?s:'unknown'}
  /* L'état AFFICHÉ (D10) : working > problem > unreviewed > done ; `unknown` reste `unknown` (jamais repeint en vert ni en jaune). */
  function displayState(row){
    const s=stateOf(row);
    if(s==='working'||s==='problem'||s==='unknown')return s;
    return row&&row.unreviewed&&typeof row.unreviewed==='object'?'unreviewed':'done';
  }
  /* `opts.plain` (Slice 08, surfaces de développement cachées) : le moteur par défaut n'est pas nommé ; un autre moteur
     (Slidecar, expérimental) l'est encore, parce que la présentation se comporte autrement. */
  function typeOf(row,opts){
    const engine=row&&row.type&&typeof row.type.engine==='string'?row.type.engine:(row&&typeof row.engine==='string'?row.engine:null);
    const name=engine&&!(opts&&opts.plain&&engine==='remotion')&&ENGINE_LABEL[engine]||null;
    return {engine:name?engine:null,badge:name||'Présentation',label:name?`Présentation · ${name}`:'Présentation'};
  }
  /* « il y a 2 h » à partir d'un horodatage ISO de Core ; illisible ou futur lointain : rien (jamais une date inventée). */
  function ago(iso,nowMs){
    const t=Date.parse(String(iso||''));if(!Number.isFinite(t))return '';
    const s=Math.max(0,Math.round(((Number(nowMs)||Date.now())-t)/1000));
    if(s<60)return 'à l’instant';
    const m=Math.round(s/60);if(m<60)return `il y a ${m} min`;
    const h=Math.round(m/60);if(h<24)return `il y a ${h} h`;
    const d=Math.round(h/24);if(d<7)return `il y a ${d} j`;
    const w=Math.round(d/7);if(w<9)return `il y a ${w} sem.`;
    return `il y a ${Math.round(d/30)} mois`;
  }
  /* Aperçu : l'image d'un rendu complet que Core désigne (`preview`), sinon une vignette typée. Jamais un chemin, jamais une fausse diapositive. */
  function previewOf(row,opts){
    const p=row&&row.preview;
    if(p&&typeof p==='object'&&p.kind==='presentation_still'&&typeof p.artifact_id==='string'&&ID_ARTIFACT.test(p.artifact_id))
      return {kind:'image',url:payloadUrl(p.artifact_id),artifact_id:p.artifact_id,width:Number(p.width)||null,height:Number(p.height)||null};
    return {kind:'placeholder',label:typeOf(row,opts).label};
  }
  /* La carte, en données (pur, testé sous node) : ce que le DOM affiche, rien de plus. */
  function cardOf(row,nowMs,opts){
    const st=displayState(row),type=typeOf(row,opts),count=Number(row&&row.variant_count)||0;
    const when=ago(row&&row.updated_at,nowMs);
    return {id:row.presentation_id,title:cleanLine(row.title,80)||'Sans titre',short:cleanLine(row.title,TITLE_SHORT)||'Sans titre',
      state:st,stateShort:STATE_SHORT[st],stateLabel:STATE_LABEL[st],color:STATE_COLOR[st],type,preview:previewOf(row,opts),
      meta:[type.badge,count>1?`${count} variantes`:null].filter(Boolean).join(' · '),when};
  }

  /* Le modèle pur : trois groupes (visibles, masquées, archivées), l'état le plus pressant du rail, ce qui travaille. */
  function modelOf(rows,pref){
    const list=Array.isArray(rows)?rows.filter(r=>r&&typeof r.presentation_id==='string'&&ID_PRESENTATION.test(r.presentation_id)):[];
    const visible=list.filter(r=>!r.hidden&&!r.archived),hidden=list.filter(r=>r.hidden&&!r.archived),archived=list.filter(r=>r.archived);
    const live=list.filter(r=>!r.archived);
    const working=live.filter(r=>stateOf(r)==='working'),problems=live.filter(r=>stateOf(r)==='problem');
    const unreviewed=live.filter(r=>displayState(r)==='unreviewed');
    return {visible,hidden,archived,working,problems,unreviewed,total:list.length,pref:pref||'auto'};
  }
  /* Visible ? (pur) */
  function shouldShow(model,ctx){
    const c=ctx||{};
    if(c.pref==='hidden')return false;
    if(c.pref==='shown')return true;
    /* Slice 08 : l'accueil d'une édition produit (`c.home`) se montre vide dans un Board Présentation. */
    if(!model.total)return !!(c.home&&(c.boardKind==='presentation'||c.mode==='presentation'));
    return !!(c.boardKind==='presentation'||c.mode==='presentation'||model.working.length||model.problems.length||c.studioOpen);
  }
  /* Densité de la carte (pur) : `full` (300 px), `slim` (72 px : vignette, libellé au focus), `drawer` (onglet sous 700 px),
     `compact` (colonne à côté du Studio). */
  function densityOf(ctx){
    const c=ctx||{},w=Number(c.width)||1280;
    if(c.studio)return c.collapsed||w<SLIM_BELOW_PX?'slim':'compact';
    if(w<DRAWER_BELOW_PX)return 'drawer';
    return c.collapsed||w<SLIM_BELOW_PX?'slim':'full';
  }
  function menuModel(row,ctx){
    const c=ctx||{};
    if(row.archived)return [{act:'restore',label:'Restaurer'}];
    const items=[
      {act:'open',label:'Ouvrir les variantes',note:c.playing&&!c.playingThis?'Une autre présentation est en cours : Variantes la montre.':null},
      /* native-studio-playback-fix Slice 11 (§ 1): Variants on the active variant, then Remotion Studio on the scene on screen, after the confirmation. */
      /* Slice 08 : outil de développement, absent quand l'édition cache ces surfaces (`c.developer === false`). */
      ...(c.developer===false?[]:[{act:'studio',label:'Remotion Studio…',note:c.playing?'Une présentation est en cours : Remotion Studio s’ouvre à son arrêt.':null}]),
      {act:'edit',label:'Éditer',note:c.playing?'Une présentation est en cours : l’inspecteur est indisponible.':null},
      {act:'play',label:'Présenter',note:c.playing?'Une présentation est déjà en cours.':null},
      '-',
      {act:row.hidden?'show':'hide',label:row.hidden?'Afficher dans le rail':'Masquer dans le rail'},
      {act:'rename',label:'Renommer…'}];
    if(stateOf(row)==='problem')items.push({act:'ack',label:'Acquitter le problème'});
    if(row.unreviewed&&typeof row.unreviewed==='object')items.push({act:'review',label:'Marquer comme vu'});
    items.push('-',{act:'archive',label:'Supprimer…',danger:true,note:c.playingThis?'Cette présentation est jouée : arrêtez la lecture d’abord.':null});
    return items;
  }

  /* Pictogramme de la vignette typée (une présentation : un écran sur pied), dessiné, pas une image de diapositive. */
  /* Pictogrammes des vignettes typées, par famille (`WorkspaceRailItem.media_type`) ; une présentation : un écran sur pied. */
  const GLYPHS=Object.freeze({
    presentation:[['rect',{x:'3',y:'4',width:'18',height:'12',rx:'1.5'}],['path',{d:'M12 16v4M8 20h8M7 12l3-3 2 2 3-4 2 2'}]],
    video:[['rect',{x:'3',y:'5',width:'18',height:'14',rx:'2'}],['path',{d:'M10 9l5 3-5 3z'}]],
    document:[['path',{d:'M7 3h7l4 4v14H7z'}],['path',{d:'M14 3v4h4M9.5 12h6M9.5 15h6M9.5 18h4'}]],
    link:[['path',{d:'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1'}],['path',{d:'M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1'}]],
    image:[['rect',{x:'3',y:'4',width:'18',height:'16',rx:'2'}],['path',{d:'M3 16l5-5 4 4 3-3 6 6'}],['circle',{cx:'16',cy:'8.5',r:'1.5'}]]});
  const GLYPH_OF=Object.freeze({video:'video',audio:'video',pdf:'document',word:'document',excel:'document',table:'document',text:'document',archive:'document',
    file:'document',powerpoint:'presentation',google_slides:'presentation',google_docs:'document',google_sheets:'document',image:'image'});

  const CSS=`
#${DOM.hostId}{--jvr-ink:var(--text,#d8edf7);--jvr-mute:var(--muted,#7190a0);--jvr-line:var(--shell-stroke,rgba(174,205,220,.12));--jvr-bg:var(--shell-glass-strong,rgba(4,10,15,.8));--jvr-hot:var(--shell-stroke-active,rgba(110,231,255,.4));
  position:fixed;z-index:30;top:var(--shell-panel-top,64px);right:var(--shell-gutter,18px);width:var(--shell-rail-w,300px);max-height:calc(100vh - var(--shell-panel-top,64px) - var(--shell-panel-bottom,68px));
  display:flex;flex-direction:column;gap:6px;padding:10px 8px 8px;background:var(--jvr-bg);border:1px solid var(--jvr-line);border-radius:var(--shell-radius,12px);
  -webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);color:var(--jvr-ink);font:12px/1.35 system-ui,"Segoe UI",sans-serif;box-shadow:0 14px 40px rgba(0,0,0,.4);user-select:none}
#${DOM.hostId}[hidden]{display:none}
#${DOM.hostId} *{box-sizing:border-box}
#${DOM.hostId} button{font:inherit;color:inherit;cursor:pointer;background:none;border:0;padding:0}
#${DOM.hostId} .jvr-head{display:flex;align-items:center;gap:8px;padding:0 4px 2px;color:var(--jvr-mute);letter-spacing:.14em;font:600 10.5px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace}
#${DOM.hostId} .jvr-title{flex:1;min-width:0;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--jvr-ink)}
#${DOM.hostId} .jvr-count{color:var(--jvr-mute);font-weight:400}
#${DOM.hostId} .jvr-voice{flex:none;width:8px;height:8px;border-radius:50%;border:1px solid #5b7686;background:transparent}
#${DOM.hostId} .jvr-voice[data-v=listening]{background:#6ee7ff;border-color:#6ee7ff;box-shadow:0 0 6px #6ee7ff}#${DOM.hostId} .jvr-voice[data-v=speaking],#${DOM.hostId} .jvr-voice[data-v=thinking]{background:#a78bfa;border-color:#a78bfa;box-shadow:0 0 6px #a78bfa}
#${DOM.hostId} .jvr-voice[data-v="hors ligne"]{border-style:dashed;opacity:.6}
#${DOM.hostId} .jvr-tool{flex:none;width:24px;height:24px;border-radius:6px;color:var(--jvr-mute);display:grid;place-items:center;font-size:14px;letter-spacing:0}
#${DOM.hostId} .jvr-tool:hover,#${DOM.hostId} .jvr-tool[aria-pressed=true]{color:var(--jvr-ink);background:rgba(110,231,255,.12)}
#${DOM.hostId} .jvr-urgent{flex:none;width:8px;height:8px;border-radius:50%;background:var(--c);display:none}
#${DOM.hostId} .jvr-list{list-style:none;margin:0;padding:0 2px 0 0;overflow:auto;display:flex;flex-direction:column;gap:6px;min-height:0;scrollbar-width:thin}
#${DOM.hostId} .jvr-card{position:relative}
#${DOM.hostId} .jvr-item{display:grid;grid-template-columns:88px minmax(0,1fr);align-items:center;gap:10px;width:100%;min-height:62px;padding:6px 30px 6px 6px;border-radius:10px;text-align:left;
  background:rgba(255,255,255,.025);border:1px solid var(--jvr-line);transition:border-color var(--shell-dur-fast,120ms) var(--shell-ease,ease),background-color var(--shell-dur-fast,120ms) var(--shell-ease,ease)}
#${DOM.hostId} .jvr-item:hover{background:rgba(110,231,255,.06);border-color:var(--jvr-hot)}
#${DOM.hostId} .jvr-item:focus-visible{outline:var(--shell-focus-w,2px) solid var(--shell-focus,#6ee7ff);outline-offset:1px}
#${DOM.hostId} .jvr-item[data-open=true]{border-color:var(--jvr-hot);background:rgba(110,231,255,.09)}
#${DOM.hostId} .jvr-item[data-dim=true]{opacity:.55}
#${DOM.hostId} .jvr-thumb{position:relative;width:88px;aspect-ratio:16/9;border-radius:7px;overflow:hidden;display:grid;place-items:center;align-content:center;gap:2px;color:rgba(232,244,250,.86);
  background:linear-gradient(135deg,hsl(var(--h) 42% 24%),hsl(calc(var(--h) + 40) 38% 12%));border:1px solid rgba(255,255,255,.1)}
#${DOM.hostId} .jvr-thumb img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;background:#05090d}
#${DOM.hostId} .jvr-thumb[data-kind=placeholder] .jvr-ph{font:600 8.5px/1 ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.08em;text-transform:uppercase;opacity:.82}
#${DOM.hostId} .jvr-badge{position:absolute;left:4px;bottom:4px;padding:2px 4px;border-radius:4px;background:rgba(2,6,9,.74);color:#e8f4fa;font:600 8.5px/1 ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.06em;text-transform:uppercase}
#${DOM.hostId} .jvr-thumb[data-kind=placeholder] .jvr-badge{display:none}
#${DOM.hostId} .jvr-body{min-width:0;display:flex;flex-direction:column;gap:3px}
#${DOM.hostId} .jvr-name{font-size:13px;font-weight:600;line-height:1.25;color:var(--jvr-ink);overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
#${DOM.hostId} .jvr-meta{color:var(--jvr-mute);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#${DOM.hostId} .jvr-status{display:flex;align-items:center;gap:6px;min-width:0;font-size:11px;white-space:nowrap}
#${DOM.hostId} .jvr-state{color:color-mix(in srgb,var(--c) 72%,var(--jvr-ink));font-weight:600}
#${DOM.hostId} .jvr-item[data-state=unknown] .jvr-state{color:var(--jvr-mute)}
#${DOM.hostId} .jvr-when{color:var(--jvr-mute);overflow:hidden;text-overflow:ellipsis}
#${DOM.hostId} .jvr-dot{flex:0 0 auto;width:8px;height:8px;border-radius:50%;background:var(--c);box-shadow:0 0 0 2px rgba(0,0,0,.35)}
/* A shape per state (status never by colour alone, also in the 72 px strip where the label hides): working = ring (pulsing), problem =
   triangle, unreviewed = diamond, done = check, unknown = dashed hollow ring. Same rules for the header's « most urgent » mark and the bubble. */
#${DOM.hostId} :is([data-state=working] .jvr-dot,.jvr-urgent[data-state=working]){-webkit-mask:radial-gradient(circle,transparent 2px,#000 2.6px);mask:radial-gradient(circle,transparent 2px,#000 2.6px);box-shadow:none}
#${DOM.hostId} .jvr-item[data-state=working] .jvr-dot{animation:jvr-pulse 1.3s ease-in-out infinite}
#${DOM.hostId} :is([data-state=problem] .jvr-dot,.jvr-urgent[data-state=problem]){width:10px;height:9px;border-radius:1px;clip-path:polygon(50% 0,100% 100%,0 100%);box-shadow:none}
#${DOM.hostId} :is([data-state=unreviewed] .jvr-dot,.jvr-urgent[data-state=unreviewed]){width:9px;height:9px;border-radius:1px;clip-path:polygon(50% 0,100% 50%,50% 100%,0 50%);box-shadow:none}
#${DOM.hostId} :is([data-state=done] .jvr-dot,.jvr-urgent[data-state=done]){width:10px;height:9px;border-radius:0;clip-path:polygon(0 52%,16% 36%,40% 60%,84% 8%,100% 24%,40% 94%);box-shadow:none}
#${DOM.hostId} [data-state=unknown] .jvr-dot{border:1px dashed var(--jvr-mute);box-shadow:none}
#${DOM.hostId} .jvr-item[data-state=problem]{border-color:color-mix(in srgb,var(--sem-problem,#ff6a4d) 45%,transparent)}
@keyframes jvr-pulse{50%{opacity:.35;transform:scale(.8)}}
@media (prefers-reduced-motion:reduce){#${DOM.hostId} .jvr-item[data-state=working] .jvr-dot{animation:none}#${DOM.hostId} .jvr-item{transition:none}}
#${DOM.hostId} .jvr-more{position:absolute;top:6px;right:4px;width:24px;height:24px;border-radius:6px;display:grid;place-items:center;color:var(--jvr-mute);font-size:15px;line-height:1}
#${DOM.hostId} .jvr-more:hover,#${DOM.hostId} .jvr-more:focus-visible{color:var(--jvr-ink);background:rgba(110,231,255,.12)}
#${DOM.hostId} .jvr-fold{display:flex;align-items:center;gap:6px;padding:6px 6px 2px;color:var(--jvr-mute);font:600 10px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.1em;text-transform:uppercase;text-align:left;width:100%;border-top:1px solid var(--jvr-line);margin-top:2px}
#${DOM.hostId} .jvr-fold:hover{color:var(--jvr-ink)}
#${DOM.hostId} .jvr-fold + .jvr-list{margin-top:6px}
#${DOM.hostId} .jvr-ws{display:flex;flex-direction:column;min-height:0;flex:0 1 auto;max-height:42vh}
#${DOM.hostId} .jvr-ws>.jvr-list{overflow:auto;min-height:0}
#${DOM.hostId} .jvr-ws:empty{display:none}
#${DOM.hostId} .jvr-ws .jvr-empty[data-kind=failed]{color:var(--sem-alert,#ff9f43)}
#${DOM.hostId} .jvr-ws .jvr-thumb{--h:200}
#${DOM.hostId} .jvr-empty,#${DOM.hostId} .jvr-note{padding:6px;color:var(--jvr-mute);font-size:11.5px;line-height:1.4}
#${DOM.hostId} .jvr-note[data-kind=failed]{color:var(--sem-alert,#ff9f43)}
#${DOM.hostId} .jvr-peek{position:absolute;right:calc(100% + 8px);top:0;width:220px;padding:8px 10px;border-radius:9px;background:var(--panel,rgba(6,12,18,.96));border:1px solid var(--jvr-hot);box-shadow:0 10px 30px rgba(0,0,0,.45);
  transform:translateY(-50%);pointer-events:none;display:flex;flex-direction:column;gap:3px}
#${DOM.hostId} .jvr-peek[hidden]{display:none}
#${DOM.hostId}[data-density=slim]{width:${SLIM_WIDTH_PX}px;padding:8px 6px}
#${DOM.hostId}[data-density=slim] .jvr-title,#${DOM.hostId}[data-density=slim] .jvr-voice,#${DOM.hostId}[data-density=slim] .jvr-fold span+span{display:none}
#${DOM.hostId}[data-density=slim] .jvr-head{justify-content:center;padding:0}
#${DOM.hostId}[data-density=slim] .jvr-item,#${DOM.hostId}[data-density=compact] .jvr-item{grid-template-columns:minmax(0,1fr);min-height:0;padding:4px;gap:6px}
#${DOM.hostId}[data-density=slim] .jvr-thumb{width:100%}
#${DOM.hostId}[data-density=slim] .jvr-body{position:absolute;top:7px;right:7px}
#${DOM.hostId}[data-density=slim] .jvr-list :is(.jvr-name,.jvr-meta,.jvr-state,.jvr-when,.jvr-more,.jvr-badge,.jvr-ph){display:none}
#${DOM.hostId}[data-density=compact] .jvr-item{grid-template-columns:44px minmax(0,1fr);padding:4px 6px 4px 4px;gap:8px}
#${DOM.hostId}[data-density=compact] .jvr-thumb{width:44px}
#${DOM.hostId}[data-density=compact] .jvr-thumb .jvr-ph,#${DOM.hostId}[data-density=compact] .jvr-thumb svg,#${DOM.hostId}[data-density=compact] .jvr-badge,#${DOM.hostId}[data-density=compact] .jvr-meta,#${DOM.hostId}[data-density=compact] .jvr-when,#${DOM.hostId}[data-density=compact] .jvr-more{display:none}
#${DOM.hostId}[data-density=compact] .jvr-name{font-size:12px;-webkit-line-clamp:1}
#${DOM.hostId}[data-density=drawer]{width:auto;max-width:calc(100vw - 2 * var(--shell-gutter,10px));padding:6px 8px}
#${DOM.hostId}[data-density=drawer][data-drawer=open]{width:min(300px,calc(100vw - 2 * var(--shell-gutter,10px)));padding:10px 8px 8px}
#${DOM.hostId}[data-density=drawer]:not([data-drawer=open]) .jvr-list,#${DOM.hostId}[data-density=drawer]:not([data-drawer=open]) .jvr-folds,#${DOM.hostId}[data-density=drawer]:not([data-drawer=open]) .jvr-ws,#${DOM.hostId}[data-density=drawer]:not([data-drawer=open]) .jvr-note{display:none}
#${DOM.hostId}[data-density=drawer]:not([data-drawer=open]) .jvr-urgent{display:block}
html.jvr-studio #${DOM.hostId}{z-index:9100;top:8px;right:8px;left:auto;bottom:8px;max-height:none;width:${STUDIO_WIDTH_PX-16}px;background:rgba(3,8,12,.92)}
html.jvr-studio #${DOM.hostId} .jvr-list{flex:1 1 auto}
/* Colonne du Studio (156 px utiles) : le titre se resserre et passe à la ligne au besoin, il ne se coupe plus en « PRÉSENTATION… » (QA S09 P7). */
html.jvr-studio #${DOM.hostId} .jvr-head{letter-spacing:.04em}
html.jvr-studio #${DOM.hostId} .jvr-title{white-space:normal}
html.jvr-studio #jvStudioExplorer:not(:fullscreen){right:${STUDIO_WIDTH_PX}px}
html.jvr-studio.jvr-slim #jvStudioExplorer:not(:fullscreen){right:60px}
html.jvr-studio.jvr-slim #${DOM.hostId}{width:44px;padding:8px 4px}
@media (forced-colors:active){#${DOM.hostId} .jvr-item{border-color:CanvasText}#${DOM.hostId} .jvr-dot{forced-color-adjust:none}}
.jvr-menu{position:fixed;z-index:9300;min-width:190px;padding:5px;background:rgba(6,12,18,.97);border:1px solid rgba(110,231,255,.28);border-radius:9px;box-shadow:0 14px 40px rgba(0,0,0,.55);
  color:#d8edf7;font:12px ui-monospace,SFMono-Regular,Consolas,monospace}
.jvr-menu[hidden]{display:none}
.jvr-menu .jvr-mhead{padding:4px 8px 6px;color:#7190a0;font-size:10px;letter-spacing:.12em;text-transform:uppercase;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.jvr-menu button{display:block;width:100%;text-align:left;padding:6px 8px;border-radius:6px;background:none;border:0;color:inherit;font:inherit;cursor:pointer}
.jvr-menu button:hover,.jvr-menu button:focus-visible{background:rgba(110,231,255,.14);outline:0}
.jvr-menu button[data-danger]{color:#ff8a98}.jvr-menu button[aria-disabled=true]{opacity:.45;cursor:default}
.jvr-menu .jvr-sep{height:1px;margin:4px 2px;background:rgba(110,231,255,.16)}
.jvr-dialog-back{position:fixed;inset:0;z-index:9400;background:rgba(0,0,0,.5);display:grid;place-items:center}
.jvr-dialog-back[hidden]{display:none}
.jvr-dialog{width:min(420px,calc(100vw - 32px));padding:16px;background:#070d13;border:1px solid rgba(110,231,255,.3);border-radius:12px;color:#d8edf7;font:13px ui-monospace,SFMono-Regular,Consolas,monospace;box-shadow:0 20px 60px rgba(0,0,0,.6)}
.jvr-dialog h2{margin:0 0 8px;font-size:14px;font-weight:700}.jvr-dialog p{margin:0 0 12px;color:#9db6c4;line-height:1.45}
.jvr-dialog input{width:100%;padding:8px 10px;margin-bottom:12px;background:#04080c;border:1px solid rgba(110,231,255,.28);border-radius:7px;color:inherit;font:inherit}
.jvr-dialog .jvr-row{display:flex;gap:8px;justify-content:flex-end}
.jvr-dialog button{padding:7px 12px;border-radius:7px;background:rgba(110,231,255,.1);border:1px solid rgba(110,231,255,.3);color:inherit;font:inherit;cursor:pointer}
.jvr-dialog button[data-danger]{background:rgba(255,101,119,.14);border-color:rgba(255,101,119,.5);color:#ff9aa6}
/* Slice 08 : accueil d'une édition produit — bouton « Nouvelle présentation » et parcours en quatre étapes. */
#${DOM.hostId} .jvr-new{display:inline-flex;align-items:center;gap:6px;margin-left:auto;padding:5px 10px;border:1px solid color-mix(in srgb,var(--accent,#6ee7ff) 45%,transparent);border-radius:999px;
  background:color-mix(in srgb,var(--accent,#6ee7ff) 10%,transparent);color:var(--accent,#6ee7ff);font:600 11px/1.1 inherit;letter-spacing:.02em;cursor:pointer;white-space:nowrap}
#${DOM.hostId} .jvr-new svg{width:13px;height:13px;flex:none}
#${DOM.hostId} .jvr-new:hover:not([aria-disabled=true]){background:color-mix(in srgb,var(--accent,#6ee7ff) 18%,transparent)}
#${DOM.hostId} .jvr-new[aria-disabled=true]{opacity:.55;cursor:progress}
#${DOM.hostId} .jvr-new:focus-visible{outline:var(--shell-focus-w,2px) solid var(--shell-focus,#6ee7ff);outline-offset:var(--shell-focus-offset,2px)}
#${DOM.hostId}[data-density=slim] .jvr-new span,#${DOM.hostId}[data-density=compact] .jvr-new span{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
#${DOM.hostId}[data-density=slim] .jvr-new,#${DOM.hostId}[data-density=compact] .jvr-new{padding:5px;margin-left:0}
#${DOM.hostId} .jvr-home{list-style:none;margin:0;padding:6px 4px 4px;display:grid;gap:10px;counter-reset:jvr-step}
#${DOM.hostId} .jvr-home-title{margin:2px 4px 0;color:var(--jvr-ink);font:600 13px/1.3 inherit;letter-spacing:.01em}
#${DOM.hostId} .jvr-step{counter-increment:jvr-step;display:grid;grid-template-columns:22px 1fr;gap:2px 9px;align-items:start}
#${DOM.hostId} .jvr-step::before{content:counter(jvr-step);grid-row:span 3;display:grid;place-items:center;width:22px;height:22px;border-radius:50%;
  border:1px solid var(--jvr-hot);color:var(--accent,#6ee7ff);font:600 11px/1 inherit}
#${DOM.hostId} .jvr-step strong{color:var(--jvr-ink);font:600 12px/1.35 inherit}
#${DOM.hostId} .jvr-step p{margin:0;color:var(--jvr-mute);font-size:11.5px;line-height:1.45}
#${DOM.hostId} .jvr-step button{justify-self:start;margin-top:4px;padding:4px 10px;border:1px solid var(--jvr-line);border-radius:999px;background:none;color:var(--jvr-ink);font:inherit;font-size:11.5px;cursor:pointer}
#${DOM.hostId} .jvr-step button:hover{border-color:var(--jvr-hot)}
#${DOM.hostId} .jvr-step button:focus-visible{outline:var(--shell-focus-w,2px) solid var(--shell-focus,#6ee7ff);outline-offset:var(--shell-focus-offset,2px)}
#${DOM.hostId} .jvr-homebox[hidden],#${DOM.hostId}[data-density=slim] .jvr-homebox,#${DOM.hostId}[data-density=compact] .jvr-homebox{display:none}
#${DOM.hostId} .jvr-list[hidden]{display:none}
@media (prefers-reduced-motion:reduce){#${DOM.hostId} .jvr-new{transition:none}}
`;

  function createRail(deps){
    const d=deps||{};
    const doc=d.document||root.document;
    const win=d.window||root;
    const fetchImpl=d.fetch||(typeof root.fetch==='function'?root.fetch.bind(root):null);
    const later=d.setTimeout||((fn,ms)=>setTimeout(fn,ms));
    const cancelLater=d.clearTimeout||(id=>clearTimeout(id));
    const now=d.now||(()=>Date.now());
    const sink=d.console||root.console;
    /* Slice 08 : l'édition (lue sur Core par `JarvisProductEdition`). Absente : comportement d'avant (pas d'accueil, moteurs nommés). */
    const edition=d.edition!==undefined?d.edition:(root.JarvisProductEdition&&root.JarvisProductEdition.instance||null);
    const editionModel=()=>{try{const v=edition&&typeof edition.state==='function'?edition.state():null;return v&&v.model||null}catch(_e){return null /* intentional: no edition = previous behaviour */}};
    /* Accueil produit : l'édition lue n'est pas `full`. Surfaces de développement : le marquage confirmé par Core. */
    const home=()=>{const m=editionModel();return !!(m&&m.edition!=='full')};
    const developer=()=>{try{return !(edition&&typeof edition.developerSurfacesShown==='function')||edition.developerSurfacesShown()}catch(_e){return true /* intentional */}};
    const S={coreOk:false,rows:[],loaded:false,lost:false,pref:'auto',collapsed:false,drawer:false,density:'full',boardKind:null,boardId:null,mode:null,voice:'idle',foldHidden:false,foldArchived:false,foldWorkspace:false,
      lastSeq:null,firstPoll:true,studioOpen:false,notice:null,busy:new Set(),playing:null,selected:null,menuRow:null,dialog:null,lastReport:'',lastReportAt:0};
    const ui={};
    let pollTimer=null,reportTimer=null,noticeTimer=null,polling=false,destroyed=false,failures=0;
    const brokenPreviews=new Set();
    /* Étape B : la source des Artifacts du Board actif (adaptateur pur, injecté ou lu sur la page). Absente : le rail reste celui des présentations. */
    const wsModel=d.workspaceModel||root.JarvisWorkspaceRailModel||null;
    const ws=wsModel&&typeof wsModel.createSource==='function'?wsModel.createSource({fetch:fetchImpl,onChange:()=>{if(ui.host)render()},log:(key,data,level)=>log(key,data,level)}):null;

    function storage(){try{return d.storage||root.localStorage||null}catch(_e){return null /* intentional: blocked storage only costs the remembered layout */}}
    function load(){
      try{const raw=storage()&&storage().getItem(STORAGE_KEY);if(!raw)return;const v=JSON.parse(raw);
        if(v&&(v.pref==='auto'||v.pref==='shown'||v.pref==='hidden'))S.pref=v.pref;
        if(v&&typeof v.collapsed==='boolean')S.collapsed=v.collapsed;
        if(v&&typeof v.foldHidden==='boolean')S.foldHidden=v.foldHidden;if(v&&typeof v.foldArchived==='boolean')S.foldArchived=v.foldArchived;
        if(v&&typeof v.foldWorkspace==='boolean')S.foldWorkspace=v.foldWorkspace}
      catch(_e){/* intentional: corrupt remembered layout -> defaults */}
    }
    function save(){try{if(storage())storage().setItem(STORAGE_KEY,JSON.stringify({pref:S.pref,collapsed:S.collapsed,foldHidden:S.foldHidden,foldArchived:S.foldArchived,foldWorkspace:S.foldWorkspace}))}catch(_e){/* intentional */}}
    function log(key,data,level){
      const line=`[presentation-rail] ${key} ${JSON.stringify(data||{})}`;
      try{if(sink){if(level==='error')sink.error(line);else if(level==='warn')sink.warn(line);else sink.info(line)}}catch(_e){/* intentional */}
    }
    function el(tag,cls,text){const n=doc.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n}
    function clear(n){while(n.firstChild)n.removeChild(n.firstChild)}

    async function call(method,path,body,timeoutMs){
      if(!fetchImpl)throw Object.assign(new Error('fetch indisponible'),{code:'network'});
      const controller=typeof AbortController==='function'?new AbortController():null;
      let timedOut=false;const timer=later(()=>{timedOut=true;if(controller)controller.abort()},timeoutMs||REQUEST_TIMEOUT_MS);
      try{
        const init={method,cache:'no-store'};if(controller)init.signal=controller.signal;
        if(body!==undefined){init.body=JSON.stringify(body);init.headers={'Content-Type':'application/json'}}
        const response=await fetchImpl(path,init);
        let payload=null;try{payload=await response.json()}catch(_e){payload=null /* intentional: reported by status below */}
        if(!response.ok){const e=payload&&payload.error||{};throw Object.assign(new Error(e.message||(payload&&typeof payload.error==='string'?payload.error:`HTTP ${response.status}`)),{status:response.status,code:e.code||`http_${response.status}`})}
        return payload;
      }catch(error){
        if(error&&error.code)throw error;
        throw Object.assign(new Error(timedOut?'aucune réponse à temps':String(error&&error.message||error)),{code:timedOut?'timeout':'network'});
      }finally{cancelLater(timer)}
    }

    /* ------------------------------------------------------------ Variantes, lecture, inspecteur : les voisins, lus à la demande */
    const explorerApi=()=>d.explorer||root.JarvisStudioExplorer||null;
    const playerApi=()=>d.player||root.JarvisStudioPlayer||null;
    const inspectorApi=()=>d.inspector||(root.JarvisStudioInspector&&root.JarvisStudioInspector.instance)||null;
    /* The presentation Variants shows, when it is open (the retired window host's `pid`, Slice 09). */
    function variantsPid(){
      const ex=explorerApi();
      try{return ex&&typeof ex.isOpen==='function'&&ex.isOpen()&&typeof ex.state==='function'?ex.state().presentation_id||null:null}
      catch(_error){return null /* intentional: an explorer that cannot answer shows nothing to the rail */}
    }
    function runActive(){
      const p=playerApi(),v=p&&typeof p.view==='function'?p.view():null;
      return !!v&&v.running===true&&v.phase!=='stopped'&&v.phase!=='idle';
    }
    function playingId(){const v=playerApi()&&typeof playerApi().view==='function'?playerApi().view():null;return v&&v.running===true&&v.presentation_id?v.presentation_id:null}

    /* ------------------------------------------------------------ rendu */
    function model(){return modelOf(S.rows,S.pref)}
    function shown(){
      if(S.studioOpen&&(Number(win.innerWidth)||1280)<HIDE_IN_STUDIO_BELOW_PX&&S.pref!=='shown')return false;
      return shouldShow(model(),{pref:S.pref,boardKind:S.boardKind,mode:S.mode,studioOpen:S.studioOpen,home:home()})}
    function build(){
      if(ui.host)return ui.host;
      if(!doc.getElementById(DOM.styleId)){const style=el('style');style.id=DOM.styleId;style.textContent=CSS;(doc.head||doc.documentElement).appendChild(style)}
      const host=doc.getElementById(DOM.hostId)||(()=>{const n=el('div');n.id=DOM.hostId;doc.body.appendChild(n);return n})();
      /* Une commande de la coque : la scène la mesure (docs/control-center-shell.md › Controls). */
      host.setAttribute('data-shell-control','');
      host.hidden=true;host.setAttribute('role','navigation');host.setAttribute('aria-label','Présentations');host.setAttribute('data-keep-live','true');
      const head=el('div','jvr-head');
      ui.title=el('span','jvr-title','Présentations');ui.count=el('span','jvr-count','');
      ui.title.append(' ',ui.count);
      ui.urgent=el('span','jvr-urgent');ui.urgent.setAttribute('aria-hidden','true');
      ui.voice=el('span','jvr-voice');ui.voice.setAttribute('role','status');
      ui.collapseBtn=el('button','jvr-tool','›');ui.collapseBtn.type='button';
      /* Sous 700 px le bouton ouvre ou ferme l'onglet ; au-dessus il replie le rail en bande de vignettes (72 px). */
      ui.collapseBtn.addEventListener('click',()=>{if(S.density==='drawer')S.drawer=!S.drawer;else{S.collapsed=!S.collapsed;save()}render()});
      /* Slice 08 : « Nouvelle présentation », montré par `render` quand l'édition est une édition produit. */
      ui.newBtn=el('button','jvr-new');ui.newBtn.type='button';ui.newBtn.hidden=true;ui.newBtn.setAttribute('aria-label','Nouvelle présentation');ui.newBtn.title='Nouvelle présentation';
      ui.newBtn.append(svgIcon([['path',{d:'M12 5v14M5 12h14'}]]),el('span','','Nouvelle'));
      ui.newBtn.addEventListener('click',()=>{createPresentation('head')});
      head.append(ui.title,ui.urgent,ui.voice,ui.newBtn,ui.collapseBtn);
      ui.list=el('ul','jvr-list');ui.list.setAttribute('role','listbox');ui.list.setAttribute('aria-label','Présentations');
      ui.folds=el('div','jvr-folds');ui.hiddenFold=el('div');ui.archivedFold=el('div');ui.folds.append(ui.hiddenFold,ui.archivedFold);
      ui.note=el('div','jvr-note');ui.note.setAttribute('role','status');ui.note.setAttribute('aria-live','polite');
      ui.note.addEventListener('click',()=>{if(S.notice){S.notice=null;render()}});
      /* Bande de vignettes : le titre et l'état d'une carte s'affichent à côté d'elle au survol et au focus (une seule bulle, hors de la liste
         qui défile, pour ne pas être rognée). */
      ui.peek=el('div','jvr-peek');ui.peek.hidden=true;ui.peek.setAttribute('aria-hidden','true');
      ui.ws=el('div','jvr-ws');ui.ws.setAttribute('role','group');ui.ws.setAttribute('aria-label','Sur ce Board');
      ui.home=el('div','jvr-homebox');ui.home.hidden=true;ui.home.setAttribute('role','group');ui.home.setAttribute('aria-label','Accueil des présentations');
      host.append(head,ui.list,ui.home,ui.ws,ui.folds,ui.note,ui.peek);
      const peekOn=event=>{const item=event.target&&event.target.closest&&event.target.closest('.jvr-item');if(item&&S.density==='slim')showPeek(item);else hidePeek()};
      host.addEventListener('focusin',peekOn);host.addEventListener('mouseover',peekOn);
      host.addEventListener('focusout',()=>hidePeek());host.addEventListener('mouseleave',()=>hidePeek());
      ui.menu=el('div','jvr-menu');ui.menu.hidden=true;ui.menu.setAttribute('role','menu');ui.menu.setAttribute('data-keep-live','true');
      ui.back=el('div','jvr-dialog-back');ui.back.hidden=true;ui.back.setAttribute('data-keep-live','true');
      doc.body.append(ui.menu,ui.back);
      host.addEventListener('keydown',onKey);
      ui.menu.addEventListener('keydown',onMenuKey);
      ui.menu.addEventListener('mousedown',e=>e.preventDefault());
      doc.addEventListener('mousedown',e=>{if(S.menuRow&&!ui.menu.contains(e.target))closeMenu(false)},true);
      ui.host=host;
      return host;
    }
    function itemFor(row,opts){
      const card=cardOf(row,now(),{plain:!developer()});
      const li=el('li','jvr-card');li.setAttribute('role','none');
      const b=el('button','jvr-item');b.type='button';b.setAttribute('role','option');b.dataset.id=row.presentation_id;
      b.dataset.state=card.state;b.style.setProperty('--c',card.color);
      const open=variantsPid()===row.presentation_id;
      b.dataset.open=String(open);b.setAttribute('aria-selected',String(open));
      if(opts&&opts.dim)b.dataset.dim='true';
      b.append(thumbFor(row,card));
      const body=el('span','jvr-body');
      const name=el('span','jvr-name',card.short);name.setAttribute('dir','auto');
      const meta=el('span','jvr-meta',card.meta);
      const status=el('span','jvr-status');
      const dot=el('span','jvr-dot');dot.setAttribute('aria-hidden','true');
      status.append(dot,el('span','jvr-state',card.stateShort));
      if(card.when)status.append(el('span','jvr-when',`· ${card.when}`));
      body.append(name,meta,status);b.append(body);
      const detail=card.state==='problem'&&row.work&&row.work.message?` — ${cleanLine(row.work.message,120)}`:'';
      b.title=`${card.title}\n${card.meta}\n${card.stateLabel}${detail}${card.when?`\nModifiée ${card.when}`:''}${row.hidden?'\nMasquée du rail':''}${row.archived?'\nArchivée (restaurable)':''}`;
      b.setAttribute('aria-label',`${card.title}, ${card.type.label} : ${card.stateLabel.toLowerCase()}${row.hidden?', masquée':''}${row.archived?', archivée':''}`);
      b.addEventListener('click',()=>{if(row.archived){openMenuFor(row,b);return}openRow(row.presentation_id,'click')});
      b.addEventListener('contextmenu',e=>{e.preventDefault();openMenuFor(row,b,e.clientX,e.clientY)});
      /* « ⋯ » : le même menu, pour la souris et la main ; le clavier a déjà Menu / Maj+F10 (pas de seconde tabulation par carte).
         Caché de l'arbre d'accessibilité (orbital-ui Slice 09, axe-core) : une liste d'options ne contient que des options, et
         l'option porte déjà le menu (Menu, Maj+F10, clic droit). */
      const more=el('button','jvr-more','⋯');more.type='button';more.tabIndex=-1;more.setAttribute('aria-hidden','true');more.title='Actions';
      more.addEventListener('click',e=>{e.stopPropagation();openMenuFor(row,b)});
      li.append(b,more);return li;
    }
    /* Vignette : l'image du dernier rendu complet (route bornée de Core) ou la vignette typée. Une image qui ne se charge pas retombe sur la
       vignette typée, une fois, et le dit au journal (jamais un cadre vide ni une image cassée). */
    function thumbFor(row,card){
      const thumb=el('span','jvr-thumb');thumb.setAttribute('aria-hidden','true');thumb.style.setProperty('--h',String(hueOf(row.presentation_id)));
      const p=card.preview;
      if(p.kind==='image'&&!brokenPreviews.has(p.artifact_id)){
        thumb.dataset.kind='image';
        const img=el('img');img.alt='';img.loading='lazy';img.decoding='async';img.draggable=false;
        if(p.width&&p.height){img.width=p.width;img.height=p.height}
        img.addEventListener('error',()=>{
          if(brokenPreviews.has(p.artifact_id))return;
          brokenPreviews.add(p.artifact_id);
          log('preview_failed',{presentation_id:row.presentation_id.slice(0,12),artifact_id:p.artifact_id},'warn');
          thumb.replaceWith(thumbFor(row,{...card,preview:{kind:'placeholder',label:card.type.label}}));
        },{once:true});
        img.src=p.url;
        thumb.append(img,el('span','jvr-badge',card.type.badge));
      }else{
        thumb.dataset.kind='placeholder';
        thumb.append(glyph('presentation'),el('span','jvr-ph',card.type.badge),el('span','jvr-badge',card.type.badge));
      }
      return thumb;
    }
    function glyph(kind){
      const NS='http://www.w3.org/2000/svg',svg=doc.createElementNS(NS,'svg');
      for(const [k,v] of [['viewBox','0 0 24 24'],['width','22'],['height','22'],['fill','none'],['stroke','currentColor'],['stroke-width','1.6'],['stroke-linecap','round'],['stroke-linejoin','round'],['aria-hidden','true']])svg.setAttribute(k,v);
      for(const [tag,attrs] of GLYPHS[kind]||GLYPHS.presentation){const n=doc.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);svg.appendChild(n)}
      return svg;
    }
    function showPeek(item){
      const wsItem=item.dataset.ws?wsItemOf(item.dataset.id):null;
      const row=wsItem?null:rowOf(item.dataset.id);if((!row&&!wsItem)||!ui.peek)return;
      const card=wsItem?wsCardOf(wsItem):cardOf(row,now());
      clear(ui.peek);
      const status=el('span','jvr-status');status.style.setProperty('--c',card.color);status.dataset.state=card.state;
      const dot=el('span','jvr-dot');status.append(dot,el('span','jvr-state',card.stateShort));
      ui.peek.append(el('span','jvr-name',card.title),el('span','jvr-meta',card.meta),status);
      const h=ui.host.getBoundingClientRect(),r=item.getBoundingClientRect();
      ui.peek.style.top=`${Math.round(r.top-h.top+r.height/2)}px`;ui.peek.hidden=false;
    }
    function hidePeek(){if(ui.peek&&!ui.peek.hidden){ui.peek.hidden=true;clear(ui.peek)}}
    /* ------------------------------------------------------------ étape B : Artifacts du Board actif */
    const wsItemOf=id=>ws?ws.view().items.find(i=>i.id===id)||null:null;
    function wsCardOf(item){
      const st=ITEM_STATE[item.activity_state]||ITEM_STATE.unknown;
      const when=ago(item.updated_at,now());
      return {title:item.title,short:cleanLine(item.title,TITLE_SHORT),state:st.state,stateShort:st.short,stateLabel:st.label,color:STATE_COLOR[st.state],
        meta:item.type.badge,when,type:{badge:item.type.badge,label:item.type.badge}};
    }
    function wsThumb(item,card){
      const thumb=el('span','jvr-thumb');thumb.setAttribute('aria-hidden','true');
      if(item.preview.kind==='image'&&!brokenPreviews.has(item.id)){
        thumb.dataset.kind='image';
        const img=el('img');img.alt='';img.loading='lazy';img.decoding='async';img.draggable=false;
        img.addEventListener('error',()=>{
          if(brokenPreviews.has(item.id))return;
          brokenPreviews.add(item.id);
          log('preview_failed',{artifact_id:item.id,kind:item.artifact_kind},'warn');
          thumb.replaceWith(wsThumb({...item,preview:{kind:'placeholder',label:card.type.badge}},card));
        },{once:true});
        img.src=item.preview.url;
        thumb.append(img,el('span','jvr-badge',card.type.badge));
      }else{
        thumb.dataset.kind='placeholder';
        thumb.dataset.media=item.media_type;
        thumb.append(glyph(GLYPH_OF[item.media_type]||(item.artifact_kind==='link'?'link':'document')),el('span','jvr-ph',card.type.badge),el('span','jvr-badge',card.type.badge));
      }
      return thumb;
    }
    function wsCardFor(item){
      const card=wsCardOf(item);
      const li=el('li','jvr-card');li.setAttribute('role','none');
      const b=el('button','jvr-item');b.type='button';b.setAttribute('role','option');b.dataset.id=item.id;b.dataset.ws=item.artifact_kind;
      b.dataset.state=card.state;b.style.setProperty('--c',card.color);b.setAttribute('aria-selected','false');
      b.append(wsThumb(item,card));
      const body=el('span','jvr-body');
      const name=el('span','jvr-name',card.short);name.setAttribute('dir','auto');
      const status=el('span','jvr-status');const dot=el('span','jvr-dot');dot.setAttribute('aria-hidden','true');
      status.append(dot,el('span','jvr-state',card.stateShort));
      if(card.when)status.append(el('span','jvr-when',`· ${card.when}`));
      body.append(name,el('span','jvr-meta',card.meta),status);b.append(body);
      b.title=`${card.title}\n${card.meta}\n${card.stateLabel}${card.when?`\nAjouté ${card.when}`:''}`;
      b.setAttribute('aria-label',`${card.title}, ${card.meta} : ${card.stateLabel.toLowerCase()}`);
      b.addEventListener('click',()=>openWsItem(item,'click'));
      b.addEventListener('contextmenu',e=>{e.preventDefault();openWsMenu(item,b,e.clientX,e.clientY)});
      const more=el('button','jvr-more','⋯');more.type='button';more.tabIndex=-1;more.setAttribute('aria-hidden','true');more.title='Actions';
      more.addEventListener('click',e=>{e.stopPropagation();openWsMenu(item,b)});
      li.append(b,more);return li;
    }
    function renderWorkspace(){
      clear(ui.ws);
      if(!ws)return;
      const v=ws.view();
      if(!v.boardId||(v.status==='ready'&&!v.items.length)||v.status==='idle')return;
      ui.ws.appendChild(foldButton('Sur ce Board',v.items.length,!S.foldWorkspace,()=>{S.foldWorkspace=!S.foldWorkspace;save();render()}));
      if(S.foldWorkspace)return;
      if(v.status==='loading'){ui.ws.appendChild(el('div','jvr-empty','Chargement des éléments du Board…'));return}
      if(v.status==='failed'&&!v.items.length){const n=el('div','jvr-empty',`Éléments du Board indisponibles : ${v.error||'raison inconnue'}`);n.dataset.kind='failed';ui.ws.appendChild(n);return}
      const ul=el('ul','jvr-list');ul.setAttribute('role','listbox');ul.setAttribute('aria-label','Éléments liés au Board');
      for(const item of v.items)ul.appendChild(wsCardFor(item));
      ui.ws.appendChild(ul);
    }
    /* Clic : une image s'ouvre dans l'aperçu des captures (Slice 05) s'il est chargé ; sinon, et pour tout le reste, le détail de l'Artifact dans
       l'inspecteur. Un lien n'est jamais ouvert de lui-même (le menu le propose). */
    function openWsItem(item,via){
      const preview=root.JarvisScreenshotPreview;
      if(item.primary_action==='lightbox'&&preview&&typeof preview.openLightbox==='function'){
        try{preview.openLightbox({artifact_id:item.id,url:item.preview.url,title:item.title});log('workspace_item_opened',{artifact_id:item.id,via,surface:'lightbox'});return true}
        catch(error){log('workspace_item_open_failed',{artifact_id:item.id,surface:'lightbox',error:cleanLine(error&&error.message,120)},'error')}
      }
      const W=root.JarvisWorkspace;
      if(!W||typeof W.open!=='function'||typeof W.act!=='function'){say('failed','L’inspecteur des espaces de travail n’est pas chargé dans cette page.');return false}
      try{
        W.open();
        Promise.resolve(W.act('artifact-show',{id:item.id})).catch(error=>{
          log('workspace_item_open_failed',{artifact_id:item.id,surface:'detail',error:cleanLine(error&&error.message,120)},'error');
          say('failed',`Détail indisponible : ${cleanLine(error&&error.message,100)}`)});
        log('workspace_item_opened',{artifact_id:item.id,via,surface:'detail'});
        return true;
      }catch(error){
        log('workspace_item_open_failed',{artifact_id:item.id,surface:'detail',error:cleanLine(error&&error.message,120)},'error');
        say('failed',`Détail indisponible : ${cleanLine(error&&error.message,100)}`);return false;
      }
    }
    function openWsMenu(item,origin,x,y){
      const items=[{act:'ws-open',label:item.primary_action==='lightbox'?'Ouvrir l’image':'Ouvrir le détail'}];
      if(item.primary_action==='lightbox')items.push({act:'ws-detail',label:'Ouvrir le détail'});
      if(item.url)items.push({act:'ws-link',label:'Ouvrir le lien dans un onglet'});
      openMenu(item.title,items,origin,x,y,act=>{
        if(act==='ws-open')openWsItem(item,'menu');
        else if(act==='ws-detail')openWsItem({...item,primary_action:'detail'},'menu');
        else if(act==='ws-link'){
          try{const w=win.open(item.url,'_blank','noopener,noreferrer');log('workspace_link_opened',{artifact_id:item.id,opened:!!w});if(!w)say('failed','Le navigateur a bloqué l’ouverture de l’onglet.')}
          catch(error){log('workspace_link_failed',{artifact_id:item.id,error:cleanLine(error&&error.message,120)},'error');say('failed',`Lien : ${cleanLine(error&&error.message,100)}`)}
        }
      });
    }
    function foldButton(label,count,open,onToggle){
      const b=el('button','jvr-fold');b.type='button';b.setAttribute('aria-expanded',String(open));
      b.append(el('span','',open?'▾':'▸'),el('span','',`${label} (${count})`));
      b.addEventListener('click',onToggle);return b;
    }
    function render(){
      if(destroyed)return;
      build();
      const m=model(),visible=shown();
      ui.host.hidden=!visible;
      /* Densité (pure, `densityOf`) : pleine, bande de vignettes (72 px, ou repliée), onglet sous 700 px, colonne à côté du Studio. */
      const density=densityOf({width:Number(win.innerWidth)||1280,collapsed:S.collapsed,studio:!!(S.studioOpen&&visible)});
      if(density!=='drawer')S.drawer=false;
      S.density=density;
      const slim=density==='slim';
      ui.host.dataset.density=density;ui.host.dataset.drawer=S.drawer?'open':'closed';
      ui.host.dataset.collapsed=String(slim);
      if(!slim)hidePeek();
      ui.count.textContent=m.visible.length?`(${m.visible.length})`:'';
      const offer=home();ui.newBtn.hidden=!offer||density==='drawer'&&!S.drawer;
      if(offer){const busy=!!S.creating;if(busy)ui.newBtn.setAttribute('aria-disabled','true');else ui.newBtn.removeAttribute('aria-disabled');
        ui.newBtn.title=busy?`Création de « ${cleanLine(S.creating.title,40)} »…`:'Nouvelle présentation'}
      const urgent=m.problems.length?'problem':m.working.length?'working':m.unreviewed.length?'unreviewed':null;
      ui.urgent.style.setProperty('--c',urgent?STATE_COLOR[urgent]:'transparent');ui.urgent.title=urgent?STATE_LABEL[urgent]:'';
      if(urgent)ui.urgent.dataset.state=urgent;else delete ui.urgent.dataset.state;
      if(density==='drawer'){
        ui.collapseBtn.textContent=S.drawer?'›':'‹';ui.collapseBtn.setAttribute('aria-expanded',String(S.drawer));
        ui.collapseBtn.setAttribute('aria-label',S.drawer?'Fermer le rail des présentations':`Ouvrir le rail des présentations${urgent?` (${STATE_SHORT[urgent].toLowerCase()})`:''}`);
      }else{
        ui.collapseBtn.removeAttribute('aria-expanded');
        ui.collapseBtn.textContent=slim?'‹':'›';ui.collapseBtn.setAttribute('aria-label',S.collapsed?'Déplier le rail':'Replier le rail');
      }
      ui.collapseBtn.title=ui.collapseBtn.getAttribute('aria-label');
      ui.voice.dataset.v=S.voice||'idle';ui.voice.setAttribute('aria-label',`Voix : ${S.voice||'idle'}`);ui.voice.title=`Voix de Jarvis : ${S.voice||'idle'} (elle reste utilisable pendant l’affichage)`;
      /* La liste est reconstruite à chaque relevé : la carte qui avait le focus le retrouve (sinon le clavier le perdrait toutes les 2 à 4 s). */
      const active=doc.activeElement;
      const focused=active&&ui.host.contains(active)&&active.classList&&active.classList.contains('jvr-item')?active.dataset.id:null;
      clear(ui.list);
      if(!S.loaded&&!S.lost)ui.list.appendChild(el('li','jvr-empty','Chargement…'));
      const showHome=S.loaded&&!m.visible.length&&!m.total&&home()&&!S.lost;
      /* L'accueil vit hors de la liste d'options (une liste d'options ne contient que des options). */
      clear(ui.home);ui.home.hidden=!showHome;ui.list.hidden=showHome;
      if(showHome)ui.home.appendChild(homeFor());
      else if(!m.visible.length)ui.list.appendChild(el('li','jvr-empty',m.total?'Toutes sont masquées ou archivées.':'Aucune présentation.'));
      for(const row of m.visible)ui.list.appendChild(itemFor(row));
      clear(ui.hiddenFold);clear(ui.archivedFold);
      if(m.hidden.length){
        ui.hiddenFold.appendChild(foldButton('Masquées',m.hidden.length,S.foldHidden,()=>{S.foldHidden=!S.foldHidden;save();render()}));
        if(S.foldHidden){const ul=el('ul','jvr-list');for(const row of m.hidden)ul.appendChild(itemFor(row,{dim:true}));ui.hiddenFold.appendChild(ul)}
      }
      if(m.archived.length){
        ui.archivedFold.appendChild(foldButton('Archivées',m.archived.length,S.foldArchived,()=>{S.foldArchived=!S.foldArchived;save();render()}));
        if(S.foldArchived){const ul=el('ul','jvr-list');for(const row of m.archived)ul.appendChild(itemFor(row,{dim:true}));ui.archivedFold.appendChild(ul)}
      }
      renderWorkspace();
      const note=S.lost?{kind:'failed',text:'Rail injoignable : l’état affiché n’est plus confirmé.'}
        :S.creating?{kind:'info',text:`Création de « ${cleanLine(S.creating.title,40)} »… ${Math.max(0,Math.floor((now()-S.creating.since)/1000))} s`}:S.notice;
      ui.note.hidden=!note;ui.note.textContent=note?note.text:'';ui.note.dataset.kind=note?note.kind:'';
      ui.note.title=note&&!S.lost?'Cliquer pour masquer ce message':'';
      /* Les secondes d'une création ne se lisent pas à voix haute chaque seconde : l'annonce part au début et à l'issue. */
      ui.note.setAttribute('aria-live',S.creating?'off':'polite');
      doc.documentElement.classList.toggle('jvr-studio',!!(S.studioOpen&&visible));
      doc.documentElement.classList.toggle('jvr-slim',!!(S.studioOpen&&visible&&slim));
      if(focused&&doc.activeElement!==ui.host.querySelector(`.jvr-item[data-id="${focused}"]`)){const again=itemById(focused);if(again){again.focus({preventScroll:true});if(slim)showPeek(again)}}
      syncStudioInset(visible);
      reportSoon();
    }
    /* Slice 08 : pictogramme au trait (même dessin que les vignettes). */
    function svgIcon(parts){
      const ns='http://www.w3.org/2000/svg',svg=doc.createElementNS(ns,'svg');
      svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','2');
      svg.setAttribute('stroke-linecap','round');svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');
      for(const [tag,attrs] of parts){const n=doc.createElementNS(ns,tag);for(const k of Object.keys(attrs))n.setAttribute(k,attrs[k]);svg.appendChild(n)}
      return svg;
    }
    /* L'accueil vide (Slice 08) : quatre étapes, chacune avec son geste quand il existe dans la page. */
    function homeFor(){
      const li=el('div','jvr-homewrap');
      const title=el('p','jvr-home-title','Votre première présentation');title.id='jvrHomeTitle';
      const list=el('ol','jvr-home');list.setAttribute('aria-labelledby',title.id);
      for(const step of JOURNEY){
        const item=el('li','jvr-step');item.dataset.step=step.step;
        item.append(el('strong','',step.title),el('p','',step.text));
        if(step.action){
          const b=el('button','',step.label);b.type='button';b.dataset.homeAct=step.action;
          if(step.action==='create'&&S.creating)b.setAttribute('aria-disabled','true');
          b.addEventListener('click',()=>homeAct(step.action,b));
          item.append(b);
        }
        list.append(item);
      }
      li.append(title,list);
      return li;
    }
    function homeAct(action,origin){
      log('home_action',{action});
      if(action==='create')return createPresentation('home');
      if(action==='dossier'){
        const dossier=d.dossier||root.JarvisDossier;
        if(!dossier||typeof dossier.open!=='function'){say('failed','Le Dossier n’est pas chargé dans cette page.');return null}
        try{const r=dossier.open({opener:origin});if(r&&r.ok===false)say('failed',r.reason||'Le Dossier n’a pas pu s’ouvrir.');return r}
        catch(error){log('home_dossier_failed',{error:cleanLine(error&&error.message,120)},'error');say('failed',`Dossier : ${cleanLine(error&&error.message,100)}`);return null}
      }
      if(action==='chat'){
        const chat=d.chat||root.JarvisChat;
        if(!chat||typeof chat.open!=='function'){say('failed','Le chat n’est pas chargé dans cette page.');return null}
        try{return chat.open({})}
        catch(error){log('home_chat_failed',{error:cleanLine(error&&error.message,120)},'error');say('failed',`Chat : ${cleanLine(error&&error.message,100)}`);return null}
      }
      return null;
    }
    /* « Nouvelle présentation » (Slice 08) : un titre, puis la création par Core (son moteur par défaut, aucun nommé). Une seule à la fois,
       bornée (`CREATE_TIMEOUT_MS`) ; l'attente se voit (note avec secondes), un échec dit sa cause, la liste est relue dans tous les cas. */
    async function createPresentation(via){
      if(S.creating){say('info','Une création est déjà en cours.');return null}
      if(!home()){log('create_refused',{via,reason:'not_product_edition'},'warn');return null}
      const title=await askText({title:'Nouvelle présentation',body:'Donnez-lui un titre. Jarvis pourra ensuite en écrire les scènes à partir des sources du Dossier.',
        value:'',confirmLabel:'Créer'});
      if(title===null)return null;
      S.creating={title,since:now()};
      const ticker=typeof win.setInterval==='function'?win.setInterval(()=>render(),1000):null;
      log('create_started',{via});render();
      try{
        const answer=await call('POST',CREATE_ROUTE,{title},CREATE_TIMEOUT_MS);
        const created=answer&&answer.presentation||null;
        const id=created&&typeof created.presentation_id==='string'?created.presentation_id:null;
        log('created',{via,presentation_id:id?id.slice(0,12):null,seconds:Math.round((now()-S.creating.since)/1000)});
        S.creating=null;
        await refresh();
        say('ok',`« ${cleanLine(title,40)} » créée. Demandez à Jarvis d’en écrire les scènes, puis ouvrez-la pour les relire.`);
        const card=id?itemById(id):null;if(card)card.focus({preventScroll:true});
        return created;
      }catch(error){
        const code=error&&error.code||'network';
        const base=CREATE_ERRORS[code];
        const text=code==='timeout'?`Pas de réponse après ${CREATE_TIMEOUT_MS/1000} s : l’issue est inconnue, la liste est relue.`
          :code==='presentation_studio_invalid'?base+cleanLine(error&&error.message,120):base||`Création impossible : ${cleanLine(error&&error.message,120)||code}`;
        log('create_failed',{via,code,status:error&&error.status||null,message:cleanLine(error&&error.message,160)},'error');
        S.creating=null;
        say('failed',text);
        refresh();
        return null;
      }finally{
        if(ticker&&typeof win.clearInterval==='function')win.clearInterval(ticker);
        S.creating=null;render();
      }
    }
    function syncStudioInset(visible){
      const html=doc.documentElement;
      if(html&&html.style)html.style.setProperty('--jvr-width',visible&&S.studioOpen?`${S.collapsed?60:STUDIO_WIDTH_PX}px`:'0px');
    }
    function say(kind,text){
      S.notice={kind,text};
      if(noticeTimer)cancelLater(noticeTimer);
      noticeTimer=kind==='failed'?null:later(()=>{S.notice=null;render()},NOTICE_MS);
      render();
    }

    /* ------------------------------------------------------------ données */
    async function refresh(){
      if(polling||destroyed)return;
      polling=true;
      try{
        const answer=await call('GET',ROUTE);
        failures=0;S.lost=false;
        S.rows=Array.isArray(answer&&answer.presentations)?answer.presentations:[];
        S.playing=answer&&answer.playing||null;
        S.loaded=true;
        S.reportWanted=!!(answer&&answer.ui&&(answer.ui.request||answer.ui.reported));
        applyUiRequest(answer&&answer.ui);
        S.firstPoll=false;
        render();
      }catch(error){
        failures+=1;
        if(failures===1||failures%10===0)log('poll_failed',{code:error.code,message:cleanLine(error.message,120),failures},'warn');
        if(failures>=2&&!S.lost){S.lost=true;render()}
      }finally{polling=false}
    }
    function applyUiRequest(uiBlock){
      const request=uiBlock&&uiBlock.request;
      if(!request)return;
      if(S.lastSeq!==null&&request.seq<=S.lastSeq)return;
      const apply=request.fresh===true;
      S.lastSeq=request.seq;
      if(!apply)return;
      log('ui_request',{seq:request.seq,action:request.action});
      if(request.action==='show_rail'){S.pref='shown';save()}
      else if(request.action==='hide_rail'){S.pref='hidden';save()}
      reportSoon(true);
    }
    function reportSoon(immediate){
      if(destroyed)return;
      if(!S.coreOk)return;
      const body=reportBody(),key=JSON.stringify(body);
      /* Seul un CHANGEMENT part (le constat de départ est la ligne de base, jamais envoyé), puis un battement toutes les 15 s tant qu'un agent a déjà demandé ou lu l'écran. */
      if(S.lastReport===''){S.lastReport=key;S.lastReportAt=now();if(!immediate)return}
      if(!immediate&&key===S.lastReport&&!(S.reportWanted&&now()-S.lastReportAt>=REPORT_EVERY_MS))return;
      if(reportTimer)cancelLater(reportTimer);
      reportTimer=later(()=>{reportTimer=null;reportNow()},immediate?0:400);
    }
    function reportBody(){
      const shown=variantsPid();
      return {rail_visible:!!(ui.host&&!ui.host.hidden),variants_open:!!shown,presentation_id:shown||null,applied_seq:S.lastSeq};
    }
    async function reportNow(){
      const body=reportBody();
      try{await call('POST',STATE_ROUTE,body,4000);S.lastReport=JSON.stringify(body);S.lastReportAt=now()}
      catch(error){log('report_failed',{code:error.code})}
    }

    /* ------------------------------------------------------------ gestes */
    const rowOf=id=>S.rows.find(r=>r.presentation_id===id)||null;
    /* A row's click, « Ouvrir les variantes », « Éditer »: Variants, windowed (the rail and the voice stay usable), on the active variant. */
    function openRow(id,via){
      const row=rowOf(id);
      if(row&&row.archived){say('failed','Archivée : restaurez-la d’abord.');return false}
      const ex=explorerApi();
      if(!ex||typeof ex.open!=='function'){say('failed','Variantes n’est pas chargé dans cette page.');return false}
      Promise.resolve(ex.open({presentation_id:id,fullscreen:false,via:'rail'})).then(result=>{
        if(result&&result.state==='refused')say('failed',result.reason||result.code||'Variantes refusé.');
        else markSeen(id,via);
        render();reportSoon(true);
      }).catch(error=>{log('variants_open_failed',{via,error:cleanLine(error&&error.message,120)},'error');say('failed',`Ouverture impossible : ${cleanLine(error&&error.message,100)}`)});
      return true;
    }
    /* « Remotion Studio… » (§ 1, Slice 11): Variants opens on the presentation, then its « Remotion Studio » door on the scene on screen (the
       confirmation names the scene; « Annuler » launches nothing). Remotion Studio's state and failures are said in Variants. */
    async function remotionStudio(id){
      const row=rowOf(id);
      if(row&&row.archived){say('failed','Archivée : restaurez-la d’abord.');return null}
      const ex=explorerApi();
      if(!ex||typeof ex.open!=='function'||!ex.remotionStudio||typeof ex.remotionStudio.open!=='function'){say('failed','Variantes n’est pas chargé dans cette page.');return null}
      try{
        const opened=await ex.open({presentation_id:id,fullscreen:false,via:'rail'});
        render();reportSoon(true);
        if(opened&&opened.state==='refused'){say('failed',opened.reason||opened.code||'Variantes refusé.');return opened}
        markSeen(id,'studio');
        const result=await ex.remotionStudio.open({via:'rail'});
        log('remotion_studio_from_rail',{state:result&&result.state});
        return result;
      }catch(error){
        log('remotion_studio_from_rail_failed',{error:cleanLine(error&&error.message,120)},'error');
        say('failed',`Remotion Studio : ${cleanLine(error&&error.message,100)}`);
        return null;
      }
    }
    /* Ouvrir une présentation depuis le rail, c'est la revoir (D10) : le jaune s'efface par l'action `review` de Core (acteur `user`). */
    function markSeen(id,via){
      const row=rowOf(id);
      if(!row||!row.unreviewed)return;
      log('review_on_open',{presentation_id:id.slice(0,12),via});
      write(id,{action:'review'},'Marquer comme vu');
    }
    async function edit(id){
      const ins=inspectorApi();
      openRow(id,'edit');
      if(!ins||typeof ins.open!=='function'){say('failed','L’inspecteur n’est pas chargé dans cette page.');return}
      try{
        if(typeof ins.refresh==='function')await ins.refresh();
        if(typeof ins.selectPresentation==='function')await ins.selectPresentation(id,{});
        const opened=ins.open();
        if(opened===false)say('info','L’inspecteur est indisponible (lecture en cours ou plein écran).');
      }catch(error){log('edit_failed',{error:cleanLine(error&&error.message,120)},'error');say('failed',`Inspecteur : ${cleanLine(error&&error.message,100)}`)}
    }
    /* « Présenter » (§ 1, § 5): a `user_presenter` run, by the page's playback client; Variants opens on it and shows it. */
    async function play(id){
      const p=playerApi();
      const result=p&&typeof p.startRun==='function'?await p.startRun(id,'user_presenter'):null;
      if(!result)say('failed','Le client de lecture n’est pas chargé dans cette page.');
      else if(result.status==='applied')say('ok','Présentation lancée dans Variantes.');
      else say('failed',`Présentation impossible : ${cleanLine(result.message||result.reason||'refusée',140)}`);
      return result;
    }
    async function write(id,body,label){
      const key=id+':'+body.action;
      if(S.busy.has(key))return null;
      S.busy.add(key);
      try{
        const answer=await call('POST',act(id),body);
        log('rail_action',{action:body.action,presentation_id:id.slice(0,12),changed:answer&&answer.changed});
        if(S.notice&&S.notice.kind==='failed')S.notice=null;
        await refresh();
        return answer;
      }catch(error){
        log('rail_action_failed',{action:body.action,code:error.code,status:error.status},'error');
        say('failed',`${label||body.action} impossible : ${cleanLine(error.message,140)}${error.code?` (${error.code})`:''}`);
        return null;
      }finally{S.busy.delete(key)}
    }
    async function run(action,id){
      const row=rowOf(id);if(!row)return;
      if(action==='open')return openRow(id,'menu');
      if(action==='edit')return edit(id);
      if(action==='studio'){if(!developer()){log('studio_hidden',{});return null}return remotionStudio(id)}
      if(action==='play')return play(id);
      if(action==='hide'||action==='show'){const a=await write(id,{action},action==='hide'?'Masquer':'Afficher');if(a)say('ok',action==='hide'?'Masquée du rail (menu Masquées pour la réafficher).':'Réaffichée dans le rail.');return}
      if(action==='ack')return write(id,{action:'acknowledge'},'Acquitter');
      if(action==='review'){const a=await write(id,{action:'review'},'Marquer comme vu');if(a)say('ok','Marquée comme vue.');return}
      if(action==='restore'){const a=await write(id,{action:'restore'},'Restaurer');if(a)say('ok','Restaurée.');return}
      if(action==='rename'){
        const value=await askText({title:'Renommer la présentation',value:row.title,confirmLabel:'Renommer'});
        if(value===null||cleanLine(value,80)===row.title)return;
        const a=await write(id,{action:'rename',title:cleanLine(value,80)},'Renommer');if(a)say('ok','Renommée.');
        return;
      }
      if(action==='archive'){
        const ok=await askConfirm({title:`Supprimer « ${cleanLine(row.title,40)} » ?`,
          body:'Elle quitte le rail et ne se lit plus. Rien n’est effacé : elle se restaure à tout moment (Archivées, en bas du rail).',confirmLabel:'Supprimer',danger:true});
        if(!ok)return;
        const ex=explorerApi();if(variantsPid()===id&&ex&&typeof ex.close==='function')ex.close({reason:'archived',quiet:true});
        const a=await write(id,{action:'archive'},'Supprimer');if(a)say('ok','Archivée : restaurable depuis « Archivées ».');
      }
    }

    /* ------------------------------------------------------------ menu contextuel et boîtes (propres au rail : elles doivent passer AU-DESSUS du Studio) */
    function openMenuFor(row,origin,x,y){
      const items=menuModel(row,{playing:runActive(),playingThis:playingId()===row.presentation_id,developer:developer()});
      openMenu(row.title,items,origin,x,y,act=>run(act,row.presentation_id),row);
    }
    /* Le menu du rail (présentations et, étape B, éléments du Board) : en-tête, entrées, une note dit pourquoi une entrée est indisponible. */
    function openMenu(title,items,origin,x,y,onPick,row){
      closeMenu(false);
      const rect=origin.getBoundingClientRect();
      S.menuRow={row:row||null,origin,id:origin&&origin.dataset?origin.dataset.id:null};
      clear(ui.menu);
      const head=el('div','jvr-mhead',cleanLine(title,40));ui.menu.appendChild(head);
      for(const it of items){
        if(it==='-'){ui.menu.appendChild(el('div','jvr-sep'));continue}
        const b=el('button','',it.label);b.type='button';b.setAttribute('role','menuitem');b.dataset.act=it.act;
        if(it.danger)b.setAttribute('data-danger','');
        if(it.note){b.setAttribute('aria-disabled','true');b.title=it.note}
        b.addEventListener('click',()=>{
          if(it.note){say('info',it.note);return}
          if(!S.menuRow)return;
          closeMenu(true);onPick(it.act);
        });
        ui.menu.appendChild(b);
      }
      ui.menu.hidden=false;
      const w=ui.menu.offsetWidth||200,h=ui.menu.offsetHeight||240,W=Number(win.innerWidth)||1280,H=Number(win.innerHeight)||800;
      /* Rail au bord droit : le menu s'ouvre à gauche de la carte (au pointeur pour un clic droit). */
      const px=x!=null?x:rect.left-w-6,py=y!=null?y:rect.top;
      ui.menu.style.left=Math.max(8,Math.min(px,W-w-8))+'px';ui.menu.style.top=Math.max(8,Math.min(py,H-h-8))+'px';
      const first=ui.menu.querySelector('button:not([aria-disabled=true])');if(first)first.focus({preventScroll:true});
      log('menu_opened',{items:items.length});
    }
    /* A card by its canonical id (the list is rebuilt on every Core read: a kept DOM node may be detached). */
    function itemById(id){return id&&ui.host?Array.from(ui.host.querySelectorAll('.jvr-item')).find(n=>n.dataset.id===id)||null:null}
    function closeMenu(restore){
      const was=S.menuRow;S.menuRow=null;if(ui.menu){ui.menu.hidden=true;clear(ui.menu)}
      if(restore&&was&&was.origin){const target=was.origin.isConnected?was.origin:itemById(was.id);if(target)target.focus({preventScroll:true})}
    }
    function onMenuKey(event){
      const buttons=Array.from(ui.menu.querySelectorAll('button'));const i=buttons.indexOf(doc.activeElement);
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeMenu(true)}
      else if(event.key==='ArrowDown'){event.preventDefault();buttons[(i+1)%buttons.length].focus()}
      else if(event.key==='ArrowUp'){event.preventDefault();buttons[(i-1+buttons.length)%buttons.length].focus()}
      else if(event.key==='Home'){event.preventDefault();buttons[0].focus()}
      else if(event.key==='End'){event.preventDefault();buttons[buttons.length-1].focus()}
      else if(event.key==='Tab'){closeMenu(false)}
    }
    function onKey(event){
      const item=event.target&&event.target.closest&&event.target.closest('.jvr-item');
      if(!item)return;
      const all=Array.from(ui.host.querySelectorAll('.jvr-item')),i=all.indexOf(item),row=rowOf(item.dataset.id);
      if(event.key==='ArrowDown'&&i<all.length-1){event.preventDefault();all[i+1].focus()}
      else if(event.key==='ArrowUp'&&i>0){event.preventDefault();all[i-1].focus()}
      else if(event.key==='ContextMenu'||(event.key==='F10'&&event.shiftKey)){event.preventDefault();if(row)openMenuFor(row,item);else if(item.dataset.ws){const w=wsItemOf(item.dataset.id);if(w)openWsMenu(w,item)}}
      else if(event.key==='F2'&&row&&!row.archived){event.preventDefault();run('rename',row.presentation_id)}
      else if(event.key==='Delete'&&row&&!row.archived){event.preventDefault();run('archive',row.presentation_id)}
    }
    function dialogShell(title,bodyText){
      const box=el('div','jvr-dialog');box.setAttribute('role','alertdialog');box.setAttribute('aria-modal','true');
      const h=el('h2','',title);h.id='jvrDialogTitle';box.setAttribute('aria-labelledby',h.id);box.appendChild(h);
      if(bodyText)box.appendChild(el('p','',bodyText));
      return box;
    }
    function showDialog(box,focusEl){
      clear(ui.back);ui.back.appendChild(box);ui.back.hidden=false;
      const previous=doc.activeElement;
      return new Promise(resolve=>{
        const finish=value=>{ui.back.hidden=true;clear(ui.back);ui.back.onkeydown=null;S.dialog=null;if(previous&&previous.isConnected&&previous.focus)previous.focus({preventScroll:true});resolve(value)};
        S.dialog={finish};
        ui.back.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();finish(null)}};
        ui.back.onmousedown=e=>{if(e.target===ui.back)finish(null)};
        box.__finish=finish;
        if(focusEl)focusEl.focus({preventScroll:true});
      });
    }
    function askText(spec){
      const box=dialogShell(spec.title,spec.body);
      const input=el('input');input.type='text';input.value=cleanLine(spec.value,80);input.maxLength=80;input.setAttribute('aria-label',spec.title);
      const row=el('div','jvr-row');const cancel=el('button','',spec.cancelLabel||'Annuler');cancel.type='button';
      const ok=el('button','',spec.confirmLabel||'Valider');ok.type='button';
      row.append(cancel,ok);box.append(input,row);
      const p=showDialog(box,input);
      cancel.addEventListener('click',()=>box.__finish(null));
      const submit=()=>{const v=cleanLine(input.value,80);if(!v){input.focus();return}box.__finish(v)};
      ok.addEventListener('click',submit);
      input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();submit()}});
      try{input.select()}catch(_e){/* intentional */}
      return p;
    }
    function askConfirm(spec){
      const box=dialogShell(spec.title,spec.body);
      const row=el('div','jvr-row');const cancel=el('button','',spec.cancelLabel||'Annuler');cancel.type='button';
      const ok=el('button','',spec.confirmLabel||'Confirmer');ok.type='button';if(spec.danger)ok.setAttribute('data-danger','');
      row.append(cancel,ok);box.appendChild(row);
      const p=showDialog(box,cancel);
      cancel.addEventListener('click',()=>box.__finish(false));
      ok.addEventListener('click',()=>box.__finish(true));
      return p.then(v=>v===true);
    }

    /* ------------------------------------------------------------ cycle de vie */
    function interval(){
      if(doc.hidden)return POLL_HIDDEN_MS;
      const m=model();return m.working.length||S.firstPoll?POLL_BUSY_MS:POLL_IDLE_MS;
    }
    /* Le rail ne sonde Core que lorsque le statut 1 Hz de la page dit que Core répond (`boards.available`) : une page sans Core (démarrage, panne, banc
       d'essai) n'envoie aucune requête vouée à l'échec et n'écrit rien dans la console. `S.coreOk` vient de `gate`. */
    function schedule(){
      if(destroyed)return;
      if(pollTimer)cancelLater(pollTimer);
      pollTimer=later(async()=>{pollTimer=null;if(S.coreOk){await refresh();refreshWorkspace(false)}schedule()},interval());
    }
    /* Étape B : le Board actif vient du statut 1 Hz ; un changement vide et relit, sinon une relecture au plus toutes les 10 s, rail visible. */
    function refreshWorkspace(force){
      if(!ws||!S.coreOk)return;
      if(ws.view().boardId!==S.boardId){ws.setBoard(S.boardId);return}
      if(!S.boardId||!ui.host||ui.host.hidden)return;
      if(force||now()-ws.loadedAt>=WORKSPACE_REFRESH_MS)ws.refresh();
    }
    function start(){
      load();build();render();
      schedule();
      if(d.assumeCore){S.coreOk=true;refresh().then(()=>{render()})}
      doc.addEventListener('visibilitychange',()=>{if(!doc.hidden&&S.coreOk)refresh()});
      win.addEventListener&&win.addEventListener('resize',()=>{const next=densityOf({width:Number(win.innerWidth)||1280,collapsed:S.collapsed,studio:!!(S.studioOpen&&ui.host&&!ui.host.hidden)});if(S.studioOpen||next!==S.density)render()});
      win.addEventListener&&win.addEventListener('jarvis:studio-explorer-opened',()=>{S.studioOpen=true;render();reportSoon(true)});
      win.addEventListener&&win.addEventListener('jarvis:studio-explorer-closed',()=>{S.studioOpen=false;render();reportSoon(true)});
      /* Slice 08 : l'édition lue (ou relue) sur Core peut ouvrir l'accueil ou cacher les noms de moteur. */
      if(edition&&typeof edition.subscribe==='function')edition.subscribe(()=>{if(ui.host)render()});
      log('installed',{});
    }
    function stop(){destroyed=true;for(const t of [pollTimer,reportTimer,noticeTimer])if(t)cancelLater(t);pollTimer=reportTimer=noticeTimer=null}

    /* Le statut 1 Hz de la page : Board actif (type), mode d'interaction (dérivé du type), état de la voix. Aucune autre vérité n'y est lue. */
    function gate(status){
      const s=status||{};
      const kind=s.boards&&s.boards.active&&s.boards.active.board_kind||null;
      const boardId=s.boards&&s.boards.active&&typeof s.boards.active.board_id==='string'?s.boards.active.board_id:null;
      const mode=s.interaction_mode&&s.interaction_mode.mode||null;
      const voice=s.voice_online===false?'hors ligne':String(s.voice_state||'idle');
      const coreOk=!!(s.boards&&s.boards.available===true);
      const wasOk=S.coreOk;
      S.coreOk=coreOk;
      if(coreOk&&!wasOk)refresh().then(()=>render());
      if(!coreOk&&wasOk&&S.loaded){S.lost=true}
      const boardChanged=boardId!==S.boardId;S.boardId=boardId;
      if(boardChanged||(coreOk&&!wasOk))refreshWorkspace(true);
      if(kind===S.boardKind&&mode===S.mode&&voice===S.voice&&coreOk===wasOk&&!boardChanged)return;
      S.boardKind=kind;S.mode=mode;S.voice=voice;render();
    }
    function setPref(value){if(value==='auto'||value==='shown'||value==='hidden'){S.pref=value;save();render();return true}return false}
    function cyclePref(){const order=['auto','shown','hidden'];setPref(order[(order.indexOf(S.pref)+1)%order.length]);return S.pref}

    return {start,stop,refresh,render,gate,setPref,cyclePref,run,openMenuFor,closeMenu,createPresentation,
      state:()=>({pref:S.pref,collapsed:S.collapsed,density:S.density,drawer:S.drawer,loaded:S.loaded,lost:S.lost,visible:!!(ui.host&&!ui.host.hidden),rows:S.rows.length,home:home(),creating:!!S.creating,
        studioOpen:S.studioOpen,menuOpen:!!S.menuRow,dialogOpen:!!S.dialog,notice:S.notice}),
      model,host:()=>ui.host,rows:()=>S.rows.slice(),workspace:()=>ws?ws.view():null,setStudio:on=>{S.studioOpen=!!on;render()}};
  }

  const API=Object.freeze({DOM,ROUTE,STATE_ROUTE,STATE_LABEL,STATE_SHORT,STATE_COLOR,CSS,cleanLine,monogram,hueOf,stateOf,displayState,typeOf,ago,previewOf,cardOf,
    densityOf,modelOf,shouldShow,menuModel,createRail,JOURNEY,CREATE_ROUTE,CREATE_ERRORS});
  root.JarvisPresentationRailCore=API;
  if(typeof module!=='undefined'&&module.exports)module.exports=API;

  if(typeof window==='undefined'||typeof document==='undefined')return;
  function installRail(){
    const rail=createRail({document,window,toast:typeof toast==='function'?toast:null});
    root.JarvisPresentationRail=Object.freeze({gate:rail.gate,refresh:rail.refresh,state:rail.state,setPref:rail.setPref,cyclePref:rail.cyclePref,run:rail.run,createPresentation:rail.createPresentation,
      model:rail.model,render:rail.render,workspace:rail.workspace});
    /* Pas de bouton au dock (sa géométrie est comptée pour dix outils, y compris celle du thème Cosmos) : Alt+Maj+P fait tourner automatique / toujours visible / masqué. */
    document.addEventListener('keydown',event=>{
      if(!(event.altKey&&event.shiftKey&&!event.ctrlKey&&!event.metaKey&&(event.key==='P'||event.key==='p')))return;
      event.preventDefault();
      const pref=rail.cyclePref();
      if(typeof toast==='function')toast({title:'Rail des présentations',sub:pref==='auto'?'Automatique : visible dans un Board de présentation ou quand un agent travaille.':pref==='shown'?'Toujours visible.':'Masqué (le cerveau peut le rouvrir).',kind:'info'});
    });
    rail.start();
  }
  /* Rattrapé ici : la page servie n'a qu'une balise <script> ; une levée emporterait la scène avec elle. */
  try{installRail()}
  catch(error){console.error('[presentation-rail] install_failed '+JSON.stringify({error:String(error&&error.message||error)}))}
})(typeof window!=='undefined'?window:globalThis);
