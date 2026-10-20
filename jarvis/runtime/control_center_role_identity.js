/* Identité visuelle des rôles et grammaire des relations d'agent, partagées par Réglages > Sous-agents
   (`control_center_subagents_settings.js`, Slice 10) et le graphe des tâches de la scène
   (`control_center_scene_page.js`, `control_center_relation_board.js`, Slice 09) du handoff
   jarvis-organic-agent-orchestration. Une seule source : un rôle a la même icône, le même badge et le même accent
   partout (D02), et une relation la même figure partout (D09).

   - `ICONS` : pictogrammes dessinés (trait 1,7, grille 24) des jetons `visual.icon` du registre, plus `flag`
     (responsable de mission, D03) ; un jeton inconnu prend la silhouette générique `agent`.
   - `RELATION_KINDS` : les cinq natures de relation, leur libellé, leur sens (dirigée ou entre pairs), leur
     pictogramme et la phrase qui relie les participants. Les libellés suivent `work_methods.RELATION_LABELS`
     (vérifié par un test) ; la page les relit dans `GET /api/subagent-roles` (`relation_labels`) quand ils y sont.
   - `createRoleRegistry` : lecture unique de `GET /api/subagent-roles` (v2), identité d'un `role_id`
     (`identity`), rôle inconnu dit tel quel, jamais deviné.

   Les accents sont des JETONS : la couleur vit dans `control_center.html` (`--role-accent-<jeton>`), jamais ici.
   Aucune écriture : ce module ne fait que lire. Contrat : `docs/subagent-roles.md` § 8 et `docs/scene-model.md`
   › *Interface: roles and relations*. */
