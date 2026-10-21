/* Registre canonique des Réglages (jarvis-settings-ui-reorganization, Slice 01).

   Contrat : `docs/settings/navigation-registry.md`. Module pur, sans DOM, sans
   réseau, sans stockage : il ne lit ni n'écrit aucun réglage.

   - Exactement six catégories, figées ici et nulle part ailleurs. Aucun appel
     ne peut en ajouter une septième : un module enregistre des SECTIONS dans
     une de ces six catégories, il ne touche plus la navigation de premier niveau.
   - `register` refuse de façon déterministe (exception portant un `code`
     stable) une section invalide, un identifiant en double ou une catégorie
     inconnue.
   - `LEGACY_TAB_ALIASES` dit où va chaque identifiant d'onglet actuel
     (`openSettingsTab('voice')`, roue Jarvis, `selectTab('memory')`…).
     Temporaire : retiré par la Slice 09 quand plus aucun appelant ni document
     durable ne s'en sert.
   - `legacyTabFor` / `navigationFromLegacyTabs` : adaptateur de migration vers
     les onglets hérités (`TABS` de `control_center.html`).
   - `shellNavigation` / `shellTarget` (Slice 02) : ce que dessine et ouvre le
     shell à six catégories — sections enregistrées, puis onglets hérités encore
     montés comme sections temporaires. Les onglets hérités disparaissent avec la
     Slice 09. */
