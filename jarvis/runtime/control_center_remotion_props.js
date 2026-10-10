/* Construction et validation des `inputProps` d'une scène Remotion, AVANT qu'elles traversent vers le bac à sable (handoff
   jarvis-remotion-presentation-integration, Slice 13 ; `docs/remotion-isolation.md` § 12, `docs/presentation-studio.md` >
   *Typed variables and fast edits*).

   Rejoue, côté navigateur, `jarvis/domain/remotion_controls.py::build_input_props` : même contrat (`input_contract` du descripteur de
   lecture : les schémas du manifeste moins ce que Remotion ne porte pas, liste `withheld`), mêmes bornes (type, min/max, longueur,
   énumération, motif, taille 64 Kio, profondeur 8, 2 000 nœuds), même résultat. La parité est testée sur un tableau de cas commun
   (`tests/fixtures/remotion_input_props_cases.json`) joué par les deux langages.

   Ce que ce module REFUSE (jamais « réparé » en silence) : une fonction, un symbole, un `undefined`, un nombre non fini, un objet
   qui n'est pas un objet simple (prototype autre que `Object.prototype` / `null`, accesseur), un nom `__proto__` / `constructor` /
   `prototype` à toute profondeur, une clé que le contrat ne connaît pas, une valeur hors bornes. Le résultat est une COPIE fraîche
   (`JSON.parse(JSON.stringify(...))`) : l'appelant ne garde aucune référence vers ce que le bac à sable reçoit.

   Module PUR : aucune E/S, aucune minuterie, aucun état. */