(function(root){
  'use strict';
  const TOKEN=/^[a-z][a-z0-9-]{0,31}$/;
  const ROLES_PATH='/api/subagent-roles';
  const RETRY_MS=30000;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  const ICONS=Object.freeze({
    question:'<circle cx="12" cy="12" r="9.5"/><path d="M9.2 9.2a2.9 2.9 0 0 1 5.6 1c0 1.9-2.8 2.6-2.8 4.3"/><path d="M12 17.6h.01"/>',
    book:'<path d="M5 19.2A2.2 2.2 0 0 1 7.2 17H19"/><path d="M7.2 3H19v18H7.2A2.2 2.2 0 0 1 5 18.8V5.2A2.2 2.2 0 0 1 7.2 3z"/>',
    globe:'<circle cx="12" cy="12" r="9.5"/><path d="M2.5 12h19"/><path d="M12 2.5a14.5 14.5 0 0 1 3.8 9.5 14.5 14.5 0 0 1-3.8 9.5 14.5 14.5 0 0 1-3.8-9.5A14.5 14.5 0 0 1 12 2.5z"/>',
    code:'<path d="M15.5 17.5 21 12l-5.5-5.5"/><path d="M8.5 6.5 3 12l5.5 5.5"/>',
    lightbulb:'<path d="M9 18h6"/><path d="M10 21.5h4"/><path d="M15 14.5c.2-1 .7-1.7 1.4-2.4A5.5 5.5 0 1 0 6.5 8c0 1.2.4 2.5 1.6 3.8.7.8 1.2 1.6 1.4 2.7"/>',
    compass:'<circle cx="12" cy="12" r="9.5"/><path d="m15.8 8.2-2.1 5.5-5.5 2.1 2.1-5.5z"/>',
    'shield-check':'<path d="M12 21.5s7.5-3.6 7.5-9.4V5.4L12 2.5 4.5 5.4v6.7c0 5.8 7.5 9.4 7.5 9.4z"/><path d="m8.8 12 2.2 2.2 4.2-4.4"/>',
    agent:'<circle cx="12" cy="8" r="3.8"/><path d="M4.5 20.5v-.8a6 6 0 0 1 6-6h3a6 6 0 0 1 6 6v.8"/>',
    unknown:'<circle cx="12" cy="12" r="9.5" stroke-dasharray="3 2.4"/><path d="M12 7.6v5.2"/><path d="M12 16.4h.01"/>',
    /* Responsable de mission (D03) : une responsabilité portée par un rôle, pas un rôle. */
    flag:'<path d="M5.5 21.5V3"/><path d="M5.5 3.8h12l-2.6 4.1 2.6 4.1h-12"/>',
  });

  /* Les cinq relations de D09. `directed` : un sens se lit (de `from` vers `to`) ; sinon des pairs.
     `glyph` : pictogramme de la pastille posée sur la relation — jamais le seul indice : le trait (plein, tirets,
     perles, double rail), la flèche et le libellé le disent aussi. */
  const RELATION_KINDS=Object.freeze({
    delegation:Object.freeze({label:'Délégation',directed:true,from:'delegator',to:'delegatee',verb:'délègue à',
      glyph:'<circle cx="12" cy="5" r="2.6"/><path d="M12 7.6v4.4"/><path d="M5.5 19.5V15h13v4.5"/><path d="M12 12v3"/>'}),
    communication:Object.freeze({label:'Échange entre agents',directed:false,verb:'échange avec',
      glyph:'<path d="M4 5h16v10.5h-9.5L6 19.5v-4H4z"/><path d="M8 9.2h8"/><path d="M8 12.2h5"/>'}),
    adversary:Object.freeze({label:'Confrontation',directed:false,verb:'en concurrence avec',
      glyph:'<path d="M4.5 4.5l9.8 9.8"/><path d="M19.5 4.5l-9.8 9.8"/><path d="M6.6 14.6l2.8 2.8"/><path d="M17.4 14.6l-2.8 2.8"/><path d="M4.5 19.5l3-3"/><path d="M19.5 19.5l-3-3"/>'}),
    qa:Object.freeze({label:'Contrôle qualité',directed:true,from:'reviewer',to:'reviewed',verb:'relit',
      glyph:'<circle cx="10.5" cy="10.5" r="6.2"/><path d="m15.2 15.2 5.3 5.3"/><path d="m7.8 10.6 1.9 1.9 3.3-3.6"/>'}),
    handoff:Object.freeze({label:'Relais',directed:true,from:'predecessor',to:'successor',verb:'passe le relais à',
      glyph:'<path d="m5 6 6 6-6 6"/><path d="m12.5 6 6 6-6 6"/>'}),
  });
  const RELATION_ORDER=Object.freeze(['delegation','qa','handoff','adversary','communication']);

  /* Issues de clôture (`agent_relations.RelationOutcome`), états (`open`/`closed`). */
  const OUTCOME_LABELS=Object.freeze({withdrawn:'retirée',returned:'rendue',ended:'terminée',winner:'gagnant désigné',
    synthesis:'synthèse',unresolved:'non tranchée',escalated:'remontée',approved:'approuvé',findings:'remarques',
    correction_requested:'correction demandée',rejected:'rejeté',transferred:'transmis'});
  const STATE_LABELS=Object.freeze({open:'en cours',closed:'close'});
  const MESSAGE_TYPE_LABELS=Object.freeze({message:'Message',proposal:'Proposition',critique:'Critique',question:'Question',
    decision:'Décision',result_summary:'Synthèse de résultat',handoff_note:'Note de relais'});
  const POSITION_LABELS=Object.freeze({delegator:'délègue',delegatee:'reçoit la délégation',member:'membre',producer:'producteur',
    reviewer:'relit',reviewed:'est relu',predecessor:'prédécesseur',successor:'successeur'});
  /* Statut vivant d'une instance (Work State) ; `null` : plus suivie (fin ancienne, Core redémarré). */
  const WORK_STATUS_LABELS=Object.freeze({pending:'en attente',running:'en cours',blocked:'bloqué',completed:'terminé',
    failed:'échec',cancelled:'annulé',interrupted:'interrompu'});

  const own=(o,k)=>!!o&&Object.prototype.hasOwnProperty.call(o,k);
  const label=(table,key,fallback)=>own(table,key)?table[key]:(fallback===undefined?String(key??''):fallback);

  function iconSvg(name,className){
    const body=own(ICONS,name)?ICONS[name]:ICONS.agent;
    return `<svg class="${esc(className||'')}" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
  }
  function relationGlyphSvg(kind,className){
    const body=own(RELATION_KINDS,kind)?RELATION_KINDS[kind].glyph:ICONS.unknown;
    return `<svg class="${esc(className||'')}" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
  }

  /* Identité d'un rôle absent du registre (ou registre pas encore lu) : son id tel quel, un badge tiré de l'id,
     l'icône « inconnu », l'accent neutre. Rien n'est deviné d'un libellé. */
  function fallbackIdentity(roleId,pending){
    const id=String(roleId||'');
    const badge=id.replace(/[^a-z0-9]/gi,'').slice(0,3).toUpperCase()||'?';
    return Object.freeze({id,name:id||'rôle inconnu',badge,icon:'unknown',accent:'slate',known:false,pending:!!pending});
  }

  /* Registre des rôles lu une fois (`GET /api/subagent-roles`), relu après un échec au plus toutes les 30 s.
     `fetchJson(path)` rend le corps ou lève une erreur portant `code` ; `onChange()` est appelé quand les
     identités changent (lecture réussie). */
  function createRoleRegistry(options){
    const opts=options||{};
    const now=typeof opts.now==='function'?opts.now:()=>Date.now();
    const log=typeof opts.log==='function'?opts.log:()=>{};
    const st={phase:'idle',roles:new Map(),aliases:{},accents:[],relationLabels:{},failedAt:0,error:null,inflight:null};
    function accept(body){
      if(!body||typeof body!=='object'||!Array.isArray(body.roles)){
        const e=new Error('Réponse du registre des rôles hors contrat (roles absent).');e.code='role_registry_payload_invalid';throw e;
      }
      const accents=Array.isArray(body.accents)?body.accents.filter(t=>TOKEN.test(String(t))):[];
      const roles=new Map();
      for(const raw of body.roles){
        if(!raw||typeof raw!=='object'||typeof raw.id!=='string'||!raw.id.trim())continue;
        const v=raw.visual&&typeof raw.visual==='object'?raw.visual:{};
        const accent=TOKEN.test(String(v.accent||''))&&(!accents.length||accents.includes(v.accent))?v.accent:'slate';
        const icon=TOKEN.test(String(v.icon||''))?v.icon:'agent';
        roles.set(raw.id,Object.freeze({id:raw.id,name:String(raw.name||raw.id).slice(0,80),
          badge:String(v.badge||raw.id).slice(0,6)||'?',icon,accent,known:true,pending:false}));
      }
      st.roles=roles;st.accents=accents;
      st.aliases=body.aliases&&typeof body.aliases==='object'&&!Array.isArray(body.aliases)?body.aliases:{};
      st.relationLabels=body.relation_labels&&typeof body.relation_labels==='object'?body.relation_labels:{};
      st.phase='ready';st.error=null;
      log('info','role_registry_loaded',{roles:roles.size});
    }
    function load(){
      if(st.phase==='ready')return Promise.resolve(true);
      if(st.inflight)return st.inflight;
      if(st.phase==='failed'&&now()-st.failedAt<RETRY_MS)return Promise.resolve(false);
      if(typeof opts.fetchJson!=='function')return Promise.resolve(false);
      st.phase='loading';
      st.inflight=Promise.resolve().then(()=>opts.fetchJson(ROLES_PATH)).then(body=>{
        accept(body);
        if(typeof opts.onChange==='function')opts.onChange();
        return true;
      },error=>{
        st.phase='failed';st.failedAt=now();st.error=error;
        log('error',error&&error.code||'role_registry_unreadable',{error:String(error&&error.message||error)});
        return false;
      }).finally(()=>{st.inflight=null});
      return st.inflight;
    }
    function identity(roleId){
      const id=String(roleId||'');
      if(st.roles.has(id))return st.roles.get(id);
      const target=own(st.aliases,id)?st.aliases[id]:null;
      if(target&&st.roles.has(target))return st.roles.get(target);
      return fallbackIdentity(id,st.phase!=='ready'&&st.phase!=='failed');
    }
    function relationLabel(kind){
      const served=own(st.relationLabels,kind)?String(st.relationLabels[kind]):'';
      if(served)return served.charAt(0).toUpperCase()+served.slice(1);
      return own(RELATION_KINDS,kind)?RELATION_KINDS[kind].label:String(kind||'relation');
    }
    function accentOf(token){return TOKEN.test(String(token||''))&&(!st.accents.length||st.accents.includes(token))?token:'slate'}
    return {load,identity,relationLabel,accentOf,state:st,phase:()=>st.phase,error:()=>st.error};
  }

  const api=Object.freeze({TOKEN,ICONS,RELATION_KINDS,RELATION_ORDER,OUTCOME_LABELS,STATE_LABELS,MESSAGE_TYPE_LABELS,
    POSITION_LABELS,WORK_STATUS_LABELS,esc,label,iconSvg,relationGlyphSvg,fallbackIdentity,createRoleRegistry});
  root.JarvisRoleIdentity=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