(function(root){
  'use strict';

  const freezeAll=list=>Object.freeze(list.map(item=>Object.freeze(item)));

  /* Ordre canonique = ordre d'affichage. Les identifiants sont stables (ASCII) ;
     les libellés ne sont que de la présentation. */
  const CATEGORIES=freezeAll([
    {id:'voice_audio',label:'Voix & audio',description:'Conversation, voix, micro et mot d’éveil.'},
    {id:'agents_models',label:'Agents & modèles',description:'Agent principal, modèles et sous-agents.'},
    {id:'memory_knowledge',label:'Mémoire & connaissances',description:'Rappel, recherche, consolidation et sources.'},
    {id:'interface_interactions',label:'Interface & interactions',description:'Thème, scène, raccourcis et Bare Hands.'},
    {id:'connections',label:'Connexions',description:'Fournisseurs et identifiants enregistrés.'},
    {id:'advanced_diagnostics',label:'Avancé & diagnostic',description:'Architecture, prompts, diagnostics et essais.'},
  ]);
  const CATEGORY_IDS=Object.freeze(CATEGORIES.map(c=>c.id));

  /* Destination de chaque identifiant d'onglet actuel : catégorie et section
     cible principales (`docs/07-target-settings-map.md`), plus les autres
     destinations du contenu éclaté (`also`). `tab` : onglet du shell actuel qui
     sert un identifiant déjà redirigé (`routing` → `cli`, contrat de
     jarvis-settings-model-catalog-ux). */
  const LEGACY_TAB_ALIASES=Object.freeze({
    /* `also` porte aussi les autres sections cibles du contenu éclaté (QA Slice 01). Depuis la
       Slice 03, `voice` n'est plus un onglet : ces sections sont enregistrées et
       `openSettingsTab('voice_output')` ouvre la section elle-même. */
    voice:Object.freeze({category:'voice_audio',section:'conversation',
      also:freezeAll([{category:'voice_audio',section:'voice_output'},{category:'voice_audio',section:'microphone_sound'},
        {category:'voice_audio',section:'turns_interruptions'},
        {category:'advanced_diagnostics',section:'architecture_compat'},{category:'advanced_diagnostics',section:'diagnostics'}])}),
    wakeword:Object.freeze({category:'voice_audio',section:'wake_word',
      also:freezeAll([{category:'advanced_diagnostics',section:'diagnostics'}])}),
    prompts:Object.freeze({category:'advanced_diagnostics',section:'prompts',also:freezeAll([])}),
    /* Slice 04 : `cli` et `subagents` ne sont plus des onglets. Le mode et le catalogue des sous-agents vont dans
       `subagent_models` ; la promotion des Work Methods dans `work_methods` (groupe Labs d'Avancé). */
    cli:Object.freeze({category:'agents_models',section:'main_agent',
      also:freezeAll([{category:'agents_models',section:'agent_behavior'},{category:'agents_models',section:'subagent_models'},
        {category:'advanced_diagnostics',section:'runtime_cli'}])}),
    routing:Object.freeze({category:'advanced_diagnostics',section:'runtime_cli',tab:'cli',also:freezeAll([])}),
    keys:Object.freeze({category:'connections',section:'providers',also:freezeAll([])}),
    shortcuts:Object.freeze({category:'interface_interactions',section:'shortcuts',also:freezeAll([])}),
    memory:Object.freeze({category:'memory_knowledge',section:'recall',
      also:freezeAll([{category:'memory_knowledge',section:'semantic_retrieval'},{category:'memory_knowledge',section:'consolidation'},
        {category:'memory_knowledge',section:'knowledge_sources'},
        {category:'memory_knowledge',section:'memory_center'},{category:'advanced_diagnostics',section:'diagnostics'}])}),
    subagents:Object.freeze({category:'agents_models',section:'subagents',
      also:freezeAll([{category:'advanced_diagnostics',section:'work_methods'}])}),
    appearance:Object.freeze({category:'interface_interactions',section:'theme_scene',also:freezeAll([])}),
    /* Onglet partagé par Bare Hands et `control_center_scene_settings.js`. Son
       nom et son contenu d'opérateur (porte de test de la scène, enregistrement,
       banc d'essai) vont dans Labs ; les préférences ordinaires de Bare Hands
       vont dans Interface, atteintes par `LEGACY_ANCHORS`. */
    experimental:Object.freeze({category:'advanced_diagnostics',section:'labs',
      also:freezeAll([{category:'interface_interactions',section:'bare_hands'}])}),
  });

  /* Ancres internes déjà publiées (`JarvisBarehands.showSettings(section)`,
     clés de `SECTION` dans `control_center_barehands.js`) : où chacune doit
     atterrir une fois l'onglet `experimental` démonté (Slices 06/08). */
  const LEGACY_ANCHORS=Object.freeze({
    barehandsSettings:Object.freeze({category:'interface_interactions',section:'bare_hands'}),
    barehandsCalibration:Object.freeze({category:'interface_interactions',section:'bare_hands'}),
    barehandsRecord:Object.freeze({category:'advanced_diagnostics',section:'labs'}),
    barehandsBenchmarkSection:Object.freeze({category:'advanced_diagnostics',section:'labs'}),
  });

  const ERROR_CODES=Object.freeze({
    invalid:'settings_section_invalid',
    unknownCategory:'settings_category_unknown',
    duplicate:'settings_section_duplicate',
    alias:'settings_alias_conflict',
  });
  const SAVE_POLICIES=Object.freeze(['footer','self','readonly']);
  const APPLIES=Object.freeze(['immediate','next_turn','next_core_start','next_voice_start']);
  const ID=/^[a-z][a-z0-9_]{0,63}$/;
  const ALIAS=/^[A-Za-z][A-Za-z0-9_]{0,63}$/;
  const KEYS=new Set(['id','category','label','description','order','group','mount','destroy','save','isDirty','advanced','applies','aliases']);

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
    if(typeof spec.mount!=='function')throw fail(ERROR_CODES.invalid,`Section ${spec.id} : fonction mount attendue.`);
    if(spec.destroy!==undefined&&typeof spec.destroy!=='function')throw fail(ERROR_CODES.invalid,`Section ${spec.id} : destroy doit être une fonction.`);
    if(!SAVE_POLICIES.includes(spec.save))throw fail(ERROR_CODES.invalid,`Section ${spec.id} : politique d’enregistrement attendue (${SAVE_POLICIES.join(', ')}).`);
    if(spec.isDirty!==undefined&&typeof spec.isDirty!=='function')throw fail(ERROR_CODES.invalid,`Section ${spec.id} : isDirty doit être une fonction.`);
    if(spec.save==='readonly'&&spec.isDirty)throw fail(ERROR_CODES.invalid,`Section ${spec.id} : une section en lecture seule n’a pas de brouillon.`);
    if(spec.advanced!==undefined&&typeof spec.advanced!=='boolean')throw fail(ERROR_CODES.invalid,`Section ${spec.id} : advanced booléen attendu.`);
    if(spec.applies!==undefined&&!APPLIES.includes(spec.applies))throw fail(ERROR_CODES.invalid,`Section ${spec.id} : applies attendu parmi ${APPLIES.join(', ')}.`);
    if(spec.aliases!==undefined&&(!Array.isArray(spec.aliases)||spec.aliases.some(a=>typeof a!=='string'||!ALIAS.test(a))))
      throw fail(ERROR_CODES.invalid,`Section ${spec.id} : aliases = liste d’identifiants attendue.`);
  }

  function createRegistry(){
    const sections=new Map(),aliases=new Map();

    function register(spec){
      validate(spec);
      const id=spec.id;
      if(sections.has(id))throw fail(ERROR_CODES.duplicate,`Section ${id} déjà enregistrée (${sections.get(id).category}).`);
      if(aliases.has(id))throw fail(ERROR_CODES.duplicate,`Section ${id} : identifiant déjà pris comme alias de ${aliases.get(id)}.`);
      const list=[...new Set(spec.aliases||[])];
      for(const alias of list){
        if(CATEGORY_IDS.includes(alias)||sections.has(alias)||alias===id)throw fail(ERROR_CODES.alias,`Section ${id} : l’alias ${alias} est déjà un identifiant canonique.`);
        if(aliases.has(alias))throw fail(ERROR_CODES.alias,`Section ${id} : l’alias ${alias} appartient déjà à ${aliases.get(alias)}.`);
        const legacy=legacyAlias(alias);
        if(legacy&&(legacy.category!==spec.category||legacy.section!==id))
          throw fail(ERROR_CODES.alias,`Section ${id} : l’alias ${alias} est déclaré vers ${legacy.category}/${legacy.section} dans LEGACY_TAB_ALIASES.`);
      }
      const entry=Object.freeze({id,category:spec.category,label:spec.label,description:spec.description||'',
        order:spec.order===undefined?0:spec.order,group:spec.group||null,mount:spec.mount,destroy:spec.destroy||null,
        save:spec.save,isDirty:spec.isDirty||null,advanced:spec.advanced===true,applies:spec.applies||null,
        aliases:Object.freeze(list),seq:sections.size});
      sections.set(id,entry);
      for(const alias of list)aliases.set(alias,id);
      return entry;
    }

    const byOrder=(a,b)=>a.order-b.order||a.seq-b.seq;
    function sectionsOf(categoryId){
      if(!CATEGORY_IDS.includes(categoryId))throw fail(ERROR_CODES.unknownCategory,`Catégorie inconnue « ${categoryId} ».`);
      return [...sections.values()].filter(s=>s.category===categoryId).sort(byOrder);
    }

    /* Une cible (catégorie, section, alias de section ou identifiant d'onglet
       hérité) → `{category, section, source}` ; `section` vaut `null` quand
       seule la catégorie est connue (page d'accueil de la catégorie). Une
       cible inconnue → `null`, à signaler par l'appelant. */
    function resolve(target){
      if(typeof target!=='string')return null;
      if(CATEGORY_IDS.includes(target))return {category:target,section:null,source:'category'};
      if(sections.has(target))return {category:sections.get(target).category,section:target,source:'section'};
      if(aliases.has(target)){const id=aliases.get(target);return {category:sections.get(id).category,section:id,source:'section_alias'}}
      const legacy=legacyAlias(target)||(own(LEGACY_ANCHORS,target)?LEGACY_ANCHORS[target]:null);
      if(legacy){
        const ok=sections.has(legacy.section)&&sections.get(legacy.section).category===legacy.category;
        return {category:legacy.category,section:ok?legacy.section:null,source:legacyAlias(target)?'legacy_tab':'legacy_anchor'};
      }
      return null;
    }

    function snapshot(){
      return CATEGORIES.map(c=>({id:c.id,label:c.label,sections:sectionsOf(c.id).map(s=>({id:s.id,label:s.label,group:s.group,order:s.order,save:s.save,advanced:s.advanced}))}));
    }

    return Object.freeze({register,section:id=>sections.get(id)||null,sections:sectionsOf,resolve,snapshot,
      categories:()=>CATEGORIES});
  }

  /* --- Adaptateur de migration vers les onglets hérités (retiré par la Slice 09) ---
     `tabs` est le `TABS` vivant de la page (base + onglets injectés). */

  /* Onglet du shell actuel à sélectionner pour une cible : l'onglet lui-même,
     sa redirection (`routing` → `cli`), le premier onglet de la catégorie,
     ou l'onglet dont la section cible est demandée. `null` si rien ne sert. */
  function legacyTabFor(target,tabs){
    if(typeof target!=='string'||!Array.isArray(tabs))return null;
    const ids=tabs.map(t=>t&&t.id);
    if(ids.includes(target))return target;
    const legacy=legacyAlias(target);
    if(legacy&&legacy.tab&&ids.includes(legacy.tab))return legacy.tab;
    const anchor=own(LEGACY_ANCHORS,target)?LEGACY_ANCHORS[target]:null;
    if(anchor)return ids.includes('experimental')?'experimental':null;
    if(CATEGORY_IDS.includes(target))return ids.find(id=>{const a=legacyAlias(id);return a&&a.category===target})||null;
    /* Section cible : d'abord l'onglet dont c'est la destination principale,
       puis celui qui en porte une partie (`also`). */
    const entries=Object.entries(LEGACY_TAB_ALIASES);
    const served=match=>entries.filter(([,a])=>match(a)).map(([id,a])=>a.tab||id).find(id=>ids.includes(id));
    return served(a=>a.section===target)||served(a=>a.also.some(d=>d.section===target))||null;
  }

  /* Les onglets actuels rangés sous les six catégories (ordre canonique des
     catégories, ordre de `TABS` dans chacune). Un onglet sans alias déclaré
     est rendu à part (`unassigned`) : c'est un module qui a ajouté un onglet
     de premier niveau sans passer par le registre. */
  function navigationFromLegacyTabs(tabs){
    const list=Array.isArray(tabs)?tabs:[];
    const unassigned=list.filter(t=>!legacyAlias(t&&t.id)).map(t=>t&&t.id);
    return {categories:CATEGORIES.map(c=>({id:c.id,label:c.label,
      tabs:list.filter(t=>{const a=legacyAlias(t.id);return a&&a.category===c.id}).map(t=>({id:t.id,label:t.label}))})),unassigned};
  }

  /* --- Navigation du shell à six catégories (Slice 02) ---------------------
     Ce que le shell dessine : pour chaque catégorie, ses entrées dans l'ordre —
     d'abord les sections enregistrées (`registry.sections`), puis les onglets
     hérités qui lui reviennent encore (adaptateur temporaire, Slices 03-08).
     Un onglet hérité disparaît de la navigation dès qu'une section enregistrée
     le déclare en alias (elle le remplace). `related` : les onglets d'autres
     catégories qui portent encore une partie de celle-ci (`also`), proposés
     comme liens tant que leur contenu n'a pas déménagé. Un onglet sans alias
     (`unassigned`) est rangé dans Avancé & diagnostic pour rester atteignable. */
  const UNASSIGNED_HOME='advanced_diagnostics';
  function shellNavigation(tabs,registry){
    const list=(Array.isArray(tabs)?tabs:[]).filter(t=>t&&typeof t.id==='string');
    const claimed=new Set(),sectionsBy={};
    for(const c of CATEGORIES){
      sectionsBy[c.id]=registry?registry.sections(c.id):[];
      for(const s of sectionsBy[c.id])for(const alias of s.aliases)claimed.add(alias);
    }
    const unassigned=list.filter(t=>!legacyAlias(t.id)).map(t=>t.id);
    const home=t=>{const a=legacyAlias(t.id);return a?a.category:UNASSIGNED_HOME};
    const categories=CATEGORIES.map(c=>({id:c.id,label:c.label,description:c.description,
      items:[
        ...sectionsBy[c.id].map(s=>({kind:'section',id:s.id,label:s.label,save:s.save,advanced:s.advanced})),
        ...list.filter(t=>!claimed.has(t.id)&&home(t)===c.id).map(t=>({kind:'tab',id:t.id,label:String(t.label||t.id)})),
      ],
      related:list.filter(t=>{const a=legacyAlias(t.id);return a&&!claimed.has(t.id)&&a.category!==c.id&&a.also.some(d=>d.category===c.id)})
        .map(t=>({id:t.id,label:String(t.label||t.id),category:legacyAlias(t.id).category}))}));
    return {categories,unassigned};
  }

  /* Une cible (catégorie, section, alias, onglet hérité, ancre, section cible
     encore servie par un onglet) → `{category, item}` dans `nav`
     (`shellNavigation`). `item` vaut `null` pour une catégorie seule : le
     shell choisit alors l'entrée retenue ou la première. `null` si rien ne
     sert la cible. Un onglet hérité encore dans la navigation s'ouvre
     lui-même : il ne cède sa place qu'à la section qui le déclare en alias. */
  function shellTarget(target,nav,registry,tabs){
    if(typeof target!=='string'||!nav)return null;
    const find=(kind,id)=>{for(const c of nav.categories){const item=c.items.find(i=>i.kind===kind&&i.id===id);if(item)return {category:c.id,item}}return null};
    if(CATEGORY_IDS.includes(target))return {category:target,item:null};
    const current=find('tab',target);
    if(current)return current;
    const hit=registry?registry.resolve(target):null;
    const section=hit&&hit.section?find('section',hit.section):null;
    if(section)return section;
    const tab=legacyTabFor(target,tabs),served=tab?find('tab',tab):null;
    if(served)return served;
    return hit?{category:hit.category,item:null}:null;
  }

  const api=Object.freeze({CATEGORIES,CATEGORY_IDS,LEGACY_TAB_ALIASES,LEGACY_ANCHORS,ERROR_CODES,SAVE_POLICIES,APPLIES,
    category,cycleCategory,legacyAlias,createRegistry,legacyTabFor,navigationFromLegacyTabs,shellNavigation,shellTarget,
    /* L'instance de la page, où les modules enregistrent leurs sections. */
    page:createRegistry()});
  root.JarvisSettingsRegistry=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