(function(root){
  'use strict';
  const MAX_INPUT_BYTES=64*1024;
  const MAX_DEPTH=8;
  const MAX_NODES=2000;
  const DATA_KEY='data';
  const DEFAULT_STRING_LENGTH=200;
  const DEFAULT_TEXT_LENGTH=2000;
  const MAX_ARRAY_ITEMS=256;
  const MAX_URL_CHARS=2048;
  const MAX_PROBLEMS=8;
  const UNSAFE=new Set(['__proto__','constructor','prototype']);
  const COLOR=/^#[0-9a-fA-F]{6}$/;

  const hasOwn=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);
  function plain(value){
    if(value===null||typeof value!=='object'||Array.isArray(value))return false;
    const proto=Object.getPrototypeOf(value);
    return proto===Object.prototype||proto===null;
  }
  function preview(value){let text;try{text=JSON.stringify(value)}catch(_error){text=String(value)}return String(text).slice(0,40)}
  function singleLine(text){return !/[\u0000-\u001f\u007f]/.test(text)}
  function multiLine(text){return !/[\u0000-\u0008\u000b-\u001f\u007f]/.test(text)}
  /* Python mesure en points de code ; on fait pareil (une paire de substituts compte pour 1). */
  function length(text){let n=0;for(const _c of text)n++;return n}

  /* Forme : JSON simple, profondeur, nombre de nœuds, noms réservés. Retourne le premier défaut, ou null. */
  function shapeProblem(value,depth,counter){
    counter.n++;
    if(counter.n>MAX_NODES)return `more than ${MAX_NODES} values`;
    if(depth>MAX_DEPTH)return `nesting deeper than ${MAX_DEPTH}`;
    if(value===null||typeof value==='string'||typeof value==='boolean')return null;
    if(typeof value==='number')return Number.isFinite(value)?null:'a number is not finite';
    if(Array.isArray(value)){
      if(Object.getPrototypeOf(value)!==Array.prototype)return 'an array is not a plain array';
      for(let i=0;i<value.length;i++){
        if(!hasOwn(value,i))return 'an array has a hole';
        const problem=shapeProblem(value[i],depth+1,counter);
        if(problem)return problem;
      }
      return null;
    }
    if(typeof value==='object'){
      if(!plain(value))return 'a value is not a plain object';
      for(const key of Reflect.ownKeys(value)){
        if(typeof key!=='string')return 'an object key is not a string';
        if(UNSAFE.has(key))return `the reserved key '${key}'`;
        const descriptor=Object.getOwnPropertyDescriptor(value,key);
        if(!descriptor||descriptor.get||descriptor.set)return 'an object holds an accessor';
        if(!descriptor.enumerable)continue;
        const problem=shapeProblem(descriptor.value,depth+1,counter);
        if(problem)return problem;
      }
      return null;
    }
    return `a value of type ${typeof value} is not plain JSON`;
  }

  function clone(value){return JSON.parse(JSON.stringify(value))}

  /* Valide `value` contre le noeud `schema` (forme du manifeste) ; complète les défauts ; pousse les erreurs. Retourne la valeur. */
  function validate(schema,value,path,errors){
    const type=schema.type;
    if(type==='object'){
      if(!plain(value)){errors.push(`${path}: expected an object`);return value}
      const properties=schema.properties||{};
      const unknown=Object.keys(value).filter((key)=>!hasOwn(properties,key));
      if(unknown.length)errors.push(`${path}: unknown keys ${JSON.stringify(unknown.slice(0,5).map((k)=>k.slice(0,40)))}`);
      const out={};
      const required=schema.required||[];
      for(const name of Object.keys(properties)){
        const child=properties[name];
        if(hasOwn(value,name))out[name]=validate(child,value[name],`${path}.${name}`,errors);
        else if(hasOwn(child,'default'))out[name]=clone(child.default);
        else if(required.includes(name))errors.push(`${path}.${name}: is required`);
      }
      return out;
    }
    if(type==='array'){
      if(!Array.isArray(value)){errors.push(`${path}: expected an array`);return value}
      const maxItems=schema.max_items!==undefined?schema.max_items:MAX_ARRAY_ITEMS;
      if(value.length>maxItems){errors.push(`${path}: holds ${value.length} items, at most ${maxItems}`);return value}
      if(value.length<(schema.min_items||0))errors.push(`${path}: holds ${value.length} items, at least ${schema.min_items}`);
      return value.map((item,index)=>validate(schema.items,item,`${path}[${index}]`,errors));
    }
    if(type==='string'||type==='text'||type==='color'||type==='enum'||type==='url'){
      if(typeof value!=='string'){errors.push(`${path}: expected a string (${type})`);return value}
      if(type==='string'){
        const limit=schema.max_length||DEFAULT_STRING_LENGTH;
        if(length(value)>limit)errors.push(`${path}: exceeds ${limit} characters`);
        else if(!singleLine(value))errors.push(`${path}: must be a single line without control characters`);
        else if(schema.pattern!==undefined){
          let ok=false;
          try{ok=new RegExp(schema.pattern,'u').test(value)}catch(_error){ok=false}
          if(!ok)errors.push(`${path}: does not match ${String(schema.pattern).slice(0,60)}`);
        }
      }else if(type==='text'){
        const limit=schema.max_length||DEFAULT_TEXT_LENGTH;
        if(length(value)>limit)errors.push(`${path}: exceeds ${limit} characters`);
        else if(!multiLine(value))errors.push(`${path}: must not contain control characters other than newline and tab`);
      }else if(type==='color'){
        if(!COLOR.test(value))errors.push(`${path}: must be a #rrggbb colour, got ${preview(value)}`);
      }else if(type==='enum'){
        if(!(schema.values||[]).includes(value))errors.push(`${path}: must be one of ${JSON.stringify((schema.values||[]).slice(0,8))}, got ${preview(value)}`);
      }else{
        let ok=value.length>0&&value.length<=MAX_URL_CHARS&&!/[\s\u0000-\u001f]/.test(value);
        if(ok){try{const url=new URL(value);ok=(url.protocol==='http:'||url.protocol==='https:')&&!!url.host}catch(_error){ok=false}}
        if(!ok)errors.push(`${path}: must be an http(s) URL of at most ${MAX_URL_CHARS} characters`);
      }
      return value;
    }
    if(type==='boolean'){
      if(typeof value!=='boolean')errors.push(`${path}: expected a boolean`);
      return value;
    }
    if(typeof value!=='number'||!Number.isFinite(value)||(type==='integer'&&!Number.isInteger(value))){
      errors.push(`${path}: expected a finite ${type}, got ${preview(value)}`);return value;
    }
    if(schema.min!==undefined&&value<schema.min)errors.push(`${path}: must be at least ${schema.min}`);
    else if(schema.max!==undefined&&value>schema.max)errors.push(`${path}: must be at most ${schema.max}`);
    return value;
  }

  /* Retire (et dit) les chemins que le contrat a retirés ; `[]` dans un chemin = un élément de liste. */
  function dropWithheld(value,path,withheld,dropped){
    if(Array.isArray(value))return value.map((item)=>dropWithheld(item,`${path}[]`,withheld,dropped));
    if(value!==null&&typeof value==='object'){
      const out={};
      for(const key of Object.keys(value)){
        const child=`${path}.${key}`;
        if(withheld.has(child)){dropped.push(child);continue}
        out[key]=dropWithheld(value[key],child,withheld,dropped);
      }
      return out;
    }
    return value;
  }

  const fail=(problems,dropped)=>({ok:false,inputProps:{},problems:problems.slice(0,MAX_PROBLEMS),dropped:dropped||[]});

  /* `contract` : `descriptor.input_contract`. Retourne {ok, inputProps, problems, dropped}. Ne lève jamais sur une valeur. */
  function buildInputProps(contract,props,data){
    try{
      if(!contract||!plain(contract)||!plain(contract.props)||!plain(contract.data)||!Array.isArray(contract.withheld))
        return fail(['the scene has no input contract: nothing is sent to the sandbox']);
      props=props===undefined||props===null?{}:props;
      data=data===undefined||data===null?{}:data;
      if(!plain(props)||!plain(data))return fail(['props and data must be objects']);
      const problems=[];
      for(const [label,value] of [['props',props],['data',data]]){
        const problem=shapeProblem(value,0,{n:0});
        if(problem)problems.push(`${label}: ${problem}`);
      }
      if(problems.length)return fail(problems);
      const withheld=new Set(contract.withheld.map((item)=>item.path));
      const dropped=[];
      const out={};
      for(const [rootName,values] of [['props',props],['data',data]]){
        out[rootName]=validate(contract[rootName],dropWithheld(values,rootName,withheld,dropped),rootName,problems);
      }
      if(problems.length)return fail(problems,dropped);
      const inputProps=Object.assign({},out.props);
      if(contract.carries_data===true)inputProps[DATA_KEY]=out.data;
      const text=JSON.stringify(inputProps);
      const size=new TextEncoder().encode(text).length;
      if(size>MAX_INPUT_BYTES)return fail([`inputProps are ${size} bytes, at most ${MAX_INPUT_BYTES}`],dropped);
      return {ok:true,inputProps:JSON.parse(text),problems:[],dropped};
    }catch(error){
      return fail([`inputProps refused: ${error&&error.message?error.message:String(error)}`]);
    }
  }

  const api=Object.freeze({MAX_INPUT_BYTES,MAX_DEPTH,MAX_NODES,DATA_KEY,buildInputProps});
  root.RemotionInputProps=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
