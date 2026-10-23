/* Registre canonique des Réglages (jarvis-settings-ui-reorganization, Slice 01).

   Contrat : `docs/settings/navigation-registry.md`. Module pur, sans DOM, sans
   réseau, sans stockage : il ne lit ni n'écrit aucun réglage.

   - Exactement six catégories, figées ici et nulle part ailleurs. Aucun appel
     ne peut en ajouter une septième : un module enregistre des SECTIONS dans
     une de ces six catégories, il ne touche plus la navigation de premier niveau.
   - `register` refuse de façon déterministe (exception portant un `code`
     stable) une section invalide, un identifiant en double ou une catégorie
     inconnue.
   - `LEGACY_TAB_ALIASES` : les seuls anciens identifiants d'onglet encore
     servis, chacun vers sa section (table explicite, Slice 09). L'ancien
     système d'onglets (`TABS`, adaptateur `legacyTabFor`) n'existe plus.
   - `shellNavigation` / `shellTarget` (Slice 02) : ce que dessine et ouvre le
     shell à six catégories — les sections enregistrées, rien d'autre. */
(function(root){
  'use strict';

  const freezeAll=list=>Object.freeze(list.map(item=>Object.freeze(item)));

  /* Ordre canonique = ordre d'affichage. Les identifiants sont stables (ASCII) ;
     les libellés ne sont que de la présentation. `notice` (facultatif) : l'avis montré sous l'intro de la catégorie. */
  const CATEGORIES=freezeAll([
    /* Libellés et descriptions du hub de cartes (2026-10-23) ; les identifiants n'ont pas changé. */
    {id:'voice_audio',label:'Personnalisation',description:'Thème, apparence, voix et comportement général.'},
    /* `agents_models` : « Architecture & Agents » (jarvis-architecture-agents-settings-editor, D01 et C2) ; deux sections,
       Architecture et Sous-agents, qui sont ses deux onglets internes (`docs/settings/architecture-agents.md`). */
    {id:'agents_models',label:'Architecture & Agents',description:'Architecture des cerveaux, délégation et modèles des sous-agents.'},
    {id:'memory_knowledge',label:'Mémoire & Connaissances',description:'Mémoire, rappel et bases de connaissances.'},
    {id:'interface_interactions',label:'Interface & Interactions',description:'Interface, modes d’interaction, entrées et sorties.'},
    {id:'connections',label:'Plugins & MCP',description:'Extensions, outils externes et connecteurs.'},
    {id:'advanced_diagnostics',label:'Avancé & Diagnostics',description:'Paramètres avancés, journaux et outils de diagnostic.',
      notice:'Outils d’opérateur : architecture, prompts, runtime, état constaté et essais de JARVIS. Les réglages du quotidien sont dans les autres catégories.'},
  ]);
  const CATEGORY_IDS=Object.freeze(CATEGORIES.map(c=>c.id));

  /* Groupes déclarés d'une catégorie (Slice 08, `docs/settings/INDEX.md` § Avancé) : ordre d'affichage, libellé et ce
     qui y va. Une catégorie qui déclare des groupes exige de chaque section un `group` parmi eux ; une catégorie qui
     n'en déclare pas refuse tout `group`. Seule Avancé & diagnostic en déclare : c'est une boîte à outils structurée,
     pas un fourre-tout. */
  const CATEGORY_GROUPS=Object.freeze({
    advanced_diagnostics:freezeAll([
      {id:'architecture_compat',label:'Architecture & compatibilité',description:'Architecture vocale, piles historiques, invariants et réglage fin.'},
      {id:'prompts',label:'Prompts & instructions',description:'Atelier des prompts et aperçu du prompt effectif.'},
      {id:'runtime_cli',label:'Runtime & CLI',description:'Commande, chemin, permissions et routage bas niveau.'},
      {id:'diagnostics',label:'Diagnostics',description:'État constaté, en lecture seule.'},
      {id:'labs',label:'Labs & outils de test',description:'Porte de test, essais, enregistrements et outils expérimentaux.'},
    ]),
  });
  const NO_GROUPS=Object.freeze([]);
  function groupsOf(categoryId){return Object.prototype.hasOwnProperty.call(CATEGORY_GROUPS,categoryId)?CATEGORY_GROUPS[categoryId]:NO_GROUPS}

  /* Catégorie par défaut du shell : celle qu'ouvre une cible inconnue (`openSettingsTab`, Slice 09). */
  const DEFAULT_CATEGORY=CATEGORY_IDS[0];

  /* Alias hérités encore servis (Slice 09) : ancien identifiant d'onglet → catégorie et section. Donnée explicite, la
     seule : aucune section ne déclare d'alias et aucune condition n'en devine. Un alias ne reste ici que tant qu'un
     appelant du dépôt ou un document durable s'en sert ; table et appelants : `docs/legacy/settings-tab-aliases.md`.
     - `memory` : bouton Réglages du Memory Center (`selectTab('memory')`, `control_center_memory.js`).
     - `main_agent`, `subagent_models` : sections retirées par la Slice 07 de jarvis-architecture-agents-settings-editor
       (liens enregistrés, tests et documents durables). Le CLI et le modèle de Core se règlent dans la fenêtre du
       cerveau Core, onglet Architecture ; le modèle de chaque rôle dans l'onglet Sous-agents (le mode Auto / Dupliqué et
       l'inventaire comparatif sont dans Avancé › Runtime & CLI). */
  const LEGACY_TAB_ALIASES=Object.freeze({
    memory:Object.freeze({category:'memory_knowledge',section:'recall'}),
    main_agent:Object.freeze({category:'agents_models',section:'architecture'}),
    subagent_models:Object.freeze({category:'agents_models',section:'subagents'}),
  });

  const ERROR_CODES=Object.freeze({
    invalid:'settings_section_invalid',
    unknownCategory:'settings_category_unknown',
    duplicate:'settings_section_duplicate',
    alias:'settings_alias_conflict',
    group:'settings_section_group',
  });
  const SAVE_POLICIES=Object.freeze(['footer','self','readonly']);
  const APPLIES=Object.freeze(['immediate','next_turn','next_core_start','next_voice_start']);
  const ID=/^[a-z][a-z0-9_]{0,63}$/;
  const KEYS=new Set(['id','category','label','description','order','group','mount','destroy','save','isDirty','advanced','applies']);

  function fail(code,message){const error=new Error(message);error.code=code;error.name='SettingsRegistryError';return error}
  const own=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);

  function category(id){return CATEGORIES.find(c=>c.id===id)||null}

  /* Catégorie voisine dans l'ordre canonique, en boucle : ce que font
     `ui_tab_next` / `ui_tab_prev` dans le shell à six catégories (Slice 02). */
  function cycleCategory(id,step){
    const index=CATEGORY_IDS.indexOf(id),delta=step<0?-1:1;
    if(index<0)return CATEGORY_IDS[delta>0?0:CATEGORY_IDS.length-1];
    return CATEGORY_IDS[(index+delta+CATEGORY_IDS.length)%CATEGORY_IDS.length];
  }

  function legacyAlias(tabId){return typeof tabId==='string'&&own(LEGACY_TAB_ALIASES,tabId)?LEGACY_TAB_ALIASES[tabId]:null}

  function validate(spec){
    if(!spec||typeof spec!=='object'||Array.isArray(spec))throw fail(ERROR_CODES.invalid,'Section de réglages : description objet attendue.');
    const where=typeof spec.id==='string'?spec.id:'?';
    for(const key of Object.keys(spec))
      if(!KEYS.has(key))throw fail(ERROR_CODES.invalid,`Section ${where} : champ inconnu « ${key} ».`);
    if(typeof spec.id!=='string'||!ID.test(spec.id))throw fail(ERROR_CODES.invalid,`Section ${where} : identifiant ASCII snake_case attendu.`);
    if(CATEGORY_IDS.includes(spec.id))throw fail(ERROR_CODES.invalid,`Section ${spec.id} : un identifiant de catégorie n’est pas un identifiant de section.`);
    if(!CATEGORY_IDS.includes(spec.category))throw fail(ERROR_CODES.unknownCategory,`Section ${spec.id} : catégorie inconnue « ${spec.category} ». Les six catégories sont fixes : ${CATEGORY_IDS.join(', ')}.`);
    if(typeof spec.label!=='string'||!spec.label.trim())throw fail(ERROR_CODES.invalid,`Section ${spec.id} : libellé attendu.`);
    if(spec.description!==undefined&&typeof spec.description!=='string')throw fail(ERROR_CODES.invalid,`Section ${spec.id} : description texte attendue.`);
    if(spec.order!==undefined&&!Number.isFinite(spec.order))throw fail(ERROR_CODES.invalid,`Section ${spec.id} : ordre numérique attendu.`);
    if(spec.group!==undefined&&(typeof spec.group!=='string'||!ID.test(spec.group)))throw fail(ERROR_CODES.invalid,`Section ${spec.id} : groupe ASCII snake_case attendu.`);
    const groups=groupsOf(spec.category);
    if(groups.length&&!groups.some(g=>g.id===spec.group))
      throw fail(ERROR_CODES.group,`Section ${spec.id} : groupe attendu parmi ${groups.map(g=>g.id).join(', ')} (catégorie ${spec.category}).`);
    if(!groups.length&&spec.group!==undefined)
      throw fail(ERROR_CODES.group,`Section ${spec.id} : la catégorie ${spec.category} ne déclare aucun groupe.`);
    if(typeof spec.mount!=='function')throw fail(ERROR_CODES.invalid,`Section ${spec.id} : fonction mount attendue.`);
    if(spec.destroy!==undefined&&typeof spec.destroy!=='function')throw fail(ERROR_CODES.invalid,`Section ${spec.id} : destroy doit être une fonction.`);
    if(!SAVE_POLICIES.includes(spec.save))throw fail(ERROR_CODES.invalid,`Section ${spec.id} : politique d’enregistrement attendue (${SAVE_POLICIES.join(', ')}).`);
    if(spec.isDirty!==undefined&&typeof spec.isDirty!=='function')throw fail(ERROR_CODES.invalid,`Section ${spec.id} : isDirty doit être une fonction.`);
    if(spec.save==='readonly'&&spec.isDirty)throw fail(ERROR_CODES.invalid,`Section ${spec.id} : une section en lecture seule n’a pas de brouillon.`);
    if(spec.advanced!==undefined&&typeof spec.advanced!=='boolean')throw fail(ERROR_CODES.invalid,`Section ${spec.id} : advanced booléen attendu.`);
    if(spec.applies!==undefined&&!APPLIES.includes(spec.applies))throw fail(ERROR_CODES.invalid,`Section ${spec.id} : applies attendu parmi ${APPLIES.join(', ')}.`);
  }

  function createRegistry(){
    const sections=new Map();

    function register(spec){
      validate(spec);
      const id=spec.id;
      if(sections.has(id))throw fail(ERROR_CODES.duplicate,`Section ${id} déjà enregistrée (${sections.get(id).category}).`);
      /* Un ID de section qui serait aussi un alias hérité masquerait l'alias : refusé. */
      if(legacyAlias(id))throw fail(ERROR_CODES.alias,`Section ${id} : identifiant déjà pris comme alias hérité (LEGACY_TAB_ALIASES).`);
      const entry=Object.freeze({id,category:spec.category,label:spec.label,description:spec.description||'',
        order:spec.order===undefined?0:spec.order,group:spec.group||null,mount:spec.mount,destroy:spec.destroy||null,
        save:spec.save,isDirty:spec.isDirty||null,advanced:spec.advanced===true,applies:spec.applies||null,
        seq:sections.size});
      sections.set(id,entry);
      return entry;
    }

    /* Ordre stable : groupe déclaré (ordre de `CATEGORY_GROUPS`), puis `order`, puis ordre d'enregistrement. */
    const groupRank=s=>{const at=groupsOf(s.category).findIndex(g=>g.id===s.group);return at<0?0:at};
    const byOrder=(a,b)=>groupRank(a)-groupRank(b)||a.order-b.order||a.seq-b.seq;
    function sectionsOf(categoryId){
      if(!CATEGORY_IDS.includes(categoryId))throw fail(ERROR_CODES.unknownCategory,`Catégorie inconnue « ${categoryId} ».`);
      return [...sections.values()].filter(s=>s.category===categoryId).sort(byOrder);
    }

    /* Une cible (catégorie, section ou alias hérité de `LEGACY_TAB_ALIASES`) → `{category, section, source}` ;
       `section` vaut `null` quand seule la catégorie est connue (page d'accueil de la catégorie, ou section cible d'un
       alias pas enregistrée). Une cible inconnue → `null`, à signaler par l'appelant. */
    function resolve(target){
      if(typeof target!=='string')return null;
      if(CATEGORY_IDS.includes(target))return {category:target,section:null,source:'category'};
      if(sections.has(target))return {category:sections.get(target).category,section:target,source:'section'};
      const legacy=legacyAlias(target);
      if(legacy){
        const ok=sections.has(legacy.section)&&sections.get(legacy.section).category===legacy.category;
        return {category:legacy.category,section:ok?legacy.section:null,source:'alias'};
      }
      return null;
    }

    function snapshot(){
      return CATEGORIES.map(c=>({id:c.id,label:c.label,groups:groupsOf(c.id).map(g=>g.id),sections:sectionsOf(c.id).map(s=>({id:s.id,label:s.label,group:s.group,order:s.order,save:s.save,advanced:s.advanced}))}));
    }

    return Object.freeze({register,section:id=>sections.get(id)||null,sections:sectionsOf,resolve,snapshot,
      categories:()=>CATEGORIES});
  }

  /* --- Navigation du shell à six catégories (Slice 02) ---------------------
     Ce que le shell dessine : pour chaque catégorie, ses sections enregistrées dans l'ordre du registre
     (`registry.sections`). Depuis la Slice 09 il n'y a plus d'onglet hérité ni de lien « encore dans ». */
  function shellNavigation(registry){
    const categories=CATEGORIES.map(c=>({id:c.id,label:c.label,description:c.description,notice:c.notice||'',groups:groupsOf(c.id),
      items:(registry?registry.sections(c.id):[]).map(s=>({kind:'section',id:s.id,label:s.label,save:s.save,advanced:s.advanced,group:s.group}))}));
    return {categories};
  }

  /* Une cible (catégorie, section, alias hérité) → `{category, item}` dans `nav` (`shellNavigation`). `item` vaut
     `null` pour une catégorie seule : le shell choisit alors l'entrée retenue ou la première. `null` si la cible est
     inconnue. */
  function shellTarget(target,nav,registry){
    if(typeof target!=='string'||!nav)return null;
    if(CATEGORY_IDS.includes(target))return {category:target,item:null};
    const hit=registry?registry.resolve(target):null;
    if(!hit)return null;
    for(const c of nav.categories){const item=hit.section&&c.items.find(i=>i.kind==='section'&&i.id===hit.section);if(item)return {category:c.id,item}}
    return {category:hit.category,item:null};
  }

  const api=Object.freeze({CATEGORIES,CATEGORY_IDS,CATEGORY_GROUPS,DEFAULT_CATEGORY,LEGACY_TAB_ALIASES,ERROR_CODES,SAVE_POLICIES,APPLIES,
    category,groups:groupsOf,cycleCategory,legacyAlias,createRegistry,shellNavigation,shellTarget,
    /* L'instance de la page, où les modules enregistrent leurs sections. */
    page:createRegistry()});
  root.JarvisSettingsRegistry=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
